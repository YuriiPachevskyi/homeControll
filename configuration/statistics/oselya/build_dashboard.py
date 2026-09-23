#!/usr/bin/env python3
"""Rebuild the "tables" view on the dedicated `dashboard-payments` sidebar
dashboard from objects.yaml. Idempotent - safe to re-run any time an object
or bill is added/removed there (e.g. when "Квартира 177" gets added); it
regenerates the whole view rather than needing a hand-written patch script.

Edits go through the HA WebSocket API (`lovelace/config/save`), not the
`.storage` file directly - that file is root-owned, and the frontend's own
autosave can race a direct file write (see memory:
homecontroll_dashboard_live_edit / oselya_payments_system).

Run manually: ./.venv/bin/python build_dashboard.py
"""
import json
from pathlib import Path

import websocket
import yaml

TOKEN = (Path.home() / ".ha_token").read_text().strip()
OBJECTS_YAML = Path(__file__).parent / "objects.yaml"
DASHBOARD_URL_PATH = "dashboard-payments"


def table_content(obj_key: str, bills: list, mobile: bool) -> str:
    """An object's payments for the selected year: a header table, then per
    month an HTML <details> (click-to-expand in the markdown card without any
    JS, per device) whose <summary> is a one-row table (month, accrued, paid,
    due, ✅/🟡/⏳) and whose body is that month's bill rows in the same
    columns - plus a separate row for a late fee/inflation part when > 0,
    since that's paid separately. All the tables share fixed column widths
    (table_css()), so they line up like one. Each bill name links to its
    receipt PDF (signed /api/documents link + target=_blank, same as the DAP
    table's ENERA acts). input_boolean.oselya_payments_expanded opens every
    month at once. `bills` is [[bill_key, label], ...] from objects.yaml.
    """
    bills_json = json.dumps(bills, ensure_ascii=False)
    status = "{{ '✅' if r.status == 'paid' else '🟡' if r.status == 'partial' else '⏳' }}"
    b_status = "{{ '✅' if b.status == 'paid' else '⏳' }}"
    s_status = "{{ '✅' if b.secondary_status == 'paid' else '⏳' }}"
    money = "{{ '%%.2f' %% %s }}"
    bold = "<b>{{ '%%.2f' %% %s }}</b>"

    def linked(text: str) -> str:  # `d` = this bill's receipt link, set in the loop below
        return ("↳ {% if d %}<a href=\"{{ d }}\" target=\"_blank\" rel=\"noopener\">"
                + text + "</a>{% else %}" + text + "{% endif %}")

    def row(cells: list, tag: str = "td") -> str:
        return "<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>"
    month = "<b>{{ months[r.period[5:7] | int - 1] }}</b>"
    if mobile:
        head = row(["Період", "До сплати", "Статус"], "th")
        month_row = row([month, bold % "r.total_due", status])
        bill_row = row([linked("{{ label }}"), money % "b.total_due", b_status])
        sec_row = row([linked("{{ b.secondary_label }}"), money % "b.secondary_due", s_status])
        total_row = row(["<b>Разом</b>", "<b>{{ '%.2f' % (rows | sum(attribute='total_due')) }}</b>", ""])
    else:
        head = row(["Період", "Нарах.", "Опл.", "До сплати", "Статус"], "th")
        month_row = row([month, bold % "r.accrued", bold % "r.paid", bold % "r.total_due", status])
        bill_row = row([linked("{{ label }}"), money % "b.accrued", money % "b.paid", money % "b.total_due", b_status])
        sec_row = row([linked("{{ b.secondary_label }}"), "", "", money % "b.secondary_due", s_status])
        # "До сплати" is a running balance, not a period amount - summing it
        # across months is meaningless, so the totals row only fills Нарах./Опл.
        total_row = row(["<b>Разом</b>", "<b>{{ '%.2f' % (rows | sum(attribute='accrued')) }}</b>",
                         "<b>{{ '%.2f' % (rows | sum(attribute='paid')) }}</b>", "", ""])
    return (
        "{%- set y = states('input_select.oselya_payments_year') -%}\n"
        "{%- set expanded = is_state('input_boolean.oselya_payments_expanded', 'on') -%}\n"
        "{%- set objs = state_attr('sensor.oselya_payments', 'objects') or {} -%}\n"
        "{%- set all_bills = state_attr('sensor.oselya_payments', 'bills') or {} -%}\n"
        f"{{%- set rows = objs.get('{obj_key}', {{}}).get('rows', []) "
        "| selectattr('period', 'match', '^' + y) | list -%}\n"
        "{%- set docs = state_attr('sensor.document_links', 'oselya') or {} -%}\n"
        "{%- set months = ['Січень', 'Лютий', 'Березень', 'Квітень', 'Травень', 'Червень', "
        "'Липень', 'Серпень', 'Вересень', 'Жовтень', 'Листопад', 'Грудень'] -%}\n"
        "**{{ y }} рік**\n\n"
        f"<table>{head}</table>\n"
        "{% for r in rows -%}\n"
        f"<details{{{{ ' open' if expanded }}}}><summary><table>{month_row}</table></summary><table>\n"
        f"{{% for bill_key, label in {bills_json} -%}}\n"
        # No `| first` here: the frontend renders in strict mode, where `first`
        # of an empty list (a month this bill has no receipt for) is an error
        # that blanks the whole card.
        f"{{%- set found = all_bills.get('{obj_key}.' ~ bill_key, {{}}).get('rows', []) "
        "| selectattr('period', 'eq', r.period) | list -%}\n"
        "{%- set b = found[0] if found else none -%}\n"
        "{%- if b -%}\n"
        f"{{%- set d = docs.get('{obj_key}.' ~ bill_key ~ '_' ~ r.period) -%}}\n"
        f"{bill_row}\n"
        "{%- if (b.secondary_due or 0) > 0 %}\n"
        f"{sec_row}\n"
        "{%- endif -%}\n"
        "{%- endif -%}\n"
        "{% endfor %}\n"
        "</table></details>\n"
        "{% endfor -%}\n"
        f"<table>{total_row}</table>\n\n"
        "грн · ✅ оплачено · 🟡 частково · ⏳ очікує оплати · клік по місяцю — його платежі"
    )


