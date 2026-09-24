#!/usr/bin/env python3
"""Re-apply homeControll's local patches to the HACS-installed Librus
integration (custom_components/librus_synergia, MichalZaniewicz/
ha-librus-synergia). A HACS update overwrites them - run this again after
every update, then restart Home Assistant:

    python3 /home/yurii/docker/homeControll/configuration/librus/apply_local_patches.py

1. School time zone: lesson times from Librus are Polish wall-clock times,
   but the integration stamps them with HA's own time zone (Europe/Kyiv
   here), which shifts "now"/current-lesson logic by an hour and shows
   lessons an hour early in a browser in Poland. They get Europe/Warsaw
   instead (still converted to HA's zone by dt_util.as_local, so the instant
   is right everywhere; the cards then show browser-local time).
2. Subject names: "<Polish> (<Ukrainian>)" from librus/subjects_uk.json,
   applied where the integration builds its subject id -> name map, so the
   translation shows up in every sensor, the calendars and the cards.
3. Descriptive grades (the only grades an early-school class gets):
   show the real grade from the API's `Map` field ("5p", "6p", "3p") plus
   the skill's name ("5p · Sprawności motoryczne") instead of the raw
   `Grade` field, which is only a category index (3 for both 5p and 6p) -
   upstream never saw this endpoint populated. Skill names come from
   `DescriptiveGrades/Skills`, fetched alongside. The sensor's `recent`
   list keeps up to 50 grades instead of 5, so the card shows them all.
4. Minute tick: next lesson / current lesson / next exam work out "now"
   only when their state is written, i.e. after a Librus refresh. Librus
   is now polled just 3 times a day (see automation
   librus_scheduled_refresh - an hourly-plus poll got the HA server's IP
   blocked), so these three sensors re-write their state every minute from
   the data already loaded - no Librus request involved.
5. Fallback route: on 2026-09-24 every librus.pl host started silently
   dropping traffic from Ukrainian IPs (the HA server's and two other
   hosts' on different ISPs). Before each refresh a plain TCP connect to
   synergia.librus.pl:443 (no HTTP, 8 s) decides the route: if it works,
   Librus is reached directly; if not, the integration's aiohttp session
   goes through tinyproxy on raspberrypi5 (Poland) over Tailscale - that
   proxy only accepts this server and only CONNECTs to *.librus.pl:443
   (/etc/tinyproxy on raspberrypi5). The chosen route sticks until the next
   refresh (the cards' message requests use it too); a change is logged.
6. Data cache and request diet (keep showing the last data, never hammer
   Librus): every successful refresh is pickled to
   /config/.storage/librus_cache_<entry id>.pickle (.storage is not in git -
   it holds the child's data), together with the reference data and the
   weekly store below. A failed refresh keeps the previous data instead of
   making every entity unavailable (a failed login - wrong password - still
   raises so HA asks for reauth). After an HA restart the first refresh just
   loads that file when it is younger than 24 h - no Librus request at all.
   Setup no longer logs in up front (upstream did when the stored session
   looked stale) - the first real refresh logs in if needed, after patch 5
   has picked the route.
   Everything the sensors show is read on every scheduled refresh (3x a
   day). Only near-static data is kept longer: attendance types and the
   reference data (subjects, teachers, classrooms, free days, ...;
   upstream: daily) are refetched weekly, after Sunday 18:30 Kyiv (the
   Sunday evening run). Timetable weeks and attendances count as fresh
   until the next refresh slot (07:30 / 13:30 / 18:30 Kyiv), so a calendar
   left open (it re-asks every few minutes, day and night) costs at most
   one request per viewed week per slot; a failed lookup is not retried
   for 15 min.
   Requests go one at a time (upstream sent up to 9 in parallel, each a new
   connection through the proxy) so they reuse one connection, each after a
   random 2-6 s pause (a full refresh takes about 2 minutes), and every
   request (login included - upstream sent
   aiohttp's own User-Agent there) carries the browser User-Agent and a
   Polish Accept-Language. Together with the random ±20 min schedule and
   weekends' single evening refresh (packages/librus.yaml) it looks like a
   parent checking the diary, not a poller.
   Each refresh fires a `librus_route` event (route: direct / rpi5) after
   patch 5 has chosen; packages/librus.yaml sends Telegram when it changes.
   A successful refresh fires `librus_refreshed` - packages/librus.yaml
   alerts on Telegram when none came for over 30 h (stale cached data).
7. School date: "today" (today's lessons, tomorrow, is_today, the week
   whose timetable to fetch, streaks, ...) is the calendar date in Poland,
   not in HA's Kyiv zone - between 00:00 and 01:00 Kyiv it is still the
   previous day in Poland, and upstream switched to the next school day an
   hour early. Every `dt_util.now().date()` becomes Warsaw's date. Instants
   (minutes until/left, "now") need no change - they compare aware times.
8. Cards (www/community/ha-librus-synergia-cards, the HACS plugin): the
   next-lesson tile and the Today card read the timetable calendar's
   `start_time` attribute, which HA writes as a zone-less "YYYY-MM-DD
   HH:MM:SS" in the SERVER's zone (Kyiv), and parse it as the BROWSER's
   local time - in Poland the tile said 13:55 and "in 1h 13m" for a lesson
   12:55 Polish time, 13 min away. It is now read in HA's zone
   (hass.config.time_zone) and shown in the browser's. The .gz copy HA
   serves is rebuilt; the resource URL gets a cache-busting "&hc=" suffix.

Idempotent (each patch carries a marker). If upstream code changed so an
expected line is missing, it stops with an error instead of guessing.
"""
import sys
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1]
INTEGRATION = CONFIG / "custom_components" / "librus_synergia"
MARKER = "homeControll local patch"

