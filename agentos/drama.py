"""The drama reel: what the crew really did, told as a four-act story worth sharing.

The Office, the World and the comic strip animate the crew in a browser tab, and the
moments people would share — two agents arguing in a huddle, the gate refusing an
`rm -rf`, the agent trying again and shipping — scroll past and are gone. This module
keeps those moments as BEATS and turns the latest episode into a STORY: the argument,
the trouble, the fix, the ship. The page records the story as a 15 second clip or a
four-panel strip (`00g-drama.js`), the server paints the strip for places without a
page (`comic.manga`: `bento drama strip`, the route), and all of them read `story()`.

Four rules keep it honest:

- **Every beat is an event that happened.** Beats are taken from the broadcast — the
  one place huddle lines, agent questions, refusals, retries and finished work already
  pass — and nothing else writes them. A story with no trouble in it says so (`missing`)
  rather than borrowing a tantrum from somewhere.
- **Words in a balloon are the agent's own.** A huddle line is what the agent said; a
  refusal shows the command and the gate's reason; a fix shows what was run next. The
  act titles ("the argument", "the tantrum") are the narrator's and are drawn as
  captions, never as somebody's speech.
- **A person's "no" is not a tantrum.** The World's rule (`world.GENTLE`): when you
  decline, the act is "you said no" and the agent takes it calmly. Only the gate and the
  team's vote get the stamp.
- **Kept per person, in their own home, and bounded.** `KEEP` beats in `drama.json`
  beside their database, so `bento drama` works with the server down and an account
  never sees another's crew. Nothing is sent anywhere; sharing is the person's act.

Stdlib only, no HTTP and no asyncio, like jobs.py: the CLI and the server read the same
file through the same functions.
"""
from __future__ import annotations

import itertools
import json
import re
import threading
import time
from pathlib import Path

#: The kinds of beat, a closed set: who said what, what was refused, what came next.
KINDS = ("argue", "vote", "ask", "answer", "blocked", "declined", "outvoted", "fix", "done")
TROUBLE = ("blocked", "outvoted", "declined")
TALK = ("argue", "vote", "ask", "answer")
#: The four acts of a story, and what the narrator calls each one.
ACTS = ("argue", "trouble", "fix", "ship")
ACT_TITLE = {"argue": "The argument", "trouble": "The tantrum", "fix": "The fix", "ship": "Shipped"}
#: How the person on stage looks in each act: words from the World's EXPRESSIONS.
MOOD = {"argue": "pace", "vote": "think", "ask": "think", "answer": "think",
        "blocked": "tantrum", "outvoted": "slump", "declined": "care", "fix": "think", "done": "cheer"}
#: The stamp over the trouble act. A person's no is said plainly, never stamped red.
STAMP = {"blocked": "BLOCKED", "outvoted": "VOTED DOWN", "declined": "YOU SAID NO"}

KEEP = 120                  # beats kept per person: a reel, not a log
EPISODE_S = 3600            # an act more than an hour from the trouble is another story
TEXT = 280                  # a balloon's words, cut at a word
AGENT = "@agent"            # the lead, as avatars names it

_LOCK = threading.Lock()
_SEQ = itertools.count()
# Per (uid, conversation or run): who is speaking, what the turn has done so far.
_TURN: dict[tuple, dict] = {}
_CALL: dict[tuple, str] = {}        # (uid, call_id) -> what the call was, in words
_RUN: dict[tuple, dict] = {}        # (uid, run_id) -> {"who", "kind", "last", "refused", "steps"}
_CTL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f‪-‮⁦-⁩]")
_MAX_LIVE = 400                     # in-flight entries kept: a turn that never ends is dropped


def _home(uid: str) -> Path:
    from . import users as usersmod
    return usersmod.home_for(uid or "")


def path_for(uid: str = "") -> Path:
    return _home(uid) / "drama.json"


def _cut(text, n: int = TEXT) -> str:
    s = _CTL.sub("", " ".join(str(text or "").split()))
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0] or s[:n]
    return cut.rstrip(",;:") + "…"


def load(uid: str = "") -> list[dict]:
    try:
        rows = json.loads(path_for(uid).read_text())
        return [b for b in rows if isinstance(b, dict) and b.get("kind") in KINDS][-KEEP:]
    except (OSError, ValueError):
        return []


