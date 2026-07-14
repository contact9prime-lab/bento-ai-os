"""AgentOS server: web UI, WebSocket event stream, REST API."""

import asyncio
import contextlib
import json
import os
import re
import secrets
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from . import config as cfgmod
from . import fabric as fabricmod
from . import knowledge
from . import providers
from .agent import Agent
from .mcp_client import MCP_AVAILABLE, MCPManager
from .memory import Store
from .policy import MAIN, PDP, Principal
from .scheduler import Scheduler
from .telegram import TelegramBridge
from .tools import Toolbox
from .trainforge import TrainForge

UI_DIR = Path(__file__).parent / "ui"

app = FastAPI(title="AgentOS")

state: dict = {}  # cfg, store, toolbox, scheduler, clients


@app.on_event("startup")
async def startup():
    cfg = cfgmod.load_config()
    cfgmod.ensure_dirs(cfg)
    store = Store(cfgmod.DB_PATH)
    toolbox = Toolbox(cfg, store)
    clients: set[WebSocket] = set()

    async def broadcast(event: dict):
        dead = []
        for ws in clients:
            try:
                await ws.send_text(json.dumps(event))
            except Exception:
                dead.append(ws)
        for ws in dead:
            clients.discard(ws)

    scheduler = Scheduler(cfg, store, toolbox, broadcast)
    toolbox.scheduler = scheduler
    mcp = MCPManager(cfg, store)
    toolbox.mcp = mcp
    telegram = TelegramBridge(cfg, store, toolbox, broadcast)
    toolbox.telegram = telegram
    toolbox.broadcast = broadcast
    control = fabricmod.ControlPlane(cfg, store, toolbox, broadcast)
    toolbox.fabric = control
    pdp = PDP(cfg, store)
    pdp.mcp = mcp
    toolbox.pdp = pdp
    trainforge = TrainForge(cfg, store)
    toolbox.trainforge = trainforge
    fabricmod.seed_builtins(cfg, store)
    state.update(cfg=cfg, store=store, toolbox=toolbox, scheduler=scheduler,
                 mcp=mcp, telegram=telegram, clients=clients, broadcast=broadcast,
                 fabric=control, pdp=pdp, trainforge=trainforge,
                 pending_approvals={},  # aid -> {"fut","offer","ws"} — global approval broker
                 app_tokens={},         # runtime token -> {"app_id","issued"} — app identity
                 pending_installs={},   # install_id -> staged app package awaiting consent
                 turns={},              # conversation_id -> {"agent","task","model"} — GLOBAL:
                                        # turns survive a page reload/reconnect; events broadcast
                 build={"agent": None, "task": None, "cancel_requested": False,
                        "timed_out": False})  # App Studio build slot (global, one at a time)
    asyncio.create_task(scheduler.run_forever())
    asyncio.create_task(mcp.start())
    asyncio.create_task(telegram.run_forever())
    asyncio.create_task(knowledge.maintenance_loop(cfg, store, broadcast))
    store.log("system", "AgentOS started")

    # pick a default model if none is set — but don't let this first write of
    # config.json disarm the setup wizard on a brand-new install
    if not cfg.get("default_model"):
        first = cfgmod.is_first_run()
        models = await providers.available_models(cfg)
        if models:
            cfg["default_model"] = models[0]["id"]
            if first:
                cfg["setup_complete"] = False
            cfgmod.save_config(cfg)

    # one-time permissions migration: apps that predate the framework get a VISIBLE
    # legacy full-access grant (revocable in the Permissions app) so nothing breaks;
    # approving their manifest later swaps it for scoped grants
    if not cfg.get("permissions_migrated") and cfgmod.CONFIG_PATH.exists():
        for a in store.list_apps():
            if (a.get("manifest_status") or "none") == "none":
                store.add_grant("app", a["id"], "*", "*", source="legacy",
                                note="pre-permissions app — full access until you approve "
                                     "its manifest")
                _propose_manifest(a["id"])  # draft from its source, ready for review
        cfg["permissions_migrated"] = True
        cfgmod.save_config(cfg)
        store.log("system", "permissions framework: legacy grants seeded for existing apps")


@app.on_event("shutdown")
async def shutdown():
    if "scheduler" in state:
        state["scheduler"].stop()
    if "telegram" in state:
        state["telegram"].stop()
    if "mcp" in state:
        await state["mcp"].stop()
    if "trainforge" in state:
        with contextlib.suppress(Exception):
            await state["trainforge"].stop()


# ---------------------------------------------------------------------------
# UI + REST
# ---------------------------------------------------------------------------

@app.get("/")
async def index():
    return FileResponse(UI_DIR / "index.html")


@app.get("/assets/{name}")
async def ui_assets(name: str):
    base = (UI_DIR / "assets").resolve()
    p = (base / name).resolve()
    if not str(p).startswith(str(base)) or not p.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    media = "text/css" if name.endswith(".css") else "application/javascript"
    return FileResponse(p, media_type=media)


@app.get("/api/analytics/tokens")
async def api_token_analytics():
    """Token usage aggregated from turn logs: totals, by-model, and a daily series."""
    import time as _t
    logs = state["store"].list_logs("turn", limit=1000)
    by_model: dict = {}
    by_day: dict = {}
    tin = tout = 0
    for L in logs:
        try:
            m = json.loads(L.get("meta") or "{}")
        except Exception:
            m = {}
        i, o = int(m.get("in", 0) or 0), int(m.get("out", 0) or 0)
        tin += i
        tout += o
        model = m.get("model", "unknown")
        bm = by_model.setdefault(model, {"in": 0, "out": 0, "turns": 0})
        bm["in"] += i
        bm["out"] += o
        bm["turns"] += 1
        day = _t.strftime("%Y-%m-%d", _t.localtime(L.get("created_at", 0)))
        bd = by_day.setdefault(day, {"in": 0, "out": 0})
        bd["in"] += i
        bd["out"] += o
    return {"total": {"in": tin, "out": tout, "turns": len(logs)},
            "by_model": by_model,
            "by_day": [{"day": k, **v} for k, v in sorted(by_day.items())]}


def _read_cpu() -> tuple[int, int]:
    with open("/proc/stat") as f:
        nums = [int(x) for x in f.readline().split()[1:]]
    idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
    return idle, sum(nums)


def _files_root() -> Path:
    from .tools import sandbox_conf
    _, root = sandbox_conf(state["cfg"])
    return Path(root)


def _safe_file(rel: str) -> Path | None:
    root = _files_root().resolve()
    p = (root / rel).resolve()
    if p == root or root in p.parents:
        return p
    return None


@app.get("/api/files")
async def api_files(path: str = ""):
    import time as _t
    root = _files_root()
    root.mkdir(parents=True, exist_ok=True)
    p = _safe_file(path)
    if p is None or not p.exists():
        p = root
    if p.is_file():
        p = p.parent
    rel = str(p.relative_to(root)) if p != root else ""
    entries = []
    for e in sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower())):
        try:
            st = e.stat()
        except OSError:
            continue
        entries.append({"name": e.name, "dir": e.is_dir(),
                        "rel": str(e.relative_to(root)),
                        "size": st.st_size, "mtime": st.st_mtime,
                        "ext": e.suffix.lower().lstrip(".")})
    return {"root": str(root), "path": rel, "entries": entries}


@app.post("/api/open")
async def api_open(body: dict):
    """Open a URL or a workspace file in the HOST OS (default browser / app)."""
    from . import desktop as desktopmod
    url = (body.get("url") or "").strip()
    rel = (body.get("path") or "").strip()
    if url:
        if not url.startswith(("http://", "https://")):
            return JSONResponse({"error": "only http(s) URLs"}, status_code=400)
        target = url
    elif rel:
        p = _safe_file(rel)
        if p is None or not p.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        target = str(p)
    else:
        return JSONResponse({"error": "nothing to open"}, status_code=400)
    err = desktopmod.open_path(target)
    if err:
        return JSONResponse({"error": err}, status_code=500)
    state["store"].log("system", f"opened in host: {target[:120]}")
    return {"ok": True, "target": target}


@app.get("/api/files/raw")
async def api_file_raw(path: str, download: int = 0):
    import mimetypes
    p = _safe_file(path)
    if p is None or not p.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    mt, _ = mimetypes.guess_type(str(p))
    # render text/html/images inline in the Browser; everything else downloads
    inline = (mt or "").startswith(("text/", "image/")) or (mt == "application/pdf") or p.suffix.lower() in (".html", ".htm", ".md", ".txt", ".json", ".csv", ".log")
    headers = {}
    if download or not inline:
        headers["Content-Disposition"] = f'attachment; filename="{p.name}"'
    if p.suffix.lower() in (".md", ".txt", ".log", ".csv", ".json"):
        mt = "text/plain; charset=utf-8"
    return FileResponse(p, media_type=mt or "application/octet-stream", headers=headers)


@app.get("/api/native/apps")
async def api_native_apps():
    from . import host
    apps = host.list_apps()
    for a in apps:
        a["has_icon"] = bool(host.resolve_icon(a["icon"]))
    return {"apps": apps}


@app.get("/api/native/icon/{app_id}")
async def api_native_icon(app_id: str):
    from . import host
    apps = {a["id"]: a for a in host.list_apps()}
    a = apps.get(app_id)
    path = host.resolve_icon(a["icon"]) if a else None
    if not path:
        return JSONResponse({"error": "no icon"}, status_code=404)
    mt = "image/svg+xml" if path.endswith(".svg") else "image/png"
    return FileResponse(path, media_type=mt, headers={"Cache-Control": "max-age=86400"})


@app.post("/api/native/launch")
async def api_native_launch(body: dict):
    from . import host
    ok, msg = host.launch_app(body.get("id", ""))
    if ok:
        state["store"].log("system", f"launched native app: {body.get('id','')}")
    return {"ok": ok, "message": msg}


@app.get("/api/windows")
async def api_windows():
    from . import host
    return host.list_windows()


@app.post("/api/windows/focus")
async def api_windows_focus(body: dict):
    from . import host
    ok, msg = host.focus_window(body.get("id", ""))
    return {"ok": ok, "message": msg}


@app.post("/api/windows/close")
async def api_windows_close(body: dict):
    from . import host
    ok, msg = host.close_window(body.get("id", ""))
    return {"ok": ok, "message": msg}


@app.get("/api/control")
async def api_control():
    from . import host
    return host.control_state()


@app.post("/api/control")
async def api_control_set(body: dict):
    from . import host
    if "settings" in body:
        ok, msg = host.open_settings(body.get("settings", ""))
        return {"ok": ok, "message": msg}
    host.set_volume(percent=body.get("volume"), mute=body.get("mute"))
    return host.get_volume()


@app.get("/api/system")
async def api_system():
    """Live system stats for the Task Manager app / TUI. Cross-platform, stdlib only:
    /proc on Linux, sysctl/vm_stat on macOS (no /proc there)."""
    import os
    import shutil
    import subprocess
    import sys as _sys

    darwin = _sys.platform == "darwin"
    cores = os.cpu_count() or 1

    cpu = 0.0
    if darwin:
        # no /proc/stat: approximate with the 1-minute load average per core
        cpu = round(min(100.0, os.getloadavg()[0] / cores * 100), 1)
    else:
        try:
            idle, total = _read_cpu()
            prev = state.get("cpu_prev")
            state["cpu_prev"] = (idle, total)
            if prev and total > prev[1]:
                cpu = round(100 * (1 - (idle - prev[0]) / (total - prev[1])), 1)
        except OSError:
            pass

    mem_total = mem_used = 0
    if darwin:
        try:
            mem_total = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                           text=True, timeout=3).stdout.strip()) // 1024  # kB
            vm = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=3).stdout
            page = 4096
            m = re.search(r"page size of (\d+)", vm)
            if m:
                page = int(m.group(1))
            pages = {k.strip(): int(v.strip().rstrip(".")) for k, v in
                     (ln.split(":", 1) for ln in vm.splitlines() if ":" in ln and "Pages" in ln)}
            free = (pages.get("Pages free", 0) + pages.get("Pages inactive", 0)
                    + pages.get("Pages speculative", 0)) * page // 1024
            mem_used = max(0, mem_total - free)
        except Exception:
            pass
    else:
        try:
            mem = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, v = line.split(":", 1)
                    mem[k] = int(v.strip().split()[0])  # kB
            mem_total = mem.get("MemTotal", 0)
            mem_used = mem_total - mem.get("MemAvailable", 0)
        except OSError:
            pass

    du = shutil.disk_usage(Path.home())
    uptime = 0.0
    if darwin:
        try:
            boot = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True,
                                  text=True, timeout=3).stdout
            m = re.search(r"sec\s*=\s*(\d+)", boot)
            if m:
                uptime = max(0.0, time.time() - int(m.group(1)))
        except Exception:
            pass
    else:
        try:
            with open("/proc/uptime") as f:
                uptime = float(f.read().split()[0])
        except OSError:
            pass

    procs = []
    try:
        argv = (["ps", "-Aceo", "pid,comm,%cpu,%mem", "-r"] if darwin
                else ["ps", "-eo", "pid,comm,%cpu,%mem", "--sort=-%cpu"])
        p = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await p.communicate()
        for line in out.decode(errors="replace").splitlines()[1:15]:
            tok = line.split()
            if len(tok) >= 4:
                procs.append({"pid": int(tok[0]), "name": " ".join(tok[1:-2]),
                              "cpu": float(tok[-2]), "mem": float(tok[-1])})
    except Exception:
        pass

    return {"cpu": max(cpu, 0.0), "load": list(os.getloadavg()),
            "mem": {"total_kb": mem_total, "used_kb": mem_used},
            "disk": {"total": du.total, "used": du.used},
            "uptime": uptime, "cores": cores, "procs": procs}


def _gpu_info() -> list[dict]:
    import shutil
    import subprocess
    if not shutil.which("nvidia-smi"):
        return []
    try:
        out = subprocess.run(["nvidia-smi",
                              "--query-gpu=name,memory.total,memory.used,utilization.gpu",
                              "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return []
    gpus = []
    for line in out.splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) >= 4:
            gpus.append({"name": p[0], "mem_total_mb": int(float(p[1])),
                         "mem_used_mb": int(float(p[2])), "util": int(float(p[3]))})
    return gpus


@app.get("/api/models/manage")
async def api_models_manage():
    """Installed Ollama models (sizes), what's loaded, and GPU capacity."""
    import httpx
    base = state["cfg"]["providers"]["ollama"]["base_url"]
    models, running = [], []
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            tags = (await c.get(f"{base}/api/tags")).json()
            models = [{"name": m["name"], "size": m.get("size", 0),
                       "family": (m.get("details") or {}).get("family", ""),
                       "params": (m.get("details") or {}).get("parameter_size", "")}
                      for m in tags.get("models", [])]
            try:
                ps = (await c.get(f"{base}/api/ps")).json()
                running = [{"name": m["name"], "size_vram": m.get("size_vram", 0)} for m in ps.get("models", [])]
            except Exception:
                pass
    except Exception as e:
        return {"error": str(e), "models": [], "running": [], "gpu": _gpu_info()}
    return {"models": models, "running": running, "gpu": _gpu_info()}


@app.post("/api/models/pull")
async def api_models_pull(body: dict):
    """Download an Ollama model in the background; broadcasts progress + 'models' when done."""
    import httpx
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "no model name"}, status_code=400)
    base = state["cfg"]["providers"]["ollama"]["base_url"]

    async def pull():
        state["store"].log("system", f"pulling model {name}")
        try:
            async with httpx.AsyncClient(timeout=None) as c:
                async with c.stream("POST", f"{base}/api/pull", json={"model": name}) as r:
                    last = ""
                    async for line in r.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            d = json.loads(line)
                        except Exception:
                            continue
                        status = d.get("status", "")
                        if d.get("total"):
                            pct = int(100 * d.get("completed", 0) / d["total"])
                            status = f"{status} {pct}%"
                        if status != last:
                            last = status
                            await state["broadcast"]({"type": "model_pull", "name": name, "status": status})
            await state["broadcast"]({"type": "model_pull", "name": name, "status": "done", "done": True})
            state["store"].log("system", f"pulled model {name}")
        except Exception as e:
            await state["broadcast"]({"type": "model_pull", "name": name, "status": f"error: {e}", "done": True})
        await state["broadcast"]({"type": "models"})

    asyncio.create_task(pull())
    return {"ok": True}


@app.delete("/api/models/{name:path}")
async def api_models_delete(name: str):
    import httpx
    base = state["cfg"]["providers"]["ollama"]["base_url"]
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            await c.request("DELETE", f"{base}/api/delete", json={"model": name})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    state["store"].log("system", f"deleted model {name}")
    await state["broadcast"]({"type": "models"})
    return {"ok": True}


@app.get("/api/models")
async def api_models():
    return {"models": await providers.available_models(state["cfg"]),
            "default": state["cfg"].get("default_model", "")}


