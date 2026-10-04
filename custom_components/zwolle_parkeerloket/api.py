"""Async client for the Gemeente Zwolle Parkeerloket (DVSPortal) JSON API.

Authentication is cookie based: ``api/login`` returns a session cookie plus a CSRF
token cookie that has to be echoed back in the ``X-XSRF-TOKEN`` header. A single
``api/login/getbase`` call returns the balance, the reservations and the saved
plates.

This module deliberately has **no Home Assistant dependency**. The
:class:`aiohttp.ClientSession` is injected by the caller and failures are reported
through the exceptions below; translating them into Home Assistant concepts
(``ConfigEntryAuthFailed``, ``UpdateFailed``, ``invalid_auth``, ...) is the job of
the coordinator and the config flow.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Final

import aiohttp
from yarl import URL

from .const import API_BASE_URL, API_TIMEOUT_SECONDS, DEFAULT_PERMIT_MEDIA_TYPE_ID
from .models import Account

_LOGGER = logging.getLogger(__name__)

SESSION_COOKIE: Final = "__Host-DVS-Cookie"
XSRF_COOKIE: Final = "__Host-Xsrf-DVSPortal"
XSRF_HEADER: Final = "X-XSRF-TOKEN"

# The Meldnummer tab of the portal's login form.
LOGIN_METHOD_MELDNUMMER: Final = 2

# Business errors the portal reports in its response body. Its own web app shows
# the accompanying ErrorMessage to the user; we use the code to pick a message of
# our own where we can say something more useful.
RESULT_START_IN_PAST: Final = 13
RESULT_END_IN_PAST: Final = 16
RESULT_PLATE_NOT_FOUND: Final = 33


class DVSPortalError(Exception):
    """Base class for every error raised by this client."""


class CannotConnect(DVSPortalError):
    """Raised when the portal cannot be reached, or answers unusably."""


class InvalidAuth(DVSPortalError):
    """Raised when the portal rejects the credentials."""


class ApiError(DVSPortalError):
    """Raised when the portal reports a business or validation error."""

    def __init__(self, message: str, *, result: int | None = None) -> None:
        """Store the portal's message and, when given, its numeric result code."""
        super().__init__(message)
        self.result = result


def _session_is_stale(status: int, content_type: str) -> bool:
    """Return whether a response means the portal session is missing or expired.

    The portal answers a stale session on ``login/getbase`` with **HTTP 500 and an
    HTML body** rather than a 401, so a 5xx that is not JSON has to be treated as
    "log in again". This was verified against the live portal.
    """
    if status == 401:
        return True
    return status >= 500 and "json" not in content_type.lower()


def _raise_for_error_message(data: dict[str, Any]) -> None:
    """Raise :class:`ApiError` when the portal reported a business error with HTTP 200."""
    message = data.get("ErrorMessage")
    if not message:
        return
    result = data.get("Result")
    raise ApiError(str(message), result=result if isinstance(result, int) else None)


