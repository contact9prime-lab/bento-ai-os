"""Quarantine: what the OS does when something will not stop itself.

Grants answer "may it?", budgets answer "how long?" — neither answers "how often?". A
subagent is bounded by max_steps and a flow by its delegation budget, but an app runs in a
browser tab and can loop for as long as the tab is open.

The numbers here are calibrated against what this machine actually does, and one test
asserts that directly: a real dashboard's refresh burst must NOT be quarantined, or the
feature is just a way to break working apps.
"""

import time
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


# ---------------------------------------------------------------------------
# the rung below the hold: steer first, stop second
#
# A ceiling that only ever holds turns a burst into a dead mission, and a mission
# held at 03:00 did nothing at all that night. These pin the ladder: the first
# trip corrects and lets the run continue, the second stops it, and the rung is
# only offered to a principal that can actually read the correction.
# ---------------------------------------------------------------------------

def _burst(pdp, principal, tool="fetch_url", n=200, **kw):
    """Call until something refuses, and hand back THAT decision.

    Stopping at the first deny is not a convenience: it is what the principal being
    metered actually experiences. A loop gets the refusal as its tool result and reacts
    to it, so a helper that kept calling past the refusal and returned the last decision
    would be asserting about calls no real agent would have made — and it would read
    "allowed" for a burst that was in fact corrected in the middle.
    """
    out = None
    for _ in range(n):
        out = pdp.decide_tool(principal, tool, {}, "safe", surface="task", **kw)
        if out.effect == "deny":
            return out
    return out


def test_a_flows_first_burst_is_steered_not_held(pdp):
    """The mission is corrected and stays alive. Held, it would have done nothing."""
    flow = Principal("flow", "morning-brief")
    dec = _burst(pdp, flow)
    assert dec.effect == "deny", "the offending call must still be refused"
    assert dec.rule == "steered", f"first trip should steer, got {dec.rule!r}"
    assert not pdp.store.quarantined("flow", "morning-brief"), \
        "a steer must not write a hold — that list is what is STOPPED"


def test_the_steer_tells_it_what_to_do_instead(pdp):
    """The refusal text IS the mechanism: it comes back as the tool's result, so it has
    to read as an instruction to a model, not as an error string for a log."""
    dec = _burst(pdp, Principal("flow", "digest"))
    said = dec.reason.lower()
    assert "fetch_url" in said, "it must name what it was doing"
    assert "already tried" in said or "something different" in said, \
        "a correction that does not say what to do instead is just a refusal"
    assert "held" in said, "it must say what happens if it carries on"


def test_a_steered_flow_can_actually_carry_on(pdp):
    """The meter is cleared with the steer. Without that the very next call re-trips
    against the same history and the steer is a hold wearing kinder words."""
    flow = Principal("flow", "watcher")
    _burst(pdp, flow)
    dec = pdp.decide_tool(flow, "fetch_url", {}, "safe", surface="task")
    assert dec.effect != "deny", "a second chance nobody can use is not a second chance"


def test_ignoring_the_steer_is_what_gets_it_held(pdp):
    flow = Principal("flow", "runaway")
    first = _burst(pdp, flow)
    assert first.rule == "steered"
    second = _burst(pdp, flow)
    assert second.effect == "deny" and second.rule == "quarantined", \
        "a loop that ignores the correction must be stopped"
    assert pdp.store.quarantined("flow", "runaway")


def test_a_subagent_is_steered_too_because_it_reads_its_refusals(pdp):
    dec = _burst(pdp, Principal("subagent", "researcher"))
    assert dec.rule == "steered"


def test_an_app_is_held_outright_because_nobody_there_reads_english(pdp):
    """An app is a browser tab running somebody's JavaScript. A loop there will not
    correct, so offering it a rung would only widen the runaway by one window."""
    dec = _burst(pdp, APP)
    assert dec.effect == "deny" and dec.rule == "quarantined"
    assert pdp.store.quarantined("app", APP.id)


def test_the_steer_is_announced_with_the_run_it_happened_in(pdp):
    seen = []
    pdp.on_rate_steer = lambda pr, st: seen.append((pr, st))
    _burst(pdp, Principal("flow", "nightly"), run_id="run-abc123")
    assert seen, "nothing was told that a mission had been corrected"
    pr, st = seen[0]
    assert pr.label == "flow:nightly"
    assert st["run_id"] == "run-abc123", "a steer with no run is one nobody can go and read"
    assert "over its limit" in st["reason"]
    assert not pdp.tripped, "a steer is not a trip — the hold callback must stay quiet"


def test_the_ledger_records_a_steer_as_its_own_rule(pdp):
    """`rule` is how the ledger is read back. A steer recorded as a quarantine would
    make the record disagree with the quarantine list it is read beside."""
    _burst(pdp, Principal("flow", "audited"))
    rows = [r for r in pdp.store.audit_list(limit=400) if r.get("rule") == "steered"]
    assert rows, "the correction never reached the ledger"
    assert rows[0]["effect"] == "deny"


def test_releasing_a_hold_resets_the_ladder(pdp):
    """"Let it run again" must mean it, and a principal one trip from being held is not
    running again in any sense the person pressing that button would recognise."""
    flow = Principal("flow", "released")
    _burst(pdp, flow)                       # steered
    _burst(pdp, flow)                       # held
    held = pdp.store.quarantined("flow", "released")
    pdp.store.quarantine_release(held["id"], "once")
    pdp.forget_rate("flow", "released")
    dec = _burst(pdp, flow)
    assert dec.rule == "steered", "it should get the full ladder again, not the last rung"


def test_a_steer_expires_so_this_evening_is_not_judged_by_this_morning(pdp, monkeypatch):
    import agentos.policy as pol
    flow = Principal("flow", "daily")
    assert _burst(pdp, flow).rule == "steered"
    t = [time.time()]
    monkeypatch.setattr(pol.time, "time", lambda: t[0])
    t[0] += pol.STEER_WINDOW + 60          # a fresh, unrelated burst hours later
    assert _burst(pdp, flow).rule == "steered", \
        "an unrelated burst after the window should be corrected, not stopped"
