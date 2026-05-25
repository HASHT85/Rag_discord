"""
Découpage et parsing des messages pour l'indexation RAG.

Gère le parsing du format d'indexation [Catégorie] Titre,
le découpage en chunks avec recouvrement, et la génération
d'identifiants uniques de documents.
"""

import re
import logging

from config import CHUNK_SIZE, CHUNK_OVERLAP

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  Regex pour le format d'indexation
# ─────────────────────────────────────────────
# Capture : [Catégorie] Titre du document
_INDEX_PATTERN = re.compile(r"^\[([^\]]+)\]\s*(.+)")


def parse_indexed_message(content: str) -> dict | None:
    """
    Parse un message suivant le format d'indexation.

    Format attendu :
        [Catégorie] Titre du document
        Contenu du message...

    Args:
        content: Le contenu brut du message Discord.

    Returns:
        Dictionnaire {'category', 'title', 'content'} ou None
        si le message ne correspond pas au format.
    """
    if not content or not content.strip():
        return None

    lines = content.strip().split("\n", 1)
    first_line = lines[0].strip()

    match = _INDEX_PATTERN.match(first_line)
    if not match:
        logger.debug("⏭️ Message ignoré (format non reconnu) : %s", first_line[:80])
        return None

    category = match.group(1).strip()
    title = match.group(2).strip()
    # Le contenu est tout ce qui suit la première ligne
    body = lines[1].strip() if len(lines) > 1 else ""

    if not body:
        logger.warning(
            "⚠️ Message indexé sans contenu : [%s] %s", category, title
        )
        return None

    logger.debug("📋 Message parsé : [%s] %s (%d car.)", category, title, len(body))

    return {
        "category": category,
        "title": title,
        "content": body,
    }


def _split_text_recursive(
    text: str,
    chunk_size: int,
    separators: list[str],
) -> list[str]:
    """
    Découpe récursivement un texte en morceaux en essayant les séparateurs
    dans l'ordre de priorité.

    Args:
        text: Le texte à découper.
        chunk_size: Taille maximale de chaque morceau.
        separators: Liste de séparateurs ordonnés du plus large au plus fin.

    Returns:
        Liste de morceaux de texte.
    """
    # Cas de base : le texte tient dans un chunk
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    # Essayer chaque séparateur
    for i, sep in enumerate(separators):
        if sep in text:
            parts = text.split(sep)
            chunks: list[str] = []
            current = ""

            for part in parts:
                # Ajouter le séparateur sauf si c'est un caractère vide
                candidate = current + sep + part if current else part

                if len(candidate) <= chunk_size:
                    current = candidate
                else:
                    # Sauvegarder le chunk courant s'il existe
                    if current.strip():
                        chunks.append(current.strip())

                    # Si la partie seule dépasse la taille, découper plus fin
                    if len(part) > chunk_size:
                        sub_chunks = _split_text_recursive(
                            part, chunk_size, separators[i + 1:]
                        )
                        chunks.extend(sub_chunks)
                        current = ""
                    else:
                        current = part

            # Ne pas oublier le dernier morceau
            if current.strip():
                chunks.append(current.strip())

            return chunks

    # Dernier recours : découpage par caractères
    chunks = []
    for start in range(0, len(text), chunk_size):
        chunk = text[start:start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
    return chunks


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """
    Découpe un texte long en chunks avec recouvrement.

    Utilise une approche récursive : tente de découper d'abord sur
    les doubles sauts de ligne, puis les simples, puis les espaces,
    et enfin par caractères.

    Args:
        text: Le texte à découper.
        chunk_size: Taille maximale de chaque chunk en caractères.
        overlap: Nombre de caractères de recouvrement entre chunks.

    Returns:
        Liste de chunks de texte.
    """
    if not text or not text.strip():
        return []

    text = text.strip()

    # Si le texte est assez court, un seul chunk
    if len(text) <= chunk_size:
        return [text]

    # Séparateurs par ordre de priorité (du plus large au plus fin)
    separators = ["\n\n", "\n", " ", ""]

    # Découpage initial sans recouvrement
    raw_chunks = _split_text_recursive(text, chunk_size, separators)

    if not raw_chunks:
        return []

    # Si pas de recouvrement demandé ou un seul chunk, retourner directement
    if overlap <= 0 or len(raw_chunks) <= 1:
        return raw_chunks

    # Appliquer le recouvrement entre chunks consécutifs
    overlapped_chunks: list[str] = [raw_chunks[0]]

    for i in range(1, len(raw_chunks)):
        prev_chunk = raw_chunks[i - 1]
        current_chunk = raw_chunks[i]

        # Prendre les derniers caractères du chunk précédent comme préfixe
        overlap_text = prev_chunk[-overlap:]

        # Éviter la duplication si le chunk commence déjà par le texte de recouvrement
        if not current_chunk.startswith(overlap_text):
            merged = (overlap_text + " " + current_chunk).strip()
            overlapped_chunks.append(merged)
        else:
            overlapped_chunks.append(current_chunk)

    logger.debug(
        "✂️ Texte découpé en %d chunk(s) (taille=%d, recouvrement=%d).",
        len(overlapped_chunks), chunk_size, overlap,
    )

    return overlapped_chunks


def build_document_text(
    category: str,
    title: str,
    content: str,
    author: str,
    channel: str,
    timestamp: str,
) -> str:
    """
    Construit le texte final à indexer avec un préfixe de métadonnées.

    Le préfixe aide le modèle d'embedding à capturer le contexte
    des documents lors de la recherche.

    Args:
        category: Catégorie du document (ex: 'Règles', 'FAQ').
        title: Titre du document.
        content: Contenu textuel du document.
        author: Nom de l'auteur du message Discord.
        channel: Nom du channel Discord source.
        timestamp: Horodatage du message (format libre).

    Returns:
        Texte formaté prêt pour l'embedding.
    """
    prefix = (
        f"[Catégorie: {category} | Titre: {title} | "
        f"Par: {author} | Dans: #{channel} | Date: {timestamp}]"
    )
    document = f"{prefix}\n{content}"

    logger.debug(
        "📝 Document construit : [%s] %s (%d car.)",
        category, title, len(document),
    )

    return document


def generate_doc_id(message_id: int, chunk_index: int = 0) -> str:
    """
    Génère un identifiant unique de document à partir de l'ID du message
    et de l'index du chunk.

    Args:
        message_id: L'identifiant unique du message Discord.
        chunk_index: L'index du chunk dans le message (0 par défaut).

    Returns:
        Identifiant unique sous forme de chaîne.
    """
    doc_id = f"msg_{message_id}_chunk_{chunk_index}"
    logger.debug("🔑 ID généré : %s", doc_id)
    return doc_id