def _save(uid: str, beats: list[dict]) -> None:
    p = path_for(uid)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(beats[-KEEP:]))
        tmp.replace(p)
    except OSError:
        pass                                    # a full disk must never break a turn


def add(uid: str, kind: str, who: str, text: str = "", **extra) -> dict | None:
    """Keep one beat. The only writer; `observe` calls it with what it saw."""
    if kind not in KINDS or not who:
        return None
    beat = {"id": f"{int(time.time() * 1000):x}{next(_SEQ) % 256:02x}", "ts": time.time(),
            "kind": kind, "who": _cut(who, 40), "text": _cut(text)}
    for k in ("to", "reason", "model", "conv", "run", "tool"):
        if extra.get(k):
            beat[k] = _cut(extra[k], 160 if k == "reason" else 60)
    with _LOCK:
        beats = load(uid)
        beats.append(beat)
        _save(uid, beats)
    return beat


def clear(uid: str = "") -> int:
    with _LOCK:
        n = len(load(uid))
        try:
            path_for(uid).unlink()
        except OSError:
            pass
    return n


def _trim(d: dict) -> None:
    while len(d) > _MAX_LIVE:
        d.pop(next(iter(d)))


# ---- watching the broadcast -----------------------------------------------------------

def _outcome(output: str) -> str:
    from .world import step_outcome
    return step_outcome(output)


_KIND_OF = {"rules": "blocked", "person": "declined", "vote": "outvoted"}


def _reason(output: str) -> str:
    return str(output or "").removeprefix("[denied]").strip()


def observe(event: dict, uid: str = "") -> dict | None:
    """Called by the server's broadcast with every event. Keeps the beats that make a
    story and returns the beat that just FINISHED an episode (a ship after trouble),
    so the server can tell the page once. Cheap for everything else."""
    if not isinstance(event, dict):
        return None
    t = event.get("type")
    try:
        if t == "agent_say":
            if event.get("vote"):
                v = event["vote"]
                add(uid, "vote", v.get("by") or event.get("speaker") or AGENT, event.get("text", ""),
                    conv=event.get("conversation_id", ""))
            elif event.get("speaker") and event.get("text"):
                add(uid, "argue", event["speaker"], event["text"], model=event.get("model", ""),
                    conv=event.get("conversation_id", ""))
            return None
        if t == "agent_msg":
            kind = "ask" if event.get("phase") == "ask" else "answer"
            add(uid, kind, event.get("from") or "", event.get("text", ""), to=event.get("to", ""),
                conv=event.get("conversation_id", ""))
            return None
        if t in ("turn_start", "tool_start", "tool_end", "text_delta", "turn_end"):
            return _chat(event, uid)
        if t == "fabric_event":
            return _fabric(event, uid)
    except Exception:
        return None                             # the reel never breaks a broadcast
    return None


def _chat(event: dict, uid: str) -> dict | None:
    t = event["type"]
    cid = event.get("conversation_id") or ""
    key = (uid, cid)
    if t == "turn_start":
        if event.get("huddle"):                 # the huddle's lines arrive as agent_say
            _TURN.pop(key, None)
            return None
        _TURN[key] = {"who": event.get("speaker") or AGENT, "tools": 0, "refused": None,
                      "fixed": False, "said": ""}
        _trim(_TURN)
        return None
    st = _TURN.get(key)
    if st is None:
        return None
    if t == "tool_start":
        st["tools"] += 1
        if event.get("call_id"):
            _CALL[(uid, event["call_id"])] = _cut(event.get("detail") or event.get("name"), 160)
            _trim(_CALL)
        return None
    if t == "tool_end":
        what = event.get("detail") or _CALL.pop((uid, event.get("call_id") or ""), "") \
            or event.get("name", "")
        if event.get("ok") is False:
            kind = _KIND_OF.get(_outcome(event.get("output", "")))
            if kind:
                st["refused"] = kind
                add(uid, kind, st["who"], what, reason=_reason(event.get("output")),
                    conv=cid, tool=event.get("name", ""))
        elif st["refused"] and not st["fixed"]:
            st["fixed"] = True
            add(uid, "fix", st["who"], what, conv=cid, tool=event.get("name", ""))
        return None
    if t == "text_delta":
        if len(st["said"]) < TEXT:
            st["said"] += str(event.get("text") or "")
        return None
    # turn_end: work done is a ship; a plain answer is not a story
    _TURN.pop(key, None)
    if st["tools"]:
        beat = add(uid, "done", st["who"], _first(st["said"]), conv=cid)
        return beat if st["refused"] else None
    return None


