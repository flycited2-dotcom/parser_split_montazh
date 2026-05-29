"""SQLite-based persistent dedup. Переживает рестарты процесса.

Ключ — (name_normalized, city). При повторной загрузке в новый прогон уже
собранные пары не сохраняются, экономим время и не плодим дубли в новых CSV.
"""

import os
import re
import sqlite3
import threading
from datetime import datetime

DEDUP_PATH = "output/dedup.db"

_NORM_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn
    os.makedirs(os.path.dirname(DEDUP_PATH), exist_ok=True)
    _conn = sqlite3.connect(DEDUP_PATH, check_same_thread=False, timeout=10.0)
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS seen (
            name_norm TEXT NOT NULL,
            city TEXT NOT NULL,
            source TEXT,
            first_seen TEXT,
            PRIMARY KEY (name_norm, city)
        )
    """)
    _conn.commit()
    return _conn


def normalize_name(name: str) -> str:
    s = (name or "").lower()
    s = _NORM_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def normalize_city(city: str) -> str:
    return (city or "").lower().strip()


def is_seen(name: str, city: str) -> bool:
    with _lock:
        conn = _connect()
        cur = conn.execute(
            "SELECT 1 FROM seen WHERE name_norm = ? AND city = ?",
            (normalize_name(name), normalize_city(city)),
        )
        return cur.fetchone() is not None


def mark_seen(name: str, city: str, source: str = "") -> bool:
    """True — это была новая запись. False — дубль."""
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO seen(name_norm, city, source, first_seen) VALUES (?, ?, ?, ?)",
                (normalize_name(name), normalize_city(city), source,
                 datetime.now().isoformat(timespec="seconds")),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def total() -> int:
    with _lock:
        conn = _connect()
        cur = conn.execute("SELECT COUNT(*) FROM seen")
        return cur.fetchone()[0]


def stats_by_source() -> dict[str, int]:
    with _lock:
        conn = _connect()
        cur = conn.execute("SELECT source, COUNT(*) FROM seen GROUP BY source")
        return {row[0] or "?": row[1] for row in cur.fetchall()}


def reset() -> None:
    """Полная очистка кэша — для ручного запуска чистого прогона."""
    with _lock:
        conn = _connect()
        conn.execute("DELETE FROM seen")
        conn.commit()
