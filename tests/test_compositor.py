"""The compositor IPC client, against a fake sway.

The fake speaks the real i3-ipc wire protocol over a unix socket and serves a
recorded layout tree, so these tests exercise header packing, reply framing,
tree flattening and command generation without needing sway installed. The live
smoke test against real sway is `agentos doctor` + the nested-session check.
"""

import asyncio
import copy
import json
import socket
import struct
import threading

import pytest

from agentos import compositor as comp

HEADER = struct.Struct("<6sII")

# A trimmed real-shaped sway tree: one output, workspace "1" holds the AgentOS
# shell (fullscreen chromium app), a tiled firefox inside a split container,
# and a floating pavucontrol. Workspace "2" holds an XWayland window, which has
# window_properties/class instead of app_id.
TREE = {
    "id": 1, "type": "root", "nodes": [{
        "id": 2, "type": "output", "name": "DP-1", "nodes": [{
            "id": 10, "type": "workspace", "name": "1", "nodes": [
                {"id": 11, "pid": 4242, "app_id": "agentos", "name": "AgentOS",
                 "focused": False, "fullscreen_mode": 1, "nodes": [], "floating_nodes": []},
                {"id": 12, "type": "con", "nodes": [
                    {"id": 13, "pid": 5001, "app_id": "firefox",
                     "name": "Mozilla Firefox", "focused": True, "fullscreen_mode": 0,
                     "nodes": [], "floating_nodes": []},
                ], "floating_nodes": []},
            ],
            "floating_nodes": [
                # No "floating" key: sway does not send one. Being in
                # floating_nodes IS the fact, and that is what windows() reads.
                {"id": 14, "pid": 5002, "app_id": "pavucontrol", "name": "Volume Control",
                 "focused": False, "fullscreen_mode": 0,
                 "nodes": [], "floating_nodes": []},
            ],
        }, {
            "id": 20, "type": "workspace", "name": "2", "nodes": [
                {"id": 21, "pid": 6001, "app_id": None,
                 "window_properties": {"class": "Gimp", "title": "GNU Image Manipulation Program"},
                 "name": "GNU Image Manipulation Program", "focused": False,
                 "fullscreen_mode": 0, "nodes": [], "floating_nodes": []},
            ], "floating_nodes": [],
        }],
    }],
}

WORKSPACES = [
    {"name": "1", "num": 1, "focused": True, "output": "DP-1", "urgent": False},
    {"name": "2", "num": 2, "focused": False, "output": "DP-1", "urgent": False},
]

OUTPUTS = [{
    "name": "DP-1", "make": "Dell", "model": "U2720Q", "serial": "ABC123",
    "active": True, "primary": True, "scale": 1.5, "transform": "normal",
    "rect": {"x": 0, "y": 0, "width": 3840, "height": 2160},
    "current_mode": {"width": 3840, "height": 2160, "refresh": 59997},
    "modes": [{"width": 3840, "height": 2160, "refresh": 59997},
              {"width": 1920, "height": 1080, "refresh": 60000}],
}]


class FakeSway:
    """Serves the i3-ipc protocol from a unix socket; records every command."""

    def __init__(self, sock_path, fail_commands=False):
        self.path = str(sock_path)
        self.commands: list[str] = []
        self.fail_commands = fail_commands
        # a mutable copy, so a test can make the tree change under the client —
        # which is the whole point when the behaviour under test is "wait for a
        # window that was not there before"
        self.tree = copy.deepcopy(TREE)
        self.spawn_on_exec: dict | None = None
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(self.path)
        self._srv.listen(8)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        self._srv.settimeout(0.2)
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            while True:
                hdr = b""
                while len(hdr) < HEADER.size:
                    chunk = conn.recv(HEADER.size - len(hdr))
                    if not chunk:
                        return
                    hdr += chunk
                magic, length, mtype = HEADER.unpack(hdr)
                payload = b""
                while len(payload) < length:
                    payload += conn.recv(length - len(payload))

                if mtype == comp.RUN_COMMAND:
                    cmd = payload.decode()
                    self.commands.append(cmd)
                    if self.spawn_on_exec and cmd.startswith("exec "):
                        self.tree["nodes"][0]["nodes"][0]["floating_nodes"].append(
                            self.spawn_on_exec)
                        self.spawn_on_exec = None
                    body = json.dumps(
                        [{"success": False, "error": "nope"}] if self.fail_commands
                        else [{"success": True}]).encode()
                    conn.sendall(HEADER.pack(magic, len(body), mtype) + body)
                elif mtype == comp.GET_TREE:
                    body = json.dumps(self.tree).encode()
                    conn.sendall(HEADER.pack(magic, len(body), mtype) + body)
                elif mtype == comp.GET_WORKSPACES:
                    body = json.dumps(WORKSPACES).encode()
                    conn.sendall(HEADER.pack(magic, len(body), mtype) + body)
                elif mtype == comp.GET_OUTPUTS:
                    body = json.dumps(OUTPUTS).encode()
                    conn.sendall(HEADER.pack(magic, len(body), mtype) + body)
                elif mtype == comp.SUBSCRIBE:
                    ack = json.dumps({"success": True}).encode()
                    conn.sendall(HEADER.pack(magic, len(ack), mtype) + ack)
                    for etype, change in ((3, "new"), (3, "focus"), (0, "focus")):
                        ev = json.dumps({"change": change}).encode()
                        conn.sendall(HEADER.pack(magic, len(ev), 0x80000000 | etype) + ev)
        except OSError:
            pass
        finally:
            conn.close()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2)
        self._srv.close()


