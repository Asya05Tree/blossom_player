import sys
from typing import Any


def log(step: str, message: str) -> None:
    print(f"[{step}] {message}", flush=True)


def log_kv(step: str, key: str, value: Any) -> None:
    print(f"[{step}] {key}: {value}", flush=True)
