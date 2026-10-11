from PyQt6.QtCore import QThread, pyqtSignal

from .blossom_error import BlossomError
from .drive import BlossomDriveManager
from .youtube_downloader import search_youtube_top_result
from .youtube_import_pipeline import import_youtube_track_safe


class TextSearchDownloadWorker(QThread):
    """Ищет текстовый запрос на YouTube и скачивает лучший результат как трек.

    Общий шаг для OCR-с-картинки и Shazam-распознавания: обоим нужно превратить
    текст (название + автор) в реальный скачанный трек через тот же downloader.
    """

    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(dict)
    progress = pyqtSignal(str)

    def __init__(self, query: str, drive: BlossomDriveManager, upload_to_drive: bool = False):
        super().__init__()
        self.query = (query or "").strip()
        self.drive = drive
        self.upload_to_drive = upload_to_drive

    def run(self):
        try:
            result = self._search_and_import()
            if result.get("ok"):
                self.finished_ok.emit(result)
            else:
                self.finished_err.emit(result.get("error") or {})
        except BlossomError as exc:
            self.finished_err.emit(exc.to_dict())
        except Exception as exc:
            self.finished_err.emit({
                "stage": "pipeline",
                "code": "TEXT_SEARCH_CRASH",
                "message": "Ошибка поиска и скачивания",
                "detail": str(exc),
            })

    def _search_and_import(self) -> dict:
        self.progress.emit(f"Ищу на YouTube: {self.query}…")
        hit = search_youtube_top_result(self.query)
        self.progress.emit(f"Нашёл: {hit['title']}")
        return import_youtube_track_safe(
            hit["url"],
            self.drive,
            upload_to_drive=self.upload_to_drive,
            progress_callback=lambda msg: self.progress.emit(msg),
        )
