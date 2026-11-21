"""Stand-ins for the 0.99.0 release run: a scripted OpenAI-compatible brain and Telegram's Bot API.

    python stand_ins.py BRAIN_PORT TG_PORT

The brain records the Authorization header of every call, which is what proves a provider key
opened from the vault reached the provider, after a restart with nobody signed in. It calls one
real tool (mail_search) when asked about mail, so a signed-in-only secret is needed by a step.
Telegram records which bot token polled, and what was sent.
"""
import asyncio
import json
import sys
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

BRAIN, TG = (int(x) for x in sys.argv[1:3])
brain = FastAPI()
CALLS: list[dict] = []


def _text(c):
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c or "")


def _decide(body):
    msgs = body.get("messages", [])
    last = msgs[-1] if msgs else {}
    said = _text(last.get("content"))
    users = [m for m in msgs if m.get("role") == "user"]
    asked = _text(users[-1].get("content")) if users else ""
    if "memory subsystem" in said or said.startswith("<request>"):
        return "[]", None
    if last.get("role") == "tool":
        return f"Your mailbox answered: {said[:140]}", None
    if "mail" in asked.lower():
        return "", ("mail_search", {"query": "invoice", "since_days": 7})
    return "Hello from the stand-in brain. I'm answering with the key this machine keeps in its vault.", None


def _chunk(delta, finish=None):
    return "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk", "created": int(time.time()),
                                  "model": "fake-1", "choices": [{"index": 0, "delta": delta,
                                                                  "finish_reason": finish}]}) + "\n\n"


@brain.get("/v1/models")
async def models(req: Request):
    return {"data": [{"id": "fake-1", "object": "model"}]}


@brain.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    text, call = _decide(body)
    CALLS.append({"auth": req.headers.get("authorization", ""), "call": call and call[0],
                  "text": text[:160], "at": time.time()})
    await asyncio.sleep(0.3)
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


tg = FastAPI()
SENT, QUEUE, POLLED, N = [], [], {}, [0]


@tg.post("/bot{token}/{method}")
async def bot(token: str, method: str, request: Request):
    body = await request.json() if await request.body() else {}
    if method == "getMe":
        return {"ok": True, "result": {"id": 42, "is_bot": True, "username": "BobsBentoBot", "first_name": "Bento"}}
    if method == "getUpdates":
        POLLED[token] = POLLED.get(token, 0) + 1
        for _ in range(20):
            if QUEUE:
                out, QUEUE[:] = list(QUEUE), []
                return {"ok": True, "result": out}
            await asyncio.sleep(0.1)
        return {"ok": True, "result": []}
    if method in ("sendMessage", "sendPhoto", "editMessageText"):
        SENT.append({"method": method, "token": token, "at": time.time(), **body})
    return {"ok": True, "result": {"message_id": len(SENT) + 100}}


@tg.get("/sent")
async def sent():
    return {"sent": SENT, "polled": POLLED}


@tg.post("/inject")
async def inject(request: Request):
    b = await request.json()
    N[0] += 1
    who = {"id": 5150, "first_name": "Bob", "is_bot": False}
    chat = {"id": 5150, "type": "private", "first_name": "Bob"}
    QUEUE.append({"update_id": 9000 + N[0], "message": {"message_id": 500 + N[0], "from": who, "chat": chat,
                                                       "date": int(time.time()), "text": b["text"]}})
    SENT.append({"method": "from_person", "at": time.time(), "text": b["text"]})
    return {"ok": True}


async def main():
    servers = [uvicorn.Server(uvicorn.Config(a, host="127.0.0.1", port=p, log_level="warning"))
               for a, p in ((brain, BRAIN), (tg, TG))]
    await asyncio.gather(*(s.serve() for s in servers))

if __name__ == "__main__":
    asyncio.run(main())
