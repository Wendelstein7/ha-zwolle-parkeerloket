"""Shared pytest fixtures for the zwolle_parkeerloket tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import aiohttp
import pytest
from aiohttp.test_utils import TestServer
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zwolle_parkeerloket.api import DVSPortalClient
from custom_components.zwolle_parkeerloket.const import DOMAIN

from .fake_portal import FakePortal
from .helpers import (
    GETBASE_URL,
    LOGIN_URL,
    MELDNUMMER,
    PINCODE,
    account_data,
    account_title,
    load_fixture,
)


@pytest.fixture
def account_payload() -> dict[str, Any]:
    """Return an account carrying one reservation and two saved plates."""
    return load_fixture("account_active_reservation.json")


# --- fixtures for the Home Assistant independent API layer -------------------


@pytest.fixture
async def fake_portal(account_payload: dict[str, Any]) -> AsyncIterator[FakePortal]:
    """Run a fake portal on ``127.0.0.1`` and yield the controller for it.

    Two test-harness accommodations, neither of which affects what is under test:

    * the Home Assistant harness restricts real sockets to ``127.0.0.1``, so the
      server is not reachable over the IPv6 ``::1`` address that ``localhost``
      resolves to first;
    * aiohttp discards cookies from an IP-literal host unless the jar is
      ``unsafe=True``, so the client fixture opts in. The integration itself uses a
      normal jar against the portal's real hostname.
    """
    portal = FakePortal(account_payload)
    server = TestServer(portal.build_app(), host="127.0.0.1")
    await server.start_server()
    portal.base_url = str(server.make_url("/")).rstrip("/")
    try:
        yield portal
    finally:
        await server.close()


@pytest.fixture
async def client(fake_portal: FakePortal) -> AsyncIterator[DVSPortalClient]:
    """Return a client pointed at the fake portal, with a cookie jar of its own."""
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
    try:
        yield DVSPortalClient(
            session,
            meldnummer=MELDNUMMER,
            pincode=PINCODE,
            base_url=fake_portal.api_url,
        )
    finally:
        await session.close()


# --- fixtures for the Home Assistant layer ----------------------------------


@pytest.fixture
def mocked_portal(aioclient_mock: Any, account_payload: dict[str, Any]) -> Any:
    """Answer the portal's two endpoints from Home Assistant's mocked session."""
    aioclient_mock.post(LOGIN_URL, json=account_payload)
    aioclient_mock.post(GETBASE_URL, json=account_payload)
    return aioclient_mock


@pytest.fixture
def account_entry() -> MockConfigEntry:
    """Return a config entry for the test account."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=account_title(),
        unique_id=MELDNUMMER,
        data=account_data(),
    )
