"""Restarting the server, which has to come back on the address it was already on.

The interesting case is the one with no service manager: a server started by hand in
a terminal, which is how most development and every `bento serve` on a Pi runs. There
is nothing to ask for a restart, so `restart_service()` re-execs the process — and an
exec cannot recover the command line it is replacing.

That is the bug these are here for. The re-exec used to be a bare `serve`, which reads
the CONFIGURED port; a server on `--port 8402` therefore came back on 8321, hit
whatever already held it, and exited 3. From the outside the restart looked fine — the
request returned, the old process went away — and nothing was listening afterwards.
`/api/update` and snapshot-restore end in the same call, so an update on a non-default
port took the server down for good.
"""

import os

import pytest

from agentos import desktop


@pytest.fixture
def reexec(monkeypatch):
    """Capture the argv `restart_service()` would exec, without exec'ing it."""
    seen: dict = {}

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            self.target = target

        def start(self):
            monkeypatch.setattr(desktop.time, "sleep", lambda s: None)
            monkeypatch.setattr(desktop.os, "execv",
                                lambda path, argv: seen.update(path=path, argv=argv))
            self.target()

    monkeypatch.setattr(desktop.threading, "Thread", FakeThread)
    # No supervisor: force the re-exec branch regardless of the host machine.
    monkeypatch.setattr(desktop, "restart_method", lambda: "process")
    return seen


def test_the_restart_keeps_the_port_it_was_serving_on(reexec, monkeypatch):
    monkeypatch.setenv("AGENTOS_BOUND_PORT", "8402")
    monkeypatch.delenv("AGENTOS_BOUND_HOST", raising=False)
    desktop.restart_service()
    assert "--port" in reexec["argv"]
    assert reexec["argv"][reexec["argv"].index("--port") + 1] == "8402"


def test_the_restart_keeps_the_host_it_was_bound_to(reexec, monkeypatch):
    """A machine deliberately serving the LAN must not come back on loopback only —
    that is a remote desktop going dark with the server apparently healthy."""
    monkeypatch.setenv("AGENTOS_BOUND_PORT", "8321")
    monkeypatch.setenv("AGENTOS_BOUND_HOST", "0.0.0.0")
    desktop.restart_service()
    assert reexec["argv"][reexec["argv"].index("--host") + 1] == "0.0.0.0"


def test_an_unpublished_address_falls_back_rather_than_passing_junk(reexec, monkeypatch):
    """Older running instances predate the env vars. Missing means 'use the config',
    which is the previous behaviour — never an empty `--port ''`."""
    monkeypatch.delenv("AGENTOS_BOUND_PORT", raising=False)
    monkeypatch.delenv("AGENTOS_BOUND_HOST", raising=False)
    desktop.restart_service()
    assert "--port" not in reexec["argv"] and "--host" not in reexec["argv"]
    assert reexec["argv"][1:4] == ["-m", "agentos", "serve"]


def test_serve_publishes_the_port_it_actually_bound():
    """`restart_service()` reads these; `serve` is the only thing that knows them.

    Asserted as a contract between the two rather than by starting a server: the
    name is the whole interface, and a rename on either side is silent otherwise.
    """
    import inspect

    from agentos import __main__ as cli
    src = inspect.getsource(cli)
    assert 'os.environ["AGENTOS_BOUND_PORT"]' in src, \
        "serve must publish the bound port, or a restart cannot find its way back"
    assert 'os.environ["AGENTOS_BOUND_HOST"]' in src


def test_restart_method_names_the_supervisor_without_restarting_anything(monkeypatch, tmp_path):
    """The CLI prints a different sentence per mechanism, so this must be pure."""
    monkeypatch.setattr(desktop, "IS_MAC", False)
    monkeypatch.setattr(desktop, "IS_WIN", False)
    # A path that cannot exist, rather than patching Path.exists — which is
    # read-only on PosixPath and would take every other exists() check with it.
    monkeypatch.setattr(desktop, "SERVICE_FILE", tmp_path / "no-such.service")
    called = []
    monkeypatch.setattr(desktop, "_run", lambda argv: called.append(argv) or (False, ""))
    assert desktop.restart_method() == "process"
    assert not any("restart" in " ".join(c) for c in called), \
        "restart_method() must only look, never act"
