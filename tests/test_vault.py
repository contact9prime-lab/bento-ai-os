"""The vault: a secret is stored encrypted, referenced from config, read only by
the code that needs it, and never handed back by any route or verb.

What these defend: the bytes on disk are not the secret; config holds a
reference after a save and after adoption; the mailbox code still gets the
password; `/api/config` and the accounts card say "in the vault" and nothing
more; the key mechanism is decided once and reported honestly; a vault whose
keyring has gone is LOCKED rather than silently re-keyed.
"""

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ["AGENTOS_VAULT_KEYRING"] = "0"          # no D-Bus in a test run

from agentos import accounts, calendars, config as cfgmod, mail as mailmod, vault   # noqa: E402


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    return tmp_path


def test_a_secret_round_trips_and_the_file_never_holds_it(home):
    ref = vault.put("mail.password", "hunter2-app-pass")
    assert ref == "vault:mail.password" and vault.is_ref(ref)
    raw = (home / "vault.json").read_bytes()
    assert b"hunter2" not in raw                                   # encrypted, not encoded
    assert stat.S_IMODE((home / "vault.json").stat().st_mode) == 0o600
    # the machine's vault is locked with the service key (away.py), a 0600 file with no keyring
    assert stat.S_IMODE((home / "away.key").stat().st_mode) == 0o600 and not (home / "vault.key").exists()
    assert vault.get(ref) == "hunter2-app-pass"
    assert vault.get("mail.password") == "hunter2-app-pass"       # by name too
    assert vault.resolve("literal") == "literal"                   # an un-adopted value passes through
    assert vault.resolve(ref) == "hunter2-app-pass"
    assert vault.names() == ["mail.password"] and vault.has(ref)
    assert vault.forget("mail.password") and not vault.has(ref) and vault.get(ref) == ""
    assert not vault.forget("mail.password")


def test_every_read_is_written_down_with_who_it_was_for(home):
    seen = []
    vault.set_reader_log(lambda n, a: seen.append((n, a)))
    try:
        ref = vault.put("calendar.password", "x")
        vault.get(ref, actor="calendar")
        assert seen == [("calendar.password", "calendar")]
    finally:
        vault.set_reader_log(None)


def test_status_says_what_protects_it_and_nothing_more(home):
    st = vault.status()
    assert st["mechanism"] == "" and "Empty" in st["detail"]
    vault.put("a", "sekrit-value")
    st = vault.status()
    assert st["mechanism"] == "service" and st["count"] == 1 and "service key" in st["detail"]
    assert "Root" in st["detail"]                       # what it does not protect against, said
    assert "a" in st["names"] and "sekrit" not in json.dumps(st)


def test_a_keyring_keyed_vault_is_locked_when_the_keyring_is_gone_never_rekeyed(home, monkeypatch, tmp_path):
    # a fake secret-tool on PATH: stores and looks up in a file
    fake = tmp_path / "bin"
    fake.mkdir()
    store = tmp_path / "ring.json"
    (fake / "secret-tool").write_text(
        "#!/bin/sh\n"
        f"F={store}\n"
        'if [ "$1" = store ]; then read -r k; echo "$k" > "$F"; exit 0; fi\n'
        'if [ "$1" = lookup ]; then [ -f "$F" ] && cat "$F" && exit 0; exit 1; fi\n'
        "exit 2\n")
    (fake / "secret-tool").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}:{os.environ['PATH']}")
    monkeypatch.setenv("AGENTOS_VAULT_KEYRING", "1")
    ref = vault.put("mail.password", "pw")
    # the machine's vault takes the service key, which lives in the keyring when there is one
    assert vault.status()["mechanism"] == "service"
    assert json.loads((home / "away.json").read_text())["key"] == "keyring"
    assert not (home / "vault.key").exists() and not (home / "away.key").exists()
    assert vault.get(ref) == "pw"
    store.unlink()                                                 # the keyring is gone
    assert vault.get(ref) == ""
    st = vault.status()
    assert st["locked"] and "can't be found" in st["detail"]
    with pytest.raises(RuntimeError):
        vault.put("mail.password", "new")                          # never mints a fresh key
    assert not (home / "away.key").exists()


