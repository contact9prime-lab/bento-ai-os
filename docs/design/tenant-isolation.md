# Tenant isolation — the plan to make AgentOS enterprise-safe

This is the design for the two large pieces that a *mutually-distrusting-tenants*
trust model requires and that the audit found missing. It is written down because
each is a request-layer or deployment-layer change big enough that landing it
blind would break the desktop or the install, and each has a real design choice
that should be visible before the code lands.

The contained fixes from the same audit are already done and on the branch: the
WebSocket user-context bypass, the sustained-rate ceiling, the tamper-evident
ledger with `uid` and an opt-in fail-closed mode, and the space-delete /
factory-reset holes that let the audit trail be erased. What remains are the two
architectural ones.

---

## Where we are: apps are same-origin, so no server check is sound

Verified with a running server:

```
POST /api/grants   (no headers)          → 200, grant written   ← an app self-grants shell
POST /api/setup/reset {"confirm":true}   → 200 (now 403)         ← closed this turn
```

Apps run in `sandbox="allow-scripts allow-same-origin allow-forms"` iframes served
from `/api/apps/<id>/page` — **same origin as the API**. Three consequences, and
they are the whole problem:

1. The iframe's `fetch()` carries the user's **session cookie** automatically.
2. On a loopback machine the server trusts the request by **source address**
   anyway, so even without the cookie an app's fetch is treated as the user.
3. `allow-same-origin` lets the iframe reach `window.parent` and read anything the
   trusted desktop holds — a CSRF token, the cookie, app state.

The only thing between an app and full user privilege is `app_privilege_guard`,
which decides "is this an app?" from a `Referer`/`X-App-Token` the app controls,
and `_principal_of`, which treats **no token as the user**. An app defeats both by
omitting two headers. No amount of denylist tuning fixes this while the app is
same-origin — every reviewer of this audit reached the same conclusion.

The good news, confirmed in `_compose_app_page`: apps reach the OS **only** through
`X-App-Token`-bearing fetches (`appTool`, `appData`, `appLLM`, `context`). The
token, not the cookie, is their sanctioned authority. So the fix does not have to
invent a new app transport — it has to make the token the *only* thing that works.

---

## Piece 1 — app origin isolation

**Goal:** an app can reach exactly the four token-authenticated runtime endpoints
and nothing else, and it cannot read the desktop's secrets — on a single-user
loopback machine as much as a multi-user remote one.

**Design (double-submit authority separation):**

1. **Drop `allow-same-origin`** from every app iframe (`05-apps-registry.js`,
   `06a-deck.js`, `07-widgets.js`). The iframe becomes an opaque origin: it can no
   longer reach `window.parent`, read `document.cookie`, or share storage with the
   desktop. This is the load-bearing change; everything else follows from it.
2. **Issue the desktop a CSRF token** — a per-session secret delivered into
   `index.html` only (a meta tag or a JS-readable, `HttpOnly:false` cookie on the
   real origin). A one-line global `fetch` wrapper in the desktop bundle attaches
   it as `X-CSRF-Token` to every same-origin request. The app iframe runs a
   *different* document, does not get the wrapper, and — now opaque-origin — cannot
   read the token from the parent.
3. **Require the CSRF token on every mutating route** via one middleware, with an
   allowlist of exactly the read-only and app-runtime endpoints that are exempt. A
   forged app fetch to `/api/grants` or `/api/config` lacks the token → refused,
   regardless of source address or cookie. This is what finally closes the
   loopback-trust leg: authority stops being "you reached us from localhost" and
   becomes "you hold the secret only the top frame has."
4. **App-runtime endpoints require `X-App-Token`, never fall through to the user.**
   `/api/tool`, `/api/apps/<id>/data`, `/api/apps/context`, `/api/apps/llm/*`:
   a request with no valid app token is refused, not resolved to `MAIN`. These
   become cross-origin from the opaque iframe, so they also get a narrow CORS
   allowance for `Origin: null` — safe, because the *authority* is the 144-bit
   token embedded server-side, not the origin.
   - One caller changes: the desktop's **automation step** runs a tool via
     `/api/tool` tokenless today (as the user). It moves to a distinct
     user-authenticated route (`/api/user/tool`) that requires the CSRF token, so
     "the user ran a tool" and "an app ran a tool" stop being the same request.

**Why not a separate origin/port for apps?** It also works (cookies never attach
cross-site) and is browser-independent, but it complicates the install (a second
bound port or a wildcard subdomain + TLS) and does not by itself solve loopback
trust. The double-submit design solves loopback trust and needs no new listener,
so it is preferred; a separate origin is the fallback if a browser is found to
leak `SameSite=Lax` cookies to same-site opaque frames.