TZ_IMPORT_ANCHOR = "from homeassistant.util import dt as dt_util\n"
TZ_IMPORT = (TZ_IMPORT_ANCHOR
             + f"from zoneinfo import ZoneInfo as _ZoneInfo  # {MARKER}: school time zone\n"
             + "_SCHOOL_TZ = _ZoneInfo(\"Europe/Warsaw\")\n")

TZ_PATCHES = {
    "calendar.py": [
        ("dt_util.as_local(datetime.combine(day, start_time))",
         "dt_util.as_local(datetime.combine(day, start_time, tzinfo=_SCHOOL_TZ))"),
        ("dt_util.as_local(datetime.combine(day, end_time))",
         "dt_util.as_local(datetime.combine(day, end_time, tzinfo=_SCHOOL_TZ))"),
    ],
    "sensor.py": [
        ("dt_util.as_local(datetime.combine(day, start_t))",
         "dt_util.as_local(datetime.combine(day, start_t, tzinfo=_SCHOOL_TZ))"),
        ("dt_util.as_local(datetime.combine(day, end_t))",
         "dt_util.as_local(datetime.combine(day, end_t, tzinfo=_SCHOOL_TZ))"),
    ],
}

SUBJECTS_LINE = '        self._cached_subjects = _parse_id_name_map(subjects_payload, ("Subjects",))\n'
SUBJECTS_PATCH = SUBJECTS_LINE + f"        self._cached_subjects = _translate_subjects(self._cached_subjects)  # {MARKER}\n"
SUBJECTS_FUNC = f'''

# --- {MARKER}: Ukrainian subject names (librus/apply_local_patches.py) ---
def _load_subjects_uk() -> dict:
    import json as _json
    from pathlib import Path as _Path
    try:
        path = _Path(__file__).resolve().parents[2] / "librus" / "subjects_uk.json"
        return _json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {{}}


# Read once at import (HA imports custom integrations in an executor thread,
# so this doesn't block the event loop); edits need an HA restart.
_SUBJECTS_UK = _load_subjects_uk()


def _translate_subjects(names: dict) -> dict:
    return {{k: f"{{v}} ({{_SUBJECTS_UK[v]}})" if v in _SUBJECTS_UK else v for k, v in names.items()}}
'''


