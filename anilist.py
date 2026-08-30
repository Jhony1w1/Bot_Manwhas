"""Integración con la API pública de AniList (GraphQL, sin API key) para ayudar
a identificar manhwas/manhuas/mangas al guardarlos."""

import re
import asyncio

import aiohttp
import discord
from discord.ui import View, Button

from config import logger

ANILIST_API_URL = "https://graphql.anilist.co"

ANILIST_SEARCH_QUERY = """
query ($search: String) {
  Page(page: 1, perPage: 5) {
    media(search: $search, type: MANGA) {
      id
      title { romaji english native }
      format
      status
      chapters
      genres
      countryOfOrigin
      description(asHtml: false)
      coverImage { large }
      siteUrl
    }
  }
}
"""

TIPO_POR_PAIS_ANILIST = {
    "JP": "🇯🇵 Manga (Japón)",
    "KR": "🇰🇷 Manhwa (Corea)",
    "CN": "🇨🇳 Manhua (China)",
    "TW": "🇹🇼 Manhua (Taiwán)",
}

ESTADO_POR_ANILIST = {
    "FINISHED": "Finalizado",
    "RELEASING": "En emisión",
    "NOT_YET_RELEASED": "Aún no publicado",
    "CANCELLED": "Cancelado",
    "HIATUS": "En pausa",
}


async def buscar_en_anilist(nombre: str):
    """Busca un manga/manhwa/manhua en AniList. Devuelve una lista de resultados (vacía si no hay o falla la API)."""
    payload = {"query": ANILIST_SEARCH_QUERY, "variables": {"search": nombre}}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.post(ANILIST_API_URL, json=payload) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return (data.get("data") or {}).get("Page", {}).get("media", []) or []
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.error(f"Error consultando AniList: {e}")
        return []


def limpiar_descripcion_anilist(descripcion, max_len=300):
    """Quita las etiquetas HTML que devuelve AniList y recorta la descripción."""
    if not descripcion:
        return None
    texto = re.sub(r"<[^>]+>", "", descripcion).strip()
    if len(texto) > max_len:
        texto = texto[:max_len].rsplit(" ", 1)[0] + "…"
    return texto


def extraer_datos_anilist(candidato):
    """Extrae los campos que guardaremos en Mongo a partir de un resultado de AniList."""
    titulo = candidato.get("title", {})
    return {
        "imagen": (candidato.get("coverImage") or {}).get("large"),
        "anilist_id": candidato.get("id"),
        "titulo_romaji": titulo.get("romaji"),
        "titulo_ingles": titulo.get("english"),
        "titulo_nativo": titulo.get("native"),
        "anilist_url": candidato.get("siteUrl"),
    }


def construir_embed_candidato_anilist(candidato, indice, total):
    """Genera el embed con la info + imagen de un resultado de AniList, para que el usuario lo identifique."""
    titulo_data = candidato.get("title", {})
    titulo_principal = titulo_data.get("english") or titulo_data.get("romaji") or titulo_data.get("native") or "Sin título"
    titulo_alt = titulo_data.get("romaji") if titulo_data.get("romaji") != titulo_principal else titulo_data.get("native")

    tipo = TIPO_POR_PAIS_ANILIST.get(candidato.get("countryOfOrigin"), candidato.get("countryOfOrigin") or "Desconocido")
    estado = ESTADO_POR_ANILIST.get(candidato.get("status"), candidato.get("status") or "—")
    capitulos = candidato.get("chapters") or "En curso"

    embed = discord.Embed(
        title=titulo_principal,
        url=candidato.get("siteUrl"),
        description=limpiar_descripcion_anilist(candidato.get("description")),
        color=discord.Color.blue()
    )
    if titulo_alt:
        embed.add_field(name="Título alternativo", value=titulo_alt, inline=False)
    embed.add_field(name="Tipo", value=tipo, inline=True)
    embed.add_field(name="Estado en AniList", value=estado, inline=True)
    embed.add_field(name="Capítulos", value=str(capitulos), inline=True)
    if candidato.get("genres"):
        embed.add_field(name="Géneros", value=", ".join(candidato["genres"][:5]), inline=False)

    imagen = (candidato.get("coverImage") or {}).get("large")
    if imagen:
        embed.set_image(url=imagen)

    embed.set_footer(text=f"Resultado {indice + 1}/{total} en AniList — haz clic en la imagen para verla en grande")
    return embed


