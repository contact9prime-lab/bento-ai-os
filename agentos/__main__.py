"""Entry point: `agentos` serves the UI; `agentos ask "..."` runs a one-shot agent in the terminal."""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
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


def _holder(host: str, port: int) -> str:
    """Who holds `port`: 'free', 'agentos', or 'foreign'.

    The distinction decides whether stopping it may even be OFFERED. "Something is
    listening" is not permission to kill it — a port collision is just as likely to
    be somebody's dev server, and an installer that terminates it because the number
    matched would be a far worse bug than the one it was solving.

    Identification is by answer, not by pid or process name: a two-line JSON reply
    that only this server produces. Two shapes count, and the second matters as much
    as the first — a machine with accounts answers 401 to everything until you sign
    in, and that is a RUNNING AgentOS, not a broken one.
    """
    if _port_free(host, port):
        return "free"
    import json as _json
    import urllib.error
    import urllib.request

    probe = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    try:
        with urllib.request.urlopen(f"http://{probe}:{port}/api/platform", timeout=4) as r:
            body = _json.loads(r.read() or b"{}")
        # keys only host.platform_state() produces
        return "agentos" if {"mode", "sui_available"} <= set(body) else "foreign"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            try:
                return ("agentos" if _json.loads(e.read() or b"{}").get("login") == "/login"
                        else "foreign")
            except Exception:
                return "foreign"
        return "foreign"
    except Exception:
        # Holds the port but does not speak HTTP, or refused us. Not ours to touch.
        return "foreign"


def _next_free_port(host: str, start: int, span: int = 40) -> int:
    """The first free port at or above `start`, or 0 if the whole span is taken."""
    return next((p for p in range(start, start + span) if _port_free(host, p)), 0)


def _second_instance_warning() -> str:
    """What a second server on another port actually costs.

    Not a scary noise: every item is something `startup()` unconditionally creates,
    against `cfgmod.DB_PATH`, which is one file per AGENTOS_HOME and not per port.
    Two schedulers fire every standing job twice; Telegram's getUpdates admits ONE
    long-poller per bot token, so two of them take turns losing messages. Somebody
    who wants a genuinely separate instance wants a separate home, and that is the
    one line at the end.
    """
    return (
        "  Both would share ~/.agentos: one database, two schedulers (every job\n"
        "  fires twice), two Telegram/WhatsApp pollers on one account, two update\n"
        "  watchers. Fine for a quick look; not something to leave running.\n"
        "  A truly separate instance needs a separate home:\n"
        "    AGENTOS_HOME=~/.agentos-test bento serve --port <n>")


def _resolve_running_instance(host: str, port: int, url: str, mode: str,
                              explicit_port: bool) -> int:
    """A server already holds the port. Decide what this invocation does instead.

    Returns the port to serve on, or raises SystemExit. Called before anything binds
    or writes, because the old behaviour — print four suggestions and exit 3 — put
    the whole decision on somebody who had just typed the most obvious command there
    is, and made the commonest case (it is already running; show it to me) the one
    thing the CLI would not do.

    `mode` is --if-running. It defaults to `ask`, and `ask` degrades to `fail` with
    no terminal to ask on: a service unit or a CI step must never block on a prompt,
    and a boot that silently chose "restart" would be worse still.
    """
    from . import desktop

    who = _holder(host, port)
    if who == "free":                       # a race: it went away while we looked
        return port

    if who == "foreign":
        # Never offer to stop this. We have no evidence it is ours.
        alt = _next_free_port(host, port + 1)
        print(f"Something holds {host}:{port}, and it did not answer as AgentOS.\n"
              f"  It may be another program that happens to use this port.\n"
              f"  AgentOS will not stop a process it cannot identify.\n"
              f"  what it is:   bento doctor"
              + (f"\n  free port:    bento serve --port {alt}" if alt else ""))
        raise SystemExit(3)

    st = desktop.service_status()
    supervised = st["manager"] != "none"
    owner = {"systemd": "a systemd user service", "launchagent": "a launchd LaunchAgent",
             "startup": "a Windows Startup entry",
             "none": "started by hand — nothing supervises it"}[st["manager"]]

    if mode == "fail":
        print(f"AgentOS is already running on {url} ({owner}).\n"
              f"  open it:      {url}\n"
              f"  details:      bento service status\n"
              f"  restart it:   bento service restart\n"
              f"  second one:   bento serve --port <other>   (see --if-running)")
        raise SystemExit(3)

    if mode == "open":
        print(f"▲ AgentOS is already running — {url}")
        webbrowser.open(url)
        raise SystemExit(0)

    if mode == "port":
        alt = _next_free_port(host, port + 1)
        if not alt:
            print(f"AgentOS is running on {url} and no free port was found near it.")
            raise SystemExit(3)
        print(f"▲ already running on {port}; starting a second instance on {alt}")
        print(_second_instance_warning())
        return alt

    if mode == "restart":
        return _take_the_port(url, supervised, port, host)

    # ---- ask ---------------------------------------------------------------
    alt = _next_free_port(host, port + 1)
    print(f"\n▲ AgentOS is already running.\n"
          f"    {url}   ({owner}"
          + (f", pid {st['pid']}" if st["pid"] else "") + ")\n")
    print("  [o] open it in a browser                        (default)")
    print(f"  [r] restart it{'' if supervised else ' — stop it and run here'}")
    if alt:
        print(f"  [p] leave it, and start a second one on port {alt}")
    print("  [q] quit, change nothing")
    try:
        choice = input("  ? ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(3)

    if choice in ("", "o", "open"):
        print(f"  opening {url}")
        webbrowser.open(url)
        raise SystemExit(0)
    if choice in ("r", "restart"):
        return _take_the_port(url, supervised, port, host)
    if choice in ("p", "port") and alt:
        print(_second_instance_warning())
        return alt
    raise SystemExit(3)


def _take_the_port(url: str, supervised: bool, port: int, host: str) -> int:
    """`restart`: hand the port back, by whichever route keeps the promise the
    machine is already making.

    Where a supervisor owns the server, restarting THROUGH it is the honest answer
    and this process then has nothing left to do — killing the unit so that a
    foreground `serve` can take the port would silently downgrade a machine that
    comes back after a reboot into one that does not. Where nothing supervises it,
    the caller asked to run it here, so stop the old one and continue.
    """
    from . import desktop

    if supervised:
        ok, msg = desktop.service_restart()
        print(("✓ " if ok else "✗ ") + msg)
        print("  (its supervisor still owns it, so this terminal is free to close)")
        raise SystemExit(0 if ok else 1)

    ok, msg = desktop.service_stop()
    if not ok:
        print("✗ " + msg)
        raise SystemExit(1)
    print("✓ " + msg)
    for _ in range(30):
        if _port_free(host, port):
            return port
        time.sleep(0.5)
    print(f"✗ port {port} did not come free after stopping the old server")
    raise SystemExit(3)


def _server_answers(port: int, timeout: float = 1.5) -> bool:
    """Is the server up AND serving the desktop — not merely holding the port?

    Uvicorn does not accept connections until the FastAPI startup hook has finished,
    so a completed HTTP request means the whole stack is live: config, database,
    routes. Anything under 500 counts, and 401 counts too — a machine with accounts
    is locked, and locked is running.
    """
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/platform",
                                    timeout=timeout) as r:
            return r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


def _open_when_ready(url: str, port: int, timeout: float = 90.0) -> None:
    """Open the browser once the server answers, in a thread — never on a timer.

    This was `threading.Timer(1.2, …)`: open the browser 1.2 seconds from now and hope.
    On the machine it was written on the server was up by then. On a first run — an
    empty database to create, a cold import, a Pi — it is not, so the browser arrives
    at a connection-refused page for a server that comes up two seconds later and
    works perfectly. Nothing is broken and there is nothing to fix; the tab is just
    wrong, and the user has to know to reload it.

    A daemon thread because `uvicorn.run` owns the main one from here on. On timeout
    it prints instead of opening: a tab showing an error is worse than no tab, because
    it looks like a verdict on the server rather than on the waiting.
    """
    def wait():
        deadline = time.time() + timeout
        while time.time() < deadline:
            if _server_answers(port):
                webbrowser.open(url)
                return
            time.sleep(0.25)
        print(f"\n  (the server has not answered after {int(timeout)}s — not opening a "
              f"browser at something that is not there yet.\n"
              f"   it may still come up; then open {url})")

    threading.Thread(target=wait, daemon=True).start()


def serve(host: str, port: int, open_browser: bool, if_running: str = "ask"):
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
    # Resolve a collision BEFORE anything binds or writes. The old code bailed here
    # too, and for the right reason — a doomed instance must not spawn MCP servers,
    # the scheduler or the Telegram poller against the database the instance that
    # actually owns the port is using. What it did not do was answer the question:
    # it printed four suggestions and exited 3, leaving the commonest case (it is
    # already running; show me) as the one thing the CLI would not do for you.
    # Ask the kernel ONCE, and branch on what it actually said. `_port_free` collapses
    # every bind failure into "not free", which sent a privileged port down the
    # already-running path — where it was probed over HTTP, did not answer, and was
    # reported as "something holds :80 that is not AgentOS". Nothing held it. The
    # kernel had refused us, and the message pointed at an innocent bystander.
    kind, why = _bind_problem(host, port)
    if kind in ("denied", "no-such-address", "other"):
        print(f"\n✗ AgentOS cannot listen on {host}:{port}.")
        print(why)
        sys.exit(4)

    if kind == "taken":
        mode = if_running
        if mode == "ask" and not (sys.stdin.isatty() and sys.stdout.isatty()):
            # No terminal to ask on. A systemd unit, a cron line or a CI step must
            # never block on a prompt, and picking an action for them unasked is
            # worse — `restart` from a boot script is a restart loop.
            mode = "fail"
        port = _resolve_running_instance(host, port, _display_url(host, port),
                                         mode, explicit_port=bool(port))

    os.environ["AGENTOS_BOUND_HOST"] = host
    # The port this instance actually bound, which is not always the configured one:
    # `--port` wins, `--if-running=port` moves it, and `desktop.restart_service()`
    # re-execs `serve` with no memory of the command line it is replacing. Without
    # this, restarting a server on any other port relaunched it on the default, where
    # it either collided with whatever was there and exited 3, or quietly moved — and
    # the update and snapshot-restore flows both end in that same re-exec.
    os.environ["AGENTOS_BOUND_PORT"] = str(port)
    # Never the bind host verbatim: 0.0.0.0 is not a clickable address.
    url = _display_url(host, port)
    print(f"""
  ┌─────────────────────────────────────┐
  │   ▲ AgentOS                         │
  │   your machine, with a brain        │
  │                                     │
  │   {url:<34}│
  └─────────────────────────────────────┘
""")
    # Say it BEFORE the URL scrolls away, and say it on every start until it is
    # done. On a headless machine the browser wizard is a screen nobody is sitting
    # in front of, so "it is set up when you open it" is not true here — the arc has
    # a terminal face and this is the only place that names it.
    try:
        if cfgmod.is_first_run():
            print("  ▲ this machine has not been set up yet.")
            print("    over SSH:  bento setup   — name it, give it a brain, put it to work")
            print("    or open the address above: the wizard is the first thing you see.\n")
    except Exception:
        pass                  # a banner is never a reason for a server not to start
    if remotemod.enabled(cfg):
        print("  remote access is ON — this desktop is reachable from your network:")
        for a in remotemod.lan_addresses(port):
            print(f"    {a}")
        print("  sign in with your passphrase; local use is unchanged.\n")
    if open_browser:
        _open_when_ready(url, port)
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


