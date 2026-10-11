"""Доступ к библиотеке Spotify через веб-сессию (cookie sp_dc).

Официальный Web API в dev-режиме требует Premium у владельца приложения,
а общее приложение spotdl упирается в суточный rate-limit. Поэтому список
плейлистов и треков читается так же, как это делает веб-плеер Spotify
(библиотека spotapi), от имени вошедшего пользователя.
"""

import json
import os
import re
import shutil
import sqlite3
import tempfile
from typing import Any, Optional

from .blossom_error import BlossomError, Stage, fail
from .paths import CONFIG_DIR

SPOTIFY_WEB_SESSION_FILE = os.path.join(CONFIG_DIR, "spotify_web_session.json")
SPOTIFY_WEB_PROFILE_DIR = os.path.join(CONFIG_DIR, "spotify_web_profile")
PARTNER_QUERY_URL = "https://api-partner.spotify.com/pathfinder/v1/query"


def get_saved_sp_dc() -> str:
    try:
        with open(SPOTIFY_WEB_SESSION_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return (data.get("sp_dc") or "").strip()
    except Exception:
        return ""


def save_sp_dc(value: str) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(SPOTIFY_WEB_SESSION_FILE, "w", encoding="utf-8") as handle:
        json.dump({"sp_dc": (value or "").strip()}, handle, ensure_ascii=False)


def clear_sp_dc() -> None:
    try:
        os.remove(SPOTIFY_WEB_SESSION_FILE)
    except OSError:
        pass


def _decrypt_chromium_value(encrypted: bytes, profile_dir: str) -> str:
    """Расшифровка cookie-значения Chromium (Windows DPAPI / AES-GCM v10)."""
    if not encrypted:
        return ""
    # Старый формат DPAPI (без префикса v10/v11)
    if not encrypted.startswith(b"v10") and not encrypted.startswith(b"v11"):
        try:
            import win32crypt  # type: ignore

            data = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)[1]
            return data.decode("utf-8", "ignore")
        except Exception:
            return ""
    # Новый формат v10/v11: AES-256-GCM, ключ лежит в Local State (DPAPI-обёрнут)
    try:
        import base64

        from Crypto.Cipher import AES  # type: ignore
        import win32crypt  # type: ignore

        local_state = os.path.join(os.path.dirname(profile_dir.rstrip("/\\")), "Local State")
        if not os.path.exists(local_state):
            local_state = os.path.join(profile_dir, "Local State")
        with open(local_state, "r", encoding="utf-8") as handle:
            state = json.load(handle)
        key_b64 = state["os_crypt"]["encrypted_key"]
        key = base64.b64decode(key_b64)[5:]  # отрезаем префикс DPAPI
        key = win32crypt.CryptUnprotectData(key, None, None, None, 0)[1]
        nonce = encrypted[3:15]
        ciphertext = encrypted[15:-16]
        tag = encrypted[-16:]
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8", "ignore")
    except Exception:
        return ""


def read_sp_dc_from_profile(profile_dir: str = SPOTIFY_WEB_PROFILE_DIR) -> str:
    """Читает cookie sp_dc прямо из Cookies-базы профиля QWebEngine.

    Нужно потому, что Qt не отдаёт HttpOnly-cookie через cookieAdded/loadAllCookies,
    а sp_dc как раз HttpOnly. Значение на Windows обычно хранится в открытом виде;
    если зашифровано — пытаемся расшифровать.
    """
    cookies_path = os.path.join(profile_dir, "Cookies")
    if not os.path.exists(cookies_path):
        return ""
    tmp_path = ""
    try:
        # База занята работающим приложением — копируем, чтобы не упереться в блокировку
        fd, tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        shutil.copy2(cookies_path, tmp_path)
        conn = sqlite3.connect(tmp_path)
        try:
            cur = conn.execute(
                "SELECT value, encrypted_value FROM cookies "
                "WHERE name='sp_dc' AND host_key LIKE '%spotify.com' "
                "ORDER BY length(value)+length(encrypted_value) DESC LIMIT 1"
            )
            row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return ""
        value, encrypted = row[0], row[1]
        if value:
            return value.strip() if isinstance(value, str) else value.decode("utf-8", "ignore").strip()
        if encrypted:
            return _decrypt_chromium_value(bytes(encrypted), profile_dir).strip()
        return ""
    except Exception:
        return ""
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def create_web_login(sp_dc: str):
    """Создаёт веб-сессию Spotify из cookie sp_dc и проверяет, что она жива."""
    if not (sp_dc or "").strip():
        fail(Stage.SPOTIFY_AUTH, "SPOTIFY_WEB_SESSION_EXPIRED", "Нет сохранённого входа в Spotify — нужен вход")
    try:
        from spotapi import Config, Login, NoopLogger
    except ImportError as exc:
        fail(Stage.SPOTIFY_AUTH, "SPOTAPI_MISSING", "Пакет spotapi не установлен", str(exc))
    # from_cookies требует и identifier, и cookies; для веб-сессии хватает sp_dc.
    dump = {"identifier": "blossom_user", "cookies": {"sp_dc": sp_dc.strip()}}
    try:
        login = Login.from_cookies(dump, Config(logger=NoopLogger()))
    except Exception as exc:
        fail(Stage.SPOTIFY_AUTH, "SPOTIFY_WEB_SESSION_EXPIRED", "Сессия Spotify не принялась — нужен вход заново", str(exc))
    # verify_login() в текущей версии spotapi падает на «Invalid JSON»,
    # поэтому проверяем живость сессии лёгким чтением библиотеки.
    try:
        from spotapi import PrivatePlaylist

        lib = PrivatePlaylist(login).get_library(1)
        if not isinstance(lib, dict) or "data" not in lib:
            raise RuntimeError("library probe returned no data")
    except BlossomError:
        raise
    except Exception as exc:
        fail(Stage.SPOTIFY_AUTH, "SPOTIFY_WEB_SESSION_EXPIRED", "Сессия Spotify истекла — нужен вход заново", str(exc))
    return login


