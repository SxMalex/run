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
from strava_client import (
    _speed_to_pace,
    _speed_to_pace_seconds,
    _seconds_to_pace_str,
    _normalize_activity_type,
    _estimate_calories,
    _extract_cadence,
    _extract_splits_metric,
    _cache_get,
    _cache_set,
    safe_load_activities,
    workout_type_label,
    StravaClient,
)


# ===========================================================================
# _seconds_to_pace_str
# ===========================================================================

class TestSecondsToPaceStr:
    def test_round_minutes(self):
        assert _seconds_to_pace_str(300.0) == "5:00/km"

    def test_non_round(self):
        assert _seconds_to_pace_str(333.0) == "5:33/km"

    def test_zero_padding(self):
        assert _seconds_to_pace_str(305.0) == "5:05/km"

    def test_zero(self):
        assert _seconds_to_pace_str(0.0) == "—"

    def test_negative(self):
        assert _seconds_to_pace_str(-10.0) == "—"

    def test_nan_float(self):
        assert _seconds_to_pace_str(float("nan")) == "—"

    def test_nan_numpy(self):
        assert _seconds_to_pace_str(np.float64("nan")) == "—"

    def test_numpy_float64(self):
        assert _seconds_to_pace_str(np.float64(300.0)) == "5:00/km"

    def test_fast_pace(self):
        # 2:46/km = 166 sec/km
        assert _seconds_to_pace_str(166.0) == "2:46/km"


# ===========================================================================
# _speed_to_pace
# ===========================================================================

class TestSpeedToPace:
    def test_normal(self):
        # 3.0 m/s → 1000/3.0 = 333.33 sec/km → 5:33
        assert _speed_to_pace(3.0) == "5:33/km"

    def test_zero(self):
        assert _speed_to_pace(0.0) == "—"

    def test_negative(self):
        assert _speed_to_pace(-1.0) == "—"

    def test_none(self):
        assert _speed_to_pace(None) == "—"

    def test_4ms(self):
        # 1000/4.0 = 250 sec = 4:10
        assert _speed_to_pace(4.0) == "4:10/km"


# ===========================================================================
# _speed_to_pace_seconds
# ===========================================================================

class TestSpeedToPaceSeconds:
    def test_normal(self):
        assert _speed_to_pace_seconds(4.0) == pytest.approx(250.0)

    def test_zero(self):
        assert _speed_to_pace_seconds(0.0) == 0.0

    def test_none(self):
        assert _speed_to_pace_seconds(None) == 0.0


# ===========================================================================
# _normalize_activity_type
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
        assert _normalize_activity_type(sport) == expected

    def test_unknown_lowercased(self):
        assert _normalize_activity_type("Kitesurfing") == "kitesurfing"

    def test_none_returns_unknown(self):
        assert _normalize_activity_type(None) == "unknown"

    def test_already_normalized(self):
        assert _normalize_activity_type("running") == "running"


# ===========================================================================
# _estimate_calories
# ===========================================================================

class TestEstimateCalories:
    def test_api_value_used_first(self):
        result = _estimate_calories(500, 1000)
        assert result == 500

    def test_api_zero_falls_through_to_kilojoules(self):
        result = _estimate_calories(0, 200.0)
        assert result == 200

    def test_api_none_falls_through_to_kilojoules(self):
        result = _estimate_calories(None, 200.0)
        assert result == 200

    def test_no_data_returns_none(self):
        result = _estimate_calories(None, None)
        assert result is None

    def test_api_zero_no_kj_returns_none(self):
        result = _estimate_calories(0, None)
        assert result is None

    def test_kilojoules_1to1_convention(self):
        # 1 kJ mécanique ≈ 1 kcal métabolique
        result = _estimate_calories(None, 640.0)
        assert result == 640

    def test_api_value_integer_cast(self):
        result = _estimate_calories(499.9, None)
        assert result == 499


# ===========================================================================
# _extract_cadence
# ===========================================================================

class TestExtractCadence:
    def test_running_doubles_rpm(self):
        assert _extract_cadence(85.0, "Run") == pytest.approx(170.0)

    def test_running_normalized_type(self):
        assert _extract_cadence(85.0, "running") == pytest.approx(170.0)

    def test_cycling_unchanged(self):
        assert _extract_cadence(90.0, "Ride") == pytest.approx(90.0)

    def test_none_input(self):
        assert _extract_cadence(None, "Run") is None

    def test_swimming_none(self):
        assert _extract_cadence(None, "Swim") is None


# ===========================================================================
# StravaClient.get_weekly_stats
# ===========================================================================

