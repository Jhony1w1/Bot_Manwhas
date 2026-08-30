import discord
from discord.ext import commands
from discord import app_commands
from pymongo import MongoClient
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import logging
import re
import json
import io
import random
import asyncio
import aiohttp
from discord.ui import View, Button, Select, Modal, TextInput

load_dotenv()
# variables de entorno
MONGO_URL = os.getenv('MONGO_URL')
DISCORD_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
DATABASE_NAME = os.getenv('DATABASE_NAME')
COLLECTION_NAME = os.getenv('COLLECTION_NAME')
COLLECTION_NAME2 = os.getenv('COLLECTION_NAME2')
COLLECTION_NAME3 = os.getenv('COLLECTION_NAME3')

_variables_requeridas = {
    "MONGO_URL": MONGO_URL,
    "DISCORD_BOT_TOKEN": DISCORD_TOKEN,
    "DATABASE_NAME": DATABASE_NAME,
    "COLLECTION_NAME": COLLECTION_NAME,
    "COLLECTION_NAME2": COLLECTION_NAME2,
    "COLLECTION_NAME3": COLLECTION_NAME3,
}
_faltantes = [nombre for nombre, valor in _variables_requeridas.items() if not valor]
if _faltantes:
    raise RuntimeError(f"Faltan variables de entorno requeridas: {', '.join(_faltantes)}")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuración del bot
intents = discord.Intents.default()
intents.message_content = True # Activa la intención de mensajes para detectar los eventos
bot = commands.Bot(command_prefix="!", intents=intents)

# Conexión a MongoDB
client = MongoClient(MONGO_URL)
db = client[DATABASE_NAME]
collection = db[COLLECTION_NAME]
collection2 = db[COLLECTION_NAME2]
collection3 = db[COLLECTION_NAME3]

manhwa_tracking = {}  # Diccionario para rastrear mensajes y manhwas

ESTADOS = {
    "leyendo": "📖 Leyendo",
    "favorito": "⭐ Favorito",
    "en_pausa": "⏸️ En pausa",
    "terminado": "✅ Terminado",
    "dropeado": "🗑️ Dropeado",
}

UMBRAL_DIAS_RECORDATORIO = 14  # días sin actualizar un manhwa "Leyendo" antes de considerarlo olvidado

# --- Integración con AniList (búsqueda pública, sin API key) ---

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

# Evento on_ready
@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")
    try:
        sincronizados = await bot.tree.sync()
        logger.info(f"Sincronizados {len(sincronizados)} comandos slash.")
    except Exception as e:
        logger.error(f"Error sincronizando comandos slash: {e}")

@bot.event
async def on_command_error(ctx, error):
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
@bot.hybrid_command(name='info', description="Muestra la información y comandos del bot")
async def info(ctx):

    result = collection2.find_one({"usuario": str(ctx.author)})

    if result is None:
        await ctx.send("❌ No tienes permisos suficientes para realizar esta acción.")
        return

    embed = discord.Embed(
        title=f"🤖 ¡Hola! Soy {bot.user} 📚",
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
        ),
        inline=False
    )

    # Pie de página
    embed.set_footer(
        text="Desarrollado por Jhony",
        icon_url=bot.user.avatar.url  # Reemplaza con tu ícono
    )

    await ctx.send(embed=embed)

# concede permisos a un usuario para que pueda guardar manhwas en el bot, solo permitido por el admin
@bot.hybrid_command(name='lector', description="Da permisos de lector a un usuario del servidor")
@app_commands.describe(usuario="Usuario del servidor a quien dar permisos")
async def admin(ctx, usuario: discord.Member):

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
@bot.hybrid_command(name='revocar', description="Quita permisos de lector a un usuario")
@app_commands.describe(usuario="Nombre exacto guardado, o mención de un miembro actual del servidor")
async def revocar(ctx, *, usuario: str):

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

