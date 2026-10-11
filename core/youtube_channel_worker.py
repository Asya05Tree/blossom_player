from PyQt6.QtCore import QThread, pyqtSignal

from . import database as db
from .blossom_error import BlossomError
from .drive import BlossomDriveManager
from .models import Playlist
from .text_style import wrap_title
from .youtube_downloader import list_channel_or_playlist_videos
from .youtube_import_pipeline import import_youtube_track_safe

CHANNEL_VIDEO_LIMIT = 50


class YoutubeChannelWorker(QThread):
    """Скачивает аудио из всех видео канала/плейлиста YouTube (до CHANNEL_VIDEO_LIMIT штук)."""

    progress = pyqtSignal(str)
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(dict)

    def __init__(self, url: str, drive: BlossomDriveManager, upload_to_drive: bool = False):
        super().__init__()
        self.url = (url or "").strip()
        self.drive = drive
        self.upload_to_drive = upload_to_drive
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def run(self):
        try:
            stats = self._run_import()
            self.finished_ok.emit(stats)
        except BlossomError as exc:
            self.finished_err.emit(exc.to_dict())
        except Exception as exc:
            self.finished_err.emit({
                "stage": "pipeline",
                "code": "YOUTUBE_CHANNEL_CRASH",
                "message": "Ошибка массовой загрузки с YouTube",
                "detail": str(exc),
            })

    def _run_import(self) -> dict:
        self.progress.emit("Читаю список видео…")
        listing = list_channel_or_playlist_videos(self.url, limit=CHANNEL_VIDEO_LIMIT)
        videos = listing["videos"]
        if not videos:
            return {"imported": 0, "skipped": 0, "failed": 0, "total": 0}

        playlist_id = self._ensure_playlist(f"YouTube: {listing['source_title']}")

        imported = skipped = failed = 0
        total = len(videos)
        self.progress.emit(f"Найдено видео: {total} (за раз скачивается максимум {CHANNEL_VIDEO_LIMIT})")
        for done, video in enumerate(videos, start=1):
            if self._stop_requested:
                break
            label = video["title"] or video["id"]
            self.progress.emit(f"[{done}/{total}] {label}")
            result = import_youtube_track_safe(
                video["url"],
                self.drive,
                upload_to_drive=self.upload_to_drive,
            )
            if result.get("ok") and result.get("song_id"):
                song_id = result["song_id"]
                if playlist_id:
                    db.add_song_to_playlist(playlist_id, song_id)
                if result.get("duplicate"):
                    skipped += 1
                else:
                    imported += 1
            else:
                error = result.get("error") or {}
                self.progress.emit(f"[{done}/{total}] Не получилось: {label} ({error.get('code', 'ERR')})")
                failed += 1

        return {
            "imported": imported,
            "skipped": skipped,
            "failed": failed,
            "total": total,
            "stopped": self._stop_requested,
        }

    def _ensure_playlist(self, name: str) -> int:
        existing = db.get_playlist_by_name(name)
        if existing:
            return existing.id
        try:
            display = wrap_title(name)
        except Exception:
            display = name
        return db.add_playlist(Playlist(name=display))
