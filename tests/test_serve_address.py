"""What `bento serve` does about the address it was asked for — and about the server
that is already on it.

Two failures live here, and both used to be reported as something else:

- **Already running.** The old code printed four suggestions and exited 3, so the
  commonest case of all — it is already running, show it to me — was the one thing
  the CLI would not do. Worse, it could not tell AgentOS from a stranger: any process
  holding the port produced the same "AgentOS is already running (or something else
  holds it)", which is either an offer to stop somebody else's server or a refusal to
  restart your own, depending on which half was true.

- **A port the kernel will not give us.** `_port_free()` collapses every bind failure
  into "not free", so a privileged port looked exactly like a busy one and was
  reported as "something holds :80" when nothing did.

The rule of thumb both of these tempt you into — "below 1024 needs root" — is wrong
often enough to be dangerous. It is FALSE on macOS, which grants 0.0.0.0:80 to any
process (and, in the same breath, refuses 127.0.0.1:80 — the check is per-address,
not per-port). On Linux it holds only until somebody lowers
`net.ipv4.ip_unprivileged_port_start`, which containers routinely do. So nothing here
guesses from a port number: it binds, and reports what the kernel said.
"""

import argparse
import http.server
import socket
import threading

import pytest

from agentos import __main__ as m


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ------------------------------------------------------------ who holds the port

def test_a_free_port_is_free():
    assert m._holder("127.0.0.1", _free_port()) == "free"


