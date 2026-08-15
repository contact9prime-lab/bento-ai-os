# Integrations

AgentOS connects to your phone, to external tool servers, and to the host desktop.

---

## Telegram

Control the agent from anywhere. Setup:

1. On Telegram, message **@BotFather** → `/newbot` → copy the bot token.
2. Open the **Telegram** app in AgentOS, paste the token, and enable the bridge.
3. Send **any** message to your new bot. The **first private chat** to do so becomes the owner;
   everyone else is listed and can be enabled or disabled per chat.

Once paired, the agent has all of its tools over Telegram — build apps, change settings, run jobs, get
reports. When it hits a risky action, it sends inline **Allow / Deny** buttons and waits for your tap
(unless autonomy is Full).

### The admin console

Telegram is also how you **operate** the machine when you are not at it. The paired owner gets
commands; every other enabled chat can only converse.

| | |
|---|---|
| `/help` | the list below |
| `/status` | model, autonomy, and whether a turn is running |
| `/model` `[id]` | what can answer; with an id, switch this machine to it |
| `/agents` | the specialists this machine has |
| `/run <agent> <task>` | hand a task to one of them |
| `/flows` · `/flow <name> [input]` | standing missions, and running one now |
| `/tools [search]` | what the agent can do |
| `/logs [n\|search]` | the operator diary, plus what was recently denied or asked about |
| `/perms` | who has been granted what |
| `/clear` | wipe this conversation and start fresh |

The commands appear as Telegram's **Menu** button and `/` autocomplete — AgentOS registers them
itself (`setMyCommands`) when the bridge starts and again when a chat becomes the owner, so there
is nothing to type into BotFather and no hand-kept copy to go stale. The menu is scoped: the
owner's chat sees the console, every other enabled chat sees only `/help`, `/status` and `/clear`,
because offering somebody a command they will then be refused is worse than not offering it. If
the menu ever looks out of date, restart the bridge from the Telegram app — publishing happens on
start. (Telegram clients cache the list briefly; it can take a minute to appear.)

Two things about it are deliberate. **A command is never a way around the gate:** `/run` is
`delegate` and `/model` is `configure_agentos`, so each goes through the same policy decision,
the same Allow / Deny buttons and the same audit row as the equivalent action at the desk — a
console that bypassed policy would be a second, unaudited way to use the machine. And **reading
works while it is busy**, because "what is it doing" is exactly the question you ask when it is
in the middle of something.


**Chat management:** the Telegram app shows every user, group and **channel** that has reached the
bot, with the owner badged and an enable/disable toggle for each. Only enabled chats can talk to the
agent. Connect more channels by adding the bot to a group (as a member) or to a broadcast channel (as
an admin) — new arrivals start blocked until you permit them in the app. (In groups, a bot only sees
messages that mention it unless you disable privacy mode via BotFather.)

**Letting somebody in before they write.** That toggle only exists once there is a row, and there is
no row until somebody has messaged you — so on its own it means a colleague has to be turned away
first and then found in a list. The **Also allow** field is the standing list, written in advance:
`@usernames` or numeric chat ids, comma separated. Anyone named there is admitted on their first
message. It is one field on the channel, so it is the same list in all three faces:

```
bento channels telegram --set 'allow=@bob, @sam'     # over SSH, no desktop needed
bento channels telegram                              # read it back
```

**Everybody else is refused, and the refusal is written down.** A stranger messaging your bot used
to leave a log line indistinguishable from a message that was answered, so *"has anyone else been
trying to reach my agent?"* could not be answered from the record. Every refusal is now logged with
who, what they sent, and how many times they have tried — every time, not only on the first message,
because a sustained attempt that shows up once and then goes quiet is the case you most want to see:

```
[telegram] refused X (333) — not paired and not on the allow-list
           {'chat_id': 333, 'username': '', 'msg_count': 2, 'text': 'hello?'}
```

Filter for them in the Logs app, or `bento logs --kind telegram`.

