# 🏃 Running Dashboard

Tableau de bord pour l'analyse de vos données de course à pied.
Se connecte à **Strava** via son API officielle, génère des **parcours inédits** via OpenRouteService,
et produit des **prompts d'analyse IA** prêts à coller dans Claude, ChatGPT ou Gemini.

Multi-utilisateur (token OAuth en session, jamais persisté), conçu pour tourner aussi bien en local
qu'en production derrière un reverse-proxy HTTPS.

---

## Fonctionnalités

- **Accueil** — métriques clés semaine/mois, dernière activité détaillée (carte + splits), estimations de performance Riegel
- **Activités** — liste filtrée par date, type et distance ; détail complet avec graphique des splits et streams Garmin-style (altitude / allure / FC)
- **Statistiques** — 6 onglets : volume, allure, FC, cadence, régularité, charge d'entraînement (CTL/ATL/TSB)
- **IA Coach** — génère un prompt prêt à coller dans n'importe quel LLM (Claude, ChatGPT, Gemini…) avec votre contexte d'entraînement
- **Prochaine sortie** — recommandation de séance basée sur la forme actuelle + parcours en boucle généré sur OpenStreetMap + export GPX pour Garmin
- **Heatmap** — cartes de chaleur des courses (fréquence, allure, FC, pente absolue, dénivelé signé) sur fond CartoDB sombre

---

## Prérequis

