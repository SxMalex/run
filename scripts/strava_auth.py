"""
Script d'authentification Strava — à exécuter une seule fois.

Usage :
    python scripts/strava_auth.py

Pré-requis :
  1. Créer une application Strava sur https://www.strava.com/settings/api
  2. Renseigner STRAVA_CLIENT_ID et STRAVA_CLIENT_SECRET dans .env
  3. Définir l'URL de callback sur "http://localhost" dans les paramètres Strava
"""

import json
import os
import sys
import webbrowser
from pathlib import Path

import requests

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"

# Lecture du CACHE_DIR depuis l'env (défaut hors Docker : répertoire courant)
CACHE_DIR = Path(os.getenv("CACHE_DIR", str(Path(__file__).parent.parent / "app" / ".cache")))
TOKEN_FILE = CACHE_DIR / "strava_token.json"


def _load_env() -> dict:
    """Charge les variables depuis .env si elles ne sont pas dans l'environnement."""
    env_vars = {}
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env_vars[key.strip()] = value.strip()
    return env_vars


def main():
    env = _load_env()
    client_id = os.getenv("STRAVA_CLIENT_ID") or env.get("STRAVA_CLIENT_ID", "")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET") or env.get("STRAVA_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        print("❌ STRAVA_CLIENT_ID et STRAVA_CLIENT_SECRET sont requis dans .env")
        print()
        print("   1. Rendez-vous sur https://www.strava.com/settings/api")
        print('   2. Créez une application (Website URL : "http://localhost")')
        print("   3. Copiez Client ID et Client Secret dans .env")
        sys.exit(1)

    auth_url = (
        f"{STRAVA_AUTH_URL}"
        f"?client_id={client_id}"
        f"&redirect_uri=http://localhost"
        f"&response_type=code"
        f"&approval_prompt=auto"
        f"&scope=activity:read_all"
    )

    print()
    print("=== Authentification Strava ===")
    print()
    print("1. Ouvrez cette URL dans votre navigateur :")
    print(f"\n   {auth_url}\n")
    print("2. Autorisez l'application.")
    print("3. Vous serez redirigé vers localhost (page d'erreur normale).")
    print("4. Copiez le paramètre 'code' depuis l'URL :")
    print("   http://localhost/?state=&code=XXXXXXXXXXXXXXX&scope=...")
    print()

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    code = input("Collez le code ici : ").strip()
    if not code:
        print("❌ Code vide, abandon.")
        sys.exit(1)

    print()
    print("Échange du code contre les tokens...")

    resp = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )

    if resp.status_code != 200:
        print(f"❌ Erreur {resp.status_code} : {resp.text}")
        sys.exit(1)

    token_data = resp.json()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2)

    athlete = token_data.get("athlete", {})
    print(f"✅ Tokens sauvegardés dans {TOKEN_FILE}")
    print(f"   Athlète : {athlete.get('firstname', '')} {athlete.get('lastname', '')}")
    print()
    print("Vous pouvez maintenant démarrer l'application :")
    print("   docker compose up")


if __name__ == "__main__":
    main()
