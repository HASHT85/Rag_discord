"""
Service de gestion de la mémoire de conversation pour le bot RAG Discord.
Gère l'historique glissant par fil (thread), par canal ou par chaîne de réponses (reply chain).
"""

import logging
import time
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)


class ConversationMemory:
    """
    Gère la mémoire glissante des conversations Discord.

    Attributes:
        max_turns: Nombre maximum de tours conservés par contexte (1 tour = 1 user msg + 1 assistant msg).
        _memory: Dictionnaire mapping context_id -> deque de tours.
        _message_to_context: Dictionnaire mapping bot_message_id -> context_id.
        _last_accessed: Dictionnaire mapping context_id -> timestamp (float).
    """

    def __init__(self, max_turns: int = 5) -> None:
        self.max_turns = max_turns
        self._memory: dict[str, deque[tuple[dict, dict]]] = {}
        self._message_to_context: dict[str, str] = {}
        self._last_accessed: dict[str, float] = {}

    def add_turn(self, context_id: str, user_query: str, assistant_response: str) -> None:
        """
        Ajoute un tour de conversation à l'historique d'un contexte.
        Un tour comprend un message utilisateur et une réponse assistant.
        """
        context_key = str(context_id)
        if context_key not in self._memory:
            self._memory[context_key] = deque(maxlen=self.max_turns)

        user_msg = {"role": "user", "content": user_query}
        assistant_msg = {"role": "assistant", "content": assistant_response}

        self._memory[context_key].append((user_msg, assistant_msg))
        self._last_accessed[context_key] = time.time()
        logger.debug(
            "Mémoire mise à jour pour context_id=%s (%d tours)",
            context_key, len(self._memory[context_key]),
        )

    def get_history(self, context_id: str) -> list[dict]:
        """
        Récupère l'historique chronologique des messages pour un context_id sous forme de list[dict].
        Chaque tour produit 2 dicts : {"role": "user", "content": ...} et {"role": "assistant", "content": ...}.
        """
        context_key = str(context_id)
        if context_key not in self._memory:
            return []

        self._last_accessed[context_key] = time.time()
        history: list[dict] = []
        for user_msg, assistant_msg in self._memory[context_key]:
            history.append(dict(user_msg))
            history.append(dict(assistant_msg))
        return history

    def register_bot_message(self, message_id: str | int, context_id: str) -> None:
        """
        Associe un message envoyé par le bot à un context_id pour supporter le suivi des reply chains.
        """
        msg_key = str(message_id)
        context_key = str(context_id)
        self._message_to_context[msg_key] = context_key
        logger.debug("Message bot %s enregistré pour context_id=%s", msg_key, context_key)

    def get_context_id_from_message(self, message_id: str | int) -> Optional[str]:
        """
        Retrouve le context_id associé à un message bot (pour les réponses de type reply).
        """
        msg_key = str(message_id)
        return self._message_to_context.get(msg_key)

    def cleanup_expired(self, ttl_seconds: int = 86400) -> int:
        """
        Nettoie les entrées de mémoire inactives depuis plus de ttl_seconds (par défaut 24h).
        Retourne le nombre de contextes nettoyés.
        """
        now = time.time()
        expired_keys = [
            cid for cid, last_time in self._last_accessed.items()
            if (now - last_time) > ttl_seconds
        ]

        for cid in expired_keys:
            self._memory.pop(cid, None)
            self._last_accessed.pop(cid, None)
            # Nettoyer les mappings message_id correspondant à ce context_id
            msg_keys_to_del = [
                msg_id for msg_id, context_id in self._message_to_context.items()
                if context_id == cid
            ]
            for msg_id in msg_keys_to_del:
                self._message_to_context.pop(msg_id, None)

        if expired_keys:
            logger.info("🧹 Nettoyage mémoire : %d contextes expirés supprimés.", len(expired_keys))
        return len(expired_keys)


# Instance globale partageable
conversation_memory = ConversationMemory()
