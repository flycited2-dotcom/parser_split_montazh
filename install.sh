#!/usr/bin/env bash
# Полная установка HVAC-парсера на сервере
# Запуск: bash install.sh
set -euo pipefail

PARSER_DIR="/home/hvac_parser"
REPO_URL="https://github.com/flycited2-dotcom/parser_split_montazh"
BRANCH="claude/hvac-installer-parser-2JVb4"
HOTELS_ENV="/home/crimea_parser/.env"
HOTELS_TOKEN="/home/crimea_parser/token.json"
SERVICE_NAME="hvac_parser"

echo "=============================================="
echo " HVAC-парсер Крым — установка"
echo "=============================================="

# ── 1. Создаём директорию ────────────────────────
echo ""
echo "[1/7] Создаём директорию $PARSER_DIR..."
mkdir -p "$PARSER_DIR"
cd "$PARSER_DIR"

# ── 2. Клонируем / обновляем репозиторий ─────────
echo ""
echo "[2/7] Получаем код из GitHub..."
if [ -d ".git" ]; then
    git fetch origin "$BRANCH"
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
else
    git clone --branch "$BRANCH" "$REPO_URL" .
fi

# ── 3. Создаём .env ──────────────────────────────
echo ""
echo "[3/7] Настраиваем .env..."
cp .env.example .env

# Берём VK_TOKEN из парсера отелей
if [ -f "$HOTELS_ENV" ]; then
    VK_LINE=$(grep "^VK_TOKEN=" "$HOTELS_ENV" 2>/dev/null || echo "")
    if [ -n "$VK_LINE" ]; then
        sed -i "s|^VK_TOKEN=.*|$VK_LINE|" .env
        echo "   ✓ VK_TOKEN взят из $HOTELS_ENV"
    else
        echo "   ⚠ VK_TOKEN не найден в $HOTELS_ENV — заполни вручную"
    fi
else
    echo "   ⚠ $HOTELS_ENV не найден — VK_TOKEN заполни вручную"
fi

# Путь к Google Drive токену — берём от отелей если существует
if [ -f "$HOTELS_TOKEN" ]; then
    sed -i "s|^GDRIVE_TOKEN=.*|GDRIVE_TOKEN=$HOTELS_TOKEN|" .env
    echo "   ✓ GDRIVE_TOKEN → $HOTELS_TOKEN"
fi

echo "   .env готов:"
grep -v "^#" .env | grep -v "^$" | sed 's/\(TOKEN=\).\{10\}.*/\1***скрыто***/'

# ── 4. Python-зависимости ────────────────────────
echo ""
echo "[4/7] Устанавливаем Python-зависимости..."
pip install -q -r requirements.txt
echo "   ✓ pip install завершён"

# ── 5. Playwright + Chromium ─────────────────────
echo ""
echo "[5/7] Устанавливаем Playwright + Chromium..."
playwright install chromium
playwright install-deps chromium 2>/dev/null || true
echo "   ✓ Chromium установлен"

# ── 6. systemd-сервис (запуск по воскресеньям 04:00) ─
echo ""
echo "[6/7] Настраиваем systemd таймер..."

cat > /etc/systemd/system/${SERVICE_NAME}.service << 'UNIT'
[Unit]
Description=HVAC Parser Crimea
After=network.target

[Service]
Type=oneshot
User=root
WorkingDirectory=/home/hvac_parser
EnvironmentFile=/home/hvac_parser/.env
ExecStart=/usr/bin/bash /home/hvac_parser/run.sh
StandardOutput=append:/home/hvac_parser/output/parser.log
StandardError=append:/home/hvac_parser/output/parser.log
TimeoutStartSec=28800

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/${SERVICE_NAME}.timer << 'TIMER'
[Unit]
Description=HVAC Parser Crimea — еженедельный запуск

[Timer]
OnCalendar=Sun *-*-* 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
TIMER

systemctl daemon-reload
systemctl enable ${SERVICE_NAME}.timer
systemctl start ${SERVICE_NAME}.timer
echo "   ✓ Таймер активирован (каждое воскресенье 04:00)"

# ── 7. Тест-запуск (только OSM, без браузера) ────
echo ""
echo "[7/7] Тест-прогон (только OSM, ~30 секунд)..."
mkdir -p output
ONLY_SOURCES=osm SKIP_ENRICHMENT=1 python main.py 2>&1 | tail -20

echo ""
echo "=============================================="
echo " ✅ Установка завершена!"
echo "=============================================="
echo ""
echo " Запуск вручную:   bash /home/hvac_parser/run.sh"
echo " Логи:             tail -f /home/hvac_parser/output/parser.log"
echo " Статус таймера:   systemctl status hvac_parser.timer"
echo " Следующий запуск: systemctl list-timers hvac_parser.timer"
echo ""
