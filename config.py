import os
import logging
from dotenv import load_dotenv

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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("bot_manhwas")

ESTADOS = {
    "leyendo": "📖 Leyendo",
    "favorito": "⭐ Favorito",
    "en_pausa": "⏸️ En pausa",
    "terminado": "✅ Terminado",
    "dropeado": "🗑️ Dropeado",
}

UMBRAL_DIAS_RECORDATORIO = 30  # días sin actualizar un manhwa "Leyendo" antes de considerarlo olvidado
