"""Live windows: the shared browser, terminal sessions and native apps in a window (0.6.33).

Each window is a real process that the person and the agent both use. What is pinned
here is what keeps that shared use honest:

- the browser opens web pages only, and a page that wants a sign-in, a code or a CAPTCHA
  hands the window to the person and the agent carries on in the same session;
- a browser step is decided per SITE, the hands' web list bounds it, and the untrusted-
  content ceiling waives only a step on the very site everything untrusted came from;
- a terminal session outlives its window, and typing into one is a command, judged like
  one, and always a person's call when something other than the shell has the keyboard;
- a native app runs in its own headless display, and the status says what to install.
"""
import asyncio
import http.server
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import appstream, cdpbrowser, components, executors, ptyhub   # noqa: E402
from agentos import config as cfgmod                                          # noqa: E402
from agentos import policy                                                    # noqa: E402
from agentos.memory import Store                                              # noqa: E402
from agentos.policy import MAIN, PDP                                          # noqa: E402
from agentos.tools import SAFE_TOOLS, TOOL_SCHEMAS, Toolbox                   # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"


def _world(tmp_path, **cfg):
    c = cfgmod.load_config()
    c.update({"workspace": str(tmp_path / "ws"), "autonomy": "balanced", "policies": []})
    c.update(cfg)
    store = Store(tmp_path / "t.db")
    return c, store, Toolbox(c, store), PDP(c, store)


def _decide(tb, pdp, name, args, taint=None, autonomy="balanced"):
    lvl, why = tb.risk_of(name, args)
    return pdp.decide_tool(MAIN, name, args, lvl, reason=why, surface="gui", autonomy=autonomy,
                           taint=taint or [], base_risk=tb.base_risk(name, args))


# ---- the browser opens web pages, and nothing else ----

def test_only_web_pages_open():
    assert cdpbrowser.allowed("https://shop.example/orders") == ""
    assert cdpbrowser.allowed("about:blank") == ""
    for bad in ("file:///etc/passwd", "chrome://settings", "javascript:alert(1)", "data:text/html,x"):
        assert cdpbrowser.allowed(bad), bad
    assert cdpbrowser.normalise("example.com") == "https://example.com"
    assert cdpbrowser.normalise("cheap flights") .startswith("https://duckduckgo.com/?q=cheap+flights")
    assert cdpbrowser.site_of("https://www.Shop.example/a?b") == "shop.example"


def test_every_new_tool_is_classified_and_reaches_the_schemas():
    names = {t["name"] for t in TOOL_SCHEMAS}
    for n in executors.WORKSPACE_DOOR_TOOLS:
        assert n in names, n
    for safe in ("browser_read", "browser_tabs", "terminal_read", "terminal_sessions", "app_windows"):
        assert safe in SAFE_TOOLS
    for risky in ("browser_click", "browser_type", "app_window_open", "app_window_act"):
        assert risky not in SAFE_TOOLS


# ---- the gate decides a browser step per site ----

def test_a_browser_step_is_an_action_on_its_site():
    assert policy.action_of("browser_click", {"_site": "shop.example"}) == ("browser.act", "site:shop.example")
    assert policy.action_of("browser_open", {"url": "https://www.news.example/x"})[1] == "site:news.example"
    assert policy.action_of("browser_read", {})[0] == "browser.read"


def test_the_model_cannot_name_the_site(tmp_path):
    """`_site` is the browser's, injected by the agent loop after the model's args."""
    src = (ROOT / "agentos/agent.py").read_text()
    i = src.index("if name in BROWSER_ACTS:")
    assert '"_site": _browser_site()' in src[i:i + 400]


def test_same_site_taint_lifts_only_for_that_site():
    page = [{"tool": "browser_read", "source": "shop.example (in the shared browser)", "site": "shop.example"}]
    assert policy._same_site_taint(page, "browser_click", "site:shop.example")
    assert not policy._same_site_taint(page, "browser_click", "site:bank.example")
    mixed = page + [{"tool": "fetch_url", "source": "https://evil.example"}]
    assert not policy._same_site_taint(mixed, "browser_click", "site:shop.example")
    assert not policy._same_site_taint(page, "run_command", "site:shop.example")


def test_a_click_after_reading_another_site_asks(tmp_path):
    c, store, tb, pdp = _world(tmp_path, autonomy="full")
    other = [{"tool": "browser_read", "source": "forum", "site": "forum.example"}]
    d = _decide(tb, pdp, "browser_click", {"ref": 3, "_site": "shop.example"}, taint=other, autonomy="full")
    assert d.effect != "allow"
    same = [{"tool": "browser_read", "source": "shop", "site": "shop.example"}]
    d2 = _decide(tb, pdp, "browser_click", {"ref": 3, "_site": "shop.example"}, taint=same, autonomy="full")
    assert d2.effect == "allow"


# ---- a terminal session outlives its window ----

