"""An in-memory stand-in for the Parkeerloket portal, used by the tests.

It emulates the endpoints this integration uses, including the three that change
a booking, so the actions can be tested without spending real balance.

Simplifications, all of them deliberate:

* cookies are set *without* ``Secure`` because the test server speaks plain HTTP
  and aiohttp's cookie jar refuses to send ``Secure`` cookies over ``http://``.
  The real portal's ``Secure``/``__Host-`` semantics were verified against the
  live portal; what these tests exercise is our own logic.
* an extend or shorten changes the balance one-for-one, while the real portal only
  charges for minutes that fall inside a paid window.
* a created reservation always lasts the permit's ``ReservationDuration``.

Responses that override the normal answer are given as *factories*, because an
aiohttp ``web.Response`` can only be sent once: reusing one object makes the
second request hang until it times out.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from aiohttp import web

BASE_PATH = "/DVSPortal"
XSRF_NAME = "__Host-Xsrf-DVSPortal"
SESSION_NAME = "__Host-DVS-Cookie"

HTML_ERROR = "<!DOCTYPE html><html lang='nl'><body><h1>Error</h1></body></html>"

CREATE_PATH = f"{BASE_PATH}/api/reservation/create"
UPDATE_PATH = f"{BASE_PATH}/api/reservation/update"
END_PATH = f"{BASE_PATH}/api/reservation/end"

# Business errors, with the codes the portal uses.
REJECTION_END_IN_PAST = {
    "ErrorMessage": "De eindtijd ligt in het verleden",
    "Result": 16,
}
REJECTION_PLATE_NOT_FOUND = {
    "ErrorMessage": "Het kenteken is niet gevonden",
    "Result": 33,
    "LoginStatus": 0,
    "RequiresOtp": False,
}
REJECTION_UNKNOWN = {"ErrorMessage": "Onbekende fout", "Result": 99}


def response_factory(
    status: int, content_type: str, text: str
) -> Callable[[], web.Response]:
    """Return a factory that produces a fresh response for every request."""

    def factory() -> web.Response:
        return web.Response(status=status, content_type=content_type, text=text)

    return factory


def json_response_factory(payload: dict[str, Any]) -> Callable[[], web.Response]:
    """Return a factory that produces a fresh JSON response for every request."""

    def factory() -> web.Response:
        return web.json_response(payload)

    return factory


def _iso(moment: datetime) -> str:
    """Render a timestamp the way the portal does."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakePortal:
    """Emulates the portal endpoints the client talks to, with full control."""

    def __init__(self, payload: dict[str, Any]) -> None:
        """Start with ``payload`` as the account state returned by both endpoints."""
        self.base_url = ""
        self.payload = payload

        # Set to a business-error body to make ``login`` reject the credentials.
        self.login_rejection: dict[str, Any] | None = None
        # Set to a response factory to bypass the normal ``getbase`` answer.
        self.getbase_override: Callable[[], web.Response] | None = None
        # Set to a business-error body to reject a booking action.
        self.create_rejection: dict[str, Any] | None = None
        self.update_rejection: dict[str, Any] | None = None
        self.end_rejection: dict[str, Any] | None = None

        self.login_calls = 0
        self.getbase_calls = 0
        self.received_paths: list[str] = []
        self.received_xsrf: list[str | None] = []
        self.received_login_bodies: list[dict[str, Any]] = []
        self.received_writes: list[tuple[str, dict[str, Any]]] = []

        self._sessions: set[str] = set()
        self._xsrf = ""
        self._next_reservation_id = 9000

    # --- state helpers ------------------------------------------------------

    @property
    def api_url(self) -> str:
        """Return the API base URL the client should be pointed at."""
        return f"{self.base_url}{BASE_PATH}"

    @property
    def create_path(self) -> str:
        """Return the path of the create endpoint."""
        return CREATE_PATH

    @property
    def update_path(self) -> str:
        """Return the path of the update endpoint."""
        return UPDATE_PATH

    @property
    def end_path(self) -> str:
        """Return the path of the end endpoint."""
        return END_PATH

    @property
    def permit(self) -> dict[str, Any]:
        """Return the account's single permit, which is what writes answer with."""
        return self.payload["Permits"][0]

    @property
    def media(self) -> dict[str, Any]:
        """Return the permit medium the integration acts on."""
        return self.permit["PermitMedias"][0]

    def permit_response(self) -> dict[str, Any]:
        """Return the body a write answers with: a single permit."""
        return {"Permit": self.permit}

    def expire_sessions(self) -> None:
        """Invalidate every issued session, as the portal does after a timeout."""
        self._sessions.clear()

    def writes_to(self, path: str) -> list[dict[str, Any]]:
        """Return the bodies of every write sent to one endpoint."""
        return [body for received, body in self.received_writes if received == path]

    def _rotate_xsrf(self) -> str:
        """Issue a new CSRF token, mimicking the portal's rotation on login."""
        self._xsrf = f"csrf-token-{self.login_calls}"
        return self._xsrf

    def _session_is_valid(self, request: web.Request) -> bool:
        """Return whether the request carries a session cookie we issued."""
        return request.cookies.get(SESSION_NAME, "") in self._sessions

    def _find_reservation(self, reservation_id: int) -> dict[str, Any] | None:
        """Return a reservation by id, if it exists."""
        for reservation in self.media["ActiveReservations"]:
            if reservation["ReservationID"] == reservation_id:
                return reservation
        return None

    # --- endpoints ----------------------------------------------------------

    async def _handle_login(self, request: web.Request) -> web.Response:
        self.login_calls += 1
        self.received_paths.append(request.path)
        self.received_xsrf.append(request.headers.get("X-XSRF-TOKEN"))
        self.received_login_bodies.append(await request.json())

        if self.login_rejection is not None:
            # The portal answers a failed login with HTTP 200 and an error body.
            return web.json_response(self.login_rejection)

        session_id = f"session-{self.login_calls}"
        self._sessions.add(session_id)
        response = web.json_response(self.payload)
        response.set_cookie(SESSION_NAME, session_id, path="/", httponly=True)
        response.set_cookie(XSRF_NAME, self._rotate_xsrf(), path="/")
        return response

    async def _handle_getbase(self, request: web.Request) -> web.Response:
        self.getbase_calls += 1
        self.received_paths.append(request.path)
        self.received_xsrf.append(request.headers.get("X-XSRF-TOKEN"))

        if not self._session_is_valid(request):
            # The real portal answers a stale session with 500 + HTML, not 401.
            return web.Response(status=500, content_type="text/html", text=HTML_ERROR)

        if self.getbase_override is not None:
            return self.getbase_override()

        return web.json_response(self.payload)

    async def _handle_create(self, request: web.Request) -> web.Response:
        return await self._handle_write(request, CREATE_PATH, self.create_rejection)

    async def _handle_update(self, request: web.Request) -> web.Response:
        body = await self._read_write(request)
        if isinstance(body, web.Response):
            return body

        if self.update_rejection is not None:
            return web.json_response(self.update_rejection)

        reservation = self._find_reservation(body["ReservationID"])
        if reservation is None:
            return web.json_response(REJECTION_END_IN_PAST)

        minutes = int(body["Minutes"])
        new_until = self._parse(reservation["ValidUntil"]) + timedelta(minutes=minutes)
        if new_until <= datetime.now(UTC):
            return web.json_response(REJECTION_END_IN_PAST)

        reservation["ValidUntil"] = _iso(new_until)
        # Simplification: one minute of balance per minute of reservation.
        self.media["Balance"] += 0 if minutes >= 0 else abs(minutes)
        if minutes > 0:
            self.media["Balance"] -= minutes
        return web.json_response(self.permit_response())

    async def _handle_end(self, request: web.Request) -> web.Response:
        body = await self._read_write(request)
        if isinstance(body, web.Response):
            return body

        if self.end_rejection is not None:
            return web.json_response(self.end_rejection)

        reservation = self._find_reservation(body["ReservationID"])
        if reservation is None:
            return web.json_response(REJECTION_UNKNOWN)

        self.media["ActiveReservations"].remove(reservation)
        self.media["Balance"] += int(reservation.get("Units") or 0)
        return web.json_response(self.permit_response())

    async def _handle_write(
        self,
        request: web.Request,
        path: str,
        rejection: dict[str, Any] | None,
    ) -> web.Response:
        """Book a new reservation from ``now`` for the permit's own duration."""
        body = await self._read_write(request)
        if isinstance(body, web.Response):
            return body

        if rejection is not None:
            return web.json_response(rejection)

        plate = (body.get("LicensePlate") or {}).get("Value")
        if plate is None:
            return web.json_response(REJECTION_PLATE_NOT_FOUND)

        now = datetime.now(UTC)
        duration = int(self.permit.get("ReservationDuration") or 60)
        self._next_reservation_id += 1
        self.media["ActiveReservations"].append(
            {
                "ReservationID": self._next_reservation_id,
                "ValidFrom": _iso(now),
                "ValidUntil": _iso(now + timedelta(minutes=duration)),
                "LicensePlate": {"Value": plate, "DisplayValue": plate, "Name": None},
                "Units": 0,
                "PermitMediaCode": self.media["Code"],
            }
        )
        return web.json_response(self.permit_response())

    async def _read_write(self, request: web.Request) -> dict[str, Any] | web.Response:
        """Validate the session and record the body of a write request."""
        self.received_paths.append(request.path)
        self.received_xsrf.append(request.headers.get("X-XSRF-TOKEN"))

        if not self._session_is_valid(request):
            return web.Response(status=500, content_type="text/html", text=HTML_ERROR)

        body = await request.json()
        self.received_writes.append((str(request.path), body))
        return body

    @staticmethod
    def _parse(value: str) -> datetime:
        """Parse one of the portal's timestamps."""
        return datetime.fromisoformat(value)

    def build_app(self) -> web.Application:
        """Return the aiohttp application implementing the emulated endpoints."""
        app = web.Application()
        app.router.add_post(f"{BASE_PATH}/api/login", self._handle_login)
        app.router.add_post(f"{BASE_PATH}/api/login/getbase", self._handle_getbase)
        app.router.add_post(CREATE_PATH, self._handle_create)
        app.router.add_post(UPDATE_PATH, self._handle_update)
        app.router.add_post(END_PATH, self._handle_end)
        return app
