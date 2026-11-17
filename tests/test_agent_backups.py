"""Each agent chooses from more than one model, in priority, like the lead; it shows the
company it works in; and the map draws who may ask whom.

Asked for as "you should be able to give the capability for the agents to choose from more
than one model in priority, like in the lead agent … the agents should also show which
companies they belong to … the map should also show which agent can talk to what agent".
"""
import asyncio
from pathlib import Path

import pytest

from agentos import fabric
from agentos.memory import Store

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "agentos/ui/src/js"


def _cfg():
    return {"team": {"own_brains": True}, "executors": {}, "engine": "aria",
            "default_model": "ollama/qwen",
            "providers": {"ollama": {"enabled": True}, "openai": {"enabled": True, "api_key": "k"},
                          "anthropic": {"enabled": False}, "google": {"enabled": True, "api_key": ""}}}


def test_the_first_choice_this_machine_can_run_answers(tmp_path):
    cfg = _cfg()
    defn = {"name": "r", "model": "anthropic/claude-x", "backups": ["google/gemini-y", "openai/gpt-z"]}
    b = fabric.agent_brain(cfg, defn)
    assert b["own"] and b["model"] == "openai/gpt-z" and b["backup"] == 2
    assert "Anthropic is switched off" in b["note"] and "no key" in b["note"]
    # the first choice answers when it can, and a per-step override has no backups
    cfg["providers"]["anthropic"] = {"enabled": True, "api_key": "k"}
    assert fabric.agent_brain(cfg, defn)["model"] == "anthropic/claude-x"
    assert fabric.agent_brain(cfg, defn, "google/gemini-y")["own"] is False
    # none can run: the machine's brain, and every reason is said
    b = fabric.agent_brain(_cfg(), {"name": "r", "model": "anthropic/a", "backups": ["google/g"]})
    assert not b["own"] and b["model"] == "ollama/qwen" and "Anthropic" in b["note"]


def test_backups_are_checked_kept_in_order_and_on_the_record(tmp_path):
    store = Store(tmp_path / "a.db")
    store.save_subagent({"name": "r", "soul": "x", "model": "openai/gpt-z"})
    cfg = _cfg()
    b = fabric.set_agent_backups(store, cfg, "r", ["ollama/llama", "openai/gpt-z", "ollama/llama", "google/g"])
    sa = store.get_subagent("r")
    assert sa["backups"] == ["ollama/llama", "google/g"]          # the pin and a repeat dropped
    assert b["model"] == "openai/gpt-z"
    # a save that doesn't name them keeps them
    store.save_subagent({**sa, "soul": "y"})
    store.db.execute("UPDATE subagents SET soul='y' WHERE name='r'")
    assert store.get_subagent("r")["backups"] == ["ollama/llama", "google/g"]
    with pytest.raises(ValueError):
        fabric.set_agent_backups(store, cfg, "r", ["nowhere/x"])
    with pytest.raises(ValueError):
        fabric.set_agent_backups(store, cfg, "r", [f"ollama/m{i}" for i in range(6)])
    with pytest.raises(KeyError):
        fabric.set_agent_backups(store, cfg, "nobody", [])
    assert any(r["action"] == "agent.write" and "backups" in (r.get("detail") or "")
               for r in store.audit_list(limit=20))


class _Store:
    def __init__(self):
        self.lines = []

    def log(self, kind, msg, meta=None, **kw):
        self.lines.append(msg)


def _plane(results):
    cp = object.__new__(fabric.ControlPlane)
    cp.cfg, cp.store, calls = _cfg(), _Store(), []

    async def once(defn, task, context="", **kw):
        calls.append(kw.get("model_override", ""))
        return results.pop(0)
    cp._run_subagent_once = once
    return cp, calls


def test_a_run_whose_brain_was_unavailable_is_asked_of_the_next_backup():
    defn = {"name": "r", "model": "openai/gpt-z", "backups": ["ollama/llama", "ollama/other"]}
    cp, calls = _plane([{"status": "error", "fault": "usage limit reached", "content": "", "steps": []},
                        {"status": "ok", "content": "done", "steps": []}])
    res = asyncio.run(cp.run_subagent(defn, "task"))
    assert res["content"] == "done" and calls == ["", "ollama/llama"]
    assert "asking its backup ollama/llama" in cp.store.lines[0]


@pytest.mark.parametrize("first", [
    {"status": "error", "fault": "denied by the gate", "content": "", "steps": []},      # a refusal
    {"status": "cancelled", "fault": "", "content": "", "steps": []},                       # a stop
    {"status": "error", "fault": "rate limit", "content": "", "steps": [{"type": "tool"}]},  # it acted
    {"status": "error", "fault": "rate limit", "content": "half an answer", "steps": []},  # it spoke
])
def test_a_refusal_a_stop_or_a_run_that_did_something_is_never_retried(first):
    defn = {"name": "r", "model": "openai/gpt-z", "backups": ["ollama/llama"]}
    cp, calls = _plane([first, {"status": "ok", "content": "x", "steps": []}])
    asyncio.run(cp.run_subagent(defn, "task"))
    assert calls == [""]


def test_the_page_shows_company_backups_and_who_may_ask_whom():
    js = (JS / "11-settings.js").read_text()
    body = js[js.index("async function paintTeamBrains"):js.index("async function paintTeamMatrix")]
    assert "works_for" in body and "Default company" in body and "backups:" in body and "tb-add" in body
    server = (ROOT / "agentos/server.py").read_text()
    assert 's["works_for"]' in server and 'body["backups"]' in server
    zm = (JS / "24s-zmap.js").read_text()
    assert "function zmTalkEdges" in zm and "function zmTalkRows" in zm and "agent:p.name" in zm
    assert "talk=await apiJSON('/api/team/matrix')" in (JS / "11e-hands.js").read_text()
    cli = (ROOT / "agentos/__main__.py").read_text()
    assert 'act == "backups"' in cli and "set_agent_backups" in cli


def test_the_map_reads_a_cell_as_the_gate_does(tmp_path):
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    zm = (JS / "24s-zmap.js").read_text()
    fn = zm[zm.index("function zmTalkOf"):zm.index("function zmTalkEdges")]
    prog = fn + """
const t={talk:'matrix',cells:{'a>b':'allow','b>a':'deny'}};
const out=[zmTalkOf(t,'a','b'),zmTalkOf(t,'b','a'),zmTalkOf(t,'a','c'),
  zmTalkOf({...t,talk:'swarm'},'a','c'),zmTalkOf({...t,talk:'swarm'},'b','a'),zmTalkOf({...t,talk:'off'},'a','b')];
console.log(JSON.stringify(out));"""
    got = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=20).stdout.strip()
    assert got == '["ok","no","","ok","no",""]'
