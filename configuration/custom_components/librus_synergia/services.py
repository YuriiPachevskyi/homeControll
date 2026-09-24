"""Service registrations for the Librus Synergia (unofficial) integration.

- `get_message` - see its handler's docstring for why this is deliberately
  a service (explicit user action) rather than anything wired into routine
  polling.
- `refresh` - force an immediate data refresh (e.g. right before a morning
  briefing automation, instead of waiting for the next poll).
- `get_grades` - all of a student's grades (optionally filtered to one
  subject) in one response, instead of reading each subject sensor's own
  `grades` attribute separately. Purely a reshape of `coordinator.data`
  already in memory - no extra Librus request, unlike `get_message`.
"""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import DOMAIN
from .coordinator import LibrusDataUpdateCoordinator, decode_message_content, resolve_sender_name
from .librus_api import LibrusError

_LOGGER = logging.getLogger(__name__)

SERVICE_GET_MESSAGE = "get_message"
SERVICE_REFRESH = "refresh"
SERVICE_GET_GRADES = "get_grades"

_GET_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("message_id"): cv.string,
        vol.Optional("mailbox", default="inbox"): cv.string,
    }
)

_REFRESH_SCHEMA = vol.Schema({vol.Optional("device_id"): cv.string})

_GET_GRADES_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Optional("subject_id"): vol.Coerce(int),
    }
)


def _resolve_coordinator(hass: HomeAssistant, device_id: str) -> LibrusDataUpdateCoordinator:
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(f"Unknown device: {device_id}")

    entry = next(
        (
            e
            for entry_id in device.config_entries
            if (e := hass.config_entries.async_get_entry(entry_id)) is not None
            and e.domain == DOMAIN
        ),
        None,
    )
    if entry is None:
        raise ServiceValidationError(f"Device {device_id} is not a Librus Synergia device.")
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(f"The Librus Synergia entry for {device_id} isn't loaded.")
    return entry.runtime_data


def async_setup_services(hass: HomeAssistant) -> None:
    """Register this integration's services, once for the whole domain
    regardless of how many config entries (students) exist - guarded so a
    second config entry being set up doesn't try to double-register."""
    if hass.services.has_service(DOMAIN, SERVICE_GET_MESSAGE):
        return

    async def _async_handle_refresh(call: ServiceCall) -> None:
        """Force an immediate data refresh. With `device_id` set, just that
        student; otherwise every loaded Librus Synergia entry. Uses the
        coordinator's debounced request, so spamming it is harmless."""
        device_id = call.data.get("device_id")
        if device_id:
            coordinators = [_resolve_coordinator(hass, device_id)]
        else:
            coordinators = [
                entry.runtime_data
                for entry in hass.config_entries.async_entries(DOMAIN)
                if entry.state is ConfigEntryState.LOADED
            ]
        for coordinator in coordinators:
            await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, _async_handle_refresh, schema=_REFRESH_SCHEMA
    )

    async def _async_handle_get_message(call: ServiceCall) -> ServiceResponse:
        """Fetch ONE message's full, untruncated content.

        Deliberately a service, not a sensor attribute or coordinator
        field: CONFIRMED live (2026-09-06) that fetching a single message
        marks it read server-side on Librus (readDate flips from null to a
        real timestamp on the very next poll) - exactly like opening a
        message in the real Librus app. This must only ever run when a
        person has explicitly asked to read ONE specific message (e.g.
        clicking it in a dashboard card) - never from the coordinator's
        routine polling, which only ever uses the list/count endpoints and
        never marks anything read (see LibrusApiClient's module comment
        above async_get_message).
        """
        coordinator = _resolve_coordinator(hass, call.data["device_id"])
        message_id = call.data["message_id"]
        mailbox = call.data["mailbox"]
        try:
            raw = await coordinator.async_fetch_message(mailbox, message_id)
        except LibrusError as err:
            raise HomeAssistantError(f"Failed to fetch message {message_id}: {err}") from err

        data = raw.get("data")
        if not isinstance(data, dict):
            raise HomeAssistantError(f"Unexpected response fetching message {message_id}.")

        sender_name = resolve_sender_name(data)
        # CONFIRMED live (2026-09-17): each entry is {"filename": ..., "id":
        # ...}. The file itself still can't be downloaded through this
        # integration (see BACKLOG.md) - only the name, so at least someone
        # knows what to look for in the real Librus app/website.
        attachments = [
            {"id": str(a["id"]), "filename": a.get("filename")}
            for a in data.get("attachments") or []
            if isinstance(a, dict) and a.get("id") is not None
        ]
        return {
            "id": message_id,
            "mailbox": mailbox,
            "sender": sender_name,
            "topic": data.get("topic", ""),
            "content": decode_message_content(data.get("Message", "")),
            "send_date": data.get("sendDate"),
            "read_date": data.get("readDate"),
            "has_attachment": bool(attachments),
            "attachments": attachments,
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_MESSAGE,
        _async_handle_get_message,
        schema=_GET_MESSAGE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    async def _async_handle_get_grades(call: ServiceCall) -> ServiceResponse:
        """All of a student's grades in one response, optionally filtered
        to one `subject_id`.

        Unlike `get_message`, this reads straight from the coordinator's
        already-fetched data - no live Librus request, so it's safe to
        call from routine automations, not just direct user action. Each
        subject average sensor already exposes its OWN `grades` attribute,
        but reading "every grade across every subject" today means polling
        16+ separate sensors; this is the single-call equivalent.
        """
        coordinator = _resolve_coordinator(hass, call.data["device_id"])
        if coordinator.data is None:
            raise HomeAssistantError("No data available yet - the integration hasn't completed its first refresh.")

        subject_id = call.data.get("subject_id")
        data = coordinator.data
        grades = [
            {
                "subject": data.subjects.get(grade.subject_id) if grade.subject_id is not None else None,
                "subject_id": grade.subject_id,
                "value": grade.value,
                "category": (
                    category.name
                    if (category := data.grade_categories.get(grade.category_id)) is not None
                    else None
                ),
                "date": grade.add_date,
                "semester": grade.semester,
                "comments": list(grade.comments),
            }
            for grade in data.grades
            if subject_id is None or grade.subject_id == subject_id
        ]
        grades.sort(key=lambda g: g["date"] or "", reverse=True)
        return {"grades": grades, "count": len(grades)}

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_GRADES,
        _async_handle_get_grades,
        schema=_GET_GRADES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )


