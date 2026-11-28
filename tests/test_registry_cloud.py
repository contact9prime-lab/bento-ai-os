"""The Bento Registry client (agentos/registryhub.py) against a stand-in registry.

The registry's server (Supabase migrations, the publish and download functions) is in
the website repo, bento-box-os-com, under supabase/. Its tools/check_registry.py checks
that its leak rules equal agentbundle._LEAK_RULES and its reserved names equal
registryhub.RESERVED.

Nothing here reaches the network: `_call` and `_fetch_bytes` are replaced by a
fake that keeps what was published, so the same signature the real `publish`
function checks is checked here on the way back.
"""

import base64
import hashlib
import json
import re
from pathlib import Path

import pytest

from agentos import agentbundle, registryhub as hub

ROOT = Path(__file__).resolve().parent.parent


class FakeHub:
    def __init__(self):
        self.calls = []
        self.files = {}
        self.machines = {}
        self.versions = {}
        self.profile = None

    def __call__(self, method, path, body=None, token="", headers=None, raw=False):
        self.calls.append((method, path.split("?")[0]))
        if path.startswith("/auth/v1/otp"):
            return {}
        if path.startswith("/auth/v1/verify") or path.startswith("/auth/v1/token"):
            return {"access_token": "acc", "refresh_token": "ref-secret", "expires_in": 3600,
                    "user": {"id": "u1"}}
        if path.startswith("/auth/v1/logout"):
            return {}
        if path.startswith("/rest/v1/profiles") and method == "GET":
            return [self.profile] if self.profile else []
        if path.startswith("/rest/v1/profiles"):
            self.profile = {"handle": body["handle"]}
            return None
        if path.startswith("/rest/v1/machines") and method == "GET":
            kid = path.split("key_id=eq.")[1]
            return [self.machines[kid]] if kid in self.machines else []
        if path.startswith("/rest/v1/machines") and method == "POST":
            self.machines[body["key_id"]] = {"key_id": body["key_id"], "public_key": body["public_key"],
                                            "revoked_at": None}
            return None
        if path.startswith("/functions/v1/publish"):
            data = body["package"].encode()
            m = self.machines[body["key_id"]]
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            Ed25519PublicKey.from_public_bytes(base64.b64decode(m["public_key"])).verify(
                base64.b64decode(body["signature"]), ("sha256:" + hashlib.sha256(data).hexdigest()).encode())
            url = f"{hub.HUB_URL}/storage/v1/object/public/packages/{body['kind']}/{body['slug']}/{body['version']}.json"
            self.files[url] = data
            self.versions[(body["kind"], body["slug"])] = {
                "url": url, "sha256": hashlib.sha256(data).hexdigest(), "key_id": body["key_id"],
                "signature": body["signature"], "publisher_key": m["public_key"], "publisher": "ada",
                "version": body["version"], "name": body["name"], "revoked": False}
            return {"ok": True, "version": body["version"], "page": "x"}
        if path.startswith("/functions/v1/download"):
            q = dict(p.split("=") for p in path.split("?")[1].split("&"))
            return dict(self.versions[(q["kind"], q["slug"])])
        raise AssertionError(f"unexpected call {method} {path}")

    def fetch(self, url):
        return self.files[url]


@pytest.fixture
def fake(monkeypatch, tmp_path):
    f = FakeHub()
    monkeypatch.setattr(hub, "_call", f)
    monkeypatch.setattr(hub, "_fetch_bytes", f.fetch)
    monkeypatch.setattr(hub, "home", lambda: tmp_path)
    hub._ACCESS.clear()
    return f


def _signed_in(fake):
    hub.start_login("ada@example.org")
    hub.finish_login("123456")
    hub.set_handle("ada")
    hub.register_machine("test box")



