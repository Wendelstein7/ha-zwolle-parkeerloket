"""Buttons for the Zwolle Bezoekersparkeren integration.

Four one-tap actions: book now, stop, extend and shorten. Each is only available
when the portal would actually accept it, so the UI answers "can I press this?"
before the user finds out the hard way.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import BOOKING_STEP_MINUTES
from .coordinator import ZwolleParkeerloketConfigEntry, ZwolleParkeerloketCoordinator
from .entity import ZwolleParkeerloketEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZwolleParkeerloketConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the action buttons for a parking account."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            ZwolleParkeerloketBookButton(coordinator),
            ZwolleParkeerloketStopButton(coordinator),
            ZwolleParkeerloketExtendButton(coordinator),
            ZwolleParkeerloketShortenButton(coordinator),
        ]
    )


class ZwolleParkeerloketBookButton(ZwolleParkeerloketEntity, ButtonEntity):
    """Book a parking session starting now."""

    _attr_icon = "mdi:car-plus"

    def __init__(self, coordinator: ZwolleParkeerloketCoordinator) -> None:
        """Create the book button."""
        super().__init__(coordinator, "book_now")

    @property
    def available(self) -> bool:
        """Return whether booking makes sense right now.

        Booking is pointless without a plate, and the portal allows only one
        reservation at a time, so an existing one has to be stopped first.
        """
        return (
            super().available
            and self.coordinator.bookable_plate is not None
            and self.coordinator.current_reservation is None
        )

    async def async_press(self) -> None:
        """Book a session with the plate from the licence plate field."""
        await self.coordinator.async_start_booking()


class _ReservationButton(ZwolleParkeerloketEntity, ButtonEntity):
    """Base for buttons that act on the current reservation."""

    minutes: int = 0

    @property
    def available(self) -> bool:
        """Return whether there is a reservation this button can act on."""
        if not super().available:
            return False
        reservation = self.coordinator.current_reservation
        if reservation is None:
            return False
        if self.minutes == 0:
            return True
        return self.coordinator.data.media.can_change_by(
            reservation, self.minutes, dt_util.utcnow()
        )


class ZwolleParkeerloketStopButton(_ReservationButton):
    """Cancel the current parking session."""

    _attr_icon = "mdi:car-off"

    def __init__(self, coordinator: ZwolleParkeerloketCoordinator) -> None:
        """Create the stop button."""
        super().__init__(coordinator, "stop_booking")

    async def async_press(self) -> None:
        """Cancel the current session."""
        await self.coordinator.async_stop_booking()


class ZwolleParkeerloketExtendButton(_ReservationButton):
    """Extend the current parking session."""

    minutes = BOOKING_STEP_MINUTES
    _attr_icon = "mdi:plus-circle"

    def __init__(self, coordinator: ZwolleParkeerloketCoordinator) -> None:
        """Create the extend button."""
        super().__init__(coordinator, "extend_time")

    async def async_press(self) -> None:
        """Add the step to the current session."""
        await self.coordinator.async_change_booking_time(self.minutes)


class ZwolleParkeerloketShortenButton(_ReservationButton):
    """Shorten the current parking session."""

    minutes = -BOOKING_STEP_MINUTES
    _attr_icon = "mdi:minus-circle"

    def __init__(self, coordinator: ZwolleParkeerloketCoordinator) -> None:
        """Create the shorten button."""
        super().__init__(coordinator, "shorten_time")

    async def async_press(self) -> None:
        """Take the step off the current session."""
        await self.coordinator.async_change_booking_time(self.minutes)
