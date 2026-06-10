"""
Point d'entrée principal du bot Discord RAG.
Initialise le bot, charge les cogs et démarre la connexion Discord.
"""

import asyncio
import logging
import os
import sys

import discord
from discord.ext import commands

from config import DISCORD_TOKEN, validate_config

# ─────────────────────────────────────────────
#  Configuration du logging
# ─────────────────────────────────────────────
_log_formatter = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Handler console avec UTF-8 (évite les erreurs cp1252 sur Windows)
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_log_formatter)
_console_handler.stream = open(sys.stdout.fileno(), mode="w", encoding="utf-8", closefd=False)

# Créer le dossier logs s'il n'existe pas
os.makedirs("logs", exist_ok=True)

# Handler fichier avec UTF-8
_file_handler = logging.FileHandler("logs/bot.log", encoding="utf-8")
_file_handler.setFormatter(_log_formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[_console_handler, _file_handler],
)
logger = logging.getLogger("bot")

# Réduire le bruit des loggers Discord
logging.getLogger("discord").setLevel(logging.WARNING)
logging.getLogger("discord.http").setLevel(logging.WARNING)

# ─────────────────────────────────────────────
#  Validation de la configuration au démarrage
# ─────────────────────────────────────────────
validate_config()

# ─────────────────────────────────────────────
#  Configuration des intents
# ─────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

# ─────────────────────────────────────────────
#  Création du bot
# ─────────────────────────────────────────────
bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    description="Bot RAG Discord — Indexation et recherche intelligente",
)

# Liste des extensions (cogs) à charger
EXTENSIONS: list[str] = [
    "cogs.indexer",
    "cogs.rag",
    "cogs.admin",
]


async def load_cogs() -> None:
    """Charge toutes les extensions (cogs) du bot."""
    for extension in EXTENSIONS:
        try:
            await bot.load_extension(extension)
            logger.info("✅ Extension chargée : %s", extension)
        except Exception as exc:
            logger.error("❌ Impossible de charger %s : %s", extension, exc, exc_info=True)


@bot.event
async def on_ready() -> None:
    """Événement déclenché quand le bot est connecté et prêt."""
    logger.info("✅ %s connecté !", bot.user)
    logger.info("   Serveurs : %d", len(bot.guilds))
    logger.info("   ID : %s", bot.user.id if bot.user else "inconnu")

    # ── Synchronisation des commandes slash par serveur (instantané) ──
    total_synced = 0
    for guild in bot.guilds:
        try:
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            logger.info("   ✅ %d commande(s) synchronisée(s) sur %s", len(synced), guild.name)
            total_synced += len(synced)
        except Exception as exc:
            logger.error("   ❌ Erreur sync sur %s : %s", guild.name, exc)

    # Sync global aussi (pour les futurs serveurs)
    try:
        await bot.tree.sync()
        logger.info("   ✅ Sync global effectué")
    except Exception as exc:
        logger.error("   ❌ Erreur sync global : %s", exc)

    logger.info("   Total : %d commande(s) synchronisée(s)", total_synced)

    # ── Définir le statut du bot ──
    activity = discord.Activity(
        type=discord.ActivityType.listening,
        name="/ask • RAG Bot",
    )
    await bot.change_presence(activity=activity)


@bot.command(name="sync")
@commands.is_owner()
async def sync_commands(ctx: commands.Context) -> None:
    """Commande manuelle pour forcer la synchronisation des commandes slash."""
    msg = await ctx.send("🔄 Synchronisation des commandes en cours...")
    total = 0
    for guild in bot.guilds:
        try:
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            total += len(synced)
        except Exception as exc:
            await ctx.send(f"❌ Erreur sur {guild.name} : {exc}")
    await msg.edit(content=f"✅ {total} commande(s) synchronisée(s) sur {len(bot.guilds)} serveur(s) !")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    """Gestion globale des erreurs de commandes préfixées."""
    if isinstance(error, commands.CommandNotFound):
        return  # Ignorer silencieusement les commandes inconnues
    logger.error("Erreur de commande : %s", error, exc_info=True)


async def main() -> None:
    """Fonction principale — charge les cogs et démarre le bot."""
    async with bot:
        await load_cogs()
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Arrêt du bot (interruption clavier)")
