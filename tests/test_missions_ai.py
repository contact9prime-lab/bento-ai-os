"""Building a mission (and a specialist) by describing it, on whatever brain answers.

Reported as: "When I am building a new agent in the Mission Build section it doesn't
work" and "I should be able to build a mission via AI directly". The drafts asked only
`default_model`, so on a machine whose brain is Claude Code they said "no model
configured" — and Missions had no place to describe one at all outside Build.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from fastapi.testclient import TestClient                          # noqa: E402

from agentos import executors as execmod                           # noqa: E402
from agentos import flows as flowsmod                              # noqa: E402
from agentos import server as servermod                            # noqa: E402
from agentos.memory import Store                                   # noqa: E402

SRC = Path(__file__).parent.parent / "agentos" / "ui" / "src" / "js"
TOOLS = [{"name": "list_dir", "description": "list a folder"},
         {"name": "save_report", "description": "write a report"}]

FLOW_JSON = """{"name":"downloads-watch","description":"sort new downloads",
 "mission":"When a file lands in ~/Downloads, say what it is.",
 "new_agents":[{"name":"sorter","soul":"You look at new files.","tools":["list_dir"]}],
 "roster":[{"subagent":"sorter","why":"it looks"}],
 "permissions":{"tools":["list_dir"],"memory":"read-space"},
 "sinks":[{"kind":"origin"}],
 "triggers":[{"kind":"os_event","config":{"event":"file_change","path":"~/Downloads"}}]}"""

AGENT_JSON = """{"name":"invoice-clerk","soul":"You read invoices and file them.",
 "tools":["list_dir"],"autonomy_cap":"ask"}"""


@pytest.fixture()
def store(tmp_path):
    return Store(tmp_path / "t.db")


@pytest.fixture()
def executor_brain(monkeypatch):
    """The machine's brain is an installed agent, and there is NO provider model."""
    asked = []

    async def fake_forward(engine, text, cfg, cwd, *a, **k):
        asked.append((engine, text))
        return (AGENT_JSON if "You design SUBAGENTS" in text else FLOW_JSON), None

    monkeypatch.setattr(execmod, "resolve_engine", lambda cfg: "claude-code")
    monkeypatch.setattr(execmod, "forward", fake_forward)
    return asked


def test_a_mission_is_drafted_on_an_executor_brain(store, executor_brain):
    d = asyncio.run(flowsmod.compose({}, store, "watch my Downloads folder", TOOLS))
    assert not d.get("error"), d
    assert d["name"] == "downloads-watch"
    assert d["model"] == "claude-code", "the draft says which brain designed it"
    assert executor_brain and executor_brain[0][0] == "claude-code"


def test_a_specialist_is_drafted_on_an_executor_brain(store, executor_brain):
    d = asyncio.run(flowsmod.compose_subagent({}, store, "someone to file invoices", TOOLS))
    assert not d.get("error"), d
    assert d["name"] == "invoice-clerk"


def test_an_executor_that_fails_says_so_in_its_own_words(store, monkeypatch):
    async def broken(engine, text, cfg, cwd, *a, **k):
        return "[error] not signed in", None
    monkeypatch.setattr(execmod, "resolve_engine", lambda cfg: "claude-code")
    monkeypatch.setattr(execmod, "forward", broken)
    d = asyncio.run(flowsmod.compose({}, store, "watch my Downloads", TOOLS))
    assert d["error"] == "claude-code could not answer: not signed in"


def test_the_draft_route_carries_its_triggers(executor_brain):
    """Without them the card read "Starts when you run it" beside a folder trigger it
    did have — the triggers live in their own table, not on the flow row."""
    with TestClient(servermod.app) as c:
        store = servermod.state["store"]
        for table in ("flows", "flow_triggers", "grants", "tasks"):
            store.db.execute(f"DELETE FROM {table}")
        store.db.commit()
        r = c.post("/api/flows/draft", json={"request": "watch my Downloads folder"})
        assert r.status_code == 200, r.text
        body = r.json()
        f = body["flow"]
        assert not f["enabled"], "a draft lands switched off: Enable is the act of granting"
        assert [t["kind"] for t in f["triggers"]] == ["os_event"]
        assert f["triggers"][0]["config"]["path"] == "~/Downloads"
        # the consent list is what ENABLING would grant, computed before it is granted
        assert body["would_grant"], "the card shows what turning it on would allow"
        assert not [g for g in store.list_grants() if g["source_ref"] == "flow:downloads-watch"]


