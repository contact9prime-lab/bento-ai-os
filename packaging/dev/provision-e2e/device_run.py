"""A Zero's get and set, end to end on real servers (devio.py): the hub (`bento serve` with a
stand-in brain) sets up a Zero as zero_run.py does, then:

  1. the hub reads what the Zero has (Devices → Hardware → Check now)
  2. nothing is usable yet: a live read is refused BY THE ZERO
  3. the hub permits cpu.temp to read and gpio.17 to set (Devices → What agents may use): the Zero
     keeps the list, the hub keeps a copy and writes its own agent's grants
  4. a live read from Devices, and the hub's chat asking "what is the Pi's temperature?" calls
     device_get, then device_get on that machine, through the gate
  5. a set asked at the Zero's own screen: no Telegram and nobody at the hub's screens, so it is
     refused at once, never made
  6. `bento network get|permit|set` from a terminal, the pin read back
  7. both ledgers and both diaries say what happened

The Zero is this computer with a stand-in `pinctrl` on its PATH (2 lent to I2C, 17 an input).

    python device_run.py [WORKDIR] [--keep]
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import zero_run as zr          # noqa: E402  (its machines, servers and helpers)

PINCTRL = '''#!/usr/bin/env python3
import json, sys
from pathlib import Path
f = Path(__file__).with_suffix(".json")
pins = json.loads(f.read_text()) if f.exists() else {"2": ["a0", 1, "SDA1"], "3": ["a0", 1, "SCL1"], "17": ["ip", 0, "input"]}
a = sys.argv[1:]
if a and a[0] == "get":
    r = a[1] if len(a) > 1 else "0-27"
    lo, _, hi = r.partition("-")
    for n in range(int(lo), int(hi or lo) + 1):
        m, lv, fn = pins.get(str(n), ["ip", 0, "input"])
        print(f"{n}: {m}    pd | {'hi' if lv else 'lo'} // GPIO{n} = {fn}")
elif a and a[0] == "set":
    pins[a[1]] = ["op", 1 if a[3] == "dh" else 0, "output"]
    f.write_text(json.dumps(pins))
'''


def rows(name):
    con = sqlite3.connect(zr.home(name) / "agentos.db")
    out = {"ledger": con.execute("select action, resource, coalesce(reason,'') || coalesce(detail,'') from audit "
                                 "where action like 'device.%' order by rowid").fetchall(),
           "diary": [r[0] for r in con.execute("select message from logs where kind='device' order by id")]}
    con.close()
    return out


def main():
    zr.say(f"work dir {zr.WORK}")
    bin_ = zr.WORK / "bin"
    bin_.mkdir(parents=True, exist_ok=True)
    (bin_ / "pinctrl").write_text(PINCTRL)
    (bin_ / "pinctrl").chmod(0o755)
    pi_env = {"PATH": f"{bin_}:{os.environ.get('PATH', '')}"}
    brain = zr.subprocess.Popen([sys.executable, str(HERE / "zero_brain.py"), "9441"], env=zr.ENV,
                                stdout=zr.subprocess.DEVNULL, stderr=zr.subprocess.DEVNULL)
    try:
        for x in zr.MACHINES:
            zr.config(*x)
        zr.start("big-box")
        st, z = zr.http("big-box", "POST", "/api/provision/zero", {"hubs": ["127.0.0.1"]})
        assert st == 200, z
        enroll = zr.re.search(r"--enroll=(\S+)", z["line"]).group(1)
        hubs = zr.re.search(r"--hub=(\S+)", z["line"]).group(1)
        assert zr.bento("pi-zero", "pool", "hub", hubs).returncode == 0
        zr.start("pi-zero", {"AGENTOS_ENROLL": enroll, **pi_env})
        zr.wait("the Zero is set up by the key",
                lambda: zr.http("pi-zero", "GET", "/api/provision")[1]["this"]["claimed"] or None, limit=60)

        def zero_row():
            r = next((r for r in zr.http("big-box", "GET", "/api/network")[1]["rows"]
                      if any(lk.get("label") for lk in r.get("links") or [])), None)
            return r
        _, row = zr.wait("the Zero is on the hub's list with its link", zero_row, limit=60)
        key = row["key"]
        # its link door opens once it has joined (zero_run.py waits the same way)
        _, hw = zr.wait("the Zero answers its hub", lambda: (lambda r: r[1] if r[0] == 200 else None)(
            zr.http("big-box", "POST", "/api/network/hardware", {"key": key})), limit=90, every=3)
        row = zero_row()
        can = row.get("device_can") or {}
        zr.step("1. the hub read what the Zero has", things=hw["items"], usable=len(can),
                settable=[k for k, v in can.items() if v == "set"][:6])
        assert can.get("gpio.17") == "set" and can.get("cpu.temp") == "get"

        st, no = zr.http("big-box", "POST", "/api/devices/read", {"key": key, "item": "cpu.temp"})
        zr.step("2. nothing permitted yet: the Zero refuses", status=st, said=no.get("error"))
        assert st == 400 and "isn't permitted" in no["error"]

        st, p = zr.http("big-box", "PUT", "/api/devices/permits",
                        {"key": key, "get": ["cpu.temp", "system.load"], "set": ["gpio.17", "gpio.2"]})
        assert st == 200, p
        kept = json.loads((zr.home("pi-zero") / "devices.json").read_text())
        zr.step("3. permitted from Devices", hub_copy=p["permits"], on_the_zero=kept, grants=p["grants"])
        assert kept["set"] == ["gpio.17", "gpio.2"] and p["grants"]["added"] == 6

        st, r = zr.http("big-box", "POST", "/api/devices/read", {"key": key, "item": "cpu.temp"})
        assert st == 200 and r["unit"] == "°C", r
        st, ans = zr.http("big-box", "POST", "/api/chat", {"text": "what is the Pi's temperature?"}, timeout=120)
        assert st == 200, ans
        zr.step("4. read live from Devices, and by the hub's agent through device_get",
                devices=f"{r['value']} {r['unit']}", chat=ans.get("content", "")[:300])
        assert "°C" in ans.get("content", ""), ans

        st, zans = zr.http("pi-zero", "POST", "/api/chat", {"text": "switch on pin 17"}, timeout=200)
        pin = json.loads((bin_ / "pinctrl.json").read_text()) if (bin_ / "pinctrl.json").exists() else {}
        zr.step("5. a set asked at the Zero's screen, with nobody to say yes: refused, not made",
                answer=zans.get("content", "")[:300], pin17=pin.get("17", ["ip", 0, "input"]))
        assert pin.get("17", ["ip"])[0] == "ip", "the pin must not have moved"
        assert "[denied]" in zans.get("content", "") and "needs a person" in zans["content"], zans

        cli = {}
        for args in (("get", "pi-zero"), ("permit", "pi-zero", "system.load", "off"), ("get", "pi-zero", "cpu.temp"),
                     ("set", "pi-zero", "gpio.17", "1", "--yes"), ("set", "pi-zero", "gpio.2", "1", "--yes"),
                     ("get", "pi-zero", "system.load")):
            out = zr.bento("big-box", "network", *args)
            cli[" ".join(args)] = (out.returncode, (out.stdout + out.stderr).strip())
        (zr.WORK / "device-terminal.txt").write_text("\n\n".join(f"$ bento network {k}\n{v[1]}" for k, v in cli.items()))
        pin = json.loads((bin_ / "pinctrl.json").read_text())
        zr.step("6. from a terminal", **{k: v[1].splitlines()[-1] for k, v in cli.items()}, pin17=pin["17"])
        assert pin["17"] == ["op", 1, "output"] and cli["set pi-zero gpio.2 1 --yes"][0] != 0
        assert cli["get pi-zero system.load"][0] != 0, "turned off, so refused"

        hub, zero = rows("big-box"), rows("pi-zero")
        zr.step("7. both sides wrote it down",
                hub_ledger=[f"{a} {r_}" for a, r_, _ in hub["ledger"]][-8:],
                zero_ledger=[f"{a} {r_}: {d[:90]}" for a, r_, d in zero["ledger"]][-8:],
                zero_diary=zero["diary"][-6:])
        assert any(a == "device.set" for a, _, _ in zero["ledger"])
        assert any("Reading its CPU temperature" in d for _, _, d in zero["ledger"]), "the agent's reason went along"
        (zr.WORK / "report.json").write_text(json.dumps(zr.REPORT, indent=1, default=str))
        zr.say("all steps passed")
        if zr.KEEP:
            zr.say("--keep: servers left running (hub http://127.0.0.1:8541, Zero http://127.0.0.1:8542)")
            while True:
                time.sleep(3600)
    finally:
        if not zr.KEEP:
            brain.terminate()
            for p in zr.PROCS.values():
                p.terminate()


if __name__ == "__main__":
    main()
