from PyQt6.QtCore import QThread, pyqtSignal

from . import database as db
from .blossom_error import BlossomError, Stage, fail
from .drive import BlossomDriveManager
from .text_style import strip_decor
from .youtube_downloader import search_youtube_top_result
from .youtube_import_pipeline import import_youtube_track_safe


class InstrumentalWorker(QThread):
    """Ищет готовую инструментальную версию песни на YouTube и скачивает её как новый трек."""

    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(dict)
    progress = pyqtSignal(str)

    def __init__(self, song_id: int, drive: BlossomDriveManager, upload_to_drive: bool = False):
        super().__init__()
        self.song_id = song_id
        self.drive = drive
        self.upload_to_drive = upload_to_drive

    def run(self):
        try:
            result = self._find_and_import()
            if result.get("ok"):
                self.finished_ok.emit(result)
            else:
                self.finished_err.emit(result.get("error") or {})
        except BlossomError as exc:
            self.finished_err.emit(exc.to_dict())
        except Exception as exc:
            self.finished_err.emit({
                "stage": "pipeline",
                "code": "INSTRUMENTAL_CRASH",
                "message": "Ошибка поиска инструментала",
                "detail": str(exc),
            })

    def _find_and_import(self) -> dict:
        song = db.get_song(self.song_id)
        if not song:
            fail(Stage.PIPELINE, "SONG_NOT_FOUND", "Трек не найден")

        title = strip_decor(song.title)
        artist = strip_decor(song.artist)

        self.progress.emit(f"Ищу инструментал: {artist} — {title}…")
        hit = search_youtube_top_result(f"{artist} {title} instrumental")
        self.progress.emit(f"Нашёл: {hit['title']}")

        return import_youtube_track_safe(
            hit["url"],
            self.drive,
            title_override=f"{title} (Instrumental)",
            artist_override=artist,
            upload_to_drive=self.upload_to_drive,
            progress_callback=lambda msg: self.progress.emit(msg),
        )
