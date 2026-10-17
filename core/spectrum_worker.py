import json

from PyQt6.QtCore import QThread, pyqtSignal

from .audio_spectrum import FRAME_MS, analyze_spectrum


class SpectrumAnalysisWorker(QThread):
    """Разовый фоновый расчёт аудио-спектра одной песни для визуализатора."""

    finished_ok = pyqtSignal(int, str)   # song_id, json {"frame_ms": int, "frames": [[...]]}
    finished_err = pyqtSignal(int, str)

    def __init__(self, song_id: int, filepath: str):
        super().__init__()
        self.song_id = song_id
        self.filepath = filepath

    def run(self):
        try:
            frames = analyze_spectrum(self.filepath)
            payload = json.dumps({"frame_ms": FRAME_MS, "frames": frames}, ensure_ascii=False)
            self.finished_ok.emit(self.song_id, payload)
        except Exception as exc:
            self.finished_err.emit(self.song_id, str(exc))
