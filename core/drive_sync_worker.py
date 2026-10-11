import json
import os

from PyQt6.QtCore import QThread, pyqtSignal

from . import database as db
from .drive import BlossomDriveManager
from .models import Song
from .paths import DOWNLOADS_DIR, COVERS_DIR
from .text_style import wrap_title, wrap_artist


class DriveSyncWorker(QThread):
    """Syncs library from Google Drive Meta/ folder to local DB."""
    finished_ok = pyqtSignal(int)  # number of synced songs
    finished_err = pyqtSignal(str)

    def __init__(self, drive: BlossomDriveManager):
        super().__init__()
        self.drive = drive

    def run(self):
        try:
            if not self.drive.service:
                self.drive.login()

            meta_files = self.drive.list_files_in_folder("Meta")
            synced = 0

            for mf in meta_files:
                if not mf["name"].endswith(".json"):
                    continue
                try:
                    raw = self.drive.download_text(mf["id"])
                    meta = json.loads(raw)
                except Exception:
                    continue

                audio_file_id = meta.get("audio_file_id", "")
                if not audio_file_id:
                    continue

                # Check if already in local DB by drive_file_id
                existing = self._find_by_drive_id(audio_file_id)
                if existing:
                    continue

                title = meta.get("title", "Unknown")
                artist = meta.get("artist", "Unknown")

                # Download audio to local cache
                audio_filename = meta.get("audio_filename", f"{title}.mp3")
                os.makedirs(DOWNLOADS_DIR, exist_ok=True)
                local_audio = os.path.join(DOWNLOADS_DIR, audio_filename)
                if not os.path.isfile(local_audio):
                    self.drive.download_file(audio_file_id, local_audio)

                # Download cover
                cover_path = ""
                cover_file_id = meta.get("cover_file_id", "")
                if cover_file_id:
                    cover_filename = meta.get("cover_filename", f"{title}_cover.jpg")
                    os.makedirs(COVERS_DIR, exist_ok=True)
                    local_cover = os.path.join(COVERS_DIR, cover_filename)
                    if not os.path.isfile(local_cover):
                        try:
                            self.drive.download_file(cover_file_id, local_cover)
                        except Exception:
                            pass
                    if os.path.isfile(local_cover):
                        cover_path = local_cover

                lyrics = meta.get("lyrics", "")

                song = Song(
                    title=wrap_title(title),
                    artist=wrap_artist(artist),
                    filepath=local_audio,
                    cover_path=cover_path,
                    lyrics=lyrics,
                    video_link="",
                    drive_file_id=audio_file_id,
                    spotify_track_id=(meta.get("spotify_track_id") or "").strip() or None,
                )
                db.add_song(song)
                synced += 1

            # Восстановление плейлистов из Meta/playlists.json
            try:
                self._sync_playlists(meta_files)
            except Exception:
                pass

            self.finished_ok.emit(synced)
        except Exception as exc:
            self.finished_err.emit(str(exc))

    def _sync_playlists(self, meta_files: list) -> None:
        from .models import Playlist

        playlists_file = next(
            (mf for mf in meta_files if mf.get("name") == "playlists.json"), None
        )
        if not playlists_file:
            return
        try:
            payload = json.loads(self.drive.download_text(playlists_file["id"]))
        except Exception:
            return
        for entry in payload.get("playlists") or []:
            name = (entry.get("name") or "").strip()
            if not name:
                continue
            playlist = db.get_playlist_by_name(name)
            playlist_id = playlist.id if playlist else db.add_playlist(Playlist(name=name))
            song_ids = set()
            for spotify_id in entry.get("spotify_ids") or []:
                sid = db.find_song_id_by_spotify_id(spotify_id)
                if sid:
                    song_ids.add(sid)
            for drive_id in entry.get("drive_file_ids") or []:
                sid = db.find_song_id_by_drive_file_id(drive_id)
                if sid:
                    song_ids.add(sid)
            for sid in song_ids:
                db.add_song_to_playlist(playlist_id, sid)

    def _find_by_drive_id(self, drive_file_id: str) -> bool:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM songs WHERE drive_file_id = ?", (drive_file_id,))
        row = cursor.fetchone()
        conn.close()
        return row is not None


class DriveDownloadWorker(QThread):
    """Downloads a single audio file from Drive for playback."""
    finished_ok = pyqtSignal(int, str)  # song_id, local_path
    finished_err = pyqtSignal(int, str)  # song_id, error

    def __init__(self, drive: BlossomDriveManager, song_id: int, drive_file_id: str, local_path: str):
        super().__init__()
        self.drive = drive
        self.song_id = song_id
        self.drive_file_id = drive_file_id
        self.local_path = local_path

    def run(self):
        try:
            if not self.drive.service:
                self.drive.login()
            os.makedirs(os.path.dirname(self.local_path), exist_ok=True)
            self.drive.download_file(self.drive_file_id, self.local_path)
            self.finished_ok.emit(self.song_id, self.local_path)
        except Exception as exc:
            self.finished_err.emit(self.song_id, str(exc))
