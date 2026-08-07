"""Executors — handing a task to another agent that already lives on this machine.

AgentOS owns the desktop: the compositor, the windows, the hardware controls. What
it does not need to own is every way of *doing work*. If the user already has a
capable coding agent installed, the OS should be able to delegate to it rather
than reimplement it.

Claude Code is the first executor. It is not a computer-control agent — it has no
screen, mouse, or keyboard — so the division is clean: AgentOS drives the machine,
the executor does files, shell, code, and research inside a directory we hand it.

Two things make this safe enough to offer:

1. **A capability envelope, decided before the run starts.** This build of the
   Claude Code CLI has no per-call permission hook, so we cannot approve tools one
   at a time the way `agent.py` does. Pretending otherwise would be worse than
   useless. Instead every run is bounded up front — which directory, which tools,
   which model, how many dollars — and AgentOS asks the user to approve *that
   envelope* once. What the CLI cannot be told to allow, it cannot do.
2. **Its events become our events.** The executor's stream is translated into the
   same turn events the AgentOS agent emits (`turn_start`, `text_delta`,
   `tool_start`, `tool_end`, `turn_end`), so a delegated run is watched, stopped
   and logged exactly like a local one — no second, weaker UI for "the other
   agent".
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Tools we offer to hand over, in the CLI's own vocabulary. Deliberately a short
# list of the ones that make sense for delegated work — an executor that could
# reach for anything would make the envelope meaningless.
KNOWN_TOOLS = ("Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebFetch", "WebSearch")

# What a run gets when the user has expressed no preference: read and search, but
# nothing that writes to disk or runs a command. Widening this is a decision the
# user makes in Settings, not a default they inherit.
DEFAULT_TOOLS = ("Read", "Glob", "Grep", "WebSearch")

# What a run may spend before it is cut off. The number means two very different
# things depending on how the CLI is signed in, and conflating them is what made
# real work stop half-finished:
#
#   API key       every dollar is a dollar. A tight ceiling is a real safeguard.
#   subscription  nothing is billed per token — the CLI reports a NOTIONAL cost.
#                 A $2 ceiling there controls no spending whatsoever; it only
#                 stops the work. A build died mid-`python -m venv` at $2.40 on a
#                 Max plan, which cost the user nothing and lost them the app.
#
# So the default follows the billing mode. It is still a runaway-loop backstop in
# both cases, and still the user's to change.
DEFAULT_BUDGET_USD = 2.0
SUBSCRIPTION_BUDGET_USD = 25.0
MAX_BUDGET_USD = 100.0


@dataclass
class Envelope:
    """Everything a run is allowed to do, fixed before it starts."""

    workspace: str
    tools: tuple[str, ...] = DEFAULT_TOOLS
    model: str = ""                      # "" = the executor's own default
    budget_usd: float = DEFAULT_BUDGET_USD
    session_id: str = ""                 # resume a previous delegated run
    # What the caller is looking at. The built-in agent receives this as
    # `extra_system`; without it here, a copilot turn reached the executor as a
    # bare sentence — "make the button bigger" with no idea which button, in
    # which app, on whose screen. Same text, same channel, so the two kinds of
    # turn actually behave the same way.
    context: str = ""
    # Opt-in: may this run also reach AgentOS's own source? Off by default,
    # because "the OS can rewrite itself" is a decision someone makes on purpose,
    # not a side effect of enabling an executor.
    allow_source: bool = False

    def describe(self) -> str:
        """One sentence a person can approve or refuse."""
        tools = ", ".join(self.tools) if self.tools else "no tools"
        writes = any(t in self.tools for t in ("Write", "Edit", "Bash"))
        where = self.workspace
        if self.allow_source:
            where += " and AgentOS's own source"
        return (f"Claude Code in {where} with {tools}"
                f"{' (can change files and run commands)' if writes else ' (read-only)'}"
                f", up to ${self.budget_usd:.2f}")

    def sanitized(self) -> "Envelope":
        """Clamp anything the caller got wrong rather than trusting it."""
        tools = tuple(t for t in self.tools if t in KNOWN_TOOLS)
        # `or DEFAULT` would be wrong here: 0 is falsy, so asking for no spend at
        # all would silently become the default budget — a widening, in the one
        # place that exists to prevent them. Only a missing value takes the default.
        raw = default_budget() if self.budget_usd is None else float(self.budget_usd)
        budget = max(0.05, min(raw, MAX_BUDGET_USD))
        ws = str(Path(self.workspace).expanduser())
        # UI-supplied and it lands in a system prompt, so it gets the same
        # treatment the local agent's extra_system gets: capped, and stripped of
        # control characters that could forge structure in the prompt.
        ctx = "".join(c for c in str(self.context or "")[:4096]
                      if c in "\n\t" or ord(c) >= 32)
        return Envelope(workspace=ws, tools=tools, model=self.model,
                        budget_usd=budget, session_id=self.session_id, context=ctx,
                        allow_source=bool(self.allow_source))


@dataclass
class Run:
    """A live delegated run, so it can be watched and stopped."""

    proc: asyncio.subprocess.Process | None = None
    session_id: str = ""
    model: str = ""                # what actually answered, reported by the CLI
    cost_usd: float = 0.0
    turns: int = 0
    denials: list = field(default_factory=list)
    stopped: bool = False
    reported_error: bool = False   # the result event already said why; don't say it twice
    # call_id -> (name, detail) for the calls seen so far. The CLI reports a tool
    # RESULT with only the id, so without this the end of a call is anonymous —
    # which is how a ten-minute build read as ten minutes of nothing.
    calls: dict = field(default_factory=dict)
    steps: int = 0                 # tool calls started, for a live "step N" line
    last: str = ""                 # what it is doing right now, in words
    dropped: int = 0               # stream events too large to read (see STREAM_LINE_LIMIT)


# --- forwarding: the machine as a front end ---------------------------------
#
# `engine` in config turns the whole machine into a forwarder: every turn a
# PERSON starts goes to another agent instead of the built-in one. Set it once
# and the chat window, the omnibar, a copilot panel, Telegram, the headless API
# and scheduled turns all route the same way — otherwise "forward everything"
# would mean "forward the chat window", which is not what it says.
#
# Two callers are deliberately NOT forwarded, because they are machinery with
# their own contract rather than someone asking a question:
#
#   * the app runtime (`appAgent`) — a user app calls it expecting AgentOS's
#     tools and its own private data store. An executor has neither, so
#     forwarding would break every app that uses it.
#   * App Studio's builder — it already has an explicit build-model choice, and
#     silently substituting a different agent is the exact behaviour the model
#     picker exists to prevent.
#
# The UI states this rather than implying totality.
ENGINES = ("aria", "claude-code", "hermes")
FORWARDED_SURFACES = ("chat", "omnibar", "copilot", "telegram", "api", "task")


def resolve_engine(cfg: dict, requested: str = "") -> str:
    """Which agent should answer this turn.

    An explicit per-turn choice always wins — picking a model in one chat is a
    local override, not a fight with the machine setting. Otherwise the machine's
    own engine decides, so a forwarder stays a forwarder on every surface.
    """
    if requested in ("claude-code", "hermes"):
        return requested
    if requested:                      # a real model id: the built-in agent
        return "aria"
    engine = str((cfg or {}).get("engine") or "aria")
    return engine if engine in ENGINES else "aria"


def forwarding(cfg: dict) -> str:
    """The engine this machine forwards to, or "" when it answers for itself."""
    engine = resolve_engine(cfg)
    return "" if engine == "aria" else engine


def default_budget() -> float:
    """The ceiling to use when the user has not set one."""
    return (SUBSCRIPTION_BUDGET_USD if billing().get("mode") == "subscription"
            else DEFAULT_BUDGET_USD)


def envelope_from(cfg: dict, workspace_default: str) -> "Envelope":
    """The configured envelope — one reading of config, used by every surface."""
    conf = ((cfg or {}).get("executors") or {}).get("claude_code") or {}
    return Envelope(
        workspace=conf.get("workspace") or workspace_default,
        tools=tuple(conf.get("tools") or DEFAULT_TOOLS),
        model=conf.get("model", ""),
        budget_usd=float(conf.get("budget_usd") or default_budget()),
        allow_source=bool(conf.get("allow_source")),
    ).sanitized()


async def forward(engine: str, text: str, cfg: dict, workspace_default: str,
                  emit=None, session_id: str = "",
                  context: str = "") -> tuple[str, "Run | None"]:
    """Send one turn to another agent and return what it said.

    Used by the surfaces that have no event stream of their own (Telegram, the
    headless API, scheduled turns). The chat path streams instead, so it drives
    `run_task` directly.
    """
    collected: list[str] = []

    async def sink(ev: dict):
        if ev.get("type") == "text_delta":
            collected.append(ev.get("text", ""))
        if emit:
            await emit(ev)

    if engine == "hermes":
        from . import hermes as hermesmod
        return await hermesmod.ask(text), None

    env = envelope_from(cfg, workspace_default)
    env.session_id = session_id
    # Always, even when the surface supplies nothing of its own: a forwarded
    # Telegram or scheduled turn otherwise arrives believing it owns the desktop.
    env.context = context_for(context)
    run = Run()
    await run_task(text, env, sink, run)
    return "".join(collected), run


# The copilot's context is written for the BUILT-IN agent and ends by naming
# tools an executor does not have. Handed to Claude Code unedited it is worse
# than no context at all: it tells a filesystem agent to reach for
# control_desktop and write_file, so it flails at an app it was never able to
# touch. This line is replaced rather than passed through.
_LOCAL_TOOLS_HINT = "Desktop control is available via"


def context_for(ui_context: str) -> str:
    """Translate the UI's per-surface context for an executor.

    The copilot preamble is written for the built-in agent and ends by naming
    tools only it has. Handed to a filesystem agent unedited it is worse than no
    context: it sends it reaching for control_desktop and write_file.

    What it must NOT do is assert where apps live. AgentOS has two kinds, and
    they are opposites: a user app is a row in the database, a built-in app
    (Settings, Files, Chat) is part of the OS's own source. A blanket "apps are
    database rows" told someone asking to fix the Settings window that it needed
    App Studio — false, and App Studio cannot edit Settings either. That belongs
    per-app, in `app_note`, where the kind is actually known.
    """
    lines = [ln for ln in str(ui_context or "").splitlines()
             if not ln.startswith(_LOCAL_TOOLS_HINT)]
    body = "\n".join(lines).strip()
    preamble = (
        "You are answering inside AgentOS, an agentic desktop OS, as a delegated "
        "executor. Know your limits here:\n"
        "- You have no screen, no keyboard and no control of the desktop. AgentOS "
        "owns those. Do not claim to have clicked, opened or focused anything.\n"
        "- You cannot use AgentOS's own tools (control_desktop, read_file, "
        "write_file, create_app and the rest). You have only the tools you were "
        "started with, inside the directories you were given."
    )
    return (preamble + ("\n\n" + body if body else "")).strip()


def builtin_app_note(app_id: str, allow_source: bool) -> str:
    """What to say about a BUILT-IN app — part of AgentOS itself, not a DB row.

    Getting this wrong is how "fix the theme dropdown in Settings" came back as
    "AgentOS apps live in the database, use App Studio": untrue of a built-in
    app, and a dead end, since App Studio cannot touch Settings either. When the
    source is not granted, the honest answer names the switch that grants it.
    """
    if not allow_source:
        return (f"\nIMPORTANT: \"{app_id}\" is a BUILT-IN part of AgentOS — its window "
                "is the OS's own source code, not a database row and not something "
                "App Studio can edit. You have NOT been given that source, so you "
                "cannot change it from here. Say exactly that, and say the switch is "
                "\"Let it work on AgentOS itself\" in Settings → Executors. Do not "
                "suggest App Studio for this, and do not look for it in the database.")
    return (f"\n\"{app_id}\" is a BUILT-IN part of AgentOS and you DO have its source. "
            f"Its window is drawn by JavaScript in {source_root()}/agentos/ui/src/js/ "
            f"and styled in {source_root()}/agentos/ui/src/css/ — grep those for "
            f"\"{app_id}\" or for the visible label to find the right file. Edit "
            "`ui/src`, never `agentos/ui/index.html`, then run "
            "`python -m agentos.ui.build`. Tell the user to reload the desktop to see it.")


# --- letting a filesystem agent edit something that is not a file -----------
#
# An AgentOS app is a row in the database, and Claude Code only understands
# files. Explaining that was honest but useless: the answer was always "ask
# somebody else". So the app is checked OUT to a real file inside the workspace
# the executor already has, edited there, and written back as a new version.
#
# Write-back is safe because it goes through `save_app`, which records a version
# on every change and keeps the last 30 — so a bad edit is one Restore away,
# exactly like an App Studio edit. Nothing else about the envelope changes: the
# file lives inside the one directory the executor was already allowed.

APP_DIRNAME = "apps"
MAX_APP_HTML = 2_000_000        # a runaway write must not become a DB row


def checkout_app(store, app_id: str, workspace: str) -> dict | None:
    """Put an app on disk so the executor can actually work on it."""
    app = store.get_app(app_id)
    if not app:
        return None
    before = app.get("html") or ""
    d = Path(workspace).expanduser() / APP_DIRNAME / app_id
    d.mkdir(parents=True, exist_ok=True)
    path = d / "app.html"
    path.write_text(before, encoding="utf-8")
    (d / "README.md").write_text(
        f"# {app.get('name', 'App')}\n\n"
        f"{app.get('description', '')}\n\n"
        "This is an AgentOS application: ONE self-contained HTML document —\n"
        "markup, CSS and JavaScript in a single file, no build step and no\n"
        "external assets.\n\n"
        "`app.html` is the whole app. Edit it in place. When you finish, AgentOS\n"
        "saves it back as a new version of the app (the previous version stays in\n"
        "the app's history, so a bad edit can be rolled back).\n\n"
        "Do not rename or move this file, and do not add files expecting them to\n"
        "be served — only `app.html` is saved back.\n",
        encoding="utf-8")
    return {"app_id": app_id, "name": app.get("name", ""), "icon": app.get("icon", ""),
            "description": app.get("description", ""), "path": str(path),
            "dir": str(d), "before": before}


def app_checkout_note(co: dict, tools: tuple[str, ...]) -> str:
    """What to tell the executor about the app now sitting in its workspace."""
    can_write = any(t in tools for t in ("Write", "Edit"))
    if not can_write:
        return (f"\nThe app \"{co['name']}\" is checked out READ-ONLY at {co['path']}. "
                "You may read it, but your envelope has no Write or Edit tool, so you "
                "cannot change it — say what you would change, or ask for those tools "
                "in Settings → Executors.")
    return (f"\nThe app \"{co['name']}\" is checked out at {co['path']} — that file IS "
            "the app: one self-contained HTML document. Edit it in place with your "
            "normal file tools and AgentOS saves it back as a new version when you "
            "finish (the old version stays in the app's history). Read it before "
            "changing it, keep it self-contained, and change only what was asked.")


def commit_app(store, co: dict, note: str = "") -> tuple[bool, str]:
    """Save an edited checkout back to the app it came from."""
    try:
        after = Path(co["path"]).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return False, "the app file was deleted rather than edited — nothing saved"
    except Exception as exc:
        return False, f"could not read the edited app back: {exc}"
    if after == co["before"]:
        return False, ""                      # nothing changed: not worth saying
    if not after.strip():
        return False, "the app file was emptied — refusing to save that"
    if len(after) > MAX_APP_HTML:
        return False, f"the edited app is {len(after) // 1000}KB, past the limit — not saved"
    try:
        store.save_app(co["name"], co["icon"], co["description"], after,
                       note or "edited by Claude Code")
    except Exception as exc:
        return False, f"could not save the app: {exc}"
    return True, f"saved “{co['name']}” as a new version"


BUILD_DIRNAME = "builds"
# A build gets more room than a chat turn, because the failure the ceiling causes
# is the expensive one: a half-finished app is worth nothing, while a chat answer
# that stops early is merely short. This is a floor for builds, still clamped by
# MAX_BUDGET_USD and still the user's to change.
BUILD_MIN_BUDGET_USD = 10.0


def build_dir(workspace: str, name: str) -> str:
    """Where an app being built by an executor lives while it is being built."""
    safe = "".join(c if (c.isalnum() or c in "-_") else "-" for c in (name or "app"))[:40]
    return str(Path(workspace).expanduser() / BUILD_DIRNAME / (safe or "app"))


def prepare_build(workspace: str, name: str, existing_html: str = "") -> dict:
    """Set up a directory an executor can actually build an app in.

    The built-in builder has one turn to emit a whole app in one fenced block,
    which is why an ambitious brief comes back as a sketch. An executor works the
    way a person does instead — write the file, read it, run it back, fix it —
    for as many steps as it needs, because the app is a FILE the whole time
    rather than one enormous message it has to get right first try.
    """
    d = Path(build_dir(workspace, name))
    d.mkdir(parents=True, exist_ok=True)
    path = d / "app.html"
    if existing_html and not path.exists():
        path.write_text(existing_html, encoding="utf-8")
    elif not path.exists():
        path.write_text("", encoding="utf-8")
    return {"dir": str(d), "path": str(path),
            "before": path.read_text(encoding="utf-8", errors="replace")}


def build_task(prompt: str, co: dict, persona: str) -> str:
    """The brief handed to an executor building an AgentOS app."""
    return (
        f"{persona}\n\n"
        "=== HOW TO DELIVER IT HERE ===\n"
        f"You are building this app as a FILE: {co['path']}\n"
        "Write the complete app there — one self-contained HTML document, all CSS and\n"
        "JS inline, no external assets. AgentOS installs that file as the app when you\n"
        "finish, so the file IS the deliverable; nothing you print in chat is installed.\n"
        "Work like an engineer, not a one-shot generator: write it, read it back, check\n"
        "the JS for the mistakes listed above, and keep going until it is genuinely\n"
        "finished and would survive a demo. Do not stop at a sketch or a TODO, and do\n"
        "not ask whether to continue — finish it.\n\n"
        f"=== WHAT TO BUILD ===\n{prompt}\n"
    )


def read_build(co: dict) -> tuple[str, str]:
    """The built app, or why there isn't one. Returns (html, problem)."""
    try:
        html = Path(co["path"]).read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return "", f"the executor left no app file ({exc})"
    if not html.strip():
        return "", "the executor finished without writing the app"
    if len(html) > MAX_APP_HTML:
        return "", f"the built app is {len(html) // 1000}KB, past the limit"
    if "<" not in html:
        return "", "what the executor wrote does not look like an app"
    return html, ""


