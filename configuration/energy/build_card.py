#!/usr/bin/env python3
"""Rebuild the energy table card at the end of the Home view of the
Overview dashboard from sensor.monthly_energy_table (energy/monthly_table.py).

One table for everything: a row per year (its totals), each an HTML
<details> that opens that year's months in the same columns, the year's
totals then moving under its last month (click-to-expand
without JS, same trick as the Payments tables), then the "Всього" row.
No heading above the table: years are opened one by one in the table itself.
The card is found again by MARKER and replaced
in place, so the rest of the view is left alone. Styled like the Payments
tables: bold left-aligned headers with a small coloured icon before the name,
short month labels ("Вер 26"). Columns
Сонце / Експорт / Імпорт / Бойлер / Будинок; each cell shows kWh and, for
three of them, the matching ₴ amount under it in small type: Сонце -
potential (the station's income at the green tariff), Експорт - net income
(what the meter's saldo really paid), Будинок - house_cost (= Сонце - Експорт,
what the house's consumption took from the station: a deficit month's saldo at
night / day tariffs, the rest at the ENERA green tariff, see monthly_table.py;
the year and total rows add its share in %), split into those three parts in
₴ (SOURCES) above the ₴ total, deficit months only.
Month names link to the ENERA act PDF when there is one (signed link from
sensor.document_links). Always the compact layout (short names, smaller
type): the Home view is masonry, its columns are ~370px even on desktop.
No Бойлер column (see SKIP).

Edits go through the HA WebSocket API, never .storage directly (see memory:
homecontroll_dashboard_live_edit). Idempotent - re-run any time.
Run: ../statistics/oselya/.venv/bin/python build_card.py
"""
import json
from pathlib import Path

import websocket

TOKEN = (Path.home() / ".secrets" / "ha_token").read_text().strip()
URL_PATH, VIEW_PATH = None, "default_view"  # None = Overview (lovelace)
MARKER = "sensor.monthly_energy_table"  # how the card is found again

# (kWh key, ₴ key or None, icon, colour, name, phone name, ₴ kind); a cell shows
# the kWh on top and, where there is one, the ₴ amount under it in small type
COLUMNS = [
    ("solar", "potential", "solar-power-variant", "#ffc107", "Сонце", "Сонце", "money"),
    ("exp", "net", "transmission-tower-export", "#4caf50", "Експорт", "Експ.", "net"),
    ("imp", None, "transmission-tower-import", "#44739e", "Імпорт", "Імп.", None),
    ("boiler", None, "water-boiler", "#ffc107", "Бойлер", "Бойл.", None),
    ("house", "house_cost", "home-lightning-bolt", "#ff9800", "Будинок", "Буд.", "cost"),
]
# columns left out of the table: Бойлер as its own column did not fit the phone,
# it is shown inside the Будинок cell instead ("143 (46)", see cell())
SKIP = {"boiler"}
# relative column widths: kWh-only columns hold short numbers, Будинок carries
# "12428 ₴ (21%)"
NARROW = {"imp": 0.75, "house": 1.25}
# in a deficit month the Будинок cell also splits its ₴ into night import /
# day import / solar, each in its own colour; <em> because ha-markdown strips
# class attributes (coloured by position, see css)
BOILER_COLOUR = "#66bb6a"  # green: the boiler runs on surplus solar
SOURCES = [("cost_night", "weather-night", "#5c6bc0"), ("cost_day", "white-balance-sunny", "#ef6c00"),
           ("cost_solar", "solar-power-variant", "#f9a825")]


def cols_for(phone: bool) -> list:
    return [c for c in COLUMNS if c[0] not in SKIP]


