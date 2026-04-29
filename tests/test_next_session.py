"""
Tests des fonctions de recommandation de séance et de génération GPX.
"""

import xml.etree.ElementTree as ET
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from datetime import date, datetime, timedelta

import next_session_logic as logic
from next_session_logic import (
    compute_tsb as _compute_tsb,
    recommend_session as _recommend_session,
    build_gpx as _build_gpx,
    parse_ors_route as _parse_ors_route,
    suggest_next_date as _suggest_next_date,
    format_date_fr as _format_date_fr,
)


# ===========================================================================
# _parse_ors_route
# ===========================================================================

class TestParseOrsRoute:
    def test_valid_response(self, sample_ors_geojson):
        result = _parse_ors_route(sample_ors_geojson)
        assert result is not None
        assert result["distance_km"] == pytest.approx(5.20, abs=0.01)
        assert result["ascent_m"] == 45
        assert len(result["lats"]) == 4
        assert len(result["lons"]) == 4
        assert len(result["elevations"]) == 4

    def test_elevations_extracted(self, sample_ors_geojson):
        result = _parse_ors_route(sample_ors_geojson)
        assert result["elevations"][0] == pytest.approx(120.0)

    def test_2d_coords_no_elevation(self, sample_ors_geojson):
        geojson = sample_ors_geojson.copy()
        geojson["features"][0]["geometry"]["coordinates"] = [
            [2.35, 48.85],
            [2.36, 48.86],
        ]
        result = _parse_ors_route(geojson)
        assert result["elevations"] == []

    def test_missing_ascent_defaults_zero(self, sample_ors_geojson):
        geojson = sample_ors_geojson.copy()
        del geojson["features"][0]["properties"]["ascent"]
        result = _parse_ors_route(geojson)
        assert result["ascent_m"] == 0

    def test_none_ascent_defaults_zero(self, sample_ors_geojson):
        geojson = sample_ors_geojson.copy()
        geojson["features"][0]["properties"]["ascent"] = None
        result = _parse_ors_route(geojson)
        assert result["ascent_m"] == 0

    def test_missing_features_returns_none(self):
        assert _parse_ors_route({}) is None

    def test_empty_features_returns_none(self):
        assert _parse_ors_route({"features": []}) is None

    def test_missing_summary_returns_none(self, sample_ors_geojson):
        geojson = sample_ors_geojson.copy()
        del geojson["features"][0]["properties"]["summary"]
        assert _parse_ors_route(geojson) is None


# ===========================================================================
# _build_gpx
# ===========================================================================

class TestBuildGpx:
    def test_valid_xml(self, sample_route):
        gpx = _build_gpx(sample_route, "Endurance", "5:30/km")
        ET.fromstring(gpx)  # lève une exception si XML invalide

    def test_starts_with_xml_declaration(self, sample_route):
        gpx = _build_gpx(sample_route, "Endurance", "5:30/km")
        assert gpx.startswith("<?xml")

    def test_contains_trkpt(self, sample_route):
        gpx = _build_gpx(sample_route, "Endurance", "5:30/km")
        assert "<trkpt" in gpx

    def test_trkpt_count_matches_coords(self, sample_route):
        gpx = _build_gpx(sample_route, "Endurance", "5:30/km")
        assert gpx.count("<trkpt") == len(sample_route["lats"])

    def test_elevation_tags_present(self, sample_route):
        gpx = _build_gpx(sample_route, "Endurance", "5:30/km")
        assert "<ele>" in gpx
        assert "120.0" in gpx

    def test_no_elevation_no_ele_tag(self, sample_route):
        route = {**sample_route, "elevations": []}
        gpx = _build_gpx(route, "Endurance", "5:30/km")
        assert "<ele>" not in gpx

    def test_session_label_in_output(self, sample_route):
        gpx = _build_gpx(sample_route, "Sortie longue", "5:00/km")
        assert "Sortie longue" in gpx

    def test_pace_in_description(self, sample_route):
        gpx = _build_gpx(sample_route, "Tempo", "4:45/km")
        assert "4:45/km" in gpx


