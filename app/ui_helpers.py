"""Helpers d'affichage Streamlit partagés entre pages."""

import plotly.graph_objects as go
import polyline as polyline_lib
import streamlit as st

from strava_client import StravaClient, map_zoom


def _has_session_token() -> bool:
    return bool(
        st.session_state.get("strava_token")
        and st.session_state.get("strava_athlete_id")
    )


def require_token() -> None:
    """
    Garde à appeler en haut des sous-pages : si l'utilisateur n'a pas
    de token Strava en session, on affiche un message + un lien vers l'accueil
    (où vit le flux OAuth) et on arrête le rendu de la page courante.
    """
    if _has_session_token():
        return
    st.title("🔒 Connexion requise")
    st.warning(
        "Tu dois d'abord connecter ton compte Strava pour accéder à cette page.",
        icon="🔑",
    )
    st.page_link("main.py", label="Aller à la page de connexion", icon="🏠")
    st.stop()


def _persist_token(token: dict) -> None:
    """Callback appelé par StravaClient quand le token est rafraîchi."""
    st.session_state["strava_token"] = token


def get_strava_client() -> StravaClient:
    """
    Construit un `StravaClient` à partir du token de session courant.
    À appeler après `require_token()`.
    """
    return StravaClient(
        token=st.session_state["strava_token"],
        athlete_id=st.session_state["strava_athlete_id"],
        on_token_update=_persist_token,
    )


def render_activity_map(details_data: dict, height: int = 420) -> None:
    """
    Décode le polyline Strava et affiche le tracé GPS sur OpenStreetMap.
    Ne fait rien si l'activité n'a pas de données GPS (tapis, indoor...).
    """
    map_data = details_data.get("details", {}).get("map", {})
    encoded = map_data.get("polyline") or map_data.get("summary_polyline")
    if not encoded:
        return
    coords = polyline_lib.decode(encoded)
    if not coords:
        return

    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    center_lat, center_lon, zoom = map_zoom(lats, lons)

    fig = go.Figure()
    fig.add_trace(go.Scattermap(
        lat=lats, lon=lons,
        mode="lines",
        line=dict(width=4, color="#fc4c02"),
        hoverinfo="none",
    ))
    fig.add_trace(go.Scattermap(
        lat=[lats[0], lats[-1]], lon=[lons[0], lons[-1]],
        mode="markers",
        marker=dict(size=14, color=["#22c55e", "#ef4444"]),
        text=["Départ", "Arrivée"],
        hoverinfo="text",
    ))
    fig.update_layout(
        map=dict(
            style="open-street-map",
            center=dict(lat=center_lat, lon=center_lon),
            zoom=zoom,
        ),
        height=height,
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False,
    )
    st.plotly_chart(fig)
