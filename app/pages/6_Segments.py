"""
Page Segments — Palmarès KOM/QOM, PR récents, segments à reconquérir, à découvrir.

On extrait les segment_efforts depuis le détail de chaque activité
(déjà cachés sur disque pour les activités déjà visitées). Le rang KOM/QOM
est celui enregistré par Strava au moment de l'effort — l'API publique
n'expose plus les leaderboards depuis 2020.

Pour la section "À découvrir", on utilise /segments/explore autour du point
de départ le plus fréquent (détecté avec heatmap_logic.detect_home).
"""

import math
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from dateutil.relativedelta import relativedelta

from heatmap_logic import detect_home
from strava_client import _seconds_to_pace_str, safe_load_activities
from ui_helpers import get_strava_client, render_strava_attribution, require_token

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Segments — Running Dashboard",
    page_icon="🏆",
    layout="wide",
)

require_token()
_athlete_id = st.session_state["strava_athlete_id"]


# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner="Chargement des activités...")
def load_activities(athlete_id: int, limit: int = 100) -> tuple[pd.DataFrame, str | None]:
    return safe_load_activities(get_strava_client(), limit)


@st.cache_data(ttl=3600, show_spinner="Analyse des segments...")
def load_segment_efforts(athlete_id: int, activity_ids: tuple[int, ...]) -> pd.DataFrame:
    """Tuple en argument pour rester hashable par st.cache_data."""
    return get_strava_client().get_segment_efforts(list(activity_ids))


@st.cache_data(ttl=3600, show_spinner="Exploration des segments populaires...")
def load_explored_segments(
    athlete_id: int,
    sw_lat: float, sw_lon: float, ne_lat: float, ne_lon: float,
) -> list[dict]:
    return get_strava_client().explore_segments(sw_lat, sw_lon, ne_lat, ne_lon)


@st.cache_data(ttl=3600, show_spinner=False)
def _detect_home_cached(
    athlete_id: int,
    starts_tuple: tuple[tuple[float, float], ...],
) -> tuple[float, float, int]:
    """Wrapper caché de heatmap_logic.detect_home (athlete_id pour isolation)."""
    return detect_home(list(starts_tuple))


# ---------------------------------------------------------------------------
# Helpers de formatage
# ---------------------------------------------------------------------------
def _format_elapsed(seconds: float | None) -> str:
    if seconds is None or pd.isna(seconds):
        return "—"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}'{s:02d}\""
    return f"{m}'{s:02d}\""


def _segment_pace(distance_m: float | None, elapsed_s: float | None) -> str:
    if not distance_m or not elapsed_s or distance_m <= 0 or elapsed_s <= 0:
        return "—"
    return _seconds_to_pace_str(elapsed_s / (distance_m / 1000))


def _rank_badge(rank: float | None) -> str:
    if rank is None or pd.isna(rank):
        return ""
    r = int(rank)
    return {1: "🥇 1er", 2: "🥈 2e", 3: "🥉 3e"}.get(r, f"#{r}")


def _fmt_distance(d: float | None) -> str:
    if d is None or pd.isna(d):
        return "—"
    return f"{d:.0f} m" if d < 1000 else f"{d / 1000:.2f} km"


def _fmt_grade(g: float | None) -> str:
    return f"{g:+.1f} %" if g is not None and not pd.isna(g) else "—"


def _fmt_location(city: str | None, country: str | None) -> str:
    parts = [p for p in (city, country) if p]
    return ", ".join(parts) if parts else "—"


def _strava_segment_link(segment_id: int) -> str:
    return f"https://www.strava.com/segments/{int(segment_id)}"


def _months_ago(d: pd.Timestamp | None) -> str:
    """Distance calendaire exacte entre `d` et maintenant ('1 an 3 mois', '8 mois', '15 j')."""
    if d is None or pd.isna(d):
        return "—"
    past = d.to_pydatetime().replace(tzinfo=None)
    rd = relativedelta(datetime.now(), past)
    if rd.years >= 1:
        suffix = "ans" if rd.years > 1 else "an"
        if rd.months:
            return f"{rd.years} {suffix} {rd.months} mois"
        return f"{rd.years} {suffix}"
    if rd.months >= 1:
        return f"{rd.months} mois"
    return f"{rd.days} j"


