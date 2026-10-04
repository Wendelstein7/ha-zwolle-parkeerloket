"""Tests for the parsed API models, with no Home Assistant involved."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from custom_components.zwolle_parkeerloket.models import (
    Account,
    LicensePlate,
    PermitMedia,
    Reservation,
)

MOMENT = datetime(2026, 10, 5, 8, 15, tzinfo=UTC)


def _reservation(**overrides: Any) -> Reservation:
    """Return a reservation covering 08:00-08:30 UTC on 2026-10-05."""
    defaults: dict[str, Any] = {
        "reservation_id": 1,
        "valid_from": datetime(2026, 10, 5, 8, 0, tzinfo=UTC),
        "valid_until": datetime(2026, 10, 5, 8, 30, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Reservation(**defaults)


def test_account_parses_the_permit_media(account_payload: dict[str, Any]) -> None:
    """Balance, zone, prolong step, plates and reservations come from the permit."""
    account = Account.from_json(account_payload)

    assert len(account.media) == 1
    media = account.media[0]
    assert media.type_id == 9
    assert media.code == "12345"
    assert media.balance == 7140
    assert media.zone_code == "ZONE1"
    assert len(media.reservations) == 1
    assert len(media.license_plates) == 2
    assert {plate.value for plate in media.license_plates} == {"AA11BB", "CC22DD"}


def test_reservation_parses_the_utc_window_and_plate(
    account_payload: dict[str, Any],
) -> None:
    """Timestamps are normalised to UTC and the plate is parsed."""
    reservation = Account.from_json(account_payload).media[0].reservations[0]

    assert reservation.reservation_id == 555001
    assert reservation.valid_from == datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
    assert reservation.valid_until == datetime(2026, 10, 5, 8, 30, tzinfo=UTC)
    assert reservation.units == 30
    assert reservation.license_plate is not None
    assert reservation.license_plate.value == "AA11BB"
    assert reservation.license_plate.display == "AA-11-BB"


def test_plate_display_falls_back_to_the_raw_value() -> None:
    """Saved plates have no display value, so the raw value is used."""
    plate = LicensePlate.from_json({"Value": "CC22DD", "Name": "Visitor two"})

    assert plate is not None
    assert plate.display == "CC22DD"
    assert plate.name == "Visitor two"


def test_plate_without_a_value_is_ignored() -> None:
    """A plate object without a value is not usable."""
    assert LicensePlate.from_json({"Name": "no value"}) is None
    assert LicensePlate.from_json(None) is None


def test_reservation_covers_only_its_own_window() -> None:
    """``covers`` is inclusive of the start and exclusive of the end."""
    reservation = _reservation()

    assert reservation.covers(datetime(2026, 10, 5, 8, 0, tzinfo=UTC)) is True
    assert reservation.covers(MOMENT) is True
    assert reservation.covers(datetime(2026, 10, 5, 8, 30, tzinfo=UTC)) is False
    assert reservation.covers(datetime(2026, 10, 5, 7, 59, tzinfo=UTC)) is False


def test_current_reservation_prefers_the_active_one() -> None:
    """An active reservation wins over an upcoming one."""
    finished = _reservation(
        reservation_id=1,
        valid_from=datetime(2026, 10, 5, 6, 0, tzinfo=UTC),
        valid_until=datetime(2026, 10, 5, 6, 30, tzinfo=UTC),
    )
    active = _reservation(reservation_id=2)
    upcoming = _reservation(
        reservation_id=3,
        valid_from=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
        valid_until=datetime(2026, 10, 5, 10, 30, tzinfo=UTC),
    )
    media = PermitMedia(
        type_id=9, code="12345", balance=7200, reservations=(finished, active, upcoming)
    )

    assert media.reservation_covering(MOMENT) is active
    assert media.current_reservation(MOMENT) is active


def test_current_reservation_falls_back_to_the_soonest_upcoming() -> None:
    """With nothing active, the next booking is used; ended ones are ignored."""
    finished = _reservation(
        reservation_id=1,
        valid_from=datetime(2026, 10, 5, 6, 0, tzinfo=UTC),
        valid_until=datetime(2026, 10, 5, 6, 30, tzinfo=UTC),
    )
    later = _reservation(
        reservation_id=2,
        valid_from=datetime(2026, 10, 6, 8, 0, tzinfo=UTC),
        valid_until=datetime(2026, 10, 6, 8, 30, tzinfo=UTC),
    )
    sooner = _reservation(
        reservation_id=3,
        valid_from=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
        valid_until=datetime(2026, 10, 5, 10, 30, tzinfo=UTC),
    )
    media = PermitMedia(
        type_id=9, code="12345", balance=7200, reservations=(finished, later, sooner)
    )

    assert media.reservation_covering(MOMENT) is None
    assert media.current_reservation(MOMENT) is sooner


def test_no_reservations_at_all() -> None:
    """An account without reservations simply has none."""
    media = PermitMedia(type_id=9, code="12345", balance=7200)

    assert media.reservations == ()
    assert media.current_reservation(MOMENT) is None


def test_reservations_without_a_usable_window_are_skipped() -> None:
    """A reservation without a parsable window is dropped instead of crashing."""
    account = Account.from_json(
        {
            "Permits": [
                {
                    "ZoneCode": "ZONE1",
                    "PermitMedias": [
                        {
                            "TypeID": 9,
                            "Code": "12345",
                            "Balance": 100,
                            "ActiveReservations": [
                                {
                                    "ReservationID": 1,
                                    "ValidFrom": None,
                                    "ValidUntil": None,
                                },
                                {"ReservationID": 2},
                                _valid_reservation_json(),
                            ],
                        }
                    ],
                }
            ]
        }
    )

    reservations = account.media[0].reservations
    # The first two entries have no usable window and are dropped.
    assert [reservation.reservation_id for reservation in reservations] == [3]


def _valid_reservation_json() -> dict[str, Any]:
    """Return a reservation payload the parser must accept."""
    return {
        "ReservationID": 3,
        "ValidFrom": "2026-10-05T08:00:00Z",
        "ValidUntil": "2026-10-05T08:30:00Z",
    }


def test_timezone_less_timestamps_are_treated_as_utc() -> None:
    """Sentinel-style timestamps must not mix naive and aware datetimes."""
    reservation = Reservation.from_json(
        {
            "ReservationID": 9,
            "ValidFrom": "0001-01-01T00:00:00",
            "ValidUntil": "2026-10-05T08:30:00Z",
        }
    )

    assert reservation is not None
    assert reservation.valid_from == datetime(1, 1, 1, tzinfo=UTC)


def test_local_offset_timestamps_are_converted() -> None:
    """A timestamp with a local offset is normalised to UTC."""
    reservation = Reservation.from_json(
        {
            "ReservationID": 9,
            "ValidFrom": "2026-10-05T10:00:00.000+02:00",
            "ValidUntil": "2026-10-05T10:30:00.000+02:00",
        }
    )

    assert reservation is not None
    assert reservation.valid_from == datetime(2026, 10, 5, 8, 0, tzinfo=UTC)


def test_unparsable_units_fall_back_to_zero() -> None:
    """Odd numeric values must not break parsing."""
    reservation = Reservation.from_json(
        {
            "ReservationID": 9,
            "ValidFrom": "2026-10-05T08:00:00Z",
            "ValidUntil": "2026-10-05T08:30:00Z",
            "Units": "not a number",
        }
    )

    assert reservation is not None
    assert reservation.units == 0


def test_find_media_matches_on_code_and_type(account_payload: dict[str, Any]) -> None:
    """The configured Meldnummer selects the right permit medium."""
    account = Account.from_json(account_payload)

    assert account.find_media("12345", 9) is not None
    assert account.find_media("99999", 9) is not None, (
        "a single medium is used as a fallback"
    )


def test_find_media_returns_none_when_ambiguous() -> None:
    """With several media and no match, nothing is selected."""
    account = Account.from_json(
        {
            "Permits": [
                {
                    "PermitMedias": [
                        {"TypeID": 9, "Code": "11111", "Balance": 1},
                        {"TypeID": 9, "Code": "22222", "Balance": 2},
                    ]
                }
            ]
        }
    )

    assert account.find_media("11111", 9) is not None
    assert account.find_media("33333", 9) is None


def test_multiple_permits_are_flattened() -> None:
    """Media from every permit are collected, each carrying its own zone."""
    account = Account.from_json(
        {
            "Permits": [
                {
                    "ZoneCode": "ZONE1",
                    "ProlongMinutes": 10,
                    "PermitMedias": [{"TypeID": 9, "Code": "11111"}],
                },
                {
                    "ZoneCode": "CENTRUM",
                    "ProlongMinutes": 30,
                    "PermitMedias": [{"TypeID": 9, "Code": "22222"}],
                },
            ]
        }
    )

    assert [(media.code, media.zone_code) for media in account.media] == [
        ("11111", "ZONE1"),
        ("22222", "CENTRUM"),
    ]
