"""Comando de información del bot y manejo global de eventos/errores."""

import discord
from discord.ext import commands

from config import logger, UMBRAL_DIAS_RECORDATORIO
from database import collection2


class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"Bot conectado como {self.bot.user}")
        try:
            sincronizados = await self.bot.tree.sync()
            logger.info(f"Sincronizados {len(sincronizados)} comandos slash.")
        except Exception as e:
            logger.error(f"Error sincronizando comandos slash: {e}")

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Manejador global de errores para comandos con prefijo '!' (los slash usan su propio flujo)."""
        if isinstance(error, (commands.MemberNotFound, commands.UserNotFound)):
            await ctx.send(f"❌ No se encontró ningún usuario '{error.argument}' en este servidor.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Falta el argumento '{error.param.name}'. Usa `!info` para ver cómo usar el comando.")
        elif isinstance(error, commands.CommandNotFound):
            pass
        else:
            logger.error(f"Error no manejado en comando: {error}")
            await ctx.send("❌ Ocurrió un error inesperado al ejecutar el comando.")

    # muestra la lista de comandos del bot
    @commands.hybrid_command(name='info', description="Muestra la información y comandos del bot")
    async def info(self, ctx):

        result = collection2.find_one({"usuario": str(ctx.author)})

        if result is None:
            await ctx.send("❌ No tienes permisos suficientes para realizar esta acción.")
            return

        embed = discord.Embed(
            title=f"🤖 ¡Hola! Soy {self.bot.user} 📚",
            description="Estoy aquí para ayudarte a gestionar tu colección de manhwas. Ya que olympus no ayuda\nPuedes usar los comandos con `!` o con `/`.",
            color=discord.Color.blue()
        )

        # Sección de Comandos (1/2)
        embed.add_field(
            name="📋 Comandos Disponibles (1/2):",
            value=(
                "**• info**\n"
                "  Muestra la información del bot\n\n"
                "**• guardar nombre, capitulo, link (opcional)**\n"
                "  Guarda un nuevo manhwa en tu lista (busca en AniList para ayudarte a identificarlo)\n"
                "  Si el nombre tiene comas, enciérralo entre [ ] o \" \": !guardar [Solo Leveling, Ragnarok], 12\n\n"
                "**• buscador nombre**\n"
                "  Busca en AniList sin guardar nada, para identificar un manhwa antes de guardarlo\n\n"
                "**• listar**\n"
                "  Muestra todos tus manhwas guardados\n\n"
                "**• listar [nombre]**\n"
                "  Busca un manhwa en tu lista y selecciona hasta que capitulo has leído\n\n"
                "**• eliminar [nombre]**\n"
                "  Elimina un manhwa de tu lista\n\n"
                "**• estado [nombre]**\n"
                "  Cambia el estado de lectura (Leyendo, Favorito, En pausa, Terminado, Dropeado)\n\n"
            ),
            inline=False
        )

        # Sección de Comandos (2/2)
        embed.add_field(
            name="📋 Comandos Disponibles (2/2):",
            value=(
                "**• random**\n"
                "  Elige un manhwa al azar de tu lista\n\n"
                "**• recordatorios**\n"
                f"  Muestra los manhwas 'Leyendo' sin actualizar hace más de {UMBRAL_DIAS_RECORDATORIO} días\n\n"
                "**• stats**\n"
                "  Muestra estadísticas de tu colección\n\n"
                "**• exportar**\n"
                "  Descarga un respaldo de tu lista en JSON\n\n"
                "**• importar [archivo]**\n"
                "  Restaura manhwas desde un respaldo .json (adjunta el archivo al comando)\n\n"
                "**• lector [usuario]**\n"
                "  Le asigna permisos a un usuario para poder guardar manhwas, mangas, manhuas en el bot\n\n"
                "**• revocar [usuario]**\n"
                "  Le quita los permisos a un usuario\n\n"
            ),
            inline=False
        )

        # Sección de Novedades (1/2)
        embed.add_field(
            name="🆕 Novedades — Comandos",
            value=(
                "**Comandos nuevos**\n"
                "• `eliminar` — borra un manhwa de tu lista (con confirmación).\n"
                "• `revocar` — le quita permisos de lector a un usuario.\n"
                "• `estado` — marca un manhwa como Leyendo, Favorito, En pausa, Terminado o Dropeado.\n"
                "• `random` — elige un manhwa al azar para leer.\n"
                "• `recordatorios` — te avisa qué llevas mucho tiempo sin actualizar.\n"
                "• `stats` — resumen de tu colección (total, capítulos, más avanzado, por estado).\n"
                "• `exportar`/`importar` — respaldo y restauración de tu lista como archivo JSON.\n\n"
                "**Slash commands**\n"
                "• Todos los comandos también funcionan con `/`, con autocompletado nativo.\n"
                "• `/listar`, `/eliminar` y `/estado` sugieren tus propios manhwas mientras escribes.\n"
                "• `/lector` te deja elegir al usuario directamente desde un selector.\n"
            ),
            inline=False
        )

        # Sección de Novedades (2/2)
        embed.add_field(
            name="🆕 Novedades — Mejoras",
            value=(
                "**Guardar**\n"
                "• Si vuelves a guardar un manhwa que ya tienes, actualiza el capítulo/link en vez de duplicarlo.\n"
                "• Si el nombre tiene comas, enciérralo entre `[ ]` o `\" \"` para que no se confunda con los separadores.\n\n"
                "**Interfaz**\n"
                "• Actualizar el capítulo ahora abre un formulario emergente en vez de pedir que escribas en el chat.\n"
                "• Si hay varias coincidencias al buscar o eliminar, aparece un menú desplegable para elegir cuál.\n"
                "• Eliminar y dar/quitar permisos piden confirmación con botones antes de aplicar el cambio.\n\n"
                "**Seguridad**\n"
                "• `lector` valida que el usuario exista en el servidor y evita duplicados.\n"
                "• Mejor manejo de errores y mensajes más claros cuando algo falla.\n"
                f"• `listar` marca con ⏰ los manhwas 'Leyendo' sin actualizar hace {UMBRAL_DIAS_RECORDATORIO}+ días.\n"
            ),
            inline=False
        )

        # Sección de Novedades (3/3) — AniList
        embed.add_field(
            name="🆕 Novedades — Integración con AniList",
            value=(
                "• Al guardar un manhwa nuevo, el bot lo busca en AniList y te muestra su portada, "
                "títulos en otros idiomas, género y estado para que lo identifiques fácil, incluso si "
                "el nombre está en coreano/japonés/chino.\n"
                "• Si no aparece en AniList (o la API falla), lo guardas libremente como siempre.\n"
                "• La portada queda guardada y se muestra en `listar [nombre]` y `random` — haz clic en "
                "la imagen para verla en grande.\n"
                "• `buscador` — consulta AniList sin guardar nada, para chequear antes de usar `guardar`.\n"
            ),
            inline=False
        )

        # Pie de página
        embed.set_footer(
            text="Desarrollado por Jhony",
            icon_url=self.bot.user.avatar.url  # Reemplaza con tu ícono
        )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(General(bot))
