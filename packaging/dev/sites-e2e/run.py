"""A mission works on a site you are signed in to, and asks your phone for what only you can do.

    .venv/bin/python packaging/dev/sites-e2e/run.py WORKDIR

A real `bento serve` on a throwaway home, the real shared Chromium, and stand-ins (stand_ins.py)
for a social site (Postly: a code sign-in, a post form), the brain and Telegram. Nobody is at a
screen, as for a mission on its schedule. The run installs the catalogue's "Run my social account"
mission in "show me each post first" mode and starts it, then plays the person on the phone:

  1. the site wants a sign-in code: the owner's Telegram is asked, with a picture of the page
  2. the code is sent in the chat: it goes into the page, never into the conversation
  3. the agent gives the site a picture and writes the caption: no question (the mission may act)
  4. it presses Share: that posts as you, so the owner's Telegram gets an approval card
  5. Allow: the post is on the site, and the site is in the list of signed-in sites

Then it photographs Settings → Accounts → Websites and the mission form's consent at 1440x900
and on a 390px phone, and writes `bento sites` as a transcript, into WORKDIR/shots.
Prints FINDINGS (empty when it all held).
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

ROOT = Path(__file__).resolve().parents[3]
PY = str(ROOT / ".venv" / "bin" / "python")
HERE = Path(__file__).resolve().parent
SERVER, SITE, BRAIN, TG = 8691, 8692, 8693, 8694
FINDINGS: list[str] = []


def check(ok, what):
    print(("  ✓ " if ok else "  ✗ ") + what, flush=True)
    if not ok:
        FINDINGS.append(what)


_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # loopback, never a proxy


def call(port, path, method="GET", body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with _DIRECT.open(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read() or b"{}")
        except ValueError:
            return {"error": str(e)}
    except OSError:
        return {}


def until(fn, what, secs=60):
    end = time.time() + secs
    while time.time() < end:
        got = fn()
        if got:
            return got
        time.sleep(0.5)
    check(False, what)
    return None


def main():
    work = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/sites-e2e")
    shutil.rmtree(work, ignore_errors=True)
    home, shots = work / "home", work / "shots"
    shots.mkdir(parents=True)
    ws = home / "work"
    ws.mkdir(parents=True)
    # the picture the post carries, already made (generate_image needs an image provider)
    shutil.copy(ROOT / "docs" / "screenshots" / "telegram-steps.png", ws / "post.png")
    (home / "config.json").write_text(json.dumps({
        "agent_name": "Bento", "setup_complete": True, "permissions_migrated": True, "autonomy": "balanced",
        "default_model": "custom/fake-1", "workspace": str(ws),
        "telegram": {"enabled": True, "bot_token": "1:T", "owner_chat_id": 5150, "status_messages": False},
        "providers": {"custom": {"enabled": True, "base_url": f"http://127.0.0.1:{BRAIN}/v1",
                                 "api_key": "", "models": ["fake-1"]}}}))
    env = {k: v for k, v in os.environ.items() if "PROXY" not in k.upper() and not k.startswith("AGENTOS_")}
    env.update(AGENTOS_HOME=str(home), AGENTOS_VAULT_KEYRING="0", NO_PROXY="127.0.0.1,localhost,.localhost",
               no_proxy="127.0.0.1,localhost,.localhost", AGENTOS_TELEGRAM_API=f"http://127.0.0.1:{TG}",
               AGENTOS_CHROMIUM="/opt/pw-browsers/chromium", AGENTOS_PORT=str(SERVER))
    subprocess.run([PY, "-c", "from agentos.memory import Store; s=Store(); "
                              "s.tg_upsert_chat(5150, 'Ada', '', 'private'); s.tg_set_allowed(5150, 1, by='the run')"],
                   env=env, cwd=ROOT, check=True)
    procs = [subprocess.Popen([PY, str(HERE / "stand_ins.py"), str(SITE), str(BRAIN), str(TG), str(work)],
                              env=env, stdout=open(work / "stand-ins.log", "w"), stderr=subprocess.STDOUT),
             subprocess.Popen([PY, "-m", "agentos", "serve", "--port", str(SERVER), "--no-browser",
                               "--if-running", "fail"], env=env, cwd=ROOT,
                              stdout=open(work / "server.log", "w"), stderr=subprocess.STDOUT)]
    sent = lambda: call(TG, "/sent")                                       # noqa: E731
    try:
        until(lambda: call(SERVER, "/api/platform").get("mode") is not None, "the server came up", 90)
        call(SERVER, "/api/pricing", "PUT", {"model": "custom/fake-1", "in": 0, "out": 0})

        print("1. The mission is installed from the catalogue, showing each post first")
        pv = call(SERVER, "/api/jobs/preview", "POST", {"recipe": "social-account", "answers": {
            "site": "postly.localhost", "about": "Bento, an AI desktop you own. Friendly and plain.",
            "publish": "ask", "deliver": "report"}})
        site = (pv.get("sites") or [{}])[0]
        check(site.get("site") == "postly.localhost" and site.get("signed_in") is False,
              "the consent says postly.localhost is not signed in yet")
        check("asks you first" in (site.get("words") or ""), "and that every post asks you first")
        got = call(SERVER, "/api/jobs", "POST", {"recipe": "social-account", "answers": {
            "site": "postly.localhost", "about": "Bento, an AI desktop you own. Friendly and plain.",
            "publish": "ask", "deliver": "report"}})
        name = ((got.get("flow") or {}).get("name")) or ""
        check(bool(name), f"installed as {name or 'nothing'}")
        grants = call(SERVER, "/api/grants")
        rows = grants if isinstance(grants, list) else grants.get("grants") or []
        acts = {(g.get("action"), g.get("resource")) for g in rows if g.get("principal_id") == "operator"}
        check(("browser.act", "site:postly.localhost") in acts and
              not any(a == "browser.commit" for a, _ in acts), "the roster may act on Postly, and may not post on its own")

        print("2. It runs with nobody at a screen")
        call(SERVER, f"/api/jobs/{name}/run", "POST", {})
        wall = until(lambda: next((m for m in sent() if m["method"] == "sendPhoto"), None),
                     "the sign-in code is asked on the owner's Telegram", 120)
        if wall:
            check("postly.localhost" in (wall.get("caption") or ""), "the chat is told which site wants it")
            check("code" in (wall.get("caption") or "").lower(), "and that it wants a code")

        print("3. The code goes in from the phone")
        call(TG, "/inject", "POST", {"text": "481516"})
        until(lambda: any("Carrying on" in (m.get("text") or "") or "Typed into" in (m.get("text") or "")
                          for m in sent()), "the phone hears the code went into the page", 60)

        print("4. It gives the site a picture and a caption, then presses Share: that asks")
        card = until(lambda: next((m for m in sent() if m["method"] == "sendMessage" and
                                   any(str(b.get("callback_data", "")).startswith("ap:")
                                       for r in ((m.get("reply_markup") or {}).get("inline_keyboard") or [])
                                       for b in r)), None), "an approval card reaches the phone", 120)
        allow = ""
        if card:
            text = card.get("text") or ""
            check("Share" in text and "postly.localhost" in text, "the card says it presses Share on Postly")
            check("Day 8" in text, "and quotes the caption it is posting")
            allow = next(b["callback_data"] for r in card["reply_markup"]["inline_keyboard"] for b in r
                         if str(b.get("callback_data", "")).endswith(":1"))
        posts = call(SITE, "/api/posts")
        check(len(posts) == 1, "nothing is posted before the yes")

        print("5. Allow")
        if allow:
            call(TG, "/inject", "POST", {"tap": allow, "label": "Allow once"})
        posted = until(lambda: next((p for p in call(SITE, "/api/posts") if p["at"] == "today"), None),
                       "the post is on the site after the yes", 90)
        if posted:
            check(posted["caption"].startswith("Day 8") and posted["picture"] > 1000,
                  "with the caption and the picture")
        sites = call(SERVER, "/api/sites").get("sites") or []
        check(any(s["site"] == "postly.localhost" for s in sites), "postly.localhost is in the signed-in sites")
        calls = call(BRAIN, "/calls")
        check(not any(c.get("args") and "481516" in json.dumps(c["args"]) for c in calls),
              "the code never reached the brain")

        (work / "telegram.json").write_text(json.dumps(sent(), indent=1, ensure_ascii=False))
        (work / "brain.json").write_text(json.dumps(call(BRAIN, "/calls"), indent=1))
        print("6. Pictures")
        try:
            asyncio.run(_shots(shots, sent()))
        except Exception as e:
            check(False, f"the pictures were taken ({type(e).__name__}: {str(e)[:160]})")
        cli = subprocess.run([PY, "-m", "agentos", "sites"], env=env, cwd=ROOT, capture_output=True, text=True)
        (shots / "terminal-bento-sites.txt").write_text("$ bento sites\n" + cli.stdout + cli.stderr)
        check("postly.localhost" in cli.stdout, "`bento sites` lists it")
        (work / "telegram.json").write_text(json.dumps(sent(), indent=1, ensure_ascii=False))
    finally:
        for p in procs:
            p.terminate()
    print("FINDINGS:", json.dumps(FINDINGS))
    return 1 if FINDINGS else 0


async def _shots(shots: Path, sent: list):
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        for tag, vp, scale, mobile in (("wide", {"width": 1440, "height": 900}, 1, False),
                                       ("phone", {"width": 390, "height": 844}, 2, True)):
            c = await b.new_context(viewport=vp, device_scale_factor=scale, is_mobile=mobile, has_touch=mobile)
            p = await c.new_page()
            await p.goto(f"http://127.0.0.1:{SERVER}/")
            await p.wait_for_function("typeof openApp==='function'")
            await p.wait_for_timeout(2500)
            await p.evaluate("()=>placeSettings('accounts','Websites')()")
            try:
                await p.wait_for_selector("#site-list .pgroup", timeout=15000)
            except Exception:
                await p.screenshot(path=str(shots / f"debug-{tag}-settings.png"))
                print("   debug:", await p.evaluate("()=>({list:!!document.getElementById('site-list'),html:(document.getElementById('site-list')||{}).innerHTML?.slice(0,300),tabs:[...document.querySelectorAll('.prefs-side [data-t]')].map(e=>e.dataset.t).join(',')})"))
                raise
            await p.wait_for_timeout(900)
            await p.evaluate("()=>{const e=document.querySelector('#site-list');e&&e.scrollIntoView({block:'start'})}")
            await p.wait_for_timeout(500)
            await p.screenshot(path=str(shots / f"{tag}-settings-websites.png"))
            # the mission form, its consent saying what it may do on a site
            await p.evaluate("()=>{closeWin&&WM&&[...WM.wins.values()].forEach(w=>closeWin(w));openApp('jobs')}")
            await p.wait_for_timeout(1500)
            opened = await p.evaluate("""()=>{const c=[...document.querySelectorAll('[data-recipe],[data-id],.job-card,.catcard')]
              .find(e=>/Run my social account/.test(e.textContent||''));if(!c)return false;c.click();return true}""")
            if opened:
                await p.wait_for_selector("#jf-site", timeout=8000)
                await p.fill("#jf-site", "linkedin.com")
                await p.fill("#jf-about", "Bento, an AI desktop you own.")
                await p.wait_for_timeout(1500)
                await p.evaluate("()=>{const e=document.getElementById('jf-consent');e&&e.scrollIntoView({block:'center'})}")
                await p.wait_for_timeout(400)
                await p.screenshot(path=str(shots / f"{tag}-mission-consent.png"))
            await c.close()
        # what the phone received, drawn as the chat it is
        rows = []
        for m in sent:
            if m["method"] == "sendPhoto":
                rows.append(("bot", m.get("caption") or "", m.get("photo")))
            elif m["method"] in ("sendMessage",) and (m.get("text") or "").strip():
                rows.append(("bot", m["text"], None))
            elif m["method"] == "from_person":
                rows.append(("me", m["text"], None))
            elif m["method"] == "tap":
                rows.append(("me", "▸ " + m["text"], None))
        import html
        body = "".join(f'<div class="b {w}">' + (f'<img src="../{ph}">' if ph else "") +
                       f'<div>{html.escape(t)}</div></div>' for w, t, ph in rows)
        page = shots / "telegram.html"
        page.write_text(f"""<!doctype html><meta charset=utf-8><style>body{{margin:0;background:#d9e7d0;
font:15px/1.4 system-ui}}header{{background:#517da2;color:#fff;padding:14px 16px;font-weight:600}}
main{{max-width:560px;margin:0 auto;padding:12px 10px 40px;display:flex;flex-direction:column;gap:8px}}
.b{{white-space:pre-wrap;padding:8px 10px;border-radius:12px;max-width:86%;box-shadow:0 1px 1px rgba(0,0,0,.12)}}
.me{{align-self:flex-end;background:#effdde}}.bot{{align-self:flex-start;background:#fff}}
img{{max-width:100%;border-radius:8px;display:block;margin-bottom:6px}}</style>
<header>Bento · a mission on its schedule</header><main>{body}</main>""")
        c = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        p = await c.new_page()
        await p.goto(page.as_uri())
        await p.screenshot(path=str(shots / "phone-telegram.png"), full_page=True)
        await c.close()
        await b.close()


if __name__ == "__main__":
    sys.exit(main())
