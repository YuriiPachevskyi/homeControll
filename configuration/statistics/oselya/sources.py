"""Per-source bill fetchers, dispatched by sync.py based on objects.yaml's
bill.source. Each fetcher's job is only to make sure RECEIPTS/parsed rows
exist on disk for a bill up through the current month - parsing/aggregation
stays in sync.py so every source ends up in the same row shape.
"""
import email
import imaplib
import json
from datetime import date, datetime, timedelta
from email.header import decode_header, make_header
from pathlib import Path

import brovk_water
import client
import koec_cabinet
import parse_koec
import parse_receipt
import rates

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


FIRST_PERIOD = "2025-01"  # history starts here for every object


def _cabinet_cache(bill_key: str) -> Path:
    # Next to the PDFs: gitignored, backed up, and readable from the HA
    # container (the --reconcile-only run has no cabinet credentials).
    return RECEIPTS / f"{bill_key}.cabinet.json"


def fetch_koec_cabinet_bill(bill_key: str, bill_cfg: dict) -> None:
    """Refresh the cached bills/charges/payments tables from the KOEC cabinet
    and save the latest bill's PDF (the only one the cabinet offers) as
    <bill_key>_<period>.pdf, period taken from the PDF itself.
    """
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    cab = koec_cabinet.KoecCabinet(bill_cfg["credentials"])
    # One year before FIRST_PERIOD so the first months' payments have context.
    snap = cab.snapshot(int(FIRST_PERIOD[:4]) - 1)
    cache = _cabinet_cache(bill_key)
    cache.write_text(json.dumps(snap, ensure_ascii=False, indent=1))
    cache.chmod(0o600)
    pdf = cab.current_bill_pdf()
    row = parse_koec.parse(pdf)
    if row["account_id"] != bill_cfg["account_id"]:
        print(f"{bill_key}: cabinet bill is for account {row['account_id']}, not saved")
        return
    target = RECEIPTS / f"{bill_key}_{row['period']}.pdf"
    if not target.exists():
        target.write_bytes(pdf)
        target.chmod(0o600)
        print(f"fetched {target.name}")


