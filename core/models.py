from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class VideoLink:
    """Хранит ссылку на фоновое видео (TikTok или YouTube)"""
    url: str
    platform: str  # например, 'youtube' или 'tiktok'

@dataclass
class Song:
    """Модель песни со всеми её атрибутами"""
    id: Optional[int] = None
    title: str = ""
    artist: str = ""
    filepath: str = ""              # Путь к локальному аудиофайлу
    cover_path: Optional[str] = None # Путь к картинке песни
    lyrics: Optional[str] = ""      # Текст песни
    video_link: Optional[str] = None # Ссылка на клип
    drive_file_id: Optional[str] = None # ID аудио в Google Drive
    drive_cover_id: Optional[str] = None
    drive_lyrics_id: Optional[str] = None
    drive_meta_id: Optional[str] = None
    spotify_track_id: Optional[str] = None # ID трека в Spotify (для дедупликации)
    youtube_video_id: Optional[str] = None # ID видео на YouTube (для дедупликации)
    fingerprint: Optional[str] = None # Аудио-отпечаток (JSON-массив чисел) для поиска дублей по звуку
    added_at: Optional[int] = None  # Unix-время добавления в библиотеку (для сортировки по дате)

@dataclass
class Playlist:
    """Модель плейлиста"""
    id: Optional[int] = None
    name: str = ""                  # Название (с декоративными символами)
    cover_path: Optional[str] = None # Картинка плейлиста
    song_ids: List[int] = field(default_factory=list) # Список ID песен в плейлисте