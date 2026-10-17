import os
from typing import Any, Optional

from . import database as db
from .blossom_error import BlossomError, Stage, fail
from .covers import save_and_resize_cover
from .downloader import download_from_spotify
from .drive import BlossomDriveManager
from .models import Song
from .paths import COVERS_DIR
from .log_util import log
from .spotify_service import resolve_track_metadata
from .text_style import wrap_artist, wrap_title
from .import_common import (
    download_cover_from_url as _download_cover_from_url,
    ensure_artist_playlist as _ensure_artist_playlist,
    safe_filename as _safe_filename,
    save_lyrics_local as _save_lyrics_local,
)
from .log_util import log_to_file


def _add_to_artist_playlist(song_id: Optional[int], artist_name: str) -> None:
    if not song_id:
        return
    playlist_id = _ensure_artist_playlist(artist_name)
    if playlist_id:
        db.add_song_to_playlist(playlist_id, song_id)


def import_spotify_track(
    track_url: str,
    drive: BlossomDriveManager,
    *,
    lyrics: str = "",
    cover_source: str = "",
    video_link: str = "",
    upload_to_drive: bool = True,
    save_to_db: bool = True,
    auto_artist_playlist: bool = False,
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
            if auto_artist_playlist:
                _add_to_artist_playlist(existing_id, meta.get("artist") or (existing.artist if existing else ""))
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
        if auto_artist_playlist:
            _add_to_artist_playlist(song_id, downloaded["artist"])

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
        err = exc.to_dict()
        log_to_file("spotify_import", f"{track_url} -> {err}", filename="download_errors.log")
        return {"ok": False, "error": err}
    except Exception as exc:
        err = {
            "stage": Stage.PIPELINE.value,
            "code": "UNEXPECTED",
            "message": "Непредвиденная ошибка импорта",
            "detail": str(exc),
        }
        log_to_file("spotify_import", f"{track_url} -> {err}", filename="download_errors.log")
        return {"ok": False, "error": err}
