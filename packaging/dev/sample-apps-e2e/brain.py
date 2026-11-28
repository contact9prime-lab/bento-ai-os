"""A stand-in OpenAI-compatible model for the sample apps' live run.

It answers each app's AI feature with a fixed, realistic reply picked from the prompt,
streamed in small chunks like a real model, so the screenshots show the apps working
and the run needs no key. It decides nothing: the apps parse what it says exactly as
they would a real model's answer.

    python brain.py 9431
"""
import asyncio
import json
import sys
import time
from datetime import date, timedelta

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()


def _text(c):
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c or "")


def _day(n):
    return (date.today() + timedelta(days=n)).isoformat()


def _answer(body) -> str:
    msgs = body.get("messages") or []
    allt = "\n".join(_text(m.get("content")) for m in msgs)
    if "Turn the task into JSON" in allt:
        return json.dumps({"title": "Send Sam the invoice", "due": _day(3), "priority": "high",
                           "note": "Sam asked for it before the end of the week"})
    if "Break the task into" in allt:
        return json.dumps(["Shortlist three venues near the station", "Ask each for a quote for thirty people",
                           "Check the dates against the team calendar", "Book the best one and send the invite"])
    if "Pick the one or two I should do next" in allt:
        return ("Fix the signup bug on mobile first: it was due yesterday and it is urgent, so every day it waits "
                "costs signups.\nThen send Sam the March invoice, which is due today.\nYou have two things in Doing; "
                "finish the bug before you pull the pricing copy forward.")
    if "List the action items" in allt:
        return json.dumps([{"text": "Update the pricing page copy with the annual plan", "who": "Ben", "due": _day(3)},
                           {"text": "Find a support contractor for launch week", "who": "Chloe", "due": _day(5)},
                           {"text": "Draft both versions of the customer email", "who": "Ana", "due": ""}])
    if "Write the minutes" in allt:
        return ("The team agreed to launch on the 14th and to add a support contractor for launch week. "
                "Pricing copy will be updated for the new annual plan.\n\nDecisions:\n- Launch on the 14th\n"
                "- Add one support contractor for two weeks\n\nOpen questions:\n- Email existing customers before "
                "or after the launch post?")
    if "You plan a realistic workday" in allt:
        return json.dumps([
            {"from": "09:00", "to": "09:30", "name": "Standup", "kind": "meet"},
            {"from": "09:30", "to": "11:30", "name": "Finish the proposal draft", "kind": "focus"},
            {"from": "11:30", "to": "11:45", "name": "Walk", "kind": "break"},
            {"from": "11:45", "to": "12:30", "name": "Reply to the three client emails", "kind": "admin"},
            {"from": "12:30", "to": "13:30", "name": "Lunch", "kind": "break"},
            {"from": "13:30", "to": "15:00", "name": "Plan next week's sprint", "kind": "focus"}])
    if "In three short lines" in allt:
        return ("Went well: the proposal draft got your best two hours.\nSlipped: the client emails ran into "
                "lunch, so the afternoon started late.\nTomorrow: send the proposal before you open your inbox.")
    if "As my coach" in allt:
        return ("Reading is going really well: you have barely missed a day in four weeks.\n"
                "The one that slips is No phone after 10pm, mostly on Fridays and Saturdays.\n"
                "One small change: put the phone on the charger in the kitchen at 9:45 on weekends.")
    if "Give me three small, concrete steps" in allt:
        return ("1. Reread last quarter's update and list the three headline numbers (5 min)\n"
                "2. Write one paragraph per number: what happened and why (15 min)\n"
                "3. Add a closing line on next quarter's focus (5 min)\n\nDone looks like: a rough draft you "
                "could send to one person for comments.")
    if "Here are my focus sessions" in allt:
        return ("- Most of your time went to Draft the quarterly update and Review the design doc.\n"
                "- Your best day was Tuesday, with five sessions.\n- You focus more before lunch: most sessions "
                "start before noon.\n- Tomorrow: protect your first two hours for the quarterly update.")
    return "Here's what I'd do: start with the thing that is due soonest, and keep the rest for later."


def _chunk(delta, finish=None):
    return "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk",
                                  "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n"


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [{"id": "stand-in", "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    text = _answer(body)
    if body.get("stream"):
        async def gen():
            yield _chunk({"role": "assistant", "content": ""})
            for i in range(0, len(text), 24):
                yield _chunk({"content": text[i:i + 24]})
                await asyncio.sleep(0.02)
            yield _chunk({}, "stop")
            yield "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk", "choices": [],
                                         "usage": {"prompt_tokens": 50, "completion_tokens": 60,
                                                   "total_tokens": 110}}) + "\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")
    return {"id": "x", "object": "chat.completion", "created": int(time.time()),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 60, "total_tokens": 110}}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
