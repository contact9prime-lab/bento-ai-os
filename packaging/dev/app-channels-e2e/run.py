"""An app reports in your chats, and the phone reaches the app: walked through end to end.

    .venv/bin/python packaging/dev/app-channels-e2e/run.py WORKDIR

A real `bento serve` on a throwaway home, a stand-in Telegram here (AGENTOS_TELEGRAM_API) with the
owner's chat and a group called Traders both let in, and a headless Chrome on the desktop. The app
"Signal Desk" asks for an app job with send_to ['telegram', 'Traders']; the run checks:

  - the job's card names both chats, and Allow is the only yes
  - the job runs with no model, saves its numbers without "_message", and the owner's chat and the
    group each get one message starting with the app's name
  - Missions → Schedule says "reports to …"
  - from the phone, /apps lists the app with a button, the button shows its numbers, and
    /app Signal Desk shows the same glance
  - a stranger's chat (never let in) gets nothing

Screenshots of the card, Missions, the app and the phone's chats go to WORKDIR/shots.
"""
import asyncio
import base64
import html
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import httpx
import uvicorn
import websockets
from fastapi import FastAPI, Request

ROOT = Path(__file__).resolve().parents[3]
PY = sys.executable
PORT, TG, CDP = 8673, 9473, 9474
OWNER, GROUP, STRANGER = 777, -100500, 888

tg = FastAPI()
UPD: list = []
LOG: list = []          # every message sent: {at, chat, text, buttons}
NEXT = [100]


@tg.api_route("/bot{token}/{method}", methods=["GET", "POST"])
async def api(token: str, method: str, req: Request):
    try:
        b = await req.json()
    except Exception:
        b = dict(req.query_params)
    if method == "getMe":
        return {"ok": True, "result": {"id": 1, "is_bot": True, "username": "bento_bot", "first_name": "Bento"}}
    if method == "getUpdates":
        off = int(b.get("offset") or 0)
        if off:
            UPD[:] = [u for u in UPD if u["update_id"] >= off]
        t0 = time.time()
        while time.time() - t0 < min(float(b.get("timeout") or 0), 2) and not UPD:
            await asyncio.sleep(0.2)
        return {"ok": True, "result": [u for u in UPD if u["update_id"] >= off]}
    if method == "sendMessage":
        NEXT[0] += 1
        btns = [x for row in ((b.get("reply_markup") or {}).get("inline_keyboard") or []) for x in row]
        LOG.append({"at": time.time(), "chat": int(b.get("chat_id") or 0), "id": NEXT[0],
                    "text": str(b.get("text") or ""), "buttons": btns})
        return {"ok": True, "result": {"message_id": NEXT[0], "chat": {"id": b.get("chat_id")},
                                       "date": int(time.time())}}
    return {"ok": True, "result": True}


SAID: list = []         # what the owner typed: {at, text}


def say(text):
    SAID.append({"at": time.time(), "text": text})
    NEXT[0] += 1
    UPD.append({"update_id": NEXT[0], "message": {
        "message_id": NEXT[0], "date": int(time.time()), "text": text,
        "from": {"id": OWNER, "is_bot": False, "first_name": "Piyush"},
        "chat": {"id": OWNER, "type": "private", "first_name": "Piyush"}}})


def tap(data, mid):
    NEXT[0] += 1
    UPD.append({"update_id": NEXT[0], "callback_query": {
        "id": str(NEXT[0]), "data": data, "from": {"id": OWNER, "is_bot": False, "first_name": "Piyush"},
        "message": {"message_id": mid, "chat": {"id": OWNER, "type": "private"}, "date": int(time.time())}}})


SCRIPT = r'''import json, time
signals = 40 + int(time.time()) % 9
out = {"signals": signals, "newest": time.strftime("%H:%M")}
if signals >= 40:
    out["_message"] = f"{signals} stocks broke out of a tight range. Newest at {out['newest']}."
print(json.dumps(out))
'''