def table_css(mobile: bool) -> str:
    """Fixed, shared column widths so the separate tables line up; the month
    row gets its own ▸/▾ marker (the native one sits outside the table)."""
    widths = ["44%", "32%", "24%"] if mobile else ["31%", "17%", "17%", "19%", "16%"]
    cols = "".join(f"th:nth-child({i + 1}), td:nth-child({i + 1}) {{ width: {w}; }}\n"
                   for i, w in enumerate(widths))
    return (
        "table { width: 100%; table-layout: fixed; border-collapse: collapse; margin: 0 !important; }\n"
        + cols +
        "th, td { padding: 3px 6px !important; text-align: right; }\n"
        "th:first-child, td:first-child { text-align: left; }\n"
        "th:last-child, td:last-child { text-align: center; }\n"
        "summary { list-style: none; cursor: pointer; }\n"
        "summary::-webkit-details-marker { display: none; }\n"
        "summary td:first-child::before { content: '▸ '; }\n"
        "details[open] > summary td:first-child::before { content: '▾ '; }\n"
        "details[open] > table td:first-child { padding-left: 18px !important; }\n"
        "details { border-top: 1px solid var(--divider-color); }\n"
        + ("table { font-size: 12px; }\n" if mobile else "")
    )


def summary_card(objects_cfg: dict) -> dict:
    entries = [[k, v["label"]] for k, v in objects_cfg.items()]
    entries_json = json.dumps(entries, ensure_ascii=False)
    content = (
        "{%- set objs = state_attr('sensor.oselya_payments', 'objects') or {} -%}\n"
        "{%- set all_years = objs.values() | map(attribute='year_totals') | sum(start=[]) "
        "| map(attribute='year') | unique | sort | list -%}\n"
        "{%- set years = all_years[-3:] -%}\n"  # cap at 3 columns so this never outgrows the screen
        "| Об'єкт | {% for y in years %}{{ y }} | {% endfor %}\n"
        "|:--|{% for y in years %}--:|{% endfor %}\n"
        f"{{% for key, label in {entries_json} -%}}\n"
        "{%- set yt = objs.get(key, {}).get('year_totals', []) -%}\n"
        "| {{ label }} | {% for y in years -%}\n"
        "{%- set match = yt | selectattr('year', 'eq', y) | map(attribute='total') | list -%}\n"
        "{{ '%.0f' % (match[0] if match else 0) }} | {% endfor %}\n"
        "{% endfor -%}\n"
        "| **Разом** | {% for y in years -%}\n"
        "{%- set total = namespace(v=0) -%}\n"
        f"{{%- for key, label in {entries_json} -%}}\n"
        "{%- set yt = objs.get(key, {}).get('year_totals', []) -%}\n"
        "{%- set match = yt | selectattr('year', 'eq', y) | map(attribute='total') | list -%}\n"
        "{%- set total.v = total.v + (match[0] if match else 0) -%}\n"
        "{%- endfor -%}\n"
        "**{{ '%.0f' % total.v }}** | {% endfor %}\n\n"
        "грн нараховано за рік (борги/переплати вже враховані у сумі)"
    )
    return {"type": "markdown", "title": "Підсумок по роках", "content": content}


