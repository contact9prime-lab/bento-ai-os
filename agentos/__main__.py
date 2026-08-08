"""Entry point: `agentos` serves the UI; `agentos ask "..."` runs a one-shot agent in the terminal."""

import argparse
import asyncio
import json
import os
import sys
import threading
import time
import webbrowser


def _use_system_certs():
    # verify TLS against the OS trust store instead of certifi's bundled CAs
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass


def _port_free(host: str, port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def serve(host: str, port: int, open_browser: bool):
    import uvicorn
    from . import config as cfgmod
    from . import remote as remotemod
    cfg = remotemod.sanitize_remote(cfgmod.load_config())
    port = port or cfg.get("port", 8321)

    # Binding off-loopback is the one thing this program will not do on a flag
    # alone. AgentOS hands whoever loads it a real shell, so listening on the
    # network requires the passphrase that guards it — set it in
    # Settings → Remote access (or `agentos remote --passphrase ...`).
    if host == "127.0.0.1" and remotemod.enabled(cfg):
        host = remotemod.bind_host(cfg)          # the setting opts in; honour it
    if not remotemod.is_loopback(host) and not remotemod.enabled(cfg):
        print(f"Refusing to serve on {host}: remote access is off.\n"
              f"  AgentOS has no login until you give it one, and the agent has a real\n"
              f"  shell — an open port here is an open shell.\n"
              f"  Turn it on:  agentos serve   (then Settings → Remote access)\n"
              f"  or headless: agentos remote --on --passphrase '<something long>'")
        sys.exit(4)
    os.environ["AGENTOS_BOUND_HOST"] = host
    url = f"http://{host}:{port}"
    if not _port_free(host, port):
        # bail BEFORE the app's startup hook runs: a doomed instance must not spawn
        # MCP servers / scheduler / telegram or write to the DB it shares with the
        # instance that actually owns the port
        print(f"AgentOS is already running (or something else holds {host}:{port}).\n"
              f"  open it:            {url}\n"
              f"  or stop the owner:  systemctl --user stop agentos   (if installed as a service)\n"
              f"  or pick a port:     agentos serve --port <other>")
        sys.exit(3)
    print(f"""
  ┌─────────────────────────────────────┐
  │   ▲ AgentOS                         │
  │   your machine, with a brain        │
  │                                     │
  │   {url:<34}│
  └─────────────────────────────────────┘
""")
    if remotemod.enabled(cfg):
        print("  remote access is ON — this desktop is reachable from your network:")
        for a in remotemod.lan_addresses(port):
            print(f"    {a}")
        print("  sign in with your passphrase; local use is unchanged.\n")
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    uvicorn.run("agentos.server:app", host=host, port=port, log_level="warning")


def ask(prompt: str, model: str | None, full: bool):
    from . import config as cfgmod
    from .agent import Agent
    from .memory import Store
    from .tools import Toolbox

    cfg = cfgmod.load_config()
    cfgmod.ensure_dirs(cfg)
    if cfgmod.is_first_run():
        print("Tip: run `agentos setup` for first-time setup (model, autonomy, boot autostart).\n")
    if full:
        cfg["autonomy"] = "full"
    store = Store(cfgmod.DB_PATH)
    toolbox = Toolbox(cfg, store)

    async def emit(ev):
        if ev["type"] == "text_delta":
            sys.stdout.write(ev["text"])
            sys.stdout.flush()
        elif ev["type"] == "tool_start":
            args = json.dumps(ev["args"])
            print(f"\n\033[36m▸ {ev['name']} {args[:160]}\033[0m")
        elif ev["type"] == "tool_end":
            out = ev["output"].strip()
            if out:
                shown = "\n".join(out.splitlines()[:12])
                print(f"\033[90m{shown}\033[0m")
        elif ev["type"] == "error":
            print(f"\033[31merror: {ev['message']}\033[0m")

    async def approver(name, args, reason) -> bool:
        print(f"\n\033[33m⚠ approval needed: {name} {json.dumps(args)[:200]}\n  {reason}\033[0m")
        ans = input("  allow? [y/N] ").strip().lower()
        return ans in ("y", "yes")

    async def main_async():
        model_id = model or cfg.get("default_model", "")
        if not model_id:
            from . import providers
            models = await providers.available_models(cfg)
            if not models:
                print("No models available. Start Ollama or add an API key via the UI (`agentos`).")
                return
            model_id = models[0]["id"]
        agent = Agent(cfg, toolbox, model_id, emit, approver)
        await agent.run([{"role": "user", "content": prompt}])
        print()

    asyncio.run(main_async())


def usage_cmd(args):
    """`agentos usage` — the headless face of the cost ledger."""
    from . import config as cfgmod
    from . import usage as usagemod
    from .memory import Store

    cfg = cfgmod.load_config()
    rep = usagemod.report(Store(cfgmod.DB_PATH), cfg, days=args.days, group=args.by)
    if not rep["rows"]:
        print(f"no turns recorded in the last {args.days:g} day(s).")
        return
    print(usagemod.format_report(rep))


def eval_cmd(args):
    """The TUI face of the eval harness: `agentos eval` over SSH, no browser.

    Exit status is the gate — 0 only if every case passed on every model — so it
    can sit in a CI step or a pre-release check without anyone reading the table.
    """
    from . import config as cfgmod
    from . import evals

    cfg = cfgmod.load_config()
    if args.list:
        for c in evals.select(evals.load_cases(), tags=args.tag, network=True):
            tags = ",".join(c.get("tags") or []) or "-"
            net = " [needs network]" if c.get("network") else ""
            print(f"{c['id']:<26} {tags:<22} {c.get('title', '')}{net}")
        return

    models = args.model or [cfg.get("default_model", "")]
    models = [m for m in models if m]
    if not models:
        print("No model configured. Pass --model, or set one in Settings (`agentos`).")
        sys.exit(2)

    print(f"Running behavioural evals against: {', '.join(models)}")
    print("(each case runs in a throwaway home — nothing here touches your data)\n")

    def show(r):
        mark = {"pass": "\033[32mPASS\033[0m", "fail": "\033[31mFAIL\033[0m",
                "error": "\033[33mERR \033[0m"}[r["status"]]
        print(f"  {mark}  {r['id']:<26} {r['seconds']}s")

    report = asyncio.run(evals.run(models, only=args.case, tags=args.tag,
                                   network=args.network, on_result=show))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(evals.format_report(report, verbose=args.verbose))
    path = evals.save(report)
    print(f"\nreport: {path}")
    failed = sum(s["failed"] + s["errors"] for s in report["by_model"].values())
    sys.exit(1 if failed else 0)


def forward_cmd(engine: str | None):
    """Read or set the machine-wide engine.

    The TUI face of Settings → Executors → Forward everything. Over SSH there is
    no menu bar to carry the forwarding chip, so this prints the state plainly and
    names what is deliberately not forwarded — a headless box quietly answering as
    a different agent is exactly the surprise this wording exists to prevent.
    """
    from . import config as cfgmod
    from . import executors as execmod

    cfg = cfgmod.load_config()
    if not engine:
        cur = execmod.resolve_engine(cfg)
        if cur == "aria":
            print(f"answering with {cfg.get('agent_name', 'Aria')} (the built-in agent)")
        else:
            print(f"forwarding every request to {cur}")
            print("  (apps and App Studio still use the built-in agent — they need its tools)")
        return

    want = "aria" if engine == "off" else engine
    if want == "claude-code":
        info = execmod.available()
        if not info.get("available"):
            print(info.get("reason", "Claude Code is not available"))
            return
    cfg["engine"] = want
    cfgmod.save_config(cfg)
    if want == "aria":
        print(f"answering with {cfg.get('agent_name', 'Aria')} again")
    else:
        print(f"forwarding every request to {want}")
        print("  chat · prompt bar · copilot · Telegram · API · scheduled turns")
        print("  not forwarded: apps and App Studio (they depend on the built-in tools)")
    print("  a running server picks this up on its next turn")


def tunnel_cmd(on: bool, off: bool, public: bool, provider: str, install: bool = False):
    """Show or change how this machine is reached from elsewhere.

    The TUI face matters more here than anywhere: a headless box is exactly the
    one you cannot walk over to in order to read its address off the screen.
    """
    import asyncio as _aio
    from . import config as cfgmod
    from . import tunnel as tunmod

    cfg = cfgmod.load_config()
    if install:
        ok, message = _aio.run(tunmod.install(provider or "cloudflared"))
        print(("  " if ok else "  refused: ") + message)
        return
    if off:
        ok, message = _aio.run(tunmod.stop(cfg))
        print(("  " if ok else "  refused: ") + message)
        return
    if on:
        ok, message, url = _aio.run(tunmod.start(cfg, provider or "tailscale", public))
        print(("  " if ok else "  refused: ") + message)
        if url:
            print(f"  {url}")
        return

    st = _aio.run(tunmod.status(cfg))
    if st.get("gate"):
        print(f"  not publishable yet: {st['gate']}")
        print()
    reach = st.get("reachable") or []
    if reach:
        print("  reachable now:")
        for r in reach:
            print(f"    {r['url']:<46} {r['via']} — {r['who']}")
    else:
        print("  reachable only from this machine (remote access is off)")
    print()
    for p in st.get("providers") or []:
        mark = "●" if p["available"] else "○"
        print(f"  {mark} {p['title']}: {p.get('reason') or p.get('needs') or 'ready'}")
        if p.get("install_cmd"):
            print(f"      install it:  agentos tunnel --install --provider {p['id']}")
    print()
    print("  agentos tunnel --on [--public] [--provider tailscale] | --off")


def channels_cmd(channel: str | None, on: bool, off: bool, posture: str | None,
                  sets: list | None = None, link: bool = False):
    """Show or change the ways in.

    The TUI face of Settings → Channels. This is the face that matters most on a
    headless machine: the box you can only reach over SSH is exactly the one where
    "who can talk to this, and how far do I trust it" needs answering, and there
    is no settings window there to answer it in.
    """
    from . import config as cfgmod
    from . import channels as chmod

    cfg = cfgmod.load_config()
    if not channel:
        for c in chmod.state(cfg):
            mark = {"on": "●", "off": "○", "needs": "!"}.get(c["status"], "·")
            trust = c["posture_label"] + ("" if c["own_gate"]
                                          else f" (follows {c['posture_from']})")
            print(f"  {mark} {c['title']:<16} {c['detail']:<34} {trust}")
            print(f"      {c['reach']}")
        print()
        print("  agentos channels <id> --on|--off --posture "
              f"{'|'.join(chmod.POSTURE_LABELS)}")
        return

    if channel not in chmod.BY_ID:
        print(f"no such channel: {channel}")
        print("  known: " + ", ".join(chmod.BY_ID))
        return

    patch: dict = {}
    if on:
        patch["enabled"] = True
    if off:
        patch["enabled"] = False
    if posture:
        patch["posture"] = posture
    if link:
        if channel != "whatsapp":
            print("  --link is only for whatsapp")
            return
        _whatsapp_link_cli(cfg)
        return

    known = {f.key for f in chmod.BY_ID[channel].fields}
    for pair in (sets or []):
        key, _, val = str(pair).partition("=")
        key = key.strip()
        if key not in known:
            print(f"  {chmod.BY_ID[channel].title} has no field '{key}'"
                  + (f" — it takes: {', '.join(sorted(known))}" if known else ""))
            return
        patch[key] = val
    if not patch:
        c = next(x for x in chmod.state(cfg) if x["id"] == channel)
        print(f"  {c['title']} — {c['detail']}")
        print(f"  who: {c['reach']}")
        print(f"  trust: {c['posture_label']}"
              + ("" if c["own_gate"] else f" (follows {c['posture_from']})"))
        if c.get("note"):
            print(f"  note: {c['note']}")
        for f in chmod.BY_ID[channel].fields:
            print(f"    --set {f.key}={'…' if f.secret else '<value>'}"
                  f"{'  (set)' if c['set'].get(f.key) else ''}  {f.label}")
        if channel == "whatsapp":
            _whatsapp_webhook_note(cfg)
        return

    ok, message = chmod.save(cfg, channel, patch)
    cfgmod.save_config(cfg)          # a partial change still persists what took
    print(("  " if ok else "  refused: ") + message)
    if ok:
        print("  a running server picks this up on its next turn")
        if channel == "whatsapp":
            _whatsapp_webhook_note(cfg)


def _whatsapp_link_cli(cfg: dict):
    """Draw the QR in the terminal and wait for the scan.

    The one place a QR genuinely has to be ASCII: a headless Pi over SSH is
    exactly where you cannot open a settings page, and it is also exactly where a
    standing WhatsApp channel is most useful. Goes through the running server so
    there is one bridge process, not two fighting over the same credentials.
    """
    import urllib.error
    import urllib.request

    from . import whatsapp_link as wl
    base = f"http://127.0.0.1:{cfg.get('port', 8321)}"

    def call(path, method="GET"):
        req = urllib.request.Request(base + path, method=method,
                                     data=b"{}" if method == "POST" else None,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")

    try:
        st = call("/api/whatsapp")
    except OSError:
        print("✗ AgentOS is not running here — start it with `bento serve`")
        sys.exit(1)
    if not st.get("link", {}).get("installed"):
        print(f"  {st.get('link', {}).get('why', 'the bridge is not installed')}")
        print("\n  Install it first — it is MIT (Baileys) and UNOFFICIAL:")
        print("  WhatsApp does not support automating a linked device and has banned")
        print("  accounts for it. Prefer a spare number.\n")
        print("  bento apps install whatsapp-bridge     (or use Settings → Channels)")
        sys.exit(1)
    try:
        call("/api/whatsapp/link", "POST")
    except urllib.error.HTTPError as e:
        print(f"✗ {json.loads(e.read() or b'{}').get('error', e)}")
        sys.exit(1)

    print("  On your phone: WhatsApp → Settings → Linked devices → Link a device\n")
    seen = ""
    for _ in range(90):                      # ~3 minutes of QR rounds
        time.sleep(2)
        try:
            link = call("/api/whatsapp").get("link") or {}
        except OSError:
            print("✗ lost the server")
            sys.exit(1)
        if link.get("state") == "ready":
            print(f"\n  ✓ linked as {(link.get('me') or '').split(':')[0]}")
            print("  Message this WhatsApp from your phone — that chat becomes the owner.")
            return
        payload = link.get("qr_payload") or ""
        if payload and payload != seen:
            seen = payload
            art = wl.qr_ascii(payload)
            if art:
                print(art)
            else:
                # No renderer: hand over the payload rather than an empty box.
                print("  (install the `qrcode` package to draw it here; the raw code is)")
                print(f"  {payload}")
            print("  waiting for the scan…\n")
        if link.get("error"):
            print(f"  {link['error']}")
    print("  timed out waiting for the scan — run it again when you are ready")


def _whatsapp_webhook_note(cfg: dict):
    """The callback URL, or the sentence that says why there is not one yet.

    A webhook channel that is "on" but unreachable receives nothing, forever, with
    no error anywhere. Over SSH there is no settings page to notice that on, so the
    terminal has to say it out loud.
    """
    import asyncio as _aio

    from . import whatsapp as wamod
    try:
        reach = _aio.run(wamod.reachability(cfg))
    except Exception:
        reach = {"reachable": False, "why": "could not check how this machine is reachable"}
    if reach.get("reachable"):
        print(f"  webhook URL (paste into developers.facebook.com):\n    {reach['webhook']}")
    else:
        print(f"  not reachable yet: {reach.get('why', '')}")


def delegate(prompt: str, workdir: str | None, tools: str | None,
             model: str | None, budget: float | None):
    """Hand a task to an executor from the terminal.

    The TUI face of Settings → Executors: over SSH there is no model picker, so
    the envelope is stated as flags instead — and printed before the run starts,
    because delegating work to another agent should never be silent about what
    that agent was allowed to touch.
    """
    import asyncio

    from . import config as cfgmod
    from . import executors as execmod

    info = execmod.available()
    if not info.get("available"):
        print(info.get("reason", "no executor available"))
        if info.get("install"):
            print(f"  {info['install']}")
        return

    cfg = cfgmod.load_config()
    conf = (cfg.get("executors") or {}).get("claude_code") or {}
    env = execmod.Envelope(
        workspace=workdir or conf.get("workspace") or str(cfgmod.AGENTOS_HOME / "workspace"),
        tools=tuple(t.strip() for t in tools.split(",") if t.strip()) if tools
              else tuple(conf.get("tools") or execmod.DEFAULT_TOOLS),
        model=model or conf.get("model", ""),
        budget_usd=budget if budget is not None
                   else float(conf.get("budget_usd", execmod.DEFAULT_BUDGET_USD)),
    ).sanitized()
    print(f"→ {env.describe()}\n")

    run = execmod.Run()

    async def emit(ev: dict):
        kind = ev.get("type")
        if kind == "text_delta":
            print(ev.get("text", ""), end="", flush=True)
        elif kind == "tool_start":
            print(f"\n  · {ev.get('name')}", flush=True)
        elif kind == "error":
            print(f"\n  ! {ev.get('message')}", flush=True)

    try:
        asyncio.run(execmod.run_task(prompt, env, emit, run))
    except KeyboardInterrupt:
        execmod.stop(run)
        print("\nstopped.")
        return
    print(f"\n\n— {run.turns} turn(s), ${run.cost_usd:.4f}")


def doctor(fix: bool = False, session: bool = False):
    """Environment sanity: the checks that catch every 'it hangs' class of incident.
    With fix=True, auto-remediate what is safe to fix and print sudo steps for the rest."""
    import json as _json
    import shutil
    import socket
    import sqlite3
    import subprocess
    import urllib.request
    from . import config as cfgmod

    ok = lambda m: print(f"  \033[32m✓\033[0m {m}")           # noqa: E731
    warn = lambda m: print(f"  \033[33m!\033[0m {m}")         # noqa: E731
    bad = lambda m: print(f"  \033[31m✗\033[0m {m}")          # noqa: E731
    fixed = lambda m: print(f"  \033[36m⚑ fixed:\033[0m {m}")  # noqa: E731
    todo = lambda m: print(f"  \033[35m→ do:\033[0m {m}")     # noqa: E731

    def run(argv):
        try:
            return subprocess.run(argv, capture_output=True, text=True, timeout=15)
        except Exception:
            return None

    cfg = cfgmod.load_config()
    port = cfg.get("port", 8321)
    print("AgentOS doctor" + ("  (--fix: auto-repair on)" if fix else "") + "\n")

    # --session answers one question — what can draw the desktop here — and it is
    # the only thing worth printing when that is what you are asking. Every probe
    # runs in a subprocess, because the failures it looks for are aborts and
    # segfaults inside GTK and WebKit.
    if session:
        from . import sessiondoctor
        sessiondoctor.report(ok, warn, bad, todo)
        return

    # 1. who owns the port?
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/build/status", timeout=3) as r:
            _json.loads(r.read())
        ok(f"server responding on 127.0.0.1:{port}")
    except Exception:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                bad(f"port {port} is taken but does not answer like AgentOS — another app owns it")
            else:
                warn(f"no server on port {port} (start with: agentos serve)")

    # 2. duplicate instances (the crash-loop incident class)
    try:
        out = subprocess.run(["pgrep", "-fc", "agentos serve"], capture_output=True, text=True)
        n = int(out.stdout.strip() or 0)
        if n > 1:
            bad(f"{n} 'agentos serve' processes are running — they will fight over the port and the DB")
        elif n == 1:
            ok("exactly one server process")
    except Exception:
        pass
    r = run(["systemctl", "--user", "is-active", "agentos"])
    if r is not None:
        st = r.stdout.strip()
        if st == "activating":
            bad("systemd unit 'agentos' is crash-looping (activating)")
            if fix:
                # if something already answers the port, the unit is the loser of a
                # port war and should stand down; otherwise stopping is still safe
                run(["systemctl", "--user", "stop", "agentos"])
                after = run(["systemctl", "--user", "is-active", "agentos"])
                if after and after.stdout.strip() != "activating":
                    fixed("stopped the crash-looping unit (re-enable later with: "
                          "systemctl --user start agentos)")
                else:
                    todo("systemctl --user stop agentos   (couldn't stop it automatically)")
            else:
                todo("agentos doctor --fix   (or: systemctl --user stop agentos)")
        elif st == "active":
            ok("systemd user service active")
        else:
            warn(f"systemd user service: {st}")

    # 3. Ollama + VRAM pressure
    base = cfg["providers"]["ollama"]["base_url"]
    try:
        with urllib.request.urlopen(f"{base}/api/ps", timeout=3) as r:
            loaded = _json.loads(r.read()).get("models", [])
        ok(f"ollama up at {base} ({len(loaded)} model(s) loaded)")
        for m in loaded:
            gb = m.get("size_vram", 0) / 1e9
            pinned = (str(m.get("expires_at", "")).startswith("2")
                      and int(str(m.get("expires_at", "0"))[:4] or 0) > 2100)
            (warn if pinned else ok)(
                f"  loaded: {m['name']} ({gb:.1f}GB VRAM)"
                + (" — pinned forever (keep_alive=-1)" if pinned else ""))
            if pinned and fix:
                try:
                    req = urllib.request.Request(
                        f"{base}/api/generate", method="POST",
                        data=_json.dumps({"model": m["name"], "keep_alive": 0}).encode(),
                        headers={"Content-Type": "application/json"})
                    urllib.request.urlopen(req, timeout=10).read()
                    fixed(f"released {m['name']} from VRAM (keep_alive=0 for this run)")
                except Exception:
                    todo(f"ollama stop {m['name']}")
    except Exception:
        warn(f"ollama not reachable at {base} (local models unavailable)")
    # exposure check: an unauthenticated Ollama on 0.0.0.0 is reachable by the whole LAN
    r = run(["ss", "-tln"])
    if r is not None:
        for line in r.stdout.splitlines():
            if ":11434" in line and ("0.0.0.0:11434" in line or "*:11434" in line or "[::]:11434" in line):
                bad("ollama listens on ALL interfaces (OLLAMA_HOST=0.0.0.0) — the LAN can use it")
                # needs root to edit the service → always guidance, never auto-sudo
                todo("set OLLAMA_HOST=127.0.0.1: edit /etc/systemd/system/ollama.service.d/*.conf "
                     "(or `launchctl setenv` on macOS), then restart ollama")
                break

    # 4. DB
    try:
        db = sqlite3.connect(str(cfgmod.DB_PATH), timeout=3)
        mode = db.execute("PRAGMA journal_mode").fetchone()[0]
        if mode != "wal" and fix:
            new = db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            db.execute("PRAGMA busy_timeout=5000")
            if new == "wal":
                fixed("set db journal_mode=WAL")
                mode = new
        integ = db.execute("PRAGMA integrity_check").fetchone()[0]
        (ok if mode == "wal" else warn)(f"db journal_mode={mode}")
        (ok if integ == "ok" else bad)(f"db integrity: {integ}")
    except Exception as e:
        bad(f"db check failed: {e}")

    # 5. optional companions
    ok("git available" if shutil.which("git") else "")
    if not shutil.which("git"):
        warn("git not installed — the Ship pillar (git_* tools) needs it")
    from .tools import sandbox_mechanism
    mech = sandbox_mechanism()
    if mech:
        ok(f"sandbox available ({mech})")
    elif sys.platform == "linux":
        warn("bubblewrap missing — sandbox falls back to unjailed commands (install: apt install bubblewrap)")
    else:
        warn("no sandbox mechanism found — shell commands run unjailed")
    from . import trainforge as tfmod
    tf = tfmod.conf(cfg)
    if tf["path"]:
        ok(f"TrainForge found at {tf['path']} (Train pillar)")
    elif tf.get("repo") and "YOUR_ORG" not in tf["repo"]:
        warn("TrainForge not installed — the Train app will fetch it on first Start")
    else:
        warn("TrainForge not found — set trainforge.path or trainforge.repo to enable the Train pillar")

    # 6. the desktop (AgentOS-as-the-DE)
    if sys.platform == "linux":
        from pathlib import Path as _P

        from . import compositor as compmod
        from . import runmode
        effective, detected = runmode.resolve(cfg)
        ok(f"desktop mode: {effective}"
           + (f" (pinned; detected {detected})" if effective != detected else "")
           + f" — session type {os.environ.get('XDG_SESSION_TYPE', 'unknown')}")

        wl_entry = _P("/usr/share/wayland-sessions/agentos.desktop")
        x_entry = _P("/usr/share/xsessions/agentos.desktop")
        if wl_entry.exists():
            ok("AgentOS Wayland session installed (pick it at the login screen)")
        elif x_entry.exists():
            warn("only the legacy X11 AgentOS session is installed — "
                 "`agentos install-session` adds the Wayland one")
        else:
            warn("AgentOS is not installed as a login session — `agentos install-session`")

        if shutil.which("sway"):
            if compmod.available():
                try:
                    n = len(compmod.Compositor().windows())
                    ok(f"compositor reachable on $SWAYSOCK ({n} managed windows)")
                except Exception as e:
                    bad(f"compositor socket present but not answering: {e}")
                _doctor_session_handover(compmod, effective, runmode, ok, warn, bad)
            elif effective == runmode.DE:
                bad("in DE mode but $SWAYSOCK is not set — window management is dead")
            else:
                ok("sway installed (compositor for the AgentOS session)")
        elif wl_entry.exists() or effective == runmode.DE:
            bad("sway is not installed but the AgentOS session expects it — apt install sway")
        else:
            warn("sway not installed — needed only for the AgentOS Wayland session")

        # How the desktop gets DRAWN, which decides whether it is a real desktop
        # surface or a window pretending to be one.
        from . import shellhost as _sh
        from . import desktop as desktopmod
        # A previous login tried the native surface and got nothing on screen, so
        # the session launcher parked it. Say so loudly: otherwise the machine
        # silently keeps using the fallback and nobody knows why.
        _lsfail = cfgmod.AGENTOS_HOME / "layer-shell-failed"
        if _lsfail.is_file():
            warn("the native desktop surface is DISABLED — it failed to render here")
            for _line in _lsfail.read_text().splitlines()[:2]:
                print(f"      {_line}")
            if fix:
                _lsfail.unlink()
                fixed("cleared the flag — the next login will try the native surface again")
            else:
                todo(f"agentos doctor --fix   (or: rm {_lsfail})   to try it again")
        _py, _wk = _sh.python_with_gi()
        if _py and not _lsfail.is_file():
            ok(f"native desktop surface available (WebKit2GTK {_wk} via {_py})")
            ok("  → app windows stack above the desktop natively; the menu bar and dock "
               "are reserved with the compositor")
        elif _py:
            pass                        # already reported as disabled above
        else:
            warn("no native desktop surface — the session will draw the desktop in a "
                 "Chromium window instead, which has to fake the stacking order")
            todo(_sh.install_hint())
        if desktopmod.find_browser():
            ok("Chromium-family browser found (the fallback renderer, and the Web app)")
        elif not _py:
            bad("nothing can draw the desktop: no WebKitGTK layer-shell stack and no "
                "chromium-family browser")
        else:
            warn("no chromium-family browser (only needed as the fallback renderer)")

        # The browser remote desktop: reachable from a phone with nothing on it.
        from . import remotedesktop as _rd
        _have = _rd.available()
        if _have["wayvnc"] and _have["novnc"]:
            ok("Remote Desktop ready (wayvnc + noVNC) — usable from a phone browser")
        elif _have["wayvnc"]:
            warn("wayvnc is installed but noVNC is not — remote control needs a VNC "
                 "client app until you add it (apt install novnc)")
        else:
            warn("Remote Desktop not installed (apt install wayvnc novnc) — optional")

        try:
            from . import session as _sess
            if _sess.SWAY_CONF.is_file() and _sess.config_is_stale():
                if fix:
                    _changed, _how = _sess.refresh_config()
                    fixed(f"compositor config was from an older AgentOS — {_how}")
                else:
                    bad("the installed compositor config is older than this AgentOS. "
                        "Window rules shipped since you installed the session are not "
                        "active — that is what 'no window controls' and 'apps always on "
                        "top' look like")
                    todo("agentos doctor --fix   (or `agentos install-session` again)")
            elif _sess.SWAY_CONF.is_file():
                ok("compositor config matches this version of AgentOS")
        except Exception:
            pass

        if effective == runmode.DE and os.environ.get("AGENTOS_SESSION") != "1":
            warn("server reports DE mode but wasn't started by the session launcher — "
                 "a stale server from another session may be holding the port")

        # NVIDIA + wlroots: modeset must be on for the session to light up.
        # (Some driver builds make this file root-only — unreadable is not a finding.)
        try:
            modeset = _P("/sys/module/nvidia_drm/parameters/modeset").read_text().strip()
        except OSError:
            modeset = ""
        if modeset and modeset not in ("Y", "1"):
            warn("NVIDIA without nvidia-drm.modeset=1 — the Wayland session may not start "
                 "on this GPU (add nvidia-drm.modeset=1 to the kernel cmdline, or let it "
                 "use the iGPU)")

        from .hostctl import audio as _au
        from .hostctl import bluetooth as _bt
        from .hostctl import brightness as _br
        from .hostctl import network as _net
        for label, avail in (("wifi control (NetworkManager)", _net.available()[:2]),
                             ("bluetooth (BlueZ)", _bt.available()[:2]),
                             ("audio devices (PipeWire)", _au.available()[:2]),
                             ("brightness", _br.available()[:2])):
            avail_ok, why = avail
            if avail_ok:
                ok(label)
            else:
                warn(f"{label}: {why}")
    print()
    if not fix:
        print("  \033[90mrun `agentos doctor --fix` to auto-repair the fixable items above\033[0m\n")



def _doctor_session_handover(compmod, effective, runmode, ok, warn, bad):
    """The three facts that decide whether launching an app actually works.

    Every one of these was broken at some point in a way no unit test could see,
    because they are properties of a LIVE compositor: the desktop has to be
    findable, it has to be able to step back, and a command has to survive sway's
    own parser on the way to the shell.
    """
    if effective != runmode.DE:
        return
    C = compmod.Compositor()
    port = compmod.shell_port()

    shell = ""
    try:
        shell = C.find_shell(port)
    except Exception as e:
        bad(f"could not look for the desktop window: {e}")
    if shell:
        ok(f"the desktop window is identifiable (con_id {shell}) — raise/lower can work")
    else:
        bad(f"the desktop window was NOT found on port {port}. Launching an app cannot "
            f"lower it, so the app will open behind a screen-filling window and look "
            f"like nothing happened")

    # can the desktop actually step back? do it and put it straight back.
    if shell:
        try:
            was = compmod.SHELL_RAISED[0]
            C.raise_shell(False)
            floating = next((w["floating"] for w in C.windows(include_shell=True)
                             if w["id"] == shell), None)
            if floating:
                warn("the desktop is still floating after being lowered — apps will be "
                     "painted underneath it")
            else:
                ok("the desktop steps back on demand (apps can come to the front)")
            if was:
                C.raise_shell(True)
        except Exception as e:
            bad(f"lowering the desktop failed: {e}")

    # does a command survive sway's parser? `,` and `;` are separators to it, and
    # real .desktop Exec lines are full of them.
    try:
        C.exec("sh -c 'exit 0'  # agentos doctor, ignore")
        ok("the compositor accepts launch commands verbatim (.desktop Exec lines are safe)")
    except Exception as e:
        bad(f"the compositor rejected a launch command: {e}")


def _apps_cli(args):
    """Native applications from a terminal.

    The same catalogue and the same consent ladder as the desktop's
    Applications -> Get apps. It exists because a headless Pi reached over SSH is
    a first-class way to run AgentOS, and "install this program" is the most
    ordinary thing anyone does with a machine.
    """
    from . import appstore
    b = appstore.backends()
    if not appstore.available():
        print("No package manager found (looked for flatpak, apt, dnf, pacman).")
        sys.exit(1)

    if args.action == "list" and not args.name:
        print("available here: " + ", ".join(k for k, v in b.items() if v and k != "needs_root"))
        print("\n  agentos apps search <query>")
        print("  agentos apps install <package> [--backend flatpak|apt|dnf|pacman]")
        print("  agentos apps remove  <package>")
        return

    if args.action in ("list", "search"):
        res = asyncio.run(appstore.search(args.name, 40))
        if res.get("message"):
            print(res["message"])
        for r in res["results"]:
            mark = "installed" if r["installed"] else ""
            print(f"  {r['name'][:34]:36} {r['backend']:8} {mark:9} {r['summary'][:60]}")
        if not res["results"]:
            print("  nothing matched")
        return

    if not args.name:
        print(f"which package? e.g. agentos apps {args.action} gimp")
        sys.exit(2)
    # Say what will run before running it. This is someone's machine.
    print(f"{args.action}: {args.name}"
          + (f" (via {args.backend})" if args.backend else ""))
    res = asyncio.run(appstore.act(args.action, args.name, args.backend))
    if res.get("command"):
        print(f"  $ {res['command']}")
    print(("✓ " if res.get("ok") else "✗ ") + (res.get("message") or ""))
    sys.exit(0 if res.get("ok") else 1)


def _remote_desktop_cli(args):
    """Turn the browser remote desktop on or off without a desktop to click in.

    This is the switch you want over SSH: enable it, then open the machine's
    AgentOS address on your phone and go to /remote-desktop. The VNC server it
    starts is bound to 127.0.0.1 — AgentOS relays it over the connection your
    passphrase already protects.
    """
    import urllib.error
    import urllib.request
    from . import config as cfgmod
    from . import remotedesktop as rd

    port = cfgmod.load_config().get("port", 8321)
    base = f"http://127.0.0.1:{port}"
    have = rd.available()

    def call(path, data=None):
        req = urllib.request.Request(base + path, method="POST" if data else "GET",
                                     data=json.dumps(data).encode() if data else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return {"error": json.loads(e.read() or b"{}").get("error", str(e))}
        except Exception as e:                                    # noqa: BLE001
            return {"error": f"{e} — is AgentOS running? (agentos serve)"}

    if args.on or args.off:
        if args.on and not (have["wayvnc"] and have["novnc"]):
            missing = [n for n in ("wayvnc", "novnc") if not have[n]]
            print(f"! {' and '.join(missing)} not installed — the packages that make this work.")
            print(f"    sudo apt install {' '.join(missing)}")
            sys.exit(1)
        res = call("/api/screen/control", {"action": "start" if args.on else "stop"})
        if res.get("error"):
            print(f"✗ {res['error']}")
            sys.exit(1)
        print("✓ remote desktop " + ("on" if args.on else "off"))

    st = call("/api/screen/control")
    if st.get("error"):
        print(f"  ({st['error']})")
        return
    print(f"  wayvnc installed : {st.get('installed')}")
    print(f"  noVNC client     : {st.get('novnc')}")
    print(f"  running          : {st.get('running')}")
    if st.get("running"):
        from . import remote as remotemod
        print("  open on your phone:")
        for a in (remotemod.lan_addresses(port) or [f"http://127.0.0.1:{port}"]):
            print(f"    {a.rstrip('/')}/remote-desktop")
        print("  (sign in with your AgentOS passphrase; the VNC port stays on 127.0.0.1)")


def _flow_cli(args):
    """`agentos flow` — the control plane from a terminal.

    Runs, boards and approvals go over the local HTTP API, because a flow is a live thing
    the running server owns; listing and hooks read the store directly so they still work
    with the server down. Answering an approval from here is the point: until this
    existed, a flow started from a terminal could only be watched failing.
    """
    import urllib.error
    import urllib.request

    from . import config as cfgmod
    from . import flows as flowsmod
    cfg, store = _open_store()
    base = f"http://127.0.0.1:{cfg.get('port', 8321)}"

    def call(path, data=None, method=None):
        req = urllib.request.Request(
            base + path, method=method or ("POST" if data is not None else "GET"),
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return {"error": json.loads(e.read() or b"{}").get("error", str(e))}
        except Exception as e:                                    # noqa: BLE001
            return {"error": f"{e} — is AgentOS running? (agentos serve)"}

    act = args.action
    if act == "list":
        rows = store.list_flows()
        if not rows:
            print("no flows yet — make one in Workflows → Flows, or with the API")
            return
        for f in rows:
            trigs = store.flow_triggers(f["name"])
            last = [r for r in store.fabric_runs(limit=60)
                    if (r.get("flow") or "") == f["name"]]
            print(f"\n▲ {f['name']}{'' if f['enabled'] else '  (disabled)'}")
            print(f"    {(f.get('mission') or '')[:90]}")
            print(f"    roster: {', '.join(r['subagent'] for r in f['roster']) or '—'}")
            print(f"    starts: {', '.join(t['kind'] for t in trigs) or 'only when you say so'}")
            if last:
                print(f"    last:   {last[0]['status']} · "
                      f"{time.strftime('%d %b %H:%M', time.localtime(last[0]['started_at']))}")
        return

    if act == "hooks":
        hooks = store.flow_triggers(args.name, kind="webhook")
        if not hooks:
            print(f"'{args.name}' has no webhook trigger — add one in Workflows → Flows")
            return
        for t in hooks:
            url = flowsmod.hook_url(cfg, args.name, t)
            print(f"\n  curl -X POST '{url}' -d '{{\"hello\":\"world\"}}'")
            print("  (or send the secret as the X-AgentOS-Hook-Secret header)")
            print(f"  fired {t['fires']}×, {t['dropped']} refused by the "
                  f"{t['cooldown_secs']}s cooldown")
        return

    if act == "approvals":
        res = call("/api/fabric/approvals")
        if res.get("error"):
            print(f"✗ {res['error']}")
            sys.exit(1)
        rows = res.get("approvals") or []
        if not rows:
            print("nothing is waiting on you")
            return
        for a in rows:
            print(f"\n  {a['id']}  {a['name']}  {json.dumps(a.get('args') or {})[:80]}")
            print(f"      {a.get('flow') or a.get('run_id', '')[:8]} · {a.get('reason', '')[:120]}")
        print("\n  agentos flow allow <id> [--always]   |   agentos flow deny <id>")
        return

    if act in ("allow", "deny"):
        res = call(f"/api/fabric/approvals/{args.name}",
                   {"approved": act == "allow", "remember": bool(args.always)})
        print("✓ answered" if not res.get("error") else f"✗ {res['error']}")
        return

    if act == "show":
        res = call(f"/api/fabric/runs/{args.name}")
        if res.get("error"):
            print(f"✗ {res['error']}")
            sys.exit(1)
        run = res["run"]
        print(f"▲ {run.get('flow') or run['ref']} · {run['status']} · model {run.get('model') or '—'}")
        for s in res.get("steps") or []:
            print(f"  ├─ {s['ref']:<14} {s['status']:<9} "
                  f"{(s.get('tokens_in') or 0) + (s.get('tokens_out') or 0):>6} tok")
        board = call(f"/api/flows/runs/{args.name}/board").get("board") or []
        for a in board:
            print(f"  {a['handle']:<4} {(a['agent'] or a['kind']):<12} {a['status']:<8} "
                  f"{a['bytes']:>7}B  {(a['preview'] or '')[:60]}")
        if run.get("output"):
            print("\n" + run["output"][:2000])
        return

    if act == "run":
        if not args.name:
            print("which flow? (agentos flow list)")
            sys.exit(2)
        res = call(f"/api/flows/{args.name}/run",
                   {"input": args.input, "surface": "tui"})
        if res.get("error"):
            print(f"✗ {res['error']}")
            sys.exit(1)
        rid = res["run_id"]
        print(f"▶ {args.name} started · run {rid}")
        if not args.wait:
            print(f"  agentos flow show {rid}")
            return
        while True:
            time.sleep(2)
            d = call(f"/api/fabric/runs/{rid}")
            run = d.get("run") or {}
            if run.get("status") and run["status"] != "running":
                break
            for a in (call(f"/api/flows/runs/{rid}/board").get("board") or [])[-1:]:
                print(f"  · {a['handle']} {a['agent'] or a['kind']} {a['status']}")
        print(f"\n{run.get('status')} · {run.get('output') or run.get('fault') or ''}"[:4000])
        return


def _job_cli(args):
    """`bento job` — give this machine something to do, from a terminal.

    The TUI face of the first-run "give it a job" beat (CLAUDE.md: every feature in
    all three). A headless Pi is exactly where a standing job earns its keep and
    exactly where there is no wizard to run one, so the same catalogue and the same
    `jobs.install` are reachable here.

    Listing and adding go straight through the store, so they work with the server
    down; only `run` needs the running server, because a run is a live thing it owns.
    """
    import urllib.error
    import urllib.request

    from . import jobs as jobsmod
    cfg, store = _open_store()
    act = args.action

    if act == "list":
        rows = jobsmod.installed(store)
        if not rows:
            print("nothing is running yet.\n")
            print("  bento job recipes           what this machine can be asked to do")
            return
        for j in rows:
            print(f"\n▲ {j['name']}{'' if j['enabled'] else '  (off)'}")
            print(f"    {j['description']}")
            print(f"    next: {j['next']}")
        return

    if act == "recipes":
        for r in jobsmod.RECIPES:
            print(f"\n{r.icon}  {r.id}")
            print(f"    {r.title} — {r.blurb}")
            print(f"    e.g. {r.example}")
            for n in r.needs:
                if n.key == "deliver":
                    continue
                print(f"    --{n.key:<8} {n.label}"
                      + (f"  (default {n.default})" if n.default else ""))
        ways = [d for d in jobsmod.deliveries(cfg)]
        print("\n  --deliver  " + ", ".join(
            f"{d['id']}{'' if d['ready'] else ' (not set up)'}" for d in ways))
        print("\n  bento job add morning-brief --topics 'my industry' --at 08:00")
        return

    if act == "add":
        if not args.name:
            print("which recipe? (bento job recipes)")
            sys.exit(2)
        answers = {k: v for k, v in
                   (("topics", args.topics), ("folder", args.folder), ("url", args.url),
                    ("at", args.at), ("minutes", args.minutes), ("deliver", args.deliver))
                   if v}
        try:
            res = jobsmod.install(cfg, store, args.name, answers)
        except ValueError as e:
            print(f"✗ {e}")
            sys.exit(1)
        print(f"✓ {res['flow']['name']} — runs {jobsmod.describe_next(store, res['flow']['name'])}")
        for p in res.get("reads") or []:
            print(f"  reads: {p}")
        print(f"  delivers: {res['delivery']['label'].lower()}")
        if res.get("substituted"):
            print(f"  note: {res['substituted']}")
        # The clock lives in the running server's scheduler; a job added while it is
        # down is still a real row, it just starts ticking at the next start.
        print(f"\n  bento job run {res['flow']['name']}     try it now")
        return

    if act == "run":
        if not args.name:
            print("which job? (bento job list)")
            sys.exit(2)
        url = f"http://127.0.0.1:{cfg.get('port', 8321)}/api/jobs/{args.name}/run"
        req = urllib.request.Request(url, method="POST", data=b"{}",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                res = json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            print(f"✗ {json.loads(e.read() or b'{}').get('error', e)}")
            sys.exit(1)
        except OSError:
            print("✗ AgentOS is not running here — start it with `bento serve`")
            sys.exit(1)
        print(f"▶ {args.name} started · run {res['run_id']}\n  bento flow show {res['run_id']}")
        return


def _remote_cli(args):
    """`agentos remote` — the headless equivalent of Settings → Remote access,
    for machines you only ever reach over SSH (a Pi, a server)."""
    import getpass

    from . import config as cfgmod
    from . import remote as remotemod
    cfg = remotemod.sanitize_remote(cfgmod.load_config())
    r = cfg.setdefault("remote", {})

    pw = args.passphrase
    if args.on and not pw and not r.get("pass_hash"):
        pw = getpass.getpass("Set a remote-access passphrase: ")
        if pw != getpass.getpass("Repeat it: "):
            print("those did not match")
            sys.exit(1)
    if pw:
        problem = remotemod.passphrase_problem(pw)
        if problem:
            print(f"passphrase: {problem}")
            sys.exit(1)
        r["pass_hash"], r["pass_salt"] = remotemod.hash_passphrase(pw)
    if args.bind:
        r["bind"] = args.bind
    if args.on:
        if not r.get("pass_hash"):
            print("set a passphrase first: agentos remote --on --passphrase '<something long>'")
            sys.exit(1)
        r["enabled"] = True
    if args.off:
        r["enabled"] = False
    if args.on or args.off or pw or args.bind:
        remotemod.sanitize_remote(cfg)
        cfgmod.save_config(cfg)

    st = remotemod.status(cfg)
    print(f"remote access: {'ON' if st['enabled'] else 'off'}"
          f"{'' if st['configured'] else '  (no passphrase set)'}")
    print(f"  binds:   {remotemod.bind_host(cfg)}:{st['port']}")
    for a in st["addresses"]:
        print(f"  reach:   {a}")
    if st["enabled"]:
        print("  restart AgentOS for a bind change to take effect.")


# ---------------------------------------------------------------------------
# Spaces, timeline, assets, audit — the terminal face
#
# These talk to the Store directly rather than to the HTTP API, so they work on a
# machine where the server is not running (which is when you most want to read an
# audit log). Nothing here writes to the desktop's live config except `space`,
# which sets the TUI surface's own default — never the GUI's.
# ---------------------------------------------------------------------------

def _open_store():
    from . import config as cfgmod
    from .memory import Store
    return cfgmod.load_config(), Store(cfgmod.DB_PATH)


def _since_secs(text: str) -> float:
    """'24h' / '7d' / '90m' -> seconds. Anything unparseable means 'all time',
    said out loud by the caller rather than silently becoming a default window."""
    text = (text or "").strip().lower()
    if not text or text == "all":
        return 0.0
    unit, num = text[-1], text[:-1]
    mult = {"m": 60, "h": 3600, "d": 86400, "w": 604800}.get(unit)
    if not mult:
        return 0.0
    try:
        return float(num) * mult
    except ValueError:
        return 0.0


def _space_cli(args):
    from . import config as cfgmod
    from . import spaces as spacemod
    cfg, store = _open_store()

    if args.new:
        sid = store.create_space(args.new, description=args.about)
        if not sid:
            print("a space needs a name")
            return
        spacemod.set_active(cfg, "tui", sid)
        cfgmod.save_config(cfg)
        print(f"✓ created '{args.new}' and this terminal is now working in it")
        return

    if args.none:
        spacemod.set_active(cfg, "tui", "")
        cfgmod.save_config(cfg)
        print("✓ this terminal works everywhere (the shared scope)")
        return

    if args.name:
        row = store.get_space(args.name)
        if not row:
            names = ", ".join(s["name"] for s in store.list_spaces()) or "(none)"
            print(f"no space called '{args.name}'. Known spaces: {names}")
            print("  create one with:  agentos space --new '<name>' --about '<one line>'")
            sys.exit(2)
        spacemod.set_active(cfg, "tui", row["id"])
        cfgmod.save_config(cfg)
        print(f"✓ this terminal is working in '{row['name']}'")
        return

    active = (cfg.get("spaces") or {}).get("active", {}).get("tui", "")
    rows = store.list_spaces()
    print(f"this terminal works in: {spacemod.label(store, active)}")
    print("  (a space sees its own memory and facts PLUS everything true everywhere)\n")
    if not rows:
        print("  no spaces yet — everything is shared.")
        print("  agentos space --new 'Q3 launch' --about 'the launch, its people and copy'")
        return
    for s in rows:
        mark = "*" if s["id"] == active else " "
        print(f" {mark} {s['name'][:24]:<24} {(s.get('description') or '')[:52]}")
    print("\n  agentos space '<name>'   ·   agentos space --none")


def _timeline_cli(args):
    _, store = _open_store()
    cfg, _ = _open_store()
    active = (cfg.get("spaces") or {}).get("active", {}).get("tui", "")
    since = _since_secs(args.since)
    rows = store.timeline(space=active, kind=args.kind,
                          since=(time.time() - since) if since else 0.0,
                          limit=args.limit)
    if not rows:
        print(f"nothing on the timeline for the last {args.since}.")
        return
    day = ""
    for e in rows:
        d = time.strftime("%A %d %B", time.localtime(e["ts"]))
        if d != day:
            day = d
            print(f"\n{d}")
        print(f"  {time.strftime('%H:%M', time.localtime(e['ts']))}  "
              f"[{e['kind']}] {e['title']}")


def _assets_cli(args):
    import subprocess

    from . import assets as assetmod
    cfg, store = _open_store()
    active = (cfg.get("spaces") or {}).get("active", {}).get("tui", "")

    if args.action in ("path", "open", "rm"):
        if not args.id:
            print(f"agentos assets {args.action} <id>")
            sys.exit(2)
        row = store.asset_get(args.id)
        if not row:
            print(f"no asset with id {args.id}")
            sys.exit(2)
        if args.action == "rm":
            assetmod.delete(store, args.id)
            print(f"✓ deleted {args.id}")
            return
        path = assetmod.path_of(row)
        if not path:
            print(f"the file behind {args.id} is missing from disk")
            sys.exit(1)
        if args.action == "path":
            print(path)
            return
        # A terminal cannot show a picture. Where there is a display, hand it to
        # the desktop; where there is not, say so and print the path — which is
        # the useful thing over SSH anyway.
        if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            subprocess.Popen(["xdg-open", str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"opened {path} on this machine's display")
        else:
            print(f"no display on this session, so nothing can be shown here.\n{path}")
        return

    rows = store.asset_list(kind=args.kind, space=active, limit=200)
    cap = assetmod.capability()
    if not rows:
        print("no assets yet." if not args.kind else f"no {args.kind} assets.")
    for r in rows:
        size = f"{(r.get('bytes') or 0)//1024} KB"
        extra = f" {r['duration']:.0f}s" if r.get("duration") else ""
        print(f"{r['id']}  {r['kind']:<6} {size:>9}{extra:<6}  "
              f"{(r.get('title') or '')[:38]:<38} {r.get('source') or ''}")
    if not cap["ffmpeg"]:
        print(f"\n{cap['why']}")
        print(f"  the '{cap['component']}' component would fix it "
              f"(offered in Settings → Components, licence in view)")


def _audit_cli(args):
    _, store = _open_store()
    since = _since_secs(args.since)
    ts = (time.time() - since) if since else 0.0
    summary = store.audit_summary(since=ts)
    eff = summary.get("effects") or {}
    print(f"access ledger — last {args.since}: "
          f"{eff.get('allow', 0)} allowed · {eff.get('deny', 0)} denied · "
          f"{eff.get('ask', 0)} asked")
    top = summary.get("top_denied") or []
    if top:
        print("\nmost refused:")
        for t in top[:5]:
            print(f"  {t['n']}×  {t['action']:<14} {t['resource'][:56]}")
    rows = store.audit_list(limit=args.limit, effect=args.effect,
                            principal_kind=args.who, surface=args.surface, since=ts)
    if not rows:
        print("\n(no matching decisions)")
        return
    print()
    for a in rows:
        who = f"{a['principal_kind']}:{a['principal_id']}" if a["principal_id"] else a["principal_kind"]
        print(f"{time.strftime('%d %b %H:%M:%S', time.localtime(a['ts']))}  "
              f"{a['effect']:<5} {a['action']:<14} {a['resource'][:44]:<44} "
              f"{who} via {a['surface'] or '?'} · {a['rule']}")


def main():
    _use_system_certs()
    # Name it after however it was invoked. `bento` and `agentos` are the same
    # program, and help text that answers with a different name than the one you
    # typed is the kind of small lie that makes people doubt the rest.
    parser = argparse.ArgumentParser(
        prog=os.path.basename(sys.argv[0]) or "bento",
        description="Bento Box AI — your machine, with a brain.")
    sub = parser.add_subparsers(dest="cmd")

    p_serve = sub.add_parser("serve", help="start the AgentOS server + UI (default)")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=0)
    p_serve.add_argument("--no-browser", action="store_true")

    p_ask = sub.add_parser("ask", help="one-shot agent run in the terminal")
    p_ask.add_argument("prompt", nargs="+")
    p_ask.add_argument("--model", default=None, help="e.g. ollama/qwen3.5:9b")
    p_ask.add_argument("--full", action="store_true", help="full autonomy (no approval prompts)")

    p_usage = sub.add_parser("usage", help="what the agent has spent — tokens, and money where the model is priced")
    p_usage.add_argument("--days", type=float, default=1.0, help="how far back (default: 1)")
    p_usage.add_argument("--by", default="model",
                         choices=["model", "day", "surface", "kind", "conversation", "space"])

    p_eval = sub.add_parser("eval", help="run the behavioural evals against a model (does the agent still behave?)")
    p_eval.add_argument("--model", action="append", default=None,
                        help="model to test; repeat to compare several (default: the configured one)")
    p_eval.add_argument("--case", action="append", default=None, help="run only this case id (repeatable)")
    p_eval.add_argument("--tag", action="append", default=None, help="run only cases with this tag")
    p_eval.add_argument("--network", action="store_true", help="include cases that need the internet")
    p_eval.add_argument("--list", action="store_true", help="list the cases and exit")
    p_eval.add_argument("--verbose", "-v", action="store_true", help="show every assertion, not just failures")
    p_eval.add_argument("--json", action="store_true", help="print the raw report")

    p_fwd = sub.add_parser("forward", help="make this machine answer with another agent (or show what it does now)")
    p_fwd.add_argument("engine", nargs="?", choices=["aria", "claude-code", "off"],
                       help="omit to show the current setting; 'off' is the same as 'aria'")

    p_del = sub.add_parser("delegate", help="hand a task to an executor (Claude Code) and stream it here")
    p_del.add_argument("prompt", nargs="+")
    p_del.add_argument("--dir", default=None, help="the only folder it may touch (default: the configured workspace)")
    p_del.add_argument("--tools", default=None, help="comma-separated, e.g. Read,Grep,Edit (default: the configured envelope)")
    p_del.add_argument("--model", default=None, help="model for the executor; omit to use its own default")
    p_del.add_argument("--budget", type=float, default=None, help="hard spend ceiling in USD")

    sub.add_parser("app", help="open AgentOS as a desktop app window")
    p_doctor = sub.add_parser("doctor", help="check the environment: port conflicts, duplicate instances, Ollama/VRAM, DB health")
    p_doctor.add_argument("--fix", action="store_true", help="auto-repair what's safe; print sudo steps for the rest")
    p_doctor.add_argument("--session", action="store_true",
                          help="probe what can actually draw the desktop on this machine "
                               "(why the session came up, or did not)")
    sub.add_parser("tui", help="terminal UI — the AgentOS agent in your terminal (great over SSH)")
    sub.add_parser("setup", help="first-time setup wizard (name, model, autonomy, autostart)")
    p_install = sub.add_parser("install", help="install app launcher + boot service + login autostart")
    p_install.add_argument("--no-service", action="store_true",
                           help="launcher only; skip the background boot service")
    p_install.add_argument("--no-login", action="store_true",
                           help="don't open AgentOS automatically at login")
    sub.add_parser("uninstall", help="remove launcher + boot service")
    p_auto = sub.add_parser("autostart", help="open AgentOS at login (on) or stop (--off)")
    p_auto.add_argument("--off", action="store_true", help="disable login autostart")
    # The installer is the one entry point that has to work BEFORE anything is
    # set up — on a machine where the session packages are missing and the
    # server has never run. That is why it is a plain terminal UI rather than a
    # screen in `agentos tui`, which needs Textual and a live server.
    p_inst = sub.add_parser("installer",
                            help="terminal installer — detect this OS and install what "
                                 "AgentOS needs (re-runnable; shows what is missing)")
    p_inst.add_argument("--session", action="store_true",
                        help="only what the login session needs")
    p_inst.add_argument("--yes", action="store_true",
                        help="install everything offered without asking (still prints "
                             "every package and licence first)")
    p_sess = sub.add_parser("install-session",
                            help="add AgentOS as a login session (Linux only) — pick it at the login screen, "
                                 "or --autologin to boot straight into it")
    p_sess.add_argument("--wayland", action="store_true",
                        help="the sway-based Wayland session (default)")
    p_sess.add_argument("--x11", action="store_true",
                        help="the older X11 kiosk session instead")
    p_sess.add_argument("--autologin", action="store_true",
                        help="boot tty1 straight into AgentOS, no login screen (reversible; prints the escape hatch)")
    p_sess.add_argument("--force", action="store_true",
                        help="allow --autologin over SSH")
    p_sess.add_argument("--remove", action="store_true", help="remove the AgentOS session")
    p_chan = sub.add_parser("channels", help="show or change the ways in (this window, terminal, remote, API, Telegram…) and how far each is trusted")
    p_chan.add_argument("channel", nargs="?", default="", help="channel id (omit to list them all)")
    p_chan.add_argument("--on", action="store_true", help="switch this channel on")
    p_chan.add_argument("--off", action="store_true", help="switch this channel off")
    p_chan.add_argument("--posture", default="",
                        help="how far to trust it: inherit | read_only | ask | full")
    # Telegram needs one value, WhatsApp needs four. Without this, configuring a
    # channel is a GUI-only act — which is exactly backwards for a headless machine.
    p_chan.add_argument("--link", action="store_true",
                        help="whatsapp: link this machine by QR, drawn in the terminal")
    p_chan.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="set one of this channel's fields, e.g. --set verify_token=hunter2 "
                             "(repeatable; `agentos channels <id>` lists the fields it needs)")

    p_tun = sub.add_parser("tunnel", help="show how to reach this machine from elsewhere (Tailscale / tunnel), or publish it")
    p_tun.add_argument("--on", action="store_true", help="publish AgentOS")
    p_tun.add_argument("--off", action="store_true", help="stop publishing")
    p_tun.add_argument("--public", action="store_true",
                       help="publish to the whole internet, not just your own devices")
    p_tun.add_argument("--provider", default="tailscale", help="tailscale | cloudflared")
    p_tun.add_argument("--install", action="store_true",
                       help="install the provider (cloudflared) into ~/.local/bin")

    # Spaces, the gallery inventory and the access ledger from a terminal. Each of
    # these is a real capability, so each needs a way in with no pointer — a
    # headless server is exactly where you audit what ran overnight.
    p_space = sub.add_parser("space", help="show or switch the space this terminal works in")
    p_space.add_argument("name", nargs="?", default="", help="space to work in (omit to list)")
    p_space.add_argument("--none", action="store_true", help="work everywhere (the shared scope)")
    p_space.add_argument("--new", default="", help="create a space with this name")
    p_space.add_argument("--about", default="", help="one line describing a new space")

    p_tl = sub.add_parser("timeline", help="what happened — runs, assets, memory, apps")
    p_tl.add_argument("--since", default="7d", help="e.g. 24h, 7d, 30d (default 7d)")
    p_tl.add_argument("--kind", default="", help="run | asset | memory | app_version | conversation | task")
    p_tl.add_argument("--limit", type=int, default=40)

    p_assets = sub.add_parser("assets", help="list, open or remove things the agent made")
    p_assets.add_argument("action", nargs="?", default="list",
                          choices=["list", "path", "open", "rm"])
    p_assets.add_argument("id", nargs="?", default="", help="asset id, for path/open/rm")
    p_assets.add_argument("--kind", default="", help="image | video | audio | doc")

    p_audit = sub.add_parser("audit", help="the access ledger — who was allowed to do what")
    p_audit.add_argument("--since", default="24h", help="e.g. 1h, 24h, 7d (default 24h)")
    p_audit.add_argument("--effect", default="", choices=["", "allow", "deny", "ask"])
    p_audit.add_argument("--who", default="", help="user | app | subagent | workflow | system")
    p_audit.add_argument("--surface", default="", help="gui | tui | telegram | api | task")
    p_audit.add_argument("--limit", type=int, default=50)

    p_flow = sub.add_parser("flow", help="flows — standing missions run by a master orchestrator")
    p_flow.add_argument("action", nargs="?", default="list",
                        choices=["list", "run", "show", "approvals", "allow", "deny", "hooks"])
    p_flow.add_argument("name", nargs="?", default="",
                        help="flow name, or a run id for `show`, or an approval id")
    p_flow.add_argument("--input", default="", help="what to hand the flow")
    p_flow.add_argument("--wait", action="store_true", help="stay attached until it finishes")
    p_flow.add_argument("--always", action="store_true",
                        help="with `allow`: remember it as a grant, not just this once")

    p_job = sub.add_parser("job", help="give this machine a standing job — the terminal "
                                       "half of the first-run 'give it a job' screen")
    p_job.add_argument("action", nargs="?", default="list",
                       choices=["list", "recipes", "add", "run"])
    p_job.add_argument("name", nargs="?", default="", help="recipe id for `add`, job name for `run`")
    p_job.add_argument("--topics", default="", help="morning-brief: what to keep an eye on")
    p_job.add_argument("--folder", default="", help="folder-watch: the one folder it may read")
    p_job.add_argument("--url", default="", help="page-watch: the page to check")
    p_job.add_argument("--at", default="", help="time of day, HH:MM")
    p_job.add_argument("--minutes", default="", help="how often, in minutes")
    p_job.add_argument("--deliver", default="", help="report | notify | telegram")

    p_remote = sub.add_parser("remote", help="show or change remote access (reach this desktop from your phone)")
    p_remote.add_argument("--on", action="store_true", help="enable remote access (needs a passphrase)")
    p_remote.add_argument("--off", action="store_true", help="disable it and go back to loopback only")
    p_remote.add_argument("--passphrase", default="", help="set the sign-in passphrase (prompted if omitted)")
    p_remote.add_argument("--bind", default="", help="interface to listen on once enabled (default 0.0.0.0)")

    # Every graphical capability needs a way in from a terminal too — a headless
    # Pi reached over SSH is a first-class way to run AgentOS, not an edge case.
    p_apps = sub.add_parser("apps", help="find, install and remove native applications")
    p_apps.add_argument("action", nargs="?", default="list",
                        choices=["list", "search", "install", "remove"])
    p_apps.add_argument("name", nargs="?", default="", help="query, or the package to act on")
    p_apps.add_argument("--backend", default="", help="flatpak, apt, dnf or pacman")

    p_rd = sub.add_parser("remote-desktop",
                          help="the browser remote desktop — use the real screen from a phone")
    p_rd.add_argument("--on", action="store_true", help="start it")
    p_rd.add_argument("--off", action="store_true", help="stop it")

    p_mode = sub.add_parser("session", help="show or pin the desktop run mode (auto | de | hosted | kiosk)")
    p_mode.add_argument("action", nargs="?", default="show", choices=["show", "mode", "run"])
    p_mode.add_argument("value", nargs="?", default="",
                        help="with `mode`: auto, de, hosted or kiosk")

    args = parser.parse_args()
    if args.cmd == "doctor":
        doctor(fix=getattr(args, "fix", False), session=getattr(args, "session", False))
    elif args.cmd == "ask":
        ask(" ".join(args.prompt), args.model, args.full)
    elif args.cmd == "eval":
        eval_cmd(args)
    elif args.cmd == "usage":
        usage_cmd(args)
    elif args.cmd == "forward":
        forward_cmd(args.engine)
    elif args.cmd == "tunnel":
        tunnel_cmd(args.on, args.off, args.public, args.provider, args.install)
    elif args.cmd == "channels":
        channels_cmd(args.channel, args.on, args.off, args.posture, args.set,
                     link=args.link)
    elif args.cmd == "delegate":
        delegate(" ".join(args.prompt), args.dir, args.tools, args.model, args.budget)
    elif args.cmd == "app":
        from . import desktop
        desktop.app_mode()
    elif args.cmd == "setup":
        from . import setup as setupmod
        setupmod.run_cli_wizard()
    elif args.cmd == "tui":
        from . import config as cfgmod
        if cfgmod.is_first_run():
            from . import setup as setupmod
            setupmod.run_cli_wizard()
        try:
            from . import tui_app          # full-screen Textual UI
            tui_app.run()
        except ImportError:
            import asyncio as _a            # fallback: simple REPL
            from . import clitui
            try:
                _a.run(clitui.run_tui())
            except KeyboardInterrupt:
                pass
    elif args.cmd == "installer":
        from . import installer
        raise SystemExit(installer.run(session_only=args.session, assume_yes=args.yes))
    elif args.cmd == "install":
        from . import desktop
        desktop.install(autostart=not args.no_service, open_at_login=not args.no_login)
    elif args.cmd == "uninstall":
        from . import desktop
        desktop.uninstall()
    elif args.cmd == "autostart":
        from . import desktop
        desktop.enable_login_app(not args.off)
    elif args.cmd == "install-session":
        from . import session
        if args.remove:
            session.remove(autologin=args.autologin)
        else:
            session.install(wayland=not args.x11, autologin=args.autologin,
                            force=args.force)
    elif args.cmd == "space":
        _space_cli(args)
    elif args.cmd == "timeline":
        _timeline_cli(args)
    elif args.cmd == "assets":
        _assets_cli(args)
    elif args.cmd == "audit":
        _audit_cli(args)
    elif args.cmd == "flow":
        _flow_cli(args)
    elif args.cmd == "job":
        _job_cli(args)
    elif args.cmd == "remote":
        _remote_cli(args)
    elif args.cmd == "apps":
        _apps_cli(args)
    elif args.cmd == "remote-desktop":
        _remote_desktop_cli(args)
    elif args.cmd == "session":
        from . import config as cfgmod
        from . import runmode
        if args.action == "run":     # Exec target of the packaged session entry
            from . import session
            session.run_session()
            return
        cfg = cfgmod.load_config()
        if args.action == "mode" and args.value:
            if args.value not in runmode.CHOICES:
                print(f"mode must be one of: {', '.join(runmode.CHOICES)}")
                sys.exit(2)
            cfg.setdefault("desktop", {})["mode"] = args.value
            cfgmod.save_config(cfg)
            print(f"✓ desktop.mode = {args.value}  (takes effect on the next server start)")
        effective, detected = runmode.resolve(cfg)
        pin = cfg.get("desktop", {}).get("mode", "auto")
        print(f"mode: {effective}  (detected: {detected}, pinned: {pin})")
        print(f"  {runmode.describe(effective)}")
    else:
        host = getattr(args, "host", "127.0.0.1")
        port = getattr(args, "port", 0)
        no_browser = getattr(args, "no_browser", False)
        serve(host, port, not no_browser)


if __name__ == "__main__":
    main()