def extraer_partes(datos: str):
    """Separa 'datos' en [nombre, capitulo, link?]. Si el nombre contiene comas,
    debe envolverse entre [ ] o " " para que no se confunda con los separadores."""
    datos = datos.strip()

    if datos.startswith('[') and ']' in datos:
        cierre = datos.index(']')
        nombre = datos[1:cierre].strip()
        resto = datos[cierre + 1:].lstrip(', ').strip()
    elif datos.startswith('"') and datos.count('"') >= 2:
        cierre = datos.index('"', 1)
        nombre = datos[1:cierre].strip()
        resto = datos[cierre + 1:].lstrip(', ').strip()
    else:
        primer_coma = datos.find(',')
        if primer_coma == -1:
            return [datos]
        nombre = datos[:primer_coma].strip()
        resto = datos[primer_coma + 1:].strip()

    partes_resto = [p.strip() for p in resto.split(',')] if resto else []
    return [nombre] + partes_resto

async def guardar_o_actualizar(send_func, usuario, nombre, capitulo, link, datos_anilist=None):
    """Hace el upsert en Mongo y envía el embed de confirmación. Reutilizado por el flujo manual
    y por el flujo de confirmación con AniList."""
    filtro = {
        "usuario": usuario,
        "nombre_manhwa": {"$regex": f"^{re.escape(nombre)}$", "$options": "i"}
    }
    campos_set = {"capitulo": capitulo, "fecha_guardado": datetime.now()}
    if link:
        campos_set["link"] = link
    if datos_anilist:
        campos_set.update(datos_anilist)

    actualizacion = {
        "$set": campos_set,
        "$setOnInsert": {"nombre_manhwa": nombre, "usuario": usuario, "estado": "leyendo"}
    }

    resultado = collection.update_one(filtro, actualizacion, upsert=True)
    es_nuevo = resultado.upserted_id is not None

    embed = discord.Embed(
        title="✅ Manhwa Guardado" if es_nuevo else "🔄 Manhwa Actualizado",
        color=discord.Color.green()
    )
    embed.add_field(name="Nombre", value=nombre, inline=False)
    embed.add_field(name="Capítulo", value=capitulo, inline=False)
    if link:
        embed.add_field(name="Link", value=link, inline=False)
    if es_nuevo:
        embed.add_field(name="Estado", value=ESTADOS["leyendo"], inline=False)
    if datos_anilist and datos_anilist.get("imagen"):
        embed.set_thumbnail(url=datos_anilist["imagen"])
    embed.set_footer(text=f"Guardado por {usuario}")

    await send_func(embed=embed)

@bot.hybrid_command(name='guardar', description="Guarda o actualiza un manhwa en tu lista")
@app_commands.describe(datos="nombre, capítulo, link opcional. Si el nombre tiene comas, enciérralo entre [ ] o \" \"")
async def guardar(ctx, *, datos: str): # El argumento datos es una cadena que puede contener espacios, * captura toda la linea de texto
    try:

        result = collection2.find_one({"usuario": str(ctx.author)})

        if result is None:
            await ctx.send("❌ No tienes permisos suficientes para realizar esta acción.")
            return

        # Separar los datos, respetando nombres entre [ ] o " " que contengan comas
        partes = extraer_partes(datos)

        # Validar que tengamos al menos nombre y capítulo
        if len(partes) < 2:
            await ctx.send("❌ Formato incorrecto. Usa: nombre, capítulo, [link]")
            return

        # Extraer datos
        nombre = partes[0]

        # Convertir capítulo a entero, manejar posibles errores
        try:
            capitulo = float(partes[1])
        except ValueError:
            await ctx.send("❌ El capítulo debe ser un número válido.")
            return

        # Link es opcional
        link = partes[2] if len(partes) > 2 else None
        usuario = str(ctx.author)

        # Si el manhwa ya existe para este usuario, solo actualizamos (sin volver a buscar en AniList)
        ya_existe = collection.find_one({
            "usuario": usuario,
            "nombre_manhwa": {"$regex": f"^{re.escape(nombre)}$", "$options": "i"}
        }) is not None

        if ya_existe:
            await guardar_o_actualizar(ctx.send, usuario, nombre, capitulo, link)
            return

        # Es un manhwa nuevo: buscamos en AniList para ayudar a identificarlo (nombres en otro idioma, etc.)
        async with ctx.typing():
            candidatos = await buscar_en_anilist(nombre)

        if not candidatos:
            # No se encontró nada en AniList (o la API falló): se guarda libremente, como antes
            await guardar_o_actualizar(ctx.send, usuario, nombre, capitulo, link)
            return

        async def al_confirmar(interaction, candidato):
            datos_anilist = extraer_datos_anilist(candidato)
            await guardar_o_actualizar(interaction.followup.send, usuario, nombre, capitulo, link, datos_anilist)

        async def al_elegir_manual(interaction):
            await guardar_o_actualizar(interaction.followup.send, usuario, nombre, capitulo, link)

        embed = construir_embed_candidato_anilist(candidatos[0], 0, len(candidatos))
        vista = crear_vista_busqueda_anilist(ctx.author, candidatos, al_confirmar, al_elegir_manual)
        vista.message = await ctx.send(
            f"🔎 Encontré esto en AniList para \"{nombre}\". ¿Es tu manhwa?", embed=embed, view=vista
        )

    except Exception as e:
        await ctx.send("❌ Error al guardar el manhwa.")
        logger.error(f"Error en guardar: {e}")

