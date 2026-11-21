"""A scripted OpenAI-compatible model for the phone-steps run. Each kind of request gets the
call a real model would make, slowly enough that the phone has something to show:

  the lead, asked to get Finance on it   -> department_task(Finance)
  the Finance desk's master              -> delegate fin-analyst, delegate bookkeeper, finish
  a Finance specialist                   -> save_report, then a line of findings
  a boss signing off / the auditor       -> APPROVE / PASS
  the memory pass, the ethics reviewer   -> nothing to keep / OK

    python brain.py 9461
"""
import asyncio
import json
import re
import sys
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()
PACE = 1.4          # seconds a "model call" takes, so the steps arrive one by one


def _text(c):
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c or "")


def _tools(body):
    return {(t.get("function") or t).get("name") for t in body.get("tools") or []}


def _reply(body):
    msgs = body.get("messages", [])
    tools = _tools(body)
    system = " ".join(_text(m.get("content")) for m in msgs if m.get("role") == "system")
    last = msgs[-1] if msgs else {}
    said = _text(last.get("content"))
    called = [tc["function"]["name"] for m in msgs if m.get("role") == "assistant"
              for tc in (m.get("tool_calls") or [])]
    whole = system + " " + " ".join(_text(m.get("content")) for m in msgs if m.get("role") == "user")
    if said.startswith("<request>"):
        return "OK. An ordinary finance task.", None
    if "memory subsystem" in said:
        return "[]", None
    if re.search(r"PASS.{0,40}CONCERNS.{0,40}FAIL", whole, re.S):
        return "PASS\nThe runway figure traces to the bank balance and the monthly burn.", None
    if re.search(r"APPROVE.{0,80}SEND BACK", whole, re.S):
        return "APPROVE\nThe runway and the plan to extend it are both there.", None
    if "MASTER ORCHESTRATOR" in system:
        if "delegate" not in called:
            return "", ("delegate", {"subagent": "fin-analyst",
                                     "task": "Work out the cash runway from this month's bank balance and burn"})
        if called.count("delegate") == 1:
            return "", ("delegate", {"subagent": "bookkeeper",
                                     "task": "Check the burn against the ledger and list the three biggest costs"})
        if "finish" not in called:
            return "", ("finish", {"summary": "Runway is 14 months at the current burn of 41k a month. "
                                              "The three biggest costs are payroll, cloud and rent; "
                                              "moving cloud to reserved pricing adds about 6 weeks."})
        return "Done.", None
    if last.get("role") == "tool":
        if called and called[-1] == "department_task":
            return ("Finance is done. Your runway is 14 months at a 41k monthly burn. Payroll, cloud and rent "
                    "are the biggest costs, and reserved cloud pricing would add about 6 weeks. "
                    "Their head signed it off and the auditor passed it."), None
        if called and called[-1] == "save_report":
            if "bookkeeper" in system.lower():
                return "Ledger checked: burn is 41k a month; payroll 26k, cloud 8k, rent 4k.", None
            return "Runway: 574k in the bank at 41k a month is about 14 months.", None
        return "Done.", None
    if "department_task" in tools and "finance" in said.lower():
        return "", ("department_task", {"department": "Finance",
                                        "task": "Work out our cash runway this quarter and how to extend it"})
    if "save_report" in tools and "save_report" not in called:
        return "", ("save_report", {"title": "runway-notes", "content": "Working notes for the runway."})
    return "Hello.", None


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
    await asyncio.sleep(PACE)
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
