"""
Client LLM — interaction avec Ollama pour l'analyse de course à pied.
Supporte le streaming des réponses et les questions personnalisées.
"""

import json
import os
import logging
from typing import Generator, Optional

import pandas as pd
import requests

from strava_client import _seconds_to_pace_str

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

# Prompt système : le LLM joue le rôle d'un coach running expert
SYSTEM_PROMPT = """Tu es un coach running expert et bienveillant avec plus de 20 ans d'expérience.
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
Tes réponses sont structurées avec des titres clairs et des listes à puces quand c'est pertinent."""


class OllamaClient:
    """
    Client pour interagir avec Ollama via son API HTTP.
    Supporte le streaming et la gestion d'erreurs gracieuse.
    """

    def __init__(
        self,
        host: str = OLLAMA_HOST,
        model: str = OLLAMA_MODEL,
        timeout: int = 120,
    ):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._api_chat = f"{self.host}/api/chat"
        self._api_tags = f"{self.host}/api/tags"
        self._api_pull = f"{self.host}/api/pull"

    # ------------------------------------------------------------------
    # Vérifications
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Vérifie que le serveur Ollama est accessible."""
        try:
            response = requests.get(f"{self.host}/", timeout=5)
            return response.status_code == 200
        except requests.exceptions.ConnectionError:
            return False
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """Retourne la liste des modèles disponibles sur ce serveur Ollama."""
        try:
            response = requests.get(self._api_tags, timeout=10)
            response.raise_for_status()
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.warning("Impossible de lister les modèles : %s", e)
            return []

    def model_is_available(self) -> bool:
        """Vérifie que le modèle configuré est téléchargé."""
        models = self.list_models()
        # Comparaison souple : llama3.2 == llama3.2:latest
        model_base = self.model.split(":")[0]
        for m in models:
            if m.split(":")[0] == model_base:
                return True
        return False

    # ------------------------------------------------------------------
    # Génération de réponses
    # ------------------------------------------------------------------

    def analyze_training(
        self,
        activities_summary: str,
        stream: bool = True,
    ) -> Generator[str, None, None]:
        """
        Envoie un résumé des activités récentes au LLM et génère une analyse.

        Args:
            activities_summary: Résumé textuel des activités récentes
            stream: Si True, génère les tokens au fur et à mesure

        Yields:
            Tokens de texte de la réponse du modèle
        """
        user_message = f"""Voici le résumé de mes activités de course récentes :

{activities_summary}

Merci d'analyser ces données et de me donner :
1. Une évaluation de ma charge d'entraînement actuelle
2. Les points forts observés
3. Les points d'amélioration
4. Des recommandations concrètes pour la prochaine semaine
5. Une note de motivation personnalisée"""

        yield from self._chat(user_message, stream=stream)

    def ask_custom_question(
        self,
        question: str,
        activities_summary: str,
        stream: bool = True,
    ) -> Generator[str, None, None]:
        """
        Répond à une question personnalisée du coureur sur son entraînement.

        Args:
            question: La question posée par l'utilisateur
            activities_summary: Contexte des activités récentes
            stream: Si True, génère les tokens au fur et à mesure

        Yields:
            Tokens de texte de la réponse du modèle
        """
        user_message = f"""Contexte de mes activités récentes :

{activities_summary}

Ma question : {question}"""

        yield from self._chat(user_message, stream=stream)

    def _chat(
        self,
        user_message: str,
        system_prompt: str = SYSTEM_PROMPT,
        stream: bool = True,
    ) -> Generator[str, None, None]:
        """
        Appel bas niveau à l'API /api/chat d'Ollama.

        Args:
            user_message: Message de l'utilisateur
            system_prompt: Prompt système définissant le comportement du modèle
            stream: Activer le streaming

        Yields:
            Tokens de texte générés par le modèle
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": stream,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
                "num_predict": 2048,
            },
        }

        try:
            with requests.post(
                self._api_chat,
                json=payload,
                stream=stream,
                timeout=self.timeout,
            ) as response:
                response.raise_for_status()

                if stream:
                    for line in response.iter_lines():
                        if line:
                            try:
                                chunk = json.loads(line.decode("utf-8"))
                                content = chunk.get("message", {}).get("content", "")
                                if content:
                                    yield content
                                if chunk.get("done", False):
                                    break
                            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                                logger.warning("Erreur décodage chunk : %s", e)
                                continue
                else:
                    data = response.json()
                    yield data.get("message", {}).get("content", "")

        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(
                f"Impossible de contacter Ollama à {self.host}.\n"
                "Vérifiez que le conteneur Ollama est bien démarré."
            ) from e
        except requests.exceptions.Timeout as e:
            raise TimeoutError(
                f"Ollama n'a pas répondu dans les {self.timeout}s impartis."
            ) from e
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                raise ValueError(
                    f"Modèle '{self.model}' non trouvé sur Ollama.\n"
                    "Lancez : docker compose exec ollama ollama pull "
                    + self.model
                ) from e
            raise RuntimeError(f"Erreur HTTP Ollama : {e}") from e

    # ------------------------------------------------------------------
    # Formatage du contexte
    # ------------------------------------------------------------------

    @staticmethod
    def format_activities_summary(df, n: int = 10) -> str:
        """
        Formate les N dernières activités de course en texte structuré
        pour le contexte du LLM.

        Args:
            df: DataFrame des activités (depuis StravaClient.get_activities)
            n: Nombre d'activités à inclure dans le résumé

        Returns:
            Résumé textuel formaté
        """
        if df is None or df.empty:
            return "Aucune activité disponible."

        # Filtrer les courses uniquement
        running = df[df["activityType"] == "running"].copy()
        if running.empty:
            return "Aucune activité de course disponible."

        running = running.sort_values("startTimeLocal", ascending=False).head(n)

        lines = [f"=== {len(running)} dernières sorties course ===\n"]

        for _, row in running.iterrows():
            date_str = pd.to_datetime(row["startTimeLocal"]).strftime("%d/%m/%Y")
            name = row.get("activityName", "Course") or "Course"
            dist = row.get("distance_km", 0)
            dur = row.get("duration_min", 0)
            pace = row.get("avgPace", "—")
            hr = row.get("avgHR")
            cadence = row.get("avgCadence")
            elev = row.get("elevationGain")
            calories = row.get("calories")

            hr_str = f"{int(hr)} bpm" if hr and not pd.isna(hr) else "N/A"
            cad_str = f"{int(cadence)} spm" if cadence and not pd.isna(cadence) else "N/A"
            elev_str = f"{int(elev)} m D+" if elev and not pd.isna(elev) else "N/A"
            cal_str = f"{int(calories)} kcal" if calories and not pd.isna(calories) else "N/A"

            lines.append(
                f"- {date_str} | {name}\n"
                f"  Distance : {dist:.1f} km | Durée : {dur:.0f} min | "
                f"Allure : {pace}\n"
                f"  FC moy : {hr_str} | Cadence : {cad_str} | "
                f"D+ : {elev_str} | Calories : {cal_str}"
            )

        # Statistiques globales
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