def source_root() -> str:
    """The AgentOS checkout this process is running from."""
    return str(Path(__file__).resolve().parent.parent)


def source_note(root: str) -> str:
    """What the executor needs to know before it edits the OS it is running in."""
    return (
        f"\nAgentOS's own source is at {root} and you may change it. Read before you "
        "write; match the surrounding style. Two things are load-bearing here:\n"
        "- The UI is BUILT, not edited. Change `agentos/ui/src/` and run "
        "`python -m agentos.ui.build`; editing `agentos/ui/index.html` directly is "
        "overwritten and a test fails on a stale bundle.\n"
        "- Run the test suite (`python -m pytest -q`) after a change. A change that "
        "breaks it is not finished.\n"
        "You are editing the program that is currently running: it does not pick up "
        "your changes until it restarts, which the user does — say what needs a "
        "restart rather than restarting it yourself."
    )


def claude_exe() -> str:
    """Absolute path to the Claude Code CLI, found the way a GUI-launched process
    has to look for it.

    `shutil.which("claude")` alone is wrong here and was reporting "not installed"
    on a machine where it plainly was. The server is started by systemd (or a
    macOS LaunchAgent), which does NOT source a login shell — so `~/.local/bin`,
    where Claude Code installs itself, is simply absent from PATH. The user's own
    terminal finds it; the service does not. `mcp_client._extended_path()` already
    exists for exactly this failure and is what npx/uvx resolution uses.
    """
    from .mcp_client import _extended_path
    return shutil.which("claude", path=_extended_path()) or ""


