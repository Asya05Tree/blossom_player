import os
import time

from PyQt6.QtCore import QThread, pyqtSignal

from . import database as db
from .drive_meta_sync import push_song_meta
from .lrclib_service import fetch_synced_lyrics
from .lyrics_service import INSTRUMENTAL_MARK, resolve_lyrics_for_song
from .text_style import strip_decor


def _audio_duration_seconds(filepath: str) -> float:
    """Длительность трека нужна lrclib.net для точного совпадения записи
    (одно название часто встречается в нескольких версиях разной длины)."""
    if not filepath or not os.path.isfile(filepath):
        return 0.0
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(filepath)
        return float(audio.info.length) if audio and audio.info else 0.0
    except Exception:
        return 0.0

# Пауза между песнями в массовом поиске — чтобы не долбить Genius пачкой
# запросов подряд (повышает риск временной блокировки) и не прогонять через
# Shazam-фолбэк десятки треков без паузы (см. use_shazam_fallback=False ниже —
# shazamio-core нативный, и многократные быстрые вызовы подряд из фонового
# потока — вероятная причина периодических жёстких крашей приложения).
_BULK_DELAY_SECONDS = 1.0

# BATCH_SIZE группирует progress-сигналы (один на пачку, а не один на каждую
# песню) — так цикл по сотням песен не заливает GUI-поток/QtWebChannel сотнями
# сигналов в секунду. Раньше здесь были ещё DRIVE_CALL_PAUSE_SECONDS/
# BATCH_PAUSE_SECONDS — искусственные паузы вокруг каждого Drive-запроса,
# добавленные пока настоящая причина крашей была не найдена. Реальная причина
# оказалась гонкой потоков на общем self.service (см. core/drive.py,
# threading.RLock) — она исправлена на уровне Drive-клиента, так что пачки
# теперь обрабатываются быстро и без искусственных задержек.
BATCH_SIZE = 25


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
            if result.get("status") == "error":
                self.finished_err.emit({
                    "stage": "pipeline",
                    "code": "LYRICS_BLOCKED",
                    "message": result.get("error") or "Не удалось проверить текст (сетевая блокировка)",
                })
                return
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

    def __init__(self, drive=None, mode: str = "missing"):
        super().__init__()
        self.drive = drive
        # "missing" — песни без текста; "recheck_instrumental" — повторная
        # проверка уже помеченных инструментальными (на случай, если раньше
        # их пометили так ошибочно — например, из-за бага скрейпинга Genius).
        self.mode = mode
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
        if self.mode == "recheck_instrumental":
            songs = db.get_instrumental_songs()
        else:
            songs = db.get_songs_without_lyrics()
        total = len(songs)
        found = instrumental = failed = blocked_in_a_row = 0
        for idx, song in enumerate(songs, start=1):
            if self._stop_requested:
                break
            title = strip_decor(song.title)
            artist = strip_decor(song.artist)
            self.progress.emit(f"({idx}/{total}) {artist} — {title}…")
            try:
                result = resolve_lyrics_for_song(
                    song.title, song.artist, song.filepath or "", use_shazam_fallback=False,
                )
            except Exception:
                failed += 1
                continue
            status = result.get("status")
            if status == "error":
                # Блокировка/сетевая ошибка — не доказывает отсутствие текста,
                # оставляем песню как есть (плейсхолдер), попробуем в другой раз.
                failed += 1
                blocked_in_a_row += 1
                if blocked_in_a_row >= 3:
                    self.progress.emit("Genius временно блокирует запросы — остановлено, попробуй позже")
                    break
                time.sleep(_BULK_DELAY_SECONDS)
                continue
            blocked_in_a_row = 0
            lyrics = result.get("lyrics") or INSTRUMENTAL_MARK
            db.update_song_lyrics(song.id, lyrics)
            if self.drive is not None:
                push_song_meta(self.drive, song, title, artist, lyrics)
            if status == "instrumental":
                instrumental += 1
            else:
                found += 1
            time.sleep(_BULK_DELAY_SECONDS)
        return {
            "mode": self.mode,
            "total": total,
            "found": found,
            "instrumental": instrumental,
            "failed": failed,
            "stopped": self._stop_requested,
        }


class ClearAllLyricsWorker(QThread):
    """Настройки → «Удалить текст у всех песен»: массовая очистка текста
    (включая метки инструментала) у всей библиотеки — например, чтобы
    переразыскать всё заново после правки поиска текста."""

    progress = pyqtSignal(str)
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(dict)

    def __init__(self, drive=None):
        super().__init__()
        self.drive = drive
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def run(self):
        try:
            stats = self._clear_all()
            self.finished_ok.emit(stats)
        except Exception as exc:
            self.finished_err.emit({
                "stage": "pipeline",
                "code": "LYRICS_CLEAR_ALL_CRASH",
                "message": "Ошибка при удалении текстов",
                "detail": str(exc),
            })

    def _clear_all(self) -> dict:
        songs = [
            s for s in db.get_all_songs()
            if (s.lyrics or "").strip() and (s.lyrics or "").strip() != db.DEFAULT_LYRICS_PLACEHOLDER
        ]
        total = len(songs)
        cleared = 0
        for batch_start in range(0, total, BATCH_SIZE):
            if self._stop_requested:
                break
            batch = songs[batch_start: batch_start + BATCH_SIZE]
            self.progress.emit(f"Удаляю {batch_start + 1}–{batch_start + len(batch)} из {total}…")
            for song in batch:
                if self._stop_requested:
                    break
                title = strip_decor(song.title)
                artist = strip_decor(song.artist)
                db.update_song_lyrics(song.id, "")
                if self.drive is not None:
                    push_song_meta(self.drive, song, title, artist, "")
                cleared += 1
        return {
            "total": total,
            "cleared": cleared,
            "stopped": self._stop_requested,
        }


class SyncedLyricsWorker(QThread):
    """Разовый фоновый поиск караоке-текста (с таймкодами) для одной песни —
    запускается при включении трека, если для него ещё не пробовали искать."""

    finished_ok = pyqtSignal(int, str)   # song_id, lrc text ("" если не нашли)
    finished_err = pyqtSignal(int, str)  # song_id, сообщение об ошибке

    def __init__(self, song_id: int, title: str, artist: str, filepath: str = ""):
        super().__init__()
        self.song_id = song_id
        self.title = title
        self.artist = artist
        self.filepath = filepath

    def run(self):
        try:
            duration = _audio_duration_seconds(self.filepath)
            lrc = fetch_synced_lyrics(self.title, self.artist, duration)
            db.update_song_synced_lyrics(self.song_id, lrc)
            self.finished_ok.emit(self.song_id, lrc)
        except Exception as exc:
            self.finished_err.emit(self.song_id, str(exc))
