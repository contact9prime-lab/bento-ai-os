# AgentOS Documentation

<p align="right"><sub>
The overview is translated by AI (not yet proofread — the English README is the reference) —
<a href="i18n/README.zh-CN.md">简体中文</a> ·
<a href="i18n/README.zh-TW.md">繁體中文</a> ·
<a href="i18n/README.ja.md">日本語</a> ·
<a href="i18n/README.ko.md">한국어</a> ·
<a href="i18n/README.es.md">Español</a> ·
<a href="i18n/README.pt-BR.md">Português&nbsp;(BR)</a> ·
<a href="i18n/README.fr.md">Français</a> ·
<a href="i18n/README.de.md">Deutsch</a> ·
<a href="i18n/README.ru.md">Русский</a> ·
<a href="i18n/README.hi.md">हिन्दी</a> ·
<a href="i18n/README.ar.md">العربية</a><br>
The guides below are English only.
</sub></p>

**Your machine, with a team.** Bento Box AI is a local-first agentic operating system: a desktop
with real windows, files and a terminal, run by a lead agent and specialists that act on your
machine with your approval. The brain can be a local model through Ollama, a cloud model, or Claude
Code, Gemini CLI or Codex, and each specialist can run on a different one. The
[front page](../README.md) is the tour; the guides below go deeper.

---

## Contents

