"""What a phone sees while its turn is still working.

Reported as "when it is running a chat with Telegram or WhatsApp and it sends the message to the
department and sub department, it is not showing those interim steps in the channels". A phone
turn's events all went to the desktop (the Office walked the hand-over, Chat's card followed the
desk's run) while the phone got "typing…" and, minutes later, the answer. The hand-over to a
department, who its desk gave each piece to, a boss sending it back: none of it reached the
chat that asked.

One tap per phone turn, fed by the server's broadcast (`observe`, beside playground's), so it
sees exactly what the screens see and nothing a screen does not: the lead's own steps and
hand-overs (events carrying the conversation), and every run the turn started, found the way
Chat's department card finds them: a `flow_start` naming this conversation, then any run whose
`parent_run` is one of ours. Lines are words, never the work: a step's tool, who handed what to
whom, a sign-off, the finish. The answer itself still arrives as the reply.

A bridge shows the lines its own way (`pump`): Telegram edits one message in place, WhatsApp
sends short batches, because a WhatsApp message cannot be edited and each one is a buzz.

GUI: the desktop already draws all of this (the Office, Chat's live rows). TUI: the terminal chat
streams the same events over the socket. SUI: nothing here touches a window.
"""
from __future__ import annotations

import asyncio
import time

KEEP = 60                 # lines a tap keeps; a phone shows the last SHOW of them
SHOW = 14
TASK_CHARS = 90

# the lead's tools that hand work on, in the words a phone shows
HANDS = {"department_task": "▦ To {department}", "delegate": "↳ To @{subagent}",
         "huddle": "◎ Huddle", "run_flow": "▶ Mission {name}", "ask_agent": "↳ Asks @{agent}",
         "pool_task": "↳ To the community"}
QUIET = {"recall", "remember", "kg_query", "kg_add", "brief_item", "finish", "read_app_data",
         "think", "memory_text"}

_TAPS: dict[str, list["Tap"]] = {}


class Tap:
    def __init__(self, cid: str):
        self.cid = cid
        self.runs: dict[str, str] = {}      # run id -> who works it (a desk, a person)
        self.lines: list[str] = []
        self.changed = asyncio.Event()
        self.n = 0                          # lines ever added, so a sender knows what is new

    def add(self, line: str) -> None:
        line = " ".join(str(line or "").split())
        if not line or (self.lines and self.lines[-1] == line):
            return
        self.lines.append(line[:300])
        del self.lines[:-KEEP]
        self.n += 1
        self.changed.set()


def listen(cid: str) -> Tap:
    tap = Tap(cid)
    if cid:
        _TAPS.setdefault(cid, []).append(tap)
    return tap


def close(tap: Tap) -> None:
    taps = _TAPS.get(tap.cid) or []
    if tap in taps:
        taps.remove(tap)
    if not taps:
        _TAPS.pop(tap.cid, None)


def _cut(text, n: int = TASK_CHARS) -> str:
    t = " ".join(str(text or "").split())
    if len(t) <= n:
        return t
    t = t[:n].rsplit(" ", 1)[0]
    return t.rstrip(",.;:") + "…"


def _hand(name: str, args: dict) -> str:
    args = args if isinstance(args, dict) else {}
    head = HANDS[name]
    try:
        head = head.format(**{k: str(v) for k, v in args.items()}) if "{" in head else head
    except (KeyError, IndexError):
        head = head.split(" {")[0]
    what = args.get("task") or args.get("topic") or args.get("question") or args.get("input") or ""
    return head + (f": {_cut(what)}" if what else "")


