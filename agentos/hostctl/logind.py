"""systemd-logind: session lock, power actions, and the brightness write path.

logind is the one daemon guaranteed on every systemd machine, and it grants the
active session's user these calls without root — which is exactly what a
desktop needs: lock and suspend must work with no sudo and no polkit prompt.
"""

from __future__ import annotations

from pathlib import Path

from dbus_fast.errors import DBusError

from . import HostCtlError, interface

SERVICE = "org.freedesktop.login1"
MANAGER_PATH = "/org/freedesktop/login1"
MANAGER_IFACE = "org.freedesktop.login1.Manager"
# "auto" resolves to the caller's own session — no session id bookkeeping.
SESSION_PATH = "/org/freedesktop/login1/session/auto"
SESSION_IFACE = "org.freedesktop.login1.Session"


def available() -> tuple[bool, str]:
    if not Path("/run/systemd/system").exists():
        return False, "This system is not running systemd."
    return True, ""


async def _manager():
    return await interface(SERVICE, MANAGER_PATH, MANAGER_IFACE)


async def _session():
    return await interface(SERVICE, SESSION_PATH, SESSION_IFACE)


async def lock() -> None:
    try:
        await (await _session()).call_lock()
    except DBusError as e:
        raise HostCtlError(f"could not lock the session: {e.text}") from e


async def power(action: str) -> None:
    """suspend | restart | poweroff — non-interactive, current session's rights."""
    calls = {"suspend": "call_suspend", "restart": "call_reboot",
             "poweroff": "call_power_off"}
    if action not in calls:
        raise HostCtlError(f"unknown power action '{action}'")
    mgr = await _manager()
    try:
        await getattr(mgr, calls[action])(False)   # interactive=False: no auth prompt
    except DBusError as e:
        raise HostCtlError(f"could not {action}: {e.text}") from e


async def set_brightness(subsystem: str, name: str, value: int) -> None:
    """logind writes /sys/class/<subsystem>/<name>/brightness on our behalf —
    this is how an unprivileged session sets backlight brightness."""
    try:
        await (await _session()).call_set_brightness(subsystem, name, max(0, int(value)))
    except DBusError as e:
        raise HostCtlError(f"could not set brightness on {name}: {e.text}") from e
