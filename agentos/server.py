"""AgentOS server: web UI, WebSocket event stream, REST API."""

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from . import config as cfgmod
from . import fabric as fabricmod
from . import knowledge
from . import providers
from .agent import Agent
from .mcp_client import MCP_AVAILABLE, MCPManager
from .memory import Store
from .scheduler import Scheduler
from .telegram import TelegramBridge
from .tools import Toolbox

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
    fabricmod.seed_builtins(cfg, store)
    state.update(cfg=cfg, store=store, toolbox=toolbox, scheduler=scheduler,
                 mcp=mcp, telegram=telegram, clients=clients, broadcast=broadcast,
                 fabric=control)
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


@app.on_event("shutdown")
async def shutdown():
    if "scheduler" in state:
        state["scheduler"].stop()
    if "telegram" in state:
        state["telegram"].stop()
    if "mcp" in state:
        await state["mcp"].stop()


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
    """Open a URL or a workspace file in the HOST OS (default browser / app) via xdg-open."""
    import shutil
    import subprocess
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
    opener = shutil.which("xdg-open") or shutil.which("gio")
    if not opener:
        return JSONResponse({"error": "no host opener (xdg-open) available"}, status_code=500)
    try:
        subprocess.Popen([opener, "open", target] if opener.endswith("gio") else [opener, target],
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
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
    """Live system stats for the Task Manager app (Linux, stdlib only)."""
    import os
    import shutil

    idle, total = _read_cpu()
    prev = state.get("cpu_prev")
    state["cpu_prev"] = (idle, total)
    cpu = 0.0
    if prev and total > prev[1]:
        cpu = round(100 * (1 - (idle - prev[0]) / (total - prev[1])), 1)

    mem = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            mem[k] = int(v.strip().split()[0])  # kB
    mem_total = mem.get("MemTotal", 0)
    mem_used = mem_total - mem.get("MemAvailable", 0)

    du = shutil.disk_usage(Path.home())
    with open("/proc/uptime") as f:
        uptime = float(f.read().split()[0])

    procs = []
    try:
        p = await asyncio.create_subprocess_exec(
            "ps", "-eo", "pid,comm,%cpu,%mem", "--sort=-%cpu",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
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
            "uptime": uptime, "cores": os.cpu_count() or 1, "procs": procs}


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
    for name, pconf in (patch.get("providers") or {}).items():
        if name not in cfg["providers"]:
            continue
        for k in ("enabled", "base_url", "models"):
            if k in pconf:
                cfg["providers"][name][k] = pconf[k]
        # masked keys ("•••xxxx") mean "unchanged"
        if "api_key" in pconf and not str(pconf["api_key"]).startswith("•••"):
            cfg["providers"][name]["api_key"] = pconf["api_key"]
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
async def api_logs(kind: str = "", limit: int = 300):
    return {"logs": state["store"].list_logs(kind, min(limit, 1000))}


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
    aid = state["store"].save_app(t["name"], t["icon"], t["desc"], t["html"])
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
// Every built app gets its own data store (its "MCP"): appData.get()/set() persist server-side
// and are readable by the agent. Also appTool(name,args) runs any OS/MCP tool.
window.appData = {
  async get(){ try{ return await (await fetch('/api/apps/'+window.APP_ID+'/data')).json(); }catch(e){ return {}; } },
  async set(obj){ try{ await fetch('/api/apps/'+window.APP_ID+'/data',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(obj)}); }catch(e){} },
};
window.appTool = async (name,args={}) => {
  try{ const r = await fetch('/api/tool',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,args})}); return await r.json(); }catch(e){ return {error:String(e)}; }
};
</script>"""


@app.get("/api/apps/{aid}/page")
async def api_app_page(aid: str):
    from fastapi.responses import HTMLResponse
    a = state["store"].get_app(aid)
    if not a:
        return JSONResponse({"error": "not found"}, status_code=404)
    html = a["html"] or ""
    if not html.lstrip().lower().startswith(("<!doctype", "<html")):
        html = APP_SHELL.format(body=html)
    runtime = APP_RUNTIME % aid
    # inject the runtime right after <body>, or prepend it
    low = html.lower()
    if "<body" in low:
        i = low.index("<body")
        i = low.index(">", i) + 1
        html = html[:i] + runtime + html[i:]
    else:
        html = runtime + html
    return HTMLResponse(html)


@app.get("/api/apps/{aid}/data")
async def api_app_data_get(aid: str):
    return json.loads(state["store"].get_app_data(aid) or "{}")


@app.put("/api/apps/{aid}/data")
async def api_app_data_set(aid: str, body: dict):
    state["store"].set_app_data(aid, json.dumps(body)[:200_000])
    return {"ok": True}


def _extract_html(text: str) -> str:
    """Pull an HTML app out of model text: a ```html fenced block, any fenced block that
    looks like HTML, or a raw <...> body."""
    import re
    if not text:
        return ""
    m = re.search(r"```(?:html)?\s*\n(.*?)```", text, re.DOTALL)
    if m and ("<" in m.group(1)):
        return m.group(1).strip()
    m = re.search(r"(<(?:!doctype|html|div|h[1-6]|style|section|main|body)[\s\S]*)", text, re.IGNORECASE)
    if m and len(m.group(1)) > 40:
        return m.group(1).strip().rstrip("`").strip()
    return ""


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

