"""What a page may load and run, and what a file may do on this origin (S-10, S-33, S-34, S-35).

Header tests are faithful here: the browser enforces these on the server's word, and a real
page was checked in headless Chrome separately. The choke point is `security_headers`.
"""
import ast
import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient      # noqa: E402
from agentos import server as servermod        # noqa: E402
from agentos import memory, policy             # noqa: E402

XSS = "<img src=x onerror=alert(1)>"


@pytest.fixture()
def api():
    with TestClient(servermod.app) as c:
        yield c


def _workspace(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    monkeypatch.setitem(servermod.state["cfg"], "workspace", str(ws))
    return ws


def test_the_mcp_callback_escapes_what_it_was_sent(api):
    r = api.get("/api/mcp/oauth/callback/" + XSS, params={"error": "<script>alert(2)</script>"})
    assert XSS not in r.text and "<script>" not in r.text
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "sandbox" in csp
    assert "script-src" not in csp


def test_every_api_page_gets_the_no_script_policy(api):
    """The next route that returns HTML can't forget: the middleware adds it."""
    r = api.get("/api/accounts/oauth/nobody/callback", params={"state": "x", "error": XSS})
    if r.headers.get("content-type", "").startswith("text/html"):
        assert "default-src 'none'" in r.headers["content-security-policy"]
    assert XSS not in r.text
    assert servermod._active_doc("TEXT/HTML; charset=utf-8") and servermod._active_doc("image/svg+xml")
    assert servermod._active_doc("application/atom+xml") and not servermod._active_doc("image/png")


def test_the_desktop_has_a_real_policy_and_no_remote_script(api):
    for path in ("/", "/login"):
        r = api.get(path)
        assert r.headers["x-content-type-options"] == "nosniff"
        csp = r.headers["content-security-policy"]
        assert "script-src 'self' 'unsafe-inline';" in csp, csp
        for need in ("object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'",
                     "connect-src 'self'", "https://www.youtube-nocookie.com"):
            assert need in csp
        script = csp.split("script-src")[1].split(";")[0]
        assert "http" not in script and "*" not in script and "unsafe-eval" not in script


def test_a_host_header_cannot_write_into_the_policy(api):
    r = api.get("/", headers={"host": "a; script-src *"})
    assert "script-src *" not in r.headers.get("content-security-policy", "")


@pytest.mark.parametrize("name,body", [("x.html", "<script>alert(1)</script>"),
                                       ("y.svg", "<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"),
                                       ("z.xml", "<a/>"), ("v.xhtml", "<a/>")])
def test_a_file_that_can_carry_script_is_sandboxed_and_downloads(api, tmp_path, monkeypatch, name, body):
    ws = _workspace(tmp_path, monkeypatch)
    (ws / name).write_text(body)
    for route in ("/api/files/get", "/api/files/raw"):
        r = api.get(route, params={"path": str(ws / name)})
        if r.status_code == 404:        # /raw reads the machine's shared folder, not this one
            continue
        assert r.status_code == 200
        assert "attachment" in r.headers.get("content-disposition", ""), route
        assert r.headers["content-security-policy"].startswith("sandbox"), route
    # The chip's Open asks to view it: still no script, and still not this origin.
    r = api.get("/api/files/get", params={"path": str(ws / name), "view": 1})
    assert r.status_code == 200
    if not name.endswith((".xml", ".xhtml")):       # those have no reader in a tab worth opening
        assert "attachment" not in r.headers.get("content-disposition", "")
    assert r.headers["content-security-policy"].startswith("sandbox")
    assert "script-src" not in r.headers["content-security-policy"]


def test_an_image_and_a_text_file_still_show_inline(api, tmp_path, monkeypatch):
    ws = _workspace(tmp_path, monkeypatch)
    (ws / "a.png").write_bytes(b"\x89PNG\r\n")
    (ws / "b.txt").write_text("hello")
    for n in ("a.png", "b.txt"):
        r = api.get("/api/files/get", params={"path": str(ws / n)})
        assert r.status_code == 200 and "attachment" not in r.headers.get("content-disposition", "")


def test_a_fetched_asset_keeps_no_power_from_its_remote_type(api, tmp_path):
    from agentos import assets as assetmod
    store = servermod.state["store"]
    for mime, want_attach in (("text/html", True), ("image/svg+xml", False), ("image/png", False)):
        row = asyncio.run(assetmod.put_bytes(store, ("<script>alert(1)</script>" + mime).encode(), name="x",
                                             mime=mime, title="t", source="url"))
        r = api.get(f"/api/assets/{row['id']}/file")
        assert ("attachment" in r.headers.get("content-disposition", "")) is want_attach, mime
        if mime != "image/png":
            assert r.headers["content-security-policy"].startswith("sandbox"), mime


def _app(name="victim"):
    return servermod.state["store"].save_app(name, "", "d", "<html><body><script>var secret=1</script></body></html>")


def test_an_app_page_is_sandboxed_by_the_response_itself(api):
    """The iframe attribute only protects a page opened in a frame; a tab ran it as the desktop."""
    aid = _app("sandbox-probe")
    r = api.get(f"/api/apps/{aid}/page")
    csp = r.headers["content-security-policy"]
    assert "sandbox allow-scripts allow-forms" in csp and "allow-same-origin" not in csp
    assert "frame-ancestors 'self'" in csp


def test_an_app_cannot_fetch_another_apps_page(api):
    aid = _app("page-probe")
    r = api.get(f"/api/apps/{aid}/page", headers={"origin": "null"})
    assert r.status_code == 403 and "var secret" not in r.text
    assert "access-control-allow-origin" not in r.headers
    r = api.get(f"/api/apps/{aid}/page", headers={"sec-fetch-mode": "cors"})
    assert r.status_code == 403
    r = api.get(f"/api/apps/{aid}/page", headers={"sec-fetch-mode": "navigate", "sec-fetch-dest": "iframe"})
    assert r.status_code == 200, "a frame loading its page must still work"
    assert "access-control-allow-origin" not in r.headers


def test_a_tokenless_opaque_read_of_the_runtime_is_refused(api):
    aid = _app("data-probe")
    servermod.state["store"].set_app_data(aid, '{"private": 1}')
    for path in (f"/api/apps/{aid}/data", "/api/apps/context"):
        r = api.get(path, headers={"origin": "null"})
        assert r.status_code == 403 and "private" not in r.text, path
        r = api.get(path, headers={"origin": "https://evil.example"})
        assert r.status_code == 403, path


def test_a_token_still_reads_its_own_data(api):
    aid = _app("own-data")
    servermod.state["store"].set_app_data(aid, '{"mine": 1}')
    servermod.state["app_tokens"]["tok-own"] = {"app_id": aid, "issued": 9e12}
    r = api.get(f"/api/apps/{aid}/data", headers={"origin": "null", "x-app-token": "tok-own"})
    assert r.status_code == 200 and "mine" in r.text
    assert r.headers["access-control-allow-origin"] == "null"


def test_desktop_state_does_not_name_other_apps_to_an_app():
    from agentos.tools import Toolbox
    tb = Toolbox.__new__(Toolbox)
    tb.notifd = None

    async def shell(*a, **k):
        return True, {"open": [{"app": "ua_other", "title": "Secret"}, {"app": "ua_me", "title": "Me"},
                               {"app": "chat", "title": "Chat"}], "theme": "nova"}
    tb.shell = shell
    out = asyncio.run(tb.desktop_state(_app="me"))
    assert "ua_other" not in out and "Secret" not in out and "ua_me" in out and "chat" in out
    assert "ua_other" in asyncio.run(tb.desktop_state())


def test_an_app_name_is_plain_text(tmp_path):
    st = memory.Store(str(tmp_path / "a.db"))
    aid = st.save_app('<img src=x onerror=import("//e.vu/a")>', "", "", "<h1>x</h1>")
    assert "<" not in st.get_app(aid)["name"] and ">" not in st.get_app(aid)["name"]
    assert st.rename_app(aid, name="<b>bold\x07</b>") is None
    assert "<" not in st.get_app(aid)["name"] and "\x07" not in st.get_app(aid)["name"]


def _bridge():
    """shellhost imports GTK at the top, so its two pure pieces are lifted out to run here."""
    src = (ROOT / "agentos" / "shellhost.py").read_text()
    tree = ast.parse(src)
    keep = [n for n in tree.body if (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "BRIDGE_JS")
            or (isinstance(n, ast.FunctionDef) and n.name in ("bridge_script", "bridge_sender_ok"))]
    ns = {}
    exec("import json, hmac\n" + "\n".join(ast.get_source_segment(src, n) for n in keep), ns)
    return ns


def test_the_session_bridge_only_obeys_the_top_frames_token():
    """WebKit shows the handler to every frame and doesn't say which one sent a message."""
    ns = _bridge()
    js = ns["bridge_script"]("tok-1")
    assert '"tok-1"' in js and "__TOKEN__" not in js
    # inside a closure, so a frame (or a later script) can't read it off window
    assert js.index('(function () {') < js.index('"tok-1"')
    assert "window.suiCall" in js
    ok = ns["bridge_sender_ok"]
    assert ok({"cmd": "quit", "token": "tok-1"}, "tok-1")
    for bad in ({"cmd": "quit"}, {"cmd": "quit", "token": "guess"}, {"cmd": "quit", "token": ""}, "quit", None, []):
        assert not ok(bad, "tok-1")
