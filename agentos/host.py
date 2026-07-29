"""Host desktop integration — the facade over the platform backends.

This module is the stable surface the rest of AgentOS calls: the REST endpoints
in server.py, the agent tools in tools.py, and the TUI. It keeps the function
names and return shapes it has always had, and delegates the actual work to
whichever backend fits the machine and run mode (see `agentos/platform/`):

    linux_hosted   AgentOS as a guest on GNOME/KDE/…   (the original behaviour)
    linux_de       AgentOS as the session               (compositor, our settings)
    macos          AgentOS as a Mac app
    windows        AgentOS as a Windows app

Adding a system control means implementing it on a backend, not editing this
file. Ask `capabilities()` before offering one in the UI — every backend answers
for every capability, and says why when it can't.
"""

from __future__ import annotations

from . import runmode
from .platform import caps, get_platform

# Kept for callers that predate the platform layer.
IS_MAC = runmode.IS_MAC
IS_WIN = runmode.IS_WIN


def _p():
    from .config import load_config
    try:
        cfg = load_config()
    except Exception:
        cfg = {}
    return get_platform(cfg)


# --- capabilities ----------------------------------------------------------

def capabilities() -> dict:
    """Capability id -> descriptor dict. The UI renders from this."""
    return {cid: c.as_dict() for cid, c in _p().capabilities().items()}


def can(cap_id: str) -> bool:
    return _p().can(cap_id)


def platform_state() -> dict:
    """Full platform + run mode description. Backs GET /api/platform."""
    from .config import load_config
    from .platform import describe
    try:
        cfg = load_config()
    except Exception:
        cfg = {}
    return describe(cfg)


# --- native applications ---------------------------------------------------

def list_apps() -> list[dict]:
    return _p().list_apps()


def resolve_icon(name: str) -> str | None:
    return _p().resolve_icon(name)


def launch_app(app_id: str) -> tuple[bool, str]:
    return _p().launch_app(app_id)


# --- system controls -------------------------------------------------------

def get_volume() -> dict:
    return _p().get_volume()


def set_volume(percent: int | None = None, mute: bool | None = None) -> bool:
    return _p().set_volume(percent=percent, mute=mute)


def get_battery() -> dict:
    return _p().get_battery()


def get_network() -> dict:
    return _p().get_network()


def open_settings(panel: str = "") -> tuple[bool, str]:
    return _p().open_settings(panel)


def control_state() -> dict:
    return _p().control_state()


# --- native window management ----------------------------------------------

def list_windows() -> dict:
    """Open windows on the host desktop, in whatever way this session allows."""
    return _p().list_windows()


def focus_window(win_id: str) -> tuple[bool, str]:
    return _p().focus_window(win_id)


def close_window(win_id: str) -> tuple[bool, str]:
    return _p().close_window(win_id)


def move_window_to_workspace(win_id: str, workspace: str) -> tuple[bool, str]:
    return _p().move_window_to_workspace(win_id, workspace)


def set_window_floating(win_id: str, floating: bool) -> tuple[bool, str]:
    return _p().set_window_floating(win_id, floating)


def minimize_window(win_id: str) -> tuple[bool, str]:
    return _p().minimize_window(win_id)


def restore_window(win_id: str) -> tuple[bool, str]:
    return _p().restore_window(win_id)


def maximize_window(win_id: str, on: bool = True) -> tuple[bool, str]:
    return _p().maximize_window(win_id, on)


def fullscreen_window(win_id: str, on: bool | None = None) -> tuple[bool, str]:
    return _p().fullscreen_window(win_id, on)


def show_desktop() -> tuple[bool, str]:
    return _p().show_desktop()


def raise_shell(on: bool = True) -> tuple[bool, str]:
    return _p().raise_shell(on)


def goto_desktop(n: int) -> tuple[bool, str]:
    return _p().goto_desktop(n)


def cycle_focus(direction: str = "next") -> tuple[bool, str]:
    return _p().cycle_focus(direction)


# --- workspaces & displays (compositor-backed; DE mode only) ----------------

def workspaces() -> dict:
    return _p().workspaces()


def switch_workspace(workspace: str) -> tuple[bool, str]:
    return _p().switch_workspace(workspace)


def outputs() -> dict:
    return _p().outputs()


def configure_output(name: str, **kw) -> tuple[bool, str]:
    return _p().configure_output(name, **kw)


__all__ = [
    "IS_MAC", "IS_WIN", "can", "capabilities", "close_window", "control_state",
    "caps", "focus_window", "get_battery", "get_network", "get_volume",
    "launch_app", "list_apps", "list_windows", "open_settings", "platform_state",
    "resolve_icon", "set_volume",
]