def cell(kwh: str, money: str | None, kind: str | None, var: str, bold: bool, with_share: bool) -> str:
    v = f"{var}.{kwh}"
    text = f"{{{{ ({v} | round(0) | int) if {v} is not none else '–' }}}}"
    if kwh == "house":  # the boiler's share of it, in its own colour (<i>, see css)
        text += f"{{% if {var}.boiler is not none %}} <i>({{{{ {var}.boiler | round(0) | int }}}})</i>{{% endif %}}"
    if bold:
        text = f"<b>{text}</b>"
    if kwh == "house":  # deficit months only: house_cost split by source (monthly_table.py), total under it
        text += (f"{{% if {var}.cost_night is defined %}}"
                 + "".join(f"<br><em><ha-icon icon=\"mdi:{icon}\"></ha-icon>{{{{ {var}.{key} }}}} ₴</em>"
                           for key, icon, _ in SOURCES)
                 + "{% endif %}")
    if money:
        m = f"{var}.{money}"
        amount = f"{{{{ '%+d' % {m} }}}}" if kind == "net" else f"{{{{ {m} }}}}"
        share = (f"{{% if {var}.potential > 0 %}} ({{{{ (100 * {m} / {var}.potential) | round(0) | int }}}}%)"
                 "{% endif %}") if kind == "cost" and with_share else ""
        text += f"<br><small>{amount} ₴{share}</small>"
    return text


# gas vs the electric boiler: m³ price, kWh of heat in 1 m³, boiler efficiency;
# the heat for one full 80 l boiler (15 -> 55 °C)
GAS_PRICE, GAS_KWH, GAS_EFF, BOILER_KWH = 12, 9.3, 0.9, 3.7
# plain-language note under the table (for the user's mother-in-law): is the
# boiler cheaper on gas or on electricity; the ₴/kWh is the last full month's
# ENERA green tariff after tax (what a kWh of our solar sells for). The user
# cut the column legend that used to precede it.
# "Вер" -> "Вересень"
MONTH_NAME = ("{%- set month_name = {'Січ': 'Січень', 'Лют': 'Лютий', 'Бер': 'Березень', 'Кві': 'Квітень',"
              " 'Тра': 'Травень', 'Чер': 'Червень', 'Лип': 'Липень', 'Сер': 'Серпень', 'Вер': 'Вересень',"
              " 'Жов': 'Жовтень', 'Лис': 'Листопад', 'Гру': 'Грудень'} %}")
# the "143 (46)" legend, with the latest month that has boiler data
BOILER_NOTE = (
    "{%- set bm = rows | selectattr('kind', 'eq', 'month') | rejectattr('boiler', 'none') | list | last"
    " if rows | selectattr('kind', 'eq', 'month') | rejectattr('boiler', 'none') | list else none -%}\n"
    + MONTH_NAME +
    "{%- if bm %}<p>{{ month_name[bm.label.split(' ')[0]] }}, <ha-icon icon=\"mdi:home-lightning-bolt\"></ha-icon>: <b>{{ bm.house | round(0) | int }} kWh</b>, "
    "з них <ha-icon icon=\"mdi:water-boiler\"></ha-icon>: <b><i>{{ bm.boiler | round(0) | int }} kWh</i></b>.<br>"
    "Експорт, <ha-icon icon=\"mdi:transmission-tower-export\"></ha-icon>: <b>{{ bm.exp | round(0) | int }} kWh</b>, "
    "сальдо: <b>{{ (bm.exp - bm.imp) | round(0) | int }} kWh</b>"  # export - import, what ENERA pays for
    "{% if bm.net is not none %} <small>({{ '%+d' % bm.net }} ₴)</small>{% endif %}.</p>\n\n{% endif %}"
)
EXPLAIN = (
    "{%- set full = rows | selectattr('kind', 'eq', 'month') | rejectattr('label', 'search', '⏳') | list -%}\n"
    "{%- set m = full | last if full else none -%}\n"
    "{%- if m and m.green -%}\n"
    "{%- set el = m.green -%}\n"
    f"{{%- set gas = {GAS_PRICE} / ({GAS_KWH} * {GAS_EFF}) -%}}\n"
    "\nНагріти 80 л води (з 15 до 55 °C):\n"
    f"- електричним бойлером: {f"{BOILER_KWH:g}".replace(".", ",")} кВт·год × {{{{ ('%.2f' % el) | replace('.', ',') }}}} ₴ ≈ "
    f"<b>{{{{ ({BOILER_KWH} * el) | round(0) | int }}}} ₴</b>\n"
    f"- газовим котлом: {{{{ ('%.2f' % ({BOILER_KWH} / ({GAS_KWH} * {GAS_EFF}))) | replace('.', ',') }}}} м³ × {GAS_PRICE} ₴ ≈ "
    f"<b>{{{{ ({BOILER_KWH} * gas) | round(0) | int }}}} ₴</b>\n"
    "{%- endif %}"
)


