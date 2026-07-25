"""
Cog RAG — Gère les requêtes de recherche intelligente.
Fournit une commande /ask et écoute les messages du canal de sortie.
"""

import logging
import re
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import load_channels_config, TOP_K
from services.conversation_memory import ConversationMemory, conversation_memory
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


def resolve_context_id(
    channel: Optional[discord.abc.GuildChannel | discord.Thread | discord.DMChannel | discord.abc.PrivateChannel] = None,
    reference: Optional[discord.MessageReference] = None,
    memory: Optional[ConversationMemory] = None,
) -> str:
    """
    Détermine l'identifiant de contexte pour la mémoire de conversation.
    Priorités :
    1. Si le message répond à un message bot répertorié dans la mémoire, on utilise son context_id.
    2. Si le canal est un Thread Discord, tous les messages du fil appartiennent au contexte du fil str(channel.id),
       sauf si la référence pointe explicitement vers un message bot enregistré (Priorité 1).
    3. Si le message répond à un autre message hors fil (parent_message_id), on utilise str(parent_message_id).
    4. Sinon, on utilise str(channel.id).
    """
    if reference and reference.message_id:
        parent_id = str(reference.message_id)
        if memory:
            registered_context = memory.get_context_id_from_message(parent_id)
            if registered_context:
                return registered_context

    if isinstance(channel, discord.Thread):
        return str(channel.id)

    if reference and reference.message_id:
        return str(reference.message_id)

    if channel and hasattr(channel, "id"):
        return str(channel.id)

    return "default_context"


