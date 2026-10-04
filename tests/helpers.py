"""Shared, fixture-free helpers for the zwolle_parkeerloket tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.zwolle_parkeerloket.const import (
    API_BASE_URL,
    CONF_MELDNUMMER,
    CONF_PINCODE,
    DOMAIN,
    NAME,
)

FIXTURES = Path(__file__).parent / "fixtures"

# Synthetic placeholders. These must never be copied from a real account: the
# research credentials are not test data and personal data (plates, names) does
# not belong in this repository either.
MELDNUMMER = "12345"
PINCODE = "test-pincode"

LOGIN_URL = f"{API_BASE_URL}/api/login"
GETBASE_URL = f"{API_BASE_URL}/api/login/getbase"


def load_fixture(name: str) -> dict[str, Any]:
    """Return a sanitised JSON payload from the fixtures directory."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def account_data(pincode: str = PINCODE) -> dict[str, Any]:
    """Return a config entry payload for the test account."""
    return {CONF_MELDNUMMER: MELDNUMMER, CONF_PINCODE: pincode}


def account_title() -> str:
    """Return the title the config flow gives to the test account."""
    return f"{NAME} ({MELDNUMMER})"


def posted_login_payloads(mock: Any) -> list[dict[str, Any]]:
    """Return every login body the integration has sent."""
    return [
        payload
        for method, url, payload, _headers in mock.mock_calls
        if method.lower() == "post" and str(url) == LOGIN_URL
    ]


def entity_id_for(hass: HomeAssistant, platform: str, key: str) -> str | None:
    """Return the entity id of one of our entities, looked up by its unique id."""
    registry = er.async_get(hass)
    return registry.async_get_entity_id(platform, DOMAIN, f"{MELDNUMMER}_{key}")