def crear_vista_busqueda_anilist(autor, candidatos, on_confirmar, on_manual, timeout=60):
    """Vista para navegar los resultados de AniList y confirmar cuál guardar.
    on_confirmar es async(interaction, candidato). on_manual es async(interaction)."""
    view = View(timeout=timeout)
    view.message = None
    estado = {"indice": 0}

    boton_confirmar = Button(label="✅ Es este", style=discord.ButtonStyle.success)
    boton_siguiente = Button(label="➡️ Siguiente resultado", style=discord.ButtonStyle.primary, disabled=len(candidatos) <= 1)
    boton_manual = Button(label="✏️ Ninguno, guardar manual", style=discord.ButtonStyle.secondary)

    async def confirmar_callback(interaction: discord.Interaction):
        if interaction.user != autor:
            await interaction.response.send_message("❌ No puedes usar este menú.", ephemeral=True)
            return
        for item in view.children:
            item.disabled = True
        await interaction.response.edit_message(view=view)
        await on_confirmar(interaction, candidatos[estado["indice"]])
        view.stop()

    async def siguiente_callback(interaction: discord.Interaction):
        if interaction.user != autor:
            await interaction.response.send_message("❌ No puedes usar este menú.", ephemeral=True)
            return
        estado["indice"] = (estado["indice"] + 1) % len(candidatos)
        embed = construir_embed_candidato_anilist(candidatos[estado["indice"]], estado["indice"], len(candidatos))
        await interaction.response.edit_message(embed=embed, view=view)

    async def manual_callback(interaction: discord.Interaction):
        if interaction.user != autor:
            await interaction.response.send_message("❌ No puedes usar este menú.", ephemeral=True)
            return
        for item in view.children:
            item.disabled = True
        await interaction.response.edit_message(view=view)
        await on_manual(interaction)
        view.stop()

    async def on_timeout():
        for item in view.children:
            item.disabled = True
        if view.message:
            try:
                await view.message.edit(view=view)
            except discord.HTTPException:
                pass

    boton_confirmar.callback = confirmar_callback
    boton_siguiente.callback = siguiente_callback
    boton_manual.callback = manual_callback
    view.on_timeout = on_timeout

    view.add_item(boton_confirmar)
    if len(candidatos) > 1:
        view.add_item(boton_siguiente)
    view.add_item(boton_manual)
    return view


def crear_vista_navegacion_anilist(autor, candidatos, timeout=60):
    """Vista de solo consulta: navega los resultados de AniList sin ninguna acción de guardado."""
    view = View(timeout=timeout)
    view.message = None
    estado = {"indice": 0}

    boton_anterior = Button(label="⬅️ Anterior", style=discord.ButtonStyle.primary, disabled=len(candidatos) <= 1)
    boton_siguiente = Button(label="➡️ Siguiente", style=discord.ButtonStyle.primary, disabled=len(candidatos) <= 1)

    async def actualizar(interaction: discord.Interaction):
        embed = construir_embed_candidato_anilist(candidatos[estado["indice"]], estado["indice"], len(candidatos))
        await interaction.response.edit_message(embed=embed, view=view)

    async def anterior_callback(interaction: discord.Interaction):
        if interaction.user != autor:
            await interaction.response.send_message("❌ No puedes usar este menú.", ephemeral=True)
            return
        estado["indice"] = (estado["indice"] - 1) % len(candidatos)
        await actualizar(interaction)

    async def siguiente_callback(interaction: discord.Interaction):
        if interaction.user != autor:
            await interaction.response.send_message("❌ No puedes usar este menú.", ephemeral=True)
            return
        estado["indice"] = (estado["indice"] + 1) % len(candidatos)
        await actualizar(interaction)

    async def on_timeout():
        for item in view.children:
            item.disabled = True
        if view.message:
            try:
                await view.message.edit(view=view)
            except discord.HTTPException:
                pass

    boton_anterior.callback = anterior_callback
    boton_siguiente.callback = siguiente_callback
    view.on_timeout = on_timeout

    view.add_item(boton_anterior)
    view.add_item(boton_siguiente)
    return view
