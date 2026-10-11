"""Автосейв: запускается по таймеру (Планировщик заданий, каждые 5 минут),
проверяет, есть ли изменения в репозитории, и коммитит + пушит их, но только
если изменения "устоялись" — то есть не менялись с прошлого запуска скрипта.
Это даёт эффект "подождать, пока дописал, потом закоммитить" без постоянно
висящего в фоне процесса.

Регистрация в планировщике: scripts/register_autosave_task.ps1
"""
import subprocess
from datetime import datetime
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_DIR / ".git" / "autosave_state.txt"
LOG_FILE = REPO_DIR / "autosave.log"


def run_git(*args: str) -> tuple[int, str]:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_DIR,
        capture_output=True,
        text=True,
    )
    return result.returncode, (result.stdout + result.stderr).strip()


def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def get_status() -> str:
    code, out = run_git("status", "--porcelain")
    return out if code == 0 else ""


def commit_and_push() -> None:
    run_git("add", "-A")
    code, diff = run_git("diff", "--cached", "--name-only")
    if not diff:
        return
    message = f"Автосохранение {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    code, out = run_git("commit", "-m", message)
    if code != 0:
        log(f"Коммит не удался: {out}")
        return
    log(f"Коммит создан: {message}")
    code, out = run_git("push", "origin", "main")
    if code != 0:
        log(f"Push не удался (попробую в следующий запуск): {out}")
    else:
        log("Push успешен")


def main() -> None:
    status = get_status()
    previous = STATE_FILE.read_text(encoding="utf-8") if STATE_FILE.exists() else ""

    if not status:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        return

    if status != previous:
        # Изменения ещё "свежие" (поменялись с прошлого тика) — подождём ещё один цикл
        STATE_FILE.write_text(status, encoding="utf-8")
        return

    # Статус не менялся с прошлого запуска — значит, дописали, можно коммитить
    commit_and_push()
    if STATE_FILE.exists():
        STATE_FILE.unlink()


if __name__ == "__main__":
    main()
