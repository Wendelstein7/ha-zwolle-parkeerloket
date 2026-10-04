"""Polling coordinator for the Zwolle Bezoekersparkeren integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ApiError, CannotConnect, DVSPortalClient, InvalidAuth
from .const import (
    CONF_MELDNUMMER,
    CONF_PERMIT_MEDIA_TYPE_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_PERMIT_MEDIA_TYPE_ID,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)
from .models import Account, PermitMedia

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ZwolleParkeerloketData:
    """The account state the entities read from the coordinator."""

    account: Account
    media: PermitMedia


class ZwolleParkeerloketCoordinator(DataUpdateCoordinator[ZwolleParkeerloketData]):
    """Poll the portal's single read endpoint for this account."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: DVSPortalClient,
    ) -> None:
        """Set up the coordinator with the entry's credentials and interval."""
        self.client = client
        self.meldnummer: str = entry.data[CONF_MELDNUMMER]
        self.permit_media_type_id: int = entry.data.get(
            CONF_PERMIT_MEDIA_TYPE_ID, DEFAULT_PERMIT_MEDIA_TYPE_ID
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                minutes=entry.options.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
                )
            ),
        )

    async def _async_setup(self) -> None:
        """Log in once, before the first data fetch."""
        try:
            await self.client.async_login()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(
                f"the portal rejected the credentials: {err}"
            ) from err
        except CannotConnect as err:
            raise UpdateFailed(f"could not reach the portal: {err}") from err

    async def _async_update_data(self) -> ZwolleParkeerloketData:
        """Fetch the account state and select this entry's permit medium."""
        try:
            account = await self.client.async_get_account()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(
                f"the portal rejected the credentials: {err}"
            ) from err
        except (CannotConnect, ApiError) as err:
            raise UpdateFailed(f"could not read the account: {err}") from err

        media = account.find_media(self.meldnummer, self.permit_media_type_id)
        if media is None:
            raise UpdateFailed(
                f"Meldnummer {self.meldnummer} is not among the account's permits"
            )
        return ZwolleParkeerloketData(account=account, media=media)


type ZwolleParkeerloketConfigEntry = ConfigEntry[ZwolleParkeerloketCoordinator]