@pytest.mark.skipif(ptyhub.available() != "", reason="no pty here")
def test_a_session_outlives_its_window_and_reports_its_foreground():
    async def go():
        s = ptyhub.spawn("tester", ["/bin/sh"], name="build")
        got = []

        async def watch(data):
            got.append(data)
        sub = s.attach(watch)
        s.write("echo hello-pty\n")
        for _ in range(40):
            await asyncio.sleep(0.05)
            if "hello-pty" in s.tail():
                break
        assert "hello-pty" in s.tail()
        assert s.foreground() == ""               # the shell at its prompt is the shell
        s.detach(sub)                             # the window closed
        assert ptyhub.get("tester", "build") is s and s.alive
        s.write("sleep 3\n")
        for _ in range(40):
            await asyncio.sleep(0.05)
            if s.foreground() == "sleep":
                break
        assert s.foreground() == "sleep"
        assert ptyhub.get("someone-else", "build") is None    # per person
        s.end()
        await asyncio.sleep(0.1)
        assert not s.alive
        assert got and b"hello-pty" in b"".join(got)
    asyncio.run(go())
    ptyhub.end_all()


def test_typing_into_a_program_is_never_autonomy(tmp_path):
    c, store, tb, pdp = _world(tmp_path, autonomy="full")
    assert tb.risk_of("terminal_send", {"text": "ls", "_fg": ""})[0] == "safe"
    lvl, why = tb.risk_of("terminal_send", {"text": "ls", "_fg": "vim"})
    assert lvl == "risky" and "vim" in why
    assert tb.risk_of("terminal_send", {"text": "rm -rf /"})[0] == "blocked"
    src = (ROOT / "agentos/agent.py").read_text()
    assert 'must_person = f"typed into {args[\'_fg\']}, not the shell"' in src


# ---- native apps in a window ----

def test_app_window_status_names_its_components():
    st = appstream.status()
    assert set(st) >= {"ok", "backend", "missing", "why", "notes"}
    for comp in set(appstream.COMPONENT.values()):
        assert comp in components.CATALOG, comp
    if not st["ok"] and st["missing"]:
        assert st["why"] and st["components"]


@pytest.mark.skipif(not (shutil.which("Xvfb") and shutil.which("xdotool") and appstream._ffmpeg()
                         and shutil.which("xterm")), reason="needs Xvfb, xdotool, ffmpeg and xterm")
def test_an_app_fills_its_window_and_takes_typing():
    async def go():
        s = appstream.Stream("", "t1", "xterm", ["xterm"], "x11", (640, 400))
        await s.start()
        frames = []

        async def fb(f):
            frames.append(f)

        async def fj(_m):
            pass
        await s.add_viewer(fb, fj)
        await asyncio.sleep(3)
        geo = (await appstream._run("xdotool", "getwindowfocus", "getwindowgeometry", env=s.env))[1].decode()
        await s.type("echo hi")
        await asyncio.sleep(1)
        await s.stop()
        return frames, geo
    frames, geo = asyncio.run(go())
    assert frames and frames[-1][:2] == b"\xff\xd8"        # JPEG frames
    assert "640x400" in geo                                  # no window manager, so we sized it


# ---- the real browser, when this machine has one ----

PAGES = {
    "/login": "<title>Sign in</title><form action=/home><input name=u><input type=password name=p>"
              "<button>Sign in</button></form>",
    "/home": "<title>Orders</title><h1>Your orders</h1><a href=/o/1>Order 1</a>",
}


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGES.get(self.path.split("?")[0], "<p>nothing</p>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.mark.skipif(not cdpbrowser.binary({}), reason="no Chromium here")
def test_a_sign_in_wall_hands_the_window_over_and_the_agent_carries_on(tmp_path):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    told = []

    async def attention(uid, a):
        told.append(a)
    cdpbrowser.bind(attention=attention, presence=lambda uid: True)

    async def go():
        b = await cdpbrowser.get("", {}, tmp_path)
        try:
            words = await cdpbrowser.tool_open(b, base + "/login")
            assert "[needs you]" in words and b.attention and b.attention["kind"] == "login"
            assert told and told[0]["site"] == "127.0.0.1"

            async def person():
                await asyncio.sleep(1)
                await b.person({"type": "navigate", "url": base + "/home"})   # they signed in
            asyncio.ensure_future(person())
            after = await cdpbrowser.tool_wait(b, "sign in please", timeout=20)
            assert after.startswith("[carry on]") and "Your orders" in after
            assert b.attention is None
            clicked = await cdpbrowser.tool_click(b, text="Order 1")
            assert "clicked" in clicked
            assert (await cdpbrowser.tool_open(b, "file:///etc/passwd")).startswith("[refused]")
        finally:
            await cdpbrowser.stop_all()
    asyncio.run(go())
    srv.shutdown()


def test_nobody_here_means_the_agent_stops_and_says_so():
    class B:
        uid = ""
    cdpbrowser.bind(presence=lambda uid: False)
    out = asyncio.run(cdpbrowser.tool_wait(B(), "code"))
    assert out.startswith("[nobody here]")


# ---- the page ----

def test_the_page_keeps_keys_in_a_stream_window():
    for f in ("28a-omnibar.js", "29-keyboard-palette.js"):
        assert ".sv" in (JS / f).read_text(), f
    ws = (JS / "09-websocket.js").read_text()
    assert "case 'browser_attention'" in ws and "case 'appstream'" in ws


def test_the_terminal_from_ssh_is_the_same_session():
    from agentos import termcli
    assert termcli.DETACH == b"\x1d"
    src = (ROOT / "agentos/termcli.py").read_text()
    assert "/ws/terminal?session=" in src
    assert termcli._base({"port": 9}) == "http://127.0.0.1:9"     # loopback only

