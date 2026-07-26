"""Proactivity layer — triggers, triage gates, suggestion rate limits, the metric.

The promise: the OS may start turns, but only through rate-limited, user-created
triggers and hard-gated background passes — never a runaway loop.
"""

import asyncio
import os
import tempfile
import time
from collections import deque

os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import attention                  # noqa: E402
from agentos.memory import Store               # noqa: E402
from agentos.scheduler import Scheduler        # noqa: E402


def _sched(tmp_path):
    store = Store(tmp_path / "t.db")
    return Scheduler({"autonomy": "balanced"}, store, None, None), store


class FakeNotifd:
    def __init__(self, items=None):
        self.items = deque(items or [])
        self.dnd = False


# ---------------------------------------------------------------------------
# triggers
# ---------------------------------------------------------------------------

def test_create_trigger_validation(tmp_path):
    s, _ = _sched(tmp_path)
    assert "[error]" in s.create_trigger("nope", "do a thing")
    assert "[error]" in s.create_trigger("notification", "")
    assert "[error]" in s.create_trigger("notification", "p")          # no match
    assert "[error]" in s.create_trigger("file_change", "p")           # no path
    assert "trigger " in s.create_trigger("notification", "p", match="deploy")


def test_notification_trigger_fires_and_cools_down(tmp_path):
    s, store = _sched(tmp_path)
    s.create_trigger("notification", "summarize it", match="deploy", cooldown_secs=300)
    fired = s.offer_notification({"app": "ci", "summary": "deploy finished", "body": ""})
    assert len(fired) == 1
    # cooldown: an identical notification straight after must NOT fire
    assert s.offer_notification({"app": "ci", "summary": "deploy finished", "body": ""}) == []
    # and a non-matching one never fires
    assert s.offer_notification({"app": "mail", "summary": "newsletter", "body": ""}) == []


def test_notification_match_regex_and_substring(tmp_path):
    m = Scheduler._notif_matches
    item = {"app": "Mail", "summary": "Invoice #42 due", "body": "pay by friday"}
    assert m("invoice", item)                    # case-insensitive substring
    assert m(r"invoice #\d+", item)              # regex
    assert not m("calendar", item)
    assert not m("", item)


def test_file_trigger_baselines_then_fires(tmp_path):
    s, _ = _sched(tmp_path)
    f = tmp_path / "watched.txt"
    f.write_text("v1")
    s.create_trigger("file_change", "react to it", path=str(f), cooldown_secs=0)
    s._poll_file_triggers()                       # baseline — must not fire
    t = s._trigger_tasks("file_change")[0]
    assert not t.get("last_fired")
    f.write_text("v2")
    os.utime(f, (time.time() + 5, time.time() + 5))
    s._poll_file_triggers()
    t = s._trigger_tasks("file_change")[0]
    assert t.get("last_fired")


def test_idle_trigger_fires_once_per_idle_period(tmp_path, monkeypatch):
    from agentos import knowledge
    s, _ = _sched(tmp_path)
    s.create_trigger("idle", "check in", minutes=1, cooldown_secs=0)
    monkeypatch.setattr(knowledge, "last_turn_ts", lambda: time.time() - 120)
    s._poll_idle_triggers()
    t = s._trigger_tasks("idle")[0]
    first = t.get("last_fired")
    assert first
    s._poll_idle_triggers()                       # same idle period → no refire
    assert s._trigger_tasks("idle")[0]["last_fired"] == first


# ---------------------------------------------------------------------------
# triage gates (no model may be called below the thresholds)
# ---------------------------------------------------------------------------

def test_triage_gate_below_batch(monkeypatch):
    attention._state["last_triage"] = time.time()
    nd = FakeNotifd([{"id": 1, "summary": "x", "read": False}])
    assert not attention.should_triage(nd)


def test_triage_gate_at_batch():
    attention._state["last_triage"] = time.time()
    nd = FakeNotifd([{"id": i, "summary": "x", "read": False} for i in range(5)])
    assert attention.should_triage(nd)


def test_triage_gate_all_scored():
    nd = FakeNotifd([{"id": i, "summary": "x", "importance": 1} for i in range(9)])
    assert not attention.should_triage(nd)


# ---------------------------------------------------------------------------
# briefing + suggestions
# ---------------------------------------------------------------------------

def test_briefing_needs_material(tmp_path):
    store = Store(tmp_path / "t.db")
    assert attention.briefing_material(store, FakeNotifd(), time.time() - 3600) == ""


def test_suggestion_rate_limit(tmp_path):
    store = Store(tmp_path / "t.db")
    store.add_proactive("suggestion", "try a daily digest?")
    # one live suggestion at a time — the second pass must bail before any model
    out = asyncio.run(attention.maybe_suggest({}, store))
    assert out is None
    store.dismiss_proactive(kind="suggestion")
    # dismissed <24h ago → still quiet
    assert asyncio.run(attention.maybe_suggest({}, store)) is None


# ---------------------------------------------------------------------------
# the metric
# ---------------------------------------------------------------------------

def test_conversation_origin_tagging(tmp_path):
    store = Store(tmp_path / "t.db")
    a = store.create_conversation("hi")                       # default: user
    b = store.create_conversation("cron", origin="trigger")
    rows = {r["id"]: r["origin"] for r in store.db.execute(
        "select id, origin from conversations").fetchall()}
    assert rows[a] == "user" and rows[b] == "trigger"
