"""Shared entity behaviour for the Zwolle Parkeerloket integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import API_BASE_URL, DOMAIN, MANUFACTURER, NAME
from .coordinator import ZwolleParkeerloketCoordinator
from .models import Reservation


class ZwolleParkeerloketEntity(CoordinatorEntity[ZwolleParkeerloketCoordinator]):
    """Base entity for a parking account, tied to its own device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ZwolleParkeerloketCoordinator, key: str) -> None:
        """Attach the entity to the account's device."""
        super().__init__(coordinator)
        meldnummer = coordinator.meldnummer
        self._attr_translation_key = key
        self._attr_unique_id = f"{meldnummer}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, meldnummer)},
            entry_type=DeviceEntryType.SERVICE,
            manufacturer=MANUFACTURER,
            name=NAME,
            configuration_url=API_BASE_URL,
        )

    @property
    def reservation(self) -> Reservation | None:
        """Return the reservation the entities describe: the car ending soonest.

        Several cars can be parked at once, so an entity holding a single value
        shows the session most likely to need attention, and reports how many
        others there are so the lone value cannot mislead.
        """
        return self.coordinator.primary_reservation

    @property
    def active_reservations(self) -> tuple[Reservation, ...]:
        """Return every reservation parking a car right now, ending soonest first."""
        return self.coordinator.data.media.active_reservations(dt_util.utcnow())
