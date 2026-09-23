#!/usr/bin/env python3
"""Fixed-rate (manual_fixed_rate) tariffs: rates.yaml is the single source,
edited from the Payments dashboard's "Тарифи" tab via script.oselya_rate_save
-> shell_command.oselya_rate_set, which runs inside the HA container:

    python3 rates.py set "<object label> — <bill label>" <amount> <YYYY-MM>
    python3 rates.py undo

A new amount from month M closes the tariff running at M (valid_to = M-1)
and replaces any that started at M or later; amount 0 just stops the bill
from M. Rows for months already in payments.json are recomputed from the
new tariffs (paid marks are kept), so a past month fixes a wrong amount.
Every `set` first pushes the previous tariffs onto rates_history.json (last
HISTORY_KEEP changes); `undo` pops one and restores it (script.oselya_rate_undo).
The one output line becomes input_text.oselya_rate_status on the dashboard.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

BASE = Path(__file__).parent
RATES = BASE / "rates.yaml"
HISTORY = BASE / "rates_history.json"
HISTORY_KEEP = 20
OBJECTS_YAML = BASE / "objects.yaml"
MONTHS_UA = ["Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень",
             "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень"]
HEADER = """\
# Fixed-rate bill tariffs (objects.yaml bills with source: manual_fixed_rate),
# keyed "<object>.<bill>". Edited from the Payments dashboard ("Тарифи" tab),
# which rewrites this whole file - comments other than this header are lost.
# valid_from/valid_to are "YYYY-MM"; valid_to null = still in force.
"""


def load() -> dict:
    return (yaml.safe_load(RATES.read_text()) or {}) if RATES.exists() else {}


def save(rates: dict) -> None:
    # Written in place (not via a temp file + rename) so the file keeps its
    # owner when the HA container (root) writes it.
    RATES.write_text(HEADER + yaml.safe_dump(rates, allow_unicode=True, sort_keys=True,
                                             default_flow_style=None))


def fixed_bills() -> dict[str, str]:
    """{"<object label> — <bill label>": "<object>.<bill>"} for every fixed-rate bill."""
    objects = yaml.safe_load(OBJECTS_YAML.read_text())["objects"]
    return {f"{o['label']} — {b['label']}": f"{ok}.{bk}"
            for ok, o in objects.items() for bk, b in o["bills"].items()
            if b["source"] == "manual_fixed_rate"}


def month_label(period: str) -> str:
    return f"{MONTHS_UA[int(period[5:]) - 1]} {period[:4]}"


def prev_month(period: str) -> str:
    y, m = int(period[:4]), int(period[5:])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def set_rate(rates: dict, bill_key: str, amount: float, start: str) -> None:
    periods = [p for p in rates.get(bill_key, []) if p["valid_from"] < start]
    for p in periods:
        if p["valid_to"] is None or p["valid_to"] >= start:
            p["valid_to"] = prev_month(start)
    if amount > 0:
        periods.append({"rate": round(amount, 2), "valid_from": start, "valid_to": None})
    rates[bill_key] = periods


def load_history() -> list:
    return json.loads(HISTORY.read_text()) if HISTORY.exists() else []


def save_history(history: list) -> None:
    HISTORY.write_text(json.dumps(history[-HISTORY_KEEP:], ensure_ascii=False, indent=1))


def run_sync() -> str:
    """Recompute rows + to-do items right away; returns a note if it failed.
    PYTHONPATH can't be set in a templated shell_command (no shell), so it's
    passed to the child here."""
    env = {**os.environ, "PYTHONPATH": str(BASE / "vendor")}
    with open(BASE / "sync.log", "a") as log:
        rc = subprocess.run([sys.executable, str(BASE / "sync.py"), "--reconcile-only"],
                            env=env, stdout=log, stderr=log).returncode
    return "" if rc == 0 else " (але перерахунок таблиць не вдався, див. sync.log)"


def undo() -> int:
    history = load_history()
    if not history:
        print("ℹ️ Немає змін для скасування")
        return 0
    last = history.pop()
    save(last["before"])
    save_history(history)
    print(f"↶ Скасовано: {last['change']}{run_sync()}")
    return 0


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "undo":
        return undo()
    if len(sys.argv) != 5 or sys.argv[1] != "set":
        print("usage: rates.py set <bill label> <amount> <YYYY-MM> | rates.py undo")
        return 2
    label, amount_s, start = sys.argv[2].strip(), sys.argv[3].strip(), sys.argv[4].strip()
    bills = fixed_bills()
    if label not in bills:
        print(f"❌ Невідомий платіж: {label}")
        return 1
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", start):
        print(f"❌ «Діє з» має бути у форматі РРРР-ММ, наприклад 2026-10 (зараз: {start or 'порожньо'})")
        return 1
    try:
        amount = float(amount_s.replace(",", "."))
    except ValueError:
        amount = -1
    if amount < 0:
        print(f"❌ Неправильна сума: {amount_s}")
        return 1

    rates = load()
    before = json.loads(json.dumps(rates))
    set_rate(rates, bills[label], amount, start)
    what = f"{amount:.2f} грн" if amount > 0 else "припинено"
    change = f"{label}: {what} з {month_label(start)}"
    if rates == before:
        print(f"ℹ️ Без змін: {change}")
        return 0
    history = load_history()
    history.append({"time": datetime.now().isoformat(timespec="seconds"), "change": change, "before": before})
    save_history(history)
    save(rates)
    print(f"✅ {change}{run_sync()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
