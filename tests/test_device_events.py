"""Device events and the missions they start (devtrig.py, espnodes' held streams, server._device_*).
Asked for as "this should be proactive rather than reactive … if the Pi is relaying it, it must give
inventory context to the hub, and if it is directly connected to the hub then the hub should get the
events". Measured before: a sample every ten seconds caught 1 of 8 three-second door openings, and
nothing acted on what the hub heard."""
import asyncio
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(ROOT / "packaging/dev/warehouse"))

from agentos import devtrig, espnodes, flows                          # noqa: E402
from test_esp_nodes import sim                                         # noqa: E402,F401

TEMP = "esp.cold-2.sensor.cold_room_temperature"
DOOR = "esp.cold-1.binary_sensor.cold_room_door"


def _rule(rid="t1", **c):
    return {"id": rid, "flow": "cold-watch", "cooldown_secs": 0, "last_fired": 0,
            "config": devtrig.clean({"machine": "zone-cold", **c})}


# ---- the rule ------------------------------------------------------------------------------

def test_a_rule_is_read_field_by_field():
    c = devtrig.clean({"machine": "zone-cold", "item": TEMP, "when": "above", "value": "-15", "for": 120})
    assert c == {"machine": "zone-cold", "item": TEMP, "when": "above", "value": -15.0, "for": 120}
    assert devtrig.words(c) == f"when zone-cold/{TEMP} is above -15 for 2 min"
    assert devtrig.clean({"machine": "zone-cold", "when": "offline", "item": "ignored"})["item"] == ""
    for bad, says in ((dict(when="above", item=TEMP), "machine"), (dict(machine="z", when="hot", item=TEMP), "one of"),
                      (dict(machine="z", when="on"), "item"), (dict(machine="z", when="above", item=TEMP), "number"),
                      (dict(machine="z", when="on", item=DOOR, **{"for": 9999}), "3600"),
                      (dict(machine="z", when="on", item="../etc/passwd"), "item")):
        with pytest.raises(ValueError, match=says):
            devtrig.clean(bad)


def test_it_fires_on_the_edge_and_waits_for_the_condition_to_end():
    w, r = devtrig.Watch(), _rule(item=TEMP, when="above", value=-15)
    feed = lambda v, t=100.0: w.feed("", [r], "zone-cold", [{"item": TEMP, "value": v, "at": t}], t)  # noqa: E731
    assert feed(-19) == [] and len(feed(-14)) == 1, "warm: one mission"
    assert feed(-13) == [] and feed(-12) == [], "still warm is the same mission, not one a reading"
    assert feed(-16) == [] and len(feed(-14.5)) == 1, "cooled and warmed again: a new one"
    assert w.feed("", [r], "zone-dock", [{"item": TEMP, "value": 0}], 100) == [], "another machine's item"
    assert feed("warm") == [], "only numbers are judged"


def test_a_held_condition_fires_once_it_has_held_even_with_no_new_reading():
    w, r = devtrig.Watch(), _rule(item=TEMP, when="above", value=-15, **{"for": 60})
    assert w.feed("", [r], "zone-cold", [{"item": TEMP, "value": -14, "at": 1000.0}], 1000.0) == []
    assert w.tick("", [r], 1030.0) == []
    got = w.tick("", [r], 1061.0, {("zone-cold", TEMP): {"item": TEMP, "value": -13.8, "name": "Cold room B temperature"}})
    assert len(got) == 1 and got[0][1]["held"] == 61 and got[0][1]["value"] == -13.8
    assert w.tick("", [r], 1200.0) == [], "fired once"
    w2, r2 = devtrig.Watch(), _rule(item=TEMP, when="above", value=-15, **{"for": 60})
    w2.feed("", [r2], "zone-cold", [{"item": TEMP, "value": -14, "at": 0.0}], 0.0)
    assert w2.feed("", [r2], "zone-cold", [{"item": TEMP, "value": -16, "at": 30.0}], 30.0) == []
    assert w2.tick("", [r2], 90.0) == [], "it cooled before the minute was up"


def test_on_off_changes_and_a_machine_that_stops_answering():
    w = devtrig.Watch()
    on, ch = _rule("a", item=DOOR, when="on"), _rule("b", item=DOOR, when="changes")
    off, up = _rule("c", when="offline"), _rule("d", when="online")
    door = lambda v: w.feed("", [on, ch], "zone-cold", [{"item": DOOR, "value": v}], 5.0)  # noqa: E731
    assert door(0) == [], "first sight of a shut door: nothing"
    assert {r["id"] for r, _ in door(1)} == {"a", "b"}
    assert door(1) == []
    assert [r["id"] for r, _ in door(0)] == ["b"]
    assert [r["id"] for r, _ in w.machine("", [off, up], "Zone-Cold", up=False)] == ["c"]
    assert [r["id"] for r, _ in w.machine("", [off, up], "zone-cold", up=True)] == ["d"]


