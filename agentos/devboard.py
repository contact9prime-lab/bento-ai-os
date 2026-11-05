"""The device board: every machine's things as last heard, and the alarms among them.

Asked for as "when we are in the device mode the device screen should be there on the hub, so I
can see all the devices in real time along with alarms … like a device hub instead of the town",
after a demo where a tripped compressor showed nowhere until a mission asked about it. The hub
already heard every change (server._device_observe); nothing showed the floor as a whole, and
nothing said "this is wrong now". This module says it.

An alarm is a condition that is TRUE NOW, judged on the newest reading of each thing:

  * an alarm rule of the person's own (`device_alarms`, a USER_KEY): the closed set of a device
    trigger (devtrig.clean: machine, item, on/off/above/below, for) plus a level, alarm or warning
  * a device rule of a mission that is on: what a mission watches for is worth seeing too
  * a machine the hub set up that is not answering
  * a sensor that reports no number (ESPHome's NA: a probe that fell off)

Four rules:

  * It is a STATE, not an event. An alarm is raised when its condition has held for its `for`,
    stays while it holds, and clears by itself when it stops. Raised and cleared are one diary line
    each (Devices → Events), so what happened while nobody looked is still there.
  * Acknowledged is a person's mark, never a fix. It quiets the alarm on the screens, says who and
    when, and goes away with the alarm; the next time it is raised it is a new alarm.
  * Nothing here acts. Switching is still device_set, asked of a person every time, and a mission's
    rule still fires through devtrig's own watch and the flow's own consent.
  * Text sensors are never judged and their words never reach a line: a value here is a number.

Free of HTTP and asyncio, like devtrig.py: the server, the CLI and the tests call the same functions.
"""
from __future__ import annotations

import hashlib
import time

from . import devtrig

LEVELS = ("alarm", "warning")
MAX_RULES = 50
JUDGED = ("on", "off", "above", "below", "offline")      # a state; 'changes' and 'online' are moments


def _rule_id(c: dict) -> str:
    return "a" + hashlib.sha1(devtrig.canonical(c).encode()).hexdigest()[:10]


def clean_rule(conf: dict) -> dict:
    """One alarm rule, read field by field. Raises ValueError with the sentence a person needs."""
    c = conf if isinstance(conf, dict) else {}
    out = devtrig.clean(c)
    if out["when"] not in JUDGED:
        raise ValueError("an alarm is on, off, above, below or offline: something that stays true")
    lvl = str(c.get("level") or "alarm").strip().lower()
    if lvl not in LEVELS:
        raise ValueError("an alarm's level is alarm or warning")
    out["level"] = lvl
    out["id"] = _rule_id(out)
    return out


def clean_rules(rules) -> tuple[list[dict], list[str]]:
    """A person's alarm rules: kept (deduplicated, at most MAX_RULES) and what was dropped, in words."""
    kept, dropped, seen = [], [], set()
    for r in rules if isinstance(rules, list) else []:
        try:
            c = clean_rule(r)
        except ValueError as e:
            dropped.append(str(e))
            continue
        if c["id"] in seen:
            continue
        if len(kept) >= MAX_RULES:
            dropped.append(f"more than {MAX_RULES} alarms")
            break
        seen.add(c["id"])
        kept.append(c)
    return kept, dropped


def _fmt(v, unit: str = "") -> str:
    n = devtrig._num(v)
    if n is None:
        return str(v)
    s = f"{n:g}" if abs(n) >= 100 or n == int(n) else f"{n:.1f}"
    return s + ((" " if unit not in ("°C", "%") else "") + unit if unit else "")


def text_of(c: dict, name: str = "", unit: str = "") -> str:
    """'Cold room temperature is above -15 °C' / 'Dock door 2 is on' / 'zone-dock is not answering'."""
    when = c.get("when")
    if when == "offline":
        return f"{c.get('machine')} is not answering"
    what = name or c.get("item") or "a thing"
    if when in devtrig.NEEDS_VALUE:
        return f"{what} is {when} {_fmt(c.get('value'), unit)}"
    onword = {"on": "on", "off": "off"}[when]
    if devtrig.domain_of(str(c.get("item") or "")) == "binary_sensor" and "door" in what.lower():
        onword = "open" if when == "on" else "shut"
    if str(c.get("item") or "").startswith("gpio."):
        onword = "high" if when == "on" else "low"
    return f"{what} is {onword}"


