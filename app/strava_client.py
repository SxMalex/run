"""
Client Strava — récupération et mise en cache des données d'entraînement.
"""

import os
import json
import time
import hashlib
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import pandas as pd
import numpy as np
import requests

logger = logging.getLogger(__name__)

CACHE_DIR = Path(os.getenv("CACHE_DIR", "/app/.cache"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))
TOKEN_FILE = CACHE_DIR / "strava_token.json"

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"


# ---------------------------------------------------------------------------
# Utilitaires de cache disque
# ---------------------------------------------------------------------------

def _cache_path(key: str) -> Path:
    safe_key = hashlib.md5(key.encode()).hexdigest()
    return CACHE_DIR / f"{safe_key}.json"


def _cache_get(key: str) -> Optional[object]:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        if time.time() - entry["timestamp"] < CACHE_TTL:
            return entry["data"]
        path.unlink(missing_ok=True)
    except (json.JSONDecodeError, KeyError, OSError) as e:
        logger.warning("Erreur lecture cache : %s", e)
    return None


def _cache_set(key: str, data: object) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(key)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time(), "data": data}, f, default=str)
    except OSError as e:
        logger.warning("Impossible d'écrire le cache : %s", e)


# ---------------------------------------------------------------------------
# Helpers OAuth (utilisés par l'UI Streamlit)
# ---------------------------------------------------------------------------

def get_auth_url(client_id: str, redirect_uri: str) -> str:
    """Génère l'URL d'autorisation Strava."""
    return (
        f"{STRAVA_AUTH_URL}"
        f"?client_id={client_id}"
        f"&redirect_uri={quote(redirect_uri, safe='')}"
        f"&response_type=code"
        f"&approval_prompt=auto"
        f"&scope=activity:read_all"
    )


def exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    """
    Échange un code d'autorisation contre des tokens d'accès.
    Sauvegarde les tokens dans TOKEN_FILE et retourne les données du token.
    """
    resp = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    resp.raise_for_status()
    token_data = resp.json()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(token_data, f)
    return token_data


# ---------------------------------------------------------------------------
# Classe principale
# ---------------------------------------------------------------------------

