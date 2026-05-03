"""
Client Strava — récupération et mise en cache des données d'entraînement.

Multi-user : le token vit dans `st.session_state` côté UI (jamais sur disque).
Le cache disque est cloisonné par athlete_id (sous-dossier dédié), donc
deux utilisateurs ne peuvent pas se voir mutuellement.
"""

import os
import json
import time
import shutil
import hashlib
import logging
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote

import pandas as pd
import numpy as np
import requests

logger = logging.getLogger(__name__)

CACHE_DIR = Path(os.getenv("CACHE_DIR", "/app/.cache"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"


# ---------------------------------------------------------------------------
# Utilitaires de cache disque (cloisonné par athlete_id)
# ---------------------------------------------------------------------------

def _cache_path(athlete_id: int, key: str) -> Path:
    """Cache file path under a per-athlete subdirectory."""
    safe_key = hashlib.md5(key.encode()).hexdigest()
    return CACHE_DIR / str(athlete_id) / f"{safe_key}.json"


def _cache_get(athlete_id: int, key: str) -> Optional[object]:
    path = _cache_path(athlete_id, key)
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


def _cache_set(athlete_id: int, key: str, data: object) -> None:
    path = _cache_path(athlete_id, key)
    path.parent.mkdir(parents=True, exist_ok=True)
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
        f"&scope=activity:read_all,profile:read_all"
    )


def exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    """
    Échange un code d'autorisation contre des tokens d'accès.
    Retourne le dict de token (l'appelant le stocke en session_state).
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
    return resp.json()


# ---------------------------------------------------------------------------
# Classe principale
# ---------------------------------------------------------------------------

class StravaClient:
    """
    Encapsule la connexion à l'API Strava et la récupération des données.

    Le token vit dans `st.session_state` côté UI ; on le passe au constructeur
    et `on_token_update` permet d'écrire le token rafraîchi dans la session.
    """

    def __init__(
        self,
        token: dict,
        athlete_id: int,
        on_token_update: Optional[Callable[[dict], None]] = None,
    ):
        self.client_id = os.getenv("STRAVA_CLIENT_ID", "")
        self.client_secret = os.getenv("STRAVA_CLIENT_SECRET", "")
        self.athlete_id = int(athlete_id)
        self._token = token
        self._on_token_update = on_token_update

    # ------------------------------------------------------------------
    # Connexion et gestion des tokens
    # ------------------------------------------------------------------

    def _ensure_fresh_token(self) -> None:
        """Rafraîchit le token s'il expire dans moins de 5 minutes."""
        if not self._token or "access_token" not in self._token:
            raise ValueError("Token Strava manquant ou invalide.")
        if time.time() > self._token.get("expires_at", 0) - 300:
            logger.info("Token Strava expiré, rafraîchissement...")
            self._token = self._refresh_token(self._token["refresh_token"])
            if self._on_token_update is not None:
                self._on_token_update(self._token)

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
        return resp.json()

    def _get(self, endpoint: str, params: dict = None) -> dict | list:
        """Effectue un GET authentifié vers l'API Strava, avec 1 retry sur erreur 5xx."""
        self._ensure_fresh_token()
        headers = {"Authorization": f"Bearer {self._token['access_token']}"}
        url = f"{STRAVA_API_BASE}/{endpoint}"

        # Tour 0 : si 5xx → on retente après 2 s. Tour 1 : on laisse remonter quoi qu'il arrive.
        resp = requests.get(url, headers=headers, params=params or {}, timeout=30)
        if resp.status_code >= 500:
            logger.warning("Strava 5xx (%s) sur %s, retry dans 2s…", resp.status_code, endpoint)
            time.sleep(2)
            resp = requests.get(url, headers=headers, params=params or {}, timeout=30)

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
        cache_key = f"activities_{limit}"
        cached = _cache_get(self.athlete_id, cache_key)
        if cached is not None:
            logger.info("Activités chargées depuis le cache.")
            df = pd.DataFrame(cached)
            if not df.empty:
                df["startTimeLocal"] = pd.to_datetime(df["startTimeLocal"], utc=True).dt.tz_convert(None)
            return df

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
            distance_m = act.get("distance", 0)
            duration_s = act.get("moving_time", 0)
            avg_speed_ms = act.get("average_speed", 0)
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
                "calories": _estimate_calories(
                    act.get("calories"),
                    act.get("kilojoules"),
                ),
                "elevationGain": act.get("total_elevation_gain"),
                "avgSpeed_ms": avg_speed_ms,
                "kudosCount": act.get("kudos_count", 0),
                "startLat": (act.get("start_latlng") or [None, None])[0],
                "startLon": (act.get("start_latlng") or [None, None])[1],
                "workoutType": act.get("workout_type", 0) or 0,
            })

        _cache_set(self.athlete_id, cache_key, rows)
        df = pd.DataFrame(rows)
        if not df.empty:
            df["startTimeLocal"] = pd.to_datetime(df["startTimeLocal"], utc=True).dt.tz_convert(None)
        return df

    def get_activity_details(self, activity_id: int) -> dict:
        """
        Récupère les détails complets d'une activité spécifique.
        Retourne un dict avec les clés "details", "splits", "splits_metric", "summary".
        Retourne {} en cas d'erreur API (l'erreur est loggée) ; les appelants
        doivent tester `if not result` pour distinguer erreur et données réelles.
        """
        cache_key = f"activity_detail_{activity_id}"
        cached = _cache_get(self.athlete_id, cache_key)
        if cached is not None:
            return cached

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
            "splits_metric": _extract_splits_metric(details),
            "summary": self._summarize_activity(details),
        }

        _cache_set(self.athlete_id, cache_key, result)
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
        running_df = _filter_running(df)
        if running_df is None:
            return pd.DataFrame()
        running_df["week"] = running_df["startTimeLocal"].dt.to_period("W").apply(
            lambda r: r.start_time
        )
        weekly = (
            running_df.groupby("week")
            .agg(
                km_total=("distance_km", "sum"),
                nb_sorties=("activityId", "count"),
                pace_moyen_sec=("avgPace_sec", _agg_mean_pace),
                hr_moyen=("avgHR", "mean"),
                denivele_total=("elevationGain", "sum"),
            )
            .reset_index()
        )
        return _finalize_stats(weekly).sort_values("week")

    def get_monthly_stats(self, df: pd.DataFrame) -> pd.DataFrame:
        """Agrège les activités par mois."""
        running_df = _filter_running(df)
        if running_df is None:
            return pd.DataFrame()
        running_df["month"] = running_df["startTimeLocal"].dt.to_period("M").apply(
            lambda r: r.start_time
        )
        monthly = (
            running_df.groupby("month")
            .agg(
                km_total=("distance_km", "sum"),
                nb_sorties=("activityId", "count"),
                pace_moyen_sec=("avgPace_sec", _agg_mean_pace),
                hr_moyen=("avgHR", "mean"),
            )
            .reset_index()
        )
        monthly = _finalize_stats(monthly)
        monthly["month_label"] = monthly["month"].dt.strftime("%b %Y")
        return monthly.sort_values("month")

    def get_hr_zones(self, df: pd.DataFrame, hr_zones: list) -> pd.DataFrame:
        """Distribue les activités dans les zones FC définies par Strava (bornes bpm réelles)."""
        if df.empty or not hr_zones:
            return pd.DataFrame()

        running_df = df[df["activityType"] == "running"].dropna(subset=["avgHR"]).copy()
        if running_df.empty:
            return pd.DataFrame()

        rows = []
        for i, zone in enumerate(hr_zones, 1):
            low = zone.get("min", 0) or 0
            high = zone.get("max", -1)
            unlimited = not high or high < 0
            label = f"Z{i} (≥{low} bpm)" if unlimited else f"Z{i} ({low}–{high} bpm)"
            mask = running_df["avgHR"] >= low if unlimited else (
                (running_df["avgHR"] >= low) & (running_df["avgHR"] < high)
            )
            rows.append({"zone": label, "nb_activites": int(mask.sum())})

        return pd.DataFrame(rows)

    def get_summary_metrics(self, df: pd.DataFrame) -> dict:
        """Retourne les métriques résumées pour la semaine et le mois courants."""
        if df.empty:
            return {
                "km_semaine": 0, "km_mois": 0,
                "pace_moyen": "—", "hr_moyen": "—",
                "nb_sorties_semaine": 0, "nb_sorties_mois": 0,
            }

        running = df[df["activityType"] == "running"].copy()
        from datetime import datetime, timedelta
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

    def get_athlete(self) -> dict:
        """Retourne le profil de l'athlète (poids, chaussures, id…)."""
        cache_key = "athlete"
        cached = _cache_get(self.athlete_id, cache_key)
        if cached is not None:
            return cached
        try:
            data = self._get("athlete")
            _cache_set(self.athlete_id, cache_key, data)
            return data
        except Exception as e:
            logger.warning("Profil athlète indisponible : %s", e)
            return {}

    def get_athlete_stats(self) -> dict:
        """Retourne les totaux all-time / YTD / 4 semaines pour course et vélo."""
        cache_key = "athlete_stats"
        cached = _cache_get(self.athlete_id, cache_key)
        if cached is not None:
            return cached
        try:
            data = self._get(f"athletes/{self.athlete_id}/stats")
            _cache_set(self.athlete_id, cache_key, data)
            return data
        except Exception as e:
            logger.warning("Stats athlète indisponibles : %s", e)
            return {}

    def get_athlete_zones(self) -> dict:
        """Retourne les zones FC (et puissance) configurées dans Strava."""
        cache_key = "zones"
        cached = _cache_get(self.athlete_id, cache_key)
        if cached is not None:
            return cached
        try:
            data = self._get("athlete/zones")
            _cache_set(self.athlete_id, cache_key, data)
            return data
        except Exception as e:
            logger.warning("Zones athlète indisponibles : %s", e)
            return {}

    def get_best_efforts(self, activity_ids: list[int]) -> dict[str, dict]:
        """
        Récupère les best_efforts Strava (meilleurs temps sur distances standard)
        depuis les détails des activités fournies.
        Retourne un dict {nom_distance: {elapsed_time, date, activity_name}}.
        Conserve le meilleur temps toutes activités confondues.
        """
        cache_key = f"best_efforts_{'_'.join(str(i) for i in sorted(activity_ids))}"
        cached = _cache_get(self.athlete_id, cache_key)
        if cached is not None:
            return cached

        best: dict[str, dict] = {}

        for activity_id in activity_ids:
            try:
                details = self._get(f"activities/{activity_id}")
            except Exception as e:
                logger.warning("Impossible de récupérer l'activité %s : %s", activity_id, e)
                continue

            activity_name = details.get("name", "")
            date_str = details.get("start_date_local", "")

            for effort in details.get("best_efforts", []):
                name = effort.get("name", "")
                elapsed = effort.get("elapsed_time")
                pr_rank = effort.get("pr_rank")
                if not elapsed or not name:
                    continue
                # On garde le meilleur effort toutes activités confondues
                if name not in best or elapsed < best[name]["elapsed_time"]:
                    best[name] = {
                        "elapsed_time": elapsed,
                        "date": date_str,
                        "activity_name": activity_name,
                        "pr_rank": pr_rank,
                    }

        _cache_set(self.athlete_id, cache_key, best)
        return best

    def get_splits_aggregate(self, activity_ids: list[int]) -> pd.DataFrame:
        """
        Charge les splits_metric pour une liste d'activités et retourne un DataFrame
        long : activityId, split, pace_sec, pace_min, avg_hr, elev_diff.
        Un délai de 0.5 s est appliqué entre chaque appel API réel pour respecter
        le rate limit Strava (100 req/15 min) ; les hits de cache sont instantanés.
        """
        rows = []
        for aid in activity_ids:
            cache_key = f"activity_detail_{aid}"
            detail_data = _cache_get(self.athlete_id, cache_key)
            if detail_data is None:
                try:
                    detail_data = self.get_activity_details(aid)
                    time.sleep(0.5)
                except Exception as e:
                    logger.warning("Splits indisponibles pour l'activité %s : %s", aid, e)
                    time.sleep(1.0)
                    continue
            if not detail_data:
                continue
            for s in detail_data.get("splits_metric", []):
                if s["pace_sec"] <= 0:
                    continue
                rows.append({
                    "activityId": aid,
                    "split": s["split"],
                    "pace_sec": s["pace_sec"],
                    "pace_min": s["pace_sec"] / 60,
                    "avg_hr": s.get("avg_hr"),
                    "elev_diff": s.get("elev_diff", 0) or 0,
                })
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    def get_streams(self, activity_id: int) -> dict[str, list]:
        """
        Récupère les streams haute-résolution d'une activité.
        Retourne un dict {type: [valeurs]} — types disponibles selon l'appareil :
        time, distance, heartrate, altitude, velocity_smooth, cadence, grade_smooth.
        """
        cache_key = f"streams_{activity_id}"
        cached = _cache_get(self.athlete_id, cache_key)
        if cached is not None:
            return cached

        keys = "time,distance,heartrate,altitude,velocity_smooth,cadence,grade_smooth"
        try:
            raw = self._get(
                f"activities/{activity_id}/streams",
                {"keys": keys, "key_by_type": "true"},
            )
            result = {k: v.get("data", []) for k, v in raw.items() if isinstance(v, dict)}
            _cache_set(self.athlete_id, cache_key, result)
            return result
        except Exception as e:
            logger.warning("Streams indisponibles pour l'activité %s : %s", activity_id, e)
            return {}

    def invalidate_cache(self) -> None:
        """Supprime le cache disque de cet athlète uniquement."""
        athlete_dir = CACHE_DIR / str(self.athlete_id)
        if athlete_dir.exists():
            shutil.rmtree(athlete_dir, ignore_errors=True)
        logger.info("Cache invalidé pour l'athlète %s.", self.athlete_id)


