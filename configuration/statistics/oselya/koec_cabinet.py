"""Client for the KOEC/ONDO household cabinet (ok.koec.com.ua), used for
bills that don't arrive by mail (source "koec_cabinet" in objects.yaml).

It's a Rails site: login is a plain form with an authenticity_token, and
after login the cabinet must "connect" to the supplier's server (the page
auto-clicks a data-remote link) before any data pages work. The per-year
tables (bills, charges, payments) are loaded the same way - an XHR GET that
answers with jQuery code carrying the table HTML - so every data request
here sends the XHR headers and un-escapes that JS string.

Only the latest bill is available as a PDF (/home/bill.pdf); older months
exist only as table rows.
"""
import json
import re
from datetime import date, datetime
from pathlib import Path

import requests

BASE = "https://ok.koec.com.ua"


class CabinetError(RuntimeError):
    pass


def _num(s: str) -> float:
    return float(re.sub(r"[\s  ]", "", s).replace(",", "."))


def _js_html(js: str) -> str:
    return js.replace("\\n", "\n").replace('\\"', '"').replace("\\/", "/").replace("\\'", "'")


def _rows(html: str) -> list[str]:
    return re.findall(r"(?s)<tr[^>]*>(.*?)</tr>", html)


def _tds(row: str) -> list[str]:
    cells = re.findall(r"(?s)<td[^>]*>(.*?)</td>", row)
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in cells]


class KoecCabinet:
    def __init__(self, creds_file: str):
        creds = json.loads(Path(creds_file).expanduser().read_text())
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "Mozilla/5.0"
        self._login(creds["email"], creds["password"])

    def _login(self, email: str, password: str) -> None:
        page = self.s.get(BASE + "/home/login", timeout=60).text
        token = re.search(r'name="authenticity_token" value="([^"]+)"', page).group(1)
        r = self.s.post(BASE + "/home/login", timeout=60, data={
            "utf8": "✓", "authenticity_token": token,
            "username": email, "password": password, "commit": "Увійти"})
        if "/home/login" in r.url:
            raise CabinetError("login failed (wrong credentials?)")
        link = re.search(r'class="auto_click" data-remote="true" href="([^"]+)"', r.text)
        self.csrf = re.search(r'name="csrf-token" content="([^"]+)"', r.text).group(1)
        if link:  # connect to the supplier's server, as the page's JS would
            js = self._xhr(link.group(1))
            if "Успішно підключено" not in js:
                raise CabinetError("could not connect to the supplier's server (maintenance?)")

    def _xhr(self, path: str, params: dict | None = None) -> str:
        r = self.s.get(BASE + path, params=params, timeout=90, headers={
            "X-Requested-With": "XMLHttpRequest", "X-CSRF-Token": self.csrf,
            "Accept": "text/javascript, application/javascript, */*; q=0.01"})
        r.raise_for_status()
        return _js_html(r.text)

    def bills(self, year: int) -> list[dict]:
        """Bills issued in `year`: {date, amount, number, due}."""
        out = []
        for row in _rows(self._xhr("/home/bills", {"f[year]": str(year)})):
            c = _tds(row)
            if len(c) >= 5 and re.fullmatch(r"\d+\.", c[0]) and re.fullmatch(r"\d\d\.\d\d\.\d{4}", c[1]):
                out.append({"date": datetime.strptime(c[1], "%d.%m.%Y").date().isoformat(),
                            "amount": _num(c[2]), "number": c[3],
                            "due": datetime.strptime(c[4], "%d.%m.%Y").date().isoformat()})
        return out

    def fees(self, year: int) -> dict[str, dict]:
        """Charges per period of `year`: {"YYYY-MM": {kwh, accrued}}."""
        html = self._xhr("/home/fees", {"f[year]": str(year)})
        out = {}
        for m in re.finditer(r'(?s)<tr[^>]*id="fee-(\d{4}-\d\d)"[^>]*>(.*?)</tr>', html):
            c = _tds(m.group(2))
            out[m.group(1)] = {"kwh": _num(c[1]), "accrued": _num(c[3])}
        return out

    def payments(self, year: int) -> list[dict]:
        """Payments made in `year`: {date, amount}."""
        out = []
        for row in _rows(self._xhr("/home/payments", {"f[year]": str(year)})):
            c = _tds(row)
            if len(c) >= 4 and re.fullmatch(r"\d+\.", c[0]) and re.fullmatch(r"\d\d\.\d\d\.\d{4}", c[1]):
                out.append({"date": datetime.strptime(c[1], "%d.%m.%Y").date().isoformat(),
                            "amount": _num(c[3])})
        return out

    def current_bill_pdf(self) -> bytes:
        r = self.s.get(BASE + "/home/bill.pdf", timeout=90)
        if r.headers.get("content-type", "").split(";")[0] != "application/pdf":
            raise CabinetError(f"/home/bill.pdf returned {r.headers.get('content-type')}")
        return r.content

    def snapshot(self, from_year: int) -> dict:
        """Everything needed to build rows, for every year from from_year on."""
        years = range(from_year, date.today().year + 1)
        fees = {}
        for y in years:
            fees.update(self.fees(y))
        return {
            "fetched": datetime.now().isoformat(timespec="seconds"),
            "bills": sorted((b for y in years for b in self.bills(y)), key=lambda b: b["date"]),
            "fees": fees,
            "payments": sorted((p for y in years for p in self.payments(y)), key=lambda p: p["date"]),
        }
