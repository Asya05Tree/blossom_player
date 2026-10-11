import argparse
import json
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

from core.drive import BlossomDriveManager
from core.import_pipeline import import_spotify_track_safe
from core.log_util import log


def main() -> int:
    parser = argparse.ArgumentParser(description="Импорт трека Spotify -> локально + Google Drive")
    parser.add_argument("url", help="Ссылка на трек Spotify")
    parser.add_argument("--lyrics", default="", help="Текст песни")
    parser.add_argument("--cover", default="", help="Путь к обложке или URL")
    parser.add_argument("--video", default="", help="Ссылка на фоновое видео")
    parser.add_argument("--no-drive", action="store_true", help="Не загружать в Google Drive")
    parser.add_argument("--no-db", action="store_true", help="Не сохранять в SQLite")
    args = parser.parse_args()

    log("cli", "старт импорта (первый раз может занять несколько минут)")
    drive = BlossomDriveManager()
    result = import_spotify_track_safe(
        args.url,
        drive,
        lyrics=args.lyrics,
        cover_source=args.cover,
        video_link=args.video,
        upload_to_drive=not args.no_drive,
        save_to_db=not args.no_db,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
