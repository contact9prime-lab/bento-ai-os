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

import base64
import binascii
import contextvars
import json
import re

# Who is asking, for a card whose offer is None (a step confirmed every time has no
# remember, so the offer that named the asker is gone). Set around the approver call by the
# agent loop and /api/tool. Found live: an app's job card said "Aria wants to …".
ASKER: contextvars.ContextVar = contextvars.ContextVar("approval_asker", default=None)


def asker_of(principal) -> dict | None:
    if principal is None:
        return None
    return {"principal_kind": getattr(principal, "kind", ""), "principal_id": getattr(principal, "id", "")}

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
    "create_theme": "Change how the whole desktop looks",
    "create_theme_shell": "Draw a page over the whole desktop",
    "request_capability": "Give a department or an agent an ability it lacks",
    "open_company": "Open another of your companies",
    "new_company": "Start a new company",
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
    "schedule_app_job": "Run an app's script on a clock, with no model",
    "send_to_channel": "Send a message from an app to a chat",
    "train_autopilot": "Make a small model from a goal",
    "train_job": "Train a model on this machine",
    "train_datasets": "Get or write training examples",
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
    if name == "open_company":
        return (f"Open {args.get('company') or 'that company'}. This desk and this chat move to "
                f"its office, departments and people. The company that is open now is kept as it is.")
    if name == "new_company":
        return (f"Start a company called {args.get('name') or '(no name)'} and open it."
                + (f"\nWhat it is: {args.get('about')}" if args.get("about") else "")
                + (f"\nWhat it is for: {args.get('objective')}" if args.get("objective") else "")
                + "\nIt starts with no departments. The company that is open now is kept as it is.")
    if name == "request_capability":
        # what is asked, for whom and why, in words; the ability is one of a closed set
        who = str(args.get("who") or args.get("_from") or "an agent")
        what = {"run_code": "run Python code (each run is still asked)"}.get(str(args.get("ability") or ""), "")
        return f"{who} asks to {what or args.get('ability')}.\nWhy: {args.get('why') or '(not said)'}"
    if name == "schedule_app_job":
        # the script IS what is approved: the yes is a grant for exactly these bytes
        return (f"Every {args.get('interval_minutes')} minutes, with no model, as the app: run "
                f"this script and save what it prints under \"{args.get('key')}\" in the app's "
                f"data."
                + (f" When it prints a \"_message\", send it to {args['_send_labels']}."
                   if args.get("_send_labels") else "")
                + f"\n\n{args.get('script') or ''}")
    if name == "send_to_channel":
        return (f"To: {args.get('_dest_label') or args.get('to') or 'a chat'}\n\n"
                f"{str(args.get('text') or '')}")
    if name == "install_mcp_server":
        # the command that will run, with its version: the name alone says nothing about that
        from . import mcp_store
        return mcp_store.card_text(str(args.get("registry_name") or ""), str(args.get("env") or ""))
    if name == "install_skill":
        # what is installed is the text read earlier, so that text is the body
        from . import skillhub
        return skillhub.card_text(str(args.get("source") or ""))
    if name in ("browser_click", "browser_type", "browser_key") and args.get("_commit"):
        # the page's own label for what is pressed, never a bare ref number (cdpbrowser.commit_of)
        site = str(args.get("_site") or "the site")
        typed = f"\nTypes: {_fmt(args['text'])}" if name == "browser_type" and args.get("text") else ""
        return f"On {site}, as you: {args['_commit']}{typed}"
    rows = []
    for k, v in args.items():
        if str(k).startswith("_") or k == "description" and name == "Bash":
            continue
        val = _fmt(v)
        rows.append(f"{k}:\n{val}" if "\n" in val else f"{k}: {val}")
    return "\n".join(rows)


# --- What it means for the person -------------------------------------------------
# Reported with a screenshot: an app asked to run `echo aW1wb3J0… | base64 -d | python3`,
# and the card showed the base64 and five buttons. "I don't know what this means for me."
# So a card also says who is asking, what the step does in plain words (a hidden script
# decoded first), and what each button will do. All of it is read from the text: nothing
# here runs anything, and the card says the reading is not a check.

