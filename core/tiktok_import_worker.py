"""Сканирование коллекции видео TikTok: каждое видео прослушивается Shazam'ом
в нескольких точках (в одном ролике может быть смонтировано несколько треков
подряд). Сам воркер НИЧЕГО не скачивает — только находит кандидатов и
предлагает их пользователю на подтверждение (прослушать/скачать/пропустить),
потому что распознавание по 12-секундному отрывку может ошибаться."""
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

COLLECTION_VIDEO_LIMIT = 30
# Видео дольше этого считаются компиляциями/стримами, а не отдельными
# роликами с одной-двумя песнями — пользователь попросил не тратить время
# на распознавание в них.
MAX_VIDEO_DURATION_SECONDS = 5 * 60
PROBE_CLIP_SECONDS = 12
PROBE_OFFSET_RATIOS = (0.1, 0.45, 0.8)
CANDIDATE_RESULTS_LIMIT = 4


class TikTokCollectionWorker(QThread):
    """Сканирует все видео коллекции/профиля TikTok (до COLLECTION_VIDEO_LIMIT
    штук) и для каждой распознанной Shazam'ом песни эмитит candidate_found —
    само скачивание происходит отдельно, только после подтверждения пользователем."""

    progress = pyqtSignal(str)
    candidate_found = pyqtSignal(dict)
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
            return {"identified": 0, "skipped": 0, "failed": 0, "total": 0}

        playlist_id = self._ensure_playlist(f"TikTok: {listing['source_title']}")

        identified = skipped = failed = 0
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
                downloaded = download_tiktok_video_audio(video["url"])
            except Exception as exc:
                log_to_file("tiktok_collection", f"[{done}/{total}] скачивание не удалось {label}: {exc}")
                failed += 1
                continue

            real_duration = downloaded.get("duration") or duration
            if real_duration and real_duration > MAX_VIDEO_DURATION_SECONDS:
                skipped += 1
                self.progress.emit(
                    f"[{done}/{total}] Пропускаю (видео {int(real_duration) // 60} мин — слишком длинное): {label}"
                )
                self._cleanup(downloaded["filepath"])
                continue

            self.progress.emit(f"[{done}/{total}] Распознаю музыку в видео…")
            found_songs = self._identify_songs(downloaded["filepath"], real_duration)
            self._cleanup(downloaded["filepath"])

            if not found_songs:
                self.progress.emit(f"[{done}/{total}] Не удалось распознать музыку: {label}")
                failed += 1
                continue

            for title, artist in found_songs:
                if self._stop_requested:
                    break
                query = f"{artist} {title}".strip()
                self.progress.emit(f"[{done}/{total}] Распознано «{title}» — {artist}. Ищу варианты…")
                try:
                    results = search_youtube_results(query, limit=CANDIDATE_RESULTS_LIMIT)
                except Exception as exc:
                    log_to_file("tiktok_collection", f"поиск не удался для «{title}» — {artist}: {exc}")
                    failed += 1
                    continue
                if not results:
                    failed += 1
                    continue
                identified += 1
                self.candidate_found.emit({
                    "video_label": label,
                    "title": title,
                    "artist": artist,
                    "playlist_id": playlist_id,
                    "results": results,
                })

        log_to_file(
            "tiktok_collection",
            f"Готово: «{listing['source_title']}» — найдено кандидатов {identified}, "
            f"пропущено {skipped}, ошибок {failed}",
        )

        return {
            "identified": identified,
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

    def _ensure_playlist(self, name: str) -> int:
        existing = db.get_playlist_by_name(name)
        if existing:
            return existing.id
        try:
            display = wrap_title(name)
        except Exception:
            display = name
        return db.add_playlist(Playlist(name=display))


class TikTokCandidateDownloadWorker(QThread):
    """Скачивает ОДНОГО подтверждённого пользователем кандидата (после
    прослушивания в модалке) — независимо от потока сканирования коллекции."""

    progress = pyqtSignal(str)
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(dict)

    def __init__(self, url: str, drive: BlossomDriveManager, playlist_id: int = 0, upload_to_drive: bool = False):
        super().__init__()
        self.url = (url or "").strip()
        self.drive = drive
        self.playlist_id = playlist_id
        self.upload_to_drive = upload_to_drive

    def run(self):
        try:
            result = import_youtube_track_safe(
                self.url,
                self.drive,
                upload_to_drive=self.upload_to_drive,
                progress_callback=lambda msg: self.progress.emit(msg),
            )
            if result.get("ok") and result.get("song_id") and self.playlist_id:
                db.add_song_to_playlist(self.playlist_id, result["song_id"])
            if result.get("ok"):
                self.finished_ok.emit(result)
            else:
                self.finished_err.emit(result.get("error") or {})
        except BlossomError as exc:
            self.finished_err.emit(exc.to_dict())
        except Exception as exc:
            self.finished_err.emit({
                "stage": "pipeline",
                "code": "TIKTOK_CANDIDATE_DOWNLOAD_CRASH",
                "message": "Ошибка скачивания выбранного трека",
                "detail": str(exc),
            })
