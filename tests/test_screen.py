"""Bento on this machine's own screen at start (agentos/screen.py).

Asked for as "when the Pi has been installed, by default when it loads it opens up Bento in the
client mode with the office, so we can hook it to a screen and start talking to it". The kiosk
page existed; nothing drew it on a Pi's screen at boot. Checked live with the real cage
(headless) and Chromium: `bento screen run` waited for the server, then the Office kiosk filled
the screen (docs/screenshots/screen-kiosk.png).
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import remoteinstall, screen, sdcard   # noqa: E402

ROOT = Path(__file__).parent.parent


def test_the_unit_draws_the_screen_with_no_shell_logged_in():
    u = screen.unit_text({"port": 8321}, user="ada", python="/opt/bento/py", cage="/usr/bin/cage")
    assert "User=ada" in u and "PAMName=bento-screen" in u and "TTYPath=/dev/tty1" in u
    assert "Conflicts=getty@tty1.service" in u
    assert "ExecStartPre=/opt/bento/py -m agentos screen wait" in u
    assert "ExecStart=/usr/bin/cage -s -- /opt/bento/py -m agentos screen run" in u
    assert "Restart=always" in u and "WantedBy=multi-user.target" in u
    assert "autologin" not in u, "a keyboard plugged into the Pi must never reach a shell"
    assert "pam_systemd.so" in screen.PAM_TEXT


def test_the_unit_carries_a_home_that_is_not_the_default(monkeypatch):
    monkeypatch.setenv("AGENTOS_HOME", "/data/bento")
    assert "Environment=AGENTOS_HOME=/data/bento" in screen.unit_text({}, user="ada", python="p", cage="c")


def test_the_browser_shows_the_kiosk_and_nothing_answers_the_mic_for_other_pages(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    a = screen.run_argv({"port": 8400}, exe="/usr/bin/chromium", profile=str(tmp_path / "p"))
    assert a[0] == "/usr/bin/chromium" and "--kiosk" in a and a[-1] == "http://127.0.0.1:8400/#kiosk"
    assert "--autoplay-policy=no-user-gesture-required" in a, "the answer is spoken without a tap"
    assert not any("fake-ui-for-media" in x for x in a), "never a yes to every page's mic"
    assert "--no-sandbox" not in a
    import json
    pol = json.loads(screen.policy_text({"port": 8400}))
    assert pol["AudioCaptureAllowedUrls"] == ["http://127.0.0.1:8400"]


def test_screens_are_read_from_the_kernel(monkeypatch, tmp_path):
    for name, st in (("card1-HDMI-A-1", "connected"), ("card1-HDMI-A-2", "disconnected"), ("card1-DSI-1", "connected")):
        (tmp_path / name).mkdir()
        (tmp_path / name / "status").write_text(st + "\n")
    monkeypatch.setattr(screen, "DRM", tmp_path)
    assert screen.screens() == ["DSI-1", "HDMI-A-1"] and screen.has_drm()


def test_wait_holds_until_a_screen_and_the_server(monkeypatch, tmp_path):
    (tmp_path / "card1-HDMI-A-1").mkdir()
    st = tmp_path / "card1-HDMI-A-1" / "status"
    st.write_text("disconnected\n")
    monkeypatch.setattr(screen, "DRM", tmp_path)
    up = {"n": 0}
    monkeypatch.setattr(screen, "_server_up", lambda cfg=None: up["n"] >= 2)

    def sleep(_s):
        up["n"] += 1
        if up["n"] == 3:
            st.write_text("connected\n")
    assert screen.wait({}, sleep=sleep) and up["n"] == 3


def _console(monkeypatch, cage=False, browser=False):
    monkeypatch.setattr(screen, "road", lambda: ("console", "no desktop"))
    monkeypatch.setattr(screen, "_cage", lambda: "/usr/bin/cage" if cage else "")
    monkeypatch.setattr(screen, "browser", lambda: "/usr/bin/chromium" if browser else "")


def test_the_plan_on_a_machine_with_no_desktop(monkeypatch):
    _console(monkeypatch)
    ids = [s["id"] for s in screen.plan({"port": 8321})]
    assert ids == ["install-cage", "install-chromium", "mic", "pam", "unit"]
    steps = {s["id"]: s for s in screen.plan({"port": 8321})}
    assert "MIT" in steps["install-cage"]["why"] and "cage" in steps["install-cage"]["runs"]
    assert "Ctrl+Alt+F2" in steps["unit"]["why"]
    _console(monkeypatch, cage=True, browser=True)
    assert [s["id"] for s in screen.plan({})] == ["mic", "pam", "unit"]


def test_the_plan_on_a_desktop_changes_nothing_system_wide_but_the_mic(monkeypatch):
    monkeypatch.setattr(screen, "road", lambda: ("desktop", "lightdm"))
    monkeypatch.setattr(screen, "browser", lambda: "/usr/bin/chromium")
    steps = screen.plan({})
    assert [s["id"] for s in steps] == ["autostart", "mic"], "the window first: it needs no root"
    assert [s["root"] for s in steps] == [False, True]


def test_a_desktop_whose_sudo_wants_a_password_still_opens_on_its_screen(monkeypatch, tmp_path):
    """Found on a Pi 3 B+ installed from the hub: the mic policy needed root, sudo asked for a
    password, and the step stopped before the autostart, so the screen never showed Bento."""
    from agentos import desktop
    monkeypatch.setattr(screen, "road", lambda: ("desktop", "lightdm"))
    monkeypatch.setattr(screen, "browser", lambda: "/usr/bin/chromium")
    monkeypatch.setattr(screen, "AUTOSTART", tmp_path / "autostart" / "bento-screen.desktop")
    monkeypatch.setattr(desktop, "AUTOSTART_FILE", tmp_path / "autostart" / "agentos-app.desktop")
    monkeypatch.setattr(screen, "_root_write", lambda *a, **k: (False, "a password is required"))
    got = screen.enable({}, say=lambda _l: None)
    assert got["ok"] and got["done"] == ["autostart"] and screen.AUTOSTART.exists()
    assert "microphone" in got["mic"] and any(c.startswith("bento screen on") for c in got["needs"])


def test_the_screen_draws_on_the_desktops_wayland_when_it_has_one(monkeypatch, tmp_path):
    """The hint "auto" chose X11 on labwc and Chromium exited: "Missing X server"."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert "--ozone-platform-hint=auto" in screen.run_argv({}, exe="chromium", profile="p")
    (tmp_path / "wayland-0").touch()
    argv = screen.run_argv({}, exe="chromium", profile="p")
    assert "--ozone-platform=wayland" in argv and "--ozone-platform-hint=auto" not in argv