APP = """<!doctype html><html><head><meta charset="utf-8"><title>Signal Desk</title></head>
<body><main class="app"><h1>Signal Desk</h1><p class="sub" id="when">waiting for the first scan…</p>
<div class="card"><div class="big" id="n">–</div><div class="sub">breakouts in the last scan</div></div>
<p class="sub" id="where"></p></main>
<script>
const PY = %s;
async function draw(){
  const d = await appData.get(); const j = (d._jobs || {})['Scan the market'];
  if (d.scan){ document.getElementById('n').textContent = d.scan.signals; }
  document.getElementById('when').textContent = j ? ('updated ' + appFmt.ago(j.at)) : 'waiting for the first scan…';
}
window.addEventListener('appdata', draw);
(async () => {
  await draw();
  const r = await appJob.ensure({title: 'Scan the market', script: PY, every: 5, key: 'scan',
                                 send_to: ['telegram', 'Traders']});
  const chats = await appChannel.list();
  document.getElementById('where').textContent = 'Reports to: ' + chats.filter(c => c.kind !== 'person').map(c => c.label).join(', ');
  await draw();
})();
</script></body></html>""" % json.dumps(SCRIPT)


def setup(home: Path, env: dict):
    shutil.rmtree(home, ignore_errors=True)
    (home / "work").mkdir(parents=True)
    (home / "config.json").write_text(json.dumps({
        "agent_name": "Aria", "setup_complete": True, "permissions_migrated": True,
        "workspace": str(home / "work"), "autonomy": "balanced",
        "sandbox": {"enabled": False}, "memory": {"auto_extract": False},
        "providers": {"ollama": {"enabled": False}},
        "telegram": {"enabled": True, "bot_token": "1:T", "owner_chat_id": OWNER, "status_messages": False,
                     "groups": True}}))
    subprocess.run([PY, "-c", f"""
from agentos.memory import Store
store = Store()
for cid, title, kind, ok in (({OWNER}, 'Piyush', 'private', 1), ({GROUP}, 'Traders', 'supergroup', 1),
                             ({STRANGER}, 'Someone', 'private', 0)):
    store.tg_upsert_chat(cid, title, '', kind)
    store.tg_set_allowed(cid, ok, by='the run')
"""], env=env, cwd=ROOT, check=True)


def transcript(items: list, title: str) -> str:
    rows = []
    for it in items:
        btns = "".join(f'<span class="btn">{html.escape(b["text"])}</span>' for b in it.get("buttons") or [])
        # what Telegram shows: the bot's text is sent as Telegram HTML, so it is read back first
        shown = html.unescape(it["text"]) if it["who"] == "bot" else it["text"]
        rows.append(f'<div class="b {it["who"]}">{html.escape(shown)}'
                    + (f'<div class="btns">{btns}</div>' if btns else "")
                    + f'<span class="t">{it["when"]}</span></div>')
    return f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">
