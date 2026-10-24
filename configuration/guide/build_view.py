#!/usr/bin/env python3
"""Rebuild the "Guide" view of the Overview dashboard: how the power load
cascade, the Deye states and the Selling mode work (Ukrainian text, live
values via Jinja in markdown cards). The view is found by its path and
replaced in place, inserted before the "diagram" (Other) view the first time.

Numbers hard-coded in the text mirror packages/energy/power_cascade.yaml
(power_load_cascade_step) and packages/energy/deye_schedule.yaml
(deye_state_controller): update them together.

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

🟩 заряд 6kW · 🟧 бойлер · 🟦 експорт 5kW · 🟪 кондиціонери

- Кроки заряду 6kW працюють лише поки 6kW < 95 %.
- Поки 6kW у No Battery (нічний Standby, ще не прокинувся), кроки заряду 6kW пропускаються (вони тоді нічого не дають), а бойлер не вмикається через те, що 5kW заряджається на межі: цей лишок 5kW і так віддає в мережу. Бойлер тоді вмикається лише коли 5kW справді обрізає PV або немає мережі.
- ¹ Лише в станах продажу (коли межа експорту стану > 1000 W). В Idle не спрацьовує, у Save + Night Charge — поки 5kW не заряджена до 100 %.
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
| Morning Export | слайдер | smart limit | 5050 W | 40 % ⁴ / 0.9 kW |
| Max Solar | слайдер | 0.35 kW | 5080 W | 40 % ⁴ / 1 kW |
| Evening Export | слайдер | smart limit | 5000 W | ³ ⁴ |
| Idle | 35 | 1 kW | 100 W | 35 % / 1.3 kW |

- **min SOC** — до якого рівня батарея може *розряджатися*. Він не змушує батарею заряджатися: у режимі Export First Deye спершу продає PV і тільки залишок віддає в батарею.
- **Експорт** — максимум, який 5kW віддає в мережу. 100 W означає «не продавати», і тоді PV іде в батарею.
- **Слайдер** — *Deye 5kW export SOC* (зараз {{ states('input_number.deye_5kw_export_soc')|int(0) }} %). 100 = батарею не продаємо, але надлишок PV продається.
- **smart limit** — потужність розряду з `Deye 5kW Smart Discharge Limit`, не більше 2.4 kW.
- ³ 6kW продає батарею лише ввечері і лише коли ввімкнено *Deye 6kW battery selling*: тоді peak shaving вимикається, а 6kW розряджається до *Deye 6kW export SOC* (зараз {{ states('input_number.deye_6kw_export_soc')|int(0) }} %). Коли дійде до нього, продаж вимикається автоматично. Перемикач сам вмикається за хвилину до Evening Export, якщо зараз літній сезон ({{ state_attr('binary_sensor.summer_season', 'start') }} до {{ state_attr('binary_sensor.summer_season', 'stop') }} (*Summer season* на Home)) і завтра очікується > 70 % сонця. Без продажу peak shaving лишається ввімкненим і 6kW тільки живить дім (той самий min SOC, 1.1 kW).
- ⁴ Узимку (*Summer season* вимкнений) 6kW min SOC — *Deye 6kW export SOC* (зараз {{ states('input_number.deye_6kw_export_soc')|int(0) }} %) у всіх станах, крім Force і продажу батареї 6kW. Уночі (після заходу сонця, не раніше 16:00) інвертори по черзі йдуть у Standby (*battery operation mode* = No Battery) і не витрачають ~40–60 W кожен на себе: спершу 5kW — тоді 6kW без мережі живить дім від своєї батареї, без мигання; коли 6kW дійде до цього SOC (або велике навантаження, нічний заряд, буст, продаж батареї 5kW, мережа зникла), 5kW повертається, а за кілька хвилин у Standby іде 6kW, і дім живиться від 5kW (тільки коли в рядку *Deye 6kW standby* ввімкнено At night; без нього 6kW усю ніч працює сам). Перехід 6kW на ~30 с знеструмлює будинок, разом із Raspberry з HA; якщо Bizon спав, після ввімкнення його знову приспить. Уранці 6kW у No Battery сам вмикається від сонця (без мигання): PV живить дім, а лишок іде в 5kW — не працює тільки батарея 6kW. У Capacity (знову ~30 с без світла) він повертається лише тоді, коли PV 6kW (або 5kW) тримається ≥ *Deye 6kW wake PV* ({{ states('input_number.deye_6kw_wake_pv') }} kW) 10 хв і прогноз на решту дня сонячніший за *Deye 6kW wake sunny* ({{ states('input_number.deye_6kw_wake_sunny')|int(0) }} %, зараз {{ states('sensor.deye_6kw_sunny_today') }} %), тож у похмурий день перемикань немає зовсім. Без мережі він сам не прокидається (дім живиться від 5kW), але якщо при цьому PV ≥ wake PV 10 хв — прокидається без огляду на прогноз, щоб сонце йшло в його батарею. У ніч на 1-ше число (23:10–06:30) 6kW прокидається і заряджається з мережі до 100 %, а батарея 5kW на цей час не розряджається. Коли панелі 6kW засипані снігом, вмикай Snow у рядку *Deye 6kW standby*: 6kW тоді в Standby і вдень, від сонця не прокидається; як панелі очистяться — вимкни Snow. Кнопки 5kW / 6kW (жовта — Normal, синя — Standby) перемикають інвертор вручну з підтвердженням; ручний Standby автоматика не скасовує до 05:00 (крім мінімального SOC 6kW, навантаження 6kW понад 4 kW, зникнення мережі чи 6kW, що не працює). Усі перемикання видно в logbook як *Deye night standby*.
- Налаштування повторно застосовуються щогодини, тож ручна зміна цих значень протримається не більше години. Щоб змінити поведінку, міняй слайдери, час або Selling mode.

**Зараз:** {{ states('input_select.deye_system_state') }} · експорт {{ states('input_number.export_deye_5kw_power')|int(0) }} W · 5kW min SOC {{ states('input_number.deye_5kw_min_soc')|int(0) }} % · 6kW min SOC {{ states('input_number.deye_6kw_min_soc')|int(0) }} %
"""

