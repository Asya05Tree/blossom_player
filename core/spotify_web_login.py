"""Встроенное окно входа в Spotify (QWebEngineView) с захватом cookie sp_dc."""

import os

from PyQt6.QtCore import QUrl, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
)
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView

from .paths import CONFIG_DIR
from .spotify_web_service import save_sp_dc, read_sp_dc_from_profile, SPOTIFY_WEB_PROFILE_DIR

LOGIN_URL = "https://accounts.spotify.com/login?continue=https%3A%2F%2Fopen.spotify.com%2F"
PLAYER_URL = "https://open.spotify.com/"

# Профиль держим на уровне модуля: если он умрёт раньше страницы, WebEngine ругается
# («Release of profile requested but WebEnginePage still not deleted») и окно виснет.
_shared_profile: QWebEngineProfile | None = None


def _get_profile() -> QWebEngineProfile:
    global _shared_profile
    if _shared_profile is None:
        profile = QWebEngineProfile("spotify_web_login", QApplication.instance())
        profile.setPersistentStoragePath(os.path.join(CONFIG_DIR, "spotify_web_profile"))
        profile.setCachePath(os.path.join(CONFIG_DIR, "spotify_web_profile", "cache"))
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        _shared_profile = profile
    return _shared_profile


def _qba_to_str(value) -> str:
    """QByteArray/bytes/str -> str, устойчиво к типу, который отдаёт PyQt."""
    try:
        if isinstance(value, str):
            return value
        if hasattr(value, "data"):  # QByteArray
            return bytes(value.data()).decode("utf-8", "ignore")
        return bytes(value).decode("utf-8", "ignore")
    except Exception:
        try:
            return str(value)
        except Exception:
            return ""


class SpotifyWebLoginDialog(QDialog):
    """Окно «войди в свой Spotify»: после входа cookie sp_dc сохраняется автоматически."""

    sp_dc_captured = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Вход в Spotify")
        self.resize(480, 720)
        self._sp_dc = ""
        self._finishing = False
        self._seen_cookie_names = set()
        self._forced_player = False

        layout = QVBoxLayout(self)
        self.hint = QLabel("Войди в свой аккаунт Spotify. Окно закроется само после входа.")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#7e57c2;font-size:12px;padding:4px")
        layout.addWidget(self.hint)

        self.profile = _get_profile()
        self._store = self.profile.cookieStore()
        self._store.cookieAdded.connect(self._on_cookie_added)

        self.view = QWebEngineView(self)
        self.page = QWebEnginePage(self.profile, self.view)
        self.view.setPage(self.page)
        # Когда страница догрузилась (например, open.spotify.com после входа) —
        # принудительно переотдаём cookie, чтобы поймать уже выставленный sp_dc.
        self.view.loadFinished.connect(lambda ok: self._rescan_cookies())
        layout.addWidget(self.view, 1)

        btn_row = QHBoxLayout()
        self.btn_done = QPushButton("Я вошёл(ла) — продолжить")
        self.btn_done.clicked.connect(self._manual_continue)
        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_done)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)

        self.view.setUrl(QUrl(LOGIN_URL))
        # Переотдать уже сохранённые cookie (sp_dc мог остаться с прошлой сессии профиля)
        self._rescan_cookies()

    def _rescan_cookies(self):
        try:
            self._store.loadAllCookies()
        except Exception:
            pass
        # sp_dc — HttpOnly, Qt его через cookieAdded не отдаёт; читаем из профиля на диске.
        self._try_disk_capture()

    def _try_disk_capture(self) -> bool:
        if self._sp_dc:
            return True
        try:
            value = read_sp_dc_from_profile(SPOTIFY_WEB_PROFILE_DIR)
        except Exception:
            value = ""
        if value:
            self._capture(value)
            return True
        return False

    def _capture(self, value: str):
        self._sp_dc = value
        try:
            save_sp_dc(value)
        except Exception:
            pass
        self.hint.setText("Вход выполнен! Завершаю…")
        if not self._finishing:
            self._finishing = True
            QTimer.singleShot(300, self._finish_success)

    def _on_cookie_added(self, cookie):
        name = _qba_to_str(cookie.name())
        if name:
            self._seen_cookie_names.add(name)
        if name != "sp_dc":
            return
        value = _qba_to_str(cookie.value()).strip()
        if not value:
            return
        # НЕ закрываем синхронно внутри callback во время навигации — это вешает WebEngine.
        self._capture(value)

    def _manual_continue(self):
        if self._sp_dc or self._try_disk_capture():
            self._finish_success()
            return
        # Принудительно перечитываем cookie и проверяем чуть позже
        self.hint.setText("Проверяю вход…")
        self._rescan_cookies()
        QTimer.singleShot(700, self._after_manual_rescan)

    def _poll_disk(self, attempts_left: int):
        """Несколько раз пробуем прочитать sp_dc с диска (он пишется не мгновенно)."""
        if self._sp_dc or self._try_disk_capture():
            return
        if attempts_left > 0:
            QTimer.singleShot(1500, lambda: self._poll_disk(attempts_left - 1))
        else:
            seen = ", ".join(sorted(self._seen_cookie_names)) or "ничего"
            self.hint.setText(
                "Spotify пока не выдал ключ sp_dc. Открой внутри окна свой плейлист "
                "и нажми «Я вошёл(ла)» ещё раз.\n"
                f"Вижу cookie: {seen}"
            )

    def _after_manual_rescan(self):
        if self._sp_dc or self._try_disk_capture():
            self._finish_success()
            return
        has_session = self._seen_cookie_names & {"sp_t", "sp_key", "sp_sso_csrf_token"}
        current = _qba_to_str(self.view.url().toString())
        on_player = current.startswith("https://open.spotify.com")
        # Вход есть, но sp_dc выдаёт только сам веб-плеер open.spotify.com.
        # Если мы ещё не там — принудительно переходим туда и пробуем снова.
        if has_session and not on_player and not self._forced_player:
            self._forced_player = True
            self.hint.setText("Открываю веб-плеер Spotify для получения ключа…")
            self.view.setUrl(QUrl(PLAYER_URL))
            QTimer.singleShot(3500, lambda: self._poll_disk(5))
            return
        if has_session and on_player:
            # Уже на плеере, но ключа нет — опрашиваем диск с повторами.
            self.hint.setText("Почти готово, получаю ключ…")
            self._poll_disk(6)
            return
        seen = ", ".join(sorted(self._seen_cookie_names)) or "ничего"
        msg = ("Пока не вижу вход. Дойди до своей музыки на open.spotify.com, "
               "затем нажми «Я вошёл(ла)» ещё раз.")
        self.hint.setText(f"{msg}\nВижу cookie: {seen}")

    def _finish_success(self):
        if not self._sp_dc:
            return
        self.sp_dc_captured.emit(self._sp_dc)
        self.accept()

    def _teardown(self):
        try:
            self._store.cookieAdded.disconnect(self._on_cookie_added)
        except Exception:
            pass
        try:
            self.view.stop()
            self.view.setPage(None)
            self.page.deleteLater()
        except Exception:
            pass

    def closeEvent(self, event):
        self._teardown()
        super().closeEvent(event)

    def done(self, result):
        self._teardown()
        super().done(result)
