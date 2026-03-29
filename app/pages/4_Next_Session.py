"""
Page Prochaine sortie — Génère un parcours inédit et des objectifs
basés sur les dernières activités et la charge d'entraînement.
"""

import os
import sys
import requests
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strava_client import StravaClient, _seconds_to_pace_str

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Prochaine sortie — Running Dashboard",
    page_icon="🗺️",
    layout="wide",
)

ORS_API_BASE = "https://api.openrouteservice.org/v2"

# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
@st.cache_resource
def get_strava_client() -> StravaClient:
    return StravaClient()


@st.cache_data(ttl=3600, show_spinner="Chargement des activités...")
def load_activities(limit: int = 200) -> tuple[pd.DataFrame, str | None]:
    client = get_strava_client()
    try:
        df = client.get_activities(limit=limit)
        return df, None
    except Exception as e:
        return pd.DataFrame(), str(e)


# ---------------------------------------------------------------------------
# Algorithme de recommandation
# ---------------------------------------------------------------------------

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


def _compute_tsb(running_df: pd.DataFrame) -> tuple[float, float, float]:
    """Retourne (CTL, ATL, TSB) actuels à partir des activités de course."""
    runs = running_df[running_df["avgPace_sec"] > 0].copy()
    if runs.empty:
        return 0.0, 0.0, 0.0

    # Allure seuil auto-détectée (15e centile des sorties ≥ 8 km)
    long_runs = runs[runs["distance_km"] >= 8]
    threshold_sec = int(long_runs["avgPace_sec"].quantile(0.15)) if not long_runs.empty else 330

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
    for tss in daily_full:
        ctl_v = ctl_v * k_ctl + tss * (1 - k_ctl)
        atl_v = atl_v * k_atl + tss * (1 - k_atl)

    tsb_v = ctl_v - atl_v
    return round(ctl_v, 1), round(atl_v, 1), round(tsb_v, 1)


def _recommend_session(running_df: pd.DataFrame) -> dict:
    """
    Analyse les dernières sorties et retourne un dict de recommandations.
    """
    recent = running_df.sort_values("startTimeLocal", ascending=False).head(20)

    # Métriques de base
    avg_dist = recent["distance_km"].mean()
    avg_pace_sec = recent.loc[recent["avgPace_sec"] > 0, "avgPace_sec"].mean()
    avg_elev = recent["elevationGain"].dropna().mean()

    last_run_date = recent["startTimeLocal"].max()
    days_since = (datetime.now() - last_run_date).days

    # Cherche si une sortie longue a eu lieu récemment
    long_runs = recent[recent["distance_km"] >= avg_dist * 1.2]
    days_since_long = (
        (datetime.now() - long_runs["startTimeLocal"].max()).days
        if not long_runs.empty else 999
    )

    ctl, atl, tsb = _compute_tsb(running_df)

    # Choix du type de séance
    if tsb < -20:
        session_key = "recuperation"
    elif tsb > 10 and days_since_long >= 6:
        session_key = "sortie_longue"
    elif tsb > 10:
        session_key = "tempo"
    else:
        session_key = "endurance"

    # Si longtemps sans courir → endurance douce
    if days_since >= 5:
        session_key = "endurance"

    s = SESSION_TYPES[session_key]
    target_dist_km = round(avg_dist * s["dist_factor"], 1)
    target_dist_km = max(3.0, target_dist_km)  # minimum 3 km
    target_pace_sec = avg_pace_sec * s["pace_factor"]
    target_elev = round(avg_elev * s["elev_factor"]) if avg_elev and not np.isnan(avg_elev) else 0

    duration_min = round(target_dist_km * target_pace_sec / 60)

    return {
        "session_key": session_key,
        "session": s,
        "ctl": ctl,
        "atl": atl,
        "tsb": tsb,
        "days_since": days_since,
        "target_dist_km": target_dist_km,
        "target_pace_sec": target_pace_sec,
        "target_pace_str": _seconds_to_pace_str(target_pace_sec),
        "target_elev": target_elev,
        "duration_min": duration_min,
        "avg_dist": round(avg_dist, 1),
        "avg_pace_str": _seconds_to_pace_str(avg_pace_sec),
    }


