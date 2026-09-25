#!/usr/bin/env python3
"""Hourly job (cron): pick up new ENERA acts, refresh tariffs, send the PDF,
and forward planned-outage notices from the utility cabinet (esvitlo.py).

1. fetch_acts.fetch()   - new PDFs from the mailbox into statistics/documents/enera/
2. parse_acts           - rebuild enera/tariffs.json (also fixes months that
                          failed to parse earlier)
3. every act not yet in enera/sent.json is sent to Telegram (PDF + caption with
   the payout); a failed send is retried on the next run
4. Home Assistant is told to re-read sensor.enera_green_tariffs

`sync.py --mark-all-sent` records every PDF already on disk as sent (used once
so history is not re-sent).
"""
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import esvitlo
import fetch_acts
import parse_acts

BASE = Path(__file__).parent
CONFIG = BASE.parent.parent  # .../configuration (statistics/enera moved a level deeper on 2026-09-22)
SENT = BASE / "sent.json"
sys.path.insert(0, str(CONFIG / "notify"))
import notify_log  # noqa: E402  (dashboard "Сповіщення" log)
CHAT_IDS = [
    "612533502",  # Yurii P
    "481606181",  # Kateryna
    "802313549",  # Nataliya
]
MONTHS = ["січень", "лютий", "березень", "квітень", "травень", "червень",
          "липень", "серпень", "вересень", "жовтень", "листопад", "грудень"]


def bot_url() -> str:
    entries = json.loads((CONFIG / ".storage/core.config_entries").read_text())["data"]["entries"]
    token = next(e["data"]["api_key"] for e in entries if e["domain"] == "telegram_bot")
    return f"https://api.telegram.org/bot{token}"


def send_pdf_to(path: Path, caption: str, chat: str) -> int | None:
    """Return the Telegram message_id on success, None on failure."""
    # Markdown makes the payout line bold; if Telegram rejects the markup,
    # deliver the same caption as plain text rather than retry forever.
    for cap, mode in ((caption, "Markdown"), (caption.replace("*", ""), None)):
        cmd = ["curl", "-s", "-m", "60", "-F", f"chat_id={chat}", "-F", f"caption={cap}",
               "-F", f"document=@{path}", f"{bot_url()}/sendDocument"]
        if mode:
            cmd[-1:-1] = ["-F", f"parse_mode={mode}"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        try:
            resp = json.loads(r.stdout)
            if resp.get("ok", False):
                return resp["result"]["message_id"]
        except json.JSONDecodeError:
            pass
    return None


def send_text_to(text: str, chat: str) -> int | None:
    """Return the Telegram message_id on success, None on failure."""
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    try:
        resp = json.load(urllib.request.urlopen(
            urllib.request.Request(f"{bot_url()}/sendMessage", data=data), timeout=30))
        return resp["result"]["message_id"] if resp.get("ok", False) else None
    except Exception as e:
        print(f"sendMessage to {chat} failed: {e}")
        return None


def send_pdf(path: Path, caption: str) -> bool:
    """Send to every chat (ad-hoc use); the cron job tracks each chat separately."""
    return all([send_pdf_to(path, caption, c) for c in CHAT_IDS])


def send_text(text: str) -> bool:
    return all([send_text_to(text, c) for c in CHAT_IDS])


def log_notification(title: str, message: str, chats: list) -> None:
    """Add a row to the dashboard's "Сповіщення" log, same as script.notify_all
    does, so the message is listed there and its delete button works."""
    notify_log.add(title, message, chats)
    refresh_ha_sensor("sensor.telegram_notify_log")


def deliver(key: str, send_one, sent: set, title: str, message: str) -> int:
    """Send to each chat that has not got `key` yet; return the number of failures.

    Progress is stored per chat ("<key>@<chat>") so a failure for one person
    never makes the others receive the message twice. A bare `key` means
    "delivered to everyone" (this is how entries from before the family chats
    were added are read).
    """
    if key in sent:
        return 0
    failed = 0
    chats = []
    for chat in CHAT_IDS:
        tag = f"{key}@{chat}"
        if tag in sent:
            continue
        message_id = send_one(chat)
        if message_id:
            sent.add(tag)
            chats.append({"chat_id": int(chat), "message_id": message_id})
        else:
            failed += 1
    if not failed:
        sent.add(key)
    SENT.write_text(json.dumps(sorted(sent), indent=1))
    if chats:
        log_notification(title, message, chats)
    return failed


def caption_for(path: Path) -> str:
    """Two-line message in the house style; falls back to a plain title."""
    now = datetime.now().strftime("%H:%M")
    try:
        month, rec = parse_acts.parse(path)
    except Exception as e:  # layout changed - still deliver the PDF
        print(f"parse failed for {path.name}: {e}")
        return f"🕐 {now} 📄 Акт!!!\nСуму не вдалося прочитати автоматично"
    y, m = month.split("-")
    title = f"🕐 {now} 📄 Акт за {MONTHS[int(m) - 1]} {y}!!!"
    if rec.get("green_tariff"):
        return f"{title}\n💰 *До виплати: {rec['payout']:.2f} ₴*"
    return f"{title}\n*Виплати немає*"


def refresh_ha_sensor(entity_id: str = "sensor.enera_green_tariffs") -> None:
    try:
        token = (Path.home() / ".ha_token").read_text().strip()
        req = urllib.request.Request(
            "http://localhost:8123/api/services/homeassistant/update_entity",
            data=json.dumps({"entity_id": entity_id}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20)
    except Exception as e:  # the sensor also polls hourly on its own
        print(f"HA sensor refresh failed: {e}")


def main() -> int:
    acts = lambda: sorted(fetch_acts.ACTS_DIR.glob("*.pdf"))
    if "--mark-all-sent" in sys.argv:
        SENT.write_text(json.dumps(sorted(p.name for p in acts()), indent=1))
        print(f"marked {len(acts())} acts as sent")
        return 0

    fetch_acts.fetch(since_days=45)
    parse_acts.main()
    refresh_ha_sensor()

    sent = set(json.loads(SENT.read_text())) if SENT.exists() else set()
    failed = 0
    for pdf in acts():
        caption = caption_for(pdf) if pdf.name not in sent else ""
        n = deliver(pdf.name, lambda chat, p=pdf, c=caption: send_pdf_to(p, c, chat), sent,
                    "ENERA", caption.replace("*", ""))
        if n:
            failed += n
            print(f"send FAILED for {pdf.name} to {n} chat(s), will retry")
        elif caption:
            print(f"sent {pdf.name}")

    # Planned outage notices from the utility cabinet (short text, no PDF).
    for key, text in esvitlo.new_notices(sent):
        n = deliver(key, lambda chat, t=text: send_text_to(t, chat), sent, "Світло", text)
        if n:
            failed += n
            print(f"outage notice send FAILED to {n} chat(s), will retry")
        else:
            print(f"sent outage notice {key[:40]}")
    return 1 if failed else 0

if __name__ == "__main__":
    os.chdir(BASE)
    sys.exit(main())