def test_no_root_hands_the_commands_back_and_writes_nothing(monkeypatch, tmp_path):
    _console(monkeypatch, cage=True, browser=True)
    monkeypatch.setattr(screen, "_root_write", lambda *a, **k: (False, "a password is required"))
    got = screen.enable({}, say=lambda _l: None)
    assert not got["ok"] and got["done"] == []
    assert any(c.startswith("bento screen on") for c in got["needs"]), "asks at a terminal, never as root"
    assert not any(c.startswith("sudo bento") or "sudo " + sys.executable in c for c in got["needs"])


def test_a_desktop_gets_one_window_at_login_and_off_puts_it_back(monkeypatch, tmp_path):
    from agentos import desktop
    monkeypatch.setattr(screen, "road", lambda: ("desktop", "lightdm"))
    monkeypatch.setattr(screen, "browser", lambda: "/usr/bin/chromium")
    monkeypatch.setattr(screen, "AUTOSTART", tmp_path / "autostart" / "bento-screen.desktop")
    monkeypatch.setattr(screen, "UNIT", tmp_path / "none.service")
    monkeypatch.setattr(screen, "PAM", tmp_path / "none.pam")
    monkeypatch.setattr(desktop, "AUTOSTART_FILE", tmp_path / "autostart" / "agentos-app.desktop")
    desktop.AUTOSTART_FILE.parent.mkdir(parents=True)
    desktop.AUTOSTART_FILE.write_text("[Desktop Entry]\nExec=bento app\n")
    wrote = []
    monkeypatch.setattr(screen, "_root_write", lambda path, text, why: (wrote.append(path), (True, ""))[1])
    got = screen.enable({"port": 8321}, say=lambda _l: None)
    assert got["ok"] and got["done"] == ["autostart", "mic"] and not got.get("mic")
    assert "-m agentos screen run" in screen.AUTOSTART.read_text()
    assert not desktop.AUTOSTART_FILE.exists(), "the app's own login window would be a second one"
    assert all(p.name == screen.POLICY_NAME for p in wrote)
    monkeypatch.setattr(screen, "POLICY_DIRS", ())
    off = screen.disable({}, say=lambda _l: None)
    assert off["ok"] and not screen.AUTOSTART.exists() and desktop.AUTOSTART_FILE.exists()


