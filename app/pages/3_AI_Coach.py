"""
Page IA Coach — Génère des prompts prêts à copier dans n'importe quel LLM.
Aucune dépendance Ollama — compatible Streamlit Community Cloud.
"""

import html

import streamlit as st
import pandas as pd

from strava_client import StravaClient, _seconds_to_pace_str, safe_load_activities
from ui_helpers import require_token

st.set_page_config(
    page_title="IA Coach — Running Dashboard",
    page_icon="🤖",
    layout="wide",
)

require_token()

st.markdown("""
<style>
    .summary-block {
        background: #1e1e2e;
        border: 1px solid #3a3a5c;
        border-radius: 8px;
        padding: 12px 16px;
        font-family: monospace;
        font-size: 0.85rem;
        line-height: 1.6;
        white-space: pre-wrap;
        color: #a0aec0;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Prompt système partagé
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """\
Tu es un coach running expert et bienveillant avec plus de 20 ans d'expérience.
Tu analyses les données d'entraînement d'un coureur et fournis des conseils personnalisés,
précis et motivants.

Tes analyses couvrent :
- L'évaluation de la charge d'entraînement (volume, intensité, récupération)
- La progression du pace et de la fréquence cardiaque
- La prévention des blessures (sur-entraînement, sous-récupération)
- Des recommandations concrètes pour la prochaine semaine
- Des encouragements adaptés au niveau du coureur

Tu réponds toujours en français, avec un ton professionnel mais chaleureux.
Tu bases tes analyses uniquement sur les données fournies.
Quand tu n'as pas assez de données pour conclure, tu le précises honnêtement.
Tes réponses sont structurées avec des titres clairs et des listes à puces quand c'est pertinent.\
"""

_ANALYSIS_REQUEST = """\
Analyse ces données et donne-moi :
1. Une évaluation de ma charge d'entraînement actuelle
2. Les points forts observés
3. Les points d'amélioration
4. Des recommandations concrètes pour la prochaine semaine
5. Une note de motivation personnalisée\
"""

_SUGGESTIONS = [
    ("🎯 Objectif semi", "Comment me préparer pour un semi-marathon dans 2 mois ?"),
    ("😴 Récupération", "Est-ce que je me repose suffisamment entre mes sorties ?"),
    ("📈 Allure 10 km", "Comment puis-je améliorer mon allure sur 10 km ?"),
    ("❤️ Fréquence cardiaque", "Mon profil de fréquence cardiaque est-il bon pour mon niveau ?"),
    ("🌿 Endurance", "Comment développer mon endurance fondamentale ?"),
    ("⚡ Vitesse", "Quel type de séance de vitesse me conseilles-tu ?"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _format_activities_summary(df: pd.DataFrame, n: int = 10) -> str:
    if df is None or df.empty:
        return "Aucune activité disponible."
    running = df[df["activityType"] == "running"].copy()
    if running.empty:
        return "Aucune activité de course disponible."

    running = running.sort_values("startTimeLocal", ascending=False).head(n)
    lines = [f"=== {len(running)} dernières sorties course ===\n"]

    for _, row in running.iterrows():
        date_str = pd.to_datetime(row["startTimeLocal"]).strftime("%d/%m/%Y")
        name = row.get("activityName") or "Course"
        dist = row.get("distance_km", 0)
        dur = row.get("duration_min", 0)
        pace = row.get("avgPace", "—")
        hr = row.get("avgHR")
        cadence = row.get("avgCadence")
        elev = row.get("elevationGain")
        calories = row.get("calories")

        hr_str  = f"{int(hr)} bpm"      if hr       and not pd.isna(hr)       else "N/A"
        cad_str = f"{int(cadence)} spm" if cadence  and not pd.isna(cadence)  else "N/A"
        elev_str = f"{int(elev)} m D+"  if elev     and not pd.isna(elev)     else "N/A"
        cal_str  = f"{int(calories)} kcal" if calories and not pd.isna(calories) else "N/A"

        lines.append(
            f"- {date_str} | {name}\n"
            f"  Distance : {dist:.1f} km | Durée : {dur:.0f} min | Allure : {pace}\n"
            f"  FC moy : {hr_str} | Cadence : {cad_str} | D+ : {elev_str} | Calories : {cal_str}"
        )

    total_km = running["distance_km"].sum()
    avg_pace_sec = running.loc[running["avgPace_sec"] > 0, "avgPace_sec"].mean()
    avg_hr = running["avgHR"].dropna().mean()

    lines.append(
        f"\n=== Statistiques sur ces {len(running)} sorties ===\n"
        f"- Volume total : {total_km:.1f} km\n"
        f"- Allure moyenne : {_seconds_to_pace_str(avg_pace_sec)}\n"
        f"- FC moyenne : {int(avg_hr) if avg_hr and not pd.isna(avg_hr) else 'N/A'} bpm"
    )
    return "\n".join(lines)


def _build_prompt(context: str, question: str) -> str:
    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"---\n\n"
        f"{context}\n\n"
        f"---\n\n"
        f"{question}"
    )


# ---------------------------------------------------------------------------
# Clients & cache
# ---------------------------------------------------------------------------
@st.cache_resource
def get_strava_client() -> StravaClient:
    return StravaClient()


@st.cache_data(ttl=3600, show_spinner="Chargement des activités...")
def load_activities(limit: int = 50) -> tuple[pd.DataFrame, str | None]:
    return safe_load_activities(get_strava_client(), limit)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("🤖 Coach IA — Prompts prêts à l'emploi")
st.caption(
    "Copiez le prompt généré et collez-le dans **Claude**, **ChatGPT**, **Gemini** "
    "ou n'importe quel autre LLM. Vos données Strava sont incluses dans le contexte."
)

df, error = load_activities(50)

# Sidebar
with st.sidebar:
    st.markdown("## ⚙️ Paramètres")
    nb_activites = st.slider(
        "Activités à inclure",
        min_value=5, max_value=20, value=10,
        help="Nombre de sorties récentes incluses dans le prompt",
    )
    st.divider()
    if st.button("🔄 Actualiser données", width='stretch'):
        st.cache_data.clear()
        st.rerun()

if error:
    st.error(f"**Erreur Strava :** {error}")
    st.stop()
if df.empty:
    st.warning("Aucune activité disponible.")
    st.stop()

# Métriques rapides
running_only = df[df["activityType"] == "running"]
if not running_only.empty:
    recent = running_only.sort_values("startTimeLocal", ascending=False).head(10)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sorties analysées", min(nb_activites, len(running_only)))
    c2.metric("Volume (10 dernières)", f"{recent['distance_km'].sum():.1f} km")
    pace_vals = recent[recent["avgPace_sec"] > 0]["avgPace_sec"]
    c3.metric("Allure moyenne", _seconds_to_pace_str(pace_vals.mean()) if not pace_vals.empty else "—")
    hr_vals = recent["avgHR"].dropna()
    c4.metric("FC moyenne", f"{hr_vals.mean():.0f} bpm" if not hr_vals.empty else "—")

# Contexte partagé entre les deux sections
context = _format_activities_summary(df, n=nb_activites)

with st.expander("📋 Données incluses dans le prompt", expanded=False):
    # Échappement HTML : les noms d'activités Strava sont contrôlés par
    # l'utilisateur et pourraient contenir des balises (XSS si rendu brut).
    st.markdown(
        f'<div class="summary-block">{html.escape(context)}</div>',
        unsafe_allow_html=True,
    )

st.divider()

# ---------------------------------------------------------------------------
# Onglets via radio (survie au rerun des boutons suggestion)
# ---------------------------------------------------------------------------
_TABS = ["🏃 Analyse complète", "💬 Question personnalisée"]
if "coach_active_tab" not in st.session_state:
    st.session_state["coach_active_tab"] = _TABS[0]

active_tab = st.radio(
    "Onglet",
    _TABS,
    key="coach_active_tab",
    horizontal=True,
    label_visibility="collapsed",
)

# ---------------------------------------------------------------------------
# Onglet 1 — Analyse complète
# ---------------------------------------------------------------------------
if active_tab == _TABS[0]:
    st.subheader("Prompt d'analyse automatique")
    st.info(
        "Ce prompt demande au LLM une analyse complète de votre entraînement récent : "
        "charge, points forts, points d'amélioration et recommandations pour la semaine."
    )
    prompt = _build_prompt(context, _ANALYSIS_REQUEST)
    st.code(prompt, language="markdown")
    st.download_button(
        "⬇️ Télécharger le prompt (.txt)",
        data=prompt,
        file_name="coach_analyse.txt",
        mime="text/plain",
    )

# ---------------------------------------------------------------------------
# Onglet 2 — Question personnalisée
# ---------------------------------------------------------------------------
else:
    st.subheader("Prompt pour une question personnalisée")

    st.markdown("**Suggestions :**")
    sug_cols = st.columns(3)
    for i, (label, question) in enumerate(_SUGGESTIONS):
        if sug_cols[i % 3].button(label, key=f"sug_{i}", width='stretch', help=question):
            st.session_state["coach_question"] = question

    if "coach_question" not in st.session_state:
        st.session_state["coach_question"] = ""

    st.text_area(
        "Votre question",
        key="coach_question",
        placeholder="Ex : Comment améliorer ma cadence ? Suis-je prêt pour un marathon ?",
        height=90,
    )

    question = st.session_state["coach_question"].strip()
    if question:
        prompt = _build_prompt(context, f"Ma question : {question}")
        st.code(prompt, language="markdown")
        st.download_button(
            "⬇️ Télécharger le prompt (.txt)",
            data=prompt,
            file_name="coach_question.txt",
            mime="text/plain",
        )
    else:
        st.caption("Sélectionnez une suggestion ou tapez votre question pour générer le prompt.")
