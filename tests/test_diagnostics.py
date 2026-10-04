"""Tests for the diagnostics, which must never leak personal data."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zwolle_parkeerloket.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .helpers import (
    GETBASE_URL,
    LOGIN_URL,
    MELDNUMMER,
    PINCODE,
    load_fixture,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_diagnostics_redact_credentials_and_plates(
    hass: HomeAssistant, aioclient_mock: Any, account_entry: MockConfigEntry
) -> None:
    """The Meldnummer, Pincode and every licence plate are redacted."""
    payload = load_fixture("account_active_reservation.json")
    aioclient_mock.post(LOGIN_URL, json=payload)
    aioclient_mock.post(GETBASE_URL, json=payload)
    account_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(account_entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, account_entry)
    serialised = repr(diagnostics)

    assert MELDNUMMER not in serialised
    assert PINCODE not in serialised
    assert "AA11BB" not in serialised
    assert "AA-11-BB" not in serialised
    assert "Visitor one" not in serialised
    assert "CC22DD" not in serialised


async def test_diagnostics_still_describe_the_account(
    hass: HomeAssistant, aioclient_mock: Any, account_entry: MockConfigEntry
) -> None:
    """Useful, non-personal state survives the redaction."""
    payload = load_fixture("account_active_reservation.json")
    aioclient_mock.post(LOGIN_URL, json=payload)
    aioclient_mock.post(GETBASE_URL, json=payload)
    account_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(account_entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, account_entry)
    account = diagnostics["account"]

    assert account["balance"] == 7140
    assert account["zone_code"] == "ZONE1"
    assert account["media_type_id"] == 9
    assert account["reservation_count"] == 1
    assert account["license_plate_count"] == 2

    reservation = account["reservations"][0]
    assert reservation["reservation_id"] == 555001
    assert reservation["valid_from"] == "2026-10-05T08:00:00+00:00"
    assert reservation["valid_until"] == "2026-10-05T08:30:00+00:00"
    assert reservation["units"] == 30
    assert reservation["license_plate"] == {
        "value": "**REDACTED**",
        "name": "**REDACTED**",
    }