def content(phone: bool) -> str:
    cols = cols_for(phone)

    def row(first: str, var: str, bold: bool) -> str:
        return ("<tr><td>" + first + "</td>"
                + "".join(f"<td>{cell(k, m, kind, var, bold, bold)}</td>" for k, m, _, _, _, _, kind in cols)
                + "</tr>")
    names = "<tr><th>Період</th>" + "".join(
        f"<th><ha-icon icon=\"mdi:{icon}\"></ha-icon> {pname if phone else name}"
        + "</th>"
        for _, m, icon, _, name, pname, _ in cols) + "</tr>"
    month_label = "{%- set lbl = r.label | replace(' 20', ' ') -%}"  # "Вер 26"
    return (
        "{%- set rows = state_attr('sensor.monthly_energy_table', 'rows') or [] -%}\n"
        "{%- set acts = state_attr('sensor.document_links', 'enera') or {} -%}\n"
        f"<table>{names}</table>\n"
        "{% for s in rows if s.kind == 'sum' -%}\n"
        "{%- set y = s.label[-4:] -%}\n"
        f"<details><summary><table>{row('<b>{{ y }}</b>', 's', True)}</table></summary><table>\n"
        "{% for r in rows if r.kind == 'month' and r.label.split(' ')[1] == y -%}\n"
        f"{month_label}\n"
        + row("{% if acts.get(r.get('act')) %}<a href=\"{{ acts[r.act] }}\" target=\"_blank\" "
              "rel=\"noopener\">{{ lbl }}</a>{% else %}{{ lbl }}{% endif %}", "r", False) + "\n"
        "{% endfor %}"
        # an open year repeats its totals under its last month; the summary
        # row on top then shows only the year (see css)
        + row("<b>{{ y }}</b>", "s", True) + "</table></details>\n"
        "{% endfor -%}\n"
        "{% for t in rows if t.kind == 'total' %}"
        f"<table>{row('<b>Всього</b>', 't', True)}</table>"
        "{% endfor %}\n\n"
        + BOILER_NOTE
        + EXPLAIN
    )


