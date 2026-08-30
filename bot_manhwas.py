import discord
from discord.ext import commands
from discord import app_commands
from pymongo import MongoClient
from datetime import datetime
import os
from dotenv import load_dotenv
import logging
import re
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

    # Sección de Comandos
    embed.add_field(
        name="📋 Comandos Disponibles:",
        value=(
            "**• info**\n"
            "  Muestra la información del bot\n\n"
            "**• guardar nombre, capitulo, link (opcional)**\n"
            "  Guarda un nuevo manhwa en tu lista\n"
            "  Si el nombre tiene comas, enciérralo entre [ ] o \" \": !guardar [Solo Leveling, Ragnarok], 12\n\n"
            "**• listar**\n"
            "  Muestra todos tus manhwas guardados\n\n"
            "**• listar [nombre]**\n"
            "  Busca un manhwa en tu lista y selecciona hasta que capitulo has leído\n\n"
            "**• eliminar [nombre]**\n"
            "  Elimina un manhwa de tu lista\n\n"
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
            "• `revocar` — le quita permisos de lector a un usuario.\n\n"
            "**Slash commands**\n"
            "• Todos los comandos ahora también funcionan con `/`, con autocompletado nativo de Discord.\n"
            "• `/lector` te deja elegir al usuario directamente desde un selector, sin escribir el nombre.\n"
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

        # Upsert por usuario + nombre (case-insensitive) para no duplicar el manhwa
        filtro = {
            "usuario": usuario,
            "nombre_manhwa": {"$regex": f"^{re.escape(nombre)}$", "$options": "i"}
        }
        campos_set = {"capitulo": capitulo, "fecha_guardado": datetime.now()}
        if link:
            campos_set["link"] = link

        actualizacion = {
            "$set": campos_set,
            "$setOnInsert": {"nombre_manhwa": nombre, "usuario": usuario}
        }

        resultado = collection.update_one(filtro, actualizacion, upsert=True)
        es_nuevo = resultado.upserted_id is not None

        # Mensaje de confirmación con embed
        embed = discord.Embed(
            title="✅ Manhwa Guardado" if es_nuevo else "🔄 Manhwa Actualizado",
            color=discord.Color.green()
        )
        embed.add_field(name="Nombre", value=nombre, inline=False)
        embed.add_field(name="Capítulo", value=capitulo, inline=False)
        if link:
            embed.add_field(name="Link", value=link, inline=False)
        embed.set_footer(text=f"Guardado por {ctx.author}")

        await ctx.send(embed=embed)

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
            valor_manhwa = (
                f"**Capítulo actual:** {registro['capitulo']}\n"
                f"**Fecha Guardado:** {registro['fecha_guardado'].strftime('%Y-%m-%d')}"
            )
            embed.add_field(name=f"📖 {registro['nombre_manhwa']}", value=valor_manhwa, inline=False)

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
            if pagina_actual > 0:
                await actualizar_mensaje(interaction, pagina_actual - 1)

        async def siguiente_callback(interaction: discord.Interaction):
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
    embed = discord.Embed(title=f"📚 Manhwa: {registro['nombre_manhwa']}", color=discord.Color.blue())
    valor_manhwa = (
        f"**Capítulo actual:** {registro['capitulo']}\n"
        f"**Fecha Guardado:** {registro['fecha_guardado'].strftime('%Y-%m-%d')}\n"
        f"**Link:** [Ir al manhwa]({registro['link']})"
    )
    embed.add_field(name="📖 Detalles", value=valor_manhwa, inline=False)

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

def crear_selector_manhwas(autor, registros, on_seleccionar, placeholder="Elige un manhwa...", timeout=30):
    """Menú desplegable para elegir un manhwa entre varias coincidencias.
    on_seleccionar es un callback async(interaction, registro)."""
    view = View(timeout=timeout)
    view.message = None

    registros_por_id = {str(r["_id"]): r for r in registros[:25]}
    opciones = [
        discord.SelectOption(label=r["nombre_manhwa"][:100], value=str(r["_id"]))
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
