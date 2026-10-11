import json
import os
import shutil

from .blossom_error import Stage, fail
from .paths import APP_SETTINGS_FILE, BASE_DIR


def resolve_ffmpeg() -> str:
    env_path = (os.environ.get("BLOSSOM_FFMPEG") or "").strip()
    if env_path and os.path.isfile(env_path):
        return env_path
    if os.path.isfile(APP_SETTINGS_FILE):
        try:
            with open(APP_SETTINGS_FILE, "r", encoding="utf-8") as handle:
                settings = json.load(handle)
            cfg_path = (settings.get("ffmpeg_path") or "").strip()
            if cfg_path and os.path.isfile(cfg_path):
                return cfg_path
        except (json.JSONDecodeError, OSError):
            pass
    from_path = shutil.which("ffmpeg")
    if from_path:
        return from_path
    for candidate in (
        os.path.join(BASE_DIR, "ffmpeg", "bin", "ffmpeg.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "spotdl", "ffmpeg.exe"),
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    ):
        if candidate and os.path.isfile(candidate):
            return candidate
    fail(
        Stage.SPOTIFY_DOWNLOAD,
        "FFMPEG_MISSING",
        "ffmpeg не найден. Добавь в PATH или укажи путь в config/app_settings.json",
    )
