"""Поиск текста песни в интернете (Genius) + эвристика "это инструментал".

Genius REST API не отдаёт полный текст напрямую (ToS) — он отдаёт только
ссылку на страницу песни. Текст достаём тем же способом, что использует
открытый пакет lyricsgenius: скачиваем HTML страницы и вытаскиваем контейнеры
с атрибутом data-lyrics-container.
"""
import json
import os
import re

import requests
from bs4 import BeautifulSoup

from .paths import GENIUS_CLIENT_FILE
from .text_style import strip_decor

INSTRUMENTAL_MARK = "♬ ♬ ♬"

_INSTRUMENTAL_KEYWORDS = (
    "instrumental", "инструментал", "karaoke", "караоке",
    "minus one", "минус", "backing track", "no vocals", "без слов", "beat only",
)

GENIUS_SEARCH_URL = "https://api.genius.com/search"
_REQUEST_TIMEOUT = 10

# Без правдоподобных браузерных заголовков Cloudflare перед genius.com отдаёт
# 403 почти сразу (особенно при частых запросах во время массового поиска) —
# тогда "текста не нашли" выглядело бы так же, как "текста и не существует",
# и песня ошибочно помечалась инструментальной. Поэтому держим одну сессию
# с набором заголовков настоящего браузера на весь процесс поиска текстов.
_session = requests.Session()
_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
})

_BLOCK_MARKERS = ("just a moment", "attention required", "cf-browser-verification", "cloudflare")


class LyricsLookupError(Exception):
    """Сеть/антибот-блокировка — означает "не смогли проверить", а не
    "текста точно не существует". Вызывающий код не должен на основании этой
    ошибки помечать песню инструментальной."""


def _looks_blocked(resp: requests.Response) -> bool:
    if resp.status_code in (403, 429, 503):
        return True
    low = resp.text[:2000].lower()
    return any(marker in low for marker in _BLOCK_MARKERS)


def looks_instrumental(*texts: str) -> bool:
    for text in texts:
        low = (text or "").lower()
        if any(keyword in low for keyword in _INSTRUMENTAL_KEYWORDS):
            return True
    return False


