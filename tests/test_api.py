"""Tests for the Home Assistant independent Parkeerloket client.

These tests run against a local fake portal over aiohttp, without any Home
Assistant fixture, so the API layer stays verifiably standalone.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from yarl import URL

from custom_components.zwolle_parkeerloket import api as api_module
from custom_components.zwolle_parkeerloket.api import (
    SESSION_COOKIE,
    XSRF_COOKIE,
    XSRF_HEADER,
    ApiError,
    CannotConnect,
    DVSPortalClient,
    InvalidAuth,
)

from .fake_portal import HTML_ERROR, FakePortal, json_response_factory, response_factory
from .helpers import MELDNUMMER, PINCODE, load_fixture

# The Home Assistant test harness ships pytest-socket, which blocks real network
# sockets. These tests talk to a local fake portal on purpose, so they opt out.
pytestmark = pytest.mark.usefixtures("socket_enabled")


@asynccontextmanager
async def client_at(base_url: str) -> AsyncIterator[DVSPortalClient]:
    """Yield a client with its own cookie jar, pointed at ``base_url``."""
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
    try:
        yield DVSPortalClient(
            session, meldnummer=MELDNUMMER, pincode=PINCODE, base_url=base_url
        )
    finally:
        await session.close()


async def test_login_returns_the_account(
    client: DVSPortalClient, fake_portal: FakePortal
) -> None:
    """A successful login yields the account state from the login response."""
    account = await client.async_login()

    assert client.logged_in is True
    assert fake_portal.login_calls == 1
    assert [media.code for media in account.media] == [MELDNUMMER]
    assert account.media[0].balance == 7140


async def test_login_sends_the_documented_payload(
    client: DVSPortalClient, fake_portal: FakePortal
) -> None:
    """The login body must match what the portal's own web app sends."""
    await client.async_login()

    body = fake_portal.received_login_bodies[0]
    assert body["identifier"] == MELDNUMMER
    assert body["password"] == PINCODE
    assert body["loginMethod"] == 2
    assert body["permitMediaTypeID"] == 9
    assert body["otp"] is None
    assert body["resetCode"] is None
    assert body["asIdentifier"] is None
    assert body["zipCode"] is None


async def test_login_rejection_raises_invalid_auth(
    client: DVSPortalClient, fake_portal: FakePortal
) -> None:
    """The portal rejects credentials with HTTP 200 and an error body."""
    fake_portal.login_rejection = load_fixture("login_rejected.json")

    with pytest.raises(InvalidAuth, match="nummer of de pincode"):
        await client.async_login()

    assert client.logged_in is False


async def test_login_without_permit_data_is_invalid_auth(
    client: DVSPortalClient, fake_portal: FakePortal
) -> None:
    """A login response without permits is not treated as a success."""
    fake_portal.login_rejection = {"LoginStatus": 1}

    with pytest.raises(InvalidAuth):
        await client.async_login()


async def test_get_account_returns_balance_and_reservations(
    client: DVSPortalClient,
) -> None:
    """``getbase`` is the single read call and carries balance plus reservations."""
    await client.async_login()
    account = await client.async_get_account()

    media = account.media[0]
    assert media.balance == 7140
    assert media.zone_code == "ZONE1"
    assert len(media.reservations) == 1
    assert media.reservations[0].license_plate is not None
    assert media.reservations[0].license_plate.value == "AA11BB"
    assert len(media.license_plates) == 2


async def test_csrf_token_is_sent_and_rotated(
    client: DVSPortalClient, fake_portal: FakePortal
) -> None:
    """Every call carries the CSRF header, and a re-login re-reads the new token."""
    await client.async_login()
    await client.async_get_account()

    # The login itself happens without a token; the authenticated call must have one.
    assert fake_portal.received_xsrf[0] is None
    assert fake_portal.received_xsrf[1] == "csrf-token-1"

    fake_portal.expire_sessions()
    await client.async_get_account()

    assert fake_portal.login_calls == 2
    assert fake_portal.received_xsrf[-1] == "csrf-token-2"


async def test_stale_session_is_recovered_with_one_login(
    client: DVSPortalClient, fake_portal: FakePortal
) -> None:
    """A stale session answers 500 + HTML; the client logs in again and retries once."""
    await client.async_login()
    fake_portal.expire_sessions()

    account = await client.async_get_account()

    assert account.media[0].balance == 7140
    assert fake_portal.login_calls == 2
    assert fake_portal.getbase_calls == 2


