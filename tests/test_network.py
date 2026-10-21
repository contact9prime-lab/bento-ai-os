"""Settings → Network: one inventory of the machines on this network, Secure it, Disconnect.

Asked for as "the discovery of the devices should be another tab … it should install and also
make sure it maintains the inventory and secures the box too", then "you should also be able
to remove the connections". What these defend:

- the inventory is ONE row per machine, folded from what a scan heard, Bento machines waiting
  or set up, links and community members, by MAC, address and certificate;
- "secured" is what was measured on the machine, never that a run finished;
- what runs is what was shown, the password never reaches a command line, and sudo gets it on
  stdin only when sudo needs it;
- password logins go off only after this machine's key got in ON ITS OWN, and every later step
  logs in with the key;
- the firewall is its own nftables table, refuses to lock out the login doing it, and undoes
  itself unless a NEW login proves Bento still gets in;
- Disconnect takes this machine's key off, but never when it is the only way in.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import harden, inventory, provision, teamlink              # noqa: E402

ROOT = Path(__file__).parent.parent

# A stand-in `ssh` playing a Pi. Its state is a JSON file; each step the real script would run
# changes the state it stands for, so a later check reads what an earlier step did.
FAKE_SSH = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__))
st_path = os.path.join(here, "machine.json")
st = json.load(open(st_path))
args = sys.argv[1:]
remote = args[-1]
stdin = "" if sys.stdin.isatty() else sys.stdin.read()
via = "password" if os.environ.get("SSH_ASKPASS") else "key"
if via == "password":
    pw = subprocess.run([os.environ["SSH_ASKPASS"]], capture_output=True, text=True).stdout.strip()
    ok = pw == st["password"] and not st["passwords_off"]
else:
    ok = "-i" in args and st["authorized"] and not st.get("key_broken")
with open(os.path.join(here, "calls.jsonl"), "a") as f:
    f.write(json.dumps({"args": args, "remote": remote, "via": via, "stdin": stdin, "ok": ok}) + "\n")
if st.get("reloading", 0) > 0:
    st["reloading"] -= 1; json.dump(st, open(st_path, "w"))
    with open(os.path.join(here, "calls.jsonl"), "a") as f:
        f.write(json.dumps({"args": args, "remote": remote, "via": via, "stdin": "", "ok": False, "refused": True}) + "\n")
    sys.stderr.write("ssh: connect to host 127.0.0.2 port 22: Connection refused\n")
    sys.exit(255)
if not ok:
    sys.stderr.write("pi@host: Permission denied (publickey,password).\n")
    sys.exit(255)
yes = lambda b: "ok" if b else "no"
def save():
    json.dump(st, open(st_path, "w"))
needs_pw = not st["sudo_nopw"]
def sudo_ok():
    if "sudo -n " in remote and needs_pw:
        sys.stderr.write("sudo: a password is required\n"); sys.exit(1)
    if "sudo -S " in remote and stdin.strip() != st["password"]:
        sys.stderr.write("sudo: incorrect password\n"); sys.exit(1)
if remote.startswith("echo key="):
    print("key=" + yes(st["authorized"]))
    print("passwords=" + yes(st["passwords_off"]))
    print("firewall=" + yes(st["firewall"]))
    print("updates=" + yes(st["updates"]))
    print("sudo=" + yes(st["sudo_nopw"]))
    print("apt=ok")
elif "echo ours=" in remote:
    print("ours=" + ("1" if st["authorized"] else "0"))
    print("others=" + str(st.get("other_keys", 0)))
    print("pwoff=" + ("yes" if st["passwords_off"] else "no"))
elif "mktemp ~/.ssh/.ak" in remote:
    st["authorized"] = False; save()
elif remote.startswith("umask 077") and "authorized_keys" in remote:
    st["authorized"] = True; save()
elif remote == "true":
    pass
elif "/etc/ssh/sshd_config.d/10-bento.conf" in remote:
    sudo_ok(); st["passwords_off"] = True; st["reloading"] = st.get("refuse_after_reload", 0); save()
elif "bento-firewall.nft" in remote and "nft -f" in remote:
    sudo_ok(); st["firewall"] = True; st["fw_kept"] = False; save()
    print("firewall on; it switches itself off in 90s unless Bento can still log in")
elif "touch /run/bento-firewall-ok" in remote:
    sudo_ok(); st["fw_kept"] = True; save()
elif "unattended-upgrades" in remote:
    sudo_ok(); st["updates"] = True; save()
else:
    sys.stderr.write("unexpected: " + remote[:80] + "\n"); sys.exit(9)
'''


@pytest.fixture()
def pi(tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    ssh = bin_ / "ssh"
    ssh.write_text(FAKE_SSH)
    ssh.chmod(0o755)
    keygen = bin_ / "ssh-keygen"          # the pinned host key is not what these tests read
    keygen.write_text("#!/bin/sh\nexit 0\n")
    keygen.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("AGENTOS_SCAN_NETWORKS", "127.0.0.0/8")
    monkeypatch.setenv("BENTO_SSH_PASSWORD", "leaked-from-the-parent")
    state = {"password": "raspberry-1", "authorized": False, "passwords_off": False, "firewall": False,
             "updates": False, "sudo_nopw": True}
    (bin_ / "machine.json").write_text(json.dumps(state))
    home = tmp_path / "home"
    with teamlink.at(home):
        kp = home / "pki" / "ssh_ed25519"
        kp.parent.mkdir(parents=True, exist_ok=True)
        kp.write_text("PRIVATE")
        Path(str(kp) + ".pub").write_text("ssh-ed25519 AAAAC3Nza-this-machine bento@lead")
        yield bin_


def _calls(bin_):
    return [json.loads(x) for x in (bin_ / "calls.jsonl").read_text().splitlines()]


def _state(bin_):
    return json.loads((bin_ / "machine.json").read_text())


def _set(bin_, **kw):
    st = _state(bin_)
    st.update(kw)
    (bin_ / "machine.json").write_text(json.dumps(st))


def run(c):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(c)


# ---- what runs is what was shown --------------------------------------------------------------

def test_the_plan_is_the_commands_that_run(pi):
    shown = {p["id"]: p["runs"] for p in harden.plan(None, ssh_port=2222)}
    assert list(shown) == ["key", "passwords", "firewall", "updates"], "the order is the safe order"
    run(harden.secure("127.0.0.2", "pi", "raspberry-1", 2222))
    sent = [c["remote"] for c in _calls(pi)]
    for sid, cmd in shown.items():
        assert cmd in sent, f"{sid} ran something other than what was shown"


def test_the_password_never_reaches_a_command_line(pi):
    _set(pi, sudo_nopw=False)
    run(harden.secure("127.0.0.2", "pi", "raspberry-1"))
    for c in _calls(pi):
        assert "raspberry-1" not in " ".join(c["args"]), "a password on a command line is in ps"
        assert "leaked-from-the-parent" not in c["stdin"]
    # sudo needed it, so it went on stdin, and only to the steps that run as root
    root = [c for c in _calls(pi) if "sudo -S" in c["remote"]]
    assert root and all(c["stdin"] == "raspberry-1\n" for c in root)
    assert not any(c["stdin"] for c in _calls(pi) if c["remote"].startswith("umask 077"))


def test_with_sudo_needing_nothing_no_password_is_sent_to_it(pi):
    run(harden.secure("127.0.0.2", "pi", "raspberry-1"))
    assert not any(c["stdin"] for c in _calls(pi)), "sudo -n needs no password on stdin"
    assert any("sudo -n sh -c" in c["remote"] for c in _calls(pi))


# ---- the order that cannot lock anybody out ---------------------------------------------------

def test_passwords_go_off_only_after_the_key_got_in_on_its_own(pi):
    got = run(harden.secure("127.0.0.2", "pi", "raspberry-1"))
    assert got["ran"] == ["key", "passwords", "firewall", "updates"]
    assert all(got["done"].values()), got["done"]
    calls = _calls(pi)
    i_pw = next(i for i, c in enumerate(calls) if c["remote"].startswith("sudo") and "10-bento.conf" in c["remote"])
    proof = calls[i_pw - 1]
    assert proof["remote"] == "true" and proof["via"] == "key" and proof["ok"], \
        "a login with the key alone came right before password logins went off"
    # every login after that is with the key: a password login is refused from then on
    assert all(c["via"] == "key" for c in calls[i_pw + 1:])
    # and the first thing after the reload is a key-only login, waited for: sshd re-executes
    assert calls[i_pw + 1]["remote"] == "true" and calls[i_pw + 1]["via"] == "key"


def test_a_reload_that_is_slow_to_answer_is_waited_for(pi, monkeypatch):
    """Found by the live run: right after the reload sshd refused the firewall step's login."""
    monkeypatch.setattr(harden, "RELOAD_WAIT_S", 0.01)
    _set(pi, refuse_after_reload=2)
    got = run(harden.secure("127.0.0.2", "pi", "raspberry-1"))
    assert got["ran"] == ["key", "passwords", "firewall", "updates"]
    refused = [c for c in _calls(pi) if c.get("refused")]
    assert len(refused) == 2, "two refusals, then it got in and carried on"


