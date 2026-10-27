"""A machine whose address changed, what happened to the machines, and the logs nobody saw.

Reported from a hub and its Pi on one home network: "the Pi's IP can change time and again, we
should work on DHCP", "in the devices section we need events", "the system logs I am not able
to see", and "when the Pi updates, the hub should refresh the session on it: the browser says
not reachable and doesn't refresh". What these defend:

  * a pinned machine heard from a new address is followed there; one that stopped answering is
    found where it is now; a certificate that isn't the pinned one is never used, wherever it is;
  * a name is never rewritten, and a real address never becomes a loopback one;
  * the minute watch says moved / stopped answering / answering again / updated, and refreshes
    a Zero's screen when it comes back on a new version;
  * Devices → Events reads the machine's diary and ledger together, for one machine or all;
  * an admin's Logs show the machine's own diary, and a non-admin's only their own;
  * the page reloads only once its server answers again.
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import teamlink                                           # noqa: E402
from agentos import users as usersmod                                  # noqa: E402
from agentos.memory import Store                                       # noqa: E402

ROOT = Path(__file__).parent.parent


@pytest.fixture()
def pair(tmp_path):
    """Two machines on loopback, linked through a real invite. Listening on 127.0.0.1 only, so
    127.0.0.2 is an address where nothing answers: where a Pi was before DHCP moved it."""
    a, b = tmp_path / "hub", tmp_path / "pi"

    async def setup():
        with teamlink.at(a):
            la = teamlink.Listener({"team": {"machine_name": "hub"}})
            pa = await la.start("127.0.0.1", 0)
            inv = teamlink.invite("", "machine", address="127.0.0.1", port=pa, cfg={"team": {"machine_name": "hub"}})
        with teamlink.at(b):
            lb = teamlink.Listener({"team": {"machine_name": "pi"}})
            pb = await lb.start("127.0.0.1", 0)
            await teamlink.join(inv["invite"], "", cfg={"team": {"machine_name": "pi"}}, my_port=pb)
        return la, lb, pa, pb
    loop = asyncio.new_event_loop()
    la, lb, pa, pb = loop.run_until_complete(setup())
    teamlink._RELOCATING.clear()
    yield {"a": a, "b": b, "pa": pa, "pb": pb, "loop": loop}
    for x in (la, lb):
        loop.run_until_complete(x.stop())
    loop.close()


def _set(home, label, **kv):
    with teamlink.at(home):
        d = teamlink._load()
        for lk in d["links"]:
            if lk["label"] == label:
                lk.update(kv)
        teamlink._save(d)


def _get(home, label):
    with teamlink.at(home):
        return teamlink.find("", label)


def test_a_machine_heard_from_a_new_address_is_followed_there(pair, monkeypatch):
    moved = []

    async def on_moved(lk, old, new, how):
        moved.append((lk["label"], old, new, how))
    monkeypatch.setattr(teamlink, "ON_MOVED", on_moved)
    _set(pair["a"], "pi", url=f"127.0.0.2:{pair['pb']}")      # the hub still has the old address

    async def go():
        with teamlink.at(pair["b"]):
            got = await teamlink.call(_get(pair["b"], "hub"), {"op": "hello"})   # the Pi's minute hello
        await asyncio.sleep(0.05)
        return got
    assert pair["loop"].run_until_complete(go())["ok"]
    lk = _get(pair["a"], "pi")
    assert lk["url"] == f"127.0.0.1:{pair['pb']}", "the hub follows the address its Pi connected from"
    assert lk["seen_from"] == "127.0.0.1"
    assert lk["moved"][-1]["from"] == "127.0.0.2" and lk["moved"][-1]["how"] == "heard"
    assert moved == [("pi", "127.0.0.2", "127.0.0.1", "heard")], "every move is said, once"

    async def back():
        with teamlink.at(pair["a"]):
            return await teamlink.call(_get(pair["a"], "pi"), {"op": "hello"})
    assert pair["loop"].run_until_complete(back())["ok"], "and the hub reaches it there"


def test_a_machine_that_stopped_answering_is_found_where_it_is_now(pair, monkeypatch):
    monkeypatch.setattr(teamlink, "ON_MOVED", None)
    _set(pair["a"], "pi", url=f"127.0.0.2:{pair['pb']}", seen_from="127.0.0.1")

    async def go():
        with teamlink.at(pair["a"]):
            return await teamlink.call(_get(pair["a"], "pi"), {"op": "hello"})
    got = pair["loop"].run_until_complete(go())
    assert got["ok"] and got["name"] == "pi", got
    assert _get(pair["a"], "pi")["url"] == f"127.0.0.1:{pair['pb']}", "the link is moved to where it answered"


def test_another_certificate_at_the_new_address_is_never_used(pair, monkeypatch):
    monkeypatch.setattr(teamlink, "ON_MOVED", None)
    # the candidate address holds a Bento, but the hub itself, not the pinned Pi
    _set(pair["a"], "pi", url=f"127.0.0.2:{pair['pa']}", seen_from="127.0.0.1")

    async def go():
        with teamlink.at(pair["a"]):
            return await teamlink.call(_get(pair["a"], "pi"), {"op": "hello"})
    got = pair["loop"].run_until_complete(go())
    assert not got["ok"] and "could not reach" in got["error"]
    assert _get(pair["a"], "pi")["url"] == f"127.0.0.2:{pair['pa']}", "a certificate that isn't the pinned one moves nothing"


def test_a_name_is_never_rewritten_and_a_real_address_never_becomes_loopback(tmp_path):
    home = tmp_path / "h"
    with teamlink.at(home):
        d = teamlink._load()
        d["links"] = [{"id": "n1", "kind": "machine", "label": "pi", "url": "pi.local:8622", "peer_host_fp": "f1"},
                      {"id": "n2", "kind": "machine", "label": "pi2", "url": "192.168.1.20:8622", "peer_host_fp": "f2"},
                      {"id": "n3", "kind": "machine", "label": "pi3", "url": "192.168.1.30:8622", "peer_host_fp": "f3",
                       "host": "192.168.1.30"}]
        teamlink._save(d)
        assert teamlink.note_seen("f1", "192.168.1.9") is None, "a name follows its machine through DNS"
        assert teamlink.find("", "pi")["seen_from"] == "192.168.1.9", "where it came from is still kept"
        assert teamlink.note_seen("f2", "127.0.0.1") is None
        assert teamlink.find("", "pi2")["url"] == "192.168.1.20:8622"
        view, old = teamlink.note_seen("f3", "192.168.1.31")
        assert old == "192.168.1.30" and view["url"] == "192.168.1.31:8622" and view["host"] == "192.168.1.31", \
            "ties.host_of reads `host` first, so it moves with the url"
        assert teamlink.note_seen("nobody", "192.168.1.5") is None


def test_the_watch_says_what_changed_and_refreshes_a_zero_back_on_a_new_version(monkeypatch):
    from agentos import server as servermod
    from agentos import ties as tiesmod
    from agentos import zero as zeromod
    lk = {"id": "z1", "kind": "machine", "label": "pi", "url": "192.168.1.20:8622", "owner": ""}
    monkeypatch.setattr(teamlink, "_load", lambda: {"links": [lk], "invites": [], "requests": []})
    monkeypatch.setattr(zeromod, "ships_to", lambda x: True)
    monkeypatch.setattr(tiesmod, "hardware_due", lambda x: "")   # its hardware: test_pi_hardware.py
    said, calls = [], []

    async def dev_event(owner, event, label, text, **meta):
        said.append((event, text))
    monkeypatch.setattr(servermod, "_device_event", dev_event)

    async def call(lk_, req, **kw):
        calls.append(req["op"])
        return {"ok": True, "said": "the page reloaded"}
    monkeypatch.setattr(teamlink, "call", call)
    answers = iter([(True, "0.6.91"), (False, ""), (False, ""), (True, "0.6.92")])

    async def probe(lks, force=False, wait=0):
        assert wait >= 30, "the watch gives a moved machine time to be looked for"
        ok, v = next(answers)
        tiesmod._PROBED["z1"] = (0, ok, "" if ok else "no answer in time")
        if ok:
            tiesmod._VERSION["z1"] = v
    monkeypatch.setattr(tiesmod, "probe", probe)
    for d in (servermod._TIE_UP, servermod._TIE_MISS):
        d.pop("z1", None)
    tiesmod._VERSION.pop("z1", None)
    loop = asyncio.new_event_loop()
    rounds = [loop.run_until_complete(servermod._ties_check()) for _ in range(4)]
    loop.close()
    assert rounds[0] == [], "the first look is where it is, not news"
    assert rounds[1] == [], "one miss is a Wi-Fi blink"
    assert [e["event"] for e in rounds[2]] == ["offline"]
    assert [e["event"] for e in rounds[3]] == ["online", "updated", "refreshed"]
    assert calls == ["zero_refresh"], "back on a new version, its screen is refreshed from here"
    assert any("is on 0.6.92 now (was 0.6.91)" in t for _, t in said)


def test_events_read_the_machines_diary_and_ledger_for_one_machine_or_all(tmp_path):
    from agentos import devevents
    st = Store(tmp_path / "m.db")
    st.log("device", "pi moved from 192.168.1.20 to 192.168.1.31 (it connected from there)",
           {"event": "moved", "link": "pi"})
    st.audit_add(principal_kind="system", principal_id="provision", action="device.moved", resource="link:pi",
                 effect="allow", rule="person", outcome="ok", detail="pi moved (the ledger's copy)")
    st.audit_add(principal_kind="user", principal_id="", action="device.installed", resource="device:192.168.1.40",
                 effect="allow", rule="person", outcome="ok", detail="Bento installed on kitchen")
    st.audit_add(principal_kind="user", principal_id="", action="grant.write", resource="tool:x",
                 effect="allow", rule="person", outcome="ok", detail="not about a machine")
    every = devevents.gather([st, None])
    assert [e["event"] for e in every] == ["installed", "moved"], "the watch's line, not the ledger's copy twice"
    assert [e["label"] for e in devevents.gather([st], who="192.168.1.40")] == ["192.168.1.40"]
    assert [e["event"] for e in devevents.gather([st], who="pi")] == ["moved"]
    assert "Nothing has happened" in devevents.text([])


def test_an_admins_logs_show_the_machines_own_diary(tmp_path):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    usersmod.create("ada", "ada-password-1", role="admin")
    usersmod.create("bob", "bob-password-1")
    with TestClient(servermod.app) as cl:
        with usersmod.as_user(""):
            servermod.state["store"].log("provision", "MACHINE-LINE heard a Pi waiting")
        assert cl.post("/api/users/login", json={"name": "ada", "password": "ada-password-1"}).status_code == 200
        d = cl.get("/api/logs?q=MACHINE-LINE").json()
        assert [r["where"] for r in d["logs"]] == ["machine"], "an admin reads the machine's diary"
        assert [x["id"] for x in d["sources"]] == ["mine", "machine", "service"]
        assert cl.get("/api/logs?q=MACHINE-LINE&source=mine").json()["logs"] == []
        cl.post("/api/users/logout")
        assert cl.post("/api/users/login", json={"name": "bob", "password": "bob-password-1"}).status_code == 200
        d = cl.get("/api/logs?q=MACHINE-LINE&source=machine").json()
        assert d["logs"] == [] and [x["id"] for x in d["sources"]] == ["mine"], "anyone else reads their own"
        assert cl.get("/api/network/events").status_code == 403


def test_the_page_reloads_only_once_its_server_answers():
    js = (ROOT / "agentos/ui/src/js/09-websocket.js").read_text()
    assert "case 'reload': reloadWhenUp(" in js
    assert "setTimeout(()=>location.reload(),ev.delay" not in js, \
        "a reload while the server is down is the browser's own error page, where nothing of ours runs"
    assert "if(!live)location.reload()" not in js
    init = (ROOT / "agentos/ui/src/js/30-init.js").read_text()
    assert "KIOSK.on)return location.reload()" in init, "a kiosk takes the new page itself"


def test_a_screen_left_on_the_error_page_is_started_again(monkeypatch):
    from agentos import screen
    killed = []
    monkeypatch.setattr(screen, "showing", lambda: [] if killed else [42])
    monkeypatch.setattr(screen, "close_now", lambda: killed.append(42) or 1)
    monkeypatch.setattr(screen, "road", lambda: ("console", ""))
    assert screen.restart_now({}, wait=0.1) == "started the screen's browser again"
    assert killed
    monkeypatch.setattr(screen, "close_now", lambda: 0)
    assert "no browser" in screen.restart_now({}, wait=0.1)