def css(phone: bool) -> str:
    cols = cols_for(phone)
    first = 17  # just "Вер 26 ⏳" after the month indent
    weights = [NARROW.get(c[0], 1.0) for c in cols]
    unit = (100 - first) / sum(weights)
    colours = "".join(f"ha-icon[icon=\"mdi:{icon}\"] {{ color: {colour}; }}\n"
                      for _, _, icon, colour, *_ in COLUMNS)
    return (
        "table { width: 100%; table-layout: fixed; border-collapse: collapse; margin: 0 !important; }\n"
        + "".join(f"th:nth-child({i + 2}), td:nth-child({i + 2}) {{ width: {w * unit:.2f}%; }}\n"
                  for i, w in enumerate(weights)) +
        f"th, td {{ padding: {'2px 2px' if phone else '3px 6px'} !important; text-align: right; }}\n"
        f"th:first-child, td:first-child {{ width: {first}%; text-align: left; white-space: nowrap; }}\n"
        "th, td { border: 1px solid var(--divider-color) !important; border-top: none !important; white-space: nowrap; box-sizing: border-box; }\n"
        "th { border-top: 1px solid var(--divider-color) !important; }\n"
        "th { font-weight: normal; vertical-align: bottom; text-align: right !important; }\n"
        "th:first-child { text-align: left !important; }\n"
        "td small { color: var(--secondary-text-color); }\n"
        f"i {{ font-style: normal; color: {BOILER_COLOUR}; }}\n"
        "td em { font-style: normal; font-size: smaller; white-space: nowrap; }\n"
        "td em ha-icon[icon] { --mdc-icon-size: 12px; color: inherit; margin-right: 2px; }\n"
        + "".join(f"td em:nth-of-type({i + 1}) {{ color: {c}; }}\n" for i, (_, _, c) in enumerate(SOURCES))
        # ha-markdown strips class attributes, so colour the ₴ lines by column
        + "".join(f"td:nth-child({i + 2}) small {{ color: {c}; }}\n"
                  for i, (_, _, _, _, _, _, kind) in enumerate(cols)
                  for c in [{"net": "#4caf50", "cost": "#f44336"}.get(kind)] if c) +
        "summary { list-style: none; cursor: pointer; }\n"
        "summary::-webkit-details-marker { display: none; }\n"
        "summary td:first-child::before { content: '▸ '; }\n"
        "details[open] > summary td:first-child::before { content: '▾ '; }\n"
        "details[open] > table td:first-child { padding-left: 10px !important; }\n"
        "details[open] > summary td:not(:first-child) { font-size: 0; }\n"
        "details[open] > summary td:not(:first-child) * { display: none; }\n"
        "details[open] > table tr:last-child td { border-top: 2px solid var(--divider-color) !important; }\n"
        "details[open] > table tr:last-child td:first-child { padding-left: 6px !important; }\n"
        + colours
        # styled like the Payments tables ("Квартира 197"): bold headers aligned
        # left with a small icon before the name, numbers right-aligned
        + "th, th:first-child { font-weight: bold; text-align: left !important; vertical-align: middle; }\n"
        "th, td { padding: 3px 6px !important; }\n"
        "ha-icon { --mdc-icon-size: 16px; vertical-align: text-bottom; }\n"
        + ("table { font-size: 12px; }\n" if phone else "")
        # the boiler / gas note under the table: tight and small, so "≈ 19 ₴"
        # stays on its line on a phone
        + "p, ul { margin: 2px 0 !important; font-size: 12px; }\n"
        "ul { padding-left: 18px; }\n"
        "table + p { margin-top: 6px !important; }\n"
        "p + p { margin-top: 8px !important; }\n"
        "p small { font-size: inherit; color: #4caf50; }\n"  # the export ₴, green like in the table
    )


def card() -> dict:
    # Kept in a vertical-stack: as a bare top-level card of the masonry view
    # the card_mod table styles are not applied.
    return {"type": "vertical-stack", "cards": [
        {"type": "markdown", "content": content(phone=True),
         "card_mod": {"style": {"ha-markdown $": css(phone=True)}}}]}


class HA:
    def __init__(self):
        self.ws = websocket.create_connection("ws://localhost:8123/api/websocket", timeout=10)
        assert json.loads(self.ws.recv())["type"] == "auth_required"
        self.ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        assert json.loads(self.ws.recv())["type"] == "auth_ok"
        self._id = 0

    def call(self, payload: dict):
        self._id += 1
        payload["id"] = self._id
        self.ws.send(json.dumps(payload))
        msg = json.loads(self.ws.recv())
        assert msg.get("success"), msg
        return msg.get("result")


def main():
    ha = HA()
    config = ha.call({"type": "lovelace/config", "url_path": URL_PATH})
    view = next(v for v in config["views"] if v.get("path") == VIEW_PATH)
    cards = view["cards"]
    old = [i for i, c in enumerate(cards) if MARKER in json.dumps(c)]
    if old:
        cards[old[0]] = card()
    else:
        cards.append(card())
    ha.call({"type": "lovelace/config/save", "url_path": URL_PATH, "config": config})
    print(f"{'replaced' if old else 'added'} the energy table on {VIEW_PATH}")


if __name__ == "__main__":
    main()
