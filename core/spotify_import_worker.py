import os
import glob

from PyQt6.QtCore import QThread, pyqtSignal

from .drive import BlossomDriveManager
from .import_pipeline import import_spotify_track_safe
from .paths import DOWNLOADS_DIR


class SpotifyImportWorker(QThread):
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(dict)
    progress = pyqtSignal(str)  # step description

    def __init__(
        self,
        track_url: str,
        drive: BlossomDriveManager,
        lyrics: str = "",
        cover_source: str = "",
        video_link: str = "",
        upload_to_drive: bool = True,
        save_to_db: bool = True,
    ):
        super().__init__()
        self.track_url = track_url
        self.drive = drive
        self.lyrics = lyrics
        self.cover_source = cover_source
        self.video_link = video_link
        self.upload_to_drive = upload_to_drive
        self.save_to_db = save_to_db

    def run(self):
        try:
            # Clear spotdl cache and old downloads to prevent stale data
            self._clear_spotdl_cache()
            self._clear_downloads()

            self.progress.emit("Получение метаданных...")
            result = import_spotify_track_safe(
                self.track_url,
                self.drive,
                lyrics=self.lyrics,
                cover_source=self.cover_source,
                video_link=self.video_link,
                upload_to_drive=self.upload_to_drive,
                save_to_db=self.save_to_db,
                auto_artist_playlist=True,
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
                "message": f"Ошибка в потоке импорта: {exc}",
            })

    def _clear_spotdl_cache(self):
        """Reset the global spotdl instance and cache so each import is fresh."""
        try:
            from . import spotdl_client
            spotdl_client._spotdl_instance = None
            spotdl_client._song_cache.clear()
        except Exception:
            pass

    def _clear_downloads(self):
        """Remove stale downloaded files, keeping files referenced by library songs."""
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
                for f in glob.glob(os.path.join(DOWNLOADS_DIR, "*")):
                    if os.path.isfile(f) and os.path.normcase(os.path.abspath(f)) not in keep:
                        os.remove(f)
        except Exception:
            pass