async def _run_rag_pipeline(
    vector_store: VectorStore,
    question: str,
    bot: Optional[commands.Bot] = None,
    conversation_history: Optional[list[dict]] = None,
) -> tuple[str, str, Optional[str], Optional[str]]:
    """
    Exécute le pipeline RAG état de l'art avec support de la mémoire de conversation :
    Formulation de la requête → Embedding → Recherche Hybride Qdrant → Re-Ranking FlashRank → Génération Multimodale.

    Retourne (answer, sources_footer, attachment_url, attachment_name).
    Lève ValueError si aucun document pertinent n'est trouvé.
    """
    from services.reranker import rerank_documents

    # Formuler la requête de recherche vectorielle en enrichissant si besoin avec le contexte précédent
    retrieval_query = question
    if conversation_history:
        prev_user_msgs = [msg["content"] for msg in conversation_history if msg.get("role") == "user"]
        if prev_user_msgs:
            last_user_query = prev_user_msgs[-1]
            followup_indicators = [
                "ce point", "le point", "celui-ci", "celle-ci", "ce dernier", "cette dernière",
                "en savoir plus", "détailler", "expliquer", "préciser", "pourquoi", "comment",
                "et pour", "qu'en est-il", "plus de détails", "lequel", "laquelle", "lesquels", "lesquelles"
            ]
            pattern = r'\b(?:' + '|'.join(re.escape(w) for w in followup_indicators) + r')\b'
            is_followup = bool(re.search(pattern, question.lower()))
            if is_followup:
                retrieval_query = f"{last_user_query} {question}"

    # 1. Embedding Dense de la question (3072d)
    question_embedding = await get_embedding([retrieval_query])

    # 2. Recherche Hybride dans Qdrant (Dense + Sparse BM25)
    results = vector_store.query(
        query_embedding=question_embedding[0],
        query_text=retrieval_query,
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
    ranked_docs = rerank_documents(query=retrieval_query, documents=raw_docs, top_n=TOP_K)
    if not ranked_docs:
        raise ValueError("Aucun document pertinent retenu après filtrage.")

    # 5. Concaténer le contexte et extraire les images / fichiers joints
    context_parts = []
    image_paths = []
    attachments: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for doc in ranked_docs:
        context_parts.append(doc["text"])
        meta = doc.get("metadata", {})
        if meta.get("type") == "image" and meta.get("local_path"):
            image_paths.append(meta.get("local_path"))
        
        url = meta.get("attachment_url")
        name = meta.get("attachment_name") or meta.get("title") or "Fichier joint"
        if url and url not in seen_urls:
            seen_urls.add(url)
            attachments.append({"name": name, "url": url})

    # Fallback dynamique : Si l'URL n'était pas stockée en métadonnée (anciens index), la récupérer directement sur Discord
    if not attachments and bot:
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
                            for att in msg.attachments:
                                if att.url not in seen_urls:
                                    seen_urls.add(att.url)
                                    attachments.append({"name": att.filename, "url": att.url})
                    except Exception as exc:
                        logger.warning("Impossible de récupérer les pièces jointes du message %s : %s", message_id, exc)

    context = "\n\n---\n\n".join(context_parts)

    # 6. Générer la réponse avec le LLM (Raisonnement + Vision + Mémoire de conversation)
    answer = await generate_answer(
        question=question,
        context=context,
        image_paths=image_paths if image_paths else None,
        conversation_history=conversation_history,
    )
    sources_footer = _build_sources_footer(ranked_docs)

    return answer, sources_footer, attachments


def _is_image_attachment(name: str, url: str) -> bool:
    """Vérifie si l'extension ou l'URL correspond à un fichier image."""
    target = f"{name} {url}".lower()
    return any(ext in target for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"])


def _build_response_embeds(
    question: str,
    answer: str,
    sources_footer: str,
    attachments: list[dict[str, str]] | None = None,
) -> list[discord.Embed]:
    """
    Construit un ou plusieurs embeds Discord pour la réponse RAG.
    Affiche tous les fichiers d'origine et génère un aperçu visuel pour chaque image source utilisée.
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
        embeds.append(embed)

    # Footer sur le dernier embed de texte
    embeds[-1].set_footer(text=_truncate(sources_footer, 2048))

    # Gérer l'affichage des fichiers joints et images sources
    if attachments:
        # Numéroter proprement les noms s'il y a des doublons (ex: image.png #1, image.png #2)
        name_counts: dict[str, int] = {}
        for att in attachments:
            n = att["name"]
            name_counts[n] = name_counts.get(n, 0) + 1

        seen_counts: dict[str, int] = {}
        formatted_attachments: list[dict[str, str]] = []
        for att in attachments:
            n = att["name"]
            if name_counts[n] > 1:
                seen_counts[n] = seen_counts.get(n, 0) + 1
                disp_name = f"{n} (#{seen_counts[n]})"
            else:
                disp_name = n
            formatted_attachments.append({"name": disp_name, "url": att["url"]})

        # Ajouter les liens de téléchargement sur le dernier embed de texte
        last_embed = embeds[-1]
        file_links = [
            f"📥 **[{att['name']}]({att['url']})**"
            for att in formatted_attachments
        ]
        field_title = "📎 Fichier joint d'origine" if len(formatted_attachments) == 1 else f"📎 {len(formatted_attachments)} Fichiers joints d'origine"
        last_embed.add_field(
            name=field_title,
            value="\n".join(file_links[:10]),
            inline=False,
        )

        # Affichage visuel des images sources
        image_atts = [att for att in formatted_attachments if _is_image_attachment(att["name"], att["url"])]
        if image_atts:
            # La première image est affichée directement sur l'embed principal
            embeds[0].set_image(url=image_atts[0]["url"])

            # Pour les images 2, 3, 4..., ajouter un sub-embed dans le même message
            for idx, att in enumerate(image_atts[1:5], start=2):
                img_embed = discord.Embed(
                    title=f"🖼️ Image source #{idx} — {att['name']}",
                    color=BLURPLE,
                )
                img_embed.set_image(url=att["url"])
                embeds.append(img_embed)

    return embeds


class RAGCog(commands.Cog):
    """Cog de recherche RAG — répond aux questions via embeddings et LLM."""

    def __init__(self, bot: commands.Bot, memory: Optional[ConversationMemory] = None) -> None:
        """Initialise le cog avec une référence au bot, le VectorStore et la mémoire de conversation."""
        self.bot = bot
        self.vector_store = VectorStore()
        self.memory = memory if memory is not None else conversation_memory
        self.cleanup_task.start()

    def cog_unload(self) -> None:
        """Stoppe les tâches en arrière-plan au déchargement du cog."""
        self.cleanup_task.cancel()

    @tasks.loop(hours=1)
    async def cleanup_task(self) -> None:
        """Tâche périodique nettoyant la mémoire de conversation expirée (toutes les heures)."""
        try:
            cleaned = self.memory.cleanup_expired(ttl_seconds=86400)
            if cleaned > 0:
                logger.info("🧹 Tâche périodique : %d contextes expirés supprimés.", cleaned)
        except Exception as exc:
            logger.error("Erreur lors du nettoyage périodique de la mémoire : %s", exc)

    @cleanup_task.before_loop
    async def before_cleanup_task(self) -> None:
        """Attend que le bot soit prêt avant de démarrer la boucle de nettoyage."""
        await self.bot.wait_until_ready()

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
        # ── Différer la réponse (thinking…) ──
        await interaction.response.defer(thinking=True)

        # ── Vérifier le canal de sortie (si configuré) ──
        channels_config = load_channels_config()
        output_channel_id = channels_config.get("output_channel_id")

        if output_channel_id and interaction.channel_id != output_channel_id:
            await interaction.followup.send(
                f"⚠️ Cette commande est réservée au canal <#{output_channel_id}>.",
                ephemeral=True,
            )
            return

        context_id = resolve_context_id(
            channel=interaction.channel,
            reference=None,
            memory=self.memory,
        )
        history = self.memory.get_history(context_id)

        try:
            answer, sources_footer, attachments = await _run_rag_pipeline(
                self.vector_store, question, bot=self.bot, conversation_history=history
            )

            embeds = _build_response_embeds(question, answer, sources_footer, attachments)

            # Envoyer tous les embeds ensemble dans UN SEUL message unifié
            first_msg = await interaction.followup.send(embeds=embeds, wait=True)

            # Enregistrer le tour dans la mémoire
            self.memory.add_turn(context_id, question, answer)
            if first_msg and hasattr(first_msg, "id"):
                self.memory.register_bot_message(first_msg.id, context_id)

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
        Écoute les messages du canal de sortie et des threads associés.
        Traite chaque message non-bot comme une question RAG.
        """
        # ── Ignorer les bots ──
        if message.author.bot:
            return

        # ── Vérifier que le message est dans le canal de sortie ou un fil dérivé ──
        channels_config = load_channels_config()
        output_channel_id = channels_config.get("output_channel_id")

        if output_channel_id is not None:
            is_target_channel = message.channel.id == output_channel_id
            is_target_thread = (
                isinstance(message.channel, discord.Thread)
                and message.channel.parent_id == output_channel_id
            )
            if not (is_target_channel or is_target_thread):
                return

        # ── Ignorer les commandes potentielles (préfixe !) ──
        if message.content.startswith("!") or message.content.startswith("/"):
            return

        # ── Ignorer les messages trop courts ──
        question = message.content.strip()
        if len(question) < 3:
            return

        context_id = resolve_context_id(
            channel=message.channel,
            reference=message.reference,
            memory=self.memory,
        )
        history = self.memory.get_history(context_id)

        # ── Indicateur de traitement (typing…) ──
        async with message.channel.typing():
            try:
                answer, sources_footer, attachments = await _run_rag_pipeline(
                    self.vector_store, question, bot=self.bot, conversation_history=history
                )

                embeds = _build_response_embeds(question, answer, sources_footer, attachments)

                # Répondre avec TOUS les embeds dans un SEUL message unifié
                reply_msg = await message.reply(embeds=embeds, mention_author=False)

                # Enregistrer le tour dans la mémoire
                self.memory.add_turn(context_id, question, answer)
                if reply_msg and hasattr(reply_msg, "id"):
                    self.memory.register_bot_message(reply_msg.id, context_id)

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

