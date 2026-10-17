"""Сканирование коллекции видео TikTok: каждое видео прослушивается Shazam'ом
в нескольких точках (в одном ролике может быть смонтировано несколько треков
подряд). Для каждой распознанной песни сразу скачивается первый найденный
на YouTube результат — без промежуточного выбора пользователем, потому что
коллекции могут быть большими и ждать подтверждения на каждый трек неудобно."""
import os
import uuid

from PyQt6.QtCore import QThread, pyqtSignal

from . import database as db
from .blossom_error import BlossomError
from .drive import BlossomDriveManager
from .log_util import log_to_file
from .models import Playlist
from .shazam_util import identify_from_file
from .text_style import wrap_title
from .tiktok_downloader import (
    TIKTOK_TEMP_DIR,
    download_tiktok_video_audio,
    extract_audio_clip,
    list_tiktok_collection_videos,
)
from .youtube_downloader import search_youtube_results
from .youtube_import_pipeline import import_youtube_track_safe

TIKTOK_PLAYLIST_NAME = "TikTok"
COLLECTION_VIDEO_LIMIT = 30
# Видео дольше этого считаются компиляциями/стримами, а не отдельными
# роликами с одной-двумя песнями — пользователь попросил не тратить время
# на распознавание в них.
MAX_VIDEO_DURATION_SECONDS = 5 * 60
PROBE_CLIP_SECONDS = 12
PROBE_OFFSET_RATIOS = (0.1, 0.45, 0.8)


