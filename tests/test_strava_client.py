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

    def test_zero_pace_excluded_from_avg(self, sample_running_df):
        df = sample_running_df.copy()
        df.loc[0, "avgPace_sec"] = 0.0
        result = self.client.get_weekly_stats(df)
        # La moyenne ne doit pas être nulle si d'autres sorties ont un pace valide
        assert result["pace_moyen_sec"].iloc[-1] > 0

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
