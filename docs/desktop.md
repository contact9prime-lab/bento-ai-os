# The Desktop

AgentOS is a full desktop environment, not a chat box. This guide covers the shell — windows, the
taskbar, virtual desktops, widgets, themes, shortcuts — and the catalog of built-in apps.

---

## The shell

### Windows
Every app opens in a draggable, resizable window with minimize / maximize / close and proper
z-ordering. Double-click a title bar to maximize. The **taskbar** at the bottom tracks open windows.

### Start menu & dock
- **Start** (bottom-left) opens the full app menu with descriptions.
- The **dock** next to Start holds quick-launch shortcuts for your favorite apps, each showing a dot
  when running. Right-click a dock icon to remove it.

### Desktop icons
Every app has a desktop icon. **Drag icons anywhere** — positions are remembered. Single-click
selects; double-click launches.

### Virtual desktops
A pager in the taskbar (`1 2 +`) gives you multiple desktops:
- **Click** a number to switch; **right-click** a number to move the active window there.
- **Ctrl+1…6** switches desktops.
- Widgets are **per-desktop**, so each desktop is its own workspace.

### Command palette
Press **Alt+Space** or **Ctrl+Space** anywhere for a fast launcher: fuzzy-search to open any app, run
an action (new chat, clear session, toggle voice, reset wallpaper), or choose **"Ask …"** to send
your text straight to the agent.

### Fullscreen
Press **F11** (or use the Settings button) to toggle fullscreen. Launched via `agentos app`, the
desktop opens fullscreen automatically, hiding the host taskbar.

---

## Widgets

Pin any app to the desktop as a **live tile**:
- From **App Studio**, select an app and choose **Pin to desktop**, or ask the agent
  (*"pin the stock tracker to my desktop"*).
- Widgets are frameless; hover to reveal a small toolbar (refresh, open in a window, unpin).
- **Drag** to move (snaps to a grid), drag the corner to resize — positions persist and restore on
  startup.
- Start menu → **▦ Arrange widgets** tiles them neatly.

Because widgets are full apps, they can poll on a schedule, call the OS, run tools, and update in
real time.

---

## Themes

Open **Settings → Appearance** and pick a theme; the entire interface recolors instantly:

- **AgentOS** (teal, default)
- **Ember** (dark — warm orange accent)
- **Ember** (light)
- **Dracula**
- **Nord**

Your choice is remembered.

### Wallpaper
In **Personalize** you can:
- **Use your system wallpaper** — adopts the host desktop background so AgentOS matches your system.
- **Generate a wallpaper** with AI from a text description (saved to a local gallery you can pick
  from later).
- **Reset** to the built-in background.

See [Models & Appearance](models.md) for more.

---

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| **Alt+Space** / **Ctrl+Space** / **Ctrl+K** | command palette (launch app / ask the agent) |
| **Ctrl+Shift+P** | command palette (works inside the terminal too) |
| **Ctrl+Alt+T** | open a terminal |
| **Ctrl+1 … Ctrl+6** | switch virtual desktop |
| **F11** | toggle fullscreen |
| **Enter** (in chat) | send · **Shift+Enter** for a newline |

---

## App catalog

| App | Purpose |
|---|---|
| **Agent Chat** | talk to the agent — streaming replies, tool activity, approvals, voice |
| **Applications** | launch any program installed on your computer |
| **Web** | open web pages in your real system browser |
| **Files** | browse your workspace; click a file to open it |
| **Terminal** | a real shell on your machine (sandboxed if enabled) |
| **Quick Settings** | sound, network, battery, and shortcuts to native settings |
| **Store** | install ready-made apps, add tool channels, or build with AI |
| **App Studio** | build and refine apps by describing them |
| **Task Manager** | live CPU / memory / disk, processes, open windows |
| **Model Manager** | manage local Ollama models and view GPU usage |
| **Knowledge Graph** | what the agent knows, as a live graph |
| **Soul** | the agent's persistent identity and personality |
| ◈ **Memory** | long-term facts the agent remembers |
| **Skills** | reusable procedures; install from git or a URL |
| **MCP Servers** | connect external tool servers |
| **Telegram** | control the agent from your phone |
| **Policies** | always-allow / always-deny rules for the agent |
| **Logs** | everything the system did |
| **Token Analytics** | model token usage over time |
| **Scheduler** | recurring background jobs |
| **Personalize** | wallpapers and gallery |
| **Snapshots** | restore points for the whole system |
| **Settings** | providers, model, autonomy, appearance, voice, sandbox |
| ▲ **About** | system information |

Details for the interactive and integration apps are in [Building Apps](building-apps.md) and
[Integrations](integrations.md).

---

## Voice

In **Settings → Voice** you can enable:
- **Speak replies** (text-to-speech) — toggle with in the chat toolbar.
- **Dictation** — the button in the composer transcribes your speech into the message.

Both use your browser's built-in speech features; grant microphone permission on first use.