@pytest.fixture
def sway(tmp_path):
    fake = FakeSway(tmp_path / "sway.sock")
    yield fake
    fake.stop()


@pytest.fixture
def client(sway):
    return comp.Compositor(sock=sway.path)


def test_windows_flattens_the_tree_and_hides_the_shell(client):
    wins = client.windows()
    by_app = {w["app"]: w for w in wins}
    # The shell must never appear in its own taskbar; nested + floating +
    # XWayland windows all must.
    assert "agentos" not in by_app
    assert set(by_app) == {"firefox", "pavucontrol", "Gimp"}
    ff = by_app["firefox"]
    assert ff == {"id": "13", "pid": 5001, "app": "firefox", "title": "Mozilla Firefox",
                  "workspace": "1", "focused": True, "floating": False,
                  "fullscreen": False, "minimized": False}
    assert by_app["pavucontrol"]["floating"] is True
    assert by_app["Gimp"]["workspace"] == "2"
    assert by_app["Gimp"]["title"] == "GNU Image Manipulation Program"


def test_window_commands_generate_correct_criteria(client, sway):
    client.focus("13")
    client.close("13")
    client.move_to_workspace("13", "2")
    client.set_floating("13", True)
    client.set_floating("13", False)
    assert sway.commands == [
        # focus tries the scratchpad first, so focusing a MINIMISED window brings
        # it back rather than doing nothing; sway shrugs off the no-op otherwise
        "[con_id=13] scratchpad show",
        "[con_id=13] focus",
        "[con_id=13] kill",
        '[con_id=13] move container to workspace "2"',
        "[con_id=13] floating enable",
        "[con_id=13] floating disable",
    ]


def test_workspaces_and_switch(client, sway):
    ws = client.workspaces()
    assert [w["name"] for w in ws] == ["1", "2"]
    assert ws[0]["focused"] is True
    client.switch_workspace("2")
    assert sway.commands == ['workspace "2"']


def test_outputs_shape(client):
    outs = client.outputs()
    assert len(outs) == 1
    o = outs[0]
    assert o["name"] == "DP-1" and o["active"] and o["scale"] == 1.5
    assert o["mode"]["width"] == 3840
    assert {"width": 1920, "height": 1080, "refresh": 60000} in o["modes"]


def test_configure_output_builds_one_command(client, sway):
    client.configure_output("DP-1", mode="1920x1080@60Hz", scale=2.0,
                            transform="90", position=(1920, 0))
    assert sway.commands == [
        'output "DP-1" mode 1920x1080@60Hz scale 2.0 transform 90 position 1920 0']
    sway.commands.clear()
    client.configure_output("DP-1", enabled=False)
    assert sway.commands == ['output "DP-1" disable']
    sway.commands.clear()
    client.configure_output("DP-1")          # nothing to change -> no command
    assert sway.commands == []


def test_command_failure_surfaces_sways_error(tmp_path):
    fake = FakeSway(tmp_path / "sway2.sock", fail_commands=True)
    try:
        c = comp.Compositor(sock=fake.path)
        with pytest.raises(comp.CompositorError, match="nope"):
            c.focus("13")
    finally:
        fake.stop()


def test_unreachable_socket_raises_cleanly(tmp_path, monkeypatch):
    c = comp.Compositor(sock=str(tmp_path / "absent.sock"))
    with pytest.raises(comp.CompositorError, match="cannot reach"):
        c.windows()
    # No inherited SWAYSOCK *and* nothing discoverable: say so plainly. Discovery
    # is pinned off here so the result doesn't depend on whether the machine
    # running the tests happens to have a compositor of its own.
    monkeypatch.delenv("SWAYSOCK", raising=False)
    monkeypatch.delenv("I3SOCK", raising=False)
    monkeypatch.setattr(comp, "_discover_socket", lambda: "")
    with pytest.raises(comp.CompositorError, match="SWAYSOCK"):
        comp.Compositor(sock="").windows()


