"""What an approval says, once, for every surface that asks.

Reported with a screenshot: a long command (a heredoc, an app's whole HTML) made the
floating card taller than the screen, so Allow and Deny were below its edge and the
person could neither read what was asked nor answer it. Every surface built its own
line for the card (`JSON.stringify(args)` on the page, `json.dumps(args)[:120]` in the
TUI, `[:300]` on Telegram), so each one failed differently.

`card()` is the one answer, carried on the approval event:

- `goal` is what the agent is trying to achieve, in a sentence. When the agent said so
  in the reply that made the call, those are its words and `said` is True, and every
  surface shows them as a quote: it is the agent's claim, not a fact the gate checked.
  Otherwise it is the tool's own phrase plus the thing it acts on.
- `body` is exactly what will run or be written, in full up to `BODY_CAP`. A surface
  shows the start of it and says how much more there is. Truncating a command without
  saying so would hide the `; rm -rf ~` at the end of it, so `preview()` always says.

Stdlib only, no HTTP: the TUI, the CLI and the channels import it as they are.
"""
from __future__ import annotations

import json
import re

BODY_CAP = 20_000          # past this the card is not the place to read it
GOAL_MAX = 200
PREVIEW_LINES = 6
PREVIEW_CHARS = 600

# The tool's own phrase, for a call the agent did not explain. A tool missing here
# reads as its name in words ("export app to git"), which is still a sentence.
GOALS = {
    "run_command": "Run a command on this machine",
    "Bash": "Run a command on this machine",
    "write_file": "Write a file",
    "browser_click": "Click in your browser",
    "browser_type": "Type in your browser",
    "browser_key": "Press a key in your browser",
    "terminal_send": "Type into your terminal",
    "app_window_open": "Open an app in a window",
    "app_window_act": "Use an app window",
    "Write": "Write a file",
    "Edit": "Change a file",
    "edit_file": "Change a file",
    "mail_send": "Send an email",
    "create_app": "Build an app",
    "create_flow": "Set up a mission",
    "enable_flow": "Switch a mission on",
    "create_subagent": "Add a specialist to your team",
    "set_agent_brain": "Move an agent to another model",
    "delegate": "Hand work to a specialist",
    "send_files": "Send files to another team",
    "huddle": "Call a huddle with the team",
    "ask_agent": "Ask a colleague",
    "schedule_task": "Set up a schedule",
    "create_trigger": "Set up a trigger",
    "git_commit": "Commit changes",
    "git_push": "Push commits to a remote",
    "git_pull": "Pull from a remote",
    "git_clone": "Clone a repository",
    "fetch_url": "Open a web page",
    "run_python": "Run Python code",
    "install_mcp_server": "Install a tool server",
    "install_skill": "Install a skill from the internet",
    "request_capability": "Give a department or an agent an ability it lacks",
    "add_mcp_server": "Add a tool server",
    "install_openclaw_plugin": "Install a plugin",
    "enable_openclaw_plugin": "Switch a plugin on",
    "configure_agentos": "Change a setting",
    "update_agentos": "Update this machine",
    "develop_agentos": "Change AgentOS itself",
    "restart_agentos": "Restart AgentOS",
    "update_soul": "Change how your agent thinks of itself",
    "share_folder": "Share a folder",
    "set_engine": "Change the machine's brain",
    "launch_native_app": "Open an app on this machine",
    "pool_task": "Hand work to the community",
    "llm_generate": "Use the AI",
    "appAgent": "Ask your agent",
}

# The argument that names what a tool acts on, for the goal line.
_TARGET = ("path", "file_path", "name", "url", "to", "agent", "repo", "remote", "app")


def _words(name: str) -> str:
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(name or "a step")).replace("_", " ").strip()
    return s[:1].upper() + s[1:]


def _cut(s: str, n: int) -> str:
    s = " ".join(str(s or "").split())
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0] or s[:n]
    return cut.rstrip(",;:") + "…"


def intent(text: str) -> str:
    """The agent's own sentence about what it is about to do, from the reply that made
    the call: the last thing it said before the tool, without code or markdown. ''
    when it said nothing usable (most models call a tool without a word)."""
    t = str(text or "")
    t = re.sub(r"```.*?(```|$)", " ", t, flags=re.S)       # a code block is not a goal
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"[*_#>]+", "", t)
    paras = [p.strip() for p in re.split(r"\n\s*\n", t) if p.strip()]
    if not paras:
        return ""
    last = " ".join(paras[-1].split())
    # a sentence ends at a stop followed by a space: "-3.7 °C" or "2.6.1" is never split
    sentences = [x for x in re.split(r"(?<=[.!?])\s+", last) if x]
    out = ""
    for s in reversed(sentences):        # the whole last paragraph when it fits, else its end
        cand = (s.strip() + " " + out).strip()
        if len(cand) > GOAL_MAX and out:
            break
        out = cand
    out = out.rstrip(":").strip()
    return _cut(out, GOAL_MAX) if len(out) >= 8 else ""


