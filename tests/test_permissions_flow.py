"""Permissions → Flow: the gate's steps, a pretend call traced through them, and the
Ledger naming the step that decided each row (policy.STAGES / stage_of,
/api/policy/trace, 20b-permflow.js)."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import policy                                   # noqa: E402
from agentos.memory import Store                             # noqa: E402
from agentos.policy import PDP, Principal, STAGES, stage_of  # noqa: E402

ROOT = Path(__file__).parent.parent
KEYS = [k for k, _, _ in STAGES]


def test_every_named_rule_in_the_gate_lands_on_a_step():
    """A rule the gate can return that no step claims would light nothing on the page."""
    src = (ROOT / "agentos/policy.py").read_text()
    for rule in set(re.findall(r'rule="([a-z0-9-]+)"', src)):
        assert stage_of(rule) in KEYS, rule


def test_the_steps_are_in_the_gates_order():
    assert KEYS == ["hard", "builtin", "reach", "channel", "taint", "rate", "team",
                    "rules", "default", "person"]
    assert stage_of("hard-block") == "hard"
    assert stage_of("taint") == "taint"
    assert stage_of("quarantined") == "rate"
    assert stage_of("io-gate") == "rules"
    assert stage_of("roster") == "default" and stage_of("") == "default"
    assert stage_of("0123456789ab") == "rules", "a grant row is your rules"
    assert stage_of("0123456789ab", "agent.message") == "team", "a matrix cell is the team's"


def test_the_step_named_matches_what_the_gate_decided(tmp_path):
    store = Store(tmp_path / "t.db")
    pdp = PDP({"autonomy": "balanced"}, store)
    me, app = Principal("user", ""), Principal("app", "a1")
    gid = store.add_grant("app", "a1", "net.fetch", "net:*")
    d = pdp.decide(app, "net.fetch", "net:https://x.test", {"risk": "safe", "audit": False})
    assert d.rule == gid and stage_of(d.rule, d.action) == "rules"
    d = pdp.decide(me, "tool.use", "tool:run_command rm -rf /", {"risk": "blocked", "audit": False})
    assert stage_of(d.rule) == "hard"
    d = pdp.decide(me, "fs.write", "fs:/tmp/a", {"risk": "risky", "audit": False,
                                                 "taint": [{"source": "a page"}]})
    assert d.effect == "ask" and stage_of(d.rule) == "taint"


def test_the_trace_route_walks_the_steps_and_records_nothing(tmp_path):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        store = servermod.state["store"]
        before = len(store.audit_list(limit=2000))
        r = cl.post("/api/policy/trace", json={"principal_kind": "user", "tool": "run_command",
                                               "detail": "rm -rf /"}).json()
        assert r["effect"] == "deny" and r["stage"] == "hard"
        assert [s["state"] for s in r["steps"]][:2] == ["decided", "skipped"]
        assert r["resource"] == "tool:run_command rm -rf /"
        r = cl.post("/api/policy/trace", json={"principal_kind": "user", "tool": "write_file",
                                               "detail": "notes.md", "after_web": True}).json()
        assert r["effect"] == "ask" and r["stage"] == "taint"
        assert [s["state"] for s in r["steps"]].count("passed") == KEYS.index("taint")
        gid = store.add_grant("user", "", "tool.use", "tool:run_command echo*",
                              note="test rule")
        try:
            r = cl.post("/api/policy/trace", json={"principal_kind": "user", "tool": "run_command",
                                                   "detail": "echo hi"}).json()
            assert r["effect"] == "allow" and r["stage"] == "rules" and r["grant"]["id"] == gid
        finally:
            store.revoke_grant(gid)
        assert cl.post("/api/policy/trace", json={"tool": "no_such_tool"}).status_code == 400
        assert cl.post("/api/policy/trace", json={"principal_kind": "wizard",
                                                  "tool": "read_file"}).status_code == 400
        # a probe is not an access: the grant writes above are ledger rows, the traces are not
        rows = store.audit_list(limit=2000)
        assert not [a for a in rows[:len(rows) - before] if not a["action"].startswith("grant.")]
        assert [s["key"] for s in cl.get("/api/policy/stages").json()["stages"]] == KEYS


def test_the_ledger_route_names_the_step():
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        servermod.state["toolbox"].pdp.decide(Principal("user", ""), "tool.use",
                                              "tool:run_command rm -rf /", {"risk": "blocked"})
        rows = cl.get("/api/audit?limit=5").json()["entries"]
        assert rows[0]["stage"] == "hard"


def test_the_page_reads_the_steps_from_the_server():
    js = (ROOT / "agentos/ui/src/js/20b-permflow.js").read_text()
    assert "/api/policy/stages" in js and "/api/policy/trace" in js
    assert "Hard blocks" not in js, "the steps' words come from policy.STAGES, not a copy"
    perm = (ROOT / "agentos/ui/src/js/20-permissions.js").read_text()
    assert "tab:'flow'" in perm and "flow:permFlow" in perm, "Flow is the first thing shown"
    assert "audPath" in (ROOT / "agentos/ui/src/js/19a-audit.js").read_text()
    assert policy.STAGES and all(len(a) <= 90 for _, _, a in STAGES)
