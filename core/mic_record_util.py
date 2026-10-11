import os
import wave

from .blossom_error import Stage, fail
from .paths import TEMP_DIR

SAMPLE_RATE = 44100
CHANNELS = 1


def record_clip(duration_seconds: float = 8.0) -> str:
    """Записывает duration_seconds секунд с микрофона в WAV, возвращает путь к файлу."""
    try:
        import sounddevice as sd
    except Exception as exc:
        fail(Stage.PIPELINE, "MIC_BACKEND_MISSING", "Не удалось подключиться к микрофону (sounddevice)", str(exc))

    try:
        frames = sd.rec(int(duration_seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16")
        sd.wait()
    except Exception as exc:
        fail(Stage.PIPELINE, "MIC_RECORD_FAIL", "Не удалось записать звук с микрофона", str(exc))

    os.makedirs(TEMP_DIR, exist_ok=True)
    out_path = os.path.join(TEMP_DIR, "shazam_listen.wav")
    try:
        with wave.open(out_path, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(frames.tobytes())
    except Exception as exc:
        fail(Stage.FILE_IO, "MIC_WAV_WRITE_FAIL", "Не удалось сохранить запись с микрофона", str(exc))
    return out_path
