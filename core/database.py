import os
import sqlite3
from typing import List, Optional
from .models import Song, Playlist

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "blossom.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    # Доступ к колонкам по имени: в старых БД порядок колонок может отличаться
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            artist TEXT,
            filepath TEXT NOT NULL,
            cover_path TEXT,
            lyrics TEXT,
            video_link TEXT,
            drive_file_id TEXT,
            drive_cover_id TEXT,
            drive_lyrics_id TEXT,
            drive_meta_id TEXT,
            spotify_track_id TEXT,
            youtube_video_id TEXT,
            fingerprint TEXT
        )
    ''')
    # Add columns if upgrading from old schema
    try:
        cursor.execute("ALTER TABLE songs ADD COLUMN drive_cover_id TEXT")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE songs ADD COLUMN drive_lyrics_id TEXT")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE songs ADD COLUMN drive_meta_id TEXT")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE songs ADD COLUMN spotify_track_id TEXT")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE songs ADD COLUMN youtube_video_id TEXT")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE songs ADD COLUMN fingerprint TEXT")
    except Exception:
        pass
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            cover_path TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS playlist_songs (
            playlist_id INTEGER,
            song_id INTEGER,
            FOREIGN KEY (playlist_id) REFERENCES playlists (id) ON DELETE CASCADE,
            FOREIGN KEY (song_id) REFERENCES songs (id) ON DELETE CASCADE,
            PRIMARY KEY (playlist_id, song_id)
        )
    ''')
    conn.commit()
    conn.close()

def add_song(song: Song) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO songs (title, artist, filepath, cover_path, lyrics, video_link, drive_file_id, drive_cover_id, drive_lyrics_id, drive_meta_id, spotify_track_id, youtube_video_id, fingerprint)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (song.title, song.artist, song.filepath, song.cover_path, song.lyrics, song.video_link,
          song.drive_file_id, song.drive_cover_id, song.drive_lyrics_id, song.drive_meta_id,
          song.spotify_track_id, song.youtube_video_id, song.fingerprint))
    conn.commit()
    song_id = cursor.lastrowid
    conn.close()
    return song_id

def _row_to_song(row) -> Song:
    keys = row.keys()

    def _get(name):
        return row[name] if name in keys else None

    return Song(
        id=_get("id"), title=_get("title") or "", artist=_get("artist") or "",
        filepath=_get("filepath") or "",
        cover_path=_get("cover_path"), lyrics=_get("lyrics"), video_link=_get("video_link"),
        drive_file_id=_get("drive_file_id"),
        drive_cover_id=_get("drive_cover_id"),
        drive_lyrics_id=_get("drive_lyrics_id"),
        drive_meta_id=_get("drive_meta_id"),
        spotify_track_id=_get("spotify_track_id"),
        youtube_video_id=_get("youtube_video_id"),
        fingerprint=_get("fingerprint"),
    )


def _normalize_text(value: str) -> str:
    """Нормализует строку для сравнения дублей: только буквы/цифры, нижний регистр."""
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def find_song_id_by_spotify_id(spotify_track_id: str) -> Optional[int]:
    if not spotify_track_id:
        return None
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM songs WHERE spotify_track_id = ?', (spotify_track_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def find_song_id_by_drive_file_id(drive_file_id: str) -> Optional[int]:
    if not drive_file_id:
        return None
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM songs WHERE drive_file_id = ?', (drive_file_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def find_song_id_by_title_artist(title: str, artist: str) -> Optional[int]:
    """Ищет дубль по нормализованным названию+исполнителю (декор игнорируется)."""
    target = (_normalize_text(title), _normalize_text(artist))
    if not target[0]:
        return None
    for song in get_all_songs():
        if (_normalize_text(song.title), _normalize_text(song.artist)) == target:
            return song.id
    return None


def set_song_spotify_id(song_id: int, spotify_track_id: str) -> None:
    conn = get_connection()
    conn.cursor().execute(
        'UPDATE songs SET spotify_track_id = ? WHERE id = ?',
        (spotify_track_id, song_id),
    )
    conn.commit()
    conn.close()


