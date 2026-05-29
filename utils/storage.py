import csv
import os
import re
from datetime import datetime
from utils.categories import normalize as normalize_category
from utils import dedup, progress

FIELDS = [
    "city", "name", "client_type", "category",
    "address", "phone", "email", "website", "social",
    "comment", "source", "parsed_at",
]

OUTPUT_DIR = "output"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"result_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")

CSV_DELIMITER = ";"

_seen = set()
_rows = []


def normalize_phone(raw: str) -> str:
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits[0] in ("7", "8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    else:
        return (raw or "").strip()
    return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"


def _clean(value: str) -> str:
    if not value:
        return ""
    s = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def _key(item):
    return f"{item.get('name','').lower().strip()}|{item.get('city','').lower().strip()}"


def save_item(item):
    global _rows
    if not item.get("name"):
        return False
    k = _key(item)

    if k in _seen:
        return False

    if not dedup.mark_seen(item.get("name", ""), item.get("city", ""),
                           item.get("source", "")):
        _seen.add(k)
        return False

    _seen.add(k)
    cleaned = {k_: _clean(item.get(k_, "")) for k_ in FIELDS}

    if cleaned.get("phone"):
        cleaned["phone"] = normalize_phone(cleaned["phone"])

    if not cleaned.get("client_type"):
        cleaned["client_type"] = normalize_category(cleaned.get("category", ""))

    _rows.append(cleaned)
    _flush()

    if len(_rows) % 10 == 0:
        try:
            progress.mark_count(len(_rows))
        except Exception:
            pass

    print(f" ✓ [{cleaned['source']}] {cleaned['city']} | {cleaned['name']} | "
          f"{cleaned.get('phone') or '—'} | {cleaned.get('email') or '—'}")
    return True


def _flush():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=FIELDS,
            delimiter=CSV_DELIMITER, quoting=csv.QUOTE_ALL,
            extrasaction="ignore", restval="",
        )
        writer.writeheader()
        writer.writerows(_rows)


def total():
    return len(_rows)


def get_output_file():
    return OUTPUT_FILE


_NAME_NORMALIZE_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def _normalize_name(name: str) -> str:
    if not name:
        return ""
    s = name.lower()
    s = _NAME_NORMALIZE_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


_MERGE_FIELDS = ("phone", "email", "website", "address", "social")

_SOURCE_PRIORITY = {
    "OSM": 5,
    "2ГИС": 4,
    "Авито": 3,
    "Я.Карты": 2,
    "VK": 1,
}


def cross_source_merge() -> int:
    """Объединяет записи из разных источников с похожими именами в одном городе."""
    groups: dict[tuple[str, str], list[dict]] = {}

    for r in _rows:
        norm = _normalize_name(r.get("name", ""))
        if not norm:
            continue
        city = (r.get("city") or "").lower().strip()
        groups.setdefault((norm, city), []).append(r)

    enriched = 0
    for rows in groups.values():
        if len(rows) < 2:
            continue

        rows_sorted = sorted(
            rows,
            key=lambda r: _SOURCE_PRIORITY.get(r.get("source", ""), 0),
            reverse=True,
        )

        for r in rows:
            for f in _MERGE_FIELDS:
                if r.get(f):
                    continue
                for donor in rows_sorted:
                    if donor is r:
                        continue
                    val = donor.get(f)
                    if val:
                        r[f] = val
                        enriched += 1
                        break

    if enriched:
        _flush()

    return enriched
