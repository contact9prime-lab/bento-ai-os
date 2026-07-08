"""AgentOS server: web UI, WebSocket event stream, REST API."""

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from . import config as cfgmod
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
    state.update(cfg=cfg, store=store, toolbox=toolbox, scheduler=scheduler,
                 mcp=mcp, telegram=telegram, clients=clients, broadcast=broadcast)
    asyncio.create_task(scheduler.run_forever())
    asyncio.create_task(mcp.start())
    asyncio.create_task(telegram.run_forever())
    store.log("system", "AgentOS started")

    # pick a default model if none is set
    if not cfg.get("default_model"):
        models = await providers.available_models(cfg)
        if models:
            cfg["default_model"] = models[0]["id"]
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
    aid = state["store"].save_app(body.get("name", ""), body.get("icon", "🧰"),
                                  body.get("description", ""), body.get("html", ""))
    state["store"].log("system", f"user app saved: {body.get('name', '')}")
    await state["broadcast"]({"type": "apps"})
    return {"id": aid}


@app.delete("/api/apps/{aid}")
async def api_delete_app(aid: str):
    state["store"].delete_app(aid)
    await state["broadcast"]({"type": "apps"})
    return {"ok": True}


@app.get("/api/apps/{aid}/page")
async def api_app_page(aid: str):
    from fastapi.responses import HTMLResponse
    a = state["store"].get_app(aid)
    if not a:
        return JSONResponse({"error": "not found"}, status_code=404)
    html = a["html"] or ""
    if not html.lstrip().lower().startswith(("<!doctype", "<html")):
        html = APP_SHELL.format(body=html)
    return HTMLResponse(html)


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
You are the AgentOS App Builder — an agent that builds and refines UI apps INSIDE this operating system.
Your ONE job this turn: produce a working app by calling the `create_app` tool.

Rules:
- Preferred: call create_app(name, icon, description, html) with COMPLETE self-contained HTML/CSS/JS.
- If you cannot call the tool, INSTEAD output the complete app as a single ```html fenced code block
  (nothing else needed) — the system will install it. Never reply with only a description.
- When refining an existing app, call create_app with the SAME name to update it in place.
- Match the OS dark theme: background #0e1116, text #e6ebf2, accents #5eead4 / #22d3ee, rounded corners.
- Keep all JS inline in a <script> tag. No external CDNs (they are blocked). Make it actually functional.
- Apps run in a same-origin iframe and CAN call the AgentOS REST API. Use it to make apps that DO things:
    GET  /api/system        -> {cpu, mem:{used_kb,total_kb}, disk, load, procs}
    GET  /api/tasks , /api/memories , /api/kg , /api/logs
    POST /api/chat  {text}  -> {content}   (one-shot agent turn — for AI-powered apps)
    POST /api/tool  {name, args}  -> {output}   (run ANY agent or MCP tool, e.g. run_command,
         fetch_url, or a connected mcp_* server tool — this is how an app gets live output from the OS)
- If the user asks what tools/MCP servers exist, you may call list-type tools first, then build.
- Apps can be full, LIVE apps — their JS may: poll on a schedule (setInterval), open a WebSocket to
  `ws(s)://{location.host}/ws` for realtime, call the REST API, run OS/MCP tools via POST /api/tool,
  and respond to user interaction (buttons, inputs). Build for the behaviour the user asks for.
- If the user wants it "on the desktop", "as a widget", "pinned", or "always visible", call
  `pin_widget(name)` after create_app so it lives on the desktop and restores on startup.
- After create_app succeeds, reply with one short sentence describing what you built.
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
    """(name, description, content) from a markdown skill file:
    first '# heading' is the name, first '>' quote or plain line is the description."""
    name, desc = fallback_name, ""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#") and name == fallback_name:
            name = s.lstrip("# ").strip() or fallback_name
            continue
        if not desc and not s.startswith("#"):
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
            for p in sorted(Path(tmp).rglob("*.md")):
                if p.name.upper() in ("README.MD", "LICENSE.MD", "CONTRIBUTING.MD", "CHANGELOG.MD"):
                    continue
                try:
                    text = p.read_text(errors="replace")
                except Exception:
                    continue
                if len(text.strip()) < 20 or len(text) > 100_000:
                    continue
                name, desc, content = _parse_skill_md(text, p.stem)
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
async def api_memories():
    return {"memories": state["store"].search_memories("", limit=200)}


@app.post("/api/memories")
async def api_add_memory(body: dict):
    mid = state["store"].add_memory(body.get("content", ""))
    return {"id": mid}


