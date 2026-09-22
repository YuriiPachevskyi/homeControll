#!/usr/bin/env python3
"""Rolling log of the last 10 Telegram notifications sent via script.notify_all.

Backs the "Сповіщення" dashboard tab: each entry keeps the chat_id/message_id
pairs telegram_bot.send_message returned, so a row's delete button
(script.delete_notification_slot) can call telegram_bot.delete_message for
every recipient. Invoked from shell_command (see configuration.yaml):

    notify_log.py append <base64-json>   # payload: {ts, title, message, chats}
    notify_log.py remove <slot>          # 1 = newest

Stdlib only, no dependencies. The newest entry is always index 0.
"""
import base64
import json
import sys
from pathlib import Path

LOG_FILE = Path(__file__).parent / "notify_log.json"
MAX_ENTRIES = 10


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
    rows = load()
    rows.insert(0, entry)
    save(rows[:MAX_ENTRIES])


def remove(slot: str) -> None:
    idx = int(slot) - 1
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
