"""Home Assistant glue that builds the API client with a session of its own.

The client itself (:mod:`custom_components.zwolle_parkeerloket.api`) knows nothing
about Home Assistant; only this module does.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import DVSPortalClient
from .const import (
    CONF_MELDNUMMER,
    CONF_PERMIT_MEDIA_TYPE_ID,
    CONF_PINCODE,
    DEFAULT_PERMIT_MEDIA_TYPE_ID,
)


def async_create_client(
    hass: HomeAssistant, data: Mapping[str, Any]
) -> DVSPortalClient:
    """Return a client backed by a dedicated Home Assistant managed session.

    The portal authenticates with a session cookie plus a rotating CSRF cookie, so
    it gets a session of its own instead of sharing the cookie jar of every other
    integration. ``async_create_clientsession`` closes the session when the config
    entry is unloaded, and when Home Assistant stops.
    """
    session = async_create_clientsession(
        hass, cookie_jar=aiohttp.CookieJar(unsafe=False)
    )
    return DVSPortalClient(
        session,
        meldnummer=data[CONF_MELDNUMMER],
        pincode=data[CONF_PINCODE],
        permit_media_type_id=data.get(
            CONF_PERMIT_MEDIA_TYPE_ID, DEFAULT_PERMIT_MEDIA_TYPE_ID
        ),
    )
