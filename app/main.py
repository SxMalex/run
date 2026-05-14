"""
Tableau de bord Running — Page d'accueil
Affiche les métriques clés de la semaine/mois et les dernières activités.
"""

import html
import os
from urllib.parse import parse_qsl, urlparse

import numpy as np
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta

from strava_client import (
    exchange_code,
    get_auth_url,
    safe_load_activities,
)
from ui_helpers import get_strava_client, render_activity_map, render_strava_attribution

# ---------------------------------------------------------------------------
# Configuration de la page
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Running Dashboard",
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


def _has_token() -> bool:
    return bool(
        st.session_state.get("strava_token")
        and st.session_state.get("strava_athlete_id")
    )


def _store_token(token_data: dict) -> None:
    """Stocke token + athlete_id en session après l'échange OAuth."""
    st.session_state["strava_token"] = {
        "access_token": token_data["access_token"],
        "refresh_token": token_data["refresh_token"],
        "expires_at": token_data["expires_at"],
    }
    athlete = token_data.get("athlete") or {}
    st.session_state["strava_athlete_id"] = int(athlete["id"])


# Étape 1 : callback OAuth (Strava redirige avec ?code=XXX).
# Note : on ne valide pas un paramètre `state` côté serveur car
# st.session_state ne survit pas toujours au redirect externe vers Strava
# (la WebSocket se reconnecte parfois en nouvelle session). Le redirect_uri
# est vérouillé côté Strava → le risque CSRF résiduel est marginal pour
# ce dashboard en lecture seule.
_params = st.query_params
if "code" in _params and not _has_token():
    if "error" in _params:
        st.error(f"Autorisation refusée : {_params['error']}")
        st.query_params.clear()
    else:
        with st.spinner("Connexion à Strava en cours..."):
            try:
                _token = exchange_code(_client_id, _client_secret, _params["code"])
                _store_token(_token)
                st.query_params.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Erreur lors de l'échange du code : {e}")
                st.query_params.clear()

# Étape 2 : pas de token → page de connexion
if not _has_token():
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
                f"Définissez l'**Authorization Callback Domain** sur le domaine de `{_redirect_uri}`"
            )
        else:
            _auth_url = get_auth_url(_client_id, _redirect_uri)
            st.markdown(
                "<p style='text-align:center; color:#888; margin-bottom: 24px;'>"
                "Autorisez l'accès en lecture à vos activités Strava."
                "</p>",
                unsafe_allow_html=True,
            )
            # Soumission de formulaire pour rester dans l'onglet courant.
            # Une soumission de <form> en GET navigue l'onglet par défaut
            # (pas de target="_blank" forcé par le sanitizer Streamlit, qui
            # ne réécrit que les <a>). On éclate les query params en hidden
            # inputs pour que le browser construise l'URL OAuth proprement.
            _parsed = urlparse(_auth_url)
            _action = html.escape(
                f"{_parsed.scheme}://{_parsed.netloc}{_parsed.path}", quote=True
            )
            _hidden_inputs = "\n".join(
                f'<input type="hidden" '
                f'name="{html.escape(k, quote=True)}" '
                f'value="{html.escape(v, quote=True)}">'
                for k, v in parse_qsl(_parsed.query)
            )
            st.markdown(
                f"""
                <form action="{_action}" method="get" style="margin: 0;">
                  {_hidden_inputs}
                  <button type="submit" class="strava-connect-btn">
                    🔗 Connecter à Strava
                  </button>
                </form>
                <style>
                  .strava-connect-btn {{
                    display: block;
                    width: 100%;
                    box-sizing: border-box;
                    padding: 0.6rem 1rem;
                    background: #fc4c02;
                    color: white;
                    text-align: center;
                    font-weight: 600;
                    font-size: 1rem;
                    border-radius: 0.5rem;
                    border: 1px solid #fc4c02;
                    cursor: pointer;
                    transition: background 0.15s ease;
                  }}
                  .strava-connect-btn:hover {{
                    background: #e54400;
                    border-color: #e54400;
                  }}
                </style>
                """,
                unsafe_allow_html=True,
            )
            st.caption(
                f"Vous serez redirigé vers Strava, puis automatiquement "
                f"renvoyé sur `{_redirect_uri}`."
            )
    st.stop()


