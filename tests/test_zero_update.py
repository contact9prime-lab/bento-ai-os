"""A Zero stays current with its hub (ties.py, server._zeros_keep_current / _zero_update_from_hub,
the kiosk's update offer). Asked for as "if Bento is updated, ask the hub to update the Pi, or the
Pi can check and ask the user to update itself". A hub and a Zero over real mTLS (test_zero_mind)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agentos import __version__, teamlink, ties          # noqa: E402
from test_zero_mind import _on, hz                      # noqa: E402,F401

ROOT = Path(__file__).parent.parent


def _hub_link(H, Z):
    """The hub's link to its Zero, with the address set up gives it (a joined link has none)."""
    with teamlink.at(H["home"]):
        d = teamlink._load()
        d["links"][0]["url"] = f"127.0.0.1:{Z['lst'].port}"
        teamlink._save(d)
        return d["links"][0]


def test_a_link_says_its_version_and_the_hub_sees_who_is_behind(hz, monkeypatch):
    H, Z, loop = hz
    lk = _hub_link(H, Z)
    got = _on(H, loop, lambda: teamlink.call(lk, {"op": "hello"}, timeout=10))
    assert got["ok"] and got["version"] == __version__
    _on(H, loop, lambda: ties.probe([lk], force=True))
    with teamlink.at(H["home"]):
        t = next(x for x in ties.ties(None) if x["id"] == lk["id"])
    assert t["version"] == __version__ and not t["behind"], "the same version is not behind"
    assert ties.behind("0.6.1") and ties.behind("0.5.99") and not ties.behind("")
    assert not ties.behind("99.0.0")
    assert ties.behind(ties.OLDER), "a hello with no version is a Bento from before versions were said"


def test_only_its_own_hub_can_ask_and_an_older_zero_is_said_in_words(hz, monkeypatch):
    H, Z, loop = hz
    real_probe = ties.probe

    async def old_hello(lks, force=False, wait=ties.PROBE_TIMEOUT):
        await real_probe(lks, force=force, wait=wait)
        for lk_ in lks:
            ties._VERSION[lk_.get("id") or ""] = ties.OLDER    # a hello with no version: before 0.6.88
    monkeypatch.setattr(ties, "probe", old_hello)
    assert not _on(H, loop, lambda: ties.ask_update({"kind": "machine", "peer_host_fp": "nobody"}))["ok"]

    async def old_zero(lk, req):
        return {"ok": False, "error": f"unknown request '{req.get('op')}'"}
    Z["lst"].on_ask = old_zero
    lk = _hub_link(H, Z)
    got = _on(H, loop, lambda: ties.ask_update(lk))
    assert not got["ok"] and "Controls → Update" in got["error"]


def test_the_modes_and_the_doors():
    assert ties.update_mode({}) == "ask" and ties.update_mode({"provision": {"zero_updates": "auto"}}) == "auto"
    assert ties.update_mode({"provision": {"zero_updates": "nonsense"}}) == "ask"
    srv = (ROOT / "agentos/server.py").read_text()
    h = srv[srv.index("async def _zero_update_from_hub"):]
    h = h[:h.index("\nasync def ")]
    assert "is_my_hub" in h and "run_tests=False" in h, "only its own hub, and no test suite on a Pi"
    assert '"zero_update"' in (ROOT / "agentos/teamlink.py").read_text()
    js = (ROOT / "agentos/ui/src/js/24h-kiosk.js").read_text()
    assert "function kioskUpdate" in js and "/api/update" in js and "run_tests:false" in js
    ws = (ROOT / "agentos/ui/src/js/09-websocket.js").read_text()
    assert "case 'zero_behind'" in ws and "kioskUpdate" in ws
