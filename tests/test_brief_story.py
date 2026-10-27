"""The Brief comes on a schedule, and it comes as something you watch.

Asked for as "the brief experience is not very good: if that is the first thing I need to hear
after a while, it must be immersive", then "the brief should periodically check, based on the
schedule, and give a brief, which is what the brief is about". Measured on the owner's own
Brief: 24 open items in one long list, two of them twice, nothing on top that said what mattered.

- the schedule is the person's (`brief` USER_KEY): times, weekdays, an AI summary, Telegram;
  a scheduled moment is delivered once, and a machine that was off delivers the same day only;
- the story is built from the rows alone (counts with their source, what needs you, decisions
  with their choices, where it comes from, what's worth knowing), every scene in the Stage's
  closed set, with a line for the narrator;
- the same item filed by several runs is one card, acted on together;
- Play, the "ready" toast and the welcome back all open the same story.
"""
import asyncio
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import brief, stage, users                              # noqa: E402
from agentos.memory import Store                                     # noqa: E402

ROOT = Path(__file__).parent.parent


def _at(h, m=0, day=19):
    return datetime(2026, 10, day, h, m).timestamp()     # 19 Oct 2026 is a Monday


def test_the_schedule_is_checked_and_delivered_once():
    cfg = {}
    s = brief.set_schedule(cfg, times=["8:00", "18:30"], days="weekdays")
    assert s["times"] == ["08:00", "18:30"] and s["days"] == "weekdays"
    with pytest.raises(ValueError, match="HH:MM"):
        brief.set_schedule(cfg, times=["25:00"])
    s = brief.schedule(cfg)
    assert brief.due_at(s, _at(7, 59)) == 0
    assert brief.due_at(s, _at(8, 1)) == _at(8)
    cfg["brief"]["last_at"] = _at(8)
    assert brief.due_at(brief.schedule(cfg), _at(12)) == 0, "once"
    assert brief.due_at(brief.schedule(cfg), _at(19)) == _at(18, 30)
    assert brief.due_at(brief.schedule(cfg), _at(9, day=24)) == 0, "a Saturday, on weekdays only"
    assert brief.next_at(brief.schedule(cfg), _at(19)) == _at(8, day=20)
    assert brief.schedule({"brief": {"times": []}})["times"] == [] and brief.next_at(brief.schedule({"brief": {"times": []}}), _at(9)) == 0
    assert "brief" in users.USER_KEYS


def _item(i, kind, title, mission="desk", state="open", created=0.0):
    return {"id": f"b{i}", "kind": kind, "title": title, "mission": mission, "state": state,
            "who": "", "due": "", "options": ["A", "B"] if kind == "decide" else [],
            "updated_at": i, "created_at": created or i}


def test_the_same_item_from_several_runs_is_one_card():
    items = [_item(1, "needs_you", "The auditor failed Research's task"),
             _item(2, "needs_you", "The auditor failed Research's task"),
             _item(3, "fyi", "Lot size is 65")]
    out = brief.fold(items)
    card = next(i for i in out if i["kind"] == "needs_you")
    assert len(out) == 2 and card["id"] == "b2" and card["twins"] == ["b1"], "newest kept"
    assert brief.counts_of(out)["needs_you"] == 1


def test_the_story_is_the_rows_in_the_stages_shapes():
    items = [_item(i, k, f"T{i}", m) for i, (k, m) in enumerate(
        [("needs_you", "research"), ("needs_you", "tech"), ("decide", "research"), ("fyi", "tech"),
         ("needs_you", "research"), ("needs_you", "research"), ("needs_you", "tech")], 1)]
    scenes = brief.story(items, _at(9), since=4.5, agent="Aria")
    kinds = [s["kind"] for s in scenes]
    assert kinds == ["numbers", "steps", "steps", "chart", "steps"]
    for sc in scenes:
        clean, dropped = stage.clean(sc)
        assert not dropped and clean["say"], sc["title"]
    first = scenes[0]
    assert first["caption"].startswith("Good morning. 5 need you") and first["source"] == "your Brief"
    assert {"label": "New since the last Brief", "value": "3"} in first["items"]
    assert len(scenes[1]["items"]) == brief.SHOW and "1 more in the Brief" in scenes[1]["caption"]
    assert brief.story([], _at(20))[0]["caption"] == "Good evening. Nothing is waiting for you."
    assert "only what is in the list" in brief.summary_prompt(items)