def year_link(year: str) -> dict:
    return {
        "type": "button", "name": year, "show_icon": False, "show_name": True, "show_state": False,
        "tap_action": {"action": "call-service", "service": "input_select.select_option",
                        "service_data": {"entity_id": "input_select.oselya_payments_year", "option": year}},
        "card_mod": {"style": (
            "ha-card { box-shadow: none; border: none; background: none; min-height: 28px; padding: 0; }\n"
            ".info { font-weight: bold; text-decoration: underline; }\n"
        )},
    }


def expand_toggle() -> list:
    """"Розгорнути"/"Згорнути" link for input_boolean.oselya_payments_expanded -
    two conditional buttons so the label always says what a tap will do.
    Styled like the year links. The helper is global (shared by every table
    and every device/user viewing the dashboard).
    """
    def button(name: str, when: str) -> dict:
        return {
            "type": "conditional",
            "conditions": [{"condition": "state", "entity": "input_boolean.oselya_payments_expanded", "state": when}],
            "card": {
                "type": "button", "name": name, "show_icon": False, "show_name": True, "show_state": False,
                "tap_action": {"action": "call-service", "service": "input_boolean.toggle",
                                "service_data": {"entity_id": "input_boolean.oselya_payments_expanded"}},
                "card_mod": {"style": (
                    "ha-card { box-shadow: none; border: none; background: none; min-height: 28px; padding: 0; }\n"
                    ".info { font-weight: bold; text-decoration: underline; }\n"
                )},
            },
        }
    return [button("▸ Розгорнути по платежах", "off"), button("▾ Згорнути до місяців", "on")]


def receipts_links_card() -> dict:
    """Currently-outstanding bills, each linked to its receipt PDF the same way
    the DAP energy table links ENERA acts: a signed, expiring /api/documents
    link from sensor.document_links, opened with target=_blank. (The old
    unauthenticated /local/ links are what got the iPhone Companion App's
    WebView stuck - see memory: oselya_payments_system.)
    """
    content = (
        "{%- set items = state_attr('sensor.oselya_payments', 'outstanding') or [] -%}\n"
        "{%- set docs = state_attr('sensor.document_links', 'oselya') or {} -%}\n"
        "{% for i in items -%}\n"
        "{%- set text = i.object ~ ' — ' ~ i.purpose ~ ' — ' ~ i.period ~ ' — ' ~ ('%.2f' % i.amount) ~ ' грн' -%}\n"
        "🧾 {% if docs.get(i.receipt) %}<a href=\"{{ docs[i.receipt] }}\" target=\"_blank\" rel=\"noopener\">{{ text }}</a>"
        "{% else %}{{ text }}{% endif %}\n"
        "{% endfor %}"
    )
    return {"type": "markdown", "title": "Квитанції", "content": content}


def build_todo_view() -> dict:
    return {
        "type": "sections", "max_columns": 2, "title": "До оплати", "path": "todo",
        "icon": "mdi:checkbox-marked-circle-outline",
        "sections": [{
            "type": "grid",
            "cards": [
                {"type": "heading", "heading": "Що оплатити", "heading_style": "title"},
                {"type": "todo-list", "entity": "todo.payments", "title": "Payments"},
                receipts_links_card(),
            ],
        }],
    }


