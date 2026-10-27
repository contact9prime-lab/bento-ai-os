"""A Zero's get and set (devio.py, the device_get / device_set tools, the link's device_* ops,
Devices → What agents may use, bento network get/set/permit). Asked for as "the Pi has two MCPs,
get and set … the hub is responsible for executing … only sensors where permission was granted,
at the tool level or the agent level … every set is asked, and from the Pi itself it goes to
Telegram as a double check"."""
import asyncio
import json
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from agentos import devio, hardware, inventory, teamlink, ties           # noqa: E402
from agentos.agent import Agent                                          # noqa: E402
from agentos.policy import MAIN, PDP, Principal                          # noqa: E402
from agentos.tools import SAFE_TOOLS, SPACE_SCOPED_TOOLS, TOOL_SCHEMAS   # noqa: E402
from test_gate_hardening import _decide, _world                          # noqa: E402
from test_pi_hardware import pi                                          # noqa: E402,F401
from test_zero_mind import _on, hz                                       # noqa: E402,F401

ROOT = Path(__file__).parent.parent

# a stand-in for pinctrl that keeps its pins in a file: 2 is lent to I2C, 17 is an input
FAKE_PINCTRL = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, sys
    from pathlib import Path
    f = Path(__file__).with_suffix(".json")
    pins = json.loads(f.read_text()) if f.exists() else {"2": ["a0", 1, "SDA1"], "17": ["ip", 0, "input"]}
    a = sys.argv[1:]
    if a[0] == "get":
        for n in (a[1].split("-") if "-" in a[1] else [a[1]]):
            m, lv, fn = pins.get(n, ["ip", 0, "input"])
            print(f"{n}: {m}    pd | {'hi' if lv else 'lo'} // GPIO{n} = {fn}")
    elif a[0] == "set":
        pins[a[1]] = ["op", 1 if a[3] == "dh" else 0, "output"]
        f.write_text(json.dumps(pins))
