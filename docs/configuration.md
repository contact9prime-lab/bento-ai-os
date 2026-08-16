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
| `security` | `{ taint }` — what a turn may do after reading untrusted content (a fetched page, an MCP reply): `ask` (default, holds risky steps for you even at full autonomy) \| `strict` (refuses them) \| `off`. See [security.md](security.md#the-taint-ceiling-what-a-fetched-page-is-allowed-to-cause) |
| `history` | `{ tool_trace, trace_chars, compact, budget_tokens, model }` — how a conversation is replayed each turn. `tool_trace` replays what earlier turns actually did; `compact` summarises turns that no longer fit the window (off = they are dropped, and you are told); `budget_tokens` 0 derives the budget from the model (`ollama_num_ctx` for local models) |
| `tools` | `{ scope, budget, window_share, cloud_context }` — how many of the ~90 tools are offered per step. `scope: "all"` (default) never narrows; `auto` narrows only on a tight context window. Measured to score slightly worse on a local 9B, so it ships off — check your own model with `agentos eval` |
| `pricing` | `{ "<model-glob>": {in, out} }` — USD per **million** tokens, used by the cost ledger (`agentos usage`, `/api/usage`). Overrides the shipped table; a model with no match is recorded in tokens only, never as $0 |
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
"sandbox": { "enabled": true, "root": "", "folders": [] }
```

When enabled (and `bubblewrap` is installed), the agent's shell/file tools and the Terminal are
confined to `root` (defaults to the workspace). Outside that folder the filesystem is read-only and
other home directories are hidden. Turn it on/off and set the folder in **Settings → Sandbox**.

### Safe folders

`folders` is the list of **other** places the agent may read and write. The jail has one root and
that root is the workspace, which is not where your data lives — so "summarise last quarter's
invoices" used to begin with copying them into the workspace first. Naming the folder is the
alternative:

```
bento config sandbox.folders '["/data/reports", "/srv/shared"]'
```

or one per line in **Settings → Sandbox → Safe folders**. They apply to the file tools, `run_command`
and the Terminal alike — a folder the agent can read but the Terminal cannot would be a difference
nobody could explain.

Two entries are always refused, and `bento doctor` names any that are:

- **`/`** — naming the whole machine would switch the jail off while the toggle still read *on*. If
  that is what you want, turn the jail off and it will say so.
- **Anything holding the accounts** (`~/.agentos/users`, a home inside it, or any directory above
  it). `sandbox` is a machine setting rather than a personal one, so a safe folder is shared by every
  account — which is exactly why this one cannot be named. Otherwise a single line here would undo
  the directory isolation that keeps one account's memory and credentials away from another's. See
  [Users](users.md) and [Tenant isolation](design/tenant-isolation.md).

A folder that does not exist is refused too, with that reason — a mistyped path that was silently
dropped looks exactly like a folder the agent is refusing to use.

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

- **Starting another agent asks once per agent**, at `paranoid` and `balanced`, whatever the
  risk table says — `delegate` is not a "risky command", it is a second actor with its own
  model and its own spending. At `full` it does not ask, like everything else. See
  [Agents that start agents](security.md) for what the approval covers and how it is
  remembered.

---

## Updates

`agentos/VERSION` is the one place a version is written — the package reads it, the
update checker compares against the same file published on `master`, and a test fails if
`pyproject.toml` disagrees. A release is one edit.

```jsonc
"updates": {
  "enabled": true,             // check automatically. Installing is NEVER automatic.
  "branch": "master",
  "check_interval_hours": 24,
  "skipped": ""                // a version you said no to; cleared if you re-enable checks
}
```

When a newer version exists you get a card: **Update now · Later · Skip this version**.
There is deliberately no "install automatically" setting. An agentic OS that could
replace its own code unattended is a different product from the one you agreed to run —
the consent model in [security](security.md) would mean little if the code implementing
it could rewrite itself overnight.

Installing does four things in order, and refuses rather than guessing:

1. **Pull** `origin/<branch>`, fast-forward only. Refused if the checkout has uncommitted
   changes (it would land on top of your work), is on another branch, or is not a git
   install at all — each with a sentence naming which.
2. **Sync dependencies**, only if `pyproject.toml` or `uv.lock` changed.
3. **Verify** against the test suite. If the new version fails its own tests the checkout
   is reset to the commit it started from: a machine that cannot answer is worse than a
   machine one version behind.
4. **Restart the service, then reload every open page** — the code on disk, the running
   service and the page on screen, or you end up looking at the old shell talking to the
   new server.

`GET /api/update` reports the state (`?check=true` to look now); `POST /api/update`
installs and is **loopback-only** — this replaces the code enforcing every other
permission on the machine, so it is not something a remote browser may start.

Your desktop survives it: which windows were open, where, and any unsent message come
back after the reload.

---

## What it costs

Every turn's tokens are recorded, per model, surface, space and conversation:

```bash
agentos usage                 # the last day, by model
agentos usage --days 30 --by day
agentos usage --by surface    # what the phone costs vs the desk
```

Money is only reported for models that have a price. The shipped table covers the common
families and is a convenience, not an authority — it was written on 2026-08-04 and providers
change prices without telling anyone. Correct it, or price a model it does not know, with
`pricing` in `config.json`:

```jsonc
"pricing": {
  "anthropic/claude-sonnet-5": {"in": 3.0, "out": 15.0},   // USD per MILLION tokens
  "mylab/*":                   {"in": 0.5, "out": 1.5}
}
```

Local models are priced at `0` explicitly — "free" and "unpriced" are different answers, and
a turn on an unpriced model is counted in tokens and reported as unpriced rather than folded
into the total as zero. Mission Control shows the last 24 hours; `/api/usage` serves the same
report to anything else.
