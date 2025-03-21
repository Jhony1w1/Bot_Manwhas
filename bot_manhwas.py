import discord
from discord.ext import commands
from pymongo import MongoClient
from datetime import datetime
import os
from dotenv import load_dotenv
import logging
import re
import asyncio
from discord.ui import View, Button

load_dotenv()
# variables de entorno
MONGO_URL = os.getenv('MONGO_URL')
DISCORD_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
DATABASE_NAME = os.getenv('DATABASE_NAME')
COLLECTION_NAME = os.getenv('COLLECTION_NAME')
COLLECTION_NAME2 = os.getenv('COLLECTION_NAME2')
COLLECTION_NAME3 = os.getenv('COLLECTION_NAME3')

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

# muestra la lista de comandos del bot
@bot.command(name='info')
async def info(ctx):

    result = collection2.find_one({"usuario": str(ctx.author)})

    if result is None:
        await ctx.send("❌ No tienes permisos suficientes para realizar esta acción.")
        return

    embed = discord.Embed(
        title=f"🤖 ¡Hola! Soy {bot.user} 📚",
        description="Estoy aquí para ayudarte a gestionar tu colección de manhwas. Ya que olympus no ayuda",
        color=discord.Color.blue()
    )

    # Sección de Comandos
    embed.add_field(
        name="📋 Comandos Disponibles:",
        value=(
            "**• !info**\n"
            "  Muestra la información del bot\n\n"
            "**• !guardar [nombre],[capitulo],[link] (opcional)**\n"
            "  Guarda un nuevo manhwa en tu lista\n\n"
            "**• !listar**\n"
            "  Muestra todos tus manhwas guardados\n\n"
            "**• !listar [nombre]**\n"
            "  Busca un manhwa en tu lista y selecciona hasta que capitulo has leído\n\n"
            "**• !lector [nickname]**\n"
            "  Le asigna permisos a un usuario para poder guardar manhwas, mangas, manhuas en el bot\n\n"
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
@bot.command(name='lector')
async def admin(ctx, usuario: str):

    result = collection3.find_one({"usuario": str(ctx.author)})

    if result is None:
        await ctx.send("❌ No tienes permisos suficientes para realizar esta acción.")
        return

    # Crear registro
    nuevo_registro = {
        "usuario": usuario,
    }
    
    # Insertar en la base de datos
    collection3.insert_one(nuevo_registro)
    
    # Mensaje de confirmación con embed
    embed = discord.Embed(
        title="✅ Permisos concedidos", 
        color=discord.Color.green()
    )

    embed.set_footer(text=f"Guardado por {ctx.author}")

    await ctx.send(embed=embed)

@bot.command(name='guardar')
async def guardar(ctx, *, datos: str): # El argumento datos es una cadena que puede contener espacios, * captura toda la linea de texto
    try:
        
        result = collection2.find_one({"usuario": str(ctx.author)})

        if result is None:
            await ctx.send("❌ No tienes permisos suficientes para realizar esta acción.")
            return

        # Separar los datos por coma
        partes = [parte.strip() for parte in datos.split(',')]
        
        # Validar que tengamos al menos nombre y capítulo
        if len(partes) < 2:
            await ctx.send("❌ Formato incorrecto. Usa: nombre, capítulo, [link]")
            return
        
        # Extraer datos
        nombre = partes[0]
        
        # Convertir capítulo a entero, manejar posibles errores
        try:
            capitulo = int(partes[1])
        except ValueError:
            await ctx.send("❌ El capítulo debe ser un número válido.")
            return
        
        # Link es opcional
        link = partes[2] if len(partes) > 2 else None

        # Crear registro
        nuevo_registro = {
            "nombre_manhwa": nombre,
            "usuario": str(ctx.author),
            "fecha_guardado": datetime.now(),
            "capitulo": capitulo,
            "link": link
        }
        
        # Insertar en la base de datos
        collection.insert_one(nuevo_registro)
        
        # Mensaje de confirmación con embed
        embed = discord.Embed(
            title="✅ Manhwa Guardado", 
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
        print(e)

# listar uno o varios manhwas
@bot.command(name="listar")
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

    except Exception:
        await ctx.send("❌ Hubo un error al listar los manhwas.")

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

async def listar_por_nombre(ctx, nombre_manhwa):
    usuario = str(ctx.author)
    query = {"usuario": usuario, "nombre_manhwa": {"$regex": nombre_manhwa, "$options": "i"}}
    registros = list(collection.find(query))

    if not registros:
        await ctx.send("🔍 No se encontraron manhwas con ese nombre.")
        return

    registro = registros[0]  # Tomamos el primer resultado coincidente

    embed = discord.Embed(title=f"📚 Manhwa: {registro['nombre_manhwa']}", color=discord.Color.blue())
    valor_manhwa = (
        f"**Capítulo actual:** {registro['capitulo']}\n"
        f"**Fecha Guardado:** {registro['fecha_guardado'].strftime('%Y-%m-%d')}\n"
        f"**Link:** [Ir al manhwa]({registro['link']})"
    )
    embed.add_field(name="📖 Detalles", value=valor_manhwa, inline=False)

    # Enviar el mensaje con el botón
    view = crear_vista_boton(usuario, registro["nombre_manhwa"])
    message = await ctx.send(embed=embed, view=view)

    # Guardar la referencia
    manhwa_tracking[message.id] = {"usuario": usuario, "nombre_manhwa": registro["nombre_manhwa"]}

def crear_vista_boton(usuario, nombre_manhwa):
    """Crea una vista con un botón para actualizar el capítulo."""
    view = View()

    async def boton_callback(interaction: discord.Interaction):
        """Maneja la solicitud de actualización del capítulo."""
        if str(interaction.user) != usuario:
            await interaction.response.send_message("❌ No puedes actualizar este capítulo.", ephemeral=True)
            return

        await interaction.response.send_message("📖 ¿A qué capítulo deseas actualizar?", ephemeral=True)

        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel and m.content.isdigit()

        try:
            msg = await bot.wait_for("message", check=check, timeout=15)

            # Validación para asegurarse de que el mensaje sea un número
            try:
                nuevo_capitulo = int(msg.content)
            except ValueError:
                await interaction.channel.send("❌ El capítulo debe ser un número válido.")
                return  # Salir de la función o continuar con el flujo de error

            # Buscar el manhwa en la base de datos
            manhwa = collection.find_one({"usuario": usuario, "nombre_manhwa": {"$regex": f"^{re.escape(nombre_manhwa)}$", "$options": "i"}})

            if manhwa:
                result = collection.update_one(
                    {"_id": manhwa["_id"]},
                    {"$set": {"capitulo": nuevo_capitulo, "fecha_guardado": datetime.now()}}
                )

                if result.modified_count > 0:
                    await interaction.channel.send(f"✅ **{nombre_manhwa}** ha sido actualizado al capítulo **{nuevo_capitulo}**.")
                else:
                    await interaction.channel.send("❌ No se pudo actualizar el capítulo.")
            else:
                await interaction.channel.send(f"❌ No se encontró el manhwa '{nombre_manhwa}'.")

        except TimeoutError:
            await interaction.followup.send("⏳ No ingresaste el número del capítulo a tiempo.", ephemeral=True)

    # Crear el botón y agregarlo a la vista
    boton = Button(label="🔄️Actualizar capítulo", style=discord.ButtonStyle.success)
    boton.callback = boton_callback
    view.add_item(boton)

    return view

# Token del bot
bot.run(DISCORD_TOKEN)
