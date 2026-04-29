"""
Tests des fonctions utilitaires et méthodes DataFrame de strava_client.py
"""

import math
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import patch

import strava_client as sc
from strava_client import (
    _speed_to_pace,
    _speed_to_pace_seconds,
    _seconds_to_pace_str,
    _normalize_activity_type,
    _estimate_calories,
    _extract_cadence,
    _extract_splits_metric,
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
        result = _estimate_calories(500, 1000, 10000, 3600, "running")
        assert result == 500

    def test_api_zero_falls_through(self):
        # calories_api=0 → falsy → falls to running formula
        result = _estimate_calories(0, None, 10000, 3600, "running")
        expected = int(sc.ATHLETE_WEIGHT_KG * 10.0 * 1.04)
        assert result == expected

    def test_running_formula(self):
        result = _estimate_calories(None, None, 10000, 3600, "running")
        expected = int(sc.ATHLETE_WEIGHT_KG * 10.0 * 1.04)
        assert result == expected

    def test_running_zero_distance_returns_none(self):
        result = _estimate_calories(None, None, 0, 3600, "running")
        assert result is None

    def test_cycling_with_kilojoules(self):
        result = _estimate_calories(None, 200.0, 0, 3600, "cycling")
        assert result == int(200.0 / 4.184)

    def test_no_data_returns_none(self):
        result = _estimate_calories(None, None, 0, 0, "cycling")
        assert result is None

    def test_custom_weight(self):
        with patch.object(sc, "ATHLETE_WEIGHT_KG", 80.0):
            result = _estimate_calories(None, None, 10000, 3600, "running")
            assert result == int(80.0 * 10.0 * 1.04)


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
        # Build two activities explicitly in the same week to avoid day-of-week sensitivity
        monday = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
        monday -= timedelta(days=monday.weekday())  # rewind to Monday
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
    def setup_method(self):
        self.client = StravaClient()

    def test_empty_df(self, empty_df):
        assert self.client.get_hr_zones(empty_df).empty

    def test_no_running(self, mixed_activities_df):
        cycling_only = mixed_activities_df[mixed_activities_df["activityType"] == "cycling"]
        assert self.client.get_hr_zones(cycling_only).empty

    def test_five_zones_returned(self, sample_running_df):
        result = self.client.get_hr_zones(sample_running_df, max_hr=190)
        assert len(result) == 5

    def test_counts_sum_to_valid_runs(self, sample_running_df):
        valid = sample_running_df.dropna(subset=["avgHR"])
        result = self.client.get_hr_zones(sample_running_df, max_hr=190)
        assert result["nb_activites"].sum() == len(valid)

    def test_nan_hr_excluded(self, sample_running_df):
        df = sample_running_df.copy()
        df.loc[0, "avgHR"] = np.nan
        result = self.client.get_hr_zones(df, max_hr=190)
        valid_count = df["avgHR"].notna().sum()
        assert result["nb_activites"].sum() == valid_count

    def test_all_in_z1_when_low_hr(self, sample_running_df):
        df = sample_running_df.copy()
        df["avgHR"] = 50.0  # < 60% de 190 = 114
        result = self.client.get_hr_zones(df, max_hr=190)
        z1 = result[result["zone"].str.startswith("Z1")]
        assert z1["nb_activites"].iloc[0] == len(df)


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
