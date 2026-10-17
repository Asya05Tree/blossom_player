import json
import os
from PyQt6.QtCore import QObject, pyqtSlot, pyqtSignal, QTimer
from PyQt6.QtWidgets import QApplication, QFileDialog
from .models import Song, Playlist
from . import database as db
from .player import BlossomPlayer
from .covers import save_and_resize_cover
from .drive import BlossomDriveManager
from .drive_login_worker import DriveLoginWorker, DriveVerifyWorker
from .drive_upload_worker import DriveUploadWorker
from .drive_sync_worker import DriveSyncWorker, DriveDownloadWorker
from .spotify_import_worker import SpotifyImportWorker
from .spotify_library_worker import SpotifyLibraryWorker
from .youtube_import_worker import YoutubeImportWorker
from .artist_import_worker import ArtistImportWorker
from .youtube_channel_worker import YoutubeChannelWorker
from .tiktok_import_worker import TikTokCollectionWorker
from .instrumental_worker import InstrumentalSearchWorker, InstrumentalDownloadWorker
from .duplicate_finder_worker import DuplicateFinderWorker
from .blossom_error import BlossomError
from .trim_util import trim_audio
from .shazam_worker import ShazamWorker
from .lyrics_worker import LyricsPreviewWorker, LyricsBulkWorker, ClearAllLyricsWorker, SyncedLyricsWorker, SingleLyricsSearchWorker
from .online_search_worker import OnlineSearchWorker
from .spectrum_worker import SpectrumAnalysisWorker
from .drive_meta_sync import push_song_meta
from .fingerprint_util import compute_fingerprint, fingerprint_duration, fingerprint_similarity, DEFAULT_DUPLICATE_THRESHOLD
from typing import Optional
from .text_style import strip_decor, wrap_artist, wrap_title

DEFAULT_LYRICS = db.DEFAULT_LYRICS_PLACEHOLDER
MAX_PLAYLISTS_PER_SONG = 5


