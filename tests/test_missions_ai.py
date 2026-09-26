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
    assert "approvalVisible(ev.id)" in case and "approvalFloat(ev)" in case, \
        "placed is not SEEN: a hidden card floats a copy"
    assert "label:'Review'" in case and "approvalReveal(ev.id)" in case, \
        "the toast is a door to the card, not a notice"
    # offsetParent is null for a position:fixed card, so it cannot be the test
    shown = ws[ws.index("function approvalShown"):ws.index("function approvalVisible")]
    assert "offsetParent" not in shown.split("*/")[-1]
    assert "delete APPROVALS[ev.id]" in ws, "an answered card stops being offered"
    act = (SRC / "08b-activity.js").read_text()
    assert "act-approving" in act and "approvalReveal()" in act, \
        "the 'waiting for you' line opens the card"


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
