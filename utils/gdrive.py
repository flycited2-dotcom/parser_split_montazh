"""Загрузка файлов на Google Drive через OAuth2.

Обязательные env-переменные:
  GDRIVE_FOLDER_ID — ID папки Drive (последняя часть URL папки)
  GDRIVE_TOKEN     — путь к token.json (по умолчанию /home/hvac_parser/token.json)

Настройка один раз:
  1. В Google Cloud Console включить Drive API.
  2. Создать OAuth2 Client ID (Desktop), скачать client_secrets.json.
  3. Запустить: python setup_gdrive_auth.py client_secrets.json
  4. Загрузить token.json на сервер по пути GDRIVE_TOKEN.
  5. Прописать GDRIVE_FOLDER_ID в .env.
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_TOKEN = "/home/hvac_parser/token.json"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _get_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    token_path = os.getenv("GDRIVE_TOKEN", _DEFAULT_TOKEN)

    if not os.path.exists(token_path):
        raise FileNotFoundError(
            f"[gdrive] token.json не найден: {token_path}. "
            "Запустите setup_gdrive_auth.py для авторизации."
        )

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w") as f:
                f.write(creds.to_json())
        else:
            raise RuntimeError(
                "[gdrive] токен истёк. Повторно запустите setup_gdrive_auth.py."
            )

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def upload_file(local_path: str, folder_id: str | None = None) -> str | None:
    """Загружает файл на Google Drive. Возвращает web-ссылку или None."""
    folder_id = folder_id or os.getenv("GDRIVE_FOLDER_ID", "")

    if not folder_id:
        print("[gdrive] GDRIVE_FOLDER_ID не задан — пропускаем загрузку")
        return None

    try:
        from googleapiclient.http import MediaFileUpload

        service = _get_service()
        file_name = Path(local_path).name

        if local_path.endswith(".xlsx"):
            mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            mime = "text/csv"

        existing = (
            service.files()
            .list(
                q=f"name='{file_name}' and '{folder_id}' in parents and trashed=false",
                fields="files(id)",
            )
            .execute()
            .get("files", [])
        )

        media = MediaFileUpload(local_path, mimetype=mime, resumable=True)

        if existing:
            file_id = existing[0]["id"]
            service.files().update(fileId=file_id, media_body=media).execute()
        else:
            meta = {"name": file_name, "parents": [folder_id]}
            result = service.files().create(
                body=meta, media_body=media, fields="id"
            ).execute()
            file_id = result["id"]

        link = f"https://drive.google.com/file/d/{file_id}/view"
        print(f"[gdrive] загружен: {file_name} → {link}")
        return link

    except Exception as e:
        print(f"[gdrive] ошибка загрузки {local_path}: {e}")
        return None
