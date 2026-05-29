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

## Текущий статус (на 2026-05-29, обновлено)

Код **полностью написан**. Установка на сервере **ЗАВЕРШЕНА и проверена**.

### Что готово
- ✅ Весь код парсера (5 источников + утилиты + оркестратор)
- ✅ `.env` на сервере настроен (VK_TOKEN из отелей, TG, GDRIVE_TOKEN/FOLDER)
- ✅ `setup.sh` переведён на **venv** (см. ниже), `install.sh` удалён как ловушка
- ✅ Сервер развёрнут: venv `/home/hvac_parser/venv`, зависимости установлены,
  Playwright Chromium 1223 (headless + headed под xvfb проверены)
- ✅ systemd-таймер `hvac_parser.timer` активен — каждое воскресенье 04:00
- ✅ Сквозная проверка: тест VK дал **~1490 записей** → XLSX (17 листов) →
  Google Drive → Telegram. Весь пайплайн работает.
- ✅ Запушено в `claude/hvac-installer-parser-2JVb4` (коммит 5d3a681)

### Корневой блокер установки (РЕШЁН)
Ubuntu 24.04 включает **PEP 668 (externally-managed-environment)** — системный
`pip install` молча блокируется. Старый `setup.sh`/`install.sh` ставили пакеты
системно и из-за этого НИЧЕГО не доставляли (ошибки глушились `2>/dev/null`),
хотя таймер создавался — отсюда иллюзия «почти установлено».
**Фикс:** всё ставится в venv (как у рабочего парсера отелей). См. коммит 5d3a681.

---

## Доступ к серверу: SSH РАБОТАЕТ (прежний блокер устарел)

⚠️ Прежняя версия этого документа утверждала, что SSH (порт 22) заблокирован в
песочнице и установка возможна только через VNC-консоль. **Это больше не так.**

Из текущей среды **прямой SSH к серверу работает**:
```bash
ssh -i ~/.ssh/climat_simf_deploy root@212.116.115.150
```
Ключ `~/.ssh/climat_simf_deploy` авторизован на сервере (root). Порт 22 открыт
и к серверу, и к github.com. Можно ставить/чинить/гонять парсер напрямую —
VNC-консоль больше не нужна.

### Команда переустановки с нуля (если понадобится)
```bash
curl -s https://raw.githubusercontent.com/flycited2-dotcom/parser_split_montazh/claude/hvac-installer-parser-2JVb4/setup.sh | nohup bash > /tmp/hvac_setup.log 2>&1 &
```
Теперь `setup.sh` создаёт venv корректно. Прогресс шлётся в Telegram-группу
«Парсер_Монтажников».

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

Установка готова. Дальше — качество данных и тюнинг:

1. Запустить полный прогон (все источники) и проверить отчёт в Telegram:
   ```bash
   ssh -i ~/.ssh/climat_simf_deploy root@212.116.115.150 \
     'cd /home/hvac_parser && nohup bash run.sh > output/parser.log 2>&1 &'
   ```
   (или просто дождаться воскресного таймера 04:00). Полный прогон — часы.
2. Известные находки/доработки:
   - **OSM даёт ~0**: в Крыму почти нет тегов `shop=air_conditioning`, а
     name-regex по всему bbox упирается в timeout Overpass (~7.5 мин впустую
     в начале прогона). Стоит ускорить/упростить запрос или резко снизить
     read-timeout, т.к. источник всё равно почти пустой. Реальные данные — VK.
   - **VK пропускает мусор**: в выдачу лезут гостевые дома/«Отдых в Крыму» и
     города вне Крыма (Москва, Воронеж, Краснодар). Подкрутить фильтры
     релевантности (`parsers/vk_groups.py`, RELEVANCE_KEYWORDS / гео-привязка).
   - **Категории VK не нормализованы**: встречаются «Публичная страница»,
     «Бытовая техника», «прочее» вместо 6 канонических client_type — проверить
     маппинг через `utils/categories.py`.
   - Проверить, не блокирует ли Авито (был бан у отелей).

## Важные ограничения среды
- **SSH к серверу РАБОТАЕТ** через `~/.ssh/climat_simf_deploy` (root@212.116.115.150).
  Можно ставить/чинить/гонять напрямую. (Прежнее «порт 22 заблокирован» устарело.)
- GitHub — git push в ветку (или MCP `mcp__github__*`).
- Работаем в ветке `claude/hvac-installer-parser-2JVb4` (deployment, с неё
  сервер делает git pull). Рабочая worktree-ветка fast-forward'ится в неё.
- Репозиторий публичный — токены уже засвечены, юзер взял ответственность на себя.