def profile_cmd(want: str | None):
    """Show or set the footprint profile — the Pi switch.

    The TUI face of it, and the one the installer calls for `--lite`. Printing
    what it changes rather than just the word: a profile whose effects are not on
    screen is a machine behaving differently for reasons nobody can see.
    """
    from . import config as cfgmod
    from . import mcp_store as mcpmod
    from . import profile as profmod

    cfg = cfgmod.load_config()
    if not want:
        print(f"profile: {profmod.describe(cfg)}")
        m = profmod.machine()
        print(f"  machine:   {m['ram_mb']} MB RAM · {m['cores']} cores · {m['arch']}"
              + (f" · {m['board']}" if m["board"] else ""))
        try:
            size = mcpmod.INDEX_PATH.stat().st_size
            print(f"  MCP cache: {size // 1024} kB at {mcpmod.INDEX_PATH}")
        except OSError:
            print("  MCP cache: nothing on disk")
        print()
        print("  bento profile lite   # fetch the MCP catalogue only while you search")
        print("  bento profile full   # keep it, refresh it daily")
        print("  bento profile auto   # decide from this machine")
        return
    ok, msg = profmod.apply(cfg, want)
    if not ok:
        print(msg)
        raise SystemExit(2)
    cfgmod.save_config(cfg)
    print(f"profile: {msg}")
    # Light mode means nothing kept, so the cache goes NOW rather than at the next
    # maintenance pass — somebody switching to lite on a full SD card is asking
    # for the space back today.
    if profmod.settings(cfg)["mcp_cache"] == "discard":
        try:
            size = mcpmod.INDEX_PATH.stat().st_size
            mcpmod.INDEX_PATH.unlink()
            print(f"  deleted the MCP catalogue cache ({size // 1024} kB) — "
                  f"the next search fetches it again")
        except OSError:
            pass
    print("  a running server picks this up on its next maintenance pass")


def brain_cmd(executor: str | None, model: str | None):
    """Read or set the brain: which executor answers, and which of ITS models.

    The TUI face of Settings → AI providers. `bento forward` remains the narrow
    "answer as another agent" switch; this is the whole choice, and it is the one
    that matters on a headless box — over SSH there is no picker and no chip, so
    the list prints what could answer, what it would run on, and why anything
    missing is missing.
    """
    import asyncio as _aio

    from . import config as cfgmod
    from . import executors as execmod
    from . import providers as provmod

    cfg = cfgmod.load_config()
    try:
        models = _aio.run(provmod.available_models(cfg))
    except Exception as exc:                       # a provider that cannot be asked
        print(f"(could not ask every provider: {exc})")
        models = []
    state = execmod.brains(cfg, models)
    cur = state["current"]

    if not executor:
        print(f"answering with: {cur['executor'] or '(nothing set)'}"
              + (f" · {cur['model']}" if cur["model"] else ""))
        print()
        for e in state["executors"]:
            mark = "▸" if e["id"] == cur["executor"] else " "
            head = f" {mark} {e['id']:<12} {e['name']}"
            print(head + (f"  [{e['detail']}]" if e["detail"] else ""))
            if not e["available"]:
                print(f"      {e['reason']}")
                if e["install_cmd"]:
                    print(f"      install: {e['install_cmd']}")
                continue
            names = ", ".join(m["id"] or "(its own default)" for m in e["models"][:8])
            print(f"      models: {names}"
                  + (f" … +{len(e['models']) - 8}" if len(e["models"]) > 8 else ""))
        print()
        print("set it with:  bento brain <executor> [model]")
        return

    ok, msg = execmod.set_brain(cfg, executor, model or "", models)
    if not ok:
        print(msg)
        raise SystemExit(1)
    cfgmod.save_config(cfg)
    print(f"answering with {msg}")
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


def _wrap_plain(text: str, indent: int, width: int = 78) -> str:
    """Wrap to the terminal, continuation lines aligned under the first.

    A four-step walkthrough printed as four unbroken lines is unreadable in an
    80-column SSH session, which is the only place this view is really used.
    """
    import textwrap
    return textwrap.fill(text, width=width, subsequent_indent=" " * indent).strip()


def folders_cmd(action: str, path: str, mode: str, users: str) -> None:
    """Show or change the folders the agent may work in, and who may work there.

    The TUI face of Settings → Sandbox → Safe folders. It matters most exactly
    where there is no settings window: the server nobody logs into is the one
    whose data folders somebody has to open up over SSH.

    Sharing is an ADMIN act — /api/config already refuses a non-admin the whole
    `sandbox` key — and this writes the same setting, so a machine with accounts
    should be administered by someone who has one.
    """
    from . import config as cfgmod
    from .tools import (FOLDER_MODES, check_safe_folder, folder_problems,
                        folder_risk, folder_shares)

    cfg = cfgmod.load_config()

    def _show():
        shares = folder_shares(cfg)
        if not shares:
            print("  no shared folders — the agent works in the workspace only")
        for sh in shares:
            who = ", ".join(sh["users"]) if sh["users"] else "everyone"
            print(f"  {sh['mode']:<3} {sh['path']:<44} {who}")
            # The caution belongs in the LIST as well as at the moment of adding:
            # whoever reviews what this machine has opened up is usually not the
            # person who opened it.
            if (risk := folder_risk(sh["path"], sh["mode"])):
                print(f"      ⚠ {risk}")
        for entry, why in folder_problems(cfg):
            print(f"  !   {entry:<44} not in use — {why}")

    if action in ("", "list"):
        _show()
        print("\n  bento folders add /data/reports --mode ro --users ada,bob")
        return

    raw = list((cfg.get("sandbox") or {}).get("folders") or [])
    if action == "add":
        if not path:
            print("  which folder? e.g. bento folders add /data/reports"); return
        p, why = check_safe_folder(path)
        # Refuse at the point of decision. Writing an entry that the loader will
        # drop is how a setting comes to list a folder nobody can use.
        if not p:
            print(f"  refused: {why}"); return
        if mode not in FOLDER_MODES:
            print(f"  mode is one of {', '.join(FOLDER_MODES)}"); return
        who = [u.strip() for u in (users or "").replace(",", " ").split() if u.strip()]
        raw = [r for r in raw if _folder_path_of(r) != p]      # replace, never duplicate
        raw.append({"path": p, "mode": mode, "users": who})
        cfg.setdefault("sandbox", {})["folders"] = raw
        cfgmod.save_config(cfg)
        print(f"  shared {p} ({mode}) with {', '.join(who) if who else 'everyone'}")
        if (risk := folder_risk(p, mode)):
            print(f"  ⚠ {risk}")
        return
    if action == "remove":
        p = os.path.realpath(os.path.expanduser(path or ""))
        keep = [r for r in raw if _folder_path_of(r) != p]
        if len(keep) == len(raw):
            print(f"  not shared: {p}"); return
        cfg.setdefault("sandbox", {})["folders"] = keep
        cfgmod.save_config(cfg)
        print(f"  no longer shared: {p}")
        return
    print("  usage: bento folders [list|add|remove] [PATH] [--mode ro|rw] [--users a,b]")


def _folder_path_of(entry) -> str:
    """The real path of a configured entry, in either shape."""
    raw = entry if isinstance(entry, str) else (entry or {}).get("path") or ""
    return os.path.realpath(os.path.expanduser(str(raw)))


def channels_cmd(channel: str | None, on: bool, off: bool, posture: str | None,
                  sets: list | None = None):
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
            # "needs Bot token" names the gap and not the way out of it, and this is
            # the surface where that hurts most: a headless box has no Settings panel
            # to go and read. Only for what is actually unconfigured — a working
            # channel does not need reminding how it was set up.
            if c["status"] == "needs" and c.get("setup"):
                for i, line in enumerate(c["setup"], 1):
                    # The registry marks emphasis for the desktop; a terminal wants
                    # the words, not the asterisks.
                    plain = line.replace("**", "").replace("`", "")
                    print(f"        {i}. {_wrap_plain(plain, 11)}")
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
    known = {f.key for f in chmod.BY_ID[channel].fields}
    for pair in (sets or []):
        key, _, val = str(pair).partition("=")
        key = key.strip()
        if key not in known:
            print(f"  {chmod.BY_ID[channel].title} has no field '{key}'"
                  + (f" — it takes: {', '.join(sorted(known))}" if known else ""))
            return
        patch[key] = val
    if channel == "whatsapp" and (getattr(args, "pair", False)
                                  or getattr(args, "unpair", False)):
        _whatsapp_pair_cli(cfg, unpair=getattr(args, "unpair", False))
        return
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


def _qr_ascii(data: str) -> str:
    """A scannable QR in a terminal, with no new dependency.

    `qrcode` is not a dependency of AgentOS and adding one for a pairing screen
    would be a poor trade, so this encodes it here. Two rows per line via the
    half-block character, because a QR drawn one row per line is twice as tall as
    most terminals and scans badly when it wraps.
    """
    try:
        import qrcode                      # present on some machines; use it if so
        q = qrcode.QRCode(border=1)
        q.add_data(data)
        q.make(fit=True)
        m = q.get_matrix()
    except Exception:
        return ""
    out = []
    for y in range(0, len(m), 2):
        row = ""
        for x in range(len(m[0])):
            top, bot = m[y][x], (m[y + 1][x] if y + 1 < len(m) else False)
            row += "█" if top and bot else "▀" if top else "▄" if bot else " "
        out.append(row)
    return "\n".join(out)


