"""
Cog d'administration — Commandes de configuration, de statut et de réindexation.
Toutes les commandes (sauf /help_format) nécessitent la permission manage_guild.
"""

import logging
import time
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from config import (
    load_channels_config,
    save_channels_config,
    LLM_MODEL,
    EMBEDDING_MODEL,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
)
from services.chunker import (
    parse_indexed_message,
    chunk_text,
    build_document_text,
    generate_doc_id,
)
from services.openrouter_client import get_embedding
from services.vectorstore import VectorStore

logger = logging.getLogger(__name__)

# Couleur Discord « blurple »
BLURPLE = 0x5865F2


class AdminCog(commands.Cog):
    """Cog d'administration pour la configuration et la maintenance du bot RAG."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialise le cog avec une référence au bot et le VectorStore."""
        self.bot = bot
        self.vector_store = VectorStore()
        self.start_time = time.time()

    # ─────────────────────────────────────────────
    #  /setup — Configuration des canaux
    # ─────────────────────────────────────────────
    @app_commands.command(
        name="setup",
        description="Configurer les canaux d'entrée (indexation) et de sortie (Q&A).",
    )
    @app_commands.describe(
        input_channel="Canal d'entrée pour l'indexation des documents",
        output_channel="Canal de sortie pour les questions/réponses RAG",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup(
        self,
        interaction: discord.Interaction,
        input_channel: discord.TextChannel,
        output_channel: discord.TextChannel,
    ) -> None:
        """Configure les canaux d'entrée et de sortie du bot."""
        # ── Sauvegarder la configuration ──
        save_channels_config(input_channel.id, output_channel.id)

        # ── Embed de confirmation ──
        embed = discord.Embed(
            title="⚙️ Configuration mise à jour",
            color=BLURPLE,
        )
        embed.add_field(
            name="📥 Canal d'entrée (indexation)",
            value=f"{input_channel.mention}",
            inline=True,
        )
        embed.add_field(
            name="📤 Canal de sortie (Q&A)",
            value=f"{output_channel.mention}",
            inline=True,
        )
        embed.set_footer(text="Configuration sauvegardée avec succès.")
        await interaction.response.send_message(embed=embed)

        # ── Messages de bienvenue dans les canaux ──
        try:
            welcome_input = discord.Embed(
                title="📥 Canal d'indexation configuré",
                description=(
                    "Ce canal est maintenant configuré pour l'indexation.\n\n"
                    "**Format attendu :**\n"
                    "```\n"
                    "[Catégorie] Titre du document\n"
                    "Contenu du message...\n"
                    "```\n\n"
                    "Utilisez `/help_format` pour plus de détails."
                ),
                color=discord.Color.green(),
            )
            await input_channel.send(embed=welcome_input)
        except discord.HTTPException as exc:
            logger.warning("Impossible d'envoyer le message de bienvenue dans %s : %s", input_channel, exc)

        try:
            welcome_output = discord.Embed(
                title="📤 Canal Q&A configuré",
                description=(
                    "Ce canal est maintenant configuré pour les questions/réponses.\n\n"
                    "**Comment l'utiliser :**\n"
                    "• Tapez votre question directement ici\n"
                    "• Ou utilisez la commande `/ask`\n\n"
                    "Le bot recherchera dans les documents indexés et "
                    "vous fournira une réponse intelligente. 🤖"
                ),
                color=discord.Color.blue(),
            )
            await output_channel.send(embed=welcome_output)
        except discord.HTTPException as exc:
            logger.warning("Impossible d'envoyer le message de bienvenue dans %s : %s", output_channel, exc)

    # ─────────────────────────────────────────────
    #  /status — État du bot
    # ─────────────────────────────────────────────
    @app_commands.command(
        name="status",
        description="Afficher l'état actuel du bot RAG (documents, canaux, uptime…).",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction) -> None:
        """Affiche un résumé de l'état du bot."""
        await interaction.response.defer(thinking=True)

        # ── Statistiques du VectorStore ──
        stats = self.vector_store.get_stats()

        # ── Configuration des canaux ──
        channels_config = load_channels_config()
        input_id = channels_config.get("input_channel_id")
        output_id = channels_config.get("output_channel_id")
        input_mention = f"<#{input_id}>" if input_id else "❌ Non configuré"
        output_mention = f"<#{output_id}>" if output_id else "❌ Non configuré"

        # ── Calcul de l'uptime ──
        uptime_seconds = int(time.time() - self.start_time)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        # ── Construction de l'embed ──
        embed = discord.Embed(
            title="📊 État du Bot RAG",
            color=BLURPLE,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="📚 Documents indexés",
            value=f"`{stats.get('total_documents', 0)}`",
            inline=True,
        )
        embed.add_field(
            name="⏱️ Uptime",
            value=f"`{uptime_str}`",
            inline=True,
        )
        embed.add_field(
            name="🤖 Modèle LLM",
            value=f"`{LLM_MODEL}`",
            inline=False,
        )
        embed.add_field(
            name="🔢 Modèle d'embedding",
            value=f"`{EMBEDDING_MODEL}`",
            inline=True,
        )
        embed.add_field(
            name="📥 Canal d'entrée",
            value=input_mention,
            inline=True,
        )
        embed.add_field(
            name="📤 Canal de sortie",
            value=output_mention,
            inline=True,
        )
        embed.add_field(
            name="⚙️ Paramètres RAG",
            value=f"Chunk : `{CHUNK_SIZE}` | Overlap : `{CHUNK_OVERLAP}`",
            inline=False,
        )
        embed.set_footer(text=f"Serveurs : {len(self.bot.guilds)}")

        await interaction.followup.send(embed=embed)

    # ─────────────────────────────────────────────
    #  /reindex — Réindexation d'un canal
    # ─────────────────────────────────────────────
    @app_commands.command(
        name="reindex",
        description="Réindexer l'historique d'un canal (supprime les anciens documents du canal).",
    )
    @app_commands.describe(
        channel="Le canal dont l'historique doit être réindexé",
        limit="Nombre maximum de messages à parcourir (défaut : 200)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reindex(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        limit: int = 200,
    ) -> None:
        """Réindexe l'historique d'un canal en supprimant les anciens documents."""
        await interaction.response.defer(thinking=True)

        # ── Message de progression ──
        progress_embed = discord.Embed(
            title="🔄 Réindexation en cours…",
            description=f"Canal : {channel.mention}\nAnalyse de l'historique…",
            color=discord.Color.orange(),
        )
        progress_msg = await interaction.followup.send(embed=progress_embed, wait=True)

        try:
            # ── Suppression des anciens documents du canal ──
            self.vector_store.delete_by_metadata("channel_id", str(channel.id))

            # ── Parcours de l'historique ──
            indexed = 0
            skipped = 0
            errors = 0
            total_processed = 0

            async for message in channel.history(limit=limit, oldest_first=True):
                total_processed += 1

                # Ignorer les bots
                if message.author.bot:
                    skipped += 1
                    continue

                # Parser le message
                parsed = parse_indexed_message(message.content)
                if parsed is None:
                    skipped += 1
                    continue

                try:
                    category = parsed["category"]
                    title = parsed["title"]
                    content = parsed["content"]

                    # Construction du texte
                    timestamp_str = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
                    full_text = build_document_text(
                        category=category,
                        title=title,
                        content=content,
                        author=str(message.author),
                        channel=channel.name,
                        timestamp=timestamp_str,
                    )

                    # Chunks + embeddings
                    chunks = chunk_text(full_text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
                    embeddings = await get_embedding(chunks)

                    ids = [generate_doc_id(message.id, idx) for idx in range(len(chunks))]
                    metadatas = [
                        {
                            "message_id": str(message.id),
                            "channel_id": str(channel.id),
                            "author": str(message.author),
                            "category": category,
                            "title": title,
                            "timestamp": timestamp_str,
                            "has_attachment": bool(message.attachments),
                            "chunk_index": idx,
                            "total_chunks": len(chunks),
                        }
                        for idx in range(len(chunks))
                    ]

                    self.vector_store.add_documents(
                        texts=chunks,
                        metadatas=metadatas,
                        ids=ids,
                        embeddings=embeddings,
                    )
                    indexed += 1

                except Exception as exc:
                    logger.warning("Erreur lors de la réindexation du message %s : %s", message.id, exc)
                    errors += 1

                # ── Mise à jour de la progression toutes les 20 messages ──
                if total_processed % 20 == 0:
                    progress_embed.description = (
                        f"Canal : {channel.mention}\n"
                        f"Progression : `{total_processed}` messages analysés\n"
                        f"✅ Indexés : `{indexed}` | ⏭️ Ignorés : `{skipped}` | ⚠️ Erreurs : `{errors}`"
                    )
                    await progress_msg.edit(embed=progress_embed)

            # ── Résultat final ──
            result_embed = discord.Embed(
                title="✅ Réindexation terminée",
                color=discord.Color.green(),
            )
            result_embed.add_field(name="📋 Canal", value=channel.mention, inline=True)
            result_embed.add_field(name="📝 Messages analysés", value=f"`{total_processed}`", inline=True)
            result_embed.add_field(name="✅ Indexés", value=f"`{indexed}`", inline=True)
            result_embed.add_field(name="⏭️ Ignorés", value=f"`{skipped}`", inline=True)
            result_embed.add_field(name="⚠️ Erreurs", value=f"`{errors}`", inline=True)

            await progress_msg.edit(embed=result_embed)

        except Exception as exc:
            logger.error("Erreur critique lors de la réindexation : %s", exc, exc_info=True)
            error_embed = discord.Embed(
                title="❌ Erreur de réindexation",
                description=f"Une erreur est survenue : `{exc}`",
                color=discord.Color.red(),
            )
            await progress_msg.edit(embed=error_embed)

    # ─────────────────────────────────────────────
    #  /help_format — Aide sur le format d'indexation
    # ─────────────────────────────────────────────
    @app_commands.command(
        name="help_format",
        description="Afficher le format attendu pour l'indexation des documents.",
    )
    async def help_format(self, interaction: discord.Interaction) -> None:
        """Affiche un guide détaillé du format d'indexation avec des exemples."""
        embed = discord.Embed(
            title="📖 Guide du format d'indexation",
            description=(
                "Pour indexer un document, envoyez un message dans le canal d'entrée "
                "en respectant le format suivant :"
            ),
            color=BLURPLE,
        )

        embed.add_field(
            name="📝 Format",
            value=(
                "```\n"
                "[Catégorie] Titre du document\n"
                "Contenu du message…\n"
                "```"
            ),
            inline=False,
        )

        embed.add_field(
            name="📄 Exemple 1 — Documentation",
            value=(
                "```\n"
                "[Documentation] Guide Docker\n"
                "Pour installer Docker sur Ubuntu :\n"
                "1. Mettre à jour les paquets\n"
                "2. Installer les dépendances\n"
                "3. Ajouter le dépôt Docker\n"
                "```"
            ),
            inline=False,
        )

        embed.add_field(
            name="🔧 Exemple 2 — Procédure",
            value=(
                "```\n"
                "[Procédure] Déploiement production\n"
                "Étapes pour déployer l'application en production :\n"
                "1. Builder le projet avec npm run build\n"
                "2. Lancer les tests\n"
                "3. Déployer sur le serveur\n"
                "```"
            ),
            inline=False,
        )

        embed.add_field(
            name="❓ Exemple 3 — FAQ",
            value=(
                "```\n"
                "[FAQ] Comment réinitialiser le mot de passe\n"
                "Rendez-vous sur la page de connexion,\n"
                "cliquez sur « Mot de passe oublié »\n"
                "et suivez les instructions.\n"
                "```"
            ),
            inline=False,
        )

        embed.add_field(
            name="📎 Pièces jointes",
            value=(
                "Vous pouvez joindre des fichiers texte (`.txt`, `.md`, `.py`, etc.) "
                "à votre message. Le contenu sera automatiquement extrait et indexé."
            ),
            inline=False,
        )

        embed.set_footer(text="💡 La catégorie est libre — utilisez ce qui vous convient !")

        await interaction.response.send_message(embed=embed)

    # ─────────────────────────────────────────────
    #  Gestion des erreurs de permissions
    # ─────────────────────────────────────────────
    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Gère les erreurs de permissions pour les commandes admin."""
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "🔒 Vous n'avez pas la permission d'utiliser cette commande.\n"
                "Permission requise : `Gérer le serveur`",
                ephemeral=True,
            )
        else:
            logger.error("Erreur dans une commande admin : %s", error, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ Une erreur est survenue : `{error}`",
                    ephemeral=True,
                )


async def setup(bot: commands.Bot) -> None:
    """Point d'entrée pour charger le cog d'administration."""
    await bot.add_cog(AdminCog(bot))
