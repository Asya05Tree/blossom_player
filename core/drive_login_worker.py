import json

from PyQt6.QtCore import QThread, pyqtSignal

from .blossom_error import BlossomError
from .drive import BlossomDriveManager


class DriveVerifyWorker(QThread):
    """Тихо проверяет реальный доступ к Google Drive (без браузера)."""

    finished_status = pyqtSignal(str)

    def __init__(self, drive: BlossomDriveManager):
        super().__init__()
        self.drive = drive

    def run(self):
        try:
            self.drive.try_silent_login()
        except Exception:
            pass
        self.finished_status.emit(json.dumps(self.drive.status_snapshot(), ensure_ascii=False))


class DriveLoginWorker(QThread):
    finished_ok = pyqtSignal(str)
    finished_err = pyqtSignal(str, str, str)

    def __init__(self, drive: BlossomDriveManager, pick_account: bool = False):
        super().__init__()
        self.drive = drive
        self.pick_account = pick_account

    def run(self):
        try:
            self.drive.login(pick_account=self.pick_account)
            payload = self.drive.status_snapshot()
            self.finished_ok.emit(json.dumps(payload, ensure_ascii=False))
        except BlossomError as exc:
            msg = exc.message
            if exc.detail and exc.code != "GOOGLE_TEST_USER_REQUIRED":
                msg = f"{exc.message} — {exc.detail[:200]}"
            self.finished_err.emit(exc.stage.value, exc.code, msg)
        except Exception as exc:
            self.finished_err.emit("drive_auth", "UNEXPECTED", str(exc))
