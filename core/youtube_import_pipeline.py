import os
from typing import Any

from . import database as db
from .blossom_error import BlossomError, Stage, fail
from .covers import save_and_resize_cover
from .drive import BlossomDriveManager
from .import_common import download_cover_from_url, safe_filename, save_lyrics_local
from .log_util import log
from .models import Song
from .paths import COVERS_DIR
from .text_style import wrap_artist, wrap_title
from .youtube_downloader import download_youtube_audio


def import_youtube_track(
    url: str,
    drive: BlossomDriveManager,
    *,
    lyrics: str = "",
    cover_source: str = "",
    title_override: str = "",
    artist_override: str = "",
    upload_to_drive: bool = True,
    progress_callback=None,
) -> dict[str, Any]:
    def _progress(msg):
        if progress_callback:
            try:
                progress_callback(msg)
            except Exception:
                pass
        log("youtube_pipeline", msg)

    if not url or not url.strip():
        fail(Stage.PIPELINE, "YOUTUBE_URL_EMPTY", "Не передана ссылка на видео")

    from .youtube_downloader import extract_video_id
    video_id = extract_video_id(url)

    # Дедупликация по video_id — если уже скачивали это видео, не качаем заново
    existing_id = db.find_song_id_by_youtube_id(video_id)
    if existing_id:
        existing = db.get_song(existing_id)
        _progress("Это видео уже есть в библиотеке — дубликат не добавлен")
        return {
            "ok": True,
            "duplicate": True,
            "song_id": existing_id,
            "title_display": existing.title if existing else "",
            "artist_display": existing.artist if existing else "",
        }

    _progress("1/3: Скачивание аудио с YouTube...")
    downloaded = download_youtube_audio(url)

    raw_title = (title_override or downloaded["title"]).strip()
    raw_artist = (artist_override or downloaded["artist"]).strip()

    # Повторная проверка дублей по названию+автору (вдруг то же видео уже было добавлено вручную)
    dup_by_name = db.find_song_id_by_title_artist(raw_title, raw_artist)
    if dup_by_name:
        db.set_song_youtube_id(dup_by_name, video_id)
        existing = db.get_song(dup_by_name)
        _progress("Такой трек уже есть в библиотеке — дубликат не добавлен")
        return {
            "ok": True,
            "duplicate": True,
            "song_id": dup_by_name,
            "title_display": existing.title if existing else raw_title,
            "artist_display": existing.artist if existing else raw_artist,
        }

    title_display = wrap_title(raw_title)
    artist_display = wrap_artist(raw_artist)
    stem = safe_filename(raw_artist, raw_title)

    drive_audio_id = ""
    drive_cover_id = ""
    drive_lyrics_id = ""

    if upload_to_drive:
        _progress("2/3: Загрузка на Google Drive...")
        drive.login()
        ext = os.path.splitext(downloaded["filepath"])[1]
        drive_audio_id = drive.upload_file(
            downloaded["filepath"],
            drive_filename=f"{stem}{ext}",
            folder_key="Music",
        )
        final_lyrics = (lyrics or "").strip()
        if final_lyrics:
            drive_lyrics_id = drive.upload_text(
                final_lyrics,
                drive_filename=f"{stem}.txt",
                folder_key="Lyrics",
            )
    final_lyrics = (lyrics or "").strip()

    _progress("3/3: Сохранение в библиотеку...")
    song = Song(
        title=title_display,
        artist=artist_display,
        filepath=downloaded["filepath"],
        lyrics=final_lyrics,
        video_link="",
        drive_file_id=drive_audio_id or None,
        youtube_video_id=video_id,
    )
    song_id = db.add_song(song)

    cover_seed = (cover_source or "").strip()
    if not cover_seed and downloaded.get("thumbnail_url"):
        temp_cover = os.path.join(COVERS_DIR, f"youtube_{song_id}.jpg")
        try:
            download_cover_from_url(downloaded["thumbnail_url"], temp_cover)
            cover_seed = temp_cover
        except BlossomError:
            cover_seed = ""
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
        save_lyrics_local(song_id, final_lyrics)

    if upload_to_drive and cover_path and os.path.isfile(cover_path):
        drive_cover_id = drive.upload_file(
            cover_path,
            drive_filename=f"{stem}_cover.jpg",
            folder_key="Covers",
        )

    drive_meta_id = ""
    if upload_to_drive:
        try:
            meta_data = {
                "title": raw_title,
                "artist": raw_artist,
                "lyrics": final_lyrics,
                "audio_file_id": drive_audio_id,
                "cover_file_id": drive_cover_id,
                "lyrics_file_id": drive_lyrics_id,
                "youtube_video_id": video_id,
            }
            drive_meta_id = drive.upload_json(meta_data, drive_filename=f"{stem}.json", folder_key="Meta")
        except Exception:
            pass

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
        "title": raw_title,
        "artist": raw_artist,
        "title_display": title_display,
        "artist_display": artist_display,
        "filepath": downloaded["filepath"],
        "cover_path": cover_path,
        "lyrics": final_lyrics,
    }


def import_youtube_track_safe(
    url: str,
    drive: BlossomDriveManager,
    progress_callback=None,
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        return import_youtube_track(url, drive, progress_callback=progress_callback, **kwargs)
    except BlossomError as exc:
        return {"ok": False, "error": exc.to_dict()}
    except Exception as exc:
        return {
            "ok": False,
            "error": {
                "stage": Stage.PIPELINE.value,
                "code": "UNEXPECTED",
                "message": "Непредвиденная ошибка импорта с YouTube",
                "detail": str(exc),
            },
        }
