#!/usr/bin/env python3
"""
Claude Telegram Bridge — мост между Telegram и Claude Code CLI.

Пишешь боту в Telegram -> сообщение уходит в `claude -p` на этой машине ->
ответ Claude возвращается тебе в Telegram. Контекст диалога сохраняется
(claude --resume), т.е. это полноценная беседа, а не разовые запросы.

Зависимости: только стандартная библиотека Python 3.9+ и установленный
Claude Code CLI (команда `claude`), авторизованный на этой машине.

Конфиг: .env рядом со скриптом (см. .env.example) или переменные окружения.

Безопасность: бот ИСПОЛНЯЕТ ЗАДАЧИ НА ЭТОЙ МАШИНЕ. Доступ жёстко ограничен
белым списком BRIDGE_ALLOWED_USER_IDS — без него мост не стартует.
"""

import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IS_POSIX = os.name == "posix"

# ─── Конфиг ──────────────────────────────────────────────────────────────


def load_env_file(path: str) -> None:
    """Подгружает KEY=VALUE из .env, не перетирая уже заданное окружение."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


load_env_file(os.environ.get("BRIDGE_ENV", os.path.join(SCRIPT_DIR, ".env")))

BOT_TOKEN = os.environ.get("BRIDGE_BOT_TOKEN", "")
ALLOWED_USER_IDS = {
    int(x) for x in re.split(r"[,;\s]+", os.environ.get("BRIDGE_ALLOWED_USER_IDS", "")) if x
}
CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"
PERMISSION_MODE = os.environ.get("BRIDGE_PERMISSION_MODE", "acceptEdits")
TASK_TIMEOUT = int(os.environ.get("BRIDGE_TASK_TIMEOUT", "3600"))
POLL_TIMEOUT = int(os.environ.get("BRIDGE_POLL_TIMEOUT", "50"))
STATE_FILE = os.environ.get("BRIDGE_STATE_FILE", os.path.join(SCRIPT_DIR, "bridge_state.json"))
DEFAULT_DIR = os.path.expanduser(os.environ.get("BRIDGE_DEFAULT_DIR", "~"))
EXTRA_ARGS = os.environ.get("BRIDGE_CLAUDE_ARGS", "").split()

# Проекты: "имя=/путь;имя2=/путь2" — переключение через /project имя
PROJECTS = {}
for chunk in os.environ.get("BRIDGE_PROJECTS", "").split(";"):
    if "=" in chunk:
        name, _, path = chunk.partition("=")
        PROJECTS[name.strip()] = os.path.expanduser(path.strip())

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
TG_LIMIT = 4000  # лимит Telegram 4096, берём с запасом

HELP = (
    "Я — мост к Claude Code на твоей машине. Просто напиши задачу текстом,\n"
    "я передам её Claude и пришлю ответ. Контекст беседы сохраняется.\n\n"
    "Команды:\n"
    "/new — начать новый диалог (сбросить контекст)\n"
    "/project <имя|/путь> — сменить рабочую директорию\n"
    "/projects — список настроенных проектов\n"
    "/status — текущий проект, сессия, активная задача\n"
    "/stop — прервать выполняемую задачу\n"
    "/help — эта справка"
)

# ─── Утилиты ─────────────────────────────────────────────────────────────


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def api(method: str, **params):
    data = json.dumps(params).encode()
    req = urllib.request.Request(
        f"{API_URL}/{method}", data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=POLL_TIMEOUT + 20) as resp:
        return json.load(resp)


def send(chat_id: int, text: str) -> None:
    """Отправляет текст, режет на куски под лимит Telegram."""
    text = text.strip() or "(пустой ответ)"
    while text:
        if len(text) <= TG_LIMIT:
            chunk, text = text, ""
        else:
            cut = text.rfind("\n", 0, TG_LIMIT)
            if cut < TG_LIMIT // 2:
                cut = TG_LIMIT
            chunk, text = text[:cut], text[cut:].lstrip("\n")
        try:
            api("sendMessage", chat_id=chat_id, text=chunk)
        except Exception as e:  # noqa: BLE001
            log(f"sendMessage failed: {e}")
            return


# ─── Состояние (переживает рестарты) ─────────────────────────────────────

_state_lock = threading.Lock()
try:
    with open(STATE_FILE, encoding="utf-8") as f:
        STATE = json.load(f)
except Exception:  # noqa: BLE001
    STATE = {}
STATE.setdefault("chats", {})


def save_state() -> None:
    with _state_lock:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(STATE, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_FILE)


def chat_state(chat_id: int) -> dict:
    return STATE["chats"].setdefault(str(chat_id), {"session_id": None, "dir": DEFAULT_DIR})


# ─── Запуск Claude ───────────────────────────────────────────────────────

RUNNING: dict[int, subprocess.Popen] = {}  # chat_id -> процесс claude
QUEUES: dict[int, "queue.Queue[str]"] = {}
STOPPED: set[int] = set()  # чаты, где пользователь дал /stop


def stop_proc(proc: subprocess.Popen) -> None:
    """Останавливает claude вместе с дочерними процессами (кроссплатформенно)."""
    if IS_POSIX:
        os.killpg(proc.pid, signal.SIGTERM)
    else:
        proc.terminate()


def typing_loop(chat_id: int, proc: subprocess.Popen) -> None:
    while proc.poll() is None:
        try:
            api("sendChatAction", chat_id=chat_id, action="typing")
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5)


def run_claude(chat_id: int, prompt: str) -> None:
    st = chat_state(chat_id)
    workdir = st.get("dir") or DEFAULT_DIR
    if not os.path.isdir(workdir):
        send(chat_id, f"⚠️ Директория не существует: {workdir}\nСмени через /project")
        return

    cmd = [CLAUDE_BIN, "-p", "--output-format", "json", "--permission-mode", PERMISSION_MODE]
    if st.get("session_id"):
        cmd += ["--resume", st["session_id"]]
    cmd += EXTRA_ARGS + [prompt]

    log(f"chat {chat_id}: claude in {workdir}: {prompt[:80]!r}")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=IS_POSIX,
        )
    except FileNotFoundError:
        send(chat_id, f"❌ Не найден Claude Code CLI ({CLAUDE_BIN}). Проверь CLAUDE_BIN в .env")
        return

    RUNNING[chat_id] = proc
    threading.Thread(target=typing_loop, args=(chat_id, proc), daemon=True).start()
    try:
        out, err = proc.communicate(timeout=TASK_TIMEOUT)
    except subprocess.TimeoutExpired:
        stop_proc(proc)
        out, err = proc.communicate(timeout=30)
        send(chat_id, f"⏰ Задача прервана по таймауту ({TASK_TIMEOUT} c). Хвост вывода:\n{out[-1500:]}")
        return
    finally:
        RUNNING.pop(chat_id, None)

    if chat_id in STOPPED:
        STOPPED.discard(chat_id)
        send(chat_id, "🛑 Задача остановлена.")
        return

    try:
        data = json.loads(out)
    except Exception:  # noqa: BLE001
        tail = (out or "") + ("\n--- stderr ---\n" + err if err.strip() else "")
        send(chat_id, f"⚠️ Claude завершился с кодом {proc.returncode}:\n{tail[-3000:] or '(нет вывода)'}")
        return

    if data.get("session_id"):
        st["session_id"] = data["session_id"]
        save_state()

    text = data.get("result") or json.dumps(data, ensure_ascii=False)[:3000]
    footer_bits = []
    if data.get("duration_ms"):
        footer_bits.append(f"⏱ {round(data['duration_ms'] / 1000)} c")
    if data.get("num_turns"):
        footer_bits.append(f"🔄 {data['num_turns']} шагов")
    if data.get("total_cost_usd"):
        footer_bits.append(f"💲{data['total_cost_usd']:.2f}")
    if data.get("is_error"):
        text = "❌ Ошибка:\n" + text
    footer = ("\n\n" + " · ".join(footer_bits)) if footer_bits else ""
    send(chat_id, text + footer)


def worker(chat_id: int) -> None:
    q = QUEUES[chat_id]
    while True:
        prompt = q.get()
        try:
            run_claude(chat_id, prompt)
        except Exception as e:  # noqa: BLE001
            log(f"chat {chat_id}: worker error: {e}")
            try:
                send(chat_id, f"❌ Внутренняя ошибка моста: {e}")
            except Exception:  # noqa: BLE001
                pass
        q.task_done()


def enqueue(chat_id: int, prompt: str) -> None:
    if chat_id not in QUEUES:
        QUEUES[chat_id] = queue.Queue()
        threading.Thread(target=worker, args=(chat_id,), daemon=True).start()
    busy = chat_id in RUNNING or not QUEUES[chat_id].empty()
    QUEUES[chat_id].put(prompt)
    if busy:
        send(chat_id, "⏳ Claude ещё работает — задача добавлена в очередь.")


# ─── Обработка сообщений ─────────────────────────────────────────────────


def handle_command(chat_id: int, text: str) -> None:
    st = chat_state(chat_id)
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    arg = arg.strip()

    if cmd in ("/start", "/help"):
        send(chat_id, HELP + f"\n\nТекущий проект: {st.get('dir')}")
    elif cmd == "/new":
        st["session_id"] = None
        save_state()
        send(chat_id, "🆕 Новый диалог. Контекст сброшен.")
    elif cmd == "/projects":
        if PROJECTS:
            lines = [f"• {name} → {path}" for name, path in PROJECTS.items()]
            send(chat_id, "Проекты (переключение: /project имя):\n" + "\n".join(lines))
        else:
            send(chat_id, "Проекты не настроены (BRIDGE_PROJECTS в .env).\n"
                          "Можно указать путь напрямую: /project /home/user/repo")
    elif cmd == "/project":
        if not arg:
            send(chat_id, f"Текущий проект: {st.get('dir')}\nСмена: /project <имя|/путь>")
            return
        path = PROJECTS.get(arg, os.path.expanduser(arg))
        if not os.path.isdir(path):
            send(chat_id, f"❌ Нет такой директории: {path}")
            return
        st["dir"] = path
        st["session_id"] = None  # новый проект = новый контекст
        save_state()
        send(chat_id, f"📂 Проект: {path}\nКонтекст диалога сброшен.")
    elif cmd == "/status":
        running = "да" if chat_id in RUNNING else "нет"
        qsize = QUEUES[chat_id].qsize() if chat_id in QUEUES else 0
        send(chat_id,
             f"📂 Проект: {st.get('dir')}\n"
             f"🧵 Сессия Claude: {st.get('session_id') or 'нет (новый диалог)'}\n"
             f"⚙️ Задача выполняется: {running}, в очереди: {qsize}\n"
             f"🔐 Режим прав: {PERMISSION_MODE}")
    elif cmd == "/stop":
        proc = RUNNING.get(chat_id)
        if proc and proc.poll() is None:
            STOPPED.add(chat_id)
            stop_proc(proc)
            send(chat_id, "🛑 Посылаю остановку...")
        else:
            send(chat_id, "Сейчас ничего не выполняется.")
    else:
        send(chat_id, f"Неизвестная команда {cmd}. /help — справка.")


def handle_update(upd: dict) -> None:
    msg = upd.get("message") or upd.get("edited_message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    user = msg.get("from", {})
    if user.get("id") not in ALLOWED_USER_IDS:
        log(f"отказ: user {user.get('id')} ({user.get('username')}) не в белом списке")
        try:
            api("sendMessage", chat_id=chat_id, text="⛔ Доступ запрещён.")
        except Exception:  # noqa: BLE001
            pass
        return
    text = (msg.get("text") or "").strip()
    if not text:
        send(chat_id, "Я понимаю только текстовые сообщения.")
        return
    if text.startswith("/"):
        handle_command(chat_id, text)
    else:
        enqueue(chat_id, text)


def register_menu() -> None:
    commands = [
        {"command": "new", "description": "Новый диалог (сброс контекста)"},
        {"command": "project", "description": "Сменить проект/директорию"},
        {"command": "projects", "description": "Список проектов"},
        {"command": "status", "description": "Статус моста"},
        {"command": "stop", "description": "Прервать задачу"},
        {"command": "help", "description": "Справка"},
    ]
    try:
        api("setMyCommands", commands=commands)
    except Exception as e:  # noqa: BLE001
        log(f"setMyCommands failed: {e}")


def main() -> None:
    if not BOT_TOKEN:
        sys.exit("BRIDGE_BOT_TOKEN не задан. Создай бота у @BotFather и пропиши токен в .env")
    if not ALLOWED_USER_IDS:
        sys.exit("BRIDGE_ALLOWED_USER_IDS не задан. Узнай свой ID у @userinfobot и пропиши в .env — "
                 "без белого списка мост не запускается (любой мог бы управлять твоей машиной).")

    me = api("getMe")["result"]
    log(f"Мост запущен: @{me['username']}, claude={CLAUDE_BIN}, режим={PERMISSION_MODE}")
    register_menu()

    offset = STATE.get("offset", 0)
    while True:
        try:
            resp = api("getUpdates", offset=offset + 1, timeout=POLL_TIMEOUT,
                       allowed_updates=["message"])
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            log(f"getUpdates: {e}; повтор через 5 c")
            time.sleep(5)
            continue
        for upd in resp.get("result", []):
            offset = max(offset, upd["update_id"])
            STATE["offset"] = offset
            save_state()
            try:
                handle_update(upd)
            except Exception as e:  # noqa: BLE001
                log(f"handle_update error: {e}")


if __name__ == "__main__":
    main()
