#!/usr/bin/env python3
"""Parse ENERA settlement acts (statistics/documents/enera/*.pdf) into enera/tariffs.json.

tariffs.json is keyed by the billing month ("YYYY-MM") and holds only numbers
(no names, EIC codes or contract numbers), so it is safe to keep in git:
  green_tariff  UAH/kWh excl. VAT for the month (the value Home Assistant uses)
  green_kwh     volume paid at the green tariff
  avg_kwh/avg_tariff  remainder paid at the "average market" tariff
  generation / consumption / saldo  meter report, kWh
  gross         total before tax, UAH
  payout        amount actually paid out (after PDFO 18% + military levy 5%)
Every value is cross-checked (volume x tariff vs cost, gross - taxes vs payout);
a mismatch is reported and the month is skipped rather than stored wrong.
"""
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader

BASE = Path(__file__).parent
ACTS_DIR = BASE.parent / "documents" / "enera"
OUT = BASE / "tariffs.json"


def num(s: str) -> float:
    return float(s.replace(",", "."))


def parse(path: Path) -> dict:
    text = "\n".join(p.extract_text() for p in PdfReader(path).pages)
    flat = re.sub(r"\s+", " ", text)

    period = re.search(
        r"01\.(\d{2})\.(\d{4}) р\. по \d{2}\.\d{2}\.\d{4}", flat
    )
    if not period:
        raise ValueError("billing period not found")
    month = f"{period.group(2)}-{period.group(1)}"

    meter = re.search(
        r"1 2 3 4 5 \S+ кВт\*год (-?[\d.]+) (-?[\d.]+) (-?[\d.]+)", flat
    )
    if not meter:
        raise ValueError("meter report not found")
    rec = {
        "generation": num(meter.group(1)),
        "consumption": num(meter.group(2)),
        "saldo": num(meter.group(3)),
    }

    green = re.search(
        r"по Зеленому тарифу\) ([\d.]+) ([\d.]+) - ([\d.]+)", flat
    )
    if not green:
        # Deficit month (consumption > generation): the act has the meter
        # report only, nothing is bought, so there is no tariff to record.
        if rec["saldo"] >= 0:
            raise ValueError("no purchase table but saldo is not negative")
        return month, {**rec, "green_tariff": None, "payout": 0.0}

    # The average-tariff row is just "-" when everything was sold at green.
    avg = re.search(r"по середньому тарифу\) ([\d.]+) - ([\d.]+) ([\d.]+)", flat)
    total = re.search(r"Всього ([\d.]+) X X ([\d.]+)", flat)
    payout = re.search(r"Сума до сплати \(прописом\) ([\d.]+) грн", flat)
    if not (total and payout):
        raise ValueError("unrecognised act layout")

    rec.update(
        {
            "green_tariff": num(green.group(2)),
            "green_kwh": num(green.group(1)),
            "green_cost": num(green.group(3)),
            "avg_kwh": num(avg.group(1)) if avg else 0.0,
            "avg_tariff": num(avg.group(2)) if avg else None,
            "avg_cost": num(avg.group(3)) if avg else 0.0,
            "gross": num(total.group(2)),
            "payout": num(payout.group(1)),
        }
    )

    # Cross-checks
    problems = []
    if abs(rec["green_kwh"] * rec["green_tariff"] - rec["green_cost"]) > 0.02:
        problems.append("green volume x tariff != cost")
    if abs(rec["green_cost"] + rec["avg_cost"] - rec["gross"]) > 0.02:
        problems.append("green + average cost != total")
    if abs(rec["gross"] * 0.77 - rec["payout"]) > 0.05:
        problems.append("payout is not 77% of gross")
    if abs(rec["generation"] - rec["consumption"] - rec["saldo"]) > 0.01:
        problems.append("generation - consumption != saldo")
    if problems:
        raise ValueError("; ".join(problems))
    return month, rec


def main() -> int:
    result = {}
    failed = 0
    for pdf in sorted(ACTS_DIR.glob("*.pdf")):
        try:
            month, rec = parse(pdf)
        except Exception as e:  # keep going, report each bad file
            print(f"FAIL {pdf.name}: {e}")
            failed += 1
            continue
        result[month] = rec
        print(f"{month}  green {rec['green_tariff']}  saldo {rec['saldo']}  payout {rec['payout']}")
    OUT.write_text(
        json.dumps(dict(sorted(result.items())), indent=2, ensure_ascii=False) + "\n"
    )
    print(f"{len(result)} months written to {OUT.name}, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
