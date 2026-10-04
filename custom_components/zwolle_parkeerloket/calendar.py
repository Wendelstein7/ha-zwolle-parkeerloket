"""Calendar entity for the Zwolle Bezoekersparkeren integration.

Every reservation is an event, one per parked car, so the Calendar panel shows at
a glance which cars are parked and until when. Home Assistant drives the delete
and update features of a calendar entity from that panel and addresses an event by
its uid, which is the portal's reservation id — so cancelling or resizing an event
acts on exactly one car, which is what a button cannot do once several are parked.

There is deliberately no creation support: ``calendar.create_event`` wants a
summary, and a summary is where the licence plate would have to go, which is a
poor way to book. Booking is what the book button and ``start_booking`` are for.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEntityFeature,
    CalendarEvent,
)
from homeassistant.components.calendar.const import EVENT_END, EVENT_START
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import ZwolleParkeerloketConfigEntry, ZwolleParkeerloketCoordinator
from .entity import ZwolleParkeerloketEntity
from .models import Reservation

# The Calendar panel carries a booking's window through a JavaScript date, which
# keeps milliseconds, while the portal stores microseconds: a booking starting at
# 21:42:26.142660 comes back from the editor as 21:42:26.142. That is the same
# instant as far as the panel is concerned, and anything a person can pick is at
# least a minute away, so a second separates "untouched" from "moved".
_EDITOR_PRECISION = timedelta(seconds=1)


def _requested_minutes(stored_end: datetime, requested_end: datetime) -> int:
    """Return the signed number of minutes the editor is asking for.

    Both ends are compared at the resolution the panel works in, whole minutes: it
    shows the end as 20:53 even when the portal stored 20:53:46, so asking it for
    21:23 is half an hour later, not twenty-nine minutes. Measuring from the stored
    seconds instead would leave the booking ending at 21:22, one minute short of the
    time the user picked.

    An end that was left alone comes back with the microseconds the editor dropped,
    which lands on the same minute and therefore on a change of zero.
    """
    displayed = dt_util.as_local(stored_end).replace(second=0, microsecond=0)
    requested = dt_util.as_local(requested_end).replace(second=0, microsecond=0)
    return round((requested - displayed).total_seconds() / 60)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZwolleParkeerloketConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the calendar for a parking account."""
    async_add_entities([ZwolleParkeerloketCalendar(entry.runtime_data)])


class ZwolleParkeerloketCalendar(ZwolleParkeerloketEntity, CalendarEntity):
    """The account's reservations, as calendar events."""

    _attr_icon = "mdi:car"
    _attr_supported_features = (
        CalendarEntityFeature.DELETE_EVENT | CalendarEntityFeature.UPDATE_EVENT
    )

    def __init__(self, coordinator: ZwolleParkeerloketCoordinator) -> None:
        """Create the calendar."""
        super().__init__(coordinator, "calendar")

    @property
    def event(self) -> CalendarEvent | None:
        """Return the booking the account is following, if there is one."""
        reservation = self.reservation
        if reservation is None:
            return None
        return self._as_event(reservation)

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return every booking that overlaps the requested period."""
        return [
            self._as_event(reservation)
            for reservation in self.coordinator.data.media.reservations
            if reservation.valid_from < end_date
            and reservation.valid_until > start_date
        ]

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Cancel the booking an event stands for."""
        await self.coordinator.async_stop_reservation(self._reservation_for(uid))

    async def async_update_event(
        self,
        uid: str,
        event: dict[str, Any],
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Change how long a booking lasts, from a new end time.

        The portal can only adjust a reservation by a number of minutes: once
        booked, its start and its licence plate are fixed. A moved start or a
        renamed event is therefore refused rather than quietly ignored, and a new
        end time is turned back into the signed number of minutes the portal wants.

        The panel's editor is less precise than the portal: it round-trips a window
        through a date that keeps milliseconds and shows times in whole minutes, so
        both comparisons are made at the resolution the panel can actually express.
        """
        reservation = self._reservation_for(uid)
        start = event.get(EVENT_START)
        end = event.get(EVENT_END)
        if not isinstance(start, datetime) or not isinstance(end, datetime):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="calendar_whole_days",
            )

        if abs(dt_util.as_utc(start) - reservation.valid_from) >= _EDITOR_PRECISION:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="calendar_start_is_fixed",
                translation_placeholders={
                    "start": reservation.valid_from.astimezone().strftime("%H:%M"),
                },
            )

        if event.get("summary") not in (None, self._summary(reservation)):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="calendar_plate_is_fixed",
            )

        minutes = _requested_minutes(reservation.valid_until, dt_util.as_utc(end))
        if minutes == 0:
            # The panel hands back a booking it never touched with seconds rounded
            # away, so this is a save with nothing to change rather than an error.
            return

        await self.coordinator.async_change_reservation_time(reservation, minutes)

    def _reservation_for(self, uid: str) -> Reservation:
        """Return the reservation an event uid stands for.

        Raises:
            ServiceValidationError: the uid is not a reservation id, or the portal
                no longer lists that reservation.
        """
        try:
            reservation_id = int(uid)
        except (TypeError, ValueError) as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="unknown_booking"
            ) from err

        reservation = self.coordinator.data.media.reservation_by_id(reservation_id)
        if reservation is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="unknown_booking"
            )
        return reservation

    @staticmethod
    def _summary(reservation: Reservation) -> str:
        """Return the event title: the plate of the car being parked."""
        if reservation.license_plate is None:
            return "Parking"
        return reservation.license_plate.display

    def _as_event(self, reservation: Reservation) -> CalendarEvent:
        """Describe a reservation as a calendar event."""
        return CalendarEvent(
            start=reservation.valid_from,
            end=reservation.valid_until,
            summary=self._summary(reservation),
            description=(
                f"Reservation {reservation.reservation_id}"
                f" · {reservation.units} min charged"
            ),
            location=self.coordinator.data.media.zone_code,
            uid=str(reservation.reservation_id),
        )
