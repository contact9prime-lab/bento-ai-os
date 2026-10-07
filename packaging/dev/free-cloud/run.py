# ruff: noqa  -- a test script
"""The free cloud, end to end: the real image under Render Free's limits.

Render Free gives a container 0.1 of a CPU and 512 MB, hands it a PORT, and wipes its disk
on every restart. This runs the image exactly that way (no volume at all) with the two
things the free blueprint adds: a GitHub key (here, fake_github.py) and the keep-awake
visit. A stand-in model (fake_model.py) calls Bento's real `remember` tool and answers
from what Bento puts in its prompt. Then it stops the container the way Render does
(SIGTERM), starts a NEW one on an empty disk, and asks again.

    python run.py IMAGE SHOTS_DIR          # docker must be running; ports 9303/9304/10000
"""
import asyncio, json, os, subprocess, sys, time
from pathlib import Path
import httpx

HERE = Path(__file__).resolve().parent
IMAGE = sys.argv[1] if len(sys.argv) > 1 else "bento-cloud-test"
SHOTS = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/free-cloud-shots")
SHOTS.mkdir(parents=True, exist_ok=True)
HOSTIP = subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split()[0]
os.environ["NO_PROXY"] = os.environ["no_proxy"] = f"127.0.0.1,localhost,{HOSTIP}"
URL = "http://127.0.0.1:10000"
PW = "indigo-tundra-harbor-saffron-46"
NAME = "bento-free"
T0 = time.time()
RESULTS = {}


def say(*a):
    print(f"[{time.time()-T0:6.1f}s]", *a, flush=True)


def sh(*cmd, check=True):
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def start(label):
    sh("docker", "rm", "-f", NAME, check=False)
    t = time.time()
    sh("docker", "run", "-d", "--name", NAME, "--cpus", "0.1", "--memory", "512m",
       "-p", "10000:10000", "-e", "PORT=10000", "-e", f"AGENTOS_PASSPHRASE={PW}",
       "-e", "BENTO_KEEP_GITHUB_TOKEN=good-token", "-e", f"AGENTOS_GITHUB_API=http://{HOSTIP}:9303",
       "-e", "BENTO_EPHEMERAL=1", "-e", "BENTO_KEEP_AWAKE=1", "-e", f"RENDER_EXTERNAL_URL={URL}",
       "-e", f"NO_PROXY={HOSTIP}", "-e", f"no_proxy={HOSTIP}", IMAGE)
    while time.time() - t < 600:
        try:
            if httpx.get(URL + "/login", timeout=3).status_code == 200:
                break
        except Exception:
            pass
        time.sleep(1)
    secs = round(time.time() - t, 1)
    RESULTS[f"{label}_up_s"] = secs
    say(f"{label}: /login answered after {secs}s (0.1 CPU, 512 MB, no volume)")
    return secs


def login():
    c = httpx.Client(base_url=URL, timeout=60)
    r = c.post("/api/remote/login", json={"passphrase": PW})
    assert r.status_code == 200, r.text
    return c


def chat(c, text):
    import websockets
    async def go():
        hdr = {"Cookie": "; ".join(f"{k}={v}" for k, v in c.cookies.items())}
        async with websockets.connect(URL.replace("http", "ws") + "/ws", additional_headers=hdr, proxy=None) as ws:
            await ws.send(json.dumps({"type": "chat", "text": text, "title": text[:40]}))
            out, t, tools = "", time.time(), []
            while time.time() - t < 240:
                ev = json.loads(await asyncio.wait_for(ws.recv(), 240))
                if ev.get("type") == "text_delta":
                    out += ev.get("text", "")
                if ev.get("type") == "tool_start":
                    tools.append(ev.get("name") or ev.get("tool"))
                if ev.get("type") == "error":
                    out += " [error] " + ev.get("message", "")
                if ev.get("type") == "turn_end":
                    return out, tools
            return out + " [timeout]", tools
    return asyncio.run(go())


async def shots(name, steps):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        for vname, vp, mob in (("desk", {"width": 1280, "height": 800}, False),
                               ("phone", {"width": 390, "height": 844}, True)):
            ctx = await b.new_context(viewport=vp, is_mobile=mob, has_touch=mob)
            pg = await ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            await steps(pg)
            await pg.screenshot(path=str(SHOTS / f"{name}-{vname}.png"))
            say(f"shot {name}-{vname}.png", "errors:", errs[:2])
        await b.close()


async def sign_in(pg):
    await pg.goto(URL + "/login")
    await pg.wait_for_timeout(1500)
    await pg.fill("input[type=password]", PW)
    await pg.keyboard.press("Enter")
    await pg.wait_for_timeout(4000)
    for t in ("Finish later", "Skip for now", "Not now"):
        try:
            await pg.get_by_text(t).first.click(timeout=1200)
        except Exception:
            pass