@app.get("/api/config")
async def api_get_config():
    cfg = json.loads(json.dumps(state["cfg"]))
    for p in cfg["providers"].values():
        if p.get("api_key"):
            p["api_key"] = "•••" + p["api_key"][-4:]
            p["_has_key"] = True
    if cfg.get("telegram", {}).get("bot_token"):
        cfg["telegram"]["bot_token"] = "•••" + cfg["telegram"]["bot_token"][-4:]
        cfg["telegram"]["_has_token"] = True
    if cfg.get("github", {}).get("token"):
        cfg["github"]["token"] = "•••" + cfg["github"]["token"][-4:]
        cfg["github"]["_has_token"] = True
    return cfg


@app.put("/api/config")
async def api_put_config(patch: dict):
    cfg = state["cfg"]
    for key in ("default_model", "autonomy", "max_steps", "workspace", "agent_name", "policies", "sandbox"):
        if key in patch:
            cfg[key] = patch[key]
    if isinstance(patch.get("memory"), dict):
        mem = cfg.setdefault("memory", {})
        for k in ("auto_extract", "model", "inject_user", "inject_session", "inject_facts",
                  "embed_model", "rollup_after_hours", "kg_dedup"):
            if k in patch["memory"]:
                mem[k] = patch["memory"][k]
    if isinstance(patch.get("image"), dict):
        img = cfg.setdefault("image", {})
        for k in ("provider", "model"):
            if k in patch["image"]:
                img[k] = patch["image"][k]
    for name, pconf in (patch.get("providers") or {}).items():
        if name not in cfg["providers"]:
            continue
        for k in ("enabled", "base_url", "models"):
            if k in pconf:
                cfg["providers"][name][k] = pconf[k]
        # masked keys ("•••xxxx") mean "unchanged"
        if "api_key" in pconf and not str(pconf["api_key"]).startswith("•••"):
            cfg["providers"][name]["api_key"] = pconf["api_key"]
    if isinstance(patch.get("github"), dict):
        gh = cfg.setdefault("github", {"token": "", "username": ""})
        if "username" in patch["github"]:
            gh["username"] = patch["github"]["username"]
        if "token" in patch["github"] and not str(patch["github"]["token"]).startswith("•••"):
            gh["token"] = patch["github"]["token"]
    cfgmod.save_config(cfg)
    cfgmod.ensure_dirs(cfg)
    return {"ok": True}


@app.get("/api/conversations")
async def api_conversations():
    return {"conversations": state["store"].list_conversations()}


@app.get("/api/conversations/{cid}")
async def api_conversation(cid: str):
    return {"messages": state["store"].get_messages(cid)}


@app.delete("/api/conversations/{cid}")
async def api_delete_conversation(cid: str):
    state["store"].delete_conversation(cid)
    return {"ok": True}


@app.post("/api/conversations/{cid}/clear")
async def api_clear_conversation(cid: str):
    state["store"].clear_messages(cid)
    state["store"].log("system", f"session {cid} cleared")
    return {"ok": True}


# ---- MCP ------------------------------------------------------------------

@app.get("/api/mcp")
async def api_mcp():
    return {"available": MCP_AVAILABLE, "servers": state["mcp"].status()}


@app.put("/api/mcp")
async def api_put_mcp(body: dict):
    """Replace the MCP server config and reconnect."""
    servers = body.get("servers")
    if isinstance(servers, dict):
        state["cfg"]["mcp_servers"] = servers
        cfgmod.save_config(state["cfg"])
        await state["mcp"].reload()
    return {"ok": True}


# ---- Telegram ---------------------------------------------------------------

@app.get("/api/telegram")
async def api_telegram():
    return state["telegram"].info()


@app.put("/api/telegram")
async def api_put_telegram(body: dict):
    t = state["cfg"].setdefault("telegram", {})
    if "enabled" in body:
        t["enabled"] = bool(body["enabled"])
    tok = str(body.get("bot_token", ""))
    if tok and not tok.startswith("•••"):
        t["bot_token"] = tok.strip()
        state["telegram"].bot_username = ""   # force re-validation with the new token
        if "enabled" not in body:
            t["enabled"] = True               # setting a token means "connect"
    if body.get("unpair"):
        t["owner_chat_id"] = 0
    cfgmod.save_config(state["cfg"])
    return {"ok": True}


@app.put("/api/telegram/chats/{chat_id}")
async def api_telegram_chat(chat_id: int, body: dict):
    if "allowed" in body:
        state["store"].tg_set_allowed(chat_id, 1 if body["allowed"] else 0)
        state["store"].log("telegram", f"chat {chat_id} {'enabled' if body['allowed'] else 'disabled'}")
    return {"ok": True}


@app.delete("/api/telegram/chats/{chat_id}")
async def api_telegram_chat_delete(chat_id: int):
    state["store"].tg_delete_chat(chat_id)
    return {"ok": True}


@app.post("/api/telegram/test")
async def api_telegram_test():
    result = await state["telegram"].send("▲ Test message from AgentOS — the bridge works.")
    return {"result": result}


# ---- Logs -------------------------------------------------------------------

@app.get("/api/logs")
async def api_logs(kind: str = "", limit: int = 300, q: str = ""):
    """System logs, filterable by kind and free-text search (message + meta)."""
    return {"logs": state["store"].list_logs(kind, min(limit, 1000), q=q)}


@app.delete("/api/logs")
async def api_clear_logs():
    state["store"].clear_logs()
    return {"ok": True}


# ---- Knowledge graph ---------------------------------------------------------

@app.get("/api/kg")
async def api_kg():
    return state["store"].kg_graph()


@app.post("/api/kg")
async def api_kg_add(body: dict):
    eid = state["store"].kg_add(
        body.get("subject", ""), body.get("relation", ""), body.get("object", ""),
        body.get("subject_type", ""), body.get("object_type", ""))
    return {"id": eid}


@app.delete("/api/kg")
async def api_kg_clear():
    state["store"].kg_clear()
    state["store"].log("system", "knowledge graph cleared")
    return {"ok": True}


@app.delete("/api/kg/nodes/{nid}")
async def api_kg_delete_node(nid: str):
    state["store"].kg_delete_node(nid)
    return {"ok": True}


# ---- Store: curated one-click templates (install without needing a model) ----

STORE_TEMPLATES = [
    {"id": "pomodoro", "name": "Focus Timer", "icon": "", "desc": "25/5 focus timer",
     "html": """<h2 style='margin:0 0 6px'>Focus Timer</h2>
<div id='t' style='font-size:56px;font-weight:800;text-align:center;font-variant-numeric:tabular-nums'>25:00</div>
<div style='display:flex;gap:8px;justify-content:center;margin-top:10px'>
<button id='s'>Start</button><button id='r'>Reset</button><button id='b'>Break</button></div>
<script>let left=1500,run=0,iv;const el=document.getElementById('t');
function fmt(){el.textContent=String(Math.floor(left/60)).padStart(2,'0')+':'+String(left%60).padStart(2,'0')}
function tick(){if(left>0){left--;fmt()}else{clearInterval(iv);run=0;document.getElementById('s').textContent='Start';try{new Audio('data:audio/wav;base64,UklGRl9vAAA=').play()}catch(e){}}}
document.getElementById('s').onclick=function(){if(run){clearInterval(iv);run=0;this.textContent='Start'}else{run=1;this.textContent='Pause';iv=setInterval(tick,1000)}};
document.getElementById('r').onclick=()=>{clearInterval(iv);run=0;left=1500;fmt();document.getElementById('s').textContent='Start'};
document.getElementById('b').onclick=()=>{clearInterval(iv);run=0;left=300;fmt();document.getElementById('s').textContent='Start'};
fmt();</script>"""},
    {"id": "notes", "name": "Quick Notes", "icon": "", "desc": "a scratchpad that saves itself",
     "html": """<h2 style='margin:0 0 8px'>Quick Notes</h2>
<textarea id='n' style='width:100%;height:calc(100vh - 90px);background:#171b22;color:#e6ebf2;border:1px solid #232a35;border-radius:8px;padding:12px;font-size:14px;line-height:1.6' placeholder='Type… saved automatically'></textarea>
<div id='st' style='color:#5c6577;font-size:11px;margin-top:6px'>saved</div>
<script>const n=document.getElementById('n'),st=document.getElementById('st');
n.value=localStorage.getItem('quicknotes')||'';let t;
n.oninput=()=>{st.textContent='saving…';clearTimeout(t);t=setTimeout(()=>{localStorage.setItem('quicknotes',n.value);st.textContent='saved '+new Date().toLocaleTimeString()},400)};</script>"""},
    {"id": "calc", "name": "Calculator", "icon": "", "desc": "a simple calculator",
     "html": """<h2 style='margin:0 0 8px'>Calculator</h2>
<input id='d' readonly style='width:100%;text-align:right;font-size:26px;padding:10px;background:#171b22;color:#e6ebf2;border:1px solid #232a35;border-radius:8px;font-variant-numeric:tabular-nums'>
<div id='pad' style='display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:8px'></div>
<script>const d=document.getElementById('d');let s='';
const keys=['7','8','9','/','4','5','6','*','1','2','3','-','0','.','=','+','C'];
const pad=document.getElementById('pad');
keys.forEach(k=>{const b=document.createElement('button');b.textContent=k;b.style.padding='14px';b.style.fontSize='17px';
b.onclick=()=>{if(k==='C'){s='';}else if(k==='='){try{s=String(Function('return '+s)())}catch(e){s='error'}}else{s+=k}d.value=s};pad.appendChild(b)});</script>"""},
    {"id": "worldclock", "name": "World Clock", "icon": "", "desc": "times around the world",
     "html": """<h2 style='margin:0 0 10px'>World Clock</h2><div id='z'></div>
<script>const zones=[['Mumbai','Asia/Kolkata'],['London','Europe/London'],['New York','America/New_York'],['San Francisco','America/Los_Angeles'],['Tokyo','Asia/Tokyo'],['Sydney','Australia/Sydney']];
function tick(){document.getElementById('z').innerHTML=zones.map(([n,tz])=>{const t=new Date().toLocaleTimeString('en-GB',{timeZone:tz,hour:'2-digit',minute:'2-digit'});return "<div style='display:flex;justify-content:space-between;padding:10px 12px;margin-bottom:7px;background:#171b22;border:1px solid #232a35;border-radius:9px'><span>"+n+"</span><b style='font-variant-numeric:tabular-nums;font-size:16px'>"+t+"</b></div>"}).join('')}
tick();setInterval(tick,1000);</script>"""},
    {"id": "sysmon", "name": "System Monitor", "icon": "", "desc": "live CPU, memory & disk",
     "html": """<h2 style='margin:0 0 10px'>System Monitor</h2><div id='m'>loading…</div>
<script>function bar(p,c){return "<div style='height:8px;border-radius:5px;background:#1e242e;overflow:hidden;margin:4px 0 12px'><div style='height:100%;width:"+Math.min(p,100)+"%;background:"+(p>85?'#f87171':c)+"'></div></div>"}
async function tick(){try{const d=await (await fetch('/api/system')).json();const mp=100*d.mem.used_kb/d.mem.total_kb,dp=100*d.disk.used/d.disk.total;
document.getElementById('m').innerHTML="<b>CPU "+d.cpu.toFixed(0)+"%</b>"+bar(d.cpu,'#5eead4')+"<b>Memory "+mp.toFixed(0)+"%</b>"+bar(mp,'#22d3ee')+"<b>Disk "+dp.toFixed(0)+"%</b>"+bar(dp,'#5eead4')+"<div style='color:#5c6577;font-size:12px'>"+d.cores+" cores · load "+d.load.map(x=>x.toFixed(2)).join(' ')+"</div>"}catch(e){}}
tick();setInterval(tick,2000);</script>"""},
]


@app.get("/api/store/templates")
async def api_store_templates():
    installed = {a["name"] for a in state["store"].list_apps()}
    return {"templates": [{**{k: v for k, v in t.items() if k != "html"},
                           "installed": t["name"] in installed} for t in STORE_TEMPLATES]}


@app.post("/api/store/install")
async def api_store_install(body: dict):
    t = next((x for x in STORE_TEMPLATES if x["id"] == body.get("id")), None)
    if not t:
        return JSONResponse({"error": "unknown template"}, status_code=404)
    aid = state["store"].save_app(t["name"], t["icon"], t["desc"], t["html"], note="installed from store")
    state["store"].log("system", f"store install: {t['name']}")
    await state["broadcast"]({"type": "apps"})
    return {"ok": True, "id": aid, "name": t["name"]}


# ---- User apps (AI-built UI tools) --------------------------------------------

APP_SHELL = """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
:root{{color-scheme:dark}}
body{{background:#0e1116;color:#e6ebf2;font-family:-apple-system,'Segoe UI',Roboto,sans-serif;
     font-size:14px;margin:0;padding:14px}}
button{{background:#1e242e;color:#e6ebf2;border:1px solid #232a35;border-radius:8px;padding:7px 14px;cursor:pointer}}
button:hover{{border-color:#5eead4}}
input,select,textarea{{background:#171b22;color:#e6ebf2;border:1px solid #232a35;border-radius:8px;padding:7px 10px}}
a{{color:#22d3ee}}
</style></head><body>{body}</body></html>"""


@app.get("/api/apps")
async def api_apps(html: int = 0):
    return {"apps": state["store"].list_apps(with_html=bool(html))}


@app.get("/api/themes")
async def api_themes():
    return {"themes": state["store"].list_themes()}


@app.post("/api/themes")
async def api_save_theme(body: dict):
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "theme needs a name"}, status_code=400)
    state["store"].save_theme(name, json.dumps(body))
    await state["broadcast"]({"type": "themes"})
    if body.get("apply"):
        await state["broadcast"]({"type": "theme_apply", "theme": body})
    return {"ok": True, "name": name}


@app.delete("/api/themes/{name}")
async def api_delete_theme(name: str):
    state["store"].delete_theme(name)
    await state["broadcast"]({"type": "themes"})
    return {"ok": True}


@app.get("/api/widgets")
async def api_widgets():
    return {"widgets": state["cfg"].get("widgets", [])}


@app.put("/api/widgets")
async def api_put_widgets(body: dict):
    w = body.get("widgets")
    if isinstance(w, list):
        state["cfg"]["widgets"] = w
        cfgmod.save_config(state["cfg"])
        await state["broadcast"]({"type": "widgets"})
    return {"ok": True}


@app.post("/api/apps")
async def api_save_app(body: dict):
    aid = state["store"].save_app(body.get("name", ""), body.get("icon", ""),
                                  body.get("description", ""), body.get("html", ""))
    state["store"].log("system", f"user app saved: {body.get('name', '')}")
    await state["broadcast"]({"type": "apps"})
    return {"id": aid}


@app.delete("/api/apps/{aid}")
async def api_delete_app(aid: str):
    state["store"].delete_app(aid)
    await state["broadcast"]({"type": "apps"})
    return {"ok": True}


APP_RUNTIME = """<script>
window.APP_ID = %r;
window.APP_TOKEN = %r; // runtime identity: the OS knows WHICH app is calling (permission gate)
// Every built app gets its own data store (its "MCP"): appData.get()/set() persist server-side
// and are readable by the agent. Also appTool(name,args) runs any OS/MCP tool.
window.appData = {
  async get(){ try{ return await (await fetch('/api/apps/'+window.APP_ID+'/data',{headers:{'X-App-Token':window.APP_TOKEN}})).json(); }catch(e){ return {}; } },
  async set(obj){ try{ await fetch('/api/apps/'+window.APP_ID+'/data',{method:'PUT',headers:{'Content-Type':'application/json','X-App-Token':window.APP_TOKEN},body:JSON.stringify(obj)}); }catch(e){} },
};
window.appTool = async (name,args={}) => {
  try{ const r = await fetch('/api/tool',{method:'POST',headers:{'Content-Type':'application/json','X-App-Token':window.APP_TOKEN},body:JSON.stringify({name,args})}); return await r.json(); }catch(e){ return {error:String(e)}; }
};
// AI inside the app: one-shot LLM completion (no tools). Returns plain text.
window.appLLM = async (prompt, system='') => {
  const r = await window.appTool('llm_generate', system ? {prompt, system} : {prompt});
  if (r && r.output !== undefined) return r.output;
  return '[error] ' + ((r && r.error) || 'llm unavailable');
};
// surface runtime errors to the host (App Studio shows them with a one-click fix)
window.addEventListener('error', e => {
  try{ parent.postMessage({agentos:'app_error', app_id:window.APP_ID,
    message:String((e && (e.message||e.error))||'script error').slice(0,300),
    source:((e&&e.filename)||'')+':'+((e&&e.lineno)||0)}, '*'); }catch(_){}
});
window.addEventListener('unhandledrejection', e => {
  try{ parent.postMessage({agentos:'app_error', app_id:window.APP_ID,
    message:('unhandled rejection: '+String(e&&e.reason)).slice(0,300), source:''}, '*'); }catch(_){}
});
</script>"""