class TikTokCollectionWorker(QThread):
    """Сканирует все видео коллекции/профиля TikTok (до COLLECTION_VIDEO_LIMIT
    штук) и для каждой распознанной Shazam'ом песни сразу скачивает первый
    найденный на YouTube результат в общий плейлист «TikTok»."""

    progress = pyqtSignal(str)
    track_imported = pyqtSignal()
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(dict)

    def __init__(self, url: str, drive: BlossomDriveManager, upload_to_drive: bool = False):
        super().__init__()
        self.url = (url or "").strip()
        self.drive = drive
        self.upload_to_drive = upload_to_drive
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def run(self):
        try:
            stats = self._run_scan()
            self.finished_ok.emit(stats)
        except BlossomError as exc:
            self.finished_err.emit(exc.to_dict())
        except Exception as exc:
            self.finished_err.emit({
                "stage": "pipeline",
                "code": "TIKTOK_COLLECTION_CRASH",
                "message": "Ошибка сканирования коллекции TikTok",
                "detail": str(exc),
            })

    def _run_scan(self) -> dict:
        self.progress.emit("Читаю список видео TikTok…")
        listing = list_tiktok_collection_videos(self.url, limit=COLLECTION_VIDEO_LIMIT)
        videos = listing["videos"]
        if not videos:
            return {"downloaded": 0, "skipped": 0, "failed": 0, "total": 0}

        playlist_id = self._ensure_playlist()

        downloaded = skipped = failed = 0
        total = len(videos)
        self.progress.emit(f"Найдено видео: {total} (за раз максимум {COLLECTION_VIDEO_LIMIT})")
        log_to_file("tiktok_collection", f"Старт: «{listing['source_title']}», видео {total}")

        for done, video in enumerate(videos, start=1):
            if self._stop_requested:
                break
            label = video["title"] or video["id"] or video["url"]

            duration = video.get("duration") or 0
            if duration and duration > MAX_VIDEO_DURATION_SECONDS:
                skipped += 1
                self.progress.emit(
                    f"[{done}/{total}] Пропускаю (видео {duration // 60} мин — слишком длинное): {label}"
                )
                continue

            self.progress.emit(f"[{done}/{total}] Скачиваю видео для распознавания: {label}")
            try:
                video_file = download_tiktok_video_audio(video["url"])
            except Exception as exc:
                log_to_file("tiktok_collection", f"[{done}/{total}] скачивание не удалось {label}: {exc}")
                failed += 1
                continue

            real_duration = video_file.get("duration") or duration
            if real_duration and real_duration > MAX_VIDEO_DURATION_SECONDS:
                skipped += 1
                self.progress.emit(
                    f"[{done}/{total}] Пропускаю (видео {int(real_duration) // 60} мин — слишком длинное): {label}"
                )
                self._cleanup(video_file["filepath"])
                continue

            self.progress.emit(f"[{done}/{total}] Распознаю музыку в видео…")
            found_songs = self._identify_songs(video_file["filepath"], real_duration)
            self._cleanup(video_file["filepath"])

            if not found_songs:
                self.progress.emit(f"[{done}/{total}] Не удалось распознать музыку: {label}")
                failed += 1
                continue

            for title, artist in found_songs:
                if self._stop_requested:
                    break
                query = f"{artist} {title}".strip()
                self.progress.emit(f"[{done}/{total}] Распознано «{title}» — {artist}. Скачиваю…")
                try:
                    results = search_youtube_results(query, limit=1)
                except Exception as exc:
                    log_to_file("tiktok_collection", f"поиск не удался для «{title}» — {artist}: {exc}")
                    failed += 1
                    continue
                if not results:
                    failed += 1
                    continue

                result = import_youtube_track_safe(
                    results[0]["url"],
                    self.drive,
                    title_override=title,
                    artist_override=artist,
                    upload_to_drive=self.upload_to_drive,
                    progress_callback=lambda msg: self.progress.emit(f"[{done}/{total}] {msg}"),
                )
                if not result.get("ok"):
                    log_to_file("tiktok_collection", f"скачивание не удалось для «{title}» — {artist}: {result.get('error')}")
                    failed += 1
                    continue

                if result.get("song_id"):
                    db.add_song_to_playlist(playlist_id, result["song_id"])
                downloaded += 1
                self.progress.emit(f"[{done}/{total}] Скачано: {artist} — {title}")
                self.track_imported.emit()

        log_to_file(
            "tiktok_collection",
            f"Готово: «{listing['source_title']}» — скачано {downloaded}, "
            f"пропущено {skipped}, ошибок {failed}",
        )

        return {
            "downloaded": downloaded,
            "skipped": skipped,
            "failed": failed,
            "total": total,
            "stopped": self._stop_requested,
        }

    def _identify_songs(self, filepath: str, duration: float) -> list:
        """Прослушивает файл Shazam'ом в нескольких точках и возвращает
        уникальные найденные (title, artist) — в одном видео может быть
        смонтировано несколько песен подряд."""
        if duration and duration > PROBE_CLIP_SECONDS:
            offsets = sorted({
                min(max(0.0, duration - PROBE_CLIP_SECONDS), duration * ratio)
                for ratio in PROBE_OFFSET_RATIOS
            })
        else:
            offsets = [0.0]

        found = {}
        for offset in offsets:
            if self._stop_requested:
                break
            clip_path = os.path.join(TIKTOK_TEMP_DIR, f"probe_{uuid.uuid4().hex}.mp3")
            try:
                if not extract_audio_clip(filepath, offset, PROBE_CLIP_SECONDS, clip_path):
                    continue
                info = identify_from_file(clip_path)
            except Exception:
                info = {}
            finally:
                self._cleanup(clip_path)

            title = (info.get("title") or "").strip()
            artist = (info.get("artist") or "").strip()
            if not title:
                continue
            key = (title.lower(), artist.lower())
            if key not in found:
                found[key] = (title, artist)
        return list(found.values())

    def _cleanup(self, path: str) -> None:
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass

    def _ensure_playlist(self) -> int:
        existing = db.get_playlist_by_name(TIKTOK_PLAYLIST_NAME)
        if existing:
            if not existing.is_default:
                db.mark_playlist_default(existing.id)
            return existing.id
        try:
            display = wrap_title(TIKTOK_PLAYLIST_NAME)
        except Exception:
            display = TIKTOK_PLAYLIST_NAME
        return db.add_playlist(Playlist(name=display, is_default=True))
