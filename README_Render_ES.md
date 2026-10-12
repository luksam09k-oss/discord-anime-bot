# Bot de interacciones de Discord + Google Drive + Render

## Archivos del proyecto

- `bot.py`: comandos `/hi`, `/hug` y `/pat` con GIFs adjuntos, pie con el nombre del anime y botón para devolver la interacción.
- `requirements.txt`: dependencias Python.
- `.python-version`: versión de Python para Render.

## Estructura en Google Drive

La carpeta raíz que vas a compartir debe tener esta estructura:

```text
Gifs/
  hi/
    anime-hi.gif
    metadata.json
  hug/
    anime-hug.gif
    metadata.json
  pat/
    anime-pat.gif
    metadata.json
```

Cada `metadata.json` es un objeto JSON que relaciona el nombre exacto del archivo GIF con el nombre de su anime. Ejemplo dentro de `hi/metadata.json`:

```json
{
  "anime-hi.gif": "Nombre real del anime"
}
```

El nombre del archivo debe coincidir exactamente con el nombre del GIF en Drive. Si falta la entrada, el bot mostrará `Anime no especificado`.

## Variables de entorno necesarias

- `DISCORD_BOT_TOKEN`: token nuevo del bot de Discord.
- `GDRIVE_ROOT_FOLDER_ID`: ID de la carpeta principal `Gifs` (no el ID de `hi`, `hug` o `pat`).
- `GOOGLE_SERVICE_ACCOUNT_JSON`: contenido completo del JSON de la cuenta de servicio de Google Cloud.

Opcionalmente se puede usar `GOOGLE_SERVICE_ACCOUNT_FILE` si la plataforma permite proporcionar un archivo secreto y se indica la ruta a él; no hace falta configurar ambas opciones.

## Render

- Runtime: Python 3.
- Build Command: `pip install -r requirements.txt`
- Start Command: `python bot.py`
- Tipo de servicio recomendado para un bot Discord 24/7: Background Worker (requiere un plan compatible/pago en Render).

No subas el token de Discord ni la clave JSON de Google a GitHub.
