"""
Tests des fonctions utilitaires et méthodes DataFrame de strava_client.py
"""

import hashlib
import json
import math
import time
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import requests
import strava_client as sc
from formatting import (
    speed_to_pace,
    speed_to_pace_seconds,
    seconds_to_pace_str,
    normalize_activity_type,
    estimate_calories,
    extract_cadence,
    extract_splits_metric,
    workout_type_label,
)
from strava_client import (
    _cache_get,
    _cache_set,
    safe_load_activities,
    StravaClient,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DUMMY_ATHLETE_ID = 42


def _make_client(athlete_id: int = _DUMMY_ATHLETE_ID, **token_overrides) -> StravaClient:
    """Construit un StravaClient pour les tests, avec un token valide en mémoire."""
    token = {
        "access_token": "tok",
        "refresh_token": "rot",
        "expires_at": int(time.time()) + 3600,
    }
    token.update(token_overrides)
    return StravaClient(token=token, athlete_id=athlete_id)


# ===========================================================================
# seconds_to_pace_str
# ===========================================================================

class TestSecondsToPaceStr:
    def test_round_minutes(self):
        assert seconds_to_pace_str(300.0) == "5:00/km"

    def test_non_round(self):
        assert seconds_to_pace_str(333.0) == "5:33/km"

    def test_zero_padding(self):
        assert seconds_to_pace_str(305.0) == "5:05/km"

    def test_zero(self):
        assert seconds_to_pace_str(0.0) == "—"

    def test_negative(self):
        assert seconds_to_pace_str(-10.0) == "—"

    def test_nan_float(self):
        assert seconds_to_pace_str(float("nan")) == "—"

    def test_nan_numpy(self):
        assert seconds_to_pace_str(np.float64("nan")) == "—"

    def test_numpy_float64(self):
        assert seconds_to_pace_str(np.float64(300.0)) == "5:00/km"

    def test_fast_pace(self):
        # 2:46/km = 166 sec/km
        assert seconds_to_pace_str(166.0) == "2:46/km"


# ===========================================================================
# speed_to_pace
# ===========================================================================

class TestSpeedToPace:
    def test_normal(self):
        # 3.0 m/s → 1000/3.0 = 333.33 sec/km → 5:33
        assert speed_to_pace(3.0) == "5:33/km"

    def test_zero(self):
        assert speed_to_pace(0.0) == "—"

    def test_negative(self):
        assert speed_to_pace(-1.0) == "—"

    def test_none(self):
        assert speed_to_pace(None) == "—"

    def test_4ms(self):
        # 1000/4.0 = 250 sec = 4:10
        assert speed_to_pace(4.0) == "4:10/km"


# ===========================================================================
# speed_to_pace_seconds
# ===========================================================================

class TestSpeedToPaceSeconds:
    def test_normal(self):
        assert speed_to_pace_seconds(4.0) == pytest.approx(250.0)

    def test_zero(self):
        assert speed_to_pace_seconds(0.0) == 0.0

    def test_none(self):
        assert speed_to_pace_seconds(None) == 0.0


# ===========================================================================
# normalize_activity_type
# ===========================================================================

class TestNormalizeActivityType:
    @pytest.mark.parametrize("sport,expected", [
        ("Run",           "running"),
        ("TrailRun",      "running"),
        ("VirtualRun",    "running"),
        ("running",       "running"),
        ("Ride",          "cycling"),
        ("VirtualRide",   "cycling"),
        ("GravelRide",    "cycling"),
        ("Swim",          "swimming"),
        ("Walk",          "walking"),
        ("Hike",          "hiking"),
        ("WeightTraining","strength"),
        ("Yoga",          "yoga"),
    ])
    def test_known_types(self, sport, expected):
        assert normalize_activity_type(sport) == expected

    def test_unknown_lowercased(self):
        assert normalize_activity_type("Kitesurfing") == "kitesurfing"

    def test_none_returns_unknown(self):
        assert normalize_activity_type(None) == "unknown"

    def test_already_normalized(self):
        assert normalize_activity_type("running") == "running"


# ===========================================================================
# estimate_calories
# ===========================================================================

class TestEstimateCalories:
    def test_api_value_used_first(self):
        result = estimate_calories(500, 1000)
        assert result == 500

    def test_api_zero_falls_through_to_kilojoules(self):
        result = estimate_calories(0, 200.0)
        assert result == 200

    def test_api_none_falls_through_to_kilojoules(self):
        result = estimate_calories(None, 200.0)
        assert result == 200

    def test_no_data_returns_none(self):
        result = estimate_calories(None, None)
        assert result is None

    def test_api_zero_no_kj_returns_none(self):
        result = estimate_calories(0, None)
        assert result is None

    def test_kilojoules_1to1_convention(self):
        # 1 kJ mécanique ≈ 1 kcal métabolique
        result = estimate_calories(None, 640.0)
        assert result == 640

    def test_api_value_integer_cast(self):
        result = estimate_calories(499.9, None)
        assert result == 499


# ===========================================================================
# extract_cadence
# ===========================================================================

class TestExtractCadence:
    def test_running_doubles_rpm(self):
        assert extract_cadence(85.0, "Run") == pytest.approx(170.0)

    def test_running_normalized_type(self):
        assert extract_cadence(85.0, "running") == pytest.approx(170.0)

    def test_cycling_unchanged(self):
        assert extract_cadence(90.0, "Ride") == pytest.approx(90.0)

    def test_none_input(self):
        assert extract_cadence(None, "Run") is None

    def test_swimming_none(self):
        assert extract_cadence(None, "Swim") is None


# ===========================================================================
# StravaClient.get_weekly_stats
# ===========================================================================

class TestGetWeeklyStats:
    def setup_method(self):
        self.client = _make_client()

    def test_empty_df(self, empty_df):
        result = self.client.get_weekly_stats(empty_df)
        assert result.empty

    def test_no_running(self, mixed_activities_df):
        cycling_only = mixed_activities_df[mixed_activities_df["activityType"] == "cycling"]
        result = self.client.get_weekly_stats(cycling_only)
        assert result.empty

    def test_columns_present(self, sample_running_df):
        result = self.client.get_weekly_stats(sample_running_df)
        for col in ["km_total", "nb_sorties", "pace_moyen", "hr_moyen", "week"]:
            assert col in result.columns

    def test_km_total_positive(self, sample_running_df):
        result = self.client.get_weekly_stats(sample_running_df)
        assert (result["km_total"] > 0).all()

    def test_sorted_ascending(self, sample_running_df):
        result = self.client.get_weekly_stats(sample_running_df)
        assert result["week"].is_monotonic_increasing

    def test_zero_pace_excluded_from_avg(self):
        # Fixed Monday so the test is not sensitive to the day the suite runs
        monday = datetime(2024, 1, 1, 10, 0, 0)  # 2024-01-01 is a known Monday
        rows = [
            {"activityId": 1, "startTimeLocal": monday, "activityName": "A",
             "activityType": "running", "distance_km": 8.0, "duration_min": 45.0,
             "avgPace": "5:30/km", "avgPace_sec": 0.0,  # zeroed out
             "avgHR": 150.0, "maxHR": 175.0, "avgCadence": 170.0,
             "calories": 450, "elevationGain": 80.0, "avgSpeed_ms": 3.0,
             "kudosCount": 0, "startLat": 48.85, "startLon": 2.35},
            {"activityId": 2, "startTimeLocal": monday + timedelta(days=2), "activityName": "B",
             "activityType": "running", "distance_km": 9.0, "duration_min": 50.0,
             "avgPace": "5:30/km", "avgPace_sec": 330.0,  # valid pace
             "avgHR": 152.0, "maxHR": 177.0, "avgCadence": 172.0,
             "calories": 470, "elevationGain": 90.0, "avgSpeed_ms": 3.03,
             "kudosCount": 1, "startLat": 48.86, "startLon": 2.36},
        ]
        df = pd.DataFrame(rows)
        df["startTimeLocal"] = pd.to_datetime(df["startTimeLocal"])
        result = self.client.get_weekly_stats(df)
        # The week has one zero-pace and one valid — average should use only the valid one
        assert len(result) == 1
        assert result["pace_moyen_sec"].iloc[0] == 330.0

    def test_filters_out_non_running(self, mixed_activities_df):
        result = self.client.get_weekly_stats(mixed_activities_df)
        # Seulement les runs contribuent → km_total < total de tous les sports
        total_all = mixed_activities_df["distance_km"].sum()
        assert result["km_total"].sum() < total_all


# ===========================================================================
# StravaClient.get_monthly_stats
# ===========================================================================

class TestGetMonthlyStats:
    def setup_method(self):
        self.client = _make_client()

    def test_empty_df(self, empty_df):
        assert self.client.get_monthly_stats(empty_df).empty

    def test_month_label_format(self, sample_running_df):
        result = self.client.get_monthly_stats(sample_running_df)
        import re
        for label in result["month_label"]:
            assert re.match(r"[A-Za-zéû]+ \d{4}", label), f"Format inattendu : {label}"

    def test_columns_present(self, sample_running_df):
        result = self.client.get_monthly_stats(sample_running_df)
        for col in ["km_total", "nb_sorties", "month_label"]:
            assert col in result.columns


# ===========================================================================
# StravaClient.get_summary_metrics
# ===========================================================================

class TestGetSummaryMetrics:
    def setup_method(self):
        self.client = _make_client()

    def test_empty_df_returns_defaults(self, empty_df):
        result = self.client.get_summary_metrics(empty_df)
        assert result["km_semaine"] == 0
        assert result["pace_moyen"] == "—"
        assert result["hr_moyen"] == "—"

    def test_all_keys_present(self, sample_running_df):
        result = self.client.get_summary_metrics(sample_running_df)
        for key in ["km_semaine", "km_mois", "pace_moyen", "hr_moyen",
                    "nb_sorties_semaine", "nb_sorties_mois"]:
            assert key in result

    def test_recent_run_counted(self, recent_running_df):
        result = self.client.get_summary_metrics(recent_running_df)
        assert result["nb_sorties_semaine"] >= 1
        assert result["km_semaine"] > 0

    def test_cycling_not_counted(self, mixed_activities_df):
        result = self.client.get_summary_metrics(mixed_activities_df)
        running_only = mixed_activities_df[mixed_activities_df["activityType"] == "running"]
        expected_km = self.client.get_summary_metrics(running_only)["km_mois"]
        assert result["km_mois"] == pytest.approx(expected_km)

    def test_missing_hr_returns_dash(self, sample_running_df):
        df = sample_running_df.copy()
        df["avgHR"] = np.nan
        result = self.client.get_summary_metrics(df)
        assert result["hr_moyen"] == "—"


# ===========================================================================
# StravaClient.get_hr_zones
# ===========================================================================

class TestGetHrZones:
    _ZONES = [
        {"min": 0,   "max": 114},
        {"min": 114, "max": 133},
        {"min": 133, "max": 152},
        {"min": 152, "max": 171},
        {"min": 171, "max": -1},
    ]

    def setup_method(self):
        self.client = _make_client()

    def test_empty_df(self, empty_df):
        assert self.client.get_hr_zones(empty_df, hr_zones=self._ZONES).empty

    def test_empty_zones_returns_empty(self, sample_running_df):
        assert self.client.get_hr_zones(sample_running_df, hr_zones=[]).empty

    def test_no_running(self, mixed_activities_df):
        cycling_only = mixed_activities_df[mixed_activities_df["activityType"] == "cycling"]
        assert self.client.get_hr_zones(cycling_only, hr_zones=self._ZONES).empty

    def test_five_zones_returned(self, sample_running_df):
        result = self.client.get_hr_zones(sample_running_df, hr_zones=self._ZONES)
        assert len(result) == 5

    def test_counts_sum_to_valid_runs(self, sample_running_df):
        valid = sample_running_df.dropna(subset=["avgHR"])
        result = self.client.get_hr_zones(sample_running_df, hr_zones=self._ZONES)
        assert result["nb_activites"].sum() == len(valid)

    def test_nan_hr_excluded(self, sample_running_df):
        df = sample_running_df.copy()
        df.loc[0, "avgHR"] = np.nan
        result = self.client.get_hr_zones(df, hr_zones=self._ZONES)
        assert result["nb_activites"].sum() == df["avgHR"].notna().sum()

    def test_all_in_z1_when_low_hr(self, sample_running_df):
        df = sample_running_df.copy()
        df["avgHR"] = 50.0  # < 114 bpm → Z1
        result = self.client.get_hr_zones(df, hr_zones=self._ZONES)
        z1 = result[result["zone"].str.startswith("Z1")]
        assert z1["nb_activites"].iloc[0] == len(df)

    def test_last_zone_label_has_gte(self, sample_running_df):
        result = self.client.get_hr_zones(sample_running_df, hr_zones=self._ZONES)
        assert "≥" in result.iloc[-1]["zone"]


# ===========================================================================
# workout_type_label
# ===========================================================================

class TestWorkoutTypeLabel:
    @pytest.mark.parametrize("wt,expected", [
        (0,  "Normal"),
        (1,  "Race"),
        (2,  "Sortie longue"),
        (3,  "Entraînement"),
        (10, "Normal"),
        (11, "Race"),
        (12, "Sortie"),
    ])
    def test_known_values(self, wt, expected):
        assert workout_type_label(wt) == expected

    def test_none_returns_normal(self):
        assert workout_type_label(None) == "Normal"

    def test_zero_returns_normal(self):
        assert workout_type_label(0) == "Normal"

    def test_unknown_value_returns_normal(self):
        assert workout_type_label(99) == "Normal"

    def test_string_int_accepted(self):
        assert workout_type_label("1") == "Race"


# ===========================================================================
# normalize_activity_type — cas manquants
# ===========================================================================

class TestNormalizeActivityTypeExtra:
    @pytest.mark.parametrize("sport,expected", [
        ("Treadmill",       "running"),
        ("trail_running",   "running"),
        ("MountainBikeRide","cycling"),
        ("EBikeRide",       "cycling"),
        ("strength_training","strength"),
        ("Workout",         "cardio"),
        ("Crossfit",        "cardio"),
        ("cardio_training", "cardio"),
    ])
    def test_missing_variants(self, sport, expected):
        assert normalize_activity_type(sport) == expected


# ===========================================================================
# extract_splits_metric
# ===========================================================================

class TestExtractSplitsMetric:
    def _split(self, **kwargs):
        base = {
            "split": 1,
            "distance": 1000.0,
            "elapsed_time": 330,
            "moving_time": 325,
            "average_speed": 3.03,
            "average_heartrate": 150.0,
            "elevation_difference": 5.0,
            "pace_zone": 3,
        }
        base.update(kwargs)
        return base

    def test_empty_list(self):
        assert extract_splits_metric({"splits_metric": []}) == []

    def test_missing_key(self):
        assert extract_splits_metric({}) == []

    def test_split_count(self):
        details = {"splits_metric": [self._split(split=i) for i in range(1, 4)]}
        assert len(extract_splits_metric(details)) == 3

    def test_split_number(self):
        details = {"splits_metric": [self._split(split=3)]}
        assert extract_splits_metric(details)[0]["split"] == 3

    def test_pace_computed_from_speed(self):
        details = {"splits_metric": [self._split(average_speed=4.0)]}
        row = extract_splits_metric(details)[0]
        assert row["pace_sec"] == pytest.approx(250.0)
        assert row["pace"] == "4:10/km"

    def test_zero_speed_gives_zero_pace(self):
        details = {"splits_metric": [self._split(average_speed=0)]}
        row = extract_splits_metric(details)[0]
        assert row["pace_sec"] == 0.0

    def test_none_speed_gives_zero_pace(self):
        details = {"splits_metric": [self._split(average_speed=None)]}
        row = extract_splits_metric(details)[0]
        assert row["pace_sec"] == 0.0

    def test_missing_hr_is_none(self):
        details = {"splits_metric": [self._split()]}
        details["splits_metric"][0].pop("average_heartrate", None)
        row = extract_splits_metric(details)[0]
        assert row["avg_hr"] is None

    def test_elevation_difference(self):
        details = {"splits_metric": [self._split(elevation_difference=-3.0)]}
        row = extract_splits_metric(details)[0]
        assert row["elev_diff"] == pytest.approx(-3.0)

    def test_none_elev_defaults_zero(self):
        details = {"splits_metric": [self._split(elevation_difference=None)]}
        row = extract_splits_metric(details)[0]
        assert row["elev_diff"] == 0


# ===========================================================================
# StravaClient._summarize_activity
# ===========================================================================

class TestSummarizeActivity:
    def setup_method(self):
        self.client = _make_client()

    def _details(self, **kwargs):
        base = {
            "distance": 10000.0,
            "moving_time": 3300,
            "average_speed": 3.03,
            "average_heartrate": 148.0,
            "max_heartrate": 172.0,
            "average_cadence": 85.0,
            "calories": 600,
            "total_elevation_gain": 80.0,
            "average_watts": None,
            "sport_type": "Run",
        }
        base.update(kwargs)
        return base

    def test_distance_converted_to_km(self):
        result = self.client._summarize_activity(self._details(distance=10000.0))
        assert result["distance_km"] == pytest.approx(10.0)

    def test_duration_converted_to_min(self):
        result = self.client._summarize_activity(self._details(moving_time=3600))
        assert result["duration_min"] == pytest.approx(60.0)

    def test_pace_formatted(self):
        result = self.client._summarize_activity(self._details(average_speed=4.0))
        assert result["avgPace"] == "4:10/km"

    def test_running_cadence_doubled(self):
        result = self.client._summarize_activity(self._details(average_cadence=85.0, sport_type="Run"))
        assert result["avgCadence"] == pytest.approx(170.0)

    def test_cycling_cadence_unchanged(self):
        result = self.client._summarize_activity(self._details(average_cadence=90.0, sport_type="Ride"))
        assert result["avgCadence"] == pytest.approx(90.0)

    def test_missing_distance_defaults_zero(self):
        details = self._details()
        details.pop("distance")
        result = self.client._summarize_activity(details)
        assert result["distance_km"] == 0.0

    def test_none_hr_propagated(self):
        result = self.client._summarize_activity(self._details(average_heartrate=None))
        assert result["avgHR"] is None

    def test_all_keys_present(self):
        result = self.client._summarize_activity(self._details())
        for key in ["distance_km", "duration_min", "avgPace", "avgHR",
                    "maxHR", "avgCadence", "calories", "elevationGain", "avgPower"]:
            assert key in result


# ===========================================================================
# Cache TTL boundary conditions
# ===========================================================================

class TestCacheTTL:
    KEY = "test_cache_ttl_key"
    ATHLETE_ID = 42

    def _write_entry(self, cache_dir, athlete_id: int, key: str, data, timestamp: float) -> None:
        safe_key = hashlib.md5(key.encode()).hexdigest()
        athlete_dir = cache_dir / str(athlete_id)
        athlete_dir.mkdir(parents=True, exist_ok=True)
        (athlete_dir / f"{safe_key}.json").write_text(
            json.dumps({"timestamp": timestamp, "data": data})
        )

    def test_fresh_data_returned(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sc, "CACHE_DIR", tmp_path)
        _cache_set(self.ATHLETE_ID, self.KEY, {"value": 42})
        assert _cache_get(self.ATHLETE_ID, self.KEY) == {"value": 42}

    def test_isolated_per_athlete(self, monkeypatch, tmp_path):
        """Deux athlètes ne se voient pas — même clé, données distinctes."""
        monkeypatch.setattr(sc, "CACHE_DIR", tmp_path)
        _cache_set(1, self.KEY, {"value": "alice"})
        _cache_set(2, self.KEY, {"value": "bob"})
        assert _cache_get(1, self.KEY) == {"value": "alice"}
        assert _cache_get(2, self.KEY) == {"value": "bob"}
        # Athlète sans donnée écrite → cache miss
        assert _cache_get(3, self.KEY) is None

    def test_expired_data_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sc, "CACHE_DIR", tmp_path)
        old_ts = time.time() - sc.CACHE_TTL - 1
        self._write_entry(tmp_path, self.ATHLETE_ID, self.KEY, {"value": 99}, old_ts)
        assert _cache_get(self.ATHLETE_ID, self.KEY) is None

    def test_expired_file_is_deleted(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sc, "CACHE_DIR", tmp_path)
        old_ts = time.time() - sc.CACHE_TTL - 1
        self._write_entry(tmp_path, self.ATHLETE_ID, self.KEY, {"value": 99}, old_ts)
        _cache_get(self.ATHLETE_ID, self.KEY)
        safe_key = hashlib.md5(self.KEY.encode()).hexdigest()
        assert not (tmp_path / str(self.ATHLETE_ID) / f"{safe_key}.json").exists()

    def test_boundary_at_exact_ttl_is_expired(self, monkeypatch, tmp_path):
        # Condition is strict <, so age == CACHE_TTL → expired.
        monkeypatch.setattr(sc, "CACHE_DIR", tmp_path)
        boundary_ts = time.time() - sc.CACHE_TTL
        self._write_entry(tmp_path, self.ATHLETE_ID, self.KEY, {"value": 1}, boundary_ts)
        assert _cache_get(self.ATHLETE_ID, self.KEY) is None

    def test_just_before_ttl_is_hit(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sc, "CACHE_DIR", tmp_path)
        recent_ts = time.time() - sc.CACHE_TTL + 60  # 60 s before expiry
        self._write_entry(tmp_path, self.ATHLETE_ID, self.KEY, {"value": 7}, recent_ts)
        assert _cache_get(self.ATHLETE_ID, self.KEY) == {"value": 7}

    def test_corrupted_json_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sc, "CACHE_DIR", tmp_path)
        athlete_dir = tmp_path / str(self.ATHLETE_ID)
        athlete_dir.mkdir(parents=True, exist_ok=True)
        safe_key = hashlib.md5(self.KEY.encode()).hexdigest()
        (athlete_dir / f"{safe_key}.json").write_text("not valid json {{")
        assert _cache_get(self.ATHLETE_ID, self.KEY) is None

    def test_missing_file_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sc, "CACHE_DIR", tmp_path)
        assert _cache_get(self.ATHLETE_ID, "nonexistent_key_xyz") is None

    def test_invalidate_cache_only_affects_one_athlete(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sc, "CACHE_DIR", tmp_path)
        _cache_set(1, "k", {"v": 1})
        _cache_set(2, "k", {"v": 2})
        client = _make_client(athlete_id=1)
        client.invalidate_cache()
        assert _cache_get(1, "k") is None
        assert _cache_get(2, "k") == {"v": 2}