class BlossomBridge(QObject):
    songChanged = pyqtSignal(int, str, str, str, str, str, str, bool, bool, bool, str)
    nextSongPreview = pyqtSignal(str)
    playlistListUpdated = pyqtSignal(list)
    importStarted = pyqtSignal(str)
    importFinished = pyqtSignal(str)
    importFailed = pyqtSignal(str, str, str)
    driveStatusChanged = pyqtSignal(str)
    driveLoginFailed = pyqtSignal(str, str, str)
    libraryUpdated = pyqtSignal(str)
    filePicked = pyqtSignal(str, str)
    toastMessage = pyqtSignal(str, bool)
    songForEditReady = pyqtSignal(str)
    playlistSongsReady = pyqtSignal(int, str)
    playlistsForSongReady = pyqtSignal(int, str)
    positionChanged = pyqtSignal(int, int)
    importProgress = pyqtSignal(str)
    spotifyAutoProgress = pyqtSignal(str)
    spotifyAutoFinished = pyqtSignal(str)
    spotifyAutoFailed = pyqtSignal(str)
    youtubeImportStarted = pyqtSignal(str)
    youtubeImportProgress = pyqtSignal(str)
    youtubeImportFinished = pyqtSignal(str)
    youtubeImportFailed = pyqtSignal(str, str, str)
    artistImportProgress = pyqtSignal(str)
    artistImportFinished = pyqtSignal(str)
    artistImportFailed = pyqtSignal(str)
    youtubeChannelProgress = pyqtSignal(str)
    youtubeChannelFinished = pyqtSignal(str)
    youtubeChannelFailed = pyqtSignal(str)
    tiktokCollectionProgress = pyqtSignal(str)
    tiktokCollectionFinished = pyqtSignal(str)
    tiktokCollectionFailed = pyqtSignal(str)
    instrumentalStarted = pyqtSignal(int)
    instrumentalProgress = pyqtSignal(str)
    instrumentalFound = pyqtSignal(str)
    instrumentalFinished = pyqtSignal(str)
    instrumentalFailed = pyqtSignal(str)
    duplicatesScanProgress = pyqtSignal(str)
    duplicatesScanFinished = pyqtSignal(str)
    duplicatesScanFailed = pyqtSignal(str)
    shazamStarted = pyqtSignal()
    shazamProgress = pyqtSignal(str)
    shazamFinished = pyqtSignal(str)
    shazamFailed = pyqtSignal(str)
    lyricsPreviewReady = pyqtSignal(str)
    lyricsPreviewFailed = pyqtSignal(str)
    singleLyricsSearchReady = pyqtSignal(int, str)
    singleLyricsSearchFailed = pyqtSignal(int, str)
    lyricsBulkStarted = pyqtSignal()
    lyricsBulkProgress = pyqtSignal(str)
    lyricsBulkFinished = pyqtSignal(str)
    lyricsBulkFailed = pyqtSignal(str)
    syncedLyricsReady = pyqtSignal(int, str)
    onlineSearchReady = pyqtSignal(str)
    onlineSearchFailed = pyqtSignal(str)
    heavyJobsChanged = pyqtSignal(str)
    spectrumReady = pyqtSignal(int, str)

    def __init__(self, player: BlossomPlayer, drive: BlossomDriveManager):
        super().__init__()
        self.player = player
        self.drive = drive
        self._import_worker = None
        self._drive_login_worker = None
        self._drive_upload_worker = None
        self._drive_verify_worker = None
        self._spotify_library_worker = None
        self._spotify_login_dialog = None
        self._spotify_relogin_done = False
        self._youtube_import_worker = None
        self._artist_import_worker = None
        self._youtube_channel_worker = None
        self._tiktok_collection_worker = None
        self._instrumental_search_worker = None
        self._instrumental_download_worker = None
        self._duplicate_finder_worker = None
        self._shazam_worker = None
        self._lyrics_preview_worker = None
        self._single_lyrics_worker = None
        self._lyrics_bulk_worker = None
        self._clear_all_lyrics_worker = None
        self._synced_lyrics_worker = None
        self._synced_lyrics_tried_song_id = None
        self._online_search_worker = None
        self._spectrum_worker = None
        self._spectrum_tried_song_id = None
        db.init_db()
        self.player.player.positionChanged.connect(self._on_position_changed)
        self.player.player.durationChanged.connect(self._on_duration_changed)
        self.player.player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._last_duration = 0

        # Пока идёт работа с текстами песен или скачивание — блокируем клики по
        # библиотеке/плеер на фронтенде (см. heavyJobsChanged в script.js):
        # параллельное переключение песен во время таких операций уже роняло
        # приложение. Опрос таймером, а не хук на каждый старт воркера —
        # не нужно трогать десяток разных мест, где воркеры запускаются.
        self._heavy_jobs_payload = "[]"
        self._heavy_job_detail = {}
        self._heavy_lock_timer = QTimer(self)
        self._heavy_lock_timer.setInterval(400)
        self._heavy_lock_timer.timeout.connect(self._check_heavy_jobs)
        self._heavy_lock_timer.start()

    _JOB_WORKER_ATTRS = (
        "_drive_verify_worker", "_drive_login_worker", "_sync_worker", "_drive_upload_worker",
        "_import_worker", "_youtube_import_worker", "_artist_import_worker", "_youtube_channel_worker",
        "_tiktok_collection_worker",
        "_instrumental_search_worker", "_instrumental_download_worker",
        "_shazam_worker", "_duplicate_finder_worker", "_spotify_library_worker",
        "_lyrics_preview_worker", "_single_lyrics_worker", "_lyrics_bulk_worker", "_clear_all_lyrics_worker",
        "_synced_lyrics_worker", "_online_search_worker", "_spectrum_worker",
    )

    # Подмножество _JOB_WORKER_ATTRS, которое блокирует клики по библиотеке —
    # только "работа с текстами песен или загрузка" в точном смысле просьбы
    # пользователя. Лёгкие фоновые штуки (авто-поиск караоке-текста/спектра,
    # поиск дублей — у них своя модалка со Stop) сюда не входят, иначе
    # библиотека блокировалась бы почти постоянно без всякой пользы.
    # label — что показать пользователю; stoppable=True только если у воркера
    # есть request_stop() и его правда можно прервать без риска оставить
    # недоделанную/повреждённую запись.
    _HEAVY_LOCK_JOBS = {
        "lyricsBulk": ("_lyrics_bulk_worker", "Поиск текстов песен", True),
        "clearAllLyrics": ("_clear_all_lyrics_worker", "Удаление текстов у всех песен", True),
        "spotifyImport": ("_import_worker", "Скачивание трека со Spotify", False),
        "youtubeImport": ("_youtube_import_worker", "Скачивание трека с YouTube", False),
        "artistImport": ("_artist_import_worker", "Скачивание дискографии артиста", True),
        "youtubeChannel": ("_youtube_channel_worker", "Скачивание канала YouTube", True),
        "tiktokCollection": ("_tiktok_collection_worker", "Распознавание и скачивание песен из коллекции TikTok", True),
        "spotifyLibrary": ("_spotify_library_worker", "Спотифай автоматически", True),
        "instrumentalDownload": ("_instrumental_download_worker", "Скачивание инструментала", False),
        "shazam": ("_shazam_worker", "Распознавание Shazam", False),
        "driveSync": ("_sync_worker", "Синхронизация с Google Drive", True),
        "driveUpload": ("_drive_upload_worker", "Загрузка в Google Drive", False),
    }

    def _check_heavy_jobs(self):
        active = []
        for key, (attr_name, label, stoppable) in self._HEAVY_LOCK_JOBS.items():
            worker = getattr(self, attr_name, None)
            if worker is not None and worker.isRunning():
                active.append({
                    "key": key,
                    "label": label,
                    "stoppable": stoppable,
                    "detail": self._heavy_job_detail.get(key, ""),
                })
            else:
                self._heavy_job_detail.pop(key, None)
        payload = json.dumps(active, ensure_ascii=False)
        if payload != self._heavy_jobs_payload:
            self._heavy_jobs_payload = payload
            self.heavyJobsChanged.emit(payload)

    def _set_heavy_job_detail(self, key: str, detail: str) -> None:
        self._heavy_job_detail[key] = detail

    @pyqtSlot(str)
    def stopHeavyJob(self, key):
        entry = self._HEAVY_LOCK_JOBS.get(key)
        if not entry:
            return
        attr_name, _label, stoppable = entry
        if not stoppable:
            return
        worker = getattr(self, attr_name, None)
        if worker is not None and worker.isRunning() and hasattr(worker, "request_stop"):
            worker.request_stop()

    def _active_jobs(self) -> list:
        workers = []
        for name in self._JOB_WORKER_ATTRS:
            worker = getattr(self, name, None)
            if worker is not None and worker.isRunning():
                workers.append(worker)
        return workers

    def has_active_jobs(self) -> bool:
        """Используется при закрытии окна (main.py) — нельзя закрываться, пока идёт скачивание/анализ."""
        return bool(self._active_jobs())

    def stop_all_jobs(self) -> None:
        """Просит все активные фоновые потоки остановиться (после текущего элемента —
        у кого есть такая поддержка). Не ждёт завершения — за ожиданием следит вызывающий."""
        for worker in self._active_jobs():
            stop = getattr(worker, "request_stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass

    def _on_position_changed(self, position: int):
        self.positionChanged.emit(position, self._last_duration)

    def _on_duration_changed(self, duration: int):
        self._last_duration = duration
        self.positionChanged.emit(0, duration)

    def _on_media_status_changed(self, status):
        from PyQt6.QtMultimedia import QMediaPlayer
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.player.loop_mode == "repeat_one":
                self.player.play()
                self._update_ui_state()
            elif self.player.next():
                self._update_ui_state()

    def _window(self):
        return QApplication.activeWindow()

    def _emit_drive_status(self):
        self.driveStatusChanged.emit(json.dumps(self.drive.status_snapshot(), ensure_ascii=False))

    def _strip_decor(self, text: str) -> str:
        return strip_decor(text)

    def _cover_file_url(self, cover_path: str) -> str:
        if not cover_path or not os.path.isfile(cover_path):
            return ""
        # Имя файла обложки стабильно (cover_<song_id>.jpg) и перезаписывается на месте
        # при редактировании — без ?v=mtime QWebEngine отдаёт старую картинку из кэша
        # до перезапуска приложения, хотя сам файл на диске уже новый.
        mtime = int(os.path.getmtime(cover_path))
        return "file:///" + os.path.abspath(cover_path).replace("\\", "/") + f"?v={mtime}"

    def _emit_library(self):
        playlist_names = db.get_song_playlist_names_map()
        items = []
        for song in db.get_all_songs():
            items.append({
                "id": song.id,
                "title": song.title,
                "artist": song.artist,
                "title_raw": self._strip_decor(song.title),
                "artist_raw": self._strip_decor(song.artist),
                "cover": self._cover_file_url(song.cover_path or ""),
                "filepath": song.filepath,
                "added_at": song.added_at or 0,
                "playlists": playlist_names.get(song.id, []),
                "has_lyrics": bool(song.lyrics and song.lyrics.strip() and song.lyrics.strip() != DEFAULT_LYRICS),
            })
        self.libraryUpdated.emit(json.dumps(items, ensure_ascii=False))

    def _reload_queue_keep(self, song_id: Optional[int] = None):
        all_songs = db.get_all_songs()
        if not all_songs:
            self.player.load_queue([], 0)
            return
        index = 0
        if song_id is not None:
            index = next((i for i, s in enumerate(all_songs) if s.id == song_id), 0)
        elif self.player.get_current_song():
            cur = self.player.get_current_song()
            index = next((i for i, s in enumerate(all_songs) if s.id == cur.id), 0)
        self.player.load_queue(all_songs, start_index=index)

    def _update_ui_state(self):
        song = self.player.get_current_song()
        if not song:
            self.songChanged.emit(
                0,
                "Выбери трек",
                "Включите песню",
                "",
                DEFAULT_LYRICS,
                "",
                "Моя коллекция",
                False,
                False,
                False,
                "",
            )
            return

        video_source = song.video_link.strip() if (song.video_link and song.video_link.endswith(".mp4")) else ""

        has_prev = self.player.current_index > 0
        has_next = self.player.current_index < len(self.player.queue) - 1
        if self.player.loop_mode == "repeat_all":
            has_prev = has_next = True

        cover_url = self._cover_file_url(song.cover_path or "")

        next_song = self.player.get_next_song()
        next_text = next_song.title if next_song else "Конец очереди"
        self.nextSongPreview.emit(f"Далее: {next_text}")

        has_lyrics_content = bool(song.lyrics and song.lyrics.strip() and song.lyrics.strip() != DEFAULT_LYRICS)

        self.songChanged.emit(
            song.id,
            song.title,
            song.artist,
            cover_url,
            song.lyrics or DEFAULT_LYRICS,
            video_source,
            "Моя коллекция",
            has_prev,
            has_next,
            has_lyrics_content,
            song.synced_lyrics or "",
        )

        # synced_lyrics is None -> ещё не пробовали искать караоке-текст для
        # этой песни. "" (не None) значит "искали, не нашли" — не долбим lrclib
        # заново на каждое включение трека.
        if (
            has_lyrics_content
            and song.synced_lyrics is None
            and self._synced_lyrics_tried_song_id != song.id
            and not (self._synced_lyrics_worker and self._synced_lyrics_worker.isRunning())
        ):
            self._synced_lyrics_tried_song_id = song.id
            self._synced_lyrics_worker = SyncedLyricsWorker(
                song.id, strip_decor(song.title), strip_decor(song.artist), song.filepath or "",
            )
            self._synced_lyrics_worker.finished_ok.connect(self._on_synced_lyrics_ok)
            self._synced_lyrics_worker.finished_err.connect(lambda sid, msg: None)
            self._synced_lyrics_worker.start()

        # Спектр считается через ffmpeg+FFT и кэшируется на диске по пути к
        # файлу (core/audio_spectrum.py) — гонять воркер при каждом повторном
        # включении той же песни не накладно (второй раз просто читает кэш),
        # но свой "уже пробовали" флаг всё равно нужен, чтобы не запускать
        # второй воркер на ту же песню, пока первый ещё не закончил.
        if (
            song.filepath
            and self._spectrum_tried_song_id != song.id
            and not (self._spectrum_worker and self._spectrum_worker.isRunning())
        ):
            self._spectrum_tried_song_id = song.id
            self._spectrum_worker = SpectrumAnalysisWorker(song.id, song.filepath)
            self._spectrum_worker.finished_ok.connect(self._on_spectrum_ok)
            self._spectrum_worker.finished_err.connect(lambda sid, msg: None)
            self._spectrum_worker.start()

    def _on_synced_lyrics_ok(self, song_id: int, lrc: str):
        self.syncedLyricsReady.emit(song_id, lrc)

    def _on_spectrum_ok(self, song_id: int, payload: str):
        self.spectrumReady.emit(song_id, payload)

    @pyqtSlot(result=str)
    def getDriveStatus(self) -> str:
        # Раньше тут был синхронный self.drive._fetch_user_email() (сетевой
        # вызов) прямо на GUI-потоке — на нестабильной сети UI подвисал
        # ("не отвечает") на каждое открытие настроек. login()/try_silent_login()
        # уже выставляют user_email при входе — здесь просто отдаём, что есть.
        return json.dumps(self.drive.status_snapshot(), ensure_ascii=False)

    @pyqtSlot()
    def emitDriveStatus(self):
        """Emit driveStatusChanged signal so JS can react asynchronously."""
        self._emit_drive_status()

    @pyqtSlot()
    def checkDriveAccess(self):
        """Тихая проверка реального доступа к Google Drive (без браузера).

        Наличие token.json не означает доступ — токен может быть отозван,
        поэтому проверяем настоящим вызовом Drive API в фоне.
        """
        if self.drive.service:
            self._emit_drive_status()
            return
        if self._drive_verify_worker and self._drive_verify_worker.isRunning():
            return
        self._drive_verify_worker = DriveVerifyWorker(self.drive)
        self._drive_verify_worker.finished_status.connect(self.driveStatusChanged.emit)
        self._drive_verify_worker.start()

    @pyqtSlot(bool)
    def loginGoogleDrive(self, pick_account: bool):
        if self._drive_login_worker and self._drive_login_worker.isRunning():
            self.driveLoginFailed.emit("drive_auth", "LOGIN_BUSY", "Вход уже выполняется")
            return
        self._drive_login_worker = DriveLoginWorker(self.drive, pick_account=bool(pick_account))
        self._drive_login_worker.finished_ok.connect(self._on_drive_login_ok)
        self._drive_login_worker.finished_err.connect(self._on_drive_login_err)
        self._drive_login_worker.start()

    def _on_drive_login_ok(self, status_json: str):
        self.driveStatusChanged.emit(status_json)

    def _on_drive_login_err(self, stage: str, code: str, message: str):
        self.driveLoginFailed.emit(stage, code, message)

    @pyqtSlot()
    def logoutGoogleDrive(self):
        self.drive.logout()
        self._emit_drive_status()

    @pyqtSlot(str)
    def pickFile(self, kind: str):
        parent = self._window()
        path = ""
        if kind == "audio":
            path, _ = QFileDialog.getOpenFileName(
                parent, "Выбери аудиофайл", "", "Audio (*.mp3 *.m4a *.flac *.wav *.ogg)",
            )
        elif kind in ("cover", "cover_local", "cover_edit"):
            path, _ = QFileDialog.getOpenFileName(
                parent, "Выбери обложку", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
            )
        elif kind == "video_bg":
            path, _ = QFileDialog.getOpenFileName(
                parent, "Выбери видео для фона", "", "Video (*.webm *.mp4)",
            )
        elif kind == "shazam_audio":
            path, _ = QFileDialog.getOpenFileName(
                parent, "Выбери аудио или видео с записью песни", "",
                "Audio/Video (*.mp3 *.m4a *.wav *.ogg *.flac *.mp4 *.webm *.mov)",
            )
        if path:
            self.filePicked.emit(path, kind)
            self.toastMessage.emit(f"Выбрано: {os.path.basename(path)}", False)

    @pyqtSlot(result=str)
    def getLibraryJson(self) -> str:
        self._emit_library()
        return "ok"

    @pyqtSlot(int)
    def playSongById(self, song_id: int):
        all_songs = db.get_all_songs()
        idx = next((i for i, s in enumerate(all_songs) if s.id == song_id), -1)
        if idx < 0:
            self.toastMessage.emit("Трек не найден", True)
            return
        song = all_songs[idx]
        if not self._ensure_local_file(song):
            self.toastMessage.emit("Файл не найден и нет Drive ID для скачивания", True)
            return
        self.player.load_queue(all_songs, start_index=idx)
        self.player.play()
        self._update_ui_state()

    @pyqtSlot(int)
    def deleteSongById(self, song_id: int):
        song = db.get_song(song_id)
        if not song:
            self.toastMessage.emit("Трек не найден", True)
            return
        affected_playlist_ids = db.get_song_playlist_ids(song_id)
        # Delete from Drive
        if self.drive.service:
            for fid in [song.drive_file_id, song.drive_cover_id, song.drive_lyrics_id, song.drive_meta_id]:
                if fid:
                    try:
                        self.drive.delete_file(fid)
                    except Exception:
                        pass
        if not db.delete_song(song_id):
            self.toastMessage.emit("Не удалось удалить", True)
            return
        for playlist_id in affected_playlist_ids:
            self._delete_if_empty(playlist_id)
        self._reload_queue_keep()
        self._update_ui_state()
        self._emit_library()
        self.toastMessage.emit("Трек удалён", False)

    @pyqtSlot(int, str, str, str, str)
    def updateSongById(self, song_id: int, title, artist, lyrics, cover_source):
        song = db.get_song(song_id)
        if not song:
            self.toastMessage.emit("Трек не найден", True)
            return
        raw_title = (title or self._strip_decor(song.title)).strip()
        raw_artist = (artist or self._strip_decor(song.artist)).strip()
        if not raw_title:
            self.toastMessage.emit("Название не может быть пустым", True)
            return
        cover_path = song.cover_path
        cover_seed = (cover_source or "").strip()
        if cover_seed and os.path.isfile(cover_seed):
            cover_path = save_and_resize_cover(cover_seed, song_id)
        final_lyrics = (lyrics or "").strip() or DEFAULT_LYRICS
        db.update_song_row(
            song_id,
            wrap_title(raw_title),
            wrap_artist(raw_artist),
            final_lyrics,
            cover_path,
        )
        push_song_meta(self.drive, song, raw_title, raw_artist, final_lyrics)
        self._reload_queue_keep(song_id)
        self._update_ui_state()
        self._emit_library()
        self.toastMessage.emit("Сохранено", False)

    @pyqtSlot(int, result=str)
    def getSongForEdit(self, song_id: int) -> str:
        song = db.get_song(song_id)
        if not song:
            return "{}"
        return json.dumps({
            "id": song.id,
            "title": self._strip_decor(song.title),
            "artist": self._strip_decor(song.artist),
            "lyrics": song.lyrics or "",
            "cover": self._cover_file_url(song.cover_path or ""),
        }, ensure_ascii=False)

    @pyqtSlot(int)
    def requestSongForEdit(self, song_id: int):
        song = db.get_song(song_id)
        if not song:
            self.songForEditReady.emit("{}")
            return
        self.songForEditReady.emit(json.dumps({
            "id": song.id,
            "title": self._strip_decor(song.title),
            "artist": self._strip_decor(song.artist),
            "lyrics": song.lyrics or "",
            "cover": self._cover_file_url(song.cover_path or ""),
        }, ensure_ascii=False))

    @pyqtSlot(int)
    def seekTo(self, position_ms: int):
        self.player.player.setPosition(position_ms)

    @pyqtSlot(str)
    def createPlaylist(self, name: str):
        raw = (name or "").strip()
        if not raw:
            self.toastMessage.emit("Введи название плейлиста", True)
            return
        from .text_style import wrap_title as wt
        try:
            display = wt(raw)
        except Exception:
            display = raw
        db.add_playlist(Playlist(name=display))
        self._emit_playlists()
        self.toastMessage.emit("Плейлист создан", False)

    def _emit_playlists(self):
        items = [{"id": p.id, "name": p.name, "is_default": p.is_default} for p in db.get_all_playlists()]
        self.playlistListUpdated.emit(items)

    @pyqtSlot(int, int)
    def addSongToPlaylist(self, playlist_id: int, song_id: int):
        current_ids = db.get_song_playlist_ids(song_id)
        if playlist_id not in current_ids and len(current_ids) >= MAX_PLAYLISTS_PER_SONG:
            self.toastMessage.emit(
                f"Песня уже в {MAX_PLAYLISTS_PER_SONG} плейлистах — это максимум",
                True,
            )
            return
        db.add_song_to_playlist(playlist_id, song_id)
        self._emit_library()
        self.toastMessage.emit("Добавлено в плейлист", False)

    @pyqtSlot(int)
    def deletePlaylistById(self, playlist_id: int):
        if db.delete_playlist(playlist_id):
            self._emit_playlists()
            self.toastMessage.emit("Плейлист удалён", False)
        else:
            self.toastMessage.emit("Этот плейлист нельзя удалить — можно удалять только песни в нём", True)

    @pyqtSlot(int)
    def requestPlaylistSongs(self, playlist_id: int):
        # result=str QWebChannel-слоты требуют JS-колбэка и НИКОГДА не возвращаются
        # синхронно — старый код звал их как обычную функцию (var x = pyBridge.foo())
        # и всегда получал undefined, из-за чего плейлист выглядел пустым даже
        # с песнями внутри. Сигнал + подписка в JS — единственный рабочий способ.
        songs = db.get_playlist_songs(playlist_id)
        playlist_names = db.get_song_playlist_names_map()
        current_name = next((p.name for p in db.get_all_playlists() if p.id == playlist_id), "")
        items = []
        for song in songs:
            other_playlists = [n for n in playlist_names.get(song.id, []) if n != current_name]
            items.append({
                "id": song.id,
                "title": song.title,
                "artist": song.artist,
                "title_raw": self._strip_decor(song.title),
                "artist_raw": self._strip_decor(song.artist),
                "cover": self._cover_file_url(song.cover_path or ""),
                "filepath": song.filepath,
                "added_at": song.added_at or 0,
                "other_playlists": other_playlists,
            })
        self.playlistSongsReady.emit(playlist_id, json.dumps(items, ensure_ascii=False))

    @pyqtSlot(int)
    def requestPlaylistsForSong(self, song_id: int):
        all_playlists = db.get_all_playlists()
        song_pl_ids = db.get_song_playlist_ids(song_id)
        items = []
        for p in all_playlists:
            items.append({
                "id": p.id,
                "name": p.name,
                "has_song": p.id in song_pl_ids,
            })
        self.playlistsForSongReady.emit(song_id, json.dumps(items, ensure_ascii=False))

    @pyqtSlot(int, int)
    def removeSongFromPlaylist(self, playlist_id: int, song_id: int):
        if db.remove_song_from_playlist(playlist_id, song_id):
            self.toastMessage.emit("Убрано из плейлиста", False)
            self._emit_library()
            self._delete_if_empty(playlist_id)

    def _delete_if_empty(self, playlist_id: int) -> None:
        # Пустые плейлисты не нужны — убираем их сразу, а не копим мусор, который
        # потом приходится чистить вручную.
        if db.count_playlist_songs(playlist_id) == 0:
            if db.delete_playlist(playlist_id):
                self._emit_playlists()

    @pyqtSlot(int, str)
    def renamePlaylist(self, playlist_id: int, new_name: str):
        raw = (new_name or "").strip()
        if not raw:
            self.toastMessage.emit("Введи название", True)
            return
        from .text_style import wrap_title as wt
        try:
            display = wt(raw)
        except Exception:
            display = raw
        if db.rename_playlist(playlist_id, display):
            self._emit_playlists()
            self.toastMessage.emit("Переименовано", False)

    @pyqtSlot(int)
    def playPlaylist(self, playlist_id: int):
        songs = db.get_playlist_songs(playlist_id)
        if not songs:
            self.toastMessage.emit("Плейлист пуст", True)
            return
        self.player.load_queue(songs, start_index=0)
        self.player.play()
        self._update_ui_state()

    @pyqtSlot()
    def syncFromDrive(self):
        if not self.drive.service and not os.path.exists(self.drive._token_file()):
            self.toastMessage.emit("Сначала войди в Google Drive", True)
            return
        self._sync_worker = DriveSyncWorker(self.drive)
        self._sync_worker.progress.connect(lambda msg: self._set_heavy_job_detail("driveSync", msg))
        self._sync_worker.finished_ok.connect(self._on_sync_ok)
        self._sync_worker.finished_err.connect(
            lambda e: self.toastMessage.emit(f"Ошибка синхронизации: {e}", True)
        )
        self.toastMessage.emit("Синхронизация с Drive...", False)
        self._sync_worker.start()

    def _on_sync_ok(self, count: int):
        if count > 0:
            self._reload_queue_keep()
            self._update_ui_state()
            self._emit_library()
        self._emit_playlists()
        self.toastMessage.emit(f"Синхронизировано: {count} новых треков", False)

    def _ensure_local_file(self, song):
        """If song file doesn't exist locally but has drive_file_id, download it."""
        if song.filepath and os.path.isfile(song.filepath):
            return True
        if not song.drive_file_id:
            return False
        from .paths import DOWNLOADS_DIR
        local_path = os.path.join(DOWNLOADS_DIR, os.path.basename(song.filepath or f"song_{song.id}.mp3"))
        if os.path.isfile(local_path):
            if local_path != song.filepath:
                conn = db.get_connection()
                conn.cursor().execute("UPDATE songs SET filepath = ? WHERE id = ?", (local_path, song.id))
                conn.commit()
                conn.close()
                song.filepath = local_path
            return True
        # Need to download - do it synchronously for now
        try:
            if not self.drive.service:
                self.drive.login()
            os.makedirs(DOWNLOADS_DIR, exist_ok=True)
            self.drive.download_file(song.drive_file_id, local_path)
            conn = db.get_connection()
            conn.cursor().execute("UPDATE songs SET filepath = ? WHERE id = ?", (local_path, song.id))
            conn.commit()
            conn.close()
            song.filepath = local_path
            return True
        except Exception as exc:
            self.toastMessage.emit(f"Не удалось скачать из Drive: {exc}", True)
            return False

    @pyqtSlot()
    def play(self):
        song = self.player.get_current_song()
        if not song:
            return
        if self.player.is_paused:
            self.player.resume()
        else:
            if not self._ensure_local_file(song):
                self.toastMessage.emit("Файл не найден", True)
                return
            self.player.play()
        self._update_ui_state()

    @pyqtSlot()
    def pause(self):
        self.player.pause()

    @pyqtSlot()
    def stop(self):
        self.player.stop()

    @pyqtSlot()
    def restart(self):
        self.player.restart()
        self._update_ui_state()

    @pyqtSlot()
    def next(self):
        if self.player.next():
            self._update_ui_state()

    @pyqtSlot()
    def prev(self):
        if self.player.prev():
            self._update_ui_state()

    @pyqtSlot(float)
    def setVolume(self, val):
        self.player.set_volume(val / 100.0)

    @pyqtSlot(str)
    def setLoopMode(self, mode):
        self.player.set_loop_mode(mode)
        self._update_ui_state()

    @pyqtSlot()
    def toggleShuffle(self):
        self.player.toggle_shuffle()
        self._update_ui_state()

    @pyqtSlot(str, str, str, str, str)
    def addSongFull(self, title, artist, filepath, lyrics, cover_source):
        filepath = (filepath or "").strip()
        if not filepath or not os.path.isfile(filepath):
            self.toastMessage.emit("Файл не найден — выбери снова", True)
            return

        # Дубль по ЗВУКУ, а не по названию/автору — название в файле может
        # быть любым, но если это тот же самый трек (тот же отпечаток
        # Chromaprint), добавлять его второй раз не нужно. Тот же порог и
        # способ сравнения, что в core/duplicate_finder_worker.py.
        new_fp = ""
        try:
            new_fp = compute_fingerprint(filepath)
        except Exception:
            pass
        if new_fp:
            new_duration = fingerprint_duration(new_fp)
            for existing in db.get_all_songs():
                if not existing.fingerprint:
                    continue
                if new_duration and abs(fingerprint_duration(existing.fingerprint) - new_duration) > 2.0:
                    continue
                if fingerprint_similarity(new_fp, existing.fingerprint) >= DEFAULT_DUPLICATE_THRESHOLD:
                    self.toastMessage.emit(
                        f"Эта песня уже есть в библиотеке: «{existing.title}» — не добавляю повторно", True,
                    )
                    return

        raw_title = (title or os.path.splitext(os.path.basename(filepath))[0]).strip()
        raw_artist = (artist or "Unknown Artist").strip()
        try:
            song = Song(
                title=wrap_title(raw_title),
                artist=wrap_artist(raw_artist),
                filepath=filepath,
                lyrics=(lyrics or "").strip() or DEFAULT_LYRICS,
                video_link="",
                fingerprint=new_fp or None,
            )
        except Exception as exc:
            self.toastMessage.emit(str(exc), True)
            return
        song_id = db.add_song(song)
        seed = (cover_source or "").strip()
        final_cover = save_and_resize_cover(seed, song_id)
        conn = db.get_connection()
        conn.cursor().execute("UPDATE songs SET cover_path = ? WHERE id = ?", (final_cover, song_id))
        conn.commit()
        conn.close()
        self._reload_queue_keep(song_id)
        self._update_ui_state()
        self._emit_library()
        self.toastMessage.emit("Трек добавлен", False)
        self._try_upload_to_drive(filepath, raw_title, raw_artist, final_cover, (lyrics or "").strip(), song_id)

    def _try_upload_to_drive(self, filepath, title, artist, cover_path, lyrics, song_id=0):
        if not self.drive.service and not os.path.exists(self.drive._token_file()):
            return
        self._drive_upload_worker = DriveUploadWorker(
            drive=self.drive,
            filepath=filepath,
            title=title,
            artist=artist,
            cover_path=cover_path or "",
            lyrics=lyrics or "",
            song_id=song_id,
        )
        self._drive_upload_worker.finished_ok.connect(
            lambda t: self.toastMessage.emit(f"Загружено в Drive: {t}", False)
        )
        self._drive_upload_worker.finished_err.connect(
            lambda e: self.toastMessage.emit(f"Ошибка Drive: {e}", True)
        )
        self._drive_upload_worker.start()

    @pyqtSlot(str, str, str, bool)
    def importFromSpotify(self, url, lyrics, cover_source, upload_to_drive):
        if self._import_worker and self._import_worker.isRunning():
            self.importFailed.emit("pipeline", "IMPORT_BUSY", "Импорт уже выполняется")
            return
        if upload_to_drive and self.drive.service is None and not os.path.exists(self.drive._token_file()):
            self.importFailed.emit(
                "drive_auth",
                "DRIVE_NOT_LOGGED_IN",
                "Сначала войди в Google Drive. Gmail должна быть в Test users в Google Cloud.",
            )
            return
        # Stop playback during import
        self.player.stop()
        self.importStarted.emit(url)
        self._import_worker = SpotifyImportWorker(
            track_url=url,
            drive=self.drive,
            lyrics=lyrics or "",
            cover_source=cover_source or "",
            video_link="",
            upload_to_drive=bool(upload_to_drive),
            save_to_db=True,
        )
        self._import_worker.finished_ok.connect(self._on_import_ok)
        self._import_worker.finished_err.connect(self._on_import_err)
        self._import_worker.progress.connect(lambda msg: self.importProgress.emit(msg))
        self._import_worker.start()

    def _on_import_ok(self, payload):
        all_songs = db.get_all_songs()
        if payload.get("song_id"):
            idx = next(
                (i for i, s in enumerate(all_songs) if s.id == payload["song_id"]),
                len(all_songs) - 1,
            )
            self.player.load_queue(all_songs, max(0, idx))
            self._update_ui_state()
        title = payload.get("title_display") or payload.get("title") or "track"
        if payload.get("duplicate"):
            title = f"{title} (уже была в библиотеке)"
        self._emit_library()
        self.importFinished.emit(title)

    def _on_import_err(self, err):
        stage = err.get("stage", "pipeline")
        code = err.get("code", "UNKNOWN")
        message = err.get("message", "Ошибка импорта")
        self.importFailed.emit(stage, code, message)

    @pyqtSlot(str, str, str, bool)
    def importFromYoutube(self, url, lyrics, cover_source, upload_to_drive):
        if self._youtube_import_worker and self._youtube_import_worker.isRunning():
            self.youtubeImportFailed.emit("pipeline", "IMPORT_BUSY", "Импорт с YouTube уже выполняется")
            return
        if upload_to_drive and self.drive.service is None and not os.path.exists(self.drive._token_file()):
            self.youtubeImportFailed.emit(
                "drive_auth",
                "DRIVE_NOT_LOGGED_IN",
                "Сначала войди в Google Drive или сними галочку загрузки на Drive.",
            )
            return
        self.player.stop()
        self.youtubeImportStarted.emit(url)
        self._youtube_import_worker = YoutubeImportWorker(
            url=url,
            drive=self.drive,
            lyrics=lyrics or "",
            cover_source=cover_source or "",
            upload_to_drive=bool(upload_to_drive),
        )
        self._youtube_import_worker.finished_ok.connect(self._on_youtube_import_ok)
        self._youtube_import_worker.finished_err.connect(self._on_youtube_import_err)
        self._youtube_import_worker.progress.connect(lambda msg: self.youtubeImportProgress.emit(msg))
        self._youtube_import_worker.start()

    def _on_youtube_import_ok(self, payload):
        all_songs = db.get_all_songs()
        if payload.get("song_id"):
            idx = next(
                (i for i, s in enumerate(all_songs) if s.id == payload["song_id"]),
                len(all_songs) - 1,
            )
            self.player.load_queue(all_songs, max(0, idx))
            self._update_ui_state()
        title = payload.get("title_display") or payload.get("title") or "track"
        if payload.get("duplicate"):
            title = f"{title} (уже была в библиотеке)"
        self._emit_library()
        self.youtubeImportFinished.emit(title)

    def _on_youtube_import_err(self, err):
        stage = err.get("stage", "pipeline")
        code = err.get("code", "UNKNOWN")
        message = err.get("message", "Ошибка импорта с YouTube")
        self.youtubeImportFailed.emit(stage, code, message)

    @pyqtSlot(str)
    def importArtistFromSpotify(self, query):
        if self._artist_import_worker and self._artist_import_worker.isRunning():
            self.artistImportFailed.emit("Загрузка дискографии уже выполняется")
            return
        from .spotify_web_service import get_saved_sp_dc
        if not get_saved_sp_dc():
            self.artistImportFailed.emit("Сначала войди в Spotify через «Спотифай автоматически»")
            return
        self.player.stop()
        self._artist_import_worker = ArtistImportWorker(query=query, drive=self.drive)
        self._artist_import_worker.progress.connect(self.artistImportProgress.emit)
        self._artist_import_worker.track_imported.connect(self._emit_library)
        self._artist_import_worker.finished_ok.connect(self._on_artist_import_ok)
        self._artist_import_worker.finished_err.connect(self._on_artist_import_err)
        self._artist_import_worker.start()

    @pyqtSlot()
    def stopArtistImport(self):
        if self._artist_import_worker and self._artist_import_worker.isRunning():
            self._artist_import_worker.request_stop()
            self.artistImportProgress.emit("Останавливаю после текущего трека…")

    def _on_artist_import_ok(self, stats: dict):
        self._reload_queue_keep()
        self._update_ui_state()
        self._emit_library()
        self._emit_playlists()
        text = (
            f"«{stats.get('artist_name', '')}»: новых треков {stats.get('imported', 0)}, "
            f"дублей пропущено {stats.get('skipped', 0)}, ошибок {stats.get('failed', 0)} "
            f"из {stats.get('total', 0)}"
        )
        if stats.get("stopped"):
            text = "Остановлено. " + text
        self.artistImportFinished.emit(text)

    def _on_artist_import_err(self, err: dict):
        stage = err.get("stage", "pipeline")
        code = err.get("code", "UNKNOWN")
        message = err.get("message", "Ошибка загрузки дискографии")
        detail = (err.get("detail") or "").strip()
        text = f"[{stage}:{code}] {message}"
        if detail:
            text += f" — {detail[:300]}"
        self.artistImportFailed.emit(text)

    @pyqtSlot(str)
    def importYoutubeChannel(self, url):
        if self._youtube_channel_worker and self._youtube_channel_worker.isRunning():
            self.youtubeChannelFailed.emit("Загрузка канала уже выполняется")
            return
        self.player.stop()
        self._youtube_channel_worker = YoutubeChannelWorker(
            url=url,
            drive=self.drive,
            upload_to_drive=bool(self.drive.service),
        )
        self._youtube_channel_worker.progress.connect(self.youtubeChannelProgress.emit)
        self._youtube_channel_worker.track_imported.connect(self._emit_library)
        self._youtube_channel_worker.finished_ok.connect(self._on_youtube_channel_ok)
        self._youtube_channel_worker.finished_err.connect(self._on_youtube_channel_err)
        self._youtube_channel_worker.start()

    @pyqtSlot()
    def stopYoutubeChannel(self):
        if self._youtube_channel_worker and self._youtube_channel_worker.isRunning():
            self._youtube_channel_worker.request_stop()
            self.youtubeChannelProgress.emit("Останавливаю после текущего видео…")

    def _on_youtube_channel_ok(self, stats: dict):
        self._reload_queue_keep()
        self._update_ui_state()
        self._emit_library()
        self._emit_playlists()
        text = (
            f"Новых треков {stats.get('imported', 0)}, дублей пропущено {stats.get('skipped', 0)}, "
            f"ошибок {stats.get('failed', 0)} из {stats.get('total', 0)}"
        )
        if stats.get("stopped"):
            text = "Остановлено. " + text
        self.youtubeChannelFinished.emit(text)

    def _on_youtube_channel_err(self, err: dict):
        stage = err.get("stage", "pipeline")
        code = err.get("code", "UNKNOWN")
        message = err.get("message", "Ошибка загрузки канала")
        detail = (err.get("detail") or "").strip()
        text = f"[{stage}:{code}] {message}"
        if detail:
            text += f" — {detail[:300]}"
        self.youtubeChannelFailed.emit(text)

    @pyqtSlot(str)
    def importTikTokCollection(self, url):
        if self._tiktok_collection_worker and self._tiktok_collection_worker.isRunning():
            self.tiktokCollectionFailed.emit("Загрузка коллекции TikTok уже выполняется")
            return
        self.player.stop()
        self._tiktok_collection_worker = TikTokCollectionWorker(
            url=url,
            drive=self.drive,
            upload_to_drive=bool(self.drive.service),
        )
        self._tiktok_collection_worker.progress.connect(self._on_tiktok_collection_progress)
        self._tiktok_collection_worker.track_imported.connect(self._on_tiktok_track_imported)
        self._tiktok_collection_worker.finished_ok.connect(self._on_tiktok_collection_ok)
        self._tiktok_collection_worker.finished_err.connect(self._on_tiktok_collection_err)
        self._tiktok_collection_worker.start()

    def _on_tiktok_collection_progress(self, msg: str) -> None:
        self.tiktokCollectionProgress.emit(msg)
        self._set_heavy_job_detail("tiktokCollection", msg)

    def _on_tiktok_track_imported(self) -> None:
        self._emit_library()
        self._emit_playlists()

    @pyqtSlot()
    def stopTikTokCollection(self):
        if self._tiktok_collection_worker and self._tiktok_collection_worker.isRunning():
            self._tiktok_collection_worker.request_stop()
            self.tiktokCollectionProgress.emit("Останавливаю после текущего видео…")

    def _on_tiktok_collection_ok(self, stats: dict):
        self._reload_queue_keep()
        self._update_ui_state()
        text = (
            f"Скачано треков: {stats.get('downloaded', 0)}. "
            f"Пропущено длинных {stats.get('skipped', 0)}, ошибок {stats.get('failed', 0)} "
            f"из {stats.get('total', 0)} видео"
        )
        if stats.get("stopped"):
            text = "Остановлено. " + text
        self.tiktokCollectionFinished.emit(text)

    def _on_tiktok_collection_err(self, err: dict):
        stage = err.get("stage", "pipeline")
        code = err.get("code", "UNKNOWN")
        message = err.get("message", "Ошибка загрузки коллекции TikTok")
        detail = (err.get("detail") or "").strip()
        text = f"[{stage}:{code}] {message}"
        if detail:
            text += f" — {detail[:300]}"
        self.tiktokCollectionFailed.emit(text)

    @pyqtSlot(int)
    def findInstrumental(self, song_id):
        """Только ищет инструментал на YouTube — ничего не скачивает.
        Найденное уходит в instrumentalFound, пользователь подтверждает скачивание
        отдельным вызовом downloadInstrumental (можно сперва открыть и прослушать)."""
        if self._instrumental_search_worker and self._instrumental_search_worker.isRunning():
            self.instrumentalFailed.emit("Поиск инструментала уже выполняется")
            return
        self.instrumentalStarted.emit(song_id)
        self._instrumental_search_worker = InstrumentalSearchWorker(song_id=song_id)
        self._instrumental_search_worker.progress.connect(self.instrumentalProgress.emit)
        self._instrumental_search_worker.finished_ok.connect(self._on_instrumental_found)
        self._instrumental_search_worker.finished_err.connect(self._on_instrumental_err)
        self._instrumental_search_worker.start()

    def _on_instrumental_found(self, payload: dict):
        self.instrumentalFound.emit(json.dumps(payload, ensure_ascii=False))

    @pyqtSlot(int, str)
    def downloadInstrumental(self, song_id, video_url):
        if self._instrumental_download_worker and self._instrumental_download_worker.isRunning():
            self.instrumentalFailed.emit("Скачивание инструментала уже выполняется")
            return
        self._instrumental_download_worker = InstrumentalDownloadWorker(
            song_id=song_id,
            video_url=video_url,
            drive=self.drive,
            upload_to_drive=bool(self.drive.service),
        )
        self._instrumental_download_worker.progress.connect(self.instrumentalProgress.emit)
        self._instrumental_download_worker.finished_ok.connect(self._on_instrumental_ok)
        self._instrumental_download_worker.finished_err.connect(self._on_instrumental_err)
        self._instrumental_download_worker.start()

    def _on_instrumental_ok(self, payload):
        self._emit_library()
        self._emit_playlists()
        title = payload.get("title_display") or payload.get("title") or "track"
        if payload.get("duplicate"):
            title = f"{title} (уже была в библиотеке)"
        self.instrumentalFinished.emit(title)

    def _on_instrumental_err(self, err):
        stage = err.get("stage", "pipeline")
        code = err.get("code", "UNKNOWN")
        message = err.get("message", "Не удалось найти инструментал")
        self.instrumentalFailed.emit(f"[{stage}:{code}] {message}")

    @pyqtSlot(int, float, float)
    def trimSongById(self, song_id, cut_start_seconds, cut_end_seconds):
        song = db.get_song(song_id)
        if not song or not song.filepath or not os.path.isfile(song.filepath):
            self.toastMessage.emit("Файл трека не найден", True)
            return
        self.player.stop()
        try:
            new_duration = trim_audio(song.filepath, cut_start_seconds, cut_end_seconds)
        except BlossomError as exc:
            self.toastMessage.emit(f"Не удалось обрезать: {exc.message}", True)
            return
        except Exception as exc:
            self.toastMessage.emit(f"Не удалось обрезать: {exc}", True)
            return
        db.set_song_fingerprint(song_id, None)
        self._reload_queue_keep(song_id)
        self._update_ui_state()
        self.toastMessage.emit(f"Обрезано. Новая длительность: {int(new_duration)} сек", False)

    @pyqtSlot(str)
    def searchOnline(self, query):
        """Поиск трека по тексту на YouTube и Spotify — показывает оба списка
        результатов, пользователь сам выбирает что импортировать (через уже
        существующие importFromYoutube/importFromSpotify)."""
        if self._online_search_worker and self._online_search_worker.isRunning():
            self.onlineSearchFailed.emit("Поиск уже выполняется")
            return
        self._online_search_worker = OnlineSearchWorker(query)
        self._online_search_worker.finished_ok.connect(
            lambda payload: self.onlineSearchReady.emit(json.dumps(payload, ensure_ascii=False))
        )
        self._online_search_worker.finished_err.connect(
            lambda err: self.onlineSearchFailed.emit(err.get("message") or "Не удалось выполнить поиск")
        )
        self._online_search_worker.start()

    @pyqtSlot(float, str)
    def startShazamListen(self, listen_seconds, source="mic"):
        # Клэмп на бэкенде — не доверяем, что JS-поле не прислало что-то за
        # пределами 8–30 сек (слишком короткая запись Shazam не распознаёт,
        # слишком длинная просто тратит время пользователя без выигрыша).
        clamped = max(8.0, min(30.0, float(listen_seconds or 8.0)))
        self._start_shazam(audio_path="", listen_seconds=clamped, source=source or "mic")

    @pyqtSlot(str)
    def identifyFromAudioFile(self, audio_path):
        self._start_shazam(audio_path=audio_path, listen_seconds=0, source="mic")

    def _start_shazam(self, audio_path: str, listen_seconds: float, source: str = "mic"):
        if self._shazam_worker and self._shazam_worker.isRunning():
            self.shazamFailed.emit("Распознавание уже выполняется")
            return
        self.shazamStarted.emit()
        self._shazam_worker = ShazamWorker(
            drive=self.drive,
            audio_path=audio_path,
            listen_seconds=listen_seconds,
            source=source,
        )
        self._shazam_worker.progress.connect(self.shazamProgress.emit)
        self._shazam_worker.finished_ok.connect(self._on_shazam_ok)
        self._shazam_worker.finished_err.connect(self._on_shazam_err)
        self._shazam_worker.start()

    def _on_shazam_ok(self, payload):
        self._emit_library()
        title = payload.get("title_display") or payload.get("title") or "track"
        if payload.get("duplicate"):
            title = f"{title} (уже была в библиотеке)"
        self.shazamFinished.emit(title)

    def _on_shazam_err(self, err: dict):
        stage = err.get("stage", "pipeline")
        code = err.get("code", "UNKNOWN")
        message = err.get("message", "Не удалось распознать трек")
        self.shazamFailed.emit(f"[{stage}:{code}] {message}" if code != "SHAZAM_NO_MATCH" else message)

    @pyqtSlot(str, str, str)
    def searchLyricsPreview(self, title, artist, filepath):
        """Разовый поиск текста для окна добавления локального трека (до сохранения в БД)."""
        if self._lyrics_preview_worker and self._lyrics_preview_worker.isRunning():
            self.lyricsPreviewFailed.emit("Поиск текста уже выполняется")
            return
        self._lyrics_preview_worker = LyricsPreviewWorker(
            title=(title or "").strip(),
            artist=(artist or "").strip() or "Unknown Artist",
            filepath=filepath or "",
        )
        self._lyrics_preview_worker.finished_ok.connect(self._on_lyrics_preview_ok)
        self._lyrics_preview_worker.finished_err.connect(self._on_lyrics_preview_err)
        self._lyrics_preview_worker.start()

    def _on_lyrics_preview_ok(self, payload):
        self.lyricsPreviewReady.emit(json.dumps(payload, ensure_ascii=False))

    def _on_lyrics_preview_err(self, err):
        self.lyricsPreviewFailed.emit(err.get("message", "Не удалось найти текст"))

    @pyqtSlot(int)
    def searchLyricsForSong(self, song_id):
        """Поиск текста для ОДНОЙ конкретной песни из библиотеки — кнопка на
        карточке песни без текста, в отличие от searchLyricsPreview сразу
        сохраняет результат в БД."""
        if self._single_lyrics_worker and self._single_lyrics_worker.isRunning():
            self.singleLyricsSearchFailed.emit(song_id, "Поиск текста уже выполняется")
            return
        song = db.get_song(song_id)
        if not song:
            return
        self._single_lyrics_worker = SingleLyricsSearchWorker(
            song_id=song_id,
            title=song.title,
            artist=song.artist,
            filepath=song.filepath or "",
            drive=self.drive,
        )
        self._single_lyrics_worker.finished_ok.connect(self._on_single_lyrics_ok)
        self._single_lyrics_worker.finished_err.connect(self._on_single_lyrics_err)
        self._single_lyrics_worker.start()

    def _on_single_lyrics_ok(self, song_id: int, result: dict):
        self._emit_library()
        current = self.player.get_current_song()
        if current and current.id == song_id:
            self._update_ui_state()
        msg = "Похоже, это инструментал — слов нет" if result.get("status") == "instrumental" else "Текст найден"
        self.singleLyricsSearchReady.emit(song_id, msg)

    def _on_single_lyrics_err(self, song_id: int, err: dict):
        self.singleLyricsSearchFailed.emit(song_id, err.get("message", "Не удалось найти текст"))

    def _any_lyrics_bulk_job_running(self) -> bool:
        return bool(
            (self._lyrics_bulk_worker and self._lyrics_bulk_worker.isRunning())
            or (self._clear_all_lyrics_worker and self._clear_all_lyrics_worker.isRunning())
        )

    @pyqtSlot()
    def findMissingLyrics(self):
        """Настройки → «Найти текст песен для песен без текста»: массовый проход
        по всей библиотеке, у кого текст ещё не заполнен."""
        if self._any_lyrics_bulk_job_running():
            self.lyricsBulkFailed.emit("Другая операция с текстами уже выполняется")
            return
        self.lyricsBulkStarted.emit()
        self._lyrics_bulk_worker = LyricsBulkWorker(drive=self.drive)
        self._lyrics_bulk_worker.progress.connect(self.lyricsBulkProgress.emit)
        self._lyrics_bulk_worker.finished_ok.connect(self._on_lyrics_bulk_ok)
        self._lyrics_bulk_worker.finished_err.connect(self._on_lyrics_bulk_err)
        self._lyrics_bulk_worker.start()

    @pyqtSlot()
    def recheckInstrumentalLyrics(self):
        """Настройки → «Перепроверить инструменталы»: повторно ищет текст для
        песен, уже помеченных инструментальными — на случай, если раньше их
        пометили так ошибочно (например, из-за бага скрейпинга Genius)."""
        if self._any_lyrics_bulk_job_running():
            self.lyricsBulkFailed.emit("Другая операция с текстами уже выполняется")
            return
        self.lyricsBulkStarted.emit()
        self._lyrics_bulk_worker = LyricsBulkWorker(drive=self.drive, mode="recheck_instrumental")
        self._lyrics_bulk_worker.progress.connect(self.lyricsBulkProgress.emit)
        self._lyrics_bulk_worker.finished_ok.connect(self._on_lyrics_bulk_ok)
        self._lyrics_bulk_worker.finished_err.connect(self._on_lyrics_bulk_err)
        self._lyrics_bulk_worker.start()

    @pyqtSlot()
    def clearAllLyrics(self):
        """Настройки → «Удалить текст у всех песен» (подтверждение у пользователя
        уже на стороне JS, здесь просто выполняем)."""
        if self._any_lyrics_bulk_job_running():
            self.lyricsBulkFailed.emit("Другая операция с текстами уже выполняется")
            return
        self.lyricsBulkStarted.emit()
        self._clear_all_lyrics_worker = ClearAllLyricsWorker(drive=self.drive)
        self._clear_all_lyrics_worker.progress.connect(self.lyricsBulkProgress.emit)
        self._clear_all_lyrics_worker.finished_ok.connect(self._on_clear_all_lyrics_ok)
        self._clear_all_lyrics_worker.finished_err.connect(self._on_lyrics_bulk_err)
        self._clear_all_lyrics_worker.start()

    def _on_clear_all_lyrics_ok(self, stats: dict):
        self._emit_library()
        self._update_ui_state()
        text = f"Удалено текстов: {stats.get('cleared', 0)} из {stats.get('total', 0)}"
        if stats.get("stopped"):
            text = "Остановлено. " + text
        self.lyricsBulkFinished.emit(text)

    @pyqtSlot()
    def stopFindMissingLyrics(self):
        if self._lyrics_bulk_worker and self._lyrics_bulk_worker.isRunning():
            self._lyrics_bulk_worker.request_stop()
            self.lyricsBulkProgress.emit("Останавливаю…")
        if self._clear_all_lyrics_worker and self._clear_all_lyrics_worker.isRunning():
            self._clear_all_lyrics_worker.request_stop()
            self.lyricsBulkProgress.emit("Останавливаю…")

    def _on_lyrics_bulk_ok(self, stats: dict):
        self._emit_library()
        self._update_ui_state()
        if stats.get("mode") == "recheck_instrumental":
            text = (
                f"Готово: текст нашёлся у {stats.get('found', 0)} из {stats.get('total', 0)} "
                f"ранее отмеченных инструменталом, "
                f"подтверждено инструменталом {stats.get('instrumental', 0)}, "
                f"ошибок {stats.get('failed', 0)}"
            )
        else:
            text = (
                f"Готово: найдено текстов {stats.get('found', 0)}, "
                f"инструменталов {stats.get('instrumental', 0)}, "
                f"ошибок {stats.get('failed', 0)} из {stats.get('total', 0)}"
            )
        if stats.get("stopped"):
            text = "Остановлено. " + text
        self.lyricsBulkFinished.emit(text)

    def _on_lyrics_bulk_err(self, err: dict):
        self.lyricsBulkFailed.emit(err.get("message", "Ошибка поиска текстов"))

    @pyqtSlot()
    def findDuplicates(self):
        if self._duplicate_finder_worker and self._duplicate_finder_worker.isRunning():
            self.duplicatesScanFailed.emit("Поиск дублей уже выполняется")
            return
        self._duplicate_finder_worker = DuplicateFinderWorker()
        self._duplicate_finder_worker.progress.connect(self.duplicatesScanProgress.emit)
        self._duplicate_finder_worker.finished_ok.connect(self._on_duplicates_ok)
        self._duplicate_finder_worker.finished_err.connect(self._on_duplicates_err)
        self._duplicate_finder_worker.start()

    @pyqtSlot()
    def stopDuplicateScan(self):
        if self._duplicate_finder_worker and self._duplicate_finder_worker.isRunning():
            self._duplicate_finder_worker.request_stop()
            self.duplicatesScanProgress.emit("Останавливаю…")

    def _on_duplicates_ok(self, groups: list):
        self.duplicatesScanFinished.emit(json.dumps(groups, ensure_ascii=False))

    def _on_duplicates_err(self, err: dict):
        stage = err.get("stage", "pipeline")
        code = err.get("code", "UNKNOWN")
        message = err.get("message", "Ошибка поиска дублей")
        detail = (err.get("detail") or "").strip()
        text = f"[{stage}:{code}] {message}"
        if detail:
            text += f" — {detail[:300]}"
        self.duplicatesScanFailed.emit(text)

    @pyqtSlot()
    def importSpotifyLibrary(self):
        """«Спотифай автоматически»: вход в Spotify и импорт всех плейлистов."""
        if self._spotify_library_worker and self._spotify_library_worker.isRunning():
            self.spotifyAutoProgress.emit("Импорт уже выполняется…")
            return
        if self._import_worker and self._import_worker.isRunning():
            self.spotifyAutoFailed.emit("Дождись окончания текущего импорта трека")
            return
        from .spotify_web_service import get_saved_sp_dc
        self._spotify_relogin_done = False
        if not get_saved_sp_dc():
            self._open_spotify_web_login()
            return
        self._start_spotify_library_worker()

    def _open_spotify_web_login(self):
        from .spotify_web_login import SpotifyWebLoginDialog
        self.spotifyAutoProgress.emit("Открываю окно входа в Spotify…")
        dialog = SpotifyWebLoginDialog(self._window())
        self._spotify_login_dialog = dialog
        dialog.sp_dc_captured.connect(lambda _v: self._start_spotify_library_worker())
        dialog.rejected.connect(lambda: self.spotifyAutoFailed.emit("Вход в Spotify отменён"))
        dialog.show()

    def _start_spotify_library_worker(self):
        if self._spotify_library_worker and self._spotify_library_worker.isRunning():
            return
        self.player.stop()
        self._spotify_library_worker = SpotifyLibraryWorker(self.drive)
        self._spotify_library_worker.progress.connect(self.spotifyAutoProgress.emit)
        self._spotify_library_worker.finished_ok.connect(self._on_spotify_library_ok)
        self._spotify_library_worker.finished_err.connect(self._on_spotify_library_err)
        self._spotify_library_worker.start()

    @pyqtSlot()
    def stopSpotifyLibraryImport(self):
        if self._spotify_library_worker and self._spotify_library_worker.isRunning():
            self._spotify_library_worker.request_stop()
            self.spotifyAutoProgress.emit("Останавливаю после текущего трека…")

    def _on_spotify_library_ok(self, stats: dict):
        self._reload_queue_keep()
        self._update_ui_state()
        self._emit_library()
        self._emit_playlists()
        text = (
            f"Готово! Новых треков: {stats.get('imported', 0)}, "
            f"дублей пропущено: {stats.get('skipped', 0)}, "
            f"ошибок: {stats.get('failed', 0)}, "
            f"плейлистов: {stats.get('playlists', 0)}"
        )
        if stats.get("stopped"):
            text = "Импорт остановлен. " + text
        self.spotifyAutoFinished.emit(text)
        self.toastMessage.emit(text, False)

    def _on_spotify_library_err(self, err: dict):
        stage = err.get("stage", "pipeline")
        code = err.get("code", "UNKNOWN")
        message = err.get("message", "Ошибка импорта Spotify")
        detail = (err.get("detail") or "").strip()
        # Сессия Spotify истекла — предложить вход заново (один раз, без цикла)
        if code in ("SPOTIFY_WEB_SESSION_EXPIRED", "SPOTIFY_WEB_LOGIN_REQUIRED"):
            from .spotify_web_service import clear_sp_dc
            if not getattr(self, "_spotify_relogin_done", False):
                self._spotify_relogin_done = True
                clear_sp_dc()
                self._open_spotify_web_login()
                return
        text = f"[{stage}:{code}] {message}"
        if detail:
            text += f" — {detail[:300]}"
        self.spotifyAutoFailed.emit(text)

    @pyqtSlot()
    def add_new_song_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self._window(),
            "Выбери трек",
            "",
            "Audio (*.mp3 *.m4a *.flac *.wav)",
        )
        if not path:
            return
        title = os.path.splitext(os.path.basename(path))[0]
        new_song = Song(
            title=wrap_title(title),
            artist=wrap_artist("Unknown Artist"),
            filepath=path,
            lyrics=DEFAULT_LYRICS,
            video_link="",
        )
        song_id = db.add_song(new_song)
        cover_path = save_and_resize_cover("", song_id)
        conn = db.get_connection()
        conn.cursor().execute("UPDATE songs SET cover_path = ? WHERE id = ?", (cover_path, song_id))
        conn.commit()
        conn.close()
        self._reload_queue_keep(song_id)
        self._update_ui_state()
        self._emit_library()
        self.toastMessage.emit("Трек добавлен", False)
