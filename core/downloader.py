import os
import time
from typing import Any

from mutagen.easyid3 import EasyID3

from .blossom_error import Stage, fail
from .paths import DOWNLOADS_DIR, TEMP_DIR
from .spotify_service import normalize_track_url
from .spotdl_client import download_track
from .log_util import log

SUPPORTED_AUDIO_EXT = {".mp3", ".m4a", ".opus", ".ogg"}


def _ensure_dir(path: str, code: str, label: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        fail(Stage.FILE_IO, code, label, str(exc))


def _validate_local_audio(path: str) -> str:
    if not path or not os.path.isfile(path):
        fail(Stage.SPOTIFY_DOWNLOAD, "AUDIO_FILE_MISSING", "Скачанный аудиофайл не найден", path or "")
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_AUDIO_EXT:
        fail(Stage.SPOTIFY_DOWNLOAD, "AUDIO_EXT_INVALID", "Неподдерживаемое расширение аудио", ext)
    size = os.path.getsize(path)
    if size <= 0:
        fail(Stage.SPOTIFY_DOWNLOAD, "AUDIO_FILE_EMPTY", "Скачанный файл пустой", path)
    return path


def _read_tags(path: str, fallback_title: str, fallback_artist: str) -> dict[str, str]:
    title = fallback_title
    artist = fallback_artist
    try:
        tags = EasyID3(path)
        title = (tags.get("title") or [fallback_title])[0].strip() or fallback_title
        artist = (tags.get("artist") or [fallback_artist])[0].strip() or fallback_artist
    except Exception:
        pass
    if not title.strip():
        fail(Stage.SPOTIFY_DOWNLOAD, "TAG_TITLE_EMPTY", "В файле нет title", path)
    if not artist.strip():
        fail(Stage.SPOTIFY_DOWNLOAD, "TAG_ARTIST_EMPTY", "В файле нет artist", path)
    return {"title": title, "artist": artist}


def _pick_downloaded_file(expected_stem: str) -> str:
    if not os.path.isdir(DOWNLOADS_DIR):
        fail(Stage.SPOTIFY_DOWNLOAD, "DOWNLOAD_DIR_MISSING", "Папка загрузок не создана", DOWNLOADS_DIR)
    candidates = []
    for name in os.listdir(DOWNLOADS_DIR):
        full = os.path.join(DOWNLOADS_DIR, name)
        if not os.path.isfile(full):
            continue
        if os.path.splitext(name)[1].lower() not in SUPPORTED_AUDIO_EXT:
            continue
        candidates.append(full)
    if not candidates:
        fail(Stage.SPOTIFY_DOWNLOAD, "AUDIO_NOT_FOUND", "После spotdl не найден аудиофайл", DOWNLOADS_DIR)
    expected_lower = expected_stem.lower()
    for path in candidates:
        if os.path.splitext(os.path.basename(path))[0].lower() == expected_lower:
            return _validate_local_audio(path)
    newest = max(candidates, key=os.path.getmtime)
    return _validate_local_audio(newest)


def _download_with_spotdl_api(track_url: str, meta: dict[str, Any]) -> dict[str, Any]:
    _ensure_dir(DOWNLOADS_DIR, "DOWNLOAD_DIR_CREATE_FAIL", "Не удалось создать папку загрузок")
    _ensure_dir(TEMP_DIR, "TEMP_DIR_CREATE_FAIL", "Не удалось создать temp-папку")
    normalized = normalize_track_url(track_url)
    started = time.time()
    log("download", "spotdl: старт (обычно 1–5 минут, не закрывай окно)")
    try:
        log("download", f"spotdl: скачивание «{meta.get('title', '')}»…")
        song_obj, downloaded = download_track(normalized)
        log("download", "spotdl: скачивание завершено")
    except Exception as exc:
        fail(Stage.SPOTIFY_DOWNLOAD, "SPOTDL_DOWNLOAD_FAIL", "spotdl не смог скачать трек", str(exc))

    if downloaded is None:
        stem = f"{meta['artist']} - {meta['title']}"
        path = _pick_downloaded_file(stem)
    else:
        path = _validate_local_audio(str(downloaded))

    auto_lyrics = ""
    if song_obj and getattr(song_obj, "lyrics", None):
        auto_lyrics = str(song_obj.lyrics).strip()

    if time.time() - started > 600:
        fail(Stage.SPOTIFY_DOWNLOAD, "DOWNLOAD_TIMEOUT", "Скачивание заняло слишком много времени")

    tags = _read_tags(path, meta["title"], meta["artist"])
    return {
        "title": tags["title"],
        "artist": tags["artist"],
        "filepath": path,
        "track_id": meta["track_id"],
        "album": meta.get("album", ""),
        "cover_url": meta.get("cover_url", ""),
        "duration_ms": meta.get("duration_ms", 0),
        "lyrics": auto_lyrics,
    }


def download_from_spotify(track_url: str, meta: dict[str, Any]) -> dict[str, Any]:
    if not meta:
        fail(Stage.SPOTIFY_DOWNLOAD, "META_EMPTY", "Нет метаданных трека перед скачиванием")
    return _download_with_spotdl_api(track_url, meta)
