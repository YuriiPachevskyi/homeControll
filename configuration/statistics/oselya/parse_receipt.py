"""Extract totals from an oselya.com.ua receipt PDF.

Each receipt bundles a main invoice (utility management fee / concierge fee)
plus one small secondary invoice (late-payment interest, or a penalty -
"ПЕНІ") with a different title depending on the account. Both have the same
summary-box shape: ALL-CAPS labels БОРГ / АВАНС / ОПЛАЧЕНО / НАРАХОВАНО /
ПЕРЕРАХУНОК / РАЗОМ до сплати, each immediately followed by its amount when
one applies (blank when it doesn't - e.g. АВАНС is usually absent). The
all-caps spelling is what distinguishes these summary figures from the
look-alike table column headers ("Борг на ...", "Нараховано разом, грн")
which use title case and must NOT be matched.

Only totals are parsed here (no per-service line items), by design.
"""
import re

from pypdf import PdfReader

MONTHS = {
    "січень": 1, "лютий": 2, "березень": 3, "квітень": 4, "травень": 5,
    "червень": 6, "липень": 7, "серпень": 8, "вересень": 9, "жовтень": 10,
    "листопад": 11, "грудень": 12,
}

NUM = r"([\d  ]+,\d{1,2})"


class ParseError(RuntimeError):
    pass


def _num(s: str | None) -> float:
    if not s:
        return 0.0
    return float(s.replace(" ", "").replace(" ", "").replace(",", "."))


def _field(text: str, label: str) -> float:
    m = re.search(re.escape(label) + r"[ \t ]+" + NUM, text)
    return _num(m.group(1)) if m else 0.0


def extract_text(pdf_bytes: bytes) -> str:
    import io
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(p.extract_text() for p in reader.pages)


def parse(pdf_bytes: bytes) -> dict:
    text = extract_text(pdf_bytes)

    m = re.search(r"За\s+(\S+)\s+(\d{4})\s+р\.", text)
    if not m:
        raise ParseError("period ('За <Місяць> <Рік> р.') not found")
    month_name, year = m.group(1).lower(), int(m.group(2))
    if month_name not in MONTHS:
        raise ParseError(f"unrecognised month name: {month_name!r}")
    period = f"{year}-{MONTHS[month_name]:02d}"

    m = re.search(r"Особовий рахунок:\s*(\S+)", text)
    if not m:
        raise ParseError("'Особовий рахунок' not found")
    account_id = m.group(1)

    # Split into the main invoice and the secondary one (whichever title it has).
    m = re.search(r"РАХУНОК НА СПЛАТУ (ЗА ІНФЛЯЦІЙНО-КОМПЕНСАЦІЙНІ ВИТРАТИ|ПЕНІ)", text)
    if m:
        main_text, secondary_text = text[:m.start()], text[m.start():]
        secondary_label = "Інфляція" if "ІНФЛЯЦІЙНО" in m.group(1) else "Пеня"
    else:
        main_text, secondary_text = text, ""
        secondary_label = None

    m = re.search(r"БОРГ на\s+[\d.]+[ \t ]+" + NUM, main_text)
    debt = _num(m.group(1)) if m else 0.0

    row = {
        "period": period,
        "account_id": account_id,
        "debt": debt,
        "avans": _field(main_text, "АВАНС"),
        "paid": _field(main_text, "ОПЛАЧЕНО"),
        "accrued": _field(main_text, "НАРАХОВАНО"),
        "recalc": _field(main_text, "ПЕРЕРАХУНОК"),
        "total_due": _field(main_text, "РАЗОМ до сплати"),
        "secondary_label": secondary_label,
        "secondary_due": _field(secondary_text, "РАЗОМ до сплати") if secondary_text else 0.0,
    }
    return row
