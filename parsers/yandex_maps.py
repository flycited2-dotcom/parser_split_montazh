"""Яндекс.Карты — парсинг HVAC-компаний по городам Крыма.

Стратегия: матрица город × поисковый запрос.
Используем Playwright для автоматизации браузера.
"""

import asyncio
import random
import re
from datetime import datetime
from utils.storage import save_item, normalize_phone
from utils import progress

CITIES = [
    # Крым: города
    "Симферополь", "Ялта", "Севастополь", "Евпатория", "Феодосия",
    "Керчь", "Алушта", "Судак", "Саки", "Бахчисарай",
    "Джанкой", "Армянск", "Красноперекопск", "Белогорск", "Старый Крым",
    "Щёлкино", "Черноморское",
    # Запорожская область: крупные
    "Мелитополь", "Бердянск", "Энергодар", "Каменка-Днепровская",
    "Токмак", "Васильевка",
    # Херсонская область: крупные
    "Геническ", "Скадовск", "Каховка", "Новая Каховка", "Голая Пристань",
    "Алёшки",
]

QUERIES = [
    "кондиционеры",
    "установка кондиционеров",
    "монтаж кондиционеров",
    "ремонт кондиционеров",
    "чистка кондиционеров",
    "обслуживание кондиционеров",
    "вентиляция монтаж",
    "климатическое оборудование",
]

# Региональные запросы без привязки к конкретному городу
REGIONAL_QUERIES = [
    "кондиционеры Крым",
    "установка кондиционеров Крым",
    "монтаж сплит-систем Крым",
    "вентиляция Крым",
    "кондиционеры Запорожская область",
    "установка кондиционеров Запорожская область",
    "кондиционеры Херсонская область",
    "установка кондиционеров Херсонская область",
]

MAX_SNIPPETS = 35
SOURCE = "Я.Карты"


def _normalize_phone(raw: str) -> str:
    return normalize_phone(raw) if raw else ""


def _detect_city_from_address(address: str) -> str:
    city_hints = (
        # Крым
        "Симферополь", "Ялта", "Севастополь", "Евпатория", "Феодосия",
        "Керчь", "Алушта", "Судак", "Саки", "Бахчисарай",
        "Коктебель", "Партенит", "Гурзуф", "Балаклава", "Джанкой",
        "Армянск", "Красноперекопск", "Белогорск", "Старый Крым",
        "Щёлкино", "Щелкино", "Черноморское", "Николаевка", "Гаспра",
        "Массандра", "Ливадия", "Форос", "Симеиз", "Алупка",
        "Орджоникидзе", "Приморский", "Новофёдоровка",
        # Запорожская обл.
        "Мелитополь", "Бердянск", "Энергодар", "Каменка-Днепровская",
        "Днепрорудный", "Токмак", "Васильевка", "Михайловка", "Пологи",
        "Приморск", "Акимовка",
        # Херсонская обл.
        "Геническ", "Скадовск", "Каховка", "Новая Каховка",
        "Голая Пристань", "Алёшки", "Алешки", "Таврийск",
        "Новотроицкое", "Каланчак", "Чаплынка", "Новоалексеевка",
    )
    low = address.lower()
    for city in city_hints:
        if city.lower() in low:
            return city
    if "запорож" in low:
        return "Запорожская обл."
    if "херсон" in low or "таврия" in low:
        return "Херсонская обл."
    return "Крым"


def _category_from_query(query: str) -> str:
    q = query.lower()
    if "вентил" in q:
        return "вентиляция"
    if "ремонт" in q:
        return "ремонт"
    if "холодильн" in q:
        return "промхолод"
    if "монтаж" in q or "установк" in q:
        return "монтаж"
    return "продажа+монтаж"


