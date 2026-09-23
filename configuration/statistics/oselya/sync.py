#!/usr/bin/env python3
"""Daily job (cron): fetch new bills for every object/bill in objects.yaml,
rebuild payments.json (per-bill detail + per-object aggregate), forward new
Oselya receipts to Telegram, add unpaid amounts to the "Payments" to-do list,
and reconcile items the user has checked off.

Despite the directory name, this orchestrates bills from more than just
Oselya now - objects.yaml's bill.source picks the fetcher (see sources.py):
"oselya" (scraped PDF), "koec_mail" (electricity bill PDF mailed by
KOEC/ONDO, read from Gmail over IMAP), "koec_cabinet" (KOEC/ONDO household
cabinet: bill/charge/payment tables + the latest bill's PDF; paid status
comes from its payment history), "brovk_water" (КП Броваритепловодоенергія
lookup by address + account: 12-month service tables + last month's bill
PDF) or "manual_fixed_rate" (a rate that
applies for a date range, entered by hand, with no ledger - the to-do
checkbox is the only source of "paid" for those).

Key design point (see the plan / memory for the full reasoning): a bill's
secondary invoice (secondary_due/secondary_label - "Інфляційна складова" or
"Пеня") has its OWN "Призначення платежу" and its own bank account - it is
NOT the same payment as the bill's main total_due, even though both are on
one PDF. So every place a human acts on this data (to-do items, Telegram
captions) must show them as two separate amounts, never summed.

1. sources.fetch_oselya_bill() / fetch_koec_mail_bill() /
   fetch_koec_cabinet_bill() / fetch_brovk_water_bill() /
   manual_fixed_rate_rows() - get new rows
2. rebuild_payments() - payments.json "bills" (per object.bill) + "objects"
   (aggregated per object, with a paid/partial/unpaid status per period)
3. every receipt PDF (any PDF_SOURCES bill) not yet in sent.json is sent to Telegram (PDF +
   caption, two amounts if there's a secondary_due); a failed send is
   retried on the next run
4. any bill's *latest* period with an unpaid main and/or secondary amount
   gets its own to-do item(s); items the user has checked off (or deleted)
   are reconciled back into payments.json (bidirectional, never removed -
   see memory: an early version deleted completed items, which made an
   accidental checkmark unrecoverable)
5. Home Assistant is told to re-read sensor.oselya_payments
"""
import json
import os
import subprocess
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

import yaml

import client
import rates
import sources

BASE = Path(__file__).parent
CONFIG = BASE.parent.parent  # .../configuration
PAYMENTS = BASE / "payments.json"
SENT = BASE / "sent.json"
TODO_ADDED = BASE / "todo_added.json"
OBJECTS_YAML = BASE / "objects.yaml"

# Yurii P + Kateryna (added 2026-09-23). A bare "<key>" in sent.json means
# "delivered to everyone", so receipts sent before she was added are not resent.
CHAT_IDS = ["612533502", "481606181"]
TODO_ENTITY = "todo.payments"  # Local To-do list "Payments", added 2026-09-22
# Real external hostname (Nginx Proxy Manager, see memory: fail2ban_nginx_ha_fix) -
# a relative "/api/..." link inside a to-do item's description gets intercepted by
# HA's own frontend router and just bounces to the home page instead of the PDF;
# an absolute https:// URL forces a real browser navigation instead.
HA_BASE_URL = "https://ha.yuriip4.duckdns.org"
PDF_SOURCES = {"oselya", "koec_mail", "koec_cabinet", "brovk_water"}  # bill sources that come with a receipt PDF
COMPLETED_RETENTION_DAYS = 30  # how long a paid item stays visible (checked off) before it's retired

MONTH_UA = ["січень", "лютий", "березень", "квітень", "травень", "червень",
            "липень", "серпень", "вересень", "жовтень", "листопад", "грудень"]
MONTH_SHORT = ["Січ", "Лют", "Бер", "Кві", "Тра", "Чер", "Лип", "Сер", "Вер", "Жов", "Лис", "Гру"]


def load_objects() -> dict:
    return yaml.safe_load(OBJECTS_YAML.read_text())["objects"]


