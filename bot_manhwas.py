"""Punto de entrada del bot: arma el objeto Bot y carga las extensiones (cogs)."""

import discord
from discord.ext import commands

from config import DISCORD_TOKEN

# Configuración del bot
intents = discord.Intents.default()
intents.message_content = True  # Activa la intención de mensajes para detectar los eventos

EXTENSIONS = [
    "cogs.general",
    "cogs.permisos",
    "cogs.manhwas",
]


class BotManhwas(commands.Bot):
    async def setup_hook(self):
        for extension in EXTENSIONS:
            await self.load_extension(extension)


bot = BotManhwas(command_prefix="!", intents=intents)

# Token del bot
bot.run(DISCORD_TOKEN)
