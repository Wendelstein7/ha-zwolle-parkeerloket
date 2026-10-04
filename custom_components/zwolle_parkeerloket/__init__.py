"""The Zwolle Bezoekersparkeren integration.

Read-only monitor for visitor-parking reservations and balance on the Gemeente
Zwolle "Parkeerloket" (DVSPortal) portal.
"""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .client import async_create_client
from .coordinator import ZwolleParkeerloketConfigEntry, ZwolleParkeerloketCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(
    hass: HomeAssistant, entry: ZwolleParkeerloketConfigEntry
) -> bool:
    """Set up a parking account from a config entry."""
    coordinator = ZwolleParkeerloketCoordinator(
        hass, entry, async_create_client(hass, entry.data)
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ZwolleParkeerloketConfigEntry
) -> bool:
    """Unload a parking account.

    The client's session is closed by Home Assistant when the entry is unloaded,
    because it was created through ``async_create_clientsession``.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
