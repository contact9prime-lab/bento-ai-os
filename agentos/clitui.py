"""AgentOS CLI UI — a terminal client for the AgentOS agent, for use over SSH.

It connects to the running AgentOS server (starting one if needed) and gives you the same
agent — streaming replies, tool activity, approvals — plus quick views of the system, apps,
and models, all in a styled text interface.

    agentos tui
"""

import asyncio
import json
import os
import sys

from . import config as cfgmod

C = {
    "acc": "\033[38;5;80m", "acc2": "\033[38;5;44m", "dim": "\033[90m", "teal": "\033[36m",
    "b": "\033[1m", "r": "\033[0m", "warn": "\033[33m", "err": "\033[31m", "ok": "\033[32m",
    "inv": "\033[7m",
}


def _w() -> int:
    try:
        return min(os.get_terminal_size().columns, 96)
    except OSError:
        return 80


def _rule(ch="─"):
    print(C["dim"] + ch * _w() + C["r"])


def _banner(sysinfo: dict, model: str, name: str):
    if sys.stdout.isatty():
        sys.stdout.write("\033[H\033[2J")   # clear only on a real terminal
    line = f"{C['acc']}{C['b']}▲ AgentOS{C['r']}  {C['dim']}· {name} · {model or 'no model'}{C['r']}"
    print(line)
    if sysinfo:
        mem = sysinfo.get("mem", {})
        used = mem.get("used_kb", 0) / 1e6
        tot = mem.get("total_kb", 1) / 1e6
        du = sysinfo.get("disk", {})
        print(f"{C['dim']}{sysinfo.get('cores','?')} cores · "
              f"cpu {sysinfo.get('cpu',0):.0f}% · mem {used:.1f}/{tot:.0f}GB · "
              f"disk {du.get('used',0)/1e9:.0f}/{du.get('total',0)/1e9:.0f}GB{C['r']}")
    _rule()
    print(f"{C['dim']}Type a message, or /help for commands. Ctrl-D to quit.{C['r']}\n")


async def _ainput(prompt: str) -> str:
    return await asyncio.to_thread(input, prompt)


HELP = f"""{C['b']}Commands{C['r']}
  {C['acc']}/sys{C['r']}          system snapshot (CPU, memory, disk, top processes)
  {C['acc']}/apps{C['r']}         list installed apps
  {C['acc']}/models{C['r']}       list models · {C['acc']}/model <id>{C['r']} to switch
  {C['acc']}/tasks{C['r']}        scheduled jobs
  {C['acc']}/clear{C['r']}        start a fresh conversation
  {C['acc']}/help{C['r']}         this help
  {C['acc']}/quit{C['r']}         exit
Anything else is sent to the agent, which can act on this machine (with your approval).
"""


