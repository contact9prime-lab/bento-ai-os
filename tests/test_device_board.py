"""The device board and its alarms (devboard.py, server._alarms_judge, /api/devices/board), and the
Devices scene that draws them on its own desktop (01h-devscene.js, 01b immersiveSceneOf). Asked for
as "the device screen should be there on the hub, so I can see all the devices in real time along
with alarms … like a device hub instead of the town, and the desktops could be used to switch"."""
import asyncio
import re
import time
from pathlib import Path

import pytest

from agentos import devboard

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"
TEMP = "esp.cold-1.sensor.cold_room_temperature"
DOOR = "esp.cold-1.binary_sensor.cold_room_door"
COMP = "esp.cold-2.switch.compressor"


def _r(**c):
    k = devboard.clean_rule({"machine": "zone-cold", **c})
    return {"id": k["id"], "config": k, "level": k["level"], "source": "alarm"}


def _ev(item, value, at, name=""):
    return {"item": item, "value": value, "at": at, "name": name or item, "machine": "zone-cold"}


# ---- the rule ------------------------------------------------------------------------------

def test_an_alarm_rule_is_a_state_read_field_by_field():
    a = devboard.clean_rule({"machine": "zone-cold", "item": TEMP, "when": "above", "value": "-15", "for": 20})
    assert a["level"] == "alarm" and a["value"] == -15.0 and a["id"].startswith("a")
    assert a["id"] == devboard.clean_rule({**a, "level": "warning"})["id"], "the id is the condition, not its level"
    for bad, says in (({"when": "changes", "item": DOOR}, "stays true"), ({"when": "online"}, "stays true"),
                      ({"when": "on", "item": DOOR, "level": "panic"}, "alarm or warning"),
                      ({"when": "above", "item": TEMP}, "number")):
        with pytest.raises(ValueError, match=says):
            devboard.clean_rule({"machine": "zone-cold", **bad})
    kept, dropped = devboard.clean_rules([{"machine": "zone-cold", "item": DOOR, "when": "on"}] * 2
                                         + [{"machine": "zone-cold", "when": "hot"}, "nonsense"])
    assert len(kept) == 1 and len(dropped) == 2


def test_the_demo_alarms_name_things_its_simulation_has():
    from agentos.demos import esp_sim, warehouse
    kept, dropped = devboard.clean_rules(warehouse.ALARMS)
    assert not dropped and len(kept) == len(warehouse.ALARMS)
    have = set()
    for n in esp_sim.build("warehouse", 30000):
        for e in n.ents.values():
            have.add(f"esp.{n.host_name}.{e.domain}.{e.object_id}")
    for a in kept:
        assert a["item"] in have, a["item"]
    # every way to cause trouble on the floor page raises one
    floor = (ROOT / "agentos/demos/floor.html").read_text()
    for node, ent in re.findall(r"\['([a-z0-9-]+)','([^']+)',", floor):
        oid = "".join(c if c.isalnum() else "_" for c in ent.lower())
        assert any(a["item"].startswith(f"esp.{node}.") and a["item"].endswith("." + oid) for a in kept) \
            or (node, ent) == ("cold-2", "Compressor") and any(a["item"] == COMP for a in kept), (node, ent)


# ---- the judge -----------------------------------------------------------------------------

