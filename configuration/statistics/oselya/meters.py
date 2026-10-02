#!/usr/bin/env python3
"""Meter readings, entered on the suppliers' sites from the Payments
dashboard's "Лічильники" tab. A *point* is a bill whose source has a
readings form (POINT_SOURCES): "<object>.<bill>", e.g. apartment_177.water.

    meters.py load <point>
    meters.py submit <point> <value 1> [<value 2> ...]   (one per meter, in order)

Runs on the host (the sites need logins/addresses from ~/.secrets): the HA
container calls it over ssh (shell_command.oselya_meter_load/_submit).
`load` reads the readings on file into meters.json (sensor.oselya_meters);
`submit` checks the new ones, sends them and records the submission in
meter_readings.json. The one output line becomes
input_text.oselya_meter_status on the dashboard.

What "done" means differs per site:
  brovk_water   - the site only *accepts* readings ("будуть оброблені
                  протягом робочого дня"); an operator moves them into
                  "Показники у базі даних" later. The submission is `accepted`
                  at once and `applied` when a later load (or the host's daily
                  sync, via refresh_bill) finds them on file.
  koec_cabinet  - passed straight on to the distribution operator; the page
                  then shows them as the latest readings, so a successful
                  submission is `applied` right away.
"""
import json
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

import brovk_water
import koec_cabinet

BASE = Path(__file__).parent
OBJECTS_YAML = BASE / "objects.yaml"
CACHE_DIR = BASE.parent / "documents" / "oselya"
STATE = BASE / "meters.json"
HISTORY = BASE / "meter_readings.json"
RESPONSE = BASE / "meter_submit_response.html"  # last unconfirmed answer, for debugging
POINT_SOURCES = ("brovk_water", "koec_cabinet")
# brovk_water's alert after a successful submission.
WATER_ACCEPTED = "будуть оброблені протягом робочого дня"
WATER_KINDS = {"cold": "Холодна вода", "hot": "Гаряча вода"}


class MeterError(Exception):
    pass


def points() -> dict[str, dict]:
    """{"<object>.<bill>": {label, source, cfg}} for every bill with meters."""
    objects = yaml.safe_load(OBJECTS_YAML.read_text())["objects"]
    return {f"{ok}.{bk}": {"label": f"{o['label']} — {b['label']}", "source": b["source"], "cfg": b}
            for ok, o in objects.items() for bk, b in o["bills"].items() if b["source"] in POINT_SOURCES}


def fmt(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".")


def history() -> list:
    return json.loads(HISTORY.read_text()) if HISTORY.exists() else []


def save_history(hist: list) -> None:
    HISTORY.write_text(json.dumps(hist, ensure_ascii=False, indent=1))


# ---- per-site readers: (point, bill cfg) -> (info, meters, handle) ----------
# meters: [{n, name, detail, previous, previous_date, min, max, unit, precision}]

def read_water(point: str, cfg: dict):
    # The form opens by URL alone; the host sync caches it (see
    # sources.fetch_brovk_water_bill) so no address cascade is needed here.
    cache = CACHE_DIR / f"{point}.cabinet.json"
    url = json.loads(cache.read_text()).get("meter_form") if cache.exists() else None
    if not url:
        raise MeterError("немає посилання на форму - його збереже нічна синхронізація")
    form = brovk_water.MeterForm(url)
    meters = [{
        "n": m["n"], "name": WATER_KINDS.get(m["kind"], m["name"]),
        "detail": f"{m['model']} №{m['serial']}" + (f", повірка {m['check_date']}" if m["check_date"] else ""),
        "previous": m["previous"], "previous_date": None, "min": m["min"], "max": m["max"],
        "unit": "м³", "precision": 3,
    } for m in form.meters]
    return f"розрахунковий період: {form.period}", meters, form


