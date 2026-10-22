"""Switches for a Bento machine from the hub, and Remove (agentos/devicectl.py).

Asked for as "an option of removing it, I would like to test on and off on a few things, and
that should be in the inventory". The scripts devicectl sends are run here by a stand-in ssh in
real bash, against a stand-in Pi home whose `bento` and `systemctl` change files, so what is
tested is the shell that goes over the wire: the state is read from the machine, a switch is
what was shown, and Remove takes the program and keeps ~/.agentos."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import devicectl, inventory, teamlink                   # noqa: E402

ROOT = Path(__file__).parent.parent

SSH = r'''#!/bin/sh
# the last argument is the remote command: run it as the Pi would, in its home
for a; do last="$a"; done
printf '%s\n' "$last" >> "$PI_HOME/../calls.txt"
HOME="$PI_HOME" PATH="$PI_BIN:/usr/bin:/bin" exec bash -c "$last"
'''
SYSTEMCTL = r'''#!/bin/sh
case "$*" in
  *is-active*agentos*) cat "$HOME/.running" 2>/dev/null || echo inactive ;;
  *is-enabled*) exit 1 ;;
esac
'''
BENTO = r'''#!/bin/sh
case "$1 $2" in
  "service start") echo active > "$HOME/.running" ;;
  "service stop") echo inactive > "$HOME/.running" ;;
  "screen on") mkdir -p "$HOME/.config/autostart"; touch "$HOME/.config/autostart/bento-screen.desktop" ;;
  "screen off") rm -f "$HOME/.config/autostart/bento-screen.desktop" ;;
  "face kiosk") python3 -c "import json,os,sys
p=os.path.expanduser('~/.agentos/config.json'); c=json.load(open(p)); c.setdefault('face',{})['kiosk']=sys.argv[1]=='on'
json.dump(c,open(p,'w'))" "$3" ;;
  "uninstall ") echo inactive > "$HOME/.running"; echo "▲ AgentOS uninstalled" ;;
esac
'''


@pytest.fixture()
def pi(tmp_path, monkeypatch):
    bin_, pib = tmp_path / "bin", tmp_path / "pibin"
    home = tmp_path / "pihome"
    for d in (bin_, pib, home / ".local/bin", home / ".local/src/agentic-os/agentos", home / ".agentos"):
        d.mkdir(parents=True)
    for path, text in ((bin_ / "ssh", SSH), (pib / "systemctl", SYSTEMCTL), (home / ".local/bin/bento", BENTO),
                       (pib / "curl", "#!/bin/sh\nexit 7\n"), (bin_ / "ssh-keygen", "#!/bin/sh\nexit 0\n"),
                       # never the host's own pkill: it would stop whatever matches on the machine running the tests
                       (pib / "pkill", "#!/bin/sh\necho \"$@\" >> \"$HOME/../pkill.txt\"\n")):
        path.write_text(text)
        path.chmod(0o755)
    (pib / "python3").symlink_to(sys.executable)
    (home / ".local/src/agentic-os/agentos/VERSION").write_text("0.6.75\n")
    (home / ".agentos/config.json").write_text(json.dumps({"port": 8321, "face": {"kiosk": False}}))
    (home / ".agentos/agentos.db").write_text("memory")
    (home / ".running").write_text("active\n")
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("PI_HOME", str(home))
    monkeypatch.setenv("PI_BIN", str(pib))
    with teamlink.at(tmp_path / "hub"):
        kp = tmp_path / "hub" / "pki" / "ssh_ed25519"
        kp.parent.mkdir(parents=True, exist_ok=True)
        kp.write_text("PRIVATE")
        yield home


def _st():
    return asyncio.run(devicectl.state("192.168.1.9", "pi"))


def test_the_state_is_read_from_the_machine_in_plain_shell(pi):
    st = _st()
    assert st["installed"] and st["version"] == "0.6.75" and st["running"]
    assert not st["screen"] and not st["listening"] and st["port"] == 8321
    assert "bento" not in devicectl.STATE_SCRIPT.split("\n")[0].replace('"$HOME/.local/bin/bento"', ""), \
        "it reads files and systemctl, so an old Bento answers too"


def test_each_switch_is_what_was_shown_and_is_read_back(pi):
    calls = pi.parent / "calls.txt"
    for which in ("screen", "listening", "running"):
        for on in (which != "running", which == "running"):
            got = asyncio.run(devicectl.switch("192.168.1.9", "pi", "", 22, which, on))
            assert got["state"][which] == on, (which, on)
            assert devicectl.command(which, on) in calls.read_text()
    assert "--yes" in devicectl.command("screen", True), "the hub's form is the consent; nothing asks there"
    with pytest.raises(ValueError):
        devicectl.command("code", True)


def test_remove_takes_the_program_and_keeps_its_data(pi):
    got = asyncio.run(devicectl.remove("192.168.1.9", "pi"))
    assert got["ok"] and not got["state"]["installed"]
    assert not (pi / ".local/src/agentic-os").exists() and not (pi / ".local/bin/bento").exists()
    assert (pi / ".agentos/agentos.db").read_text() == "memory", "memory and settings stay"
    assert "-f [s]creen-profile" in (pi.parent / "pkill.txt").read_text(), "closes the screen without matching itself"


def test_what_was_read_is_kept_in_the_inventory_and_a_removed_one_says_so(pi, monkeypatch):
    inventory.note_controls("192.168.1.9", "", _st(), "pi", by="test")
    e = inventory.load()["devices"]["192.168.1.9"]
    assert e["controls"]["state"]["running"] and e["controls"]["at"] and e["user"] == "pi"
    asyncio.run(devicectl.remove("192.168.1.9", "pi"))
    inventory.note_controls("192.168.1.9", "", _st(), "pi")
    r = inventory.find(inventory.rows(), "192.168.1.9")
    assert r["bento"] == "removed"


def test_the_hub_has_routes_a_terminal_and_a_devices_app_for_it():
    src = (ROOT / "agentos/server.py").read_text()
    for route in ("/api/network/controls", "/api/network/switch", "/api/network/remove"):
        body = src[src.index(f'@app.post("{route}")'):][:600]
        assert "_require_admin()" in body, route
    remove = src[src.index('@app.post("/api/network/remove")'):src.index('@app.post("/api/network/disconnect")')]
    assert "_team_end_link" in remove and "poolmod.remove" in remove and "device.remove" in remove
    cli = (ROOT / "agentos/__main__.py").read_text()
    assert '"controls", "switch", "remove", "update"]' in cli
    js = (ROOT / "agentos/ui/src/js/05-apps-registry.js").read_text()
    assert "devices:{id:'devices'" in js and "'devices'" in js.split("DESKTOP_APPS")[1][:300]
    net = (ROOT / "agentos/ui/src/js/24n-network.js").read_text()
    assert ".devhub-box" in net, "the Devices app and Settings draw one list"


def test_update_runs_bento_update_there_and_reads_the_version_after(pi):
    (pi / ".local/bin/bento").write_text((pi / ".local/bin/bento").read_text().replace(
        'case "$1 $2" in', 'case "$1 $2" in\n  "update ") echo 0.6.79 > "$HOME/.local/src/agentic-os/agentos/VERSION"; echo "version 0.6.75 → 0.6.79" ;;'))
    got = asyncio.run(devicectl.update("192.168.1.9", "pi"))
    assert got["ok"] and got["state"]["version"] == "0.6.79" and "0.6.79" in got["said"][-1]