def test_a_key_that_does_not_get_in_leaves_password_logins_on(pi):
    _set(pi, key_broken=True)
    with pytest.raises(Exception) as e:
        run(harden.secure("127.0.0.2", "pi", "raspberry-1"))
    assert "password logins were left on" in str(e.value)
    assert _state(pi)["passwords_off"] is False and _state(pi)["authorized"] is True


def test_the_firewall_is_kept_only_by_a_new_login(pi):
    run(harden.secure("127.0.0.2", "pi", "raspberry-1", steps=["key", "firewall"]))
    calls = _calls(pi)
    i = next(i for i, c in enumerate(calls) if "nft -f" in c["remote"])
    assert "touch /run/bento-firewall-ok" in calls[i + 1]["remote"], "a fresh login stops the undo timer"
    assert _state(pi)["fw_kept"] is True
    script = next(c["remote"] for c in calls if "nft -f" in c["remote"])
    assert "sleep 90" in script and "nft delete table inet bento" in script, "it undoes itself unless kept"
    assert "SSH_CLIENT" in script and "exit 4" in script, "it refuses to drop the address doing it"


def test_the_firewall_is_its_own_table_and_keeps_the_doors(pi):
    rules = harden.nft_rules(2222)
    assert rules.startswith("table inet bento\ndelete table inet bento\n"), "loading twice is loading once"
    assert "policy drop" in rules and "ct state established,related accept" in rules
    for net in harden.PRIVATE:
        assert net in rules
    for port in ("2222", "8321", "8322", "8620", "5353", "68"):
        assert port in rules, port
    assert 'iifname "tailscale0" accept' in rules
    assert "flush ruleset" not in rules, "a person's own rules, and Docker's, are left alone"