def test_an_alarm_holds_for_its_time_then_is_raised_once_and_clears_by_itself():
    al, r = devboard.Alarms(), _r(item=TEMP, when="above", value=-15, **{"for": 20})
    names = {("zone-cold", TEMP): ("Cold room A: Cold room temperature", "°C"), ("zone-cold", ""): ("zone-cold", "")}
    judge = lambda v, at, now: al.judge("", [r], {("zone-cold", TEMP): _ev(TEMP, v, at)}, {"zone-cold": True},  # noqa: E731
                                        names, now)
    out, raised, cleared = judge(-19, 100, 100)
    assert out == [] and raised == []
    out, raised, _ = judge(-14, 110, 110)
    assert len(out) == 1 and out[0]["state"] == "pending" and raised == [], "warm for 0 s of 20"
    out, raised, _ = judge(-13.5, 125, 131)
    assert out[0]["state"] == "active" and len(raised) == 1 and out[0]["held"] == 21
    assert raised[0]["text"] == "Cold room A: Cold room temperature is above -15°C"
    out, raised, _ = judge(-13, 140, 140)
    assert raised == [], "still warm: the same alarm, not a new one"
    assert al.ack("", out[0]["id"], "Ada", 141)["ack"]["by"] == "Ada"
    assert judge(-13, 150, 150)[0][0]["ack"]["by"] == "Ada"
    out, raised, cleared = judge(-17, 160, 160)
    assert out == [] and len(cleared) == 1
    assert al.ack("", cleared[0]["id"], "Ada") is None, "only a raised alarm is acknowledged"
    judge(-14, 170, 170)
    out, raised, _ = judge(-14, 170, 191)
    assert len(raised) == 1 and out[0]["ack"] is None, "raised again is a new alarm: the old mark went with it"


def test_a_machine_not_answering_and_a_sensor_with_no_number_are_alarms_with_no_rule():
    al = devboard.Alarms()
    last = {("zone-cold", TEMP): _ev(TEMP, None, 5)}
    out, raised, _ = al.judge("", [], last, {"zone-cold": True, "zone-dock": False},
                              {("zone-dock", ""): ("zone-dock", ""), ("zone-cold", TEMP): ("Cold room A: temp", "°C")}, 10)
    words = {a["text"]: a for a in out}
    assert "zone-dock is not answering" in words and words["zone-dock is not answering"]["level"] == "alarm"
    assert "Cold room A: temp has no reading" in words and words["Cold room A: temp has no reading"]["level"] == "warning"
    assert len(raised) == 2
    out, _, cleared = al.judge("", [], {("zone-cold", TEMP): _ev(TEMP, -18, 20)}, {"zone-cold": True, "zone-dock": True}, {}, 20)
    assert out == [] and len(cleared) == 2


def test_an_on_off_alarm_counts_from_when_it_changed():
    al, r = devboard.Alarms(), _r(item=DOOR, when="on", level="warning", **{"for": 30})
    out, raised, _ = al.judge("", [r], {("zone-cold", DOOR): _ev(DOOR, True, 100)}, {}, {}, 140)
    assert out[0]["state"] == "active" and out[0]["held"] == 40 and out[0]["level"] == "warning" and len(raised) == 1


def test_the_terminal_says_the_same_board():
    b = {"machines": [{"machine": "zone-cold", "up": True, "things": [
        {"id": TEMP, "name": "Cold room A: Cold room temperature", "unit": "°C", "kind": "sensor", "onoff": False,
         "group_name": "Cold room A", "value": -18.4},
        {"id": DOOR, "name": "Cold room A: Cold room door", "unit": "", "kind": "binary_sensor", "onoff": True,
         "group_name": "Cold room A", "value": True}]}],
        "alarms": [{"machine": "zone-cold", "text": "Cold room A: Cold room door is on", "level": "warning",
                    "state": "active", "held": 40, "ack": {"by": "Ada"}}]}
    t = devboard.text(b)
    assert "1 alarms" in t and "seen by Ada" in t and "-18.4°C" in t and "open" in t and "Cold room temperature" in t


# ---- the hub -------------------------------------------------------------------------------

