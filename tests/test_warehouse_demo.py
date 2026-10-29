"""The warehouse demo a person starts and plays with (agentos/demos/warehouse.py). Asked for as "is
the simulation something people can try with Bento, to play around, for demo purposes". The whole
start is run live (four servers); these pin what decides whether it is safe and honest."""
import json
from pathlib import Path

import pytest

from agentos.demos import esp_sim, warehouse_brain as wb, warehouse as wh

ROOT = Path(__file__).parent.parent


def test_your_brain_is_copied_by_value_and_its_folder_left_behind(monkeypatch):
    from agentos import executors
    monkeypatch.setattr(executors, "resolve_engine", lambda cfg, requested="": cfg.get("engine") or "aria")
    cfg = {"engine": "claude-code", "default_model": "", "telegram": {"token": "x"},
           "executors": {"claude_code": {"workspace": "/home/me/secret", "model": "opus"}},
           "providers": {"anthropic": {"api_key": "k"}}}
    keys, words = wh.brain_of(cfg)
    assert words == "Claude Code (opus)"
    assert keys["executors"]["claude_code"]["workspace"] == ""
    assert cfg["executors"]["claude_code"]["workspace"] == "/home/me/secret", "a copy, never the person's own"
    assert "telegram" not in keys and set(keys) <= set(wh.BRAIN_KEYS)
    assert wh.brain_of({"engine": "aria", "default_model": ""}) == ({}, "")