# ---------------------------------------------------------------------------
# UI — entête + chargement
# ---------------------------------------------------------------------------
st.title("🏆 Segments")
st.caption(
    "Tes performances sur les segments Strava. "
    "Le rang KOM/QOM est celui enregistré par Strava au moment de l'effort "
    "(les classements en temps réel ne sont plus exposés par l'API publique)."
)

df, error = load_activities(_athlete_id, 100)
if error:
    st.error(f"Erreur Strava : {error}")
    st.stop()
if df.empty:
    st.warning("Aucune activité disponible.")
    st.stop()

running = (
    df[df["activityType"] == "running"]
    .sort_values("startTimeLocal", ascending=False)
    .copy()
)
if running.empty:
    st.info("Aucune activité de course dans les 100 dernières activités.")
    st.stop()

with st.sidebar:
    st.markdown("## ⚙️ Paramètres")
    n_max = len(running)
    n_to_analyze = st.slider(
        "Activités à analyser",
        min_value=min(10, n_max),
        max_value=n_max,
        value=min(50, n_max),
        step=5,
        help=(
            "Plus tu en analyses, plus tu auras de segments — mais le premier "
            "chargement est plus long si les détails ne sont pas encore en cache."
        ),
    )

activity_ids = tuple(int(x) for x in running["activityId"].head(n_to_analyze).tolist())

with st.spinner("Récupération des segments..."):
    efforts = load_segment_efforts(_athlete_id, activity_ids)

if efforts.empty:
    st.warning(
        "Aucun segment trouvé dans les activités analysées. "
        "Strava n'expose les segment_efforts que dans le détail des activités — "
        "ouvre quelques activités depuis la page **Activités** pour peupler le cache."
    )
    st.stop()

efforts["effort_date"] = (
    pd.to_datetime(efforts["effort_date"], errors="coerce", utc=True)
    .dt.tz_convert(None)
)

# Métriques globales — comptées en segments uniques pour rester cohérent avec
# les tableaux (qui dédoublonnent par segment_id), sauf "efforts totaux".
total_efforts = len(efforts)
unique_segments = efforts["segment_id"].nunique()
top10_segments = int(
    efforts[efforts["kom_rank"].between(1, 10)]["segment_id"].nunique()
)
pr_segments = int(efforts[efforts["pr_rank"] == 1]["segment_id"].nunique())

m1, m2, m3, m4 = st.columns(4)
m1.metric("Segments parcourus", f"{unique_segments}")
m2.metric("Efforts totaux", f"{total_efforts}")
m3.metric("Segments top 10", f"{top10_segments}")
m4.metric("Segments avec PR", f"{pr_segments}")

st.divider()

section = st.radio(
    "Section",
    options=[
        "🏆 Mon palmarès KOM/QOM",
        "⏱️ Mes PR récents",
        "🎯 À reconquérir",
        "🗺️ À découvrir",
    ],
    horizontal=True,
    label_visibility="collapsed",
    key="segments_section",
)


# ---------------------------------------------------------------------------
# Helpers : enrichit un DataFrame avec les colonnes d'affichage
# ---------------------------------------------------------------------------
def _enrich_segment_info(df_segments: pd.DataFrame) -> pd.DataFrame:
    """
    Ajoute les colonnes communes Segment / Lieu / Distance / Pente / Lien.
    Marche sur tout DataFrame qui contient segment_name, segment_city,
    segment_country, segment_distance_m, segment_avg_grade, segment_id.
    """
    out = df_segments.copy()
    out["Segment"] = out["segment_name"]
    out["Lieu"] = [
        _fmt_location(c, k) for c, k in zip(out["segment_city"], out["segment_country"])
    ]
    out["Distance"] = out["segment_distance_m"].apply(_fmt_distance)
    out["Pente"] = out["segment_avg_grade"].apply(_fmt_grade)
    out["Lien"] = out["segment_id"].apply(_strava_segment_link)
    return out