class TestGetWeeklyStats:
    def setup_method(self):
        self.client = StravaClient()

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
        self.client = StravaClient()

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
        self.client = StravaClient()

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
        self.client = StravaClient()

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
# _normalize_activity_type — cas manquants
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
        assert _normalize_activity_type(sport) == expected


# ===========================================================================
# _extract_splits_metric
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
        assert _extract_splits_metric({"splits_metric": []}) == []

    def test_missing_key(self):
        assert _extract_splits_metric({}) == []

    def test_split_count(self):
        details = {"splits_metric": [self._split(split=i) for i in range(1, 4)]}
        assert len(_extract_splits_metric(details)) == 3

    def test_split_number(self):
        details = {"splits_metric": [self._split(split=3)]}
        assert _extract_splits_metric(details)[0]["split"] == 3

    def test_pace_computed_from_speed(self):
        details = {"splits_metric": [self._split(average_speed=4.0)]}
        row = _extract_splits_metric(details)[0]
        assert row["pace_sec"] == pytest.approx(250.0)
        assert row["pace"] == "4:10/km"

    def test_zero_speed_gives_zero_pace(self):
        details = {"splits_metric": [self._split(average_speed=0)]}
        row = _extract_splits_metric(details)[0]
        assert row["pace_sec"] == 0.0

    def test_none_speed_gives_zero_pace(self):
        details = {"splits_metric": [self._split(average_speed=None)]}
        row = _extract_splits_metric(details)[0]
        assert row["pace_sec"] == 0.0

    def test_missing_hr_is_none(self):
        details = {"splits_metric": [self._split()]}
        details["splits_metric"][0].pop("average_heartrate", None)
        row = _extract_splits_metric(details)[0]
        assert row["avg_hr"] is None

    def test_elevation_difference(self):
        details = {"splits_metric": [self._split(elevation_difference=-3.0)]}
        row = _extract_splits_metric(details)[0]
        assert row["elev_diff"] == pytest.approx(-3.0)

    def test_none_elev_defaults_zero(self):
        details = {"splits_metric": [self._split(elevation_difference=None)]}
        row = _extract_splits_metric(details)[0]
        assert row["elev_diff"] == 0


# ===========================================================================
# StravaClient._summarize_activity
# ===========================================================================

class TestSummarizeActivity:
    def setup_method(self):
        self.client = StravaClient()

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
# StravaClient.get_best_efforts
# ===========================================================================

class TestGetBestEfforts:
    def setup_method(self):
        self.client = StravaClient()

    def _mock_details(self, activity_name, efforts):
        """Construit un faux dict d'activité Strava avec best_efforts."""
        return {
            "name": activity_name,
            "start_date_local": "2025-04-01T07:00:00Z",
            "best_efforts": [
                {"name": e["name"], "elapsed_time": e["elapsed_time"], "pr_rank": e.get("pr_rank")}
                for e in efforts
            ],
        }

    def _patches(self, get_side_effect=None, get_return=None):
        """Contexte de mock commun : cache désactivé + connexion bouchonnée."""
        side = {"side_effect": get_side_effect} if get_side_effect else {"return_value": get_return}
        return (
            patch.object(self.client, "_ensure_connected"),
            patch.object(self.client, "_get", **side),
            patch("strava_client._cache_get", return_value=None),
            patch("strava_client._cache_set"),
        )

    def test_empty_list_returns_empty_dict(self):
        with patch.object(self.client, "_ensure_connected"), \
             patch("strava_client._cache_get", return_value=None), \
             patch("strava_client._cache_set"):
            result = self.client.get_best_efforts([])
        assert result == {}

    def test_single_effort_stored(self):
        details = self._mock_details("Run A", [{"name": "1k", "elapsed_time": 240}])
        p1, p2, p3, p4 = self._patches(get_return=details)
        with p1, p2, p3, p4:
            result = self.client.get_best_efforts([1])
        assert "1k" in result
        assert result["1k"]["elapsed_time"] == 240

    def test_best_time_wins_across_activities(self):
        fast = self._mock_details("Fast Run", [{"name": "1k", "elapsed_time": 210}])
        slow = self._mock_details("Slow Run", [{"name": "1k", "elapsed_time": 270}])
        p1, p2, p3, p4 = self._patches(get_side_effect=[fast, slow])
        with p1, p2, p3, p4:
            result = self.client.get_best_efforts([1, 2])
        assert result["1k"]["elapsed_time"] == 210
        assert result["1k"]["activity_name"] == "Fast Run"

    def test_activity_without_efforts_ignored(self):
        details = self._mock_details("No efforts", [])
        p1, p2, p3, p4 = self._patches(get_return=details)
        with p1, p2, p3, p4:
            result = self.client.get_best_efforts([1])
        assert result == {}

    def test_effort_missing_elapsed_time_skipped(self):
        details = self._mock_details("Run", [{"name": "1k", "elapsed_time": None}])
        p1, p2, p3, p4 = self._patches(get_return=details)
        with p1, p2, p3, p4:
            result = self.client.get_best_efforts([1])
        assert result == {}

    def test_api_error_skipped_continues(self):
        good = self._mock_details("Good", [{"name": "5k", "elapsed_time": 1200}])
        p1, p2, p3, p4 = self._patches(get_side_effect=[Exception("timeout"), good])
        with p1, p2, p3, p4:
            result = self.client.get_best_efforts([1, 2])
        assert "5k" in result


