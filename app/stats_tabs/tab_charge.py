import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

from next_session_logic import compute_pmc_series


def render(running_df: pd.DataFrame, cutoff: datetime) -> None:
    st.subheader("Charge d'entraînement — CTL / ATL / TSB")
    st.caption(
        "Modèle fitness/fatigue (PMC) · "
        "**CTL** = forme chronique (42 j) · "
        "**ATL** = fatigue aiguë (7 j) · "
        "**TSB** = fraîcheur = CTL − ATL"
    )

    long_runs = running_df[
        (running_df["distance_km"] >= 8) & (running_df["avgPace_sec"] > 0)
    ]
    auto_sec_raw = int(long_runs["avgPace_sec"].quantile(0.15)) if not long_runs.empty else 330
    auto_sec = round((auto_sec_raw - 180) / 5) * 5 + 180
    auto_sec = max(180, min(480, auto_sec))

    if "charge_threshold" not in st.session_state:
        st.session_state["charge_threshold"] = auto_sec

    col_slider, col_info = st.columns([2, 3])
    with col_slider:
        threshold_pace_sec = st.slider(
            "Allure seuil (sec/km)",
            min_value=180, max_value=480, step=5,
            key="charge_threshold",
        )
        st.caption(
            f"**{threshold_pace_sec // 60}:{threshold_pace_sec % 60:02d} /km** · "
            f"1 h à cette allure = 100 TSS  "
            f"(auto : {auto_sec // 60}:{auto_sec % 60:02d} /km)"
        )
    with col_info:
        st.info(
            "L'**allure seuil** (lactate threshold) est votre allure de course "
            "soutenable sur ~1 heure — environ votre allure semi-marathon. "
            "Elle calibre l'Intensity Factor : IF = allure_seuil / allure_moy."
        )

    pmc = compute_pmc_series(running_df, threshold_pace_sec)
    if pmc.empty:
        st.info("Pas de données de course disponibles.")
        return

    pmc_view = pmc[pmc["date"] >= pd.Timestamp(cutoff)].copy()

    last    = pmc.iloc[-1]
    tsb_now = last["tsb"]
    if tsb_now > 25:
        tsb_status, tsb_color = "Sous-entraîné", "off"
    elif tsb_now >= 5:
        tsb_status, tsb_color = "Forme optimale ✓", "normal"
    elif tsb_now >= -20:
        tsb_status, tsb_color = "Charge normale", "off"
    else:
        tsb_status, tsb_color = "Sur-entraîné ⚠️", "inverse"

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("CTL — Forme",    f"{last['ctl']:.1f}", help="Charge chronique sur 42 jours (fitness)")
    m2.metric("ATL — Fatigue",  f"{last['atl']:.1f}", help="Charge aiguë sur 7 jours (fatigue)")
    m3.metric("TSB — Fraîcheur", f"{tsb_now:.1f}", delta=tsb_status, delta_color=tsb_color)
    m4.metric("TSS aujourd'hui", f"{last['tss']:.0f}", help="Training Stress Score du jour")

    st.divider()

    fig = go.Figure()
    tss_bars = pmc_view[pmc_view["tss"] > 0]
    fig.add_trace(go.Bar(
        x=tss_bars["date"], y=tss_bars["tss"], name="TSS",
        marker_color="rgba(124, 156, 252, 0.25)", yaxis="y2",
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>TSS : %{y:.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=pmc_view["date"], y=pmc_view["tsb"].clip(lower=0),
        fill="tozeroy", fillcolor="rgba(74, 222, 128, 0.12)",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=pmc_view["date"], y=pmc_view["tsb"].clip(upper=0),
        fill="tozeroy", fillcolor="rgba(248, 113, 113, 0.12)",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=pmc_view["date"], y=pmc_view["ctl"],
        mode="lines", name="CTL — Forme",
        line=dict(color="#7c9cfc", width=2.5),
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>CTL : %{y:.1f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=pmc_view["date"], y=pmc_view["atl"],
        mode="lines", name="ATL — Fatigue",
        line=dict(color="#fb923c", width=2),
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>ATL : %{y:.1f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=pmc_view["date"], y=pmc_view["tsb"],
        mode="lines", name="TSB — Fraîcheur",
        line=dict(color="#4ade80", width=2, dash="dot"),
        hovertemplate="<b>%{x|%d/%m/%Y}</b><br>TSB : %{y:.1f}<extra></extra>",
    ))
    fig.add_hline(y=0, line_color="rgba(255,255,255,0.15)", line_dash="dot")

    tss_max = pmc_view["tss"].max() if not pmc_view.empty else 100
    fig.update_layout(
        height=420,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc"),
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(
            gridcolor="rgba(255,255,255,0.05)", title="CTL / ATL / TSB",
            zeroline=True, zerolinecolor="rgba(255,255,255,0.15)",
        ),
        yaxis2=dict(
            title="TSS journalier", overlaying="y", side="right",
            showgrid=False, range=[0, max(tss_max * 4, 100)],
            tickfont=dict(color="rgba(124,156,252,0.5)"),
            titlefont=dict(color="rgba(124,156,252,0.5)"),
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=0, r=60, t=40, b=0),
        hovermode="x unified",
    )
    st.plotly_chart(fig)

    st.markdown("#### Interprétation du TSB")
    iz1, iz2, iz3, iz4 = st.columns(4)
    iz1.info("**TSB > 25**\nTrop frais\nSous-entraîné")
    iz2.success("**TSB 5 → 25**\nForme optimale\nIdéal compétition")
    iz3.warning("**TSB −20 → 5**\nCharge normale\nPhase d'entraînement")
    iz4.error("**TSB < −20**\nSur-entraîné\nRécupération requise")
