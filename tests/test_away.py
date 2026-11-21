"""Secrets that work while you're away (agentos/away.py).

The owner's correction to the seal: "Bento starts as a service for everyone; once the user has
accepted to store the password for future missions it should work unless they revoke it or set a
time limit; allowed once, it works the next time and resets, whether they're signed in or not."
So most of these run a read with NOBODY signed in (no pad, no page) and check what each choice
does, and then check the copy that makes it possible reaches nobody else.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import away                                            # noqa: E402
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
    vault.forget_held()
    yield tmp_path
    seal._PADS.clear()
    vault.forget_held()
    usersmod.reset_caches()
    usersmod.set_current("")


def _ada():
    u = usersmod.create("ada", PW, role="admin")["id"]
    priv, _ = seal.establish(u, PW)
    return u, priv


def _all_bytes(root: Path) -> bytes:
    out = b""
    for p in root.rglob("*"):
        if p.is_file():
            out += p.read_bytes()
    return out


# ---- the four choices, read with nobody signed in --------------------------------------------

def test_a_saved_secret_works_with_nobody_signed_in_until_revoked(home):
    u, _ = _ada()
    with usersmod.as_user(u):
        vault.put("mail.password", "hunter2")
        assert vault.away_meta("mail.password")["mode"] == "always"
        seal._PADS.clear()                         # a restart: no pad for anybody
        assert vault.get("mail.password") == "hunter2"
        # revoking needs nothing, and closes it at once
        vault.set_away("mail.password", "off")
        with pytest.raises(seal.Sealed, match="Mail password is set to work only while you're signed in"):
            vault.get("mail.password")


def test_switching_one_back_on_needs_your_key(home):
    u, priv = _ada()
    with usersmod.as_user(u):
        vault.put("mail.password", "hunter2")
        vault.set_away("mail.password", "off")
        with pytest.raises(seal.Sealed, match="needs your key once"):
            vault.set_away("mail.password", "always")
        vault.set_away("mail.password", "always", priv=priv)
        assert vault.get("mail.password") == "hunter2"


def test_once_works_for_the_next_run_and_then_resets(home):
    u, priv = _ada()
    with usersmod.as_user(u):
        vault.put("mail.password", "hunter2")
        vault.set_away("mail.password", "once")              # the copy is there: no key needed
        assert vault.get("mail.password") == "hunter2"       # the run starts using it
        assert vault.get("mail.password") == "hunter2"       # and keeps it for that run
        m = vault.away_meta("mail.password")
        m["used"] = time.time() - away.ONCE_S - 1            # the run is long over
        vault.note_away("mail.password", m)
        with pytest.raises(seal.Sealed):
            vault.get("mail.password")
        m = vault.away_meta("mail.password")
        assert m["mode"] == "off" and m["ended"] == "once" and "box" not in m
        assert vault.away_list()[0]["words"] == "Used once. Now only while you're signed in"


def test_a_once_is_not_spent_while_a_page_of_yours_could_lend(home, monkeypatch):
    u, priv = _ada()
    with usersmod.as_user(u):
        vault.put("mail.password", "hunter2")
        vault.set_away("mail.password", "once")
        monkeypatch.setattr(seal, "open_here", lambda uid: True)
        monkeypatch.setattr(seal, "borrow_blocking", lambda uid, why: priv)
        assert vault.get("mail.password") == "hunter2"
        assert not vault.away_meta("mail.password").get("used")


def test_a_time_limit_ends_by_itself(home):
    u, priv = _ada()
    with usersmod.as_user(u):
        vault.put("mail.password", "hunter2")
        vault.set_away("mail.password", "until", days=7)
        assert "7 days left" in vault.away_list()[0]["words"]
        assert vault.get("mail.password") == "hunter2"
        m = vault.away_meta("mail.password")
        m["until"] = time.time() - 1
        vault.note_away("mail.password", m)
        with pytest.raises(seal.Sealed):
            vault.get("mail.password")
        assert vault.away_meta("mail.password")["ended"] == "until"


def test_a_refreshed_token_keeps_the_choice(home):
    """A sign-in refreshing its token in the night writes it again: what the person chose stays."""
    u, priv = _ada()
    with usersmod.as_user(u):
        vault.put("oauth.mail", "token-1")
        vault.set_away("oauth.mail", "off")
        vault.put("oauth.mail", "token-2")
        assert vault.away_meta("oauth.mail")["mode"] == "off"
        vault.set_away("oauth.mail", "until", days=3, priv=priv)
        vault.put("oauth.mail", "token-3")
        assert vault.away_meta("oauth.mail")["mode"] == "until"
        assert vault.get("oauth.mail") == "token-3"


def test_bad_choices_are_refused_in_words(home):
    for mode, days in (("sometimes", None), ("until", 0), ("until", 99999)):
        with pytest.raises(ValueError):
            away.choice(mode, days)


# ---- the copy reaches nobody else ----------------------------------------------------------------

def test_nothing_on_disk_is_the_secret_in_clear(home):
    u, _ = _ada()
    with usersmod.as_user(u):
        vault.put("mail.password", "a-very-findable-secret")
    assert b"a-very-findable-secret" not in _all_bytes(home)


def test_another_account_cannot_open_your_copy(home):
    """The copy is bound to its account: moved into bob's vault it does not open as bob's."""
    u, _ = _ada()
    b = usersmod.create("bob", PW + "b")["id"]
    seal.establish(b, PW + "b")
    with usersmod.as_user(u):
        vault.put("mail.password", "adas-secret")
        box = vault.away_meta("mail.password")["box"]
    with usersmod.as_user(b):
        assert vault.get("mail.password") == ""           # bob's own vault has nothing of hers
        assert away.unlock(b, "vault/mail.password", box) is None
    assert away.unlock(u, "vault/mail.password", box) == b"adas-secret"


def test_the_service_key_is_never_reminted(home):
    u, _ = _ada()
    with usersmod.as_user(u):
        vault.put("mail.password", "x")
        (home / away.KEY_FILE).unlink()
        assert away._load(create=False) == b""
        with pytest.raises(seal.Sealed):
            vault.get("mail.password")


# ---- tokens a running service uses ---------------------------------------------------------------

def test_bot_tokens_and_mcp_keys_go_into_the_vault_before_the_file(home):
    u, _ = _ada()
    cfg = {"telegram": {"bot_token": "123:abc", "enabled": True},
           "channels": {"telegram": {"bot_token": "123:abc"},
                        "whatsapp": {"access_token": "EAAG-tok", "app_secret": "sh", "verify_token": "mine"}},
           "mcp_servers": [{"name": "notion", "env": {"NOTION_API_KEY": "secret_n", "ROOT_DIR": "/srv"},
                            "headers": {"Authorization": "Bearer xyz"}}]}
    usersmod.save_user_cfg(u, cfg)
    text = usersmod.cfg_path_for(u).read_text()
    for clear in ("123:abc", "EAAG-tok", "secret_n", "Bearer xyz"):
        assert clear not in text
    # what isn't a secret stays where the person can read it
    assert "/srv" in text and '"verify_token": "mine"' in text
    # one value in two places is one secret
    assert cfg["telegram"]["bot_token"] == cfg["channels"]["telegram"]["bot_token"]
    with usersmod.as_user(u):
        assert vault.get(cfg["mcp_servers"][0]["env"]["NOTION_API_KEY"]) == "secret_n"
        names = [x["label"] for x in vault.away_list()]
    assert "Telegram bot" in names and "MCP notion: NOTION_API_KEY" in names


def test_telegram_and_whatsapp_open_their_tokens(home):
    from agentos import telegram, whatsapp
    u, _ = _ada()
    cfg = {"_uid": u, "telegram": {"bot_token": "123:abc"},
           "whatsapp": {"access_token": "EAAG-tok", "app_secret": "sh"}}
    with usersmod.as_user(u):
        vault.adopt(cfg)
    assert vault.is_ref(cfg["telegram"]["bot_token"])
    br = telegram.TelegramBridge.__new__(telegram.TelegramBridge)
    br.cfg = cfg
    assert br._token() == "123:abc"
    assert whatsapp.secret(cfg, "app_secret") == "sh"


def test_mcp_env_and_headers_are_opened_for_the_server(home):
    from agentos import mcp_client
    u, _ = _ada()
    conf = {"name": "notion", "env": {"NOTION_API_KEY": "secret_n", "ROOT": "/srv"}}
    with usersmod.as_user(u):
        vault.adopt({"mcp_servers": [conf]})
        assert vault.is_ref(conf["env"]["NOTION_API_KEY"])
        assert mcp_client._opened(conf["env"], "notion") == {"NOTION_API_KEY": "secret_n", "ROOT": "/srv"}
        vault.set_away(conf["env"]["NOTION_API_KEY"][len(vault.REF):], "off")
        # with nobody signed in, a signed-in-only key is left out rather than sent empty
        assert mcp_client._opened(conf["env"], "notion") == {"ROOT": "/srv"}


def test_an_mcp_sign_in_is_a_vault_item_with_a_marker_file(home, monkeypatch):
    from agentos import mcp_oauth
    u, _ = _ada()
    with usersmod.as_user(u):
        mcp_oauth._write("linear", "https://mcp.linear.app/sse", {"tokens": {"access_token": "lin-at"}}, u)
        f = mcp_oauth._token_path("linear", "https://mcp.linear.app/sse", u)
        assert b"lin-at" not in f.read_bytes() and json.loads(f.read_text())["has_tokens"]
        # a listing never opens the vault
        with monkeypatch.context() as m:
            m.setattr(vault, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("opened")))
            assert mcp_oauth.has_tokens("linear", "https://mcp.linear.app/sse")
        assert mcp_oauth._read("linear", "https://mcp.linear.app/sse", u)["tokens"]["access_token"] == "lin-at"
        assert mcp_oauth.forget("linear") and not vault.has(mcp_oauth._vault_name(f))


def test_a_bot_token_set_to_signed_in_only_is_not_kept_in_memory(home):
    u, _ = _ada()
    with usersmod.as_user(u):
        ref = vault.put("telegram.bot_token", "123:abc")
        assert vault.held(ref, "telegram") == "123:abc"
        assert vault._CACHE                              # works unattended anyway: kept an hour
        vault.forget_held()
        vault.set_away("telegram.bot_token", "off")
        with pytest.raises(Exception):
            vault.get(ref)
        assert vault.held(ref, "telegram") == "" and not vault._CACHE


# ---- the browser profile -------------------------------------------------------------------------

def test_the_signed_in_browser_opens_with_nobody_signed_in(home):
    from agentos import cdpbrowser
    u, _ = _ada()
    base = usersmod.home_for(u) / "browser"
    base.mkdir(parents=True)
    run = home / "run"
    (run / "Default").mkdir(parents=True)
    (run / "Default" / "Cookies").write_bytes(b"site-cookie")
    tar = cdpbrowser._tar(run)
    with usersmod.as_user(u):
        cdpbrowser._write_box(base / cdpbrowser.SEALED_PROFILE, seal.seal_bytes(u, tar, "browser"))
        cdpbrowser._keep_away(u, base, tar)
        assert (base / cdpbrowser.AWAY_PROFILE).exists()
        assert cdpbrowser._open_away(u, base) == tar
        assert b"site-cookie" not in (base / cdpbrowser.AWAY_PROFILE).read_bytes()
        vault.set_away(vault.BROWSER, "off")
        assert not (base / cdpbrowser.AWAY_PROFILE).exists()
        assert cdpbrowser._open_away(u, base) is None
        assert vault.away_list()[-1]["label"] == "Websites you're signed in to"


# ---- the faces -----------------------------------------------------------------------------------

@pytest.fixture()
def api(home):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as c:
        yield c


def test_the_card_lists_each_secret_and_changes_it(api):
    api.post("/api/users", json={"name": "ada", "password": PW})
    u = usersmod.by_name("ada")["id"]
    with usersmod.as_user(u):
        vault.put("mail.password", "hunter2")
    st = api.get("/api/seal").json()
    assert st["secrets"][0]["name"] == "mail.password" and "root" in st["away_cost"]
    r = api.put("/api/seal/away", json={"name": "mail.password", "mode": "off"})
    assert r.status_code == 200 and r.json()["secrets"][0]["mode"] == "off"
    # back on: this request carries the key (the browser's half and this session's pad)
    r = api.put("/api/seal/away", json={"name": "mail.password", "mode": "until", "days": 30})
    assert r.status_code == 200 and r.json()["secrets"][0]["mode"] == "until"
    assert api.put("/api/seal/away", json={"name": "mail.password", "mode": "maybe"}).status_code == 400
    assert api.put("/api/seal/away", json={"name": "nope", "mode": "off"}).status_code == 404
    rows = usersmod.store_for(u).db.execute(
        "SELECT reason FROM audit WHERE action='seal.away'").fetchall()
    assert len(rows) == 2


def test_no_agent_tool_reaches_the_choice():
    from agentos import tools
    src = Path(tools.__file__).read_text()
    assert "set_away" not in src and "/api/seal/away" not in src


def test_the_card_draws_with_text_nodes():
    js = (Path(__file__).parent.parent / "agentos/ui/src/js/11o-seal.js").read_text()
    start = js.index("function sealAwaySelect")
    assert "innerHTML" not in js[start:start + 3000]


def test_a_backup_carries_the_service_key():
    from agentos import backup
    assert backup._vault_scope("away.json") == away.SCOPE
