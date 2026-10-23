"""Wi-Fi from the machine's own screen (agentos/wifi.py, the kiosk's Wi-Fi panel, bento wifi).

Asked for from a Raspberry Pi whose kiosk fills the screen: "I am not able to connect to wifi
when it loads". A stand-in nmcli records every call, so what is tested is what would be asked
of NetworkManager: the password is never on a command line, it reaches NetworkManager through
a private file that is gone afterwards, and a machine whose internet check is off still reads
as online when it is connected."""
import json
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import wifi  # noqa: E402

ROOT = Path(__file__).parent.parent

NMCLI = r'''#!/usr/bin/env python3
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
a = sys.argv[1:]
rec = {"argv": a}
if "passwd-file" in a:
    f = a[a.index("passwd-file") + 1]
    st = os.stat(f)
    rec["file_mode"] = oct(st.st_mode & 0o777)
    rec["dir_mode"] = oct(os.stat(os.path.dirname(f)).st_mode & 0o777)
    rec["file"] = f
    rec["secret"] = open(f).read()
with open(os.path.join(here, "calls.jsonl"), "a") as fh:
    fh.write(json.dumps(rec) + "\n")
conn = os.environ.get("FAKE_CONN", "full")
if a[:2] == ["networking", "connectivity"]:
    print(conn); sys.exit(0)
if "device" in a and "wifi" not in a:
    print("wlan0:wifi:" + os.environ.get("FAKE_STATE", "connected") + ":1401")
    print("eth0:ethernet:unavailable:")
    sys.exit(0)
if "list" in a:
    print("*:1401:64:WPA2")
    print(" :Cafe\\:Guest:80:")
    print(" :1401:40:WPA2")
    print(" ::50:WPA2")
    print(" :Evil‮Name:20:WPA2")
    sys.exit(0)
if a[:2] == ["-t", "-f"] and "connection" in a and "show" in a:
    sys.exit(0)
if "up" in a and os.environ.get("FAKE_BADPW") and "passwd-file" in a:
    sys.stderr.write("Error: Connection activation failed: Secrets were required, but not provided.\n")
    sys.exit(4)
sys.exit(0)
'''


@pytest.fixture()
def nm(tmp_path, monkeypatch):
    b = tmp_path / "bin"
    b.mkdir()
    (b / "nmcli").write_text(NMCLI)
    (b / "nmcli").chmod(0o755)
    monkeypatch.setenv("PATH", f"{b}{os.pathsep}{os.environ['PATH']}")
    return b


def _calls(b):
    p = b / "calls.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_status_reads_the_network_and_unknown_with_a_connection_is_online(nm, monkeypatch):
    st = wifi.status()
    assert st["online"] and st["wifi"]["connection"] == "1401" and st["wifi"]["signal"] == 64
    monkeypatch.setenv("FAKE_CONN", "unknown")
    assert wifi.status()["online"], "Raspberry Pi OS turns the internet check off: connected is online"
    monkeypatch.setenv("FAKE_STATE", "disconnected")
    monkeypatch.setenv("FAKE_CONN", "none")
    st = wifi.status()
    assert not st["online"] and st["wifi"]["state"] == "disconnected"


def test_networks_are_named_cleanly_one_row_each_strongest_first(nm):
    got = wifi.networks()
    names = [n["ssid"] for n in got]
    assert names[0] == "1401" and got[0]["in_use"], "the one in use first"
    assert "Cafe:Guest" in names, "an escaped colon in a name is part of the name"
    assert names.count("1401") == 1 and "" not in names, "one row per name, a hidden network has none"
    assert not any("‮" in n for n in names), "a name is somebody else's words: no bidi override"
    assert next(n for n in got if n["ssid"] == "Cafe:Guest")["secure"] is False


def test_joining_never_puts_the_password_on_a_command_line(nm):
    got = wifi.connect("1401_5G", "correct horse")
    assert got["ok"]
    calls = _calls(nm)
    assert not any("correct horse" in " ".join(c["argv"]) for c in calls)
    up = next(c for c in calls if "passwd-file" in c["argv"])
    assert up["secret"] == "802-11-wireless-security.psk:correct horse\n"
    assert up["file_mode"] == "0o600" and up["dir_mode"] == "0o700"
    assert not Path(up["file"]).exists(), "the file is gone afterwards"
    add = next(c for c in calls if "add" in c["argv"])
    assert "wifi-sec.psk-flags" in add["argv"] and "0" in add["argv"], "kept for the next boot"
    assert "connection.autoconnect" in add["argv"]


def test_a_refused_password_is_a_sentence_and_bad_input_never_reaches_nmcli(nm, monkeypatch):
    monkeypatch.setenv("FAKE_BADPW", "1")
    with pytest.raises(ValueError, match="password was not accepted"):
        wifi.connect("1401_5G", "wrong-one")
    n = len(_calls(nm))
    for ssid, pw in (("", "longenough"), ("x" * 33, "longenough"), ("a\nb", "longenough"), ("ok", "short")):
        with pytest.raises(ValueError):
            wifi.connect(ssid, pw)
    assert len(_calls(nm)) == n


def test_no_networkmanager_is_a_sentence(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert "NetworkManager" in wifi.available()
    st = wifi.status()
    assert not st["ok"] and "NetworkManager" in st["why"] and wifi.networks() == []


def test_the_kiosk_offers_wifi_when_offline_and_joining_is_admin_only():
    js = (ROOT / "agentos/ui/src/js/24h-kiosk.js").read_text()
    assert "No network. Tap Wi-Fi to join one." in js and "/api/wifi/connect" in js
    assert "setInterval" not in js[js.index("function kioskNet"):], "a timer that stops with the kiosk"
    srv = (ROOT / "agentos/server.py").read_text()
    route = srv[srv.index('@app.post("/api/wifi/connect")'):]
    route = route[:route.index("\n@app.")]
    assert "_require_admin()" in route and "password" not in route.split("_ledger(", 1)[1][:200]
