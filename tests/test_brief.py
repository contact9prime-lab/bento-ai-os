"""The Brief: a mission delivers ITEMS a person acts on, not a message.

What these defend: an item is written through the gate with its mission and run
stamped by the agent (never by an argument); a re-run updates rather than
duplicates and a person's Done sticks; the page groups and counts; a decision
hands the answer back to the agent as a turn; the delivery digest and the
Telegram buttons are derived from the same rows; and every mission recipe
delivers through it.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import brief, jobs                                     # noqa: E402
from agentos.agent import Agent                                     # noqa: E402
from agentos.memory import Store                                    # noqa: E402
from agentos.policy import PDP, Principal                           # noqa: E402
from agentos.tools import TOOL_SCHEMAS, Toolbox                     # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return Store(tmp_path / "b.db")


def test_an_item_is_added_then_updated_by_its_key_and_done_sticks(store):
    a = brief.add(store, "inbox-triage", "r1", "needs_you", "Sign the SOW", who="Jane Doe",
                  due="Thu 24 Sep", draft="Hi Jane…", source={"type": "mail", "ref": "1"}, key="1")
    assert a["created"]
    b = brief.add(store, "inbox-triage", "r2", "needs_you", "Sign the revised SOW", who="Jane Doe",
                  due="Thu 24 Sep", key="1")
    assert not b["created"] and b["id"] == a["id"]                 # the same thing, updated
    assert store.brief_get(a["id"])["title"] == "Sign the revised SOW"
    brief.act(store, a["id"], "done")
    brief.add(store, "inbox-triage", "r3", "needs_you", "Sign the SOW (again)", key="1")
    assert store.brief_get(a["id"])["state"] == "done"             # a person's Done is not undone by a run
    # a different mission with the same key is a different item
    c = brief.add(store, "follow-ups", "r4", "fyi", "SOW thread", key="1")
    assert c["created"] and c["id"] != a["id"]


def test_the_page_groups_counts_and_carries_open_items_over(store):
    brief.add(store, "m", "r", "needs_you", "Sign", who="Jane")
    brief.add(store, "m", "r", "decide", "Pricing", options=["Accept", "Counter", "Hold"])
    brief.add(store, "m", "r", "fyi", "Invoice due")
    brief.add(store, "m", "r", "done", "Filed the receipts")
    # something from yesterday, still open, is still on today's page
    old = brief.add(store, "m", "r0", "needs_you", "Old ask", key="old")
    store.db.execute("UPDATE brief_items SET day='2020-01-01' WHERE id=?", (old["id"],))
    store.db.commit()
    pg = brief.page(store)
    assert [g["kind"] for g in pg["groups"]] == ["needs_you", "decide", "fyi", "done"]
    assert pg["counts"] == {"needs_you": 2, "decide": 1, "fyi": 1, "done": 1, "open": 5}
    assert brief.headline(pg["counts"]) == "2 need you · 1 decision · 1 FYI · 1 done for you"
    assert "Old ask" in [i["title"] for i in pg["items"]]
    brief.act(store, old["id"], "later")
    assert store.brief_get(old["id"])["state"] == "later"
    assert brief.headline(brief.page(store)["counts"]).startswith("2 need you")   # later still needs you


def test_a_decision_is_recorded_and_becomes_the_agent_s_next_turn(store):
    d = brief.add(store, "inbox-triage", "r", "decide", "Raj's pricing ask", who="Raj Patel",
                  body="$18 vs $22 for 50 seats", options=["Accept", "Counter at $20", "Hold"])
    with pytest.raises(ValueError, match="which choice"):
        brief.act(store, d["id"], "decide", "")
    item = brief.act(store, d["id"], "decide", "Counter at $20")
    assert item["state"] == "decided" and item["decision"] == "Counter at $20"
    prompt = brief.decide_prompt(item, "Counter at $20")
    assert "Raj's pricing ask" in prompt and "Counter at $20" in prompt and "sending always asks" in prompt
    assert "$18 vs $22" in prompt
    with pytest.raises(ValueError, match="no item"):
        brief.act(store, "nope", "done")
    with pytest.raises(ValueError, match="one of"):
        brief.act(store, d["id"], "eat")


def test_the_digest_and_the_buttons_come_from_the_same_rows(store):
    brief.add(store, "m", "r", "needs_you", "Sign the SOW", who="Jane", due="Thu")
    brief.add(store, "m", "r", "decide", "Pricing", options=["Accept", "Counter"])
    brief.add(store, "m", "r", "fyi", "Invoice")
    items = brief.page(store)["items"]
    text = brief.digest(items, "inbox-triage")
    assert text.splitlines()[0] == "▲ inbox-triage · 1 needs you · 1 decision · 1 FYI"
    assert "1. • Sign the SOW — Jane (by Thu)" in text and "Accept / Counter" in text
    rows = brief.telegram_rows(items)
    assert rows[0][0]["callback_data"].endswith(":done") and rows[0][1]["callback_data"].endswith(":later")
    assert [b["callback_data"].split(":")[-1] for b in rows[1]] == ["Accept", "Counter"]
    assert all(len(b["callback_data"]) <= 64 for row in rows for b in row)   # Telegram's limit
    said = brief.spoken(items)
    assert said.startswith("1 needs you, 1 decision, 1 FYI.") and "Sign the SOW, from Jane, by Thu." in said


def test_the_tool_stamps_the_mission_and_run_from_the_agent_not_the_model(tmp_path):
    c = {"agent_name": "Aria", "autonomy": "full", "max_steps": 6, "default_model": "",
         "workspace": str(tmp_path), "providers": {}, "memory": {"inject_facts": 0, "inject_user": 0}}
    store = Store(tmp_path / "t.db")
    tb = Toolbox(c, store)
    tb.pdp = PDP(c, store)
    events = []

    async def emit(ev):
        events.append(ev)

    async def approver(*a, **k):
        return True
    a = Agent(c, tb, "ollama/x", emit, approver, tool_filter=["brief_item"],
              principal=Principal("subagent", "assistant"), flow="inbox-triage")
    a.run_id = "run77"
    a._task_text = "x"
    out, ok, _, _ = asyncio.run(a.call_tool(
        "brief_item", {"kind": "needs_you", "title": "Sign the SOW", "who": "Jane",
                       "_flow": "somebody-else", "_run_id": "forged"}, "c1"))
    assert ok and "added in the Brief" in out
    it = brief.page(store)["items"][0]
    assert it["mission"] == "inbox-triage" and it["run_id"] == "run77"   # the agent's, not the model's
    assert store.brief_for_run("run77")
    out, ok, _, _ = asyncio.run(a.call_tool("brief_item", {"kind": "banana", "title": "x"}, "c2"))
    assert not ok and "kind must be one of" in out
    assert any(t["name"] == "brief_item" for t in TOOL_SCHEMAS)


def test_every_mission_delivers_through_the_brief(tmp_path):
    store = Store(tmp_path / "j.db")
    jobs.ensure_roster({}, store)
    cfg = {"mail": {"enabled": True, "host": "h", "user": "u", "password": "p"},
           "calendar": {"enabled": True, "kind": "ics", "url": "https://x/basic.ics"}}
    from tests.test_jobs import _answers_for
    for r in jobs.RECIPES:
        body = jobs.build(cfg, store, r.id, _answers_for(r, store))
        assert "brief_item" in body["permissions"]["tools"], r.id
        assert "brief_item" in body["mission"] and "DELIVER IT" in body["mission"], r.id


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        s = servermod.state["store"]
        s.db.execute("DELETE FROM brief_items")
        s.db.commit()
        yield cl, servermod


def test_the_routes_serve_the_page_and_act_on_an_item(client, monkeypatch):
    cl, servermod = client
    store = servermod.state["store"]
    it = brief.add(store, "m", "r", "decide", "Pricing", options=["Accept", "Counter"])
    pg = cl.get("/api/brief").json()
    assert pg["open"] == 1 and pg["headline"] == "1 decision" and pg["spoken"].startswith("1 decision.")

    async def fake_prompt(prompt, origin="schedule", title="", space_id=""):
        assert origin == "brief" and "Counter" in prompt
        return "cid-1", "Drafted the counter-offer."
    monkeypatch.setattr(servermod.state["scheduler"], "run_prompt", fake_prompt)
    r = cl.post(f"/api/brief/{it['id']}/act", json={"action": "decide", "choice": "Counter", "wait": True})
    assert r.status_code == 200
    j = r.json()
    assert j["item"]["state"] == "decided" and j["conversation_id"] == "cid-1"
    assert j["answer"] == "Drafted the counter-offer." and j["item"]["answer_cid"] == "cid-1"
    # without `wait` the tap returns at once: decided, the turn running behind it
    it2 = brief.add(store, "m", "r", "decide", "Renewal", options=["Yes", "No"])
    j = cl.post(f"/api/brief/{it2['id']}/act", json={"action": "decide", "choice": "Yes"}).json()
    assert j["started"] and j["item"]["state"] == "decided" and "answer" not in j
    assert cl.post(f"/api/brief/{it['id']}/act", json={"action": "eat"}).status_code == 400
    r = cl.post(f"/api/brief/{it['id']}/act", json={"action": "reopen"})
    assert r.json()["item"]["state"] == "open"


@pytest.mark.asyncio
async def test_a_telegram_button_acts_on_the_item_and_a_decision_starts_the_turn(tmp_path, monkeypatch):
    """The buttons under the digest are the same act(): Done sticks, and a
    decision hands the answer back to the agent through the toolbox's scheduler
    (the bridge has none of its own). Only the owner's taps count."""
    from agentos.telegram import TelegramBridge
    store = Store(tmp_path / "t.db")
    cfg = {"autonomy": "balanced", "default_model": "m", "policies": [],
           "workspace": str(tmp_path / "ws"), "telegram": {"bot_token": "x", "owner_chat_id": 111}}
    tb = Toolbox(cfg, store)
    tb.pdp = PDP(cfg, store)
    prompts, sent, calls = [], [], []

    class Sched:
        async def run_prompt(self, prompt, origin="schedule", title="", space_id=""):
            prompts.append((prompt, origin))
            return "cid-9", "Drafted the counter."
    tb.scheduler = Sched()

    async def _bc(_ev):
        pass
    tg = TelegramBridge(cfg, store, tb, _bc)

    async def _api(method, **kw):
        calls.append((method, kw))
        return {}

    async def _send(text, chat_id=None):
        sent.append(text)
    monkeypatch.setattr(tg, "_api", _api)
    monkeypatch.setattr(tg, "send", _send)

    a = brief.add(store, "m", "r", "needs_you", "Sign the SOW")
    d = brief.add(store, "m", "r", "decide", "Pricing", options=["Accept", "Counter"])
    msg = {"chat": {"id": 111}, "message_id": 5, "text": "▲ digest"}
    await tg._handle_callback({"id": "q1", "from": {"id": 222}, "data": f"br:{a['id']}:done", "message": msg})
    assert store.brief_get(a["id"])["state"] == "open"                 # not the owner: ignored
    await tg._handle_callback({"id": "q2", "from": {"id": 111}, "data": f"br:{a['id']}:done", "message": msg})
    assert store.brief_get(a["id"])["state"] == "done"
    assert any(m == "editMessageText" and "✓ done: Sign the SOW" in kw["text"] for m, kw in calls)
    await tg._handle_callback({"id": "q3", "from": {"id": 111}, "data": f"br:{d['id']}:decide:Counter", "message": msg})
    await tg._answer_task                                                 # the turn runs behind the tap
    it = store.brief_get(d["id"])
    assert it["state"] == "decided" and it["decision"] == "Counter" and it["answer_cid"] == "cid-9"
    assert prompts and prompts[0][1] == "brief" and "Counter" in prompts[0][0]
    assert sent[-1] == "Drafted the counter."
    # the digest with its buttons goes out as one message with an inline keyboard
    brief.add(store, "m", "r2", "needs_you", "Call the bank")          # something still open
    rows = brief.telegram_rows(brief.page(store)["items"])
    assert rows, "a Done item and a decided one carry no buttons; the open one does"
    await tg.send_brief("▲ digest", rows)
    assert calls[-1][0] == "sendMessage" and "reply_markup" in calls[-1][1]
