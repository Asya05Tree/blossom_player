import os
import wave

from .blossom_error import BlossomError, Stage, fail
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


def record_loopback_clip(duration_seconds: float = 8.0) -> str:
    """Записывает duration_seconds секунд звука, который сейчас играет на компьютере
    (WASAPI loopback устройства вывода по умолчанию — колонки/наушники), а не с
    микрофона. Нужен для Shazam, когда источник звука — сам компьютер (браузер и т.п.),
    а не внешний источник рядом с физическим микрофоном.
    """
    try:
        import pyaudiowpatch as pyaudio
    except Exception as exc:
        fail(
            Stage.PIPELINE,
            "LOOPBACK_BACKEND_MISSING",
            "Не удалось подключиться к звуку компьютера (нужен PyAudioWPatch, Windows-only)",
            str(exc),
        )

    p = pyaudio.PyAudio()
    frames: list[bytes] = []
    try:
        try:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
            if not default_speakers.get("isLoopbackDevice"):
                for loopback in p.get_loopback_device_info_generator():
                    if default_speakers["name"] in loopback["name"]:
                        default_speakers = loopback
                        break
                else:
                    fail(
                        Stage.PIPELINE,
                        "LOOPBACK_DEVICE_NOT_FOUND",
                        "Не нашла loopback-устройство для звука компьютера по умолчанию",
                    )
        except BlossomError:
            raise
        except Exception as exc:
            fail(Stage.PIPELINE, "LOOPBACK_DEVICE_FAIL", "Не удалось получить устройство вывода звука", str(exc))

        rate = int(default_speakers["defaultSampleRate"])
        channels = max(1, int(default_speakers["maxInputChannels"]))

        def _callback(in_data, frame_count, time_info, status):
            frames.append(in_data)
            return (in_data, pyaudio.paContinue)

        try:
            stream = p.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                frames_per_buffer=1024,
                input=True,
                input_device_index=default_speakers["index"],
                stream_callback=_callback,
            )
        except Exception as exc:
            fail(Stage.PIPELINE, "LOOPBACK_OPEN_FAIL", "Не удалось открыть поток звука компьютера", str(exc))

        import time as _time
        stream.start_stream()
        _time.sleep(duration_seconds)
        stream.stop_stream()
        stream.close()
    finally:
        p.terminate()

    if not frames:
        fail(Stage.PIPELINE, "LOOPBACK_EMPTY", "Со звуком компьютера ничего не записалось")

    os.makedirs(TEMP_DIR, exist_ok=True)
    out_path = os.path.join(TEMP_DIR, "shazam_listen_loopback.wav")
    try:
        with wave.open(out_path, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(b"".join(frames))
    except Exception as exc:
        fail(Stage.FILE_IO, "LOOPBACK_WAV_WRITE_FAIL", "Не удалось сохранить запись звука компьютера", str(exc))
    return out_path
