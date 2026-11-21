"""Sealed secrets, live: two people on one machine, a real server, a real Chromium.

    .venv/bin/python packaging/dev/seal-e2e/run.py WORKDIR

A real `bento serve` on a throwaway home, a stand-in website that sets a sign-in cookie, and
Playwright as three people signing in through the real sign-in page. It checks:

  - each person's first sign-in shows a recovery code to save, once;
  - bob's mail password and his website sign-in are on disk only sealed: the whole home is
    searched for both after the server stops, and the profile in RAM is gone;
  - after a restart nothing of bob's opens until bob enters his password, and then it does;
  - an admin resetting bob's password gets nothing of his: bob's recovery code opens it;
  - `bento vault --user bob` says it is sealed and prints no value.

Pictures go to WORKDIR/shots at 1440x900 and 390 px; the terminal transcript beside them.
"""
import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PY = str(ROOT / ".venv" / "bin" / "python")
PORT, SITE = 8721, 8722
BASE = f"http://127.0.0.1:{PORT}"
MAIL_PW = "BOB-MAIL-PASSWORD-31337"
SITE_TOKEN = "BOB-SITE-TOKEN-777"
PW = {"ada": "ada-password-1", "bob": "bob-password-1", "cleo": "cleo-password-1"}


class Site(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Set-Cookie", f"sessionid={SITE_TOKEN}; Max-Age=86400; HttpOnly")
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h1>Postly</h1><p>Signed in as @bob</p>")

    def log_message(self, *a):
        pass


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
    """Every file in the home, read raw, for each secret in clear."""
    hits = []
    for f in home.rglob("*"):
        if f.is_file():
            with open(f, "rb") as fh:
                raw = fh.read()
            hits += [f"{n} in {f.relative_to(home)}" for n in needles if n.encode() in raw]
    return hits


async def desk(p, timeout=30):
    """Wait for the desktop's script, by asking (the page's CSP refuses Playwright's in-page wait)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if await p.evaluate("()=>typeof openApp==='function'"):
                return
        except Exception:
            pass
        await asyncio.sleep(0.4)
    raise TimeoutError("the desktop did not load")


async def sign_in(p, name, pw):
    await p.goto(BASE + "/login")
    await p.wait_for_selector("#who:not([hidden])", timeout=15000)
    await p.fill("#who", name)
    await p.fill("#pw", pw)
    await p.click("#go")


async def open_web_window(p, url):
    """What the Web window does: open the shared browser's socket and ask for a page."""
    return await p.evaluate("""(url)=>new Promise(res=>{
      const ws=new WebSocket((location.protocol==='https:'?'wss':'ws')+'://'+location.host+'/ws/browser');
      let done=false;const fin=v=>{if(!done){done=true;try{ws.close()}catch(e){};res(v)}};
      ws.onopen=()=>ws.send(JSON.stringify({w:800,h:600,url}));
      ws.onmessage=m=>{if(typeof m.data==='string'){const d=JSON.parse(m.data);
          if(d.type==='error')fin('error: '+d.text);if(d.type==='state'&&(d.tabs||d.url))setTimeout(()=>fin('ok'),2500)}
        else setTimeout(()=>fin('ok'),2500)};
      ws.onerror=()=>fin('socket error');setTimeout(()=>fin('timeout'),40000)})""", url)


def main():
    work = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/seal-e2e")
    home, shots = work / "home", work / "shots"
    shutil.rmtree(home, ignore_errors=True)
    shots.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True)
    (home / "config.json").write_text(json.dumps({"agent_name": "Bento", "setup_complete": True,
                                                  "permissions_migrated": True,
                                                  "workspace": str(home / "work")}))
    threading.Thread(target=HTTPServer(("127.0.0.1", SITE), Site).serve_forever, daemon=True).start()
    env = {k: v for k, v in os.environ.items() if "PROXY" not in k.upper() and not k.startswith("AGENTOS_")}
    env.update(AGENTOS_HOME=str(home), AGENTOS_VAULT_KEYRING="0", NO_PROXY="127.0.0.1,localhost",
               AGENTOS_CHROMIUM=os.environ.get("AGENTOS_CHROMIUM", "/opt/pw-browsers/chromium"))
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
            # ada makes the first account (the machine's owner), then bob and cleo
            ada = await br.new_context(**wide)
            a = await ada.new_page()
            await a.goto(BASE + "/")
            r = await a.request.post(BASE + "/api/users", data={"name": "ada", "password": PW["ada"]})
            d = await r.json()
            check(len(d.get("recovery_code", "")) == 29, "the first account is shown a recovery code")
            for n in ("bob", "cleo"):
                await a.request.post(BASE + "/api/users", data={"name": n, "password": PW[n]})

            # bob's first sign-in, through the real page: the code, saved, then the desktop
            bobc = await br.new_context(**wide)
            b = await bobc.new_page()
            await sign_in(b, "bob", PW["bob"])
            await b.wait_for_selector(".code", timeout=20000)
            code = (await b.text_content(".code")).strip()
            check(len(code) == 29, "bob's first sign-in shows his recovery code")
            await b.screenshot(path=str(shots / "wide-recovery-code.png"))
            check(await b.is_disabled("#seal button:not(.ghost):not(.link)"), "Continue waits until he says he saved it")
            await b.check("#seal input[type=checkbox]")
            await b.click("#seal button:not(.ghost):not(.link)")
            await desk(b)
            # bob is a new account: his setup wizard would cover the desktop, and it isn't the subject
            await b.request.post(BASE + "/api/setup", data={})
            await b.reload()
            await desk(b)

            # cleo signs in on a phone: the same screen at 390 px
            cc = await br.new_context(**phone)
            c = await cc.new_page()
            await sign_in(c, "cleo", PW["cleo"])
            await c.wait_for_selector(".code", timeout=20000)
            await c.screenshot(path=str(shots / "phone-recovery-code.png"))

            # bob keeps a mail password and signs in to a website in his browser
            r = await b.request.put(BASE + "/api/accounts/mail",
                                    data={"user": "bob@example.com", "host": "127.0.0.1", "password": MAIL_PW})
            check(r.ok, "bob's mail password is saved")
            got = await open_web_window(b, f"http://127.0.0.1:{SITE}/")
            check(got == "ok", f"bob's Web window opens his browser ({got})")
            await asyncio.sleep(3)
            uid = next(u["id"] for u in json.loads((home / "users.json").read_text())["users"] if u["name"] == "bob")
            run_dirs = list(Path("/dev/shm").glob(f"bento-browser-*-{uid}-*"))
            check(len(run_dirs) == 1 and oct(run_dirs[0].stat().st_mode & 0o777) == "0o700",
                  "his profile is open in RAM only, in a folder only this user can read")
            st = await (await b.request.get(BASE + "/api/seal")).json()
            check(st.get("sealed") and st.get("open"), "Settings says his secrets are sealed and open while he's signed in")
            await b.evaluate("()=>placeSettings('accounts','Your secrets')()")
            await b.wait_for_selector("#seal-card .pgroup", timeout=15000)
            await b.wait_for_timeout(800)
            await b.evaluate("()=>{const e=document.querySelector('#seal-card');e&&e.scrollIntoView({block:'start'})}")
            await b.wait_for_timeout(400)
            await b.screenshot(path=str(shots / "wide-settings-secrets-open.png"))
            bob_cookies = await bobc.cookies()

            # the server stops: everything is put away, and the home is searched
            stop(srv)
            hits = scan(home, [MAIL_PW, SITE_TOKEN, code.replace("-", ""), code])
            check(not hits, "after it stops, neither secret nor the code is anywhere on disk" + (f": {hits}" if hits else ""))
            bh = home / "users" / uid
            check((bh / "browser" / "profile.sealed").exists() and not (bh / "browser" / "profile").exists(),
                  "his website sign-ins are kept only sealed")
            check(not list(Path("/dev/shm").glob(f"bento-browser-*-{uid}-*")), "the opened profile in RAM is gone")
            check(not (bh / "vault.key").exists(), "there is no vault key file to steal")
            sj = json.loads((bh / "seal.json").read_text())
            notes.append(f"seal.json holds: {sorted(sj)}")

            # restart: nothing of bob's opens until he enters his password
            srv = serve(env, log)
            check(wait_up(), "the server comes back")
            await bobc.add_cookies(bob_cookies)
            await b.goto(BASE + "/")
            await desk(b)
            st = await (await b.request.get(BASE + "/api/seal")).json()
            check(st.get("sealed") and not st.get("open"), "after a restart his secrets are closed")
            got = await open_web_window(b, f"http://127.0.0.1:{SITE}/")
            check(got.startswith("error") and "password" in got, f"his browser won't open: {got[:110]}")
            await b.wait_for_timeout(3500)
            await b.screenshot(path=str(shots / "wide-restart-toast.png"))
            await b.evaluate("()=>placeSettings('accounts','Your secrets')()")
            await b.wait_for_selector("#seal-card .pgroup input[type=password]", timeout=15000)
            await b.evaluate("()=>{const e=document.querySelector('#seal-card');e&&e.scrollIntoView({block:'start'})}")
            await b.wait_for_timeout(400)
            await b.screenshot(path=str(shots / "wide-settings-secrets-closed.png"))
            # the same card on a phone
            bp = await br.new_context(**phone)
            await bp.add_cookies(await bobc.cookies())
            pp = await bp.new_page()
            await pp.goto(BASE + "/")
            await desk(pp)
            await pp.evaluate("()=>placeSettings('accounts','Your secrets')()")
            await pp.wait_for_selector("#seal-card .pgroup", timeout=15000)
            await pp.evaluate("()=>{const e=document.querySelector('#seal-card');e&&e.scrollIntoView({block:'start'})}")
            await pp.wait_for_timeout(500)
            await pp.screenshot(path=str(shots / "phone-settings-secrets-closed.png"))
            await b.fill("#seal-card input[type=password]", PW["bob"])
            await b.click("#seal-card .pc button")
            await b.wait_for_timeout(2500)
            st = await (await b.request.get(BASE + "/api/seal")).json()
            check(st.get("open"), "his password opens them again")
            got = await open_web_window(b, f"http://127.0.0.1:{SITE}/")
            check(got == "ok", f"and his browser opens with his sign-ins ({got})")

            # ada, an admin, resets bob's password: she gets nothing of his
            r = await a.request.put(BASE + f"/api/users/{uid}", data={"password": "reset-by-ada"})
            check(r.ok, "the admin resets bob's password")
            b2c = await br.new_context(**wide)
            b2 = await b2c.new_page()
            await sign_in(b2, "bob", "reset-by-ada")
            await b2.wait_for_selector("#seal input[placeholder='Recovery code']", timeout=20000)
            await b2.screenshot(path=str(shots / "wide-enter-recovery-code.png"))
            st = await (await b2.request.get(BASE + "/api/seal")).json()
            check(st.get("needs_recovery") and not st.get("open"), "after the reset his secrets need his code")
            await b2.fill("#seal input[placeholder='Recovery code']", code)
            await b2.click("#seal button:not(.ghost):not(.link)")
            await b2.wait_for_selector(".code", timeout=20000)
            new = (await b2.text_content(".code")).strip()
            check(new and new != code, "his code opens them, and he gets a new one")
            st = await (await b2.request.get(BASE + "/api/seal")).json()
            check(st.get("open"), "his secrets are open again, under his new password")
            await br.close()

    try:
        if not wait_up():
            bad.append("the server did not come up")
        else:
            asyncio.run(run())
            stop(srv)
            out = subprocess.run([PY, "-m", "agentos", "vault", "--user", "bob"], env=env, cwd=ROOT,
                                 capture_output=True, text=True, timeout=60)
            text = "$ bento vault --user bob\n" + (out.stdout + out.stderr).strip() + "\n"
            (shots / "terminal-bento-vault.txt").write_text(text)
            print(text)
            check("Sealed with your password" in text and "mail.password" in text and MAIL_PW not in text,
                  "`bento vault` names what's sealed and shows no value")
    finally:
        with __import__("contextlib").suppress(Exception):
            stop(srv)
    for n in notes:
        print("  ·", n)
    print("FINDINGS:", json.dumps(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
