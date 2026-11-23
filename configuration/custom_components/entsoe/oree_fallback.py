"""Local patch: OREE (Ukrainian market operator) fallback for UA_IPS day-ahead prices.

ENTSO-E sometimes has no UA_IPS prices for whole days ("No matching data found"),
while oree.com.ua publishes them (same numbers, UAH/MWh, IPS zone = DAM/2).
fill_missing() adds the hours ENTSO-E did not return; existing ENTSO-E values win.
Note: a HACS update of this integration removes this file and the hook in api_client.py.
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiohttp

_LOGGER = logging.getLogger(__name__)
TZ = ZoneInfo("Europe/Kyiv")
URL = "https://www.oree.com.ua/index.php/PXS/get_pxs_hdata/{d:%d.%m.%Y}/DAM/2"
MIN_HOURS = 20  # same threshold as the coordinator uses for "day is complete"


def parse(text: str) -> list[float]:
    """Hourly prices (UAH/MWh) in hour order from the OREE JSON/HTML answer; [] if not published."""
    body = json.loads(text).get("html", "")
    prices = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        # columns: hidden index, hour (1..24), price, volumes...
        if len(cells) >= 3 and cells[1].isdigit():
            prices.append(float(cells[2].replace(" ", "").replace(",", ".")))
    return prices


def hour_slots(day: date, count: int) -> list[datetime]:
    """Start of each delivery hour of a local day in UTC (23/25 on DST days)."""
    midnight = datetime(day.year, day.month, day.day, tzinfo=TZ).astimezone(timezone.utc)
    return [midnight + timedelta(hours=i) for i in range(count)]


async def fetch_day(session: aiohttp.ClientSession, day: date) -> dict:
    async with session.get(URL.format(d=day), headers={"User-Agent": "Mozilla/5.0"}) as resp:
        resp.raise_for_status()
        prices = parse(await resp.text())
    return {t.astimezone(): p for t, p in zip(hour_slots(day, len(prices)), prices)}


async def fill_missing(series: dict, start: datetime, end: datetime, interval_minutes: int = 60) -> dict:
    """Return series with the missing local days in [start, end) filled from OREE."""
    days, d = [], start.astimezone(TZ).date()
    last = (end - timedelta(seconds=1)).astimezone(TZ).date()
    while d <= last:
        have = sum(1 for t in series if t.astimezone(TZ).date() == d)
        if have < MIN_HOURS * 60 // interval_minutes:
            days.append(d)
        d += timedelta(days=1)
    if not days:
        return series
    out = dict(series)
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            for day in days:
                try:
                    hourly = await fetch_day(session, day)
                except Exception as exc:  # OREE down or format changed: keep what ENTSO-E gave
                    _LOGGER.warning("OREE fallback for %s failed: %s", day, exc)
                    continue
                added = 0
                for t, price in hourly.items():
                    for k in range(60 // interval_minutes):
                        slot = t + timedelta(minutes=k * interval_minutes)
                        if slot not in out:
                            out[slot] = price
                            added += 1
                if added:
                    _LOGGER.warning("ENTSO-E had no UA prices for %s, took %d slots from OREE", day, added)
    except Exception as exc:
        _LOGGER.warning("OREE fallback failed: %s", exc)
    return dict(sorted(out.items()))
