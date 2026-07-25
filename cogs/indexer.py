"""
Cog d'indexation — Écoute les messages du canal d'entrée,
parse le format structuré, découpe en chunks et stocke dans ChromaDB.
"""

import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

from pathlib import Path

from config import load_channels_config, CHUNK_SIZE, CHUNK_OVERLAP
from services.chunker import (
    parse_indexed_message,
    chunk_text,
    build_document_text,
    generate_doc_id,
)
from services.openrouter_client import get_embedding
from services.vectorstore import VectorStore
from services.attachments import (
    extract_text_from_attachment,
    extract_attachment_details,
    is_supported_attachment,
)

logger = logging.getLogger(__name__)

# Message d'aide envoyé quand le format est incorrect
FORMAT_REMINDER = (
    "❌ **Format attendu :**\n"
    "```\n"
    "[Catégorie] Titre du document\n"
    "Contenu du message...\n"
    "```"
)


class IndexerCog(commands.Cog):
    """Cog responsable de l'indexation des messages dans le canal d'entrée."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialise le cog avec une référence au bot et le VectorStore."""
        self.bot = bot
        self.vector_store = VectorStore()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        Écoute tous les messages entrants.
        Indexe uniquement ceux du canal d'entrée qui respectent le format attendu.
        """
        # ── Ignorer les bots ──
        if message.author.bot:
            return

        # ── Vérifier que le message est dans le canal d'entrée configuré ──
        channels_config = load_channels_config()
        input_channel_id = channels_config.get("input_channel_id")

        if input_channel_id is None or message.channel.id != input_channel_id:
            return

        # ── Parser le message (avec fallback automatique si pas de catégorie) ──
        parsed = parse_indexed_message(message.content)

        if parsed:
            category: str = parsed["category"]
            title: str = parsed["title"]
            content: str = parsed["content"]
        elif message.attachments:
            category: str = "Général"
            title: str = message.attachments[0].filename
            content: str = message.content or message.attachments[0].filename
        else:
            return

        try:
            # ── Traitement des pièces jointes ──
            file_type = "text"
            file_ext = ""
            source = "discord_message"
            page_or_sheet_count = 1
            attachment_name = None
            attachment_url = None

            if message.attachments:
                for attachment in message.attachments:
                    if attachment_name is None:
                        attachment_name = attachment.filename
                        attachment_url = attachment.url
                        source = attachment.filename
                        file_ext = Path(attachment.filename).suffix.lower()
                    if is_supported_attachment(attachment.filename):
                        details = await extract_attachment_details(attachment)
                        if details:
                            content += f"\n\n--- Pièce jointe : {attachment.filename} ---\n{details['text']}"
                            file_type = details.get("file_type", file_type)
                            file_ext = details.get("file_ext", file_ext)
                            page_or_sheet_count = details.get("page_or_sheet_count", page_or_sheet_count)

            # ── Construction du texte complet du document ──
            timestamp_str = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
            full_text = build_document_text(
                category=category,
                title=title,
                content=content,
                author=str(message.author),
                channel=message.channel.name,
                timestamp=timestamp_str,
            )

            # ── Découpage en chunks si nécessaire ──
            chunks = chunk_text(full_text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)

            # ── Génération des embeddings ──
            embeddings = await get_embedding(chunks)

            # ── Préparation des métadonnées et IDs pour chaque chunk ──
            ids: list[str] = []
            metadatas: list[dict] = []

            for idx, _chunk in enumerate(chunks):
                doc_id = generate_doc_id(message.id, chunk_index=idx)
                ids.append(doc_id)
                metadatas.append({
                    "message_id": str(message.id),
                    "channel_id": str(message.channel.id),
                    "author": str(message.author),
                    "category": category,
                    "title": title,
                    "timestamp": timestamp_str,
                    "has_attachment": bool(message.attachments),
                    "attachment_name": attachment_name,
                    "attachment_url": attachment_url,
                    "file_type": file_type,
                    "file_ext": file_ext,
                    "source": source,
                    "page_or_sheet_count": page_or_sheet_count,
                    "chunk_index": idx,
                    "total_chunks": len(chunks),
                })

            # ── Stockage dans ChromaDB ──
            self.vector_store.add_documents(
                texts=chunks,
                metadatas=metadatas,
                ids=ids,
                embeddings=embeddings,
            )

            # ── Confirmation visuelle ──
            await message.add_reaction("✅")
            await message.reply(
                f"📄 Indexé : **{title}** [{category}] — {len(chunks)} chunk(s)",
                delete_after=15,
            )
            logger.info(
                "Message %s indexé : '%s' [%s] — %d chunk(s)",
                message.id, title, category, len(chunks),
            )

        except Exception as exc:
            # ── Gestion d'erreur : signaler visuellement et loguer ──
            logger.error("Erreur lors de l'indexation du message %s : %s", message.id, exc, exc_info=True)
            try:
                await message.add_reaction("⚠️")
                await message.reply(
                    f"⚠️ Erreur lors de l'indexation : `{exc}`",
                    delete_after=30,
                )
            except discord.HTTPException:
                pass

    # ─────────────────────────────────────────────
    #  Méthode interne partagée pour l'indexation
    # ─────────────────────────────────────────────

    async def _index_info(
        self,
        interaction: discord.Interaction,
        sujet: str,
        titre: str,
        description: str,
        fichiers: list[discord.Attachment] | None = None,
    ) -> None:
        """Logique commune d'indexation pour toutes les commandes slash."""
        try:
            content = description

            # ── Traitement des pièces jointes ──
            file_type = "text"
            file_ext = ""
            source = "discord_message"
            page_or_sheet_count = 1
            attachment_name = None
            attachment_url = None
            processed_files = []

            if fichiers:
                for fichier in fichiers:
                    if attachment_name is None:
                        attachment_name = fichier.filename
                        attachment_url = fichier.url
                        source = fichier.filename
                        file_ext = Path(fichier.filename).suffix.lower()
                    if is_supported_attachment(fichier.filename):
                        details = await extract_attachment_details(fichier)
                        if details:
                            content += f"\n\n--- Pièce jointe : {fichier.filename} ---\n{details['text']}"
                            file_type = details.get("file_type", file_type)
                            file_ext = details.get("file_ext", file_ext)
                            page_or_sheet_count = details.get("page_or_sheet_count", page_or_sheet_count)
                            processed_files.append(fichier.filename)
                    else:
                        logger.warning("Format non supporté ignoré dans /add : %s", fichier.filename)

            # ── Construction du texte complet ──
            timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            full_text = build_document_text(
                category=sujet,
                title=titre,
                content=content,
                author=str(interaction.user),
                channel=interaction.channel.name if interaction.channel else "inconnu",
                timestamp=timestamp_str,
            )

            # ── Découpage en chunks ──
            chunks = chunk_text(full_text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)

            # ── Génération des embeddings ──
            embeddings = await get_embedding(chunks)

            # ── Préparation des métadonnées et IDs ──
            base_id = int(interaction.id)
            ids: list[str] = []
            metadatas: list[dict] = []

            for idx, _chunk in enumerate(chunks):
                doc_id = generate_doc_id(base_id, chunk_index=idx)
                ids.append(doc_id)
                metadatas.append({
                    "message_id": str(interaction.id),
                    "channel_id": str(interaction.channel_id),
                    "author": str(interaction.user),
                    "category": sujet,
                    "title": titre,
                    "timestamp": timestamp_str,
                    "has_attachment": bool(processed_files),
                    "attachment_name": attachment_name,
                    "attachment_url": attachment_url,
                    "file_type": file_type,
                    "file_ext": file_ext,
                    "source": source,
                    "page_or_sheet_count": page_or_sheet_count,
                    "chunk_index": idx,
                    "total_chunks": len(chunks),
                })

            # ── Stockage dans Qdrant ──
            self.vector_store.add_documents(
                texts=chunks,
                metadatas=metadatas,
                ids=ids,
                embeddings=embeddings,
            )

            embed = discord.Embed(
                title=f"📄 {sujet} indexé(e)",
                color=0x5865F2,
            )
            embed.add_field(name="📝 Titre", value=titre, inline=False)
            if description:
                embed.add_field(name="📄 Description", value=description[:300], inline=False)
            if processed_files:
                embed.add_field(name="📎 Fichier(s) joint(s)", value=", ".join(processed_files), inline=True)
            embed.set_footer(text=f"{len(chunks)} chunk(s) • Par {interaction.user.display_name}")

            await interaction.followup.send(embed=embed)
            logger.info(
                "/add : '%s' indexé avec %d fichier(s) — %d chunk(s) par %s",
                titre, len(processed_files), len(chunks), interaction.user,
            )

        except Exception as exc:
            logger.error("Erreur indexation /add : %s", exc, exc_info=True)
            await interaction.followup.send(
                f"⚠️ Erreur lors de l'indexation : `{exc}`",
                ephemeral=True,
            )

    # ─────────────────────────────────────────────
    #  Commande slash universelle d'indexation
    # ─────────────────────────────────────────────

    @discord.app_commands.command(
        name="add",
        description="➕ Ajouter un document, une note ou des fichiers à la base RAG",
    )
    @discord.app_commands.describe(
        titre="Le titre ou résumé du document",
        description="Le contenu textuel (optionnel si un fichier est joint)",
        fichier="Premier fichier joint (PDF, Word, Excel, Python, image, etc. - optionnel)",
        fichier2="Deuxième fichier joint (optionnel)",
        fichier3="Troisième fichier joint (optionnel)",
        categorie="Catégorie (Optionnel - Défaut: Général)",
    )
    async def add_command(
        self,
        interaction: discord.Interaction,
        titre: str,
        description: str = "",
        fichier: discord.Attachment | None = None,
        fichier2: discord.Attachment | None = None,
        fichier3: discord.Attachment | None = None,
        categorie: str = "Général",
    ) -> None:
        await interaction.response.defer(thinking=True)
        fichiers = [f for f in (fichier, fichier2, fichier3) if f is not None]
        await self._index_info(interaction, categorie, titre, description, fichiers)


async def setup(bot: commands.Bot) -> None:
    """Point d'entrée pour charger le cog d'indexation."""
    await bot.add_cog(IndexerCog(bot))
