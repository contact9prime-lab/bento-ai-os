"""ESP32 nodes running ESPHome, as part of the Pi they are attached to (espnodes.py). Asked for as
"Bento has a controlling effect on the Pi now, think about sense with ESP32". Tested against
agentos/demos/esp_sim.py, which speaks ESPHome 2026.6's web server API and mDNS."""
import asyncio
import json
import socket
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

from agentos import devio, espnodes, hardware, teamlink, vault       # noqa: E402
from agentos.demos import esp_sim                                    # noqa: E402


def _free(n: int) -> int:
    """A base port with n free ports after it."""
    for _ in range(50):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        base = s.getsockname()[1]
        s.close()
        try:
            held = []
            for i in range(n):
                t = socket.socket()
                t.bind(("127.0.0.1", base + i))
                held.append(t)
            for t in held:
                t.close()
            return base
        except OSError:
            for t in held:
                t.close()
    raise RuntimeError("no free ports")


@pytest.fixture()
def sim(tmp_path, monkeypatch):
    monkeypatch.setattr(teamlink, "home", lambda: tmp_path)
    monkeypatch.setenv("AGENTOS_HOME", str(tmp_path))
    monkeypatch.setenv("AGENTOS_VAULT_KEYRING", "0")
    monkeypatch.setattr(vault, "_home", lambda: tmp_path)
    espnodes._LAST.clear()
    espnodes._DOWN.clear()
    base = _free(4)
    nodes = esp_sim.build("one", base, auth={"dock-1": ("admin", "s3cret")})
    esp_sim.serve(nodes, mdns=base + 3, speed=0.0)
    monkeypatch.setenv("AGENTOS_MDNS_TARGET", f"127.0.0.1:{base + 3}")
    time.sleep(0.2)
    return {n.host_name: n for n in nodes}


def test_a_node_is_kept_only_after_it_answers_and_its_password_stays_in_the_vault(sim, tmp_path):
    cold, dock = sim["cold-1"], sim["dock-1"]
    assert "nothing is listening" in espnodes.add("x", "127.0.0.1", cold.port + 50)["error"]
    assert "own network" in espnodes.add("x", "8.8.8.8", 80)["error"], "never a node on the internet"
    assert "password" in espnodes.add("dock-1", "127.0.0.1", dock.port)["error"], "it wants a password"
    no = espnodes.add("dock-1", "127.0.0.1", dock.port, user="admin", password="wrong")
    assert not no["ok"] and not vault.has("esp.dock-1"), "a refused add keeps no password"
    ok = espnodes.add("dock-1", "127.0.0.1", dock.port, user="admin", password="s3cret")
    assert ok["ok"] and ok["node"]["things"] == 6 and "plain HTTP" in ok["said"]
    kept = (tmp_path / espnodes.FILE).read_text()
    assert "s3cret" not in kept and vault.get("esp.dock-1") == "s3cret", "the password is in the vault only"
    assert "s3cret" not in json.dumps(espnodes.public(espnodes.node("dock-1")))
    assert espnodes.add("cold-1", "127.0.0.1", cold.port)["ok"]
    assert espnodes.remove("dock-1")["ok"] and not vault.has("esp.dock-1")


def test_what_a_node_has_is_read_from_it_and_becomes_the_pis_hardware(sim):
    espnodes.add("cold-1", "127.0.0.1", sim["cold-1"].port)
    items = {i["id"]: i for i in espnodes.items()}
    t = items["esp.cold-1.sensor.cold_room_temperature"]
    assert t["kind"] == "esphome" and t["unit"] == "°C" and t["can"] == ["read"] and t["value"] < -15
    assert items["esp.cold-1.switch.compressor"]["can"] == ["read", "write"]
    assert items["esp.cold-1.binary_sensor.cold_room_door"]["value"] == 0
    assert items["esp.cold-1"]["can"] == [] and "answering" in items["esp.cold-1"]["detail"]
    for iid, it in items.items():
        assert hardware._ID.fullmatch(iid), f"{iid} must fit an inventory id"
        if iid != "esp.cold-1":
            assert devio.GET_ID.fullmatch(iid)
    assert devio.SET_ID.fullmatch("esp.cold-1.switch.compressor")
    assert not devio.SET_ID.fullmatch("esp.cold-1.binary_sensor.cold_room_door")
    clean = hardware.clean({"items": list(items.values())})
    assert len(clean["items"]) == len(items), "the hub keeps every one"
    door = next(i for i in clean["items"] if i["id"].endswith("cold_room_door"))
    assert hardware.value_words({**door, "value": 1}) == "on"
    s = espnodes.sample()
    assert s["esp.cold-1.switch.compressor"] == 1 and isinstance(s["esp.cold-1.sensor.humidity"], float)
    before = espnodes.quick()
    sim["cold-1"].add("sensor", "Floor temperature", 2.0, "°C")
    espnodes.look("cold-1")
    assert espnodes.quick() != before, "a new sensor on a node changes the hash the hello carries"


