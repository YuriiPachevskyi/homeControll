#!/usr/bin/env python3
"""LAN watcher: phone presence and new-device alerts on openwrtn + openwrtk.

Runs from cron every minute. Asks each router (ssh) which MACs are active right
now: associated Wi-Fi stations on both radios plus the br-lan forwarding
table, which also covers devices behind the MiWiFi repeater (wired bridge
port). "Known" devices are the router's static DHCP hosts (the named ones).

1. Phone presence. Each phone in PHONES (by its router's static host name)
   becomes device_tracker.<name> via MQTT discovery (retained): state
   "home"/"not_home", attribute "since" = when that state really started
   (arrival time, or the last time the phone was seen before it left). A phone counts as gone only after AWAY_AFTER without
   being seen, so short Wi-Fi sleeps don't flap. The automation "Phone back
   on the network" uses "since" for its 10 h rule (realme-6: 5 daytime
   hours). If a router can't be reached, its phones keep their last state.

2. New devices. An active MAC that is not a static host on its router, not
   an ignored vendor and has never been seen before triggers script.notify_new_device in HA (Telegram to Yurii) once, with its
   IP/hostname from the DHCP lease, vendor (IEEE OUI list) and how it is
   connected. The alert waits up to NEW_DEVICE_WAIT for the DHCP lease so the
   IP is usually there. Every MAC ever seen is kept in state.json, so each
   device is reported only once. The first run on a router only records what
   is already there (seeded_routers), without alerts.

State between runs: presence/state.json. stdlib + mosquitto_pub only.
"""
import json
import re
import subprocess
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# (router, static DHCP host name on that router)
PHONES = [
    ("openwrtn", "HUAWEIP30"),
    ("openwrtn", "POCO-M5s"),
    ("openwrtk", "realme-6"),
]
ROUTERS = ["openwrtn", "openwrtk"]
# Vendors never reported as new, per router (substring of the IEEE OUI name).
NEW_DEVICE_IGNORE_VENDORS = {"openwrtn": [], "openwrtk": ["TCL"]}
AWAY_AFTER = timedelta(minutes=10)
NEW_DEVICE_WAIT = timedelta(minutes=3)
STATE_FILE = Path(__file__).with_name("state.json")
OUI_FILE = Path("/usr/share/ieee-data/oui.txt")
HA_URL = "http://localhost:8123"
HA_TOKEN_FILE = Path.home() / ".secrets" / "ha_token"
RADIO_NAMES = {"phy0-ap0": "Wi-Fi 2.4 ГГц", "phy1-ap0": "Wi-Fi 5 ГГц"}

ROUTER_CMD = (
    "echo '#hosts'; uci show dhcp | grep -E '@host\\[[0-9]+\\]\\.(name|mac)=';"
    "echo '#leases'; cat /tmp/dhcp.leases;"
    "for i in $(iw dev | awk '/Interface/{print $2}'); do"
    " echo \"#station $i\"; iw dev $i station dump | awk '/^Station/{print $2}'; done;"
    "echo '#bridge'; brctl showmacs br-lan | awk '$3==\"no\"{print $2}'"
)


def router_snapshot(router):
    out = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", router, ROUTER_CMD],
        capture_output=True, text=True, timeout=30, check=True,
    ).stdout
    hosts, leases, links, section = {}, {}, {}, None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("#"):
            section = line[1:]
            continue
        if not line or section is None:
            continue
        if section == "hosts" and "=" in line:
            key, value = line.split("=", 1)
            idx, field = key.rsplit(".", 1)
            hosts.setdefault(idx, {})[field] = value.strip("'")
        elif section == "leases":
            parts = line.split()
            if len(parts) >= 4:
                leases[parts[1].lower()] = {"ip": parts[2], "hostname": "" if parts[3] == "*" else parts[3]}
        elif section.startswith("station "):
            links[line.lower()] = RADIO_NAMES.get(section.split()[1], "Wi-Fi")
        elif section == "bridge":
            links.setdefault(line.lower(), "дріт або репітер")
    # One host entry may list several MACs separated by spaces.
    known = {}
    for h in hosts.values():
        for mac in h.get("mac", "").lower().split():
            known[mac] = h.get("name", "")
    return known, leases, links


def vendor(mac):
    if int(mac[:2], 16) & 0x02:
        return "випадковий MAC (телефон чи ноутбук)"
    prefix = mac.replace(":", "")[:6].upper()
    try:
        with OUI_FILE.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith(prefix):
                    return re.split(r"\(base 16\)", line, maxsplit=1)[1].strip()
    except FileNotFoundError:
        pass
    return "невідомий"


