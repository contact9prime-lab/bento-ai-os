"""Quarantine: what the OS does when something will not stop itself.

Grants answer "may it?", budgets answer "how long?" — neither answers "how often?". A
subagent is bounded by max_steps and a flow by its delegation budget, but an app runs in a
browser tab and can loop for as long as the tab is open.

The numbers here are calibrated against what this machine actually does, and one test
asserts that directly: a real dashboard's refresh burst must NOT be quarantined, or the
feature is just a way to break working apps.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos.memory import Store                                   # noqa: E402
from agentos.policy import MAIN, PDP, Principal, call_class        # noqa: E402

APP = Principal("app", "f57269ef6f9c")


@pytest.fixture()
def pdp(tmp_path):
    p = PDP({"autonomy": "balanced"}, Store(tmp_path / "t.db"))
    p.tripped = []
    p.on_rate_trip = lambda pr, st: p.tripped.append((pr, st))
    return p


def _call(pdp, tool, n=1, principal=APP):
    out = None
    for _ in range(n):
        out = pdp.decide_tool(principal, tool, {}, "safe", surface="gui")
    return out


# ---------------------------------------------------------------------------
# the limits are calibrated, not guessed
# ---------------------------------------------------------------------------

def test_a_real_dashboard_refresh_is_not_quarantined(pdp):
    """Measured on this machine: the busiest legitimate app fired 25 fetches in 10s on
    refresh. If that trips, the feature is a way to break working apps."""
    dec = _call(pdp, "fetch_url", 25)
    assert dec.effect != "deny", "a legitimate refresh burst was quarantined"
    assert not pdp.tripped


def test_a_runaway_fetch_loop_is_quarantined(pdp):
    dec = _call(pdp, "fetch_url", 200)
    assert dec.effect == "deny" and dec.rule == "quarantined"
    assert pdp.tripped, "nothing was told to hold it"
    assert "tool calls" in pdp.tripped[0][1]["reason"]


def test_model_calls_are_counted_separately_and_far_tighter(pdp):
    """Six model calls a minute is money leaving at a rate nobody asked for; six fetches is
    a page refreshing. Counting them together would either hold every app or catch nothing."""
    assert call_class("llm_generate") == "llm"
    assert call_class("app→appLLM.stream") == "llm"
    assert call_class("fetch_url") == "tool"

    dec = _call(pdp, "llm_generate", 7)
    assert dec.effect == "deny" and dec.rule == "quarantined"
    assert pdp.tripped[0][1]["class"] == "llm"
    assert "model calls" in pdp.tripped[0][1]["reason"]


def test_the_two_classes_do_not_borrow_from_each_other(pdp):
    _call(pdp, "fetch_url", 30)            # well within the tool budget
    assert _call(pdp, "llm_generate", 3).effect != "deny", "fetches ate the model budget"


# ---------------------------------------------------------------------------
# what being held means
# ---------------------------------------------------------------------------

def test_the_user_is_never_rate_limited(pdp):
    """The main agent acts as the user. Holding the user out of their own machine is not a
    safety feature."""
    for _ in range(300):
        dec = pdp.decide_tool(MAIN, "fetch_url", {}, "safe", surface="gui")
    assert dec.effect != "deny"


def test_being_held_refuses_everything_after(pdp):
    """Held means held: a different tool, on a budget it never touched, is still refused —
    and the refusal repeats the reason it was held for, not a generic one."""
    _call(pdp, "fetch_url", 200)
    dec = pdp.decide_tool(APP, "read_file", {}, "safe", surface="gui")
    assert dec.effect == "deny" and dec.rule == "quarantined"
    assert "tool calls" in dec.reason and "fetch_url" in dec.reason
    assert "let it out" in dec.reason, "a refusal has to say what to do about it"


def test_one_incident_is_one_record_not_one_per_call(pdp):
    """A runaway calls many times a second. Two hundred rows of the same incident is not a
    record, it is the runaway again in a different table."""
    _call(pdp, "fetch_url", 400)
    assert len(pdp.store.quarantine_list()) <= 1


def test_a_probe_is_not_a_call(pdp):
    """`audit=False` is the tool-list filter asking "could this?" over the whole catalogue.
    Metering it would quarantine an app for opening."""
    for _ in range(300):
        pdp.decide_tool(APP, "fetch_url", {}, "safe", surface="gui", audit=False)
    assert not pdp.tripped


# ---------------------------------------------------------------------------
# the three ways out
# ---------------------------------------------------------------------------

def test_release_once_lets_it_run_and_keeps_watching(pdp):
    qid = pdp.store.quarantine_add("app", APP.id, "looping")
    pdp.store.quarantine_release(qid, "once")
    assert pdp.decide_tool(APP, "fetch_url", {}, "safe", surface="gui").effect != "deny"
    assert not pdp.store.quarantine_exempt("app", APP.id), "'once' is not an exemption"


def test_release_forever_is_an_exemption_that_survives(pdp):
    qid = pdp.store.quarantine_add("app", APP.id, "looping")
    pdp.store.quarantine_release(qid, "forever")
    assert pdp.store.quarantine_exempt("app", APP.id)
    # and it is not held again for the same thing, however fast it goes
    dec = _call(pdp, "fetch_url", 300)
    assert dec.effect != "deny"
    assert not pdp.tripped


def test_the_release_decision_stays_on_the_record(pdp):
    qid = pdp.store.quarantine_add("app", APP.id, "looping", label="Ticker")
    pdp.store.quarantine_release(qid, "forever", by="user")
    row = [r for r in pdp.store.quarantine_list(include_released=True) if r["id"] == qid][0]
    assert row["release_mode"] == "forever" and row["released_by"] == "user"
    assert row["released_at"] and row["reason"] == "looping"
    assert row["label"] == "Ticker", "the name it had at the time survives a rename"


def test_the_evidence_is_kept_so_the_user_can_judge(pdp):
    _call(pdp, "llm_generate", 8)
    held = pdp.store.quarantine_list()[0]
    ev = held["evidence"]
    assert ev["count"] > ev["allowed"] and ev["window"] and ev["class"] == "llm"
    assert held["reason"] and "over its limit" in held["reason"]


# ---------------------------------------------------------------------------
# it is not only apps
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["app", "subagent", "flow"])
def test_agents_and_flows_are_held_the_same_way(pdp, kind):
    p = Principal(kind, "runaway")
    for _ in range(400):
        dec = pdp.decide_tool(p, "llm_generate", {}, "safe", surface="gui")
    assert dec.effect == "deny" and dec.rule == "quarantined"
    assert pdp.store.quarantined(kind, "runaway")


def test_turning_it_off_is_possible_and_explicit(tmp_path):
    p = PDP({"autonomy": "balanced", "security": {"rate_limits": {}}}, Store(tmp_path / "t.db"))
    for _ in range(300):
        dec = p.decide_tool(APP, "fetch_url", {}, "safe", surface="gui")
    assert dec.effect != "deny"


# ---------------------------------------------------------------------------
# The drip: a loop paced to slip under the burst ceiling forever
# ---------------------------------------------------------------------------

def test_a_patient_loop_under_the_burst_limit_is_still_caught(pdp, monkeypatch):
    """The burst ceiling only sees a tight loop. A loop that fetches twice a second
    all night never fills a 20s window past 60 — but it is still hammering somebody
    else's API, and the sustained ceiling is the only thing that sees it. Before
    this ceiling existed, this loop ran forever."""
    import agentos.policy as policy
    clock = {"t": 1000.0}
    monkeypatch.setattr(policy.time, "time", lambda: clock["t"])
    dec = None
    for _ in range(400):                 # 2 calls/sec for 200s: 40 per 20s (< 60 burst)
        dec = pdp.decide_tool(APP, "fetch_url", {}, "safe", surface="gui")
        if dec.effect == "deny":
            break
        clock["t"] += 0.5
    assert dec.effect == "deny" and dec.rule == "quarantined"
    assert pdp.tripped, "the sustained ceiling did not tell anyone"
    assert "does not let up" in pdp.tripped[0][1]["reason"]
    # and it was NOT the burst ceiling that caught it
    assert "tight loop" not in pdp.tripped[0][1]["reason"]


def test_a_burst_then_quiet_is_not_a_drip(pdp, monkeypatch):
    """A real dashboard bursts on refresh and then goes quiet. Over the long window
    that averages out well under the sustained budget — it must not accumulate into
    a hold across refreshes."""
    import agentos.policy as policy
    clock = {"t": 5000.0}
    monkeypatch.setattr(policy.time, "time", lambda: clock["t"])
    dec = None
    for _ in range(8):                   # eight refreshes, 40s apart, 25 fetches each
        for _ in range(25):
            dec = pdp.decide_tool(APP, "fetch_url", {}, "safe", surface="gui")
        clock["t"] += 40
    assert dec.effect != "deny", "a bursty-but-quiet dashboard was held as a drip"
    assert not pdp.tripped