@st.cache_data(ttl=3600, show_spinner=False)
def load_athlete(athlete_id: int) -> dict:
    return get_strava_client().get_athlete()


@st.cache_data(ttl=3600, show_spinner=False)
def load_athlete_stats(athlete_id: int) -> dict:
    return get_strava_client().get_athlete_stats()


@st.cache_data(ttl=3600, show_spinner=False)
def load_athlete_zones(athlete_id: int) -> list:
    zones_data = get_strava_client().get_athlete_zones()
    return zones_data.get("heart_rate", {}).get("zones", [])


@st.cache_data(ttl=3600, show_spinner="Chargement des activités Strava...")
def load_activities(athlete_id: int, limit: int = 100) -> tuple[pd.DataFrame, str | None]:
    """Charge les activités depuis Strava (cache Streamlit 1h, par athlète)."""
    return safe_load_activities(get_strava_client(), limit)


_athlete_id = st.session_state["strava_athlete_id"]

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

    if st.button("🔄 Actualiser les données", width='stretch'):
        get_strava_client().invalidate_cache()
        st.cache_data.clear()
        st.rerun()

    if st.button("🚪 Déconnexion", width='stretch'):
        # On vide uniquement la session — pas le cache global : ça affecterait
        # les autres utilisateurs connectés. Le cache @st.cache_data est isolé
        # par athlete_id via les arguments de fonction, donc inoffensif.
        for key in ("strava_token", "strava_athlete_id"):
            st.session_state.pop(key, None)
        st.rerun()

    st.divider()
    st.caption(f"Dernière mise à jour : {datetime.now().strftime('%H:%M:%S')}")


# ---------------------------------------------------------------------------
# Chargement des données
# ---------------------------------------------------------------------------
df, error = load_activities(_athlete_id, nb_activites)

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
        for key in ("strava_token", "strava_athlete_id"):
            st.session_state.pop(key, None)
        st.rerun()
    st.stop()

if df.empty:
    st.warning("Aucune activité trouvée. Vérifiez votre configuration.")
    st.stop()

# Chaussures dans la sidebar — chargé ici, après vérification de la connexion
with st.sidebar:
    st.divider()
    athlete = load_athlete(_athlete_id)
    shoes = athlete.get("shoes", [])
    if athlete and not shoes:
        st.markdown("### 👟 Chaussures")
        st.caption("Aucune chaussure configurée dans ton profil Strava.")
    elif shoes:
        st.markdown("### 👟 Chaussures")
        for shoe in shoes:
            km = round(shoe.get("distance", 0) / 1000)
            label = shoe.get("name") or shoe.get("nickname") or f"Chaussure {shoe.get('id', '')}"
            retired = shoe.get("retired", False)
            if retired:
                st.caption(f"~~{label}~~ — {km} km *(retirée)*")
            else:
                st.caption(f"**{label}** — {km} km")
                st.progress(min(km / 800, 1.0), text=f"{min(round(km / 8), 100)} %")
        st.caption("Objectif indicatif : 800 km")

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
# Statistiques de carrière
# ---------------------------------------------------------------------------
stats = load_athlete_stats(_athlete_id)
if stats:
    def _totals(key: str) -> tuple[float, float, int]:
        t = stats.get(key, {})
        return round(t.get("distance", 0) / 1000, 0), round(t.get("elevation_gain", 0), 0), t.get("count", 0)

    all_km, all_elev, all_count = _totals("all_run_totals")
    ytd_km, ytd_elev, ytd_count = _totals("ytd_run_totals")
    rec_km, rec_elev, rec_count = _totals("recent_run_totals")

    st.subheader("🏆 Statistiques de carrière")
    s1, s2, s3, s4, s5, s6 = st.columns(6)
    s1.metric("Km all-time",      f"{all_km:,.0f} km")
    s2.metric("D+ all-time",      f"{all_elev:,.0f} m")
    s3.metric("Sorties all-time", f"{all_count:,}")
    s4.metric("Km cette année",   f"{ytd_km:,.0f} km",
              delta=f"+{rec_km:.0f} km (4 sem.)", delta_color="off")
    s5.metric("D+ cette année",   f"{ytd_elev:,.0f} m",
              delta=f"+{rec_elev:.0f} m (4 sem.)", delta_color="off")
    s6.metric("Sorties cette année", f"{ytd_count:,}",
              delta=f"+{rec_count} (4 sem.)", delta_color="off")
    st.divider()