async def test_repeated_failure_does_not_loop(
    client: DVSPortalClient, fake_portal: FakePortal
) -> None:
    """When the retry fails too, the client gives up instead of logging in forever."""
    await client.async_login()
    fake_portal.getbase_override = response_factory(500, "text/html", HTML_ERROR)

    with pytest.raises(CannotConnect):
        await client.async_get_account()

    # One initial login plus exactly one re-login, and exactly one retry.
    assert fake_portal.login_calls == 2
    assert fake_portal.getbase_calls == 2


async def test_unauthorized_is_treated_as_a_stale_session(
    client: DVSPortalClient, fake_portal: FakePortal
) -> None:
    """A 401 also triggers exactly one re-login attempt."""
    await client.async_login()
    fake_portal.getbase_override = response_factory(
        401, "application/problem+json", "{}"
    )

    with pytest.raises(CannotConnect):
        await client.async_get_account()

    assert fake_portal.login_calls == 2


async def test_business_error_raises_api_error(
    client: DVSPortalClient, fake_portal: FakePortal
) -> None:
    """A business error reported with HTTP 200 becomes an ``ApiError``."""
    await client.async_login()
    fake_portal.getbase_override = json_response_factory(
        load_fixture("business_error.json")
    )

    with pytest.raises(ApiError) as err:
        await client.async_get_account()

    assert err.value.result == 13


async def test_non_json_success_is_an_api_error(
    client: DVSPortalClient, fake_portal: FakePortal
) -> None:
    """A 200 answer that is not JSON must not be mistaken for account data."""
    await client.async_login()
    fake_portal.getbase_override = response_factory(200, "text/html", HTML_ERROR)

    with pytest.raises(ApiError, match="non-JSON"):
        await client.async_get_account()


async def test_unreachable_portal_raises_cannot_connect() -> None:
    """A connection error must surface as ``CannotConnect``, not a raw aiohttp error."""
    async with client_at("http://127.0.0.1:1/DVSPortal") as offline:
        with pytest.raises(CannotConnect):
            await offline.async_login()


async def test_timeout_raises_cannot_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    """A portal that never answers must surface as ``CannotConnect``."""

    async def slow_handler(_: web.Request) -> web.Response:
        await asyncio.sleep(10)
        return web.Response()

    app = web.Application()
    app.router.add_post("/DVSPortal/api/login", slow_handler)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    monkeypatch.setattr(api_module, "API_TIMEOUT_SECONDS", 0.05)
    try:
        base_url = f"{str(server.make_url('/')).rstrip('/')}/DVSPortal"
        async with client_at(base_url) as slow_client:
            with pytest.raises(CannotConnect, match="timeout"):
                await slow_client.async_login()
    finally:
        await server.close()


async def test_cookies_are_kept_in_the_injected_session(
    client: DVSPortalClient, fake_portal: FakePortal
) -> None:
    """The session and CSRF cookies belong to the caller's session, not the client."""
    await client.async_login()

    cookies = client._session.cookie_jar.filter_cookies(URL(fake_portal.api_url))
    assert SESSION_COOKIE in cookies
    assert XSRF_COOKIE in cookies
    assert XSRF_HEADER == "X-XSRF-TOKEN"


# --- booking actions ---------------------------------------------------------


@pytest.fixture
def empty_portal(fake_portal: FakePortal) -> FakePortal:
    """Start from an account with nothing booked.

    The default fixture mirrors a live account that already has a reservation, so
    the write tests clear it to keep their expectations about *their own* booking
    unambiguous.
    """
    fake_portal.media["ActiveReservations"].clear()
    return fake_portal


async def test_create_reservation_sends_the_documented_body(
    client: DVSPortalClient, fake_portal: FakePortal
) -> None:
    """The booking body must match the one the portal's own web app sends."""
    await client.async_login()
    await client.async_create_reservation(MELDNUMMER, "AA11BB", "Visitor one")

    body = fake_portal.writes_to(fake_portal.create_path)[0]
    assert body["permitMediaTypeID"] == 9
    assert body["permitMediaCode"] == MELDNUMMER
    assert body["LicensePlate"] == {"Value": "AA11BB", "Name": "Visitor one"}
    # The dates are omitted on purpose: the portal then books from now for its own
    # default duration, and an explicit start of "now" could be rejected as past.
    assert "DateFrom" not in body
    assert "DateUntil" not in body


