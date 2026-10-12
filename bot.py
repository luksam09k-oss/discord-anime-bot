from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import random
import re
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ---------------------------------------------------------------------------
# Configuración general
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger("interaction-bot")
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

INTERACCIONES: dict[str, dict[str, str]] = {
    "hi": {
        "descripcion": "Saluda amistosamente a alguien",
        "verbo": "saluda a",
        "verbo_vuelta": "le devuelve el saludo a",
        "verbo_solo": "saludó a todos alegremente",
        "boton_texto": "Saludar",
        "boton_emoji": "👋",
    },
    "hug": {
        "descripcion": "Dale un cálido abrazo a un usuario",
        "verbo": "abraza a",
        "verbo_vuelta": "le devuelve el abrazo a",
        "verbo_solo": "necesita un abrazo y se abraza a sí mismo",
        "boton_texto": "Devolver abrazo",
        "boton_emoji": "🫂",
    },
    "pat": {
        "descripcion": "Dale una caricia en la cabeza a alguien",
        "verbo": "acaricia a",
        "verbo_vuelta": "le devuelve la caricia a",
        "verbo_solo": "quiere mimos y se da palmaditas",
        "boton_texto": "Devolver caricia",
        "boton_emoji": "🐾",
    },
}

# Datos en memoria: se descargan de Google Drive al iniciar el bot.
GIF_LIBRARY: dict[str, list[dict[str, Any]]] = {}


def _env_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Falta configurar la variable de entorno {name} en Render.")
    return value