async def run_tui():
    try:
        import httpx
        import websockets
    except ImportError:
        print("The TUI needs httpx and websockets (already AgentOS deps).", file=sys.stderr)
        return

    if not sys.stdin.isatty():
        print("The AgentOS TUI needs an interactive terminal (a real shell or an SSH session).\n"
              "It looks like input isn't a TTY here. Try running it directly in your terminal:\n"
              "  agentos tui", file=sys.stderr)
        return

    cfg = cfgmod.load_config()
    port = cfg.get("port", 8321)
    base = f"http://127.0.0.1:{port}"
    ws_url = f"ws://127.0.0.1:{port}/ws"

    # start the server in-process if it isn't already up
    import socket
    def up():
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            return False
    if not up():
        print(f"{C['dim']}starting AgentOS server…{C['r']}")
        from . import desktop
        desktop._start_server_thread(port)

    async with httpx.AsyncClient(timeout=8) as http:
        async def get(path):
            try:
                return (await http.get(base + path)).json()
            except Exception:
                return {}
        sysinfo = await get("/api/system")
        models = (await get("/api/models"))
        model = cfg.get("default_model", "") or (models.get("models", [{}])[0] or {}).get("id", "")
        name = cfg.get("agent_name", "Aria")
        _banner(sysinfo, model, name)

        cid = None
        try:
            async with websockets.connect(ws_url, max_size=None) as ws:
                pending = {}

                async def drain_turn():
                    nonlocal cid
                    while True:
                        ev = json.loads(await ws.recv())
                        t = ev.get("type")
                        if t == "conversation":
                            cid = ev["id"]
                        elif t == "text_delta":
                            sys.stdout.write(ev["text"]); sys.stdout.flush()
                        elif t == "thinking_delta":
                            pass
                        elif t == "tool_start":
                            arg = ev["args"].get("command", "") if ev["name"] == "run_command" else json.dumps(ev["args"])
                            print(f"\n{C['dim']}▸ {ev['name']} {arg[:100]}{C['r']}")
                        elif t == "tool_end":
                            out = (ev.get("output") or "").strip().splitlines()
                            for ln in out[:6]:
                                print(f"{C['dim']}  {ln[:_w()-2]}{C['r']}")
                            if len(out) > 6:
                                print(f"{C['dim']}  … (+{len(out)-6} lines){C['r']}")
                        elif t == "approval_request":
                            detail = ev["args"].get("command", "") if ev["name"] == "run_command" else json.dumps(ev["args"])
                            print(f"\n{C['warn']}⚠ approval: {ev['name']} {detail[:120]}\n  {ev.get('reason','')}{C['r']}")
                            ans = (await _ainput(f"{C['warn']}  allow? [y/N] {C['r']}")).strip().lower()
                            await ws.send(json.dumps({"type": "approval", "id": ev["id"],
                                                      "approved": ans in ("y", "yes")}))
                        elif t == "error":
                            print(f"\n{C['err']}error: {ev.get('message','')}{C['r']}")
                        elif t == "turn_end":
                            print("\n")
                            return

                while True:
                    try:
                        text = (await _ainput(f"{C['acc']}{C['b']}❯ {C['r']}")).strip()
                    except (EOFError, KeyboardInterrupt):
                        print("\n" + C["dim"] + "bye." + C["r"]); break
                    if not text:
                        continue
                    if text in ("/quit", "/exit", ":q"):
                        break
                    if text == "/help":
                        print(HELP); continue
                    if text == "/clear":
                        cid = None; _banner(await get("/api/system"), model, name); continue
                    if text == "/sys":
                        d = await get("/api/system"); _print_sys(d); continue
                    if text == "/apps":
                        d = await get("/api/native/apps")
                        names = [a["name"] for a in d.get("apps", [])]
                        print(f"{C['dim']}" + ", ".join(names[:60]) + C["r"] + "\n"); continue
                    if text == "/models" or text == "/model":
                        for m in models.get("models", []):
                            mk = C["ok"] if m["id"] == model else C["dim"]
                            print(f"  {mk}{m['id']}{C['r']}")
                        print(); continue
                    if text.startswith("/model "):
                        model = text.split(" ", 1)[1].strip(); print(f"{C['dim']}model → {model}{C['r']}\n"); continue
                    if text == "/tasks":
                        d = await get("/api/tasks")
                        for tk in d.get("tasks", []):
                            print(f"  {C['acc']}{tk.get('prompt','')[:70]}{C['r']} {C['dim']}· {tk.get('schedule_type')}{C['r']}")
                        print(); continue

                    print(f"{C['teal']}{C['b']}{name}{C['r']} ", end="")
                    await ws.send(json.dumps({"type": "chat", "text": text, "surface": "tui",
                                              "conversation_id": cid, "model": model}))
                    await drain_turn()
        except Exception as e:
            print(f"{C['err']}connection error: {e}{C['r']}")


def _print_sys(d: dict):
    if not d:
        print(f"{C['err']}no data{C['r']}\n"); return
    mem = d.get("mem", {}); du = d.get("disk", {})
    print(f"  {C['b']}CPU{C['r']} {d.get('cpu',0):.0f}%   "
          f"{C['b']}MEM{C['r']} {mem.get('used_kb',0)/1e6:.1f}/{mem.get('total_kb',1)/1e6:.0f}GB   "
          f"{C['b']}DISK{C['r']} {du.get('used',0)/1e9:.0f}/{du.get('total',0)/1e9:.0f}GB   "
          f"{C['b']}load{C['r']} {' '.join(f'{x:.2f}' for x in d.get('load',[]))}")
    for p in d.get("procs", [])[:8]:
        print(f"  {C['dim']}{p['pid']:>7} {p['name'][:26]:<26} {p['cpu']:>5.1f}% {p['mem']:>5.1f}%{C['r']}")
    print()