def test_a_stranger_on_the_port_is_never_called_agentos():
    """The load-bearing half. 'Something is listening' is not permission to kill it:
    a port collision is just as likely to be somebody's dev server, and offering to
    stop it because the number matched would be a worse bug than the one this solves."""
    port = _free_port()
    srv = http.server.HTTPServer(("127.0.0.1", port),
                                 http.server.SimpleHTTPRequestHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        assert m._holder("127.0.0.1", port) == "foreign"
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_socket_that_never_speaks_http_is_foreign_not_agentos():
    """A bare listening socket answers nothing at all. The probe must time out into
    'foreign', not hang and not guess."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        assert m._holder("127.0.0.1", port) == "foreign"
    finally:
        s.close()


def test_next_free_port_skips_what_is_taken():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        assert m._next_free_port("127.0.0.1", port) > port
    finally:
        s.close()


# ------------------------------------------------------- can we bind it, and why not

def test_a_free_port_has_no_bind_problem():
    assert m._bind_problem("127.0.0.1", _free_port()) == ("", "")


def test_a_held_port_is_taken_not_denied():
    """'taken' routes to the already-running conversation; 'denied' must not. Getting
    these two confused is what reported a permission refusal as a phantom process."""
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        kind, why = m._bind_problem("127.0.0.1", port)
        assert kind == "taken", (kind, why)
    finally:
        s.close()


def test_an_address_this_machine_does_not_hold_says_so():
    """Binding 10.99.99.99 is not a busy port and not a permission problem — it is an
    address that does not exist here, and the fix is a different address."""
    kind, why = m._bind_problem("10.99.99.99", _free_port())
    assert kind == "no-such-address", (kind, why)
    assert "0.0.0.0" in why, "the answer that would work is not offered"


@pytest.fixture
def never_serves(monkeypatch):
    """Make reaching uvicorn a fast, loud failure.

    Without this a regression in the dispatch does not fail these tests — it HANGS
    them, because `serve` falls through and really starts a server on the real port.
    A test that catches a bug by never finishing is one somebody eventually deletes.
    """
    import uvicorn

    def boom(*a, **k):
        raise AssertionError("serve reached uvicorn.run — the bind check let it past")

    monkeypatch.setattr(uvicorn, "run", boom)


@pytest.mark.parametrize("kind", ["denied", "no-such-address", "other"])
def test_serve_stops_on_a_bind_it_cannot_make_and_never_calls_it_already_running(
        kind, monkeypatch, capsys, never_serves):
    """The dispatch, not just the diagnosis.

    Classifying correctly is useless if `serve` routes every non-free port into the
    already-running conversation anyway — which is the bug: a privileged port was
    announced as "something holds :80 that is not AgentOS" when nothing held it.
    An unmakeable bind must exit 4 and must never reach `_resolve_running_instance`.
    """
    monkeypatch.setattr(m, "_bind_problem", lambda h, p: (kind, "  because reasons"))

    def explode(*a, **k):                       # must not be reached
        raise AssertionError("serve treated an unmakeable bind as a running server")

    monkeypatch.setattr(m, "_resolve_running_instance", explode)
    monkeypatch.setattr(m, "_holder", explode)

    with pytest.raises(SystemExit) as e:
        m.serve("127.0.0.1", 8321, open_browser=False, if_running="fail")
    assert e.value.code == 4
    out = capsys.readouterr().out
    assert "cannot listen" in out and "because reasons" in out
    assert "already running" not in out


def test_serve_routes_a_genuinely_busy_port_to_the_running_instance_flow(
        monkeypatch, never_serves):
    """The other half: 'taken' — and only 'taken' — is what the already-running
    conversation is for."""
    monkeypatch.setattr(m, "_bind_problem", lambda h, p: ("taken", ""))
    called = {}

    def fake(host, port, url, mode, explicit_port):
        called["mode"] = mode
        raise SystemExit(3)

    monkeypatch.setattr(m, "_resolve_running_instance", fake)
    with pytest.raises(SystemExit) as e:
        m.serve("127.0.0.1", 8321, open_browser=False, if_running="fail")
    assert e.value.code == 3
    assert called["mode"] == "fail"


def test_the_bind_check_never_guesses_from_the_port_number():
    """`port < 1024` appears nowhere as a decision — only as wording AFTER the kernel
    has already refused. On macOS the guess is simply wrong."""
    import inspect
    src = inspect.getsource(m._bind_problem)
    body = src.split('"""', 2)[-1]          # drop the docstring
    assert "s.bind(" in body, "the check no longer actually binds"
    decision = body.index("except PermissionError")
    assert "port < 1024" not in body[:decision], (
        "the port number is being used to DECIDE, not just to explain")


# -------------------------------------------------------------- what we show a person

@pytest.mark.parametrize("wildcard", ["0.0.0.0", "::", ""])
def test_a_wildcard_bind_is_never_printed_as_the_way_in(wildcard):
    """0.0.0.0 is an instruction to the kernel, not an address. Browsers refuse or
    silently reinterpret http://0.0.0.0:8321, so printing it as the link — and
    handing it to webbrowser.open — offers a dead URL on exactly the setup somebody
    has just finished configuring."""
    assert m._display_url(wildcard, 8321) == "http://127.0.0.1:8321"


def test_a_real_address_is_shown_as_itself():
    assert m._display_url("192.168.1.20", 8080) == "http://192.168.1.20:8080"
    assert m._display_url("127.0.0.1", 8321) == "http://127.0.0.1:8321"


def test_the_install_line_says_when_the_machine_is_on_the_network():
    """`http://127.0.0.1:{port}` was hardcoded into the install and status output. On
    a box configured to be reachable that is not false — loopback does answer — but it
    is the one line somebody checks to find out whether their `bind` took effect, and
    it read as "your setting was ignored"."""
    from agentos import config as cfgmod
    from agentos import desktop

    cfg = cfgmod.load_config()
    cfg["port"] = 8321
    cfg.setdefault("remote", {}).update(
        {"enabled": True, "bind": "0.0.0.0", "pass_hash": "x", "pass_salt": "y"})
    cfgmod.save_config(cfg)

    lines = desktop.where_it_answers(8321)
    assert lines[0] == "http://127.0.0.1:8321", "loopback must stay first — it always works"
    assert any("0.0.0.0" in ln for ln in lines[1:]), (
        "a machine bound to every interface is still described as loopback-only")


def test_a_bind_that_is_configured_but_not_in_use_says_so():
    """`bind_host()` refuses to leave loopback without a lock, which is correct and
    deliberate. But the setting still sits in config.json saying 0.0.0.0, and the only
    way to find out which one won was to diff `cat config.json` against this line."""
    from agentos import config as cfgmod
    from agentos import desktop

    cfg = cfgmod.load_config()
    cfg.setdefault("remote", {}).update(
        {"enabled": False, "bind": "0.0.0.0", "pass_hash": "", "pass_salt": ""})
    cfgmod.save_config(cfg)

    text = "\n".join(desktop.where_it_answers(8321))
    assert "not in use" in text, "the ignored bind setting is still silent"
    assert "bento remote --on" in text, "no way out is offered"


def test_a_hostname_that_already_ends_in_local_gets_no_second_one(monkeypatch):
    """macOS's gethostname() returns the mDNS name in full, so appending `.local`
    produced `http://Someones-MacBook-Pro.local.local:8321` — an address that resolves
    nowhere, printed as the way to reach the machine from a phone."""
    import socket

    from agentos import remote as remotemod

    monkeypatch.setattr(socket, "gethostname", lambda: "Someones-MacBook-Pro.local")
    got = remotemod.lan_addresses(8321)
    assert not any(".local.local" in a for a in got), got
    assert any(a.endswith("Someones-MacBook-Pro.local:8321") for a in got), got

    monkeypatch.setattr(socket, "gethostname", lambda: "plainbox")
    assert any(a.endswith("plainbox.local:8321") for a in remotemod.lan_addresses(8321))


# ------------------------------------------------------------------- the --if-running flag

def _serve_arg(dest: str):
    seen = {}
    real = argparse.ArgumentParser.parse_args

    def capture(self, *a, **k):
        seen["p"] = self
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = capture
    try:
        with pytest.raises(SystemExit):
            m.main()
    finally:
        argparse.ArgumentParser.parse_args = real
    sub = next(a for a in seen["p"]._actions if isinstance(a, argparse._SubParsersAction))
    return next(a for a in sub.choices["serve"]._actions if a.dest == dest)


def test_if_running_offers_every_answer_and_asks_by_default():
    a = _serve_arg("if_running")
    assert set(a.choices) == {"ask", "open", "port", "restart", "fail"}
    assert a.default == "ask"


def test_ask_needs_a_terminal_and_falls_back_to_fail():
    """A systemd unit, a cron line and a CI step all reach `serve` with no tty. A
    prompt there hangs the boot; picking an action for them unasked is worse —
    `restart` from a unit is a restart loop."""
    import inspect
    src = inspect.getsource(m.serve)
    assert "isatty()" in src
    i = src.index("isatty()")
    assert 'mode = "fail"' in src[i:i + 400], (
        "no terminal no longer degrades to fail")


def test_the_reexec_pins_if_running_so_a_restart_cannot_stop_at_a_prompt():
    """`restart_service()`'s last resort is os.execv, and the replacement inherits
    this process's stdin — which for a server started from a terminal is a real tty.
    Without the pin, a restart that raced the old socket's release would stop at an
    interactive prompt nobody is watching, with the machine's only server gone."""
    import inspect

    from agentos import desktop
    src = inspect.getsource(desktop.restart_service)
    assert "--if-running=fail" in src


# ------------------------------------------------- a second instance is not free

def test_the_second_instance_warning_names_what_is_actually_shared():
    """`startup()` unconditionally creates a scheduler, an MCP manager, a Telegram
    poller and an update watcher against cfgmod.DB_PATH — one file per AGENTOS_HOME,
    not per port. Offering a second port without saying that is offering duplicate
    job runs and two long-pollers on one bot token."""
    w = m._second_instance_warning()
    assert "scheduler" in w.lower() and "telegram" in w.lower()
    assert "AGENTOS_HOME" in w, "the genuinely-separate-instance answer is missing"


# ---------------------------------------------------------------- the port setting

def test_remote_accepts_a_port():
    a = None
    seen = {}
    real = argparse.ArgumentParser.parse_args

    def capture(self, *args, **k):
        seen["p"] = self
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = capture
    try:
        with pytest.raises(SystemExit):
            m.main()
    finally:
        argparse.ArgumentParser.parse_args = real
    sub = next(x for x in seen["p"]._actions if isinstance(x, argparse._SubParsersAction))
    dests = {x.dest for x in sub.choices["remote"]._actions}
    assert "port" in dests, (
        "`bento remote --port` is gone — the persisted port has no CLI again, and "
        "`serve --port` lasts one run while the service bakes in the config value")
    assert a is None


def test_setting_the_port_persists_it(capsys):
    from agentos import config as cfgmod

    args = argparse.Namespace(on=False, off=False, passphrase="", bind="", port=9137)
    m._remote_cli(args)
    assert cfgmod.load_config()["port"] == 9137


def test_an_impossible_port_is_refused_before_it_is_saved():
    from agentos import config as cfgmod

    before = cfgmod.load_config().get("port")
    args = argparse.Namespace(on=False, off=False, passphrase="", bind="", port=99999)
    with pytest.raises(SystemExit):
        m._remote_cli(args)
    assert cfgmod.load_config().get("port") == before