# name -> (marker that says it's done, [(old, new), ...])
GRADE_PATCHES = {
    "librus_api/client.py": (f"{MARKER}: skill names", [(
        "        return await self._async_request(ENDPOINT_DESCRIPTIVE_GRADES)\n",
        "        payload = await self._async_request(ENDPOINT_DESCRIPTIVE_GRADES)\n"
        f"        # {MARKER}: skill names from DescriptiveGrades/Skills on each grade\n"
        "        try:\n"
        "            skills = await self._async_request(\"DescriptiveGrades/Skills\")\n"
        "            names = {k.get(\"Id\"): k.get(\"Name\") for k in skills.get(\"Skills\", []) if isinstance(k, dict)}\n"
        "            for grade in payload.get(\"Grades\", []) if isinstance(payload, dict) else []:\n"
        "                skill = grade.get(\"Skill\") if isinstance(grade, dict) else None\n"
        "                if isinstance(skill, dict) and names.get(skill.get(\"Id\")):\n"
        "                    skill[\"Name\"] = names[skill[\"Id\"]]\n"
        "        except Exception:  # noqa: BLE001 - optional extra; never break the grades fetch\n"
        "            pass  # grades still work, just without skill names\n"
        "        return payload\n",
    )]),
    "coordinator.py": (f"{MARKER}: real grade", [(
        '                value=item.get("Grade", ""),\n',
        f'                # {MARKER}: real grade ("5p") + skill name, not the category index\n'
        '                value=" · ".join(str(x) for x in (\n'
        '                    item.get("Map") or item.get("RealGradeValue") or item.get("Grade", ""),\n'
        '                    skill.get("Name")) if x),\n',
    )]),
    "sensor.py": (f"{MARKER}: was 5", [(
        "            (g for g in self.coordinator.data.descriptive_grades if g.add_date),\n"
        "            key=lambda g: g.add_date,\n            reverse=True,\n        )[:5]\n",
        "            (g for g in self.coordinator.data.descriptive_grades if g.add_date),\n"
        f"            key=lambda g: g.add_date,\n            reverse=True,\n        )[:50]  # {MARKER}: was 5\n",
    )]),
}


def patch_grades() -> None:
    """Patch 3, with per-file markers of its own - sensor.py and
    coordinator.py already carry MARKER from patches 1-2."""
    for name, (marker, edits) in GRADE_PATCHES.items():
        path = INTEGRATION / name
        text = path.read_text(encoding="utf-8")
        if marker in text:
            print(f"{name}: grades already patched")
            continue
        for old, new in edits:
            if text.count(old) != 1:
                sys.exit(f"{name}: expected exactly one {old!r} - upstream changed, patch not applied")
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")
        print(f"{name}: grades patched")


TICK_MARKER = f"{MARKER}: minute tick"
TICK_MIXIN = (
    "_SCHOOL_TZ = _ZoneInfo(\"Europe/Warsaw\")\n"
    "\n\n"
    f"class _MinuteTick:  # {TICK_MARKER}\n"
    "    \"\"\"Re-write the state every minute from cached data (no Librus request).\"\"\"\n"
    "\n"
    "    async def async_added_to_hass(self) -> None:\n"
    "        from datetime import timedelta as _timedelta\n"
    "        from homeassistant.helpers.event import async_track_time_interval\n"
    "        await super().async_added_to_hass()\n"
    "        self.async_on_remove(async_track_time_interval(self.hass, self._minute_tick, _timedelta(minutes=1)))\n"
    "\n"
    "    @callback\n"
    "    def _minute_tick(self, _now) -> None:\n"
    "        self.async_write_ha_state()\n"
)
TICK_EDITS = [
    ("_SCHOOL_TZ = _ZoneInfo(\"Europe/Warsaw\")\n", TICK_MIXIN),
    ("from homeassistant.core import HomeAssistant\n", "from homeassistant.core import HomeAssistant, callback\n"),
    ("class LibrusNextLessonSensor(LibrusSensorBase):", "class LibrusNextLessonSensor(_MinuteTick, LibrusSensorBase):"),
    ("class LibrusCurrentLessonSensor(LibrusSensorBase):", "class LibrusCurrentLessonSensor(_MinuteTick, LibrusSensorBase):"),
    ("class LibrusNextExamSensor(LibrusSensorBase):", "class LibrusNextExamSensor(_MinuteTick, LibrusSensorBase):"),
]


def patch_tick() -> None:
    """Patch 4 - needs patch 1's _SCHOOL_TZ line as its anchor."""
    path = INTEGRATION / "sensor.py"
    text = path.read_text(encoding="utf-8")
    if TICK_MARKER in text:
        print("sensor.py: minute tick already patched")
        return
    for old, new in TICK_EDITS:
        if text.count(old) != 1:
            sys.exit(f"sensor.py: expected exactly one {old!r} - upstream changed, patch not applied")
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    print("sensor.py: minute tick patched")


ROUTE_MARKER = f"{MARKER}: fallback route"
ROUTE_ANCHOR = ("        if self.data is not None and self._in_quiet_hours():\n"
                "            return self.data\n")
