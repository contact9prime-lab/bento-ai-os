# API Reference

AgentOS exposes a REST API, two WebSocket streams, and a catalog of agent tools. Everything the UI
does goes through these, and apps you build can use them too. The server binds to `127.0.0.1:8321` by
default.

---

## WebSocket

### `/ws` — chat, approvals, build & live events
The primary channel. Send:
- `{ "type": "chat", "text", "conversation_id?", "model?" }` — run an agent turn
- `{ "type": "build", "prompt", "app_id?", "model?" }` — run an App Studio build
- `{ "type": "approval", "id", "approved" }` — answer an approval request
- `{ "type": "abort" }` — stop the current turn

It streams back events including `text_delta`, `thinking_delta`, `tool_start`, `tool_end`,
`approval_request`, `turn_end`, and build/model progress events.

### `/ws/terminal` — host shell
A PTY bridge for the Terminal app. Send `{ "type": "input", "data" }` and
`{ "type": "resize", "cols", "rows" }`; receive raw terminal output.

---

## REST endpoints

### Chat & conversations
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/chat` | one-shot agent turn: `{ text, model?, conversation_id? }` → `{ content, steps }` |
| GET | `/api/conversations` | list conversations |
| GET | `/api/conversations/{id}` | messages in a conversation |
| POST | `/api/conversations/{id}/clear` | wipe a conversation's messages |
| DELETE | `/api/conversations/{id}` | delete a conversation |

### System & files
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/system` | CPU, memory, disk, load, uptime, top processes |
| GET | `/api/files?path=` | list workspace files (sandbox-scoped) |
| GET | `/api/files/raw?path=` | fetch a file's contents |
| POST | `/api/open` | open a URL or workspace file in the host browser/app |

### Tools & registry
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/registry` | **the API registry** — self-describing list of every REST/WS endpoint, tool, realtime event and injected page global. The contract AI-built apps, themes and full replacement shells code against |
| GET | `/api/tools` | list callable tools (built-in + MCP) |
| POST | `/api/tool` | run a tool: `{ name, args }` → `{ output }` (risk-gated) |

### Apps, widgets & store
| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/api/apps` | list / save a user app |
| GET | `/api/apps/{id}/versions`, `/{version}` | version history (every changed save is a version) |
| POST | `/api/apps/{id}/versions/{version}/restore` | roll back — restores as a new version, deployed live |
| DELETE | `/api/apps/{id}` | delete an app |
| GET | `/api/apps/{id}/page` | the app's HTML (runtime injected) |
| GET/PUT | `/api/apps/{id}/data` | the app's data store |
| GET/PUT | `/api/widgets` | list / set pinned desktop widgets |
| GET | `/api/store/templates` | curated one-click app templates |
| POST | `/api/store/install` | install a template |

### Memory, knowledge, skills, soul
| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/api/memories`, PUT/DELETE `/{id}` | memory. GET filters: `?scope=user\|session`, `conversation_id`, `q`. POST: `{content, scope, conversation_id, pinned}`. PUT: `{content, pinned, scope}` — scope `user` promotes a session memory |
| GET/POST | `/api/kg`, DELETE `/api/kg`, DELETE `/api/kg/nodes/{id}` | knowledge graph |
| GET | `/api/knowledge/status` | memory/KG counts, embedding model, auto-learn state |
| POST | `/api/knowledge/maintain` | run maintenance now: embed memories, roll up idle sessions, dedup the graph |

### Fabric (subagents & workflows — the control plane)
| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/api/subagents`, DELETE `/{id}`, POST `/{name}/run` | subagent definitions + fire a test run |
| GET/POST | `/api/workflows`, DELETE `/{id}`, POST `/{name}/run` | workflow DAGs + start a run |
| GET | `/api/fabric/runs`, `/api/fabric/runs/{id}` | run history; detail includes step runs + events (heartbeats, steps, faults) |
| POST | `/api/fabric/runs/{id}/cancel` | control → data plane: abort a run and its steps |
| GET | `/api/fabric/observability` | faults / performance / tokens per data plane, incl. the main agent; live heartbeats |
| POST | `/api/plane/llm` | model plane: run a completion through the control plane's provider config (the surface L1+ workers call over mTLS) |

