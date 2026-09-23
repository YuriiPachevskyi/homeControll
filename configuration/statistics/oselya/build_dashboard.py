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


def table_content(obj_key: str, mobile: bool) -> str:
    header = "| Період | До сплати | Статус |" if mobile else \
        "| Період | Нарах. | Опл. | Борг | До сплати | Статус |"
    sep = "|:--|--:|:--:|" if mobile else "|:--|--:|--:|--:|--:|:--:|"
    # Partial status names exactly which bill(s) are still unpaid - otherwise
    # 🟡 alone doesn't say what's missing.
    status_expr = ("{{ '✅' if r.status == 'paid' else "
                    "('🟡 ' + (r.unpaid_labels | join(', '))) if r.status == 'partial' "
                    "else '⏳' }}")
    # The year is shown once in the heading line below (it's already fixed by the
    # year-link buttons for the whole card), so the period column only needs the
    # month - and the totals row just says "Разом", not "Разом 2026".
    month_only = "r.label.split(' ')[0]"
    if mobile:
        row = f"| {{{{ {month_only} }}}} | {{{{ '%.2f' % r.total_due }}}} | {status_expr} |"
        total_row = "| **Разом** | **{{ '%.2f' % (rows | sum(attribute='total_due')) }}** | |"
    else:
        row = (f"| {{{{ {month_only} }}}} | {{{{ '%.2f' % r.accrued }}}} | {{{{ '%.2f' % r.paid }}}} | "
               f"{{{{ '%.2f' % r.debt }}}} | {{{{ '%.2f' % r.total_due }}}} | {status_expr} |")
        # Summing "Борг"/"До сплати" across months is meaningless (they're running
        # balances, not period amounts) - the totals row only fills Нарах./Опл.
        total_row = ("| **Разом** | **{{ '%.2f' % (rows | sum(attribute='accrued')) }}** | "
                      "**{{ '%.2f' % (rows | sum(attribute='paid')) }}** | | | |")
    return (
        "{%- set y = states('input_select.oselya_payments_year') -%}\n"
        f"{{%- set objs = state_attr('sensor.oselya_payments', 'objects') or {{}} -%}}\n"
        f"{{%- set rows = objs.get('{obj_key}', {{}}).get('rows', []) "
        "| selectattr('period', 'match', '^' + y) | list -%}\n"
        "**{{ y }} рік**\n\n"
        f"{header}\n{sep}\n"
        "{% for r in rows -%}\n"
        f"{row}\n"
        "{% endfor -%}\n"
        f"{total_row}\n\n"
        "грн · ✅ оплачено · 🟡 частково · ⏳ очікує оплати"
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


def receipts_links_card() -> dict:
    """Read-only list of currently-outstanding bills - NOT tappable/linked.
    Every HTML-level attempt to make the PDF link behave safely on iPhone
    (target=_blank, no target, `download`) either did nothing or - twice -
    got the HA Companion App's WebView stuck with no way back. Plain text
    until this gets revisited on a laptop, away from the phone entirely.
    """
    content = (
        "{%- set items = state_attr('sensor.oselya_payments', 'outstanding') or [] -%}\n"
        "{% for i in items -%}\n"
        "🧾 {{ i.object }} — {{ i.purpose }} — {{ i.period }} — {{ '%.2f' % i.amount }} грн\n"
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


def build_view(objects_cfg: dict) -> dict:
    # Matches input_select.oselya_payments_year's options (packages/oselya_payments.yaml) -
    # update both places if a new year needs to show up.
    years = ["2025", "2026"]
    sections = [{
        "type": "grid",
        "cards": [
            {"type": "heading", "heading": "Огляд", "heading_style": "title"},
            {"type": "horizontal-stack", "cards": [year_link(y) for y in years]},
            summary_card(objects_cfg),
        ],
    }]
    for obj_key, obj_cfg in objects_cfg.items():
        sections.append({
            "type": "grid",
            "cards": [
                {"type": "heading", "heading": obj_cfg["label"], "heading_style": "title"},
                {"type": "conditional", "conditions": [{"condition": "screen", "media_query": "(min-width: 768px)"}],
                 "card": {"type": "markdown", "title": obj_cfg["label"],
                          "content": table_content(obj_key, mobile=False)}},
                {"type": "conditional", "conditions": [{"condition": "screen", "media_query": "(max-width: 767px)"}],
                 "card": {"type": "markdown", "title": obj_cfg["label"],
                          "content": table_content(obj_key, mobile=True),
                          "card_mod": {"style": {"ha-markdown $": (
                              "table { width: 100%; font-size: 12px; }\n"
                              "th, td { padding: 2px 4px !important; }\n")}}}},
            ],
        })
    return {
        # 2 (not 4) so each object's table card gets roughly half the screen
        # width - enough room for all 6 columns without overflowing.
        "type": "sections", "max_columns": 2, "title": "Таблиці", "path": "tables",
        "icon": "mdi:table", "sections": sections,
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
    config["views"] = ([v for v in config["views"] if v.get("path") not in ("tables", "todo")]
                        + [build_todo_view(), build_view(objects_cfg)])
    msg = ha.call({"type": "lovelace/config/save", "url_path": DASHBOARD_URL_PATH, "config": config})
    assert msg.get("success"), msg
    print(f"rebuilt 'todo' + 'tables' views with {len(objects_cfg)} object(s)")


if __name__ == "__main__":
    main()
