# The Lifecycle — Train · Test · Operate · Build · Ship · Manage

AgentOS is not a chat box: it is an operating system for the things you and your agent make
together. Everything you make moves through six lifecycle pillars, and every pillar lives
*inside* the OS. **Mission Control** (◎ on the desktop) shows all six on one screen, live,
with deep links into each surface.

| Pillar | What it means | Where it lives |
|---|---|---|
| 🧬 **Train** | Fine-tune and evaluate your own models, locally | The **Train** app (TrainForge) · `train_*` agent tools |
| 🧪 **Test** | Prove things work before they ship or go live | `tests/` suite · `run_tests` tool · the self-modification test gate |
| ⚙ **Operate** | Keep things running unattended | **Scheduler**, **Team** (fabric observability), **Logs**, Telegram alerts |
| 🔨 **Build** | Make software: apps, projects, the OS itself | **App Studio**, `create_app`, `develop_agentos` |
| 🚀 **Ship** | Version and publish what you built | `git_*` tools, `export_app_to_git`, app packages, the `.deb` |
| 🛡 **Manage** | Govern who may do what | **Permissions** (PDP + grants), **Policies**, autonomy, **Snapshots**, sandbox |

## Train

The Train pillar is powered by **TrainForge**, a self-hosted training platform managed by
AgentOS as a local service (loopback-only). From the **Train** app — or by just asking the
agent — you can:

- import datasets (Hugging Face Hub search, URL, upload),
- fine-tune models: tabular (sklearn), text classification (Transformers), and
  **causal-lm — LoRA fine-tunes of language models on your own GPU**,
- watch live loss curves and logs,
- call every trained model as a live endpoint (that's your Test loop for models),
- publish to the Hugging Face Hub.

See [training.md](training.md) for the full guide, including the loop that matters most:
*your data → a LoRA fine-tune → an Ollama model → your agent answering with it.*

## Test

- **The OS tests itself.** `tests/` holds the pytest suite; the agent's `run_tests` tool runs
  it (or any project's suite in your workspace).
- **The self-modification gate:** `develop_agentos(..., restart=true)` and `restart_agentos`
  refuse to restart if the suite fails — a self-modification that breaks the tests cannot go
  live. (Snapshots remain the recovery hatch.)
- **Built apps are validated before install:** the App Studio pipeline structurally validates
  every generated app (truncation, unclosed tags, script leaks) and runs a repair pass;
  anything it can't fix ships as an explicit warning, never a silent success.
- `agentos doctor` checks the environment itself: port conflicts, duplicate instances,
  crash-looping services, Ollama reachability and VRAM pinning, DB integrity, network exposure.

## Operate

The mature pillar: the **Scheduler** runs headless agent jobs on intervals; the **Team** app
shows every subagent and workflow run with heartbeats, faults, and token telemetry; **Logs**
records every tool call and policy decision; Telegram delivers results and approvals anywhere.
Mission Control surfaces the 24-hour pulse (turns, errors, running work).

## Build

**App Studio** turns a sentence into an installed desktop app, with versions and rollback.
Builds stream honest progress (including failed tool calls), survive page reloads, always end
in an explicit done/error, and validate completeness before install. The agent can also modify
AgentOS's own source (`develop_agentos`) behind a snapshot + syntax check + test gate.

## Ship

- **Git-first**: the agent has structured git tools — `git_init/commit/diff/log/branch/push/
  pull/clone`. Reads run free; local commits inside the workspace run free; pushes and
  remote changes ask for approval.
- **`export_app_to_git`** turns any app you built into a real project folder
  (`workspace/projects/<name>` with README + manifest), committed, and optionally pushed to a
  GitHub repo it creates for you (Settings → GitHub token).
- App **packages** (`.aos` export/import with checksums) and the self-contained **`.deb`**
  cover distribution of apps and of the OS itself.

## Manage

One policy decision point governs every capability — tools, models, MCP servers, skills, app
data — for every principal (you, apps, subagents, workflows), with persisted grants, audit
logs, autonomy levels, the bubblewrap sandbox, and one-click snapshots. See
[design/permissions.md](design/permissions.md).
