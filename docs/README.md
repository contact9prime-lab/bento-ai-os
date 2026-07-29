# AgentOS Documentation

**Your machine, with a brain.** AgentOS is a local-first *agentic operating system*: a complete
desktop environment, driven by an AI agent that takes real actions on your computer — running
commands, managing files, building its own apps, and integrating with the host desktop. It runs
locally with Ollama or connects to cloud models, and everything happens with your approval.

---

## Contents

| Guide | What's inside |
|---|---|
| [Installation](installation.md) | Requirements, running from source, the `.deb` package, boot & login autostart |
| [Getting Started](getting-started.md) | First launch, choosing a model, autonomy, your first tasks |
| [The Lifecycle](lifecycle.md) | **Train · Test · Operate · Build · Ship · Manage** — the six pillars and Mission Control |
| [The Desktop](desktop.md) | Windows, taskbar, dock, virtual desktops, widgets, themes, keyboard shortcuts, the app catalog |
| [AgentOS as your DE](desktop-environment.md) | The AgentOS **login session** — boot into AgentOS, run modes, System Settings, notifications, lock screen, licences |
| [The living desktop](experience.md) | Motion & design tokens, window management, the agent's hands, proactivity, the agent-led first run |
| [The Agent](agent.md) | How the agent works, the full tool set, autonomy levels, policies, memory, soul, skills |
| [Building Apps](building-apps.md) | App Studio, the Store, app data stores, letting apps call the OS |
| [Training Models](training.md) | The Train app (TrainForge): datasets, LoRA fine-tuning, evaluation, publishing |
| [Git & Shipping](git.md) | The git toolset, GitHub setup, exporting apps to repos |
| [The TUI](tui.md) | AgentOS in a terminal — over SSH or without a browser |
| [Remote access](remote-access.md) | Reach the desktop from your phone — the opt-in switch, the lock, and what it is not |
| [Security](security.md) | Threat model, trust boundaries, `agentos doctor`, incident recovery |
| [Hermes](hermes.md) | The Hermes companion agent — use it as a chat engine, download & configure it in AgentOS |
| [Integrations](integrations.md) | Telegram, MCP tool servers, native desktop apps, system control, files & reports |
| [Models & Appearance](models.md) | Providers, the Ollama Model Manager, wallpapers & themes |
| [Configuration](configuration.md) | `config.json`, the sandbox, Settings, environment variables |
| [API Reference](api-reference.md) | REST endpoints, WebSocket streams, and the agent tool catalog |
| [Architecture](architecture.md) | How it's built — modules, data, request flow |
| [Roadmap](roadmap.md) | Product vision, differentiation vs chat-first assistants, feature pillars |
| [Design: Subagents](design/subagents.md) | The execution fabric — subagents, task envelopes, mTLS enrollment, docker/remote workers |
| [Troubleshooting](troubleshooting.md) | Common issues and fixes |

---

## In one minute

```bash
uv sync            # install
uv run agentos     # launch the desktop at http://127.0.0.1:8321
```

Then open **Settings**, pick a model, and start giving instructions in **Agent Chat** — or press
**Alt+Space** anywhere to launch an app or ask the agent directly.

> **Model note:** the agent uses tools to do real work. Choose a tool-capable model — any `qwen`
> model locally, or a cloud model. Some small local models won't reliably call tools.

---

## What makes it different

- **It acts.** The agent runs shell commands, edits files, browses, schedules jobs, and reports back
  with real output — not just chat.
- **It's a real desktop.** Draggable windows, a taskbar and dock, virtual desktops, pinnable live
  widgets, themes, and a command palette.
- **It builds itself.** Describe a tool and the agent builds a working app for it on the spot; apps
  get their own data store and can call the OS.
- **It integrates with your machine.** Launch any installed application, control sound and settings,
  browse and open your files, and reach the agent from Telegram.
- **It's yours and private.** Runs on `127.0.0.1`; with a local model, nothing leaves the machine.
  Risky actions ask for approval, destructive ones are blocked, and you can snapshot and roll back.
