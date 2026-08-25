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
import re

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
    # Every socket now passes ONE gate, `_ws_reject`, which does the cross-origin
    # refusal (CSWSH) BEFORE the auth check — see test_ws_origin.py. That gate
    # calls `_ws_authed` internally, so the relay is still authenticated and now
    # also origin-guarded; asserting the gate call is the current contract.
    assert "_ws_reject(ws)" in relay, "the relay is a full remote desktop; it must be gated"
    gate = server.split("async def _ws_reject")[1][:1200]
    assert "_ws_origin_ok(ws)" in gate and "_ws_authed(ws)" in gate, \
        "the WS gate must refuse cross-origin AND unauthenticated handshakes"
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


# --- the three faces --------------------------------------------------------
# CLAUDE.md's first rule: every feature is considered in GUI, TUI and SUI. These
# assert the TUI half of the two new capabilities exists, because a headless Pi
# reached over SSH is a first-class way to run AgentOS and "install a program" is
# the most ordinary thing anyone does with a machine.

def test_native_apps_and_remote_desktop_are_reachable_from_a_terminal():
    # Matched on the verb NAME, not on how it is registered. This used to pin
    # `sub.add_parser("apps"` and broke the day the CLI grew a registration helper
    # to keep `--help` short — a green-to-red on a test whose subject (does the TUI
    # have these verbs?) had not changed at all.
    cli = (SRC / "__main__.py").read_text()
    for name in ("apps", "remote-desktop"):
        assert re.search(rf'(sub\.add_parser|verb)\("{name}"', cli), (
            f"`bento {name}` is no longer registered — the TUI half of this "
            f"capability has gone")
    assert "def _apps_cli" in cli and "def _remote_desktop_cli" in cli


def test_the_cli_shows_the_command_before_running_it():
    """Installing software on someone's machine is not a thing to do invisibly."""
    cli = (SRC / "__main__.py").read_text()
    body = cli.split("def _apps_cli")[1].split("def _remote_desktop_cli")[0]
    assert 'res.get("command")' in body and "$ {res['command']}" in body


def test_doctor_reports_which_desktop_you_get():
    """The two answers are genuinely different desktops; the doctor must say
    which one, and print the line that upgrades the weaker one."""
    cli = (SRC / "__main__.py").read_text()
    assert "native desktop surface available" in cli
    assert "install_hint()" in cli


# --- never leave a blank screen ---------------------------------------------
# Reported from a real machine: the session came up black and needed a hard
# reboot. Three defects, all in the launcher, all of them the same mistake —
# treating "the libraries imported" as "the desktop appeared".

def test_the_launcher_does_not_exec_the_host():
    """`exec` replaces the process, which makes the fallback unreachable. The
    whole point of having a fallback is being able to get to it."""
    from agentos import session
    script = session.shell_script_text(8321)
    host = script.split("SHELLHOST=", 1)[1]
    assert 'exec "$HOSTPY"' not in host, "exec makes the Chromium fallback unreachable"
    assert "HOSTPID=$!" in host, "the host must run as a child so its exit can be seen"


def test_the_launcher_forces_wayland():
    """layer-shell is a Wayland protocol; gtk_layer_init_for_window() ABORTS under
    X11, and the script exports DISPLAY for XWayland apps just above."""
    from agentos import session
    assert 'GDK_BACKEND=wayland "$HOSTPY"' in session.shell_script_text(8321)
    assert 'os.environ.setdefault("GDK_BACKEND", "wayland")' in \
        (SRC / "shellhost.py").read_text()


def test_a_renderer_failure_falls_back_instead_of_ending_the_session():
    """Measured: WebKit can print "desktop is up", having really loaded the page,
    and segfault a moment later. So the marker is not proof on its own — the exit
    status is the other half, and a non-zero one must reach the fallback."""
    from agentos import session
    script = session.shell_script_text(8321)
    assert 'wait "$HOSTPID"; HOSTRC=$?' in script
    assert '[ "$HOSTRC" = 0 ] && exit 0' in script, "only a CLEAN exit is a logout"
    assert "falling back to Chromium" in script


def test_the_host_gives_up_rather_than_sitting_on_a_black_screen():
    host = (SRC / "shellhost.py").read_text()
    assert "--give-up-after" in host
    assert 'state["exit"] = 3' in host, "failing to render must be a non-zero exit"
    assert "return state[\"exit\"]" in host, "main() must propagate the failure"


def test_an_early_failure_is_remembered_and_is_clearable():
    """A machine that cannot draw must not spend 25 black seconds on every login —
    and dying after hours of use is a crash, not a verdict on the hardware."""
    from agentos import session
    script = session.shell_script_text(8321)
    assert "layer-shell-failed" in script
    assert "NOW - HOSTSTART" in script, "only an EARLY failure should be remembered"
    cli = (SRC / "__main__.py").read_text()
    assert "layer-shell-failed" in cli and "cleared the flag" in cli


def test_the_fallback_is_announced_on_screen():
    """A log nobody knows about is not telling the user."""
    from agentos import session
    assert "swaynag" in session.shell_script_text(8321).split("SHELLHOST=", 1)[1]


# --- the session diagnostic -------------------------------------------------
# `agentos doctor --session`. Built because the previous answer to "my screen is
# black" was "read a renderer's stderr and tell me what you see", which is the
# wrong way round.

def test_probes_run_in_subprocesses():
    """The failures being diagnosed are aborts and segfaults inside GTK and
    WebKit. A probe that crashes the doctor cannot report that it crashed."""
    src = (SRC / "sessiondoctor.py").read_text()
    assert "subprocess.run" in src
    assert "_signal_name" in src, "a signal death is a RESULT and must be named"


def test_loading_is_not_treated_as_drawing():
    """Measured: WebKit reports FINISHED, having really loaded and run the page,
    then segfaults seconds later while compositing it. A probe that exits on
    FINISHED passes on a machine that black-screens."""
    src = (SRC / "sessiondoctor.py").read_text()
    assert "state['loaded']" in src
    assert "kept drawing" in src
    assert "requestAnimationFrame" in src, "a still page can sit quietly on a broken stack"


def test_the_probe_loads_the_real_desktop_when_it_can():
    """A 20-byte page renders happily on a stack that dies on the real shell."""
    src = (SRC / "sessiondoctor.py").read_text()
    assert "__PROBE_URL__" in src and "_webkit_probe" in src
    assert "backdrop-filter" in src, "the synthetic fallback must cost what the shell costs"


def test_it_probes_the_combination_the_session_actually_uses():
    """WebKit can render in a window and still fail on a layer surface."""
    src = (SRC / "sessiondoctor.py").read_text()
    assert "PROBE_WEBKIT_LAYER" in src
    assert "GtkLayerShell.set_exclusive_zone" in src


def test_doctor_exposes_it():
    cli = (SRC / "__main__.py").read_text()
    assert '"--session"' in cli
    assert "sessiondoctor.report" in cli
