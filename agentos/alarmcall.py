"""Calling people about an alarm nobody has acknowledged.

Asked for after a reel of incidents, one of them a hotel whose chlorine alarm went out by email
that nobody read, and fifteen guests were hurt. The board showed an alarm, the Events tab kept
its line, and nothing reached a person who was not looking at a screen. This module decides who
is told and when; the server sends it on the phones that are already paired.

  * Step 1: an alarm still open and not acknowledged after `after_min` minutes goes to the
    owner's own paired chats (Telegram, WhatsApp).
  * Step 2: still not acknowledged `then_min` minutes later, it goes to the one second chat the
    person picked (somebody let in on their Telegram or WhatsApp, or a group), and the owner is
    told it was passed on.
  * Cleared, everyone who was told hears that it cleared. Acknowledged, nobody more is called.

Five rules:

  * It is the person's choice, read field by field (`clean`), on by default for alarms and off
    for warnings. The second chat is a chat of their own, looked up again at every send
    (phoneforward.targets), never an address a model wrote.
  * Acknowledging from a phone is the same mark as on the board (devboard.Alarms.ack), and only
    a chat that was told about that alarm can give it. It fixes nothing.
  * Nobody could be told is said once, in the diary, never silence.
  * A step is a diary line (`escalated`) and a ledger row, so a restart reads back who was told
    (`restore`) and never calls the same people twice.
  * No agent tool sets it: a model that could switch alarms off its phone could silence one.

Free of HTTP and asyncio, like devboard.py: the server sends, the CLI and the tests call this.
"""
from __future__ import annotations

import hashlib
import time

LEVELS = ("alarm", "warning")
DEFAULT = {"on": True, "after_min": 10, "then_min": 15, "levels": ["alarm"], "second": None}
MIN_MIN, MAX_MIN = 1, 24 * 60
CHANNELS = ("telegram", "whatsapp")
NAME_MAX = 60

# Bound by the server: ack(owner, aid, by, from_key) -> the acknowledged alarm or None (a coroutine).
_HOOKS: dict = {}


def bind(**fns) -> None:
    _HOOKS.update(fns)


def _minutes(v, default: int, name: str, dropped: list) -> int:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        if v not in (None, ""):
            dropped.append(f"{name} wasn't a number, so it is {default}")
        return default
    if n < MIN_MIN or n > MAX_MIN:
        k = min(max(n, MIN_MIN), MAX_MIN)
        dropped.append(f"{name} is between {MIN_MIN} and {MAX_MIN} minutes, so it is {k}")
        return k
    return n


def clean(raw) -> tuple[dict, list[str]]:
    """The person's policy, field by field. Returns (policy, what was dropped or corrected)."""
    r = raw if isinstance(raw, dict) else {}
    dropped: list[str] = []
    for k in r:
        if k not in DEFAULT:
            dropped.append(f"{k} isn't a setting here")
    out = {"on": bool(r.get("on", DEFAULT["on"])),
           "after_min": _minutes(r.get("after_min"), DEFAULT["after_min"], "after", dropped),
           "then_min": _minutes(r.get("then_min"), DEFAULT["then_min"], "then", dropped),
           "levels": [], "second": None}
    lv = r.get("levels", DEFAULT["levels"])
    for x in (lv if isinstance(lv, (list, tuple)) else [lv]):
        x = str(x or "").strip().lower()
        if x in LEVELS and x not in out["levels"]:
            out["levels"].append(x)
        elif x:
            dropped.append(f"{x} isn't a level (alarm or warning)")
    s = r.get("second")
    if isinstance(s, dict) and s.get("to"):
        ch = str(s.get("channel") or "").lower()
        to = str(s.get("to") or "").strip()[:40]
        if ch in CHANNELS and to.lstrip("-").replace("+", "").isdigit():
            out["second"] = {"channel": ch, "to": to, "name": str(s.get("name") or to)[:NAME_MAX]}
        else:
            dropped.append("the second chat wasn't one of your chats, so nobody else is called")
    elif s:
        dropped.append("the second chat wasn't one of your chats, so nobody else is called")
    return out, dropped


def policy_of(cfg: dict) -> dict:
    return clean((cfg or {}).get("device_escalation") or {})[0]


def code_of(owner: str, aid: str) -> str:
    """A short name for one alarm, small enough for a Telegram button (64 bytes)."""
    return hashlib.sha1(f"{owner}\0{aid}".encode()).hexdigest()[:10]


