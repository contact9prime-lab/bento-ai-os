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
  * An alarm outlives a restart, and only a device's answer ends it. What was open is read back from
    the diary (`episodes`, `Alarms.restore`) and checked against what the machines say now: still
    true keeps its first time and its acknowledgement with no second "raised" line; no longer true
    is cleared with a line that says so. While a machine can't be asked it reads "checking", never
    clear and never raised. Before this a restart forgot them, so the day read "9 raised, 1 cleared".

Free of HTTP and asyncio, like devtrig.py: the server, the CLI and the tests call the same functions.
"""
from __future__ import annotations

import hashlib
import time

from . import devtrig

LEVELS = ("alarm", "warning")
MAX_RULES = 50
JUDGED = ("on", "off", "above", "below", "offline")      # a state; 'changes' and 'online' are moments
NAME_MAX, NOTE_MAX = 60, 240                             # a rule's own name, and what to do when it goes off
GRACE_S = 150                                            # how long a restart waits for a reading before giving up on one


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
    # what the person calls it and what to do when it goes off: words shown beside the alarm,
    # never part of what it judges, so naming or pausing a rule keeps its id (and its ack)
    from .teamlink import plain
    name = plain(c.get("name") or "", NAME_MAX, newlines=False)
    note = plain(c.get("note") or "", NOTE_MAX, newlines=False)
    if name:
        out["name"] = name
    if note:
        out["note"] = note
    if c.get("paused") is True or c.get("enabled") is False:
        out["paused"] = True
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
    """Which alarms are raised, since when, and who acknowledged them, per account. Held in memory
    and judged from the newest readings; `restore` brings back what the diary says was open."""

    restored = False        # a class attribute so tests/conftest.py can turn the diary read off

    def __init__(self):
        self.since: dict[tuple, float] = {}
        self.active: dict[str, dict] = {}
        self.acks: dict[tuple, dict] = {}
        self.checking: dict[tuple, float] = {}    # (owner, alarm) brought back by a restart -> give up at

    def restore(self, owner: str, rows: list[dict], now: float | None = None) -> None:
        """Alarms the diary says were open when this hub last stopped. They stay raised, under their
        first time, until judge() has a reading that says otherwise."""
        now = now or time.time()
        on = self.active.setdefault(owner, {})
        for r in rows:
            aid = r["id"]
            if aid in on:
                continue
            on[aid] = {"id": aid, "level": r.get("level") or "alarm", "machine": r.get("machine") or "",
                       "item": r.get("item") or "", "name": r.get("item") or "", "text": r.get("text") or "",
                       "since": r["since"], "for": 0, "source": r.get("source") or "", "flow": ""}
            self.since[(owner, aid)] = r["since"]
            self.checking[(owner, aid)] = now + GRACE_S
            if r.get("ack"):
                self.acks[(owner, aid)] = r["ack"]

    @staticmethod
    def _verdict(a: dict, rule: dict | None, last: dict, up: dict, late: bool) -> str | None:
        """Why a restored alarm that is not true by the readings has ended, or None while nobody can
        say. Readings decide; a machine that can't be asked keeps it open for as long as that lasts."""
        aid, ml = a["id"], str(a.get("machine") or "").lower()
        fault = aid.startswith("na:")
        if not rule and not fault and not aid.startswith("off:"):
            return "its rule is gone"
        if ml not in up:
            return "that machine is no longer on this hub"
        c = (rule or {}).get("config") or {}
        if aid.startswith("off:") or c.get("when") == "offline":
            if up.get(ml) is True:
                return "the machine answers again"
        else:
            item = aid.split("/", 1)[1] if fault else c.get("item")
            if (ml, item) in last:
                return "the device reads normal now"
        if up.get(ml) is False or not late:
            return None
        return "no reading says it is still true"

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
            if when not in JUDGED or c.get("paused"):
                if c.get("paused"):
                    self.since.pop((owner, r["id"]), None)
                continue
            m = str(c.get("machine") or "")
            ml = m.lower()
            aid = r["id"]
            words = {"label": c.get("name") or "", "note": c.get("note") or ""}
            if when == "offline":
                if up.get(ml) is False:
                    since = hold(aid, now)
                    found[aid] = {"id": aid, "level": r.get("level") or "alarm", "machine": m, "item": "",
                                  "name": m, "text": text_of(c), "since": since, "for": int(c.get("for") or 0),
                                  "source": r.get("source") or "alarm", "flow": r.get("flow") or "", **words}
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
                          "source": r.get("source") or "alarm", "flow": r.get("flow") or "", **words}
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
        # what a restart brought back: confirmed by the readings above, ended, or not yet known
        ruled = {r["id"]: r for r in rules}
        for key, give_up in list(self.checking.items()):
            if key[0] != owner:
                continue
            aid = key[1]
            a = was.get(aid)
            if aid in found or not a:
                self.checking.pop(key, None)
                continue
            why = self._verdict(a, ruled.get(aid), last, up, now >= give_up)
            if why:
                a["why"] = why
                self.checking.pop(key, None)
            else:
                found[aid] = {**a, "state": "unconfirmed", "held": round(max(0.0, now - a["since"]))}
        now_on = {k: a for k, a in found.items() if a["state"] != "pending"}
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


