"""A stand-in OpenAI-compatible brain for the link-files run. Two parts, told apart by the
system prompt, calling the real tools:

  home's lead      -> delegate to analyst@office with data.csv, then says what came back
  office's analyst -> write_file the deck where its task says, then answers naming it

    python brain.py PORT
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
    system = next((_text(m.get("content")) for m in msgs if m.get("role") == "system"), "")
    user = next((_text(m.get("content")) for m in msgs if m.get("role") == "user"), "")
    tool = _text(msgs[-1].get("content")) if msgs and msgs[-1].get("role") == "tool" else None
    if "SOUL-analyst" in system:
        folder = re.search(r"write them in (/\S+) \(or", user)
        got = re.search(r"saved here: `([^`]+)`", user)
        dest = f"{folder.group(1)}/q3-deck.pptx" if folder else "q3-deck.pptx"
        if tool is None:
            src = open(got.group(1)).read() if got else "(no data was sent)"
            return "", {"name": "write_file", "arguments": json.dumps(
                {"path": dest, "content": "Q3 deck\n\nSlide 1: revenue by month\n" + src})}
        return f"The deck is ready: `{dest}`. The old plan is `{OLD}`.", None
    if "make the deck" in user:
        if tool is None:
            return "", {"name": "delegate", "arguments": json.dumps(
                {"subagent": "analyst@office", "task": "Build a Q3 deck from the attached data.",
                 "files": ["data.csv"]})}
        return f"Office made it. {tool[:900]}", None
    return f"heard: {user.strip()[:200]}", None


OLD = sys.argv[2] if len(sys.argv) > 2 else ""


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
                                     "usage": {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52}}) + "\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