def _get_recent_starts(running_df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Retourne les N dernières sorties avec coordonnées GPS valides."""
    recent = running_df.sort_values("startTimeLocal", ascending=False)
    valid = recent.dropna(subset=["startLat", "startLon"]).head(n)
    return valid[["startTimeLocal", "activityName", "startLat", "startLon", "distance_km"]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Appel ORS
# ---------------------------------------------------------------------------

def fetch_ors_route(lat: float, lon: float, distance_m: int, seed: int, api_key: str) -> dict | None:
    """Appelle l'API OpenRouteService pour générer une boucle inédite."""
    url = f"{ORS_API_BASE}/directions/foot-running/geojson"
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json, application/geo+json",
    }
    body = {
        "coordinates": [[lon, lat]],
        "options": {
            "round_trip": {
                "length": distance_m,
                "points": 3,
                "seed": seed,
            }
        },
        "elevation": True,
        "instructions": False,
    }
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        st.error(f"Erreur ORS ({e.response.status_code}) : {e.response.text[:300]}")
        return None
    except Exception as e:
        st.error(f"Erreur réseau : {e}")
        return None


def _build_gpx(route: dict, session_label: str, target_pace_str: str) -> str:
    """Génère un fichier GPX (course) compatible Garmin Connect."""
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
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


def _parse_ors_route(geojson: dict) -> dict | None:
    """Extrait coordonnées, distance réelle et dénivelé depuis la réponse ORS."""
    try:
        feature = geojson["features"][0]
        coords = feature["geometry"]["coordinates"]  # [lon, lat, ele]
        summary = feature["properties"]["summary"]
        ascent = feature["properties"].get("ascent", 0) or 0

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


# ---------------------------------------------------------------------------
# Rendu carte
# ---------------------------------------------------------------------------

