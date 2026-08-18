# Security & threat model

An agent with real hands needs a real trust story. AgentOS's posture: **secure by default,
visible by design** — the 2026 wave of self-hosted agents showed exactly how this goes wrong
(exposed gateways on 0.0.0.0, no auth, unvetted marketplaces, blanket-trusted commands), and
AgentOS is built to be the opposite of that story.

## Trust boundaries

| Boundary | Default | Notes |
|---|---|---|
| Network | binds `127.0.0.1` only | nothing is reachable from the LAN until you deliberately open it. [Remote access](remote-access.md) is the only way, it is off by default, and it refuses to enable without a passphrase — `--host 0.0.0.0` alone exits with an error rather than serving an unauthenticated shell |
| Remote sessions | passphrase + signed cookie | PBKDF2-SHA256 (210k rounds), never the passphrase itself; the cookie is `HttpOnly`, `SameSite=Lax`, and `Secure` over a tunnel; failed attempts back off per source address; the switch itself is only reachable from loopback, so nothing signed in remotely can widen its own access |
| WebSocket handshakes | origin-checked before auth | every socket (`/ws`, `/ws/terminal`, `/ws/vnc`) passes one gate that refuses a cross-origin — or `null` — Origin, closing the Cross-Site WebSocket Hijacking path a foreign page would otherwise use to reach the shell socket. A browser sets Origin and cannot forge it; a non-browser client with no Origin carries no cookie jar and is left to the auth gate |
| Clickjacking | the desktop cannot be framed | the desktop's one-click Allow/Deny grants real capability, so it ships `frame-ancestors 'none'` + `X-Frame-Options: DENY`; an app page ships `frame-ancestors 'self'` so only its own desktop may embed it. `nosniff`, `no-referrer`, `same-origin` opener, and HSTS-over-TLS are on every response |
| Filesystem | OS sandbox ON | agent commands and file tools are jailed to the workspace **plus any safe folders you name** (`sandbox.folders` — see [Configuration](configuration.md#safe-folders)). Linux: **bubblewrap** (whole FS read-only, `/home` hidden). macOS: **sandbox-exec** (whole FS readable, writes confined to those folders + tmp/caches). Same guarantee — the agent's shell cannot modify files outside them. A folder holding another account is refused, so widening the jail can never breach account isolation |
| Capabilities | one policy decision point | every tool/model/MCP/skill/app-data access, for every principal (you, apps, subagents, workflows), flows through the PDP: allow / ask / deny + persisted, revocable grants |
| Shell | risk-classified | read-only commands run free; mutating commands ask; destructive patterns are hard-blocked and non-overridable. `git push`, config writes, and remote changes ask |
| Secrets | masked & env-injected | API keys and the GitHub token are masked in the API; git auth goes through an askpass helper — tokens never enter command lines, remotes, or logs |
| Self-modification | snapshot + AST + **test gate** | the OS snapshots itself before any source write, refuses syntax errors, and refuses to restart if the test suite fails |
| Managed services | loopback-only | TrainForge (no auth of its own) is always started on `127.0.0.1` |

## IO gates: surface-scoped permissions

Every capability call arrives via one of the OS's **surfaces** — `gui` (the desktop and its
apps), `tui` (the terminal UI), `telegram` (the channel bridge), `api` (headless REST), and
`task` (scheduled jobs). These are the permission framework's **import/export gates**: a grant
can be scoped to a subset of them in the Permissions app (the ⛩ badge on any rule, or the
"IO gates" picker when attaching one).

- A rule with gates `*` (the default) behaves exactly as before — it applies everywhere.
- A scoped rule only applies to calls arriving via its gates. If consent exists but not for
  the current surface, the call is **denied** and an `io-gate` entry lands in Logs (kind
  `policy`, plus an explicit `error` entry) — permitted on all the surfaces means it flows;
  anywhere else the IO errors out, visibly.
- Example: grant an app `mcp.use · mcp:github/*` scoped to `gui` and the same capability is
  refused when a turn arrives over Telegram.

Deny rules scope the same way, so "allowed everywhere except over Telegram" is one allow rule
plus one telegram-scoped deny.

## Agents that start agents

A conversation can hand work to a specialist, and build one when none fits. Both are
capabilities in their own right, decided by the same gate as everything else.

![Approving a delegation: the card names the agent, the model it runs on, its step and time budget, and the exact tools and skills its definition grants it](screenshots/agent-approval.png)

| The step | The action | The default |
|---|---|---|
| build a specialist | `agent.write` · `agent:subagent/<name>` | **only the user's own agent** — apps, subagents, workflows and flows are refused by a built-in deny that no grant can override |
| start one | `agent.invoke` · `agent:subagent/<name>` | **asks the first time**, then remembered per agent |
| what it then does | its own tools, skills and grants, as `subagent:<name>` | its definition is the ceiling; every call is its own audit row |

Three consequences worth knowing:

- **Defining an agent grants nothing.** The definition only says what that agent *would*
  hold; the first invocation is what asks. That is what makes it safe for the agent to build
  a specialist without interrupting you — the same reason a drafted flow is safe because it
  is created disabled.
- **The approval is per agent, not per call.** Approving `researcher` is not approving
  `deploy-bot`. "Allow & remember" writes `agent.invoke agent:subagent/researcher` and
  nothing wider, and it is revocable in Permissions like any other grant.
- **Unattended, it is refused rather than acquired.** A scheduled task has nobody to ask, so
  the ask ends in a denial with the reason in the ledger. Something running alone must not be
  able to pick up an actor you never approved. Approve it once at the desk and the job works
  from then on.

An agent may never start or define another one — enforced by the gate, not by a counter, which
is what keeps the tree exactly two deep. The one exception is a flow's master orchestrator,
whose whole purpose is delegation, and it may only reach the agents on its own roster.

## The taint ceiling: what a fetched page is allowed to cause

Grants answer *who is asking*. They cannot answer *on whose say-so* — and those are
different questions. A web page, an MCP server's reply or another agent's answer can all
contain text shaped like an instruction, and no model reliably tells that apart from what
you typed. Prompt injection is not a bug to be patched; it is a property of putting
untrusted text and trusted text in the same context window.

So AgentOS does not try to detect the attack. It bounds the blast radius:

- Output from `fetch_url` and any `mcp_*` tool is **fenced** before the model
  sees it (`<untrusted source="…">`), and the system prompt states that instructions inside a
  fence are content to report on, never to obey.
- Once a turn has read untrusted content it is **tainted for the rest of the turn**, and a
  tainted turn's *risky* steps are held for you — **at `full` autonomy too**, because full
  autonomy is trust placed in your instructions, not a stranger's. Safe steps are never
  escalated, so reading and researching stay as fast as they were.
- The ceiling is checked **before grants**, exactly like the read-only channel ceiling.
  "Allow `fetch_url` everywhere" is consent for the agent to fetch pages; it is not consent
  for a fetched page to spend the grant on something else. For the same reason the approval
  card offers no "allow & remember" — remembering it would hand the next page the same key.
- Taint survives a turn boundary: a conversation whose history contains fenced content starts
  its next turn tainted. "Fetch this page" … "ok, go ahead" is the obvious way around a
  per-turn rule.
- Settings → Agent → *Content from outside* (or `security.taint`, or `agentos` TUI → Config):
  `ask` (default), `strict` (refuse to change anything for the rest of the turn), `off`.

The chat marks the step that brought the outside world in, so you can see which tool call
tainted the turn. `tests/test_taint.py` holds the guarantees, including the end-to-end case
where the page says "run this", the model obeys, and the OS still stops to ask.

**What this does not do.** It does not stop a model being *fooled* — a page can still make an
agent summarise it wrongly or draw a false conclusion, and a tainted turn's *safe* tools
(reading files, searching) still run freely. `read_file` is deliberately not a tainting tool:
your own disk is yours, and marking every file read untrusted would escalate half the turns
in the OS and train you to click through the prompt. A file you downloaded is the honest gap
that leaves, and closing it needs provenance on the file rather than on the tool.

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