def _lead_line(event: dict) -> str:
    """A line for an event of the turn itself (it carries the conversation)."""
    t = event.get("type")
    if t == "tool_start":
        name = str(event.get("name") or "")
        if name.startswith("mcp__bento__"):
            return ""                       # the CLI's copy of a step the gate already sent
        if name in HANDS:
            return _hand(name, event.get("args") or {})
        if name in QUIET:
            return ""
        detail = _cut(event.get("detail") or "", 60)
        return f"• {name}" + (f" · {detail}" if detail else "")
    if t == "tool_end" and event.get("ok") is False:
        return f"✗ {event.get('name') or 'a step'} didn't go through"
    if t == "agent_msg" and event.get("phase") == "ask":
        return f"↳ @{event.get('from')} asks @{event.get('to')}: {_cut(event.get('text'))}"
    if t == "agent_msg" and event.get("phase") == "reply":
        return f"✓ @{event.get('from')} answered @{event.get('to')}"
    return ""


def _run_line(tap: Tap, rid: str, ev: str, e: dict) -> str:
    """A line for an event of a run this turn started."""
    who = tap.runs.get(rid) or ""
    if ev == "flow_start":
        dept, head = e.get("department") or "", e.get("head") or ""
        if dept:
            return f"▦ {dept} desk took it" + (f", head @{head}" if head else "")
        return f"▶ Mission {e.get('flow') or ''} started"
    if ev == "node_add":
        return f"  ↳ @{e.get('agent')}: {_cut(e.get('task'))}"
    if ev == "node_status":
        st = e.get("status") or ""
        if st == "parked":
            return "  ⏸ waiting for your answer"
        if st == "ok":
            return ""                       # the person's own finished line says it
        return f"  ✗ a hand-over ended {st}" + (f": {_cut(e.get('fault'), 80)}" if e.get("fault") else "")
    if ev == "status":
        st, ref = e.get("status") or "", e.get("ref") or who
        if e.get("kind") in ("review", "audit"):
            return ""
        if st == "running":
            return ""                       # node_add already said who got it
        if st == "ok":
            n = e.get("steps") or 0
            return f"    ✓ @{ref} finished" + (f" ({n} step{'' if n == 1 else 's'})" if n else "")
        if st in ("error", "timeout", "denied"):
            return f"    ✗ @{ref} {st}" + (f": {_cut(e.get('fault'), 80)}" if e.get("fault") else "")
        return ""
    if ev == "step" and e.get("status") == "start":
        tool = str(e.get("tool") or "")
        if tool in QUIET or tool == "delegate" or who.endswith(" desk"):   # the desk's own hand-overs are node_add
            return ""
        detail = _cut(e.get("detail") or "", 50)
        return f"    • @{who} {tool}" + (f" · {detail}" if detail else "")
    if ev == "review":
        if e.get("phase") == "start":
            return f"  ◇ @{e.get('reviewer')} is checking it"
        ans = str(e.get("answer") or "").upper()
        word = {"APPROVE": "signed it off", "SEND BACK": "sent it back", "ESCALATE": "passed it up"}.get(
            ans, "couldn't check it")
        why = _cut(" ".join(e.get("notes") or []) or e.get("why") or "", 80)
        return f"  ◆ @{e.get('reviewer')} {word}" + (f": {why}" if why and ans != "APPROVE" else "")
    if ev == "audit" and e.get("phase") == "done":
        word = {"pass": "passed it", "concerns": "has concerns", "fail": "failed it"}.get(
            str(e.get("verdict") or "").lower(), "couldn't check it")
        return f"  ⚑ The auditor {word}" + (f": {_cut(e.get('line'), 80)}"
                                             if e.get("line") and word != "passed it" else "")
    if ev == "flow_end":
        st = e.get("status") or ""
        name = who or e.get("flow") or "the desk"
        return f"▦ {name} {'finished' if st == 'ok' else st}"
    if ev == "fault":
        return f"  ✗ {_cut(e.get('message'), 100)}"
    return ""