def test_a_credential_blocks_and_personal_details_are_shown():
    pkg = {"format": hub.KINDS["skill"], "name": "x",
           "content": "call me on +44 7700 900123, ada@acme-corp.io, files in /home/ada/work, "
                      "box at 192.168.1.20, key sk-ant-abcdefghijklmnop1234"}
    text = hub.text_of(pkg)
    rep = hub.report("skill", text, pkg)
    assert not rep["ok"] and rep["verdict"] == "blocked"
    assert [b["what"] for b in rep["blocking"]] == ["an Anthropic API key"]
    seen = {w["what"] for w in rep["warnings"]}
    assert {"an email address", "a phone number", "a home folder", "a private network address"} <= seen
    assert rep["ack"] == hashlib.sha256(text.encode()).hexdigest()
    # the excerpt never repeats the whole thing
    assert all("acme-corp" not in w["excerpt"] for w in rep["warnings"])


def test_example_addresses_are_not_personal():
    pkg = {"format": hub.KINDS["soul"], "name": "s", "content": "write to someone@example.com"}
    rep = hub.report("soul", hub.text_of(pkg), pkg)
    assert rep["ok"] and not [w for w in rep["warnings"] if w["what"] == "an email address"]


def test_publish_stops_before_the_network(fake):
    pkg = {"format": hub.KINDS["skill"], "name": "x", "content": "ghp_" + "a" * 30}
    text = hub.text_of(pkg)
    with pytest.raises(hub.HubError, match="won't be published"):
        hub.publish("skill", "xx", "1.0.0", text, ack=hub.report("skill", text)["ack"])
    clean = hub.text_of({"format": hub.KINDS["skill"], "name": "x", "content": "hello"})
    with pytest.raises(hub.HubError, match="look at the report"):
        hub.publish("skill", "xx", "1.0.0", clean, ack="not-this")
    with pytest.raises(hub.HubError, match="sign in"):
        hub.publish("skill", "xx", "1.0.0", clean, ack=hub.report("skill", clean)["ack"])
    assert fake.calls == []


def test_the_session_is_in_the_vault_not_the_file(fake, tmp_path):
    from agentos import vault
    _signed_in(fake)
    st = hub.status()
    assert st["signed_in"] and st["handle"] == "ada" and st["registered"] and st["can_publish"]
    assert st["email"].startswith("ad…@")
    on_disk = (tmp_path / "registry" / "hub.json").read_text()
    assert "ref-secret" not in on_disk
    assert vault.get(hub.VAULT_NAME) == "ref-secret"
    assert (tmp_path / "registry" / "machine.key").stat().st_mode & 0o077 == 0
    hub.logout()
    assert not hub.status()["signed_in"]
    assert not vault.has(hub.VAULT_NAME)


def test_published_bytes_come_back_checked(fake):
    _signed_in(fake)
    pkg = {"format": hub.KINDS["skill"], "name": "Tables", "description": "d", "content": "# read tables"}
    text = hub.text_of(pkg)
    hub.publish("skill", "tables", "1.0.0", text, ack=hub.report("skill", text)["ack"], name="Tables")
    got = hub.fetch("skill", "tables", cfg={})
    assert got["package"] == pkg and got["pin_status"] == "first-install"
    cfg = hub.pin({}, got)
    assert hub.fetch("skill", "tables", cfg=cfg)["pin_status"] == "match"

    # a changed byte on the way is refused
    url = fake.versions[("skill", "tables")]["url"]
    fake.files[url] = fake.files[url].replace(b"read", b"rm -rf")
    with pytest.raises(hub.HubError, match="doesn't match"):
        hub.fetch("skill", "tables")

    # a record re-hashed to match tampered bytes still fails the signature
    fake.versions[("skill", "tables")]["sha256"] = hashlib.sha256(fake.files[url]).hexdigest()
    with pytest.raises(hub.HubError, match="signature"):
        hub.fetch("skill", "tables")


def test_a_file_from_anywhere_else_is_refused():
    with pytest.raises(hub.HubError, match="outside its own storage"):
        hub._fetch_bytes("https://evil.example/packages/x.json")


def test_names_and_versions_are_read_strictly():
    assert hub.parse_ref("app/hello-notes@1.2") == ("app", "hello-notes", "1.2")
    for bad in ("hello", "plugin/x", "app/../x", "app/X"):
        with pytest.raises(hub.HubError):
            hub.parse_ref(bad)
    assert hub.slug_of("My Great App!") == "my-great-app"