class StravaClient:
    """
    Encapsule la connexion à l'API Strava et la récupération des données.
    Utilise un cache disque pour limiter les appels à l'API.
    """

    def __init__(self):
        self.client_id = os.getenv("STRAVA_CLIENT_ID", "")
        self.client_secret = os.getenv("STRAVA_CLIENT_SECRET", "")
        self._access_token: Optional[str] = None
        self._connected = False

    # ------------------------------------------------------------------
    # Connexion et gestion des tokens
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """
        Charge les tokens depuis le fichier de cache et rafraîchit si nécessaire.
        """
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        if not TOKEN_FILE.exists():
            raise ValueError(
                "Tokens Strava non trouvés.\n"
                "Exécutez le script d'authentification :\n"
                "  python scripts/strava_auth.py\n"
                "puis redémarrez l'application."
            )

        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                token_data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            raise ValueError(f"Impossible de lire le fichier de token Strava : {e}") from e

        # Rafraîchit si le token expire dans moins de 5 minutes
        if time.time() > token_data.get("expires_at", 0) - 300:
            logger.info("Token Strava expiré, rafraîchissement...")
            token_data = self._refresh_token(token_data["refresh_token"])

        self._access_token = token_data["access_token"]
        self._connected = True
        logger.info("Connecté à Strava.")

    def _refresh_token(self, refresh_token: str) -> dict:
        """Rafraîchit le token d'accès via le refresh token."""
        if not self.client_id or not self.client_secret:
            raise ValueError(
                "STRAVA_CLIENT_ID et STRAVA_CLIENT_SECRET sont requis dans .env"
            )
        resp = requests.post(
            STRAVA_TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=30,
        )
        resp.raise_for_status()
        token_data = resp.json()
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(token_data, f)
        return token_data

    def _ensure_connected(self) -> None:
        if not self._connected or self._access_token is None:
            self.connect()

    def _get(self, endpoint: str, params: dict = None) -> dict | list:
        """Effectue un GET authentifié vers l'API Strava."""
        self._ensure_connected()
        headers = {"Authorization": f"Bearer {self._access_token}"}
        resp = requests.get(
            f"{STRAVA_API_BASE}/{endpoint}",
            headers=headers,
            params=params or {},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Récupération des activités
    # ------------------------------------------------------------------

    def get_activities(self, limit: int = 50) -> pd.DataFrame:
        """
        Récupère les N dernières activités et retourne un DataFrame.

        Colonnes retournées :
        activityId, startTimeLocal, activityName, activityType,
        distance_km, duration_min, avgPace, avgPace_sec,
        avgHR, maxHR, avgCadence, calories, elevationGain, avgSpeed_ms
        """
        cache_key = f"strava_activities_{self.client_id}_{limit}"
        cached = _cache_get(cache_key)
        if cached is not None:
            logger.info("Activités chargées depuis le cache.")
            df = pd.DataFrame(cached)
            if not df.empty:
                df["startTimeLocal"] = pd.to_datetime(df["startTimeLocal"], utc=True).dt.tz_convert(None)
            return df

        self._ensure_connected()
        logger.info("Récupération de %d activités depuis Strava...", limit)

        activities = []
        page = 1
        per_page = min(limit, 200)
        while len(activities) < limit:
            batch = self._get("athlete/activities", {"page": page, "per_page": per_page})
            if not batch:
                break
            activities.extend(batch)
            if len(batch) < per_page:
                break
            page += 1

        activities = activities[:limit]

        rows = []
        for act in activities:
            distance_m = act.get("distance", 0) or 0
            duration_s = act.get("moving_time", 0) or 0
            avg_speed_ms = act.get("average_speed", 0) or 0
            sport = act.get("sport_type") or act.get("type", "unknown")

            avg_pace_str = _speed_to_pace(avg_speed_ms)
            avg_pace_sec = _speed_to_pace_seconds(avg_speed_ms)
            cadence = _extract_cadence(act.get("average_cadence"), sport)

            rows.append({
                "activityId": act.get("id"),
                "startTimeLocal": act.get("start_date_local"),
                "activityName": act.get("name", ""),
                "activityType": _normalize_activity_type(sport),
                "distance_km": round(distance_m / 1000, 2),
                "duration_min": round(duration_s / 60, 1),
                "avgPace": avg_pace_str,
                "avgPace_sec": avg_pace_sec,
                "avgHR": act.get("average_heartrate"),
                "maxHR": act.get("max_heartrate"),
                "avgCadence": cadence,
                "calories": act.get("calories"),
                "elevationGain": act.get("total_elevation_gain"),
                "avgSpeed_ms": avg_speed_ms,
            })

        _cache_set(cache_key, rows)
        df = pd.DataFrame(rows)
        if not df.empty:
            df["startTimeLocal"] = pd.to_datetime(df["startTimeLocal"], utc=True).dt.tz_convert(None)
        return df

    def get_activity_details(self, activity_id: int) -> dict:
        """
        Récupère les détails complets d'une activité spécifique.
        Retourne un dictionnaire avec les métriques détaillées et les laps.
        """
        cache_key = f"strava_activity_detail_{activity_id}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        self._ensure_connected()
        logger.info("Récupération des détails de l'activité %s...", activity_id)

        try:
            details = self._get(f"activities/{activity_id}")
        except Exception as e:
            logger.error("Erreur récupération activité %s : %s", activity_id, e)
            return {}

        splits = self._extract_splits(activity_id, details)

        result = {
            "details": details,
            "splits": splits,
            "summary": self._summarize_activity(details),
        }

        _cache_set(cache_key, result)
        return result

    def _extract_splits(self, activity_id: int, details: dict) -> list[dict]:
        """Extrait les laps depuis l'API Strava."""
        try:
            laps = self._get(f"activities/{activity_id}/laps")
            sport = details.get("sport_type") or details.get("type", "unknown")
            splits = []
            for i, lap in enumerate(laps, 1):
                dist = lap.get("distance", 0) or 0
                dur = lap.get("elapsed_time", 0) or 0
                speed = lap.get("average_speed", 0) or 0
                cadence = _extract_cadence(lap.get("average_cadence"), sport)
                splits.append({
                    "lap": i,
                    "distance_km": round(dist / 1000, 2),
                    "duration_min": round(dur / 60, 2),
                    "pace": _speed_to_pace(speed),
                    "pace_sec": _speed_to_pace_seconds(speed),
                    "avgHR": lap.get("average_heartrate"),
                    "avgCadence": cadence,
                    "elevationGain": lap.get("total_elevation_gain"),
                })
            return splits
        except Exception as e:
            logger.warning("Impossible de récupérer les laps : %s", e)
            return []

    def _summarize_activity(self, details: dict) -> dict:
        """Extrait un résumé des détails d'une activité Strava."""
        distance_m = details.get("distance", 0) or 0
        duration_s = details.get("moving_time", 0) or 0
        avg_speed = details.get("average_speed", 0) or 0
        sport = details.get("sport_type") or details.get("type", "unknown")
        cadence = _extract_cadence(details.get("average_cadence"), sport)

        return {
            "distance_km": round(distance_m / 1000, 2),
            "duration_min": round(duration_s / 60, 1),
            "avgPace": _speed_to_pace(avg_speed),
            "avgHR": details.get("average_heartrate"),
            "maxHR": details.get("max_heartrate"),
            "avgCadence": cadence,
            "calories": details.get("calories"),
            "elevationGain": details.get("total_elevation_gain"),
            "avgPower": details.get("average_watts"),
        }

    # ------------------------------------------------------------------
    # Statistiques agrégées
    # ------------------------------------------------------------------

    def get_weekly_stats(self, df: pd.DataFrame) -> pd.DataFrame:
        """Agrège les activités par semaine."""
        if df.empty:
            return pd.DataFrame()

        running_df = df[df["activityType"] == "running"].copy()
        if running_df.empty:
            return pd.DataFrame()

        running_df["week"] = running_df["startTimeLocal"].dt.to_period("W").apply(
            lambda r: r.start_time
        )

        weekly = (
            running_df.groupby("week")
            .agg(
                km_total=("distance_km", "sum"),
                nb_sorties=("activityId", "count"),
                pace_moyen_sec=("avgPace_sec", lambda x: x[x > 0].mean() if (x > 0).any() else 0),
                hr_moyen=("avgHR", "mean"),
                denivele_total=("elevationGain", "sum"),
            )
            .reset_index()
        )

        weekly["pace_moyen"] = weekly["pace_moyen_sec"].apply(_seconds_to_pace_str)
        weekly["km_total"] = weekly["km_total"].round(1)
        weekly["hr_moyen"] = weekly["hr_moyen"].round(0)
        return weekly.sort_values("week")

    def get_monthly_stats(self, df: pd.DataFrame) -> pd.DataFrame:
        """Agrège les activités par mois."""
        if df.empty:
            return pd.DataFrame()

        running_df = df[df["activityType"] == "running"].copy()
        if running_df.empty:
            return pd.DataFrame()

        running_df["month"] = running_df["startTimeLocal"].dt.to_period("M").apply(
            lambda r: r.start_time
        )

        monthly = (
            running_df.groupby("month")
            .agg(
                km_total=("distance_km", "sum"),
                nb_sorties=("activityId", "count"),
                pace_moyen_sec=("avgPace_sec", lambda x: x[x > 0].mean() if (x > 0).any() else 0),
                hr_moyen=("avgHR", "mean"),
            )
            .reset_index()
        )

        monthly["pace_moyen"] = monthly["pace_moyen_sec"].apply(_seconds_to_pace_str)
        monthly["km_total"] = monthly["km_total"].round(1)
        monthly["hr_moyen"] = monthly["hr_moyen"].round(0)
        monthly["month_label"] = monthly["month"].dt.strftime("%b %Y")
        return monthly.sort_values("month")

    def get_hr_zones(self, df: pd.DataFrame, max_hr: int = 190) -> pd.DataFrame:
        """Estime la distribution des zones de fréquence cardiaque."""
        if df.empty:
            return pd.DataFrame()

        running_df = df[df["activityType"] == "running"].dropna(subset=["avgHR"]).copy()
        if running_df.empty:
            return pd.DataFrame()

        zones = {
            "Z1 — Récupération (<60%)": (0, 0.60),
            "Z2 — Endurance (60-70%)": (0.60, 0.70),
            "Z3 — Tempo (70-80%)": (0.70, 0.80),
            "Z4 — Seuil (80-90%)": (0.80, 0.90),
            "Z5 — VO2max (>90%)": (0.90, 1.01),
        }

        counts = {}
        for zone_name, (low, high) in zones.items():
            mask = (running_df["avgHR"] >= low * max_hr) & (running_df["avgHR"] < high * max_hr)
            counts[zone_name] = mask.sum()

        return pd.DataFrame(
            {"zone": list(counts.keys()), "nb_activites": list(counts.values())}
        )

    def get_summary_metrics(self, df: pd.DataFrame) -> dict:
        """Retourne les métriques résumées pour la semaine et le mois courants."""
        if df.empty:
            return {
                "km_semaine": 0, "km_mois": 0,
                "pace_moyen": "—", "hr_moyen": "—",
                "nb_sorties_semaine": 0, "nb_sorties_mois": 0,
            }

        running = df[df["activityType"] == "running"].copy()
        now = datetime.now()
        start_of_week = now - timedelta(days=now.weekday())
        start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        week_mask = running["startTimeLocal"] >= start_of_week
        month_mask = running["startTimeLocal"] >= start_of_month

        km_semaine = running.loc[week_mask, "distance_km"].sum()
        km_mois = running.loc[month_mask, "distance_km"].sum()
        nb_semaine = week_mask.sum()
        nb_mois = month_mask.sum()

        pace_vals = running.loc[running["avgPace_sec"] > 0, "avgPace_sec"]
        pace_moyen = _seconds_to_pace_str(pace_vals.mean()) if not pace_vals.empty else "—"

        hr_vals = running["avgHR"].dropna()
        hr_moyen = f"{int(hr_vals.mean())} bpm" if not hr_vals.empty else "—"

        return {
            "km_semaine": round(km_semaine, 1),
            "km_mois": round(km_mois, 1),
            "pace_moyen": pace_moyen,
            "hr_moyen": hr_moyen,
            "nb_sorties_semaine": int(nb_semaine),
            "nb_sorties_mois": int(nb_mois),
        }

    def invalidate_cache(self) -> None:
        """Supprime les fichiers de cache des données (préserve le token Strava)."""
        for f in CACHE_DIR.glob("*.json"):
            if f != TOKEN_FILE:
                f.unlink(missing_ok=True)
        logger.info("Cache invalidé.")


# ---------------------------------------------------------------------------
# Fonctions utilitaires
# ---------------------------------------------------------------------------

def _speed_to_pace(speed_ms: float) -> str:
    """Convertit une vitesse en m/s en pace min:sec/km."""
    if not speed_ms or speed_ms <= 0:
        return "—"
    return _seconds_to_pace_str(1000 / speed_ms)


def _speed_to_pace_seconds(speed_ms: float) -> float:
    """Convertit une vitesse en m/s en pace en secondes/km."""
    if not speed_ms or speed_ms <= 0:
        return 0.0
    return 1000 / speed_ms


def _seconds_to_pace_str(pace_sec: float) -> str:
    """Convertit un pace en secondes/km en chaîne min:sec/km."""
    if not pace_sec or pace_sec <= 0 or np.isnan(pace_sec):
        return "—"
    minutes = int(pace_sec // 60)
    seconds = int(pace_sec % 60)
    return f"{minutes}:{seconds:02d}/km"


def _extract_cadence(cadence_rpm: Optional[float], sport_type: str) -> Optional[float]:
    """
    Convertit la cadence Strava (RPM) en spm pour la course.
    Strava stocke la cadence en révolutions/minute — pour la course,
    1 révolution = 2 pas, donc spm = cadence_rpm * 2.
    """
    if cadence_rpm is None:
        return None
    if _normalize_activity_type(sport_type) == "running":
        return round(cadence_rpm * 2, 1)
    return cadence_rpm


def _normalize_activity_type(sport_type: str) -> str:
    """Normalise les types d'activité Strava en catégories lisibles."""
    mapping = {
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
    return mapping.get(sport_type, sport_type.lower() if sport_type else "unknown")
