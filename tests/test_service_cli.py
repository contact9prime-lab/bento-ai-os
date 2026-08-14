"""`bento service` — controlling the background server without knowing which OS you are on.

`bento install` put a systemd --user unit on Linux and a LaunchAgent on macOS, and
then every later question about that service — is it up, stop it, why did it die,
take it off this box — had to be answered in `systemctl` or `launchctl`. That is
asking someone to know which supervisor their machine uses in order to control their
own agent, and it is the same "capability that exists but has no way in" the TUI rule
in CLAUDE.md exists to prevent.

Nothing here starts or stops a real server. Every test either reads state or works
against paths redirected into tmp_path — a test that removed the developer's own
LaunchAgent would be a very memorable way to learn that lesson.
"""

import argparse

import pytest

from agentos import desktop


# ------------------------------------------------------------------ the CLI surface

def _service_action():
    """The real `action` argument of the real `bento service` parser.

    main() builds its parser inline and immediately parses, so the only way to read
    the shipped one is to intercept parse_args. Reconstructing an equivalent parser
    here would test the copy.
    """
    import agentos.__main__ as m

    seen = {}
    real_parse = argparse.ArgumentParser.parse_args

    def capture(self, *a, **k):
        seen["parser"] = self
        raise SystemExit(0)          # stop before main() does anything

    argparse.ArgumentParser.parse_args = capture
    try:
        with pytest.raises(SystemExit):
            m.main()
    finally:
        argparse.ArgumentParser.parse_args = real_parse

    sub = next(a for a in seen["parser"]._actions
               if isinstance(a, argparse._SubParsersAction))
    assert "service" in sub.choices, "`bento service` is not a registered subcommand"
    return next(a for a in sub.choices["service"]._actions if a.dest == "action")


def test_service_offers_the_whole_lifecycle():
    """Each of these is a question somebody had to answer in systemctl before."""
    choices = list(_service_action().choices)
    for verb in ("status", "start", "stop", "restart", "install", "uninstall", "logs"):
        assert verb in choices, f"`bento service {verb}` is missing"


def test_service_defaults_to_status():
    """A bare `bento service` must report, never act. Inferring `start` from a verb
    nobody typed is a CLI taking an action nobody asked for — and `stop` or
    `uninstall` as a default would be worse in the other direction."""
    assert _service_action().default == "status"


# ------------------------------------------------------------- what status reports

def test_service_manager_is_one_of_the_four_known_answers():
    assert desktop.service_manager() in {"systemd", "launchagent", "startup", "none"}


def test_status_has_every_field_the_cli_prints():
    st = desktop.service_status()
    for k in ("manager", "installed", "port", "running", "enabled", "answering",
              "detail", "pid"):
        assert k in st, f"service_status() no longer reports {k!r}"
    assert isinstance(st["port"], int)
    assert st["detail"].strip(), "a status with no sentence explains nothing"


def test_running_and_answering_are_separate_facts():
    """The interesting failure is a unit the supervisor calls 'active' while nothing
    answers on the port — a crash loop inside RestartSec, or a wedged startup.
    Collapsing the two into one boolean reports that state as healthy."""
    st = desktop.service_status()
    assert isinstance(st["running"], bool)
    assert isinstance(st["answering"], bool)
    assert "running" in st and "answering" in st


def test_a_free_port_has_no_listening_pid():
    """`service_stop` kills what `_listening_pid` finds, so a wrong answer here is a
    signal sent to somebody else's process."""
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    # the socket is closed now, so nothing holds `free`
    assert desktop._listening_pid(free) == ""


# ------------------------------------------- the commands sent to each supervisor
#
# A container has no user D-Bus and a Mac has no systemd, so neither branch can be
# exercised end to end on the machine that runs this suite. What CAN be checked
# everywhere is the thing that actually breaks: the argv. A wrong unit name or a
# missing `--user` fails at runtime on somebody else's machine, silently, as
# "the service did not start".

@pytest.fixture
def spy(monkeypatch):
    calls = []
    monkeypatch.setattr(desktop, "_run", lambda cmd: (calls.append(cmd), (True, ""))[1])
    monkeypatch.setattr(desktop, "_server_up", lambda port: False)
    monkeypatch.setattr(desktop, "_wait_for", lambda pred, seconds=20.0: True)
    return calls


def test_systemd_start_stop_restart_target_the_user_unit(spy, monkeypatch):
    monkeypatch.setattr(desktop, "service_manager", lambda: "systemd")
    desktop.service_start()
    desktop.service_restart()
    monkeypatch.setattr(desktop, "_wait_for", lambda pred, seconds=20.0: True)
    desktop.service_stop()

    issued = [c for c in spy if c and c[0] == "systemctl"]
    assert issued, "no systemctl command was issued on the systemd path"
    for cmd in issued:
        assert cmd[1] == "--user", (
            f"{cmd} is missing --user — that is the SYSTEM manager, which AgentOS "
            f"does not install into and cannot touch without root")
        assert cmd[-1] == f"{desktop.APP_ID}.service", f"{cmd} names the wrong unit"
    assert {c[2] for c in issued} == {"start", "restart", "stop"}


def test_launchd_stop_unloads_rather_than_killing(spy, monkeypatch):
    """The LaunchAgent sets KeepAlive, so launchd restarts the server the instant it
    is merely killed — a `stop` built on `kickstart -k` is a restart with extra
    steps. `bootout` is the only thing that actually stops it."""
    monkeypatch.setattr(desktop, "service_manager", lambda: "launchagent")
    monkeypatch.setattr(desktop, "_wait_for", lambda pred, seconds=20.0: True)
    desktop.service_stop()
    lc = [c for c in spy if c and c[0] == "launchctl"]
    assert lc, "no launchctl command was issued"
    assert any(c[1] == "bootout" for c in lc), f"stop did not bootout: {lc}"
    assert not any("kickstart" in c for c in lc), (
        "stop used kickstart, which KeepAlive turns straight back on")


