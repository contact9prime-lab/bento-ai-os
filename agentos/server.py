"""AgentOS server: web UI, WebSocket event stream, REST API."""

import asyncio
import contextlib
import json
import os
import re
import secrets
import socket
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from . import config as cfgmod
from . import fabric as fabricmod
from . import knowledge
from . import providers
from . import remote as remotemod
from .agent import Agent
from .mcp_client import MCP_AVAILABLE, MCPManager
from .memory import Store
from .policy import MAIN, PDP, Principal
from .scheduler import Scheduler
from .telegram import TelegramBridge
from .tools import ALWAYS_ASK, Toolbox
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
        # Wallpaper continuity in de mode: every wallpaper change (there are six
        # producers) funnels through this broadcast, so this is the one place to
        # keep the compositor background + swaylock in step with the shell.
        if event.get("type") == "wallpaper":
            try:
                from . import runmode as _rmw
                if _rmw.mode() != "de":
                    return
                from . import session as sessionmod
                wall = cfgmod.AGENTOS_HOME / "wallpaper.png"
                await asyncio.to_thread(
                    sessionmod.apply_wallpaper_live, str(wall) if wall.exists() else None)
            except Exception:
                pass

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
    trainforge = TrainForge(cfg, store, broadcast)
    toolbox.trainforge = trainforge
    toolbox.shell = shell_command  # the parity law: shell actions are tools too
    fabricmod.seed_builtins(cfg, store)
    state.update(cfg=cfg, store=store, toolbox=toolbox, scheduler=scheduler,
                 mcp=mcp, telegram=telegram, clients=clients, broadcast=broadcast,
                 fabric=control, pdp=pdp, trainforge=trainforge,
                 wayvnc=None,           # the interactive-control server, when running
                 pending_approvals={},  # aid -> {"fut","offer","ws"} — global approval broker
                 shell_pending={},      # cmd id -> Future — shell-control channel (see below)
                 app_tokens={},         # runtime token -> {"app_id","issued"} — app identity
                 pending_installs={},   # install_id -> staged app package awaiting consent
                 turns={},              # conversation_id -> {"agent","task","model"} — GLOBAL:
                                        # turns survive a page reload/reconnect; events broadcast
                 queues={},             # conversation_id -> [queued user message] — what the
                                        # user typed while a turn was running (see _queue_add)
                 build={"agent": None, "task": None, "cancel_requested": False,
                        "timed_out": False})  # App Studio build slot (global, one at a time)
    asyncio.create_task(scheduler.run_forever())
    asyncio.create_task(mcp.start())
    asyncio.create_task(telegram.run_forever())
    asyncio.create_task(knowledge.maintenance_loop(cfg, store, broadcast))
    # attention engine: notification triage (importance + "For you" digest),
    # batch-gated and model-idle-deferred — a no-op without a daemon or model
    from . import attention
    asyncio.create_task(attention.attention_loop(cfg, store,
                                                 lambda: state.get("notifd"), broadcast))

    async def wm_events():
        # In the AgentOS session, the compositor tells us the moment a window
        # opens/closes/focuses or an output changes — the UI listens for these
        # "wm" events instead of polling /api/windows every 3 seconds.
        #
        # This waits for the compositor instead of giving up when it isn't there
        # yet: the service is usually started by systemd at login, BEFORE (or
        # without) the AgentOS session, and the session then reuses this very
        # server. Attaching late is the difference between native windows
        # appearing in the shell and never showing up at all.
        from . import compositor as comp
        from . import runmode as _rm
        attached = False
        while True:
            if not comp.available():
                attached = False
                await asyncio.sleep(3)
                continue
            if not attached:
                attached = True
                await _on_compositor_attached()
            try:
                async for ev in comp.Compositor().subscribe():
                    # The compositor is the authority on where the user actually
                    # is. Focus landing on something that is not our shell means
                    # the desktop is no longer in front, however it got there —
                    # a click, sway's own Alt-Tab, a new window mapping. Without
                    # this, SHELL_RAISED stayed true forever and anchor_shell
                    # (which respects it) stopped putting the desktop back to
                    # being the base layer, so apps opened behind it.
                    if ev.get("change") == "focus":
                        con = ev.get("container") or {}
                        props = con.get("window_properties") or {}
                        is_shell = comp._is_shell_node(
                            con, con.get("app_id") or props.get("class") or "",
                            con.get("name") or "", _port_of(cfg))
                        if not is_shell:
                            comp.SHELL_RAISED[0] = False
                    if ev.get("change") in ("new", "close", "move", "floating"):
                        with contextlib.suppress(Exception):
                            comp.Compositor().anchor_shell(_port_of(cfg))
                    await broadcast({"type": "wm", **ev})
            except Exception:
                pass
            await asyncio.sleep(2)       # compositor hiccup or session ended — re-probe

    async def _on_compositor_attached():
        """We can see the compositor now — re-probe capabilities, tell the shell,
        and claim what only the session owner may claim."""
        from . import runmode as _rm
        try:
            from .platform import get_platform
            get_platform(refresh=True)
        except Exception:
            pass
        # An upgrade must actually reach the compositor. SWAY_CONF is generated
        # and was only ever written by install-session, so window rules shipped
        # after the user installed the session never arrived — the desktop looked
        # like it had no window controls and every app was stuck on top, because
        # on that machine it did and they were.
        if _rm.resolve(cfg)[0] == _rm.DE:
            try:
                from . import session as sessionmod
                changed, how = sessionmod.refresh_config()
                if changed:
                    state["store"].log("system", f"session config: {how}")
                    await broadcast({"type": "toast",
                                     "text": "Compositor settings updated for this "
                                             "version of AgentOS"})
            except Exception:
                pass
        if _rm.resolve(cfg)[0] == _rm.DE and not state.get("notifd"):
            try:
                from .notifications import NotificationDaemon
                nd = NotificationDaemon(broadcast)
                state["notifd"] = nd
                toolbox.notifd = nd
                nd.on_notification = scheduler.offer_notification
                asyncio.create_task(nd.start())
            except Exception:
                pass
        # The shell must be the tiled base layer filling the screen; app windows
        # float above it. Chromium's app_id is not ours under native Wayland, so
        # this is done by process identity rather than a window rule.
        try:
            from . import compositor as _c
            if _c.Compositor().anchor_shell(_port_of(cfg)):
                store.log("system", "shell anchored as the session's base layer")
        except Exception:
            pass
        store.log("system", "compositor attached — native window management is live")
        await broadcast({"type": "platform"})
    asyncio.create_task(wm_events())

    # When AgentOS is the session, nobody else can receive desktop
    # notifications — so we claim org.freedesktop.Notifications. Guarded by
    # run mode, never config: claiming it as a guest would steal GNOME's.
    from . import runmode
    if runmode.resolve(cfg)[0] == runmode.DE:
        from .notifications import NotificationDaemon
        notifd = NotificationDaemon(broadcast)
        state["notifd"] = notifd
        toolbox.notifd = notifd   # the agent can read the center (list_notifications)
        notifd.on_notification = scheduler.offer_notification  # feeds notification triggers
        asyncio.create_task(notifd.start())
    if runmode.resolve(cfg)[0] in (runmode.DE, runmode.KIOSK):
        # session start ≈ login: fire login triggers + the "while you were away"
        # briefing (and, best-effort, re-brief on logind session unlock)
        asyncio.create_task(attention.session_start(cfg, store,
                                                    lambda: state.get("notifd"),
                                                    scheduler, broadcast))
    from . import mcp_store as mcp_storemod
    mcp_storemod.ensure_index(store)  # warm the MCP catalog index in the background
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
    if state.get("notifd"):
        state["notifd"].stop()
    if "scheduler" in state:
        state["scheduler"].stop()
    if "telegram" in state:
        state["telegram"].stop()
    if "mcp" in state:
        await state["mcp"].stop()
    if "trainforge" in state:
        with contextlib.suppress(Exception):
            await state["trainforge"].stop()
    # never outlive the session that started it — an orphaned VNC server is an
    # unauthenticated door left open on the machine
    proc = state.get("wayvnc")
    if proc and proc.returncode is None:
        with contextlib.suppress(Exception):
            proc.terminate()


# ---------------------------------------------------------------------------
# UI + REST
# ---------------------------------------------------------------------------

# The desktop shell and the lock screen are the same URL with different answers,
# so neither may be cached: a browser that kept the lock screen would show it
# again after a successful sign-in (and, worse, could serve the desktop from
# cache after a sign-out).
NO_STORE = {"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"}


@app.get("/")
async def index():
    return FileResponse(UI_DIR / "index.html", headers=NO_STORE)


ASSET_TYPES = {".css": "text/css", ".js": "application/javascript",
               ".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp",
               ".woff2": "font/woff2", ".json": "application/json"}


