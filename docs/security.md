# Security & threat model

An agent with real hands needs a real trust story. AgentOS's posture: **secure by default,
visible by design** — the 2026 wave of self-hosted agents showed exactly how this goes wrong
(exposed gateways on 0.0.0.0, no auth, unvetted marketplaces, blanket-trusted commands), and
AgentOS is built to be the opposite of that story.

## Trust boundaries

| Boundary | Default | Notes |
|---|---|---|
| Network | binds `127.0.0.1` only | nothing is reachable from the LAN; there is deliberately no "expose" flag |
| Filesystem | bubblewrap sandbox ON | agent commands, file tools, and the Terminal are jailed to the workspace; the rest of the FS is read-only, other `/home` files hidden |
| Capabilities | one policy decision point | every tool/model/MCP/skill/app-data access, for every principal (you, apps, subagents, workflows), flows through the PDP: allow / ask / deny + persisted, revocable grants |
| Shell | risk-classified | read-only commands run free; mutating commands ask; destructive patterns are hard-blocked and non-overridable. `git push`, config writes, and remote changes ask |
| Secrets | masked & env-injected | API keys and the GitHub token are masked in the API; git auth goes through an askpass helper — tokens never enter command lines, remotes, or logs |
| Self-modification | snapshot + AST + **test gate** | the OS snapshots itself before any source write, refuses syntax errors, and refuses to restart if the test suite fails |
| Managed services | loopback-only | TrainForge (no auth of its own) is always started on `127.0.0.1` |

## The known trade-offs (read this)

- **Local trust:** the HTTP/WS surface has no authentication — protection is the localhost
  bind. Any process already running as your user can drive AgentOS (including its PTY
  terminal). If your threat model includes hostile local processes, you have bigger problems,
  but know the boundary.
- **Approval fatigue is real:** if you find yourself clicking Allow reflexively, move the
  decision into policy instead — "Allow & remember" writes a scoped, revocable grant, and the
  Permissions app is where consent actually lives. Prefer narrowing the sandbox + grants over
  running at `full` autonomy.
- **Plaintext config:** `config.json` stores keys in plaintext under your user (a secrets
  vault is on the roadmap). File permissions are your last line there.
- **Skills and MCP servers are code you invite in.** Install skills only from sources you
  trust; MCP servers run with your user's rights. App permission manifests + the store's
  checksum flow exist precisely because community marketplaces are the proven attack path.

## Check yourself

```bash
agentos doctor
```

flags: port conflicts and duplicate instances, a crash-looping service, DB integrity, VRAM
pinning — and **network exposure** (e.g. an Ollama configured on `0.0.0.0`, which anyone on
your network can use; set `OLLAMA_HOST=127.0.0.1` unless you truly mean to share it).

## Incident recovery

Snapshots (one click, or automatic before self-modification) capture config + DB + source;
restore rolls the OS back in time. `factory-reset` starts truly fresh. The audit trail
(Logs + the policy ledger) records every tool call and every consent decision.
