"""Поисковый краулер — ищет сайты HVAC-компаний через Яндекс/Bing/Mail.ru.

Собираем URL сайтов, отфильтровываем агрегаторы, обходим сайты
за контактами (email, phone, address).
"""

import asyncio
import random
import re
from datetime import datetime
from urllib.parse import urlparse
from utils.storage import save_item
from utils import progress

SOURCE = "Краулер"

QUERY_MATRIX = [
    # (запрос, город, category)
    ("установка кондиционеров", "Симферополь",  "монтаж"),
    ("установка кондиционеров", "Ялта",         "монтаж"),
    ("установка кондиционеров", "Севастополь",  "монтаж"),
    ("установка кондиционеров", "Евпатория",    "монтаж"),
    ("установка кондиционеров", "Феодосия",     "монтаж"),
    ("установка кондиционеров", "Керчь",        "монтаж"),
    ("монтаж сплит-систем",     "Крым",         "монтаж"),
    ("кондиционеры продажа",    "Симферополь",  "продажа"),
    ("кондиционеры продажа",    "Ялта",         "продажа"),
    ("кондиционеры продажа",    "Севастополь",  "продажа"),
    ("ремонт кондиционеров",    "Крым",         "ремонт"),
    ("вентиляция монтаж",       "Крым",         "вентиляция"),
    ("холодильное оборудование","Крым",         "промхолод"),
    ("климатическое оборудование Крым", "",     "продажа+монтаж"),
    ("сплит системы Крым установка",    "",     "монтаж"),
    ("чистка кондиционеров",            "Симферополь", "ремонт"),
    ("чистка кондиционеров",            "Ялта",        "ремонт"),
    ("обслуживание кондиционеров",      "Крым",        "ремонт"),
    ("срочный монтаж кондиционеров",    "Крым",        "монтаж"),
    # Доп. крымские
    ("установка кондиционеров",         "Джанкой",     "монтаж"),
    ("установка кондиционеров",         "Армянск",     "монтаж"),
    ("установка кондиционеров",         "Красноперекопск", "монтаж"),
    # Запорожская область
    ("установка кондиционеров",         "Мелитополь",  "монтаж"),
    ("установка кондиционеров",         "Бердянск",    "монтаж"),
    ("установка кондиционеров",         "Энергодар",   "монтаж"),
    ("установка кондиционеров",         "Каменка-Днепровская", "монтаж"),
    ("установка кондиционеров",         "Токмак",      "монтаж"),
    ("установка кондиционеров",         "Васильевка",  "монтаж"),
    ("кондиционеры Запорожская область", "",           "продажа+монтаж"),
    # Херсонская область
    ("установка кондиционеров",         "Геническ",    "монтаж"),
    ("установка кондиционеров",         "Скадовск",    "монтаж"),
    ("установка кондиционеров",         "Каховка",     "монтаж"),
    ("установка кондиционеров",         "Новая Каховка", "монтаж"),
    ("установка кондиционеров",         "Голая Пристань", "монтаж"),
    ("установка кондиционеров",         "Алёшки",      "монтаж"),
    ("кондиционеры Херсонская область", "",            "продажа+монтаж"),
]

AGGREGATORS = {
    "avito.ru", "youla.ru", "farpost.ru", "irr.ru", "olx.ru",
    "booking.com", "yandex.ru", "google.com", "google.ru", "bing.com",
    "vk.com", "ok.ru", "instagram.com", "facebook.com", "t.me",
    "2gis.ru", "zoon.ru", "yell.ru", "flamp.ru",
    "blizko.ru", "flagma.ru", "tiu.ru", "pulscen.ru",
    "mastert.ru", "profi.ru", "youdo.com", "remontnik.ru",
    "yclients.com", "mir-klimata.com", "e-katalog.ru",
    "dns-shop.ru", "mvideo.ru", "eldorado.ru", "citilink.ru",
    "ozon.ru", "wildberries.ru",
    "wikipedia.org", "youtube.com", "zen.yandex.ru",
}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._\%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}")

CONTACT_PATHS = [
    "/contacts", "/contact", "/o-nas", "/o_nas", "/about",
    "/kontakty", "/kontakt", "/svyaz", "/feedback",
    "/page/contacts", "/info", "/rekvizity",
]


