"""Parsed representations of the Parkeerloket (DVSPortal) JSON payloads.

This module is deliberately free of any Home Assistant dependency: it can be
imported, parsed and tested on its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp, normalising it to UTC.

    The portal returns UTC with a ``Z`` suffix for reservations, but uses
    timezone-less values such as ``0001-01-01T00:00:00`` for sentinel dates.
    Sentinels and unparsable values yield ``None``.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # Timezone-less values are only ever sentinels; treat them as UTC so
        # comparisons never mix naive and aware datetimes.
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _as_int(value: Any, default: int = 0) -> int:
    """Coerce a JSON number to an int, falling back to ``default``."""
    if isinstance(value, bool) or value is None:
        return default
    try:
        return int(value)
    except TypeError, ValueError:
        return default


@dataclass(frozen=True, slots=True)
class LicensePlate:
    """A licence plate, either saved as a favourite or booked on a reservation."""

    value: str
    name: str | None = None
    display_value: str | None = None

    @classmethod
    def from_json(cls, payload: Mapping[str, Any] | None) -> LicensePlate | None:
        """Build a plate from a JSON object, or ``None`` when there is nothing usable."""
        if not payload:
            return None
        value = payload.get("Value")
        if not value:
            return None
        return cls(
            value=str(value),
            name=payload.get("Name") or None,
            display_value=payload.get("DisplayValue") or None,
        )

    @property
    def display(self) -> str:
        """Return the plate as the portal would display it."""
        return self.display_value or self.value


@dataclass(frozen=True, slots=True)
class Reservation:
    """A visitor-parking reservation, active or upcoming."""

    reservation_id: int
    valid_from: datetime
    valid_until: datetime
    license_plate: LicensePlate | None = None
    units: int = 0
    permit_media_code: str | None = None

    @classmethod
    def from_json(cls, payload: Mapping[str, Any] | None) -> Reservation | None:
        """Build a reservation from a JSON object, or ``None`` if it has no usable window."""
        if not payload:
            return None
        valid_from = _parse_timestamp(payload.get("ValidFrom"))
        valid_until = _parse_timestamp(payload.get("ValidUntil"))
        if valid_from is None or valid_until is None:
            return None
        return cls(
            reservation_id=_as_int(payload.get("ReservationID")),
            valid_from=valid_from,
            valid_until=valid_until,
            license_plate=LicensePlate.from_json(payload.get("LicensePlate")),
            units=_as_int(payload.get("Units")),
            permit_media_code=payload.get("PermitMediaCode"),
        )

    def covers(self, moment: datetime) -> bool:
        """Return whether this reservation is active at ``moment``.

        A reservation that has not started yet is not active, and one that has
        ended is not active either.
        """
        return self.valid_from <= moment < self.valid_until


@dataclass(frozen=True, slots=True)
class PermitMedia:
    """A parking permit medium (the Meldnummer) with its balance and bookings."""

    type_id: int | None
    code: str | None
    balance: int
    zone_code: str | None = None
    reservations: tuple[Reservation, ...] = ()
    license_plates: tuple[LicensePlate, ...] = ()

    @classmethod
    def from_json(
        cls, payload: Mapping[str, Any], *, zone_code: str | None = None
    ) -> PermitMedia:
        """Build a permit medium, inheriting the zone from its permit."""
        reservations = sorted(
            (
                reservation
                for item in payload.get("ActiveReservations") or []
                if (reservation := Reservation.from_json(item)) is not None
            ),
            key=lambda reservation: reservation.valid_from,
        )
        plates = tuple(
            plate
            for item in payload.get("LicensePlates") or []
            if (plate := LicensePlate.from_json(item)) is not None
        )
        return cls(
            type_id=payload.get("TypeID"),
            code=payload.get("Code"),
            balance=_as_int(payload.get("Balance")),
            zone_code=zone_code,
            reservations=tuple(reservations),
            license_plates=plates,
        )

    def reservation_covering(self, moment: datetime) -> Reservation | None:
        """Return the reservation that is active at ``moment``, if any."""
        for reservation in self.reservations:
            if reservation.covers(moment):
                return reservation
        return None

    def upcoming_reservation(self, moment: datetime) -> Reservation | None:
        """Return the soonest reservation that starts after ``moment``, if any."""
        upcoming = [
            reservation
            for reservation in self.reservations
            if reservation.valid_from > moment
        ]
        return min(
            upcoming, key=lambda reservation: reservation.valid_from, default=None
        )

    def current_reservation(self, moment: datetime) -> Reservation | None:
        """Return the reservation covering ``moment``, else the soonest upcoming one.

        The portal only allows one reservation at a time, but it can be scheduled
        in the future, in which case there is nothing active right now.
        """
        return self.reservation_covering(moment) or self.upcoming_reservation(moment)


@dataclass(frozen=True, slots=True)
class Account:
    """The account behind a Meldnummer: its name and permit media."""

    name: str = ""
    media: tuple[PermitMedia, ...] = ()

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> Account:
        """Build the account from a ``login``/``login/getbase`` response body."""
        media: list[PermitMedia] = []
        for permit in payload.get("Permits") or []:
            zone_code = permit.get("ZoneCode")
            media.extend(
                PermitMedia.from_json(permit_media, zone_code=zone_code)
                for permit_media in permit.get("PermitMedias") or []
            )
        return cls(name=str(payload.get("Name") or ""), media=tuple(media))

    def find_media(
        self, code: str | None, type_id: int | None = None
    ) -> PermitMedia | None:
        """Return the permit medium matching ``code`` (and ``type_id``), if present.

        Falls back to the only medium when the account has exactly one, so a
        reissued or reformatted Meldnummer does not leave the entities without data.
        """
        for media in self.media:
            if media.code == code and (type_id is None or media.type_id == type_id):
                return media
        if len(self.media) == 1:
            return self.media[0]
        return None


__all__ = [
    "Account",
    "LicensePlate",
    "PermitMedia",
    "Reservation",
]
