"""The access ledger.

`logs` is the operator's diary. This is the structured record of who was allowed
to do what, on which way in, and under which rule — the question you cannot
answer by grepping a JSON blob. Every PDP decision writes exactly one row.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos.memory import Store                                   # noqa: E402
from agentos.policy import PDP, Principal, action_of               # noqa: E402


def _pdp(tmp_path, autonomy="balanced", cfg=None):
    store = Store(tmp_path / "t.db")
    return PDP({"autonomy": autonomy, **(cfg or {})}, store), store


def test_every_decision_lands_in_the_ledger(tmp_path):
    pdp, store = _pdp(tmp_path)
    pdp.decide(Principal("subagent", "researcher"), "fs.write", "fs:/tmp/x",
               {"risk": "risky", "surface": "telegram", "space_id": "s1"})
    rows = store.audit_list()
    assert len(rows) == 1
    a = rows[0]
    assert a["principal_kind"] == "subagent" and a["principal_id"] == "researcher"
    assert a["action"] == "fs.write" and a["resource"] == "fs:/tmp/x"
    assert a["surface"] == "telegram" and a["space_id"] == "s1"
    assert a["effect"] in ("allow", "deny", "ask")
    assert a["rule"]                       # never blank: something decided this


def test_allow_deny_and_ask_are_all_recorded(tmp_path):
    pdp, store = _pdp(tmp_path)
    user = Principal("user", "")
    pdp.decide(user, "fs.read", "fs:/tmp/a", {"risk": "safe", "surface": "gui"})
    pdp.decide(user, "fs.write", "fs:/tmp/b", {"risk": "risky", "surface": "gui"})
    pdp.decide(user, "tool.use", "tool:rm -rf /", {"risk": "blocked", "surface": "gui"})
    effects = {r["effect"] for r in store.audit_list()}
    assert effects == {"allow", "ask", "deny"}
    summary = store.audit_summary()
    assert summary["total"] == 3
    assert summary["effects"]["deny"] == 1


def test_the_outcome_is_stamped_onto_the_decision(tmp_path):
    """A permission that was granted and then failed must not look like one that
    was granted and worked."""
    pdp, store = _pdp(tmp_path, autonomy="full")
    dec = pdp.decide(Principal("user", ""), "tool.use", "tool:fetch_url",
                     {"risk": "risky", "surface": "gui"})
    assert dec.audit_id
    store.audit_finish(dec.audit_id, "error", detail="connection refused", duration_ms=42)
    row = store.audit_list()[0]
    assert row["effect"] == "allow" and row["outcome"] == "error"
    assert "refused" in row["detail"] and row["duration_ms"] == 42


def test_a_read_only_channel_is_recorded_as_a_channel_refusal(tmp_path):
    pdp, store = _pdp(tmp_path, cfg={"channels": {"telegram": {"posture": "read_only"}}})
    dec = pdp.decide(Principal("user", ""), "fs.write", "fs:/tmp/x",
                     {"risk": "risky", "surface": "telegram"})
    assert dec.effect == "deny"
    row = store.audit_list()[0]
    assert row["rule"] == "channel-read-only"
    assert row["surface"] == "telegram"


def test_the_ledger_is_filterable_the_way_grants_are_written(tmp_path):
    pdp, store = _pdp(tmp_path)
    pdp.decide(Principal("app", "a1"), "mcp.use", "mcp:github/create_issue",
               {"risk": "risky", "surface": "gui"})
    pdp.decide(Principal("subagent", "writer"), "media.generate", "media:image",
               {"risk": "risky", "surface": "task"})
    assert len(store.audit_list(principal_kind="app")) == 1
    assert len(store.audit_list(surface="task")) == 1
    assert len(store.audit_list(action="media.generate")) == 1
    assert len(store.audit_list(q="github")) == 1


def test_top_denied_surfaces_what_keeps_being_refused(tmp_path):
    pdp, store = _pdp(tmp_path)
    for _ in range(3):
        pdp.decide(Principal("subagent", "s"), "tool.use", "tool:develop_agentos",
                   {"risk": "safe", "surface": "gui"})
    top = store.audit_summary()["top_denied"]
    assert top and top[0]["n"] == 3
    assert "develop_agentos" in top[0]["resource"]


def test_an_internal_probe_is_not_an_access(tmp_path):
    """'Could I do this?' asked by the UI to grey out a button is not somebody
    doing something, and filling the ledger with it would bury the real entries."""
    pdp, store = _pdp(tmp_path)
    pdp.decide(Principal("user", ""), "fs.read", "fs:/tmp/a",
               {"risk": "safe", "surface": "gui", "audit": False})
    assert store.audit_list() == []


def test_a_broken_ledger_never_takes_a_decision_down(tmp_path):
    pdp, store = _pdp(tmp_path)
    store.db.execute("DROP TABLE audit")
    store.db.commit()
    dec = pdp.decide(Principal("user", ""), "fs.read", "fs:/tmp/a",
                     {"risk": "safe", "surface": "gui"})
    assert dec.effect == "allow"      # the decision still happened
    assert dec.audit_id == ""


def test_media_and_space_actions_are_grantable_vocabulary(tmp_path):
    """They are separate actions, not another tool.use string, so 'may look at the
    gallery but may not bill my image provider' is expressible as a grant."""
    assert action_of("generate_image", {"prompt": "x"}) == ("media.generate", "media:image")
    assert action_of("list_assets", {}) == ("media.read", "media:*")
    assert action_of("get_asset", {"asset_id": "a1"}) == ("media.read", "media:a1")
    assert action_of("create_space", {"name": "Alpha"}) == ("space.write", "space:Alpha")

    pdp, store = _pdp(tmp_path)
    sub = Principal("subagent", "writer")
    store.add_grant("subagent", "writer", "media.read", "media:*")
    assert pdp.decide(sub, "media.read", "media:*", {"risk": "safe"}).effect == "allow"
    assert pdp.decide(sub, "media.generate", "media:image",
                      {"risk": "risky"}).effect == "ask"


def test_memory_resources_are_space_qualified(tmp_path):
    """So a grant can say 'this subagent may write memory in one space only'."""
    action, resource = action_of("remember", {"scope": "user", "space_id": "s1"})
    assert action == "memory.write" and resource == "memory:user@s1"
    assert action_of("kg_add", {"space_id": "s1"})[1] == "kg:s1"
    assert action_of("remember", {"scope": "user"})[1] == "memory:user"

    pdp, store = _pdp(tmp_path)
    sub = Principal("subagent", "w")
    store.add_grant("subagent", "w", "memory.write", "memory:*@s1")
    assert pdp.decide(sub, "memory.write", "memory:user@s1", {"risk": "risky"}).effect == "allow"
    assert pdp.decide(sub, "memory.write", "memory:user@s2", {"risk": "risky"}).effect == "ask"


def test_logs_carry_the_conversation_as_a_column_now(tmp_path):
    """It used to ride inside the meta JSON, which made it unfilterable."""
    store = Store(tmp_path / "t.db")
    store.log("turn", "hello", {"conversation_id": "c1", "space_id": "s1"})
    store.log("turn", "elsewhere", {}, conversation_id="c2")
    assert len(store.list_logs(conversation_id="c1")) == 1
    assert store.list_logs(conversation_id="c2")[0]["message"] == "elsewhere"
    # the same visibility rule as everywhere else: a space sees its own AND global
    assert {r["message"] for r in store.list_logs(space="s1")} == {"hello", "elsewhere"}
    assert [r["message"] for r in store.list_logs(space=store.GLOBAL_ONLY)] == ["elsewhere"]
