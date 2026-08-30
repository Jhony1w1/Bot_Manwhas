from pymongo import MongoClient

from config import MONGO_URL, DATABASE_NAME, COLLECTION_NAME, COLLECTION_NAME2, COLLECTION_NAME3

client = MongoClient(MONGO_URL)
db = client[DATABASE_NAME]

collection = db[COLLECTION_NAME]    # manhwas guardados por cada usuario
collection2 = db[COLLECTION_NAME2]  # usuarios con permiso de "lector" (pueden guardar/listar/etc.)
collection3 = db[COLLECTION_NAME3]  # usuarios con permiso para conceder/revocar el rol de lector
