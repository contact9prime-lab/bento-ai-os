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

## What travels, and what doesn't

This is the one thing worth understanding before you use it from a phone, because
it explains a result that otherwise looks like a bug.

There are **two different things** on the host machine:

| | Where it lives | Does it reach your phone? |
|---|---|---|
| The AgentOS **shell** — windows, dock, deck, apps, chat | an HTML page served over HTTP | **Yes.** This is what remote access sends |
| **Native apps** — LibreOffice, a browser, a terminal | windows the compositor paints on the host's physical display | **No.** They were never in the page |

So launching a system app from your phone really does start it — **on the machine
at home**, on that machine's monitor. Your phone gets the taskbar entry, because
the compositor tells the server and the server tells the page. It does not get the
pixels, because those pixels are on a screen in another room.

AgentOS says so now rather than looking broken: a launch from a remote client
answers with *"opened on <host>"* and an explanation, not a bare tick.

**What you can still do from anywhere:** every window verb goes through the
compositor, so native windows can be focused, moved between desktops, minimised,
maximised and closed from the taskbar and the Window menu, remotely, exactly as
if you were sitting there.

**To see them: the Host Screen app.** It fetches a frame of the machine's real
display (`grim`, which the session already ships for screenshots) and refreshes
it. That is a picture, not a video, and you cannot click on it — but it answers
"did it open, and what is it showing", which is usually the question.

### Actually using a native app: Take control

Seeing is not using. To click and type inside a native app you need pixels
streamed *and* input sent back — remote-desktop work, which
[`wayvnc`](https://github.com/any1/wayvnc) (ISC) does properly for wlroots. So
AgentOS starts it rather than reinventing it: **Host Screen → Take control**
offers *Install wayvnc…* if it is missing, then Start/Stop, and shows the address.

**It binds `127.0.0.1` only, always.** wayvnc ships with security type "None" — no
password — so putting it on the network would hand the whole machine to anyone
who can reach port 5900, undoing every other lock here. AgentOS will not do that
on your behalf. Reach it the way you reach anything else on that machine:

```bash
ssh -L 5900:127.0.0.1:5900 you@your-machine     # then point a VNC client at localhost:5900
```

or over the VPN you already use (Tailscale/WireGuard). The panel shows the exact
tunnel command with a copy button. If you want it exposed directly, configure
wayvnc's own authentication and run it yourself — that is a deliberate choice,
not a checkbox here.

It stops when you stop it, and when AgentOS shuts down — an orphaned VNC server
is an unauthenticated door left open.

| | Host Screen (built in) | Take control (wayvnc) |
|---|---|---|
| See the host display | yes, a refreshing still | yes, live |
| Click and type in native apps | no | yes |
| Needs installing | no | yes, one click |
| Reachable over the LAN | through AgentOS's passphrase | no — loopback + your tunnel |

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
