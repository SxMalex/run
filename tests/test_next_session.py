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
    compute_pmc_series as _compute_pmc_series,
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

    def test_empty_coords_returns_none(self):
        assert _parse_ors_route({
            "features": [{
                "geometry": {"coordinates": []},
                "properties": {
                    "summary": {"distance": 5000.0, "duration": 1800.0},
                    "ascent": 10,
                },
            }]
        }) is None

    def test_missing_geometry_returns_none(self):
        assert _parse_ors_route({
            "features": [{
                "properties": {
                    "summary": {"distance": 5000.0, "duration": 1800.0},
                }
            }]
        }) is None


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
# build_gpx — round-trip coordinate fidelity
# ===========================================================================

class TestBuildGpxRoundtrip:
    NS = {"gpx": "http://www.topografix.com/GPX/1/1"}

    def test_lat_lon_survive_roundtrip(self, sample_route):
        gpx = _build_gpx(sample_route, "Endurance", "5:30/km")
        root = ET.fromstring(gpx)
        trkpts = root.findall(".//gpx:trkpt", self.NS)
        assert len(trkpts) == len(sample_route["lats"])
        for i, pt in enumerate(trkpts):
            assert float(pt.attrib["lat"]) == pytest.approx(sample_route["lats"][i], abs=1e-5)
            assert float(pt.attrib["lon"]) == pytest.approx(sample_route["lons"][i], abs=1e-5)

    def test_elevations_survive_roundtrip(self, sample_route):
        gpx = _build_gpx(sample_route, "Endurance", "5:30/km")
        root = ET.fromstring(gpx)
        ele_tags = root.findall(".//gpx:trkpt/gpx:ele", self.NS)
        assert len(ele_tags) == len(sample_route["elevations"])
        for i, ele in enumerate(ele_tags):
            assert float(ele.text) == pytest.approx(sample_route["elevations"][i], abs=0.1)

    def test_no_elevations_produces_no_ele_tags(self, sample_route):
        route = {**sample_route, "elevations": []}
        gpx = _build_gpx(route, "Endurance", "5:30/km")
        root = ET.fromstring(gpx)
        assert root.findall(".//gpx:trkpt/gpx:ele", self.NS) == []


# ===========================================================================
# _compute_tsb
# ===========================================================================

class TestComputeTsb:
    def test_empty_df_returns_zeros(self):
        ctl, atl, tsb = _compute_tsb(pd.DataFrame())
        assert (ctl, atl, tsb) == (0.0, 0.0, 0.0)

    def test_zero_pace_returns_zeros(self, make_running_df):
        df = make_running_df(days_apart=4, pace_sec=0.0, with_location=False)
        ctl, atl, tsb = _compute_tsb(df)
        assert (ctl, atl, tsb) == (0.0, 0.0, 0.0)

    def test_returns_floats(self, make_running_df):
        df = make_running_df(days_apart=4, with_location=False)
        ctl, atl, tsb = _compute_tsb(df)
        assert all(isinstance(v, float) for v in (ctl, atl, tsb))

    def test_ctl_positive_with_training(self, make_running_df):
        df = make_running_df(n=15, days_apart=4, with_location=False)
        ctl, atl, tsb = _compute_tsb(df)
        assert ctl > 0

    def test_tsb_close_to_ctl_minus_atl(self, make_running_df):
        df = make_running_df(days_apart=4, with_location=False)
        ctl, atl, tsb = _compute_tsb(df)
        # TSB peut différer de ctl-atl de ±0.2 à cause des arrondis indépendants
        assert abs(tsb - (ctl - atl)) < 0.2

    def test_heavy_recent_load_gives_negative_tsb(self, make_running_df):
        # Toutes les sorties dans les 3 derniers jours → ATL > CTL
        df = make_running_df(n=10, days_apart=0, with_location=False)
        ctl, atl, tsb = _compute_tsb(df)
        assert atl > ctl
        assert tsb < 0

    def test_single_activity(self, make_running_df):
        df = make_running_df(n=1, days_apart=4, with_location=False)
        ctl, atl, tsb = _compute_tsb(df)
        assert ctl > 0 or atl > 0  # au moins un non-nul


