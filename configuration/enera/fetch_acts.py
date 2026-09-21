#!/usr/bin/env python3
"""Download PDF attachments from ENERA (info-bill@vin.enera.ua) emails.

Credentials come from ~/.enera_mail (mode 600): line 1 = Gmail address,
line 2 = Gmail app password. Optional line 3 = IMAP host (default imap.gmail.com).

PDFs are saved to enera/acts/<YYYY-MM-DD>_<original name>.pdf, named by the
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
ACTS_DIR = Path(__file__).parent / "acts"
CREDS = Path.home() / ".enera_mail"


def safe_name(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE).strip("_")


def fetch(since_days: int | None = None) -> list[Path]:
    """Save new PDFs; return the paths that were not on disk before.

    since_days limits the IMAP search to recent mail, so the hourly cron run
    does not download the whole history every time.
    """
    lines = [ln.strip() for ln in CREDS.read_text().splitlines() if ln.strip()]
    user = lines[0]
    password = lines[1].replace(" ", "")  # app passwords are shown in groups of 4
    host = lines[2] if len(lines) > 2 else "imap.gmail.com"

    ACTS_DIR.mkdir(exist_ok=True)
    imap = imaplib.IMAP4_SSL(host)
    imap.login(user, password)
    # "All Mail" also finds messages that were archived or moved to a label.
    status, _ = imap.select('"[Gmail]/All Mail"', readonly=True)
    if status != "OK":
        imap.select("INBOX", readonly=True)

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
