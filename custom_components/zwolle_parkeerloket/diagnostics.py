"""Diagnostics support for the Zwolle Parkeerloket integration.

The Meldnummer, the Pincode, the permit media code and every licence plate are
redacted: they are personal data and diagnostics are meant to be shareable.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_MELDNUMMER, CONF_PERMIT_MEDIA_TYPE_ID, CONF_PINCODE
from .coordinator import ZwolleParkeerloketConfigEntry
from .models import LicensePlate, Reservation

TO_REDACT = {CONF_MELDNUMMER, CONF_PINCODE, CONF_PERMIT_MEDIA_TYPE_ID}


def _redact_plate(plate: LicensePlate | None) -> dict[str, Any] | None:
    """Describe a licence plate without revealing it."""
    if plate is None:
        return None
    return {"value": "**REDACTED**", "name": "**REDACTED**"}


def _describe_reservation(reservation: Reservation) -> dict[str, Any]:
    """Describe a reservation without revealing its plate."""
    return {
        "reservation_id": reservation.reservation_id,
        "valid_from": reservation.valid_from.isoformat(),
        "valid_until": reservation.valid_until.isoformat(),
        "units": reservation.units,
        "license_plate": _redact_plate(reservation.license_plate),
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ZwolleParkeerloketConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator = entry.runtime_data
    media = coordinator.data.media

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "account": {
            "name": coordinator.data.account.name,
            "permit_media_count": len(coordinator.data.account.media),
            "zone_code": media.zone_code,
            "media_type_id": media.type_id,
            "balance": media.balance,
            "reservation_count": len(media.reservations),
            "reservations": [
                _describe_reservation(reservation) for reservation in media.reservations
            ],
            "license_plate_count": len(media.license_plates),
            "license_plates": [_redact_plate(plate) for plate in media.license_plates],
        },
    }
