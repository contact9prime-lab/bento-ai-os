"""hostctl — the parsing and message-building brains, without live daemons.

The D-Bus calls themselves are thin; what can rot silently is the logic around
them: security-flag interpretation, the connection blob NM accepts, BlueZ tree
flattening, the PipeWire graph parse, and sysfs handling. Those are pure
functions, tested here with recorded shapes. `agentos doctor` covers the live
daemons.
"""

import json
from types import SimpleNamespace

import pytest

from agentos.hostctl import HostCtlError
from agentos.hostctl import audio, bluetooth, brightness, network


# --- network ----------------------------------------------------------------

def test_ap_security_ladder():
    # (flags, wpa, rsn) -> label
    assert network.ap_security(0, 0, 0) == "open"
    assert network.ap_security(1, 0, 0) == "wep"
    assert network.ap_security(1, 0x188, 0) == "wpa"
    assert network.ap_security(1, 0, 0x188) == "wpa2"
    assert network.ap_security(1, 0, 0x200) == "wpa3"       # SAE
    assert network.ap_security(1, 0x188, 0x188) == "wpa2"   # mixed mode -> best label


def test_build_connection_open_network_has_no_security_block():
    blob = network.build_connection("CafeWifi", None, "open")
    assert "802-11-wireless-security" not in blob
    assert blob["802-11-wireless"]["ssid"].value == b"CafeWifi"
    assert blob["connection"]["type"].value == "802-11-wireless"


def test_build_connection_wpa2_and_wpa3():
    blob = network.build_connection("Home", "hunter22", "wpa2")
    sec = blob["802-11-wireless-security"]
    assert sec["key-mgmt"].value == "wpa-psk"
    assert sec["psk"].value == "hunter22"
    blob3 = network.build_connection("Home", "hunter22", "wpa3")
    assert blob3["802-11-wireless-security"]["key-mgmt"].value == "sae"


def test_build_connection_protected_without_password_refuses():
    with pytest.raises(HostCtlError, match="password"):
        network.build_connection("Home", None, "wpa2")
    with pytest.raises(HostCtlError, match="password"):
        network.build_connection("Home", "", "wpa3")


def test_ssid_bytes_roundtrip_non_ascii():
    blob = network.build_connection("Пиюш-5G", "pw", "wpa2")
    assert blob["802-11-wireless"]["ssid"].value.decode() == "Пиюш-5G"


# --- bluetooth ---------------------------------------------------------------

def _var(v):
    return SimpleNamespace(value=v)


BLUEZ_TREE = {
    "/org/bluez/hci0": {
        "org.bluez.Adapter1": {"Alias": _var("agentos-box"), "Address": _var("AA:BB:CC:DD:EE:FF"),
                               "Powered": _var(True), "Discovering": _var(False)},
    },
    "/org/bluez/hci0/dev_11_22_33_44_55_66": {
        "org.bluez.Device1": {"Alias": _var("WH-1000XM4"), "Address": _var("11:22:33:44:55:66"),
                              "Paired": _var(True), "Connected": _var(True),
                              "Trusted": _var(True), "Icon": _var("audio-headset"),
                              "RSSI": _var(-45)},
        "org.bluez.Battery1": {"Percentage": _var(80)},
    },
    "/org/bluez/hci0/dev_77_88_99_AA_BB_CC": {
        "org.bluez.Device1": {"Name": _var("MX Master"), "Address": _var("77:88:99:AA:BB:CC"),
                              "Paired": _var(False), "Connected": _var(False),
                              "Trusted": _var(False)},
    },
}


def test_bluez_tree_parses_adapters_devices_and_battery():
    t = bluetooth.parse_tree(BLUEZ_TREE)
    assert t["adapters"][0]["name"] == "agentos-box"
    assert t["adapters"][0]["powered"] is True
    names = [d["name"] for d in t["devices"]]
    assert names == ["WH-1000XM4", "MX Master"]     # connected sorts first
    headset = t["devices"][0]
    assert headset["battery"] == 80
    assert headset["icon"] == "audio-headset"
    assert "battery" not in t["devices"][1]


def test_bluez_paths_are_validated():
    with pytest.raises(HostCtlError, match="invalid"):
        bluetooth._checked_path("/etc/passwd")
    assert bluetooth._checked_path("/org/bluez/hci0/dev_X") == "/org/bluez/hci0/dev_X"