def read_koec(point: str, cfg: dict):
    cab = koec_cabinet.KoecCabinet(cfg["credentials"])
    form = cab.readings_form()
    if form["closed"]:
        return read_koec_closed(point, form) + ((cab, form),)
    prev_date = datetime.fromisoformat(form["date"]).strftime("%d.%m.%Y") if form["date"] else None
    meters = [{
        "n": z["n"], "name": z["name"].capitalize(),
        "detail": f"на 1-ше число: {fmt(z['month_start'])}" if z["month_start"] is not None else "",
        "previous": z["previous"], "previous_date": prev_date,
        # "Перекрут" (lower than on file) is allowed by the site, but here it
        # is almost certainly a typo - such a reading goes in on the site itself.
        "min": z["previous"], "max": None, "unit": "кВт·год", "precision": form["precision"],
    } for z in form["zones"]]
    return f"останні показники від {prev_date}", meters, (cab, form)


def read_koec_closed(point: str, form: dict):
    """This month's readings are already in: the site shows only the first
    zone's value, so the zones come from our own submission of that day (if
    it was ours). Nothing can be submitted until the next month."""
    day = datetime.fromisoformat(form["date"]).strftime("%d.%m.%Y")
    ours = [h for h in history() if h["point"] == point and h["time"][:10] == form["date"]
            and abs(h["meters"][0]["sent"] - form["value"]) < 0.5]
    if not ours:
        raise MeterError(f"цього місяця показники вже внесено ({fmt(form['value'])} кВт·год на {day}) "
                         "не звідси; нові - з 1-го числа наступного місяця")
    meters = [{
        "n": m["n"], "name": m["name"], "detail": "", "previous": m["sent"], "previous_date": day,
        "min": m["sent"], "max": None, "unit": m["unit"], "precision": 0,
    } for m in ours[-1]["meters"]]
    return (f"показники за цей місяць уже внесено {day} - нові сайт прийме з 1-го числа "
            "наступного місяця (виправити - на сайті ДТЕК)", meters)


READERS = {"brovk_water": read_water, "koec_cabinet": read_koec}


# ---- state ------------------------------------------------------------------

def refresh_pending(point: str, meters: list) -> None:
    """Mark accepted submissions whose readings are now on file as applied."""
    on_file = {m["n"]: m["previous"] for m in meters}
    hist, changed = history(), False
    for h in hist:
        if h["point"] == point and h.get("accepted") and not h.get("applied") and all(
                abs(on_file.get(m["n"], -1) - m["sent"]) < 0.0005 for m in h["meters"]):
            h["applied"] = datetime.now().isoformat(timespec="seconds")
            changed = True
    if changed:
        save_history(hist)


# ---- "more than usual" warning (dashboard only, never blocks a submission) ---

WATER_MONTHLY_FALLBACK = 10.0  # m³ per meter, until there are 2+ submissions