def available() -> dict:
    """Is there an executor to delegate to on this machine?

    Reports the reason when there isn't, so the UI can explain rather than just
    greying a control out.
    """
    exe = claude_exe()
    if not exe:
        # "Not installed" on its own is a dead end. Say what to run, and offer to
        # run it — the same shape components.py uses for everything optional:
        # the exact command in view, nothing installed without agreeing to it.
        return {"available": False,
                "reason": "Claude Code is not installed on this machine.",
                "install": "https://claude.com/claude-code",
                "install_cmd": INSTALL_CMD,
                "install_note": ("Installs Anthropic's Claude Code CLI into your own "
                                 "account. It signs in with your Claude subscription — "
                                 "AgentOS never passes it an API key."),
                "can_install": bool(shutil.which("npm") or shutil.which("curl"))}
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10)
        version = (out.stdout or "").strip()
    except Exception as e:
        return {"available": False, "reason": f"Claude Code did not answer: {e}"}
    signed_in = billing().get("mode") == "subscription"
    return {"available": True, "path": exe, "version": version,
            "tools": list(KNOWN_TOOLS), "default_tools": list(DEFAULT_TOOLS),
            # Installed but nobody signed in is its own dead end, and a different
            # one: the fix is a terminal, not an installer.
            "needs_signin": not signed_in,
            "signin_cmd": "claude" if not signed_in else ""}