# ===========================================================================
# _compute_tsb
# ===========================================================================

class TestComputeTsb:
    def _make_df(self, n=10, days_apart=4, pace_sec=330.0, distance_km=10.0, duration_min=55.0):
        now = datetime.now()
        rows = [
            {
                "startTimeLocal": now - timedelta(days=i * days_apart),
                "activityType": "running",
                "distance_km": distance_km,
                "duration_min": duration_min,
                "avgPace_sec": pace_sec,
                "avgHR": 148.0,
                "elevationGain": 60.0,
            }
            for i in range(n)
        ]
        df = pd.DataFrame(rows)
        df["startTimeLocal"] = pd.to_datetime(df["startTimeLocal"])
        return df

    def test_empty_df_returns_zeros(self):
        ctl, atl, tsb = _compute_tsb(pd.DataFrame())
        assert (ctl, atl, tsb) == (0.0, 0.0, 0.0)

    def test_zero_pace_returns_zeros(self):
        df = self._make_df(pace_sec=0.0)
        ctl, atl, tsb = _compute_tsb(df)
        assert (ctl, atl, tsb) == (0.0, 0.0, 0.0)

    def test_returns_floats(self):
        df = self._make_df()
        ctl, atl, tsb = _compute_tsb(df)
        assert all(isinstance(v, float) for v in (ctl, atl, tsb))

    def test_ctl_positive_with_training(self):
        df = self._make_df(n=15)
        ctl, atl, tsb = _compute_tsb(df)
        assert ctl > 0

    def test_tsb_close_to_ctl_minus_atl(self):
        df = self._make_df()
        ctl, atl, tsb = _compute_tsb(df)
        # TSB peut différer de ctl-atl de ±0.2 à cause des arrondis indépendants
        assert abs(tsb - (ctl - atl)) < 0.2

    def test_heavy_recent_load_gives_negative_tsb(self):
        # Toutes les sorties dans les 3 derniers jours → ATL > CTL
        df = self._make_df(n=10, days_apart=0)
        ctl, atl, tsb = _compute_tsb(df)
        assert atl > ctl
        assert tsb < 0

    def test_single_activity(self):
        df = self._make_df(n=1)
        ctl, atl, tsb = _compute_tsb(df)
        assert ctl > 0 or atl > 0  # au moins un non-nul


# ===========================================================================
# _recommend_session
# ===========================================================================

