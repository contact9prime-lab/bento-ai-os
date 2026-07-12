# Design: Subagents & the Execution Fabric

*Status: **F0 implemented ✅** (in-process subagents, visual workflows, control plane,
heartbeats, observability — see §"Control plane & data plane"). L1–L3 (mTLS wire protocol,
docker, remote nodes) remain design — see [Roadmap](../roadmap.md), Pillar E.*

---

## 1. The idea

Today AgentOS is one agent on one machine. The next step is a **fabric**: a parent AgentOS
that can delegate work to **subagents** running in progressively stronger isolation —
j
```
parent AOS ──delegate──▶ persona      (same process, restricted tools)      L0
           ──delegate──▶ sub-AOS      (separate process, own workspace)     L1
           ──delegate──▶ docker AOS   (container, throwaway filesystem)     L2
           ──delegate──▶ remote AOS   (another machine, mTLS)               L3
```

One mental model everywhere: **a subagent is an AgentOS turn executed elsewhere.** The same
task envelope, the same result envelope, the same audit trail — only the isolation level and
transport change. L0 runs in-process; L1–L3 all speak the same wire protocol over mTLS.

Why this matters (product): heavy jobs stop blocking the desktop; untrusted work (community
skills, scraping, code execution) runs in a container that is destroyed afterwards; a laptop
can delegate to a heavy homelab GPU box; and "a staff, not a bot" (Roadmap Pillar E) gets its
execution substrate.

---

## 2. Concepts

### Subagent (definition, not instance)
A named worker with an identity and a contract, stored in a new `subagents` table and
manageable in a **Team app**:

```jsonc
{
  "name": "researcher",
  "soul": "…persona markdown…",          // its own soul, NOT the parent's
  "model": "ollama/qwen3.5:9b",          // may differ from the parent's model
  "tools": ["fetch_url", "read_file", "save_report"],   // allow-list, nothing else
  "skills": ["deep-research"],           // skills bound to this subagent
  "memory": "read-user",                 // none | read-user | read-write-user
  "autonomy_cap": "balanced",            // can never exceed the parent's level
  "target": "docker",                    // local | subprocess | docker | node:<id>
  "budget": {"max_steps": 15, "max_seconds": 600, "max_tokens": 200000}
}
```

### Task envelope (what crosses the boundary)
Delegation is **explicit data transfer, never shared state**. The child sees only what the
envelope carries:

```jsonc
{
  "id": "tk_9f2c…",                      // idempotency key — replays return the cached result
  "task": "Research X and produce a report",
  "subagent": { …definition above… },    // the contract travels with the task
  "context": {
    "memories": ["…relevant user memories, filtered by semantic recall…"],
    "facts": ["Piyush —works at→ Accacia"],
    "files": [{"name": "input.csv", "sha256": "…", "bytes": "…base64 or fetch-ref…"}]
  },
  "skills": [{"name": "deep-research", "version": "1.2.0", "content": "…md…"}],
  "policy": {"autonomy": "balanced", "deny": ["run_command sudo *"], "sandbox": true},
  "deadline": 1783750000.0
}
```

### Result envelope
```jsonc
{
  "id": "tk_9f2c…",
  "status": "ok | error | timeout | denied",
  "content": "…final text…",
  "steps": [ …tool trace, same shape the UI already renders… ],
  "artifacts": [{"name": "report.html", "sha256": "…", "bytes": "…"}],
  "memory_proposals": [{"scope": "user", "content": "…"}],   // parent DECIDES, child proposes
  "usage": {"input": 0, "output": 0, "seconds": 42}
}
```

Two invariants worth stating loudly:
- **Memory is proposed, not written.** A child never writes to the parent's store; it returns
  `memory_proposals` which the parent's normal dedup/supersede pipeline accepts or drops.
- **Secrets never enter an envelope.** The vault (Roadmap Pillar D) stays parent-side; if a
  child needs an authenticated call, the parent performs it and passes the *result*.

### Skills as the unit of capability
Skills already exist (SQLite, installable from git/URL). In the fabric they become the
delegation currency: a subagent's `skills` list is shipped inside the envelope
(version-pinned content, not a reference), so a child needs no store access and two runs of
the same task are reproducible. When the registry lands (Roadmap Pillar G), envelopes may
reference signed bundles instead of inlining.

---

## 2b. Control plane & data plane  *(implemented ✅ at L0 — `agentos/fabric.py`)*

The fabric separates **who decides** from **who executes**:

