"""The ledger is tamper-evident, self-describing, and can be made fail-closed.

'Everything a principal does goes in the ledger' is only worth as much as the
ledger's own integrity. These defend three enterprise properties: a deleted or
edited row is detectable, a row says which account acted (not only which file it
sits in), and an operator can require that nothing happens off the record.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos.memory import Store                                   # noqa: E402
from agentos.policy import PDP, Principal                          # noqa: E402

APP = Principal("app", "notes")


@pytest.fixture()
def pdp(tmp_path):
    return PDP({"autonomy": "balanced"}, Store(tmp_path / "t.db"))


def _decisions(pdp, n):
    for i in range(n):
        pdp.decide(APP, "tool.use", f"tool:fetch_url {i}", {"risk": "safe", "surface": "gui"})


# ---------------------------------------------------------------------------
# Tamper-evidence
# ---------------------------------------------------------------------------

def test_an_untouched_chain_verifies(pdp):
    _decisions(pdp, 6)
    v = pdp.store.audit_verify()
    assert v["ok"] and v["checked"] == 6 and v["head_seq"] == 6


def test_editing_a_recorded_row_is_detected(pdp):
    """Changing what a decision said, after the fact, is the anti-forensic move the
    chain exists to catch."""
    _decisions(pdp, 6)
    pdp.store.db.execute("UPDATE audit SET resource='tool:evil' WHERE seq=3")
    pdp.store.db.commit()
    v = pdp.store.audit_verify()
    assert not v["ok"] and v["at_seq"] == 3 and "altered" in v["reason"]


def test_deleting_a_row_leaves_a_detectable_gap(pdp):
    _decisions(pdp, 6)
    pdp.store.db.execute("DELETE FROM audit WHERE seq=3")
    pdp.store.db.commit()
    v = pdp.store.audit_verify()
    assert not v["ok"] and "deleted" in v["reason"]


def test_stamping_an_outcome_does_not_break_the_chain(pdp):
    """The outcome is written after the decision, on purpose, so it is outside the
    hash. audit_finish must not look like tampering."""
    aid = pdp.decide(APP, "tool.use", "tool:fetch_url", {"risk": "safe", "surface": "gui"}).audit_id
    pdp.store.audit_finish(aid, "ok", "done", 12)
    assert pdp.store.audit_verify()["ok"]


def test_the_chain_survives_a_restart(tmp_path):
    """A new Store on the same file must continue the chain, not fork a second one
    from seq 1 that would read as a break."""
    db = tmp_path / "t.db"
    _decisions(PDP({}, Store(db)), 3)
    pdp2 = PDP({}, Store(db))          # 'restart'
    _decisions(pdp2, 3)
    v = pdp2.store.audit_verify()
    assert v["ok"] and v["head_seq"] == 6


# ---------------------------------------------------------------------------
# Self-describing
# ---------------------------------------------------------------------------

def test_a_row_records_the_acting_account(tmp_path):
    """On a multi-user machine, 'which user' must be in the row, not only implied by
    which file it lives in — or a merged/exported ledger loses it."""
    import agentos.config as cfgmod
    import agentos.users as usersmod
    home = tmp_path / "home"
    orig = cfgmod.AGENTOS_HOME
    cfgmod.AGENTOS_HOME = home
    try:
        usersmod.reset_caches()
        u = usersmod.create("ada", "hunter2hunter")
        st = usersmod.store_for(u["id"])
        with usersmod.as_user(u["id"]):
            PDP({}, st).decide(APP, "tool.use", "tool:x", {"risk": "safe", "surface": "gui"})
        row = st.db.execute("SELECT uid FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        assert row["uid"] == u["id"]
    finally:
        cfgmod.AGENTOS_HOME = orig
        usersmod.reset_caches()
        usersmod.set_current("")


# ---------------------------------------------------------------------------
# Fail-closed
# ---------------------------------------------------------------------------

def test_fail_closed_refuses_an_allow_that_cannot_be_logged(tmp_path, monkeypatch):
    """With the option on, an adversary who wedges the ledger cannot thereby buy
    un-logged-but-allowed actions."""
    pdp = PDP({"autonomy": "balanced", "security": {"audit_fail_closed": True}},
              Store(tmp_path / "t.db"))
    monkeypatch.setattr(pdp.store, "audit_add", lambda *a, **k: "")   # ledger wedged
    dec = pdp.decide(APP, "tool.use", "tool:fetch_url", {"risk": "safe", "surface": "gui"})
    assert dec.effect == "deny" and dec.rule == "audit-unavailable"


def test_fail_open_is_the_default(tmp_path, monkeypatch):
    """A home machine would rather keep working than stop when its disk is full."""
    pdp = PDP({"autonomy": "balanced"}, Store(tmp_path / "t.db"))
    monkeypatch.setattr(pdp.store, "audit_add", lambda *a, **k: "")
    dec = pdp.decide(APP, "tool.use", "tool:fetch_url", {"risk": "safe", "surface": "gui"})
    assert dec.effect == "allow"


def test_a_probe_is_not_subject_to_fail_closed(tmp_path, monkeypatch):
    """audit=False is a 'could this principal?' filter, not an access; fail-closed
    must not turn tool-list filtering into denials."""
    pdp = PDP({"autonomy": "balanced", "security": {"audit_fail_closed": True}},
              Store(tmp_path / "t.db"))
    monkeypatch.setattr(pdp.store, "audit_add", lambda *a, **k: "")
    dec = pdp.decide(APP, "tool.use", "tool:fetch_url",
                     {"risk": "safe", "surface": "gui", "audit": False})
    assert dec.effect == "allow"
