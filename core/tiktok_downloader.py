"""Скачивание видео из коллекций TikTok через yt-dlp (та же библиотека, что и
для YouTube, но без youtube-специфичного извлечения video_id по регулярке —
тут используется собственный "id" из метаданных yt-dlp)."""
import os
import subprocess

from yt_dlp import YoutubeDL

from .blossom_error import Stage, fail
from .deno_util import resolve_deno
from .ffmpeg_util import resolve_ffmpeg
from .paths import TEMP_DIR, ensure_disk_space
from .proc_util import NO_WINDOW_FLAGS

TIKTOK_TEMP_DIR = os.path.join(TEMP_DIR, "tiktok_scan")


def _js_runtime_opts() -> dict:
    deno_path = resolve_deno()
    if not deno_path:
        return {}
    return {"js_runtimes": {"deno": {"path": deno_path}}}


def list_tiktok_collection_videos(url: str, limit: int = 30) -> dict:
    """Список видео коллекции/профиля TikTok без скачивания.

    Возвращает {"source_title": str, "videos": [{"id", "url", "title", "duration"}, ...]}.
    """
    target = (url or "").strip()
    if not target:
        fail(Stage.YOUTUBE_DOWNLOAD, "TIKTOK_URL_EMPTY", "Нужна ссылка на коллекцию видео TikTok")
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlistend": limit,
        **_js_runtime_opts(),
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target, download=False)
    except Exception as exc:
        fail(Stage.YOUTUBE_DOWNLOAD, "TIKTOK_COLLECTION_FETCH_FAIL", "Не удалось прочитать коллекцию TikTok", str(exc))

    if not isinstance(info, dict):
        fail(Stage.YOUTUBE_DOWNLOAD, "TIKTOK_COLLECTION_EMPTY", "Пустой ответ по ссылке коллекции TikTok")

    source_title = (info.get("title") or "").strip() or "TikTok"
    entries = info.get("entries")
    if entries is None:
        entries = [info] if info.get("id") else []

    videos = []
    for entry in entries:
        if not entry:
            continue
        video_url = entry.get("url") or entry.get("webpage_url") or ""
        if not video_url:
            continue
        videos.append({
            "id": entry.get("id") or "",
            "url": video_url,
            "title": (entry.get("title") or "").strip(),
            "duration": entry.get("duration") or 0,
        })
    return {"source_title": source_title, "videos": videos}


def download_tiktok_video_audio(url: str) -> dict:
    """Скачивает аудио одного видео TikTok (как mp3) во временную папку
    для последующего распознавания — не для сохранения в библиотеку."""
    ensure_disk_space()
    os.makedirs(TIKTOK_TEMP_DIR, exist_ok=True)
    ffmpeg_dir = os.path.dirname(resolve_ffmpeg())
    outtmpl = os.path.join(TIKTOK_TEMP_DIR, "%(id)s.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/worst",
        "outtmpl": outtmpl,
        "ffmpeg_location": ffmpeg_dir,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "128",
        }],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "noprogress": True,
        **_js_runtime_opts(),
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        fail(Stage.YOUTUBE_DOWNLOAD, "TIKTOK_DOWNLOAD_FAIL", "Не удалось скачать видео TikTok", str(exc))

    video_id = (info or {}).get("id") or ""
    final_path = os.path.join(TIKTOK_TEMP_DIR, f"{video_id}.mp3")
    if not os.path.isfile(final_path) or os.path.getsize(final_path) <= 0:
        fail(Stage.YOUTUBE_DOWNLOAD, "TIKTOK_AUDIO_MISSING", "Аудио после скачивания видео TikTok не найдено", final_path)

    return {
        "filepath": final_path,
        "duration": (info or {}).get("duration") or 0,
        "title": ((info or {}).get("title") or "").strip(),
    }


def extract_audio_clip(src_path: str, offset_seconds: float, clip_seconds: float, out_path: str) -> bool:
    """Вырезает короткий фрагмент аудио (для одного "прослушивания" Shazam'ом)."""
    try:
        ffmpeg = resolve_ffmpeg()
    except Exception:
        return False
    cmd = [
        ffmpeg, "-v", "quiet", "-y",
        "-ss", str(max(0.0, offset_seconds)),
        "-i", src_path,
        "-t", str(clip_seconds),
        "-ac", "1", "-ar", "44100",
        out_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=60, creationflags=NO_WINDOW_FLAGS)
    except Exception:
        return False
    return os.path.isfile(out_path) and os.path.getsize(out_path) > 0
