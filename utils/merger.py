"""Объединяет все result_*.csv в output/ в единый master_all.csv + master_all.xlsx."""

from __future__ import annotations

import csv
import glob
import os
from collections import OrderedDict

_HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(os.path.dirname(_HERE), "output")

FIELDNAMES = [
    "city", "name", "client_type", "category",
    "address", "phone", "email", "website", "social",
    "comment", "source", "parsed_at",
]


def _dedup_key(row: dict) -> str:
    name = (row.get("name") or "").strip().lower()
    phone = (row.get("phone") or "").strip().replace(" ", "").replace("-", "")
    return f"{name}|{phone}"


def build_master(output_dir: str = OUTPUT_DIR) -> str:
    pattern = os.path.join(output_dir, "result_*.csv")
    raw_files = sorted(
        [f for f in glob.glob(pattern) if "enriched" not in os.path.basename(f)],
        key=os.path.getmtime,
    )

    enriched_bases = {
        os.path.basename(f).replace("_enriched", "")
        for f in glob.glob(os.path.join(output_dir, "*_enriched.csv"))
    }

    seen: OrderedDict[str, dict] = OrderedDict()

    for filepath in raw_files:
        base = os.path.basename(filepath)
        if base in enriched_bases:
            continue
        _load_csv_into(filepath, seen)

    for filepath in sorted(
        glob.glob(os.path.join(output_dir, "*_enriched.csv")),
        key=os.path.getmtime,
    ):
        _load_csv_into(filepath, seen)

    rows = list(seen.values())
    master_path = os.path.join(output_dir, "master_all.csv")
    os.makedirs(output_dir, exist_ok=True)

    with open(master_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=FIELDNAMES, delimiter=";",
            extrasaction="ignore", restval="", quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"[merger] master_all.csv: {len(rows)} записей из {len(raw_files)} файлов")
    return master_path


def _load_csv_into(filepath: str, seen: OrderedDict) -> None:
    try:
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                key = _dedup_key(row)
                if key not in seen:
                    seen[key] = row
                else:
                    existing = seen[key]
                    for field in FIELDNAMES:
                        if not existing.get(field) and row.get(field):
                            existing[field] = row[field]
    except Exception as e:
        print(f"[merger] ошибка чтения {filepath}: {e}")


def build_master_xlsx(output_dir: str = OUTPUT_DIR) -> tuple[str, str]:
    csv_path = build_master(output_dir)
    xlsx_path = os.path.join(output_dir, "master_all.xlsx")

    try:
        from utils.excel_export import build_xlsx
        result = build_xlsx(csv_path, xlsx_path)
        xlsx_path = result or xlsx_path
    except Exception as e:
        print(f"[merger] xlsx ошибка: {e}")
        xlsx_path = ""

    return csv_path, xlsx_path