_B64 = re.compile(r"[A-Za-z0-9+/_-]{24,}={0,2}")
_DECODES = re.compile(r"\bbase64\s+(?:-d|--decode|-D)\b|b64decode|atob\(|frombase64string", re.I)
_RUNNER = re.compile(r"\|\s*(?:sudo\s+)?(python3?|bash|sh|zsh|node|perl|ruby|php)\b")
HIDDEN_MAX = 8_000


def _b64(tok: str) -> str:
    t = tok.replace("-", "+").replace("_", "/")
    try:
        raw = base64.b64decode(t + "=" * (-len(t) % 4), validate=True)
        text = raw.decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return ""
    ok = sum(c.isprintable() or c in "\n\r\t" for c in text)
    return text if text and ok >= 0.95 * len(text) else ""


def unhide(command: str) -> list[dict]:
    """The scripts a command carries in base64 and decodes to run: [{runs, text}]. A command
    that hides what it runs is the one a person most needs to read, so the card decodes it."""
    cmd = str(command or "")
    if not _DECODES.search(cmd):
        return []
    m = _RUNNER.search(cmd)
    runs = m.group(1) if m else ("python" if "b64decode" in cmd else "")
    out = []
    for tok in _B64.findall(cmd):
        text = _b64(tok)
        if text and len(text) >= 8:
            out.append({"runs": runs, "text": text[:HIDDEN_MAX]})
    return out[:3]


# What a script or command line visibly does, read from its words. Each is a plain phrase.
_DOES = (
    ("connects to the internet", r"\bcurl\b|\bwget\b|\brequests\.|urllib|http\.client|https?://|\bfetch\(|socket\."),
    ("deletes files", r"\brm\s|\brmdir\b|\bunlink\b|rmtree|os\.remove|\.unlink\("),
    ("writes or changes files", r"(?<![<>=!])>{1,2}\s*[^\s&=>]|open\([^)]*,\s*['\"][wax]|write_text|write_bytes|\.write\(|\b(?:mv|cp|mkdir|touch|chmod|chown|tee|sed\s+-i)\b"),
    ("reads files", r"\bopen\(|read_text|read_bytes|\bcat\s|\bhead\s|\btail\s|sqlite3|\bglob\b|listdir|os\.walk|\bls\b"),
    ("installs software", r"pip3?\s+install|apt(?:-get)?\s+install|npm\s+(?:i|install)\b|brew\s+install|\buv\s+(?:add|pip)"),
    ("runs other programs", r"subprocess|os\.system|\bexec\(|\beval\(|popen"),
    ("reaches Bento's own data", r"\.agentos\b|agentos\.db"),
    ("touches passwords, keys or tokens", r"\.ssh\b|\.env\b|passw|secret|token|api[_-]?key|keyring|vault"),
    ("needs administrator rights", r"\bsudo\b|\bsu\s"),
)


def does(text: str) -> list[str]:
    t = str(text or "")
    return [w for w, rx in _DOES if re.search(rx, t, re.I)]


def store_who(offer: dict | None, store=None, agent_name: str = "") -> str:
    """who_of with an app's name read from a Store, for surfaces holding one."""
    def app_name(aid):
        return ((store.get_app(aid) if store else None) or {}).get("name") or ""
    return who_of(offer, app_name, agent_name)


def who_of(offer: dict | None, app_name=None, agent_name: str = "") -> str:
    """Who is asking, as a person says it. `app_name(id)` looks an app's name up."""
    o = offer or ASKER.get() or {}
    kind, pid = str(o.get("principal_kind") or ""), str(o.get("principal_id") or "")
    if kind == "app":
        name = ""
        try:
            name = app_name(pid) if app_name else ""
        except Exception:
            name = ""
        return f'The app "{name or pid}"'
    if kind == "subagent":
        return f"Your agent {pid}" if pid else "One of your agents"
    if kind == "team":
        return f'The linked team "{pid.rstrip("/*")}"'
    if kind == "flow":
        return f'The mission "{pid}"'
    return agent_name or "Your agent"