def test_missions_run_tab_offers_describe_your_own():
    js = (SRC / "14a-jobs.js").read_text()
    assert "Describe your own" in js
    assert "/api/flows/draft" in js
    # a fabric_defs broadcast re-renders the tab while the draft is awaited: the draft
    # must live in JOBS and the output be looked up AGAIN after the await, or the card
    # is written into a detached node and vanishes (found in the browser)
    assert "JOBS.aiDraft=r" in js
    body = js[js.index("async function jobDraftAI"):js.index("function jobAIDraftHTML")]
    after = body[body.index("await "):]
    assert "querySelector('.job-ai-out')" in after or ".job-ai-out" in after
    assert "JOBS.aiDraft?jobAIDraftHTML(JOBS.aiDraft)" in js
    # plain words, never the raw action names
    assert "function jobGrantWords" in js


# ---------------------------------------------------------------------------
# the rest of the same report: an approval nobody could reach, a bar that lost
# questions, an Office that went missing from the dock
# ---------------------------------------------------------------------------

def test_an_approval_can_always_be_reached():
    """A hand-over to the toolsmith waited five minutes on a card placed inside the
    prompt bar's answer card, hidden the moment a window opened."""
    ws = (SRC / "09-websocket.js").read_text()
    case = ws[ws.index("case 'approval_request'"):ws.index("case 'error'")]
    assert "APPROVALS[ev.id]=ev" in case
    assert "approvalHome(ev.id)" in case and "approvalWatch()" in case, \
        "placed is not SEEN: a card is re-homed while it waits"
    home = ws[ws.index("function approvalHome"):ws.index("function approvalShownArea")]
    # "Open in Chat" closes the bar's answer card and took the approval with it: the
    # open conversation draws it, anything else floats it
    assert "ev.conversation_id===currentConv" in home and "approvalFloat(ev)" in home
    watch = ws[ws.index("function approvalWatch"):ws.index("function approvalReveal")]
    assert "clearInterval" in watch and "document.hidden" in watch, "it stops itself, and sleeps"
    assert "label:'Review'" in case and "approvalReveal(ev.id)" in case, \
        "the toast is a door to the card, not a notice"
    # offsetParent is null for a position:fixed card, so it cannot be the test
    shown = ws[ws.index("function approvalShown"):ws.index("function approvalVisible")]
    assert "offsetParent" not in shown.split("*/")[-1]
    assert "elementFromPoint" in shown, "a card under a window is not seen"
    assert "delete APPROVALS[ev.id]" in ws, "an answered card stops being offered"
    act = (SRC / "08b-activity.js").read_text()
    assert "act-approving" in act and "approvalReveal()" in act, \
        "the 'waiting for you' line opens the card"
    assert "ap-review" in act and "'Review'" in act, "and says so with a button"


def test_each_question_from_the_bar_is_its_own_thread():
    js = (SRC / "28a-omnibar.js").read_text()
    assert "'◉ Desktop'" not in js, "one thread for every question read as lost"
    thread = js[js.index("async function omniThread"):js.index("function omniCard")]
    assert "title:omniTitle(q)" in thread
    assert "c.dataset.cid===OMNI.cid" in thread, "a follow-up on an open card continues it"
    assert "card.dataset.cid" in js, "Open in Chat goes to THIS card's thread"


def test_removing_from_the_dock_says_the_way_back():
    js = (SRC / "06-icon-layout.js").read_text()
    menu = js[js.index("function dockCtxMenu"):]
    menu = menu[:menu.index("\n}\n")]
    assert "Pin to dock" in menu and "label:'Undo'" in menu


def test_the_agent_editor_names_its_steps_and_saves_from_any_of_them():
    """"The UI for the agent needs to be better": three unlabelled dots, fields half the
    dialog wide, and a drafted agent's Save two pages away."""
    js = (SRC / "13-fabric.js").read_text()
    draw = js[js.index("function drawSAW"):js.index("function sawRefreshList")]
    assert "SAW_STEPS" in draw and 'role="tab"' in draw, "the steps are named, and jumpable"
    assert "onclick=\"sawSave()\"" in draw
    assert draw.count("sawSave()") == 1, "one Save, on every step — not only the last"
    assert "New subagent" not in js, "on screen it is an agent"
    assert "saw-cap" in draw, "trust is three plain choices, not a select of jargon"
    save = js[js.index("async function sawSave"):js.index("function testSubagent")]
    assert "apiJSON('/api/subagents'" in save and "could not save" in save, \
        "a refused save is said, and the editor stays open"
    css = (Path(__file__).parent.parent / "agentos/ui/src/css/09-chat-team-docs.css").read_text()
    assert ".saw-box{" in css and "@media (max-width:640px)" in css[css.index(".saw-box{"):]
    assert "min-height:var(--tap" in css[css.index(".saw-tabs"):css.index(".saw-foot")]


