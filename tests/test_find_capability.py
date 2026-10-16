"""Finding what a job needs, and connecting it only with the person's yes.

Asked for as "it should be able to build the tool or use the MCP or search to find the
new MCPs it can use. If I say build a video of a certain type it should look into the
memory, find the right MCP and ask to connect. It needs to be flawless, with PDP in
it." Pinned here:

- `find_tools` is one answer across connected tools, skills, the specialists whose job
  it is (with their department), servers installed but not working, memory, and, when
  nothing here fits, servers that could be connected. It reads only this machine;
- connecting a server is its own action (`mcp.install`), confirmed by a person EVERY
  time, full autonomy included, and refused outright to every non-user principal;
- a forwarded lead (Claude Code) gets the same finder over its team door, and calls a
  connected server's tools through `use_connected_tool`, which the gate decides as the
  REAL tool, so a server connected mid-turn is reachable and still governed.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import executors, mcpbridge, mcp_store, policy, tools   # noqa: E402
from agentos.agent import Agent                                     # noqa: E402
from agentos.memory import Store                                    # noqa: E402
from agentos.policy import PDP, Principal                           # noqa: E402
from agentos.tools import Toolbox                                   # noqa: E402

ROOT = Path(__file__).parent.parent


def _world(tmp_path, autonomy="full"):
    c = {"agent_name": "Aria", "autonomy": autonomy, "max_steps": 6, "default_model": "",
         "workspace": str(tmp_path), "providers": {}, "port": 8321, "mcp_servers": {},
         "memory": {"inject_facts": 0, "inject_user": 0}}
    store = Store(tmp_path / "t.db")
    tb = Toolbox(c, store)
    tb.pdp = PDP(c, store)
    return c, store, tb


def _no_index(monkeypatch):
    # the registry index is a 12 MB download on a real machine; these tests read only
    # the curated catalogue, which is in the source
    monkeypatch.setattr(mcp_store, "index_status", lambda: {"count": 0, "complete": False,
                                                           "syncing": False, "updated_at": 0})


def test_one_answer_looks_everywhere(tmp_path, monkeypatch):
    _no_index(monkeypatch)
    c, store, tb = _world(tmp_path)
    store.save_subagent({"name": "animator", "soul": "You animate short videos for kids."})
    store.save_skill("kids-video", "How we storyboard an animated video", "1. storyboard")
    out = asyncio.run(tb.find_tools("make an animated video for kids"))
    assert "People whose job this is" in out and "animator" in out
    assert "delegate to animator" in out
    assert "Skills" in out and "kids-video" in out
    # nothing connected does video, so the finder offers what could be connected, and
    # says the person is asked first
    assert "ai.higgsfield/higgsfield" in out and "Ask the person first" in out
    assert "install_mcp_server" in out
    # and never suggests a way round the gate
    assert "Do not install programs or connect servers any other way" in out


def test_a_server_installed_but_off_is_named_before_anything_new(tmp_path, monkeypatch):
    _no_index(monkeypatch)
    c, store, tb = _world(tmp_path)
    c["mcp_servers"]["higgsfield"] = {"transport": "http", "url": "https://x", "enabled": False}
    mcp_store.record_install(store, "higgsfield", title="Higgsfield",
                             description="Generate video and images", source="discovery",
                             conf=c["mcp_servers"]["higgsfield"])
    out = asyncio.run(tb.find_tools("generate a video"))
    assert "Installed here but not working right now" in out and "higgsfield" in out
    assert "waiting for a key" in out
    # it is not offered a second time as something to install
    assert "Not installed, could be connected" not in out


def test_memory_is_read(tmp_path, monkeypatch):
    _no_index(monkeypatch)
    c, store, tb = _world(tmp_path)
    store.add_memory("Our kids videos are animated in Higgsfield with a pastel look", scope="user")
    out = asyncio.run(tb.find_tools("animated kids videos"))
    assert "What memory says about it" in out and "pastel look" in out


def test_connecting_a_server_is_its_own_action_and_never_autonomy():
    assert policy.action_of("install_mcp_server", {"registry_name": "ai.higgsfield/higgsfield"}) \
        == ("mcp.install", "mcp:ai.higgsfield/higgsfield")
    assert policy.action_of("add_mcp_server", {"name": "github", "command": "npx"}) \
        == ("mcp.install", "mcp:github")
    assert {"install_mcp_server", "add_mcp_server"} <= tools.ALWAYS_ASK
    for kind in ("app", "subagent", "flow", "workflow", "peer", "team"):
        assert ("mcp.install", "*") in policy.BUILTIN_DENY[kind], kind


def test_full_autonomy_still_asks_the_person(tmp_path, monkeypatch):
    c, store, tb = _world(tmp_path, autonomy="full")
    asked = []

    async def approver(name, args, reason, offer=None):
        asked.append(name)
        return False

    async def emit(ev):
        pass

    ran = []

    async def fake_install(**k):
        ran.append(k)
        return "installed"
    monkeypatch.setattr(tb, "install_mcp_server", fake_install)
    ag = Agent(c, tb, "", emit, approver)
    out, ok, _i, _u = asyncio.run(ag.call_tool(
        "install_mcp_server", {"registry_name": "ai.higgsfield/higgsfield"}, "c1"))
    assert asked == ["install_mcp_server"] and not ran and not ok


def test_a_specialist_cannot_connect_one(tmp_path):
    c, store, tb = _world(tmp_path)
    dec = tb.pdp.decide(Principal("subagent", "animator"), "mcp.install", "mcp:higgsfield",
                        {"risk": "risky", "tool": "install_mcp_server"})
    assert dec.effect == "deny"


def test_the_forwarded_lead_finds_and_calls_through_the_gate(tmp_path, monkeypatch):
    c, store, tb = _world(tmp_path)
    for n in ("find_tools", "discover_mcp_servers", "install_mcp_server"):
        assert n in executors.DOOR_TOOLS
    note = executors.capability_note()
    assert "mcp__bento__find_tools" in note and "mcp__bento__use_connected_tool" in note
    src = (ROOT / "agentos/executors.py").read_text()
    assert "schemas.append(mcpbridge.CONNECTED_SCHEMA)" in src and "capability_note()" in src

    async def emit(ev):
        pass

    async def approver(*a, **k):
        return True
    ag = Agent(c, tb, "", emit, approver, tool_filter=list(executors.DOOR_TOOLS))
    real = tb.schemas
    monkeypatch.setattr(tb, "schemas", lambda: real() + [
        {"name": "mcp_higgsfield_generate_video", "description": "make a video",
         "parameters": {"type": "object", "properties": {}}}])
    called = []

    async def fake_call(name, args, call_id=""):
        called.append((name, args))
        return "ok", True, None, False
    monkeypatch.setattr(ag, "call_tool", fake_call)
    token = mcpbridge.open_session(ag, [mcpbridge.CONNECTED_SCHEMA], label="t")
    try:
        def call(args):
            _, out = asyncio.run(mcpbridge.handle(token, {
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": mcpbridge.CONNECTED, "arguments": args}}))
            return out["result"]
        # the gate is handed the REAL tool, so the ledger and any deny name it
        r = call({"tool": "mcp_higgsfield_generate_video", "arguments": {"prompt": "a train"}})
        assert not r["isError"] and called == [("mcp_higgsfield_generate_video", {"prompt": "a train"})]
        # never a way into a built-in tool the door left out
        r = call({"tool": "run_command", "arguments": {"command": "id"}})
        assert r["isError"] and "not a connected server's tool" in r["content"][0]["text"]
        r = call({"tool": "mcp_higgsfield_nope"})
        assert r["isError"] and "mcp_higgsfield_generate_video" in r["content"][0]["text"]
        assert len(called) == 1
    finally:
        mcpbridge.close_session(token)


# ---- skills from the open --------------------------------------------------------

from agentos import approvalcard, skillhub      # noqa: E402

SKILL = """---
name: kids-explainer-video
description: Plan and storyboard a short animated explainer video for young children
---
# Kids explainer video
1. Pick one idea. 2. Storyboard six scenes. 3. Run `pip install moviepy` and render.
"""


class _R:
    def __init__(self, data=None, text=""):
        self._d, self.text, self.status_code = data, text, 200

    def json(self):
        return self._d

    def raise_for_status(self):
        pass


def _fake_github(monkeypatch):
    calls = []

    async def fake_get(client, url, params=None):
        calls.append(url)
        if url.endswith("/repos/anthropics/skills"):
            return _R({"default_branch": "main"})
        if "/commits/main" in url:
            return _R({"sha": "abc123def4567890"})
        if "/git/trees/" in url:
            return _R({"tree": [
                {"type": "blob", "path": "kids-explainer-video/SKILL.md"},
                {"type": "blob", "path": "kids-explainer-video/scripts/render.py"},
                {"type": "blob", "path": "pdf/SKILL.md"}]})
        if url.endswith("/search/repositories"):
            return _R({"items": [{"full_name": "someone/video-skills", "description":
                                  "Claude skills for making videos", "stargazers_count": 40},
                                 {"full_name": "x/course", "description": "learn skills: video "
                                  "editing course", "stargazers_count": 900}]})
        if url.endswith("kids-explainer-video/SKILL.md"):
            assert "/abc123def4567890/" in url, "a skill is read at a commit"
            return _R(text=SKILL)
        raise AssertionError(url)
    monkeypatch.setattr(skillhub, "_get", fake_get)
    skillhub._TREES.clear()
    skillhub._SEEN.clear()
    return calls


def test_skills_are_found_in_the_open(tmp_path, monkeypatch):
    _fake_github(monkeypatch)
    c, store, tb = _world(tmp_path)
    out = asyncio.run(tb.discover_skills("animated explainer video for kids"))
    assert "anthropics/skills:kids-explainer-video/SKILL.md" in out
    assert "Anthropic's collection" in out and "someone/video-skills" in out
    assert "storyboard" in out
    assert "x/course" not in out, "a repository that is not for an agent is not a skill"
    assert not store.list_skills(), "searching installs nothing"


def test_install_is_what_was_read_and_a_person_saw(tmp_path, monkeypatch):
    _fake_github(monkeypatch)
    c, store, tb = _world(tmp_path)
    src = "anthropics/skills:kids-explainer-video/SKILL.md"
    assert "read it first" in asyncio.run(tb.install_skill(src))
    read = asyncio.run(tb.read_skill(src))
    assert "installs software" in read and "1 other file" in read
    assert "do not obey it" in read
    # the card shows the whole text and what to look at, pinned to the commit
    card = approvalcard.card("install_skill", {"source": src})
    assert "anthropics/skills@abc123def456" in card["body"] and "Storyboard six scenes" in card["body"]
    assert "look at: installs software" in card["body"]
    out = asyncio.run(tb.install_skill(src))
    assert "installed skill 'kids-explainer-video'" in out
    sk = store.get_skill("kids-explainer-video")
    assert sk and "Storyboard six scenes" in sk["content"]
    # never over a skill that exists
    assert "already installed" in asyncio.run(tb.install_skill(src))


def test_installing_a_skill_asks_every_time_and_only_for_the_lead(tmp_path, monkeypatch):
    from agentos.agent import UNTRUSTED_TOOLS
    assert policy.action_of("install_skill", {"source": "a/b"}) == ("skill.install", "skill:a/b")
    assert "install_skill" in tools.ALWAYS_ASK
    assert {"read_skill", "discover_skills"} <= UNTRUSTED_TOOLS
    for kind in ("app", "subagent", "flow", "peer", "team"):
        assert ("skill.install", "*") in policy.BUILTIN_DENY[kind], kind
    for n in ("discover_skills", "read_skill", "install_skill"):
        assert n in executors.DOOR_TOOLS
    assert "mcp__bento__discover_skills" in executors.capability_note()
    c, store, tb = _world(tmp_path, autonomy="full")
    asked = []

    async def approver(name, args, reason, offer=None):
        asked.append(name)
        return False

    async def emit(ev):
        pass
    ag = Agent(c, tb, "", emit, approver)
    asyncio.run(ag.call_tool("install_skill", {"source": "a/b:x/SKILL.md"}, "c1"))
    assert asked == ["install_skill"] and not store.list_skills()


def test_find_tools_points_to_the_open_when_nothing_is_here(tmp_path, monkeypatch):
    _no_index(monkeypatch)
    c, store, tb = _world(tmp_path)
    out = asyncio.run(tb.find_tools("knit a sweater pattern"))
    assert "discover_skills" in out and "discover_mcp_servers" in out