# elimina un manhwa de la lista del usuario
@bot.hybrid_command(name='eliminar', description="Elimina un manhwa de tu lista")
@app_commands.describe(nombre_manhwa="Nombre (o parte) del manhwa a eliminar")
async def eliminar(ctx, *, nombre_manhwa: str):
    try:
        result = collection2.find_one({"usuario": str(ctx.author)})

        if result is None:
            await ctx.send("❌ No tienes permisos suficientes para realizar esta acción.")
            return

        usuario = str(ctx.author)
        filtro = {
            "usuario": usuario,
            "nombre_manhwa": {"$regex": re.escape(nombre_manhwa), "$options": "i"}
        }
        registros = list(collection.find(filtro))

        if not registros:
            await ctx.send(f"❌ No se encontró '{nombre_manhwa}' en tu lista.")
            return

        async def solicitar_confirmacion(send_func, registro):
            async def eliminar_registro():
                collection.delete_one({"_id": registro["_id"]})
                return f"🗑️ **{registro['nombre_manhwa']}** eliminado de tu lista."

            view = crear_vista_confirmacion(
                ctx.author, eliminar_registro,
                mensaje_cancelado="❌ Eliminación cancelada.",
                texto_confirmar="✅ Eliminar"
            )
            view.message = await send_func(
                f"⚠️ ¿Seguro que deseas eliminar **{registro['nombre_manhwa']}**?", view=view
            )

        if len(registros) > 1:
            async def al_seleccionar(interaction, registro):
                await solicitar_confirmacion(interaction.followup.send, registro)

            selector = crear_selector_manhwas(
                ctx.author, registros, al_seleccionar, placeholder="Elige cuál eliminar..."
            )
            selector.message = await ctx.send("🔍 Se encontraron varias coincidencias, elige cuál eliminar:", view=selector)
            return

        await solicitar_confirmacion(ctx.send, registros[0])

    except Exception as e:
        await ctx.send("❌ Error al eliminar el manhwa.")
        logger.error(f"Error en eliminar: {e}")

# cambia el estado de lectura de un manhwa (leyendo, favorito, en pausa, terminado, dropeado)
@bot.hybrid_command(name='estado', description="Cambia el estado de lectura de un manhwa")
@app_commands.describe(nombre_manhwa="Nombre (o parte) del manhwa")
async def estado(ctx, *, nombre_manhwa: str):
    try:
        result = collection2.find_one({"usuario": str(ctx.author)})

        if result is None:
            await ctx.send("❌ No tienes permisos suficientes para realizar esta acción.")
            return

        usuario = str(ctx.author)
        filtro = {
            "usuario": usuario,
            "nombre_manhwa": {"$regex": re.escape(nombre_manhwa), "$options": "i"}
        }
        registros = list(collection.find(filtro))

        if not registros:
            await ctx.send(f"❌ No se encontró '{nombre_manhwa}' en tu lista.")
            return

        async def solicitar_estado(send_func, registro):
            view = crear_selector_estado(ctx.author, registro)
            view.message = await send_func(
                f"📋 Elige el nuevo estado para **{registro['nombre_manhwa']}**:", view=view
            )

        if len(registros) > 1:
            async def al_seleccionar(interaction, registro):
                await solicitar_estado(interaction.followup.send, registro)

            selector = crear_selector_manhwas(
                ctx.author, registros, al_seleccionar, placeholder="Elige un manhwa..."
            )
            selector.message = await ctx.send("🔍 Se encontraron varias coincidencias, elige una:", view=selector)
            return

        await solicitar_estado(ctx.send, registros[0])

    except Exception as e:
        await ctx.send("❌ Error al cambiar el estado.")
        logger.error(f"Error en estado: {e}")

