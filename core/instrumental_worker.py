from PyQt6.QtCore import QThread, pyqtSignal

from . import database as db
from .blossom_error import BlossomError, Stage, fail
from .drive import BlossomDriveManager
from .models import Playlist
from .text_style import strip_decor, wrap_title
from .youtube_downloader import search_youtube_top_result
from .youtube_import_pipeline import import_youtube_track_safe

INSTRUMENTAL_PLAYLIST_NAME = "Инструменталы"


class InstrumentalSearchWorker(QThread):
    """Ищет инструментал на YouTube и возвращает найденное БЕЗ скачивания —
    пользователь сам решает (и может сперва прослушать на YouTube), качать или нет.
    """

    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(dict)
    progress = pyqtSignal(str)

    def __init__(self, song_id: int):
        super().__init__()
        self.song_id = song_id

    def run(self):
        try:
            result = self._find()
            self.finished_ok.emit(result)
        except BlossomError as exc:
            self.finished_err.emit(exc.to_dict())
        except Exception as exc:
            self.finished_err.emit({
                "stage": "pipeline",
                "code": "INSTRUMENTAL_SEARCH_CRASH",
                "message": "Ошибка поиска инструментала",
                "detail": str(exc),
            })

    def _find(self) -> dict:
        song = db.get_song(self.song_id)
        if not song:
            fail(Stage.PIPELINE, "SONG_NOT_FOUND", "Трек не найден")

        title = strip_decor(song.title)
        artist = strip_decor(song.artist)

        self.progress.emit(f"Ищу инструментал: {artist} — {title}…")
        hit = search_youtube_top_result(f"{artist} {title} instrumental")

        return {
            "song_id": self.song_id,
            "title": title,
            "artist": artist,
            "video_id": hit["id"],
            "video_title": hit["title"],
            "video_url": hit["url"],
            "video_channel": hit.get("channel") or "",
            "video_duration": hit.get("duration") or 0,
        }


class InstrumentalDownloadWorker(QThread):
    """Скачивает уже найденный (и подтверждённый пользователем) инструментал."""

    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(dict)
    progress = pyqtSignal(str)

    def __init__(
        self,
        song_id: int,
        video_url: str,
        drive: BlossomDriveManager,
        upload_to_drive: bool = False,
    ):
        super().__init__()
        self.song_id = song_id
        self.video_url = video_url
        self.drive = drive
        self.upload_to_drive = upload_to_drive

    def run(self):
        try:
            result = self._download()
            if result.get("ok"):
                self.finished_ok.emit(result)
            else:
                self.finished_err.emit(result.get("error") or {})
        except BlossomError as exc:
            self.finished_err.emit(exc.to_dict())
        except Exception as exc:
            self.finished_err.emit({
                "stage": "pipeline",
                "code": "INSTRUMENTAL_DOWNLOAD_CRASH",
                "message": "Ошибка скачивания инструментала",
                "detail": str(exc),
            })

    def _download(self) -> dict:
        song = db.get_song(self.song_id)
        if not song:
            fail(Stage.PIPELINE, "SONG_NOT_FOUND", "Трек не найден")

        title = strip_decor(song.title)
        artist = strip_decor(song.artist)

        result = import_youtube_track_safe(
            self.video_url,
            self.drive,
            title_override=f"{title} (Instrumental)",
            artist_override=artist,
            upload_to_drive=self.upload_to_drive,
            auto_artist_playlist=True,
            progress_callback=lambda msg: self.progress.emit(msg),
        )
        if result.get("ok") and result.get("song_id"):
            playlist_id = self._ensure_instrumental_playlist()
            if playlist_id:
                db.add_song_to_playlist(playlist_id, result["song_id"])
        return result

    def _ensure_instrumental_playlist(self) -> int:
        existing = db.get_playlist_by_name(INSTRUMENTAL_PLAYLIST_NAME)
        if existing:
            return existing.id
        try:
            display = wrap_title(INSTRUMENTAL_PLAYLIST_NAME)
        except Exception:
            display = INSTRUMENTAL_PLAYLIST_NAME
        return db.add_playlist(Playlist(name=display))