def find_song_id_by_youtube_id(youtube_video_id: str) -> Optional[int]:
    if not youtube_video_id:
        return None
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM songs WHERE youtube_video_id = ?', (youtube_video_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def set_song_youtube_id(song_id: int, youtube_video_id: str) -> None:
    conn = get_connection()
    conn.cursor().execute(
        'UPDATE songs SET youtube_video_id = ? WHERE id = ?',
        (youtube_video_id, song_id),
    )
    conn.commit()
    conn.close()


def set_song_fingerprint(song_id: int, fingerprint: str) -> None:
    conn = get_connection()
    conn.cursor().execute(
        'UPDATE songs SET fingerprint = ? WHERE id = ?',
        (fingerprint, song_id),
    )
    conn.commit()
    conn.close()


def get_songs_missing_fingerprint() -> List[Song]:
    """Песни с существующим локальным файлом, но без аудио-отпечатка."""
    return [
        s for s in get_all_songs()
        if not s.fingerprint and s.filepath and os.path.isfile(s.filepath)
    ]


def get_playlist_by_name(name: str) -> Optional[Playlist]:
    target = _normalize_text(name)
    if not target:
        return None
    for playlist in get_all_playlists():
        if _normalize_text(playlist.name) == target:
            return playlist
    return None

def get_all_songs() -> List[Song]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM songs')
    rows = cursor.fetchall()
    conn.close()
    return [_row_to_song(r) for r in rows]

def add_playlist(playlist: Playlist) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO playlists (name, cover_path) VALUES (?, ?)', 
                   (playlist.name, playlist.cover_path))
    conn.commit()
    playlist_id = cursor.lastrowid
    conn.close()
    return playlist_id

def add_song_to_playlist(playlist_id: int, song_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO playlist_songs (playlist_id, song_id) VALUES (?, ?)', 
                   (playlist_id, song_id))
    conn.commit()
    conn.close()


def get_song(song_id: int) -> Optional[Song]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM songs WHERE id = ?', (song_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return _row_to_song(row)


def update_song_row(
    song_id: int,
    title: str,
    artist: str,
    lyrics: str,
    cover_path: Optional[str] = None,
) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    if cover_path:
        cursor.execute(
            'UPDATE songs SET title = ?, artist = ?, lyrics = ?, cover_path = ? WHERE id = ?',
            (title, artist, lyrics, cover_path, song_id),
        )
    else:
        cursor.execute(
            'UPDATE songs SET title = ?, artist = ?, lyrics = ? WHERE id = ?',
            (title, artist, lyrics, song_id),
        )
    conn.commit()
    ok = cursor.rowcount > 0
    conn.close()
    return ok


def delete_song(song_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM playlist_songs WHERE song_id = ?', (song_id,))
    cursor.execute('DELETE FROM songs WHERE id = ?', (song_id,))
    conn.commit()
    ok = cursor.rowcount > 0
    conn.close()
    return ok


def get_all_playlists() -> List[Playlist]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, name, cover_path FROM playlists')
    rows = cursor.fetchall()
    conn.close()
    return [Playlist(id=r[0], name=r[1], cover_path=r[2]) for r in rows]


def get_playlist_songs(playlist_id: int) -> List[Song]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT s.* FROM songs s
        JOIN playlist_songs ps ON s.id = ps.song_id
        WHERE ps.playlist_id = ?
    ''', (playlist_id,))
    rows = cursor.fetchall()
    conn.close()
    return [_row_to_song(r) for r in rows]


def get_song_playlist_ids(song_id: int) -> List[int]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT playlist_id FROM playlist_songs WHERE song_id = ?', (song_id,))
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]


def remove_song_from_playlist(playlist_id: int, song_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM playlist_songs WHERE playlist_id = ? AND song_id = ?',
                   (playlist_id, song_id))
    conn.commit()
    ok = cursor.rowcount > 0
    conn.close()
    return ok


def rename_playlist(playlist_id: int, new_name: str) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE playlists SET name = ? WHERE id = ?', (new_name, playlist_id))
    conn.commit()
    ok = cursor.rowcount > 0
    conn.close()
    return ok


def delete_playlist(playlist_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM playlist_songs WHERE playlist_id = ?', (playlist_id,))
    cursor.execute('DELETE FROM playlists WHERE id = ?', (playlist_id,))
    conn.commit()
    ok = cursor.rowcount > 0
    conn.close()
    return ok