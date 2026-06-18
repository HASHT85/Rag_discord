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
OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"

# ─────────────────────────────────────────────
#  ChromaDB
# ─────────────────────────────────────────────
CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
COLLECTION_NAME: str = "discord_rag"

# ─────────────────────────────────────────────
#  Paramètres RAG
# ─────────────────────────────────────────────
TOP_K: int = int(os.getenv("TOP_K", "5"))
CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "50"))

# ─────────────────────────────────────────────
#  Fichier de persistance des channels configurés
# ─────────────────────────────────────────────
CHANNELS_CONFIG_FILE: str = os.path.join(
    os.path.dirname(__file__), "data", "channels_config.json"
)


def load_channels_config() -> dict:
    """Charge la configuration des channels (input/output) depuis le fichier JSON."""
    if os.path.exists(CHANNELS_CONFIG_FILE):
        with open(CHANNELS_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"input_channel_id": None, "output_channel_id": None}


def save_channels_config(input_channel_id: int | None, output_channel_id: int | None) -> None:
    """Sauvegarde la configuration des channels dans le fichier JSON."""
    os.makedirs(os.path.dirname(CHANNELS_CONFIG_FILE), exist_ok=True)
    data = {
        "input_channel_id": input_channel_id,
        "output_channel_id": output_channel_id,
    }
    with open(CHANNELS_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


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
