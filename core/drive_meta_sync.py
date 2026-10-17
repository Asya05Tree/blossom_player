import json
import os
import re

from .paths import TEMP_DIR


def push_song_meta(drive, song, title: str, artist: str, lyrics: str) -> None:
    """Перезаписывает meta.json песни на Drive с актуальным текстом песни.

    Без этого текст, найденный один раз (вручную или массовым поиском),
    пришлось бы искать повторно после синхронизации на другом устройстве —
    DriveSyncWorker восстанавливает lyrics именно из поля meta.json, а не из
    отдельного .txt файла в папке Lyrics."""
    if not (drive.service and song.drive_meta_id):
        return
    try:
        stem = re.sub(r'[<>:"/\\|?*]+', "", f"{artist}_{title}")
        stem = re.sub(r"\s+", "_", stem).strip("._")[:120] or "track"
        meta = {
            "title": title,
            "artist": artist,
            "lyrics": lyrics,
            "audio_file_id": song.drive_file_id or "",
            "cover_file_id": song.drive_cover_id or "",
            "lyrics_file_id": song.drive_lyrics_id or "",
        }
        os.makedirs(TEMP_DIR, exist_ok=True)
        local_meta = os.path.join(TEMP_DIR, f"{stem}.json")
        with open(local_meta, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
        drive.update_file(song.drive_meta_id, local_meta)
    except Exception:
        pass
