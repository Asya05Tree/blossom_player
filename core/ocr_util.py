"""Распознавание текста (название/автор песни) с картинки через easyocr.

easyocr группирует языки по совместимым наборам — нельзя смешать корейский
и японский в одном Reader, поэтому держим отдельный закэшированный Reader
на каждый поддерживаемый язык (плюс английский, который сочетается с любым).
"""
import re
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


_SEPARATOR_RE = re.compile(r"\s*[-–—:|]\s*")
# Подряд идущие латинские слова внутри строки — ловит английское название трека,
# затерявшееся посреди кириллического (или любого другого) текста, которое
# иначе никогда не стало бы отдельным кандидатом на скачивание.
_LATIN_RUN_RE = re.compile(r"[A-Za-z][A-Za-z0-9 .,'&!-]*[A-Za-z0-9]")
_MIN_CANDIDATE_LEN = 3


def extract_title_candidates(lines: list[str]) -> list[dict[str, Any]]:
    """Из распознанных строк достаёт более узких кандидатов на "название трека":
    части строки по разделителям ("Артист - Название") и отдельные латинские
    куски внутри строк на другом языке. Исходные строки не теряются — только
    дополняются. Возвращает [{"text": str, "is_line": bool}, ...] без дублей.
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    def _add(text: str, is_line: bool) -> None:
        cleaned = " ".join((text or "").split())
        key = cleaned.lower()
        if len(cleaned) < _MIN_CANDIDATE_LEN or key in seen:
            return
        seen.add(key)
        out.append({"text": cleaned, "is_line": is_line})

    for line in lines:
        _add(line, True)

    for line in lines:
        for part in _SEPARATOR_RE.split(line):
            if part.strip() and part.strip() != line.strip():
                _add(part, False)
        for match in _LATIN_RUN_RE.finditer(line):
            candidate = match.group(0).strip()
            if candidate and candidate != line.strip():
                _add(candidate, False)

    return out
