"""
Wrapper autour de ChromaDB pour le stockage et la recherche de vecteurs.

Gère la persistance locale des embeddings et fournit une interface
simple pour l'ajout, la recherche et la suppression de documents.
"""

import logging
from typing import Any

import chromadb

from config import CHROMA_PERSIST_DIR, COLLECTION_NAME, TOP_K

logger = logging.getLogger(__name__)


class VectorStore:
    """
    Gestionnaire du vectorstore ChromaDB.

    Encapsule un client persistant ChromaDB et fournit des méthodes
    pour manipuler les documents et leurs embeddings.
    """

    def __init__(self) -> None:
        """
        Initialise le client ChromaDB et récupère ou crée la collection.
        """
        logger.info(
            "🗄️ Initialisation de ChromaDB (dossier=%s, collection=%s)...",
            CHROMA_PERSIST_DIR, COLLECTION_NAME,
        )

        self._client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

        count = self._collection.count()
        logger.info(
            "✅ VectorStore prêt — %d document(s) existant(s).", count
        )

    def add_documents(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]],
        ids: list[str],
        embeddings: list[list[float]],
    ) -> None:
        """
        Ajoute des documents avec leurs embeddings pré-calculés.

        Args:
            texts: Liste des textes des documents.
            metadatas: Liste des métadonnées associées à chaque document.
            ids: Liste des identifiants uniques de chaque document.
            embeddings: Liste des vecteurs d'embedding pré-calculés.

        Raises:
            ValueError: Si les listes n'ont pas la même longueur.
        """
        if not texts:
            logger.warning("⚠️ Aucun document à ajouter.")
            return

        # Vérification de cohérence des tailles
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

        logger.debug("📥 Ajout de %d document(s) au vectorstore...", len(texts))

        self._collection.add(
            documents=texts,
            metadatas=metadatas,  # type: ignore[arg-type]
            ids=ids,
            embeddings=embeddings,  # type: ignore[arg-type]
        )

        logger.info("✅ %d document(s) ajouté(s) avec succès.", len(texts))

    def query(
        self,
        query_embedding: list[float],
        n_results: int = TOP_K,
    ) -> dict[str, Any]:
        """
        Effectue une recherche par similarité cosinus.

        Args:
            query_embedding: Le vecteur d'embedding de la requête.
            n_results: Nombre maximum de résultats à retourner.

        Returns:
            Dictionnaire contenant les clés 'ids', 'documents',
            'metadatas' et 'distances'.
        """
        logger.debug(
            "🔍 Recherche de similarité (top_k=%d)...", n_results
        )

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

        nb_found = len(results["ids"][0]) if results["ids"] else 0
        logger.info("✅ %d résultat(s) trouvé(s).", nb_found)

        return {
            "ids": results["ids"][0] if results["ids"] else [],
            "documents": results["documents"][0] if results["documents"] else [],
            "metadatas": results["metadatas"][0] if results["metadatas"] else [],
            "distances": results["distances"][0] if results["distances"] else [],
        }

    def get_stats(self) -> dict[str, Any]:
        """
        Retourne des statistiques sur le vectorstore.

        Returns:
            Dictionnaire avec le nombre de documents et les infos de collection.
        """
        count = self._collection.count()
        metadata = self._collection.metadata

        stats = {
            "total_documents": count,
            "collection_name": COLLECTION_NAME,
            "persist_directory": CHROMA_PERSIST_DIR,
            "collection_metadata": metadata,
        }

        logger.debug("📊 Stats vectorstore : %s", stats)
        return stats

    def delete_by_metadata(self, key: str, value: str) -> None:
        """
        Supprime tous les documents dont une métadonnée correspond au filtre.

        Args:
            key: Clé de métadonnée à filtrer.
            value: Valeur attendue pour la suppression.
        """
        logger.debug(
            "🗑️ Suppression des documents où %s='%s'...", key, value
        )

        # Récupérer les IDs correspondants via un filtre where
        results = self._collection.get(
            where={key: value},
            include=[],
        )

        ids_to_delete = results["ids"]
        if not ids_to_delete:
            logger.info("ℹ️ Aucun document trouvé pour %s='%s'.", key, value)
            return

        self._collection.delete(ids=ids_to_delete)
        logger.info(
            "✅ %d document(s) supprimé(s) (filtre: %s='%s').",
            len(ids_to_delete), key, value,
        )

    def document_exists(self, doc_id: str) -> bool:
        """
        Vérifie si un document avec l'identifiant donné existe déjà.

        Args:
            doc_id: Identifiant unique du document.

        Returns:
            True si le document existe, False sinon.
        """
        results = self._collection.get(ids=[doc_id], include=[])
        exists = len(results["ids"]) > 0

        logger.debug(
            "🔎 Document '%s' existe : %s", doc_id, exists
        )
        return exists
