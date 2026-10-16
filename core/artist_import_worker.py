from PyQt6.QtCore import QThread, pyqtSignal

from . import database as db
from .blossom_error import BlossomError, Stage, fail
from .drive import BlossomDriveManager
from .import_pipeline import import_spotify_track_safe
from .models import Playlist
from .spotify_web_service import (
    create_web_login,
    extract_artist_id_from_url,
    fetch_artist_discography_web,
    get_saved_sp_dc,
    search_artist_web,
)
from .text_style import wrap_title


class ArtistImportWorker(QThread):
    """Скачивает всю дискографию артиста Spotify (по ссылке или имени) на устройство/Drive."""

    progress = pyqtSignal(str)
    track_imported = pyqtSignal()
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(dict)

    def __init__(self, query: str, drive: BlossomDriveManager):
        super().__init__()
        self.query = (query or "").strip()
        self.drive = drive
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
                "code": "ARTIST_IMPORT_CRASH",
                "message": "Ошибка импорта дискографии артиста",
                "detail": str(exc),
            })

    def _run_import(self) -> dict:
        sp_dc = get_saved_sp_dc()
        if not sp_dc:
            fail(Stage.SPOTIFY_AUTH, "SPOTIFY_WEB_LOGIN_REQUIRED", "Нужен вход в Spotify")

        self.progress.emit("Подключаюсь к Spotify…")
        login = create_web_login(sp_dc)

        artist_id = extract_artist_id_from_url(self.query)
        if not artist_id:
            self.progress.emit(f"Ищу артиста «{self.query}»…")
            found = search_artist_web(login, self.query, limit=5)
            if not found:
                fail(Stage.SPOTIFY_RESOLVE, "SPOTIFY_ARTIST_NOT_FOUND", "Артист не найден", self.query)
            artist_id = found[0]["id"]
            self.progress.emit(f"Нашёл: {found[0]['name']}")

        result = fetch_artist_discography_web(login, artist_id, progress=lambda msg: self.progress.emit(msg))
        artist_name = result["artist_name"]
        tracks = result["tracks"]
        if not tracks:
            return {"artist_name": artist_name, "imported": 0, "skipped": 0, "failed": 0, "total": 0}

        upload_to_drive = bool(self.drive.service)
        playlist_id = self._ensure_playlist(f"Дискография: {artist_name}")

        imported = skipped = failed = 0
        total = len(tracks)
        for done, track in enumerate(tracks, start=1):
            if self._stop_requested:
                break
            song_id, status = self._import_track(track, done, total, upload_to_drive)
            if status == "imported":
                imported += 1
            elif status == "skipped":
                skipped += 1
            else:
                failed += 1
            if song_id and playlist_id:
                db.add_song_to_playlist(playlist_id, song_id)
            if song_id:
                self.track_imported.emit()

        return {
            "artist_name": artist_name,
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

    def _import_track(self, track: dict, done: int, total: int, upload_to_drive: bool):
        label = f"{track['artist']} — {track['title']}"

        existing_id = db.find_song_id_by_spotify_id(track["id"])
        if not existing_id:
            existing_id = db.find_song_id_by_title_artist(track["title"], track["artist"])
            if existing_id:
                db.set_song_spotify_id(existing_id, track["id"])
        if existing_id:
            self.progress.emit(f"[{done}/{total}] Уже есть: {label}")
            return existing_id, "skipped"

        self.progress.emit(f"[{done}/{total}] Скачиваю: {label}")
        result = import_spotify_track_safe(
            track["url"],
            self.drive,
            upload_to_drive=upload_to_drive,
            save_to_db=True,
        )
        if result.get("ok") and result.get("song_id"):
            song_id = result["song_id"]
            if not result.get("duplicate"):
                db.set_song_spotify_id(song_id, track["id"])
            return song_id, ("skipped" if result.get("duplicate") else "imported")

        error = result.get("error") or {}
        self.progress.emit(f"[{done}/{total}] Не получилось: {label} ({error.get('code', 'ERR')})")
        return None, "failed"
