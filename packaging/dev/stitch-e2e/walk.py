"""End-to-end walk of the stitched experience: chat -> agents (PDP) -> apps -> missions.

    .venv/bin/python packaging/dev/stitch-e2e/walk.py      # screenshots in /tmp/stitch-e2e-shots

One person on a machine WITH accounts (the case every seam broke on), a stand-in brain
that calls the real tools (fake_brain.py), and Chromium. It ends by printing FINDINGS,
which is an empty list when everything is stitched. tests/test_stitched_walk.py pins
what it found the first time.

A real server, a real browser, the scripted brain in fake_brain.py. Every step checks
what the person sees AND what the server recorded, and prints FINDING lines for seams.
"""
import asyncio, json, os, shutil, subprocess, sys, time, urllib.request
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = str(Path(__file__).resolve().parents[3])
SP = os.path.dirname(os.path.abspath(__file__)) + "/"
OUT = os.environ.get("OUT_DIR", "/tmp/stitch-e2e-shots") + "/"; Path(OUT).mkdir(parents=True, exist_ok=True)
for f in Path(OUT).glob("*.png"): f.unlink()
PORT, BRAIN = int(os.environ.get("PORT", 8611)), 9411
HOME = Path(os.environ.get("HOME_DIR", "/tmp/e2e-home"))
shutil.rmtree(HOME, ignore_errors=True); HOME.mkdir(parents=True)
(HOME / "config.json").write_text(json.dumps({
    "agent_name": "Aria", "setup_complete": True, "permissions_migrated": True,
    "default_model": "custom/fake-1", "workspace": str(HOME / "work"),
    "providers": {"custom": {"enabled": True, "base_url": f"http://127.0.0.1:{BRAIN}/v1", "api_key": "", "models": ["fake-1"]}}}))
env = {k: v for k, v in os.environ.items() if "PROXY" not in k.upper()}
env.update(AGENTOS_HOME=str(HOME), AGENTOS_VAULT_KEYRING="0", NO_PROXY="127.0.0.1,localhost")
subprocess.run([ROOT + "/.venv/bin/python", "-c",
                "from agentos import users; users.create('piyush2','correct horse battery staple 9','admin')"],
               env=env, check=True, cwd=ROOT)
brain = subprocess.Popen([ROOT + "/.venv/bin/python", SP + "fake_brain.py", str(BRAIN)], env=env,
                         stdout=open(OUT + "brain.log", "w"), stderr=subprocess.STDOUT)
srv = subprocess.Popen([ROOT + "/.venv/bin/python", "-m", "agentos", "serve", "--port", str(PORT), "--no-browser",
                        "--if-running", "fail"], env=env, cwd=ROOT, stdout=open(OUT + "server.log", "w"),
                       stderr=subprocess.STDOUT)
for _ in range(100):
    try: urllib.request.urlopen(f"http://127.0.0.1:{PORT}/login", timeout=2); break
    except Exception: time.sleep(0.5)

FIND = []
def finding(s):
    FIND.append(s); print("FINDING:", s, flush=True)
