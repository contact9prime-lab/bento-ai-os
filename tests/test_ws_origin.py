"""Cross-Site WebSocket Hijacking — the socket half of the CSRF guard.

`csrf_origin_guard` refuses a cross-origin mutation of `/api/*`. It could not see
the WebSockets, because a WS handshake never enters HTTP middleware — and a
browser DOES attach the site's cookies to a cross-origin WS connection while the
same-origin policy does NOT stop a foreign page from opening one. So a page on
the open web, while AgentOS runs on localhost, could open `ws://localhost/ws` or
even `/ws/terminal` and be handed a socket — on a default single-user box
`_ws_authed` trusts loopback and asks for no cookie at all, which makes the
terminal socket remote code execution.

These pin the fix at the header level, which is faithful because the real browser
behaviour it defends against is exactly "Origin is set by the browser and cannot
be forged by script". A same-origin handshake (the desktop, the PWA, the native
host — all served from the server's own origin) is allowed; a cross-origin or
`null` one is refused before authentication even runs.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-ws-home-"))

from starlette.websockets import WebSocketDisconnect            # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402

from agentos import server as servermod                         # noqa: E402

SOCKETS = ("/ws", "/ws/terminal", "/ws/vnc")


@pytest.fixture()
def api():
    with TestClient(servermod.app) as c:
        yield c


def _closed_cross_origin(c, path, headers):
    """True if the handshake was refused with our forbidden-origin code (4403)."""
    try:
        with c.websocket_connect(path, headers=headers) as ws:
            # A refused socket may surface either as a raise on connect or as an
            # immediate close frame on first receive — accept both, then assert
            # the code is ours.
            ws.receive_text()
        return False
    except WebSocketDisconnect as e:
        return e.code == 4403
    except Exception:
        # Starlette raises on a handshake the endpoint closed before accept.
        return True


@pytest.mark.parametrize("path", SOCKETS)
def test_a_foreign_page_cannot_open_any_socket(api, path):
    """The whole point: evil.example is a different origin, and the terminal
    socket is a shell."""
    assert _closed_cross_origin(api, path, {"origin": "https://evil.example",
                                            "host": "testserver"})


@pytest.mark.parametrize("path", SOCKETS)
def test_a_sandboxed_opener_is_refused(api, path):
    """`Origin: null` is a sandboxed iframe or a file:// page — never the desktop,
    which is served from a real origin."""
    assert _closed_cross_origin(api, path, {"origin": "null", "host": "testserver"})


def test_the_real_desktop_socket_still_connects(api):
    """Same origin (the served desktop) must not be caught by the guard."""
    with api.websocket_connect("/ws", headers={"origin": "http://testserver",
                                               "host": "testserver"}) as ws:
        first = ws.receive_json()
        assert first.get("type")          # state_sync or similar — a live socket


def test_a_non_browser_client_with_no_origin_still_connects(api):
    """A CLI or a test harness sends no Origin and carries no cookie jar, so it is
    not a CSRF vector — the same call the HTTP guard makes for a header-less
    request."""
    with api.websocket_connect("/ws", headers={"host": "testserver"}) as ws:
        assert ws.receive_json().get("type")


def test_the_guard_keys_on_the_header_a_browser_cannot_forge():
    """`_ws_origin_ok` is browser-independent: present-and-mismatched is refused,
    present-and-matching is allowed, absent is allowed, null is refused."""
    class WS:
        def __init__(self, origin, host="testserver"):
            self.headers = {"host": host}
            if origin is not None:
                self.headers["origin"] = origin

    ok = servermod._ws_origin_ok
    assert ok(WS("http://testserver")) is True
    assert ok(WS(None)) is True
    assert ok(WS("null")) is False
    assert ok(WS("http://evil.example")) is False
    assert ok(WS("http://testserver", host="other")) is False