def _fabric(event: dict, uid: str) -> dict | None:
    rid = event.get("run_id") or ""
    key = (uid, rid)
    ev = event.get("event")
    if ev == "status":
        status = event.get("status")
        if status == "running":
            if event.get("kind") in ("vote", "review", "audit", "freetalk") or event.get("ref") == "team":
                return None
            _RUN[key] = {"who": event.get("ref") or "", "last": "", "refused": None,
                         "fixed": False, "steps": 0}
            _trim(_RUN)
            return None
        st = _RUN.pop(key, None)
        if st and status == "ok" and st["steps"]:
            beat = add(uid, "done", st["who"], f"finished in {st['steps']} steps", run=rid)
            return beat if st["refused"] else None
        return None
    st = _RUN.get(key)
    if st is None or ev != "step":
        return None
    if event.get("status") == "start":
        st["steps"] += 1
        st["last"] = event.get("detail") or event.get("tool") or ""
        return None
    if event.get("ok") is False:
        kind = _KIND_OF.get(event.get("outcome") or "")
        if kind:
            st["refused"] = kind
            add(uid, kind, st["who"], event.get("detail") or st["last"] or event.get("tool", ""),
                run=rid, tool=event.get("tool", ""))
    elif st["refused"] and not st["fixed"]:
        st["fixed"] = True
        add(uid, "fix", st["who"], st["last"] or event.get("tool", ""), run=rid, tool=event.get("tool", ""))
    return None


def _first(text: str) -> str:
    s = " ".join(str(text or "").split())
    m = re.match(r"(.{12,200}?[.!?])(\s|$)", s)
    return _cut(m.group(1) if m else s, 200)


# ---- the story ------------------------------------------------------------------------

def story(beats: list[dict], cfg: dict | None = None) -> dict:
    """The latest episode, as four acts: the argument, the trouble, the fix, the ship.

    Built around the newest trouble (a refusal, a vote lost, your no). Talk in the hour
    before it is the argument; the next retry by the same agent is the fix; the next
    finished work is the ship. With no trouble yet, the newest talk and the newest
    finished work make a two-act story, and `missing` names what has not happened. An
    act is only ever a beat; nothing is filled in."""
    beats = sorted((b for b in beats if b.get("kind") in KINDS), key=lambda b: b.get("ts", 0))
    acts: dict[str, list[dict]] = {}
    trouble = next((b for b in reversed(beats) if b["kind"] in TROUBLE), None)
    if trouble:
        t0 = trouble["ts"]
        same = lambda b: (b.get("conv") and b.get("conv") == trouble.get("conv")) or \
            (b.get("run") and b.get("run") == trouble.get("run")) or b["who"] == trouble["who"]
        talk = [b for b in beats if b["kind"] in TALK and t0 - EPISODE_S <= b["ts"] <= t0]
        acts["argue"] = _argument(talk, trouble)
        acts["trouble"] = [trouble]
        fix = next((b for b in beats if b["kind"] == "fix" and b["ts"] >= t0 and same(b)
                    and b["ts"] - t0 <= EPISODE_S), None)
        acts["fix"] = [fix] if fix else []
        after = fix["ts"] if fix else t0
        ship = next((b for b in beats if b["kind"] == "done" and b["ts"] >= after
                     and b["ts"] - t0 <= EPISODE_S), None)
        acts["ship"] = [ship] if ship else []
    else:
        talk = [b for b in beats if b["kind"] in TALK]
        acts["argue"] = talk[-2:]
        acts["trouble"], acts["fix"] = [], []
        ship = next((b for b in reversed(beats) if b["kind"] == "done"), None)
        acts["ship"] = [ship] if ship else []
    out = []
    for act in ACTS:
        for b in acts.get(act) or []:
            out.append(panel(act, b, cfg))
    missing = [a for a in ACTS if not acts.get(a)]
    first = out[0]["ts"] if out else 0
    last = out[-1]["ts"] if out else 0
    return {"id": (trouble or (out[-1] if out else {})).get("id", ""),
            "panels": out[:4] if len(out) <= 4 else _four(out),
            "clip": out[:5],
            "missing": missing, "complete": not missing,
            "cast": sorted({p["who"] for p in out}),
            "span_s": round(last - first, 1),
            "title": title_of(out, cfg)}


