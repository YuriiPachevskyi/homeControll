"""Extract totals from a KOEC (ТОВ "Київська обласна ЕК", brand ONDO)
electricity bill PDF, as mailed monthly by rahunok@sender.koec.com.ua.

The bill for month M arrives around the 8th-12th of M+1 and names its own
period ("Рахунок за е/е № <account> *\\nсерпень 2026р."). Two layouts exist
(the older one, until ~Aug 2025, also has a tear-off slip repeating the
totals) - the patterns below match the first occurrence, which is the main
bill in both. Amounts use a dot decimal separator.
"""
import re

from parse_receipt import MONTHS, ParseError, extract_text

NUM = r"(-?\d[\d  ]*\.\d{1,2}|-?\d+)"


def _num(s: str) -> float:
    return float(s.replace(" ", "").replace(" ", ""))


def _field(text: str, pattern: str, label: str) -> float:
    m = re.search(pattern, text, re.S)
    if not m:
        raise ParseError(f"{label} not found")
    return _num(m.group(1))


def parse(pdf_bytes: bytes) -> dict:
    text = extract_text(pdf_bytes)
    m = re.search(r"Рахунок за е/е № (\d+)\s*\*?\s*([а-яіїєґ']+) (\d{4})\s*р", text)
    if not m or m.group(2) not in MONTHS:
        raise ParseError("bill number/period not found")
    account_id, month, year = m.group(1), MONTHS[m.group(2)], m.group(3)

    cur = re.search(r"Поточні нарахування.*?ПДВ\s*\n" + NUM + r"\s*\n" + NUM, text, re.S)
    if not cur:
        raise ParseError("current charges not found")
    kwh, accrued = _num(cur.group(1)), _num(cur.group(2))
    balance = _field(text, r"Баланс попереднього періоду, з\s*ПДВ\s*\n" + NUM, "previous balance")
    paid = _field(text, r"Оплата попереднього періоду, з\s*ПДВ\s*\n" + NUM, "previous payment")
    total_due = _field(text, r"СУМА ДО СПЛАТИ, грн з ПДВ\s*\n" + NUM, "amount due")

    # Same row shape as parse_receipt.parse() (Oselya) so sync.py treats every
    # source alike; kwh is extra, informational only.
    return {
        "period": f"{year}-{month:02d}", "account_id": account_id,
        "debt": balance, "avans": 0.0, "paid": paid, "accrued": accrued,
        "recalc": 0.0, "total_due": total_due,
        "secondary_label": None, "secondary_due": 0.0,
        "kwh": kwh,
    }
