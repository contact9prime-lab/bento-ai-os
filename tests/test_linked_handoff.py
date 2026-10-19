"""The lead hands work to a linked team, and a machine with no agents offloads to one.

Reported as "I linked the two machines but I can't see the hand-over between the agent and
the foreign agent", and "a machine may only offload to another, with no agents of its own".
The lead's `delegate` knew only local specialists, it was never told a linked team existed,
the other side answered only its specialists (so a link to a machine without any could be
allowed nobody), and the Office dropped any hand-over to a name it could not find on the
floor. Now:

- `delegate` takes `name@team` and `lead@team`, decided as the matrix's question
  (agent.message, asked the first time, a cell in Permissions once remembered);
- the other side's lead answers when its link allows "lead", working the task with its own
  team and nothing else, tainted, in a conversation of its own there;
- the lead hears its linked teams (`linked_note`) and can list them (`linked_teams`).
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import executors, fabric, policy, providers, teamlink   # noqa: E402
from agentos.agent import Agent                                       # noqa: E402
from test_teamlink import pair                                        # noqa: E402,F401

ROOT = Path(__file__).parent.parent


def _brains(seen):
    """home's lead hands the task to office's lead; office's lead gives it to its analyst."""
    def chat(cfg, model, messages, tools, options=None):
        async def gen():
            sys_txt = next((m["content"] for m in messages if m["role"] == "system"), "")
            user = next(m["content"] for m in messages if m["role"] == "user")
            done = [m for m in messages if m["role"] == "tool"]
            if "SOUL-analyst" in sys_txt:
                yield {"type": "text", "text": "Churn is 4% on the Pro plan."}
            elif "is the lead of the linked team" in user:
                seen["office_lead_tools"] = sorted(t["name"] for t in tools or [])
                if not done:
                    yield {"type": "tool_call", "id": "o1", "name": "delegate",
                           "args": {"subagent": "analyst", "task": "Pro churn?"}}
                    yield {"type": "finish", "reason": "tool_calls"}
                    return
                yield {"type": "text", "text": "OFFICE SAYS " + done[-1]["content"][-60:]}
            elif user == "HOME-TASK":
                if not done:
                    yield {"type": "tool_call", "id": "h1", "name": "delegate",
                           "args": {"subagent": "lead@office", "task": "Find our Pro churn."}}
                    yield {"type": "finish", "reason": "tool_calls"}
                    return
                yield {"type": "text", "text": "HOME GOT " + done[-1]["content"]}
            else:
                yield {"type": "text", "text": "?"}
            yield {"type": "finish", "reason": "stop"}
        return gen()
    return chat


def _home_turn(B, loop, asked):
    async def approver(name, args, reason, offer=None):
        asked.append((name, args.get("subagent"), reason))
        return True

    async def emit(_):
        pass

    async def go():
        with teamlink.at(B["home"]):
            a = Agent(B["cfg"], B["tb"], "openai/gpt-4o", emit, approver, conversation_id="c-home")
            return await a.run([{"role": "user", "content": "HOME-TASK"}])
    return loop.run_until_complete(go())


def test_the_lead_hands_a_whole_task_to_the_other_teams_lead(pair, monkeypatch):
    A, B, inv, loop = pair
    seen, asked = {}, []
    monkeypatch.setattr(providers, "chat", _brains(seen))
    fabric.set_link_access(A["store"], "home", theirs_may_ask=["lead"])
    assert fabric.link_access(A["store"], "home")["theirs_may_ask"] == ["lead"]
    res = _home_turn(B, loop, asked)
    assert res["content"].startswith("HOME GOT") and "Churn is 4%" in res["content"]
    # asked once, as the matrix's question; "Allow & remember" would write the cell
    assert [a[:2] for a in asked] == [("delegate", "lead@office")]
    # office's lead managed it with its own team, and nothing that reaches the machine
    assert set(seen["office_lead_tools"]) <= set(executors.LINKED_LEAD_TOOLS)
    assert "write_file" not in seen["office_lead_tools"] and "run_command" not in seen["office_lead_tools"]
    # kept on office as a conversation of its own, and in its ledger
    convs = [c for c in A["store"].list_conversations(limit=50) if c["title"].startswith("↔ home")]
    assert convs and A["store"].get_messages(convs[0]["id"])[-1]["content"].startswith("OFFICE SAYS")
    rows = A["store"].db.execute("SELECT principal_kind, principal_id, resource, effect FROM audit "
                                 "WHERE action='agent.message'").fetchall()
    assert ("team", "home/Aria", "agent:main", "allow") in [tuple(r) for r in rows]
    # and home's screens heard both halves: Chat, the Office and Telegram all read agent_msg
    talk = [e for e in B["events"] if e.get("type") == "agent_msg" and e.get("phase") != "progress"]
    assert [(e["phase"], e["conversation_id"]) for e in talk] == [("ask", "c-home"), ("reply", "c-home")]
    # and where it was in between: office said its lead took it on (teamlink progress)
    prog = [e["text"] for e in B["events"] if e.get("type") == "agent_msg" and e.get("phase") == "progress"]
    assert any("the lead here, is working on it" in t for t in prog), prog
    assert talk[0]["to"] == "lead@office"