@app.get("/api/apps/{aid}/page")
async def api_app_page(aid: str):
    from fastapi.responses import HTMLResponse
    a = state["store"].get_app(aid)
    if not a:
        return JSONResponse({"error": "not found"}, status_code=404)
    # mint the app's runtime identity token (revocation lives in grants, not token expiry,
    # since the PDP reads live grants — the token only says WHO is calling)
    tok = secrets.token_urlsafe(24)
    now = time.time()
    state["app_tokens"][tok] = {"app_id": aid, "issued": now}
    for k, v in list(state["app_tokens"].items()):
        if now - v["issued"] > 86400:
            state["app_tokens"].pop(k, None)
    html = a["html"] or ""
    if not html.lstrip().lower().startswith(("<!doctype", "<html")):
        html = APP_SHELL.format(body=html)
    runtime = APP_RUNTIME % (aid, tok)
    # inject the runtime right after <body>, or prepend it
    low = html.lower()
    if "<body" in low:
        i = low.index("<body")
        i = low.index(">", i) + 1
        html = html[:i] + runtime + html[i:]
    else:
        html = runtime + html
    return HTMLResponse(html)


@app.get("/api/apps/{aid}/versions")
async def api_app_versions(aid: str):
    """Version history for an app — every save with changed source is restorable."""
    return {"versions": state["store"].app_versions(aid)}


@app.get("/api/apps/{aid}/versions/{version}")
async def api_app_version(aid: str, version: int):
    v = state["store"].get_app_version(aid, version)
    if not v:
        return JSONResponse({"error": "not found"}, status_code=404)
    return v


@app.post("/api/apps/{aid}/versions/{version}/restore")
async def api_app_version_restore(aid: str, version: int):
    ok = state["store"].restore_app_version(aid, version)
    if ok:
        state["store"].log("system", f"app {aid}: restored v{version}")
        await state["broadcast"]({"type": "apps"})
    return {"ok": ok}


@app.get("/api/apps/{aid}/data")
async def api_app_data_get(aid: str, request: Request):
    p = _principal_of(request)
    if p.kind == "app" and p.id != aid:  # app↔app data needs an explicit grant
        if state["pdp"].decide(p, "app.data.read", f"app:{aid}/data").effect != "allow":
            state["store"].log("policy", f"deny: {p.label} → app.data.read app:{aid}/data",
                               {"principal": p.label, "action": "app.data.read",
                                "resource": f"app:{aid}/data", "effect": "deny", "via": "app_data"})
            return JSONResponse({"error": "denied: no grant to read another app's data "
                                          "(add app.data.read in the Permissions app)"},
                                status_code=403)
    return json.loads(state["store"].get_app_data(aid) or "{}")


@app.put("/api/apps/{aid}/data")
async def api_app_data_set(aid: str, body: dict, request: Request):
    p = _principal_of(request)
    if p.kind == "app" and p.id != aid:
        if state["pdp"].decide(p, "app.data.write", f"app:{aid}/data").effect != "allow":
            state["store"].log("policy", f"deny: {p.label} → app.data.write app:{aid}/data",
                               {"principal": p.label, "action": "app.data.write",
                                "resource": f"app:{aid}/data", "effect": "deny", "via": "app_data"})
            return JSONResponse({"error": "denied: no grant to write another app's data "
                                          "(add app.data.write in the Permissions app)"},
                                status_code=403)
    state["store"].set_app_data(aid, json.dumps(body)[:200_000])
    return {"ok": True}


# ---- App manifests: declared permissions, consented by the user ------------------

def _app_manifest(a: dict) -> dict:
    try:
        man = json.loads(a.get("manifest") or "{}")
    except Exception:
        man = {}
    man.setdefault("format", 1)
    man.setdefault("name", a.get("name", ""))
    man.setdefault("permissions", [])
    man.setdefault("prerequisites", {})
    return man


@app.get("/api/apps/{aid}/manifest")
async def api_app_manifest(aid: str):
    """An app's permission manifest + status (none | proposed | approved) + its live grants."""
    a = state["store"].get_app(aid)
    if not a:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"manifest": _app_manifest(a), "status": a.get("manifest_status") or "none",
            "grants": state["store"].list_grants("app", aid)}


def _scan_app_permissions(html: str) -> list[dict]:
    """Infer an app's needed permissions from its source: appTool('x') calls, appData
    usage and /api/chat fetches. Static scan first — historical logs predate per-app
    identity, so the source is the most reliable signal."""
    import re as _re
    from . import policy as policymod
    perms, seen = [], set()
    for t in sorted(set(_re.findall(r"appTool\(\s*['\"]([\w.-]+)['\"]", html or ""))):
        action, resource = policymod.action_of(t, {}, mcp=state.get("mcp"))
        if action == "tool.use":
            resource = f"tool:{t}*"
        elif action in ("fs.read", "fs.write"):
            resource = "fs:*"
        elif action == "net.fetch":
            resource = "net:*"
        elif action == "mcp.use" and "/" not in resource:
            # the server isn't connected, so mcp_<server>_<tool> couldn't resolve —
            # recover the server name from the configured entries (same mangling)
            from .mcp_client import _safe
            suffix = resource[4:]
            for s in (state["cfg"].get("mcp_servers") or {}):
                if suffix == _safe(s) or suffix.startswith(_safe(s) + "_"):
                    resource = f"mcp:{s}/{suffix[len(_safe(s)) + 1:] or '*'}"
                    break
        if (action, resource) in seen:
            continue
        seen.add((action, resource))
        perms.append({"action": action, "resource": resource,
                      "reason": f"calls appTool('{t}')", "required": False})
    if _re.search(r"appLLM\s*\(", html or "") and ("tool.use", "tool:llm_generate*") not in seen:
        seen.add(("tool.use", "tool:llm_generate*"))
        perms.append({"action": "tool.use", "resource": "tool:llm_generate*",
                      "reason": "uses the AI model inside the app (appLLM)", "required": False})
    if _re.search(r"appData\.(get|set)", html or ""):
        perms.append({"action": "app.data.*", "resource": "app:self/data",
                      "reason": "saves its own settings/data", "required": True})
    if _re.search(r"fetch\(\s*[`'\"]/api/chat", html or ""):
        perms.append({"action": "agent.invoke", "resource": "agent:main",
                      "reason": "asks the AI over POST /api/chat", "required": False})
    return perms


def _mine_app_log_permissions(aid: str) -> list[dict]:
    """Tighten the proposal with what the app actually did (logs carry app_id now)."""
    from . import policy as policymod
    perms, seen = [], set()
    for L in state["store"].list_logs("tool", limit=1000):
        try:
            meta = json.loads(L.get("meta") or "{}")
        except Exception:
            continue
        if meta.get("app_id") != aid:
            continue
        name = (L.get("message") or "").replace("app→", "", 1)
        args = meta.get("args") or {}
        action, resource = policymod.action_of(name, args, mcp=state.get("mcp"))
        if name == "run_command":
            base = (args.get("command") or "").split()
            resource = f"tool:run_command {base[0]}*" if base else "tool:run_command*"
        elif action == "tool.use":
            resource = f"tool:{name}*"
        if (action, resource) in seen:
            continue
        seen.add((action, resource))
        perms.append({"action": action, "resource": resource,
                      "reason": "observed in this app's activity log", "required": False})
    return perms


def _propose_manifest(aid: str) -> dict | None:
    """Draft a manifest (source scan + log mining) and queue it for the user's review."""
    a = state["store"].get_app(aid)
    if not a:
        return None
    perms = _scan_app_permissions(a.get("html") or "")
    have = {(p["action"], p["resource"]) for p in perms}
    perms += [p for p in _mine_app_log_permissions(aid)
              if (p["action"], p["resource"]) not in have]
    man = _app_manifest(a)
    man["permissions"] = perms
    man["description"] = man.get("description") or (a.get("description") or "")
    state["store"].set_app_manifest(aid, json.dumps(man), "proposed")
    return man


@app.post("/api/apps/{aid}/manifest/propose")
async def api_app_manifest_propose(aid: str):
    """Draft a permission manifest from the app's source and activity, for user review."""
    man = _propose_manifest(aid)
    if man is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    await state["broadcast"]({"type": "apps"})
    return {"manifest": man, "status": "proposed"}


@app.post("/api/apps/{aid}/manifest/approve")
async def api_app_manifest_approve(aid: str, body: dict):
    """Consent: write one grant per accepted manifest permission and retire any legacy
    full-access grant. body.granted = list of permission indices the user accepted
    (required permissions are always included; omit `granted` to accept everything)."""
    store = state["store"]
    a = store.get_app(aid)
    if not a:
        return JSONResponse({"error": "not found"}, status_code=404)
    man = _app_manifest(a)
    perms = man.get("permissions") or []
    granted = body.get("granted")
    idx = set(granted) if isinstance(granted, list) else set(range(len(perms)))
    n = 0
    for i, p in enumerate(perms):
        if not (p.get("required") or i in idx):
            continue
        res = (p.get("resource") or "*").replace("app:self/", f"app:{aid}/")
        store.add_grant("app", aid, p.get("action") or "*", res,
                        source="manifest", note=p.get("reason", ""))
        n += 1
    store.revoke_grants_for("app", aid, source="legacy")
    store.set_app_manifest(aid, json.dumps(man), "approved")
    store.log("policy", f"manifest approved for app '{a['name']}': {n} permission(s) granted",
              {"principal": f"app:{aid}", "granted": n, "via": "consent_screen"})
    await state["broadcast"]({"type": "grants"})
    await state["broadcast"]({"type": "apps"})
    return {"ok": True, "granted": n}


# ---- App packages: distribution with consent (export / import) -------------------

def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _package_checksum(manifest: dict, html: str) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256((_canonical(manifest) + "\n" + html).encode()).hexdigest()


def _sanitize_mcp_conf(name: str, conf: dict) -> dict:
    """A shareable MCP prerequisite: connection shape only — secrets become placeholders
    the installing user fills in themselves. Real env/headers values NEVER leave this OS."""
    out = {"name": name}
    for k in ("transport", "command", "args", "url"):
        if conf.get(k):
            out[k] = conf[k]
    if conf.get("env"):
        out["env_template"] = {k: f"<YOUR_{k}>" for k in conf["env"]}
    if conf.get("headers"):
        out["headers_template"] = {k: "<your value>" for k in conf["headers"]}
    return out