# elige un manhwa al azar de tu lista (para cuando no sabes qué leer)
@bot.hybrid_command(name='random', description="Elige un manhwa al azar de tu lista para leer")
async def elegir_random(ctx):
    try:
        result = collection2.find_one({"usuario": str(ctx.author)})
        if result is None:
            await ctx.send("❌ No tienes permisos suficientes para realizar esta acción.")
            return

        usuario = str(ctx.author)
        registros = list(collection.find({"usuario": usuario}))

        if not registros:
            await ctx.send("🔍 No se encontraron manhwas para este usuario.")
            return

        # Prioriza manhwas que no estén terminados o dropeados; si no hay, elige de toda la lista
        candidatos = [r for r in registros if r.get("estado", "leyendo") not in ("terminado", "dropeado")]
        if not candidatos:
            candidatos = registros

        registro = random.choice(candidatos)
        await enviar_detalle_manhwa(ctx.send, usuario, registro)

    except Exception as e:
        await ctx.send("❌ Error al elegir un manhwa al azar.")
        logger.error(f"Error en random: {e}")

# muestra los manhwas "Leyendo" que llevan mucho tiempo sin actualizarse
@bot.hybrid_command(
    name='recordatorios',
    description=f"Muestra los manhwas que llevas más de {UMBRAL_DIAS_RECORDATORIO} días sin actualizar"
)
async def recordatorios(ctx):
    try:
        result = collection2.find_one({"usuario": str(ctx.author)})
        if result is None:
            await ctx.send("❌ No tienes permisos suficientes para realizar esta acción.")
            return

        usuario = str(ctx.author)
        limite = datetime.now() - timedelta(days=UMBRAL_DIAS_RECORDATORIO)
        registros = list(collection.find({
            "usuario": usuario,
            "estado": "leyendo",
            "fecha_guardado": {"$lt": limite}
        }))

        if not registros:
            await ctx.send(f"✅ No tienes manhwas en Leyendo con más de {UMBRAL_DIAS_RECORDATORIO} días sin actualizar. ¡Vas al día!")
            return

        registros.sort(key=lambda r: r["fecha_guardado"])

        embed = discord.Embed(
            title="⏰ Manhwas que quizás olvidaste",
            description=f"Llevan más de {UMBRAL_DIAS_RECORDATORIO} días sin actualizarse:",
            color=discord.Color.orange()
        )
        for r in registros[:25]:
            dias = (datetime.now() - r["fecha_guardado"]).days
            embed.add_field(
                name=f"📖 {r['nombre_manhwa']}",
                value=f"Cap. {r['capitulo']:g} · hace {dias} días",
                inline=False
            )

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send("❌ Error al generar los recordatorios.")
        logger.error(f"Error en recordatorios: {e}")

# muestra estadísticas de la colección del usuario
@bot.hybrid_command(name='stats', description="Muestra estadísticas de tu colección de manhwas")
async def stats(ctx):
    try:
        result = collection2.find_one({"usuario": str(ctx.author)})
        if result is None:
            await ctx.send("❌ No tienes permisos suficientes para realizar esta acción.")
            return

        usuario = str(ctx.author)
        registros = list(collection.find({"usuario": usuario}))

        if not registros:
            await ctx.send("🔍 No se encontraron manhwas para este usuario.")
            return

        total_manhwas = len(registros)
        total_capitulos = sum(r.get("capitulo", 0) for r in registros)

        conteo_estados = {valor: 0 for valor in ESTADOS}
        for r in registros:
            estado_actual = r.get("estado", "leyendo")
            conteo_estados[estado_actual] = conteo_estados.get(estado_actual, 0) + 1

        mas_avanzado = max(registros, key=lambda r: r.get("capitulo", 0))

        embed = discord.Embed(title=f"📊 Estadísticas de {usuario}", color=discord.Color.gold())
        embed.add_field(name="📚 Total de manhwas", value=str(total_manhwas), inline=True)
        embed.add_field(name="📖 Capítulos acumulados", value=f"{total_capitulos:g}", inline=True)
        embed.add_field(
            name="🏆 Más avanzado",
            value=f"{mas_avanzado['nombre_manhwa']} (cap. {mas_avanzado['capitulo']:g})",
            inline=False
        )

        desglose = "\n".join(f"{ESTADOS[valor]}: {conteo_estados[valor]}" for valor in ESTADOS)
        embed.add_field(name="📋 Por estado", value=desglose, inline=False)

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send("❌ Error al generar las estadísticas.")
        logger.error(f"Error en stats: {e}")