# The official installer. Kept as data so the UI can show the exact command
# before anything runs, and so there is one place to correct it.
INSTALL_CMD = "curl -fsSL https://claude.ai/install.sh | bash"


async def install(note=None) -> tuple[bool, str]:
    """Install the Claude Code CLI, streaming progress to `note`.

    Never silent and never elevated: it installs into the user's own account,
    exactly the command shown in the UI beforehand.
    """
    if claude_exe():
        return True, "Claude Code is already installed"
    env = child_env()
    try:
        proc = await asyncio.create_subprocess_shell(
            INSTALL_CMD, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, env=env)
    except Exception as exc:
        return False, f"could not start the installer: {exc}"
    tail: list[str] = []
    assert proc.stdout is not None
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        text = line.decode(errors="replace").rstrip()
        if not text:
            continue
        tail.append(text)
        del tail[:-40]
        if note:
            await note(text[:200])
    code = await proc.wait()
    if code != 0:
        return False, ("the installer failed:\n" + "\n".join(tail[-8:]))[:600]
    if not claude_exe():
        return False, ("the installer finished but `claude` is not on PATH yet — "
                       "open a new terminal, or add ~/.local/bin to your PATH")
    return True, "Claude Code installed — run `claude` once to sign in"


def permission_mode(env: Envelope) -> str:
    """Which CLI permission mode matches the envelope we already agreed.

    This was a single hardcoded `dontAsk`, chosen to stop a headless run blocking
    on a prompt nobody can answer. Tested against a real edit, it turned out to
    *deny* rather than pass through: the run read the file, tried one Edit, was
    refused, and reported "the tool call was denied" — an executor granted Write
    and Edit in Settings that silently could not write.

    The mode now follows the envelope, because the envelope IS the approval:

      no write tools  dontAsk        nothing to approve; anything sneaky is denied
      Write/Edit      acceptEdits    exactly what was granted, without prompting
      Bash            bypassPermissions

    `bypassPermissions` is not a widening here and is never reached by default:
    it applies only when someone ticked Bash, and the run is still confined to
    `--tools` and `--add-dir`. Its alternative is a run that hangs forever on a
    prompt with no human attached, which is a worse failure and not a safer one.
    """
    if any(t in env.tools for t in ("Bash",)):
        return "bypassPermissions"
    if any(t in env.tools for t in ("Write", "Edit")):
        return "acceptEdits"
    return "dontAsk"