@app.delete("/api/memories/{mid}")
async def api_delete_memory(mid: str):
    state["store"].delete_memory(mid)
    return {"ok": True}


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

    agent = Agent(cfg, toolbox, model, emit, approver)
    result = await agent.run(history)
    store.add_message(cid, "assistant", result["content"], {"steps": result["steps"]})
    store.touch_conversation(cid)
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
    current: dict = {"agent": None, "task": None}

    async def send(event: dict):
        try:
            await ws.send_text(json.dumps(event))
        except Exception:
            pass

    async def approver(name: str, args: dict, reason: str) -> bool:
        aid = uuid.uuid4().hex[:8]
        fut = asyncio.get_event_loop().create_future()
        pending_approvals[aid] = fut
        await send({"type": "approval_request", "id": aid, "name": name,
                    "args": args, "reason": reason})
        try:
            return await asyncio.wait_for(fut, timeout=300)
        except asyncio.TimeoutError:
            return False
        finally:
            pending_approvals.pop(aid, None)

    async def run_chat(data: dict):
        cfg, store, toolbox = state["cfg"], state["store"], state["toolbox"]
        text = data.get("text", "").strip()
        if not text:
            return
        model = data.get("model") or cfg.get("default_model", "")
        cid = data.get("conversation_id")
        if not cid:
            cid = store.create_conversation(text[:60])
            await send({"type": "conversation", "id": cid, "title": text[:60]})
        history = _history_for(cid)
        store.add_message(cid, "user", text)
        history.append({"role": "user", "content": text})
        store.touch_conversation(cid)

        agent = Agent(cfg, toolbox, model, send, approver)
        current["agent"] = agent
        await send({"type": "turn_start", "conversation_id": cid, "model": model})
        try:
            result = await agent.run(history)
        except Exception as e:
            await send({"type": "error", "message": f"{type(e).__name__}: {e}"})
            result = {"content": "", "steps": []}
        finally:
            current["agent"] = None
        store.add_message(cid, "assistant", result["content"], {"steps": result["steps"]})
        store.touch_conversation(cid)
        tk = result.get("tokens") or {"input": 0, "output": 0}
        store.log("turn", text[:200], {"conversation_id": cid, "model": model,
                                       "steps": len(result["steps"]),
                                       "in": tk["input"], "out": tk["output"]})
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
        title = f"🧰 build: {existing['name'] if existing else prompt[:32]}"
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

        async def attempt(use_model):
            """Run one build turn; return (built_app_or_None, result)."""
            before = {a["id"] for a in store.list_apps()}
            agent = Agent(bcfg, toolbox, use_model, bemit, bapprove, extra_system=BUILDER_PERSONA,
                          tool_filter=["create_app", "read_file", "list_dir", "fetch_url", "system_info"])
            current["agent"] = agent
            try:
                res = await asyncio.wait_for(agent.run(history), timeout=240)
            except asyncio.TimeoutError:
                agent.aborted = True
                res = {"content": "", "steps": []}
            except Exception as e:
                await send({"type": "build_error", "message": f"{type(e).__name__}: {e}"})
                res = {"content": "", "steps": []}
            finally:
                current["agent"] = None
            apps = store.list_apps()
            new = [a for a in apps if a["id"] not in before]
            if not new:  # model wrote HTML as text instead of calling create_app → extract it
                html = _extract_html(res["content"]) or _extract_html_from_steps(res["steps"])
                if html:
                    if existing:
                        store.save_app(existing["name"], existing["icon"], existing["description"], html)
                    else:
                        nm = (prompt[:28].strip() or "App").title()
                        store.save_app(nm, "🧰", prompt[:80], html)
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
                if current["task"] and not current["task"].done():
                    await send({"type": "error", "message": "A turn is already running — stop it first."})
                else:
                    current["task"] = asyncio.create_task(run_chat(data))
            elif t == "build":
                if current["task"] and not current["task"].done():
                    await send({"type": "build_error", "message": "Something is already running — wait for it."})
                else:
                    current["task"] = asyncio.create_task(run_build(data))
            elif t == "approval":
                fut = pending_approvals.get(data.get("id", ""))
                if fut and not fut.done():
                    fut.set_result(bool(data.get("approved")))
            elif t == "abort":
                if current["agent"]:
                    current["agent"].aborted = True
                for fut in pending_approvals.values():
                    if not fut.done():
                        fut.set_result(False)
    except WebSocketDisconnect:
        pass
    finally:
        state["clients"].discard(ws)
        if current["agent"]:
            current["agent"].aborted = True
        for fut in pending_approvals.values():
            if not fut.done():
                fut.set_result(False)