def test_quotes_are_stripped_from_workspace_names(client, sway):
    client.move_to_workspace("13", 'evil" fullscreen; exec rm')
    assert '"evil fullscreen; exec rm"' in sway.commands[0]
    assert sway.commands[0].count('"') == 2


def test_subscribe_yields_events(sway):
    async def collect():
        c = comp.Compositor(sock=sway.path)
        got = []
        async for ev in c.subscribe():
            got.append(ev)
            if len(got) == 3:
                break
        return got

    events = asyncio.run(asyncio.wait_for(collect(), timeout=5))
    assert events == [{"event": "window", "change": "new"},
                      {"event": "window", "change": "focus"},
                      {"event": "workspace", "change": "focus"}]


def test_de_backend_reports_compositor_errors_as_reasons(tmp_path, monkeypatch):
    """The platform layer must translate IPC failures into {available, reason},
    never let them escape as exceptions."""
    from agentos.platform.linux_de import LinuxDE
    monkeypatch.setenv("SWAYSOCK", str(tmp_path / "gone.sock"))
    de = LinuxDE()
    de._comp = comp.Compositor(sock=str(tmp_path / "gone.sock"))
    w = de.list_windows()
    assert w["available"] is False and w["reason"]
    ok, msg = de.focus_window("13")
    assert ok is False and msg
    assert de.focus_window("not-a-number") == (False, "invalid window id")
    ws = de.workspaces()
    assert ws["available"] is False and ws["reason"]


def test_windows_include_shell_flags_it(client):
    wins = client.windows(include_shell=True)
    shell = [w for w in wins if w.get("shell")]
    assert len(shell) == 1 and shell[0]["app"] == "agentos"
    # default call still hides it — the taskbar contract
    assert not any(w.get("shell") for w in client.windows())


def test_alt_tab_cycles_natives_then_returns_to_shell(sway, monkeypatch):
    """firefox is focused in the recorded tree; next → pavucontrol → Gimp →
    shell. That's the whole Alt-Tab ring."""
    from agentos.platform.linux_de import LinuxDE
    monkeypatch.setenv("SWAYSOCK", sway.path)
    de = LinuxDE()
    ok, what = de.cycle_focus("next")            # firefox → pavucontrol (id 14)
    assert ok and sway.commands[-1] == "[con_id=14] focus"
    # The fake's tree is static (firefox stays 'focused'), so exercise the
    # ends of the ring directly: prev from firefox (index 0) wraps to the shell.
    sway.commands.clear()
    ok, what = de.cycle_focus("prev")
    assert ok and what == "shell"
    # /proc has no pid 4242, so the command-line probe cannot identify the shell.
    # find_shell now falls back to app_id (the same test windows() uses) and
    # resolves it to a con_id, instead of leaving focus_shell to guess with an
    # app_id criteria string. Same intent, one layer earlier — and raise/lower
    # get the fallback too, which is what they were missing.
    assert sway.commands == ["[con_id=11] focus"], (
        "with no shell on the command line, app_id must still identify the desktop")


def test_cycle_focus_reports_compositor_failure(tmp_path, monkeypatch):
    from agentos.platform.linux_de import LinuxDE
    from agentos import compositor as comp_mod
    de = LinuxDE()
    de._comp = comp_mod.Compositor(sock=str(tmp_path / "gone.sock"))
    ok, msg = de.cycle_focus()
    assert ok is False and msg


def test_de_backend_windows_through_fake_sway(sway, monkeypatch):
    from agentos.platform.linux_de import LinuxDE
    monkeypatch.setenv("SWAYSOCK", sway.path)
    de = LinuxDE()
    w = de.list_windows()
    assert w["available"] is True
    assert {x["app"] for x in w["windows"]} == {"firefox", "pavucontrol", "Gimp"}
    assert de.focus_window("13") == (True, "ok")
    assert de.workspaces()["workspaces"][0]["name"] == "1"
    assert de.outputs()["outputs"][0]["name"] == "DP-1"
    assert de.configure_output("DP-1", scale=1.0) == (True, "ok")
    # And the probe flips the capabilities on when the socket is live.
    from agentos.platform import caps as C
    assert de.capabilities(refresh=True)[C.WINDOWS_MANAGE].available is True
    assert de.capabilities()[C.DISPLAY_CONFIGURE].available is True