def test_the_desktop_publishes_the_bytes_it_reported(fake, tmp_path):
    """The page sends the report's hash, never the package: what was read is what goes."""
    from fastapi.testclient import TestClient

    from agentos import server as servermod
    _signed_in(fake)
    with TestClient(servermod.app) as c:
        st = servermod.state["store"]
        st.save_skill("Reg Tables", "reads tables", "# tables\nwrite to me: ada@acme-corp.io")
        rep = c.post("/api/store/registry/report", json={"kind": "skill", "item": "Reg Tables"}).json()
        assert rep["ok"] and rep["warnings"] and rep["slug"] == "reg-tables"
        # personal details: not without the tick
        r = c.post("/api/store/registry/publish", json={"ack": rep["ack"], "slug": "reg-tables", "version": "1.0.0"})
        assert r.status_code == 400 and "tick" in r.json()["error"]
        # a hash the server never reported on
        r = c.post("/api/store/registry/publish", json={"ack": "0" * 64, "slug": "reg-tables",
                                                        "version": "1.0.0", "understood": True})
        assert r.status_code == 409
        r = c.post("/api/store/registry/publish", json={"ack": rep["ack"], "slug": "reg-tables",
                                                        "version": "1.0.0", "understood": True})
        assert r.json()["ok"], r.json()
        sent = fake.files[fake.versions[("skill", "reg-tables")]["url"]].decode()
        assert sent == rep["preview"][:len(sent)] and "Reg Tables" in sent

        # getting it back: checked, shown, and it never replaces the skill that is here
        got = c.post("/api/store/registry/get", json={"ref": "skill/reg-tables"}).json()
        assert got["preview"]["exists"] is True and got["publisher"] == "ada"
        r = c.post("/api/store/registry/install", json={"sha256": got["sha256"]})
        assert r.status_code == 409 and "left as it is" in r.json()["error"]
        st.delete_skill(st.get_skill("Reg Tables")["id"])
        got = c.post("/api/store/registry/get", json={"ref": "skill/reg-tables"}).json()
        r = c.post("/api/store/registry/install", json={"sha256": got["sha256"]}).json()
        assert r["ok"] and st.get_skill("Reg Tables")["source"] == "bento-registry:skill/reg-tables@1.0.0"
        st.delete_skill(st.get_skill("Reg Tables")["id"])


def _refusing(monkeypatch, tmp_path, msg, status):
    def call(method, path, body=None, token="", headers=None, raw=False):
        raise hub.HubError(msg, status, {})
    monkeypatch.setattr(hub, "_call", call)
    monkeypatch.setattr(hub, "home", lambda: tmp_path)


@pytest.mark.parametrize("msg,status,said", [
    ("Error sending confirmation email", 500, "couldn't send the email"),
    ("Error sending magic link email", 500, "couldn't send the email"),
    ("email rate limit exceeded", 429, "too many sign-in codes"),
    ("For security purposes, you can only request this after 42 seconds.", 429, "a code was just sent"),
])
def test_a_code_that_was_not_sent_says_why(monkeypatch, tmp_path, msg, status, said):
    """Reported as "the email comes but there is no code" with nothing on screen saying why."""
    _refusing(monkeypatch, tmp_path, msg, status)
    with pytest.raises(hub.HubError) as e:
        hub.start_login("ada@example.org")
    assert said in str(e.value)
    assert msg in str(e.value), "the registry's own words are kept for whoever runs it"


def test_a_wrong_code_says_ask_for_a_new_one(monkeypatch, tmp_path):
    _refusing(monkeypatch, tmp_path, "Token has expired or is invalid", 403)
    with pytest.raises(hub.HubError) as e:
        hub.finish_login("123456", "ada@example.org")
    assert "wrong or has expired" in str(e.value)


def test_the_sign_in_card_keeps_its_error_and_never_sends_an_email_as_a_code():
    js = (ROOT / "agentos/ui/src/js/25b-registry.js").read_text()
    assert 'class="reg-err" role="alert"' in js
    assert "REG.err = 'The code was not sent: '" in js
    assert "That is your email" in js