def _make_drive_service():
    """Crea el cliente autenticado de Drive sin guardar la clave en el repositorio."""
    credentials_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    credentials_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()

    if credentials_json:
        try:
            credentials_info = json.loads(credentials_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "GOOGLE_SERVICE_ACCOUNT_JSON no contiene un JSON válido. "
                "Copia el contenido completo del archivo JSON de Google Cloud."
            ) from exc
        credentials = service_account.Credentials.from_service_account_info(
            credentials_info, scopes=DRIVE_SCOPES
        )
    elif credentials_path:
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=DRIVE_SCOPES
        )
    else:
        raise RuntimeError(
            "Configura GOOGLE_SERVICE_ACCOUNT_JSON con el JSON de tu cuenta de servicio."
        )

    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _list_children(drive, parent_id: str) -> list[dict[str, Any]]:
    """Lista todos los archivos/carpetas que están directamente dentro de parent_id."""
    results: list[dict[str, Any]] = []
    page_token = None

    while True:
        response = (
            drive.files()
            .list(
                q=f"'{parent_id}' in parents and trashed = false",
                pageSize=1000,
                pageToken=page_token,
                fields="nextPageToken, files(id,name,mimeType,size)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        results.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return results


def _download_drive_file(drive, file_id: str) -> bytes:
    """Descarga un archivo pequeño, como un GIF o metadata.json, como bytes."""
    content = drive.files().get_media(fileId=file_id, supportsAllDrives=True).execute()
    if not isinstance(content, bytes):
        content = bytes(content)
    return content


def _safe_attachment_name(action: str, original_name: str) -> str:
    # Evita espacios y caracteres que pueden complicar attachment:// en el embed.
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", original_name).strip("._") or "anime.gif"
    if not base.lower().endswith(".gif"):
        base += ".gif"
    return f"{action}_{base}"


def load_gif_library() -> dict[str, list[dict[str, Any]]]:
    """Carga la estructura Gifs/{hi,hug,pat}/ desde Google Drive."""
    root_id = _env_required("GDRIVE_ROOT_FOLDER_ID")
    drive = _make_drive_service()
    root_items = _list_children(drive, root_id)
    by_name: dict[str, dict[str, Any]] = {
        item.get("name", "").casefold(): item
        for item in root_items
        if item.get("mimeType") == "application/vnd.google-apps.folder"
    }

    library: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []

    for action in INTERACCIONES:
        action_folder = by_name.get(action.casefold())
        if not action_folder:
            errors.append(f"No encontré la subcarpeta '{action}' dentro de Gifs.")
            continue

        children = _list_children(drive, action_folder["id"])
        metadata_file = next(
            (item for item in children if item.get("name", "").casefold() == "metadata.json"),
            None,
        )

        anime_by_filename: dict[str, str] = {}
        if metadata_file:
            try:
                raw_metadata = _download_drive_file(drive, metadata_file["id"])
                parsed = json.loads(raw_metadata.decode("utf-8-sig"))
                if isinstance(parsed, dict):
                    for filename, value in parsed.items():
                        if isinstance(value, str):
                            anime_by_filename[str(filename)] = value.strip()
                        elif isinstance(value, dict):
                            anime_by_filename[str(filename)] = str(value.get("anime", "")).strip()
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                LOGGER.warning("metadata.json inválido en '%s': %s", action, exc)

        gif_files = [
            item for item in children
            if item.get("name", "").lower().endswith(".gif")
            and item.get("mimeType") != "application/vnd.google-apps.folder"
        ]
        loaded_gifs: list[dict[str, Any]] = []
        for item in gif_files:
            try:
                content = _download_drive_file(drive, item["id"])
                if not content:
                    LOGGER.warning("El GIF '%s' de '%s' está vacío.", item["name"], action)
                    continue
                anime_name = anime_by_filename.get(item["name"], "").strip()
                if not anime_name:
                    anime_name = "Anime no especificado"
                    LOGGER.warning(
                        "No hay nombre de anime para '%s' en %s/metadata.json.",
                        item["name"], action,
                    )
                loaded_gifs.append(
                    {
                        "original_filename": item["name"],
                        "filename": _safe_attachment_name(action, item["name"]),
                        "content": content,
                        "anime": anime_name,
                    }
                )
            except Exception as exc:  # Mantener cargando los demás GIF si uno falla.
                LOGGER.exception("No pude descargar '%s': %s", item.get("name", "GIF"), exc)

        if loaded_gifs:
            library[action] = loaded_gifs
            LOGGER.info("Cargué %d GIF(s) para /%s.", len(loaded_gifs), action)
        else:
            errors.append(f"La carpeta '{action}' no contiene ningún archivo .gif válido.")

    if errors:
        raise RuntimeError("Problemas al cargar la biblioteca de GIFs: " + " ".join(errors))

    return library


def choose_gif(action: str) -> dict[str, Any]:
    choices = GIF_LIBRARY.get(action, [])
    if not choices:
        raise RuntimeError(f"No hay GIFs cargados para la interacción '{action}'.")
    return random.choice(choices)


def make_embed(action: str, title_text: str, gif_data: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(description=f"### {title_text}", color=0x2B2D31)
    embed.set_image(url=f"attachment://{gif_data['filename']}")
    embed.set_footer(text=f"Anime: {gif_data['anime']}")
    return embed


def make_discord_file(gif_data: dict[str, Any]) -> discord.File:
    return discord.File(
        fp=io.BytesIO(gif_data["content"]),
        filename=gif_data["filename"],
    )


class InteractionBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        global GIF_LIBRARY
        # Las llamadas del cliente de Google son síncronas; ejecutarlas fuera del loop de Discord.
        LOGGER.info("Cargando GIFs y metadata desde Google Drive...")
        GIF_LIBRARY = await asyncio.to_thread(load_gif_library)
        synced = await self.tree.sync()
        LOGGER.info("Sincronicé %d comando(s) slash.", len(synced))

    async def on_ready(self) -> None:
        LOGGER.info("Bot conectado como %s (ID: %s).", self.user, self.user.id if self.user else "?")


bot = InteractionBot()


class DevolverInteractionView(discord.ui.View):
    """Botón que permite que la persona objetivo devuelva la interacción."""

    def __init__(self, accion: str, autor: discord.abc.User, objetivo: discord.abc.User) -> None:
        super().__init__(timeout=180)
        self.accion = accion
        self.autor = autor
        self.objetivo = objetivo

        datos = INTERACCIONES[accion]
        button = discord.ui.Button(
            label=datos["boton_texto"],
            emoji=datos["boton_emoji"],
            style=discord.ButtonStyle.secondary,
        )
        button.callback = self.button_callback
        self.add_item(button)

    async def button_callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.objetivo.id:
            await interaction.response.send_message(
                f"❌ Solo **{self.objetivo.display_name}** puede responder a esta interacción.",
                ephemeral=True,
            )
            return

        nuevo_autor = interaction.user
        nuevo_objetivo = self.autor
        datos = INTERACCIONES[self.accion]
        gif_data = choose_gif(self.accion)
        texto = (
            f"**{nuevo_autor.display_name}** {datos['verbo_vuelta']} "
            f"**{nuevo_objetivo.display_name}**."
        )
        embed = make_embed(self.accion, texto, gif_data)
        view = DevolverInteractionView(
            self.accion,
            autor=nuevo_autor,
            objetivo=nuevo_objetivo,
        )
        await interaction.response.send_message(
            embed=embed,
            file=make_discord_file(gif_data),
            view=view,
        )


def register_commands() -> None:
    for accion, datos in INTERACCIONES.items():
        # Una función por comando: no se usan parámetros dict/str extra que Discord rechazaría.
        def build_callback(action: str):
            async def callback(
                interaction: discord.Interaction,
                usuario: discord.User | None = None,
            ) -> None:
                selected = INTERACCIONES[action]
                gif_data = choose_gif(action)
                author_name = interaction.user.display_name

                if usuario is not None:
                    title_text = f"**{author_name}** {selected['verbo']} **{usuario.display_name}**."
                    view: discord.ui.View | None = DevolverInteractionView(
                        accion=action,
                        autor=interaction.user,
                        objetivo=usuario,
                    )
                else:
                    title_text = f"**{author_name}** {selected['verbo_solo']}."
                    view = None

                embed = make_embed(action, title_text, gif_data)
                await interaction.response.send_message(
                    embed=embed,
                    file=make_discord_file(gif_data),
                    view=view,
                )

            callback.__name__ = f"command_{action}"
            return callback

        command_callback = build_callback(accion)
        command_callback = app_commands.describe(
            usuario="La persona con quien quieres interactuar (opcional)."
        )(command_callback)
        command_callback = app_commands.allowed_contexts(
            guilds=True, dms=True, private_channels=True
        )(command_callback)
        command_callback = app_commands.allowed_installs(guilds=True, users=True)(command_callback)
        bot.tree.command(name=accion, description=datos["descripcion"])(command_callback)


register_commands()


if __name__ == "__main__":
    token = _env_required("DISCORD_BOT_TOKEN")
    bot.run(token, log_handler=None)
