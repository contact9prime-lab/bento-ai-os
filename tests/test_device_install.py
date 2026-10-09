"""Machines WITHOUT Bento: found on the network, recognised, and offered an install.

Asked for as "discover the devices in the same network, or add a new device without Bento
installed on it, and ask if you would like to install on it … the idea is POAP: it connects
to the network, DHCP gives it an IP, and Bento discovers it and asks". Three roads, each
pinned here: the passive mDNS ear and the on-request scan (netscan.py), the install over SSH
with a person's yes (remoteinstall.py), and the SD card that installs on first boot
(sdcard.py). The live walk-through with a real OpenSSH server and the real installer is
packaging/dev/provision-e2e/install_over_ssh.py.
"""
import asyncio
import ipaddress
import json
import os
import socket
import stat
import struct
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import netscan, remoteinstall, sdcard, teamlink        # noqa: E402

ROOT = Path(__file__).parent.parent


# ---- the ear: what a booted Pi says on the network ------------------------------------------

def _name(n: str) -> bytes:
    return b"".join(bytes([len(x)]) + x.encode() for x in n.split(".")) + b"\0"


def _answer(records, question=False) -> bytes:
    """An mDNS message the way avahi sends one: a response with A records, the second
    one using a compression pointer back to the first name."""
    flags = 0x0000 if question else 0x8400
    out = struct.pack("!6H", 0, flags, 0, len(records), 0, 0)
    first = None
    for name, ip in records:
        if first is not None and name == records[0][0]:
            out += struct.pack("!H", 0xC000 | first)
        else:
            first = len(out) if first is None else first
            out += _name(name)
        out += struct.pack("!HHIH", 1, 0x8001, 120, 4) + socket.inet_aton(ip)
    return out


def test_the_ear_reads_a_pi_saying_its_name():
    pkt = _answer([("raspberrypi.local", "192.168.1.40"), ("raspberrypi.local", "10.0.0.7")])
    assert netscan.parse_mdns(pkt) == [("raspberrypi.local", "192.168.1.40"),
                                       ("raspberrypi.local", "10.0.0.7")]


def test_the_ear_ignores_questions_and_garbage():
    assert netscan.parse_mdns(_answer([("x.local", "192.168.1.2")], question=True)) == []
    for junk in (b"", b"\x00" * 5, b"\xff" * 64, _answer([("a.local", "10.0.0.1")])[:-3]):
        assert netscan.parse_mdns(junk) == []
    # a pointer loop must not hang the ear
    loop = struct.pack("!6H", 0, 0x8400, 0, 1, 0, 0) + b"\xc0\x0c"
    assert netscan.parse_mdns(loop) == []


def test_the_ear_hears_over_udp_and_keeps_only_local_names(monkeypatch):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    monkeypatch.setenv("AGENTOS_MDNS_PORT", str(port))
    monkeypatch.delenv("AGENTOS_SCAN_NETWORKS", raising=False)
    heard = []

    async def go():
        ear = await netscan.MdnsEar(lambda n, ip: heard.append((n, ip))).start()
        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tx.sendto(_answer([("raspberrypi.local", "192.168.1.40")]), ("127.0.0.1", port))
        tx.sendto(_answer([("evil.example.com", "192.168.1.41")]), ("127.0.0.1", port))
        tx.sendto(_answer([("far.local", "8.8.8.8")]), ("127.0.0.1", port))
        tx.close()
        await asyncio.sleep(0.3)
        await ear.stop()
    asyncio.run(go())
    assert heard == [("raspberrypi", "192.168.1.40")], "only a .local name with a private address"


# ---- who is who -------------------------------------------------------------------------------

def test_a_pi_is_known_by_its_mac_and_a_random_one_is_not_guessed():
    assert netscan.maker("D8:3A:DD:12:34:56") == "Raspberry Pi"
    assert netscan.maker("2c:cf:67:00:00:01") == "Raspberry Pi"
    assert netscan.maker("da:a1:19:00:00:01") == "private address"
    assert netscan.maker("00:1a:2b:00:00:01") == ""
    assert netscan.maker("nonsense") == ""


def test_the_neighbour_table_is_read_and_incomplete_rows_skipped():
    arp = ("IP address       HW type     Flags       HW address            Mask     Device\n"
           "192.168.1.40     0x1         0x2         dc:a6:32:aa:bb:cc     *        wlan0\n"
           "192.168.1.41     0x1         0x0         00:00:00:00:00:00     *        wlan0\n"
           "192.168.1.42     0x1         0x2         garbage               *        wlan0\n")
    assert netscan.neighbours(arp) == {"192.168.1.40": "dc:a6:32:aa:bb:cc"}