DATA — every app has its OWN data store (its "MCP"), pre-injected as page globals:
- `await appData.get()` returns the app's saved object; `await appData.set(obj)` saves it. USE THIS for
  anything the user creates so it survives reloads AND the agent can read it later. Prefer it to localStorage.
- `await appTool(name, args)` runs ANY OS/MCP tool from the app and returns its output — the way to pull
  LIVE data, e.g. appTool('fetch_url',{url:…}), appTool('system_info'), appTool('run_command',{command:…}),
  or a connected mcp_* tool. Plain REST also works: GET /api/system · POST /api/chat {text} (AI answers).
- Apps may poll (setInterval) or open ws://{location.host}/ws for realtime.
- THE FULL API REGISTRY of this OS is appended below (also live at GET /api/registry). Anything listed
  there is fair game — your app can drive the whole OS: chat, files, models, tasks, themes, workflows.
  The user's interface wishes are the spec; the registry is what makes them possible.

PROCESS:
- If the app needs live data or specific tools, you MAY call one read-only tool first to learn the shape,
  then build; otherwise go straight to create_app. Leave `icon` empty (the OS renders a clean monogram tile — the user dislikes emoji icons) and pick a concise name.
- If the user wants it pinned / on the desktop / as a widget, call pin_widget(name) after create_app.
- Do the work in THIS turn — never ask questions. Finish with one short sentence on what you built.
"""


# ---- Run a single tool (for AI-built apps to reach the OS / MCP) -----------------

@app.post("/api/tool")
async def api_run_tool(body: dict):
    """Let a user-built app invoke an agent or MCP tool and get its output.
    Blocked/destructive calls are refused; risky calls run only in full autonomy."""
    name = body.get("name", "")
    args = body.get("args") or {}
    toolbox = state["toolbox"]
    if name not in {t["name"] for t in toolbox.schemas()}:
        return JSONResponse({"error": f"unknown tool: {name}"}, status_code=400)
    level, reason = toolbox.risk_of(name, args)
    if level == "blocked":
        return JSONResponse({"error": f"blocked: {reason}"}, status_code=403)
    if level == "risky" and state["cfg"].get("autonomy") != "full":
        return JSONResponse({"error": f"needs approval (set autonomy to Full to allow): {reason}"},
                            status_code=403)
    out = await toolbox.execute(name, args)
    state["store"].log("tool", f"app→{name}", {"args": args, "via": "user_app"})
    return {"output": out}


@app.get("/api/tools")
async def api_list_tools():
    """The tool names an app (or user) can call via /api/tool, incl. connected MCP tools."""
    return {"tools": [{"name": t["name"], "description": t["description"]}
                      for t in state["toolbox"].schemas()]}


# ---- API registry: the UI-builder's contract ---------------------------------

WS_EVENTS = {
    "outbound (server → client)": [
        "text_delta {text}", "thinking_delta {text}", "tool_start {call_id,name,args}",
        "tool_end {call_id,ok,output}", "approval_request {id,name,args,reason}",
        "turn_start / turn_end {conversation_id}", "error {message}",
        "apps / themes / widgets / wallpaper / models / files / config  (refresh hints)",
        "theme_apply {theme}", "model_pull {name,status,done}", "fabric_event / fabric_defs",
        "telegram_in / telegram_out {conversation_id,text}", "knowledge_update",
    ],
    "inbound (client → server)": [
        "chat {text, conversation_id?, model?}", "build {prompt, app_id?, model?}",
        "approval {id, approved}", "abort {}",
    ],
}

APP_RUNTIME_GLOBALS = {
    "APP_ID": "the app's own id (string), injected into every built app page",
    "appData.get() / appData.set(obj)": "the app's private persistent JSON store, server-side",
    "appTool(name, args)": "run any agent/MCP tool listed under `tools` and get its output",
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
                      "POST /api/tool {name,args} runs a tool; risky calls need Full autonomy."]}


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
    import subprocess
    subprocess.Popen(["systemctl", "--user", "restart", "agentos.service"],
                     start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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


@app.post("/api/wallpaper/system")
async def api_wallpaper_system():
    """Adopt the host GNOME desktop wallpaper as the AgentOS wallpaper."""
    import shutil
    import subprocess
    import urllib.parse
    try:
        uri = subprocess.run(["gsettings", "get", "org.gnome.desktop.background", "picture-uri-dark"],
                             capture_output=True, text=True, timeout=5).stdout.strip().strip("'")
        if not uri:
            uri = subprocess.run(["gsettings", "get", "org.gnome.desktop.background", "picture-uri"],
                                 capture_output=True, text=True, timeout=5).stdout.strip().strip("'")
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    path = urllib.parse.unquote(uri.replace("file://", ""))
    if not path or not Path(path).is_file():
        return JSONResponse({"error": "could not read the system wallpaper"}, status_code=404)
    shutil.copy2(path, cfgmod.AGENTOS_HOME / "wallpaper.png")
    await state["broadcast"]({"type": "wallpaper"})
    return {"ok": True, "source": path}


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
    order = ["README.md", "getting-started.md", "installation.md", "desktop.md", "agent.md",
             "building-apps.md", "integrations.md", "models.md", "configuration.md",
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
    from .desktop import SERVICE_FILE
    return {
        "first_run": cfgmod.is_first_run(),
        "agent_name": cfg.get("agent_name", "Aria"),
        "autonomy": cfg.get("autonomy", "balanced"),
        "default_model": cfg.get("default_model", ""),
        "ollama_models": local,
        "providers": {p: bool(cfg["providers"][p].get("api_key"))
                      for p in ("anthropic", "openai", "openrouter")},
        "autostart_installed": SERVICE_FILE.exists(),
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
async def api_chat(body: dict):
    """Headless one-shot chat (for scripts / curl). Autonomy rules still apply:
    risky actions are only taken in 'full' mode."""
    cfg, store, toolbox = state["cfg"], state["store"], state["toolbox"]
    text = body.get("text", "")
    model = body.get("model") or cfg.get("default_model", "")
    cid = body.get("conversation_id") or store.create_conversation(text[:60] or "API chat")
    history = _history_for(cid)
    store.add_message(cid, "user", text)
    history.append({"role": "user", "content": text})

    async def emit(_ev):
        pass

    async def approver(_n, _a, _r):
        return cfg.get("autonomy") == "full"

    agent = Agent(cfg, toolbox, model, emit, approver, conversation_id=cid)
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
    """Rebuild model-facing history from stored messages (text only; tool traces stay in meta)."""
    out = []
    for m in state["store"].get_messages(cid):
        if m["role"] in ("user", "assistant") and (m["content"] or "").strip():
            out.append({"role": m["role"], "content": m["content"]})
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
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    state["clients"].add(ws)
    pending_approvals: dict[str, asyncio.Future] = {}
    turns: dict = {}                            # conversation_id -> {"agent", "task"}
    build: dict = {"agent": None, "task": None}  # App Studio builds keep their own slot

    async def send(event: dict):
        try:
            await ws.send_text(json.dumps(event))
        except Exception:
            pass

    def _approver_for(evsend):
        async def approver(name: str, args: dict, reason: str) -> bool:
            aid = uuid.uuid4().hex[:8]
            fut = asyncio.get_event_loop().create_future()
            pending_approvals[aid] = fut
            await evsend({"type": "approval_request", "id": aid, "name": name,
                          "args": args, "reason": reason})
            try:
                return await asyncio.wait_for(fut, timeout=300)
            except asyncio.TimeoutError:
                return False
            finally:
                pending_approvals.pop(aid, None)
        return approver

    async def run_chat(cid: str, data: dict):
        """One turn in one conversation — several may run at once. Every event is
        stamped with its conversation_id so the UI routes streams to the right chat."""
        cfg, store, toolbox = state["cfg"], state["store"], state["toolbox"]
        text = data.get("text", "").strip()
        model = data.get("model") or cfg.get("default_model", "")

        async def evsend(ev: dict):
            await send({**ev, "conversation_id": cid})

        history = _history_for(cid)
        store.add_message(cid, "user", text)
        history.append({"role": "user", "content": text})
        store.touch_conversation(cid)

        agent = Agent(cfg, toolbox, model, evsend, _approver_for(evsend), conversation_id=cid)
        turns[cid] = {"agent": agent, "task": asyncio.current_task()}
        knowledge.turn_started()
        await send({"type": "turn_start", "conversation_id": cid, "model": model})
        try:
            result = await agent.run(history)
        except Exception as e:
            await evsend({"type": "error", "message": f"{type(e).__name__}: {e}"})
            result = {"content": "", "steps": []}
        finally:
            knowledge.turn_ended()
            turns.pop(cid, None)
        store.add_message(cid, "assistant", result["content"], {"steps": result["steps"]})
        store.touch_conversation(cid)
        tk = result.get("tokens") or {"input": 0, "output": 0}
        store.log("turn", text[:200], {"conversation_id": cid, "model": model,
                                       "steps": len(result["steps"]),
                                       "in": tk["input"], "out": tk["output"]})
        knowledge.schedule_extraction(cfg, store, cid, text, result["content"], state.get("broadcast"))
        await send({"type": "turn_end", "conversation_id": cid})

    async def run_build(data: dict):
        """Agentic App Builder: an agent whose job is to build/refine a UI app via create_app,
        streamed live to App Studio with a preview."""
        cfg, store, toolbox = state["cfg"], state["store"], state["toolbox"]
        prompt = data.get("prompt", "").strip()
        if not prompt:
            return
        model = data.get("model") or cfg.get("default_model", "")
        app_id = data.get("app_id") or ""
        existing = store.get_app(app_id) if app_id else None

        # one persistent build conversation per app (context for iterative refinement)
        title = f"build: {existing['name'] if existing else prompt[:32]}"
        cid = None
        if existing:
            for c in store.list_conversations(limit=500):
                if c["title"] == title:
                    cid = c["id"]
                    break
        cid = cid or store.create_conversation(title)
        history = _history_for(cid)

        ctx = prompt
        if existing:
            ctx = (f"You are refining the existing app named \"{existing['name']}\" (icon {existing['icon']}). "
                   f"Its current HTML is below. Output the COMPLETE updated app (with the change applied) as a "
                   f"single ```html code block, or call create_app with the SAME name.\n\n"
                   f"```html\n{existing['html'][:7000]}\n```\n\nChange requested: {prompt}")
        store.add_message(cid, "user", prompt)
        history.append({"role": "user", "content": ctx})

        # builds must not loop: cap steps low and time-box the whole turn
        bcfg = {**cfg, "max_steps": 4}

        async def bemit(ev):
            m = {"text_delta": "build_text", "thinking_delta": "build_thinking",
                 "tool_start": "build_tool", "tool_end": "build_tool_end", "error": "build_error"}
            if ev["type"] in m:
                await send({**ev, "type": m[ev["type"]]})

        async def bapprove(name, args, reason):
            return True if name == "create_app" else (cfg.get("autonomy") == "full")

        try:
            persona = BUILDER_PERSONA + "\n=== API REGISTRY (everything this app may call) ===\n" + _registry_text()
        except Exception:
            persona = BUILDER_PERSONA

        async def attempt(use_model):
            """Run one build turn; return (built_app_or_None, result)."""
            before = {a["id"] for a in store.list_apps()}
            agent = Agent(bcfg, toolbox, use_model, bemit, bapprove, extra_system=persona,
                          tool_filter=["create_app", "read_file", "list_dir", "fetch_url", "system_info"])
            build["agent"] = agent
            knowledge.turn_started()
            try:
                res = await asyncio.wait_for(agent.run(history), timeout=240)
            except asyncio.TimeoutError:
                agent.aborted = True
                res = {"content": "", "steps": []}
            except Exception as e:
                await send({"type": "build_error", "message": f"{type(e).__name__}: {e}"})
                res = {"content": "", "steps": []}
            finally:
                knowledge.turn_ended()
                build["agent"] = None
            apps = store.list_apps()
            new = [a for a in apps if a["id"] not in before]
            if not new:  # model wrote HTML as text instead of calling create_app → extract it
                html = _extract_html(res["content"]) or _extract_html_from_steps(res["steps"])
                if html:
                    if existing:
                        store.save_app(existing["name"], existing["icon"], existing["description"], html)
                    else:
                        nm = (prompt[:28].strip() or "App").title()
                        store.save_app(nm, "", prompt[:80], html)
                    apps = store.list_apps()
                    new = [a for a in apps if a["id"] not in before]
            return (existing or (new[0] if new else None)), res

        await send({"type": "build_start"})
        built, result = await attempt(model)

        # Auto-retry with a tool-capable model if the selected one produced nothing
        # (some local models, e.g. gemma, don't reliably tool-call under a large prompt).
        if not built:
            try:
                models = await providers.available_models(cfg)
            except Exception:
                models = []
            better = next((m["id"] for m in models
                           if "qwen" in m["id"].lower() and m["id"] != model), None)
            if better:
                await send({"type": "build_text", "text": f"\n({model.split('/')[-1]} produced nothing — retrying with {better.split('/')[-1]}…)\n"})
                store.log("system", f"build retry with {better} (from {model})")
                built, result = await attempt(better)

        store.add_message(cid, "assistant", result["content"], {"steps": result["steps"]})
        await state["broadcast"]({"type": "apps"})
        if built:
            await send({"type": "build_done", "app_id": built["id"], "name": built["name"],
                        "summary": result["content"][:600]})
        else:
            await send({"type": "build_error",
                        "message": "couldn't produce an app — try rephrasing, or select a tool-capable model (e.g. a qwen model) in the chat window"})

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            t = data.get("type")
            if t == "chat":
                text = (data.get("text") or "").strip()
                if not text:
                    continue
                cid = data.get("conversation_id")
                if cid and cid in turns:
                    await send({"type": "error", "conversation_id": cid,
                                "message": "This conversation already has a turn running — "
                                           "stop it, or continue in another chat."})
                    continue
                if not cid:
                    cid = state["store"].create_conversation(text[:60])
                    await send({"type": "conversation", "id": cid, "title": text[:60]})
                asyncio.create_task(run_chat(cid, data))
            elif t == "build":
                if build["task"] and not build["task"].done():
                    await send({"type": "build_error", "message": "A build is already running — wait for it."})
                else:
                    build["task"] = asyncio.create_task(run_build(data))
            elif t == "approval":
                fut = pending_approvals.get(data.get("id", ""))
                if fut and not fut.done():
                    fut.set_result(bool(data.get("approved")))
            elif t == "abort":
                cid = data.get("conversation_id")
                if cid:  # stop one conversation's turn; its pending approvals die with it
                    if cid in turns:
                        turns[cid]["agent"].aborted = True
                else:    # legacy/global abort: stop everything on this socket
                    for tinfo in turns.values():
                        tinfo["agent"].aborted = True
                    if build["agent"]:
                        build["agent"].aborted = True
                    for fut in pending_approvals.values():
                        if not fut.done():
                            fut.set_result(False)
    except WebSocketDisconnect:
        pass
    finally:
        state["clients"].discard(ws)
        for tinfo in turns.values():
            tinfo["agent"].aborted = True
        if build["agent"]:
            build["agent"].aborted = True
        for fut in pending_approvals.values():
            if not fut.done():
                fut.set_result(False)