def test_not_linux_is_a_sentence(monkeypatch):
    monkeypatch.setattr(screen, "_linux", lambda: False)
    assert screen.road()[0] == "" and "Linux" in screen.road()[1]
    assert screen.plan({}) == []


# ---- reaching it from the hub's Install form, the SD card and the terminal -------------------

def test_the_install_command_shows_screen_when_asked(monkeypatch):
    monkeypatch.setenv("AGENTOS_INSTALL_URL", "https://example.test/install.sh")
    monkeypatch.delenv("AGENTOS_REPO", raising=False)
    assert remoteinstall.plan({}, "bento-enroll-1.x", screen=True).endswith(" --screen")
    assert "--screen" not in remoteinstall.plan({}, "bento-enroll-1.x")
    cmd = sdcard.first_boot_command("https://example.test/install.sh", "ada", "bento-enroll-1.x", screen=True)
    assert "--enroll=bento-enroll-1.x --screen" in cmd[-1]
    assert "--screen" not in sdcard.first_boot_command("https://example.test/install.sh", "ada", "k")[-1]


def test_install_sh_takes_screen_and_runs_the_one_verb():
    sh = (ROOT / "install.sh").read_text()
    assert "--screen) SCREEN=1 ;;" in sh and "uv run bento screen on --yes" in sh
    r = subprocess.run(["sh", str(ROOT / "install.sh"), "--help"], capture_output=True, text=True, timeout=20)
    assert "--screen" in r.stdout and "--no-verify" in r.stdout


def test_the_form_opens_on_its_screen_by_default_and_the_shown_command_follows_the_switch():
    js = (ROOT / "agentos/ui/src/js/24j-provision.js").read_text()
    assert "pSwitch('dev-kiosk',true)} Open on its screen" in js
    assert "pSwitch('card-kiosk',true)} Open on its screen" in js
    net = (ROOT / "agentos/ui/src/js/24n-network.js").read_text()
    assert "'dev-auth','dev-kiosk'" in net, "a repaint keeps the switch as it was set"
    assert "replace(/ --screen$/,'')" in net
    src = (ROOT / "agentos/server.py").read_text()
    route = src[src.index('@app.post("/api/screen")'):]
    route = route[:route.index("\n@app.")]
    assert "_require_admin()" in route and "screen.on" in route and "screen.off" in route
    assert "screen=_wants_screen(b)" in src


def test_the_terminal_verb():
    r = subprocess.run([sys.executable, "-m", "agentos", "screen", "--help"], cwd=ROOT,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "status | on | off" in r.stdout


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the screen is a Linux machine's")
def test_status_is_measured_and_says_one_sentence():
    st = screen.status({"port": 8321})
    assert set(st) >= {"on", "road", "why", "screens", "missing", "words", "url"}
    assert st["url"] == "http://127.0.0.1:8321/#kiosk" and st["words"]


# ---- what you call it: "Chef", "Fridge" ---------------------------------------------------------

def test_the_name_given_at_install_is_what_wakes_it():
    """Asked for as "we should be able to name the agent so I can say chef, fridge". The name
    rides the machine's enrolment profile, becomes its agent_name when it is set up, and the
    agent's name is always a wake word on its screen."""
    from agentos import face, provision
    prof = provision.clean_profile({"agent_name": "  Chef\x1b[31m ", "kiosk": True, "lite": True})
    assert prof["agent_name"].startswith("Chef") and "\x1b" not in prof["agent_name"]
    words = face.wake_words({"agent_name": "Fridge"})
    assert "Fridge" in words
    assert face.addressed("Fridge, what can I make tonight?", words) == ("Fridge", "what can I make tonight?")
    js = (ROOT / "agentos/ui/src/js/24j-provision.js").read_text()
    assert 'id="dev-agent"' in js and 'id="card-agent"' in js and "agent_name:agent" in js
    assert "'dev-agent'" in (ROOT / "agentos/ui/src/js/24n-network.js").read_text()
