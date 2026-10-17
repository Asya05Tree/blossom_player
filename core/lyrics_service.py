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
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BlossomPlayer/1.0"


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
    resp = requests.get(
        GENIUS_SEARCH_URL,
        params={"q": query},
        headers={"Authorization": f"Bearer {token}", "User-Agent": _USER_AGENT},
        timeout=_REQUEST_TIMEOUT,
    )
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
    resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_REQUEST_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    containers = soup.find_all(attrs={"data-lyrics-container": "true"})
    if not containers:
        return ""
    chunks = []
    for container in containers:
        for br in container.find_all("br"):
            br.replace_with("\n")
        chunks.append(container.get_text())
    text = "\n".join(chunks)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def search_lyrics_genius(title: str, artist: str) -> str:
    """Возвращает текст песни с Genius или '' если не найдено / нет уверенного совпадения."""
    clean_title = strip_decor(title or "").strip()
    clean_artist = strip_decor(artist or "").strip()
    if not clean_title:
        return ""
    token = _load_genius_token()
    if not token:
        return ""
    unknown_artist = clean_artist.lower() in ("", "unknown artist", "unknown")
    query = clean_title if unknown_artist else f"{clean_artist} {clean_title}"
    try:
        hits = _genius_search_hits(query, token)
    except Exception:
        return ""
    if not hits:
        return ""
    best = _pick_best_hit(hits, clean_title, clean_artist)
    if not best or not best.get("url"):
        return ""
    try:
        return _scrape_lyrics_page(best["url"])
    except Exception:
        return ""


def resolve_lyrics_for_song(title: str, artist: str, filepath: str = "") -> dict:
    """Определяет статус песни и находит текст.

    Порядок: 1) понять, не инструментал ли это уже по названию;
    2) искать текст по названию+автору; 3) если не нашли и есть локальный файл —
    уточнить трек через Shazam и повторить поиск по уточнённым данным;
    4) если текста так и не нашли — считаем песню инструментальной.

    Возвращает {"status": "found"|"instrumental", "lyrics": str,
    "identified_title"?: str, "identified_artist"?: str}.
    """
    clean_title = strip_decor(title or "")
    clean_artist = strip_decor(artist or "")

    if looks_instrumental(clean_title, clean_artist):
        return {"status": "instrumental", "lyrics": INSTRUMENTAL_MARK}

    lyrics = search_lyrics_genius(clean_title, clean_artist)
    if lyrics:
        return {"status": "found", "lyrics": lyrics}

    if filepath and os.path.isfile(filepath):
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
            lyrics = search_lyrics_genius(ident_title, ident_artist)
            if lyrics:
                return {
                    "status": "found",
                    "lyrics": lyrics,
                    "identified_title": ident_title,
                    "identified_artist": ident_artist,
                }

    return {"status": "instrumental", "lyrics": INSTRUMENTAL_MARK}