# exporta la lista del usuario como respaldo en formato JSON
@bot.hybrid_command(name='exportar', description="Exporta tu lista de manhwas como archivo de respaldo (JSON)")
async def exportar(ctx):
    try:
        result = collection2.find_one({"usuario": str(ctx.author)})
        if result is None:
            await ctx.send("❌ No tienes permisos suficientes para realizar esta acción.")
            return

        usuario = str(ctx.author)
        registros = list(collection.find({"usuario": usuario}))

        if not registros:
            await ctx.send("🔍 No se encontraron manhwas para este usuario.")
            return

        datos_exportables = [
            {
                "nombre_manhwa": r.get("nombre_manhwa"),
                "capitulo": r.get("capitulo"),
                "link": r.get("link"),
                "estado": r.get("estado", "leyendo"),
                "fecha_guardado": r["fecha_guardado"].isoformat() if r.get("fecha_guardado") else None,
                "imagen": r.get("imagen"),
                "anilist_id": r.get("anilist_id"),
                "titulo_romaji": r.get("titulo_romaji"),
                "titulo_ingles": r.get("titulo_ingles"),
                "titulo_nativo": r.get("titulo_nativo"),
                "anilist_url": r.get("anilist_url"),
            }
            for r in registros
        ]

        contenido = json.dumps(datos_exportables, ensure_ascii=False, indent=2)
        archivo = discord.File(io.BytesIO(contenido.encode("utf-8")), filename="manhwas_backup.json")

        await ctx.send(f"📦 Aquí tienes tu respaldo con {len(datos_exportables)} manhwa(s).", file=archivo)

    except Exception as e:
        await ctx.send("❌ Error al exportar tu lista.")
        logger.error(f"Error en exportar: {e}")

