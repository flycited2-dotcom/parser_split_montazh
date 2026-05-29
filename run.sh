#!/usr/bin/env bash
# Запуск парсера
set -euo pipefail

cd "$(dirname "$0")"

# Если нет .env — напоминаем
if [ ! -f .env ]; then
  echo "[run.sh] .env не найден. Скопируйте: cp .env.example .env"
  exit 1
fi

# Запускаем через xvfb-run (виртуальный дисплей, нужен на сервере без GUI)
if command -v xvfb-run &>/dev/null && [ "${HEADLESS:-1}" != "0" ]; then
  exec xvfb-run --auto-servernum --server-args="-screen 0 1366x768x24" \
    python main.py "$@"
else
  exec python main.py "$@"
fi
