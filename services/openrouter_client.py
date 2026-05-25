"""
Client asynchrone pour l'API OpenRouter.

Utilise le package openai avec base_url pointant vers OpenRouter
pour les embeddings et la génération de réponses LLM.
"""

import asyncio
import logging
from typing import Optional

from openai import AsyncOpenAI, APIError, APIConnectionError, RateLimitError

from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, LLM_MODEL, EMBEDDING_MODEL

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  Configuration du client OpenRouter
# ─────────────────────────────────────────────

# En-têtes supplémentaires requis par OpenRouter
_EXTRA_HEADERS = {
    "HTTP-Referer": "discord-rag-bot",
    "X-Title": "Discord RAG Bot",
}

# Client asynchrone OpenAI configuré pour OpenRouter
_client = AsyncOpenAI(
    base_url=OPENROUTER_BASE_URL,
    api_key=OPENROUTER_API_KEY,
    default_headers=_EXTRA_HEADERS,
)

# ─────────────────────────────────────────────
#  Paramètres de retry
# ─────────────────────────────────────────────
_MAX_RETRIES: int = 3
_RETRY_BASE_DELAY: float = 1.0  # secondes


async def _retry_with_backoff(coro_factory, description: str = "requête"):
    """
    Exécute une coroutine avec retry et backoff exponentiel.

    Args:
        coro_factory: Fonction sans argument qui retourne une coroutine.
        description: Description de l'opération pour les logs.

    Returns:
        Le résultat de la coroutine.

    Raises:
        Exception: Relance la dernière erreur après épuisement des retries.
    """
    last_exception: Optional[Exception] = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return await coro_factory()
        except RateLimitError as e:
            last_exception = e
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.warning(
                "⚠️ Rate limit atteint pour %s (tentative %d/%d). "
                "Nouvelle tentative dans %.1fs...",
                description, attempt, _MAX_RETRIES, delay,
            )
            await asyncio.sleep(delay)
        except APIConnectionError as e:
            last_exception = e
            delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.warning(
                "⚠️ Erreur de connexion pour %s (tentative %d/%d). "
                "Nouvelle tentative dans %.1fs...",
                description, attempt, _MAX_RETRIES, delay,
            )
            await asyncio.sleep(delay)
        except APIError as e:
            last_exception = e
            # Erreurs 5xx : on retry. Erreurs 4xx (sauf 429) : on abandonne.
            if e.status_code and e.status_code >= 500:
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "⚠️ Erreur serveur %d pour %s (tentative %d/%d). "
                    "Nouvelle tentative dans %.1fs...",
                    e.status_code, description, attempt, _MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "❌ Erreur API irrécupérable pour %s : %s",
                    description, e,
                )
                raise

    # Toutes les tentatives ont échoué
    logger.error(
        "❌ Échec de %s après %d tentatives.", description, _MAX_RETRIES
    )
    raise last_exception  # type: ignore[misc]


# ─────────────────────────────────────────────
#  Fonctions publiques
# ─────────────────────────────────────────────


async def get_embedding(texts: list[str]) -> list[list[float]]:
    """
    Génère les embeddings pour une liste de textes via OpenRouter.

    Args:
        texts: Liste de textes à convertir en vecteurs.

    Returns:
        Liste de vecteurs (liste de floats) dans le même ordre que les textes.

    Raises:
        APIError: En cas d'erreur irrécupérable de l'API.
    """
    if not texts:
        return []

    logger.debug("📐 Génération d'embeddings pour %d texte(s)...", len(texts))

    async def _call():
        response = await _client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts,
        )
        return response

    response = await _retry_with_backoff(_call, description="embedding")

    # Trier par index pour garantir l'ordre
    sorted_data = sorted(response.data, key=lambda x: x.index)
    embeddings = [item.embedding for item in sorted_data]

    logger.info(
        "✅ %d embedding(s) généré(s) (dimension=%d).",
        len(embeddings),
        len(embeddings[0]) if embeddings else 0,
    )

    return embeddings


async def generate_answer(question: str, context: str) -> str:
    """
    Génère une réponse à une question en utilisant le contexte fourni.

    Args:
        question: La question posée par l'utilisateur.
        context: Le contexte extrait du vectorstore (documents pertinents).

    Returns:
        La réponse générée par le LLM.

    Raises:
        APIError: En cas d'erreur irrécupérable de l'API.
    """
    # Prompt système en français, orienté RAG Discord
    system_prompt = (
        "Tu es un assistant intelligent intégré dans un serveur Discord. "
        "Tu réponds **toujours en français**.\n\n"
        "Tu disposes du contexte suivant, extrait de messages et documents "
        "indexés sur ce serveur Discord. Utilise **uniquement** ce contexte "
        "pour répondre à la question de l'utilisateur.\n\n"
        "Règles :\n"
        "- Réponds de manière claire, concise et structurée.\n"
        "- Cite tes sources quand c'est possible (catégorie, titre, auteur).\n"
        "- Si le contexte ne contient pas assez d'informations pour répondre, "
        "dis-le honnêtement.\n"
        "- N'invente jamais d'informations qui ne sont pas dans le contexte.\n\n"
        f"--- CONTEXTE ---\n{context}\n--- FIN DU CONTEXTE ---"
    )

    logger.debug("🤖 Génération de réponse pour : %s", question[:100])

    async def _call():
        response = await _client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            temperature=0.3,
            max_tokens=1500,
        )
        return response

    response = await _retry_with_backoff(_call, description="génération LLM")

    answer = response.choices[0].message.content or ""

    logger.info(
        "✅ Réponse générée (%d caractères, modèle=%s).",
        len(answer), LLM_MODEL,
    )

    return answer.strip()
