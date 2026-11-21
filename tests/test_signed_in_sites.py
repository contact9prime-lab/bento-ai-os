"""Signed-in sites: an agent and its missions work on websites the person is signed in to.

Asked for as "login to my Instagram and start managing my content … the token would be there,
and then it can build a mission on it", then "think of the use cases around it": a social
account, a supplier portal, a store's admin, a page behind a login. One mechanism, the shared
browser the person signed in to (cdpbrowser), and four rules pinned here:

- what can't be taken back (post, send, submit, pay, delete) is read off the PAGE's own label,
  never the model's description, and is its own action, `browser.commit`;
- outside a mission set to post on its own, a post by any agent but the person's lead is a
  person's yes at every autonomy level;
- a mission grants exactly the sites it declares (read, act, and commit only when "auto");
- a sign-in wall with nobody at a screen reaches the account's own phone chats.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import cdpbrowser, flows, jobs                           # noqa: E402
from agentos.policy import PDP, Principal, action_of, person_rule      # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _page(uid="", seen=None, typed="", url="https://www.instagram.com/bento"):
    b = SimpleNamespace(uid=uid, seen=seen or {}, typed_ref=typed, running=True,
                        tab=lambda: {"url": url, "session": "s"})
    cdpbrowser._BROWSERS[uid] = b
    return b


@pytest.fixture
def store(tmp_path):
    from agentos.memory import Store
    return Store(tmp_path / "t.db")


@pytest.fixture(autouse=True)
def _clean():
    yield
    cdpbrowser._BROWSERS.clear()


SEEN = {"1": {"name": "Share", "tag": "button"},
        "2": {"name": "Write a caption…", "tag": "textarea"},
        "3": {"name": "Search", "tag": "input", "type": "search"},
        "4": {"name": "Shared with you", "tag": "a"},
        "5": {"name": "Add a comment…", "tag": "textarea"},
        "6": {"name": "Place order", "tag": "input", "type": "submit"},
        "7": {"name": "Next", "tag": "div", "role": "button"}}


def test_the_page_decides_what_cannot_be_taken_back():
    _page(seen=SEEN)
    c = lambda tool, **a: cdpbrowser.commit_of("", tool, a)               # noqa: E731
    assert c("browser_click", ref=1) == "“Share”"
    assert c("browser_click", ref=6) == "“Place order”"
    assert c("browser_click", ref=2) == "" and c("browser_click", ref=4) == "" and c("browser_click", ref=7) == ""
    # by words: judged on what the page shows under those words, and on the words themselves
    assert c("browser_click", text="Share") == "“Share”"
    assert c("browser_click", text="next") == ""
    # pressing Enter: a search box is not a send; a comment box (or an unknown field) is
    assert c("browser_type", ref=3, text="bento", submit=True) == ""
    assert c("browser_type", ref=5, text="thanks!", submit=True) != ""
    _page(seen=SEEN, typed="5")
    assert c("browser_key", key="Enter") != ""
    _page(seen=SEEN, typed="3")
    assert c("browser_key", key="Enter") == "" and c("browser_key", key="Tab") == ""
    # the model's own word for the target counts for nothing: ref 2 is a caption box
    assert c("browser_click", ref=2, text="Share") == ""


def test_the_loop_stamps_the_commit_and_the_gate_names_it():
    from agentos.agent import gate_fields
    _page(seen=SEEN)
    got = gate_fields("browser_click", {"ref": 1, "_commit": "", "_site": "evil.example"})
    assert got["_site"] == "instagram.com" and got["_commit"] == "“Share”"
    assert action_of("browser_click", got) == ("browser.commit", "site:instagram.com")
    plain = gate_fields("browser_click", {"ref": 7, "_commit": "“Share”"})
    assert "_commit" not in plain, "a caller's own _commit is dropped, not believed"
    assert action_of("browser_click", plain) == ("browser.act", "site:instagram.com")


def _decide(store, who, args, autonomy, flow=""):
    pdp = PDP({"autonomy": autonomy}, store)
    d = pdp.decide_tool(who, "browser_click", args, "risky", autonomy=autonomy,
                        surface="task" if who.kind != "user" else "gui", flow=flow, audit=False)
    return d, person_rule(who, "browser_click", args, d, pdp, level="risky")


def test_a_post_by_anyone_but_your_lead_is_a_persons_yes_at_full_autonomy(store):
    post = {"ref": 1, "_site": "instagram.com", "_commit": "“Share”"}
    d, must = _decide(store, Principal("subagent", "operator"), post, "full", flow="ig")
    assert d.effect == "ask" and "posts or sends as you" in must
    # an ordinary click at full autonomy is not held, and the lead follows the autonomy it was given
    d, must = _decide(store, Principal("subagent", "operator"), {"ref": 7, "_site": "instagram.com"}, "full", "ig")
    assert d.effect == "allow" and not must
    d, must = _decide(store, Principal("user", ""), post, "full")
    assert d.effect == "allow"
    d, _ = _decide(store, Principal("user", ""), post, "balanced")
    assert d.effect == "ask"


def test_a_mission_grants_exactly_the_sites_it_declares(store):
    f = flows.validate({"name": "ig", "mission": "m", "roster": ["operator"], "permissions": {"sites": [
        {"site": "https://www.Instagram.com/bento", "act": True, "publish": "auto"},
        {"site": "portal.acme.com", "act": True},
        {"site": "etsy.com"}, {"site": "not a site"}, {"site": "etsy.com"}]}})
    assert f["permissions"]["sites"] == [
        {"site": "instagram.com", "act": True, "publish": "auto"},
        {"site": "portal.acme.com", "act": True, "publish": "ask"},
        {"site": "etsy.com", "act": False, "publish": "ask"}]
    rows = {(g["action"], g["resource"]) for g in flows.declared_grants(f)}
    assert ("browser.commit", "site:instagram.com") in rows
    assert ("browser.act", "site:portal.acme.com") in rows and ("browser.commit", "site:portal.acme.com") not in rows
    assert ("browser.read", "site:etsy.com") in rows and ("browser.act", "site:etsy.com") not in rows
    note = next(g["note"] for g in flows.declared_grants(f) if g["resource"] == "site:instagram.com"
                and g["action"] == "browser.read")
    assert "doesn't allow automating" in note, "the site's own warning is on the consent line"
    # the "auto" grant posts only inside its own mission
    for g in flows.declared_grants(f):
        store.add_grant(g["principal_kind"], g["principal_id"], g["action"], g["resource"], g["effect"],
                        source="definition", source_ref="flow:ig")
    post = {"ref": 1, "_site": "instagram.com", "_commit": "“Share”"}
    d, must = _decide(store, Principal("subagent", "operator"), post, "balanced", flow="ig")
    assert d.effect == "allow" and not must
    d, _ = _decide(store, Principal("subagent", "operator"), post, "full", flow="another")
    assert d.effect == "ask"
    d, _ = _decide(store, Principal("subagent", "operator"),
                   {"ref": 1, "_site": "portal.acme.com", "_commit": "“Pay”"}, "full", flow="ig")
    assert d.effect == "ask", "an ask-mode site's payment waits for a person"


def test_the_site_recipes_build_and_say_who_presses_post(tmp_path, store):
    cfg = {"workspace": str(tmp_path)}
    for publish, commit in (("ask", False), ("auto", True)):
        f = jobs.build(cfg, store, "social-account", {"site": "instagram.com", "about": "Bento",
                                                       "publish": publish, "deliver": "report"})
        rows = {g["action"] for g in flows.declared_grants(flows.validate(f, store=None))}
        assert ("browser.commit" in rows) is commit
        assert ("asks the user first" in f["mission"]) is (not commit)
        assert "Keep the pace human" in f["mission"], "a strict site gets the pace line and its warning"
    p = jobs.build(cfg, store, "portal-fetch", {"site": "portal.acme.com", "deliver": "report"})
    assert p["permissions"]["sites"][0]["publish"] == "ask" and "Never pay" in p["mission"]
    w = jobs.build(cfg, store, "login-watch", {"site": "etsy.com", "page": "https://www.etsy.com/your/orders",
                                               "deliver": "report"})
    assert w["permissions"]["sites"] == [{"site": "etsy.com", "act": False, "publish": "ask"}]
    with pytest.raises(ValueError, match="on example.org, not etsy.com"):
        jobs.build(cfg, store, "login-watch", {"site": "etsy.com", "page": "https://example.org/x",
                                               "deliver": "report"})
    with pytest.raises(ValueError, match="not a site address"):
        jobs.build(cfg, store, "social-account", {"site": "my insta", "about": "x", "deliver": "report"})


def test_a_sign_in_is_recorded_listed_and_said_on_the_consent(tmp_path, monkeypatch):
    cdpbrowser.note_signed_in(tmp_path, "https://www.instagram.com/accounts/login", "signed in by you")
    cdpbrowser.note_signed_in(tmp_path, "nonsense", "x")
    rows = cdpbrowser.signed_in(tmp_path)
    assert [r["site"] for r in rows] == ["instagram.com"] and rows[0]["how"] == "signed in by you"
    assert cdpbrowser.is_signed_in(tmp_path, "www.instagram.com")
    assert not cdpbrowser.is_signed_in(tmp_path, "etsy.com")
    assert oct((tmp_path / "browser" / "sites.json").stat().st_mode)[-3:] == "600"
    from agentos import users
    monkeypatch.setattr(users, "home_for", lambda uid: tmp_path)
    view = jobs.sites_view([{"site": "instagram.com", "act": True, "publish": "ask"},
                            {"site": "etsy.com", "act": False, "publish": "ask"}])
    assert [v["signed_in"] for v in view] == [True, False]
    assert "asks you first" in view[0]["words"] and view[0]["warn"]


def test_a_wall_nobody_is_at_a_screen_for_goes_to_the_owners_phone(monkeypatch):
    b = _page(uid="ada")
    asked = []

    async def ask(att, png):
        asked.append("asked")

    async def fake_wait(b_, reason, timeout, phones):
        # while it waits, the owner's chat is the one the phone's reply is matched against
        assert "tg:42" in cdpbrowser._REACH.get("ada", {}) and set(phones) == {"tg:42"}
        return "[carry on]"
    monkeypatch.setattr(cdpbrowser, "_wait_for_person", fake_wait)
    monkeypatch.setattr(cdpbrowser, "_PRESENCE", [lambda uid: False])
    monkeypatch.setattr(cdpbrowser, "_OWNER_PHONES", [lambda uid: [("tg:42", ask, None)] if uid == "ada" else []])
    assert asyncio.run(cdpbrowser.tool_wait(b, "Sign in to instagram.com")) == "[carry on]"
    assert "ada" not in cdpbrowser._REACH, "the owner's chat is lent for the wait only"
    # nobody at a screen and no phone set up: said, with the Brief as the place to leave it
    monkeypatch.setattr(cdpbrowser, "_OWNER_PHONES", [lambda uid: []])
    said = asyncio.run(cdpbrowser.tool_wait(b, "Sign in"))
    assert said.startswith("[nobody here]") and "needs_you" in said


def test_an_upload_gives_a_site_only_your_own_files(tmp_path, monkeypatch):
    from agentos.tools import Toolbox
    from agentos.memory import Store
    ws = tmp_path / "work"
    ws.mkdir()
    (ws / "post.png").write_bytes(b"\x89PNG")
    (tmp_path / "secret.txt").write_text("no")
    tb = Toolbox({"workspace": str(ws)}, Store(tmp_path / "t.db"))
    seen = []

    async def do(what):
        seen.append(what)
        return "gave"
    monkeypatch.setattr(tb, "_browser_do", do)
    assert asyncio.run(tb.browser_upload(str(tmp_path / "secret.txt"))).startswith("[refused]")
    assert asyncio.run(tb.browser_upload("../secret.txt")).startswith("[refused]")
    assert asyncio.run(tb.browser_upload("nope.png")).startswith("[error]")
    assert asyncio.run(tb.browser_upload("post.png")) == "gave" and len(seen) == 1


def test_the_tools_are_classified_offered_and_drawn():
    from agentos import executors
    from agentos.tools import SAFE_TOOLS, TOOL_SCHEMAS
    names = {t["name"] for t in TOOL_SCHEMAS}
    assert {"browser_sign_in", "browser_sites", "browser_upload"} <= names
    assert {"browser_sign_in", "browser_sites"} <= SAFE_TOOLS and "browser_upload" not in SAFE_TOOLS
    assert {"browser_sign_in", "browser_sites", "browser_upload"} <= set(executors.WORKSPACE_DOOR_TOOLS)
    assert action_of("browser_sign_in", {"site": "https://www.instagram.com/"}) == ("browser.read", "site:instagram.com")
    ui = "".join(p.read_text() for p in (ROOT / "agentos/ui/src/js").glob("*.js"))
    assert "function renderSites" in ui and "/api/sites/signin" in ui and "'Websites','Websites'" in ui
    assert "n.kind==='choice'" in ui and "job-signin" in ui
    main = (ROOT / "agentos/__main__.py").read_text()
    assert 'verb("sites"' in main and "def _sites_cli" in main


def test_a_commit_card_names_what_is_pressed_not_a_ref():
    from agentos import approvalcard
    c = approvalcard.card("browser_click", {"ref": 3, "_site": "postly.example", "_commit": "“Share”"})
    assert "Share" in c["body"] and "postly.example" in c["body"] and "ref" not in c["body"]
    c = approvalcard.card("browser_click", {"ref": 3})
    assert "ref: 3" in c["body"]
