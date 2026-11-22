"""Stand-ins for the signed-in sites run: a social site, a scripted brain, Telegram's Bot API.

    python stand_ins.py SITE_PORT BRAIN_PORT TG_PORT OUT_DIR

Postly (the site) has what a real one has where it matters: a sign-in that wants a code sent
to your phone, a feed, and a post form with a picture field, a caption and a Share button. The
brain only calls Bento's real tools, choosing each from the words the tools gave back, so every
step goes through the gate. Telegram records what was sent and takes what the person "does".
"""
import asyncio
import json
import re
import sys
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

SITE, BRAIN, TG = (int(x) for x in sys.argv[1:4])
OUT = Path(sys.argv[4])
CODE = "481516"
HOST = f"postly.localhost:{SITE}"

# ---- Postly -------------------------------------------------------------------------------
site = FastAPI()
POSTS: list[dict] = [{"by": "bento", "caption": "Hello from Bento's first week.", "picture": 0, "at": "Mon"}]
SESSIONS: set = set()
PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">
<title>{title}</title><style>body{{font:16px system-ui;max-width:560px;margin:24px auto;padding:0 16px}}
.post{{border:1px solid #ddd;border-radius:12px;padding:12px;margin:10px 0}}button{{font:inherit;padding:8px 16px}}
textarea{{width:100%;height:70px;font:inherit}}</style>{body}"""


def _in(request: Request) -> bool:
    return request.cookies.get("postly") in SESSIONS


@site.get("/", response_class=HTMLResponse)
async def home(request: Request):
    if not _in(request):
        return PAGE.format(title="Postly", body="<h1>Postly</h1><p>Share what you make.</p>"
                                                "<p><a href='/login'>Log in</a></p>")
    feed = "".join(f"<div class=post><b>@{p['by']}</b> · {p['at']}<p>{p['caption']}</p>"
                   f"{'<p>🖼 picture, ' + str(p['picture']) + ' bytes</p>' if p['picture'] else ''}</div>"
                   for p in reversed(POSTS))
    return PAGE.format(title="Postly · @bento", body=f"""<h1>@bento</h1>
<form method=post action=/post enctype=multipart/form-data>
<label>Picture <input type=file name=picture accept="image/*"></label>
<textarea name=caption aria-label="Write a caption…"></textarea>
<button type=submit>Share</button></form>
<h2>Your posts</h2>{feed}""")


@site.get("/login", response_class=HTMLResponse)
async def login_page():
    return PAGE.format(title="Log in · Postly", body="""<h1>Log in to Postly</h1>
<p>We sent a code to your phone. Enter the code to continue.</p>
<form method=post action=/login><input name=code autocomplete="one-time-code" placeholder="6-digit code">
<button type=submit>Continue</button></form>""")


@site.post("/login")
async def login(request: Request):
    form = await request.form()
    if str(form.get("code") or "").strip() != CODE:
        return RedirectResponse("/login", status_code=303)
    sid = f"s{len(SESSIONS) + 1}"
    SESSIONS.add(sid)
    r = RedirectResponse("/", status_code=303)
    r.set_cookie("postly", sid, httponly=True)
    return r


@site.post("/post")
async def post(request: Request):
    if not _in(request):
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    pic = form.get("picture")
    size = len(await pic.read()) if pic is not None and not isinstance(pic, str) else 0
    POSTS.append({"by": "bento", "caption": str(form.get("caption") or ""), "picture": size, "at": "today"})
    return RedirectResponse("/", status_code=303)


@site.get("/api/posts")
async def posts():
    return POSTS


# ---- the brain ----------------------------------------------------------------------------
brain = FastAPI()
CALLS: list[dict] = []


def _text(c):
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c or "")


def _ref(words: str, pattern: str) -> int | None:
    m = re.search(r"\[(\d+)\] " + pattern, words)
    return int(m.group(1)) if m else None


def _decide(body):
    msgs = body.get("messages", [])
    system = " ".join(_text(m.get("content")) for m in msgs if m.get("role") == "system")
    last = msgs[-1] if msgs else {}
    said = _text(last.get("content"))
    called = [tc["function"]["name"] for m in msgs if m.get("role") == "assistant"
              for tc in (m.get("tool_calls") or [])]
    tools = {(t.get("function") or t).get("name") for t in body.get("tools") or []}
    if said.startswith("<request>"):
        return "OK. Posting on the person's own account.", None
    if "memory subsystem" in said:
        return "[]", None
    if re.search(r"PASS.{0,40}CONCERNS.{0,40}FAIL", " ".join(_text(m.get("content")) for m in msgs), re.S):
        return "PASS\nOne post went up with the person's yes.", None
    if "MASTER ORCHESTRATOR" in system:
        if "delegate" not in called:
            return "", ("delegate", {"subagent": "operator",
                                     "task": f"Post today's picture post.png from the workspace on http://{HOST}/ "
                                             "with the caption 'Day 8: Bento now runs your social account.'"})
        if "finish" not in called:
            return "", ("finish", {"summary": "Today's post is up on Postly, after your yes."})
        return "Done.", None
    if "browser_open" in tools:
        if not called:
            return "", ("browser_open", {"url": f"http://{HOST}/login"})
        out = said
        if called[-1] == "browser_open" and ("one-time-code" in out or "Enter the code" in out):
            return "", ("browser_wait_for_person", {"reason": "Postly wants the code it sent to your phone"})
        if called[-1] in ("browser_open", "browser_wait_for_person") and "Share" in out:
            return "", ("browser_upload", {"path": "post.png"})
        if called[-1] == "browser_upload":
            ref = _ref(out, r"textarea(?:\[\w+\])? Write a caption")
            return "", ("browser_type", {"ref": ref, "text": "Day 8: Bento now runs your social account."})
        if called[-1] == "browser_type":
            ref = _ref(out, r"button(?:\[\w+\])? Share")
            return "Posting the picture with the caption 'Day 8: Bento now runs your social account.'", \
                ("browser_click", {"ref": ref})
        if called[-1] == "browser_click":
            return "Posted: today's picture with its caption is on Postly.", None
        return f"I stopped: {out[:200]}", None
    return "Done.", None


def _chunk(delta, finish=None):
    return "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk", "created": int(time.time()),
                                  "model": "fake-1", "choices": [{"index": 0, "delta": delta,
                                                                  "finish_reason": finish}]}) + "\n\n"


@brain.get("/v1/models")
async def models():
    return {"data": [{"id": "fake-1", "object": "model"}]}


@brain.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    text, call = _decide(body)
    CALLS.append({"call": call and call[0], "args": call and call[1], "text": text[:120]})
    await asyncio.sleep(0.6)
    if call:
        call = {"name": call[0], "arguments": json.dumps(call[1])}

    async def gen():
        if text:
            yield _chunk({"role": "assistant", "content": text})
        if call:
            yield _chunk({"role": "assistant", "tool_calls": [{"index": 0, "id": f"call_{time.time_ns()}",
                                                               "type": "function", "function": call}]})
            yield _chunk({}, "tool_calls")
        else:
            yield _chunk({}, "stop")
        yield "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk", "choices": [],
                                     "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}}) + "\n\n"
        yield "data: [DONE]\n\n"
    if body.get("stream"):
        return StreamingResponse(gen(), media_type="text/event-stream")
    msg = {"role": "assistant", "content": text or None}
    if call:
        msg["tool_calls"] = [{"id": "call_1", "type": "function", "function": call}]
    return {"id": "x", "object": "chat.completion", "choices": [{"index": 0, "message": msg,
            "finish_reason": "tool_calls" if call else "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


@brain.get("/calls")
async def calls():
    return CALLS


# ---- Telegram's Bot API -------------------------------------------------------------------
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
        return {"ok": True, "result": {"id": 42, "is_bot": True, "username": "BentoBot", "first_name": "Bento"}}
    if method == "getUpdates":
        for _ in range(20):
            if QUEUE:
                out, QUEUE[:] = list(QUEUE), []
                return {"ok": True, "result": out}
            await asyncio.sleep(0.1)
        return {"ok": True, "result": []}
    if method in ("sendMessage", "sendPhoto", "editMessageText", "editMessageReplyMarkup"):
        SENT.append({"method": method, "at": time.time(), **body})
    return {"ok": True, "result": {"message_id": len(SENT) + 100}}


@tg.get("/sent")
async def sent():
    return SENT


@tg.post("/inject")
async def inject(request: Request):
    """What the person does in the chat: {"text": …} or {"tap": "ap:…:1"}."""
    b = await request.json()
    N[0] += 1
    who = {"id": 5150, "first_name": "Ada", "is_bot": False}
    chat = {"id": 5150, "type": "private", "first_name": "Ada"}
    if "tap" in b:
        QUEUE.append({"update_id": 9000 + N[0], "callback_query": {"id": f"cq{N[0]}", "from": who, "data": b["tap"],
                                                                  "message": {"message_id": 1, "chat": chat}}})
        SENT.append({"method": "tap", "at": time.time(), "text": b.get("label") or b["tap"]})
    else:
        QUEUE.append({"update_id": 9000 + N[0], "message": {"message_id": 500 + N[0], "from": who, "chat": chat,
                                                           "date": int(time.time()), "text": b["text"]}})
        SENT.append({"method": "from_person", "at": time.time(), "text": b["text"]})
    return {"ok": True}


async def main():
    servers = [uvicorn.Server(uvicorn.Config(a, host="127.0.0.1", port=p, log_level="warning"))
               for a, p in ((site, SITE), (brain, BRAIN), (tg, TG))]
    await asyncio.gather(*(s.serve() for s in servers))

if __name__ == "__main__":
    asyncio.run(main())
