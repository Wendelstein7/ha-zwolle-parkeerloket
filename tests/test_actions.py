"""Tests for the booking actions: service actions, buttons and the plate field."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.zwolle_parkeerloket.const import API_BASE_URL, DOMAIN
from custom_components.zwolle_parkeerloket.services import (
    SERVICE_CHANGE_BOOKING_TIME,
    SERVICE_START_BOOKING,
    SERVICE_STOP_BOOKING,
)

from .helpers import (
    GETBASE_URL,
    LOGIN_URL,
    MELDNUMMER,
    as_write_response,
    build_account_payload,
    entity_id_for,
    load_fixture,
    reservation_payload,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

CREATE_URL = f"{API_BASE_URL}/api/reservation/create"
UPDATE_URL = f"{API_BASE_URL}/api/reservation/update"
END_URL = f"{API_BASE_URL}/api/reservation/end"

# A Monday morning with nothing booked, a moment inside an hour-long booking, and
# the free window the fixture's reservation sits in.
IDLE = "2026-10-05T10:00:00+00:00"
DURING = "2026-10-05T08:15:00+00:00"
BOOKING = ("2026-10-05T08:00:00Z", "2026-10-05T08:30:00Z")
LONG_BOOKING = ("2026-10-05T08:00:00Z", "2026-10-05T09:00:00Z")


def _register_reads(aioclient_mock: Any, payload: dict[str, Any]) -> None:
    """Answer logging in and reading the account."""
    aioclient_mock.post(LOGIN_URL, json=payload)
    aioclient_mock.post(GETBASE_URL, json=payload)


def _register_writes(aioclient_mock: Any, payload: dict[str, Any]) -> None:
    """Answer every write with the permit the payload describes.

    The mock returns the first registration for a URL, so a test that needs a
    different answer for one endpoint registers that one instead of this helper.
    """
    response = as_write_response(payload)
    for url in (CREATE_URL, UPDATE_URL, END_URL):
        aioclient_mock.post(url, json=response)


def _requests(aioclient_mock: Any, url: str) -> list[dict[str, Any]]:
    """Return the bodies of every request made to one URL."""
    return [
        data
        for _method, request_url, data, _headers in aioclient_mock.mock_calls
        if str(request_url) == url
    ]


def _calls(aioclient_mock: Any, url: str) -> int:
    """Return how many times one URL was requested."""
    return len(_requests(aioclient_mock, url))


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, freezer: Any, moment: str
) -> None:
    """Add the entry and set it up at a frozen moment."""
    freezer.move_to(moment)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _entity(hass: HomeAssistant, platform: str, key: str) -> str:
    """Return the entity id of one of our entities."""
    entity_id = entity_id_for(hass, platform, key)
    assert entity_id is not None, f"no entity registered for {platform}.{key}"
    return entity_id


def _state(hass: HomeAssistant, platform: str, key: str) -> str | None:
    """Return the state of one of our entities."""
    state = hass.states.get(_entity(hass, platform, key))
    assert state is not None
    return state.state


def _is_unavailable(hass: HomeAssistant, platform: str, key: str) -> bool:
    """Return whether an entity is currently unavailable."""
    return _state(hass, platform, key) == "unavailable"


async def _call(
    hass: HomeAssistant, service: str, data: dict[str, Any] | None = None
) -> None:
    """Call one of our actions, targeting the test account's device."""
    await hass.services.async_call(
        DOMAIN,
        service,
        {**(data or {}), "device_id": _device_id(hass)},
        blocking=True,
    )


def _device_id(hass: HomeAssistant) -> str:
    """Return the device id every entity of the test account belongs to."""
    entry = er.async_get(hass).async_get(_entity(hass, "sensor", "balance"))
    assert entry is not None and entry.device_id is not None
    return entry.device_id


