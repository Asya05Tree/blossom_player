import json
import os
import re
from typing import Any

from .blossom_error import BlossomError, Stage, fail
from .paths import CONFIG_DIR, SPOTIFY_CACHE_FILE, SPOTIFY_CLIENT_FILE

SPOTIFY_SCOPES = "user-library-read playlist-read-private playlist-read-collaborative user-read-email"
TRACK_ID_RE = re.compile(
    r"(?:https?://open\.spotify\.com/(?:intl-[a-z]{2}/)?track/|spotify:track:)([A-Za-z0-9]{22})",
    re.IGNORECASE,
)


def _require_path(path: str, code: str, label: str) -> None:
    if not path or not os.path.isfile(path):
        fail(Stage.CONFIG, code, label, path or "путь пустой")


def _read_json(path: str) -> dict:
    _require_path(path, "JSON_FILE_MISSING", f"Файл конфигурации не найден: {path}")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        fail(Stage.CONFIG, "JSON_INVALID", f"Невалидный JSON: {path}", str(exc))
    if not isinstance(data, dict):
        fail(Stage.CONFIG, "JSON_NOT_OBJECT", f"Ожидался объект JSON: {path}")
    return data


def load_client_config() -> dict:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    data = _read_json(SPOTIFY_CLIENT_FILE)
    client_id = (data.get("client_id") or "").strip()
    client_secret = (data.get("client_secret") or "").strip()
    redirect_uri = (data.get("redirect_uri") or "http://127.0.0.1:8888/callback").strip()
    if not client_id:
        fail(Stage.CONFIG, "SPOTIFY_CLIENT_ID_MISSING", "В spotify_client.json нет client_id")
    if not client_secret:
        fail(Stage.CONFIG, "SPOTIFY_CLIENT_SECRET_MISSING", "В spotify_client.json нет client_secret")
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }


def extract_track_id(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        fail(Stage.SPOTIFY_RESOLVE, "URL_EMPTY", "Пустая Spotify-ссылка")
    matches = TRACK_ID_RE.findall(text)
    if not matches:
        fail(
            Stage.SPOTIFY_RESOLVE,
            "URL_NOT_TRACK",
            "Не найден ID трека. Вставь одну ссылку: https://open.spotify.com/track/...",
            text[:200],
        )
    return matches[-1]


def normalize_track_url(url: str) -> str:
    track_id = extract_track_id(url)
    return f"https://open.spotify.com/track/{track_id}"


def _duration_to_ms(value: int) -> int:
    if value <= 0:
        return 0
    if value > 10000:
        return value
    return value * 1000


def _is_spotify_api_blocked(detail: str) -> bool:
    lowered = (detail or "").lower()
    return "403" in lowered or "premium" in lowered or "active premium" in lowered


# Приложение spotdl (extended quota): не подпадает под требование Spotify
# об активном Premium у владельца приложения для Web API в dev-режиме.
SPOTDL_APP_CLIENT_ID = "5f573c9620494bae87890c0f08a60293"
SPOTDL_APP_CLIENT_SECRET = "212476d9b0f3472eaa762d90b19b0ba8"
SPOTDL_APP_REDIRECT_URI = "http://127.0.0.1:9900/"
SPOTIFY_FALLBACK_CACHE_FILE = SPOTIFY_CACHE_FILE + "_spotdl"


def _require_free_redirect_port(redirect_uri: str) -> None:
    """Проверяет, что порт redirect-сервера OAuth свободен, иначе вход зависнет."""
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
    except OSError:
        fail(
            Stage.SPOTIFY_AUTH,
            "SPOTIFY_REDIRECT_PORT_BUSY",
            f"Порт {port} занят (возможно, предыдущий вход в Spotify ещё ждёт). "
            "Закрой старое окно входа или перезапусти приложение.",
            redirect_uri,
        )


def _build_oauth_client(client_id: str, client_secret: str, redirect_uri: str, cache_path: str):
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth

    auth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=SPOTIFY_SCOPES,
        cache_path=cache_path,
        open_browser=True,
    )
    token = auth.get_cached_token()
    if not token:
        _require_free_redirect_port(redirect_uri)
        token = auth.get_access_token(as_dict=False)
    if not token:
        fail(Stage.SPOTIFY_AUTH, "SPOTIFY_TOKEN_EMPTY", "Spotify не выдал access token")
    return spotipy.Spotify(auth_manager=auth)


