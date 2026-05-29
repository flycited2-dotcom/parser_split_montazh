"""Авито — объявления по установке и продаже кондиционеров в Крыму.

Ищем в разделе «Услуги» и «Товары» по ключевым словам.
Парсим название компании/исполнителя, телефон, адрес.
"""

import asyncio
import random
import re
from datetime import datetime
from utils.storage import save_item, normalize_phone
from utils import progress

SOURCE = "Авито"

CITIES = [
    ("simferopol",   "Симферополь"),
    ("yalta",        "Ялта"),
    ("sevastopol",   "Севастополь"),
    ("evpatoriya",   "Евпатория"),
    ("feodosiya",    "Феодосия"),
    ("kerch",        "Керчь"),
    ("alushta",      "Алушта"),
    ("respublika_krym", "Крым"),
]

SEARCH_QUERIES = [
    ("установка кондиционеров", "монтаж"),
    ("монтаж сплит систем",     "монтаж"),
    ("ремонт кондиционеров",    "ремонт"),
    ("заправка кондиционеров",  "ремонт"),
    ("кондиционеры продажа",    "продажа"),
    ("вентиляция монтаж",       "вентиляция"),
]

MAX_PAGES = 3


async def _parse_listing_page(page, city: str, category: str) -> int:
    added = 0
    try:
        # Список объявлений
        items = await page.query_selector_all("[data-marker='item']")

        for item in items:
            try:
                # Название
                title_el = await item.query_selector("[itemprop='name']")
                if not title_el:
                    title_el = await item.query_selector("[data-marker='item-title']")
                name = (await title_el.inner_text() if title_el else "").strip()
                if not name:
                    continue

                # Адрес из описания
                addr_el = await item.query_selector("[class*='geo-']")
                address = (await addr_el.inner_text() if addr_el else "").strip()

                # Переходим на страницу объявления за телефоном
                link_el = await item.query_selector("a[data-marker='item-title']")
                href = await link_el.get_attribute("href") if link_el else ""
                if not href:
                    continue

                ad_url = href if href.startswith("http") else f"https://www.avito.ru{href}"
                ad_page = await page.context.new_page()
                phone = ""

                try:
                    await ad_page.goto(ad_url, wait_until="domcontentloaded", timeout=20000)
                    await ad_page.wait_for_timeout(1500)

                    # Кнопка «Показать телефон»
                    show_phone = await ad_page.query_selector(
                        "button[data-marker='phone-button']"
                    )
                    if show_phone:
                        await show_phone.click()
                        await ad_page.wait_for_timeout(1200)

                    phone_el = await ad_page.query_selector("a[href^='tel:']")
                    if phone_el:
                        href_tel = await phone_el.get_attribute("href") or ""
                        phone = normalize_phone(href_tel.replace("tel:", ""))

                except Exception:
                    pass
                finally:
                    try:
                        await ad_page.close()
                    except Exception:
                        pass

                if save_item({
                    "city":      city,
                    "name":      name,
                    "address":   address,
                    "phone":     phone,
                    "category":  category,
                    "source":    SOURCE,
                    "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }):
                    added += 1

                await asyncio.sleep(random.uniform(1.5, 3.0))

            except Exception as e:
                print(f" [Авито] объявление ошибка: {e}")
                continue

    except Exception as e:
        print(f" [Авито] страница ошибка: {e}")

    return added


async def run(context):
    print(f"\n=== Авито (HVAC Крым) ===")
    total_added = 0

    page = await context.new_page()

    for city_slug, city_name in CITIES:
        for query_text, category in SEARCH_QUERIES:
            progress.mark_query(f"Авито: {city_name} / {query_text}")

            for page_num in range(1, MAX_PAGES + 1):
                q_encoded = query_text.replace(" ", "+")
                if page_num == 1:
                    url = f"https://www.avito.ru/{city_slug}?q={q_encoded}"
                else:
                    url = f"https://www.avito.ru/{city_slug}?q={q_encoded}&p={page_num}"

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    await page.wait_for_timeout(2000)

                    # Проверяем блокировку
                    title = await page.title()
                    if "заблокирован" in title.lower() or "captcha" in title.lower():
                        print(f" [Авито] заблокирован на '{query_text}' {city_name}, пропуск")
                        break

                    added = await _parse_listing_page(page, city_name, category)
                    total_added += added
                    print(f" [{city_name}] '{query_text}' стр.{page_num}: +{added}")

                    if added == 0:
                        break

                    await asyncio.sleep(random.uniform(3.0, 6.0))

                except Exception as e:
                    print(f" [Авито] '{query_text}' {city_name} p{page_num}: {e}")
                    break

    try:
        await page.close()
    except Exception:
        pass

    print(f"\n[Авито] итого добавлено: {total_added}")
