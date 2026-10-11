import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
DOWNLOADS_DIR = os.path.join(ASSETS_DIR, "downloads")
COVERS_DIR = os.path.join(ASSETS_DIR, "covers")
LYRICS_DIR = os.path.join(ASSETS_DIR, "lyrics")
TEMP_DIR = os.path.join(ASSETS_DIR, "temp")

SPOTIFY_CLIENT_FILE = os.path.join(CONFIG_DIR, "spotify_client.json")
SPOTIFY_CACHE_FILE = os.path.join(CONFIG_DIR, ".spotify_cache")
GOOGLE_CREDENTIALS_FILE = os.path.join(CONFIG_DIR, "credentials.json")
GOOGLE_TOKEN_FILE = os.path.join(CONFIG_DIR, "token.json")
APP_SETTINGS_FILE = os.path.join(CONFIG_DIR, "app_settings.json")
