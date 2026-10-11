from enum import Enum
from dataclasses import dataclass


class Stage(str, Enum):
    CONFIG = "config"
    SPOTIFY_AUTH = "spotify_auth"
    SPOTIFY_RESOLVE = "spotify_resolve"
    SPOTIFY_DOWNLOAD = "spotify_download"
    YOUTUBE_DOWNLOAD = "youtube_download"
    DRIVE_AUTH = "drive_auth"
    DRIVE_FOLDER = "drive_folder"
    DRIVE_UPLOAD = "drive_upload"
    FILE_IO = "file_io"
    FORMAT = "format"
    PIPELINE = "pipeline"


@dataclass
class BlossomError(Exception):
    stage: Stage
    code: str
    message: str
    detail: str = ""

    def __str__(self) -> str:
        base = f"[{self.stage.value}:{self.code}] {self.message}"
        if self.detail:
            return f"{base} | {self.detail}"
        return base

    def to_dict(self) -> dict:
        return {
            "stage": self.stage.value,
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
        }


def fail(stage: Stage, code: str, message: str, detail: str = "") -> None:
    raise BlossomError(stage=stage, code=code, message=message, detail=detail)