class Alarms:
    """Which alarms are raised, since when, and who acknowledged them, per account. In memory: a
    hub that restarts judges everything again from the next reading."""

    def __init__(self):
        self.since: dict[tuple, float] = {}
        self.active: dict[str, dict] = {}
        self.acks: dict[tuple, dict] = {}

    def judge(self, owner: str, rules: list[dict], last: dict, up: dict, names: dict | None = None,
              now: float | None = None) -> tuple[list[dict], list[dict], list[dict]]:
        """rules: [{id, config, level, source, flow}]; last: {(machine lower, item): event};
        up: {machine lower: bool | None}; names: {(machine lower, item): (name, unit)}.
        Returns (alarms now, newly raised, cleared). An alarm still holding for less than its
        `for` is in the list as `pending` and is neither raised nor news."""
        now = now or time.time()
        names = names or {}
        found: dict[str, dict] = {}

        def hold(aid: str, since: float) -> float:
            return self.since.setdefault((owner, aid), min(since or now, now))

        for r in rules:
            c = r.get("config") or {}
            when = c.get("when")
            if when not in JUDGED:
                continue
            m = str(c.get("machine") or "")
            ml = m.lower()
            aid = r["id"]
            if when == "offline":
                if up.get(ml) is False:
                    since = hold(aid, now)
                    found[aid] = {"id": aid, "level": r.get("level") or "alarm", "machine": m, "item": "",
                                  "name": m, "text": text_of(c), "since": since, "for": int(c.get("for") or 0),
                                  "source": r.get("source") or "alarm", "flow": r.get("flow") or ""}
                continue
            ev = last.get((ml, c.get("item")))
            if not ev:
                continue
            name, unit = names.get((ml, c.get("item")), (ev.get("name") or "", ev.get("unit") or ""))
            ok = devtrig.holds(c, ev.get("value"))
            if not ok:
                self.since.pop((owner, aid), None)
                continue
            since = hold(aid, float(ev.get("at") or now))
            found[aid] = {"id": aid, "level": r.get("level") or "alarm", "machine": m, "item": c.get("item"),
                          "name": name or c.get("item"), "text": text_of(c, name, unit), "value": ev.get("value"),
                          "unit": unit, "since": since, "for": int(c.get("for") or 0),
                          "source": r.get("source") or "alarm", "flow": r.get("flow") or ""}
        # what nobody wrote a rule for, and is still wrong: a machine set up here not answering,
        # a sensor with no number
        for ml, ok in up.items():
            aid = "off:" + ml
            if ok is False and not any(a["machine"].lower() == ml and not a["item"] for a in found.values()):
                found[aid] = {"id": aid, "level": "alarm", "machine": names.get((ml, ""), (ml, ""))[0] or ml,
                              "item": "", "name": ml, "text": f"{names.get((ml, ''), (ml, ''))[0] or ml} is not answering",
                              "since": hold(aid, now), "for": 0, "source": "machine", "flow": ""}
            elif ok is not False:
                self.since.pop((owner, aid), None)
        for (ml, item), ev in last.items():
            if devtrig.domain_of(item) != "sensor" or ev.get("value") is not None:
                if devtrig.domain_of(item) == "sensor":
                    self.since.pop((owner, "na:" + ml + "/" + item), None)
                continue
            aid = "na:" + ml + "/" + item
            name, unit = names.get((ml, item), (ev.get("name") or item, ev.get("unit") or ""))
            found[aid] = {"id": aid, "level": "warning", "machine": ev.get("machine") or ml, "item": item,
                          "name": name or item, "text": f"{name or item} has no reading", "value": None,
                          "unit": unit, "since": hold(aid, float(ev.get("at") or now)), "for": 0,
                          "source": "fault", "flow": ""}
        for a in found.values():
            a["held"] = round(max(0.0, now - a["since"]))
            a["state"] = "active" if a["held"] >= a["for"] else "pending"
        was = self.active.get(owner, {})
        now_on = {k: a for k, a in found.items() if a["state"] == "active"}
        raised = [a for k, a in now_on.items() if k not in was]
        cleared = [a for k, a in was.items() if k not in now_on]
        for a in cleared:
            self.acks.pop((owner, a["id"]), None)
        for k in [k for k in self.since if k[0] == owner and k[1] not in found]:
            self.since.pop(k, None)
        self.active[owner] = now_on
        for a in found.values():
            a["ack"] = self.acks.get((owner, a["id"]))
        order = {"alarm": 0, "warning": 1}
        out = sorted(found.values(), key=lambda a: (a["state"] != "active", order.get(a["level"], 2), -a["since"]))
        return out, raised, cleared

    def ack(self, owner: str, aid: str, by: str, now: float | None = None) -> dict | None:
        """A person's mark on a raised alarm. None when that alarm is not raised now."""
        a = self.active.get(owner, {}).get(aid)
        if not a:
            return None
        mark = {"by": str(by or "someone")[:60], "at": now or time.time()}
        self.acks[(owner, aid)] = mark
        return {**a, "ack": mark}


def _val(t: dict) -> str:
    v = t.get("value")
    if v is None:
        return "no reading" if t.get("kind") == "sensor" else "-"
    if t.get("onoff"):
        if t.get("kind") == "gpio":
            return "high" if v else "low"
        return ("open" if v else "shut") if "door" in str(t.get("name") or "").lower() else ("on" if v else "off")
    return _fmt(v, t.get("unit") or "")


def text(board: dict) -> str:
    """The board in a terminal (`bento network board`): the alarms, then every machine's things."""
    al, ms = board.get("alarms") or [], board.get("machines") or []
    raised = [a for a in al if a.get("state") == "active"]
    lines = [f"  {len(ms)} machines · {sum(len(m.get('things') or []) for m in ms)} things · "
             + (f"{len(raised)} alarms" if raised else "all clear"), ""]
    for a in al:
        mark = "!!" if a.get("level") == "alarm" else " !"
        if a.get("state") != "active":
            mark = " ~"
        seen = f", seen by {a['ack']['by']}" if a.get("ack") else ""
        lines.append(f"  {mark} {a.get('machine')}: {a.get('text')} ({a.get('level')}, {a.get('held', 0)} s{seen})")
    if al:
        lines.append("")
    for m in ms:
        st = "not answering" if m.get("up") is False else ("this hub" if m.get("here") else "")
        lines.append(f"  {m.get('machine')}" + (f"  ({st})" if st else ""))
        group = None
        for t in m.get("things") or []:
            if t.get("group_name") != group:
                group = t.get("group_name")
                lines.append(f"    {group}")
            name = str(t.get("name") or "")
            name = name[len(group) + 2:] if group and name.startswith(group + ": ") else name
            lines.append(f"      {name:<28} {_val(t)}")
    return "\n".join(lines)
