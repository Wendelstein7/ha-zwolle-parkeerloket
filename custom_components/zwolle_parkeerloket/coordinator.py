"""Polling coordinator for the Zwolle Bezoekersparkeren integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    RESULT_END_IN_PAST,
    RESULT_PLATE_NOT_FOUND,
    RESULT_START_IN_PAST,
    ApiError,
    CannotConnect,
    DVSPortalClient,
    InvalidAuth,
)
from .const import (
    CONF_MELDNUMMER,
    CONF_PERMIT_MEDIA_TYPE_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_PERMIT_MEDIA_TYPE_ID,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)
from .models import Account, PermitMedia, Reservation, normalise_plate

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ZwolleParkeerloketData:
    """The account state the entities read from the coordinator."""

    account: Account
    media: PermitMedia


class ZwolleParkeerloketCoordinator(DataUpdateCoordinator[ZwolleParkeerloketData]):
    """Poll the portal's single read endpoint for this account."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: DVSPortalClient,
    ) -> None:
        """Set up the coordinator with the entry's credentials and interval."""
        self.client = client
        self.meldnummer: str = entry.data[CONF_MELDNUMMER]
        self.permit_media_type_id: int = entry.data.get(
            CONF_PERMIT_MEDIA_TYPE_ID, DEFAULT_PERMIT_MEDIA_TYPE_ID
        )
        # The licence plate the user last typed, used when booking from a button.
        self.plate_draft: str | None = None
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                minutes=entry.options.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES
                )
            ),
        )

    async def _async_setup(self) -> None:
        """Log in once, before the first data fetch."""
        try:
            await self.client.async_login()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(
                f"the portal rejected the credentials: {err}"
            ) from err
        except CannotConnect as err:
            raise UpdateFailed(f"could not reach the portal: {err}") from err

    async def _async_update_data(self) -> ZwolleParkeerloketData:
        """Fetch the account state and select this entry's permit medium."""
        try:
            account = await self.client.async_get_account()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(
                f"the portal rejected the credentials: {err}"
            ) from err
        except (CannotConnect, ApiError) as err:
            raise UpdateFailed(f"could not read the account: {err}") from err

        media = account.find_media(self.meldnummer, self.permit_media_type_id)
        if media is None:
            raise UpdateFailed(
                f"Meldnummer {self.meldnummer} is not among the account's permits"
            )
        return ZwolleParkeerloketData(account=account, media=media)

    # --- actions ------------------------------------------------------------

    @property
    def current_reservation(self) -> Reservation | None:
        """Return the reservation covering now, else the soonest upcoming one."""
        return self.data.media.current_reservation(dt_util.utcnow())

    @property
    def bookable_plate(self) -> str | None:
        """Return the plate a button would book: the draft, else the booked plate."""
        if self.plate_draft:
            return self.plate_draft
        reservation = self.current_reservation
        if reservation is not None and reservation.license_plate is not None:
            return reservation.license_plate.value
        return None

    @callback
    def async_set_plate_draft(self, plate: str | None) -> None:
        """Remember the plate the user typed, so a button can book it.

        The draft lives on the coordinator rather than in its data, so listeners
        are told explicitly: the book button's availability depends on it, and the
        user expects the button to become usable as soon as a plate is typed,
        rather than at the next poll.
        """
        if plate == self.plate_draft:
            return
        self.plate_draft = plate
        self.async_update_listeners()

    async def async_start_booking(
        self, license_plate: str | None = None, *, force: bool = False
    ) -> None:
        """Book a parking session starting now.

        The portal only allows one reservation at a time and a booking costs
        balance, so an existing reservation blocks this unless ``force`` is set.

        Raises:
            ServiceValidationError: the request cannot be made as asked.
            HomeAssistantError: the portal could not be reached.
        """
        plate_value = license_plate or self.bookable_plate
        if not plate_value:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="plate_required"
            )
        try:
            plate = normalise_plate(plate_value)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_plate",
                translation_placeholders={"plate": plate_value},
            ) from err

        if not force and self.current_reservation is not None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="booking_already_exists"
            )

        permit = await self._async_write(
            self.client.async_create_reservation(self.data.media.code or "", plate)
        )
        self._apply_permit(permit)

    async def async_stop_booking(self) -> None:
        """Cancel the current reservation, refunding any unused minutes.

        Raises:
            ServiceValidationError: there is no reservation to cancel.
            HomeAssistantError: the portal could not be reached.
        """
        reservation = self._require_reservation()
        permit = await self._async_write(
            self.client.async_end_reservation(
                self.data.media.code or "", reservation.reservation_id
            )
        )
        self._apply_permit(permit)

    async def async_change_booking_time(self, minutes: int) -> None:
        """Extend (positive) or shorten (negative) the current reservation.

        Raises:
            ServiceValidationError: there is nothing to change, or the change is
                not possible.
            HomeAssistantError: the portal could not be reached.
        """
        reservation = self._require_reservation()
        now = dt_util.utcnow()
        media = self.data.media

        if not media.can_change_by(reservation, minutes, now):
            key = "cannot_shorten" if minutes < 0 else "cannot_extend"
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=key,
                translation_placeholders={
                    "minutes": str(abs(minutes)),
                    "until": reservation.valid_until.astimezone().strftime("%H:%M"),
                },
            )

        permit = await self._async_write(
            self.client.async_update_reservation(
                media.code or "", reservation.reservation_id, minutes
            )
        )
        self._apply_permit(permit)

    def _require_reservation(self) -> Reservation:
        """Return the current reservation, or explain that there is none."""
        reservation = self.current_reservation
        if reservation is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_booking"
            )
        return reservation

    async def _async_write(self, request: Any) -> Mapping[str, Any]:
        """Await a write request, translating its failures into Home Assistant errors."""
        try:
            return await request
        except ApiError as err:
            raise self._map_api_error(err) from err
        except CannotConnect as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="cannot_connect_write",
            ) from err
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(
                f"the portal rejected the credentials: {err}"
            ) from err

    @staticmethod
    def _map_api_error(err: ApiError) -> HomeAssistantError:
        """Translate a rejected change into an error the user can act on.

        The portal answers with a code and a Dutch sentence. Where the code tells
        us something more useful than the sentence, we say it ourselves; otherwise
        the portal's own wording is passed through, since it is the portal's UX.
        """
        if err.result in (RESULT_START_IN_PAST, RESULT_END_IN_PAST):
            key = "reservation_rejected_time"
        elif err.result == RESULT_PLATE_NOT_FOUND:
            key = "plate_not_found"
        else:
            return ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="portal_rejected",
                translation_placeholders={"message": str(err)},
            )
        return ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders={"message": str(err)},
        )

    @callback
    def _apply_permit(self, payload: Mapping[str, Any]) -> None:
        """Update the entities from the permit a write response returned.

        The write responses carry the updated permit, so there is no need for an
        extra poll to see the result of an action.
        """
        account = self.data.account.merged_with_permit(payload)
        media = account.find_media(self.meldnummer, self.permit_media_type_id)
        if media is None:
            _LOGGER.warning(
                "the portal no longer reports Meldnummer %s; refreshing instead",
                self.meldnummer,
            )
            self.hass.async_create_task(self.async_request_refresh())
            return
        self.async_set_updated_data(
            ZwolleParkeerloketData(account=account, media=media)
        )


type ZwolleParkeerloketConfigEntry = ConfigEntry[ZwolleParkeerloketCoordinator]
