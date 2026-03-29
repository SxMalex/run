"""
Tableau de bord Running — Page d'accueil
Affiche les métriques clés de la semaine/mois et les dernières activités.
"""

import os
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import polyline as polyline_lib
from datetime import datetime, timedelta

from strava_client import StravaClient, TOKEN_FILE, get_auth_url, exchange_code
from llm_client import OllamaClient

# ---------------------------------------------------------------------------
# Configuration de la page
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="🏃 Running Dashboard",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": "Tableau de bord Running — Données Strava + IA Coach",
    },
)

# ---------------------------------------------------------------------------
# CSS personnalisé
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    .status-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .status-ok { background: #1a3a2a; color: #4ade80; border: 1px solid #4ade80; }
    .status-error { background: #3a1a1a; color: #f87171; border: 1px solid #f87171; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# OAuth Strava — gestion du callback et de la page de connexion
# ---------------------------------------------------------------------------
_client_id = os.getenv("STRAVA_CLIENT_ID", "")
_client_secret = os.getenv("STRAVA_CLIENT_SECRET", "")
_redirect_uri = os.getenv("STRAVA_REDIRECT_URI", "http://localhost:8501")

# Étape 1 : pas de token → afficher la page de connexion
# (vérifié avant le callback pour éviter une boucle si le token vient d'être créé)

# Étape 2 : Strava a redirigé ici avec ?code=XXX → échange le code contre les tokens
_params = st.query_params
if "code" in _params:
    if "error" in _params:
        st.error(f"Autorisation refusée : {_params['error']}")
    else:
        with st.spinner("Connexion à Strava en cours..."):
            try:
                _token = exchange_code(_client_id, _client_secret, _params["code"])
                st.query_params.clear()
                st.cache_resource.clear()
                st.rerun()
            except Exception as _e:
                st.error(f"Erreur lors de l'échange du code : {_e}")
                st.query_params.clear()

# Étape 1 (suite) : toujours pas de token → page de connexion
if not TOKEN_FILE.exists():
    st.markdown("""
    <div class="dashboard-header" style="text-align:center; padding: 48px 32px;">
        <h1 style="margin:0; font-size: 2.5rem;">🏃 Running Dashboard</h1>
        <p style="margin: 12px 0 0; color: #888; font-size: 1.1rem;">
            Connectez votre compte Strava pour accéder à votre tableau de bord
        </p>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    col_a, col_b, col_c = st.columns([1, 2, 1])
    with col_b:
        if not _client_id or not _client_secret:
            st.error(
                "**Variables manquantes dans `.env`**\n\n"
                "Renseignez `STRAVA_CLIENT_ID` et `STRAVA_CLIENT_SECRET` puis redémarrez l'application."
            )
            st.info(
                "Créez votre application Strava sur [strava.com/settings/api](https://www.strava.com/settings/api)\n\n"
                f"Définissez l'**Authorization Callback Domain** sur `localhost`\n\n"
                f"Et l'URL de redirection sur `{_redirect_uri}`"
            )
        else:
            _auth_url = get_auth_url(_client_id, _redirect_uri)
            st.markdown(
                "<p style='text-align:center; color:#888; margin-bottom: 24px;'>"
                "Autorisez l'accès en lecture à vos activités Strava."
                "</p>",
                unsafe_allow_html=True,
            )
            st.link_button(
                "🔗 Connecter à Strava",
                _auth_url,
                use_container_width=True,
                type="primary",
            )
            st.caption(
                f"Vous serez redirigé vers Strava, puis automatiquement "
                f"renvoyé sur `{_redirect_uri}`."
            )
    st.stop()

@st.cache_resource
def get_strava_client() -> StravaClient:
    """Singleton du client Strava."""
    return StravaClient()


@st.cache_resource
def get_ollama_client() -> OllamaClient:
    """Singleton du client Ollama."""
    return OllamaClient()


@st.cache_data(ttl=3600, show_spinner="Chargement des activités Strava...")
def load_activities(limit: int = 100) -> tuple[pd.DataFrame, str | None]:
    """
    Charge les activités depuis Strava (avec cache Streamlit 1h).
    Retourne (DataFrame, message_erreur).
    """
    client = get_strava_client()
    try:
        df = client.get_activities(limit=limit)
        return df, None
    except ValueError as e:
        return pd.DataFrame(), str(e)
    except Exception as e:
        return pd.DataFrame(), f"Erreur de connexion Strava : {e}"


# ---------------------------------------------------------------------------
# Barre latérale
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## ⚙️ Paramètres")

    nb_activites = st.slider(
        "Nombre d'activités à charger",
        min_value=20,
        max_value=200,
        value=100,
        step=10,
    )

    if st.button("🔄 Actualiser les données", use_container_width=True):
        st.cache_data.clear()
        st.session_state.activities_df = None
        st.rerun()

    st.divider()

    # Statut Ollama
    ollama = get_ollama_client()
    ollama_ok = ollama.is_available()
    model_ok = ollama.model_is_available() if ollama_ok else False

    st.markdown("### 🤖 Statut IA")
    if ollama_ok:
        st.markdown(
            '<span class="status-badge status-ok">✓ Ollama connecté</span>',
            unsafe_allow_html=True,
        )
        if model_ok:
            st.markdown(
                f'<span class="status-badge status-ok">✓ {ollama.model}</span>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<span class="status-badge status-error">✗ {ollama.model} non trouvé</span>',
                unsafe_allow_html=True,
            )
            st.caption("Lancez : `./scripts/pull_model.sh`")
    else:
        st.markdown(
            '<span class="status-badge status-error">✗ Ollama non disponible</span>',
            unsafe_allow_html=True,
        )

    st.divider()
    st.caption(f"Dernière mise à jour : {datetime.now().strftime('%H:%M:%S')}")


# ---------------------------------------------------------------------------
# Chargement des données
# ---------------------------------------------------------------------------
df, error = load_activities(nb_activites)

# ---------------------------------------------------------------------------
# En-tête principal
# ---------------------------------------------------------------------------
st.title("🏃 Running Dashboard")
st.caption("Analyse de vos performances de course — Données Strava")

# ---------------------------------------------------------------------------
# Gestion des erreurs Strava
# ---------------------------------------------------------------------------
if error:
    st.error(f"**Erreur de connexion Strava**\n\n{error}")
    if st.button("🔄 Reconnecter à Strava"):
        TOKEN_FILE.unlink(missing_ok=True)
        st.cache_resource.clear()
        st.rerun()
    st.stop()

if df.empty:
    st.warning("Aucune activité trouvée. Vérifiez votre configuration.")
    st.stop()

# ---------------------------------------------------------------------------
# Métriques résumées
# ---------------------------------------------------------------------------
client = get_strava_client()
metrics = client.get_summary_metrics(df)
running_df = df[df["activityType"] == "running"]

col1, col2, col3, col4, col5, col6, col7 = st.columns(7)

total_kudos = int(df["kudosCount"].sum()) if "kudosCount" in df.columns else 0

metric_data = [
    (col1, metrics["km_semaine"], "km", "Cette semaine", "🗓️"),
    (col2, metrics["km_mois"], "km", "Ce mois", "📅"),
    (col3, metrics["nb_sorties_semaine"], "", "Sorties / semaine", "👟"),
    (col4, metrics["nb_sorties_mois"], "", "Sorties / mois", "📊"),
    (col5, metrics["pace_moyen"], "", "Allure moyenne", "⏱️"),
    (col6, metrics["hr_moyen"], "", "FC moyenne", "❤️"),
    (col7, total_kudos, "", "Kudos reçus", "👍"),
]

for col, value, unit, label, icon in metric_data:
    with col:
        st.metric(label=f"{icon} {label}", value=f"{value} {unit}".strip())

st.divider()

# ---------------------------------------------------------------------------
# Prédictions de performance — Formule de Riegel
# ---------------------------------------------------------------------------
st.subheader("🏆 Meilleures performances estimées")

@st.cache_data(ttl=3600)
def _predict_race_times(runs: pd.DataFrame) -> list[dict]:
    """
    Estime les temps sur 5km, 10km, semi et marathon via la formule de Riegel :
    T2 = T1 × (D2 / D1) ^ 1.06
    Pour chaque distance cible, on prend la projection la plus optimiste
    parmi toutes les sorties disponibles (vectorisé avec NumPy).
    """
    valid = runs[(runs["avgPace_sec"] > 0) & (runs["distance_km"] >= 1.0)]
    if valid.empty:
        return []

    targets = [
        ("5 km",     5.0,      "🥇"),
        ("10 km",    10.0,     "🥈"),
        ("Semi",     21.0975,  "🥉"),
        ("Marathon", 42.195,   "🏅"),
    ]

    d1 = valid["distance_km"].to_numpy()
    t1 = valid["avgPace_sec"].to_numpy() * d1  # temps total en secondes

    results = []
    for label, target_km, icon in targets:
        t2 = t1 * (target_km / d1) ** 1.06     # projection Riegel vectorisée
        best_sec = float(t2.min())

        h = int(best_sec // 3600)
        m = int((best_sec % 3600) // 60)
        s = int(best_sec % 60)
        time_str = f"{h}h{m:02d}'{s:02d}\"" if h > 0 else f"{m}'{s:02d}\""
        pace_sec = best_sec / target_km
        pace_str = f"{int(pace_sec // 60)}:{int(pace_sec % 60):02d}/km"
        results.append({"label": label, "icon": icon, "time": time_str, "pace": pace_str})

    return results

if not running_df.empty:
    predictions = _predict_race_times(running_df)
    if predictions:
        cols = st.columns(len(predictions))
        for col, pred in zip(cols, predictions):
            with col:
                st.metric(
                    label=f"{pred['icon']} {pred['label']}",
                    value=pred["time"],
                    delta=pred["pace"],
                    delta_color="off",
                )
        st.caption("Estimations basées sur la formule de Riegel (T2 = T1 × (D2/D1)^1.06) — à titre indicatif.")

        # ── Évolution des prédictions dans le temps ────────────────────────
        @st.cache_data(ttl=3600)
        def _riegel_history(runs: pd.DataFrame, window_days: int = 60) -> pd.DataFrame:
            """
            Pour chaque semaine, calcule la meilleure prédiction Riegel sur les
            `window_days` jours précédents. Renvoie un DataFrame avec une colonne
            par distance cible (en secondes).
            """
            valid = runs[(runs["avgPace_sec"] > 0) & (runs["distance_km"] >= 1.0)].copy()
            if len(valid) < 2:
                return pd.DataFrame()

            targets = [("5 km", 5.0), ("10 km", 10.0), ("Semi", 21.0975), ("Marathon", 42.195)]
            valid = valid.sort_values("startTimeLocal")

            first = valid["startTimeLocal"].min()
            last  = pd.Timestamp(datetime.now())
            weekly_ends = pd.date_range(first + timedelta(days=window_days), last, freq="W-MON")

            rows = []
            for week_end in weekly_ends:
                window = valid[
                    (valid["startTimeLocal"] > week_end - timedelta(days=window_days))
                    & (valid["startTimeLocal"] <= week_end)
                ]
                if window.empty:
                    continue
                d1 = window["distance_km"].to_numpy()
                t1 = window["avgPace_sec"].to_numpy() * d1
                row = {"date": week_end}
                for label, target_km in targets:
                    t2 = t1 * (target_km / d1) ** 1.06
                    row[label] = float(t2.min())   # secondes
                rows.append(row)

            return pd.DataFrame(rows)

        window = st.slider(
            "Fenêtre glissante (jours)", min_value=14, max_value=90, value=30, step=7,
            key="riegel_window",
        )
        hist = _riegel_history(running_df, window_days=window)

        if not hist.empty:
            def _fmt_sec(s: float) -> str:
                h, rem = divmod(int(s), 3600)
                m, sec = divmod(rem, 60)
                return f"{h}h{m:02d}'{sec:02d}\"" if h else f"{m}'{sec:02d}\""

            colors = {
                "5 km":     "#4ade80",
                "10 km":    "#7c9cfc",
                "Semi":     "#fb923c",
                "Marathon": "#f87171",
            }

            fig_hist = go.Figure()
            for label, color in colors.items():
                if label not in hist.columns:
                    continue
                col_min = hist[label].min()
                fig_hist.add_trace(go.Scatter(
                    x=hist["date"],
                    y=hist[label] / 60,          # minutes pour l'axe Y
                    mode="lines",
                    name=label,
                    line=dict(color=color, width=2),
                    customdata=hist[label].apply(_fmt_sec),
                    hovertemplate=(
                        f"<b>{label}</b> · %{{x|%b %Y}}<br>"
                        "Meilleur estimé : <b>%{customdata}</b><extra></extra>"
                    ),
                ))
                # Annotation sur le meilleur point
                best_idx = hist[label].idxmin()
                fig_hist.add_annotation(
                    x=hist.loc[best_idx, "date"],
                    y=col_min / 60,
                    text=f"  ↓ {_fmt_sec(col_min)}",
                    font=dict(color=color, size=10),
                    showarrow=False,
                    xanchor="left",
                )

            fig_hist.update_layout(
                height=300,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#ccc"),
                xaxis=dict(gridcolor="rgba(255,255,255,0.05)", title="Date"),
                yaxis=dict(
                    gridcolor="rgba(255,255,255,0.05)",
                    title="Temps estimé (min)",
                    tickformat=".0f",
                ),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(l=0, r=0, t=30, b=0),
                hovermode="x unified",
            )
            st.plotly_chart(fig_hist, use_container_width=True)
            st.caption(f"Fenêtre glissante de {window} jours — ↓ = amélioration des performances.")

st.divider()

# ---------------------------------------------------------------------------
# Tableau des dernières activités
# ---------------------------------------------------------------------------
st.subheader("🏅 Dernière activité")


@st.cache_data(ttl=3600, show_spinner="Chargement des détails...")
def load_last_activity_details(activity_id: int) -> dict:
    return get_strava_client().get_activity_details(activity_id)


def _render_last_activity_map(details_data: dict) -> None:
    map_data = details_data.get("details", {}).get("map", {})
    encoded = map_data.get("polyline") or map_data.get("summary_polyline")
    if not encoded:
        return
    coords = polyline_lib.decode(encoded)
    if not coords:
        return
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    center_lat = (min(lats) + max(lats)) / 2
    center_lon = (min(lons) + max(lons)) / 2
    max_range = max(max(lats) - min(lats), max(lons) - min(lons))
    zoom = 15 if max_range < 0.01 else 13 if max_range < 0.05 else 12 if max_range < 0.15 else 11 if max_range < 0.4 else 10

    fig = go.Figure()
    fig.add_trace(go.Scattermapbox(
        lat=lats, lon=lons, mode="lines",
        line=dict(width=4, color="#fc4c02"), hoverinfo="none",
    ))
    fig.add_trace(go.Scattermapbox(
        lat=[lats[0], lats[-1]], lon=[lons[0], lons[-1]],
        mode="markers", marker=dict(size=14, color=["#22c55e", "#ef4444"]),
        text=["Départ", "Arrivée"], hoverinfo="text",
    ))
    fig.update_layout(
        mapbox=dict(style="open-street-map", center=dict(lat=center_lat, lon=center_lon), zoom=zoom),
        height=380, margin=dict(l=0, r=0, t=0, b=0), showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


if not running_df.empty:
    last = running_df.sort_values("startTimeLocal", ascending=False).iloc[0]
    date_fmt = pd.to_datetime(last["startTimeLocal"]).strftime("%A %d %B %Y à %H:%M")

    st.markdown(f"#### {last['activityName']}")
    st.caption(f"📅 {date_fmt}")

    m1, m2, m3, m4, m5, m6, m7, m8 = st.columns(8)
    m1.metric("📏 Distance",  f"{last['distance_km']:.2f} km")
    m2.metric("⏱️ Durée",     f"{int(last['duration_min'])} min")
    m3.metric("🐇 Allure",    last["avgPace"])
    m4.metric("❤️ FC moy",    f"{int(last['avgHR'])} bpm"       if pd.notna(last.get("avgHR"))       else "—")
    m5.metric("❤️‍🔥 FC max",   f"{int(last['maxHR'])} bpm"       if pd.notna(last.get("maxHR"))       else "—")
    m6.metric("🦶 Cadence",   f"{int(last['avgCadence'])} spm"  if pd.notna(last.get("avgCadence"))  else "—")
    m7.metric("🔥 Calories",  f"{int(last['calories'])} kcal"   if pd.notna(last.get("calories"))    else "—")
    m8.metric("⛰️ D+",        f"{int(last['elevationGain'])} m" if pd.notna(last.get("elevationGain")) else "—")

    with st.spinner("Chargement de la carte et des splits..."):
        details = load_last_activity_details(int(last["activityId"]))

    if details:
        col_map, col_splits = st.columns([3, 2])

        with col_map:
            _render_last_activity_map(details)

        with col_splits:
            splits = details.get("splits", [])
            if splits:
                splits_df = pd.DataFrame(splits)
                avg_pace = splits_df.loc[splits_df["pace_sec"] > 0, "pace_sec"].mean()
                fig_s = go.Figure()
                fig_s.add_trace(go.Bar(
                    x=splits_df["lap"].astype(str),
                    y=splits_df["pace_sec"].apply(lambda s: s / 60 if s > 0 else None),
                    marker_color=[
                        "rgba(74,222,128,0.85)" if (p > 0 and p < avg_pace) else "rgba(124,156,252,0.85)"
                        for p in splits_df["pace_sec"]
                    ],
                    hovertemplate="<b>Km %{x}</b><br>%{customdata}<extra></extra>",
                    customdata=splits_df["pace"],
                ))
                fig_s.update_layout(
                    height=380,
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#ccc"),
                    xaxis=dict(title="Km", gridcolor="rgba(255,255,255,0.05)"),
                    yaxis=dict(title="Allure (min/km)", gridcolor="rgba(255,255,255,0.05)", tickformat=".1f"),
                    margin=dict(l=0, r=0, t=10, b=0), showlegend=False,
                )
                st.plotly_chart(fig_s, use_container_width=True)
else:
    st.info("Aucune activité de course trouvée dans les données chargées.")

# ---------------------------------------------------------------------------
# Pied de page
# ---------------------------------------------------------------------------
st.divider()
col_l, col_r = st.columns([3, 1])
with col_l:
    st.caption(
        "Données issues de l'API officielle Strava. "
        "Analyse IA propulsée par Ollama (local)."
    )
with col_r:
    if not running_df.empty:
        total_km = running_df["distance_km"].sum()
        st.caption(f"Total chargé : {total_km:.0f} km sur {len(running_df)} sorties")
