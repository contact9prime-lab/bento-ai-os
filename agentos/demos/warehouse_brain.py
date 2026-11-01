"""A scripted, OpenAI-compatible brain for the warehouse demo and its run. It is the hub's lead,
and it does what a model would do with the two device tools: read the zones it is asked about,
then say what it read. Every number in its answers is parsed out of a tool result, so the words
can't be better than what the nodes said. It is free and works offline, which is why
`bento demo warehouse --scripted` offers it; it understands only what a warehouse floor is asked:

  "walk me through"        the cold rooms, the dock doors, the aisles and the forklift battery,
                           one device_get each, then a summary
  "cold room b"            its temperature, door and compressor; if the compressor is off with
                           the door shut, it asks to switch it back on (device_set)
  a room by name           cold room a, the dock, the aisles, the forklift bay: what it has, read
  "fans|lights|charger|compressor" with "on" or "off"   device_set on each, asked of a person
  a mission's orchestrator  delegate the task to its roster, read what came back, finish
                           (a device trigger starts one with nobody asking)

    python -m agentos.demos.warehouse_brain PORT
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
                                  "model": "warehouse-script", "choices": [{"index": 0, "delta": delta,
                                                                  "finish_reason": finish}]}) + "\n\n"


def _get(machine, item, words=""):
    return words, {"name": "device_get", "arguments": json.dumps({"machine": machine, "item": item})}


def _val(t):
    """The value out of a device_get answer: '<name> on <machine>: <value>, read live at …'."""
    m = re.search(r" on [\w.-]+: (.+?)(?: \(.*?\))?, read live", t or "")
    return m.group(1) if m else "?"


ROOMS = [
    (("cold room a",), "Cold room A", [("Temperature", "zone-cold", "esp.cold-1.sensor.cold_room_temperature"),
                                       ("Door", "zone-cold", "esp.cold-1.binary_sensor.cold_room_door"),
                                       ("Compressor", "zone-cold", "esp.cold-1.switch.compressor")]),
    (("dock", "doors"), "The loading dock", [("Door 1", "zone-dock", "esp.dock-1.binary_sensor.dock_door_1"),
                                              ("Door 2", "zone-dock", "esp.dock-1.binary_sensor.dock_door_2"),
                                              ("Door 3", "zone-dock", "esp.dock-1.binary_sensor.dock_door_3"),
                                              ("Lights", "zone-dock", "esp.dock-1.switch.dock_lights"),
                                              ("Temperature", "zone-dock", "esp.dock-1.sensor.dock_temperature")]),
    (("forklift", "battery", "charg"), "The forklift bay", [("Battery", "zone-dock", "esp.charge-1.sensor.forklift_battery"),
                                                           ("Charger", "zone-dock", "esp.charge-1.switch.charger"),
                                                           ("Drawing", "zone-dock", "esp.charge-1.sensor.charger_power")]),
    (("aisle",), "The aisles", [("Aisles 1-6", "zone-aisle", "esp.aisle-1.sensor.aisle_temperature"),
                                ("Aisles 7-12", "zone-aisle", "esp.aisle-2.sensor.aisle_temperature"),
                                ("Fan over 1-6", "zone-aisle", "esp.aisle-1.switch.ceiling_fan"),
                                ("Fan over 7-12", "zone-aisle", "esp.aisle-2.switch.ceiling_fan")]),
]
SWITCHES = [  # words, what it is, [(zone, item)]
    (("fan",), "the ceiling fan", None),
    (("light",), "the dock lights", [("zone-dock", "esp.dock-1.switch.dock_lights")]),
    (("charger", "charging", "charge the"), "the forklift charger", [("zone-dock", "esp.charge-1.switch.charger")]),
    (("compressor",), "the compressor", None),
]


def _fans(ask):
    if "1-6" in ask or "1 to 6" in ask:
        return [("zone-aisle", "esp.aisle-1.switch.ceiling_fan")]
    if "7-12" in ask or "7 to 12" in ask:
        return [("zone-aisle", "esp.aisle-2.switch.ceiling_fan")]
    return [("zone-aisle", "esp.aisle-1.switch.ceiling_fan"), ("zone-aisle", "esp.aisle-2.switch.ceiling_fan")]


def _compressors(ask):
    if "room a" in ask:
        return [("zone-cold", "esp.cold-1.switch.compressor")]
    return [("zone-cold", "esp.cold-2.switch.compressor")]


def _set(machine, item, value):
    return {"name": "device_set", "arguments": json.dumps({"machine": machine, "item": item, "value": value})}


def _switching(ask, done):
    """'put the fans on', 'lights off': one device_set per thing, then what came back."""
    # asked to DO something: a verb, or "fans off" -- "is the compressor on?" is a question
    verb = re.search(r"\b(switch|turn|put|start|stop|shut|charge)\b", ask)
    if not (verb or (re.search(r"\b(fans?|lights?|charger|compressors?) (on|off)\b", ask) and "?" not in ask)):
        return None
    on, off = re.search(r"\bon\b|\bstart|\bcharge\b", ask), re.search(r"\boff\b|\bstop|\bshut", ask)
    if not (on or off):
        return None
    for words, what, targets in SWITCHES:
        if not any(w in ask for w in words):
            continue
        targets = targets or (_fans(ask) if words == ("fan",) else _compressors(ask))
        if len(targets) > 1:
            what += "s"
        value = "0" if off and not on else "1"
        k = len(done)
        if k < len(targets):
            return (f"Switching {what} {'on' if value == '1' else 'off'}." if not k else ""), _set(*targets[k], value)
        return "Done. " + " ".join(done), None
    return None


def _reply(msgs):
    i = max((k for k, m in enumerate(msgs) if m.get("role") == "user"), default=0)
    ask = _text(msgs[i].get("content")).lower()
    done = [_text(m.get("content")) for m in msgs[i + 1:] if m.get("role") == "tool"]
    if done and done[-1].startswith(("[denied]", "[error]")):
        return "I couldn't do that: " + done[-1][:300], None
    if "walk me through" in ask or "how is the floor" in ask or "how's the floor" in ask:
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
    switched = _switching(ask, done)
    if switched:
        return switched
    if "cold room b" in ask:
        k = len(done)
        if k < len(COLDB):
            return _get(*COLDB[k])
        if k == len(COLDB):
            t, door, comp = (_val(x) for x in done[:3])
            if comp == "off" and door == "off":
                return (f"Cold room B is at {t} and climbing. The door is shut, but the compressor is off. "
                        f"I'm asking to switch it back on.", _set("zone-cold", "esp.cold-2.switch.compressor", "1"))
            if door == "on":
                return (f"Cold room B is at {t}. Its door is open, so it's warming whatever the compressor "
                        f"does. Somebody needs to shut it."), None
            return f"Cold room B is at {t}. Door shut, compressor {comp}.", None
        return f"Done. {done[-1]} It should be back under -15 °C within the hour.", None
    for words, title, things in ROOMS:
        if any(w in ask for w in words):
            k = len(done)
            if k < len(things):
                return _get(things[k][1], things[k][2], f"Reading {title[0].lower() + title[1:]}." if not k else "")
            lines = "\n".join(f"- {n}: {_val(t)}" for (n, _, _), t in zip(things, done))
            return f"{title}, read live from the nodes:\n\n{lines}", None
    return ("I look after this warehouse through its three zone Pis and their ESP32 nodes. Ask me to walk you "
            "through it, about a room (cold room A or B, the dock, the aisles, the forklift bay), or to switch "
            "the fans, the dock lights, the charger or a compressor on or off."), None


def _orchestrate(body, msgs):
    """A mission's orchestrator (a flow run, which a device trigger starts on its own): hand the
    whole task to the first agent on its roster, read what came back, and finish with it."""
    tools = {t["function"]["name"]: t["function"] for t in body.get("tools") or []
             if isinstance(t, dict) and isinstance(t.get("function"), dict)}
    if "delegate" not in tools or "finish" not in tools:
        return None
    i = max((k for k, m in enumerate(msgs) if m.get("role") == "user"), default=0)
    task = _text(msgs[i].get("content"))
    done = [_text(m.get("content")) for m in msgs[i + 1:] if m.get("role") == "tool"]
    if not done:
        desc = str(((tools["delegate"].get("parameters") or {}).get("properties") or {}).get("subagent", {})
                   .get("description") or "")
        who = desc.split("one of:", 1)[-1].split(",")[0].strip()
        return "Handing this to the floor's watcher.", {"name": "delegate", "arguments": json.dumps(
            {"subagent": who, "task": task})}
    m = re.search(r"handle (\w+)", done[0])
    if len(done) == 1 and m and "read_handle" in tools:
        return "", {"name": "read_handle", "arguments": json.dumps({"handle": m.group(1)})}
    return "", {"name": "finish", "arguments": json.dumps({"summary": done[-1][:3000]})}


def _num(s):
    m = re.search(r"-?\d+(?:\.\d+)?", str(s).replace("−", "-"))
    return float(m.group(0)) if m else 0.0


@app.get("/v1/models")
async def models():
    return {"data": [{"id": "warehouse-script", "object": "model"}, {"id": "fake-1", "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    text, call = _orchestrate(body, body.get("messages", [])) or _reply(body.get("messages", []))

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
