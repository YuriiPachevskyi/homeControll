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
    print("Restart Home Assistant for the patches to take effect.")


if __name__ == "__main__":
    main()
