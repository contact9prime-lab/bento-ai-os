"""System control backends for the AgentOS desktop — D-Bus, not shell-outs.

In DE mode AgentOS is the desktop, so wifi, bluetooth, brightness, battery and
power profiles must be first-class controls, not hand-offs to gnome-control-
center. Each module here speaks to the standard Linux system daemon over D-Bus
(dbus-fast, MIT):

    logind.py      org.freedesktop.login1      lock, suspend/reboot/poweroff, brightness
    upower.py      org.freedesktop.UPower      battery      (+ net.hadess power profiles)
    network.py     org.freedesktop.NetworkManager   wifi scan/join/forget, airplane
    bluetooth.py   org.bluez                   power, discovery, pair/connect/remove
    audio.py       PipeWire (pw-dump/wpctl)    devices, default sink, per-app volume
    brightness.py  sysfs + logind (+ ddcutil)  backlight and external monitors

The daemons are GPL; that is fine — they are separate programs shipped by the
distro, and D-Bus is an interface, not linkage. AgentOS never bundles them
(see packaging/audit-licenses.sh).

Every public entry point returns data or raises HostCtlError with a sentence a
user can act on. Nothing here assumes a daemon exists: `available()` on each
module is the cheap synchronous check the capability probe uses, and the async
calls translate D-Bus failures into HostCtlError.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from dbus_fast import BusType
from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusError


class HostCtlError(Exception):
    """A control failed, with a user-facing sentence."""


_buses: dict[BusType, MessageBus] = {}
_bus_locks: dict[BusType, asyncio.Lock] = {}


def system_bus_present() -> bool:
    return Path("/run/dbus/system_bus_socket").exists()


async def get_bus(bus_type: BusType = BusType.SYSTEM) -> MessageBus:
    """One shared connection per bus, created lazily and replaced if it drops."""
    lock = _bus_locks.setdefault(bus_type, asyncio.Lock())
    async with lock:
        bus = _buses.get(bus_type)
        if bus is not None and bus.connected:
            return bus
        try:
            bus = await MessageBus(bus_type=bus_type).connect()
        except Exception as e:
            raise HostCtlError(f"cannot reach the {bus_type.name.lower()} D-Bus: {e}") from e
        _buses[bus_type] = bus
        return bus


async def proxy(service: str, path: str, bus_type: BusType = BusType.SYSTEM):
    """Introspected proxy object, or HostCtlError naming the missing daemon."""
    bus = await get_bus(bus_type)
    try:
        intro = await asyncio.wait_for(bus.introspect(service, path), timeout=10)
    except (DBusError, asyncio.TimeoutError) as e:
        raise HostCtlError(f"{service} is not answering: {e}") from e
    return bus.get_proxy_object(service, path, intro)


async def interface(service: str, path: str, iface: str,
                    bus_type: BusType = BusType.SYSTEM):
    obj = await proxy(service, path, bus_type)
    try:
        return obj.get_interface(iface)
    except Exception as e:
        raise HostCtlError(f"{service} does not provide {iface}: {e}") from e
