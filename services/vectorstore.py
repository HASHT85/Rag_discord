"""
Wrapper autour de Firestore pour le stockage et la recherche de vecteurs.

Gère la persistance cloud des embeddings et fournit une interface
simple pour l'ajout, la recherche et la suppression de documents.
"""

import logging
from typing import Any

from google.api_core.exceptions import FailedPrecondition
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from google.cloud.firestore_v1.vector import Vector
from firebase_admin import firestore

from config import db, COLLECTION_NAME, TOP_K

logger = logging.getLogger(__name__)


class VectorStore:
    """
    Gestionnaire du vectorstore Firestore.

    Encapsule un client Firestore et fournit des méthodes
    pour manipuler les documents et leurs embeddings.
    """

    def __init__(self) -> None:
        """
        Initialise le client Firestore et la collection.
        """
        logger.info(
            "🗄️ Initialisation de Firestore (collection=%s)...",
            COLLECTION_NAME,
        )
        self._collection = db.collection(COLLECTION_NAME)
        logger.info("✅ Firestore VectorStore prêt.")

    def add_documents(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str],
        embeddings: list[list[float]],
    ) -> None:
        """
        Ajoute des documents avec leurs embeddings pré-calculés dans Firestore.
        """
        if not texts:
            logger.warning("⚠️ Aucun document à ajouter.")
            return

        lengths = {
            "texts": len(texts),
            "metadatas": len(metadatas),
            "ids": len(ids),
            "embeddings": len(embeddings),
        }
        unique_lengths = set(lengths.values())
        if len(unique_lengths) > 1:
            raise ValueError(
                f"Les listes doivent avoir la même taille : {lengths}"
            )

        logger.debug("📥 Ajout de %d document(s) à Firestore...", len(texts))

        batch = db.batch()
        for i, (text, metadata, doc_id, embedding) in enumerate(zip(texts, metadatas, ids, embeddings)):
            doc_ref = self._collection.document(doc_id)
            batch.set(doc_ref, {
                "text": text,
                "embedding": Vector(embedding),
                "metadata": metadata,
                "created_at": firestore.SERVER_TIMESTAMP,
            })

            # Firestore limite les batchs à 500 écritures
            if (i + 1) % 500 == 0:
                batch.commit()
                batch = db.batch()

        if len(texts) % 500 != 0:
            batch.commit()

        logger.info("✅ %d document(s) ajouté(s) avec succès.", len(texts))

    def query(
        self,
        query_embedding: list[float],
        n_results: int = TOP_K,
    ) -> dict[str, Any]:
        """
        Effectue une recherche par similarité cosinus dans Firestore.
        """
        logger.debug(
            "🔍 Recherche de similarité Firestore (top_k=%d)...", n_results
        )

        try:
            vector_query = self._collection.find_nearest(
                vector_field="embedding",
                query_vector=Vector(query_embedding),
                distance_measure=DistanceMeasure.COSINE,
                limit=n_results,
                distance_result_field="vector_distance"
            )

            docs = vector_query.stream()

            ids = []
            documents = []
            metadatas = []
            distances = []

            for doc in docs:
                data = doc.to_dict()
                ids.append(doc.id)
                documents.append(data.get("text", ""))
                metadatas.append(data.get("metadata", {}))
                
                # Récupérer la distance retournée
                distance = data.get("vector_distance", 0.0)
                distances.append(distance)

            logger.info("✅ %d résultat(s) trouvé(s).", len(ids))

            return {
                "ids": ids,
                "documents": documents,
                "metadatas": metadatas,
                "distances": distances,
            }

        except FailedPrecondition as exc:
            logger.error("❌ L'index vectoriel Firestore est requis.")
            logger.error("👉 Vous devez le créer en cliquant sur le lien suivant dans votre console Firebase :")
            logger.error("   %s", exc.message)
            raise exc
        except Exception as exc:
            logger.error("❌ Erreur lors de la recherche vectorielle : %s", exc, exc_info=True)
            raise exc

    def get_stats(self) -> dict[str, Any]:
        """
        Retourne des statistiques sur le vectorstore Firestore.
        """
        try:
            alias = "count"
            count_query = self._collection.count(alias=alias)
            results = count_query.get()
            count = results[0].get(alias)
        except Exception as exc:
            logger.warning("Impossible de récupérer le nombre de documents : %s", exc)
            count = -1

        stats = {
            "total_documents": count,
            "collection_name": COLLECTION_NAME,
        }

        logger.debug("📊 Stats vectorstore : %s", stats)
        return stats

    def delete_by_metadata(self, key: str, value: str) -> None:
        """
        Supprime tous les documents dont une métadonnée correspond au filtre.
        """
        logger.debug(
            "🗑️ Suppression des documents où metadata.%s='%s'...", key, value
        )

        query = self._collection.where(f"metadata.{key}", "==", value)
        docs = query.stream()

        batch = db.batch()
        count = 0
        for doc in docs:
            batch.delete(doc.reference)
            count += 1
            if count % 500 == 0:
                batch.commit()
                batch = db.batch()

        if count % 500 != 0:
            batch.commit()

        logger.info(
            "✅ %d document(s) supprimé(s) (filtre: metadata.%s='%s').",
            count, key, value,
        )

    def document_exists(self, doc_id: str) -> bool:
        """
        Vérifie si un document avec l'identifiant donné existe déjà.
        """
        doc_ref = self._collection.document(doc_id)
        doc = doc_ref.get()
        return doc.exists
