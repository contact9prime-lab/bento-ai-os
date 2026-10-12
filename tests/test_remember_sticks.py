""""Allow & remember" sticks until you take it back.

Asked: in normal mode, when I allow and remember between the agent and a sub agent, or
between two sub agents, does it stick around forever? It does. The button writes an
ordinary grant with no expiry and every surface ('*'), in the person's own database, so
it survives a restart and applies from Telegram as well as the desk. It ends only when
someone revokes it (Permissions, the matrix cell, `bento team ask`). Inside a mission
only the mission's own rules count, which is the one place a desk decision does not reach.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import fabric                                    # noqa: E402
from agentos.memory import Store                              # noqa: E402
from agentos.policy import PDP, Principal, MAIN               # noqa: E402

CFG = {"autonomy": "balanced", "team": {"talk": "matrix"}}


def _remember(store, dec):
    """What every "Allow & remember" button does with the card's offer."""
    o = dec.grant_offer
    assert o, "the card offers a remember"
    store.add_grant(o["principal_kind"], o["principal_id"], o["action"], o["resource"],
                    source="user", note="allowed & remembered from an approval prompt")


def _hand_over(pdp, who, surface="gui"):
    return pdp.decide(MAIN, "agent.invoke", f"agent:subagent/{who}",
                      {"surface": surface, "autonomy": "balanced"})


def _ask(pdp, a, b, surface="gui", flow=""):
    return pdp.decide(Principal("subagent", a), "agent.message", f"agent:subagent/{b}",
                      {"surface": surface, "flow": flow})


def test_lead_to_specialist_is_remembered_across_a_restart_and_every_surface(tmp_path):
    db = tmp_path / "a.db"
    store = Store(db)
    first = _hand_over(PDP(CFG, store), "researcher")
    assert first.effect == "ask"
    _remember(store, first)
    store.db.close()
    again = PDP(CFG, Store(db))                     # a restart: a new process, same file
    for surface in ("gui", "telegram", "whatsapp", "tui"):
        assert _hand_over(again, "researcher", surface).effect == "allow", surface
    # it is scoped to that one specialist
    assert _hand_over(again, "writer").effect == "ask"
    # and nothing about it runs out
    g = [r for r in again.store.list_grants() if r["action"] == "agent.invoke"][0]
    assert not g.get("expires_at") and (g.get("surfaces") or "*") == "*"


def test_specialist_to_specialist_is_remembered_as_its_matrix_cell(tmp_path):
    db = tmp_path / "b.db"
    store = Store(db)
    first = _ask(PDP(CFG, store), "researcher", "validator")
    assert first.effect == "ask"
    _remember(store, first)
    store.db.close()
    store = Store(db)
    pdp = PDP(CFG, store)
    assert _ask(pdp, "researcher", "validator").effect == "allow"
    assert _ask(pdp, "researcher", "validator", surface="telegram").effect == "allow"
    # one direction only: the validator asking the researcher is its own cell
    assert _ask(pdp, "validator", "researcher").effect == "ask"
    # the matrix shows it as allowed, so Settings and `bento team` can take it back
    assert fabric.matrix(store, CFG)["cells"].get("researcher>validator") == "allow"


def test_it_ends_when_you_revoke_it(tmp_path):
    store = Store(tmp_path / "c.db")
    for n in ("researcher", "validator"):
        store.save_subagent({"name": n, "soul": n, "tools": ["recall"]})
    pdp = PDP(CFG, store)
    _remember(store, _ask(pdp, "researcher", "validator"))
    assert _ask(pdp, "researcher", "validator").effect == "allow"
    fabric.set_cell(store, "researcher", "validator", "ask")   # back to "ask me"
    assert _ask(pdp, "researcher", "validator").effect == "ask"


