#!/usr/bin/env python3
"""Create/rebuild the "Librus" sidebar dashboard (dashboard-librus) from the
Librus Synergia Cards (MichalZaniewicz/ha-librus-synergia-cards, HACS
plugin) on top of the librus_synergia integration. Idempotent - re-run any
time; it replaces the whole dashboard config through the HA WebSocket API
(never .storage directly - see memory: homecontroll_dashboard_live_edit).

The cards find the child's device on their own (one student), so they need
no entity ids; the "Календар" tab looks its calendar entities up at run
time, so no child-identifying ids end up in git. Their labels follow each user's HA language (Polish or
English built in); subject names carry a Ukrainian translation from
librus/subjects_uk.json (see apply_local_patches.py).

Run: /home/yurii/docker/homeControll/configuration/statistics/oselya/.venv/bin/python build_dashboard.py
"""
import json
from pathlib import Path

import websocket

TOKEN = (Path.home() / ".ha_token").read_text().strip()
URL_PATH = "dashboard-librus"


def card(kind: str, **opts) -> dict:
    return {"type": f"custom:librus-{kind}", **opts}


def section(heading: str, icon: str, cards: list, span: int = 1) -> dict:
    return {"type": "grid", "column_span": span, "cards": [
        {"type": "heading", "heading": heading, "heading_style": "title", "icon": icon}, *cards]}


def view(title: str, path: str, icon: str, sections: list) -> dict:
    return {"type": "sections", "max_columns": 3, "title": title, "path": path, "icon": icon,
            "sections": sections}


VIEWS = [
    view("Сьогодні", "today", "mdi:calendar-today", [
        section("Сьогодні", "mdi:white-balance-sunny", [
            card("today-card"), card("next-lesson-tile-card"), card("today-lessons-card")]),
        section("Завтра", "mdi:calendar-arrow-right", [card("tomorrow-card")]),
        section("Що нового", "mdi:bell-ring", [
            card("exam-countdown-card", exam_keywords="sprawdzian, kartkówka, praca klasowa"),
            card("recent-activity-card", max_items=8), card("lucky-number-card")]),
    ]),
    view("Розклад", "timetable", "mdi:timetable", [
        section("Тиждень", "mdi:table-large", [card("week-timetable-card")], span=2),
        section("День", "mdi:clock-outline", [card("bell-schedule-card"), card("free-days-card")]),
    ]),
    view("Повідомлення", "messages", "mdi:email", [
        section("Повідомлення", "mdi:email-outline", [card("messages-card", max_items=15)], span=2),
        section("Оголошення і заміни", "mdi:bullhorn", [
            card("announcements-card"), card("substitutions-card")]),
    ]),
    view("Оцінки", "grades", "mdi:star-circle", [
        section("Описові оцінки", "mdi:text-box-check", [card("descriptive-grades-card")], span=2),
        section("Журнал і поведінка", "mdi:notebook", [
            card("latest-grade-card"), card("grade-log-card", max_items=20),
            card("behaviour-grade-card"), card("behaviour-notices-card")]),
    ]),
    view("Контрольні й домашні", "agenda", "mdi:clipboard-text-clock", [
        section("Терміни", "mdi:calendar-clock", [card("agenda-card", days_ahead=21)], span=2),
        section("Домашні завдання", "mdi:home-edit", [
            card("exam-countdown-card", exam_keywords="sprawdzian, kartkówka, praca klasowa"),
            card("homework-assignments-card")]),
    ]),
    view("Відвідування", "attendance", "mdi:account-check", [
        section("Відвідування", "mdi:account-check-outline", [
            card("attendance-card"), card("attendance-heatmap-card")], span=2),
        section("Пропуски", "mdi:chart-bar", [
            card("attendance-weekday-card"), card("attendance-subject-card"), card("streak-card")]),
    ]),
]


def calendar_view(calendars: list[str]) -> dict:
    """Week list (listWeek) over the integration's calendars (timetable, agenda, free
    days) - replaces the generic sidebar Calendar panel, which shows only
    these anyway."""
    return {"type": "panel", "title": "Календар", "path": "calendar", "icon": "mdi:calendar-month",
            "cards": [{"type": "calendar", "initial_view": "listWeek", "entities": calendars}]}


class HA:
    def __init__(self):
        self.ws = websocket.create_connection("ws://localhost:8123/api/websocket", timeout=10)
        assert json.loads(self.ws.recv())["type"] == "auth_required"
        self.ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        assert json.loads(self.ws.recv())["type"] == "auth_ok"
        self._id = 0

    def call(self, payload: dict) -> dict:
        self._id += 1
        payload["id"] = self._id
        self.ws.send(json.dumps(payload))
        return json.loads(self.ws.recv())


def main():
    ha = HA()
    dashboards = ha.call({"type": "lovelace/dashboards/list"})["result"]
    if not any(d["url_path"] == URL_PATH for d in dashboards):
        msg = ha.call({"type": "lovelace/dashboards/create", "url_path": URL_PATH, "title": "Librus",
                       "icon": "mdi:school", "show_in_sidebar": True, "require_admin": False, "mode": "storage"})
        assert msg.get("success"), msg
        print("created dashboard", URL_PATH)
    registry = ha.call({"type": "config/entity_registry/list"})["result"]
    calendars = sorted(e["entity_id"] for e in registry
                       if e["platform"] == "librus_synergia" and e["entity_id"].startswith("calendar."))
    assert calendars, "no librus_synergia calendars found"
    views = VIEWS[:2] + [calendar_view(calendars)] + VIEWS[2:]
    msg = ha.call({"type": "lovelace/config/save", "url_path": URL_PATH,
                   "config": {"title": "Librus", "views": views}})
    assert msg.get("success"), msg
    print(f"saved {len(views)} views: " + ", ".join(v["title"] for v in views))


if __name__ == "__main__":
    main()