ROUTE_CALL = ROUTE_ANCHOR + f"        await _choose_route(self._client)  # {ROUTE_MARKER}\n"
ROUTE_FUNC = f'''

# --- {ROUTE_MARKER} (librus/apply_local_patches.py, patch 5) ---
_FALLBACK_PROXY = "http://100.102.244.45:8888"  # tinyproxy on raspberrypi5 (PL), Tailscale-only


async def _choose_route(client) -> None:
    """Direct if synergia.librus.pl:443 accepts a TCP connection, otherwise
    the session's default proxy is the raspberrypi5 fallback."""
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection("synergia.librus.pl", 443), 8)
        writer.close()
        proxy = None
    except (OSError, asyncio.TimeoutError):
        proxy = _FALLBACK_PROXY
    session = client._session
    if getattr(session, "_default_proxy", None) != proxy:
        _LOGGER.warning("Librus route: %s", f"via {{proxy}}" if proxy else "direct")
    session._default_proxy = proxy
'''


def patch_route() -> None:
    """Patch 5 - see the module docstring."""
    path = INTEGRATION / "coordinator.py"
    text = path.read_text(encoding="utf-8")
    if ROUTE_MARKER in text:
        print("coordinator.py: fallback route already patched")
        return
    if text.count(ROUTE_ANCHOR) != 1:
        sys.exit("coordinator.py: quiet-hours check not found - upstream changed, patch not applied")
    path.write_text(text.replace(ROUTE_ANCHOR, ROUTE_CALL) + ROUTE_FUNC, encoding="utf-8")
    print("coordinator.py: fallback route patched")