def test_launchd_restart_uses_kickstart_k(spy, monkeypatch):
    monkeypatch.setattr(desktop, "service_manager", lambda: "launchagent")
    desktop.service_restart()
    lc = [c for c in spy if c and c[0] == "launchctl"]
    assert any(c[1:3] == ["kickstart", "-k"] for c in lc), f"{lc}"
    assert any(desktop.MAC_SERVER_LABEL in part for c in lc for part in c)


# ------------------------------------------------------------------ uninstall scope

def test_uninstalling_nothing_refuses_rather_than_claiming_success(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop, "SERVICE_FILE", tmp_path / "agentos.service")
    monkeypatch.setattr(desktop, "MAC_SERVER_PLIST", tmp_path / "server.plist")
    monkeypatch.setattr(desktop, "WIN_SERVER_VBS", tmp_path / "server.vbs")
    ok, msg = desktop.service_uninstall()
    assert not ok
    assert "no background service" in msg


def test_service_uninstall_leaves_the_launcher_and_the_data(tmp_path, monkeypatch):
    """`bento service uninstall` is deliberately narrower than `bento uninstall`.
    "Stop this machine answering on its own" and "remove AgentOS" are different
    requests, and the only way to make the first out of the second was to uninstall
    everything and reinstall the half you wanted back."""
    launcher = tmp_path / "agentos.desktop"
    launcher.write_text("[Desktop Entry]\n")
    icon = tmp_path / "agentos.svg"
    icon.write_text("<svg/>")
    unit = tmp_path / "agentos.service"
    unit.write_text("[Unit]\n")

    monkeypatch.setattr(desktop, "SERVICE_FILE", unit)
    monkeypatch.setattr(desktop, "DESKTOP_FILE", launcher)
    monkeypatch.setattr(desktop, "ICON_FILE", icon)
    monkeypatch.setattr(desktop, "MAC_SERVER_PLIST", tmp_path / "absent.plist")
    monkeypatch.setattr(desktop, "WIN_SERVER_VBS", tmp_path / "absent.vbs")
    monkeypatch.setattr(desktop, "_run", lambda cmd: (True, ""))
    monkeypatch.setattr(desktop, "_server_up", lambda port: False)

    if desktop.IS_MAC or desktop.IS_WIN:
        pytest.skip("the systemd branch only exists on Linux")

    ok, msg = desktop.service_uninstall()
    assert ok, msg
    assert not unit.exists(), "the unit was not removed"
    assert launcher.exists(), "service uninstall removed the app launcher too"
    assert icon.exists(), "service uninstall removed the icon too"
    assert "bento service install" in msg, "no way back is offered"


# ------------------------------------------- install must not claim a start it got

def test_install_verifies_the_server_answered_before_calling_it_started():
    """`systemctl enable --now` exits 0 when systemd ACCEPTS the job, not when the
    server binds. A unit whose ExecStart cannot bind — port 80 without privilege is
    the everyday case — leaves systemctl returning 0 while the service dies, waits
    RestartSec, and dies again.

    That printed `✓ service enabled + started (http://127.0.0.1:80)` on a machine
    where nothing would ever answer, and the next thing the user saw was `bento`
    refusing to bind the very same port. Two contradictory claims, the false one
    printed as the result.
    """
    import inspect
    # Comments are stripped first: the note above the fix quotes the false line it
    # replaced, and matching that instead of the code would make this test pass on
    # the very code it exists to reject.
    src = "\n".join(ln for ln in inspect.getsource(desktop._install_linux).splitlines()
                    if not ln.strip().startswith("#"))
    started = src.index("enabled + started")
    guard = src.rindex("_wait_for", 0, started)
    assert "_server_up" in src[guard:started], (
        "the success line is printed without waiting for the port to answer")
    assert "is-active" in src, "the failure branch does not say whether the unit died"


def test_install_shows_the_journal_when_the_service_does_not_answer():
    """'It did not come up' with no output is a dead end — the reason is one
    journalctl away and the user should not have to know that."""
    import inspect
    assert "journalctl" in inspect.getsource(desktop._install_linux)


def test_the_mac_launchagent_is_verified_the_same_way():
    """`launchctl bootstrap` returning 0 means launchd took the job, not that the
    server bound the port — the identical trap, one platform over."""
    import inspect
    src = inspect.getsource(desktop._install_mac)
    assert "_wait_for" in src and "_server_up" in src


# ------------------------------------------------------------------------ the logs

def test_the_mac_launchagent_captures_its_own_output():
    """launchd sends stdout/stderr to /dev/null unless told otherwise, so a server
    that dies at startup leaves no evidence anywhere — and `bento service logs` on
    macOS would have nothing to read. systemd gets this free from the journal."""
    import inspect
    src = inspect.getsource(desktop._install_mac)
    assert "StandardOutPath" in src and "StandardErrorPath" in src
    assert "server_log()" in src


def test_the_server_log_is_resolved_late_not_frozen_at_import():
    """The hazard tests/conftest.py exists for, one module over: `agentos.config`
    resolves AGENTOS_HOME at import, so a module-level `SERVER_LOG = ... / "logs"`
    keeps writing the developer's real ~/.agentos no matter what is redirected
    afterwards — which is how a test suite starts appending to a live install."""
    from agentos import config as cfgmod
    assert not hasattr(desktop, "SERVER_LOG"), (
        "SERVER_LOG is a module constant again — it is frozen against the real home")
    # this test runs under conftest's redirect, so a late-bound path follows it
    assert desktop.server_log().is_relative_to(cfgmod.AGENTOS_HOME)
