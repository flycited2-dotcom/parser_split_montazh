"""Отправка отчётов в Telegram после завершения парсера HVAC-компаний Крыма."""

from __future__ import annotations

import os
import time
import urllib.parse
import urllib.request
from datetime import datetime

TG_API = "https://api.telegram.org/bot"
_MAX_RETRIES = 5


def _http_post(url: str, data: bytes, headers: dict) -> int:
    last_err = None
    for attempt in range(_MAX_RETRIES):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status
        except Exception as e:
            last_err = e
            if hasattr(e, "code") and 400 <= e.code < 500:
                break
            delay = 2 ** attempt
            print(f"[tg] попытка {attempt + 1} упала ({e}), ждём {delay}с")
            time.sleep(delay)
    print(f"[tg] все попытки исчерпаны: {last_err}")
    return 0


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    token = os.getenv("TG_BOT_TOKEN", "")
    chat_id = os.getenv("TG_CHAT_ID", "")
    if not token or not chat_id:
        return False
    url = f"{TG_API}{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text[:4096],
        "parse_mode": parse_mode,
        "disable_web_page_preview": "true",
    }).encode()
    status = _http_post(url, payload, {"Content-Type": "application/x-www-form-urlencoded"})
    return status == 200


def send_document(path: str, caption: str = "") -> bool:
    token = os.getenv("TG_BOT_TOKEN", "")
    chat_id = os.getenv("TG_CHAT_ID", "")
    if not token or not chat_id or not os.path.exists(path):
        return False
    url = f"{TG_API}{token}/sendDocument"
    boundary = "----TGBoundary"
    fname = os.path.basename(path)
    with open(path, "rb") as f:
        file_data = f.read()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption[:1024]}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="document"; filename="{fname}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()
    status = _http_post(url, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return status == 200


def build_summary(stats: dict) -> str:
    total = stats.get("total", 0)
    with_phone = stats.get("with_phone", 0)
    with_email = stats.get("with_email", 0)
    with_site = stats.get("with_site", 0)
    sources = stats.get("by_source", {})
    cities = stats.get("by_city", {})
    types = stats.get("by_type", {})
    elapsed = stats.get("elapsed", "—")

    def pct(n: int) -> str:
        return f"{100 * n / total:.0f}%" if total else "—"

    lines = [
        "🌡 <b>HVAC-парсер Крым — завершён</b>",
        f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}  |  ⏱ {elapsed}",
        "",
        f"📊 <b>Всего записей:</b> {total}",
        f"📞 С телефоном: {with_phone} ({pct(with_phone)})",
        f"📧 С email: {with_email} ({pct(with_email)})",
        f"🌐 С сайтом: {with_site} ({pct(with_site)})",
    ]

    if sources:
        lines += ["", "<b>Источники:</b>"]
        for k, v in sorted(sources.items(), key=lambda x: -x[1]):
            lines.append(f"  {k}: {v}")

    if types:
        lines += ["", "<b>Типы компаний:</b>"]
        for k, v in sorted(types.items(), key=lambda x: -x[1]):
            lines.append(f"  {k}: {v}")

    if cities:
        lines += ["", "<b>Топ городов:</b>"]
        for k, v in list(sorted(cities.items(), key=lambda x: -x[1]))[:10]:
            lines.append(f"  {k}: {v}")

    return "\n".join(lines)


def checkpoint(label: str, added: int, total: int, elapsed: str = "") -> None:
    token = os.getenv("TG_BOT_TOKEN", "")
    chat_id = os.getenv("TG_CHAT_ID", "")
    if not token or not chat_id:
        return
    msg = f"✅ {label}: +{added} (итого: {total}"
    if elapsed:
        msg += f", {elapsed}"
    msg += ")"
    send_message(msg)


def notify(stats: dict, csv_path: str = "", xlsx_path: str = "") -> None:
    summary = build_summary(stats)
    send_message(summary)
    if csv_path and os.path.exists(csv_path):
        send_document(csv_path, caption="CSV — все данные")
    if xlsx_path and os.path.exists(xlsx_path):
        send_document(xlsx_path, caption="Excel — с разбивкой по городам")
