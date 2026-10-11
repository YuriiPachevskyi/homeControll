#!/usr/bin/env python3
"""Rebuild the "Guide" view of the Overview dashboard: how the power load
cascade, the Deye states and the Selling mode work (Ukrainian text, live
values via Jinja in markdown cards). The view is found by its path and
replaced in place, inserted before the "diagram" (Other) view the first time.

Numbers hard-coded in the text mirror scripts.yaml (power_load_cascade_step)
and automations.yaml (deye_state_controller): update them together.

Edits go through the HA WebSocket API, never .storage directly. Idempotent.
Run: ../statistics/oselya/.venv/bin/python build_view.py
"""
import json
from pathlib import Path

import websocket

TOKEN = (Path.home() / ".secrets" / "ha_token").read_text().strip()
VIEW_PATH, BEFORE = "guide", "diagram"
CASCADE_HOW = """\
Кожен запуск робить **один крок**: або додає навантаження (**Enable**), коли є надлишок PV, або знімає його (**Disable**), коли батарея чи мережа перевантажені.

**Коли крок:** звичайний такт — кожні 30 с. Нове перевантаження або надлишок, що тримається 5 с, запускає крок одразу. Поки стан триває, наступні кроки йдуть кожні 15 с, але не раніше ніж через 15 с після попередньої зміни (Deye оновлюється кожні 5 с, тож наступний крок уже бачить ефект попереднього).

**Перевантаження** (`Any device high power`), якщо будь-що з цього більше за *High load threshold* (зараз **{{ (states('input_number.deye_load_off_power_threshold')|float(0)*1000)|int }} W**):
- імпорт 5kW з мережі
- розряд батареї 5kW або 6kW
- у режимі **Force**: також коли 5kW заряджається повільніше за половину *surplus threshold*

**Надлишок PV**, якщо будь-що з цього:
- 5kW заряджається сильніше за *Deye 5kW surplus power threshold* (зараз **{{ states('input_number.deye_5kw_surplus_power_threshold') }} kW**) або 6kW віддає стільки ж у 5kW
- PV1 5kW нижче 95 % від PV1 6kW (5kW обрізає панелі, бо енергію нікуди дівати)
- для бойлера ще: мережі немає, а 6kW швидко заряджається

**Зараз:** {{ 'перевантаження' if is_state('binary_sensor.any_device_high_power','on') else 'надлишок' if is_state('binary_sensor.battery_charge_and_export_power_limit','on') or is_state('binary_sensor.pv1_5kw_lower_than_6kw','on') else 'рівновага' }} · каскад {{ 'увімкнений' if is_state('automation.power_load_cascade','on') else '**вимкнений**' }}
Останній запис у логу: *{{ states('input_text.last_script_trigger') }}*
"""

CASCADE_STEPS = """\
Enable іде зверху вниз, Disable — у зворотному порядку. Береться перший крок, умови якого виконуються.

| # | Enable (надлишок) | Disable (перевантаження) |
|---|---|---|
| 1 | Заряд 6kW 0.75 kW | Експорт 5kW → значення стану |
| 2 | Заряд 6kW 1.5 kW | Бойлер 2.0 → 1.2 |
| 3 | Заряд 6kW 2.25 kW | Бойлер 1.2 → 0.8 |
| 4 | Бойлер 0.8 kW | Бойлер 0.8 OFF |
| 5 | Бойлер 1.2 kW (замість 0.8) | Заряд 6kW → 1.5 |
| 6 | Бойлер 2.0 kW (1.2 + 0.8) | Заряд 6kW → 0.75 |
| 7 | Експорт 5kW 5.5 kW ¹ | Заряд 6kW → 0 |
| 8 | Кондиціонер Bedroom ² | Big Bedroom OFF (6kW ≤ 70 %) |
| 9 | Кондиціонер Big Bedroom ² | Bedroom OFF (6kW ≤ 50 %) |

- Кроки заряду 6kW працюють лише поки 6kW < 95 %.
- ¹ Лише в станах продажу (коли межа експорту стану > 1000 W). В Idle і Night Charge не спрацьовує.
- ² Лише коли 6kW заряджена на 100 % і для кондиціонера на вкладці Climate вибрано режим (не *off*). Вимикаються останніми й тільки при низькому заряді 6kW: комфорт важливіший за продаж.
- Вручну ввімкнений бойлер чи кондиціонер каскад теж може вимкнути при перевантаженні.
"""

