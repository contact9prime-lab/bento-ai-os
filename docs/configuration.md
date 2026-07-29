# Configuration

Most settings are managed visually in **Settings**, but everything is stored in a single JSON file
you can also edit directly.

---

## Files & locations

| Path | Contents |
|---|---|
| `~/.agentos/config.json` | all settings (below) |
| `~/.agentos/agentos.db` | SQLite: conversations, memory, tasks, apps, app data, logs, knowledge graph, skills, snapshots metadata |
| `~/.agentos/soul.md` | the agent's persistent identity |
| `~/.agentos/wallpapers/` | generated wallpapers (the gallery) |
| `~/.agentos/snapshots/` | restore points |
| `~/AgentOS/` | the agent's working directory / sandbox root (reports in `~/AgentOS/reports/`) |

Override the config/data location with the `AGENTOS_HOME` environment variable.

---

## `config.json` keys

| Key | Meaning |
|---|---|
| `providers` | model providers — `ollama`, `anthropic`, `openai`, `openrouter`, `custom` (each with `enabled`, `base_url`, `api_key`, `models`) |
| `default_model` | the active model id, e.g. `ollama/qwen3.5:9b` |
| `agent_name` | what the agent calls itself (default **Aria**) |
| `autonomy` | `paranoid` \| `balanced` \| `full` |
| `max_steps` | maximum tool steps per turn |
| `steer_queued_messages` | when you type again mid-turn, let the running turn decide whether that message belongs to the run in flight (default `true`; `false` = every queued message waits its turn) |
| `steer_triage_timeout` | seconds that decision may take before the message's wording decides instead (default `30`) |
| `workspace` | the agent's working directory (default `~/AgentOS`) |
| `port` | server port (default `8321`) |
| `sandbox` | `{ enabled, root }` — the folder jail (see below) |
| `policies` | list of `{ action: "allow"｜"deny", match: "pattern *" }` rules |
| `mcp_servers` | connected MCP tool servers |
| `telegram` | `{ enabled, bot_token, owner_chat_id }` |
| `widgets` | pinned desktop widgets |
| `memory` | `{ auto_extract, model, inject_user, inject_session, inject_facts, embed_model, rollup_after_hours, kg_dedup }` — auto-learn mines every chat turn for user memories, session memories, and knowledge-graph facts, and applies corrections/retractions. `model` picks the extraction model (empty = `default_model`; a small fast model works well). `inject_*` counts control how many of each go into the system prompt. `embed_model` enables semantic recall (empty = auto-detect an installed Ollama embedding model such as `nomic-embed-text`). `rollup_after_hours` distills idle conversations' session memory into user memory (0 disables). `kg_dedup` periodically merges duplicate graph entities |

Edit through the UI when possible; the agent can also change most of these with its
`configure_agentos` tool. If you edit the file by hand, restart the service
(`systemctl --user restart agentos`).

---

## Providers

Each provider entry looks like:

```json
"anthropic": {
  "enabled": true,
  "base_url": "https://api.anthropic.com",
  "api_key": "sk-…",
  "models": ["claude-sonnet-4.5", "…"]
}
```

`ollama` needs only a `base_url` (default `http://localhost:11434`) and discovers models
automatically. API keys can also come from environment variables — see [Models](models.md).

---

## The sandbox

```json
"sandbox": { "enabled": true, "root": "" }
```

When enabled (and `bubblewrap` is installed), the agent's shell/file tools and the Terminal are
confined to `root` (defaults to the workspace). Outside that folder the filesystem is read-only and
other home directories are hidden. Turn it on/off and set the folder in **Settings → Sandbox**.

---

## Policies

```json
"policies": [
  { "action": "allow", "match": "run_command git *" },
  { "action": "deny",  "match": "run_command *rm -rf*" }
]
```

Patterns use `*` wildcards and are matched against `<tool> <command-or-args>`. **Deny wins** over
allow, and hard-blocked destructive commands stay blocked regardless. Manage these in the **Policies** app, or click **"Always allow"** on any approval prompt.

---

## Autonomy & steps

- `autonomy` controls whether risky actions ask first (`paranoid`/`balanced`) or run automatically
  (`full`). Destructive commands are always blocked.
- `max_steps` caps how many tool steps the agent takes per turn (a safety limit against loops).
