"""HVAC-бот: обработчики команд.

Все команды читают output/* (master_all.csv, progress.json, parser.log) и
позволяют запустить/остановить прогон. Доступ ограничен в main.py (только
сообщения из TG_CHAT_ID-группы).
"""
import csv
import json
import mimetypes
import os
import subprocess
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PARSER_DIR = "/home/hvac_parser"
OUTPUT_DIR = f"{PARSER_DIR}/output"
PROGRESS_JSON = f"{OUTPUT_DIR}/progress.json"
PARSER_LOG = f"{OUTPUT_DIR}/parser.log"
MASTER_CSV = f"{OUTPUT_DIR}/master_all.csv"
MASTER_XLSX = f"{OUTPUT_DIR}/master_all.xlsx"

API_BASE = "https://api.telegram.org/bot"


# ───────── Telegram API: send_message / send_document ─────────

def _send(token: str, chat_id: int, text: str, parse_mode: str = "HTML") -> None:
    """Отправить сообщение. Длинное (>4000) режем на куски."""
    while text:
        chunk, text = text[:4000], text[4000:]
        try:
            data = urlencode({
                "chat_id": chat_id, "text": chunk,
                "parse_mode": parse_mode,
                "disable_web_page_preview": "true",
            }).encode()
            urlopen(f"{API_BASE}{token}/sendMessage", data=data, timeout=15).read()
        except Exception as e:
            print(f"[handlers] send err: {e}", flush=True)


def _send_doc(token: str, chat_id: int, path: str, caption: str = "") -> None:
    """Отправить файл документом (multipart/form-data)."""
    if not os.path.exists(path):
        _send(token, chat_id, f"❌ Файл не найден: <code>{path}</code>")
        return
    boundary = f"----HVACBot{int(time.time())}"
    with open(path, "rb") as f:
        content = f.read()
    name = os.path.basename(path)
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    parts = [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode(),
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode(),
        f"--{boundary}\r\n".encode(),
        (f'Content-Disposition: form-data; name="document"; filename="{name}"\r\n'
         f'Content-Type: {mime}\r\n\r\n').encode(),
        content,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)
    req = Request(
        f"{API_BASE}{token}/sendDocument",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        urlopen(req, timeout=120).read()
    except Exception as e:
        _send(token, chat_id, f"❌ Ошибка отправки: <code>{e}</code>")


# ───────── Helpers ─────────

def _load_csv() -> list[dict]:
    if not os.path.exists(MASTER_CSV):
        return []
    try:
        with open(MASTER_CSV, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f, delimiter=";"))
    except Exception:
        return []


def _progress() -> dict:
    try:
        return json.loads(Path(PROGRESS_JSON).read_text("utf-8"))
    except Exception:
        return {}


def _parser_pid() -> int | None:
    """PID главного процесса парсера (без xvfb), или None. Отсекаем чужие
    проекты (бот отелей) по реальному cwd через /proc/<pid>/cwd."""
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "venv/bin/python main.py"],
            text=True, stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return None
    for pid in out.split():
        if not pid.isdigit():
            continue
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            continue
        if cwd == PARSER_DIR:
            return int(pid)
    return None


def _pct(num: int, den: int) -> int:
    return 100 * num // den if den else 0


# ───────── Команды ─────────

def cmd_help(token, chat_id, args):
    lines = ["🤖 <b>HVAC-парсер — команды:</b>", ""]
    for c, d in COMMANDS:
        lines.append(f"<code>{c}</code> — {d}")
    _send(token, chat_id, "\n".join(lines))


def cmd_status(token, chat_id, args):
    pr = _progress()
    pid = _parser_pid()
    if not pr:
        _send(token, chat_id, "ℹ️ Парсер ещё ни разу не запускался." if not pid
              else "🟢 Парсер запущен, прогресс пока не записан.")
        return
    status = pr.get("status", "?")
    emoji = {"running": "🟢", "ok": "✅", "failed": "❌"}.get(status, "•")
    text = (
        f"{emoji} <b>Статус:</b> {status}\n"
        f"Стадия: <b>{pr.get('stage','?')}</b>\n"
        f"Записей: <b>{pr.get('current_count', 0)}</b>\n"
        f"Сейчас: {pr.get('current_query') or '—'}\n"
        f"Завершено: {', '.join(pr.get('completed_sources') or []) or '—'}\n"
        f"PID: {pid or '—'}\n"
        f"Старт: {pr.get('started_at','?')}\n"
        f"Обновлено: {pr.get('last_update','?')}"
    )
    _send(token, chat_id, text)


