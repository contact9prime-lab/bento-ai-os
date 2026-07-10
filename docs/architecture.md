# Architecture

AgentOS is a Python backend that serves a single-file desktop environment to the browser, plus a set
of modules that give the agent its capabilities. There is no build step for the UI.

---

## Modules

```
agentos/
├── __main__.py    Command-line entry: serve · app · install · uninstall · autostart · ask
├── agent.py       The kernel: the think → act (tools) → observe loop, approval gates, and personas
├── providers.py   Unified streaming chat across Ollama / Anthropic / OpenAI / OpenRouter / custom
├── tools.py       The agent's tools: shell, files, web, reports, memory, knowledge graph, soul,
│                  skills, apps, widgets, wallpaper, models, native apps, system control,
│                  MCP dispatch, self-modification, and the sandbox jail
├── mcp_client.py  Model Context Protocol client (connects to stdio and HTTP tool servers)
├── telegram.py    Telegram bridge: chat registry, inline approval keyboard, headless turns
├── host.py        Host desktop integration: launch native apps, volume/battery/network, settings
├── memory.py      SQLite storage: conversations, messages, memory, tasks, logs, knowledge graph,
│                  skills, apps, app data, telegram chats
├── scheduler.py   Background job runner
├── config.py      Configuration loading/saving and the soul file
├── desktop.py     Native app window + installer (menu launcher, systemd service, login autostart)
├── server.py      HTTP + WebSocket server: the desktop UI, REST API, streams, file serving,
│                  host-open, app store, model management
└── ui/
    ├── index.html The entire desktop environment — a single self-contained file
    └── assets/    Vendored terminal (xterm.js)
```

---

## Request flow

**A chat turn**
1. The UI sends a `chat` message over `/ws`.
2. `server.py` builds an `Agent` (`agent.py`) with the chosen model and an approval callback.
3. The agent assembles its system prompt (identity/soul, memory, skills, sandbox notes) and streams a
   completion from `providers.py`.
4. When the model calls a tool, `tools.py` classifies its risk. Safe tools run immediately; risky
   ones pause for approval (via the UI, or Telegram's inline buttons); blocked ones are refused.
5. Tool output goes back to the model; the loop continues until the task is done or the step limit is
   reached.
6. Every event streams live to the UI; the final result and tool trace are stored in `memory.py`.

**Building an app**
1. A `build` message runs a specialized builder persona with a focused tool set.
2. The agent produces the app via `create_app`; it's stored and served at `/api/apps/{id}/page` with
   a runtime injected (its data store and OS-tool bridge).
3. The desktop refreshes; the app gets an icon and can be pinned as a widget.

---

## Design principles

- **Local-first & private.** Binds to `127.0.0.1`; with a local model, nothing leaves the machine.
- **Everything is a tool.** The agent's abilities — and anything you connect via MCP — are uniform
  tools with a risk level, so safety and extensibility are consistent.
- **Degrade gracefully.** Optional host tools (sandbox, native launch, system control, screenshots)
  are detected at runtime; missing ones simply disable that feature rather than erroring.
- **No UI build step.** The desktop is one HTML file that talks to the API — easy to read, host, and
  extend, and it can even be modified by the agent itself.

---

## Packaging

`packaging/build-deb.sh` produces a self-contained `.deb` that bundles a Python environment with all
dependencies plus the menu launcher and systemd service. `desktop.py` handles installation into a
user's session (menu entry, boot service with linger, login autostart). See
[Installation](installation.md).
