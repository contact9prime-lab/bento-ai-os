#!/usr/bin/env python3
"""Check a Bento mission and write what it may do in plain words.

    python3 mission.py mission.json [-o mission.md]

mission.json is the shape Bento's Missions app saves (name, mission, roster, new_agents,
permissions, sinks, triggers). The check uses Bento's own closed sets and the lessons
its missions taught; the sheet is the consent block a person reads before Enable.
If `bento` is installed, `bento flow add --file mission.json` brings it in, switched off.

Standard library only. Generated from the Bento Box AI repository; do not edit by hand.
"""
import argparse
import json
import re
import sys
from pathlib import Path

# filled in from agentos/flows.py and agentos/brief.py when the skill is built
TRIGGER_KINDS = ('cron', 'message', 'webhook', 'os_event', 'flow_done', 'device')
SINK_KINDS = ('origin', 'telegram', 'whatsapp', 'gui', 'notify', 'report', 'conversation')
MEMORY_SCOPES = ('none', 'read', 'read-space', 'read-write')
BRIEF_KINDS = ('needs_you', 'decide', 'fyi', 'done')
NAME = re.compile(r"^[A-Za-z0-9_-]{1,49}$")
REMEMBERS = ("remember",)

MEMORY_WORDS = {"none": "does not read or write your memory",
                "read": "reads your memory, writes nothing to it",
                "read-space": "reads the memory of this space only, writes nothing",
                "read-write": "reads and writes memory, so the next run can compare with this one"}
TRIGGER_WORDS = {"cron": "on a schedule", "message": "when a message starts with a word you chose",
                 "webhook": "when its private web address is called",
                 "os_event": "when something happens on this computer",
                 "flow_done": "when another mission finishes", "device": "when a device changes"}


def check(m: dict) -> tuple[list, list]:
    """(problems that stop it, warnings worth reading)."""
    bad, warn = [], []
    if not NAME.match(str(m.get("name") or "")):
        bad.append("name: 1-49 letters, digits, '-' or '_'")
    if not str(m.get("mission") or "").strip():
        bad.append("mission: say what it is for, in the second person, specific enough to act on")
    new = {a.get("name"): a for a in (m.get("new_agents") or []) if isinstance(a, dict)}
    roster = [r if isinstance(r, dict) else {"subagent": r} for r in (m.get("roster") or [])]
    if not roster:
        bad.append("roster: at least one agent; the orchestrator delegates, it does not do the work")
    perms = m.get("permissions") or {}
    tools = list(perms.get("tools") or [])
    if not tools:
        bad.append("permissions.tools: list every tool the roster will use; a tool not granted is refused")
    mem = str(perms.get("memory") or "read-space")
    if mem not in MEMORY_SCOPES:
        bad.append(f"permissions.memory: one of {', '.join(MEMORY_SCOPES)}")
    if any(t in REMEMBERS for t in tools) and mem != "read-write":
        bad.append("a mission that remembers needs memory: read-write, or 'compare with last time' "
                   "compares with nothing")
    reach, known = set(), True
    for r in roster:
        name = r.get("subagent")
        agent = new.get(name)
        if agent is None:
            known = False
            warn.append(f"@{name} is not in new_agents: it must already exist on the machine")
            continue
        reach |= set(agent.get("tools") or [])
    missing = [t for t in tools if t not in reach]
    if known and roster and missing:
        bad.append(f"nobody on the roster can call {', '.join(missing)}: a specialist only calls "
                   f"the tools on its own list, so add them to one or drop the grant")
    for s in m.get("sinks") or []:
        k = s.get("kind") if isinstance(s, dict) else s
        if k not in SINK_KINDS:
            bad.append(f"sinks: {k!r} is not one of {', '.join(SINK_KINDS)}")
    for t in m.get("triggers") or []:
        k = (t or {}).get("kind")
        if k not in TRIGGER_KINDS:
            bad.append(f"triggers: {k!r} is not one of {', '.join(TRIGGER_KINDS)}")
        elif k == "flow_done" and ((t.get("config") or {}).get("flow") == m.get("name")):
            bad.append("triggers: a mission cannot follow itself")
    if "mail_send" in tools:
        warn.append("mail_send sends mail as you; Bento asks you every time, whatever this says")
    return bad, warn


def sheet(m: dict, warn: list) -> str:
    p = m.get("permissions") or {}
    lines = [f"# {m.get('name')}", "", str(m.get("description") or "").strip(), "",
             "## What it is told", "", str(m.get("mission") or "").strip(), "", "## Who does the work", ""]
    for r in m.get("roster") or []:
        r = r if isinstance(r, dict) else {"subagent": r}
        lines.append(f"- @{r.get('subagent')}" + (f": {r['why']}" if r.get("why") else ""))
    lines += ["", "## What it may do (nothing until you switch it on)", ""]
    lines.append(f"- Tools: {', '.join(p.get('tools') or []) or 'none'}")
    for key, words in (("fs_read", "Reads"), ("fs_write", "Writes"), ("net", "Fetches")):
        if p.get(key):
            lines.append(f"- {words}: {', '.join(p[key])}")
    lines.append(f"- Memory: {MEMORY_WORDS.get(str(p.get('memory') or 'read-space'), '')}")
    trig = [TRIGGER_WORDS.get((t or {}).get("kind"), "") + (f" ({json.dumps(t.get('config'))})"
            if t.get("config") else "") for t in m.get("triggers") or []]
    lines += ["", "## When it runs", "", "- " + ("\n- ".join(trig) if trig else "only when you say so"),
              "", "## What you get", "",
              f"- Items in your Brief ({', '.join(BRIEF_KINDS)}), not a wall of text"]
    if warn:
        lines += ["", "## Worth reading", ""] + [f"- {w}" for w in warn]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("mission", help="mission.json")
    ap.add_argument("-o", "--out", default="", help="the consent sheet (default: next to mission.json)")
    a = ap.parse_args(argv)
    m = json.loads(Path(a.mission).read_text(encoding="utf-8"))
    bad, warn = check(m)
    if bad:
        print("✗ not ready:\n  " + "\n  ".join(bad))
        return 1
    out = Path(a.out) if a.out else Path(a.mission).with_suffix(".md")
    out.write_text(sheet(m, warn), encoding="utf-8")
    for w in warn:
        print("note:", w)
    print(f"✓ {m['name']} is ready. Consent sheet: {out.resolve()}")
    print(f"  in Bento: bento flow add --file {a.mission}   (it arrives switched off)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
