"""A stand-in OpenAI-compatible brain for the Zero run. It plays three parts, told apart by
what the system prompt says, and calls the real tools:

  the Zero's lead   ("THIS MACHINE IS A ZERO")  -> delegate the task to lead@<hub>
  the hub's lead    ("is the lead of the linked team", or a Zero's chat run there: "a small
                    machine this hub set up")  -> delegate to the writer, saying
                    where the Zero's files go (the folder the prompt names)
  the writer        ("WRITER-SOUL")  -> write_file into that folder
  after a tool      -> says what came back, naming any path it was given

    python zero_brain.py PORT
"""
import json
import re
import sys
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()
CALLS = []


def _text(c):
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c or "")


def _chunk(delta, finish=None):
    return "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk", "created": int(time.time()),
                                  "model": "fake-1", "choices": [{"index": 0, "delta": delta,
                                                                  "finish_reason": finish}]}) + "\n\n"


def _call(name, args):
    return "", {"name": name, "arguments": json.dumps(args)}


def _reply(msgs):
    system = next((_text(m.get("content")) for m in msgs if m.get("role") == "system"), "")
    user = next((_text(m.get("content")) for m in msgs if m.get("role") == "user"), "")
    every = system + "\n" + user
    tool = _text(msgs[-1].get("content")) if msgs and msgs[-1].get("role") == "tool" else None
    folder = re.search(r"go in (/\S+?) or through save_report", every)
    if "WRITER-SOUL" in system:
        if tool is None:
            m = re.search(r"into (/\S+)", user)
            return _call("write_file", {"path": m.group(1) if m else "kitchen-plan.md",
                                        "content": "# Kitchen plan\n\n- eggs\n- milk\n- coffee\n"})
        return f"writer: {tool[:200]}", None
    last = next((_text(m.get("content")) for m in reversed(msgs) if m.get("role") == "user"), "")
    if last.strip().startswith("Say:"):
        return last.strip()[4:].strip(), None                 # a scheduled job firing: its words
    said = " ".join(_text(m.get("content")) for m in msgs if m.get("role") == "user").lower()
    if "remind me" in said and "a small machine this hub set up" in every:
        # a schedule asked for at a Zero: a one-off, due at once, so a run sees it fire
        if tool is None:
            return _call("schedule_task", {"prompt": "Say: time for tea, the kettle is on",
                                           "schedule_type": "once", "delay_minutes": 0})
        return f"Done: {tool[:200]}", None
    if "on my screen" in last.lower():
        # a person at a Zero asking for widgets: the tool, then what it said
        if tool is None:
            return _call("screen_face", {"new_face": {"name": "Kitchen", "layout": "board",
                                                      "widgets": ["clock", "timer", "quote"]}})
        return f"Done: {tool[:300]}", None
    if "is the lead of the linked team" in every or "a small machine this hub set up" in every:
        if tool is None and last.strip().lower().startswith("thanks"):
            return "You're welcome.", None        # a follow-up in the same session: nothing to make
        if tool is None:
            dest = f"{folder.group(1)}/kitchen-plan.md" if folder else "kitchen-plan.md"
            return _call("delegate", {"subagent": "writer", "task": f"write the kitchen plan into {dest}"})
        dest = f"{folder.group(1)}/kitchen-plan.md" if folder else ""
        return f"The hub's writer made the plan: `{dest}`", None
    m = re.search(r'"subagent": "(lead@[\w.-]+)"', system)
    if m:
        if tool is None:
            return _call("delegate", {"subagent": m.group(1), "task": user.strip()})
        kept = " [its memory came from the hub]" if "Your memory is kept on" in system else ""
        return f"The hub did it.{kept} {tool[:600]}", None
    return f"heard: {user.strip()[:200]}", None


@app.get("/v1/models")
async def models():
    return {"data": [{"id": "fake-1", "object": "model"}]}


@app.get("/__calls")
async def calls():
    return {"calls": CALLS[-200:]}


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    msgs = body.get("messages", [])
    text, call = _reply(msgs)
    system = next((_text(m.get("content")) for m in msgs if m.get("role") == "system"), "")
    # which tools this request was offered, and whose prompt it was: the per-account run
    # reads these to see whose integrations answered a Zero
    CALLS.append({"answer": (text or json.dumps(call))[:160],
                  "tools": [t.get("function", {}).get("name") for t in body.get("tools") or []],
                  "linked_lead": "is the lead of the linked team" in (system + " ".join(
                      _text(m.get("content")) for m in msgs if m.get("role") == "user")),
                  "writer": "WRITER-SOUL" in system,
                  "agent": (re.search(r"You are (\w+)", system) or [None, ""])[1]})

    async def gen():
        # "take your time" in what was said: a slow answer, so a screenshot can catch the
        # work while it is happening (the Office, the device map)
        if "take your time" in " ".join(_text(m.get("content")) for m in msgs if m.get("role") == "user"):
            import asyncio
            await asyncio.sleep(8)
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
