"""Config and options flow for the Zwolle Parkeerloket integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import ApiError, CannotConnect, InvalidAuth
from .client import async_create_client
from .const import (
    CONF_MELDNUMMER,
    CONF_PINCODE,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
    NAME,
)

_MELDNUMMER_SELECTOR = TextSelector(TextSelectorConfig(autocomplete="username"))
_PINCODE_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
)


def _user_schema() -> vol.Schema:
    """Return the schema asking for both credentials."""
    return vol.Schema(
        {
            vol.Required(CONF_MELDNUMMER): _MELDNUMMER_SELECTOR,
            vol.Required(CONF_PINCODE): _PINCODE_SELECTOR,
        }
    )


def _reauth_schema() -> vol.Schema:
    """Return the schema asking only for the Pincode, since the Meldnummer is fixed."""
    return vol.Schema({vol.Required(CONF_PINCODE): _PINCODE_SELECTOR})


async def _async_validate_credentials(
    hass: HomeAssistant, data: Mapping[str, Any]
) -> dict[str, str]:
    """Log in with the given credentials and translate failures into form errors."""
    client = async_create_client(hass, data)
    try:
        await client.async_login()
    except InvalidAuth:
        return {"base": "invalid_auth"}
    except CannotConnect:
        return {"base": "cannot_connect"}
    except ApiError:
        return {"base": "unknown"}
    return {}


class ZwolleParkeerloketConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for a single parking account."""

    VERSION = 1

    _reauth_entry: ConfigEntry

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the credentials and verify them against the portal."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_MELDNUMMER])
            self._abort_if_unique_id_configured()
            errors = await _async_validate_credentials(self.hass, user_input)
            if not errors:
                return self.async_create_entry(
                    title=f"{NAME} ({user_input[CONF_MELDNUMMER]})",
                    data=dict(user_input),
                )

        return self.async_show_form(
            step_id="user", data_schema=_user_schema(), errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start the reauthentication flow for an entry whose session was rejected."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the Pincode again and verify it."""
        entry = self._reauth_entry
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**entry.data, CONF_PINCODE: user_input[CONF_PINCODE]}
            errors = await _async_validate_credentials(self.hass, data)
            if not errors:
                self.hass.config_entries.async_update_entry(entry, data=data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_reauth_schema(),
            errors=errors,
            description_placeholders={"meldnummer": entry.data[CONF_MELDNUMMER]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow, which only configures the polling interval."""
        return ZwolleParkeerloketOptionsFlow()


class ZwolleParkeerloketOptionsFlow(OptionsFlow):
    """Handle the polling interval option."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask how often the portal should be polled."""
        if user_input is not None:
            # The number selector yields a float; whole minutes are what we store.
            return self.async_create_entry(
                title="",
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])},
            )

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL_MINUTES,
                            max=MAX_SCAN_INTERVAL_MINUTES,
                            step=1,
                            unit_of_measurement="min",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )
