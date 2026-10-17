import os
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3NoHeaderError
from yt_dlp import YoutubeDL

from .blossom_error import Stage, fail
from .deno_util import resolve_deno
from .ffmpeg_util import resolve_ffmpeg
from .paths import DOWNLOADS_DIR, TEMP_DIR, ensure_disk_space

VIDEO_ID_RE = re.compile(
    r'(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})'
)

# Клиент "android" меньше подвержен антибот-проверке YouTube ("Sign in to confirm
# you're not a bot"), в отличие от дефолтного веб-клиента yt-dlp.
_RESILIENT_EXTRACTOR_ARGS = {"youtube": {"player_client": ["android", "web"]}}


def _js_runtime_opts() -> dict:
    """yt-dlp теперь решает JS-испытания YouTube через Deno — без него львиная
    доля треков падает с AudioProviderError. См. core/deno_util.py."""
    deno_path = resolve_deno()
    if not deno_path:
        return {}
    return {"js_runtimes": {"deno": {"path": deno_path}}}


def extract_video_id(url: str) -> str:
    match = VIDEO_ID_RE.search((url or "").strip())
    if not match:
        fail(Stage.YOUTUBE_DOWNLOAD, "YOUTUBE_URL_INVALID", "Не похоже на ссылку YouTube", url or "")
    return match.group(1)


