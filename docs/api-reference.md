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

### Tools
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/tools` | list callable tools (built-in + MCP) |
| POST | `/api/tool` | run a tool: `{ name, args }` → `{ output }` (risk-gated) |

### Apps, widgets & store
| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/api/apps` | list / save a user app |
| DELETE | `/api/apps/{id}` | delete an app |
| GET | `/api/apps/{id}/page` | the app's HTML (runtime injected) |
| GET/PUT | `/api/apps/{id}/data` | the app's data store |
| GET/PUT | `/api/widgets` | list / set pinned desktop widgets |
| GET | `/api/store/templates` | curated one-click app templates |
| POST | `/api/store/install` | install a template |

### Memory, knowledge, skills, soul
| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/api/memories`, DELETE `/{id}` | long-term memory |
| GET/POST | `/api/kg`, DELETE `/api/kg`, DELETE `/api/kg/nodes/{id}` | knowledge graph |
| GET/POST | `/api/skills`, DELETE `/{id}`, POST `/api/skills/install` | skills (incl. git/URL install) |
| GET/PUT | `/api/soul` | the agent's identity file |

### Scheduler, logs, analytics
| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/api/tasks`, PUT/DELETE `/{id}` | scheduled jobs |
| GET/DELETE | `/api/logs` | activity logs |
| GET | `/api/analytics/tokens` | token usage totals, by model and by day |

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
