"""Синхронизированный (построчно, с таймкодами) текст песни — для караоке-
подсветки во время воспроизведения. Genius (core/lyrics_service.py) таймкодов
не отдаёт — это чистый текст. lrclib.net — открытая база построчно
синхронизированных текстов (формат .lrc), бесплатный API без ключа.
"""
import requests

from .text_style import strip_decor

LRCLIB_GET_URL = "https://lrclib.net/api/get"
LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"
_REQUEST_TIMEOUT = 10

_session = requests.Session()
_session.headers.update({
    "User-Agent": "BlossomPlayer/1.0 (desktop music player; synced lyrics lookup)",
    "Accept": "application/json",
})


def fetch_synced_lyrics(title: str, artist: str, duration_seconds: float = 0) -> str:
    """Возвращает LRC-текст (строки вида "[mm:ss.xx]текст") или '' если не нашли."""
    clean_title = strip_decor(title or "").strip()
    clean_artist = strip_decor(artist or "").strip()
    if not clean_title:
        return ""

    # Точный запрос по длительности — надёжнее совпадает именно с нужной записью
    if duration_seconds:
        try:
            resp = _session.get(
                LRCLIB_GET_URL,
                params={
                    "track_name": clean_title,
                    "artist_name": clean_artist,
                    "duration": int(round(duration_seconds)),
                },
                timeout=_REQUEST_TIMEOUT,
            )
            if resp.status_code == 200:
                synced = (resp.json().get("syncedLyrics") or "").strip()
                if synced:
                    return synced
        except Exception:
            pass

    # Фоллбэк — нечёткий поиск без длительности (может не совпасть с нужной версией записи)
    try:
        resp = _session.get(
            LRCLIB_SEARCH_URL,
            params={"track_name": clean_title, "artist_name": clean_artist},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        hits = resp.json() or []
    except Exception:
        return ""
    for hit in hits:
        synced = (hit.get("syncedLyrics") or "").strip()
        if synced:
            return synced
    return ""