def _find_playlists_in_library(node: Any, found: dict) -> None:
    """Рекурсивно собирает {uri: name} всех плейлистов из ответа libraryV3."""
    if isinstance(node, dict):
        uri = node.get("uri")
        name = node.get("name")
        typename = node.get("__typename") or ""
        if isinstance(uri, str) and isinstance(name, str):
            if uri.startswith("spotify:playlist:") and "Playlist" in typename:
                found.setdefault(uri, name)
            elif uri == "spotify:collection:tracks":
                found.setdefault(uri, name)
        for value in node.values():
            _find_playlists_in_library(value, found)
    elif isinstance(node, list):
        for value in node:
            _find_playlists_in_library(value, found)


def _track_entry_from_web(data: Optional[dict]) -> Optional[dict]:
    if not isinstance(data, dict):
        return None
    uri = data.get("uri") or ""
    if not uri.startswith("spotify:track:"):
        return None
    track_id = uri.split(":")[-1]
    if not track_id:
        return None
    artists_node = ((data.get("artists") or {}).get("items")) or []
    artists = ", ".join(
        ((a.get("profile") or {}).get("name") or "").strip()
        for a in artists_node
        if (a.get("profile") or {}).get("name")
    )
    return {
        "id": track_id,
        "url": f"https://open.spotify.com/track/{track_id}",
        "title": (data.get("name") or "").strip() or "Unknown",
        "artist": artists or "Unknown Artist",
    }


def _fetch_playlist_tracks(login, playlist_uri: str) -> list[dict]:
    from spotapi import PublicPlaylist

    playlist_id = playlist_uri.split(":")[-1]
    # Авторизованный клиент сессии — так читаются и приватные плейлисты
    playlist = PublicPlaylist(playlist_id, client=login.client)
    tracks: list[dict] = []
    for chunk in playlist.paginate_playlist():
        for item in chunk.get("items") or []:
            data = ((item.get("itemV2") or {}).get("data")) or {}
            entry = _track_entry_from_web(data)
            if entry:
                tracks.append(entry)
    return tracks


def _fetch_liked_tracks(login) -> list[dict]:
    """Любимые треки через ту же GraphQL-операцию, что и веб-плеер."""
    from spotapi import PrivatePlaylist

    base = PrivatePlaylist(login).base
    tracks: list[dict] = []
    offset, limit = 0, 100
    while True:
        params = {
            "operationName": "fetchLibraryTracks",
            "variables": json.dumps({"limit": limit, "offset": offset}),
            "extensions": json.dumps(
                {"persistedQuery": {"version": 1, "sha256Hash": base.part_hash("fetchLibraryTracks")}}
            ),
        }
        resp = login.client.post(PARTNER_QUERY_URL, params=params, authenticate=True)
        if getattr(resp, "fail", True):
            raise RuntimeError("fetchLibraryTracks failed")
        library = (((resp.response or {}).get("data") or {}).get("me") or {}).get("library") or {}
        node = library.get("tracks") or {}
        items = node.get("items") or []
        for item in items:
            data = ((item.get("track") or {}).get("data")) or {}
            entry = _track_entry_from_web(data)
            if entry:
                tracks.append(entry)
        total = int(node.get("totalCount") or 0)
        offset += limit
        if offset >= total or not items:
            break
    return tracks


ARTIST_URL_RE = re.compile(
    r"open\.spotify\.com/(?:intl-[a-z]{2}/)?artist/([A-Za-z0-9]{22})", re.IGNORECASE
)


def extract_artist_id_from_url(url: str) -> str:
    match = ARTIST_URL_RE.search((url or "").strip())
    return match.group(1) if match else ""


