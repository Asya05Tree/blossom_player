import json
import os

from PyQt6.QtCore import QThread, pyqtSignal

from . import database as db
from .blossom_error import BlossomError
from .drive import BlossomDriveManager
from .import_pipeline import import_spotify_track_safe
from .models import Playlist
from .paths import TEMP_DIR
from .spotify_web_service import create_web_login, fetch_user_library_web, get_saved_sp_dc
from .text_style import wrap_title

PLAYLISTS_META_FILENAME = "playlists.json"


def upload_playlists_snapshot(drive: BlossomDriveManager) -> bool:
    """Загружает снимок всех локальных плейлистов в Drive/Meta/playlists.json."""
    if not drive.service:
        return False
    payload = {"playlists": []}
    for playlist in db.get_all_playlists():
        songs = db.get_playlist_songs(playlist.id)
        payload["playlists"].append({
            "name": playlist.name,
            "spotify_ids": [s.spotify_track_id for s in songs if s.spotify_track_id],
            "drive_file_ids": [s.drive_file_id for s in songs if s.drive_file_id],
        })
    os.makedirs(TEMP_DIR, exist_ok=True)
    local_path = os.path.join(TEMP_DIR, PLAYLISTS_META_FILENAME)
    with open(local_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    existing_id = drive.find_file_in_folder("Meta", PLAYLISTS_META_FILENAME)
    if existing_id:
        drive.update_file(existing_id, local_path)
    else:
        drive.upload_file(local_path, drive_filename=PLAYLISTS_META_FILENAME, folder_key="Meta")
    return True


class SpotifyLibraryWorker(QThread):
    """Вход в Spotify, скачивание всех плейлистов и треков на устройство и в Drive."""

    progress = pyqtSignal(str)
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(dict)

    def __init__(self, drive: BlossomDriveManager):
        super().__init__()
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
                "code": "SPOTIFY_LIBRARY_CRASH",
                "message": "Ошибка импорта библиотеки Spotify",
                "detail": str(exc),
            })

    def _run_import(self) -> dict:
        from .blossom_error import Stage, fail

        sp_dc = get_saved_sp_dc()
        if not sp_dc:
            fail(Stage.SPOTIFY_AUTH, "SPOTIFY_WEB_LOGIN_REQUIRED", "Нужен вход в Spotify")

        self.progress.emit("Подключаюсь к Spotify…")
        login = create_web_login(sp_dc)

        playlists = fetch_user_library_web(login, progress=lambda msg: self.progress.emit(msg))
        total = sum(len(p["tracks"]) for p in playlists)
        if not total:
            return {"imported": 0, "skipped": 0, "failed": 0, "playlists": 0}

        upload_to_drive = bool(self.drive.service)
        self.progress.emit(
            f"Найдено плейлистов: {len(playlists)}, треков: {total}. "
            + ("Загрузка на устройство и Google Drive." if upload_to_drive else "Drive не подключён — только на устройство.")
        )

        imported = skipped = failed = 0
        done = 0
        # Один и тот же трек в нескольких плейлистах скачиваем только один раз
        song_id_by_track: dict[str, int] = {}

        for pl in playlists:
            if self._stop_requested:
                break
            playlist_id = self._ensure_playlist(pl["name"])
            for track in pl["tracks"]:
                if self._stop_requested:
                    break
                done += 1
                song_id = song_id_by_track.get(track["id"])
                if song_id is None:
                    song_id, status = self._import_track(track, done, total, upload_to_drive)
                    if status == "imported":
                        imported += 1
                    elif status == "skipped":
                        skipped += 1
                    else:
                        failed += 1
                    if song_id:
                        song_id_by_track[track["id"]] = song_id
                if song_id and playlist_id:
                    db.add_song_to_playlist(playlist_id, song_id)

        if upload_to_drive:
            try:
                self.progress.emit("Сохраняю плейлисты на Google Drive…")
                upload_playlists_snapshot(self.drive)
            except Exception:
                self.progress.emit("Не удалось сохранить плейлисты на Drive (треки уже загружены)")

        return {
            "imported": imported,
            "skipped": skipped,
            "failed": failed,
            "playlists": len(playlists),
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
        """Возвращает (song_id | None, 'imported' | 'skipped' | 'failed')."""
        label = f"{track['artist']} — {track['title']}"

        # Дубликат уже в библиотеке?
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
