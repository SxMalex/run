"""
Page Prochaine sortie — Génère un parcours inédit et des objectifs
basés sur les dernières activités et la charge d'entraînement.
"""

import os
import requests
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime, timedelta

from strava_client import StravaClient, _seconds_to_pace_str
from next_session_logic import (
    SESSION_TYPES,
    compute_tsb as _compute_tsb,
    recommend_session as _recommend_session,
    parse_ors_route as _parse_ors_route,
    build_gpx as _build_gpx,
)

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
    fig.add_trace(go.Scattermap(
        lat=lats, lon=lons,
        mode="lines",
        line=dict(width=9, color="white"),
        hoverinfo="none",
        showlegend=False,
    ))

    fig.add_trace(go.Scattermap(
        lat=lats, lon=lons,
        mode="lines",
        line=dict(width=5, color=session_color),
        hoverinfo="none",
        name="Parcours",
    ))

    fig.add_trace(go.Scattermap(
        lat=[lats[0], lats[-1]],
        lon=[lons[0], lons[-1]],
        mode="markers",
        marker=dict(size=16, color=["#22c55e", "#ef4444"]),
        text=["Départ / Arrivée", "Arrivée"],
        hoverinfo="text",
        name="Points clés",
    ))

    fig.update_layout(
        map=dict(
            style="open-street-map",
            center=dict(lat=center_lat, lon=center_lon),
            zoom=zoom,
        ),
        height=480,
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False,
    )
    st.plotly_chart(fig)


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
    st.plotly_chart(fig)


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

# Recommandation calculée avant la sidebar pour alimenter les défauts
rec = _recommend_session(running_df)
s = rec["session"]

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
    st.markdown("### Parcours")

    prefer_trails = st.toggle(
        "Préférer les chemins / sentiers",
        value=False,
        help="Privilégie les chemins hors-route dans le tracé",
    )

    custom_dist = st.number_input(
        "Distance (km)",
        min_value=2.0,
        max_value=100.0,
        value=float(rec["target_dist_km"]),
        step=0.5,
        help=f"Recommandation : {rec['target_dist_km']} km",
    )

    custom_elev = st.number_input(
        "D+ cible (m)",
        min_value=0,
        max_value=3000,
        value=int(rec["target_elev"]),
        step=10,
        help=f"Recommandation : {rec['target_elev']} m",
    )
    st.caption("Le D+ réel dépend du terrain — active 'Sentiers' pour plus de dénivelé.")

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

    if st.button("🔄 Actualiser les données", width='stretch'):
        st.cache_data.clear()
        st.rerun()

# Paramètres finaux (valeurs sidebar ou recommandation par défaut)
target_dist_km = custom_dist
target_elev_m = custom_elev
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
c4.metric("D+ cible", f"{target_elev_m} m")

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
    if st.button("🔀 Autre variante", width='stretch'):
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
        width='stretch',
    )
