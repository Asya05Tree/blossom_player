"""Реальный аудио-спектр (не имитация) для визуализатора вокруг обложки.

QMediaPlayer (Qt6 Multimedia) не даёт хука на сырые PCM-сэмплы во время
воспроизведения (QAudioProbe из Qt5 в Qt6 убрали) — поэтому спектр считается
не "вживую" из звуковой карты, а заранее, одним проходом по файлу через
ffmpeg (уже используется в проекте), покадрово через FFT. Кадры кэшируются
на диске по пути к файлу, так что при повторном включении той же песни
пересчёта не происходит. Фронтенд синхронизирует кадр с текущей позицией
воспроизведения (core/bridge.py шлёт позицию, кадр = позиция // FRAME_MS).
"""
import hashlib
import json
import os
import subprocess

import numpy as np

from .ffmpeg_util import resolve_ffmpeg
from .paths import TEMP_DIR
from .proc_util import NO_WINDOW_FLAGS

SAMPLE_RATE = 11025  # хватает для визуализации (до ~5.5 кГц) и быстро читать/анализировать
FRAME_MS = 50
BANDS = 24
_CACHE_DIR = os.path.join(TEMP_DIR, "spectrum_cache")


def _cache_path(filepath: str) -> str:
    key = hashlib.sha1(os.path.abspath(filepath).encode("utf-8")).hexdigest()
    return os.path.join(_CACHE_DIR, f"{key}.json")


def analyze_spectrum(filepath: str) -> list:
    """Возвращает список кадров — [[BANDS чисел 0..1], ...], один кадр на
    FRAME_MS мс звука. Пустой список, если файл не прочитать."""
    if not filepath or not os.path.isfile(filepath):
        return []

    cache_file = _cache_path(filepath)
    if os.path.isfile(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass

    try:
        ffmpeg = resolve_ffmpeg()
    except Exception:
        return []

    cmd = [
        ffmpeg, "-v", "quiet", "-i", filepath,
        "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=120, creationflags=NO_WINDOW_FLAGS,
        )
    except Exception:
        return []
    raw = proc.stdout
    if not raw:
        return []

    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    frame_size = int(SAMPLE_RATE * FRAME_MS / 1000)
    num_frames = len(samples) // frame_size
    if num_frames <= 0:
        return []

    window = np.hanning(frame_size)
    freqs = np.fft.rfftfreq(frame_size, d=1.0 / SAMPLE_RATE)
    band_edges = np.logspace(np.log10(60), np.log10(SAMPLE_RATE / 2 - 50), BANDS + 1)
    band_masks = [(freqs >= band_edges[b]) & (freqs < band_edges[b + 1]) for b in range(BANDS)]

    frames = np.empty((num_frames, BANDS), dtype=np.float32)
    for i in range(num_frames):
        chunk = samples[i * frame_size:(i + 1) * frame_size] * window
        spectrum = np.abs(np.fft.rfft(chunk))
        for b, mask in enumerate(band_masks):
            frames[i, b] = spectrum[mask].mean() if mask.any() else 0.0

    max_val = float(frames.max()) if frames.size else 0.0
    if max_val > 0:
        frames = frames / max_val
    # Громкость воспринимается логарифмически — без сжатия тихие участки
    # выглядят практически плоскими на фоне пары громких пиков.
    frames = np.sqrt(np.clip(frames, 0.0, 1.0))

    result = frames.round(3).tolist()
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as fh:
            json.dump(result, fh)
    except Exception:
        pass
    return result
