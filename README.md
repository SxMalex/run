# 🏃 Running Dashboard

Tableau de bord personnel pour l'analyse de vos données de course à pied.
Se connecte à **Strava** via son API officielle, génère des **parcours inédits** via OpenRouteService,
et offre des conseils personnalisés grâce à une **IA locale** (Ollama) — **100% gratuit, 100% local**.

---

## Fonctionnalités

- **Accueil** — métriques clés semaine/mois, dernière activité détaillée (carte + splits), estimations de performance Riegel
- **Activités** — liste filtrée par date, type et distance ; détail complet avec graphique des splits
- **Statistiques** — 6 onglets : volume, allure, FC, cadence, régularité, charge d'entraînement (CTL/ATL/TSB)
- **IA Coach** — analyse personnalisée en streaming, questions libres à votre coach IA local
- **Prochaine sortie** — recommandation de séance basée sur la forme actuelle + parcours en boucle généré sur OpenStreetMap + export GPX pour Garmin

---

## Prérequis

| Outil | Version minimale | Vérification |
|---|---|---|
| [Docker](https://docs.docker.com/get-docker/) | 24.x | `docker --version` |
| [Docker Compose](https://docs.docker.com/compose/install/) | v2.x | `docker compose version` |
| Compte Strava | — | [strava.com](https://www.strava.com) |
| Clé API OpenRouteService | — | [openrouteservice.org](https://openrouteservice.org/dev/#/signup) *(gratuit, optionnel)* |

> **Note :** Ollama est inclus dans Docker Compose, aucune installation supplémentaire n'est nécessaire.

---

## Installation et démarrage

### 1. Cloner ou télécharger le projet

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
OLLAMA_HOST=http://ollama:11434
OLLAMA_MODEL=llama3.2
CACHE_TTL=3600

# Optionnel — améliore le calcul des calories (défaut : 70 kg)
ATHLETE_WEIGHT_KG=70

# Optionnel — nécessaire uniquement pour la page Prochaine sortie
ORS_API_KEY=votre_cle_ors
```

> ⚠️ **Sécurité :** le fichier `.env` ne doit jamais être versionné (il est dans `.gitignore`).

### 4. Démarrer les conteneurs

```bash
docker compose up -d
```

Cela démarre :
- **app** — le tableau de bord Streamlit sur le port `8501`
- **ollama** — le serveur de modèles LLM sur le port `11434`

### 5. Connecter votre compte Strava

Ouvrez **[http://localhost:8501](http://localhost:8501)** dans votre navigateur.

La page de connexion s'affiche automatiquement si vous n'êtes pas encore authentifié.
Cliquez sur **"🔗 Connecter à Strava"**, autorisez l'application, et vous serez redirigé
vers le tableau de bord.

Cette étape n'est à faire **qu'une seule fois** — le token est sauvegardé et se rafraîchit automatiquement.

### 6. Télécharger le modèle IA (première fois)

Le modèle LLM doit être téléchargé une seule fois (environ 2 Go pour `llama3.2`) :

```bash
./scripts/pull_model.sh
```

---

## Utilisation des pages

### 🏠 Accueil (`/`)

- **Métriques clés** : km cette semaine, km ce mois, nombre de sorties, allure moyenne, FC moyenne
- **Estimations de performance** : temps prédits sur 5km, 10km, semi-marathon et marathon via la formule de Riegel, calculés sur vos meilleures sorties récentes
- **Dernière activité** : carte du tracé GPS, splits kilomètre par kilomètre avec code couleur, 8 métriques clés

---

### 📋 Activités (`/Activities`)

Liste complète de vos sorties avec des **filtres** :

- **Type d'activité** : course, vélo, natation, marche, etc.
- **Plage de dates** : du/au (sélecteurs calendrier)
- **Distance** : curseur de filtre min/max
- **Recherche par nom** : texte libre

**Cliquez sur une ligne** pour afficher les détails complets :
- Métriques (distance, durée, allure, FC, cadence, D+, calories, FC max)
- **Graphique des splits** kilomètre par kilomètre avec code couleur (vert = plus rapide que la moyenne)
- Tableau des splits avec toutes les métriques par kilomètre

---

### 📊 Statistiques (`/Stats`)

Six onglets d'analyse :

**📦 Volume** — histogrammes hebdomadaires et mensuels, distribution des distances

**🐇 Allure** — évolution temporelle avec tendance, allure par tranche de distance

**❤️ Fréquence cardiaque** — évolution FC, zones Z1-Z5, corrélation FC/allure

**🦶 Cadence** — évolution avec zone optimale (170-180 spm), distribution

**📅 Régularité** — calendrier heatmap des sorties, streaks, jours de repos

**⚡ Charge d'entraînement** — CTL (forme chronique 42j), ATL (fatigue aiguë 7j), TSB (fraîcheur), graphique historique de la forme

---

### 🤖 IA Coach (`/AI_Coach`)

1. Cliquez sur **"🤖 Analyser mon entraînement"** — l'IA génère une analyse en streaming
2. Utilisez les **boutons de suggestions** ou posez votre propre question
3. Choisissez le modèle LLM et le nombre de sorties analysées dans la barre latérale

> 💡 **Confidentialité :** toutes les données restent sur votre machine. Aucune donnée n'est envoyée à un service externe.

---

### 🗺️ Prochaine sortie (`/Next_Session`)

Génère une recommandation de séance et un parcours inédit basés sur votre forme actuelle :

1. **Recommandation automatique** : calcul CTL/ATL/TSB → sélection du type de séance (récupération, endurance, tempo ou sortie longue)
2. **Objectifs** : distance cible, allure cible avec fourchette ±4%, dénivelé, durée estimée
3. **Parcours en boucle** : généré via OpenRouteService autour d'un de vos points de départ habituels
4. **Carte interactive** et **profil altimétrique**
5. **Export GPX** compatible Garmin Connect

> Nécessite une clé API OpenRouteService (gratuite, inscription sur [openrouteservice.org](https://openrouteservice.org/dev/#/signup)).

---

## Commandes utiles

```bash
# Démarrer tous les services
docker compose up -d

# Arrêter tous les services
docker compose down

# Voir les logs en temps réel
docker compose logs -f

# Reconstruire l'image après modification du code
docker compose build app && docker compose up -d app

# Vider le cache des données
docker compose exec app find /app/.cache -name "*.json" -not -name "strava_token.json" -delete

# Se déconnecter de Strava (supprime le token)
docker compose exec app rm -f /app/.cache/strava_token.json

# Lister les modèles Ollama disponibles
docker compose exec ollama ollama list

# Télécharger un autre modèle
./scripts/pull_model.sh mistral
```

---

## Configuration avancée

### Variables d'environnement

| Variable | Défaut | Description |
|---|---|---|
| `STRAVA_CLIENT_ID` | — | Client ID de l'application Strava |
| `STRAVA_CLIENT_SECRET` | — | Client Secret de l'application Strava |
| `STRAVA_REDIRECT_URI` | `http://localhost:8501` | URL de redirection OAuth |
| `OLLAMA_HOST` | `http://ollama:11434` | URL du serveur Ollama |
| `OLLAMA_MODEL` | `llama3.2` | Modèle LLM à utiliser |
| `CACHE_TTL` | `3600` | Durée du cache en secondes |
| `ATHLETE_WEIGHT_KG` | `70` | Poids de l'athlète pour le calcul des calories |
| `ORS_API_KEY` | — | Clé API OpenRouteService (page Prochaine sortie) |

### Modèles Ollama recommandés

| Modèle | RAM nécessaire | Qualité | Vitesse |
|---|---|---|---|
| `llama3.2:1b` | ~1 Go | ★★☆ | ★★★ |
| `llama3.2` | ~2 Go | ★★★ | ★★☆ |
| `mistral` | ~4 Go | ★★★ | ★★☆ |
| `llama3.1:8b` | ~5 Go | ★★★ | ★☆☆ |

### Utiliser un GPU

Pour accélérer Ollama avec un GPU NVIDIA, ajoutez dans `docker-compose.yml` :

```yaml
ollama:
  image: ollama/ollama
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

---

## Structure du projet

```
run/
├── docker-compose.yml          # Orchestration Docker
├── .env.example                # Template de configuration
├── pytest.ini                  # Configuration des tests (pythonpath = app)
├── README.md                   # Ce fichier
├── scripts/
│   ├── strava_auth.py          # Authentification OAuth (alternative CLI)
│   └── pull_model.sh           # Téléchargement du modèle Ollama
├── tests/
│   ├── conftest.py             # Fixtures et stubs partagés
│   ├── test_strava_client.py   # Tests des fonctions utilitaires Strava
│   └── test_next_session.py    # Tests de la logique de recommandation
└── app/
    ├── Dockerfile              # Image Docker de l'application
    ├── requirements.txt        # Dépendances Python
    ├── main.py                 # Page d'accueil Streamlit
    ├── strava_client.py        # Client API Strava + cache + transformations
    ├── llm_client.py           # Client Ollama (IA Coach)
    ├── next_session_logic.py   # Logique métier pure : TSB, recommandation, GPX
    └── pages/
        ├── 1_Activities.py     # Liste et détails des activités
        ├── 2_Stats.py          # Graphiques statistiques (6 onglets)
        ├── 3_AI_Coach.py       # Coach IA avec streaming
        └── 4_Next_Session.py   # Prochaine sortie + parcours ORS
```

---

## Tests

```bash
# Lancer la suite de tests (94 tests)
pytest

# Avec couverture de code
pytest --cov=app --cov-report=term-missing
```

Les tests couvrent les fonctions pures sans dépendance à Streamlit :
- `strava_client.py` — utilitaires (allure, calories, cadence, normalisation) et méthodes DataFrame
- `next_session_logic.py` — calcul TSB, recommandation de séance, parsing ORS, génération GPX (**99% de couverture**)

---

## Dépannage

**L'application ne démarre pas**
```bash
docker compose logs app
# Vérifiez que le fichier .env est bien rempli
```

**Erreur de connexion Strava**
- Vérifiez `STRAVA_CLIENT_ID` et `STRAVA_CLIENT_SECRET` dans `.env`
- Assurez-vous que l'**Authorization Callback Domain** est bien `localhost` dans les paramètres de votre app Strava
- Cliquez sur "🔄 Reconnecter à Strava" dans le tableau de bord

**L'IA ne répond pas**
```bash
docker compose logs ollama
# Vérifiez que le modèle est téléchargé
docker compose exec ollama ollama list
```

**Pas de données affichées**
- Cliquez sur "🔄 Actualiser les données" dans la barre latérale
- Vérifiez que vous avez des activités sur Strava

**La page Prochaine sortie ne génère pas de parcours**
- Vérifiez que `ORS_API_KEY` est définie dans `.env` ou saisie dans la barre latérale
- Le profil utilisé est `foot-walking` (compatible running)

---

## Architecture et fonctionnement

### Vue d'ensemble

Le projet est une application **mono-utilisateur 100% locale** : aucune donnée ne quitte votre machine (hormis les appels API Strava et ORS). Deux services tournent en parallèle via Docker Compose.

```
Navigateur
    │
    ▼
[Streamlit :8501]  ←→  [API Strava]
    │                  [API ORS]
    ▼
[Ollama :11434]  (LLM local)
```

---

### Technologies

**Interface — Streamlit**

Streamlit transforme du code Python en application web sans HTML/JS. Chaque interaction déclenche une réexécution complète du script (modèle stateless). Le projet l'utilise en **multi-pages** : chaque fichier dans `pages/` devient automatiquement un onglet de navigation.

**Données — Pandas + Plotly**

- **Pandas** gère toutes les données sous forme de `DataFrame`. Toutes les agrégations (stats semaine/mois, filtres, zones FC, CTL/ATL/TSB) se font via ses opérateurs vectorisés.
- **Plotly** génère les graphiques interactifs (zoom, hover) directement depuis les DataFrames.

**API — Strava OAuth 2.0**

L'accès aux données passe par l'API REST officielle Strava avec le flux OAuth 2.0 :
- **Access token** : valide 6h, utilisé dans chaque requête HTTP
- **Refresh token** : permanent, permet de regénérer un access token automatiquement
- Les tokens sont stockés dans un fichier JSON sur le volume Docker (`/app/.cache/strava_token.json`)

**Parcours — OpenRouteService**

L'API ORS génère des boucles de course en `foot-walking` autour d'un point GPS de départ, avec dénivelé réel via MNT. Chaque variante est reproductible via un paramètre `seed`.

**IA — Ollama**

Ollama est un serveur local qui fait tourner des LLMs (llama3.2, mistral...). Le projet lui envoie des requêtes HTTP en **streaming** : les tokens arrivent un par un et Streamlit les affiche au fil de l'eau.

**Infrastructure — Docker Compose**

Deux conteneurs orchestrés :
- `app` : image Python 3.12-slim avec Streamlit
- `ollama` : image officielle Ollama avec les modèles stockés dans un volume persistant

---

### Patterns utilisés

**Cache à deux niveaux**

```
Requête données
      │
      ▼
@st.cache_data (RAM, durée de session Streamlit)
      │ miss
      ▼
_cache_get() (fichier JSON sur disque, TTL 1h)
      │ miss
      ▼
API Strava (réseau)
      │
      ▼
_cache_set() → disque → retour → RAM Streamlit
```

**Séparation des responsabilités**

| Couche | Fichier(s) | Rôle |
|---|---|---|
| Données | `strava_client.py` | Fetch API, cache, transformation en DataFrame |
| Logique métier | `next_session_logic.py` | Calculs purs, testables sans Streamlit |
| IA | `llm_client.py` | Appels Ollama, streaming, formatage du contexte |
| UI | `main.py` + `pages/` | Affichage uniquement, aucune logique métier |

**Calcul de la charge d'entraînement (CTL/ATL/TSB)**

Le TSS (Training Stress Score) de chaque sortie est calculé ainsi :
```
IF = allure_seuil / allure_moyenne   (clampé à 1.5)
TSS = durée_heures × IF² × 100
```
CTL et ATL sont des moyennes exponentielles (EWMA) avec des constantes de temps de 42 et 7 jours respectivement. TSB = CTL − ATL.

---

## Licence

Projet personnel à usage privé. Utilise des bibliothèques open-source :
[Strava API](https://developers.strava.com),
[Streamlit](https://streamlit.io),
[Ollama](https://ollama.ai),
[OpenRouteService](https://openrouteservice.org),
[Plotly](https://plotly.com).
