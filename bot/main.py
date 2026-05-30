"""HVAC Telegram-бот — long-poll, отдельный systemd-сервис.

Реагирует только на сообщения в группе с chat_id == TG_CHAT_ID.
Из любых других чатов команды игнорируются (защита от внешних запросов).
"""
import json
import os
import sys
import time
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

# чтобы импорты parsers/utils/bot работали при запуске из systemd
sys.path.insert(0, "/home/hvac_parser")

from dotenv import load_dotenv
load_dotenv("/home/hvac_parser/.env")

from bot.handlers import dispatch, COMMANDS


API_BASE = "https://api.telegram.org/bot"


def _set_commands(token: str) -> None:
    """Регистрирует меню команд в Telegram (видно у поля ввода)."""
    cmds = [{"command": c.lstrip("/"), "description": d} for c, d in COMMANDS]
    try:
        data = urlencode({
            "commands": json.dumps(cmds, ensure_ascii=False)
        }).encode()
        with urlopen(f"{API_BASE}{token}/setMyCommands", data=data, timeout=15) as r:
            r.read()
    except Exception as e:
        print(f"[bot] setMyCommands err: {e}", flush=True)


def _get_updates(token: str, offset: int, timeout: int = 30) -> list:
    params = {"timeout": timeout, "allowed_updates": '["message"]'}
    if offset:
        params["offset"] = offset
    url = f"{API_BASE}{token}/getUpdates?{urlencode(params)}"
    try:
        with urlopen(url, timeout=timeout + 10) as r:
            data = json.loads(r.read().decode("utf-8"))
    except HTTPError as e:
        body = e.read() if hasattr(e, "read") else b""
        print(f"[bot] HTTP {e.code}: {body[:200]!r}", flush=True)
        return []
    except URLError as e:
        print(f"[bot] URLError: {e}", flush=True)
        time.sleep(5)
        return []
    except Exception as e:
        print(f"[bot] error: {e}", flush=True)
        time.sleep(5)
        return []
    if not data.get("ok"):
        print(f"[bot] not ok: {data!r}", flush=True)
        return []
    return data.get("result", [])


def main() -> None:
    token = os.getenv("TG_BOT_TOKEN", "").strip()
    try:
        allowed_chat = int(os.getenv("TG_CHAT_ID", "0"))
    except ValueError:
        allowed_chat = 0
    if not token or not allowed_chat:
        print("[bot] TG_BOT_TOKEN / TG_CHAT_ID не заданы", flush=True)
        sys.exit(1)

    _set_commands(token)
    print(f"[bot] long-poll started, allowed chat_id={allowed_chat}", flush=True)

    offset = 0
    while True:
        try:
            updates = _get_updates(token, offset, timeout=30)
            for upd in updates:
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                text = msg.get("text") or ""
                chat = msg.get("chat") or {}
                chat_id = chat.get("id")
                if chat_id != allowed_chat:
                    # сообщение не из нашей группы — игнор
                    continue
                if not text.startswith("/"):
                    continue
                frm = msg.get("from") or {}
                print(f"[bot] {frm.get('username','?')}: {text[:120]}", flush=True)
                dispatch(token, chat_id, text)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[bot] loop error: {e}", flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()
