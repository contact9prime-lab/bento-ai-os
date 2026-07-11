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

### Can't manage or alt-tab native windows; computer-use isn't available

This requires an **X11 session** with window-control tools (`wmctrl`, `xdotool`). Under a **Wayland**
session these are unavailable because Wayland restricts window and input control for security. Log
into an X11 session and install the tools to enable it.

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

### AgentOS didn't open at login

Ensure autostart is enabled (`agentos autostart`), then **log out and back in** — the autostart entry
runs at session start. The background server is separate and is managed by
`systemctl --user … agentos`.

### It's not responding

```bash
systemctl --user status agentos      # running?
systemctl --user restart agentos     # restart
journalctl --user -u agentos -f      # watch logs
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8321/   # should print 200
```
