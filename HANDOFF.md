# HANDOFF — HVAC-парсер (Крым + Запорожская + Херсонская обл.)

Документ для передачи контекста между сессиями. Прочитай целиком перед продолжением работы.

---

## Что это за проект

Парсер контактов HVAC-компаний (кондиционеры, сплит-системы, вентиляция, промхолод)
по югу — **Крым + материковая часть Запорожской и Херсонской областей**.
Сделан как клон архитектуры парсера отелей
(`flycited2-dotcom/hotels_sbor_baza`, директория `_extracted/crimea_parser`).
Имя проекта осталось «HVAC-парсер Крым», но география шире — см. ниже.

**Цель:** собрать базу контактов (телефон, email, сайт, соцсети, адрес, город)
компаний, которые продают/устанавливают/ремонтируют кондиционеры и вентиляцию.

**Типы компаний (client_type):** монтаж, продажа+монтаж, продажа, ремонт,
вентиляция, промхолод.

---

## Текущий статус (на 2026-05-30)

Код написан и доработан. Установка завершена. На сервере крутятся **два сервиса**:
парсер (по таймеру) и Telegram-бот (всегда-онлайн, командное меню в группе).

### Что готово
- ✅ Установка: venv `/home/hvac_parser/venv`, Playwright Chromium 1223
  (headless+headed под xvfb проверены), `setup.sh` под venv,
  устаревший `install.sh` удалён.
- ✅ systemd-таймер `hvac_parser.timer` активен — каждое воскресенье 04:00.
- ✅ systemd-сервис `hvac_bot.service` — long-poll Telegram-бот, **Restart=always**,
  команды через `setMyCommands` видны у поля ввода в группе.
- ✅ Качество данных: централ. отсев отелей (`utils/categories.is_hotel_junk`),
  гео-фильтр по Крым+Запорожье+Херсон (`vk_groups._is_target_region`),
  нормализация category→client_type (6 канонических), фикс багов
  (`TimeoutError` в OSM, `SyntaxWarning` в excel_export).
- ✅ Источники: VK работает (API), **Яндекс.Карты ожили** (обновил устаревшие
  селекторы — `.search-business-snippet-view__title`, `.card-phones-view__phone`,
  `.business-contacts-view__address`, `.business-urls-view__link`).
- ✅ География: ~85 точек по списку пользователя (Крым города/районы/посёлки
  + Запорожская обл. + Херсонская обл.). OSM bbox расширен на север до 48.0.
- ✅ Ключевые фразы: установка/чистка/обслуживание/срочный монтаж/монтаж сегодня
  добавлены во все источники.
- ✅ Сквозная проверка: первый чистый прогон VK дал ~1023 записи, отельный
  мусор 0/1480 (был 467/1480 ≈ 32%), все 6 client_type канонические.

### Корневой блокер установки (РЕШЁН)
Ubuntu 24.04 включает **PEP 668 (externally-managed-environment)** — системный
`pip install` молча блокируется. Старый `setup.sh`/`install.sh` ставили пакеты
системно и из-за этого НИЧЕГО не доставляли (ошибки глушились `2>/dev/null`),
хотя таймер создавался — отсюда иллюзия «почти установлено».
**Фикс:** всё ставится в venv (как у рабочего парсера отелей).

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
  osm.py            — OSM Overpass API. BBOX расширен на север (44.0,32.0,48.0,37.0)
                      для покрытия Энергодара/Днепрорудного. На практике в этом
                      регионе HVAC-тегов почти нет — источник даёт ~0.
  vk_groups.py      — VK API: 18 запросов × 15 city_id + 47 city-less regional
                      (REGIONAL_POINTS). Гео-фильтр: TARGET_MARKERS (103 substring,
                      Крым+Запорожье+Херсон), `_is_target_region` принимает
                      «Запорожск/Херсонск» но НЕ сами города Запорожье/Херсон.
                      Дефолт категории — «продажа+монтаж» (не сырой VK-activity).
  yandex_maps.py    — Playwright: 8 запросов × 29 городов + 8 регион. queries.
                      Селекторы обновлены под актуальный DOM Я.Карт (2026).
  avito.py          — Playwright: 10 запросов × 19 городов (Крым + Запорожье
                      + Херсон + регионные слаги). На серверном IP — IP-блок,
                      нужен прокси.
  search_engine.py  — Playwright: Яндекс+Bing → обход сайтов. Я-поиск на сервере
                      даёт капчу (нужен прокси). Bing.com добавлен в AGGREGATORS.
  email_finder.py   — Playwright: добор email/phone/social с сайтов
                      (mailto/tel, JSON-LD, /contacts страницы).

