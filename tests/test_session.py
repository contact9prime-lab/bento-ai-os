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
    monkeypatch.setattr(session, "IDLE_SCRIPT", tmp_path / "bin" / "agentos-idle")
    monkeypatch.setattr(session, "POWER_SCRIPT", tmp_path / "bin" / "agentos-power")
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
    # Ctrl+Alt+Delete has to be claimed by the compositor. Unbound, the kernel
    # answers it and ctrl-alt-del.target is an alias for reboot.target — an
    # instant reboot with nothing saved and nothing asked.
    assert session.POWER_SCRIPT.exists() and os.access(session.POWER_SCRIPT, os.X_OK)
    conf = session.SWAY_CONF.read_text()
    assert "bindsym Ctrl+Alt+Delete" in conf
    assert "bindsym Ctrl+Alt+BackSpace" in conf, "the emergency hatch must survive too"
    # and it must offer a CHOICE, never act on its own
    power = session.POWER_SCRIPT.read_text()
    assert '"action":"power"' in power
    assert "swaynag" in power, "if the shell is not answering, the compositor must ask"
    for destructive in ("poweroff", "reboot", "shutdown"):
        assert f"exec {destructive}" not in power


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
    import re as _re
    body = conf.split("include")[0]
    assert not _re.search(r"^\s*bar\s*\{", body, _re.M), "sway must draw no bar of its own"
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


# --- display & input settings: what a Wayland session is expected to own -----

def test_display_layout_survives_logout(home):
    """Applying a mode over IPC lasts until logout. GNOME's Displays panel makes
    it stick; so must ours, or every reboot forgets the second monitor."""
    path = session.write_output_config([
        {"name": "HDMI-A-1", "mode": "2560x1440@59.951Hz", "scale": 1.25,
         "position": "0,0", "transform": "normal"},
        {"name": "eDP-1", "enabled": False},
        {"name": "", "mode": "junk"},                      # nameless output is skipped
    ])
    text = path.read_text()
    assert 'output "HDMI-A-1" mode 2560x1440@59.951Hz scale 1.25 transform normal position 0,0 enable' in text
    assert 'output "eDP-1" disable' in text
    assert "junk" not in text
    assert str(path.parent) == str(session.SWAY_DROPIN_DIR), "must land in the drop-in dir"


def test_input_config_speaks_sway(home):
    text = session.input_config_text({
        "keyboard": {"layout": "in", "variant": "eng", "repeat_delay": 250, "repeat_rate": 40},
        "touchpad": {"tap": True, "natural_scroll": False, "dwt": True, "accel": 0.3},
    })
    assert 'xkb_layout "in"' in text and 'xkb_variant "eng"' in text
    assert "repeat_delay 250" in text and "repeat_rate 40" in text
    assert "tap enabled" in text and "natural_scroll disabled" in text and "dwt enabled" in text
    assert "pointer_accel 0.30" in text


def test_empty_input_settings_write_nothing_to_override(home):
    """Saving defaults must not pin the system's own keyboard layout."""
    text = session.input_config_text({})
    assert "input type:keyboard" not in text and "input type:touchpad" not in text


def test_dropins_are_not_applied_outside_a_live_session(home, monkeypatch):
    monkeypatch.delenv("SWAYSOCK", raising=False)
    assert session.apply_dropins() is False


def test_display_change_is_both_applied_and_persisted(home, monkeypatch):
    """The endpoint used to have this block sitting after its `return`, so every
    display change was forgotten at logout. Guard the wiring, not just the writer."""
    import asyncio
    from agentos import server, host

    monkeypatch.setattr(host, "configure_output", lambda name, **kw: (True, "ok"))
    monkeypatch.setattr(server.cfgmod, "save_config", lambda cfg: None)
    monkeypatch.setitem(server.state, "cfg", {})
    r = asyncio.run(server.api_wm_output_configure(
        {"name": "HDMI-A-1", "scale": 1.5, "position": {"x": 1920, "y": 0}}))
    assert r["ok"] is True
    text = (session.SWAY_DROPIN_DIR / "outputs.conf").read_text()
    assert 'output "HDMI-A-1" scale 1.5 position 1920,0 enable' in text
    assert server.state["cfg"]["displays"]["HDMI-A-1"]["scale"] == 1.5


