"""
Cog d'indexation — Écoute les messages du canal d'entrée,
parse le format structuré, découpe en chunks et stocke dans ChromaDB.
"""

import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

from config import load_channels_config, CHUNK_SIZE, CHUNK_OVERLAP
from services.chunker import (
    parse_indexed_message,
    chunk_text,
    build_document_text,
    generate_doc_id,
)
from services.openrouter_client import get_embedding
from services.vectorstore import VectorStore
from services.attachments import extract_text_from_attachment, is_supported_attachment

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

        # ── Parser le message structuré ──
        parsed = parse_indexed_message(message.content)

        if parsed is None:
            # Format incorrect : réagir et envoyer un rappel
            try:
                await message.add_reaction("❌")
                await message.reply(FORMAT_REMINDER, delete_after=30)
            except discord.HTTPException as exc:
                logger.warning("Impossible de réagir/répondre au message %s : %s", message.id, exc)
            return

        # ── Extraction des données parsées ──
        category: str = parsed["category"]
        title: str = parsed["title"]
        content: str = parsed["content"]

        try:
            # ── Traitement des pièces jointes ──
            if message.attachments:
                for attachment in message.attachments:
                    if is_supported_attachment(attachment.filename):
                        extracted = await extract_text_from_attachment(attachment)
                        if extracted:
                            content += f"\n\n--- Pièce jointe : {attachment.filename} ---\n{extracted}"

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

    @discord.app_commands.command(
        name="type",
        description="Indexer une information dans la base de connaissances",
    )
    @discord.app_commands.describe(
        sujet="Le sujet / catégorie de l'information (ex: Documentation, Procédure, Note...)",
        titre="Le titre de l'information",
        description="Une description courte du contenu",
        fichier="Un fichier à joindre (PDF, image, texte...)",
    )
    async def type_command(
        self,
        interaction: discord.Interaction,
        sujet: str,
        titre: str,
        description: str,
        fichier: discord.Attachment | None = None,
    ) -> None:
        """Commande slash pour indexer une information avec titre, sujet et description."""
        await interaction.response.defer(thinking=True)

        try:
            content = description

            # ── Traitement du fichier joint ──
            if fichier is not None:
                if is_supported_attachment(fichier.filename):
                    extracted = await extract_text_from_attachment(fichier)
                    if extracted:
                        content += f"\n\n--- Pièce jointe : {fichier.filename} ---\n{extracted}"
                else:
                    await interaction.followup.send(
                        f"⚠️ Format de fichier non supporté : `{fichier.filename}`",
                        ephemeral=True,
                    )
                    return

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
            # Utiliser un ID unique basé sur le timestamp et l'interaction
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
                    "has_attachment": fichier is not None,
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

            # ── Confirmation ──
            embed = discord.Embed(
                title="✅ Information indexée",
                color=0x57F287,
            )
            embed.add_field(name="📁 Sujet", value=sujet, inline=True)
            embed.add_field(name="📝 Titre", value=titre, inline=True)
            embed.add_field(name="📄 Description", value=description[:200], inline=False)
            if fichier:
                embed.add_field(name="📎 Fichier", value=fichier.filename, inline=True)
            embed.set_footer(text=f"{len(chunks)} chunk(s) • Par {interaction.user.display_name}")

            await interaction.followup.send(embed=embed)
            logger.info(
                "Commande /type : '%s' [%s] indexé — %d chunk(s) par %s",
                titre, sujet, len(chunks), interaction.user,
            )

        except Exception as exc:
            logger.error("Erreur /type : %s", exc, exc_info=True)
            await interaction.followup.send(
                f"⚠️ Erreur lors de l'indexation : `{exc}`",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    """Point d'entrée pour charger le cog d'indexation."""
    await bot.add_cog(IndexerCog(bot))
