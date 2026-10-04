"""Tests for the parsed API models, with no Home Assistant involved."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.zwolle_parkeerloket.models import (
    Account,
    LicensePlate,
    PermitMedia,
    Reservation,
    normalise_plate,
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


def test_primary_reservation_is_the_active_one() -> None:
    """An active reservation wins over one that has not started yet."""
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

    assert media.active_reservations(MOMENT) == (active,)
    assert media.primary_reservation(MOMENT) is active


def test_primary_reservation_prefers_the_car_that_leaves_first() -> None:
    """With several cars parked, the one ending soonest is the one described.

    It is the booking most likely to need attention, and the entities that show a
    single reservation report how many others there are alongside it.
    """
    leaving_late = _reservation(
        reservation_id=1,
        valid_from=datetime(2026, 10, 5, 8, 0, tzinfo=UTC),
        valid_until=datetime(2026, 10, 5, 9, 0, tzinfo=UTC),
    )
    leaving_first = _reservation(
        reservation_id=2,
        valid_from=datetime(2026, 10, 5, 8, 0, tzinfo=UTC),
        valid_until=datetime(2026, 10, 5, 8, 45, tzinfo=UTC),
    )
    media = PermitMedia(
        type_id=9,
        code="12345",
        balance=7200,
        reservations=(leaving_late, leaving_first),
    )

    assert media.active_reservations(MOMENT) == (leaving_first, leaving_late)
    assert media.primary_reservation(MOMENT) is leaving_first


def test_primary_reservation_falls_back_to_the_soonest_upcoming() -> None:
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

    assert media.active_reservations(MOMENT) == ()
    assert media.upcoming_reservations(MOMENT) == (sooner, later)
    assert media.primary_reservation(MOMENT) is sooner


def test_reservation_for_plate_prefers_the_parked_car() -> None:
    """A plate names a booking: the parked one, else the soonest upcoming one."""
    parked = _reservation(reservation_id=2, license_plate=LicensePlate("AA11BB"))
    later = _reservation(
        reservation_id=3,
        license_plate=LicensePlate("AA11BB"),
        valid_from=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
        valid_until=datetime(2026, 10, 5, 10, 30, tzinfo=UTC),
    )
    other_car = _reservation(reservation_id=4, license_plate=LicensePlate("CC22DD"))
    media = PermitMedia(
        type_id=9,
        code="12345",
        balance=7200,
        reservations=(parked, later, other_car),
    )

    assert media.reservation_for_plate("AA11BB", MOMENT) is parked
    assert media.reservation_for_plate("CC22DD", MOMENT) is other_car
    assert media.reservation_for_plate("XX99YY", MOMENT) is None


def test_reservation_for_plate_ignores_separators_and_case() -> None:
    """A plate is compared the way a person would read it."""
    media = PermitMedia(
        type_id=9,
        code="12345",
        balance=7200,
        reservations=(_reservation(license_plate=LicensePlate("AA11BB")),),
    )

    assert media.reservation_for_plate("aa-11-bb", MOMENT) is not None


def test_reservation_for_plate_falls_back_to_an_upcoming_one() -> None:
    """A plate that is booked but not parked yet still resolves."""
    later = _reservation(
        reservation_id=3,
        license_plate=LicensePlate("AA11BB"),
        valid_from=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
        valid_until=datetime(2026, 10, 5, 10, 30, tzinfo=UTC),
    )
    media = PermitMedia(type_id=9, code="12345", balance=7200, reservations=(later,))

    assert media.active_reservation_for_plate("AA11BB", MOMENT) is None
    assert media.reservation_for_plate("AA11BB", MOMENT) is later


def test_reservation_by_id_finds_only_what_is_listed() -> None:
    """The calendar addresses a booking by its portal id."""
    media = PermitMedia(
        type_id=9,
        code="12345",
        balance=7200,
        reservations=(_reservation(reservation_id=77),),
    )

    assert media.reservation_by_id(77) is not None
    assert media.reservation_by_id(78) is None


def test_no_reservations_at_all() -> None:
    """An account without reservations simply has none."""
    media = PermitMedia(type_id=9, code="12345", balance=7200)

    assert media.reservations == ()
    assert media.active_reservations(MOMENT) == ()
    assert media.primary_reservation(MOMENT) is None
    assert media.reservation_for_plate("AA11BB", MOMENT) is None


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


# --- licence plates ----------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("AA11BB", "AA11BB"),
        ("aa-11-bb", "AA11BB"),
        (" aa 11 bb ", "AA11BB"),
        ("cc22dd", "CC22DD"),
        ("1-ABC-12", "1ABC12"),
    ],
)
def test_normalise_plate(typed: str, expected: str) -> None:
    """Plates are uppercased and stripped of separators, as the API expects."""
    assert normalise_plate(typed) == expected


@pytest.mark.parametrize("typed", ["", "!!", "A", "TOOLONGPLATE1"])
def test_normalise_plate_rejects_nonsense(typed: str) -> None:
    """Anything that cannot be a plate is rejected before it reaches the portal."""
    with pytest.raises(ValueError):
        normalise_plate(typed)


# --- booking constraints ----------------------------------------------------


def _media(**overrides: Any) -> PermitMedia:
    """Return a permit medium with one reservation covering 08:00-08:30 UTC."""
    defaults: dict[str, Any] = {
        "type_id": 9,
        "code": "12345",
        "balance": 7200,
        "reservations": (_reservation(),),
    }
    defaults.update(overrides)
    return PermitMedia(**defaults)


def test_block_times_give_the_bookable_horizon(account_payload: dict[str, Any]) -> None:
    """The end of the last block is how far the portal allows booking."""
    payload = account_payload
    payload["Permits"][0]["BlockTimes"] = [
        {"ValidUntil": "2026-10-10T20:00:00Z"},
        {"ValidUntil": "2026-12-03T23:00:00Z"},
        {"ValidUntil": "2026-11-01T20:00:00Z"},
    ]

    media = Account.from_json(payload).media[0]

    assert media.max_bookable_end == datetime(2026, 12, 3, 23, 0, tzinfo=UTC)


def test_missing_block_times_leave_the_horizon_unknown() -> None:
    """Without a published calendar the portal is left to judge."""
    media = Account.from_json({"Permits": [{"PermitMedias": [{"TypeID": 9}]}]}).media[0]

    assert media.max_bookable_end is None
    assert media.extension_room(_reservation()) is None


def test_extension_room_is_the_distance_to_the_horizon() -> None:
    """Room is measured from the end of the reservation to the horizon."""
    media = _media(max_bookable_end=datetime(2026, 10, 5, 9, 0, tzinfo=UTC))

    assert media.extension_room(_reservation()) == timedelta(minutes=30)


def test_extension_room_never_goes_negative() -> None:
    """A reservation already past the horizon has no room left."""
    media = _media(max_bookable_end=datetime(2026, 10, 5, 8, 0, tzinfo=UTC))

    assert media.extension_room(_reservation()) == timedelta(0)


def test_restricted_reservations_cannot_be_extended() -> None:
    """The portal names the reservations it refuses to prolong."""
    reservation = _reservation()
    media = _media(restricted_prolong_ids=frozenset({reservation.reservation_id}))

    assert media.prolong_is_restricted(reservation) is True
    assert media.can_change_by(reservation, 30, MOMENT) is False
    # Shortening is still allowed: only prolonging is restricted.
    assert media.can_change_by(reservation, -10, MOMENT) is True


def test_shortening_may_not_move_the_end_into_the_past() -> None:
    """This is the same rule the portal's own web app applies."""
    media = _media()
    reservation = _reservation()

    # Ends 08:30, now 08:15: ten minutes still leaves it in the future.
    assert media.can_change_by(reservation, -10, MOMENT) is True
    # Thirty would end it at 08:00, which is behind us.
    assert media.can_change_by(reservation, -30, MOMENT) is False
    assert media.can_change_by(reservation, -15, MOMENT) is False
    # Exactly now counts as the past: a zero-length booking makes no sense.
    assert (
        media.can_change_by(reservation, -15, datetime(2026, 10, 5, 8, 15, tzinfo=UTC))
        is False
    )