# ---------------------------------------------------------------------------
# Wrapper d'erreur partagé pour les pages Streamlit
# ---------------------------------------------------------------------------

def safe_load_activities(
    client: StravaClient, limit: int
) -> tuple[pd.DataFrame, str | None]:
    """
    Encapsule `client.get_activities(limit)` avec des messages d'erreur lisibles.
    Retourne (DataFrame, message). `message` est None en cas de succès.
    """
    try:
        df = client.get_activities(limit=limit)
        return df, None
    except requests.HTTPError as e:
        status = getattr(e.response, "status_code", 0) or 0
        if status == 401:
            return pd.DataFrame(), "Token expiré ou révoqué. Reconnecte-toi à Strava."
        if status == 429:
            return pd.DataFrame(), "Limite de requêtes Strava atteinte. Réessaie dans 15 minutes."
        if status >= 500:
            return pd.DataFrame(), (
                f"Les serveurs Strava sont temporairement indisponibles (erreur {status}). "
                "Réessaie dans quelques instants."
            )
        return pd.DataFrame(), f"Erreur Strava ({status})"
    except ValueError as e:
        # Token absent / illisible / config manquante.
        return pd.DataFrame(), str(e)
    except requests.RequestException as e:
        return pd.DataFrame(), f"Erreur réseau Strava : {e}"
    except Exception as e:
        logger.exception("Erreur inattendue dans safe_load_activities")
        return pd.DataFrame(), f"Erreur inattendue : {e}"


