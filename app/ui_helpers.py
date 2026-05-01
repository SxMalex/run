"""Helpers d'affichage Streamlit partagés entre pages."""

import plotly.graph_objects as go
import polyline as polyline_lib
import streamlit as st

from strava_client import map_zoom


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
