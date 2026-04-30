"""Helpers partagés entre les onglets de 2_Stats.py."""

import numpy as np
import plotly.graph_objects as go

WORKOUT_COLORS = {
    "Normal":        "rgba(124, 156, 252, 0.8)",
    "Race":          "rgba(248, 113, 113, 0.9)",
    "Sortie longue": "rgba(74, 222, 128, 0.8)",
    "Entraînement":  "rgba(251, 146, 60, 0.8)",
}


def add_trend_line(
    fig: go.Figure, x, y, ascending_better: bool = False
) -> tuple[go.Figure, float | None]:
    """
    Ajoute une ligne de tendance (régression linéaire) à un graphique Plotly.
    Retourne (fig, pente) — pente=None si moins de 5 points.
    ascending_better=True → vert si pente > 0 (cadence) ; False → vert si pente < 0 (allure, FC).
    """
    if len(y) < 5:
        return fig, None
    x_num = np.arange(len(y))
    z = np.polyfit(x_num, y, 1)
    slope = z[0]
    color = (
        "rgba(74, 222, 128, 0.8)"
        if (slope > 0) == ascending_better
        else "rgba(248, 113, 113, 0.7)"
    )
    fig.add_trace(go.Scatter(
        x=x,
        y=np.poly1d(z)(x_num),
        mode="lines",
        name="Tendance",
        line=dict(color=color, width=2, dash="dot"),
    ))
    return fig, slope
