#!/usr/bin/env python3
"""Print enera/tariffs.json in the compact form Home Assistant needs.

Run by the command_line sensor in packages/enera_tariffs.yaml inside the HA
container, so it must stay stdlib-only. Output (one JSON line):
  {"months": N, "latest": <green tariff of newest month>,
   "tariffs": {"YYYY-MM": <green tariff>, ...}}
Months without a green tariff (deficit months such as 2026-01) are left out.
"""
import json
from pathlib import Path

data = json.loads((Path(__file__).parent / "tariffs.json").read_text())
tariffs = {m: r["green_tariff"] for m, r in sorted(data.items()) if r.get("green_tariff")}
print(
    json.dumps(
        {
            "months": len(tariffs),
            "latest": tariffs[max(tariffs)] if tariffs else None,
            "tariffs": tariffs,
        }
    )
)
