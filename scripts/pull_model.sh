#!/usr/bin/env bash
# ============================================================
# pull_model.sh — Télécharge le modèle Ollama configuré
# Usage : ./scripts/pull_model.sh [nom_du_modele]
# Exemple : ./scripts/pull_model.sh mistral
# ============================================================

set -euo pipefail

# Répertoire racine du projet (parent du répertoire scripts/)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Charger les variables d'environnement si .env existe
if [ -f ".env" ]; then
    # shellcheck disable=SC1091
    set -o allexport
    source .env
    set +o allexport
fi

# Modèle à utiliser (argument CLI > variable d'env > défaut)
MODEL="${1:-${OLLAMA_MODEL:-llama3.2}}"

echo "=================================================="
echo "  🤖 Téléchargement du modèle Ollama : $MODEL"
echo "=================================================="
echo ""

# Vérifier que Docker est disponible
if ! command -v docker &> /dev/null; then
    echo "❌ Docker n'est pas installé ou n'est pas dans le PATH."
    exit 1
fi

# Vérifier que le conteneur ollama tourne
if ! docker compose ps ollama 2>/dev/null | grep -q "running"; then
    echo "⚠️  Le conteneur Ollama ne semble pas démarré. Tentative de démarrage..."
    docker compose up -d ollama
    echo "⏳ Attente du démarrage d'Ollama (15 secondes)..."
    sleep 15
fi

echo "📥 Téléchargement de $MODEL..."
echo ""

docker compose exec ollama ollama pull "$MODEL"

echo ""
echo "✅ Modèle $MODEL téléchargé avec succès !"
echo ""
echo "Modèles disponibles sur ce serveur Ollama :"
docker compose exec ollama ollama list
echo ""
echo "Vous pouvez maintenant utiliser l'IA Coach sur http://localhost:8501"