# ---------------------------------------------------------------------------
# "Does it also build the persona, the image and the skills?" — it does now, and all
# three are shown and editable before anything is written
# ---------------------------------------------------------------------------

import json as _json                                                # noqa: E402
import types                                                       # noqa: E402

from agentos import __main__ as climod                             # noqa: E402
from agentos import avatars as avmod                               # noqa: E402

FULL_AGENT = _json.dumps({
    "name": "invoice-clerk", "soul": "You read invoices and file them. Never pay anything.",
    "tools": ["list_dir"], "skills": ["writing"],
    "look": {"hair": "auburn", "style": "bob", "glasses": True, "outfit": "blazer",
             "shirt": "green", "wings": "yes", "note": "a careful clerk"},
    "new_skills": [
        {"name": "Invoice Filing", "description": "how to file one",
         "content": "## Filing\n1. Read the sender and amount.\n2. Name it by date."},
        {"name": "house-style", "description": "clashes", "content": "the model's own version of it"},
        {"name": "x", "content": "too short"}]})


@pytest.fixture()
def full_brain(monkeypatch):
    async def fake_forward(engine, text, cfg, cwd, *a, **k):
        return FULL_AGENT, None
    monkeypatch.setattr(execmod, "resolve_engine", lambda cfg: "claude-code")
    monkeypatch.setattr(execmod, "forward", fake_forward)


def test_a_draft_brings_a_persona_a_look_and_skills(store, full_brain):
    store.save_skill("house-style", "ours", "the person's own house style")
    d = asyncio.run(flowsmod.compose_subagent({}, store, "file my invoices", TOOLS))
    assert d["soul"].startswith("You read invoices")
    # the look is the closed set: an invented field is dropped and NAMED, and the
    # blazer is the lead's — a specialist never takes it
    assert d["look"]["glasses"] is True and d["look"]["style"] == "bob"
    assert "outfit" not in d["look"] and "wings" not in str(d["look"])
    assert any("blazer" in w for w in d["warnings"])
    assert d["look_note"] == "a careful clerk"
    # a new skill is PROPOSED (never written); one that exists is attached, not replaced
    assert [s["name"] for s in d["new_skills"]] == ["invoice-filing"]
    assert "house-style" in d["skills"]
    assert store.get_skill("invoice-filing") is None, "drafting writes nothing"
    assert store.get_skill("house-style")["content"] == "the person's own house style"
    assert any("unusable" in w for w in d["warnings"])


def test_saving_creates_the_kept_skills_and_the_look_and_never_overwrites(store):
    store.save_skill("house-style", "ours", "the person's own house style")
    rep = flowsmod.save_specialist(store, {}, {
        "name": "invoice-clerk", "soul": "You file.", "tools": ["list_dir"], "skills": [],
        "new_skills": [{"name": "invoice-filing", "description": "d", "content": "## edited by the person"},
                       {"name": "house-style", "description": "d", "content": "a model's rewrite"}],
        "look": {"hair": 5, "style": "bun", "glasses": True}})
    assert rep["skills_created"] == ["invoice-filing"] and rep["skills_kept"] == ["house-style"]
    assert store.get_skill("invoice-filing")["content"] == "## edited by the person"
    assert store.get_skill("house-style")["content"] == "the person's own house style"
    assert set(store.get_subagent("invoice-clerk")["skills"]) == {"invoice-filing", "house-style"}
    rec = avmod.recipe_for(store, "invoice-clerk")
    assert rec["style"] == "bun" and rec["glasses"] is True and not rep["look_error"]


def test_a_look_is_previewed_without_writing_anything():
    with TestClient(servermod.app) as c:
        store = servermod.state["store"]
        before = store.avatar_get("not-saved-yet")
        r = c.post("/api/avatars/preview", json={"description": "grey bun and a violet hoodie",
                                                 "name": "not-saved-yet"})
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["patch"]["style"] == "bun" and b["recipe"]["outfit"] == "hoodie"
        assert "grey" in b["about"] and store.avatar_get("not-saved-yet") == before
        assert c.post("/api/avatars/preview", json={"description": "zz"}).status_code == 400