@app.get("/api/apps/{aid}/export")
async def api_app_export(aid: str):
    """Export an app as a portable package (manifest + HTML + prerequisite declarations
    + integrity checksum) installable on another AgentOS. Secrets are never included."""
    a = state["store"].get_app(aid)
    if not a:
        return JSONResponse({"error": "not found"}, status_code=404)
    man = _app_manifest(a)
    if not man.get("permissions") and (a.get("manifest_status") or "none") == "none":
        man = _propose_manifest(aid) or man
    prereq = dict(man.get("prerequisites") or {})
    mcp_names = {r.split(":", 1)[1].split("/", 1)[0]
                 for p in man.get("permissions", [])
                 for r in [p.get("resource") or ""] if r.startswith("mcp:")}
    declared = {m.get("name") for m in prereq.get("mcp_servers", [])}
    for nm in sorted(mcp_names - declared):
        conf = (state["cfg"].get("mcp_servers") or {}).get(nm)
        if conf:
            prereq.setdefault("mcp_servers", []).append(_sanitize_mcp_conf(nm, conf))
    man["prerequisites"] = prereq
    man["description"] = man.get("description") or (a.get("description") or "")
    html = a.get("html") or ""
    pkg = {"format": "agentos-app/1", "manifest": man, "html": html,
           "checksum": _package_checksum(man, html), "signature": None}
    from fastapi.responses import Response
    fname = (a["name"] or "app").lower().replace(" ", "-") + ".agentapp.json"
    return Response(json.dumps(pkg, indent=1), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.post("/api/apps/import")
async def api_app_import(body: dict):
    """Stage an app package (inline or from a URL) for install: verify integrity and diff
    prerequisites. Nothing installs and nothing is granted until the user confirms."""
    pkg = body.get("package")
    url = (body.get("url") or "").strip()
    if not pkg and url:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                r = await client.get(url)
            if r.status_code != 200:
                return JSONResponse({"error": f"HTTP {r.status_code} fetching package"},
                                    status_code=400)
            pkg = r.json()
        except Exception as e:
            return JSONResponse({"error": f"fetch failed: {e}"}, status_code=400)
    if not isinstance(pkg, dict) or pkg.get("format") != "agentos-app/1":
        return JSONResponse({"error": "not an agentos-app/1 package"}, status_code=400)
    man, html = pkg.get("manifest") or {}, pkg.get("html") or ""
    if not man.get("name") or len(html.strip()) < 20:
        return JSONResponse({"error": "package is missing a name or app markup"}, status_code=400)
    if pkg.get("checksum") != _package_checksum(man, html):
        return JSONResponse({"error": "checksum mismatch — the package was modified in transit"},
                            status_code=400)
    prereq = man.get("prerequisites") or {}
    have_mcp = set((state["cfg"].get("mcp_servers") or {}).keys())
    have_skills = {s["name"].lower() for s in state["store"].list_skills()}
    missing = {
        "mcp_servers": [m for m in prereq.get("mcp_servers", []) if m.get("name") not in have_mcp],
        "skills": [s for s in prereq.get("skills", [])
                   if (s.get("name") or "").lower() not in have_skills],
    }
    iid = uuid.uuid4().hex[:8]
    state["pending_installs"][iid] = pkg
    conflict = any(a["name"].lower() == man["name"].lower() for a in state["store"].list_apps())
    return {"install_id": iid, "manifest": man, "missing": missing, "name_conflict": conflict}


@app.post("/api/apps/import/{iid}/confirm")
async def api_app_import_confirm(iid: str, body: dict):
    """Complete a staged install: save the app, write ONLY the accepted grants, and add
    the prerequisite MCP servers (disabled, placeholder keys) / skills the user opted into."""
    pkg = state["pending_installs"].pop(iid, None)
    if not pkg:
        return JSONResponse({"error": "unknown or expired install"}, status_code=404)
    man, html = pkg["manifest"], pkg["html"]
    name = (body.get("name") or man["name"]).strip()
    aid = state["store"].save_app(name, man.get("icon", ""), man.get("description", ""),
                                  html, note="installed from package")
    perms = man.get("permissions") or []
    granted = body.get("granted")
    idx = set(granted) if isinstance(granted, list) else set(range(len(perms)))
    for i, p in enumerate(perms):
        if p.get("required") or i in idx:
            res = (p.get("resource") or "*").replace("app:self/", f"app:{aid}/")
            state["store"].add_grant("app", aid, p.get("action") or "*", res,
                                     source="manifest", note=p.get("reason", ""))
    state["store"].set_app_manifest(aid, json.dumps(man), "approved")
    installed = {"mcp": [], "skills": []}
    for m in (man.get("prerequisites") or {}).get("mcp_servers", []):
        if m.get("name") in (body.get("install_mcp") or []):
            conf = {k: m[k] for k in ("transport", "command", "args", "url") if m.get(k)}
            conf["enabled"] = False  # placeholder keys: user fills them in the MCP app first
            if m.get("env_template"):
                conf["env"] = dict(m["env_template"])
            if m.get("headers_template"):
                conf["headers"] = dict(m["headers_template"])
            state["cfg"].setdefault("mcp_servers", {})[m["name"]] = conf
            installed["mcp"].append(m["name"])
    if installed["mcp"]:
        cfgmod.save_config(state["cfg"])
        await state["mcp"].reload()
    for s in (man.get("prerequisites") or {}).get("skills", []):
        if s.get("name") in (body.get("install_skills") or []) and s.get("source"):
            res = await api_install_skill({"source": s["source"]})
            if isinstance(res, dict) and res.get("ok"):
                installed["skills"].append(s["name"])
    state["store"].log("system", f"app installed from package: {name}")
    await state["broadcast"]({"type": "apps"})
    await state["broadcast"]({"type": "grants"})
    return {"ok": True, "id": aid, "installed": installed}


def _extract_html(text: str) -> str:
    """Pull an HTML app out of model text: a ```html fenced block, any fenced block that
    looks like HTML, or a raw <...> body. Trailing prose/fences after the markup (models
    love to append 'I have built…' or leftover tool-call JSON) is cut off."""
    import re
    if not text:
        return ""

    def _trim(chunk: str) -> str:
        chunk = chunk.split("\n```")[0]  # stop at a closing/next fence
        # cut anything after the last closing tag — trailing prose is never part of the app
        m2 = re.match(r"([\s\S]*</[a-zA-Z][a-zA-Z0-9-]*>)", chunk)
        if m2:
            chunk = m2.group(1)
        return chunk.strip().rstrip("`").strip()

    m = re.search(r"```(?:html)?\s*\n(.*?)```", text, re.DOTALL)
    if m and ("<" in m.group(1)):
        return _trim(m.group(1))
    m = re.search(r"(<(?:!doctype|html|div|h[1-6]|style|section|main|body)[\s\S]*)", text, re.IGNORECASE)
    if m and len(m.group(1)) > 40:
        return _trim(m.group(1))
    return ""


def _extract_app_meta(text: str) -> tuple[str, str]:
    """Fish name/description out of a botched tool-call the model wrote as text."""
    import re
    name = desc = ""
    m = re.search(r"[\"']?name[\"']?\s*[:=]\s*[\"']([^\"']{2,40})[\"']", text or "")
    if m:
        name = m.group(1).strip()
    m = re.search(r"[\"']?description[\"']?\s*[:=]\s*[\"']([^\"']{2,120})[\"']", text or "")
    if m:
        desc = m.group(1).strip()
    return name, desc


def _default_app_name(prompt: str) -> str:
    """'build an application that tracks prices…' → 'Tracks Prices…', not 'Build An Applicati'."""
    import re
    p = re.sub(r"^(?:please\s+)?(?:build|create|make|design)\s+(?:me\s+)?(?:an?\s+)?"
               r"(?:(?:application|app|tool|widget|dashboard|page)\b)?\s*(?:(?:that|which|to|for)\b)?\s*",
               "", (prompt or "").strip(), flags=re.IGNORECASE).strip()
    p = (p or prompt or "App").strip()
    words, out = p.split(), ""
    for w in words:  # whole words up to ~30 chars — never cut mid-word
        if len(out) + len(w) + 1 > 30:
            break
        out = (out + " " + w).strip()
    return (out or p[:30]).title()


def _extract_html_from_steps(steps: list) -> str:
    for s in steps:
        if s.get("type") == "tool" and s.get("name") == "create_app":
            h = (s.get("args") or {}).get("html", "")
            if h:
                return h
        if s.get("type") == "text":
            h = _extract_html(s.get("text", ""))
            if h:
                return h
    return ""


BUILDER_PERSONA = """=== APP BUILDER MODE ===
You are the AgentOS App Builder — a senior product designer + front-end engineer who ships polished,
genuinely useful desktop apps. Your ONE job this turn: produce a COMPLETE, working, good-looking app by
calling `create_app(name, icon, description, html)`. If you truly cannot call the tool, output the whole
app as a single ```html fenced block instead. NEVER reply with only a description, a stub, or a TODO.
When refining an existing app, call create_app with the SAME name to update it in place.

BUILD QUALITY — this matters; make it look and feel professional, not a demo:
- Real, finished features. If it's a tracker it adds/edits/deletes/persists; if it's a dashboard it shows
  real data; handle empty states and errors. No dead buttons, no lorem ipsum.
- Design like a modern native app, matching the OS. Use this dark palette exactly:
    page #0e1116 · surface #171b22 · raised #1e242e · border #232a35 · text #e6ebf2 · muted #8a94a6 ·
    accent gradient #5eead4 → #22d3ee (one accent, used sparingly).
  Generous padding (16-20px), 10-14px radii, a clear header/title, comfortable line-height (~1.5),
  hover/focus states on every interactive element, subtle shadows, and a layout that fills the window
  responsively (flex/grid). Crisp and breathable — never cramped or flat. Ship something you're proud of.
- System font stack; restrained micro-interactions. NO external CDNs, fonts, or images (blocked) — inline
  all CSS/JS, embed any assets as data URIs.
- START from this baseline skeleton and build on it — never ship unstyled controls:
    <style>
      :root{--bg:#0e1116;--s:#171b22;--r:#1e242e;--ln:#232a35;--tx:#e6ebf2;--mut:#8a94a6;--acc:#5eead4;--acc2:#22d3ee}
      *{box-sizing:border-box;margin:0}
      body{background:var(--bg);color:var(--tx);font:14px/1.5 system-ui,sans-serif;padding:18px}
      h1{font-size:17px} .sub{color:var(--mut);font-size:12.5px;margin:2px 0 14px}
      .card{background:var(--s);border:1px solid var(--ln);border-radius:12px;padding:14px;margin-bottom:10px}
      input,select{background:var(--r);border:1px solid var(--ln);border-radius:9px;color:var(--tx);padding:9px 11px;font:inherit;width:100%}
      input:focus{outline:none;border-color:var(--acc)}
      button{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#04211c;border:0;border-radius:9px;padding:9px 14px;font-weight:700;cursor:pointer}
      button.ghost{background:none;border:1px solid var(--ln);color:var(--mut)}
      .row{display:flex;gap:8px;align-items:center} .muted{color:var(--mut);font-size:12px}
      .err{color:#f87171} .ok{color:#34d399}
    </style>
  Every async action shows a loading state and a readable error state; every list has an empty state
  telling the user what to do first; numbers/dates are formatted, not raw.
- JS CORRECTNESS (the #1 way apps die): a plain <script> cannot use top-level `await` — wrap ALL
  startup logic in `(async () => { … })();` and call appData/appTool/appLLM only inside async
  functions. Attach handlers with addEventListener or onclick attributes that call DEFINED functions;
  test mentally that every referenced element id exists. A syntax error kills the entire app.

DATA — every app has its OWN data store (its "MCP"), pre-injected as page globals:
- `await appData.get()` returns the app's saved object; `await appData.set(obj)` saves it. USE THIS for
  anything the user creates so it survives reloads AND the agent can read it later. Prefer it to localStorage.
- `await appTool(name, args)` runs ANY OS/MCP tool from the app and returns {output} — the way to pull
  LIVE data, e.g. appTool('fetch_url',{url:…}), appTool('system_info'), appTool('run_command',{command:…}),
  or a connected mcp_* tool.
- `await appLLM(prompt, system?)` runs the OS's language model INSIDE the app (one-shot, returns text).
  This is how apps get AI features: summarize what they fetched, classify or rewrite entries, and —
  critically — EXTRACT data from messy pages instead of brittle regex: after appTool('fetch_url',…),
  call appLLM(pageText, 'Reply with ONLY JSON {"price": number|null, "currency": string}') and
  JSON.parse the reply inside try/catch. Prefer appLLM over hand-written parsers for anything scraped.
- Apps may poll (setInterval) or open ws://{location.host}/ws for realtime.
- THE FULL API REGISTRY of this OS is appended below (also live at GET /api/registry). Anything listed
  there is fair game — your app can drive the whole OS: chat, files, models, tasks, themes, workflows.
  The user's interface wishes are the spec; the registry is what makes them possible.

ALERTS & CHANNELS — bake delivery in; the user should not have to keep the window open:
- appTool('notify',{title,message}) shows a desktop notification; appTool('telegram_send',{message})
  reaches the user's phone when Telegram is paired (configured channels are listed in the registry).
- For anything the user wants tracked/monitored, ALSO wire background checking:
  appTool('schedule_task',{prompt:'check <thing>; if <condition>, send the user a telegram_send alert',
  schedule_type:'interval', interval_minutes:N}) — this keeps working with the app closed.
- Give such apps a small "Alerts" card in the UI: a threshold/condition input and an on/off toggle that
  creates or removes the scheduled task, and show when the last check ran.

PERMISSIONS — declare what the app needs:
- Pass `permissions` to create_app: a JSON list of {action, resource, reason, required} covering every
  appTool/appData/API capability the app uses (actions: tool.use, mcp.use, skill.use, net.fetch, fs.read,
  fs.write, memory.read, agent.invoke, app.data.*). The user consents to exactly this list at install;
  anything undeclared prompts them at runtime. Keep it minimal and honest — reasons are shown verbatim.

PROCESS — work like a product team in one turn:
1. SPEC. Silently expand the request into concrete features, a data model, and data sources — fill the
   obvious gaps yourself. e.g. "track prices of a product" implies: add/remove products (name + URL),
   fetch the current price with appTool('fetch_url', …) using resilient parsing, keep a price HISTORY in
   appData, show last-checked time and change vs. last check, a Refresh button, and refresh-on-open.
   A one-line request still deserves the complete, obvious app around it.
2. GROUND. If the app depends on live data, an API, or a specific tool, call the matching read-only tool
   FIRST (fetch_url on the real page/API, system_info, list_dir) to learn the actual response shape —
   never write parsing code against a guessed format. One or two grounding calls, then build.
3. BUILD. Call create_app with the complete app. Leave `icon` empty (the OS renders a clean monogram
   tile — the user dislikes emoji icons) and pick a concise name. Wrap every appTool call in try/catch
   and show a readable error state in the UI when a tool fails or returns something unexpected.
4. FIX. If an automated check or a tool error reports problems with what you built, call create_app
   again with the SAME name and the corrected HTML — don't apologize, just fix it.
- If the user wants it pinned / on the desktop / as a widget, call pin_widget(name) after create_app.
- Do the work in THIS turn — never ask questions. Finish with one short sentence on what you built.
"""


def _lint_app_html(html: str, toolbox=None) -> list[str]:
    """Static checks on a built app: things that WILL break at runtime."""
    import re
    issues = []
    for m in re.finditer(r"<(?:script|link|img|iframe)\b[^>]*?(?:src|href)\s*=\s*[\"'](https?://[^\"']+)",
                         html, re.IGNORECASE):
        issues.append(f"external asset will be blocked at runtime: {m.group(1)[:120]} — "
                      "inline the code/style or embed the asset as a data: URI")
    if toolbox is not None:
        try:
            known = {t["name"] for t in toolbox.schemas()}
        except Exception:
            known = set()
        if known:
            for m in re.finditer(r"appTool\(\s*['\"]([\w.-]+)['\"]", html):
                if m.group(1) not in known:
                    issues.append(f"appTool('{m.group(1)}') calls a tool that does not exist — "
                                  "use a name from the API registry")
    return issues[:6]


# ---- Approval broker (global): any surface can ask the user and await Allow/Deny ----

async def request_approval(name: str, args: dict, reason: str, offer: dict | None = None,
                           evsend=None, ws=None) -> bool:
    """Raise an approval card and wait for the user's answer. `offer` is a ready-to-write
    grant: when the user picks "allow & remember", it is persisted before resolving True.
    evsend routes the card to one chat's client; otherwise it broadcasts to every client."""
    aid = uuid.uuid4().hex[:8]
    fut = asyncio.get_event_loop().create_future()
    state["pending_approvals"][aid] = {"fut": fut, "offer": offer, "ws": ws}
    ev = {"type": "approval_request", "id": aid, "name": name, "args": args,
          "reason": reason, "offer": offer}
    if evsend is not None:
        await evsend(ev)
    else:
        await state["broadcast"](ev)
    try:
        return await asyncio.wait_for(fut, timeout=300)
    except asyncio.TimeoutError:
        return False
    finally:
        state["pending_approvals"].pop(aid, None)


async def resolve_approval(aid: str, approved: bool, remember: bool = False):
    entry = state["pending_approvals"].get(aid)
    if not entry or entry["fut"].done():
        return
    if approved and remember and entry.get("offer"):
        o = entry["offer"]
        state["store"].add_grant(o["principal_kind"], o["principal_id"], o["action"],
                                 o["resource"], source="user",
                                 note="allowed & remembered from an approval prompt")
        state["store"].log("policy", f"grant remembered: {o['action']} {o['resource']}",
                           {"principal": f"{o['principal_kind']}:{o['principal_id']}",
                            "action": o["action"], "resource": o["resource"],
                            "effect": "allow", "via": "approval_prompt"})
        await state["broadcast"]({"type": "grants"})
    entry["fut"].set_result(bool(approved))


# ---- App privilege guard: apps may never reconfigure the OS over plain REST ------

# method + path-prefix pairs an app-originated request is never allowed to hit;
# capability access goes through /api/tool + grants, never around them
SENSITIVE_FOR_APPS = (
    ("PUT", "/api/config"), ("PUT", "/api/mcp"), ("PUT", "/api/soul"),
    ("POST", "/api/apps"), ("DELETE", "/api/apps"),
    ("POST", "/api/grants"), ("DELETE", "/api/grants"),
    ("POST", "/api/snapshots"), ("DELETE", "/api/snapshots"),
    ("PUT", "/api/telegram"), ("PUT", "/api/widgets"), ("POST", "/api/skills"),
    ("DELETE", "/api/skills"), ("POST", "/api/factory-reset"),
)


@app.middleware("http")
async def app_privilege_guard(request: Request, call_next):
    tok = request.headers.get("x-app-token", "")
    ref = request.headers.get("referer", "")
    from_app = (tok and tok in state.get("app_tokens", {})) or \
               ("/api/apps/" in ref and ref.rstrip("/").endswith("/page"))
    if from_app:
        path, method = request.url.path, request.method
        # an app's own data/manifest endpoints stay reachable (gated above/below)
        own_surface = path.startswith("/api/apps/") and path.endswith(("/data", "/page"))
        if not own_surface:
            for m, p in SENSITIVE_FOR_APPS:
                if method == m and path.startswith(p):
                    state["store"].log("system", f"app blocked from {method} {path}",
                                       {"via": "privilege_guard"})
                    return JSONResponse(
                        {"error": "denied: apps cannot change OS configuration — "
                                  "capabilities go through appTool() and the permission grants"},
                        status_code=403)
    return await call_next(request)


# ---- Run a single tool (for AI-built apps to reach the OS / MCP) -----------------

def _principal_of(request) -> Principal:
    """Map a request to its principal: an app runtime token (X-App-Token, minted when the
    app page is served) makes it that app; anything else acts as the user."""
    tok = request.headers.get("x-app-token", "") if request is not None else ""
    entry = state["app_tokens"].get(tok) if tok else None
    return Principal("app", entry["app_id"]) if entry else MAIN


@app.post("/api/tool")
async def api_run_tool(body: dict, request: Request):
    """Let a user-built app invoke an agent or MCP tool and get its output. Every call
    flows through the policy gate; an ungranted call raises an approval card with
    "allow & remember" instead of failing flat."""
    name = body.get("name", "")
    args = body.get("args") or {}
    toolbox = state["toolbox"]
    principal = _principal_of(request)
    if name not in {t["name"] for t in toolbox.schemas()}:
        return JSONResponse({"error": f"unknown tool: {name}"}, status_code=400)
    level, reason = toolbox.risk_of(name, args)
    dec = state["pdp"].decide_tool(principal, name, args, level, reason=reason,
                                   autonomy=state["cfg"].get("autonomy", ""))

    def _plog(outcome: str, approved=None):
        state["store"].log("policy",
                           f"{outcome}: {principal.label} → {dec.action} {dec.resource}"[:400],
                           {"principal": principal.label, "action": dec.action,
                            "resource": dec.resource, "effect": dec.effect, "rule": dec.rule,
                            "reason": dec.reason or reason, "tool": name,
                            "approved": approved, "via": "api_tool"})
    if dec.effect == "deny":
        _plog("deny")
        return JSONResponse({"error": f"denied: {dec.reason or reason}"}, status_code=403)
    if dec.effect == "ask":
        if not state["clients"]:  # headless: nobody to ask
            _plog("ask", approved=False)
            return JSONResponse({"error": f"needs approval: {dec.reason or reason}"},
                                status_code=403)
        approved = await request_approval(name, args, dec.reason or reason,
                                          offer=dec.grant_offer)
        _plog("ask", approved=bool(approved))
        if not approved:
            return JSONResponse({"error": f"not approved: {dec.reason or reason}"},
                                status_code=403)
    out = await toolbox.execute(name, args)
    state["store"].log("tool", f"app→{name}",
                       {"args": args, "via": "user_app", "principal": principal.label,
                        "app_id": principal.id if principal.kind == "app" else "",
                        "decision": dec.rule})
    return {"output": out}


# ---- Grants: the consent ledger of the permission framework ---------------------

@app.get("/api/grants")
async def api_grants(kind: str = "", pid: str = "", all: int = 0):
    """Permission grants: who (app/subagent) may do what. Written by manifest approval,
    "allow & remember" prompts, or the Permissions app — revocable there any time."""
    return {"grants": state["store"].list_grants(kind, pid, include_revoked=bool(all))}


@app.post("/api/grants")
async def api_add_grant(body: dict):
    kind, action = (body.get("principal_kind") or "").strip(), (body.get("action") or "").strip()
    if not kind or not action:
        return JSONResponse({"error": "principal_kind and action are required"}, status_code=400)
    pid = (body.get("principal_id") or "").strip()
    resource = (body.get("resource") or "*").strip()
    effect = body.get("effect", "allow")
    gid = state["store"].add_grant(kind, pid, action, resource, effect=effect,
                                   source="user", note=body.get("note", ""))
    state["store"].log("policy", f"grant attached: {effect} {kind}:{pid} → {action} {resource}",
                       {"principal": f"{kind}:{pid}", "action": action, "resource": resource,
                        "effect": effect, "via": "permissions_ui"})
    await state["broadcast"]({"type": "grants"})
    return {"id": gid}


@app.put("/api/grants/{gid}")
async def api_update_grant(gid: str, body: dict):
    """Toggle a grant's effect between allow and deny (the policy map click-toggle)."""
    effect = (body.get("effect") or "").strip()
    ok = state["store"].update_grant(gid, effect)
    if ok:
        state["store"].log("policy", f"grant toggled to {effect}: {gid}",
                           {"grant_id": gid, "effect": effect, "via": "permissions_ui"})
        await state["broadcast"]({"type": "grants", "revoked": effect == "deny"})
    return {"ok": ok}


@app.delete("/api/grants/{gid}")
async def api_revoke_grant(gid: str):
    ok = state["store"].revoke_grant(gid)
    if ok:
        state["store"].log("policy", f"grant revoked: {gid}",
                           {"grant_id": gid, "via": "permissions_ui"})
        await state["broadcast"]({"type": "grants", "revoked": True})
    return {"ok": ok}


@app.get("/api/policy/options")
async def api_policy_options():
    """Everything the Permissions composer can pick from: principals (apps, subagents,
    workflows), actions, and real resources (tools, MCP, skills, models, agents) — so
    rules are attached by selection, never typed blind."""
    store, cfg, toolbox = state["store"], state["cfg"], state["toolbox"]
    principals = (
        [{"kind": "app", "id": a["id"], "label": a["name"],
          "status": a.get("manifest_status") or "none"} for a in store.list_apps()]
        + [{"kind": "subagent", "id": s["name"], "label": s["name"]}
           for s in store.list_subagents()]
        + [{"kind": "workflow", "id": w["name"], "label": w["name"]}
           for w in store.list_workflows()])
    tools = sorted(t["name"] for t in toolbox.schemas() if not t["name"].startswith("mcp_"))
    mcp_res = []
    for s in (state["mcp"].status() if state.get("mcp") else []):
        mcp_res.append({"value": f"mcp:{s['name']}/*", "label": f"{s['name']} — all tools"})
        for t in (s.get("tools") or [])[:40]:
            tn = t["name"] if isinstance(t, dict) else t
            mcp_res.append({"value": f"mcp:{s['name']}/{tn}", "label": f"{s['name']} / {tn}"})
    for name in (cfg.get("mcp_servers") or {}):
        v = f"mcp:{name}/*"
        if not any(m["value"] == v for m in mcp_res):
            mcp_res.append({"value": v, "label": f"{name} — all tools (not connected)"})
    try:
        models = [m["id"] for m in await providers.available_models(cfg)]
    except Exception:
        models = [cfg.get("default_model", "")]
    ws = cfg.get("workspace", "")
    return {"principals": principals,
            "actions": ["tool.use", "mcp.use", "skill.use", "model.use", "net.fetch",
                        "fs.read", "fs.write", "memory.read", "memory.write",
                        "kg.read", "kg.write", "agent.invoke",
                        "app.data.read", "app.data.write", "*"],
            "resources": {
                "tool.use": [{"value": f"tool:{t}*", "label": t} for t in tools],
                "mcp.use": mcp_res,
                "skill.use": [{"value": f"skill:{s['name']}", "label": s["name"]}
                              for s in store.list_skills()],
                "model.use": [{"value": f"model:{m}", "label": m} for m in models if m],
                "agent.invoke": ([{"value": "agent:main", "label": "main agent (/api/chat)"}]
                                 + [{"value": f"agent:subagent/{s['name']}", "label": f"subagent {s['name']}"}
                                    for s in store.list_subagents()]
                                 + [{"value": f"agent:workflow/{w['name']}", "label": f"workflow {w['name']}"}
                                    for w in store.list_workflows()]),
                "net.fetch": [{"value": "net:*", "label": "any URL"},
                              {"value": "net:https://*", "label": "any https URL"}],
                "fs.read": [{"value": f"fs:{ws}/*", "label": "workspace files"},
                            {"value": "fs:*", "label": "any path (sandbox still applies)"}],
                "fs.write": [{"value": f"fs:{ws}/*", "label": "workspace files"},
                             {"value": "fs:*", "label": "any path (sandbox still applies)"}],
                "memory.read": [{"value": "memory:*", "label": "all memory scopes"}],
                "memory.write": [{"value": "memory:*", "label": "all memory scopes"}],
                "kg.read": [{"value": "kg:*", "label": "knowledge graph"}],
                "kg.write": [{"value": "kg:*", "label": "knowledge graph"}],
                "app.data.read": [{"value": f"app:{a['id']}/data", "label": f"data of {a['name']}"}
                                  for a in store.list_apps()],
                "app.data.write": [{"value": f"app:{a['id']}/data", "label": f"data of {a['name']}"}
                                   for a in store.list_apps()],
                "*": [{"value": "*", "label": "everything (full access)"}],
            }}


@app.get("/api/tools")
async def api_list_tools():
    """The tool names an app (or user) can call via /api/tool, incl. connected MCP tools."""
    return {"tools": [{"name": t["name"], "description": t["description"]}
                      for t in state["toolbox"].schemas()]}


# ---- API registry: the UI-builder's contract ---------------------------------

WS_EVENTS = {
    "outbound (server → client)": [
        "text_delta {text}", "thinking_delta {text}", "tool_start {call_id,name,args}",
        "tool_end {call_id,ok,output}", "approval_request {id,name,args,reason,offer?}",
        "turn_start / turn_end {conversation_id}", "error {message}",
        "apps / themes / widgets / wallpaper / models / files / config / grants  (refresh hints)",
        "theme_apply {theme}", "model_pull {name,status,done}", "fabric_event / fabric_defs",
        "telegram_in / telegram_out {conversation_id,text}", "knowledge_update",
    ],
    "inbound (client → server)": [
        "chat {text, conversation_id?, model?}", "build {prompt, app_id?, model?}",
        "approval {id, approved, remember?}", "abort {}",
    ],
}

APP_RUNTIME_GLOBALS = {
    "APP_ID": "the app's own id (string), injected into every built app page",
    "APP_TOKEN": "the app's runtime identity — appTool/appData send it as X-App-Token so "
                 "the permission gate knows WHO is calling",
    "appData.get() / appData.set(obj)": "the app's private persistent JSON store, server-side",
    "appTool(name, args)": "run any agent/MCP tool listed under `tools` and get its output; "
                           "ungranted calls raise a consent prompt for the user",
}


def _registry() -> dict:
    """Enumerate every REST/WS endpoint and agent tool — the contract a UI builder codes against."""
    from fastapi.routing import APIRoute, APIWebSocketRoute
    routes = []
    for r in app.routes:
        doc = (getattr(getattr(r, "endpoint", None), "__doc__", "") or "").strip()
        doc = doc.split("\n\n")[0].replace("\n", " ").strip()
        if isinstance(r, APIRoute):
            for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                routes.append({"method": m, "path": r.path, "summary": doc})
        elif isinstance(r, APIWebSocketRoute):
            routes.append({"method": "WS", "path": r.path, "summary": doc})
    routes.sort(key=lambda x: (x["path"], x["method"]))
    tools = [{"name": t["name"], "description": (t["description"] or "").split(". ")[0][:160]}
             for t in state["toolbox"].schemas()]
    return {"routes": routes, "tools": tools, "websocket_events": WS_EVENTS,
            "app_runtime_globals": APP_RUNTIME_GLOBALS,
            "notes": ["All endpoints are same-origin — plain fetch() works from any app/shell/theme.",
                      "Realtime: open a WebSocket to /ws (JSON events) or /ws/terminal (PTY).",
                      "POST /api/tool {name,args} runs a tool. Calls from apps are permission-"
                      "gated per app: granted → runs; ungranted → the user gets a consent "
                      "prompt (grants are managed in the Permissions app).",
                      "Apps cannot change OS configuration over REST (PUT /api/config, "
                      "/api/mcp, …) — capabilities flow through appTool() and grants."]}


def _registry_text(max_tools: int = 48) -> str:
    """Compact, prompt-friendly rendering of the registry for builder/designer personas."""
    reg = _registry()
    lines = ["REST + WS endpoints (method path — what it does):"]
    for r in reg["routes"]:
        s = f"  {r['method']:<6} {r['path']}"
        if r["summary"]:
            s += f" — {r['summary'][:90]}"
        lines.append(s)
    lines.append("Realtime /ws events out: " + "; ".join(reg["websocket_events"]["outbound (server → client)"][:6]) + " …")
    lines.append("Realtime /ws events in: " + "; ".join(reg["websocket_events"]["inbound (client → server)"]))
    tools = reg["tools"]
    lines.append(f"Tools callable via POST /api/tool or appTool() ({len(tools)} total): "
                 + ", ".join(t["name"] for t in tools[:max_tools])
                 + (" …" if len(tools) > max_tools else ""))
    return "\n".join(lines)


@app.get("/api/registry")
async def api_registry():
    """The full API registry: every REST/WS endpoint, agent tool, realtime event and injected page
    global a UI builder can use — the contract for AI-designed apps, themes and shells. An interface
    built against it can completely replace the stock UI."""
    return _registry()


# ---- Snapshots (restore points) --------------------------------------------------

def _snap_dir():
    d = cfgmod.AGENTOS_HOME / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


@app.get("/api/snapshots")
async def api_snapshots():
    import json as _j
    out = []
    for d in sorted(_snap_dir().iterdir(), reverse=True) if _snap_dir().exists() else []:
        if not d.is_dir():
            continue
        meta = {}
        mp = d / "meta.json"
        if mp.exists():
            try:
                meta = _j.loads(mp.read_text())
            except Exception:
                pass
        out.append({"id": d.name, "label": meta.get("label", ""), "created_at": meta.get("created_at", 0),
                    "has_source": (d / "agentos").exists()})
    return {"snapshots": out}


@app.post("/api/snapshots")
async def api_snapshot_create(body: dict):
    import json as _j
    import shutil
    import time as _t
    sid = str(int(_t.time()))
    d = _snap_dir() / sid
    d.mkdir(parents=True, exist_ok=True)
    home = cfgmod.AGENTOS_HOME
    for f in ("config.json", "soul.md", "agentos.db"):
        if (home / f).exists():
            shutil.copy2(home / f, d / f)
    # copy the AgentOS source (python only) so self-modifications can be rolled back
    src = Path(__file__).resolve().parent
    shutil.copytree(src, d / "agentos",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (d / "meta.json").write_text(_j.dumps({"label": body.get("label", ""), "created_at": _t.time()}))
    state["store"].log("system", f"snapshot created: {sid} {body.get('label','')}")
    return {"ok": True, "id": sid}


@app.post("/api/snapshots/{sid}/restore")
async def api_snapshot_restore(sid: str):
    import shutil
    d = _snap_dir() / sid
    if not d.is_dir():
        return JSONResponse({"error": "not found"}, status_code=404)
    home = cfgmod.AGENTOS_HOME
    for f in ("config.json", "soul.md", "agentos.db"):
        if (d / f).exists():
            shutil.copy2(d / f, home / f)
    src = Path(__file__).resolve().parent
    if (d / "agentos").exists():
        for py in (d / "agentos").glob("*.py"):
            shutil.copy2(py, src / py.name)
    state["store"].log("system", f"snapshot restored: {sid} — restarting")
    from . import desktop as desktopmod
    desktopmod.restart_service()
    return {"ok": True, "restarting": True}


@app.delete("/api/snapshots/{sid}")
async def api_snapshot_delete(sid: str):
    import shutil
    d = _snap_dir() / sid
    if d.is_dir():
        shutil.rmtree(d)
    return {"ok": True}


# ---- Skills ----------------------------------------------------------------------

def _parse_skill_md(text: str, fallback_name: str) -> tuple[str, str, str]:
    """(name, description, content) from a markdown skill file.
    Understands the standard SKILL.md YAML frontmatter (name:/description:, incl.
    folded multi-line values); otherwise first '# heading' is the name and the
    first plain line the description."""
    name, desc = fallback_name, ""
    body = text
    stripped = text.lstrip()
    if stripped.startswith("---"):
        end = stripped.find("\n---", 3)
        if end != -1:
            lines = stripped[3:end].splitlines()
            body = stripped[end + 4:]
            i = 0
            while i < len(lines):
                line = lines[i]
                if ":" in line and not line.startswith((" ", "\t")):
                    k, v = line.split(":", 1)
                    k, v = k.strip().lower(), v.strip().strip("\"'")
                    if v in (">", ">-", "|", "|-"):  # folded/literal block: gather indented lines
                        parts = []
                        while i + 1 < len(lines) and lines[i + 1].startswith((" ", "\t")):
                            i += 1
                            parts.append(lines[i].strip())
                        v = " ".join(parts)
                    if k == "name" and v:
                        name = v
                    elif k == "description" and v:
                        desc = v[:200]
                i += 1
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            if name == fallback_name:
                name = s.lstrip("# ").strip() or fallback_name
            continue
        if not desc:
            desc = s.lstrip("> ").strip()[:200]
        break
    return name, desc, text


@app.get("/api/skills")
async def api_skills():
    return {"skills": state["store"].list_skills()}


@app.post("/api/skills")
async def api_save_skill(body: dict):
    sid = state["store"].save_skill(body.get("name", ""), body.get("description", ""),
                                    body.get("content", ""))
    return {"id": sid}


@app.delete("/api/skills/{sid}")
async def api_delete_skill(sid: str):
    state["store"].delete_skill(sid)
    return {"ok": True}


@app.post("/api/skills/install")
async def api_install_skill(body: dict):
    """Install skills from a raw .md URL or a git repo (scans *.md files)."""
    import tempfile

    import httpx
    src = (body.get("source") or "").strip()
    store = state["store"]
    if not src:
        return {"ok": False, "error": "no source given"}
    try:
        if src.endswith(".md") or "raw.githubusercontent.com" in src:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                r = await client.get(src)
            if r.status_code != 200:
                return {"ok": False, "error": f"HTTP {r.status_code}"}
            fallback = src.rsplit("/", 1)[-1].removesuffix(".md")
            name, desc, content = _parse_skill_md(r.text, fallback)
            store.save_skill(name, desc, content, source=src)
            store.log("system", f"skill installed from URL: {name}")
            return {"ok": True, "count": 1}
        # treat as a git repo
        with tempfile.TemporaryDirectory() as tmp:
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", "--depth", "1", src, tmp,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            _, err = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode != 0:
                return {"ok": False, "error": f"git clone failed: {err.decode(errors='replace')[-300:]}"}
            count = 0
            files = sorted(Path(tmp).rglob("*.md"))
            # standard skill repos keep one SKILL.md per folder — when present,
            # install only those (skipping references, docs, templates, ...)
            skill_files = [p for p in files if p.name == "SKILL.md"]
            if skill_files:
                files = skill_files
            for p in files:
                if p.name.upper() in ("README.MD", "LICENSE.MD", "CONTRIBUTING.MD", "CHANGELOG.MD"):
                    continue
                try:
                    text = p.read_text(errors="replace")
                except Exception:
                    continue
                if len(text.strip()) < 20 or len(text) > 100_000:
                    continue
                fallback = p.parent.name if p.name == "SKILL.md" else p.stem
                name, desc, content = _parse_skill_md(text, fallback)
                store.save_skill(name, desc, content, source=src)
                count += 1
                if count >= 50:
                    break
            store.log("system", f"{count} skill(s) installed from {src}")
            return {"ok": count > 0, "count": count,
                    "error": "" if count else "no skill .md files found in the repo"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ---- Wallpaper ------------------------------------------------------------------

@app.get("/api/wallpaper")
async def api_wallpaper():
    p = cfgmod.AGENTOS_HOME / "wallpaper.png"
    if p.exists():
        return FileResponse(p, media_type="image/png",
                            headers={"Cache-Control": "no-store"})
    return JSONResponse({"exists": False}, status_code=404)


@app.post("/api/wallpaper/generate")
async def api_wallpaper_generate(body: dict):
    result = await state["toolbox"].generate_wallpaper(body.get("prompt", ""))
    return {"ok": not result.startswith("[error]"), "result": result}


_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".heic", ".tif", ".tiff", ".webp", ".gif", ".bmp")


def _mac_wallpaper_file() -> Path | None:
    """Current macOS wallpaper via AppleScript, the macOS 14+ wallpaper store, or the
    pre-Sonoma Dock database — whichever this system exposes."""
    import plistlib
    import sqlite3
    import subprocess
    import urllib.parse
    # 1) AppleScript (most accurate, but needs the Automation permission and fails for
    #    some dynamic wallpapers on macOS 14+)
    for script in ('tell application "System Events" to get picture of current desktop',
                   'tell application "Finder" to get POSIX path of (get desktop picture as alias)'):
        try:
            r = subprocess.run(["osascript", "-e", script],
                               capture_output=True, text=True, timeout=10)
            p = Path(r.stdout.strip()).expanduser()
            if r.returncode == 0 and r.stdout.strip() and p.is_file():
                return p
        except Exception:
            pass
    # 2) macOS 14+ (Sonoma/Sequoia) wallpaper store — plain file read, no permissions.
    #    File URLs are nested inside base64-embedded binary plists; walk everything.
    idx = Path.home() / "Library/Application Support/com.apple.wallpaper/Store/Index.plist"
    if idx.is_file():
        try:
            urls: list[str] = []

            def walk(node):
                if isinstance(node, dict):
                    for v in node.values():
                        walk(v)
                elif isinstance(node, list):
                    for v in node:
                        walk(v)
                elif isinstance(node, str) and node.startswith("file://"):
                    urls.append(node)
                elif isinstance(node, bytes):
                    try:
                        walk(plistlib.loads(node))
                    except Exception:
                        pass

            walk(plistlib.loads(idx.read_bytes()))
            for u in urls:
                p = Path(urllib.parse.unquote(u[len("file://"):]))
                if p.is_file() and p.suffix.lower() in _IMAGE_EXTS:
                    return p
        except Exception:
            pass
    # 3) pre-Sonoma Dock database
    db = Path.home() / "Library/Application Support/Dock/desktoppicture.db"
    if db.is_file():
        try:
            rows = sqlite3.connect(str(db)).execute("select value from data").fetchall()
            for (v,) in reversed(rows):
                if isinstance(v, str):
                    p = Path(v).expanduser()
                    if p.is_file() and p.suffix.lower() in _IMAGE_EXTS:
                        return p
        except Exception:
            pass
    return None


def _host_wallpaper_file() -> Path | None:
    """Path of the host OS desktop wallpaper (macOS / Windows / Linux), or None."""
    import os
    import shutil as _sh
    import subprocess
    import sys as _sys
    import urllib.parse
    if _sys.platform == "darwin":
        return _mac_wallpaper_file()
    if _sys.platform.startswith("win"):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as k:
                p = Path(winreg.QueryValueEx(k, "WallPaper")[0])
            if p.is_file():
                return p
        except OSError:
            pass
        p = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Themes/TranscodedWallpaper"
        return p if p.is_file() else None
    # Linux: GNOME / Cinnamon / MATE expose it via gsettings
    if _sh.which("gsettings"):
        for schema, key in (("org.gnome.desktop.background", "picture-uri-dark"),
                            ("org.gnome.desktop.background", "picture-uri"),
                            ("org.cinnamon.desktop.background", "picture-uri"),
                            ("org.mate.background", "picture-filename")):
            r = subprocess.run(["gsettings", "get", schema, key],
                               capture_output=True, text=True, timeout=5)
            uri = r.stdout.strip().strip("'")
            if r.returncode == 0 and uri:
                p = Path(urllib.parse.unquote(uri.removeprefix("file://")))
                if p.is_file():
                    return p
    return None


@app.post("/api/wallpaper/system")
async def api_wallpaper_system():
    """Adopt the host OS desktop wallpaper as the AgentOS wallpaper."""
    import shutil
    import subprocess
    import sys as _sys
    try:
        path = _host_wallpaper_file()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    if path is None:
        msg = "could not read the system wallpaper on this desktop"
        if _sys.platform == "darwin":
            msg += (" — if you just denied an Automation prompt, allow it in System Settings → "
                    "Privacy & Security → Automation, or set a static image as your wallpaper")
        return JSONResponse({"error": msg}, status_code=404)
    dest = cfgmod.AGENTOS_HOME / "wallpaper.png"
    # browsers can't render HEIC/TIFF (Apple's default wallpapers) — convert via sips
    if _sys.platform == "darwin" and path.suffix.lower() in (".heic", ".tif", ".tiff", ".bmp"):
        r = subprocess.run(["sips", "-s", "format", "png", str(path), "--out", str(dest)],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return JSONResponse({"error": f"could not convert {path.suffix} wallpaper: "
                                          f"{(r.stderr or r.stdout).strip()}"}, status_code=500)
    else:
        shutil.copy2(path, dest)
    await state["broadcast"]({"type": "wallpaper"})
    return {"ok": True, "source": str(path)}


@app.get("/api/wallpapers")
async def api_wallpapers():
    d = cfgmod.AGENTOS_HOME / "wallpapers"
    ids = sorted((p.stem for p in d.glob("*.png")), reverse=True) if d.exists() else []
    return {"wallpapers": ids}


@app.get("/api/wallpapers/{wid}")
async def api_wallpaper_file(wid: str):
    p = (cfgmod.AGENTOS_HOME / "wallpapers" / f"{wid}.png")
    if not p.is_file() or ".." in wid or "/" in wid:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(p, media_type="image/png")


@app.post("/api/wallpapers/{wid}/set")
async def api_wallpaper_set(wid: str):
    p = (cfgmod.AGENTOS_HOME / "wallpapers" / f"{wid}.png")
    if not p.is_file() or ".." in wid or "/" in wid:
        return JSONResponse({"error": "not found"}, status_code=404)
    (cfgmod.AGENTOS_HOME / "wallpaper.png").write_bytes(p.read_bytes())
    await state["broadcast"]({"type": "wallpaper"})
    return {"ok": True}


@app.delete("/api/wallpapers/{wid}")
async def api_wallpaper_delete(wid: str):
    p = (cfgmod.AGENTOS_HOME / "wallpapers" / f"{wid}.png")
    if p.is_file() and ".." not in wid and "/" not in wid:
        p.unlink()
    return {"ok": True}


@app.delete("/api/wallpaper")
async def api_wallpaper_reset():
    (cfgmod.AGENTOS_HOME / "wallpaper.png").unlink(missing_ok=True)
    await state["broadcast"]({"type": "wallpaper"})
    return {"ok": True}


# ---- Soul ---------------------------------------------------------------------

@app.get("/api/soul")
async def api_soul():
    return {"content": cfgmod.load_soul()}


@app.put("/api/soul")
async def api_put_soul(body: dict):
    cfgmod.save_soul(body.get("content", ""))
    state["store"].log("system", "soul updated via UI")
    return {"ok": True}


@app.get("/api/memories")
async def api_memories(scope: str = "", conversation_id: str = "", q: str = ""):
    store = state["store"]
    mems = store.search_memories(q, limit=500, scope=scope, conversation_id=conversation_id)
    titles = {c["id"]: c["title"] for c in store.list_conversations(limit=1000)}
    for m in mems:
        m["conversation_title"] = titles.get(m.get("conversation_id") or "", "")
        m["embedded"] = bool(m.pop("embedding", None))  # vectors are internal; ship a flag only
    return {"memories": mems}


@app.post("/api/memories")
async def api_add_memory(body: dict):
    mid = state["store"].add_memory(
        body.get("content", ""),
        scope=body.get("scope", "user"),
        conversation_id=body.get("conversation_id") or None,
        source="ui",
        pinned=1 if body.get("pinned") else 0,
    )
    return {"id": mid}


@app.put("/api/memories/{mid}")
async def api_update_memory(mid: str, body: dict):
    """Edit content, toggle pin, or change scope (scope='user' promotes a session memory)."""
    state["store"].update_memory(
        mid,
        content=body.get("content") if "content" in body else None,
        pinned=body.get("pinned") if "pinned" in body else None,
        scope=body.get("scope") if "scope" in body else None,
    )
    return {"ok": True}


@app.delete("/api/memories/{mid}")
async def api_delete_memory(mid: str):
    state["store"].delete_memory(mid)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Docs (served into the UI/TUI) + first-run setup wizard
# ---------------------------------------------------------------------------

def _docs_dir() -> Path | None:
    for cand in (Path(__file__).parent / "docs",          # packaged wheel
                 Path(__file__).parent.parent / "docs"):  # repo checkout
        if cand.is_dir():
            return cand
    return None


@app.get("/api/docs")
async def api_docs():
    base = _docs_dir()
    if not base:
        return {"docs": []}
    out = []
    for p in sorted(base.glob("**/*.md")):
        rel = str(p.relative_to(base))
        try:
            first = next((ln for ln in p.read_text().splitlines() if ln.startswith("#")), rel)
        except Exception:
            first = rel
        out.append({"file": rel, "title": first.lstrip("# ").strip()})
    order = ["README.md", "getting-started.md", "installation.md", "lifecycle.md",
             "desktop.md", "agent.md", "building-apps.md", "training.md", "git.md",
             "tui.md", "security.md", "integrations.md", "models.md", "configuration.md",
             "api-reference.md", "architecture.md", "roadmap.md"]
    out.sort(key=lambda d: order.index(d["file"]) if d["file"] in order else 99)
    return {"docs": out}


@app.get("/api/docs/{name:path}")
async def api_doc(name: str):
    base = _docs_dir()
    if not base:
        return JSONResponse({"error": "docs not found"}, status_code=404)
    p = (base / name).resolve()
    if not str(p).startswith(str(base.resolve())) or p.suffix != ".md" or not p.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"file": name, "content": p.read_text()}


@app.get("/api/setup")
async def api_setup_state():
    cfg = state["cfg"]
    local = await providers.ollama_models(cfg["providers"]["ollama"]["base_url"])
    from . import desktop as desktopmod
    return {
        "first_run": cfgmod.is_first_run(),
        "agent_name": cfg.get("agent_name", "Aria"),
        "autonomy": cfg.get("autonomy", "balanced"),
        "default_model": cfg.get("default_model", ""),
        "ollama_models": local,
        "providers": {p: bool(cfg["providers"][p].get("api_key"))
                      for p in ("anthropic", "openai", "openrouter")},
        "autostart_installed": desktopmod.autostart_installed(),
    }


@app.post("/api/setup")
async def api_setup_apply(body: dict):
    from . import setup as setupmod
    report = setupmod.apply_setup(state["cfg"], body or {})
    state["store"].log("system", "first-run setup completed via wizard", report)
    await state["broadcast"]({"type": "config"})
    return {"ok": True, "report": report}


@app.post("/api/setup/reset")
async def api_setup_reset(body: dict):
    """Factory reset: wipe profile/data, reset config, re-arm the wizard."""
    if not (body or {}).get("confirm"):
        return JSONResponse({"error": "pass {\"confirm\": true}"}, status_code=400)
    from . import setup as setupmod
    setupmod.factory_reset(state["cfg"], state["store"])
    await state["broadcast"]({"type": "setup"})
    return {"ok": True, "first_run": True}


# ---------------------------------------------------------------------------
# Fabric: subagents, workflows, runs, observability (the control plane API)
# ---------------------------------------------------------------------------

@app.get("/api/subagents")
async def api_subagents():
    return {"subagents": state["store"].list_subagents()}


@app.post("/api/subagents")
async def api_save_subagent(body: dict):
    if not (body.get("name") or "").strip():
        return JSONResponse({"error": "name required"}, status_code=400)
    sid = state["store"].save_subagent(body)
    await state["broadcast"]({"type": "fabric_defs"})
    return {"id": sid}


@app.delete("/api/subagents/{sid}")
async def api_delete_subagent(sid: str):
    state["store"].delete_subagent(sid)
    await state["broadcast"]({"type": "fabric_defs"})
    return {"ok": True}


@app.get("/api/workflows")
async def api_workflows():
    return {"workflows": state["store"].list_workflows()}


@app.post("/api/workflows")
async def api_save_workflow(body: dict):
    if not (body.get("name") or "").strip():
        return JSONResponse({"error": "name required"}, status_code=400)
    wid = state["store"].save_workflow(body)
    await state["broadcast"]({"type": "fabric_defs"})
    return {"id": wid}


@app.delete("/api/workflows/{wid}")
async def api_delete_workflow(wid: str):
    state["store"].delete_workflow(wid)
    await state["broadcast"]({"type": "fabric_defs"})
    return {"ok": True}


@app.post("/api/workflows/{name}/run")
async def api_run_workflow(name: str, body: dict):
    wf = state["store"].get_workflow(name)
    if not wf:
        return JSONResponse({"error": f"no workflow '{name}'"}, status_code=404)
    input_text = (body or {}).get("input", "")
    asyncio.create_task(state["fabric"].run_workflow(wf, input_text))
    return {"ok": True, "started": True}


@app.post("/api/subagents/{name}/run")
async def api_run_subagent(name: str, body: dict):
    defn = state["store"].get_subagent(name)
    if not defn:
        return JSONResponse({"error": f"no subagent '{name}'"}, status_code=404)
    asyncio.create_task(state["fabric"].run_subagent(defn, (body or {}).get("task", "")))
    return {"ok": True, "started": True}


@app.get("/api/fabric/runs")
async def api_fabric_runs(limit: int = 60):
    runs = state["store"].fabric_runs(limit=limit)
    return {"runs": runs, "live": state["fabric"].live_instances()}


@app.get("/api/fabric/runs/{rid}")
async def api_fabric_run(rid: str):
    run = state["store"].fabric_run(rid)
    if not run:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"run": run,
            "steps": state["store"].fabric_runs(parent_run=rid),
            "events": state["store"].fabric_events_for(rid)}


@app.post("/api/fabric/runs/{rid}/cancel")
async def api_fabric_cancel(rid: str):
    return {"ok": state["fabric"].cancel(rid)}


@app.get("/api/fabric/observability")
async def api_fabric_observability():
    """Faults / performance / logs per data plane — including the main agent (L0 setup)."""
    store = state["store"]
    runs = store.fabric_runs(limit=500)
    child_runs = [dict(r) for r in store.db.execute(
        "SELECT * FROM fabric_runs WHERE kind='step' ORDER BY started_at DESC LIMIT 500").fetchall()]
    per: dict = {}
    for r in runs + child_runs:
        key = r["ref"] if r["kind"] != "workflow" else f"workflow:{r['ref']}"
        p = per.setdefault(key, {"runs": 0, "ok": 0, "faults": 0, "tokens_in": 0,
                                 "tokens_out": 0, "secs": 0.0})
        p["runs"] += 1
        p["ok"] += 1 if r["status"] == "ok" else 0
        p["faults"] += 1 if r["status"] in ("error", "timeout", "denied") else 0
        p["tokens_in"] += r.get("tokens_in") or 0
        p["tokens_out"] += r.get("tokens_out") or 0
        if r.get("finished_at") and r.get("started_at"):
            p["secs"] += r["finished_at"] - r["started_at"]
    # the main agent — the L0 "current setup" — reports through the same pane (7-day window)
    import time as _t
    week_ago = _t.time() - 7 * 86400
    turns = [L for L in store.list_logs("turn", limit=1000) if L["created_at"] > week_ago]
    n_errors = store.db.execute(
        "SELECT COUNT(*) c FROM logs WHERE kind='error' AND created_at>?", (week_ago,)).fetchone()["c"]
    main = {"runs": len(turns), "faults": n_errors, "tokens_in": 0, "tokens_out": 0,
            "window": "7d"}
    for L in turns:
        try:
            m = json.loads(L.get("meta") or "{}")
            main["tokens_in"] += int(m.get("in", 0) or 0)
            main["tokens_out"] += int(m.get("out", 0) or 0)
        except Exception:
            pass
    faults = [{"ref": r["ref"], "kind": r["kind"], "status": r["status"],
               "fault": r["fault"], "at": r["started_at"]}
              for r in runs + child_runs
              if r["status"] in ("error", "timeout", "denied")][:30]
    return {"main_agent": main, "per_plane": per, "recent_faults": faults,
            "live": state["fabric"].live_instances()}


@app.post("/api/plane/llm")
async def api_plane_llm(body: dict):
    """Model plane: data planes reach LLMs through the control plane's provider config,
    never with their own keys. L0 calls in-process; L1+ will call this over mTLS."""
    model = body.get("model") or state["cfg"].get("default_model", "")
    messages = body.get("messages") or []
    text, calls, usage = [], [], {"input": 0, "output": 0}
    try:
        async for ev in providers.chat(state["cfg"], model, messages, body.get("tools") or []):
            if ev["type"] == "text":
                text.append(ev["text"])
            elif ev["type"] == "tool_call":
                calls.append({"id": ev["id"], "name": ev["name"], "args": ev["args"]})
            elif ev["type"] == "usage":
                usage = {"input": ev.get("input", 0), "output": ev.get("output", 0)}
    except providers.ProviderError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    return {"model": model, "content": "".join(text), "tool_calls": calls, "usage": usage}


@app.post("/api/knowledge/maintain")
async def api_knowledge_maintain():
    """Run knowledge maintenance now: embed memories, roll up idle sessions, dedup the KG."""
    asyncio.create_task(knowledge.run_maintenance(
        state["cfg"], state["store"], state.get("broadcast"), force=True))
    return {"ok": True, "started": True}


@app.get("/api/knowledge/status")
async def api_knowledge_status():
    store, cfg = state["store"], state["cfg"]
    mems = store.search_memories("", limit=10**6)
    g = store.kg_graph()
    emb = await knowledge.embed_model(cfg)
    return {
        "user_memories": sum(1 for m in mems if (m.get("scope") or "user") == "user"),
        "session_memories": sum(1 for m in mems if m.get("scope") == "session"),
        "pinned": sum(1 for m in mems if m.get("pinned")),
        "unembedded": sum(1 for m in mems if not m.get("embedding")),
        "kg_nodes": len(g["nodes"]),
        "kg_edges": len(g["edges"]),
        "embed_model": emb or "",
        "auto_extract": (cfg.get("memory") or {}).get("auto_extract", True),
    }


@app.get("/api/tasks")
async def api_tasks():
    return {"tasks": state["store"].list_tasks()}


@app.post("/api/tasks")
async def api_add_task(body: dict):
    msg = state["scheduler"].create_task(
        body.get("prompt", ""), body.get("schedule_type", "once"),
        int(body.get("interval_minutes") or 0), body.get("at_time", ""),
        int(body.get("delay_minutes") or 0))
    return {"ok": True, "message": msg}


@app.put("/api/tasks/{tid}")
async def api_update_task(tid: str, body: dict):
    fields = {}
    if "enabled" in body:
        fields["enabled"] = 1 if body["enabled"] else 0
    if fields:
        state["store"].update_task(tid, **fields)
    return {"ok": True}


@app.delete("/api/tasks/{tid}")
async def api_delete_task(tid: str):
    state["store"].delete_task(tid)
    return {"ok": True}


@app.post("/api/chat")
async def api_chat(body: dict, request: Request):
    """Headless one-shot chat (for scripts / curl / apps). Autonomy rules still apply;
    calls from an app run AS that app, so its grants gate every tool the turn uses."""
    cfg, store, toolbox = state["cfg"], state["store"], state["toolbox"]
    text = body.get("text", "")
    principal = _principal_of(request)
    if principal.kind == "app":
        dec = state["pdp"].decide(principal, "agent.invoke", "agent:main")
        if dec.effect == "deny":
            state["store"].log("policy", f"deny: {principal.label} → agent.invoke agent:main",
                               {"principal": principal.label, "action": "agent.invoke",
                                "resource": "agent:main", "effect": "deny", "rule": dec.rule,
                                "via": "api_chat"})
            return JSONResponse({"error": f"denied: {dec.reason}"}, status_code=403)
        if dec.effect == "ask":
            offer = {"principal_kind": "app", "principal_id": principal.id,
                     "action": "agent.invoke", "resource": "agent:main"}
            if not state["clients"] or not await request_approval(
                    "chat", {"text": text[:200]},
                    "This app wants to ask the AI (POST /api/chat).", offer=offer):
                return JSONResponse({"error": "needs approval: agent.invoke"}, status_code=403)
    model = body.get("model") or cfg.get("default_model", "")
    cid = body.get("conversation_id") or store.create_conversation(text[:60] or "API chat")
    history = _history_for(cid)
    store.add_message(cid, "user", text)
    history.append({"role": "user", "content": text})

    async def emit(_ev):
        pass

    async def approver(_n, _a, _r, _offer=None):
        return cfg.get("autonomy") == "full"

    agent = Agent(cfg, toolbox, model, emit, approver, conversation_id=cid,
                  principal=principal)
    knowledge.turn_started()
    try:
        result = await agent.run(history)
    finally:
        knowledge.turn_ended()
    store.add_message(cid, "assistant", result["content"], {"steps": result["steps"]})
    store.touch_conversation(cid)
    knowledge.schedule_extraction(cfg, store, cid, text, result["content"], state.get("broadcast"))
    return {"conversation_id": cid, "content": result["content"], "steps": result["steps"]}


def _history_for(cid: str) -> list[dict]:
    """Rebuild model-facing history from stored messages (text + attached images;
    tool traces stay in meta)."""
    out = []
    for m in state["store"].get_messages(cid):
        images = (m.get("meta") or {}).get("images") or []
        if m["role"] in ("user", "assistant") and ((m["content"] or "").strip() or images):
            entry = {"role": m["role"], "content": m["content"] or ""}
            if images:
                entry["images"] = images
            out.append(entry)
    return out


def _chat_images(data: dict, limit: int = 4) -> list[str]:
    """Sanitize client-supplied image attachments: data-URL images only, capped
    in count and size (~8 MB each as base64)."""
    out = []
    for u in (data.get("images") or [])[:limit]:
        if isinstance(u, str) and u.startswith("data:image/") and ";base64," in u and len(u) < 8_000_000:
            out.append(u)
    return out


# ---------------------------------------------------------------------------
# WebSocket: host terminal (PTY)
# ---------------------------------------------------------------------------

@app.websocket("/ws/terminal")
async def ws_terminal(ws: WebSocket):
    """A real shell on the host, bridged to xterm.js in the Terminal app."""
    import fcntl
    import os
    import pty
    import signal
    import struct
    import termios

    await ws.accept()
    from .tools import bwrap_argv, sandbox_conf
    sandboxed, sb_root = sandbox_conf(state["cfg"])
    if sandboxed:
        Path(sb_root).mkdir(parents=True, exist_ok=True)
    shell = os.environ.get("SHELL", "/bin/bash")
    pid, fd = pty.fork()
    if pid == 0:  # child: become the user's shell (jailed to the sandbox root if enabled)
        env = dict(os.environ)
        env["TERM"] = "xterm-256color"
        if sandboxed:
            os.execvpe("bwrap", bwrap_argv(sb_root, ["/bin/bash", "-l"]), env)
        try:
            os.chdir(os.path.expanduser("~"))
        except OSError:
            pass
        os.execvpe(shell, [shell, "-l"], env)

    state["store"].log("system", f"terminal session opened (pid {pid})")
    loop = asyncio.get_event_loop()
    out_q: asyncio.Queue = asyncio.Queue()

    def on_readable():
        try:
            data = os.read(fd, 65536)
        except OSError:
            data = b""
        out_q.put_nowait(data)

    loop.add_reader(fd, on_readable)

    async def pump():
        while True:
            data = await out_q.get()
            if not data:
                try:
                    await ws.close()
                except Exception:
                    pass
                return
            try:
                await ws.send_text(data.decode("utf-8", "replace"))
            except Exception:
                return

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("type") == "input":
                os.write(fd, msg.get("data", "").encode())
            elif msg.get("type") == "resize":
                fcntl.ioctl(fd, termios.TIOCSWINSZ,
                            struct.pack("HHHH", int(msg.get("rows", 24)), int(msg.get("cols", 80)), 0, 0))
    except (WebSocketDisconnect, OSError, json.JSONDecodeError):
        pass
    finally:
        loop.remove_reader(fd)
        pump_task.cancel()
        try:
            os.kill(pid, signal.SIGHUP)
        except ProcessLookupError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# WebSocket: chat + approvals
#
# Turns and builds are GLOBAL (state["turns"] / state["build"]) and their events go
# through the global broadcast: a page reload, a second window, or a dropped socket
# never strands a running turn — clients re-attach via the state_sync event and the
# UI routes streams by conversation_id. Every turn is guaranteed to release its slot
# and emit a terminal event (turn_end / build_done / build_error), whatever happens.
# ---------------------------------------------------------------------------


async def _force_cancel(task: asyncio.Task, grace: float = 8.0):
    """Give a stopped turn `grace` seconds to wind down cooperatively (the aborted
    flag), then cancel for real — cancellation closes the provider's HTTP stream,
    the only thing that interrupts a model that hasn't produced a token yet."""
    for _ in range(max(1, int(grace * 2))):
        if task.done():
            return
        await asyncio.sleep(0.5)
    if not task.done():
        task.cancel()


async def run_chat(cid: str, data: dict):
    """One chat turn, running as its own task — several conversations may run at
    once. Two guarantees on every exit path: the turn slot is released, and a
    terminal event reaches the UI."""
    cfg, store, toolbox = state["cfg"], state["store"], state["toolbox"]
    turns = state["turns"]
    text = (data.get("text") or "").strip()

    async def evsend(ev: dict):
        await state["broadcast"]({**ev, "conversation_id": cid})

    async def approver(name: str, args: dict, reason: str, offer: dict | None = None) -> bool:
        # global broker: the card renders in this chat, but any client may answer
        return await request_approval(name, args, reason, offer=offer, evsend=evsend)

    agent = None
    started = False
    header = ""
    model = data.get("model") or cfg.get("default_model", "")
    result = {"content": "", "steps": [], "tokens": {"input": 0, "output": 0}}
    try:
        images = _chat_images(data)
        history = _history_for(cid)
        store.add_message(cid, "user", text, {"images": images} if images else None)
        entry = {"role": "user", "content": text}
        if images:
            entry["images"] = images
        history.append(entry)
        store.touch_conversation(cid)

        # '@subagent task' addresses a team member directly — it runs INSIDE this chat,
        # streaming its steps like a normal turn, and still shows up in Observability
        mention = fabricmod.parse_mention(store, text)
        if mention:
            defn, task = mention
            model = state["fabric"].resolve_model(defn)
            turns[cid] = {"agent": None, "task": asyncio.current_task(), "model": model}
            knowledge.turn_started()
            started = True
            await evsend({"type": "turn_start", "model": model})
            res = await state["fabric"].run_subagent(
                defn, task, conversation_id=cid, ui_emit=evsend,
                approver=approver, agent_slot=turns[cid])
            content = res["content"] or (f"({res['status']}: {res['fault']})" if res["fault"]
                                         else f"({res['status']})")
            header = f"@{defn['name']} · {res['model']}\n\n" if res.get("model") else ""
            if not res["content"]:
                await evsend({"type": "text_delta", "text": header + content})
            usage = res.get("usage") or {}
            result = {"content": content, "steps": res["steps"],
                      "tokens": {"input": usage.get("in", 0), "output": usage.get("out", 0)}}
        else:
            agent = Agent(cfg, toolbox, model, evsend, approver, conversation_id=cid)
            turns[cid] = {"agent": agent, "task": asyncio.current_task(), "model": model}
            knowledge.turn_started()
            started = True
            await evsend({"type": "turn_start", "model": model})
            result = await agent.run(history)
    except asyncio.CancelledError:
        # force-stopped (user abort escalation / shutdown): keep whatever streamed,
        # still close the turn cleanly below
        if agent is not None:
            result = {"content": agent.partial_text, "steps": agent.partial_steps,
                      "tokens": result["tokens"]}
        with contextlib.suppress(Exception):
            await evsend({"type": "error", "message": "turn stopped"})
    except Exception as e:
        with contextlib.suppress(Exception):
            await evsend({"type": "error", "message": f"{type(e).__name__}: {e}"})
        with contextlib.suppress(Exception):
            store.log("error", f"chat turn failed: {type(e).__name__}: {e}"[:400],
                      {"conversation_id": cid})
    finally:
        if started:
            knowledge.turn_ended()
        try:
            store.add_message(cid, "assistant", header + result["content"],
                              {"steps": result["steps"]})
            store.touch_conversation(cid)
            tk = result.get("tokens") or {}
            store.log("turn", text[:200], {"conversation_id": cid, "model": model,
                                           "steps": len(result["steps"]),
                                           "in": tk.get("input", 0), "out": tk.get("output", 0)})
            knowledge.schedule_extraction(cfg, store, cid, text, result["content"],
                                          state.get("broadcast"))
        except Exception as e:
            with contextlib.suppress(Exception):
                store.log("error", f"turn persistence failed: {e}"[:400])
        turns.pop(cid, None)
        with contextlib.suppress(Exception):
            await evsend({"type": "turn_end"})

def _validate_app_html(html: str) -> list[str]:
    """Structural completeness checks — catches the truncated / half-generated apps a
    token-limit cutoff produces. Returns human-readable issues (empty = looks whole)."""
    import html.parser as _hp
    issues: list[str] = []
    h = (html or "").strip()
    if not h:
        return ["empty document"]
    low = h.lower()
    if h.startswith("```") or h.endswith("```"):
        issues.append("output is still wrapped in a markdown code fence")
    if "<html" in low and "</html>" not in low:
        issues.append("document opens <html> but never closes it (output was likely cut off)")
    for tag in ("script", "style"):
        if low.count(f"<{tag}") > low.count(f"</{tag}"):
            issues.append(f"unclosed <{tag}> block (output was likely cut off)")
    if h.rstrip().endswith(("<", "=", "(", "{", ",", "&&", "||", "+")):
        issues.append("document ends mid-token (output was cut off)")
    end_idx = low.rfind("</html>")
    if end_idx != -1 and h[end_idx + len("</html>"):].strip():
        issues.append("content continues after </html> (malformed or duplicated output)")
    # JS leaking into visible page text = a missing/broken <script> tag — the app
    # will render its own source code to the user
    try:
        from .tools import _TextExtractor
        ex = _TextExtractor()
        ex.feed(h)
        visible = " ".join(ex.parts)
        import re as _re2
        if _re2.search(r"\bfunction\s*\w*\s*\(|\)\s*=>\s*\{|document\.(querySelector|getElementById)", visible):
            issues.append("javascript appears as visible page text (missing <script> tag or broken markup)")
    except Exception:
        pass

    class _Chk(_hp.HTMLParser):
        VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
                "meta", "param", "source", "track", "wbr"}

        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.stack: list[str] = []

        def handle_starttag(self, tag, attrs):
            if tag not in self.VOID:
                self.stack.append(tag)

        def handle_endtag(self, tag):
            if tag in self.VOID:
                return
            if tag in self.stack:
                while self.stack and self.stack[-1] != tag:
                    self.stack.pop()
                if self.stack:
                    self.stack.pop()

    try:
        p = _Chk()
        p.feed(h)
        p.close()
        leftovers = [t for t in p.stack if t not in ("html", "body", "head", "p", "li")]
        if len(leftovers) >= 2:
            issues.append("unbalanced HTML — unclosed <" + ">, <".join(leftovers[-4:])
                          + "> (likely truncated)")
    except Exception:
        pass
    return issues


