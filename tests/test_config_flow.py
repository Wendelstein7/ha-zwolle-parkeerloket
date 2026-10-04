"""Tests for the config, reauth and options flows."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zwolle_parkeerloket.const import (
    CONF_PINCODE,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)

from .helpers import (
    LOGIN_URL,
    MELDNUMMER,
    PINCODE,
    account_data,
    account_title,
    load_fixture,
    posted_login_payloads,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def _start_user_flow(hass: HomeAssistant) -> dict[str, Any]:
    """Start the user step and return the form it shows."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_user_flow_shows_a_form(hass: HomeAssistant) -> None:
    """The first step asks for the Meldnummer and Pincode."""
    result = await _start_user_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_user_flow_creates_the_entry(
    hass: HomeAssistant, mocked_portal: Any
) -> None:
    """Correct credentials create an entry holding them."""
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], account_data()
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == account_title()
    assert result["data"] == account_data()
    assert result["result"].unique_id == MELDNUMMER


async def test_user_flow_sends_the_documented_login_body(
    hass: HomeAssistant, mocked_portal: Any
) -> None:
    """The credentials must be posted the way the portal's own web app does it."""
    result = await _start_user_flow(hass)
    await hass.config_entries.flow.async_configure(result["flow_id"], account_data())
    await hass.async_block_till_done()

    payload = posted_login_payloads(mocked_portal)[0]
    assert payload["identifier"] == MELDNUMMER
    assert payload["password"] == PINCODE
    assert payload["loginMethod"] == 2
    assert payload["permitMediaTypeID"] == 9


async def test_user_flow_rejects_bad_credentials(
    hass: HomeAssistant, aioclient_mock: Any
) -> None:
    """A rejected login points at the credentials instead of creating an entry."""
    aioclient_mock.post(LOGIN_URL, json=load_fixture("login_rejected.json"))

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], account_data()
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_auth"}
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_user_flow_reports_connection_problems(
    hass: HomeAssistant, aioclient_mock: Any
) -> None:
    """An unreachable portal is reported as a connection problem."""
    aioclient_mock.post(LOGIN_URL, exc=aiohttp.ClientConnectionError)

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], account_data()
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_aborts_for_a_known_meldnummer(
    hass: HomeAssistant, mocked_portal: Any, account_entry: MockConfigEntry
) -> None:
    """The same Meldnummer cannot be added twice."""
    account_entry.add_to_hass(hass)

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], account_data()
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_reauth_flow_updates_the_pincode(
    hass: HomeAssistant, mocked_portal: Any, account_entry: MockConfigEntry
) -> None:
    """A new Pincode is verified and stored."""
    account_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": account_entry.entry_id,
        },
        data=account_entry.data,
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PINCODE: "new-pin"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert account_entry.data[CONF_PINCODE] == "new-pin"


async def test_reauth_flow_rejects_a_bad_pincode(
    hass: HomeAssistant, aioclient_mock: Any, account_entry: MockConfigEntry
) -> None:
    """A wrong Pincode keeps the reauth form open."""
    account_entry.add_to_hass(hass)
    aioclient_mock.post(LOGIN_URL, json=load_fixture("login_rejected.json"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": account_entry.entry_id,
        },
        data=account_entry.data,
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PINCODE: "wrong"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert account_entry.data[CONF_PINCODE] == PINCODE


async def test_options_flow_stores_the_scan_interval(
    hass: HomeAssistant, mocked_portal: Any, account_entry: MockConfigEntry
) -> None:
    """The options flow only configures the polling interval."""
    account_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(account_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(account_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 15}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert account_entry.options[CONF_SCAN_INTERVAL] == 15
    assert account_entry.state is ConfigEntryState.LOADED


async def test_options_default_is_used_when_unset(
    hass: HomeAssistant, mocked_portal: Any, account_entry: MockConfigEntry
) -> None:
    """Without options the default polling interval applies."""
    account_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(account_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(account_entry.entry_id)

    assert result["data_schema"]({}) == {
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL_MINUTES
    }