MODES = """\
**Selling mode** визначає, *як* продаємо. Його перемикаєш вручну.

**Normal** — усе за розкладом зі стану.

**Force** — працює тільки в Morning Export і Max Solar. 5kW: SOC 40, розряд 0.35 kW, експорт 5080 W; 6kW: SOC 55, 1 kW. Каскад додатково скидає навантаження, коли 5kW заряджається повільніше за половину *surplus threshold*. Поза вікном {{ states('input_datetime.deye_morning_export_start_time')[:5] }}–{{ states('input_datetime.deye_evening_export_start_time')[:5] }} сам повертається в Normal.

**Save** — спершу заряджає 5kW з PV до **100 %**: експорт 100 W, увесь PV 5kW іде в батарею, а нижче 75 % її не розряджаємо. У Morning Export і Max Solar, щойно 5kW досягне 100 %, продається лише лишок PV (SOC 100, експорт стану), як у Save + Night Charge; назад на заряд, коли 5kW < 95 %. Увечері експорт 100 W. Можна вибрати за будь-якого SOC. Улітку (з {{ state_attr('binary_sensor.summer_season', 'start') }} до {{ state_attr('binary_sensor.summer_season', 'stop') }} (*Summer season* на Home)) на початку Morning Export сам повертається в Normal, узимку лишається. Узимку Save і Save + Night Charge щогодини ставлять заряд 6kW 1.5 kW, і каскад не опускає його нижче.

**Save + Night Charge** (для зими) — удень спершу заряджає 5kW з PV: експорт 100 W, 5kW SOC 40. У Morning Export і Max Solar, щойно 5kW досягне **100 %**, експорт повертається до значення стану, а SOC стає 100: продається лише лишок PV, сама батарея ні (назад на заряд, коли 5kW < 95 %). Peak shaving на 5kW для цього не працює після оновлення прошивки. Увечері й у Idle експорт 100 W, батарея живить дім. Уночі з 23:10 до 06:30 5kW заряджається з мережі до 100 % (~2.4 kW), і каскад на цей час вимикається, бо імпорт з мережі він сприйняв би як перевантаження. Автоматично не скидається.

**Зараз:** {{ states('input_select.selling_mode') }}{{ ' · 5kW заряджається з PV до 100 %, далі продаж лишку' if is_state('input_select.selling_mode','Save') else '' }}
"""

# Step table cells tinted by device, so the reversed Disable order is visible:
# (column, first row, last row, colour). Rows follow CASCADE_STEPS; keep in sync.
GREEN, ORANGE, BLUE, PURPLE = "76, 175, 80", "255, 152, 0", "33, 150, 243", "156, 39, 176"
STEP_GROUPS = [
    (2, 1, 3, GREEN), (2, 4, 6, ORANGE), (2, 7, 7, BLUE), (2, 8, 9, PURPLE),
    (3, 1, 1, BLUE), (3, 2, 4, ORANGE), (3, 5, 7, GREEN), (3, 8, 9, PURPLE),
]
STEPS_CSS = "table { border-collapse: collapse; }\n" + "\n".join(
    f"tbody tr:nth-child(n+{first}):nth-child(-n+{last}) td:nth-child({col}) "
    f"{{ background: rgba({rgb}, 0.2); }}"
    for col, first, last, rgb in STEP_GROUPS)

# Both STATES tables list the states in the same order, so row N = the same
# state in each; tint whole rows (Morning Export, Max Solar, Evening Export, Idle).
STATE_COLOURS = ["255, 193, 7", "255, 87, 34", "233, 30, 99", "63, 81, 181"]
STATES_CSS = "table { border-collapse: collapse; }\n" + "\n".join(
    f"tbody tr:nth-child({n}) td {{ background: rgba({rgb}, 0.2); }}"
    for n, rgb in enumerate(STATE_COLOURS, 1))


def section(heading, icon, md, span=1, css=None):
    card = {"type": "markdown", "content": md}
    if css:
        card["card_mod"] = {"style": {"ha-markdown $": css}}
    return {"type": "grid", "column_span": span, "cards": [
        {"type": "heading", "heading": heading, "heading_style": "title", "icon": icon},
        card,
    ]}


view = {
    "type": "sections",
    "max_columns": 2,
    "title": "Guide",
    "path": "guide",
    "sections": [
        section("Каскад навантаження", "mdi:stairs", CASCADE_HOW),
        section("Порядок кроків", "mdi:format-list-numbered", CASCADE_STEPS, css=STEPS_CSS),
        section("Стани Deye", "mdi:clock-outline", STATES, css=STATES_CSS),
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