| Guide | What's inside |
|---|---|
| [Installation](installation.md) | Requirements, running from source, the `.deb` package, boot & login autostart |
| [Getting Started](getting-started.md) | First launch, choosing a model, autonomy, your first tasks |
| [The Lifecycle](lifecycle.md) | **Train · Test · Operate · Build · Ship · Manage** — the six pillars and Mission Control |
| [The Desktop](desktop.md) | Windows, the dock, the prompt bar and the places it finds inside apps, virtual desktops, widgets, themes and the immersive look, characters, keyboard shortcuts, the app catalog |
| [The session UI (SUI)](session-ui.md) | AgentOS **as** your Linux desktop: the layer-shell surface, native window management, installing applications, and what to install |
| [AgentOS as your DE](desktop-environment.md) | The AgentOS **login session** — boot into AgentOS, run modes, System Settings, notifications, lock screen, licences |
| [Licensing & trademarks](licensing.md) | What AgentOS ships and what it only *asks for*; why it redistributes no distribution; where the Ubuntu/Canonical trademark line sits |
| [The living desktop](experience.md) | Motion & design tokens, window management, the agent's hands, proactivity, the agent-led first run |
| [The Agent](agent.md) | How the agent works, the full tool set, autonomy levels, policies, memory, soul, skills |
| [Files your agents make](files.md) | Open a deck or a report from the chat that mentions it, get it on your phone, or find it in the Office's filing cabinet |
| [The World](world.md) | An experimental scene where your agents live with feelings that come from what they really do, grow in their own world, and your lead asks how you are. It all sleeps when you leave the scene |
| [The Mind](mind.md) | A scene that draws your lead and every specialist as one picture: what each remembers, knows and ran, how they are connected, the week in numbers, and a voice that says them |
| [The Office](office.md) | A comic-strip office where you watch your agents work: papers to desks, agents walking over to ask each other, huddles round the meeting table, and a designer for the look |
| [Your company](company.md) | Describe your business and get departments of agents, each with a head, staff and a persona. Give any department a task and watch the cards count the work |
| [Agents](agents.md) | Every agent's brain (AI providers), hands (executors: tools, folders, web, MCP), permissions and skills — and the map of who reaches what |
| [The team](team.md) | Each agent on its own brain (a provider model, or Claude Code, Gemini CLI or Codex), huddles, the matrix of who may ask whom, swarm and democracy (2 of 3 decide), and linked teams |
| [Accounts](accounts.md) | The mailbox and the calendar the agent may read for you: Sign in with Google or Microsoft, an MCP server, or an app password; what is never touched; the missions built on them |
| [Backup and moving machines](backup.md) | One encrypted file with the whole machine: every account, the vault's keys and the workspace. Restore it here or on a new computer, and see what needs you after |
| [Put Bento in the cloud](cloud.md) | Free, in one click on Render: its memory is kept sealed in your own free storage bucket, so a restart loses nothing. Or a paid plan, Fly.io, or your own server, with what each costs |
| [Cloud standby](standby.md) | Pair a cloud machine that takes over only while yours is away, and hands the work back when it returns. Active sync keeps it seconds behind. Or move to it on purpose |
| [A community of machines](pool.md) | Small machines like a Raspberry Pi join one leader: it lends its brain and holds the keys, they share notes and each take a piece of a bigger job. If the leader goes, the next one that may lead takes over |
| [One agent on screen, and the kiosk](small-screens.md) | For a small machine's own screen: the Office with just your agent, or the Office full screen with the mic on. Say your agent's name and what you need |
| [The vault](vault.md) | Where every account secret lives: encrypted, keyed by the keyring where there is one, read only by the system for its job and written down each time, never printed |
| [The Brief](brief.md) | How a mission delivers: things to act on, not a message — one living page a day, on the desktop, the phone, Telegram and out loud, where a decision is one tap and the reply comes back to the item |
| [Missions](missions.md) | What this machine does for you every day: the catalogue by persona (founder, coder, consultant), what a mission may read, what it did, and `bento job` |
| [Spaces, Gallery, Timeline, Audit](spaces.md) | Scoping memory and facts to a project, keeping what media servers return, the milestone timeline, and the structured access ledger |
| [Building Apps](building-apps.md) | App Studio, the Store, app data stores, letting apps call the OS |
| [Training Models](training.md) | The Train app (TrainForge): datasets, LoRA fine-tuning, evaluation, publishing |
| [Git & Shipping](git.md) | The git toolset, GitHub setup, exporting apps to repos |
| [The TUI](tui.md) | AgentOS in a terminal — over SSH or without a browser |
| [WhatsApp](whatsapp.md) | Your agent on WhatsApp — the Cloud API setup, the webhook, and Meta's 24-hour window |
| [Remote access](remote-access.md) | Reach the desktop from your phone — the opt-in switch, the lock, and what it is not |
| [Security](security.md) | Threat model, trust boundaries, `agentos doctor`, incident recovery |
| [Integrations](integrations.md) | Telegram, MCP tool servers, native desktop apps, system control, files & reports |
| [OpenClaw plugins](openclaw-plugins.md) | Extending OpenClaw from AgentOS — the scan, the consent screen, real permissions, and quarantine |
| [Agent sharing](agent-sharing.md) | Share your agent as one file, fork somebody else's — no data, no credentials, nothing enabled |
| [Models & Appearance](models.md) | Providers, the Ollama Model Manager, wallpapers & themes |
| [Configuration](configuration.md) | `config.json`, the sandbox, Settings, environment variables |
| [API Reference](api-reference.md) | REST endpoints, WebSocket streams, and the agent tool catalog |
| [Architecture](architecture.md) | How it's built — modules, data, request flow |
| [Roadmap](roadmap.md) | Product vision, differentiation vs chat-first assistants, feature pillars |
| [UX review, Sept 2026](design/ux-review-2026-09.md) | What a new person meets on a fresh install, measured in a real browser — defects, structural issues, and a plan |
| [Design: Subagents](design/subagents.md) | The execution fabric — subagents, task envelopes, mTLS enrollment, docker/remote workers |
| [Troubleshooting](troubleshooting.md) | Common issues and fixes |

---

## In one minute

```bash
curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh | sh
bento              # or, from a checkout: uv sync && uv run bento
```

Open http://127.0.0.1:8321 and setup walks you through a brain, your agent, the crew and a first
mission. `bento setup` does the same in a terminal. After that, ask from the prompt bar
(**Ctrl+Space**) or open Agent Chat.

> **Model note:** the agent uses tools to do real work. Choose a tool-capable model — any `qwen`
> model locally, or a cloud model. Some small local models won't reliably call tools.

---

## What makes it different

- **It acts.** The agent runs shell commands, edits files, browses, runs standing missions ([missions.md](missions.md)), and reports back
  with real output — not just chat.
- **It's a real desktop.** Draggable windows, a taskbar and dock, virtual desktops, pinnable live
  widgets, themes, and a command palette.
- **It builds itself.** Describe a tool and the agent builds a working app for it on the spot; apps
  get their own data store and can call the OS.
- **It integrates with your machine.** Launch any installed application, control sound and settings,
  browse and open your files, and reach the agent from Telegram.
- **It's yours and private.** Runs on `127.0.0.1`; with a local model, nothing leaves the machine.
  Risky actions ask for approval, destructive ones are blocked, and you can snapshot and roll back.