def _said(line: str) -> str:
    """'Alarm on zone-cold: Door is open' → 'Door is open'."""
    return str(line or "").split(": ", 1)[-1]


def episodes(lines: list[dict]) -> tuple[list[dict], list[dict]]:
    """The diary's alarm lines (devevents: event alarm, cleared, acknowledged) as alarms: each raised
    with its end. Returns (ended, open), oldest first. Two raised lines with no clear between them
    mean the hub stopped in between, so the earlier one ended at a time nobody recorded."""
    ended, opened = [], {}
    for e in sorted(lines, key=lambda x: float(x.get("at") or 0)):
        ev, at = e.get("event"), float(e.get("at") or 0)
        key = (e.get("owner") or "", e.get("alarm") or _said(e.get("text")))
        if ev == "alarm":
            if key in opened:
                ended.append(opened.pop(key))
            opened[key] = {"id": key[1], "owner": key[0], "level": e.get("level") or "alarm",
                           "machine": e.get("label") or "", "item": e.get("item") or "", "source": e.get("source") or "",
                           "text": _said(e.get("text")), "since": at, "ended": None, "why": "", "ack": None}
        elif ev == "acknowledged" and key in opened:
            opened[key]["ack"] = {"by": str(e.get("by") or "someone")[:60], "at": at}
        elif ev == "cleared" and key in opened:
            a = opened.pop(key)
            a["ended"], a["why"] = at, str(e.get("why") or "")
            ended.append(a)
    return ended, list(opened.values())


def history(lines: list[dict], now_ids=(), hours: int = 24, now: float | None = None, limit: int = 200) -> list[dict]:
    """The alarms that are over, newest first: raised or ended in the last `hours`. A line still open
    in the diary and not raised now (`now_ids`) ended unrecorded too."""
    now = now or time.time()
    ended, still = episodes(lines)
    now_ids = set(now_ids)
    rows = ended + [a for a in still if a["id"] not in now_ids]
    rows = [a for a in rows if max(a["ended"] or 0, a["since"]) >= now - hours * 3600]
    rows.sort(key=lambda a: a["ended"] or a["since"], reverse=True)
    for a in rows:
        a["lasted"] = round(a["ended"] - a["since"]) if a["ended"] else None
    return rows[:limit]


