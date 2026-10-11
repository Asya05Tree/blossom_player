"""Распознавание текста (название/автор песни) с картинки через easyocr.

easyocr группирует языки по совместимым наборам — нельзя смешать корейский
и японский в одном Reader, поэтому держим отдельный закэшированный Reader
на каждый поддерживаемый язык (плюс английский, который сочетается с любым).
"""
from typing import Any

from .blossom_error import Stage, fail

LANG_GROUPS: dict[str, list[str]] = {
    "en": ["en"],
    "ru": ["en", "ru"],
    "ko": ["en", "ko"],
    "ja": ["en", "ja"],
    "ch": ["en", "ch_sim"],
}
DEFAULT_LANG = "en"
MIN_CONFIDENCE = 0.3

_readers: dict[str, Any] = {}


def _get_reader(lang: str):
    import easyocr

    key = lang if lang in LANG_GROUPS else DEFAULT_LANG
    if key not in _readers:
        try:
            _readers[key] = easyocr.Reader(LANG_GROUPS[key], gpu=False)
        except Exception as exc:
            fail(Stage.PIPELINE, "OCR_READER_INIT_FAIL", "Не удалось загрузить модель распознавания текста", str(exc))
    return _readers[key]


def recognize_text(image_path: str, lang: str = DEFAULT_LANG) -> list[str]:
    """Возвращает распознанные строки текста (отфильтрованные по уверенности)."""
    import os

    if not image_path or not os.path.isfile(image_path):
        fail(Stage.FILE_IO, "OCR_IMAGE_MISSING", "Картинка не найдена", image_path or "")
    reader = _get_reader(lang)
    try:
        results = reader.readtext(image_path)
    except Exception as exc:
        fail(Stage.PIPELINE, "OCR_RUN_FAIL", "Не удалось распознать текст на картинке", str(exc))
    lines = []
    for _box, text, conf in results:
        text = (text or "").strip()
        if text and conf >= MIN_CONFIDENCE:
            lines.append(text)
    return lines
