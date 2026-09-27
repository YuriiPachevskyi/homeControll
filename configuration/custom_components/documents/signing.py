"""Signed /api/documents links that survive HA restarts."""
from __future__ import annotations

import secrets
import time
from datetime import timedelta
from urllib.parse import unquote

import jwt

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, SIGN_QUERY_PARAM, STORAGE_KEY, STORAGE_VERSION


async def async_load_secret(hass: HomeAssistant) -> None:
    store: Store[dict[str, str]] = Store(
        hass, STORAGE_VERSION, STORAGE_KEY, private=True
    )
    data = await store.async_load()
    if not data or not data.get("secret"):
        data = {"secret": secrets.token_hex(32)}
        await store.async_save(data)
    hass.data[DOMAIN] = data["secret"]


def sign_path(hass: HomeAssistant, path: str, expiration: timedelta) -> str:
    """path must already be URL-quoted; the claim holds the decoded form."""
    claims = {
        "path": unquote(path),
        "exp": int(time.time() + expiration.total_seconds()),
    }
    token = jwt.encode(claims, hass.data[DOMAIN], algorithm="HS256")
    return f"{path}?{SIGN_QUERY_PARAM}={token}"


def check_signature(hass: HomeAssistant, token: str, path: str) -> str:
    """'ok', 'expired' (genuine but old) or 'invalid'."""
    try:
        claims = jwt.decode(token, hass.data[DOMAIN], algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return "expired"
    except jwt.InvalidTokenError:
        return "invalid"
    return "ok" if claims.get("path") == path else "invalid"
