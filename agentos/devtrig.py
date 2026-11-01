"""Device triggers: a mission starts when a device does something.

Asked for as "this should be proactive rather than reactive … event-based triggers", after a
reel where a person had to type "Cold room B looks warm" before anything happened. The readings
already reached the hub; nothing acted on them. This is the rule side: a flow trigger of kind
`device`, written by a person (the Missions editor, `bento flow trigger --kind device`, or a
draft from chat that lands disabled), and the watch that decides when one is met.

A rule names a machine (a Zero's label as Devices lists it, or this hub's own name), one of its
inventory items (`esp.cold-2.sensor.cold_room_temperature`, `gpio.17`) and a condition from a
closed set:

  on, off           a contact, switch, light, fan or pin is on / off
  above, below      a number is over / under `value`
  changes           an on/off thing changed either way
  offline, online   the machine stopped / started answering (no item)

`for` (seconds) asks the condition to hold that long first: "above -15 for 2 minutes" is a room
that is warm, not a door opened once.

Four rules keep it honest:

  * It fires on the EDGE. A rule fires once when its condition becomes true (and has held for
    `for`), then waits until the condition is false again before it can fire again. A room
    that stays warm is one mission, not one a minute. The trigger's own cooldown is on top.
  * The first reading arms it: a condition already true when the hub first hears the item fires
    once, because "the freezer is already warm" is exactly what the rule is for.
  * Only numbers are judged. A text sensor's value is somebody's words and never reaches a rule
    or a mission's brief; names come from the hub's own inventory where it has them.
  * The watch only DECIDES. Firing (the flow's own consent, its cooldown, the ledger) is the
    server's, through the same door a `flow_done` uses. Switching anything is still a device_set,
    asked of a person every time.

Free of HTTP and asyncio, like flows.py: the server, the CLI and the tests call the same functions.
"""
from __future__ import annotations

import math
import re
import time

WHENS = ("on", "off", "above", "below", "changes", "offline", "online")
NEEDS_VALUE = ("above", "below")
MACHINE_WHENS = ("offline", "online")
ONOFF_WHENS = ("on", "off", "changes")
FOR_MAX = 3600
MACHINE = re.compile(r"[A-Za-z0-9][\w .'-]{0,39}")
WORDS = {"on": "turns on", "off": "turns off", "above": "is above", "below": "is below",
         "changes": "changes", "offline": "stops answering", "online": "answers again"}


def _num(v):
    if isinstance(v, bool):
        return float(v)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def clean(conf: dict) -> dict:
    """A device trigger's config, read field by field. Raises ValueError with the sentence a
    person needs. {machine, item, when, value?, for}"""
    from .hardware import _ID
    c = conf if isinstance(conf, dict) else {}
    machine = str(c.get("machine") or "").strip()
    if not MACHINE.fullmatch(machine):
        raise ValueError("a device trigger needs the machine, named as Devices lists it")
    when = str(c.get("when") or "").strip().lower()
    if when not in WHENS:
        raise ValueError(f"a device trigger's condition is one of {', '.join(WHENS)}")
    out = {"machine": machine, "when": when}
    if when in MACHINE_WHENS:
        out["item"] = ""
    else:
        item = str(c.get("item") or "").strip().lower()
        if not _ID.fullmatch(item):
            raise ValueError("a device trigger needs the item, as Devices lists it "
                             "(for example esp.cold-2.sensor.cold_room_temperature)")
        out["item"] = item
    if when in NEEDS_VALUE:
        v = _num(c.get("value"))
        if v is None:
            raise ValueError(f"'{when}' needs a number to compare with")
        out["value"] = round(v, 3)
    secs = c.get("for", c.get("for_s", 0))
    try:
        secs = int(float(secs or 0))
    except (TypeError, ValueError):
        raise ValueError("'for' is a number of seconds") from None
    if not 0 <= secs <= FOR_MAX:
        raise ValueError(f"'for' is 0 to {FOR_MAX} seconds")
    out["for"] = secs
    return out


def canonical(c: dict) -> str:
    """What makes a device trigger THAT trigger (flows._canonical)."""
    return (f"device:{str(c.get('machine') or '').lower()}:{c.get('item') or ''}:{c.get('when') or ''}:"
            f"{c.get('value', '')}:{c.get('for') or 0}")


def _span(secs: int) -> str:
    if secs < 60:
        return f"{secs} s"
    return f"{secs // 60} min" + (f" {secs % 60} s" if secs % 60 else "")


def words(c: dict, name: str = "") -> str:
    """'when zone-cold/esp.cold-2.sensor.cold_room_temperature is above -15 for 2 min'."""
    when = c.get("when") or ""
    what = c.get("machine") or "a machine"
    if c.get("item"):
        what = name or f"{what}/{c['item']}"
    out = f"when {what} {WORDS.get(when, when)}"
    if when in NEEDS_VALUE:
        v = _num(c.get("value"))
        out += f" {v:g}" if v is not None else f" {c.get('value')}"
    if c.get("for"):
        out += f" for {_span(int(c['for']))}"
    return out