| Outil | Version minimale | Vérification |
|---|---|---|
| [Docker](https://docs.docker.com/get-docker/) | 24.x | `docker --version` |
| [Docker Compose](https://docs.docker.com/compose/install/) | v2.x | `docker compose version` |
| Compte Strava | — | [strava.com](https://www.strava.com) |
| Clé API OpenRouteService | — | [openrouteservice.org](https://openrouteservice.org/dev/#/signup) *(gratuit, optionnel)* |

---

## Démarrage rapide (dev local)

### 1. Cloner le projet

```bash
git clone <url-du-repo> running-dashboard
cd running-dashboard
```

### 2. Créer une application Strava

1. Rendez-vous sur [strava.com/settings/api](https://www.strava.com/settings/api)
2. Créez une application (le nom et la description sont libres)
3. Définissez l'**Authorization Callback Domain** sur `localhost`
4. Notez le **Client ID** et le **Client Secret**

### 3. Configurer l'environnement

```bash
cp .env.example .env
```

Éditez le fichier `.env` :

```dotenv
STRAVA_CLIENT_ID=votre_client_id
STRAVA_CLIENT_SECRET=votre_client_secret
STRAVA_REDIRECT_URI=http://localhost:8501
CACHE_TTL=3600

# Optionnel — page Prochaine sortie
ORS_API_KEY=votre_cle_ors
```

> ⚠️ **Sécurité :** le fichier `.env` ne doit jamais être versionné (il est dans `.gitignore`).

### 4. Démarrer

```bash
docker compose up -d
```

Cela lance Streamlit sur le port `8501` avec hot-reload (un changement dans `app/*.py` est rechargé sans redémarrer le container).

### 5. Connecter votre compte Strava

Ouvrez **[http://localhost:8501](http://localhost:8501)**, cliquez sur **"🔗 Connecter à Strava"**, autorisez l'application, et vous arrivez sur le tableau de bord.

Le token OAuth vit dans la session du navigateur (`st.session_state`). Il est rafraîchi automatiquement tant que la session est ouverte. À la fermeture de l'onglet, une nouvelle connexion est demandée — instantanée puisque Strava se souvient de l'autorisation.

---

## Déploiement en production

Pour exposer l'app publiquement avec HTTPS, un service Caddy en frontal est fourni.

### 1. Préparer le DNS et les variables

- Pointer ton domaine (`running.exemple.com`) vers l'IP de ton serveur.
- Ouvrir les ports `80` et `443` sur le firewall.
- Compléter `.env` avec :

```dotenv
PUBLIC_DOMAIN=running.exemple.com
ACME_EMAIL=admin@exemple.com
STRAVA_REDIRECT_URI=https://running.exemple.com/
```

- Mettre à jour l'**Authorization Callback Domain** côté Strava sur `running.exemple.com`.

### 2. Démarrer la stack prod

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Caddy obtient automatiquement un certificat Let's Encrypt au premier démarrage. Le port `8501` n'est plus exposé : tout passe par HTTPS via Caddy.

### 3. Mettre à jour le code

```bash
git pull
docker compose -f docker-compose.prod.yml build app
docker compose -f docker-compose.prod.yml up -d
```

L'image prod n'utilise pas de bind mount — un rebuild est nécessaire pour propager les changements.

### Sécurité incluse

- **HTTPS auto** via Let's Encrypt (renouvellement géré par Caddy).
- **Headers** : HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, CSP `frame-ancestors 'none'`.
- **Healthcheck actif** : si Streamlit crashe, Caddy renvoie 502 immédiatement au lieu de proxifier dans le vide.
- **XSRF + CORS** activés côté Streamlit.
- **Token OAuth jamais persisté sur disque** — il vit uniquement dans la session navigateur.

---

## Utilisation des pages

### 🏠 Accueil (`/`)

- Métriques clés : km cette semaine, km ce mois, nombre de sorties, allure moyenne, FC moyenne
- Estimations de performance : temps prédits sur 5 km, 10 km, semi et marathon via la formule de Riegel, calculés sur vos meilleures sorties récentes
- Dernière activité : carte du tracé GPS, splits kilomètre par kilomètre avec code couleur, 8 métriques clés

### 📋 Activités (`/Activities`)

Liste complète de vos sorties avec filtres (type, dates, distance, recherche par nom). Cliquez sur une ligne pour les détails :

- Métriques (distance, durée, allure, FC, cadence, D+, calories, FC max)
- Carte GPS du tracé
- Streams haute-résolution Garmin-style : altitude avec pente, allure lissée, FC avec bandes de zones
- Tableau des splits avec toutes les métriques par kilomètre

### 📊 Statistiques (`/Stats`)

Six onglets d'analyse :

- **📦 Volume** — histogrammes hebdomadaires et mensuels, distribution des distances
- **🐇 Allure** — évolution temporelle avec tendance, splits km par km moyennés
- **❤️ Fréquence cardiaque** — évolution FC, zones Z1-Z5, corrélation FC/allure
- **🦶 Cadence** — évolution avec zone optimale (170-180 spm), distribution
- **📅 Régularité** — calendrier heatmap des sorties, streaks, jours de repos
- **⚡ Charge d'entraînement** — CTL (forme chronique 42 j), ATL (fatigue aiguë 7 j), TSB (fraîcheur), graphique historique

### 🤖 IA Coach (`/AI_Coach`)

Génère un prompt complet (system prompt + contexte d'entraînement + demande d'analyse) prêt à être collé dans **Claude**, **ChatGPT**, **Gemini** ou n'importe quel autre LLM. L'application **ne fait aucun appel à un LLM elle-même** : vos données restent sur votre machine, et vous gardez la main sur le LLM utilisé.

Réglez le nombre de sorties incluses dans la barre latérale (5 à 50), copiez le prompt, collez-le où vous voulez.

### 🔥 Heatmap (`/Heatmap`)

Cartes de chaleur multi-calques calculées à partir des streams GPS haute résolution :

- **Fréquence (linéaire / log)** — orange Strava, intensité = nombre de passages par pixel
- **Allure moyenne** — bleu, brillant = rapide
- **FC moyenne** — rouge, brillant = haut
- **Pente absolue** — blanc, brillant = raide
- **Dénivelé signé** — vert (descente) / violet (montée)

Pipeline interne : récupération des streams `latlng`/`velocity_smooth`/`heartrate`/`altitude`, rasterisation
en projection Web Mercator, flou gaussien, normalisation par percentiles, encodage PNG et superposition
sur fond CartoDB DarkMatter via Folium. La logique pure (rasterize / blur / normalize / colormaps) vit
dans `app/heatmap_logic.py` et est couverte par les tests.

La sidebar permet d'ajuster la période, le type d'activité, le rayon autour de la maison (auto-détectée
sur la cellule de départ la plus dense), la résolution et le rayon de clipping des tracks.

Inspiré du notebook [moresamwilson/running-heatmap](https://github.com/moresamwilson/running-heatmap).

### 🗺️ Prochaine sortie (`/Next_Session`)

Recommandation de séance et parcours inédit basés sur votre forme actuelle :

1. **Recommandation** : calcul CTL/ATL/TSB → sélection du type de séance (récupération, endurance, tempo ou sortie longue)
2. **Objectifs** : distance cible, allure cible avec fourchette ±4%, dénivelé, durée estimée
3. **Parcours en boucle** : généré via OpenRouteService autour d'un de vos points de départ habituels
4. **Carte interactive** + **profil altimétrique**
5. **Export GPX** compatible Garmin Connect

> Nécessite une clé API OpenRouteService (gratuite, inscription sur [openrouteservice.org](https://openrouteservice.org/dev/#/signup)). La clé peut être globale via `ORS_API_KEY` dans `.env`, ou saisie par chaque utilisateur dans la sidebar.

---

## Commandes utiles

```bash
# ── Dev ──────────────────────────────────────────────────────────────
docker compose up -d                # démarrer
docker compose down                 # arrêter
docker compose logs -f              # logs temps réel
docker compose build app            # reconstruire après changement Dockerfile
docker compose exec app rm -rf /app/.cache   # vider tout le cache disque

# ── Prod ─────────────────────────────────────────────────────────────
docker compose -f docker-compose.prod.yml up -d --build   # déployer
docker compose -f docker-compose.prod.yml logs -f caddy   # logs Caddy
docker compose -f docker-compose.prod.yml logs -f app     # logs app
docker compose -f docker-compose.prod.yml restart app     # redémarrer l'app

# ── Backup des certificats Let's Encrypt (prod) ──────────────────────
docker run --rm -v running_caddy_data:/data -v $(pwd):/backup alpine \
    tar czf /backup/caddy-certs.tgz /data
```

Pour se déconnecter d'un compte Strava : utiliser le bouton **« Déconnexion »** dans la barre latérale (le token n'est nulle part sur disque).

---

## Configuration avancée

### Variables d'environnement

| Variable | Défaut | Description |
|---|---|---|
| `STRAVA_CLIENT_ID` | — | Client ID de l'application Strava |
| `STRAVA_CLIENT_SECRET` | — | Client Secret de l'application Strava |
| `STRAVA_REDIRECT_URI` | `http://localhost:8501` | URL de redirection OAuth — doit matcher l'Authorization Callback Domain Strava |
| `CACHE_TTL` | `3600` | Durée du cache disque en secondes |
| `ORS_API_KEY` | — | Clé API OpenRouteService (page Prochaine sortie) |
| `PUBLIC_DOMAIN` | — | *(prod uniquement)* Domaine servi par Caddy |
| `ACME_EMAIL` | — | *(prod uniquement)* Email pour les notifications Let's Encrypt |

---

## Structure du projet

```
run/
├── docker-compose.yml          # Stack dev (Streamlit avec hot-reload)
├── docker-compose.prod.yml     # Stack prod (Caddy + Streamlit, image figée)
├── Caddyfile                   # Reverse-proxy HTTPS + headers de sécurité
├── .env.example                # Template de configuration
├── pytest.ini                  # Configuration des tests (pythonpath = app)
├── README.md                   # Ce fichier
├── CLAUDE.md                   # Instructions projet pour assistants IA
├── tests/
│   ├── conftest.py             # Fixtures pytest et stubs Streamlit/Plotly
│   ├── test_strava_client.py   # Client Strava, cache, OAuth refresh
│   ├── test_next_session.py    # Logique TSB / recommandation / GPX
│   └── test_heatmap_logic.py   # Haversine, detect_home, rasterize, normalize
└── app/
    ├── Dockerfile              # Image Docker (Python 3.12-slim, user non-root)
    ├── docker-entrypoint.sh    # Init du dossier .cache au démarrage
    ├── requirements.txt        # Dépendances Python
    ├── main.py                 # Page d'accueil + flux OAuth Strava
    ├── strava_client.py        # Client API Strava + cache + transformations
    ├── next_session_logic.py   # Logique pure : TSB, recommandation, GPX
    ├── heatmap_logic.py        # Logique pure : rasterize, blur, normalize, cmaps
    ├── ui_helpers.py           # require_token(), get_strava_client(), carte
    ├── stats_tabs/             # 6 onglets de la page Statistiques
    ├── .streamlit/config.toml  # XSRF/CORS, headless server
    └── pages/
        ├── 1_Activities.py     # Liste et détails des activités
        ├── 2_Stats.py          # Graphiques statistiques
        ├── 3_AI_Coach.py       # Prompts LLM prêts à copier
        ├── 4_Next_Session.py   # Recommandation + parcours ORS
        └── 5_Heatmap.py        # Heatmaps multi-calques (Folium)
```

---

## Tests

```bash
# Lancer la suite (223 tests)
python3 -m pytest tests/ -v

# Avec couverture (nécessite pytest-cov)
python3 -m pytest tests/ --cov=app --cov-report=term-missing
```

Les tests couvrent les fonctions pures sans dépendance à Streamlit ou à l'API Strava :

- `strava_client.py` — utilitaires (allure, calories, cadence, normalisation), méthodes DataFrame, cache disque cloisonné par athlète, refresh OAuth, retry sur 5xx, traduction d'erreurs HTTP
- `next_session_logic.py` — calcul TSB, recommandation de séance, parsing ORS, génération GPX
- `heatmap_logic.py` — haversine, détection de la maison, rasterisation, normalisation, génération des PNG

---

## Dépannage

**L'application ne démarre pas**
```bash
docker compose logs app
# Vérifiez que le fichier .env est bien rempli
```

**Erreur de connexion Strava**
- Vérifiez `STRAVA_CLIENT_ID` et `STRAVA_CLIENT_SECRET` dans `.env`
- Assurez-vous que l'**Authorization Callback Domain** correspond au domaine de `STRAVA_REDIRECT_URI` (ex. `localhost` pour le dev, `running.exemple.com` pour la prod)
- Cliquez sur "🔄 Reconnecter à Strava" dans le tableau de bord

**Pas de données affichées**
- Cliquez sur "🔄 Actualiser les données" dans la barre latérale
- Vérifiez que vous avez des activités sur Strava

**La page Prochaine sortie ne génère pas de parcours**
- Vérifiez que `ORS_API_KEY` est définie dans `.env` ou saisie dans la barre latérale
- Le profil utilisé est `foot-walking` (compatible running) ou `foot-hiking` pour les sentiers

**Prod : Caddy ne récupère pas de certificat**
- Vérifiez que les ports 80 et 443 sont ouverts et atteignables depuis Internet
- Vérifiez que le DNS pointe bien sur le serveur (`dig +short ${PUBLIC_DOMAIN}`)
- Logs Caddy : `docker compose -f docker-compose.prod.yml logs caddy`

---

## Architecture et fonctionnement

### Vue d'ensemble

```
                  ┌─── dev ─────┐         ┌─── prod ────────────┐
                  │             │         │                     │
   Navigateur ──→ │  Streamlit  │   ou    │  Caddy (HTTPS) ──→  │ ──→ Streamlit
                  │   :8501     │         │   :443              │      :8501
                  └─────────────┘         └─────────────────────┘
                         │
                         ▼
                  API Strava (REST)
                  API OpenRouteService (REST)
```

L'app est **stateless** : aucune base de données. Les seules données persistées sur disque sont le cache des appels API Strava (`app/.cache/{athlete_id}/`), purgeable à tout moment.

### Multi-user

- **Token OAuth** : vit dans `st.session_state` côté navigateur. Per-session, jamais sur disque. Rafraîchi automatiquement par un callback dans la session.
- **Cache disque** cloisonné par athlète : chaque utilisateur a son sous-dossier `app/.cache/{athlete_id}/`.
- **Cache mémoire Streamlit** (`@st.cache_data`) : isolé par `athlete_id` via les arguments de fonction.
- **Pas de singleton `StravaClient`** : un client est construit per-session depuis le token courant.

### Cache à deux niveaux

```
Requête données
      │
      ▼
@st.cache_data (RAM, isolé par athlete_id, TTL 1h)
      │ miss
      ▼
_cache_get(athlete_id, key) (fichier JSON sur disque, TTL 1h)
      │ miss
      ▼
API Strava (réseau, 1 retry sur 5xx)
      │
      ▼
_cache_set(athlete_id, key) → disque → retour → RAM Streamlit
```

### Séparation des responsabilités

| Couche | Fichier(s) | Rôle |
|---|---|---|
| Données | `strava_client.py` | Fetch API, cache disque, OAuth, transformations DataFrame |
| Logique métier | `next_session_logic.py` | Calculs purs (TSB, recommandation, GPX), testables sans Streamlit |
| UI helpers | `ui_helpers.py` | `require_token()`, `get_strava_client()`, rendu carte commun |
| UI | `main.py` + `pages/` + `stats_tabs/` | Affichage uniquement, pas de logique métier |

### Calcul de la charge d'entraînement (CTL/ATL/TSB)

Le TSS (Training Stress Score) de chaque sortie est calculé ainsi :
```
IF  = allure_seuil / allure_moyenne   (clampé à 1.5)
TSS = durée_heures × IF² × 100
```

CTL et ATL sont des moyennes exponentielles (EWMA) avec des constantes de temps de 42 et 7 jours respectivement. **TSB = CTL − ATL**.

---

## Licence

Projet personnel à usage privé. Utilise des bibliothèques open-source :
[Strava API](https://developers.strava.com),
[Streamlit](https://streamlit.io),
[OpenRouteService](https://openrouteservice.org),
[Plotly](https://plotly.com),
[Caddy](https://caddyserver.com).