# ===========================================================================
# Cache hit ⇒ pas d'appel API
# ===========================================================================

class TestCacheHitSkipsApi:
    """Sur cache hit, _get n'est jamais appelé (donc pas de refresh non plus)."""

    def setup_method(self):
        self.client = _make_client()
        self._minimal_details = {
            "distance": 10000.0,
            "moving_time": 3300,
            "average_speed": 3.03,
            "sport_type": "Run",
            "average_heartrate": None,
            "max_heartrate": None,
            "average_cadence": None,
            "calories": None,
            "kilojoules": None,
            "total_elevation_gain": None,
            "average_watts": None,
        }

    def test_get_streams_calls_api_on_miss(self):
        with patch("strava_client._cache_get", return_value=None), \
             patch("strava_client._cache_set"), \
             patch.object(self.client, "_get", return_value={"heartrate": {"data": [150]}}) as mock_get:
            self.client.get_streams(42)
        mock_get.assert_called_once()

    def test_get_streams_skips_api_on_hit(self):
        with patch("strava_client._cache_get", return_value={"heartrate": [150]}), \
             patch.object(self.client, "_get") as mock_get:
            self.client.get_streams(42)
        mock_get.assert_not_called()

    def test_get_activity_details_calls_api_on_miss(self):
        with patch("strava_client._cache_get", return_value=None), \
             patch("strava_client._cache_set"), \
             patch.object(self.client, "_get", side_effect=[self._minimal_details, []]) as mock_get:
            self.client.get_activity_details(99)
        assert mock_get.call_count >= 1

    def test_get_activity_details_skips_api_on_hit(self):
        cached = {"details": {}, "splits": [], "splits_metric": [], "summary": {}}
        with patch("strava_client._cache_get", return_value=cached), \
             patch.object(self.client, "_get") as mock_get:
            self.client.get_activity_details(99)
        mock_get.assert_not_called()


