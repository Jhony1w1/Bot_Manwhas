"""Componentes de interfaz (botones, menús desplegables, modal) reutilizados por varios comandos."""

import re
from datetime import datetime

import discord
from discord.ui import View, Button, Select, Modal, TextInput

from config import ESTADOS
from database import collection


def crear_vista_confirmacion(autor, on_confirmar, mensaje_cancelado="❌ Acción cancelada.", texto_confirmar="✅ Confirmar", timeout=15):
    """Vista genérica con botones Confirmar/Cancelar.
    on_confirmar es una función async sin argumentos que ejecuta la acción y devuelve el mensaje final."""
    view = View(timeout=timeout)
    view.message = None

    boton_confirmar = Button(label=texto_confirmar, style=discord.ButtonStyle.danger)
    boton_cancelar = Button(label="❌ Cancelar", style=discord.ButtonStyle.secondary)

    async def confirmar_callback(interaction: discord.Interaction):
        if interaction.user != autor:
            await interaction.response.send_message("❌ No puedes confirmar esta acción.", ephemeral=True)
            return

        mensaje_final = await on_confirmar()
        for item in view.children:
            item.disabled = True
        await interaction.response.edit_message(content=mensaje_final, view=view)
        view.stop()

    async def cancelar_callback(interaction: discord.Interaction):
        if interaction.user != autor:
            await interaction.response.send_message("❌ No puedes cancelar esta acción.", ephemeral=True)
            return

        for item in view.children:
            item.disabled = True
        await interaction.response.edit_message(content=mensaje_cancelado, view=view)
        view.stop()

    async def on_timeout():
        for item in view.children:
            item.disabled = True
        if view.message:
            try:
                await view.message.edit(content="⏳ Tiempo agotado, no se realizó ningún cambio.", view=view)
            except discord.HTTPException:
                pass

    boton_confirmar.callback = confirmar_callback
    boton_cancelar.callback = cancelar_callback
    view.on_timeout = on_timeout

    view.add_item(boton_confirmar)
    view.add_item(boton_cancelar)
    return view


def crear_selector_estado(autor, registro, timeout=30):
    """Menú desplegable para cambiar el estado de lectura de un manhwa."""
    view = View(timeout=timeout)
    view.message = None

    opciones = [
        discord.SelectOption(label=etiqueta, value=valor)
        for valor, etiqueta in ESTADOS.items()
    ]
    select = Select(placeholder="Elige el nuevo estado...", options=opciones)

    async def seleccionar_callback(interaction: discord.Interaction):
        if interaction.user != autor:
            await interaction.response.send_message("❌ No puedes usar este menú.", ephemeral=True)
            return

        nuevo_estado = select.values[0]
        collection.update_one({"_id": registro["_id"]}, {"$set": {"estado": nuevo_estado}})

        for item in view.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ **{registro['nombre_manhwa']}** ahora está marcado como {ESTADOS[nuevo_estado]}.",
            view=view
        )

    async def on_timeout():
        for item in view.children:
            item.disabled = True
        if view.message:
            try:
                await view.message.edit(content="⏳ Tiempo agotado.", view=view)
            except discord.HTTPException:
                pass

    select.callback = seleccionar_callback
    view.on_timeout = on_timeout
    view.add_item(select)
    return view


def crear_selector_manhwas(autor, registros, on_seleccionar, placeholder="Elige un manhwa...", timeout=30):
    """Menú desplegable para elegir un manhwa entre varias coincidencias.
    on_seleccionar es un callback async(interaction, registro)."""
    view = View(timeout=timeout)
    view.message = None

    registros_por_id = {str(r["_id"]): r for r in registros[:25]}
    opciones = [
        discord.SelectOption(
            label=r["nombre_manhwa"][:100],
            value=str(r["_id"]),
            description=(r.get("titulo_ingles") or r.get("titulo_romaji") or "")[:100] or None
        )
        for r in registros[:25]
    ]
    select = Select(placeholder=placeholder, options=opciones)

    async def seleccionar_callback(interaction: discord.Interaction):
        if interaction.user != autor:
            await interaction.response.send_message("❌ No puedes usar este menú.", ephemeral=True)
            return

        registro = registros_por_id[select.values[0]]
        for item in view.children:
            item.disabled = True
        await interaction.response.edit_message(view=view)
        await on_seleccionar(interaction, registro)

    async def on_timeout():
        for item in view.children:
            item.disabled = True
        if view.message:
            try:
                await view.message.edit(content="⏳ Tiempo agotado.", view=view)
            except discord.HTTPException:
                pass

    select.callback = seleccionar_callback
    view.on_timeout = on_timeout
    view.add_item(select)
    return view


class ModalActualizarCapitulo(Modal, title="Actualizar capítulo"):
    """Formulario nativo de Discord para ingresar el nuevo capítulo, sin esperar un mensaje de chat."""

    capitulo = TextInput(label="Nuevo capítulo", placeholder="Ej: 125 o 125.5", required=True, max_length=10)

    def __init__(self, usuario, nombre_manhwa):
        super().__init__()
        self.usuario = usuario
        self.nombre_manhwa = nombre_manhwa

    async def on_submit(self, interaction: discord.Interaction):
        try:
            nuevo_capitulo = float(self.capitulo.value)
        except ValueError:
            await interaction.response.send_message("❌ El capítulo debe ser un número válido.", ephemeral=True)
            return

        manhwa = collection.find_one({
            "usuario": self.usuario,
            "nombre_manhwa": {"$regex": f"^{re.escape(self.nombre_manhwa)}$", "$options": "i"}
        })

        if not manhwa:
            await interaction.response.send_message(f"❌ No se encontró el manhwa '{self.nombre_manhwa}'.", ephemeral=True)
            return

        collection.update_one(
            {"_id": manhwa["_id"]},
            {"$set": {"capitulo": nuevo_capitulo, "fecha_guardado": datetime.now()}}
        )
        await interaction.response.send_message(
            f"✅ **{self.nombre_manhwa}** ha sido actualizado al capítulo **{nuevo_capitulo}**."
        )


def crear_vista_boton(usuario, nombre_manhwa):
    """Crea una vista con un botón que abre un modal para actualizar el capítulo."""
    view = View()

    async def boton_callback(interaction: discord.Interaction):
        if str(interaction.user) != usuario:
            await interaction.response.send_message("❌ No puedes actualizar este capítulo.", ephemeral=True)
            return

        await interaction.response.send_modal(ModalActualizarCapitulo(usuario, nombre_manhwa))

    boton = Button(label="🔄️Actualizar capítulo", style=discord.ButtonStyle.success)
    boton.callback = boton_callback
    view.add_item(boton)

    return view
