"""Entry point: `agentos` serves the UI; `agentos ask "..."` runs a one-shot agent in the terminal."""

import argparse
import asyncio
import json
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
    cfg = cfgmod.load_config()
    port = port or cfg.get("port", 8321)
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
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
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


def doctor(fix: bool = False):
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

    from . import hermes as hermesmod
    hcli = hermesmod.cli_path()
    if hcli:
        ok(f"Hermes companion agent available ({'gateway running' if hermesmod.gateway_running() else 'installed'})")
    print()
    if not fix:
        print("  \033[90mrun `agentos doctor --fix` to auto-repair the fixable items above\033[0m\n")


def main():
    _use_system_certs()
    parser = argparse.ArgumentParser(prog="agentos", description="AgentOS — your machine, with a brain.")
    sub = parser.add_subparsers(dest="cmd")

    p_serve = sub.add_parser("serve", help="start the AgentOS server + UI (default)")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=0)
    p_serve.add_argument("--no-browser", action="store_true")

    p_ask = sub.add_parser("ask", help="one-shot agent run in the terminal")
    p_ask.add_argument("prompt", nargs="+")
    p_ask.add_argument("--model", default=None, help="e.g. ollama/qwen3.5:9b")
    p_ask.add_argument("--full", action="store_true", help="full autonomy (no approval prompts)")

    sub.add_parser("app", help="open AgentOS as a desktop app window")
    p_doctor = sub.add_parser("doctor", help="check the environment: port conflicts, duplicate instances, Ollama/VRAM, DB health")
    p_doctor.add_argument("--fix", action="store_true", help="auto-repair what's safe; print sudo steps for the rest")
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
    p_sess = sub.add_parser("install-session",
                            help="add AgentOS as a login session (Linux only; boots into kiosk as the desktop shell)")
    p_sess.add_argument("--remove", action="store_true", help="remove the AgentOS session")

    args = parser.parse_args()
    if args.cmd == "doctor":
        doctor(fix=getattr(args, "fix", False))
    elif args.cmd == "ask":
        ask(" ".join(args.prompt), args.model, args.full)
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
        from . import desktop
        desktop.uninstall_session() if args.remove else desktop.install_session()
    else:
        host = getattr(args, "host", "127.0.0.1")
        port = getattr(args, "port", 0)
        no_browser = getattr(args, "no_browser", False)
        serve(host, port, not no_browser)


if __name__ == "__main__":
    main()
