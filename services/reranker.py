"""
Service de Re-Ranking (Filtrage Anti-Bruit) avec FlashRank.
Permet d'éliminer 90% du hors-sujet et de garantir la pertinence des documents envoyés au LLM.
"""

import logging
from typing import Any
from flashrank import Ranker, RerankRequest

logger = logging.getLogger(__name__)

# Initialiser le ranker (modèle ultraléger ms-marco-TinyBERT-L-2-v2)
_ranker: Ranker | None = None


def get_ranker() -> Ranker:
    """Retourne l'instance singleton du Ranker FlashRank."""
    global _ranker
    if _ranker is None:
        logger.info("⚡ Initialisation du Reranker FlashRank...")
        _ranker = Ranker(model_name="ms-marco-TinyBERT-L-2-v2")
        logger.info("✅ FlashRank Reranker prêt.")
    return _ranker


def rerank_documents(
    query: str,
    documents: list[dict[str, Any]],
    top_n: int = 5,
) -> list[dict[str, Any]]:
    """
    Réordonne et filtre une liste de documents candidats renvoyés par la recherche vectorielle.

    Args:
        query: La question posée par l'utilisateur.
        documents: Liste de dictionnaires contenant 'id', 'text', 'metadata', etc.
        top_n: Le nombre maximal de documents à conserver après filtrage.

    Returns:
        La liste des top_n documents les plus pertinents, triés par score décroissant.
    """
    if not documents:
        return []

    ranker = get_ranker()

    # Formater les passages pour FlashRank
    passages = []
    for doc in documents:
        passages.append({
            "id": doc.get("id"),
            "text": doc.get("text", ""),
            "metadata": doc.get("metadata", {}),
        })

    logger.debug("🛡️ Re-Ranking de %d candidat(s) pour la requête : '%s'", len(passages), query[:50])

    try:
        rerank_req = RerankRequest(query=query, passages=passages)
        ranked_results = ranker.rerank(rerank_req)

        # Reconstruire les documents enrichis du score de pertinence
        final_docs = []
        for item in ranked_results[:top_n]:
            final_docs.append({
                "id": item["id"],
                "text": item["text"],
                "metadata": item.get("metadata", {}),
                "score": item.get("score", 0.0),
            })

        logger.info("✅ Re-Ranking terminé : %d document(s) retenu(s) (meilleur score=%.4f).",
                    len(final_docs), final_docs[0]["score"] if final_docs else 0.0)

        return final_docs

    except Exception as exc:
        logger.error("❌ Erreur lors du Re-Ranking : %s. Retour des candidats originaux.", exc, exc_info=True)
        return documents[:top_n]
