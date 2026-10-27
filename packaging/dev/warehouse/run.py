"""A warehouse run centrally from one hub, end to end on real servers (espnodes.py):

  the hub          `bento serve` with a stand-in brain (warehouse_brain.py)
  three zone Pis   fresh `bento serve`s set up from the hub's one line: zone-cold, zone-dock,
                   zone-aisle
  six ESP32 nodes  esp_sim.py, speaking ESPHome's web server API and mDNS, two on each zone's
                   own network: the cold rooms, the loading dock and the forklift bay, the aisles

What it checks, in order:

  1. the three zones are set up by the hub's key, nobody pressing anything
  2. each zone finds ITS nodes over mDNS (the hub asks; the zone listens on its own network)
  3. the hub adds them, the zone reads each one first, and they join the zone's hardware list
     as <zone>/esp.<node>.<domain>.<name>
  4. nothing is usable until permitted: a read is refused BY THE ZONE; then the hub permits the
     sensors and the switches (Devices → What agents may use)
  5. "walk me through the warehouse": the hub's agent reads seven things across three zones
  6. cold room B's compressor trips: the agent finds it, asks to switch it back on, a person says
     yes on the hub's screen, and it is read back from the node; the room starts cooling
  7. a set with nobody to say yes is refused, never made
  8. `bento network esp|get|set` from a terminal
  9. the readings reach the hub (the hello), and both ledgers say what happened

    python run.py [WORKDIR] [--keep] [--setup-only]

--setup-only stops after step 4 and leaves everything running, to drive the hub's chat by hand.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "provision-e2e"))
import zero_run as zr          # noqa: E402  (its servers and helpers)

HUB = "warehouse-hub"
ZONES = ["zone-cold", "zone-dock", "zone-aisle"]
# name, http, link, claim door, brain port, broadcast targets
zr.MACHINES = [(HUB, 8581, 8681, 0, 9481, "127.255.255.255")] + [
    (z, 8582 + i, 8682 + i, 8782 + i, None, "203.0.113.255") for i, z in enumerate(ZONES)]
zr.ENV["AGENTOS_DISCOVER_UDP"] = "18641"
SIM = {z: 18810 + 10 * i for i, z in enumerate(ZONES)}      # each zone's nodes: base, +7 control, +8 mDNS
SPEED = float(os.environ.get("WAREHOUSE_SPEED") or 20)       # model seconds per real second


def sim_env(z):
    # each zone its own address, as Pis on a network have (teamlink.local_addr), and its own
    # nodes' mDNS: a zone hears only the nodes on its own network
    return {"AGENTOS_MDNS_TARGET": f"127.0.0.1:{SIM[z] + 8}", "AGENTOS_LINK_FROM": f"127.0.0.{ZONES.index(z) + 2}"}


def poke(zone, node, entity, value):
    req = urllib.request.Request(f"http://127.0.0.1:{SIM[zone] + 7}/", method="POST",
                                 data=json.dumps({"node": node, "entity": entity, "value": value}).encode())
    urllib.request.urlopen(req, timeout=5).read()


def sim_state(zone):
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{SIM[zone] + 7}/", timeout=5).read())


def chat(text, approve=None, timeout=200):
    """The hub's chat as the desktop sends it (the websocket), so an approval card comes up as it
    does on a screen. `approve`: what the person at the hub says to each card."""
    import asyncio
    import websockets

    async def go():
        out, asked = [], []
        async with websockets.connect("ws://127.0.0.1:8581/ws", max_size=None) as ws:
            await ws.send(json.dumps({"type": "chat", "text": text}))
            t0 = time.time()
            while time.time() - t0 < timeout:
                ev = json.loads(await asyncio.wait_for(ws.recv(), timeout))
                t = ev.get("type")
                if t == "text_delta":
                    out.append(ev.get("text") or "")
                elif t == "tool_start":
                    out.append("\n")
                elif t == "approval_request":
                    asked.append(ev)
                    await asyncio.sleep(1.0)
                    if approve is not None:
                        await ws.send(json.dumps({"type": "approval", "id": ev["id"], "approved": approve}))
                elif t == "turn_end":
                    break
        return "".join(out).strip(), asked
    return asyncio.run(go())


def main():
    zr.say(f"work dir {zr.WORK}")
    procs = [subprocess.Popen([sys.executable, str(HERE / "warehouse_brain.py"), "9481"], env=zr.ENV,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    for z in ZONES:
        procs.append(subprocess.Popen([sys.executable, str(HERE / "esp_sim.py"), "--zone", z, "--base", str(SIM[z]),
                                       "--control", str(SIM[z] + 7), "--mdns", str(SIM[z] + 8), "--speed", str(SPEED)],
                                      env=zr.ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    try:
        for x in zr.MACHINES:
            zr.config(*x)
        zr.start(HUB)
        st, z = zr.http(HUB, "POST", "/api/provision/zero", {"hubs": ["127.0.0.1"]})
        assert st == 200, z
        enroll = zr.re.search(r"--enroll=(\S+)", z["line"]).group(1)
        hubs = zr.re.search(r"--hub=(\S+)", z["line"]).group(1)
        for zone in ZONES:
            assert zr.bento(zone, "pool", "hub", hubs).returncode == 0
            zr.start(zone, {"AGENTOS_ENROLL": enroll, **sim_env(zone)})
        for zone in ZONES:
            zr.wait(f"{zone} is set up by the key",
                    lambda: zr.http(zone, "GET", "/api/provision")[1]["this"]["claimed"] or None, limit=90)

        def row(zone):
            return next((r for r in zr.http(HUB, "GET", "/api/network")[1]["rows"]
                         if any(lk.get("label") == zone for lk in r.get("links") or [])), None)
        keys = {}
        for zone in ZONES:
            _, r = zr.wait(f"{zone} is on the hub's list", lambda: row(zone), limit=90)
            keys[zone] = r["key"]
            zr.wait(f"{zone} answers its hub", lambda: (lambda s: s[1] if s[0] == 200 else None)(
                zr.http(HUB, "POST", "/api/network/hardware", {"key": keys[zone]})), limit=120, every=3)
        zr.step("1. three zones set up from the hub's one line", zones=ZONES)

        found = {}
        for zone in ZONES:
            st, f = zr.http(HUB, "POST", "/api/devices/esp", {"key": keys[zone], "action": "find"})
            assert st == 200, f
            found[zone] = f["found"]
        zr.step("2. each zone finds its own nodes over mDNS",
                **{zone: [f"{x['name']} ({x['title']}) {x['host']}:{x['port']}" for x in fs] for zone, fs in found.items()})
        assert sorted(x["name"] for x in found["zone-cold"]) == ["cold-1", "cold-2"]

        added = {}
        for zone in ZONES:
            for x in found[zone]:
                st, a = zr.http(HUB, "POST", "/api/devices/esp", {"key": keys[zone], "action": "add", "name": x["name"],
                                                                  "host": x["host"], "port": x["port"]})
                assert st == 200, a
                added.setdefault(zone, []).append(f"{a['node']['title']}: {a['node']['things']} things")
        items = {zone: [i["id"] for i in (row(zone).get("hardware") or {}).get("items") or [] if i["id"].startswith("esp.")]
                 for zone in ZONES}
        zr.step("3. added from the hub, read by the zone, on its hardware list", **added,
                cold_items=items["zone-cold"][:8], said=a.get("said"))
        assert "esp.cold-2.switch.compressor" in items["zone-cold"]

        st, no = zr.http(HUB, "POST", "/api/devices/read", {"key": keys["zone-cold"],
                                                            "item": "esp.cold-2.sensor.cold_room_temperature"})
        assert st == 400 and "isn't permitted" in no["error"], no
        perms = {}
        for zone in ZONES:
            r = row(zone)
            can = r.get("device_can") or {}
            g = [i for i in can if i.startswith("esp.") and ".wifi_signal" not in i]
            s_ = [i for i, v in can.items() if v == "set" and i.startswith("esp.")]
            st, p = zr.http(HUB, "PUT", "/api/devices/permits", {"key": keys[zone], "get": g, "set": s_})
            assert st == 200, p
            perms[zone] = f"read {len(p['permits']['get'])}, set {', '.join(p['permits']['set'])}"
        zr.step("4. nothing usable until permitted: refused by the zone, then permitted from the hub",
                refused=no["error"], **perms)
        if "--setup-only" in sys.argv:
            (zr.WORK / "keys.json").write_text(json.dumps(keys))
            zr.say(f"set up: hub http://127.0.0.1:8581, sims control {[SIM[z] + 7 for z in ZONES]}")
            while True:
                time.sleep(3600)

        ans, _ = chat("Morning. Walk me through the warehouse.")
        zr.step("5. 'walk me through the warehouse'", answer=ans)
        assert "Cold room A:" in ans and "°C" in ans and "?" not in ans.split("Forklift battery:")[1][:6]

        poke("zone-cold", "cold-2", "Compressor", False)          # the compressor trips
        zr.wait("cold room B warms", lambda: sim_state("zone-cold")["cold-2"]["ents"]["Cold room temperature"] > -15,
                limit=120, every=2)
        ans, asked = chat("Cold room B looks warm. What's going on?", approve=True)
        st_after = sim_state("zone-cold")["cold-2"]["ents"]
        zr.step("6. the compressor tripped: found, asked, a person said yes, read back",
                card=[(a["name"], a["args"]) for a in asked], answer=ans, compressor_now=st_after["Compressor"])
        assert asked and asked[0]["name"] == "device_set" and st_after["Compressor"] is True
        assert "Read back from the node" in ans

        ans, asked = chat("Put the fans on in aisles 7-12.", approve=False)
        fan = sim_state("zone-aisle")["aisle-2"]["ents"]["Ceiling fan"]
        zr.step("7. a set the person says no to is not made", answer=ans, fan=fan)
        assert asked and fan is False

        cli = {}
        for args in (("esp", "zone-cold"), ("esp", "zone-dock", "find"), ("get", "zone-cold"),
                     ("get", "zone-cold", "esp.cold-2.sensor.cold_room_temperature"),
                     ("set", "zone-aisle", "esp.aisle-2.switch.ceiling_fan", "1", "--yes"),
                     ("set", "zone-dock", "esp.dock-1.binary_sensor.dock_door_1", "1", "--yes")):
            out = zr.bento(HUB, "network", *args)
            cli[" ".join(args)] = (out.returncode, (out.stdout + out.stderr).rstrip())
        (zr.WORK / "warehouse-terminal.txt").write_text(
            "\n\n".join(f"$ bento network {k}\n{v[1]}" for k, v in cli.items()) + "\n")
        zr.step("8. from a terminal", **{k: v[1].splitlines()[-1][:160] for k, v in cli.items()})
        assert sim_state("zone-aisle")["aisle-2"]["ents"]["Ceiling fan"] is True
        assert cli["set zone-dock esp.dock-1.binary_sensor.dock_door_1 1 --yes"][0] != 0, "a door contact is read only"

        def kept():
            st, d = zr.http(HUB, "GET", f"/api/devices/readings?key={keys['zone-cold']}&item=esp.cold-2.sensor.cold_room_temperature&range=day")
            return d if st == 200 and d.get("points") else None
        _, d = zr.wait("the cold room's readings reach the hub", kept, limit=200, every=5)
        led = {n: [f"{a} {d_[:90]}" for a, d_ in zr.ledger(n, "device.%")][-6:] for n in (HUB, "zone-cold")}
        zr.step("9. readings kept on the hub; both ledgers", points=len(d["points"]), stats=d.get("stats"),
                hub=led[HUB], zone_cold=led["zone-cold"])
        (zr.WORK / "report.json").write_text(json.dumps(zr.REPORT, indent=1, default=str))
        zr.say("all steps passed")
        if zr.KEEP:
            zr.say(f"--keep: hub http://127.0.0.1:8581, zones 8582-8584; sims control {[SIM[z] + 7 for z in ZONES]}")
            while True:
                time.sleep(3600)
    finally:
        if not zr.KEEP:
            for p in procs + list(zr.PROCS.values()):
                p.terminate()


if __name__ == "__main__":
    main()
