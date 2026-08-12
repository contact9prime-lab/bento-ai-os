"""The parity law: every capability the UI has is also a PDP-gated agent tool.

Covers the desktop-parity tool family: registration (schema + dispatch), risk
classification, graceful degradation on machines without the capability (no
compositor, no D-Bus daemons, no shell connected — a sentence, never a raise),
the shell-control channel, and the image tool-result plumbing. No live buses:
hostctl/host/compositor calls are monkeypatched to fail the way they fail on a
machine without them.
"""

import asyncio
import os
import tempfile

import pytest

os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import config as cfgmod                                # noqa: E402
from agentos import server as servermod                             # noqa: E402
from agentos.agent import _media_result as _image_result                             # noqa: E402
from agentos.hostctl import HostCtlError                            # noqa: E402
from agentos.memory import Store                                    # noqa: E402
from agentos.tools import (ALWAYS_ASK, BUILTIN_THEMES,              # noqa: E402
                           DESKTOP_TOOL_SCHEMAS, TOOL_SCHEMAS, Toolbox)

NEW_TOOLS = ["desktop_state", "control_desktop", "manage_window", "list_themes",
             "wifi", "bluetooth", "set_brightness", "audio", "power_profile",
             "lock_screen", "power_action", "list_notifications", "take_screenshot"]


@pytest.fixture()
def toolbox(tmp_path):
    cfg = cfgmod.load_config()
    cfg["workspace"] = str(tmp_path)
    cfg["sandbox"] = {"enabled": False, "root": ""}
    return Toolbox(cfg, Store(tmp_path / "db.sqlite"))


# ---------------------------------------------------------------------------
# registration: schema + dispatch
# ---------------------------------------------------------------------------

def test_every_new_tool_is_registered(toolbox):
    names = {t["name"] for t in TOOL_SCHEMAS}
    for n in NEW_TOOLS:
        assert n in names, f"{n} missing from TOOL_SCHEMAS"
        fn = getattr(toolbox, n, None)
        assert fn is not None and asyncio.iscoroutinefunction(fn), f"{n} not dispatchable"


def test_new_tool_schemas_are_valid():
    for t in DESKTOP_TOOL_SCHEMAS:
        assert t["name"] in NEW_TOOLS
        assert t["description"].strip()
        p = t["parameters"]
        assert p["type"] == "object" and isinstance(p["properties"], dict)
        for req in p.get("required", []):
            assert req in p["properties"], f"{t['name']} requires undeclared '{req}'"


def test_no_duplicate_tool_names():
    names = [t["name"] for t in TOOL_SCHEMAS]
    assert len(names) == len(set(names))


def test_builtin_themes_present():
    assert "agentos" in BUILTIN_THEMES and "dracula" in BUILTIN_THEMES


# ---------------------------------------------------------------------------
# risk classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,args,want", [
    ("desktop_state", {}, "safe"),
    ("list_themes", {}, "safe"),
    ("list_notifications", {}, "safe"),
    ("set_brightness", {"percent": 50}, "safe"),
    ("audio", {"action": "volume", "value": 30}, "safe"),
    ("audio", {"action": "route", "device": "headphones"}, "safe"),
    ("power_profile", {"profile": "performance"}, "safe"),
    ("control_desktop", {"action": "open_app", "target": "Notes"}, "safe"),
    ("control_desktop", {"action": "apply_theme", "target": "nord"}, "safe"),
    ("control_desktop", {"action": "close_app", "target": "Notes"}, "risky"),
    ("manage_window", {"window_id": "5", "action": "focus"}, "safe"),
    ("manage_window", {"window_id": "5", "action": "close"}, "risky"),
    ("manage_window", {"window_id": "5", "action": "float"}, "risky"),
    ("manage_window", {"window_id": "5", "action": "move_to_workspace",
                       "workspace": "2"}, "risky"),
    ("wifi", {"action": "list"}, "safe"),
    ("wifi", {"action": "status"}, "safe"),
    ("wifi", {"action": "connect", "ssid": "Home"}, "risky"),
    ("wifi", {"action": "forget", "ssid": "Home"}, "risky"),
    ("bluetooth", {"action": "status"}, "safe"),
    ("bluetooth", {"action": "scan"}, "safe"),
    ("bluetooth", {"action": "pair", "device": "buds"}, "risky"),
    ("bluetooth", {"action": "disconnect", "device": "buds"}, "risky"),
    ("lock_screen", {}, "risky"),
    ("power_action", {"action": "suspend"}, "risky"),
    ("power_action", {"action": "poweroff"}, "risky"),
    ("take_screenshot", {}, "risky"),
])
def test_desktop_risk_levels(toolbox, name, args, want):
    assert toolbox.risk_of(name, args)[0] == want


