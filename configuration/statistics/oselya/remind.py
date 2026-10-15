#!/usr/bin/env python3
"""Telegram messages for open "Payments" to-do items: the receipt PDF itself
(when the bill has one) with a "✅ Виконати" button per open item - ONE
message per receipt, since 2026-10-06 (before, the PDF and the reminder
with the button were two separate messages). The PDF is attached rather
than linked because signed /api/documents links expire after 7 days.

- run() at the end of every sync.py run: one message per receipt (or per
  item, for bills without a PDF) whose open items were not sent yet (state
  in reminded.json; a reopened item counts as new again).
- run(weekly=True) - `remind.py --weekly`, from automation
  oselya_payments_weekly_reminder (Mondays 10:00): a fresh message for
  everything still open.
- Either way, sent messages are kept up to date: a paid item gets a ✅ and
  loses its button, a deleted one is struck out, and when nothing is left
  open the header says "✅ Оплачено".

A receipt's main amount and its secondary one (Пеня/Інфляція) are separate
to-do items (separate payments), so such a message has two buttons.

The button's callback_data is "/paid <uid>"; HA's telegram_bot (polling)
turns a tap into a telegram_callback event with command "/paid" and args
[uid], handled by automation oselya_payments_paid_button, which completes
the item and clears the buttons - and the to-do-change automation then runs
sync.py, whose run() here re-renders the message (restoring the buttons of
items still open). Sent straight through the Bot API (not HA's notify)
because the message ids are needed to edit them later.
"""
import html
import json
import sys
from pathlib import Path

import requests

import sources
import sync

REMIND_CHAT_IDS = sync.CHAT_IDS  # Yurii + Kateryna (Kateryna only until 2026-10-06)
REMINDED = Path(__file__).parent / "reminded.json"


def _load() -> dict:
    state = json.loads(REMINDED.read_text()) if REMINDED.exists() else {}
    if "groups" not in state:
        # Pre-2026-10-06 format: {uid: {summary, messages: [[chat, id]], closed}},
        # one text message per item.
        state = {"groups": [
            {"receipt": None, "uids": [uid], "summaries": {uid: e["summary"]},
             "messages": [[chat, mid, "text"] for chat, mid in e["messages"]],
             "closed": bool(e.get("closed"))}
            for uid, e in state.items()]}
    return state


def _save(state: dict) -> None:
    REMINDED.write_text(json.dumps(state, ensure_ascii=False, indent=1))


def _bot(method: str, files: dict | None = None, **payload) -> dict:
    url = f"{sync.bot_url()}/{method}"
    if files:
        data = {k: json.dumps(v) if isinstance(v, dict) else v for k, v in payload.items()}
        r = requests.post(url, data=data, files=files, timeout=60)
    else:
        r = requests.post(url, json=payload, timeout=30)
    return r.json()


def _items() -> list[dict]:
    resp = sync.ha_call("todo.get_items", {"entity_id": sync.TODO_ENTITY}, return_response=True)
    return resp["service_response"][sync.TODO_ENTITY]["items"]


def _split(summary: str) -> tuple[str, str, str, str] | None:
    # Summary is "<object> — <bill> — <period> — <amount> грн".
    parts = summary.split(" — ")
    return tuple(parts) if len(parts) == 4 else None


def _render(group: dict, by_uid: dict) -> tuple[str, dict]:
    """Caption/text and keyboard for a group, from the items' current state."""
    open_uids = [u for u in group["uids"] if by_uid.get(u, {}).get("status") == "needs_action"]
    first = _split(group["summaries"][group["uids"][0]])
    head = f"{first[0]} — {first[1]}" if first else group["summaries"][group["uids"][0]]
    lines = ["Платежі", "🧾 До оплати" if open_uids else "✅ Оплачено", f"<b>{html.escape(head)}</b>"]
    buttons = []
    for uid in group["uids"]:
        summary = group["summaries"][uid]
        parts = _split(summary)
        if parts:
            obj, purpose, period, amount = parts
            if first and purpose != first[1]:
                # Secondary amount, e.g. "Консьєрж (Пеня)" -> "Пеня" - a separate payment.
                extra = purpose.removeprefix(first[1]).strip(" ()")
                line = f"➕ {extra}: {amount} (окремий платіж!)"
                label = f"✅ {extra} — {amount.removesuffix(' грн')}"
            else:
                line = f"{period} — {amount}"
                label = "✅ Виконати"
        else:
            line = label = summary
        if uid not in by_uid:
            line = f"<s>{html.escape(line)}</s> 🗑"
        elif uid in open_uids:
            line = html.escape(line)
            buttons.append([{"text": label if len(group["uids"]) > 1 else "✅ Виконати",
                             "callback_data": f"/paid {uid}"}])
        else:
            line = f"✅ {html.escape(line)}"
        lines.append(line)
    return "\n".join(lines), {"inline_keyboard": buttons}


