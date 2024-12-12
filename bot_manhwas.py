import discord
from discord.ext import commands
from pymongo import MongoClient
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()
# variables de entorno
MONGO_URL = os.getenv('MONGO_URL')
DISCORD_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
DATABASE_NAME = os.getenv('DATABASE_NAME')
COLLECTION_NAME = os.getenv('COLLECTION_NAME')

# Configuración del bot
intents = discord.Intents.default()
intents.message_content = True # Activa la intención de mensajes para detectar los eventos
intents.members = True  # Activa la intención de miembros para detectar los eventos
bot = commands.Bot(command_prefix="!", intents=intents)

# Conexión a MongoDB
client = MongoClient(MONGO_URL)
db = client[DATABASE_NAME]
collection = db[COLLECTION_NAME]

# Evento on_ready
@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")


@bot.command(name='info')
async def info(ctx):
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
            "  Busca un manhwa en tu lista"
        ),
        inline=False
    )

    # Pie de página
    embed.set_footer(
        text="Desarrollado por Jhony",
        icon_url=bot.user.avatar.url  # Reemplaza con tu ícono
    )

    await ctx.send(embed=embed)

@bot.command()
async def guardar(ctx, *, datos: str): # El argumento datos es una cadena que puede contener espacios, * captura toda la linea de texto
    try:
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
        usuario = str(ctx.author)
        
        # Filtrar por usuario y opcionalmente por nombre de manhwa
        query = {"usuario": usuario}
        if nombre_manhwa:
            query["nombre_manhwa"] = {"$regex": nombre_manhwa, "$options": "i"}  # Búsqueda parcial e insensible a mayúsculas

        registros = list(collection.find(query))
        if not registros:
            await ctx.send("🔍 No se encontraron manhwas para este usuario.")
            return

        # Crear un embed para una presentación más elegante
        embed = discord.Embed(
            title=f"📚 Manhwas de {usuario}",
            color=discord.Color.blue()
        )

        # Mostrar solo los primeros 5 manhwas para evitar saturar el mensaje
        for registro in registros[-10:]:
            # Crear un campo por cada manhwa
            valor_manhwa = (
                f"**Capítulo:** {registro['capitulo']}\n"
                f"**Fecha Guardado:** {registro['fecha_guardado'].strftime('%Y-%m-%d')}"
            )
            
            # Agregar enlace si está disponible
            if registro.get("link"):
                valor_manhwa += f"\n**Link:** [Ir al manhwa]({registro['link']})"
            
            embed.add_field(
                name=f"📖 {registro['nombre_manhwa']}", 
                value=valor_manhwa, 
                inline=False
            )

        # Añadir un pie de página con información adicional
        if len(registros) > 10:
            embed.set_footer(text=f"... y {len(registros) - 10} manhwas más")

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send("❌ Hubo un error al listar los manhwas.")
        print(e)

# Token del bot
bot.run(DISCORD_TOKEN)