def test_the_banner_hints_at_the_os():
    assert netscan.os_from_banner("SSH-2.0-OpenSSH_10.0p2 Debian-7") == "Debian 13 (trixie)"
    assert netscan.os_from_banner("SSH-2.0-OpenSSH_9.2p1 Debian-2+deb12u3") == "Debian 12 (bookworm)"
    assert netscan.os_from_banner("SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13") == "Ubuntu"
    assert netscan.os_from_banner("SSH-2.0-dropbear") == ""


def test_only_private_networks_are_ever_knocked_on(monkeypatch):
    monkeypatch.delenv("AGENTOS_SCAN_NETWORKS", raising=False)
    for ip in ("192.168.1.5", "10.1.2.3", "172.16.0.9", "169.254.10.10"):
        assert netscan.allowed(ip), ip
    for ip in ("8.8.8.8", "1.1.1.1", "127.0.0.1", "not-an-ip", ""):
        assert not netscan.allowed(ip), ip
    for net in netscan.local_networks():
        assert net.num_addresses <= netscan.MAX_HOSTS + 2 or net.prefixlen >= 22


def test_a_device_heard_then_knocked_on_is_one_device():
    seen = {}
    assert netscan.remember(seen, {"ip": "192.168.1.40", "name": "raspberrypi"}) is True
    assert netscan.remember(seen, {"ip": "192.168.1.40", "mac": "dc:a6:32:aa:bb:cc", "ssh": True}) is False
    assert list(seen) == ["dc:a6:32:aa:bb:cc"]
    assert seen["dc:a6:32:aa:bb:cc"]["name"] == "raspberrypi"
    assert netscan.remember(seen, {"ip": "192.168.1.40", "name": "raspberrypi"}) is False, \
        "heard again by name: no second toast"
    for i in range(300):
        netscan.remember(seen, {"ip": f"10.0.{i // 250}.{i % 250 + 1}"})
    assert len(seen) <= 256


def test_a_scan_finds_ssh_reads_its_banner_and_skips_a_silent_port(monkeypatch):
    async def go():
        async def sshd(r, w):
            w.write(b"SSH-2.0-OpenSSH_10.0p2 Debian-7\r\n")
            await w.drain()
            w.close()
        srv = await asyncio.start_server(sshd, "127.0.0.3", 0)
        port = srv.sockets[0].getsockname()[1]
        closed = socket.socket()
        closed.bind(("127.0.0.3", 0))
        dead = closed.getsockname()[1]
        closed.close()
        monkeypatch.setenv("AGENTOS_SCAN_NETWORKS", "127.0.0.3/32")
        monkeypatch.setenv("AGENTOS_SCAN_PORTS", f"{port},{dead}")
        got = await netscan.scan([ipaddress.ip_network("127.0.0.3/32"),
                                  ipaddress.ip_network("127.0.0.4/32")], timeout=0.5)
        srv.close()
        return got, port
    got, port = asyncio.run(go())
    assert len(got) == 1, got
    d = got[0]
    assert d["ip"] == "127.0.0.3" and d["ssh"] and d["ports"] == [port]
    assert d["os"] == "Debian 13 (trixie)" and d["banner"].startswith("SSH-2.0")


# ---- the install over SSH ---------------------------------------------------------------------

FAKE_SSH = r'''#!/usr/bin/env python3
"""A stand-in `ssh`: logs in with the password from SSH_ASKPASS or with the key, runs the
check or records the install. Its own log is how the test reads what was asked of it."""
import json, os, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
remote = args[-1]
target = args[-2]
log = {"args": args, "env_has_password": "BENTO_SSH_PASSWORD" in os.environ}
if os.environ.get("SSH_ASKPASS"):
    pw = subprocess.run([os.environ["SSH_ASKPASS"]], capture_output=True, text=True).stdout.strip()
    log["via"] = "password"
    ok = pw == "right-one"
else:
    log["via"] = "key"
    ok = "-i" in args and os.path.exists(os.path.join(here, "authorized"))
with open(os.path.join(here, "calls.jsonl"), "a") as f:
    f.write(json.dumps(log) + "\n")
if not ok:
    sys.stderr.write(target + ": Permission denied (publickey,password).\n")
    sys.exit(255)
if remote.startswith("echo arch="):
    print("arch=aarch64\nboard=Raspberry Pi 5 Model B Rev 1.0\nos=Debian GNU/Linux 13 (trixie)\n"
          "curl=yes\nbento=no\nfree_kb=20971520\nram_kb=8245000")
    sys.exit(0)
with open(os.path.join(here, "remote.txt"), "w") as f:
    f.write(remote)
if "authorized_keys" in remote:
    open(os.path.join(here, "authorized"), "w").close()
if "will-fail" in remote:
    print("\x1b[36m\u25b2 cloning AgentOS\x1b[0m")
    sys.stderr.write("\x1b[31m\u2717 clone failed: check the network and try again\x1b[0m\n")
    sys.exit(1)
print("Bento installer\nbuilding the environment\ndone")
'''


