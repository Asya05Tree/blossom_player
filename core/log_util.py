import os
import sys
import time
from typing import Any


def log(step: str, message: str) -> None:
    print(f"[{step}] {message}", flush=True)


def log_kv(step: str, key: str, value: Any) -> None:
    print(f"[{step}] {key}: {value}", flush=True)


def log_to_file(step: str, message: str, filename: str = "crash_forensics.log") -> None:
    """Пишет лог на диск (не только в stdout, как log()) — переживает крэш самого
    процесса или закрытие консоли. Нужен там, где при повторном крэше важно знать
    последний шаг до падения (например, импорт большой дискографии артиста).
    Никогда не бросает исключение — логирование не должно само ронять программу.
    """
    try:
        from .paths import BASE_DIR
        log_dir = os.path.join(BASE_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{step}] {message}\n"
        with open(os.path.join(log_dir, filename), "a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
    except Exception:
        pass