def gist_log():
    return httpx.get(f"http://{HOSTIP}:9303/log", timeout=10).json()


def mem_mb():
    s = sh("docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", NAME).stdout.strip()
    return s.split("/")[0].strip()


# ---- 1. a fresh free machine --------------------------------------------------------
start("first start")
log = sh("docker", "logs", NAME).stdout
say("entrypoint:", " | ".join(l for l in log.splitlines() if "▲" in l or "restored" in l or "nothing" in l)[:300])


async def s_login(pg):
    await pg.goto(URL + "/login")
    await pg.wait_for_timeout(2500)
asyncio.run(shots("free-1-signin", s_login))

c = login()
r = c.put("/api/config", json={"agent_name": "Aria", "default_model": "custom/fake-1",
                               "providers": {"custom": {"enabled": True, "base_url": f"http://{HOSTIP}:9304/v1",
                                                        "api_key": "", "models": ["fake-1"]}}})
say("brain set:", r.status_code)
# The stand-in model has no published price, so Bento would ask for one before its first
# turn (a real Gemini or OpenRouter model has one). Answer it the way a person would: free.
say("price set:", c.put("/api/pricing", json={"model": "custom/fake-1", "in": 0, "out": 0}).status_code)
ans, tools = chat(c, "Remember that my favourite colour is teal")
RESULTS["remember_tools"] = tools
say("chat 1:", ans, tools)
ans2, _ = chat(c, "What is my favourite colour?")
say("chat 2 (same machine):", ans2)
say("memory in use:", mem_mb())
RESULTS["mem_first"] = mem_mb()

# the save loop runs every 30 s after a 15 s settle; wait for the first save
t = time.time()
while time.time() - t < 240:
    st = c.get("/api/keep").json()
    if st.get("saved_at"):
        break
    time.sleep(3)
RESULTS["first_save_after_s"] = round(time.time() - t, 1)
say("kept:", json.dumps({k: st.get(k) for k in ("line", "saved_bytes", "url")}))


async def s_chat(pg):
    await sign_in(pg)
    await pg.evaluate("openApp('chat')")
    await pg.wait_for_timeout(3000)
    await pg.evaluate("""(()=>{const it=[...document.querySelectorAll('.conv,.citem,[data-cid]')].find(e=>/favourite/i.test(e.textContent));if(it)it.click()})()""")
    await pg.wait_for_timeout(2500)
asyncio.run(shots("free-2-chat", s_chat))


async def s_kept(pg):
    await sign_in(pg)
    await pg.evaluate("SETTAB='system';try{localStorage.setItem('settab','system')}catch(e){};openApp('settings')")
    await pg.wait_for_timeout(3500)
    await pg.evaluate("document.getElementById('cd-box').scrollIntoView({block:'start'})")
    await pg.wait_for_timeout(800)
asyncio.run(shots("free-3-kept", s_kept))

# ---- 2. Render stops it (a spin-down, a redeploy) -----------------------------------
ans3, _ = chat(c, "Remember that the launch is on the 14th")
say("chat 3 (just before the stop):", ans3)
t = time.time()
sh("docker", "stop", "-t", "30", NAME)
RESULTS["stop_s"] = round(time.time() - t, 1)
say(f"stopped with SIGTERM in {RESULTS['stop_s']}s; gist calls:",
    [(e["m"], e["p"]) for e in gist_log()["log"] if e["m"] != "GET"][-3:])

# ---- 3. a NEW container on an empty disk ---------------------------------------------
start("second start")
log = sh("docker", "logs", NAME).stdout
say("entrypoint:", " | ".join(l for l in log.splitlines() if "restored" in l or "✗" in l)[:300])
c = httpx.Client(base_url=URL, timeout=60, cookies=c.cookies)
r = c.get("/api/config")
RESULTS["old_session_works"] = r.status_code == 200
say("the session from before the restart:", r.status_code)
if r.status_code != 200:
    c = login()
ans4, _ = chat(c, "What do you remember about me?")
RESULTS["after_restart_answer"] = ans4
say("chat 4 (new container):", ans4)
convs = c.get("/api/conversations").json()
convs = convs if isinstance(convs, list) else convs.get("conversations", [])
RESULTS["conversations_after"] = [x.get("title") for x in convs][:6]
say("conversations:", RESULTS["conversations_after"])
RESULTS["mem_second"] = mem_mb()


async def s_after(pg):
    await sign_in(pg)
    await pg.evaluate("openApp('chat')")
    await pg.wait_for_timeout(3000)
    await pg.evaluate("""(()=>{const it=[...document.querySelectorAll('.conv,.citem,[data-cid]')].find(e=>/remember about me/i.test(e.textContent));if(it)it.click()})()""")
    await pg.wait_for_timeout(2500)
asyncio.run(shots("free-4-after-restart", s_after))

print(json.dumps(RESULTS, indent=2))