def test_a_desk_decision_does_not_reach_into_a_mission(tmp_path):
    store = Store(tmp_path / "d.db")
    pdp = PDP(CFG, store)
    _remember(store, _ask(pdp, "researcher", "validator"))
    # inside a mission only the mission's own rules count
    assert _ask(pdp, "researcher", "validator", flow="digest").effect == "deny"


def test_deleting_an_agent_takes_its_remembered_permissions_with_it(tmp_path):
    # Found while answering the question above: "forever" outlived the agent. A new
    # specialist created later under the same name inherited consent nobody gave it.
    store = Store(tmp_path / "e.db")
    for n in ("researcher", "validator", "writer"):
        store.save_subagent({"name": n, "soul": n, "tools": ["recall"]})
    pdp = PDP(CFG, store)
    _remember(store, _hand_over(pdp, "researcher"))
    _remember(store, _ask(pdp, "researcher", "validator"))
    _remember(store, _ask(pdp, "writer", "researcher"))
    _remember(store, _ask(pdp, "writer", "validator"))          # not about the researcher
    store.delete_subagent(store.get_subagent("researcher")["id"])
    store.save_subagent({"name": "researcher", "soul": "someone new", "tools": ["recall"]})
    assert _hand_over(pdp, "researcher").effect == "ask"
    assert _ask(pdp, "researcher", "validator").effect == "ask"
    assert _ask(pdp, "writer", "researcher").effect == "ask"
    assert _ask(pdp, "writer", "validator").effect == "allow", "other agents keep theirs"
    # and each revocation is in the ledger
    rows = store.db.execute("SELECT detail FROM audit WHERE action='grant.revoke'").fetchall()
    assert sum("was deleted" in (r["detail"] or "") for r in rows) == 3


# ------------------------------------------------------------------ shell commands
#
# Reported as "once the approval is given, like approved always, it still asks again".
# "Always" on a shell command remembered ONE pattern, for the first program, and a pattern
# covers a chain one command at a time and never a line with a redirect, so the commands
# an agent actually runs (`cd app && npm test`, `pytest 2>&1 | tail -5`) asked every time.

def _shell(pdp, cmd):
    return pdp.decide_tool(MAIN, "run_command", {"command": cmd}, "risky", surface="gui",
                           autonomy="balanced", conversation_id="c1")


def _always(store, dec):
    from agentos.policy import write_remembered
    assert dec.effect == "ask" and dec.grant_offer, dec
    write_remembered(store, dec.grant_offer, "always", via="a test")


def test_always_covers_every_program_in_a_chain(tmp_path):
    store = Store(tmp_path / "s.db")
    pdp = PDP(CFG, store)
    dec = _shell(pdp, "cd app && npm test")
    assert dec.grant_offer["resource"] == "tool:run_command {cd*,npm*}"
    _always(store, dec)
    assert _shell(pdp, "cd app && npm test").effect == "allow"
    assert _shell(pdp, "cd web && npm run build").effect == "allow", "the same programs, other arguments"
    assert _shell(pdp, "cd app && rm -rf build").effect == "ask", "a program you never allowed"


def test_always_on_a_line_with_a_redirect_covers_that_line(tmp_path):
    store = Store(tmp_path / "r.db")
    pdp = PDP(CFG, store)
    line = "python -m pytest -q 2>&1 | tail -5"
    _always(store, _shell(pdp, line))
    assert _shell(pdp, line).effect == "allow", "the same command again"
    # a wildcard never covers a redirect, so another one still asks
    assert _shell(pdp, "python -m pytest -q > ~/.bashrc").effect == "ask"


def test_a_simple_command_is_still_one_pattern(tmp_path):
    store = Store(tmp_path / "p.db")
    pdp = PDP(CFG, store)
    dec = _shell(pdp, "git status")
    assert dec.grant_offer["resource"] == "tool:run_command git*"
    _always(store, dec)
    assert _shell(pdp, "git log --oneline").effect == "allow"
    assert _shell(pdp, "git log; bash").effect == "ask", "a chain is still read one command at a time"