def _load_genius_token() -> str:
    if not os.path.isfile(GENIUS_CLIENT_FILE):
        return ""
    try:
        with open(GENIUS_CLIENT_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return ""
    return (data.get("access_token") or "").strip()


def _normalize(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def _genius_search_hits(query: str, token: str) -> list:
    resp = _session.get(
        GENIUS_SEARCH_URL,
        params={"q": query},
        headers={"Authorization": f"Bearer {token}"},
        timeout=_REQUEST_TIMEOUT,
    )
    if _looks_blocked(resp):
        raise LyricsLookupError(f"Genius API заблокировал запрос (код {resp.status_code})")
    resp.raise_for_status()
    data = resp.json()
    return (data.get("response") or {}).get("hits") or []


def _pick_best_hit(hits: list, title: str, artist: str) -> dict:
    """Возвращает лучший результат, только если совпадение уверенное.
    Если по названию/автору нельзя понять, какой из результатов нужен —
    возвращает None (вызывающий код попробует уточнить трек через Shazam)."""
    target_title = _normalize(title)
    target_artist = _normalize(artist)
    unknown_artist = target_artist in ("", "unknownartist", "unknown")
    best = None
    best_score = 0
    for hit in hits:
        result = hit.get("result") or {}
        hit_title = _normalize(result.get("title") or "")
        hit_artist = _normalize((result.get("primary_artist") or {}).get("name") or "")
        if not target_title or not hit_title:
            continue
        title_exact = target_title == hit_title
        title_overlap = target_title in hit_title or hit_title in target_title
        if not (title_exact or title_overlap):
            # Название вообще не совпадает — совпавший автор одного этого не
            # компенсирует (иначе подставится случайная песня того же артиста).
            continue
        score = 3 if title_exact else 2
        if not unknown_artist:
            if target_artist == hit_artist:
                score += 2
            elif target_artist in hit_artist or hit_artist in target_artist:
                score += 1
            else:
                score -= 1
        if score > best_score:
            best_score = score
            best = result
    return best if best_score >= 2 else None


def _scrape_lyrics_page(url: str) -> str:
    resp = _session.get(url, timeout=_REQUEST_TIMEOUT)
    if _looks_blocked(resp):
        raise LyricsLookupError(f"Genius заблокировал открытие страницы текста (код {resp.status_code})")
    resp.raise_for_status()
    # resp.content (байты), а не resp.text — requests угадывает кодировку по
    # заголовкам и часто промахивается на кириллице, что давало "кракозябры"
    # вместо текста; BeautifulSoup сам правильно определит кодировку по meta.
    soup = BeautifulSoup(resp.content, "html.parser")
    containers = soup.find_all(attrs={"data-lyrics-container": "true"})
    if not containers:
        return ""
    chunks = []
    for container in containers:
        # Genius вкладывает внутрь самого контейнера текста заголовок вида
        # "N ContributorsНазвание Lyrics" (кнопка со счётчиком соавторов) —
        # он помечен data-exclude-from-selection="true" (сам Genius исключает
        # его из выделения/копирования текста), и мы делаем то же самое.
        for excluded in container.select('[data-exclude-from-selection="true"]'):
            excluded.decompose()
        for br in container.find_all("br"):
            br.replace_with("\n")
        chunks.append(container.get_text())
    text = "\n".join(chunks)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def search_lyrics_genius(title: str, artist: str) -> str:
    """Возвращает текст песни с Genius или '' если не найдено / нет уверенного совпадения.
    Поднимает LyricsLookupError при сетевой блокировке (не значит "текста нет")."""
    clean_title = strip_decor(title or "").strip()
    clean_artist = strip_decor(artist or "").strip()
    if not clean_title:
        return ""
    token = _load_genius_token()
    if not token:
        return ""
    unknown_artist = clean_artist.lower() in ("", "unknown artist", "unknown")
    query = clean_title if unknown_artist else f"{clean_artist} {clean_title}"
    hits = _genius_search_hits(query, token)
    if not hits:
        return ""
    best = _pick_best_hit(hits, clean_title, clean_artist)
    if not best or not best.get("url"):
        return ""
    return _scrape_lyrics_page(best["url"])


def resolve_lyrics_for_song(title: str, artist: str, filepath: str = "", use_shazam_fallback: bool = True) -> dict:
    """Определяет статус песни и находит текст.

    Порядок: 1) понять, не инструментал ли это уже по названию;
    2) искать текст по названию+автору; 3) если не нашли и есть локальный файл —
    уточнить трек через Shazam и повторить поиск по уточнённым данным;
    4) если текста так и не нашли — считаем песню инструментальной.

    Если поиск упёрся в сетевую блокировку (Genius отбил запрос) — возвращает
    status "error", а НЕ "instrumental": блокировка не доказывает отсутствие
    текста, и песню нельзя клеймить инструментальной на основании сбоя сети.

    Возвращает {"status": "found"|"instrumental"|"error", "lyrics": str|None,
    "identified_title"?: str, "identified_artist"?: str, "error"?: str}.
    """
    clean_title = strip_decor(title or "")
    clean_artist = strip_decor(artist or "")

    if looks_instrumental(clean_title, clean_artist):
        return {"status": "instrumental", "lyrics": INSTRUMENTAL_MARK}

    try:
        lyrics = search_lyrics_genius(clean_title, clean_artist)
    except LyricsLookupError as exc:
        return {"status": "error", "lyrics": None, "error": str(exc)}
    if lyrics:
        return {"status": "found", "lyrics": lyrics}

    if use_shazam_fallback and filepath and os.path.isfile(filepath):
        try:
            from .shazam_util import identify_from_file
            identified = identify_from_file(filepath)
        except Exception:
            identified = {}
        ident_title = (identified.get("title") or "").strip()
        ident_artist = (identified.get("artist") or "").strip()
        if ident_title:
            if looks_instrumental(ident_title, ident_artist):
                return {"status": "instrumental", "lyrics": INSTRUMENTAL_MARK}
            try:
                lyrics = search_lyrics_genius(ident_title, ident_artist)
            except LyricsLookupError as exc:
                return {"status": "error", "lyrics": None, "error": str(exc)}
            if lyrics:
                return {
                    "status": "found",
                    "lyrics": lyrics,
                    "identified_title": ident_title,
                    "identified_artist": ident_artist,
                }

    return {"status": "instrumental", "lyrics": INSTRUMENTAL_MARK}
