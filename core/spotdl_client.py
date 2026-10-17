import os
from typing import Any, Optional

from .blossom_error import Stage, fail
from .paths import DOWNLOADS_DIR, TEMP_DIR
from .spotify_service import load_client_config, normalize_track_url
from .ffmpeg_util import resolve_ffmpeg

_spotdl_instance: Any = None
_song_cache: dict[str, Any] = {}


def _ensure_dir(path: str, code: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        fail(Stage.FILE_IO, code, "Не удалось создать папку", str(exc))


def get_spotdl_client():
    global _spotdl_instance
    if _spotdl_instance is not None:
        return _spotdl_instance
    try:
        from spotdl import Spotdl
    except ImportError as exc:
        fail(Stage.SPOTIFY_DOWNLOAD, "SPOTDL_IMPORT_FAIL", "Пакет spotdl не установлен", str(exc))

    cfg = load_client_config()
    ffmpeg_path = resolve_ffmpeg()
    _ensure_dir(DOWNLOADS_DIR, "DOWNLOAD_DIR_CREATE_FAIL")
    _ensure_dir(TEMP_DIR, "TEMP_DIR_CREATE_FAIL")
    output_template = os.path.join(DOWNLOADS_DIR, "{artist} - {title}.{output-ext}")
    _spotdl_instance = Spotdl(
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        user_auth=False,
        cache_path=TEMP_DIR,
        downloader_settings={
            "output": output_template,
            "format": "mp3",
            "ffmpeg": ffmpeg_path,
            "print_errors": True,
            "log_level": "INFO",
            # spotdl по умолчанию качает через yt-dlp с форматом "bestaudio/best" —
            # "/best" может утащить тяжёлый комбинированный видео+аудио поток, если
            # для трека на YouTube не нашлось чистого audio-only. Меняем фоллбэк на
            # "worst" (минимально возможное по весу видео, если без него никак) —
            # то же решение, что для прямых YouTube-ссылок в youtube_downloader.py.
            # "--retries 2" — у yt-dlp внутри spotdl дефолт 5 попыток на трек;
            # при массовом импорте (SpotifyLibraryWorker) "Остановить" проверяется
            # только МЕЖДУ треками, так что чем дольше yt-dlp бьётся за один
            # сбойный трек, тем дольше кажется, что остановка не работает.
            "yt_dlp_args": "-f bestaudio/worst --retries 2",
            # spotdl по умолчанию САМ ищет текст на genius/azlyrics/musixmatch и
            # сам скачивает обложку для каждого трека — лишние сетевые запросы
            # (у нас уже есть свой поиск текста в core/lyrics_service.py и своя
            # загрузка обложки в core/covers.py) и лишний источник ошибок:
            # сбой любого из трёх lyrics-провайдеров внутри spotdl мог завалить
            # весь download() трека, даже если аудио скачалось нормально.
            "lyrics_providers": [],
            "skip_album_art": True,
        },
    )
    return _spotdl_instance


def search_track(track_url: str) -> Any:
    normalized = normalize_track_url(track_url)
    if normalized in _song_cache:
        return _song_cache[normalized]
    client = get_spotdl_client()
    songs = client.search([normalized])
    if not songs:
        fail(Stage.SPOTIFY_RESOLVE, "SPOTDL_META_EMPTY", "spotdl не нашёл трек", normalized)
    _song_cache[normalized] = songs[0]
    return songs[0]


def download_track(track_url: str) -> tuple[Any, Any]:
    normalized = normalize_track_url(track_url)
    song = _song_cache.get(normalized) or search_track(track_url)
    client = get_spotdl_client()
    client.downloader.errors.clear()
    song_obj, downloaded = client.download(song)
    if downloaded is None:
        # downloaded=None из spotdl — это ВСЕГДА провал скачивания (см.
        # Downloader.download_multiple_songs), не редкий формат успешного ответа.
        # Раньше это трактовалось как "скачалось, просто путь не вернулся" и код
        # хватал САМЫЙ СВЕЖИЙ файл из папки загрузок наугад — на деле это мог
        # оказаться файл СОВСЕМ ДРУГОГО трека (прошлый успешный download), который
        # потом сохранялся в библиотеку под метаданными упавшего трека.
        last_error = client.downloader.errors[-1] if client.downloader.errors else "неизвестная ошибка"
        fail(Stage.SPOTIFY_DOWNLOAD, "SPOTDL_DOWNLOAD_FAIL", "spotdl не смог скачать трек", last_error)
    return song_obj, downloaded


def create_spotdl_client():
    return get_spotdl_client()