async def _search_yandex_maps(context, search_query: str, city: str) -> int:
    page = None
    added = 0
    full_query = f"{search_query} {city}" if city and city not in search_query else search_query

    try:
        page = await context.new_page()
        url = f"https://yandex.ru/maps/?text={full_query.replace(' ', '+')}"
        progress.mark_query(full_query)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            await page.goto(url, timeout=40000)

        await page.wait_for_timeout(3000)

        # Проверяем капчу
        if await page.query_selector("form[id='form']"):
            print(f" [Я.Карты] капча на запросе '{full_query}', пропуск")
            return 0

        # Ожидаем загрузку списка
        try:
            await page.wait_for_selector(".search-snippet-view", timeout=10000)
        except Exception:
            print(f" [Я.Карты] нет результатов для '{full_query}'")
            return 0

        # Скроллим список результатов для загрузки
        list_container = await page.query_selector(".scroll__container")
        if list_container:
            for _ in range(6):
                await list_container.evaluate("el => el.scrollBy(0, 600)")
                await page.wait_for_timeout(800)

        snippets = await page.query_selector_all(".search-snippet-view")
        snippets = snippets[:MAX_SNIPPETS]

        for snippet in snippets:
            try:
                # Извлекаем название (актуальный класс Яндекс.Карт)
                title_el = await snippet.query_selector(
                    ".search-business-snippet-view__title"
                ) or await snippet.query_selector(".search-snippet-view__title")
                name = (await title_el.inner_text() if title_el else "").strip()
                if not name:
                    continue

                # Адрес из сниппета (если есть)
                addr_el = await snippet.query_selector(
                    ".search-business-snippet-view__address"
                ) or await snippet.query_selector(".search-snippet-view__address")
                address = (await addr_el.inner_text() if addr_el else "").strip()
                detected_city = city or _detect_city_from_address(address)

                # Открываем карточку
                await snippet.click()
                await page.wait_for_timeout(1800)

                # Ждём sidebar
                try:
                    await page.wait_for_selector(".card-title-view__title", timeout=5000)
                except Exception:
                    pass

                phone = ""
                website = ""

                # Телефон: раскрываем кнопкой, читаем ТЕКСТ (не tel:-ссылка)
                show_btn = await page.query_selector(".card-phones-view__more")
                if show_btn:
                    try:
                        await show_btn.click()
                        await page.wait_for_timeout(700)
                    except Exception:
                        pass
                phone_el = (
                    await page.query_selector(".card-phones-view__phone")
                    or await page.query_selector(".card-phones-view__number")
                    or await page.query_selector("a[href^='tel:']")
                )
                if phone_el:
                    raw = (await phone_el.inner_text() or "").strip()
                    if not raw:
                        raw = (await phone_el.get_attribute("href") or "")
                    phone = _normalize_phone(raw.replace("tel:", ""))

                # Адрес из карточки (точнее сниппета)
                addr_card = await page.query_selector(".business-contacts-view__address")
                if addr_card:
                    address = (await addr_card.inner_text()).strip() or address

                # Сайт (обрезаем tracking-параметры)
                link_el = await page.query_selector(
                    ".business-urls-view__link"
                ) or await page.query_selector(
                    "a[class*='business-urls'][href^='http']:not([href*='yandex'])"
                )
                if link_el:
                    website = (await link_el.get_attribute("href") or "").split("?")[0]

                category = _category_from_query(search_query)

                if save_item({
                    "city":      detected_city,
                    "name":      name,
                    "address":   address,
                    "phone":     phone,
                    "website":   website,
                    "category":  category,
                    "source":    SOURCE,
                    "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }):
                    added += 1

                await page.wait_for_timeout(random.uniform(600, 1200))

            except Exception as e:
                print(f" [Я.Карты] сниппет ошибка: {e}")
                continue

    except Exception as e:
        print(f" [Я.Карты] запрос '{full_query}' упал: {e}")
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass

    return added


async def run(context):
    print(f"\n=== Яндекс.Карты (HVAC Крым) ===")
    total_added = 0

    # Матрица город × запрос
    for city in CITIES:
        for query in QUERIES:
            added = await _search_yandex_maps(context, query, city)
            total_added += added
            print(f" [{city}] '{query}': +{added}")
            await asyncio.sleep(random.uniform(2.5, 5.0))

    # Региональные запросы
    for query in REGIONAL_QUERIES:
        added = await _search_yandex_maps(context, query, "")
        total_added += added
        print(f" [Крым] '{query}': +{added}")
        await asyncio.sleep(random.uniform(2.5, 5.0))

    print(f"\n[Я.Карты] итого добавлено: {total_added}")
