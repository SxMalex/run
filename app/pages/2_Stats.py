"""
Page Statistiques — Graphiques d'analyse des performances.
Volume, allure, FC, cadence sur le temps.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import numpy as np
from datetime import datetime, timedelta

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strava_client import StravaClient, _seconds_to_pace_str

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Statistiques — Running Dashboard",
    page_icon="📊",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
@st.cache_resource
def get_strava_client() -> StravaClient:
    return StravaClient()


@st.cache_data(ttl=3600, show_spinner="Chargement des statistiques...")
def load_data(limit: int = 200) -> tuple[pd.DataFrame, str | None]:
    client = get_strava_client()
    try:
        df = client.get_activities(limit=limit)
        return df, None
    except Exception as e:
        return pd.DataFrame(), str(e)


# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------
st.title("📊 Statistiques d'entraînement")

df, error = load_data(200)

if error:
    st.error(f"Erreur Strava : {error}")
    st.stop()

if df.empty:
    st.warning("Aucune donnée disponible.")
    st.stop()

# Filtrer les courses
running_df = df[df["activityType"] == "running"].copy()

if running_df.empty:
    st.warning("Aucune activité de course trouvée.")
    st.stop()

# ---------------------------------------------------------------------------
# Sélecteur de période (sidebar)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## ⚙️ Période d'analyse")
    period = st.selectbox(
        "Afficher les",
        options=["3 derniers mois", "6 derniers mois", "12 derniers mois", "Toutes les données"],
        index=2,
    )
    period_days = {"3 derniers mois": 90, "6 derniers mois": 180, "12 derniers mois": 365, "Toutes les données": 9999}
    cutoff = datetime.now() - timedelta(days=period_days[period])

    if st.button("🔄 Actualiser", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# Appliquer le filtre de période
running_filtered = running_df[running_df["startTimeLocal"] >= cutoff].copy()

if running_filtered.empty:
    st.warning(f"Aucune activité sur la période sélectionnée ({period}).")
    st.stop()

client = get_strava_client()

# ---------------------------------------------------------------------------
# Onglets
# ---------------------------------------------------------------------------
tab_volume, tab_allure, tab_fc, tab_cadence, tab_regularite = st.tabs([
    "📦 Volume", "🐇 Allure", "❤️ Fréquence cardiaque", "🦶 Cadence", "📅 Régularité"
])


# ============================================================
# TAB 1 : Volume
# ============================================================
with tab_volume:
    st.subheader("Volume hebdomadaire et mensuel")

    col_left, col_right = st.columns(2)

    # --- Volume hebdomadaire ---
    with col_left:
        st.markdown("#### Par semaine")
        weekly = client.get_weekly_stats(running_filtered)

        if not weekly.empty:
            weekly["week_label"] = weekly["week"].dt.strftime("S%V %d/%m")

            fig_w = go.Figure()
            fig_w.add_trace(go.Bar(
                x=weekly["week_label"],
                y=weekly["km_total"],
                name="km/semaine",
                marker_color="rgba(124, 156, 252, 0.8)",
                hovertemplate="<b>%{x}</b><br>%{y:.1f} km<br>%{customdata} sorties<extra></extra>",
                customdata=weekly["nb_sorties"],
            ))

            # Moyenne mobile 4 semaines
            if len(weekly) >= 4:
                weekly["rolling_avg"] = weekly["km_total"].rolling(4, min_periods=2).mean()
                fig_w.add_trace(go.Scatter(
                    x=weekly["week_label"],
                    y=weekly["rolling_avg"],
                    mode="lines",
                    name="Moy. mobile (4 sem.)",
                    line=dict(color="rgba(250, 166, 26, 0.9)", width=2),
                ))

            fig_w.update_layout(
                height=350,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#ccc"),
                xaxis=dict(gridcolor="rgba(255,255,255,0.05)", tickangle=-45),
                yaxis=dict(gridcolor="rgba(255,255,255,0.05)", title="km"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                margin=dict(l=0, r=0, t=30, b=60),
                hovermode="x unified",
            )
            st.plotly_chart(fig_w, use_container_width=True)

            # Métriques hebdo
            c1, c2, c3 = st.columns(3)
            c1.metric("Semaine max", f"{weekly['km_total'].max():.1f} km")
            c2.metric("Semaine moy.", f"{weekly['km_total'].mean():.1f} km")
            c3.metric("Semaines actives", str(len(weekly)))
        else:
            st.info("Pas assez de données.")

    # --- Volume mensuel ---
    with col_right:
        st.markdown("#### Par mois")
        monthly = client.get_monthly_stats(running_filtered)

        if not monthly.empty:
            fig_m = go.Figure()
            fig_m.add_trace(go.Bar(
                x=monthly["month_label"],
                y=monthly["km_total"],
                name="km/mois",
                marker_color=[
                    f"rgba({int(100 + 155 * i / max(len(monthly)-1, 1))}, 156, 252, 0.8)"
                    for i in range(len(monthly))
                ],
                hovertemplate="<b>%{x}</b><br>%{y:.1f} km<br>%{customdata} sorties<extra></extra>",
                customdata=monthly["nb_sorties"],
                text=monthly["km_total"].map("{:.0f}".format),
                textposition="outside",
            ))

            fig_m.update_layout(
                height=350,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#ccc"),
                xaxis=dict(gridcolor="rgba(255,255,255,0.05)", tickangle=-30),
                yaxis=dict(gridcolor="rgba(255,255,255,0.05)", title="km"),
                margin=dict(l=0, r=0, t=30, b=60),
                showlegend=False,
                hovermode="x unified",
            )
            st.plotly_chart(fig_m, use_container_width=True)

            # Métriques mensuelles
            c1, c2, c3 = st.columns(3)
            c1.metric("Mois record", f"{monthly['km_total'].max():.1f} km")
            c2.metric("Mois moyen", f"{monthly['km_total'].mean():.1f} km")
            c3.metric("Total période", f"{monthly['km_total'].sum():.0f} km")
        else:
            st.info("Pas assez de données.")

    # --- Distribution des distances ---
    st.markdown("#### Distribution des distances")
    fig_hist = px.histogram(
        running_filtered,
        x="distance_km",
        nbins=20,
        labels={"distance_km": "Distance (km)", "count": "Nombre de sorties"},
        color_discrete_sequence=["rgba(124, 156, 252, 0.8)"],
    )
    fig_hist.update_layout(
        height=280,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc"),
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(gridcolor="rgba(255,255,255,0.05)", title="Sorties"),
        margin=dict(l=0, r=0, t=10, b=0),
        showlegend=False,
    )
    st.plotly_chart(fig_hist, use_container_width=True)


# ============================================================
# TAB 2 : Allure
# ============================================================
with tab_allure:
    st.subheader("Évolution de l'allure dans le temps")

    pace_data = running_filtered[running_filtered["avgPace_sec"] > 0].copy()
    pace_data = pace_data.sort_values("startTimeLocal")

    if pace_data.empty:
        st.info("Pas de données d'allure disponibles.")
    else:
        # Convertir pace en min/km (flottant pour le graphique)
        pace_data["pace_min"] = pace_data["avgPace_sec"] / 60

        fig_pace = go.Figure()

        # Points individuels
        fig_pace.add_trace(go.Scatter(
            x=pace_data["startTimeLocal"],
            y=pace_data["pace_min"],
            mode="markers",
            name="Allure",
            marker=dict(
                color=pace_data["distance_km"],
                colorscale="Viridis",
                size=8,
                colorbar=dict(title="Distance (km)", tickfont=dict(color="#ccc")),
                showscale=True,
            ),
            hovertemplate=(
                "<b>%{x|%d/%m/%Y}</b><br>"
                "Allure : %{customdata[0]}<br>"
                "Distance : %{customdata[1]:.1f} km<extra></extra>"
            ),
            customdata=list(zip(pace_data["avgPace"], pace_data["distance_km"])),
        ))

        # Tendance linéaire
        if len(pace_data) >= 5:
            x_num = np.arange(len(pace_data))
            z = np.polyfit(x_num, pace_data["pace_min"], 1)
            p = np.poly1d(z)
            trend = p(x_num)
            color_trend = "rgba(74, 222, 128, 0.8)" if z[0] < 0 else "rgba(248, 113, 113, 0.8)"
            fig_pace.add_trace(go.Scatter(
                x=pace_data["startTimeLocal"],
                y=trend,
                mode="lines",
                name="Tendance",
                line=dict(color=color_trend, width=2, dash="dot"),
            ))

        # Axe Y inversé (allure plus basse = plus rapide)
        y_min = pace_data["pace_min"].min()
        y_max = pace_data["pace_min"].max()
        padding = (y_max - y_min) * 0.1 if y_max > y_min else 0.5

        fig_pace.update_layout(
            height=400,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#ccc"),
            xaxis=dict(gridcolor="rgba(255,255,255,0.05)", title="Date"),
            yaxis=dict(
                gridcolor="rgba(255,255,255,0.05)",
                title="Allure (min/km)",
                range=[y_max + padding, y_min - padding],  # Inversé
                tickformat=".1f",
            ),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=0, r=0, t=30, b=0),
            hovermode="closest",
        )
        st.plotly_chart(fig_pace, use_container_width=True)

        st.caption("⬇️ L'axe Y est inversé : une allure plus basse indique une vitesse plus élevée.")

        # Stats allure
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Meilleure allure", _seconds_to_pace_str(pace_data["avgPace_sec"].min()))
        c2.metric("Allure moyenne", _seconds_to_pace_str(pace_data["avgPace_sec"].mean()))
        c3.metric("Allure médiane", _seconds_to_pace_str(float(pace_data["avgPace_sec"].median())))
        trend_txt = "Amélioration 📈" if z[0] < 0 else "Ralentissement 📉"
        c4.metric("Tendance", trend_txt if len(pace_data) >= 5 else "N/A")

        # Allure par distance
        st.markdown("#### Allure moyenne par tranche de distance")
        bins = [0, 5, 10, 15, 21.1, 30, 42.2, 999]
        labels_dist = ["< 5 km", "5-10 km", "10-15 km", "15-21 km", "Semi-marathon", "30-42 km", "Marathon+"]
        pace_data["distance_bin"] = pd.cut(
            pace_data["distance_km"], bins=bins, labels=labels_dist, right=False
        )
        pace_by_dist = (
            pace_data.groupby("distance_bin", observed=True)["avgPace_sec"]
            .mean()
            .reset_index()
        )
        pace_by_dist["allure"] = pace_by_dist["avgPace_sec"].apply(_seconds_to_pace_str)
        pace_by_dist["pace_min"] = pace_by_dist["avgPace_sec"] / 60

        fig_pace_dist = go.Figure(go.Bar(
            x=pace_by_dist["distance_bin"].astype(str),
            y=pace_by_dist["pace_min"],
            text=pace_by_dist["allure"],
            textposition="outside",
            marker_color="rgba(124, 156, 252, 0.8)",
        ))
        fig_pace_dist.update_layout(
            height=300,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#ccc"),
            xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
            yaxis=dict(
                gridcolor="rgba(255,255,255,0.05)",
                title="Allure (min/km)",
                tickformat=".1f",
                range=[
                    pace_by_dist["pace_min"].max() * 1.1 if not pace_by_dist.empty else 8,
                    pace_by_dist["pace_min"].min() * 0.9 if not pace_by_dist.empty else 4,
                ],
            ),
            margin=dict(l=0, r=0, t=30, b=0),
            showlegend=False,
        )
        st.plotly_chart(fig_pace_dist, use_container_width=True)


# ============================================================
# TAB 3 : Fréquence cardiaque
# ============================================================
with tab_fc:
    st.subheader("Analyse de la fréquence cardiaque")

    hr_data = running_filtered.dropna(subset=["avgHR"]).copy()
    hr_data = hr_data.sort_values("startTimeLocal")

    if hr_data.empty:
        st.info("Pas de données de fréquence cardiaque disponibles.")
    else:
        col_left, col_right = st.columns([3, 2])

        with col_left:
            st.markdown("#### Évolution FC dans le temps")
            fig_hr = go.Figure()

            fig_hr.add_trace(go.Scatter(
                x=hr_data["startTimeLocal"],
                y=hr_data["avgHR"],
                mode="markers+lines",
                name="FC moyenne",
                line=dict(color="rgba(248, 113, 113, 0.5)", width=1),
                marker=dict(color="rgba(248, 113, 113, 0.9)", size=6),
                hovertemplate="<b>%{x|%d/%m/%Y}</b><br>FC : %{y:.0f} bpm<extra></extra>",
            ))

            if hr_data["maxHR"].notna().any():
                max_hr_data = hr_data.dropna(subset=["maxHR"])
                fig_hr.add_trace(go.Scatter(
                    x=max_hr_data["startTimeLocal"],
                    y=max_hr_data["maxHR"],
                    mode="markers",
                    name="FC max",
                    marker=dict(color="rgba(251, 146, 60, 0.7)", size=5, symbol="triangle-up"),
                    hovertemplate="<b>%{x|%d/%m/%Y}</b><br>FC max : %{y:.0f} bpm<extra></extra>",
                ))

            # Tendance FC
            if len(hr_data) >= 5:
                x_num = np.arange(len(hr_data))
                z_hr = np.polyfit(x_num, hr_data["avgHR"], 1)
                p_hr = np.poly1d(z_hr)
                color_hr = "rgba(74, 222, 128, 0.8)" if z_hr[0] < 0 else "rgba(248, 113, 113, 0.6)"
                fig_hr.add_trace(go.Scatter(
                    x=hr_data["startTimeLocal"],
                    y=p_hr(x_num),
                    mode="lines",
                    name="Tendance",
                    line=dict(color=color_hr, width=2, dash="dot"),
                ))

            fig_hr.update_layout(
                height=350,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#ccc"),
                xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
                yaxis=dict(gridcolor="rgba(255,255,255,0.05)", title="bpm"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                margin=dict(l=0, r=0, t=30, b=0),
            )
            st.plotly_chart(fig_hr, use_container_width=True)

        with col_right:
            st.markdown("#### Distribution des zones FC")
            max_hr_setting = st.number_input(
                "FC max (bpm)", min_value=150, max_value=220, value=190, step=1
            )
            hr_zones = client.get_hr_zones(running_filtered, max_hr=max_hr_setting)

            if not hr_zones.empty and hr_zones["nb_activites"].sum() > 0:
                fig_zones = go.Figure(go.Pie(
                    labels=hr_zones["zone"],
                    values=hr_zones["nb_activites"],
                    hole=0.4,
                    marker=dict(
                        colors=[
                            "#60a5fa",  # Z1 bleu
                            "#4ade80",  # Z2 vert
                            "#facc15",  # Z3 jaune
                            "#fb923c",  # Z4 orange
                            "#f87171",  # Z5 rouge
                        ]
                    ),
                    textinfo="label+percent",
                    textfont=dict(size=11),
                ))
                fig_zones.update_layout(
                    height=350,
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#ccc"),
                    legend=dict(orientation="v", font=dict(size=10)),
                    margin=dict(l=0, r=0, t=10, b=0),
                    showlegend=True,
                )
                st.plotly_chart(fig_zones, use_container_width=True)
                st.caption("Distribution estimée d'après la FC moyenne par activité.")
            else:
                st.info("Pas assez de données FC pour les zones.")

        # Stats FC
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("FC moy globale", f"{hr_data['avgHR'].mean():.0f} bpm")
        c2.metric("FC moy minimale", f"{hr_data['avgHR'].min():.0f} bpm")
        c3.metric("FC moy maximale", f"{hr_data['avgHR'].max():.0f} bpm")
        hr_trend_txt = "Baisse 📈" if len(hr_data) >= 5 and z_hr[0] < 0 else ("Hausse 📉" if len(hr_data) >= 5 else "N/A")
        c4.metric("Tendance FC", hr_trend_txt)

        # FC vs Allure (corrélation)
        st.markdown("#### Corrélation FC / Allure")
        corr_data = running_filtered.dropna(subset=["avgHR"]).copy()
        corr_data = corr_data[corr_data["avgPace_sec"] > 0]

        if len(corr_data) >= 5:
            fig_corr = px.scatter(
                corr_data,
                x="avgPace_sec",
                y="avgHR",
                color="distance_km",
                color_continuous_scale="Viridis",
                labels={
                    "avgPace_sec": "Allure (sec/km)",
                    "avgHR": "FC moyenne (bpm)",
                    "distance_km": "Distance (km)",
                },
                hover_data={"avgPace": True, "startTimeLocal": "|%d/%m/%Y"},
            )
            fig_corr.update_traces(marker=dict(size=8))
            fig_corr.update_layout(
                height=300,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#ccc"),
                xaxis=dict(
                    gridcolor="rgba(255,255,255,0.05)",
                    title="Allure (sec/km) — valeur élevée = lent",
                ),
                yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
                coloraxis_colorbar=dict(tickfont=dict(color="#ccc")),
                margin=dict(l=0, r=0, t=10, b=0),
            )
            st.plotly_chart(fig_corr, use_container_width=True)
            corr_val = corr_data["avgPace_sec"].corr(corr_data["avgHR"])
            st.caption(f"Corrélation allure/FC : {corr_val:.2f} (proche de 1 = FC monte avec le pace)")


# ============================================================
# TAB 4 : Cadence
# ============================================================
with tab_cadence:
    st.subheader("Évolution de la cadence de course")

    cad_data = running_filtered.dropna(subset=["avgCadence"]).copy()
    cad_data = cad_data[cad_data["avgCadence"] > 0].sort_values("startTimeLocal")

    if cad_data.empty:
        st.info("Pas de données de cadence disponibles.")
    else:
        # Zone optimale : 170-180 spm
        CADENCE_LOW = 170
        CADENCE_HIGH = 180

        fig_cad = go.Figure()

        # Zone optimale
        fig_cad.add_hrect(
            y0=CADENCE_LOW, y1=CADENCE_HIGH,
            fillcolor="rgba(74, 222, 128, 0.1)",
            line_width=0,
            annotation_text="Zone optimale",
            annotation_position="top right",
            annotation_font=dict(color="rgba(74, 222, 128, 0.8)", size=11),
        )

        # Données
        fig_cad.add_trace(go.Scatter(
            x=cad_data["startTimeLocal"],
            y=cad_data["avgCadence"],
            mode="markers+lines",
            name="Cadence",
            line=dict(color="rgba(167, 139, 250, 0.5)", width=1),
            marker=dict(
                color=cad_data["avgCadence"].apply(
                    lambda c: "rgba(74, 222, 128, 0.9)" if CADENCE_LOW <= c <= CADENCE_HIGH
                    else ("rgba(251, 146, 60, 0.9)" if c < CADENCE_LOW else "rgba(248, 113, 113, 0.9)")
                ),
                size=7,
            ),
            hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Cadence : %{y:.0f} spm<extra></extra>",
        ))

        # Tendance
        if len(cad_data) >= 5:
            x_num = np.arange(len(cad_data))
            z_cad = np.polyfit(x_num, cad_data["avgCadence"], 1)
            p_cad = np.poly1d(z_cad)
            color_cad = "rgba(74, 222, 128, 0.8)" if z_cad[0] > 0 else "rgba(251, 146, 60, 0.8)"
            fig_cad.add_trace(go.Scatter(
                x=cad_data["startTimeLocal"],
                y=p_cad(x_num),
                mode="lines",
                name="Tendance",
                line=dict(color=color_cad, width=2, dash="dot"),
            ))

        fig_cad.update_layout(
            height=380,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#ccc"),
            xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
            yaxis=dict(gridcolor="rgba(255,255,255,0.05)", title="Cadence (spm)"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=0, r=0, t=30, b=0),
        )
        st.plotly_chart(fig_cad, use_container_width=True)

        # Stats cadence
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Cadence moyenne", f"{cad_data['avgCadence'].mean():.0f} spm")
        c2.metric("Cadence max", f"{cad_data['avgCadence'].max():.0f} spm")

        pct_optimal = (
            ((cad_data["avgCadence"] >= CADENCE_LOW) & (cad_data["avgCadence"] <= CADENCE_HIGH)).sum()
            / len(cad_data) * 100
        )
        c3.metric("Dans la zone optimale", f"{pct_optimal:.0f}%")

        cad_trend_txt = "Amélioration 📈" if len(cad_data) >= 5 and z_cad[0] > 0 else ("Baisse 📉" if len(cad_data) >= 5 else "N/A")
        c4.metric("Tendance", cad_trend_txt)

        st.info(
            "💡 Une cadence optimale se situe entre **170 et 180 spm** pour la plupart des coureurs. "
            "Une cadence élevée réduit l'impact au sol et diminue le risque de blessure."
        )

        # Histogramme de distribution cadence
        st.markdown("#### Distribution de la cadence")
        fig_cad_hist = go.Figure(go.Histogram(
            x=cad_data["avgCadence"],
            nbinsx=20,
            marker_color="rgba(167, 139, 250, 0.8)",
            hovertemplate="Cadence : %{x:.0f} spm<br>Sorties : %{y}<extra></extra>",
        ))
        fig_cad_hist.add_vline(
            x=CADENCE_LOW, line_color="rgba(74, 222, 128, 0.7)",
            line_dash="dash", annotation_text="170 spm",
            annotation_font=dict(color="rgba(74, 222, 128, 0.9)"),
        )
        fig_cad_hist.add_vline(
            x=CADENCE_HIGH, line_color="rgba(74, 222, 128, 0.7)",
            line_dash="dash", annotation_text="180 spm",
            annotation_font=dict(color="rgba(74, 222, 128, 0.9)"),
        )
        fig_cad_hist.update_layout(
            height=280,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#ccc"),
            xaxis=dict(gridcolor="rgba(255,255,255,0.05)", title="Cadence (spm)"),
            yaxis=dict(gridcolor="rgba(255,255,255,0.05)", title="Nombre de sorties"),
            margin=dict(l=0, r=0, t=10, b=0),
            showlegend=False,
        )
        st.plotly_chart(fig_cad_hist, use_container_width=True)


# ============================================================
# TAB 5 : Régularité — Calendar heatmap
# ============================================================
with tab_regularite:
    st.subheader("Calendrier de régularité")

    from datetime import date, timedelta as td

    # Sélecteur d'année — indépendant du filtre de période de la sidebar
    available_years = sorted(running_df["startTimeLocal"].dt.year.unique(), reverse=True)
    selected_year = st.selectbox("Année", available_years, index=0, key="heatmap_year")

    # Agréger par jour sur l'année complète
    year_df = running_df[running_df["startTimeLocal"].dt.year == selected_year].copy()
    year_df["date"] = pd.to_datetime(year_df["startTimeLocal"].dt.date)
    daily = year_df.groupby("date").agg(
        distance_km=("distance_km", "sum"),
        nb_sorties=("activityId", "count"),
    ).reset_index()

    # Grille Jan 1 → Dec 31
    jan1 = pd.Timestamp(f"{selected_year}-01-01")
    dec31 = pd.Timestamp(f"{selected_year}-12-31")
    full_year = pd.DataFrame({"date": pd.date_range(jan1, dec31, freq="D")})
    full_year = full_year.merge(daily, on="date", how="left")
    full_year["distance_km"] = full_year["distance_km"].fillna(0.0)
    full_year["nb_sorties"] = full_year["nb_sorties"].fillna(0).astype(int)
    full_year["dow"] = full_year["date"].dt.dayofweek  # 0 = Lun, 6 = Dim

    # Colonne = semaine depuis le lundi précédant le 1er janvier
    grid_start = jan1 - pd.Timedelta(days=jan1.dayofweek)
    full_year["col"] = ((full_year["date"] - grid_start) / pd.Timedelta(days=1)).astype(int) // 7

    n_weeks = int(full_year["col"].max()) + 1

    # Matrices z (valeurs) et text (hover)
    z = np.full((7, n_weeks), np.nan)
    hover_text = np.full((7, n_weeks), "", dtype=object)

    for _, row in full_year.iterrows():
        dow = int(row["dow"])
        col = int(row["col"])
        km = float(row["distance_km"])
        z[dow, col] = km
        date_str = row["date"].strftime("%A %d %B")
        if km > 0:
            detail = f" ({int(row['nb_sorties'])} sorties)" if row["nb_sorties"] > 1 else ""
            hover_text[dow, col] = f"{date_str}<br>🏃 {km:.1f} km{detail}"
        else:
            hover_text[dow, col] = f"{date_str}<br>Repos"

    # Labels des mois sur l'axe X (en haut)
    x_tickvals, x_ticktext = [], []
    for month in range(1, 13):
        m_start = pd.Timestamp(f"{selected_year}-{month:02d}-01")
        col_idx = int((m_start - grid_start) / pd.Timedelta(days=1)) // 7
        if 0 <= col_idx < n_weeks:
            x_tickvals.append(col_idx)
            x_ticktext.append(m_start.strftime("%b"))

    # Palette : fond sombre (repos) → orange Strava (volume élevé)
    colorscale = [
        [0.00, "#1e2030"],
        [0.05, "#6b2317"],
        [0.25, "#9a3412"],
        [0.50, "#c2410c"],
        [0.75, "#ea580c"],
        [1.00, "#fc4c02"],
    ]
    max_km = float(full_year["distance_km"].max()) or 1.0

    fig_cal = go.Figure(go.Heatmap(
        z=z,
        x=list(range(n_weeks)),
        y=["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"],
        text=hover_text,
        hovertemplate="%{text}<extra></extra>",
        colorscale=colorscale,
        zmin=0,
        zmax=max_km,
        xgap=3,
        ygap=3,
        showscale=True,
        colorbar=dict(
            title="km",
            thickness=12,
            len=0.85,
            tickfont=dict(color="#ccc", size=10),
            titlefont=dict(color="#ccc"),
        ),
    ))

    fig_cal.update_layout(
        height=210,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc"),
        xaxis=dict(
            tickmode="array",
            tickvals=x_tickvals,
            ticktext=x_ticktext,
            tickfont=dict(size=11),
            showgrid=False,
            side="top",
        ),
        yaxis=dict(
            autorange="reversed",
            tickfont=dict(size=10),
            showgrid=False,
        ),
        margin=dict(l=40, r=80, t=30, b=10),
    )

    st.plotly_chart(fig_cal, use_container_width=True)

    # --- Statistiques de régularité ---
    dates_with_run: set[date] = set(
        full_year[full_year["distance_km"] > 0]["date"].dt.date
    )
    today = date.today()

    # Streak actuel (on accepte hier si aujourd'hui pas encore couru)
    def _streak_back(d: date, date_set: set) -> int:
        count = 0
        while d in date_set:
            count += 1
            d -= td(days=1)
        return count

    current_streak = _streak_back(today, dates_with_run)
    if current_streak == 0:
        current_streak = _streak_back(today - td(days=1), dates_with_run)

    # Streak maximum sur l'année
    streak_max = 0
    temp_streak = 0
    for _, row in full_year.sort_values("date").iterrows():
        if row["distance_km"] > 0:
            temp_streak += 1
            streak_max = max(streak_max, temp_streak)
        else:
            temp_streak = 0

    n_jours = len(dates_with_run & {
        (jan1 + pd.Timedelta(days=i)).date() for i in range((dec31 - jan1).days + 1)
    })
    total_km_year = full_year["distance_km"].sum()

    # Mois le plus actif
    full_year["month"] = full_year["date"].dt.month
    monthly_runs = (
        full_year[full_year["distance_km"] > 0]
        .groupby("month")
        .size()
    )
    best_month_num = int(monthly_runs.idxmax()) if not monthly_runs.empty else None
    best_month_name = pd.Timestamp(f"{selected_year}-{best_month_num:02d}-01").strftime("%B") if best_month_num else "—"

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Jours courus", str(n_jours))
    c2.metric("Volume total", f"{total_km_year:.0f} km")
    c3.metric("Streak max", f"{streak_max} j")
    c4.metric("Streak actuel", f"{current_streak} j")
    c5.metric("Mois le + actif", best_month_name)
