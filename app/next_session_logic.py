"""
Logique métier de la page Prochaine sortie — fonctions pures testables
sans dépendance à Streamlit.
"""

import numpy as np
import pandas as pd
from datetime import date, datetime, timedelta, timezone
from formatting import seconds_to_pace_str

_JOURS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
_MOIS_FR = ["jan.", "fév.", "mars", "avr.", "mai", "juin",
            "juil.", "août", "sept.", "oct.", "nov.", "déc."]

# Seuil de pace de référence pour le calcul TSB : percentile utilisé sur les
# sorties longues pour estimer la FC threshold ; 330 s/km (~5:30/km) si absent.
_TSB_THRESHOLD_PERCENTILE = 0.15
_DEFAULT_THRESHOLD_PACE_SEC = 330

SESSION_TYPES = {
    "recuperation": {
        "label": "Récupération active",
        "icon": "💤",
        "color": "#3b82f6",
        "description": "Ta charge récente est élevée. Une sortie légère pour relancer la circulation sans stresser l'organisme.",
        "dist_factor": 0.60,
        "pace_factor": 1.15,
        "elev_factor": 0.4,
    },
    "endurance": {
        "label": "Endurance fondamentale",
        "icon": "🏃",
        "color": "#16a34a",
        "description": "Séance clé du coureur. Allure confortable, conversation possible. Développe le moteur aérobie.",
        "dist_factor": 1.00,
        "pace_factor": 1.05,
        "elev_factor": 1.0,
    },
    "tempo": {
        "label": "Tempo / Seuil",
        "icon": "⚡",
        "color": "#ea580c",
        "description": "Tu es bien reposé. Séance à allure soutenue pour repousser ton seuil lactique.",
        "dist_factor": 0.80,
        "pace_factor": 0.92,
        "elev_factor": 0.6,
    },
    "sortie_longue": {
        "label": "Sortie longue",
        "icon": "🏔️",
        "color": "#7c3aed",
        "description": "Excellente fraîcheur. C'est le moment idéal pour une longue sortie et construire ton endurance.",
        "dist_factor": 1.40,
        "pace_factor": 1.10,
        "elev_factor": 1.3,
    },
}


def suggest_next_date(
    running_df: pd.DataFrame,
    session_key: str,
    days_since: int,
    tsb: float,
) -> date:
    """Suggère la prochaine date selon la fréquence habituelle et la fatigue."""
    today = date.today()

    # Gap typique entre séances (sur les 15 dernières)
    recent_dates = (
        running_df
        .sort_values("startTimeLocal", ascending=False)
        .head(15)["startTimeLocal"]
        .dt.date
        .tolist()
    )
    if len(recent_dates) >= 3:
        gaps = [
            (recent_dates[i] - recent_dates[i + 1]).days
            for i in range(min(10, len(recent_dates) - 1))
            if (recent_dates[i] - recent_dates[i + 1]).days > 0
        ]
        typical_gap = round(sum(gaps) / len(gaps)) if gaps else 2
    else:
        typical_gap = 2
    typical_gap = max(1, min(typical_gap, 5))

    # Ajustement fatigue (TSB)
    if tsb < -20:
        fatigue_adj = +1    # très fatigué → reporter
    elif tsb > 10:
        fatigue_adj = -1    # bien reposé → avancer
    else:
        fatigue_adj = 0

    # Ajustement type de séance
    if session_key in ("tempo", "sortie_longue"):
        session_adj = +1    # séance exigeante → besoin d'être plus frais
    elif session_key == "recuperation":
        session_adj = -1    # séance légère → peut y aller plus tôt
    else:
        session_adj = 0

    target_gap = max(1, typical_gap + fatigue_adj + session_adj)
    days_until = max(0, target_gap - days_since)
    return today + timedelta(days=days_until)


def format_date_fr(d: date) -> str:
    """Formate une date en français lisible (ex. 'Demain', 'Jeudi 1 mai')."""
    today = date.today()
    delta = (d - today).days
    if delta == 0:
        return "Aujourd'hui"
    if delta == 1:
        return "Demain"
    return f"{_JOURS_FR[d.weekday()]} {d.day} {_MOIS_FR[d.month - 1]}"


def compute_pmc_series(running_df: pd.DataFrame, threshold_sec: float) -> pd.DataFrame:
    """
    Calcule la série quotidienne du modèle Performance Management Chart.
    Retourne un DataFrame avec colonnes : date, tss, ctl, atl, tsb.

    Conventions :
    - `ctl` et `atl` sont les valeurs en fin de journée (après TSS du jour),
    - `tsb` est la fraîcheur en début de journée (avant TSS du jour) — ce qui
      reflète l'état du coureur au moment où il commence sa séance.

    Retourne un DataFrame vide si pas de données exploitables.
    """
    empty = pd.DataFrame(columns=["date", "tss", "ctl", "atl", "tsb"])
    if running_df.empty or "avgPace_sec" not in running_df.columns:
        return empty
    runs = running_df[running_df["avgPace_sec"] > 0].copy()
    if runs.empty:
        return empty

    runs["duration_h"] = runs["duration_min"] / 60
    runs["IF"] = (threshold_sec / runs["avgPace_sec"]).clip(upper=1.5)
    runs["tss"] = (runs["duration_h"] * runs["IF"] ** 2 * 100).clip(upper=400)
    runs["day"] = runs["startTimeLocal"].dt.normalize()

    daily_tss = runs.groupby("day")["tss"].sum()
    today_ts = pd.Timestamp(datetime.now().date())
    full_range = pd.date_range(daily_tss.index.min(), today_ts, freq="D")
    daily_full = pd.Series(0.0, index=full_range)
    daily_full.update(daily_tss)

    k_ctl = np.exp(-1 / 42)
    k_atl = np.exp(-1 / 7)
    ctl_v = atl_v = 0.0
    records = []
    for d, tss in daily_full.items():
        tsb_v = ctl_v - atl_v
        ctl_v = ctl_v * k_ctl + tss * (1 - k_ctl)
        atl_v = atl_v * k_atl + tss * (1 - k_atl)
        records.append({"date": d, "tss": tss, "ctl": ctl_v, "atl": atl_v, "tsb": tsb_v})

    return pd.DataFrame(records)


