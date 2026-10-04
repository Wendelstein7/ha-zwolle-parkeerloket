"""Tests for the sensor and binary sensor entities."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.zwolle_parkeerloket.const import MANUFACTURER, NAME

from .helpers import (
    GETBASE_URL,
    LOGIN_URL,
    build_account_payload,
    entity_id_for,
    load_fixture,
    reservation_payload,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

START = "2026-10-05T08:00:00+00:00"
END = "2026-10-05T08:30:00+00:00"
BEFORE = "2026-10-05T07:00:00+00:00"
DURING = "2026-10-05T08:15:00+00:00"
AFTER = "2026-10-05T09:00:00+00:00"


def _payload(
    start: str, end: str, *, plate: str = "AA11BB", display: str = "AA-11-BB"
) -> dict[str, Any]:
    """Return an account payload with a single reservation at the given window."""
    payload = load_fixture("account_active_reservation.json")
    reservation = payload["Permits"][0]["PermitMedias"][0]["ActiveReservations"][0]
    reservation["ValidFrom"] = start
    reservation["ValidUntil"] = end
    reservation["LicensePlate"]["Value"] = plate
    reservation["LicensePlate"]["DisplayValue"] = display
    return payload


def _mock_portal(aioclient_mock: Any, payload: dict[str, Any]) -> None:
    """Answer the portal's two endpoints with the given account payload."""
    aioclient_mock.post(LOGIN_URL, json=payload)
    aioclient_mock.post(GETBASE_URL, json=payload)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add the entry and set it up."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, platform: str, key: str) -> Any:
    """Return the state object of one of our entities."""
    entity_id = entity_id_for(hass, platform, key)
    assert entity_id is not None, f"no entity registered for {platform}.{key}"
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} has no state"
    return state


async def test_entities_reflect_an_active_reservation(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """While a reservation is running, every entity mirrors it."""
    freezer.move_to(DURING)
    _mock_portal(aioclient_mock, _payload(START, END))
    await _setup(hass, account_entry)

    balance = _state(hass, "sensor", "balance")
    assert balance.attributes["unit_of_measurement"] == "h"
    assert float(balance.state) == pytest.approx(119.0)

    plate = _state(hass, "sensor", "plate")
    assert plate.state == "AA11BB"
    assert plate.attributes["display_value"] == "AA-11-BB"
    assert plate.attributes["parked"] is True

    bookings = _state(hass, "sensor", "bookings")
    assert bookings.state == "1"
    assert bookings.attributes["reservations"] == [
        {
            "reservation_id": 555001,
            "license_plate": "AA11BB",
            "start": START,
            "end": END,
            "parked": True,
            "units": 30,
        }
    ]
    assert _state(hass, "binary_sensor", "parking_active").state == "on"


async def test_entities_without_any_reservation(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """Without a reservation the plate and the window are unknown and parking is off."""
    freezer.move_to(DURING)
    _mock_portal(aioclient_mock, load_fixture("account_no_reservations.json"))
    await _setup(hass, account_entry)

    assert _state(hass, "sensor", "balance").state == "120.0"
    assert _state(hass, "sensor", "plate").state == "unknown"
    assert "display_value" not in _state(hass, "sensor", "plate").attributes

    bookings = _state(hass, "sensor", "bookings")
    assert bookings.state == "0"
    assert bookings.attributes["reservations"] == []
    assert _state(hass, "binary_sensor", "parking_active").state == "off"


async def test_entities_with_a_future_reservation(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """A booking that has not started yet is shown, but parking is not active."""
    freezer.move_to(BEFORE)
    _mock_portal(aioclient_mock, _payload(START, END))
    await _setup(hass, account_entry)

    plate = _state(hass, "sensor", "plate")
    assert plate.state == "AA11BB"
    assert plate.attributes["parked"] is False, "it has not started yet"
    assert _state(hass, "sensor", "bookings").state == "0"
    assert _state(hass, "binary_sensor", "parking_active").state == "off"


async def test_entities_describe_the_car_that_leaves_first(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """With two cars parked, the single-valued entities describe one of them.

    The plate belongs to the car whose session ends soonest, which is the one most
    likely to need attention, and the bookings count says how many others there are
    so a dashboard cannot be misled by the lone value.
    """
    freezer.move_to(DURING)
    leaving_first = reservation_payload(
        reservation_id=555002,
        plate="CC22DD",
        valid_from=START,
        valid_until="2026-10-05T08:20:00Z",
    )
    payload = build_account_payload(
        reservation=(START, END), also_reserved=[leaving_first]
    )
    _mock_portal(aioclient_mock, payload)
    await _setup(hass, account_entry)

    plate = _state(hass, "sensor", "plate")
    assert plate.state == "CC22DD"
    assert plate.attributes["parked"] is True

    bookings = _state(hass, "sensor", "bookings")
    assert bookings.state == "2"
    assert [item["license_plate"] for item in bookings.attributes["reservations"]] == [
        "AA11BB",
        "CC22DD",
    ]
    assert _state(hass, "binary_sensor", "parking_active").state == "on"


async def test_parking_active_turns_off_after_the_window(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """Once the reservation has ended, parking is no longer reported as active."""
    freezer.move_to(DURING)
    _mock_portal(aioclient_mock, _payload(START, END))
    await _setup(hass, account_entry)
    assert _state(hass, "binary_sensor", "parking_active").state == "on"

    freezer.move_to(AFTER)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert _state(hass, "binary_sensor", "parking_active").state == "off"
    assert _state(hass, "sensor", "plate").state == "unknown"


async def test_zone_entity_is_disabled_by_default(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """The diagnostic zone entity is registered but disabled."""
    freezer.move_to(DURING)
    _mock_portal(aioclient_mock, _payload(START, END))
    await _setup(hass, account_entry)

    entity_id = entity_id_for(hass, "sensor", "zone")
    assert entity_id is not None
    assert hass.states.get(entity_id) is None
    assert (
        er.async_get(hass).async_get(entity_id).disabled_by
        is RegistryEntryDisabler.INTEGRATION
    )


async def test_zone_entity_can_be_enabled(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """Enabling the zone entity makes it report the permit zone."""
    freezer.move_to(DURING)
    _mock_portal(aioclient_mock, _payload(START, END))
    await _setup(hass, account_entry)

    entity_id = entity_id_for(hass, "sensor", "zone")
    registry = er.async_get(hass)
    registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(account_entry.entry_id)
    await hass.async_block_till_done()

    assert _state(hass, "sensor", "zone").state == "ZONE1"


async def test_entities_are_grouped_in_one_device(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """Every entity belongs to the account's device."""
    freezer.move_to(DURING)
    _mock_portal(aioclient_mock, _payload(START, END))
    await _setup(hass, account_entry)

    device_id = (
        er.async_get(hass).async_get(entity_id_for(hass, "sensor", "balance")).device_id
    )
    device = dr.async_get(hass).async_get(device_id)

    assert device is not None
    assert device.name == NAME
    assert device.manufacturer == MANUFACTURER
    assert device.entry_type is DeviceEntryType.SERVICE
    for platform, key in (
        ("sensor", "plate"),
        ("sensor", "bookings"),
        ("binary_sensor", "parking_active"),
        ("calendar", "calendar"),
    ):
        assert (
            er.async_get(hass).async_get(entity_id_for(hass, platform, key)).device_id
            == device_id
        )
