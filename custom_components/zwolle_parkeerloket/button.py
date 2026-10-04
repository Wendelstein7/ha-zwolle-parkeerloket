"""Buttons for the Zwolle Bezoekersparkeren integration.

Four one-tap actions: book now, stop, extend and shorten. Each is only available
when the portal would actually accept it, so the UI answers "can I press this?"
before the user finds out the hard way.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import BOOKING_STEP_MINUTES, DOMAIN
from .coordinator import ZwolleParkeerloketConfigEntry, ZwolleParkeerloketCoordinator
from .entity import ZwolleParkeerloketEntity
from .models import Reservation


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

        Booking needs a plate, and the portal refuses a plate that already has an
        overlapping reservation, so an already-parked plate is refused here too
        rather than costing a round trip.
        """
        if not super().available:
            return False
        plate = self.coordinator.plate_draft
        if plate is None:
            return False
        return (
            self.coordinator.data.media.active_reservation_for_plate(
                plate, dt_util.utcnow()
            )
            is None
        )

    async def async_press(self) -> None:
        """Book a session with the plate from the licence plate field."""
        plate = self.coordinator.plate_draft
        if plate is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="plate_required"
            )
        await self.coordinator.async_start_booking(plate)


class _ReservationButton(ZwolleParkeerloketEntity, ButtonEntity):
    """Base for buttons that act on a single reservation.

    A button cannot take an argument, so it can only act when exactly one booking
    is in play. With several cars parked, guessing which one was meant could
    cancel the wrong car, so these buttons go unavailable and the calendar or a
    service action — both of which name the booking — take over.
    """

    minutes: int = 0

    @property
    def _target(self) -> Reservation | None:
        """Return the booking this button acts on, or ``None`` when that is unclear.

        Parked cars come first; when nothing is parked, the sessions booked for
        later are candidates instead. Either way there must be exactly one, and it
        must name a plate, since a plate is how the booking is passed on.
        """
        media = self.coordinator.data.media
        now = dt_util.utcnow()
        candidates = media.active_reservations(now) or media.upcoming_reservations(now)
        if len(candidates) != 1:
            return None
        target = candidates[0]
        if target.license_plate is None:
            return None
        return target

    def _require_plate(self) -> str:
        """Return the plate of the booking this button stands for.

        Raises:
            ServiceValidationError: it is no longer clear which booking was meant.
        """
        target = self._target
        if target is None or target.license_plate is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="several_bookings"
            )
        return target.license_plate.value

    @property
    def available(self) -> bool:
        """Return whether this button has exactly one booking it can act on."""
        target = self._target
        if target is None or not super().available:
            return False
        if self.minutes == 0:
            return True
        return self.coordinator.data.media.can_change_by(
            target, self.minutes, dt_util.utcnow()
        )


class ZwolleParkeerloketStopButton(_ReservationButton):
    """Cancel a parking session."""

    _attr_icon = "mdi:car-off"

    def __init__(self, coordinator: ZwolleParkeerloketCoordinator) -> None:
        """Create the stop button."""
        super().__init__(coordinator, "stop_booking")

    async def async_press(self) -> None:
        """Cancel the session."""
        await self.coordinator.async_stop_booking(self._require_plate())


class ZwolleParkeerloketExtendButton(_ReservationButton):
    """Extend a parking session."""

    minutes = BOOKING_STEP_MINUTES
    _attr_icon = "mdi:plus-circle"

    def __init__(self, coordinator: ZwolleParkeerloketCoordinator) -> None:
        """Create the extend button."""
        super().__init__(coordinator, "extend_time")

    async def async_press(self) -> None:
        """Add the step to the session."""
        await self.coordinator.async_change_booking_time(
            self._require_plate(), self.minutes
        )


class ZwolleParkeerloketShortenButton(_ReservationButton):
    """Shorten a parking session."""

    minutes = -BOOKING_STEP_MINUTES
    _attr_icon = "mdi:minus-circle"

    def __init__(self, coordinator: ZwolleParkeerloketCoordinator) -> None:
        """Create the shorten button."""
        super().__init__(coordinator, "shorten_time")

    async def async_press(self) -> None:
        """Take the step off the session."""
        await self.coordinator.async_change_booking_time(
            self._require_plate(), self.minutes
        )
