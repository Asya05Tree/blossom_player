import os
import re
from typing import Any, Optional
from urllib.request import urlopen

from . import database as db
from .blossom_error import BlossomError, Stage, fail
from .covers import save_and_resize_cover
from .downloader import download_from_spotify
from .drive import BlossomDriveManager
from .models import Song
from .paths import COVERS_DIR, LYRICS_DIR
from .log_util import log
from .spotify_service import resolve_track_metadata
from .text_style import wrap_artist, wrap_title


def _ensure_asset_dirs() -> None:
    for folder in (COVERS_DIR, LYRICS_DIR):
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            fail(Stage.FILE_IO, "ASSET_DIR_CREATE_FAIL", f"Не удалось создать {folder}", str(exc))


def _safe_filename(*parts: str) -> str:
    raw = "_".join(p.strip() for p in parts if p and p.strip())
    cleaned = re.sub(r'[<>:"/\\|?*]+', "", raw)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._")
    if not cleaned:
        fail(Stage.PIPELINE, "SAFE_FILENAME_EMPTY", "Не удалось собрать безопасное имя файла")
    return cleaned[:120]


def _download_cover_from_url(url: str, target_path: str) -> str:
    if not url or not url.strip():
        fail(Stage.PIPELINE, "COVER_URL_EMPTY", "Нет URL обложки Spotify")
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


def _save_lyrics_local(song_id: int, lyrics: str) -> str:
    _ensure_asset_dirs()
    path = os.path.join(LYRICS_DIR, f"lyrics_{song_id}.txt")
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write((lyrics or "").strip() + "\n")
    except OSError as exc:
        fail(Stage.FILE_IO, "LYRICS_LOCAL_WRITE_FAIL", "Не удалось сохранить текст локально", str(exc))
    return path


