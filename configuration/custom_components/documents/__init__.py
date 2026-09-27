"""Serve the synced PDFs (ENERA acts, Oselya receipts) behind HA auth.

GET /api/documents/<kind>/<file> needs either a normal HA login or a signed
link (?docSig=..., see signing.py). sensor.document_links holds a fresh
signed link per file for the dashboards and the to-do list.

The signing secret is persisted in .storage, so links (e.g. in Telegram
messages) stay valid across HA restarts until they expire. A genuine but
expired link gets a plain 403 - only missing/forged auth raises 401, which
HA counts as a failed login.
"""
from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote

from aiohttp import web
from aiohttp.web_exceptions import HTTPUnauthorized

from homeassistant.components.http import KEY_AUTHENTICATED, HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery
from homeassistant.helpers.typing import ConfigType

from .const import DOCUMENTS_ROOT, DOMAIN, KINDS, SIGN_QUERY_PARAM
from .signing import async_load_secret, check_signature


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    await async_load_secret(hass)
    hass.http.register_view(DocumentsView())
    hass.async_create_task(
        discovery.async_load_platform(hass, "sensor", DOMAIN, {}, config)
    )
    return True


class DocumentsView(HomeAssistantView):
    url = "/api/documents/{kind}/{filename}"
    name = "api:documents"
    requires_auth = False  # checked in get(): HA login or our docSig

    async def get(self, request: web.Request, kind: str, filename: str) -> web.StreamResponse:
        hass = request.app["hass"]
        if not request.get(KEY_AUTHENTICATED):
            token = request.query.get(SIGN_QUERY_PARAM)
            result = check_signature(hass, token, request.path) if token else "invalid"
            if result == "expired":
                return web.Response(
                    status=HTTPStatus.FORBIDDEN,
                    text="Посилання застаріло - відкрий документ із дашборда.",
                )
            if result != "ok":
                raise HTTPUnauthorized
        if (
            kind not in KINDS
            or "/" in filename
            or "\\" in filename
            or filename.startswith(".")
            or not filename.lower().endswith(".pdf")
        ):
            return web.Response(status=HTTPStatus.NOT_FOUND)
        path = Path(DOCUMENTS_ROOT / kind / filename)
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
