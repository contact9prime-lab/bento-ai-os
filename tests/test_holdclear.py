"""Clearing a security hold from an admin's phone or Settings (holdclear.py).

Asked for as "the users should be allowed to reset and get a clear picture or accept it at admin's
telegram or whatsapp ... it is then difficult to login to the machine to do this". Real files in a
throwaway tree and home, a real git repository for the picture."""
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import config as cfgmod                 # noqa: E402
from agentos import holdclear, integrity, secevents  # noqa: E402

ROOT = Path(__file__).parent.parent


def _git(tree, *a):
    subprocess.run(["git", *a], cwd=tree, check=True, capture_output=True)


@pytest.fixture()
def box(tmp_path, monkeypatch):
    tree = tmp_path / "tree"
    (tree / "agentos").mkdir(parents=True)
    (tree / "agentos" / "policy.py").write_text("GATE = 1\n")
    (tree / "install.sh").write_text("#!/bin/sh\n")
    (tree / "pyproject.toml").write_text("[project]\n")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", home)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", home / "config.json")
    monkeypatch.setattr(integrity, "code_root", lambda: tree.resolve())
    for k in ("GIT_COMMITTER_NAME", "GIT_AUTHOR_NAME"):
        monkeypatch.setenv(k, "t")
    for k in ("GIT_COMMITTER_EMAIL", "GIT_AUTHOR_EMAIL"):
        monkeypatch.setenv(k, "t@t")
    # a repository with a remote that has the commits, as a checkout made by the installer
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    _git(tree, "init", "-q", "-b", "master")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-q", "-m", "first")
    _git(tree, "remote", "add", "origin", str(origin))
    _git(tree, "push", "-q", "origin", "master")
    integrity.forget_for_tests()
    secevents.forget_for_tests()
    holdclear.forget_for_tests()
    integrity.seal(tree)
    w = integrity.start_watching(tree)
    yield tree, home, w, origin
    integrity.forget_for_tests()
    secevents.forget_for_tests()
    holdclear.forget_for_tests()


def _trip(w, tree, text="GATE = 0\n"):
    (tree / "agentos" / "policy.py").write_text(text)
    w.tick()
    assert integrity.held()


