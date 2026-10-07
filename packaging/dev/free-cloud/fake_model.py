"""A stand-in OpenAI-compatible model that does what the run needs a real one to do:
it calls Bento's real `remember` tool when asked to remember something, and answers a
question from the memories Bento put in its prompt. So "it still knows after a restart"
is decided by what Bento handed the model, not by anything this file keeps.

    python fake_model.py 9304          # serves http://0.0.0.0:9304/v1
"""
import json
import re
import sys
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()


def _text(c):
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c or "")


def _chunk(delta, finish=None):
    return "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk", "created": int(time.time()),
                                  "model": "fake-1", "choices": [{"index": 0, "delta": delta,
                                                                  "finish_reason": finish}]}) + "\n\n"


def _reply(msgs):
    """(text, tool_call) for the conversation so far."""
    if msgs and msgs[-1].get("role") == "tool":
        return "Done. I'll remember that, even after this machine restarts.", None
    user = next((_text(m.get("content")) for m in reversed(msgs) if m.get("role") == "user"), "")
    system = " ".join(_text(m.get("content")) for m in msgs if m.get("role") == "system")
    m = re.match(r"\s*remember(?: that)?\s+(.+)", user, re.I)
    if m:
        return "", {"name": "remember", "arguments": json.dumps({"content": m.group(1).strip().rstrip(".")})}
    if "?" in user:
        mem = re.search(r"=== User memory[^\n]*\n(.*?)\n=== end user memory", system, re.S)
        facts = [ln.lstrip("- ").replace("📌 ", "") for ln in (mem.group(1).splitlines() if mem else []) if ln.strip()]
        if facts:
            return "From what I remember: " + "; ".join(facts) + ".", None
        return "I don't have anything about that in my memory yet.", None
    return "Hello! I'm your Bento, running in the cloud.", None


@app.get("/v1/models")
async def models():
    return {"data": [{"id": "fake-1", "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    text, call = _reply(body.get("messages", []))

    async def gen():
        if call:
            yield _chunk({"role": "assistant", "tool_calls": [{"index": 0, "id": f"call_{int(time.time()*1000)}",
                                                               "type": "function", "function": call}]})
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
        msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": call}]}
    return {"id": "x", "object": "chat.completion", "choices": [{"index": 0, "message": msg,
            "finish_reason": "tool_calls" if call else "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(sys.argv[1]) if len(sys.argv) > 1 else 9304, log_level="warning")
