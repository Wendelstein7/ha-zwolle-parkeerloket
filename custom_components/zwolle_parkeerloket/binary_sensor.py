"""Binary sensor entities for the Zwolle Parkeerloket integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ZwolleParkeerloketConfigEntry, ZwolleParkeerloketCoordinator
from .entity import ZwolleParkeerloketEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZwolleParkeerloketConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the binary sensors for a parking account."""
    async_add_entities([ZwolleParkeerloketActiveBinarySensor(entry.runtime_data)])


class ZwolleParkeerloketActiveBinarySensor(
    ZwolleParkeerloketEntity, BinarySensorEntity
):
    """Whether a parking reservation is active right now."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_icon = "mdi:car"

    def __init__(self, coordinator: ZwolleParkeerloketCoordinator) -> None:
        """Create the parking-active binary sensor."""
        super().__init__(coordinator, "parking_active")

    @property
    def is_on(self) -> bool:
        """Return whether any reservation covers the current moment.

        Several cars may be parked at once; this is on when at least one is. A
        reservation that is only scheduled for the future does not count.
        """
        return bool(self.active_reservations)
