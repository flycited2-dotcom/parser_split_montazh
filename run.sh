#!/usr/bin/env bash
# Запуск парсера
set -euo pipefail

cd "$(dirname "$0")"

# Если нет .env — напоминаем
if [ ! -f .env ]; then
  echo "[run.sh] .env не найден. Скопируйте: cp .env.example .env"
  exit 1
fi

# venv-питон если есть, иначе системный python3
if [ -x "venv/bin/python" ]; then
  PY="venv/bin/python"
else
  PY="python3"
fi

# Запускаем через xvfb-run (виртуальный дисплей, нужен на сервере без GUI)
if command -v xvfb-run &>/dev/null && [ "${HEADLESS:-1}" != "0" ]; then
  exec xvfb-run --auto-servernum --server-args="-screen 0 1366x768x24" \
    "$PY" main.py "$@"
else
  exec "$PY" main.py "$@"
fi
