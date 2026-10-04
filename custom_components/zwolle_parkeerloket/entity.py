"""Shared entity behaviour for the Zwolle Bezoekersparkeren integration."""

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
        """Return the reservation covering now, else the soonest upcoming one.

        Only one reservation can be active at a time, and a booking may be
        scheduled in the future, in which case nothing is active right now.
        """
        return self.coordinator.data.media.current_reservation(dt_util.utcnow())

    @property
    def active_reservation(self) -> Reservation | None:
        """Return the reservation covering the current moment, if there is one."""
        return self.coordinator.data.media.reservation_covering(dt_util.utcnow())