def test_a_display_the_compositor_rejects_is_not_persisted(home, monkeypatch):
    """Writing a layout the hardware refused would break the next login."""
    import asyncio
    from agentos import server, host

    monkeypatch.setattr(host, "configure_output", lambda name, **kw: (False, "no such mode"))
    monkeypatch.setattr(server.cfgmod, "save_config", lambda cfg: None)
    monkeypatch.setitem(server.state, "cfg", {})
    r = asyncio.run(server.api_wm_output_configure({"name": "HDMI-A-1", "mode": "9999x9999"}))
    assert r["ok"] is False
    assert not (session.SWAY_DROPIN_DIR / "outputs.conf").exists()
    assert "displays" not in server.state["cfg"]


def test_night_light_is_off_until_asked_for(home):
    assert session.nightlight_cmd_text(None) == ":"
    assert session.nightlight_cmd_text({"enabled": False, "night_temp": 3000}) == ":"


def test_night_light_uses_the_hours_or_the_place(home):
    by_clock = session.nightlight_cmd_text(
        {"enabled": True, "night_temp": 3400, "day_temp": 6500, "from": "19:30", "to": "07:00"})
    assert "wlsunset -t 3400 -T 6500 -S 19:30 -s 07:00" in by_clock
    by_place = session.nightlight_cmd_text(
        {"enabled": True, "night_temp": 4000, "lat": 12.97, "lon": 77.59})
    assert "-l 12.97 -L 77.59" in by_place and "-S" not in by_place


def test_night_light_lands_in_a_dropin_so_it_survives_reinstall(home):
    path = session.stage_nightlight({"enabled": True, "night_temp": 3800})
    assert path.parent == session.SWAY_DROPIN_DIR
    assert "wlsunset" in path.read_text()
    # turning it off must actively clear it, not merely stop writing
    session.stage_nightlight({"enabled": False})
    assert "wlsunset -t" not in path.read_text()
    assert "pkill" in path.read_text()


def test_the_session_provides_what_a_wayland_desktop_is_expected_to(home):
    """Portals, auto-mount, media keys and idle inhibition are not extras — a
    session without them silently fails at screen sharing, USB sticks, the
    play/pause key, and locks the screen halfway through a film."""
    conf = session.sway_config_text(9111)
    assert "xdg-desktop-portal" in conf
    assert "udiskie" in conf
    assert "XF86AudioPlay exec playerctl play-pause" in conf
    assert "inhibit_idle fullscreen" in conf


def test_the_session_identifies_itself_as_something_other_software_knows(home):
    """XDG_CURRENT_DESKTOP is a list, and it is how portals pick a backend and
    how secret storage decides it is on a real desktop. "AgentOS" alone means
    nothing to them — which is what produced "OS keyring couldn't be identified
    for your current desktop environment" and secrets stored in plain text."""
    script = session.session_script_text()
    assert "XDG_CURRENT_DESKTOP=AgentOS:sway:wlroots:GNOME" in script
    assert "XDG_SESSION_TYPE=wayland" in script


def test_the_secret_service_starts_before_the_compositor(home):
    """Started from inside sway it would only reach D-Bus-activated services;
    apps launched by the session would still find no keyring."""
    script = session.session_script_text()
    keyring = script.index("gnome-keyring-daemon")
    assert keyring < script.index("exec sway")
    assert "export SSH_AUTH_SOCK GNOME_KEYRING_CONTROL" in script


def test_native_windows_can_be_switched_and_put_away(home):
    conf = session.sway_config_text(9111)
    assert "Mod1+Tab" in conf and "Mod4+Tab" in conf
    assert "/api/windows/showdesktop" in conf
    assert "/api/windows/minimize" in conf
    # Ctrl+Tab belongs to the focused app (browser tabs), not to the window manager
    assert "bindsym Ctrl+Tab" not in conf


def test_coming_back_from_suspend_or_lock_is_handled(home):
    """Without after-resume and unlock hooks the outputs stayed powered off and
    the shell kept no focus — a black screen with no way back to the desktop."""
    idle = session.idle_script_text(9111, wallpaper="/w.png")
    assert "after-resume" in idle and "unlock '" in idle
    assert idle.count("/api/shell/wake") == 2
    assert idle.count("output * power on") == 3      # idle-resume, after-resume, unlock
    # the sway config must RESTART it, or a reload silently keeps the old daemon
    conf = session.sway_config_text(9111)
    assert "exec_always" in conf and str(session.IDLE_SCRIPT) in conf
    assert "pkill" in idle and idle.index("pkill") < idle.index("exec swayidle")


