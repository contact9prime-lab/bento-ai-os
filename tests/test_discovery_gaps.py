"""A Pi on the network is found, a Zero is its owner's, and a Zero's Office is one person.

Reported as "there is a machine on the network which is a raspi but it is not being
discovered, would it work on ping or ssh based checks". Three gaps, each pinned here:

- the scan counted a machine only when SSH or Bento's port was OPEN, so a Pi with SSH off
  (Imager leaves it off) was invisible. A refused connection means a machine is there, and
  knocking makes the kernel ask the whole segment who is where, so the neighbour table names
  every machine that answered, even one that drops what it does not want. No ping needed.
- the mDNS ear started only on a machine that could LEAD a community, which needs a provider
  model: a hub on Claude Code heard no Pi at all, and did not hear its own Zeros either.
- a scan names what it found over mDNS (a reverse lookup a Pi's avahi answers).

Then "this should not allow any other user to connect, only the logged-in user should be
shown": a Zero is made for the person signed in, by them, and nobody else. And "for the zero
device just show one man in the office flat display".
"""
import asyncio
import ipaddress
import os
import socket
import struct
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import netscan, office, provision, teamlink                       # noqa: E402

ROOT = Path(__file__).parent.parent


def _dead_port(ip: str) -> int:
    s = socket.socket()
    s.bind((ip, 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ---- the scan ---------------------------------------------------------------------------------

def test_a_machine_with_ssh_off_is_found_by_its_refusal(monkeypatch):
    """Both ports shut, nothing listening: the machine refuses, so it is there."""
    port = _dead_port("127.0.0.6")
    monkeypatch.setenv("AGENTOS_SCAN_NETWORKS", "127.0.0.6/32")
    monkeypatch.setenv("AGENTOS_SCAN_PORTS", f"{port}")
    monkeypatch.setenv("AGENTOS_MDNS_TARGET", f"127.0.0.1:{_dead_port('127.0.0.1')}")
    monkeypatch.setattr(netscan, "neighbours", lambda text=None: {"127.0.0.6": "b8:27:eb:12:34:56"})
    got = asyncio.run(netscan.scan([ipaddress.ip_network("127.0.0.6/32")], timeout=0.5))
    assert len(got) == 1, got
    d = got[0]
    assert d["seen_by"] == "refused" and d["ssh"] is False and d["ports"] == []
    assert d["maker"] == "Raspberry Pi" and d["pi"], "a Pi 3's MAC (b8:27:eb) says what it is"
    assert "SSH is off" in netscan.ssh_off_words(d) and "raspi-config" in netscan.ssh_off_words(d)


def test_a_machine_that_answers_nothing_but_the_neighbour_table_is_found(monkeypatch):
    """A firewalled Pi drops every knock, and still answers 'who has this address'."""
    monkeypatch.setenv("AGENTOS_SCAN_NETWORKS", "10.254.254.0/30")
    monkeypatch.setenv("AGENTOS_SCAN_PORTS", "22")
    monkeypatch.setenv("AGENTOS_MDNS_TARGET", f"127.0.0.1:{_dead_port('127.0.0.1')}")

    async def silent(ip, port, timeout, banner_too=False):
        return None, ""
    monkeypatch.setattr(netscan, "_touch", silent)
    monkeypatch.setattr(netscan, "neighbours", lambda text=None: {
        "10.254.254.1": "dc:a6:32:aa:bb:cc",        # asked for in this scan: found
        "192.168.77.9": "dc:a6:32:00:00:01"})       # not in the networks scanned: not ours to list
    got = asyncio.run(netscan.scan([ipaddress.ip_network("10.254.254.0/30")], timeout=0.2))
    assert [(d["ip"], d["seen_by"], d["pi"]) for d in got] == [("10.254.254.1", "arp", True)]


def test_the_neighbour_table_skips_incomplete_entries():
    text = ("IP address       HW type     Flags       HW address            Mask     Device\n"
            "192.168.29.40    0x1         0x2         b8:27:eb:11:22:33     *        wlan0\n"
            "192.168.29.41    0x1         0x0         00:00:00:00:00:00     *        wlan0\n")
    assert netscan.neighbours(text) == {"192.168.29.40": "b8:27:eb:11:22:33"}


def _reverse_answer(ip: str, name: str) -> bytes:
    rname = ".".join(reversed(ip.split("."))) + ".in-addr.arpa"
    enc = lambda n: b"".join(bytes([len(p)]) + p.encode() for p in n.split(".")) + b"\0"  # noqa: E731
    target = enc(name)
    rec = enc(rname) + struct.pack("!HHIH", 12, 0x8001, 120, len(target)) + target
    a = enc(name) + struct.pack("!HHIH", 1, 0x8001, 120, 4) + socket.inet_aton(ip)
    return struct.pack("!6H", 0, 0x8400, 0, 1, 0, 1) + rec + a


def test_a_reverse_answer_names_the_machine():
    got = netscan.parse_reverse(_reverse_answer("192.168.29.40", "pi-garden.local"))
    assert got == {"192.168.29.40": "pi-garden"}
    assert netscan.parse_reverse(b"\x00" * 5) == {}, "somebody else's bytes: nothing, never a crash"


def test_a_scan_asks_the_network_what_each_machine_calls_itself(monkeypatch):
    """One mDNS question for every address found, answered straight back to our port."""
    async def go():
        asked = []

        class Responder(asyncio.DatagramProtocol):
            def connection_made(self, tr):
                self.tr = tr

            def datagram_received(self, data, addr):
                asked.append(data)
                self.tr.sendto(_reverse_answer("192.168.29.40", "pi-garden.local"), addr)
        loop = asyncio.get_running_loop()
        tr, _ = await loop.create_datagram_endpoint(Responder, local_addr=("127.0.0.1", 0))
        monkeypatch.setenv("AGENTOS_MDNS_TARGET", f"127.0.0.1:{tr.get_extra_info('sockname')[1]}")
        got = await netscan.mdns_names(["192.168.29.40", "192.168.29.41", "8.8.8.8"], timeout=0.4)
        tr.close()
        return got, asked
    got, asked = asyncio.run(go())
    assert got == {"192.168.29.40": "pi-garden"}
    assert len(asked) == 1 and b"\x0240\x0229\x03168\x03192\x07in-addr\x04arpa" in asked[0]
    assert b"8\x018\x018\x018" not in asked[0], "a public address is never asked about"


def test_the_ear_never_sends():
    src = (ROOT / "agentos/netscan.py").read_text()
    ear = src[src.index("class MdnsEar"):src.index("def remember(")]
    assert "sendto" not in ear, "listening is passive; only a scan somebody asked for sends"


# ---- who listens ------------------------------------------------------------------------------

def test_a_hub_on_claude_code_still_hears_devices_and_its_zeros(tmp_path):
    with teamlink.at(tmp_path / "home"):
        cc = {"default_model": "claude-code/default", "engine": "claude-code"}
        assert provision.hearing_devices(cc), "the Network tab is not only for a machine that could lead"
        assert not provision.watching(cc), "no provider model to lend and no Zero line: nobody to hear"
        provision.zero_key("")
        assert provision.watching(cc), "it handed out a Zero line, so it listens for the Zeros"
        d = provision.load()
        d["watch"] = False
        provision.save(d)
        assert not provision.hearing_devices(cc) and not provision.watching(cc), "the admin said no"


def test_a_zero_leaves_hearing_to_its_hub(tmp_path):
    with teamlink.at(tmp_path / "home"):
        z = {"zero": {"hub": "big-box", "execution": "hub"}}
        assert not provision.hearing_devices(z)


def test_the_server_starts_the_ear_on_its_own_answer():
    srv = (ROOT / "agentos/server.py").read_text()
    sync = srv[srv.index("async def _provision_sync"):srv.index("def _device_heard")]
    assert "provmod.hearing_devices(cfg)" in sync
    watch_branch = sync[sync.index("if want_watch and not watch:"):sync.index("want_ear")]
    assert "MdnsEar" not in watch_branch, "the ear no longer waits on being able to lead"


# ---- a Zero is its owner's ---------------------------------------------------------------------

@pytest.fixture()
def accounts(monkeypatch):
    from agentos import server
    people = {"u-ada": {"id": "u-ada", "name": "ada"}, "u-bob": {"id": "u-bob", "name": "bob"}}
    me = {"id": "u-bob"}
    monkeypatch.setattr(server.usersmod, "enabled", lambda: True)
    monkeypatch.setattr(server.usersmod, "current", lambda: me["id"])
    monkeypatch.setattr(server.usersmod, "get", lambda uid: people.get(uid))
    monkeypatch.setattr(server.usersmod, "by_name", lambda n: next(
        (p for p in people.values() if p["name"] == n), None))
    return server, me


def test_a_zero_is_made_for_the_person_signed_in_and_nobody_else(accounts):
    server, me = accounts
    assert server._zero_for("") == ("u-bob", "")
    assert server._zero_for("bob") == ("u-bob", ""), "naming yourself is fine"
    assert server._zero_for("u-bob") == ("u-bob", "")
    owner, err = server._zero_for("ada")
    assert owner is None and "only for them" in err, "not for another account, admin or not"
    assert server._zero_for("nobody")[0] is None
    me["id"] = "u-ada"
    assert server._zero_for("bob")[0] is None and server._zero_for("")[0] == "u-ada"


def test_the_page_offers_no_list_of_other_people():
    js = (ROOT / "agentos/ui/src/js/24j-provision.js").read_text()
    assert "zero-for" not in js and "v.accounts" not in js
    assert "esc(mine)" in js, "the account's name is escaped where it is shown"
    srv = (ROOT / "agentos/server.py").read_text()
    view = srv[srv.index("def _provision_view"):srv.index("def _device_rows")]
    assert "list_users()" not in view, "the other accounts are not sent to the page"
    route = srv[srv.index('@app.post("/api/provision/zero")'):srv.index('@app.post("/api/provision/ignore")')]
    assert "_require_admin()" not in route and "sign in to make a Zero" in route, \
        "anyone signed in makes their own; setting up other machines stays an admin's"


# ---- a Zero's office ---------------------------------------------------------------------------

def test_a_zeros_office_is_one_person_drawn_flat(tmp_path):
    from agentos.memory import Store
    store = Store(tmp_path / "a.db")
    store.save_subagent({"name": "researcher", "soul": "finds things"})
    cfg = {"agent_name": "Aria", "office": {"look": "3d", "pet": "cat", "lounge": True, "meeting": True},
           "zero": {"hub": "big-box", "execution": "hub"}}
    v = office.view(cfg, store)
    assert v["zero"] and v["buddy"]
    assert [r["kind"] for r in v["rooms"]] == ["lead"], "one desk: no floor, meeting room or lounge"
    assert v["office"]["look"] == "flat" and v["office"]["pet"] == "none"
    assert cfg["office"]["look"] == "3d", "what is drawn changes; the saved plan does not"
    plain = office.view({**cfg, "zero": {}}, store)
    assert not plain["zero"] and "lounge" in [r["kind"] for r in plain["rooms"]]
    js = (ROOT / "agentos/ui/src/js/24k-office3d.js").read_text()
    want = js[js.index("function of3Wanted"):js.index("function of3GL")]
    assert want.index("if(v.zero)return false") < want.index("of3HQ()"), "not even the HQ scene is 3D"


def test_a_quiet_scan_does_not_take_ssh_away():
    """Found on the owner's Pi: one scan where its Wi-Fi dropped saw it only by ARP, wrote
    ssh: False over the knock that had found port 22, and the row lost its Install button."""
    from agentos import netscan
    seen: dict = {}
    mac = "b8:27:eb:56:2d:48"
    netscan.remember(seen, {"ip": "192.168.1.9", "mac": mac, "ports": [22], "ssh": True, "seen_by": "port"})
    netscan.remember(seen, {"ip": "192.168.1.9", "mac": mac, "ports": [], "ssh": False, "seen_by": "arp"})
    assert seen[mac]["ssh"] is True and seen[mac]["ports"] == [22]
    # a refusal is an answer: SSH really is closed now
    netscan.remember(seen, {"ip": "192.168.1.9", "mac": mac, "ports": [], "ssh": False, "seen_by": "refused"})
    assert seen[mac]["ssh"] is False


def test_a_removed_machine_with_a_working_login_offers_install_again():
    src = (Path(__file__).resolve().parents[1] / "agentos/ui/src/js/24n-network.js").read_text()
    assert "(r.ssh||r.user)" in src
