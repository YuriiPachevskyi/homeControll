"""Serve the synced PDFs (ENERA acts, Oselya receipts) behind HA auth.

GET /api/documents/<kind>/<file> needs either a normal HA login or a signed
link (?authSig=..., see http.auth.async_sign_path). sensor.document_links
holds a fresh signed link per file for the dashboards and the to-do list.

Signed links die on every HA restart (the signing secret lives only in
memory) - the sensor re-signs on startup, so anything reading it catches up.
"""
from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery
from homeassistant.helpers.typing import ConfigType

from .const import DOCUMENTS_ROOT, DOMAIN, KINDS


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.http.register_view(DocumentsView())
    hass.async_create_task(
        discovery.async_load_platform(hass, "sensor", DOMAIN, {}, config)
    )
    return True


class DocumentsView(HomeAssistantView):
    url = "/api/documents/{kind}/{filename}"
    name = "api:documents"
    requires_auth = True

    async def get(self, request: web.Request, kind: str, filename: str) -> web.StreamResponse:
        if (
            kind not in KINDS
            or "/" in filename
            or "\\" in filename
            or filename.startswith(".")
            or not filename.lower().endswith(".pdf")
        ):
            return web.Response(status=HTTPStatus.NOT_FOUND)
        path = Path(DOCUMENTS_ROOT / kind / filename)
        hass = request.app["hass"]
        if not await hass.async_add_executor_job(path.is_file):
            return web.Response(status=HTTPStatus.NOT_FOUND)
        return web.FileResponse(
            path,
            headers={
                "Content-Type": "application/pdf",
                "Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}",
                "Cache-Control": "private, no-store",
            },
        )