def _build_history(cid: str, keep: int = 6) -> list[dict]:
    """Build-conversation history, bounded: only the last `keep` messages, with
    embedded ```html sources stripped from all but the newest message — each
    refinement re-embeds the CURRENT source, so older copies are dead weight that
    multiplies truncation odds on local models."""
    import re
    hist = _history_for(cid)[-keep:]
    for m in hist[:-1]:
        c = m.get("content") or ""
        if "```html" in c:
            m["content"] = re.sub(r"```html.*?```",
                                  "```html\n<!-- (older app source omitted) -->\n```",
                                  c, flags=re.S)
    return hist


def _pick_build_model(models, current, cloud_only=False):
    """Prefer a model known to tool-call reliably: cloud first, then strong local families.
    With cloud_only=True (the failure-retry path) local models are excluded — "retrying"
    onto a bigger local model usually means CPU offload: slower and worse, not better."""
    ids = [m["id"] for m in models if m["id"] != current]
    markers = ("claude", "gpt-5", "gpt-4") if cloud_only \
        else ("claude", "gpt-5", "gpt-4", "qwen", "devstral", "mistral", "llama3")
    for marker in markers:
        pool = [i for i in ids if marker in i.lower()]
        if cloud_only:
            pool = [i for i in pool if not i.startswith("ollama/")]
        if pool:
            return pool[0]
    return None