# ===========================================================================
# Cache TTL boundary conditions
# ===========================================================================

class TestCacheTTL:
    KEY = "test_cache_ttl_key"

    def _write_entry(self, cache_dir, key: str, data, timestamp: float) -> None:
        safe_key = hashlib.md5(key.encode()).hexdigest()
        (cache_dir / f"{safe_key}.json").write_text(
            json.dumps({"timestamp": timestamp, "data": data})
        )

    def test_fresh_data_returned(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sc, "CACHE_DIR", tmp_path)
        _cache_set(self.KEY, {"value": 42})
        assert _cache_get(self.KEY) == {"value": 42}

    def test_expired_data_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sc, "CACHE_DIR", tmp_path)
        old_ts = time.time() - sc.CACHE_TTL - 1
        self._write_entry(tmp_path, self.KEY, {"value": 99}, old_ts)
        assert _cache_get(self.KEY) is None

    def test_expired_file_is_deleted(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sc, "CACHE_DIR", tmp_path)
        old_ts = time.time() - sc.CACHE_TTL - 1
        self._write_entry(tmp_path, self.KEY, {"value": 99}, old_ts)
        _cache_get(self.KEY)
        safe_key = hashlib.md5(self.KEY.encode()).hexdigest()
        assert not (tmp_path / f"{safe_key}.json").exists()

    def test_boundary_at_exact_ttl_is_expired(self, monkeypatch, tmp_path):
        # Condition is strict <, so age == CACHE_TTL → expired.
        # Setting timestamp to now - CACHE_TTL means any subsequent read
        # will see age >= CACHE_TTL, which fails the strict < check.
        monkeypatch.setattr(sc, "CACHE_DIR", tmp_path)
        boundary_ts = time.time() - sc.CACHE_TTL
        self._write_entry(tmp_path, self.KEY, {"value": 1}, boundary_ts)
        assert _cache_get(self.KEY) is None

    def test_just_before_ttl_is_hit(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sc, "CACHE_DIR", tmp_path)
        recent_ts = time.time() - sc.CACHE_TTL + 60  # 60 s before expiry
        self._write_entry(tmp_path, self.KEY, {"value": 7}, recent_ts)
        assert _cache_get(self.KEY) == {"value": 7}

    def test_corrupted_json_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sc, "CACHE_DIR", tmp_path)
        safe_key = hashlib.md5(self.KEY.encode()).hexdigest()
        (tmp_path / f"{safe_key}.json").write_text("not valid json {{")
        assert _cache_get(self.KEY) is None

    def test_missing_file_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sc, "CACHE_DIR", tmp_path)
        assert _cache_get("nonexistent_key_xyz") is None


# ===========================================================================
# _ensure_connected call contract
# ===========================================================================

class TestEnsureConnectedContract:
    """_ensure_connected must be called on cache miss and skipped on cache hit."""

    def setup_method(self):
        self.client = StravaClient()
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

    def test_get_streams_calls_ensure_connected_on_miss(self):
        with patch("strava_client._cache_get", return_value=None), \
             patch("strava_client._cache_set"), \
             patch.object(self.client, "_ensure_connected") as mock_connect, \
             patch.object(self.client, "_get", return_value={"heartrate": {"data": [150]}}):
            self.client.get_streams(42)
        mock_connect.assert_called_once()

    def test_get_streams_skips_ensure_connected_on_hit(self):
        with patch("strava_client._cache_get", return_value={"heartrate": [150]}), \
             patch.object(self.client, "_ensure_connected") as mock_connect:
            self.client.get_streams(42)
        mock_connect.assert_not_called()

    def test_get_activity_details_calls_ensure_connected_on_miss(self):
        with patch("strava_client._cache_get", return_value=None), \
             patch("strava_client._cache_set"), \
             patch.object(self.client, "_ensure_connected") as mock_connect, \
             patch.object(self.client, "_get", side_effect=[self._minimal_details, []]):
            self.client.get_activity_details(99)
        mock_connect.assert_called_once()

    def test_get_activity_details_skips_ensure_connected_on_hit(self):
        cached = {"details": {}, "splits": [], "splits_metric": [], "summary": {}}
        with patch("strava_client._cache_get", return_value=cached), \
             patch.object(self.client, "_ensure_connected") as mock_connect:
            self.client.get_activity_details(99)
        mock_connect.assert_not_called()


