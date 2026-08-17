"""One brain: an executor and one of ITS models.

The OS used to ask this twice. "Engine" chose which agent answers; "default
model" chose which weights it woke up on; nothing tied them together. So the
picker could show Claude Code selected as the engine AND a Gemini model selected
underneath it — two answers to the same question disagreeing on screen, which is
what the user reported: "when I select claude code it automatically selects
gemini".

These tests are about that coupling. A model belongs to the executor that can
actually run it, choosing one is ONE write, and an executor that cannot answer
here says why rather than sitting in the list as a choice that fails on the
first turn.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import executors as execmod                   # noqa: E402

MODELS = [
    {"id": "ollama/qwen3", "provider": "ollama", "name": "qwen3"},
    {"id": "ollama/llama3", "provider": "ollama", "name": "llama3"},
    {"id": "google/gemini-3.1-flash-lite", "provider": "google", "name": "gemini-3.1-flash-lite"},
]


def cfg(**over) -> dict:
    base = {"engine": "aria", "default_model": "", "executors": {}}
    base.update(over)
    return base


def by_id(state: dict, eid: str) -> dict:
    return next(e for e in state["executors"] if e["id"] == eid)


# --- the list ---------------------------------------------------------------

def test_every_provider_is_an_executor_with_its_own_models():
    """The user's list: ollama, llama.cpp, openrouter, openai, gemini, claude
    code, anthropic, hermes, openclaw. Each one owns the models you can pick."""
    st = execmod.brains(cfg(), MODELS)
    ids = [e["id"] for e in st["executors"]]
    for want in ("ollama", "anthropic", "openai", "google", "openrouter", "custom",
                 "claude-code", "hermes", "openclaw"):
        assert want in ids, f"{want} is not offered as an executor: {ids}"


def test_a_models_executor_is_the_one_that_can_run_it():
    st = execmod.brains(cfg(), MODELS)
    assert [m["id"] for m in by_id(st, "ollama")["models"]] == ["ollama/qwen3", "ollama/llama3"]
    assert [m["id"] for m in by_id(st, "google")["models"]] == ["google/gemini-3.1-flash-lite"]
    # and no cross-contamination: this is the bug in one assertion
    assert not any(m["id"].startswith("google/") for m in by_id(st, "ollama")["models"])
    assert not any(m["id"].startswith("ollama/")
                   for m in by_id(st, "claude-code")["models"])


def test_llamacpp_is_reachable_through_the_openai_compatible_entry():
    """We do not invent a `llamacpp` provider — llama.cpp's server speaks the
    OpenAI API, so it is the custom entry, and the entry says so."""
    st = execmod.brains(cfg(), MODELS)
    custom = by_id(st, "custom")
    assert "llama.cpp" in custom["name"].lower()


def test_an_executor_with_nothing_to_run_says_what_would_fix_it():
    st = execmod.brains(cfg(), MODELS)
    oai = by_id(st, "openai")
    assert oai["available"] is False
    assert oai["reason"] and "key" in oai["reason"].lower()


def test_a_missing_agent_is_listed_with_its_reason_not_hidden():
    st = execmod.brains(cfg(), MODELS)
    for eid in ("hermes", "openclaw"):
        e = by_id(st, eid)
        if not e["available"]:
            assert e["reason"], f"{eid} is missing and does not say so"


def test_aria_is_not_a_brain_to_pick():
    """Aria is the loop; the brain is the provider it borrows. Offering "Aria"
    beside "Ollama" asks the same question twice."""
    st = execmod.brains(cfg(), MODELS)
    assert "aria" not in [e["id"] for e in st["executors"]]


def test_an_agent_executor_offers_models_and_never_invents_a_catalogue():
    st = execmod.brains(cfg(), MODELS)
    cc = by_id(st, "claude-code")
    ids = [m["id"] for m in cc["models"]]
    assert ids[0] == "", "the honest default — whatever it is signed in to use"
    assert "opus" in ids and "sonnet" in ids and "haiku" in ids
    # documented aliases only; nothing claiming to be a fetched list
    assert all(len(i) < 40 for i in ids)


# --- what is selected ------------------------------------------------------

def test_current_follows_the_model_when_a_provider_answers():
    st = execmod.brains(cfg(default_model="google/gemini-3.1-flash-lite"), MODELS)
    assert st["current"] == {"executor": "google", "model": "google/gemini-3.1-flash-lite"}


def test_current_follows_the_engine_when_an_agent_answers():
    """The reported bug: with a model in config AND an agent as the engine, the
    agent is what is answering, so it is what is selected."""
    c = cfg(engine="claude-code", default_model="google/gemini-3.1-flash-lite",
            executors={"claude_code": {"model": "opus"}})
    st = execmod.brains(c, MODELS, engine="claude-code")
    assert st["current"] == {"executor": "claude-code", "model": "opus"}


def test_each_executor_remembers_its_own_model():
    """Switching away and back must not lose the choice already made."""
    c = cfg(engine="claude-code", default_model="ollama/llama3",
            executors={"claude_code": {"model": "haiku"}})
    st = execmod.brains(c, MODELS, engine="claude-code")
    assert by_id(st, "claude-code")["model"] == "haiku"
    assert by_id(st, "ollama")["model"] == "ollama/llama3"


def test_no_model_set_still_names_something_that_could_answer():
    st = execmod.brains(cfg(), MODELS)
    cur = st["current"]
    assert cur["executor"] == "ollama" and cur["model"] == "ollama/qwen3"


# --- choosing --------------------------------------------------------------

def test_choosing_a_provider_stops_forwarding():
    """Otherwise picking a model changes nothing, which is the whole bug: the
    picker offered something that did not apply."""
    c = cfg(engine="claude-code", executors={"claude_code": {"model": "opus"}})
    ok, msg = execmod.set_brain(c, "ollama", "ollama/llama3", MODELS)
    assert ok, msg
    assert c["engine"] == "aria"
    assert c["default_model"] == "ollama/llama3"


def test_choosing_an_agent_writes_the_engine_and_its_model_together():
    c = cfg(default_model="ollama/qwen3")
    ok, msg = execmod.set_brain(c, "claude-code", "sonnet", MODELS)
    if not ok:                       # Claude Code is not installed on this box
        assert "not installed" in msg
        return
    assert c["engine"] == "claude-code"
    assert c["executors"]["claude_code"]["model"] == "sonnet"
    # the provider model is left alone — it is what "aria" goes back to
    assert c["default_model"] == "ollama/qwen3"


def test_an_agent_may_be_asked_for_its_own_default():
    c = cfg()
    ok, _ = execmod.set_brain(c, "claude-code", "", MODELS)
    if ok:
        assert c["executors"]["claude_code"]["model"] == ""


def test_a_model_from_another_executor_is_refused():
    """The mis-selection, refused at the write as well as in the picker."""
    c = cfg()
    ok, msg = execmod.set_brain(c, "claude-code", "google/gemini-3.1-flash-lite", MODELS)
    assert not ok
    assert "does not offer" in msg or "not installed" in msg


def test_an_unknown_executor_is_refused():
    ok, msg = execmod.set_brain(cfg(), "nope", "", MODELS)
    assert not ok and "no executor" in msg


def test_an_executor_that_cannot_answer_here_is_refused_with_its_reason():
    c = cfg()
    ok, msg = execmod.set_brain(c, "openai", "", MODELS)
    assert not ok and msg
    assert c["engine"] == "aria" and c["default_model"] == ""


def test_executor_model_reads_the_config_key_not_a_guess():
    c = cfg(executors={"claude_code": {"model": "opus"}})
    assert execmod.executor_model(c, "claude-code") == "opus"
    assert execmod.executor_model(c, "hermes") == ""