def test_power_action_always_asks(toolbox):
    # risky (= ask below full autonomy) AND in ALWAYS_ASK — the agent loop and
    # /api/tool downgrade the PDP's default-allow to ask even at autonomy=full
    assert "power_action" in ALWAYS_ASK
    level, reason = toolbox.risk_of("power_action", {"action": "poweroff"})
    assert level == "risky" and reason


# ---------------------------------------------------------------------------
# graceful degradation: no shell, no compositor, no D-Bus daemons
# ---------------------------------------------------------------------------

def _raise(*a, **k):
    raise HostCtlError("the daemon is not answering (test)")


async def _araise(*a, **k):
    raise HostCtlError("the daemon is not answering (test)")


async def test_control_desktop_without_shell(toolbox):
    out = await toolbox.control_desktop("open_app", "Notes")
    assert out.startswith("[error]") and "not supported on this platform" in out


async def test_control_desktop_rejects_unknown_action(toolbox):
    out = await toolbox.control_desktop("explode")
    assert out.startswith("[error] action must be")


async def test_control_desktop_unknown_theme(toolbox):
    async def shell(action, args, timeout=8.0):   # a shell IS connected…
        return True, "applied"
    toolbox.shell = shell
    out = await toolbox.control_desktop("apply_theme", "no-such-theme")
    assert out.startswith("[error]") and "agentos" in out    # …but the id must exist
    assert "applied" == await toolbox.control_desktop("apply_theme", "nord")


async def test_manage_window_without_window_control(toolbox, monkeypatch):
    monkeypatch.setattr("agentos.host.list_windows",
                        lambda: {"available": False, "windows": [],
                                 "reason": "no compositor in this session"})
    out = await toolbox.manage_window("firefox", "close")
    assert out.startswith("[error]") and "not supported on this platform" in out


async def test_wifi_degrades_without_networkmanager(toolbox, monkeypatch):
    from agentos.hostctl import network
    monkeypatch.setattr(network, "status", _araise)
    monkeypatch.setattr(network, "wifi_scan", _araise)
    monkeypatch.setattr(network, "wifi_join", _araise)
    for args in (("status",), ("list",), ("connect", "Home", "pw")):
        out = await toolbox.wifi(*args)
        assert out.startswith("[error]") and "not answering" in out


async def test_bluetooth_degrades_without_bluez(toolbox, monkeypatch):
    from agentos.hostctl import bluetooth as bt
    monkeypatch.setattr(bt, "tree", _araise)
    for args in (("status",), ("scan",), ("pair", "buds")):
        out = await toolbox.bluetooth(*args)
        assert out.startswith("[error]") and "not answering" in out


async def test_power_profile_degrades(toolbox, monkeypatch):
    from agentos.hostctl import upower
    monkeypatch.setattr(upower, "get_profile", _araise)
    monkeypatch.setattr(upower, "set_profile", _araise)
    assert (await toolbox.power_profile()).startswith("[error]")
    assert (await toolbox.power_profile("performance")).startswith("[error]")


async def test_set_brightness_degrades(toolbox, monkeypatch):
    from agentos.hostctl import brightness
    async def no_displays():
        return {"available": False, "displays": [], "reason": "No internal backlight.",
                "component": "ddcutil"}
    monkeypatch.setattr(brightness, "state", no_displays)
    out = await toolbox.set_brightness(70)
    assert out.startswith("[error]") and "not supported on this platform" in out


async def test_desktop_state_degrades_to_a_sentence(toolbox, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no platform")
    for fn in ("list_windows", "workspaces", "get_battery", "get_network", "get_volume"):
        monkeypatch.setattr(f"agentos.host.{fn}", boom)
    from agentos.hostctl import brightness, upower
    monkeypatch.setattr(upower, "get_profile", _araise)
    monkeypatch.setattr(brightness, "backlights", _raise)
    out = await toolbox.desktop_state()          # every probe fails, nothing raises
    assert "no desktop state available" in out


async def test_list_notifications_without_daemon(toolbox):
    out = await toolbox.list_notifications()
    assert out.startswith("[error]") and "not supported on this platform" in out


async def test_list_notifications_reads_the_center(toolbox):
    from agentos.notifications import NotificationDaemon
    async def sink(ev):
        pass
    d = NotificationDaemon(sink)
    d.add("firefox", 0, "", "Download finished", "cat.png", {})
    toolbox.notifd = d
    out = await toolbox.list_notifications()
    assert "firefox" in out and "Download finished" in out and "(unread)" in out
    assert await toolbox.list_notifications(unread_only=True) != "no notifications (unread)"
    d.mark_read()
    assert (await toolbox.list_notifications(unread_only=True)).startswith("no notifications")


async def test_take_screenshot_degrades_without_grim(toolbox, monkeypatch):
    async def no_grim(area="full", workspace=""):
        return False, "not supported on this platform: screenshots need grim"
    monkeypatch.setattr(servermod, "capture_screen", no_grim)
    out = await toolbox.take_screenshot()
    assert out.startswith("[error]") and "not supported on this platform" in out


async def test_take_screenshot_returns_image_result(toolbox, monkeypatch, tmp_path):
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"\x89PNG fake")
    async def ok(area="full", workspace=""):
        return True, str(shot)
    monkeypatch.setattr(servermod, "capture_screen", ok)
    out = await toolbox.take_screenshot()
    text, path = _image_result(out)
    assert path == str(shot) and "screenshot saved to" in text