# ---------------------------------------------------------------------------
# Estimations de performance — Formule de Riegel
# ---------------------------------------------------------------------------
st.subheader("🏆 Meilleures performances estimées")

_RIEGEL_EXPONENT = 1.06
_RACE_TARGETS = [
    ("5 km",      5.0,     "🥇"),
    ("10 km",    10.0,     "🥈"),
    ("Semi",     21.0975,  "🥉"),
    ("Marathon", 42.195,   "🏅"),
]


@st.cache_data(ttl=3600)
def _riegel_estimates(runs: pd.DataFrame) -> list[dict]:
    valid = runs[(runs["avgPace_sec"] > 0) & (runs["distance_km"] >= 1.0)]
    if valid.empty:
        return []
    d1 = valid["distance_km"].to_numpy()
    t1 = valid["avgPace_sec"].to_numpy() * d1
    results = []
    for label, target_km, icon in _RACE_TARGETS:
        best_sec = float((t1 * (target_km / d1) ** _RIEGEL_EXPONENT).min())
        if not np.isfinite(best_sec) or best_sec <= 0:
            continue
        h, rem = divmod(int(best_sec), 3600)
        m, s = divmod(rem, 60)
        results.append({
            "label": label, "icon": icon,
            "time": f"{h}h{m:02d}'{s:02d}\"" if h else f"{m}'{s:02d}\"",
            "pace": f"{int(best_sec / target_km // 60)}:{int(best_sec / target_km % 60):02d}/km",
        })
    return results


if not running_df.empty:
    estimates = _riegel_estimates(running_df)
    if estimates:
        cols = st.columns(len(estimates))
        for col, est in zip(cols, estimates):
            with col:
                st.metric(label=f"{est['icon']} {est['label']}", value=est["time"], delta=est["pace"], delta_color="off")
        st.caption("Estimations via la formule de Riegel (T2 = T1 × (D2/D1)^1.06) — à titre indicatif.")

st.divider()

# ---------------------------------------------------------------------------
# Tableau des dernières activités
# ---------------------------------------------------------------------------
st.subheader("🏅 Dernière activité")


@st.cache_data(ttl=3600, show_spinner="Chargement des détails...")
def load_last_activity_details(athlete_id: int, activity_id: int) -> dict:
    return get_strava_client().get_activity_details(activity_id)


@st.cache_data(ttl=3600, show_spinner=False)
def load_last_activity_streams(athlete_id: int, activity_id: int) -> dict:
    return get_strava_client().get_streams(activity_id)