def words(p: dict) -> str:
    """The policy as a person would say it."""
    if not p.get("on") or not p.get("levels"):
        return "Nobody is called about alarms. They show on the board and in Events only."
    lv = " and ".join({"alarm": "alarms", "warning": "warnings"}[x] for x in p["levels"])
    s = (f"{lv.capitalize()} nobody acknowledges go to your phone after {p['after_min']} min")
    if p.get("second"):
        s += f", then to {p['second']['name']} {p['then_min']} min later"
    return s + "."


def message(a: dict, step: int, open_min: int, passed_to: str = "") -> str:
    head = "⚠ Alarm" if a.get("level") != "warning" else "⚠ Warning"
    s = f"{head} on {a.get('machine') or 'a machine'}: {a.get('text') or 'something is wrong'}."
    s += f" Open {open_min} min and nobody has acknowledged it."
    if a.get("note"):
        s += f"\nWhat to do: {a['note']}"
    if step == 2:
        s = "Passed on to you. " + s
    if passed_to:
        s += f"\nIt has gone to {passed_to} too."
    return s


class Calls:
    """Who was told about which alarm, per (owner, alarm id). In memory; the diary keeps it."""

    def __init__(self):
        self.state: dict = {}           # (owner, aid) -> {"step", "told": [keys], "at", "names"}
        self.codes: dict = {}           # code -> (owner, aid)
        self.restored = False

    def due(self, owner: str, alarms: list[dict], p: dict, now: float | None = None) -> list[tuple[dict, int]]:
        """The steps that are due now: (alarm, 1|2). Pure: nothing is marked until `told`."""
        now = now or time.time()
        out = []
        if not p.get("on"):
            return out
        for a in alarms:
            if a.get("ack") or a.get("state") in ("checking", "unconfirmed") or a.get("level") not in p["levels"]:
                continue
            st = self.state.get((owner, a["id"])) or {"step": 0}
            age = now - float(a.get("since") or now) - float(a.get("for") or 0)   # since it was raised
            if st["step"] == 0 and age >= p["after_min"] * 60:
                out.append((a, 1))
            elif st["step"] == 1 and p.get("second") and now - st["at"] >= p["then_min"] * 60:
                out.append((a, 2))
        return out

    def told(self, owner: str, aid: str, step: int, keys: list[str], now: float | None = None) -> None:
        st = self.state.setdefault((owner, aid), {"step": 0, "told": [], "at": 0})
        st["step"], st["at"] = max(st["step"], step), now or time.time()
        st["told"] = list(dict.fromkeys(st["told"] + [k for k in keys if k]))
        self.codes[code_of(owner, aid)] = (owner, aid)

    def told_keys(self, owner: str, aid: str) -> list[str]:
        return list((self.state.get((owner, aid)) or {}).get("told") or [])

    def ended(self, owner: str, aid: str) -> list[str]:
        """The alarm cleared or was acknowledged: forget it, and return who had been told."""
        st = self.state.pop((owner, aid), None) or {}
        self.codes.pop(code_of(owner, aid), None)
        return list(st.get("told") or [])

    def asked_by(self, key: str, code: str = "") -> list[tuple[str, str]]:
        """The alarms this chat was told about and could acknowledge: one by its code, or all."""
        if code:
            got = self.codes.get(code)
            return [got] if got and key in self.told_keys(*got) else []
        return [k for k, st in self.state.items() if key in (st.get("told") or [])]

    def restore(self, lines: list[dict], still_open: set) -> None:
        """Once after a start: the `escalated` diary lines of alarms still open say who was told."""
        if self.restored:
            return
        self.restored = True
        for e in sorted(lines, key=lambda x: float(x.get("at") or 0)):
            if e.get("event") != "escalated":
                continue
            key = (e.get("owner") or "", e.get("alarm") or "")
            if key in still_open:
                self.told(key[0], key[1], int(e.get("step") or 1), list(e.get("told") or []),
                          float(e.get("at") or 0) or None)


CALLS = Calls()


def is_ack(text: str) -> bool:
    t = (text or "").strip().lower().rstrip(".!")
    return t in ("ack", "acknowledge", "acknowledged", "ok ack", "seen")


async def answer(key: str, by: str, code: str = "") -> str | None:
    """A phone said it saw the alarm. Returns what to reply, or None when this chat was told
    about nothing (the message is then an ordinary one, for the agent)."""
    got = CALLS.asked_by(key, code)
    if not got:
        return "That alarm is already over or acknowledged." if code else None
    fn = _HOOKS.get("ack")
    done = []
    for owner, aid in got:
        a = await fn(owner, aid, by, key) if fn else None
        if a:
            done.append(a)
    if not done:
        return "That alarm is already over or acknowledged."
    names = "; ".join(f"{a.get('machine')}: {a.get('text')}" for a in done[:3])
    return f"✓ Acknowledged ({names}). Nobody else will be called about it. Fixing it is still yours."
