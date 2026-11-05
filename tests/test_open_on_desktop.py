"""A server started at boot opens things on the desktop the person logged in to later.

systemd starts the service before the session imports DISPLAY/WAYLAND_DISPLAY, so xdg-open
ran with no screen: Chrome started without a window, held the profile, and "Open the floor"
said "opened in your browser" while nothing appeared (desktop.session_env)."""
from agentos import desktop

MANAGER = "HOME=/home/x\nDISPLAY=:0\nWAYLAND_DISPLAY=wayland-0\nXDG_CURRENT_DESKTOP=ubuntu:GNOME\nPATH=/usr/bin\n"


def test_a_boot_time_server_borrows_the_sessions_display(tmp_path):
    env = desktop.session_env({"XDG_RUNTIME_DIR": str(tmp_path), "PATH": "/bin"}, MANAGER)
    assert env["DISPLAY"] == ":0" and env["WAYLAND_DISPLAY"] == "wayland-0"
    assert env["XDG_CURRENT_DESKTOP"] == "ubuntu:GNOME"
    assert env["PATH"] == "/bin"          # only the session's keys are taken


def test_its_own_display_wins(tmp_path):
    env = desktop.session_env({"DISPLAY": ":5"}, MANAGER)
    assert env["DISPLAY"] == ":5" and "WAYLAND_DISPLAY" not in env


def test_the_wayland_socket_is_found_when_the_manager_has_nothing(tmp_path):
    (tmp_path / "wayland-1").touch()
    env = desktop.session_env({"XDG_RUNTIME_DIR": str(tmp_path)}, "")
    assert env["WAYLAND_DISPLAY"] == "wayland-1"


def test_no_screen_is_said_not_pretended(tmp_path, monkeypatch):
    assert desktop.session_env({"XDG_RUNTIME_DIR": str(tmp_path)}, "") is None
    monkeypatch.setattr(desktop, "IS_WIN", False)
    monkeypatch.setattr(desktop, "IS_MAC", False)
    monkeypatch.setattr(desktop, "session_env", lambda: None)
    started = []
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda *a, **k: started.append(a))
    assert "no desktop" in desktop.open_path("http://127.0.0.1:1/")
    assert not started