DESKTOP = {"condition": "screen", "media_query": "(min-width: 768px)"}
MOBILE = {"condition": "screen", "media_query": "(max-width: 767px)"}


def object_cards(obj_key: str, obj_cfg: dict, mobile: bool) -> list:
    """Heading (with the object's icon) + its table. The heading is the only
    title - the markdown card itself has none, so the name isn't shown twice."""
    bills = [[k, b["label"]] for k, b in obj_cfg["bills"].items()]
    table = {"type": "markdown", "content": table_content(obj_key, bills, mobile=mobile),
             "card_mod": {"style": {"ha-markdown $": table_css(mobile)}}}
    return [
        {"type": "heading", "heading": obj_cfg["label"], "heading_style": "title",
         **({"icon": obj_cfg["icon"]} if obj_cfg.get("icon") else {})},
        table,
    ]


def build_view(objects_cfg: dict) -> dict:
    # Matches input_select.oselya_payments_year's options (packages/oselya_payments.yaml) -
    # update both places if a new year needs to show up.
    years = ["2025", "2026"]
    overview = [
        {"type": "heading", "heading": "Огляд", "heading_style": "title"},
        {"type": "horizontal-stack", "cards": [year_link(y) for y in years]},
        *expand_toggle(),
        summary_card(objects_cfg),
    ]
    # Desktop: a sections view lays sections out in rows, each as tall as its
    # tallest section - one section per object left a big gap under the short
    # overview next to Квартира 197's long table. So there are exactly two
    # sections (= the two columns), and each object goes to whichever column
    # is shorter so far. Height is estimated as 1 + number of bills (a month
    # plus its bill rows when expanded); the overview counts as 1.5.
    # objects.yaml order is kept within each column.
    columns = [[], []]
    heights = [1.5, 0.0]
    for obj_key, obj_cfg in sorted(objects_cfg.items(), key=lambda kv: -len(kv[1]["bills"])):
        i = heights.index(min(heights))
        columns[i].append(obj_key)
        heights[i] += 1 + len(obj_cfg["bills"])
    order = list(objects_cfg)
    sections = []
    for i, keys in enumerate(columns):
        cards = list(overview) if i == 0 else []
        for obj_key in sorted(keys, key=order.index):
            cards += object_cards(obj_key, objects_cfg[obj_key], mobile=False)
        sections.append({"type": "grid", "visibility": [DESKTOP], "cards": cards})
    # Mobile: one column, so the columns above would just stack - instead a
    # single section in plain objects.yaml order (apartments first).
    cards = list(overview)
    for obj_key, obj_cfg in objects_cfg.items():
        cards += object_cards(obj_key, obj_cfg, mobile=True)
    sections.append({"type": "grid", "visibility": [MOBILE], "cards": cards})
    return {
        # 2 (not 4) so each object's table card gets roughly half the screen
        # width - enough room for all columns without overflowing.
        "type": "sections", "max_columns": 2, "title": "Таблиці", "path": "tables",
        "icon": "mdi:table", "sections": sections,
    }