def create_spotify_client(progress=None):
    """Клиент Spotify с доступом к библиотеке пользователя.

    Сначала пробует приложение из config/spotify_client.json. Если Spotify
    блокирует его Web API (нужен Premium у владельца приложения) — повторяет
    вход через приложение spotdl, на которое это ограничение не действует.
    """

    def _notify(msg: str) -> None:
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    blocked_detail = ""
    try:
        cfg = load_client_config()
    except BlossomError:
        cfg = None
    if cfg:
        try:
            client = _build_oauth_client(
                cfg["client_id"], cfg["client_secret"], cfg["redirect_uri"], SPOTIFY_CACHE_FILE,
            )
            client.me()  # проба: dev-приложения без Premium у владельца получают 403
            return client
        except BlossomError:
            raise
        except Exception as exc:
            blocked_detail = str(exc)
            if not _is_spotify_api_blocked(blocked_detail):
                fail(Stage.SPOTIFY_AUTH, "SPOTIFY_AUTH_FAILED", "Ошибка авторизации Spotify", blocked_detail)

    _notify("Web API твоего приложения Spotify заблокирован — вход через приложение spotdl…")
    try:
        client = _build_oauth_client(
            SPOTDL_APP_CLIENT_ID,
            SPOTDL_APP_CLIENT_SECRET,
            SPOTDL_APP_REDIRECT_URI,
            SPOTIFY_FALLBACK_CACHE_FILE,
        )
        client.me()
        return client
    except BlossomError:
        raise
    except Exception as exc:
        fail(
            Stage.SPOTIFY_AUTH,
            "SPOTIFY_AUTH_FAILED",
            "Ошибка авторизации Spotify (и через резервное приложение spotdl)",
            f"{blocked_detail} | fallback: {exc}" if blocked_detail else str(exc),
        )


def _playlist_track_entry(track: Any) -> dict[str, Any] | None:
    """Превращает трек из ответа Spotify API в компактную запись (или None)."""
    if not isinstance(track, dict) or track.get("is_local"):
        return None
    track_id = (track.get("id") or "").strip()
    if not track_id:
        return None
    artists = ", ".join(
        a.get("name", "").strip() for a in (track.get("artists") or []) if a.get("name")
    )
    return {
        "id": track_id,
        "url": f"https://open.spotify.com/track/{track_id}",
        "title": (track.get("name") or "").strip() or "Unknown",
        "artist": artists or "Unknown Artist",
    }


def _iterate_pages(client, first_page):
    page = first_page
    while page:
        for item in page.get("items") or []:
            yield item
        page = client.next(page) if page.get("next") else None


def fetch_user_library(client, progress=None) -> list[dict[str, Any]]:
    """Скачивает список всех плейлистов пользователя (включая Liked Songs) с треками."""

    def _notify(msg: str) -> None:
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    playlists: list[dict[str, Any]] = []

    # Любимые треки (Liked Songs)
    _notify("Читаю «Любимые треки»…")
    liked: list[dict[str, Any]] = []
    try:
        first = client.current_user_saved_tracks(limit=50)
    except Exception as exc:
        fail(Stage.SPOTIFY_RESOLVE, "SPOTIFY_LIKED_FAIL", "Не удалось прочитать любимые треки Spotify", str(exc))
    for item in _iterate_pages(client, first):
        entry = _playlist_track_entry((item or {}).get("track"))
        if entry:
            liked.append(entry)
    if liked:
        playlists.append({"name": "Любимые из Spotify", "tracks": liked})

    # Плейлисты пользователя
    _notify("Читаю список плейлистов…")
    try:
        first = client.current_user_playlists(limit=50)
    except Exception as exc:
        fail(Stage.SPOTIFY_RESOLVE, "SPOTIFY_PLAYLISTS_FAIL", "Не удалось прочитать плейлисты Spotify", str(exc))
    summaries = [
        {"id": p.get("id"), "name": (p.get("name") or "").strip() or "Без названия"}
        for p in _iterate_pages(client, first)
        if p and p.get("id")
    ]

    for index, summary in enumerate(summaries, start=1):
        _notify(f"Плейлист {index}/{len(summaries)}: {summary['name']}…")
        tracks: list[dict[str, Any]] = []
        try:
            first = client.playlist_items(summary["id"], limit=100, additional_types=("track",))
        except Exception:
            continue
        for item in _iterate_pages(client, first):
            entry = _playlist_track_entry((item or {}).get("track"))
            if entry:
                tracks.append(entry)
        playlists.append({"name": summary["name"], "tracks": tracks})

    return playlists


