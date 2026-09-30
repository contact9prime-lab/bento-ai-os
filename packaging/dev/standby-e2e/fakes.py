# ruff: noqa  -- a test script: `from h import *` and one-line steps on purpose
"""A fake OpenAI-compatible provider (:9301) and a fake Telegram Bot API (:9302).
Telegram is modelled the way the real one confirms updates: an update is gone once a
getUpdates call arrives with an offset above its id. Each side of the test uses its own
path prefix (/A, /B) so the log says WHICH machine polled and answered."""
import asyncio, json, time, threading
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn

prov = FastAPI()
CALLS = []

@prov.get('/v1/models')
async def models():
    return {"data": [{"id": "fake-1", "object": "model"}]}

def chunk(delta, finish=None):
    return "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk", "created": int(time.time()),
                                  "model": "fake-1", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n"

@prov.post('/v1/chat/completions')
async def cc(req: Request):
    body = await req.json()
    last = [m for m in body.get('messages', []) if m.get('role') == 'user'][-1:]
    text = (last[0].get('content') if last else '') or ''
    if isinstance(text, list):
        text = ' '.join(p.get('text', '') for p in text if isinstance(p, dict))
    CALLS.append({"at": time.time(), "q": str(text)[:80]})
    ans = f"FAKE-ANSWER to: {str(text)[:40]}"
    if not body.get('stream'):
        return JSONResponse({"id": "x", "object": "chat.completion", "choices": [{"index": 0, "message": {"role": "assistant", "content": ans}, "finish_reason": "stop"}],
                             "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
    async def gen():
        yield chunk({"role": "assistant", "content": ans})
        yield chunk({}, "stop")
        yield "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk", "choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}}) + "\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")

@prov.get('/calls')
async def calls():
    return CALLS

tg = FastAPI()
UPD = []            # pending updates
NEXT = [1000]
POLLS = {}          # side -> [times]
SENT = []           # {side, chat_id, text, at}
SEEN = []           # {side, update_id, at}: which side RECEIVED which update

async def _body(req):
    try:
        return await req.json()
    except Exception:
        try:
            return dict(await req.form())
        except Exception:
            return {}

@tg.api_route('/{side}/bot{token}/{method}', methods=['GET', 'POST'])
async def api(side: str, token: str, method: str, req: Request):
    b = {**dict(req.query_params), **(await _body(req))}
    if method == 'getMe':
        return {"ok": True, "result": {"id": 1, "is_bot": True, "username": "fake_bento_bot", "first_name": "Bento"}}
    if method == 'getUpdates':
        POLLS.setdefault(side, []).append(time.time())
        off = int(b.get('offset') or 0)
        if off:
            UPD[:] = [u for u in UPD if u['update_id'] >= off]      # confirmed
        t0 = time.time()
        while time.time() - t0 < min(float(b.get('timeout') or 0), 3):
            if UPD:
                break
            await asyncio.sleep(0.2)
        out = [u for u in UPD if u['update_id'] >= off]
        for u in out:
            SEEN.append({"side": side, "update_id": u['update_id'], "at": time.time(), "text": u['message']['text']})
        return {"ok": True, "result": out}
    if method in ('sendMessage', 'editMessageText', 'sendPhoto', 'sendDocument'):
        SENT.append({"side": side, "method": method, "chat_id": b.get('chat_id'), "text": str(b.get('text', ''))[:200], "at": time.time()})
        return {"ok": True, "result": {"message_id": len(SENT), "chat": {"id": b.get('chat_id')}, "date": int(time.time())}}
    return {"ok": True, "result": True}

@tg.post('/inject')
async def inject(req: Request):
    b = await req.json()
    NEXT[0] += 1
    UPD.append({"update_id": NEXT[0], "message": {"message_id": NEXT[0], "date": int(time.time()), "text": b["text"],
                "from": {"id": 777, "is_bot": False, "first_name": "Piyush"}, "chat": {"id": 777, "type": "private", "first_name": "Piyush"}}})
    return {"update_id": NEXT[0]}

@tg.get('/log')
async def log():
    now = time.time()
    return {"polls": {s: {"count": len(v), "last_ago": round(now - v[-1], 1)} for s, v in POLLS.items()},
            "sent": SENT, "seen": SEEN, "pending": UPD}

def run(app, port):
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")

threading.Thread(target=run, args=(prov, 9301), daemon=True).start()
run(tg, 9302)