def months_since(day: date | None) -> int:
    """Whole months (at least 1) the new readings cover."""
    return max(1, -(-((date.today() - day).days if day else 0) // 30))


def expectation(point: str, source: str, meters: list) -> dict:
    """{scope: total|meter, limit / limits {n: ...}, basis} - consumption
    above which the dashboard shows ⚠️. Electricity: the site gives monthly
    kWh only for both zones together, so the zones' sum is compared with the
    largest month of the last year. Water: the site has no volumes, so the
    fastest rate between our own submissions (x2), or a fallback."""
    if source == "koec_cabinet":
        cache = CACHE_DIR / f"{point}.cabinet.json"
        fees = json.loads(cache.read_text()).get("fees", {}) if cache.exists() else {}
        kwh = [v["kwh"] for _, v in sorted(fees.items())[-12:] if v.get("kwh") is not None]
        if not kwh:
            return {}
        prev = meters[0].get("previous_date")
        k = months_since(datetime.strptime(prev, "%d.%m.%Y").date() if prev else None)
        return {"scope": "total", "limit": max(kwh) * k,
                "basis": f"найбільше за місяць за рік: {fmt(max(kwh))} кВт·год" + (f" × {k} міс." if k > 1 else "")}
    subs = [h for h in history() if h["point"] == point]
    k = months_since(datetime.fromisoformat(subs[-1]["time"]).date() if subs else None)
    rates = {}  # meter n -> fastest monthly consumption between submissions
    for a, b in zip(subs, subs[1:]):
        days = max(1, (datetime.fromisoformat(b["time"]) - datetime.fromisoformat(a["time"])).days)
        sent_a = {m["n"]: m["sent"] for m in a["meters"]}
        for m in b["meters"]:
            if m["n"] in sent_a:
                rates[m["n"]] = max(rates.get(m["n"], 0), (m["sent"] - sent_a[m["n"]]) / days * 30)
    if rates:
        limits = {m["n"]: 2 * rates.get(m["n"], WATER_MONTHLY_FALLBACK / 2) * k for m in meters}
        basis = "удвічі більше за найшвидше споживання між подачами"
    else:
        limits = {m["n"]: WATER_MONTHLY_FALLBACK * k for m in meters}
        basis = f"поки мало історії: {fmt(WATER_MONTHLY_FALLBACK)} м³ на місяць"
    return {"scope": "meter", "limits": {str(n): round(v, 3) for n, v in limits.items()},
            "basis": basis + (f" × {k} міс." if k > 1 else "")}


def with_expectation(point: str, source: str, meters: list) -> list:
    """The meters plus warn_above (per meter), warn_total_above (the sum of
    all meters) and warn_basis - inside `meters`, as sensor.oselya_meters
    exposes only the attributes listed in its config."""
    e = expectation(point, source, meters)
    return [{**m, "warn_above": e.get("limits", {}).get(str(m["n"])),
             "warn_total_above": e.get("limit"), "warn_basis": e.get("basis")} for m in meters]


def write_state(point: str, info: str, meters: list) -> None:
    pts = points()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    layouts = state.get("layouts", {})
    layouts[point] = [{"n": m["n"], "name": m["name"], "unit": m["unit"]} for m in meters]
    STATE.write_text(json.dumps({
        "updated": datetime.now().isoformat(timespec="seconds"),
        "point": point, "label": pts[point]["label"], "info": info,
        "meters": with_expectation(point, pts[point]["source"], meters),
        "history": [h for h in history() if h["point"] == point][-6:][::-1],
        # For the dashboard: picker options (label -> point) and each point's
        # meter names, so build_dashboard.py can label the input fields.
        "points": {p["label"]: k for k, p in sorted(pts.items(), key=lambda kp: kp[1]["label"])},
        "layouts": {k: v for k, v in layouts.items() if k in pts},
    }, ensure_ascii=False, indent=1))


def listing(meters: list, values: dict | None = None) -> str:
    return ", ".join(f"{m['name'].lower()} {fmt(values[m['n']] if values else m['previous'])}"
                     for m in meters) + f" {meters[0]['unit']}"


def pending_note(point: str) -> str:
    pending = [h for h in history() if h["point"] == point and h.get("accepted") and not h.get("applied")]
    if not pending:
        return ""
    return "; 📨 чекає обробки: " + ", ".join(f"{m['name'].lower()} {fmt(m['sent'])}" for m in pending[-1]["meters"])


def get_point(point: str) -> dict:
    pts = points()
    if point not in pts:
        raise MeterError(f"невідома точка обліку {point!r}")
    return pts[point]


def load(point: str) -> None:
    p = get_point(point)
    info, meters, _ = READERS[p["source"]](point, p["cfg"])
    refresh_pending(point, meters)
    write_state(point, info, meters)
    print(f"На сайті ({info}): {listing(meters)}{pending_note(point)}")


def refresh_bill(point: str) -> None:
    """Daily (host sync): re-check a point with submissions still waiting to
    be applied, and refresh the dashboard's state if it shows that point."""
    if not any(h["point"] == point and h.get("accepted") and not h.get("applied") for h in history()):
        return
    p = get_point(point)
    info, meters, _ = READERS[p["source"]](point, p["cfg"])
    refresh_pending(point, meters)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if state.get("point") == point:
        write_state(point, info, meters)


def check(meters: list, raw: list[str]) -> dict[int, float]:
    """{meter n: value} after the site's own limits (and whole numbers where
    the site wants them)."""
    if len(raw) < len(meters):
        raise MeterError(f"потрібно {len(meters)} показники, отримано {len(raw)}")
    values = {}
    for m, r in zip(meters, raw):
        v = float(r)
        if m["precision"] == 0 and v != int(v):
            raise MeterError(f"{m['name']}: лише ціле число")
        if m["min"] is not None and v < m["min"] - 0.0005:
            raise MeterError(f"{m['name']} {fmt(v)} менше, ніж на сайті ({fmt(m['previous'])})"
                             if m["min"] == m["previous"] else
                             f"{m['name']} {fmt(v)}: сайт приймає від {fmt(m['min'])}")
        if m["max"] is not None and v > m["max"] + 0.0005:
            raise MeterError(f"{m['name']} {fmt(v)}: сайт приймає до {fmt(m['max'])} "
                             f"(на сайті {fmt(m['previous'])})")
        values[m["n"]] = v
    return values


def submit(point: str, raw: list[str]) -> None:
    p = get_point(point)
    info, meters, handle = READERS[p["source"]](point, p["cfg"])
    values = check(meters, raw)
    if p["source"] == "brovk_water":
        form = handle
        form.submit(values)
        response = form.response.text
        accepted = WATER_ACCEPTED in response
        on_file = {m["n"]: m["previous"] for m in form.meters}
    else:
        cab, form = handle
        if form["closed"]:
            raise MeterError(f"цього місяця показники вже внесено ({datetime.fromisoformat(form['date']):%d.%m.%Y}) - "
                             "нові сайт прийме з 1-го числа наступного місяця")
        day = date.today().isoformat()
        if day not in form["dates"]:
            raise MeterError(f"сайт не приймає показники за {day}")
        response = cab.submit_readings(form, values, day).text
        new = cab.readings_form()
        if new["closed"]:  # the usual outcome: the form closes for the month
            accepted = new["date"] == day and abs(new["value"] - values[min(values)]) < 0.5
            on_file = dict(values) if accepted else {}
        else:
            on_file = {z["n"]: z["previous"] for z in new["zones"]}
            accepted = new["date"] == day and all(abs(on_file[n] - v) < 0.0005 for n, v in values.items())

    save_history(history() + [{
        "time": datetime.now().isoformat(timespec="seconds"), "point": point,
        "meters": [{"n": m["n"], "name": m["name"], "unit": m["unit"], "before": m["previous"],
                    "sent": values[m["n"]]} for m in meters],
        "accepted": accepted, "applied": None,
    }])
    meters_now = [{**m, "previous": on_file.get(m["n"], m["previous"])} for m in meters]
    refresh_pending(point, meters_now)
    write_state(point, info, meters_now)
    sent = listing(meters, values)
    if history()[-1]["applied"]:
        print(f"✅ Передано, вже на сайті: {sent}")
    elif accepted:
        print(f"📨 Сайт прийняв: {sent} - з'являться протягом робочого дня")
    else:
        RESPONSE.write_text(response)
        print(f"⚠️ Сайт не прийняв показники ({sent}) - передай на сайті")


def main() -> None:
    args = sys.argv[1:]
    try:
        if len(args) == 2 and args[0] == "load":
            load(args[1])
        elif len(args) >= 3 and args[0] == "submit":
            submit(args[1], args[2:])
        else:
            raise SystemExit(__doc__)
    except MeterError as e:
        raise SystemExit(f"❌ {e}")
    except (brovk_water.WaterError, koec_cabinet.CabinetError, OSError) as e:  # requests' errors are OSErrors
        raise SystemExit(f"❌ Сайт: {e}")
    except ValueError as e:
        raise SystemExit(f"❌ Невірне число: {e}")


if __name__ == "__main__":
    main()
