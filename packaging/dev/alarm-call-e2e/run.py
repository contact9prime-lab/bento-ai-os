"""An alarm nobody acknowledges reaches a person, end to end on a real server (alarmcall.py):

  the hub       `bento serve` on a throwaway home, holding a simulated ESP32 cold room itself
  the node      esp_sim.py, speaking ESPHome's web server API (cold room B, its compressor)
  Telegram      a stand-in Bot API that records what is sent and delivers taps, here

What it checks, and photographs (1440x900 and a 390px phone):

  1. the alarm rules page says who is called, and the person picks the second chat
  2. the compressor trips: the alarm is raised, and nobody is called yet
  3. a minute later the owner's Telegram gets it with an Acknowledge button
  4. a minute after that it goes to Sam, the second chat, and the owner is told it went on
  5. Sam taps Acknowledge: the board shows "seen by Sam on Telegram", the owner hears who took it,
     and Events and the ledger have each step
  6. Settings → System → Backup says nothing is kept elsewhere, then that a backup was made
  7. setup's step "Keep a copy somewhere else"
  8. the terminal: `bento network alarms call`, `bento doctor`'s line, the vulnerability audit

    .venv/bin/python packaging/dev/alarm-call-e2e/run.py WORKDIR
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PY = str(ROOT / ".venv" / "bin" / "python")
PORT, TG, SIM = 8761, 8762, 18930
BASE = f"http://127.0.0.1:{PORT}"
OWNER, SAM = 5150, 6160
COMP = "esp.cold-2.switch.compressor"


# ---- a stand-in Telegram: what is sent, and taps delivered --------------------------------------

def tg_server():
    import uvicorn
    from fastapi import FastAPI, Request
    app = FastAPI()
    SENT, QUEUE, N = [], [], [0]

    @app.post("/bot{token}/{method}")
    async def bot(token: str, method: str, request: Request):
        body = await request.json() if await request.body() else {}
        if method == "getMe":
            return {"ok": True, "result": {"id": 42, "is_bot": True, "username": "HubBot", "first_name": "Bento"}}
        if method == "getUpdates":
            for _ in range(20):
                if QUEUE:
                    out, QUEUE[:] = list(QUEUE), []
                    return {"ok": True, "result": out}
                await asyncio.sleep(0.1)
            return {"ok": True, "result": []}
        if method in ("sendMessage", "editMessageText", "sendPhoto"):
            SENT.append({"method": method, "at": time.time(), **body})
        return {"ok": True, "result": {"message_id": len(SENT) + 100}}

    @app.get("/sent")
    async def sent():
        return {"sent": SENT}

    @app.post("/tap")
    async def tap(request: Request):
        b = await request.json()
        N[0] += 1
        who = {"id": b["chat"], "first_name": b["name"], "is_bot": False}
        chat = {"id": b["chat"], "type": "private", "first_name": b["name"]}
        QUEUE.append({"update_id": 7000 + N[0], "callback_query": {
            "id": f"cq{N[0]}", "from": who, "data": b["data"],
            "message": {"message_id": 1, "chat": chat, "date": int(time.time()), "text": ""}}})
        return {"ok": True}

    uvicorn.run(app, host="127.0.0.1", port=TG, log_level="warning")


def get(path, port=PORT):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=20) as r:
        return json.loads(r.read() or b"{}")


def send(path, body, method="POST", port=PORT):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def sent_to(chat):
    """What this chat got about the alarm (the bot's own lines, "back online" and the like, left out)."""
    return [m for m in get("/sent", TG)["sent"] if str(m.get("chat_id")) == str(chat) and m["method"] == "sendMessage"
            and any(w in m.get("text", "") for w in ("Compressor", "Acknowledged", "acknowledged", "Cleared"))]


def wait(fn, timeout, what):
    t0 = time.time()
    while time.time() - t0 < timeout:
        got = fn()
        if got:
            return got
        time.sleep(1)
    raise TimeoutError(what)


def main():
    work = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/alarm-call-e2e")
    home, shots = work / "home", work / "shots"
    shutil.rmtree(home, ignore_errors=True)
    shots.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True)
    (home / "config.json").write_text(json.dumps({
        "agent_name": "Bento", "setup_complete": True, "permissions_migrated": True, "workspace": str(home / "work"),
        "port": PORT,                           # the terminal verbs find the server by it
        "telegram": {"enabled": True, "bot_token": "123:FAKE", "owner_chat_id": OWNER}}))
    env = {k: v for k, v in os.environ.items() if "PROXY" not in k.upper() and not k.startswith("AGENTOS_")}
    env.update(AGENTOS_HOME=str(home), AGENTOS_VAULT_KEYRING="0", NO_PROXY="127.0.0.1,localhost",
               AGENTOS_TELEGRAM_API=f"http://127.0.0.1:{TG}")
    threading.Thread(target=tg_server, daemon=True).start()
    sim = subprocess.Popen([PY, "-m", "agentos.demos.esp_sim", "--layout", "warehouse", "--zone", "zone-cold",
                            "--base", str(SIM), "--control", str(SIM + 7)], cwd=ROOT, env=env,
                           stdout=open(work / "sim.log", "w"), stderr=subprocess.STDOUT)
    srv = subprocess.Popen([PY, "-m", "agentos", "serve", "--port", str(PORT), "--no-browser", "--if-running", "fail"],
                           env=env, cwd=ROOT, stdout=open(work / "server.log", "w"), stderr=subprocess.STDOUT)
    bad, notes = [], []

    def check(ok, what):
        print(("  ✓ " if ok else "  ✗ ") + what)
        if not ok:
            bad.append(what)

    def poke(entity, value):
        req = urllib.request.Request(f"http://127.0.0.1:{SIM + 7}/", method="POST",
                                     data=json.dumps({"node": "cold-2", "entity": entity, "value": value}).encode())
        urllib.request.urlopen(req, timeout=5).read()

    async def shoot():
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            br = await pw.chromium.launch()
            for name, ctx in (("wide", {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 1}),
                              ("phone", {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2,
                                         "is_mobile": True, "has_touch": True})):
                c = await br.new_context(**ctx)
                p = await c.new_page()
                await p.goto(BASE + "/")
                await p.wait_for_function("()=>typeof openApp==='function'", timeout=40000)
                await p.wait_for_timeout(1500)
                yield name, p
                await c.close()
            await br.close()

    async def shots_rules(tag):
        async for name, p in shoot():
            await p.evaluate("()=>{openApp('devices')}")
            await p.wait_for_timeout(2500)
            await p.evaluate("()=>{if(typeof devRulesShow==='function')devRulesShow()}")
            await p.wait_for_selector(".dvr-call .dvc-words", timeout=20000)
            await p.evaluate("()=>{const w=[...document.querySelectorAll('.win')].pop();"
                             "const b=w&&w.querySelector('.tbtns .mx');b&&b.offsetParent&&b.click()}")
            await p.wait_for_timeout(800)
            await p.evaluate("()=>{const e=document.querySelector('.dvr-call');e&&e.scrollIntoView({block:'start'})}")
            await p.wait_for_timeout(500)
            await p.screenshot(path=str(shots / f"{name}-{tag}.png"))

    async def shots_board():
        async for name, p in shoot():
            await p.evaluate("()=>{openApp('devices')}")
            await p.wait_for_timeout(3000)
            await p.evaluate("()=>{const w=[...document.querySelectorAll('.win')].pop();"
                             "const b=w&&w.querySelector('.tbtns .mx');b&&b.offsetParent&&b.click()}")
            await p.wait_for_timeout(800)
            await p.evaluate("()=>{const e=document.querySelector('.dev-alarms,.dvs-alarms');e&&e.scrollIntoView({block:'start'})}")
            await p.wait_for_timeout(500)
            await p.screenshot(path=str(shots / f"{name}-alarm-acknowledged.png"))

    async def shots_backup(tag):
        async for name, p in shoot():
            await p.evaluate("()=>{SETTAB='system';localStorage.setItem('settab','system');"
                             "localStorage.setItem('setsub.system','Backup & cloud');openApp('settings')}")
            await p.wait_for_selector("#bk-offsite:not([hidden])", timeout=20000)
            await p.evaluate("()=>{const w=[...document.querySelectorAll('.win')].pop();"
                             "const b=w&&w.querySelector('.tbtns .mx');b&&b.offsetParent&&b.click()}")
            await p.wait_for_timeout(800)
            await p.evaluate("()=>{const e=document.querySelector('#bk-offsite');e&&e.scrollIntoView({block:'center'})}")
            await p.wait_for_timeout(500)
            await p.screenshot(path=str(shots / f"{name}-{tag}.png"))

    async def shots_setup():
        async for name, p in shoot():
            await p.evaluate("()=>obShow({step:'copy'})")
            await p.wait_for_selector(".ob-copy-doors .job-card", timeout=20000)
            await p.wait_for_timeout(700)
            await p.screenshot(path=str(shots / f"{name}-setup-copy.png"))

    try:
        t0 = time.time()
        while time.time() - t0 < 80:
            try:
                get("/api/platform")
                break
            except Exception:
                time.sleep(0.5)
        from agentos.memory import Store
        st = Store(str(home / "agentos.db"))
        st.tg_upsert_chat(SAM, "Sam (night shift)", "sam", "private")
        st.tg_set_allowed(SAM, 1, by="the owner on Telegram")
        st.db.commit()

        print("1. The rules page says who is called, and the second chat is picked")
        code, got = send("/api/devices/esp", {"key": "here", "action": "add", "name": "cold-2", "host": "127.0.0.1",
                                              "port": SIM + 1})
        check(code == 200, f"the hub holds cold room B's node ({code} {str(got)[:120]})")
        machine = wait(lambda: next((m["machine"] for m in get("/api/devices/board")["machines"]
                                     if any(t["id"] == COMP for t in m["things"])), None), 60, "the compressor on the board")
        code, got = send("/api/devices/alarms", {"alarms": [{"machine": machine, "item": COMP, "when": "off",
                                                              "name": "Cold room B compressor",
                                                              "note": "Reset the breaker in room B, then check the door seal."}]},
                         "PUT")
        check(code == 200 and len(got.get("alarms") or []) == 1, "an alarm rule for the compressor")
        g = get("/api/devices/escalation")
        check(g["own"] == [{"channel": "telegram", "name": "your Telegram"}] and any(c["to"] == str(SAM) for c in g["choices"]),
              "your Telegram is called first, and Sam can be the second chat")
        code, got = send("/api/devices/escalation", {"on": True, "after_min": 1, "then_min": 1,
                                                     "second": {"channel": "telegram", "to": str(SAM)}}, "PUT")
        check(code == 200 and "then to Sam" in got["words"], "saved: " + got.get("words", ""))
        asyncio.run(shots_rules("alarm-calls"))

        print("2. The compressor trips")
        poke("Compressor", False)
        raised = wait(lambda: [a for a in get("/api/devices/board")["alarms"] if a.get("state") == "active"], 60, "raised")
        check(bool(raised), f"raised: {raised[0]['text']}")
        check(not sent_to(OWNER), "nobody is called the moment it is raised")

        print("3. A minute later, the owner's phone")
        first = wait(lambda: sent_to(OWNER), 100, "the owner's call")
        m = first[0]
        btn = (((m.get("reply_markup") or {}).get("inline_keyboard") or [[{}]])[0] or [{}])[0]
        check("nobody has acknowledged it" in m["text"] and "Reset the breaker" in m["text"],
              "the owner's Telegram: " + m["text"].replace("\n", " / ")[:160])
        check(btn.get("text") == "Acknowledge" and str(btn.get("callback_data", "")).startswith("al:"),
              "with an Acknowledge button")
        check(not sent_to(SAM), "Sam isn't called yet")

        print("4. A minute after that, the second chat")
        second = wait(lambda: sent_to(SAM), 100, "Sam's call")
        check(second[0]["text"].startswith("Passed on to you."), "Sam: " + second[0]["text"].replace("\n", " / ")[:120])
        told = wait(lambda: [x for x in sent_to(OWNER) if "it went to Sam" in x["text"]], 20, "the owner told")
        check(bool(told), "and the owner: " + told[0]["text"][:120])

        print("5. Sam taps Acknowledge")
        sbtn = second[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        send("/tap", {"chat": SAM, "name": "Sam", "data": sbtn}, port=TG)
        ack = wait(lambda: [a for a in get("/api/devices/board")["alarms"] if a.get("ack")], 30, "acknowledged")
        check(ack[0]["ack"]["by"] == "Sam on Telegram", "the board: seen by " + ack[0]["ack"]["by"])
        thanks = wait(lambda: [x for x in sent_to(SAM) if x["text"].startswith("✓ Acknowledged")], 20, "Sam answered")
        check(bool(thanks), "Sam is answered: " + thanks[0]["text"][:100])
        heard = wait(lambda: [x for x in sent_to(OWNER) if "Sam on Telegram acknowledged" in x["text"]], 20, "the owner hears")
        check(bool(heard), "the owner hears who took it")
        kinds = [e.get("event") for e in get("/api/network/events")["events"]]
        check(kinds.count("escalated") == 2 and "acknowledged" in kinds, f"Events: {kinds[:8]}")
        asyncio.run(shots_board())
        poke("Compressor", True)
        wait(lambda: not get("/api/devices/board")["alarms"], 60, "cleared")
        check(True, "it clears when the compressor runs again")
        notes.append("Telegram transcript:\n" + "\n".join(
            f"  → {'you' if str(x['chat_id']) == str(OWNER) else 'Sam'}: {x['text']}"
            for x in get("/sent", TG)["sent"] if x["method"] == "sendMessage"))

        print("6. Is a copy kept elsewhere?")
        b = get("/api/backup")
        check(b["offsite"]["kind"] == "none" and b["offsite"]["level"] == "bad", "nothing yet: " + b["offsite"]["line"])
        asyncio.run(shots_backup("backup-nothing-elsewhere"))
        asyncio.run(shots_setup())
        req = urllib.request.Request(BASE + "/api/backup", method="POST",
                                     data=json.dumps({"passphrase": "a long passphrase 1", "workspace": False}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            (work / "machine.bento").write_bytes(r.read())
        b = get("/api/backup")
        check(b["offsite"]["kind"] == "file" and "another disk" in b["offsite"]["line"], "after a download: " + b["offsite"]["line"])
        asyncio.run(shots_backup("backup-made"))
        out = subprocess.run([PY, "-m", "agentos", "network", "alarms", "call"], env=env, cwd=ROOT,
                             capture_output=True, text=True, timeout=120)
        notes.append("$ bento network alarms call\n" + (out.stdout + out.stderr).rstrip())
    finally:
        srv.send_signal(signal.SIGTERM)
        try:
            srv.wait(40)
        except subprocess.TimeoutExpired:
            srv.kill()
        sim.terminate()

    print("8. The terminal")
    lines = [n for n in notes if n.startswith("$ ")]
    notes[:] = [n for n in notes if not n.startswith("$ ")]
    for argv in (["doctor"],):
        out = subprocess.run([PY, "-m", "agentos", *argv], env=env, cwd=ROOT, capture_output=True, text=True, timeout=120)
        text = out.stdout + out.stderr
        if argv == ["doctor"]:
            text = "\n".join(x for x in text.splitlines() if "copy elsewhere" in x or "bento standby pair" in x)
        lines.append("$ bento " + " ".join(argv) + "\n" + text.rstrip())
    out = subprocess.run(["python3", "packaging/audit-vulns.py"], cwd=ROOT, capture_output=True, text=True, timeout=900)
    lines.append("$ python3 packaging/audit-vulns.py\n" + "\n".join(x for x in out.stdout.splitlines()))
    import re
    text = re.sub(r"\x1b\[[0-9;]*m", "", "\n\n".join(lines) + "\n")
    (shots / "terminal.txt").write_text(text)
    print(text)
    check("copy elsewhere:" in text and "no known vulnerability" in text and "then to Sam" in text,
          "the terminal says the same")
    for n in notes:
        print("  ·", n)
    print("FINDINGS:", json.dumps(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
