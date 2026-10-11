from PyQt6.QtCore import QThread, pyqtSignal

from .blossom_error import BlossomError
from .ocr_util import recognize_text


class OcrWorker(QThread):
    finished_ok = pyqtSignal(list)
    finished_err = pyqtSignal(dict)

    def __init__(self, image_path: str, lang: str = "en"):
        super().__init__()
        self.image_path = image_path
        self.lang = lang

    def run(self):
        try:
            lines = recognize_text(self.image_path, self.lang)
            self.finished_ok.emit(lines)
        except BlossomError as exc:
            self.finished_err.emit(exc.to_dict())
        except Exception as exc:
            self.finished_err.emit({
                "stage": "pipeline",
                "code": "OCR_CRASH",
                "message": "Ошибка распознавания текста",
                "detail": str(exc),
            })
