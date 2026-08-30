"""Comandos principales: guardar, listar, eliminar, estado, random, recordatorios, stats, exportar/importar."""

import re
import json
import io
import random
from datetime import datetime, timedelta

import discord
from discord.ext import commands
from discord import app_commands

from config import logger, ESTADOS, UMBRAL_DIAS_RECORDATORIO
from database import collection, collection2
from ui import crear_vista_confirmacion, crear_selector_estado, crear_selector_manhwas, crear_vista_boton
from anilist import (
    buscar_en_anilist,
    extraer_datos_anilist,
    construir_embed_candidato_anilist,
    crear_vista_busqueda_anilist,
    crear_vista_navegacion_anilist,
)

manhwa_tracking = {}  # Diccionario para rastrear mensajes y manhwas


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
        view = discord.ui.View(timeout=60)

        boton_anterior = discord.ui.Button(label="⬅️ Anterior", style=discord.ButtonStyle.primary, disabled=(pagina_actual == 0))
        boton_siguiente = discord.ui.Button(label="➡️ Siguiente", style=discord.ButtonStyle.primary, disabled=(pagina_actual >= total_paginas - 1))

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


async def autocompletar_manhwa(interaction: discord.Interaction, current: str):
    """Sugiere nombres de manhwas ya guardados por el usuario para los slash commands."""
    usuario = str(interaction.user)
    query = {"usuario": usuario, "nombre_manhwa": {"$regex": re.escape(current), "$options": "i"}}
    registros = collection.find(query).limit(25)
    return [
        app_commands.Choice(name=r["nombre_manhwa"][:100], value=r["nombre_manhwa"])
        for r in registros
    ]


class Manhwas(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name='guardar', description="Guarda o actualiza un manhwa en tu lista")
    @app_commands.describe(datos="nombre, capítulo, link opcional. Si el nombre tiene comas, enciérralo entre [ ] o \" \"")
    async def guardar(self, ctx, *, datos: str):  # El argumento datos es una cadena que puede contener espacios, * captura toda la linea de texto
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

    # busca un manga/manhwa/manhua en AniList sin guardar nada, solo para identificarlo
    @commands.hybrid_command(name='buscador', description="Busca un manga/manhwa/manhua en AniList sin guardarlo")
    @app_commands.describe(nombre="Nombre a buscar en AniList")
    async def buscador(self, ctx, *, nombre: str):
        try:
            result = collection2.find_one({"usuario": str(ctx.author)})
            if result is None:
                await ctx.send("❌ No tienes permisos suficientes para realizar esta acción.")
                return

            async with ctx.typing():
                candidatos = await buscar_en_anilist(nombre)

            if not candidatos:
                await ctx.send(f"🔍 No se encontró nada en AniList para \"{nombre}\".")
                return

            embed = construir_embed_candidato_anilist(candidatos[0], 0, len(candidatos))
            vista = crear_vista_navegacion_anilist(ctx.author, candidatos)
            vista.message = await ctx.send(embed=embed, view=vista)

        except Exception as e:
            await ctx.send("❌ Error al buscar en AniList.")
            logger.error(f"Error en buscador: {e}")

    # elimina un manhwa de la lista del usuario
    @commands.hybrid_command(name='eliminar', description="Elimina un manhwa de tu lista")
    @app_commands.describe(nombre_manhwa="Nombre (o parte) del manhwa a eliminar")
    async def eliminar(self, ctx, *, nombre_manhwa: str):
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

    @eliminar.autocomplete("nombre_manhwa")
    async def eliminar_autocomplete(self, interaction: discord.Interaction, current: str):
        return await autocompletar_manhwa(interaction, current)

    # cambia el estado de lectura de un manhwa (leyendo, favorito, en pausa, terminado, dropeado)
    @commands.hybrid_command(name='estado', description="Cambia el estado de lectura de un manhwa")
    @app_commands.describe(nombre_manhwa="Nombre (o parte) del manhwa")
    async def estado(self, ctx, *, nombre_manhwa: str):
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

    @estado.autocomplete("nombre_manhwa")
    async def estado_autocomplete(self, interaction: discord.Interaction, current: str):
        return await autocompletar_manhwa(interaction, current)

    # elige un manhwa al azar de tu lista (para cuando no sabes qué leer)
    @commands.hybrid_command(name='random', description="Elige un manhwa al azar de tu lista para leer")
    async def elegir_random(self, ctx):
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
    @commands.hybrid_command(
        name='recordatorios',
        description=f"Muestra los manhwas que llevas más de {UMBRAL_DIAS_RECORDATORIO} días sin actualizar"
    )
    async def recordatorios(self, ctx):
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
    @commands.hybrid_command(name='stats', description="Muestra estadísticas de tu colección de manhwas")
    async def stats(self, ctx):
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
    @commands.hybrid_command(name='exportar', description="Exporta tu lista de manhwas como archivo de respaldo (JSON)")
    async def exportar(self, ctx):
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
    @commands.hybrid_command(name='importar', description="Importa manhwas desde un archivo de respaldo JSON")
    @app_commands.describe(archivo="Archivo .json generado previamente con /exportar")
    async def importar(self, ctx, archivo: discord.Attachment):
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
    @commands.hybrid_command(name="listar", description="Lista tus manhwas guardados o busca uno por nombre")
    @app_commands.describe(nombre_manhwa="Nombre (o parte) del manhwa a buscar (opcional)")
    async def listar(self, ctx, *, nombre_manhwa: str = None):
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

    @listar.autocomplete("nombre_manhwa")
    async def listar_autocomplete(self, interaction: discord.Interaction, current: str):
        return await autocompletar_manhwa(interaction, current)


async def setup(bot):
    await bot.add_cog(Manhwas(bot))