def iter_bills(objects_cfg: dict):
    """Yield (bill_full_key, obj_key, obj_cfg, bill_key, bill_cfg) for every bill."""
    for obj_key, obj_cfg in objects_cfg.items():
        for bill_key, bill_cfg in obj_cfg["bills"].items():
            yield f"{obj_key}.{bill_key}", obj_key, obj_cfg, bill_key, bill_cfg


def receipt_key(bill_full_key: str, period: str) -> str | None:
    """Key of the receipt PDF in sensor.document_links' "oselya" map, if fetched.

    The PDF itself stays in statistics/documents/oselya/ and is served behind
    HA auth by custom_components/documents via a signed, expiring link.
    """
    key = f"{bill_full_key}_{period}"
    return key if (sources.RECEIPTS / f"{key}.pdf").exists() else None


def document_links() -> dict:
    """Current signed receipt links ({key: "/api/documents/...?authSig=..."})."""
    req = urllib.request.Request(
        "http://localhost:8123/api/states/sensor.document_links",
        headers={"Authorization": f"Bearer {get_ha_token()}"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=20))["attributes"].get("oselya", {})
    except Exception as e:
        print(f"reading sensor.document_links failed, to-do links left as-is: {e}")
        return {}


def bot_url() -> str:
    entries = json.loads((CONFIG / ".storage/core.config_entries").read_text())["data"]["entries"]
    token = next(e["data"]["api_key"] for e in entries if e["domain"] == "telegram_bot")
    return f"https://api.telegram.org/bot{token}"