''')


@pytest.fixture()
def pins(tmp_path, monkeypatch):
    p = tmp_path / "pinctrl"
    p.write_text(FAKE_PINCTRL)
    p.chmod(0o755)
    monkeypatch.setenv("AGENTOS_PINCTRL", str(p))
    return p


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(teamlink, "home", lambda: tmp_path)
    return tmp_path


# ---- on the Pi -----------------------------------------------------------------------------

def test_the_pi_uses_only_what_it_permits_and_what_bento_can_read(home, pi, pins):
    assert "isn't permitted" in devio.refusal("get", "cpu.temp")
    assert "no reader" in devio.refusal("get", "camera.0"), "listed, but nothing built to use it"
    assert "can't set" in devio.refusal("set", "cpu.temp")
    got = devio.save_permits(["cpu.temp", "camera.0", "gpio.40"], ["gpio.17", "power.throttle"], by="office")
    assert sorted(got["get"]) == ["cpu.temp", "gpio.17"] and got["set"] == ["gpio.17"], "a settable item is readable too"
    assert any("camera.0" in d for d in got["dropped"]) and any("power.throttle" in d for d in got["dropped"])
    assert devio.refusal("get", "cpu.temp") == "" and devio.refusal("set", "gpio.17") == ""
    assert devio.permits()["by"] == "office"


def test_a_read_is_one_items_value_now(home, pi, pins):
    t = devio.read("cpu.temp")
    assert t["ok"] and isinstance(t["value"], float) and t["unit"] == "°C"
    g = devio.read("gpio.17")
    assert g["ok"] and g["value"] == 0 and g["detail"] == "input"
    assert not devio.read("w1.28-nothing")["ok"]


def test_a_set_drives_a_pin_reads_it_back_and_never_a_pin_lent_to_a_bus(home, pi, pins):
    out = devio.write("gpio.17", "on")
    assert out["ok"] and out["value"] == 1 and out["was"] == 0 and out["was_mode"] == "input"
    assert devio.read("gpio.17")["detail"] == "output"
    assert devio.write("gpio.17", "off")["value"] == 0
    assert "in use as SDA1" in devio.write("gpio.2", 1)["error"]
    assert not devio.write("gpio.17", "maybe")["ok"]


def test_the_pi_answers_only_its_own_hub(home, pi, pins, monkeypatch):
    from agentos import zero
    monkeypatch.setattr(zero, "is_my_hub", lambda cfg, lk: lk.get("label") == "office")
    devio.save_permits(["cpu.temp"], [])
    assert "only the hub" in devio.answer({}, {"label": "stranger"}, {"op": "device_get", "item": "cpu.temp"})["error"]
    assert devio.answer({}, {"label": "office"}, {"op": "device_get", "item": "cpu.temp"})["ok"]
    no = devio.answer({}, {"label": "office"}, {"op": "device_set", "item": "gpio.17", "value": 1})
    assert no["refused"] and "isn't permitted" in no["error"]
    w = devio.words({"op": "device_get", "item": "cpu.temp", "who": "Aria", "why": "is it too hot?"},
                    {"ok": True, "value": 51.2, "unit": "°C"}, "office")
    assert w == 'office read cpu.temp for Aria: 51.2 °C ("is it too hot?")'


# ---- on the hub: the gate ------------------------------------------------------------------

def test_the_hubs_gate_decides_each_item_for_each_agent(tmp_path):
    c, store, tb, pdp = _world(tmp_path)
    assert {"device_get", "device_set"} <= {t["name"] for t in TOOL_SCHEMAS}
    assert "device_get" in SAFE_TOOLS and tb.risk_of("device_set", {"item": "gpio.17"})[0] == "risky"
    assert {"device_get", "device_set"} <= SPACE_SCOPED_TOOLS
    listing = _decide(tb, pdp, MAIN, "device_get", {"machine": "pi"})
    assert listing.effect == "allow", "what a machine has is what Devices shows"
    app = Principal("app", "a-strangers-app")
    assert _decide(tb, pdp, app, "device_get", {"machine": "pi"}).effect == "ask", "an app asks even for the list"
    d = _decide(tb, pdp, MAIN, "device_get", {"machine": "Pi", "item": "cpu.temp"})
    assert d.effect == "ask" and d.grant_offer["resource"] == "device:pi/cpu.temp"
    assert _decide(tb, pdp, MAIN, "device_set", {"machine": "pi", "item": "gpio.17", "value": "1"}).rule == "device-ungranted"
    devio.sync_grants(store, "pi", ["cpu.temp", "gpio.17"], ["gpio.17"])
    assert _decide(tb, pdp, MAIN, "device_get", {"machine": "pi", "item": "cpu.temp"}).effect == "allow"
    assert _decide(tb, pdp, MAIN, "device_set", {"machine": "pi", "item": "gpio.17", "value": "1"}).effect == "allow"
    spec = Principal("subagent", "researcher")
    assert _decide(tb, pdp, spec, "device_get", {"machine": "pi", "item": "cpu.temp"}).effect == "ask", \
        "a grant for your own agent isn't one for a specialist"
    assert devio.sync_grants(store, "pi", ["cpu.temp"], []) == {"added": 0, "removed": 2}
    assert _decide(tb, pdp, MAIN, "device_set", {"machine": "pi", "item": "gpio.17", "value": "1"}).effect == "deny"
    store.add_grant("user", "", "device.get", "device:pi/*", source="user")
    devio.sync_grants(store, "pi", [], [])
    assert any(g["resource"] == "device:pi/*" for g in store.list_grants("user", "")), "a person's own grant is left"


def test_every_set_is_asked_even_with_a_grant(tmp_path):
    c, store, tb, pdp = _world(tmp_path, autonomy="full")
    tb.pdp = pdp
    devio.sync_grants(store, "pi", ["gpio.17"], ["gpio.17"])
    calls, asked = [], []

    async def devices(*a):
        calls.append(a)
        return "ok"
    tb.devices = devices

    async def approver(name, args, reason, offer=None):
        asked.append((name, offer))
        return False

    async def emit(ev):
        pass
    a = Agent(c, tb, "none", emit, approver)
    a._said = "Turning the fan on, it is 71 degrees."
    loop = asyncio.new_event_loop()
    out = loop.run_until_complete(a.call_tool("device_set", {"machine": "pi", "item": "gpio.17", "value": "1"}))
    assert asked == [("device_set", None)] and not calls, "asked at full autonomy, with a grant, no remember"
    asked.clear()
    a._said = "Checking the pin first."          # the agent's words before THIS call
    loop.run_until_complete(a.call_tool("device_get", {"machine": "pi", "item": "gpio.17"}))
    assert not asked and calls[0][:3] == ("get", "pi", "gpio.17")
    assert calls[0][6] == (c.get("agent_name") or "your agent") and calls[0][7] == "Checking the pin first.", \
        "who and why are the agent's, never the model's"
    loop.close()
    assert out


# ---- hub and Pi, over the real link ------------------------------------------------------

def test_the_hub_reads_and_sets_a_pis_pin_over_the_link_and_both_write_it_down(hz, pi, pins, monkeypatch):
    H, Z, loop = hz
    with teamlink.at(H["home"]):
        d = teamlink._load()
        d["links"][0]["url"] = f"127.0.0.1:{Z['lst'].port}"
        teamlink._save(d)
        lk = d["links"][0]
    zlog = []

    async def zero_on_ask(lk_, req):
        with teamlink.at(Z["home"]):
            if req.get("op") == "zero_hardware":
                return hardware.answer(Z["cfg"], lk_)
            got = devio.answer(Z["cfg"], lk_, req)
            zlog.append(devio.words(req, got, lk_.get("label")))
            return got
    Z["lst"].on_ask = zero_on_ask
    assert _on(H, loop, lambda: ties.ask_hardware(lk))["ok"]

    no = _on(H, loop, lambda: ties.device_call(lk, {"op": "device_get", "item": "cpu.temp", "who": "Aria"}))
    assert not no["ok"] and "isn't permitted" in no["error"], "nothing is permitted until somebody says so"
    p = _on(H, loop, lambda: ties.device_call(lk, {"op": "device_permits",
                                                   "permits": {"get": ["cpu.temp"], "set": ["gpio.17"]}}))
    assert p["ok"] and p["set"] == ["gpio.17"]
    with teamlink.at(Z["home"]):
        assert json.loads((Z["home"] / devio.FILE).read_text())["get"] == ["cpu.temp", "gpio.17"], "kept on the Pi"
    got = _on(H, loop, lambda: ties.device_call(lk, {"op": "device_get", "item": "cpu.temp", "who": "Aria",
                                                     "why": "is it hot in there?"}))
    assert got["ok"] and got["unit"] == "°C"
    s = _on(H, loop, lambda: ties.device_call(lk, {"op": "device_set", "item": "gpio.17", "value": 1, "who": "Aria"}))
    assert s["ok"] and s["value"] == 1
    assert len(zlog) == 4 and "is it hot in there?" in zlog[2] and "set gpio.17 to 1 for Aria" in zlog[3]
    # the hub's copy follows the machine at its next look
    with teamlink.at(H["home"]):
        assert _on(H, loop, lambda: ties.ask_hardware(lk))["ok"]
        row = ties.inventory_row(lk)
        assert row["device_permits"]["set"] == ["gpio.17"]
        assert devio.mark("gpio.17", row) == "read, set" and devio.mark("camera.0", row) == "listed only"
        assert "[read, set]" in devio.list_words(lk["label"], row)


def test_the_doors():
    srv = (ROOT / "agentos/server.py").read_text()
    h = srv[srv.index("async def _device_from_hub"):srv.index("def _here_name")]
    assert "devio.answer" in h and 'log("device"' in h and "audit_team" in h, "the Pi keeps its own record"
    on = srv[srv.index("async def _team_on_ask"):]
    assert '"device_get", "device_set", "device_permits"' in on[:3000]
    la = srv[srv.index("async def _linked_approval"):srv.index("def chat_id_of")]
    assert 'name == "device_set"' in la and "ask_approval" in la, "a set from the Pi goes to the owner's Telegram"
    t = srv[srv.index("async def _device_tool"):srv.index("def _zero_link")]
    assert "_device_zero" in t and "_device_event" in t
    r = srv[srv.index('@app.put("/api/devices/permits")'):]
    assert "_require_admin()" in r[:600] and "sync_grants" in r[:3000]
    from agentos import executors, fabric
    assert {"device_get", "device_set"} <= set(executors.TEAM_TOOLS), "a forwarded lead calls them over MCP"
    assert {"device_get", "device_set"} <= set(fabric.ZERO_CHAT_TOOLS)
    tl = (ROOT / "agentos/teamlink.py").read_text()
    assert '"device_get", "device_set"' in tl
    ag = (ROOT / "agentos/agent.py").read_text()
    assert 'name == "device_set" and dec.effect == "allow"' in ag
    js = (ROOT / "agentos/ui/src/js/24n-network.js").read_text()
    assert "function netHwPermHTML" in js and "/api/devices/permits" in js
    assert '"permit"' in (ROOT / "agentos/__main__.py").read_text()
