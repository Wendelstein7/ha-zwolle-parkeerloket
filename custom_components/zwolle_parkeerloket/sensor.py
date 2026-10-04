"""Sensor entities for the Zwolle Bezoekersparkeren integration."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ZwolleParkeerloketConfigEntry, ZwolleParkeerloketCoordinator
from .entity import ZwolleParkeerloketEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZwolleParkeerloketConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors for a parking account."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            ZwolleParkeerloketBalanceSensor(coordinator),
            ZwolleParkeerloketPlateSensor(coordinator),
            ZwolleParkeerloketStartSensor(coordinator),
            ZwolleParkeerloketEndSensor(coordinator),
            ZwolleParkeerloketZoneSensor(coordinator),
        ]
    )


class ZwolleParkeerloketBalanceSensor(ZwolleParkeerloketEntity, SensorEntity):
    """Remaining parking balance, in minutes."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_suggested_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ZwolleParkeerloketCoordinator) -> None:
        """Create the balance sensor."""
        super().__init__(coordinator, "balance")

    @property
    def native_value(self) -> int:
        """Return the remaining balance in minutes."""
        return self.coordinator.data.media.balance


class ZwolleParkeerloketPlateSensor(ZwolleParkeerloketEntity, SensorEntity):
    """Licence plate of the current reservation."""

    _attr_icon = "mdi:car"

    def __init__(self, coordinator: ZwolleParkeerloketCoordinator) -> None:
        """Create the licence plate sensor."""
        super().__init__(coordinator, "plate")

    @property
    def native_value(self) -> str | None:
        """Return the normalised plate, or ``None`` when nothing is booked.

        The normalised value is used (no dashes) because it is the stable form for
        automations; the portal's display form is offered as an attribute.
        """
        reservation = self.reservation
        if reservation is None or reservation.license_plate is None:
            return None
        return reservation.license_plate.value

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Return the display form of the plate, when the portal provides one."""
        reservation = self.reservation
        if reservation is None or reservation.license_plate is None:
            return None
        return {"display_value": reservation.license_plate.display}


class ZwolleParkeerloketStartSensor(ZwolleParkeerloketEntity, SensorEntity):
    """Start of the current (or next) reservation."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: ZwolleParkeerloketCoordinator) -> None:
        """Create the start sensor."""
        super().__init__(coordinator, "start")

    @property
    def native_value(self) -> datetime | None:
        """Return the start of the reservation, if there is one."""
        reservation = self.reservation
        return reservation.valid_from if reservation else None


class ZwolleParkeerloketEndSensor(ZwolleParkeerloketEntity, SensorEntity):
    """End of the current (or next) reservation."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: ZwolleParkeerloketCoordinator) -> None:
        """Create the end sensor."""
        super().__init__(coordinator, "end")

    @property
    def native_value(self) -> datetime | None:
        """Return the end of the reservation, if there is one."""
        reservation = self.reservation
        return reservation.valid_until if reservation else None


class ZwolleParkeerloketZoneSensor(ZwolleParkeerloketEntity, SensorEntity):
    """Permit zone of the account, for troubleshooting."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:map-marker"

    def __init__(self, coordinator: ZwolleParkeerloketCoordinator) -> None:
        """Create the zone sensor."""
        super().__init__(coordinator, "zone")

    @property
    def native_value(self) -> str | None:
        """Return the permit zone code."""
        return self.coordinator.data.media.zone_code