def import_spotify_track(
    track_url: str,
    drive: BlossomDriveManager,
    *,
    lyrics: str = "",
    cover_source: str = "",
    video_link: str = "",
    upload_to_drive: bool = True,
    save_to_db: bool = True,
    progress_callback=None,
) -> dict[str, Any]:
    def _progress(msg):
        if progress_callback:
            try:
                progress_callback(msg)
            except Exception:
                pass
        log("pipeline", msg)

    if not track_url or not track_url.strip():
        fail(Stage.PIPELINE, "TRACK_URL_EMPTY", "Не передана ссылка на трек")

    _progress("1/4: Получение метаданных...")
    meta = resolve_track_metadata(track_url)

    # Дедупликация: не добавлять трек, который уже есть в библиотеке
    if save_to_db:
        existing_id = db.find_song_id_by_spotify_id(meta.get("track_id") or "")
        if not existing_id:
            existing_id = db.find_song_id_by_title_artist(meta.get("title") or "", meta.get("artist") or "")
            if existing_id and meta.get("track_id"):
                db.set_song_spotify_id(existing_id, meta["track_id"])
        if existing_id:
            existing = db.get_song(existing_id)
            _progress("Трек уже есть в библиотеке — дубликат не добавлен")
            return {
                "ok": True,
                "duplicate": True,
                "song_id": existing_id,
                "track_id": meta.get("track_id") or "",
                "title": meta.get("title") or "",
                "artist": meta.get("artist") or "",
                "title_display": existing.title if existing else meta.get("title") or "",
                "artist_display": existing.artist if existing else meta.get("artist") or "",
                "filepath": existing.filepath if existing else "",
                "cover_path": existing.cover_path if existing else "",
                "lyrics": existing.lyrics if existing else "",
                "drive_audio_id": existing.drive_file_id if existing else "",
                "drive_cover_id": existing.drive_cover_id if existing else "",
                "drive_lyrics_id": existing.drive_lyrics_id if existing else "",
            }

    _progress(f"2/4: Скачивание — {meta.get('title')} / {meta.get('artist')}...")
    downloaded = download_from_spotify(meta["url"], meta)
    final_lyrics = lyrics.strip() or (downloaded.get("lyrics") or "").strip()

    title_display = wrap_title(downloaded["title"])
    artist_display = wrap_artist(downloaded["artist"])
    stem = _safe_filename(downloaded["artist"], downloaded["title"])

    drive_audio_id = ""
    drive_cover_id = ""
    drive_lyrics_id = ""

    if upload_to_drive:
        _progress("3/4: Загрузка на Google Drive...")
        drive.login()
        ext = os.path.splitext(downloaded["filepath"])[1]
        drive_audio_id = drive.upload_file(
            downloaded["filepath"],
            drive_filename=f"{stem}{ext}",
            folder_key="Music",
        )
        if final_lyrics:
            drive_lyrics_id = drive.upload_text(
                final_lyrics,
                drive_filename=f"{stem}.txt",
                folder_key="Lyrics",
            )

    drive_meta_id = ""
    song_id = None
    cover_path = ""
    if save_to_db:
        _progress("4/4: Сохранение в библиотеку...")
        song = Song(
            title=title_display,
            artist=artist_display,
            filepath=downloaded["filepath"],
            lyrics=final_lyrics,
            video_link=video_link.strip(),
            drive_file_id=drive_audio_id or None,
            spotify_track_id=(downloaded.get("track_id") or meta.get("track_id") or None),
        )
        song_id = db.add_song(song)

        cover_seed = (cover_source or "").strip()
        if not cover_seed and meta.get("cover_url"):
            temp_cover = os.path.join(COVERS_DIR, f"spotify_{song_id}.jpg")
            _download_cover_from_url(meta["cover_url"], temp_cover)
            cover_seed = temp_cover
        cover_path = save_and_resize_cover(cover_seed, song_id)

        conn = db.get_connection()
        try:
            conn.cursor().execute(
                "UPDATE songs SET cover_path = ? WHERE id = ?",
                (cover_path, song_id),
            )
            conn.commit()
        finally:
            conn.close()

        if final_lyrics:
            _save_lyrics_local(song_id, final_lyrics)

        if upload_to_drive and cover_path and os.path.isfile(cover_path):
            drive_cover_id = drive.upload_file(
                cover_path,
                drive_filename=f"{stem}_cover.jpg",
                folder_key="Covers",
            )

        # Upload meta JSON to Drive
        if upload_to_drive and song_id:
            try:
                meta_data = {
                    "title": downloaded["title"],
                    "artist": downloaded["artist"],
                    "lyrics": final_lyrics,
                    "audio_file_id": drive_audio_id,
                    "cover_file_id": drive_cover_id,
                    "lyrics_file_id": drive_lyrics_id,
                    "audio_filename": f"{stem}{os.path.splitext(downloaded['filepath'])[1]}",
                    "cover_filename": f"{stem}_cover.jpg" if drive_cover_id else "",
                    "spotify_track_id": downloaded.get("track_id") or meta.get("track_id") or "",
                }
                drive_meta_id = drive.upload_json(meta_data, drive_filename=f"{stem}.json", folder_key="Meta")
            except Exception:
                pass

        # Update DB with all drive IDs
        if song_id:
            conn2 = db.get_connection()
            try:
                conn2.cursor().execute(
                    "UPDATE songs SET drive_file_id=?, drive_cover_id=?, drive_lyrics_id=?, drive_meta_id=? WHERE id=?",
                    (drive_audio_id or None, drive_cover_id or None, drive_lyrics_id or None, drive_meta_id or None, song_id),
                )
                conn2.commit()
            finally:
                conn2.close()

    return {
        "ok": True,
        "song_id": song_id,
        "track_id": downloaded["track_id"],
        "title": downloaded["title"],
        "artist": downloaded["artist"],
        "title_display": title_display,
        "artist_display": artist_display,
        "filepath": downloaded["filepath"],
        "cover_path": cover_path,
        "lyrics": final_lyrics,
        "drive_audio_id": drive_audio_id,
        "drive_cover_id": drive_cover_id,
        "drive_lyrics_id": drive_lyrics_id,
    }


def import_spotify_track_safe(
    track_url: str,
    drive: BlossomDriveManager,
    progress_callback=None,
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        return import_spotify_track(track_url, drive, progress_callback=progress_callback, **kwargs)
    except BlossomError as exc:
        return {"ok": False, "error": exc.to_dict()}
    except Exception as exc:
        return {
            "ok": False,
            "error": {
                "stage": Stage.PIPELINE.value,
                "code": "UNEXPECTED",
                "message": "Непредвиденная ошибка импорта",
                "detail": str(exc),
            },
        }
