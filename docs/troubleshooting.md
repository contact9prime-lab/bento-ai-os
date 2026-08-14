# Troubleshooting

---

### The agent stops halfway, or produces nothing

Almost always the model. The agent works by calling tools, and some small local models (e.g. `gemma`)
don't call tools reliably. Switch to a **tool-capable model** — any `qwen` model, or a cloud model —
in the chat window's model dropdown, and retry. App builds automatically retry with a tool-capable
model when one is available.

### An app build returns nothing

Same cause. Pick a tool-capable model. You can also use the **Store → Apps** tab, whose curated
apps install instantly without a model.

### Risky actions don't run

At **Paranoid**/**Balanced** autonomy, actions that change the system wait for your approval. Approve
them in the prompt, add an **allow policy** (or click "Always allow"), or switch to **Full** autonomy.
Destructive commands are always blocked, by design.

### Scheduled jobs don't take actions

At Balanced autonomy, background jobs stay read-only because no one is present to approve. Run **Full**
autonomy or add a policy allowing the specific actions the job needs.

### The sandbox isn't confining anything

The folder sandbox needs `bubblewrap` (`bwrap`) installed. Without it, the sandbox silently stays off.
Install it (`sudo apt install bubblewrap`) and enable it in **Settings → Sandbox**.

### Telegram won't connect / messages do nothing

- Make sure the token is pasted **and** the bridge is enabled in the Telegram app.
- Send your bot **any** message (not only `/start`); the first private chat becomes the owner.
- In groups, a bot only sees messages that mention it unless you disable privacy mode via BotFather.
- Check the **Logs** app for `telegram` entries.

### Native apps or system controls are missing

These use host tools that may not be installed: `gtk-launch` (launch apps), `wpctl` (volume), `upower`
(battery), `nmcli` (network), `gnome-control-center` (settings). Install the ones you need; features
without their tool simply don't appear.

### Can't manage or alt-tab native windows

Wayland deliberately stops one application from controlling another's windows, so when AgentOS
runs **hosted** on a Wayland desktop (stock Ubuntu), native window management is off — the
taskbar explains this. Two ways to get it:

- **Log into the AgentOS session** ([AgentOS as your desktop environment](desktop-environment.md)) —
  there AgentOS *is* the compositor and manages windows natively. This is the full answer.
- On an **X11 session**, install `wmctrl` (and `xdotool` for computer-use) — the older path
  still works.

### Generated wallpapers look low-resolution

The built-in generator uses a free service that caps resolution. For a full-resolution background,
set a local photo or an image URL as the wallpaper (via `set_wallpaper`, or the Personalize app).

### Model download shows GPU is full

The Model Manager shows VRAM used/total. Downloading a model doesn't load it, but running one that
exceeds free VRAM will spill to CPU (slow) or fail. Remove unused models or choose a smaller one — a
~14B model needs roughly 9–10 GB of VRAM.

### The `.deb` won't install on another machine

The prebuilt package targets the Python version it was built against. On a different distribution or
Python version, rebuild it there: `./packaging/build-deb.sh`.

### `bento: command not found` after the curl install

Installers before this fix wrote the `bento` shim into `~/.local/bin` but never added
that directory to your shell's PATH — the installer's own check asked the PATH it had
just widened for itself, so it always concluded the directory was already there. It
printed `✓ AgentOS is installed` and then advice you could not follow.

It bites hardest on Linux, because a graphical terminal tab is a **non-login** shell:
it reads `~/.bashrc` and never `~/.profile`, and the stock Ubuntu/Debian `~/.local/bin`
snippet lives in `~/.profile` and only fires if the directory already existed when the
shell started — which, on a first install, it did not.

Re-running the installer fixes it. To fix an existing machine by hand:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc   # or ~/.zshrc
exec $SHELL                                                # or open a new terminal
bento --help
```

Fish uses different syntax: `fish_add_path ~/.local/bin`.

Until then, AgentOS still runs from its checkout:
`cd ~/.local/src/agentic-os && uv run bento …`

### "AgentOS is already running" when you run `bento`

Since this fix, `bento` checks first and asks rather than refusing:

```
▲ AgentOS is already running.
    http://127.0.0.1:8321   (a systemd user service, pid 1841)

  [o] open it in a browser                        (default)
  [r] restart it
  [p] leave it, and start a second one on port 8322
  [q] quit, change nothing
```

Pick without being asked using `--if-running`: `open`, `port`, `restart`, `fail`.
With no terminal to ask on — a systemd unit, cron, CI — it always behaves as `fail`,
so nothing ever blocks on a prompt nobody is watching.

**A second instance is not free.** Both would use the same `~/.agentos`: one database,
two schedulers (every standing job fires twice), two Telegram/WhatsApp pollers on one
account. For a genuinely separate instance, give it a separate home:
`AGENTOS_HOME=~/.agentos-test bento serve --port 8322`.

If the holder does not identify itself as AgentOS, Bento will not offer to stop it —
it may be an unrelated program on that port. `bento doctor` says what it can.

### "cannot listen on … " — a port the kernel refuses

```
✗ AgentOS cannot listen on 127.0.0.1:80.
  The OS refused to let this process bind port 80.
  Ports below 1024 are privileged, and AgentOS runs as you, not as root.
```

On Linux, allow it once (survives reboot):

```bash
echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee /etc/sysctl.d/50-agentos.conf
sudo sysctl --system
```

…or redirect the port and leave AgentOS unprivileged, or put nginx/caddy in front.
Running the server as root is not advised — the agent has a real shell.

This is checked by binding, never by the port number, because the usual rule of thumb
is wrong: macOS grants `0.0.0.0:80` to any process while refusing `127.0.0.1:80`, and
on Linux the threshold is tunable. If the address you asked for is refused but the
wildcard would work, the message says so.

### `uv: not found` from cron, systemd or a desktop launcher

The shim runs AgentOS through `uv`. Older shims called it by bare name, so they only
worked where PATH already had it — an interactive shell — and failed from anything
with a minimal environment. Re-run the installer: the shim now bakes in the absolute
path to `uv` and falls back to a PATH lookup if that ever moves.

### AgentOS didn't open at login

Ensure autostart is enabled (`agentos autostart`), then **log out and back in** — the autostart entry
runs at session start. The background server is separate and is managed by
`bento service` (`systemctl --user … agentos` underneath, on Linux).

### It's not responding

```bash
bento service status     # running? at boot? is the port answering?
bento service restart
bento service logs -f    # the journal on Linux, the log file on macOS
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8321/   # should print 200
```

If `status` says the supervisor has it running but the port is silent, that is a
crash loop or a wedged startup rather than a stopped service — `bento service logs`
is the next step, not another restart.