def test_the_hub_never_asks_its_zones_to_update_and_zones_think_with_it(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_DEMO_DIR", str(tmp_path))
    wh._config(wh.HUB, {})
    hub = json.loads((tmp_path / wh.HUB / "config.json").read_text())
    assert hub["provision"]["zero_updates"] == "off", "a zone's code root is this install"
    assert hub["default_model"] == wh.SCRIPTED and wh.SCRIPTED in hub["pricing_skip"]
    assert (tmp_path / wh.HUB / "soul.md").read_text().startswith("You are Aria")
    wh._config("zone-cold", {})
    z = json.loads((tmp_path / "zone-cold" / "config.json").read_text())
    assert z["provision"]["port"] == wh.door_port("zone-cold")
    env = wh._env("zone-cold")
    assert env["AGENTOS_VAULT_KEYRING"] == "0" and env["AGENTOS_HOME"].startswith(str(tmp_path))
    assert env["AGENTOS_MDNS_TARGET"].endswith(str(wh.sim_port("zone-cold") + 8))


def test_every_port_is_its_own_and_a_taken_one_refuses_in_a_sentence(tmp_path, monkeypatch):
    ps = wh.ports()
    assert len(ps) == len(set(ps))
    monkeypatch.setenv("AGENTOS_DEMO_DIR", str(tmp_path))
    monkeypatch.setattr(wh, "_port_taken", lambda p: p == wh.FLOOR)
    st = wh.start({}, scripted=True)
    assert st["phase"] == "failed" and f"Port {wh.FLOOR} is in use" in st["error"]
    assert not (tmp_path / "status.json").exists(), "nothing was started"


def test_start_over_deletes_only_a_demo_folder(tmp_path, monkeypatch):
    d = tmp_path / "mine"
    d.mkdir()
    (d / "keep.txt").write_text("x")
    monkeypatch.setenv("AGENTOS_DEMO_DIR", str(d))
    monkeypatch.setattr(wh, "_port_taken", lambda p: False)
    st = wh.start({}, scripted=True, fresh=True)
    assert "isn't a demo folder" in st["error"] and (d / "keep.txt").exists()


def test_a_dead_supervisor_reads_as_off(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_DEMO_DIR", str(tmp_path))
    wh._write_status(phase="ready", pid=2 ** 22 + 7)
    assert wh.status()["phase"] == "off"
    wh._write_status(phase="failed", error="zone-cold stopped")
    assert wh.status()["error"] == "zone-cold stopped"


def _say(*turns):
    msgs = [{"role": "user", "content": turns[0]}] + [{"role": "tool", "content": t} for t in turns[1:]]
    return wb._reply(msgs)


def test_the_scripted_brain_switches_only_when_asked_to():
    assert _say("is the compressor on in cold room a?")[1]["name"] == "device_get"
    assert _say("Cold room B looks warm. What's going on?")[1]["name"] == "device_get"
    _, call = _say("Put the fans on in aisles 7-12.")
    assert call["name"] == "device_set" and json.loads(call["arguments"])["item"] == "esp.aisle-2.switch.ceiling_fan"
    text, call = _say("turn off the fans")
    assert "fans off" in text and json.loads(call["arguments"])["value"] == "0"
    assert _say("turn off the fans", "a", "b") == ("Done. a b", None)
    assert _say("dock lights on")[1]["name"] == "device_set"
    assert _say("I couldn't care less", )[1] is None
    text, call = _say("how is the dock", *(["x on zone-dock: shut, read live"] * 5))
    assert call is None and text.startswith("The loading dock, read live") and "Door 1: shut" in text


def test_the_floor_is_moved_only_by_its_own_page(tmp_path, monkeypatch):
    sup = wh._Supervisor()
    sup.nodes = {"zone-cold": esp_sim.build("warehouse", 0, zone="zone-cold")}
    assert sup.poke({"node": "cold-2", "entity": "Compressor", "value": "off"})["value"] is False
    assert sup.poke({"node": "cold-2", "entity": "Cold room temperature", "value": "-3"})["value"] == -3.0
    assert not sup.poke({"node": "cold-9", "entity": "Compressor", "value": 1})["ok"]
    st = sup.state()
    names = [e["name"] for n in st["zones"]["zone-cold"] for e in n["ents"]]
    assert "WiFi signal" not in names, "diagnostics stay off the floor"
    page = (ROOT / "agentos/demos/floor.html").read_text()
    assert "innerHTML" not in page, "names are drawn as text"


def test_every_face_reaches_it():
    main = (ROOT / "agentos/__main__.py").read_text()
    assert 'verb("demo"' in main and "_demo_cli(args)" in main
    srv = (ROOT / "agentos/server.py").read_text()
    assert '@app.post("/api/demo/warehouse")' in srv and '("POST", "/api/demo")' in srv
    js = (ROOT / "agentos/ui/src/js/24o-devices.js").read_text()
    assert "devDemoLoad" in js and "winTick(w,devDemoLoad" in js
    assert "'warehouse'" in (ROOT / "agentos/ui/src/js/05b-places.js").read_text()
    assert (ROOT / "docs/warehouse-demo.md").exists()


@pytest.mark.parametrize("path", ["packaging/dev/warehouse/esp_sim.py", "packaging/dev/warehouse/warehouse_brain.py"])
def test_the_dev_run_still_finds_its_parts(path):
    assert "agentos.demos" in (ROOT / path).read_text()


def test_with_accounts_it_runs_as_a_user_of_its_own(tmp_path, monkeypatch):
    """Asked for as "the simulation should be started as a different user … so it wouldn't bother the app"."""
    monkeypatch.setenv("AGENTOS_DEMO_DIR", str(tmp_path / "warehouse"))
    assert wh.owner() is None
    wh.set_owner("abc123", "demo")
    assert wh.owner()["name"] == "demo" and (tmp_path / "warehouse-owner.json").exists(), \
        "kept beside the folder, so Start over keeps it"
    srv = (ROOT / "agentos/server.py").read_text()
    route = srv[srv.index("def _demo_account"):srv.index('@app.post("/api/devices/esp")')]
    assert 'return {"need": ""}' in route.split("if not usersmod.enabled():")[1][:40], "no accounts: as before"
    assert '"need": "create"' in route and '"need": "signin"' in route
    assert 'role="executor"' in route and '["setup_complete"] = True' in route
    js = (ROOT / "agentos/ui/src/js/24o-devices.js").read_text()
    assert "ac.need==='create'" in js and "ac.need==='signin'" in js
