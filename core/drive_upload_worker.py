import json
import os
import re

from PyQt6.QtCore import QThread, pyqtSignal

from .drive import BlossomDriveManager


def _safe_filename(*parts: str) -> str:
    raw = "_".join(p.strip() for p in parts if p and p.strip())
    cleaned = re.sub(r'[<>:"/\\|?*]+', "", raw)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._")
    return cleaned[:120] or "track"


class DriveUploadWorker(QThread):
    finished_ok = pyqtSignal(str)
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        drive: BlossomDriveManager,
        filepath: str,
        title: str = "",
        artist: str = "",
        cover_path: str = "",
        lyrics: str = "",
        song_id: int = 0,
    ):
        super().__init__()
        self.drive = drive
        self.filepath = filepath
        self.title = title
        self.artist = artist
        self.cover_path = cover_path
        self.lyrics = lyrics
        self.song_id = song_id
        self.drive_audio_id = ""
        self.drive_meta_id = ""

    def run(self):
        try:
            if not self.drive.service:
                self.drive.login()
            stem = _safe_filename(self.artist, self.title)
            ext = os.path.splitext(self.filepath)[1]

            # Upload audio
            self.drive_audio_id = self.drive.upload_file(
                self.filepath, drive_filename=f"{stem}{ext}", folder_key="Music"
            )

            # Upload cover
            drive_cover_id = ""
            if self.cover_path and os.path.isfile(self.cover_path):
                drive_cover_id = self.drive.upload_file(
                    self.cover_path, drive_filename=f"{stem}_cover.jpg", folder_key="Covers"
                )

            # Upload lyrics
            drive_lyrics_id = ""
            if self.lyrics and self.lyrics.strip():
                drive_lyrics_id = self.drive.upload_text(
                    self.lyrics, drive_filename=f"{stem}.txt", folder_key="Lyrics"
                )

            # Upload metadata JSON
            meta = {
                "title": self.title,
                "artist": self.artist,
                "lyrics": self.lyrics or "",
                "audio_file_id": self.drive_audio_id,
                "cover_file_id": drive_cover_id,
                "lyrics_file_id": drive_lyrics_id,
                "audio_filename": f"{stem}{ext}",
                "cover_filename": f"{stem}_cover.jpg" if drive_cover_id else "",
                "local_song_id": self.song_id,
            }
            self.drive_meta_id = self.drive.upload_json(
                meta, drive_filename=f"{stem}.json", folder_key="Meta"
            )

            # Update local DB with all drive IDs
            if self.song_id:
                from . import database as db
                conn = db.get_connection()
                conn.cursor().execute(
                    "UPDATE songs SET drive_file_id=?, drive_cover_id=?, drive_lyrics_id=?, drive_meta_id=? WHERE id=?",
                    (self.drive_audio_id, drive_cover_id, drive_lyrics_id, self.drive_meta_id, self.song_id),
                )
                conn.commit()
                conn.close()

            self.finished_ok.emit(self.title)
        except Exception as exc:
            self.finished_err.emit(str(exc))
