#!/usr/bin/env python3
"""Month-by-month energy table for the DAP dashboard -> energy/monthly_energy.json.

Same numbers and the same billing rules as the monthly Telegram report
(automation "Monthly energy summary"): hourly long-term statistics are summed
per local month; a month where more came from the grid than went to it
("deficit") pays for the meter's saldo (import - export) at the day/night
blended tariff, as the ENERA act does (Jan 2026: saldo -292), any other month is
(export - import) x the month's green tariff x 0.77 (tariffs from
statistics/enera/tariffs.json, the latest known one for a month whose act
has not arrived yet).

Runs from cron every few hours; stdlib only. Rows are
display-ready: per month, a "Сума <year>" row after each year and a "Всього"
row when more than one year is covered. The current month is included and
marked partial. Rebuilding from statistics every time is cheap, so nothing
needs to be appended by hand when a month ends.
Each row also treats the station and the house as two separate parties:
"potential" is the station's income at the green tariff (export - import +
house: the export plus the solar the house used); "house_cost" is what the
house pays: its grid import at the night / day tariffs plus its own solar
(house - import) at the green tariff. Battery/inverter losses are charged to
nobody. "green" is the month's green tariff after tax (UAH/kWh).
A deficit month also gets "cost_night" / "cost_day" / "cost_solar", the three
parts of house_cost (23-07 night import / day import / own solar).
Each month row also gets an "act" key ("YYYY-MM") when the matching ENERA act
PDF has been synced (statistics/documents/enera/*-YYMM-*.pdf, see
statistics/enera/sync.py). The dashboard looks the link up by that key in
sensor.document_links (custom_components/documents), which serves the PDF
behind HA auth via a signed, expiring link - never from www/.
"""
import json
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Kyiv")
BASE = Path(__file__).parent
OUT = BASE / "monthly_energy.json"
TARIFFS = BASE.parent / "statistics" / "enera" / "tariffs.json"
ACTS_DIR = BASE.parent / "statistics" / "documents" / "enera"
START = (2025, 9)  # green tariff starts here; nothing was paid for export before
MONEY = ("net", "potential", "house_cost")  # whole hryvnias in the output
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
TOKEN = (Path.home() / ".secrets" / "ha_token").read_text().strip()


def act_key(y: int, mo: int) -> str | None:
    """"YYYY-MM" if the ENERA act for that month has been synced, else None."""
    code = f"{y % 100:02d}{mo:02d}"
    return f"{y}-{mo:02d}" if next(ACTS_DIR.glob(f"*-{code}-*.pdf"), None) else None


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
            g = tariffs.get(f"{y}-{mo:02d}")
            green = g * TAX if g else fallback
            night = a["night_imp"]
            # the station's income at the green tariff: the export plus the solar
            # the house used; battery/inverter losses are charged to nobody
            potential = (exp - imp + house) * green
            if imp > exp:  # deficit month: the meter's saldo is billed at day/night tariffs, export is not paid
                bl = ((imp - night) * DAY_T + night * NIGHT_T) / imp
                net = -(imp - exp) * bl
            else:
                net = (exp - imp) * green
            # the house as a separate customer: grid import at day/night tariffs,
            # its own solar (house - import) at the ENERA green tariff
            c_night, c_day = night * NIGHT_T, (imp - night) * DAY_T
            c_solar = max(house - imp, 0.0) * green
            house_cost = c_night + c_day + c_solar
            split = ({"cost_night": round(c_night), "cost_day": round(c_day), "cost_solar": round(c_solar)}
                     if imp > exp else None)
            boiler = a["boiler"] if a["boiler_rows"] else None
            partial = (y, mo) == (now.year, now.month)
            rows.append({"kind": "month", "label": f"{NAMES[mo - 1]} {y}" + (" ⏳" if partial else ""),
                         "solar": round(solar, 1), "exp": round(exp, 1), "imp": round(imp, 1),
                         "house": round(house, 1), "boiler": None if boiler is None else round(boiler, 1),
                         "net": round(net), "potential": round(potential), "house_cost": round(house_cost),
                         "green": round(green, 4), "act": act_key(y, mo), **(split or {})})
            t = ytot.setdefault(y, {"solar": 0.0, "exp": 0.0, "imp": 0.0, "house": 0.0, "boiler": None, "net": 0.0,
                                    "potential": 0.0, "house_cost": 0.0})
            for k, v in (("solar", solar), ("exp", exp), ("imp", imp), ("house", house), ("net", net),
                         ("potential", potential), ("house_cost", house_cost)):
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
                         **{k: (None if v is None else round(v, 1)) for k, v in ytot[yy].items()},
                         **{k: round(ytot[yy][k]) for k in MONEY}})
    if len(ytot) > 1:
        tot = {k: None for k in ("solar", "exp", "imp", "house", "boiler", *MONEY)}
        for t in ytot.values():
            for k in tot:
                if t[k] is not None:
                    tot[k] = (tot[k] or 0.0) + t[k]
        rows.append({"kind": "total", "label": "Всього",
                     **{k: (None if v is None else round(v, 1)) for k, v in tot.items()},
                     **{k: round(tot[k]) for k in MONEY}})

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
