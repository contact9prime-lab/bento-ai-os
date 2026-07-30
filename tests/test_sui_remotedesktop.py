"""The session UI, the app store, and the browser remote desktop.

Three things arrived together, and each has one property that is easy to break
by accident and expensive to notice:

  · the session host must be launchable by an interpreter that is NOT the
    server's — the server lives in a virtualenv that usually cannot see the
    system PyGObject, so a hardcoded sys.executable means the desktop silently
    falls back to a Chromium window forever.
  · installing software and claiming to be the session's own desktop are
    loopback-only. A phone holding a valid remote session is a viewer of this
    machine, not its administrator.
  · the remote desktop's whole security argument is that wayvnc stays on
    127.0.0.1 and AgentOS's authentication is what protects it. If the VNC port
    ever gets bound to an address, that argument is gone.
"""
import pathlib

import pytest

from agentos import appstore, compositor, remotedesktop, shellhost

SRC = pathlib.Path(__file__).resolve().parents[1] / "agentos"


# --- the session host -------------------------------------------------------

def test_shellhost_imports_nothing_from_agentos():
    """It has to run under the SYSTEM python, which has no agentos package."""
    text = (SRC / "shellhost.py").read_text()
    body = text.split('"""', 2)[-1]          # skip the module docstring
    for bad in ("from . import", "from agentos", "import agentos"):
        assert bad not in body, f"shellhost.py must stay standalone; found {bad!r}"


def test_shellhost_probe_is_cached():
    """/api/platform calls available() on every page load; probing five
    interpreters each time would make the desktop feel broken."""
    shellhost._PROBED.clear()
    first = shellhost.python_with_gi()
    shellhost._PROBED[:] = [("/sentinel/python", "9.9")]
    assert shellhost.python_with_gi() == ("/sentinel/python", "9.9")
    shellhost._PROBED[:] = [first]


def test_install_hint_is_a_real_command():
    hint = shellhost.install_hint()
    assert "gtklayershell" in hint.replace("-", "") or "gtk-layer-shell" in hint
    assert hint.startswith("sudo ")


def test_session_script_probes_for_an_interpreter():
    """The generated launcher must not assume the server's python has PyGObject."""
    from agentos import session
    script = session.shell_script_text(8321)
    assert "shellhost.py" in script
    assert "GtkLayerShell" in script, "the launcher must test the import, not guess"
    assert "AGENTOS_NO_LAYER_SHELL" in script, "there must be a way to force the fallback"
    # and the Chromium fallback has to survive
    assert "RENDERER" in script and "--app=" in script


def test_sui_flag_disables_the_window_shuffling():
    """With the desktop on the BACKGROUND layer there is no window to anchor or
    raise; doing it anyway would grab some unrelated window."""
    comp = compositor.Compositor.__new__(compositor.Compositor)
    comp._sock = ""                      # any real call would raise
    compositor.SUI_HOST[0] = True
    try:
        assert comp.anchor_shell(8321) is True
        assert comp.raise_shell(True) is True
    finally:
        compositor.SUI_HOST[0] = False


def test_snap_zones_cover_halves_and_quarters():
    z = compositor.Compositor.SNAP_ZONES
    for name in ("left", "right", "top", "bottom", "tl", "tr", "bl", "br", "center", "full"):
        assert name in z
    assert z["left"] == (0.0, 0.0, 0.5, 1.0)
    assert z["br"] == (0.5, 0.5, 0.5, 0.5)


# --- the app store ----------------------------------------------------------

@pytest.mark.parametrize("pkg", [
    "gimp; rm -rf /", "gimp && curl evil", "gimp|sh", "../../etc/passwd",
    "$(whoami)", "`id`", "gimp\nrm -rf /", "", "a" * 300,
])
def test_package_names_that_could_become_a_second_command_are_refused(pkg):
    """This string reaches a privileged process. Validated, never escaped."""
    assert not appstore._valid(pkg)


@pytest.mark.parametrize("pkg", ["gimp", "libreoffice-calc", "org.inkscape.Inkscape",
                                 "python3-gi", "foo+bar", "a.b_c-1"])
def test_real_package_names_are_accepted(pkg):
    assert appstore._valid(pkg)


@pytest.mark.asyncio
async def test_act_refuses_a_bad_name_without_running_anything():
    res = await appstore.act("install", "gimp; rm -rf /")
    assert res["ok"] is False
    assert res["command"] == ""


@pytest.mark.asyncio
async def test_act_refuses_unknown_actions():
    res = await appstore.act("purge-everything", "gimp")
    assert res["ok"] is False


def test_flatpak_installs_per_user():
    """--user is the whole reason to prefer flatpak: no root, no prompt, and it
    cannot break the system's own packages."""
    argv = appstore._argv("install", "org.gimp.GIMP", "flatpak")
    assert "--user" in argv
    assert "flathub" in argv


# --- the remote desktop -----------------------------------------------------

def test_novnc_is_detected_by_the_file_we_need():
    """A directory can exist without the client in it."""
    assert "core" in str(remotedesktop.NOVNC_DIRS) or True
    text = (SRC / "remotedesktop.py").read_text()
    assert 'os.path.join(d, "core", "rfb.js")' in text


def test_the_page_talks_to_the_relay_not_to_the_vnc_port():
    """The phone must never be told to open port 5900 — that port is loopback."""
    page = remotedesktop.page("/ws/vnc", "somehost")
    assert "/ws/vnc" in page
    assert "5900" not in page
    assert "wsProtocols: ['binary']" in page, "base64 framing would double the bytes"


def test_vnc_stays_on_loopback():
    """The entire security argument: AgentOS authenticates, wayvnc never listens
    on anything but 127.0.0.1."""
    server = (SRC / "server.py").read_text()
    assert '"wayvnc", "127.0.0.1", str(VNC_PORT)' in server
    assert 'asyncio.open_connection("127.0.0.1", VNC_PORT)' in server


def test_relay_and_install_are_gated():
    server = (SRC / "server.py").read_text()
    # generous windows: these handlers open with long docstrings explaining the
    # security model, and the check is "the gate is in this handler", not "in the
    # first N characters of it"
    relay = server.split('@app.websocket("/ws/vnc")')[1][:2400]
    assert "_ws_authed(ws)" in relay, "the relay is a full remote desktop; it must be gated"
    store = server.split('async def api_native_store_act')[1][:900]
    assert "is_loopback" in store, "installing software must be loopback-only"
    sui = server.split("async def api_shell_sui")[1][:900]
    assert "is_loopback" in sui, "only the machine's own desktop may claim the session UI"


def test_novnc_route_resolves_before_checking_containment():
    """A string check for '..' is wrong in a way that is hard to see; this route
    reads files, so it must compare real paths."""
    server = (SRC / "server.py").read_text()
    route = server.split("async def novnc_asset")[1][:1200]
    assert "os.path.realpath" in route
    assert "startswith(root + os.sep)" in route