def compute_tsb(running_df: pd.DataFrame) -> tuple[float, float, float]:
    """Retourne (CTL, ATL, TSB) actuels à partir des activités de course."""
    if running_df.empty or "avgPace_sec" not in running_df.columns:
        return 0.0, 0.0, 0.0
    runs = running_df[running_df["avgPace_sec"] > 0]
    if runs.empty:
        return 0.0, 0.0, 0.0

    long_runs = runs[runs["distance_km"] >= 8]
    threshold_sec = (
        int(long_runs["avgPace_sec"].quantile(_TSB_THRESHOLD_PERCENTILE))
        if not long_runs.empty
        else _DEFAULT_THRESHOLD_PACE_SEC
    )

    pmc = compute_pmc_series(running_df, threshold_sec)
    if pmc.empty:
        return 0.0, 0.0, 0.0
    last = pmc.iloc[-1]
    ctl_v = float(last["ctl"])
    atl_v = float(last["atl"])
    return round(ctl_v, 1), round(atl_v, 1), round(ctl_v - atl_v, 1)


def recommend_session(running_df: pd.DataFrame) -> dict:
    """Analyse les dernières sorties et retourne un dict de recommandations."""
    recent = running_df.sort_values("startTimeLocal", ascending=False).head(20)

    avg_dist = recent["distance_km"].mean()
    avg_pace_sec = recent.loc[recent["avgPace_sec"] > 0, "avgPace_sec"].mean()
    avg_elev = recent["elevationGain"].dropna().mean()

    last_run_date = recent["startTimeLocal"].max()
    days_since = (datetime.now() - last_run_date).days

    long_runs = recent[recent["distance_km"] >= avg_dist * 1.2]
    days_since_long = (
        (datetime.now() - long_runs["startTimeLocal"].max()).days
        if not long_runs.empty else 999
    )

    ctl, atl, tsb = compute_tsb(running_df)

    if tsb < -20:
        session_key = "recuperation"
    elif tsb > 10 and days_since_long >= 6:
        session_key = "sortie_longue"
    elif tsb > 10:
        session_key = "tempo"
    else:
        session_key = "endurance"

    if days_since >= 5:
        session_key = "endurance"

    s = SESSION_TYPES[session_key]
    target_dist_km = round(avg_dist * s["dist_factor"], 1)
    target_dist_km = max(3.0, target_dist_km)
    target_pace_sec = avg_pace_sec * s["pace_factor"]
    target_elev = round(avg_elev * s["elev_factor"]) if avg_elev and not np.isnan(avg_elev) else 0
    duration_min = round(target_dist_km * target_pace_sec / 60)

    suggested_date = suggest_next_date(running_df, session_key, days_since, tsb)

    return {
        "session_key": session_key,
        "session": s,
        "ctl": ctl, "atl": atl, "tsb": tsb,
        "days_since": days_since,
        "target_dist_km": target_dist_km,
        "target_pace_sec": target_pace_sec,
        "target_pace_str": seconds_to_pace_str(target_pace_sec),
        "target_elev": target_elev,
        "duration_min": duration_min,
        "avg_dist": round(avg_dist, 1),
        "avg_pace_str": seconds_to_pace_str(avg_pace_sec),
        "suggested_date": suggested_date,
        "suggested_date_str": format_date_fr(suggested_date),
    }


def parse_ors_route(geojson: dict) -> dict | None:
    """Extrait coordonnées, distance réelle et dénivelé depuis la réponse ORS."""
    try:
        feature = geojson["features"][0]
        coords = feature["geometry"]["coordinates"]
        summary = feature["properties"]["summary"]
        ascent = feature["properties"].get("ascent", 0) or 0

        if not coords:
            return None

        lats = [c[1] for c in coords]
        lons = [c[0] for c in coords]
        eles = [c[2] for c in coords] if len(coords[0]) > 2 else []

        return {
            "lats": lats,
            "lons": lons,
            "elevations": eles,
            "distance_km": round(summary["distance"] / 1000, 2),
            "duration_s": summary.get("duration", 0),
            "ascent_m": round(ascent),
        }
    except (KeyError, IndexError, TypeError):
        return None


def build_gpx(route: dict, session_label: str, target_pace_str: str) -> str:
    """Génère un fichier GPX (course) compatible Garmin Connect."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    name = f"Prochaine sortie — {session_label}"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="Running Dashboard"',
        '     xmlns="http://www.topografix.com/GPX/1/1"',
        '     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
        '     xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd">',
        f'  <metadata><name>{name}</name><time>{now}</time></metadata>',
        '  <trk>',
        f'    <name>{name}</name>',
        f'    <desc>Allure cible : {target_pace_str} — {route["distance_km"]:.2f} km · D+ {route["ascent_m"]} m</desc>',
        '    <trkseg>',
    ]
    for i, (lat, lon) in enumerate(zip(route["lats"], route["lons"])):
        ele_tag = f"<ele>{route['elevations'][i]:.1f}</ele>" if route["elevations"] else ""
        lines.append(f'      <trkpt lat="{lat:.6f}" lon="{lon:.6f}">{ele_tag}</trkpt>')
    lines += ["    </trkseg>", "  </trk>", "</gpx>"]
    return "\n".join(lines)