def build_command(task: str, env: Envelope) -> list[str]:
    """The exact argv for a delegated run.

    `--print` with `--output-format stream-json` is what turns the CLI into
    something a program can drive; the CLI additionally requires `--verbose` for
    that pairing. Everything else here is the envelope, expressed in flags:
    `--add-dir` bounds the filesystem, `--tools` bounds the capability set,
    `--max-budget-usd` bounds the spend, and `--permission-mode dontAsk` keeps a
    headless run from blocking forever on a prompt nobody can answer — the run is
    already limited to what we allowed, so there is nothing left to ask about.
    """
    exe = claude_exe() or "claude"
    cmd = [exe, "--print", task,
           "--output-format", "stream-json", "--verbose",
           "--add-dir", env.workspace,
           *(("--add-dir", source_root()) if env.allow_source else ()),
           "--tools", ",".join(env.tools) if env.tools else "",
           "--permission-mode", permission_mode(env),
           "--max-budget-usd", f"{env.budget_usd:.2f}"]
    if env.allow_source and env.context:
        env = Envelope(**{**env.__dict__, "context": env.context + source_note(source_root())})
    if env.context:
        # The executor's equivalent of the local agent's extra_system: what the
        # person is looking at while they type. A delegated copilot turn without
        # it is a stranger being asked to "fix this" with no idea what "this" is.
        cmd += ["--append-system-prompt", env.context]
    if env.model:
        cmd += ["--model", env.model]
    if env.session_id:
        cmd += ["--resume", env.session_id]
    return cmd


