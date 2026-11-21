"""The 0.99.0 release run: missions with nobody signed in, the phone link after a restart, provider
keys in the vault, and Shared and Isolated Tenants. A real `bento serve` on a throwaway home, a
stand-in brain that records which key it was called with, a stand-in Telegram, and Playwright.

    .venv/bin/python packaging/dev/release-e2e/run.py WORKDIR

It checks, and photographs (1440x900 and a 390px phone):
  1. the admin's provider key is in the machine's vault, never in config.json;
  2. bob's Telegram token and mail password are in his own vault, with how long each works
     while he's away (Settings → Accounts → Your secrets);
  3. after a restart with nobody signed in, bob's bot polls with his token, and a phone turn is
     answered with the machine's provider key;
  4. a step needing his signed-in-only mail password sends his own chat a link, he signs in on
     his phone, opens it for the next run, and the step carries on;
  5. eve's Isolated Tenant has none of the machine's keys, sees only its own people, and its own
     key reaches the provider.
"""
import asyncio
import html
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PY = str(ROOT / ".venv" / "bin" / "python")
PORT, BRAIN, TG = 8731, 8732, 8733
BASE = f"http://127.0.0.1:{PORT}"
PROVIDER_KEY = "sk-RELEASE-OPENAI-31337"
EVE_KEY = "sk-EVE-TENANT-4242"
BOT = "777:BOBS-BOT-TOKEN"
MAIL_PW = "BOB-MAIL-PASSWORD-8080"
PW = {"ada": "ada-password-1", "bob": "bob-password-1", "eve": "eve-password-1"}


def get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
        return json.loads(r.read() or b"{}")


def post(port, path, body):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read() or b"{}")


def serve(env, log):
    return subprocess.Popen([PY, "-m", "agentos", "serve", "--port", str(PORT), "--no-browser",
                             "--if-running", "fail"], env=env, cwd=ROOT,
                            stdout=open(log, "a"), stderr=subprocess.STDOUT)


def wait_up():
    for _ in range(160):
        try:
            urllib.request.urlopen(BASE + "/api/users/who", timeout=2)
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


def scan(home: Path, needles: list[str]) -> list[str]:
    hits = []
    for f in home.rglob("*"):
        if f.is_file() and "browser" not in f.parts:
            raw = f.read_bytes()
            hits += [f"{n} in {f.relative_to(home)}" for n in needles if n.encode() in raw]
    return hits