def _enrich_display(df_efforts: pd.DataFrame) -> pd.DataFrame:
    """Variante pour les DataFrames d'efforts : ajoute Temps + Allure."""
    out = _enrich_segment_info(df_efforts)
    out["Temps"] = out["elapsed_time"].apply(_format_elapsed)
    out["Allure"] = out.apply(
        lambda r: _segment_pace(r["segment_distance_m"], r["elapsed_time"]), axis=1
    )
    return out


# ---------------------------------------------------------------------------
# Section 1 : palmarès KOM/QOM
# ---------------------------------------------------------------------------
if section == "🏆 Mon palmarès KOM/QOM":
    podium = efforts.dropna(subset=["kom_rank"]).copy()
    podium = podium[podium["kom_rank"].between(1, 10)]

    if podium.empty:
        st.info("Aucun top 10 KOM/QOM dans les activités analysées.")
    else:
        # Meilleur rang par segment (rang min, puis effort le plus récent en cas d'égalité)
        podium = podium.sort_values(["kom_rank", "effort_date"], ascending=[True, False])
        best = podium.drop_duplicates(subset=["segment_id"], keep="first")
        best = _enrich_display(best)
        best["Rang"] = best["kom_rank"].apply(_rank_badge)
        best["Date"] = best["effort_date"].dt.strftime("%d/%m/%Y")

        display = best[[
            "Rang", "Segment", "Lieu", "Distance", "Pente", "Temps", "Allure", "Date", "Lien",
        ]].reset_index(drop=True)

        st.subheader(f"🏆 {len(display)} segments avec top 10 KOM/QOM")
        st.dataframe(
            display,
            width="stretch",
            hide_index=True,
            column_config={
                "Rang":     st.column_config.TextColumn("🏅 Rang"),
                "Segment":  st.column_config.TextColumn("📍 Segment"),
                "Lieu":     st.column_config.TextColumn("🌍 Lieu"),
                "Distance": st.column_config.TextColumn("📏 Distance"),
                "Pente":    st.column_config.TextColumn("⛰️ Pente"),
                "Temps":    st.column_config.TextColumn("⏱️ Temps"),
                "Allure":   st.column_config.TextColumn("🐇 Allure"),
                "Date":     st.column_config.TextColumn("📅 Date"),
                "Lien":     st.column_config.LinkColumn("🔗 Strava", display_text="Voir"),
            },
        )

# ---------------------------------------------------------------------------
# Section 2 : PR récents
# ---------------------------------------------------------------------------
elif section == "⏱️ Mes PR récents":
    prs = efforts[efforts["pr_rank"] == 1].copy()

    if prs.empty:
        st.info("Aucun PR personnel marqué dans les activités analysées.")
    else:
        prs = prs.sort_values("effort_date", ascending=False)
        prs = _enrich_display(prs)
        prs["Date"] = prs["effort_date"].dt.strftime("%d/%m/%Y")
        prs["Activité"] = prs["activity_name"]

        display = prs[[
            "Date", "Segment", "Lieu", "Distance", "Pente", "Temps", "Allure", "Activité", "Lien",
        ]].reset_index(drop=True)

        st.subheader(f"⏱️ {len(display)} records personnels battus")
        st.dataframe(
            display,
            width="stretch",
            hide_index=True,
            column_config={
                "Date":     st.column_config.TextColumn("📅 Date"),
                "Segment":  st.column_config.TextColumn("📍 Segment"),
                "Lieu":     st.column_config.TextColumn("🌍 Lieu"),
                "Distance": st.column_config.TextColumn("📏 Distance"),
                "Pente":    st.column_config.TextColumn("⛰️ Pente"),
                "Temps":    st.column_config.TextColumn("⏱️ Temps"),
                "Allure":   st.column_config.TextColumn("🐇 Allure"),
                "Activité": st.column_config.TextColumn("🏃 Activité"),
                "Lien":     st.column_config.LinkColumn("🔗 Strava", display_text="Voir"),
            },
        )