# ---------------------------------------------------------------------------
# shell-control channel
# ---------------------------------------------------------------------------

async def test_shell_command_without_a_shell(monkeypatch):
    monkeypatch.setitem(servermod.state, "clients", set())
    ok, msg = await servermod.shell_command("open_app", {"target": "Notes"})
    assert not ok and "no desktop shell is connected" in msg


async def test_shell_command_times_out_cleanly(monkeypatch):
    sent = []
    async def broadcast(ev):
        sent.append(ev)
    monkeypatch.setitem(servermod.state, "clients", {object()})
    monkeypatch.setitem(servermod.state, "broadcast", broadcast)
    monkeypatch.setitem(servermod.state, "shell_pending", {})
    ok, msg = await servermod.shell_command("list_open_apps", timeout=0.1)
    assert not ok and "did not answer" in msg
    assert sent and sent[0]["type"] == "shell_cmd" and sent[0]["action"] == "list_open_apps"
    assert not servermod.state["shell_pending"]          # no leaked futures


async def test_shell_command_resolved_by_result_post(monkeypatch):
    async def broadcast(ev):
        # the "shell": answer the command the way POST /api/shell/result does
        fut = servermod.state["shell_pending"][ev["id"]]
        fut.set_result({"ok": True, "data": ["Notes", "Browser"]})
    monkeypatch.setitem(servermod.state, "clients", {object()})
    monkeypatch.setitem(servermod.state, "broadcast", broadcast)
    monkeypatch.setitem(servermod.state, "shell_pending", {})
    ok, data = await servermod.shell_command("list_open_apps", timeout=2)
    assert ok and data == ["Notes", "Browser"]


def test_shell_result_endpoint_is_sensitive_for_apps():
    assert ("POST", "/api/shell/result") in servermod.SENSITIVE_FOR_APPS


# ---------------------------------------------------------------------------
# shared power helper + image result plumbing
# ---------------------------------------------------------------------------

async def test_power_exec_unknown_action():
    ok, msg = await servermod.power_exec("explode")
    assert not ok and "unknown action" in msg


def test_image_result_split_and_passthrough():
    text, path = _image_result('{"__image__": "/tmp/x.png", "text": "screenshot saved to /tmp/x.png"}')
    assert path == "/tmp/x.png" and text == "screenshot saved to /tmp/x.png"
    text, path = _image_result("plain tool output")
    assert path == "" and text == "plain tool output"


def test_every_schema_agrees_with_the_method_it_calls():
    """A tool's schema is its contract with the model; the signature is the code.

    `create_app` had `icon` in `required` while its own description said "leave
    empty". A model that followed the description made a call the dispatcher could
    not complete — `Toolbox.create_app() missing 1 required positional argument:
    'icon'` — and it failed AFTER the app had been written, so the build looked
    broken while the app existed. The two halves must agree in both directions:
    anything the method needs must be required, and nothing may be required that the
    method cannot accept.
    """
    import inspect

    from agentos import tools as toolsmod

    problems = []
    for schema in toolsmod.TOOL_SCHEMAS:
        fn = schema.get("function", schema)
        name = fn.get("name")
        params = fn.get("parameters") or {}
        required = set(params.get("required") or [])
        method = getattr(toolsmod.Toolbox, name, None)
        if method is None:
            problems.append(f"{name}: schema has no method")
            continue
        args = {k: v for k, v in inspect.signature(method).parameters.items()
                if k != "self"}
        needs = {k for k, v in args.items()
                 if v.default is inspect.Parameter.empty
                 and v.kind not in (v.VAR_POSITIONAL, v.VAR_KEYWORD)}
        if (gap := needs - required):
            problems.append(f"{name}: {sorted(gap)} have no default but are not "
                            f"in the schema's required list")
        if (extra := required - set(args)):
            problems.append(f"{name}: schema requires {sorted(extra)}, "
                            f"which the method does not accept")
    assert not problems, "schema/signature disagreement:\n  " + "\n  ".join(problems)