def test_extension_is_limited_by_the_horizon() -> None:
    """Extending past the published window is refused rather than attempted."""
    media = _media(max_bookable_end=datetime(2026, 10, 5, 8, 40, tzinfo=UTC))
    reservation = _reservation()

    assert media.can_change_by(reservation, 10, MOMENT) is True
    assert media.can_change_by(reservation, 30, MOMENT) is False


def test_a_change_of_zero_is_never_useful() -> None:
    """Asking for no change at all is not an action."""
    assert _media().can_change_by(_reservation(), 0, MOMENT) is False


# --- merging a write response ------------------------------------------------


def _permit_response(**media_overrides: Any) -> dict[str, Any]:
    """Return a write response wrapping a single permit."""
    media: dict[str, Any] = {
        "TypeID": 9,
        "Code": "12345",
        "Balance": 7140,
        "ActiveReservations": [],
        "LicensePlates": [],
    }
    media.update(media_overrides)
    return {"Permit": {"Code": None, "ZoneCode": "ZONE1", "PermitMedias": [media]}}


def test_merge_replaces_the_media_of_the_write_response(
    account_payload: dict[str, Any],
) -> None:
    """The fresh balance and reservations from a write replace the cached ones."""
    account = Account.from_json(account_payload)

    merged = account.merged_with_permit(
        _permit_response(Balance=6000, ActiveReservations=[])
    )

    media = merged.media[0]
    assert media.balance == 6000
    assert media.reservations == ()
    assert merged.name == account.name


def test_merge_keeps_saved_plates_the_response_omits(
    account_payload: dict[str, Any],
) -> None:
    """Booking does not change the saved plates, so they must survive the merge."""
    account = Account.from_json(account_payload)
    assert account.media[0].license_plates

    merged = account.merged_with_permit(_permit_response())

    assert merged.media[0].license_plates == account.media[0].license_plates


def test_merge_keeps_the_zone_and_horizon_when_absent() -> None:
    """Metadata the response leaves out is inherited rather than lost."""
    account = Account.from_json(
        {
            "Permits": [
                {
                    "ZoneCode": "ZONE1",
                    "BlockTimes": [{"ValidUntil": "2026-12-03T23:00:00Z"}],
                    "PermitMedias": [{"TypeID": 9, "Code": "12345", "Balance": 7200}],
                }
            ]
        }
    )

    merged = account.merged_with_permit(
        {"Permit": {"PermitMedias": [{"TypeID": 9, "Code": "12345", "Balance": 10}]}}
    )

    media = merged.media[0]
    assert media.zone_code == "ZONE1"
    assert media.max_bookable_end == datetime(2026, 12, 3, 23, 0, tzinfo=UTC)


def test_merge_accepts_a_full_model_response(account_payload: dict[str, Any]) -> None:
    """A response carrying the whole model instead of one permit is used as-is."""
    merged = Account.from_json(account_payload).merged_with_permit(account_payload)

    assert merged.media[0].balance == 7140
    assert len(merged.media[0].reservations) == 1
