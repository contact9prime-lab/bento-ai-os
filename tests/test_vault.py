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
    assert stat.S_IMODE((home / "vault.key").stat().st_mode) == 0o600
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
    assert st["mechanism"] == "file" and st["count"] == 1 and "file permissions" in st["detail"]
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
    assert vault.status()["mechanism"] == "keyring" and "keyring" in vault.status()["detail"]
    assert not (home / "vault.key").exists()                       # the key is NOT beside the lock
    assert vault.get(ref) == "pw"
    store.unlink()                                                 # the keyring is gone
    assert vault.get(ref) == ""
    st = vault.status()
    assert st["locked"] and "not reachable" in st["detail"]
    with pytest.raises(RuntimeError):
        vault.put("mail.password", "new")                          # never mints a fresh key
    assert not (home / "vault.key").exists()


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
    assert a["values"]["password"] == "" and a["vault"]["mechanism"] == "file"
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
