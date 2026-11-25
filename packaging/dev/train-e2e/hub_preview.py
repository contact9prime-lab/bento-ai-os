"""Preview a Hub dataset before importing it, live: a real server on a throwaway home and
the real Hugging Face Hub.

    python packaging/dev/train-e2e/hub_preview.py /tmp/train-hub

Walks Datasets → Hugging Face Hub → search "sms spam" → Preview on ucirvine/sms_spam (whose
columns, `sms` and `label`, no conventional pair names), swaps the columns, puts them back,
and imports what it showed, at 1440x900 and on a 390px phone. Prints ✓/✗, exits 1 on any ✗.
Needs playwright (`uv run --with playwright`); CHROME names a browser when playwright has none.
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
PY = sys.executable
PORT = 8653
BASE = f"http://127.0.0.1:{PORT}"
REPO = "ucirvine/sms_spam"


def main():
    work = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/train-hub")
    home, shots = work / "home", work / "shots"
    shutil.rmtree(home, ignore_errors=True)
    shots.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True)
    (home / "config.json").write_text(json.dumps({
        "agent_name": "Bento", "setup_complete": True, "permissions_migrated": True,
        "workspace": str(home / "work"), "updates": {"enabled": False}}))
    env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTOS_")}
    env.update(AGENTOS_HOME=str(home), AGENTOS_VAULT_KEYRING="0", NO_PROXY="127.0.0.1,localhost",
               no_proxy="127.0.0.1,localhost")
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
            chrome = os.environ.get("CHROME")
            br = await pw.chromium.launch(**({"executable_path": chrome} if chrome else {}))
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
                await p.evaluate("()=>trainSrc('hub')")
                await p.fill("#trn-hubq", "sms spam")
                await p.evaluate("()=>trainHub()")
                await p.wait_for_selector(".trn-srcbody .trn-hub", timeout=30000)
                row = p.locator(".trn-hub", has_text=REPO).first
                await row.get_by_role("button", name="Preview").click()
                await p.wait_for_selector(".trn-prev-t", timeout=30000)
                await p.wait_for_timeout(400)
                await p.evaluate("()=>document.querySelector('.trn-hub.open,.trn-prev').previousElementSibling.scrollIntoView({block:'start'})")
                await p.wait_for_timeout(300)
                print(("1. " if not name else "3. ") + "Preview " + REPO + (" on a phone" if name else ""))
                cells = await p.locator(".trn-prev-t tbody tr").count()
                head = await p.inner_text(".trn-prev")
                check(cells >= 5, f"the first rows are shown ({cells})")
                check("spam" in head and "ham" in head, "the label column shows its names, not 0 and 1")
                picked = await p.evaluate("()=>[...document.querySelectorAll('.trn-prev select')].map(s=>s.value)")
                check(picked[-2:] == ["sms", "label"], f"read as prompt = sms, answer = label ({picked})")
                await p.screenshot(path=str(shots / f"train-hub-preview{name}.png"))
                if name:
                    over = await p.evaluate("()=>{const e=document.querySelector('.trn-pane');return e.scrollWidth-e.clientWidth}")
                    wide = await p.evaluate("""()=>{const W=document.querySelector('.trn-pane').getBoundingClientRect().right;
                        return [...document.querySelectorAll('.trn-pane *')].filter(e=>e.getBoundingClientRect().right>W+1)
                        .slice(0,4).map(e=>e.tagName+'.'+e.className+' '+Math.round(e.getBoundingClientRect().right))}""")
                    if over > 1:
                        print("    wide:", wide)
                    small = await p.evaluate("""()=>[...document.querySelectorAll('.trn-prev button,.trn-hub button,.trn-prev select')].filter(b=>b.offsetParent&&!b.disabled)
                        .map(b=>{const r=b.getBoundingClientRect();return [b.textContent.trim().slice(0,18),Math.round(r.height),Math.round(r.right)]})
                        .filter(x=>x[1]<36||x[2]>391)""")
                    check(over <= 1 and not small, f"nothing runs off a phone and every control is 36px or more ({over}px, {small[:3]})")
                else:
                    sels = p.locator(".trn-prev select")
                    await sels.nth(sels_n := (await sels.count()) - 1).select_option("")
                    await p.wait_for_function("()=>TRAIN.busy===''", timeout=30000)
                    after = await p.evaluate("()=>[...document.querySelectorAll('.trn-prev select')].map(s=>s.value)")
                    print("2. Change the columns, then import")
                    check(after[-1] == "", f"the answer can be left to a teacher ({after})")
                    await p.screenshot(path=str(shots / "train-hub-preview-noanswer.png"))
                    await p.locator(".trn-prev select").nth(sels_n).select_option("label")
                    await p.wait_for_function("()=>TRAIN.busy===''", timeout=30000)
                    await row.get_by_role("button", name="Import").click()
                    await p.wait_for_selector(".dlg input", timeout=10000)
                    inp = p.locator(".dlg input").first
                    await inp.fill("200")
                    await inp.press("Enter")
                    await p.wait_for_selector(".trn-ds", timeout=60000)
                    d = await (await p.request.get(BASE + "/api/train")).json()
                    ds = d["datasets_list"][0]
                    check(ds["source"] == "hub" and ds["ref"] == REPO and ds["rows"] >= 190 and ds["answers"] == ds["rows"],
                          f"imported with every row answered ({ds['rows']} rows, {ds['answers']} answered)")
                    check(ds["how"]["prompt"] == "sms" and ds["how"]["response"] == "label", f"read as it was previewed ({ds['how']})")
                    full = await (await p.request.get(BASE + f"/api/train/datasets/{ds['id']}?rows=200")).json()
                    check({r["response"] for r in full["sample"]} == {"ham", "spam"}, "answers are ham and spam")
                    await p.evaluate(f"()=>trainOpenDs('{ds['id']}')")
                    await p.wait_for_selector(".trn-ds .trn-open", timeout=15000)
                    await p.evaluate("()=>document.querySelector('.trn-ds').scrollIntoView({block:'start'})")
                    await p.wait_for_timeout(400)
                    await p.screenshot(path=str(shots / "train-hub-imported.png"))
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
        print("4. The terminal")
        out = subprocess.run([PY, "-m", "agentos", "train", "preview", REPO], env=env, cwd=ROOT,
                             capture_output=True, text=True, timeout=120).stdout
        (shots / "train-hub-preview-terminal.txt").write_text("$ bento train preview " + REPO + "\n" + out)
        check("label [answer], sms [prompt]" in out and "--prompt sms --answer label" in out,
              "bento train preview reads it the same way")
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