def build_rates_view() -> dict:
    """Fixed-rate (manual_fixed_rate) tariffs from rates.yaml, published as
    sensor.oselya_payments' `rates`, plus a form to change them: bill +
    amount + first month -> script.oselya_rate_save -> rates.py (the rules
    are in its docstring). The result line comes back in
    input_text.oselya_rate_status.
    """
    table = (
        "{%- set months = ['Січень', 'Лютий', 'Березень', 'Квітень', 'Травень', 'Червень', "
        "'Липень', 'Серпень', 'Вересень', 'Жовтень', 'Листопад', 'Грудень'] -%}\n"
        "{%- macro month(p) -%}{{ months[p[5:7] | int - 1] ~ ' ' ~ p[:4] if p else '—' }}{%- endmacro -%}\n"
        "| Об'єкт | Платіж | Сума, грн | Діє з | Діє до |\n|:--|:--|--:|:--|:--|\n"
        "{% for r in state_attr('sensor.oselya_payments', 'rates') or [] -%}\n"
        "| {{ r.object }} | {{ r.bill }} | {{ '%.2f' % r.rate }} | {{ month(r.valid_from) }} | {{ month(r.valid_to) }} |\n"
        "{% endfor %}\n"
        "Суми, яких немає звідки взяти автоматично. Оплату відмічай галочкою у списку «Payments». "
        "«—» у «Діє до» означає, що тариф чинний зараз."
    )
    help_text = (
        "Нова сума діє **з вказаного місяця**: попередній тариф закривається місяцем раніше, "
        "старі місяці лишаються зі старою сумою.\n\n"
        "- **0** — платіж припиняється з цього місяця.\n"
        "- **Минулий місяць** — виправляє суму вже створених місяців (позначки «оплачено» зберігаються).\n"
        "- **Скасувати останню зміну** — повертає тарифи до стану перед останнім збереженням "
        "(можна натискати кілька разів, пам'ятає 20 змін).\n"
        "- Новий *вид* платежу (не зміну суми) додає Claude в objects.yaml."
    )
    status = ("{%- set s = states('input_text.oselya_rate_status') -%}"
              "{{ s if s not in ['unknown', 'unavailable', ''] else '' }}")
    return {
        "type": "sections", "max_columns": 2, "title": "Тарифи", "path": "rates",
        "icon": "mdi:tag-text-outline",
        "sections": [
            {"type": "grid", "cards": [
                {"type": "heading", "heading": "Фіксовані тарифи", "heading_style": "title"},
                {"type": "markdown", "content": table},
            ]},
            {"type": "grid", "cards": [
                {"type": "heading", "heading": "Змінити тариф", "heading_style": "title",
                 "icon": "mdi:pencil"},
                # tap_action none: tapping a field's name would otherwise open
                # HA's more-info dialog with the helper's history graph.
                {"type": "entities", "entities": [
                    {"entity": e, "tap_action": {"action": "none"}}
                    for e in ("input_select.oselya_rate_bill", "input_number.oselya_rate_amount",
                              "input_datetime.oselya_rate_from")
                ]},
                {"type": "horizontal-stack", "cards": [
                    {"type": "button", "name": "Зберегти", "icon": "mdi:content-save",
                     "show_state": False, "icon_height": "32px",
                     "tap_action": {"action": "perform-action", "perform_action": "script.oselya_rate_save",
                                    "confirmation": {"text": "Зберегти новий тариф?"}}},
                    {"type": "button", "name": "Скасувати останню зміну", "icon": "mdi:undo",
                     "show_state": False, "icon_height": "32px",
                     "tap_action": {"action": "perform-action", "perform_action": "script.oselya_rate_undo",
                                    "confirmation": {"text": "Повернути тарифи до стану перед останнім збереженням?"}}},
                ]},
                {"type": "markdown", "content": status},
                {"type": "markdown", "content": help_text},
            ]},
        ],
    }


class HA:
    def __init__(self):
        self.ws = websocket.create_connection("ws://localhost:8123/api/websocket", timeout=10)
        msg = json.loads(self.ws.recv())
        assert msg["type"] == "auth_required", msg
        self.ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        msg = json.loads(self.ws.recv())
        assert msg["type"] == "auth_ok", msg
        self._id = 0

    def call(self, payload: dict) -> dict:
        self._id += 1
        payload["id"] = self._id
        self.ws.send(json.dumps(payload))
        return json.loads(self.ws.recv())


def main():
    objects_cfg = yaml.safe_load(OBJECTS_YAML.read_text())["objects"]
    ha = HA()
    msg = ha.call({"type": "lovelace/config", "url_path": DASHBOARD_URL_PATH})
    config = msg["result"]
    config["views"] = ([v for v in config["views"] if v.get("path") not in ("tables", "tables2", "todo", "rates")]
                        + [build_todo_view(), build_view(objects_cfg), build_rates_view()])
    msg = ha.call({"type": "lovelace/config/save", "url_path": DASHBOARD_URL_PATH, "config": config})
    assert msg.get("success"), msg
    print(f"rebuilt 'todo' + 'tables' + 'rates' views with {len(objects_cfg)} object(s)")


if __name__ == "__main__":
    main()