<title>{html.escape(title)}</title><style>
:root{{color-scheme:light}}body{{margin:0;background:#d9e7d0;font:15px/1.4 -apple-system,system-ui,sans-serif}}
header{{background:#517da2;color:#fff;padding:14px 16px;font-weight:600}}header small{{display:block;font-weight:400;opacity:.8}}
main{{max-width:560px;margin:0 auto;padding:12px 10px 40px;display:flex;flex-direction:column;gap:8px}}
.b{{white-space:pre-wrap;padding:8px 10px 18px;border-radius:12px;max-width:86%;position:relative;box-shadow:0 1px 1px rgba(0,0,0,.12)}}
.me{{align-self:flex-end;background:#effdde}}.bot{{align-self:flex-start;background:#fff}}
.btns{{display:flex;flex-direction:column;gap:4px;margin-top:8px}}.btn{{background:#e8f0f7;color:#2b5f8a;border-radius:8px;padding:6px;text-align:center}}
.t{{position:absolute;right:8px;bottom:3px;font-size:11px;color:#8a9aa9}}
</style><header>{html.escape(title)}</header><main>{''.join(rows)}</main>"""


async def desktop(work: Path, aid: str, bad: list):
    """Open the app in a real desktop page, read the card, press Allow, wait for the job's run."""
    shots = work / "shots"
    ch = subprocess.Popen(["/opt/google/chrome/chrome", "--headless=new", "--no-sandbox",
                           f"--remote-debugging-port={CDP}", f"--user-data-dir={work}/chrome",
                           "--hide-scrollbars", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    B = f"http://127.0.0.1:{PORT}"
    try:
        for _ in range(50):
            try:
                tabs = httpx.get(f"http://127.0.0.1:{CDP}/json").json()
                break
            except Exception:
                await asyncio.sleep(.2)
        async with websockets.connect([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"],
                                      max_size=2 ** 26) as ws:
            n = [0]

            async def cdp(m, **p):
                n[0] += 1
                i = n[0]
                await ws.send(json.dumps({"id": i, "method": m, "params": p}))
                while True:
                    r = json.loads(await ws.recv())
                    if r.get("id") == i:
                        return r.get("result", r.get("error"))

            async def js(x):
                return (await cdp("Runtime.evaluate", expression=x, awaitPromise=True,
                                  returnByValue=True)).get("result", {}).get("value")

            async def shot(name):
                r = await cdp("Page.captureScreenshot", format="png")
                (shots / f"{name}.png").write_bytes(base64.b64decode(r["data"]))

            await cdp("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)
            await cdp("Page.navigate", url=B + "/")
            await asyncio.sleep(7)
            await js(f"(async()=>{{for(let i=0;i<20&&!(USERAPPS||[]).length;i++)await new Promise(r=>setTimeout(r,300)); openApp('ua_{aid}')}})()")
            card = ""
            for _ in range(40):
                await asyncio.sleep(1)
                card = await js("(()=>{const b=document.querySelector('.approval');return b?b.innerText:''})()") or ""
                if "Traders" in card:
                    break
            print("CARD:\n" + card[:900])
            if "the group Traders on Telegram" not in card or "you on Telegram" not in card:
                bad.append("the job's card did not name both chats")
            await shot("card")
            await js("[...document.querySelectorAll('.approval .allow')].pop().click()")
            t = time.time()
            while time.time() - t < 90 and not any(e["chat"] == GROUP for e in LOG):
                await asyncio.sleep(2)
            await asyncio.sleep(4)
            await shot("app-after-run")
            await js("openApp('tasks')")
            await asyncio.sleep(3)
            sched = await js("(()=>{const r=document.querySelector('.task-sends');return r?r.innerText:''})()") or ""
            print("MISSIONS:", sched)
            if "reports to" not in sched or "Traders" not in sched:
                bad.append("Missions did not say where the job reports")
            await shot("missions")
            await cdp("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=2, mobile=True)
            await cdp("Page.navigate", url=B + "/")
            await asyncio.sleep(7)
            await js(f"(async()=>{{for(let i=0;i<20&&!(USERAPPS||[]).length;i++)await new Promise(r=>setTimeout(r,300)); openApp('ua_{aid}')}})()")
            await asyncio.sleep(5)
            await shot("app-phone")
    finally:
        ch.terminate()


async def shoot(pages: dict, out: Path):
    """The transcripts, photographed by headless Chrome at a phone's size and a desktop's."""
    for name, path in pages.items():
        for tag, size, scale in (("phone", "390,844", "2"), ("wide", "1440,900", "1")):
            subprocess.run(["/opt/google/chrome/chrome", "--headless=new", "--no-sandbox", "--hide-scrollbars",
                            f"--window-size={size}", f"--force-device-scale-factor={scale}",
                            f"--screenshot={out / f'{tag}-{name}.png'}", path.as_uri()],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)


def main():
    work = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/app-channels-e2e")
    home, shots = work / "home", work / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=lambda: uvicorn.run(tg, host="127.0.0.1", port=TG, log_level="warning"),
                     daemon=True).start()
    env = {k: v for k, v in os.environ.items() if "PROXY" not in k.upper() and not k.startswith("AGENTOS_")}
    env.update(AGENTOS_HOME=str(home), AGENTOS_VAULT_KEYRING="0", NO_PROXY="127.0.0.1,localhost",
               AGENTOS_TELEGRAM_API=f"http://127.0.0.1:{TG}", PYTHONPATH=str(ROOT),
               DBUS_SYSTEM_BUS_ADDRESS="unix:path=/nonexistent", DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent")
    setup(home, env)
    srv = subprocess.Popen([PY, "-m", "agentos", "serve", "--port", str(PORT), "--no-browser",
                            "--if-running", "fail"], env=env, cwd=ROOT,
                           stdout=open(work / "server.log", "w"), stderr=subprocess.STDOUT)
    bad = []
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/login", timeout=2)
                break
            except Exception:
                time.sleep(0.5)
        time.sleep(3)
        B = f"http://127.0.0.1:{PORT}"
        aid = httpx.post(B + "/api/apps/new", json={"name": "Signal Desk"}).json()["id"]
        src = httpx.get(B + f"/api/apps/{aid}/source").json()
        httpx.put(B + f"/api/apps/{aid}/source", json={"html": APP, "base": src.get("version"), "force": True})
        asyncio.run(desktop(work, aid, bad))
        to_owner = [e for e in LOG if e["chat"] == OWNER and e["text"].startswith("▦ Signal Desk")]
        to_group = [e for e in LOG if e["chat"] == GROUP]
        if not to_owner:
            bad.append("the owner's chat got no report")
        if len(to_group) != 1 or not to_group[0]["text"].startswith("▦ Signal Desk\n"):
            bad.append(f"the group got {len(to_group)} reports, or one without the app's name")
        if any(e["chat"] == STRANGER for e in LOG):
            bad.append("the stranger's chat got a message")
        data = httpx.get(B + f"/api/apps/{aid}/data").json()
        print("DATA:", json.dumps(data)[:300])
        if "_message" in json.dumps(data.get("scan") or {}):
            bad.append("the message was saved with the data")
        # the phone: /apps, its button, /app <name>
        n0 = len(LOG)
        say("/apps")
        t = time.time()
        while time.time() - t < 20 and not any(e["buttons"] for e in LOG[n0:]):
            time.sleep(.5)
        listing = next((e for e in LOG[n0:] if e["buttons"]), None)
        if not listing or not any(b["text"] == "Signal Desk" for b in listing["buttons"]):
            bad.append("/apps did not list the app with a button")
        else:
            n1 = len(LOG)
            tap(next(b["callback_data"] for b in listing["buttons"] if b["text"] == "Signal Desk"), listing["id"])
            t = time.time()
            while time.time() - t < 20 and len(LOG) == n1:
                time.sleep(.5)
        glance = LOG[-1] if len(LOG) > n0 + 1 else None
        if not glance or "Scan the market · every 5 min" not in glance["text"]:
            bad.append("the app's button did not show its numbers")
        n2 = len(LOG)
        say("/app Signal Desk")
        t = time.time()
        while time.time() - t < 20 and len(LOG) == n2:
            time.sleep(.5)
        typed = LOG[-1] if len(LOG) > n2 else None
        if not typed or "signals: " not in typed["text"]:
            bad.append("/app Signal Desk did not show the glance")
        hhmm = lambda x: time.strftime("%H:%M", time.localtime(x))      # noqa: E731
        # the owner's chat as the phone showed it, the approval card left out (it is on the desktop
        # shot): the report, then what was typed and each answer, in the order they happened
        phone = sorted([{"who": "bot", "text": e["text"], "at": e["at"], "buttons": e["buttons"]}
                        for e in LOG if e["chat"] == OWNER and not e["text"].startswith("⚠")]
                       + [{"who": "me", "text": x["text"], "at": x["at"]} for x in SAID], key=lambda r: r["at"])
        for r in phone:
            r["when"] = hhmm(r.pop("at"))
        group = [{"who": "bot", "text": e["text"], "when": hhmm(e["at"])} for e in to_group]
        pages = {}
        for name, items, title in (("owner-chat", phone, "Bento · your chat"),
                                   ("group-chat", group, "Traders · group")):
            p = work / f"{name}.html"
            p.write_text(transcript(items, title))
            pages[name] = p
        asyncio.run(shoot(pages, shots))
        (work / "telegram-log.json").write_text(json.dumps(LOG, indent=1, ensure_ascii=False))
    finally:
        srv.terminate()
    print("FINDINGS:", json.dumps(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