# ---------------------------------------------------------------------------
# Fonctions utilitaires
# ---------------------------------------------------------------------------

def _estimate_calories(
    calories_api: float | None,
    kilojoules: float | None,
) -> int | None:
    """
    Retourne les calories depuis Strava.
    Fallback : kilojoules (capteur de puissance vélo) → kcal via conversion physique.
    """
    if calories_api and calories_api > 0:
        return int(calories_api)
    # Convention : 1 kJ mécanique ≈ 1 kcal métabolique (rendement ~25% × 4.184 s'annulent)
    if kilojoules and kilojoules > 0:
        return int(kilojoules)
    return None


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


def _agg_mean_pace(x):
    """Moyenne de pace en ignorant les valeurs nulles (utilisée dans groupby.agg)."""
    return x[x > 0].mean() if (x > 0).any() else 0


def _filter_running(df: pd.DataFrame) -> pd.DataFrame | None:
    """Filtre aux activités de course ; retourne None si vide."""
    if df.empty:
        return None
    runs = df[df["activityType"] == "running"].copy()
    return runs if not runs.empty else None


def _finalize_stats(agg: pd.DataFrame) -> pd.DataFrame:
    """Applique les transformations communes aux DataFrames d'agrégation."""
    agg["pace_moyen"] = agg["pace_moyen_sec"].apply(_seconds_to_pace_str)
    agg["km_total"] = agg["km_total"].round(1)
    agg["hr_moyen"] = agg["hr_moyen"].round(0)
    return agg


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


_WORKOUT_TYPE_LABELS = {
    0: "Normal", 1: "Race", 2: "Sortie longue", 3: "Entraînement",
    10: "Normal", 11: "Race", 12: "Sortie",
}


def workout_type_label(wt) -> str:
    """Traduit le workout_type Strava (entier) en libellé lisible."""
    return _WORKOUT_TYPE_LABELS.get(int(wt or 0), "Normal")


def _extract_splits_metric(details: dict) -> list[dict]:
    """Extrait les splits par kilomètre depuis les détails d'une activité."""
    rows = []
    for i, s in enumerate(details.get("splits_metric", [])):
        speed = s.get("average_speed", 0) or 0
        rows.append({
            "split": s.get("split", i + 1),
            "distance_m": round(s.get("distance", 0) or 0, 1),
            "elapsed_s": s.get("elapsed_time", 0) or 0,
            "moving_s": s.get("moving_time", 0) or 0,
            "pace_sec": _speed_to_pace_seconds(speed),
            "pace": _speed_to_pace(speed),
            "avg_hr": s.get("average_heartrate"),
            "elev_diff": s.get("elevation_difference", 0) or 0,
            "pace_zone": s.get("pace_zone"),
        })
    return rows


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
