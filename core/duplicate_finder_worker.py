import os
import re

from PyQt6.QtCore import QThread, pyqtSignal

from . import database as db
from .blossom_error import BlossomError
from .fingerprint_util import (
    DEFAULT_DUPLICATE_THRESHOLD,
    compute_fingerprint,
    fingerprint_duration,
    fingerprint_similarity,
)
from .text_style import strip_decor

# Сравниваем отпечатки только у треков с похожей длительностью — иначе
# пришлось бы попарно сравнивать всю библиотеку (O(n²) на тысячах треков).
# Сужено с 3.0: нам нужны настоящие повторные копии одного и того же файла,
# а не просто похожие по звуку треки с чуть разной длиной.
DURATION_TOLERANCE_SECONDS = 2.0

_INSTRUMENTAL_RE = re.compile(r"instrumental|инструментал", re.IGNORECASE)


def _is_instrumental_title(title: str) -> bool:
    return bool(_INSTRUMENTAL_RE.search(title or ""))


class DuplicateFinderWorker(QThread):
    """Строит отпечатки для треков без них и ищет вероятные дубли по звуку."""

    progress = pyqtSignal(str)
    finished_ok = pyqtSignal(list)
    finished_err = pyqtSignal(dict)

    def __init__(self, threshold: float = DEFAULT_DUPLICATE_THRESHOLD):
        super().__init__()
        self.threshold = threshold
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def run(self):
        try:
            groups = self._scan()
            self.finished_ok.emit(groups)
        except BlossomError as exc:
            self.finished_err.emit(exc.to_dict())
        except Exception as exc:
            self.finished_err.emit({
                "stage": "pipeline",
                "code": "DUPLICATE_SCAN_CRASH",
                "message": "Ошибка поиска дублей",
                "detail": str(exc),
            })

    def _build_missing_fingerprints(self):
        missing = db.get_songs_missing_fingerprint()
        total = len(missing)
        if not total:
            return
        for index, song in enumerate(missing, start=1):
            if self._stop_requested:
                return
            label = f"{strip_decor(song.artist)} — {strip_decor(song.title)}"
            self.progress.emit(f"Строю отпечаток {index}/{total}: {label}")
            try:
                fp = compute_fingerprint(song.filepath)
                db.set_song_fingerprint(song.id, fp)
            except BlossomError as exc:
                self.progress.emit(f"Пропускаю (не вышло построить отпечаток): {label} — {exc.message}")

    def _scan(self) -> list[dict]:
        self._build_missing_fingerprints()
        if self._stop_requested:
            return []

        self.progress.emit("Сравниваю треки…")
        candidates = [
            (song, fingerprint_duration(song.fingerprint))
            for song in db.get_all_songs()
            if song.fingerprint
        ]
        candidates.sort(key=lambda pair: pair[1])
        n = len(candidates)
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[ry] = rx

        for i in range(n):
            if self._stop_requested:
                break
            song_i, dur_i = candidates[i]
            instr_i = _is_instrumental_title(song_i.title)
            j = i + 1
            while j < n and candidates[j][1] - dur_i <= DURATION_TOLERANCE_SECONDS:
                song_j, _ = candidates[j]
                # Инструментал и обычная версия никогда не дубликаты друг друга,
                # даже если звуковой отпечаток совпал (общая подложка) — это
                # разные треки по смыслу, а не два файла одной записи.
                if instr_i != _is_instrumental_title(song_j.title):
                    j += 1
                    continue
                sim = fingerprint_similarity(song_i.fingerprint, song_j.fingerprint)
                if sim >= self.threshold:
                    union(i, j)
                j += 1

        groups_map: dict[int, list] = {}
        for i, (song, _) in enumerate(candidates):
            groups_map.setdefault(find(i), []).append(song)

        groups = []
        for members in groups_map.values():
            if len(members) > 1:
                groups.append({
                    "songs": [
                        {
                            "id": s.id,
                            "title": s.title,
                            "artist": s.artist,
                            "title_raw": strip_decor(s.title),
                            "artist_raw": strip_decor(s.artist),
                            "filepath": s.filepath,
                            "filesize": self._safe_filesize(s.filepath),
                            "is_instrumental": _is_instrumental_title(s.title),
                        }
                        for s in members
                    ]
                })
        return groups

    @staticmethod
    def _safe_filesize(filepath: str) -> int:
        try:
            return os.path.getsize(filepath) if filepath and os.path.isfile(filepath) else 0
        except OSError:
            return 0
