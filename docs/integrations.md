# Integrations

AgentOS connects to your phone, to external tool servers, and to the host desktop.

---

## Telegram

Control the agent from anywhere. Setup:

1. On Telegram, message **@BotFather** → `/newbot` → copy the bot token.
2. Open the **✈️ Telegram** app in AgentOS, paste the token, and enable the bridge.
3. Send **any** message to your new bot. The **first private chat** to do so becomes the owner;
   everyone else is listed and can be enabled or disabled per chat.

Once paired, the agent has all of its tools over Telegram — build apps, change settings, run jobs, get
reports. When it hits a risky action, it sends inline **Allow / Deny** buttons and waits for your tap
(unless autonomy is Full).

**Commands:** `/clear` resets the session · `/status` reports the current model and autonomy.

**Chat management:** the Telegram app shows every user/group that has messaged the bot, with the owner
badged and an enable/disable toggle for each. Only enabled chats can talk to the agent. (In groups,
a bot only sees messages that mention it unless you disable privacy mode via BotFather.)

---

## MCP tool servers ("channels")

The **Model Context Protocol** lets AgentOS connect to external tool servers, giving the agent new
abilities. Add them from the **🔌 MCP Servers** app or the App Store's **Channels** tab:

- One-click catalog entries: **Playwright** (browser automation), **Filesystem**, **Fetch**,
  **Memory**, **Git**, **GitHub**, **Time**, **SQLite**, **Postgres**, **Puppeteer**, **Brave
  Search**, **DuckDuckGo**, **Slack**, **Google Maps**, **Context7**, and more.
- Or add a custom `stdio` (command) or `http` (URL) server, with optional environment variables for
  API keys.

A connected server's tools appear to the agent as `mcp_<server>_<tool>` and to built apps via
`appTool(...)`. You can also just ask: *"add the playwright channel," "remove the git server."*

MCP tools are treated as risky by default (they call external services), so they ask for approval
unless autonomy is Full.

> Running MCP servers usually requires `npx` (Node) and/or `uvx` on your machine.

---

## Native applications

The **🗔 Applications** app is a searchable grid of **every program installed on your computer**, with
their real icons. Click one to launch it on the host desktop. The agent can do this too —
*"open Firefox," "launch the calculator."*

### Running windows in the taskbar

AgentOS's taskbar shows the **native windows open on your desktop** (Firefox, editors, file managers,
etc.) next to its own windows. Click one to **switch to it** (raise/focus), or right-click to close
it — so AgentOS acts as a real shell over your running apps. The agent can do it too:
*"switch to Firefox," "what windows are open?"* (`list_windows`, `focus_window`).

> **Requirement:** this needs an **X11 session** with `wmctrl` installed
> (`sudo apt install wmctrl`). Under a **Wayland** session the list stays empty and the taskbar shows
> nothing, because Wayland restricts window control for security — log into an X11 session (e.g. the
> Xfce/X11 option at the login screen) to enable switching and closing native windows from AgentOS.

---

## System control

The **🎛 Control Center** wires the OS to your real hardware:

- **Sound** — volume slider and mute (PipeWire/`wpctl`).
- **Battery** — charge level and state (`upower`).
- **Network** — current connections (`nmcli`).
- **Native settings** — buttons that open the system's Sound, Wi-Fi, Bluetooth, Display, Power, and
  Background panels.

A tray indicator in the taskbar shows volume and battery at a glance; click it to open the Control
Center. The agent can also control this: *"set the volume to 30," "mute," "open sound settings."*

---

## Files & reports

The **🗂 Files** app browses your workspace (`~/AgentOS` by default). Click a folder to navigate;
click a file to **open it in your system browser or its default app** — reports, images, PDFs, and
documents all open natively.

When the agent finishes research or analysis, it saves a formatted **report** to `~/AgentOS/reports/`,
which shows up in Files and opens in your browser. Reports can also be delivered to Telegram in the
same step. Ask for one directly — *"research X and save a report"* — or schedule it as a recurring
job.