def test_the_editor_shows_and_edits_all_three():
    js = (SRC / "13-fabric.js").read_text()
    draw = js[js.index("function drawSAW"):js.index("function sawRefreshList")]
    assert "id=\"sw-soul\"" in draw and "saw-drafted" in draw, "the drafted persona is shown, editable"
    assert "sawLook()" in draw and "Give it this look when I save" in draw
    assert "Create this skill" in draw and "SAW.newSkills[${i}].content=this.value" in draw
    face = js[js.index("function sawFace"):js.index("function drawSAW")]
    assert "avatarRecipeImg(SAW.lookRec" in face, "the drafted face, through the one door"
    look = js[js.index("async function sawLook"):js.index("function drawSAW")]
    assert "/api/avatars/preview" in look, "a look for an unsaved agent writes nothing"
    save = js[js.index("async function sawSave"):js.index("function testSubagent")]
    assert "k.on&&" in save and "new_skills" in save and "SAW.useLook" in save
    assert "kept your existing" in save, "a skill not replaced is said"


def test_a_terminal_can_draft_one_and_nothing_is_saved_without_a_yes(store, full_brain, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", types.SimpleNamespace(isatty=lambda: False))
    args = types.SimpleNamespace(name="file", model="my", more=["invoices"], yes=False, user="")
    assert climod._team_draft(args, {}, store, False) == 0
    out = capsys.readouterr().out
    assert "Persona" in out and "You read invoices" in out and "Look" in out
    assert "New skill invoice-filing" in out and "## Filing" in out, "the skill's whole text is shown"
    assert "not saved" in out and store.get_subagent("invoice-clerk") is None
    args.yes = True
    assert climod._team_draft(args, {}, store, False) == 0
    assert store.get_subagent("invoice-clerk") and store.get_skill("invoice-filing")


# ---------------------------------------------------------------------------
# "The agent UI takes a lot of time to open; the New agent button is out of place"
# ---------------------------------------------------------------------------

from agentos import providers as provmod                           # noqa: E402


def test_the_model_list_asks_every_provider_at_once_and_keeps_it(monkeypatch):
    """Measured with four endpoints answering in 2s each: 8.35s on every call before
    (one after another, nothing kept), 2.0s the first time after, ~0 for a minute."""
    calls = []

    async def slow_ollama(base):
        calls.append("ollama"); await asyncio.sleep(0.3); return ["llama3"]

    async def slow_openai(base, key=""):
        calls.append(base); await asyncio.sleep(0.3); return ["gpt-x"]
    monkeypatch.setattr(provmod, "ollama_models", slow_ollama)
    monkeypatch.setattr(provmod, "openai_models", slow_openai)
    provmod.forget_models()
    cfg = {"providers": {"ollama": {"enabled": True, "base_url": "o"},
                         "openai": {"enabled": True, "api_key": "k", "base_url": "http://a/v1"},
                         "openrouter": {"enabled": True, "api_key": "k", "base_url": "http://b/v1"},
                         "custom": {"enabled": True, "base_url": "http://c/v1"}}}
    import time as _t
    t0 = _t.monotonic()
    first = asyncio.run(provmod.available_models(cfg))
    took = _t.monotonic() - t0
    assert took < 0.8, f"asked one after another ({took:.2f}s for four 0.3s answers)"
    assert len(calls) == 4 and {m["provider"] for m in first} == {"ollama", "openai", "openrouter", "custom"}
    asyncio.run(provmod.available_models(cfg))
    assert len(calls) == 4, "kept for a minute"
    cfg["providers"]["custom"]["models"] = ["pinned"]          # a settings change is seen at once
    asyncio.run(provmod.available_models(cfg))
    assert len(calls) == 8
    provmod.forget_models()


def test_the_editor_opens_before_the_models_arrive():
    js = (SRC / "13-fabric.js").read_text()
    open_ = js[js.index("async function openSAW"):js.index("function sawModelsArrive")]
    waited = open_[open_.index("await Promise.all"):open_.index("drawSAW()")]
    assert "/api/models" not in waited, "the editor must not wait on every provider to draw"
    assert "sawModelsArrive" in open_
    draw = js[js.index("function drawSAW"):js.index("function sawRefreshList")]
    assert "!SAW.models.some(m=>m.id===d.model)" in draw, "a pinned model survives the list arriving late"


def test_new_agent_is_in_the_list_header():
    js = (SRC / "11e-hands.js").read_text()
    lst = js[js.index("async function renderAgentsList"):js.index("async function agentEdit")]
    assert 'class="ag-head"' in lst and "ag-new" in lst
    assert lst.count("agentEdit('')") + lst.count("agentEdit(\\'\\')") == 2, \
        "the header, and the could-not-load fallback — and not a third at the end of the list"
