"""Sealed secrets: each account's vault and website sign-ins open only from that person's own
signed-in browser (agentos/seal.py).

Asked for as "per account, not cross-pollinated even from root; the user has to be signed in to
read it, period", and "do not keep in memory something that might unlock something". So most of
these are one shape: seal as A, then prove that B, an admin, the disk, the server's memory and a
copied cookie each cannot open it on their own.
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import config as cfgmod                                # noqa: E402
from agentos import seal                                            # noqa: E402
from agentos import users as usersmod                               # noqa: E402
from agentos import vault                                           # noqa: E402

PW = "correct horse 1"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", tmp_path / "config.json")
    usersmod.reset_caches()
    usersmod.set_current("")
    seal._PADS.clear()
    yield tmp_path
    seal._PADS.clear()
    usersmod.reset_caches()
    usersmod.set_current("")


def _browser(uid, sid, share):
    """What the middleware does for a request from that browser."""
    return seal.from_request(uid, sid, share)


# ---- the seal itself ------------------------------------------------------------------------

def test_neither_half_opens_anything_alone(home):
    u = usersmod.create("ada", PW, role="admin")["id"]
    priv, _code = seal.establish(u, PW)
    share = seal.lend_cookie(u, "s1", priv)
    pad = seal._PADS["s1"][1]
    assert pad != priv and len(pad) == 32
    # the server's half alone: no browser in this request
    assert seal.key_here(u) is None
    # the browser's half with no pad here (a copied cookie after sign-out)
    seal.drop("s1")
    t = _browser(u, "s1", share)
    try:
        assert seal.key_here(u) is None
    finally:
        seal.reset_request(t)


def test_together_they_open_it_for_one_use(home):
    u = usersmod.create("ada", PW, role="admin")["id"]
    priv, _code = seal.establish(u, PW)
    share = seal.lend_cookie(u, "s1", priv)
    t = _browser(u, "s1", share)
    try:
        assert seal.key_here(u) == priv
    finally:
        seal.reset_request(t)
    assert seal.key_here(u) is None, "nothing is kept after the request"


def test_a_forged_half_opens_nothing(home):
    u = usersmod.create("ada", PW, role="admin")["id"]
    priv, _ = seal.establish(u, PW)
    seal.lend_cookie(u, "s1", priv)
    t = _browser(u, "s1", "A" * 43 + "=")
    try:
        assert seal.key_here(u) is None
    finally:
        seal.reset_request(t)


def test_one_account_cannot_open_anothers_seal(home):
    a = usersmod.create("ada", PW, role="admin")["id"]
    b = usersmod.create("bob", PW + "x")["id"]
    pa, _ = seal.establish(a, PW)
    seal.establish(b, PW + "x")
    share_a = seal.lend_cookie(a, "sa", pa)
    t = _browser(a, "sa", share_a)
    try:
        assert seal.key_here(b) is None, "A's browser must never open B's seal"
    finally:
        seal.reset_request(t)
    # A's whole key against B's box: a different key pair
    box = seal.seal_bytes(b, b"bob's secret", "vault/x")
    with pytest.raises(Exception):
        seal.open_bytes(b, pa, box, "vault/x")


def test_nothing_on_disk_opens_it(home):
    """At rest, root has the files and nothing else: no key in clear, no secret in clear."""
    u = usersmod.create("ada", PW, role="admin")["id"]
    priv, code = seal.establish(u, PW)
    with usersmod.as_user(u):
        vault.reseal(u)
        vault.put("mail.password", "the-mail-password")
    raw = b"".join(p.read_bytes() for p in usersmod.home_for(u).rglob("*") if p.is_file())
    assert priv not in raw and b"the-mail-password" not in raw and code.encode() not in raw
    assert not (usersmod.home_for(u) / "vault.key").exists()


def test_a_wrong_password_or_code_opens_nothing(home):
    u = usersmod.create("ada", PW, role="admin")["id"]
    seal.establish(u, PW)
    with pytest.raises(seal.Sealed):
        seal.open_with_password(u, "not it at all")
    with pytest.raises(seal.Sealed):
        seal.open_with_code(u, "AAAAA-AAAAA-AAAAA-AAAAA-AAAAA")


def test_the_recovery_code_is_typed_loosely(home):
    u = usersmod.create("ada", PW, role="admin")["id"]
    priv, code = seal.establish(u, PW)
    assert seal.open_with_code(u, " " + code.lower().replace("-", " ") + " ") == priv


def test_an_admin_reset_asks_for_the_recovery_code(home):
    u = usersmod.create("ada", PW, role="admin")["id"]
    priv, code = seal.establish(u, PW)
    seal.lend_cookie(u, "s1", priv)
    seal.mark_password_reset(u)
    assert seal.needs_recovery(u) and not seal.open_here(u), "a reset drops every half"
    with pytest.raises(seal.Sealed, match="recovery code"):
        seal.open_with_password(u, PW)
    got = seal.open_with_code(u, code)
    seal.rewrap(u, got, "a brand new one")
    assert seal.open_with_password(u, "a brand new one") == priv and not seal.needs_recovery(u)


def test_starting_fresh_removes_what_can_never_be_opened(home):
    u = usersmod.create("ada", PW, role="admin")["id"]
    seal.establish(u, PW)
    with usersmod.as_user(u):
        vault.reseal(u)
        vault.put("mail.password", "x")
    (usersmod.home_for(u) / "browser").mkdir(parents=True)
    (usersmod.home_for(u) / "browser" / "profile.sealed").write_text("{}")
    gone = seal.start_fresh(u)
    assert any("vault" in g for g in gone) and "your website sign-ins" in gone
    assert not seal.exists(u)
    with usersmod.as_user(u):
        assert vault.names() == []


def test_the_machine_has_no_seal(home):
    with pytest.raises(ValueError):
        seal.establish("", PW)
    assert seal.exists("") is False and seal.status("")["sealed"] is False


# ---- the vault --------------------------------------------------------------------------------

def test_an_old_vault_moves_into_the_seal_and_its_key_goes(home):
    u = usersmod.create("ada", PW, role="admin")["id"]
    with usersmod.as_user(u):
        vault.put("mail.password", "before-the-update")
        assert (usersmod.home_for(u) / "vault.key").exists()
    priv, _ = seal.establish(u, PW)
    with usersmod.as_user(u):
        assert vault.reseal(u) == 1
        assert vault.sealed() and not (usersmod.home_for(u) / "vault.key").exists()
        share = seal.lend_cookie(u, "s1", priv)
        t = _browser(u, "s1", share)
        try:
            assert vault.get("mail.password") == "before-the-update"
        finally:
            seal.reset_request(t)


def test_a_sealed_vault_takes_a_secret_with_nothing_secret_in_memory(home):
    """A sign-in refreshing its token in the night writes it with the public key only."""
    u = usersmod.create("ada", PW, role="admin")["id"]
    priv, _ = seal.establish(u, PW)
    priv = None
    with usersmod.as_user(u):
        vault.reseal(u)
        vault.put("oauth.google", "refreshed-token")
        assert vault.has("oauth.google")
        vault.set_away("oauth.google", "off")          # the strict rule: only while signed in
        with pytest.raises(seal.Sealed, match="only while you're signed in"):
            vault.get("oauth.google")


def test_a_signed_out_read_says_what_to_do(home):
    u = usersmod.create("ada", PW, role="admin")["id"]
    seal.establish(u, PW)
    with usersmod.as_user(u):
        vault.reseal(u)
        vault.put("mail.password", "x")
        vault.set_away("mail.password", "off")
        with pytest.raises(seal.Sealed) as e:
            vault.get("mail.password")
    assert "signed in" in str(e.value).lower() and "Your secrets" in str(e.value)


def test_the_machine_vault_is_not_sealed(home):
    """Nobody signs in as the machine: its vault is locked with the service key (away.py)."""
    vault.put("integrity.totp", "machine-secret")
    assert vault.get("integrity.totp") == "machine-secret"
    assert vault.status()["mechanism"] == "service"


# ---- borrowing, for a step nobody is watching ------------------------------------------------

def test_a_step_borrows_from_the_open_page_and_keeps_nothing(home):
    u = usersmod.create("ada", PW, role="admin")["id"]
    priv, _ = seal.establish(u, PW)
    share = seal.lend_cookie(u, "s1", priv)

    async def run():
        async def ask(uid, ticket, why):
            # the page answers: its request carries its half, and the route hands the key over
            async def page():
                t = _browser(uid, "s1", share)
                try:
                    assert seal.lent(ticket, uid)
                finally:
                    seal.reset_request(t)
            asyncio.get_running_loop().call_later(0.05, lambda: asyncio.ensure_future(page()))
            return True
        seal.bind(asyncio.get_running_loop(), ask)
        got = await seal.borrow(u, "read your mail")
        assert got == priv and not seal._WAIT and not seal._WANTS.get(u)
    asyncio.run(run())
    seal.bind(None, None)


def test_with_no_page_open_a_step_is_refused_at_once(home):
    u = usersmod.create("ada", PW, role="admin")["id"]
    priv, _ = seal.establish(u, PW)
    seal.lend_cookie(u, "s1", priv)
    seal.note_sign_in(u)

    async def run():
        async def ask(uid, ticket, why):
            return False
        seal.bind(asyncio.get_running_loop(), ask)
        with pytest.raises(seal.Sealed, match="none is open"):
            await seal.borrow(u, "read your mail")
    asyncio.run(run())
    seal.bind(None, None)


def test_a_locked_page_lends_by_asking(home):
    """A locked screen has no socket, so it polls `wants` and lends (the owner's choice)."""
    u = usersmod.create("ada", PW, role="admin")["id"]
    priv, _ = seal.establish(u, PW)
    share = seal.lend_cookie(u, "s1", priv)
    seal.wants(u)                                   # the locked page asked a moment ago

    async def run():
        async def ask(uid, ticket, why):
            return False                            # no socket
        seal.bind(asyncio.get_running_loop(), ask)
        task = asyncio.ensure_future(seal.borrow(u, "post today's picture"))
        await asyncio.sleep(0.05)
        w = seal.wants(u)
        assert [x["why"] for x in w] == ["post today's picture"]
        t = _browser(u, "s1", share)
        try:
            assert seal.lent(w[0]["ticket"], u)
        finally:
            seal.reset_request(t)
        assert await task == priv
    asyncio.run(run())
    seal.bind(None, None)


def test_after_a_restart_the_step_says_to_enter_the_password(home):
    u = usersmod.create("ada", PW, role="admin")["id"]
    seal.establish(u, PW)
    seal._SIGNED_IN_AT.pop(u, None)

    async def run():
        with pytest.raises(seal.Sealed):
            await seal.borrow(u, "x")
    asyncio.run(run())


# ---- the browser profile ----------------------------------------------------------------------

def test_a_profile_is_sealed_without_its_caches_and_opens_safely(tmp_path):
    from agentos import cdpbrowser as cb
    root = tmp_path / "p"
    (root / "Default").mkdir(parents=True)
    (root / "Default" / "Cookies").write_bytes(b"cookie-db")
    (root / "Default" / "Cache").mkdir()
    (root / "Default" / "Cache" / "big").write_bytes(b"x" * 1000)
    data = cb._tar(root)
    out = tmp_path / "o"
    out.mkdir()
    cb._untar(data, out)
    assert (out / "Default" / "Cookies").read_bytes() == b"cookie-db"
    assert not (out / "Default" / "Cache").exists()
    # a box with a path out of the folder: that member is skipped
    import io
    import tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        ti = tarfile.TarInfo("../escaped")
        ti.size = 1
        t.addfile(ti, io.BytesIO(b"x"))
    cb._untar(buf.getvalue(), out)
    assert not (tmp_path / "escaped").exists()


def test_the_pages_draw_the_code_from_text_nodes():
    root = Path(__file__).parent.parent / "agentos" / "ui"
    js = (root / "src" / "js" / "11o-seal.js").read_text()
    assert "innerHTML" not in js
    login = (root / "login.html").read_text()
    part = login[login.index("// ---- sealed secrets"):]
    assert "innerHTML" not in part


def test_the_seal_is_a_security_file_no_agent_reads():
    from agentos import protected
    assert "agentos/seal.py" in protected.SECURITY_MODULES
    assert "seal.json" in protected.SECRET_FILES


# ---- over HTTP --------------------------------------------------------------------------------

@pytest.fixture()
def api(home):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as c:
        yield c


def test_the_first_account_is_sealed_and_shown_its_code_once(api):
    r = api.post("/api/users", json={"name": "ada", "password": PW})
    d = r.json()
    assert r.status_code == 200 and len(d["recovery_code"]) == 29
    assert "httponly" in r.headers.get("set-cookie", "").lower()
    assert api.cookies.get(seal.COOKIE)
    st = api.get("/api/seal").json()
    assert st["sealed"] and st["open"]
    # signing in again opens it and shows no code
    api.cookies.clear()
    d2 = api.post("/api/users/login", json={"name": "ada", "password": PW}).json()
    assert "recovery_code" not in d2 and api.get("/api/seal").json()["open"]


def test_an_existing_account_is_sealed_at_its_next_sign_in(api, home):
    """"On next sign-in post upgrade": an account made before the update gets its code then."""
    api.post("/api/users", json={"name": "ada", "password": PW})
    b = usersmod.create("bob", PW + "b")["id"]
    with usersmod.as_user(b):
        vault.put("mail.password", "bobs-old-secret")
    assert not seal.exists(b)
    api.cookies.clear()
    d = api.post("/api/users/login", json={"name": "bob", "password": PW + "b"}).json()
    assert d.get("recovery_code") and seal.exists(b)
    with usersmod.as_user(b):
        assert vault.sealed()


def test_signing_out_leaves_a_copied_cookie_unable_to_open_it(api):
    api.post("/api/users", json={"name": "ada", "password": PW})
    copied = dict(api.cookies)
    api.post("/api/users/logout")
    assert not seal._PADS
    api.cookies.update(copied)
    assert api.get("/api/seal").status_code in (200, 401)
    st = api.get("/api/seal")
    assert st.status_code == 401 or not st.json().get("open")


def test_an_admin_cannot_open_somebody_elses_seal(api):
    api.post("/api/users", json={"name": "ada", "password": PW})
    api.post("/api/users", json={"name": "bob", "password": PW + "b"})
    api.cookies.clear()
    api.post("/api/users/login", json={"name": "bob", "password": PW + "b"})
    b = usersmod.by_name("bob")["id"]
    with usersmod.as_user(b):
        vault.put("mail.password", "bobs-secret")
        vault.set_away("mail.password", "off")
    api.cookies.clear()
    api.post("/api/users/login", json={"name": "ada", "password": PW})
    ada = dict(api.cookies)
    with usersmod.as_user(b):
        t = seal.from_request(b, "any", ada.get(seal.COOKIE, ""))
        try:
            with pytest.raises(seal.Sealed):
                vault.get("mail.password")
        finally:
            seal.reset_request(t)
    # and the admin resetting bob's password does not give them bob's secrets
    r = api.put(f"/api/users/{b}", json={"password": "reset-by-admin"})
    assert r.status_code == 200 and seal.needs_recovery(b)


def test_after_an_admin_reset_the_code_opens_it_or_starting_fresh_clears_it(api):
    api.post("/api/users", json={"name": "ada", "password": PW})
    api.post("/api/users", json={"name": "bob", "password": PW + "b"})
    api.cookies.clear()
    code = api.post("/api/users/login", json={"name": "bob", "password": PW + "b"}).json()["recovery_code"]
    b = usersmod.by_name("bob")["id"]
    with usersmod.as_user(b):
        vault.put("mail.password", "bobs-secret")
    api.cookies.clear()
    api.post("/api/users/login", json={"name": "ada", "password": PW})
    api.put(f"/api/users/{b}", json={"password": "reset-by-admin"})
    api.cookies.clear()
    d = api.post("/api/users/login", json={"name": "bob", "password": "reset-by-admin"}).json()
    assert d["needs_recovery"]
    assert api.post("/api/seal/recover", json={"code": "wrong", "password": "reset-by-admin"}).status_code == 403
    r = api.post("/api/seal/recover", json={"code": code, "password": "reset-by-admin"})
    assert r.status_code == 200 and r.json()["recovery_code"] != code
    assert api.get("/api/seal").json()["open"]


def test_a_new_recovery_code_needs_the_password(api):
    api.post("/api/users", json={"name": "ada", "password": PW})
    assert api.post("/api/seal/code", json={"password": "nope"}).status_code == 403
    r = api.post("/api/seal/code", json={"password": PW})
    assert r.status_code == 200 and len(r.json()["recovery_code"]) == 29


def test_lending_needs_the_cookie_and_the_half(api):
    api.post("/api/users", json={"name": "ada", "password": PW})
    keep = dict(api.cookies)
    api.cookies.clear()
    assert api.post("/api/seal/lend", json={"ticket": "x"}).status_code == 401
    api.cookies.update(keep)
    assert api.post("/api/seal/lend", json={"ticket": "nobody-asked"}).json() == {"ok": False}


def test_a_task_started_from_a_request_keeps_no_half_after_it(home):
    """asyncio copies the context into a task; the half must not outlive the request in it."""
    u = usersmod.create("ada", PW, role="admin")["id"]
    priv, _ = seal.establish(u, PW)
    share = seal.lend_cookie(u, "s1", priv)

    async def run():
        t = _browser(u, "s1", share)
        seen = {}

        async def later():
            await asyncio.sleep(0.05)
            seen["after"] = seal.key_here(u)
        task = asyncio.create_task(later())
        seen["during"] = seal.key_here(u)
        seal.reset_request(t)            # the request answered
        await task
        return seen
    seen = asyncio.run(run())
    assert seen["during"] == priv and seen["after"] is None


def test_a_sweep_leaves_a_running_servers_profile_alone(tmp_path, monkeypatch):
    """Found by running the live test beside the suite: a start-up sweep removed another
    running server's open profile. Only a dead server's folder goes."""
    from agentos import cdpbrowser as cb
    monkeypatch.setattr(cb, "_ram_dir", lambda: str(tmp_path))
    live = tmp_path / f"bento-browser-{os.getppid()}-u1-abc"
    dead = tmp_path / "bento-browser-999999-u1-def"
    live.mkdir()
    dead.mkdir()
    assert cb.sweep_runs() == 1
    assert live.exists() and not dead.exists()
