"""Распознавание трека по звуку через shazamio (использует реальный Shazam).

shazamio 0.8.1 на PyPI жёстко требует shazamio-core==1.1.2, у которого нет
прекомпилированного колеса под эту версию Python — поэтому здесь установлен
shazamio-core 2.0.0 (колесо есть) через pip с игнорированием версийного пина;
API, которым пользуется shazamio (Recognizer/Signature/SearchParams), совпадает
в обеих версиях, так что реальное распознавание работает (проверено).
"""
import asyncio
import os

from .blossom_error import Stage, fail
from .ffmpeg_util import resolve_ffmpeg


def _ensure_ffmpeg_on_path() -> None:
    try:
        ffmpeg_dir = os.path.dirname(resolve_ffmpeg())
    except Exception:
        return
    if ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")


def identify_from_file(filepath: str) -> dict:
    """Возвращает {"title", "artist", "cover_url"} или {} если не распознано."""
    if not filepath or not os.path.isfile(filepath):
        fail(Stage.FILE_IO, "SHAZAM_FILE_MISSING", "Файл для распознавания не найден", filepath or "")
    _ensure_ffmpeg_on_path()
    from shazamio import Shazam

    async def _run():
        shazam = Shazam()
        return await shazam.recognize(filepath)

    try:
        data = asyncio.run(_run())
    except Exception as exc:
        fail(Stage.PIPELINE, "SHAZAM_RUN_FAIL", "Не удалось обратиться к Shazam", str(exc))

    track = (data or {}).get("track")
    if not track:
        return {}
    images = track.get("images") or {}
    return {
        "title": (track.get("title") or "").strip(),
        "artist": (track.get("subtitle") or "").strip(),
        "cover_url": images.get("coverart") or images.get("coverarthq") or "",
    }
