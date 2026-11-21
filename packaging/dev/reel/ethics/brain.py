"""A scripted OpenAI-compatible model for the ethics reel.

It asks for exactly the steps the reel shows, so every refusal and every typed
confirmation on screen is the real gate's answer, not a mock:

  "scan ..."    -> run_command nmap over a whole range (refused: not your machines)
  "clean up ..." -> run_command rm -rfv photos (640 of your own files: type to confirm)

    python brain.py 9431
"""
import asyncio
import json
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


def _reply(body):
    msgs = body.get("messages", [])
    user = next((_text(m.get("content")) for m in reversed(msgs) if m.get("role") == "user"), "").lower()
    last = msgs[-1] if msgs else {}
    said = _text(last.get("content"))
    if said.startswith("<request>"):                 # the ethics reviewer reading a step
        return "OK. The person asked to delete their own photos and the check showed what goes.", None
    if "memory subsystem" in said:                   # the auto-learn pass after a turn
        return "[]", None
    if "ended without delivering" in said:           # the unfinished-reply nudge after a silent rm
        return "The photos folder is deleted: all 640 files are gone, and rm printed nothing because it worked.", None
    if last.get("role") == "tool":
        out = _text(last.get("content")).lower()
        if "scan" in user or "nmap" in out:
            return ("I can't run that scan. Bento refused it: those addresses aren't shown to be yours, "
                    "and saying it's authorised doesn't change that. Point me at one machine you own and I'll check it."), None
        if "denied" in out or "refused" in out or "declined" in out:
            return "Okay, I left the photos folder alone.", None
        return "Done. The photos folder is deleted: all 640 files are gone.", None
    if "scan" in user:
        return "", ("run_command", {"command": "nmap -sS -p- 203.0.113.0/24"})
    if "clean up" in user or "delete" in user:
        return "", ("run_command", {"command": "rm -rfv photos"})
    return "Hi! What should we do?", None


def _chunk(delta, finish=None):
    return "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk", "created": int(time.time()),
                                  "model": "fake-1", "choices": [{"index": 0, "delta": delta,
                                                                  "finish_reason": finish}]}) + "\n\n"


@app.get("/v1/models")
async def models():
    return {"data": [{"id": "fake-1", "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    text, call = _reply(body)
    if call:
        call = {"name": call[0], "arguments": json.dumps(call[1])}

    async def gen():
        if call:
            yield _chunk({"role": "assistant", "tool_calls": [{"index": 0, "id": f"call_{time.time_ns()}",
                                                               "type": "function", "function": call}]})
            yield _chunk({}, "tool_calls")
        else:
            # stream the words so the reply types out on screen
            yield _chunk({"role": "assistant", "content": ""})
            for w in text.split(" "):
                yield _chunk({"content": w + " "})
                await asyncio.sleep(0.04)
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
            "finish_reason": "tool_calls" if call else "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