CACHE_MARKER = f"{MARKER}: data cache"
CACHE_DEF = "    async def _async_update_data(self) -> LibrusData:\n"
CACHE_RENAMED = f"    async def _async_update_data_upstream(self) -> LibrusData:  # {CACHE_MARKER}\n"
CACHE_VERSION = "cache-v8"  # bump when CACHE_FUNC changes: re-applies the block in place
CACHE_FUNC = f"""

# --- {CACHE_MARKER} (librus/apply_local_patches.py, patch 6, {CACHE_VERSION}) ---
_CACHE_MAX_AGE_ON_START = timedelta(hours=24)
# Coordinator state kept across restarts so a restart never refetches it.
_CACHE_EXTRA_ATTRS = (
    "_reference_data_fetched_at", "_cached_subjects", "_cached_teachers", "_cached_classrooms",
    "_cached_lesson_subjects", "_cached_school", "_cached_class", "_cached_homework_categories",
    "_cached_free_days", "_cached_note_categories", "_cached_behaviour_grade_categories",
    "_cached_lucky_number", "_lucky_number_fetched_date",
)


def _hc_week_boundary():
    \"\"\"The most recent Sunday 18:30 (HA local time) - weekly data fetched
    before it is stale. The Sunday evening scheduled refresh (18:40-19:20
    Kyiv) is the first one after it.\"\"\"
    now = dt_util.now()
    boundary = (now - timedelta(days=(now.weekday() - 6) % 7)).replace(hour=18, minute=30, second=0, microsecond=0)
    return boundary if boundary <= now else boundary - timedelta(days=7)


def _hc_daily_boundary(hour: int, minute: int):
    \"\"\"The most recent HH:MM (HA local time) - data fetched before it is stale.\"\"\"
    now = dt_util.now()
    boundary = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return boundary if boundary <= now else boundary - timedelta(days=1)


def _hc_this_refresh():
    # The latest refresh slot start (07:30 / 13:30 / 18:30 Kyiv - each
    # scheduled refresh runs 10-50 min after one): every scheduled refresh
    # reads the data again, while calendar lookups in between (an open tab
    # re-asks every few minutes, day and night) reuse it - at most one
    # request per week viewed per slot.
    return max(_hc_daily_boundary(h, 30) for h in (7, 13, 18))


def _hc_evening():  # the 18:40-19:20 Kyiv scheduled refresh is the first one after it
    return _hc_daily_boundary(18, 30)


async def _hc_weekly(client, key, fetch, boundary=_hc_week_boundary):
    \"\"\"Serve `key` from the client's store unless it is missing or was
    fetched before `boundary()` (default: the last Sunday evening).\"\"\"
    store = client.__dict__.setdefault("_hc_weekly", {{}})
    hit = store.get(key)
    if hit is not None and hit[0] >= boundary():
        return hit[1]
    failed = client.__dict__.setdefault("_hc_failed", {{}}).get(key)
    if failed is not None and dt_util.now() - failed[0] < timedelta(minutes=15):
        raise failed[1]  # don't retry a failed lookup on every calendar re-ask
    try:
        payload = await fetch()
    except Exception as err:
        client._hc_failed[key] = (dt_util.now(), err)
        raise
    client._hc_failed.pop(key, None)
    store[key] = (dt_util.now(), payload)
    old = dt_util.now() - timedelta(weeks=8)
    for k in [k for k, v in store.items() if v[0] < old]:
        del store[k]
    return payload


_hc_orig_attendances = LibrusApiClient.async_get_attendances
_hc_orig_attendance_types = LibrusApiClient.async_get_attendance_types
_hc_orig_timetable = LibrusApiClient.async_get_timetable
_hc_orig_request_url = LibrusApiClient._async_request_url


async def _hc_attendances(self):
    return await _hc_weekly(self, "attendances", lambda: _hc_orig_attendances(self), _hc_this_refresh)


async def _hc_attendance_types(self):
    return await _hc_weekly(self, "attendance_types", lambda: _hc_orig_attendance_types(self))


async def _hc_timetable(self, week_start):
    # also serves the calendar entities' on-demand week lookups
    return await _hc_weekly(self, ("timetable", week_start.isoformat()),
                            lambda: _hc_orig_timetable(self, week_start), _hc_this_refresh)


async def _hc_request_url(self, *args, **kwargs):
    # One request at a time: upstream fires up to 9 in parallel (9 new
    # connections through the proxy); sequential requests reuse one. A random
    # 2-6 s pause before each, like someone clicking through the diary - a
    # full refresh (~30 requests) takes about 2 minutes.
    import random
    lock = self.__dict__.setdefault("_hc_request_lock", asyncio.Lock())
    async with lock:
        # Requests outside a refresh (calendar weeks, message bodies) right
        # after a restart served from the cache have no route yet.
        chosen = self.__dict__.get("_hc_route_at")
        if chosen is None or dt_util.utcnow() - chosen > timedelta(minutes=30):
            await _choose_route(self)
        await asyncio.sleep(random.uniform(2.0, 6.0))
        return await _hc_orig_request_url(self, *args, **kwargs)


def _hc_browser_headers(session) -> None:
    # Session-wide defaults so every request - including the login GETs,
    # which upstream sends with aiohttp's own "Python/3.x aiohttp/3.x"
    # User-Agent - looks like the same desktop browser, set up in Poland.
    # HA hands the session a read-only mapping - replace it with a copy.
    from multidict import CIMultiDict
    from .librus_api.const import USER_AGENT
    headers = CIMultiDict(session._default_headers)
    headers["User-Agent"] = USER_AGENT
    headers["Accept-Language"] = "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7"
    session._default_headers = headers


LibrusApiClient.async_get_attendances = _hc_attendances
LibrusApiClient.async_get_attendance_types = _hc_attendance_types
LibrusApiClient.async_get_timetable = _hc_timetable
LibrusApiClient._async_request_url = _hc_request_url


_hc_orig_choose_route = _choose_route


async def _choose_route(client) -> None:
    # Patch 5's route choice + a "librus_route" event ({{"route": "direct" |
    # "rpi5"}}) on every refresh; the Telegram automation in
    # packages/librus.yaml notices when it differs from the last one.
    await _hc_orig_choose_route(client)
    client._hc_route_at = dt_util.utcnow()
    hass = client.__dict__.get("_hc_hass")
    if hass is not None:
        hass.bus.async_fire("librus_route", {{"route": "rpi5" if client._session._default_proxy else "direct"}})


def _cache_path(coordinator) -> str:
    return coordinator.hass.config.path(".storage", f"librus_cache_{{coordinator.config_entry.entry_id}}.pickle")


def _cache_read(path: str):
    import os
    import pickle
    try:
        with open(path, "rb") as fh:
            saved = pickle.load(fh)
    except FileNotFoundError:
        return None
    except Exception as err:  # e.g. the models changed after an update
        _LOGGER.warning("Librus cache %s unreadable (%s) - ignoring it", os.path.basename(path), err)
        return None
    return saved if len(saved) == 3 else (*saved, {{}})  # v1 files had no extras


def _cache_write(path: str, data, extras) -> None:
    import os
    import pickle
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        pickle.dump((dt_util.utcnow(), data, extras), fh)
    os.replace(tmp, path)


def _cache_restore(coordinator, extras) -> None:
    for attr, value in extras.get("coordinator", {{}}).items():
        if hasattr(coordinator, attr):
            setattr(coordinator, attr, value)
    coordinator._client.__dict__.setdefault("_hc_weekly", {{}}).update(extras.get("weekly", {{}}))


def _cache_extras(coordinator) -> dict:
    return {{
        "coordinator": {{a: getattr(coordinator, a) for a in _CACHE_EXTRA_ATTRS if hasattr(coordinator, a)}},
        "weekly": dict(coordinator._client.__dict__.get("_hc_weekly", {{}})),
    }}


async def _async_update_data_cached(self) -> LibrusData:
    path = _cache_path(self)
    cached = None
    if self.data is None:  # first refresh since HA (re)started / the entry was set up
        cached = await self.hass.async_add_executor_job(_cache_read, path)
        if cached is not None:
            _cache_restore(self, cached[2])
            if dt_util.utcnow() - cached[0] < _CACHE_MAX_AGE_ON_START:
                _LOGGER.info("Librus: using cached data from %s, no request", dt_util.as_local(cached[0]))
                return cached[1]
    self._client._hc_hass = self.hass
    try:
        _hc_browser_headers(self._client._session)
    except Exception as err:  # never let cosmetics break a refresh
        _LOGGER.warning("Librus: browser headers not set: %s", err)
    try:
        data = await self._async_update_data_upstream()
    except ConfigEntryAuthFailed:
        raise
    except Exception as err:
        fallback = self.data if self.data is not None else (cached[1] if cached else None)
        if fallback is None:
            raise
        _LOGGER.warning("Librus refresh failed (%s) - keeping the previous data", err)
        return fallback
    self.hass.bus.async_fire("librus_refreshed", {{}})  # packages/librus.yaml: stale-data alert
    try:
        await self.hass.async_add_executor_job(_cache_write, path, data, _cache_extras(self))
    except Exception as err:
        _LOGGER.warning("Librus cache not saved: %s", err)
    return data


LibrusDataUpdateCoordinator._async_update_data = _async_update_data_cached
"""
REFERENCE_AGE = "            and now - self._reference_data_fetched_at < timedelta(hours=24)\n"
REFERENCE_WEEKLY = f"            and self._reference_data_fetched_at >= _hc_week_boundary()  # {CACHE_MARKER}: weekly\n"
SETUP_LOGIN = ("    if not client.is_session_valid():\n"
               "        await client.async_login(entry.data[CONF_PASSWORD])\n")
