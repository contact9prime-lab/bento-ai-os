"""A stand-in teacher for the Train live run: an OpenAI-compatible model that plans, writes
examples and answers prompts for ONE job (sorting support mail into billing, bug or other).

Only the teacher is a stand-in. The examples it writes are real text, the student is a
real model from the Hugging Face Hub, and the training and the check are the real thing.

    python teacher.py 9431
"""
import json
import random
import re
import sys

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()
CALLS = {"plan": 0, "write": 0, "answer": 0}
RNG = random.Random(7)
FILL = {"plan": ["Team", "Pro", "Starter", "Business"], "feature": ["the dashboard", "reports", "the calendar", "search", "the mobile app", "exports", "notifications", "the editor"],
        "fmt": ["CSV", "PDF", "Excel"], "code": ["500", "E-1042", "403", "timeout"], "device": ["my iPhone", "Android", "Safari", "the desktop app"],
        "city": ["Pune", "Lisbon", "Austin", "Berlin", "Nairobi"], "amt": ["$49", "€39", "$120", "₹2,400"], "n": ["#1182", "#2207", "#3310", "#4096"],
        "d": ["4242", "1881", "0005"], "name": ["Priya", "Tom", "Aiko", "Lena", "Sam"]}
BANK = {
    "billing": ["I was charged twice for the {plan} plan this month.", "Invoice {n} shows the wrong VAT number, can you fix it?",
                "Can I get a refund for the {plan} renewal? We meant to cancel.", "My card ending {d} was declined but the money left my account.",
                "Please move us to annual billing.", "Why did our price go up to {amt}?", "Where can I download last year's receipts?",
                "We need a quote for 40 seats on {plan}.", "The discount code did not apply at checkout, I paid {amt}.",
                "Hi, {name} here. Our payment failed and the account says past due."],
    "bug": ["The app crashes every time I open {feature}.", "{feature} shows a blank page since yesterday's update.",
            "Export to {fmt} produces an empty file.", "I get error {code} when saving a record.", "I'm stuck in a login loop on {device}.",
            "Notifications arrive three hours late on {device}.", "Search returns nothing for words I can see on the page.",
            "The save button in {feature} does nothing.", "Dates in {feature} are off by one day.", "Uploading a photo freezes {feature} on {device}."],
    "other": ["Do you have an office in {city}?", "How do I invite a teammate?", "Is there a dark mode?", "Thanks, {feature} is great!",
              "Could someone from your team speak at our meetup in {city}?", "What are your support hours?", "Do you offer student internships?",
              "Where is your privacy policy?", "{name} from our team wants a demo next week.", "Can I change the language to Spanish?"],
}
TAILS = ["", " Thanks.", " Please help.", " This is urgent.", " Any update?", " Regards, {name}", " We are on the {plan} plan."]


def one():
    label = RNG.choice(list(BANK))
    text = (RNG.choice(BANK[label]) + RNG.choice(TAILS)).format(**{k: RNG.choice(v) for k, v in FILL.items()})
    return {"prompt": text, "response": label}


def classify(text: str) -> str:
    t = text.lower()
    if re.search(r"charg|invoice|refund|card|billing|price|receipt|quote|discount|payment|paid", t):
        return "billing"
    if re.search(r"crash|blank|error|empty file|loop|late|nothing|freez|off by|does nothing|returns", t):
        return "bug"
    return "other"


def reply(body) -> str:
    msgs = body.get("messages") or []
    text = lambda m: m.get("content") if isinstance(m.get("content"), str) else " ".join(  # noqa: E731
        p.get("text", "") for p in m.get("content") or [] if isinstance(p, dict))
    system = " ".join(text(m) for m in msgs if m.get("role") == "system")
    user = next((text(m) for m in reversed(msgs) if m.get("role") == "user"), "")
    if "You plan the training" in system:
        CALLS["plan"] += 1
        return json.dumps({"name": "Support mail sorter",
                           "task": "Sort the support message into billing, bug or other. Answer with that one word.",
                           "source": "synthetic", "examples": 240, "size": "tiny",
                           "seeds": ["I was charged twice this month.", "The app crashes when I open reports.", "Do you have an office in Pune?"]})
    if "You write training examples" in system:
        CALLS["write"] += 1
        n = int((re.search(r"Write (\d+) new examples", user) or [0, 10])[1])
        out, seen = [], set()
        while len(out) < n:
            e = one()
            if e["prompt"] not in seen:
                seen.add(e["prompt"])
                out.append(e)
        return json.dumps(out)
    if "You are the reference" in system:
        CALLS["answer"] += 1
        return classify(user)
    return "I am the stand-in teacher for the Train run."


def chunk(delta, finish=None):
    return "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk",
                                  "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n"


@app.get("/v1/models")
async def models():
    return {"data": [{"id": "teacher-1", "object": "model"}]}


@app.get("/calls")
async def calls():
    return CALLS


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    text = reply(body)
    usage = {"prompt_tokens": 400, "completion_tokens": max(1, len(text) // 4), "total_tokens": 400 + len(text) // 4}

    async def gen():
        yield chunk({"role": "assistant", "content": text})
        yield chunk({}, "stop")
        yield "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk", "choices": [], "usage": usage}) + "\n\n"
        yield "data: [DONE]\n\n"
    if body.get("stream"):
        return StreamingResponse(gen(), media_type="text/event-stream")
    return {"id": "x", "object": "chat.completion", "usage": usage,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