### Flows (a master orchestrator as the control plane — [design](design/flows.md))
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/flows` | every flow with its triggers (webhook URLs included) and the grants its definition wrote |
| POST | `/api/flows/draft` | compose from a sentence and create it **disabled**, so it appears as a card holding no permissions |
| POST | `/api/flows/compose` | compose from a sentence, or revise one (`current`) — writes nothing |
| POST | `/api/flows/{name}/enable` | `{"enabled": true\|false}` — enabling is what grants permissions and arms triggers |
| POST | `/api/flows/{name}/discard` | throw a draft away, including agents it created that nothing else uses |
| GET | `/api/flows/runs` | every flow execution, newest first, `?flow=` to filter — delegations, agents used, failed steps, duration |
| POST | `/api/subagents/compose` | draft or revise one specialist from a sentence — writes nothing |
| POST | `/api/flows/preview` | what saving this definition *would* grant — writes nothing |
| POST | `/api/flows` | create/update: validates, saves, reconciles grants and triggers, returns a report |
| DELETE | `/api/flows/{name}` | delete; its triggers stop and its definition-sourced grants are revoked |
| POST | `/api/flows/{name}/run` | start it; returns `run_id` **synchronously** so the caller can subscribe to its events |
| GET | `/api/flows/runs/{id}/board` | the blackboard index (no artefact contents) |
| GET | `/api/flows/runs/{id}/artifacts/{handle}` | one artefact in full |
| POST | `/api/hooks/{flow}/{trigger_id}` | inbound webhook. Per-trigger secret (`?k=` or `X-AgentOS-Hook-Secret`), cooldown enforced before the body is read, 64 KB cap, run is tainted. **Outside the remote-access gate** |
| GET | `/api/fabric/approvals` | what is paused waiting for a person (this is what makes the TUI/CLI first-class) |
| POST | `/api/fabric/approvals/{id}` | answer one: `{"approved": true, "remember": false}` |

### Quarantine (what the OS stopped, and why)
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/quarantine?history=` | what is held now — principal, reason, evidence — and past release decisions |
| POST | `/api/quarantine/{id}/release` | `{"mode": "once"\|"forever"\|"deleted"}` — the choice and who made it are logged |
| POST | `/api/apps/{id}/resume` | start a stopped app again (its rate history is forgotten, or it would trip immediately) |

### Docs & setup
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/docs`, `/api/docs/{file}` | the bundled manual (markdown) — powers the Docs app and TUI tab 8 |
| GET | `/api/setup` | wizard state: first_run flag, detected Ollama models, provider/key status, autostart state |
| POST | `/api/setup` | apply wizard choices `{agent_name, autonomy, default_model, providers, autostart, open_at_login}`; autostart installs the launcher + systemd user service (+ boot-time linger where allowed) |
| POST | `/api/setup/reset` | factory reset `{confirm: true}` — wipes all data + config, deletes the soul, re-arms the wizard |
| GET/POST | `/api/skills`, DELETE `/{id}`, POST `/api/skills/install` | skills (incl. git/URL install) |
| GET/PUT | `/api/soul` | the agent's identity file |

### Scheduler, logs, analytics
| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/api/tasks`, PUT/DELETE `/{id}` | scheduled jobs |
| GET/DELETE | `/api/logs` | activity logs |
| GET | `/api/analytics/tokens` | token totals from turn logs, by model and by day (last 1000 turns) |
| GET | `/api/usage` | the cost ledger: `?days=&group=model\|day\|surface\|kind\|conversation\|space` → tokens **and** money, with unpriced turns reported separately |
| GET | `/api/evals` | behavioural eval cases + the last run |
| POST | `/api/evals/run` | run the evals: `{ models?, cases?, tags?, network? }` → report (one run at a time) |

### Models & appearance
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/models` | available models across providers |
| GET | `/api/models/manage` | installed Ollama models, running models, GPU |
| POST | `/api/models/pull` | download a model (background, progress via `/ws`) |
| DELETE | `/api/models/{name}` | remove a model |
| POST | `/api/wallpaper/generate` | generate a wallpaper from a prompt |
| POST | `/api/wallpaper/system` | adopt the host wallpaper |
| GET | `/api/wallpapers`, `/{id}`, POST `/{id}/set`, DELETE `/{id}` | wallpaper gallery |

### Integrations
| Method | Path | Purpose |
|---|---|---|
| GET/PUT | `/api/telegram`, POST `/api/telegram/test` | Telegram bridge config & test |
| PUT/DELETE | `/api/telegram/chats/{id}` | enable/disable/remove a chat |
| GET/PUT | `/api/mcp` | MCP servers status & config |
| GET | `/api/native/apps`, `/api/native/icon/{id}`, POST `/api/native/launch` | native app launcher |
| GET/POST | `/api/control` | sound/battery/network state; set volume/mute/open settings |

### Snapshots & config
| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/api/snapshots`, POST `/{id}/restore`, DELETE `/{id}` | restore points |
| GET/PUT | `/api/config` | read / update settings (API keys are masked on read) |

---

## Agent tools

Callable via `POST /api/tool { name, args }`, from apps via `appTool(name, args)`, and by the agent
itself. Risk level determines whether they need approval (see [Safety](agent.md#safety)).

`run_command`, `read_file`, `write_file`, `list_dir`, `fetch_url`, `system_info`, `open_app`,
`notify`, `remember`, `recall`, `kg_add`, `kg_query`, `update_soul`, `read_app_data`, `save_report`,
`create_app`, `pin_widget`, `configure_agentos`, `add_mcp_server`, `manage_models`, `use_skill`,
`save_skill`, `delete_skill`, `schedule_task`, `launch_native_app`, `system_control`,
`telegram_send`, `read_source`, `develop_agentos`, `restart_agentos`, `snapshot_os`, `generate_wallpaper`,
`set_wallpaper` — plus every connected MCP tool as `mcp_<server>_<tool>`.

Get the live list (including MCP tools) from `GET /api/tools`.