def download_youtube_audio(url: str) -> dict[str, Any]:
    """Скачивает аудио видео YouTube как mp3 и прописывает базовые ID3-теги.

    Возвращает title/artist, взятые из метаданных видео (uploader как fallback-автор) —
    их можно переопределить в UI перед сохранением в библиотеку.
    """
    video_id = extract_video_id(url)
    ensure_disk_space()
    try:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        os.makedirs(TEMP_DIR, exist_ok=True)
    except OSError as exc:
        fail(Stage.FILE_IO, "DOWNLOAD_DIR_CREATE_FAIL", "Не удалось создать папку загрузок", str(exc))

    outtmpl = os.path.join(DOWNLOADS_DIR, f"yt_{video_id}.%(ext)s")
    ffmpeg_dir = os.path.dirname(resolve_ffmpeg())
    ydl_opts = {
        # "bestaudio" — чистый аудио-поток, если он есть. Антибот-обход через
        # player_client: android иногда вообще не отдаёт отдельный аудио-поток —
        # тогда остаётся только комбинированный видео+аудио. В этом случае раньше
        # стоял "/best" — самый ТЯЖЁЛЫЙ (вплоть до 1080p) комбинированный поток,
        # хотя видео всё равно потом выбрасывается ffmpeg'ом. "/worst" — тот же
        # фоллбэк, но самый лёгкий по видео комбинированный поток, какой есть —
        # меньше лишнего трафика и быстрее скачивание.
        "format": "bestaudio/worst",
        "outtmpl": outtmpl,
        "ffmpeg_location": ffmpeg_dir,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "noprogress": True,
        "extractor_args": _RESILIENT_EXTRACTOR_ARGS,
        **_js_runtime_opts(),
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
    except Exception as exc:
        fail(Stage.YOUTUBE_DOWNLOAD, "YOUTUBE_DOWNLOAD_FAIL", "yt-dlp не смог скачать видео", str(exc))

    final_path = os.path.join(DOWNLOADS_DIR, f"yt_{video_id}.mp3")
    if not os.path.isfile(final_path) or os.path.getsize(final_path) <= 0:
        fail(Stage.YOUTUBE_DOWNLOAD, "YOUTUBE_AUDIO_MISSING", "Аудиофайл после скачивания не найден", final_path)

    raw_title = (info.get("track") or info.get("title") or "Unknown Title").strip()
    raw_artist = (info.get("artist") or info.get("uploader") or "Unknown Artist").strip()
    thumbnail_url = info.get("thumbnail") or ""
    duration = info.get("duration") or 0

    try:
        tags = EasyID3(final_path)
    except ID3NoHeaderError:
        tags = EasyID3()
        tags.save(final_path)
        tags = EasyID3(final_path)
    tags["title"] = raw_title
    tags["artist"] = raw_artist
    tags.save(final_path)

    return {
        "title": raw_title,
        "artist": raw_artist,
        "filepath": final_path,
        "video_id": video_id,
        "thumbnail_url": thumbnail_url,
        "duration": duration,
    }


def search_youtube_results(query: str, limit: int = 8) -> list[dict[str, Any]]:
    """Возвращает до limit результатов поиска YouTube по текстовому запросу
    (без скачивания) — для UI, где пользователь сам выбирает нужное видео."""
    clean_query = (query or "").strip()
    if not clean_query:
        fail(Stage.YOUTUBE_DOWNLOAD, "YOUTUBE_SEARCH_QUERY_EMPTY", "Пустой поисковый запрос")
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "noplaylist": True,
        "extractor_args": _RESILIENT_EXTRACTOR_ARGS,
        **_js_runtime_opts(),
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch{max(1, limit)}:{clean_query}", download=False)
    except Exception as exc:
        fail(Stage.YOUTUBE_DOWNLOAD, "YOUTUBE_SEARCH_FAIL", "Не удалось выполнить поиск на YouTube", str(exc))

    entries = (info or {}).get("entries") or ([info] if info and info.get("id") else [])
    out = []
    for entry in entries[:limit]:
        video_id = entry.get("id") or ""
        if not video_id:
            continue
        out.append({
            "id": video_id,
            "title": (entry.get("title") or "").strip(),
            "url": entry.get("url") or f"https://www.youtube.com/watch?v={video_id}",
            "duration": entry.get("duration") or 0,
            "channel": (entry.get("channel") or entry.get("uploader") or "").strip(),
        })
    return out


def search_youtube_top_result(query: str) -> dict[str, Any]:
    """Возвращает лучший результат поиска YouTube по текстовому запросу (без скачивания)."""
    results = search_youtube_results(query, limit=1)
    if not results:
        fail(Stage.YOUTUBE_DOWNLOAD, "YOUTUBE_SEARCH_EMPTY", "Поиск не дал результатов", (query or "").strip())
    return results[0]


def list_channel_or_playlist_videos(url: str, limit: int = 50) -> dict[str, Any]:
    """Список видео канала/плейлиста без скачивания (для массовой закачки).

    Возвращает {"source_title": str, "videos": [{"id", "url", "title"}, ...]}.
    Для простой ссылки на канал (без вкладки) подставляет "/videos".
    """
    target = (url or "").strip()
    if not target:
        fail(Stage.YOUTUBE_DOWNLOAD, "YOUTUBE_CHANNEL_URL_EMPTY", "Нужна ссылка на канал или плейлист")
    # Ссылки часто приходят с трекинговыми параметрами (?si=...&drli=1, в т.ч. с
    # music.youtube.com) — раньше "/videos" дописывался ПОСЛЕ query-строки и ломал
    # URL (…?si=xxx/videos). Разбираем URL и дописываем /videos только к пути,
    # отбрасывая query/fragment — они не нужны для получения списка видео.
    parts = urlsplit(target)
    path = parts.path
    has_playlist_param = "list=" in parts.query
    if not has_playlist_param and "/videos" not in path and "/playlists" not in path:
        path = path.rstrip("/") + "/videos"
    target = urlunsplit((parts.scheme, parts.netloc, path, parts.query if has_playlist_param else "", ""))

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlistend": limit,
        "extractor_args": _RESILIENT_EXTRACTOR_ARGS,
        **_js_runtime_opts(),
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target, download=False)
    except Exception as exc:
        fail(Stage.YOUTUBE_DOWNLOAD, "YOUTUBE_CHANNEL_FETCH_FAIL", "Не удалось прочитать список видео", str(exc))

    if not isinstance(info, dict):
        fail(Stage.YOUTUBE_DOWNLOAD, "YOUTUBE_CHANNEL_EMPTY", "Пустой ответ по ссылке канала/плейлиста")

    source_title = (info.get("title") or "").strip() or "YouTube"
    videos = []
    for entry in info.get("entries") or []:
        if not entry:
            continue
        video_id = entry.get("id") or ""
        if not video_id:
            continue
        videos.append({
            "id": video_id,
            "url": entry.get("url") or f"https://www.youtube.com/watch?v={video_id}",
            "title": (entry.get("title") or "").strip(),
        })
    return {"source_title": source_title, "videos": videos}
