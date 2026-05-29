"""Email/phone/адрес enrichment — обход сайтов компаний для добора контактов.

Логика:
1. На главной — ищем mailto:/tel:/visible-text email и phone.
2. JSON-LD (script[type='application/ld+json']) — часто структурированные данные.
3. Обходим контактные страницы (/contacts, /kontakty, /o-nas...).
4. Ранжируем email: фирменный (домен=сайт) > info@/office@/... > остальные.
5. Собираем social-ссылки (vk.com, t.me, ok.ru) при отсутствии website.
"""

import asyncio
import csv
import json
import os
import random
import re
from datetime import datetime
from urllib.parse import urlparse
from playwright.async_api import async_playwright
from utils.browser import create_browser_context
from utils.storage import CSV_DELIMITER, FIELDS, normalize_phone

OUTPUT_FILE = f"output/result_enriched_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"

EMAIL_RE = re.compile(r"[a-zA-Z0-9._\%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}")

EMAIL_BLOCKLIST = (
    "example.", "@domain", "@test.", "noreply", "no-reply",
    ".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp",
    "@react", "@vue", "@sentry", "@wixpress", "@cloudflare",
    "admin@yandex", "support@google", "support@apple", "your@email",
)

PREFERRED_EMAIL_PREFIXES = (
    "info", "office", "manager", "sales", "contact",
    "klimat", "hvac", "montazh", "service", "master",
)

CONTACT_PATHS = [
    "/contacts", "/contact", "/contact-us",
    "/kontakty", "/kontakt", "/o-nas", "/o_nas",
    "/about", "/about-us", "/rekvizity",
    "/feedback", "/svyaz", "/svyazatsya",
    "/page/contact", "/page/contacts", "/info",
]

SOCIAL_HOSTS = (
    "vk.com", "vk.ru", "t.me", "telegram.me",
    "ok.ru", "instagram.com", "facebook.com",
    "wa.me", "whatsapp.com",
)


def _site_domain(website: str) -> str:
    if not website:
        return ""
    try:
        host = urlparse(website).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _email_score(email: str, site_domain: str) -> int:
    low = email.lower()
    if any(b in low for b in EMAIL_BLOCKLIST):
        return -1
    if low.endswith((".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif")):
        return -1
    score = 0
    local, _, domain = low.partition("@")
    if site_domain and (domain == site_domain or domain.endswith("." + site_domain)
                        or site_domain.endswith("." + domain)):
        score += 100
    for i, pref in enumerate(PREFERRED_EMAIL_PREFIXES):
        if local == pref or local.startswith(pref + "."):
            score += 50 - i
            break
    return score


def pick_email(text: str, site_domain: str = "") -> str:
    if not text:
        return ""
    best = ""
    best_score = -1
    for e in set(EMAIL_RE.findall(text)):
        s = _email_score(e, site_domain)
        if s > best_score:
            best = e
            best_score = s
    return best if best_score >= 0 else ""


def pick_phone(text: str) -> str:
    matches = PHONE_RE.findall(text or "")
    return normalize_phone(matches[0]) if matches else ""


async def _harvest_dom(page, site_domain: str = "") -> tuple[str, str]:
    email = phone = ""
    try:
        ems = await page.query_selector_all("a[href^='mailto:']")
        candidates = []
        for em in ems:
            href = await em.get_attribute("href") or ""
            c = href.replace("mailto:", "").split("?")[0].strip()
            if c and "@" in c:
                candidates.append(c)
        if candidates:
            best = max(candidates, key=lambda e: _email_score(e, site_domain))
            if _email_score(best, site_domain) >= 0:
                email = best
    except Exception:
        pass
    try:
        tl = await page.query_selector("a[href^='tel:']")
        if tl:
            href = await tl.get_attribute("href") or ""
            phone = normalize_phone(href.replace("tel:", "").strip())
    except Exception:
        pass
    return email, phone


async def _extract_from_jsonld(page) -> tuple[str, str]:
    email = phone = ""
    try:
        scripts = await page.query_selector_all("script[type='application/ld+json']")
        for s in scripts:
            txt = await s.inner_text()
            if not txt or "{" not in txt:
                continue
            try:
                data = json.loads(txt)
            except Exception:
                continue
            stack = [data] if not isinstance(data, list) else list(data)
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    if not email:
                        e = node.get("email")
                        if isinstance(e, str) and "@" in e:
                            email = e.strip()
                    if not phone:
                        t = node.get("telephone")
                        if isinstance(t, str) and t.strip():
                            phone = normalize_phone(t.strip())
                    for v in node.values():
                        if isinstance(v, (dict, list)):
                            stack.append(v)
                elif isinstance(node, list):
                    stack.extend(node)
            if email and phone:
                return email, phone
    except Exception:
        pass
    return email, phone