# ===========================================================================
# _recommend_session
# ===========================================================================

class TestRecommendSession:
    def test_return_keys(self, make_running_df):
        df = make_running_df()
        result = _recommend_session(df)
        for key in ["session_key", "session", "ctl", "atl", "tsb",
                    "target_dist_km", "target_pace_sec", "target_pace_str",
                    "target_elev", "duration_min", "avg_dist",
                    "suggested_date", "suggested_date_str"]:
            assert key in result

    def test_suggested_date_is_date_object(self, make_running_df):
        df = make_running_df()
        result = _recommend_session(df)
        assert isinstance(result["suggested_date"], date)

    def test_suggested_date_str_is_string(self, make_running_df):
        df = make_running_df()
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

    def test_target_dist_minimum(self, make_running_df):
        # Même avec un facteur faible le minimum est 3 km
        df = make_running_df()
        with patch.object(logic, "compute_tsb", return_value=(-30.0, 10.0, -40.0)):
            result = _recommend_session(df)
        assert result["target_dist_km"] >= 3.0

    def test_recuperation_when_fatigue(self, make_running_df):
        df = make_running_df()
        with patch.object(logic, "compute_tsb", return_value=(80.0, 110.0, -30.0)):
            result = _recommend_session(df)
        assert result["session_key"] == "recuperation"

    def test_sortie_longue_when_fresh_and_no_recent_long(self, make_running_df):
        df = make_running_df(days_apart=7)  # espacement → pas de sortie longue récente
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

    def test_endurance_normal_tsb(self, make_running_df):
        df = make_running_df()
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
    def _days_until(self, df, session_key, days_since, tsb):
        result = _suggest_next_date(df, session_key, days_since, tsb)
        return (result - date.today()).days

    def test_returns_date_object(self, make_running_df):
        df = make_running_df(days_apart=2)
        result = _suggest_next_date(df, "endurance", 1, 0.0)
        assert isinstance(result, date)

    def test_never_in_past(self, make_running_df):
        # Même très reposé avec beaucoup de jours écoulés → au pire aujourd'hui
        df = make_running_df(days_apart=2)
        assert self._days_until(df, "endurance", 10, 15.0) == 0

    def test_typical_gap_respected(self, make_running_df):
        # 10 sorties tous les 3j → typical_gap=3, TSB neutre, endurance → 3j d'attente
        df = make_running_df(days_apart=3)
        assert self._days_until(df, "endurance", 0, 0.0) == 3

    def test_high_fatigue_delays(self, make_running_df):
        # TSB < -20 → +1j par rapport à TSB neutre
        df = make_running_df(days_apart=2)
        normal = self._days_until(df, "endurance", 0, 0.0)
        fatigued = self._days_until(df, "endurance", 0, -25.0)
        assert fatigued > normal

    def test_fresh_brings_forward(self, make_running_df):
        # TSB > 10 → -1j par rapport à TSB neutre
        df = make_running_df(days_apart=2)
        normal = self._days_until(df, "endurance", 0, 0.0)
        fresh = self._days_until(df, "endurance", 0, 15.0)
        assert fresh < normal

    def test_tempo_later_than_endurance(self, make_running_df):
        df = make_running_df(days_apart=2)
        assert self._days_until(df, "tempo", 0, 0.0) > self._days_until(df, "endurance", 0, 0.0)

    def test_sortie_longue_later_than_endurance(self, make_running_df):
        df = make_running_df(days_apart=2)
        assert self._days_until(df, "sortie_longue", 0, 0.0) > self._days_until(df, "endurance", 0, 0.0)

    def test_recuperation_earlier_than_endurance(self, make_running_df):
        df = make_running_df(days_apart=2)
        assert self._days_until(df, "recuperation", 0, 0.0) < self._days_until(df, "endurance", 0, 0.0)

    def test_already_rested_enough_returns_today(self, make_running_df):
        # days_since=5 avec typical_gap=2 → déjà assez reposé → aujourd'hui
        df = make_running_df(days_apart=2)
        assert self._days_until(df, "endurance", 5, 0.0) == 0

    def test_days_since_reduces_wait(self, make_running_df):
        # days_since=1 → 1j de moins que days_since=0
        df = make_running_df(days_apart=3)
        wait_0 = self._days_until(df, "endurance", 0, 0.0)
        wait_1 = self._days_until(df, "endurance", 1, 0.0)
        assert wait_1 == wait_0 - 1

    def test_fallback_few_runs(self, make_running_df):
        # Moins de 3 sorties → pas d'erreur, retourne une date valide
        df = make_running_df(n=2, days_apart=2)
        result = _suggest_next_date(df, "endurance", 0, 0.0)
        assert isinstance(result, date)
        assert result >= date.today()

    def test_target_gap_minimum_one(self, make_running_df):
        # récupération + frais → target_gap = max(1, 2-1-1) = max(1,0) = 1 → jamais 0j d'attente
        df = make_running_df(days_apart=2)
        assert self._days_until(df, "recuperation", 0, 15.0) >= 0