def observe(event: dict) -> None:
    """Called by the server's broadcast with every event. Returns at once with no tap open."""
    if not _TAPS or not isinstance(event, dict):
        return
    if event.get("type") == "fabric_event":
        rid, ev = str(event.get("run_id") or ""), str(event.get("event") or "")
        if ev == "heartbeat" or not rid:
            return
        for taps in list(_TAPS.values()):
            for tap in taps:
                if rid not in tap.runs:
                    parent = str(event.get("parent_run") or "")
                    mine = ((ev == "flow_start" and event.get("conversation_id") == tap.cid)
                            or (ev == "status" and event.get("status") == "running"
                                and (parent in tap.runs
                                     or (not parent and event.get("conversation_id") == tap.cid))))
                    if not mine:
                        continue
                    tap.runs[rid] = (f"{event.get('department')} desk" if event.get("department")
                                     else str(event.get("ref") or event.get("flow") or ""))
                tap.add(_run_line(tap, rid, ev, event))
        return
    for tap in _TAPS.get(str(event.get("conversation_id") or ""), ()):
        tap.add(_lead_line(event))


class Live:
    """One turn's steps on one phone chat. `edit` given (Telegram): one message, sent by
    `send(text)` (which returns its id) and then edited in place. No `edit` (WhatsApp): the
    new lines go as a short message every `every` seconds, at most `cap` of them a turn.

    Nothing is sent for a turn that ends within `first` seconds: a quick answer needs no
    running commentary, and the reply follows at once."""

    def __init__(self, tap: Tap, send, edit=None, every: float = 2.5, first: float = 3.0,
                 cap: int = 8):
        self.tap, self._send, self._edit = tap, send, edit
        self.every, self.first, self.cap = every, first, cap
        self.mid = None             # the edited message (edit mode)
        self.sent_n = 0             # lines already sent (batch mode)
        self.msgs = 0
        self.t0 = time.monotonic()
        self.task = asyncio.create_task(self._run())

    async def _show(self, done: bool = False) -> None:
        lines, n = list(self.tap.lines), self.tap.n
        if not lines:
            return
        if self._edit is not None:
            text = text_of(lines, done)
            if self.mid is None:
                self.mid = await self._send(text)
            else:
                await self._edit(self.mid, text)
            return
        new = lines[-min(n - self.sent_n, len(lines)):] if n > self.sent_n else []
        if not new or self.msgs > self.cap:
            return
        self.sent_n = n
        self.msgs += 1
        if self.msgs > self.cap:
            await self._send("⚙ …more steps are going on; the answer comes when they're done.")
            return
        await self._send(("⚙ " if self.msgs == 1 else "") + "\n".join(new[-SHOW:]))

    async def _run(self) -> None:
        while True:
            await self.tap.changed.wait()
            wait = self.first - (time.monotonic() - self.t0)
            if wait > 0:
                await asyncio.sleep(wait)
            self.tap.changed.clear()
            t = time.monotonic()
            try:
                await self._show()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass                # a refused edit (unchanged text, a rate limit) waits for the next
            await asyncio.sleep(max(0.0, self.every - (time.monotonic() - t)))

    async def end(self) -> None:
        """The turn is over: stop, and finish what is on the phone if anything was shown."""
        if self.task.done() and self.tap.cid not in _TAPS:
            return                  # ended already (the bridge's `finally` calls it again)
        self.task.cancel()
        try:
            await self.task
        except BaseException:
            pass
        try:
            if self.mid is not None or self.msgs:
                await self._show(done=True)
        except Exception:
            pass
        close(self.tap)


def text_of(lines: list[str], done: bool = False) -> str:
    """The live message: a header and the last SHOW lines."""
    shown = lines[-SHOW:]
    head = "⚙ Steps so far" + (f" (last {SHOW} of {len(lines)})" if len(lines) > SHOW else "")
    if done:
        head = "✓ Steps" + (f" (last {SHOW} of {len(lines)})" if len(lines) > SHOW else "")
    return head + "\n" + "\n".join(shown)


def on(cfg: dict, channel: str) -> bool:
    """Steps on the phone are on unless the person switched them off for that channel."""
    return (cfg.get(channel) or {}).get("live_steps", True) is not False