STATES = """\
**Стан** визначає, *коли* і скільки продаємо. Його ставить розклад:

| Стан | З | До |
|---|---|---|
| Morning Export | {{ states('input_datetime.deye_morning_export_start_time')[:5] }} | {{ states('input_datetime.deye_max_solar_start_time')[:5] }} |
| Max Solar | {{ states('input_datetime.deye_max_solar_start_time')[:5] }} | {{ states('input_datetime.deye_evening_export_start_time')[:5] }} |
| Evening Export | {{ states('input_datetime.deye_evening_export_start_time')[:5] }} | {{ states('input_datetime.deye_night_idle_start_time')[:5] }} |
| Idle | {{ states('input_datetime.deye_night_idle_start_time')[:5] }} | {{ states('input_datetime.deye_morning_export_start_time')[:5] }} |

Що виставляється в кожному стані:

| Стан | 5kW min SOC | 5kW розряд | Експорт 5kW | 6kW min SOC / розряд |
|---|---|---|---|---|
| Morning Export | слайдер | smart limit | 5050 W | 40 % / 0.9 kW |
| Max Solar | слайдер | 0.35 kW | 5080 W | 40 % / 1 kW |
| Evening Export | слайдер | smart limit | 5000 W | ³ |
| Idle | 35 | 1 kW | 100 W | 35 % / 1.3 kW |

- **min SOC** — до якого рівня батарея може *розряджатися*. Він не змушує батарею заряджатися: у режимі Export First Deye спершу продає PV і тільки залишок віддає в батарею.
- **Експорт** — максимум, який 5kW віддає в мережу. 100 W означає «не продавати», і тоді PV іде в батарею.
- **Слайдер** — *Deye 5kW export SOC* (зараз {{ states('input_number.deye_5kw_export_soc')|int(0) }} %). 100 = батарею не продаємо, але надлишок PV продається.
- **smart limit** — потужність розряду з `Deye 5kW Smart Discharge Limit`, не більше 2.4 kW.
- ³ 6kW продає батарею лише ввечері і лише коли ввімкнено *Deye 6kW battery selling*: тоді peak shaving вимикається, а 6kW розряджається до *Deye 6kW export SOC* (зараз {{ states('input_number.deye_6kw_export_soc')|int(0) }} %). Коли дійде до нього, продаж вимикається автоматично. Перемикач сам вмикається за хвилину до Evening Export, якщо завтра в березні–вересні очікується > 70 % сонця. Без продажу peak shaving лишається ввімкненим і 6kW тільки живить дім (той самий min SOC, 1.1 kW).
- Налаштування повторно застосовуються щогодини, тож ручна зміна цих значень протримається не більше години. Щоб змінити поведінку, міняй слайдери, час або Selling mode.

**Зараз:** {{ states('input_select.deye_system_state') }} · експорт {{ states('input_number.export_deye_5kw_power')|int(0) }} W · 5kW min SOC {{ states('input_number.deye_5kw_min_soc')|int(0) }} % · 6kW min SOC {{ states('input_number.deye_6kw_min_soc')|int(0) }} %
"""

MODES = """\
**Selling mode** визначає, *як* продаємо. Його перемикаєш вручну.

**Normal** — усе за розкладом зі стану.

**Force** — працює тільки в Morning Export і Max Solar. 5kW: SOC 40, розряд 0.35 kW, експорт 5080 W; 6kW: SOC 55, 1 kW. Каскад додатково скидає навантаження, коли 5kW заряджається повільніше за половину *surplus threshold*. Поза вікном {{ states('input_datetime.deye_morning_export_start_time')[:5] }}–{{ states('input_datetime.deye_evening_export_start_time')[:5] }} сам повертається в Normal.

**Save** — спершу заряджає 5kW з PV до **75 %**: поки батарея нижча, експорт 100 W. Після цього звичайний продаж надлишку, а батарею 5kW не розряджаємо нижче 75 %. У березні–жовтні на початку Morning Export сам повертається в Normal, узимку лишається.

**Night Charge** (зима) — удень нічого не продається (експорт 100 W, усе PV іде в батареї), 5kW SOC 40. Уночі з 23:10 до 06:30 5kW заряджається з мережі до 100 % (~2.4 kW), і каскад на цей час вимикається, бо імпорт з мережі він сприйняв би як перевантаження. Автоматично не скидається.

**Зараз:** {{ states('input_select.selling_mode') }}{{ ' · 5kW заряджається з PV до 75 %' if is_state('input_select.selling_mode','Save') and states('sensor.deye_5kw_battery')|float(0) < 75 else '' }}
"""


def section(heading, icon, md, span=1):
    return {"type": "grid", "column_span": span, "cards": [
        {"type": "heading", "heading": heading, "heading_style": "title", "icon": icon},
        {"type": "markdown", "content": md},
    ]}


view = {
    "type": "sections",
    "max_columns": 2,
    "title": "Guide",
    "path": "guide",
    "sections": [
        section("Каскад навантаження", "mdi:stairs", CASCADE_HOW),
        section("Порядок кроків", "mdi:format-list-numbered", CASCADE_STEPS),
        section("Стани Deye", "mdi:clock-outline", STATES),
        section("Selling mode", "mdi:cash-sync", MODES),
    ],
}
def main():
    ws = websocket.create_connection("ws://localhost:8123/api/websocket", timeout=10)
    assert json.loads(ws.recv())["type"] == "auth_required"
    ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
    assert json.loads(ws.recv())["type"] == "auth_ok"

    def call(n, payload):
        ws.send(json.dumps({"id": n, **payload}))
        msg = json.loads(ws.recv())
        assert msg["success"], msg
        return msg["result"]

    config = call(1, {"type": "lovelace/config"})
    views = [v for v in config["views"] if v.get("path") != VIEW_PATH]
    i = next((n for n, v in enumerate(views) if v.get("path") == BEFORE), len(views))
    views.insert(i, view)
    config["views"] = views
    call(2, {"type": "lovelace/config/save", "config": config})
    print("saved:", [v.get("title") for v in views])


if __name__ == "__main__":
    main()
