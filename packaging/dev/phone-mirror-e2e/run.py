"""A chat started on Telegram, carried on at the desk, and back on Telegram: what the phone sees.

    .venv/bin/python packaging/dev/phone-mirror-e2e/run.py WORKDIR

A real `bento serve` on a throwaway home, a scripted model (it answers "Answer to: <question>")
and a stand-in Telegram (AGENTOS_TELEGRAM_API) that keeps every message. The phone says one
thing, the desk says one thing in that same chat over the socket, then the phone says one more.
The run checks the phone received the desk's question and answer between its own two turns,
and renders what the phone showed as a transcript, photographed at 390 px and 1440x900.
"""
import asyncio
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

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

ROOT = Path(__file__).resolve().parents[3]
PY = str(ROOT / ".venv" / "bin" / "python")
PORT, BRAIN, TG = 8671, 9471, 9472
CHAT = 778

tg, brain = FastAPI(), FastAPI()
UPD: list = []
SEEN: list = []      # what the phone shows: {who, text, at}
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
        SEEN.append({"who": "bot", "text": str(b.get("text") or ""), "at": time.time()})
        return {"ok": True, "result": {"message_id": NEXT[0], "chat": {"id": CHAT}, "date": int(time.time())}}
    return {"ok": True, "result": True}


@brain.get("/v1/models")
async def models():
    return {"data": [{"id": "fake-1", "object": "model"}]}


@brain.post("/v1/chat/completions")
async def complete(req: Request):
    body = await req.json()
    last = next((m for m in reversed(body.get("messages") or []) if m.get("role") == "user"), {})
    c = last.get("content")
    q = " ".join(p.get("text", "") for p in c if isinstance(p, dict)) if isinstance(c, list) else str(c or "")
    text = "Answer to: " + q.strip().splitlines()[-1][:120] if q.strip() else "Hello."
    chunk = lambda d, f=None: "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk", "model": "fake-1",
                                                     "choices": [{"index": 0, "delta": d, "finish_reason": f}]}) + "\n\n"

    async def gen():
        yield chunk({"role": "assistant", "content": text})
        yield chunk({}, "stop")
        yield "data: [DONE]\n\n"
    if body.get("stream"):
        return StreamingResponse(gen(), media_type="text/event-stream")
    return {"id": "x", "object": "chat.completion", "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": text}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


def say(text):
    NEXT[0] += 1
    SEEN.append({"who": "me", "text": text, "at": time.time()})
    UPD.append({"update_id": NEXT[0], "message": {
        "message_id": NEXT[0], "date": int(time.time()), "text": text,
        "from": {"id": CHAT, "is_bot": False, "first_name": "Piyush"},
        "chat": {"id": CHAT, "type": "private", "first_name": "Piyush"}}})


def wait_for(pred, secs=60):
    t0 = time.time()
    while time.time() - t0 < secs:
        if pred():
            return True
        time.sleep(0.3)
    return False


async def desk_turn(cid: str, text: str):
    import websockets
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws") as ws:
        await ws.send(json.dumps({"type": "chat", "text": text, "conversation_id": cid, "origin": "user"}))
        t0 = time.time()
        while time.time() - t0 < 60:
            ev = json.loads(await asyncio.wait_for(ws.recv(), 60))
            if ev.get("type") == "turn_end" and ev.get("conversation_id") == cid:
                return


def page(items, title):
    rows = "".join(f'<div class="b {"me" if i["who"] == "me" else "bot"}">{html.escape(i["text"])}</div>' for i in items)
    return f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">