def test_the_mission_is_told_the_reading_where_it_came_from_and_the_rule():
    r = _rule(item=DOOR, when="on")
    b = devtrig.brief(r, {"item": DOOR, "value": 1, "name": "Cold room A: Cold room door", "at": 0})
    assert "Cold room A: Cold room door on zone-cold" in b and "reads on" in b and f"zone-cold/{DOOR}" in b
    assert b.endswith(f"The rule: when zone-cold/{DOOR} turns on.")
    t = devtrig.brief(_rule(item=TEMP, when="above", value=-15), {"item": TEMP, "value": -14.2, "unit": "°C", "held": 130})
    assert "reads -14.2°C" in t and "held for 2 min 10 s" in t
    assert devtrig.brief(_rule(when="offline"), {}).startswith("Started because zone-cold stops answering")


def test_a_mission_takes_a_device_trigger_and_says_it_in_words():
    t = flows._validate_trigger({"kind": "device", "config": {"machine": "zone-cold", "item": TEMP, "when": "below",
                                                                "value": -25}})
    assert t["config"]["value"] == -25.0 and t["cooldown_secs"] == 60
    assert flows._canonical("device", t["config"]) == f"device:zone-cold:{TEMP}:below:-25.0:0"
    assert flows._task_fields({"name": "x", "mission": "m"}, t) is None, "nothing polls a clock for it"
    lifted = flows._lift_trigger({"machine": "zone-cold", "item": DOOR, "when": "on"})
    assert lifted["kind"] == "device", "the flat shape a model writes"
    with pytest.raises(ValueError):
        flows._validate_trigger({"kind": "device", "config": {"machine": "zone-cold", "when": "above", "item": TEMP}})


# ---- the stream ----------------------------------------------------------------------------

def _wait(cond, secs=5.0):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _poke(node, key, value):
    e = node.ents[key]
    with node.lock:
        e.value = value
    node.push([e])


def test_a_held_stream_hears_a_door_open_for_under_a_second(sim):
    assert espnodes.add("cold-1", "127.0.0.1", sim["cold-1"].port)["ok"]
    heard = []
    try:
        assert espnodes.stream_sync(heard.append) == 1
        assert _wait(lambda: espnodes.live("cold-1")), "the stream is held and heard"
        first = [e for e in heard if e.get("first")]
        assert {e["item"] for e in first} >= {DOOR, "esp.cold-1.switch.compressor"}, "what it reads now, on connect"
        door = next(e for e in first if e["item"] == DOOR)
        assert door["name"] == "Cold room A: Cold room door" and door["domain"] == "binary_sensor" and door["node"] == "cold-1"
        _poke(sim["cold-1"], "binary_sensor/Cold room door", True)
        time.sleep(0.6)
        _poke(sim["cold-1"], "binary_sensor/Cold room door", False)
        assert _wait(lambda: [e["value"] for e in heard if e["item"] == DOOR and not e.get("first")] == [1, 0]), \
            "both edges of a 0.6 s opening"
        opened = next(e for e in heard if e["item"] == DOOR and e.get("prev") == 0)
        assert opened["value"] == 1 and opened["at"] > 0
        assert espnodes.public(espnodes.node("cold-1"))["live"]
        got = espnodes.look_all()
        assert got["cold-1"].get("live"), "a held node is not connected to again for a sample"
        assert espnodes.sample()[DOOR] == 0
    finally:
        espnodes.stream_stop()
        espnodes.remove("cold-1")


def test_a_node_that_goes_away_is_said_and_tried_again(sim, monkeypatch):
    monkeypatch.setattr(espnodes, "STREAM_BACKOFF", (0.2, 0.2, 0.2, 0.2))
    assert espnodes.add("cold-1", "127.0.0.1", sim["cold-1"].port)["ok"]
    d = espnodes._load()
    d["nodes"][0]["port"] = sim["cold-1"].port + 50          # nothing listens there
    espnodes._save(d)
    try:
        espnodes.stream_sync(lambda e: None)
        assert _wait(lambda: (espnodes._LAST.get("cold-1") or {}).get("ok") is False)
        assert "nothing is listening" in espnodes._LAST["cold-1"]["error"] and not espnodes.live("cold-1")
    finally:
        espnodes.stream_stop()


