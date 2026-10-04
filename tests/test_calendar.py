"""Tests for the calendar entity and the panel commands that edit it.

Home Assistant's Calendar panel does not change an event through a service: it
sends the ``calendar/event/create|delete|update`` websocket commands. Those are
what these tests drive, so they exercise the path a user's tap takes.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import CLIENT_ID, MockConfigEntry

from custom_components.zwolle_parkeerloket.const import API_BASE_URL

from .helpers import (
    GETBASE_URL,
    LOGIN_URL,
    as_write_response,
    build_account_payload,
    entity_id_for,
    reservation_payload,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

UPDATE_URL = f"{API_BASE_URL}/api/reservation/update"
END_URL = f"{API_BASE_URL}/api/reservation/end"

IDLE = "2026-10-05T07:00:00+00:00"
DURING = "2026-10-05T08:15:00+00:00"

# The portal stores a booking's window to the microsecond, while the Calendar panel
# carries it through a JavaScript date, which keeps only milliseconds. A field the
# user did not touch therefore comes back as the stored value with the last three
# digits dropped, which is what these two constants are for: the tests that edit a
# booking send them for the fields the user left alone.
START = "2026-10-05T08:00:26.142660+00:00"
END = "2026-10-05T08:30:26.142660+00:00"
START_UNTOUCHED = "2026-10-05T08:00:26.142+00:00"
END_UNTOUCHED = "2026-10-05T08:30:26.142+00:00"


def _mock_portal(aioclient_mock: Any, payload: dict[str, Any]) -> None:
    """Answer reads with the payload and every write with its permit."""
    aioclient_mock.post(LOGIN_URL, json=payload)
    aioclient_mock.post(GETBASE_URL, json=payload)
    response = as_write_response(payload)
    aioclient_mock.post(UPDATE_URL, json=response)
    aioclient_mock.post(END_URL, json=response)


async def _setup(
    hass: HomeAssistant, entry: MockConfigEntry, freezer: Any, moment: str
) -> None:
    """Add the entry and set it up at a frozen moment."""
    freezer.move_to(moment)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _calendar_id(hass: HomeAssistant) -> str:
    """Return the entity id of the calendar."""
    entity_id = entity_id_for(hass, "calendar", "calendar")
    assert entity_id is not None
    return entity_id


async def _events(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return the events the calendar reports, through its own service."""
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": _calendar_id(hass),
            "start_date_time": "2026-10-05T00:00:00+00:00",
            "end_date_time": "2026-10-06T00:00:00+00:00",
        },
        blocking=True,
        return_response=True,
    )
    return response[_calendar_id(hass)]["events"]


async def _command(
    hass: HomeAssistant,
    hass_ws_client: Any,
    user: Any,
    message: dict[str, Any],
) -> dict[str, Any]:
    """Send one Calendar panel command and return its reply.

    The access token is minted here rather than taken from the fixture: Home
    Assistant gives access tokens a 30-minute lifetime, and these tests run with
    the clock moved to a fixed day, so a token made at fixture time has already
    expired by the time the test connects.
    """
    refresh_token = await hass.auth.async_create_refresh_token(
        user, CLIENT_ID, access_token_expiration=timedelta(days=1)
    )
    client = await hass_ws_client(
        hass, access_token=hass.auth.async_create_access_token(refresh_token)
    )
    await client.send_json({"id": 1, **message})
    reply = await client.receive_json()
    await client.close()
    return reply


def _requests(aioclient_mock: Any, url: str) -> list[dict[str, Any]]:
    """Return the bodies of every request made to one URL."""
    return [
        data
        for _method, request_url, data, _headers in aioclient_mock.mock_calls
        if str(request_url) == url
    ]


def _event(*, start: str, end: str, summary: str = "AA11BB") -> dict[str, Any]:
    """Return the event body the panel sends when an event is edited.

    The panel always sends both ends of the window, so a test that changes one of
    them passes the untouched value for the other.
    """
    return {"dtstart": start, "dtend": end, "summary": summary}