def test_the_idle_script_survives_an_apostrophe_in_the_wallpaper_path(home):
    """The reason swayidle lives in its own file: the lock command is already
    full of quotes, and nesting it inside sh -c '…' breaks on the first one."""
    import subprocess
    path = session.write_idle_script(9111, wallpaper="/home/a/Bob's photos/w.png")
    r = subprocess.run(["sh", "-n", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, f"generated idle script is not valid shell: {r.stderr}"


def test_alt_tab_is_a_mode_so_the_switcher_can_be_seen(home):
    """A single keypress can switch windows but never show anything: the shell
    sits behind the native windows. Holding Alt has to be a sway mode."""
    conf = session.sway_config_text(9111)
    assert 'mode "switcher"' in conf
    assert '"action":"open"' in conf and '"action":"step"' in conf
    assert '--release Alt_L mode "default"' in conf
    assert '"action":"commit"' in conf and '"action":"cancel"' in conf


def test_native_windows_have_title_bars_that_actually_do_something(home):
    """An app's own minimize button can never work (sway does not implement
    xdg_toplevel.set_minimized), but its title bar is ours to bind."""
    conf = session.sway_config_text(9111)
    assert "default_border normal" in conf and "default_floating_border normal" in conf
    assert "--border --release button3 move scratchpad" in conf   # minimize
    assert "--border --release button2 kill" in conf              # close


# ---------------------------------------------------------------------------
# The generated config must not outlive the build that generated it.
#
# SWAY_CONF is written by install-session and was never touched again, so a
# machine that installed the session months ago kept that month's window rules
# forever. Every fix since — title bars on native windows, Super-drag to move,
# Super+D for the desktop, the layering that stops apps opening under the shell
# — shipped in the template and never reached the disk. From the user's chair
# that is "AgentOS has no window controls and every app is stuck on top".
# ---------------------------------------------------------------------------

def test_a_config_from_an_older_build_is_detected_and_repaired(tmp_path, monkeypatch):
    from agentos import session as sess
    conf = tmp_path / "sway.conf"
    monkeypatch.setattr(sess, "SWAY_CONF", conf)

    current = sess.current_config_text()
    stale = "\n".join(l for l in current.splitlines()
                      if not l.startswith(("default_floating_border", "floating_modifier",
                                           "bindsym Mod4+d")))
    conf.write_text(stale)
    assert sess.config_is_stale() is True

    changed, _how = sess.refresh_config(reload_now=False)
    assert changed is True
    text = conf.read_text()
    for rule in ("default_floating_border normal 2",   # a title bar to grab
                 "floating_modifier Mod4",             # Super-drag to move
                 "bindsym Mod4+d"):                    # show the desktop
        assert rule in text, f"{rule!r} did not reach the installed config"
    assert sess.config_is_stale() is False


def test_a_current_config_is_left_alone(tmp_path, monkeypatch):
    from agentos import session as sess
    conf = tmp_path / "sway.conf"
    monkeypatch.setattr(sess, "SWAY_CONF", conf)
    conf.write_text(sess.current_config_text())
    assert sess.config_is_stale() is False
    changed, how = sess.refresh_config(reload_now=False)
    assert changed is False and how == "already current"


def test_nothing_happens_without_an_installed_session(tmp_path, monkeypatch):
    from agentos import session as sess
    monkeypatch.setattr(sess, "SWAY_CONF", tmp_path / "absent.conf")
    assert sess.config_is_stale() is False
    assert sess.refresh_config(reload_now=False) == (False, "no session config installed")


def test_the_shell_survives_a_reload():
    """refresh_config() reloads sway live. That is only safe because the shell is
    started with plain `exec` — `exec_always` would relaunch the desktop under
    the user every time an upgrade landed."""
    from agentos import session as sess
    text = sess.current_config_text()
    shell = next(l for l in text.splitlines() if sess.SHELL_SCRIPT.name in l)
    assert shell.startswith("exec "), shell
    assert not shell.startswith("exec_always"), "a reload would restart the desktop"
