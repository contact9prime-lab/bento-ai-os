"""BlueZ over D-Bus: adapter power, discovery, pairing, connecting.

BlueZ exposes everything through one ObjectManager tree — adapters are
org.bluez.Adapter1 nodes, devices org.bluez.Device1, and a device's battery (if
it reports one) org.bluez.Battery1 on the same path. One GetManagedObjects call
paints the whole panel.

Pairing note: Pair() succeeds unprompted for "just works" devices (headphones,
mice, speakers — the overwhelming case). Devices demanding a PIN confirmation
need a pairing agent, which is a later addition; until then the error from
BlueZ is surfaced as-is.
"""

from __future__ import annotations

from pathlib import Path

from dbus_fast.errors import DBusError

from . import HostCtlError, interface, proxy

BLUEZ = "org.bluez"
OM_IFACE = "org.freedesktop.DBus.ObjectManager"
ADAPTER_IFACE = "org.bluez.Adapter1"
DEVICE_IFACE = "org.bluez.Device1"
BATTERY_IFACE = "org.bluez.Battery1"


def available() -> tuple[bool, str, str]:
    bt_class = Path("/sys/class/bluetooth")
    if not bt_class.exists() or not any(bt_class.iterdir()):
        return False, "No bluetooth adapter found on this machine.", ""
    return True, "", ""


def parse_tree(objects: dict) -> dict:
    """GetManagedObjects → {adapters: [...], devices: [...]}. Pure, testable."""
    adapters, devices = [], []
    for path, ifaces in objects.items():
        if ADAPTER_IFACE in ifaces:
            a = ifaces[ADAPTER_IFACE]
            adapters.append({
                "path": path,
                "name": _v(a.get("Alias")) or _v(a.get("Name")) or "",
                "address": _v(a.get("Address")) or "",
                "powered": bool(_v(a.get("Powered"))),
                "discovering": bool(_v(a.get("Discovering"))),
            })
        if DEVICE_IFACE in ifaces:
            d = ifaces[DEVICE_IFACE]
            dev = {
                "path": path,
                "name": _v(d.get("Alias")) or _v(d.get("Name")) or _v(d.get("Address")) or "",
                "address": _v(d.get("Address")) or "",
                "paired": bool(_v(d.get("Paired"))),
                "connected": bool(_v(d.get("Connected"))),
                "trusted": bool(_v(d.get("Trusted"))),
                "icon": _v(d.get("Icon")) or "",
                "rssi": _v(d.get("RSSI")),
            }
            if BATTERY_IFACE in ifaces:
                dev["battery"] = _v(ifaces[BATTERY_IFACE].get("Percentage"))
            devices.append(dev)
    devices.sort(key=lambda d: (not d["connected"], not d["paired"], d["name"].lower()))
    return {"adapters": adapters, "devices": devices}


def _v(x):
    return getattr(x, "value", x)


async def tree() -> dict:
    try:
        om = await interface(BLUEZ, "/", OM_IFACE)
        return parse_tree(await om.call_get_managed_objects())
    except (HostCtlError, DBusError) as e:
        raise HostCtlError(f"bluetooth unavailable: {e}") from e


def _checked_path(path: str) -> str:
    if not str(path).startswith("/org/bluez/"):
        raise HostCtlError("invalid bluetooth device path")
    return str(path)


async def set_powered(adapter_path: str, powered: bool) -> None:
    try:
        a = await interface(BLUEZ, _checked_path(adapter_path), ADAPTER_IFACE)
        await a.set_powered(bool(powered))
    except DBusError as e:
        raise HostCtlError(f"could not switch bluetooth: {e.text}") from e


async def set_discovering(adapter_path: str, on: bool) -> None:
    try:
        a = await interface(BLUEZ, _checked_path(adapter_path), ADAPTER_IFACE)
        await (a.call_start_discovery() if on else a.call_stop_discovery())
    except DBusError as e:
        # Already started/stopped is not a failure worth surfacing.
        if "InProgress" not in (e.type or "") and "NotReady" not in (e.type or ""):
            raise HostCtlError(f"could not change discovery: {e.text}") from e


async def device_action(device_path: str, action: str) -> None:
    """pair | connect | disconnect | trust | untrust | remove."""
    path = _checked_path(device_path)
    try:
        if action == "remove":
            adapter_path = path.rsplit("/", 1)[0]
            a = await interface(BLUEZ, adapter_path, ADAPTER_IFACE)
            await a.call_remove_device(path)
            return
        d = await interface(BLUEZ, path, DEVICE_IFACE)
        if action == "pair":
            await d.call_pair()
            await d.set_trusted(True)     # paired from our own UI ⇒ auto-reconnect wanted
        elif action == "connect":
            await d.call_connect()
        elif action == "disconnect":
            await d.call_disconnect()
        elif action in ("trust", "untrust"):
            await d.set_trusted(action == "trust")
        else:
            raise HostCtlError(f"unknown bluetooth action '{action}'")
    except DBusError as e:
        raise HostCtlError(f"bluetooth {action} failed: {e.text or e.type}") from e