def _covers(offer: dict | None) -> str:
    """What a remembered yes would cover, in words, read from the grant it would write."""
    res = str((offer or {}).get("resource") or "")
    if res.startswith("tool:run_command "):
        pat = res[len("tool:run_command "):].strip()
        if pat.startswith("@read-only:"):
            return ("read-only commands (ls, cat, head, grep and the like) on files in "
                    f"{pat[len('@read-only:'):]}, never a hidden file")
        if pat.startswith("{") and pat.endswith("}"):
            progs = [p.rstrip("*").strip() for p in pat[1:-1].split(",") if p.strip()]
            return "command lines made only of " + ", ".join(f"`{p}`" for p in progs)
        if pat.endswith("*") and "*" not in pat[:-1]:
            return f"commands that start with `{pat[:-1].strip()}`"
        return "this exact command"
    if res.startswith("fs:"):
        path = res[3:]
        return f"files in {path[:-2]}" if path.endswith("/*") else f"the file {path}"
    if res.startswith("net:"):
        u = res[4:].rstrip("*").rstrip("/")
        return f"pages on {u}"
    if res.startswith("tool:"):
        return f"the {_words(res[5:].rstrip('*')).lower()} tool"
    if res.startswith("agent:"):
        return f"asking {res.split('/')[-1]}"
    return "this kind of step"


def choices(offer: dict | None, who: str) -> dict:
    """What each button does, one sentence each, keyed as the page's buttons are."""
    if not offer:
        return {"allow": "It runs now. This kind of step asks you every time.",
                "deny": f"Nothing runs, and {_lc(who)} is told you said no."}
    if offer.get("label"):
        return {"allow": "It runs now, this once. Next time it asks again.",
                "deny": f"Nothing runs, and {_lc(who)} is told you said no.",
                "always": str(offer.get("note") or offer["label"])}
    what = _covers(offer)
    out = {"allow": "It runs now, this once. Next time it asks again.",
           "deny": f"Nothing runs, and {_lc(who)} is told you said no."}
    if offer.get("conversation_id"):
        out["chat"] = f"{who} may run {what} without asking, in this chat only, for up to a day."
    out["hour"] = f"{who} may run {what} without asking, for the next hour."
    out["always"] = (f"{who} may run {what} without asking, until you remove it in "
                     f"Permissions → Rules.")
    return out


# A yes that sets something up, rather than running one step: Allow's line says what it starts.
# "This kind of step asks you every time" read as if the job would ask on every run.
_SETS_UP = {
    "schedule_app_job": lambda a: (f"The job starts and runs every {a.get('interval_minutes')} minutes "
                                   f"without asking again, until you remove it in Missions → Schedule. "
                                   f"A changed script asks again."),
}


def _choices_for(name: str, args: dict, offer: dict | None, who: str) -> dict:
    out = choices(offer, who)
    if name in _SETS_UP and not offer:
        out["allow"] = _SETS_UP[name](args if isinstance(args, dict) else {})
        out["deny"] = f"Nothing is set up, and {_lc(who)} is told you said no."
    return out


def _lc(who: str) -> str:
    return who[:1].lower() + who[1:] if who.startswith(("Your", "One", "The")) else who


