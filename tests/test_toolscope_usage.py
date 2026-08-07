"""Tool scoping (how many tools the model sees) and the cost ledger.

Both exist for the same reason: the OS was spending something — context window,
money — without measuring it or telling anyone.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import toolscope, usage                # noqa: E402
from agentos.memory import Store                    # noqa: E402
from agentos.tools import TOOL_SCHEMAS              # noqa: E402

# Narrowing ships OFF (see toolscope.py's docstring for the measurement), so the
# tests for what narrowing DOES must ask for it explicitly.
SMALL = {"default_model": "ollama/x", "ollama_num_ctx": 24576, "tools": {"scope": "auto"}}
BIG = {"default_model": "anthropic/claude-sonnet-5", "tools": {"scope": "auto"}}


# ---------------------------------------------------------------------------
# when to narrow
# ---------------------------------------------------------------------------

def test_the_real_catalogue_is_worth_narrowing_on_a_small_window():
    """The measurement that motivated this: ~11.6k tokens of schema against a
    24.5k window. If this ever stops being true, the default should be revisited."""
    assert toolscope.schema_tokens(TOOL_SCHEMAS) > 6000
    assert toolscope.should_scope(TOOL_SCHEMAS, SMALL)


def test_narrowing_is_off_by_default():
    """It was measured with `agentos eval` and scored slightly worse on the local
    model. The mechanism ships; the default does not. If this test is ever
    flipped, flip it because a new measurement said to."""
    assert toolscope.DEFAULTS["scope"] == "all"
    assert not toolscope.should_scope(TOOL_SCHEMAS, {"default_model": "ollama/x",
                                                     "ollama_num_ctx": 24576})


def test_a_large_window_is_left_alone():
    """Hiding a tool is worse than paying for it when there is room."""
    assert not toolscope.should_scope(TOOL_SCHEMAS, BIG)
    out, narrowed = toolscope.scope(TOOL_SCHEMAS, "anything", BIG)
    assert not narrowed and len(out) == len(TOOL_SCHEMAS)


def test_the_setting_wins_in_both_directions():
    assert not toolscope.should_scope(TOOL_SCHEMAS, {**SMALL, "tools": {"scope": "all"}})
    assert toolscope.should_scope(TOOL_SCHEMAS, {**BIG, "tools": {"scope": "always"}})


def test_window_comes_from_config_not_from_the_model_name():
    """A 128k local model must be treated as a large one — no name ladders."""
    assert not toolscope.should_scope(
        TOOL_SCHEMAS, {"default_model": "ollama/x", "ollama_num_ctx": 262144,
                       "tools": {"scope": "auto"}})


# ---------------------------------------------------------------------------
# what survives narrowing
# ---------------------------------------------------------------------------

def test_core_tools_are_always_offered():
    out, narrowed = toolscope.scope(TOOL_SCHEMAS, "hello", SMALL)
    assert narrowed
    names = {t["name"] for t in out}
    for must in ("read_file", "write_file", "run_command", "remember", "find_tools"):
        assert must in names, f"{must} must never be scoped away"


def test_narrowing_actually_narrows():
    out, _ = toolscope.scope(TOOL_SCHEMAS, "hello", SMALL)
    assert len(out) < len(TOOL_SCHEMAS)
    assert toolscope.schema_tokens(out) < toolscope.schema_tokens(TOOL_SCHEMAS) * 0.7


def test_the_request_pulls_its_own_tools_in():
    out, _ = toolscope.scope(TOOL_SCHEMAS, "schedule a task to run every morning", SMALL)
    assert "schedule_task" in {t["name"] for t in out}
    out2, _ = toolscope.scope(TOOL_SCHEMAS, "commit this and push it to github", SMALL)
    names = {t["name"] for t in out2}
    assert "git_commit" in names and "git_push" in names


def test_pinned_tools_survive_a_change_of_subject():
    """A turn that used git_status will want git_commit next, and the user's
    words never mentioned either."""
    out, _ = toolscope.scope(TOOL_SCHEMAS, "now tell me a joke", SMALL,
                             pinned={"git_commit", "train_job"})
    names = {t["name"] for t in out}
    assert "git_commit" in names and "train_job" in names


def test_find_tools_matches_plain_words():
    assert "telegram_send" in toolscope.match_names(TOOL_SCHEMAS, "send a telegram message")
    assert "schedule_task" in toolscope.match_names(TOOL_SCHEMAS, "schedule something daily")
    assert "train_model" in toolscope.match_names(TOOL_SCHEMAS, "fine-tune a model")
    assert toolscope.match_names(TOOL_SCHEMAS, "qqzzxx unrelated gibberish") == []


def test_matching_tolerates_english_endings():
    """'scheduling' must find schedule_task — keyword matching that only does
    exact words sends the model away believing the capability is missing."""
    assert "schedule_task" in toolscope.match_names(TOOL_SCHEMAS, "scheduling a daily job")
    assert "create_trigger" in toolscope.match_names(TOOL_SCHEMAS, "react to notifications")


def test_the_model_is_told_what_it_cannot_see():
    """Otherwise it confidently tells the user the OS cannot do something it can."""
    out, _ = toolscope.scope(TOOL_SCHEMAS, "hello", SMALL)
    note = toolscope.catalogue(TOOL_SCHEMAS, out)
    assert "find_tools" in note
    assert str(len(TOOL_SCHEMAS)) in note
    assert toolscope.catalogue(TOOL_SCHEMAS, TOOL_SCHEMAS) == ""


def test_budget_is_respected():
    out, _ = toolscope.scope(TOOL_SCHEMAS, "git commit push status log branch clone pull",
                             {**SMALL, "tools": {"scope": "always", "budget": 25}})
    assert len(out) <= max(25, len(toolscope.CORE))


# ---------------------------------------------------------------------------
# the agent uses it
# ---------------------------------------------------------------------------

def test_an_explicit_tool_filter_is_never_second_guessed(tmp_path):
    from agentos.agent import Agent
    from agentos.tools import Toolbox

    cfg = {**SMALL, "workspace": str(tmp_path), "tools": {"scope": "always"}}
    tb = Toolbox(cfg, Store(tmp_path / "t.db"))

    async def emit(_e):
        pass

    async def approver(*_a, **_k):
        return False

    ag = Agent(cfg, tb, "ollama/x", emit, approver, tool_filter=["read_file", "write_file"])
    assert {t["name"] for t in ag._tools()} == {"read_file", "write_file"}


def test_the_agent_narrows_and_records_the_note(tmp_path):
    from agentos.agent import Agent
    from agentos.tools import Toolbox

    cfg = {**SMALL, "workspace": str(tmp_path), "tools": {"scope": "auto"}}
    tb = Toolbox(cfg, Store(tmp_path / "t.db"))

    async def emit(_e):
        pass

    async def approver(*_a, **_k):
        return False

    ag = Agent(cfg, tb, "ollama/x", emit, approver)
    ag._task_text = "read my notes file"
    offered = ag._tools()
    assert len(offered) < len(tb.schemas())
    assert "find_tools" in ag._tool_note
    # and a pinned tool comes back on the next step
    ag._pinned_tools.add("train_job")
    assert "train_job" in {t["name"] for t in ag._tools()}


def test_probing_the_catalogue_does_not_flood_the_ledger(tmp_path):
    """Filtering 90 tools for a subagent is one question, not 90 accesses."""
    from agentos.policy import PDP, Principal

    store = Store(tmp_path / "t.db")
    pdp = PDP({"autonomy": "balanced"}, store)
    for t in TOOL_SCHEMAS[:20]:
        pdp.decide_tool(Principal("subagent", "r"), t["name"], {}, "safe", audit=False)
    assert store.audit_list(limit=5) == []
    pdp.decide_tool(Principal("subagent", "r"), "read_file", {}, "safe")
    assert len(store.audit_list(limit=5)) == 1


# ---------------------------------------------------------------------------
# the cost ledger
# ---------------------------------------------------------------------------

def test_local_models_are_priced_at_zero_not_left_unknown():
    """'free' and 'unpriced' are different answers and must not be conflated."""
    assert usage.price_of({}, "ollama/qwen3.5:9b") == (0.0, 0.0)
    assert usage.cost({}, "ollama/qwen3.5:9b", 10_000, 5_000) == 0.0


def test_an_unknown_model_stays_unpriced():
    assert usage.price_of({}, "somelab/mystery-1") is None
    assert usage.cost({}, "somelab/mystery-1", 10_000, 5_000) is None


def test_user_pricing_overrides_the_shipped_table():
    cfg = {"pricing": {"somelab/*": {"in": 1.0, "out": 2.0}}}
    assert usage.cost(cfg, "somelab/mystery-1", 1_000_000, 1_000_000) == 3.0
    # and can correct a shipped price
    cfg2 = {"pricing": {"*claude-sonnet*": [1.0, 1.0]}}
    assert usage.cost(cfg2, "anthropic/claude-sonnet-5", 1_000_000, 0) == 1.0


def test_cost_arithmetic():
    # $3/M in, $15/M out
    assert usage.cost({}, "anthropic/claude-sonnet-5", 1_000_000, 100_000) == pytest.approx(4.5)


def test_a_turn_is_recorded_with_its_cost(tmp_path):
    store = Store(tmp_path / "t.db")
    usage.record(store, {}, "anthropic/claude-sonnet-5", {"input": 1000, "output": 500},
                 surface="gui", conversation_id="c1")
    rep = usage.report(store, {}, days=1)
    assert rep["tokens_in"] == 1000 and rep["tokens_out"] == 500
    assert rep["cost_usd"] > 0
    assert rep["unpriced_turns"] == 0


def test_a_turn_that_spent_nothing_is_not_recorded(tmp_path):
    """A provider that reports no usage is not the same as a free turn — better a
    missing row than a false zero."""
    store = Store(tmp_path / "t.db")
    usage.record(store, {}, "x/y", {"input": 0, "output": 0})
    assert usage.report(store, {}, days=1)["rows"] == []


def test_unpriced_turns_are_reported_separately_not_as_zero(tmp_path):
    store = Store(tmp_path / "t.db")
    usage.record(store, {}, "somelab/mystery-1", {"input": 900, "output": 100})
    rep = usage.report(store, {}, days=1)
    assert rep["unpriced_turns"] == 1
    assert rep["cost_usd"] == 0
    assert "tokens only" in rep["note"]
    assert "—" in usage.format_report(rep), "an unpriced row must not print $0.0000"


def test_grouping(tmp_path):
    store = Store(tmp_path / "t.db")
    usage.record(store, {}, "ollama/a", {"input": 10, "output": 1}, surface="gui")
    usage.record(store, {}, "ollama/b", {"input": 20, "output": 2}, surface="telegram")
    usage.record(store, {}, "ollama/b", {"input": 30, "output": 3}, surface="telegram")
    by_model = {r["bucket"]: r["n"] for r in usage.report(store, {}, group="model")["rows"]}
    assert by_model == {"ollama/a": 1, "ollama/b": 2}
    by_surface = {r["bucket"]: r["tin"] for r in usage.report(store, {}, group="surface")["rows"]}
    assert by_surface == {"gui": 10, "telegram": 50}
    days = usage.report(store, {}, group="day")["rows"]
    assert len(days) == 1 and "-" in days[0]["bucket"]


def test_a_broken_ledger_write_never_costs_the_user_the_answer(tmp_path):
    class Broken(Store):
        def usage_add(self, *a, **k):
            raise RuntimeError("disk full")

    store = Broken(tmp_path / "t.db")
    with pytest.raises(RuntimeError):
        store.usage_add()
    # record() calls through Store.usage_add, which swallows its own failure;
    # here the method itself is replaced, so record must not be the thing that
    # takes the turn down either
    try:
        usage.record(store, {}, "x/y", {"input": 1, "output": 1})
    except RuntimeError:
        pytest.fail("a bookkeeping failure must never propagate into a turn")