def test_saving_an_account_puts_the_password_in_the_vault_and_the_mailbox_still_gets_it(home):
    cfg = {"mail": {}, "calendar": {}}
    ok, _ = accounts.save(cfg, "mail", {"preset": "gmail", "user": "me@gmail.com", "password": "app-pass"})
    assert ok and cfg["mail"]["password"] == "vault:mail.password"
    assert mailmod.conf(cfg)["password"] == "app-pass"             # the code that opens the box
    ok, _ = accounts.save(cfg, "calendar", {"preset": "icloud", "user": "me", "password": "cal-pass"})
    assert ok and cfg["calendar"]["password"] == "vault:calendar.password"
    assert calendars.conf(cfg)["password"] == "cal-pass"
    # the card: set, "in the vault", and what protects it — never the value
    a = next(x for x in accounts.state(cfg) if x["id"] == "mail")
    assert a["set"]["password"] and a["masked"]["password"] == "in the vault"
    assert a["values"]["password"] == "" and a["vault"]["mechanism"] == "service"
    assert "app-pass" not in json.dumps(accounts.state(cfg))
    # a blank password keeps the reference (the card's normal state)
    ok, _ = accounts.save(cfg, "mail", {"user": "me@gmail.com", "password": ""})
    assert cfg["mail"]["password"] == "vault:mail.password"


def test_a_config_still_holding_clear_text_is_adopted_once(home):
    cfg = {"mail": {"password": "old-clear", "user": "u"}, "calendar": {"password": "", "url": "x"}}
    assert vault.adopt(cfg)
    assert cfg["mail"]["password"] == "vault:mail.password" and cfg["calendar"]["password"] == ""
    assert mailmod.conf(cfg)["password"] == "old-clear"
    assert not vault.adopt(cfg)                                    # nothing left to move
    masked = {"mail": {"password": "•••"}}
    assert not vault.adopt(masked) and masked["mail"]["password"] == "•••"   # a mask is not a secret


def test_the_config_route_says_nothing_but_that_there_is_one(home):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        cfg = servermod.state["cfg"]
        cfg.setdefault("mail", {})["password"] = vault.put("mail.password", "s3cret")
        j = cl.get("/api/config").json()
        assert j["mail"]["password"] == "•••" and j["mail"]["_has_password"]
        assert "s3cret" not in cl.get("/api/config").text
        assert "s3cret" not in cl.get("/api/accounts").text
        cfg["mail"]["password"] = ""


def test_an_old_key_file_vault_moves_onto_the_service_key_once(home):
    """A machine vault from before the service key: decided once as `file`, then moved across at
    the next start (vault.to_service), every item with it, and the old key file deleted."""
    import base64
    key = os.urandom(32)
    (home / "vault.key").write_text(base64.b64encode(key).decode())
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    n = os.urandom(12)
    c = AESGCM(key).encrypt(n, b"old-totp", b"integrity.totp")
    (home / "vault.json").write_text(json.dumps({"key": "file", "v": 1, "items": {
        "integrity.totp": {"n": base64.b64encode(n).decode(), "c": base64.b64encode(c).decode()}}}))
    assert vault.get("integrity.totp") == "old-totp"
    assert vault.to_service() == 1
    assert vault.status()["mechanism"] == "service" and not (home / "vault.key").exists()
    assert vault.get("integrity.totp") == "old-totp"
    assert vault.to_service() == 0


def test_provider_keys_go_into_the_machines_vault_and_open_for_a_turn(home, monkeypatch):
    """The provider API keys: out of config.json in clear, opened by the service when it calls."""
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", home / "config.json")
    cfg = cfgmod.load_config()
    cfg["providers"]["anthropic"]["api_key"] = "sk-ant-PROVIDER"
    cfg.setdefault("speech", {})["elevenlabs"] = {"api_key": "el-VOICE"}
    cfgmod.save_config(cfg)
    text = (home / "config.json").read_text()
    assert "sk-ant-PROVIDER" not in text and "el-VOICE" not in text
    from agentos import providers, speech
    fresh = cfgmod.load_config()
    assert providers._key(fresh["providers"]["anthropic"]) == "sk-ant-PROVIDER"
    assert speech._key(fresh, "elevenlabs") == "el-VOICE"
    vault.forget_held()