def send_pdf_to(path: Path, caption: str, chat: str) -> bool:
    for cap, mode in ((caption, "Markdown"), (caption.replace("*", ""), None)):
        cmd = ["curl", "-s", "-m", "60", "-F", f"chat_id={chat}", "-F", f"caption={cap}",
               "-F", f"document=@{path}", f"{bot_url()}/sendDocument"]
        if mode:
            cmd[-1:-1] = ["-F", f"parse_mode={mode}"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        try:
            if json.loads(r.stdout).get("ok", False):
                return True
        except json.JSONDecodeError:
            pass
    return False


def deliver(key: str, send_one, sent: set) -> int:
    if key in sent:
        return 0
    failed = 0
    for chat in CHAT_IDS:
        tag = f"{key}@{chat}"
        if tag in sent:
            continue
        if send_one(chat):
            sent.add(tag)
        else:
            failed += 1
    if not failed:
        sent.add(key)
    SENT.write_text(json.dumps(sorted(sent), indent=1))
    return failed


def caption_for(label: str, row: dict) -> str:
    now = datetime.now().strftime("%H:%M")
    y, m = row["period"].split("-")
    title = f"🕐 {now} 🧾 {label} — {MONTH_UA[int(m) - 1]} {y}!!!"
    lines = [title]
    if row["total_due"] > 0:
        lines.append(f"💰 *До сплати: {row['total_due']:.2f} ₴*")
    if row["secondary_due"] > 0:
        lines.append(f"➕ *{row['secondary_label']}: {row['secondary_due']:.2f} ₴* (окремий платіж!)")
    if len(lines) == 1:
        lines.append("*До сплати немає*")
    return "\n".join(lines)


def get_ha_token() -> str:
    """~/.ha_token only exists on the host - this script also runs inside
    the HA container (via shell_command, triggered by the to-do-change
    automation), which only has /config bind-mounted, not the host $HOME.
    A copy lives at CONFIG/.ha_token (gitignored) for that case.
    """
    for candidate in (Path.home() / ".ha_token", CONFIG / ".ha_token"):
        if candidate.exists():
            return candidate.read_text().strip()
    raise FileNotFoundError("no .ha_token found (checked $HOME and CONFIG)")


def refresh_ha_sensor() -> None:
    try:
        token = get_ha_token()
        req = urllib.request.Request(
            "http://localhost:8123/api/services/homeassistant/update_entity",
            data=json.dumps({"entity_id": "sensor.oselya_payments"}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20)
    except Exception as e:
        print(f"HA sensor refresh failed: {e}")


def ha_call(service: str, data: dict, return_response: bool = False):
    token = get_ha_token()
    url = f"http://localhost:8123/api/services/{service.replace('.', '/')}"
    if return_response:
        url += "?return_response"
    req = urllib.request.Request(
        url, data=json.dumps(data).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def fetch_all(objects_cfg: dict) -> None:
    needs_login = any(b["source"] == "oselya" for _, _, _, _, b in iter_bills(objects_cfg))
    oselya_client = None
    if needs_login:
        creds = client.load_config()
        oselya_client = client.OselyaClient(creds["email"], creds["password"])
        oselya_client.login()
    for bill_full_key, _, _, _, bill_cfg in iter_bills(objects_cfg):
        try:
            if bill_cfg["source"] == "oselya":
                sources.fetch_oselya_bill(oselya_client, bill_full_key, bill_cfg)
            elif bill_cfg["source"] == "koec_mail":
                sources.fetch_koec_mail_bill(bill_full_key, bill_cfg)
            elif bill_cfg["source"] == "koec_cabinet":
                sources.fetch_koec_cabinet_bill(bill_full_key, bill_cfg)
            elif bill_cfg["source"] == "brovk_water":
                sources.fetch_brovk_water_bill(bill_full_key, bill_cfg)
        except Exception as e:  # one broken source must not block the others
            print(f"fetch failed for {bill_full_key}: {e}")


def _finish_row(bill_full_key: str, raw: dict, existing: dict) -> dict:
    y, m = raw["period"].split("-")
    row = {
        **raw,
        "label": f"{MONTH_SHORT[int(m) - 1]} {y}",
        "receipt": receipt_key(bill_full_key, raw["period"]) if raw.get("account_id") else None,
        "status": existing.get("status", "paid" if raw["total_due"] <= 0 else "unpaid"),
        "paid_date": existing.get("paid_date"),
        # A source with its own payment history (koec_cabinet) can confirm a
        # payment, but never undo one - a to-do checkmark made before the bank
        # transfer shows up in the cabinet (3-5 days) must stick.
        **({"status": "paid", "paid_date": existing.get("paid_date") or raw.get("source_paid_date")}
           if raw.get("source_paid") else {}),
        "secondary_status": existing.get(
            "secondary_status", "paid" if raw["secondary_due"] <= 0 else "unpaid"),
        "secondary_paid_date": existing.get("secondary_paid_date"),
    }
    return row


def rebuild_payments(objects_cfg: dict) -> dict:
    payments = json.loads(PAYMENTS.read_text()) if PAYMENTS.exists() else {}
    bills, objects_out = payments.get("bills", {}), {}

    for bill_full_key, obj_key, obj_cfg, bill_key, bill_cfg in iter_bills(objects_cfg):
        rows_by_period = {r["period"]: r for r in bills.get(bill_full_key, {}).get("rows", [])}
        existing_periods = set(rows_by_period)
        if bill_cfg["source"] == "oselya":
            raw_rows = sources.parse_oselya_bill_rows(bill_full_key)
        elif bill_cfg["source"] == "koec_mail":
            raw_rows = sources.parse_koec_mail_bill_rows(bill_full_key)
        elif bill_cfg["source"] == "koec_cabinet":
            raw_rows = sources.parse_koec_cabinet_bill_rows(bill_full_key, bill_cfg)
        elif bill_cfg["source"] == "brovk_water":
            raw_rows = sources.parse_brovk_water_bill_rows(bill_full_key, bill_cfg)
        elif bill_cfg["source"] == "manual_fixed_rate":
            raw_rows = sources.manual_fixed_rate_rows(bill_full_key)
            # Months no tariff covers any more (bill stopped/moved) are dropped.
            keep = {r["period"] for r in raw_rows}
            rows_by_period = {p: r for p, r in rows_by_period.items() if p in keep}
        else:
            raise ValueError(f"unknown bill source: {bill_cfg['source']!r}")
        for raw in raw_rows:
            rows_by_period[raw["period"]] = _finish_row(
                bill_full_key, raw, rows_by_period.get(raw["period"], {}))
        bills[bill_full_key] = {
            "object": obj_key,
            "label": f"{obj_cfg['label']} — {bill_cfg['label']}",
            "source": bill_cfg["source"],
            "rows": sorted(rows_by_period.values(), key=lambda r: r["period"]),
        }

    for obj_key, obj_cfg in objects_cfg.items():
        bill_entries = [(bc, bills[f"{obj_key}.{bk}"]) for bk, bc in obj_cfg["bills"].items()]
        periods = sorted({r["period"] for _, b in bill_entries for r in b["rows"]})
        agg_rows = []
        for period in periods:
            rows_here = [r for _, b in bill_entries for r in b["rows"] if r["period"] == period]
            units_total = units_paid = 0
            unpaid_labels = []
            for bc, b in bill_entries:
                r = next((r for r in b["rows"] if r["period"] == period), None)
                if r is None:
                    continue
                if r["total_due"] > 0:
                    units_total += 1
                    if r["status"] == "paid":
                        units_paid += 1
                    else:
                        unpaid_labels.append(bc["label"])
                if r["secondary_due"] > 0:
                    units_total += 1
                    if r["secondary_status"] == "paid":
                        units_paid += 1
                    else:
                        unpaid_labels.append(r["secondary_label"] or bc["label"])
            # Nothing to pay (e.g. prepaid month, total_due 0) counts as paid.
            status = ("paid" if units_paid == units_total else
                      "unpaid" if units_paid == 0 else "partial")
            y, m = period.split("-")
            agg_rows.append({
                "period": period, "label": f"{MONTH_SHORT[int(m) - 1]} {y}",
                "accrued": round(sum(r["accrued"] for r in rows_here), 2),
                "paid": round(sum(r["paid"] for r in rows_here), 2),
                "debt": round(sum(r["debt"] for r in rows_here), 2),
                # A credit (negative total_due, e.g. water overpaid) belongs to
                # that one payee - it can't offset another bill's amount.
                "total_due": round(sum(max(r["total_due"], 0) + r["secondary_due"] for r in rows_here), 2),
                "status": status, "bills_total": units_total, "bills_paid": units_paid,
                "unpaid_labels": unpaid_labels,
            })
        by_year: dict[str, float] = {}
        for r in agg_rows:
            by_year[r["period"][:4]] = by_year.get(r["period"][:4], 0.0) + r["accrued"]
        objects_out[obj_key] = {
            "label": obj_cfg["label"], "rows": agg_rows,
            "year_totals": [{"year": y, "total": round(t, 2)} for y, t in sorted(by_year.items())],
        }

    outstanding = []
    for bill_full_key, obj_key, obj_cfg, bill_key, bill_cfg in iter_bills(objects_cfg):
        rows = bills[bill_full_key]["rows"]
        if not rows:
            continue
        row = rows[-1]  # only the latest period is actually outstanding (debt carries forward)
        for part, amount, purpose, status_field in (
            ("main", row["total_due"], bill_cfg["label"], "status"),
            ("secondary", row["secondary_due"],
             f"{bill_cfg['label']} ({row['secondary_label']})", "secondary_status"),
        ):
            if amount <= 0 or row[status_field] == "paid":
                continue
            outstanding.append({
                "todo_key": f"{bill_full_key}|{row['period']}|{part}",
                "object": obj_cfg["label"], "purpose": purpose,
                "period": row["label"], "amount": round(amount, 2),
                "receipt": row.get("receipt"),
            })

    # For the dashboard's "Тарифи" tab: the tariff table and the bill picker.
    fixed = [(f"{o['label']} — {b['label']}", f"{ok}.{bk}", o, b)
             for ok, o in objects_cfg.items() for bk, b in o["bills"].items()
             if b["source"] == "manual_fixed_rate"]
    tariffs = rates.load()
    rate_rows = [{"object": o["label"], "bill": b["label"], "rate": rp["rate"],
                  "valid_from": rp["valid_from"], "valid_to": rp.get("valid_to")}
                 for _, key, o, b in fixed for rp in sorted(tariffs.get(key, []), key=lambda r: r["valid_from"])]

    payments = {"updated": datetime.now().isoformat(timespec="seconds"),
                "bills": bills, "objects": objects_out, "outstanding": outstanding,
                "rates": rate_rows, "rate_bills": [label for label, _, _, _ in fixed]}
    PAYMENTS.write_text(json.dumps(payments, ensure_ascii=False, indent=1))
    return payments


def notify_new_receipts(objects_cfg: dict, payments: dict, sent: set) -> int:
    failed = 0
    for bill_full_key, _, _, _, bill_cfg in iter_bills(objects_cfg):
        if bill_cfg["source"] not in PDF_SOURCES:
            continue
        bill = payments["bills"][bill_full_key]
        for row in bill["rows"]:
            pdf = sources.RECEIPTS / f"{bill_full_key}_{row['period']}.pdf"
            if not pdf.exists():
                continue
            msg_key = f"receipt:{bill_full_key}:{row['period']}"
            caption = caption_for(bill["label"], row)
            n = deliver(msg_key, lambda chat, p=pdf, c=caption: send_pdf_to(p, c, chat), sent)
            if n:
                failed += n
                print(f"send FAILED for {msg_key} to {n} chat(s), will retry")
            elif msg_key not in sent:
                print(f"sent {msg_key}")
    return failed


def sync_todo(objects_cfg: dict, payments: dict, todo_added: dict) -> None:
    """Add unpaid main/secondary amounts (as separate items!) to the to-do
    list; reconcile items the user has checked off, unchecked, or deleted.
    """
    if not TODO_ENTITY:
        return

    try:
        items = ha_call("todo.get_items", {"entity_id": TODO_ENTITY}, return_response=True)
        current = {it["summary"]: it for it in items["service_response"][TODO_ENTITY]["items"]}
    except Exception as e:
        print(f"todo.get_items failed, skipping reconciliation: {e}")
        current = None

    if current is not None:
        changed = False
        for todo_key, text in list(todo_added.items()):
            item = current.get(text)
            if item is None:
                del todo_added[todo_key]  # user deleted it - stop tracking, leave status as-is
                continue
            bill_full_key, period, part = todo_key.split("|")
            want_paid = item.get("status") == "completed"
            field = "status" if part == "main" else "secondary_status"
            date_field = "paid_date" if part == "main" else "secondary_paid_date"
            for row in payments["bills"][bill_full_key]["rows"]:
                if row["period"] == period and part == "main" and row.get("source_paid") and not want_paid:
                    # Paid according to the source itself: tick the item
                    # instead of reverting the row.
                    try:
                        ha_call("todo.update_item", {"entity_id": TODO_ENTITY, "item": item["uid"],
                                                     "status": "completed"})
                        print(f"completed (paid per source): {todo_key}")
                    except Exception as e:
                        print(f"todo.update_item failed for {todo_key}: {e}")
                    continue
                if row["period"] == period and (row[field] == "paid") != want_paid:
                    row[field] = "paid" if want_paid else "unpaid"
                    row[date_field] = date.today().isoformat() if want_paid else None
                    print(f"{'marked paid' if want_paid else 'reverted to unpaid'}: {todo_key}")
                    changed = True

            # Retire (finally remove) items completed long enough ago that an
            # accidental checkmark would surely have been noticed by now - the
            # payments.json row above already recorded it as paid regardless,
            # this is purely about not letting the to-do list grow forever.
            if item.get("status") == "completed" and item.get("completed"):
                completed_at = datetime.fromisoformat(item["completed"])
                age_days = (datetime.now(completed_at.tzinfo) - completed_at).days
                if age_days >= COMPLETED_RETENTION_DAYS:
                    try:
                        ha_call("todo.remove_item", {"entity_id": TODO_ENTITY, "item": item["uid"]})
                        del todo_added[todo_key]
                        print(f"retired (completed {age_days}d ago): {todo_key}")
                    except Exception as e:
                        print(f"todo.remove_item failed for {todo_key}: {e}")
        if changed:
            # Persist the mutated bill statuses BEFORE recomputing - rebuild_payments()
            # re-reads payments.json from disk, so without this write it would just
            # re-derive the object aggregate from the stale pre-mutation file.
            PAYMENTS.write_text(json.dumps(payments, ensure_ascii=False, indent=1))
            payments = rebuild_payments(objects_cfg)

    # payments["outstanding"] (built by rebuild_payments) is exactly this same
    # "latest period, still owed" set as structured data - reuse it rather than
    # re-deriving the same condition twice.
    # Receipt links are signed and expire (and die on every HA restart), so the
    # description of an item already on the list is refreshed whenever the
    # current link differs. Absolute URL, not a relative "/api/..." one - a
    # relative link inside a to-do item's description gets intercepted by HA's
    # own frontend router and just bounces to the home page instead of the PDF.
    # The description is rendered as markdown, so it holds a short <a> (new tab,
    # like the DAP table's ENERA act links) instead of the bare ~400-char URL.
    links = document_links()

    def link_for(todo_key: str) -> str | None:
        bill_full_key, period, _ = todo_key.split("|")
        path = links.get(f"{bill_full_key}_{period}")
        if not path:
            return None
        return f'<a href="{HA_BASE_URL}{path}" target="_blank" rel="noopener">🧾 Квитанція (PDF)</a>'

    for todo_key, text in todo_added.items():
        item = (current or {}).get(text)
        link = link_for(todo_key)
        if link and item and item.get("description") != link:
            try:
                ha_call("todo.update_item", {"entity_id": TODO_ENTITY, "item": item["uid"], "description": link})
            except Exception as e:
                print(f"todo.update_item failed for {todo_key}: {e}")

    for entry in payments["outstanding"]:
        todo_key = entry["todo_key"]
        text = f"{entry['object']} — {entry['purpose']} — {entry['period']} — {entry['amount']:.2f} грн"
        if todo_key in todo_added:
            # The amount changed (a fixed-rate tariff was edited) - rename the
            # open item so its text keeps matching the table.
            item = (current or {}).get(todo_added[todo_key])
            if item and todo_added[todo_key] != text and item.get("status") != "completed":
                try:
                    ha_call("todo.update_item", {"entity_id": TODO_ENTITY, "item": item["uid"], "rename": text})
                    todo_added[todo_key] = text
                    print(f"renamed to-do: {text}")
                except Exception as e:
                    print(f"todo.update_item (rename) failed for {todo_key}: {e}")
            continue
        link = link_for(todo_key)
        data = {"entity_id": TODO_ENTITY, "item": text}
        if link:
            data["description"] = link
        try:
            ha_call("todo.add_item", data)
            todo_added[todo_key] = text
            print(f"added to-do: {text}")
        except Exception as e:
            print(f"todo.add_item failed for {todo_key}: {e}")

    TODO_ADDED.write_text(json.dumps(todo_added, ensure_ascii=False, indent=1))


def main() -> int:
    objects_cfg = load_objects()
    reconcile_only = "--reconcile-only" in sys.argv
    # Skip fetch_all() (needs ~/.oselya_cabinet - login credentials that only
    # exist on the host, not inside the HA container) when this run was
    # triggered by the to-do-change automation: it only needs to reconcile
    # to-do checkboxes against already-downloaded/parsed data, not fetch
    # anything new. The daily cron run (on the host) always does the full job.
    if not reconcile_only:
        fetch_all(objects_cfg)
    payments = rebuild_payments(objects_cfg)

    sent = set(json.loads(SENT.read_text())) if SENT.exists() else set()
    if "--mark-all-sent" in sys.argv:
        # One-time backfill: don't blast historical receipts to Telegram.
        for bill_full_key, _, _, _, bill_cfg in iter_bills(objects_cfg):
            if bill_cfg["source"] not in PDF_SOURCES:
                continue
            for row in payments["bills"][bill_full_key]["rows"]:
                sent.add(f"receipt:{bill_full_key}:{row['period']}")
        SENT.write_text(json.dumps(sorted(sent), indent=1))
        print(f"marked {len(sent)} receipts as sent")
        refresh_ha_sensor()
        return 0

    failed = 0 if reconcile_only else notify_new_receipts(objects_cfg, payments, sent)

    todo_added = json.loads(TODO_ADDED.read_text()) if TODO_ADDED.exists() else {}
    sync_todo(objects_cfg, payments, todo_added)
    refresh_ha_sensor()

    return 1 if failed else 0


if __name__ == "__main__":
    os.chdir(BASE)
    sys.exit(main())
