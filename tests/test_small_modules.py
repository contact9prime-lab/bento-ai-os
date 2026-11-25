"""Modules no test named before the test report found them: clitui (the plain terminal
client) and sessiondoctor (`agentos doctor --session`). Each test here pins the claim the
module's own docstring makes. (The third was trainforge, the separate training service;
it is gone, and Train is tested in test_train.py.)"""
import asyncio
import os
import signal
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import clitui, sessiondoctor, shellhost   # noqa: E402


# ---- sessiondoctor: a crash is a result, and nothing is changed ------------------------

def test_a_probe_that_crashes_reports_its_signal(monkeypatch):
    monkeypatch.setattr(shellhost, "python_with_gi", lambda: (sys.executable, "test"))
    rc, out = sessiondoctor._run_py("import os, signal; os.kill(os.getpid(), signal.SIGSEGV)")
    assert rc == -signal.SIGSEGV and sessiondoctor._signal_name(rc) == " (killed by SIGSEGV)"
    assert sessiondoctor._signal_name(0) == ""


def test_a_probe_that_hangs_says_it_hung(monkeypatch):
    monkeypatch.setattr(shellhost, "python_with_gi", lambda: (sys.executable, "test"))
    rc, out = sessiondoctor._run_py("import time; time.sleep(5)", timeout=0.5)
    assert rc == 124 and "hung" in out


def test_no_interpreter_is_said_with_the_fix(monkeypatch):
    monkeypatch.setattr(shellhost, "python_with_gi", lambda: ("", ""))
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    said = {"ok": [], "warn": [], "bad": [], "todo": []}
    sessiondoctor.report(*(said[k].append for k in ("ok", "warn", "bad", "todo")))
    assert said["bad"] and "PyGObject" in said["bad"][0]
    assert said["todo"] and said["warn"], "what to do, and that this shell is not the session"
    assert sessiondoctor._run_py("print(1)")[0] == 127


# ---- clitui: the plain client draws for whatever it is attached to ----------------------

def test_the_banner_does_not_clear_a_screen_that_is_not_a_terminal(capsys, monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)
    clitui._banner({"cores": 4, "cpu": 12.0, "mem": {"used_kb": 2e6, "total_kb": 8e6},
                    "disk": {"used": 5e10, "total": 1e11}}, "", "Aria")
    out = capsys.readouterr().out
    assert "\033[2J" not in out and "no model" in out and "4 cores" in out and "Aria" in out


def test_system_view_with_nothing_says_so(capsys):
    clitui._print_sys({})
    assert "no data" in capsys.readouterr().out


def test_the_width_never_passes_96_columns(monkeypatch):
    monkeypatch.setattr(clitui.os, "get_terminal_size", lambda: os.terminal_size((300, 50)))
    assert clitui._w() == 96
    def raises():
        raise OSError
    monkeypatch.setattr(clitui.os, "get_terminal_size", raises)
    assert clitui._w() == 80