def fetch_track_metadata_spotdl(track_url: str) -> dict[str, Any]:
    from .log_util import log
    from .spotdl_client import search_track

    normalized = normalize_track_url(track_url)
    log("meta", "spotdl: поиск метаданных…")
    track_id = extract_track_id(normalized)
    try:
        song = search_track(normalized)
    except BlossomError:
        raise
    except Exception as exc:
        fail(Stage.SPOTIFY_RESOLVE, "SPOTDL_META_FAIL", "spotdl не смог прочитать трек", str(exc))
    title = (getattr(song, "name", None) or "").strip()
    artist = (getattr(song, "artist", None) or "").strip()
    if not title:
        fail(Stage.SPOTIFY_RESOLVE, "SPOTDL_TITLE_EMPTY", "spotdl вернул трек без названия", track_id)
    if not artist:
        artists = getattr(song, "artists", None) or []
        artist = ", ".join(artists) if artists else "Unknown Artist"
    return {
        "track_id": (getattr(song, "song_id", None) or track_id),
        "url": (getattr(song, "url", None) or normalized),
        "title": title,
        "artist": artist,
        "album": (getattr(song, "album_name", None) or "").strip(),
        "cover_url": (getattr(song, "cover_url", None) or "") or "",
        "duration_ms": _duration_to_ms(int(getattr(song, "duration", 0) or 0)),
        "source": "spotdl",
    }


def fetch_track_metadata_api(client, track_url: str) -> dict[str, Any]:
    normalized = normalize_track_url(track_url)
    track_id = extract_track_id(normalized)
    try:
        track = client.track(track_id)
    except Exception as exc:
        detail = str(exc)
        if _is_spotify_api_blocked(detail):
            fail(
                Stage.SPOTIFY_RESOLVE,
                "SPOTIFY_PREMIUM_REQUIRED",
                "Spotify Web API недоступен для этого приложения (нужен Premium у владельца приложения). Используется spotdl.",
                detail,
            )
        fail(Stage.SPOTIFY_RESOLVE, "TRACK_FETCH_FAILED", "Spotify API не вернул трек", detail)
    if not track:
        fail(Stage.SPOTIFY_RESOLVE, "TRACK_EMPTY", "Пустой ответ Spotify API", track_id)
    name = (track.get("name") or "").strip()
    if not name:
        fail(Stage.SPOTIFY_RESOLVE, "TRACK_NAME_EMPTY", "У трека нет названия", track_id)
    artists = track.get("artists") or []
    artist_names = [a.get("name", "").strip() for a in artists if a.get("name")]
    if not artist_names:
        fail(Stage.SPOTIFY_RESOLVE, "TRACK_ARTIST_NAMES_EMPTY", "Не удалось прочитать артистов", track_id)
    album = track.get("album") or {}
    images = album.get("images") or []
    cover_url = images[0].get("url") if images else ""
    duration_ms = int(track.get("duration_ms") or 0)
    return {
        "track_id": track_id,
        "url": normalized,
        "title": name,
        "artist": ", ".join(artist_names),
        "album": (album.get("name") or "").strip(),
        "cover_url": cover_url or "",
        "duration_ms": duration_ms,
        "source": "spotify_api",
    }


def resolve_track_metadata(track_url: str) -> dict[str, Any]:
    from .log_util import log

    log("meta", f"ссылка: {normalize_track_url(track_url)}")
    try:
        return fetch_track_metadata_spotdl(track_url)
    except BlossomError as spotdl_error:
        if spotdl_error.code not in ("SPOTDL_META_FAIL", "SPOTDL_META_EMPTY"):
            raise
    try:
        client = create_spotify_client()
        return fetch_track_metadata_api(client, track_url)
    except BlossomError as api_error:
        if api_error.code == "SPOTIFY_PREMIUM_REQUIRED":
            fail(
                Stage.SPOTIFY_RESOLVE,
                "SPOTIFY_META_UNAVAILABLE",
                "Не удалось получить трек ни через spotdl, ни через Spotify API. Проверь ссылку и client_id/secret.",
                api_error.detail,
            )
        raise


def fetch_track_metadata(client, track_url: str) -> dict[str, Any]:
    return fetch_track_metadata_api(client, track_url)
