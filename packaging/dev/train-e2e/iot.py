"""Train on device readings, live: the page's "Your devices" source on a seeded hub.

    python packaging/dev/train-e2e/iot.py /tmp/train-iot

A real server on a throwaway home that seed_iot.py gave two days of a cold room's readings
and fifteen alarms (made-up history, a real readings store and a real diary). It walks
Datasets → Your devices → Make examples at 1440x900 and on a 390px phone, and checks the
examples against the record. The fine-tune on them is `bento train start` (slow on a
processor, so it is not repeated here). Prints ✓/✗ and exits 1 on any ✗.
"""
import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[3])
PY = ROOT + "/.venv/bin/python"
PORT = 8652
BASE = f"http://127.0.0.1:{PORT}"


def main():
    work = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/train-iot")
    home, shots = work / "home", work / "shots"
    shutil.rmtree(home, ignore_errors=True)
    shots.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True)
    (home / "config.json").write_text(json.dumps({
        "agent_name": "Bento", "setup_complete": True, "permissions_migrated": True,
        "workspace": str(home / "work"), "updates": {"enabled": False}}))
    keep = ("AGENTOS_TRAIN_PYTHON", "AGENTOS_TRAIN_HF_HOME")
    env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTOS_") or k in keep}
    env.update(AGENTOS_HOME=str(home), AGENTOS_VAULT_KEYRING="0", NO_PROXY="127.0.0.1,localhost",
               no_proxy="127.0.0.1,localhost")
    seeded = json.loads(subprocess.run([PY, str(Path(__file__).with_name("seed_iot.py"))], env=env, cwd=ROOT,
                                       capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1])
    srv = subprocess.Popen([PY, "-m", "agentos", "serve", "--port", str(PORT), "--no-browser", "--if-running", "fail"],
                           env=env, cwd=ROOT, stdout=open(work / "server.log", "w"), stderr=subprocess.STDOUT)
    bad = []

    def check(ok, what):
        print(("  ✓ " if ok else "  ✗ ") + what, flush=True)
        if not ok:
            bad.append(what)

    async def run():
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            br = await pw.chromium.launch()
            for name, ctx in (("", {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 2, "reduced_motion": "reduce"}),
                              ("-phone", {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True,
                                          "device_scale_factor": 2, "reduced_motion": "reduce"})):
                c = await br.new_context(**ctx)
                p = await c.new_page()
                errs = []
                p.on("pageerror", lambda e: errs.append(str(e)))
                await p.add_init_script("try{localStorage.setItem('immersive.scene','aurora');localStorage.setItem('immersive.town','1')}catch(e){}")
                await p.goto(BASE + "/")
                for _ in range(100):
                    try:
                        if await p.evaluate("()=>typeof openApp==='function'"):
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(0.4)
                await p.evaluate("()=>openApp('train')")
                await p.wait_for_selector(".trn-tabs", timeout=20000)
                if not name:
                    await p.evaluate("()=>{const w=[...document.querySelectorAll('.win')].pop();"
                                     "const b=w&&w.querySelector('.tbtns .mx');b&&b.offsetParent&&b.click()}")
                await p.evaluate("()=>trainTab('datasets')")
                await p.wait_for_selector(".trn-srcs", timeout=15000)
                await p.evaluate("()=>trainSrc('devices')")
                await p.wait_for_selector(".trn-srcbody .trn-hub", timeout=15000)
                await p.wait_for_timeout(500)
                if not name:
                    print("1. Datasets → Your devices")
                    said = await p.inner_text(".trn-srcbody .trn-hub")
                    check(seeded["machine"] in said and f"{seeded['alarms']} alarms on record" in said,
                          f"the hub's own board is listed with its {seeded['alarms']} alarms on record")
                    check("Cold room B: Temperature" in said, "its things are named as Devices names them")
                await p.screenshot(path=str(shots / f"train-devices{name}.png"))
                if name:
                    over = await p.evaluate("()=>{const e=document.querySelector('.trn-pane');return e.scrollWidth-e.clientWidth}")
                    small = await p.evaluate("""()=>[...document.querySelectorAll('.trn button')].filter(b=>b.offsetParent&&!b.disabled)
                        .map(b=>{const r=b.getBoundingClientRect();return [b.textContent.trim().slice(0,18),Math.round(r.height),Math.round(r.right)]})
                        .filter(x=>x[1]<36||x[2]>391)""")
                    print("3. A phone")
                    check(over <= 1 and not small, f"nothing runs off a phone and every button is 36px or more ({over}px, {small[:3]})")
                else:
                    await p.select_option("#trn-dv-days", "1")
                    await p.click(".trn-srcbody >> text=Make examples")
                    await p.wait_for_selector(".trn-ds", timeout=30000)
                    d = await (await p.request.get(BASE + "/api/train")).json()
                    ds = d["datasets_list"][0]
                    full = await (await p.request.get(BASE + f"/api/train/datasets/{ds['id']}?rows=200")).json()
                    kinds = {}
                    for r in full["sample"]:
                        kinds[r["response"].split(":")[0]] = kinds.get(r["response"].split(":")[0], 0) + 1
                    print("2. Make examples")
                    check(ds["source"] == "devices" and ds["rows"] == ds["answers"] >= 20, f"{ds['rows']} examples, every one answered from the record")
                    check(set(kinds) == {"normal", "alarm", "coming"}, f"windows that were quiet, had an alarm on, and had one coming ({kinds})")
                    check(kinds["normal"] <= max(20, kinds["alarm"] + kinds["coming"]), "the quiet windows are thinned to match the others")
                    hot = next(r for r in full["sample"] if r["response"].startswith("alarm"))
                    now_temp = float(hot["prompt"].split("Temperature (°C): ")[1].split("now ")[1].split(",")[0])
                    check(now_temp > 8, f"a window marked alarm ends above the 8 °C that raised it ({now_temp})")
                    check("Cold room B is too warm" in full["system"], "the instruction names the alarm it has to know")
                    led = await (await p.request.get(BASE + "/api/audit?limit=50")).json()
                    check(any(r.get("action") == "train.import" and "device:" in (r.get("resource") or "") for r in led["entries"]),
                          "the ledger has the import from the machine")
                    await p.evaluate(f"()=>trainOpenDs('{ds['id']}')")
                    await p.wait_for_selector(".trn-ds .trn-open", timeout=15000)
                    await p.evaluate("()=>document.querySelector('.trn-ds').scrollIntoView({block:'start'})")
                    await p.wait_for_timeout(400)
                    await p.screenshot(path=str(shots / "train-devices-examples.png"))
                check(not errs, "no page errors" + (": " + "; ".join(errs[:3]) if errs else ""))
                await c.close()
            await br.close()
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(BASE + "/api/users/who", timeout=2)
                break
            except Exception:
                time.sleep(0.5)
        asyncio.run(run())
    finally:
        srv.send_signal(signal.SIGTERM)
        try:
            srv.wait(40)
        except subprocess.TimeoutExpired:
            srv.kill()
    print("\n" + ("ALL GOOD" if not bad else f"{len(bad)} FAILED:\n  " + "\n  ".join(bad)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
