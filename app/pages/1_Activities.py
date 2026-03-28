"""
Page Activités — Liste filtrée et détails des sorties.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta, date

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strava_client import StravaClient

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Activités — Running Dashboard",
    page_icon="📋",
    layout="wide",
)

st.markdown("""
<style>
    .activity-card {
        background: linear-gradient(135deg, #1e1e2e 0%, #2a2a3e 100%);
        border: 1px solid #3a3a5c;
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 8px;
    }
    .split-table th {
        background: #2a2a3e;
        color: #7c9cfc;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Client Strava (réutilisé depuis le cache Streamlit)
# ---------------------------------------------------------------------------
@st.cache_resource
def get_strava_client() -> StravaClient:
    return StravaClient()


@st.cache_data(ttl=3600, show_spinner="Chargement des activités...")
def load_activities(limit: int = 100) -> tuple[pd.DataFrame, str | None]:
    client = get_strava_client()
    try:
        df = client.get_activities(limit=limit)
        return df, None
    except Exception as e:
        return pd.DataFrame(), str(e)


@st.cache_data(ttl=3600, show_spinner="Chargement des détails...")
def load_activity_details(activity_id: int) -> dict:
    client = get_strava_client()
    return client.get_activity_details(activity_id)


# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------
st.title("📋 Mes Activités")

df, error = load_activities(100)

if error:
    st.error(f"Erreur Strava : {error}")
    st.stop()

if df.empty:
    st.warning("Aucune activité disponible.")
    st.stop()

# ---------------------------------------------------------------------------
# Filtres dans la barre latérale
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## 🔍 Filtres")

    # Filtre par type d'activité
    all_types = sorted(df["activityType"].unique().tolist())
    type_labels = {
        "running": "🏃 Course",
        "cycling": "🚴 Vélo",
        "swimming": "🏊 Natation",
        "walking": "🚶 Marche",
        "hiking": "🥾 Randonnée",
        "strength": "💪 Musculation",
        "yoga": "🧘 Yoga",
        "cardio": "❤️ Cardio",
    }
    type_options = [type_labels.get(t, t.title()) for t in all_types]
    type_mapping = dict(zip(type_options, all_types))

    selected_type_labels = st.multiselect(
        "Type d'activité",
        options=type_options,
        default=["🏃 Course"] if "🏃 Course" in type_options else type_options[:1],
    )
    selected_types = [type_mapping[l] for l in selected_type_labels]

    st.divider()

    # Filtre par date
    min_date = df["startTimeLocal"].min().date() if not df.empty else date.today() - timedelta(days=365)
    max_date = df["startTimeLocal"].max().date() if not df.empty else date.today()

    date_from = st.date_input(
        "Du",
        value=max_date - timedelta(days=90),
        min_value=min_date,
        max_value=max_date,
    )
    date_to = st.date_input(
        "Au",
        value=max_date,
        min_value=min_date,
        max_value=max_date,
    )

    st.divider()

    # Filtre par distance
    if not df.empty and "distance_km" in df.columns:
        max_dist = float(df["distance_km"].max()) if not df.empty else 50.0
        dist_range = st.slider(
            "Distance (km)",
            min_value=0.0,
            max_value=max(max_dist, 1.0),
            value=(0.0, max(max_dist, 1.0)),
            step=0.5,
        )
    else:
        dist_range = (0.0, 999.0)

    # Recherche par nom
    search_name = st.text_input("🔎 Rechercher par nom", placeholder="ex : 10km, Trail...")

# ---------------------------------------------------------------------------
# Application des filtres
# ---------------------------------------------------------------------------
filtered = df.copy()

if selected_types:
    filtered = filtered[filtered["activityType"].isin(selected_types)]

filtered = filtered[
    (filtered["startTimeLocal"].dt.date >= date_from)
    & (filtered["startTimeLocal"].dt.date <= date_to)
]

filtered = filtered[
    (filtered["distance_km"] >= dist_range[0])
    & (filtered["distance_km"] <= dist_range[1])
]

if search_name:
    filtered = filtered[
        filtered["activityName"].str.contains(search_name, case=False, na=False)
    ]

filtered = filtered.sort_values("startTimeLocal", ascending=False)

# ---------------------------------------------------------------------------
# Résumé des filtres
# ---------------------------------------------------------------------------
col1, col2, col3, col4 = st.columns(4)
col1.metric("Activités trouvées", len(filtered))
if not filtered.empty:
    col2.metric("Volume total", f"{filtered['distance_km'].sum():.1f} km")
    col3.metric("Durée totale", f"{filtered['duration_min'].sum() / 60:.1f} h")
    pace_vals = filtered.loc[filtered["avgPace_sec"] > 0, "avgPace_sec"]
    from strava_client import _seconds_to_pace_str
    col4.metric(
        "Allure moyenne",
        _seconds_to_pace_str(pace_vals.mean()) if not pace_vals.empty else "—"
    )

st.divider()

# ---------------------------------------------------------------------------
# Tableau des activités
# ---------------------------------------------------------------------------
if filtered.empty:
    st.info("Aucune activité ne correspond aux filtres sélectionnés.")
    st.stop()

# Préparer l'affichage
display = filtered[[
    "startTimeLocal", "activityName", "activityType",
    "distance_km", "duration_min", "avgPace",
    "avgHR", "avgCadence", "calories", "elevationGain",
]].copy()

display["startTimeLocal"] = pd.to_datetime(display["startTimeLocal"]).dt.strftime("%d/%m/%Y %H:%M")
display["activityType"] = display["activityType"].map(type_labels).fillna(display["activityType"])
display["distance_km"] = display["distance_km"].map("{:.2f}".format)
display["duration_min"] = display["duration_min"].map("{:.0f}".format)

for col in ["avgHR", "avgCadence", "calories", "elevationGain"]:
    display[col] = display[col].apply(
        lambda x: f"{int(x)}" if pd.notna(x) and x != 0 else "—"
    )

display = display.rename(columns={
    "startTimeLocal": "Date",
    "activityName": "Nom",
    "activityType": "Type",
    "distance_km": "Distance (km)",
    "duration_min": "Durée (min)",
    "avgPace": "Allure",
    "avgHR": "FC moy",
    "avgCadence": "Cadence",
    "calories": "Calories",
    "elevationGain": "D+ (m)",
})

# Sélection d'une ligne
selected_event = st.dataframe(
    display,
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "Date": st.column_config.TextColumn("📅 Date"),
        "Nom": st.column_config.TextColumn("🏃 Nom"),
        "Type": st.column_config.TextColumn("🏷️ Type"),
        "Distance (km)": st.column_config.TextColumn("📏 Distance"),
        "Durée (min)": st.column_config.TextColumn("⏱️ Durée"),
        "Allure": st.column_config.TextColumn("🐇 Allure"),
        "FC moy": st.column_config.TextColumn("❤️ FC moy"),
        "Cadence": st.column_config.TextColumn("🦶 Cadence"),
        "Calories": st.column_config.TextColumn("🔥 Calories"),
        "D+ (m)": st.column_config.TextColumn("⛰️ D+"),
    },
)

# ---------------------------------------------------------------------------
# Détails de l'activité sélectionnée
# ---------------------------------------------------------------------------
if selected_event and selected_event.selection and selected_event.selection.rows:
    selected_idx = selected_event.selection.rows[0]
    selected_row = filtered.iloc[selected_idx]
    activity_id = selected_row["activityId"]

    st.divider()
    st.subheader(f"🔍 Détails — {selected_row.get('activityName', 'Activité')}")

    date_fmt = pd.to_datetime(selected_row["startTimeLocal"]).strftime("%A %d %B %Y à %H:%M")
    st.caption(f"📅 {date_fmt}")

    # Métriques principales
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("📏 Distance", f"{selected_row['distance_km']:.2f} km")
    m2.metric("⏱️ Durée", f"{selected_row['duration_min']:.0f} min")
    m3.metric("🐇 Allure", selected_row["avgPace"])
    m4.metric("❤️ FC moy", f"{int(selected_row['avgHR'])} bpm" if pd.notna(selected_row.get("avgHR")) else "—")
    m5.metric("🦶 Cadence", f"{int(selected_row['avgCadence'])} spm" if pd.notna(selected_row.get("avgCadence")) else "—")

    m6, m7, m8, _, _ = st.columns(5)
    m6.metric("🔥 Calories", f"{int(selected_row['calories'])} kcal" if pd.notna(selected_row.get("calories")) else "—")
    m7.metric("⛰️ D+", f"{int(selected_row['elevationGain'])} m" if pd.notna(selected_row.get("elevationGain")) else "—")
    m8.metric("❤️‍🔥 FC max", f"{int(selected_row['maxHR'])} bpm" if pd.notna(selected_row.get("maxHR")) else "—")

    # Chargement des détails et splits
    with st.spinner("Chargement des splits..."):
        details = load_activity_details(activity_id)

    if details and details.get("splits"):
        st.subheader("📊 Splits par kilomètre")
        splits = details["splits"]
        splits_df = pd.DataFrame(splits)

        if not splits_df.empty:
            # Graphique des splits
            fig_splits = go.Figure()

            fig_splits.add_trace(go.Bar(
                x=splits_df["lap"].astype(str),
                y=splits_df["pace_sec"].apply(lambda s: s / 60 if s > 0 else None),
                name="Allure (min/km)",
                marker_color=[
                    "rgba(74, 222, 128, 0.8)" if p > 0 and p < splits_df.loc[splits_df["pace_sec"] > 0, "pace_sec"].mean()
                    else "rgba(124, 156, 252, 0.8)"
                    for p in splits_df["pace_sec"]
                ],
                hovertemplate="<b>Km %{x}</b><br>Allure : %{customdata}<extra></extra>",
                customdata=splits_df["pace"],
            ))

            fig_splits.update_layout(
                height=280,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#ccc"),
                xaxis=dict(
                    title="Kilomètre",
                    gridcolor="rgba(255,255,255,0.05)",
                ),
                yaxis=dict(
                    title="Allure (min/km)",
                    gridcolor="rgba(255,255,255,0.05)",
                    tickformat=".1f",
                ),
                margin=dict(l=0, r=0, t=10, b=0),
                showlegend=False,
            )
            st.plotly_chart(fig_splits, use_container_width=True)

            # Tableau des splits
            splits_display = splits_df[["lap", "distance_km", "duration_min", "pace", "avgHR", "avgCadence", "elevationGain"]].copy()
            splits_display["avgHR"] = splits_display["avgHR"].apply(lambda x: f"{int(x)}" if pd.notna(x) else "—")
            splits_display["avgCadence"] = splits_display["avgCadence"].apply(lambda x: f"{int(x)}" if pd.notna(x) else "—")
            splits_display["elevationGain"] = splits_display["elevationGain"].apply(lambda x: f"{int(x)}" if pd.notna(x) else "—")
            splits_display = splits_display.rename(columns={
                "lap": "Km",
                "distance_km": "Distance",
                "duration_min": "Durée (min)",
                "pace": "Allure",
                "avgHR": "FC moy",
                "avgCadence": "Cadence",
                "elevationGain": "D+",
            })
            st.dataframe(splits_display, use_container_width=True, hide_index=True)
    elif details:
        st.info("Les données de splits ne sont pas disponibles pour cette activité.")
    else:
        st.info("Impossible de charger les détails de cette activité.")
