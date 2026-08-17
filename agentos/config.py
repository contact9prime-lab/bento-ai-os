"""Configuration: loaded from ~/.agentos/config.json, env vars fill in API keys."""

import copy
import json
import os
from pathlib import Path

AGENTOS_HOME = Path(os.environ.get("AGENTOS_HOME", Path.home() / ".agentos"))
CONFIG_PATH = AGENTOS_HOME / "config.json"
DB_PATH = AGENTOS_HOME / "agentos.db"
SOUL_PATH = AGENTOS_HOME / "soul.md"

# Which agents may answer. Named here rather than imported from executors.py,
# because that module imports this one and the reverse would be a cycle; a test
# asserts the two lists stay equal, which is the only thing that could drift.
ENGINE_NAMES = ("aria", "claude-code", "hermes", "openclaw")

DEFAULT_SOUL = """# Soul of this AgentOS

I am the resident intelligence of this machine. I act, I remember, I learn.

## Personality
- Direct, warm, and practical. No filler.
- I do things instead of describing how they could be done.

## Values
- The user's time is precious; their data is theirs; their machine is their castle.
- I ask before doing anything destructive or hard to reverse.

## How I grow
- I keep durable facts in memory, and the *structure* of what I know in my knowledge graph.
- I refine this soul file as I learn who my user is and what they need.
"""


def soul_path() -> Path:
    """Whose soul. On a single-user machine this is the one file it has always
    been; with users, it is theirs — an agent's identity is the most personal
    thing in the OS and sharing one would be the strangest possible default."""
    from . import users as usersmod
    uid = usersmod.current() if usersmod.enabled() else ""
    return usersmod.soul_path_for(uid) if uid else SOUL_PATH


def load_soul() -> str:
    p = soul_path()
    if p.exists():
        try:
            return p.read_text()
        except Exception:
            return DEFAULT_SOUL
    return DEFAULT_SOUL


def save_soul(text: str) -> None:
    p = soul_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)

