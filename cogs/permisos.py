"""Comandos para conceder/revocar el permiso de lector."""

import discord
from discord.ext import commands
from discord import app_commands

from database import collection3
from ui import crear_vista_confirmacion


class Permisos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # concede permisos a un usuario para que pueda guardar manhwas en el bot, solo permitido por el admin
    @commands.hybrid_command(name='lector', description="Da permisos de lector a un usuario del servidor")
    @app_commands.describe(usuario="Usuario del servidor a quien dar permisos")
    async def lector(self, ctx, usuario: discord.Member):

        result = collection3.find_one({"usuario": str(ctx.author)})

        if result is None:
            await ctx.send("❌ No tienes permisos suficientes para realizar esta acción.")
            return

        usuario_str = str(usuario)

        if collection3.find_one({"usuario": usuario_str}):
            await ctx.send(f"⚠️ **{usuario_str}** ya tiene permisos concedidos.")
            return

        async def conceder():
            collection3.insert_one({"usuario": usuario_str})
            return f"✅ Permisos concedidos a **{usuario_str}**."

        view = crear_vista_confirmacion(
            ctx.author, conceder,
            mensaje_cancelado="❌ Operación cancelada.",
            texto_confirmar="✅ Conceder"
        )
        view.message = await ctx.send(f"⚠️ ¿Confirmas dar permisos de lector a **{usuario_str}**?", view=view)

    # revoca permisos de un usuario, solo permitido por el admin
    @commands.hybrid_command(name='revocar', description="Quita permisos de lector a un usuario")
    @app_commands.describe(usuario="Nombre exacto guardado, o mención de un miembro actual del servidor")
    async def revocar(self, ctx, *, usuario: str):

        result = collection3.find_one({"usuario": str(ctx.author)})

        if result is None:
            await ctx.send("❌ No tienes permisos suficientes para realizar esta acción.")
            return

        try:
            miembro = await commands.MemberConverter().convert(ctx, usuario.strip())
            usuario_str = str(miembro)
        except commands.BadArgument:
            # Permitir revocar por nombre exacto aunque ya no esté en el servidor
            usuario_str = usuario.strip()

        if not collection3.find_one({"usuario": usuario_str}):
            await ctx.send(f"❌ **{usuario_str}** no tenía permisos concedidos.")
            return

        async def revocar_permiso():
            collection3.delete_one({"usuario": usuario_str})
            return f"✅ Permisos revocados a **{usuario_str}**."

        view = crear_vista_confirmacion(
            ctx.author, revocar_permiso,
            mensaje_cancelado="❌ Operación cancelada.",
            texto_confirmar="✅ Revocar"
        )
        view.message = await ctx.send(f"⚠️ ¿Confirmas quitar permisos de lector a **{usuario_str}**?", view=view)


async def setup(bot):
    await bot.add_cog(Permisos(bot))
