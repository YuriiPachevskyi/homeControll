#!/usr/bin/env python3
"""Rebuild the energy table card on the "monthly-energy" view of
`dashboard-deye` from sensor.monthly_energy_table (energy/monthly_table.py).

One table for everything: a row per year (its totals), each an HTML
<details> that opens that year's months in the same columns, the year's
totals then moving under its last month (click-to-expand
without JS, same trick as the Payments tables), then the "Всього" row.
The title is a section heading above the card; tapping it toggles
input_boolean.monthly_energy_expanded, which opens every year at once.
Styled like the Payments tables and, like them, one ~500px column wide
(sections view): bold left-aligned headers with a small coloured icon before
the name, short month labels ("Вер 26"). Columns
Сонце / Експорт / Імпорт / Бойлер / Будинок; each cell shows kWh and, for
three of them, the matching ₴ amount under it in small type: Сонце -
potential (income if the house had used nothing), Експорт - net income,
Будинок - house_cost (what its consumption cost; the year and total rows add
its share in %, desktop only).
Month names link to the ENERA act PDF when there is one (signed link from
sensor.document_links). Desktop and phone get separate conditional cards
(phone: short names, smaller type). No Бойлер column (see SKIP).

Edits go through the HA WebSocket API, never .storage directly (see memory:
homecontroll_dashboard_live_edit). Idempotent - re-run any time.
Run: ../statistics/oselya/.venv/bin/python build_card.py
"""
import json
from pathlib import Path

import websocket

TOKEN = (Path.home() / ".ha_token").read_text().strip()
URL_PATH, VIEW_PATH = "dashboard-deye", "monthly-energy"
TITLE = "Генерація"
EXPANDED = "input_boolean.monthly_energy_expanded"  # packages/monthly_energy_table.yaml

# (kWh key, ₴ key or None, icon, colour, name, phone name, ₴ kind); a cell shows
# the kWh on top and, where there is one, the ₴ amount under it in small type
COLUMNS = [
    ("solar", "potential", "solar-power-variant", "#ffc107", "Сонце", "Сонце", "money"),
    ("exp", "net", "transmission-tower-export", "#4caf50", "Експорт", "Експ.", "net"),
    ("imp", None, "transmission-tower-import", "#44739e", "Імпорт", "Імп.", None),
    ("boiler", None, "water-boiler", "#e91e63", "Бойлер", "Бойл.", None),
    ("house", "house_cost", "home-lightning-bolt", "#ff9800", "Будинок", "Буд.", "cost"),
]
# Бойлер is left out: 5 columns don't fit the ~500px card (and it only has data
# from Sep 2026 anyway); kept in COLUMNS so it is easy to bring back
SKIP = {"boiler"}


def cols_for(phone: bool) -> list:
    return [c for c in COLUMNS if c[0] not in SKIP]


def cell(kwh: str, money: str | None, kind: str | None, var: str, bold: bool, with_share: bool) -> str:
    v = f"{var}.{kwh}"
    text = f"{{{{ ({v} | round(0) | int) if {v} is not none else '–' }}}}"
    if bold:
        text = f"<b>{text}</b>"
    if money:
        m = f"{var}.{money}"
        amount = f"{{{{ '%+d' % {m} }}}}" if kind == "net" else f"{{{{ {m} }}}}"
        share = (f"{{% if {var}.potential > 0 %}} ({{{{ (100 * {m} / {var}.potential) | round(0) | int }}}}%)"
                 "{% endif %}") if kind == "cost" and with_share else ""
        text += f"<br><small>{amount} ₴{share}</small>"
    return text


def content(phone: bool) -> str:
    cols = cols_for(phone)

    def row(first: str, var: str, bold: bool) -> str:
        return ("<tr><td>" + first + "</td>"
                + "".join(f"<td>{cell(k, m, kind, var, bold, bold and not phone)}</td>" for k, m, _, _, _, _, kind in cols)
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
        f"<details{{{{ ' open' if is_state('{EXPANDED}', 'on') }}}}><summary><table>{row('<b>{{ y }}</b>', 's', True)}</table></summary><table>\n"
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
        "<small>клік по «Генерація» — усі місяці · по року — його місяці · посилання на місяці — акти ENERA</small>"
    )


def css(phone: bool) -> str:
    cols = cols_for(phone)
    n = len(cols)
    first = 18
    other = (100 - first) / n
    colours = "".join(f"ha-icon[icon=\"mdi:{icon}\"] {{ color: {colour}; }}\n"
                      for _, _, icon, colour, *_ in COLUMNS)
    return (
        "table { width: 100%; table-layout: fixed; border-collapse: collapse; margin: 0 !important; }\n"
        f"th, td {{ width: {other:.2f}%; padding: {'2px 2px' if phone else '3px 6px'} !important; text-align: right; }}\n"
        f"th:first-child, td:first-child {{ width: {first}%; text-align: left; white-space: nowrap; }}\n"
        "th, td { border: 1px solid var(--divider-color) !important; border-top: none !important; white-space: nowrap; box-sizing: border-box; }\n"
        "th { border-top: 1px solid var(--divider-color) !important; }\n"
        "th { font-weight: normal; vertical-align: bottom; text-align: right !important; }\n"
        "th:first-child { text-align: left !important; }\n"
        "td small { color: var(--secondary-text-color); }\n"
        # ha-markdown strips class attributes, so colour the ₴ lines by column
        + "".join(f"td:nth-child({i + 2}) small {{ color: {c}; }}\n"
                  for i, (_, _, _, _, _, _, kind) in enumerate(cols)
                  for c in [{"net": "#4caf50", "cost": "#f44336"}.get(kind)] if c) +
        "summary { list-style: none; cursor: pointer; }\n"
        "summary::-webkit-details-marker { display: none; }\n"
        "summary td:first-child::before { content: '▸ '; }\n"
        "details[open] > summary td:first-child::before { content: '▾ '; }\n"
        "details[open] > table td:first-child { padding-left: 16px !important; }\n"
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
    )


def headings() -> list:
    """The table's title as a section heading: tapping it toggles EXPANDED
    (every year open / all collapsed). Two headings shown by state, so the
    arrow always says what a tap will do - like the Payments "Розгорнути"."""
    def heading(arrow: str, state: str) -> dict:
        return {"type": "heading", "heading": f"{arrow} {TITLE}", "heading_style": "title",
                "icon": "mdi:solar-power-variant",
                "tap_action": {"action": "perform-action", "perform_action": "input_boolean.toggle",
                               "target": {"entity_id": EXPANDED}},
                "visibility": [{"condition": "state", "entity": EXPANDED, "state": state}]}
    return [heading("▸", "off"), heading("▾", "on")]


def card(phone: bool) -> dict:
    query = "(max-width: 767px)" if phone else "(min-width: 768px)"
    return {"type": "conditional", "conditions": [{"condition": "screen", "media_query": query}],
            "card": {"type": "markdown", "content": content(phone),
                     "card_mod": {"style": {"ha-markdown $": css(phone)}}}}


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
    # A sections view keeps the card one column wide (~500px, like the
    # Payments tables) instead of stretching it over the whole screen.
    view.pop("cards", None)
    view.update({"type": "sections", "max_columns": 4,
                 "sections": [{"type": "grid", "cards": [*headings(), card(phone=False), card(phone=True)]}]})
    ha.call({"type": "lovelace/config/save", "url_path": URL_PATH, "config": config})
    print(f"rebuilt the energy table on {URL_PATH}/{VIEW_PATH}")


if __name__ == "__main__":
    main()