def slug(name):
    return name.lower().replace("-", "_")


def publish(topic, payload):
    subprocess.run(
        ["mosquitto_pub", "-h", "localhost", "-r", "-t", topic, "-m", payload],
        check=True, timeout=10,
    )


def ha_script(name, data):
    req = urllib.request.Request(
        f"{HA_URL}/api/services/script/{name}",
        data=json.dumps(data).encode(),
        headers={
            "Authorization": f"Bearer {HA_TOKEN_FILE.read_text().strip()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    urllib.request.urlopen(req, timeout=30).read()


def track_phones(state, now, snapshots):
    phones = state.setdefault("phones", {})
    for router, name in PHONES:
        if router not in snapshots:
            continue
        known, _, links = snapshots[router]
        mac = {n: m for m, n in known.items()}.get(name)
        if not mac:
            print(f"{now:%F %T} {name}: no static DHCP host with this name on {router}")
            continue
        s = phones.setdefault(name, {"status": "not_home", "since": now.isoformat(), "last_seen": None})
        if mac in links:
            s["last_seen"] = now.isoformat()
            if s["status"] != "home":
                s["status"], s["since"] = "home", now.isoformat()
                print(f"{now:%F %T} {name}: home")
        elif s["status"] == "home":
            last_seen = datetime.fromisoformat(s["last_seen"])
            if now - last_seen >= AWAY_AFTER:
                s["status"], s["since"] = "not_home", s["last_seen"]
                print(f"{now:%F %T} {name}: not_home (last seen {last_seen:%F %T})")

        base = f"homecontroll/presence/{slug(name)}"
        publish(f"homeassistant/device_tracker/phone_{slug(name)}/config", json.dumps({
            "name": None,
            "unique_id": f"phone_presence_{slug(name)}",
            "object_id": slug(name),
            "state_topic": f"{base}/state",
            "json_attributes_topic": f"{base}/attributes",
            "payload_home": "home",
            "payload_not_home": "not_home",
            "source_type": "router",
            "icon": "mdi:cellphone",
            "device": {"identifiers": [f"phone_{slug(name)}"], "name": name},
        }))
        publish(f"{base}/state", s["status"])
        publish(f"{base}/attributes", json.dumps({"since": s["since"], "mac": mac, "router": router}))


def watch_new_devices(state, now, router, known, leases, links):
    seeded = state.setdefault("seeded_routers", [])
    first_run = router not in seeded
    seen = state.setdefault("seen_macs", {})
    pending = state.setdefault("pending_new", {}).setdefault(router, {})
    ignore_vendors = NEW_DEVICE_IGNORE_VENDORS.get(router, [])
    for mac in links:
        if mac in known or mac in seen:
            continue
        if any(v.lower() in vendor(mac).lower() for v in ignore_vendors):
            continue
        if first_run:
            seen[mac] = now.isoformat()
            continue
        first = datetime.fromisoformat(pending.setdefault(mac, now.isoformat()))
        lease = leases.get(mac)
        if not lease and now - first < NEW_DEVICE_WAIT:
            continue
        lease = lease or {}
        ha_script("notify_new_device", {
            "hostname": lease.get("hostname") or "—",
            "ip": lease.get("ip") or "—",
            "mac": mac,
            "vendor": vendor(mac),
            "link": links[mac],
            "router": router,
        })
        print(f"{now:%F %T} new device on {router}: {mac} {lease.get('ip', '')} {lease.get('hostname', '')}")
        seen[mac] = now.isoformat()
        del pending[mac]
    if first_run:
        seeded.append(router)
    # Forget pending MACs that vanished before being reported; they count as new next time.
    for mac in [m for m in pending if m not in links]:
        del pending[mac]


def main():
    now = datetime.now().astimezone()
    snapshots = {}
    for router in ROUTERS:
        try:
            snapshots[router] = router_snapshot(router)
        except (subprocess.SubprocessError, OSError) as e:
            print(f"{now:%F %T} {router}: unreachable ({e.__class__.__name__})")
    try:
        state = json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}

    track_phones(state, now, snapshots)
    try:
        for router in NEW_DEVICE_IGNORE_VENDORS:
            if router in snapshots:
                watch_new_devices(state, now, router, *snapshots[router])
    finally:
        STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


if __name__ == "__main__":
    main()
