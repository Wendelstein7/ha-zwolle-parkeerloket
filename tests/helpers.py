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


DEFAULT_RESERVATION_ID = 555001


def reservation_payload(
    *,
    reservation_id: int = DEFAULT_RESERVATION_ID,
    plate: str = "AA11BB",
    valid_from: str,
    valid_until: str,
    units: int = 30,
) -> dict[str, Any]:
    """Return one entry for the portal's ``ActiveReservations`` list."""
    return {
        "ReservationID": reservation_id,
        "ValidFrom": valid_from,
        "ValidUntil": valid_until,
        "LicensePlate": {
            "IsCleared": False,
            "IsAnonymised": False,
            "DisplayValue": plate,
            "Value": plate,
            "Name": None,
        },
        "Units": units,
        "PermitMediaCode": MELDNUMMER,
    }


def build_account_payload(
    *,
    balance: int = 7140,
    reservation: tuple[str, str] | None = None,
    also_reserved: list[dict[str, Any]] | None = None,
    plate: str = "AA11BB",
    restricted_prolong: bool = False,
    restricted_prolong_ids: list[int] | None = None,
    horizon: str | None = None,
) -> dict[str, Any]:
    """Return an account payload with the state a test needs.

    ``reservation`` is a ``(ValidFrom, ValidUntil)`` pair, omitted for an account
    with nothing booked. ``also_reserved`` adds further reservations, built with
    :func:`reservation_payload`, for the accounts that have more than one car
    parked at once. ``restricted_prolong`` marks the default reservation as one the
    portal refuses to extend, and ``horizon`` adds the bookable window the portal
    publishes as ``BlockTimes``.
    """
    payload = load_fixture("account_active_reservation.json")
    permit = payload["Permits"][0]
    media = permit["PermitMedias"][0]

    media["Balance"] = balance
    media["Code"] = MELDNUMMER

    active: list[dict[str, Any]] = []
    if reservation is not None:
        start, end = reservation
        active.append(
            reservation_payload(plate=plate, valid_from=start, valid_until=end)
        )
    active.extend(also_reserved or [])
    media["ActiveReservations"] = active

    if restricted_prolong_ids is not None:
        restricted = restricted_prolong_ids
    else:
        restricted = [DEFAULT_RESERVATION_ID] if restricted_prolong else []
    media["RestrictedProlongReservationIDs"] = restricted

    permit["BlockTimes"] = (
        [{"ValidFrom": "2026-10-04T00:00:00Z", "ValidUntil": horizon}]
        if horizon is not None
        else []
    )
    return payload


def as_write_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap an account payload the way the portal answers a write: one permit."""
    return {"Permit": payload["Permits"][0]}
