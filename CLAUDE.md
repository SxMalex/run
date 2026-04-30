# CLAUDE.md — Running Dashboard

## Stack

- **Streamlit 1.56+** — multipage app (`app/main.py` + `app/pages/`)
- **Python 3.12**, Pandas, Plotly, NumPy
- **Docker Compose** — service `app` (Streamlit)
- **Strava API** via OAuth2 — token stocké dans `app/.cache/strava_token.json`
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
docker compose up          # démarre l'app Streamlit
docker compose restart app # recharger après un changement de config Docker
```

Streamlit recharge automatiquement les fichiers `.py` modifiés — pas besoin de redémarrer le container pour les changements de code.

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

## Règles de commit

- **Ne jamais commiter sans demande explicite** de l'utilisateur.
- **Commits conventionnels** obligatoires : `type(scope): message` en minuscules.
  - Types valides : `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `style`
  - Exemples : `fix(stats): correct slider step alignment`, `feat(next-session): add GPX export`
- **Pas de signature Claude** — ne jamais ajouter `Co-Authored-By: Claude` ni aucune mention de l'IA dans les commits.
- Message court (< 72 caractères), au présent, en anglais.

## Variables d'environnement (`.env`)

```
STRAVA_CLIENT_ID=
STRAVA_CLIENT_SECRET=
STRAVA_REDIRECT_URI=http://localhost:8501
ORS_API_KEY=           # optionnel — page Prochaine sortie
```
