#!/usr/bin/env bash
# Watchdog — перезапускает парсер если он завис или упал
set -euo pipefail

SCRIPT_DIR="$(dirname "$(realpath "$0")")"
LOG_FILE="$SCRIPT_DIR/output/parser.log"
PID_FILE="$SCRIPT_DIR/output/parser.pid"
MAX_RUNTIME_HOURS=8

mkdir -p "$SCRIPT_DIR/output"

echo "[watchdog] $(date '+%Y-%m-%d %H:%M') старт"

# Проверяем не запущен ли уже парсер
if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    RUNTIME=$(( ($(date +%s) - $(stat -c %Y "$PID_FILE")) / 3600 ))
    if [ "$RUNTIME" -lt "$MAX_RUNTIME_HOURS" ]; then
      echo "[watchdog] парсер уже работает (PID=$PID, ${RUNTIME}ч), пропуск"
      exit 0
    else
      echo "[watchdog] парсер завис (${RUNTIME}ч > ${MAX_RUNTIME_HOURS}ч), убиваем"
      kill "$PID" 2>/dev/null || true
      sleep 2
    fi
  fi
fi

# Запускаем парсер
cd "$SCRIPT_DIR"
echo "[watchdog] $(date '+%Y-%m-%d %H:%M') запуск парсера"
nohup bash run.sh >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
echo "[watchdog] PID=$(cat $PID_FILE)"
