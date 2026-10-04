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
    def primary_reservation(self) -> Reservation | None:
        """Return the reservation the glanceable entities describe.

        Several cars can be parked at once, so an entity that shows one booking
        shows the one whose session ends soonest — the most likely to need
        attention — and reports the rest as attributes.
        """
        return self.data.media.primary_reservation(dt_util.utcnow())

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

    async def async_start_booking(self, license_plate: str) -> None:
        """Book a session for a licence plate, starting now.

        The portal refuses a booking for a plate that already has an overlapping
        reservation (``Result`` 24), so the same rule is applied here first: the
        user gets a clear message without a round trip, and the portal is spared
        a request it would only reject.

        Raises:
            ServiceValidationError: the plate is unusable or already parked.
            HomeAssistantError: the portal could not be reached.
        """
        plate = self._normalise_plate(license_plate)
        media = self.data.media
        if media.active_reservation_for_plate(plate, dt_util.utcnow()) is not None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="plate_already_parked",
                translation_placeholders={"plate": plate},
            )

        permit = await self._async_write(
            self.client.async_create_reservation(media.code or "", plate)
        )
        self._apply_permit(permit)

    async def async_stop_booking(self, license_plate: str) -> None:
        """Cancel the session parking a plate, refunding any unused minutes.

        Raises:
            ServiceValidationError: that plate has no reservation to cancel.
            HomeAssistantError: the portal could not be reached.
        """
        await self.async_stop_reservation(self._require_reservation(license_plate))

    async def async_stop_reservation(self, reservation: Reservation) -> None:
        """Cancel one reservation, refunding any unused minutes.

        The calendar knows exactly which reservation an event stands for, so it
        comes in here directly; the plate-based action above resolves to the same
        call, which keeps both paths from drifting apart.
        """
        permit = await self._async_write(
            self.client.async_end_reservation(
                self.data.media.code or "", reservation.reservation_id
            )
        )
        self._apply_permit(permit)

    async def async_change_booking_time(self, license_plate: str, minutes: int) -> None:
        """Extend (positive) or shorten (negative) the session parking a plate.

        Raises:
            ServiceValidationError: that plate has no session, or the change is
                not possible.
            HomeAssistantError: the portal could not be reached.
        """
        await self.async_change_reservation_time(
            self._require_reservation(license_plate), minutes
        )

    async def async_change_reservation_time(
        self, reservation: Reservation, minutes: int
    ) -> None:
        """Extend (positive) or shorten (negative) one reservation.

        Raises:
            ServiceValidationError: the change is not possible.
            HomeAssistantError: the portal could not be reached.
        """
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

    def _require_reservation(self, license_plate: str) -> Reservation:
        """Return the reservation a plate refers to, or explain that there is none."""
        plate = self._normalise_plate(license_plate)
        reservation = self.data.media.reservation_for_plate(plate, dt_util.utcnow())
        if reservation is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_booking_for_plate",
                translation_placeholders={"plate": plate},
            )
        return reservation

    @staticmethod
    def _normalise_plate(license_plate: str) -> str:
        """Return the plate in the form the portal expects.

        Raises:
            ServiceValidationError: the value is not a plausible licence plate.
        """
        try:
            return normalise_plate(license_plate)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_plate",
                translation_placeholders={"plate": license_plate},
            ) from err

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
