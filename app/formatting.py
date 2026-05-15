"""
Fonctions de formatage pures (pace, vitesse, cadence, types d'activité Strava).

Aucune dépendance à Streamlit ni au client Strava — ce module est importable
depuis n'importe quelle couche (UI, client, logique métier) sans cycle.
"""

from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Pace / vitesse
# ---------------------------------------------------------------------------

def seconds_to_pace_str(pace_sec: float) -> str:
    """Convertit un pace en secondes/km en chaîne min:sec/km."""
    if not pace_sec or pace_sec <= 0 or np.isnan(pace_sec):
        return "—"
    minutes = int(pace_sec // 60)
    seconds = int(pace_sec % 60)
    return f"{minutes}:{seconds:02d}/km"


def speed_to_pace(speed_ms: float) -> str:
    """Convertit une vitesse en m/s en pace min:sec/km."""
    if not speed_ms or speed_ms <= 0:
        return "—"
    return seconds_to_pace_str(1000 / speed_ms)


def speed_to_pace_seconds(speed_ms: float) -> float:
    """Convertit une vitesse en m/s en pace en secondes/km."""
    if not speed_ms or speed_ms <= 0:
        return 0.0
    return 1000 / speed_ms


# ---------------------------------------------------------------------------
# Calories / cadence
# ---------------------------------------------------------------------------

def estimate_calories(
    calories_api: float | None,
    kilojoules: float | None,
) -> int | None:
    """
    Retourne les calories depuis Strava.
    Fallback : kilojoules (capteur de puissance vélo) → kcal via conversion physique.
    """
    if calories_api and calories_api > 0:
        return int(calories_api)
    # 1 kJ mécanique ≈ 1 kcal métabolique (rendement ~25% × 4.184 s'annulent)
    if kilojoules and kilojoules > 0:
        return int(kilojoules)
    return None


def extract_cadence(cadence_rpm: Optional[float], sport_type: str) -> Optional[float]:
    """
    Convertit la cadence Strava (RPM) en spm pour la course.
    Strava stocke la cadence en révolutions/minute — pour la course,
    1 révolution = 2 pas, donc spm = cadence_rpm * 2.
    """
    if cadence_rpm is None:
        return None
    if normalize_activity_type(sport_type) == "running":
        return round(cadence_rpm * 2, 1)
    return cadence_rpm


# ---------------------------------------------------------------------------
# Types d'activité / workout
# ---------------------------------------------------------------------------

_ACTIVITY_TYPE_MAP = {
    # Course
    "Run": "running",
    "TrailRun": "running",
    "VirtualRun": "running",
    "Treadmill": "running",
    "running": "running",
    "trail_running": "running",
    # Vélo
    "Ride": "cycling",
    "VirtualRide": "cycling",
    "MountainBikeRide": "cycling",
    "GravelRide": "cycling",
    "EBikeRide": "cycling",
    "cycling": "cycling",
    # Natation
    "Swim": "swimming",
    "swimming": "swimming",
    # Marche / Randonnée
    "Walk": "walking",
    "walking": "walking",
    "Hike": "hiking",
    "hiking": "hiking",
    # Musculation / Autre
    "WeightTraining": "strength",
    "strength_training": "strength",
    "Yoga": "yoga",
    "yoga": "yoga",
    "Workout": "cardio",
    "Crossfit": "cardio",
    "cardio_training": "cardio",
}


def normalize_activity_type(sport_type: str) -> str:
    """Normalise les types d'activité Strava en catégories lisibles."""
    return _ACTIVITY_TYPE_MAP.get(
        sport_type, sport_type.lower() if sport_type else "unknown"
    )


_WORKOUT_TYPE_LABELS = {
    0: "Normal", 1: "Race", 2: "Sortie longue", 3: "Entraînement",
    10: "Normal", 11: "Race", 12: "Sortie",
}


def workout_type_label(wt) -> str:
    """Traduit le workout_type Strava (entier) en libellé lisible."""
    return _WORKOUT_TYPE_LABELS.get(int(wt or 0), "Normal")


# ---------------------------------------------------------------------------
# Splits / cartes
# ---------------------------------------------------------------------------

def extract_splits_metric(details: dict) -> list[dict]:
    """Extrait les splits par kilomètre depuis les détails d'une activité Strava."""
    rows = []
    for i, s in enumerate(details.get("splits_metric", [])):
        speed = s.get("average_speed", 0) or 0
        rows.append({
            "split": s.get("split", i + 1),
            "distance_m": round(s.get("distance", 0) or 0, 1),
            "elapsed_s": s.get("elapsed_time", 0) or 0,
            "moving_s": s.get("moving_time", 0) or 0,
            "pace_sec": speed_to_pace_seconds(speed),
            "pace": speed_to_pace(speed),
            "avg_hr": s.get("average_heartrate"),
            "elev_diff": s.get("elevation_difference", 0) or 0,
            "pace_zone": s.get("pace_zone"),
        })
    return rows


def decimate(values: list, target: int = 1000) -> list:
    """
    Sous-échantillonne une liste en gardant ~target points équirépartis.
    Utile pour réduire la charge Plotly sur les streams haute résolution
    (5k-15k points/activité) sans perte visuelle.
    """
    n = len(values)
    if n <= target or target <= 0:
        return list(values)
    step = n / target
    return [values[int(i * step)] for i in range(target)]


def map_zoom(lats: list[float], lons: list[float]) -> tuple[float, float, int]:
    """Retourne (center_lat, center_lon, zoom) depuis une liste de coordonnées."""
    center_lat = (min(lats) + max(lats)) / 2
    center_lon = (min(lons) + max(lons)) / 2
    max_range = max(max(lats) - min(lats), max(lons) - min(lons))
    if max_range < 0.01:
        zoom = 15
    elif max_range < 0.05:
        zoom = 13
    elif max_range < 0.15:
        zoom = 12
    elif max_range < 0.4:
        zoom = 11
    elif max_range < 1.0:
        zoom = 10
    else:
        zoom = 9
    return center_lat, center_lon, zoom
