"""Brightness: sysfs backlights via logind, external monitors via ddcutil.

Two very different worlds behind one control:

  * Internal panels appear in /sys/class/backlight. Reading is plain sysfs;
    writing goes through logind's SetBrightness, which is the sanctioned way
    for an unprivileged session to set it.
  * Desktop monitors have no backlight device — their brightness lives in the
    monitor itself, spoken to over DDC/CI. That needs ddcutil (GPL-2), which we
    do not ship; it's an optional component the UI can offer to install.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import HostCtlError
from . import logind

BACKLIGHT_DIR = Path("/sys/class/backlight")


def available() -> tuple[bool, str, str]:
    if BACKLIGHT_DIR.exists() and any(BACKLIGHT_DIR.iterdir()):
        return True, "", ""
    if shutil.which("ddcutil"):
        return True, "", ""
    return (False,
            "No internal backlight, and controlling external monitors needs ddcutil.",
            "ddcutil")


def backlights() -> list[dict]:
    """Internal panels from sysfs, brightness as 0-100."""
    out = []
    if not BACKLIGHT_DIR.exists():
        return out
    for dev in sorted(BACKLIGHT_DIR.iterdir()):
        try:
            maximum = int((dev / "max_brightness").read_text())
            current = int((dev / "brightness").read_text())
        except (OSError, ValueError):
            continue
        if maximum <= 0:
            continue
        out.append({"kind": "backlight", "name": dev.name,
                    "percent": round(current * 100 / maximum), "max": maximum})
    return out


async def set_backlight(name: str, percent: int) -> None:
    devs = {d["name"]: d for d in backlights()}
    if name not in devs:
        raise HostCtlError(f"no backlight device '{name}'")
    raw = round(max(0, min(100, int(percent))) * devs[name]["max"] / 100)
    await logind.set_brightness("backlight", name, raw)


# --- external monitors (DDC/CI) ---------------------------------------------

def ddc_displays() -> list[dict]:
    """External monitors via ddcutil, brightness as 0-100. Empty if not installed."""
    if not shutil.which("ddcutil"):
        return []
    out = []
    try:
        detect = subprocess.run(["ddcutil", "detect", "--terse"], capture_output=True,
                                text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    for block in detect.split("\n\n"):
        if not block.strip().startswith("Display"):
            continue
        num = block.strip().split()[1]
        monitor = next((ln.split(":", 1)[1].strip() for ln in block.splitlines()
                        if ln.strip().startswith("Monitor:")), f"Display {num}")
        row = {"kind": "ddc", "name": num, "monitor": monitor, "percent": None}
        try:
            # VCP feature 0x10 = luminance; terse output: "VCP 10 C <cur> <max>"
            vcp = subprocess.run(["ddcutil", "-d", num, "getvcp", "10", "--terse"],
                                 capture_output=True, text=True, timeout=15).stdout.split()
            if len(vcp) >= 5 and int(vcp[4]) > 0:
                row["percent"] = round(int(vcp[3]) * 100 / int(vcp[4]))
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
            pass
        out.append(row)
    return out


def set_ddc(display_num: str, percent: int) -> None:
    if not shutil.which("ddcutil"):
        raise HostCtlError("ddcutil is not installed.")
    try:
        r = subprocess.run(["ddcutil", "-d", str(int(display_num)), "setvcp", "10",
                            str(max(0, min(100, int(percent))))],
                           capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            raise HostCtlError((r.stderr or r.stdout).strip() or "ddcutil failed")
    except (OSError, subprocess.TimeoutExpired) as e:
        raise HostCtlError(f"ddcutil: {e}") from e


async def state() -> dict:
    """Everything adjustable, internal and external, one list."""
    displays = backlights() + ddc_displays()
    ok, reason, component = available()
    return {"available": ok and bool(displays) or bool(displays),
            "displays": displays,
            "reason": "" if displays else reason,
            "component": "" if displays else component}


async def set_level(name: str, percent: int, kind: str = "") -> None:
    if kind == "ddc" or (not kind and str(name).isdigit()):
        set_ddc(name, percent)
    else:
        await set_backlight(name, percent)