def _send(group: dict, by_uid: dict, state: dict) -> None:
    text, keyboard = _render(group, by_uid)
    pdf = sources.RECEIPTS / f"{group['receipt']}.pdf" if group["receipt"] else None
    group["messages"] = []
    chats = []
    for chat in REMIND_CHAT_IDS:
        if pdf and pdf.exists():
            with open(pdf, "rb") as f:
                r = _bot("sendDocument", files={"document": (pdf.name, f, "application/pdf")},
                         chat_id=chat, caption=text, parse_mode="HTML", reply_markup=keyboard)
            kind = "doc"
        else:
            r = _bot("sendMessage", chat_id=chat, text=text, parse_mode="HTML", reply_markup=keyboard)
            kind = "text"
        if r.get("ok"):
            group["messages"].append([chat, r["result"]["message_id"], kind])
            chats.append({"chat_id": int(chat), "message_id": r["result"]["message_id"]})
            print(f"reminded {chat}: {' | '.join(group['summaries'].values())}")
        else:
            print(f"reminder to {chat} FAILED for {group['summaries']}: {r.get('description')}")
    if not chats:
        return  # not recorded - retried on the next run
    group["rendered"] = text + json.dumps(keyboard)
    state["groups"].append(group)
    if chats:
        # A later edit of a message deleted from the dashboard just fails with
        # "message to edit not found" in _refresh - harmless.
        sync.log_notification("Платежі", "🧾 До оплати: " + "; ".join(group["summaries"].values()), chats)


def _refresh(state: dict, by_uid: dict) -> None:
    """Re-render sent messages whose items changed; close finished groups."""
    for group in state["groups"]:
        if group.get("closed"):
            continue
        text, keyboard = _render(group, by_uid)
        if group.get("rendered") != text + json.dumps(keyboard):
            for chat, message_id, kind in group["messages"]:
                if kind == "doc":
                    r = _bot("editMessageCaption", chat_id=chat, message_id=message_id, caption=text,
                             parse_mode="HTML", reply_markup=keyboard)
                else:
                    r = _bot("editMessageText", chat_id=chat, message_id=message_id, text=text,
                             parse_mode="HTML", reply_markup=keyboard)
                if not r.get("ok") and "not modified" not in (r.get("description") or ""):
                    print(f"edit FAILED for {group['summaries']}: {r.get('description')}")
            group["rendered"] = text + json.dumps(keyboard)
        if not keyboard["inline_keyboard"]:
            group["closed"] = True


def _new_groups(items: list[dict], state: dict, weekly: bool) -> list[dict]:
    """Open items that need a message, grouped by receipt."""
    covered = set() if weekly else {u for g in state["groups"] if not g.get("closed") for u in g["uids"]}
    todo_added = json.loads(sync.TODO_ADDED.read_text()) if sync.TODO_ADDED.exists() else {}
    key_by_text = {text: key for key, text in todo_added.items()}
    payments = json.loads(sync.PAYMENTS.read_text())
    receipt_by_key = {e["todo_key"]: e.get("receipt") for e in payments.get("outstanding", [])}
    groups: dict[str, dict] = {}
    for item in items:
        if item["status"] != "needs_action" or item["uid"] in covered:
            continue
        todo_key = key_by_text.get(item["summary"])
        receipt = receipt_by_key.get(todo_key) if todo_key else None
        group = groups.setdefault(receipt or item["uid"],
                                  {"receipt": receipt, "uids": [], "summaries": {}, "messages": []})
        group["uids"].append(item["uid"])
        group["summaries"][item["uid"]] = item["summary"]
    for group in groups.values():
        # Main amount first, then Пеня/Інфляція.
        group["uids"].sort(key=lambda u: "(" in (_split(group["summaries"][u]) or ("", ""))[1])
    return list(groups.values())


def run(weekly: bool = False) -> None:
    state = _load()
    try:
        items = _items()
    except Exception as e:
        print(f"reminders skipped, todo.get_items failed: {e}")
        return
    by_uid = {i["uid"]: i for i in items}
    _refresh(state, by_uid)
    for group in _new_groups(items, state, weekly):
        _send(group, by_uid, state)
    # Forget long-finished groups, keep the file small.
    state["groups"] = [g for g in state["groups"] if not g.get("closed")] + \
        [g for g in state["groups"] if g.get("closed")][-50:]
    _save(state)


if __name__ == "__main__":
    run(weekly="--weekly" in sys.argv)
