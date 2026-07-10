# Getting Started

This walks you from a fresh launch to giving the agent real work.

---

## 1. Launch

```bash
uv run agentos
```

The desktop opens at **http://127.0.0.1:8321**. You'll see a wallpaper, app icons, a taskbar with a
Start menu and dock, and the **Agent Chat** window.

---

## 2. Choose a model

Open **⚙ Settings** and configure a provider:

- **Ollama (local)** — detected automatically if Ollama is running. Nothing leaves your machine.
- **Anthropic**, **OpenAI**, **OpenRouter**, or any **OpenAI-compatible** endpoint — paste a key and
  list the models you want.

Pick the active model from the dropdown at the top of the chat window at any time.

> **Important:** the agent works by calling tools. Use a **tool-capable model** — any `qwen` model
> locally, or a cloud model. Small models like `gemma` often won't call tools reliably, so tasks may
> stop early or produce nothing.

---

## 3. Set your autonomy level

Also in the chat toolbar (and Settings):

| Level | Behavior |
|---|---|
| 🛡 **Paranoid** / ⚖ **Balanced** | read-only actions run automatically; anything that changes the system asks for approval first |
| ⚡ **Full** | everything runs without prompting (destructive commands stay blocked either way) |

Start on **Balanced**. You approve risky actions with one click when they come up. See
[The Agent → Safety](agent.md#safety) for the full model.

---

## 4. Give it work

Type in **Agent Chat**, or press **Alt+Space** (or **Ctrl+Space**) anywhere to open the command
palette and either launch an app or send a request straight to the agent.

Things to try:

- *"How is this machine doing? Check CPU, memory, and disk."*
- *"What's taking up the most space in my home folder?"*
- *"Create a project folder with a starter README in my workspace."*
- *"Summarize today's top technology news and save it as a report."*
- *"Build me a pomodoro timer and pin it to the desktop."*
- *"Every morning at 9, check disk space and message me on Telegram if it's low."*
- *"Remember that I prefer concise answers."*

The agent will use its tools, show you what it's doing, ask approval where needed, and report the
real result.

---

## 5. Explore the desktop

- **Start menu / dock** — launch any built-in app.
- **Applications (🗔)** — launch any installed program on your computer.
- **App Store (🛍)** — install ready-made apps in one click, add tool channels, or build a new app
  with AI.
- **Control Center (🎛)** — sound, network, battery, and shortcuts to native settings.
- **Files (🗂)** — browse your workspace; click a file to open it in your system browser.
- **Terminal (🖥)** — a real shell on your machine.

See [The Desktop](desktop.md) for everything.

---

## 6. Make it permanent (optional)

```bash
uv run agentos install
```

Adds a menu entry, starts AgentOS at boot, and opens it automatically at login. Log out and back in
to see it come up on its own. See [Installation](installation.md).

---

## A note on results

The agent is instructed to **finish tasks** — to turn research and analysis into a concrete
deliverable (a report file, a created project, a scheduled job), not stop halfway. If a run ever
ends early, it's almost always the model: switch to a stronger/tool-capable one and retry.
