"""A stand-in OpenAI-compatible brain for the community run. It says WHICH brain it is
(the name on the command line), so every answer in the run shows whose key paid for it.

  split: A | B          -> calls pool_task with the pieces (the leader's agent splitting work)
  share: some fact      -> calls remember(community=true)
  what does the community know about X? -> calls community_recall
  a worker's piece      -> answers "<brain> did: <piece>"
  anything else         -> "<brain> heard: <text>"

    python fake_brain.py PORT NAME
"""
import json
import re
import sys
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()
NAME = sys.argv[2] if len(sys.argv) > 2 else "brain"
CALLS = []


def _text(c):
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c or "")


def _chunk(delta, finish=None):
    return "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk", "created": int(time.time()),
                                  "model": "fake-1", "choices": [{"index": 0, "delta": delta,
                                                                  "finish_reason": finish}]}) + "\n\n"


def _reply(msgs):
    if msgs and msgs[-1].get("role") == "tool":
        out = _text(msgs[-1].get("content"))
        notes = re.findall(r"^- \[[0-9a-f]+\] \(([^)]*)\) (.+)$", out, re.M)
        if notes:      # community_recall: say it, the way a model would
            return f"{NAME}: the community knows " + "; ".join(f"{t} (from {m})" for m, t in notes) + ".", None
        return f"{NAME}: here is what came back.\n{out}", None
    user = next((_text(m.get("content")) for m in reversed(msgs) if m.get("role") == "user"), "")
    m = re.search(r"hands you this piece of work:\s*(.+)", user, re.S)
    if m:
        return f"{NAME} did: {m.group(1).strip()}", None
    m = re.match(r"\s*split:\s*(.+)", user, re.I)
    if m:
        pieces = [p.strip() for p in m.group(1).split("|") if p.strip()]
        return "", {"name": "pool_task", "arguments": json.dumps({"pieces": pieces})}
    m = re.match(r"\s*share:\s*(.+)", user, re.I)
    if m:
        return "", {"name": "remember", "arguments": json.dumps({"content": m.group(1).strip(), "community": True})}
    m = re.search(r"what does the community know about (.+?)\?", user, re.I)
    if m:
        return "", {"name": "community_recall", "arguments": json.dumps({"query": m.group(1)})}
    return f"{NAME} heard: {user.strip()[:200]}", None


@app.get("/v1/models")
async def models():
    return {"data": [{"id": "fake-1", "object": "model"}]}


@app.get("/__calls")
async def calls():
    return {"calls": CALLS[-50:]}


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    msgs = body.get("messages", [])
    text, call = _reply(msgs)
    CALLS.append({"user": next((_text(m.get("content"))[:120] for m in reversed(msgs) if m.get("role") == "user"), ""),
                  "answer": (text or json.dumps(call))[:120]})

    async def gen():
        if call:
            yield _chunk({"role": "assistant", "tool_calls": [{"index": 0, "id": f"call_{int(time.time()*1000)}",
                                                               "type": "function", "function": call}]})
            yield _chunk({}, "tool_calls")
        else:
            yield _chunk({"role": "assistant", "content": text})
            yield _chunk({}, "stop")
        yield "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk", "choices": [],
                                     "usage": {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52}}) + "\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