# Credentials that make the Claude Code CLI bill per token against an API
# account. When one of these is present the CLI prefers it over the subscription
# you signed in with — so a key sitting in a shell profile, put there years ago
# for something else, silently turns every delegated run into a metered API call.
# The whole point of delegating to the CLI is that it runs on the plan the user
# already pays for, so the child never sees them.
API_BILLING_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                    "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK",
                    "CLAUDE_CODE_USE_VERTEX")


def child_env() -> dict:
    """The environment a delegated run gets: this one, minus the API credentials."""
    env = {k: v for k, v in os.environ.items() if k not in API_BILLING_VARS}
    env["CLAUDE_CODE_ENTRYPOINT"] = "agentos"
    # The CLI shells out to its own helpers (node, ripgrep, git). Under systemd
    # this process's PATH lacks ~/.local/bin, so hand the child the same extended
    # PATH we used to find the CLI itself — resolving the executable and then
    # starving it of its tools would be a subtler version of the same bug.
    from .mcp_client import _extended_path
    env["PATH"] = _extended_path()
    return env


def billing() -> dict:
    """How a delegated run will be paid for, read from the CLI's own login.

    Worth stating plainly in the UI: "delegate this turn" reads as free when it
    is a subscription and as nothing at all when it is a metered key, and those
    are very different things to click.
    """
    forced = [k for k in API_BILLING_VARS if os.environ.get(k)]
    try:
        with open(os.path.expanduser("~/.claude.json")) as f:
            acct = (json.load(f) or {}).get("oauthAccount") or {}
    except Exception:
        acct = {}
    org = str(acct.get("organizationType") or "")
    if acct.get("emailAddress") or acct.get("accountUuid"):
        plan = {"claude_max": "Claude Max", "claude_pro": "Claude Pro"}.get(org, org or "Claude")
        return {"mode": "subscription", "plan": plan,
                "detail": f"signed in to {plan} — delegated runs come out of that "
                          f"plan, not an API bill",
                # If a key were present the CLI would prefer it; AgentOS removes
                # them from the child, so say so rather than leaving it ambiguous.
                "stripped": forced}
    if forced:
        return {"mode": "api", "plan": "",
                "detail": "no Claude subscription is signed in, and AgentOS does not "
                          "pass API keys to it — run `claude` once and sign in",
                "stripped": forced}
    return {"mode": "none", "plan": "",
            "detail": "nobody is signed in to Claude Code — run `claude` once in a "
                      "terminal to sign in", "stripped": []}


