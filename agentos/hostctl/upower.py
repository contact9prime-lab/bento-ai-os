"""UPower: battery state. net.hadess.PowerProfiles: performance modes.

UPower's DisplayDevice is the composite "what the battery icon should show"
object, so one read covers laptops with several batteries. Power profiles come
from power-profiles-daemon, which desktop Ubuntu ships but servers don't —
that's a capability with a component to offer, not an error.
"""

from __future__ import annotations

import shutil

from dbus_fast.errors import DBusError

from . import HostCtlError, interface

UPOWER = "org.freedesktop.UPower"
DISPLAY_DEVICE = "/org/freedesktop/UPower/devices/DisplayDevice"
DEVICE_IFACE = "org.freedesktop.UPower.Device"

PROFILES = "net.hadess.PowerProfiles"
PROFILES_PATH = "/net/hadess/PowerProfiles"

# UPower state enum → the words the UI shows
_STATES = {1: "charging", 2: "discharging", 3: "empty", 4: "fully charged",
           5: "pending charge", 6: "pending discharge"}


def available() -> tuple[bool, str]:
    if not shutil.which("upowerd") and not shutil.which("upower"):
        return False, "upower is not installed."
    return True, ""


def profiles_available() -> tuple[bool, str, str]:
    if not shutil.which("powerprofilesctl"):
        return (False, "Power profiles need power-profiles-daemon.",
                "power-profiles-daemon")
    return True, "", ""


async def battery() -> dict:
    try:
        dev = await interface(UPOWER, DISPLAY_DEVICE, DEVICE_IFACE)
        if not await dev.get_is_present():
            return {}
        return {
            "percent": round(await dev.get_percentage()),
            "state": _STATES.get(await dev.get_state(), ""),
            "time_to_empty": await dev.get_time_to_empty(),   # seconds, 0 = unknown
            "time_to_full": await dev.get_time_to_full(),
        }
    except (HostCtlError, DBusError):
        return {}          # same contract as host.get_battery(): {} means "no battery info"


async def get_profile() -> dict:
    try:
        p = await interface(PROFILES, PROFILES_PATH, PROFILES)
        return {"active": await p.get_active_profile(),
                "profiles": [d["Profile"].value for d in await p.get_profiles()]}
    except (HostCtlError, DBusError) as e:
        raise HostCtlError(f"power profiles unavailable: {e}") from e


async def set_profile(profile: str) -> None:
    try:
        p = await interface(PROFILES, PROFILES_PATH, PROFILES)
        await p.set_active_profile(profile)
    except (HostCtlError, DBusError) as e:
        raise HostCtlError(f"could not set power profile '{profile}': {e}") from e