def rule_rows(rules: list[dict], names: dict | None = None, alarms=()) -> list[dict]:
    """Every rule that can raise an alarm, in one list, with what it says now. rules is what
    _alarm_rules returns; a person's can be edited, a mission's belongs to the mission."""
    names = names or {}
    now = {a["id"]: a.get("state") for a in alarms}
    out = []
    for r in rules:
        c = r.get("config") or {}
        if c.get("when") not in JUDGED:
            continue
        name, unit = names.get((str(c.get("machine") or "").lower(), c.get("item")), ("", ""))
        out.append({"id": r["id"], "machine": c.get("machine"), "item": c.get("item") or "", "when": c.get("when"),
                    "value": c.get("value"), "for": int(c.get("for") or 0), "level": r.get("level") or "alarm",
                    "source": r.get("source") or "alarm", "flow": r.get("flow") or "",
                    "editable": r.get("source") == "alarm", "text": text_of(c, name, unit),
                    "label": c.get("name") or "", "note": c.get("note") or "", "paused": bool(c.get("paused")),
                    "unit": unit, "now": "paused" if c.get("paused") else now.get(r["id"]) or "clear"})
    return out


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
        if a.get("state") == "unconfirmed":
            mark, seen = " ?", ", being checked with the machine"
        lines.append(f"  {mark} {a.get('machine')}: {a.get('text')} ({a.get('level')}, {a.get('held', 0)} s{seen})")
    if al:
        lines.append("")
    past = board.get("history") or []
    if past:
        lines.append("  Earlier, the last 24 hours")
        for a in past[:10]:
            at = time.strftime("%H:%M", time.localtime(a.get("since") or 0))
            end = f"cleared after {a['lasted']} s" if a.get("lasted") is not None else "ended, time not recorded"
            lines.append(f"     {at}  {a.get('machine')}: {a.get('text')} ({a.get('level')}, {end})")
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


def rules_text(board: dict) -> str:
    """The alarm rules in a terminal (`bento network alarms`), numbered for `remove`."""
    lines, n = [], 0
    for r in board.get("rule_list") or []:
        who = f"mission {r.get('flow')}" if r.get("source") == "mission" else ("demo" if r.get("demo") else "yours")
        tag = "   "
        if r.get("editable") and not r.get("demo"):
            n += 1
            tag = f"{n:>2}."
        held = f" for {r['for']} s" if r.get("for") else ""
        lines.append(f"  {tag} {r.get('level'):<8}{r.get('machine')}: {r.get('text')}{held}  ({who}, {r.get('now')})")
    lines.append("      always on: a machine that stops answering, and a sensor with no reading")
    return "\n".join(lines)


def analytics(events: list[dict], alarms: list[dict], machines: list[dict], now: float | None = None) -> dict:
    """The board's numbers for the last 24 hours, read from the Events diary (alarm and cleared
    lines, devevents.gather) and the board itself: how many machines answer, how many alarms were
    raised and cleared, by hour, which came back most often, and how long the open ones have held."""
    now = now or time.time()
    day = [e for e in events if now - float(e.get("at") or 0) <= 86400]
    raised = [e for e in day if e.get("event") == "alarm"]
    cleared = [e for e in day if e.get("event") == "cleared"]
    hours = [0] * 24
    for e in raised:
        h = int((now - float(e["at"])) // 3600)
        if 0 <= h < 24:
            hours[23 - h] += 1
    top: dict = {}
    for e in raised:
        t = str(e.get("text") or "").split(": ", 1)[-1]
        top[t] = top.get(t, 0) + 1
    active = [a for a in alarms if a.get("state") == "active"]
    things = sum(len(m.get("things") or []) for m in machines)
    reading = sum(1 for m in machines for t in m.get("things") or [] if t.get("value") is not None)
    return {"machines": len(machines), "answering": sum(1 for m in machines if m.get("up") is not False),
            "things": things, "reading": reading,
            "active": len(active), "alarms_now": sum(1 for a in active if a.get("level") == "alarm"),
            "warnings_now": sum(1 for a in active if a.get("level") == "warning"),
            "acked": sum(1 for a in active if a.get("ack")),
            "pending": sum(1 for a in alarms if a.get("state") == "pending"),
            "raised_24h": len(raised), "cleared_24h": len(cleared), "by_hour": hours,
            "top": sorted(top.items(), key=lambda kv: -kv[1])[:5],
            "longest": max((a.get("held") or 0 for a in active), default=0)}