def holds(c: dict, value) -> bool | None:
    """Is the condition true for this reading? None when it can't be judged (not a number)."""
    v = _num(value)
    if v is None:
        return None
    when = c.get("when")
    if when == "on":
        return v != 0
    if when == "off":
        return v == 0
    if when == "above":
        return v > float(c.get("value"))
    if when == "below":
        return v < float(c.get("value"))
    return None


class Watch:
    """Which rules are met, held and spent, keyed on (account, trigger id). In memory: a hub
    that restarts arms everything again, and a condition still true fires once more."""

    def __init__(self):
        self.s: dict[tuple, dict] = {}

    def _st(self, uid: str, rule: dict) -> dict:
        key = (uid or "", rule["id"])
        st = self.s.get(key)
        sig = canonical(rule.get("config") or {})
        if not st or st.get("sig") != sig:           # a rule that was edited starts again
            st = self.s[key] = {"sig": sig, "met": False, "since": 0.0, "spent": False, "last": None}
        return st

    def feed(self, uid: str, rules: list[dict], machine: str, events: list[dict], now: float | None = None) -> list:
        """Readings from one machine. Returns [(rule, event)] to fire."""
        now = now or time.time()
        out = []
        m = str(machine or "").lower()
        for rule in rules:
            c = rule.get("config") or {}
            if str(c.get("machine") or "").lower() != m or c.get("when") in MACHINE_WHENS:
                continue
            for ev in events:
                if ev.get("item") != c.get("item"):
                    continue
                st = self._st(uid, rule)
                v = _num(ev.get("value"))
                if v is None:
                    continue
                if c.get("when") == "changes":
                    if st["last"] is not None and v != st["last"]:
                        out.append((rule, ev))
                    st["last"] = v
                    continue
                st["last"] = v
                ok = holds(c, v)
                if ok is None:
                    continue
                if not ok:
                    st.update(met=False, spent=False)
                    continue
                if not st["met"]:
                    st.update(met=True, since=float(ev.get("at") or now))
                if not st["spent"] and now - st["since"] >= int(c.get("for") or 0):
                    st["spent"] = True
                    out.append((rule, {**ev, "held": round(now - st["since"])}))
        return out

    def tick(self, uid: str, rules: list[dict], now: float | None = None, last: dict | None = None) -> list:
        """Conditions that have now held long enough with no new reading: a sensor that
        reports only on change sends nothing while it stays warm. `last` is {(machine, item):
        event} so the mission is told what it read."""
        now = now or time.time()
        out = []
        for rule in rules:
            c = rule.get("config") or {}
            st = self.s.get((uid or "", rule["id"]))
            if not st or not st["met"] or st["spent"] or not c.get("for"):
                continue
            if now - st["since"] >= int(c["for"]):
                st["spent"] = True
                ev = dict((last or {}).get((str(c.get("machine") or "").lower(), c.get("item"))) or {})
                ev.setdefault("item", c.get("item"))
                ev.setdefault("value", st["last"])
                ev["held"] = round(now - st["since"])
                out.append((rule, ev))
        return out

    def machine(self, uid: str, rules: list[dict], machine: str, up: bool, now: float | None = None) -> list:
        """A machine stopped or started answering (the ties watch says so)."""
        now = now or time.time()
        want = "online" if up else "offline"
        out = []
        for rule in rules:
            c = rule.get("config") or {}
            if c.get("when") in MACHINE_WHENS and str(c.get("machine") or "").lower() == str(machine).lower():
                st = self._st(uid, rule)
                if c["when"] == want:
                    out.append((rule, {"machine": machine, "item": "", "at": now, "up": up}))
                st["met"] = c["when"] == want
        return out


def domain_of(item: str) -> str:
    """An ESP32 node's item says its domain (esp.<node>.<domain>.<name>); a pin is a pin."""
    parts = str(item or "").split(".")
    if len(parts) == 4 and parts[0] == "esp":
        return parts[2]
    return "gpio" if parts[0] == "gpio" else ""


def onoff(item: str, domain: str = "") -> bool:
    return (domain or domain_of(item)) in ("binary_sensor", "switch", "light", "fan", "gpio")


def brief(rule: dict, ev: dict) -> str:
    """What the mission is told about why it started: the reading, where it came from, the rule.
    Numbers and names only: a text sensor's words never reach here."""
    c = rule.get("config") or {}
    at = time.strftime("%H:%M:%S", time.localtime(float(ev.get("at") or time.time())))
    m = c.get("machine") or ev.get("machine") or "a machine"
    if c.get("when") in MACHINE_WHENS:
        return f"Started because {m} {WORDS[c['when']]} (at {at})."
    name = str(ev.get("name") or "").strip() or c.get("item")
    v = ev.get("value")
    unit = str(ev.get("unit") or "")
    if onoff(str(c.get("item") or ""), ev.get("domain") or ""):
        reads = ("on" if _num(v) else "off") if not str(c.get("item") or "").startswith("gpio.") else (
            "high" if _num(v) else "low")
    else:
        reads = f"{v}{'' if unit in ('', '°C') else ' '}{unit}".strip()
    held = f", held for {_span(int(ev['held']))}" if ev.get("held") else ""
    return (f"Started because {name} on {m} ({m}/{c.get('item')}) reads {reads} at {at}{held}. "
            f"The rule: {words(c)}.")
