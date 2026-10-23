"""Teams and Zeros in Network (agentos/ties.py, 24p-ties.js, the device map in 24o-devices.js).

Asked for as "in network we should not only show the devices that are zero connected but also
the teams connection", "the device map should show teams and zero as well, with indication and
management of both", "a filtered view of KB, memory, sessions and logs" for each, and "what
agents it has access to and what executors it can run on". Found on the owner's hub: every link
kept its address in `url` only, so the inventory (which read `host`) listed none of them, and
two links left by Pi reinstalls answered with a certificate nobody had any more."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import provision, teamlink, ties          # noqa: E402
from agentos.memory import Store                         # noqa: E402

ROOT = Path(__file__).parent.parent


def _links(tmp_path, monkeypatch, links, enabled=None):
    monkeypatch.setattr(teamlink, "home", lambda: tmp_path)
    (tmp_path / "links.json").write_text(json.dumps({"links": links}))
    monkeypatch.setattr(provision, "load", lambda: {"enabled": enabled or {}, "keys": [], "devices": {}})


def _lk(label, url, created, fp="fp", peer="raspberrypi", kind="machine", owner=""):
    return {"label": label, "url": url, "created": created, "peer_host_fp": fp, "peer_name": peer,
            "kind": kind, "owner": owner, "id": label + "-id", "peer_ca": "x"}


def test_an_address_is_read_from_url_when_there_is_no_host():
    assert ties.host_of({"url": "192.168.29.246:8322"}) == "192.168.29.246"
    assert ties.host_of({"url": "100.85.200.46:8322"}) == "100.85.200.46"
    assert ties.host_of({"host": "pi.local", "url": "x:1"}) == "pi.local"
    assert ties.host_of({"url": "[fd7a::1]:8322"}) == "fd7a::1"


def test_kinds_and_a_link_a_reinstall_left_behind(tmp_path, monkeypatch):
    _links(tmp_path, monkeypatch, [
        _lk("raspberrypi", "192.168.29.246:8322", 100, fp="old"),
        _lk("raspberrypi-3", "192.168.29.246:8322", 300, fp="new"),
        _lk("studio", "100.85.200.46:8322", 200, fp="mac", peer="studio"),
        {"label": "ada", "kind": "account", "owner": "", "id": "acc", "created": 50, "peer": "u1"},
    ], enabled={"new": {"execution": "hub", "label": "raspberrypi-3", "space": "s1"}})
    got = {t["label"]: t for t in ties.ties(None)}
    assert got["raspberrypi-3"]["kind"] == "zero" and not got["raspberrypi-3"]["stale"]
    assert got["raspberrypi"]["stale"], "a newer link to the same machine makes this one old"
    assert got["studio"]["kind"] == "team" and got["ada"]["kind"] == "account"
    assert got["raspberrypi-3"]["space"] == "s1"
    assert [t["label"] for t in ties.ties(None)][-1] == "raspberrypi", "old links last"


def test_the_inventory_lists_every_link(tmp_path, monkeypatch):
    from agentos import inventory, netscan  # noqa: F401
    _links(tmp_path, monkeypatch, [_lk("studio", "100.85.200.46:8322", 200, fp="mac", peer="studio")])
    monkeypatch.setattr(provision, "seen_list", lambda: [])
    monkeypatch.setattr(inventory, "load", lambda: {"devices": {}})
    rows = inventory.rows({})
    assert any(r.get("ip") == "100.85.200.46" and r["bento"] == "linked" for r in rows), rows


def test_a_ties_views_read_only_its_own_rows(tmp_path):
    st = Store(tmp_path / "a.db")
    sid = st.create_space("Zero · kitchen")
    other = st.create_space("Zero · garage")
    st.add_memory("kitchen: green tea", space_id=sid)
    st.add_memory("garage: the drill", space_id=other)
    st.add_memory("HUB-PRIVATE", space_id="")
    c = st.create_conversation("◫ kitchen: hi", origin="zero", space_id=sid)
    st.add_message(c, "user", "hi")
    st.create_conversation("someone else", space_id="")
    st.log("turn", "kitchen: hi", {"zero": "kitchen", "space_id": sid})
    st.log("turn", "something else", {})
    t = {"label": "kitchen", "kind": "zero", "space": sid}
    mem = [r["content"] for r in ties.view(st, t, "memory")["rows"]]
    assert mem == ["kitchen: green tea"], "exactly its section: no global, no other Zero"
    sess = ties.view(st, t, "sessions")["rows"]
    assert [s["title"] for s in sess] == ["◫ kitchen: hi"] and sess[0]["messages"] == 1
    logs = [r["text"] for r in ties.view(st, t, "logs")["rows"]]
    assert logs == ["kitchen: hi"]
    team = {"label": "studio", "kind": "team", "space": ""}
    assert ties.view(st, team, "memory")["note"], "a team keeps its memory on its own machine"
    with pytest.raises(ValueError):
        ties.view(st, t, "secrets")


def test_the_brain_a_tie_runs_on_and_adopting_one(tmp_path, monkeypatch):
    _links(tmp_path, monkeypatch, [_lk("pi", "1.2.3.4:8322", 1, fp="z")],
           enabled={"z": {"execution": "hub", "label": "pi", "space": "s"}})
    saved = {}
    monkeypatch.setattr(provision, "save", lambda d: saved.update(d))
    got = ties.set_brain("", "pi", "aria", "ollama/qwen3.5:9b")
    assert got == {"executor": "aria", "model": "ollama/qwen3.5:9b"}
    eng, model, cfg = ties.brain_for({"default_model": "openai/x", "providers": {}}, teamlink._load()["links"][0])
    assert (eng, model, cfg["default_model"]) == ("aria", "ollama/qwen3.5:9b", "ollama/qwen3.5:9b")
    with pytest.raises(ValueError):
        ties.set_brain("", "pi", "made-up-cli", "")
    assert ties.set_brain("", "pi", "", "") == {"executor": "", "model": ""}
    out = ties.adopt("pi", "u1")
    assert out["owner"] == "u1" and teamlink._load()["links"][0]["owner"] == "u1"
    assert saved["enabled"]["z"]["owner"] == "u1" and "space" not in saved["enabled"]["z"]
    with pytest.raises(LookupError):
        ties.adopt("pi", "u2"), "only a link the MACHINE owns can be adopted"


def test_routes_are_admin_and_the_page_draws_both_kinds():
    srv = (ROOT / "agentos/server.py").read_text()
    for r in ('@app.get("/api/network/ties")', '@app.put("/api/network/ties/{label}/brain")',
              '@app.post("/api/network/ties/{label}/adopt")', '@app.delete("/api/network/ties/{label}")',
              '@app.get("/api/network/ties/{label}/view")', '@app.put("/api/network/ties/{label}/access")'):
        body = srv[srv.index(r):]
        body = body[:body.index("\n@app.")]
        assert "_require_admin()" in body, r
    js = (ROOT / "agentos/ui/src/js/24o-devices.js").read_text() + (ROOT / "agentos/ui/src/js/24s-zmap.js").read_text()
    assert "t.kind==='zero'" in js and "'Zero':'Team'" in js and "devMapPulse" in js
    ws = (ROOT / "agentos/ui/src/js/09-websocket.js").read_text()
    assert "case 'zero_work'" in ws and "officeZero" in ws


def test_the_office_repaints_its_rooms_when_the_gpu_drops_the_canvas():
    js = (ROOT / "agentos/ui/src/js/24d-office.js").read_text()
    assert "contextrestored" in js and "officeBgGone()" in js[js.index("function officeDraw"):]
