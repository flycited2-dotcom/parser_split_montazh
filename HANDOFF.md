# HANDOFF — HVAC-парсер Крым

Документ для передачи контекста между сессиями. Прочитай целиком перед продолжением работы.

---

## Что это за проект

Парсер контактов HVAC-компаний (кондиционеры, сплит-системы, вентиляция, промхолод)
по всему Крыму. Сделан как клон архитектуры парсера отелей
(`flycited2-dotcom/hotels_sbor_baza`, директория `_extracted/crimea_parser`).

**Цель:** собрать базу контактов (телефон, email, сайт, соцсети, адрес, город)
компаний, которые продают/устанавливают/ремонтируют кондиционеры и вентиляцию.

**Типы компаний (client_type):** монтаж, продажа+монтаж, продажа, ремонт,
вентиляция, промхолод.

---

## Текущий статус (на 2026-05-29)

Код **полностью написан и работает**. Установка на сервере **не завершена** —
застряли на сетевом блокере (см. ниже).

### Что готово
- ✅ Весь код парсера (5 источников + утилиты + оркестратор)
- ✅ `.env.example` с прописанными токенами (TG бот, chat_id, Google Drive folder)
- ✅ `setup.sh` — скрипт развёртывания с нуля + отчёты в Telegram
- ✅ Запушено в ветку `claude/hvac-installer-parser-2JVb4`

### Где застряли
Установка на сервере sprintbox (`212.116.115.150`, Ubuntu 24.04, root).
Прогон `setup.sh` доходил до разных шагов и падал, последовательно чинили:
1. `libasound2` → переименован в `libasound2t64` на Ubuntu 24.04 — **исправлено**
2. `pip` не найден → автодетект pip3/python3 -m pip — **исправлено**
3. `set -euo pipefail` + ERR trap палили ложные ошибки — **убрано**
4. `pip install -r requirements.txt` падал (aiohttp требует компилятор C) →
   добавлены gcc/g++/python3-dev + `--prefer-binary` + установка по одному — **исправлено (последний коммит 9461069)**

**Последний прогон НЕ запускался после коммита 9461069.** Нужно, чтобы юзер
запустил `setup.sh` ещё раз и прислал результат из Telegram.

---

## ГЛАВНЫЙ БЛОКЕР: нельзя подключиться к серверу из этой среды

Проверено исчерпывающе (socket-тесты):
- Исходящий **порт 22 (SSH) заблокирован** к ЛЮБОМУ хосту (github.com:22,
  ssh.github.com:22, localhost.run:22 — все timeout).
- Исходящий **порт 443 (HTTPS) работает** везде.
- VNC websocket (`vnc.sprintbox.ru`) отдаёт `403 host_not_allowed` — пускает
  только IP браузера юзера.

**Вывод:** песочница Claude Code режет весь исходящий SSH. paramiko/ssh/туннель
через порт 22 — невозможны. Подключиться к серверу напрямую НЕЛЬЗЯ.
Не трать время на повторные попытки SSH — это тупик.

**Единственный путь установки:** юзер вставляет команду в VNC-консоль sprintbox
(вкладка «Консоль» в панели cp.sprintbox.ru), консоль доступна только из его браузера.

### Команда запуска установки (дать юзеру)
```bash
curl -s https://raw.githubusercontent.com/flycited2-dotcom/parser_split_montazh/claude/hvac-installer-parser-2JVb4/setup.sh | nohup bash > /tmp/hvac_setup.log 2>&1 &
```
Скрипт работает в фоне, шлёт прогресс в Telegram-группу «Парсер_Монтажников».

---

## Архитектура (структура файлов)