def _target(name: str, args: dict) -> str:
    if name in ("run_command", "Bash"):
        return ""
    for k in _TARGET:
        v = args.get(k)
        if isinstance(v, str) and v.strip() and "\n" not in v.strip():
            return _cut(v, 80)
    return ""


def _fmt(v) -> str:
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, indent=1, ensure_ascii=False)
    except Exception:
        return str(v)


def body(name: str, args: dict) -> str:
    """Exactly what will run or be written. A command is itself; anything else is its
    arguments one per line, a long value in full (the surface collapses it)."""
    args = args if isinstance(args, dict) else {}
    if name in ("run_command", "Bash") and isinstance(args.get("command"), str):
        return args["command"]
    if name == "send_files":
        # what leaves this machine, by name, and for whom (linkfiles.py)
        names = [str(x) for x in (args.get("files") or [])][:12]
        return (f"To {args.get('to') or 'another team'}, with the task:\n"
                + "\n".join(f"- {n}" for n in names)
                + (f"\nNot sent: {'; '.join(args['refused'])}" if args.get("refused") else ""))
    if name == "request_capability":
        # what is asked, for whom and why, in words; the ability is one of a closed set
        who = str(args.get("who") or args.get("_from") or "an agent")
        what = {"run_code": "run Python code (each run is still asked)"}.get(str(args.get("ability") or ""), "")
        return f"{who} asks to {what or args.get('ability')}.\nWhy: {args.get('why') or '(not said)'}"
    if name == "install_skill":
        # what is installed is the text read earlier, so that text is the body
        from . import skillhub
        return skillhub.card_text(str(args.get("source") or ""))
    rows = []
    for k, v in args.items():
        if str(k).startswith("_") or k == "description" and name == "Bash":
            continue
        val = _fmt(v)
        rows.append(f"{k}:\n{val}" if "\n" in val else f"{k}: {val}")
    return "\n".join(rows)


def card(name: str, args: dict, said: str = "") -> dict:
    """{goal, said, body, lines, chars, cut}. `said` is the reply text that made the
    call; `cut` is how many characters past BODY_CAP were left off."""
    args = args if isinstance(args, dict) else {}
    goal = intent(said)
    from_agent = bool(goal)
    if not goal and name == "Bash" and isinstance(args.get("description"), str):
        goal, from_agent = _cut(args["description"], GOAL_MAX), True
    if not goal:
        goal = GOALS.get(name) or _words(name)
        tgt = _target(name, args)
        if tgt:
            goal = f"{goal}: {tgt}"
    full = body(name, args)
    cut = max(0, len(full) - BODY_CAP)
    text = full[:BODY_CAP]
    return {"goal": goal, "said": from_agent, "body": text,
            "lines": text.count("\n") + 1 if text else 0, "chars": len(full), "cut": cut}


def preview(c: dict, lines: int = PREVIEW_LINES, chars: int = PREVIEW_CHARS) -> str:
    """The start of the body for a surface that cannot collapse it (a terminal, a chat
    message), and ALWAYS a line saying how much is not shown."""
    b = str(c.get("body") or "")
    rows = b.splitlines()
    head = "\n".join(rows[:lines])
    if len(head) > chars:
        head = head[:chars].rstrip()
    shown_lines = head.count("\n") + 1 if head else 0
    more_lines = max(0, len(rows) - shown_lines)
    more_chars = max(0, int(c.get("chars") or len(b)) - len(head))
    if more_chars <= 0:
        return head
    tail = (f"{more_lines} more line{'s' if more_lines != 1 else ''}" if more_lines
            else f"{more_chars} more characters")
    return f"{head}\n… ({tail} not shown)"


def headline(c: dict) -> str:
    """The goal as a surface prints it: the agent's own words in quotes."""
    g = str(c.get("goal") or "")
    return f"“{g}”" if c.get("said") else g


def message(c: dict, reason: str = "", limit: int = 0, lines: int = PREVIEW_LINES) -> str:
    """The card as one plain-text message (Telegram, WhatsApp). The goal and the reason
    always fit; the preview shrinks to make room, so a 1024-character cap never cuts the
    reason off the end the way slicing the whole message did."""
    top = f"⚠ Approval needed\n{headline(c)}"
    tail = f"\n\n{reason}" if reason else ""
    chars = PREVIEW_CHARS
    while True:
        pv = preview(c, lines=lines, chars=chars)
        out = top + (f"\n\n{pv}" if pv else "") + tail
        if not limit or len(out) <= limit or chars <= 40:
            return out[:limit] if limit else out
        chars = max(40, chars - max(40, len(out) - limit))
        lines = max(1, min(lines, chars // 40))
