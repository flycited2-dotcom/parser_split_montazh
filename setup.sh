#!/usr/bin/env bash
# =======================================================
#  HVAC-парсер Крым — полное развёртывание с нуля
#  Запуск в фоне:
#    curl -s https://raw.githubusercontent.com/flycited2-dotcom/parser_split_montazh/claude/hvac-installer-parser-2JVb4/setup.sh | nohup bash > /tmp/hvac_setup.log 2>&1 &
#    tail -f /tmp/hvac_setup.log
# =======================================================

PARSER_DIR="/home/hvac_parser"
REPO_URL="https://github.com/flycited2-dotcom/parser_split_montazh"
BRANCH="claude/hvac-installer-parser-2JVb4"
HOTELS_ENV="/home/crimea_parser/.env"
HOTELS_TOKEN="/home/crimea_parser/token.json"
SERVICE_NAME="hvac_parser"
LOG="/tmp/hvac_setup.log"

TG_BOT_TOKEN="8690586646:AAHnUuylar9uhYhHVuPt6Dt3mZiW7Zyweng"
TG_CHAT_ID="-1003554068532"

# ── Вывод в лог и на экран одновременно ──────────────
exec > >(tee -a "$LOG") 2>&1

set -euo pipefail
trap 'tg_send "❌ Установка упала на строке $LINENO. Смотри лог: $LOG"' ERR

# ── Telegram-уведомления ──────────────────────────────
tg_send() {
    curl -s -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${TG_CHAT_ID}" \
        --data-urlencode "text=$1" \
        --data-urlencode "parse_mode=HTML" \
        -o /dev/null || true
}

stamp() { date '+%Y-%m-%d %H:%M:%S'; }

echo ""
echo "======================================================"
echo "  HVAC-парсер Крым — развёртывание  $(stamp)"
echo "======================================================"
tg_send "🚀 <b>HVAC-парсер</b> — начало установки на сервере ($(stamp))"

# ── ШАГ 1: Системные пакеты ───────────────────────────
echo ""
echo "[1/8] Обновляем систему и устанавливаем пакеты..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    python3 python3-pip python3-venv \
    git curl wget \
    xvfb xauth \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 \
    ca-certificates fonts-liberation \
    2>/dev/null
echo "   ✓ системные пакеты установлены"
tg_send "✅ Шаг 1/8 — системные пакеты установлены"

# ── ШАГ 2: pip ────────────────────────────────────────
echo ""
echo "[2/8] Настраиваем pip..."
if command -v pip3 &>/dev/null; then
    PIP="pip3"
elif python3 -m pip --version &>/dev/null 2>&1; then
    PIP="python3 -m pip"
else
    curl -s https://bootstrap.pypa.io/get-pip.py | python3 -
    PIP="python3 -m pip"
fi
$PIP install -q --upgrade pip setuptools wheel
PYTHON="python3"
echo "   ✓ pip готов: $($PIP --version)"

# ── ШАГ 3: Код из GitHub ──────────────────────────────
echo ""
echo "[3/8] Клонируем репозиторий..."
mkdir -p "$PARSER_DIR"
cd "$PARSER_DIR"
if [ -d ".git" ]; then
    git fetch origin "$BRANCH"
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
    echo "   ✓ репозиторий обновлён"
else
    git clone --branch "$BRANCH" "$REPO_URL" .
    echo "   ✓ репозиторий склонирован"
fi
tg_send "✅ Шаг 3/8 — код получен из GitHub"

# ── ШАГ 4: .env ───────────────────────────────────────
echo ""
echo "[4/8] Создаём .env..."
cp .env.example .env

# VK_TOKEN из отелей
if [ -f "$HOTELS_ENV" ]; then
    VK_LINE=$(grep "^VK_TOKEN=" "$HOTELS_ENV" 2>/dev/null || true)
    [ -n "$VK_LINE" ] && sed -i "s|^VK_TOKEN=.*|$VK_LINE|" .env \
        && echo "   ✓ VK_TOKEN — взят из парсера отелей"
else
    echo "   ⚠ VK_TOKEN — заполни вручную в $PARSER_DIR/.env"
fi