def search_artist_web(login, query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Ищет артистов по имени, возвращает [{id, name}] по релевантности."""
    from spotapi import Artist

    try:
        res = Artist(login).query_artists(query, limit=limit)
    except Exception as exc:
        fail(Stage.SPOTIFY_RESOLVE, "SPOTIFY_ARTIST_SEARCH_FAIL", "Не удалось найти артиста", str(exc))
    items = (((res.get("data") or {}).get("searchV2") or {}).get("artists") or {}).get("items") or []
    out = []
    for item in items:
        data = (item or {}).get("data") or {}
        uri = data.get("uri") or ""
        name = ((data.get("profile") or {}).get("name") or "").strip()
        if uri.startswith("spotify:artist:") and name:
            out.append({"id": uri.split(":")[-1], "name": name})
    return out


def _release_items(section: Optional[dict]) -> list[dict]:
    """Извлекает альбомы/синглы из секции дискографии (albums/singles/compilations)."""
    out: list[dict] = []
    for item in (section or {}).get("items") or []:
        for release in ((item.get("releases") or {}).get("items")) or []:
            if release.get("id"):
                out.append(release)
    return out


def fetch_artist_discography_web(login, artist_id: str, progress=None) -> dict[str, Any]:
    """Все треки артиста (альбомы+синглы+сборники), без дублей по track_id.

    Ограничение: берётся первая страница каждой секции дискографии (обычно
    по 10 альбомов и синглов) — у spotapi нет пагинации для queryArtistOverview.
    Для подавляющего большинства артистов этого достаточно для полной дискографии.
    """

    def _notify(msg: str) -> None:
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    from spotapi import Artist, PublicAlbum

    _notify("Читаю карточку артиста…")
    try:
        res = Artist(login).get_artist(artist_id)
    except Exception as exc:
        fail(Stage.SPOTIFY_RESOLVE, "SPOTIFY_ARTIST_FETCH_FAIL", "Не удалось получить данные артиста", str(exc))

    artist_union = ((res.get("data") or {}).get("artistUnion")) or {}
    artist_name = ((artist_union.get("profile") or {}).get("name") or "").strip() or "Unknown Artist"
    discography = artist_union.get("discography") or {}

    albums: dict[str, dict] = {}
    skipped_more = 0
    for section_key in ("albums", "singles", "compilations"):
        section = discography.get(section_key) or {}
        releases = _release_items(section)
        total = int(section.get("totalCount") or 0)
        if total > len(releases):
            skipped_more += total - len(releases)
        for release in releases:
            album_id = release.get("id")
            if album_id:
                albums.setdefault(album_id, release)

    if skipped_more:
        _notify(f"Найдено релизов: {len(albums)} (ещё {skipped_more} не попали в первую страницу)")
    else:
        _notify(f"Найдено релизов: {len(albums)}")

    tracks: list[dict[str, Any]] = []
    seen_track_ids: set[str] = set()
    for index, (album_id, release) in enumerate(albums.items(), start=1):
        album_name = (release.get("name") or "").strip() or "Без названия"
        _notify(f"Альбом {index}/{len(albums)}: {album_name}…")
        try:
            info = PublicAlbum(album_id, client=login.client).get_album_info()
        except Exception:
            continue
        album_union = ((info.get("data") or {}).get("albumUnion")) or {}
        items = ((album_union.get("tracksV2") or {}).get("items")) or []
        for item in items:
            track = (item or {}).get("track") or {}
            uri = track.get("uri") or ""
            if not uri.startswith("spotify:track:"):
                continue
            track_id = uri.split(":")[-1]
            if not track_id or track_id in seen_track_ids:
                continue
            seen_track_ids.add(track_id)
            artist_names = ", ".join(
                ((a.get("profile") or {}).get("name") or "").strip()
                for a in ((track.get("artists") or {}).get("items") or [])
                if (a.get("profile") or {}).get("name")
            )
            tracks.append({
                "id": track_id,
                "url": f"https://open.spotify.com/track/{track_id}",
                "title": (track.get("name") or "").strip() or "Unknown",
                "artist": artist_names or artist_name,
            })
    return {"artist_name": artist_name, "tracks": tracks}


def fetch_user_library_web(login, progress=None) -> list[dict[str, Any]]:
    """Все плейлисты пользователя (включая «Любимые треки») с треками."""

    def _notify(msg: str) -> None:
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    from spotapi import PrivatePlaylist

    _notify("Читаю список плейлистов…")
    try:
        library = PrivatePlaylist(login).get_library(50)
    except Exception as exc:
        fail(Stage.SPOTIFY_RESOLVE, "SPOTIFY_WEB_LIBRARY_FAIL", "Не удалось прочитать библиотеку Spotify", str(exc))

    found: dict = {}
    _find_playlists_in_library(library, found)

    playlists: list[dict[str, Any]] = []

    # Любимые треки
    if "spotify:collection:tracks" in found:
        _notify("Читаю «Любимые треки»…")
        try:
            liked = _fetch_liked_tracks(login)
            if liked:
                playlists.append({"name": "Любимые из Spotify", "tracks": liked})
        except Exception:
            _notify("«Любимые треки» прочитать не удалось — продолжаю с плейлистами")

    playlist_uris = [u for u in found if u.startswith("spotify:playlist:")]
    for index, uri in enumerate(playlist_uris, start=1):
        name = (found[uri] or "").strip() or "Без названия"
        _notify(f"Плейлист {index}/{len(playlist_uris)}: {name}…")
        try:
            tracks = _fetch_playlist_tracks(login, uri)
        except Exception:
            _notify(f"Не удалось прочитать «{name}» — пропускаю")
            continue
        playlists.append({"name": name, "tracks": tracks})

    return playlists
