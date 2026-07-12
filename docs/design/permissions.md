# The permission framework: one gate for the whole control plane

Every capability in AgentOS — tools, MCP servers, skills, models, app data, agent
invocation — now flows through a single policy decision point (PDP). The PDP knows
**who** is asking (a principal), checks **persisted consent** (grants), and answers
`allow`, `deny`, or `ask`. It is the single source of gate of the control plane:
apps, the main agent, subagents, workflows, scheduled jobs and Telegram turns all
route through the same decision.

## Vocabulary

- **Principal** — who is acting: `user` (the main agent acts as the user),
  `app:<id>`, `subagent:<name>`, `workflow:<name>`. (`agentos/policy.py`)
- **Action** — what kind of thing: `tool.use`, `mcp.use`, `skill.use`, `model.use`,
  `fs.read`, `fs.write`, `net.fetch`, `memory.read`, `memory.write`, `kg.read`,
  `kg.write`, `agent.invoke`, `app.data.read`, `app.data.write`.
- **Resource** — the specific thing, fnmatch-patterned:
  `tool:run_command git *`, `mcp:github/create_issue`, `skill:webapp-testing`,
  `model:anthropic/*`, `fs:/home/x/AgentOS/*`, `net:https://api.github.com/*`,
  `agent:subagent/researcher`, `app:<id>/data`.
- **Grant** — one persisted consent rule (`grants` table in `agentos/memory.py`):
  principal + action pattern + resource pattern + effect (allow/deny) + source
  (`manifest` | `user` | `legacy` | `auto`) + note. Soft-revoked (`revoked_at`),
  so the audit trail survives. The PDP caches live grants in memory and
  invalidates on any write (`Store.grants_version`).

## Decision order (first hit wins) — `PDP.decide()`

1. **Hard blocks** — `BLOCKED_PATTERNS` and legacy deny policies (folded into
   `risk == "blocked"` by `Toolbox.risk_of`). Never overridable.
2. **Built-in denies** — apps/subagents may never self-modify the OS
   (`configure_agentos`, `update_soul`, `develop_agentos`, `restart_agentos`,
   `snapshot_os`); subagents/workflows may never re-delegate (`agent.invoke`).
   Not revocable, not grantable — same spirit as the hard blocks.
3. **Deny grants** — deny wins over allow.
4. **Allow grants** — an explicit grant *satisfies the approval requirement*:
   consent already happened when the grant was written, so no re-prompt.
5. **Defaults by principal kind** —
   - `user`: today's autonomy semantics, byte-for-byte (safe runs; risky asks
     unless autonomy is `full`; the legacy `cfg["policies"]` fnmatch rules keep
     working through `risk_of`, as global rules for every principal).
   - `app`: safe/read-only actions run; anything else → `ask` (a consent card
     with **Allow & remember**, which writes a principal-scoped grant).
   - `subagent`/`workflow`: autonomy semantics with the *effective* (capped)
     autonomy; headless runs resolve `ask` to deny unless effective autonomy is
     `full` (the pre-existing `headless_approver` behavior).
   - `model.use` defaults to allow for everyone; restrict per principal with
     deny grants (e.g. `deny model.use model:anthropic/*` for a subagent).

`risk_of` stays the **risk classifier**; the PDP is the **decider**.

## App identity

Serving `/api/apps/{id}/page` mints a runtime token injected as `window.APP_TOKEN`;
`appTool()`/`appData` send it as `X-App-Token`. The server maps token → app
principal (`_principal_of`). Requests without a token act as the user (the UI
shell, curl). Revocation doesn't need token expiry — the PDP reads live grants.

Gated surfaces: `POST /api/tool`, `GET/PUT /api/apps/{id}/data` (cross-app needs
an `app.data.*` grant; own data is always allowed), `POST /api/chat`
(`agent.invoke`, and the whole turn runs as the app principal). A middleware
backstop (`app_privilege_guard`) refuses app-originated requests to sensitive
REST (`PUT /api/config`, `PUT /api/mcp`, grants CRUD, snapshots, …). Read-only
REST and `/ws` are not app-gated in v1 (single-user, same-origin, sandboxed
iframes) — tightening that is v2 (`api:` resources on grants).