@pytest.mark.skipif(not shutil.which("nft"), reason="no nftables here")
def test_nftables_accepts_the_rules(tmp_path):
    f = tmp_path / "bento.nft"
    f.write_text(harden.nft_rules(22))
    r = subprocess.run(["nft", "-c", "-f", str(f)], capture_output=True, text=True)
    if r.returncode and ("Operation not permitted" in r.stderr or "permission" in r.stderr.lower()):
        pytest.skip("nft -c needs privileges here")
    assert r.returncode == 0, r.stderr


def test_a_step_already_in_place_is_not_run_again(pi):
    _set(pi, authorized=True, updates=True)
    got = run(harden.secure("127.0.0.2", "pi", "raspberry-1"))
    assert got["ran"] == ["passwords", "firewall"]
    assert not any(c["remote"].startswith("sudo") and "unattended-upgrades" in c["remote"] for c in _calls(pi))


def test_a_check_where_passwords_are_off_gets_in_with_the_key(pi):
    _set(pi, authorized=True, passwords_off=True)
    c = run(harden.check("127.0.0.2", "pi", "raspberry-1"))
    assert c["login"] == "key" and c["done"]["passwords"] is True


def test_sudo_needing_a_password_that_was_not_given_is_said(pi):
    _set(pi, sudo_nopw=False, authorized=True)
    c = run(harden.check("127.0.0.2", "pi", ""))
    assert any("needs a password for sudo" in p for p in c["problems"])
    with pytest.raises(Exception) as e:
        run(harden.secure("127.0.0.2", "pi", ""))
    assert "needs a password for sudo" in str(e.value)


def test_only_a_machine_on_this_network(pi, monkeypatch):
    monkeypatch.delenv("AGENTOS_SCAN_NETWORKS")
    with pytest.raises(Exception) as e:
        run(harden.check("8.8.8.8", "pi", "x"))
    assert "this network" in str(e.value)
    assert not (pi / "calls.jsonl").exists()


# ---- Disconnect: this machine's key -----------------------------------------------------------

def test_taking_the_key_off_is_refused_when_it_is_the_only_way_in(pi):
    _set(pi, authorized=True, passwords_off=True, other_keys=0)
    with pytest.raises(Exception) as e:
        run(harden.remove_key("127.0.0.2", "pi"))
    assert "nobody able to log in" in str(e.value)
    assert _state(pi)["authorized"] is True
    got = run(harden.remove_key("127.0.0.2", "pi", force=True))
    assert got["removed"] and _state(pi)["authorized"] is False


