#!/usr/bin/env bash
# =======================================================
#  HVAC-парсер Крым — полное развёртывание с нуля
#  Запуск в фоне (не падает при дисконнекте):
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

# Без set -e и без ERR-trap — управляем ошибками вручную
exec > >(tee -a "$LOG") 2>&1

tg_send() {
    local text="$1"
    curl -s -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${TG_CHAT_ID}" \
        --data-urlencode "text=${text}" \
        --data-urlencode "parse_mode=HTML" \
        -o /dev/null 2>/dev/null
    return 0
}

die() {
    echo ""
    echo "!!! КРИТИЧЕСКАЯ ОШИБКА: $1"
    tg_send "❌ <b>Установка упала:</b> $1&#10;Лог: <code>cat $LOG</code>"
    exit 1
}

stamp() { date '+%Y-%m-%d %H:%M:%S'; }

echo ""
echo "======================================================"
echo "  HVAC-парсер Крым — развёртывание  $(stamp)"
echo "======================================================"
tg_send "🚀 <b>HVAC-парсер</b> — начало установки ($(stamp))"

# ════════════════════════════════════════════════════
# ШАГ 1: Системные пакеты
# ════════════════════════════════════════════════════
echo ""
echo "[1/8] Обновляем систему и устанавливаем пакеты..."
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq 2>/dev/null || true
apt-get upgrade -y -qq 2>/dev/null || true

# Обязательные — без них дальше не идём
apt-get install -y -qq python3 git curl wget ca-certificates 2>/dev/null \
    || die "Не удалось установить базовые пакеты (python3 git curl)"

# Опциональные — пропускаем если нет
for pkg in python3-pip python3-venv xvfb xauth \
           libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
           libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
           libgbm1 libpango-1.0-0 libcairo2 fonts-liberation; do
    apt-get install -y -qq "$pkg" 2>/dev/null \
        && echo "   ✓ $pkg" \
        || echo "   ⚠ $pkg — пропуск"
done

# libasound2 — Ubuntu 24.04 переименовал его
apt-get install -y -qq libasound2t64 2>/dev/null \
    || apt-get install -y -qq libasound2 2>/dev/null \
    || echo "   ⚠ libasound2 — пропуск"

echo "   ✓ системные пакеты готовы"
tg_send "✅ Шаг 1/8 — системные пакеты установлены"

# ════════════════════════════════════════════════════
# ШАГ 2: pip
# ════════════════════════════════════════════════════
echo ""
echo "[2/8] Настраиваем pip..."

if command -v pip3 &>/dev/null; then
    PIP="pip3"
elif python3 -m pip --version &>/dev/null 2>&1; then
    PIP="python3 -m pip"
else
    echo "   pip не найден, скачиваем get-pip.py..."
    curl -s https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py \
        && python3 /tmp/get-pip.py -q \
        || die "Не удалось установить pip"
    PIP="python3 -m pip"
fi

$PIP install -q --upgrade pip setuptools wheel 2>/dev/null || true
PYTHON="python3"
echo "   ✓ $($PIP --version 2>/dev/null || echo 'pip OK')"

# ════════════════════════════════════════════════════
# ШАГ 3: Код
# ════════════════════════════════════════════════════
echo ""
echo "[3/8] Клонируем репозиторий..."
mkdir -p "$PARSER_DIR"
cd "$PARSER_DIR" || die "Не могу войти в $PARSER_DIR"

if [ -d ".git" ]; then
    git fetch origin "$BRANCH" 2>/dev/null && \
    git checkout "$BRANCH" 2>/dev/null && \
    git pull origin "$BRANCH" 2>/dev/null \
        && echo "   ✓ репозиторий обновлён" \
        || die "git pull не прошёл"
else
    git clone --branch "$BRANCH" "$REPO_URL" . \
        || die "git clone не прошёл"
    echo "   ✓ репозиторий склонирован"
fi
tg_send "✅ Шаг 3/8 — код получен из GitHub"

# ════════════════════════════════════════════════════
# ШАГ 4: .env
# ════════════════════════════════════════════════════
echo ""
echo "[4/8] Создаём .env..."
cp .env.example .env

if [ -f "$HOTELS_ENV" ]; then
    VK_LINE=$(grep "^VK_TOKEN=" "$HOTELS_ENV" 2>/dev/null || true)
    if [ -n "$VK_LINE" ]; then
        sed -i "s|^VK_TOKEN=.*|${VK_LINE}|" .env
        echo "   ✓ VK_TOKEN взят из $HOTELS_ENV"
    fi
else
    echo "   ⚠ $HOTELS_ENV не найден — VK_TOKEN пуст"
fi

if [ -f "$HOTELS_TOKEN" ]; then
    sed -i "s|^GDRIVE_TOKEN=.*|GDRIVE_TOKEN=${HOTELS_TOKEN}|" .env
    echo "   ✓ GDRIVE_TOKEN → $HOTELS_TOKEN"
