from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from . import database as db
from .blossom_error import BlossomError
from .drive import BlossomDriveManager
from .import_pipeline import import_spotify_track_safe
from .mic_record_util import record_clip, record_loopback_clip
from .shazam_util import identify_from_file
from .spotify_web_service import search_track_web
from .youtube_downloader import search_youtube_top_result
from .youtube_import_pipeline import import_youtube_track_safe


def _normalize(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


class ShazamWorker(QThread):
    """Слушает микрофон (или берёт готовый аудиофайл), узнаёт трек через Shazam
    и, если его ещё нет в библиотеке, скачивает через существующий downloader.
    """

    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(dict)
    progress = pyqtSignal(str)

    def __init__(
        self,
        drive: BlossomDriveManager,
        audio_path: str = "",
        listen_seconds: float = 8.0,
        source: str = "mic",
    ):
        super().__init__()
        self.drive = drive
        self.audio_path = (audio_path or "").strip()
        self.listen_seconds = listen_seconds
        self.source = source or "mic"

    def run(self):
        try:
            result = self._identify_and_import()
            if result.get("ok"):
                self.finished_ok.emit(result)
            else:
                self.finished_err.emit(result.get("error") or {})
        except BlossomError as exc:
            self.finished_err.emit(exc.to_dict())
        except Exception as exc:
            self.finished_err.emit({
                "stage": "pipeline",
                "code": "SHAZAM_CRASH",
                "message": "Ошибка распознавания",
                "detail": str(exc),
            })

    def _identify_and_import(self) -> dict:
        clip_path = self.audio_path
        if not clip_path:
            if self.source == "loopback":
                self.progress.emit(f"Слушаю звук компьютера {int(self.listen_seconds)} сек…")
                clip_path = record_loopback_clip(self.listen_seconds)
            else:
                self.progress.emit(f"Слушаю микрофон {int(self.listen_seconds)} сек…")
                clip_path = record_clip(self.listen_seconds)

        self.progress.emit("Узнаю трек через Shazam…")
        match = identify_from_file(clip_path)
        if not match or not match.get("title"):
            return {
                "ok": False,
                "error": {
                    "stage": "pipeline",
                    "code": "SHAZAM_NO_MATCH",
                    "message": "Не удалось узнать трек — попробуй поднести ближе к источнику звука",
                },
            }

        title, artist = match["title"], match["artist"] or "Unknown Artist"
        self.progress.emit(f"Узнал: {artist} — {title}")

        existing_id = db.find_song_id_by_title_artist(title, artist)
        if existing_id:
            existing = db.get_song(existing_id)
            return {
                "ok": True,
                "duplicate": True,
                "song_id": existing_id,
                "title_display": existing.title if existing else title,
                "artist_display": existing.artist if existing else artist,
            }

        self.progress.emit("Ищу на Spotify…")
        spotify_result = self._try_spotify_import(title, artist)
        if spotify_result is not None:
            return spotify_result

        self.progress.emit("Ищу и скачиваю с YouTube…")
        hit = search_youtube_top_result(f"{artist} {title}")
        return import_youtube_track_safe(
            hit["url"],
            self.drive,
            title_override=title,
            artist_override=artist,
            upload_to_drive=bool(self.drive.service),
            auto_artist_playlist=True,
            progress_callback=lambda msg: self.progress.emit(msg),
        )

    def _try_spotify_import(self, title: str, artist: str) -> Optional[dict]:
        """Пробует найти и скачать трек на Spotify (лучшие метаданные/обложка,
        тот же spotdl-пайплайн). Возвращает None при любой неудаче, чтобы
        вызывающий код тихо упал обратно на YouTube — это дополнительный
        источник, а не замена гарантированного YouTube-фоллбэка.
        """
        try:
            hits = search_track_web(f"{artist} {title}")
        except Exception:
            return None
        match = self._pick_spotify_match(hits, title, artist)
        if not match:
            return None
        self.progress.emit(f"Нашёл на Spotify: {match['artist']} — {match['title']}")
        result = import_spotify_track_safe(
            match["url"],
            self.drive,
            upload_to_drive=bool(self.drive.service),
            auto_artist_playlist=True,
            progress_callback=lambda msg: self.progress.emit(msg),
        )
        return result if result.get("ok") else None

    @staticmethod
    def _pick_spotify_match(hits: list, title: str, artist: str) -> Optional[dict]:
        want_title = _normalize(title)
        want_artist = _normalize(artist)
        for hit in hits:
            got_title = _normalize(hit.get("title"))
            got_artist = _normalize(hit.get("artist"))
            title_ok = want_title and (want_title in got_title or got_title in want_title)
            artist_ok = not want_artist or want_artist in got_artist or got_artist in want_artist
            if title_ok and artist_ok:
                return hit
        return None
