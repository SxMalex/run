"""
Page IA Coach — Analyse personnalisée de l'entraînement via Ollama.
Affiche un résumé des activités et génère des conseils en streaming.
"""

import os
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from strava_client import StravaClient, _seconds_to_pace_str
from llm_client import OllamaClient

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="IA Coach — Running Dashboard",
    page_icon="🤖",
    layout="wide",
)

st.markdown("""
<style>
    .coach-message {
        background: linear-gradient(135deg, #1a2a1a 0%, #1e2a2e 100%);
        border: 1px solid #2a4a3a;
        border-left: 4px solid #4ade80;
        border-radius: 8px;
        padding: 16px 20px;
        margin: 8px 0;
    }
    .user-question {
        background: linear-gradient(135deg, #1a1a2e 0%, #2a2a3e 100%);
        border: 1px solid #3a3a5c;
        border-left: 4px solid #7c9cfc;
        border-radius: 8px;
        padding: 12px 16px;
        margin: 8px 0;
        font-style: italic;
    }
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
# Clients
# ---------------------------------------------------------------------------
@st.cache_resource
def get_strava_client() -> StravaClient:
    return StravaClient()


@st.cache_resource
def get_ollama_client() -> OllamaClient:
    return OllamaClient()


@st.cache_data(ttl=3600, show_spinner="Chargement des activités...")
def load_activities(limit: int = 50) -> tuple[pd.DataFrame, str | None]:
    client = get_strava_client()
    try:
        df = client.get_activities(limit=limit)
        return df, None
    except Exception as e:
        return pd.DataFrame(), str(e)


# ---------------------------------------------------------------------------
# Session state pour l'historique du chat
# ---------------------------------------------------------------------------
MAX_CHAT_HISTORY = 20

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "activities_summary" not in st.session_state:
    st.session_state.activities_summary = None
if "_summary_n" not in st.session_state:
    st.session_state["_summary_n"] = None


# ---------------------------------------------------------------------------
# Chargement des données
# ---------------------------------------------------------------------------
st.title("🤖 IA Coach Running")
st.markdown("*Conseils personnalisés basés sur vos données Strava, propulsés par Ollama (IA locale)*")

df, error = load_activities(50)

# ---------------------------------------------------------------------------
# Sidebar — paramètres
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## ⚙️ Paramètres du coach")

    ollama = get_ollama_client()
    ollama_ok = ollama.is_available()

    if ollama_ok:
        st.success("✅ Ollama disponible")
        available_models = ollama.list_models()
        if available_models:
            current_model = os.getenv("OLLAMA_MODEL", "llama3.2")
            model_names = [m.split(":")[0] for m in available_models]
            # Trouver l'index du modèle actuel
            default_idx = 0
            for i, m in enumerate(model_names):
                if current_model.split(":")[0] in m:
                    default_idx = i
                    break
            selected_model = st.selectbox(
                "Modèle LLM",
                options=model_names,
                index=default_idx,
            )
            ollama.model = selected_model
        else:
            st.warning("⚠️ Aucun modèle téléchargé")
            st.code("./scripts/pull_model.sh", language="bash")
    else:
        st.error("❌ Ollama non disponible")
        st.info("Vérifiez que le conteneur Ollama est démarré.")

    st.divider()

    nb_activites_coach = st.slider(
        "Activités à analyser",
        min_value=5,
        max_value=20,
        value=10,
        help="Nombre de sorties récentes incluses dans le contexte de l'IA",
    )

    st.divider()

    if st.button("🗑️ Effacer l'historique", use_container_width=True):
        st.session_state.chat_history = []
        st.rerun()

    if st.button("🔄 Actualiser données", use_container_width=True):
        st.cache_data.clear()
        st.session_state.activities_summary = None
        st.rerun()


# ---------------------------------------------------------------------------
# Gestion des erreurs de connexion
# ---------------------------------------------------------------------------
if error:
    st.error(f"**Erreur Strava :** {error}")
    st.stop()

if not ollama_ok:
    st.error(
        "**Ollama n'est pas disponible.**\n\n"
        "Assurez-vous que le conteneur Docker Ollama est démarré :\n"
        "```bash\ndocker compose up -d ollama\n```"
    )
    st.stop()

if not ollama.model_is_available():
    st.warning(
        f"**Le modèle `{ollama.model}` n'est pas téléchargé.**\n\n"
        "Téléchargez-le avec :\n"
        "```bash\n./scripts/pull_model.sh\n```\n"
        "Ou directement :\n"
        f"```bash\ndocker compose exec ollama ollama pull {ollama.model}\n```"
    )
    st.stop()

if df.empty:
    st.warning("Aucune activité disponible pour l'analyse.")
    st.stop()


# ---------------------------------------------------------------------------
# Préparation du résumé des activités (mis en cache par session)
# ---------------------------------------------------------------------------
if st.session_state["_summary_n"] != nb_activites_coach or st.session_state.activities_summary is None:
    activities_summary = OllamaClient.format_activities_summary(df, n=nb_activites_coach)
    st.session_state.activities_summary = activities_summary
    st.session_state["_summary_n"] = nb_activites_coach
else:
    activities_summary = st.session_state.activities_summary

# Afficher le résumé dans un expandeur
with st.expander("📋 Données envoyées à l'IA (contexte)", expanded=False):
    st.markdown(f'<div class="summary-block">{activities_summary}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Section : Analyse automatique
# ---------------------------------------------------------------------------
st.subheader("🏃 Analyse de votre entraînement")

# Statistiques rapides
running_only = df[df["activityType"] == "running"]
if not running_only.empty:
    recent_10 = running_only.sort_values("startTimeLocal", ascending=False).head(10)
    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Sorties analysées",
        min(nb_activites_coach, len(running_only)),
    )
    col2.metric(
        "Volume (10 dernières)",
        f"{recent_10['distance_km'].sum():.1f} km",
    )
    pace_vals = recent_10[recent_10["avgPace_sec"] > 0]["avgPace_sec"]
    col3.metric(
        "Allure moyenne",
        _seconds_to_pace_str(pace_vals.mean()) if not pace_vals.empty else "—",
    )
    hr_vals = recent_10["avgHR"].dropna()
    col4.metric(
        "FC moyenne",
        f"{hr_vals.mean():.0f} bpm" if not hr_vals.empty else "—",
    )

st.divider()

# Bouton d'analyse
col_btn1, col_btn2 = st.columns([1, 3])
with col_btn1:
    analyze_clicked = st.button(
        "🤖 Analyser mon entraînement",
        type="primary",
        use_container_width=True,
    )
with col_btn2:
    st.caption(
        f"L'IA analysera vos {nb_activites_coach} dernières sorties "
        f"avec le modèle **{ollama.model}**"
    )

if analyze_clicked:
    with st.chat_message("assistant", avatar="🤖"):
        response_placeholder = st.empty()
        full_response = ""

        try:
            with st.spinner("Votre coach réfléchit..."):
                response_parts = []
                for token in ollama.analyze_training(activities_summary, stream=True):
                    full_response += token
                    response_placeholder.markdown(full_response + "▌")

            response_placeholder.markdown(full_response)

            # Sauvegarder dans l'historique (limité à MAX_CHAT_HISTORY messages)
            st.session_state.chat_history.append({
                "role": "assistant",
                "content": full_response,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "type": "analysis",
            })
            st.session_state.chat_history = st.session_state.chat_history[-MAX_CHAT_HISTORY:]

        except ConnectionError as e:
            st.error(f"Connexion impossible à Ollama : {e}")
        except TimeoutError as e:
            st.error(f"Timeout : {e}")
        except ValueError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Erreur inattendue : {e}")


# ---------------------------------------------------------------------------
# Section : Questions personnalisées
# ---------------------------------------------------------------------------
st.divider()
st.subheader("💬 Posez une question à votre coach")

# Suggestions de questions
st.markdown("**Suggestions :**")
suggestion_cols = st.columns(3)

suggestions = [
    ("🎯 Objectif", "Comment me préparer pour un semi-marathon dans 2 mois ?"),
    ("😴 Récupération", "Est-ce que je me repose suffisamment entre mes sorties ?"),
    ("📈 Progression", "Comment puis-je améliorer mon allure sur 10 km ?"),
    ("❤️ FC", "Mon profil de fréquence cardiaque est-il bon pour mon niveau ?"),
    ("🌿 Endurance", "Comment développer mon endurance fondamentale ?"),
    ("⚡ Vitesse", "Quel type de séance de vitesse me conseilles-tu ?"),
]

if "selected_suggestion" not in st.session_state:
    st.session_state.selected_suggestion = ""

for i, (label, question) in enumerate(suggestions):
    col = suggestion_cols[i % 3]
    if col.button(label, key=f"sug_{i}", use_container_width=True, help=question):
        st.session_state.selected_suggestion = question

# Zone de saisie
user_question = st.chat_input(
    "Tapez votre question ici... (ex: 'Comment améliorer ma cadence ?')"
)

# Utiliser la suggestion si sélectionnée
active_question = user_question or (
    st.session_state.selected_suggestion if st.session_state.get("selected_suggestion") else None
)

if active_question:
    # Réinitialiser la suggestion
    st.session_state.selected_suggestion = ""

    # Afficher la question
    with st.chat_message("user", avatar="🏃"):
        st.write(active_question)

    # Sauvegarder la question
    st.session_state.chat_history.append({
        "role": "user",
        "content": active_question,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "type": "question",
    })

    # Générer la réponse
    with st.chat_message("assistant", avatar="🤖"):
        response_placeholder = st.empty()
        full_response = ""

        try:
            for token in ollama.ask_custom_question(
                question=active_question,
                activities_summary=activities_summary,
                stream=True,
            ):
                full_response += token
                response_placeholder.markdown(full_response + "▌")

            response_placeholder.markdown(full_response)

            st.session_state.chat_history.append({
                "role": "assistant",
                "content": full_response,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "type": "answer",
            })
            st.session_state.chat_history = st.session_state.chat_history[-MAX_CHAT_HISTORY:]

        except ConnectionError as e:
            st.error(f"Connexion impossible à Ollama : {e}")
        except TimeoutError as e:
            st.error(f"Timeout : {e}")
        except ValueError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Erreur inattendue : {e}")


# ---------------------------------------------------------------------------
# Historique de la conversation
# ---------------------------------------------------------------------------
if st.session_state.chat_history:
    st.divider()
    with st.expander(f"📜 Historique de la session ({len(st.session_state.chat_history)} messages)", expanded=False):
        for msg in reversed(st.session_state.chat_history):
            timestamp = msg.get("timestamp", "")
            if msg["role"] == "user":
                st.markdown(
                    f'<div class="user-question">🏃 <small>{timestamp}</small><br>{msg["content"]}</div>',
                    unsafe_allow_html=True,
                )
            else:
                with st.chat_message("assistant", avatar="🤖"):
                    st.markdown(f"*{timestamp}*")
                    st.markdown(msg["content"])
