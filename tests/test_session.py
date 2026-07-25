"""The session installer.

What matters here is the non-destructive guarantee and the safety rails:
staging never needs root, generated scripts carry the configured port instead
of a hardcoded one, autologin refuses to run blind over SSH, and removal
strips exactly what install added — including the ~/.profile hook, without
eating the rest of the file.
"""

import os
from pathlib import Path

import pytest

from agentos import session


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Redirect every filesystem target into a sandbox and neuter sudo/subprocess."""
    monkeypatch.setattr(session, "BIN_DIR", tmp_path / "bin")
    monkeypatch.setattr(session, "SESSION_SCRIPT", tmp_path / "bin" / "agentos-session-wayland")
    monkeypatch.setattr(session, "SHELL_SCRIPT", tmp_path / "bin" / "agentos-shell")
    monkeypatch.setattr(session, "X11_SESSION_SCRIPT", tmp_path / "bin" / "agentos-session")
    monkeypatch.setattr(session, "SWAY_CONF", tmp_path / "cfg" / "sway.conf")
    monkeypatch.setattr(session, "SWAY_DROPIN_DIR", tmp_path / "cfg" / "sway.d")
    monkeypatch.setattr(session, "WL_STAGE", tmp_path / "stage" / "wl.desktop")
    monkeypatch.setattr(session, "X11_STAGE", tmp_path / "stage" / "x11.desktop")
    monkeypatch.setattr(session.cfgmod, "AGENTOS_HOME", tmp_path / "stage")
    monkeypatch.setattr(session, "_run", lambda cmd: (False, "disabled in tests"))
    monkeypatch.setattr(session, "_port", lambda: 9111)
    return tmp_path


def test_stage_wayland_writes_only_user_files(home):
    written = session.stage(wayland=True)
    assert all(str(p).startswith(str(home)) for p in written), "stage() must never need root"
    assert session.SWAY_CONF.exists()
    assert session.SESSION_SCRIPT.exists() and os.access(session.SESSION_SCRIPT, os.X_OK)
    assert session.SHELL_SCRIPT.exists() and os.access(session.SHELL_SCRIPT, os.X_OK)
    assert session.WL_STAGE.exists()


def test_generated_scripts_use_the_configured_port(home):
    """The old X11 generator hardcoded 8321; both variants must honour config."""
    session.stage(wayland=True)
    session.stage(wayland=False)
    assert "9111" in session.SHELL_SCRIPT.read_text()
    assert "8321" not in session.SHELL_SCRIPT.read_text()
    assert "9111" in session.X11_SESSION_SCRIPT.read_text()
    assert "8321" not in session.X11_SESSION_SCRIPT.read_text()


def test_session_script_marks_the_session_and_hands_off_to_sway(home):
    session.stage(wayland=True)
    text = session.SESSION_SCRIPT.read_text()
    assert "AGENTOS_SESSION=1" in text
    assert "XDG_CURRENT_DESKTOP=AgentOS" in text
    assert "exec sway" in text
    # The server must NOT be started here — it has to start inside sway so it
    # inherits $SWAYSOCK and detects `de` mode. That's the shell script's job.
    assert "agentos serve" not in text
    assert "agentos serve" in session.SHELL_SCRIPT.read_text()


def test_sway_conf_is_an_invisible_engine_with_an_escape_hatch(home):
    session.stage(wayland=True)
    conf = session.SWAY_CONF.read_text()
    assert "xwayland enable" in conf
    assert "bar" not in conf.split("include")[0].lower().replace("bars", "")  # no bar block
    assert "Ctrl+Alt+BackSpace" in conf                  # the one keybinding
    assert "swaymsg exit" in conf                        # renderer death ends the session
    assert str(session.SWAY_DROPIN_DIR) in conf          # user overrides survive regeneration


def test_wayland_entry_points_at_the_session_script(home):
    session.stage(wayland=True)
    entry = session.WL_STAGE.read_text()
    assert f"Exec={session.SESSION_SCRIPT}" in entry
    assert "Name=AgentOS" in entry


def test_autologin_refuses_over_ssh_without_force(home, monkeypatch, capsys):
    monkeypatch.setenv("SSH_CONNECTION", "10.0.0.5 22 10.0.0.9 22")
    assert session.install_autologin(force=False) is False
    out = capsys.readouterr().out
    assert "SSH" in out and "--force" in out


def test_autologin_prints_the_escape_hatch_before_changing_anything(home, monkeypatch, capsys):
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.delenv("SSH_TTY", raising=False)
    monkeypatch.setenv("USER", "piyush")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    session.install_autologin(force=False)   # sudo is disabled → prints commands
    out = capsys.readouterr().out
    assert "Ctrl+Alt+F3" in out
    assert "--remove --autologin" in out


def test_profile_hook_is_guarded_and_strippable(home, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    profile = home / ".profile"
    profile.write_text("# my existing profile\nexport EDITOR=vim\n")
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.delenv("SSH_TTY", raising=False)
    monkeypatch.setenv("USER", "piyush")
    session.install_autologin(force=False)

    text = profile.read_text()
    assert session.PROFILE_MARK_BEGIN in text
    assert '"$(tty)" = "/dev/tty1"' in text              # only ever fires on tty1
    assert "export EDITOR=vim" in text                   # existing content intact

    # Running install twice must not duplicate the hook.
    session.install_autologin(force=False)
    assert profile.read_text().count(session.PROFILE_MARK_BEGIN) == 1

    session._strip_profile_snippet(profile)
    text = profile.read_text()
    assert session.PROFILE_MARK_BEGIN not in text
    assert "tty1" not in text
    assert "export EDITOR=vim" in text                   # removal only removes ours


def test_remove_deletes_generated_user_files(home, capsys):
    session.stage(wayland=True)
    session.stage(wayland=False)
    session.remove()
    assert not session.SESSION_SCRIPT.exists()
    assert not session.SHELL_SCRIPT.exists()
    assert not session.X11_SESSION_SCRIPT.exists()
    assert not session.SWAY_CONF.exists()
    # sudo unavailable → the root-owned paths are printed, not silently skipped
    assert "sudo rm -f" in capsys.readouterr().out


def test_wayland_install_requires_sway(home, monkeypatch, capsys):
    monkeypatch.setattr(session.shutil, "which", lambda name: None)
    session.install(wayland=True)
    out = capsys.readouterr().out
    assert "sway is not installed" in out
    assert not session.SESSION_SCRIPT.exists(), "must not stage a session that cannot start"


def test_x11_delegate_still_works(home, monkeypatch):
    """desktop.install_session() predates session.py; it must keep functioning."""
    from agentos import desktop
    monkeypatch.setattr(session.shutil, "which", lambda name: "/usr/bin/" + name)
    desktop.install_session()
    assert session.X11_SESSION_SCRIPT.exists()


def test_wayland_install_never_touches_the_legacy_x11_script(home, monkeypatch):
    """Machines with the old X11 entry installed have /usr/share/xsessions
    pointing at ~/.local/bin/agentos-session. Staging the Wayland session must
    leave that script exactly as it was."""
    session.stage(wayland=False)
    before = session.X11_SESSION_SCRIPT.read_text()
    session.stage(wayland=True)
    assert session.X11_SESSION_SCRIPT.read_text() == before
    assert session.SESSION_SCRIPT != session.X11_SESSION_SCRIPT
    assert "exec sway" not in before
