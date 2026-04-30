"""
Page Statistiques — Graphiques d'analyse des performances.
Volume, allure, FC, cadence sur le temps.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from strava_client import StravaClient, workout_type_label
from stats_tabs import tab_volume, tab_allure, tab_fc, tab_cadence, tab_regularite, tab_charge


def _add_trend_line(fig, x, y, ascending_better=False):
    from stats_tabs._shared import add_trend_line
    return add_trend_line(fig, x, y, ascending_better)


st.set_page_config(
    page_title="Statistiques — Running Dashboard",
    page_icon="📊",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Clients & données
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


@st.cache_data(ttl=86400, show_spinner=False)
def load_athlete_zones() -> dict:
    return get_strava_client().get_athlete_zones()


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

running_df = df[df["activityType"] == "running"].copy()
if "workoutType" not in running_df.columns:
    running_df["workoutType"] = 0
running_df["workoutLabel"] = running_df["workoutType"].apply(workout_type_label)

if running_df.empty:
    st.warning("Aucune activité de course trouvée.")
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar — période et FC max
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## ⚙️ Période d'analyse")
    period = st.selectbox(
        "Afficher les",
        options=["3 derniers mois", "6 derniers mois", "12 derniers mois", "Toutes les données"],
        index=2,
    )
    period_days = {
        "3 derniers mois": 90, "6 derniers mois": 180,
        "12 derniers mois": 365, "Toutes les données": 9999,
    }
    cutoff = datetime.now() - timedelta(days=period_days[period])

    if st.button("🔄 Actualiser", width='stretch'):
        get_strava_client().invalidate_cache()
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()

    st.markdown("---")
    st.markdown("#### ❤️ FC max")
    zones_data = load_athlete_zones()
    hr_zones_list = (zones_data.get("heart_rate") or {}).get("zones") or []
    max_hr_from_zones = None
    if len(hr_zones_list) >= 2:
        z_last_min = (hr_zones_list[-1] or {}).get("min", 0)
        if z_last_min and z_last_min > 100:
            max_hr_from_zones = round(z_last_min / 0.90)
    recorded_max   = running_df["maxHR"].dropna()
    max_hr_from_data = int(recorded_max.max()) if not recorded_max.empty else 0
    max_hr_setting = max(max_hr_from_zones or 0, max_hr_from_data, 150)
    max_hr_setting = min(max_hr_setting, 220)
    source = "zones Strava" if max_hr_from_zones and max_hr_from_zones >= max_hr_from_data else "pic enregistré"
    st.caption(f"**{max_hr_setting} bpm** — estimée d'après le {source}")

running_filtered = running_df[running_df["startTimeLocal"] >= cutoff].copy()
if running_filtered.empty:
    st.warning(f"Aucune activité sur la période sélectionnée ({period}).")
    st.stop()

client = get_strava_client()

# ---------------------------------------------------------------------------
# Onglets
# ---------------------------------------------------------------------------
_TAB_LABELS = ["📦 Volume", "🐇 Allure", "❤️ Fréquence cardiaque", "🦶 Cadence", "📅 Régularité", "⚡ Charge"]
if "stats_active_tab" not in st.session_state:
    st.session_state["stats_active_tab"] = _TAB_LABELS[0]

active_tab = st.radio(
    "Onglet", _TAB_LABELS,
    key="stats_active_tab",
    horizontal=True,
    label_visibility="collapsed",
)

if active_tab == "📦 Volume":
    tab_volume.render(running_filtered, client)
elif active_tab == "🐇 Allure":
    tab_allure.render(running_filtered)
elif active_tab == "❤️ Fréquence cardiaque":
    tab_fc.render(running_filtered, client, max_hr_setting)
elif active_tab == "🦶 Cadence":
    tab_cadence.render(running_filtered)
elif active_tab == "📅 Régularité":
    tab_regularite.render(running_df)
elif active_tab == "⚡ Charge":
    tab_charge.render(running_df, cutoff)