def _bookings(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return the reservations the bookings sensor reports."""
    state = hass.states.get(_entity(hass, "sensor", "bookings"))
    assert state is not None
    return state.attributes["reservations"]


async def _set_plate(hass: HomeAssistant, value: str) -> None:
    """Type a value into the licence plate field."""
    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": _entity(hass, "text", "plate_draft"), "value": value},
        blocking=True,
    )


async def _press(hass: HomeAssistant, key: str) -> None:
    """Press one of the buttons."""
    await hass.services.async_call(
        "button", "press", {"entity_id": _entity(hass, "button", key)}, blocking=True
    )


# --- starting a booking ------------------------------------------------------


async def test_start_booking_sends_the_plate_without_dates(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """Booking now omits the dates so the portal picks the start itself."""
    _register_reads(aioclient_mock, build_account_payload())
    _register_writes(aioclient_mock, build_account_payload())
    await _setup(hass, account_entry, freezer, IDLE)

    await _call(hass, SERVICE_START_BOOKING, {"license_plate": "aa-11-bb"})

    body = _requests(aioclient_mock, CREATE_URL)[0]
    assert body["LicensePlate"]["Value"] == "AA11BB", "the plate must be normalised"
    assert body["permitMediaCode"] == MELDNUMMER
    assert "DateFrom" not in body
    assert "DateUntil" not in body


async def test_start_booking_applies_the_response_without_repolling(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """The write response already carries the new state, so no extra read is due."""
    booked = build_account_payload(
        balance=7080, reservation=("2026-10-05T10:00:00Z", "2026-10-05T11:00:00Z")
    )
    _register_reads(aioclient_mock, build_account_payload())
    _register_writes(aioclient_mock, booked)
    await _setup(hass, account_entry, freezer, IDLE)
    reads_before = _calls(aioclient_mock, GETBASE_URL)

    await _call(hass, SERVICE_START_BOOKING, {"license_plate": "AA11BB"})
    await hass.async_block_till_done()

    assert _calls(aioclient_mock, GETBASE_URL) == reads_before
    assert _state(hass, "binary_sensor", "parking_active") == "on"
    assert _state(hass, "sensor", "plate") == "AA11BB"
    assert _state(hass, "sensor", "balance") == "118.0"


async def test_start_booking_requires_a_plate(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """The plate names the booking, so the action demands one.

    The portal keeps several reservations at once, so an action that did not name
    a car could act on the wrong one. Home Assistant rejects the call before our
    code runs, so nothing reaches the portal. The exception type is left open
    because it comes from Home Assistant's own field validation.
    """
    _register_reads(aioclient_mock, build_account_payload())
    _register_writes(aioclient_mock, build_account_payload())
    await _setup(hass, account_entry, freezer, IDLE)

    with pytest.raises(Exception, match="license_plate"):
        await _call(hass, SERVICE_START_BOOKING)

    assert not _requests(aioclient_mock, CREATE_URL)


async def test_start_booking_with_an_impossible_plate_is_refused(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """A plate that cannot be real is rejected before it reaches the portal.

    The value is long enough to satisfy the schema, so it is our own validation
    that turns it down rather than Home Assistant's field length check.
    """
    _register_reads(aioclient_mock, build_account_payload())
    _register_writes(aioclient_mock, build_account_payload())
    await _setup(hass, account_entry, freezer, IDLE)

    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, SERVICE_START_BOOKING, {"license_plate": "!!!!"})

    assert err.value.translation_key == "invalid_plate"
    assert err.value.translation_placeholders["plate"] == "!!!!"
    assert not _requests(aioclient_mock, CREATE_URL)


async def test_start_booking_refuses_a_plate_that_is_already_parked(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """The portal refuses two overlapping bookings for one plate, and so do we.

    Checking first means the user gets a clear message instead of a round trip
    that was always going to be rejected.
    """
    _register_reads(aioclient_mock, build_account_payload(reservation=BOOKING))
    _register_writes(aioclient_mock, build_account_payload(reservation=BOOKING))
    await _setup(hass, account_entry, freezer, DURING)

    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, SERVICE_START_BOOKING, {"license_plate": "AA11BB"})

    assert err.value.translation_key == "plate_already_parked"
    assert err.value.translation_placeholders["plate"] == "AA11BB"
    assert not _requests(aioclient_mock, CREATE_URL)


async def test_start_booking_allows_a_second_car(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """A different plate may be parked while another car is parked."""
    _register_reads(aioclient_mock, build_account_payload(reservation=BOOKING))
    _register_writes(aioclient_mock, build_account_payload(reservation=BOOKING))
    await _setup(hass, account_entry, freezer, DURING)

    await _call(hass, SERVICE_START_BOOKING, {"license_plate": "CC22DD"})

    assert _requests(aioclient_mock, CREATE_URL)[0]["LicensePlate"]["Value"] == "CC22DD"


async def test_start_booking_rejection_from_the_portal_is_reported(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """A business error from the portal becomes a message the user can act on."""
    _register_reads(aioclient_mock, build_account_payload())
    aioclient_mock.post(CREATE_URL, json=load_fixture("business_error.json"))
    await _setup(hass, account_entry, freezer, IDLE)

    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, SERVICE_START_BOOKING, {"license_plate": "AA11BB"})

    assert err.value.translation_key == "reservation_rejected_time"
    assert "starttijd" in err.value.translation_placeholders["message"]


async def test_a_same_plate_race_is_reported_in_the_portal_s_words(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """The portal can refuse a plate that is not parked here yet.

    Our own check only knows what the last poll returned, so if another client
    books the same plate in between, the portal is the one that says no. Its
    wording is passed through rather than guessed at.
    """
    _register_reads(aioclient_mock, build_account_payload())
    aioclient_mock.post(
        CREATE_URL,
        json={
            "ErrorMessage": (
                "Het opgegeven kenteken is reeds in gebruik in een overlappende reservering"
            ),
            "Result": 24,
        },
    )
    await _setup(hass, account_entry, freezer, IDLE)

    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, SERVICE_START_BOOKING, {"license_plate": "AA11BB"})

    assert err.value.translation_key == "portal_rejected"
    assert "overlappende" in err.value.translation_placeholders["message"]


async def test_actions_need_one_of_our_accounts(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """Targeting something that is not a parking account is refused."""
    _register_reads(aioclient_mock, build_account_payload())
    _register_writes(aioclient_mock, build_account_payload())
    await _setup(hass, account_entry, freezer, IDLE)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_STOP_BOOKING,
            {"entity_id": "sensor.something_else_entirely", "license_plate": "AA11BB"},
            blocking=True,
        )

    assert err.value.translation_key == "no_target"
    assert not _requests(aioclient_mock, END_URL)


# --- stopping a booking ------------------------------------------------------


async def test_stop_booking_cancels_the_named_plate(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """Cancelling sends the reservation id of the plate, and applies the response."""
    _register_reads(aioclient_mock, build_account_payload(reservation=BOOKING))
    _register_writes(aioclient_mock, build_account_payload(balance=7200))
    await _setup(hass, account_entry, freezer, DURING)
    assert _state(hass, "binary_sensor", "parking_active") == "on"

    await _call(hass, SERVICE_STOP_BOOKING, {"license_plate": "aa-11-bb"})
    await hass.async_block_till_done()

    body = _requests(aioclient_mock, END_URL)[0]
    assert body["ReservationID"] == 555001
    assert body["permitMediaCode"] == MELDNUMMER
    assert _state(hass, "binary_sensor", "parking_active") == "off"
    assert _state(hass, "sensor", "balance") == "120.0"


async def test_stop_booking_without_a_reservation_is_refused(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """There is nothing to cancel when that plate is not parked."""
    _register_reads(aioclient_mock, build_account_payload())
    _register_writes(aioclient_mock, build_account_payload())
    await _setup(hass, account_entry, freezer, IDLE)

    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, SERVICE_STOP_BOOKING, {"license_plate": "AA11BB"})

    assert err.value.translation_key == "no_booking_for_plate"
    assert err.value.translation_placeholders["plate"] == "AA11BB"
    assert not _requests(aioclient_mock, END_URL)


async def test_stop_booking_only_cancels_the_plate_it_was_given(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """With two cars parked, the plate decides which one is cancelled."""
    other = reservation_payload(
        reservation_id=555002,
        plate="CC22DD",
        valid_from=BOOKING[0],
        valid_until=BOOKING[1],
    )
    payload = build_account_payload(reservation=BOOKING, also_reserved=[other])
    _register_reads(aioclient_mock, payload)
    _register_writes(aioclient_mock, payload)
    await _setup(hass, account_entry, freezer, DURING)

    await _call(hass, SERVICE_STOP_BOOKING, {"license_plate": "CC22DD"})

    assert _requests(aioclient_mock, END_URL)[0]["ReservationID"] == 555002


# --- changing the duration ---------------------------------------------------


async def test_change_booking_time_extends(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """A positive number of minutes is sent as a delta, and the result is applied."""
    _register_reads(aioclient_mock, build_account_payload(reservation=BOOKING))
    _register_writes(aioclient_mock, build_account_payload(reservation=LONG_BOOKING))
    await _setup(hass, account_entry, freezer, DURING)

    await _call(
        hass, SERVICE_CHANGE_BOOKING_TIME, {"license_plate": "AA11BB", "minutes": 30}
    )
    await hass.async_block_till_done()

    body = _requests(aioclient_mock, UPDATE_URL)[0]
    assert body["Minutes"] == 30
    assert body["ReservationID"] == 555001
    assert _bookings(hass)[0]["end"] == "2026-10-05T09:00:00+00:00"


async def test_change_booking_time_shortens(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """A negative number of minutes is sent as it is."""
    _register_reads(aioclient_mock, build_account_payload(reservation=LONG_BOOKING))
    _register_writes(aioclient_mock, build_account_payload(reservation=LONG_BOOKING))
    await _setup(hass, account_entry, freezer, "2026-10-05T08:00:00+00:00")

    await _call(
        hass, SERVICE_CHANGE_BOOKING_TIME, {"license_plate": "AA11BB", "minutes": -20}
    )

    assert _requests(aioclient_mock, UPDATE_URL)[0]["Minutes"] == -20


async def test_shortening_may_not_end_the_session(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """Shortening past the current moment is refused locally, not by the portal."""
    _register_reads(aioclient_mock, build_account_payload(reservation=BOOKING))
    _register_writes(aioclient_mock, build_account_payload(reservation=BOOKING))
    await _setup(hass, account_entry, freezer, DURING)

    with pytest.raises(ServiceValidationError) as err:
        await _call(
            hass,
            SERVICE_CHANGE_BOOKING_TIME,
            {"license_plate": "AA11BB", "minutes": -30},
        )

    assert err.value.translation_key == "cannot_shorten"
    assert err.value.translation_placeholders["minutes"] == "30"
    assert not _requests(aioclient_mock, UPDATE_URL)


async def test_extending_beyond_the_bookable_window_is_refused(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """The portal's published window is respected before asking it."""
    payload = build_account_payload(reservation=BOOKING, horizon="2026-10-05T08:40:00Z")
    _register_reads(aioclient_mock, payload)
    _register_writes(aioclient_mock, payload)
    await _setup(hass, account_entry, freezer, DURING)

    with pytest.raises(ServiceValidationError) as err:
        await _call(
            hass,
            SERVICE_CHANGE_BOOKING_TIME,
            {"license_plate": "AA11BB", "minutes": 30},
        )

    assert err.value.translation_key == "cannot_extend"
    assert err.value.translation_placeholders["minutes"] == "30"
    assert not _requests(aioclient_mock, UPDATE_URL)


async def test_extending_a_restricted_reservation_is_refused(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """The portal lists the reservations it will not prolong."""
    payload = build_account_payload(reservation=BOOKING, restricted_prolong=True)
    _register_reads(aioclient_mock, payload)
    _register_writes(aioclient_mock, payload)
    await _setup(hass, account_entry, freezer, DURING)

    with pytest.raises(ServiceValidationError) as err:
        await _call(
            hass,
            SERVICE_CHANGE_BOOKING_TIME,
            {"license_plate": "AA11BB", "minutes": 30},
        )

    assert err.value.translation_key == "cannot_extend"
    assert not _requests(aioclient_mock, UPDATE_URL)


async def test_changing_without_a_reservation_is_refused(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """There is nothing to change when nothing is booked."""
    _register_reads(aioclient_mock, build_account_payload())
    _register_writes(aioclient_mock, build_account_payload())
    await _setup(hass, account_entry, freezer, IDLE)

    with pytest.raises(ServiceValidationError) as err:
        await _call(
            hass,
            SERVICE_CHANGE_BOOKING_TIME,
            {"license_plate": "AA11BB", "minutes": 30},
        )

    assert err.value.translation_key == "no_booking_for_plate"
    assert err.value.translation_placeholders["plate"] == "AA11BB"
    assert not _requests(aioclient_mock, UPDATE_URL)


async def test_an_unknown_portal_rejection_is_passed_through(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """A rejection we cannot interpret keeps the portal's own message."""
    _register_reads(aioclient_mock, build_account_payload(reservation=BOOKING))
    aioclient_mock.post(
        UPDATE_URL, json={"ErrorMessage": "Onbekende fout", "Result": 99}
    )
    await _setup(hass, account_entry, freezer, DURING)

    with pytest.raises(ServiceValidationError) as err:
        await _call(
            hass,
            SERVICE_CHANGE_BOOKING_TIME,
            {"license_plate": "AA11BB", "minutes": 30},
        )

    assert err.value.translation_key == "portal_rejected"
    assert "Onbekende fout" in err.value.translation_placeholders["message"]


async def test_a_known_portal_rejection_gets_its_own_message(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """A code we understand is translated into something more useful."""
    _register_reads(aioclient_mock, build_account_payload(reservation=BOOKING))
    aioclient_mock.post(
        UPDATE_URL, json={"ErrorMessage": "Het kenteken is niet gevonden", "Result": 33}
    )
    await _setup(hass, account_entry, freezer, DURING)

    with pytest.raises(ServiceValidationError) as err:
        await _call(
            hass,
            SERVICE_CHANGE_BOOKING_TIME,
            {"license_plate": "AA11BB", "minutes": 30},
        )

    assert err.value.translation_key == "plate_not_found"


async def test_a_connection_failure_is_not_reported_as_a_rejection(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """A network problem is a failure, not something the user did wrong."""
    _register_reads(aioclient_mock, build_account_payload(reservation=BOOKING))
    aioclient_mock.post(UPDATE_URL, exc=TimeoutError)
    await _setup(hass, account_entry, freezer, DURING)

    with pytest.raises(HomeAssistantError) as err:
        await _call(
            hass,
            SERVICE_CHANGE_BOOKING_TIME,
            {"license_plate": "AA11BB", "minutes": 30},
        )

    assert err.value.translation_key == "cannot_connect_write"


# --- button availability -----------------------------------------------------


async def test_buttons_without_a_booking(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """Nothing to stop or adjust, and booking needs a plate first."""
    _register_reads(aioclient_mock, build_account_payload())
    _register_writes(aioclient_mock, build_account_payload())
    await _setup(hass, account_entry, freezer, IDLE)

    assert _is_unavailable(hass, "button", "book_now"), "no plate to book yet"
    for key in ("stop_booking", "extend_time", "shorten_time"):
        assert _is_unavailable(hass, "button", key)

    await _set_plate(hass, "AA11BB")

    assert not _is_unavailable(hass, "button", "book_now")


async def test_buttons_during_a_booking(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """With one car parked, stop and extend are offered; booking that car is not."""
    _register_reads(aioclient_mock, build_account_payload(reservation=BOOKING))
    _register_writes(aioclient_mock, build_account_payload(reservation=BOOKING))
    await _setup(hass, account_entry, freezer, DURING)
    await _set_plate(hass, "AA11BB")

    # That plate is parked already, and the portal refuses an overlapping booking.
    assert _is_unavailable(hass, "button", "book_now")
    assert not _is_unavailable(hass, "button", "stop_booking")
    assert not _is_unavailable(hass, "button", "extend_time")
    # Shortening by the step would end the session before now.
    assert _is_unavailable(hass, "button", "shorten_time")

    # A different car can still be booked while this one is parked.
    await _set_plate(hass, "CC22DD")

    assert not _is_unavailable(hass, "button", "book_now")


async def test_buttons_step_aside_when_several_cars_are_parked(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """A button cannot name a car, so with two parked it does not act at all.

    Cancelling whichever car happened to come first could cancel the wrong one.
    The calendar and the action services both name a booking, so they take over.
    """
    other = reservation_payload(
        reservation_id=555002,
        plate="CC22DD",
        valid_from=BOOKING[0],
        valid_until=BOOKING[1],
    )
    payload = build_account_payload(reservation=BOOKING, also_reserved=[other])
    _register_reads(aioclient_mock, payload)
    _register_writes(aioclient_mock, payload)
    await _setup(hass, account_entry, freezer, DURING)

    for key in ("stop_booking", "extend_time", "shorten_time"):
        assert _is_unavailable(hass, "button", key), key

    # Booking a third car is still a perfectly clear thing to ask for.
    await _set_plate(hass, "DD44EE")

    assert not _is_unavailable(hass, "button", "book_now")


async def test_shorten_button_is_available_on_a_long_enough_booking(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """An hour-long booking can lose half an hour."""
    _register_reads(aioclient_mock, build_account_payload(reservation=LONG_BOOKING))
    _register_writes(aioclient_mock, build_account_payload(reservation=LONG_BOOKING))
    await _setup(hass, account_entry, freezer, DURING)

    assert not _is_unavailable(hass, "button", "shorten_time")


async def test_extend_button_is_unavailable_when_prolonging_is_restricted(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """The button reflects the portal's own restriction."""
    payload = build_account_payload(reservation=BOOKING, restricted_prolong=True)
    _register_reads(aioclient_mock, payload)
    _register_writes(aioclient_mock, payload)
    await _setup(hass, account_entry, freezer, DURING)

    assert _is_unavailable(hass, "button", "extend_time")


async def test_pressing_the_buttons(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """Each button maps to exactly one portal call."""
    _register_reads(aioclient_mock, build_account_payload(reservation=LONG_BOOKING))
    _register_writes(aioclient_mock, build_account_payload(reservation=LONG_BOOKING))
    await _setup(hass, account_entry, freezer, DURING)

    await _press(hass, "extend_time")
    await _press(hass, "shorten_time")

    assert [body["Minutes"] for body in _requests(aioclient_mock, UPDATE_URL)] == [
        30,
        -30,
    ]

    await _press(hass, "stop_booking")

    assert _requests(aioclient_mock, END_URL)


async def test_pressing_book_uses_the_plate_field(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """The book button books whatever the plate field holds."""
    _register_reads(aioclient_mock, build_account_payload())
    _register_writes(aioclient_mock, build_account_payload())
    await _setup(hass, account_entry, freezer, IDLE)
    await _set_plate(hass, "dd33ee")

    await _press(hass, "book_now")

    assert _requests(aioclient_mock, CREATE_URL)[0]["LicensePlate"]["Value"] == "DD33EE"


# --- the licence plate field -------------------------------------------------


async def test_plate_field_normalises_what_is_typed(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """The field stores the plate in the form the API expects."""
    _register_reads(aioclient_mock, build_account_payload())
    await _setup(hass, account_entry, freezer, IDLE)

    await _set_plate(hass, "aa-11-bb")

    assert _state(hass, "text", "plate_draft") == "AA11BB"


async def test_plate_field_refuses_nonsense(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """A value that cannot be a plate is rejected as it is entered."""
    _register_reads(aioclient_mock, build_account_payload())
    await _setup(hass, account_entry, freezer, IDLE)

    with pytest.raises(ServiceValidationError) as err:
        await _set_plate(hass, "!!")

    assert err.value.translation_key == "invalid_plate"


async def test_plate_field_can_be_cleared(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """Clearing the field leaves nothing to book."""
    _register_reads(aioclient_mock, build_account_payload())
    await _setup(hass, account_entry, freezer, IDLE)
    await _set_plate(hass, "AA11BB")

    await _set_plate(hass, "")

    assert _state(hass, "text", "plate_draft") == "unknown"


async def test_plate_field_shows_what_is_booked(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """With nothing typed, the field shows the plate the portal reports."""
    _register_reads(
        aioclient_mock, build_account_payload(reservation=BOOKING, plate="EE44FF")
    )
    await _setup(hass, account_entry, freezer, DURING)

    assert _state(hass, "text", "plate_draft") == "EE44FF"


async def test_plate_field_keeps_a_draft_while_polling(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """A draft survives polls that repeat the same remote plate."""
    _register_reads(aioclient_mock, build_account_payload(reservation=BOOKING))
    await _setup(hass, account_entry, freezer, DURING)
    await _set_plate(hass, "FF55GG")

    freezer.tick(300)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert _state(hass, "text", "plate_draft") == "FF55GG"


async def test_plate_field_mirrors_a_change_from_the_portal(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """When the portal's plate changes, the field follows it."""
    _register_reads(aioclient_mock, build_account_payload(reservation=BOOKING))
    await _setup(hass, account_entry, freezer, DURING)
    assert _state(hass, "text", "plate_draft") == "AA11BB"

    # The booking is replaced elsewhere, and the next poll reports the new plate.
    aioclient_mock.clear_requests()
    _register_reads(
        aioclient_mock, build_account_payload(reservation=BOOKING, plate="HH66II")
    )
    freezer.tick(300)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert _state(hass, "text", "plate_draft") == "HH66II"


async def test_plate_field_keeps_the_plate_after_the_booking_ends(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """The plate you just used stays available for the next booking."""
    _register_reads(aioclient_mock, build_account_payload(reservation=BOOKING))
    await _setup(hass, account_entry, freezer, DURING)

    aioclient_mock.clear_requests()
    _register_reads(aioclient_mock, build_account_payload())
    freezer.tick(300)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert _state(hass, "text", "plate_draft") == "AA11BB"


async def test_plate_field_restores_a_draft_across_a_reload(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """A typed plate survives a restart of the integration."""
    _register_reads(aioclient_mock, build_account_payload())
    await _setup(hass, account_entry, freezer, IDLE)
    await _set_plate(hass, "JJ77KK")

    assert await hass.config_entries.async_reload(account_entry.entry_id)
    await hass.async_block_till_done()

    assert _state(hass, "text", "plate_draft") == "JJ77KK"
