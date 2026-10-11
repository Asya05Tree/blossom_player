import mimetypes
import os
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .blossom_error import Stage, fail
from .paths import BASE_DIR, GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE, TEMP_DIR


def _resolve_config_path(preferred: str, legacy_name: str) -> str:
    if os.path.isfile(preferred):
        return preferred
    legacy = os.path.join(BASE_DIR, legacy_name)
    if os.path.isfile(legacy):
        return legacy
    return preferred

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
ROOT_FOLDER_NAME = "BlossomPlayer"
SUBFOLDERS = ("Music", "Covers", "Lyrics", "Meta")


class BlossomDriveManager:
    def __init__(self):
        self.service = None
        self.root_folder_id: Optional[str] = None
        self.subfolder_ids: dict[str, str] = {}
        self.user_email: str = ""

    def _token_file(self) -> str:
        return _resolve_config_path(GOOGLE_TOKEN_FILE, "token.json")

    def _credentials_file(self) -> str:
        return _resolve_config_path(GOOGLE_CREDENTIALS_FILE, "credentials.json")

    def logout(self) -> None:
        token_file = self._token_file()
        if os.path.exists(token_file):
            os.remove(token_file)
        self.service = None
        self.root_folder_id = None
        self.subfolder_ids = {}
        self.user_email = ""

    def _fetch_user_email(self) -> str:
        self._require_service()
        try:
            about = self.service.about().get(fields="user(emailAddress)").execute()
            user = about.get("user") or {}
            return (user.get("emailAddress") or "").strip()
        except Exception as exc:
            fail(Stage.DRIVE_AUTH, "DRIVE_EMAIL_FAIL", "Не удалось получить почту Google", str(exc))

    def status_snapshot(self) -> dict:
        # logged_in только при реально работающем сервисе (проверенный доступ),
        # наличие token.json само по себе ничего не гарантирует
        if self.service:
            return {"logged_in": True, "email": self.user_email or "…"}
        return {"logged_in": False, "email": ""}

    def try_silent_login(self) -> bool:
        """Проверяет реальный доступ к Google Drive без открытия браузера.

        Возвращает True только если токен валиден и Drive API реально отвечает.
        Невалидный/отозванный токен удаляется, чтобы UI показал вход заново.
        """
        token_file = self._token_file()
        if not os.path.exists(token_file):
            return False
        try:
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        except Exception:
            return False
        if not creds.valid:
            if not (creds.expired and creds.refresh_token):
                return False
            try:
                creds.refresh(Request())
            except Exception:
                # Токен отозван или невалиден — считаем, что пользователь не зашёл
                try:
                    os.remove(token_file)
                except OSError:
                    pass
                self.service = None
                return False
            try:
                with open(token_file, "w", encoding="utf-8") as token:
                    token.write(creds.to_json())
            except OSError:
                pass
        try:
            service = build("drive", "v3", credentials=creds, cache_discovery=False)
            # Реальный вызов API — единственная честная проверка доступа
            about = service.about().get(fields="user(emailAddress)").execute()
            self.service = service
            self.user_email = ((about.get("user") or {}).get("emailAddress") or "").strip()
            self.root_folder_id = self._get_or_create_folder(ROOT_FOLDER_NAME, None)
            self.subfolder_ids = {}
            for name in SUBFOLDERS:
                self.subfolder_ids[name] = self._get_or_create_folder(name, self.root_folder_id)
            return True
        except Exception:
            self.service = None
            self.root_folder_id = None
            self.subfolder_ids = {}
            self.user_email = ""
            return False

    def _require_service(self) -> None:
        if self.service is None:
            fail(Stage.DRIVE_AUTH, "DRIVE_NOT_LOGGED_IN", "Сначала вызови login() для Google Drive")

    def _require_local_file(self, local_path: str, code: str) -> None:
        if not local_path or not os.path.isfile(local_path):
            fail(Stage.DRIVE_UPLOAD, code, "Локальный файл не найден", local_path or "")
        if os.path.getsize(local_path) <= 0:
            fail(Stage.DRIVE_UPLOAD, f"{code}_EMPTY", "Локальный файл пустой", local_path)

    def login(self, pick_account: bool = False) -> bool:
        creds = None
        token_file = self._token_file()
        credentials_file = self._credentials_file()

        if pick_account:
            self.logout()

        if os.path.exists(token_file):
            try:
                creds = Credentials.from_authorized_user_file(token_file, SCOPES)
            except Exception as exc:
                fail(Stage.DRIVE_AUTH, "TOKEN_PARSE_FAIL", "Не удалось прочитать token.json", str(exc))

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as exc:
                    if os.path.exists(token_file):
                        os.remove(token_file)
                    fail(Stage.DRIVE_AUTH, "GOOGLE_TOKEN_REFRESH_FAIL", "Не удалось обновить token Google", str(exc))
            else:
                if not os.path.exists(credentials_file):
                    fail(
                        Stage.DRIVE_AUTH,
                        "GOOGLE_CREDENTIALS_MISSING",
                        "Нет config/credentials.json для Google Drive",
                        credentials_file,
                    )
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
                    if pick_account:
                        creds = flow.run_local_server(port=0, prompt="select_account consent")
                    else:
                        creds = flow.run_local_server(port=0)
                except Exception as exc:
                    detail = str(exc)
                    if "access_denied" in detail.lower():
                        fail(
                            Stage.DRIVE_AUTH,
                            "GOOGLE_TEST_USER_REQUIRED",
                            "Google: приложение в тестовом режиме. Добавь свою Gmail в Test users (Google Cloud Console → OAuth consent screen).",
                            detail,
                        )
                    fail(Stage.DRIVE_AUTH, "GOOGLE_OAUTH_FAIL", "OAuth Google Drive не прошёл", detail)

            os.makedirs(os.path.dirname(token_file), exist_ok=True)
            with open(token_file, "w", encoding="utf-8") as token:
                token.write(creds.to_json())

        try:
            self.service = build("drive", "v3", credentials=creds, cache_discovery=False)
            self.root_folder_id = self._get_or_create_folder(ROOT_FOLDER_NAME, None)
            self.subfolder_ids = {}
            for name in SUBFOLDERS:
                self.subfolder_ids[name] = self._get_or_create_folder(name, self.root_folder_id)
            self.user_email = self._fetch_user_email()
            return True
        except Exception as exc:
            fail(Stage.DRIVE_AUTH, "DRIVE_API_INIT_FAIL", "Не удалось инициализировать Drive API", str(exc))

    def _get_or_create_folder(self, folder_name: str, parent_id: Optional[str]) -> str:
        self._require_service()
        safe_name = folder_name.replace("'", "\\'")
        query = (
            f"name = '{safe_name}' and mimeType = 'application/vnd.google-apps.folder' "
            "and trashed = false"
        )
        if parent_id:
            query += f" and '{parent_id}' in parents"
        try:
            response = self.service.files().list(q=query, fields="files(id, name)", pageSize=5).execute()
        except Exception as exc:
            fail(Stage.DRIVE_FOLDER, "DRIVE_LIST_FAIL", f"Не удалось искать папку {folder_name}", str(exc))
        files = response.get("files") or []
        if files:
            folder_id = files[0].get("id")
            if not folder_id:
                fail(Stage.DRIVE_FOLDER, "DRIVE_FOLDER_ID_EMPTY", f"Папка {folder_name} без id")
            return folder_id
        meta = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
        if parent_id:
            meta["parents"] = [parent_id]
        try:
            created = self.service.files().create(body=meta, fields="id").execute()
        except Exception as exc:
            fail(Stage.DRIVE_FOLDER, "DRIVE_FOLDER_CREATE_FAIL", f"Не удалось создать папку {folder_name}", str(exc))
        folder_id = created.get("id")
        if not folder_id:
            fail(Stage.DRIVE_FOLDER, "DRIVE_CREATED_ID_EMPTY", f"Создана папка без id: {folder_name}")
        return folder_id

    def upload_file(
        self,
        local_path: str,
        drive_filename: Optional[str] = None,
        folder_key: str = "Music",
    ) -> str:
        self._require_service()
        self._require_local_file(local_path, "UPLOAD_SOURCE_MISSING")
        if folder_key not in self.subfolder_ids:
            fail(Stage.DRIVE_UPLOAD, "DRIVE_FOLDER_KEY_INVALID", "Неизвестная папка Drive", folder_key)
        parent_id = self.subfolder_ids[folder_key]
        if not parent_id:
            fail(Stage.DRIVE_UPLOAD, "DRIVE_PARENT_MISSING", "Не найден parent_id для загрузки", folder_key)

        filename = (drive_filename or os.path.basename(local_path)).strip()
        if not filename:
            fail(Stage.DRIVE_UPLOAD, "DRIVE_FILENAME_EMPTY", "Пустое имя файла на Drive")

        mime, _ = mimetypes.guess_type(local_path)
        if not mime:
            mime = "application/octet-stream"

        meta = {"name": filename, "parents": [parent_id]}
        media = MediaFileUpload(local_path, mimetype=mime, resumable=True)
        try:
            drive_file = self.service.files().create(body=meta, media_body=media, fields="id, name").execute()
        except Exception as exc:
            fail(
                Stage.DRIVE_UPLOAD,
                "DRIVE_UPLOAD_FAIL",
                f"Ошибка загрузки {filename} в {folder_key}",
                str(exc),
            )
        file_id = drive_file.get("id")
        if not file_id:
            fail(Stage.DRIVE_UPLOAD, "DRIVE_UPLOAD_ID_EMPTY", "Google Drive не вернул id файла", filename)
        return file_id

    def download_file(self, file_id: str, local_path: str) -> str:
        self._require_service()
        from googleapiclient.http import MediaIoBaseDownload
        import io
        request = self.service.files().get_media(fileId=file_id)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return local_path

    def list_files_in_folder(self, folder_key: str) -> list:
        self._require_service()
        if folder_key not in self.subfolder_ids:
            return []
        parent_id = self.subfolder_ids[folder_key]
        results = []
        page_token = None
        while True:
            resp = self.service.files().list(
                q=f"'{parent_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType, size)",
                pageSize=100,
                pageToken=page_token,
            ).execute()
            results.extend(resp.get("files", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return results

    def find_file_in_folder(self, folder_key: str, filename: str) -> Optional[str]:
        for item in self.list_files_in_folder(folder_key):
            if item.get("name") == filename:
                return item.get("id")
        return None

    def delete_file(self, file_id: str) -> bool:
        self._require_service()
        if not file_id:
            return False
        try:
            self.service.files().delete(fileId=file_id).execute()
            return True
        except Exception:
            return False

    def download_text(self, file_id: str) -> str:
        self._require_service()
        import io
        from googleapiclient.http import MediaIoBaseDownload
        request = self.service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue().decode("utf-8")

    def upload_json(self, data: dict, drive_filename: str, folder_key: str = "Meta") -> str:
        import json as _json
        os.makedirs(TEMP_DIR, exist_ok=True)
        local_path = os.path.join(TEMP_DIR, drive_filename)
        with open(local_path, "w", encoding="utf-8") as fh:
            _json.dump(data, fh, ensure_ascii=False, indent=2)
        file_id = self.upload_file(local_path, drive_filename=drive_filename, folder_key=folder_key)
        return file_id

    def update_file(self, file_id: str, local_path: str) -> str:
        self._require_service()
        self._require_local_file(local_path, "UPDATE_SOURCE_MISSING")
        mime, _ = mimetypes.guess_type(local_path)
        if not mime:
            mime = "application/octet-stream"
        media = MediaFileUpload(local_path, mimetype=mime, resumable=True)
        self.service.files().update(fileId=file_id, media_body=media).execute()
        return file_id

    def upload_text(self, text: str, drive_filename: str, folder_key: str = "Lyrics") -> str:
        if text is None or not str(text).strip():
            fail(Stage.DRIVE_UPLOAD, "LYRICS_TEXT_EMPTY", "Пустой текст для загрузки на Drive")
        os.makedirs(TEMP_DIR, exist_ok=True)
        local_path = os.path.join(TEMP_DIR, drive_filename)
        try:
            with open(local_path, "w", encoding="utf-8") as handle:
                handle.write(text.strip() + "\n")
        except OSError as exc:
            fail(Stage.FILE_IO, "LYRICS_WRITE_FAIL", "Не удалось записать lyrics во временный файл", str(exc))
        file_id = self.upload_file(local_path, drive_filename=drive_filename, folder_key=folder_key)
        return file_id
