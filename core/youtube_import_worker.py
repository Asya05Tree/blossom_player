import os
import glob

from PyQt6.QtCore import QThread, pyqtSignal

from .drive import BlossomDriveManager
from .youtube_import_pipeline import import_youtube_track_safe
from .paths import DOWNLOADS_DIR


class YoutubeImportWorker(QThread):
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(dict)
    progress = pyqtSignal(str)

    def __init__(
        self,
        url: str,
        drive: BlossomDriveManager,
        lyrics: str = "",
        cover_source: str = "",
        upload_to_drive: bool = True,
    ):
        super().__init__()
        self.url = url
        self.drive = drive
        self.lyrics = lyrics
        self.cover_source = cover_source
        self.upload_to_drive = upload_to_drive

    def run(self):
        try:
            self._clear_stale_downloads()
            self.progress.emit("Получение данных видео...")
            result = import_youtube_track_safe(
                self.url,
                self.drive,
                lyrics=self.lyrics,
                cover_source=self.cover_source,
                upload_to_drive=self.upload_to_drive,
                progress_callback=lambda msg: self.progress.emit(msg),
            )
            if result.get("ok"):
                self.finished_ok.emit(result)
            else:
                self.finished_err.emit(result.get("error") or {})
        except Exception as exc:
            self.finished_err.emit({
                "stage": "pipeline",
                "code": "WORKER_CRASH",
                "message": f"Ошибка в потоке импорта с YouTube: {exc}",
            })

    def _clear_stale_downloads(self):
        """Удаляет файлы в downloads/, не привязанные ни к одной песне в библиотеке."""
        try:
            from . import database as db
            keep = set()
            try:
                for song in db.get_all_songs():
                    if song.filepath:
                        keep.add(os.path.normcase(os.path.abspath(song.filepath)))
            except Exception:
                pass
            if os.path.isdir(DOWNLOADS_DIR):
                for f in glob.glob(os.path.join(DOWNLOADS_DIR, "yt_*")):
                    if os.path.isfile(f) and os.path.normcase(os.path.abspath(f)) not in keep:
                        os.remove(f)
        except Exception:
            pass