<title>{html.escape(title)}</title><style>
:root{{color-scheme:light}}body{{margin:0;background:#d9e7d0;font:15px/1.4 system-ui,sans-serif}}
header{{background:#517da2;color:#fff;padding:14px 16px;font-weight:600}}
main{{max-width:560px;margin:0 auto;padding:12px 10px 40px;display:flex;flex-direction:column;gap:8px}}
.b{{white-space:pre-wrap;padding:8px 10px;border-radius:12px;max-width:86%;box-shadow:0 1px 1px rgba(0,0,0,.12)}}
.me{{align-self:flex-end;background:#effdde}}.bot{{align-self:flex-start;background:#fff}}
</style><header>Bento · {html.escape(title)}</header><main>{rows}</main>"""


def shoot(path: Path, out: Path):
    """Chrome's own headless screenshot: no Playwright needed."""
    chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    if not chrome:
        print("no Chrome here: the transcript is", path)
        return
    for tag, size in (("phone", "390,844"), ("wide", "1440,900")):
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
                        f"--user-data-dir={out / ('chrome-' + tag)}", f"--window-size={size}",
                        f"--screenshot={out / (tag + '-telegram.png')}", path.as_uri()],
                       capture_output=True, timeout=60)


def main():
    work = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/phone-mirror-e2e")
    home, shots = work / "home", work / "shots"
    shutil.rmtree(home, ignore_errors=True)
    (home / "work").mkdir(parents=True)
    shots.mkdir(parents=True, exist_ok=True)
    for app, port in ((tg, TG), (brain, BRAIN)):
        threading.Thread(target=lambda a=app, p=port: uvicorn.run(a, host="127.0.0.1", port=p, log_level="warning"),
                         daemon=True).start()
    env = {k: v for k, v in os.environ.items() if "PROXY" not in k.upper() and not k.startswith("AGENTOS_")}
    env.update(AGENTOS_HOME=str(home), AGENTOS_VAULT_KEYRING="0", NO_PROXY="127.0.0.1,localhost",
               AGENTOS_TELEGRAM_API=f"http://127.0.0.1:{TG}")
    (home / "config.json").write_text(json.dumps({
        "agent_name": "Aria", "setup_complete": True, "permissions_migrated": True, "engine": "aria",
        "default_model": "custom/fake-1", "workspace": str(home / "work"), "autonomy": "full",
        "pricing": {"custom/fake-1": {"input": 0, "output": 0}},
        "telegram": {"enabled": True, "bot_token": "1:T", "owner_chat_id": CHAT, "status_messages": False},
        "providers": {"custom": {"enabled": True, "base_url": f"http://127.0.0.1:{BRAIN}/v1",
                                 "api_key": "", "models": ["fake-1"]}}}))
    subprocess.run([PY, "-c", f"from agentos.memory import Store; s=Store(); "
                    f"s.tg_upsert_chat({CHAT}, 'Piyush', '', 'private'); s.tg_set_allowed({CHAT}, 1, by='the run')"],
                   env=env, cwd=ROOT, check=True)
    srv = subprocess.Popen([PY, "-m", "agentos", "serve", "--port", str(PORT), "--no-browser",
                            "--if-running", "fail"], env=env, cwd=ROOT,
                           stdout=open(work / "server.log", "w"), stderr=subprocess.STDOUT)
    bad = []
    try:
        wait_for(lambda: _up(), 90)
        time.sleep(4)                                   # the bridge's first poll
        say("What's on my plate this week?")
        if not wait_for(lambda: any(s["who"] == "bot" and "plate" in s["text"] for s in SEEN)):
            bad.append("the phone's first question got no answer")
        cid = subprocess.run([PY, "-c", f"from agentos.memory import Store; s=Store(); "
                              f"print(next(c['conversation_id'] for c in s.tg_list_chats() if c['chat_id']=={CHAT}))"],
                             env=env, cwd=ROOT, capture_output=True, text=True).stdout.strip()
        n = len(SEEN)
        asyncio.run(desk_turn(cid, "Move the Friday review to Monday"))
        if not wait_for(lambda: len([s for s in SEEN[n:] if s["who"] == "bot"]) >= 2, 20):
            bad.append("the desk turn did not reach the phone")
        mirrored = [s["text"] for s in SEEN[n:]]
        if not (mirrored and "at the desk" in mirrored[0] and "Friday review" in mirrored[0]):
            bad.append(f"the desk's question was not shown first: {mirrored[:1]}")
        if not any("Answer to: Move the Friday review" in t for t in mirrored[1:2]):
            bad.append(f"the desk's answer was not shown: {mirrored[1:2]}")
        say("And who is coming to it?")
        if not wait_for(lambda: any(s["who"] == "bot" and "who is coming" in s["text"] for s in SEEN)):
            bad.append("the phone's follow-up got no answer")
        for s in SEEN:
            print(f"{s['who']:>3}: {s['text'][:100]!r}")
        out = work / "telegram.html"
        out.write_text(page(SEEN, "Telegram"))
        shoot(out, shots)
    finally:
        srv.terminate()
        srv.wait(10)
    print("FINDINGS:", bad or "none")
    sys.exit(1 if bad else 0)


def _up():
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/platform", timeout=2)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    main()
