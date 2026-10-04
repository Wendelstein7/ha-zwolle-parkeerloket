"""An in-memory stand-in for the Parkeerloket portal, used by the tests.

Only the two endpoints this integration uses are emulated. Cookies are set
*without* the ``Secure`` flag because the test server speaks plain HTTP and
aiohttp's cookie jar refuses to send ``Secure`` cookies over ``http://``. The real
portal's ``Secure``/``__Host-`` semantics were verified against the live portal;
what these tests exercise is *our* logic: the CSRF header, re-login on a stale
session, and error handling.

Responses that override the normal answer are given as *factories*, because an
aiohttp ``web.Response`` can only be sent once: reusing one object makes the
second request hang until it times out.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aiohttp import web

BASE_PATH = "/DVSPortal"
XSRF_NAME = "__Host-Xsrf-DVSPortal"
SESSION_NAME = "__Host-DVS-Cookie"

HTML_ERROR = "<!DOCTYPE html><html lang='nl'><body><h1>Error</h1></body></html>"


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


class FakePortal:
    """Emulates the portal endpoints the client talks to, with full control."""

    def __init__(self, payload: dict[str, Any]) -> None:
        """Start with ``payload`` as the account state returned by both endpoints."""
        self.base_url = ""
        self.payload = payload

        # Set this to a business-error body to make ``login`` reject the credentials.
        self.login_rejection: dict[str, Any] | None = None
        # Set this to a response factory to bypass the normal ``getbase`` answer.
        self.getbase_override: Callable[[], web.Response] | None = None

        self.login_calls = 0
        self.getbase_calls = 0
        self.received_paths: list[str] = []
        self.received_xsrf: list[str | None] = []
        self.received_login_bodies: list[dict[str, Any]] = []

        self._sessions: set[str] = set()
        self._xsrf = ""

    @property
    def api_url(self) -> str:
        """Return the API base URL the client should be pointed at."""
        return f"{self.base_url}{BASE_PATH}"

    def expire_sessions(self) -> None:
        """Invalidate every issued session, as the portal does after a timeout."""
        self._sessions.clear()

    def _rotate_xsrf(self) -> str:
        """Issue a new CSRF token, mimicking the portal's rotation on login."""
        self._xsrf = f"csrf-token-{self.login_calls}"
        return self._xsrf

    def _session_is_valid(self, request: web.Request) -> bool:
        """Return whether the request carries a session cookie we issued."""
        return request.cookies.get(SESSION_NAME, "") in self._sessions

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

    def build_app(self) -> web.Application:
        """Return the aiohttp application implementing the emulated endpoints."""
        app = web.Application()
        app.router.add_post(f"{BASE_PATH}/api/login", self._handle_login)
        app.router.add_post(f"{BASE_PATH}/api/login/getbase", self._handle_getbase)
        return app