# --- audio -------------------------------------------------------------------

PW_DUMP = [
    {"id": 40, "type": "PipeWire:Interface:Node",
     "info": {"props": {"media.class": "Audio/Sink", "node.name": "alsa_output.hdmi",
                        "node.description": "HDMI Audio"}}},
    {"id": 41, "type": "PipeWire:Interface:Node",
     "info": {"props": {"media.class": "Audio/Sink", "node.name": "bluez_output.xm4",
                        "node.description": "WH-1000XM4"}}},
    {"id": 50, "type": "PipeWire:Interface:Node",
     "info": {"props": {"media.class": "Audio/Source", "node.name": "alsa_input.mic",
                        "node.description": "Microphone"}}},
    {"id": 60, "type": "PipeWire:Interface:Node",
     "info": {"props": {"media.class": "Stream/Output/Audio",
                        "application.name": "Firefox", "node.name": "firefox"}}},
    {"id": 61, "type": "PipeWire:Interface:Node",
     "info": {"props": {"media.class": "Stream/Input/Audio",   # a recorder, not playback
                        "application.name": "OBS", "node.name": "obs"}}},
    {"id": 2, "type": "PipeWire:Interface:Metadata",
     "props": {"metadata.name": "default"},
     "metadata": [{"key": "default.audio.sink", "value": {"name": "bluez_output.xm4"}},
                  {"key": "default.audio.source", "value": {"name": "alsa_input.mic"}}]},
]


def test_pw_graph_parse_and_defaults():
    sink, source = audio._default_node_names(PW_DUMP)
    assert (sink, source) == ("bluez_output.xm4", "alsa_input.mic")
    g = audio.parse_graph(PW_DUMP, sink, source)
    assert [s["description"] for s in g["sinks"]] == ["HDMI Audio", "WH-1000XM4"]
    assert [s["default"] for s in g["sinks"]] == [False, True]
    assert g["sources"][0]["default"] is True
    # Only playback streams belong in a volume mixer; capture streams don't.
    assert [s["app"] for s in g["streams"]] == ["Firefox"]


def test_pw_graph_handles_empty_dump():
    assert audio.parse_graph([], "", "") == {"sinks": [], "sources": [], "streams": []}


# --- brightness --------------------------------------------------------------

def test_backlights_reads_sysfs(tmp_path, monkeypatch):
    intel = tmp_path / "intel_backlight"
    intel.mkdir()
    (intel / "max_brightness").write_text("19200\n")
    (intel / "brightness").write_text("9600\n")
    broken = tmp_path / "weird"
    broken.mkdir()
    (broken / "max_brightness").write_text("0\n")      # divide-by-zero bait
    monkeypatch.setattr(brightness, "BACKLIGHT_DIR", tmp_path)
    devs = brightness.backlights()
    assert devs == [{"kind": "backlight", "name": "intel_backlight",
                     "percent": 50, "max": 19200}]


def test_backlights_empty_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(brightness, "BACKLIGHT_DIR", tmp_path / "nope")
    assert brightness.backlights() == []


def test_brightness_availability_names_the_component(tmp_path, monkeypatch):
    monkeypatch.setattr(brightness, "BACKLIGHT_DIR", tmp_path / "none")
    monkeypatch.setattr(brightness.shutil, "which", lambda n: None)
    ok, reason, component = brightness.available()
    assert ok is False and component == "ddcutil" and "ddcutil" in reason


@pytest.mark.asyncio
async def test_set_backlight_validates_device(tmp_path, monkeypatch):
    monkeypatch.setattr(brightness, "BACKLIGHT_DIR", tmp_path)
    with pytest.raises(HostCtlError, match="no backlight device"):
        await brightness.set_backlight("ghost", 50)


# --- api shape ---------------------------------------------------------------

def test_wifi_scan_rows_hide_dbus_paths_at_the_api(monkeypatch):
    """The endpoint strips _ap_path before returning; make the field's privacy
    contract explicit here so a rename doesn't silently start leaking it."""
    row = {"ssid": "x", "signal": 70, "security": "wpa2", "frequency": 5180,
           "connected": False, "device": "/org/freedesktop/NetworkManager/Devices/2",
           "_ap_path": "/org/freedesktop/NetworkManager/AccessPoint/9", "saved": False}
    public = {k: v for k, v in row.items() if k != "_ap_path"}
    assert "_ap_path" not in public and public["ssid"] == "x"