def _whatsapp_pair_cli(cfg: dict, unpair: bool = False):
    """Link this machine to WhatsApp from a terminal.

    The QR is the whole reason this verb exists. On a headless box there is no
    browser to render one, and telling somebody to "open Settings → Channels" on a
    machine with no screen is the kind of instruction that makes a feature
    theoretical. So it is drawn here, in the terminal, and failing that the raw
    payload is printed so it can be turned into a QR anywhere.
    """
    import json as _json
    import urllib.request
    from . import wa_baileys

    base = f"http://127.0.0.1:{cfg.get('port', 8321)}"

    def api(path, method="GET"):
        req = urllib.request.Request(base + path, method=method)
        with urllib.request.urlopen(req, timeout=180) as r:
            return _json.loads(r.read() or b"{}")

    if unpair:
        try:
            api("/api/whatsapp/link", method="DELETE")
            print("✓ unlinked — the device credentials and the paired chat are gone")
        except Exception as e:
            print(f"could not reach the AgentOS server at {base}: {e}")
            sys.exit(1)
        return

    gap = wa_baileys.why_not()
    if gap:
        # The component ladder, in a terminal: say what is missing, what it costs,
        # and the exact command — then stop. Nothing installs without a yes.
        from . import components
        comp = components.CATALOG["whatsapp-bridge"]
        print(f"\n  {gap}\n")
        print(f"  {comp['title']} — {comp['licence']}")
        print(f"  {comp['unlocks']}\n")
        cmd = components.install_command(comp)
        if cmd:
            print(f"  Install it with:\n    {cmd}\n")
            print("  or from the desktop: Settings → Channels → WhatsApp → Install")
        else:
            print(f"  {components.unavailable_reason(comp)}")
        sys.exit(1)

    print("  starting the WhatsApp Web bridge…")
    try:
        d = api("/api/whatsapp/link", method="POST")
    except Exception as e:
        print(f"could not reach the AgentOS server at {base}: {e}")
        print("is it running?  systemctl --user status agentos.service")
        sys.exit(1)

    if d.get("state") == "ready":
        print("✓ already linked — this machine is connected to WhatsApp.")
        return
    qr = d.get("qr") or ""
    if not qr:
        print(f"  no pairing code arrived: {d.get('error') or d.get('state') or 'unknown'}")
        sys.exit(1)
    art = _qr_ascii(qr)
    print()
    if art:
        print(art)
    else:
        print("  (install `qrcode` to render this here: uv pip install qrcode)")
        print("  pairing payload:\n")
        print("   " + qr)
    print("\n  On your phone: WhatsApp → Settings → Linked devices → Link a device,")
    print("  and scan the code above. It expires after about 20 seconds; re-run")
    print("  this command for a fresh one.\n")
    print("  Then message this WhatsApp from your phone — the first chat to write")
    print("  becomes the owner. Check with: bento channels whatsapp")


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
    except urllib.error.HTTPError as e:
        # An ANSWER, just not one this caller is allowed to read. `/api/build/status`
        # needs a session, so on a machine with accounts doctor was accusing its own
        # healthy server of being "another app" — the one check whose whole job is
        # telling those two apart. Only a stranger fails to speak HTTP at all.
        if e.code in (401, 403):
            ok(f"server responding on 127.0.0.1:{port} (locked by this machine's accounts)")
        else:
            bad(f"port {port} answers HTTP {e.code} — something is there, but not a healthy AgentOS")
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

    # 3a. The profile — what this machine has decided to keep. On a Pi it is the
    # line that explains why the MCP Store is slower and the database smaller.
    try:
        from . import profile as profmod
        ok(f"profile {profmod.describe(cfg)}")
    except Exception as exc:
        warn(f"could not read the profile: {exc}")

    # 3b. The brain. "What will answer a turn here" is the first thing to check on
    # a headless box, and it was the one thing this report did not say — a machine
    # with no reachable model looks healthy in every other line.
    try:
        import asyncio as _aio

        from . import executors as _exec
        from . import providers as _prov
        _models = _aio.run(_prov.available_models(cfg))
        _brain = _exec.brains(cfg, _models)
        _cur, _ex = _brain["current"], None
        _ex = next((e for e in _brain["executors"] if e["id"] == _cur["executor"]), None)
        if _ex and _ex["available"]:
            ok(f"answering with {_ex['name']} · {_cur['model'] or 'its own default'}")
        elif _ex:
            bad(f"set to answer with {_ex['name']}, which cannot: {_ex['reason']}")
        else:
            warn("no brain set — nothing can answer a turn yet")
            todo("bento brain            # what could answer, and what would fix it")
    except Exception as exc:
        warn(f"could not work out what answers turns here: {exc}")

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
        # How much disk it is using, and what is using it. On an SD card this is
        # the number that matters and nothing reported it — a database that grows
        # every day is invisible until the machine cannot write at all.
        size = 0
        for suffix in ("", "-wal", "-shm"):
            try:
                size += os.path.getsize(str(cfgmod.DB_PATH) + suffix)
            except OSError:
                pass
        mb = size / 1_048_576
        rows = db.execute("SELECT count(*) FROM logs").fetchone()[0]
        ret = (cfg.get("retention") or {})
        line = f"database {mb:.1f} MB, {rows} log rows"
        if mb > 2000:
            bad(line + " — that is a lot for an SD card")
            todo("bento config retention.logs_days 7   # and restart, or prune by hand")
        elif mb > 500:
            warn(line)
        else:
            ok(line + (" · retention off" if not ret.get("enabled", True) else
                       f" · keeping {ret.get('logs_days', 30)}d of logs"))
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
    # Safe folders, and — the point of saying anything here — the ones that are
    # configured but not being used. A folder silently dropped for a typo looks
    # exactly like one the agent is refusing to touch.
    from .tools import folder_problems, folder_risk, folder_shares
    for sh in folder_shares(cfg):
        who = ", ".join(sh["users"]) if sh["users"] else "everyone"
        if (risk := folder_risk(sh["path"], sh["mode"])):
            warn(f"safe folder {sh['mode']}: {sh['path']} ({who}) — {risk}")
        else:
            ok(f"safe folder {sh['mode']}: {sh['path']}  ({who})")
    for entry, why in folder_problems(cfg):
        warn(f"safe folder not in use — {entry}: {why}")
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


def _quarantine_cli(args):
    """Quarantine from a terminal.

    Quarantine shipped with a GUI tab and nothing else, which meant that on a headless
    box — over SSH, on a Pi — an app the OS had stopped could be seen in the logs and
    never released. "Something stopped working and I cannot un-stop it" is the worst
    shape for this feature to have, so the way out exists wherever the hold does.
    """
    import json as _json
    import time
    import urllib.request
    from . import config as cfgmod

    cfg = cfgmod.load_config()
    base = f"http://127.0.0.1:{cfg.get('port', 8321)}"

    def api(path, method="GET", body=None):
        data = _json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            base + path, method=method, data=data,
            headers={"Content-Type": "application/json"} if data else {})
        with urllib.request.urlopen(req, timeout=30) as r:
            return _json.loads(r.read() or b"{}")

    try:
        if args.action == "release":
            if not args.id:
                print("which hold? run `bento quarantine list` for the ids")
                sys.exit(2)
            out = api(f"/api/quarantine/{args.id}/release", method="POST",
                      body={"mode": args.mode})
            if out.get("error"):
                print(out["error"])
                sys.exit(1)
            print({"once": "✓ released — still watched",
                   "forever": "✓ allowed forever — recorded as your decision",
                   "deleted": "✓ deleted"}[args.mode])
            return

        d = api("/api/quarantine?history=1")
        held = d.get("held") or []
        if args.action == "history":
            rows = [r for r in (d.get("history") or []) if r.get("released_at")]
            if not rows:
                print("Nothing has been released yet.")
                return
            for r in rows:
                when = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["created_at"]))
                print(f"  {when}  {r.get('label') or r.get('principal_id')} "
                      f"({r.get('principal_kind')}) → {r.get('release_mode')} "
                      f"by {r.get('released_by') or 'user'}")
            return

        if not held:
            print("Nothing is quarantined.")
            print("\nIf an app, agent or flow starts calling in a loop, the OS holds it")
            print("and it shows up here with the numbers that justified the hold.")
            return
        for q in held:
            ev = q.get("evidence") or {}
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(q["created_at"]))
            print(f"\n  {q['id']}  {q.get('label') or q.get('principal_id')} "
                  f"({q.get('principal_kind')}) — held {when}")
            print(f"    {q.get('reason', '')}")
            if ev.get("count"):
                kind = "model" if ev.get("class") == "llm" else "tool"
                print(f"    {ev['count']} {kind} calls in {round(ev.get('window', 0))}s "
                      f"— the limit is {ev.get('allowed')}")
        print("\n  bento quarantine release <id> --mode once|forever|deleted")
    except Exception as e:
        print(f"could not reach the AgentOS server at {base}: {e}")
        print("is it running?  systemctl --user status agentos.service")
        sys.exit(1)