def async_unload_services(hass: HomeAssistant) -> None:
    """Remove this integration's services - call only once the LAST config
    entry is about to be unloaded (see __init__.py::async_unload_entry),
    so a second student's entry doesn't lose the service while the first
    one is just being reloaded."""
    for service in (SERVICE_GET_MESSAGE, SERVICE_REFRESH, SERVICE_GET_GRADES):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)


# --- homeControll local patch: attachments (librus/apply_local_patches.py, patch 9) ---
import asyncio as _hc_asyncio
import re as _hc_re
import time as _hc_time
from urllib.parse import quote as _hc_quote

from aiohttp import web as _hc_web
from homeassistant.components.http import HomeAssistantView as _HcView
from homeassistant.const import CONF_PASSWORD as _HC_CONF_PASSWORD
from homeassistant.helpers.http import KEY_HASS as _HC_KEY_HASS

from .librus_api import LibrusSessionExpiredError as _HcExpired
from .librus_api.client import LibrusApiClient as _HcClient
from .librus_api.const import MESSAGES_BASE_URL as _HC_MSG_BASE


async def _hc_client_download(self, message_id: str, attachment_id: str):
    info = await self._async_request_url(f"{_HC_MSG_BASE}/attachments/{attachment_id}/messages/{message_id}")
    link = ((info or {}).get("data") or {}).get("downloadLink")
    if not link:
        raise LibrusError(f"No download link for attachment {attachment_id}")
    async with self._session.get(link) as resp:  # the "Pobieranie plików" page a browser loads first
        await resp.read()
    await _hc_asyncio.sleep(1.5)
    async with self._session.get(link.rstrip("/") + "/get") as resp:
        if resp.status != 200:
            raise LibrusError(f"Attachment download failed: HTTP {resp.status}")
        return await resp.read(), resp.headers.get("Content-Type", ""), resp.headers.get("Content-Disposition", "")


_HcClient.async_download_attachment = _hc_client_download


async def _hc_coordinator_download(self, message_id: str, attachment_id: str):
    try:
        return await self._client.async_download_attachment(message_id, attachment_id)
    except _HcExpired:  # same recovery as async_fetch_message
        await self._client.async_ensure_session_valid(self.config_entry.data[_HC_CONF_PASSWORD], force=True)
        self._messages_bootstrapped = False
        self._messages_available = await self._client.async_bootstrap_messages()
        self._messages_bootstrapped = True
        return await self._client.async_download_attachment(message_id, attachment_id)


LibrusDataUpdateCoordinator.async_download_attachment = _hc_coordinator_download
_HC_ATT_CACHE: dict = {}


class _HcAttachmentView(_HcView):
    url = "/api/librus_synergia/attachment/{message_id}/{attachment_id}"
    name = "api:librus_synergia:attachment"
    requires_auth = True  # the cards open it through a signed path

    async def get(self, request, message_id: str, attachment_id: str):
        if not (message_id.isdigit() and attachment_id.isdigit()):
            return _hc_web.Response(status=400)
        hass = request.app[_HC_KEY_HASS]
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        if not entries:
            return _hc_web.Response(status=503, text="Librus is not loaded")
        key = (message_id, attachment_id)
        hit = _HC_ATT_CACHE.get(key)
        if hit is None or _hc_time.time() - hit[0] > 3600:
            try:
                body, ctype, disp = await entries[0].runtime_data.async_download_attachment(message_id, attachment_id)
            except Exception as err:
                _LOGGER.warning("Librus attachment %s/%s: %s", message_id, attachment_id, err)
                return _hc_web.Response(status=502, text="Could not download the attachment from Librus")
            match = _hc_re.search(r'filename="?([^";]+)"?', disp or "")
            hit = (_hc_time.time(), body, (ctype or "application/octet-stream").split(";")[0].strip(),
                   match.group(1) if match else f"attachment-{attachment_id}")
            _HC_ATT_CACHE[key] = hit
            for old in sorted(_HC_ATT_CACHE, key=lambda k: _HC_ATT_CACHE[k][0])[:-5]:
                del _HC_ATT_CACHE[old]
        _, body, ctype, filename = hit
        return _hc_web.Response(body=body, content_type=ctype, headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{_hc_quote(filename)}",
            "Cache-Control": "private, max-age=3600",
        })


_hc_orig_setup_services = async_setup_services


def async_setup_services(hass: HomeAssistant) -> None:
    _hc_orig_setup_services(hass)
    if not hass.data.get("_hc_librus_attachment_view"):
        hass.http.register_view(_HcAttachmentView())
        hass.data["_hc_librus_attachment_view"] = True