def _render_elevation_profile(streams: dict) -> None:
    alts = streams.get("altitude", [])
    dists = streams.get("distance", [])
    if not alts or not dists:
        st.caption("Profil altimétrique non disponible.")
        return
    dists_km = [d / 1000 for d in dists]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dists_km, y=alts,
        mode="lines",
        fill="tozeroy",
        fillcolor="rgba(252,76,2,0.15)",
        line=dict(color="#fc4c02", width=2),
        hovertemplate="<b>%{x:.2f} km</b><br>Altitude : %{y:.0f} m<extra></extra>",
    ))
    fig.update_layout(
        height=210,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc"),
        xaxis=dict(title="Distance (km)", gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(title="Altitude (m)", gridcolor="rgba(255,255,255,0.05)"),
        margin=dict(l=0, r=0, t=10, b=0), showlegend=False,
    )
    st.plotly_chart(fig)


def _render_hr_chart(splits_df: pd.DataFrame, max_hr: int, hr_zones: list | None = None) -> None:
    hr_data = splits_df["avgHR"].dropna()
    if hr_data.empty:
        st.caption("FC non disponible pour cette activité.")
        return

    _zone_colors = ["#3b82f6", "#22c55e", "#eab308", "#f97316", "#ef4444"]

    def _hr_color(hr):
        if not hr or pd.isna(hr):
            return "rgba(100,100,100,0.5)"
        if hr_zones:
            for i, z in enumerate(hr_zones):
                zmax = z["max"] if z["max"] != -1 else float("inf")
                if z["min"] <= hr < zmax:
                    return _zone_colors[min(i, 4)]
            return _zone_colors[-1]
        pct = hr / max_hr
        if pct < 0.60: return _zone_colors[0]
        if pct < 0.70: return _zone_colors[1]
        if pct < 0.80: return _zone_colors[2]
        if pct < 0.90: return _zone_colors[3]
        return _zone_colors[4]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=splits_df["lap"].astype(str),
        y=splits_df["avgHR"],
        marker_color=[_hr_color(hr) for hr in splits_df["avgHR"]],
        hovertemplate="<b>Km %{x}</b><br>FC : %{y:.0f} bpm<extra></extra>",
    ))
    fig.update_layout(
        height=210,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc"),
        xaxis=dict(title="Km", gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(title="FC (bpm)", gridcolor="rgba(255,255,255,0.05)"),
        margin=dict(l=0, r=0, t=10, b=0), showlegend=False,
    )
    st.plotly_chart(fig)


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
        details = load_last_activity_details(_athlete_id, int(last["activityId"]))
        streams = load_last_activity_streams(_athlete_id, int(last["activityId"]))

    if details:
        splits = details.get("splits", [])
        splits_df = pd.DataFrame(splits) if splits else pd.DataFrame()
        max_hr = int(details.get("details", {}).get("max_heartrate") or 190)

        # ── Ligne 1 : carte | allure par km ───────────────────────────────
        col_map, col_pace = st.columns([3, 2])

        with col_map:
            render_activity_map(details, height=300)

        with col_pace:
            st.caption("Allure par km")
            if not splits_df.empty:
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
                    height=300,
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#ccc"),
                    xaxis=dict(title="Km", gridcolor="rgba(255,255,255,0.05)"),
                    yaxis=dict(title="Allure (min/km)", gridcolor="rgba(255,255,255,0.05)", tickformat=".1f"),
                    margin=dict(l=0, r=0, t=10, b=0), showlegend=False,
                )
                st.plotly_chart(fig_s)

        # ── Ligne 2 : profil altimétrique | FC par km ─────────────────────
        col_elev, col_hr = st.columns([3, 2])

        with col_elev:
            st.caption("Profil altimétrique")
            _render_elevation_profile(streams)

        with col_hr:
            st.caption("Fréquence cardiaque par km")
            if not splits_df.empty:
                _render_hr_chart(splits_df, max_hr, load_athlete_zones(_athlete_id))
else:
    st.info("Aucune activité de course trouvée dans les données chargées.")

# ---------------------------------------------------------------------------
# Pied de page
# ---------------------------------------------------------------------------
st.divider()
if not running_df.empty:
    total_km = running_df["distance_km"].sum()
    st.caption(f"Total chargé : {total_km:.0f} km sur {len(running_df)} sorties")
render_strava_attribution()