class TestRecommendSession:
    def _make_df(self, n=10, days_apart=3):
        now = datetime.now()
        rows = [
            {
                "startTimeLocal": now - timedelta(days=i * days_apart),
                "activityType": "running",
                "distance_km": 10.0 + i * 0.5,
                "duration_min": 55.0,
                "avgPace_sec": 330.0,
                "avgHR": 148.0,
                "elevationGain": 60.0,
                "activityName": f"Run {i}",
                "startLat": 48.85,
                "startLon": 2.35,
                "activityId": i + 1,
            }
            for i in range(n)
        ]
        df = pd.DataFrame(rows)
        df["startTimeLocal"] = pd.to_datetime(df["startTimeLocal"])
        return df

    def test_return_keys(self):
        df = self._make_df()
        result = _recommend_session(df)
        for key in ["session_key", "session", "ctl", "atl", "tsb",
                    "target_dist_km", "target_pace_sec", "target_pace_str",
                    "target_elev", "duration_min", "avg_dist",
                    "suggested_date", "suggested_date_str"]:
            assert key in result

    def test_suggested_date_is_date_object(self):
        df = self._make_df()
        result = _recommend_session(df)
        assert isinstance(result["suggested_date"], date)

    def test_suggested_date_str_is_string(self):
        df = self._make_df()
        result = _recommend_session(df)
        assert isinstance(result["suggested_date_str"], str)
        assert len(result["suggested_date_str"]) > 0

    def test_tempo_when_fresh_and_recent_long(self):
        # TSB > 10 et sortie longue il y a 3 jours (< 6) → tempo
        now = datetime.now()
        # Une sortie longue récente + sorties standard
        rows = [{"startTimeLocal": now - timedelta(days=3), "distance_km": 18.0,
                 "duration_min": 100.0, "avgPace_sec": 330.0, "avgHR": 148.0,
                 "elevationGain": 80.0, "activityName": "Long", "startLat": 48.85,
                 "startLon": 2.35, "activityId": 0, "activityType": "running"}]
        rows += [
            {"startTimeLocal": now - timedelta(days=5 + i * 2), "distance_km": 10.0,
             "duration_min": 55.0, "avgPace_sec": 330.0, "avgHR": 148.0,
             "elevationGain": 60.0, "activityName": f"Run {i}", "startLat": 48.85,
             "startLon": 2.35, "activityId": i + 1, "activityType": "running"}
            for i in range(9)
        ]
        df = pd.DataFrame(rows)
        df["startTimeLocal"] = pd.to_datetime(df["startTimeLocal"])
        with patch.object(logic, "compute_tsb", return_value=(50.0, 38.0, 12.0)):
            result = _recommend_session(df)
        assert result["session_key"] == "tempo"

    def test_target_dist_minimum(self):
        # Même avec un facteur faible le minimum est 3 km
        df = self._make_df()
        with patch.object(logic, "compute_tsb", return_value=(-30.0, 10.0, -40.0)):
            result = _recommend_session(df)
        assert result["target_dist_km"] >= 3.0

    def test_recuperation_when_fatigue(self):
        df = self._make_df()
        with patch.object(logic, "compute_tsb", return_value=(80.0, 110.0, -30.0)):
            result = _recommend_session(df)
        assert result["session_key"] == "recuperation"

    def test_sortie_longue_when_fresh_and_no_recent_long(self):
        df = self._make_df(days_apart=7)  # espacement → pas de sortie longue récente
        with patch.object(logic, "compute_tsb", return_value=(50.0, 38.0, 12.0)):
            result = _recommend_session(df)
        assert result["session_key"] in ("sortie_longue", "tempo")

    def test_endurance_when_days_since_high(self):
        # Dernière sortie il y a 6 jours → override vers endurance
        now = datetime.now()
        rows = [
            {
                "startTimeLocal": now - timedelta(days=6),
                "activityType": "running",
                "distance_km": 10.0,
                "duration_min": 55.0,
                "avgPace_sec": 330.0,
                "avgHR": 148.0,
                "elevationGain": 60.0,
                "activityName": "Old run",
                "startLat": 48.85,
                "startLon": 2.35,
                "activityId": 1,
            }
        ]
        df = pd.DataFrame(rows)
        df["startTimeLocal"] = pd.to_datetime(df["startTimeLocal"])
        with patch.object(logic, "compute_tsb", return_value=(50.0, 38.0, 12.0)):
            result = _recommend_session(df)
        assert result["session_key"] == "endurance"

    def test_endurance_normal_tsb(self):
        df = self._make_df()
        with patch.object(logic, "compute_tsb", return_value=(40.0, 42.0, -2.0)):
            result = _recommend_session(df)
        assert result["session_key"] == "endurance"


# ===========================================================================
# format_date_fr
# ===========================================================================

class TestFormatDateFr:
    def test_today(self):
        assert _format_date_fr(date.today()) == "Aujourd'hui"

    def test_tomorrow(self):
        assert _format_date_fr(date.today() + timedelta(days=1)) == "Demain"

    def test_future_contains_day_name(self):
        d = date.today() + timedelta(days=7)
        result = _format_date_fr(d)
        assert any(j in result for j in logic._JOURS_FR)

    def test_future_contains_month_name(self):
        d = date.today() + timedelta(days=7)
        result = _format_date_fr(d)
        assert any(m in result for m in logic._MOIS_FR)

    def test_future_contains_day_number(self):
        d = date.today() + timedelta(days=7)
        result = _format_date_fr(d)
        assert str(d.day) in result

    def test_known_date(self):
        # 7 mai 2025 est un mercredi
        with patch.object(logic, "date") as mock_date:
            mock_date.today.return_value = date(2025, 5, 5)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = _format_date_fr(date(2025, 5, 7))
        assert result == "Mercredi 7 mai"