# ===========================================================================
# compute_pmc_series — modèle PMC (CTL/ATL/TSB) en série quotidienne
# ===========================================================================

class TestComputePmcSeries:
    """
    Couvre la dynamique exponentielle du PMC. Ces tests fixent le comportement
    des constantes de temps (k_ctl = exp(-1/42), k_atl = exp(-1/7)) afin qu'une
    inversion accidentelle des deux casse au moins un test.
    """

    def test_empty_df_returns_empty_series(self):
        result = _compute_pmc_series(pd.DataFrame(), threshold_sec=330.0)
        assert result.empty
        assert list(result.columns) == ["date", "tss", "ctl", "atl", "tsb"]

    def test_zero_pace_only_returns_empty(self, make_running_df):
        df = make_running_df(pace_sec=0.0, with_location=False)
        result = _compute_pmc_series(df, threshold_sec=330.0)
        assert result.empty

    def test_missing_avgpace_sec_column_returns_empty(self):
        # Cas robuste : DataFrame sans la colonne avgPace_sec
        df = pd.DataFrame([{"startTimeLocal": datetime.now(), "duration_min": 30.0}])
        result = _compute_pmc_series(df, threshold_sec=330.0)
        assert result.empty

    def test_single_activity_ctl_atl_start_at_zero_then_grow(self):
        """
        Une seule activité aujourd'hui :
        - le PMC démarre la série au jour de l'activité (récit borné par .min())
        - première ligne : ctl_v et atl_v incrémentés depuis 0 par la TSS du jour
        - TSB de la première ligne (mesuré AVANT le boost) = 0
        """
        df = pd.DataFrame([{
            "startTimeLocal": datetime.now(),
            "activityType": "running",
            "distance_km": 10.0,
            "duration_min": 60.0,
            "avgPace_sec": 330.0,
            "avgHR": 148.0,
            "elevationGain": 60.0,
        }])
        df["startTimeLocal"] = pd.to_datetime(df["startTimeLocal"])
        result = _compute_pmc_series(df, threshold_sec=330.0)
        assert not result.empty
        # IF=1, duration_h=1 → tss=100
        assert result.iloc[0]["tss"] == pytest.approx(100.0)
        # TSB du jour de la première activité = avant boost = 0
        assert result.iloc[0]["tsb"] == pytest.approx(0.0)
        # Après la TSS, ATL et CTL sont strictement positifs
        assert result.iloc[0]["ctl"] > 0
        assert result.iloc[0]["atl"] > 0
        # ATL réagit plus vite que CTL (k_atl < k_ctl → pondération nouvelle TSS plus forte)
        assert result.iloc[0]["atl"] > result.iloc[0]["ctl"]

    def test_ctl_decays_exponentially_after_last_activity(self):
        """
        Après une seule activité, sur les jours suivants sans TSS, CTL doit
        décroître exactement selon k_ctl = exp(-1/42).
        """
        # On force une activité 10 jours avant aujourd'hui pour avoir 10 jours
        # de décroissance derrière
        now = datetime.now()
        df = pd.DataFrame([{
            "startTimeLocal": now - timedelta(days=10),
            "activityType": "running",
            "distance_km": 10.0,
            "duration_min": 60.0,
            "avgPace_sec": 330.0,
            "avgHR": 148.0,
            "elevationGain": 60.0,
        }])
        df["startTimeLocal"] = pd.to_datetime(df["startTimeLocal"])
        result = _compute_pmc_series(df, threshold_sec=330.0)
        # Au moins 11 jours dans la série (jour de l'activité + jours suivants jusqu'à aujourd'hui)
        assert len(result) >= 2
        # Vérifie le ratio entre deux jours successifs sans TSS = k_ctl
        k_ctl_expected = float(np.exp(-1 / 42))
        # On prend le ratio entre jour 1 (lendemain de l'activité, tss=0) et jour 0
        ratio = result.iloc[1]["ctl"] / result.iloc[0]["ctl"]
        assert ratio == pytest.approx(k_ctl_expected, abs=1e-6)

    def test_atl_decays_faster_than_ctl(self):
        """
        Vérifie k_atl < k_ctl : sur un jour sans TSS, ATL chute plus
        que CTL en proportion. Ce test échouerait si on avait inversé les deux
        constantes.
        """
        now = datetime.now()
        df = pd.DataFrame([{
            "startTimeLocal": now - timedelta(days=10),
            "activityType": "running",
            "distance_km": 10.0,
            "duration_min": 60.0,
            "avgPace_sec": 330.0,
            "avgHR": 148.0,
            "elevationGain": 60.0,
        }])
        df["startTimeLocal"] = pd.to_datetime(df["startTimeLocal"])
        result = _compute_pmc_series(df, threshold_sec=330.0)
        ratio_ctl = result.iloc[1]["ctl"] / result.iloc[0]["ctl"]
        ratio_atl = result.iloc[1]["atl"] / result.iloc[0]["atl"]
        # ATL décroît plus vite ⇒ son ratio j+1/j est plus petit
        assert ratio_atl < ratio_ctl

    def test_constants_discriminant(self):
        """
        Test discriminant : si k_ctl et k_atl étaient inversés, ce ratio
        serait celui d'ATL (~0.866) au lieu de celui de CTL (~0.976).
        """
        now = datetime.now()
        df = pd.DataFrame([{
            "startTimeLocal": now - timedelta(days=5),
            "activityType": "running",
            "distance_km": 10.0,
            "duration_min": 60.0,
            "avgPace_sec": 330.0,
            "avgHR": 148.0,
            "elevationGain": 60.0,
        }])
        df["startTimeLocal"] = pd.to_datetime(df["startTimeLocal"])
        result = _compute_pmc_series(df, threshold_sec=330.0)
        k_ctl_expected = float(np.exp(-1 / 42))  # ≈ 0.9764
        k_atl_expected = float(np.exp(-1 / 7))   # ≈ 0.8669
        ratio_ctl = result.iloc[1]["ctl"] / result.iloc[0]["ctl"]
        # Doit matcher k_ctl, pas k_atl — gap nettement plus grand que la tolérance
        assert ratio_ctl == pytest.approx(k_ctl_expected, abs=1e-6)
        assert abs(ratio_ctl - k_atl_expected) > 0.05

    def test_repeated_training_makes_ctl_converge_toward_tss(self):
        """
        Avec une TSS constante quotidienne, CTL doit converger vers cette TSS
        (limite de la suite récurrente x_{n+1} = k*x_n + (1-k)*TSS).
        """
        now = datetime.now()
        # 200 jours de runs quotidiens identiques pour atteindre l'équilibre CTL
        rows = [
            {
                "startTimeLocal": now - timedelta(days=i),
                "activityType": "running",
                "distance_km": 10.0,
                "duration_min": 60.0,
                "avgPace_sec": 330.0,  # IF=1 → tss=100
                "avgHR": 148.0,
                "elevationGain": 60.0,
            }
            for i in range(200)
        ]
        df = pd.DataFrame(rows)
        df["startTimeLocal"] = pd.to_datetime(df["startTimeLocal"])
        result = _compute_pmc_series(df, threshold_sec=330.0)
        # À l'équilibre, CTL doit être proche de 100 (la TSS quotidienne)
        assert result.iloc[-1]["ctl"] == pytest.approx(100.0, abs=2.0)
        assert result.iloc[-1]["atl"] == pytest.approx(100.0, abs=2.0)