def _is_aggregator(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return any(host == a or host.endswith("." + a) for a in AGGREGATORS)
    except Exception:
        return True


def _extract_name(page_title: str, url: str) -> str:
    if not page_title:
        try:
            host = urlparse(url).netloc.lower()
            return host[4:] if host.startswith("www.") else host
        except Exception:
            return ""
    # Убираем шаблонные суффиксы
    for sep in [" — ", " - ", " | ", " :: ", " · "]:
        if sep in page_title:
            parts = page_title.split(sep)
            name = min(parts, key=len).strip()
            if len(name) > 4:
                return name[:200]
    return page_title.strip()[:200]


async def _enrich_site(page, url: str, city: str, category: str) -> None:
    """Обходим сайт, собираем контакты и сохраняем запись."""
    email = phone = address = ""

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(1500)

        title = await page.title()
        name = _extract_name(title, url)
        if not name:
            return

        html = await page.content()
        emails = EMAIL_RE.findall(html)
        email = emails[0] if emails else ""
        phones = PHONE_RE.findall(html)
        phone = phones[0] if phones else ""

        # Дополнительно — страница контактов
        if not (email and phone):
            base = url.rstrip("/")
            for path in CONTACT_PATHS:
                try:
                    await page.goto(base + path, wait_until="domcontentloaded", timeout=10000)
                    await page.wait_for_timeout(800)
                    html2 = await page.content()
                    if not email:
                        m = EMAIL_RE.search(html2)
                        if m:
                            email = m.group(0)
                    if not phone:
                        m = PHONE_RE.search(html2)
                        if m:
                            phone = m.group(0)
                    if email and phone:
                        break
                except Exception:
                    continue

        save_item({
            "city":      city,
            "name":      name,
            "phone":     phone,
            "email":     email,
            "website":   url,
            "category":  category,
            "source":    SOURCE,
            "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })

    except Exception as e:
        print(f" [Краулер] сайт {url}: {e}")


async def _search_yandex(page, query: str) -> list[str]:
    urls = []
    seen = set()
    try:
        search_url = f"https://yandex.ru/search/?text={query.replace(' ', '+')}&lr=977"
        await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)

        if await page.query_selector("form[id='form']"):
            print(f" [Краулер/Яндекс] капча, пропуск")
            return urls

        links = await page.query_selector_all("a.link[href^='http']")
        for link in links[:20]:
            href = await link.get_attribute("href") or ""
            if href and not _is_aggregator(href):
                origin = urlparse(href).netloc
                if origin and origin not in seen:
                    seen.add(origin)
                    urls.append(href.split("?")[0])
    except Exception as e:
        print(f" [Краулер/Яндекс] '{query}': {e}")
    return urls


async def _search_bing(page, query: str) -> list[str]:
    urls = []
    seen = set()
    try:
        search_url = f"https://www.bing.com/search?q={query.replace(' ', '+')}"
        await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)

        links = await page.query_selector_all("li.b_algo h2 a")
        for link in links[:15]:
            href = await link.get_attribute("href") or ""
            if href.startswith("http") and not _is_aggregator(href):
                origin = urlparse(href).netloc
                if origin and origin not in seen:
                    seen.add(origin)
                    urls.append(href.split("?")[0])
    except Exception as e:
        print(f" [Краулер/Bing] '{query}': {e}")
    return urls


async def run(context):
    print(f"\n=== Поисковый краулер (HVAC Крым) ===")
    total_added = 0

    search_page = await context.new_page()
    enrich_page = await context.new_page()
    seen_origins: set[str] = set()

    for query_text, city, category in QUERY_MATRIX:
        full_query = f"{query_text} {city} Крым".strip() if city else f"{query_text} Крым"
        progress.mark_query(full_query)
        print(f" [Краулер] '{full_query}'")

        # Ищем через Яндекс
        urls = await _search_yandex(search_page, full_query)
        await asyncio.sleep(random.uniform(2.0, 4.0))

        # Дополняем Bing
        if len(urls) < 5:
            bing_urls = await _search_bing(search_page, full_query)
            for u in bing_urls:
                if u not in urls:
                    urls.append(u)
            await asyncio.sleep(random.uniform(1.5, 3.0))

        # Обходим найденные сайты
        for url in urls:
            origin = urlparse(url).netloc
            if origin in seen_origins:
                continue
            seen_origins.add(origin)

            before = total_added
            await _enrich_site(enrich_page, url, city or "Крым", category)
            await asyncio.sleep(random.uniform(1.0, 2.5))

    try:
        await search_page.close()
        await enrich_page.close()
    except Exception:
        pass

    print(f"\n[Краулер] итого добавлено: {total_added}")
