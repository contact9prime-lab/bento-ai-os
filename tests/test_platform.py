"""The platform contract.

These tests exist to protect one promise: the UI is written once, against
capabilities, and every backend answers for every capability without raising.
A backend that forgets a capability, or reports one unavailable without saying
why, breaks that promise silently — the control just disappears from the UI with
no explanation. So the contract is checked here rather than discovered later on
someone's Mac.
"""

import os
from unittest import mock

import pytest

from agentos import runmode
from agentos.platform import caps as C
from agentos.platform.base import Capability, Platform
from agentos.platform.linux_de import LinuxDE
from agentos.platform.linux_hosted import LinuxHosted
from agentos.platform.macos import MacOS
from agentos.platform.windows import Windows

BACKENDS = [Platform, LinuxHosted, LinuxDE, MacOS, Windows]


@pytest.fixture(params=BACKENDS, ids=lambda b: b.__name__)
def backend(request):
    return request.param()


def test_every_backend_answers_for_every_capability(backend):
    got = backend.capabilities()
    assert set(got) == set(C.ALL), (
        f"{type(backend).__name__} capability set drifted from caps.ALL")


def test_unavailable_capabilities_always_explain_themselves(backend):
    """No silent dead controls: if it isn't available, the user gets a sentence."""
    for cid, cap in backend.capabilities().items():
        if not cap.available:
            assert cap.reason.strip(), f"{type(backend).__name__}.{cid} is unavailable with no reason"
            assert not cap.reason.lower().startswith("not implemented"), (
                f"{type(backend).__name__}.{cid} leaks an implementation detail to the user")


def test_available_implies_supported(backend):
    for cid, cap in backend.capabilities().items():
        if cap.available:
            assert cap.supported, f"{cid} is available but not supported — contradictory"


def test_no_method_raises_on_the_base_platform():
    """The default backend knows nothing and must still break nothing."""
    p = Platform()
    assert p.list_apps() == []
    assert p.resolve_icon("firefox") is None
    assert p.launch_app("firefox")[0] is False
    assert p.get_volume() == {"volume": None, "muted": False}
    assert p.set_volume(percent=50) is False
    assert p.get_battery() == {}
    assert p.get_network() == {}
    assert p.open_settings("wifi")[0] is False
    assert p.list_windows()["available"] is False
    assert p.focus_window("0x1")[0] is False
    assert p.close_window("0x1")[0] is False
    assert "audio" in p.control_state()


def test_capability_dicts_carry_what_the_ui_needs(backend):
    for cid, cap in backend.capabilities().items():
        d = cap.as_dict()
        assert d["id"] == cid
        assert d["title"], f"{cid} has no human title in caps.CAPS"
        # An unavailable capability tells the user what they lose because of it.
        if not d["available"]:
            assert d["impact"], f"{cid} has no impact sentence"


def test_de_mode_never_hands_off_to_gnome():
    """When AgentOS is the desktop there is no other settings app to open."""
    de = LinuxDE()
    ok, msg = de.open_settings("wifi")
    assert ok is False
    assert "gnome" not in msg.lower()
    assert de.capabilities()[C.SETTINGS_OPEN].available is False


def test_de_inherits_shared_behaviour_from_hosted():
    """App listing and volume are the same job whoever owns the session."""
    assert LinuxDE.list_apps is LinuxHosted.list_apps
    assert LinuxDE.get_volume is LinuxHosted.get_volume


def test_de_launches_apps_through_the_compositor():
    """Spawned from systemd, the server has no Wayland display of its own — so in
    DE mode a launch has to go through sway, or the app starts and dies unseen."""
    assert LinuxDE.launch_app is not LinuxHosted.launch_app
    de = LinuxDE()
    assert de.launch_app("evil; rm -rf /") == (False, "invalid app id")

    calls: list[str] = []
    from agentos import compositor as comp
    with mock.patch.object(comp, "available", lambda: True), \
         mock.patch("shutil.which", lambda n: "/usr/bin/" + n if n == "gtk-launch" else None), \
         mock.patch.object(comp.Compositor, "exec", lambda self, cmd: calls.append(cmd)):
        launched, _ = de.launch_app("firefox")
    assert launched is True
    assert calls == ["gtk-launch 'firefox'"]


def test_hosted_never_claims_the_notification_bus():
    """Claiming org.freedesktop.Notifications as a guest would break the host DE."""
    assert LinuxHosted().capabilities()[C.NOTIFY_DAEMON].available is False


# --- run mode detection ----------------------------------------------------

def test_detect_hosted_without_session_marker(monkeypatch):
    monkeypatch.delenv("AGENTOS_SESSION", raising=False)
    monkeypatch.delenv("SWAYSOCK", raising=False)
    monkeypatch.setattr(runmode, "IS_LINUX", True)
    assert runmode.detect() == runmode.HOSTED


