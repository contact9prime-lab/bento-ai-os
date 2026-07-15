# Hermes — companion agent & wrapped engine

Hermes (Nous Research's self-hosted assistant, MIT) is itself an agent. AgentOS treats it two
ways, both from the **Hermes** app (🜁 on the desktop):

## 1. As an alternative chat engine

Open **Agent Chat**, and in the model dropdown pick **🜁 Hermes agent** (shown when Hermes is
installed). That conversation's turns now run through Hermes instead of the built-in Aria
agent — with AgentOS's working indicator, Stop button, and history persistence intact. Switch
back to any model to return to Aria. This is a per-conversation choice; it is never saved as
your global default (background jobs keep using their own model).

## 2. As a control surface (AgentOS wraps Hermes)

The **Hermes** app lets you manage Hermes entirely from AgentOS:

- **Download Hermes (MIT)** — if it isn't installed, one click clones it from `hermes.repo`
  into `~/.hermes/hermes-agent`, provisions its virtualenv, installs it, and symlinks the CLI
  so AgentOS and your shell can find it. Progress streams live. (A few minutes, one-time.)
- **Config editor** — read and edit `~/.hermes/config.yaml` (default model/provider, providers,
  toolsets, personalities) right in the app. Saves are **YAML-validated** first and keep a
  `.bak`, so a bad edit can't corrupt the file. **API keys live in `~/.hermes/.env` and are
  never shown or touched here** — Hermes keeps its own secrets.
- **Gateway** — start/stop the Hermes messaging gateway.
- **Update** — pull the latest Hermes and reinstall.

## 3. As tools the agent can call

The built-in agent can reach Hermes directly:

- `hermes_status` — installed? gateway running? which model?
- `hermes_ask` — delegate a task to Hermes and get its answer back (a cross-product subagent).
- `hermes_send` — deliver a message through any platform Hermes is paired with — WhatsApp,
  Slack, Discord, Signal, Telegram (`target` like `slack:#ops` or `signal:+15551234567`).

## Configuration

`config.json` → `hermes`:

```jsonc
"hermes": {
  "repo": "https://github.com/NousResearch/hermes-agent.git",  // download source
  "install_dir": "",          // default ~/.hermes/hermes-agent
  "engine_enabled": true      // show Hermes in the chat engine selector
}
```

## Trust

Hermes runs under your own account with its own permission model — delegating to it or sending
through it are approval-gated in AgentOS. AgentOS reads/writes only `config.yaml`, never
Hermes's credentials.
