"""
Traitement des pièces jointes Discord.

Télécharge et extrait le texte des fichiers joints aux messages
Discord (PDF, fichiers texte, images) pour l'indexation RAG.
"""

import io
import logging
from pathlib import Path

import aiohttp
import discord
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  Constantes
# ─────────────────────────────────────────────

# Taille maximale de fichier autorisée (10 Mo)
_MAX_FILE_SIZE: int = 10 * 1024 * 1024

# Extensions de fichiers texte supportées
_TEXT_EXTENSIONS: set[str] = {
    ".txt", ".md", ".py", ".json", ".csv", ".log",
    ".xml", ".yaml", ".yml", ".html", ".css", ".js", ".ts",
}

# Extensions d'images supportées (décrites par le LLM vision)
_IMAGE_EXTENSIONS: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
}

# Toutes les extensions supportées (texte + PDF + images)
_SUPPORTED_EXTENSIONS: set[str] = _TEXT_EXTENSIONS | {".pdf"} | _IMAGE_EXTENSIONS


def is_supported_attachment(filename: str) -> bool:
    """
    Vérifie si l'extension du fichier est supportée pour l'extraction de texte.

    Args:
        filename: Nom du fichier (avec extension).

    Returns:
        True si le fichier est supporté, False sinon.
    """
    ext = Path(filename).suffix.lower()
    supported = ext in _SUPPORTED_EXTENSIONS
    logger.debug(
        "📎 Fichier '%s' (ext=%s) — supporté : %s",
        filename, ext, supported,
    )
    return supported


async def _download_attachment(attachment: discord.Attachment) -> bytes | None:
    """
    Télécharge le contenu d'une pièce jointe Discord de manière asynchrone.

    Args:
        attachment: Objet Attachment de discord.py.

    Returns:
        Contenu du fichier en bytes, ou None en cas d'erreur ou de dépassement
        de taille.
    """
    # Vérifier la taille avant le téléchargement
    if attachment.size and attachment.size > _MAX_FILE_SIZE:
        logger.warning(
            "⚠️ Fichier '%s' trop volumineux (%d octets, max=%d).",
            attachment.filename, attachment.size, _MAX_FILE_SIZE,
        )
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as response:
                if response.status != 200:
                    logger.error(
                        "❌ Échec du téléchargement de '%s' (HTTP %d).",
                        attachment.filename, response.status,
                    )
                    return None

                data = await response.read()

                # Vérification de taille post-téléchargement
                if len(data) > _MAX_FILE_SIZE:
                    logger.warning(
                        "⚠️ Fichier '%s' trop volumineux après téléchargement "
                        "(%d octets).",
                        attachment.filename, len(data),
                    )
                    return None

                logger.debug(
                    "📥 Fichier '%s' téléchargé (%d octets).",
                    attachment.filename, len(data),
                )
                return data

    except aiohttp.ClientError as e:
        logger.error(
            "❌ Erreur réseau lors du téléchargement de '%s' : %s",
            attachment.filename, e,
        )
        return None


def _extract_text_from_pdf(data: bytes) -> str | None:
    """
    Extrait le texte de toutes les pages d'un fichier PDF.

    Args:
        data: Contenu du PDF en bytes.

    Returns:
        Texte extrait concaténé, ou None si aucun texte trouvé.
    """
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        pages_text: list[str] = []

        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text = page.get_text("text")
            if text and text.strip():
                pages_text.append(text.strip())

        doc.close()

        if not pages_text:
            logger.warning("⚠️ Aucun texte extrait du PDF.")
            return None

        full_text = "\n\n".join(pages_text)
        logger.info(
            "📄 Texte PDF extrait : %d page(s), %d caractères.",
            len(pages_text), len(full_text),
        )
        return full_text

    except Exception as e:
        logger.error("❌ Erreur lors de l'extraction PDF : %s", e)
        return None


def _extract_text_from_text_file(data: bytes, filename: str) -> str | None:
    """
    Décode le contenu d'un fichier texte.

    Tente le décodage en UTF-8, puis en latin-1 en cas d'échec.

    Args:
        data: Contenu du fichier en bytes.
        filename: Nom du fichier (pour les logs).

    Returns:
        Contenu décodé en chaîne, ou None si le décodage échoue.
    """
    # Essayer UTF-8 d'abord, puis latin-1 comme fallback
    for encoding in ("utf-8", "latin-1"):
        try:
            text = data.decode(encoding)
            if text.strip():
                logger.debug(
                    "📝 Fichier '%s' décodé en %s (%d car.).",
                    filename, encoding, len(text),
                )
                return text.strip()
        except (UnicodeDecodeError, ValueError):
            continue

    logger.warning("⚠️ Impossible de décoder le fichier '%s'.", filename)
    return None


async def extract_text_from_attachment(
    attachment: discord.Attachment,
) -> str | None:
    """
    Télécharge et extrait le texte d'une pièce jointe Discord.

    Supporte les fichiers PDF (via PyMuPDF) et les fichiers texte
    courants (.txt, .md, .py, .json, .csv, .log, .xml, .yaml,
    .yml, .html, .css, .js, .ts).

    Args:
        attachment: Objet Attachment de discord.py.

    Returns:
        Le texte extrait, ou None si le format n'est pas supporté,
        le fichier est trop volumineux, ou l'extraction a échoué.
    """
    filename = attachment.filename
    ext = Path(filename).suffix.lower()

    # Vérifier que le format est supporté
    if not is_supported_attachment(filename):
        logger.info(
            "ℹ️ Format non supporté pour '%s' (ext=%s).",
            filename, ext,
        )
        return None

    # Télécharger le fichier
    data = await _download_attachment(attachment)
    if data is None:
        return None

    # Extraire le texte selon le type de fichier
    if ext == ".pdf":
        text = _extract_text_from_pdf(data)
    elif ext in _IMAGE_EXTENSIONS:
        text = await _describe_image_with_llm(data, filename)
    elif ext in _TEXT_EXTENSIONS:
        text = _extract_text_from_text_file(data, filename)
    else:
        logger.warning("⚠️ Extension '%s' non gérée.", ext)
        return None

    if text:
        logger.info(
            "✅ Texte extrait de '%s' : %d caractères.", filename, len(text)
        )
    else:
        logger.warning("⚠️ Aucun texte extrait de '%s'.", filename)

    return text


async def _describe_image_with_llm(data: bytes, filename: str) -> str | None:
    """
    Décrit une image via le LLM vision (Gemini Flash).

    Args:
        data: Contenu brut de l'image en bytes.
        filename: Nom du fichier image.

    Returns:
        Description textuelle de l'image, ou None en cas d'erreur.
    """
    from services.openrouter_client import describe_image

    try:
        description = await describe_image(data, filename)
        if description:
            logger.info(
                "🖼️ Image '%s' décrite par le LLM (%d caractères).",
                filename, len(description),
            )
            return f"[Image : {filename}]\n{description}"
        return None
    except Exception as e:
        logger.error("❌ Erreur description image '%s' : %s", filename, e)
        return None