def _mcp_cli(args):
    """MCP servers from a terminal — the TUI/headless face of the Store.

    This is not a convenience wrapper on the GUI. A machine with no screen is the
    case OAuth is hardest for: the consent page has to be opened *somewhere else*,
    so `connect` prints the URL instead of assuming a browser exists here, and the
    callback is served over HTTP so finishing it from a laptop works. Set
    `mcp_oauth.redirect_base` in the config when this box is not reachable at
    127.0.0.1 from wherever you will open that link.
    """
    import json as _json
    import urllib.request
    from . import config as cfgmod
    from . import mcp_catalog

    cfg = cfgmod.load_config()
    base = f"http://127.0.0.1:{cfg.get('port', 8321)}"

    def api(path, method="GET"):
        req = urllib.request.Request(base + path, method=method)
        with urllib.request.urlopen(req, timeout=90) as r:
            return _json.loads(r.read() or b"{}")

    if args.action == "catalog":
        by_cat: dict[str, list] = {}
        for c in mcp_catalog.all_candidates():
            by_cat.setdefault(c["category_title"], []).append(c)
        for title, entries in by_cat.items():
            print(f"\n{title}")
            for c in entries:
                print(f"  {c['key']:<12} {c['description']}")
        print("\n  bento mcp add <key>        add it and start sign-in")
        print("  bento mcp connect <name>   sign in (or sign in again)")
        return

    if args.action in ("add", "connect", "disconnect") and not args.name:
        print(f"which server? try: bento mcp {args.action} canva")
        sys.exit(2)

    try:
        if args.action == "list":
            for s in api("/api/mcp").get("servers", []):
                mark = {"connected": "✓", "authorizing": "…"}.get(s["status"], "✗")
                extra = ""
                if s.get("auth") == "oauth" and not s.get("authorized"):
                    extra = "  — not signed in: bento mcp connect " + s["name"]
                print(f"  {mark} {s['name']:<18} {s['status']:<12}"
                      f"{len(s.get('tools') or [])} tools{extra}")
            return

        if args.action == "disconnect":
            api(f"/api/mcp/oauth/{args.name}", method="DELETE")
            print(f"✓ signed out of {args.name}")
            return

        name = args.name
        if args.action == "add":
            cand = mcp_catalog.get(args.name)
            if not cand:
                print(f"'{args.name}' is not in the curated catalogue — "
                      f"see: bento mcp catalog")
                sys.exit(2)
            req = urllib.request.Request(
                base + "/api/store/mcp/install", method="POST",
                data=_json.dumps({"registry_name": cand["registry_name"]}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                name = _json.loads(r.read()).get("name", args.name)
            print(f"✓ added {name}")

        out = api(f"/api/mcp/oauth/{name}/connect", method="POST")
        if out.get("url"):
            print("\nOpen this to sign in — any browser, on any machine that can reach"
                  "\nthis one. AgentOS is waiting for you to finish:\n")
            print("  " + out["url"] + "\n")
            print("Then: bento mcp list")
        elif out.get("authorized"):
            print(f"{name} is already signed in.")
        else:
            print(f"{name} did not ask for a sign-in — check `bento mcp list` for its error.")
    except Exception as e:
        print(f"could not reach the AgentOS server at {base}: {e}")
        print("is it running?  systemctl --user status agentos.service")
        sys.exit(1)


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
    cfg, store = _open_store(getattr(args, "user", ""))
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
    cfg, store = _open_store(getattr(args, "user", ""))
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


def _bind_problem(host: str, port: int) -> tuple[str, str]:
    """Can this process bind host:port, and if not, why — ASKED, not assumed.

    ('', '') when it can. Otherwise (kind, explanation) where kind is 'denied',
    'taken', 'no-such-address' or 'other'.

    It really binds rather than reasoning from the port number, because the rule of
    thumb is wrong on a machine somebody actually owns. "Below 1024 needs root" is
    true on Linux and FALSE on macOS, which has let unprivileged processes bind low
    TCP ports for years — so a `port < 1024` warning tells half our users their
    install is broken when it is about to work perfectly. Linux itself is not fixed
    either: `net.ipv4.ip_unprivileged_port_start` is tunable and containers routinely
    ship it lowered, so even there the number does not decide. The kernel does, and
    it will answer in a microsecond if asked.
    """
    import errno
    import socket

    fam = socket.AF_INET6 if ":" in host and host != "" else socket.AF_INET
    try:
        with socket.socket(fam, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
        return "", ""
    except PermissionError:
        lines = [f"  The OS refused to let this process bind port {port}."]
        if port < 1024:
            lines.append("  Ports below 1024 are privileged, and AgentOS runs as you,"
                         " not as root.")
        lines.append("  Ways out, cheapest first:")
        if sys.platform.startswith("linux"):
            lines += [
                f"    · allow it for unprivileged processes (survives reboot):",
                f"        echo 'net.ipv4.ip_unprivileged_port_start={port}' | "
                f"sudo tee /etc/sysctl.d/50-agentos.conf",
                f"        sudo sysctl --system",
                f"    · or redirect {port} to an unprivileged port and leave AgentOS there:",
                f"        sudo nft add rule inet nat prerouting tcp dport {port} redirect to :8321",
                f"    · or put nginx/caddy in front of it",
            ]
        else:
            lines += [
                f"    · redirect {port} to an unprivileged port and leave AgentOS there",
                f"    · or put a reverse proxy in front of it",
            ]
        lines.append("  Running the server as root is not advised: the agent has a"
                     " real shell.")
        # macOS refuses 127.0.0.1:80 to a non-root process and ALLOWS 0.0.0.0:80 —
        # the privileged-port check is per-address there, not per-port. So the same
        # port can be refused on loopback and granted on the wildcard, and somebody
        # setting up a public server hits the refusal first, on the configuration
        # they are about to change. Say so rather than let them conclude it is
        # impossible.
        if host not in ("0.0.0.0", "::", "") and not _bind_problem("0.0.0.0", port)[0]:
            lines.append(f"  Note: this machine WILL allow port {port} on 0.0.0.0"
                         f" (all interfaces), just not on {host}.")
        return "denied", "\n".join(lines)
    except OSError as e:
        if e.errno in (errno.EADDRINUSE,):
            return "taken", f"  {host}:{port} is already in use."
        if e.errno in (errno.EADDRNOTAVAIL, errno.EAFNOSUPPORT):
            return "no-such-address", (
                f"  {host} is not an address this machine holds, so nothing can listen"
                f" on it.\n  0.0.0.0 listens on every interface; this machine's are:\n"
                + "\n".join(f"    {a}" for a in _local_addresses(port)))
        return "other", f"  {host}:{port} could not be bound: {e}"


def _local_addresses(port: int) -> list[str]:
    from . import remote as remotemod
    return remotemod.lan_addresses(port) or [f"http://127.0.0.1:{port}"]


def _display_url(host: str, port: int) -> str:
    """A URL a person can actually click, for a host that may be a wildcard.

    0.0.0.0 and :: are instructions to the kernel — "listen on everything" — not
    addresses. Chrome and Safari either refuse http://0.0.0.0:8321 or silently
    reinterpret it, so printing it as the way in (and handing it to
    `webbrowser.open`) offers a link that does not work, on exactly the setup
    somebody has just gone to the trouble of configuring.
    """
    return f"http://{'127.0.0.1' if host in ('0.0.0.0', '::', '') else host}:{port}"


# Keys whose VALUE must never be printed. Matched on the key name, anywhere in the
# tree, deny-by-default — not an allowlist of known-secret paths.
#
# The allowlist is what /api/config does, and it has already drifted: it masks the
# provider keys, the Telegram token and the GitHub token, and prints `remote.pass_hash`
# and every MCP server's credentials in full. A name-pattern rule covers the provider
# added next week without anybody remembering to come back here, and the cost of a
# false positive is one `--raw` away.
_SECRET_HINTS = ("key", "token", "secret", "password", "passphrase", "pass_hash",
                 "pass_salt", "credential", "auth", "cookie", "session")


def _looks_secret(key: str) -> bool:
    k = key.lower()
    return any(h in k for h in _SECRET_HINTS)


def _redact(value, key: str = ""):
    """A copy of `value` with anything secret-looking masked, preserving shape."""
    if isinstance(value, dict):
        return {k: ("•••" + str(v)[-4:] if _looks_secret(k) and isinstance(v, str) and v
                    else _redact(v, k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    if _looks_secret(key) and isinstance(value, str) and value:
        return "•••" + value[-4:]
    return value


def _dig(cfg: dict, path: str):
    """Fetch a dotted path. Raises KeyError naming the part that was missing."""
    cur = cfg
    for i, part in enumerate(path.split(".")):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(".".join(path.split(".")[:i + 1]))
        cur = cur[part]
    return cur


def _plant(cfg: dict, path: str, value) -> None:
    parts = path.split(".")
    cur = cfg
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _config_cli(args) -> int:
    """`bento config` — read and change the settings file from a terminal.

    The file has always been there (`~/.agentos/config.json`, or under AGENTOS_HOME),
    but every documented way to change it was a GUI panel or a command that happened
    to own one key — so "change the port" meant `bento remote --port`, which is
    filed under remote access and is not where anybody looks. Editing the JSON by
    hand works and is what people were doing; the failure mode is that a typo makes
    the file unparseable and the server then will not start, with no clue which
    edit did it. This validates before it writes.
    """
    import json as _json

    from . import config as cfgmod

    path = cfgmod.CONFIG_PATH
    if args.path:
        print(path)
        return 0

    if args.edit:
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
        if not shutil.which(editor.split()[0]):
            print(f"{editor} is not installed. Set $EDITOR, or edit {path} directly.")
            return 1
        # `load_config()` reads and merges defaults; it does NOT write. On a machine
        # where nothing has saved yet there is no file to open, and $EDITOR on a
        # missing path is a blank buffer — save an empty edit and the defaults are
        # replaced by nothing. Materialise it first so what you see is what is live.
        if not path.exists():
            cfgmod.save_config(cfgmod.load_config())
        before = path.read_text()
        subprocess.run([*editor.split(), str(path)], check=False)
        after = path.read_text() if path.exists() else ""
        if after == before:
            print("unchanged")
            return 0
        # The whole reason to wrap $EDITOR rather than tell people the path: a
        # half-typed comma leaves a file the server cannot read, and the next thing
        # it does is fail to start for a reason that names JSON, not the edit.
        try:
            _json.loads(after)
        except Exception as e:
            path.write_text(before)
            print(f"✗ that left invalid JSON: {e}")
            print(f"  your edit was NOT kept — {path} is back as it was.")
            return 1
        print(f"✓ saved {path}")
        print("  restart to pick it up:  bento service restart")
        return 0

    cfg = cfgmod.load_config()

    if not args.key:                                # show everything
        print(_json.dumps(_redact(cfg) if not args.raw else cfg,
                          indent=2, sort_keys=True, ensure_ascii=False))
        if not args.raw:
            print(f"\n  secrets masked; --raw shows them.  file: {path}", file=sys.stderr)
        return 0

    if args.value is None:                          # show one key
        try:
            got = _dig(cfg, args.key)
        except KeyError as missing:
            print(f"no such setting: {missing.args[0]}")
            near = [k for k in cfg if args.key.split(".")[0] in k]
            if near:
                print(f"  did you mean: {', '.join(sorted(near))}")
            return 1
        got = got if args.raw else _redact(got, args.key.split(".")[-1])
        print(got if isinstance(got, str)
              else _json.dumps(got, indent=2, sort_keys=True, ensure_ascii=False))
        return 0

    # set. JSON first so `true`, `8080` and `["a"]` arrive as the types they look
    # like; anything else is the string it was typed as, which is what makes
    # `bento config remote.bind 0.0.0.0` work without quoting rules.
    try:
        value = _json.loads(args.value)
    except Exception:
        value = args.value

    if args.key == "port":
        if not isinstance(value, int):
            print(f"port must be a number, not {args.value!r}")
            return 1
        _set_port(cfg, value)
    else:
        _plant(cfg, args.key, value)

    cfgmod.save_config(cfg)
    shown = "•••" if _looks_secret(args.key.split(".")[-1]) else _json.dumps(value)
    print(f"✓ {args.key} = {shown}")
    if args.key == "port":
        _port_change_epilogue(value)
    else:
        print("  restart to pick it up:  bento service restart")
    return 0


def _set_port(cfg: dict, port: int) -> None:
    """Put `port` into cfg (NOT saved here) and say anything true about it.

    One copy, called by both `bento remote --port` and `bento config port`, because
    two commands that set the same key must not disagree about whether it is valid,
    whether it can be bound, or whether the boot service still points at the old one.
    A second copy is how one of them ends up silently skipping the service warning.
    """
    from . import remote as remotemod

    if not 1 <= port <= 65535:
        print(f"port must be 1–65535, not {port}")
        sys.exit(1)
    cfg["port"] = port
    # Saved either way — the setting is the user's to make, and a port that is merely
    # busy right now is a perfectly good port to configure. But a bind the kernel will
    # refuse is a service that never starts, and finding that out here beats finding
    # it out from a unit in a restart loop.
    kind, why = _bind_problem(remotemod.bind_host(cfg), port)
    if kind == "denied":
        print(f"! saved, but this machine will not let AgentOS listen on {port} "
              f"as things stand:")
        print(why)


def _port_change_epilogue(port: int) -> None:
    """Said after the save, because the unit/plist bakes the port into ExecStart.

    A port change that only touched config.json takes effect for `bento serve` and
    silently not for the service, and the two then disagree about which port this
    machine answers on — the hardest kind of "it works for me".
    """
    from . import desktop

    if desktop.autostart_installed():
        print("  the boot service still starts the old port — "
              "update it with:  bento service install && bento service restart")


def _remote_cli(args):
    """`agentos remote` — the headless equivalent of Settings → Remote access,
    for machines you only ever reach over SSH (a Pi, a server)."""
    import getpass

    from . import config as cfgmod
    from . import remote as remotemod
    cfg = remotemod.sanitize_remote(cfgmod.load_config())
    r = cfg.setdefault("remote", {})

    # The port lives at the top of config, not under `remote`, because it is the
    # port on every surface — loopback included. It is settable HERE because this is
    # the command about how the machine is reached, and until now the only way to
    # change it for good was to edit config.json by hand: `serve --port` lasts one
    # run, and the systemd unit bakes in whatever the config said at install time.
    if args.port:
        _set_port(cfg, args.port)

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
    if args.on or args.off or pw or args.bind or args.port:
        remotemod.sanitize_remote(cfg)
        cfgmod.save_config(cfg)
        if args.port:
            _port_change_epilogue(args.port)

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

def _user_cli(args):
    """`bento user` — accounts from a terminal.

    The TUI face of the Users app (CLAUDE.md: every feature in all three). It is
    not a nicety here: a headless machine has no desktop to add the first account
    from, and the alternative would be editing users.json by hand — which is also
    the only way back from a machine with no admin, so it must not be the normal
    way in.
    """
    import getpass

    from . import users as usersmod
    act = args.action

    if act == "list":
        if not usersmod.enabled():
            print("this machine has one user: whoever is at it.\n"
                  "`bento user add NAME` turns on accounts — everything already here "
                  "becomes that account's.")
            return
        for u in usersmod.list_users():
            print(f"  {u['name']:<16} {u['role']:<9} {u.get('display') or ''}")
        return

    if act == "add":
        if not args.name:
            print("usage: bento user add NAME [--role admin|executor]")
            sys.exit(2)
        first = not usersmod.enabled()
        if first:
            print("Adding the first account turns on accounts for this machine.\n"
                  "  · everything already here becomes that account's\n"
                  "  · this machine starts asking who you are, at the keyboard too\n"
                  "  · the first account is an admin, whatever you ask for")
        pw = args.password or getpass.getpass("password: ")
        try:
            u = usersmod.create(args.name, pw, role=args.role, display=args.display)
        except ValueError as e:
            print(e)
            sys.exit(1)
        print(f"✓ {u['name']} ({u['role']}) — home {usersmod.home_for(u['id'])}")
        return

    if act in ("role", "passwd", "remove"):
        u = usersmod.by_name(args.name or "")
        if not u:
            print(f"no user called {args.name!r}")
            sys.exit(1)
        try:
            if act == "role":
                print("✓ " + usersmod.set_role(u["id"], args.role)["role"])
            elif act == "passwd":
                usersmod.set_password(u["id"], args.password or getpass.getpass("new password: "))
                print("✓ password changed")
            else:
                # `--wipe` is separate and explicit: taking somebody's access away
                # and destroying what they made are two decisions.
                r = usersmod.delete(u["id"], wipe=args.wipe)
                print(f"✓ removed — {'home wiped' if r['wiped'] else 'home kept at ' + r['home']}")
        except ValueError as e:
            print(e)
            sys.exit(1)


def _open_store(uid: str = ""):
    """The config and database this command should work with.

    On a single-user machine that is the one pair it has always been. With users
    it has to be somebody's, and guessing is the wrong answer: a `bento job add`
    that silently landed in the wrong person's database would be discovered weeks
    later by whoever did not get their briefing. So: whoever `--user` names; the
    only account if there is exactly one; otherwise say who to choose between.
    """
    from . import config as cfgmod
    from . import users as usersmod
    from .memory import Store
    if usersmod.enabled():
        want = (uid or "").strip().lower()
        people = usersmod.list_users()
        u = usersmod.by_name(want) or usersmod.get(want) if want else (
            people[0] if len(people) == 1 else None)
        if not u:
            if want:
                print(f"no user called {want!r} on this machine")
            else:
                print("this machine has accounts, so a command has to say whose:\n"
                      "  " + "  ".join(x["name"] for x in people) + "\n"
                      "use --user NAME, or set AGENTOS_USER.")
            sys.exit(2)
        usersmod.set_current(u["id"])
        return usersmod.cfg_for(u["id"]), usersmod.store_for(u["id"])
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


def _pid_on_port(port: int) -> str:
    """The pid listening on `port`, or '' — best effort, for a message only.

    Never used to decide anything, only to save somebody a lookup, so every failure
    path returns '' and the caller falls back to a sentence that needs no pid.
    """
    import shutil
    import subprocess
    if not (lsof := shutil.which("lsof")):
        return ""
    try:
        out = subprocess.run([lsof, "-ti", f":{port}", "-sTCP:LISTEN"],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return ""
    return (out.split() or [""])[0]


def _log_cli(args) -> int:
    """`bento log` — everything you need when the desktop will not load.

    There was already `bento service logs`, and it was the wrong shape for the
    question people actually have. That verb tails ONE stream — the journal, or
    server.log — and the failure it is most often reached for does not live in
    either: a browser-side error leaves the server perfectly healthy and answering
    200s, and an exception during a turn is recorded in the OS's own log table,
    not on stderr. So somebody looking at a blank window read a clean journal and
    concluded nothing was wrong.

    This prints the three together, in the order you would want them: where things
    are, then the process output, then what AgentOS itself recorded as an error.
    """
    from . import config as cfgmod
    from . import desktop

    cfg = cfgmod.load_config()
    port = cfg.get("port", 8321)
    mgr = desktop.service_manager() or "none (started by hand)"
    path = desktop.server_log()

    if not args.errors_only:
        print("AgentOS logs")
        print(f"  service:   {mgr}")
        print(f"  file:      {path}{'' if path.exists() else '   (not written yet)'}")
        print(f"  port:      {port}", end="")
        try:
            import urllib.request
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/platform", timeout=2)
            print("   answering")
        except Exception as e:
            print(f"   NOT answering ({type(e).__name__})")
        print()
        print("── process output " + "─" * 44)
        ok, msg = desktop.service_logs(lines=args.lines, follow=args.follow)
        if not ok:
            print(f"  {msg}")
        if args.follow:
            return 0                      # -f never returns until interrupted

    # The half that is not on stderr. A turn that raised, a tool that was denied,
    # a bridge that could not start: all recorded here, by the process that is
    # still running fine as far as the OS is concerned.
    print()
    print("── what AgentOS recorded " + "─" * 37)
    try:
        from .memory import Store
        store = Store(cfgmod.DB_PATH)
    except Exception as e:
        print(f"  could not open the database: {e}")
        return 1
    kinds = ("error",) if args.errors_only else ("error", "system")
    rows = [r for k in kinds for r in store.list_logs(kind=k, limit=args.lines)]
    rows.sort(key=lambda r: r.get("created_at") or 0)
    if not rows:
        print("  nothing recorded"
              + ("" if args.errors_only else " — no errors and no system events"))
        return 0
    for r in rows[-args.lines:]:
        when = time.strftime("%H:%M:%S", time.localtime(r.get("created_at") or 0))
        print(f"  {when}  [{r.get('kind','')}] {(r.get('message') or '')[:150]}")
    return 0


def _confirm(question: str) -> bool:
    """Ask a yes/no question, and take silence for no.

    No terminal means nobody to ask: a systemd timer, a cron line or a CI step
    must never block on a prompt, and answering it for them is worse than refusing
    — so an unattended run gets the same refusal it always got, and only a person
    sitting in front of the command can say yes. `--stash` is how a script says it
    on purpose.
    """
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    try:
        return input(f"\n  {question} [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def _update_cli(args) -> int:
    """`bento update` — is there a newer version, and pull it.

    Every part of this already existed in `agentos/updates.py`: the version check, the
    safety gate, the fast-forward, the dependency sync, the test gate and the rollback.
    What it did not have was a door from a terminal — it was reachable from the Settings
    panel and from a background watcher, and nowhere else. On a headless box, which is
    exactly where a standing install quietly falls behind, "update it" meant reading the
    source to find out what the panel would have called.

    Checking is the default and it changes nothing. Installing is `--apply`, because a
    pull that rewrites the code answering the user's turns is not something to do
    because they typed a bare verb.
    """
    from . import config as cfgmod
    from . import updates as upd

    cfg = cfgmod.load_config()
    root = upd.install_dir()

    state = asyncio.run(upd.check(cfg, force=True))
    cfgmod.save_config(cfg)          # check() stamps last_check on the conf dict

    print(f"AgentOS {upd.current()}")
    print(f"  checkout:  {root or '(not a git checkout — installed some other way)'}")
    print(f"  branch:    {state.get('on_branch') or '(unknown)'}"
          + (f"  → updates track '{state.get('tracks')}'"
             if state.get("mismatch") else "  (the branch updates track)"))
    if state.get("ahead"):
        # Somebody's own commits. Worth naming: it is the other half of "I pushed
        # and nothing happened" — the code is here, it is just not upstream.
        print(f"  ahead:     {state['ahead']} commit(s) of your own, not on "
              f"origin/{state.get('tracks')}")

    # An error is not a reason to stop reporting: the version file may be
    # unreachable while git knows exactly how far behind this copy is, and vice
    # versa. Print what is known, then the failure.
    if state.get("error"):
        print(f"\n! {state['error']}")

    if not state.get("update_available"):
        if state.get("mismatch"):
            print(f"\n✓ up to date with origin/{state.get('tracks')} — but this checkout is "
                  f"on '{state.get('on_branch')}', so commits you pushed to another branch "
                  f"will never show up here")
        else:
            print(f"\n✓ up to date with origin/{state.get('tracks')} "
                  f"(published version {state.get('latest') or 'unknown'})")
        return 0 if not state.get("error") else 1

    # Two different pieces of news. A version bump is a release; commits waiting on
    # the tracked branch are the code, and between releases only the second moves —
    # printing "0.2.0 is available (you have 0.2.0)" is how this said nothing.
    if state.get("latest") and upd.is_newer(state["latest"], upd.current()):
        print(f"\n▲ {state['latest']} is available (you have {upd.current()})")
        for e in upd.entries(state.get("notes") or "", limit=3):
            if e.get("title"):
                print(f"\n  {e['title']}")
            for line in (e.get("body") or "").splitlines()[:6]:
                if line.strip():
                    print(f"    {line.strip()[:100]}")
    else:
        n = state.get("behind") or 0
        print(f"\n▲ {n} change{'s' if n != 1 else ''} waiting on origin/"
              f"{state.get('tracks')} — same version ({upd.current()}), newer code")

    # The changelog nobody maintains by hand: the commits themselves, already
    # fetched by the check rather than fetched a second time here.
    waiting = state.get("commits") or []
    if waiting:
        print(f"\n  {len(waiting)} change{'s' if len(waiting) != 1 else ''} waiting:")
        for c in waiting:
            print(f"    {c['hash']}  {c['title'][:88]}")

    # Whether it COULD be installed is worth saying even on a bare check: a machine
    # with local edits or on the wrong branch will refuse at `--apply`, and finding
    # that out now beats finding it out halfway through an upgrade you scheduled.
    ok, why = upd.can_apply(cfg)
    stashed = ""
    if not ok:
        # "1 uncommitted change(s)" and a full stop is a dead end: the one thing
        # the user needs — WHICH file, and what to do about it — is the thing the
        # refusal did not say, so every hit meant leaving the command and running
        # git by hand. Name them, then offer the one answer that loses nothing.
        dirty = upd.local_changes()
        if not dirty:
            print(f"\n✗ cannot install it here: {why}")     # wrong branch, no git, …
            return 1
        print(f"\n! this checkout has {len(dirty)} uncommitted change"
              f"{'s' if len(dirty) != 1 else ''} of your own:")
        for c in dirty:
            print(f"    {c['code']:<2}  {c['path']}")
        print(f"\n  Updating would pull on top of them. Stashing parks them in the "
              f"repository first —\n  nothing is discarded, and `git stash pop` brings "
              f"them straight back afterwards.")
        if not (getattr(args, "stash", False) or _confirm("stash them and install the update?")):
            # A no is a full answer: say what was NOT done, and leave the two ways
            # out that do not involve this command.
            print("\n  stopped — nothing was stashed, pulled or restarted.")
            print("  commit or stash them yourself, then:  bento update --apply")
            return 1
        okz, msg = upd.stash_local()
        print(f"\n  {msg}")
        if not okz:
            return 1
        stashed = msg
        ok, why = upd.can_apply(cfg)
        if not ok:
            print(f"\n✗ still cannot install it here: {why}")
            return 1
        # Answering that prompt IS the instruction to install — asking again for
        # `--apply` after somebody typed 'y' to "install the update?" would be the
        # same dead end with an extra step.
        args.apply = True

    if not getattr(args, "apply", False):
        print(f"\n  install it:  bento update --apply")
        return 0

    # Work parked at the start of this command is the easiest thing in the world to
    # forget, and whoever forgets it concludes the update ate their edits. So it is
    # said again on the way out — on EVERY way out, including the two that fail:
    # a rolled-back update with a silent stash behind it is the worst version of this.
    def parked() -> None:
        if stashed:
            print(f"\n  your parked changes: {stashed.split('with: ')[-1]}")

    print()
    result = asyncio.run(upd.apply(cfg, run_tests=not args.no_tests,
                                   log=lambda m: print(f"  {m}")))
    if not result.get("ok"):
        print(f"✗ {result.get('error')}")
        parked()
        return 1
    if result.get("unchanged"):
        print("✓ already at the newest commit — nothing changed")
        parked()
        return 0
    print(f"✓ updated {result['from']} → {result['to']} "
          f"({result['files']} files, now {result.get('version') or '?'})")
    # What actually landed. Printed after the fact as well as before it, because
    # an unattended update (a watcher, a cron line) is one nobody read the preview
    # of — this is the only place that machine's operator ever sees what changed.
    for c in (result.get("changes") or []):
        print(f"    {c['hash']}  {c['title'][:88]}")
    parked()

    # An update that has not been loaded is a half-state: the files on disk and the
    # process answering turns disagree, and nothing on screen says which one you are
    # talking to. `apply()` deliberately leaves this to its caller — in the HTTP path
    # the response has to reach the browser first. Here there is no such constraint.
    if args.no_restart:
        print("  load it:  bento service restart")
        return 0
    from . import desktop
    started, msg = desktop.service_restart()
    print(("✓ " if started else "✗ ") + msg)
    return 0 if started else 1


def _service_cli(args) -> int:
    """`bento service …` — the background server, on whatever supervisor this
    machine has.

    Everything here goes through `desktop.service_*`, which is where the systemd /
    launchd / no-supervisor difference lives. This function only prints, and the
    thing it works hardest to print is WHICH of the three just happened: "stopped"
    means something different on a machine that will bring it back at boot than on
    one that will not, and a user cannot see which they have from the outside.
    """
    from . import desktop

    action = getattr(args, "action", "status")

    if action == "status":
        st = desktop.service_status()
        mark = "✓" if st["answering"] else ("!" if st["running"] else "·")
        where = {
            "systemd": "systemd user service",
            "launchagent": "launchd LaunchAgent",
            "startup": "Windows Startup entry",
            "none": "not installed as a service",
        }[st["manager"]]
        print(f"AgentOS background server")
        print(f"  {mark} {st['detail']}")
        print(f"  supervisor:  {where}"
              + (f"  (pid {st['pid']})" if st["pid"] else ""))
        if st["enabled"] is not None:
            print(f"  at boot:     {'yes' if st['enabled'] else 'no'}")
        if st["answering"]:
            where = desktop.where_it_answers(st["port"])
            print(f"  port {st['port']}:   answering — {where[0]}")
            for extra in where[1:]:
                print(f"               {extra}")
        else:
            print(f"  port {st['port']}:   nothing listening")
        # The disagreement is the interesting case, so name it rather than leaving
        # two lines that quietly contradict each other.
        if st["running"] and not st["answering"]:
            print("\n  ! the supervisor thinks it is up but the port is silent —"
                  "\n    that is a crash loop or a wedged startup:  bento service logs")
        if not st["installed"] and st["answering"]:
            print("\n  · started by hand, so a reboot loses it:  bento service install")
        return 0 if st["answering"] else 1

    if action == "install":
        desktop.install(autostart=True, open_at_login=not args.no_login)
        return 0

    fn = {"start": desktop.service_start,
          "stop": desktop.service_stop,
          "restart": desktop.service_restart,
          "uninstall": desktop.service_uninstall}.get(action)
    if fn:
        ok, msg = fn()
        print(("✓ " if ok else "✗ ") + msg)
        return 0 if ok else 1

    if action == "logs":
        ok, msg = desktop.service_logs(lines=args.lines, follow=args.follow)
        if msg:
            print(msg)
        return 0 if ok else 1
    return 2


def _restart_cli(args) -> int:
    """`bento restart` — ask the running server to restart itself.

    Deliberately NOT `desktop.restart_service()` called here. That function's last
    resort is re-exec'ing the current process, which is right inside the server and
    wrong in a CLI: it would leave the stale server holding the port and start a
    second one beside it, sharing the database. The server is the only process that
    can correctly replace the server, so this asks it to.

    A server that is not running is not an error worth a traceback — it is somebody
    who wanted AgentOS running, so say the command that starts it.
    """
    import json as _json
    import urllib.error
    import urllib.request

    from . import config as cfgmod

    cfg = cfgmod.load_config()
    port = args.port or cfg.get("port", 8321)
    base = f"http://127.0.0.1:{port}"
    try:
        req = urllib.request.Request(base + "/api/restart", method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            res = _json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # The one case this command cannot fix by itself, and the case it was
            # written for: a server running code older than the route it is being
            # asked for. Nothing on the wire can restart it, so print the two things
            # needed to do it by hand rather than a bare 404 — which reads as "the
            # restart failed" when the truth is "this server has never heard of it".
            print(f"This server predates `bento restart` (no /api/restart on {base}),\n"
                  "  which is itself a sign it is running old code. Stop it by hand:")
            pid = _pid_on_port(port)
            print(f"    kill {pid} && bento serve" if pid
                  else "    stop the terminal running it, then:  bento serve")
            return 1
        print(f"✗ the server refused the restart: {e.code} {e.reason}")
        return 1
    except Exception:
        # No server on the port. `_port_free` tells the two cases apart: something
        # else holding it is a different problem from nothing holding it, and
        # "start it with X" would be wrong advice for the first.
        if _port_free("127.0.0.1", port):
            print(f"AgentOS is not running on {base}.\n  start it:  bento serve")
        else:
            print(f"Something holds {base} but it is not answering as AgentOS.\n"
                  f"  check it:  bento doctor")
        return 1

    how = (res or {}).get("how", "process")
    print({
        "launchagent": "✓ restarting — launchd owns the server, so it comes back by itself",
        "systemd": "✓ restarting — systemd owns the server, so it comes back by itself",
    }.get(how, "✓ restarting the server process (started by hand, so it is not "
                "supervised — if it does not come back, run `bento serve`)"))
    print(f"  {base}  — give it a few seconds")
    return 0


def _space_cli(args):
    from . import config as cfgmod
    from . import spaces as spacemod
    cfg, store = _open_store(getattr(args, "user", ""))

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
    cfg, store = _open_store(getattr(args, "user", ""))
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
    cfg, store = _open_store(getattr(args, "user", ""))
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
    _, store = _open_store(getattr(args, "user", ""))
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


def _help_cli(parser, sub, verbs: dict, everyday, args) -> int:
    """`bento help` — the catalogue, in the two sizes it is actually wanted in.

    `--help` shows the verbs a new machine needs; this is where the rest of them
    are, so that shortening the front page never becomes hiding anything. A command
    that is real but undiscoverable is worse than a long list.
    """
    topic = (args.topic or "").strip()
    if topic:
        p = sub.choices.get(topic)
        if not p:
            print(f"no such command: {topic}")
            print(f"  `{parser.prog} help --all` lists every one")
            return 2
        p.print_help()
        return 0
    if not args.all:
        parser.print_help()
        return 0

    width = max(len(v) for v in verbs) + 2
    print(f"\n{parser.prog} — every command on this machine.\n")
    print("  every day")
    for v in verbs:
        if v in everyday:
            print(f"    {v:<{width}}{verbs[v]}")
    print("\n  the rest")
    for v in verbs:
        if v not in everyday:
            print(f"    {v:<{width}}{verbs[v]}")
    print(f"\n  `{parser.prog} help <command>` for one of them in full.\n")
    return 0


def main():
    _use_system_certs()
    # Name it after however it was invoked. `bento` and `agentos` are the same
    # program, and help text that answers with a different name than the one you
    # typed is the kind of small lie that makes people doubt the rest.
    parser = argparse.ArgumentParser(
        prog=os.path.basename(sys.argv[0]) or "bento",
        description="Bento Box AI — your machine, with a brain.")
    # Whose machine. Ignored entirely until somebody adds a user; after that every
    # verb that reads data needs to know, because there is no longer one answer.
    # An environment variable too, so a cron line or a systemd unit can say it once.
    parser.add_argument("--user", default=os.environ.get("AGENTOS_USER", ""),
                        help="act as this user (multi-user machines only)")
    # `metavar`, or the usage line is a 39-word comma-separated wall that scrolls
    # the actual help off an 80-column SSH window — which is exactly the terminal a
    # fresh Pi is read from.
    sub = parser.add_subparsers(dest="cmd", title="commands", metavar="<command>")

    # The verbs a machine that was installed ten minutes ago needs. Everything else
    # still exists, still works, and is still documented — it is just not the first
    # thing somebody is shown, because a list of 39 things reads as "you have to
    # understand all of this" rather than "start here".
    EVERYDAY = ("setup", "serve", "tui", "ask", "remote", "service",
                "doctor", "update", "job", "config")
    VERBS: dict[str, str] = {}          # every verb -> its one-liner, in order

    def verb(name, help="", **kw):
        """Register a subcommand.

        argparse has no notion of a hidden subcommand: a parser registered WITHOUT
        `help=` is absent from the listing while remaining a perfectly valid choice.
        That is the whole mechanism here — nothing is removed, and `bento help --all`
        prints the full catalogue from `VERBS`, which is why the text is recorded
        here rather than only handed to argparse.
        """
        VERBS[name] = help
        for a in kw.get("aliases", ()):
            VERBS[a] = f"same as `{name}`"
        if name in EVERYDAY:
            kw["help"] = help
        return sub.add_parser(name, **kw)

    p_help = verb("help", help="the full list of commands, or help for one of them")
    p_help.add_argument("topic", nargs="?", default="",
                        help="a command name — `bento help remote`")
    p_help.add_argument("--all", action="store_true",
                        help="every command, including the ones --help does not list")

    verb("setup", help="set this machine up — the same arc as the desktop wizard, in the terminal")

    p_serve = verb("serve", help="start the AgentOS server + UI (default)")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=0)
    p_serve.add_argument("--no-browser", action="store_true")
    # What to do when one is already running. `ask` needs a terminal and falls back
    # to `fail` without one — the unattended callers (the systemd unit, the
    # LaunchAgent, CI) are exactly the ones for whom guessing would be worst.
    p_serve.add_argument("--if-running", default="ask",
                         choices=["ask", "open", "port", "restart", "fail"],
                         help="one is already running: ask (default), open it, use "
                              "another port, restart it, or fail")

    verb("tui", help="terminal UI — the AgentOS agent in your terminal (great over SSH)")

    p_ask = verb("ask", help="one-shot agent run in the terminal")
    p_ask.add_argument("prompt", nargs="+")
    p_ask.add_argument("--model", default=None, help="e.g. ollama/qwen3.5:9b")
    p_ask.add_argument("--full", action="store_true", help="full autonomy (no approval prompts)")

    p_usage = verb("usage", help="what the agent has spent — tokens, and money where the model is priced")
    p_usage.add_argument("--days", type=float, default=1.0, help="how far back (default: 1)")
    p_usage.add_argument("--by", default="model",
                         choices=["model", "day", "surface", "kind", "conversation", "space"])

    p_eval = verb("eval", help="run the behavioural evals against a model (does the agent still behave?)")
    p_eval.add_argument("--model", action="append", default=None,
                        help="model to test; repeat to compare several (default: the configured one)")
    p_eval.add_argument("--case", action="append", default=None, help="run only this case id (repeatable)")
    p_eval.add_argument("--tag", action="append", default=None, help="run only cases with this tag")
    p_eval.add_argument("--network", action="store_true", help="include cases that need the internet")
    p_eval.add_argument("--list", action="store_true", help="list the cases and exit")
    p_eval.add_argument("--verbose", "-v", action="store_true", help="show every assertion, not just failures")
    p_eval.add_argument("--json", action="store_true", help="print the raw report")

    p_fwd = verb("forward", help="make this machine answer with another agent (or show what it does now)")
    p_fwd.add_argument("engine", nargs="?", choices=["aria", "claude-code", "off"],
                       help="omit to show the current setting; 'off' is the same as 'aria'")

    p_prof = verb("profile", help="footprint profile — lite keeps nothing "
                                            "it is not using (for a Pi)")
    p_prof.add_argument("profile", nargs="?", choices=["auto", "full", "lite"],
                        help="omit to show what this machine is doing now")

    p_brain = verb("brain", help="which executor answers and which of its models "
                                          "(omit everything to list what could)")
    # No `choices=`: the executors are a probe of this machine, and a hardcoded
    # list here is how `bento forward` ended up unable to name Hermes or OpenClaw.
    p_brain.add_argument("executor", nargs="?", help="ollama | openai | anthropic | google | "
                                                    "openrouter | custom | claude-code | hermes | "
                                                    "openclaw | aria")
    p_brain.add_argument("model", nargs="?", help="one of THAT executor's models; omit for its default")

    p_del = verb("delegate", help="hand a task to an executor (Claude Code) and stream it here")
    p_del.add_argument("prompt", nargs="+")
    p_del.add_argument("--dir", default=None, help="the only folder it may touch (default: the configured workspace)")
    p_del.add_argument("--tools", default=None, help="comma-separated, e.g. Read,Grep,Edit (default: the configured envelope)")
    p_del.add_argument("--model", default=None, help="model for the executor; omit to use its own default")
    p_del.add_argument("--budget", type=float, default=None, help="hard spend ceiling in USD")

    verb("app", help="open AgentOS as a desktop app window")
    p_doctor = verb("doctor", help="check the environment: port conflicts, duplicate instances, Ollama/VRAM, DB health")
    p_doctor.add_argument("--fix", action="store_true", help="auto-repair what's safe; print sudo steps for the rest")
    p_doctor.add_argument("--session", action="store_true",
                          help="probe what can actually draw the desktop on this machine "
                               "(why the session came up, or did not)")
    p_install = verb("install", help="install app launcher + boot service + login autostart")
    p_install.add_argument("--no-service", action="store_true",
                           help="launcher only; skip the background boot service")
    p_install.add_argument("--no-login", action="store_true",
                           help="don't open AgentOS automatically at login")
    verb("uninstall", help="remove launcher + boot service")
    # The background server, from the terminal. This is the half of `install` that
    # was missing: `bento install` put a systemd unit / LaunchAgent on the machine
    # and then every later question about it — is it up, stop it, why did it die,
    # take it off this box — had to be answered in systemctl and launchctl, which
    # is asking the user to know which OS they are on to control their own agent.
    # Checking is the default and changes nothing; installing is an explicit flag.
    # A bare verb must not rewrite the code that is answering the user's turns.
    p_upd = verb("update",
                           help="check for a newer AgentOS, and pull it with --apply")
    p_upd.add_argument("--apply", action="store_true",
                       help="actually install it: fast-forward, sync deps, run the "
                            "tests, restart")
    p_upd.add_argument("--stash", action="store_true",
                       help="if the checkout has your own uncommitted edits, park them "
                            "with `git stash` and update anyway (answers the prompt "
                            "for an unattended run)")
    p_upd.add_argument("--no-tests", action="store_true",
                       help="skip the test gate (it is what rolls a bad update back)")
    p_upd.add_argument("--no-restart", action="store_true",
                       help="leave the restart to you")

    p_svc = verb("service",
                           help="the background server: status, start, stop, restart, logs, uninstall")
    p_svc.add_argument("action", nargs="?", default="status",
                       choices=["status", "start", "stop", "restart",
                                "install", "uninstall", "logs"])
    p_svc.add_argument("--lines", "-n", type=int, default=60,
                       help="logs: how many lines (default 60)")
    p_svc.add_argument("--follow", "-f", action="store_true",
                       help="logs: keep streaming")
    p_svc.add_argument("--no-login", action="store_true",
                       help="install: don't also open the AgentOS window at login")
    p_restart = verb("restart",
                               help="restart the running AgentOS server (to load code changes)")
    p_restart.add_argument("--port", type=int, default=0,
                           help="port the server is on (default: the configured one)")
    p_auto = verb("autostart", help="open AgentOS at login (on) or stop (--off)")
    p_auto.add_argument("--off", action="store_true", help="disable login autostart")
    # The installer is the one entry point that has to work BEFORE anything is
    # set up — on a machine where the session packages are missing and the
    # server has never run. That is why it is a plain terminal UI rather than a
    # screen in `agentos tui`, which needs Textual and a live server.
    p_inst = verb("installer",
                            help="terminal installer — detect this OS and install what "
                                 "AgentOS needs (re-runnable; shows what is missing)")
    p_inst.add_argument("--session", action="store_true",
                        help="only what the login session needs")
    p_inst.add_argument("--yes", action="store_true",
                        help="install everything offered without asking (still prints "
                             "every package and licence first)")
    p_sess = verb("install-session",
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
    p_log = verb("log", aliases=["logs"],
                           help="the process log and everything AgentOS recorded as an error")
    p_log.add_argument("-n", "--lines", type=int, default=60, help="how many lines (default 60)")
    p_log.add_argument("-f", "--follow", action="store_true", help="keep streaming")
    p_log.add_argument("--errors", dest="errors_only", action="store_true",
                       help="only what AgentOS recorded as an error")
    p_fold = verb("folders",
                            help="show or change the folders the agent may work in, and who may work there")
    p_fold.add_argument("action", nargs="?", default="", choices=["", "list", "add", "remove"],
                        help="omit to list")
    p_fold.add_argument("path", nargs="?", default="", help="the folder")
    p_fold.add_argument("--mode", default="rw", help="ro (read-only) or rw (read-write)")
    p_fold.add_argument("--users", default="",
                        help="accounts to share with, comma separated (omit for everyone)")
    p_chan = verb("channels", help="show or change the ways in (this window, terminal, remote, API, Telegram…) and how far each is trusted")
    p_chan.add_argument("channel", nargs="?", default="", help="channel id (omit to list them all)")
    p_chan.add_argument("--on", action="store_true", help="switch this channel on")
    p_chan.add_argument("--off", action="store_true", help="switch this channel off")
    p_chan.add_argument("--posture", default="",
                        help="how far to trust it: inherit | read_only | ask | full")
    # Telegram needs one value, WhatsApp needs four. Without this, configuring a
    # channel is a GUI-only act — which is exactly backwards for a headless machine.
    p_chan.add_argument("--pair", action="store_true",
                        help="whatsapp: link this machine by scanning a QR code "
                             "(the Baileys bridge — no Meta account needed)")
    p_chan.add_argument("--unpair", action="store_true",
                        help="whatsapp: unlink the device and forget the paired chat")
    p_chan.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="set one of this channel's fields, e.g. --set verify_token=hunter2 "
                             "(repeatable; `agentos channels <id>` lists the fields it needs)")

    p_tun = verb("tunnel", help="show how to reach this machine from elsewhere (Tailscale / tunnel), or publish it")
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
    p_space = verb("space", help="show or switch the space this terminal works in")
    p_space.add_argument("name", nargs="?", default="", help="space to work in (omit to list)")
    p_space.add_argument("--none", action="store_true", help="work everywhere (the shared scope)")
    p_space.add_argument("--new", default="", help="create a space with this name")
    p_space.add_argument("--about", default="", help="one line describing a new space")

    p_tl = verb("timeline", help="what happened — runs, assets, memory, apps")
    p_tl.add_argument("--since", default="7d", help="e.g. 24h, 7d, 30d (default 7d)")
    p_tl.add_argument("--kind", default="", help="run | asset | memory | app_version | conversation | task")
    p_tl.add_argument("--limit", type=int, default=40)

    p_assets = verb("assets", help="list, open or remove things the agent made")
    p_assets.add_argument("action", nargs="?", default="list",
                          choices=["list", "path", "open", "rm"])
    p_assets.add_argument("id", nargs="?", default="", help="asset id, for path/open/rm")
    p_assets.add_argument("--kind", default="", help="image | video | audio | doc")

    p_audit = verb("audit", help="the access ledger — who was allowed to do what")
    p_audit.add_argument("--since", default="24h", help="e.g. 1h, 24h, 7d (default 24h)")
    p_audit.add_argument("--effect", default="", choices=["", "allow", "deny", "ask"])
    p_audit.add_argument("--who", default="", help="user | app | subagent | workflow | system")
    p_audit.add_argument("--surface", default="", help="gui | tui | telegram | api | task")
    p_audit.add_argument("--limit", type=int, default=50)

    p_flow = verb("flow", help="flows — standing missions run by a master orchestrator")
    p_flow.add_argument("action", nargs="?", default="list",
                        choices=["list", "run", "show", "approvals", "allow", "deny", "hooks"])
    p_flow.add_argument("name", nargs="?", default="",
                        help="flow name, or a run id for `show`, or an approval id")
    p_flow.add_argument("--input", default="", help="what to hand the flow")
    p_flow.add_argument("--wait", action="store_true", help="stay attached until it finishes")
    p_flow.add_argument("--always", action="store_true",
                        help="with `allow`: remember it as a grant, not just this once")

    p_job = verb("job", help="give this machine a standing job — the terminal "
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

    p_user = verb("user", help="accounts — several people on one machine, "
                                         "each with their own home")
    p_user.add_argument("action", nargs="?", default="list",
                        choices=["list", "add", "role", "passwd", "remove"])
    p_user.add_argument("name", nargs="?", default="")
    p_user.add_argument("--role", default="executor", choices=["admin", "executor"])
    p_user.add_argument("--display", default="", help="the name shown on screen")
    p_user.add_argument("--password", default="", help="prompted for if omitted")
    p_user.add_argument("--wipe", action="store_true",
                        help="remove: also delete their home directory and everything in it")

    # The settings file, from a terminal. It has always existed and every documented
    # way to change it was a GUI panel or a command that happened to own one key —
    # so "change the port" lived under `bento remote`, which is filed under remote
    # access and is not where anybody looks for it.
    p_cfg = verb("config",
                           help="show or change settings (~/.agentos/config.json)")
    p_cfg.add_argument("key", nargs="?", default="",
                       help="dotted, e.g. port, remote.bind, telegram.enabled "
                            "(omit to show everything)")
    p_cfg.add_argument("value", nargs="?", default=None,
                       help="the new value (omit to just show it)")
    p_cfg.add_argument("--raw", action="store_true",
                       help="do not mask API keys, tokens and passphrase hashes")
    p_cfg.add_argument("--path", action="store_true", help="print the file's location")
    p_cfg.add_argument("--edit", action="store_true",
                       help="open it in $EDITOR; refuses to save invalid JSON")

    p_remote = verb("remote", help="show or change remote access (reach this desktop from your phone)")
    p_remote.add_argument("--on", action="store_true", help="enable remote access (needs a passphrase)")
    p_remote.add_argument("--off", action="store_true", help="disable it and go back to loopback only")
    p_remote.add_argument("--passphrase", default="", help="set the sign-in passphrase (prompted if omitted)")
    p_remote.add_argument("--bind", default="", help="interface to listen on once enabled (default 0.0.0.0)")
    p_remote.add_argument("--port", type=int, default=0,
                          help="the port this machine answers on, saved to config "
                               "(the service picks it up on `bento service install`)")

    # Every graphical capability needs a way in from a terminal too — a headless
    # Pi reached over SSH is a first-class way to run AgentOS, not an edge case.
    p_apps = verb("apps", help="find, install and remove native applications")
    p_apps.add_argument("action", nargs="?", default="list",
                        choices=["list", "search", "install", "remove"])
    p_apps.add_argument("name", nargs="?", default="", help="query, or the package to act on")
    p_apps.add_argument("--backend", default="", help="flatpak, apt, dnf or pacman")

    p_mcp = verb("mcp", help="MCP servers — what is connected, and add the "
                                       "first-party ones (Canva, Higgsfield, Notion…)")
    p_mcp.add_argument("action", nargs="?", default="list",
                       choices=["list", "catalog", "add", "connect", "disconnect"])
    p_mcp.add_argument("name", nargs="?", default="",
                       help="with add: a catalogue key (canva, higgsfield…); "
                            "otherwise a configured server name")

    p_quar = verb("quarantine",
                            help="what the OS stopped for running away, and let it go again")
    p_quar.add_argument("action", nargs="?", default="list",
                        choices=["list", "history", "release"])
    p_quar.add_argument("id", nargs="?", default="", help="with release: the hold id")
    p_quar.add_argument("--mode", default="once", choices=["once", "forever", "deleted"],
                        help="once (still watched), forever (an exemption), deleted")

    p_rd = verb("remote-desktop",
                          help="the browser remote desktop — use the real screen from a phone")
    p_rd.add_argument("--on", action="store_true", help="start it")
    p_rd.add_argument("--off", action="store_true", help="stop it")

    p_mode = verb("session", help="show or pin the desktop run mode (auto | de | hosted | kiosk)")
    p_mode.add_argument("action", nargs="?", default="show", choices=["show", "mode", "run"])
    p_mode.add_argument("value", nargs="?", default="",
                        help="with `mode`: auto, de, hosted or kiosk")

    # Set here rather than at construction: it counts the catalogue, and the
    # catalogue is not complete until the last verb above has registered.
    hidden = len(VERBS) - len([v for v in VERBS if v in EVERYDAY])
    parser.epilog = (f"{len(VERBS)} commands in all — `{parser.prog} help --all` lists "
                     f"the other {hidden}.\n"
                     f"New machine? `{parser.prog} setup` walks the whole thing.")
    parser.formatter_class = argparse.RawDescriptionHelpFormatter

    args = parser.parse_args()
    if args.cmd == "help":
        raise SystemExit(_help_cli(parser, sub, VERBS, EVERYDAY, args))
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
    elif args.cmd == "brain":
        brain_cmd(args.executor, args.model)
    elif args.cmd == "profile":
        profile_cmd(args.profile)
    elif args.cmd == "tunnel":
        tunnel_cmd(args.on, args.off, args.public, args.provider, args.install)
    elif args.cmd in ("log", "logs"):
        raise SystemExit(_log_cli(args))
    elif args.cmd == "folders":
        folders_cmd(args.action, args.path, args.mode, args.users)
    elif args.cmd == "channels":
        channels_cmd(args.channel, args.on, args.off, args.posture, args.set)
    elif args.cmd == "delegate":
        delegate(" ".join(args.prompt), args.dir, args.tools, args.model, args.budget)
    elif args.cmd == "app":
        from . import desktop
        desktop.app_mode()
    elif args.cmd == "setup":
        # The arc, not the old five-question form: the same catalogue and the same
        # probe the browser wizard uses, so a machine set up half way in one and
        # finished in the other picks up exactly where it was left.
        from . import setup_tui
        cfg, store = _open_store(getattr(args, "user", ""))
        setup_tui.run(cfg, store)
    elif args.cmd == "tui":
        from . import config as cfgmod
        if cfgmod.is_first_run():
            from . import setup_tui
            setup_tui.run()
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
    elif args.cmd == "update":
        raise SystemExit(_update_cli(args))
    elif args.cmd == "service":
        raise SystemExit(_service_cli(args))
    elif args.cmd == "restart":
        raise SystemExit(_restart_cli(args))
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
    elif args.cmd == "user":
        _user_cli(args)
    elif args.cmd == "config":
        raise SystemExit(_config_cli(args))
    elif args.cmd == "remote":
        _remote_cli(args)
    elif args.cmd == "apps":
        _apps_cli(args)
    elif args.cmd == "mcp":
        _mcp_cli(args)
    elif args.cmd == "quarantine":
        _quarantine_cli(args)
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
        serve(host, port, not no_browser, getattr(args, "if_running", "ask"))


if __name__ == "__main__":
    main()