# importa manhwas desde un archivo de respaldo generado por !exportar
@bot.hybrid_command(name='importar', description="Importa manhwas desde un archivo de respaldo JSON")
@app_commands.describe(archivo="Archivo .json generado previamente con /exportar")
async def importar(ctx, archivo: discord.Attachment):
    try:
        result = collection2.find_one({"usuario": str(ctx.author)})
        if result is None:
            await ctx.send("❌ No tienes permisos suficientes para realizar esta acción.")
            return

        if not archivo.filename.lower().endswith(".json"):
            await ctx.send("❌ El archivo debe ser un .json (como el que genera `!exportar`).")
            return

        if archivo.size > 2 * 1024 * 1024:
            await ctx.send("❌ El archivo es demasiado grande (máximo 2 MB).")
            return

        contenido = await archivo.read()
        try:
            datos = json.loads(contenido.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            await ctx.send("❌ El archivo no es un JSON válido.")
            return

        if not isinstance(datos, list):
            await ctx.send("❌ Formato inválido: se esperaba una lista de manhwas.")
            return

        usuario = str(ctx.author)
        importados = 0
        actualizados = 0
        omitidos = 0

        for item in datos:
            if not isinstance(item, dict):
                omitidos += 1
                continue

            nombre = item.get("nombre_manhwa")
            capitulo = item.get("capitulo")

            if not nombre or capitulo is None:
                omitidos += 1
                continue

            try:
                capitulo = float(capitulo)
            except (TypeError, ValueError):
                omitidos += 1
                continue

            estado_valor = item.get("estado", "leyendo")
            if estado_valor not in ESTADOS:
                estado_valor = "leyendo"

            try:
                fecha_guardado = datetime.fromisoformat(item["fecha_guardado"]) if item.get("fecha_guardado") else datetime.now()
            except (ValueError, TypeError):
                fecha_guardado = datetime.now()

            campos_set = {"capitulo": capitulo, "estado": estado_valor, "fecha_guardado": fecha_guardado}
            if item.get("link"):
                campos_set["link"] = item["link"]
            for campo_anilist in ("imagen", "anilist_id", "titulo_romaji", "titulo_ingles", "titulo_nativo", "anilist_url"):
                if item.get(campo_anilist):
                    campos_set[campo_anilist] = item[campo_anilist]

            filtro = {
                "usuario": usuario,
                "nombre_manhwa": {"$regex": f"^{re.escape(nombre)}$", "$options": "i"}
            }
            actualizacion = {
                "$set": campos_set,
                "$setOnInsert": {"nombre_manhwa": nombre, "usuario": usuario}
            }

            resultado = collection.update_one(filtro, actualizacion, upsert=True)
            if resultado.upserted_id is not None:
                importados += 1
            else:
                actualizados += 1

        await ctx.send(
            f"📥 Importación completa: **{importados}** nuevo(s), **{actualizados}** actualizado(s)"
            + (f", **{omitidos}** omitido(s) por datos inválidos." if omitidos else ".")
        )

    except Exception as e:
        await ctx.send("❌ Error al importar el archivo.")
        logger.error(f"Error en importar: {e}")

# listar uno o varios manhwas
@bot.hybrid_command(name="listar", description="Lista tus manhwas guardados o busca uno por nombre")
@app_commands.describe(nombre_manhwa="Nombre (o parte) del manhwa a buscar (opcional)")
async def listar(ctx, *, nombre_manhwa: str = None):
    try:
        result = collection2.find_one({"usuario": str(ctx.author)})
        if result is None:
            await ctx.send("❌ No tienes permisos suficientes para realizar esta acción.")
            return

        if nombre_manhwa:
            await listar_por_nombre(ctx, nombre_manhwa)
        else:
            await listar_todos(ctx)

    except Exception as e:
        await ctx.send("❌ Hubo un error al listar los manhwas.")
        logger.error(f"Error en listar: {e}")

async def autocompletar_manhwa(interaction: discord.Interaction, current: str):
    """Sugiere nombres de manhwas ya guardados por el usuario para los slash commands."""
    usuario = str(interaction.user)
    query = {"usuario": usuario, "nombre_manhwa": {"$regex": re.escape(current), "$options": "i"}}
    registros = collection.find(query).limit(25)
    return [
        app_commands.Choice(name=r["nombre_manhwa"][:100], value=r["nombre_manhwa"])
        for r in registros
    ]

listar.autocomplete("nombre_manhwa")(autocompletar_manhwa)
eliminar.autocomplete("nombre_manhwa")(autocompletar_manhwa)
estado.autocomplete("nombre_manhwa")(autocompletar_manhwa)

async def listar_todos(ctx):
    usuario = str(ctx.author)
    query = {"usuario": usuario}
    registros = list(collection.find(query))

    if not registros:
        await ctx.send("🔍 No se encontraron manhwas para este usuario.")
        return

    # Variables para la paginación
    pagina_actual = 0
    manhwas_por_pagina = 25
    total_paginas = (len(registros) - 1) // manhwas_por_pagina + 1

    async def obtener_embed(pagina):
        """Genera un embed con los manhwas de la página dada."""
        inicio = pagina * manhwas_por_pagina
        fin = inicio + manhwas_por_pagina
        registros_pagina = registros[inicio:fin]

        embed = discord.Embed(
            title=f"📚 Manhwas de {usuario} (Página {pagina + 1}/{total_paginas})",
            color=discord.Color.blue()
        )

        for registro in registros_pagina:
            estado_valor = registro.get("estado", "leyendo")
            estado = ESTADOS.get(estado_valor, ESTADOS["leyendo"])
            dias_inactivo = (datetime.now() - registro["fecha_guardado"]).days
            olvidado = estado_valor == "leyendo" and dias_inactivo >= UMBRAL_DIAS_RECORDATORIO

            valor_manhwa = (
                f"**Capítulo actual:** {registro['capitulo']}\n"
                f"**Estado:** {estado}\n"
                f"**Fecha Guardado:** {registro['fecha_guardado'].strftime('%Y-%m-%d')}"
            )
            if olvidado:
                valor_manhwa += f"\n⏰ *Sin actualizar hace {dias_inactivo} días*"

            prefijo = "⏰ " if olvidado else "📖 "
            embed.add_field(name=f"{prefijo}{registro['nombre_manhwa']}", value=valor_manhwa, inline=False)

        return embed

    async def actualizar_mensaje(interaction, pagina):
        """Edita el mensaje con la nueva página del embed."""
        nonlocal pagina_actual
        pagina_actual = pagina
        view = crear_vista()
        await interaction.response.defer()
        await interaction.message.edit(embed=await obtener_embed(pagina_actual), view=view)

    def crear_vista():
        """Crea los botones de paginación."""
        view = View(timeout=60)

        boton_anterior = Button(label="⬅️ Anterior", style=discord.ButtonStyle.primary, disabled=(pagina_actual == 0))
        boton_siguiente = Button(label="➡️ Siguiente", style=discord.ButtonStyle.primary, disabled=(pagina_actual >= total_paginas - 1))

        async def anterior_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message("❌ No puedes controlar esta lista.", ephemeral=True)
                return
            if pagina_actual > 0:
                await actualizar_mensaje(interaction, pagina_actual - 1)

        async def siguiente_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message("❌ No puedes controlar esta lista.", ephemeral=True)
                return
            if pagina_actual < total_paginas - 1:
                await actualizar_mensaje(interaction, pagina_actual + 1)

        boton_anterior.callback = anterior_callback
        boton_siguiente.callback = siguiente_callback

        view.add_item(boton_anterior)
        view.add_item(boton_siguiente)
        return view

    # Enviar el mensaje inicial con la primera página
    await ctx.send(embed=await obtener_embed(pagina_actual), view=crear_vista())

async def enviar_detalle_manhwa(send_func, usuario, registro):
    """Envía el embed de detalle de un manhwa junto con el botón de actualizar capítulo."""
    estado = ESTADOS.get(registro.get("estado", "leyendo"), ESTADOS["leyendo"])
    embed = discord.Embed(title=f"📚 Manhwa: {registro['nombre_manhwa']}", color=discord.Color.blue())
    valor_manhwa = (
        f"**Capítulo actual:** {registro['capitulo']}\n"
        f"**Estado:** {estado}\n"
        f"**Fecha Guardado:** {registro['fecha_guardado'].strftime('%Y-%m-%d')}\n"
        f"**Link:** [Ir al manhwa]({registro['link']})"
    )
    embed.add_field(name="📖 Detalles", value=valor_manhwa, inline=False)

    titulo_alt = registro.get("titulo_ingles") or registro.get("titulo_romaji")
    if titulo_alt and titulo_alt.lower() != registro["nombre_manhwa"].lower():
        embed.add_field(name="Título alternativo (AniList)", value=titulo_alt, inline=False)

    if registro.get("imagen"):
        embed.set_image(url=registro["imagen"])  # clic en la imagen la expande en Discord

    view = crear_vista_boton(usuario, registro["nombre_manhwa"])
    message = await send_func(embed=embed, view=view)

    manhwa_tracking[message.id] = {"usuario": usuario, "nombre_manhwa": registro["nombre_manhwa"]}

async def listar_por_nombre(ctx, nombre_manhwa):
    usuario = str(ctx.author)
    query = {"usuario": usuario, "nombre_manhwa": {"$regex": re.escape(nombre_manhwa), "$options": "i"}}
    registros = list(collection.find(query))

    if not registros:
        await ctx.send("🔍 No se encontraron manhwas con ese nombre.")
        return

    if len(registros) > 1:
        async def al_seleccionar(interaction, registro):
            await enviar_detalle_manhwa(interaction.followup.send, usuario, registro)

        selector = crear_selector_manhwas(
            ctx.author, registros, al_seleccionar, placeholder="Elige un manhwa para ver detalles..."
        )
        selector.message = await ctx.send("🔍 Se encontraron varias coincidencias, elige una:", view=selector)
        return

    await enviar_detalle_manhwa(ctx.send, usuario, registros[0])

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

# Token del bot
bot.run(DISCORD_TOKEN)