def test_without_the_cell_the_other_side_refuses_in_a_sentence(pair, monkeypatch):
    A, B, inv, loop = pair
    monkeypatch.setattr(providers, "chat", _brains({}))
    res = _home_turn(B, loop, [])
    assert "may not ask" in res["content"] or "not allowed" in res["content"]


def test_a_machine_with_no_agents_is_told_where_work_goes(pair, monkeypatch):
    A, B, inv, loop = pair
    for s in B["store"].list_subagents():
        B["store"].delete_subagent(s["id"])
    fabric.set_link_access(A["store"], "home", theirs_may_ask=["lead"])
    with teamlink.at(B["home"]):
        note = executors.linked_note(B["cfg"], B["store"])
        listing = loop.run_until_complete(B["tb"].linked_teams())
    assert "office" in note and "lead@<team>" in note and "no specialists on this machine" in note
    assert "lead@office (Aria, their lead" in listing


def test_the_gate_and_the_page():
    # the lead's hand-over across a link is the matrix's question; a mission's is not changed
    assert policy.action_of("delegate", {"subagent": "lead@office", "_cross": True}) == \
        ("agent.message", "agent:subagent/lead@office")
    assert policy.action_of("delegate", {"subagent": "analyst@office"})[0] == "agent.invoke"
    office = (ROOT / "agentos/ui/src/js/24d-office.js").read_text()
    assert "handed ${ev.to} on a linked team" in office, "the Office draws work leaving for another team"
    settings = (ROOT / "agentos/ui/src/js/11-settings.js").read_text()
    assert 'data-agent="lead"' in settings, "the link card can let the other team hand tasks to your lead"


def test_the_other_machine_asks_its_person_when_nobody_decided(pair, monkeypatch):
    """Asked for as "the other machine should also get a popup to authorize, only if there is
    a link between them": an undecided pair is asked of the person there, Allow & remember is
    the link's cell, a block written there still refuses without asking."""
    A, B, inv, loop = pair
    monkeypatch.setattr(providers, "chat", _brains({}))
    asked = []

    async def person(lk, frm, agent, name, args, reason, offer):
        asked.append((lk["label"], frm, agent, args["to"], offer["resource"]))
        return True
    A["cp"].linked_approvals = person
    res = _home_turn(B, loop, [])
    assert res["content"].startswith("HOME GOT") and "Churn is 4%" in res["content"]
    assert asked == [("home", "Aria", "Aria", "your lead Aria", "agent:main")]
    rows = [tuple(r) for r in A["store"].db.execute(
        "SELECT action, detail FROM audit WHERE action='link.ask'").fetchall()]
    assert rows and "allowed by the person here" in rows[0][1]

    async def no(*a):
        asked.append("no")
        return False
    A["cp"].linked_approvals = no
    assert "not allowed" in _home_turn(B, loop, [])["content"]
    # a block written here: refused, nobody asked
    asked.clear()
    A["store"].add_grant("team", "home/*", "agent.message", "agent:main", effect="deny", source="user")
    assert "not allowed" in _home_turn(B, loop, [])["content"] and asked == []