def _prev_month(iso_date: str) -> str:
    y, m = int(iso_date[:4]), int(iso_date[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def parse_koec_cabinet_bill_rows(bill_key: str, bill_cfg: dict) -> list[dict]:
    """Rows from the cached cabinet tables. A bill issued in month M is for
    period M-1. It counts as paid when the payments made between its issue
    date and the next bill's reach its amount, when there's nothing to pay,
    or when a later bill is paid (a later bill's amount includes any debt
    carried over). `source_paid` lets sync.py mark it paid without a to-do
    checkmark.
    """
    cache = _cabinet_cache(bill_key)
    if not cache.exists():
        return []
    snap = json.loads(cache.read_text())
    bills, payments = snap["bills"], snap["payments"]
    rows = []
    for i, b in enumerate(bills):
        until = bills[i + 1]["date"] if i + 1 < len(bills) else "9999-12-31"
        window = [p for p in payments if b["date"] <= p["date"] < until]
        paid_sum = round(sum(p["amount"] for p in window), 2)
        fee = snap["fees"].get(_prev_month(b["date"]), {})
        rows.append({
            "period": _prev_month(b["date"]), "account_id": bill_cfg["account_id"],
            "debt": 0.0, "avans": 0.0, "paid": paid_sum,
            "accrued": fee.get("accrued", b["amount"]), "recalc": 0.0,
            "total_due": b["amount"], "secondary_label": None, "secondary_due": 0.0,
            "kwh": fee.get("kwh"),
            "source_paid": b["amount"] <= 0.005 or paid_sum >= b["amount"] - 0.005,
            "source_paid_date": window[-1]["date"] if window else None,
        })
    for i in range(len(rows) - 2, -1, -1):  # a paid later bill settles the earlier ones
        if rows[i + 1]["source_paid"] and rows[i + 1]["total_due"] > 0:
            rows[i]["source_paid"] = True
    return [r for r in rows if r["period"] >= FIRST_PERIOD]


def fetch_brovk_water_bill(bill_key: str, bill_cfg: dict) -> None:
    """Merge the site's 12-month service tables into the cache (older months
    drop off the site, the cache keeps them) and save last month's bill PDF
    as <bill_key>_<period>.pdf.
    """
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    # The address is kept out of the (public) repo: with the account number it
    # opens the account without a password.
    creds = json.loads(Path(bill_cfg["credentials"]).expanduser().read_text())
    site = brovk_water.BrovkWater(creds["address"], bill_cfg["account_id"])
    cache = _cabinet_cache(bill_key)
    snap = json.loads(cache.read_text()) if cache.exists() else {"services": {}}
    for service in brovk_water.SERVICES:
        rows = snap["services"].setdefault(service, {})
        for r in site.service_table(service):
            rows[r["period"]] = r
    snap["fetched"] = datetime.now().isoformat(timespec="seconds")
    cache.write_text(json.dumps(snap, ensure_ascii=False, indent=1))
    cache.chmod(0o600)
    pdf = site.last_month_bill_pdf(creds["print_name"])
    bill = brovk_water.parse_bill(pdf)
    if bill["account_id"] != bill_cfg["account_id"]:
        print(f"{bill_key}: bill is for account {bill['account_id']}, not saved")
        return
    target = RECEIPTS / f"{bill_key}_{bill['period']}.pdf"
    if not target.exists():
        target.write_bytes(pdf)
        target.chmod(0o600)
        print(f"fetched {target.name}")


def parse_brovk_water_bill_rows(bill_key: str, bill_cfg: dict) -> list[dict]:
    """One row per period with the three services netted, as the printed bill
    does: total_due = sum of month-end balances (negative = credit). Paid when
    there's nothing to pay or later months' payments cover it.
    """
    cache = _cabinet_cache(bill_key)
    if not cache.exists():
        return []
    services = json.loads(cache.read_text())["services"].values()
    periods = sorted({p for rows in services for p in rows})
    rows = []
    for period in periods:
        here = [rows_[period] for rows_ in services if period in rows_]
        total = lambda k: round(sum(r[k] for r in here), 2)
        rows.append({
            "period": period, "account_id": bill_cfg["account_id"],
            "debt": total("start"), "avans": 0.0, "paid": total("paid"),
            "accrued": total("accrued"), "recalc": -total("recalc"),
            "total_due": total("end"), "secondary_label": None, "secondary_due": 0.0,
        })
    for i, r in enumerate(rows):
        later_paid = sum(x["paid"] for x in rows[i + 1:])
        r["source_paid"] = r["total_due"] <= 0.005 or later_paid >= r["total_due"] - 0.005
        r["source_paid_date"] = None
    return [r for r in rows if r["period"] >= FIRST_PERIOD]


def manual_fixed_rate_rows(bill_key: str) -> list[dict]:
    """Rows for a manual_fixed_rate bill from its tariffs in rates.yaml (see
    rates.py) - one per month at that month's rate, up to last month like the
    other bills (August's bills arrive in September). Every month is
    recomputed on each run, so editing a tariff also corrects months already
    in the table; sync.py keeps their paid marks.
    No PDF, no ledger: paid/status is set entirely by the to-do checkbox.
    """
    today = date.today()
    last = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    rows = []
    for rp in rates.load().get(bill_key, []):
        vy, vm = (int(x) for x in rp["valid_from"].split("-"))
        if rp.get("valid_to"):
            ey, em = (int(x) for x in rp["valid_to"].split("-"))
        else:
            ey, em = last
        ey, em = min((ey, em), last)
        y, m = vy, vm
        while (y, m) <= (ey, em):
            period = f"{y}-{m:02d}"
            if period >= FIRST_PERIOD:
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
