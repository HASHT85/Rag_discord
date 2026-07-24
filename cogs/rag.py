"""
Cog RAG — Gère les requêtes de recherche intelligente.
Fournit une commande /ask et écoute les messages du canal de sortie.
"""

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import load_channels_config, TOP_K
from services.openrouter_client import get_embedding, generate_answer
from services.vectorstore import VectorStore

logger = logging.getLogger(__name__)

# Couleur Discord « blurple »
BLURPLE = 0x5865F2

# Limite de caractères pour la description d'un embed Discord
EMBED_DESC_LIMIT = 4096


def _truncate(text: str, max_len: int) -> str:
    """Tronque un texte en ajoutant '…' si nécessaire."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _build_sources_footer(ranked_docs: list[dict]) -> str:
    """
    Construit un résumé des sources à partir des documents retenus par le Reranker.
    Renvoie une chaîne formatée avec catégories et titres uniques.
    """
    seen: set[str] = set()
    sources: list[str] = []

    for doc in ranked_docs:
        meta = doc.get("metadata", {})
        key = f"[{meta.get('category', '?')}] {meta.get('title', '?')}"
        if key not in seen:
            seen.add(key)
            sources.append(key)

    if not sources:
        return "Aucune source"
    return "Sources : " + " • ".join(sources)


async def _run_rag_pipeline(
    vector_store: VectorStore,
    question: str,
    bot: Optional[commands.Bot] = None,
) -> tuple[str, str, Optional[str]]:
    """
    Exécute le pipeline RAG état de l'art :
    Embedding → Recherche Hybride Qdrant (Dense + Sparse BM25) → Re-Ranking FlashRank → Génération Multimodale.

    Retourne (answer, sources_footer, attachment_url).
    Lève ValueError si aucun document pertinent n'est trouvé.
    """
    from services.reranker import rerank_documents

    # 1. Embedding Dense de la question (3072d)
    question_embedding = await get_embedding([question])

    # 2. Recherche Hybride dans Qdrant (Dense + Sparse BM25)
    results = vector_store.query(
        query_embedding=question_embedding[0],
        query_text=question,
        n_results=TOP_K,
    )

    documents = results.get("documents", [])
    if not documents:
        raise ValueError("Aucun document pertinent trouvé.")

    # 3. Préparer les candidat(s) pour le Re-Ranking
    raw_docs = []
    for i in range(len(results["ids"])):
        raw_docs.append({
            "id": results["ids"][i],
            "text": results["documents"][i],
            "metadata": results["metadatas"][i],
        })

    # 4. Re-Ranking FlashRank (Filtrage anti-bruit)
    ranked_docs = rerank_documents(query=question, documents=raw_docs, top_n=TOP_K)
    if not ranked_docs:
        raise ValueError("Aucun document pertinent retenu après filtrage.")

    # 5. Concaténer le contexte et extraire les images (locales ou URLs Discord)
    context_parts = []
    image_paths = []
    attachment_url = None
    for doc in ranked_docs:
        context_parts.append(doc["text"])
        meta = doc.get("metadata", {})
        if meta.get("type") == "image" and meta.get("local_path"):
            image_paths.append(meta.get("local_path"))
        if not attachment_url and meta.get("attachment_url"):
            attachment_url = meta.get("attachment_url")

    # Fallback dynamique : Si l'URL n'était pas stockée en métadonnée (anciens index), la récupérer directement sur Discord
    if not attachment_url and bot:
        for doc in ranked_docs:
            meta = doc.get("metadata", {})
            if meta.get("has_attachment") or meta.get("attachment_url"):
                channel_id = meta.get("channel_id")
                message_id = meta.get("message_id")
                if channel_id and message_id:
                    try:
                        ch = bot.get_channel(int(channel_id))
                        if not ch:
                            ch = await bot.fetch_channel(int(channel_id))
                        if ch:
                            msg = await ch.fetch_message(int(message_id))
                            if msg.attachments:
                                attachment_url = msg.attachments[0].url
                                logger.info("🖼️ URL d'image récupérée sur Discord (message %s) : %s", message_id, attachment_url)
                                break
                    except Exception as exc:
                        logger.warning("Impossible de récupérer l'image du message %s : %s", message_id, exc)

    context = "\n\n---\n\n".join(context_parts)

    # 6. Générer la réponse avec le LLM (Raisonnement + Vision)
    answer = await generate_answer(
        question=question,
        context=context,
        image_paths=image_paths if image_paths else None,
    )
    sources_footer = _build_sources_footer(ranked_docs)

    return answer, sources_footer, attachment_url


def _build_response_embeds(
    question: str,
    answer: str,
    sources_footer: str,
    attachment_url: Optional[str] = None,
) -> list[discord.Embed]:
    """
    Construit un ou plusieurs embeds Discord pour la réponse RAG.
    Découpe automatiquement si la réponse dépasse la limite et affiche l'image d'illustration si disponible.
    """
    embeds: list[discord.Embed] = []
    truncated_question = _truncate(question, 256)

    # Découper la réponse en morceaux de taille EMBED_DESC_LIMIT
    chunks: list[str] = []
    remaining = answer
    while remaining:
        if len(remaining) <= EMBED_DESC_LIMIT:
            chunks.append(remaining)
            break
        # Trouver un point de coupure propre (saut de ligne ou espace)
        cut = remaining.rfind("\n", 0, EMBED_DESC_LIMIT)
        if cut == -1:
            cut = remaining.rfind(" ", 0, EMBED_DESC_LIMIT)
        if cut == -1:
            cut = EMBED_DESC_LIMIT
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()

    for i, chunk in enumerate(chunks):
        embed = discord.Embed(
            color=BLURPLE,
            description=chunk,
        )
        # Titre uniquement sur le premier embed
        if i == 0:
            embed.title = f"💡 {truncated_question}"

        # Footer et image uniquement sur le dernier embed
        if i == len(chunks) - 1:
            embed.set_footer(text=_truncate(sources_footer, 2048))
            if attachment_url:
                embed.set_image(url=attachment_url)

        embeds.append(embed)

    return embeds


class RAGCog(commands.Cog):
    """Cog de recherche RAG — répond aux questions via embeddings et LLM."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialise le cog avec une référence au bot et le VectorStore."""
        self.bot = bot
        self.vector_store = VectorStore()

    # ─────────────────────────────────────────────
    #  Commande slash /ask
    # ─────────────────────────────────────────────
    @app_commands.command(
        name="ask",
        description="Poser une question au bot RAG pour obtenir une réponse basée sur les documents indexés.",
    )
    @app_commands.describe(question="La question à poser")
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        """Commande slash /ask — exécute le pipeline RAG et répond."""
        # ── Vérifier le canal de sortie (si configuré) ──
        channels_config = load_channels_config()
        output_channel_id = channels_config.get("output_channel_id")

        if output_channel_id and interaction.channel_id != output_channel_id:
            await interaction.response.send_message(
                f"⚠️ Cette commande est réservée au canal <#{output_channel_id}>.",
                ephemeral=True,
            )
            return

        # ── Différer la réponse (thinking…) ──
        await interaction.response.defer(thinking=True)

        try:
            answer, sources_footer, attachment_url = await _run_rag_pipeline(
                self.vector_store, question, bot=self.bot
            )

            embeds = _build_response_embeds(question, answer, sources_footer, attachment_url)

            # Envoyer le premier embed en followup, les suivants en messages séparés
            await interaction.followup.send(embed=embeds[0])
            for embed in embeds[1:]:
                await interaction.followup.send(embed=embed)

        except ValueError as exc:
            # Aucun document trouvé
            embed = discord.Embed(
                title="🔍 Aucun résultat",
                description=str(exc),
                color=discord.Color.orange(),
            )
            await interaction.followup.send(embed=embed)

        except Exception as exc:
            logger.error("Erreur dans /ask : %s", exc, exc_info=True)
            embed = discord.Embed(
                title="❌ Erreur",
                description=f"Une erreur est survenue lors du traitement : `{exc}`",
                color=discord.Color.red(),
            )
            await interaction.followup.send(embed=embed)

    # ─────────────────────────────────────────────
    #  Listener sur le canal de sortie (questions naturelles)
    # ─────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        Écoute les messages du canal de sortie.
        Traite chaque message non-bot comme une question RAG.
        """
        # ── Ignorer les bots ──
        if message.author.bot:
            return

        # ── Vérifier que le message est dans le canal de sortie ──
        channels_config = load_channels_config()
        output_channel_id = channels_config.get("output_channel_id")

        if output_channel_id is None or message.channel.id != output_channel_id:
            return

        # ── Ignorer les commandes potentielles (préfixe !) ──
        if message.content.startswith("!") or message.content.startswith("/"):
            return

        # ── Ignorer les messages trop courts ──
        question = message.content.strip()
        if len(question) < 3:
            return

        # ── Indicateur de traitement (typing…) ──
        async with message.channel.typing():
            try:
                answer, sources_footer, attachment_url = await _run_rag_pipeline(
                    self.vector_store, question, bot=self.bot
                )

                embeds = _build_response_embeds(question, answer, sources_footer, attachment_url)

                # Répondre en reply au message original
                await message.reply(embed=embeds[0], mention_author=False)
                for embed in embeds[1:]:
                    await message.channel.send(embed=embed)

            except ValueError:
                # Aucun document trouvé
                await message.reply(
                    "🔍 Aucun document pertinent trouvé pour votre question.",
                    mention_author=False,
                )

            except Exception as exc:
                logger.error(
                    "Erreur RAG pour le message %s : %s",
                    message.id, exc, exc_info=True,
                )
                await message.reply(
                    f"⚠️ Erreur lors du traitement : `{exc}`",
                    mention_author=False,
                )


async def setup(bot: commands.Bot) -> None:
    """Point d'entrée pour charger le cog RAG."""
    await bot.add_cog(RAGCog(bot))
