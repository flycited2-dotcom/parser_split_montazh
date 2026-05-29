"""OpenStreetMap Overpass API: HVAC-компании и магазины климатической техники в Крыму.

Один HTTP-запрос — JSON со всеми node/way/relation с нужными тегами.
В тегах напрямую: name, phone, email, website, addr:*.
"""

import json
import re
from datetime import datetime
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from utils.storage import save_item
from utils.geo_city import detect_city_by_coords

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
]

# Крым + материковая часть Запорожской и Херсонской обл.
# (расширено на север до 48.0 для Энергодара/Днепрорудного/Каменки-Днепровской)
BBOX = "44.0,32.0,48.0,37.0"

# Основной запрос: точные теги для HVAC-объектов
QUERY = f"""
[out:json][timeout:120];
(
  node["shop"="air_conditioning"]({BBOX});
  way["shop"="air_conditioning"]({BBOX});
  node["craft"="hvac"]({BBOX});
  way["craft"="hvac"]({BBOX});
  node["shop"="hvac"]({BBOX});
  way["shop"="hvac"]({BBOX});
  node["trade"="air_conditioning"]({BBOX});
  way["trade"="air_conditioning"]({BBOX});
  node["service"="hvac"]({BBOX});
  node["shop"="appliances"]["name"~"[Кк]ондиционер|[Сс]плит|[Кк]лимат|[Вв]ентил",i]({BBOX});
  way["shop"="appliances"]["name"~"[Кк]ондиционер|[Сс]плит|[Кк]лимат|[Вв]ентил",i]({BBOX});
  node["shop"="electronics"]["name"~"[Кк]ондиционер|[Сс]плит|[Кк]лимат",i]({BBOX});
  way["shop"="electronics"]["name"~"[Кк]ондиционер|[Сс]плит|[Кк]лимат",i]({BBOX});
  node["name"~"[Кк]ондиционер|[Сс]плит.систем|[Кк]лиматическ|[Вв]ентиляц|[Хх]олодильн",i]
      ["shop"]({BBOX});
  node["name"~"[Кк]ондиционер|[Сс]плит.систем|[Кк]лиматическ|[Вв]ентиляц|[Хх]олодильн",i]
      ["craft"]({BBOX});
  node["name"~"[Кк]ондиционер|[Сс]плит.систем|[Кк]лиматическ|[Вв]ентиляц|[Хх]олодильн",i]
      ["office"]({BBOX});
);
out center tags;
"""

CITY_HINTS = (
    "Симферополь", "Ялта", "Севастополь", "Евпатория", "Феодосия",
    "Керчь", "Алушта", "Судак", "Саки", "Бахчисарай",
    "Коктебель", "Партенит", "Гурзуф", "Балаклава", "Форос",
    "Симеиз", "Алупка", "Ливадия", "Массандра", "Мисхор",
    "Канака", "Орджоникидзе", "Щёлкино", "Морское", "Малореченское",
)

CATEGORY_MAP = {
    "air_conditioning": "продажа+монтаж",
    "hvac":             "монтаж",
    "appliances":       "продажа",
    "electronics":      "продажа",
    "trade":            "продажа",
}


def _normalize_phone(raw: str) -> str:
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits[0] in ("7", "8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    else:
        return raw.strip()
    return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"


def _detect_city(tags: dict, lat: float | None = None, lon: float | None = None) -> str:
    for k in ("addr:city", "addr:town", "addr:village", "addr:hamlet"):
        v = tags.get(k)
        if v:
            for c in CITY_HINTS:
                if c.lower() in v.lower():
                    return c
            return v

    addr_full = tags.get("addr:full") or tags.get("address") or ""
    for c in CITY_HINTS:
        if c in addr_full:
            return c

    by_coords = detect_city_by_coords(lat, lon)
    if by_coords:
        return by_coords

    return "Крым"


def _build_address(tags: dict) -> str:
    parts = []
    for k in ("addr:city", "addr:town", "addr:village"):
        if tags.get(k):
            parts.append(f"г. {tags[k]}")
            break

    if tags.get("addr:street"):
        s = "ул. " + tags["addr:street"]
        if tags.get("addr:housenumber"):
            s += f", {tags['addr:housenumber']}"
        parts.append(s)

    if tags.get("addr:postcode"):
        parts.append(tags["addr:postcode"])

    if not parts:
        return tags.get("addr:full") or tags.get("address") or ""

    return ", ".join(parts)


def _category(tags: dict) -> str:
    name_lower = (tags.get("name") or "").lower()

    if any(w in name_lower for w in ("вентил", "вытяж")):
        return "вентиляция"
    if any(w in name_lower for w in ("холодильн", "чиллер", "промышленн")):
        return "промхолод"
    if any(w in name_lower for w in ("ремонт", "сервис", "обслужив")):
        return "ремонт"

    for k in ("shop", "craft", "trade", "service"):
        v = tags.get(k)
        if v and v in CATEGORY_MAP:
            return CATEGORY_MAP[v]

    return "продажа+монтаж"


def _website(tags: dict) -> str:
    for k in ("website", "contact:website", "url"):
        v = tags.get(k)
        if v:
            v = v.strip()
            if not v.startswith("http"):
                v = "https://" + v
            return v
    return ""


def _email(tags: dict) -> str:
    for k in ("email", "contact:email"):
        v = tags.get(k)
        if v:
            return v.split(";")[0].strip()
    return ""


def _phone(tags: dict) -> str:
    for k in ("phone", "contact:phone", "phone:mobile", "contact:mobile"):
        v = tags.get(k)
        if v:
            return _normalize_phone(v.split(";")[0])
    return ""


def _fetch_overpass() -> list:
    body = QUERY.encode("utf-8")
    last_err = None

    for url in OVERPASS_ENDPOINTS:
        try:
            req = Request(
                url, data=b"data=" + body,
                headers={
                    "User-Agent": "hvac_crimea_parser/1.0",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                method="POST",
            )
            with urlopen(req, timeout=150) as r:
                data = json.loads(r.read().decode("utf-8"))
                return data.get("elements", [])
        except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as e:
            print(f" [OSM] {url} fail: {e}")
            last_err = e
            continue

    print(f" [OSM] все эндпоинты упали: {last_err}")
    return []


async def run(context):
    """context — Playwright BrowserContext, не используется."""
    print("\n=== OSM Overpass (HVAC) ===")
    elements = _fetch_overpass()
    print(f" получено объектов: {len(elements)}")

    added = 0
    for el in elements:
        tags = el.get("tags") or {}
        name = tags.get("name") or tags.get("name:ru") or tags.get("operator") or ""

        if not name:
            continue

        lat = el.get("lat")
        lon = el.get("lon")
        if lat is None and "center" in el:
            lat = el["center"].get("lat")
            lon = el["center"].get("lon")

        item = {
            "city":      _detect_city(tags, lat, lon),
            "name":      name,
            "address":   _build_address(tags),
            "phone":     _phone(tags),
            "email":     _email(tags),
            "website":   _website(tags),
            "category":  _category(tags),
            "source":    "OSM",
            "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

        if save_item(item):
            added += 1

    print(f"\n[OSM] добавлено: {added}")
