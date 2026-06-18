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

    # ── Synchronisation locale des commandes slash (instantanée) ──
    # Note : On ne synchronise plus globalement ici pour éviter les doublons.
    # Pour nettoyer les doublons existants, utilisez la commande préfixée `!sync guild`.
    total_synced = 0
    for guild in bot.guilds:
        try:
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            logger.info("   ✅ %d commande(s) synchronisée(s) sur %s", len(synced), guild.name)
            total_synced += len(synced)
        except Exception as exc:
            logger.error("   ❌ Erreur sync sur %s : %s", guild.name, exc)

    logger.info("   Total : %d commande(s) synchronisée(s) localement", total_synced)

    # ── Définir le statut du bot ──
    activity = discord.Activity(
        type=discord.ActivityType.listening,
        name="/ask • RAG Bot",
    )
    await bot.change_presence(activity=activity)


@bot.command(name="sync")
@commands.is_owner()
async def sync_commands(ctx: commands.Context, scope: str = "guild") -> None:
    """Commande manuelle pour forcer la synchronisation des commandes slash.
    Usage:
      !sync guild   -> Enregistre localement sur chaque serveur et supprime les globales (Recommandé)
      !sync global  -> Enregistre globalement et supprime les commandes locales
      !sync clear   -> Supprime toutes les commandes (globales et locales)
    """
    msg = await ctx.send("🔄 Synchronisation et nettoyage en cours...")
    
    try:
        if scope == "guild":
            # 1. Nettoyer les commandes globales de Discord pour ce bot
            bot.tree.clear_commands(guild=None)
            await bot.tree.sync()
            
            # 2. Copier et synchroniser sur chaque serveur
            total = 0
            for guild in bot.guilds:
                bot.tree.copy_global_to(guild=guild)
                synced = await bot.tree.sync(guild=guild)
                total += len(synced)
            await msg.edit(content=f"✅ Commandes synchronisées LOCALEMENT ({total} au total sur {len(bot.guilds)} serveurs). Les commandes globales ont été nettoyées pour éviter les doublons.")
            
        elif scope == "global":
            # 1. Nettoyer les commandes locales (guild) sur tous les serveurs
            for guild in bot.guilds:
                bot.tree.clear_commands(guild=guild)
                await bot.tree.sync(guild=guild)
            
            # 2. Synchroniser globalement
            synced = await bot.tree.sync()
            await msg.edit(content=f"✅ Commandes synchronisées GLOBALEMENT ({len(synced)} commandes). Les commandes locales ont été nettoyées.")
            
        elif scope == "clear":
            # Nettoyer globales
            bot.tree.clear_commands(guild=None)
            await bot.tree.sync()
            
            # Nettoyer locales
            for guild in bot.guilds:
                bot.tree.clear_commands(guild=guild)
                await bot.tree.sync(guild=guild)
                
            await msg.edit(content="✅ Toutes les commandes (globales et locales) ont été supprimées.")
            
        else:
            await msg.edit(content="❌ Scope invalide. Utilisez `guild`, `global` ou `clear`.")
            
    except Exception as exc:
        logger.error("Erreur lors de la synchronisation : %s", exc, exc_info=True)
        await msg.edit(content=f"❌ Erreur lors de la synchronisation : {exc}")


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