fi

echo "   .env содержимое:"
grep -v "^#" .env | grep -v "^$" | sed 's/\(TOKEN=\).\{8\}.*/\1***/' || true
tg_send "✅ Шаг 4/8 — .env настроен"

# ════════════════════════════════════════════════════
# ШАГ 5: Python-зависимости
# ════════════════════════════════════════════════════
echo ""
echo "[5/8] Устанавливаем Python-пакеты..."
$PIP install -q -r requirements.txt \
    || die "pip install -r requirements.txt не прошёл"
echo "   ✓ requirements.txt установлен"
tg_send "✅ Шаг 5/8 — Python-зависимости установлены"

# ════════════════════════════════════════════════════
# ШАГ 6: Playwright + Chromium
# ════════════════════════════════════════════════════
echo ""
echo "[6/8] Устанавливаем Playwright + Chromium (~5 мин)..."
tg_send "⏳ Шаг 6/8 — скачиваем Chromium..."

$PYTHON -m playwright install chromium 2>&1 \
    || die "playwright install chromium не прошёл"
$PYTHON -m playwright install-deps chromium 2>/dev/null || true

echo "   ✓ Chromium установлен"
tg_send "✅ Шаг 6/8 — Chromium установлен"

# ════════════════════════════════════════════════════
# ШАГ 7: systemd таймер
# ════════════════════════════════════════════════════
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

systemctl daemon-reload 2>/dev/null || true
systemctl enable ${SERVICE_NAME}.timer 2>/dev/null || true
systemctl start ${SERVICE_NAME}.timer 2>/dev/null || true
echo "   ✓ таймер настроен"

# ════════════════════════════════════════════════════
# ШАГ 8: Диагностика + тест OSM
# ════════════════════════════════════════════════════
echo ""
echo "[8/8] Проверяем импорты и запускаем тест OSM..."
tg_send "⏳ Шаг 8/8 — тестовый прогон OSM..."
mkdir -p output

# Сначала проверяем импорты
echo "   Проверка импортов Python..."
IMPORT_ERR=$($PYTHON -c "
import sys, os
sys.path.insert(0, '.')
os.chdir('${PARSER_DIR}')
errors = []
mods = ['utils.storage','utils.dedup','utils.categories',
        'utils.geo_city','utils.progress','parsers.osm',
        'parsers.vk_groups','parsers.yandex_maps']
for m in mods:
    try:
        __import__(m)
    except Exception as e:
        errors.append(f'{m}: {e}')
if errors:
    print('\n'.join(errors))
    sys.exit(1)
print('OK')
" 2>&1)

if echo "$IMPORT_ERR" | grep -q "OK"; then
    echo "   ✓ все импорты в порядке"
else
    echo "   ✗ ошибки импорта:"
    echo "$IMPORT_ERR"
    tg_send "⚠️ Ошибки импорта Python:&#10;<code>${IMPORT_ERR}</code>"
fi

# Тест-прогон OSM
OSM_OUTPUT=$( cd "$PARSER_DIR" && ONLY_SOURCES=osm SKIP_ENRICHMENT=1 $PYTHON main.py 2>&1 )
OSM_EXIT=$?
echo "$OSM_OUTPUT" | tee /tmp/hvac_osm_test.log | tail -30

ADDED=$(echo "$OSM_OUTPUT" | grep -c "✓ \[OSM\]" 2>/dev/null || echo "0")

echo ""
echo "======================================================"
if [ "$OSM_EXIT" -eq 0 ]; then
    echo "  ✅ Установка завершена!  $(stamp)"
    tg_send "✅ <b>HVAC-парсер Крым установлен!</b>

📍 Сервер: $(hostname)
🗓 Расписание: каждое воскресенье 04:00
🧪 Тест OSM: найдено <b>${ADDED}</b> HVAC-компаний

▶️ Запустить сейчас:
<code>nohup bash ${PARSER_DIR}/run.sh &gt; ${PARSER_DIR}/output/parser.log 2&gt;&amp;1 &amp;</code>

📋 Логи:
<code>tail -f ${PARSER_DIR}/output/parser.log</code>"
else
    LAST_LINES=$(echo "$OSM_OUTPUT" | tail -10)
    echo "  ⚠ Тест OSM вернул ошибку (код $OSM_EXIT)"
    tg_send "⚠️ <b>Парсер установлен</b>, но тест-прогон OSM не прошёл (код ${OSM_EXIT}).

Последние строки лога:
<code>${LAST_LINES}</code>

Запустить диагностику:
<code>cd ${PARSER_DIR} &amp;&amp; python3 main.py 2&gt;&amp;1 | head -30</code>"
fi
echo "======================================================"
echo "  Запуск:  nohup bash ${PARSER_DIR}/run.sh > ${PARSER_DIR}/output/parser.log 2>&1 &"
echo "  Логи:    tail -f ${PARSER_DIR}/output/parser.log"
echo "======================================================"
