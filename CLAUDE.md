# CLAUDE.md — Running Dashboard

## Stack

- **Streamlit 1.56+** — multipage app (`app/main.py` + `app/pages/`)
- **Python 3.12**, Pandas, Plotly, NumPy
- **Docker Compose** — service `app` (Streamlit), service `caddy` (reverse-proxy HTTPS) en prod
- **Strava API** via OAuth2 — token vit dans `st.session_state` (per-user, jamais sur disque)
- **OpenRouteService API** — génération de parcours GPX (page 4)

## Structure

```
app/
  main.py                  # page d'accueil + OAuth Strava
  pages/
    1_Activities.py        # liste et détails des activités
    2_Stats.py             # graphiques volume / allure / FC / cadence / charge
    3_AI_Coach.py          # génération de prompts LLM prêts à copier
    4_Next_Session.py      # recommandation de séance + parcours ORS
  strava_client.py         # client Strava + helpers DataFrame
  next_session_logic.py    # logique pure testable (TSB, recommandation, GPX)
tests/
  conftest.py              # fixtures pytest
  test_strava_client.py
  test_next_session.py
```

## Lancer le projet

```bash
docker compose up          # dev local — Streamlit sur :8501
docker compose restart app # recharger après un changement de config Docker
```

Streamlit recharge automatiquement les fichiers `.py` modifiés — pas besoin de redémarrer le container pour les changements de code.

### Production multi-user

```bash
docker compose -f docker-compose.prod.yml up -d
```

Caddy frontalise Streamlit en HTTPS (Let's Encrypt auto). Variables `.env` requises : `PUBLIC_DOMAIN`, `ACME_EMAIL`, `STRAVA_REDIRECT_URI=https://${PUBLIC_DOMAIN}/`. Le port `:8501` n'est pas exposé publiquement.

## Tests

```bash
python3 -m pytest tests/ -v
```

Les tests sont dans `tests/`, le `pythonpath` pytest pointe sur `app/` (cf. `pytest.ini`). Les tests ne touchent pas l'API Strava — tout est testé via des DataFrames construits en mémoire.

## Règles Streamlit

- **Ne jamais utiliser `use_container_width=`** — remplacé par `width='stretch'` (True) ou `width='content'` (False) depuis Streamlit 1.44+.
- **Cartes Plotly** : utiliser `go.Scattermap` et `layout.map` — `go.Scattermapbox` / `layout.mapbox` sont dépréciés.
- **Widgets avec `key=`** : ne pas passer `value=` en même temps que `key=`. Initialiser la valeur par défaut via `st.session_state` avant la déclaration du widget.
- **Tabs sensibles aux reruns** : utiliser `st.radio(horizontal=True, key=...)` plutôt que `st.tabs()` pour les onglets dont l'état doit survivre à un rerun déclenché par un widget (ex. `2_Stats.py`).
- **Sliders** : s'assurer que `value` et `max_value` sont alignés sur `step`. Utiliser `math.ceil(val * (1/step)) * step` pour arrondir au pas supérieur.

## Règles Docker

- Le dossier `app/.cache/` est monté via bind mount (`./app:/app`), pas via volume nommé.
- Si `app/.cache/` est owned `root` sur le host, corriger avec :
  ```bash
  docker exec -u root run-app-1 chown -R appuser:appuser /app/.cache
  ```

## Logique métier (ne pas casser)

- **TSB / CTL / ATL** dans `next_session_logic.py` — fonctions pures, couvertes par tests.
- **`_seconds_to_pace_str`** dans `strava_client.py` — gère `NaN`, `None`, négatifs et numpy floats.
- **Cadence course** : Strava envoie des RPM (tours/min), à doubler pour obtenir des SPM (foulées/min).
- **Calories** : priorité à la valeur API Strava, estimation par formule si zéro ou absente.

## Multi-user (ne pas casser)

- **Token Strava** : vit en `st.session_state["strava_token"]` — per-session, jamais sur disque. `StravaClient` reçoit le token + un callback `on_token_update` qui réécrit dans la session après refresh.
- **Cache disque** cloisonné par athlète : `app/.cache/{athlete_id}/{md5}.json`. Toute donnée mise en cache transite par `_cache_get(athlete_id, key)` / `_cache_set(athlete_id, key, data)`.
- **`@st.cache_data` Streamlit** : toutes les fonctions cachées prennent un `athlete_id` en argument — c'est ce qui isole les caches inter-utilisateurs.
- **Pas de `@st.cache_resource` sur `StravaClient`** — il serait partagé entre toutes les sessions. Utiliser `ui_helpers.get_strava_client()` qui le construit depuis la session courante.
- **Pas de validation OAuth `state`** : `st.session_state` ne survit pas toujours au redirect externe vers Strava et revient (la WebSocket se reconnecte parfois en session neuve). Le `redirect_uri` étant verrouillé côté Strava, le risque CSRF résiduel est marginal pour ce dashboard en lecture seule.

## Règles de commit

- **Ne jamais commiter sans demande explicite** de l'utilisateur.
- **Ne jamais `git add` sans demande explicite** de l'utilisateur — même pour préparer un commit. Laisser à l'utilisateur le contrôle de ce qui entre dans l'index.
- **Commits conventionnels** obligatoires : `type(scope): message` en minuscules.
  - Types valides : `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `style`
  - Exemples : `fix(stats): correct slider step alignment`, `feat(next-session): add GPX export`
- **Pas de signature Claude** — ne jamais ajouter `Co-Authored-By: Claude` ni aucune mention de l'IA dans les commits.
- Message court (< 72 caractères), au présent, en anglais.

## Règles de documentation

- **Mettre à jour le `README.md`** dès qu'une modification technique ou fonctionnelle d'envergure est apportée au projet. Exemples qui déclenchent une mise à jour :
  - Ajout / suppression d'une page, d'un service Docker, d'une dépendance majeure
  - Changement du modèle d'authentification, du stockage, du cache
  - Nouvelles variables d'environnement ou changement de leur sémantique
  - Ajout d'un mode de déploiement (dev, prod, staging…)
  - Changement dans la structure de fichiers exposée à l'utilisateur
- Garder le `README.md` cohérent avec l'état réel du code — pas de section qui décrit une fonctionnalité supprimée.

## Variables d'environnement (`.env`)

```
STRAVA_CLIENT_ID=
STRAVA_CLIENT_SECRET=
STRAVA_REDIRECT_URI=http://localhost:8501   # https://${PUBLIC_DOMAIN}/ en prod
ORS_API_KEY=           # optionnel — page Prochaine sortie

# Production uniquement (docker-compose.prod.yml)
PUBLIC_DOMAIN=running.exemple.com
ACME_EMAIL=admin@exemple.com
```

`STRAVA_REDIRECT_URI` doit matcher exactement l'**Authorization Callback Domain** déclaré dans la console Strava (`strava.com/settings/api`).
