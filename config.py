"""
Configuration centralisée du bot Discord RAG.
Charge les variables d'environnement et expose les constantes.
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

# Charger le .env depuis la racine du projet
load_dotenv(Path(__file__).parent / ".env")


# ─────────────────────────────────────────────
#  Credentials
# ─────────────────────────────────────────────
DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")

# ─────────────────────────────────────────────
#  Modèles OpenRouter
# ─────────────────────────────────────────────
LLM_MODEL: str = os.getenv("LLM_MODEL", "google/gemini-3.1-flash-lite")
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "google/gemini-embedding-2-preview")
EMBEDDING_DIMENSIONS: int = int(os.getenv("EMBEDDING_DIMENSIONS", "3072"))
OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"

# ─────────────────────────────────────────────
#  Qdrant & VectorStore
# ─────────────────────────────────────────────
QDRANT_HOST: str = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION_NAME: str = os.getenv("COLLECTION_NAME", "discord_rag")

# ─────────────────────────────────────────────
#  Paramètres RAG
# ─────────────────────────────────────────────
TOP_K: int = int(os.getenv("TOP_K", "10"))
CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "50"))

CONFIG_FILE_PATH = Path(__file__).parent / "data" / "channels_config.json"


def load_channels_config() -> dict:
    """Charge la configuration des channels (input/output) depuis le fichier JSON persistant."""
    try:
        if CONFIG_FILE_PATH.exists():
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        print(f"⚠️ Erreur lors du chargement de la config des channels : {exc}")
    return {"input_channel_id": None, "output_channel_id": None}


def save_channels_config(input_channel_id: int | None, output_channel_id: int | None) -> None:
    """Sauvegarde la configuration des channels dans le fichier JSON persistant."""
    try:
        CONFIG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "input_channel_id": input_channel_id,
                "output_channel_id": output_channel_id,
            }, f, indent=2)
    except Exception as exc:
        print(f"❌ Erreur lors de la sauvegarde de la config des channels : {exc}")


def validate_config() -> None:
    """Vérifie que les variables d'environnement essentielles sont définies."""
    missing = []
    if not DISCORD_TOKEN:
        missing.append("DISCORD_TOKEN")
    if not OPENROUTER_API_KEY:
        missing.append("OPENROUTER_API_KEY")

    if missing:
        print(f"❌ Variables d'environnement manquantes : {', '.join(missing)}")
        print("   Vérifiez votre fichier .env")
        sys.exit(1)