def ok(s): print("ok:", s, flush=True)


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        c = await b.new_context(viewport={"width": 1440, "height": 900})
        p = await c.new_page(); errs = []
        p.on("pageerror", lambda e: errs.append(str(e)))
        r = await p.request.post(f"http://127.0.0.1:{PORT}/api/users/login",
                                 data={"name": "piyush2", "password": "correct horse battery staple 9"})
        print("login", r.status)
        base = f"http://127.0.0.1:{PORT}"

        async def api(path, method="GET", body=None):
            if method == "GET":
                r = await p.request.get(base + path)
            else:
                r = await p.request.fetch(base + path, method=method, data=body)
            try: return await r.json()
            except Exception: return {"status": r.status, "text": (await r.text())[:200]}

        async def price():
            await api("/api/pricing", "PUT", {"model": "custom/fake-1", "in": 0, "out": 0})
        await price()
        await p.goto(base + "/"); await p.wait_for_timeout(5000)

        async def shot(name, sel=None):
            if sel:
                el = await p.query_selector(sel)
                if el: return await el.screenshot(path=OUT + name + ".png")
            await p.screenshot(path=OUT + name + ".png")

        async def idle(ms=20000):
            t0 = time.time()
            while time.time() - t0 < ms / 1000:
                n = await p.evaluate("()=>RUNNING.size")
                if n == 0:
                    await p.wait_for_timeout(600)
                    if await p.evaluate("()=>RUNNING.size") == 0: return True
                await p.wait_for_timeout(300)
            return False

        async def answer_card(allow, wait=6.0, tag=""):
            """Click Allow/Deny on the approval card that is on top of the screen, as a
            person would. Returns its text, or None if no card became reachable."""
            t0 = time.time()
            while time.time() - t0 < wait:
                idx = await p.evaluate("""()=>{const all=[...document.querySelectorAll('.approval')];
                  return all.findIndex(b=>{const a=b.querySelector('button.allow');return a&&!a.disabled&&approvalShown(b)})}""")
                if idx >= 0:
                    box = p.locator(".approval").nth(idx)
                    txt = await box.inner_text()
                    if tag: await shot("card-" + tag)
                    await box.locator("button.allow" if allow else ".btns button.deny:not(.always)").click()
                    return txt
                await p.wait_for_timeout(300)
            return None

        async def say(text, approve=None):
            """Type into Chat, answer at most one approval card, wait for the turn to end."""
            await p.evaluate("()=>openApp('chat')"); await p.wait_for_timeout(500)
            n0 = await p.evaluate("()=>document.querySelectorAll('#feed .msg.user').length")
            await p.fill("#input", text); await p.keyboard.press("Enter")
            await p.wait_for_timeout(800)
            n1 = await p.evaluate("()=>document.querySelectorAll('#feed .msg.user').length")
            if n1 <= n0:
                diag = await p.evaluate("()=>({conv:currentConv,running:RUNNING.size,busy:running,queues:JSON.stringify(QUEUES).slice(0,300),feed:document.getElementById('feed').innerText.slice(-300),wins:[...WM.wins.keys()],sock:ws?ws.readyState:null,sameInput:input===document.getElementById('input'),sameFeed:feed===document.getElementById('feed')})")
                finding(f"chat: '{text[:30]}' was typed but no message was sent: {diag}")
            seen = None
            t0 = time.time()
            while time.time() - t0 < 25:
                await p.wait_for_timeout(400)
                if approve is not None and seen is None:
                    seen = await answer_card(approve, wait=0.5, tag=text[:20].replace(" ", "_"))
                if await p.evaluate("()=>RUNNING.size") == 0 and time.time() - t0 > 2:
                    break
            await idle()
            return seen

        async def ledger(principal_prefix, n=50):
            rows = await api(f"/api/audit?limit={n}")
            rows = rows.get("entries", rows) if isinstance(rows, dict) else rows
            return [r for r in rows if str(r.get("principal_kind", "")).startswith(principal_prefix)]

        # ---------------- 1. chat asks for a risky step: the PDP card in chat
        seen = await say("Please save a note for me", approve=True)
        if not seen: finding("1: no approval card appeared in Chat for write_file")
        else: ok("1: approval card: " + seen.replace("\n", " | ")[:160])
        note = HOME / "users"
        hits = list(HOME.rglob("e2e-note.md"))
        ok(f"1: file written at {hits[0]}") if hits else finding("1: the approved note was not written")
        rows = await api("/api/audit?limit=20")
        for r in (rows.get("entries") or [])[:6]:
            print("   audit:", r.get("principal_kind"), r.get("action"), r.get("resource"), r.get("effect"), r.get("rule"), r.get("outcome"))
        await shot("01-chat-note")

        # ---------------- 2. hand-over to a specialist
        seen = await say("Hand this to the researcher please", approve=True)
        ok("2: hand-over card: " + (seen or "none").replace("\n", " | ")[:160])
        runs = await api("/api/fabric/runs?limit=5")
        print("   runs:", json.dumps(runs)[:400])
        msgs = await p.evaluate("()=>[...document.querySelectorAll('#feed .msg')].slice(-3).map(m=>m.innerText.slice(0,200))")
        print("   last msgs:", msgs)
        await shot("02-handover")

        # ---------------- 3. build an app from chat, follow the handoff
        await say("Build me a volume tracker app", approve=True)
        chip = await p.query_selector(".handoff .ho-go")
        if not chip: finding("3: no 'Open in App Studio' handoff after create_app")
        else:
            ok("3: handoff chip: " + await p.evaluate("()=>document.querySelector('.handoff').innerText"))
            await shot("03-chat-app-handoff")
            await chip.click(); await p.wait_for_timeout(2500)
            sel = await p.evaluate("()=>typeof STUDIO!=='undefined'?STUDIO.sel:null")
            apps = await api("/api/apps")
            apps = apps.get("apps", apps) if isinstance(apps, dict) else apps
            app = next((a for a in apps if a.get("name") == "Volume Tracker"), None)
            if not app: finding("3: app Volume Tracker not in /api/apps")
            elif sel != app["id"]: finding(f"3: Studio opened but selected {sel!r}, not the app {app['id']}")
            else: ok("3: Studio opened on the app")
            convs = await api(f"/api/apps/{app['id']}/conversations") if app else {}
            print("   app conversations:", json.dumps(convs)[:300])
            await shot("03b-studio")
            # run the app and press its buttons: app principal through the PDP
            await p.evaluate(f"()=>openApp('ua_{app['id']}')")
            await p.wait_for_timeout(2500)
            fr = None
            for f in p.frames:
                if await f.query_selector("#fetch") if f != p.main_frame else None:
                    fr = f
            if not fr: finding("3: could not find the running app's frame")
            else:
                for k in ("fetch", "ai", "save"):
                    await fr.click("#" + k); await p.wait_for_timeout(2500)
                    txt = await answer_card(k == "ai", wait=4.0, tag="app-" + k)
                    if txt:
                        ok(f"3: app '{k}' raised a card ({'allowed' if k == 'ai' else 'denied'}): " + txt.replace("\n", " | ")[:160])
                        await p.wait_for_timeout(1500)
                    out = await fr.inner_text("#out")
                    print(f"   app {k}: {out[:200]}")
                await shot("03d-app")
            arows = await ledger("app")
            print("   app ledger rows:", [(r.get('action'), r.get('resource'), r.get('effect'), r.get('rule')) for r in arows][:8])
            if not arows: finding("3: no ledger rows for the app principal")

        # ---------------- 4. schedule for the app from chat
        await p.evaluate("()=>{[...WM.wins.values()].forEach(w=>closeWin(w))}")
        seen = await say("Please schedule a refresh of it every 10 minutes", approve=True)
        ok("4: schedule card: " + (seen or "none").replace("\n", " | ")[:160])
        chips = await p.evaluate("()=>[...document.querySelectorAll('.handoff')].map(h=>h.innerText)")
        print("   handoffs:", chips)
        sch = await api("/api/tasks")
        print("   schedules:", json.dumps(sch)[:400])
        await shot("04-schedule")

        # ---------------- 5. a mission from chat, enable, run, history, brief, ledger
        await say("Make a mission for morning solar news", approve=True)
        chip = await p.query_selector(".handoff:last-of-type .ho-go")
        hs = await p.evaluate("()=>[...document.querySelectorAll('.handoff')].map(h=>h.innerText)")
        print("   handoffs:", hs)
        if not any("solar-news" in h for h in hs): finding("5: no Open in Missions handoff for the drafted mission")
        btns = await p.query_selector_all(".handoff .ho-go")
        if btns:
            await btns[-1].click(); await p.wait_for_timeout(2500)
            await shot("05-missions-after-handoff")
            focus = await p.evaluate("()=>({focus:typeof FLOW_FOCUS!=='undefined'?FLOW_FOCUS:null, tab:typeof fabTab!=='undefined'?fabTab:null, wins:[...WM.wins.keys()],sock:ws?ws.readyState:null,sameInput:input===document.getElementById('input'),sameFeed:feed===document.getElementById('feed')})")
            print("   after mission handoff:", focus)
        flows = await api("/api/flows")
        fl = flows.get("flows", flows) if isinstance(flows, dict) else flows
        f = next((x for x in fl if x.get("name") == "solar-news"), None)
        if not f: finding("5: the drafted mission is not in /api/flows")
        else:
            ok(f"5: drafted, enabled={f.get('enabled')}")
            pre = await api(f"/api/flows/solar-news/enable", "POST", {"enabled": True})
            print("   enable:", json.dumps(pre)[:300])
            g = await api("/api/grants")
            g = g.get("grants", g) if isinstance(g, dict) else g
            dg = [x for x in g if str(x.get("source_ref", "")) == "flow:solar-news"]
            ok(f"5: {len(dg)} definition grants for flow:solar-news") if dg else finding("5: enabling wrote no definition grants")
            run = await api("/api/flows/solar-news/run", "POST", {})
            print("   run:", json.dumps(run)[:300])
            for _ in range(40):
                await p.wait_for_timeout(500)
                rs = await api("/api/fabric/runs?limit=10")
                rs = rs.get("runs", rs) if isinstance(rs, dict) else rs
                top = [x for x in rs if x.get("ref") == "solar-news"]
                if top and top[0].get("status") not in ("running", "parked"): break
            print("   flow runs:", [(x.get('ref'), x.get('status'), x.get('kind')) for x in rs][:6])
            hist = await api("/api/missions/history?limit=10")
            print("   history:", json.dumps(hist)[:500])
            br = await api("/api/brief")
            print("   brief:", json.dumps(br)[:400])
            frows = await ledger("flow")
            print("   flow ledger:", [(r.get('principal_id'), r.get('action'), r.get('effect'), r.get('outcome')) for r in frows][:6])
            srows = await ledger("subagent")
            print("   specialist ledger:", [(r.get('principal_id'), r.get('action'), r.get('resource'), r.get('effect'), r.get('outcome')) for r in srows][:6])

        # ---------------- 6. the views that should tell the story
        await p.evaluate("()=>{[...WM.wins.values()].forEach(w=>closeWin(w))}")
        for app_id, name in (("audit", "06-permissions-ledger"), ("jobs", "07-missions-run"), ("brief", "08-brief")):
            await p.evaluate(f"()=>openApp('{app_id}')"); await p.wait_for_timeout(2500)
            await shot(name)
            await p.evaluate("()=>{[...WM.wins.values()].forEach(w=>closeWin(w))}")
        print("page errors:", errs)
        print("FINDINGS:", json.dumps(FIND, indent=1))
        await b.close()

try:
    asyncio.run(main())
finally:
    srv.terminate(); brain.terminate()
