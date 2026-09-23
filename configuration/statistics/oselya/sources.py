"""Per-source bill fetchers, dispatched by sync.py based on objects.yaml's
bill.source. Each fetcher's job is only to make sure RECEIPTS/parsed rows
exist on disk for a bill up through the current month - parsing/aggregation
stays in sync.py so every source ends up in the same row shape.
"""
from datetime import date
from pathlib import Path

import client
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
