#!/usr/bin/env python3
"""Month-by-month energy table for the DAP dashboard -> energy/monthly_energy.json.

Same numbers and the same billing rules as the monthly Telegram report
(automation "Monthly energy summary"): hourly long-term statistics are summed
per local month; a month where the house used more than the solar produced
("deficit") is billed at the day/night blended tariff, any other month is
(export - import) x the month's green tariff x 0.77 (tariffs from
statistics/enera/tariffs.json, the latest known one for a month whose act
has not arrived yet).

Runs from cron every few hours; stdlib only. Rows are
display-ready: per month, a "Сума <year>" row after each year and a "Всього"
row when more than one year is covered. The current month is included and
marked partial. Rebuilding from statistics every time is cheap, so nothing
needs to be appended by hand when a month ends.
Each month row also gets an "act" URL when the matching ENERA act PDF has been
synced (statistics/enera/acts/*-YYMM-*.pdf, see statistics/enera/sync.py):
the file is copied as www/enera_acts/YYYY-MM.pdf (HA's /local/ static server
doesn't follow symlinks, and the dashboard table links to it so tapping a
month downloads the act) - the dashboard reads the url via r.act.
"""
import json
import shutil
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Kyiv")
BASE = Path(__file__).parent
OUT = BASE / "monthly_energy.json"
TARIFFS = BASE.parent / "statistics" / "enera" / "tariffs.json"
ACTS_DIR = BASE.parent / "statistics" / "enera" / "acts"
WWW_ACTS_DIR = BASE.parent / "www" / "enera_acts"
START = (2025, 9)  # green tariff starts here; nothing was paid for export before
DAY_T, NIGHT_T, NIGHT_FROM, NIGHT_TO, TAX, FALLBACK = 4.32, 2.16, 23, 7, 0.77, 5.2353
NAMES = ["Січ", "Лют", "Бер", "Кві", "Тра", "Чер", "Лип", "Сер", "Вер", "Жов", "Лис", "Гру"]
IDS = {
    "pv5": "sensor.deye_5kw_total_production",
    "pv6": "sensor.deye_6kw_total_production",
    "exp": "sensor.deye_5kw_total_energy_export",
    "imp": "sensor.deye_5kw_total_energy_import",
    "house": "sensor.home_load_energy",
    "boiler": "sensor.boiler_ten_energy_total",
}
TOKEN = (Path.home() / ".ha_token").read_text().strip()


def act_url(y: int, mo: int) -> str | None:
    """Copy the matching ENERA act PDF into www/ and return its /local/ URL, if synced."""
    code = f"{y % 100:02d}{mo:02d}"
    match = next(ACTS_DIR.glob(f"*-{code}-*.pdf"), None)
    if not match:
        return None
    WWW_ACTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = WWW_ACTS_DIR / f"{y}-{mo:02d}.pdf"
    if not dest.exists() or dest.stat().st_size != match.stat().st_size:
        shutil.copy2(match, dest)
    return f"/local/enera_acts/{y}-{mo:02d}.pdf"


def api(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        "http://localhost:8123/api/" + path, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=120))


def main() -> None:
    now = datetime.now(TZ)
    start = datetime(*START, 1, tzinfo=TZ)
    end = now.replace(minute=0, second=0, microsecond=0)
    resp = api("services/recorder/get_statistics?return_response", {
        "start_time": start.isoformat(), "end_time": end.isoformat(),
        "period": "hour", "types": ["change"], "statistic_ids": list(IDS.values())})
    stats = resp["service_response"]["statistics"]

    agg: dict = {}
    for key, sid in IDS.items():
        for r in stats.get(sid, []):
            t = datetime.fromisoformat(r["start"]).astimezone(TZ)
            m = agg.setdefault((t.year, t.month), {k: 0.0 for k in IDS} | {"night_imp": 0.0, "boiler_rows": 0})
            v = r["change"] or 0
            m[key] += v
            if key == "imp" and (t.hour >= NIGHT_FROM or t.hour < NIGHT_TO):
                m["night_imp"] += v
            if key == "boiler":
                m["boiler_rows"] += 1

    tariffs = {k: r["green_tariff"] for k, r in json.loads(TARIFFS.read_text()).items() if r.get("green_tariff")}
    latest = tariffs[max(tariffs)] if tariffs else None
    fallback = latest * TAX if latest else FALLBACK

    rows, ytot = [], {}
    y, mo = START
    while (y, mo) <= (now.year, now.month):
        a = agg.get((y, mo))
        if a:
            solar = a["pv5"] + a["pv6"]
            exp, imp, house = a["exp"], a["imp"], a["house"]
            if house > solar:  # deficit month: generation offsets consumption, export is not paid
                bl = ((imp - a["night_imp"]) * DAY_T + a["night_imp"] * NIGHT_T) / imp if imp > 0 else DAY_T
                net = -(house - solar) * bl
            else:
                g = tariffs.get(f"{y}-{mo:02d}")
                net = (exp - imp) * (g * TAX if g else fallback)
            boiler = a["boiler"] if a["boiler_rows"] else None
            partial = (y, mo) == (now.year, now.month)
            rows.append({"kind": "month", "label": f"{NAMES[mo - 1]} {y}" + (" ⏳" if partial else ""),
                         "solar": round(solar, 1), "exp": round(exp, 1), "imp": round(imp, 1),
                         "house": round(house, 1), "boiler": None if boiler is None else round(boiler, 1),
                         "net": round(net), "act": act_url(y, mo)})
            t = ytot.setdefault(y, {"solar": 0.0, "exp": 0.0, "imp": 0.0, "house": 0.0, "boiler": None, "net": 0.0})
            for k, v in (("solar", solar), ("exp", exp), ("imp", imp), ("house", house), ("net", net)):
                t[k] += v
            if boiler is not None:
                t["boiler"] = (t["boiler"] or 0.0) + boiler
        mo += 1
        if mo > 12:
            y, mo = y + 1, 1
        # close a year's block right after its last month (Dec) or at the end of the data
        if (mo == 1 or (y, mo) > (now.year, now.month)) and (y - (1 if mo == 1 else 0)) in ytot:
            yy = y - 1 if mo == 1 else y
            rows.append({"kind": "sum", "label": f"Сума {yy}",
                         **{k: (None if v is None else round(v, 1)) for k, v in ytot[yy].items() if k != "net"},
                         "net": round(ytot[yy]["net"])})
    if len(ytot) > 1:
        tot = {k: None for k in ("solar", "exp", "imp", "house", "boiler", "net")}
        for t in ytot.values():
            for k in tot:
                if t[k] is not None:
                    tot[k] = (tot[k] or 0.0) + t[k]
        rows.append({"kind": "total", "label": "Всього",
                     **{k: (None if v is None else round(v, 1)) for k, v in tot.items() if k != "net"},
                     "net": round(tot["net"])})

    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps({"updated": now.isoformat(timespec="minutes"), "rows": rows}, ensure_ascii=False, indent=1))
    tmp.replace(OUT)
    try:  # tell HA to re-read the file now instead of on its own hourly poll
        api("services/homeassistant/update_entity", {"entity_id": "sensor.monthly_energy_table"})
    except Exception:
        pass
    for r in rows:
        print(f"{r['label']:<13}{r['solar']:>8}{r['exp']:>8}{r['imp']:>7}{r['house']:>8}"
              f"{'' if r['boiler'] is None else r['boiler']:>7}{r['net']:>+8}")


if __name__ == "__main__":
    main()