# ===========================================================================
# StravaClient._get retry behaviour
# ===========================================================================

class TestGetRetry:
    """Le retry sur 5xx doit relancer une seule fois et propager le résultat final."""

    def setup_method(self):
        # Token frais — n'a pas besoin d'être rafraîchi pendant ces tests.
        self.client = _make_client()

    def _resp(self, status: int, json_body=None):
        r = MagicMock()
        r.status_code = status
        r.json.return_value = json_body if json_body is not None else {}
        if status >= 400:
            r.raise_for_status.side_effect = requests.HTTPError(response=r)
        else:
            r.raise_for_status.return_value = None
        return r

    def test_success_first_try_no_retry(self):
        ok = self._resp(200, {"k": 1})
        with patch("strava_client.requests.get", return_value=ok) as mget, \
             patch("strava_client.time.sleep"):
            result = self.client._get("athlete")
        assert result == {"k": 1}
        assert mget.call_count == 1

    def test_5xx_then_success(self):
        with patch(
            "strava_client.requests.get",
            side_effect=[self._resp(503), self._resp(200, {"k": 2})],
        ) as mget, patch("strava_client.time.sleep") as msleep:
            result = self.client._get("athlete")
        assert result == {"k": 2}
        assert mget.call_count == 2
        msleep.assert_called_once_with(2)

    def test_5xx_twice_raises(self):
        with patch(
            "strava_client.requests.get",
            side_effect=[self._resp(502), self._resp(503)],
        ), patch("strava_client.time.sleep"):
            with pytest.raises(requests.HTTPError):
                self.client._get("athlete")

    def test_4xx_no_retry(self):
        with patch(
            "strava_client.requests.get", return_value=self._resp(401)
        ) as mget, patch("strava_client.time.sleep") as msleep:
            with pytest.raises(requests.HTTPError):
                self.client._get("athlete")
        assert mget.call_count == 1
        msleep.assert_not_called()


