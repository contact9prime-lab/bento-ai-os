# Security

Bento Box AI runs shell commands, edits files and installs software on the
machine it is on, and can be reached from a phone. Please report anything you
find privately first.

## Reporting

Open a [private advisory](https://github.com/contact9prime-lab/bento-ai-os/security/advisories/new).
Not a public issue — a working exploit against a self-hosted agent is a working
exploit against everybody who has already installed it.

Please include what you did, what you got, and which face you were in (GUI, TUI,
SUI, a phone over remote access, or a channel like Telegram). If you are not sure
whether something is a vulnerability, report it anyway.

## What we consider in scope

The boundaries that decide *who a principal is* and *what it can reach*, all
documented in [`docs/design/tenant-isolation.md`](docs/design/tenant-isolation.md):

- **The app sandbox.** Apps are opaque-origin iframes (`allow-scripts allow-forms`,
  deliberately without `allow-same-origin`). Anything that lets an app reach a
  normal `/api/*` mutation, read `window.parent`, or forge an `Origin`.
- **The WebSocket origin gate.** One of these sockets is a shell. A cross-origin
  handshake that gets past `_ws_reject` is remote code execution.
- **User isolation.** Accounts are separate directories, not a column. Anything
  that lets one account read another's home, database, memory or credentials.
- **The policy gate.** Anything that performs a capability without passing through
  the PDP, or that reaches a tool without the grant it should have needed.
- **The audit ledger.** Rows are hash-chained. Anything that edits or deletes a
  row without `audit_verify()` noticing.
- **Remote access and the locks.** Anything that gets past the passphrase, the
  account sign-in, or a locked session — including anything that keeps a socket
  streaming while the page is behind a lock screen.
- **Prompt injection that crosses a boundary.** Content the agent reads is
  untrusted. A page or file that talks the agent into an action the user never
  approved is a bug, not a curiosity.

## What is deliberately not defended

Saying so plainly is the point; a security page that implies more than it does is
worse than one that implies less.

- **A `bubblewrap` escape**, or an account with root or physical disk access.
  Per-account jails blank sibling homes, and that is a real boundary against a
  normal process — it is not a boundary against root. Deployments that need that
  guarantee should use per-user uids or containers.
- **A model doing something silly within the permissions it was granted.** Grants,
  budgets and the rate ceiling bound it; judgement is not a security control.
- **The machine's own operator.** `is_admin('')` is True on a machine with no
  accounts, deliberately: there is nobody to refuse.

## Supported versions

The latest release, and `master`. This project has not yet reached 1.0 and there
are no backports.
