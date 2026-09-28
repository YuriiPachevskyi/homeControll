"""Client for the КП "Броваритепловодоенергія" consumer lookup
(debt.crewingcrm.com/brovk), used by the "brovk_water" bill source.

No login: an account is opened by address + account number. It's an
ASP.NET WebForms site - the address is a cascade of dropdowns (settlement
-> street -> house), each change being a postback that carries the page's
__VIEWSTATE, then apartment + account number + "Пошук". The server answers
403 to requests without a browser User-Agent.

The account has three services (water/sewage + two monthly subscription
fees), each with its own 12-month table; the printed bill nets all three
into one amount. A bill PDF can only be generated for the last month.

Water meter readings are entered in a separate pop-up form
(WebForms/WebFormVM.aspx?prm=D=<house id>$L=<account>$N=<apartment>$S=VODA)
that opens directly by that URL, without the address cascade - see MeterForm.
"""
import html
import re
from datetime import datetime

import requests

URL = "https://debt.crewingcrm.com/brovk/"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
SERVICES = ("VODA", "VODA_ABPL_PODACHA", "VODA_ABPL_STOKI")
F = "ctl00$MainContent$"


class WaterError(RuntimeError):
    pass


def _num(s: str) -> float:
    return float(re.sub(r"[\s ]", "", s).replace(",", "."))


