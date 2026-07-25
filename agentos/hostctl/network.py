"""NetworkManager over D-Bus: the wifi picker that replaces gnome-control-center.

Scan, list with signal/security, join with a passphrase, forget, airplane mode.
Talking D-Bus instead of shelling nmcli means passphrases go over the bus to the
daemon — never onto a command line where any process could read them from
/proc/*/cmdline.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from dbus_fast import Variant
from dbus_fast.errors import DBusError

from . import HostCtlError, interface, proxy

NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
SETTINGS_PATH = "/org/freedesktop/NetworkManager/Settings"
SETTINGS_IFACE = "org.freedesktop.NetworkManager.Settings"
CONN_IFACE = "org.freedesktop.NetworkManager.Settings.Connection"
DEVICE_IFACE = "org.freedesktop.NetworkManager.Device"
WIRELESS_IFACE = "org.freedesktop.NetworkManager.Device.Wireless"
AP_IFACE = "org.freedesktop.NetworkManager.AccessPoint"

NM_DEVICE_TYPE_WIFI = 2


def available() -> tuple[bool, str, str]:
    if not Path("/run/NetworkManager").exists():
        return (False, "NetworkManager isn't running on this system.", "network-manager")
    return True, "", ""


def ap_security(flags: int, wpa: int, rsn: int) -> str:
    """Human word for an AP's protection, from its three NM flag fields."""
    if rsn & 0x200 or rsn & 0x400:      # KEY_MGMT_SAE / OWE
        return "wpa3"
    if rsn:
        return "wpa2"
    if wpa:
        return "wpa"
    if flags & 0x1:                     # NM_802_11_AP_FLAGS_PRIVACY (WEP-era)
        return "wep"
    return "open"


def build_connection(ssid: str, psk: str | None, security: str) -> dict:
    """The a{sa{sv}} settings blob for AddAndActivateConnection."""
    conn: dict = {
        "connection": {"id": Variant("s", ssid),
                       "type": Variant("s", "802-11-wireless")},
        "802-11-wireless": {"ssid": Variant("ay", ssid.encode()),
                            "mode": Variant("s", "infrastructure")},
    }
    if security == "open":
        return conn
    if not psk:
        raise HostCtlError(f"'{ssid}' is protected — a password is required.")
    if security in ("wpa", "wpa2", "wpa3"):
        key_mgmt = "sae" if security == "wpa3" else "wpa-psk"
        conn["802-11-wireless-security"] = {"key-mgmt": Variant("s", key_mgmt),
                                            "psk": Variant("s", psk)}
    elif security == "wep":
        conn["802-11-wireless-security"] = {"key-mgmt": Variant("s", "none"),
                                            "wep-key0": Variant("s", psk),
                                            "wep-key-type": Variant("u", 2)}
    return conn


async def _wifi_devices() -> list[str]:
    nm = await interface(NM, NM_PATH, NM)
    paths = []
    for dev_path in await nm.call_get_devices():
        try:
            dev = await interface(NM, dev_path, DEVICE_IFACE)
            if await dev.get_device_type() == NM_DEVICE_TYPE_WIFI:
                paths.append(dev_path)
        except (HostCtlError, DBusError):
            continue
    return paths


async def status() -> dict:
    """Adapter + connection overview for the panel header."""
    try:
        nm = await interface(NM, NM_PATH, NM)
        return {"wifi_enabled": await nm.get_wireless_enabled(),
                "wifi_hardware": await nm.get_wireless_hardware_enabled(),
                "networking": await nm.get_networking_enabled(),
                "connectivity": await nm.get_state()}   # NMState enum; 70 = full
    except (HostCtlError, DBusError) as e:
        raise HostCtlError(f"NetworkManager unavailable: {e}") from e