def _render_route_map(route: dict, session_color: str) -> None:
    lats, lons = route["lats"], route["lons"]
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
    else:
        zoom = 10

    fig = go.Figure()

    # Contour blanc pour faire ressortir le tracé sur la carte
    fig.add_trace(go.Scattermapbox(
        lat=lats, lon=lons,
        mode="lines",
        line=dict(width=9, color="white"),
        hoverinfo="none",
        showlegend=False,
    ))

    fig.add_trace(go.Scattermapbox(
        lat=lats, lon=lons,
        mode="lines",
        line=dict(width=5, color=session_color),
        hoverinfo="none",
        name="Parcours",
    ))

    fig.add_trace(go.Scattermapbox(
        lat=[lats[0], lats[-1]],
        lon=[lons[0], lons[-1]],
        mode="markers",
        marker=dict(size=16, color=["#22c55e", "#ef4444"]),
        text=["Départ / Arrivée", "Arrivée"],
        hoverinfo="text",
        name="Points clés",
    ))

    fig.update_layout(
        mapbox=dict(
            style="open-street-map",
            center=dict(lat=center_lat, lon=center_lon),
            zoom=zoom,
        ),
        height=480,
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_elevation_profile(route: dict, session_color: str) -> None:
    eles = route["elevations"]
    if not eles:
        return

    lats, lons = route["lats"], route["lons"]
    # Distances cumulées (approximation)
    dists = [0.0]
    for i in range(1, len(lats)):
        dlat = (lats[i] - lats[i - 1]) * 111_000
        dlon = (lons[i] - lons[i - 1]) * 111_000 * np.cos(np.radians(lats[i]))
        dists.append(dists[-1] + np.sqrt(dlat ** 2 + dlon ** 2) / 1000)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dists, y=eles,
        mode="lines",
        fill="tozeroy",
        fillcolor=f"rgba({int(session_color[1:3],16)},{int(session_color[3:5],16)},{int(session_color[5:7],16)},0.18)",
        line=dict(color=session_color, width=2.5),
        hovertemplate="<b>%{x:.2f} km</b><br>Altitude : %{y:.0f} m<extra></extra>",
    ))
    fig.update_layout(
        height=200,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc"),
        xaxis=dict(title="Distance (km)", gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(title="Altitude (m)", gridcolor="rgba(255,255,255,0.05)"),
        margin=dict(l=0, r=0, t=10, b=0),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# UI principale
# ---------------------------------------------------------------------------

st.title("🗺️ Prochaine sortie")
st.caption("Parcours inédit généré sur OpenStreetMap, adapté à ta forme actuelle.")

# Chargement
df, error = load_activities(200)
if error:
    st.error(f"Erreur Strava : {error}")
    st.stop()
if df.empty:
    st.warning("Aucune activité disponible.")
    st.stop()

running_df = df[df["activityType"] == "running"].copy()
if len(running_df) < 3:
    st.warning("Il faut au moins 3 sorties pour générer une recommandation.")
    st.stop()

# Clé ORS
ors_key = os.getenv("ORS_API_KEY", "")

# Sidebar — paramètres
with st.sidebar:
    st.markdown("## ⚙️ Paramètres")

    if not ors_key:
        ors_key = st.text_input(
            "Clé API OpenRouteService",
            type="password",
            help="Obtiens ta clé gratuite sur openrouteservice.org",
        )

    st.divider()
    st.markdown("### Ajustements")

    dist_offset = st.slider(
        "Ajuster la distance (%)",
        min_value=-30,
        max_value=50,
        value=0,
        step=5,
        help="Modifier la distance cible par rapport à la recommandation",
    )

    prefer_trails = st.toggle(
        "Préférer les chemins / sentiers",
        value=False,
        help="Privilégie les chemins hors-route dans le tracé",
    )

    st.divider()
    st.markdown("### Point de départ")

    recent_starts = _get_recent_starts(running_df)
    if not recent_starts.empty:
        start_options = [
            f"{row['startTimeLocal'].strftime('%d/%m')} · {row['activityName'][:25]} ({row['distance_km']:.1f} km)"
            for _, row in recent_starts.iterrows()
        ]
        selected_start_idx = st.selectbox(
            "Départ depuis",
            options=range(len(start_options)),
            format_func=lambda i: start_options[i],
            index=0,
            help="Choisis le point de départ parmi tes sorties récentes",
        )
        chosen_start = recent_starts.iloc[selected_start_idx]
        sidebar_start_lat = float(chosen_start["startLat"])
        sidebar_start_lon = float(chosen_start["startLon"])
    else:
        sidebar_start_lat = None
        sidebar_start_lon = None

    if st.button("🔄 Actualiser les données", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# Recommandation
rec = _recommend_session(running_df)
s = rec["session"]

# Appliquer l'ajustement de distance
target_dist_km = round(rec["target_dist_km"] * (1 + dist_offset / 100), 1)
target_dist_km = max(2.0, target_dist_km)

# Recalcul durée avec la distance ajustée
duration_min = round(target_dist_km * rec["target_pace_sec"] / 60)

# ── Section 1 : Type de séance ─────────────────────────────────────────────
st.markdown(f"## {s['icon']} {s['label']}")
st.markdown(f"*{s['description']}*")

st.divider()

# ── Section 2 : Métriques de forme ────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
col1.metric("CTL — Forme", f"{rec['ctl']:.1f}", help="Fitness chronique sur 42 jours")
col2.metric("ATL — Fatigue", f"{rec['atl']:.1f}", help="Fatigue aiguë sur 7 jours")

tsb = rec["tsb"]
if tsb > 10:
    tsb_delta, tsb_dc = "Bien reposé", "normal"
elif tsb > -20:
    tsb_delta, tsb_dc = "Charge normale", "off"
else:
    tsb_delta, tsb_dc = "Récupération nécessaire", "inverse"

col3.metric("TSB — Fraîcheur", f"{tsb:.1f}", delta=tsb_delta, delta_color=tsb_dc)
col4.metric("Repos depuis", f"{rec['days_since']} j", help="Jours depuis la dernière sortie")

st.divider()

# ── Section 3 : Objectifs de la séance ────────────────────────────────────
st.markdown("### Objectifs de la séance")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Distance cible", f"{target_dist_km} km",
          help=f"Moyenne récente : {rec['avg_dist']} km")
c2.metric("Allure cible", rec["target_pace_str"],
          help=f"Allure moyenne récente : {rec['avg_pace_str']}")
c3.metric("Durée estimée", f"{duration_min} min")
c4.metric("D+ estimé", f"{rec['target_elev']} m")

# Fourchette d'allure
pace_min = _seconds_to_pace_str(rec["target_pace_sec"] * 0.96)
pace_max = _seconds_to_pace_str(rec["target_pace_sec"] * 1.04)
st.caption(f"Fourchette d'allure conseillée : **{pace_min}** → **{pace_max}**")

st.divider()

# ── Section 4 : Parcours ──────────────────────────────────────────────────
st.markdown("### Parcours proposé")

if not ors_key:
    st.warning(
        "Entre ta clé API OpenRouteService dans la barre latérale pour générer le tracé. "
        "Inscription gratuite sur [openrouteservice.org](https://openrouteservice.org/dev/#/signup).",
        icon="🔑",
    )
    st.stop()

if sidebar_start_lat is None:
    st.warning("Impossible de déterminer un point de départ (coordonnées GPS manquantes).")
    st.stop()

start_lat, start_lon = sidebar_start_lat, sidebar_start_lon

# Seed pour la variation du parcours
if "route_seed" not in st.session_state:
    st.session_state["route_seed"] = 1

col_regen, col_info = st.columns([1, 3])
with col_regen:
    if st.button("🔀 Autre variante", use_container_width=True):
        st.session_state["route_seed"] += 1

with col_info:
    st.caption(f"Départ : {start_lat:.4f}, {start_lon:.4f} · Variante #{st.session_state['route_seed']}")

# Génération du parcours
distance_m = int(target_dist_km * 1000)
profile = "foot-hiking" if prefer_trails else "foot-walking"

with st.spinner("Génération du parcours en cours..."):
    # On appelle directement sans mise en cache pour permettre "autre variante"
    url = f"{ORS_API_BASE}/directions/{profile}/geojson"
    headers = {
        "Authorization": ors_key,
        "Content-Type": "application/json",
        "Accept": "application/json, application/geo+json",
    }
    body = {
        "coordinates": [[start_lon, start_lat]],
        "options": {
            "round_trip": {
                "length": distance_m,
                "points": 3,
                "seed": st.session_state["route_seed"],
            }
        },
        "elevation": True,
        "instructions": False,
    }
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=30)
        resp.raise_for_status()
        geojson = resp.json()
        route = _parse_ors_route(geojson)
    except requests.HTTPError as e:
        st.error(f"Erreur ORS ({e.response.status_code}) : {e.response.text[:400]}")
        route = None
    except Exception as e:
        st.error(f"Erreur réseau : {e}")
        route = None

if route:
    # Métriques du parcours réel
    r1, r2, r3 = st.columns(3)
    r1.metric("Distance réelle", f"{route['distance_km']} km")
    r2.metric("D+ réel", f"{route['ascent_m']} m")
    duration_real = round(route['distance_km'] * rec["target_pace_sec"] / 60)
    r3.metric("Durée estimée", f"{duration_real} min")

    # Carte
    _render_route_map(route, s["color"])

    # Profil altimétrique
    if route["elevations"]:
        st.markdown("#### Profil altimétrique")
        _render_elevation_profile(route, s["color"])

    # Export GPX
    st.divider()
    gpx_content = _build_gpx(route, s["label"], rec["target_pace_str"])
    filename = f"parcours_{rec['session_key']}_{route['distance_km']:.1f}km.gpx"
    st.download_button(
        label="Télécharger le parcours (.gpx)",
        data=gpx_content,
        file_name=filename,
        mime="application/gpx+xml",
        use_container_width=True,
    )
