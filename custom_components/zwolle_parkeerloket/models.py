"""Parsed representations of the Parkeerloket (DVSPortal) JSON payloads.

This module is deliberately free of any Home Assistant dependency: it can be
imported, parsed and tested on its own.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

# Dutch licence plates, and the plates of visiting foreigners, in their normalised
# form: letters and digits only, no dashes or spaces.
PLATE_PATTERN = re.compile(r"^[A-Z0-9]{4,10}$")

# Separators people type into a plate field but the API does not expect.
_PLATE_SEPARATORS = re.compile(r"[\s\-.]")


def normalise_plate(value: str) -> str:
    """Return a licence plate in the form the API expects.

    The portal takes plates without separators and in capitals, so ``aa-11-bb``
    becomes ``AA11BB``.

    Raises:
        ValueError: the value is not a plausible licence plate.
    """
    plate = _PLATE_SEPARATORS.sub("", value).upper()
    if not PLATE_PATTERN.match(plate):
        raise ValueError(f"{value!r} is not a valid licence plate")
    return plate


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


def _plate_matches(reservation: Reservation, plate: str) -> bool:
    """Return whether a reservation was made for ``plate``.

    Both sides are normalised, since the plate a user names a booking by may come
    from an automation as ``aa-11-bb`` while the portal stored ``AA11BB``.
    """
    if reservation.license_plate is None or not reservation.license_plate.value:
        return False
    try:
        return normalise_plate(reservation.license_plate.value) == normalise_plate(
            plate
        )
    except ValueError:
        return False


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
    """A parking reservation, active or upcoming."""

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
    restricted_prolong_ids: frozenset[int] = frozenset()
    max_bookable_end: datetime | None = None

    @classmethod
    def from_json(
        cls,
        payload: Mapping[str, Any],
        *,
        zone_code: str | None = None,
        max_bookable_end: datetime | None = None,
    ) -> PermitMedia:
        """Build a permit medium, inheriting the zone and horizon from its permit."""
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
            restricted_prolong_ids=frozenset(
                _as_int(item)
                for item in payload.get("RestrictedProlongReservationIDs") or []
            ),
            max_bookable_end=max_bookable_end,
        )

    def active_reservations(self, moment: datetime) -> tuple[Reservation, ...]:
        """Return every reservation covering ``moment``, ending soonest first.

        The portal keeps several reservations at once — different plates may be
        parked over the same period — so this is a list rather than the single
        reservation this integration used to assume. Ordering by end time puts the
        one most likely to need attention first.
        """
        return tuple(
            sorted(
                (
                    reservation
                    for reservation in self.reservations
                    if reservation.covers(moment)
                ),
                key=lambda reservation: reservation.valid_until,
            )
        )

    def upcoming_reservations(self, moment: datetime) -> tuple[Reservation, ...]:
        """Return every reservation starting after ``moment``, soonest first."""
        return tuple(
            sorted(
                (
                    reservation
                    for reservation in self.reservations
                    if reservation.valid_from > moment
                ),
                key=lambda reservation: reservation.valid_from,
            )
        )

    def primary_reservation(self, moment: datetime) -> Reservation | None:
        """Return the reservation the glanceable entities describe.

        That is the parked car whose session ends soonest, or, when nothing is
        parked, the soonest upcoming session. Several cars can be parked at once,
        so this is a choice: it is the one most likely to need the user's
        attention, and the entities that show it also report how many others there
        are so the single value cannot mislead.
        """
        active = self.active_reservations(moment)
        if active:
            return active[0]
        upcoming = self.upcoming_reservations(moment)
        return upcoming[0] if upcoming else None

    def reservation_by_id(self, reservation_id: int) -> Reservation | None:
        """Return the reservation with this id, if the portal still lists it."""
        for reservation in self.reservations:
            if reservation.reservation_id == reservation_id:
                return reservation
        return None

    def active_reservation_for_plate(
        self, plate: str, moment: datetime
    ) -> Reservation | None:
        """Return the reservation parking ``plate`` right now, if any."""
        for reservation in self.active_reservations(moment):
            if _plate_matches(reservation, plate):
                return reservation
        return None

    def reservation_for_plate(self, plate: str, moment: datetime) -> Reservation | None:
        """Return the reservation that ``plate`` refers to.

        A licence plate is how the service actions and the buttons name a booking,
        since it is what a user knows without looking anything up. The parked
        reservation wins; otherwise the soonest upcoming one for that plate. The
        portal refuses overlapping reservations for one plate, so at most one can
        be parked at a time and this stays unambiguous in practice.
        """
        active = self.active_reservation_for_plate(plate, moment)
        if active is not None:
            return active
        return next(
            (
                reservation
                for reservation in self.upcoming_reservations(moment)
                if _plate_matches(reservation, plate)
            ),
            None,
        )

    def prolong_is_restricted(self, reservation: Reservation) -> bool:
        """Return whether the portal refuses to extend this reservation.

        The portal names the reservations that may not be prolonged, for example
        because they already reach the end of the bookable window. Its own web app
        hides the extend control for those, so we treat it as a hard block rather
        than letting the user walk into a rejection.
        """
        return reservation.reservation_id in self.restricted_prolong_ids

    def extension_room(self, reservation: Reservation) -> timedelta | None:
        """Return how much later this reservation may end.

        ``None`` means the portal did not publish its bookable window, in which
        case the request is left to the portal to judge.
        """
        if self.max_bookable_end is None:
            return None
        return max(self.max_bookable_end - reservation.valid_until, timedelta())

    def can_change_by(
        self, reservation: Reservation, minutes: int, moment: datetime
    ) -> bool:
        """Return whether changing this reservation by ``minutes`` is possible.

        Positive values extend and negative values shorten. Extending is limited
        by the bookable window and by the portal's prolong restrictions; shortening
        may never move the end into the past, which is the same rule the portal's
        own web app applies before offering its minus control.
        """
        if minutes == 0:
            return False
        if minutes < 0:
            return reservation.valid_until + timedelta(minutes=minutes) > moment
        if self.prolong_is_restricted(reservation):
            return False
        room = self.extension_room(reservation)
        return room is None or room >= timedelta(minutes=minutes)


def _permit_horizon(permit: Mapping[str, Any]) -> datetime | None:
    """Return the furthest moment the portal allows a reservation to end.

    The portal publishes its bookable window as a rolling calendar in
    ``BlockTimes``; its own web app uses the end of the last block as the maximum
    date of its pickers, so that is the horizon we validate against too.
    """
    latest: datetime | None = None
    for block in permit.get("BlockTimes") or []:
        end = _parse_timestamp(block.get("ValidUntil"))
        if end is not None and (latest is None or end > latest):
            latest = end
    return latest


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
            horizon = _permit_horizon(permit)
            media.extend(
                PermitMedia.from_json(
                    permit_media, zone_code=zone_code, max_bookable_end=horizon
                )
                for permit_media in permit.get("PermitMedias") or []
            )
        return cls(name=str(payload.get("Name") or ""), media=tuple(media))

    def merged_with_permit(self, payload: Mapping[str, Any]) -> Account:
        """Return a copy with the permit of a write response merged in.

        ``reservation/create|update|end`` answer with a single ``Permit`` instead
        of the whole model. The portal's own web app merges it into its cached
        state; doing the same means a write needs no extra poll. A response that
        carries the full model instead is used as-is.
        """
        permit = payload.get("Permit")
        if not isinstance(permit, Mapping):
            return Account.from_json(payload)

        zone_code = permit.get("ZoneCode")
        horizon = _permit_horizon(permit)
        replacements = {
            (media.code, media.type_id): media
            for media in (
                PermitMedia.from_json(
                    permit_media, zone_code=zone_code, max_bookable_end=horizon
                )
                for permit_media in permit.get("PermitMedias") or []
            )
        }

        merged: list[PermitMedia] = []
        for existing in self.media:
            media = replacements.pop((existing.code, existing.type_id), None)
            if media is None:
                merged.append(existing)
                continue
            # Booking does not touch the saved plates or the permit metadata, so a
            # response that omits them must not drop what we already knew.
            if not media.license_plates:
                media = replace(media, license_plates=existing.license_plates)
            if media.zone_code is None:
                media = replace(media, zone_code=existing.zone_code)
            if media.max_bookable_end is None:
                media = replace(media, max_bookable_end=existing.max_bookable_end)
            merged.append(media)

        merged.extend(replacements.values())
        return Account(name=self.name, media=tuple(merged))

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
    "normalise_plate",
]