def meaning(name: str, args: dict, who: str, hidden: list[dict]) -> list[str]:
    """Two or three plain sentences: who wants what, and what it would do to you."""
    args = args if isinstance(args, dict) else {}
    lines = []
    if name in ("run_command", "Bash"):
        cmd = str(args.get("command") or "")
        lines.append(f"{who} wants to run a command on this computer. It runs as you, so it can "
                     f"do what you can do with your files.")
        if hidden:
            lines.append("The command hides the script it runs in base64, which is unusual. "
                         "It is decoded below so you can read what would really run.")
        found = does(cmd + "\n" + "\n".join(h["text"] for h in hidden))
        if found:
            lines.append("Read from its text, it " + _join(found) + ". That is a reading, not a check.")
    elif name in ("write_file", "Write", "Edit", "edit_file"):
        path = args.get("path") or args.get("file_path") or "a file"
        lines.append(f"{who} wants to change {path} on this computer.")
    elif name == "schedule_app_job":
        lines.append(f"{who} wants to run its own Python script every {args.get('interval_minutes')} "
                     f"minutes, with no model, to keep its numbers fresh. Each run goes through "
                     f"your permissions and the ethics check, and shows in Missions → History.")
        found = does(str(args.get("script") or ""))
        if found:
            lines.append("Read from its text, the script " + _join(found) + ". That is a reading, not a check.")
        if args.get("_send_labels"):
            lines.append(f"When a run has something to say, it also sends it to "
                         f"{args['_send_labels']}, starting with the app's name.")
        lines.append("If the script changes, you're asked again.")
    elif name == "send_to_channel":
        lines.append(f"{who} wants to send this message to "
                     f"{args.get('_dest_label') or 'a chat'}. It starts with the app's name, so "
                     f"whoever reads it knows an app sent it. Always lets this app send there "
                     f"again without asking, including from its schedules.")
    elif name == "run_python":
        lines.append(f"{who} wants to run Python code on this computer.")
        found = does(str(args.get("code") or ""))
        if found:
            lines.append("Read from its text, it " + _join(found) + ". That is a reading, not a check.")
    else:
        g = GOALS.get(name) or _words(name)
        lines.append(f"{who} wants to: {g[:1].lower() + g[1:]}.")
    return lines


def _join(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def card(name: str, args: dict, said: str = "", offer: dict | None = None,
         who: str = "") -> dict:
    """{goal, said, body, lines, chars, cut, who, means, choices, hidden}. `said` is the
    reply text that made the call; `cut` is how many characters past BODY_CAP were left
    off; `offer` is the grant a remembered yes would write, which the choices describe."""
    args = args if isinstance(args, dict) else {}
    who = who or who_of(offer)
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
    hidden = unhide(args.get("command")) if name in ("run_command", "Bash") else []
    if hidden:
        # what really runs comes first, and the command as sent after it
        shown = "\n\n".join(f"Decoded, it runs this{' with ' + h['runs'] if h['runs'] else ''}:\n{h['text']}"
                             for h in hidden)
        full = f"{shown}\n\nThe command as sent:\n{full}"
    cut = max(0, len(full) - BODY_CAP)
    text = full[:BODY_CAP]
    return {"goal": goal, "said": from_agent, "body": text,
            "lines": text.count("\n") + 1 if text else 0, "chars": len(full), "cut": cut,
            "who": who, "means": meaning(name, args, who, hidden), "hidden": bool(hidden),
            "choices": _choices_for(name, args, offer, who)}


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


def message(c: dict, reason: str = "", limit: int = 0, lines: int = PREVIEW_LINES,
            buttons: tuple = ("allow", "deny", "hour", "always"), labels: dict | None = None) -> str:
    """The card as one plain-text message (Telegram, WhatsApp). The goal and the reason
    always fit; the preview shrinks to make room, so a 1024-character cap never cuts the
    reason off the end the way slicing the whole message did. When even that is too long,
    the buttons' meanings go first, then what it means (the goal and reason stay)."""
    means = " ".join(c.get("means") or [])
    ch = c.get("choices") or {}
    names = {"allow": "Allow once" if "hour" in ch else "Allow", "deny": "Deny",
             "hour": "1 hour", "always": "Always", **(labels or {})}
    opts = [f"• {names[k]}: {ch[k]}" for k in buttons if ch.get(k)]
    out = ""
    for with_means, with_opts in ((True, True), (True, False), (False, False)):
        top = f"⚠ Approval needed\n{headline(c)}" + (f"\n\n{means}" if means and with_means else "")
        # the buttons' meaning before the reason: the reason is always the last line
        tail = ("\n\n" + "\n".join(opts) if opts and with_opts else "") + (f"\n\n{reason}" if reason else "")
        chars, n = PREVIEW_CHARS, lines
        while True:
            pv = preview(c, lines=n, chars=chars)
            out = top + (f"\n\n{pv}" if pv else "") + tail
            if not limit or len(out) <= limit or chars <= 40:
                break
            chars = max(40, chars - max(40, len(out) - limit))
            n = max(1, min(n, chars // 40))
        if not limit or len(out) <= limit:
            return out
    return out[:limit]