**Telegram is an IO gate:** it is one of the permission framework's surfaces. Any grant can be scoped
to `telegram` (or kept off it) in the Permissions app — a rule permitted on all surfaces flows
everywhere; scoped rules only apply on their gates, and blocked IO is denied and logged. See
[Security → IO gates](security.md).

---

## MCP tool servers ("channels")

The **Model Context Protocol** lets AgentOS connect to external tool servers, giving the agent new
abilities. Add them from the **MCP Servers** app or the Store's **Channels** tab — the
catalog covers the most renowned servers, one click each, and prompts for whatever credential the
service needs. You can also add a custom `stdio` (command) or `http` (URL) server.

### Discover: the worldwide MCP registry

The Store's **Discover** tab is the app store's discovery engine: it searches the public
[MCP registry](https://registry.modelcontextprotocol.io) — thousands of community-published
servers — and turns any result into a working AgentOS integration:

1. **Search as you type** for a capability ("weather", "postgres", "calendar"…). The public
   registry API is slow (15-25s per request), so AgentOS syncs the whole catalog into a local
   index in the background (`~/.agentos/mcp_index.json`, refreshed daily) and searches it
   locally in milliseconds — while the first sync is still running, results keep growing and
   the status line shows how much of the registry has been indexed so far.
2. **Install with consent** — nothing installs silently. You confirm *"build around this?"*,
   supply any API keys (or leave them for later — the server stays disabled until they're set
   in the MCP app), and the config is written for you (npm → `npx`, PyPI → `uvx`, remote →
   `http` with header templates).
3. **The MCP Registry** records every installed server as a first-class entry — where it came
   from, how it runs, what it needs — visible via `GET /api/mcp/registry` and behind the 📖
   buttons in the MCP Servers app.
4. **Documentation is generated automatically**: each registry entry gets a manual page in the
   **Docs** app (`mcp/<name>.md`) covering its tools (refreshed when the server connects),
   configuration keys, and the permissions that govern it.
5. **Build on top** — after installing, the Store offers to build an AI-native desktop app
   around the new server in App Studio, with a permission manifest scoped to
   `mcp.use · mcp:<name>/*` that you approve at install.

The agent can drive the same flow conversationally: `discover_mcp_servers(query)` searches the
registry, and `install_mcp_server(...)` — always approval-gated — installs after you say yes.

### The curated catalogue: first-party servers the registry does not list

The public registry is a *publishing* registry — a vendor appears in it only if that vendor
chose to publish there, and most of the well-known ones did not. Searching it for
`higgsfield` returns **nothing**; searching for `canva` returns third-party imitations and
Canvas-LMS courseware, with no official server among them. Their servers are real and
running; they are announced on the vendor's own domain instead.

So AgentOS ships a short curated list (`agentos/mcp_catalog.py`) of servers it knows exist,
merged **ahead of** registry results in Discover and shown as its own section in the MCP
Servers app. Every entry was probed live before being added, and
`packaging/dev/probe-catalog.sh` re-checks them all on demand.

| Server | Category | What it adds |
|---|---|---|
| Higgsfield | Media & creative | video, image, audio and 3D generation; upscale, reframe, publish |
| Canva | Media & creative | designs, brand templates, folders, exports |
| Replicate | Media & creative | thousands of open image/video/audio models |
| fal | Media & creative | fast hosted generative media |
| Figma | Media & creative | read designs and components to build from |
| Notion | Productivity | pages and databases |
| Linear | Productivity | issues, projects, cycles |

All seven sign in with **OAuth in your browser** — there is no key to paste. Two rules keep
the list honest, and both are enforced by review rather than by hope:

- **Nothing goes in unprobed.** The endpoint must answer an MCP `initialize`.
- **Dynamic Client Registration is required.** That is what makes connecting one click. A
  server that needs a hand-made OAuth app cannot be one click, so it stays out —
  `mcp.stripe.com` is real, and deliberately absent for exactly this reason. (Stripe is
  still available as an API-key preset, below.)

Add one from anywhere:

```
bento mcp catalog              # what is on offer
bento mcp add canva            # add it and start sign-in
bento mcp list                 # what is connected, and what is waiting for you
bento mcp disconnect canva     # forget the tokens and the registration
```

### Catalog & authentication

**Essentials — no key needed:** Playwright (browser automation), Filesystem, Fetch, Memory
(knowledge graph), Sequential Thinking, Git, Time, SQLite, Everything (test server).

**Web & search:**

| Server | Auth | Where to get it |
|---|---|---|
| DuckDuckGo | none | — |
| Context7 (library docs) | none | — |
| DeepWiki (ask about any GitHub repo) | none | — |
| Microsoft Learn | none | — |
| Brave Search | `BRAVE_API_KEY` | brave.com/search/api (free tier) |
| Tavily | `TAVILY_API_KEY` | app.tavily.com (free tier) |
| Exa | `EXA_API_KEY` | dashboard.exa.ai/api-keys |
| Perplexity | `PERPLEXITY_API_KEY` | perplexity.ai → Settings → API |
| Firecrawl | `FIRECRAWL_API_KEY` | firecrawl.dev → API keys |
| Hugging Face | optional token | hf.co/settings/tokens (works anonymously) |

**Developer & data:**

| Server | Auth | Where to get it |
|---|---|---|
| GitHub (official, remote) | personal access token | github.com/settings/tokens |
| Postgres | connection string | your database |
| MongoDB | `MDB_MCP_CONNECTION_STRING` | Atlas → Connect → Drivers |
| Supabase | `SUPABASE_ACCESS_TOKEN` + project ref | supabase.com/dashboard/account/tokens |
| Sentry | OAuth (browser sign-in) | — |
| Vercel | OAuth (browser sign-in) | — |
| Kubernetes | local kubeconfig | — |
| AWS Docs / Cloudflare Docs | none | — |

**Apps & SaaS:**

| Server | Auth | Where to get it |
|---|---|---|
| Notion | `NOTION_TOKEN` (integration secret) | notion.so/profile/integrations — then share pages with the integration |
| Linear | OAuth (browser sign-in) | — |
| Atlassian (Jira & Confluence) | OAuth (browser sign-in) | — |
| Slack | `SLACK_BOT_TOKEN` + `SLACK_TEAM_ID` | api.slack.com/apps → OAuth & Permissions |
| Airtable | `AIRTABLE_API_KEY` | airtable.com/create/tokens |
| Stripe | secret key (`sk_…`) | dashboard.stripe.com/apikeys (restricted key recommended) |
| Figma | `FIGMA_API_KEY` | Figma → Settings → Security |
| Google Maps | `GOOGLE_MAPS_API_KEY` | console.cloud.google.com → Credentials |
| Zapier (8,000+ apps) | personal MCP URL | mcp.zapier.com |
| ElevenLabs | `ELEVENLABS_API_KEY` | elevenlabs.io → API keys |

### How auth is wired

- **stdio servers** get API keys as **environment variables** (`"env": {...}` in the server's
  config entry) — the catalog prompts you and stores them in `~/.agentos/config.json`.
- **http servers** authenticate with **request headers**, typically
  `"headers": {"Authorization": "Bearer <token>"}`.
- **Curated OAuth servers** (Canva, Higgsfield, Notion, Linear, Figma, Replicate, fal)
  authenticate **natively** — AgentOS speaks OAuth 2.1 itself (`agentos/mcp_oauth.py`):
  it discovers the authorisation server from the `401`, registers itself dynamically,
  runs the code+PKCE exchange and refreshes the token when it expires. No Node, no
  subprocess, no bridge. Tokens live in `~/.agentos/oauth/<server>.json` at mode `0600`,
  and **Sign out** deletes both the tokens and the client registration, so the next
  sign-in genuinely asks again.

  Each server gets its own callback path (`/api/mcp/oauth/callback/<name>`), which is how
  two simultaneous sign-ins are told apart. On a **headless machine** nothing can open a
  browser, so `bento mcp connect <name>` prints the URL for you to open anywhere — set
  `mcp_oauth.redirect_base` in `~/.agentos/config.json` when the box is not reachable at
  `127.0.0.1` from wherever you open it.

- **Older OAuth presets** (Sentry, Atlassian, Vercel) still run through the
  [`mcp-remote`](https://www.npmjs.com/package/mcp-remote) bridge: the first connection opens a
  browser tab where you sign in; the token is cached in `~/.mcp-auth` afterwards. These need
  Node, which is the trade-off native OAuth removes.

A connected server's tools appear to the agent as `mcp_<server>_<tool>` and to built apps via
`appTool(...)`. You can also just ask: *"add the playwright channel," "remove the git server."*

MCP tools are treated as risky by default (they call external services), so they ask for approval
unless autonomy is Full.

> Running MCP servers usually requires `npx` (Node) and/or `uvx` on your machine.
> Keys live in `~/.agentos/config.json` in plain text — treat that file as a secret.

---

## Skills

Skills are reusable procedures the agent loads with `use_skill` before starting a matching task.
The **Skills** app (and the Store's **Skills** tab) ships a catalog of renowned open-source
skills — every entry is **MIT or Apache-2.0 licensed**, so they can be pulled and built on freely:

| Skill | License | Source |
|---|---|---|
| Superpowers (pack: TDD, debugging, planning, code review, …) | MIT (repo-wide LICENSE) | github.com/obra/superpowers |
| React Best Practices | MIT (declared in its SKILL.md) | github.com/vercel-labs/agent-skills |
| Skill Creator, MCP Builder, Webapp Testing, Frontend Design, Canvas Design, Algorithmic Art, Brand Guidelines, Theme Factory, Internal Comms | Apache-2.0 (per-skill LICENSE.txt) | github.com/anthropics/skills |

Every license above was verified against the actual LICENSE file or frontmatter, not the README.
Deliberately **excluded** despite being in those repos: the `docx`/`pdf`/`pptx`/`xlsx` document
skills (source-available, not open source), `doc-coauthoring` (ships no license grant at all), and
the other Vercel skills (no repo-level LICENSE and no per-skill declaration). Install those
manually if their terms work for you.

You can also install from any git repo or raw `.md` URL: repos are scanned for `SKILL.md` files
(one skill per folder, YAML frontmatter for name/description), falling back to all `*.md` files.
The agent's system prompt lists installed skills and connected MCP servers each turn, and instructs
it to load a matching skill before starting a task and to prefer MCP tools in their domain.

---

## Native applications

The **Applications** app is a searchable grid of **every program installed on your computer**, with
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

The **Quick Settings** wires the OS to your real hardware:

- **Sound** — volume slider and mute (PipeWire/`wpctl`).
- **Battery** — charge level and state (`upower`).
- **Network** — current connections (`nmcli`).
- **Native settings** — buttons that open the system's Sound, Wi-Fi, Bluetooth, Display, Power, and
  Background panels.

A tray indicator in the taskbar shows volume and battery at a glance; click it to open the Control
Center. The agent can also control this: *"set the volume to 30," "mute," "open sound settings."*

---

## Files & reports

The **Files** app browses your workspace (`~/AgentOS` by default). Click a folder to navigate;
click a file to **open it in your system browser or its default app** — reports, images, PDFs, and
documents all open natively.

When the agent finishes research or analysis, it saves a formatted **report** to `~/AgentOS/reports/`,
which shows up in Files and opens in your browser. Reports can also be delivered to Telegram in the
same step. Ask for one directly — *"research X and save a report"* — or schedule it as a recurring
job.

### other things -- PC 

 Plus the app studio should be able to use the MCPs as well for the connection to get more information that
  permission should be taken in the app and installed as a manifest for the appllication and it can be added to
  pre-requsite if its install on the third party os to install that as well (Distribution made easy). Once the
  permissionsa re give it can be revoked as well by the user too. This is important to be in control. The Apps
  permission should flow through the policy framework. The policy framework has to be made more robust to support such
  service mesh permissions. Permission to Interact, Permission between apps, Permissions between Agents, Permissions
  between Services etc. Permissions to use the skills, Permissions to use the MCP, Permissions to use the LLMs. All
  should be defined in the manifest of the Permission framework. That is single source of gate of the control plane.
  Also the subagents should be able to be use this framework for the controls etc. Policy is most important for things
  to work.