async def wifi_scan(rescan: bool = True) -> list[dict]:
    """Nearby networks, one row per SSID (strongest AP wins), sorted by signal."""
    devices = await _wifi_devices()
    if not devices:
        raise HostCtlError("No wifi adapter found on this machine.")
    aps: dict[str, dict] = {}
    for dev_path in devices:
        wl = await interface(NM, dev_path, WIRELESS_IFACE)
        if rescan:
            try:
                await wl.call_request_scan({})
                await asyncio.sleep(1.5)     # results land asynchronously; a beat is enough
            except DBusError:
                pass                          # scan throttled — cached APs are fine
        active_ap = await wl.get_active_access_point()
        for ap_path in await wl.call_get_all_access_points():
            try:
                ap = await interface(NM, ap_path, AP_IFACE)
                ssid = bytes(await ap.get_ssid()).decode(errors="replace")
                if not ssid:
                    continue                  # hidden network
                row = {
                    "ssid": ssid,
                    "signal": await ap.get_strength(),
                    "security": ap_security(await ap.get_flags(),
                                            await ap.get_wpa_flags(),
                                            await ap.get_rsn_flags()),
                    "frequency": await ap.get_frequency(),
                    "connected": ap_path == active_ap,
                    "device": dev_path,
                    "_ap_path": ap_path,
                }
                cur = aps.get(ssid)
                if not cur or row["signal"] > cur["signal"] or row["connected"]:
                    aps[ssid] = row
            except (HostCtlError, DBusError):
                continue
    known = {s async for s in _saved_ssids()}
    out = []
    for row in sorted(aps.values(), key=lambda r: (-r["connected"], -r["signal"])):
        row["saved"] = row["ssid"] in known
        out.append(row)
    return out


async def _saved_ssids():
    settings = await interface(NM, SETTINGS_PATH, SETTINGS_IFACE)
    for cpath in await settings.call_list_connections():
        try:
            c = await interface(NM, cpath, CONN_IFACE)
            s = await c.call_get_settings()
            wl = s.get("802-11-wireless")
            if wl and "ssid" in wl:
                yield bytes(wl["ssid"].value).decode(errors="replace")
        except (HostCtlError, DBusError):
            continue


async def wifi_join(ssid: str, psk: str | None = None) -> None:
    """Join by SSID. Reactivates a saved profile when one exists; otherwise
    creates one from the live AP's advertised security."""
    devices = await _wifi_devices()
    if not devices:
        raise HostCtlError("No wifi adapter found on this machine.")
    dev_path = devices[0]
    nm = await interface(NM, NM_PATH, NM)

    # A saved profile first — no passphrase needed again.
    settings = await interface(NM, SETTINGS_PATH, SETTINGS_IFACE)
    for cpath in await settings.call_list_connections():
        try:
            c = await interface(NM, cpath, CONN_IFACE)
            s = await c.call_get_settings()
            wl = s.get("802-11-wireless")
            if wl and bytes(wl["ssid"].value).decode(errors="replace") == ssid:
                await nm.call_activate_connection(cpath, dev_path, "/")
                return
        except (HostCtlError, DBusError):
            continue

    target = next((r for r in await wifi_scan(rescan=False) if r["ssid"] == ssid), None)
    if not target:
        raise HostCtlError(f"'{ssid}' is not in range.")
    try:
        await nm.call_add_and_activate_connection(
            build_connection(ssid, psk, target["security"]),
            dev_path, target["_ap_path"])
    except DBusError as e:
        raise HostCtlError(f"could not join '{ssid}': {e.text}") from e


async def wifi_forget(ssid: str) -> bool:
    settings = await interface(NM, SETTINGS_PATH, SETTINGS_IFACE)
    removed = False
    for cpath in await settings.call_list_connections():
        try:
            c = await interface(NM, cpath, CONN_IFACE)
            s = await c.call_get_settings()
            wl = s.get("802-11-wireless")
            if wl and bytes(wl["ssid"].value).decode(errors="replace") == ssid:
                await c.call_delete()
                removed = True
        except (HostCtlError, DBusError):
            continue
    return removed


async def set_wifi_enabled(enabled: bool) -> None:
    try:
        nm = await interface(NM, NM_PATH, NM)
        await nm.set_wireless_enabled(bool(enabled))
    except (HostCtlError, DBusError) as e:
        raise HostCtlError(f"could not switch wifi: {e}") from e


async def set_networking_enabled(enabled: bool) -> None:
    """Airplane mode is `networking off` — every radio and link at once."""
    try:
        nm = await interface(NM, NM_PATH, NM)
        await nm.call_enable(bool(enabled))
    except (HostCtlError, DBusError) as e:
        raise HostCtlError(f"could not switch networking: {e}") from e