SETUP_NO_LOGIN = (f"    # {CACHE_MARKER}: no up-front login - the first real refresh logs in\n"
                  "    # if needed, after the route is chosen (or is served from the cache).\n")


def patch_cache() -> None:
    """Patch 6 - see the module docstring. Upgrades an older version of the
    appended block in place (it is always the last thing in the file)."""
    path = INTEGRATION / "coordinator.py"
    text = path.read_text(encoding="utf-8")
    header = f"\n\n# --- {CACHE_MARKER} (librus/apply_local_patches.py, patch 6"
    if CACHE_MARKER not in text:
        if text.count(CACHE_DEF) != 1:
            sys.exit("coordinator.py: _async_update_data not found - upstream changed, patch not applied")
        text = text.replace(CACHE_DEF, CACHE_RENAMED) + CACHE_FUNC
        print("coordinator.py: data cache patched")
    elif CACHE_VERSION not in text:
        text = text[:text.index(header)] + CACHE_FUNC
        print(f"coordinator.py: data cache upgraded to {CACHE_VERSION}")
    else:
        print("coordinator.py: data cache already patched")
    if REFERENCE_WEEKLY not in text:
        if text.count(REFERENCE_AGE) != 1:
            sys.exit("coordinator.py: reference-data 24 h check not found - upstream changed, patch not applied")
        text = text.replace(REFERENCE_AGE, REFERENCE_WEEKLY)
        print("coordinator.py: reference data weekly")
    path.write_text(text, encoding="utf-8")
    init = INTEGRATION / "__init__.py"
    text = init.read_text(encoding="utf-8")
    if CACHE_MARKER in text:
        print("__init__.py: setup login already patched")
    else:
        if text.count(SETUP_LOGIN) != 1:
            sys.exit("__init__.py: setup login not found - upstream changed, patch not applied")
        init.write_text(text.replace(SETUP_LOGIN, SETUP_NO_LOGIN), encoding="utf-8")
        print("__init__.py: setup login patched")


