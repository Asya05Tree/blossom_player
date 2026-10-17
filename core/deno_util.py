"""Deno нужен yt-dlp, чтобы решать новые JS-испытания YouTube (PoToken/n-sig) —
без него yt-dlp падает с "AudioProviderError: YT-DLP download error" почти на
каждом втором треке (сам yt-dlp честно пишет "Some YouTube downloads require
Deno. Run spotdl --download-deno or install Deno system-wide"). Бандлим свою
копию в tools/deno, чтобы ничего не требовалось ставить руками.
"""
import os
import shutil

from .paths import BASE_DIR


def resolve_deno() -> str:
    """Возвращает путь к deno.exe или '' если не найден (деградируем мягко —
    отсутствие Deno не должно блокировать само скачивание, yt-dlp просто
    выдаст то же предупреждение, что и раньше)."""
    env_path = (os.environ.get("BLOSSOM_DENO") or "").strip()
    if env_path and os.path.isfile(env_path):
        return env_path
    bundled = os.path.join(BASE_DIR, "tools", "deno", "deno.exe")
    if os.path.isfile(bundled):
        return bundled
    return shutil.which("deno") or ""