# ===========================================================================
# safe_load_activities
# ===========================================================================

class TestSafeLoadActivities:
    """Le wrapper traduit les exceptions Strava en messages utilisateur."""

    def setup_method(self):
        self.client = _make_client()

    def _http_error(self, status: int) -> requests.HTTPError:
        resp = MagicMock()
        resp.status_code = status
        return requests.HTTPError(response=resp)

    def test_success_returns_dataframe_no_error(self, sample_running_df):
        with patch.object(self.client, "get_activities", return_value=sample_running_df):
            df, err = safe_load_activities(self.client, 50)
        assert err is None
        assert not df.empty

    def test_401_returns_token_message(self):
        with patch.object(self.client, "get_activities", side_effect=self._http_error(401)):
            df, err = safe_load_activities(self.client, 50)
        assert df.empty
        assert "Token" in err

    def test_429_returns_rate_limit_message(self):
        with patch.object(self.client, "get_activities", side_effect=self._http_error(429)):
            df, err = safe_load_activities(self.client, 50)
        assert "Limite" in err

    def test_503_returns_server_message(self):
        with patch.object(self.client, "get_activities", side_effect=self._http_error(503)):
            df, err = safe_load_activities(self.client, 50)
        assert "503" in err
        assert "indisponibles" in err

    def test_other_http_status(self):
        with patch.object(self.client, "get_activities", side_effect=self._http_error(418)):
            df, err = safe_load_activities(self.client, 50)
        assert "418" in err

    def test_value_error_propagated(self):
        with patch.object(
            self.client, "get_activities", side_effect=ValueError("Tokens Strava non trouvés.")
        ):
            df, err = safe_load_activities(self.client, 50)
        assert err == "Tokens Strava non trouvés."

    def test_network_error(self):
        with patch.object(
            self.client,
            "get_activities",
            side_effect=requests.ConnectionError("name resolution"),
        ):
            df, err = safe_load_activities(self.client, 50)
        assert "réseau" in err.lower()

    def test_unexpected_exception_caught(self):
        with patch.object(self.client, "get_activities", side_effect=RuntimeError("boom")):
            df, err = safe_load_activities(self.client, 50)
        assert df.empty
        assert "inattendue" in err.lower()

    def test_http_error_without_response_attr(self):
        # Cas dégradé : e.response est None → status code = 0
        err_obj = requests.HTTPError()
        err_obj.response = None
        with patch.object(self.client, "get_activities", side_effect=err_obj):
            df, err = safe_load_activities(self.client, 50)
        assert df.empty
        assert err is not None