def _code_now():
    return holdclear._hotp(holdclear._secret(), int(time.time() // holdclear.STEP_S))


# ------------------------------------------------------------------------------ the picture

def test_an_undone_change_is_back_to_normal(box):
    tree, home, w, _ = box
    _trip(w, tree)
    (tree / "agentos" / "policy.py").write_text("GATE = 1\n")
    pic = holdclear.picture()
    assert pic["kind"] == holdclear.SETTLED and "back to what was recorded" in pic["words"]
    assert holdclear.why_not(pic) == "", "a settled change needs no code"


def test_a_clean_commit_on_the_remote_is_known(box):
    tree, home, w, origin = box
    (tree / "agentos" / "policy.py").write_text("GATE = 2\n")
    _git(tree, "commit", "-qam", "pulled")
    _git(tree, "push", "-q", "origin", "master")
    w.tick()
    pic = holdclear.picture()
    assert pic["kind"] == holdclear.KNOWN and "pulled" in pic["commit"]
    assert "agentos/policy.py" in holdclear.changes(pic)


def test_edits_git_cant_vouch_for_are_unknown_and_need_a_code(box):
    tree, home, w, _ = box
    _trip(w, tree, "GATE = 0  # planted\n")
    pic = holdclear.picture()
    assert pic["kind"] == holdclear.UNKNOWN
    assert "policy.py changed" in pic["words"] and "isn't in any commit" in pic["words"]
    shown = holdclear.changes(pic)
    assert "planted" in shown, "the diff shows what was written"
    assert "\n+GATE = 0" in shown, "and keeps its lines"
    assert "authenticator" in holdclear.why_not(pic), "no code set up: refused in a sentence"


def test_a_planted_file_is_shown_in_full(box):
    tree, home, w, _ = box
    (tree / "agentos" / "zz_planted.py").write_text("OPEN = True  # planted\n")
    w.tick()
    pic = holdclear.picture()
    assert pic["kind"] == holdclear.UNKNOWN and "zz_planted.py is new" in pic["words"]
    assert "New file agentos/zz_planted.py:" in holdclear.changes(pic)
    assert not holdclear.changes(pic, head=False).startswith(pic["words"])
    assert "OPEN = True  # planted" in holdclear.changes(pic)


def test_a_commit_that_isnt_on_the_remote_is_unknown(box):
    tree, home, w, _ = box
    (tree / "agentos" / "policy.py").write_text("GATE = 3\n")
    _git(tree, "commit", "-qam", "local only")
    w.tick()
    assert holdclear.picture()["kind"] == holdclear.UNKNOWN


def test_a_locked_home_file_is_unknown_and_never_shown(box):
    tree, home, w, _ = box
    (home / "session.key").write_text("first")
    integrity.rebaseline_home()
    (home / "session.key").write_text("replaced-secret")
    w.tick()
    pic = holdclear.picture()
    assert pic["kind"] == holdclear.UNKNOWN and pic["home"]
    assert "replaced-secret" not in holdclear.changes(pic)


# ------------------------------------------------------------------------------ the code

def test_the_code_works_once_and_wrong_ones_pause(box):
    tree, home, w, _ = box
    _trip(w, tree, "GATE = 0  # planted\n")
    got = holdclear.new_code("ada")
    assert got["uri"].startswith("otpauth://totp/") and got["secret"] in got["uri"]
    assert holdclear.code_set()
    pic = holdclear.picture()
    assert holdclear.why_not(pic, "") .startswith("This change needs")
    code = _code_now()
    assert holdclear.why_not(pic, code) == ""
    assert not holdclear.code_ok(code), "a code is spent once"
    for _ in range(holdclear.TRIES):
        holdclear.why_not(pic, "000000" if code != "000000" else "111111")
    assert holdclear.paused()
    assert "Too many" in holdclear.why_not(pic, _code_now())


def test_a_signed_machine_accepts_only_at_its_terminal(box, tmp_path):
    tree, home, w, _ = box
    path, key_id, pub = integrity.keygen(tmp_path / "k")
    integrity.trust(pub)
    integrity.seal(tree, key_path=path)
    _trip(w, tree)
    (tree / "agentos" / "policy.py").write_text("GATE = 1\n")
    assert "terminal with the key" in holdclear.why_not(holdclear.picture())


# ------------------------------------------------------------------------------ accepting

def test_accept_lets_the_agents_run_and_is_said(box):
    tree, home, w, _ = box
    _trip(w, tree)
    (tree / "agentos" / "policy.py").write_text("GATE = 1\n")
    got = holdclear.accept("ada", "settings")
    assert got["released"] and integrity.held() is None
    entry = integrity.record_for(tree)
    assert entry["by"] == "accept" and entry["via"] == "settings:ada"
    assert [e for e in secevents.recent(50) if e["kind"] == "integrity.accepted"]


def test_the_phone_answers_only_an_admins_paired_chat(box):
    tree, home, w, _ = box
    _trip(w, tree)
    assert holdclear.from_phone("tg:9", "accept", False, "ada", "telegram") is None, \
        "anybody else goes on to the agent, which refuses"
    assert "Reply show" in holdclear.from_phone("tg:1", "hello", True, "ada", "telegram")
    assert "agentos/policy.py" in holdclear.from_phone("tg:1", "show", True, "ada", "telegram")
    assert "stay stopped" in holdclear.from_phone("tg:1", "keep", True, "ada", "telegram")
    # an unknown change, with a code set up: accept asks for it, the code clears it
    holdclear.new_code()
    assert "6-digit" in holdclear.from_phone("tg:1", "accept", True, "ada", "telegram")
    assert integrity.held()
    said = holdclear.from_phone("tg:1", _code_now(), True, "ada", "telegram")
    assert said.startswith("✓") and integrity.held() is None
    assert integrity.record_for(tree)["via"] == "telegram:ada"
    assert holdclear.from_phone("tg:1", "accept", True, "ada", "telegram") is None, "nothing held now"


def test_a_settled_hold_is_one_tap_from_the_phone(box):
    tree, home, w, _ = box
    _trip(w, tree)
    (tree / "agentos" / "policy.py").write_text("GATE = 1\n")
    assert holdclear.from_phone("wa:1", "Accept", True, "ada", "whatsapp").startswith("✓")
    assert integrity.held() is None


def test_the_refusal_still_names_the_terminal_and_now_the_admin(box):
    tree, home, w, _ = box
    _trip(w, tree)
    r = integrity.refusal()
    assert "bento integrity accept" in r and "Settings" in r and "phone" in r


# ------------------------------------------------------------------------------ the doors

def test_the_bridges_catch_the_hold_before_any_agent():
    tg = (ROOT / "agentos/telegram.py").read_text()
    h = tg[tg.index("async def _handle(self, msg"):tg.index("frm = msg.get(\"from\", {})")]
    assert "_hold_answer" in h, "Telegram answers the hold before the turn is saved"
    assert "text" not in h[h.index("_hold_answer"):].split("store.log")[1].split("\n")[0], "a code is never logged"
    hb = tg[tg.index("def _hold_answer"):tg.index("async def send_hold")]
    assert "owner_chat_id" in hb and "is_admin" in hb and '"private"' in hb
    wa = (ROOT / "agentos/whatsapp.py").read_text()
    h = wa[wa.index("async def _one(self"):wa.index("name = self._profile_name(val, wa_id)")]
    assert "holdclear.from_phone" in h and "owner_wa_id" in h and "is_admin" in h


def test_the_routes_are_an_admins_with_proof():
    srv = (ROOT / "agentos/server.py").read_text()
    h = srv[srv.index("def _accept_proof"):srv.index("def _accept_who")]
    assert "_require_admin()" in h and "check_password" in h and "_at_machine(request)" in h
    assert "holdclear.missed()" in h and "paused()" in h
    a = srv[srv.index("async def api_security_accept"):srv.index("async def api_security_code")]
    assert "_accept_proof(" in a and "why_not(" in a and "_accept_ledger(" in a
    c = srv[srv.index("async def api_security_code"):srv.index('@app.get("/api/security/events")')]
    assert "code_ok(" in c, "replacing a code needs the current one"


def test_the_hold_is_told_to_the_phones_at_start_and_when_it_trips():
    srv = (ROOT / "agentos/server.py").read_text()
    loop = srv[srv.index("async def _integrity_loop"):srv.index('@app.get("/api/security/status")')]
    assert loop.index("_hold_phones()") < loop.index("verify_ledgers"), "the first check at start"
    held = srv[srv.index("def _integrity_held"):srv.index("LEDGER_CHECK_S")]
    assert "await _hold_phones()" in held


def test_the_route_answers_end_to_end(box, monkeypatch):
    """The real app, no accounts, at the machine: accept clears a settled hold."""
    from fastapi.testclient import TestClient
    from agentos import server
    tree, home, w, _ = box
    _trip(w, tree)
    (tree / "agentos" / "policy.py").write_text("GATE = 1\n")
    monkeypatch.setattr(server, "_at_machine", lambda r: True)
    with TestClient(server.app) as c:
        pic = c.get("/api/security/picture").json()
        assert pic["kind"] == "settled" and pic["needs_password"] is False
        r = c.post("/api/security/accept", json={})
        assert r.status_code == 200, r.text
    assert integrity.held() is None
    rows = __import__("agentos.users", fromlist=["x"]).store_for("").audit_list(action="integrity.accept")
    assert rows and rows[0]["outcome"] == "ok"
