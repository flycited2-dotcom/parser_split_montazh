"""HVAC-парсер Крым — главный оркестратор.

Порядок запуска источников (от лёгких к тяжёлым):
  1. OSM Overpass     — один HTTP-запрос, без браузера
  2. VK Groups        — VK API, без браузера
  3. Яндекс.Карты     — Playwright, много запросов
  4. Авито            — Playwright, медленно из-за IP-ограничений
  5. Поисковый краулер— Playwright + обход сайтов

После сбора:
  6. cross_source_merge — обогащаем записи из разных источников
  7. Email Finder       — добираем email/phone с сайтов компаний
  8. Экспорт CSV + XLSX
  9. Загрузка на Google Drive
  10. Уведомление в Telegram

ENV переменные (.env):
  VK_TOKEN         — обязателен для VK-парсера
  TG_BOT_TOKEN     — Telegram бот
  TG_CHAT_ID       — куда слать отчёт
  GDRIVE_FOLDER_ID — папка на Google Drive
  GDRIVE_TOKEN     — путь к token.json
  HEADLESS         — 1/0, default 1 (без экрана)
  ONLY_SOURCES     — comma-separated список источников для отладки
  SKIP_ENRICHMENT  — 1 = пропустить Email Finder
"""

import asyncio
import os
import time
from datetime import datetime
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

from utils import progress, storage
from utils.browser import create_browser_context
from utils.excel_export import build_xlsx
from utils.merger import build_master_xlsx
from utils.telegram_notify import checkpoint, notify

import parsers.osm as p_osm
import parsers.vk_groups as p_vk
import parsers.yandex_maps as p_yandex
import parsers.avito as p_avito
import parsers.search_engine as p_search

HEADLESS = os.getenv("HEADLESS", "1") == "1"
ONLY_SOURCES = {s.strip().lower() for s in os.getenv("ONLY_SOURCES", "").split(",") if s.strip()}
SKIP_ENRICHMENT = os.getenv("SKIP_ENRICHMENT", "0") == "1"

# Источники: (id, module, использует_браузер)
SOURCES = [
    ("osm",      p_osm,     False),
    ("vk",       p_vk,      False),
    ("yandex",   p_yandex,  True),
    ("avito",    p_avito,   True),
    ("search",   p_search,  True),
]


def _should_run(source_id: str) -> bool:
    if not ONLY_SOURCES:
        return True
    return source_id in ONLY_SOURCES


async def main():
    progress.mark_started()
    start_ts = time.time()

    print("=" * 60)
    print("HVAC-парсер Крым — старт")
    print(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Headless: {HEADLESS}  |  Обогащение: {not SKIP_ENRICHMENT}")
    if ONLY_SOURCES:
        print(f"Только источники: {ONLY_SOURCES}")
    print("=" * 60)

    try:
        async with async_playwright() as playwright:
            browser, context = await create_browser_context(playwright, headless=HEADLESS)

            for source_id, module, needs_browser in SOURCES:
                if not _should_run(source_id):
                    print(f"\n[main] пропуск: {source_id}")
                    continue

                progress.mark_stage(source_id)
                count_before = storage.total()

                try:
                    ctx = context if needs_browser else None
                    await module.run(ctx)
                except Exception as e:
                    print(f"\n[main] {source_id} упал: {e}")

                added = storage.total() - count_before
                progress.mark_completed_source(source_id)
                elapsed = _fmt_elapsed(time.time() - start_ts)
                checkpoint(source_id, added, storage.total(), elapsed)

            await browser.close()

        # Обогащение данных между источниками
        print("\n=== Cross-source merge ===")
        progress.mark_stage("merge")
        enriched_cnt = storage.cross_source_merge()
        print(f"[merge] обогащено полей: {enriched_cnt}")

        # Email Finder — добираем контакты с сайтов
        enriched_csv = None
        if not SKIP_ENRICHMENT:
            print("\n=== Email Finder ===")
            progress.mark_stage("email_finder")
            from parsers.email_finder import run_enrichment
            enriched_csv = await run_enrichment(storage.get_output_file())

        # Собираем master_all.csv + .xlsx из всех CSV
        print("\n=== Экспорт ===")
        progress.mark_stage("export")
        csv_path, xlsx_path = build_master_xlsx()

        if not xlsx_path and not enriched_csv:
            csv_path = storage.get_output_file()
            base = os.path.splitext(csv_path)[0]
            xlsx_path = build_xlsx(csv_path, base + ".xlsx") or ""

        # Статистика для отчёта
        rows = _load_csv_rows(csv_path)
        stats = _build_stats(rows, start_ts)

        # Google Drive
        gdrive_link = ""
        if os.getenv("GDRIVE_FOLDER_ID"):
            print("\n=== Google Drive ===")
            progress.mark_stage("gdrive")
            from utils.gdrive import upload_file
            if xlsx_path and os.path.exists(xlsx_path):
                gdrive_link = upload_file(xlsx_path) or ""
            elif csv_path and os.path.exists(csv_path):
                gdrive_link = upload_file(csv_path) or ""

        # Telegram уведомление
        if os.getenv("TG_BOT_TOKEN"):
            print("\n=== Telegram ===")
            progress.mark_stage("telegram")
            if gdrive_link:
                stats["gdrive_link"] = gdrive_link
            notify(stats, csv_path, xlsx_path)

        progress.mark_finished("ok")
        elapsed = _fmt_elapsed(time.time() - start_ts)
        print(f"\n{'=' * 60}")
        print(f"✅ Готово за {elapsed}")
        print(f"Записей: {storage.total()}")
        print(f"CSV:  {csv_path}")
        if xlsx_path:
            print(f"XLSX: {xlsx_path}")
        print("=" * 60)

    except Exception as e:
        progress.mark_failed(str(e))
        print(f"\n[main] КРИТИЧЕСКАЯ ОШИБКА: {e}")
        raise


def _fmt_elapsed(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}ч {m}м {s}с"
    if m:
        return f"{m}м {s}с"
    return f"{s}с"


def _load_csv_rows(csv_path: str) -> list[dict]:
    import csv
    if not csv_path or not os.path.exists(csv_path):
        return []
    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f, delimiter=";"))
    except Exception:
        return []


def _build_stats(rows: list[dict], start_ts: float) -> dict:
    from collections import Counter
    total = len(rows)
    return {
        "total":      total,
        "with_phone": sum(1 for r in rows if (r.get("phone") or "").strip()),
        "with_email": sum(1 for r in rows if (r.get("email") or "").strip()),
        "with_site":  sum(1 for r in rows if (r.get("website") or "").strip()),
        "by_source":  dict(Counter(r.get("source", "?") for r in rows)),
        "by_city":    dict(Counter(r.get("city", "?") for r in rows)),
        "by_type":    dict(Counter(r.get("client_type", "прочее") for r in rows)),
        "elapsed":    _fmt_elapsed(time.time() - start_ts),
    }


if __name__ == "__main__":
    asyncio.run(main())