bot/  (Telegram-бот, systemd-сервис hvac_bot.service)
  main.py     — long-poll loop, доступ ограничен chat_id=TG_CHAT_ID, регистрирует
                меню через setMyCommands при старте, Restart=always.
  handlers.py — 15 команд: /status, /last, /sources, /cities, /city, /region,
                /queries, /query, /xlsx, /csv, /tail, /run, /run_source, /stop,
                /help. Запуск парсера через subprocess.Popen + start_new_session.
                Поиск PID парсера через /proc/<pid>/cwd (отсекает бот отелей).

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

## Секреты и токены

**Правило: никаких реальных токенов в репозитории, ни в `.env.example`, ни в `setup.sh`.**
Telegram (и иногда VK/Google) автоматически сканируют публичный GitHub и **сами
отзывают** засветившиеся токены. Это уже случалось — 5 июня Telegram погасил
`TG_BOT_TOKEN`, 7 июня Google истёк `token.json` (OAuth user-token).

**Где сейчас живут реальные значения:**
- На сервере: `/home/hvac_parser/.env` (gitignored).
- На сервере у соседа: `/home/crimea_parser/.env` (gitignored).
- VK_TOKEN setup.sh подтягивает из крымско-парсерного `.env`.
- TG_BOT_TOKEN и TG_CHAT_ID setup.sh берёт из env-переменных при запуске
  (`TG_BOT_TOKEN=xxx bash setup.sh`) или из существующего HVAC `.env` при reinstall.
- GDRIVE_TOKEN — путь к `/home/crimea_parser/token.json` (общий с парсером отелей).
- GDRIVE_FOLDER_ID — не секрет, хардкод дефолта в setup.sh (`GDRIVE_FOLDER_ID_DEFAULT`).

### Восстановление Telegram-бота (если ревоук)

1. `@BotFather` → `/mybots` → `parser_splity_bot` → API Token → Revoke → новый.
2. SSH: подменить `TG_BOT_TOKEN=...` в `/home/hvac_parser/.env`.
3. `systemctl restart hvac_bot.service`.
4. `curl -s "https://api.telegram.org/bot$NEW_TOKEN/getMe"` — должно вернуть `ok:true`.

Парсер не перезапускать — он сам подцепит новый токен на следующем запуске.

### Восстановление Google Drive-токена (`token.json` истёк)

`gdrive.py` использует **OAuth user-token** (не service account). Если истёк
(`invalid_grant: Token has been expired or revoked`):

1. На сервере есть готовый OAuth Desktop client от соседнего проекта
   `/root/climat-simf-qa-agent/secrets/google-oauth-client.json` (project
   `otchety-testov-site`, scope `drive.file`). Удобно переиспользовать.
2. Скачать на локальную машину (с браузером):
   `scp -i ~/.ssh/climat_simf_deploy root@212.116.115.150:/root/climat-simf-qa-agent/secrets/google-oauth-client.json ./client_secrets.json`
3. Запустить `python setup_gdrive_auth.py client_secrets.json` — скрипт поднимет
   локальный сервер на свободном порту, напечатает URL. Открыть URL в браузере,
   залогиниться **Google-аккаунтом владельца HVAC-папки Drive**, нажать Allow.
   Создастся `token.json` с `refresh_token` — будет сам обновляться.
4. Залить: `scp ... token.json root@212.116.115.150:/home/crimea_parser/token.json`
   (заменяет старый, общий с парсером отелей).
5. Проверка: `venv/bin/python -c "from utils.gdrive import upload_file;
   print(upload_file('output/master_all.xlsx'))"`.

**Замечание про эмодзи в Windows-консоли:** `setup_gdrive_auth.py` падает на
финальном `print("✅ ...")` из-за cp1251. Это уже **после** записи `token.json`,
ничего не повреждает. Просто игнорируй UnicodeEncodeError.

### История git

Старые токены в коммитах остаются доступны через `git log` — кто-то их вытащит.
Если важно — почистить через `git filter-repo` (требует force-push, рисково).

---

## Claude Telegram Bridge (`claude_bridge/`)

