"""The licence plate field for the Zwolle Parkeerloket integration.

This entity is both an input and a mirror. Typing into it sets the plate the book
button will use. Whenever the portal's own plate **changes** — a booking appears,
or a different one shows up — the field snaps to that value, so it always reflects
what is actually booked after an action. A draft you typed in between is left
alone, which means it survives polls and restarts.
"""

from __future__ import annotations

from homeassistant.components.text import RestoreText, TextMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, MAX_PLATE_INPUT_LENGTH
from .coordinator import ZwolleParkeerloketConfigEntry, ZwolleParkeerloketCoordinator
from .entity import ZwolleParkeerloketEntity
from .models import normalise_plate


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZwolleParkeerloketConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the licence plate field for a parking account."""
    async_add_entities([ZwolleParkeerloketPlateText(entry.runtime_data)])


class ZwolleParkeerloketPlateText(ZwolleParkeerloketEntity, RestoreText):
    """The licence plate to book, mirrored from the portal when it changes."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:car"
    _attr_mode = TextMode.TEXT
    _attr_native_max = MAX_PLATE_INPUT_LENGTH
    _attr_native_min = 0

    def __init__(self, coordinator: ZwolleParkeerloketCoordinator) -> None:
        """Create the licence plate field."""
        super().__init__(coordinator, "plate_draft")
        self._value: str | None = None
        # The last plate the portal reported, so a change can be told from a poll
        # that simply repeated itself.
        self._last_remote_plate: str | None = None

    @property
    def native_value(self) -> str | None:
        """Return the plate to book, or nothing when the field is empty."""
        return self._value

    async def async_set_value(self, value: str) -> None:
        """Store the plate the user typed, normalised.

        The API takes plates without separators and in capitals, so the value is
        normalised rather than stored as typed. Rejecting nonsense here beats
        booking the wrong car later.

        Raises:
            ServiceValidationError: the value is not a plausible licence plate.
        """
        if not value.strip():
            self._set_value(None)
            return
        try:
            plate = normalise_plate(value)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_plate",
                translation_placeholders={"plate": value},
            ) from err
        self._set_value(plate)

    async def async_added_to_hass(self) -> None:
        """Restore the last draft and take stock of what the portal reports."""
        await super().async_added_to_hass()

        restored = await self.async_get_last_text_data()
        if restored is not None and restored.native_value:
            self._value = restored.native_value

        if not self._value:
            # Nothing typed yet, so show what is booked instead of an empty field.
            self._value = self._remote_plate
        self.coordinator.async_set_plate_draft(self._value)

        # Treat the current state as the baseline: only a later *change* mirrors.
        self._last_remote_plate = self._remote_plate

    @callback
    def _handle_coordinator_update(self) -> None:
        """Mirror the portal's plate when it changes, keeping any draft."""
        remote = self._remote_plate
        if remote is not None and remote != self._last_remote_plate:
            self._set_value(remote)
            self._last_remote_plate = remote
        elif remote is None:
            # The booking ended. Keep the plate so it can be booked again easily,
            # but forget it as a baseline so a later booking mirrors again.
            self._last_remote_plate = None
        super()._handle_coordinator_update()

    @property
    def _remote_plate(self) -> str | None:
        """Return the plate of the booking the entities follow.

        That is the car whose session ends soonest, which is the booking the plate
        sensor reports. With several cars parked the field deliberately keeps the
        user's own draft rather than chasing whichever car is closest to leaving.
        """
        reservation = self.coordinator.primary_reservation
        if reservation is None or reservation.license_plate is None:
            return None
        return reservation.license_plate.value

    @callback
    def _set_value(self, plate: str | None) -> None:
        """Store a plate and let the buttons know which plate to book."""
        self._value = plate
        self.coordinator.async_set_plate_draft(plate)
        self.async_write_ha_state()
