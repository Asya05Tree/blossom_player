import os

# Базовые пути проекта
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(BASE_DIR, "ui")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

# Путь к главному HTML макету
INDEX_HTML_PATH = os.path.join(UI_DIR, "index.html")

# Настройки звука по умолчанию (от 0.0 до 1.0)
DEFAULT_VOLUME = 0.7

# Флаги отладки
DEBUG_MODE = True