def _fields(t: str) -> dict:
    return {m.group(1): html.unescape(m.group(2)) for m in
            re.finditer(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', t)}


def _option(t: str, name: str, label: str) -> str:
    m = re.search(r'(?s)<select name="' + re.escape(name) + r'".*?</select>', t)
    if not m:
        raise WaterError(f"no {name} dropdown")
    for value, text in re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)</option>', m.group(0)):
        if html.unescape(text).strip().upper() == label.upper():
            return html.unescape(value)
    raise WaterError(f"{label!r} not in {name.split('$')[-1]}")


class BrovkWater:
    def __init__(self, address: dict, account_id: str):
        """address: {settlement, street, house, apartment} as the site spells them."""
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.account_id = account_id
        t = self.s.get(URL, timeout=60).text
        self.sel = {}
        for field, key in (("DropDownListRAYON", "settlement"), ("DropDownListULITSA", "street"),
                           ("DropDownListDOM", "house")):
            self.sel[F + field] = _option(t, F + field, address[key])
            t = self._post(t, **{"__EVENTTARGET": F + field})
        self.sel[F + "DropDownListKVART"] = _option(t, F + "DropDownListKVART", address["apartment"])
        self.sel[F + "TextBoxLS"] = account_id
        self.page = self._post(t, **{F + "ButtonSearch": "Пошук"})
        if "Розрахунок по місяцях" not in self.page:
            raise WaterError("account not found (address/account number mismatch?)")

    def _post(self, t: str, url: str = URL, **extra) -> str:
        data = {**_fields(t), **self.sel, "__EVENTTARGET": "", "__EVENTARGUMENT": "", **extra}
        r = self.s.post(url, data=data, timeout=60)
        r.raise_for_status()
        return r.text

    def service_table(self, service: str) -> list[dict]:
        """The service's monthly table: {period, start, accrued, recalc, subsidy, paid, end}."""
        t = self.page if service == "VODA" else self._post(
            self.page, **{F + "DropDownListUSL": service, "__EVENTTARGET": F + "DropDownListUSL"})
        t = t[t.find("Розрахунок по місяцях"):]
        out = []
        for row in re.findall(r"(?s)<tr[^>]*>(.*?)</tr>", t):
            c = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", x)).strip() for x in re.findall(r"(?s)<td[^>]*>(.*?)</td>", row)]
            if len(c) >= 7 and re.fullmatch(r"\d\d\.\d{4}", c[0]):
                m, y = c[0].split(".")
                out.append({"period": f"{y}-{m}", **dict(zip(
                    ("start", "accrued", "recalc", "subsidy", "paid", "end"), map(_num, c[1:7])))})
        return out

    def meter_form_url(self) -> str:
        """URL of the account's meter readings form (the button only answers
        with a window.open script)."""
        t = self._post(self.page, **{F + "ButtonVMPOKAZ": "Введення нових показників водомірів"})
        m = re.search(r"window\.open\('([^']+WebFormVM\.aspx[^']+)'", t)
        if not m:
            raise WaterError("meter readings form link not found")
        return html.unescape(m.group(1))

    def last_month_bill_pdf(self, print_name: str) -> bytes:
        """Generate and download last month's bill (the only month the site offers)."""
        t = self._post(self.page, **{F + "DropDownListUSL": "VODA", F + "ButtonPrint": "Друк рахунка"})
        form = re.search(r'<form method="post" action="\./([^"]+)"', t)
        if not form or "TextBoxFIO" not in t:
            raise WaterError("bill print form not found")
        url = URL + "WebForms/" + html.unescape(form.group(1))
        r = self.s.post(url, timeout=60, data={
            **_fields(t), "__EVENTTARGET": "", "__EVENTARGUMENT": "",
            F + "DropDownListDATA": "LASTM", F + "TextBoxFIO": print_name, F + "ButtonPrint": "Друк рахунку"})
        link = re.search(r'id="MainContent_HyperLinkResult"[^>]*href="\.\./([^"]+\.pdf)"', r.text)
        if not link:
            raise WaterError("bill PDF link not found")
        pdf = self.s.get(URL + link.group(1), timeout=60)
        if pdf.headers.get("content-type", "").split(";")[0] != "application/pdf":
            raise WaterError(f"bill download returned {pdf.headers.get('content-type')}")
        return pdf.content


class MeterForm:
    """The meter readings form: one row per meter with the reading on file
    ("Показники у базі даних") and the range the site accepts for a new one
    (its RangeValidator: from on-file - 1 up to on-file + a few hundred m³).
    """

    def __init__(self, url: str):
        self.url = url
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.s.cookies.set("change_lang", "ukr")  # labels come in Russian otherwise
        self._load(self.s.get(url, timeout=60))

    def _load(self, r: requests.Response) -> None:
        r.raise_for_status()
        t = self.page = r.text
        label = lambda name: html.unescape(re.sub(r"<[^>]+>", "", (re.search(
            r'id="MainContent_' + name + r'"[^>]*>(.*?)</span>', t, re.S) or [None, ""])[1])).strip()
        js = lambda n, attr: (re.search(r"RangeValidatorVM" + n + r"\." + attr + r' = "([^"]*)"', t) or [None, None])[1]
        period = re.search(r'id="CalcMonthLabel"[^>]*>([^<]*)', t)
        self.period = html.unescape(period.group(1)).removesuffix(" р.").strip() if period else None
        self.meters = []
        for n in sorted(set(re.findall(r'id="MainContent_TextBoxVM_POSLED_POKAZ_(\d+)"', t)), key=int):
            kind = label(f"LabelVM_GOR_VM_{n}")
            self.meters.append({
                "n": int(n), "name": label(f"LabelVM_NUMBER_{n}"), "model": label(f"LabelVM_N_SCHETCHIKA_{n}"),
                "serial": label(f"LabelVM_SN_SCHET_{n}"), "check_date": label(f"LabelVM_DATA_PROV_SCHET_{n}") or None,
                "kind": "hot" if kind.startswith(("Гар", "Гор")) else "cold" if kind.startswith("Хол") else kind,
                "previous": _num(label(f"LabelVM_PRED_POKAZ_{n}")),
                "min": float(js(n, "minimumvalue")) if js(n, "minimumvalue") else None,
                "max": float(js(n, "maximumvalue")) if js(n, "maximumvalue") else None,
            })
        if not self.meters:
            raise WaterError("no meters in the readings form")

    def submit(self, values: dict[int, float]) -> None:
        """Enter new readings ({meter n: m³}; meters left out keep their
        on-file value), then reload the form from the response."""
        data = {**_fields(self.page), "__EVENTTARGET": "", "__EVENTARGUMENT": "",
                F + "ButtonOk": "Внести показники"}
        for m in self.meters:
            v = values.get(m["n"], m["previous"])
            data[f"{F}TextBoxVM_POSLED_POKAZ_{m['n']}"] = f"{v:.3f}".replace(".", ",")
        action = re.search(r'<form method="post" action="\./([^"]+)"', self.page)
        url = URL + "WebForms/" + html.unescape(action.group(1)) if action else self.url
        self.response = self.s.post(url, data=data, timeout=60)
        self._load(self.s.get(self.url, timeout=60))


def parse_bill(pdf_bytes: bytes) -> dict:
    """Period, account and totals from a bill PDF."""
    from parse_receipt import MONTHS, ParseError, extract_text
    text = extract_text(pdf_bytes)
    period = re.search(r"Рахунок\s+за\s+([А-ЯІЇЄҐ']+)\s+(\d{4})", text)
    account = re.search(r"Особовий\s+рахунок\s+№\s*(\d+)", text)
    due = re.search(r"ДО СПЛАТИ,\s*грн\.\s*(-?[\d\s]+[.,]\d+)", text)
    accrued = re.search(r"НАРАХОВАНО\s+(-?[\d\s]+[.,]\d+)", text)
    if not (period and account and due and period.group(1).lower() in MONTHS):
        raise ParseError("water bill: period/account/amount not found")
    return {"period": f"{period.group(2)}-{MONTHS[period.group(1).lower()]:02d}",
            "account_id": account.group(1), "total_due": _num(due.group(1)),
            "accrued": _num(accrued.group(1)) if accrued else None,
            "generated": datetime.now().isoformat(timespec="seconds")}
