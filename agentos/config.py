"""Configuration: loaded from ~/.agentos/config.json, env vars fill in API keys."""

import copy
import json
import os
from pathlib import Path

AGENTOS_HOME = Path(os.environ.get("AGENTOS_HOME", Path.home() / ".agentos"))
CONFIG_PATH = AGENTOS_HOME / "config.json"
DB_PATH = AGENTOS_HOME / "agentos.db"
SOUL_PATH = AGENTOS_HOME / "soul.md"

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


def load_soul() -> str:
    if SOUL_PATH.exists():
        try:
            return SOUL_PATH.read_text()
        except Exception:
            return DEFAULT_SOUL
    return DEFAULT_SOUL


def save_soul(text: str) -> None:
    AGENTOS_HOME.mkdir(parents=True, exist_ok=True)
    SOUL_PATH.write_text(text)

DEFAULTS = {
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
        "google": {  # Gemini — used for image generation (nano banana); key from aistudio.google.com
            "enabled": False,
            "base_url": "https://generativelanguage.googleapis.com",
            "api_key": "",
            "models": [],
        },
    },
    # image generation: provider auto|google|openai|pollinations; model optional
    # (defaults: google → gemini-2.5-flash-image "nano banana", openai → gpt-image-1).
    # auto picks google, then openai (whichever has a key), else free pollinations.ai.
    "image": {"provider": "auto", "model": ""},
    "agent_name": "Aria",         # what the agent calls itself; change it in Settings
    "default_model": "",          # e.g. "ollama/qwen3.5:9b" — picked automatically if empty
    "autonomy": "balanced",       # paranoid | balanced | full
    "max_steps": 25,
    "workspace": str(Path.home() / "AgentOS"),
    "port": 8321,
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
    "sandbox": {"enabled": True, "root": ""},
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
    "telegram": {
        "enabled": False,
        "bot_token": "",       # from @BotFather
        "owner_chat_id": 0,    # paired automatically on the first /start message
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
    for name in ("anthropic", "openai", "openrouter", "google"):
        if cfg["providers"][name]["api_key"]:
            cfg["providers"][name]["enabled"] = True
    return cfg


def save_config(cfg: dict) -> None:
    AGENTOS_HOME.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def is_first_run() -> bool:
    """True when the setup wizard should run: no config yet, or a factory reset
    explicitly set setup_complete=false. Pre-wizard installs (config exists without
    the key) are grandfathered as already set up."""
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