async def _extract_social(page) -> str:
    try:
        anchors = await page.query_selector_all("a[href^='http']")
        for a in anchors:
            href = await a.get_attribute("href") or ""
            host = urlparse(href).netloc.lower()
            if any(s in host for s in SOCIAL_HOSTS):
                low = href.lower()
                if any(b in low for b in ("share", "sharer", "send_to", "post=")):
                    continue
                return href.split("?")[0]
    except Exception:
        pass
    return ""


async def _harvest_page(page, site_domain: str = "") -> tuple[str, str, str]:
    email = phone = social = ""

    e, p = await _harvest_dom(page, site_domain)
    email = email or e
    phone = phone or p

    if not email or not phone:
        e, p = await _extract_from_jsonld(page)
        email = email or e
        phone = phone or p

    try:
        html = await page.content()
        if not email:
            email = pick_email(html, site_domain)
        if not phone:
            phone = pick_phone(html)
    except Exception:
        pass

    social = await _extract_social(page)
    return email, phone, social


async def enrich_from_website(page, website: str) -> tuple[str, str, str]:
    email = phone = social = ""
    site_domain = _site_domain(website)
    try:
        try:
            await page.goto(website, wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            print(f" goto fail: {e}")
            return "", "", ""

        await page.wait_for_timeout(1500)

        e, p, s = await _harvest_page(page, site_domain)
        email = email or e
        phone = phone or p
        social = social or s

        if not (email and phone):
            base = website.rstrip("/")
            for path in CONTACT_PATHS:
                if email and phone:
                    break
                try:
                    await page.goto(base + path, wait_until="domcontentloaded", timeout=10000)
                    await page.wait_for_timeout(800)
                    e, p, s = await _harvest_page(page, site_domain)
                    email = email or e
                    phone = phone or p
                    social = social or s
                except Exception:
                    continue

    except Exception:
        pass

    return email, phone, social


async def run_enrichment(input_csv: str):
    if not os.path.exists(input_csv):
        print(f"Файл не найден: {input_csv}")
        return None

    rows = []
    for delim in (";", ","):
        try:
            with open(input_csv, encoding="utf-8-sig") as f:
                sample = f.read(2048)
                f.seek(0)
                if delim in sample:
                    reader = csv.DictReader(f, delimiter=delim)
                    rows = list(reader)
                    if rows and "name" in rows[0]:
                        break
        except Exception:
            continue

    if not rows:
        print(f"Не удалось прочитать CSV: {input_csv}")
        return None

    targets = [r for r in rows if r.get("website") and (
        not r.get("email") or not r.get("phone") or not r.get("social", ""))]

    print(f"\n=== Email Finder: {len(targets)}/{len(rows)} компаний на обогащение ===")

    from utils.categories import normalize as _norm_cat
    for r in rows:
        if not r.get("client_type"):
            r["client_type"] = _norm_cat(r.get("category", ""))

    os.makedirs("output", exist_ok=True)

    def _flush_csv() -> None:
        tmp = OUTPUT_FILE + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(
                f, fieldnames=FIELDS,
                delimiter=CSV_DELIMITER, quoting=csv.QUOTE_ALL,
                extrasaction="ignore", restval="",
            )
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, OUTPUT_FILE)

    _flush_csv()

    processed_since_flush = 0
    FLUSH_EVERY = 25

    try:
        async with async_playwright() as p:
            browser, context = await create_browser_context(p, headless=True)
            page = await context.new_page()

            for i, row in enumerate(rows):
                if not row.get("website"):
                    continue

                need_email = not row.get("email")
                need_phone = not row.get("phone")
                need_social = not row.get("social", "")

                if not (need_email or need_phone or need_social):
                    continue

                print(f" [{i + 1}/{len(rows)}] {row.get('name', '?')} → {row['website']}")

                try:
                    email, phone, social = await enrich_from_website(page, row["website"])
                except Exception as e:
                    print(f" ошибка: {e}")
                    email = phone = social = ""

                if need_email and email:
                    row["email"] = email
                    print(f" email: {email}")
                if need_phone and phone:
                    row["phone"] = phone
                    print(f" phone: {phone}")
                if need_social and social:
                    row["social"] = social
                    print(f" social: {social}")

                processed_since_flush += 1
                if processed_since_flush >= FLUSH_EVERY:
                    _flush_csv()
                    processed_since_flush = 0

                await asyncio.sleep(random.uniform(1.2, 2.5))

            await browser.close()
    finally:
        try:
            _flush_csv()
        except Exception as e:
            print(f"[email_finder] финальный flush упал: {e}")

    print(f"\n✅ Обогащённый файл: {OUTPUT_FILE}")
    return OUTPUT_FILE
