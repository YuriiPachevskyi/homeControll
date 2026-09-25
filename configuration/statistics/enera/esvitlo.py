"""Planned power-outage notices from the utility cabinet (e-svitlo) -> short text.

The emails contain the customer's address, account number and EIC code; only
the street and house number and the outage window are forwarded.
"""
import email
import re
from email.header import decode_header, make_header
from pathlib import Path

import fetch_acts

SENDER = "cabinet@vn.e-svitlo.com.ua"
WINDOW = re.compile(
    r"з (\d\d)-(\d\d)-(\d{4}) (\d\d:\d\d) по (\d\d)-(\d\d)-(\d{4}) (\d\d:\d\d)"
)
ADDRESS = re.compile(r"за адресою:\s*(.+?),\s*особовий рахунок")
# Only notices for the addresses in this host-only file are forwarded; the
# mailbox gets notices for several accounts of the same owner. One address per
# line, matched against "вул. <street> <house>", optionally followed by
# "| <chat_id>,<chat_id>" to send that address to those chats only:
#     Назва 10
#     Інша назва 19 | 123456789
# The repo is public, so the addresses stay out of it. No file = forward
# everything to everyone; a notice without a parseable address also goes to
# everyone, so a format change never hides an outage.
WATCH_FILE = Path.home() / ".secrets" / "esvitlo_watch"


def watched() -> list[tuple[str, list[str] | None]]:
    """[(address, chat ids or None = everyone)] from WATCH_FILE."""
    try:
        lines = WATCH_FILE.read_text().splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in filter(None, (l.strip() for l in lines)):
        addr, _, chats = line.partition("|")
        ids = [c.strip() for c in chats.split(",") if c.strip()]
        out.append((addr.strip(), ids or None))
    return out


def recipients(addr: str, watch: list) -> list[str] | None | bool:
    """Chat ids for a notice at `addr`: None = everyone, False = not watched."""
    if not addr or not watch:
        return None
    hits = [chats for a, chats in watch if a in addr]
    if not hits:
        return False
    if any(chats is None for chats in hits):
        return None
    return sorted({c for chats in hits for c in chats})


def body_text(msg) -> str:
    for part in msg.walk():
        if part.get_content_type() in ("text/plain", "text/html") and not part.get_filename():
            raw = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
            raw = re.sub(r"<(script|style).*?</\1>", "", raw, flags=re.S)
            return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).strip()
    return ""


def street(text: str) -> str:
    """'вул. Назва 19, ' from the notice address; city, flat and account are dropped."""
    a = ADDRESS.search(text)
    if not a:
        return ""
    addr = re.sub(r"^м\.\s*\S+\s+", "", a.group(1))  # city
    addr = re.sub(r"\s*кв\.?\s*\S+$", "", addr)      # flat
    return f"{addr}, " if addr else ""


def format_notice(text: str) -> str:
    """Two-line message in the house style; generic fallback if unparsable."""
    w = WINDOW.search(text)
    if not w:
        return f"⚡ Лист про відключення світла\nДеталі в пошті"
    d1, m1, _y1, t1, d2, m2, _y2, t2 = w.groups()
    if (d1, m1) == (d2, m2):
        title, span = f"{d1}.{m1}", f"{t1}–{t2}"
    else:
        title, span = f"{d1}.{m1}–{d2}.{m2}", f"з {d1}.{m1} {t1} до {d2}.{m2} {t2}"
    return f"⚡ Відключення світла {title}\n{street(text)}{span}"


def new_notices(sent: set[str], since_days: int = 45) -> list[tuple[str, str, list[str] | None]]:
    """Return [(dedupe key, message text, chat ids or None = everyone)] for
    notices not yet forwarded."""
    from datetime import date, timedelta
    imap = fetch_acts.connect()
    since = (date.today() - timedelta(days=since_days)).strftime("%d-%b-%Y")
    _, data = imap.search(None, "FROM", f'"{SENDER}"', "SINCE", since)
    out = []
    watch = watched()
    for num in data[0].split():
        _, md = imap.fetch(num, "(RFC822)")
        msg = email.message_from_bytes(md[0][1])
        key = "esvitlo:" + str(make_header(decode_header(msg.get("Message-ID", num.decode()))))
        if key in sent:
            continue
        text = body_text(msg)
        chats = recipients(street(text), watch)
        if chats is False:
            continue
        out.append((key, format_notice(text), chats))
    imap.logout()
    return out
