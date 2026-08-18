"""Response headers that were simply not being sent.

Cheap, safe, and each closes a real gap:

  · the DESKTOP carries a one-click Allow / Deny that grants capability, so no
    site may frame it — `frame-ancestors 'none'` + `X-Frame-Options: DENY`
  · an APP page IS framed, but only by the desktop that served it —
    `frame-ancestors 'self'`, so a foreign site cannot embed somebody's app and
    read their clicks
  · `nosniff`, `no-referrer`, and same-origin opener apply everywhere and cannot
    break a server that already serves correct content types and never wants a
    session-bearing URL to leak in a Referer.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-hdr-home-"))

from fastapi.testclient import TestClient                       # noqa: E402

from agentos import server as servermod                         # noqa: E402


@pytest.fixture()
def api():
    with TestClient(servermod.app) as c:
        yield c


def test_the_desktop_refuses_to_be_framed(api):
    r = api.get("/")
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "frame-ancestors 'none'" in r.headers.get("Content-Security-Policy", "")


def test_the_baseline_headers_are_on_every_response(api):
    r = api.get("/")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("Referrer-Policy") == "no-referrer"
    assert r.headers.get("Cross-Origin-Opener-Policy") == "same-origin"


def test_an_app_page_may_be_framed_by_its_own_origin_only(api):
    aid = servermod.state["store"].save_app("hdrprobe", "", "", "<h1>x</h1>")
    r = api.get(f"/api/apps/{aid}/page")
    csp = r.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors 'self'" in csp, csp
    # NOT 'none' — the desktop must still be able to embed it
    assert "'none'" not in csp


def test_api_json_still_carries_the_safe_baseline(api):
    r = api.get("/api/config")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    # but an API route is neither a document nor an app page, so no framing header
    assert "X-Frame-Options" not in r.headers


def test_https_gets_a_secure_cookie_and_loopback_does_not():
    """The Secure flag must ride an HTTPS sign-in (a tunnel) but never a plain
    loopback one, or the browser drops the cookie and nobody stays signed in on
    their own machine."""
    class Req:
        def __init__(self, scheme, xfp=None):
            self.url = type("U", (), {"scheme": scheme})()
            self.headers = {"x-forwarded-proto": xfp} if xfp else {}

    assert servermod._is_https(Req("https")) is True
    assert servermod._is_https(Req("http", "https")) is True     # behind a TLS proxy
    assert servermod._is_https(Req("http")) is False


def test_loopback_never_gets_hsts(api):
    """HSTS on plain http://localhost would make the machine unreachable for a
    year — it must ride TLS only, so a loopback response must not carry it."""
    r = api.get("/")
    assert "Strict-Transport-Security" not in r.headers
