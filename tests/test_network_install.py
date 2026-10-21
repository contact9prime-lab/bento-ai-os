"""Installing Bento from the Network tab and from `bento network`, and saying why a login failed.

Reported as "I was able to discover the machine but when I try to install Bento on it, it says
not authenticated; also the bento network command should allow Bento to be installed on it".
Two things came out of it:

  * ssh's refusal lists the ways the other machine takes a login ("Permission denied
    (publickey)"), so a Pi flashed with Imager's "public-key only" is told apart from a wrong
    password, and a wrong password says that new Raspberry Pi OS has no `pi` user.
  * `bento network look` and `bento network install MACHINE` are the terminal's Look at the
    network and Install Bento, on the same code as `bento pool install`, using the SSH port
    the scan found.
"""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import provision, remoteinstall, teamlink        # noqa: E402

ROOT = Path(__file__).parent.parent

# A stand-in `ssh` whose machine takes keys only, or a password, as KEYS_ONLY says.
FAKE = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
here = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
remote, target = args[-1], args[-2]
keys_only = os.path.exists(os.path.join(here, "keys-only"))
ok = False
if os.environ.get("SSH_ASKPASS"):
    pw = subprocess.run([os.environ["SSH_ASKPASS"]], capture_output=True, text=True).stdout.strip()
    ok = pw == "right-one" and not keys_only
with open(os.path.join(here, "calls.jsonl"), "a") as f:
    f.write(json.dumps({"args": args}) + "\n")
if not ok:
    sys.stderr.write(target + ": Permission denied (" + ("publickey" if keys_only else "publickey,password") + ").\n")
    sys.exit(255)
if remote.startswith("echo arch="):
    print("arch=aarch64\nboard=Raspberry Pi 3 Model B Rev 1.2\nos=Debian GNU/Linux 13 (trixie)\n"
          "curl=yes\nbento=no\nfree_kb=20971520\nram_kb=900000")
    sys.exit(0)
print("Bento installer\ndone")
'''


@pytest.fixture()
def pi(tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "ssh").write_text(FAKE)
    (bin_ / "ssh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("AGENTOS_SCAN_NETWORKS", "127.0.0.0/8")
    monkeypatch.setenv("AGENTOS_INSTALL_URL", "https://example.test/install.sh")
    monkeypatch.delenv("AGENTOS_REPO", raising=False)
    with teamlink.at(tmp_path / "home"):
        yield bin_


def test_a_pi_that_takes_keys_only_is_not_called_a_wrong_password(pi):
    (pi / "keys-only").touch()
    with pytest.raises(remoteinstall.InstallError) as e:
        asyncio.run(remoteinstall.check("127.0.0.2", "ada", "right-one"))
    assert "keys only" in str(e.value) and "SSH key" in str(e.value)
    assert "password was refused" not in str(e.value)


def test_a_wrong_password_names_the_imager_user(pi):
    with pytest.raises(remoteinstall.InstallError) as e:
        asyncio.run(remoteinstall.check("127.0.0.2", "pi", "wrong"))
    assert "password was refused" in str(e.value) and "Imager" in str(e.value)


def test_no_password_and_a_key_the_pi_does_not_have_asks_for_the_password():
    said = remoteinstall._why("x: Permission denied (publickey,password).", 255, password=False)
    assert "key is not on that machine" in said and "password" in said.lower()
    said = remoteinstall._why("x: Permission denied (publickey).", 255, password=False)
    assert "keys only" in said
    assert remoteinstall._why("x: Permission denied (publickey).", 255) .startswith("that machine takes SSH keys only")


def test_the_form_does_not_suggest_a_pi_user():
    js = (ROOT / "agentos/ui/src/js/24j-provision.js").read_text() + \
        (ROOT / "agentos/ui/src/js/24n-network.js").read_text()
    assert 'placeholder="pi"' not in js


def _cli(pi, home, *argv, stdin=""):
    env = {**os.environ, "AGENTOS_HOME": str(home), "AGENTOS_VAULT_KEYRING": "0"}
    return subprocess.run([sys.executable, "-m", "agentos", "network", *argv], cwd=ROOT, env=env,
                          input=stdin, capture_output=True, text=True, timeout=120)


def test_bento_network_installs_on_a_listed_machine_with_its_ssh_port(pi, tmp_path):
    home = tmp_path / "home"
    d = provision.load()
    provision.save(d)
    from agentos import netscan
    netscan.remember(d["devices"], {"ip": "127.0.0.2", "ports": [2222], "ssh": True, "mac": "b8:27:eb:01:02:03",
                                    "maker": "Raspberry Pi", "name": "pi3", "os": "", "pi": True,
                                    "seen_by": "port"})
    provision.save(d)
    r = _cli(pi, home, "install", "pi3", "--user", "ada", "--password-stdin", "--yes", stdin="right-one\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Bento is installed on 127.0.0.2" in r.stdout and "Raspberry Pi 3" in r.stdout
    calls = [json.loads(x) for x in (pi / "calls.jsonl").read_text().splitlines()]
    assert all(c["args"][c["args"].index("-p") + 1] == "2222" for c in calls), "the port the scan found"
    assert "right-one" not in json.dumps(calls)
    assert any(e.get("state") == "installed" for e in provision.load()["devices"].values())
    import sqlite3
    acts = [a for (a,) in sqlite3.connect(home / "agentos.db").execute("SELECT action FROM audit")]
    assert "device.install" in acts and "device.installed" in acts


def test_bento_network_install_says_why_a_login_failed(pi, tmp_path):
    (pi / "keys-only").touch()
    r = _cli(pi, tmp_path / "home", "install", "127.0.0.2", "--user", "ada", "--password-stdin", "--yes",
             stdin="right-one\n")
    assert r.returncode != 0 and "keys only" in (r.stdout + r.stderr)


def test_bento_network_lists_look_and_install():
    main = (ROOT / "agentos/__main__.py").read_text()
    r = subprocess.run([sys.executable, "-m", "agentos", "network", "--help"], cwd=ROOT,
                       capture_output=True, text=True, timeout=60)
    assert "look" in r.stdout and "install MACHINE" in r.stdout
    assert 'return _devices_cli(args, cfg, "install"' in main