def cmd_tail(token, chat_id, args):
    n = 30
    a = args.strip()
    if a.isdigit():
        n = min(max(int(a), 5), 200)
    if not os.path.exists(PARSER_LOG):
        _send(token, chat_id, "Лог не найден.")
        return
    try:
        out = subprocess.check_output(["tail", "-n", str(n), PARSER_LOG],
                                      text=True, errors="replace")
    except Exception as e:
        _send(token, chat_id, f"Ошибка чтения лога: {e}")
        return
    out = "\n".join(l for l in out.splitlines()
                    if "SyntaxWarning" not in l and "bad = set" not in l)
    _send(token, chat_id, f"<pre>{out[:3800]}</pre>")


def cmd_last(token, chat_id, args):
    rows = _load_csv()
    if not rows:
        _send(token, chat_id, "Записей пока нет (мастер-файл не сформирован).")
        return
    n = len(rows)
    wp = sum(1 for r in rows if (r.get("phone") or "").strip())
    we = sum(1 for r in rows if (r.get("email") or "").strip())
    ws = sum(1 for r in rows if (r.get("website") or "").strip())
    by_src = Counter(r.get("source", "?") for r in rows)
    by_type = Counter(r.get("client_type", "прочее") for r in rows)
    by_city = Counter(r.get("city", "?") for r in rows)
    lines = [
        f"📊 <b>HVAC: {n} записей</b>",
        f"📞 с телефоном: {wp} ({_pct(wp,n)}%)",
        f"📧 с email: {we} ({_pct(we,n)}%)",
        f"🌐 с сайтом: {ws} ({_pct(ws,n)}%)",
        "",
        f"<b>По источникам:</b>",
    ]
    for s, c in by_src.most_common():
        lines.append(f"  {s}: {c}")
    lines.append("")
    lines.append(f"<b>По типу (client_type):</b>")
    for t, c in by_type.most_common():
        lines.append(f"  {t}: {c}")
    lines.append("")
    lines.append(f"<b>Топ-15 городов:</b>")
    for c, k in by_city.most_common(15):
        lines.append(f"  {c}: {k}")
    _send(token, chat_id, "\n".join(lines))


def cmd_sources(token, chat_id, args):
    rows = _load_csv()
    if not rows:
        _send(token, chat_id, "Записей пока нет.")
        return
    by_src = Counter(r.get("source", "?") for r in rows)
    lines = ["📡 <b>По источникам:</b>"]
    for s, c in by_src.most_common():
        wp = sum(1 for r in rows if r.get("source") == s and (r.get("phone") or "").strip())
        we = sum(1 for r in rows if r.get("source") == s and (r.get("email") or "").strip())
        lines.append(f"  <b>{s}</b>: {c} (📞 {wp}, 📧 {we})")
    _send(token, chat_id, "\n".join(lines))


def cmd_cities(token, chat_id, args):
    rows = _load_csv()
    if not rows:
        _send(token, chat_id, "Записей пока нет.")
        return
    by_city = Counter(r.get("city", "?") for r in rows)
    lines = [f"🏙 <b>Города ({len(by_city)} уникальных, всего {len(rows)} записей):</b>"]
    for c, n in by_city.most_common():
        lines.append(f"  {c}: {n}")
    _send(token, chat_id, "\n".join(lines))


def cmd_city(token, chat_id, args):
    name = args.strip()
    if not name:
        _send(token, chat_id, "Использование: <code>/city Симферополь</code>")
        return
    rows = _load_csv()
    matched = [r for r in rows if name.lower() in (r.get("city", "") or "").lower()]
    if not matched:
        _send(token, chat_id, f"По городу <b>{name}</b> ничего не найдено.")
        return
    by_src = Counter(r.get("source", "?") for r in matched)
    by_type = Counter(r.get("client_type", "прочее") for r in matched)
    lines = [
        f"🏙 <b>{name}: {len(matched)} записей</b>",
        "По источникам: " + ", ".join(f"{s}={c}" for s, c in by_src.most_common()),
        "По типу: " + ", ".join(f"{t}={c}" for t, c in by_type.most_common()),
        "",
        "<b>Топ-20 компаний:</b>",
    ]
    for r in matched[:20]:
        ph = r.get("phone") or "—"
        em = r.get("email") or ""
        web = r.get("website") or ""
        em_s = f" 📧 {em}" if em else ""
        web_s = f" 🌐 {web}" if web else ""
        lines.append(f"• {r.get('name','?')} | 📞 {ph}{em_s}{web_s}")
    _send(token, chat_id, "\n".join(lines))


