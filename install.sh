#!/usr/bin/env bash
# Полная установка HVAC-парсера на сервере
# Запуск: bash install.sh
# Устойчив к дисконнектам — все тяжёлые операции идут в фоне с логом

PARSER_DIR="/home/hvac_parser"
REPO_URL="https://github.com/flycited2-dotcom/parser_split_montazh"
BRANCH="claude/hvac-installer-parser-2JVb4"
HOTELS_ENV="/home/crimea_parser/.env"
HOTELS_TOKEN="/home/crimea_parser/token.json"
SERVICE_NAME="hvac_parser"
LOG="/tmp/hvac_install.log"

# ── pip: ищем рабочую команду ────────────────────
if command -v pip3 &>/dev/null; then
    PIP="pip3"
elif command -v pip &>/dev/null; then
    PIP="pip"
elif python3 -m pip --version &>/dev/null 2>&1; then
    PIP="python3 -m pip"
else
    echo "[!] pip не найден, устанавливаем..."
    curl -s https://bootstrap.pypa.io/get-pip.py | python3
    PIP="python3 -m pip"
fi

# ── python: ищем рабочую команду ─────────────────
if command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    PYTHON="python"
fi

echo "=============================================="
echo " HVAC-парсер Крым — установка"
echo " Лог: $LOG"
echo "=============================================="

exec > >(tee -a "$LOG") 2>&1

set -euo pipefail

# ── 1. Директория ────────────────────────────────
echo ""
echo "[1/7] Создаём директорию $PARSER_DIR..."
mkdir -p "$PARSER_DIR"
cd "$PARSER_DIR"

# ── 2. Код из GitHub ─────────────────────────────
echo ""
echo "[2/7] Получаем код из GitHub..."
if [ -d ".git" ]; then
    git fetch origin "$BRANCH"
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
else
    git clone --branch "$BRANCH" "$REPO_URL" .
fi

# ── 3. .env ──────────────────────────────────────
echo ""
echo "[3/7] Настраиваем .env..."
cp .env.example .env

if [ -f "$HOTELS_ENV" ]; then
    VK_LINE=$(grep "^VK_TOKEN=" "$HOTELS_ENV" 2>/dev/null || true)
    [ -n "$VK_LINE" ] && sed -i "s|^VK_TOKEN=.*|$VK_LINE|" .env \
        && echo "   ✓ VK_TOKEN взят из $HOTELS_ENV"
fi

if [ -f "$HOTELS_TOKEN" ]; then
    sed -i "s|^GDRIVE_TOKEN=.*|GDRIVE_TOKEN=$HOTELS_TOKEN|" .env
    echo "   ✓ GDRIVE_TOKEN → $HOTELS_TOKEN"
fi

echo "   .env готов:"
grep -v "^#" .env | grep -v "^$" | sed 's/\(TOKEN=\).\{8\}.*/\1***/'

# ── 4. Python-зависимости ────────────────────────
echo ""
echo "[4/7] Устанавливаем Python-зависимости (pip: $PIP)..."
$PIP install -q -r requirements.txt
echo "   ✓ зависимости установлены"

# ── 5. Playwright + Chromium ─────────────────────
echo ""
echo "[5/7] Устанавливаем Playwright + Chromium..."
$PYTHON -m playwright install chromium
$PYTHON -m playwright install-deps chromium 2>/dev/null || true
echo "   ✓ Chromium установлен"

# ── 6. systemd таймер ────────────────────────────
echo ""
echo "[6/7] Настраиваем systemd таймер (каждое воскресенье 04:00)..."

cat > /etc/systemd/system/${SERVICE_NAME}.service << UNIT
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

cat > /etc/systemd/system/${SERVICE_NAME}.timer << TIMER
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
echo "   ✓ Таймер активирован"

# ── 7. Тест-прогон OSM (без браузера, ~30с) ──────
echo ""
echo "[7/7] Тест-прогон OSM (без браузера)..."
mkdir -p output
ONLY_SOURCES=osm SKIP_ENRICHMENT=1 $PYTHON main.py 2>&1 | tail -25

echo ""
echo "=============================================="
echo " ✅ Установка завершена!"
echo "=============================================="
echo ""
echo " Полный запуск:    nohup bash /home/hvac_parser/run.sh > /home/hvac_parser/output/parser.log 2>&1 &"
echo " Логи установки:   cat $LOG"
echo " Логи парсера:     tail -f /home/hvac_parser/output/parser.log"
echo " Статус таймера:   systemctl status hvac_parser.timer"
echo ""