def _why(event: dict, run: Run) -> str:
    """Say why a run ended badly, in words rather than a subtype.

    "the executor failed" is the message that taught us this was needed: the run
    had actually hit its spend ceiling, which the user set and can change, and
    reporting it as a nameless failure hid the one fact that made it fixable.
    """
    said = str(event.get("result") or "").strip()
    if said:
        return said[:500]
    subtype = str(event.get("subtype") or "")
    if "budget" in subtype:
        # On a subscription nothing was actually billed, so "spend ceiling" reads
        # as a money problem when it is really a work limit — and the work is not
        # lost: the session resumes, so say to carry on rather than start over.
        if billing().get("mode") == "subscription":
            return (f"stopped at the ${run.cost_usd:.2f} work limit for this run. "
                    f"Nothing was billed — you are on a Claude subscription, so this "
                    f"is a runaway guard, not a cost. Raise it in Settings → "
                    f"Executors, then ask it to carry on; it continues where it "
                    f"stopped rather than starting again.")
        return (f"stopped at the ${run.cost_usd:.2f} spend ceiling for this run "
                f"— raise it in Settings → Executors if the task needs more. "
                f"Asking it to carry on continues the same session.")
    if "max_turns" in subtype:
        return "stopped after using all its turns before finishing"
    return f"the executor stopped: {subtype or 'no reason given'}"


def tool_detail(name: str, args: dict) -> str:
    """What a delegated tool call is actually doing, in a few words.

    A tool NAME alone is not progress. "Bash" for four minutes and "Bash" for
    four seconds look identical, and a build that reads `Read · Write · Bash ·
    Bash · Bash` tells the watcher nothing about whether it is working or stuck.
    The argument that identifies the call — the file, the command, the URL — is
    already in the event; this is only about surfacing it.
    """
    args = args if isinstance(args, dict) else {}

    def s(*keys) -> str:
        for k in keys:
            v = args.get(k)
            if isinstance(v, str) and v.strip():
                return " ".join(v.split())
        return ""

    if name in ("Read", "Write", "Edit", "NotebookEdit"):
        p = s("file_path", "path", "notebook_path")
        return Path(p).name if p else ""
    if name == "Bash":
        cmd = s("description") or s("command")
        return cmd[:90] + ("…" if len(cmd) > 90 else "")
    if name in ("Glob", "Grep"):
        pat = s("pattern", "query")
        where = s("path", "glob")
        return f"{pat}{' in ' + Path(where).name if where else ''}"[:90]
    if name in ("WebFetch", "WebSearch"):
        return s("url", "query", "prompt")[:90]
    if name == "Task":
        return s("description", "prompt")[:90]
    if name == "TodoWrite":
        todos = args.get("todos")
        if isinstance(todos, list) and todos:
            active = [t for t in todos if isinstance(t, dict)
                      and t.get("status") == "in_progress"]
            done = sum(1 for t in todos if isinstance(t, dict) and t.get("status") == "completed")
            head = str((active[0] if active else todos[0]).get("content") or "")
            return f"{head[:70]} ({done}/{len(todos)} done)"
        return ""
    # An unknown tool still has SOMETHING identifying in its arguments; showing
    # the first short string beats showing nothing.
    for v in args.values():
        if isinstance(v, str) and 0 < len(v.strip()) <= 90:
            return " ".join(v.split())
    return ""