## Consent flows

- **Runtime** (`server.request_approval`, a global broker): an ungranted call
  raises the approval card; **Allow & remember** persists a sensibly-generalized
  grant (`PDP._offer`) for that principal only. Main-agent (`user`) approvals
  keep the old global "Always allow" policy button.
- **Install-time** (`showConsent` in the UI): manifest permissions render with
  required/optional toggles; approving writes `source=manifest` grants and
  retires any legacy grant (`/api/apps/{id}/manifest/approve`).
- **Revocation** (Permissions app → `DELETE /api/grants/{gid}`): immediate —
  the PDP reads live; open app iframes reload on revocation broadcasts.

## Manifests

Stored on `user_apps.manifest` (+ `manifest_status`: `none|proposed|approved`):

```json
{"format": 1, "name": "PR Board", "description": "…",
 "permissions": [{"action": "mcp.use", "resource": "mcp:github/*",
                   "reason": "list PRs", "required": false}],
 "prerequisites": {"mcp_servers": [{"name": "github", "transport": "http",
                    "url": "…", "headers_template": {"Authorization": "<your value>"}}],
                   "skills": [{"name": "webapp-testing", "source": "https://…SKILL.md"}]}}
```

Sources of manifests:
- **The App Builder declares one** — `create_app(permissions=…)`; the persona
  instructs it to declare every capability the app uses.
- **Auto-proposed** — `_propose_manifest`: static scan of the app HTML
  (`appTool('x')`, `appData`, `/api/chat`) plus mining of the app's own tool
  logs (logs carry `app_id` now). Historical logs predate per-app identity, so
  the source scan leads.
- **Legacy migration** — a one-time startup pass (`permissions_migrated` flag in
  config) gives every pre-existing app a *visible* legacy full-access grant and
  a proposed manifest; approving the manifest swaps legacy for scoped grants.

Subagents are governed by the same PDP (principal, built-in denies, model
restrictions, ask-remember when a human is present via `@mention`). Their
`tools` row remains the schema-shaping allow-list; we deliberately do **not**
auto-convert it to allow grants — that would auto-approve risky actions the
autonomy cap currently gates.

## Packages (distribution)

`GET /api/apps/{id}/export` → a single `*.agentapp.json`:

```json
{"format": "agentos-app/1", "manifest": {…}, "html": "…",
 "checksum": "sha256:<canonical-manifest + \n + html>", "signature": null}
```

Secrets never leave the OS: MCP prerequisites carry `env_template` /
`headers_template` placeholders only. Import is two-phase:
`POST /api/apps/import` verifies format + checksum and stages the package
(returns `install_id`, the manifest, missing prerequisites, name conflicts);
`POST /api/apps/import/{iid}/confirm` installs with exactly the accepted grants,
adds opted-in MCP servers **disabled** (user fills keys in the MCP app first)
and installs opted-in skills via the existing skill installer. `signature` is
reserved for a future ed25519 signing scheme (checksum-only in v1: integrity,
not authorship).

## Files

- `agentos/policy.py` — Principal, Decision, `action_of`, PDP (new)
- `agentos/memory.py` — `grants` table + Store methods; `user_apps.manifest*`
- `agentos/agent.py` — principal plumbing; the tool-loop gate; model gate;
  grant-aware schema filtering
- `agentos/server.py` — approval broker, `_principal_of`, privilege guard,
  grants CRUD, manifest propose/approve, export/import, legacy migration
- `agentos/fabric.py` — subagent principals; model restriction fallback
- `agentos/ui/index.html` — Permissions app, `showConsent`, approval card with
  Allow & remember, Store Import tab, Studio Export/Review
