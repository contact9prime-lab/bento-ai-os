"""Three modules no test named before the test report found them: clitui (the plain
terminal client), sessiondoctor (`agentos doctor --session`) and trainforge (the Train
service). Each test here pins the claim the module's own docstring makes."""
import asyncio
import os
import signal
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import clitui, sessiondoctor, shellhost, trainforge   # noqa: E402


# ---- trainforge: found where it lives, and never listening beyond loopback -------------

def _checkout(p: Path) -> Path:
    (p / "server").mkdir(parents=True)
    (p / "server" / "main.py").write_text("")
    return p


def test_a_stale_configured_path_falls_through_to_one_that_has_the_server(tmp_path, monkeypatch):
    real = _checkout(tmp_path / "found" / "doneitrightai")          # the repo nests one level
    monkeypatch.setattr(trainforge, "_KNOWN_LOCATIONS", [str(tmp_path / "found")])
    c = trainforge.conf({"trainforge": {"path": str(tmp_path / "gone")}})
    assert c["path"] == str(real), "a path with no server/main.py is stale, and the nested repo counts"
    assert c["port"] == trainforge.DEFAULT_PORT != 8000


def test_nothing_found_is_an_empty_path_not_a_guess(tmp_path, monkeypatch):
    monkeypatch.setattr(trainforge, "_KNOWN_LOCATIONS", [str(tmp_path / "nowhere")])
    assert trainforge.conf({})["path"] == ""


def test_it_is_reached_and_started_on_loopback_only():
    tf = trainforge.TrainForge({"trainforge": {"port": 8399}}, store=None)
    assert tf.base_url() == "http://127.0.0.1:8399"
    src = Path(trainforge.__file__).read_text()
    assert '"TRAINFORGE_HOST": "127.0.0.1"' in src, "it has no auth, so it never listens beyond loopback"


def test_a_machine_with_no_download_url_says_so(tmp_path, monkeypatch):
    class _Store:
        def log(self, *a, **k):
            pass
    monkeypatch.setattr(trainforge, "_KNOWN_LOCATIONS", [])
    tf = trainforge.TrainForge({"trainforge": {"install_dir": str(tmp_path / "tf")}}, _Store())
    path, err = asyncio.run(tf._fetch())
    assert path == "" and "trainforge.repo" in err and not (tmp_path / "tf").exists()


def test_health_says_not_running_when_nothing_answers(tmp_path, monkeypatch):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                                        # a port nothing listens on
    monkeypatch.setattr(trainforge, "_KNOWN_LOCATIONS", [])
    tf = trainforge.TrainForge({"trainforge": {"port": port}}, store=None)
    h = asyncio.run(tf.health())
    assert h["running"] is False and h["managed"] is False and h["fetchable"] is False


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