def test_play_builds_the_story_in_the_brief_chat(monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        store = servermod.state["store"]
        brief.add(store, "research", "", "needs_you", "Share the workspace")
        brief.add(store, "research", "", "decide", "Buy the data?", options=["Yes", "No"])
        pg = cl.get("/api/brief").json()
        assert pg["schedule"]["times"] == ["08:00"] and pg["schedule"]["next_at"] > time.time()
        r = cl.post("/api/brief/story").json()
        assert r["scenes"] >= 3 and r["headline"].startswith("1 needs you")
        st = stage.story(store, r["cid"], r["answer_to"])
        assert [s["scene"]["kind"] for s in st][:3] == ["numbers", "steps", "steps"]
        conv = store.get_conversation(r["cid"])
        assert conv["origin"] == "brief" and conv["title"].startswith("Brief · ")
        again = cl.post("/api/brief/story").json()
        assert again["cid"] == r["cid"] and again["answer_to"] != r["answer_to"], "one chat a day, a story per play"
        assert cl.put("/api/brief/schedule", json={"times": ["7:5"]}).status_code == 400
        assert cl.put("/api/brief/schedule", json={"times": ["07:05"], "summary": "ai"}).json()["summary"] == "ai"


def test_a_scheduled_brief_goes_to_the_phone_and_history(monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app):
        store = servermod.state["store"]
        servermod.state["cfg"]["brief"] = {"times": ["08:00"], "summary": "plain", "telegram": True}
        brief.add(store, "research", "", "needs_you", "Share the workspace")
        sent = []

        class TG:
            def _t(self):
                return {"enabled": True, "bot_token": "1:T", "owner_chat_id": 5}

            async def send_brief(self, text, rows, chat_id=None):
                sent.append(("digest", text.splitlines()[0]))

            async def send_stage(self, cid, reply, chat_id):
                sent.append(("story", cid))
        real = servermod.state.get
        monkeypatch.setattr(servermod.state, "get", lambda k, d=None: TG() if k == "telegram" else real(k, d))
        due = _at(8)
        r = asyncio.run(servermod._brief_deliver(scheduled_at=due))
        assert sent[0] == ("digest", "▲ Your 08:00 Brief") and sent[1] == ("story", r["cid"])
        assert servermod.state["cfg"]["brief"]["last_at"] == due
        row = store.db.execute("SELECT task_id, status FROM task_runs WHERE task_id='brief'").fetchone()
        assert tuple(row) == ("brief", "ok"), "a scheduled Brief is in Missions → History"


def test_the_page_plays_it_and_says_so_once():
    js = (ROOT / "agentos/ui/src/js/24b-brief.js").read_text()
    for name in ("function briefPlay(", "function briefPlayStory(", "function briefReady(",
                 "function briefWelcome(", "function briefSchedSave(", "function briefWalk("):
        assert name in js
    assert "it.twins.map" in js, "Done on a folded card answers every run that filed it"
    ws = (ROOT / "agentos/ui/src/js/09-websocket.js").read_text()
    assert "ev.action==='ready'" in ws and "briefWelcome" in ws
    srv = (ROOT / "agentos/server.py").read_text()
    loop = srv[srv.index("async def _stage_loop"):][:1500]
    assert "briefmod.due_at(" in loop and '["last_at"] = due' in loop, "claimed before it runs: once"
    assert 'first=not sched["last_at"]' in loop, "the first check after an update only marks the time"


def test_a_brief_card_says_what_it_is_and_opens_its_item():
    """Reported with the morning Brief on the Stage: "I can't click or do anything there"
    and "context of what the brief is trying to do is missing". Cards were numbered steps
    joined by arrows, titles cut mid-word, a decision showed bare options, and nothing
    opened the item."""
    long = "Add the SUPERSEDED banner to the old audit plan file (no one on the team can edit it today, so the wrong plan keeps being read by people)"
    items = [{**_item(1, "needs_you", long, "bento-growth-launches-content-desk"), "id": "a1b2c3d4e5",
              "who": "auditor", "body": "The plan was replaced last week. Readers still land on it."},
             {**_item(2, "decide", "Where should the demo GIF go?"), "id": "0f0f0f0f0f",
              "body": "The README links it.", "options": ["docs/assets/", ".github/"]}]
    scenes = [stage.clean(s)[0] for s in brief.story(items, _at(9))]
    first, need, dec = scenes[0], scenes[1], scenes[2]
    assert "what your missions filed for you" in first["caption"] and "Tap a card" in first["caption"]
    assert first["items"][0]["open"] == "brief:needs_you" and first["items"][0]["note"]
    assert need["ordered"] is False and dec["ordered"] is False, "a list, not a sequence"
    card = need["items"][0]
    assert card["open"] == "brief:a1b2c3d4e5"
    assert card["title"].endswith("…") and " ".join(card["title"][:-1].split()) in long, "cut at a word"
    assert card["text"] == "The plan was replaced last week." and "from bento growth" in card["note"]
    assert dec["items"][0]["text"] == "The README links it. Choices: docs/assets/ · .github/"
    assert "Tap one to choose" in dec["caption"]


def test_a_scene_can_only_open_a_brief_door():
    sc, _ = stage.clean({"kind": "steps", "title": "x", "items": [
        {"title": "a", "open": "brief:abcdef12"}, {"title": "b", "open": "javascript:alert(1)"},
        {"title": "c", "open": "app:settings"}]})
    assert [i["open"] for i in sc["items"]] == ["brief:abcdef12", "", ""]
    assert sc["ordered"] is True, "a model's steps stay steps"