def cmd_queries(token, chat_id, args):
    """Список настроенных поисковых запросов и геоточек по источникам."""
    try:
        from parsers.vk_groups import QUERIES as vk_q, REGIONAL_POINTS as vk_pts
        from parsers.yandex_maps import QUERIES as ym_q, CITIES as ym_cities, REGIONAL_QUERIES as ym_r
        from parsers.avito import SEARCH_QUERIES as av_q, CITIES as av_cities
        from parsers.search_engine import QUERY_MATRIX as se_m
    except Exception as e:
        _send(token, chat_id, f"Не смог прочитать конфиг парсера: <code>{e}</code>")
        return
    lines = [
        "📋 <b>Настроенные запросы и точки</b>",
        "",
        f"<b>VK QUERIES ({len(vk_q)}):</b>",
        ", ".join(vk_q),
        "",
        f"<b>VK REGIONAL_POINTS ({len(vk_pts)}):</b>",
        ", ".join(vk_pts),
        "",
        f"<b>Я.Карты QUERIES ({len(ym_q)}):</b>",
        ", ".join(ym_q),
        "",
        f"<b>Я.Карты CITIES ({len(ym_cities)}):</b>",
        ", ".join(ym_cities),
        "",
        f"<b>Я.Карты REGIONAL_QUERIES ({len(ym_r)}):</b>",
        " | ".join(ym_r),
        "",
        f"<b>Авито SEARCH_QUERIES ({len(av_q)}):</b>",
        ", ".join(q for q, _ in av_q),
        "",
        f"<b>Авито CITIES ({len(av_cities)}):</b>",
        ", ".join(name for _, name in av_cities),
        "",
        f"<b>Краулер QUERY_MATRIX ({len(se_m)} строк)</b>",
    ]
    _send(token, chat_id, "\n".join(lines))


def cmd_query(token, chat_id, args):
    """Поиск по подстроке в name+category. Не идеально (мы не сохраняем «по
    какому запросу нашли»), но позволяет фильтровать по теме."""
    q = args.strip()
    if not q:
        _send(token, chat_id, "Использование: <code>/query установка</code>")
        return
    rows = _load_csv()
    low = q.lower()
    matched = [r for r in rows
               if low in (r.get("name", "") or "").lower()
               or low in (r.get("category", "") or "").lower()
               or low in (r.get("client_type", "") or "").lower()]
    if not matched:
        _send(token, chat_id, f"По запросу <b>{q}</b> ничего не найдено.")
        return
    by_city = Counter(r.get("city", "?") for r in matched)
    lines = [
        f"🔎 <b>«{q}»: {len(matched)} совпадений</b>",
        "Топ городов: " + ", ".join(f"{c}={n}" for c, n in by_city.most_common(8)),
        "",
        "<b>Первые 20:</b>",
    ]
    for r in matched[:20]:
        ph = r.get("phone") or "—"
        lines.append(f"• {r.get('city','?')} | {r.get('name','?')} | 📞 {ph}")
    _send(token, chat_id, "\n".join(lines))


_REGION_MARKERS = {
    "крым": (
        "крым", "симферополь", "ялта", "севастополь", "евпатория",
        "феодосия", "керчь", "алушта", "судак", "саки", "бахчисарай",
        "джанкой", "армянск", "красноперекопск", "белогорск", "старый крым",
        "щёлкино", "щелкино", "черноморское", "коктебель", "гурзуф",
        "партенит", "симеиз", "алупка", "ливадия", "массандра", "форос",
        "балаклава", "николаевка", "орджоникидзе", "приморский",
        "новофёдоровка", "новофедоровка", "ленино", "первомайское",
        "красногвардейское", "кировское", "советский", "раздольное",
        "нижнегорский", "октябрьское", "гвардейское", "мирное",
        "молодёжное", "молодежное", "заозёрное", "заозерное", "гаспра",
        "береговое", "морское", "малореченское", "кастрополь", "мисхор",
    ),
    "запорожье": (
        "мелитополь", "бердянск", "приазовское", "днепрорудный", "днепрорудное",
        "энергодар", "каменка-днепровская", "токмак", "акимовка", "весёлое",
        "веселое", "михайловка", "васильевка", "пологи", "куйбышево",
        "черниговка", "запорожск", "запорожская",
    ),
    "херсон": (
        "геническ", "новотроицкое", "новоалексеевка", "каланчак", "чаплынка",
        "скадовск", "белозерка", "белозёрка", "голая пристань", "алёшки",
        "алешки", "каховка", "новая каховка", "таврийск", "великая лепетиха",
        "верхний рогачик", "ивановка", "нижние серогозы", "херсонск",
        "херсонская", "таврия",
    ),
}


