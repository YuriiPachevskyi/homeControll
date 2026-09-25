#!/usr/bin/env python3
"""Download PDF attachments from ENERA (info-bill@vin.enera.ua) emails.

Credentials come from ~/.secrets/enera_mail (mode 600): line 1 = Gmail address,
line 2 = Gmail app password. Optional line 3 = IMAP host (default imap.gmail.com).

PDFs are saved to statistics/documents/enera/<YYYY-MM-DD>_<original name>.pdf, named by the
email date. Already saved files are skipped, so the script is safe to re-run.
"""
import email
import imaplib
import re
from datetime import date as date_cls, timedelta
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from pathlib import Path

SENDER = "info-bill@vin.enera.ua"
ACTS_DIR = Path(__file__).parent.parent / "documents" / "enera"
CREDS = Path.home() / ".secrets" / "enera_mail"


def safe_name(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE).strip("_")


def connect() -> imaplib.IMAP4_SSL:
    """Log in and select the Gmail "All Mail" folder (read-only).

    Its name depends on the account language, so it is found by the \\All
    attribute; INBOX is the fallback for non-Gmail hosts.
    """
    lines = [ln.strip() for ln in CREDS.read_text().splitlines() if ln.strip()]
    user = lines[0]
    password = lines[1].replace(" ", "")  # app passwords are shown in groups of 4
    host = lines[2] if len(lines) > 2 else "imap.gmail.com"
    imap = imaplib.IMAP4_SSL(host)
    imap.login(user, password)
    box = "INBOX"
    for line in imap.list()[1]:
        if b"\\All" in line:
            box = line.decode().split(' "/" ', 1)[1]
            break
    imap.select(box, readonly=True)
    return imap


def fetch(since_days: int | None = None) -> list[Path]:
    """Save new PDFs; return the paths that were not on disk before.

    since_days limits the IMAP search to recent mail, so the hourly cron run
    does not download the whole history every time.
    """
    ACTS_DIR.mkdir(parents=True, exist_ok=True)
    imap = connect()

    criteria = ["FROM", f'"{SENDER}"']
    if since_days:
        since = (date_cls.today() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        criteria += ["SINCE", since]
    status, data = imap.search(None, *criteria)
    ids = data[0].split()
    print(f"{len(ids)} messages from {SENDER}")

    saved: list[Path] = []
    for num in ids:
        _, msg_data = imap.fetch(num, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        date = parsedate_to_datetime(msg["Date"]).strftime("%Y-%m-%d")
        subject = str(make_header(decode_header(msg.get("Subject", ""))))
        for part in msg.walk():
            filename = part.get_filename()
            if not filename:
                continue
            filename = str(make_header(decode_header(filename)))
            if not filename.lower().endswith(".pdf"):
                continue
            target = ACTS_DIR / f"{date}_{safe_name(filename)}"
            if target.exists():
                continue
            target.write_bytes(part.get_payload(decode=True))
            target.chmod(0o600)
            saved.append(target)
            print(f"saved {target.name}  (subject: {subject})")

    imap.logout()
    print(f"done, {len(saved)} new PDFs")
    return saved


if __name__ == "__main__":
    fetch()