# ===========================================================================
# StravaClient._refresh_token
# ===========================================================================

class TestRefreshToken:
    """Le rafraîchissement appelle Strava et n'écrit RIEN sur disque."""

    def setup_method(self):
        self.client = _make_client()
        self.client.client_id = "id"
        self.client.client_secret = "secret"

    def test_returns_new_token(self):
        new_token = {
            "access_token": "fresh",
            "refresh_token": "rot",
            "expires_at": int(time.time()) + 21600,
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = new_token
        mock_resp.raise_for_status.return_value = None

        with patch("strava_client.requests.post", return_value=mock_resp):
            result = self.client._refresh_token("old_refresh")

        assert result == new_token

    def test_post_called_with_grant_refresh(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "x", "refresh_token": "y", "expires_at": 0}
        mock_resp.raise_for_status.return_value = None

        with patch("strava_client.requests.post", return_value=mock_resp) as mpost:
            self.client._refresh_token("old_rt")

        assert mpost.call_count == 1
        kwargs = mpost.call_args.kwargs
        assert kwargs["data"]["grant_type"] == "refresh_token"
        assert kwargs["data"]["refresh_token"] == "old_rt"
        assert kwargs["data"]["client_id"] == "id"

    def test_missing_credentials_raises(self):
        self.client.client_id = ""
        with pytest.raises(ValueError, match="STRAVA_CLIENT_ID"):
            self.client._refresh_token("old")

    def test_http_error_propagated(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("400 Bad Request")
        with patch("strava_client.requests.post", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                self.client._refresh_token("old")


# ===========================================================================
# StravaClient._ensure_fresh_token (refresh transparent piloté par le token)
# ===========================================================================

class TestEnsureFreshToken:
    """
    Le client doit rafraîchir le token quand il expire dans <5 min
    et propager le nouveau token via le callback `on_token_update`.
    """

    def _new_token(self) -> dict:
        return {
            "access_token": "fresh",
            "refresh_token": "rot2",
            "expires_at": int(time.time()) + 21600,
        }

    def test_fresh_token_does_not_refresh(self):
        client = _make_client(expires_at=int(time.time()) + 3600)
        with patch.object(client, "_refresh_token") as mock_refresh:
            client._ensure_fresh_token()
        mock_refresh.assert_not_called()
        assert client._token["access_token"] == "tok"

    def test_expired_token_triggers_refresh_and_callback(self):
        new_token = self._new_token()
        on_update = MagicMock()
        client = StravaClient(
            token={"access_token": "stale", "refresh_token": "rot", "expires_at": int(time.time()) - 100},
            athlete_id=42,
            on_token_update=on_update,
        )
        with patch.object(client, "_refresh_token", return_value=new_token) as mock_refresh:
            client._ensure_fresh_token()
        mock_refresh.assert_called_once_with("rot")
        assert client._token == new_token
        on_update.assert_called_once_with(new_token)

    def test_token_within_5min_window_triggers_refresh(self):
        # Fenêtre de refresh : expires_at - 300s ; expirant dans 60 s → refresh.
        new_token = self._new_token()
        client = _make_client(expires_at=int(time.time()) + 60)
        with patch.object(client, "_refresh_token", return_value=new_token) as mock_refresh:
            client._ensure_fresh_token()
        mock_refresh.assert_called_once()
        assert client._token["access_token"] == "fresh"

    def test_no_callback_does_not_crash(self):
        new_token = self._new_token()
        client = StravaClient(
            token={"access_token": "stale", "refresh_token": "rot", "expires_at": int(time.time()) - 100},
            athlete_id=42,
            on_token_update=None,
        )
        with patch.object(client, "_refresh_token", return_value=new_token):
            client._ensure_fresh_token()
        assert client._token == new_token

    def test_missing_token_raises(self):
        client = StravaClient(token={}, athlete_id=42)
        with pytest.raises(ValueError, match="manquant"):
            client._ensure_fresh_token()


# ===========================================================================
# get_segment_efforts
# ===========================================================================

class TestGetSegmentEfforts:
    def setup_method(self):
        self.client = _make_client()

    def _make_cached(self, name: str, segment_efforts: list) -> dict:
        """Construit le dict tel que stocké par get_activity_details."""
        return {
            "details": {"name": name, "segment_efforts": segment_efforts},
            "splits": [],
            "splits_metric": [],
            "summary": {},
        }

    def _make_effort(self, seg_id=10, seg_name="Mur", kom_rank=None, pr_rank=None,
                    elapsed=120, dist=500, grade=4.2, city="Lyon", country="France"):
        return {
            "start_date_local": "2026-04-01T07:00:00Z",
            "elapsed_time": elapsed,
            "moving_time": elapsed,
            "kom_rank": kom_rank,
            "pr_rank": pr_rank,
            "segment": {
                "id": seg_id,
                "name": seg_name,
                "activity_type": "Run",
                "distance": dist,
                "average_grade": grade,
                "city": city,
                "country": country,
            },
        }

    def test_empty_list_returns_empty_df(self):
        with patch("strava_client._cache_get", return_value=None), \
             patch.object(self.client, "get_activity_details") as mock_get:
            result = self.client.get_segment_efforts([])
        assert result.empty
        mock_get.assert_not_called()

    def test_cache_hit_skips_api(self):
        cached = self._make_cached("Run", [self._make_effort()])
        with patch("strava_client._cache_get", return_value=cached), \
             patch.object(self.client, "get_activity_details") as mock_get:
            result = self.client.get_segment_efforts([42])
        mock_get.assert_not_called()
        assert len(result) == 1
        assert result.iloc[0]["segment_id"] == 10

    def test_cache_miss_calls_get_details(self):
        cached = self._make_cached("Run", [self._make_effort()])
        with patch("strava_client._cache_get", return_value=None), \
             patch("strava_client.time.sleep"), \
             patch.object(self.client, "get_activity_details", return_value=cached) as mock_get:
            result = self.client.get_segment_efforts([42])
        mock_get.assert_called_once_with(42)
        assert len(result) == 1

    def test_columns_correct(self):
        cached = self._make_cached(
            "Tempo",
            [self._make_effort(seg_id=5, seg_name="Pont", kom_rank=3, pr_rank=1)],
        )
        with patch("strava_client._cache_get", return_value=cached):
            result = self.client.get_segment_efforts([1])
        expected_cols = {
            "activity_id", "activity_name", "effort_date", "segment_id",
            "segment_name", "segment_activity_type", "segment_distance_m",
            "segment_avg_grade", "segment_city", "segment_country",
            "elapsed_time", "moving_time", "kom_rank", "pr_rank",
        }
        assert expected_cols.issubset(set(result.columns))
        row = result.iloc[0]
        assert row["activity_id"] == 1
        assert row["activity_name"] == "Tempo"
        assert row["segment_name"] == "Pont"
        assert row["kom_rank"] == 3
        assert row["pr_rank"] == 1

    def test_multiple_efforts_become_multiple_rows(self):
        cached = self._make_cached(
            "Long",
            [
                self._make_effort(seg_id=1, seg_name="A"),
                self._make_effort(seg_id=2, seg_name="B"),
                self._make_effort(seg_id=3, seg_name="C"),
            ],
        )
        with patch("strava_client._cache_get", return_value=cached):
            result = self.client.get_segment_efforts([100])
        assert len(result) == 3
        assert sorted(result["segment_id"].tolist()) == [1, 2, 3]

    def test_effort_without_segment_id_skipped(self):
        bad = self._make_effort()
        bad["segment"]["id"] = None
        good = self._make_effort(seg_id=7)
        cached = self._make_cached("Run", [bad, good])
        with patch("strava_client._cache_get", return_value=cached):
            result = self.client.get_segment_efforts([1])
        assert len(result) == 1
        assert result.iloc[0]["segment_id"] == 7

    def test_activity_without_segments_returns_empty(self):
        cached = self._make_cached("No segments", [])
        with patch("strava_client._cache_get", return_value=cached):
            result = self.client.get_segment_efforts([1])
        assert result.empty

    def test_api_error_skips_activity(self):
        good = self._make_cached("Good", [self._make_effort(seg_id=9)])

        def cache_get_side_effect(athlete_id, key):
            return good if key == "activity_detail_2" else None

        with patch("strava_client._cache_get", side_effect=cache_get_side_effect), \
             patch("strava_client.time.sleep"), \
             patch.object(self.client, "get_activity_details", side_effect=Exception("boom")):
            result = self.client.get_segment_efforts([1, 2])
        assert len(result) == 1
        assert result.iloc[0]["segment_id"] == 9


# ===========================================================================
# explore_segments
# ===========================================================================

class TestExploreSegments:
    def setup_method(self):
        self.client = _make_client()

    def test_cache_hit_skips_api(self):
        cached = [{"id": 1, "name": "Cached"}]
        with patch("strava_client._cache_get", return_value=cached), \
             patch.object(self.client, "_get") as mock_get:
            result = self.client.explore_segments(45.0, 4.8, 45.1, 4.9)
        mock_get.assert_not_called()
        assert result == cached

    def test_cache_miss_calls_api_and_caches(self):
        segments = [{"id": 1, "name": "S1"}, {"id": 2, "name": "S2"}]
        api_response = {"segments": segments}
        with patch("strava_client._cache_get", return_value=None), \
             patch("strava_client._cache_set") as mock_set, \
             patch.object(self.client, "_get", return_value=api_response):
            result = self.client.explore_segments(45.0, 4.8, 45.1, 4.9)
        assert result == segments
        mock_set.assert_called_once()

    def test_api_error_returns_empty_list(self):
        with patch("strava_client._cache_get", return_value=None), \
             patch.object(self.client, "_get", side_effect=Exception("boom")):
            result = self.client.explore_segments(45.0, 4.8, 45.1, 4.9)
        assert result == []

    def test_passes_bounds_and_activity_type(self):
        with patch("strava_client._cache_get", return_value=None), \
             patch("strava_client._cache_set"), \
             patch.object(self.client, "_get", return_value={"segments": []}) as mock_get:
            self.client.explore_segments(45.0, 4.8, 45.1, 4.9, activity_type="riding")
        args, kwargs = mock_get.call_args
        assert args[0] == "segments/explore"
        params = args[1] if len(args) > 1 else kwargs.get("params") or kwargs
        # _get(endpoint, params) → params est le 2e positionnel
        assert params["activity_type"] == "riding"
        assert params["bounds"] == "45.0,4.8,45.1,4.9"

    def test_unexpected_response_shape_returns_empty(self):
        # API renvoie une liste au lieu d'un dict → on doit retourner []
        with patch("strava_client._cache_get", return_value=None), \
             patch("strava_client._cache_set"), \
             patch.object(self.client, "_get", return_value=[1, 2, 3]):
            result = self.client.explore_segments(45.0, 4.8, 45.1, 4.9)
        assert result == []


# ===========================================================================
# StravaClient.get_activities — pipeline central de récupération
# ===========================================================================

class TestGetActivities:
    """Couvre le mapping JSON Strava → DataFrame, la pagination et le cache."""

    def setup_method(self):
        self.client = _make_client()

    def _sample_activity(self, **overrides):
        """Une activité Strava typique (JSON brut depuis l'API)."""
        base = {
            "id": 12345,
            "name": "Morning Run",
            "sport_type": "Run",
            "start_date_local": "2026-04-01T07:30:00Z",
            "distance": 10042.5,
            "moving_time": 3300,
            "average_speed": 3.04,
            "average_heartrate": 148.0,
            "max_heartrate": 172.0,
            "average_cadence": 85.0,
            "calories": 600,
            "kilojoules": None,
            "total_elevation_gain": 80.0,
            "kudos_count": 3,
            "start_latlng": [48.85, 2.35],
            "workout_type": 0,
        }
        base.update(overrides)
        return base

    def test_cache_hit_skips_api(self):
        """Sur cache hit, get_activities renvoie un DataFrame sans toucher à _get."""
        cached_rows = [{
            "activityId": 1,
            "startTimeLocal": "2026-04-01T07:30:00",
            "activityName": "X",
            "activityType": "running",
            "distance_km": 10.0,
            "duration_min": 55.0,
            "avgPace": "5:30/km",
            "avgPace_sec": 330.0,
            "avgHR": 148.0,
            "maxHR": 172.0,
            "avgCadence": 170.0,
            "calories": 600,
            "elevationGain": 80.0,
            "avgSpeed_ms": 3.03,
            "kudosCount": 3,
            "startLat": 48.85,
            "startLon": 2.35,
            "workoutType": 0,
        }]
        with patch("strava_client._cache_get", return_value=cached_rows), \
             patch.object(self.client, "_get") as mock_get:
            df = self.client.get_activities(limit=50)
        mock_get.assert_not_called()
        assert len(df) == 1
        assert df.iloc[0]["activityId"] == 1

    def test_mapping_columns_and_distance_rounding(self):
        """Les champs JSON sont mappés sur les bons noms de colonnes ; distance arrondie à 2 décimales."""
        with patch("strava_client._cache_get", return_value=None), \
             patch("strava_client._cache_set"), \
             patch.object(self.client, "_get", return_value=[self._sample_activity()]):
            df = self.client.get_activities(limit=50)
        assert len(df) == 1
        row = df.iloc[0]
        assert row["activityId"] == 12345
        assert row["activityName"] == "Morning Run"
        assert row["activityType"] == "running"
        # 10042.5 m → 10.04 km (arrondi à 2 décimales)
        assert row["distance_km"] == pytest.approx(10.04, abs=1e-6)
        # 3300s → 55.0 min
        assert row["duration_min"] == pytest.approx(55.0, abs=1e-6)
        # cadence = 85 RPM × 2 (running) = 170
        assert row["avgCadence"] == pytest.approx(170.0)
        assert row["startLat"] == pytest.approx(48.85)
        assert row["startLon"] == pytest.approx(2.35)
        assert row["workoutType"] == 0

    def test_start_time_local_is_tz_naive(self):
        """Le timestamp ISO+Z doit ressortir tz-naive (utc=True puis tz_convert(None))."""
        activity = self._sample_activity(start_date_local="2026-04-01T07:30:00Z")
        with patch("strava_client._cache_get", return_value=None), \
             patch("strava_client._cache_set"), \
             patch.object(self.client, "_get", return_value=[activity]):
            df = self.client.get_activities(limit=50)
        ts = df.iloc[0]["startTimeLocal"]
        # tz-naive : pas d'attribut tzinfo non-None
        assert ts.tzinfo is None

    def test_start_latlng_none_does_not_crash(self):
        """Une activité sans coordonnées GPS doit produire startLat/startLon = None."""
        activity = self._sample_activity(start_latlng=None)
        with patch("strava_client._cache_get", return_value=None), \
             patch("strava_client._cache_set"), \
             patch.object(self.client, "_get", return_value=[activity]):
            df = self.client.get_activities(limit=50)
        assert df.iloc[0]["startLat"] is None
        assert df.iloc[0]["startLon"] is None

    def test_pagination_stops_when_batch_shorter_than_per_page(self):
        """
        Avec limit=200, per_page=200. Si la 1ère page renvoie 200 et la 2e
        renvoie <200, la boucle s'arrête après la 2e (donc _get appelé 2 fois).
        """
        full_page = [self._sample_activity(id=i) for i in range(200)]
        partial = [self._sample_activity(id=1000 + i) for i in range(50)]
        with patch("strava_client._cache_get", return_value=None), \
             patch("strava_client._cache_set"), \
             patch.object(self.client, "_get", side_effect=[full_page, partial]) as mock_get:
            df = self.client.get_activities(limit=200)
        # 200 activités demandées, pagination s'arrête au 1er batch complet (200 ≥ limit)
        # La logique : `while len(activities) < limit` → après 1er batch len=200 == limit → stop
        # Donc _get est appelé 1 seule fois ici
        assert mock_get.call_count == 1
        assert len(df) == 200

    def test_pagination_two_pages_when_first_smaller_than_limit(self):
        """
        Avec limit=200 et per_page=200, si la 1ère page renvoie 150,
        la condition `len(batch) < per_page` casse la boucle après cette page.
        """
        partial = [self._sample_activity(id=i) for i in range(150)]
        with patch("strava_client._cache_get", return_value=None), \
             patch("strava_client._cache_set"), \
             patch.object(self.client, "_get", side_effect=[partial]) as mock_get:
            df = self.client.get_activities(limit=200)
        assert mock_get.call_count == 1
        assert len(df) == 150

    def test_empty_response_returns_empty_df(self):
        with patch("strava_client._cache_get", return_value=None), \
             patch("strava_client._cache_set"), \
             patch.object(self.client, "_get", return_value=[]):
            df = self.client.get_activities(limit=50)
        assert df.empty

    def test_calories_estimated_from_kilojoules_when_api_zero(self):
        """Quand `calories` Strava = 0 et `kilojoules` > 0 → estimation 1:1."""
        activity = self._sample_activity(calories=0, kilojoules=420.0)
        with patch("strava_client._cache_get", return_value=None), \
             patch("strava_client._cache_set"), \
             patch.object(self.client, "_get", return_value=[activity]):
            df = self.client.get_activities(limit=50)
        assert df.iloc[0]["calories"] == 420

    def test_calories_api_used_first(self):
        """Quand `calories` API > 0, on l'utilise (pas le fallback kJ)."""
        activity = self._sample_activity(calories=550, kilojoules=999.0)
        with patch("strava_client._cache_get", return_value=None), \
             patch("strava_client._cache_set"), \
             patch.object(self.client, "_get", return_value=[activity]):
            df = self.client.get_activities(limit=50)
        assert df.iloc[0]["calories"] == 550

    def test_limit_truncates_extra_activities(self):
        """Si la 1ère page renvoie plus que limit, on tronque proprement."""
        activities = [self._sample_activity(id=i) for i in range(80)]
        with patch("strava_client._cache_get", return_value=None), \
             patch("strava_client._cache_set"), \
             patch.object(self.client, "_get", return_value=activities):
            df = self.client.get_activities(limit=50)
        # `activities = activities[:limit]` → 50 lignes
        assert len(df) == 50

    def test_cache_set_called_on_miss(self):
        """Sur cache miss, get_activities doit écrire dans le cache."""
        with patch("strava_client._cache_get", return_value=None), \
             patch("strava_client._cache_set") as mock_set, \
             patch.object(self.client, "_get", return_value=[self._sample_activity()]):
            self.client.get_activities(limit=50)
        mock_set.assert_called_once()