def test_detect_de_only_with_a_live_compositor(monkeypatch):
    monkeypatch.setattr(runmode, "IS_LINUX", True)
    monkeypatch.setenv("AGENTOS_SESSION", "1")
    monkeypatch.setenv("SWAYSOCK", "/run/user/1000/sway-ipc.sock")
    assert runmode.detect() == runmode.DE
    # Session started, but no Wayland compositor -> the older X11 kiosk.
    monkeypatch.delenv("SWAYSOCK")
    assert runmode.detect() == runmode.KIOSK


def test_installed_but_not_booted_into_is_still_hosted(monkeypatch):
    """Having the AgentOS session installed must not change how we behave today."""
    monkeypatch.setattr(runmode, "IS_LINUX", True)
    monkeypatch.delenv("AGENTOS_SESSION", raising=False)
    monkeypatch.setenv("SWAYSOCK", "/run/user/1000/sway-ipc.sock")  # e.g. nested sway
    assert runmode.detect() == runmode.HOSTED


def test_pinned_mode_overrides_detection(monkeypatch):
    monkeypatch.setattr(runmode, "IS_LINUX", True)
    monkeypatch.delenv("AGENTOS_SESSION", raising=False)
    effective, detected = runmode.resolve({"desktop": {"mode": "de"}})
    assert (effective, detected) == (runmode.DE, runmode.HOSTED)


def test_auto_follows_detection(monkeypatch):
    monkeypatch.setattr(runmode, "IS_LINUX", True)
    monkeypatch.delenv("AGENTOS_SESSION", raising=False)
    effective, detected = runmode.resolve({"desktop": {"mode": "auto"}})
    assert effective == detected == runmode.HOSTED


def test_missing_config_key_defaults_to_auto(monkeypatch):
    monkeypatch.setattr(runmode, "IS_LINUX", True)
    monkeypatch.delenv("AGENTOS_SESSION", raising=False)
    assert runmode.resolve({})[0] == runmode.HOSTED
    assert runmode.resolve(None)[0] == runmode.HOSTED


def test_session_modes_cannot_be_forced_onto_non_linux(monkeypatch):
    """Pinning `de` on a Mac must not produce a desktop that cannot exist."""
    monkeypatch.setattr(runmode, "IS_LINUX", False)
    effective, _ = runmode.resolve({"desktop": {"mode": "de"}})
    assert effective == runmode.HOSTED


# --- the facade ------------------------------------------------------------

def test_host_facade_keeps_its_public_surface():
    """server.py, tools.py and the TUI call these by name — they must not move."""
    from agentos import host
    for fn in ("list_apps", "resolve_icon", "launch_app", "get_volume", "set_volume",
               "get_battery", "get_network", "open_settings", "control_state",
               "list_windows", "focus_window", "close_window"):
        assert callable(getattr(host, fn)), f"host.{fn} disappeared"


def test_platform_state_shape():
    from agentos import host
    st = host.platform_state()
    for key in ("platform", "mode", "detected_mode", "capabilities", "summary", "modes"):
        assert key in st
    assert set(st["capabilities"]) == set(C.ALL)


def test_list_windows_shape_is_stable_across_backends(backend):
    """The taskbar reads this shape on every platform."""
    w = backend.list_windows()
    assert set(w) >= {"available", "windows"}
    assert isinstance(w["windows"], list)
    if not w["available"]:
        assert w.get("reason", "").strip(), "an unavailable window list must say why"


def test_mode_respects_a_pinned_desktop_mode(monkeypatch):
    """Three endpoints ask runmode.mode() before touching the session; if it
    ignored config, pinning `desktop.mode` would silently do nothing."""
    from agentos import config as cfgmod
    monkeypatch.setattr(runmode, "IS_LINUX", True)
    monkeypatch.delenv("AGENTOS_SESSION", raising=False)
    monkeypatch.setattr(cfgmod, "load_config", lambda: {"desktop": {"mode": "de"}})
    assert runmode.mode() == runmode.DE
    monkeypatch.setattr(cfgmod, "load_config", lambda: {})
    assert runmode.mode() == runmode.HOSTED


def test_mode_survives_an_unreadable_config(monkeypatch):
    from agentos import config as cfgmod
    monkeypatch.setattr(runmode, "IS_LINUX", True)
    monkeypatch.delenv("AGENTOS_SESSION", raising=False)
    monkeypatch.setattr(cfgmod, "load_config", lambda: (_ for _ in ()).throw(OSError("gone")))
    assert runmode.mode() == runmode.HOSTED
