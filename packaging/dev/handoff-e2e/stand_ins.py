"""Stand-ins for the sign-in link's walk (run.py): a site with a sign-in wall, a brain that
asks the real tools, and a Telegram Bot API that records what Bento sends and hands it what
"the person" taps. Nothing here decides anything: the brain only calls Bento's own tools.

    python stand_ins.py <site-port> <brain-port> <telegram-port>
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

SITE, BRAIN, TG = (int(x) for x in sys.argv[1:4])
OUT = Path(sys.argv[4]) if len(sys.argv) > 4 else Path(".")

# ---- a site that wants a password ---------------------------------------------------------
site = FastAPI()
STYLE = """<style>*{box-sizing:border-box}body{margin:0;background:#0d1117;color:#e6edf3;
font:16px -apple-system,Segoe UI,Roboto,sans-serif}.top{height:64px;display:flex;align-items:center;
justify-content:center;font-weight:700;font-size:22px;letter-spacing:-.4px}
.box{position:absolute;left:24px;right:24px;top:96px;height:320px;border:1px solid #30363d;border-radius:12px;background:#161b22}
label{position:absolute;left:44px;font-size:14px;color:#9198a1}
input{position:absolute;left:44px;right:44px;height:48px;border-radius:8px;border:1px solid #30363d;background:#0d1117;
color:#e6edf3;font-size:16px;padding:0 12px}button{position:absolute;left:44px;right:44px;top:340px;height:48px;border:0;
border-radius:8px;background:#238636;color:#fff;font-weight:600;font-size:16px}
.ok{margin:40px 24px;padding:24px;border:1px solid #30363d;border-radius:12px;background:#161b22}</style>"""


@site.get("/login")
async def login():
    return HTMLResponse(f"""<!doctype html><title>Sign in to Hubgit</title><meta name=viewport content="width=device-width">
{STYLE}<div class=top>◆ Hubgit</div><div class=box></div><form method=post action=/session>
<label style="top:124px">Username</label><input name=user style="top:148px" autocomplete=username>
<label style="top:216px">Password</label><input name=pw type=password style="top:240px" autocomplete=current-password>
<button>Sign in</button></form>""")


@site.post("/session")
async def session(request: Request):
    form = await request.form()
    ok = form.get("pw") == "correct-horse-battery"
    r = RedirectResponse("/home" if ok else "/login", status_code=303)
    if ok:
        r.set_cookie("hubgit", str(form.get("user") or "someone"))
    return r


@site.get("/home")
async def home(request: Request):
    who = request.cookies.get("hubgit")
    if not who:
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse(f"""<!doctype html><title>Hubgit</title><meta name=viewport content="width=device-width">
{STYLE}<div class=top>◆ Hubgit</div><div class=ok><h2>Signed in as {who}</h2><p>Your repositories: bento-ai-os</p></div>""")


# ---- a brain that only calls Bento's tools -------------------------------------------------
brain = FastAPI()


def _chunk(delta, finish=None):
    return "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk",
                                  "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n"


@brain.get("/v1/models")
async def models():
    return {"data": [{"id": "fake-1", "object": "model"}]}


@brain.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    msgs = body.get("messages", [])
    called = [tc["function"]["name"] for m in msgs if m.get("role") == "assistant" for tc in (m.get("tool_calls") or [])]
    last = msgs[-1] if msgs else {}
    text, call = "", None
    if last.get("role") != "tool":
        call = ("browser_open", {"url": f"http://hubgit.localhost:{SITE}/login"})
    elif called[-1] == "browser_open":
        call = ("browser_wait_for_person", {"reason": "Sign in to Hubgit so I can push the branch and open the PR.",
                                            "minutes": 10})
    else:
        got = str(last.get("content") or "")
        text = ("You're signed in. I'm pushing the branch and opening the PR now." if "[carry on]" in got
                else "I couldn't get past the sign-in: " + got[:160])

    async def gen():
        if call:
            yield _chunk({"role": "assistant", "tool_calls": [{"index": 0, "id": f"call_{time.time_ns()}", "type": "function",
                                                               "function": {"name": call[0], "arguments": json.dumps(call[1])}}]})
            yield _chunk({}, "tool_calls")
        else:
            yield _chunk({"role": "assistant", "content": text})
            yield _chunk({}, "stop")
        yield "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk", "choices": [],
                                     "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}}) + "\n\n"
        yield "data: [DONE]\n\n"
    if body.get("stream"):
        return StreamingResponse(gen(), media_type="text/event-stream")
    msg = {"role": "assistant", "content": text}
    if call:
        msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function",
               "function": {"name": call[0], "arguments": json.dumps(call[1])}}]}
    return {"id": "x", "object": "chat.completion", "choices": [{"index": 0, "message": msg,
            "finish_reason": "tool_calls" if call else "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


# ---- Telegram's Bot API, recorded ---------------------------------------------------------
tg = FastAPI()
SENT, QUEUE, N = [], [], [0]


@tg.post("/bot{token}/{method}")
async def bot(token: str, method: str, request: Request):
    kind = request.headers.get("content-type", "")
    if "multipart" in kind:
        form = await request.form()
        body = {k: (v if isinstance(v, str) else None) for k, v in form.items()}
        photo = form.get("photo")
        if photo is not None and not isinstance(photo, str):
            N[0] += 1
            name = f"tg-photo-{N[0]}.png"
            (OUT / name).write_bytes(await photo.read())
            body["photo"] = name
        if isinstance(body.get("reply_markup"), str):
            body["reply_markup"] = json.loads(body["reply_markup"])
    else:
        body = await request.json() if await request.body() else {}
    if method == "getMe":
        return {"ok": True, "result": {"id": 42, "is_bot": True, "username": "AOSbot", "first_name": "AOSbot"}}
    if method == "getUpdates":
        for _ in range(20):
            if QUEUE:
                out, QUEUE[:] = list(QUEUE), []
                return {"ok": True, "result": out}
            await asyncio.sleep(0.1)
        return {"ok": True, "result": []}
    if method in ("sendMessage", "sendPhoto"):
        SENT.append({"method": method, "at": time.time(), **body})
    return {"ok": True, "result": {"message_id": len(SENT) + 100}}


@tg.get("/sent")
async def sent():
    return SENT


@tg.post("/inject")
async def inject(request: Request):
    """What the person does in the chat: {"text": …} or {"tap": "bw:open"}."""
    b = await request.json()
    N[0] += 1
    who = {"id": 5150, "first_name": "Ada", "is_bot": False}
    chat = {"id": 5150, "type": "private", "first_name": "Ada"}
    if "tap" in b:
        QUEUE.append({"update_id": 9000 + N[0], "callback_query": {"id": f"cq{N[0]}", "from": who, "data": b["tap"],
                                                                  "message": {"message_id": 1, "chat": chat}}})
    else:
        QUEUE.append({"update_id": 9000 + N[0], "message": {"message_id": 500 + N[0], "from": who, "chat": chat,
                                                           "date": int(time.time()), "text": b["text"]}})
        SENT.append({"method": "from_person", "at": time.time(), "text": b["text"]})
    if "tap" in b:
        SENT.append({"method": "tap", "at": time.time(), "text": b.get("label") or b["tap"]})
    return {"ok": True}


async def main():
    servers = [uvicorn.Server(uvicorn.Config(a, host="127.0.0.1", port=p, log_level="warning"))
               for a, p in ((site, SITE), (brain, BRAIN), (tg, TG))]
    await asyncio.gather(*(s.serve() for s in servers))

if __name__ == "__main__":
    asyncio.run(main())