Отдельный от парсера инструмент: Telegram-бот-«пульт» к Claude Code.
Пользователь пишет боту с телефона → `bridge.py` передаёт текст в `claude -p`
на машине, где запущен мост → ответ возвращается в Telegram. Контекст диалога
сохраняется через `--resume`, есть очередь задач, `/project` для переключения
директорий, `/stop`, белый список user ID (обязателен). Только stdlib.
Установка и настройка — `claude_bridge/README.md` (нужен ОТДЕЛЬНЫЙ бот от
BotFather, не бот парсера, и авторизованный Claude Code CLI на той машине).

---

## Инфраструктура

- **Сервер:** sprintbox box-891610, `212.116.115.150`, СПб, Ubuntu 24.04,
  4 ядра / 6 GB RAM / 70 GB. На нём же крутится парсер отелей (`/home/crimea_parser`)
  и его Telegram-бот — пути и таблицы не пересекаются, общий только VK_TOKEN
  и token.json (read-only auth).
- **Целевая директория:** `/home/hvac_parser`
- **Telegram-группа:** «Парсер_Монтажников», `chat_id=-1003554068532`. Туда же
  идут уведомления парсера и оттуда же работает бот управления.
- **Расписание парсера:** systemd-таймер `hvac_parser.timer`, вс 04:00.
- **Бот:** systemd-сервис `hvac_bot.service`, всегда онлайн, Restart=always.
- **Drive:** HVAC-папка `1h5i0uPkmScGRKufGXEc1qu0pWyWioqax` (отделена от папки
  отелей `1jPGf7PZcLl5cLRzNLAvtn5_hJiXKLb4G`). Загрузка идёт по имени файла —
  `master_all.xlsx` обновляется in-place, без дубликатов.

---

## Следующие шаги (для новой сессии)

Основная функциональность готова. Открытые направления:

1. **Прокси для Авито и краулера** — главный нерешённый вопрос. На серверном
   датацентр-IP Авито отдаёт «Доступ ограничен: проблема с IP», Яндекс веб-поиск —
   капчу. Решение — резидентный/мобильный прокси (платно). Код Авито/краулера
   готов, ключевые фразы и расширенные слаги уже добавлены — заработает,
   как только подключим прокси. Спросить у пользователя готов ли он закупить
   прокси-сервис.
2. **Расписание прогона** — еженедельно вс 04:00 (systemd-таймер). Можно дёрнуть
   вручную: или `/run` в Telegram-боте, или
   `ssh ... cd /home/hvac_parser && ONLY_SOURCES=vk,yandex nohup bash run.sh ...`.
   Полный прогон ~4-5 ч (Я.Карты 29 городов × 8 запросов + email_finder).
3. **Тюнинг качества данных** (можно делать без прогона, изменения подхватятся
   на следующем):
   - VK regional queries (47 точек) — если по какому-то городу выдача шумная,
     подкрутить `parsers/vk_groups.REGIONAL_POINTS`.
   - Категории — `utils/categories.py` (`is_hotel_junk` и `_KEYWORD_RULES`).
4. **OSM по-прежнему даёт ~0** в нашем регионе. Можно или вырезать (экономия
   ~7 мин на прогон), или попробовать упростить запрос. Низкий приоритет.

## Как управлять (быстрый старт для новой сессии)

- **SSH:** `ssh -i ~/.ssh/climat_simf_deploy root@212.116.115.150`
  (директория `/home/hvac_parser`, ветка `claude/hvac-installer-parser-2JVb4`,
  pull = fast-forward с github).
- **Telegram-бот** в группе «Парсер_Монтажников» — `/help` покажет меню.
  Основное: `/status`, `/last`, `/xlsx`, `/run`, `/tail 60`, `/stop`.
- **Сервисы:** `systemctl status hvac_parser.timer hvac_bot.service`.
  Логи парсера: `/home/hvac_parser/output/parser.log`. Логи бота:
  `/home/hvac_parser/bot.log`.
- **Очистка для пересборки начисто:** `rm -f output/*.csv output/*.xlsx
  output/dedup.db output/progress.json output/parser.log` затем `/run` или
  `bash run.sh` под xvfb.

## Важные ограничения среды
- **SSH к серверу РАБОТАЕТ** через `~/.ssh/climat_simf_deploy` (root@212.116.115.150).
  Можно ставить/чинить/гонять напрямую. (Прежнее «порт 22 заблокирован» устарело.)
- GitHub — git push в ветку (или MCP `mcp__github__*`).
- Работаем в ветке `claude/hvac-installer-parser-2JVb4` (deployment, с неё
  сервер делает git pull). Рабочая worktree-ветка fast-forward'ится в неё.
- Репозиторий публичный — токены уже засвечены, юзер взял ответственность на себя.
