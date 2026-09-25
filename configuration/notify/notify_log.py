#!/usr/bin/env python3
"""Rolling log of the last 10 Telegram notifications, from any sender.

Backs the "Сповіщення" dashboard tab: each entry keeps the chat_id/message_id
pairs Telegram returned, so a row's delete button
(script.delete_notification_slot) can call telegram_bot.delete_message for
every recipient. Every new notification should end up here: HA sends via
script.notify_all or script.notify_log_record, which use shell_command (see
configuration.yaml):

    notify_log.py append <base64-json>   # payload: {ts, title, message, chats}
    notify_log.py remove <slot>          # 1 = newest

Host scripts that call the Bot API directly (statistics/enera, statistics/oselya)
import this file and call add(). Writes are serialised with a file lock.

Stdlib only, no dependencies. The newest entry is always index 0.
"""
import base64
import fcntl
import json
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

LOG_FILE = Path(__file__).parent / "notify_log.json"
LOCK_FILE = Path(__file__).parent / ".notify_log.lock"
MAX_ENTRIES = 10


@contextmanager
def locked():
    with open(LOCK_FILE, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def load() -> list:
    if not LOG_FILE.exists():
        return []
    try:
        return json.loads(LOG_FILE.read_text()).get("rows", [])
    except (json.JSONDecodeError, OSError):
        return []


def save(rows: list) -> None:
    LOG_FILE.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=1))


def append(payload_b64: str) -> None:
    entry = json.loads(base64.b64decode(payload_b64))
    with locked():
        rows = load()
        rows.insert(0, entry)
        save(rows[:MAX_ENTRIES])


def add(title: str, message: str, chats: list) -> None:
    """Log a message sent outside HA; chats = [{"chat_id": int, "message_id": int}]."""
    if not chats:
        return
    entry = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "title": title,
             "message": message, "chats": chats}
    append(base64.b64encode(json.dumps(entry, ensure_ascii=False).encode()).decode())


def remove(slot: str) -> None:
    idx = int(slot) - 1
    with locked():
        rows = load()
        if 0 <= idx < len(rows):
            rows.pop(idx)
            save(rows)


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit("usage: notify_log.py append <base64-json> | remove <slot>")
    cmd, arg = sys.argv[1], sys.argv[2]
    if cmd == "append":
        append(arg)
    elif cmd == "remove":
        remove(arg)
    else:
        sys.exit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
