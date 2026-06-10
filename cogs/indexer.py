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

    # ─────────────────────────────────────────────
    #  Méthode interne partagée pour l'indexation
    # ─────────────────────────────────────────────

    async def _index_info(
        self,
        interaction: discord.Interaction,
        sujet: str,
        titre: str,
        description: str,
        fichier: discord.Attachment | None = None,
    ) -> None:
        """Logique commune d'indexation pour toutes les commandes slash."""
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

            # ── Couleurs par sujet ──
            colors = {
                "Note": 0xFEE75C,        # Jaune
                "Documentation": 0x5865F2, # Bleu Discord
                "Procédure": 0xEB459E,     # Rose
                "Tutoriel": 0x57F287,      # Vert
                "Info": 0xED4245,          # Rouge
            }
            icons = {
                "Note": "📝",
                "Documentation": "📚",
                "Procédure": "📋",
                "Tutoriel": "🎓",
                "Info": "ℹ️",
            }

            embed = discord.Embed(
                title=f"{icons.get(sujet, '📄')} {sujet} indexé(e)",
                color=colors.get(sujet, 0x5865F2),
            )
            embed.add_field(name="📝 Titre", value=titre, inline=False)
            embed.add_field(name="📄 Description", value=description[:300], inline=False)
            if fichier:
                embed.add_field(name="📎 Fichier", value=fichier.filename, inline=True)
            embed.set_footer(text=f"{len(chunks)} chunk(s) • Par {interaction.user.display_name}")

            await interaction.followup.send(embed=embed)
            logger.info(
                "/%s : '%s' indexé — %d chunk(s) par %s",
                sujet.lower(), titre, len(chunks), interaction.user,
            )

        except Exception as exc:
            logger.error("Erreur indexation /%s : %s", sujet.lower(), exc, exc_info=True)
            await interaction.followup.send(
                f"⚠️ Erreur lors de l'indexation : `{exc}`",
                ephemeral=True,
            )

    # ─────────────────────────────────────────────
    #  Commandes slash par catégorie
    # ─────────────────────────────────────────────

    @discord.app_commands.command(name="note", description="📝 Ajouter une note à la base de connaissances")
    @discord.app_commands.describe(
        titre="Le titre de la note",
        description="Le contenu de la note",
        fichier="Un fichier à joindre (PDF, image, texte...)",
    )
    async def note_command(self, interaction: discord.Interaction, titre: str, description: str, fichier: discord.Attachment | None = None) -> None:
        await self._index_info(interaction, "Note", titre, description, fichier)

    @discord.app_commands.command(name="doc", description="📚 Ajouter une documentation à la base de connaissances")
    @discord.app_commands.describe(
        titre="Le titre du document",
        description="Le contenu / résumé du document",
        fichier="Un fichier à joindre (PDF, image, texte...)",
    )
    async def doc_command(self, interaction: discord.Interaction, titre: str, description: str, fichier: discord.Attachment | None = None) -> None:
        await self._index_info(interaction, "Documentation", titre, description, fichier)

    @discord.app_commands.command(name="procedure", description="📋 Ajouter une procédure à la base de connaissances")
    @discord.app_commands.describe(
        titre="Le titre de la procédure",
        description="Les étapes / le contenu de la procédure",
        fichier="Un fichier à joindre (PDF, image, texte...)",
    )
    async def procedure_command(self, interaction: discord.Interaction, titre: str, description: str, fichier: discord.Attachment | None = None) -> None:
        await self._index_info(interaction, "Procédure", titre, description, fichier)

    @discord.app_commands.command(name="tuto", description="🎓 Ajouter un tutoriel à la base de connaissances")
    @discord.app_commands.describe(
        titre="Le titre du tutoriel",
        description="Le contenu du tutoriel",
        fichier="Un fichier à joindre (PDF, image, texte...)",
    )
    async def tuto_command(self, interaction: discord.Interaction, titre: str, description: str, fichier: discord.Attachment | None = None) -> None:
        await self._index_info(interaction, "Tutoriel", titre, description, fichier)

    @discord.app_commands.command(name="info", description="ℹ️ Ajouter une info à la base de connaissances")
    @discord.app_commands.describe(
        titre="Le titre de l'information",
        description="Le contenu de l'information",
        fichier="Un fichier à joindre (PDF, image, texte...)",
    )
    async def info_command(self, interaction: discord.Interaction, titre: str, description: str, fichier: discord.Attachment | None = None) -> None:
        await self._index_info(interaction, "Info", titre, description, fichier)


async def setup(bot: commands.Bot) -> None:
    """Point d'entrée pour charger le cog d'indexation."""
    await bot.add_cog(IndexerCog(bot))