def test_a_set_is_a_permitted_switch_and_it_is_read_back(sim, monkeypatch):
    espnodes.add("cold-1", "127.0.0.1", sim["cold-1"].port)
    item = "esp.cold-1.switch.compressor"
    assert "isn't permitted" in devio.refusal("set", item)
    devio.save_permits(["esp.cold-1.sensor.cold_room_temperature"], [item, "esp.cold-1.binary_sensor.cold_room_door"])
    p = devio.permits()
    assert p["set"] == [item] and item in p["get"], "a contact can't be set, so it isn't kept as settable"
    assert devio.refusal("set", item) == ""
    got = devio.write(item, "off")
    assert got["ok"] and got["value"] == 0 and got["was"] == 1 and got["read_back"] == "the node"
    assert sim["cold-1"].ents["switch/Compressor"].value is False
    assert devio.read(item)["detail"] == "off"
    assert "read, not set" in espnodes.write("esp.cold-1.binary_sensor.cold_room_door", 1)["error"]
    assert "on or off" in devio.write(item, "maybe")["error"]
    monkeypatch.setattr(sim["cold-1"], "act", lambda key, action: None)      # a relay that doesn't move
    monkeypatch.setattr(espnodes, "SET_WAIT", 0.4)
    stuck = devio.write(item, 1)
    assert not stuck["ok"] and "still reads off" in stuck["error"], "done means the node says so"


def test_nodes_are_found_over_mdns_and_never_used_because_they_were_heard(sim):
    found = asyncio.run(espnodes.discover(timeout=0.6))
    by = {f["name"]: f for f in found}
    assert set(by) == {"cold-1", "dock-1"} and by["cold-1"]["port"] == sim["cold-1"].port
    assert by["cold-1"]["title"] == "Cold room A" and by["cold-1"]["platform"] == "ESP32" and not by["cold-1"]["added"]
    assert espnodes.nodes() == [] and espnodes.items() == [], "heard is not added"
    espnodes.add("cold-1", "127.0.0.1", sim["cold-1"].port)
    assert {f["name"]: f["added"] for f in asyncio.run(espnodes.discover(timeout=0.6))}["cold-1"]


def test_only_the_pis_own_hub_changes_its_nodes(sim, monkeypatch):
    from agentos import zero
    monkeypatch.setattr(zero, "is_my_hub", lambda cfg, lk: lk.get("label") == "office")
    req = {"op": "esp_nodes", "action": "add", "name": "cold-1", "host": "127.0.0.1", "port": sim["cold-1"].port,
           "password": "pw"}
    assert "only the hub" in espnodes.answer({}, {"label": "stranger"}, req)["error"]
    got = espnodes.answer({}, {"label": "office"}, req)
    assert got["ok"]
    w = espnodes.words(req, got, "office")
    assert "added ESP32 node Cold room A" in w and "pw" not in w.replace("port", "")
    assert espnodes.answer({}, {"label": "office"}, {"action": "list"})["nodes"][0]["name"] == "cold-1"


def test_the_bench_board_reads_as_bento_will_see_it(tmp_path, monkeypatch):
    """packaging/esphome/bento-bench.yaml: an ESP32-S3 with a mic, a touch pad, a vibration switch,
    its RGB LED and an alarm on the speaker. The stand-in serves the same entities, so the names,
    kinds and units Bento files them under are pinned here."""
    monkeypatch.setattr(teamlink, "home", lambda: tmp_path)
    monkeypatch.setenv("AGENTOS_VAULT_KEYRING", "0")
    monkeypatch.setattr(vault, "_home", lambda: tmp_path)
    espnodes._LAST.clear()
    base = _free(1)
    node = esp_sim.build("bench", base, auth={"bench-1": ("bento", "pw")})[0]
    esp_sim.serve([node], speed=0.0)
    time.sleep(0.2)
    assert espnodes.add("bench-1", "127.0.0.1", base, user="bento", password="pw")["ok"]
    items = {i["id"]: i for i in espnodes.items()}
    assert items["esp.bench-1.sensor.chip_temperature"]["unit"] == "°C"
    assert items["esp.bench-1.sensor.sound_level"]["unit"] == "dB"
    assert items["esp.bench-1.text_sensor.esphome_version"]["value"] == "2026.6.5"
    assert items["esp.bench-1.binary_sensor.vibration"]["can"] == ["read"]
    for iid in ("esp.bench-1.light.status_led", "esp.bench-1.switch.alarm"):
        assert items[iid]["can"] == ["read", "write"] and devio.SET_ID.fullmatch(iid)
    led = espnodes.write("esp.bench-1.light.status_led", "on")
    assert led["ok"] and led["detail"] == "on" and node.ents["light/Status LED"].value is True
    yaml = (ROOT / "packaging/esphome/bento-bench.yaml").read_text()
    for e in node.ents.values():
        assert f"name: {e.name}" in yaml, f"{e.name} is in the stand-in but not in the YAML"


def test_the_doors():
    srv = (ROOT / "agentos/server.py").read_text()
    h = srv[srv.index("async def _esp_from_hub"):srv.index("def devio_resource_here")]
    assert "espnodes.discover()" in h and "is_my_hub" in h and 'log("device"' in h and "audit_team" in h
    assert h.count("password") == 1 and "never with the password" in h, "nothing here writes the password down"
    on = srv[srv.index("async def _team_on_ask"):]
    assert 'req.get("op") == "esp_nodes"' in on[:3500]
    r = srv[srv.index('@app.post("/api/devices/esp")'):]
    assert "_require_admin()" in r[:900] and "_tie_hardware" in r[:3500]
    assert '"esp_nodes"' in (ROOT / "agentos/teamlink.py").read_text(), "the link carries the op"
    main = (ROOT / "agentos/__main__.py").read_text()
    assert '"permit", "esp"]' in main and "def _esp_cli" in main
    js = (ROOT / "agentos/ui/src/js/24n-network.js").read_text()
    e = js[js.index("function netEspHTML"):js.index("function netHwPermHTML")]
    assert "secretField('esp-pw-'" in e and "plain HTTP" in e and "Find on its network" in e
