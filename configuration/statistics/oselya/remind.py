#!/usr/bin/env python3
"""Telegram reminders for open "Payments" to-do items, with a "✅ Виконати"
button that completes the item in HA.

- run() at the end of every sync.py run: one message per open item not
  reminded yet (tracked in reminded.json by item uid; a reopened item counts
  as new again).
- run(weekly=True) - `remind.py --weekly`, from automation
  oselya_payments_weekly_reminder (Mondays 10:00): a fresh message for every
  item still open.
- Either way, messages of items no longer open (ticked in HA or via the
  button, or deleted) are edited to say so, with the buttons removed.

The button's callback_data is "/paid <uid>"; HA's telegram_bot (polling)
turns a tap into a telegram_callback event with command "/paid" and args
[uid], handled by automation oselya_payments_paid_button, which completes
the item - and the to-do-change automation then runs sync.py as usual.
Messages are sent straight through the Bot API (not HA's notify) because
the message ids are needed to edit them later.
"""
import html
import json
import re
import sys
from pathlib import Path

import requests

import sync

REMIND_CHAT_IDS = ["481606181"]  # Kateryna only, for now (2026-09-23)
REMINDED = Path(__file__).parent / "reminded.json"


def _load() -> dict:
    return json.loads(REMINDED.read_text()) if REMINDED.exists() else {}


def _save(state: dict) -> None:
    REMINDED.write_text(json.dumps(state, ensure_ascii=False, indent=1))


def _bot(method: str, **payload) -> dict:
    r = requests.post(f"{sync.bot_url()}/{method}", json=payload, timeout=30)
    return r.json()


def _items() -> list[dict]:
    resp = sync.ha_call("todo.get_items", {"entity_id": sync.TODO_ENTITY}, return_response=True)
    return resp["service_response"][sync.TODO_ENTITY]["items"]


def _text(item: dict, done: bool = False) -> str:
    # Summary is "<object> — <bill> — <period> — <amount> грн".
    parts = item["summary"].split(" — ")
    head = " — ".join(parts[:2]) if len(parts) >= 4 else item["summary"]
    tail = " — ".join(parts[2:]) if len(parts) >= 4 else ""
    mark = "✅ Оплачено" if done else "🧾 До оплати"
    # First line = category title, like HA's telegram_bot `title`.
    return f"Платежі\n{mark}\n<b>{html.escape(head)}</b>" + (f"\n{html.escape(tail)}" if tail else "")


def _keyboard(item: dict) -> dict:
    row = [{"text": "✅ Виконати", "callback_data": f"/paid {item['uid']}"}]
    link = re.search(r'href="([^"]+)"', item.get("description") or "")
    if link:
        row.append({"text": "🧾 Квитанція", "url": link.group(1)})
    return {"inline_keyboard": [row]}


def _send(item: dict, state: dict) -> None:
    entry = state.setdefault(item["uid"], {"summary": item["summary"], "messages": []})
    chats = []
    for chat in REMIND_CHAT_IDS:
        r = _bot("sendMessage", chat_id=chat, text=_text(item), parse_mode="HTML",
                 reply_markup=_keyboard(item))
        if r.get("ok"):
            entry["messages"].append([chat, r["result"]["message_id"]])
            chats.append({"chat_id": int(chat), "message_id": r["result"]["message_id"]})
            print(f"reminded {chat}: {item['summary']}")
        else:
            print(f"reminder to {chat} FAILED for {item['summary']}: {r.get('description')}")
    if chats:
        # A later "paid" edit of a message deleted from the dashboard just fails
        # with "message to edit not found" in _close_completed - harmless.
        sync.log_notification("Платежі", f"🧾 До оплати: {item['summary']}", chats)


def _close_completed(items: list[dict], state: dict) -> None:
    """Edit the messages of items that are no longer open."""
    open_uids = {i["uid"] for i in items if i["status"] == "needs_action"}
    by_uid = {i["uid"]: i for i in items}
    for uid, entry in list(state.items()):
        if uid in open_uids or entry.get("closed"):
            continue
        item = by_uid.get(uid, {"summary": entry["summary"]})
        done = uid in by_uid  # still on the list = completed; gone = deleted
        for chat, message_id in entry["messages"]:
            text = _text(item, done=True) if done else f"Платежі\n🗑 Задачу видалено\n<s>{html.escape(entry['summary'])}</s>"
            r = _bot("editMessageText", chat_id=chat, message_id=message_id, text=text, parse_mode="HTML")
            if not r.get("ok") and "not modified" not in (r.get("description") or ""):
                print(f"edit FAILED for {entry['summary']}: {r.get('description')}")
        entry["closed"] = True


def run(weekly: bool = False) -> None:
    state = _load()
    try:
        items = _items()
    except Exception as e:
        print(f"reminders skipped, todo.get_items failed: {e}")
        return
    for item in items:
        entry = state.get(item["uid"])
        # Never reminded, or reopened (unticked) after its messages were closed.
        if item["status"] == "needs_action" and (weekly or entry is None or entry.get("closed")):
            if entry is not None:
                entry["closed"] = False
            _send(item, state)
    _close_completed(items, state)
    _save(state)


if __name__ == "__main__":
    run(weekly="--weekly" in sys.argv)
