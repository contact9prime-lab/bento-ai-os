"""The sample apps, live: a real server on a throwaway home, each app installed from its
package, used in a real browser, and photographed.

    OUT_DIR=/tmp/sample-apps-shots .venv/bin/python packaging/dev/sample-apps-e2e/run.py

The AI is brain.py, a stand-in that answers each app's prompts with a fixed reply, so the
run needs no key; the apps parse it exactly as they would a real model's answer. Focus
Timer is installed through the desktop's own Store → Import consent screen; the others
through the same two calls that screen makes. Prints FINDING lines for anything wrong.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[3]
SP = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from agentos import sampleapps  # noqa: E402

OUT = Path(os.environ.get("OUT_DIR", "/tmp/sample-apps-shots"))
OUT.mkdir(parents=True, exist_ok=True)
for f in OUT.glob("*.png"):
    f.unlink()
PORT, BRAIN = int(os.environ.get("PORT", 8631)), 9431
HOME = Path(os.environ.get("HOME_DIR", "/tmp/sample-apps-home"))
shutil.rmtree(HOME, ignore_errors=True)
HOME.mkdir(parents=True)
(HOME / "config.json").write_text(json.dumps({
    "agent_name": "Bento", "setup_complete": True, "permissions_migrated": True,
    "default_model": "custom/stand-in", "pricing_skip": ["custom/stand-in"], "workspace": str(HOME / "work"),
    "providers": {"custom": {"enabled": True, "base_url": f"http://127.0.0.1:{BRAIN}/v1", "api_key": "",
                             "models": ["stand-in"]}}}))
env = {k: v for k, v in os.environ.items() if "PROXY" not in k.upper()}
env.update(AGENTOS_HOME=str(HOME), AGENTOS_VAULT_KEYRING="0", NO_PROXY="127.0.0.1,localhost")
PY = str(ROOT / ".venv/bin/python")
brain = subprocess.Popen([PY, str(SP / "brain.py"), str(BRAIN)], env=env,
                         stdout=open(OUT / "brain.log", "w"), stderr=subprocess.STDOUT)
srv = subprocess.Popen([PY, "-m", "agentos", "serve", "--port", str(PORT), "--no-browser", "--if-running", "fail"],
                       env=env, cwd=str(ROOT), stdout=open(OUT / "server.log", "w"), stderr=subprocess.STDOUT)
BASE = f"http://127.0.0.1:{PORT}"
for _ in range(120):
    try:
        urllib.request.urlopen(BASE + "/login", timeout=2)
        break
    except Exception:
        time.sleep(0.5)

FIND = []


def finding(s):
    FIND.append(s)
    print("FINDING:", s, flush=True)


def ok(s):
    print("ok:", s, flush=True)


async def wait_text(page, sel, n=40, timeout=20):
    """Wait until an element holds at least n characters (a stream finished arriving)."""
    t0 = time.time()
    last = ""
    while time.time() - t0 < timeout:
        last = (await page.locator(sel).first.inner_text()).strip()
        if len(last) >= n and "spin" not in (await page.locator(sel).first.inner_html()):
            await asyncio.sleep(0.4)
            again = (await page.locator(sel).first.inner_text()).strip()
            if again == last:
                return last
        await asyncio.sleep(0.25)
    return last


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        desk = await b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        d = await desk.new_page()
        errs = []
        d.on("pageerror", lambda e: errs.append(("desktop", str(e))))
        await d.goto(BASE + "/")
        await d.wait_for_function("typeof storeImportStage === 'function'", timeout=30000)
        await asyncio.sleep(2)

        # 1. Focus Sessions through the desktop's own Store → Import consent screen
        pkg = json.loads(sampleapps.path_of("focus-sessions").read_text())
        await d.evaluate("p => storeImportStage({package: p})", pkg)
        await d.wait_for_selector(".c-ok", timeout=15000)
        await asyncio.sleep(0.6)
        await d.screenshot(path=str(OUT / "import-consent.png"))
        await d.click(".c-ok")
        await asyncio.sleep(1.5)
        ids = {}

        def api(path, body=None):
            req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Content-Type": "application/json"},
                                         method="POST" if body is not None else "GET")
            return json.loads(urllib.request.urlopen(req, timeout=30).read())

        apps = {a["name"]: a["id"] for a in api("/api/apps")["apps"]}
        if "Focus Sessions" in apps:
            ids["focus-sessions"] = apps["Focus Sessions"]
            ok("Focus Sessions installed through the consent screen")
        else:
            finding("Focus Sessions did not install through the consent screen")
        # 2. the others through the same two calls the screen makes
        for a in sampleapps.APPS[1:]:
            p = json.loads(sampleapps.path_of(a["slug"]).read_text())
            st = api("/api/apps/import", {"package": p})
            if st.get("security") != "pass" or st.get("signature_status") not in ("unsigned", "verified"):
                finding(f"{a['name']}: import says {st.get('security')} / {st.get('signature_status')}")
            done = api(f"/api/apps/import/{st['install_id']}/confirm", {})
            ids[a["slug"]] = done["id"]
            ok(f"{a['name']} installed")
        grants = api("/api/grants")
        rows = grants if isinstance(grants, list) else grants.get("grants", [])
        have = {(g.get("principal_id"), g.get("action")) for g in rows}
        for slug, aid in ids.items():
            if (aid, "app.data.write") not in have:
                finding(f"{slug}: no app.data.write grant after install")

        # 3. each app, used
        ctx = await b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        # in Bento an app is always a frame the width of its window, so a phone is a 390px frame
        phone = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, has_touch=True)

        async def open_app(c, slug, q=""):
            pg = await c.new_page()
            pg.on("pageerror", lambda e, s=slug: errs.append((s, str(e))))
            await pg.goto(f"{BASE}/api/apps/{ids[slug]}/page{q}")
            await pg.wait_for_load_state("networkidle")
            await asyncio.sleep(0.6)
            return pg

        async def click_text(pg, text):
            await pg.get_by_text(text, exact=False).first.click()
            await asyncio.sleep(0.5)

        # Focus Sessions
        pg = await open_app(ctx, "focus-sessions")
        await click_text(pg, "Try it with an example")
        await pg.fill("#task", "Draft the quarterly update")
        await pg.click("#plan-btn")
        plan = await wait_text(pg, "#plan", 80)
        if "Done looks like" not in plan:
            finding("Focus Sessions: the session plan did not stream in: " + plan[:80])
        await pg.click("#review-btn")
        rev = await wait_text(pg, "#review-box", 80)
        if "best day" not in rev:
            finding("Focus Sessions: the look back did not stream in")
        await pg.click("#go")
        await asyncio.sleep(2.2)
        t = await pg.inner_text("#time")
        if t in ("25:00", ""):
            finding("Focus Sessions: the clock did not move after Start: " + t)
        await pg.screenshot(path=str(OUT / "focus-sessions-desktop.png"))
        await pg.close()

        # Habit Tracker
        pg = await open_app(ctx, "habit-tracker")
        await click_text(pg, "Try it with an example")
        before = await pg.inner_text("#k-today")
        await pg.locator(".ht-day.today").first.click()
        await asyncio.sleep(0.5)
        after = await pg.inner_text("#k-today")
        if before == after:
            finding(f"Habit Tracker: ticking today did not change the count ({before})")
        await pg.click("#coach-btn")
        coach = await wait_text(pg, "#coach", 80)
        if "One small change" not in coach:
            finding("Habit Tracker: the coach did not stream in")
        await pg.screenshot(path=str(OUT / "habit-tracker-desktop.png"))
        await pg.close()

        # Kanban Board
        pg = await open_app(ctx, "kanban-board")
        await click_text(pg, "try an example board")
        await pg.fill("#quick", "Send Sam the invoice by Friday, it's urgent")
        await pg.press("#quick", "Enter")
        await asyncio.sleep(2)
        note = await pg.inner_text("#quick-note")
        if "Send Sam the invoice" not in note:
            finding("Kanban Board: the plain-words task was not read: " + note)
        card = pg.locator(".kb-card", has_text="Book the team offsite venue")
        await card.get_by_text("Steps").click()
        await asyncio.sleep(2)
        n = await pg.locator(".kb-card", has_text="from “Book the team offsite venue”").count()
        if n < 2:
            finding(f"Kanban Board: Steps added {n} cards")
        # drag a card to Doing
        src = pg.locator(".kb-card", has_text="Draft the launch email")
        await src.drag_to(pg.locator('.kb-col[data-col="doing"]'))
        await asyncio.sleep(0.6)
        if await pg.locator('.kb-col[data-col="doing"] .kb-card', has_text="Draft the launch email").count() != 1:
            finding("Kanban Board: dragging a card to Doing did not move it")
        await pg.click("#next-btn")
        nx = await wait_text(pg, "#next", 80)
        if "signup bug" not in nx:
            finding("Kanban Board: What next did not stream in")
        await pg.screenshot(path=str(OUT / "kanban-board-desktop.png"), full_page=True)
        await pg.close()

        # Meeting Notes
        pg = await open_app(ctx, "meeting-notes")
        await click_text(pg, "Try it with an example")
        await pg.click("#sum-btn")
        s = await wait_text(pg, "#sum", 120)
        if "Decisions" not in s:
            finding("Meeting Notes: the summary did not stream in")
        await asyncio.sleep(1)
        await pg.click("#pull-btn")
        await asyncio.sleep(2)
        acts = await pg.locator(".mn-act").count()
        if acts < 3:
            finding(f"Meeting Notes: Pull out actions gave {acts}")
        if (await pg.inner_text("#open-count")).strip() != str(acts):
            finding("Meeting Notes: the open actions list does not count the actions")
        await pg.screenshot(path=str(OUT / "meeting-notes-desktop.png"), full_page=True)
        await pg.close()

        # Daily Planner
        pg = await open_app(ctx, "daily-planner")
        for i, t in enumerate(["Finish the proposal draft", "Reply to the three client emails", "Plan next week's sprint"]):
            el = pg.locator(".dp-top input[type=text]").nth(i)
            await el.fill(t)
            await el.press("Tab")
            await asyncio.sleep(0.3)
        await pg.click("#draft-btn")
        await asyncio.sleep(2)
        if await pg.locator("#draft .item").count() < 4:
            finding("Daily Planner: the draft did not arrive")
        await pg.click("#keep-btn")
        await asyncio.sleep(0.6)
        nb = await pg.locator(".dp-blk").count()
        if nb < 4:
            finding(f"Daily Planner: keeping the draft left {nb} blocks")
        await pg.click("#look-btn")
        lk = await wait_text(pg, "#look", 80)
        if "Tomorrow" not in lk:
            finding("Daily Planner: the look back did not stream in")
        await pg.screenshot(path=str(OUT / "daily-planner-desktop.png"), full_page=True)
        await pg.close()

        # 4. every app again on a phone, and as a widget: the data came back after a reload
        for a in sampleapps.APPS:
            pg = await open_app(phone, a["slug"])
            body = await pg.inner_text("body")
            if "Try it with an example" in body and a["slug"] != "meeting-notes":
                finding(f"{a['name']}: the phone shows the empty state, so the data did not persist")
            wide = await pg.evaluate("document.documentElement.scrollWidth")
            if wide > 392:
                finding(f"{a['name']}: the phone page is {wide}px wide (scrolls sideways)")
            await pg.screenshot(path=str(OUT / f"{a['slug']}-phone.png"))
            await pg.close()
            for size, vw, vh in (("m", 340, 240), ("s", 260, 170)):
                wc = await b.new_context(viewport={"width": vw, "height": vh}, device_scale_factor=2)
                wp = await open_app(wc, a["slug"], f"?surface=widget&size={size}")
                if await wp.locator(".desktop-only").first.is_visible():
                    finding(f"{a['name']}: the widget shows the desktop view")
                sw = await wp.evaluate("document.documentElement.scrollWidth")
                if sw > vw + 1:
                    finding(f"{a['name']}: the {size} widget scrolls sideways ({sw}px)")
                await wp.screenshot(path=str(OUT / f"{a['slug']}-widget-{size}.png"))
                await wc.close()
            ok(f"{a['name']} on a phone and as a widget")

        # 5. one app in a Bento window on the desktop
        await d.evaluate("loadUserApps()")
        await asyncio.sleep(1)
        await d.evaluate("id => openApp('ua_' + id)", ids["kanban-board"])
        await asyncio.sleep(3)
        await d.screenshot(path=str(OUT / "kanban-board-in-bento.png"))
        # and Bento itself on a phone, with an app open the way a person opens it there
        ph = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True,
                                 has_touch=True)
        pp = await ph.new_page()
        pp.on("pageerror", lambda e: errs.append(("phone desktop", str(e))))
        await pp.goto(BASE + "/")
        await pp.wait_for_function("typeof openApp === 'function'", timeout=30000)
        await asyncio.sleep(2)
        await pp.evaluate("loadUserApps()")
        await asyncio.sleep(1)
        await pp.evaluate("id => openApp('ua_' + id)", ids["habit-tracker"])
        await asyncio.sleep(3)
        await pp.screenshot(path=str(OUT / "habit-tracker-in-bento-phone.png"))
        await b.close()

    for where, e in errs:
        finding(f"page error in {where}: {e}")
    print("\nFINDINGS:", json.dumps(FIND, indent=1) if FIND else "none")


try:
    asyncio.run(main())
finally:
    srv.terminate()
    brain.terminate()
    srv.wait(10)
sys.exit(1 if FIND else 0)
