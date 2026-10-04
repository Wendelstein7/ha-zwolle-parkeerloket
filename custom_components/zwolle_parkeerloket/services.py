"""Service actions for the Zwolle Bezoekersparkeren integration.

The actions act on the account rather than on a single entity, so they are
registered on the integration domain and their target is resolved to a config
entry, following Home Assistant's guidance for actions that create a resource
belonging to the account.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service

from .const import DOMAIN
from .coordinator import ZwolleParkeerloketCoordinator

SERVICE_START_BOOKING = "start_booking"
SERVICE_STOP_BOOKING = "stop_booking"
SERVICE_CHANGE_BOOKING_TIME = "change_booking_time"

ATTR_LICENSE_PLATE = "license_plate"
ATTR_MINUTES = "minutes"

# The plate is required rather than guessed at: the portal keeps several
# reservations at once, so acting on "the" booking without naming one could
# cancel the wrong car. Every action names its booking by licence plate.
START_BOOKING_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required(ATTR_LICENSE_PLATE): vol.All(str, vol.Length(min=4, max=16)),
    }
)
STOP_BOOKING_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required(ATTR_LICENSE_PLATE): vol.All(str, vol.Length(min=4, max=16)),
    }
)
CHANGE_BOOKING_TIME_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required(ATTR_LICENSE_PLATE): vol.All(str, vol.Length(min=4, max=16)),
        vol.Required(ATTR_MINUTES): vol.All(
            vol.Coerce(int), vol.Range(min=-24 * 60, max=24 * 60)
        ),
    }
)


async def _async_coordinators(call: ServiceCall) -> list[ZwolleParkeerloketCoordinator]:
    """Return the coordinator of every account the call targets.

    Raises:
        ServiceValidationError: the call did not target a parking account.
    """
    entry_ids = await service.async_extract_config_entry_ids(call)
    coordinators = [
        entry.runtime_data
        for entry_id in entry_ids
        if (entry := call.hass.config_entries.async_get_entry(entry_id)) is not None
        and entry.domain == DOMAIN
        and isinstance(entry.runtime_data, ZwolleParkeerloketCoordinator)
    ]
    if not coordinators:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_target"
        )
    return coordinators


async def _async_start_booking(call: ServiceCall) -> None:
    """Book a parking session starting now."""
    for coordinator in await _async_coordinators(call):
        await coordinator.async_start_booking(call.data[ATTR_LICENSE_PLATE])


async def _async_stop_booking(call: ServiceCall) -> None:
    """Cancel the parking session of a licence plate."""
    for coordinator in await _async_coordinators(call):
        await coordinator.async_stop_booking(call.data[ATTR_LICENSE_PLATE])


async def _async_change_booking_time(call: ServiceCall) -> None:
    """Extend or shorten the parking session of a licence plate."""
    for coordinator in await _async_coordinators(call):
        await coordinator.async_change_booking_time(
            call.data[ATTR_LICENSE_PLATE], call.data[ATTR_MINUTES]
        )


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions, once per Home Assistant run."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_BOOKING,
        _async_start_booking,
        schema=START_BOOKING_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_BOOKING,
        _async_stop_booking,
        schema=STOP_BOOKING_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CHANGE_BOOKING_TIME,
        _async_change_booking_time,
        schema=CHANGE_BOOKING_TIME_SCHEMA,
    )
