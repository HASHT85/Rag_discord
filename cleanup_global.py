import asyncio
import discord
from discord.ext import commands
from config import DISCORD_TOKEN

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user}")
    print("🧹 Nettoyage des commandes globales en cours...")
    try:
        bot.tree.clear_commands(guild=None)
        synced = await bot.tree.sync()
        print(f"✅ Commandes globales nettoyées avec succès ! (retour : {synced})")
    except Exception as e:
        print(f"❌ Erreur lors du nettoyage des commandes globales : {e}")
    await bot.close()

if __name__ == "__main__":
    asyncio.run(bot.start(DISCORD_TOKEN))