DEFAULTS = {
    # Explicit, and in DEFAULTS on purpose. `is_first_run()` reads the RAW file, so
    # anything that calls save_config() before the wizard finishes used to write a
    # config with no key at all — which the grandfather clause below reads as "an
    # old install, already set up", and the machine silently never sees onboarding
    # again. Seeding False means the first save says so out loud. Configs written
    # before this key existed are untouched and still grandfathered.
    "setup_complete": False,
    "providers": {
        "ollama": {
            "enabled": True,
            "base_url": "http://localhost:11434",
        },
        "anthropic": {
            "enabled": False,
            "base_url": "https://api.anthropic.com",
            "api_key": "",
            "models": ["claude-sonnet-5", "claude-opus-4-8", "claude-haiku-4-5-20251001"],
        },
        "openai": {
            "enabled": False,
            "base_url": "https://api.openai.com/v1",
            "api_key": "",
            "models": ["gpt-4o", "gpt-4o-mini"],
        },
        "openrouter": {  # one key, hundreds of models (OpenAI-compatible)
            "enabled": False,
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "",
            "models": ["anthropic/claude-sonnet-4.5", "openai/gpt-4o",
                       "google/gemini-2.5-flash", "meta-llama/llama-3.3-70b-instruct"],
        },
        "custom": {  # any OpenAI-compatible endpoint (LM Studio, vLLM, Groq, ...)
            "enabled": False,
            "base_url": "",
            "api_key": "",
            "models": [],
        },
        "google": {  # Gemini — chat + image generation (nano banana); key from aistudio.google.com
            "enabled": False,
            "base_url": "https://generativelanguage.googleapis.com",
            "api_key": "",
            "models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
        },
        # DeepSeek and Moonshot (Kimi) are their own front doors rather than
        # OpenRouter entries, because the reason to reach for either is usually price
        # — routing the call through a broker gives that back. Both serve the plain
        # OpenAI dialect, so `chat()` needs no new transport: the base URL and the key
        # are the whole integration, which is exactly why leaving them out was a gap
        # rather than a decision.
        "deepseek": {
            "enabled": False,
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "",
            "models": ["deepseek-chat", "deepseek-reasoner"],
        },
        "moonshot": {  # Kimi. `kimi-k2` reasons and calls tools; the k1.5 line is older
            "enabled": False,
            "base_url": "https://api.moonshot.ai/v1",
            "api_key": "",
            "models": ["kimi-k2-0711-preview", "moonshot-v1-128k", "moonshot-v1-32k"],
        },
    },
    # image generation: provider auto|google|openai|pollinations; model optional
    # (defaults: google → gemini-2.5-flash-image "nano banana", openai → gpt-image-1).
    # auto picks google, then openai (whichever has a key), else free pollinations.ai.
    "image": {"provider": "auto", "model": ""},
    # Where and when the user is. Blank fields are auto-detected from the machine
    # (/etc/timezone, LANG); the wizard confirms them and Settings edits them. This
    # is what makes "news today" mean the right country and "tonight" the right hour.
    "locale": {"language": "", "country": "", "timezone": "", "city": "",
               "units": "", "clock": ""},
    # Which model builds apps in App Studio. "" = use default_model. The builder
    # never substitutes a model on its own; this is the user's call.
    "build": {"model": ""},
    # Keyboard/pointer preferences and per-output display layout, both written
    # into compositor drop-ins so they survive a logout like any desktop's.
    "input": {"keyboard": {"layout": "", "variant": "", "options": "",
                           "repeat_delay": 300, "repeat_rate": 30},
              "touchpad": {"tap": True, "natural_scroll": True, "dwt": True, "accel": 0.0}},
    "displays": {},
    # Executors: other agents already installed on this machine that AgentOS can
    # hand a task to. The envelope is the whole safety story — this build of the
    # Claude Code CLI has no per-call permission hook, so what a run may touch is
    # decided here, once, rather than approved call by call. Off until asked for,
    # and read-only when first switched on.
    # budget_usd is 0 = "decide it from how the CLI is billed" (executors.py).
    # A hardcoded 2.0 here meant a Claude subscription — where nothing is billed
    # per token — still cut work off at a notional $2, which stopped real builds
    # half-finished while controlling no spending at all.
    "executors": {"claude_code": {"enabled": False, "workspace": "", "model": "",
                                  "tools": ["Read", "Glob", "Grep", "WebSearch"],
                                  "budget_usd": 0}},
    # Which agent answers. "aria" is the built-in one; anything else turns this
    # machine into a forwarder — every turn a person starts goes to that agent
    # instead, on every surface (chat, omnibar, copilot, Telegram, API, tasks).
    # Which trade this machine makes between speed and footprint. "auto" decides
    # from the hardware on first run and then writes down what it decided —
    # `agentos/profile.py` is the whole rule, and what it changes lands in the
    # ordinary keys below rather than in an invisible overlay.
    "profile": "auto",
    # How long telemetry is kept. Not the ledger and not the user's own work —
    # `memory.Store.prune` says exactly what it will and will not touch. 0 for any
    # window means "keep it forever", because a machine somebody is debugging must
    # be able to switch this off without editing code.
    "retention": {"enabled": True, "logs_days": 30, "events_days": 30,
                  "usage_days": 365},
    "engine": "aria",
    "agent_name": "Aria",         # what the agent calls itself; change it in Settings
    "default_model": "",          # e.g. "ollama/qwen3.5:9b" — picked automatically if empty
    "autonomy": "balanced",       # paranoid | balanced | full
    # Autonomy answers "how much may the agent do without asking". This answers a
    # different question: "how much may a WEB PAGE do", once its text is in the
    # context window. A turn that has read untrusted content (a fetched page, an
    # MCP server's reply) holds its risky steps for a human — at full autonomy too,
    # because full autonomy is trust placed in the user's own instructions.
    #   off | ask (default) | strict (refuse outright)
    "security": {"taint": "ask"},
    "max_steps": 25,
    # Typing again while a turn is running queues the message. With this on, the agent
    # decides at each step boundary whether that message belongs to the run in flight
    # (fold it in) or is a separate ask (leave it queued for the next turn). Off = every
    # queued message simply waits its turn. That decision runs in parallel with the reply
    # already streaming, on memory.model if one is set, and steer_triage_timeout bounds
    # it — past that the message's wording decides, and waiting is the safe default.
    "steer_queued_messages": True,
    "steer_triage_timeout": 30,
    "workspace": str(Path.home() / "AgentOS"),
    "port": 8321,
    # How AgentOS presents itself on this machine. "auto" reads the environment
    # the session was started in and is almost always right:
    #   hosted — a window on your existing desktop (GNOME/KDE/macOS/Windows)
    #   de     — AgentOS *is* the session (our Wayland compositor and settings)
    #   kiosk  — the older fullscreen X11 session
    # Pin one to force it for testing; on macOS/Windows it always resolves to
    # hosted. Installing the AgentOS session never changes this on its own —
    # you switch by picking a session at the login screen. See agentos/runmode.py.
    # idle_*: DE-session timers (seconds; 0 disables) — lock the screen, then
    # power the outputs off. Re-run `agentos install-session` after changing.
    "desktop": {"mode": "auto", "idle_lock_secs": 600, "idle_screen_off_secs": 900},
    # MCP servers the agent can use. Each entry:
    #   {"transport": "stdio", "command": "npx", "args": "-y @modelcontextprotocol/server-filesystem /tmp",
    #    "env": {"SOME_API_KEY": "..."}, "enabled": true}
    #   {"transport": "http", "url": "https://api.githubcopilot.com/mcp/",
    #    "headers": {"Authorization": "Bearer <token>"}, "enabled": true}
    # Auth: stdio servers take API keys via "env"; http servers via "headers".
    # OAuth-based remote servers (Linear, Sentry, Atlassian, Vercel, ...) work as stdio
    # through the mcp-remote bridge: command "npx", args "-y mcp-remote <server-url>" —
    # the first connection opens a browser tab to sign in.
    "mcp_servers": {},
    # desktop widgets: pinned user-apps that live on the desktop and restore on startup
    # [{"app_id": "...", "x": 40, "y": 40, "w": 300, "h": 200}]
    "widgets": [],
    # folder jail: agent commands, file tools, and the Terminal are confined to
    # `root` (defaults to the workspace) via bubblewrap — everything else is
    # read-only and other files in /home are hidden entirely.
    # `folders` are the other places the agent may read and write, named by the
    # user. Seeded empty and explicit, so the key exists to be discovered in the
    # file rather than only in the settings page.
    "sandbox": {"enabled": True, "root": "", "folders": []},
    # GitHub integration (Ship pillar): a fine-grained PAT used by the git_* tools
    # to create repos and push over HTTPS. The token stays in config + env — it is
    # never placed in command lines, remotes, or tool output.
    "github": {"token": "", "username": ""},
    # TrainForge (Train pillar): path is auto-detected; if it's not on disk, Start
    # clones `repo` into `install_dir` and provisions it via run.sh. Set `repo` to
    # the doneitrightai git URL to enable auto-fetch.
    "trainforge": {"path": "", "port": 8377, "repo": "", "install_dir": ""},
    # generation budgets: Ollama context window and output-token caps (chat / builds).
    # ollama_think: null = model default; false = disable the thinking channel
    # (App Studio builds always disable it regardless).
    "ollama_num_ctx": 24576,
    "ollama_think": None,
    "max_output_tokens": 16384,
    "build_max_output_tokens": 32768,
    "build_timeout": 600,
    "first_token_timeout": 180,
    # user rules: [{"action": "allow"|"deny", "match": "run_command git *"}]
    # matched (fnmatch, * wildcards) against "<tool> <command-or-args>"; deny wins.
    "policies": [],
    # memory system: auto_extract mines each chat turn for user memories, session
    # memories, and knowledge-graph facts using `model` (default_model if empty).
    "memory": {
        "auto_extract": True,
        "model": "",              # a small/fast model works well here, e.g. "ollama/qwen3:4b"
        "inject_user": 15,        # how many user memories go into the system prompt
        "inject_session": 10,     # how many session memories go into the system prompt
        "inject_facts": 12,       # how many knowledge-graph facts go into the system prompt
        "embed_model": "",        # Ollama embedding model for semantic recall; empty = auto-detect
        "rollup_after_hours": 24, # distill idle conversations' session memory; 0 disables
        "kg_dedup": True,         # periodically merge duplicate knowledge-graph entities
    },
    # How many of the 90 tools are put in front of the model at once
    # (agentos/toolscope.py). Default "all": narrowing was measured with
    # `agentos eval` and scored slightly WORSE on this machine's local model, so
    # it ships off. "auto" narrows only when the schemas would eat a real share
    # of the context window — try it with the eval harness on your own model.
    "tools": {
        "scope": "all",           # all | auto | always
        "budget": 30,             # tools offered per step when narrowing
        "window_share": 0.20,     # narrow once schemas exceed this share of the window
        "cloud_context": 128000,  # assumed window when the provider does not say
    },
    # How a conversation is replayed to the model each turn (agentos/history.py).
    # A thread that outgrows the context window is compacted, not killed.
    "history": {
        "tool_trace": True,       # replay prior turns' tool calls + results, compactly
        "trace_chars": 600,       # how much of each past tool result is kept
        "compact": True,          # summarise turns that fall out of the budget
        "budget_tokens": 0,       # 0 = derive from the model (num_ctx for local models)
        "model": "",              # summariser; empty = the conversation's own model
    },
    "telegram": {
        "enabled": False,
        "bot_token": "",       # from @BotFather
        "owner_chat_id": 0,    # paired automatically on the first /start message
    },
    # Channels: every way a conversation reaches this machine — this window, the
    # session, a terminal, a remote browser, the API, the schedule, Telegram.
    # Keyed by channel id (see agentos/channels.py); each may carry a `posture`,
    # which is the trust ceiling for the IO gate it arrives on. Empty means every
    # channel simply inherits the machine's autonomy, which is the old behaviour.
    "channels": {},
    # Remote access: reach this desktop from your phone or another machine.
    #
    # OFF, and it stays off until a human turns it on in Settings → Remote access
    # and sets a passphrase. Nothing here can be enabled by the agent, by an app,
    # or by a config push: the API refuses to bind off-loopback without a
    # passphrase, because AgentOS gives whoever is looking at it a real shell.
    #
    #   enabled       — serve to more than loopback
    #   passphrase    — never stored; only this PBKDF2 hash + salt are
    #   bind          — the interface to listen on once enabled (0.0.0.0 = every one)
    #   session_days  — how long a signed-in device stays signed in
    #   trust_loopback— requests from this machine skip the login (the socket
    #                   proves they are local; a LAN client cannot forge it)
    "remote": {
        "enabled": False,
        "bind": "0.0.0.0",
        "pass_hash": "",
        "pass_salt": "",
        "session_days": 30,
        "trust_loopback": True,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg = _deep_merge(cfg, json.loads(CONFIG_PATH.read_text()))
        except Exception:
            pass
    # env vars fill empty keys, never overwrite explicit config
    if not cfg["providers"]["anthropic"]["api_key"]:
        cfg["providers"]["anthropic"]["api_key"] = os.environ.get("ANTHROPIC_API_KEY", "")
    if not cfg["providers"]["openai"]["api_key"]:
        cfg["providers"]["openai"]["api_key"] = os.environ.get("OPENAI_API_KEY", "")
    if not cfg["providers"]["openrouter"]["api_key"]:
        cfg["providers"]["openrouter"]["api_key"] = os.environ.get("OPENROUTER_API_KEY", "")
    if not cfg["providers"]["google"]["api_key"]:
        cfg["providers"]["google"]["api_key"] = (os.environ.get("GOOGLE_API_KEY", "")
                                                 or os.environ.get("GEMINI_API_KEY", ""))
    if not cfg["providers"]["deepseek"]["api_key"]:
        cfg["providers"]["deepseek"]["api_key"] = os.environ.get("DEEPSEEK_API_KEY", "")
    if not cfg["providers"]["moonshot"]["api_key"]:
        cfg["providers"]["moonshot"]["api_key"] = (os.environ.get("MOONSHOT_API_KEY", "")
                                                   or os.environ.get("KIMI_API_KEY", ""))
    for name in ("anthropic", "openai", "openrouter", "google", "deepseek", "moonshot"):
        if cfg["providers"][name]["api_key"]:
            cfg["providers"][name]["enabled"] = True
    # backfill Gemini chat models for installs whose saved config predates them
    if not cfg["providers"]["google"].get("models"):
        cfg["providers"]["google"]["models"] = list(DEFAULTS["providers"]["google"]["models"])
    # Removed features leave their settings behind in every saved config. A key for
    # something that no longer exists is worse than clutter — it reads as a feature
    # that is merely switched off. `engine` is repaired rather than dropped, because
    # a machine pinned to a removed engine must still answer with something.
    # The old Hermes CARRIER block (repo, engine_enabled, gateway targets) is still
    # dead and still dropped: that shape was the removed gateway, and a key for a
    # feature that no longer exists reads as one merely switched off. Hermes as an
    # EXECUTOR is a different thing with a different contract — it answers this
    # OS's turns, through this PDP, into this ledger — so the engine NAME is no
    # longer rewritten here. `executors.resolve_engine` refuses an engine that is
    # not installed at read time, which covers this case and the several the
    # migration never could: uninstalled later, edited by hand, restored onto a
    # machine that never had it.
    cfg.pop("hermes", None)
    if cfg.get("engine") not in ("", None) and cfg.get("engine") not in ENGINE_NAMES:
        cfg["engine"] = "aria"
    return cfg


def save_config(cfg: dict) -> None:
    """Write the config — to the right file, for whoever is asking.

    There are ~26 call sites and none of them know about users, which is the
    point: the routing lives here rather than in each of them. A user's save
    writes their own keys to their own file and stops. An admin's also writes the
    machine's half, stripped of the personal keys — because everything in the
    machine file becomes the starting point for the next person created.
    """
    from . import users as usersmod
    uid = usersmod.current() if usersmod.enabled() else ""
    if uid:
        usersmod.save_user_cfg(uid, cfg)
        if not usersmod.is_admin(uid):
            return
        cfg = usersmod.machine_view(cfg)
        usersmod.machine_changed(cfg)
    AGENTOS_HOME.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def is_first_run() -> bool:
    """True when the setup wizard should run: no config yet, or a factory reset
    explicitly set setup_complete=false. Pre-wizard installs (config exists without
    the key) are grandfathered as already set up.

    Per user once there are users: the arc is name-your-agent, say hello, build
    one, choose a look. All of that is personal, so a new account gets walked
    through it rather than dropped into somebody else's finished desktop.
    """
    from . import users as usersmod
    uid = usersmod.current() if usersmod.enabled() else ""
    if uid:
        return usersmod.cfg_for(uid).get("setup_complete") is not True
    if not CONFIG_PATH.exists():
        return True
    try:
        raw = json.loads(CONFIG_PATH.read_text())
    except Exception:
        return True
    return raw.get("setup_complete") is False


def mark_setup_complete(cfg: dict) -> None:
    cfg["setup_complete"] = True
    save_config(cfg)


def ensure_dirs(cfg: dict) -> None:
    AGENTOS_HOME.mkdir(parents=True, exist_ok=True)
    Path(cfg["workspace"]).expanduser().mkdir(parents=True, exist_ok=True)
