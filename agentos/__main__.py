"""Entry point: `agentos` serves the UI; `agentos ask "..."` runs a one-shot agent in the terminal."""

import argparse
import asyncio
import json
import sys
import threading
import time
import webbrowser


def serve(host: str, port: int, open_browser: bool):
    import uvicorn
    from . import config as cfgmod
    cfg = cfgmod.load_config()
    port = port or cfg.get("port", 8321)
    url = f"http://{host}:{port}"
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


def main():
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
    sub.add_parser("tui", help="terminal UI — the AgentOS agent in your terminal (great over SSH)")
    sub.add_parser("setup", help="first-time setup wizard (name, model, autonomy, autostart)")
    p_install = sub.add_parser("install", help="install app launcher + boot service + login autostart")
    p_install.add_argument("--no-service", action="store_true",
                           help="launcher only; skip the systemd boot service")
    p_install.add_argument("--no-login", action="store_true",
                           help="don't open AgentOS automatically at login")
    sub.add_parser("uninstall", help="remove launcher + boot service")
    p_auto = sub.add_parser("autostart", help="open AgentOS at login (on) or stop (--off)")
    p_auto.add_argument("--off", action="store_true", help="disable login autostart")
    p_sess = sub.add_parser("install-session",
                            help="add AgentOS as a login session (boots into kiosk as the desktop shell)")
    p_sess.add_argument("--remove", action="store_true", help="remove the AgentOS session")

    args = parser.parse_args()
    if args.cmd == "ask":
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
