import random
from typing import List, Optional
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtCore import QUrl
from .models import Song

class BlossomPlayer:
    def __init__(self):
        # Используем родной аудио-движок PyQt6
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        
        self.queue: List[Song] = []
        self.original_queue: List[Song] = []
        self.current_index: int = -1
        self.is_paused: bool = False
        
        self.loop_mode: str = "sequence" 
        self.is_shuffle: bool = False

    def load_queue(self, songs: List[Song], start_index: int = 0):
        self.original_queue = list(songs)
        valid_start = 0 <= start_index < len(songs)
        if self.is_shuffle:
            self.queue = list(songs)
            random.shuffle(self.queue)
            self.current_index = self.queue.index(songs[start_index]) if valid_start else -1
        else:
            self.queue = list(songs)
            self.current_index = start_index if valid_start else -1
        self.is_paused = False

    def get_current_song(self) -> Optional[Song]:
        if 0 <= self.current_index < len(self.queue):
            return self.queue[self.current_index]
        return None

    def get_next_song(self) -> Optional[Song]:
        if not self.queue:
            return None
        if self.loop_mode == "repeat_one":
            return self.get_current_song()
        next_idx = self.current_index + 1
        if next_idx >= len(self.queue):
            if self.loop_mode == "repeat_all":
                return self.queue[0]
            return None
        return self.queue[next_idx]

    def play(self):
        song = self.get_current_song()
        if not song or not song.filepath:
            return
        try:
            # Превращаем путь к файлу в понятный для Qt URL
            url = QUrl.fromLocalFile(song.filepath)
            self.player.setSource(url)
            self.player.play()
            self.is_paused = False
        except Exception as e:
            print(f"Error opening file {song.filepath}: {e}")

    def pause(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.is_paused = True

    def resume(self):
        if self.is_paused:
            self.player.play()
            self.is_paused = False

    def stop(self):
        self.player.stop()
        self.player.setPosition(0)
        self.is_paused = False

    def restart(self):
        """Перемотать на начало и продолжить воспроизведение."""
        self.player.setPosition(0)
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self.play()
        self.is_paused = False

    def next(self) -> bool:
        if not self.queue:
            return False
        if self.loop_mode == "repeat_one":
            self.play()
            return True
        self.current_index += 1
        if self.current_index >= len(self.queue):
            if self.loop_mode == "repeat_all":
                self.current_index = 0
            else:
                self.current_index = len(self.queue) - 1
                self.stop()
                return False
        self.play()
        return True

    def prev(self) -> bool:
        if not self.queue:
            return False
        self.current_index -= 1
        if self.current_index < 0:
            if self.loop_mode == "repeat_all":
                self.current_index = len(self.queue) - 1
            else:
                self.current_index = 0
        self.play()
        return True

    def set_volume(self, volume: float):
        # QAudioOutput принимает значение от 0.0 до 1.0
        self.audio_output.setVolume(max(0.0, min(1.0, volume)))

    def toggle_shuffle(self):
        current_song = self.get_current_song()
        self.is_shuffle = not self.is_shuffle
        if self.is_shuffle:
            random.shuffle(self.queue)
            if current_song in self.queue:
                self.queue.remove(current_song)
                self.queue.insert(0, current_song)
                self.current_index = 0
        else:
            self.queue = list(self.original_queue)
            if current_song in self.queue:
                self.current_index = self.queue.index(current_song)

    def set_loop_mode(self, mode: str):
        if mode in ["sequence", "repeat_one", "repeat_all"]:
            self.loop_mode = mode