```
        CONTROL PLANE  (the main AOS: UI + API + ControlPlane)
        ├─ owns definitions: subagents, workflows (visual DAG in the Team app)
        ├─ owns the MODEL PLANE: resolves which LLM each run gets
        │    step.model  →  subagent.model  →  default_model      ("smartness flows down")
        ├─ starts / cancels runs, sets budgets
        └─ collects telemetry: heartbeats, steps, faults, usage
              ▲│                    ▲│
   data→ctrl  ││  ctrl→data  … two-way traffic, per run
              │▼                    │▼
        DATA PLANE (one per running subagent, even at L0)
        ├─ sidecar heartbeat task (5s beat; stale > 15s flags in UI)
        ├─ emits step / log / fault events as they happen
        └─ reaches LLMs ONLY through the control plane's provider config
           (L0: in-process resolve · L1+: POST /api/plane/llm over mTLS)
```

Consequences, all implemented at L0:

- **Heterogeneous smartness** — each workflow step can pin a model
  (`step.model` > `subagent.model` > inherit), so *generation on Ollama, validation on
  Claude* is a two-line workflow definition; equally, everything can share one LLM by
  leaving models on *inherit*.
- **Hierarchy** — data planes never choose their own model or hold provider keys; the
  control plane's config is the single source of model access (`/api/plane/llm` is the
  callback surface L1–L3 workers will use over mTLS).
- **Two-way traffic** — control→data: start, cancel (`POST /api/fabric/runs/{id}/cancel`),
  budgets, resolved model; data→control: heartbeats, per-tool step events, faults, token
  usage — persisted to `fabric_runs`/`fabric_events` and mirrored live to the UI websocket.
- **Observability covers L0 / the current setup too** — the Team app's Observability tab
  shows faults / performance / tokens *per data plane*, with the main agent reported as its
  own plane from the same pane (turn + error logs). Live instances show heartbeat age and a
  STALE flag.
- **Guardrails** — child autonomy = `min(parent, cap)`; risky tools auto-denied unless
  effective `full` (no human inside a data plane); fabric-management and self-modification
  tools are stripped from every child allow-list (no recursive delegation at L0).
- **Standing on the OS's shoulders** — every L0 data plane always gets `use_skill`, `recall`,
  `kg_query`, and `remember` in addition to its allow-list, and its system prompt carries the
  user memory + (when delegated from a chat) that conversation's session memory. Delegation
  from a conversation flows the conversation id down automatically, so a subagent works with
  the same context the main agent has — and what it `remember`s lands in the same store.

Implemented surface: `subagents`/`workflows`/`fabric_runs`/`fabric_events` tables ·
`ControlPlane.run_subagent/run_workflow/cancel/live_instances` · REST CRUD + run/cancel/
observability endpoints · `delegate` and `run_workflow` agent tools · Team app (👥) with
subagent cards, a live SVG DAG per workflow, and the observability pane · built-ins seeded
on first boot (researcher / writer / validator + two workflows).

---

## 3. Execution targets

| Level | Target | Isolation | Transport | Use case |
|---|---|---|---|---|
| L0 | `local` | tool allow-list + persona (mechanism ✅ — `Agent(extra_system, tool_filter)` powers App Builder today) | in-process call | cheap specialists, parallel fan-out |
| L1 | `subprocess` | own process, own `AGENTOS_HOME`, own sandbox root | loopback HTTPS + mTLS | heavy jobs off the main loop; different model server |
| L2 | `docker` | container, throwaway fs, egress policy | HTTPS + mTLS to container | untrusted skills, scraping, code execution |
| L3 | `node:<id>` | another machine entirely | HTTPS + mTLS over LAN/tailnet | GPU box, office server, always-on pi |

**L1–L3 are the same thing** — a headless AgentOS exposing `/api/fabric/*` — differing only
in how they are started and where the certificate lives. L2 is L1 wrapped in
`docker run --rm -v task-workspace:/work agentos:worker`. L3 is L1 that someone enrolled
from another machine.

### Worker surface (new endpoints, served only over mTLS)
```
POST /api/fabric/execute     task envelope → 202 {task_id}
GET  /api/fabric/tasks/{id}  status + (when done) result envelope
WS   /ws/fabric/{id}         live step events (the parent mirrors them into its UI)
POST /api/fabric/cancel/{id}
GET  /api/fabric/health      load, models available, version
```

---

## 4. Identity & trust: mTLS everywhere

The fabric trusts **certificates, not networks**. Every parent is a CA; every worker holds a
cert issued by the parent it serves.

### PKI layout (`~/.agentos/pki/`)
```
ca.crt  ca.key          # per-install root CA, generated on first fabric use (never leaves)
host.crt host.key       # this node's own cert (client AND server usage)
issued/<node-id>.crt    # certs this node has issued to its workers
revoked.json            # serials this parent no longer accepts
```

### Enrollment ("mTLS-based creation")
Creating a worker *is* issuing it a certificate — there is no other registration state:

```
parent                                   worker (fresh AOS, docker, or remote)
──────                                   ──────
1. UI: "Add node" → one-time token
   (agentos fabric enroll-token, 10 min TTL, single use)
2.                                       agentos fabric join https://parent:8321 --token …
                                         → generates keypair, sends CSR + token
3. verifies token, signs CSR
   → returns worker cert + ca.crt
4. stores node in `nodes` table         stores parent CA; serves /api/fabric/* with
   {id, name, url, cert_serial, caps}    client-cert-required TLS
```

