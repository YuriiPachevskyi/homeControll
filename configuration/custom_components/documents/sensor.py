"""sensor.document_links: a signed /api/documents link per synced PDF."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from homeassistant.components.http.auth import async_sign_path
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

from .const import DOCUMENTS_ROOT, KINDS, LINK_EXPIRATION, RESIGN_AFTER, SCAN_INTERVAL

# ENERA act file names carry the billed month as YYMM: ..._11780675-2509-77.pdf
ENERA_MONTH = re.compile(r"-(\d{2})(\d{2})-\d+\.pdf$")


def link_key(kind: str, name: str) -> str | None:
    """Dict key a consumer looks a file up by.

    enera: the billed month "YYYY-MM" (what the DAP table rows know);
    oselya: the file stem, "<object>.<bill>_YYYY-MM".
    """
    if kind == "enera":
        m = ENERA_MONTH.search(name)
        return f"20{m[1]}-{m[2]}" if m else None
    return name[:-4]


def scan() -> dict[str, list[str]]:
    return {
        kind: sorted(p.name for p in Path(DOCUMENTS_ROOT / kind).glob("*.pdf"))
        for kind in KINDS
    }


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    sensor = DocumentLinksSensor()
    async_add_entities([sensor])


class DocumentLinksSensor(SensorEntity):
    _attr_name = "Document links"
    _attr_unique_id = "document_links"
    _attr_icon = "mdi:file-lock-outline"
    _attr_should_poll = False
    # Signed links are secrets and change daily - keep them out of the recorder.
    _unrecorded_attributes = frozenset({*KINDS, "expires"})

    def __init__(self) -> None:
        self._files: dict[str, list[str]] | None = None
        self._signed_at: datetime | None = None
        self._attr_native_value = 0
        self._attr_extra_state_attributes = {}

    async def async_added_to_hass(self) -> None:
        await self._async_refresh()
        self.async_on_remove(
            async_track_time_interval(self.hass, self._async_refresh, SCAN_INTERVAL)
        )

    async def _async_refresh(self, _now: datetime | None = None) -> None:
        files = await self.hass.async_add_executor_job(scan)
        now = dt_util.utcnow()
        if (
            files == self._files
            and self._signed_at is not None
            and now - self._signed_at < RESIGN_AFTER
        ):
            return
        attrs: dict = {}
        for kind, names in files.items():
            links = {}
            for name in names:
                if (key := link_key(kind, name)) is None:
                    continue
                links[key] = async_sign_path(
                    self.hass,
                    f"/api/documents/{kind}/{quote(name)}",
                    LINK_EXPIRATION,
                    use_content_user=True,
                )
            attrs[kind] = links
        attrs["expires"] = (now + LINK_EXPIRATION).isoformat()
        self._files, self._signed_at = files, now
        self._attr_native_value = sum(len(v) for v in files.values())
        self._attr_extra_state_attributes = attrs
        self.async_write_ha_state()