def _words(text: str) -> set:
    return {w for w in re.findall(r"[\w-]{2,}", str(text or "").lower()) if w not in _STOP}


_STOP = {"the", "and", "it", "to", "of", "a", "is", "in", "on", "we", "do", "it", "this", "that", "no"}


def _argument(talk: list[dict], trouble: dict) -> list[dict]:
    """The two lines of the argument: the one that proposed what was then refused (it
    shares words with the refused command, "rm -rf"), and the answer to it from somebody
    else. With no such line, the last two said. Chosen from what was said, never edited."""
    want = _words(trouble.get("text"))
    for i, b in enumerate(talk):
        if want & _words(b.get("text")):
            reply = next((x for x in talk[i + 1:] if x["who"] != b["who"]), None)
            return [b] + ([reply] if reply else [])
    return talk[-2:]


def _four(out: list[dict]) -> list[dict]:
    """Two argument lines and three more acts is five panels; the strip has four, so the
    answer goes and the line that started it stays (the clip has room to say both)."""
    argue = [p for p in out if p["act"] == "argue"]
    return ([argue[0]] if argue else []) + [p for p in out if p["act"] != "argue"]


def label(key: str, cfg: dict | None = None) -> str:
    if key in (AGENT, "", None):
        return (cfg or {}).get("agent_name") or "your agent"
    return str(key).lstrip("@")


def panel(act: str, b: dict, cfg: dict | None = None) -> dict:
    kind = b["kind"]
    p = {"act": act, "kind": kind, "title": ACT_TITLE[act], "who": b["who"],
         "name": label(b["who"], cfg), "mood": MOOD.get(kind, "calm"), "ts": b.get("ts", 0),
         "id": b.get("id", "")}
    if kind in TALK:
        p["says"] = b.get("text", "")
        if b.get("to"):
            p["to"], p["to_name"] = b["to"], label(b["to"], cfg)
    elif kind in TROUBLE:
        p["command"] = b.get("text", "")
        p["stamp"] = STAMP[kind]
        p["reason"] = b.get("reason", "")
        if kind == "declined":
            p["title"] = "You said no"
    elif kind == "fix":
        p["command"] = b.get("text", "")
    elif kind == "done":
        p["says"] = b.get("text", "")
    if b.get("model"):
        p["model"] = b["model"]
    if p.get("command"):
        # a shell line reads as one ("$ rm -rf build/"); another tool says its own name
        p["shell"] = b.get("tool", "run_command") in ("run_command", "")
        if not p["shell"] and b.get("tool"):
            p["command"] = f"{b['tool']}: {p['command']}"
    return p


def title_of(panels: list[dict], cfg: dict | None = None) -> str:
    names = []
    for p in panels:
        if p["name"] not in names:
            names.append(p["name"])
    if not names:
        return "Nothing yet"
    who = names[0] if len(names) == 1 else " & ".join(names[:2]) + (" & co." if len(names) > 2 else "")
    if any(p["kind"] == "blocked" for p in panels):
        return f"{who} vs. the gate"
    if any(p["kind"] == "outvoted" for p in panels):
        return f"{who} lose a vote"
    if any(p["act"] == "argue" for p in panels):
        return f"{who} in a huddle"
    return f"{who} at work"


def text(st: dict) -> str:
    """The story in words, for the terminal and a caption: one line per act."""
    if not st["panels"]:
        return "No drama yet. Start a huddle (@a @b …) or give your crew some work."
    lines = [st["title"]]
    for p in st["panels"]:
        body = p.get("says") or p.get("command") or ""
        stamp = f"[{p['stamp']}] " if p.get("stamp") else ""
        why = f" ({p['reason']})" if p.get("reason") else ""
        lines.append(f"  {p['title']}: {p['name']}: {stamp}{body}{why}")
    if st["missing"]:
        lines.append("  not yet: " + ", ".join(ACT_TITLE[a].lower() for a in st["missing"]))
    return "\n".join(lines)
