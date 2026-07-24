"""
Wrapper autour de Qdrant pour le stockage et la recherche hybride de vecteurs.
Combine un vecteur dense (Gemini Embedding 2 3072d) et un vecteur sparse (BM25).
"""

import logging
import uuid
from typing import Any
from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient, models

from config import QDRANT_HOST, QDRANT_PORT, COLLECTION_NAME, EMBEDDING_DIMENSIONS, TOP_K

logger = logging.getLogger(__name__)


class VectorStore:
    """
    Gestionnaire du vectorstore Qdrant.
    Gère l'indexation hybride (Dense 3072d + Sparse BM25) et la recherche par fusion RRF.
    """

    def __init__(self) -> None:
        """Initialise le client Qdrant, le modèle BM25 et s'assure que la collection existe."""
        logger.info(
            "🗄️ Connexion à Qdrant (%s:%d, collection=%s)...",
            QDRANT_HOST, QDRANT_PORT, COLLECTION_NAME,
        )
        self.client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        self.bm25_model = SparseTextEmbedding(model_name="Qdrant/bm25")
        self._ensure_collection()
        logger.info("✅ Qdrant VectorStore prêt.")

    def _ensure_collection(self) -> None:
        """Crée la collection Qdrant si elle n'existe pas déjà, avec support Dense + Sparse."""
        try:
            collections = self.client.get_collections().collections
            exists = any(c.name == COLLECTION_NAME for c in collections)
            if not exists:
                logger.info("📦 Création de la collection Qdrant '%s' (3072d + BM25)...", COLLECTION_NAME)
                self.client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config={
                        "dense": models.VectorParams(
                            size=EMBEDDING_DIMENSIONS,
                            distance=models.Distance.COSINE,
                        )
                    },
                    sparse_vectors_config={
                        "sparse": models.SparseVectorParams(
                            index=models.SparseIndexParams(on_disk=False)
                        )
                    },
                )
                logger.info("✅ Collection Qdrant '%s' créée avec succès.", COLLECTION_NAME)
        except Exception as exc:
            logger.error("❌ Erreur lors de l'initialisation de la collection Qdrant : %s", exc, exc_info=True)

    def add_documents(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str],
        embeddings: list[list[float]],
    ) -> None:
        """
        Ajoute des documents dans Qdrant avec leurs embeddings denses et sparse BM25.
        """
        if not texts:
            logger.warning("⚠️ Aucun document à ajouter.")
            return

        logger.debug("📥 Génération des vecteurs sparse BM25 pour %d document(s)...", len(texts))
        sparse_embeddings = list(self.bm25_model.embed(texts))

        points = []
        for doc_id, text, metadata, dense_vec, sparse_vec in zip(
            ids, texts, metadatas, embeddings, sparse_embeddings
        ):
            try:
                point_id = str(uuid.UUID(doc_id))
            except ValueError:
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(doc_id)))

            payload = {
                "text": text,
                "metadata": metadata,
                "original_id": str(doc_id),
            }

            points.append(
                models.PointStruct(
                    id=point_id,
                    vector={
                        "dense": dense_vec,
                        "sparse": models.SparseVector(
                            indices=sparse_vec.indices.tolist(),
                            values=sparse_vec.values.tolist(),
                        ),
                    },
                    payload=payload,
                )
            )

        # Batch par 100 points
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            self.client.upsert(collection_name=COLLECTION_NAME, points=batch)

        logger.info("✅ %d document(s) ajouté(s) à Qdrant.", len(texts))

    def query(
        self,
        query_embedding: list[float],
        query_text: str = "",
        n_results: int = TOP_K,
    ) -> dict[str, Any]:
        """
        Effectue une recherche hybride (Dense + Sparse BM25) avec fusion RRF dans Qdrant.
        """
        logger.debug("🔍 Recherche Hybride Qdrant (top_k=%d)...", n_results)

        try:
            prefetch = []

            # 1. Prefetch Dense
            prefetch.append(
                models.Prefetch(
                    query=query_embedding,
                    using="dense",
                    limit=n_results * 4,
                )
            )

            # 2. Prefetch Sparse (si du texte de requête est disponible)
            if query_text:
                sparse_vec = list(self.bm25_model.embed([query_text]))[0]
                prefetch.append(
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=sparse_vec.indices.tolist(),
                            values=sparse_vec.values.tolist(),
                        ),
                        using="sparse",
                        limit=n_results * 4,
                    )
                )

            # Recherche avec fusion Reciprocal Rank Fusion (RRF)
            search_result = self.client.query_points(
                collection_name=COLLECTION_NAME,
                prefetch=prefetch,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=n_results * 4,  # Récupérer plus de candidats pour le Re-Ranking !
            )

            ids = []
            documents = []
            metadatas = []
            distances = []

            for hit in search_result.points:
                payload = hit.payload or {}
                ids.append(payload.get("original_id", str(hit.id)))
                documents.append(payload.get("text", ""))
                metadatas.append(payload.get("metadata", {}))
                distances.append(hit.score)

            logger.info("✅ %d résultat(s) Hybride Qdrant trouvé(s).", len(ids))

            return {
                "ids": ids,
                "documents": documents,
                "metadatas": metadatas,
                "distances": distances,
            }

        except Exception as exc:
            logger.error("❌ Erreur lors de la recherche Qdrant : %s", exc, exc_info=True)
            raise exc

    def get_stats(self) -> dict[str, Any]:
        """Retourne des statistiques sur la collection Qdrant."""
        try:
            info = self.client.get_collection(collection_name=COLLECTION_NAME)
            count = info.points_count
        except Exception as exc:
            logger.warning("Impossible de récupérer les stats Qdrant : %s", exc)
            count = -1

        return {
            "total_documents": count,
            "collection_name": COLLECTION_NAME,
        }

    def delete_by_metadata(self, key: str, value: str) -> None:
        """Supprime tous les documents dont la métadonnée correspond au filtre."""
        try:
            self.client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key=f"metadata.{key}",
                                match=models.MatchValue(value=value),
                            )
                        ]
                    )
                ),
            )
            logger.info("✅ Documents supprimés (filtre: metadata.%s='%s').", key, value)
        except Exception as exc:
            logger.error("❌ Erreur lors de la suppression Qdrant : %s", exc, exc_info=True)

    def document_exists(self, doc_id: str) -> bool:
        """Vérifie si un document avec cet ID existe déjà."""
        try:
            point_id = str(uuid.UUID(doc_id))
        except ValueError:
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(doc_id)))

        try:
            res = self.client.retrieve(
                collection_name=COLLECTION_NAME,
                ids=[point_id],
            )
            return len(res) > 0
        except Exception:
            return False
