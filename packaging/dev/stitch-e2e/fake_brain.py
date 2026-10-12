"""A scripted OpenAI-compatible model for the stitched end-to-end walk.

It never decides anything on its own: each request type maps to the real Bento tool that
does it, so every hand-off in the walk goes through the actual gate, ledger and broadcasts.

    python fake_brain.py 9411
"""
import json
import re
import sys
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()
LOG = []


def _text(c):
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c or "")


APP_HTML = """<!doctype html><html><head><title>Volume Tracker</title></head><body>
<h1>Volume Tracker</h1>
<button id="fetch" onclick="go('fetch')">Fetch</button>
<button id="save" onclick="go('save')">Save file</button>
<button id="ai" onclick="go('ai')">Ask AI</button>
<pre id="out">ready</pre>
<script>
async function go(k){
  const o=document.getElementById('out');
  let r;
  if(k==='fetch') r=await appTool('fetch_url',{url:location.origin+'/login'});
  if(k==='save') r=await appTool('write_file',{path:'app-wrote.txt',content:'from the app'});
  if(k==='ai') r=await appLLM('Say hello from the app');
  o.textContent=k+': '+JSON.stringify(r).slice(0,300);
}
</script></body></html>"""


def _tools(body):
    return {(t.get("function") or t).get("name") for t in body.get("tools") or []}


def _reply(body):
    msgs = body.get("messages", [])
    tools = _tools(body)
    system = " ".join(_text(m.get("content")) for m in msgs if m.get("role") == "system")
    user = next((_text(m.get("content")) for m in reversed(msgs) if m.get("role") == "user"), "")
    last = msgs[-1] if msgs else {}
    called = [tc["function"]["name"] for m in msgs if m.get("role") == "assistant"
              for tc in (m.get("tool_calls") or [])]

    # a flow's master: delegate once to the first roster member, then finish
    if "MASTER ORCHESTRATOR" in system:
        roster = re.findall(r"^\s+- ([\w.@-]+):", system.split("Your roster")[1], re.M) if "Your roster" in system else []
        if "delegate" not in called and roster:
            return "", ("delegate", {"subagent": roster[0], "task": "Find three headlines about solar power today and file the best one in the Brief."})
        if "finish" not in called:
            return "", ("finish", {"summary": "Three solar headlines were gathered and the best one is in your Brief."})
        return "Mission complete.", None

    if last.get("role") == "tool":
        if called and called[-1] == "create_flow":
            return "I drafted the mission. It is off until you enable it in Missions.", None
        if called and called[-1] == "create_app":
            return "Your app is built. Open it from App Studio.", None
        return "Done.", None

    low = user.lower()
    # a specialist inside a mission run files its result
    if "brief_item" in tools and "headline" in low:
        return "", ("brief_item", {"kind": "fyi", "title": "Solar output records a new high",
                                   "body": "Three headlines checked; this one matters most.",
                                   "key": "solar-headline-1"})
    if "write_file" in tools and "note" in low:
        return "", ("write_file", {"path": "notes/e2e-note.md", "content": "A note from the walk.\n"})
    if "create_app" in tools and "build" in low:
        return "", ("create_app", {"name": "Volume Tracker", "description": "Tracks volumes",
                                   "html": APP_HTML})
    if "create_flow" in tools and "mission" in low:
        return "", ("create_flow", {"name": "solar-news", "mission": "Every morning find solar power headlines and file the best one in my Brief.",
                                    "roster": ["researcher"], "description": "Morning solar headlines",
                                    "triggers": [{"kind": "cron", "config": {"type": "daily", "at": "08:00"}}]})
    if "schedule_task" in tools and "schedule" in low:
        return "", ("schedule_task", {"prompt": "Refresh the volumes", "schedule_type": "interval",
                                      "interval_minutes": 10, "app": "Volume Tracker"})
    if "delegate" in tools and ("hand" in low or "ask the researcher" in low):
        return "", ("delegate", {"subagent": "researcher", "task": "Summarise what a volume tracker is in one line."})
    if "summarise what a volume tracker" in low:
        return "A volume tracker counts how much of a stock traded in a period.", None
    return "Hello from the stand-in brain.", None


def _chunk(delta, finish=None):
    return "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk", "created": int(time.time()),
                                  "model": "fake-1", "choices": [{"index": 0, "delta": delta,
                                                                  "finish_reason": finish}]}) + "\n\n"


@app.get("/v1/models")
async def models():
    return {"data": [{"id": "fake-1", "object": "model"}]}


@app.get("/log")
async def log():
    return LOG


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    text, call = _reply(body)
    LOG.append({"tools": sorted(_tools(body)), "call": call and call[0], "text": text[:80],
                "user": next((_text(m.get("content")) for m in reversed(body.get("messages", [])) if m.get("role") == "user"), "")[:80]})
    if call:
        call = {"name": call[0], "arguments": json.dumps(call[1])}

    async def gen():
        if call:
            yield _chunk({"role": "assistant", "tool_calls": [{"index": 0, "id": f"call_{time.time_ns()}",
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
            "finish_reason": "tool_calls" if call else "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
