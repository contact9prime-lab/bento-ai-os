"""Usage for every LLM and account, and daily quotas: a real `bento serve` on a throwaway home, the
release run's stand-in brain (an OpenAI-compatible host that answers 1,200 tokens in and 300 out, and
states its own bill for an OpenRouter-style model), and Playwright.

    .venv/bin/python packaging/dev/usage-e2e/run.py WORKDIR

It checks, and photographs (1440x900 and a 390px phone):
  1. every call is one row in the calling account's database, with its money marked as the
     provider's own figure or our estimate;
  2. the agent answers "what did I spend" from the same numbers (the usage_report tool);
  3. an admin sees every account, and sets a daily quota for bob;
  4. bob's next call is refused in a sentence, and his Token Analytics shows the quota used up.
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

ROOT = Path(__file__).resolve().parents[3]
STAND = ROOT / "packaging" / "dev" / "release-e2e" / "stand_ins.py"
PY = str(ROOT / ".venv" / "bin" / "python")
PORT, BRAIN, TG = 8741, 8742, 8743
BASE = f"http://127.0.0.1:{PORT}"
PW = {"ada": "ada-password-1", "bob": "bob-password-1"}


def get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
        return json.loads(r.read() or b"{}")


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


async def sign_in(p, name, pw):
    await p.goto(BASE + "/login")
    await p.wait_for_selector("#who:not([hidden])", timeout=15000)
    await p.fill("#who", name)
    await p.fill("#pw", pw)
    await p.click("#go")
    try:
        await p.wait_for_selector(".code", timeout=6000)
        await p.check("#seal input[type=checkbox]")
        await p.click("#seal button:not(.ghost):not(.link)")
    except Exception:
        pass
    await desk(p)


async def usage_app(p, shot, wait=".usg-llm"):
    await p.evaluate("()=>{document.querySelectorAll('.win').forEach(w=>{});openApp('tokens')}")
    await p.wait_for_selector(wait, timeout=20000)
    await p.wait_for_timeout(900)
    await p.evaluate("()=>{const w=[...document.querySelectorAll('.win')].pop();"
                     "const b=w&&w.querySelector('.tbtns .mx');b&&b.offsetParent&&b.click()}")
    await p.wait_for_timeout(600)
    await p.screenshot(path=str(shot))


def main():
    work = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/usage-e2e")
    home, shots = work / "home", work / "shots"
    shutil.rmtree(home, ignore_errors=True)
    shots.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True)
    brain = f"http://127.0.0.1:{BRAIN}/v1"
    (home / "config.json").write_text(json.dumps({
        "agent_name": "Bento", "setup_complete": True, "permissions_migrated": True,
        "default_model": "openai/fake-1", "workspace": str(home / "work"),
        "providers": {"openai": {"enabled": True, "base_url": brain, "models": ["fake-1"], "api_key": ""},
                      "openrouter": {"enabled": True, "base_url": brain, "models": ["or-fake"], "api_key": ""}}}))
    env = {k: v for k, v in os.environ.items() if "PROXY" not in k.upper() and not k.startswith("AGENTOS_")}
    env.update(AGENTOS_HOME=str(home), AGENTOS_VAULT_KEYRING="0", NO_PROXY="127.0.0.1,localhost",
               AGENTOS_TELEGRAM_API=f"http://127.0.0.1:{TG}")
    stand = subprocess.Popen([PY, str(STAND), str(BRAIN), str(TG)], env=env,
                             stdout=open(work / "stand-ins.log", "w"), stderr=subprocess.STDOUT)
    srv = subprocess.Popen([PY, "-m", "agentos", "serve", "--port", str(PORT), "--no-browser",
                            "--if-running", "fail"], env=env, cwd=ROOT,
                           stdout=open(work / "server.log", "w"), stderr=subprocess.STDOUT)
    bad, notes = [], []

    def check(ok, what):
        print(("  ✓ " if ok else "  ✗ ") + what)
        if not ok:
            bad.append(what)

    async def run():
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            br = await pw.chromium.launch()
            wide = {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 1}
            phone = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2,
                     "is_mobile": True, "has_touch": True}

            print("1. Every call is counted once, in the account that made it")
            ac = await br.new_context(**wide)
            a = await ac.new_page()
            await a.goto(BASE + "/")
            await a.request.post(BASE + "/api/users", data={"name": "ada", "password": PW["ada"]})
            await a.request.put(BASE + "/api/config", data={"providers": {
                "openai": {"api_key": "sk-USAGE-OPENAI", "enabled": True},
                "openrouter": {"api_key": "sk-or-USAGE", "enabled": True}}})
            await a.request.put(BASE + "/api/pricing", data={"model": "openai/fake-1", "in": 2.5, "out": 10})
            await a.request.put(BASE + "/api/pricing", data={"model": "openrouter/or-fake", "in": 1, "out": 1})
            await a.request.post(BASE + "/api/users", data={"name": "bob", "password": PW["bob"]})
            bc = await br.new_context(**wide)
            b = await bc.new_page()
            await sign_in(b, "bob", PW["bob"])
            await b.request.post(BASE + "/api/setup", data={})       # past the wizard, as he would be
            for text, model in (("Draft a note to the team", "openai/fake-1"),
                                ("Summarise yesterday", "openai/fake-1"),
                                ("Find three cafés nearby", "openrouter/or-fake")):
                r = await b.request.post(BASE + "/api/chat", data={"text": text, "model": model}, timeout=60000)
                check(r.ok, f"bob: {text}")
            for _ in range(40):          # the last memory extraction runs after its turn answered
                mine = await (await b.request.get(BASE + "/api/usage/llms")).json()
                by = {l["llm"]: l for l in mine["llms"]}
                if by.get("openai", {}).get("calls", 0) >= 5:
                    break
                await asyncio.sleep(0.5)
            # two turns on OpenAI, and the memory extraction after each of the three turns, which runs
            # on the default model: every call is a row, none counted twice
            check(by.get("openai", {}).get("calls") == 5 and by["openai"]["in"] == 6000
                  and by["openai"]["out"] == 1500 and by["openai"]["total"] == 7500,
                  "OpenAI: 5 calls (2 turns, 3 memory extractions), 6,000 in, 1,500 out, 7,500 in all")
            check(by["openai"]["usd_estimated"] == 0.03 and by["openai"]["usd_exact"] == 0,
                  "its money is estimated from the price list ($0.03)")
            check(by.get("openrouter", {}).get("usd_exact") == 0.0042,
                  "OpenRouter's is the bill it stated ($0.0042)")
            check(not mine["admin"] and "everyone" not in mine, "bob sees only his own")

            print("2. The agent answers from the same numbers")
            r = await b.request.post(BASE + "/api/chat", data={"text": "What did I spend this week?"}, timeout=60000)
            ans = (await r.json()).get("content") or ""
            check("OpenAI: 6 calls" in ans and "OpenRouter" in ans and "estimated" in ans,
                  "it calls usage_report and says it")
            notes.append(f"the answer: {ans[:240]}")

            print("3. The admin sees everyone, and sets bob's daily quota")
            await sign_in(a, "ada", PW["ada"])
            allx = await (await a.request.get(BASE + "/api/usage/llms?everyone=1")).json()
            names = {x["name"]: x for x in allx.get("everyone") or []}
            check(sum(l["calls"] for l in names.get("bob", {}).get("llms", [])) == 9,
                  "ada sees bob's nine calls (four turns, one with a tool round, and four extractions)")
            bob = next(x["id"] for x in allx["accounts"] if x["name"] == "bob")
            r = await a.request.put(BASE + "/api/usage/sharing", data={
                "off": ["anthropic"], "quota": {bob: {"openai": {"tokens": 6000, "usd": 1}},
                                                "*": {"openrouter": {"usd": 0.5}}}})
            check(r.ok, "she sets bob 6,000 OpenAI tokens a day, and everyone $0.50 of OpenRouter")
            await usage_app(a, shots / "wide-usage-admin.png", ".usg-qrow")
            await a.evaluate("()=>{const e=document.querySelector('.usg-share');e&&e.scrollIntoView({block:'start'})}")
            await a.wait_for_timeout(400)
            await a.screenshot(path=str(shots / "wide-usage-quotas.png"))
            apc = await br.new_context(**phone)
            await apc.add_cookies(await ac.cookies())
            ap = await apc.new_page()
            await ap.goto(BASE + "/")
            await desk(ap)
            await usage_app(ap, shots / "phone-usage-admin.png", ".usg-t")
            await ap.evaluate("()=>{const e=document.querySelector('.usg-tw');e&&e.scrollIntoView({block:'start'})}")
            await ap.wait_for_timeout(400)
            await ap.screenshot(path=str(shots / "phone-usage-everyone.png"))
            await ap.evaluate("()=>{const e=document.querySelector('#usg-quotas');e&&e.scrollIntoView({block:'start'})}")
            await ap.wait_for_timeout(400)
            await ap.screenshot(path=str(shots / "phone-usage-quotas.png"))
            await apc.close()

            print("4. Bob's next call goes past it")
            r = await b.request.post(BASE + "/api/chat", data={"text": "One more draft please"}, timeout=60000)
            body = await r.json()
            said = json.dumps(body)
            check("daily quota for OpenAI is used up" in said, "refused in a sentence: " + said[:200])
            before = len([c for c in get(BRAIN, "/calls")])
            await b.request.post(BASE + "/api/chat", data={"text": "And again"}, timeout=60000)
            check(len(get(BRAIN, "/calls")) == before, "and nothing reached the provider")
            await sign_in(b, "bob", PW["bob"])
            await usage_app(b, shots / "wide-usage-bob.png", ".usg-q")
            bpc = await br.new_context(**phone)
            await bpc.add_cookies(await bc.cookies())
            bp = await bpc.new_page()
            await bp.goto(BASE + "/")
            await desk(bp)
            await usage_app(bp, shots / "phone-usage-bob.png", ".usg-q")
            await br.close()

    try:
        time.sleep(1.5)
        if not wait_up():
            bad.append("the server did not come up")
        else:
            asyncio.run(run())
            stop(srv)
            lines = []
            for argv in (["usage", "llms", "--everyone"], ["usage", "quota"],
                         ["usage", "quota", "bob", "openai", "--tokens", "0"], ["usage", "llms", "--user", "bob"]):
                out = subprocess.run([PY, "-m", "agentos", *argv], env=env, cwd=ROOT,
                                     capture_output=True, text=True, timeout=60)
                lines.append("$ bento " + " ".join(argv) + "\n" + (out.stdout + out.stderr).strip())
            text = "\n\n".join(lines) + "\n"
            (shots / "terminal.txt").write_text(text)
            print(text)
            check("## bob" in text and "6,000 tokens and $1.00 a day" in text, "the terminal says the same")
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
