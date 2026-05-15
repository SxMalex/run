"""Helpers d'affichage Streamlit partagés entre pages."""

from typing import Sequence

import pandas as pd
import plotly.graph_objects as go
import polyline as polyline_lib
import streamlit as st

from formatting import map_zoom
from strava_client import StravaClient, safe_load_activities


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


def render_strava_attribution() -> None:
    """
    Attribution « Powered by Strava » — à appeler en bas de toute page
    affichant des données Strava (exigence des Brand Guidelines).
    Cf. https://developers.strava.com/guidelines/
    """
    st.markdown(
        """
        <div style="text-align: center; margin: 24px 0 8px 0;">
            <a href="https://www.strava.com" target="_blank"
               style="text-decoration: none; color: inherit;">
                <span style="color: #888; font-size: 0.8rem;">Powered by </span><span
                      style="color: #FC4C02; font-weight: 700; font-size: 0.85rem;
                             letter-spacing: 0.04em;">STRAVA</span>
            </a>
        </div>
        """,
        unsafe_allow_html=True,
    )


def cache_nonce() -> int:
    """
    Compteur d'invalidation per-session. À passer en argument à toute fonction
    `@st.cache_data` qui doit pouvoir être invalidée explicitement par
    `render_refresh_button` sans flusher le cache global (qui affecterait les
    autres utilisateurs connectés).
    """
    return st.session_state.get("_cache_nonce", 0)


@st.cache_data(ttl=3600, show_spinner="Chargement des activités...")
def _cached_load_activities_impl(
    athlete_id: int, limit: int, nonce: int
) -> tuple[pd.DataFrame, str | None]:
    """Le `nonce` est dans la signature pour servir de clé de cache per-session."""
    del nonce  # uniquement pour la cache key
    return safe_load_activities(get_strava_client(), limit)


def cached_load_activities(
    athlete_id: int, limit: int = 100
) -> tuple[pd.DataFrame, str | None]:
    """Wrapper unique pour `load_activities` : factorise le pattern dupliqué dans 7 pages."""
    return _cached_load_activities_impl(athlete_id, limit, cache_nonce())


def render_refresh_button(label: str = "🔄 Actualiser les données", *, stretch: bool = True) -> None:
    """
    Bouton de rafraîchissement standard. Invalide le cache disque per-athlete
    + bump du nonce per-session pour invalider les caches Streamlit `@st.cache_data`
    qui prennent `nonce` en argument. **N'utilise pas** `st.cache_data.clear()`
    qui flusherait le cache RAM partagé entre tous les utilisateurs (DoS).
    """
    if st.button(label, width="stretch" if stretch else "content"):
        get_strava_client().invalidate_cache()
        st.session_state["_cache_nonce"] = cache_nonce() + 1
        st.rerun()


def hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convertit un hex `#rrggbb` en chaîne CSS `rgba(r,g,b,a)`."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def render_elevation_profile(
    distances_km: Sequence[float],
    elevations: Sequence[float],
    *,
    color: str = "#fc4c02",
    fill_alpha: float = 0.15,
    height: int = 210,
) -> None:
    """
    Profil altimétrique générique : reçoit deux séries alignées et trace
    un Plotly Scatter avec fill. Utilisé par main.py (depuis streams Strava)
    et 4_Next_Session.py (depuis route ORS).
    """
    if not elevations or not distances_km:
        st.caption("Profil altimétrique non disponible.")
        return
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(distances_km), y=list(elevations),
        mode="lines",
        fill="tozeroy",
        fillcolor=hex_to_rgba(color, fill_alpha),
        line=dict(color=color, width=2),
        hovertemplate="<b>%{x:.2f} km</b><br>Altitude : %{y:.0f} m<extra></extra>",
    ))
    fig.update_layout(
        height=height,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc"),
        xaxis=dict(title="Distance (km)", gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(title="Altitude (m)", gridcolor="rgba(255,255,255,0.05)"),
        margin=dict(l=0, r=0, t=10, b=0), showlegend=False,
    )
    st.plotly_chart(fig)


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
