"""Standing permissions for a linked team, and linked agents on a mission's roster.

A question from another team taints the run that answers it, so every step that would
change something needs a person here — and nobody is at a network call to say yes. A
standing permission is that yes, given ahead of time, narrowly: one team, one of your
agents, one action, one folder or tool. What these defend:

- inside its scope the step runs; outside it, a person is still needed;
- the scope is the folder the write would REALLY land in — `..`, symlinks and hidden
  files (.bashrc, .ssh) are never covered, whatever the glob says;
- it applies only when every untrusted thing in the run came from THAT link: a page the
  agent also read puts the person back in the loop;
- `strict` still refuses, and an explicit deny row still wins;
- a shell, anything confirmed every time and anything that changes this OS can never be
  made standing, nor can a home or system folder;
- the approval card's "always" writes exactly the folder-scoped row, and ending the link
  revokes every standing row it held;
- a mission's roster may name `analyst@office`: saved only when that link exists, it
  grants the delegation and no envelope here, and a run sends the task across the link
  where THEIR standing permission decides — the answer landing on the board as untrusted.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import fabric, flows, providers, teamlink                # noqa: E402
from agentos.memory import Store                                      # noqa: E402
from agentos.policy import PDP, Principal, standing_refusal           # noqa: E402
from test_teamlink import pair                                        # noqa: E402,F401

LINKED = [{"tool": "linked team", "source": "home"}]
ANALYST = Principal("subagent", "analyst")


def _gate(tmp_path, taint="ask"):
    cfg = {"autonomy": "full", "workspace": str(tmp_path), "security": {"taint": taint}}
    store = Store(tmp_path / "g.db")
    store.save_subagent({"name": "analyst", "soul": "a"})
    return store, PDP(cfg, store)


def _write(pdp, path, taint=LINKED):
    return pdp.decide(ANALYST, "fs.write", f"fs:{path}",
                      {"risk": "risky", "taint": taint, "reason": "writes a file"})


# ---- the gate --------------------------------------------------------------------------------

def test_inside_the_scope_it_runs_and_outside_a_person_is_still_needed(tmp_path):
    store, pdp = _gate(tmp_path)
    (tmp_path / "shared").mkdir()
    assert _write(pdp, tmp_path / "shared/r.md").effect == "ask", "nothing is standing yet"
    got = fabric.add_standing(store, "home", "analyst", "fs.write", str(tmp_path / "shared"))
    assert got["scope"] == f"fs:{os.path.realpath(tmp_path / 'shared')}/*"
    d = _write(pdp, tmp_path / "shared/week-39/r.md")
    assert d.effect == "allow" and d.rule == got["id"]
    assert _write(pdp, tmp_path / "elsewhere.md").effect == "ask"
    # another agent, another action, another team: none of them is covered
    assert pdp.decide(Principal("subagent", "writer"), "fs.write", f"fs:{tmp_path}/shared/x",
                      {"risk": "risky", "taint": LINKED}).effect == "ask"
    assert _write(pdp, tmp_path / "shared/r.md",
                  taint=[{"tool": "linked team", "source": "office"}]).effect == "ask"


def test_the_scope_is_where_the_write_really_lands(tmp_path):
    store, pdp = _gate(tmp_path)
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared/out").symlink_to(tmp_path)
    fabric.add_standing(store, "home", "analyst", "fs.write", str(tmp_path / "shared"))
    for sneaky in ("shared/../escape.md", "shared/out/escape.md", "shared/.bashrc",
                   "shared/.git/hooks/pre-commit", "shared/x/.ssh/authorized_keys"):
        assert _write(pdp, f"{tmp_path}/{sneaky}").effect == "ask", sneaky
    # a relative path is the workspace's, exactly as the write tool resolves it
    assert _write(pdp, "shared/rel.md").effect == "allow"


def test_a_page_read_in_the_same_run_puts_the_person_back(tmp_path):
    store, pdp = _gate(tmp_path)
    fabric.add_standing(store, "home", "analyst", "fs.write", str(tmp_path / "shared"))
    mixed = LINKED + [{"tool": "fetch_url", "source": "https://example.com"}]
    assert _write(pdp, tmp_path / "shared/r.md", taint=mixed).effect == "ask"
    two_links = LINKED + [{"tool": "linked team", "source": "office"}]
    assert _write(pdp, tmp_path / "shared/r.md", taint=two_links).effect == "ask"


def test_strict_still_refuses(tmp_path):
    store, pdp = _gate(tmp_path, taint="strict")
    fabric.add_standing(store, "home", "analyst", "fs.write", str(tmp_path / "shared"))
    assert _write(pdp, tmp_path / "shared/r.md").effect == "deny"


def test_an_explicit_deny_still_wins(tmp_path):
    store, pdp = _gate(tmp_path)
    fabric.add_standing(store, "home", "analyst", "fs.write", str(tmp_path / "shared"))
    store.add_grant("subagent", "analyst", "fs.write", f"fs:{os.path.realpath(tmp_path)}/shared/*",
                    effect="deny", source="user")
    assert _write(pdp, tmp_path / "shared/r.md").effect == "deny"


@pytest.mark.parametrize("action,scope", [
    ("tool.use", "tool:run_command*"), ("tool.use", "tool:run_python*"),
    ("tool.use", "tool:power_action*"), ("tool.use", "tool:mail_send*"),
    ("tool.use", "tool:configure_agentos*"), ("tool.use", "tool:*"),
    ("agent.invoke", "agent:subagent/*"), ("flow.write", "flow:x"), ("net.fetch", "net:*"),
    ("fs.write", "fs:/*"), ("fs.write", "fs:/etc/*"), ("fs.write", "fs:/home/someone/*"),
    ("fs.write", f"fs:{os.path.expanduser('~')}/*"), ("fs.write", "fs:/srv/x/.config/*"),
    ("fs.write", "relative/*"),
])
def test_what_can_never_be_standing(action, scope):
    assert standing_refusal(action, scope)


def test_what_can(tmp_path):
    assert not standing_refusal("fs.write", "fs:/home/someone/shared/*")
    assert not standing_refusal("tool.use", "tool:save_report*")
    with pytest.raises(ValueError):
        fabric.add_standing(Store(tmp_path / "x.db"), "home", "ghost", "fs.write", "/srv/x")
    store, _ = _gate(tmp_path)
    with pytest.raises(ValueError, match="full path"):
        fabric.add_standing(store, "home", "analyst", "fs.write", "shared")
    with pytest.raises(ValueError, match="shell"):
        fabric.add_standing(store, "home", "analyst", "tool.use", "run_command")


def test_the_card_offers_the_folder_and_a_rows_own_audit(tmp_path):
    store, pdp = _gate(tmp_path)
    (tmp_path / "shared").mkdir()
    d = _write(pdp, tmp_path / "shared/r.md")
    assert d.effect == "ask" and d.grant_offer
    o = d.grant_offer
    assert (o["principal_kind"], o["principal_id"], o["action"]) == ("team", "home/*", "team.act")
    assert o["resource"] == f"analyst|fs.write|fs:{os.path.realpath(tmp_path / 'shared')}/*"
    assert "home" in o["label"]
    # the card's "remember" writes exactly this row — and then it stands
    store.add_grant(o["principal_kind"], o["principal_id"], o["action"], o["resource"], source="user")
    assert _write(pdp, tmp_path / "shared/next-week.md").effect == "allow"
    # no offer where there is nothing a link could be trusted with
    assert _write(pdp, tmp_path / "shared/r.md",
                  taint=LINKED + [{"tool": "fetch_url", "source": "x"}]).grant_offer is None
    assert _write(pdp, tmp_path / "shared/.bashrc").grant_offer is None
    rows = store.db.execute("SELECT action, resource FROM audit WHERE action LIKE 'grant.%'").fetchall()
    assert ("grant.write", f"team:home/* team.act {o['resource']}") in [tuple(r) for r in rows], \
        "writing a standing permission is itself in the ledger"


def test_ending_the_link_revokes_every_standing_row(tmp_path):
    store, pdp = _gate(tmp_path)
    fabric.add_standing(store, "home", "analyst", "fs.write", str(tmp_path / "shared"))
    fabric.add_standing(store, "home", "analyst", "tool.use", "save_report")
    fabric.add_standing(store, "office", "analyst", "tool.use", "notify")
    assert len(fabric.standing(store, "home")) == 2
    fabric.forget_link_grants(store, "home")
    assert fabric.standing(store, "home") == [] and len(fabric.standing(store, "office")) == 1
    assert _write(pdp, tmp_path / "shared/r.md").effect == "ask"


# ---- across a real link ------------------------------------------------------------------------

def _worker(target_for):
    """The analyst writes wherever the question says; the master delegates, then finishes."""
    def chat(cfg, model, messages, tools, options=None):
        async def gen():
            sys_txt = next((m["content"] for m in messages if m["role"] == "system"), "")
            user = next(m["content"] for m in messages if m["role"] == "user")
            tools_seen = [m for m in messages if m["role"] == "tool"]
            if "MASTER ORCHESTRATOR" in sys_txt:
                if not tools_seen:
                    yield {"type": "tool_call", "id": "m1", "name": "delegate",
                           "args": {"subagent": "analyst@office", "task": "write the weekly report"}}
                else:
                    yield {"type": "tool_call", "id": "m2", "name": "finish",
                           "args": {"summary": "done: " + tools_seen[-1]["content"][:200]}}
                yield {"type": "finish", "reason": "tool_calls"}
                return
            if "SOUL-analyst" in sys_txt and not tools_seen:
                yield {"type": "tool_call", "id": "w1", "name": "write_file",
                       "args": {"path": target_for(user), "content": "Pro churn 4%"}}
                yield {"type": "finish", "reason": "tool_calls"}
                return
            yield {"type": "text", "text": "REPORT " + (tools_seen[-1]["content"] if tools_seen else "")}
            yield {"type": "finish", "reason": "stop"}
        return gen()
    return chat


def _ask(A, loop, question):
    async def go():
        with teamlink.at(A["home"]):
            return await A["cp"].answer_linked(teamlink.find("", "home"), {
                "op": "ask", "from": "digest-master", "to": "analyst", "question": question,
                "chain": ["digest-master"], "root": "r1"})
    return loop.run_until_complete(go())


def test_a_linked_question_writes_inside_a_standing_folder_and_nowhere_else(pair, tmp_path, monkeypatch):
    A, B, inv, loop = pair
    A["store"].save_subagent({"name": "analyst", "soul": "SOUL-analyst", "autonomy_cap": "full",
                              "tools": ["write_file"]})
    fabric.set_link_access(A["store"], "home", theirs_may_ask=["analyst"])
    shared = tmp_path / "office-shared"
    shared.mkdir()
    fabric.add_standing(A["store"], "home", "analyst", "fs.write", str(shared))
    monkeypatch.setattr(providers, "chat", _worker(
        lambda q: str(shared / "report.md") if "SHARED" in q else str(tmp_path / "outside.md")))

    out = _ask(A, loop, "write it in the SHARED folder")
    assert (shared / "report.md").read_text() == "Pro churn 4%", out
    out = _ask(A, loop, "write it somewhere else")
    assert not (tmp_path / "outside.md").exists()
    assert "needs a person" in out["text"]


def test_a_mission_can_have_an_agent_on_a_linked_team_and_runs_it_there(pair, tmp_path, monkeypatch):
    A, B, inv, loop = pair
    A["store"].save_subagent({"name": "analyst", "soul": "SOUL-analyst", "autonomy_cap": "full",
                              "tools": ["write_file"]})
    fabric.set_link_access(A["store"], "home", theirs_may_ask=["analyst"])
    shared = tmp_path / "office-shared"
    shared.mkdir()
    fabric.add_standing(A["store"], "home", "analyst", "fs.write", str(shared))
    monkeypatch.setattr(providers, "chat", _worker(lambda q: str(shared / "weekly.md")))

    body = {"name": "digest", "mission": "Have the office analyst file the weekly report.",
            "roster": ["analyst@office"], "permissions": {"tools": [], "memory": "none"},
            "sinks": [], "triggers": [{"kind": "cron", "cron": "0 9 * * 1"}]}
    with teamlink.at(B["home"]):
        with pytest.raises(ValueError, match="no linked team called 'nowhere'"):
            flows.validate({**body, "roster": ["analyst@nowhere"]}, B["store"])
        flow, _ = flows.save(B["store"], body)
        grants = flows.declared_grants(flow)
    inv_rows = [g for g in grants if g["action"] == "agent.invoke"]
    assert [g["resource"] for g in inv_rows] == ["agent:subagent/analyst@office"]
    assert "linked team 'office'" in inv_rows[0]["note"] and "untrusted" in inv_rows[0]["note"]
    assert not [g for g in grants if g["principal_kind"] == "subagent"], \
        "a member on another team gets no envelope here — it runs under THEIR gate"

    async def run():
        with teamlink.at(B["home"]):
            return await B["cp"].run_flow(B["store"].get_flow("digest") | {"enabled": 1},
                                          "", origin={"surface": "task"})
    res = loop.run_until_complete(run())
    assert (shared / "weekly.md").read_text() == "Pro churn 4%", res
    board = {a["handle"]: a for a in B["store"].artifact_index(res["run_id"])}
    linked = [a for a in board.values() if a.get("agent") == "analyst@office"]
    assert linked and linked[0]["tainted"], "an answer from another machine lands untrusted"


# ---- the faces -----------------------------------------------------------------------------

def test_the_terminal_lets_lists_and_unlets(pair, tmp_path):
    import subprocess
    A, B, inv, loop = pair
    env = {**os.environ, "AGENTOS_HOME": str(A["home"]), "NO_COLOR": "1", "AGENTOS_VAULT_KEYRING": "0"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "agentos", "link", *a],  # noqa: E731
                                    cwd=Path(__file__).parent.parent, env=env,
                                    capture_output=True, text=True, timeout=60)
    shared = tmp_path / "shared"
    r = run("let", "home", "analyst", "fs.write", str(shared), "--days", "7")
    assert r.returncode == 0 and "without asking for 7 day(s)" in r.stdout, r.stdout + r.stderr
    gid = r.stdout.split("(id ")[1].split(" ")[0]
    r = run("let", "home", "analyst", "tool.use", "run_command")
    assert r.returncode == 2 and "refused" in r.stdout and "shell" in r.stdout
    r = run("standing", "home")
    assert gid in r.stdout and "fs.write" in r.stdout and "until" in r.stdout
    assert "without asking: analyst fs.write" in run().stdout
    assert run("unlet", "home", gid).returncode == 0
    assert "nothing" in run("standing", "home").stdout


def test_settings_and_the_missions_editor_have_it():
    root = Path(__file__).parent.parent / "agentos/ui/src/js"
    st = (root / "11-settings.js").read_text()
    assert "/standing" in st and "tlStandAdd" in st, "Settings lists, adds and removes standing permissions"
    fab = (root / "13-fabric.js").read_text()
    assert "@" in fab and "/api/team/links" in fab, "the roster picker offers agents on linked teams"