- **Docker workers** skip steps 1–2: the parent generates the keypair itself and injects
  cert+key via mounted tmpfs at `docker run` time — the container is born enrolled and its
  cert dies with it (TTL = task deadline).
- **Rotation**: workers re-CSR automatically at 2/3 of cert lifetime (default 90 days).
- **Revocation**: removing a node in the Team app adds its serial to `revoked.json`; the
  parent's TLS client rejects it thereafter. No CRL distribution needed — the parent is the
  only client that matters.
- Python side: `ssl.SSLContext` with `load_cert_chain` + `load_verify_locations` +
  `verify_mode=CERT_REQUIRED` on both ends (uvicorn `ssl_*` kwargs / httpx `cert=` + `verify=`).
  Certificate issuance via the `cryptography` package (new dependency, worker-optional).

### Authorization on top of authentication
The cert answers *who*; the envelope's `policy` answers *what*. A worker enforces the
envelope policy **and** its own local policy — whichever is stricter wins (`autonomy_cap`,
deny rules, sandbox always-on for L2). A parent's `full` autonomy does **not** propagate: the
child's effective autonomy is `min(parent_grant, subagent.autonomy_cap, worker_local_cap)`.

---

## 5. Parent-side experience

- **`delegate` tool** — the agent itself decides to farm work out:
  `delegate(subagent="researcher", task="…", wait=false)` → task id; results arrive as a
  turn event + notification, steps streamed into the chat like local tool cards (via
  `WS /ws/fabric/{id}` mirroring).
- **Team app (🧑‍🤝‍🧑)** — subagent definitions, enrolled nodes with health/load, running
  tasks with live step feeds, cost per subagent (extends Token Analytics).
- **Scheduler integration** — scheduled jobs gain an optional `subagent` field, so recurring
  heavy jobs run off-box by default.
- **Audit** — every delegation logs envelope hash, node id, cert serial, and result status on
  *both* sides; the parent's Logs app shows fabric events under a `fabric` kind.

---

## 6. Failure model

| Failure | Behavior |
|---|---|
| worker unreachable | task stays `queued` with backoff; after `deadline`, status `timeout`; optional fallback: run at a lower level (docker → local) **only if** the subagent's `tools` are all safe |
| worker dies mid-task | parent detects via WS drop + health poll; re-dispatch is safe (envelope `id` is an idempotency key — workers cache results by id) |
| cert expired/revoked | TLS handshake fails → surfaces as `denied` with a one-click "re-enroll" in the Team app |
| result too large | artifacts over a size cap return as fetch-refs the parent pulls over the same mTLS channel |
| child asks for approval | L0 bubbles to the parent's normal approval UI; L1–L3 have no human present: risky actions are auto-denied unless the envelope policy pre-approved that exact pattern |

---

## 7. Build phases

| Phase | Scope | Notes |
|---|---|---|
| **F0 — personas** ✅ | `subagents` + `workflows` tables, ControlPlane (heartbeats, telemetry, model plane), Team app with visual DAG, observability pane, `delegate`/`run_workflow` tools, built-in subagents | shipped — see §2b |
| **F1 — wire protocol** | task/result envelopes, `/api/fabric/*`, `agentos serve --worker`, PKI + enroll token flow, L1 subprocess target; workers call back to `/api/plane/llm` (already live) for models | the mTLS core lands here |
| **F2 — docker** | `agentos/worker` image, tmpfs cert injection, egress policy, auto-destroy | unlocks safe execution of untrusted skills |
| **F3 — remote nodes** | `agentos fabric join`, node health, Team-app node management, scheduler `subagent` field | LAN/tailnet; the homelab story |
| **F4 — polish** | result artifact refs, cost attribution, re-enroll UX, fallback chains | |

Suggested placement: **F0 next** (it is small and pays for itself), F1–F2 after the
Automations app ships, F3+ later.

---

## 8. Open questions

1. **Model access from containers** — does an L2 worker reach the host's Ollama
   (`host.docker.internal`, egress-allowed) or bundle its own weights? Leaning host-Ollama
   with an explicit egress allow-list entry; weights-in-image only for air-gapped nodes.
2. **Memory slice selection** — how much user memory rides in `context.memories`? Leaning:
   semantic top-k against the task text (the recall machinery from memory v2), capped small.
3. **Skill trust tiers** — should L0 refuse unsigned community skills that L2 would accept?
   Leaning yes once the registry (Pillar G) exists: unsigned ⇒ docker-only.
4. **Fan-out limits** — max concurrent delegations per parent and per node, and how they
   surface in the UI (probably Team app + a `fabric` section in Control).
5. **NAT traversal for L3** — out of scope; assume LAN or user-provided tailnet/VPN.