# GDRIVE_TOKEN из отелей
if [ -f "$HOTELS_TOKEN" ]; then
    sed -i "s|^GDRIVE_TOKEN=.*|GDRIVE_TOKEN=$HOTELS_TOKEN|" .env
    echo "   ✓ GDRIVE_TOKEN → $HOTELS_TOKEN"
fi

echo "   .env:"
grep -v "^#" .env | grep -v "^$" | sed 's/\(TOKEN=\).\{8\}.*/\1***/'

# ── ШАГ 5: Python-зависимости ─────────────────────────
echo ""
echo "[5/8] Устанавливаем Python-пакеты..."
$PIP install -q -r requirements.txt
echo "   ✓ requirements.txt установлен"
tg_send "✅ Шаг 5/8 — Python-зависимости установлены"

# ── ШАГ 6: Playwright + Chromium ──────────────────────
echo ""
echo "[6/8] Устанавливаем Playwright + Chromium (долго, ~5 мин)..."
tg_send "⏳ Шаг 6/8 — скачиваем Chromium (~5 мин)..."
$PYTHON -m playwright install chromium
$PYTHON -m playwright install-deps chromium 2>/dev/null || true
echo "   ✓ Chromium установлен"
tg_send "✅ Шаг 6/8 — Chromium установлен"

# ── ШАГ 7: systemd таймер ─────────────────────────────
echo ""
echo "[7/8] Настраиваем systemd таймер (воскресенье 04:00)..."

cat > /etc/systemd/system/${SERVICE_NAME}.service << UNIT
[Unit]
Description=HVAC Parser Crimea
After=network.target

[Service]
Type=oneshot
User=root
WorkingDirectory=${PARSER_DIR}
EnvironmentFile=${PARSER_DIR}/.env
ExecStart=/usr/bin/bash ${PARSER_DIR}/run.sh
StandardOutput=append:${PARSER_DIR}/output/parser.log
StandardError=append:${PARSER_DIR}/output/parser.log
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
NEXT=$(systemctl list-timers ${SERVICE_NAME}.timer --no-pager | grep ${SERVICE_NAME} | awk '{print $1, $2}')
echo "   ✓ таймер активен. Следующий запуск: $NEXT"

# ── ШАГ 8: Тест-прогон OSM + Telegram ────────────────
echo ""
echo "[8/8] Тест-прогон (OSM, без браузера)..."
tg_send "⏳ Шаг 8/8 — тестовый прогон OSM..."
mkdir -p output

set +e
ONLY_SOURCES=osm SKIP_ENRICHMENT=1 $PYTHON main.py 2>&1 | tee /tmp/hvac_osm_test.log | tail -30
OSM_EXIT=${PIPESTATUS[0]}
set -e

# Считаем сколько записей добавлено
ADDED=$(grep -c "✓ \[OSM\]" /tmp/hvac_osm_test.log 2>/dev/null || echo "0")

# ── Финальное сообщение ───────────────────────────────
echo ""
echo "======================================================"
if [ "$OSM_EXIT" -eq 0 ]; then
    echo "  ✅ Установка завершена успешно!  $(stamp)"
    MSG="✅ <b>HVAC-парсер Крым установлен!</b>

📍 Сервер: $(hostname)
📁 Директория: ${PARSER_DIR}
🗓 Расписание: каждое воскресенье 04:00

🧪 Тест OSM: найдено <b>${ADDED}</b> HVAC-компаний

▶️ Полный запуск:
<code>nohup bash ${PARSER_DIR}/run.sh &gt; ${PARSER_DIR}/output/parser.log 2&gt;&amp;1 &amp;</code>

📋 Логи:
<code>tail -f ${PARSER_DIR}/output/parser.log</code>"
else
    echo "  ⚠ Установка завершена, но тест-прогон вернул ошибку (код $OSM_EXIT)"
    MSG="⚠️ <b>HVAC-парсер установлен</b>, но тест-прогон OSM завершился с ошибкой (код ${OSM_EXIT}).
Проверь лог: <code>cat /tmp/hvac_osm_test.log</code>"
fi
echo "======================================================"
echo ""
echo "  Запуск:  nohup bash ${PARSER_DIR}/run.sh > ${PARSER_DIR}/output/parser.log 2>&1 &"
echo "  Логи:    tail -f ${PARSER_DIR}/output/parser.log"
echo "======================================================"

tg_send "$MSG"
