"""`bento update` — the terminal door onto machinery that already existed.

`agentos/updates.py` has done the real work for a long time: the version check, the
safety gate (`can_apply`), the fast-forward, the dependency sync, the test gate and the
rollback. It was reachable from the Settings panel and from a background watcher, and
from nowhere else — so on a headless box, which is exactly where a standing install
quietly falls behind, "update it" meant reading the source to find out what the panel
would have called. That is the gap CLAUDE.md's own rule names: a server capability
needs a way in without a pointer.

Nothing here re-implements any of that. These tests are about the two decisions the
CLI itself makes, and both are about not doing more than was asked:

  · a bare `bento update` CHECKS. It must never pull.
  · `--apply` finishes the job — including the restart, because files on disk that
    the running process has not loaded is a half-state nothing on screen explains.
"""

import argparse

import pytest

from agentos import __main__ as m


def _args(**kw):
    return argparse.Namespace(apply=kw.get("apply", False),
                              no_tests=kw.get("no_tests", False),
                              no_restart=kw.get("no_restart", False))


@pytest.fixture()
def upd(monkeypatch):
    """A fake `updates` module wired into the CLI, recording what got called."""
    from agentos import updates as real

    calls = {"check": 0, "apply": 0, "restart": 0}
    state = {"current": "0.2.0", "latest": "0.2.0", "update_available": False,
             "notes": "", "error": ""}
    gate = {"ok": True, "why": ""}
    outcome = {"ok": True, "from": "aaaaaaa", "to": "bbbbbbb", "files": 3,
               "version": "0.3.0", "unchanged": False}

    async def fake_check(cfg, force=False):
        calls["check"] += 1
        return dict(state)

    async def fake_apply(cfg, run_tests=True, log=None):
        calls["apply"] += 1
        calls["run_tests"] = run_tests
        return dict(outcome)

    monkeypatch.setattr(real, "check", fake_check)
    monkeypatch.setattr(real, "apply", fake_apply)
    monkeypatch.setattr(real, "can_apply", lambda cfg: (gate["ok"], gate["why"]))
    monkeypatch.setattr(real, "current", lambda: state["current"])
    monkeypatch.setattr(real, "install_dir", lambda: "/tmp/checkout")

    from agentos import desktop

    def fake_restart():
        calls["restart"] += 1
        return True, "restarted"

    monkeypatch.setattr(desktop, "service_restart", fake_restart)
    return calls, state, gate, outcome


# ------------------------------------------------------------------ nothing to do

def test_up_to_date_says_so_and_does_nothing(upd, capsys):
    calls, *_ = upd
    assert m._update_cli(_args()) == 0
    assert "up to date" in capsys.readouterr().out
    assert calls["apply"] == 0


def test_a_check_failure_is_reported_not_swallowed(upd, capsys):
    calls, state, *_ = upd
    state["error"] = "could not reach the update server (ConnectError)"
    assert m._update_cli(_args()) == 1
    assert "could not reach" in capsys.readouterr().out
    assert calls["apply"] == 0


# ------------------------------------------------------- an update is available

def test_a_bare_update_never_pulls(upd, capsys):
    """The load-bearing one. `bento update` rewriting the code that answers the
    user's turns, because they typed a verb, is not a thing this should ever do."""
    calls, state, *_ = upd
    state.update(latest="0.3.0", update_available=True)
    assert m._update_cli(_args()) == 0
    out = capsys.readouterr().out
    assert "0.3.0 is available" in out
    assert "bento update --apply" in out, "it does not say how to install it"
    assert calls["apply"] == 0, "a bare check pulled"


def test_it_says_upfront_when_this_machine_could_not_install_it(upd, capsys):
    """A checkout with local edits will refuse at --apply. Finding that out now beats
    finding it out halfway through an upgrade somebody scheduled overnight."""
    calls, state, gate, _ = upd
    state.update(latest="0.3.0", update_available=True)
    gate.update(ok=False, why="There are 4 uncommitted change(s) to tracked files")
    assert m._update_cli(_args()) == 1
    assert "uncommitted change" in capsys.readouterr().out
    assert calls["apply"] == 0


def test_apply_refuses_too_when_the_gate_is_shut(upd):
    calls, state, gate, _ = upd
    state.update(latest="0.3.0", update_available=True)
    gate.update(ok=False, why="not a git checkout")
    assert m._update_cli(_args(apply=True)) == 1
    assert calls["apply"] == 0


# --------------------------------------------------------------------- applying

def test_apply_pulls_and_restarts(upd, capsys):
    calls, state, *_ = upd
    state.update(latest="0.3.0", update_available=True)
    assert m._update_cli(_args(apply=True)) == 0
    assert calls["apply"] == 1
    assert calls["restart"] == 1, (
        "the files changed but the running process never loaded them — a half-state "
        "with nothing on screen to explain which version you are talking to")
    assert "aaaaaaa" in capsys.readouterr().out


def test_the_test_gate_is_on_unless_switched_off(upd):
    calls, state, *_ = upd
    state.update(latest="0.3.0", update_available=True)
    m._update_cli(_args(apply=True))
    assert calls["run_tests"] is True, "the gate that rolls a bad update back was off"
    m._update_cli(_args(apply=True, no_tests=True))
    assert calls["run_tests"] is False


def test_no_restart_leaves_it_to_the_user_but_says_so(upd, capsys):
    calls, state, *_ = upd
    state.update(latest="0.3.0", update_available=True)
    assert m._update_cli(_args(apply=True, no_restart=True)) == 0
    assert calls["restart"] == 0
    assert "bento service restart" in capsys.readouterr().out


def test_a_failed_apply_is_an_error_and_nothing_is_restarted(upd, capsys):
    calls, state, _, outcome = upd
    state.update(latest="0.3.0", update_available=True)
    outcome.update(ok=False, error="the new version fails its own tests — rolled back")
    assert m._update_cli(_args(apply=True)) == 1
    assert calls["restart"] == 0, "a rolled-back update restarted the service anyway"
    assert "rolled back" in capsys.readouterr().out


def test_an_already_current_checkout_is_not_reported_as_an_update(upd, capsys):
    """`unchanged` — the published version moved but this checkout was already at that
    commit. Restarting for nothing is noise."""
    calls, state, _, outcome = upd
    state.update(latest="0.3.0", update_available=True)
    outcome.update(unchanged=True)
    assert m._update_cli(_args(apply=True)) == 0
    assert calls["restart"] == 0
    assert "nothing changed" in capsys.readouterr().out


# ------------------------------------------------------------------ the CLI wiring

def test_update_is_a_registered_subcommand():
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
    sub = next(x for x in seen["p"]._actions
               if isinstance(x, argparse._SubParsersAction))
    assert "update" in sub.choices
    dests = {x.dest for x in sub.choices["update"]._actions}
    assert {"apply", "no_tests", "no_restart"} <= dests


def test_apply_defaults_to_off():
    """argparse's default IS the safety property tested above, stated once more where
    somebody changing the flag will see it."""
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
    sub = next(x for x in seen["p"]._actions
               if isinstance(x, argparse._SubParsersAction))
    ap = next(x for x in sub.choices["update"]._actions if x.dest == "apply")
    assert ap.default is False
