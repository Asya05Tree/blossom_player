"""Поиск трека по тексту сразу на YouTube и Spotify — пользователь видит оба
списка результатов и сам выбирает, что скачать (в отличие от Shazam,
который тихо берёт "лучший" результат без выбора)."""
from PyQt6.QtCore import QThread, pyqtSignal

from .spotify_web_service import search_track_web
from .youtube_downloader import search_youtube_results


class OnlineSearchWorker(QThread):
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(dict)

    def __init__(self, query: str):
        super().__init__()
        self.query = (query or "").strip()

    def run(self):
        if not self.query:
            self.finished_err.emit({
                "stage": "pipeline",
                "code": "ONLINE_SEARCH_EMPTY",
                "message": "Пустой поисковый запрос",
            })
            return
        try:
            youtube = search_youtube_results(self.query, limit=8)
        except Exception:
            youtube = []
        try:
            spotify = search_track_web(self.query, limit=8)
        except Exception:
            spotify = []
        self.finished_ok.emit({"youtube": youtube, "spotify": spotify})