def test_the_hub_raises_an_alarm_says_it_once_and_serves_it_on_the_board(monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import server
    with TestClient(server.app) as c:
        here = server._here_name()
        machines = [{"machine": here, "key": "here", "here": True, "up": True, "live": True, "things": [
            {"id": COMP, "name": "Cold room B: Compressor", "unit": "", "kind": "switch", "onoff": True,
             "group": "esp.cold-2", "group_name": "Cold room B"}]}]
        monkeypatch.setattr(server, "_board_machines", lambda owner: [dict(m, things=[dict(t) for t in m["things"]])
                                                                         for m in machines] if owner == "" else [])
        said, told = [], []

        async def event(owner, ev, label, text, **meta):
            said.append((ev, text))

        async def tell(ev, owner):
            told.append(ev)
        monkeypatch.setattr(server, "_device_event", event)
        monkeypatch.setattr(server, "_tie_tell", tell)
        monkeypatch.setattr(server, "_demo_shows", lambda me: False)    # never a demo running on this machine
        server._ALARMS = None
        r = c.put("/api/devices/alarms", json={"alarms": [{"machine": here, "item": COMP, "when": "off"},
                                                           {"machine": here, "when": "sometimes"}]})
        assert r.status_code == 200 and len(r.json()["alarms"]) == 1 and r.json()["dropped"]
        comp = {"item": COMP, "domain": "switch", "name": "Cold room B: Compressor", "at": time.time()}
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(server._device_observe("", here, [{**comp, "value": 1.0, "first": True}], live=True))
            assert not any(e == "alarm" for e, _ in said)
            loop.run_until_complete(server._device_observe("", here, [{**comp, "value": 0.0, "prev": 1.0}], live=True))
            loop.run_until_complete(server._device_observe("", here, [{**comp, "value": 0.0, "prev": 0.0}], live=True))
        finally:
            loop.close()
        alarms = [t for e, t in said if e == "alarm"]
        assert alarms == [f"Alarm on {here}: Cold room B: Compressor is off"], "raised once, in words"
        assert any(ev.get("type") == "device_alarm" and ev["phase"] == "raised" for ev in told)
        b = c.get("/api/devices/board").json()
        assert b["machines"][0]["things"][0]["value"] == 0.0
        a = b["alarms"][0]
        assert a["state"] == "active" and a["text"] == "Cold room B: Compressor is off"
        got = c.post("/api/devices/alarms/ack", json={"id": a["id"]})
        assert got.status_code == 200 and got.json()["alarm"]["ack"]
        assert c.post("/api/devices/alarms/ack", json={"id": "nope"}).status_code == 404
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(server._device_observe("", here, [{**comp, "value": 1.0, "prev": 0.0}], live=True))
        finally:
            loop.close()
        assert any(e == "cleared" for e, _ in said) and c.get("/api/devices/board").json()["alarms"] == []
        c.put("/api/devices/alarms", json={"alarms": []})


# ---- the page ------------------------------------------------------------------------------

def test_each_desktop_shows_its_own_scene_and_a_device_hub_gets_the_devices_one():
    b = (JS / "01b-immersive.js").read_text()
    assert "'devices'" in b.split("var IMMERSIVE_SCENES=")[1].split("\n")[0]
    assert "devices:1" in b.split("var LITE_SCENES=")[1].split("\n")[0], "words and numbers: a Pi can draw it"
    of = b.split("function immersiveSceneOf(")[1].split("\n}")[0]
    assert "deviceHub()" in of and "'devices'" in of and "'island'" in of
    # curDesk and DESKS are lets in a later file: read in a try, or the first paint throws
    assert re.search(r"function deskNow\(\)\{try\{return curDesk\}catch", b)
    assert re.search(r"function deskCount\(\)\{try\{return DESKS\}catch", b)
    assert "devSceneStart()" in b and "devSceneStop()" in b
    d = (JS / "03-virtual-desktops.js").read_text()
    sw = d.split("function switchDesk(")[1].split("\n}")[0]
    assert "immersiveDeskChanged(sceneWas)" in sw and sw.index("sceneWas=") < sw.index("curDesk=n")
    ws = (JS / "09-websocket.js").read_text()
    assert "case 'device_alarm'" in ws and "devSceneLive(ev)" in ws


def test_the_scene_draws_no_frames_and_writes_text_safely():
    s = (JS / "01h-devscene.js").read_text()
    assert "requestAnimationFrame" not in s and "<canvas" not in s
    assert "document.hidden" in s and "has-win" in s, "the refresh stops when nobody can see it"
    # every value from a machine passes esc() into the markup
    markup = "\n".join(ln for ln in s.splitlines() if "toast(" not in ln)      # a toast is text (textContent)
    for name in ("a.text", "a.machine", "m.machine", "g.name", "a.flow", "a.ack.by"):
        assert "${" + name + "}" not in markup, f"{name} reaches the markup without esc()"
    css = (ROOT / "agentos/ui/src/css/39-devscene.css").read_text()
    assert "backdrop-filter" not in css, "the one blurred surface is the active window"


def test_the_demo_floor_shows_on_this_machines_board_but_never_on_its_own_hub(monkeypatch):
    """Reported with a screenshot: the demo's user on this machine's desktop saw "0 machines",
    because the demo's devices are its own hub's. Its board is brought in here; a demo machine
    (its own env) never fetches it, or the hub asked itself, or another demo's hub."""
    from agentos.demos import warehouse
    monkeypatch.setattr(warehouse, "status", lambda: {"phase": "ready"})
    calls = []
    monkeypatch.setattr(warehouse.urllib.request, "urlopen", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(OSError("x")))
    monkeypatch.setenv("AGENTOS_DEMO_MACHINE", "warehouse-hub")
    assert warehouse.hub_board() is None and calls == []
    monkeypatch.delenv("AGENTOS_DEMO_MACHINE")
    assert warehouse.hub_board() is None and len(calls) == 1, "asked, and an unreachable hub is no board"
    assert warehouse._env("warehouse-hub", {})["AGENTOS_DEMO_MACHINE"] == "warehouse-hub"


def test_the_board_carries_the_days_numbers_and_each_numbers_hour():
    now = 100000.0
    evs = [{"at": now - 30, "event": "alarm", "text": "Alarm on zone-cold: Compressor is off"},
           {"at": now - 4000, "event": "alarm", "text": "Alarm on zone-cold: Compressor is off"},
           {"at": now - 3900, "event": "cleared", "text": "Cleared on zone-cold: Compressor is off"},
           {"at": now - 90000, "event": "alarm", "text": "too old"}]
    ms = [{"machine": "zone-cold", "up": True, "things": [{"value": 1}, {"value": None}]},
          {"machine": "zone-dock", "up": False, "things": []}]
    al = [{"state": "active", "level": "alarm", "held": 30, "ack": None},
          {"state": "active", "level": "warning", "held": 400, "ack": {"by": "x"}}, {"state": "pending"}]
    a = devboard.analytics(evs, al, ms, now)
    assert (a["answering"], a["machines"], a["reading"], a["things"]) == (1, 2, 1, 2)
    assert (a["alarms_now"], a["warnings_now"], a["acked"], a["pending"], a["longest"]) == (1, 1, 1, 1, 400)
    assert a["raised_24h"] == 2 and a["cleared_24h"] == 1 and a["by_hour"][23] == 1 and a["by_hour"][22] == 1
    assert a["top"] == [("Compressor is off", 2)]
    s = (JS / "01h-devscene.js").read_text()
    assert "function devSceneSpark" in s and "<title>" in s and "aria-label" in s, "each mark says its numbers"


def test_a_trend_is_the_kept_readings_of_the_last_hour(tmp_path, monkeypatch):
    from agentos import telemetry
    monkeypatch.setattr(telemetry, "path", lambda: tmp_path / "t.db")
    now = time.time()
    telemetry.db().executemany("INSERT INTO raw VALUES (?,?,?,?)",
                               [("m", "i", now - 3000 + 60 * k, -18.0 + k * .1) for k in range(40)])
    t = telemetry.trend("m", "i", now=now)
    assert t["first"] == -18.0 and abs(t["last"] - (-14.1)) < 1e-6 and t["min"] == -18.0
    assert len(t["points"]) == 30 and any(p is None for p in t["points"][:4])
    assert telemetry.trend("m", "nothing", now=now) == {}