**Risk & verification:** this touches the request layer, so it must be verified
in a real browser, not reasoned about. A Playwright suite drives: (a) an app
iframe's fetch to `/api/config` and `/api/grants` is refused; (b) `appTool`,
`appData`, `appLLM` still work end to end; (c) every mutating desktop action still
works with the wrapper; (d) an app can no longer read `window.parent`. The
localStorage-using demo apps (e.g. quicknotes) must migrate to `appData` — the
guidance already tells apps to prefer it, so this is a small, catalogued change.

**Staging:** ship behind a flag, opaque-origin first with the guard still in
place, then flip the CSRF requirement on once the desktop's fetch wrapper is
verified across every app.

---

## Piece 2 — per-user isolation of the shell and the filesystem

**Status: the enforcement layer is done** (`agentos/tools.py`, `agentos/server.py`,
`tests/test_tenant_isolation.py`). What a deployment still chooses is the strength
of the jail underneath it (below).

What now holds whenever accounts exist, verified against a running toolbox:

- **The in-process file tools** (`read_file`, `write_file`, `list_dir`, and the
  git / media-import / app-export paths that share `_sandbox_deny`) refuse any path
  outside the acting account's home — **independent of the Sandbox toggle**. The
  old confinement only applied with the sandbox on and only to the workspace;
  cross-tenant reads through these tools were wide open with the sandbox off. Now
  `_tenant_deny` gates all of them.
- **`run_command` is jailed per account and fails closed.** On a machine with
  accounts the shell runs in a `bwrap` jail rooted at the acting account's home
  with the whole `users/` tree tmpfs-blanked and only that account's home bound
  back — so a shell cannot even *see* another account's files, not merely not write
  them. If no jail mechanism exists, the command is refused rather than run
  unconfined: no jail cannot mean no walls.
- **The Terminal WebSocket** opens the same per-account jail in that account's own
  home (not the OS user's `$HOME`), or refuses if no jail is available.
- **A single-user machine is untouched** — no second tenant to wall off, so the
  agent still reads across the disk as before.

The remaining choice is how strong the jail is against an account that is actively
hostile and resourceful (a `bwrap` escape, or root/physical access). That is the
deployment decision below; the enforcement above makes AgentOS's own tools honour
the boundary regardless.

### The jail strength (deployment choice)

The enforcement above uses a `bwrap` jail, which is a strong boundary against a
normal account but not an unbounded one — a kernel-level `bwrap` escape, or an
account with root or physical access to the disk, is out of its scope. How much
that matters depends on how AgentOS is run, and it is a decision, not just code:

- **Per-user OS uid.** Each AgentOS account maps to a real Unix uid; the server
  drops privilege per request/turn (needs the server to start privileged, or a
  small setuid helper), and every user's home is `0700` owned by their uid. Shell
  and filesystem tools inherit kernel enforcement for free. Strongest; needs root
  at install and changes how the service starts.
- **Per-user bwrap jail.** Every `run_command` and the Terminal run inside a
  `bwrap` jail whose only writable/readable mount is that user's home. No root
  needed, but `bwrap` becomes a hard dependency (today it degrades to unsandboxed),
  and the jail must be per-user, not the current single machine-wide root.
- **Containers.** One container per user (or per session). Cleanest isolation,
  heaviest to operate; fits a hosted/multi-tenant deployment more than a laptop.

Whichever is chosen, two code changes are common to all: the Terminal/VNC
WebSockets must open in the acting user's context and home (they resolve `_ws_user`
now for auth, but still `chdir($HOME)`), and `run_command`/filesystem tools must
refuse to operate outside the acting user's home when accounts are enabled.

**Recommendation:** default AgentOS stays "trusted co-workers" and says so plainly
in `docs/users.md` (it half-does today); "mutually distrusting tenants" becomes a
deployment mode that requires one of the three above, with **per-user bwrap jail**
as the default because it needs no root and reuses the sandbox machinery already
present. That keeps the laptop install honest and gives the enterprise install a
real boundary.

---

## Order of work

1. ✅ Contained fixes (done): WS user context, sustained rate, ledger
   hardening, space-delete / factory-reset audit-erasure.
2. ✅ Piece 2 enforcement (done): the file tools, `run_command` and the Terminal
   honour the per-account boundary and fail closed; `bwrap`-per-user is the
   default jail. What remains is the deployment choice of jail strength above.
3. Piece 1, staged behind a flag with Playwright verification — the last
   verified-CRITICAL escape.