async def test_create_reservation_returns_the_updated_permit(
    client: DVSPortalClient, empty_portal: FakePortal
) -> None:
    """A write answers with the updated permit, so no extra poll is needed."""
    await client.async_login()

    response = await client.async_create_reservation(MELDNUMMER, "AA11BB")

    assert "Permit" in response
    reservations = response["Permit"]["PermitMedias"][0]["ActiveReservations"]
    assert [item["LicensePlate"]["Value"] for item in reservations] == ["AA11BB"]


async def test_create_reservation_rejection_raises_api_error(
    client: DVSPortalClient, fake_portal: FakePortal
) -> None:
    """A rejected booking is an error even though the portal answers HTTP 200."""
    await client.async_login()
    fake_portal.create_rejection = load_fixture("business_error.json")

    with pytest.raises(ApiError) as err:
        await client.async_create_reservation(MELDNUMMER, "AA11BB")

    assert err.value.result == 13
    assert "starttijd" in str(err.value)


async def test_update_reservation_sends_a_signed_delta(
    client: DVSPortalClient, fake_portal: FakePortal, empty_portal: FakePortal
) -> None:
    """Extending and shortening are both a signed Minutes delta."""
    await client.async_login()
    created = await client.async_create_reservation(MELDNUMMER, "AA11BB")
    reservation_id = created["Permit"]["PermitMedias"][0]["ActiveReservations"][0][
        "ReservationID"
    ]

    await client.async_update_reservation(MELDNUMMER, reservation_id, 30)
    await client.async_update_reservation(MELDNUMMER, reservation_id, -30)

    first, second = fake_portal.writes_to(fake_portal.update_path)
    assert first["Minutes"] == 30
    assert second["Minutes"] == -30
    assert first["ReservationID"] == reservation_id
    assert first["permitMediaTypeID"] == 9
    assert first["permitMediaCode"] == MELDNUMMER


async def test_update_reservation_rejection_raises_api_error(
    client: DVSPortalClient, fake_portal: FakePortal, empty_portal: FakePortal
) -> None:
    """The portal's own rejection of a change surfaces as an error."""
    await client.async_login()
    created = await client.async_create_reservation(MELDNUMMER, "AA11BB")
    reservation_id = created["Permit"]["PermitMedias"][0]["ActiveReservations"][0][
        "ReservationID"
    ]
    fake_portal.update_rejection = load_fixture("business_error.json")

    with pytest.raises(ApiError) as err:
        await client.async_update_reservation(MELDNUMMER, reservation_id, -600)

    assert err.value.result == 13


async def test_end_reservation_sends_the_id(
    client: DVSPortalClient, fake_portal: FakePortal, empty_portal: FakePortal
) -> None:
    """Cancelling only needs the reservation id and the permit medium."""
    await client.async_login()
    created = await client.async_create_reservation(MELDNUMMER, "AA11BB")
    reservation_id = created["Permit"]["PermitMedias"][0]["ActiveReservations"][0][
        "ReservationID"
    ]

    response = await client.async_end_reservation(MELDNUMMER, reservation_id)

    assert fake_portal.writes_to(fake_portal.end_path) == [
        {
            "ReservationID": reservation_id,
            "permitMediaTypeID": 9,
            "permitMediaCode": MELDNUMMER,
        }
    ]
    assert response["Permit"]["PermitMedias"][0]["ActiveReservations"] == []


async def test_writes_reuse_a_session_that_expired(
    client: DVSPortalClient, fake_portal: FakePortal, empty_portal: FakePortal
) -> None:
    """A write after a session timeout logs in again and still succeeds."""
    await client.async_login()
    fake_portal.expire_sessions()

    response = await client.async_create_reservation(MELDNUMMER, "AA11BB")

    assert fake_portal.login_calls == 2
    assert response["Permit"]["PermitMedias"][0]["ActiveReservations"]


async def test_write_against_a_dead_session_fails(
    client: DVSPortalClient, fake_portal: FakePortal, empty_portal: FakePortal
) -> None:
    """When the retry cannot recover either, the failure is reported, not looped."""
    await client.async_login()
    fake_portal.expire_sessions()
    fake_portal.login_rejection = load_fixture("login_rejected.json")

    with pytest.raises(InvalidAuth):
        await client.async_create_reservation(MELDNUMMER, "AA11BB")

    assert fake_portal.login_calls == 2