def translate(event: dict, run: Run) -> list[dict]:
    """Turn one Claude Code stream event into AgentOS turn events.

    This is the whole reason a delegated run doesn't need its own UI: the shapes
    below are exactly what `agent.py` emits, so the chat window, the omnibar cards
    and the copilot panels render it without knowing an executor was involved.
    """
    kind = event.get("type")
    out: list[dict] = []

    if kind == "system" and event.get("subtype") == "init":
        run.session_id = event.get("session_id") or ""
        run.model = event.get("model") or ""
        # Structured, not prose: the UI labels the reply with who actually
        # answered and on what model. Writing it into the transcript as an italic
        # line made it body text the executor appeared to have said, and left the
        # bubble still claiming the built-in agent wrote it.
        out.append({"type": "engine_info", "engine": "claude-code",
                    "model": run.model,
                    "version": event.get("claude_code_version", ""),
                    "tools": event.get("tools") or []})

    elif kind == "assistant":
        for block in (event.get("message") or {}).get("content", []):
            if block.get("type") == "text" and block.get("text"):
                out.append({"type": "text_delta", "text": block["text"]})
            elif block.get("type") == "thinking" and block.get("thinking"):
                out.append({"type": "thinking_delta", "text": block["thinking"]})
            elif block.get("type") == "tool_use":
                name = block.get("name", "tool")
                args = block.get("input") or {}
                detail = tool_detail(name, args)
                run.steps += 1
                run.last = f"{name}{' · ' + detail if detail else ''}"
                run.calls[block.get("id", "")] = (name, detail)
                out.append({"type": "tool_start", "call_id": block.get("id", ""),
                            "name": name, "args": args, "detail": detail,
                            "step": run.steps, "pending_approval": False})

    elif kind == "user":
        # The CLI reports tool results as a user turn carrying tool_result blocks.
        for block in (event.get("message") or {}).get("content", []):
            if block.get("type") == "tool_result":
                content = block.get("content")
                if isinstance(content, list):
                    content = "".join(c.get("text", "") for c in content
                                      if isinstance(c, dict))
                # The result carries only the id, so the name is recovered from
                # the call that opened it — an anonymous "✗ — failed" is the one
                # error a watcher cannot act on.
                name, detail = run.calls.pop(block.get("tool_use_id", ""), ("", ""))
                out.append({"type": "tool_end", "call_id": block.get("tool_use_id", ""),
                            "name": name, "detail": detail,
                            "output": str(content or "")[:4000],
                            "ok": not block.get("is_error")})

    elif kind == "result":
        run.cost_usd = float(event.get("total_cost_usd") or 0.0)
        run.turns = int(event.get("num_turns") or 0)
        run.denials = list(event.get("permission_denials") or [])
        if run.denials:
            # Say what the envelope refused, by name. A run that quietly did less
            # than asked because a tool was withheld is the one failure mode the
            # user cannot diagnose from the transcript alone.
            names = sorted({str(d.get("tool_name") or d) for d in run.denials})
            out.append({"type": "text_delta",
                        "text": f"\n\n_Blocked by the task's permissions: {', '.join(names)}. "
                                f"Widen them in Settings → Executors if that was wrong._"})
        if event.get("is_error") or event.get("subtype") != "success":
            out.append({"type": "error", "message": _why(event, run)})
            run.reported_error = True

    elif kind == "rate_limit_event":
        info = event.get("rate_limit_info") or {}
        if info.get("status") not in (None, "allowed"):
            out.append({"type": "status", "text": "Claude Code is rate limited — waiting…"})

    return out


# How big one line of the CLI's stream may be.
#
# `stream-json` puts one whole event on one line, and an event carries whole tool
# payloads: the app file it just wrote, the 44KB file it read back to check its
# own work. asyncio's StreamReader defaults to a 64KiB line limit, and crossing
# it does not truncate — `readline()` raises
#
#     ValueError: Separator is found, but chunk is longer than limit
#
# which killed the build *after* the executor had written a finished app to disk.
# The size that made this happen is the size of a normal app, so the ceiling has
# to be in app territory, not in log-line territory. It is a cap on one line, not
# an allocation: the buffer only ever grows to what the CLI actually wrote.
STREAM_LINE_LIMIT = 32 * 1024 * 1024


async def run_task(task: str, env: Envelope, emit, run: Run | None = None) -> Run:
    """Delegate a task and stream it back through `emit`.

    `emit` is an async callable taking one event dict — in the server it is the
    same broadcast the local agent uses, which is what makes the two kinds of turn
    indistinguishable to the UI.
    """
    env = env.sanitized()
    run = run or Run()
    Path(env.workspace).mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        *build_command(task, env),
        cwd=env.workspace,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=child_env(),
        limit=STREAM_LINE_LIMIT,
    )
    run.proc = proc

    assert proc.stdout is not None
    while True:
        try:
            line = await proc.stdout.readline()
        except ValueError:
            # Past even that ceiling. `readline()` has already dropped the
            # oversized line and left the stream usable, so lose the one event
            # rather than the whole run — the work continues on the other side
            # whatever we do here, and the file on disk is the deliverable.
            run.dropped += 1
            await emit({"type": "error",
                        "message": "one progress update was too large to read and was "
                                   "skipped — the build is still running"})
            continue
        if not line:
            break
        text = line.decode(errors="replace").strip()
        if not text:
            continue
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            continue          # the CLI also prints non-JSON chatter; it isn't ours
        for out in translate(event, run):
            await emit(out)

    await proc.wait()
    # A run that ended badly already said why on its result event; the non-zero
    # exit is the same failure seen from outside, and reporting it again reads as
    # two separate problems.
    if proc.returncode not in (0, None) and not run.stopped and not run.reported_error:
        err = (await proc.stderr.read()).decode(errors="replace").strip() if proc.stderr else ""
        await emit({"type": "error",
                    "message": err[:500] or f"the executor exited with {proc.returncode}"})
    return run


def stop(run: Run) -> bool:
    """Stop a delegated run. Same promise as Ctrl+. on a local turn."""
    run.stopped = True
    if run.proc and run.proc.returncode is None:
        try:
            run.proc.terminate()
            return True
        except ProcessLookupError:
            return False
    return False