# ---------------------------------------------------------------------------
# Section 3 : À reconquérir
# ---------------------------------------------------------------------------
elif section == "🎯 À reconquérir":
    st.markdown(
        "**Segments où ton meilleur rang historique est top 10 KOM/QOM** "
        "et où cet effort de référence date — un autre coureur t'a peut-être doublé "
        "depuis. Tri du plus vieux effort de référence au plus récent."
    )
    st.caption(
        "ℹ️ « Effort de référence » = date à laquelle tu as atteint ton meilleur rang sur ce "
        "segment. Tu peux y être repassé depuis sans refaire ton score."
    )

    cutoff_months = st.slider(
        "Effort de référence d'au moins (mois)",
        min_value=1, max_value=24, value=6, step=1,
        help="Ne montrer que les segments dont ton meilleur effort top 10 date d'au moins X mois.",
    )

    podium = efforts.dropna(subset=["kom_rank"]).copy()
    # On exclut les KOM (rang 1) — ils sont dans le palmarès ; ici on vise les "presque podiums" anciens.
    podium = podium[podium["kom_rank"].between(2, 10)]

    if podium.empty:
        st.info("Aucun top 10 (hors KOM/QOM) dans les activités analysées.")
    else:
        # Meilleur rang par segment, puis on garde la date de cet effort de référence
        podium = podium.sort_values(["kom_rank", "effort_date"], ascending=[True, False])
        best = podium.drop_duplicates(subset=["segment_id"], keep="first").copy()

        cutoff = pd.Timestamp(datetime.now() - relativedelta(months=cutoff_months))
        best = best[best["effort_date"] < cutoff]

        if best.empty:
            st.info(
                f"Aucun segment dont le top 10 de référence date de plus de {cutoff_months} mois. "
                "Réduis le seuil pour voir des podiums plus récents."
            )
        else:
            best = best.sort_values("effort_date", ascending=True)
            best = _enrich_display(best)
            best["Rang"] = best["kom_rank"].apply(_rank_badge)
            best["Effort de référence"] = best["effort_date"].dt.strftime("%d/%m/%Y")
            best["Date relative"] = best["effort_date"].apply(_months_ago)

            display = best[[
                "Rang", "Segment", "Lieu", "Distance", "Pente", "Temps",
                "Effort de référence", "Date relative", "Lien",
            ]].reset_index(drop=True)

            st.subheader(f"🎯 {len(display)} segments à reconquérir")
            st.dataframe(
                display,
                width="stretch",
                hide_index=True,
                column_config={
                    "Rang":                st.column_config.TextColumn("🏅 Rang atteint"),
                    "Segment":             st.column_config.TextColumn("📍 Segment"),
                    "Lieu":                st.column_config.TextColumn("🌍 Lieu"),
                    "Distance":            st.column_config.TextColumn("📏 Distance"),
                    "Pente":               st.column_config.TextColumn("⛰️ Pente"),
                    "Temps":               st.column_config.TextColumn("⏱️ Ton temps"),
                    "Effort de référence": st.column_config.TextColumn("📅 Effort de référence"),
                    "Date relative":       st.column_config.TextColumn("⏳ Il y a"),
                    "Lien":                st.column_config.LinkColumn("🔗 Strava", display_text="Voir"),
                },
            )