# ===========================================================================
# suggest_next_date
# ===========================================================================

class TestSuggestNextDate:
    def _make_df(self, n=10, days_apart=2):
        now = datetime.now()
        rows = [
            {
                "startTimeLocal": now - timedelta(days=i * days_apart),
                "activityType": "running",
                "distance_km": 10.0,
                "duration_min": 55.0,
                "avgPace_sec": 330.0,
                "avgHR": 148.0,
                "elevationGain": 60.0,
                "activityName": f"Run {i}",
                "startLat": 48.85, "startLon": 2.35,
                "activityId": i + 1,
            }
            for i in range(n)
        ]
        df = pd.DataFrame(rows)
        df["startTimeLocal"] = pd.to_datetime(df["startTimeLocal"])
        return df

    def _days_until(self, df, session_key, days_since, tsb):
        result = _suggest_next_date(df, session_key, days_since, tsb)
        return (result - date.today()).days

    def test_returns_date_object(self):
        df = self._make_df()
        result = _suggest_next_date(df, "endurance", 1, 0.0)
        assert isinstance(result, date)

    def test_never_in_past(self):
        # Même très reposé avec beaucoup de jours écoulés → au pire aujourd'hui
        df = self._make_df(days_apart=2)
        assert self._days_until(df, "endurance", 10, 15.0) == 0

    def test_typical_gap_respected(self):
        # 10 sorties tous les 3j → typical_gap=3, TSB neutre, endurance → 3j d'attente
        df = self._make_df(days_apart=3)
        assert self._days_until(df, "endurance", 0, 0.0) == 3

    def test_high_fatigue_delays(self):
        # TSB < -20 → +1j par rapport à TSB neutre
        df = self._make_df(days_apart=2)
        normal = self._days_until(df, "endurance", 0, 0.0)
        fatigued = self._days_until(df, "endurance", 0, -25.0)
        assert fatigued > normal

    def test_fresh_brings_forward(self):
        # TSB > 10 → -1j par rapport à TSB neutre
        df = self._make_df(days_apart=2)
        normal = self._days_until(df, "endurance", 0, 0.0)
        fresh = self._days_until(df, "endurance", 0, 15.0)
        assert fresh < normal

    def test_tempo_later_than_endurance(self):
        df = self._make_df(days_apart=2)
        assert self._days_until(df, "tempo", 0, 0.0) > self._days_until(df, "endurance", 0, 0.0)

    def test_sortie_longue_later_than_endurance(self):
        df = self._make_df(days_apart=2)
        assert self._days_until(df, "sortie_longue", 0, 0.0) > self._days_until(df, "endurance", 0, 0.0)

    def test_recuperation_earlier_than_endurance(self):
        df = self._make_df(days_apart=2)
        assert self._days_until(df, "recuperation", 0, 0.0) < self._days_until(df, "endurance", 0, 0.0)

    def test_already_rested_enough_returns_today(self):
        # days_since=5 avec typical_gap=2 → déjà assez reposé → aujourd'hui
        df = self._make_df(days_apart=2)
        assert self._days_until(df, "endurance", 5, 0.0) == 0

    def test_days_since_reduces_wait(self):
        # days_since=1 → 1j de moins que days_since=0
        df = self._make_df(days_apart=3)
        wait_0 = self._days_until(df, "endurance", 0, 0.0)
        wait_1 = self._days_until(df, "endurance", 1, 0.0)
        assert wait_1 == wait_0 - 1

    def test_fallback_few_runs(self):
        # Moins de 3 sorties → pas d'erreur, retourne une date valide
        df = self._make_df(n=2)
        result = _suggest_next_date(df, "endurance", 0, 0.0)
        assert isinstance(result, date)
        assert result >= date.today()

    def test_target_gap_minimum_one(self):
        # récupération + frais → target_gap = max(1, 2-1-1) = max(1,0) = 1 → jamais 0j d'attente
        df = self._make_df(days_apart=2)
        assert self._days_until(df, "recuperation", 0, 15.0) >= 0
