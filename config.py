"""
Configuration centralisée du bot Discord RAG.
Charge les variables d'environnement et expose les constantes.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

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
#  Firebase & Firestore
# ─────────────────────────────────────────────
FIREBASE_CREDENTIALS_PATH: str = os.getenv("FIREBASE_CREDENTIALS_PATH", "serviceAccountKey.json")
COLLECTION_NAME: str = os.getenv("COLLECTION_NAME", "discord_rag")

def init_firebase() -> firestore.firestore.Client:
    """Initialise l'application Firebase et retourne le client Firestore."""
    if not firebase_admin._apps:
        # 1. Vérifier si les credentials sont fournis sous forme de chaîne JSON
        cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
        if cred_json:
            try:
                import json
                cred_dict = json.loads(cred_json)
                if "private_key" in cred_dict:
                    pk = cred_dict["private_key"]
                    # Fix backspace corruption (Hostinger/Docker compose env parser bug)
                    # where '\nb' is incorrectly unescaped to '\x08' (backspace)
                    if '\x08' in pk:
                        pk = pk.replace('\x08', '\nb')
                    pk = pk.replace("\\n", "\n")
                    import hashlib
                    h = hashlib.sha256(pk.encode('utf-8')).hexdigest()
                    print(f"DEBUG VPS KEY: len={len(pk)}, SHA256={h}")
                    cred_dict["private_key"] = pk
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
                return firestore.client()
            except Exception as exc:
                print(f"❌ Erreur lors de l'initialisation de Firebase via la variable JSON : {exc}")
                sys.exit(1)

        # 2. Sinon, essayer le fichier local
        if os.path.exists(FIREBASE_CREDENTIALS_PATH):
            cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
            firebase_admin.initialize_app(cred)
        else:
            try:
                firebase_admin.initialize_app()
            except Exception as exc:
                print("❌ Impossible d'initialiser Firebase. Assurez-vous d'avoir configuré la variable FIREBASE_CREDENTIALS_JSON ou le fichier serviceAccountKey.json.")
                print(f"   Erreur détaillée : {exc}")
                sys.exit(1)
    return firestore.client()

db = init_firebase()

# ─────────────────────────────────────────────
#  Paramètres RAG
# ─────────────────────────────────────────────
TOP_K: int = int(os.getenv("TOP_K", "5"))
CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "50"))


def load_channels_config() -> dict:
    """Charge la configuration des channels (input/output) depuis Firestore."""
    try:
        doc_ref = db.collection("bot_config").document("channels")
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict()
    except Exception as exc:
        print(f"⚠️ Erreur lors du chargement de la config depuis Firestore : {exc}")
    return {"input_channel_id": None, "output_channel_id": None}


def save_channels_config(input_channel_id: int | None, output_channel_id: int | None) -> None:
    """Sauvegarde la configuration des channels dans Firestore."""
    try:
        doc_ref = db.collection("bot_config").document("channels")
        doc_ref.set({
            "input_channel_id": input_channel_id,
            "output_channel_id": output_channel_id,
        })
    except Exception as exc:
        print(f"❌ Erreur lors de la sauvegarde de la config dans Firestore : {exc}")


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