```
main.py                  — оркестратор: запускает источники по очереди,
                           merge, email finder, экспорт, Drive, Telegram
setup.sh                 — установка с нуля на сервере (apt, pip, playwright,
                           systemd-таймер, тест OSM, отчёты в Telegram)
run.sh                   — запуск парсера (через xvfb-run если есть)
deploy.sh                — rsync-деплой (не используется, есть setup.sh)
watchdog.sh              — перезапуск при зависании
setup_gdrive_auth.py     — одноразовая OAuth-авторизация Google Drive
requirements.txt         — playwright, openpyxl, python-dotenv, aiohttp, google-*
.env.example             — конфиг с токенами (копируется в .env)

parsers/
  osm.py            — OSM Overpass API: shop=air_conditioning, craft=hvac,
                      + name-фильтры (кондиционер|сплит|климат|вентиляц|холодильн).
                      HTTP-only, без браузера. Самый надёжный источник.
  vk_groups.py      — VK API: 14 запросов × 15 городов. Нужен VK_TOKEN.
                      Фильтрует нерелевантные группы по ключевым словам.
  yandex_maps.py    — Playwright: 8 запросов × 10 городов + 4 региональных.
  avito.py          — Playwright: установка/ремонт/продажа по 8 городам.
                      Риск IP-бана (как у отелей).
  search_engine.py  — Playwright: Яндекс+Bing → обход сайтов компаний.
  email_finder.py   — Playwright: добор email/phone/social с сайтов
                      (mailto/tel, JSON-LD, /contacts страницы).

utils/
  storage.py        — save_item, CSV-флаш, normalize_phone, cross_source_merge.
                      FIELDS = city,name,client_type,category,address,phone,
                      email,website,social,comment,source,parsed_at
  dedup.py          — SQLite persistent dedup (переживает рестарты), ключ (name,city)
  categories.py     — нормализация category → client_type (6 канонических типов)
  geo_city.py       — определение города Крыма по координатам (bbox)
  browser.py        — создание Playwright context (anti-detection, ru-RU)
  safe_browser.py   — SafeContext с авто-рекриейтом каждые 100 страниц (память)
  excel_export.py   — CSV→XLSX, листы по городам, цвета по типу, кликабельные ссылки
  merger.py         — объединяет все result_*.csv в master_all.csv + .xlsx
  gdrive.py         — загрузка на Google Drive (OAuth2 token.json)
  telegram_notify.py— отчёты в Telegram (summary, документы, checkpoints)
  progress.py       — состояние парсера в output/progress.json (атомарная запись)
```

### Поток данных в main.py
1. OSM → VK → Яндекс.Карты → Авито → краулер (от лёгких к тяжёлым)
2. cross_source_merge — обогащение записей между источниками
3. email_finder — добор контактов с сайтов
4. build_master_xlsx — единый CSV + XLSX
5. Google Drive upload
6. Telegram notify

### ENV-переменные (.env)
- `VK_TOKEN` — берётся с парсера отелей `/home/crimea_parser/.env` (setup.sh делает автоматически)
- `TG_BOT_TOKEN`, `TG_CHAT_ID` — прописаны в .env.example
- `GDRIVE_FOLDER_ID` — `1h5i0uPkmScGRKufGXEc1qu0pWyWioqax` (папка HVAC на Drive)
- `GDRIVE_TOKEN` — `/home/crimea_parser/token.json` (тот же что у отелей)
- `HEADLESS=1`, `ONLY_SOURCES=` (пусто=все), `SKIP_ENRICHMENT=0`

---

## Инфраструктура

- **Сервер:** sprintbox box-891610, `212.116.115.150`, СПб, Ubuntu 24.04,
  4 ядра / 6 GB RAM / 70 GB. На нём же крутится парсер отелей (`/home/crimea_parser`).
- **Целевая директория:** `/home/hvac_parser`
- **Telegram-группа отчётов:** «Парсер_Монтажников», chat_id `-1003554068532`
- **Расписание:** systemd-таймер, каждое воскресенье 04:00 (настраивает setup.sh)
- **Панель управления:** cp.sprintbox.ru (доступ только у юзера через браузер)

---

## Следующие шаги (для новой сессии)

1. Попроси юзера запустить команду установки (выше) в VNC-консоли и прислать
   результат из Telegram.
2. Если придёт ошибка — разбери текст (setup.sh шлёт конкретику: какой пакет/импорт
   упал), поправь, запушь, дай команду заново.
3. Когда установка пройдёт — попроси запустить полный прогон:
   ```bash
   nohup bash /home/hvac_parser/run.sh > /home/hvac_parser/output/parser.log 2>&1 &
   ```
4. Проверь качество данных по отчёту в Telegram (сколько записей, % с телефоном/email).
5. Возможные доработки после первого прогона:
   - подкрутить фильтры релевантности VK (как у отелей — отсеять мусор)
   - проверить не блокирует ли Авито (был бан у отелей)
   - расширить список городов/запросов если мало данных

## Важные ограничения среды
- НЕТ прямого доступа к серверу (SSH порт 22 заблокирован в песочнице).
- GitHub — только через MCP-инструменты (`mcp__github__*`) или git push в ветку.
- Работаем ТОЛЬКО в ветке `claude/hvac-installer-parser-2JVb4` обоих репозиториев.
- Репозиторий публичный — токены уже засвечены, юзер взял ответственность на себя.
