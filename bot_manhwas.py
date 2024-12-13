import discord
from discord.ext import commands
from pymongo import MongoClient
from datetime import datetime
import os
from dotenv import load_dotenv
import logging
import re
import asyncio

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

usuarios_que_listaron = {}

# Evento on_ready
@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")


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
            "**• !guardar [nombre],[capitulo],[link] (opcional)**\n"
            "  Guarda un nuevo manhwa en tu lista\n\n"
            "**• !listar**\n"
            "  Muestra todos tus manhwas guardados\n\n"
            "**• !listar [nombre]**\n"
            "  Busca un manhwa en tu lista y selecciona hasta que capitulo has leído"
        ),
        inline=False
    )

    # Pie de página
    embed.set_footer(
        text="Desarrollado por Jhony",
        icon_url=bot.user.avatar.url  # Reemplaza con tu ícono
    )

    await ctx.send(embed=embed)


@bot.command(name='admin')
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

@bot.command()
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



@bot.command()
async def listar(ctx, nombre_manhwa: str = None):
    try:

        result = collection2.find_one({"usuario": str(ctx.author)})

        if result is None:
            await ctx.send("❌ No tienes permisos suficientes para realizar esta acción.")
            return
        
        usuario = str(ctx.author)

        # Almacenar el usuario que ejecutó el comando
        usuarios_que_listaron['nombre'] = usuario

        # Filtrar por usuario y opcionalmente por nombre de manhwa
        query = {"usuario": usuario}
        if nombre_manhwa:
            query["nombre_manhwa"] = {"$regex": nombre_manhwa, "$options": "i"}  # Búsqueda parcial e insensible a mayúsculas

        registros = list(collection.find(query))
        if not registros:
            await ctx.send("🔍 No se encontraron manhwas para este usuario.")
            return

        embeds = []
        current_embed = discord.Embed(
            title=f"📚 Manhwas de {usuario}",
            color=discord.Color.blue()
        )

        if nombre_manhwa:
            # Mostrar el manhwa con su capítulo y enlaces a los siguientes capítulos
            for registro in registros[:1]:  # Solo mostrar el manhwa que coincida con el nombre
                valor_manhwa = (
                    f"**Capítulo actual:** {registro['capitulo']}\n"
                    f"**Fecha Guardado:** {registro['fecha_guardado'].strftime('%Y-%m-%d')}\n"
                    f"**Link:** [Ir al manhwa]({registro['link']})"
                )

                current_embed.add_field(
                    name=f"📖 {registro['nombre_manhwa']}",
                    value=valor_manhwa,
                    inline=False
                )

            embeds.append(current_embed)

            # Crear 5 embeds con los enlaces a los próximos 5 capítulos (cada uno en su propio embed)
            for i in range(1, 6):
                siguiente_capitulo = registro['capitulo'] + i
                link_capitulo = f"[Capítulo {siguiente_capitulo}](https://discord.com/channels/{ctx.guild.id}/{ctx.channel.id}/{str(registro['_id'])}/{siguiente_capitulo})"
                
                chapter_embed = discord.Embed(
                    title=f"📚 Capítulo {siguiente_capitulo} de {registro['nombre_manhwa']}",
                    color=discord.Color.green()
                )
                chapter_embed.add_field(
                    name=f"Capítulo {siguiente_capitulo}",
                    value=link_capitulo,
                    inline=False
                )

                embeds.append(chapter_embed)

        else:
            # Mostrar los primeros 5 manhwas sin enlaces a capítulos
            for registro in registros[-25:]:
                valor_manhwa = (
                    f"**Capítulo actual:** {registro['capitulo']}\n"
                    f"**Fecha Guardado:** {registro['fecha_guardado'].strftime('%Y-%m-%d')}"
                )

                current_embed.add_field(
                    name=f"📖 {registro['nombre_manhwa']}",
                    value=valor_manhwa,
                    inline=False
                )

            embeds.append(current_embed)

        # Enviar todos los embeds generados
        for embed in embeds:
            message = await ctx.send(embed=embed)

            # Solo agregar reacción si estamos en el contexto de un manhwa específico
            if nombre_manhwa:
                # Solo agregar la reacción a los embeds de capítulos
                if "Capítulo" in embed.title:
                    await message.add_reaction('✅')
                    
        # Esperar 30 segundos para permitir reacciones
        await asyncio.sleep(30)

        # Después del tiempo, limpiar el estado si aún no se procesó ninguna reacción
        if usuarios_que_listaron.get('nombre') == usuario:
            del usuarios_que_listaron['nombre']
            await ctx.send(f"⏳ Se agotó el tiempo para reaccionar.")

    except Exception as e:
        await ctx.send("❌ Hubo un error al listar los manhwas.")
        print(e)

@bot.event
async def on_reaction_add(reaction, user):
    if user == bot.user:
        return  # Ignorar las reacciones del bot
    
    if not usuarios_que_listaron:
        return

    # Verificar que el que reaccionó sea igual al que listó
    if str(user) != str(usuarios_que_listaron['nombre']):
        print("Entró, así que hay un error")
        await reaction.message.channel.send(f"❌ {user} no puedes reaccionar porque no listaste este manhwa.")
        return
            
    print("No hubo error")

    # Limpiar el diccionario sólo cuando se procesó correctamente
    del usuarios_que_listaron['nombre']

    # Verificar que la reacción sea de un capítulo (en este caso, '✅')
    if reaction.emoji == '✅':
        try:
            # Obtener el título del embed (nombre del manhwa)
            nombre_manhwa = reaction.message.embeds[0].title.split(" de ")[1].strip()

            message = reaction.message
            # Intentar extraer el capítulo del título del embed usando expresión regular
            match = re.search(r"Capítulo (\d+)", message.embeds[0].title)

            if match:
                capitulo = int(match.group(1))  # Extraemos el capítulo como número
            else:
                raise ValueError("No se pudo encontrar el capítulo en el título.")

            # Realizar la búsqueda en la base de datos de manera flexible
            manhwa = collection.find_one({"nombre_manhwa": {"$regex": f"^{re.escape(nombre_manhwa)}$", "$options": "i"}})

            if manhwa:
                # Actualizar el capítulo
                capitulo_siguiente = capitulo
                fecha_actualizacion = datetime.now()  # Fecha y hora actual
                result = collection.update_one(
                    {"_id": manhwa["_id"]},
                    {"$set": {"capitulo": capitulo_siguiente, "fecha_guardado": fecha_actualizacion}}
                )

                if result.modified_count > 0:
                    await reaction.message.channel.send(f"✅ El manhwa **{nombre_manhwa}** ha sido actualizado al capitulo **{capitulo}**.")
                else:
                    await reaction.message.channel.send("❌ No se pudo actualizar el capítulo.")
            else:
                await reaction.message.channel.send(f"❌ No se encontró el manhwa '{nombre_manhwa}'.")

        except Exception as e:
            await reaction.message.channel.send(f"❌ Error al procesar la reacción: {str(e)}")

# Token del bot
bot.run(DISCORD_TOKEN)