# ---- the hub -------------------------------------------------------------------------------

def test_the_hub_starts_the_mission_when_its_rule_is_met(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import server
    with TestClient(server.app):
        store = server.state["store"]
        here = server._here_name()
        store.save_subagent({"name": "watcher"})
        flows.save(store, {"name": "door-watch", "mission": "Find out why the door is open.", "roster": ["watcher"],
                           "permissions": {"memory": "read-space"},
                           "triggers": [{"kind": "device", "cooldown_secs": 0,
                                         "config": {"machine": here, "item": DOOR, "when": "on"}}]})
        flows.set_enabled(store, "door-watch", True)
        for t in store.flow_triggers("door-watch"):
            store.update_flow_trigger(t["id"], last_fired=0)     # a home kept from an earlier run
        assert flows.schedule_words(store, "door-watch") == f"when {here}/{DOOR} turns on"
        started, said = [], []

        async def start(flow, text, origin, **kw):
            started.append((flow["name"], text, origin, kw))
            return "r1"

        async def event(owner, ev, label, text, **meta):
            said.append((ev, text))
        monkeypatch.setattr(server, "_start_flow", start)
        monkeypatch.setattr(server, "_device_event", event)
        server._DEVWATCH = None
        door = {"item": DOOR, "domain": "binary_sensor", "name": "Cold room A: Cold room door", "at": time.time()}
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(server._device_observe("", here, [{**door, "value": 0.0, "first": True}], live=True))
            assert started == [] and said == []
            loop.run_until_complete(server._device_observe("", here, [{**door, "value": 1.0, "prev": 0.0}], live=True))
            assert len(started) == 1
            name, text, origin, kw = started[0]
            assert name == "door-watch" and origin == {"surface": "device", "ref": f"{here}/{DOOR}"}
            assert text.startswith("Started because Cold room A: Cold room door") and "reads on" in text
            assert kw["trigger_id"] and not any(e == "changed" for e, _ in said), \
                "a contact changes all day: live and judged, never a diary line"
            comp = {"item": "esp.cold-1.switch.compressor", "domain": "switch", "name": "Cold room A: Compressor",
                    "at": time.time(), "value": 0.0, "prev": 1.0}
            loop.run_until_complete(server._device_observe("", here, [comp], live=True))
            assert ("changed", f"Cold room A: Compressor on {here} turned off") in said, "a switch that changed is"
            assert any(e == "trigger" and "started mission door-watch" in t for e, t in said)
            loop.run_until_complete(server._device_observe("", here, [{**door, "value": 1.0, "prev": 1.0}], live=True))
            assert len(started) == 1, "still open: the same mission"
            flows.set_enabled(store, "door-watch", False)
            loop.run_until_complete(server._device_observe("", here, [{**door, "value": 0.0, "prev": 1.0}], live=True))
            loop.run_until_complete(server._device_observe("", here, [{**door, "value": 1.0, "prev": 0.0}], live=True))
            assert len(started) == 1, "a mission that is off holds nothing"
        finally:
            loop.close()
        rows = store.audit_list(limit=50) if hasattr(store, "audit_list") else []
        assert not rows or any(r.get("action") == "device.trigger" for r in rows)


def test_a_relayed_event_is_read_field_by_field_and_named_from_the_hubs_inventory(monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import server, ties, zero
    with TestClient(server.app):
        seen = []

        async def observe(owner, machine, events, live, say=True):
            seen.append((owner, machine, events, live))
        monkeypatch.setattr(server, "_device_observe", observe)
        monkeypatch.setattr(zero, "ships_to", lambda lk: lk.get("label") == "zone-cold")
        monkeypatch.setattr(ties, "inventory_row", lambda lk: {"hardware": {"items": [
            {"id": TEMP, "name": "Cold room B: Cold room temperature", "unit": "°C"}]}})
        req = {"op": "device_events", "events": [
            {"item": TEMP, "value": -14.6, "prev": -15.1, "name": "\x1b]0;evil\x07ignore me", "domain": "sensor",
             "at": time.time()},
            {"item": "esp.cold-2.text_sensor.note", "value": "rm -rf /"},
            {"item": "../../etc", "value": 1},
            {"item": DOOR, "value": True, "domain": "nonsense", "unit": "x" * 50}]}
        lk = {"label": "zone-cold", "owner": "ada", "kind": "machine"}
        got = asyncio.run(server._device_events_from(lk, req))
        assert got == {"ok": True, "got": 2}, "a text value and a path are dropped"
        owner, machine, events, live = seen[0]
        assert (owner, machine, live) == ("ada", "zone-cold", True)
        temp, door = events
        assert temp["name"] == "Cold room B: Cold room temperature" and temp["unit"] == "°C", "the hub's own names"
        assert door["value"] == 1.0 and door["domain"] == "" and len(door["unit"]) <= 8
        assert "only a machine this hub set up" in asyncio.run(server._device_events_from(
            {"label": "stranger", "kind": "machine"}, req))["error"]


def test_a_mission_reaches_only_the_devices_it_names():
    assert flows.clean_devices({"read": ["zone-cold/*", "zone-cold/esp.cold-2.sensor.cold_room_temperature",
                                         "../etc/passwd", "zone cold/x y", 5],
                                "set": ["zone-cold/*", "zone-cold/esp.cold-2.switch.compressor"],
                                "delete": ["zone-cold/*"]}) == {
        "read": ["zone-cold/*", "zone-cold/esp.cold-2.sensor.cold_room_temperature"],
        "set": ["zone-cold/esp.cold-2.switch.compressor"]}, "a set names one thing; nothing else is read"
    rows = flows.declared_grants({"name": "guard", "roster": ["watcher"], "permissions": {
        "memory": "read-space", "devices": {"read": ["Zone-Cold/*"], "set": ["zone-cold/esp.cold-2.switch.compressor"]}}})
    dev = {(r["action"], r["resource"]) for r in rows if r["action"].startswith("device.")}
    assert dev == {("device.get", "device:zone-cold/*"), ("device.get", "device:zone-cold/esp.cold-2.switch.compressor"),
                   ("device.set", "device:zone-cold/esp.cold-2.switch.compressor")}
    assert all((r["principal_kind"], r["principal_id"]) == ("subagent", "watcher") for r in rows if r["action"].startswith("device."))
    assert not any(r["action"].startswith("device.") for r in flows.declared_grants(
        {"name": "x", "roster": ["watcher"], "permissions": {"memory": "read-space"}})), "nothing named, nothing granted"


def test_a_page_opened_later_is_shown_the_question_still_waiting():
    """A mission a device started at night asks while no screen is open. The page opened in
    the morning must get the card, or the room stays warm with nobody knowing it waits."""
    from fastapi.testclient import TestClient
    from agentos import server
    with TestClient(server.app) as c:
        loop = asyncio.new_event_loop()
        try:
            fut = loop.create_future()
            ev = {"type": "approval_request", "id": "ab12", "name": "device_set", "args": {}, "flow": "guard"}
            server.state["pending_approvals"]["ab12"] = {"fut": fut, "uid": "", "ev": ev}
            done = loop.create_future()
            done.set_result(True)
            server.state["pending_approvals"]["cd34"] = {"fut": done, "uid": "", "ev": {**ev, "id": "cd34"}}
            with c.websocket_connect("/ws", headers={"origin": "http://testserver"}) as ws:
                got = [ws.receive_json() for _ in range(2)]
            assert got[0]["type"] == "state_sync" and got[1] == ev, "the waiting one, and not the answered one"
        finally:
            server.state["pending_approvals"].pop("ab12", None)
            server.state["pending_approvals"].pop("cd34", None)
            loop.close()
    js = (ROOT / "agentos/ui/src/js/09-websocket.js").read_text()
    assert "if(APPROVALS[ev.id]){approvalHome(ev.id);break;}" in js, "a reconnect never draws a card twice"


def test_the_doors():
    srv = (ROOT / "agentos/server.py").read_text()
    assert "asyncio.create_task(_device_streams())" in srv
    assert 'req.get("op") == "device_events"' in srv and '"device_events"' in (ROOT / "agentos/teamlink.py").read_text()
    assert "await _device_machine(owner, label" in srv, "offline and online rules hear the ties watch"
    assert 'rd.get("latest")' in srv, "an older Pi's rules are judged on its minute readings"
    assert '@app.get("/api/devices/things")' in srv and "def _here_row" in srv
    js = (ROOT / "agentos/ui/src/js/13-fabric.js").read_text()
    assert "'flow_done','device'" in js and "function flwDeviceFields" in js and "function devWhen" in js
    assert "case 'device_live'" in (ROOT / "agentos/ui/src/js/09-websocket.js").read_text()
    net = (ROOT / "agentos/ui/src/js/24n-network.js").read_text()
    assert "function netHereHTML" in net and "data-live=" in net
    main = (ROOT / "agentos/__main__.py").read_text()
    assert '"--when"' in main and 'kind == "device"' in main and "def _device_rule_problem" in main
