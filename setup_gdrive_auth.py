"""Одноразовая авторизация Google Drive.

Использование:
  python setup_gdrive_auth.py client_secrets.json

Генерирует token.json — загрузите его на сервер по пути из .env GDRIVE_TOKEN.
"""

import sys
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main():
    if len(sys.argv) < 2:
        print("Использование: python setup_gdrive_auth.py client_secrets.json")
        sys.exit(1)

    secrets_file = sys.argv[1]
    output_file = "token.json"

    flow = InstalledAppFlow.from_client_secrets_file(secrets_file, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(output_file, "w") as f:
        f.write(creds.to_json())

    print(f"✅ Токен сохранён: {output_file}")
    print(f"Загрузите его на сервер: scp {output_file} user@server:/home/hvac_parser/token.json")


if __name__ == "__main__":
    main()
