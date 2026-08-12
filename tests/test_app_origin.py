"""App origin isolation (docs/design/tenant-isolation.md, Piece 1).

Apps run in opaque-origin iframes, so their fetches carry `Origin: null` — a header
the browser sets and no script can forge. The desktop's carry the real origin. That
is the whole boundary: a same-origin mutation is the user; a cross-origin one is
refused unless it is an app reaching its own runtime with a valid app token.

Verified end to end in a real browser separately (the forge is blocked, appTool and
appData still work, the app cannot read the parent). These pin the server contract
so it cannot regress: the guard is browser-independent because it keys on a header
browsers set, so a header-level test is faithful.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from fastapi.testclient import TestClient                          # noqa: E402
from agentos import server as servermod                           # noqa: E402

DESK = {"origin": "http://testserver", "host": "testserver"}       # the real desktop
APP = {"origin": "null", "host": "testserver"}                     # an opaque app iframe


@pytest.fixture()
def api():
    with TestClient(servermod.app) as c:
        yield c


def _app_token(c) -> str:
    aid = servermod.state["store"].save_app("probe", "", "", "<h1>x</h1>")
    tok = "tok-" + aid
    servermod.state["app_tokens"][tok] = {"app_id": aid, "issued": 0}
    return tok


# ---------------------------------------------------------------------------
# The escape is closed
# ---------------------------------------------------------------------------

def test_an_opaque_app_cannot_mutate_a_normal_route(api):
    """This is the verified escape: POST /api/grants from an app, forging a shell
    grant. A cross-origin request to a non-runtime route is refused."""
    r = api.post("/api/grants", headers=APP,
                 json={"principal_kind": "app", "principal_id": "evil",
                       "action": "tool.use", "resource": "tool:run_command*",
                       "effect": "allow"})
    assert r.status_code == 403 and "cross-origin" in r.json()["error"]


def test_an_opaque_app_cannot_reach_the_config(api):
    assert api.put("/api/config", headers=APP, json={"providers": {}}).status_code == 403


def test_a_tokenless_app_call_to_the_runtime_is_refused(api):
    """The app runtime answers a valid token or the same-origin desktop — a
    cross-origin call with neither cannot fall through to the user."""
    r = api.post("/api/tool", headers=APP, json={"name": "system_info", "args": {}})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# The desktop and legitimate apps still work
# ---------------------------------------------------------------------------

def test_the_desktop_can_mutate_because_it_is_same_origin(api):
    assert api.put("/api/config", headers=DESK, json={"agent_name": "Desk"}).status_code == 200


def test_an_app_reaches_its_runtime_with_a_valid_token(api):
    tok = _app_token(api)
    r = api.post("/api/tool", headers={**APP, "x-app-token": tok},
                 json={"name": "system_info", "args": {}})
    assert r.status_code == 200


def test_the_runtime_answers_the_cors_preflight(api):
    r = api.options("/api/tool", headers={**APP,
                                          "access-control-request-method": "POST"})
    assert r.status_code == 204
    assert r.headers.get("access-control-allow-origin") == "null"
    assert "X-App-Token" in r.headers.get("access-control-allow-headers", "")


def test_a_runtime_response_carries_cors_so_the_opaque_app_can_read_it(api):
    tok = _app_token(api)
    r = api.post("/api/tool", headers={**APP, "x-app-token": tok},
                 json={"name": "system_info", "args": {}})
    assert r.headers.get("access-control-allow-origin") == "null"


# ---------------------------------------------------------------------------
# Non-browser clients and safe methods are unaffected
# ---------------------------------------------------------------------------

def test_a_non_browser_client_with_no_origin_is_not_gated(api):
    """curl, the mobile app, the TUI send no Origin and carry no ambient cookie to
    abuse — not a CSRF vector, so the guard leaves them to the auth gate."""
    assert api.put("/api/config", json={"agent_name": "CLI"}).status_code == 200


def test_reads_are_never_gated(api):
    assert api.get("/api/config", headers=APP).status_code == 200


def test_the_app_iframes_are_opaque_origin():
    """The server guard only works because the iframe has no allow-same-origin —
    that is what makes an app's Origin 'null'. If a future edit puts it back, the
    guard still passes but the isolation is gone, so pin it here."""
    js = Path(__file__).resolve().parents[1] / "agentos" / "ui" / "src" / "js"
    for f in ("05-apps-registry.js", "06a-deck.js", "07-widgets.js", "26-studio.js"):
        src = (js / f).read_text()
        for line in src.splitlines():
            if "/api/apps/" in line and "sandbox=" in line:
                assert "allow-same-origin" not in line, f"{f}: app iframe regained allow-same-origin"


# ---------------------------------------------------------------------------
# The other direction: an app's METADATA is drawn by the desktop, not the iframe
# ---------------------------------------------------------------------------

def test_an_app_icon_can_never_become_markup_in_the_desktop():
    """`iconTile()` draws an app's icon in the PARENT page, not the sandbox.

    An icon is written by the builder model, so it has to be safe for anything a
    model might emit — and it was interpolated raw into innerHTML. An icon of
    `<img src=x onerror=…>` therefore executed in the desktop's own origin, which is
    the boundary every other test in this file defends. The same hole drew a 70-char
    icon URL as text across the app name and the sidebar behind it.

    Read from source: the fix is that the value is escaped AND that anything which
    is not a short glyph never reaches the text branch at all.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "agentos" / "ui" / "src" / "js"
           / "01-app-icons.js").read_text()
    tile = src[src.index("function iconTile("):]
    tile = tile[:tile.index("\nfunction ", 1)]

    assert "${esc(v)}" in tile, "the icon value must be escaped before innerHTML"
    assert "${v}" not in tile, "a raw icon value still reaches innerHTML"
    assert "iconGlyphOK(v)" in tile, "only a short, non-URL glyph may be drawn as text"
    assert "overflow:hidden" in tile, "the tile must clip, whatever ends up inside it"


def test_the_icon_guard_rejects_urls_and_markup():
    """The rules `iconGlyphOK` encodes, asserted without a JS engine."""
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "agentos" / "ui" / "src" / "js"
           / "01-app-icons.js").read_text()
    fn = src[src.index("function iconGlyphOK"):]
    fn = fn[:fn.index("\nfunction ", 1)]

    assert re.search(r"\\s", fn), "whitespace must disqualify a glyph"
    assert "a-z0-9+.-" in fn, "a URL/data: scheme must disqualify a glyph"
    assert "[...v].length" in fn, "length must be counted in code points, not UTF-16 units"
