"""Train, live: a real server on a throwaway home, a real browser, a real fine-tune.

    python packaging/dev/train-e2e/run.py /tmp/train-e2e

Needs the training stack (AGENTOS_TRAIN_PYTHON, or `bento install train-stack`) and the
Hugging Face Hub reachable: the student (SmolLM2-135M, 270 MB) is downloaded, a Hub
dataset is searched and imported, and the model is trained on this machine's processor or
GPU. The one stand-in is the teacher (teacher.py), which writes the examples a big model
would. It walks Make from a goal to a checked model, then Datasets, Runs and Models, at
1440x900 and on a 390px phone, takes the terminal's face, and shows the page on a machine
where training is not installed. Prints ✓/✗ and exits 1 on any ✗.
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
PORT, BRAIN = 8651, 9431
BASE = f"http://127.0.0.1:{PORT}"
GOAL = "Sort support mail into billing, bug or other. Answer with one word."


def up(url, tries=120):
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def stop(p):
    p.send_signal(signal.SIGTERM)
    try:
        p.wait(40)
    except subprocess.TimeoutExpired:
        p.kill()


def main():
    work = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/train-e2e")
    home, shots = work / "home", work / "shots"
    shutil.rmtree(home, ignore_errors=True)
    shots.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True)
    (home / "config.json").write_text(json.dumps({
        "agent_name": "Bento", "setup_complete": True, "permissions_migrated": True,
        "default_model": "custom/teacher-1", "workspace": str(home / "work"),
        "updates": {"enabled": False},        # no "update available" card over the pictures
        "providers": {"custom": {"enabled": True, "base_url": f"http://127.0.0.1:{BRAIN}/v1", "api_key": "",
                                 "models": ["teacher-1"]}}}))
    keep = ("AGENTOS_TRAIN_PYTHON", "AGENTOS_TRAIN_HF_HOME")
    env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTOS_") or k in keep}
    env.update(AGENTOS_HOME=str(home), AGENTOS_VAULT_KEYRING="0", NO_PROXY="127.0.0.1,localhost",
               no_proxy="127.0.0.1,localhost")
    teacher = subprocess.Popen([PY, str(Path(__file__).with_name("teacher.py")), str(BRAIN)], env=env,
                               stdout=open(work / "teacher.log", "w"), stderr=subprocess.STDOUT)

    def serve(e):
        return subprocess.Popen([PY, "-m", "agentos", "serve", "--port", str(PORT), "--no-browser",
                                 "--if-running", "fail"], env=e, cwd=ROOT,
                                stdout=open(work / "server.log", "a"), stderr=subprocess.STDOUT)
    srv = serve(env)
    bad = []

    def check(ok, what):
        print(("  ✓ " if ok else "  ✗ ") + what, flush=True)
        if not ok:
            bad.append(what)

    async def desk(p):
        # the quiet scene: drawn in software, the 3D town takes a whole core from the training
        await p.add_init_script("try{localStorage.setItem('immersive.scene','aurora');localStorage.setItem('immersive.town','1')}catch(e){}")
        await p.goto(BASE + "/")
        for _ in range(100):
            try:
                if await p.evaluate("()=>typeof openApp==='function'"):
                    return
            except Exception:
                pass
            await asyncio.sleep(0.4)
        raise TimeoutError("the desktop did not load")

    async def train_app(p, big=True):
        await p.evaluate("()=>openApp('train')")
        await p.wait_for_selector(".trn-tabs", timeout=20000)
        if big:
            await p.evaluate("()=>{const w=[...document.querySelectorAll('.win')].pop();"
                             "const b=w&&w.querySelector('.tbtns .mx');b&&b.offsetParent&&b.click()}")
        await p.wait_for_timeout(700)

    async def api(p, path, method="GET", body=None):
        r = await (p.request.get(BASE + path) if method == "GET" else
                   p.request.fetch(BASE + path, method=method, data=body or {}))
        return await r.json()

    async def run():
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            br = await pw.chromium.launch()
            # reduced motion: a headless browser draws in software, and an animated wallpaper
            # took a whole core from the training (12 held-back answers in five minutes)
            wide = {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 2, "reduced_motion": "reduce"}
            phone = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True,
                     "device_scale_factor": 2, "reduced_motion": "reduce"}
            c = await br.new_context(**wide)
            p = await c.new_page()
            errs = []
            p.on("pageerror", lambda e: errs.append(str(e)))
            await desk(p)
            await api(p, "/api/pricing", "PUT", {"model": "custom/teacher-1", "in": 3, "out": 15})

            print("1. Make: a goal, a plan you see, a run")
            await train_app(p)
            st = await api(p, "/api/train")
            check(st["ready"], f"training is installed: {st['hardware'].get('words')}")
            check(st["teacher"] == "custom/teacher-1", f"the teacher is the machine's brain ({st['teacher']})")
            await p.screenshot(path=str(shots / "train-make-empty.png"))
            await p.fill("#trn-goal", GOAL)
            await p.click("text=Plan it")
            await p.wait_for_selector(".trn-plan", timeout=30000)
            await p.screenshot(path=str(shots / "train-plan.png"))
            base_pick = await p.input_value("#trn-p-base")
            check(await p.input_value("#trn-p-n") == "240", "the plan asks for 240 examples")
            check("write" in await p.inner_text(".trn-cost") and "24 calls" in await p.inner_text(".trn-cost"),
                  "the plan says who writes them and in how many calls, before anything is spent")
            before = (await (await p.request.get(f"http://127.0.0.1:{BRAIN}/calls")).json())
            check(before["write"] == 0, "planning wrote no examples")
            await p.click("text=Make it")
            await p.wait_for_selector(".trn-run", timeout=20000)
            seen = set()
            t0 = time.time()
            while time.time() - t0 < 1500:
                d = await api(p, "/api/train")
                r = d["runs_list"][0]
                title = r["steps"][-1]["title"] if r["steps"] else ""
                if title == "Writing examples" and "writing" not in seen and "written" in r["steps"][-1]["detail"]:
                    seen.add("writing")
                    await p.wait_for_timeout(400)
                    await p.screenshot(path=str(shots / "train-run-writing.png"))
                if title == "Training" and "training" not in seen and "training, step" in r["steps"][-1]["detail"]:
                    seen.add("training")
                    await p.wait_for_timeout(400)
                    await p.screenshot(path=str(shots / "train-run-training.png"))
                    await p.evaluate("()=>trainTab('runs')")
                    await p.wait_for_selector(".trn-detail .trn-prog", timeout=15000)
                    await p.wait_for_timeout(500)
                    await p.screenshot(path=str(shots / "train-job-running.png"))
                    await p.evaluate("()=>trainTab('make')")
                if r["state"] != "running":
                    break
                await asyncio.sleep(1.5)
            check(r["state"] == "done", f"the run finished: {r['steps'][-1]['title']}: {r['steps'][-1]['detail'][:200]}")
            check({"writing", "training"} <= seen, "the page showed it writing and then training")
            await p.wait_for_timeout(900)
            await p.screenshot(path=str(shots / "train-run-done.png"))
            calls = (await (await p.request.get(f"http://127.0.0.1:{BRAIN}/calls")).json())
            check(24 <= calls["write"] <= 40, f"the teacher was asked {calls['write']} times for 240 examples (ten to a call, repeats not kept)")
            d = await api(p, "/api/train")
            m = d["models_list"][0] if d["models_list"] else {}
            check(bool(m) and m["base"] == base_pick, f"a model was registered, from {m.get('base')}")
            ev = m.get("eval") or {}
            check(ev.get("n", 0) >= 10, f"{ev.get('n')} examples were held back and never trained on")
            check(ev.get("exact_after", 0) > ev.get("exact_before", 0),
                  f"it learned the job: {ev.get('exact_before')} exact before, {ev.get('exact_after')} after, of {ev.get('n')}")
            check(m.get("verdict", {}).get("word") == "learned", "its verdict is 'learned'")
            job = d["jobs_list"][0]
            jd = await api(p, "/api/train/jobs/" + job["id"])
            held = {i["prompt"] for i in jd["eval"]["items"]}
            ds = await api(p, f"/api/train/datasets/{job['dataset']}?rows=200")
            check(len(held) == ev["n"] and len(ds["sample"]) > 0, "the held-back examples are listed with both answers")
            usage = await api(p, "/api/usage/llms")
            n_calls = sum(m2.get("calls", 0) for u in usage.get("llms", []) for m2 in u.get("models", [])
                          if "teacher-1" in m2.get("model", ""))
            check(n_calls >= 25, f"the teacher's calls are in Usage ({n_calls} calls)")

            print("2. Runs: the loss, the check, the log")
            await p.evaluate("()=>trainTab('runs')")
            await p.wait_for_selector(".trn-chart svg", timeout=15000)
            box = await p.locator(".trn-chart svg").bounding_box()
            await p.mouse.move(box["x"] + box["width"] * .5, box["y"] + box["height"] * .5)
            await p.wait_for_timeout(300)
            check("step" in await p.inner_text(".trn-tip"), "the loss line reads a step under the pointer")
            await p.screenshot(path=str(shots / "train-job-done.png"))

            print("3. Models: what it learned, and trying it")
            await p.evaluate(f"()=>trainOpenModel('{m['id']}')")
            await p.wait_for_selector("#trn-try", timeout=15000)
            await p.fill("#trn-try", "Hello, I was billed twice for the Pro plan, please refund one.")
            await p.click(".trn-try >> text=Ask")
            await p.wait_for_selector(".trn-ans", timeout=180000)
            ans = await p.inner_text(".trn-ans > div:nth-child(2)")
            check(ans.strip().lower() == "billing", f"asked about a double charge, it answers: {ans.strip()!r}")
            check(await p.is_disabled("text=Add to Ollama") and "Ollama is not installed" in await p.inner_text(".trn-open"),
                  "with no Ollama here, Add to Ollama is greyed with the reason")
            check(await p.is_disabled("text=Publish…"), "with no token, Publish is greyed")
            await p.screenshot(path=str(shots / "train-model.png"))

            print("4. Datasets: the Hub, and a teacher answering")
            await p.evaluate("()=>trainTab('datasets')")
            await p.wait_for_selector(".trn-srcs", timeout=15000)
            await p.screenshot(path=str(shots / "train-datasets-teacher.png"))
            await p.evaluate("()=>trainSrc('hub')")
            await p.fill("#trn-hubq", "emotion")
            await p.press("#trn-hubq", "Enter")
            await p.wait_for_selector(".trn-hub", timeout=30000)
            await p.screenshot(path=str(shots / "train-datasets-hub.png"))
            got = await api(p, "/api/train/datasets/hub", "POST", {"repo": "dair-ai/emotion", "max_rows": 60})
            check(got.get("rows") == 60 and got.get("answers") == 60,
                  f"imported 60 rows of dair-ai/emotion as prompt and answer ({got.get('how', {}).get('prompt')} → {got.get('how', {}).get('response')})")
            raw = "text\n" + "\n".join(f"\"{t}\"" for t in (
                "I was charged twice.", "The export is empty.", "Do you have a dark mode?", "Refund my renewal please.",
                "Search returns nothing.", "Where is your office?", "My card was declined.", "The app crashes on save.",
                "How do I invite Tom?", "Invoice has the wrong VAT."))
            r = await p.request.post(BASE + "/api/train/datasets/file?filename=inbox.csv&system=Sort+into+billing,+bug+or+other.",
                                     data=raw.encode(), headers={"Content-Type": "text/csv"})
            f = await r.json()
            check(f.get("rows") == 10 and f.get("answers") == 0, "a file of prompts with no answers was imported as 10 prompts")
            await api(p, f"/api/train/datasets/{f['id']}/label", "POST", {})
            for _ in range(60):
                cur = await api(p, f"/api/train/datasets/{f['id']}?rows=10")
                if cur["state"] == "ready":
                    break
                await asyncio.sleep(0.5)
            check(cur["answers"] == 10 and cur["sample"][0]["response"] == "billing",
                  "the teacher answered all 10, the first as 'billing'")
            await p.evaluate("()=>trainLoad()")
            await p.wait_for_timeout(600)
            await p.evaluate(f"()=>trainOpenDs('{f['id']}')")
            await p.wait_for_selector(".trn-ds .trn-open", timeout=15000)
            await p.evaluate("()=>document.querySelector('.trn-ds .trn-open').scrollIntoView({block:'center'})")
            await p.wait_for_timeout(300)
            await p.screenshot(path=str(shots / "train-datasets.png"))

            print("5. The gate: an agent that asks to train is asked, an outsider is refused")
            mine = await api(p, "/api/policy/trace", "POST", {"tool": "train_autopilot"})
            check(mine.get("action") == "model.train" and mine.get("effect") == "ask",
                  f"your agent starting a run is its own action and is asked first ({mine.get('action')}, {mine.get('effect')})")
            app = await api(p, "/api/policy/trace", "POST", {"tool": "train_autopilot", "principal_kind": "app", "principal_id": "x"})
            check(app.get("effect") == "deny", f"an app asking for one is refused ({app.get('effect')}, {app.get('rule')})")
            ledger = await api(p, "/api/audit?limit=400")
            acts = {r.get("action") for r in ledger.get("entries", [])}
            check({"train.start", "train.teach", "train.import"} <= acts,
                  f"the ledger has the run, the teaching and the import ({sorted(a for a in acts if a and a.startswith('train'))})")
            check(not errs, "no page errors" + (": " + "; ".join(errs[:3]) if errs else ""))

            print("6. A phone")
            pc = await br.new_context(**phone)
            q = await pc.new_page()
            qerrs = []
            q.on("pageerror", lambda e: qerrs.append(str(e)))
            await desk(q)
            await train_app(q, big=False)
            await q.screenshot(path=str(shots / "train-make-phone.png"))
            await q.evaluate(f"()=>trainOpenModel('{m['id']}')")
            await q.wait_for_selector("#trn-try", timeout=15000)
            await q.wait_for_timeout(500)
            await q.screenshot(path=str(shots / "train-model-phone.png"))
            small = await q.evaluate("""()=>[...document.querySelectorAll('.trn button')].filter(b=>b.offsetParent&&!b.disabled)
                .map(b=>{const r=b.getBoundingClientRect();return [b.textContent.trim().slice(0,18),Math.round(r.width),Math.round(r.height),Math.round(r.right)]})
                .filter(x=>x[2]<36||x[3]>391)""")
            check(not small, "every button on the phone is at least 36px tall and on the screen" + (f": {small[:5]}" if small else ""))
            over = await q.evaluate("()=>{const e=document.querySelector('.trn-pane');return e.scrollWidth-e.clientWidth}")
            check(over <= 1, f"the page does not scroll sideways on a phone ({over}px)")
            await q.evaluate("()=>trainTab('runs')")
            await q.wait_for_selector(".trn-chart svg", timeout=15000)
            await q.wait_for_timeout(400)
            await q.screenshot(path=str(shots / "train-job-phone.png"))
            await q.evaluate("()=>document.querySelector('.trn-ex').scrollIntoView({block:'start'})")
            await q.wait_for_timeout(300)
            await q.screenshot(path=str(shots / "train-examples-phone.png"))
            check(not qerrs, "no page errors on the phone" + (": " + "; ".join(qerrs[:3]) if qerrs else ""))
            await pc.close()
            await c.close()
            await br.close()
            return m

    m = {}
    try:
        if not up(BASE + "/api/users/who"):
            raise RuntimeError("the server did not start: " + (work / "server.log").read_text()[-800:])
        m = asyncio.run(run())

        print("7. The terminal, with the server stopped")
        stop(srv)
        srv = None
        out = []
        for cmd in (["train", "status"], ["train", "datasets"], ["train", "models"],
                    ["train", "examples", m["id"], "--count", "3"],
                    ["train", "try", m["id"], "The dashboard shows a blank page since the update."]):
            r = subprocess.run([PY, "-m", "agentos"] + cmd, env=env, cwd=ROOT, capture_output=True, text=True, timeout=300)
            out.append("$ bento " + " ".join(f'"{c}"' if " " in c else c for c in cmd) + "\n" + r.stdout + r.stderr)
        text = "\n".join(out)
        (shots / "terminal-bento-train.txt").write_text(text)
        check("learned" in text and "'bug'" in text, "bento train reads the same model with the server down, and it answers 'bug'")

        print("8. A machine where training is not installed")
        env2 = {k: v for k, v in env.items() if k != "AGENTOS_TRAIN_PYTHON"}
        env2["AGENTOS_TRAIN_DIR"] = str(work / "no-stack")
        srv = serve(env2)
        if not up(BASE + "/api/users/who"):
            raise RuntimeError("the second server did not start")

        async def bare():
            from playwright.async_api import async_playwright
            async with async_playwright() as pw:
                br = await pw.chromium.launch()
                c = await br.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2, reduced_motion="reduce")
                p = await c.new_page()
                await desk(p)
                await train_app(p)
                check("isn't installed" in await p.inner_text(".trn-need"), "the page says training isn't installed, with Install")
                await p.fill("#trn-goal", GOAL)
                await p.click("text=Plan it")
                await p.wait_for_selector(".trn-plan", timeout=30000)
                check(await p.is_disabled("text=Make it"), "a plan can be drawn up, and Make it is greyed until training is installed")
                await p.screenshot(path=str(shots / "train-not-installed.png"))
                r = await p.request.post(BASE + "/api/train/jobs", data={"dataset": "000000000000"})
                check(r.status == 400 and "not installed" in (await r.json())["error"], "starting a training is refused in a sentence")
                await br.close()
        asyncio.run(bare())
        r = subprocess.run([PY, "-m", "agentos", "train", "status"], env=env2, cwd=ROOT, capture_output=True, text=True)
        with open(shots / "terminal-bento-train.txt", "a") as fh:
            fh.write("\n# on a machine where training is not installed\n$ bento train status\n" + r.stdout)
    finally:
        if srv:
            stop(srv)
        stop(teacher)
    print("\n" + ("ALL GOOD" if not bad else f"{len(bad)} FAILED:\n  " + "\n  ".join(bad)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