# --- windows behaving like windows -----------------------------------------

def test_minimize_uses_the_scratchpad(client, sway):
    """sway has no minimise. The scratchpad is exactly "hidden but still alive",
    which is what a person means by minimise — and it keeps the window listed."""
    client.minimize("13")
    client.unminimize("13")
    assert sway.commands == [
        "[con_id=13] move scratchpad",
        "[con_id=13] scratchpad show",
        "[con_id=13] focus",
    ]


def test_a_minimized_window_is_reported_not_dropped(client, monkeypatch):
    """A taskbar that forgets a minimised window leaves no way to bring it back."""
    wins = client.windows()
    assert all(w["minimized"] is False for w in wins)
    # the scratchpad lives on its own workspace; anything there is minimised
    scratch = {"id": 1, "type": "root", "nodes": [{
        "id": 2, "type": "output", "name": "__i3", "nodes": [{
            "id": 30, "type": "workspace", "name": "__i3_scratch", "nodes": [
                {"id": 31, "pid": 7001, "app_id": "firefox", "name": "Mozilla Firefox",
                 "focused": False, "fullscreen_mode": 0, "nodes": [], "floating_nodes": []},
            ], "floating_nodes": []}]}]}
    monkeypatch.setattr(client, "_request", lambda t, p="": scratch)
    assert client.windows()[0]["minimized"] is True


def test_fullscreen_is_a_real_verb(client, sway):
    client.set_fullscreen("13", True)
    client.set_fullscreen("13", False)
    client.set_fullscreen("13")
    assert sway.commands == ["[con_id=13] fullscreen enable",
                            "[con_id=13] fullscreen disable",
                            "[con_id=13] fullscreen toggle"]


def test_raising_the_shell_floats_it_rather_than_fullscreening_it(client, sway, monkeypatch):
    """Focus alone cannot help: sway paints floating windows above tiled ones and
    the shell is the tiled base layer, so Ctrl+Space would summon a prompt bar
    nobody can see. Fullscreen would work too — but Chromium reads it as the PAGE
    going full screen and flashes "press and hold Esc" every single time."""
    monkeypatch.setattr(client, "find_shell", lambda port: "11")
    assert client.raise_shell(True) is True
    assert sway.commands == ["[con_id=11] floating enable, "
                            "resize set width 3840 px height 2160 px, "
                            "move absolute position 0 0, focus"], (
        "must be ONE chained command — sent separately, the client acks its "
        "remembered floating size before the resize lands")
    assert not any("fullscreen" in c for c in sway.commands)
    sway.commands.clear()
    client.raise_shell(False)
    assert sway.commands == ["[con_id=11] floating disable, border none"]


def test_show_desktop_hides_every_native_window(client, sway, monkeypatch):
    """The escape hatch: without it, one native window covering the screen with a
    broken minimise leaves the user with nowhere to go."""
    monkeypatch.setattr(client, "find_shell", lambda port: "11")
    n = client.show_desktop()
    assert n == 3                                     # firefox, pavucontrol, Gimp
    assert sway.commands[:3] == ["[con_id=13] move scratchpad",
                                 "[con_id=14] move scratchpad",
                                 "[con_id=21] move scratchpad"]
    assert sway.commands[-1] == "[con_id=11] focus"


def test_maximize_fills_the_desk_but_spares_the_menu_bar(client, sway):
    """Maximize and full screen are different things and people expect both: a
    maximized window leaves the menu bar reachable."""
    client.maximize("13")
    assert sway.commands == ["[con_id=13] floating enable",
                            "[con_id=13] resize set width 3840 px height 2126 px",   # 2160 - 34
                            "[con_id=13] move absolute position 0 34"]


def test_work_area_comes_from_the_real_output(client):
    x, y, w, h = client.work_area(top=34)
    assert (x, y, w, h) == (0, 34, 3840, 2126)


def test_a_desktop_is_a_real_workspace_and_the_shell_follows(client, sway, monkeypatch):
    """AgentOS desktops used to be a page-level idea while native windows lived on
    sway workspaces — which is exactly why every external app showed up on every
    desktop."""
    monkeypatch.setattr(client, "find_shell", lambda port: "11")
    client.goto_desktop(3)
    assert sway.commands == ["[con_id=11] move container to workspace 3",
                            "workspace 3",
                            "[con_id=11] floating disable"]