@app.get("/api/lifecycle")
async def api_lifecycle():
    """Mission Control: one snapshot of all six lifecycle pillars —
    Train · Test · Operate · Build · Ship · Manage."""
    cfg, store = state["cfg"], state["store"]
    out: dict = {}

    tf = await state["trainforge"].health()
    train = {"service": "running" if tf.get("running") else ("available" if tf.get("path") else "not installed"),
             "url": tf.get("url", ""), "jobs_running": 0, "models": 0}
    if tf.get("running"):
        code, jobs = await state["trainforge"].api("GET", "/api/jobs", timeout=5)
        if code == 200 and isinstance(jobs, list):
            train["jobs_running"] = sum(1 for j in jobs if j.get("status") == "running")
            train["jobs_total"] = len(jobs)
        code, models = await state["trainforge"].api("GET", "/api/models", timeout=5)
        if code == 200 and isinstance(models, list):
            train["models"] = len(models)
    out["train"] = train

    last_test = next(iter(store.get_logs(kind="test", limit=1) or []), None) \
        if hasattr(store, "get_logs") else None
    if last_test is None:
        try:
            row = store.db.execute(
                "select message, created_at from logs where kind='test' "
                "order by created_at desc limit 1").fetchone()
            last_test = dict(row) if row else None
        except Exception:
            last_test = None
    out["test"] = {"suite": "tests/ (pytest)", "last": last_test,
                   "gate": "self-modification restarts run the suite first"}

    try:
        tasks = store.list_tasks()
    except Exception:
        tasks = []
    day_ago = time.time() - 86400
    try:
        errors_24h = store.db.execute(
            "select count(*) c from logs where kind='error' and created_at > ?",
            (day_ago,)).fetchone()["c"]
        turns_24h = store.db.execute(
            "select count(*) c from logs where kind='turn' and created_at > ?",
            (day_ago,)).fetchone()["c"]
    except Exception:
        errors_24h = turns_24h = 0
    out["operate"] = {"scheduled_tasks": len(tasks),
                      "tasks_enabled": sum(1 for t in tasks if t.get("enabled")),
                      "turns_24h": turns_24h, "errors_24h": errors_24h,
                      "turns_running": len(state.get("turns") or {})}

    apps = store.list_apps()
    b = state.get("build") or {}
    out["build"] = {"apps": len(apps),
                    "build_running": bool(b.get("task") and not b["task"].done()),
                    "last_app": apps[0]["name"] if apps else ""}

    projects_dir = Path(os.path.expanduser(cfg["workspace"])) / "projects"
    repos = []
    if projects_dir.is_dir():
        repos = [p.name for p in projects_dir.iterdir() if (p / ".git").is_dir()]
    out["ship"] = {"git_projects": repos,
                   "github_token": bool((cfg.get("github") or {}).get("token")),
                   "package": "deb (packaging/build-deb.sh)"}

    try:
        grants = len(store.list_grants())
    except Exception:
        grants = 0
    snaps_dir = cfgmod.AGENTOS_HOME / "snapshots"
    snaps = len(list(snaps_dir.iterdir())) if snaps_dir.is_dir() else 0
    out["manage"] = {"autonomy": cfg.get("autonomy", ""), "model": cfg.get("default_model", ""),
                     "grants": grants, "snapshots": snaps,
                     "sandbox": bool((cfg.get("sandbox") or {}).get("enabled"))}
    return out