# ===========================================================================
# StravaClient._get retry behaviour
# ===========================================================================

class TestGetRetry:
    """Le retry sur 5xx doit relancer une seule fois et propager le résultat final."""

    def setup_method(self):
        self.client = StravaClient()
        self.client._access_token = "tok"
        self.client._connected = True

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
        self.client = StravaClient()

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
    """Le rafraîchissement écrit le nouveau token sur disque, perms 0o600."""

    def setup_method(self):
        self.client = StravaClient()
        self.client.client_id = "id"
        self.client.client_secret = "secret"

    def _redirect_token_file(self, monkeypatch, tmp_path):
        token_file = tmp_path / "strava_token.json"
        monkeypatch.setattr(sc, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(sc, "TOKEN_FILE", token_file)
        return token_file

    def test_persists_new_token(self, tmp_path, monkeypatch):
        token_file = self._redirect_token_file(monkeypatch, tmp_path)
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
        assert token_file.exists()
        assert json.loads(token_file.read_text()) == new_token

    def test_post_called_with_grant_refresh(self, tmp_path, monkeypatch):
        self._redirect_token_file(monkeypatch, tmp_path)
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

    def test_http_error_propagated(self, tmp_path, monkeypatch):
        self._redirect_token_file(monkeypatch, tmp_path)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("400 Bad Request")
        with patch("strava_client.requests.post", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                self.client._refresh_token("old")


# ===========================================================================
# StravaClient.connect
# ===========================================================================

class TestConnect:
    def setup_method(self):
        self.client = StravaClient()
        self.client.client_id = "id"
        self.client.client_secret = "secret"

    def _set_token_path(self, monkeypatch, tmp_path) -> "Path":
        token_file = tmp_path / "strava_token.json"
        monkeypatch.setattr(sc, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(sc, "TOKEN_FILE", token_file)
        return token_file

    def test_no_token_file_raises_value_error(self, tmp_path, monkeypatch):
        self._set_token_path(monkeypatch, tmp_path)
        with pytest.raises(ValueError, match="non trouvés"):
            self.client.connect()

    def test_corrupt_token_raises_value_error(self, tmp_path, monkeypatch):
        token_file = self._set_token_path(monkeypatch, tmp_path)
        token_file.write_text("not json")
        with pytest.raises(ValueError, match="Impossible de lire"):
            self.client.connect()

    def test_fresh_token_does_not_refresh(self, tmp_path, monkeypatch):
        token_file = self._set_token_path(monkeypatch, tmp_path)
        token_file.write_text(json.dumps({
            "access_token": "current",
            "refresh_token": "rot",
            "expires_at": int(time.time()) + 3600,
        }))
        with patch.object(self.client, "_refresh_token") as mock_refresh:
            self.client.connect()
        mock_refresh.assert_not_called()
        assert self.client._access_token == "current"
        assert self.client._connected is True

    def test_expired_token_triggers_refresh(self, tmp_path, monkeypatch):
        token_file = self._set_token_path(monkeypatch, tmp_path)
        token_file.write_text(json.dumps({
            "access_token": "stale",
            "refresh_token": "rot",
            "expires_at": int(time.time()) - 100,
        }))
        new_token = {
            "access_token": "fresh",
            "refresh_token": "rot2",
            "expires_at": int(time.time()) + 21600,
        }
        with patch.object(self.client, "_refresh_token", return_value=new_token) as mock_refresh:
            self.client.connect()
        mock_refresh.assert_called_once_with("rot")
        assert self.client._access_token == "fresh"

    def test_token_within_5min_window_triggers_refresh(self, tmp_path, monkeypatch):
        # La fenêtre de refresh est expires_at - 300s ; un token expirant
        # dans 60 s doit donc déjà déclencher un refresh.
        token_file = self._set_token_path(monkeypatch, tmp_path)
        token_file.write_text(json.dumps({
            "access_token": "soon_stale",
            "refresh_token": "rot",
            "expires_at": int(time.time()) + 60,
        }))
        new_token = {
            "access_token": "fresh",
            "refresh_token": "rot2",
            "expires_at": int(time.time()) + 21600,
        }
        with patch.object(self.client, "_refresh_token", return_value=new_token) as mock_refresh:
            self.client.connect()
        mock_refresh.assert_called_once()
        assert self.client._access_token == "fresh"
