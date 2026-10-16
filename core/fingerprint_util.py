"""Аудио-отпечаток файла через fpcalc (Chromaprint) — не зависит от тегов/имени файла.

Используется для поиска дублей в библиотеке: два разных файла одной и той же
записи (разное название, разный источник, чуть обрезанные начало/конец) дают
почти совпадающие отпечатки, в отличие от сравнения по title/artist.
"""
import json
import os
import shutil
import subprocess

from .blossom_error import Stage, fail
from .paths import BASE_DIR

FPCALC_LENGTH_SECONDS = 120
# Сколько чисел отпечатка сравнивать (948 чисел ~ 120 сек у этого алгоритма,
# нам для дублей достаточно первых ~50 сек — быстрее и обычно хватает).
COMPARE_PREFIX = 400
MAX_ALIGN_OFFSET = 60  # ~секунд сдвига (на случай обрезанного начала)
MAX_BIT_ERROR = 2
# 0.4 ловил "похоже" (например, инструментал и вокальную версию с общей
# подложкой) — для кнопки удаления дублей нужно "это тот же файл", почти 1:1.
DEFAULT_DUPLICATE_THRESHOLD = 0.92


def resolve_fpcalc() -> str:
    env_path = (os.environ.get("BLOSSOM_FPCALC") or "").strip()
    if env_path and os.path.isfile(env_path):
        return env_path
    from_path = shutil.which("fpcalc")
    if from_path:
        return from_path
    candidate = os.path.join(BASE_DIR, "tools", "fpcalc", "fpcalc.exe")
    if os.path.isfile(candidate):
        return candidate
    fail(
        Stage.FILE_IO,
        "FPCALC_MISSING",
        "fpcalc не найден. Нужен tools/fpcalc/fpcalc.exe (Chromaprint) или fpcalc в PATH",
    )


def compute_fingerprint(filepath: str) -> str:
    """Возвращает JSON {"duration": сек, "fp": [...]} — хранится в БД как текст."""
    if not filepath or not os.path.isfile(filepath):
        fail(Stage.FILE_IO, "FINGERPRINT_FILE_MISSING", "Файл для отпечатка не найден", filepath or "")
    fpcalc = resolve_fpcalc()
    try:
        proc = subprocess.run(
            [fpcalc, "-raw", "-json", "-length", str(FPCALC_LENGTH_SECONDS), os.path.abspath(filepath)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception as exc:
        fail(Stage.PIPELINE, "FINGERPRINT_RUN_FAIL", "Не удалось запустить fpcalc", str(exc))
    if proc.returncode != 0 or not proc.stdout.strip():
        fail(Stage.PIPELINE, "FINGERPRINT_EMPTY", "fpcalc не вернул отпечаток", (proc.stderr or "")[:300])
    try:
        data = json.loads(proc.stdout)
        fingerprint = data["fingerprint"]
        duration = float(data["duration"])
        if not fingerprint:
            raise ValueError("empty fingerprint")
    except Exception as exc:
        fail(Stage.PIPELINE, "FINGERPRINT_PARSE_FAIL", "Не удалось разобрать вывод fpcalc", str(exc))
    return json.dumps({"duration": duration, "fp": fingerprint[: COMPARE_PREFIX * 2]})


def fingerprint_duration(fp_json: str) -> float:
    try:
        return float(json.loads(fp_json).get("duration") or 0.0)
    except Exception:
        return 0.0


def _popcount(x: int) -> int:
    return bin(x & 0xFFFFFFFF).count("1")


def fingerprint_similarity(fp_json_a: str, fp_json_b: str) -> float:
    """Схожесть двух отпечатков в диапазоне [0..1]. >= DEFAULT_DUPLICATE_THRESHOLD — вероятный дубль."""
    try:
        a = json.loads(fp_json_a)["fp"][:COMPARE_PREFIX]
        b = json.loads(fp_json_b)["fp"][:COMPARE_PREFIX]
    except Exception:
        return 0.0
    if not a or not b:
        return 0.0
    asize, bsize = len(a), len(b)
    counts: dict[int, int] = {}
    best = 0
    for i in range(asize):
        jbegin = max(0, i - MAX_ALIGN_OFFSET)
        jend = min(bsize, i + MAX_ALIGN_OFFSET)
        for j in range(jbegin, jend):
            if _popcount(a[i] ^ b[j]) <= MAX_BIT_ERROR:
                offset = i - j + bsize
                counts[offset] = counts.get(offset, 0) + 1
                if counts[offset] > best:
                    best = counts[offset]
    return best / min(asize, bsize)
