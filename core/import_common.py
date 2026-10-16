import os
import re
from urllib.request import urlopen

from .blossom_error import Stage, fail
from .paths import COVERS_DIR, LYRICS_DIR


def ensure_asset_dirs() -> None:
    for folder in (COVERS_DIR, LYRICS_DIR):
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            fail(Stage.FILE_IO, "ASSET_DIR_CREATE_FAIL", f"Не удалось создать {folder}", str(exc))


def safe_filename(*parts: str) -> str:
    raw = "_".join(p.strip() for p in parts if p and p.strip())
    cleaned = re.sub(r'[<>:"/\\|?*]+', "", raw)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._")
    if not cleaned:
        fail(Stage.PIPELINE, "SAFE_FILENAME_EMPTY", "Не удалось собрать безопасное имя файла")
    return cleaned[:120]


def download_cover_from_url(url: str, target_path: str) -> str:
    if not url or not url.strip():
        fail(Stage.PIPELINE, "COVER_URL_EMPTY", "Нет URL обложки")
    try:
        with urlopen(url, timeout=20) as response:
            data = response.read()
    except Exception as exc:
        fail(Stage.PIPELINE, "COVER_DOWNLOAD_FAIL", "Не удалось скачать обложку", str(exc))
    if not data:
        fail(Stage.PIPELINE, "COVER_BYTES_EMPTY", "Обложка скачалась пустой")
    try:
        with open(target_path, "wb") as handle:
            handle.write(data)
    except OSError as exc:
        fail(Stage.FILE_IO, "COVER_WRITE_FAIL", "Не удалось сохранить обложку", str(exc))
    if not os.path.isfile(target_path) or os.path.getsize(target_path) <= 0:
        fail(Stage.PIPELINE, "COVER_FILE_INVALID", "Файл обложки после записи невалиден", target_path)
    return target_path


def ensure_artist_playlist(artist_name: str) -> "int | None":
    """Плейлист с именем артиста — создаёт при первом треке этого артиста,
    дальше переиспользует. Используется только при добавлении ОДНОГО трека
    (ссылка, Shazam, OCR, инструментал) — массовые импортёры (вся дискография,
    весь канал) делают себе отдельный плейлист-партию сами и сюда не заходят,
    иначе получилось бы два почти одинаковых плейлиста на один прогон.
    """
    from . import database as db
    from .models import Playlist
    from .text_style import wrap_title

    clean = (artist_name or "").strip()
    if not clean:
        return None
    existing = db.get_playlist_by_name(clean)
    if existing:
        return existing.id
    try:
        display = wrap_title(clean)
    except Exception:
        display = clean
    return db.add_playlist(Playlist(name=display))


def save_lyrics_local(song_id: int, lyrics: str) -> str:
    ensure_asset_dirs()
    path = os.path.join(LYRICS_DIR, f"lyrics_{song_id}.txt")
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write((lyrics or "").strip() + "\n")
    except OSError as exc:
        fail(Stage.FILE_IO, "LYRICS_LOCAL_WRITE_FAIL", "Не удалось сохранить текст локально", str(exc))
    return path
