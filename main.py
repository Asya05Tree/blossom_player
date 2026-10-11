import os
import sys


def _relaunch_in_venv_if_needed() -> None:
    root = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(root, ".venv", "Scripts", "python.exe")
    if not os.path.isfile(venv_python):
        return
    current = os.path.normcase(os.path.abspath(sys.executable))
    target = os.path.normcase(os.path.abspath(venv_python))
    if current != target:
        os.execv(venv_python, [venv_python] + sys.argv)


_relaunch_in_venv_if_needed()

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtGui import QIcon
import core.database as db
from core.player import BlossomPlayer
from core.drive import BlossomDriveManager
from core.bridge import BlossomBridge

class BlossomWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Blossom Player 🌸")
        self.resize(1100, 720) 

        project_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(project_dir, "assets", "icon.png")
        if os.path.isfile(icon_path):
            app_icon = QIcon(icon_path)
            QApplication.instance().setWindowIcon(app_icon)
            self.setWindowIcon(app_icon)

        self.player = BlossomPlayer()
        self.player.set_volume(0.2)
        self.drive = BlossomDriveManager()
        self.bridge = BlossomBridge(self.player, self.drive)
        self.browser = QWebEngineView()
        
        # Настройка разрешений
        settings = self.browser.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, True)

        self.channel = QWebChannel()
        self.channel.registerObject("pyBridge", self.bridge)
        self.browser.page().setWebChannel(self.channel)
        
        ui_path = os.path.abspath(os.path.join(project_dir, "ui", "index.html"))
        self.browser.setUrl(QUrl.fromLocalFile(ui_path))
        self.setCentralWidget(self.browser)
        self.load_initial_library()

    def load_initial_library(self):
        from PyQt6.QtCore import QTimer
        songs = db.get_all_songs()
        if songs:
            self.player.load_queue(songs, 0)
        def on_ready():
            self.bridge._update_ui_state()
            self.bridge._emit_library()
            self.bridge._emit_playlists()

        self.browser.loadFinished.connect(lambda: QTimer.singleShot(300, on_ready))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Blossom Player")
    window = BlossomWindow()
    window.show()
    sys.exit(app.exec())