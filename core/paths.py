import os
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
DOWNLOADS_DIR = os.path.join(ASSETS_DIR, "downloads")
COVERS_DIR = os.path.join(ASSETS_DIR, "covers")
LYRICS_DIR = os.path.join(ASSETS_DIR, "lyrics")
TEMP_DIR = os.path.join(ASSETS_DIR, "temp")

SPOTIFY_CLIENT_FILE = os.path.join(CONFIG_DIR, "spotify_client.json")
GENIUS_CLIENT_FILE = os.path.join(CONFIG_DIR, "genius_client.json")
SPOTIFY_CACHE_FILE = os.path.join(CONFIG_DIR, ".spotify_cache")
GOOGLE_CREDENTIALS_FILE = os.path.join(CONFIG_DIR, "credentials.json")
GOOGLE_TOKEN_FILE = os.path.join(CONFIG_DIR, "token.json")
APP_SETTINGS_FILE = os.path.join(CONFIG_DIR, "app_settings.json")

MIN_FREE_DISK_MB = 200


def ensure_disk_space(min_free_mb: int = MIN_FREE_DISK_MB) -> None:
    """Прерывает скачивание ДО сетевого запроса, если на диске почти нет места —
    иначе пользователь тратит время/трафик на закачку, которая потом не сохранится.
    """
    from .blossom_error import Stage, fail

    try:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        free_bytes = shutil.disk_usage(DOWNLOADS_DIR).free
    except OSError:
        return
    free_mb = free_bytes / (1024 * 1024)
    if free_mb < min_free_mb:
        fail(
            Stage.FILE_IO,
            "DISK_SPACE_LOW",
            f"Мало места на диске (осталось {free_mb:.0f} МБ) — скачивание не начато",
            DOWNLOADS_DIR,
        )
