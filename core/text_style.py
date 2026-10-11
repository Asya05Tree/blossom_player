from .blossom_error import BlossomError, Stage, fail

TITLE_PREFIX = "✧ "
TITLE_SUFFIX = " ✧"
ARTIST_PREFIX = "❀ "
ARTIST_SUFFIX = " ❀"

MAX_RAW_TITLE = 64
MAX_RAW_ARTIST = 48
MAX_DISPLAY_TITLE = 80
MAX_DISPLAY_ARTIST = 64


def _trim_raw(value: str, limit: int) -> str:
    cleaned = " ".join((value or "").strip().split())
    if not cleaned:
        fail(Stage.FORMAT, "EMPTY_TEXT", "Пустое значение для оформления")
    if len(cleaned) > limit:
        return cleaned[: limit - 1] + "…"
    return cleaned


def wrap_title(raw_title: str) -> str:
    core = _trim_raw(raw_title, MAX_RAW_TITLE)
    display = f"{TITLE_PREFIX}{core}{TITLE_SUFFIX}"
    if len(display) > MAX_DISPLAY_TITLE:
        fail(Stage.FORMAT, "TITLE_TOO_LONG", "Декоративное название слишком длинное", display)
    return display


def wrap_artist(raw_artist: str) -> str:
    core = _trim_raw(raw_artist, MAX_RAW_ARTIST)
    display = f"{ARTIST_PREFIX}{core}{ARTIST_SUFFIX}"
    if len(display) > MAX_DISPLAY_ARTIST:
        fail(Stage.FORMAT, "ARTIST_TOO_LONG", "Декоративный автор слишком длинный", display)
    return display


def unwrap_for_filename(display: str) -> str:
    value = (display or "").strip()
    for token in (TITLE_PREFIX, TITLE_SUFFIX, ARTIST_PREFIX, ARTIST_SUFFIX):
        value = value.replace(token, "")
    cleaned = "_".join(value.split())
    if not cleaned:
        fail(Stage.FORMAT, "EMPTY_FILENAME", "Не удалось собрать имя файла из декоративного текста")
    return cleaned[:120]
