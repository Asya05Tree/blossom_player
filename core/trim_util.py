"""Обрезка начала/конца аудиофайла без потери ID3-тегов.

Режем через ffmpeg (-c copy, без перекодирования — быстро и без потери качества),
а исходные ID3-теги принудительно переписываем обратно после обрезки мутагеном,
чтобы не зависеть от того, перенёс ли их сам ffmpeg при копировании потока.
"""
import json
import os
import shutil
import subprocess

from mutagen.id3 import ID3, ID3NoHeaderError

from .blossom_error import Stage, fail
from .ffmpeg_util import resolve_ffmpeg, resolve_ffprobe
from .paths import TEMP_DIR


def get_duration_seconds(filepath: str) -> float:
    if not filepath or not os.path.isfile(filepath):
        fail(Stage.FILE_IO, "TRIM_FILE_MISSING", "Файл не найден", filepath or "")
    ffprobe = resolve_ffprobe()
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", filepath],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(proc.stdout)
        return float(data["format"]["duration"])
    except Exception as exc:
        fail(Stage.PIPELINE, "TRIM_DURATION_FAIL", "Не удалось определить длительность файла", str(exc))


def trim_audio(filepath: str, cut_start_seconds: float, cut_end_seconds: float) -> float:
    """Обрезает cut_start_seconds с начала и cut_end_seconds с конца (по месту).

    Возвращает новую длительность файла в секундах.
    """
    if not filepath or not os.path.isfile(filepath):
        fail(Stage.FILE_IO, "TRIM_FILE_MISSING", "Файл для обрезки не найден", filepath or "")
    cut_start_seconds = max(0.0, float(cut_start_seconds or 0))
    cut_end_seconds = max(0.0, float(cut_end_seconds or 0))
    if cut_start_seconds == 0 and cut_end_seconds == 0:
        fail(Stage.PIPELINE, "TRIM_NOOP", "Нужно указать хотя бы одну границу обрезки")

    duration = get_duration_seconds(filepath)
    end_at = duration - cut_end_seconds
    if end_at <= cut_start_seconds:
        fail(Stage.PIPELINE, "TRIM_RANGE_INVALID", "После обрезки от файла ничего не останется")

    try:
        original_tags = ID3(filepath)
    except ID3NoHeaderError:
        original_tags = None
    except Exception:
        original_tags = None

    os.makedirs(TEMP_DIR, exist_ok=True)
    tmp_out = os.path.join(TEMP_DIR, f"trim_{os.path.basename(filepath)}")
    if os.path.isfile(tmp_out):
        os.remove(tmp_out)

    ffmpeg = resolve_ffmpeg()
    cmd = [
        ffmpeg, "-y", "-i", filepath,
        "-ss", str(cut_start_seconds), "-to", str(end_at),
        "-c", "copy", "-map_metadata", "0",
        tmp_out,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as exc:
        fail(Stage.PIPELINE, "TRIM_RUN_FAIL", "Не удалось запустить ffmpeg для обрезки", str(exc))
    if proc.returncode != 0 or not os.path.isfile(tmp_out) or os.path.getsize(tmp_out) <= 0:
        fail(Stage.PIPELINE, "TRIM_FFMPEG_FAIL", "ffmpeg не смог обрезать файл", (proc.stderr or "")[-400:])

    if original_tags is not None:
        try:
            original_tags.save(tmp_out)
        except Exception:
            pass

    backup = filepath + ".trimbak"
    shutil.copy2(filepath, backup)
    try:
        os.replace(tmp_out, filepath)
    except Exception as exc:
        fail(Stage.FILE_IO, "TRIM_REPLACE_FAIL", "Не удалось заменить исходный файл обрезанным", str(exc))
    finally:
        if os.path.isfile(backup):
            os.remove(backup)

    return get_duration_seconds(filepath)