@app.get("/api/train/status")
async def train_status():
    """Train pillar: TrainForge service health for the Train desktop app."""
    return await state["trainforge"].health()


@app.post("/api/train/service")
async def train_service(body: dict):
    """Start/stop the TrainForge service from the desktop (loopback-bound, no auth
    beyond localhost — same trust model as the rest of the control surface)."""
    action = (body or {}).get("action", "")
    if action == "start":
        return {"result": await state["trainforge"].start()}
    if action == "stop":
        return {"result": await state["trainforge"].stop()}
    return JSONResponse({"error": "action must be start|stop"}, status_code=400)


@app.get("/api/build/status")
async def build_status():
    """Reconnect support: a reloaded App Studio asks whether a build is still running."""
    b = state.get("build") or {}
    running = bool(b.get("task") and not b["task"].done())
    return {"running": running, "app_id": b.get("app_id", ""),
            "prompt": b.get("prompt", ""), "started_at": b.get("started_at", 0)}


async def run_build(data: dict):
    """Agentic App Builder: an agent whose job is to build/refine a UI app via create_app,
    streamed live to App Studio with a preview. Exactly one terminal event
    (build_done / build_error) is emitted on every exit path."""
    cfg, store, toolbox = state["cfg"], state["store"], state["toolbox"]
    build = state["build"]
    bcast = state["broadcast"]
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return
    req_model = (data.get("model") or "").strip()
    # empty or "auto" ⇒ let the builder pick the most build-capable model available
    model = "" if req_model.lower() in ("", "auto") else req_model
    app_id = data.get("app_id") or ""
    existing = store.get_app(app_id) if app_id else None
    build.update(agent=None, cancel_requested=False, timed_out=False,
                 prompt=prompt[:200], app_id=app_id, started_at=time.time())

    done_sent = False

    async def terminal(ev: dict):
        nonlocal done_sent
        if done_sent:
            return
        done_sent = True
        with contextlib.suppress(Exception):
            await bcast(ev)

    try:
        # one persistent build conversation per app (context for iterative refinement);
        # new-app prompts share a single "build: new app" session — renamed to the app's
        # own session once a build succeeds — so iterating never forks a fresh conversation
        title = f"build: {existing['name']}" if existing else "build: new app"
        cid = None
        for c in store.list_conversations(limit=500):
            if c["title"] == title:
                cid = c["id"]
                break
        cid = cid or store.create_conversation(title)
        # refinements need the app's build context; a NEW app must NOT inherit the
        # shared "new app" session's past failures (small models imitate whatever
        # the previous assistant turns did — including failing)
        history = _build_history(cid) if existing else []

        ctx = prompt
        if existing:
            src = existing["html"]
            if len(src) > 60000:  # keep pathological apps bounded; still far beyond any normal app
                src = src[:60000] + "\n<!-- …source truncated for context; keep the app COMPLETE when rewriting -->"
            ctx = (f"You are refining the existing app named \"{existing['name']}\". "
                   f"Its current FULL HTML is below. Apply the requested change and output the COMPLETE "
                   f"updated app — call create_app with the SAME name (preferred), or emit a single "
                   f"```html code block. Never drop existing features while applying the change.\n\n"
                   f"```html\n{src}\n```\n\nChange requested: {prompt}")
        store.add_message(cid, "user", prompt)
        history.append({"role": "user", "content": ctx})

        # enough steps to spec → ground → build → fix, but still bounded; builds get a
        # bigger output budget than chat (a whole app must fit in one tool call), and
        # the thinking channel is OFF — a local thinking model can burn its entire
        # budget reasoning and never emit the app
        bcfg = {**cfg, "max_steps": 10,
                "max_output_tokens": int(cfg.get("build_max_output_tokens", 32768)),
                "ollama_think": False}
        build_timeout = int(cfg.get("build_timeout", 600))

        async def bemit(ev):
            m = {"text_delta": "build_text", "thinking_delta": "build_thinking",
                 "tool_start": "build_tool", "tool_end": "build_tool_end",
                 "error": "build_error_note", "status": "build_status"}
            if ev["type"] in m:
                await bcast({**ev, "type": m[ev["type"]]})

        async def bapprove(name, args, reason, offer=None):
            return True if name == "create_app" else (cfg.get("autonomy") == "full")

        def persona_for(use_model: str) -> str:
            """Full API registry for capable cloud models; trimmed for local ones —
            a 10KB+ registry inside an already-large persona overflows small contexts."""
            try:
                reg = _registry_text()
                if use_model.startswith("ollama/") and len(reg) > 4000:
                    reg = reg[:4000] + "\n… (registry trimmed — appTool/appData/appLLM above are the essentials)"
                return BUILDER_PERSONA + "\n=== API REGISTRY (everything this app may call) ===\n" + reg
            except Exception:
                return BUILDER_PERSONA

        async def attempt(use_model):
            """Run one build turn; return (built_app_or_None, result).
            Success = an app was created OR an existing app's source actually changed.

            Local (Ollama) models build WITHOUT tools: several local model templates
            mangle large tool-call payloads (the parser silently swallows the entire
            output), so they emit one ```html block as plain text instead — the
            extraction + validation path below installs it."""
            before = {a["id"]: a.get("updated_at") for a in store.list_apps()}
            local = use_model.startswith("ollama/")
            extra = persona_for(use_model)
            tf = ["create_app", "read_file", "list_dir", "fetch_url", "system_info"]
            if local:
                tf = []
                # small models anchor on the FIRST instruction they read — the output
                # contract must lead, not trail, the persona
                extra = (("=== OUTPUT CONTRACT (overrides everything below) ===\n"
                          "Tools are unavailable this turn. Your reply MUST be, in order:\n"
                          "name: \"<app name>\"\n"
                          "description: \"<one line>\"\n"
                          "then the COMPLETE app as ONE ```html fenced code block, then STOP.\n"
                          "A reply without a ```html block is a total failure. Do not describe or "
                          "announce the app — OUTPUT it.\n\n") + extra)
            agent = Agent(bcfg, toolbox, use_model, bemit, bapprove,
                          extra_system=extra, tool_filter=tf)
            build["agent"] = agent
            knowledge.turn_started()
            try:
                res = await asyncio.wait_for(agent.run(history), timeout=build_timeout)
            except asyncio.TimeoutError:
                # a timeout is NOT a user cancel: report it as such and let the
                # caller decide whether to retry on a stronger model
                agent.aborted = True
                build["timed_out"] = True
                res = {"content": agent.partial_text, "steps": agent.partial_steps}
            except Exception as e:
                await bcast({"type": "build_text",
                             "text": f"\n(attempt failed: {type(e).__name__}: {e})\n"})
                res = {"content": "", "steps": []}
            finally:
                knowledge.turn_ended()
                build["agent"] = None

            def changed_apps():
                return [a for a in store.list_apps()
                        if a["id"] not in before or a.get("updated_at") != before[a["id"]]]

            new = changed_apps()
            if not new:  # model wrote HTML as text instead of calling create_app → extract it
                html = _extract_html(res["content"]) or _extract_html_from_steps(res["steps"])
                # never install a truncated half-app as a "success"
                if html and not _validate_app_html(html):
                    if existing:
                        store.save_app(existing["name"], existing["icon"], existing["description"], html, note=prompt[:120])
                    else:
                        meta_name, meta_desc = _extract_app_meta(res["content"])
                        nm = meta_name or _default_app_name(prompt)
                        store.save_app(nm, "", meta_desc or prompt[:80], html, note=prompt[:120])
                    new = changed_apps()
            return (new[0] if new else None), res

        await bcast({"type": "build_start"})

        # Auto model selection: prefer a tool-call-reliable model (cloud first, then strong
        # local families); fall back to the configured default, then anything available.
        if not model:
            try:
                _avail = await providers.available_models(cfg)
            except Exception:
                _avail = []
            model = (_pick_build_model(_avail, "") or cfg.get("default_model", "")
                     or (_avail[0]["id"] if _avail else ""))
            if model:
                await bcast({"type": "build_text",
                             "text": f"\n(Auto-selected {model.split('/')[-1]} to build this app.)\n"})
                store.log("system", f"build auto-selected {model}")

        used_model = model
        built, result = await attempt(model)

        # announcement-only reply ("I will build it…") with no actual app: one direct
        # nudge on the same model — the prompt is now cached, so this round is cheap
        if (not built and not build.get("cancel_requested") and not build.get("timed_out")
                and result.get("content") and "```" not in result["content"]):
            await bcast({"type": "build_text",
                         "text": "\n(no app in the reply — asking the model to output it…)\n"})
            history.append({"role": "assistant", "content": result["content"]})
            history.append({"role": "user", "content":
                            "You did not output the app. No commentary — output the COMPLETE app "
                            "now as ONE ```html fenced block (with the name:/description: lines "
                            "above it)."})
            built, result = await attempt(model)

        if not built and build.get("cancel_requested"):
            store.add_message(cid, "assistant", result["content"] or "(build cancelled)",
                              {"steps": result["steps"]})
            await terminal({"type": "build_error", "message": "build cancelled"})
            return

        # Auto-retry with a tool-capable model if the selected one produced nothing
        # (some local models, e.g. gemma, don't reliably tool-call under a large prompt).
        if not built:
            if build.get("timed_out"):
                await bcast({"type": "build_text",
                             "text": f"\n(build timed out after {build_timeout}s…)\n"})
            try:
                models = await providers.available_models(cfg)
            except Exception:
                models = []
            better = _pick_build_model(models, model, cloud_only=True)
            if better:
                await bcast({"type": "build_text",
                             "text": f"\n({model.split('/')[-1]} produced nothing — retrying with {better.split('/')[-1]}…)\n"})
                store.log("system", f"build retry with {better} (from {model})")
                build["timed_out"] = False
                built, result = await attempt(better)
                if built:
                    used_model = better

        # Verification: structural completeness (truncation) + static lint (things that
        # WILL break at runtime). The model gets ONE fix pass.
        if built:
            full = store.get_app(built["id"]) or {}
            issues = _validate_app_html(full.get("html", "")) + _lint_app_html(full.get("html", ""), toolbox)
            if issues:
                await bcast({"type": "build_text",
                             "text": "\n(automated check: " + "; ".join(issues)[:400] + " — fixing…)\n"})
                history.append({"role": "assistant", "content": result["content"] or "(built the app)"})
                history.append({"role": "user", "content":
                                "AUTOMATED CHECK on the app you just built found problems:\n- "
                                + "\n- ".join(issues)
                                + f"\nCall create_app again with name \"{built['name']}\" and the corrected COMPLETE html."})
                fixed, fix_res = await attempt(used_model)
                if fixed:
                    built, result = fixed, fix_res

        store.add_message(cid, "assistant", result["content"], {"steps": result["steps"]})
        if built and not existing:
            # the "new app" session becomes this app's session — refinements continue it
            store.touch_conversation(cid, f"build: {built['name']}")
        manifest_status = "none"
        if built:  # builder didn't declare permissions? scan the source and propose them
            full = store.get_app(built["id"]) or {}
            manifest_status = full.get("manifest_status") or "none"
            if manifest_status == "none":
                _propose_manifest(built["id"])
                manifest_status = "proposed"
        await state["broadcast"]({"type": "apps"})
        if built:
            # anything the repair pass could not fix ships as an explicit warning,
            # never as a silent "success"
            remaining = _validate_app_html((store.get_app(built["id"]) or {}).get("html", ""))
            await terminal({"type": "build_done", "app_id": built["id"], "name": built["name"],
                            "summary": result["content"][:600],
                            "manifest_status": manifest_status,
                            "warnings": remaining})
        elif build.get("cancel_requested"):
            await terminal({"type": "build_error", "message": "build cancelled"})
        elif build.get("timed_out"):
            await terminal({"type": "build_error",
                            "message": f"build timed out after {build_timeout}s — try a simpler "
                                       f"prompt, or pick a stronger model"})
        else:
            await terminal({"type": "build_error",
                            "message": "couldn't produce an app — try rephrasing, or select a "
                                       "tool-capable model (e.g. a qwen model) in the chat window"})
    except asyncio.CancelledError:
        await terminal({"type": "build_error", "message": "build cancelled"})
    except Exception as e:
        with contextlib.suppress(Exception):
            store.log("error", f"build crashed: {type(e).__name__}: {e}"[:400])
        await terminal({"type": "build_error", "message": f"build failed: {type(e).__name__}: {e}"})
    finally:
        build["agent"] = None
        # belt and braces: if some path above returned without a terminal event,
        # the UI must never be left spinning
        await terminal({"type": "build_error", "message": "build ended unexpectedly"})

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    state["clients"].add(ws)
    turns, build = state["turns"], state["build"]

    async def send(event: dict):
        with contextlib.suppress(Exception):
            await ws.send_text(json.dumps(event))

    # a (re)connecting client learns what is still running, so a page reload never
    # strands a spinner — the UI re-attaches (or clears) by conversation_id
    await send({"type": "state_sync",
                "running": list(turns.keys()),
                "build_running": bool(build.get("task") and not build["task"].done())})

    def _stop(tinfo: dict):
        """Cooperative abort first; hard-cancel after a grace period — a model that
        hasn't produced a token yet only stops when its HTTP stream is closed."""
        if tinfo.get("agent"):
            tinfo["agent"].aborted = True
        task = tinfo.get("task")
        if task and not task.done():
            asyncio.create_task(_force_cancel(task))

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            t = data.get("type")
            if t == "chat":
                text = (data.get("text") or "").strip()
                if not text and not _chat_images(data):
                    continue
                cid = data.get("conversation_id")
                if cid and cid in turns:
                    await send({"type": "error", "conversation_id": cid,
                                "message": "This conversation already has a turn running — "
                                           "stop it, or continue in another chat."})
                    continue
                if not cid:
                    title = text[:60] or "(image)"
                    cid = state["store"].create_conversation(title)
                    await send({"type": "conversation", "id": cid, "title": title})
                turns[cid] = {"agent": None, "task": None, "model": ""}  # claim before the task starts
                turns[cid]["task"] = asyncio.create_task(run_chat(cid, data))
            elif t == "build":
                if build.get("task") and not build["task"].done():
                    await send({"type": "build_error", "message": "A build is already running — wait for it."})
                else:
                    build["task"] = asyncio.create_task(run_build(data))
            elif t == "build_abort":
                build["cancel_requested"] = True
                if build.get("agent"):
                    build["agent"].aborted = True
                if build.get("task") and not build["task"].done():
                    await state["broadcast"]({"type": "build_text", "text": "\n(cancelling…)\n"})
                    asyncio.create_task(_force_cancel(build["task"], grace=15.0))
            elif t == "approval":
                await resolve_approval(data.get("id", ""), bool(data.get("approved")),
                                       remember=bool(data.get("remember")))
            elif t == "abort":
                cid = data.get("conversation_id")
                if cid:  # stop one conversation's turn
                    if cid in turns:
                        _stop(turns[cid])
                else:    # legacy/global abort: stop every running turn + build
                    for tinfo in list(turns.values()):
                        _stop(tinfo)
                    build["cancel_requested"] = True
                    if build.get("agent"):
                        build["agent"].aborted = True
                    if build.get("task") and not build["task"].done():
                        asyncio.create_task(_force_cancel(build["task"], grace=15.0))
                    for entry in state["pending_approvals"].values():
                        if not entry["fut"].done():
                            entry["fut"].set_result(False)
    except (WebSocketDisconnect, json.JSONDecodeError, OSError):
        pass
    finally:
        # turns and builds are global: they KEEP RUNNING when a socket drops (the
        # reply persists and broadcasts to whoever is connected); only this socket's
        # registration is cleaned up
        state["clients"].discard(ws)
