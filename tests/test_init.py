"""Tests for setting up, updating and unloading a config entry."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zwolle_parkeerloket.const import (
    CONF_PINCODE,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)

from .helpers import (
    GETBASE_URL,
    LOGIN_URL,
    MELDNUMMER,
    PINCODE,
    load_fixture,
    posted_login_payloads,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_setup_loads_the_account(
    hass: HomeAssistant, mocked_portal: Any, account_entry: MockConfigEntry
) -> None:
    """Setting up an entry logs in and reads the account once."""
    account_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(account_entry.entry_id)
    await hass.async_block_till_done()

    assert account_entry.state is ConfigEntryState.LOADED
    data = account_entry.runtime_data.data
    assert data.media.balance == 7140
    assert data.media.zone_code == "ZONE1"
    assert data.media.code == MELDNUMMER


async def test_setup_logs_in_before_reading(
    hass: HomeAssistant, mocked_portal: Any, account_entry: MockConfigEntry
) -> None:
    """The login happens first, then the single consolidated read call."""
    account_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(account_entry.entry_id)
    await hass.async_block_till_done()

    paths = [str(url) for _method, url, _payload, _headers in mocked_portal.mock_calls]
    assert paths == [LOGIN_URL, GETBASE_URL]
    assert posted_login_payloads(mocked_portal)[0]["password"] == PINCODE


async def test_unload_entry(
    hass: HomeAssistant, mocked_portal: Any, account_entry: MockConfigEntry
) -> None:
    """An entry can be unloaded again, unloading its platforms."""
    account_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(account_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(account_entry.entry_id)
    await hass.async_block_till_done()

    assert account_entry.state is ConfigEntryState.NOT_LOADED


async def test_reload_picks_up_new_options(
    hass: HomeAssistant, mocked_portal: Any, account_entry: MockConfigEntry
) -> None:
    """Reloading after an options change re-reads the portal."""
    account_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(account_entry.entry_id)
    await hass.async_block_till_done()

    hass.config_entries.async_update_entry(
        account_entry, options={CONF_SCAN_INTERVAL: 2}
    )
    assert await hass.config_entries.async_reload(account_entry.entry_id)
    await hass.async_block_till_done()

    assert account_entry.state is ConfigEntryState.LOADED
    assert account_entry.runtime_data.update_interval.total_seconds() == 120


async def test_rejected_credentials_start_reauthentication(
    hass: HomeAssistant, aioclient_mock: Any, account_entry: MockConfigEntry
) -> None:
    """A rejected login fails the setup and offers reauthentication."""
    aioclient_mock.post(LOGIN_URL, json=load_fixture("login_rejected.json"))
    account_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(account_entry.entry_id)
    await hass.async_block_till_done()

    assert account_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_unreachable_portal_is_retried(
    hass: HomeAssistant, aioclient_mock: Any, account_entry: MockConfigEntry
) -> None:
    """An unreachable portal leaves the entry in setup-retry, not in error."""
    aioclient_mock.post(LOGIN_URL, exc=aiohttp.ClientConnectionError)
    account_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(account_entry.entry_id)
    await hass.async_block_till_done()

    assert account_entry.state is ConfigEntryState.SETUP_RETRY


async def test_reauthentication_clears_the_error(
    hass: HomeAssistant, aioclient_mock: Any, account_entry: MockConfigEntry
) -> None:
    """Completing the reauth flow loads the entry again."""
    payload = load_fixture("account_active_reservation.json")

    aioclient_mock.post(LOGIN_URL, json=load_fixture("login_rejected.json"))
    account_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(account_entry.entry_id)
    await hass.async_block_till_done()
    assert account_entry.state is ConfigEntryState.SETUP_ERROR

    # The portal accepts the new Pincode.
    aioclient_mock.clear_requests()
    aioclient_mock.post(LOGIN_URL, json=payload)
    aioclient_mock.post(GETBASE_URL, json=payload)

    flow = hass.config_entries.flow.async_progress_by_handler(DOMAIN)[0]
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_PINCODE: "new-pin"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert account_entry.state is ConfigEntryState.LOADED
    assert account_entry.data[CONF_PINCODE] == "new-pin"