SCHOOL_DATE_OLD = "dt_util.now().date()"
SCHOOL_DATE_NEW = 'dt_util.now(dt_util.get_time_zone("Europe/Warsaw")).date()'


def patch_school_date() -> None:
    """Patch 7 - see the module docstring."""
    for name in ("sensor.py", "calendar.py", "coordinator.py"):
        path = INTEGRATION / name
        text = path.read_text(encoding="utf-8")
        count = text.count(SCHOOL_DATE_OLD)
        if count:
            path.write_text(text.replace(SCHOOL_DATE_OLD, SCHOOL_DATE_NEW), encoding="utf-8")
        print(f"{name}: school date - {count} replaced" if count else f"{name}: school date already patched")


CARDS = CONFIG / "www" / "community" / "ha-librus-synergia-cards" / "librus-synergia-cards.js"
CARDS_MARKER = f"/* {MARKER}: server-zone start_time */"
CARDS_HELPER = (CARDS_MARKER + "\nfunction __hcSrvDate(s,h){"
                "const naive=String(s).replace(\" \",\"T\");"
                "try{const tz=h&&h.config&&h.config.time_zone,u=new Date(naive+\"Z\");"
                "if(!tz||isNaN(u.getTime()))return new Date(naive);const p={};"
                "for(const x of new Intl.DateTimeFormat(\"en-US\",{timeZone:tz,hourCycle:\"h23\",year:\"numeric\","
                "month:\"numeric\",day:\"numeric\",hour:\"numeric\",minute:\"numeric\",second:\"numeric\"})"
                ".formatToParts(u))p[x.type]=x.value;"
                "const asUtc=Date.UTC(+p.year,+p.month-1,+p.day,+p.hour,+p.minute,+p.second);"
                "return new Date(u.getTime()-(asUtc-u.getTime()))}catch(e){return new Date(naive)}}\n")
CARDS_EDITS = [  # (old, new, expected count) - `i` is `hass` at all three places
    ('r.replace(" ","T")', "__hcSrvDate(r,i)", 2),
    ('d.replace(" ","T")', "__hcSrvDate(d,i)", 1),
]


def patch_cards() -> None:
    """Patch 8 - see the module docstring."""
    import gzip
    text = CARDS.read_text(encoding="utf-8")
    if CARDS_MARKER in text:
        print("cards: start_time zone already patched")
        return
    for old, new, count in CARDS_EDITS:
        if text.count(old) != count:
            sys.exit(f"cards: expected {count}x {old!r} - upstream changed, patch not applied")
        text = text.replace(old, new)
    text = CARDS_HELPER + text
    CARDS.write_text(text, encoding="utf-8")
    gz = CARDS.with_name(CARDS.name + ".gz")
    if gz.exists():
        gz.write_bytes(gzip.compress(text.encode("utf-8"), 9))
    print("cards: start_time zone patched (bump the Lovelace resource URL so browsers reload it)")


def patch_file(name: str, edits: list[tuple[str, str]]) -> str:
    path = INTEGRATION / name
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        return f"{name}: already patched"
    for old, new in edits:
        if text.count(old) != 1:
            sys.exit(f"{name}: expected exactly one {old!r} - upstream changed, patch not applied")
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    return f"{name}: patched"


def main() -> None:
    if not INTEGRATION.is_dir():
        sys.exit(f"{INTEGRATION} not found - is the integration installed?")
    for name, edits in TZ_PATCHES.items():
        print(patch_file(name, [(TZ_IMPORT_ANCHOR, TZ_IMPORT), *edits]))
    coordinator = INTEGRATION / "coordinator.py"
    text = coordinator.read_text(encoding="utf-8")
    if MARKER in text:
        print("coordinator.py: already patched")
    else:
        if text.count(SUBJECTS_LINE) != 1:
            sys.exit("coordinator.py: subject map line not found - upstream changed, patch not applied")
        coordinator.write_text(text.replace(SUBJECTS_LINE, SUBJECTS_PATCH) + SUBJECTS_FUNC, encoding="utf-8")
        print("coordinator.py: patched")
    patch_grades()
    patch_tick()
    patch_route()
    patch_cache()
    patch_school_date()
    patch_cards()
    print("Restart Home Assistant for the patches to take effect.")


if __name__ == "__main__":
    main()
