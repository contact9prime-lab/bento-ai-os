"""A stand-in OpenAI-compatible brain for the warehouse run. It is the hub's lead, and it does
what a model would do with the two device tools: read the zones it is asked about, then say what
it read. Every number in its answers is parsed out of a tool result, so the words can't be
better than what the nodes said. It recognises three requests:

  "walk me through"   -> the machines, then the cold rooms, the dock doors, the aisles and the
                         forklift battery, one device_get each, then a summary
  "cold room b"       -> its temperature, door and compressor; if the compressor is off with the
                         door shut, it says so and asks to switch it back on (device_set)
  "fans"              -> device_set on the far aisles' ceiling fan

    python warehouse_brain.py PORT
"""
import json
import re
import sys
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()

WALK = [("zone-cold", "esp.cold-1.sensor.cold_room_temperature"), ("zone-cold", "esp.cold-2.sensor.cold_room_temperature"),
        ("zone-dock", "esp.dock-1.binary_sensor.dock_door_1"), ("zone-dock", "esp.dock-1.binary_sensor.dock_door_2"),
        ("zone-dock", "esp.dock-1.binary_sensor.dock_door_3"), ("zone-aisle", "esp.aisle-2.sensor.aisle_temperature"),
        ("zone-dock", "esp.charge-1.sensor.forklift_battery")]
COLDB = [("zone-cold", "esp.cold-2.sensor.cold_room_temperature"), ("zone-cold", "esp.cold-2.binary_sensor.cold_room_door"),
         ("zone-cold", "esp.cold-2.switch.compressor")]


def _text(c):
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c or "")


def _chunk(delta, finish=None):
    return "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk", "created": int(time.time()),
                                  "model": "fake-1", "choices": [{"index": 0, "delta": delta,
                                                                  "finish_reason": finish}]}) + "\n\n"


def _get(machine, item, words=""):
    return words, {"name": "device_get", "arguments": json.dumps({"machine": machine, "item": item})}


def _val(t):
    """The value out of a device_get answer: '<name> on <machine>: <value>, read live at …'."""
    m = re.search(r" on [\w.-]+: (.+?)(?: \(.*?\))?, read live", t or "")
    return m.group(1) if m else "?"


def _reply(msgs):
    i = max((k for k, m in enumerate(msgs) if m.get("role") == "user"), default=0)
    ask = _text(msgs[i].get("content")).lower()
    done = [_text(m.get("content")) for m in msgs[i + 1:] if m.get("role") == "tool"]
    if done and done[-1].startswith(("[denied]", "[error]")):
        return "I couldn't do that: " + done[-1][:300], None
    if "walk me through" in ask:
        if not done:
            return _get("", "", "Let me read every zone.")[0], {"name": "device_get", "arguments": "{}"}
        k = len(done) - 1
        if k < len(WALK):
            return _get(*WALK[k])
        v = [_val(t) for t in done[1:]]
        doors = ", ".join(f"{n} {'open' if d == 'on' else 'shut'}" for n, d in zip((1, 2, 3), v[2:5]))
        return (f"Here's the floor, read live from the nodes:\n\n"
                f"- Cold room A: {v[0]}\n- Cold room B: {v[1]}\n- Dock doors: {doors}\n"
                f"- Aisles 7-12: {v[5]}\n- Forklift battery: {v[6]}\n\n"
                + ("Cold room B is warmer than A. Want me to look at it?" if _num(v[1]) > _num(v[0]) + 2
                   else "Nothing needs you right now.")), None
    if "cold room b" in ask:
        k = len(done)
        if k < len(COLDB):
            return _get(*COLDB[k])
        if k == len(COLDB):
            t, door, comp = (_val(x) for x in done[:3])
            if comp == "off" and door == "off":
                return (f"Cold room B is at {t} and climbing. The door is shut, but the compressor is off. "
                        f"I'm asking to switch it back on.",
                        {"name": "device_set", "arguments": json.dumps({"machine": "zone-cold",
                                                                         "item": "esp.cold-2.switch.compressor", "value": "1"})})
            return f"Cold room B is at {t}. Door {('open' if door == 'on' else 'shut')}, compressor {comp}.", None
        return f"Done. {done[-1]} It should be back under -15 °C within the hour.", None
    if "fans" in ask:
        if not done:
            return ("Switching on the ceiling fan over aisles 7-12.",
                    {"name": "device_set", "arguments": json.dumps({"machine": "zone-aisle",
                                                                     "item": "esp.aisle-2.switch.ceiling_fan", "value": "1"})})
        return f"Done. {done[-1]}", None
    return "I can read and switch what the zones' nodes lend me. Ask about a room.", None


def _num(s):
    m = re.search(r"-?\d+(?:\.\d+)?", str(s).replace("−", "-"))
    return float(m.group(0)) if m else 0.0


@app.get("/v1/models")
async def models():
    return {"data": [{"id": "fake-1", "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    text, call = _reply(body.get("messages", []))

    async def gen():
        import asyncio
        await asyncio.sleep(0.6)                        # a model thinks for a moment
        if text:
            for part in re.findall(r"\S+\s*", text):    # streamed a few words at a time, as a model does
                yield _chunk({"role": "assistant", "content": part})
                await asyncio.sleep(0.03)
        if call:
            yield _chunk({"role": "assistant", "tool_calls": [{"index": 0, "id": f"call_{int(time.time()*1000)}",
                                                               "type": "function", "function": call}]})
            yield _chunk({}, "tool_calls")
        else:
            yield _chunk({}, "stop")
        yield "data: " + json.dumps({"id": "x", "object": "chat.completion.chunk", "choices": [],
                                     "usage": {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52}}) + "\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
