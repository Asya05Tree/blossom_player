from PyQt6.QtCore import QThread, pyqtSignal

from . import database as db
from .lyrics_service import INSTRUMENTAL_MARK, resolve_lyrics_for_song
from .text_style import strip_decor


class LyricsPreviewWorker(QThread):
    """Разовый поиск текста для одной песни (превью перед сохранением трека)."""

    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(dict)

    def __init__(self, title: str, artist: str, filepath: str = ""):
        super().__init__()
        self.title = title
        self.artist = artist
        self.filepath = filepath

    def run(self):
        try:
            result = resolve_lyrics_for_song(self.title, self.artist, self.filepath)
            self.finished_ok.emit(result)
        except Exception as exc:
            self.finished_err.emit({
                "stage": "pipeline",
                "code": "LYRICS_PREVIEW_CRASH",
                "message": "Не удалось найти текст",
                "detail": str(exc),
            })


class LyricsBulkWorker(QThread):
    """Проходит по всем песням без текста и пытается найти его (или помечает
    как инструментал)."""

    progress = pyqtSignal(str)
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def run(self):
        try:
            stats = self._process_all()
            self.finished_ok.emit(stats)
        except Exception as exc:
            self.finished_err.emit({
                "stage": "pipeline",
                "code": "LYRICS_BULK_CRASH",
                "message": "Ошибка массового поиска текстов",
                "detail": str(exc),
            })

    def _process_all(self) -> dict:
        songs = db.get_songs_without_lyrics()
        total = len(songs)
        found = instrumental = failed = 0
        for idx, song in enumerate(songs, start=1):
            if self._stop_requested:
                break
            title = strip_decor(song.title)
            artist = strip_decor(song.artist)
            self.progress.emit(f"({idx}/{total}) {artist} — {title}…")
            try:
                result = resolve_lyrics_for_song(song.title, song.artist, song.filepath or "")
            except Exception:
                failed += 1
                continue
            lyrics = result.get("lyrics") or INSTRUMENTAL_MARK
            db.update_song_lyrics(song.id, lyrics)
            if result.get("status") == "instrumental":
                instrumental += 1
            else:
                found += 1
        return {
            "total": total,
            "found": found,
            "instrumental": instrumental,
            "failed": failed,
            "stopped": self._stop_requested,
        }
