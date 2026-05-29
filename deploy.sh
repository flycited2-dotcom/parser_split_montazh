#!/usr/bin/env bash
# Деплой парсера на сервер
# Использование: ./deploy.sh user@server_ip
set -euo pipefail

SERVER="${1:-root@212.116.115.150}"
REMOTE_DIR="/home/hvac_parser"
REPO_DIR="$(dirname "$(realpath "$0")")"

echo "=== Деплой на $SERVER:$REMOTE_DIR ==="

# Синхронизируем файлы (без .env, output, __pycache__)
rsync -avz --delete \
  --exclude='.env' \
  --exclude='output/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.git/' \
  "$REPO_DIR/" "$SERVER:$REMOTE_DIR/"

# На сервере: устанавливаем зависимости
ssh "$SERVER" "cd $REMOTE_DIR && pip install -q -r requirements.txt && playwright install chromium"

echo "=== Деплой завершён ==="
echo "Настройка: скопируйте .env.example → .env и заполните переменные"
echo "Запуск: ssh $SERVER 'cd $REMOTE_DIR && ./run.sh'"
