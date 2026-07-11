# Building Apps

AgentOS can build tools *into itself*. You describe an app in plain language and the agent builds a
working, self-contained app that gets a desktop icon and opens in a window. Apps can store their own
data and call the operating system.

---

## App Studio

Open **App Studio** and describe what you want — *"a habit tracker with daily checkboxes," "a
dashboard of my scheduled tasks," "a button that runs a command and shows the output."* The builder:

1. streams its work in the panel on the left (with a thinking animation),
2. installs the app, and
3. shows a **live preview** on the right.

**Refine** an app by selecting it from the dropdown and describing a change — the builder edits the
existing app in place, keeping context across iterations.

From App Studio you can also **Open** an app in its own window, **Pin** it to the desktop as a widget,
or **Delete** it. You can hand-edit an app's HTML directly, too.

> Build quality tracks the model. A tool-capable model (a `qwen` model, or a cloud model) produces
> noticeably better apps. If a build produces nothing, AgentOS automatically retries with a
> tool-capable model when one is available.

---

## The Store

The **Store** has four tabs:

- **Apps** — curated, ready-made apps (Focus Timer, Quick Notes, Calculator, World Clock, System
  Monitor) that install in **one click**, no model required.
- **Channels** — the MCP tool-server catalog; add browser automation, GitHub, search, and more.
- **Skills** — install skills from a git repo or URL.
- **Build with AI** — describe an app and hand off to App Studio.

---

## What apps can do

Every built app runs in a same-origin frame and is given a small runtime automatically. That means an
app's own JavaScript can:

### Store its own data
Each app has a private, server-side data store — its own little backend:

```js
const state = await appData.get();          // returns the app's saved object
state.count = (state.count || 0) + 1;
await appData.set(state);                    // persists it
```

This survives reloads **and** is readable by the agent, so you can ask *"what's in my Notes app?"*
and it will answer from the app's stored data. Prefer `appData` over `localStorage`.

### Call the operating system
Apps can run any agent or MCP tool to pull live data or take action:

```js
const sys = await appTool('system_info');                       // machine snapshot
const page = await appTool('fetch_url', { url: 'https://…' });   // fetch a page
const out  = await appTool('run_command', { command: 'uptime' });
```

`appTool` respects your autonomy and policy settings — risky actions are gated the same way they are
for the agent.

### Use the REST API and real-time streams
Apps can also call the [REST API](api-reference.md) directly (`/api/system`, `/api/chat`, …), poll on
a schedule, or open a WebSocket to `ws://<host>/ws` for real-time updates.

---

## Widgets

Any app can be pinned to the desktop as a **live widget** — see
[The Desktop → Widgets](desktop.md#widgets). Because widgets are full apps, they keep updating,
persist their data, and restore when the desktop starts.

---

## Under the hood

- Apps are stored in the database and served at `GET /api/apps/{id}/page`, with the runtime injected
  automatically.
- App data lives at `GET`/`PUT /api/apps/{id}/data`.
- The agent's `create_app`, `read_app_data`, and `pin_widget` tools power the build/inspect/pin flow.

See the [API Reference](api-reference.md) for the exact endpoints.
