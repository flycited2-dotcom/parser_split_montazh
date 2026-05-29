"""VK API — поиск групп HVAC-компаний в Крыму и сбор контактов.

ENV: VK_TOKEN (user access_token со scope groups). Без токена — пропуск.

Логика:
1. groups.search по матрице city_id × категория → собираем уникальные group_id.
2. groups.getById пачками по 500 с fields=contacts,site,description,...
3. email: из contacts (приоритет фирменному — домен совпадает с site), затем из описания.
4. phone: из contacts. website: site (очищенный). social: vk.com/<screen_name>.
5. save_item — persistent dedup сам отсеет повторы между прогонами.
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from urllib.parse import urlparse
from utils.storage import save_item, normalize_phone

API = "https://api.vk.com/method"
V = "5.131"
RPS_PAUSE = 0.34  # VK лимит ~3 запроса/сек

VK_CITIES = {
    627:     "Симферополь",
    818:     "Ялта",
    185:     "Севастополь",
    799:     "Евпатория",
    1483:    "Феодосия",
    478:     "Керчь",
    2510:    "Алушта",
    7188:    "Судак",
    4331:    "Саки",
    475:     "Бахчисарай",
    5490687: "Коктебель",
    5490709: "Гурзуф",
    5490654: "Партенит",
    5490729: "Симеиз",
    5490701: "Алупка",
}

QUERIES = [
    "кондиционеры",
    "установка кондиционеров",
    "монтаж кондиционеров",
    "сплит-системы",
    "монтаж сплит",
    "климатическая техника",
    "климатическое оборудование",
    "вентиляция",
    "монтаж вентиляции",
    "ремонт кондиционеров",
    "сервис кондиционеров",
    "заправка кондиционеров",
    "холодильное оборудование",
    "промышленный холод",
]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._\%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
EMAIL_BLOCKLIST = ("noreply", "no-reply", "example.", "@vk.com", "@vkontakte")
PREFERRED_PREFIXES = (
    "info", "office", "manager", "sales", "klimat", "konditsioner",
    "hvac", "montazh", "service", "master", "contact",
)

# Ключевые слова для фильтрации нерелевантных групп
RELEVANCE_KEYWORDS = (
    "кондиционер", "сплит", "климат", "вентил", "hvac", "холодильн",
    "монтаж", "установка", "кондиц", "чиллер",
)


def _call(method: str, token: str, **params) -> dict:
    params["access_token"] = token
    params["v"] = V
    url = f"{API}/{method}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        return {"error": {"error_msg": str(e)}}


def _site_domain(site: str) -> str:
    try:
        h = urlparse(site if "://" in site else "http://" + site).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def _clean_site(site: str) -> str:
    if not site:
        return ""
    try:
        site = site.strip().split()[0]
        if not site.startswith("http"):
            site = "https://" + site
        sp = urlparse(site)
        if not sp.netloc:
            return ""
        return f"{sp.scheme}://{sp.netloc}{sp.path}".rstrip("/")
    except Exception:
        return ""


def _pick_email(contacts: list, description: str, site_domain: str) -> str:
    cands = []
    for c in contacts or []:
        e = (c.get("email") or "").strip()
        if e and "@" in e:
            cands.append(e)
    cands += EMAIL_RE.findall(description or "")
    best, best_score = "", -1
    for e in cands:
        low = e.lower()
        if any(b in low for b in EMAIL_BLOCKLIST):
            continue
        score = 0
        local, _, domain = low.partition("@")
        if site_domain and (domain == site_domain or domain.endswith("." + site_domain)):
            score += 100
        for i, pref in enumerate(PREFERRED_PREFIXES):
            if local == pref or local.startswith(pref + "."):
                score += 50 - i
                break
        if score > best_score:
            best, best_score = e, score
    return best if best_score >= 0 else ""


def _pick_phone(contacts: list) -> str:
    for c in contacts or []:
        p = (c.get("phone") or "").strip()
        if p:
            return normalize_phone(p)
    return ""


def _is_relevant(name: str, activity: str, description: str) -> bool:
    """Фильтруем группы, не имеющие отношения к HVAC."""
    text = " ".join([name, activity, description]).lower()
    return any(kw in text for kw in RELEVANCE_KEYWORDS)


async def run(context):
    """context не используется (HTTP-only)."""
    token = os.getenv("VK_TOKEN", "").strip()
    if not token:
        print("\n=== VK: VK_TOKEN не задан, пропуск ===")
        return
    print("\n=== VK Groups (HVAC Крым) ===")

    # 1. Сбор group_id по матрице город × запрос
    found: dict[int, str] = {}
    for city_id, city_name in VK_CITIES.items():
        for q in QUERIES:
            r = _call("groups.search", token, q=q, city_id=city_id, count=200, sort=0)
            time.sleep(RPS_PAUSE)
            if "error" in r:
                msg = r["error"].get("error_msg", "?")
                if "Too many" in msg:
                    time.sleep(1.0)
                    continue
            for it in r.get("response", {}).get("items", []):
                gid = it.get("id")
                if gid and gid not in found:
                    found[gid] = city_name
        print(f" [VK] {city_name}: накоплено {len(found)} групп")

    # Дополнительный поиск без привязки к городу
    for q in ("кондиционеры Крым", "установка кондиционеров Крым", "сплит Крым"):
        r = _call("groups.search", token, q=q, count=200, sort=0)
        time.sleep(RPS_PAUSE)
        for it in r.get("response", {}).get("items", []):
            gid = it.get("id")
            if gid and gid not in found:
                found[gid] = "Крым"

    if not found:
        print(" [VK] ничего не найдено")
        return
    print(f" [VK] всего уникальных групп: {len(found)}")

    # 2. Детали пачками по 500
    added = 0
    skipped = 0
    gids = list(found.keys())
    for start in range(0, len(gids), 500):
        chunk = gids[start:start + 500]
        r = _call("groups.getById", token,
                  group_ids=",".join(map(str, chunk)),
                  fields="contacts,site,description,activity,city,screen_name")
        time.sleep(RPS_PAUSE)
        if "error" in r:
            print(f" [VK] getById err: {r['error'].get('error_msg', '?')[:80]}")
            time.sleep(1.0)
            continue
        resp = r.get("response")
        groups = resp.get("groups") if isinstance(resp, dict) else resp
        for g in groups or []:
            name = (g.get("name") or "").strip()
            if not name:
                continue
            activity = g.get("activity") or ""
            desc = g.get("description") or ""

            if not _is_relevant(name, activity, desc):
                skipped += 1
                continue

            gid = g.get("id")
            site = _clean_site(g.get("site") or "")
            sdom = _site_domain(site)
            contacts = g.get("contacts") or []
            email = _pick_email(contacts, desc, sdom)
            phone = _pick_phone(contacts)
            city_obj = g.get("city") or {}
            city = (city_obj.get("title") if isinstance(city_obj, dict) else "") \
                or found.get(gid, "Крым")
            screen = g.get("screen_name") or f"club{gid}"
            social = f"https://vk.com/{screen}"

            # Определяем тип по activity/name
            low = (name + " " + activity).lower()
            if any(w in low for w in ("вентил", "вытяж")):
                category = "вентиляция"
            elif any(w in low for w in ("холодильн", "промышленн", "чиллер")):
                category = "промхолод"
            elif any(w in low for w in ("ремонт", "сервис", "заправк")):
                category = "ремонт"
            elif any(w in low for w in ("продаж", "магазин", "shop")):
                category = "продажа"
            elif any(w in low for w in ("монтаж", "установк", "install")):
                category = "монтаж"
            else:
                category = activity or "климатическое оборудование"

            if save_item({
                "city":      city,
                "name":      name,
                "address":   "",
                "phone":     phone,
                "email":     email,
                "website":   site,
                "social":    social,
                "category":  category,
                "source":    "VK",
                "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }):
                added += 1

    print(f"\n[VK] добавлено: {added}, отфильтровано нерелевантных: {skipped}")