@app.get("/manifest.webmanifest")
async def ui_manifest():
    """Add to Home Screen on iOS/Android. `display: standalone` is what strips
    the browser chrome, which is the whole reason a phone can feel like a client
    for this rather than a tab pointed at it."""
    return JSONResponse({
        "name": "AgentOS", "short_name": "AgentOS",
        "description": "Your machine, with a brain.",
        "start_url": "/", "scope": "/",
        "display": "standalone", "orientation": "any",
        "background_color": "#0b0d10", "theme_color": "#0b0d10",
        "icons": [
            {"src": "/assets/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/assets/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/assets/icon-maskable-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    }, media_type="application/manifest+json")


@app.get("/apple-touch-icon.png")
@app.get("/apple-touch-icon-precomposed.png")
async def ui_apple_icon():
    # iOS looks for this at the site root before it reads the manifest
    return FileResponse(UI_DIR / "assets" / "apple-touch-icon.png", media_type="image/png")


@app.get("/favicon.ico")
async def ui_favicon():
    return FileResponse(UI_DIR / "assets" / "icon-192.png", media_type="image/png")


@app.get("/assets/{name:path}")
async def ui_assets(name: str):
    # :path so subdirectories (assets/wallpapers/…) resolve; the realpath prefix
    # check below is what actually stops traversal, not the route pattern
    base = (UI_DIR / "assets").resolve()
    p = (base / name).resolve()
    if not str(p).startswith(str(base) + os.sep) or not p.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(p, media_type=ASSET_TYPES.get(p.suffix.lower(), "application/octet-stream"))


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


@app.get("/api/locale")
async def api_locale():
    """What AgentOS believes about where/when the user is: the saved locale, what
    the machine detects, and the timezone list the picker needs."""
    from . import localeinfo
    return {"locale": localeinfo.effective(state["cfg"]),
            "detected": localeinfo.detect(),
            "saved": state["cfg"].get("locale") or {},
            "countries": localeinfo.COUNTRIES,
            "timezones": localeinfo.timezones(),
            "describe": localeinfo.describe(state["cfg"])}


@app.post("/api/locale/apply")
async def api_locale_apply(body: dict):
    """Push the locale into the running session (de mode): LANG/LC_*/TZ that
    native apps launched from AgentOS inherit. Harmless elsewhere."""
    from . import localeinfo
    from . import runmode as _rm
    from . import session as sessionmod
    env = localeinfo.session_env(state["cfg"])
    wrote = sessionmod.write_locale_env(env)
    applied = False
    if _rm.mode() == "de":
        applied = sessionmod.apply_session_env(env)
    await state["broadcast"]({"type": "config"})
    return {"ok": True, "env": env, "written": str(wrote),
            "message": ("locale applied to this session" if applied
                        else "saved — it applies to the AgentOS session at next login")}


@app.get("/api/nightlight")
async def api_nightlight_get():
    """Warm the screen after dark — the display setting people notice by feeling
    tired rather than by looking at a panel."""
    import shutil as _sh
    nl = state["cfg"].get("nightlight") or {}
    return {"nightlight": nl, "available": bool(_sh.which("wlsunset")),
            "reason": "" if _sh.which("wlsunset") else
                      "wlsunset is not installed — install it from Components"}


@app.post("/api/nightlight")
async def api_nightlight_set(body: dict):
    import subprocess
    from . import session as sessionmod
    cfg = state["cfg"]
    nl = cfg.setdefault("nightlight", {})
    for k in ("enabled", "day_temp", "night_temp", "from", "to", "lat", "lon"):
        if k in (body or {}):
            nl[k] = body[k]
    cfgmod.save_config(cfg)
    # Rewrite the session config so it survives logout, and apply it right now.
    try:
        sessionmod.stage_nightlight(nl)
    except Exception as e:
        print(f"[nightlight] not persisted: {e}")
    applied = False
    try:
        subprocess.run(["pkill", "-x", "wlsunset"], capture_output=True, timeout=5)
        cmd = sessionmod.nightlight_cmd_text(nl)
        if cmd != ":" and os.environ.get("SWAYSOCK"):
            subprocess.Popen(["sh", "-c", cmd], start_new_session=True)
            applied = True
    except Exception:
        pass
    return {"ok": True, "nightlight": nl,
            "message": "night light on" if (nl.get("enabled") and applied)
                       else ("night light off" if not nl.get("enabled")
                             else "saved — it applies in the AgentOS session")}


@app.get("/api/input")
async def api_input_get():
    """Keyboard and pointer preferences — the half of "display settings" that is
    about how the machine answers your hands."""
    from . import runmode as _rm
    inp = state["cfg"].get("input") or {}
    return {"input": inp, "session": _rm.mode() == "de",
            "layouts": ["us", "gb", "in", "de", "fr", "es", "it", "ru", "jp", "cn", "br", "se"]}


@app.post("/api/input")
async def api_input_set(body: dict):
    from . import session as sessionmod
    cfg = state["cfg"]
    inp = cfg.setdefault("input", {})
    for section in ("keyboard", "touchpad"):
        if isinstance(body.get(section), dict):
            inp.setdefault(section, {}).update(body[section])
    cfgmod.save_config(cfg)
    path = sessionmod.write_input_config(inp)
    applied = sessionmod.apply_dropins()
    return {"ok": True, "written": str(path),
            "message": "applied to this session" if applied
                       else "saved — it applies when you next log into AgentOS"}


@app.post("/api/shell/action")
async def api_shell_action(body: dict):
    """Run a named shell action (the shortcut table's actions). This is what the
    compositor's keybindings curl in session mode, so a shortcut still works
    while a native window holds the keyboard."""
    action = str((body or {}).get("action") or "")[:40]
    if not action:
        return JSONResponse({"error": "action required"}, status_code=400)
    # Most shortcuts are only useful if you can SEE the desktop. In session mode
    # native windows float above the shell, so summoning the prompt bar behind a
    # browser would look like nothing happened — bring the shell forward first.
    if action in SHELL_ACTIONS_NEEDING_FOCUS:
        from . import host
        from . import runmode as _rm
        if _rm.mode() == "de":
            try:
                host.raise_shell(True)
            except Exception:
                pass
    ok, data = await shell_command("shell_action", {"target": action})
    return {"ok": ok, "result": data}


# Actions that are meaningless unless the AgentOS desktop is in front. Stopping
# the agent is deliberately NOT here: it must never steal focus mid-task.
SHELL_ACTIONS_NEEDING_FOCUS = frozenset({
    "power",
    "omnibar.focus", "omnibar.focus2", "palette", "expose", "expose.f3",
    "windows.arrange", "chat.open", "chat.new", "settings", "help", "deck",
    "copilot", "terminal", "voice", "desktop.prev", "desktop.next",
    "desktop.move.prev", "desktop.move.next", "switcher",
})


@app.post("/api/wm/desktop")
async def api_wm_desktop(body: dict):
    """Switch desktops for real: the sway workspace moves too, and the shell
    comes along. Without this, AgentOS desktops were a page-level idea and every
    external window appeared on all of them."""
    from . import host
    ok, msg = host.goto_desktop(int(body.get("desktop", 1)))
    return {"ok": ok, "message": msg}


@app.post("/api/shell/wake")
async def api_shell_wake(body: dict | None = None):
    """The screen is yours again — after a resume from suspend, or an unlock.

    Both used to leave the machine unusable: the outputs stayed powered off and
    the shell kept neither focus nor its place as the base layer, so there was no
    way back to the desktop. Powering the outputs on is swayidle's job (it runs
    before calling this); ours is to put the desktop back together.
    """
    from . import host
    from . import runmode as _rm
    done = []
    if _rm.mode() == "de":
        from . import compositor as comp
        try:
            c = comp.Compositor()
            if c.anchor_shell(comp.shell_port()):
                done.append("anchored")
            c.focus_shell()
            done.append("focused")
        except Exception as e:
            done.append(f"compositor: {e}")
    # A page that was hidden for hours may hold a dead websocket and a stale
    # clock; telling it to repaint is cheaper than making the user find Ctrl+R.
    await state["broadcast"]({"type": "wake"})
    return {"ok": True, "did": done}


@app.post("/api/shell/reload")
async def api_shell_reload(body: dict | None = None):
    """Reload the desktop itself. The shell is a page: a new build is on disk but
    not on screen until it reloads, and asking the user to find Ctrl+R on their
    own desktop is not a deploy step."""
    await state["broadcast"]({"type": "reload",
                              "delay": int((body or {}).get("delay", 400))})
    return {"ok": True}


@app.post("/api/shell/raise")
async def api_shell_raise(body: dict | None = None):
    """Put the AgentOS desktop in front of (or back behind) the native windows."""
    from . import host
    on = True if body is None else bool(body.get("on", True))
    ok, msg = host.raise_shell(on)
    return {"ok": ok, "message": msg}


@app.post("/api/shell/sui")
async def api_shell_sui(request: Request, body: dict | None = None):
    """The desktop declaring that it is drawn by the native session host.

    Only the layer-shell host injects the bridge that makes this call possible,
    so receiving it is proof the desktop is a BACKGROUND-layer surface rather
    than a Chromium window. Once known, every anchor/raise/lower in the
    compositor layer becomes a no-op — the stacking order is correct by
    construction, and there is no window to shuffle.

    Loopback only: this changes how the server manages the session's windows, so
    a remote browser must not be able to claim it. A phone connected to this
    desktop is a viewer of the session, never its host.
    """
    if not remotemod.is_loopback(_client_addr(request)):
        return JSONResponse({"error": "only the machine's own desktop can claim this"},
                            status_code=403)
    from . import compositor as comp
    on = True if body is None else bool(body.get("on", True))
    was = comp.SUI_HOST[0]
    comp.SUI_HOST[0] = on
    if on and not was:
        state["store"].log("system", "desktop is a native layer-shell surface "
                                     "(session UI) — window stacking is native")
    return {"ok": True, "sui": on}


@app.post("/api/shortcuts/apply")
async def api_shortcuts_apply(body: dict):
    """Write the session-level shortcuts into the compositor and reload it.

    Only meaningful in `de` mode; elsewhere it reports that plainly instead of
    pretending. Bindings are generated into a sway drop-in (never the generated
    main config), each one curling /api/shell/action."""
    from . import runmode as _rm
    from . import session as sessionmod
    if _rm.mode() != "de":
        return {"ok": False, "message": "not running as the desktop session — "
                                        "in-app shortcuts still work"}
    shortcuts = state["cfg"].get("shortcuts") or {}
    written = sessionmod.write_shortcut_bindings(shortcuts, _port_of(state["cfg"]))
    return {"ok": bool(written), "message": (f"{written} session shortcuts applied"
                                             if written else "no session shortcuts to apply")}


def _port_of(cfg: dict) -> int:
    try:
        return int(cfg.get("port", 8321))
    except Exception:
        return 8321


@app.get("/api/search")
async def api_search(q: str = "", limit: int = 8):
    """Semantic search over the workspace + docs (Files app, palette). Falls back
    to substring ranking when no embedding model is available — always answers."""
    from . import search as searchmod
    try:
        results = await searchmod.query(state["cfg"], state["store"], q, limit=int(limit))
    except Exception as e:
        return {"results": [], "error": str(e)}
    return {"results": results}


@app.post("/api/intent")
async def api_intent(body: dict):
    """Palette fallback: classify a free-text command into a direct shell action.
    Returns {action, target, label, hint} — action 'chat' means "no direct action,
    let the agent have it". Deliberately tiny and fast: one small completion,
    tight timeout, never an agent loop."""
    q = (body.get("q") or "").strip()[:200]
    if not q:
        return {"action": "chat"}
    from .tools import BUILTIN_THEMES
    apps = "chat, files, terminal, store, settings, syssettings, themes, personalize, " \
           "memory, kg, studio, mission, taskmgr, models, docs"
    prompt = (
        "Classify this desktop command into ONE action. Answer ONLY compact JSON, no prose.\n"
        'Schema: {"action":"open_app|close_app|focus_app|switch_desktop|apply_theme|chat",'
        '"target":"<string>","label":"<verb phrase for a menu row>"}\n'
        f"Known apps: {apps}. Known themes: {', '.join(BUILTIN_THEMES)}.\n"
        'Use "chat" when the request needs reasoning, content, or anything beyond those actions.\n'
        f"Command: {q}")
    try:
        raw = await asyncio.wait_for(
            providers.complete(state["cfg"], state["cfg"].get("default_model", ""),
                               prompt, system="You classify desktop intents."),
            timeout=6)
        m = re.search(r"\{.*\}", raw, re.S)
        d = json.loads(m.group(0)) if m else {}
        action = d.get("action") or "chat"
        if action not in ("open_app", "close_app", "focus_app", "switch_desktop",
                          "apply_theme", "chat"):
            action = "chat"
        return {"action": action, "target": str(d.get("target") or "")[:80],
                "label": str(d.get("label") or "")[:80], "hint": "suggested action"}
    except Exception:
        return {"action": "chat"}


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


@app.get("/api/native/store")
async def api_native_store(q: str = "", limit: int = 40):
    """Search the machine's own application catalogue.

    A desktop you cannot install software on is a demo. This asks appstream /
    flatpak / apt — whichever the machine has — and never ships or mirrors
    anything itself.
    """
    from . import appstore
    if not q:
        return {"results": [], "backends": appstore.backends(), "message": ""}
    return await appstore.search(q, max(1, min(int(limit or 40), 100)))


@app.post("/api/native/store")
async def api_native_store_act(request: Request, body: dict):
    """Install or remove a native application.

    Loopback only. Installing software is a change to the machine, and a browser
    somewhere else — even one holding a valid remote-access session — is not the
    right place to authorise it. The user is asked in the UI first; the exact
    command is always returned.
    """
    if not remotemod.is_loopback(_client_addr(request)):
        return JSONResponse(
            {"error": "installing software is only allowed from the machine itself"},
            status_code=403)
    from . import appstore
    action = str((body or {}).get("action") or "install")
    pkg = str((body or {}).get("id") or "")
    backend = str((body or {}).get("backend") or "")
    res = await appstore.act(action, pkg, backend)
    state["store"].log("system",
                       f"{action} {pkg} ({backend or 'auto'}): "
                       f"{'ok' if res.get('ok') else res.get('message', '')[:200]}",
                       {"ok": bool(res.get("ok")), "command": res.get("command", "")})
    if res.get("ok"):
        # a new .desktop entry means the deck's System apps group just changed
        await state["broadcast"]({"type": "native_apps"})
    return res


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
    """Launch a host application.

    In session mode this waits for the app's window to actually map (see
    compositor.launch_and_focus), so it runs in a thread — blocking the event
    loop for the seconds a heavy app takes to start would freeze every other
    client, including the desktop that is waiting for this answer.
    """
    from . import host
    app_id = body.get("id", "")
    ok, msg = await asyncio.to_thread(host.launch_app, app_id)
    state["store"].log("system",
                       f"launched native app: {app_id}" if ok
                       else f"native app failed to launch: {app_id} — {msg}",
                       {"ok": ok})
    if ok:
        # the taskbar should show the new window now, not on the next poll
        await state["broadcast"]({"type": "wm"})
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


@app.post("/api/windows/move")
async def api_windows_move(body: dict):
    from . import host
    ok, msg = host.move_window_to_workspace(body.get("id", ""),
                                            str(body.get("workspace", "")))
    return {"ok": ok, "message": msg}


@app.post("/api/windows/floating")
async def api_windows_floating(body: dict):
    from . import host
    ok, msg = host.set_window_floating(body.get("id", ""), bool(body.get("floating", True)))
    return {"ok": ok, "message": msg}


def _window_id(body: dict) -> str:
    """Accept a con_id or the literal "focused".

    The compositor keybindings cannot know an id, so they say "focused" and the
    server resolves it — which is also what a person means by "minimise this"."""
    wid = str((body or {}).get("id", "") or "")
    if wid != "focused":
        return wid
    from . import host
    for w in (host.list_windows().get("windows") or []):
        if w.get("focused") and not w.get("minimized"):
            return str(w.get("id") or "")
    return ""


@app.post("/api/windows/minimize")
async def api_windows_minimize(body: dict):
    """Minimise a native window. sway has no minimise of its own — the window is
    parked in the scratchpad, which is exactly "hidden but alive", and stays in
    the taskbar so it can be brought back."""
    from . import host
    ok, msg = host.minimize_window(_window_id(body))
    return {"ok": ok, "message": msg}


@app.post("/api/windows/restore")
async def api_windows_restore(body: dict):
    from . import host
    ok, msg = host.restore_window(_window_id(body))
    return {"ok": ok, "message": msg}


@app.post("/api/windows/maximize")
async def api_windows_maximize(body: dict):
    """Fill the desk but leave the menu bar reachable — which is what people mean
    by maximize, and a different thing from full screen."""
    from . import host
    ok, msg = host.maximize_window(_window_id(body), bool(body.get("maximize", True)))
    return {"ok": ok, "message": msg}


@app.post("/api/windows/fullscreen")
async def api_windows_fullscreen(body: dict):
    from . import host
    on = body.get("fullscreen")
    ok, msg = host.fullscreen_window(_window_id(body),
                                     None if on is None else bool(on))
    return {"ok": ok, "message": msg}


@app.post("/api/windows/snap")
async def api_windows_snap(body: dict):
    """Snap a native window to half or a quarter of the usable screen.

    AgentOS's own windows have snapped to edges from the start; native ones could
    only be dragged, which made them second-class windows on their own desktop.
    Zones: left/right/top/bottom, tl/tr/bl/br, center, full.
    """
    from . import host
    ok, msg = host.snap_window(_window_id(body), str((body or {}).get("zone") or "left"))
    if ok:
        await state["broadcast"]({"type": "wm"})
    return {"ok": ok, "message": msg}


@app.post("/api/windows/showdesktop")
async def api_windows_show_desktop(body: dict | None = None):
    """The escape hatch: hide every native window and put the keyboard back on
    the AgentOS desktop. Without it, a native window covering the screen with no
    working minimise leaves the user stuck."""
    from . import host
    ok, msg = host.show_desktop()
    return {"ok": ok, "message": msg}


SWITCHER: dict = {"open": False, "ring": [], "idx": 0}


@app.post("/api/windows/switcher")
async def api_windows_switcher(body: dict):
    """The Alt-Tab overlay, driven by a sway binding mode.

    A single keypress could switch windows but never SHOW anything — the shell is
    behind the native windows, so a HUD it draws is invisible. Holding Alt puts
    sway in a mode: open raises the desktop so the switcher can be seen, step
    moves the selection, and releasing Alt commits and drops the desktop back.
    """
    from . import host
    action = str((body or {}).get("action") or "")
    step = -1 if (body or {}).get("direction") == "prev" else 1

    if action == "open":
        wins = (host.list_windows().get("windows") or [])
        ring = [{"id": "", "shell": True, "title": "Desktop", "app": "agentos"}]
        ring += [w for w in wins if not w.get("minimized")]
        # start on the entry after wherever the user is, like every other Alt-Tab
        cur = next((i for i, w in enumerate(ring) if w.get("focused")), 0)
        SWITCHER.update({"open": True, "ring": ring,
                         "idx": (cur + step) % len(ring) if len(ring) > 1 else 0})
        host.raise_shell(True)
    elif action == "step" and SWITCHER["open"]:
        n = len(SWITCHER["ring"]) or 1
        SWITCHER["idx"] = (SWITCHER["idx"] + step) % n
    elif action in ("commit", "cancel"):
        ring, idx = SWITCHER["ring"], SWITCHER["idx"]
        SWITCHER.update({"open": False, "ring": [], "idx": 0})
        await state["broadcast"]({"type": "switcher", "open": False})
        if action == "commit" and ring:
            target = ring[idx]
            if target.get("shell"):
                host.raise_shell(True)          # stay on the desktop
            else:
                host.raise_shell(False)         # get out of the app's way
                host.focus_window(str(target.get("id") or ""))
        else:
            host.raise_shell(False)
        return {"ok": True, "closed": True}

    await state["broadcast"]({"type": "switcher", "open": SWITCHER["open"],
                              "ring": SWITCHER["ring"], "idx": SWITCHER["idx"]})
    return {"ok": True, "idx": SWITCHER["idx"], "count": len(SWITCHER["ring"])}


@app.post("/api/windows/cycle")
async def api_windows_cycle(body: dict):
    """Alt-Tab. The generated sway config binds Mod1+Tab to this endpoint, so
    cycling works regardless of which window holds the keyboard."""
    from . import host
    ok, msg = host.cycle_focus("prev" if body.get("direction") == "prev" else "next")
    return {"ok": ok, "message": msg}


# ---- workspaces & displays: real, compositor-backed in the AgentOS session ----

@app.get("/api/wm/workspaces")
async def api_wm_workspaces():
    from . import host
    return host.workspaces()


@app.post("/api/wm/workspaces")
async def api_wm_workspace_switch(body: dict):
    from . import host
    ok, msg = host.switch_workspace(str(body.get("workspace", "")))
    return {"ok": ok, "message": msg}


@app.get("/api/wm/outputs")
async def api_wm_outputs():
    from . import host
    return host.outputs()


@app.post("/api/wm/outputs")
async def api_wm_output_configure(body: dict):
    """Configure one display. Body: {name, mode?, scale?, transform?, position?, enabled?}.
    Values are validated by the compositor itself and its error comes back verbatim."""
    from . import host
    name = body.get("name", "")
    if not name:
        return JSONResponse({"error": "output 'name' is required"}, status_code=400)
    kw = {}
    if body.get("mode"):
        kw["mode"] = str(body["mode"])
    if body.get("scale") is not None:
        kw["scale"] = float(body["scale"])
    if body.get("transform"):
        kw["transform"] = str(body["transform"])
    if body.get("position") is not None:
        p = body["position"]
        kw["position"] = (int(p.get("x", 0)), int(p.get("y", 0)))
    if body.get("enabled") is not None:
        kw["enabled"] = bool(body["enabled"])
    ok, msg = host.configure_output(name, **kw)
    # A display setting must outlive the session that made it: applying a mode
    # over IPC lasts until logout, so the accepted layout is also written to a
    # compositor drop-in — the same promise GNOME's Displays panel makes.
    if ok:
        try:
            from . import session as sessionmod
            cfg = state["cfg"]
            outs = cfg.setdefault("displays", {})
            saved = outs.setdefault(name, {})
            saved.update({k: v for k, v in body.items() if k != "name"})
            if isinstance(saved.get("position"), dict):
                p = saved["position"]
                saved["position"] = f"{int(p.get('x', 0))},{int(p.get('y', 0))}"
            cfgmod.save_config(cfg)
            sessionmod.write_output_config([{"name": n, **v} for n, v in outs.items()])
        except Exception as e:
            print(f"[displays] layout not persisted: {e}")
    return {"ok": ok, "message": msg}


@app.get("/api/platform")
async def api_platform(request: Request):
    """What this machine can actually do, and which desktop mode we're in.

    The UI renders from this instead of branching on the operating system: every
    capability reports whether it's available and, when it isn't, a sentence
    explaining why plus the optional component that would fix it.

    `remote_client` is per-request, not per-machine: it says whether THIS browser
    is somewhere else. It matters because native apps are drawn by the compositor
    onto the host's physical display — they are not part of the page — so a phone
    that launches one gets a taskbar entry and no pixels unless it is told why.
    """
    from . import host
    state_ = host.platform_state()
    state_["remote_client"] = not remotemod.is_loopback(_client_addr(request))
    state_["hostname"] = socket.gethostname()
    # Is the desktop a native layer-shell surface right now, and could it be?
    # The UI shows this in About/System Settings, and the doctor uses the second
    # half to print the one apt line that upgrades a Chromium session to a real
    # desktop surface.
    from . import compositor as comp
    from . import shellhost
    state_["sui"] = bool(comp.SUI_HOST[0])
    state_["sui_available"] = shellhost.available()
    state_["sui_install_hint"] = "" if state_["sui_available"] else shellhost.install_hint()
    return state_


# ---------------------------------------------------------------------------
# Interactive control of the real screen.
#
# The Host Screen view is a picture — enough to see a native app, not to use one.
# Using one means streaming pixels AND sending input back, which is remote-desktop
# work; wayvnc does it properly for wlroots, so AgentOS starts it rather than
# reinventing it.
#
# It binds LOOPBACK ONLY, always. wayvnc's default security type is "None" — no
# password — so putting it on the network would hand the machine to anyone who
# can reach the port, which is strictly worse than everything else in this
# system. Reach it over the SSH tunnel or the VPN that docs/remote-access.md
# already recommends. Anyone who wants it exposed can configure wayvnc's own
# auth and run it themselves; AgentOS will not do that quietly on their behalf.
# ---------------------------------------------------------------------------

VNC_PORT = 5900


def _vnc_running() -> bool:
    proc = state.get("wayvnc")
    return bool(proc and proc.returncode is None)


@app.get("/novnc/{path:path}")
async def novnc_asset(path: str):
    """Serve the noVNC client that is already installed on this machine.

    AgentOS bundles no part of it. Served rather than linked because the page
    imports it as an ES module, and a module can only be imported from an origin
    the browser is already on.

    The path is resolved and then checked to be INSIDE the noVNC directory. Not a
    string check for "..": a symlink or an encoded separator makes that kind of
    filter wrong in a way that is hard to see, and this route reads files.
    """
    from . import remotedesktop as rd
    base = rd.novnc_dir()
    if not base:
        return JSONResponse({"error": "noVNC is not installed"}, status_code=404)
    root = os.path.realpath(base)
    target = os.path.realpath(os.path.join(root, path))
    if not (target == root or target.startswith(root + os.sep)) or not os.path.isfile(target):
        return JSONResponse({"error": "not found"}, status_code=404)
    ext = os.path.splitext(target)[1].lower()
    mt = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
          ".html": "text/html", ".json": "application/json", ".svg": "image/svg+xml",
          ".png": "image/png", ".ico": "image/x-icon", ".woff2": "font/woff2",
          }.get(ext, "application/octet-stream")
    return FileResponse(target, media_type=mt,
                        headers={"Cache-Control": "max-age=86400"})


@app.get("/remote-desktop")
async def remote_desktop_page(request: Request):
    """The real screen, on a phone, in the browser — no VNC app to install.

    Its own page rather than a window in the desktop: on a phone you want the
    whole screen for the remote machine, not the AgentOS dock drawn over it.
    Reaching this page already required the AgentOS passphrase (the remote-access
    gate runs as middleware), which is exactly the authentication wayvnc lacks.
    """
    from . import remotedesktop as rd
    have = rd.available()
    if not have["novnc"]:
        return HTMLResponse(
            "<body style='background:#0b0d10;color:#e6ebf2;font:15px system-ui;padding:34px'>"
            "<h2>Remote Desktop needs the noVNC client</h2>"
            "<p>It is a distribution package — AgentOS does not bundle it. Install it from "
            "<b>System Settings &rarr; Components</b>, or run:</p>"
            "<pre style='background:#151920;padding:12px;border-radius:8px'>sudo apt install novnc</pre>"
            "</body>", status_code=503, headers=NO_STORE)
    if not _vnc_running():
        return HTMLResponse(
            "<body style='background:#0b0d10;color:#e6ebf2;font:15px system-ui;padding:34px'>"
            "<h2>Remote Desktop is switched off</h2>"
            "<p>Turn it on at the machine: <b>System Settings &rarr; Remote access &rarr; "
            "Remote Desktop</b>, or the Host Screen app's <b>Take control</b> panel. "
            "Then reload this page.</p></body>", status_code=503, headers=NO_STORE)
    return HTMLResponse(rd.page("/ws/vnc", socket.gethostname()), headers=NO_STORE)


@app.get("/api/screen/control")
async def api_screen_control_status():
    import shutil as _sh
    from . import remotedesktop as rd
    have = rd.available()
    return {
        "installed": bool(_sh.which("wayvnc")),
        "running": _vnc_running(),
        "host": "127.0.0.1", "port": VNC_PORT,
        "component": "wayvnc",
        # The browser client, which is what makes this reachable from a phone
        # without installing anything on the phone.
        "novnc": have["novnc"],
        "novnc_component": "novnc",
        "web_url": "/remote-desktop" if have["novnc"] else "",
        "note": ("wayvnc has no password of its own, so AgentOS only ever binds it to "
                 "127.0.0.1. Reach it through an SSH tunnel or your VPN."),
        "tunnel": f"ssh -L {VNC_PORT}:127.0.0.1:{VNC_PORT} {os.environ.get('USER') or 'you'}@{socket.gethostname()}",
    }


@app.post("/api/screen/control")
async def api_screen_control(body: dict):
    """{action: "start" | "stop"} — run wayvnc against this compositor."""
    import shutil as _sh
    from . import runmode as _rm
    action = (body or {}).get("action", "")
    if action == "stop":
        proc = state.get("wayvnc")
        if proc and proc.returncode is None:
            proc.terminate()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=5)
        state["wayvnc"] = None
        state["store"].log("system", "interactive remote control stopped")
        return {"ok": True, "running": False}
    if action != "start":
        return JSONResponse({"error": "action must be start or stop"}, status_code=400)
    if _rm.mode() != "de":
        return JSONResponse({"error": "interactive control needs the AgentOS Wayland session"},
                            status_code=503)
    if not _sh.which("wayvnc"):
        return JSONResponse({"error": "wayvnc is not installed", "component": "wayvnc"},
                            status_code=503)
    if _vnc_running():
        return {"ok": True, "running": True, "port": VNC_PORT}
    proc = await asyncio.create_subprocess_exec(
        "wayvnc", "127.0.0.1", str(VNC_PORT),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    await asyncio.sleep(1.0)                      # let it bind or fail loudly
    if proc.returncode is not None:
        err = (await proc.stderr.read())[-300:].decode(errors="replace")
        return JSONResponse({"error": err.strip() or "wayvnc exited immediately"},
                            status_code=500)
    state["wayvnc"] = proc
    # Nudge the compositor into repainting the whole output. sway only re-renders
    # DAMAGED regions, so on a desktop that has been sitting still — which is
    # exactly the state you find it in when you reach for your phone — the first
    # frame a new client receives can be missing everything that had not changed
    # recently. The desktop's own surface is the usual casualty: you connect and
    # see the app you launched floating on black. One repaint costs nothing and
    # makes the first frame the whole screen.
    #
    # It re-applies the background the session already set, rather than setting a
    # colour: re-sending the same value damages the whole output and changes
    # nothing, where a fixed colour would quietly throw away the user's wallpaper.
    with contextlib.suppress(Exception):
        from . import compositor as _c
        wall = cfgmod.AGENTOS_HOME / "wallpaper.png"
        _c.Compositor().command(
            f"output * bg '{wall}' fill" if wall.is_file()
            else "output * bg #0b0d10 solid_color")
    state["store"].log("system", f"interactive remote control started on 127.0.0.1:{VNC_PORT}")
    return {"ok": True, "running": True, "port": VNC_PORT}


@app.get("/api/screen/frame")
async def api_screen_frame(scale: float = 1.0):
    """One frame of the host's actual screen, as PNG.

    This is the only way a remote client can see a native window: those windows
    live on the compositor's output, not in the HTML the browser loaded. It is a
    still, not a stream — enough to answer "did my app open, and what is it
    showing" without pulling a video pipeline into the OS. For interactive
    control of the real screen, run a VNC server for wlroots (wayvnc) alongside.
    """
    import shutil as _sh
    if not _sh.which("grim"):
        return JSONResponse({"error": "screen capture needs grim (Wayland session only)"},
                            status_code=503)
    argv = ["grim"]
    if scale and scale != 1.0:
        argv += ["-s", str(max(0.1, min(1.0, scale)))]
    argv += ["-t", "png", "-"]
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=15)
    except asyncio.TimeoutError:
        proc.kill()
        return JSONResponse({"error": "screen capture timed out"}, status_code=504)
    if proc.returncode != 0 or not out:
        return JSONResponse({"error": (err or b"").decode(errors="replace")[:200]
                             or "screen capture failed"}, status_code=500)
    return Response(content=out, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


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
    # Hardware keys send a STEP, not an absolute level — the compositor binds
    # XF86AudioRaise/Lower/Mute to these so the change shows in AgentOS's own UI.
    cur = host.get_volume()
    if body.get("volume_step") is not None:
        now = cur.get("volume")
        if now is None:
            return cur
        host.set_volume(percent=max(0, min(100, int(now) + int(body["volume_step"]))))
    elif body.get("mute_toggle"):
        host.set_volume(mute=not cur.get("muted"))
    else:
        host.set_volume(percent=body.get("volume"), mute=body.get("mute"))
    out = host.get_volume()
    with contextlib.suppress(Exception):
        await state["broadcast"]({"type": "control", **out})
    return out


# ---- DE-mode system controls (hostctl: D-Bus daemons + PipeWire) ----------------
#
# These are what replace gnome-control-center when AgentOS is the session. They
# work in hosted mode too where the daemon allows it; the UI decides what to
# show from /api/platform capabilities, and every failure comes back as a
# sentence, not a stack trace.

def _hostctl_error(e: Exception, status: int = 503) -> JSONResponse:
    return JSONResponse({"error": str(e)}, status_code=status)


@app.get("/api/net/wifi")
async def api_wifi(rescan: int = 1):
    from .hostctl import HostCtlError, network
    try:
        st = await network.status()
        st["networks"] = await network.wifi_scan(rescan=bool(rescan)) if st["wifi_enabled"] else []
        for n in st["networks"]:
            n.pop("_ap_path", None)          # D-Bus paths stay server-side
        return st
    except HostCtlError as e:
        return _hostctl_error(e)


@app.post("/api/net/wifi")
async def api_wifi_set(body: dict):
    from .hostctl import HostCtlError, network
    action = (body.get("action") or "").strip()
    try:
        if action == "join":
            await network.wifi_join(body.get("ssid", ""), body.get("psk") or None)
            state["store"].log("system", f"wifi: joined '{body.get('ssid','')}'")
        elif action == "forget":
            if not await network.wifi_forget(body.get("ssid", "")):
                return JSONResponse({"error": "no saved network with that name"}, 404)
            state["store"].log("system", f"wifi: forgot '{body.get('ssid','')}'")
        elif action in ("enable", "disable"):
            await network.set_wifi_enabled(action == "enable")
        elif action == "airplane":
            await network.set_networking_enabled(not bool(body.get("on", True)))
            state["store"].log("system",
                               f"airplane mode {'on' if body.get('on', True) else 'off'}")
        else:
            return JSONResponse({"error": f"unknown wifi action '{action}'"}, 400)
        return {"ok": True}
    except HostCtlError as e:
        return _hostctl_error(e)


@app.get("/api/bt")
async def api_bt():
    from .hostctl import HostCtlError, bluetooth
    try:
        return await bluetooth.tree()
    except HostCtlError as e:
        return _hostctl_error(e)


@app.post("/api/bt")
async def api_bt_set(body: dict):
    from .hostctl import HostCtlError, bluetooth
    action = (body.get("action") or "").strip()
    try:
        if action == "power":
            await bluetooth.set_powered(body.get("adapter", ""), bool(body.get("on", True)))
        elif action == "discover":
            await bluetooth.set_discovering(body.get("adapter", ""), bool(body.get("on", True)))
        elif action in ("pair", "connect", "disconnect", "trust", "untrust", "remove"):
            await bluetooth.device_action(body.get("device", ""), action)
            state["store"].log("system", f"bluetooth: {action} {body.get('device','')}")
        else:
            return JSONResponse({"error": f"unknown bluetooth action '{action}'"}, 400)
        return {"ok": True}
    except HostCtlError as e:
        return _hostctl_error(e)


@app.get("/api/brightness")
async def api_brightness():
    from .hostctl import brightness
    return await brightness.state()


@app.post("/api/brightness")
async def api_brightness_set(body: dict):
    from .hostctl import HostCtlError, brightness
    try:
        pct = body.get("percent")
        if body.get("step") is not None:           # brightness keys send a delta
            cur = 50
            with contextlib.suppress(Exception):
                bl = brightness.backlights()
                cur = int(bl[0]["percent"]) if bl else 50
            pct = max(1, min(100, cur + int(body["step"])))
        await brightness.set_level(str(body.get("name", "")), int(pct if pct is not None else 50),
                                   kind=str(body.get("kind", "")))
        with contextlib.suppress(Exception):
            await state["broadcast"]({"type": "control", "brightness": pct})
        return {"ok": True, "percent": pct}
    except (HostCtlError, ValueError) as e:
        return _hostctl_error(e)


@app.get("/api/audio/devices")
async def api_audio_devices():
    from .hostctl import HostCtlError, audio
    try:
        return audio.devices()
    except HostCtlError as e:
        return _hostctl_error(e)


@app.post("/api/audio/devices")
async def api_audio_set(body: dict):
    from .hostctl import HostCtlError, audio
    try:
        if body.get("action") == "default":
            audio.set_default(int(body.get("id", -1)))
        elif body.get("action") == "volume":
            audio.set_node_volume(int(body.get("id", -1)), int(body.get("percent", 50)))
        else:
            return JSONResponse({"error": "action must be 'default' or 'volume'"}, 400)
        return {"ok": True}
    except (HostCtlError, ValueError) as e:
        return _hostctl_error(e)


@app.get("/api/power/profile")
async def api_power_profile():
    from .hostctl import HostCtlError, upower
    try:
        return await upower.get_profile()
    except HostCtlError as e:
        return _hostctl_error(e)


@app.post("/api/power/profile")
async def api_power_profile_set(body: dict):
    from .hostctl import HostCtlError, upower
    try:
        await upower.set_profile(str(body.get("profile", "")))
        return {"ok": True}
    except HostCtlError as e:
        return _hostctl_error(e)


# ---- Optional components: can't ship it, user can add it ------------------------

@app.get("/api/components")
async def api_components():
    from . import components
    return {"components": components.catalog()}


@app.post("/api/components")
async def api_components_install(body: dict):
    """The UI shows the licence and asks before calling this — same contract as
    the MCP store's install: this endpoint IS the consequence of a yes."""
    from . import components
    cid = (body.get("id") or "").strip()
    if not cid:
        return JSONResponse({"error": "component 'id' is required"}, status_code=400)
    result = await components.install(cid)
    if result["ok"] and result["command"]:
        state["store"].log("system",
                           f"component installed with consent: {cid} ({result['command']})")
        await state["broadcast"]({"type": "config"})
    return result


# ---- Notification center (fed by the daemon in DE mode) -------------------------

@app.get("/api/notifications")
async def api_notifications():
    d = state.get("notifd")
    if not d:
        return {"available": False, "items": [], "unread": 0, "dnd": False,
                "reason": "Your desktop environment shows notifications in hosted mode."}
    from . import attention
    st = d.state()  # items carry additive per-item `importance` once triage scored them
    dg = attention.digest_state(state["store"])
    if dg:
        st["digest"] = dg  # additive: {text, at, top_ids}
    return st


@app.post("/api/notifications")
async def api_notifications_act(body: dict):
    d = state.get("notifd")
    if not d:
        return JSONResponse({"error": "no notification daemon in this mode"}, 409)
    action = (body.get("action") or "").strip()
    if action == "dismiss":
        d.dismiss(int(body.get("id", 0)))
    elif action == "clear":
        d.clear()
    elif action == "read":
        d.mark_read()
    elif action == "dnd":
        d.dnd = bool(body.get("on", True))
    elif action == "dismiss_digest":
        from . import attention
        attention.dismiss_digest(state["store"])
    else:
        return JSONResponse({"error": f"unknown action '{action}'"}, 400)
    return {"ok": True, "dnd": d.dnd}


# ---- Screenshots (grim/slurp; the AgentOS session's own capture) ----------------

async def capture_screen(area: str = "full", workspace: str = "") -> tuple[bool, str]:
    """Grab the screen with grim (the AgentOS session's own capture) into
    <workspace>/Screenshots. Returns (ok, path-or-reason) — shared by
    POST /api/screenshot and the agent's take_screenshot tool."""
    import shutil as _sh
    if not _sh.which("grim"):
        return False, ("not supported on this platform: screenshots need grim "
                       "(part of the agentos-desktop package, Wayland sessions)")
    dest_dir = Path(workspace or str(Path.home() / "AgentOS")) / "Screenshots"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / time.strftime("Screenshot-%Y%m%d-%H%M%S.png")
    argv = ["grim", str(dest)]
    if area == "select":
        if not _sh.which("slurp"):
            return False, "not supported on this platform: region capture needs slurp"
        sl = await asyncio.create_subprocess_exec(
            "slurp", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await sl.communicate()
        geometry = out.decode().strip()
        if sl.returncode != 0 or not geometry:
            return False, "selection cancelled"
        argv = ["grim", "-g", geometry, str(dest)]
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    if proc.returncode != 0:
        return False, out.decode(errors="replace")[:300] or "screenshot failed"
    return True, str(dest)


@app.post("/api/screenshot")
async def api_screenshot(body: dict):
    """{area: "full" | "select"} → saves under <workspace>/Screenshots and
    returns the path. `select` hands the pointer to slurp for a region drag."""
    ok, res = await capture_screen(
        area=(body.get("area") or "full"),
        workspace=state["cfg"].get("workspace", ""))
    if not ok:
        code = (503 if "not supported" in res
                else 400 if res == "selection cancelled" else 500)
        return JSONResponse({"error": res}, code)
    state["store"].log("system", f"screenshot saved: {Path(res).name}")
    out = {"ok": True, "path": res}
    if (body or {}).get("inline"):
        # hand the bytes back so the shell can attach the shot to a question
        try:
            import base64
            raw = Path(res).read_bytes()
            if len(raw) <= 12_000_000:
                out["data_url"] = "data:image/png;base64," + base64.b64encode(raw).decode()
        except Exception as e:
            out["inline_error"] = str(e)
    return out


# ---- Power & session: the desktop's own power menu (AgentOS as the DE) ----------
#
# AgentOS is growing into the machine's desktop environment, so the menu bar carries
# real session controls. These are USER-initiated (confirmed in the UI); the agent's
# run_command tool still hard-blocks shutdown/reboot, and apps are blocked by the
# privilege guard.

POWER_ACTIONS = {
    "lock":     {"linux": ["loginctl", "lock-session"],
                 "darwin": ["pmset", "displaysleepnow"]},
    "logout":   {"linux": ["loginctl", "terminate-user", os.environ.get("USER", "")],
                 "darwin": ["osascript", "-e", 'tell application "System Events" to log out']},
    "suspend":  {"linux": ["systemctl", "suspend"],
                 "darwin": ["pmset", "sleepnow"]},
    "restart":  {"linux": ["systemctl", "reboot"],
                 "darwin": ["osascript", "-e", 'tell application "System Events" to restart']},
    "poweroff": {"linux": ["systemctl", "poweroff"],
                 "darwin": ["osascript", "-e", 'tell application "System Events" to shut down']},
}


async def power_exec(action: str) -> tuple[bool, str]:
    """Run one POWER_ACTIONS entry. Returns (ok, reason) — shared by POST /api/power
    (the menu-bar power menu) and the agent's lock_screen / power_action tools."""
    spec = POWER_ACTIONS.get(action)
    if not spec:
        return False, f"unknown action '{action}'"
    import sys as _sys
    argv = spec["darwin"] if _sys.platform == "darwin" else spec["linux"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        if proc.returncode != 0:
            return False, (out.decode(errors="replace")[:300]
                           or f"{argv[0]} exited {proc.returncode}")
    except FileNotFoundError:
        return False, f"'{argv[0]}' not available on this system"
    except asyncio.TimeoutError:
        pass  # a poweroff/logout may never return — that's success
    return True, "ok"


@app.post("/api/power")
async def api_power(body: dict, request: Request):
    """Session/power controls for the menu-bar power menu. 'agentos-restart' restarts
    the AgentOS server itself; the rest drive the host session (loginctl/systemctl)."""
    if _principal_of(request).kind == "app":
        return JSONResponse({"error": "denied: apps cannot control the session"},
                            status_code=403)
    action = (body.get("action") or "").strip()
    if action == "agentos-restart":
        out = await state["toolbox"].restart_agentos()
        return {"ok": not out.startswith(("[error]", "[denied]")), "result": out}
    if action not in POWER_ACTIONS:
        return JSONResponse({"error": f"unknown action '{action}'"}, status_code=400)
    state["store"].log("system", f"power: {action} requested from the desktop")
    ok, msg = await power_exec(action)
    if not ok:
        return JSONResponse({"error": msg}, status_code=500)
    return {"ok": True}


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
    for key in ("default_model", "autonomy", "max_steps", "workspace", "agent_name",
                "policies", "sandbox", "steer_queued_messages"):
        if key in patch:
            cfg[key] = patch[key]
    if isinstance(patch.get("build"), dict) and "model" in patch["build"]:
        cfg.setdefault("build", {})["model"] = str(patch["build"]["model"] or "")[:80]
    if isinstance(patch.get("locale"), dict):
        from . import localeinfo
        lo = cfg.setdefault("locale", {})
        for k in localeinfo.FIELDS:
            if k in patch["locale"]:
                lo[k] = str(patch["locale"][k] or "")[:64]
    if isinstance(patch.get("shortcuts"), dict):
        # {action: "Ctrl+Space"} — the shell's editable keymap, also the source
        # for the compositor bindings written by /api/shortcuts/apply
        cfg["shortcuts"] = {str(k)[:40]: str(v)[:40] for k, v in patch["shortcuts"].items()}
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
    if isinstance(patch.get("desktop"), dict):
        desk = cfg.setdefault("desktop", {})
        from . import runmode as _rm
        if patch["desktop"].get("mode") in _rm.CHOICES:
            desk["mode"] = patch["desktop"]["mode"]
        for k in ("idle_lock_secs", "idle_screen_off_secs"):
            if isinstance(patch["desktop"].get(k), (int, float)):
                desk[k] = max(0, int(patch["desktop"][k]))
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
    {"id": "notes", "name": "Quick Notes", "icon": "", "desc": "an AI scratchpad that saves itself",
     "html": """<h2 style='margin:0 0 8px'>Quick Notes</h2>
<textarea id='n' style='width:100%;height:calc(100vh - 130px);background:#171b22;color:#e6ebf2;border:1px solid #232a35;border-radius:8px;padding:12px;font-size:14px;line-height:1.6' placeholder='Type… saved automatically'></textarea>
<div style='display:flex;gap:8px;align-items:center;margin-top:6px'>
<button id='sum'>✨ Summarize</button><button id='tidy'>✨ Tidy up</button>
<div id='st' style='color:#5c6577;font-size:11px;margin-left:auto'>saved</div></div>
<div id='ai' style='display:none;background:#171b22;border:1px solid #232a35;border-radius:8px;padding:10px;margin-top:8px;font-size:13px;white-space:pre-wrap;max-height:180px;overflow:auto'></div>
<script>const n=document.getElementById('n'),st=document.getElementById('st'),ai=document.getElementById('ai');
n.value=localStorage.getItem('quicknotes')||'';let t;
n.oninput=()=>{st.textContent='saving…';clearTimeout(t);t=setTimeout(()=>{localStorage.setItem('quicknotes',n.value);st.textContent='saved '+new Date().toLocaleTimeString()},400)};
// AI built in: the OS's selected model works on the note via appLLM.stream (injected
// runtime) — output streams into the panel live instead of appearing all at once.
async function think(btn,sys,replace){
  if(!n.value.trim())return;
  btn.disabled=true;const old=btn.textContent;btn.textContent='thinking…';
  ai.style.display='block';ai.textContent='…';
  try{
    const out=await appLLM.stream(n.value,{system:sys,
      onDelta:(d,all)=>{ai.textContent=all;ai.scrollTop=ai.scrollHeight;}});
    if(out.startsWith('[error]')){ai.textContent='AI unavailable — pick a model in Settings. '+out;}
    else if(replace){n.value=out;ai.style.display='none';n.oninput();}
    else{ai.textContent=out;}
  }catch(e){ai.textContent='AI error: '+e;}
  btn.disabled=false;btn.textContent=old;
}
document.getElementById('sum').onclick=e=>think(e.target,'Summarize these notes into their key points, as a short bullet list. Reply with only the summary.');
document.getElementById('tidy').onclick=e=>think(e.target,'Clean up these notes: fix typos and grammar, keep the meaning and all facts, keep the same language. Reply with ONLY the cleaned-up text.',true);</script>"""},
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


# ---- Store: MCP discovery — find servers in the public MCP registry, install with
# consent, record them in the local MCP Registry, and generate their docs ----------

@app.get("/api/store/mcp/search")
async def api_store_mcp_search(q: str = "", limit: int = 30):
    """Search the public MCP registry. Served from the locally-synced index (instant);
    the upstream API (15-25s/request) is only touched by the background sync — the
    response's `index` block tells the UI when results are still growing."""
    from . import mcp_store
    mcp_store.ensure_index(state["store"])
    status = mcp_store.index_status()
    try:
        if status["count"]:
            cands = mcp_store.search_local(q, limit=limit)
        elif status["syncing"]:
            cands = []  # first pages are still arriving — the UI polls
        else:  # no index and no sync possible: one slow upstream query beats nothing
            cands = await mcp_store.search(q, limit=limit)
    except Exception as e:
        return JSONResponse({"error": f"registry search failed: {e}",
                             "index": mcp_store.index_status()}, status_code=502)
    have = set((state["cfg"].get("mcp_servers") or {}).keys())
    for c in cands:
        c["installed"] = c["key"] in have
    return {"candidates": cands, "index": mcp_store.index_status()}


@app.post("/api/store/mcp/install")
async def api_store_mcp_install(body: dict):
    """Install a discovered server: write its config (disabled until required keys are
    filled), add it to the local MCP Registry, and generate its documentation. The UI
    only calls this after the user has said yes to 'build around this?'."""
    from . import mcp_store
    reg_name = (body.get("registry_name") or "").strip()
    if not reg_name:
        return JSONResponse({"error": "registry_name is required"}, status_code=400)
    try:
        cand = await mcp_store.lookup(reg_name, store=state["store"])
    except Exception as e:
        return JSONResponse({"error": f"registry lookup failed: {e}"}, status_code=502)
    if not cand:
        return JSONResponse({"error": f"'{reg_name}' not found in the public registry"},
                            status_code=404)
    name = (body.get("name") or cand["key"]).strip()
    conf, missing = mcp_store.to_conf(cand, env_values=body.get("env") or {})
    state["cfg"].setdefault("mcp_servers", {})[name] = conf
    cfgmod.save_config(state["cfg"])
    mcp_store.record_install(
        state["store"], name, title=cand["registry_name"].split("/")[-1],
        description=cand["description"], source="discovery", origin=cand["registry_name"],
        package=mcp_store.package_info(cand), homepage=cand["homepage"], conf=conf)
    state["store"].log("system", f"store: MCP '{name}' installed from the public registry "
                                 f"({cand['registry_name']})"
                                 + (f" — needs keys: {', '.join(missing)}" if missing else ""))
    await state["mcp"].reload()
    await state["broadcast"]({"type": "config"})
    return {"ok": True, "name": name, "enabled": conf.get("enabled", False),
            "missing_env": missing,
            "doc": f"mcp/{name}.md"}


@app.get("/api/store/mcp/discover_more")
async def api_store_mcp_discover_more(q: str = "", limit: int = 12):
    """Deep discovery: when the MCP registry isn't enough, the system widens the net —
    npm + GitHub swept in parallel, deduped against what the registry already found.
    npm hits install normally (registry_name 'npm:<pkg>'); GitHub-only hits come back
    agentic=True and are handed to the agent to read the repo and configure."""
    from . import mcp_store
    exclude = set()
    for c in mcp_store.search_local(q, limit=60):
        exclude.add(c["registry_name"])
        if c.get("identifier"):
            exclude.add(c["identifier"])
        if c.get("homepage"):
            exclude.add(c["homepage"].rstrip("/"))
    try:
        cands = await mcp_store.search_deep(q, limit=limit, exclude=exclude)
    except Exception as e:
        return JSONResponse({"error": f"deep discovery failed: {e}"}, status_code=502)
    have = set((state["cfg"].get("mcp_servers") or {}).keys())
    for c in cands:
        c["installed"] = c["key"] in have
    return {"candidates": cands}


@app.get("/api/mcp/registry")
async def api_mcp_registry():
    """The local MCP Registry: every server the OS knows, merged with live status."""
    live = {s["name"]: s for s in state["mcp"].status()}
    out = []
    for r in state["store"].mcp_reg_list():
        s = live.get(r["name"], {})
        out.append({**r, "live_status": s.get("status", "not-configured"),
                    "tools": len(s.get("tools") or []), "enabled": s.get("enabled", False)})
    return {"registry": out}


@app.delete("/api/mcp/registry/{name}")
async def api_mcp_registry_delete(name: str, purge: int = 0):
    """Remove a registry entry; purge=1 also removes the server config and its doc."""
    from . import mcp_store
    reg = state["store"].mcp_reg_get(name)
    if reg and purge:
        mcp_store.delete_doc(reg.get("doc_file") or "")
        if name in (state["cfg"].get("mcp_servers") or {}):
            state["cfg"]["mcp_servers"].pop(name, None)
            cfgmod.save_config(state["cfg"])
            await state["mcp"].reload()
    state["store"].mcp_reg_delete(name)
    await state["broadcast"]({"type": "config"})
    return {"ok": True}


@app.post("/api/mcp/registry/{name}/docs")
async def api_mcp_registry_docs(name: str):
    """Regenerate one registry entry's documentation from its current live state."""
    from . import mcp_store
    live = next((s for s in state["mcp"].status() if s["name"] == name), None)
    conf = (state["cfg"].get("mcp_servers") or {}).get(name)
    ok = mcp_store.refresh_doc(state["store"], name, conf=conf, live=live)
    if not ok:
        return JSONResponse({"error": "not in the MCP Registry"}, status_code=404)
    return {"ok": True, "doc": f"mcp/{name}.md"}


# ---- User apps (AI-built UI tools) --------------------------------------------

# The design system every app gets FOR FREE: OS-matched element styles + layout
# utilities, injected into every app page. The builder is instructed to lean on
# these classes and write almost no CSS — weak local models produce dramatically
# better apps composing a given system than inventing layout CSS from scratch.
# Injected at the TOP of <head>, so an app's own styles can still override.
APP_UI_CSS = """
:root{color-scheme:dark;--bg:#0e1116;--s:#171b22;--r:#1e242e;--ln:#232a35;--tx:#e6ebf2;
  --mut:#8a94a6;--acc:#5eead4;--acc2:#22d3ee;--errc:#f87171;--okc:#34d399;--warnc:#fbbf24}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--tx);font:14px/1.55 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;margin:0;padding:18px}
/* ---- the two surfaces every app has -------------------------------------
   Desktop: the whole application. Widget: the one thing worth a glance, at the
   size the user picked (S/M/L). Mark the two views with .widget-only and
   .desktop-only and the right one is shown — no script, no flash of the wrong
   surface, because the class is set before the app's own code runs. */
html[data-surface="desktop"] .widget-only{display:none!important}
html[data-surface="widget"] .desktop-only{display:none!important}
/* pinned as a widget: the AgentOS glass shows through behind the content */
html.agentos-widget,html.agentos-widget body{background:transparent}
html.agentos-widget body{padding:14px;overflow:auto}
html.agentos-widget h1{font-size:15px} html.agentos-widget h2{font-size:13px}
html.agentos-widget .card{padding:11px;border-radius:11px;margin-bottom:8px}
html.agentos-widget .kpi b{font-size:21px}
/* Small is a single glanceable number; Large can afford a table or a chart. */
html.agentos-widget-s body{padding:11px;font-size:12.5px}
html.agentos-widget-s h1{font-size:13.5px} html.agentos-widget-s .kpi b{font-size:26px}
html.agentos-widget-s .card{padding:9px}
html.agentos-widget-l body{padding:15px}
h1{font-size:18px;font-weight:750;margin:0 0 2px}
h2{font-size:15px;font-weight:700;margin:0 0 8px}
h3{font-size:11.5px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:var(--mut);margin:0 0 6px}
p{margin:0 0 10px} a{color:var(--acc2);text-decoration:none} a:hover{text-decoration:underline}
label{display:block;font-size:12px;color:var(--mut);margin:10px 0 4px}
button{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#04211c;border:0;border-radius:9px;
  padding:8px 14px;font:inherit;font-weight:700;cursor:pointer;transition:filter .12s}
button:hover{filter:brightness(1.08)} button:disabled{opacity:.5;cursor:default}
button.ghost{background:var(--r);color:var(--tx);border:1px solid var(--ln);font-weight:600}
button.ghost:hover{border-color:var(--acc);filter:none}
input,select,textarea{background:var(--s);color:var(--tx);border:1px solid var(--ln);border-radius:9px;
  padding:8px 11px;font:inherit;width:100%;max-width:100%}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--acc)}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.5px;
  padding:7px 10px;border-bottom:1px solid var(--ln)}
td{padding:8px 10px;border-bottom:1px solid var(--ln)}
tbody tr:hover td{background:rgba(94,234,212,.05)}
.card{background:var(--s);border:1px solid var(--ln);border-radius:12px;padding:14px;margin-bottom:10px}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.row>input,.row>select{flex:1;width:auto;min-width:120px}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.kpi{background:var(--s);border:1px solid var(--ln);border-radius:12px;padding:12px 14px;text-align:center}
.kpi b{display:block;font-size:24px;font-variant-numeric:tabular-nums}
.kpi span{font-size:11px;color:var(--mut)}
.badge{display:inline-block;background:var(--r);border:1px solid var(--ln);border-radius:20px;
  padding:2px 9px;font-size:10.5px;color:var(--mut)}
.muted{color:var(--mut);font-size:12px} .err{color:var(--errc)} .ok{color:var(--okc)}
.empty{border:1px dashed var(--ln);border-radius:12px;padding:26px 14px;text-align:center;color:var(--mut);font-size:12.5px}
.spin{display:inline-block;width:14px;height:14px;border:2px solid var(--acc);border-top-color:transparent;
  border-radius:50%;animation:aospin .7s linear infinite;vertical-align:-2px}
@keyframes aospin{to{transform:rotate(360deg)}}
"""

APP_SHELL = ('<!DOCTYPE html><html><head><meta charset="utf-8">'
             f'<style id="agentos-ui">{APP_UI_CSS}</style></head>'
             '<body>__BODY__</body></html>')


def _compose_app_page(html: str, runtime: str) -> str:
    """Wrap app markup into a servable page: fragments get the full shell; complete
    documents get the design system injected at the top of <head> (their own styles
    still win) and the runtime scripts right after <body>."""
    if not html.lstrip().lower().startswith(("<!doctype", "<html")):
        return APP_SHELL.replace("__BODY__", runtime + html)
    css = f'<style id="agentos-ui">{APP_UI_CSS}</style>'
    low = html.lower()
    h = low.find("<head")
    if h != -1:
        j = low.index(">", h) + 1
        html = html[:j] + css + html[j:]
    else:
        html = css + html
    low = html.lower()
    if "<body" in low:
        i = low.index("<body")
        i = low.index(">", i) + 1
        html = html[:i] + runtime + html[i:]
    else:
        html = runtime + html
    return html


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


@app.put("/api/apps/{aid}")
async def api_rename_app(aid: str, body: dict):
    """Rename/redecorate an app (name, icon, description, widget size) — the id
    stays, so its data, versions, grants and widgets all follow along."""
    err = state["store"].rename_app(aid, name=body.get("name", ""),
                                    icon=body.get("icon") if "icon" in body else None,
                                    description=body.get("description")
                                    if "description" in body else None,
                                    widget_size=body.get("widget_size")
                                    if "widget_size" in body else None)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    state["store"].log("system", f"app renamed: {aid} → {body.get('name', '')}")
    await state["broadcast"]({"type": "apps"})
    return {"ok": True}


@app.delete("/api/apps/{aid}")
async def api_delete_app(aid: str):
    state["store"].delete_app(aid)
    await state["broadcast"]({"type": "apps"})
    return {"ok": True}


APP_RUNTIME = """<script>
window.APP_ID = %r;
window.APP_TOKEN = %r; // runtime identity: the OS knows WHICH app is calling (permission gate)
// Which surface is this app being drawn on? Every app has two: the desktop
// window (the whole thing) and a widget (the one glanceable fact), at the size
// the user chose. The page is told BEFORE its own script runs, so it can render
// the right one from the first frame instead of flashing the wrong one.
window.appSurface = {mode: %r, size: %r, widget: false, desktop: true};
window.appSurface.widget = window.appSurface.mode === 'widget';
window.appSurface.desktop = !window.appSurface.widget;
try{
  const de = document.documentElement;
  de.dataset.surface = window.appSurface.mode;
  de.dataset.widgetSize = window.appSurface.size;
  if(window.appSurface.widget) de.classList.add('agentos-widget','agentos-widget-'+window.appSurface.size);
}catch(e){}
// ===== AgentOS app runtime v2 — injected into every built app =====
//   appData.get() / appData.set(obj)          the app's private server-side JSON store
//   appTool(name, args)                       run any OS/MCP tool (permission-gated)
//   appLLM(prompt, system?)                   one-shot AI completion -> text
//   appLLM.stream(prompt, {system, onDelta})  streaming completion; onDelta(delta, textSoFar)
//   appChat(messages)                         multi-turn: [{role:'system'|'user'|'assistant', content}]
//   appChat.stream(messages, {onDelta})       streaming multi-turn
//   appAgent(prompt, {tools})                 mini agent loop (up to 5 tool steps) acting AS this
//                                             app — risky tools raise the OS's normal approval card
//   appContext()                              {app_id, app_name, agent_name, model, theme}
//   appCopilot.mount({starters,system,act})   the standard in-app agent widget (✦ corner button)
// Every call is authenticated with the app token and gated by the app's permission grants.
window.appData = {
  async get(){ try{ return await (await fetch('/api/apps/'+window.APP_ID+'/data',{headers:{'X-App-Token':window.APP_TOKEN}})).json(); }catch(e){ return {}; } },
  async set(obj){ try{ await fetch('/api/apps/'+window.APP_ID+'/data',{method:'PUT',headers:{'Content-Type':'application/json','X-App-Token':window.APP_TOKEN},body:JSON.stringify(obj)}); }catch(e){} },
};
window.appTool = async (name,args={}) => {
  try{ const r = await fetch('/api/tool',{method:'POST',headers:{'Content-Type':'application/json','X-App-Token':window.APP_TOKEN},body:JSON.stringify({name,args})}); return await r.json(); }catch(e){ return {error:String(e)}; }
};
const _appHdrs = {'Content-Type':'application/json','X-App-Token':window.APP_TOKEN};
async function _appStream(body, onDelta){
  let r;
  try{ r = await fetch('/api/apps/llm/stream',{method:'POST',headers:_appHdrs,body:JSON.stringify(body)}); }
  catch(e){ return '[error] ' + e; }
  if(!r.ok || !r.body) return '[error] llm stream unavailable (HTTP ' + r.status + ')';
  const rd = r.body.getReader(), dec = new TextDecoder();
  let acc = '';
  for(;;){
    const c = await rd.read(); if(c.done) break;
    const t = dec.decode(c.value,{stream:true}); if(!t) continue;
    acc += t;
    if(onDelta){ try{ onDelta(t, acc); }catch(_){} }
  }
  return acc;
}
// AI inside the app: one-shot LLM completion (no tools). Returns plain text.
window.appLLM = async (prompt, system='') => {
  const r = await window.appTool('llm_generate', system ? {prompt, system} : {prompt});
  if (r && r.output !== undefined) return r.output;
  return '[error] ' + ((r && r.error) || 'llm unavailable');
};
// Streaming completion: resolves the full text, calling onDelta(delta, textSoFar) as it arrives.
window.appLLM.stream = (prompt, opts) =>
  _appStream((opts && opts.system) ? {prompt, system: opts.system} : {prompt}, opts && opts.onDelta);
// Multi-turn chat: pass the whole history (a system message is allowed as messages[0]).
window.appChat = async (messages) => {
  try{
    const r = await (await fetch('/api/apps/llm/chat',{method:'POST',headers:_appHdrs,body:JSON.stringify({messages})})).json();
    if (r && r.output !== undefined) return r.output;
    return '[error] ' + ((r && r.error) || 'llm unavailable');
  }catch(e){ return '[error] ' + e; }
};
window.appChat.stream = (messages, opts) => _appStream({messages}, opts && opts.onDelta);
// Mini agent: the OS agent runs up to 5 tool-using steps AS this app (its grants apply;
// ungranted risky tools raise the normal approval card for the user). Resolves final text.
window.appAgent = async (prompt, opts) => {
  try{
    const r = await (await fetch('/api/apps/agent',{method:'POST',headers:_appHdrs,
      body:JSON.stringify({prompt, tools:(opts && opts.tools) || undefined})})).json();
    if (r && r.output !== undefined) return r.output;
    return '[error] ' + ((r && r.error) || 'agent unavailable');
  }catch(e){ return '[error] ' + e; }
};
// What the app runs inside: ids, the agent's name, the selected model, and the UI theme.
// (the shell does not pass a theme param to app iframes today, so theme reports 'dark')
let _appCtx = null;
window.appContext = async () => {
  if(_appCtx) return _appCtx;
  try{ _appCtx = await (await fetch('/api/apps/context',{headers:{'X-App-Token':window.APP_TOKEN}})).json(); }catch(e){}
  return _appCtx || {app_id:window.APP_ID, app_name:'', agent_name:'', model:'', theme:'dark'};
};
// ---- appCopilot.mount({starters, system, act}) — the standard in-app agent ----
// One call gives ANY app a floating agent: a corner button opening a small
// conversation panel. act:true (default) routes turns through appAgent so the
// agent can DO things under this app's grants; act:false keeps it chat-only.
window.appCopilot = { mounted:false };
window.appCopilot.mount = (opts) => {
  if(window.appCopilot.mounted) return; window.appCopilot.mounted = true;
  opts = opts || {};
  const hist = [];
  const st = document.createElement('style');
  st.textContent = '.acp-fab{position:fixed;right:14px;bottom:14px;z-index:999;width:40px;height:40px;border-radius:999px;border:none;cursor:pointer;font-size:17px;color:#06211d;background:linear-gradient(135deg,#5eead4,#22d3ee);box-shadow:0 6px 18px rgba(0,0,0,.35)}'
    +'.acp-pan{position:fixed;right:14px;bottom:62px;z-index:999;width:min(320px,86vw);max-height:60vh;display:none;flex-direction:column;border-radius:14px;background:rgba(17,20,25,.96);color:#e6ebf2;border:1px solid rgba(255,255,255,.14);box-shadow:0 18px 48px rgba(0,0,0,.42);font:13px/1.45 system-ui,sans-serif}'
    +'.acp-pan.on{display:flex}'
    +'.acp-h{padding:9px 12px;font-weight:700;border-bottom:1px solid rgba(255,255,255,.1);color:#5eead4}'
    +'.acp-f{flex:1;overflow-y:auto;padding:10px 12px;display:flex;flex-direction:column;gap:6px}'
    +'.acp-u{align-self:flex-end;background:rgba(94,234,212,.16);border-radius:12px 3px 12px 12px;padding:5px 10px;max-width:88vw}'
    +'.acp-a{white-space:pre-wrap}'
    +'.acp-w{opacity:.6;font-style:italic}'
    +'.acp-chip{display:inline-block;margin:2px 4px 2px 0;padding:4px 10px;border-radius:999px;border:1px solid rgba(255,255,255,.16);background:none;color:#8a94a6;cursor:pointer;font-size:12px}'
    +'.acp-in{display:flex;gap:6px;padding:9px 12px;border-top:1px solid rgba(255,255,255,.1)}'
    +'.acp-in input{flex:1;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);border-radius:8px;color:inherit;padding:6px 9px;outline:none}'
    +'.acp-in button{border:none;border-radius:999px;width:30px;cursor:pointer;background:linear-gradient(135deg,#5eead4,#22d3ee);color:#06211d;font-weight:800}';
  document.head.appendChild(st);
  const fab = document.createElement('button'); fab.className='acp-fab'; fab.textContent='✦'; fab.title='Ask the agent';
  const pan = document.createElement('div'); pan.className='acp-pan';
  pan.innerHTML = '<div class="acp-h">✦ <span class="acp-nm">agent</span></div><div class="acp-f"></div>'
    +'<div class="acp-in"><input placeholder="Ask about this app…"><button>↑</button></div>';
  document.body.appendChild(fab); document.body.appendChild(pan);
  const feed = pan.querySelector('.acp-f'), inp = pan.querySelector('input');
  window.appContext().then(c => { pan.querySelector('.acp-nm').textContent = (c.agent_name||'agent') + ' · ' + (c.app_name||window.APP_ID); });
  (opts.starters||[]).forEach(s => { const b=document.createElement('button'); b.className='acp-chip'; b.textContent=s;
    b.onclick=() => { inp.value=s; go(); }; feed.appendChild(b); });
  async function go(){
    const q = inp.value.trim(); if(!q) return; inp.value='';
    const u=document.createElement('div'); u.className='acp-u'; u.textContent=q; feed.appendChild(u);
    const a=document.createElement('div'); a.className='acp-a acp-w'; a.textContent='thinking…'; feed.appendChild(a);
    feed.scrollTop=feed.scrollHeight;
    hist.push({role:'user', content:q});
    const sys = (opts.system||'You are the embedded agent of the "'+window.APP_ID+'" app on AgentOS. Be brief; prefer doing over explaining.');
    let out;
    if(opts.act === false){
      out = await window.appChat([{role:'system',content:sys}].concat(hist.slice(-12)));
    }else{
      out = await window.appAgent(sys + '\\nConversation so far:\\n'
        + hist.slice(-12).map(m => m.role + ': ' + m.content).join('\\n'));
    }
    hist.push({role:'assistant', content:out});
    a.classList.remove('acp-w'); a.textContent = out;
    feed.scrollTop=feed.scrollHeight;
  }
  pan.querySelector('.acp-in button').onclick = go;
  inp.addEventListener('keydown', e => { if(e.key==='Enter') go(); });
  fab.onclick = () => { pan.classList.toggle('on'); if(pan.classList.contains('on')) inp.focus(); };
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
async def api_app_page(aid: str, surface: str = "", size: str = ""):
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
    mode = "widget" if surface == "widget" else "desktop"
    wsize = (size or a.get("widget_size") or "m").lower()
    if wsize not in ("s", "m", "l"):
        wsize = "m"
    runtime = APP_RUNTIME % (aid, tok, mode, wsize)
    return HTMLResponse(_compose_app_page(a["html"] or "", runtime))


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
    # appLLM / appLLM.stream / appChat(.stream) all resolve to the llm_generate capability;
    # appAgent stays manifest-driven (its tool needs are whatever the manifest declares —
    # every tool it touches is still PDP-gated per step under the app's principal).
    if _re.search(r"\bapp(?:LLM|Chat)\s*[.(]", html or "") and \
            ("tool.use", "tool:llm_generate*") not in seen:
        seen.add(("tool.use", "tool:llm_generate*"))
        perms.append({"action": "tool.use", "resource": "tool:llm_generate*",
                      "reason": "uses the AI model inside the app (appLLM/appChat)",
                      "required": False})
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
        from . import mcp_store
        for nm in installed["mcp"]:  # package-borne servers land in the MCP Registry too
            mcp_store.record_install(state["store"], nm, source="package",
                                     origin=f"app package: {name}",
                                     conf=state["cfg"]["mcp_servers"].get(nm))
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
- A DESIGN SYSTEM IS PRE-INJECTED into every app page — you do NOT write or include it. It styles
  body, h1-h3, p, a, label, button (accent gradient; `button.ghost` = secondary), input/select/
  textarea, and table (striped header, row hover) automatically, and provides these utilities:
    .card (surface box) · .row (flex line: inputs stretch, buttons stay natural size) ·
    .cols (responsive auto-fit card grid) · .grid2 (two equal columns) ·
    .kpi (stat tile: <div class="kpi"><b>42</b><span>label</span></div>) ·
    .badge · .muted · .err · .ok · .empty (dashed empty-state box) ·
    .spin (ready-made loading spinner: <span class="spin"></span>)
  COMPOSE WITH THESE — semantic HTML plus these classes IS the design. Write custom CSS only for
  something genuinely app-specific (a chart, a special widget), never to restyle base elements.
- HARD LAYOUT RULES — breaking these is what makes apps look amateur; treat them as law:
  · Structure pages ONLY with .card / .row / .cols / .grid2 — NEVER position:absolute or fixed
    for layout, no floats, no rotated/vertical text, no writing-mode tricks.
  · No fixed pixel widths/heights on layout elements (flex/grid handles size); buttons are normal
    height — never stretched tall or full-screen.
  · Every input/select/textarea gets a <label> above it. Related controls share one .row.
  · One h1 title + a .muted subtitle at the top, then .card sections. Nothing may overlap.
- TWO SURFACES, ALWAYS. Every app is opened as a desktop window AND can be pinned to the desktop as a
  WIDGET (S, M or L — the user's choice). Build both, in the same HTML:
    · Wrap the full application in `<div class="desktop-only">…</div>`.
    · Wrap a compact glanceable view in `<div class="widget-only">…</div>` — the ONE number, status or
      next item that makes the app worth a glance, plus at most one action. A .kpi tile or two short
      lines is usually right; never a table, form or nav in the widget.
    · The OS shows exactly one of them — no script needed. `window.appSurface` = {mode:'widget'|'desktop',
      size:'s'|'m'|'l', widget:bool, desktop:bool} if you need to branch in JS (e.g. poll less often, or
      show more rows at size 'l'). Both views read the SAME appData state — never duplicate the logic.
    · Widget canvases are small: S ≈ 260×170, M ≈ 340×240, L ≈ 460×340 CSS px. The widget must be
      readable and complete at S, with no horizontal scrolling.
- NO external CDNs, fonts, or images (blocked) — inline any extra CSS/JS, assets as data URIs.
- Every async action shows a loading state (.spin) and a readable .err state; every list has an
  .empty state telling the user what to do first; numbers/dates are formatted, not raw.
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
- AI RUNTIME — the OS's language model is INSIDE every app, pre-injected as four helpers:
  · `await appLLM(prompt, system?)` — one-shot, returns text. For short, invisible work only:
    classify a row, extract a field, name a thing. Also the resilient-parsing trick: after
    appTool('fetch_url',…), call appLLM(pageText, 'Reply with ONLY JSON {"price": number|null,
    "currency": string}') and JSON.parse inside try/catch — prefer this over brittle regex.
  · `await appLLM.stream(prompt, {system, onDelta})` — STREAMING completion. onDelta(delta,
    textSoFar) fires per chunk; resolve value is the full text. ALWAYS stream when the output is
    user-visible and could exceed a sentence — a live-updating <div> beats a spinner every time.
  · `await appChat(messages)` / `await appChat.stream(messages, {onDelta})` — MULTI-TURN: pass the
    whole [{role, content}] history (system message allowed first). This is how you build real
    in-app assistants: keep the messages array in appData, append the user turn, stream the reply
    into the transcript, then append the assistant turn.
  · `await appAgent(prompt, {tools:['fetch_url','notify',…]})` — a real mini-agent: the OS runs up
    to 5 tool-using steps AS this app and resolves the final text. Use it when the app needs the
    AI to DO things, not just say things (fetch + compare + notify, file a note, schedule a check).
    Risky/ungranted tools raise the OS's normal approval card — declare what it needs in `permissions`.
- AI-NATIVE BY DEFAULT: every app you ship has the model built in — the "textarea + ✨ button" is
  the FLOOR, not the ceiling. Aim higher: a chat panel with memory (appChat.stream), proactive
  suggestions rendered from the app's own appData, natural-language input that appAgent turns into
  actions. Rules of thumb: user-visible output → appLLM.stream, never bare appLLM; conversation
  with history → appChat; real actions → appAgent. Every AI feature gets a loading state and a
  graceful '[error]…' fallback when no model is configured. An app without its AI feature is incomplete.
- ALWAYS call appCopilot.mount({starters:[2-3 app-specific prompts]}) once at startup — every app
  ships with its resident agent (the ✦ corner button) IN ADDITION to its bespoke AI feature. Pass
  {act:false} only for pure-content apps where acting makes no sense.
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
    # layout smells that reliably produce broken-looking apps (the design-system
    # contract bans them) — flagged so the repair pass rebuilds with .row/.cols/.card
    if re.search(r"position\s*:\s*fixed", html, re.IGNORECASE):
        issues.append("uses position:fixed — banned for app layout; restructure with the "
                      "design-system .card/.row/.cols utilities")
    if len(re.findall(r"position\s*:\s*absolute", html, re.IGNORECASE)) > 2:
        issues.append("layout leans on position:absolute — banned; restructure with the "
                      "design-system .card/.row/.cols utilities")
    if re.search(r"writing-mode|text-orientation|rotate\(\s*-?9[05]", html, re.IGNORECASE):
        issues.append("rotated/vertical text detected — banned; use a normal horizontal label")
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


# ---- Shell-control channel: server → browser-shell commands, with results --------
#
# The desktop shell (the stock browser UI, or a theme's replacement shell) is a WS
# client like any other — but it is the only party that can act INSIDE the rendered
# desktop: open an AgentOS app window, switch virtual desktops, apply a theme. The
# contract (the UI side implements the handler):
#
#   server → shell (broadcast on /ws):
#       {"type": "shell_cmd", "id": "<uuid>", "action": "<name>", "args": {...}}
#   shell → server (answer within the timeout):
#       POST /api/shell/result   {"id": "<uuid>", "ok": true|false, "data": <any JSON>}
#
# Actions the stock shell implements: open_app {target}, close_app {target},
# focus_app {target}, switch_desktop {target}, apply_theme {target},
# list_open_apps {}. `data` carries the result (e.g. the open-app list) or, on
# ok=false, a sentence saying why. /api/shell/result is in SENSITIVE_FOR_APPS so
# user-built apps cannot spoof results.

async def shell_command(action: str, args: dict | None = None, timeout: float = 8.0):
    """Send one command to the connected shell and await its answer. Returns
    (ok, data); never raises — no shell / no answer comes back as (False, sentence)."""
    if not state.get("clients"):
        return False, ("no desktop shell is connected (open the AgentOS UI in a "
                       "browser) — shell actions need a live shell")
    cid = uuid.uuid4().hex[:8]
    fut = asyncio.get_event_loop().create_future()
    state.setdefault("shell_pending", {})[cid] = fut
    await state["broadcast"]({"type": "shell_cmd", "id": cid, "action": action,
                              "args": args or {}})
    try:
        res = await asyncio.wait_for(fut, timeout=timeout)
        return bool(res.get("ok")), res.get("data")
    except asyncio.TimeoutError:
        return False, (f"the desktop shell did not answer '{action}' within "
                       f"{timeout:.0f}s — it may be an older or custom shell without "
                       "shell_cmd support")
    finally:
        state["shell_pending"].pop(cid, None)


@app.post("/api/shell/result")
async def api_shell_result(body: dict):
    """The shell's answer to a shell_cmd event (contract above). Sensitive: user-built
    apps are blocked from posting here — they could spoof shell results."""
    fut = state.get("shell_pending", {}).get(str(body.get("id", "")))
    if fut is None or fut.done():
        return JSONResponse({"error": "unknown or expired shell_cmd id"}, status_code=404)
    fut.set_result({"ok": bool(body.get("ok")), "data": body.get("data")})
    return {"ok": True}


# ---- App privilege guard: apps may never reconfigure the OS over plain REST ------

# method + path-prefix pairs an app-originated request is never allowed to hit;
# capability access goes through /api/tool + grants, never around them
SENSITIVE_FOR_APPS = (
    ("PUT", "/api/config"), ("PUT", "/api/mcp"), ("PUT", "/api/soul"),
    ("POST", "/api/apps"), ("DELETE", "/api/apps"), ("PUT", "/api/apps"),
    ("POST", "/api/grants"), ("DELETE", "/api/grants"),
    ("POST", "/api/snapshots"), ("DELETE", "/api/snapshots"),
    ("PUT", "/api/telegram"), ("PUT", "/api/widgets"), ("POST", "/api/skills"),
    ("DELETE", "/api/skills"), ("POST", "/api/factory-reset"),
    ("POST", "/api/power"), ("POST", "/api/store/mcp"), ("DELETE", "/api/mcp/registry"),
    # DE-mode system controls: joining networks, pairing devices and rewiring
    # audio are user acts, never app acts
    ("POST", "/api/net/wifi"), ("POST", "/api/bt"), ("POST", "/api/brightness"),
    ("POST", "/api/audio/devices"), ("POST", "/api/power/profile"),
    ("POST", "/api/wm/outputs"), ("POST", "/api/components"),
    # shell_cmd results come from the shell itself, never from an app iframe
    ("POST", "/api/shell/result"),
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
        own_surface = (path.startswith("/api/apps/") and path.endswith(("/data", "/page"))) \
            or path in ("/api/apps/llm/stream", "/api/apps/llm/chat",
                        "/api/apps/agent", "/api/apps/context")  # appLLM v2 runtime

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


# ---------------------------------------------------------------------------
# Remote access gate.
#
# Declared after app_privilege_guard on purpose: Starlette runs the LAST
# registered middleware FIRST, and nothing else in this file should ever see a
# request from the network that has not proved it may be here.
#
# Loopback is trusted because the kernel, not a header, decides the source
# address — so using AgentOS on the machine it runs on is unchanged whether or
# not remote access is on.
# ---------------------------------------------------------------------------

REMOTE_OPEN_PATHS = ("/login", "/api/remote/login", "/assets/", "/manifest.webmanifest",
                     "/favicon.ico", "/apple-touch-icon.png")


def _client_addr(request: Request) -> str:
    return (request.client.host if request.client else "") or ""


def _authed(request: Request) -> bool:
    cfg = state["cfg"]
    if not remotemod.enabled(cfg):
        return True                                     # loopback-only: nothing to gate
    if cfg["remote"].get("trust_loopback", True) and remotemod.is_loopback(_client_addr(request)):
        return True
    return remotemod.valid_session(cfg, request.cookies.get(remotemod.COOKIE, ""))


@app.middleware("http")
async def remote_access_gate(request: Request, call_next):
    if _authed(request):
        return await call_next(request)
    path = request.url.path
    if path.startswith(REMOTE_OPEN_PATHS):
        return await call_next(request)
    # an API caller gets a machine-readable 401; a browser gets the sign-in page
    if path.startswith("/api/") or path.startswith("/ws"):
        return JSONResponse({"error": "sign in required", "login": "/login"},
                            status_code=401, headers=NO_STORE)
    return FileResponse(UI_DIR / "login.html", headers=NO_STORE)


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
    # apps render inside the desktop, so their calls arrive via the GUI gate
    surface = "gui" if principal.kind == "app" else "api"
    dec = state["pdp"].decide_tool(principal, name, args, level, reason=reason,
                                   autonomy=state["cfg"].get("autonomy", ""),
                                   surface=surface)
    if name in ALWAYS_ASK and dec.effect == "allow" and dec.rule == "default":
        dec.effect = "ask"   # power/session actions confirm every time, autonomy aside

    def _plog(outcome: str, approved=None):
        state["store"].log("policy",
                           f"{outcome}: {principal.label} → {dec.action} {dec.resource}"[:400],
                           {"principal": principal.label, "action": dec.action,
                            "resource": dec.resource, "effect": dec.effect, "rule": dec.rule,
                            "reason": dec.reason or reason, "tool": name,
                            "approved": approved, "surface": surface, "via": "api_tool"})
        if dec.rule == "io-gate":
            state["store"].log("error", f"IO gate blocked {dec.action} {dec.resource} "
                                        f"on '{surface}'"[:400],
                               {"principal": principal.label, "surface": surface,
                                "rule": "io-gate"})
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
    surfaces = (body.get("surfaces") or "*").strip() or "*"
    gid = state["store"].add_grant(kind, pid, action, resource, effect=effect,
                                   source="user", note=body.get("note", ""),
                                   surfaces=surfaces)
    state["store"].log("policy", f"grant attached: {effect} {kind}:{pid} → {action} {resource}"
                                 + (f" [{surfaces}]" if surfaces != "*" else ""),
                       {"principal": f"{kind}:{pid}", "action": action, "resource": resource,
                        "effect": effect, "surfaces": surfaces, "via": "permissions_ui"})
    await state["broadcast"]({"type": "grants"})
    return {"id": gid}


@app.put("/api/grants/{gid}")
async def api_update_grant(gid: str, body: dict):
    """Toggle a grant's effect (allow/deny) and/or rescope its IO surfaces."""
    ok = False
    effect = (body.get("effect") or "").strip()
    if effect:
        ok = state["store"].update_grant(gid, effect)
        if ok:
            state["store"].log("policy", f"grant toggled to {effect}: {gid}",
                               {"grant_id": gid, "effect": effect, "via": "permissions_ui"})
    if "surfaces" in body:
        ok = state["store"].set_grant_surfaces(gid, body.get("surfaces") or "*") or ok
        state["store"].log("policy", f"grant surfaces set to "
                                     f"{body.get('surfaces') or '*'}: {gid}",
                           {"grant_id": gid, "surfaces": body.get("surfaces") or "*",
                            "via": "permissions_ui"})
    if ok:
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
    from .policy import SURFACES
    return {"principals": principals,
            "surfaces": list(SURFACES),
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
        "queue_update {conversation_id,queue[],added?/decided?/started?/removed?/cleared?} "
        "(messages typed while a turn runs)",
        "steer {id,mode:'now'|'later',text,reason} (a queued message was folded into "
        "the live turn, or left for the next one)",
        "apps / themes / widgets / wallpaper / models / files / config / grants  (refresh hints)",
        "theme_apply {theme}", "model_pull {name,status,done}", "fabric_event / fabric_defs",
        "telegram_in / telegram_out {conversation_id,text}", "knowledge_update",
        "briefing {text,reason,conversation_id} ('while you were away', de/kiosk)",
        "suggestion {id,text,action_prompt} (proactive; dismiss via "
        "POST /api/suggestions/{id}/dismiss)",
        "shell_cmd {id,action,args} (the shell answers via POST /api/shell/result "
        "{id,ok,data}; actions: open_app/close_app/focus_app/switch_desktop/"
        "apply_theme/list_open_apps)",
    ],
    "inbound (client → server)": [
        "chat {text, conversation_id?, model?} (queued when that chat is already busy)",
        "build {prompt, app_id?, model?}",
        "approval {id, approved, remember?}", "abort {}",
        "queue_remove {conversation_id, id} (drop a queued message)",
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
    from . import runmode as _rm
    if _rm.resolve(state.get("cfg"))[0] == _rm.DE:
        return JSONResponse({"error": "AgentOS is the desktop here — its wallpaper IS "
                                      "the system wallpaper. Pick one in Personalize."},
                            status_code=409)
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


# ---------------------------------------------------------------------------
# Automations: named, repeatable desktop sequences.
#
# The RUNNER lives in the browser, because the steps are desktop actions — open
# this app, switch to that theme, put the agent on this prompt. So /run does not
# execute anything here; it broadcasts, and every connected desktop performs the
# sequence. That is what makes one automation behave identically whether it was
# fired from the palette, a hot corner, a schedule, or the agent's own tool.
# ---------------------------------------------------------------------------

AUTOMATION_STEP_KINDS = {"app", "action", "theme", "wallpaper", "desktop",
                         "agent", "tool", "python", "wait"}


def _clean_steps(steps) -> list[dict]:
    """Keep only well-formed steps — a stored automation is replayed unattended,
    so a malformed step must be dropped at the door, not at 7am on a Monday."""
    out = []
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        kind = str(s.get("kind") or "").strip()
        if kind not in AUTOMATION_STEP_KINDS:
            continue
        step = {"kind": kind}
        for k in ("app", "action", "theme", "wallpaper", "prompt", "tool", "code"):
            if s.get(k):
                step[k] = str(s[k])[:20000]
        if kind == "tool":
            if not step.get("tool"):
                continue                      # a tool step without a tool is nothing
            args = s.get("args")
            if isinstance(args, dict):
                args = json.dumps(args)
            step["args"] = str(args or "{}")[:20000]
        if kind == "python" and not step.get("code"):
            continue
        if kind == "desktop":
            step["desk"] = max(1, min(9, int(s.get("desk") or 1)))
        if kind == "wait":
            step["ms"] = max(0, min(60000, int(s.get("ms") or 500)))
        out.append(step)
    return out[:40]


# ---------------------------------------------------------------------------
# Remote access: the sign-in surface and the switch that turns it all on.
# ---------------------------------------------------------------------------

@app.get("/login")
async def login_page():
    return FileResponse(UI_DIR / "login.html", headers=NO_STORE)


@app.post("/api/remote/login")
async def api_remote_login(body: dict, request: Request):
    cfg = state["cfg"]
    addr = _client_addr(request)
    if not remotemod.enabled(cfg):
        return {"ok": True}                        # nothing to sign in to
    wait = remotemod.locked_for(addr)
    if wait:
        return JSONResponse({"error": f"too many attempts — try again in {wait}s"},
                            status_code=429)
    if not remotemod.check_passphrase(cfg, (body or {}).get("passphrase", "")):
        held = remotemod.note_failure(addr)
        state["store"].log("system", "remote sign-in failed", {"from": addr})
        return JSONResponse(
            {"error": "wrong passphrase" + (f" — locked out for {held}s" if held else "")},
            status_code=401)
    remotemod.note_success(addr)
    state["store"].log("system", "remote sign-in", {"from": addr})
    resp = JSONResponse({"ok": True})
    resp.set_cookie(remotemod.COOKIE, remotemod.issue_session(cfg),
                    max_age=int(cfg["remote"].get("session_days") or 30) * 86400,
                    httponly=True, samesite="lax", path="/")
    return resp


@app.post("/api/remote/logout")
async def api_remote_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(remotemod.COOKIE, path="/")
    return resp


@app.get("/api/remote")
async def api_remote_status():
    return remotemod.status(state["cfg"])


@app.post("/api/remote")
async def api_remote_configure(body: dict, request: Request):
    """Turn remote access on/off and set the passphrase.

    Deliberately *not* reachable through configure_agentos: exposing this machine
    to the network is a decision for the person sitting at it, so the call must
    come from loopback. An agent, an app, or someone already signed in remotely
    cannot widen this on their own.
    """
    cfg = state["cfg"]
    if not remotemod.is_loopback(_client_addr(request)):
        return JSONResponse(
            {"error": "remote access can only be changed from the machine itself"},
            status_code=403)
    body = body or {}
    r = cfg.setdefault("remote", {})

    if "passphrase" in body:
        pw = body["passphrase"] or ""
        if pw:
            problem = remotemod.passphrase_problem(pw)
            if problem:
                return JSONResponse({"error": problem}, status_code=400)
            r["pass_hash"], r["pass_salt"] = remotemod.hash_passphrase(pw)
            remotemod.reset_failures()
        else:
            r["pass_hash"] = r["pass_salt"] = ""      # clearing it also disarms below

    if "enabled" in body:
        want = bool(body["enabled"])
        if want and not r.get("pass_hash"):
            return JSONResponse({"error": "set a passphrase before enabling remote access"},
                                status_code=400)
        r["enabled"] = want
    for k in ("bind", "session_days", "trust_loopback"):
        if k in body:
            r[k] = body[k]

    remotemod.sanitize_remote(cfg)
    cfgmod.save_config(cfg)
    state["store"].log("system", f"remote access {'enabled' if remotemod.enabled(cfg) else 'disabled'}",
                       {"bind": r.get("bind")})
    await state["broadcast"]({"type": "remote"})
    st = remotemod.status(cfg)
    st["restart_required"] = remotemod.enabled(cfg) and \
        os.environ.get("AGENTOS_BOUND_HOST", "127.0.0.1") != remotemod.bind_host(cfg)
    return st


@app.get("/api/automations")
async def api_automations():
    return {"automations": state["store"].list_automations()}


@app.post("/api/automations")
async def api_automation_save(body: dict):
    name = (body or {}).get("name", "").strip()
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    steps = _clean_steps((body or {}).get("steps"))
    if not steps:
        return JSONResponse({"error": "an automation needs at least one valid step"}, status_code=400)
    aid = state["store"].save_automation(name, json.dumps(steps), (body or {}).get("icon", ""))
    await state["broadcast"]({"type": "automations"})
    return {"ok": True, "id": aid, "steps": steps}


@app.delete("/api/automations/{key}")
async def api_automation_delete(key: str):
    state["store"].delete_automation(key)
    await state["broadcast"]({"type": "automations"})
    return {"ok": True}


@app.post("/api/automations/{key}/run")
async def api_automation_run(key: str):
    a = state["store"].get_automation(key)
    if not a:
        return JSONResponse({"error": f"no automation named {key!r}"}, status_code=404)
    state["store"].mark_automation_run(a["id"])
    state["store"].log("automation", f"ran {a['name']}", {"steps": len(a["steps"])})
    await state["broadcast"]({"type": "automation.run", "automation": a})
    return {"ok": True, "name": a["name"], "steps": len(a["steps"])}


@app.get("/api/wallpapers/builtin")
async def api_wallpapers_builtin():
    """The wallpapers that ship with AgentOS — SVG, so they cost a few KB and
    stay sharp from a phone to a 4K panel."""
    d = UI_DIR / "assets" / "wallpapers"
    ids = sorted(p.stem for p in d.glob("*.svg")) if d.exists() else []
    return {"wallpapers": ids}


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


def _user_docs_dir() -> Path | None:
    """Generated documentation (e.g. MCP Registry manuals) lives with the user's data,
    not in the source tree — merged into the same Docs app."""
    from .mcp_store import USER_DOCS_DIR
    return USER_DOCS_DIR if USER_DOCS_DIR.is_dir() else None


@app.get("/api/docs")
async def api_docs():
    out = []
    for base in (_docs_dir(), _user_docs_dir()):
        if not base:
            continue
        for p in sorted(base.glob("**/*.md")):
            rel = str(p.relative_to(base))
            if any(d["file"] == rel for d in out):
                continue  # built-in docs win a name collision
            try:
                first = next((ln for ln in p.read_text().splitlines() if ln.startswith("#")), rel)
            except Exception:
                first = rel
            out.append({"file": rel, "title": first.lstrip("# ").strip()})
    order = ["README.md", "getting-started.md", "installation.md", "lifecycle.md",
             "desktop.md", "agent.md", "building-apps.md", "training.md", "git.md",
             "tui.md", "security.md", "hermes.md", "integrations.md", "models.md", "configuration.md",
             "api-reference.md", "architecture.md", "roadmap.md"]
    out.sort(key=lambda d: order.index(d["file"]) if d["file"] in order else 99)
    return {"docs": out}


@app.get("/api/docs/{name:path}")
async def api_doc(name: str):
    for base in (_docs_dir(), _user_docs_dir()):
        if not base:
            continue
        p = (base / name).resolve()
        if str(p).startswith(str(base.resolve())) and p.suffix == ".md" and p.is_file():
            return {"file": name, "content": p.read_text()}
    return JSONResponse({"error": "not found"}, status_code=404)


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
# Agent-led onboarding: /api/setup/say — the chosen model speaks the wizard's
# conversational steps (chunked text, canned fallback when no model answers)
# ---------------------------------------------------------------------------

# canned lines: what the wizard shows when no model is configured, the provider
# errors, or the first token takes >6s — indistinguishable from the streamed
# path except that the text arrives in one chunk (the JS bakes these in too,
# for when the endpoint itself is unreachable)
SAY_FALLBACK = {
    "locale": "One thing that changes every answer: where you are. I read this off the machine — "
              "is it right? News, weather, prices and times all follow it.",
    "autonomy": "I'm {name} — good to meet you. How much should I do on my own? "
                "Balanced is a good start: I act freely and check with you before anything risky.",
    "autostart": "Should I keep running in the background — for scheduled jobs, alerts and "
                 "Telegram — even when this window is closed?",
    "de_here": "This is your desktop now, so I'm always here — nothing to install, "
               "nothing to start.",
    "wallpaper": "Let's make this place yours. Pick a wallpaper to start with — "
                 "I can generate a custom one for you later.",
    "voice": "One more thing — should I speak my replies out loud, or keep things quiet?",
    "done": "That's everything — welcome to AgentOS. Let's get to work.",
}

_SAY_ASKS = {
    "locale": "Tell the user that where they are changes every answer you give — news, "
              "weather, prices, times — say you have read it off their machine, and ask them "
              "to confirm it. Their detected country and timezone are shown as buttons under "
              "your message; do NOT name them yourself and do not list the choices.",
    "autonomy": "Introduce yourself by name in a few words, then ask how much autonomy you "
                "should have when working for them, recommending the Balanced setting (act "
                "freely, ask before risky actions). The choices are shown as buttons under "
                "your message — do not list them.",
    "autostart": "Ask whether you should keep running in the background at login — for "
                 "scheduled jobs and alerts — even when the window is closed. The yes/no "
                 "choices are buttons — do not list them.",
    "de_here": "Tell the user, briefly and warmly, that AgentOS is their desktop session now, "
               "so you are always present — nothing to install or start.",
    "wallpaper": "Invite the user to pick a starting wallpaper for their new desktop, and "
                 "mention you can generate a custom one later. The presets are shown as "
                 "buttons — do not describe them.",
    "voice": "Ask whether the user would like you to speak your replies out loud "
             "(text-to-speech). The yes/no choices are buttons — do not list them.",
    "done": "The setup just finished. Welcome the user to AgentOS in one warm sentence.",
}


@app.post("/api/setup/say")
async def api_setup_say(body: dict):
    """Stream one short in-character line from the chosen model for a wizard step.
    body: {step, name, model, provider?, key?} → chunked text/plain. Strict brief:
    ≤2 sentences, warm, no markdown. Any failure (no model, provider error, >6s to
    first token) degrades to the canned line for that step — never an error."""
    from fastapi.responses import StreamingResponse
    body = body or {}
    step = str(body.get("step") or "autonomy")
    name = (str(body.get("name") or "").strip()
            or state["cfg"].get("agent_name") or "Aria")[:40]
    model = str(body.get("model") or "").strip()
    canned = SAY_FALLBACK.get(step, SAY_FALLBACK["done"]).format(name=name)
    cfg = state["cfg"]
    prov, key = str(body.get("provider") or "").strip(), str(body.get("key") or "").strip()
    if prov and key and prov in (cfg.get("providers") or {}):
        # the wizard may hold a cloud key that isn't saved yet — use it for this line only
        import copy
        cfg = {**cfg, "providers": copy.deepcopy(cfg["providers"])}
        cfg["providers"][prov]["api_key"] = key
        cfg["providers"][prov]["enabled"] = True

    async def gen():
        if not model or step not in _SAY_ASKS:
            yield canned
            return
        sys_p = (f"You are {name}, the user's brand-new personal AI agent, speaking during "
                 "AgentOS first-run setup. Reply with EXACTLY the line to show the user: at "
                 "most 2 short sentences, warm and confident, plain text only — no markdown, "
                 "no quotes, no emoji, no stage directions.")
        agen = providers.chat(cfg, model,
                              [{"role": "system", "content": sys_p},
                               {"role": "user", "content": _SAY_ASKS[step]}], [],
                              options={"max_tokens": 120, "think": False})
        it = agen.__aiter__()

        async def first_text():
            async for ev in it:
                if ev.get("type") == "text" and ev.get("text"):
                    return ev["text"]
                if ev.get("type") == "done":
                    return None
            return None

        try:
            first = await asyncio.wait_for(first_text(), timeout=6.0)
        except Exception:
            first = None
        if not first:
            with contextlib.suppress(Exception):
                await agen.aclose()
            yield canned
            return
        sent = first
        yield first
        try:
            while len(sent) < 400:   # the brief says ≤2 sentences — cap runaways
                ev = await asyncio.wait_for(it.__anext__(), timeout=10.0)
                if ev.get("type") == "text" and ev.get("text"):
                    sent += ev["text"]
                    yield ev["text"]
                elif ev.get("type") == "done":
                    break
        except Exception:
            pass
        finally:
            with contextlib.suppress(Exception):
                await agen.aclose()

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")


# ---------------------------------------------------------------------------
# appLLM v2: the AI runtime behind the helpers injected into every built app
# (appLLM.stream / appChat / appAgent / appContext). App-token only; the same
# PDP gate as /api/tool — these endpoints never bypass the grant system.
# ---------------------------------------------------------------------------

def _app_principal(request) -> Principal | None:
    """The calling app's principal, or None when the request has no valid app token
    (these endpoints are app-only — users and the shell have /api/chat and /ws)."""
    p = _principal_of(request)
    return p if p.kind == "app" else None


async def _gate_app_llm(principal: Principal):
    """The exact gate /api/tool applies to llm_generate: PDP decision, approval card
    on 'ask', audit log on refusal. Returns an error response, or None when allowed."""
    toolbox = state["toolbox"]
    level, reason = toolbox.risk_of("llm_generate", {})
    dec = state["pdp"].decide_tool(principal, "llm_generate", {}, level, reason=reason,
                                   autonomy=state["cfg"].get("autonomy", ""), surface="gui")
    if dec.effect == "deny":
        state["store"].log("policy", f"deny: {principal.label} → {dec.action} {dec.resource}",
                           {"principal": principal.label, "action": dec.action,
                            "resource": dec.resource, "effect": "deny", "via": "app_llm"})
        return JSONResponse({"error": f"denied: {dec.reason or reason}"}, status_code=403)
    if dec.effect == "ask":
        if not state["clients"]:
            return JSONResponse({"error": f"needs approval: {dec.reason or reason}"},
                                status_code=403)
        if not await request_approval("llm_generate", {}, dec.reason or reason,
                                      offer=dec.grant_offer):
            return JSONResponse({"error": f"not approved: {dec.reason or reason}"},
                                status_code=403)
    return None


def _app_llm_messages(body: dict) -> list[dict]:
    """{prompt, system?} or {messages: [{role, content}…]} → provider messages, sanitized
    (roles whitelisted, content stringified and capped)."""
    msgs = []
    if isinstance(body.get("messages"), list):
        for m in body["messages"][:80]:
            if isinstance(m, dict) and m.get("role") in ("system", "user", "assistant"):
                msgs.append({"role": m["role"], "content": str(m.get("content") or "")[:60_000]})
    if not msgs:
        if body.get("system"):
            msgs.append({"role": "system", "content": str(body["system"])[:60_000]})
        msgs.append({"role": "user", "content": str(body.get("prompt") or "")[:60_000]})
    return msgs


@app.post("/api/apps/llm/stream")
async def api_app_llm_stream(body: dict, request: Request):
    """appLLM.stream / appChat.stream: streaming completion for a user-built app as
    chunked text. Takes {prompt, system?} or {messages}; optional {model}."""
    from fastapi.responses import StreamingResponse
    principal = _app_principal(request)
    if principal is None:
        return JSONResponse({"error": "app token required (X-App-Token)"}, status_code=401)
    gate = await _gate_app_llm(principal)
    if gate is not None:
        return gate
    body = body or {}
    model = str(body.get("model") or "").strip() or state["cfg"].get("default_model", "")
    msgs = _app_llm_messages(body)
    state["store"].log("tool", "app→appLLM.stream",
                       {"via": "user_app", "principal": principal.label,
                        "app_id": principal.id})

    async def gen():
        if not model:
            yield "[error] no model configured"
            return
        try:
            async for ev in providers.chat(state["cfg"], model, msgs, []):
                if ev.get("type") == "text" and ev.get("text"):
                    yield ev["text"]
        except Exception as e:
            yield f"[error] llm: {type(e).__name__}: {e}"

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")


@app.post("/api/apps/llm/chat")
async def api_app_llm_chat(body: dict, request: Request):
    """appChat: multi-turn one-shot — {messages} in, {output} out. Same auth + gate
    as /api/apps/llm/stream; the messages pass to the provider as-is (system allowed)."""
    principal = _app_principal(request)
    if principal is None:
        return JSONResponse({"error": "app token required (X-App-Token)"}, status_code=401)
    gate = await _gate_app_llm(principal)
    if gate is not None:
        return gate
    body = body or {}
    model = str(body.get("model") or "").strip() or state["cfg"].get("default_model", "")
    if not model:
        return {"output": "[error] no model configured"}
    parts: list[str] = []
    try:
        async for ev in providers.chat(state["cfg"], model, _app_llm_messages(body), []):
            if ev.get("type") == "text" and ev.get("text"):
                parts.append(ev["text"])
    except Exception as e:
        return {"output": f"[error] llm: {type(e).__name__}: {e}"}
    state["store"].log("tool", "app→appChat",
                       {"via": "user_app", "principal": principal.label,
                        "app_id": principal.id})
    return {"output": "".join(parts) or "(empty response)"}


@app.post("/api/apps/agent")
async def api_app_agent(body: dict, request: Request):
    """appAgent: a scoped mini agent — up to 5 steps of the standard Agent loop under
    the APP's principal. The PDP filters and gates every tool per principal exactly as
    in chat turns; risky/ungranted tools raise the normal approval card. body:
    {prompt, tools?: [names], model?} → {output: final text, steps}."""
    principal = _app_principal(request)
    if principal is None:
        return JSONResponse({"error": "app token required (X-App-Token)"}, status_code=401)
    body = body or {}
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt required"}, status_code=400)
    model = str(body.get("model") or "").strip() or state["cfg"].get("default_model", "")
    if not model:
        return {"output": "[error] no model configured", "steps": 0}
    tools = body.get("tools")
    tool_filter = [str(t) for t in tools][:24] if isinstance(tools, list) else None

    async def emit(_ev):
        pass

    async def approver(name, args, reason, offer=None):
        if not state["clients"]:   # headless: nobody to ask
            return False
        return await request_approval(name, args, reason, offer=offer)

    agent = Agent({**state["cfg"], "max_steps": 5}, state["toolbox"], model, emit, approver,
                  tool_filter=tool_filter, principal=principal, surface="gui")
    result = await agent.run([{"role": "user", "content": prompt}])
    state["store"].log("tool", "app→appAgent",
                       {"via": "user_app", "principal": principal.label,
                        "app_id": principal.id, "steps": len(result["steps"])})
    return {"output": result["content"], "steps": len(result["steps"])}


@app.get("/api/apps/context")
async def api_app_context(request: Request):
    """appContext(): what the app runs inside, so it can adapt. theme: the shell does
    not pass a ?theme= param to app iframes today, so this reports 'dark' (the OS
    shell's scheme) until it does."""
    principal = _app_principal(request)
    if principal is None:
        return JSONResponse({"error": "app token required (X-App-Token)"}, status_code=401)
    a = state["store"].get_app(principal.id) or {}
    cfg = state["cfg"]
    return {"app_id": principal.id, "app_name": a.get("name", ""),
            "agent_name": cfg.get("agent_name", "Aria"),
            "model": cfg.get("default_model", ""), "theme": "dark"}


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
    if body.get("schedule_type") == "trigger" or body.get("trigger"):
        msg = state["scheduler"].create_trigger(
            body.get("trigger", ""), body.get("prompt", ""),
            match=body.get("match", ""), path=body.get("path", ""),
            glob=body.get("glob", ""), minutes=float(body.get("minutes") or 30),
            cooldown_secs=int(body.get("cooldown_secs") or 300))
        return {"ok": not msg.startswith("[error]"), "message": msg}
    msg = state["scheduler"].create_task(
        body.get("prompt", ""), body.get("schedule_type", "once"),
        int(body.get("interval_minutes") or 0), body.get("at_time", ""),
        int(body.get("delay_minutes") or 0))
    return {"ok": True, "message": msg}


@app.get("/api/suggestions")
async def api_suggestions():
    """Live proactive suggestions (at most one at a time, by design)."""
    s = state["store"].latest_proactive("suggestion")
    if not s:
        return {"suggestions": []}
    return {"suggestions": [{"id": s["id"], "text": s["text"],
                             "action_prompt": (s["data"] or {}).get("action_prompt", ""),
                             "created_at": s["created_at"]}]}


@app.post("/api/suggestions/{sid}/dismiss")
async def api_dismiss_suggestion(sid: str):
    """Dismissing a suggestion also silences new ones for 24 hours."""
    state["store"].dismiss_proactive(pid=sid)
    return {"ok": True}


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

    # apps call from inside the desktop (GUI); everything else is the headless API gate
    agent = Agent(cfg, toolbox, model, emit, approver, conversation_id=cid,
                  principal=principal,
                  surface="gui" if principal.kind == "app" else "api")
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

def _ws_authed(ws) -> bool:
    """Websockets do not pass through HTTP middleware, so the same gate is
    applied by hand here — a socket is a longer-lived and more capable channel
    than any REST call, and the terminal one is literally a shell."""
    cfg = state["cfg"]
    if not remotemod.enabled(cfg):
        return True
    if cfg["remote"].get("trust_loopback", True) and \
       remotemod.is_loopback((ws.client.host if ws.client else "") or ""):
        return True
    return remotemod.valid_session(cfg, ws.cookies.get(remotemod.COOKIE, ""))


@app.websocket("/ws/vnc")
async def ws_vnc(ws: WebSocket):
    """Relay this WebSocket to wayvnc on loopback — the Remote Desktop transport.

    This is the whole security argument for the feature, so it is worth stating
    plainly. wayvnc has no password of its own, which is why AgentOS has always
    bound it to 127.0.0.1 and refused to put it on the network. Bridging it here
    means the phone authenticates to AGENTOS — passphrase, PBKDF2, signed session
    cookie, backoff, the loopback trust rule — and the VNC port still never
    leaves the machine. Nothing new is exposed; the client just moved into the
    browser.

    Byte-for-byte in both directions with no interpretation: this speaks RFB
    only in the sense that a pipe speaks whatever is poured into it. That is also
    why it is the same job websockify does, and why AgentOS does not need it.
    """
    if not _ws_authed(ws):
        await ws.close(code=4401)
        return
    if not _vnc_running():
        # Refuse rather than hang: a client waiting forever on a socket that will
        # never carry anything is indistinguishable from a broken network.
        await ws.close(code=4404)
        return
    # noVNC asks for the 'binary' subprotocol; accepting it is what stops it
    # falling back to base64 framing, which would double the bytes on a phone.
    sub = "binary" if "binary" in (ws.scope.get("subprotocols") or []) else None
    await ws.accept(subprotocol=sub)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", VNC_PORT)
    except Exception as e:                                        # noqa: BLE001
        state["store"].log("system", f"remote desktop: cannot reach wayvnc — {e}")
        await ws.close(code=1011)
        return

    async def to_vnc():
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                return
            data = msg.get("bytes")
            if data is None and msg.get("text") is not None:
                data = msg["text"].encode()
            if data:
                writer.write(data)
                await writer.drain()

    async def to_client():
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                return
            await ws.send_bytes(chunk)

    tasks = [asyncio.create_task(to_vnc()), asyncio.create_task(to_client())]
    try:
        # Either direction ending ends the session — a half-open RFB connection
        # shows the user a frozen screen rather than a disconnect.
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        with contextlib.suppress(Exception):
            writer.close()
            await writer.wait_closed()
        with contextlib.suppress(Exception):
            await ws.close()


@app.websocket("/ws/terminal")
async def ws_terminal(ws: WebSocket):
    """A real shell on the host, bridged to xterm.js in the Terminal app."""
    if not _ws_authed(ws):
        await ws.close(code=4401)
        return
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


# ---------------------------------------------------------------------------
# Mid-turn message queue
#
# One turn at a time per conversation stays the rule, but typing again while one is
# running is no longer an error: the message is QUEUED. Two things then happen to it —
#   · the running agent triages it at its next step boundary and either folds it into
#     the live run ("now") or leaves it queued ("later"); see Agent._drain_inbox
#   · whatever is still queued when the turn ends starts as the next turn, in order
# The queue is this conversation's visible to-do list until then. It lives in memory
# beside state["turns"], for the same reason: both die with the process, together.
# ---------------------------------------------------------------------------

_QUEUE_MAX = 8   # per conversation — a backlog longer than this is a runaway, not a plan


def _queue_add(cid: str, data: dict) -> dict:
    """Park a message sent into a busy conversation. Nothing is written to the store
    yet: a deferred item is persisted by the turn it eventually starts, a folded-in
    one by the steer hook — never both."""
    item = {"id": uuid.uuid4().hex[:12],
            "text": (data.get("text") or "").strip(),
            "images": _chat_images(data),
            "model": data.get("model") or "",
            "surface": data.get("surface") or "gui",
            "origin": str(data.get("origin") or "user")[:40],
            "context": str(data.get("context") or "")[:4096],
            "status": "queued", "reason": "", "at": time.time()}
    state["queues"].setdefault(cid, []).append(item)
    return item


def _queue_public(cid: str) -> list[dict]:
    """The queue as the UI sees it — text and decision only, never image payloads."""
    return [{"id": i["id"], "text": i["text"], "images": len(i["images"]),
             "status": i["status"], "reason": i["reason"], "at": i["at"]}
            for i in state["queues"].get(cid) or []]


async def _queue_broadcast(cid: str, **extra):
    await state["broadcast"]({"type": "queue_update", "conversation_id": cid,
                              "queue": _queue_public(cid), **extra})


def _queue_drop(cid: str, qid: str = "") -> int:
    """Remove one queued item (or the whole queue). Returns how many went."""
    q = state["queues"].get(cid) or []
    n = len(q)
    keep = [i for i in q if qid and i["id"] != qid]
    if keep:
        state["queues"][cid] = keep
    else:
        state["queues"].pop(cid, None)
    return n - len(keep)


def _steer_hook(cid: str):
    """Given to the running agent: it reports each triage decision here, and the
    queue — the thing the user can see and edit — is updated to match."""
    async def hook(item: dict, mode: str, reason: str):
        item["reason"] = reason
        if mode == "now":
            # folded into the live turn: it is a real user message in this
            # conversation now, so persist it here (the turn it would have
            # started, and would have persisted it, never happens)
            meta = {"steered": True}
            if item["images"]:
                meta["images"] = item["images"]
            with contextlib.suppress(Exception):
                state["store"].add_message(cid, "user", item["text"], meta)
            _queue_drop(cid, item["id"])
        else:
            item["status"] = "deferred"
        await _queue_broadcast(cid, decided={"id": item["id"], "mode": mode,
                                             "reason": reason})
    return hook


async def _queue_flush(cid: str):
    """A turn just ended: start the next queued message as its own turn."""
    q = state["queues"].get(cid) or []
    if not q or cid in state["turns"]:
        return
    item = q.pop(0)
    if not q:
        state["queues"].pop(cid, None)
    data = {"text": item["text"], "images": item["images"], "model": item["model"],
            "surface": item["surface"], "origin": item["origin"],
            "context": item["context"], "conversation_id": cid}
    state["turns"][cid] = {"agent": None, "task": None, "model": ""}   # claim, then start
    state["turns"][cid]["task"] = asyncio.create_task(run_chat(cid, data))
    await _queue_broadcast(cid, started={"id": item["id"], "text": item["text"]})


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
        if model == "hermes":
            # Engine = Hermes: the user picked Hermes as the chat backend. Route the
            # turn to the Hermes CLI, keeping AgentOS's turn lifecycle (working
            # indicator, global turn slot, cancellation, persistence). Hermes replies
            # in one shot rather than token-streaming.
            from . import hermes as hermesmod
            turns[cid] = {"agent": None, "task": asyncio.current_task(), "model": "hermes"}
            knowledge.turn_started()
            started = True
            await evsend({"type": "turn_start", "model": "hermes"})
            await evsend({"type": "status", "message": "Hermes is working…"})
            reply = await hermesmod.ask(text)
            header = "🜁 Hermes\n\n"
            await evsend({"type": "text_delta", "text": header + reply})
            result = {"content": header + reply, "steps": [], "tokens": {"input": 0, "output": 0}}
            header = ""  # already embedded in content — don't double-prefix on persist
        elif mention:
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
            from .policy import SURFACES
            surface = data.get("surface") if data.get("surface") in SURFACES else "gui"
            # Copilot/omnibar turns ride the normal chat path with per-surface
            # context appended to the system prompt (the app's live state, the
            # embedded-panel preamble). Sanitized and capped — it is UI-supplied.
            extra = str(data.get("context") or "")[:4096]
            extra = "".join(ch for ch in extra if ch == "\n" or ch == "\t" or ord(ch) >= 32)
            agent = Agent(cfg, toolbox, model, evsend, approver, conversation_id=cid,
                          surface=surface, extra_system=extra)
            # anything the user queued while this turn was being set up (the slot is
            # claimed before the task starts) is handed over here, once
            for queued in state["queues"].get(cid) or []:
                agent.offer(queued)
            agent.on_steer_decision = _steer_hook(cid)
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
        # the slot is free: whatever the user queued and the agent left for later
        # becomes the next turn, in the order it was typed
        with contextlib.suppress(Exception):
            await _queue_flush(cid)

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


def _salvage_app_html(content: str) -> tuple[str, str, str]:
    """Pull an app out of a reply that wrote it as TEXT instead of calling create_app.

    Models routinely stream a perfectly good ```html block and never make the tool
    call — the build then failed with a screen full of the app's own source. If the
    block really is an app, build it rather than throwing the work away.
    Returns (name, description, html) or ("", "", "")."""
    if not content:
        return "", "", ""
    blocks = re.findall(r"```(?:html|HTML)?\s*\n(.*?)```", content, re.S)
    html = ""
    for b in blocks:
        low = b.lower()
        if ("<!doctype" in low or "<html" in low
                or ("<script" in low and ("<div" in low or "<body" in low))):
            if len(b.strip()) > len(html):
                html = b.strip()
    if len(html) < 200:
        return "", "", ""
    name = desc = ""
    for line in content.splitlines():
        low = line.strip().lower()
        if low.startswith("name:") and not name:
            name = line.split(":", 1)[1].strip().strip('"').strip("'")[:60]
        elif low.startswith("description:") and not desc:
            desc = line.split(":", 1)[1].strip().strip('"').strip("'")[:200]
        if name and desc:
            break
    return name, desc, html


def _resolve_build_model(cfg: dict, avail: list, requested: str = "") -> str:
    """Which model builds this app? The one the USER chose.

    There is deliberately no ranking of model names here. A hardcoded ladder is
    always out of date (it once had no "gemini" in it, so a machine with a Gemini
    key quietly built with a local 9B) and it overrides a preference the user has
    already expressed. Order of authority:

        1. the model picked for THIS build (App Studio's dropdown)
        2. the saved build preference   (Settings → Agent → Build model)
        3. the configured default model (Settings → AI providers)
        4. whatever single model exists

    Anything unavailable is skipped rather than substituted silently.
    """
    ids = [m["id"] for m in avail]
    for cand in (requested,
                 ((cfg.get("build") or {}).get("model") or ""),
                 (cfg.get("default_model") or "")):
        c = (cand or "").strip()
        if c and c.lower() != "auto" and (not ids or c in ids):
            return c
    return ids[0] if ids else ""


def _other_models(avail: list, current: str) -> list:
    """Everything else the user could retry with — for THEM to choose from."""
    return [m["id"] for m in avail if m["id"] != current and "embed" not in m["id"].lower()]


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
    from . import hermes as hermesmod
    hs = await hermesmod.status(cfg)
    out["operate"] = {"scheduled_tasks": len(tasks),
                      "tasks_enabled": sum(1 for t in tasks if t.get("enabled")),
                      "turns_24h": turns_24h, "errors_24h": errors_24h,
                      "turns_running": len(state.get("turns") or {}),
                      "hermes": ("gateway running" if hs["gateway"]
                                 else "installed" if hs["installed"] else "not installed")}
    # the proactivity north star: what share of conversations did the OS start?
    try:
        rows = store.db.execute(
            "select coalesce(origin,'user') o, count(*) c from conversations "
            "where created_at > ? group by o", (time.time() - 7 * 86400,)).fetchall()
        os_origins = {"schedule", "trigger", "briefing", "suggestion"}
        os_turns = sum(r["c"] for r in rows if r["o"] in os_origins)
        user_turns = sum(r["c"] for r in rows if r["o"] not in os_origins)
        total = os_turns + user_turns
        out["operate"]["initiative"] = {
            "os_turns": os_turns, "user_turns": user_turns,
            "pct_os": round(100.0 * os_turns / total, 1) if total else 0.0,
            "window": "7d"}
    except Exception:
        pass

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


# ---- Hermes (companion agent + wrapper: install, config, gateway) ---------

@app.get("/api/hermes/status")
async def hermes_status():
    from . import hermes as hermesmod
    return await hermesmod.status(state["cfg"])


@app.get("/api/hermes/config")
async def hermes_get_config():
    from . import hermes as hermesmod
    return {"text": await hermesmod.read_config(), "path": hermesmod.CONFIG_PATH}


@app.put("/api/hermes/config")
async def hermes_put_config(body: dict):
    from . import hermes as hermesmod
    res = await hermesmod.write_config(body.get("text", ""))
    if res.startswith("[error]"):
        return JSONResponse({"error": res}, status_code=400)
    return {"result": res}


@app.post("/api/hermes/service")
async def hermes_service(body: dict):
    """Wrapper controls: install/update Hermes (streams progress via the
    hermes_setup broadcast) and start/stop its gateway."""
    from . import hermes as hermesmod
    action = (body or {}).get("action", "")
    bcast = state["broadcast"]

    async def note(msg: str):
        with contextlib.suppress(Exception):
            await bcast({"type": "hermes_setup", "message": msg})
        state["store"].log("system", f"hermes: {msg}"[:200])

    if action in ("install", "update"):
        # run detached so the HTTP request returns immediately; progress streams
        async def _do():
            res = await hermesmod.install(state["cfg"], note=note, update=(action == "update"))
            await note(res)
            await bcast({"type": "hermes_setup", "message": res, "done": True})
        asyncio.create_task(_do())
        return {"result": f"Hermes {action} started — watch progress in the Hermes app"}
    if action in ("gateway_start", "gateway_stop"):
        return {"result": await hermesmod.gateway("start" if action == "gateway_start" else "stop")}
    return JSONResponse({"error": "action must be install|update|gateway_start|gateway_stop"},
                        status_code=400)


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
            agent.nudge_unfinished = False   # the build path owns its own retries
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
            model = _resolve_build_model(cfg, _avail)
            if model:
                await bcast({"type": "build_text",
                             "text": f"\n(building with {model.split('/')[-1]} — your default; "
                                     f"change it in App Studio or Settings → Agent)\n"})
                store.log("system", f"build using {model} (user preference)")

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

        # The reply may contain the finished app as text (no tool call). Build it
        # instead of failing: the work is right there.
        if not built and not build.get("cancel_requested"):
            sname, sdesc, shtml = _salvage_app_html(result.get("content") or "")
            if shtml:
                await bcast({"type": "build_text",
                             "text": "\n(the model wrote the app instead of calling create_app — building it)\n"})
                try:
                    out = await toolbox.create_app(sname or (prompt[:40] or "New app"), "",
                                                   sdesc or prompt[:160], shtml)
                    if not str(out).startswith("[error]"):
                        apps = store.list_apps()
                        newest = apps[0] if apps else None
                        if newest:
                            built = newest
                            store.log("system", f"build salvaged from text ({len(shtml)} chars)")
                except Exception as e:
                    store.log("error", f"salvage failed: {type(e).__name__}: {e}")

        if not built and build.get("cancel_requested"):
            store.add_message(cid, "assistant", result["content"] or "(build cancelled)",
                              {"steps": result["steps"]})
            await terminal({"type": "build_error", "message": "build cancelled"})
            return

        # Nothing was produced. Do NOT quietly swap models — say what happened and
        # let the user choose what to run next; the UI turns this into one click.
        if not built:
            if build.get("timed_out"):
                await bcast({"type": "build_text",
                             "text": f"\n(build timed out after {build_timeout}s)\n"})
            try:
                models = await providers.available_models(cfg)
            except Exception:
                models = []
            others = _other_models(models, model)
            await bcast({"type": "build_choice", "model": model, "options": others,
                         "message": f"{model.split('/')[-1]} did not produce an app."})

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
    if not _ws_authed(ws):
        await ws.close(code=4401)
        return
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
                "queues": {c: _queue_public(c) for c in state["queues"]},
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
                    # busy: queue it instead of dropping it. The running agent decides
                    # at its next step boundary whether this belongs to what it is
                    # doing now; anything left over runs as the next turn.
                    if len(state["queues"].get(cid) or []) >= _QUEUE_MAX:
                        await send({"type": "error", "conversation_id": cid,
                                    "message": f"{_QUEUE_MAX} messages are already queued in "
                                               "this chat — let it catch up first."})
                        continue
                    item = _queue_add(cid, data)
                    ag = turns[cid].get("agent")
                    if ag is not None:
                        ag.offer(item)   # triage starts now, not at the boundary
                    await _queue_broadcast(cid, added=item["id"])
                    continue
                if not cid:
                    title = (data.get("title") or "").strip()[:60] or text[:60] or "(image)"
                    # omnibar/copilot threads tag their origin so the sidebar can
                    # group them and the initiative metric stays honest
                    origin = str(data.get("origin") or "user")[:40]
                    if not (origin == "user" or origin == "omni"
                            or origin.startswith("copilot:")):
                        origin = "user"
                    cid = state["store"].create_conversation(title, origin=origin)
                    await send({"type": "conversation", "id": cid, "title": title,
                                "origin": origin})
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
            elif t == "queue_remove":
                cid = data.get("conversation_id")
                if cid and _queue_drop(cid, str(data.get("id") or "")):
                    ag = (turns.get(cid) or {}).get("agent")
                    if ag is not None:   # never triage a message the user took back
                        for gone in [i for i in ag.inbox if i["id"] == data.get("id")]:
                            ag.inbox.remove(gone)
                            if (t := gone.pop("_triage", None)) is not None:
                                t.cancel()
                    await _queue_broadcast(cid, removed=data.get("id"))
            elif t == "abort":
                cid = data.get("conversation_id")
                if cid:  # stop one conversation's turn
                    # stop means stop: the backlog goes with it, or the next queued
                    # message would start the instant this turn dies
                    if _queue_drop(cid):
                        ag = (turns.get(cid) or {}).get("agent")
                        if ag is not None:
                            ag.clear_inbox()
                        await _queue_broadcast(cid, cleared=True)
                    if cid in turns:
                        _stop(turns[cid])
                else:    # legacy/global abort: stop every running turn + build
                    for qcid in list(state["queues"]):
                        _queue_drop(qcid)
                        await _queue_broadcast(qcid, cleared=True)
                    for tinfo in list(turns.values()):
                        if tinfo.get("agent") is not None:
                            tinfo["agent"].clear_inbox()
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