def test_anchoring_never_undoes_a_deliberate_summon(client, sway, monkeypatch):
    """anchor_shell runs on EVERY window event and does `floating disable`. It
    used to drop the desktop back behind the apps the instant Ctrl+Space raised
    it, so the prompt bar was summoned and then immediately hidden again."""
    monkeypatch.setattr(client, "find_shell", lambda port: "11")
    client.raise_shell(True)
    sway.commands.clear()
    assert client.anchor_shell(8321) is True
    assert sway.commands == [], "anchoring must be a no-op while the shell is summoned"
    client.raise_shell(False)
    sway.commands.clear()
    client.anchor_shell(8321)
    assert any("floating disable" in c for c in sway.commands)


# ---------------------------------------------------------------------------
# Handing the screen to an app.
#
# The session-mode bug these pin down: the AgentOS shell is a full-output
# FLOATING window whenever it has been summoned, and sway paints floating above
# tiled — so launching or focusing an app without lowering the desktop first put
# that app behind a screen-filling browser window. It was running. You just
# could not see it, which read as "nothing happened, this is only a web page".
# ---------------------------------------------------------------------------

NEW_WIN = {"id": 99, "pid": 7777, "app_id": "libreoffice", "name": "Untitled 1",
           "focused": False, "fullscreen_mode": 0, "nodes": [], "floating_nodes": []}


def test_focusing_an_app_lowers_the_desktop_first(client, sway):
    comp.SHELL_RAISED[0] = True
    try:
        client.focus("13")
    finally:
        comp.SHELL_RAISED[0] = False
    lower = next(i for i, c in enumerate(sway.commands) if "floating disable" in c)
    focus = next(i for i, c in enumerate(sway.commands) if c.endswith("] focus"))
    assert lower < focus, "the desktop must step back before the app takes focus"
    assert comp.SHELL_RAISED[0] is False


def test_focusing_does_not_touch_the_desktop_when_it_is_already_down(client, sway):
    comp.SHELL_RAISED[0] = False
    client.focus("13")
    assert not any("floating disable" in c for c in sway.commands)


def test_launch_waits_for_the_window_and_focuses_it(client, sway):
    sway.spawn_on_exec = NEW_WIN
    res = client.launch_and_focus("libreoffice --writer", timeout=3, poll=0.05)
    assert res["ok"] is True
    assert res["window"] == "99" and res["title"] == "Untitled 1"
    import base64 as _b64
    blob = _b64.b64encode(b"libreoffice --writer").decode()
    assert any(blob in c for c in sway.commands), "the command must survive verbatim"
    # the new window is focused, and the desktop was lowered before it appeared
    assert "[con_id=99] focus" in sway.commands
    assert any("floating disable" in c for c in sway.commands)


def test_launch_reports_failure_when_no_window_ever_appears(client, sway):
    sway.spawn_on_exec = None                    # the app dies on startup
    res = client.launch_and_focus("brokenapp", timeout=0.4, poll=0.05)
    assert res["ok"] is False
    assert "no window appeared" in res["reason"]
    # and the desktop comes back rather than leaving the user on a blank screen
    assert any("floating enable" in c for c in sway.commands)


def test_launch_ignores_windows_that_were_already_open(client, sway):
    """A slow app must not be 'confirmed' by firefox already being there."""
    res = client.launch_and_focus("slowapp", timeout=0.3, poll=0.05)
    assert res["ok"] is False
    assert "[con_id=13] focus" not in sway.commands


def test_floating_comes_from_the_tree_shape_not_a_field():
    """sway sends no `floating` key on window nodes — i3 does, and reading for it
    made every window report floating=False on every real session. The array a
    node sits in is the only fact there is."""
    assert "floating" not in TREE["nodes"][0]["nodes"][0]["floating_nodes"][0]


def test_exec_survives_sways_own_command_parser(client, sway):
    """sway parses the rest of an `exec` line itself: `,` and `;` separate
    commands and `<`/`>`/quotes are eaten or rejected. Real .desktop Exec lines
    are full of them — `--app=data:text/html,<title>x</title>` came back as
    "Unknown/invalid command '<title>x</title>'" and the app never started.
    Base64 makes the payload inert to that parser."""
    import base64 as _b64
    nasty = 'foot -T "T" sh -c "echo hi, there; echo <x>"'
    client.exec(nasty)
    sent = sway.commands[-1]
    assert nasty not in sent, "the raw command must not reach sway's parser"
    assert _b64.b64encode(nasty.encode()).decode() in sent
    for ch in (",", ";", "<", ">", '"'):
        assert ch not in sent.split("echo ")[1].split(" |")[0], f"{ch!r} reached the parser"