def test_taking_the_key_off_with_another_way_in(pi):
    _set(pi, authorized=True, passwords_off=True, other_keys=1)
    assert run(harden.remove_key("127.0.0.2", "pi"))["removed"]
    assert _state(pi)["authorized"] is False
    with pytest.raises(Exception) as e:          # gone for real: this machine's key no longer gets in
        run(harden.check("127.0.0.2", "pi"))
    assert "refused" in str(e.value)


# ---- the inventory: one row per machine -------------------------------------------------------

def test_the_inventory_folds_every_source_into_one_row(tmp_path):
    home = tmp_path / "home"
    with teamlink.at(home):
        d = provision.load()
        d["devices"]["dc:a6:32:00:00:01"] = {"ip": "192.168.1.40", "mac": "dc:a6:32:00:00:01",
                                              "maker": "Raspberry Pi", "ssh": True, "ports": [22],
                                              "first": 1, "last": 100, "state": "installed"}
        d["seen"]["fp-kitchen"] = {"name": "pi-kitchen", "addr": "192.168.1.40", "state": "enabled",
                                   "hw": {"board": "Raspberry Pi 5"}, "last": 200, "first": 50}
        provision.save(d)
        inventory.note_security("192.168.1.40", "dc:a6:32:00:00:01",
                                {"key": True, "passwords": True, "firewall": False, "updates": True}, "pi")
        rows = inventory.rows()
        assert len(rows) == 1, rows
        r = rows[0]
        assert r["name"] == "pi-kitchen" and r["board"] == "Raspberry Pi 5" and r["maker"] == "Raspberry Pi"
        assert r["bento"] == "set up" and r["user"] == "pi"
        assert r["security_words"] == "3 of 4 in place", "what was measured, in words"
        assert [c["kind"] for c in r["connections"]] == ["key"]
        inventory.set_label("192.168.1.40", "dc:a6:32:00:00:01", "Kitchen‮ Pi")
        r = inventory.rows()[0]
        assert r["display"] == "Kitchen Pi", "a label is plain text"
        assert inventory.find(inventory.rows(), "kitchen pi")["key"] == r["key"]


def test_a_machine_heard_by_address_then_by_mac_is_one_note(tmp_path):
    with teamlink.at(tmp_path / "home"):
        inventory.record("192.168.1.9", user="pi")
        inventory.record("192.168.1.9", "AA:BB:CC:00:00:09", label="garage")
        d = inventory.load()["devices"]
        assert list(d) == ["aa:bb:cc:00:00:09"] and d["aa:bb:cc:00:00:09"]["user"] == "pi"


def test_unchecked_is_said_never_guessed(tmp_path):
    with teamlink.at(tmp_path / "home"):
        d = provision.load()
        d["devices"]["10.0.0.5"] = {"ip": "10.0.0.5", "ssh": True, "last": 1, "first": 1}
        provision.save(d)
        r = inventory.rows()[0]
        assert r["security_words"] == "not checked" and r["secured_n"] == -1 and r["bento"] == "none"


# ---- every face -------------------------------------------------------------------------------

def test_every_face_has_it():
    srv = (ROOT / "agentos/server.py").read_text()
    for route in ('@app.get("/api/network")', '@app.post("/api/network/check")',
                  '@app.post("/api/network/secure")', '@app.post("/api/network/disconnect")',
                  '@app.post("/api/network/label")', '@app.post("/api/network/forget")'):
        assert route in srv, route
        body = srv[srv.index(route):srv.index("\n@app.", srv.index(route) + 5)]
        assert "_require_admin()" in body, f"{route} reaches other machines: admin only"
    for row in ('"device.check"', '"device.secure"', '"device.secured"', '"device.secure_failed"',
                '"device.disconnect"', '"device.forget"'):
        assert row in srv, f"{row} is a ledger row"
    main = (ROOT / "agentos/__main__.py").read_text()
    assert 'verb("network"' in main and "def _network_cli" in main
    js = (ROOT / "agentos/ui/src/js/24n-network.js").read_text()
    for piece in ("/api/network/check", "/api/network/secure", "/api/network/disconnect",
                  "What runs there", "osConfirm", "provDevForm"):
        assert piece in js, piece
    zero = (ROOT / "agentos/ui/src/js/00k-zeroface.js").read_text()
    assert "'network'" in zero, "a Zero's network is its hub's business"
