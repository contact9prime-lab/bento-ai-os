"""The compositor IPC client, against a fake sway.

The fake speaks the real i3-ipc wire protocol over a unix socket and serves a
recorded layout tree, so these tests exercise header packing, reply framing,
tree flattening and command generation without needing sway installed. The live
smoke test against real sway is `agentos doctor` + the nested-session check.
"""

import asyncio
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
                {"id": 14, "pid": 5002, "app_id": "pavucontrol", "name": "Volume Control",
                 "focused": False, "floating": "user_on", "fullscreen_mode": 0,
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
                    self.commands.append(payload.decode())
                    body = json.dumps(
                        [{"success": False, "error": "nope"}] if self.fail_commands
                        else [{"success": True}]).encode()
                    conn.sendall(HEADER.pack(magic, len(body), mtype) + body)
                elif mtype == comp.GET_TREE:
                    body = json.dumps(TREE).encode()
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
                  "workspace": "1", "focused": True, "floating": False, "fullscreen": False}
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


def test_unreachable_socket_raises_cleanly(tmp_path):
    c = comp.Compositor(sock=str(tmp_path / "absent.sock"))
    with pytest.raises(comp.CompositorError, match="cannot reach"):
        c.windows()
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
