# Remote access

Reach your AgentOS desktop from your phone, a tablet, or another machine — the whole desktop, laid
out for whatever screen you opened it on.

It is **off until you turn it on**, and it will not turn on without a passphrase. That is not
caution for its own sake: AgentOS gives whoever is looking at it a real shell on your machine, so
serving it to the network is the same decision as handing someone your terminal.

---

## Turning it on

**In the desktop:** **System Settings → Remote access** → set a passphrase → *Turn remote access
on*. The panel then shows the addresses your machine is reachable at.

**Headless** (a Pi, a server, anything you only reach over SSH):

```bash
agentos remote --on --passphrase 'a long passphrase you will remember'
agentos remote                       # show the current state and addresses
agentos remote --off                 # back to loopback only
```

Restart AgentOS afterwards — the bind address is chosen when the server starts.

---

## Using it from your phone

1. Open the address the settings panel shows, e.g. `http://192.168.1.24:8321`.
2. Sign in with the passphrase. The device stays signed in for 30 days.
3. **iOS:** *Share → Add to Home Screen*. **Android:** *⋮ → Install app*.

That last step is what makes it feel like a client rather than a tab: the app launches full-screen
with no browser chrome, its own icon, and its own place in the app switcher. The desktop already
knows it is on a phone — windows open as full-bleed sheets, the dock spans the bottom edge, and
the launcher and popovers become sheets. See [Phone, tablet, desktop](desktop.md#phone-tablet-desktop).

---

## What the lock actually does

| | |
|---|---|
| **Off by default** | `remote.enabled` starts false, and `enabled` without a passphrase is not a reachable state — the config is re-checked on every load, so hand-editing `config.json` cannot open it. |
| **Refuses to bind** | `agentos serve --host 0.0.0.0` exits with an error unless remote access is properly on. The flag alone is not consent. |
| **Loopback is trusted** | Using AgentOS on the machine it runs on is unchanged, signed in or not. The kernel decides the source address, so a LAN client cannot forge it — this is a real boundary, not a header check. |
| **Everything else needs a session** | Passphrase → PBKDF2-SHA256 (210k rounds) → an HMAC-signed cookie. The passphrase itself is never stored. |
| **Websockets too** | `/ws` and `/ws/terminal` are gated by hand, because they bypass HTTP middleware — and the terminal one is literally a shell. |
| **Backoff** | Five wrong guesses from one address and it starts waiting, doubling up to an hour. Every attempt is written to the Logs app. |
| **Only from the machine** | `POST /api/remote` is refused unless it comes from loopback. An agent, an app, or someone already signed in remotely cannot widen access. |
| **Nothing cached** | The desktop shell and the lock screen are the same URL with different answers, so both are `no-store` — a browser can never serve one in place of the other. |
| **Changing the passphrase signs everyone out** | Sessions are signed with the passphrase hash. |

---

## What it is not

This is **one shared passphrase protecting one machine**, not multi-user authentication. There are
no accounts, no roles, and no per-device revocation beyond changing the passphrase.

It also speaks **plain HTTP**. On your own network that is a reasonable trade; on the open internet
it is not — the passphrase would cross the wire in the clear, and so would everything else.

**Do not port-forward AgentOS to the internet.** If you want it from outside your home:

- **Tailscale / WireGuard** — the machine joins your private network and nothing is exposed
  publicly. This is the recommended answer, and it needs no changes here.
- **A reverse proxy you trust** (Caddy, nginx, Cloudflare Tunnel) terminating TLS and adding its
  own authentication in front. Keep the AgentOS passphrase on as well — defence in depth.

---

## Turning it off

```bash
agentos remote --off
```

or the same switch in System Settings. Existing sessions stop working immediately; the server goes
back to listening on loopback only after a restart.
