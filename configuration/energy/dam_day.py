#!/usr/bin/env python3
"""Hourly UA_IPS day-ahead (РДН) prices and our hourly energy for one day -> JSON on stdout.

Usage: dam_day.py YYYY-MM-DD. Run by the command_line sensor
sensor.dam_price_day (packages/dam_price_day.yaml) inside the HA container,
so the DAP dashboard can scroll back through previous days; today and
tomorrow come from the live entsoe sensor instead.
Prices come from the ENTSO-E API with the api_key of the entsoe config entry
and are cached per day in dam_prices_cache.json (a finished day never
changes); for today the prices are skipped (the card uses the live sensor).
Hourly grid export and import (the 5kW's grid port: it is the only
inverter that sells, and the 6kW hangs off its LOAD port) and house
consumption are read from the recorder's long-term statistics (hourly `sum` differences,
the same numbers as recorder.get_statistics "change") straight from the
SQLite DB, read-only, so no API token is needed inside the container.
Output: {"date", "hours": [["HH:00", UAH/kWh], ...], "avg",
"energy": {"HH:00": [export, house, import] kWh}}; a DST day has 23 or 25
hours. Stdlib only.
"""
import json
import sqlite3
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Kyiv")
BASE = Path(__file__).parent
CACHE = BASE / "dam_prices_cache.json"
ENTRIES = BASE.parent / ".storage" / "core.config_entries"
DB = BASE.parent / "home-assistant_v2.db"
AREA = "10Y1001C--000182"  # UA_IPS
EXPORT = "sensor.deye_5kw_total_energy_export"
HOUSE = "sensor.home_load_energy"
IMPORT = "sensor.deye_5kw_total_energy_import"


def entsoe_key() -> str:
    entries = json.loads(ENTRIES.read_text())["data"]["entries"]
    return next(e for e in entries if e["domain"] == "entsoe")["options"]["api_key"]


def fetch(day: date) -> list:
    """[["HH:00", price], ...] in local time; 15-min points are averaged per hour,
    positions missing from an A03 curve repeat the previous price."""
    start = datetime(day.year, day.month, day.day, tzinfo=TZ).astimezone(timezone.utc)
    end = (datetime(day.year, day.month, day.day, tzinfo=TZ) + timedelta(days=1)).astimezone(timezone.utc)
    q = urllib.parse.urlencode({
        "securityToken": entsoe_key(), "documentType": "A44", "in_Domain": AREA, "out_Domain": AREA,
        "periodStart": start.strftime("%Y%m%d%H%M"), "periodEnd": end.strftime("%Y%m%d%H%M")})
    root = ET.fromstring(urllib.request.urlopen("https://web-api.tp.entsoe.eu/api?" + q, timeout=20).read())
    for el in root.iter():
        el.tag = el.tag.split("}", 1)[-1]
    slots: dict = {}
    for period in root.iter("Period"):
        step = {"PT60M": 60, "PT1H": 60, "PT15M": 15}.get(period.findtext("resolution"))
        if not step:
            continue
        p_start = datetime.strptime(period.findtext("timeInterval/start"), "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
        p_end = datetime.strptime(period.findtext("timeInterval/end"), "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
        points = {int(p.findtext("position")): float(p.findtext("price.amount")) for p in period.iter("Point")}
        last = None
        for pos in range(1, int((p_end - p_start).total_seconds()) // 60 // step + 1):
            last = points.get(pos, last)
            t = p_start + timedelta(minutes=step * (pos - 1))
            if last is not None and start <= t < end:
                slots.setdefault(t.replace(minute=0), []).append(last / 1000)
    return [[t.astimezone(TZ).strftime("%H:00"), round(sum(v) / len(v), 2)] for t, v in sorted(slots.items())]


def energy(day: date) -> dict:
    """{"HH:00": [export, house, import]} for the finished hours of the day, kWh."""
    start = datetime(day.year, day.month, day.day, tzinfo=TZ)
    end = start + timedelta(days=1)
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    out: dict = {}
    for n, sid in enumerate((EXPORT, HOUSE, IMPORT)):
        rows = db.execute(
            "SELECT s.start_ts, s.sum FROM statistics s JOIN statistics_meta m ON m.id = s.metadata_id"
            " WHERE m.statistic_id = ? AND s.start_ts >= ? AND s.start_ts < ? ORDER BY s.start_ts",
            (sid, start.timestamp() - 3600, end.timestamp())).fetchall()
        for (_, prev), (ts, cur) in zip(rows, rows[1:]):
            if prev is not None and cur is not None:
                h = datetime.fromtimestamp(ts, TZ).strftime("%H:00")
                out.setdefault(h, [None, None, None])[n] = round(max(cur - prev, 0), 2)
    db.close()
    return out


def main() -> None:
    try:
        day = date.fromisoformat(sys.argv[1])
    except (IndexError, ValueError):
        day = datetime.now(TZ).date() - timedelta(days=1)
    key = day.isoformat()
    today = datetime.now(TZ).date()
    out = {"date": key, "hours": [], "avg": None, "energy": {}}
    try:
        out["energy"] = energy(day)
    except Exception as exc:
        out["error"] = f"stats: {exc}"[:200]
    try:
        cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    except ValueError:
        cache = {}
    hours = cache.get(key)
    if hours is None and day < today:
        try:
            hours = fetch(day)
        except Exception as exc:  # show "no data" instead of making the sensor unavailable
            out["error"] = f"ENTSO-E: {exc}"[:200]
            hours = []
        if len(hours) >= 23:
            cache[key] = hours
            tmp = CACHE.with_suffix(".tmp")
            tmp.write_text(json.dumps(cache, separators=(",", ":")))
            tmp.replace(CACHE)
    if hours:
        out["hours"] = hours
        out["avg"] = round(sum(p for _, p in hours) / len(hours), 2)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
