"""Per-source bill fetchers, dispatched by sync.py based on objects.yaml's
bill.source. Each fetcher's job is only to make sure RECEIPTS/parsed rows
exist on disk for a bill up through the current month - parsing/aggregation
stays in sync.py so every source ends up in the same row shape.
"""
import email
import imaplib
from datetime import date, timedelta
from email.header import decode_header, make_header
from pathlib import Path

import client
import parse_koec
import parse_receipt

RECEIPTS = Path(__file__).parent.parent / "documents" / "oselya"


def months_to_try(now: date):
    y, m = 2025, 1
    while (y, m) <= (now.year, now.month):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def fetch_oselya_bill(oselya_client: client.OselyaClient, bill_key: str, bill_cfg: dict) -> None:
    """Download any not-yet-fetched monthly PDF for this account into statistics/documents/oselya/."""
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    for y, m in months_to_try(date.today()):
        target = RECEIPTS / f"{bill_key}_{y}-{m:02d}.pdf"
        if target.exists():
            continue
        pdf = oselya_client.fetch_receipt(bill_cfg["account_id"], m, y)
        if pdf is None:
            continue  # not issued (yet) - normal, not an error
        target.write_bytes(pdf)
        target.chmod(0o600)
        print(f"fetched {target.name}")


def parse_oselya_bill_rows(bill_key: str) -> list[dict]:
    """Parse every downloaded PDF for this bill into raw rows (pre-finishing)."""
    rows = []
    for pdf in sorted(RECEIPTS.glob(f"{bill_key}_????-??.pdf")):
        try:
            rows.append(parse_receipt.parse(pdf.read_bytes()))
        except parse_receipt.ParseError as e:
            print(f"parse failed for {pdf.name}: {e}")
    return rows


def _mail_connect(creds_file: str) -> imaplib.IMAP4_SSL:
    """Log in (read-only) to Gmail's "All Mail" folder. Its name depends on
    the account language, so it's found by the \\All attribute (same as
    statistics/enera/fetch_acts.py). creds_file: line 1 = address, line 2 =
    Google app password; it only exists on the host, not in the HA container.
    """
    lines = [ln.strip() for ln in Path(creds_file).expanduser().read_text().splitlines() if ln.strip()]
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(lines[0], lines[1].replace(" ", ""))
    box = "INBOX"
    for line in imap.list()[1]:
        if b"\\All" in line:
            box = line.decode().split(' "/" ', 1)[1]
            break
    imap.select(box, readonly=True)
    return imap


def fetch_koec_mail_bill(bill_key: str, bill_cfg: dict) -> None:
    """Save KOEC/ONDO electricity bill PDFs mailed by bill_cfg["sender"] as
    <bill_key>_<period>.pdf - the period comes from the PDF itself (a bill
    for August arrives in September). Bills for another account are skipped.
    The whole mailbox is searched until the first PDF exists, then only the
    last 60 days.
    """
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    criteria = ["FROM", '"' + bill_cfg["sender"] + '"']
    if any(RECEIPTS.glob(f"{bill_key}_????-??.pdf")):
        criteria += ["SINCE", (date.today() - timedelta(days=60)).strftime("%d-%b-%Y")]
    imap = _mail_connect(bill_cfg["mail_credentials"])
    try:
        ids = imap.search(None, *criteria)[1][0].split()
        for num in ids:
            msg = email.message_from_bytes(imap.fetch(num, "(BODY.PEEK[])")[1][0][1])
            for part in msg.walk():
                name = part.get_filename()
                if not name or not str(make_header(decode_header(name))).lower().endswith(".pdf"):
                    continue
                pdf = part.get_payload(decode=True)
                try:
                    row = parse_koec.parse(pdf)
                except parse_receipt.ParseError as e:
                    print(f"{bill_key}: unparsable PDF {name!r} in mail {msg['Date']}: {e}")
                    continue
                if row["account_id"] != bill_cfg["account_id"]:
                    print(f"{bill_key}: skipped bill for other account {row['account_id']}")
                    continue
                target = RECEIPTS / f"{bill_key}_{row['period']}.pdf"
                if target.exists():
                    continue
                target.write_bytes(pdf)
                target.chmod(0o600)
                print(f"fetched {target.name}")
    finally:
        imap.logout()


def parse_koec_mail_bill_rows(bill_key: str) -> list[dict]:
    rows = []
    for pdf in sorted(RECEIPTS.glob(f"{bill_key}_????-??.pdf")):
        try:
            rows.append(parse_koec.parse(pdf.read_bytes()))
        except parse_receipt.ParseError as e:
            print(f"parse failed for {pdf.name}: {e}")
    return rows


def manual_fixed_rate_rows(bill_cfg: dict, existing_periods: set[str]) -> list[dict]:
    """Synthesize rows for a manual_fixed_rate bill - one per month at the
    period's rate, for any period in range that doesn't already have a row.
    No PDF, no ledger: paid/status is set entirely by the to-do checkbox.
    """
    today = date.today()
    rows = []
    for rp in bill_cfg.get("rate_periods", []):
        vy, vm = (int(x) for x in rp["valid_from"].split("-"))
        if rp.get("valid_to"):
            ey, em = (int(x) for x in rp["valid_to"].split("-"))
        else:
            ey, em = today.year, today.month
        ey, em = min((ey, em), (today.year, today.month))
        y, m = vy, vm
        while (y, m) <= (ey, em):
            period = f"{y}-{m:02d}"
            if period not in existing_periods:
                rows.append({
                    "period": period, "account_id": None,
                    "debt": 0.0, "avans": 0.0, "paid": 0.0, "accrued": rp["rate"],
                    "recalc": 0.0, "total_due": rp["rate"],
                    "secondary_label": None, "secondary_due": 0.0,
                })
            m += 1
            if m > 12:
                m, y = 1, y + 1
    return rows