def cmd_region(token, chat_id, args):
    r = args.strip().lower()
    aliases = {"крым": "крым", "crimea": "крым",
               "запорожье": "запорожье", "запорожская": "запорожье",
               "херсон": "херсон", "херсонская": "херсон"}
    key = aliases.get(r)
    if not key:
        _send(token, chat_id,
              "Использование: <code>/region крым</code> · "
              "<code>/region запорожье</code> · <code>/region херсон</code>")
        return
    markers = _REGION_MARKERS[key]
    rows = _load_csv()
    matched = [r for r in rows
               if any(m in (r.get("city", "") or "").lower() for m in markers)]
    label = {"крым": "Крым", "запорожье": "Запорожская обл.",
             "херсон": "Херсонская обл."}[key]
    if not matched:
        _send(token, chat_id, f"По <b>{label}</b> записей пока нет.")
        return
    by_city = Counter(r.get("city", "?") for r in matched)
    by_src = Counter(r.get("source", "?") for r in matched)
    wp = sum(1 for r in matched if (r.get("phone") or "").strip())
    we = sum(1 for r in matched if (r.get("email") or "").strip())
    lines = [
        f"🗺 <b>{label}: {len(matched)} записей</b>",
        f"📞 с телефоном: {wp} ({_pct(wp, len(matched))}%)",
        f"📧 с email: {we} ({_pct(we, len(matched))}%)",
        "По источникам: " + ", ".join(f"{s}={c}" for s, c in by_src.most_common()),
        "",
        "<b>По городам:</b>",
    ]
    for c, n in by_city.most_common(40):
        lines.append(f"  {c}: {n}")
    _send(token, chat_id, "\n".join(lines))


def _latest_result_csv() -> str | None:
    """Свежий инкрементальный result_*.csv (парсер пишет туда по ходу прогона)."""
    import glob
    files = sorted(glob.glob(f"{OUTPUT_DIR}/result_*.csv"))
    return files[-1] if files else None


def _count_rows(csv_path: str) -> int:
    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            return sum(1 for _ in f) - 1   # минус заголовок
    except Exception:
        return 0


def cmd_xlsx(token, chat_id, args):
    # Готовый мастер-файл (после завершения прогона)
    if os.path.exists(MASTER_XLSX):
        rows = _load_csv()
        _send_doc(token, chat_id, MASTER_XLSX,
                  caption=f"master_all.xlsx ({len(rows)} записей)")
        return
    # Прогон идёт — генерим xlsx из последнего result_*.csv на лету
    src = _latest_result_csv()
    if not src:
        _send(token, chat_id, "Записей пока нет — даже промежуточного файла.")
        return
    cnt = _count_rows(src)
    try:
        import sys
        if PARSER_DIR not in sys.path:
            sys.path.insert(0, PARSER_DIR)
        from utils.excel_export import build_xlsx
        tmp_xlsx = f"{OUTPUT_DIR}/_partial_{int(time.time())}.xlsx"
        result = build_xlsx(src, tmp_xlsx)
        if not result or not os.path.exists(tmp_xlsx):
            _send(token, chat_id, "Не получилось собрать промежуточный xlsx.")
            return
        _send_doc(token, chat_id, tmp_xlsx,
                  caption=f"⏳ Промежуточный xlsx ({cnt} записей, прогон идёт). "
                          f"Финальный придёт после окончания.")
        try:
            os.remove(tmp_xlsx)
        except OSError:
            pass
    except Exception as e:
        _send(token, chat_id, f"❌ Сборка xlsx упала: <code>{e}</code>")