async def desk(p, timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if await p.evaluate("()=>typeof openApp==='function'"):
                return
        except Exception:
            pass
        await asyncio.sleep(0.4)
    raise TimeoutError("the desktop did not load")


async def sign_in(p, name, pw, goto="/login"):
    await p.goto(BASE + goto)
    await p.wait_for_selector("#who:not([hidden])", timeout=15000)
    await p.fill("#who", name)
    await p.fill("#pw", pw)
    await p.click("#go")


async def past_code(p):
    """A first sign-in shows the recovery code once: tick it and carry on."""
    try:
        await p.wait_for_selector(".code", timeout=6000)
        await p.check("#seal input[type=checkbox]")
        await p.click("#seal button:not(.ghost):not(.link)")
    except Exception:
        pass


async def until(fn, timeout=60, step=0.5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            v = fn()
            if v:
                return v
        except Exception:
            pass
        await asyncio.sleep(step)
    return None


def main():
    work = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/release-e2e")
    home, shots = work / "home", work / "shots"
    shutil.rmtree(home, ignore_errors=True)
    shots.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True)
    (home / "config.json").write_text(json.dumps({
        "agent_name": "Bento", "setup_complete": True, "permissions_migrated": True,
        "default_model": "openai/fake-1", "workspace": str(home / "work"),
        "remote": {"enabled": True},
        "providers": {"openai": {"enabled": True, "base_url": f"http://127.0.0.1:{BRAIN}/v1",
                                 "models": ["fake-1"], "api_key": ""}}}))
    env = {k: v for k, v in os.environ.items() if "PROXY" not in k.upper() and not k.startswith("AGENTOS_")}
    env.update(AGENTOS_HOME=str(home), AGENTOS_VAULT_KEYRING="0", NO_PROXY="127.0.0.1,localhost",
               AGENTOS_TELEGRAM_API=f"http://127.0.0.1:{TG}", AGENTOS_HANDOFF_BASE=f"http://127.0.0.1:{PORT}",
               AGENTOS_CHROMIUM=os.environ.get("AGENTOS_CHROMIUM", "/opt/pw-browsers/chromium"))
    stand = subprocess.Popen([PY, str(HERE / "stand_ins.py"), str(BRAIN), str(TG)], env=env,
                             stdout=open(work / "stand-ins.log", "w"), stderr=subprocess.STDOUT)
    log = work / "server.log"
    srv = serve(env, log)
    bad, notes = [], []

    def check(ok, what):
        print(("  ✓ " if ok else "  ✗ ") + what)
        if not ok:
            bad.append(what)

    async def run():
        nonlocal srv
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            br = await pw.chromium.launch()
            wide = {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 1}
            phone = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2,
                     "is_mobile": True, "has_touch": True}

            print("1. The admin's provider key goes into the machine's vault")
            ac = await br.new_context(**wide)
            a = await ac.new_page()
            await a.goto(BASE + "/")
            r = await a.request.post(BASE + "/api/users", data={"name": "ada", "password": PW["ada"]})
            check(r.ok, "ada makes the first account")
            await a.request.put(BASE + "/api/pricing", data={"model": "openai/fake-1", "in": 0, "out": 0})
            r = await a.request.put(BASE + "/api/config",
                                    data={"providers": {"openai": {"api_key": PROVIDER_KEY, "enabled": True}}})
            check(r.ok, "she saves the OpenAI key in Settings")
            text = (home / "config.json").read_text()
            check(PROVIDER_KEY not in text and "vault:provider.openai.api_key" in text,
                  "config.json holds a reference, not the key")
            check(json.loads((home / "vault.json").read_text()).get("key") == "service",
                  "the machine's vault is locked with the service key")
            got = await (await a.request.get(BASE + "/api/config")).json()
            check(got["providers"]["openai"]["api_key"] == "•••", "Settings shows only that a key is set")
            for n in ("bob",):
                await a.request.post(BASE + "/api/users", data={"name": n, "password": PW[n]})
            r = await a.request.post(BASE + "/api/users", data={"name": "eve", "password": PW["eve"],
                                                                "scope": "isolated"})
            check(r.ok and (await r.json())["user"].get("tenant"), "eve gets an Isolated Tenant of her own")

            print("2. Bob's bot token and mail password are in his own vault")
            bc = await br.new_context(**wide)
            b = await bc.new_page()
            await sign_in(b, "bob", PW["bob"])
            await past_code(b)
            await desk(b)
            await b.request.post(BASE + "/api/setup", data={})
            uid = next(u["id"] for u in json.loads((home / "users.json").read_text())["users"] if u["name"] == "bob")
            stop(srv)
            bcfg = home / "users" / uid / "config.json"
            c = json.loads(bcfg.read_text())
            c.update(default_model="openai/fake-1",
                     telegram={"enabled": True, "bot_token": BOT, "status_messages": False},
                     mail={"enabled": True, "host": "127.0.0.1", "port": 9, "user": "bob@example.com", "password": MAIL_PW,
                           "ssl": False, "last_test": {"ok": True, "at": time.time()}})
            bcfg.write_text(json.dumps(c))
            srv = serve(env, log)
            check(wait_up(), "the server comes back")
            await b.goto(BASE + "/")
            await desk(b)
            await asyncio.sleep(2)
            check(BOT not in bcfg.read_text() and MAIL_PW not in bcfg.read_text(),
                  "his config file holds references only")
            st = await (await b.request.get(BASE + "/api/seal")).json()
            names = {x["name"]: x for x in st.get("secrets") or []}
            check(names.get("telegram.bot_token", {}).get("mode") == "always",
                  "his bot works while he's away, until he revokes it")
            # bob says his mail password works only while he's signed in, from the card
            await b.evaluate("()=>placeSettings('accounts','Your secrets')()")
            await b.wait_for_selector("#seal-card select.seal-away", timeout=15000)
            await b.select_option('#seal-card select[aria-label="While you’re away: Mail password"]', "off")
            await b.wait_for_timeout(1500)
            st = await (await b.request.get(BASE + "/api/seal")).json()
            names = {x["name"]: x for x in st.get("secrets") or []}
            check(names.get("mail.password", {}).get("mode") == "off", "his mail password: only while signed in")
            await b.evaluate("()=>{const e=document.querySelector('#seal-card');e&&e.scrollIntoView({block:'start'})}")
            await b.wait_for_timeout(500)
            await b.screenshot(path=str(shots / "wide-secrets-away.png"))
            bp = await br.new_context(**phone)
            await bp.add_cookies(await bc.cookies())
            pp = await bp.new_page()
            await pp.goto(BASE + "/")
            await desk(pp)
            await pp.evaluate("()=>placeSettings('accounts','Your secrets')()")
            await pp.wait_for_selector("#seal-card select.seal-away", timeout=15000)
            await pp.evaluate("()=>{const e=document.querySelector('#seal-card .seal-awayh');e&&e.scrollIntoView({block:'start'})}")
            await pp.wait_for_timeout(500)
            await pp.screenshot(path=str(shots / "phone-secrets-away.png"))
            await bp.close()

            print("3. A restart, and nobody signed in")
            await bc.close()
            await ac.close()
            stop(srv)
            hits = scan(home, [PROVIDER_KEY, BOT, MAIL_PW])
            check(not hits, "after it stops, no key, token or password is anywhere in clear" + (f": {hits}" if hits else ""))
            srv = serve(env, log)
            check(wait_up(), "the server comes back with nobody signed in")
            polled = await until(lambda: get(TG, "/sent")["polled"].get(BOT), 40)
            check(bool(polled), "bob's bot polls Telegram with his token, opened while he's away")
            post(TG, "/inject", {"text": "/start"})          # the first private chat pairs, as a person's would
            paired = await until(lambda: [m for m in get(TG, "/sent")["sent"] if "Linked" in (m.get("text") or "")], 40)
            check(bool(paired), "his phone pairs with his own bot")
            post(TG, "/inject", {"text": "Hi, are you there?"})
            reply = await until(lambda: [m for m in get(TG, "/sent")["sent"]
                                         if m["method"] == "sendMessage" and "stand-in brain" in (m.get("text") or "")], 60)
            check(bool(reply), "a phone turn is answered")
            calls = get(BRAIN, "/calls")
            check(any(c["auth"] == f"Bearer {PROVIDER_KEY}" for c in calls),
                  "with the machine's provider key, opened from the vault")

            print("4. A step needs his signed-in-only mail password: his own chat gets a link")
            post(TG, "/inject", {"text": "Check my mail for invoices"})
            link_msg = await until(lambda: [m for m in get(TG, "/sent")["sent"]
                                            if "/unlock" in (m.get("text") or "")], 60)
            check(bool(link_msg), "his own Telegram chat gets a link to sign in")
            text = (link_msg or [{}])[0].get("text") or ""
            check("never in this chat" in text and f"{BASE}/unlock" in text, "the link is the remote address")
            pc = await br.new_context(**phone)
            p = await pc.new_page()
            await p.goto(BASE + "/unlock")
            await p.wait_for_selector("#who:not([hidden])", timeout=15000)
            await p.screenshot(path=str(shots / "phone-unlock-sign-in.png"))
            check("Sign in to open your secrets" in (await p.content()), "the link opens the sign-in page")
            await p.fill("#who", "bob")
            await p.fill("#pw", PW["bob"])
            await p.click("#go")
            await p.wait_for_selector("text=Open all for the next run", timeout=20000)
            await p.wait_for_timeout(400)
            await p.screenshot(path=str(shots / "phone-unlock.png"))
            await p.click("text=Open all for the next run")
            await p.wait_for_selector("text=The waiting mission carries on", timeout=15000)
            await p.screenshot(path=str(shots / "phone-unlock-done.png"))
            answered = await until(lambda: [m for m in get(TG, "/sent")["sent"]
                                            if "mailbox answered" in (m.get("text") or "")], 90)
            check(bool(answered), "the waiting step carries on and the chat gets its answer")
            ans = (answered or [{}])[0].get("text") or ""
            check("only while you're signed in" not in ans, f"the mail password opened ({ans[:90]})")
            notes.append(f"the answer: {ans[:160]}")
            wc = await br.new_context(**wide)
            w = await wc.new_page()
            await w.goto(BASE + "/unlock")
            await w.wait_for_selector("#who:not([hidden])", timeout=15000)
            await w.screenshot(path=str(shots / "wide-unlock-sign-in.png"))
            await wc.close()

            # the chat as bob sees it, drawn from what the stand-in Telegram sent
            rows = []
            for m in get(TG, "/sent")["sent"]:
                if m["method"] == "from_person":
                    rows.append(("me", m["text"]))
                elif m["method"] == "sendMessage" and (m.get("text") or "").strip():
                    rows.append(("bot", m["text"]))
            body = "".join(f'<div class="b {wh}">{html.escape(t)}</div>' for wh, t in rows)
            page = shots / "telegram.html"
            page.write_text(f"""<!doctype html><meta charset=utf-8><style>body{{margin:0;background:#d9e7d0;
font:15px/1.4 system-ui}}header{{background:#517da2;color:#fff;padding:14px 16px;font-weight:600}}
main{{max-width:560px;margin:0 auto;padding:12px 10px 40px;display:flex;flex-direction:column;gap:8px}}
.b{{white-space:pre-wrap;padding:8px 10px;border-radius:12px;max-width:86%;box-shadow:0 1px 1px rgba(0,0,0,.12);word-break:break-word}}
.me{{align-self:flex-end;background:#effdde}}.bot{{align-self:flex-start;background:#fff}}</style>
<header>Bento · after a restart, nobody signed in</header><main>{body}</main>""")
            tc = await br.new_context(**phone)
            tp = await tc.new_page()
            await tp.goto(page.as_uri())
            await tp.screenshot(path=str(shots / "phone-telegram-unlock.png"), full_page=True)
            await tc.close()
            await pc.close()

            print("5. Eve's Isolated Tenant")
            ec = await br.new_context(**wide)
            e = await ec.new_page()
            await sign_in(e, "eve", PW["eve"])
            await past_code(e)
            await desk(e)
            await e.request.post(BASE + "/api/setup", data={})
            await e.reload()
            await desk(e)
            u = await (await e.request.get(BASE + "/api/users")).json()
            check([x["name"] for x in u["users"]] == ["eve"] and u["me"]["tenant_admin"] and not u["me"]["admin"],
                  "she sees only her tenant's people, and runs it without being the machine's admin")
            got = await (await e.request.get(BASE + "/api/config")).json()
            check(not got["providers"]["openai"].get("_has_key"), "none of the machine's keys are in her view")
            r = await e.request.put(BASE + "/api/config", data={"autonomy": "ask", "sandbox": {"enabled": False}})
            check(r.status == 403, "she can't change the machine's settings")
            r = await e.request.put(BASE + "/api/config",
                                    data={"providers": {"openai": {"api_key": EVE_KEY, "enabled": True,
                                                                   "base_url": f"http://127.0.0.1:{BRAIN}/v1"}}})
            check(r.ok, "she sets up her tenant's own key")
            r = await e.request.post(BASE + "/api/users", data={"name": "finn", "password": "finn-password-1"})
            check(r.ok and (await r.json())["user"].get("tenant"), "she adds finn, into her own tenant")
            await e.request.put(BASE + "/api/config", data={"default_model": "openai/fake-1"})
            r = await e.request.post(BASE + "/api/chat", data={"text": "Hello from eve's tenant"}, timeout=60000)
            calls = get(BRAIN, "/calls")
            check(any(c["auth"] == f"Bearer {EVE_KEY}" for c in calls), "her turn reaches the provider with her own key")
            tdir = next((home / "tenants").iterdir())
            check(EVE_KEY not in (tdir / "config.json").read_text() and (tdir / "vault.json").exists(),
                  "her key is in her tenant's own vault")
            await e.evaluate("()=>openApp('users')")
            await e.wait_for_selector(".usr-roster", timeout=15000)
            await e.wait_for_timeout(800)
            await e.screenshot(path=str(shots / "wide-users-isolated.png"))
            await ec.close()

            ac = await br.new_context(**wide)
            a = await ac.new_page()
            await sign_in(a, "ada", PW["ada"])
            await desk(a)
            await a.evaluate("()=>openApp('users')")
            await a.wait_for_selector(".usr-scope", timeout=15000)
            await a.wait_for_timeout(800)
            await a.screenshot(path=str(shots / "wide-users-scopes.png"))
            apc = await br.new_context(**phone)
            await apc.add_cookies(await ac.cookies())
            ap = await apc.new_page()
            await ap.goto(BASE + "/")
            await desk(ap)
            await ap.evaluate("()=>openApp('users')")
            await ap.wait_for_selector(".usr-scope", timeout=15000)
            await ap.wait_for_timeout(800)
            await ap.screenshot(path=str(shots / "phone-users-scopes.png"))
            await br.close()

    try:
        time.sleep(1.5)
        if not wait_up():
            bad.append("the server did not come up")
        else:
            asyncio.run(run())
            stop(srv)
            lines = []
            for argv in (["user", "list"], ["user", "tenants"], ["vault", "--user", "bob"],
                         ["config", "providers.openai.api_key"]):
                out = subprocess.run([PY, "-m", "agentos", *argv], env=env, cwd=ROOT,
                                     capture_output=True, text=True, timeout=60)
                lines.append("$ bento " + " ".join(argv) + "\n" + (out.stdout + out.stderr).strip())
            text = "\n\n".join(lines) + "\n"
            (shots / "terminal.txt").write_text(text)
            print(text)
            check(PROVIDER_KEY not in text and BOT not in text and MAIL_PW not in text,
                  "the terminal names what's kept and shows no value")
    finally:
        with __import__("contextlib").suppress(Exception):
            stop(srv)
        stand.terminate()
    for n in notes:
        print("  ·", n)
    print("FINDINGS:", json.dumps(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
