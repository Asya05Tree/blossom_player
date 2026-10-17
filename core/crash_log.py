"""Логирование причины вылета — пишется ДО того, как процесс реально падает.

Нативные креши (access violation в сторонней .dll, повреждение heap — см.
память crash_debugging) не перехватываются обычным Python try/except: это
работает только для Python-уровневых исключений, а не для сигналов ОС.
faulthandler.enable() ставит низкоуровневый обработчик фатальных исключений
(на Windows — через SEH) и успевает дописать в файл трейсы ВСЕХ потоков
Python на момент краша, прежде чем ОС завершит процесс. Это не лечит сам
краш (нативную память так не восстановить), но показывает, какая именно
Python-строка в каком потоке исполнялась в момент падения — не нужно каждый
раз вручную лезть в Event Log/minidump, чтобы понять "а что оно делало".
"""
import datetime
import faulthandler
import os
import sys

from .paths import BASE_DIR

CRASH_LOG_PATH = os.path.join(BASE_DIR, "crash_trace.log")
_MAX_LOG_BYTES = 2 * 1024 * 1024
_RUNNING_MARKER = os.path.join(BASE_DIR, ".blossom_running")

# Файл должен оставаться открытым весь процесс — faulthandler пишет в него
# напрямую на уровне C, в т.ч. в момент, когда обычный Python-код уже не
# может безопасно выполняться.
_log_file = None


def _rotate_if_too_big() -> None:
    try:
        if os.path.isfile(CRASH_LOG_PATH) and os.path.getsize(CRASH_LOG_PATH) > _MAX_LOG_BYTES:
            old_path = CRASH_LOG_PATH + ".old"
            if os.path.isfile(old_path):
                os.remove(old_path)
            os.replace(CRASH_LOG_PATH, old_path)
    except OSError:
        pass


def _qt_message_handler(mode, _context, message) -> None:
    """QtFatalMsg — настоящая, редкая фатальная ошибка Qt перед крашем.
    QtCriticalMsg сюда специально не включён: QtWebEngine шлёт его на каждый
    запуск для совершенно безобидных вещей (например, "permissions policy
    violation: autoplay is not allowed") — логировать это в crash_trace.log
    только зашумляло бы его на каждом старте без всякой пользы."""
    try:
        from PyQt6.QtCore import QtMsgType
        if mode == QtMsgType.QtFatalMsg and _log_file:
            _log_file.write(f"[{datetime.datetime.now().isoformat()}] Qt Fatal: {message}\n")
            _log_file.flush()
    except Exception:
        pass


def _excepthook(exc_type, exc_value, exc_tb) -> None:
    """Непойманные Python-исключения (не нативные креши) — тоже в тот же файл,
    чтобы вся история «почему вылетело» была в одном месте."""
    import traceback
    if _log_file:
        _log_file.write(f"\n[{datetime.datetime.now().isoformat()}] НЕПЕРЕХВАЧЕННОЕ ИСКЛЮЧЕНИЕ:\n")
        traceback.print_exception(exc_type, exc_value, exc_tb, file=_log_file)
        _log_file.flush()
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def had_previous_crash() -> bool:
    """True, если прошлый запуск не дошёл до mark_clean_exit() — то есть
    завершился не штатно (краш, kill, отключение питания и т.п.)."""
    return os.path.isfile(_RUNNING_MARKER)


def mark_running() -> None:
    try:
        with open(_RUNNING_MARKER, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))
    except OSError:
        pass


def mark_clean_exit() -> None:
    try:
        if os.path.isfile(_RUNNING_MARKER):
            os.remove(_RUNNING_MARKER)
    except OSError:
        pass
    if _log_file:
        _log_file.write(f"[{datetime.datetime.now().isoformat()}] Чистое завершение\n")
        _log_file.flush()


def install() -> str:
    """Включает логирование крашей. Звать максимально рано, до создания
    QApplication. Возвращает путь к лог-файлу."""
    global _log_file
    _rotate_if_too_big()
    _log_file = open(CRASH_LOG_PATH, "a", encoding="utf-8", buffering=1)
    _log_file.write(
        f"\n=== Запуск {datetime.datetime.now().isoformat()} "
        f"(pid {os.getpid()}, python {sys.version.split()[0]}) ===\n"
    )
    _log_file.flush()

    faulthandler.enable(file=_log_file, all_threads=True)
    sys.excepthook = _excepthook

    try:
        from PyQt6.QtCore import qInstallMessageHandler
        qInstallMessageHandler(_qt_message_handler)
    except Exception:
        pass

    return CRASH_LOG_PATH
