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
            timestamp_str = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
            indexed_files = []
            total_chunks_count = 0

            # ── 1. Indexer le texte principal si présent ──
            if message.content and message.content.strip():
                full_text = build_document_text(
                    category=category,
                    title=title,
                    content=content,
                    author=str(message.author),
                    channel=message.channel.name,
                    timestamp=timestamp_str,
                )
                chunks = chunk_text(full_text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
                embeddings = await get_embedding(chunks)
                ids = [generate_doc_id(f"{message.id}_msg", idx) for idx in range(len(chunks))]
                metadatas = [
                    {
                        "message_id": str(message.id),
                        "channel_id": str(message.channel.id),
                        "author": str(message.author),
                        "category": category,
                        "title": title,
                        "timestamp": timestamp_str,
                        "has_attachment": False,
                        "attachment_name": None,
                        "attachment_url": None,
                        "file_type": "text",
                        "file_ext": "",
                        "source": "discord_message",
                        "page_or_sheet_count": 1,
                        "chunk_index": idx,
                        "total_chunks": len(chunks),
                    }
                    for idx in range(len(chunks))
                ]
                self.vector_store.add_documents(texts=chunks, metadatas=metadatas, ids=ids, embeddings=embeddings)
                total_chunks_count += len(chunks)

            # ── 2. Indexer CHAQUE pièce jointe individuellement avec son propre ID et sa propre URL ──
            if message.attachments:
                for att_idx, attachment in enumerate(message.attachments):
                    if is_supported_attachment(attachment.filename):
                        details = await extract_attachment_details(attachment)
                        if details and details.get("text"):
                            att_title = f"{title} - {attachment.filename}" if message.content else attachment.filename
                            att_full_text = build_document_text(
                                category=category,
                                title=att_title,
                                content=details["text"],
                                author=str(message.author),
                                channel=message.channel.name,
                                timestamp=timestamp_str,
                            )
                            chunks = chunk_text(att_full_text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
                            embeddings = await get_embedding(chunks)
                            ids = [generate_doc_id(f"{message.id}_att{att_idx}", idx) for idx in range(len(chunks))]
                            metadatas = [
                                {
                                    "message_id": str(message.id),
                                    "channel_id": str(message.channel.id),
                                    "author": str(message.author),
                                    "category": category,
                                    "title": att_title,
                                    "timestamp": timestamp_str,
                                    "has_attachment": True,
                                    "attachment_name": attachment.filename,
                                    "attachment_url": attachment.url,
                                    "file_type": details.get("file_type", "attachment"),
                                    "file_ext": details.get("file_ext", Path(attachment.filename).suffix.lower()),
                                    "source": attachment.filename,
                                    "page_or_sheet_count": details.get("page_or_sheet_count", 1),
                                    "chunk_index": idx,
                                    "total_chunks": len(chunks),
                                }
                                for idx in range(len(chunks))
                            ]
                            self.vector_store.add_documents(texts=chunks, metadatas=metadatas, ids=ids, embeddings=embeddings)
                            indexed_files.append(attachment.filename)
                            total_chunks_count += len(chunks)

            # ── Confirmation visuelle ──
            await message.add_reaction("✅")
            info_str = f" (**{', '.join(indexed_files)}**)" if indexed_files else ""
            await message.reply(
                f"📄 Indexé : **{title}**{info_str} — {total_chunks_count} chunk(s)",
                delete_after=15,
            )
            logger.info(
                "Message %s indexé : '%s' (%d fichier(s)) — %d chunk(s)",
                message.id, title, len(indexed_files), total_chunks_count,
            )

        except Exception as exc:
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
            timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            indexed_files = []
            total_chunks_count = 0
            base_id = int(interaction.id)

            # ── 1. Indexer la description textuelle si présente ──
            if description and description.strip():
                full_text = build_document_text(
                    category=sujet,
                    title=titre,
                    content=description,
                    author=str(interaction.user),
                    channel=interaction.channel.name if interaction.channel else "inconnu",
                    timestamp=timestamp_str,
                )
                chunks = chunk_text(full_text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
                embeddings = await get_embedding(chunks)
                ids = [generate_doc_id(f"{base_id}_desc", idx) for idx in range(len(chunks))]
                metadatas = [
                    {
                        "message_id": str(interaction.id),
                        "channel_id": str(interaction.channel_id),
                        "author": str(interaction.user),
                        "category": sujet,
                        "title": titre,
                        "timestamp": timestamp_str,
                        "has_attachment": False,
                        "attachment_name": None,
                        "attachment_url": None,
                        "file_type": "text",
                        "file_ext": "",
                        "source": "slash_command",
                        "page_or_sheet_count": 1,
                        "chunk_index": idx,
                        "total_chunks": len(chunks),
                    }
                    for idx in range(len(chunks))
                ]
                self.vector_store.add_documents(texts=chunks, metadatas=metadatas, ids=ids, embeddings=embeddings)
                total_chunks_count += len(chunks)

            # ── 2. Indexer CHAQUE pièce jointe individuellement ──
            if fichiers:
                for att_idx, fichier in enumerate(fichiers):
                    if is_supported_attachment(fichier.filename):
                        details = await extract_attachment_details(fichier)
                        if details and details.get("text"):
                            att_title = f"{titre} - {fichier.filename}" if description else f"{titre} ({fichier.filename})"
                            att_full_text = build_document_text(
                                category=sujet,
                                title=att_title,
                                content=details["text"],
                                author=str(interaction.user),
                                channel=interaction.channel.name if interaction.channel else "inconnu",
                                timestamp=timestamp_str,
                            )
                            chunks = chunk_text(att_full_text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
                            embeddings = await get_embedding(chunks)
                            ids = [generate_doc_id(f"{base_id}_att{att_idx}", idx) for idx in range(len(chunks))]
                            metadatas = [
                                {
                                    "message_id": str(interaction.id),
                                    "channel_id": str(interaction.channel_id),
                                    "author": str(interaction.user),
                                    "category": sujet,
                                    "title": att_title,
                                    "timestamp": timestamp_str,
                                    "has_attachment": True,
                                    "attachment_name": fichier.filename,
                                    "attachment_url": fichier.url,
                                    "file_type": details.get("file_type", "attachment"),
                                    "file_ext": details.get("file_ext", Path(fichier.filename).suffix.lower()),
                                    "source": fichier.filename,
                                    "page_or_sheet_count": details.get("page_or_sheet_count", 1),
                                    "chunk_index": idx,
                                    "total_chunks": len(chunks),
                                }
                                for idx in range(len(chunks))
                            ]
                            self.vector_store.add_documents(texts=chunks, metadatas=metadatas, ids=ids, embeddings=embeddings)
                            indexed_files.append(fichier.filename)
                            total_chunks_count += len(chunks)

            embed = discord.Embed(
                title=f"📄 {sujet} indexé(e)",
                color=0x5865F2,
            )
            embed.add_field(name="📝 Titre", value=titre, inline=False)
            if description:
                embed.add_field(name="📄 Description", value=description[:300], inline=False)
            if indexed_files:
                embed.add_field(name="📎 Fichier(s) joint(s)", value=", ".join(indexed_files), inline=True)
            embed.set_footer(text=f"{total_chunks_count} chunk(s) • Par {interaction.user.display_name}")

            await interaction.followup.send(embed=embed)
            logger.info(
                "/add : '%s' indexé avec %d fichier(s) — %d chunk(s) par %s",
                titre, len(indexed_files), total_chunks_count, interaction.user,
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
        fichier2="2ème fichier joint (optionnel)",
        fichier3="3ème fichier joint (optionnel)",
        fichier4="4ème fichier joint (optionnel)",
        fichier5="5ème fichier joint (optionnel)",
        fichier6="6ème fichier joint (optionnel)",
        fichier7="7ème fichier joint (optionnel)",
        fichier8="8ème fichier joint (optionnel)",
        fichier9="9ème fichier joint (optionnel)",
        fichier10="10ème fichier joint (optionnel)",
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
        fichier4: discord.Attachment | None = None,
        fichier5: discord.Attachment | None = None,
        fichier6: discord.Attachment | None = None,
        fichier7: discord.Attachment | None = None,
        fichier8: discord.Attachment | None = None,
        fichier9: discord.Attachment | None = None,
        fichier10: discord.Attachment | None = None,
        categorie: str = "Général",
    ) -> None:
        await interaction.response.defer(thinking=True)
        fichiers = [
            f for f in (
                fichier, fichier2, fichier3, fichier4, fichier5,
                fichier6, fichier7, fichier8, fichier9, fichier10
            ) if f is not None
        ]
        await self._index_info(interaction, categorie, titre, description, fichiers)


async def setup(bot: commands.Bot) -> None:
    """Point d'entrée pour charger le cog d'indexation."""
    await bot.add_cog(IndexerCog(bot))