def cmd_csv(token, chat_id, args):
    if os.path.exists(MASTER_CSV):
        rows = _load_csv()
        _send_doc(token, chat_id, MASTER_CSV,
                  caption=f"master_all.csv ({len(rows)} записей)")
        return
    # Прогон идёт — отдаём последний инкрементальный CSV
    src = _latest_result_csv()
    if not src:
        _send(token, chat_id, "Записей пока нет.")
        return
    cnt = _count_rows(src)
    _send_doc(token, chat_id, src,
              caption=f"⏳ Промежуточный {os.path.basename(src)} "
                      f"({cnt} записей, прогон идёт).")


def _spawn_parser(env_overrides: dict | None = None) -> None:
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    log = open(PARSER_LOG, "ab")
    subprocess.Popen(
        ["bash", f"{PARSER_DIR}/run.sh"],
        cwd=PARSER_DIR, env=env,
        stdout=log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def cmd_run(token, chat_id, args):
    if _parser_pid():
        _send(token, chat_id, "⚠️ Парсер уже запущен. Сначала <code>/stop</code>.")
        return
    _spawn_parser()
    _send(token, chat_id,
          "🚀 Запустил полный прогон. Слежение: <code>/status</code> · "
          "<code>/tail 60</code>")


def cmd_run_source(token, chat_id, args):
    src = args.strip().lower()
    valid = ("vk", "yandex", "avito", "search", "osm")
    if src not in valid:
        _send(token, chat_id,
              f"Источник из: <code>{', '.join(valid)}</code>. "
              "Пример: <code>/run_source vk</code>")
        return
    if _parser_pid():
        _send(token, chat_id, "⚠️ Парсер уже запущен. Сначала <code>/stop</code>.")
        return
    _spawn_parser({"ONLY_SOURCES": src})
    _send(token, chat_id, f"🚀 Запустил источник <b>{src}</b>.")


def cmd_stop(token, chat_id, args):
    pid = _parser_pid()
    if not pid:
        _send(token, chat_id, "Парсер не запущен.")
        return
    subprocess.call(["pkill", "-9", "-f", "venv/bin/python main.py"])
    subprocess.call(["pkill", "-9", "-f", "xvfb-run.*main.py"])
    subprocess.call(["pkill", "-9", "-f", "Xvfb :99"])
    _send(token, chat_id, f"🛑 Остановил парсер (был PID {pid}).")


# ───────── Маршрутизация ─────────

COMMANDS = [
    ("/help",       "справка по командам"),
    ("/status",     "текущая стадия, кол-во, PID"),
    ("/last",       "итоги: всего, %phone/email, по источникам/типу/городам"),
    ("/sources",    "разбивка по источникам"),
    ("/cities",     "все города с количеством"),
    ("/city",       "/city <name> — детально по городу"),
    ("/region",     "/region крым|запорожье|херсон"),
    ("/queries",    "все настроенные запросы и точки парсера"),
    ("/query",      "/query <text> — фильтр по name/category"),
    ("/xlsx",       "прислать master_all.xlsx"),
    ("/csv",        "прислать master_all.csv"),
    ("/tail",       "/tail [N] — последние N строк лога"),
    ("/run",        "запустить полный прогон"),
    ("/run_source", "/run_source vk|yandex|avito|search|osm"),
    ("/stop",       "остановить парсер"),
]

HANDLERS = {
    "/start":      cmd_help,
    "/help":       cmd_help,
    "/status":     cmd_status,
    "/last":       cmd_last,
    "/db":         cmd_last,
    "/sources":    cmd_sources,
    "/cities":     cmd_cities,
    "/city":       cmd_city,
    "/region":     cmd_region,
    "/queries":    cmd_queries,
    "/query":      cmd_query,
    "/xlsx":       cmd_xlsx,
    "/csv":        cmd_csv,
    "/tail":       cmd_tail,
    "/run":        cmd_run,
    "/run_source": cmd_run_source,
    "/stop":       cmd_stop,
}


def dispatch(token: str, chat_id: int, text: str) -> None:
    parts = text.split(maxsplit=1)
    cmd = parts[0].split("@")[0]
    args = parts[1] if len(parts) > 1 else ""
    handler = HANDLERS.get(cmd)
    if not handler:
        _send(token, chat_id,
              f"Не знаю команду <code>{cmd}</code>. Список: <code>/help</code>")
        return
    try:
        handler(token, chat_id, args)
    except Exception as e:
        import traceback
        traceback.print_exc()
        _send(token, chat_id, f"❌ <code>{type(e).__name__}: {e}</code>")