class DVSPortalClient:
    """Talk to the Parkeerloket API over an injected aiohttp session."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        meldnummer: str,
        pincode: str,
        permit_media_type_id: int = DEFAULT_PERMIT_MEDIA_TYPE_ID,
        base_url: str = API_BASE_URL,
    ) -> None:
        """Store the credentials; nothing is sent until a method is awaited."""
        self._session = session
        self._meldnummer = meldnummer
        self._pincode = pincode
        self._permit_media_type_id = permit_media_type_id
        self._base_url = base_url.rstrip("/")
        self._logged_in = False

    @property
    def logged_in(self) -> bool:
        """Return whether a session has been established successfully."""
        return self._logged_in

    async def async_login(self) -> Account:
        """Log in and return the account state carried by the login response.

        Raises:
            InvalidAuth: the Meldnummer/Pincode combination was rejected.
            CannotConnect: the portal could not be reached.
            ApiError: the portal answered with an unexpected payload.
        """
        data = await self._async_post(
            "login",
            {
                "identifier": self._meldnummer,
                "loginMethod": LOGIN_METHOD_MELDNUMMER,
                "password": self._pincode,
                "otp": None,
                "resetCode": None,
                "asIdentifier": None,
                "zipCode": None,
                "permitMediaTypeID": self._permit_media_type_id,
            },
            allow_reauth=False,
        )

        # A successful login carries the account state; a rejected one carries an
        # ErrorMessage instead, still with HTTP 200.
        if "Permits" not in data:
            raise InvalidAuth(
                str(data.get("ErrorMessage") or "the portal rejected the credentials")
            )

        self._logged_in = True
        return Account.from_json(data)

    async def async_get_account(self) -> Account:
        """Fetch the account state: balance, reservations and saved plates.

        Logs in again once if the portal reports that the session is no longer valid.

        Raises:
            InvalidAuth: re-authenticating failed.
            CannotConnect: the portal could not be reached, or stayed unusable.
            ApiError: the portal reported an error.
        """
        data = await self._async_post("login/getbase", None, allow_reauth=True)
        _raise_for_error_message(data)
        return Account.from_json(data)

    async def async_create_reservation(
        self,
        permit_media_code: str,
        license_plate: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Book a parking session starting now, for the portal's own default duration.

        ``DateFrom`` and ``DateUntil`` are deliberately left out. The portal then
        books from the current moment for ``ReservationDuration`` (60 minutes for
        this account). Sending an explicit start of "now" would race: the portal
        rejects a start that has become the past by the time it is processed.
        A different duration is reached by adjusting the reservation afterwards,
        which is the only thing the API offers anyway.

        Returns:
            The response body, which wraps the updated permit.

        Raises:
            ApiError: the portal rejected the booking, carrying its ``result`` code.
            InvalidAuth, CannotConnect: as described on :meth:`async_get_account`.
        """
        return await self._async_write(
            "reservation/create",
            {
                "LicensePlate": {"Value": license_plate, "Name": name},
                "permitMediaTypeID": self._permit_media_type_id,
                "permitMediaCode": permit_media_code,
            },
        )

    async def async_update_reservation(
        self, permit_media_code: str, reservation_id: int, minutes: int
    ) -> dict[str, Any]:
        """Change how long a reservation lasts, by a number of minutes.

        Positive values extend the reservation and debit the extra minutes,
        negative values shorten it and refund the difference. The portal adjusts
        by a delta only: the window and the licence plate of a reservation cannot
        be changed in place.

        Returns:
            The response body, which wraps the updated permit.

        Raises:
            ApiError: the portal rejected the change, carrying its ``result`` code.
            InvalidAuth, CannotConnect: as described on :meth:`async_get_account`.
        """
        return await self._async_write(
            "reservation/update",
            {
                "Minutes": minutes,
                "ReservationID": reservation_id,
                "permitMediaTypeID": self._permit_media_type_id,
                "permitMediaCode": permit_media_code,
            },
        )

    async def async_end_reservation(
        self, permit_media_code: str, reservation_id: int
    ) -> dict[str, Any]:
        """Cancel a reservation, refunding the minutes it had not used.

        Returns:
            The response body, which wraps the updated permit.

        Raises:
            ApiError: the portal rejected the cancellation, carrying its ``result`` code.
            InvalidAuth, CannotConnect: as described on :meth:`async_get_account`.
        """
        return await self._async_write(
            "reservation/end",
            {
                "ReservationID": reservation_id,
                "permitMediaTypeID": self._permit_media_type_id,
                "permitMediaCode": permit_media_code,
            },
        )

    async def _async_write(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST a change to the portal, turning its business errors into exceptions.

        The portal answers a rejected change with HTTP 200 and an ``ErrorMessage``
        body, so a bare status check would report failures as successes.
        """
        data = await self._async_post(path, payload, allow_reauth=True)
        _raise_for_error_message(data)
        return data

    async def _async_post(
        self,
        path: str,
        payload: dict[str, Any] | None,
        *,
        allow_reauth: bool,
    ) -> dict[str, Any]:
        """POST to the portal and decode the JSON body.

        When ``allow_reauth`` is set, a stale session results in one fresh login
        followed by exactly one retry, so an expired session can never turn into a
        retry loop.
        """
        url = f"{self._base_url}/api/{path}"
        try:
            async with asyncio.timeout(API_TIMEOUT_SECONDS):
                async with self._session.post(
                    url, json=payload, headers=self._headers()
                ) as response:
                    status = response.status
                    content_type = response.headers.get("Content-Type", "")
                    body = await response.text()
        except TimeoutError as err:
            raise CannotConnect(f"timeout while calling {path}") from err
        except aiohttp.ClientError as err:
            raise CannotConnect(
                f"connection error while calling {path}: {err}"
            ) from err

        if _session_is_stale(status, content_type):
            if allow_reauth:
                _LOGGER.debug(
                    "Session expired while calling %s, logging in again", path
                )
                await self.async_login()
                return await self._async_post(path, payload, allow_reauth=False)
            raise CannotConnect(f"the portal session for {path} is not valid")

        if status >= 400:
            raise ApiError(f"the portal returned HTTP {status} for {path}")

        try:
            data = json.loads(body)
        except ValueError as err:
            raise ApiError(
                f"the portal returned a non-JSON response for {path}"
            ) from err

        if not isinstance(data, dict):
            raise ApiError(f"the portal returned an unexpected response for {path}")

        return data

    def _headers(self) -> dict[str, str]:
        """Return the request headers, including the CSRF token when we have one.

        The token is re-read from the cookie jar on every request because the
        portal rotates it on each login. No ``User-Agent`` is set here: the caller
        owns the session and Home Assistant wants its own user agent to be used.
        """
        token = self._xsrf_token()
        return {XSRF_HEADER: token} if token else {}

    def _xsrf_token(self) -> str | None:
        """Return the CSRF token cookie, or ``None`` before the first login."""
        cookies = self._session.cookie_jar.filter_cookies(URL(self._base_url))
        if XSRF_COOKIE not in cookies:
            return None
        return cookies[XSRF_COOKIE].value


__all__ = [
    "RESULT_END_IN_PAST",
    "RESULT_PLATE_NOT_FOUND",
    "RESULT_START_IN_PAST",
    "SESSION_COOKIE",
    "XSRF_COOKIE",
    "XSRF_HEADER",
    "ApiError",
    "CannotConnect",
    "DVSPortalClient",
    "DVSPortalError",
    "InvalidAuth",
]