async def test_calendar_lists_every_booking(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """Each reservation is an event, addressed by the portal's reservation id."""
    other = reservation_payload(
        reservation_id=555002, plate="CC22DD", valid_from=START, valid_until=END
    )
    payload = build_account_payload(reservation=(START, END), also_reserved=[other])
    _mock_portal(aioclient_mock, payload)
    await _setup(hass, account_entry, freezer, DURING)

    events = await _events(hass)

    assert [event["summary"] for event in events] == ["AA11BB", "CC22DD"]
    assert [event["start"] for event in events] == [START, START]
    assert [event["end"] for event in events] == [END, END]
    assert [event["location"] for event in events] == ["ZONE1", "ZONE1"]
    # The uid is what the panel uses to address an event when editing it; it is
    # deliberately not part of the listing, so it is checked where it is used.
    assert "Reservation 555001" in events[0]["description"]


async def test_calendar_reports_the_booking_that_matters_now(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """The calendar is on while a car is parked, and shows the zone."""
    _mock_portal(aioclient_mock, build_account_payload(reservation=(START, END)))
    await _setup(hass, account_entry, freezer, DURING)

    state = hass.states.get(_calendar_id(hass))

    assert state is not None
    assert state.state == "on"
    assert state.attributes["message"] == "AA11BB"
    assert state.attributes["location"] == "ZONE1"


async def test_calendar_is_off_with_nothing_booked(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
) -> None:
    """An empty account has no events and a calendar that is off."""
    _mock_portal(aioclient_mock, build_account_payload())
    await _setup(hass, account_entry, freezer, IDLE)

    assert hass.states.get(_calendar_id(hass)).state == "off"
    assert await _events(hass) == []


async def test_deleting_an_event_cancels_that_reservation(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
    hass_ws_client: Any,
    hass_admin_user: Any,
) -> None:
    """Cancelling from the panel ends the car the event belongs to."""
    other = reservation_payload(
        reservation_id=555002, plate="CC22DD", valid_from=START, valid_until=END
    )
    payload = build_account_payload(reservation=(START, END), also_reserved=[other])
    _mock_portal(aioclient_mock, payload)
    await _setup(hass, account_entry, freezer, DURING)

    reply = await _command(
        hass,
        hass_ws_client,
        hass_admin_user,
        {
            "type": "calendar/event/delete",
            "entity_id": _calendar_id(hass),
            "uid": "555002",
        },
    )

    assert reply["success"] is True, reply
    assert _requests(aioclient_mock, END_URL)[0]["ReservationID"] == 555002


async def test_resizing_an_event_changes_the_duration(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
    hass_ws_client: Any,
    hass_admin_user: Any,
) -> None:
    """The portal takes a number of minutes, so a new end time becomes a delta.

    This is the case a user hits: the end is dragged to a later time while the
    start is left alone. The start still comes back through the panel one
    sub-millisecond short of what the portal stored, which must not be mistaken
    for the booking having been moved.
    """
    _mock_portal(aioclient_mock, build_account_payload(reservation=(START, END)))
    await _setup(hass, account_entry, freezer, DURING)

    reply = await _command(
        hass,
        hass_ws_client,
        hass_admin_user,
        {
            "type": "calendar/event/update",
            "entity_id": _calendar_id(hass),
            "uid": "555001",
            "event": _event(start=START_UNTOUCHED, end="2026-10-05T09:00:00+00:00"),
        },
    )

    assert reply["success"] is True, reply
    body = _requests(aioclient_mock, UPDATE_URL)[0]
    assert body["Minutes"] == 30
    assert body["ReservationID"] == 555001


async def test_a_booking_can_be_extended_by_a_whole_hour(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
    hass_ws_client: Any,
    hass_admin_user: Any,
) -> None:
    """An added hour is sent as sixty minutes, not fifty-nine.

    The stored end carries seconds the panel cannot show, so the difference has to
    be rounded back to the minute the user actually picked.
    """
    _mock_portal(aioclient_mock, build_account_payload(reservation=(START, END)))
    await _setup(hass, account_entry, freezer, DURING)

    reply = await _command(
        hass,
        hass_ws_client,
        hass_admin_user,
        {
            "type": "calendar/event/update",
            "entity_id": _calendar_id(hass),
            "uid": "555001",
            "event": _event(start=START_UNTOUCHED, end="2026-10-05T09:30:00+00:00"),
        },
    )

    assert reply["success"] is True, reply
    assert _requests(aioclient_mock, UPDATE_URL)[0]["Minutes"] == 60


async def test_resizing_lands_exactly_on_the_minute_the_user_picked(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
    hass_ws_client: Any,
    hass_admin_user: Any,
) -> None:
    """The delta is measured from the minute the panel showed, not from the seconds.

    The panel displays 08:30 for a booking stored until 08:30:40, so asking it for
    09:00 is half an hour. Measuring from the stored seconds would send 29 minutes
    and leave the booking ending a minute earlier than the user asked for.
    """
    late_seconds = ("2026-10-05T08:00:40.142660Z", "2026-10-05T08:30:40.142660Z")
    _mock_portal(aioclient_mock, build_account_payload(reservation=late_seconds))
    await _setup(hass, account_entry, freezer, DURING)

    reply = await _command(
        hass,
        hass_ws_client,
        hass_admin_user,
        {
            "type": "calendar/event/update",
            "entity_id": _calendar_id(hass),
            "uid": "555001",
            "event": _event(
                start="2026-10-05T08:00:40.142+00:00",
                end="2026-10-05T09:00:00+00:00",
            ),
        },
    )

    assert reply["success"] is True, reply
    assert _requests(aioclient_mock, UPDATE_URL)[0]["Minutes"] == 30


async def test_saving_without_changing_anything_leaves_the_booking_alone(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
    hass_ws_client: Any,
    hass_admin_user: Any,
) -> None:
    """The panel sends both ends even when nothing was edited.

    Both ends come back with the microseconds dropped, which is a difference too
    small to be a change and must not be turned into a portal call.
    """
    _mock_portal(aioclient_mock, build_account_payload(reservation=(START, END)))
    await _setup(hass, account_entry, freezer, DURING)

    reply = await _command(
        hass,
        hass_ws_client,
        hass_admin_user,
        {
            "type": "calendar/event/update",
            "entity_id": _calendar_id(hass),
            "uid": "555001",
            "event": _event(start=START_UNTOUCHED, end=END_UNTOUCHED),
        },
    )

    assert reply["success"] is True, reply
    assert not _requests(aioclient_mock, UPDATE_URL)


async def test_shrinking_an_event_shortens_the_booking(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
    hass_ws_client: Any,
    hass_admin_user: Any,
) -> None:
    """A shorter end time is a negative delta."""
    longer = ("2026-10-05T08:00:26.142660Z", "2026-10-05T09:00:26.142660Z")
    _mock_portal(aioclient_mock, build_account_payload(reservation=longer))
    await _setup(hass, account_entry, freezer, DURING)

    reply = await _command(
        hass,
        hass_ws_client,
        hass_admin_user,
        {
            "type": "calendar/event/update",
            "entity_id": _calendar_id(hass),
            "uid": "555001",
            "event": _event(start=START_UNTOUCHED, end="2026-10-05T08:30:00+00:00"),
        },
    )

    assert reply["success"] is True, reply
    assert _requests(aioclient_mock, UPDATE_URL)[0]["Minutes"] == -30


async def test_moving_an_event_is_refused(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
    hass_ws_client: Any,
    hass_admin_user: Any,
) -> None:
    """A booking cannot start earlier or later, so a dragged start is rejected.

    The portal only adjusts how long a reservation lasts; letting the panel appear
    to move it would leave the display disagreeing with the portal. A minute is the
    smallest move the panel can express, and it is well clear of the sub-second
    difference an untouched field produces.
    """
    _mock_portal(aioclient_mock, build_account_payload(reservation=(START, END)))
    await _setup(hass, account_entry, freezer, DURING)

    reply = await _command(
        hass,
        hass_ws_client,
        hass_admin_user,
        {
            "type": "calendar/event/update",
            "entity_id": _calendar_id(hass),
            "uid": "555001",
            "event": _event(start="2026-10-05T08:01:26.142+00:00", end=END_UNTOUCHED),
        },
    )

    assert reply["success"] is False, reply
    assert not _requests(aioclient_mock, UPDATE_URL)


async def test_renaming_an_event_is_refused(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
    hass_ws_client: Any,
    hass_admin_user: Any,
) -> None:
    """The event title is the licence plate, which cannot be changed in place."""
    _mock_portal(aioclient_mock, build_account_payload(reservation=(START, END)))
    await _setup(hass, account_entry, freezer, DURING)

    reply = await _command(
        hass,
        hass_ws_client,
        hass_admin_user,
        {
            "type": "calendar/event/update",
            "entity_id": _calendar_id(hass),
            "uid": "555001",
            "event": _event(
                start=START_UNTOUCHED, end=END_UNTOUCHED, summary="Something else"
            ),
        },
    )

    assert reply["success"] is False, reply
    assert not _requests(aioclient_mock, UPDATE_URL)


async def test_a_change_of_less_than_a_minute_is_treated_as_no_change(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
    hass_ws_client: Any,
    hass_admin_user: Any,
) -> None:
    """An end the panel cannot express as a change is not sent to the portal.

    The panel works in whole minutes, so an end that lands within the same minute
    as the stored one cannot be what the user meant, and asking the portal for a
    zero-minute change would only be rejected.
    """
    _mock_portal(aioclient_mock, build_account_payload(reservation=(START, END)))
    await _setup(hass, account_entry, freezer, DURING)

    reply = await _command(
        hass,
        hass_ws_client,
        hass_admin_user,
        {
            "type": "calendar/event/update",
            "entity_id": _calendar_id(hass),
            "uid": "555001",
            "event": _event(start=START_UNTOUCHED, end="2026-10-05T08:30:05+00:00"),
        },
    )

    assert reply["success"] is True, reply
    assert not _requests(aioclient_mock, UPDATE_URL)


async def test_an_unknown_uid_is_refused(
    hass: HomeAssistant,
    aioclient_mock: Any,
    account_entry: MockConfigEntry,
    freezer: Any,
    hass_ws_client: Any,
    hass_admin_user: Any,
) -> None:
    """An event the portal no longer lists cannot be acted on."""
    _mock_portal(aioclient_mock, build_account_payload(reservation=(START, END)))
    await _setup(hass, account_entry, freezer, DURING)

    reply = await _command(
        hass,
        hass_ws_client,
        hass_admin_user,
        {
            "type": "calendar/event/delete",
            "entity_id": _calendar_id(hass),
            "uid": "999999",
        },
    )

    assert reply["success"] is False, reply
    assert not _requests(aioclient_mock, END_URL)
