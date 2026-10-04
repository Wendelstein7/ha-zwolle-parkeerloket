"""Sensor entities for the Zwolle Bezoekersparkeren integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

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
            ZwolleParkeerloketBookingsSensor(coordinator),
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
    """Licence plate of the car the account is following.

    Several cars can be parked at once, so this shows the one whose session ends
    soonest. The others are in the bookings sensor and its attributes.
    """

    _attr_icon = "mdi:car"

    def __init__(self, coordinator: ZwolleParkeerloketCoordinator) -> None:
        """Create the licence plate sensor."""
        super().__init__(coordinator, "plate")

    @property
    def native_value(self) -> str | None:
        """Return the normalised plate of the soonest-ending booking.

        The normalised value is used (no dashes) because it is the stable form for
        automations; the portal's display form is offered as an attribute.
        """
        reservation = self.reservation
        if reservation is None or reservation.license_plate is None:
            return None
        return reservation.license_plate.value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the display form of the plate, and whether that car is parked.

        The plate can belong to a booking that has not started yet, so a dashboard
        cannot read "is this car parked right now" from the state alone.
        """
        reservation = self.reservation
        if reservation is None or reservation.license_plate is None:
            return None
        return {
            "display_value": reservation.license_plate.display,
            "parked": reservation.covers(dt_util.utcnow()),
        }


class ZwolleParkeerloketBookingsSensor(ZwolleParkeerloketEntity, SensorEntity):
    """How many cars are parked right now, with every booking as an attribute.

    This is the entity to automate on: the portal keeps several reservations at
    once, so the state counts the cars parked right now and the attributes carry
    the whole list, including sessions booked for later.
    """

    _attr_icon = "mdi:car-multiple"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ZwolleParkeerloketCoordinator) -> None:
        """Create the bookings sensor."""
        super().__init__(coordinator, "bookings")

    @property
    def native_value(self) -> int:
        """Return the number of reservations covering the current moment."""
        return len(self.active_reservations)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return every reservation the portal lists, with its window."""
        now = dt_util.utcnow()
        return {
            "reservations": [
                {
                    "reservation_id": reservation.reservation_id,
                    "license_plate": (
                        reservation.license_plate.value
                        if reservation.license_plate is not None
                        else None
                    ),
                    "start": reservation.valid_from.isoformat(),
                    "end": reservation.valid_until.isoformat(),
                    "parked": reservation.covers(now),
                    "units": reservation.units,
                }
                for reservation in self.coordinator.data.media.reservations
            ]
        }


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