# ---------------------------------------------------------------------------
# Section 4 : À découvrir
# ---------------------------------------------------------------------------
else:
    # st.radio horizontal pour préserver le sous-onglet sélectionné face aux
    # reruns déclenchés par le slider sidebar ou le bouton Explorer (cf. CLAUDE.md).
    discover_section = st.radio(
        "Découverte",
        options=["📊 Proxy Local Legend (90j)", "🗺️ Tableau de chasse"],
        horizontal=True,
        label_visibility="collapsed",
        key="discover_subsection",
    )

    # --- Proxy LL : segments où tu accumules le plus d'efforts sur 90j -----
    if discover_section == "📊 Proxy Local Legend (90j)":
        st.markdown(
            "**Le Local Legend** est celui qui a fait le plus d'efforts sur un segment "
            "ces 90 derniers jours. L'API publique n'expose pas le statut LL — "
            "voici les segments où **tu accumules le plus d'efforts** sur la période, "
            "donc ceux où tu es potentiellement déjà LL ou bien placé."
        )

        min_efforts = st.slider(
            "Nombre minimum d'efforts sur 90 j",
            min_value=2, max_value=30, value=5, step=1,
            help="Le vrai Local Legend exige en général 20+ efforts ; ajuste selon ton volume.",
        )

        cutoff_90 = pd.Timestamp(datetime.now() - timedelta(days=90))
        recent = efforts[efforts["effort_date"] >= cutoff_90].copy()

        if recent.empty:
            st.info("Aucun effort dans les 90 derniers jours parmi les activités analysées.")
        else:
            agg = (
                recent.groupby("segment_id")
                .agg(
                    Efforts=("activity_id", "count"),
                    segment_name=("segment_name", "first"),
                    segment_city=("segment_city", "first"),
                    segment_country=("segment_country", "first"),
                    segment_distance_m=("segment_distance_m", "first"),
                    segment_avg_grade=("segment_avg_grade", "first"),
                    last_effort=("effort_date", "max"),
                    best_time=("elapsed_time", "min"),
                )
                .reset_index()
            )
            agg = agg[agg["Efforts"] >= min_efforts].sort_values("Efforts", ascending=False).head(25)

            if agg.empty:
                st.info(
                    f"Aucun segment couru au moins {min_efforts} fois sur 90 jours. "
                    "Baisse le seuil pour voir plus de segments, ou élargis la fenêtre d'analyse."
                )
            else:
                agg = _enrich_segment_info(agg)
                agg["Meilleur temps"] = agg["best_time"].apply(_format_elapsed)
                agg["Dernier effort"] = agg["last_effort"].dt.strftime("%d/%m/%Y")

                display = agg[[
                    "Efforts", "Segment", "Lieu", "Distance", "Pente",
                    "Meilleur temps", "Dernier effort", "Lien",
                ]].reset_index(drop=True)

                st.subheader(f"📊 {len(display)} segments les plus parcourus (90j)")
                st.dataframe(
                    display,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Efforts":        st.column_config.NumberColumn("🔁 Efforts 90j", format="%d"),
                        "Segment":        st.column_config.TextColumn("📍 Segment"),
                        "Lieu":           st.column_config.TextColumn("🌍 Lieu"),
                        "Distance":       st.column_config.TextColumn("📏 Distance"),
                        "Pente":          st.column_config.TextColumn("⛰️ Pente"),
                        "Meilleur temps": st.column_config.TextColumn("⏱️ Meilleur"),
                        "Dernier effort": st.column_config.TextColumn("📅 Dernier"),
                        "Lien":           st.column_config.LinkColumn("🔗 Strava", display_text="Voir"),
                    },
                )

    # --- Tableau de chasse : segments populaires inconnus dans ma zone ----
    else:
        st.markdown(
            "**Segments populaires** dans ta zone d'entraînement, classés par notoriété "
            "Strava. On signale ceux que tu as déjà touchés dans les activités analysées. "
            "Source : `/segments/explore` Strava."
        )

        starts = list(
            zip(
                running["startLat"].dropna().tolist(),
                running["startLon"].dropna().tolist(),
            )
        )
        if not starts:
            st.info("Aucune activité avec coordonnées GPS — impossible de définir une zone à explorer.")
        else:
            home_lat, home_lon, _ = _detect_home_cached(_athlete_id, tuple(starts))
            # Bbox de ~10 × 10 km autour du point de départ le plus fréquent.
            # Compense la convergence des méridiens : 1° lon ≈ 111 km × cos(lat).
            # Le max(..., 0.01) prévient une division par ~0 aux pôles (impossible
            # en pratique mais defensive coding gratuit).
            half_km = 5.0
            lat_offset = half_km / 111.0
            cos_lat = max(math.cos(math.radians(home_lat)), 0.01)
            lon_offset = half_km / (111.0 * cos_lat)
            sw_lat, ne_lat = home_lat - lat_offset, home_lat + lat_offset
            sw_lon, ne_lon = home_lon - lon_offset, home_lon + lon_offset

            st.caption(
                f"📍 Zone explorée : centrée sur ({home_lat:.4f}, {home_lon:.4f}) — "
                f"~10 × 10 km autour de ton point de départ le plus fréquent."
            )

            # Persistance : un clic sur Explorer arme le flag ; les reruns suivants
            # réaffichent les résultats (cache disque + cache_data Streamlit).
            # Bouton Masquer pour désarmer explicitement.
            col_go, col_clear = st.columns([3, 1])
            with col_go:
                if st.button("🔍 Explorer les segments populaires", type="primary"):
                    st.session_state["chase_explored"] = True
            with col_clear:
                if st.session_state.get("chase_explored"):
                    if st.button("🗑️ Masquer", type="secondary"):
                        st.session_state["chase_explored"] = False
                        st.rerun()

            if st.session_state.get("chase_explored"):
                with st.spinner("Appel API Strava..."):
                    segs = load_explored_segments(_athlete_id, sw_lat, sw_lon, ne_lat, ne_lon)
                if not segs:
                    st.warning("Aucun segment retourné par Strava pour cette zone.")
                else:
                    known_ids = set(efforts["segment_id"].dropna().astype(int).tolist())
                    rows = []
                    for s in segs:
                        sid = s.get("id")
                        if not sid:
                            continue
                        seen = sid in known_ids
                        rows.append({
                            "Segment": s.get("name", ""),
                            "Distance": _fmt_distance(s.get("distance")),
                            "Pente": _fmt_grade(s.get("avg_grade")),
                            "D+": (
                                f"{s.get('elev_difference', 0):.0f} m"
                                if s.get("elev_difference") is not None else "—"
                            ),
                            "Catégorie": f"Cat. {s.get('climb_category') or 0}",
                            "_seen": seen,
                            "Statut": "✅ Vu dans l'analyse" if seen else "🆕 Inédit dans l'analyse",
                            "Lien": _strava_segment_link(sid),
                        })

                    if not rows:
                        st.warning("Segments retournés mais sans identifiant exploitable.")
                    else:
                        display = (
                            pd.DataFrame(rows)
                            .sort_values("_seen", ascending=True)  # inédits en premier
                            .drop(columns=["_seen"])
                            .reset_index(drop=True)
                        )

                        st.subheader(f"🗺️ {len(display)} segments populaires dans ta zone")
                        st.dataframe(
                            display,
                            width="stretch",
                            hide_index=True,
                            column_config={
                                "Segment":   st.column_config.TextColumn("📍 Segment"),
                                "Distance":  st.column_config.TextColumn("📏 Distance"),
                                "Pente":     st.column_config.TextColumn("⛰️ Pente"),
                                "D+":        st.column_config.TextColumn("⬆️ D+"),
                                "Catégorie": st.column_config.TextColumn("🏔️ Catégorie"),
                                "Statut":    st.column_config.TextColumn("👁️ Statut"),
                                "Lien":      st.column_config.LinkColumn("🔗 Strava", display_text="Voir"),
                            },
                        )
                        st.caption(
                            "ℹ️ Strava limite l'exploration à 10 segments par appel. "
                            "« Vu dans l'analyse » signifie présent dans les activités analysées "
                            "ci-dessus — un segment couru hors fenêtre apparaîtra comme inédit."
                        )
            else:
                st.info(
                    "Clique sur **Explorer** pour interroger Strava. "
                    "Le résultat est mis en cache 1 h pour ne pas saturer l'API."
                )

render_strava_attribution()