@pytest.fixture()
def fake_ssh(tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    ssh = bin_ / "ssh"
    ssh.write_text(FAKE_SSH)
    ssh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("AGENTOS_SCAN_NETWORKS", "127.0.0.0/8")
    monkeypatch.setenv("AGENTOS_INSTALL_URL", "https://example.test/install.sh")
    monkeypatch.delenv("AGENTOS_REPO", raising=False)
    monkeypatch.setenv("BENTO_SSH_PASSWORD", "leaked-from-the-parent")
    home = tmp_path / "home"
    with teamlink.at(home):
        yield bin_


def _calls(bin_):
    return [json.loads(x) for x in (bin_ / "calls.jsonl").read_text().splitlines()]


def test_a_check_reads_the_machine_and_never_sees_the_password_on_a_command_line(fake_ssh):
    c = asyncio.run(remoteinstall.check("127.0.0.2", "pi", "right-one"))
    assert c["arch"] == "aarch64" and c["board"].startswith("Raspberry Pi 5")
    assert c["curl"] and not c["bento"] and c["free_mb"] == 20480 and c["problems"] == []
    call = _calls(fake_ssh)[0]
    assert call["via"] == "password" and "right-one" not in " ".join(call["args"])
    assert "StrictHostKeyChecking=accept-new" in call["args"]
    kh = [a for a in call["args"] if a.startswith("UserKnownHostsFile=")][0]
    assert kh.endswith("pki/known_hosts"), "Bento pins hosts in its own file"
    left = list((remoteinstall.known_hosts().parent).glob(".askpass-*"))
    assert left == [], "the askpass helper goes with the call"


def test_a_wrong_password_is_a_sentence(fake_ssh):
    with pytest.raises(remoteinstall.InstallError, match="user name or password was refused"):
        asyncio.run(remoteinstall.check("127.0.0.2", "pi", "wrong"))


def test_with_no_key_and_no_password_nothing_is_tried(fake_ssh):
    with pytest.raises(remoteinstall.InstallError, match="no SSH key yet"):
        asyncio.run(remoteinstall.check("127.0.0.2", "pi", ""))
    assert not (fake_ssh / "calls.jsonl").exists()


def test_only_a_machine_on_this_network_and_a_real_user_name(fake_ssh, monkeypatch):
    monkeypatch.delenv("AGENTOS_SCAN_NETWORKS")
    for host, user in (("8.8.8.8", "pi"), ("192.168.1.4", "pi; rm -rf ~"), ("192.168.1.4", "")):
        with pytest.raises(remoteinstall.InstallError):
            asyncio.run(remoteinstall.check(host, user, "right-one"))
    assert not (fake_ssh / "calls.jsonl").exists()


def test_install_runs_the_plan_lets_the_key_in_and_then_needs_no_password(fake_ssh):
    pub = remoteinstall.ensure_key("leader")
    assert pub.startswith("ssh-ed25519 ")
    assert stat.S_IMODE(remoteinstall.key_path().stat().st_mode) == 0o600
    lines = []

    async def on_line(ln):
        lines.append(ln)
    key = "bento-enroll-1.0a1b2c3d." + "s" * 32 + "." + "f" * 16
    got = asyncio.run(remoteinstall.install({}, "127.0.0.2", "pi", "right-one", key,
                                            authorize=True, on_line=on_line))
    assert got["ok"] and got["authorized"] and lines[-1] == "done"
    remote = (fake_ssh / "remote.txt").read_text()
    assert remote == remoteinstall.plan({}, key, authorize=True), "what was shown is what ran"
    assert f"--enroll={key}" in remote and "--lite" in remote
    assert "--yes" not in remote, "--yes would install every optional extra nobody agreed to"
    assert "https://example.test/install.sh" in remote
    # next visit: the key, no password
    c = asyncio.run(remoteinstall.check("127.0.0.2", "pi"))
    assert c["arch"] == "aarch64" and _calls(fake_ssh)[-1]["via"] == "key"
    assert "BatchMode=yes" in _calls(fake_ssh)[-1]["args"]


def test_a_failed_install_says_the_installers_own_words_without_its_colours(fake_ssh, monkeypatch):
    monkeypatch.setenv("AGENTOS_INSTALL_URL", "https://example.test/will-fail.sh")
    lines = []

    async def on_line(ln):
        lines.append(ln)
    with pytest.raises(remoteinstall.InstallError) as e:
        asyncio.run(remoteinstall.install({}, "127.0.0.2", "pi", "right-one", "k", on_line=on_line))
    assert str(e.value) == "the installer stopped: \u2717 clone failed: check the network and try again"
    assert lines == ["\u25b2 cloning AgentOS"], "no escape codes reach a toast"
    assert remoteinstall.clean_line("\x1b]52;c;ZXZpbA==\x07ok\x1b[0m\u202e") == "ok"


def test_the_plan_quotes_what_it_runs(fake_ssh, monkeypatch):
    monkeypatch.setenv("AGENTOS_INSTALL_URL", "https://x.test/a b';reboot;'.sh")
    p = remoteinstall.plan({}, "")
    assert "--wait" in p and "--enroll" not in p
    assert "'https://x.test/a b'\"'\"';reboot;'\"'\"'.sh'" in p


def test_problems_are_named_before_anything_runs():
    assert remoteinstall.problems({"curl": False, "free_mb": 900, "arch": "mips"}) == [
        "curl is not installed there (sudo apt install curl)",
        "only 900 MB free there; Bento needs about 1.5 GB",
        "mips is not a processor Bento runs on"]


def test_the_password_is_never_in_the_ledger_or_a_file(fake_ssh, tmp_path):
    asyncio.run(remoteinstall.check("127.0.0.2", "pi", "right-one"))
    for f in tmp_path.rglob("*"):
        if f.is_file() and f.name != "ssh" and f.stat().st_size < 1_000_000:
            assert b"right-one" not in f.read_bytes(), f


# ---- the SD card: zero touch on a trixie image -------------------------------------------------

IMAGER_USER_DATA = """#cloud-config
hostname: raspberrypi
manage_etc_hosts: true
packages:
- avahi-daemon
apt:
  conf: |
    Acquire {
      Check-Date "false";
    };
users:
- name: ada
  groups: users,adm,dialout,audio,netdev,video,plugdev,cdrom,games,input,gpio,spi,i2c,render,sudo
  shell: /bin/bash
  lock_passwd: false
  passwd: $5$abc$hashhashhash
timezone: Europe/London
runcmd:
- [ sh, -c, "echo imager was here" ]
"""


def _card(tmp_path, **files):
    boot = tmp_path / "bootfs"
    boot.mkdir()
    (boot / "config.txt").write_text("arm_64bit=1\n")
    (boot / "cmdline.txt").write_text("console=serial0,115200 root=PARTUUID=x rootwait\n")
    for k, v in files.items():
        (boot / k.replace("_", "-")).write_text(v)
    return boot


def test_the_kit_merges_into_what_imager_wrote_and_keeps_all_of_it(tmp_path):
    boot = _card(tmp_path, user_data=IMAGER_USER_DATA)
    key = "bento-enroll-1.0a1b2c3d." + "s" * 32 + "." + "f" * 16
    r = sdcard.write(boot, url="https://example.test/install.sh", key_text=key,
                     pubkey="ssh-ed25519 AAAAC3Nza leader", hostname="pi-kitchen",
                     wifi={"ssid": "Home Net", "password": "correct horse", "country": "gb"})
    assert r["user"] == "ada" and set(r["written"]) >= {"user-data", "meta-data", "network-config"}
    text = (boot / "user-data").read_text()
    assert text.startswith("#cloud-config\n"), "cloud-init reads nothing without that first line"
    doc = yaml.safe_load(text)
    ada = doc["users"][0]
    assert ada["passwd"] == "$5$abc$hashhashhash" and ada["lock_passwd"] is False, "Imager's user stays"
    assert ada["ssh_authorized_keys"] == ["ssh-ed25519 AAAAC3Nza leader"]
    assert doc["enable_ssh"] is True and doc["hostname"] == "pi-kitchen"
    assert doc["timezone"] == "Europe/London" and doc["packages"] == ["avahi-daemon"]
    assert doc["runcmd"][0] == ["sh", "-c", "echo imager was here"]
    cmd = doc["runcmd"][-1]
    assert cmd[:2] == ["sh", "-c"] and "runuser -l ada" in cmd[2] and key in cmd[2]
    assert "loginctl enable-linger ada" in cmd[2] and sdcard.LOG in cmd[2]
    net = yaml.safe_load((boot / "network-config").read_text())["network"]
    wl = net["wifis"]["wlan0"]
    assert net["version"] == 2 and net["wifis"]["renderer"] == "NetworkManager"
    assert wl["regulatory-domain"] == "GB" and wl["access-points"]["Home Net"]["password"] == "correct horse"
    assert (boot / "bento-enroll.txt").read_text().strip() == key


def test_writing_the_kit_twice_keeps_one_first_boot_command(tmp_path):
    boot = _card(tmp_path, user_data=IMAGER_USER_DATA)
    for _ in range(2):
        sdcard.write(boot, url="https://e.test/i.sh", key_text="k1", pubkey="ssh-ed25519 A leader")
    doc = yaml.safe_load((boot / "user-data").read_text())
    assert sum(1 for c in doc["runcmd"] if sdcard.LOG in str(c)) == 1
    assert doc["users"][0]["ssh_authorized_keys"] == ["ssh-ed25519 A leader"]


def test_the_first_boot_command_is_a_shell_that_parses():
    import subprocess
    cmd = sdcard.first_boot_command("https://e.test/i.sh", "ada", "key'with;quote")
    r = subprocess.run(["sh", "-n", "-c", cmd[2]], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    inner = cmd[2].split("runuser -l ada -c ", 1)[1]
    assert "key'\"'\"'with;quote" in inner or "with;quote" in inner


def test_a_card_that_is_not_a_trixie_boot_partition_is_refused(tmp_path):
    with pytest.raises(sdcard.KitError, match="not a folder"):
        sdcard.write(tmp_path / "nope", url="u", key_text="k", pubkey="")
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(sdcard.KitError, match="boot partition"):
        sdcard.write(plain, url="u", key_text="k", pubkey="")
    bw = tmp_path / "bw"
    bw.mkdir()
    (bw / "config.txt").write_text("")
    (bw / "firstrun.sh").write_text("#!/bin/bash\n")
    with pytest.raises(sdcard.KitError, match="bookworm"):
        sdcard.write(bw, url="u", key_text="k", pubkey="")
    assert not (bw / "user-data").exists(), "nothing was written to it"


def test_a_card_with_no_user_asks_for_one_and_a_bad_name_is_refused(tmp_path):
    boot = _card(tmp_path)
    with pytest.raises(sdcard.KitError, match="no user yet"):
        sdcard.write(boot, url="u", key_text="k", pubkey="")
    with pytest.raises(sdcard.KitError, match="not a user name"):
        sdcard.write(boot, url="u", key_text="k", pubkey="", user="Root Admin")
    r = sdcard.write(boot, url="u", key_text="k", pubkey="ssh-ed25519 A", user="pi")
    u = yaml.safe_load((boot / "user-data").read_text())["users"][0]
    assert r["user"] == "pi" and u["lock_passwd"] is True, "a user made here has no password: key only"


def test_wifi_is_checked_before_anything_is_written(tmp_path):
    for ssid, pw, country, why in (("", "longenough", "GB", "Wi-Fi name"),
                                   ("Home", "short", "GB", "8 to 63"),
                                   ("Home", "longenough", "Britain", "two letters")):
        with pytest.raises(sdcard.KitError, match=why):
            sdcard.network_config(ssid, pw, country)


def test_garbage_user_data_is_refused_not_overwritten(tmp_path):
    boot = _card(tmp_path, user_data="users: [unclosed\n")
    with pytest.raises(sdcard.KitError, match="not valid YAML"):
        sdcard.write(boot, url="u", key_text="k", pubkey="", user="pi")
    assert (boot / "user-data").read_text() == "users: [unclosed\n"


# ---- a person's act ---------------------------------------------------------------------------

def test_there_is_no_agent_tool_that_scans_or_installs():
    from agentos import tools
    names = {t["function"]["name"] if "function" in t else t.get("name") for t in tools.TOOL_SCHEMAS}
    for n in names:
        assert not any(w in (n or "") for w in ("scan", "install_bento", "ssh", "sdcard", "device")), n


def test_the_routes_are_admin_only_and_the_card_is_loopback_only():
    src = (ROOT / "agentos" / "server.py").read_text()
    for route in ("scan", "ignore", "sshkey", "check", "install", "sdcard"):
        i = src.index(f'@app.post("/api/devices/{route}")')
        body = src[i:i + 900]
        assert "_require_admin()" in body, route
    i = src.index('@app.post("/api/devices/sdcard")')
    assert "is_loopback" in src[i:i + 900]


def test_no_ssh_library_is_a_dependency():
    py = (ROOT / "pyproject.toml").read_text().lower()
    for lib in ("paramiko", "asyncssh", "fabric", "pexpect"):
        assert f'"{lib}' not in py, f"{lib} is not permissively licensed or not needed: the system ssh is used"
