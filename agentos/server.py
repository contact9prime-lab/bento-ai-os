"""AgentOS server: web UI, WebSocket event stream, REST API."""

import asyncio
import contextlib
import hmac
import json
import os
import re
import secrets
import socket
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from urllib.parse import urlsplit
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               PlainTextResponse, Response)

from . import appcheck
from . import config as cfgmod
from . import fabric as fabricmod
from . import flows as flowsmod
from . import history as historymod
from . import channels as channelsmod
from . import jobs as jobsmod
from . import onboarding as onboardmod
from . import users as usersmod
from . import knowledge
from . import providers
from . import remote as remotemod
from . import usage as usagemod
from .agent import Agent
from .mcp_client import MCP_AVAILABLE, MCPManager
from .memory import Store
from .policy import MAIN, PDP, SURFACES, Principal
from .scheduler import Scheduler
from .telegram import TelegramBridge
from . import whatsapp as whatsappmod
from .whatsapp import WhatsAppBridge
from . import tools
from .tools import ALWAYS_ASK, Toolbox
from .trainforge import TrainForge

UI_DIR = Path(__file__).parent / "ui"

app = FastAPI(title="AgentOS")

class _State(dict):
    """The server's globals, with two keys that answer per USER.

    `state["store"]` and `state["cfg"]` are read in ~250 places. Threading a user
    through all of them would be 250 chances to forget one, and a forgotten one is
    somebody reading a colleague's memory. So the lookup itself resolves: the
    request middleware sets a contextvar, and these two keys follow it.

    On a single-user machine `users.current()` is '' and both fall straight through
    to the machine's own store and config — the files this OS has always used, with
    nothing to migrate and nothing new to go wrong.
    """

    def __getitem__(self, k):
        if usersmod.enabled():
            if k in ("store", "cfg"):
                uid = usersmod.current()
                if k == "store":
                    return usersmod.store_for(uid)
                return usersmod.cfg_for(uid, machine=dict.__getitem__(self, "cfg"))
            if k in PER_USER_SERVICES:
                got = usersmod.services().get(k)
                if got is not None:
                    return got
        return dict.__getitem__(self, k)

    def machine_cfg(self) -> dict:
        """The machine's own config, never a user's view of it. Admin-only writes:
        providers, models, remote access, components."""
        return dict.__getitem__(self, "cfg")


state: _State = _State()  # cfg, store, toolbox, scheduler, clients

#: The three services `_State` also routes per user. Everything else in `state` is
#: either machine-wide (the client set, the compositor) or reaches the right data
#: through `users.Scoped` and so needs only one instance.
PER_USER_SERVICES = ("telegram", "whatsapp", "mcp")


def _build_user_services(uid: str, toolbox, broadcast) -> dict:
    """This person's own bridges, and the loops that drive them.

    A Telegram bridge polls with one bot token; a WhatsApp bridge holds one linked
    device; an MCP manager owns live subprocesses started with somebody's own
    credentials. None of the three can be shared, so each user gets their own —
    built the first time anything reaches for them rather than at startup, because
    most accounts on most machines have configured none of it and an idle bridge
    that was never asked for is a poll loop for nothing.

    They are handed the SAME toolbox: it is `users.Scoped`, so its cfg and store
    already answer for whoever the turn belongs to.
    """
    cfg, store = usersmod.cfg_for(uid, machine=state.machine_cfg()), usersmod.store_for(uid)
    tg = TelegramBridge(cfg, store, toolbox, broadcast)
    wa = WhatsAppBridge(cfg, store, toolbox, broadcast)
    mcp = MCPManager(cfg, store)
    bag = {"telegram": tg, "whatsapp": wa, "mcp": mcp}

    async def _run():
        # Every loop runs inside the owner's context, so anything they reach for —
        # the store, a tool, a turn — resolves to this person and not to whoever
        # happened to be the last request.
        with usersmod.as_user(uid):
            await asyncio.gather(tg.run_forever(), mcp.start(), return_exceptions=True)

    with contextlib.suppress(RuntimeError):     # no loop yet: CLI use, tests
        asyncio.get_running_loop()
        bag["_task"] = asyncio.create_task(_run())
    return bag


@app.on_event("startup")
async def startup():
    cfg = cfgmod.load_config()
    cfgmod.ensure_dirs(cfg)
    store = Store(cfgmod.DB_PATH)
    toolbox = Toolbox(cfg, store)
    clients: set[WebSocket] = set()
    # ws -> the account that owns the socket, from its signed cookie. A TURN
    # belongs to one account and so does its working indicator; without this map
    # there is nobody to address it to but "everyone", which is how one account's
    # spinner, reply and approval card surfaced in another's windows. On a
    # single-user machine every socket's uid is '' and the map changes nothing.
    client_uids: dict = {}

    async def broadcast(event: dict):
        """Machine-wide: a fact true for the whole box (wallpaper, an MCP consent
        prompt). A turn is NOT machine-wide — use `broadcast_user` for it."""
        dead = []
        for ws in clients:
            try:
                await ws.send_text(json.dumps(event))
            except Exception:
                dead.append(ws)
        for ws in dead:
            clients.discard(ws)
            client_uids.pop(ws, None)

    async def broadcast_user(event: dict, uid: str):
        """Deliver a turn's events only to the sessions of the account that owns
        it. The desktop and the phone of that one person both get it and either
        can answer an approval — "any client may answer" was always meant among a
        person's OWN sessions, not across accounts. On a single-user machine
        every uid is '' and this is exactly `broadcast`."""
        dead = []
        for ws in clients:
            if client_uids.get(ws, "") != uid:
                continue
            try:
                await ws.send_text(json.dumps(event))
            except Exception:
                dead.append(ws)
        for ws in dead:
            clients.discard(ws)
            client_uids.pop(ws, None)
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
    # No run_forever: WhatsApp is a webhook, so there is nothing to poll. The bridge
    # exists from startup so its state can be reported before it is configured.
    whatsapp = WhatsAppBridge(cfg, store, toolbox, broadcast)
    toolbox.whatsapp = whatsapp
    toolbox.broadcast = broadcast
    control = fabricmod.ControlPlane(cfg, store, toolbox, broadcast)
    toolbox.fabric = control
    # The control plane knows nothing about Telegram or about the UI; how a result is
    # delivered and how a paused run asks a person are injected, the same way broadcast is.
    control.deliver = _flow_deliver
    control.approvals = _flow_approval
    scheduler.fabric = control
    pdp = PDP(cfg, store)
    pdp.mcp = mcp
    pdp.on_rate_trip = _quarantine
    toolbox.pdp = pdp
    trainforge = TrainForge(cfg, store, broadcast)
    toolbox.trainforge = trainforge
    toolbox.shell = shell_command  # the parity law: shell actions are tools too
    fabricmod.seed_builtins(cfg, store)
    flowsmod.seed_builtin(store)
    state.update(cfg=cfg, store=store, toolbox=toolbox, scheduler=scheduler,
                 mcp=mcp, telegram=telegram, whatsapp=whatsapp,
                 clients=clients, client_uids=client_uids,
                 broadcast=broadcast, broadcast_user=broadcast_user,
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
    # An OAuth server asks for consent from inside its own connection attempt, which
    # has no way to reach a screen. This is the way back out to the user.
    from . import mcp_oauth
    mcp_oauth.set_notifier(broadcast, ui_probe=lambda: bool(clients))
    # A device that was linked before a restart is still linked: WhatsApp keeps the
    # session, so resuming is silent and not resuming would look like it broke.
    # Reconnect only — never START a link nobody asked for. An unlinked machine
    # gets no child process at all.
    # It has to run ONCE PER ACCOUNT, because both things it reads are per-account.
    # `whatsapp` is in `users.USER_KEYS`, so `machine_view()` strips it from the
    # machine config — asking `mode(cfg)` there got the "cloud" default, the `if` was
    # never true, and no linked account was ever resumed. Linking worked (that runs
    # inside a signed-in request), so the channel paired happily and then went silent
    # at the next restart, with nothing logged and the panel still reading "linked".
    #
    # `whatsapp` the local is the machine's bridge; each account has its own, which
    # `state["whatsapp"]` returns inside `as_user`. Resuming through the local one
    # would start a single bridge holding one person's device on everyone's behalf.
    async def _resume_one(uid: str):
        try:
            from . import whatsapp as _wa
            from . import wa_baileys as _wab
            with usersmod.as_user(uid):
                if (_wa.mode(state["cfg"]) == "baileys"
                        and _wab.installed() and _wab.paired()):
                    await state["whatsapp"].start_link()
        except Exception as e:
            store.log("error", f"whatsapp link resume ({uid or 'machine'}): "
                               f"{type(e).__name__}: {e}")

    async def _resume_whatsapp_link():
        # No accounts: '' is the machine itself, and home_for('') is the home this
        # install has always used — one pass, exactly the old behaviour.
        uids = [u["id"] for u in usersmod.list_users()] if usersmod.enabled() else [""]
        for uid in uids:
            await _resume_one(uid)
    asyncio.create_task(_resume_whatsapp_link())
    asyncio.create_task(scheduler.run_forever())
    asyncio.create_task(mcp.start())
    asyncio.create_task(telegram.run_forever())
    # The three services that cannot be shared get built per user, on demand, the
    # first time somebody's request or scheduled job reaches for one.
    usersmod.set_service_factory(
        lambda uid: _build_user_services(uid, toolbox, broadcast))
    asyncio.create_task(knowledge.maintenance_loop(cfg, store, broadcast))
    # attention engine: notification triage (importance + "For you" digest),
    # batch-gated and model-idle-deferred — a no-op without a daemon or model
    from . import attention
    asyncio.create_task(attention.attention_loop(cfg, store,
                                                 lambda: state.get("notifd"), broadcast))
    # Is there a newer version? Checking is automatic; installing never is.
    from . import updates as updmod
    asyncio.create_task(updmod.watch(cfg, store, broadcast, cfgmod.save_config))

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
    # Refresh a catalogue this machine already has; never fetch one it has not
    # asked for. Opening the MCP Store (or any search) syncs it on the spot —
    # see `ensure_index`, which every search path already calls.
    mcp_storemod.ensure_index(store, only_refresh=True, cfg=cfg)
    store.log("system", "AgentOS started")

    # Decide the footprint profile ONCE and write down what was decided. `auto` on
    # every boot would mean a machine that behaves differently after a RAM upgrade
    # with nothing on screen saying why; this leaves an ordinary config key, and
    # `bento profile` can argue with it.
    if str(cfg.get("profile") or "auto") == "auto":
        from . import profile as profmod
        first = cfgmod.is_first_run()
        ok, said = profmod.apply(cfg, profmod.resolve(cfg))
        if ok:
            if first:
                cfg["setup_complete"] = False     # same trap as the model below
            cfgmod.save_config(cfg)
            store.log("system", f"profile: {said}")

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
    if "whatsapp" in state:
        # stop(), not logout(): shutting the server down is a pause, so the next
        # start goes straight back to linked rather than asking for the QR again.
        with contextlib.suppress(Exception):
            await state["whatsapp"].link.stop()
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
    """Token usage aggregated from turn logs: totals, by-model, and a daily series.

    Superseded by `/api/usage` (the `usage` table), which carries cost and can
    group by surface, space and kind. Kept because it reads the turn log, so it
    still answers for conversations that happened before the ledger existed.
    """
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


def _pending_sync(cfg: dict) -> list:
    """`updates.pending` from a worker thread. It is async only because it sits
    beside `check()`; everything it does is subprocess work, so it runs here."""
    from . import updates as updmod
    return asyncio.run(updmod.pending(cfg, limit=15))


@app.get("/api/update")
async def api_update_status(check: bool = False):
    """What version this is, and whether there is a newer one.

    `check=false` answers from the last check so opening Settings is instant;
    `check=true` goes and looks.
    """
    from . import updates as updmod
    cfg = state["cfg"]
    ok, why = updmod.can_apply(cfg)
    if check:
        res = await updmod.check(cfg, force=True)
        cfgmod.save_config(cfg)
    else:
        c = updmod.conf(cfg)
        behind = int(c.get("last_behind") or 0)
        res = {"current": updmod.current(), "latest": c.get("last_seen", ""),
               # Both halves of the last check, not just the version: a machine
               # that was eight commits behind an hour ago must not open Settings
               # saying "up to date".
               "update_available": bool(behind or (c.get("last_seen")
                                        and updmod.is_newer(c["last_seen"], updmod.current()))),
               "behind": behind, "ahead": 0,
               "on_branch": c.get("last_on_branch", ""),
               "tracks": c.get("branch") or updmod.DEFAULT_BRANCH,
               "mismatch": bool(c.get("last_on_branch")
                                and c.get("last_on_branch") != (c.get("branch")
                                                                or updmod.DEFAULT_BRANCH)),
               "notes": "", "checked_at": c.get("last_check") or 0.0, "error": ""}
    # The commits an update would bring. Only on an explicit check — `pending()`
    # fetches, and a status route that opens Settings instantly must not do
    # network work nobody asked for.
    # In a thread: pending() shells out to `git fetch`, which is a blocking
    # subprocess of up to two minutes. Awaited directly it stalls the whole event
    # loop — every other request, every WebSocket, every turn — and from the About
    # panel that looks exactly like "check for updates does nothing".
    changes = await asyncio.to_thread(_pending_sync, cfg) if check else []
    return {**res, "can_apply": ok, "blocked_reason": why, "changes": changes,
            "branch": updmod.conf(cfg).get("branch"),
            "enabled": updmod.conf(cfg).get("enabled", True)}


@app.get("/api/changelog")
async def api_changelog(limit: int = 5):
    """What this build contains. Read from the changelog on disk rather than a
    remote, so it describes the code that is actually running."""
    from . import updates as updmod
    return {"version": updmod.current(),
            "entries": updmod.local_notes(max(1, min(20, limit)))}


@app.post("/api/restart")
async def api_restart(request: Request):
    """Restart this server. Loopback only, and the caller is told HOW it restarted.

    This exists because `bento restart` cannot do the job from outside. Where a
    service manager owns the process the CLI could kickstart it directly — but the
    common case, and the one that caused the bug this was written for, is a server
    started by hand in a terminal. There is no supervisor to ask, and
    `desktop.restart_service()` falls back to re-exec'ing THE CURRENT PROCESS: run
    from the CLI that would fork a second server beside the stale one, both bound to
    the same database, with the old one still holding the port. So the CLI asks the
    running server to re-exec ITSELF, which is the process that fallback was written
    for, and the one that actually needs replacing.

    Loopback only, like `/api/update` and for a weaker version of the same reason: a
    restart is not destructive, but dropping every open session and every in-flight
    turn is not a thing a remote browser should be able to do to the machine.

    The restart is scheduled after the response flushes, or the caller cannot tell
    "it restarted" from "it died".
    """
    if not remotemod.is_loopback(_client_addr(request)):
        return JSONResponse({"error": "a restart can only be started from this machine"},
                            status_code=403)
    from . import desktop as desktopmod

    async def _finish():
        await state["broadcast"]({"type": "reload", "delay": 6000})
        await asyncio.sleep(0.5)
        desktopmod.restart_service()

    state["store"].log("system", "restart requested")
    asyncio.create_task(_finish())
    # how, not just that: "restarting the AgentOS process" and "restarting the
    # AgentOS LaunchAgent" are different answers to "will this survive a reboot?"
    return {"ok": True, "how": desktopmod.restart_method()}


@app.post("/api/update")
async def api_update_apply(request: Request, body: dict | None = None):
    """Install the update: pull, sync, verify, then restart the service and tell
    every open page to reload.

    Loopback only. This replaces the code that enforces every other permission on
    this machine, so it is not something a remote browser gets to do — the same
    rule the WhatsApp link route follows, for a larger reason.

    The restart is scheduled AFTER the response flushes. Restarting inside the
    handler kills the connection carrying the result, and a browser cannot tell
    "the update worked and the server went away" from "the update failed".
    """
    if not remotemod.is_loopback(_client_addr(request)):
        return JSONResponse({"error": "an update can only be started from this machine"},
                            status_code=403)
    from . import updates as updmod
    body = body or {}
    if (body.get("skip") or "").strip():          # "not now, and stop asking for this one"
        updmod.conf(state["cfg"])["skipped"] = str(body["skip"]).strip()
        cfgmod.save_config(state["cfg"])
        return {"ok": True, "skipped": body["skip"]}

    async def say(msg):
        await state["broadcast"]({"type": "update_progress", "message": msg})

    loop = asyncio.get_running_loop()
    res = await updmod.apply(
        state["cfg"], run_tests=bool(body.get("run_tests", True)),
        log=lambda m: loop.call_soon(asyncio.ensure_future, say(m)))
    state["store"].log("system", f"update: {res}")
    if not res.get("ok"):
        await state["broadcast"]({"type": "update_done", **res})
        return JSONResponse(res, status_code=400)

    async def _finish():
        # The page first: it must be told to come back, and by whom, before the
        # server that would tell it disappears.
        await state["broadcast"]({"type": "update_done", **res})
        await asyncio.sleep(1.0)
        await state["broadcast"]({"type": "reload", "delay": 6000})
        await asyncio.sleep(0.5)
        from . import desktop as desktopmod
        desktopmod.restart_service()
    asyncio.create_task(_finish())
    return {**res, "restarting": True}


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
    # Which OS events a flow trigger could actually fire here, and why not. Two of
    # the four need AgentOS to own the session (the notification daemon and the
    # login hook above), so on a hosted or headless box the Flows editor must grey
    # them with the reason rather than offer a control that can never fire.
    from . import flows as flowsmod
    state_["os_events"] = {ev: flowsmod.os_event_problem(ev, state_.get("mode"))
                           for ev in flowsmod.OS_EVENTS}
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
    """The catalogue, resolved for the distro this machine actually runs.

    `os` travels with it because the panel has to be able to say "AgentOS does
    not know how this distro installs packages" rather than showing buttons that
    would run a command from somebody else's operating system.
    """
    from . import components, osdetect
    d = osdetect.detect()
    return {"components": components.catalog(),
            "os": {"describe": osdetect.describe(), "family": d["family"],
                   "manager": d["manager"], "pretty": d["pretty"],
                   "session_capable": d["session_capable"], "why": d["why"]}}


@app.post("/api/components/install")
async def api_component_install(body: dict, request: Request):
    """Install one catalogue entry.

    The first-run wizard's "install Ollama for me" and the WhatsApp bridge card
    have both always POSTed here; there was no such route, so both buttons 404'd
    silently while reporting "could not install". Loopback-only — this changes
    the machine.
    """
    if not remotemod.is_loopback(_client_addr(request)):
        return JSONResponse({"error": "only from this machine"}, status_code=403)
    from . import components as compmod
    cid = str((body or {}).get("id") or "")
    res = await compmod.install(cid)
    state["store"].log("system", f"component '{cid}': {res.get('message', '')}"[:200])
    return res


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
    """Everything that can answer a turn: provider models AND enabled engines.

    Engines belong here rather than behind a second probe, so the chat picker,
    the Models app and anything else that lists what can answer all agree — an
    executor you switched on in Settings shows up everywhere at once, and one
    that is switched off disappears everywhere at once.
    """
    from . import executors as execmod
    cfg = state["cfg"]
    # Every executor this machine knows, from the roster — not just Claude Code,
    # and not only when it happens to be enabled. The picker's job is to say what
    # could answer here; an executor that is installed but switched off, or not
    # installed at all, is a fact the user needs in order to choose, so it is
    # listed with the reason rather than left out.
    env = execmod.envelope_from(cfg, str(cfgmod.AGENTOS_HOME / "workspace"))
    engines = [{
        "id": r["id"], "name": r["title"], "kind": "executor",
        "available": bool(r["installed"]),
        # an executor that is missing says why rather than sitting in the picker
        # as a choice that fails on the first turn
        "reason": r["why_not"],
        "detail": r["version"],
        "licence": r["licence"],
        "install": _component_offer(r["id"]),
        "envelope": env.describe() if r["id"] == "claude-code" else {},
    } for r in execmod.roster() if not r.get("builtin")]

    return {"models": await providers.available_models(cfg),
            "default": cfg.get("default_model", ""),
            "engines": engines,
            # which engine this machine forwards to ("" = it answers itself)
            "engine": execmod.resolve_engine(cfg)}


@app.get("/api/profile")
async def api_profile():
    """What this machine has decided to keep, and what it is keeping right now."""
    from . import mcp_store as mcpmod
    from . import profile as profmod
    cfg = state["cfg"]
    try:
        cached = mcpmod.INDEX_PATH.stat().st_size
    except OSError:
        cached = 0
    return {"profile": cfg.get("profile", "auto"),
            "resolved": profmod.resolve(cfg),
            "description": profmod.describe(cfg),
            "machine": profmod.machine(),
            "retention": cfg.get("retention", {}),
            "mcp_cache_bytes": cached}


@app.get("/api/brains")
async def api_brains(refresh: bool = False):
    """Who can answer here, and what each of them can run.

    One list: local providers, cloud providers and other agents, each owning the
    models it can actually wake up. Every surface that asks "what is this
    machine's brain" reads this — the chat header, the menu-bar chip, Settings,
    the wizard — so the answer cannot differ between two of them.
    """
    from . import executors as execmod
    cfg = state["cfg"]
    if refresh:                      # the panel's ↻ button: ask the machine again
        await asyncio.to_thread(execmod.forget_probes)
    models = await providers.available_models(cfg)
    # `brains()` probes the roster, and a probe runs `--version` on real
    # binaries. Awaiting that on the event loop is how the update check froze
    # the whole server, so it goes to a thread. The probes are cached for five
    # minutes on top of that — every surface asks this question, and on a small
    # machine spawning three processes per Settings repaint is felt.
    return await asyncio.to_thread(execmod.brains, cfg, models)


@app.put("/api/brain")
async def api_set_brain(body: dict):
    """Choose the executor AND its model in one write."""
    from . import executors as execmod
    cfg = state["cfg"]
    executor = str((body or {}).get("executor") or "")
    model = str((body or {}).get("model") or "")
    models = await providers.available_models(cfg)
    state_now = await asyncio.to_thread(execmod.brains, cfg, models)
    ex = next((e for e in state_now["executors"] if e["id"] == executor), None)
    # Forwarding to another agent reconfigures the MACHINE — every surface, for
    # everyone on it — while a provider model is each person's own choice
    # (`users.USER_KEYS`). So the admin check is on the kind, not on the route.
    if ex and ex["kind"] == "agent" and usersmod.enabled() and not usersmod.is_admin(usersmod.current()):
        return JSONResponse({"error": "only an admin can change which agent answers "
                                      "on this machine"}, status_code=403)
    ok, msg = await asyncio.to_thread(execmod.set_brain, cfg, executor, model, models)
    if not ok:
        return JSONResponse({"error": msg}, status_code=400)
    cfgmod.save_config(cfg)
    state["store"].log("system", f"brain: {msg}")
    await state["broadcast"]({"type": "config"})
    out = await asyncio.to_thread(execmod.brains, cfg, models)
    return {"ok": True, "message": msg, **out}


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


@app.get("/api/tunnel")
async def api_tunnel():
    """How to reach this machine from elsewhere, and what could publish it."""
    from . import tunnel as tunmod
    try:
        return await asyncio.wait_for(tunmod.status(state["cfg"]), timeout=40)
    except Exception as exc:
        return {"published": False, "url": "", "reachable": [], "providers": [],
                "gate": "", "error": str(exc)[:200]}


@app.post("/api/tunnel")
async def api_tunnel_set(body: dict):
    """Publish this machine, or take it offline again."""
    from . import tunnel as tunmod
    action = str((body or {}).get("action") or "")
    if action == "stop":
        ok, message = await tunmod.stop(state["cfg"])
        return JSONResponse({"ok": ok, "message": message},
                            status_code=200 if ok else 400)
    if action == "install":
        ok, message = await tunmod.install(str(body.get("provider") or ""))
        return JSONResponse({"ok": ok, "message": message},
                            status_code=200 if ok else 400)
    if action != "start":
        return JSONResponse({"ok": False, "error": "action must be start|stop|install"},
                            status_code=400)
    ok, message, url = await tunmod.start(
        state["cfg"], str(body.get("provider") or "tailscale"),
        public=bool(body.get("public")))
    return JSONResponse({"ok": ok, "message": message, "url": url},
                        status_code=200 if ok else 400)


@app.post("/api/executors/install")
async def api_executor_install(body: dict):
    """Install Claude Code, with progress. The command was shown before this ran."""
    from . import executors as execmod
    if str((body or {}).get("id") or "claude_code") != "claude_code":
        return JSONResponse({"ok": False, "error": "unknown executor"}, status_code=400)

    async def note(line: str):
        await state["broadcast"]({"type": "executor_install", "line": line})

    ok, message = await execmod.install(note)
    await state["broadcast"]({"type": "executor_install", "done": True,
                              "ok": ok, "message": message})
    return JSONResponse({"ok": ok, "message": message},
                        status_code=200 if ok else 400)


@app.get("/api/channels")
async def api_channels():
    """Every way to reach this machine from elsewhere, and what each one still needs."""
    from . import channels as chmod
    # `carried` is kept as an empty list rather than dropped: it is a documented
    # response field, and a surface that still reads it should see "none" instead
    # of a KeyError. It goes when the next breaking API revision goes.
    return {"channels": chmod.state(state["cfg"], state.get("store")),
            "carried": [],
            "postures": [{"id": p, "label": chmod.POSTURE_LABELS[p],
                          "help": chmod.POSTURE_HELP[p]} for p in chmod.POSTURE_LABELS]}


@app.put("/api/channels/{channel_id}")
async def api_channel_save(channel_id: str, body: dict):
    from . import channels as chmod
    ok, message = chmod.save(state["cfg"], channel_id, body or {})
    cfgmod.save_config(state["cfg"])
    await state["broadcast"]({"type": "channels"})
    if not ok:
        return JSONResponse({"ok": False, "error": message}, status_code=400)
    return {"ok": True, "message": message,
            "channels": chmod.state(state["cfg"], state.get("store"))}


@app.get("/api/executors")
async def api_executors(refresh: bool = False):
    """Which other agents on this machine AgentOS can hand a task to.

    Reports the reason and the fix when there is none, rather than leaving a dead
    control — the same contract /api/platform keeps for capabilities.
    """
    from . import executors as execmod
    if refresh:
        await asyncio.to_thread(execmod.forget_probes)
    conf = (state["cfg"].get("executors") or {}).get("claude_code") or {}
    info = execmod.available()
    workspace = conf.get("workspace") or str(cfgmod.AGENTOS_HOME / "workspace")
    env = execmod.Envelope(
        workspace=workspace,
        tools=tuple(conf.get("tools") or execmod.DEFAULT_TOOLS),
        model=conf.get("model", ""),
        budget_usd=float(conf.get("budget_usd") or execmod.default_budget()),
        allow_source=bool(conf.get("allow_source")),
    ).sanitized()
    return {"executors": [{
        "id": "claude_code", "title": "Claude Code",
        "what": "Files, shell, code and research inside a directory you choose. "
                "It has no screen or keyboard — AgentOS keeps the desktop.",
        "enabled": bool(conf.get("enabled")),
        "config": {"workspace": env.workspace, "tools": list(env.tools),
                   "model": env.model, "budget_usd": env.budget_usd,
                   "allow_source": env.allow_source},
        "source_root": execmod.source_root(),
        "envelope": env.describe(),
        "billing": execmod.billing(),
        **info,
    }],
    # Every brain this machine could answer with, installed or not. The list
    # above stays Claude-Code-shaped because it carries that executor's envelope
    # (workspace, tools, budget) which the others do not have; this one is the
    # roster the model picker, AI Providers and the onboarding brain step read,
    # so none of them has to hardcode a name. A missing executor is REPORTED with
    # what would install it — hidden reads as "this OS cannot".
    "roster": [{**r, "install": _component_offer(r["id"])} for r in execmod.roster()],
    "engine": execmod.resolve_engine(state["cfg"])}


def _component_offer(executor_id: str) -> dict:
    """The install offer for an executor, from the components catalogue.

    Read from there rather than restated here, so the licence and the exact
    command on the picker are the same ones the consent screen shows. An executor
    with no component (OpenClaw) answers {} — used if present, never installed by
    a command AgentOS cannot state truthfully.
    """
    from . import components as comps
    for c in comps.catalog():
        if c["id"] == executor_id:
            return {"command": c["command"], "licence": c["licence"],
                    "available": c["available"], "reason": c["reason"],
                    "unlocks": c["unlocks"]}
    return {}


@app.put("/api/config")
async def api_put_config(patch: dict):
    # Machine settings are the machine's. Refusing here rather than letting the
    # save drop them quietly is the difference between "you cannot change that"
    # and a Settings page that appears to work and does nothing — which is the
    # version somebody reports as a bug six months later.
    mine = usersmod.current()
    if usersmod.enabled() and not usersmod.is_admin(mine):
        theirs = [k for k in (patch or {}) if k not in usersmod.USER_KEYS]
        if theirs:
            return JSONResponse(
                {"error": "only an admin can change machine settings on this machine "
                          f"({', '.join(sorted(theirs)[:6])})"}, status_code=403)
    cfg = state["cfg"]
    for key in ("default_model", "autonomy", "max_steps", "workspace", "agent_name",
                "policies", "sandbox", "steer_queued_messages"):
        if key in patch:
            cfg[key] = patch[key]
    if isinstance(patch.get("updates"), dict):
        from . import updates as updmod
        u = updmod.conf(cfg)
        for k in ("enabled", "branch", "check_interval_hours"):
            if k in patch["updates"]:
                u[k] = patch["updates"][k]
        # Turning checks back on means "tell me about the current one again":
        # a skip that outlived the decision is a machine that never updates.
        if patch["updates"].get("enabled"):
            u["skipped"] = ""
    if isinstance(patch.get("build"), dict) and "model" in patch["build"]:
        cfg.setdefault("build", {})["model"] = str(patch["build"]["model"] or "")[:80]
    if isinstance(patch.get("locale"), dict):
        from . import localeinfo
        lo = cfg.setdefault("locale", {})
        for k in localeinfo.FIELDS:
            if k in patch["locale"]:
                lo[k] = str(patch["locale"][k] or "")[:64]
    if "profile" in patch:
        # Through profile.apply(), never a bare key write: the profile's job is to
        # SET the ordinary keys (retention, and what the MCP cache does), and a
        # config that recorded "lite" without them would be a label with no effect.
        from . import profile as profmod
        ok_p, said = profmod.apply(cfg, str(patch["profile"] or "auto"))
        if not ok_p:
            return JSONResponse({"error": said}, status_code=400)
        state["store"].log("system", f"profile: {said}")
        # Somebody switching to light mode is usually asking for the space back
        # NOW, not at the next maintenance pass half an hour from now. It still
        # waits for a search in flight to finish — see `release_if_idle`.
        from . import mcp_store as mcpmod
        freed = await asyncio.to_thread(mcpmod.housekeeping, cfg)
        if freed:
            state["store"].log("system", freed)
    if "engine" in patch:
        from . import executors as execmod
        want = str(patch["engine"] or "aria")
        # An engine this machine cannot actually reach would silently break every
        # surface at once, so refuse it here rather than at the first turn.
        # Asked of the roster rather than by name. Hardcoding "claude-code" here
        # meant every executor added afterwards could be selected while missing,
        # and the failure surfaced on the first turn instead of at the click.
        if want != "aria":
            info = execmod.probe(want)
            if not info.get("installed"):
                return JSONResponse(
                    {"error": info.get("why_not") or f"{want} is not installed on this machine"},
                    status_code=400)
        cfg["engine"] = want if want in execmod.ENGINES else "aria"
    if isinstance(patch.get("executors"), dict):
        from . import executors as execmod
        ex = cfg.setdefault("executors", {}).setdefault("claude_code", {})
        got = patch["executors"].get("claude_code") or {}
        if "enabled" in got:
            ex["enabled"] = bool(got["enabled"])
        if "workspace" in got:
            ex["workspace"] = str(got["workspace"] or "")[:400]
        if "model" in got:
            ex["model"] = str(got["model"] or "")[:80]
        if got.get("budget_usd") is not None:
            # not `or 2.0` — 0 is falsy, and turning "spend nothing" into the
            # default budget is a widening the user never asked for
            ex["budget_usd"] = max(0.05, min(float(got["budget_usd"]),
                                             execmod.MAX_BUDGET_USD))
        if isinstance(got.get("tools"), list):
            # Only tools we know how to hand over. An unrecognised name would be
            # passed to the CLI verbatim and widen the envelope to whatever it
            # made of it — which is exactly the thing the envelope exists to stop.
            ex["tools"] = [t for t in got["tools"] if t in execmod.KNOWN_TOOLS]
        if "allow_source" in got:
            # Letting the OS rewrite itself is its own decision, never implied by
            # merely turning an executor on.
            ex["allow_source"] = bool(got["allow_source"])
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
    if isinstance(patch.get("security"), dict):
        from .policy import TAINT_MODES
        if patch["security"].get("taint") in TAINT_MODES:
            cfg.setdefault("security", {})["taint"] = patch["security"]["taint"]
    if isinstance(patch.get("history"), dict):
        h = cfg.setdefault("history", {})
        for k in ("tool_trace", "compact", "model"):
            if k in patch["history"]:
                h[k] = patch["history"][k]
        for k, lo, hi in (("trace_chars", 0, 8000), ("budget_tokens", 0, 1_000_000)):
            if isinstance(patch["history"].get(k), (int, float)):
                h[k] = max(lo, min(int(patch["history"][k]), hi))
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


@app.post("/api/conversations")
async def api_new_conversation(body: dict | None = None):
    """Open an empty thread up front.

    The omnibar needs this: its turn can sit queued behind another one for
    thirty seconds, and until the server answered there was no conversation to
    show, so "Open in Chat" landed somewhere else and the sidebar looked as if
    nothing had been asked. A thread that exists from the moment you press
    Enter is the whole difference between a bar that reports and one that eats
    what you typed.
    """
    from . import spaces as spacemod
    from .policy import SURFACES
    b = body or {}
    origin = str(b.get("origin") or "user")[:40]
    title = str(b.get("title") or "New chat")[:200]
    surface = b.get("surface") if b.get("surface") in SURFACES else "gui"
    # The space is the surface's active one, exactly as the socket does it — the
    # conversation decides the turn's space, so it has to be decided here too.
    space = str(b.get("space_id") or "") or spacemod.active_for(state["cfg"], surface)
    cid = state["store"].create_conversation(title, origin=origin, space_id=space)
    # Only the account that created it: a conversation lives in that user's own
    # database, so announcing it to every socket would put a stranger's new chat
    # in another person's sidebar.
    await state["broadcast_user"]({"type": "conversation", "id": cid, "title": title,
                                   "origin": origin, "space_id": space},
                                  str(usersmod.current() or ""))
    return {"id": cid, "title": title, "origin": origin, "space_id": space}


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


# ---- WhatsApp ---------------------------------------------------------------
#
# The webhook is the only route in this file, besides the flow hooks, that is meant
# to be reachable from the open internet. Everything about it is therefore written
# refusal-first: no signature, no body; wrong signature, no body; unknown verify
# token, no challenge. Meta is told 200 in every case it should be, because a 500
# here makes Meta retry the same delivery for hours.

@app.get("/api/whatsapp")
async def api_whatsapp(request: Request):
    """State plus the one thing that is useless to withhold: the callback URL.

    Reachability is probed rather than assumed — a webhook channel that is 'on' but
    unreachable receives nothing, forever, with no error anywhere, and that is the
    single most confusing state this integration can be in.
    """
    from . import whatsapp as wamod
    info = state["whatsapp"].info()
    reach = await wamod.reachability(state["cfg"])
    # Fall back to how this request actually arrived, so a machine already behind a
    # reverse proxy is not told to go and set up a tunnel it does not need.
    base = str(request.base_url).rstrip("/")
    if not reach["reachable"] and base.startswith("https://"):
        reach = {"reachable": True, "base": base, "via": "this address",
                 "webhook": wamod.webhook_url(state["cfg"], base), "why": ""}
    return {**info, "reach": reach}


@app.put("/api/whatsapp")
async def api_put_whatsapp(body: dict):
    """Settings, written through the channel registry so there is one writer.

    A blank secret means "leave it alone", never "clear it" — a saved secret is shown
    as set rather than echoed back, so an empty box is the normal state of a
    configured channel and not an instruction to erase it.
    """
    patch = {k: v for k, v in (body or {}).items()
             if k in ("phone_number_id", "access_token", "app_secret", "verify_token",
                      "enabled", "posture", "mode")}
    ok, msg = channelsmod.save(state["cfg"], "whatsapp", patch)
    if body.get("unpair"):
        state["cfg"].setdefault("whatsapp", {})["owner_wa_id"] = ""
        state["cfg"].setdefault("channels", {}).setdefault("whatsapp", {})["owner_wa_id"] = ""
    cfgmod.save_config(state["cfg"])
    return {"ok": ok, "message": msg, **state["whatsapp"].info()}


@app.put("/api/whatsapp/chats/{wa_id}")
async def api_whatsapp_chat(wa_id: str, body: dict):
    if "allowed" in body:
        state["store"].wa_set_allowed(wa_id, 1 if body["allowed"] else 0)
        state["store"].log("whatsapp",
                           f"{wa_id} {'enabled' if body['allowed'] else 'blocked'}")
    return {"ok": True}


@app.delete("/api/whatsapp/chats/{wa_id}")
async def api_whatsapp_chat_delete(wa_id: str):
    state["store"].wa_delete_chat(wa_id)
    return {"ok": True}


@app.post("/api/whatsapp/link")
async def api_whatsapp_link(request: Request):
    """Start the WhatsApp Web bridge and hand back a QR to scan.

    Pairing is not a separate verb: starting the link IS the pairing flow, because a
    bridge with no stored credentials asks for a scan and one with them just
    connects. The QR arrives a moment after the child process does, so this waits
    briefly for either outcome rather than returning "starting…" and making the UI
    invent a poll.
    """
    # Loopback only, like every other route that changes what this machine is
    # connected to: a linked WhatsApp device IS a credential, and starting one
    # is not something a remote browser should be able to do on your behalf.
    if not remotemod.is_loopback(_client_addr(request)):
        return JSONResponse({"error": "only from this machine"}, status_code=403)
    from . import whatsapp as wamod
    from . import wa_baileys
    gap = wa_baileys.why_not()
    if gap:
        return JSONResponse({"error": gap, "component": "whatsapp-bridge"},
                            status_code=428)
    # Choosing to link IS choosing the transport; making the user set a mode dropdown
    # first would be a second step for a decision they already made.
    ch = state["cfg"].setdefault("channels", {}).setdefault("whatsapp", {})
    ch["mode"] = "baileys"
    ch["enabled"] = True
    cfgmod.save_config(state["cfg"])
    err = await state["whatsapp"].start_link()
    if err:
        return JSONResponse({"error": err}, status_code=500)
    link = state["whatsapp"].link
    for _ in range(int(wa_baileys.PAIR_TIMEOUT * 2)):
        if link.state in ("qr", "ready", "error"):
            break
        await asyncio.sleep(0.5)
    await state["broadcast"]({"type": "config"})
    if link.state == "error":
        return JSONResponse({"error": link.error or "the bridge failed to start"},
                            status_code=500)
    return {"ok": True, **link.info()}


@app.delete("/api/whatsapp/link")
async def api_whatsapp_unlink(request: Request):
    """Unlink the device, forget the credentials, and clear the paired owner.
    Not merely a disconnect: the stored keys ARE the linked device."""
    if not remotemod.is_loopback(_client_addr(request)):
        return JSONResponse({"error": "only from this machine"}, status_code=403)
    res = await state["whatsapp"].unlink()
    await state["broadcast"]({"type": "config"})
    return {"ok": True, "result": res, **state["whatsapp"].info()}


@app.post("/api/whatsapp/test")
async def api_whatsapp_test():
    return {"result": await state["whatsapp"].send(
        "▲ Test message from AgentOS — the bridge works.")}


@app.get(whatsappmod.webhook_path())
async def api_whatsapp_verify(request: Request):
    """Meta's one-time handshake. Echo the challenge as plain text, or 403.

    Compared with `compare_digest` inside the bridge: this value is chosen by the
    user and checked against a value from the internet, which is the exact shape of
    a timing oracle.
    """
    q = request.query_params
    ch = state["whatsapp"].verify_challenge(q.get("hub.mode", ""),
                                            q.get("hub.verify_token", ""),
                                            q.get("hub.challenge", ""))
    if ch is None:
        return PlainTextResponse("no", status_code=403)
    return PlainTextResponse(ch)


@app.post(whatsappmod.webhook_path())
async def api_whatsapp_webhook(request: Request):
    """A delivery from Meta.

    The signature is checked over the RAW body, before anything parses it. Reading
    `await request.json()` and re-serialising would change the bytes, and the check
    would then fail on every legitimate message — the classic way this ends up
    deleted rather than fixed.

    Handling is dispatched to a task and 200 is returned immediately: Meta's webhook
    timeout is seconds, and an agent turn is not. Blocking here makes Meta retry the
    same message, which is how one sentence becomes four agent runs.
    """
    from . import whatsapp as wamod
    c = wamod.conf(state["cfg"])
    if not c.get("enabled"):
        return JSONResponse({"error": "whatsapp is off"}, status_code=404)
    raw = await request.body()
    if not wamod.verify_signature(c.get("app_secret") or "", raw,
                                  request.headers.get("x-hub-signature-256", "")):
        state["store"].log("whatsapp",
                           f"refused an unsigned webhook delivery from {_client_addr(request)}")
        return JSONResponse({"error": "bad signature"}, status_code=403)
    try:
        body = json.loads(raw or b"{}")
    except Exception:
        return {"ok": True}     # malformed: swallow it, or Meta retries it all day
    asyncio.create_task(state["whatsapp"].handle(body))
    return {"ok": True}


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


@app.get("/api/mcp/catalog")
async def api_mcp_catalog():
    """The curated catalogue: first-party servers the public registry does not list.

    Kept separate from search so the Store can show it as a storefront before anyone
    types — see mcp_catalog.py for why these cannot simply be found."""
    from . import mcp_catalog
    have = set((state["cfg"].get("mcp_servers") or {}).keys())
    cands = mcp_catalog.all_candidates()
    for c in cands:
        c["installed"] = c["key"] in have
    return {"catalog": cands, "categories":
            [{"id": i, "title": t} for i, t in mcp_catalog.CATEGORIES]}


@app.get("/api/mcp/oauth/callback/{name}")
async def api_mcp_oauth_callback(name: str, code: str = "", state_: str = "",
                                 error: str = "", request: Request = None):
    """Where the authorisation server sends the browser back.

    The server name is in the PATH rather than in `state`, because `state` is
    generated inside the SDK and is not ours to encode into — see mcp_oauth.py. This
    returns a page a human reads, not JSON: the audience is a browser tab."""
    from . import mcp_oauth
    qp = dict(request.query_params) if request is not None else {}
    st = qp.get("state") or state_ or None
    err = error or qp.get("error", "")
    ok = mcp_oauth.resolve(name, code or qp.get("code", ""), st, error=err)
    if not ok:
        msg, detail = "Nothing was waiting", (
            f"AgentOS is not currently signing in to '{name}'. The attempt may have "
            "timed out — press Connect again in the Store.")
    elif err:
        msg, detail = "Sign-in refused", f"{name} reported: {err}"
    else:
        msg, detail = "Connected", (
            f"AgentOS is signed in to {name}. You can close this tab — the server "
            "appears in the Store and its tools are available to the agent.")
    body = f"""<!doctype html><meta charset=utf-8><title>{msg} — AgentOS</title>
<body style="background:#0e1116;color:#e6ebf2;font:15px/1.6 system-ui,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="max-width:30rem;padding:2rem;text-align:center">
<div style="font-size:1.4rem;margin-bottom:.6rem;color:#5eead4">{msg}</div>
<div style="color:#8a94a6">{detail}</div></div>"""
    return HTMLResponse(body, status_code=200 if ok and not err else 400)


@app.post("/api/mcp/oauth/{name}/connect")
async def api_mcp_oauth_connect(name: str):
    """(Re)start authorisation for one server by reconnecting it.

    There is no separate "log in" call: connecting IS the flow. The provider asks for
    consent only when it has no usable token, so this is also the retry path after a
    timeout, and a no-op-shaped success when the server is already signed in."""
    from . import mcp_oauth
    conf = (state["cfg"].get("mcp_servers") or {}).get(name)
    if not conf:
        return JSONResponse({"error": f"no MCP server named '{name}'"}, status_code=404)
    if (conf.get("auth") or "") != "oauth":
        return JSONResponse({"error": f"'{name}' does not use OAuth"}, status_code=400)
    if not mcp_oauth.HAVE_OAUTH:
        return JSONResponse({"error": "the installed 'mcp' package is too old for OAuth"},
                            status_code=501)
    await state["mcp"].reload()
    # The consent URL is produced by the connection attempt, a moment later.
    for _ in range(60):
        await asyncio.sleep(0.1)
        url = mcp_oauth.pending_url(name)
        if url:
            return {"ok": True, "url": url, "authorized": False}
    return {"ok": True, "url": "", "authorized": mcp_oauth.has_tokens(name)}


@app.delete("/api/mcp/oauth/{name}")
async def api_mcp_oauth_disconnect(name: str):
    """Sign out: forget the tokens and the registered client, then reconnect so the
    server's state on screen matches reality immediately."""
    from . import mcp_oauth
    mcp_oauth.cancel(name)
    existed = mcp_oauth.forget(name)
    state["store"].log("system", f"mcp: signed out of '{name}'")
    await state["mcp"].reload()
    await state["broadcast"]({"type": "config"})
    return {"ok": True, "had_tokens": existed}


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


def _app_by_name(store, name: str) -> dict | None:
    """The app with this exact name. `list_apps()` sorts by NAME, so reaching for
    `[0]` to mean "the one just built" returns whichever app is alphabetically
    first — right on an empty machine and wrong forever after."""
    low = (name or "").strip().lower()
    for a in store.list_apps():
        if (a.get("name") or "").strip().lower() == low:
            return a
    return None


def _finish_build_checks(aid: str) -> tuple[str, list[str]]:
    """Everything a freshly built app owes the user before it is called done:
    a permission manifest to consent to, and an honest list of what it still
    ships with.

    Both build paths call this. They did not always: an app built by the
    executor skipped straight to "done", so it never asked for the permissions
    it needed and never admitted a truncated body — the same app built by the
    one-shot builder did both. Which engine built it is not something the user
    should have to know to get a consent screen.
    """
    full = state["store"].get_app(aid) or {}
    status = full.get("manifest_status") or "none"
    if status == "none":
        _propose_manifest(aid)
        status = "proposed"
    return status, _validate_app_html(full.get("html", ""))


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


def _known_tool_names(toolbox=None) -> set[str]:
    """Tool names an app may legitimately call, for the appTool check. Empty when the
    toolbox is unavailable, which disables that one rule rather than inventing it."""
    if toolbox is None:
        return set()
    try:
        return {t["name"] for t in toolbox.schemas()}
    except Exception:
        return set()


def _lint_app_html(html: str, toolbox=None) -> list[str]:
    """Static checks on a built app.

    A thin wrapper now: the rules live in `agentos/appcheck.py`, because `executors.py`
    needs them too and server.py already imports executors — a second copy over there
    would drift, and the half that drifted would be whichever one nobody was demoing.

    Keeps returning plain strings so the existing call sites and tests are unchanged.
    """
    return appcheck.check(html, _known_tool_names(toolbox)).lines()[:6]


# ---- Approval broker (global): any surface can ask the user and await Allow/Deny ----

async def request_approval(name: str, args: dict, reason: str, offer: dict | None = None,
                           evsend=None, ws=None, timeout: float = 300,
                           run_id: str = "", flow: str = "") -> bool:
    """Raise an approval card and wait for the user's answer. `offer` is a ready-to-write
    grant: when the user picks "allow & remember", it is persisted before resolving True.
    evsend routes the card to one chat's client; otherwise it broadcasts to every client.

    The entry carries what was asked and by whom, so `/api/fabric/approvals` can list it —
    a paused flow has to be answerable from the TUI and the CLI, not only from the window
    that happened to be open when it asked."""
    aid = uuid.uuid4().hex[:8]
    fut = asyncio.get_event_loop().create_future()
    state["pending_approvals"][aid] = {"fut": fut, "offer": offer, "ws": ws, "name": name,
                                       "args": args, "reason": reason, "run_id": run_id,
                                       "flow": flow, "asked_at": time.time()}
    ev = {"type": "approval_request", "id": aid, "name": name, "args": args,
          "reason": reason, "offer": offer, "run_id": run_id, "flow": flow}
    if evsend is not None:
        await evsend(ev)
    else:
        await state["broadcast"](ev)
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        return False
    finally:
        state["pending_approvals"].pop(aid, None)


async def request_price(model: str, evsend=None) -> bool:
    """A new cloud model has no price. Ask before it runs.

    Returns True when the turn may proceed (a price was set, or the user chose to
    run it unpriced). The card is prefilled with a published rate when one can be
    found, because typing a number you had to go and look up is the part people
    skip — but it is still shown for confirmation rather than written silently.

    Unattended surfaces cannot answer, so this must never wedge a scheduled job:
    on timeout the turn proceeds and the model is recorded as unpriced, with the
    reason in the log. Refusing to run would be a worse failure than not knowing
    what it cost.
    """
    if state.get("price_pending", {}).get(model):
        return True                       # already being asked about; don't stack cards
    pid = uuid.uuid4().hex[:8]
    fut = asyncio.get_event_loop().create_future()
    state.setdefault("pending_prices", {})[pid] = {"fut": fut, "model": model}
    state.setdefault("price_pending", {})[model] = True
    found = await usagemod.discover_price(state["cfg"], model)
    ev = {"type": "price_request", "id": pid, "model": model, "suggested": found}
    try:
        await (evsend(ev) if evsend is not None else state["broadcast"](ev))
        return await asyncio.wait_for(fut, timeout=300)
    except asyncio.TimeoutError:
        state["store"].log("system",
                           f"no price set for {model} — nobody answered the prompt, so the "
                           f"turn ran and its tokens are recorded as unpriced",
                           {"model": model, "kind": "pricing"})
        return True
    finally:
        state.get("pending_prices", {}).pop(pid, None)
        state.get("price_pending", {}).pop(model, None)


async def resolve_price(pid: str, action: str, price_in: float = 0, price_out: float = 0):
    """Answer a price card: `set` | `skip` | `cancel`."""
    entry = state.get("pending_prices", {}).get(pid)
    if not entry or entry["fut"].done():
        return
    model = entry["model"]
    if action == "set":
        usagemod.set_price(state["cfg"], model, price_in, price_out)
        cfgmod.save_config(state["cfg"])
        state["store"].log("system", f"price set for {model}: ${price_in}/M in, ${price_out}/M out",
                           {"model": model, "kind": "pricing"})
    elif action == "skip":
        usagemod.skip_price(state["cfg"], model)
        cfgmod.save_config(state["cfg"])
        state["store"].log("system", f"{model} will run without a price (your choice)",
                           {"model": model, "kind": "pricing"})
    await state["broadcast"]({"type": "pricing"})
    entry["fut"].set_result(action != "cancel")


def _quarantine(principal: Principal, stats: dict):
    """The PDP decided something is looping. Holding it is this layer's job.

    Deliberately not silent. Something that just stops working is a bug report; something
    that says it was quarantined, why, with the numbers, and offers three ways out is a
    decision the user can agree or disagree with — and the ledger already holds every call
    that led here."""
    store = state["store"]
    label = principal.id
    if principal.kind == "app":
        label = (store.get_app(principal.id) or {}).get("name") or principal.id
    # The PDP has already written the hold — that is what makes it real. This adds the human
    # name to it and does everything the gate has no business doing.
    held = store.quarantined(principal.kind, principal.id)
    if not held:
        return
    qid = held["id"]
    if label and label != principal.id and not held.get("label"):
        store.db.execute("UPDATE quarantine SET label=? WHERE id=?", (label[:120], qid))
        store.db.commit()
    if principal.kind == "app":
        # Its token is deliberately LEFT ALONE. Revoking it does not silence the app — it
        # makes the next call arrive unidentified, and an unidentified call used to be read
        # as the user's own. The app keeps its name so the refusal lands on the right
        # principal; `suspended_at` is what stops it.
        store.suspend_app(principal.id, stats["reason"])
    if held.get("announced"):
        return
    store.log("policy", f"quarantined {principal.kind} '{label}': {stats['reason']}",
              {"principal": principal.label, "rule": "quarantined", "quarantine": qid, **stats})
    store.log("error", f"{principal.kind} '{label}' was quarantined: {stats['reason']}",
              {"principal": principal.label, "quarantine": qid})
    with contextlib.suppress(Exception):
        asyncio.create_task(_announce_quarantine(principal, label, stats["reason"], qid))


async def _announce_quarantine(principal: Principal, label: str, reason: str, qid: str):
    await state["broadcast"]({"type": "quarantined", "id": qid, "kind": principal.kind,
                              "principal_id": principal.id, "label": label, "reason": reason})
    await state["broadcast"]({"type": "apps"})
    await state["broadcast"]({"type": "fabric_defs"})
    with contextlib.suppress(Exception):
        await state["toolbox"].notify(f"Quarantined “{label}”", reason[:180])


@app.get("/api/quarantine")
async def api_quarantine(history: bool = False):
    return {"held": state["store"].quarantine_list(include_released=False),
            "history": state["store"].quarantine_list(include_released=True, limit=40)
            if history else []}


@app.post("/api/quarantine/{qid}/release")
async def api_quarantine_release(qid: str, body: dict):
    """Let something out, and record which of the three things the user chose.

    `once`    — runs again, still watched; it can be held again tomorrow.
    `forever` — never held for this again. An exemption somebody made deliberately, so it
                stays on the record rather than disappearing when the row is cleared.
    `deleted` — it is gone.
    """
    mode = ((body or {}).get("mode") or "once").strip()
    if mode not in ("once", "forever", "deleted"):
        return JSONResponse({"error": "mode is once, forever or deleted"}, status_code=400)
    row = state["store"].quarantine_release(qid, mode)
    if not row:
        return JSONResponse({"error": "no such quarantine record"}, status_code=404)
    kind, pid = row["principal_kind"], row["principal_id"]
    store = state["store"]
    if mode == "deleted":
        if kind == "app":
            store.delete_app(pid)
        elif kind == "subagent" and store.get_subagent(pid):
            store.delete_subagent(store.get_subagent(pid)["id"])
        elif kind == "flow":
            flowsmod.delete(store, pid)
    elif kind == "app":
        store.resume_app(pid)
    with contextlib.suppress(Exception):
        state["pdp"].forget_rate(kind, pid)
    store.log("policy",
              f"{kind} '{row.get('label') or pid}' released from quarantine by the user: "
              + {"once": "allowed to run again, still watched",
                 "forever": "allowed forever — it will not be held for this again",
                 "deleted": "deleted"}[mode],
              {"principal": f"{kind}:{pid}", "quarantine": qid, "release_mode": mode})
    await state["broadcast"]({"type": "quarantine"})
    await state["broadcast"]({"type": "apps"})
    await state["broadcast"]({"type": "fabric_defs"})
    return {"ok": True, "mode": mode}


async def _flow_approval(run_id: str, name: str, args: dict, reason: str,
                         offer: dict | None, origin: dict) -> bool:
    """A paused flow, asking. It goes back where the run came from when that is a place
    a person can answer — a run started from a phone should not raise a card on a screen
    in another room — and otherwise to every open window, which in the session desktop
    means the desktop itself."""
    timeout = int((state["cfg"].get("fabric") or {}).get("approval_timeout", 900))
    run = state["store"].fabric_run(run_id) or {}
    chat_id = origin.get("chat_id") or (run.get("origin_ref") if
                                        run.get("origin_surface") == "telegram" else "")
    if origin.get("surface") == "telegram" and state.get("telegram") and chat_id:
        return await state["telegram"].ask_approval(int(chat_id), name, args, reason,
                                                    offer=offer, timeout=timeout)
    return await request_approval(name, args, reason, offer=offer, timeout=timeout,
                                  run_id=run_id, flow=run.get("flow") or "")


async def _flow_deliver(flow: dict, run: dict, origin: dict, text: str) -> list:
    """Where a finished flow's answer goes. The default sink is `origin`: triggered from
    Telegram, it answers in that chat. A flow that declares nothing gets that behaviour,
    because being told the result where you asked for it is not a feature to opt into."""
    sinks = flow.get("sinks") or [{"kind": "origin"}]
    surface = origin.get("surface") or run.get("origin_surface") or ""
    done = []
    for sink in sinks:
        kind = sink.get("kind")
        if kind == "origin":
            kind = {"telegram": "telegram", "whatsapp": "whatsapp",
                    "webhook": "notify", "task": "notify",
                    "tui": "notify"}.get(surface, "gui")
            sink = {**sink, "chat_id": origin.get("chat_id") or run.get("origin_ref") or 0}
        try:
            head = f"▲ {flow['name']} · {run.get('status', '')}"
            if kind == "telegram" and state.get("telegram"):
                await state["telegram"].send(f"{head}\n\n{text}",
                                             int(sink.get("chat_id") or 0) or None)
            elif kind == "whatsapp" and state.get("whatsapp"):
                # This can legitimately refuse: outside Meta's 24-hour window there is
                # no free-form message to send. The refusal is a sentence, and it is
                # logged as the outcome rather than swallowed as a success.
                res = await state["whatsapp"].send(f"{head}\n\n{text}",
                                                   str(sink.get("chat_id") or "") or None)
                if str(res).startswith("[error]"):
                    state["store"].log("error", f"flow '{flow['name']}': {res}",
                                       {"flow": flow["name"], "sink": "whatsapp"})
            elif kind == "notify":
                await state["toolbox"].notify(head, text[:200])
            elif kind == "report":
                await state["toolbox"].save_report(
                    f"{flow['name']} — {time.strftime('%d %b %H:%M')}", text,
                    to_telegram=bool(sink.get("to_telegram")))
            elif kind == "conversation":
                cid = sink.get("id") or run.get("conversation_id") or ""
                if cid:
                    state["store"].add_message(cid, "assistant", text)
            else:      # 'gui': the desktop is the sink, and every window hears it
                await state["broadcast"]({"type": "flow_done", "flow": flow["name"],
                                          "run_id": run.get("id", ""),
                                          "status": run.get("status", ""),
                                          "preview": text[:400]})
                kind = "gui"
            done.append(kind)
        except Exception as e:
            state["store"].log("error", f"flow '{flow['name']}': delivery to {kind} failed: {e}",
                               {"flow": flow["name"], "sink": kind})
    return done


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
    # widening what the agent's own tools may reach is the last thing an app
    # should be able to do on its own behalf
    ("PUT", "/api/folders"),
    ("POST", "/api/apps"), ("DELETE", "/api/apps"), ("PUT", "/api/apps"),
    ("POST", "/api/grants"), ("DELETE", "/api/grants"),
    ("POST", "/api/snapshots"), ("DELETE", "/api/snapshots"),
    ("PUT", "/api/telegram"), ("PUT", "/api/widgets"), ("POST", "/api/skills"),
    ("DELETE", "/api/skills"), ("POST", "/api/setup/reset"), ("POST", "/api/factory-reset"),
    ("POST", "/api/power"), ("POST", "/api/store/mcp"), ("DELETE", "/api/mcp/registry"),
    # signing this machine's owner in or out of a third-party account is a user act;
    # the GET callback stays reachable because it is a browser redirect, not an API
    ("POST", "/api/mcp/oauth"), ("DELETE", "/api/mcp/oauth"),
    # linking or unlinking a personal WhatsApp account is a user act; an app that
    # could unlink it could also silently re-pair the channel to somewhere else
    ("POST", "/api/whatsapp/link"), ("DELETE", "/api/whatsapp/link"),
    # DE-mode system controls: joining networks, pairing devices and rewiring
    # audio are user acts, never app acts
    ("POST", "/api/net/wifi"), ("POST", "/api/bt"), ("POST", "/api/brightness"),
    ("POST", "/api/audio/devices"), ("POST", "/api/power/profile"),
    ("POST", "/api/wm/outputs"), ("POST", "/api/components"),
    # shell_cmd results come from the shell itself, never from an app iframe
    ("POST", "/api/shell/result"),
    # an eval run spends real model tokens for as long as it takes; that is a
    # user's decision to make, not something an app kicks off in the background
    ("POST", "/api/evals/run"),
)


# ---------------------------------------------------------------------------
# App origin isolation (docs/design/tenant-isolation.md, Piece 1).
#
# Apps run in opaque-origin iframes (sandbox without allow-same-origin), so they
# cannot read the desktop's DOM/cookies and — the point of this guard — their
# fetches carry `Origin: null`, a header the browser sets and no script may forge.
# The desktop's own fetches carry the real same-origin value. That single
# browser-enforced difference is what tells an app's request apart from a user's,
# with no token plumbed onto the hundreds of desktop fetch sites (miss one and the
# hole is back). A same-origin mutating request is the user; a cross-origin one is
# refused unless it is an app reaching its own runtime with a valid app token.
# ---------------------------------------------------------------------------

_MUTATING = {"POST", "PUT", "DELETE", "PATCH"}


def _is_app_runtime(path: str) -> bool:
    """The only endpoints an app may reach, and the only ones that answer a
    cross-origin (opaque-app) request. Everything else is the user's."""
    return path == "/api/tool" \
        or path in ("/api/apps/llm/stream", "/api/apps/llm/chat",
                    "/api/apps/agent", "/api/apps/context") \
        or (path.startswith("/api/apps/") and path.endswith(("/data", "/page")))


def _request_origin(request: Request) -> str | None:
    o = request.headers.get("origin")
    if o:
        return o
    ref = request.headers.get("referer")            # some browsers omit Origin on same-origin
    if ref:
        u = urlsplit(ref)
        return f"{u.scheme}://{u.netloc}" if u.netloc else None
    return None


def _same_origin(request: Request):
    """True same-origin · False cross-origin (incl. opaque 'null') · None no origin
    header at all, which is a non-browser client (curl, the TUI) with no ambient
    cookie to abuse, so it is not a CSRF vector and is left to the auth gate."""
    o = _request_origin(request)
    if not o:
        return None
    if o == "null":
        return False
    return urlsplit(o).netloc == request.headers.get("host", "")


def _valid_app_token(request: Request) -> bool:
    tok = request.headers.get("x-app-token", "")
    return bool(tok) and tok in state.get("app_tokens", {})


def _cors_headers(request: Request) -> dict:
    """Let the opaque app read its own runtime responses. The authority is the app
    token, not the origin, so reflecting `null` is safe: a foreign site's sandboxed
    iframe also sends `null` but holds no valid token and is refused before here."""
    return {"Access-Control-Allow-Origin": request.headers.get("origin", "null"),
            "Access-Control-Allow-Headers": "X-App-Token, Content-Type",
            "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
            "Vary": "Origin"}


@app.middleware("http")
async def csrf_origin_guard(request: Request, call_next):
    path, method = request.url.path, request.method
    if not path.startswith("/api/"):
        return await call_next(request)
    app_runtime = _is_app_runtime(path)
    if method == "OPTIONS" and app_runtime:          # the opaque app's CORS preflight
        return Response(status_code=204, headers=_cors_headers(request))
    if method in _MUTATING and not path.startswith(REMOTE_OPEN_PATHS):
        so = _same_origin(request)
        if app_runtime:
            # its own runtime: a valid app token, or the desktop itself (same-origin,
            # e.g. an automation step running a tool as the user). A cross-origin
            # request with no token is a foreign site or a tokenless app — refused.
            if not (_valid_app_token(request) or so is True or so is None):
                return JSONResponse({"error": "denied: this needs a valid app token "
                                     "(cross-origin request)"}, status_code=403)
        elif so is False:
            # A cross-origin mutation of a non-runtime route is either an app trying
            # to escape its sandbox or a cross-site forgery. Neither is the user.
            return JSONResponse({"error": "denied: cross-origin request refused (apps "
                                 "reach the OS only through appTool and its grants)"},
                                status_code=403)
    resp = await call_next(request)
    if app_runtime and _same_origin(request) is False:
        for k, v in _cors_headers(request).items():
            resp.headers.setdefault(k, v)
    return resp


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

REMOTE_OPEN_PATHS = ("/login", "/api/remote/login", "/api/users/login",
                     "/api/users/who", "/assets/", "/manifest.webmanifest",
                     "/favicon.ico", "/apple-touch-icon.png",
                     # Flow webhooks. A service posting from the internet has no session
                     # and cannot get one, so this is the one path deliberately reachable
                     # without the remote-access gate. Its only defence is the per-trigger
                     # secret compared in constant time, plus a cooldown enforced before
                     # any work starts — both live in api_flow_hook, and the run it starts
                     # is tainted so the payload cannot spend a permission unseen.
                     "/api/hooks/")


def _client_addr(request: Request) -> str:
    return (request.client.host if request.client else "") or ""


def _authed(request: Request) -> bool:
    cfg = state.machine_cfg()
    # Adding a second person is what turns this machine into one that needs a login.
    # Loopback trust cannot survive it: "whoever is sitting here" is exactly the
    # thing that must stop being an identity once there is more than one identity,
    # and without this everybody at the keyboard would share the machine store
    # rather than reaching their own.
    if usersmod.enabled():
        uid = remotemod.session_user(cfg, request.cookies.get(remotemod.COOKIE, ""))
        return bool(uid) and usersmod.get(uid) is not None
    if not remotemod.enabled(cfg):
        return True                                     # loopback-only: nothing to gate
    if cfg["remote"].get("trust_loopback", True) and remotemod.is_loopback(_client_addr(request)):
        return True
    return remotemod.valid_session(cfg, request.cookies.get(remotemod.COOKIE, ""))


@app.middleware("http")
async def resolve_user(request: Request, call_next):
    """Who is this request, before anything reads data.

    Set from the SIGNED session cookie only — never a header or a query parameter,
    because those are things a caller chooses and this decides which private
    directory gets opened.
    """
    uid = ""
    if usersmod.enabled():
        uid = remotemod.session_user(state.machine_cfg(),
                                     request.cookies.get(remotemod.COOKIE, "")) or ""
        if uid and not usersmod.get(uid):
            uid = ""                     # the account was deleted mid-session
    token = usersmod._current.set(uid)
    try:
        return await call_next(request)
    finally:
        usersmod._current.reset(token)


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


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Headers that are cheap, safe, and were simply not being sent.

    Three of them apply to everything and cannot break anything, because the
    server already serves correct content types and never wants to leak a URL:

      · `X-Content-Type-Options: nosniff` — a stylesheet or upload is never
        re-guessed into a script.
      · `Referrer-Policy: no-referrer` — the agent's own browser and the apps
        visit the open web; a session-bearing path must not ride along in a
        Referer header to a site the user did not choose to tell.
      · `Cross-Origin-Opener-Policy: same-origin` — a window this page opened
        cannot reach back into it.

    The fourth is clickjacking, and it is scoped. The DESKTOP is the one page
    with an Allow / Deny that grants real capability on one click, and nothing
    should ever frame it — so `frame-ancestors 'none'`. An APP page is meant to
    be framed, but only by the desktop that served it — so `frame-ancestors
    'self'`, which keeps a foreign site from embedding somebody's app and
    reading their clicks. A full script-src CSP is deliberately NOT set here: the
    hand-written desktop uses inline handlers throughout, and a policy that
    breaks the whole OS to add a header nobody measured is the wrong trade.
    """
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    # HSTS only over TLS, and never on loopback: telling a browser "only ever
    # reach this host over HTTPS" is right for a tunnelled public hostname and
    # catastrophic for `localhost`, which is plain http and would become
    # unreachable for six months. So it rides the same signal the Secure cookie
    # does — the connection actually being HTTPS.
    if _is_https(request):
        resp.headers.setdefault("Strict-Transport-Security",
                                "max-age=31536000; includeSubDomains")
    path = request.url.path
    is_app_page = path.startswith("/api/apps/") and path.rstrip("/").endswith("/page")
    if is_app_page:
        # framed by the desktop (same origin), by nobody else
        resp.headers.setdefault("Content-Security-Policy", "frame-ancestors 'self'")
    elif not path.startswith("/api/") and not path.startswith("/ws"):
        # a document: the desktop, the login page, the manifest. Never framed.
        resp.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
        resp.headers.setdefault("X-Frame-Options", "DENY")
    return resp


# ---- Run a single tool (for AI-built apps to reach the OS / MCP) -----------------

def _is_https(request) -> bool:
    """Is the browser talking to us over TLS? True over a tunnel, false on plain
    loopback. A proxy terminates TLS and re-forwards http, so the scheme it
    forwarded (`X-Forwarded-Proto`) is the honest answer, not our own socket."""
    if (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip() == "https":
        return True
    return request.url.scheme == "https"


def _set_session_cookie(resp, request, token: str, days: int = 30) -> None:
    """Write the session cookie the one right way, from every sign-in path.

    `Secure` is added over HTTPS so a session that was established over a tunnel
    can never be sent back in the clear — but it must NOT be set on plain
    loopback, where the browser would then drop the cookie and the person could
    not stay signed in on their own machine. `HttpOnly` keeps script (including a
    compromised app, though the sandbox already blocks it) from reading it;
    `SameSite=Lax` keeps a foreign page from riding it on a cross-site request.
    """
    resp.set_cookie(remotemod.COOKIE, token, max_age=days * 86400,
                    httponly=True, samesite="lax", secure=_is_https(request), path="/")


def _principal_of(request) -> Principal:
    """Map a request to its principal: an app runtime token (X-App-Token, minted when the
    app page is served) makes it that app; a request with no token at all is the user."""
    tok = request.headers.get("x-app-token", "") if request is not None else ""
    entry = state["app_tokens"].get(tok) if tok else None
    return Principal("app", entry["app_id"]) if entry else MAIN


def _stale_app_token(request) -> bool:
    """A request that PRESENTS a token we do not know is a page from a previous server run,
    a deleted app, or one whose identity was revoked. It is emphatically not the user.

    Falling through to MAIN here is a privilege escalation: it takes something that was
    running with an app's narrow permissions and hands it the user's. It surfaced when a
    quarantined app's next call came back as the user's own — but a server restart alone is
    enough to reach it, which is why the fix is here and not in the quarantine path.
    """
    if request is None:
        return False
    tok = request.headers.get("x-app-token", "")
    return bool(tok) and tok not in state["app_tokens"]


@app.post("/api/apps/{aid}/resume")
async def api_resume_app(aid: str):
    """Start a stopped app again. Its rate history is forgotten too — otherwise the very
    next call would be measured against the burst that got it stopped and it would trip
    again immediately, which reads as "Resume does not work"."""
    if not state["store"].get_app(aid):
        return JSONResponse({"error": "no such app"}, status_code=404)
    state["store"].resume_app(aid)
    with contextlib.suppress(Exception):
        state["pdp"].forget_rate("app", aid)
    state["store"].log("policy", f"app {aid} started again by the user", {"app": aid})
    await state["broadcast"]({"type": "apps"})
    return {"ok": True}


@app.post("/api/tool")
async def api_run_tool(body: dict, request: Request):
    """Let a user-built app invoke an agent or MCP tool and get its output. Every call
    flows through the policy gate; an ungranted call raises an approval card with
    "allow & remember" instead of failing flat."""
    name = body.get("name", "")
    args = body.get("args") or {}
    toolbox = state["toolbox"]
    if _stale_app_token(request):
        return JSONResponse({"error": "this app's session has ended — reload it. (If it was "
                                      "quarantined, let it out in Permissions → Quarantine.)",
                             "stale": True}, status_code=401)
    principal = _principal_of(request)
    # A quarantined app is refused here, before the gate, so a page still looping in a
    # background tab cannot keep the meter warm or fill the ledger with the same denial.
    if principal.kind == "app":
        app_row = state["store"].get_app(principal.id) or {}
        if app_row.get("suspended_at"):
            why = app_row.get("suspended_reason") or "it was calling too fast"
            return JSONResponse({"error": f"this app is quarantined: {why}. Let it out in "
                                          f"Permissions → Quarantine.",
                                 "quarantined": True}, status_code=409)
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
    # An app parses this in JS, so the model's context budget does not apply —
    # clipping at MAX_OUTPUT would hand it a half-written JSON body.
    tok = tools.output_limit.set(tools.APP_MAX_OUTPUT)
    try:
        out = await toolbox.execute(name, args)
    finally:
        tools.output_limit.reset(tok)
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
                        "flow.read", "flow.write",
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
    """Sign in from elsewhere.

    On a machine with accounts this IS the account login — same username, same
    password, same session — rather than a second credential in front of it. Kept
    as its own path because a phone that added AgentOS to its home screen months
    ago has this URL cached, and an old client meeting a 404 would read as "remote
    access broke" rather than "the door moved".
    """
    cfg = state.machine_cfg()
    addr = _client_addr(request)
    if usersmod.enabled():
        return await api_users_login(body, request)
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
    _set_session_cookie(resp, request, remotemod.issue_session(cfg),
                        days=int(cfg["remote"].get("session_days") or 30))
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
        # A machine with accounts is already locked — asking it for a second,
        # shared passphrase in front of per-person credentials would make "sign
        # in" mean two different things depending on where you were standing.
        if want and not r.get("pass_hash") and not remotemod.accounts_lock():
            return JSONResponse({"error": "set a passphrase before enabling remote access "
                                          "— or add user accounts, which lock it themselves"},
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


# ---------------------------------------------------------------------------
# Spaces — the things the user is working on
# ---------------------------------------------------------------------------

def _space_of(request: Request, body: dict | None = None, query: str = "") -> str:
    """Which space this request is about.

    Explicit beats implicit, in this order: an ?space= parameter, a body field,
    the X-AgentOS-Space header, then nothing. A script has no "current" space, so
    the surface default is deliberately NOT consulted here — that belongs to the
    chat path, which knows its surface (see spaces.active_for)."""
    if query:
        return query
    if body and body.get("space_id"):
        return str(body["space_id"])
    return request.headers.get("X-AgentOS-Space", "") or ""


@app.get("/api/spaces")
async def api_spaces():
    from . import spaces as spacemod
    return spacemod.public(state["store"], state["cfg"])


@app.post("/api/spaces")
async def api_create_space(body: dict):
    store = state["store"]
    sid = store.create_space(
        (body.get("name") or "").strip()[:80],
        description=(body.get("description") or "")[:500],
        icon=(body.get("icon") or "")[:8],
        colour=(body.get("colour") or "")[:24],
        workspace=(body.get("workspace") or "")[:400])
    if not sid:
        return JSONResponse({"error": "a space needs a name"}, status_code=400)
    store.log("system", f"space created: {body.get('name')}", {"space_id": sid}, space_id=sid)
    await state["broadcast"]({"type": "spaces_update"})
    return {"ok": True, "id": sid, "space": store.get_space(sid)}


@app.put("/api/spaces/{sid}")
async def api_update_space(sid: str, body: dict):
    store = state["store"]
    if not store.get_space(sid):
        return JSONResponse({"error": "no such space"}, status_code=404)
    store.update_space(sid, **{k: v for k, v in body.items()
                               if k in ("name", "icon", "colour", "description",
                                        "workspace", "archived")})
    await state["broadcast"]({"type": "spaces_update"})
    return {"ok": True, "space": store.get_space(sid)}


@app.get("/api/spaces/{sid}/stats")
async def api_space_stats(sid: str):
    """What is in a space. The delete dialog shows this first — 'delete everything'
    should never be a guess about what everything is."""
    store = state["store"]
    if not store.get_space(sid):
        return JSONResponse({"error": "no such space"}, status_code=404)
    return {"stats": store.space_stats(sid)}


@app.delete("/api/spaces/{sid}")
async def api_delete_space(sid: str, contents: str = "archive"):
    store = state["store"]
    if not store.get_space(sid):
        return JSONResponse({"error": "no such space"}, status_code=404)
    if contents not in store.SPACE_CONTENTS:
        return JSONResponse(
            {"error": f"contents must be one of {', '.join(store.SPACE_CONTENTS)} — "
                      f"deleting a space has to say what happens to what is in it"},
            status_code=400)
    counts = store.delete_space(sid, contents=contents)
    # any surface still pointing at it falls back to global rather than filtering
    # on an id that no longer exists (which would hide everything)
    active = (state["cfg"].get("spaces") or {}).get("active") or {}
    for surface, val in list(active.items()):
        if val == sid:
            active[surface] = ""
    cfgmod.save_config(state["cfg"])
    store.log("system", f"space {sid} deleted ({contents})", {"counts": counts})
    await state["broadcast"]({"type": "spaces_update"})
    return {"ok": True, "disposition": contents, "counts": counts}


@app.post("/api/spaces/activate")
async def api_activate_space(body: dict):
    """Point one surface at a space. Per-surface on purpose: switching project at
    the desk must not silently move what your phone does next."""
    from . import spaces as spacemod
    sid = str(body.get("space_id") or "")
    if sid and not state["store"].get_space(sid):
        return JSONResponse({"error": "no such space"}, status_code=404)
    surface = str(body.get("surface") or "gui")
    spacemod.set_active(state["cfg"], surface, sid)
    cfgmod.save_config(state["cfg"])
    await state["broadcast"]({"type": "spaces_update", "surface": surface, "space_id": sid})
    return {"ok": True, "surface": surface, "space_id": sid,
            "name": spacemod.label(state["store"], sid)}


@app.get("/api/timeline")
async def api_timeline(space: str = "", kind: str = "", since: float = 0.0,
                       limit: int = 200):
    return {"events": state["store"].timeline(space=space, kind=kind, since=since,
                                              limit=min(int(limit), 1000))}


# ---------------------------------------------------------------------------
# Assets — everything the agent made or was handed
# ---------------------------------------------------------------------------

@app.get("/api/assets")
async def api_assets(kind: str = "", q: str = "", space: str = "",
                     conversation_id: str = "", run_id: str = "",
                     limit: int = 100, offset: int = 0):
    from . import assets as assetmod
    rows = state["store"].asset_list(kind=kind, q=q, space=space,
                                     conversation_id=conversation_id, run_id=run_id,
                                     limit=min(int(limit), 500), offset=int(offset))
    return {"assets": [assetmod.public(r) for r in rows],
            "capability": assetmod.capability()}


@app.get("/api/assets/{aid}")
async def api_asset(aid: str):
    from . import assets as assetmod
    row = state["store"].asset_get(aid)
    if not row:
        return JSONResponse({"error": "no such asset"}, status_code=404)
    out = assetmod.public(row)
    out["missing"] = assetmod.path_of(row) is None
    return out


@app.get("/api/assets/{aid}/file")
async def api_asset_file(aid: str):
    """Serve the bytes. The path comes from the row, never from the caller — an
    asset is addressed by id, so there is no path here to traverse."""
    from . import assets as assetmod
    row = state["store"].asset_get(aid)
    if not row:
        return JSONResponse({"error": "no such asset"}, status_code=404)
    path = assetmod.path_of(row)
    if not path:
        return JSONResponse(
            {"error": "the file behind this asset is missing from disk"}, status_code=410)
    return FileResponse(path, media_type=row.get("mime") or "application/octet-stream",
                        headers={"Cache-Control": "max-age=31536000, immutable"})


@app.get("/api/assets/{aid}/thumb")
async def api_asset_thumb(aid: str):
    from . import assets as assetmod
    row = state["store"].asset_get(aid)
    if not row or not row.get("thumb"):
        return JSONResponse({"error": "no thumbnail"}, status_code=404)
    p = Path(row["thumb"])
    if not p.is_file():
        return JSONResponse({"error": "no thumbnail"}, status_code=404)
    return FileResponse(p, media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=31536000, immutable"})


@app.post("/api/assets")
async def api_asset_create(request: Request, body: dict):
    """Small inline uploads: a pasted or dropped image as a data URL. Large files
    go to the raw PUT below — base64 in JSON inflates by a third and buffers the
    whole thing in memory twice."""
    from . import assets as assetmod
    data_url = body.get("data_url") or ""
    if not data_url.startswith("data:"):
        return JSONResponse({"error": "data_url is required"}, status_code=400)
    row = await assetmod.put_data_url(
        state["store"], data_url, title=(body.get("title") or "")[:200],
        name=(body.get("name") or ""), source="upload",
        space_id=_space_of(request, body), conversation_id=body.get("conversation_id") or "")
    if not row:
        return JSONResponse(
            {"error": f"could not store it — empty, malformed, or over the "
                      f"{assetmod.MAX_INLINE_BYTES // (1024*1024)} MB inline limit"},
            status_code=400)
    await state["broadcast"]({"type": "assets_update"})
    return {"ok": True, "asset": assetmod.public(row)}


@app.put("/api/assets/raw")
async def api_asset_raw(request: Request, name: str = "", title: str = "",
                        conversation_id: str = ""):
    """Stream a large upload straight to disk.

    A raw body rather than multipart: multipart would mean adding
    python-multipart, and streaming a 200 MB video through base64 in JSON would
    mean holding ~500 MB of string. The client side is one line —
    fetch(url, {method:'PUT', body: file}).
    """
    from . import assets as assetmod
    try:
        row = await assetmod.put_stream(
            state["store"], request.stream(), name=name[:200],
            mime=request.headers.get("content-type", "").split(";")[0],
            title=title[:200], source="upload",
            space_id=_space_of(request), conversation_id=conversation_id)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=413)
    except Exception as e:
        return JSONResponse({"error": f"upload failed: {type(e).__name__}: {e}"},
                            status_code=400)
    if not row:
        return JSONResponse({"error": "nothing was uploaded"}, status_code=400)
    await state["broadcast"]({"type": "assets_update"})
    return {"ok": True, "asset": assetmod.public(row)}


@app.delete("/api/assets/{aid}")
async def api_asset_delete(aid: str):
    from . import assets as assetmod
    if not assetmod.delete(state["store"], aid):
        return JSONResponse({"error": "no such asset"}, status_code=404)
    await state["broadcast"]({"type": "assets_update"})
    return {"ok": True}


@app.get("/api/media/capability")
async def api_media_capability():
    """What this machine can do with media, and the component that would fix what
    it cannot. The Gallery renders the sentence rather than greying a control out
    with no explanation."""
    from . import assets as assetmod
    from . import components as compmod
    cap = assetmod.capability()
    if not cap["ffmpeg"]:
        entry = compmod.CATALOG.get("ffmpeg") or {}
        cap["title"] = entry.get("title", "")
        cap["licence"] = entry.get("licence", "")
        cap["unlocks"] = entry.get("unlocks", "")
    return cap


# ---------------------------------------------------------------------------
# The access ledger
# ---------------------------------------------------------------------------

@app.get("/api/audit")
async def api_audit(limit: int = 300, effect: str = "", action: str = "",
                    principal_kind: str = "", surface: str = "", space: str = "",
                    since: float = 0.0, q: str = ""):
    return {"entries": state["store"].audit_list(
        limit=min(int(limit), 2000), effect=effect, action=action,
        principal_kind=principal_kind, surface=surface, space=space,
        since=since, q=q)}


@app.get("/api/audit/summary")
async def api_audit_summary(since: float = 0.0):
    return state["store"].audit_summary(since=since)


@app.get("/api/audit/verify")
async def api_audit_verify():
    """Walk the ledger's hash chain and report whether it is intact, or the first
    seq where a row was altered, deleted or reordered. Admin-only: on a multi-user
    machine, whether somebody's ledger has been tampered with is a machine-level
    question, and the answer names how far the record can be trusted."""
    if usersmod.enabled() and not usersmod.is_admin(usersmod.current()):
        return JSONResponse({"error": "only an admin can verify the ledger"}, status_code=403)
    return state["store"].audit_verify()


@app.get("/api/memories")
async def api_memories(scope: str = "", conversation_id: str = "", q: str = "",
                       space: str = ""):
    store = state["store"]
    mems = store.search_memories(q, limit=500, scope=scope,
                                 conversation_id=conversation_id, space=space)
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
             "tui.md", "security.md", "users.md", "whatsapp.md", "integrations.md",
             "models.md", "configuration.md",
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
    from . import setup as setupmod
    return {
        "first_run": cfgmod.is_first_run(),
        "agent_name": cfg.get("agent_name", "Aria"),
        "autonomy": cfg.get("autonomy", "balanced"),
        "default_model": cfg.get("default_model", ""),
        "ollama_models": local,
        # Driven off setup.CLOUD_PROVIDERS, not a hand-written tuple: this dict is
        # how a surface tells whether a provider already has a key, so a provider the
        # picker offers but this loop omits reads as "no key" forever.
        "providers": {p: bool(cfg["providers"].get(p, {}).get("api_key"))
                      for p, _, _ in setupmod.CLOUD_PROVIDERS},
        "autostart_installed": desktopmod.autostart_installed(),
    }


@app.post("/api/setup")
async def api_setup_apply(body: dict):
    from . import setup as setupmod
    report = setupmod.apply_setup(state["cfg"], body or {})
    state["store"].log("system", "first-run setup completed via wizard", report)
    await state["broadcast"]({"type": "config"})
    return {"ok": True, "report": report}


# ---------------------------------------------------------------------------
# Users: several people on one machine, isolated by directory.
#
# Every route below decides on `usersmod.is_admin(current)` — never on a field in
# the request. A machine with nobody added has no one to refuse, so is_admin('')
# is True and a single-user install behaves exactly as it always did.
# ---------------------------------------------------------------------------

def _me() -> dict:
    """Who this request is, in the shape the UI draws."""
    uid = usersmod.current()
    u = usersmod.get(uid) if uid else None
    return {"id": uid, "name": (u or {}).get("name", ""),
            "display": (u or {}).get("display", ""),
            "role": (u or {}).get("role", "admin" if not usersmod.enabled() else ""),
            "admin": usersmod.is_admin(uid),
            "multiuser": usersmod.enabled()}


def _require_admin():
    if not usersmod.is_admin(usersmod.current()):
        return JSONResponse({"error": "only an admin can do that"}, status_code=403)
    return None


@app.get("/api/users/who")
async def api_users_who():
    """Deliberately outside the auth gate: the sign-in page has to know whether this
    machine has users at all before it can ask for anything."""
    return {**_me(), "any": usersmod.enabled()}


@app.post("/api/users/login")
async def api_users_login(body: dict, request: Request):
    name = str((body or {}).get("name") or "").strip().lower()
    pw = str((body or {}).get("password") or "")
    addr = _client_addr(request)
    wait = remotemod.locked_for(addr)
    if wait:
        return JSONResponse({"error": f"too many attempts — wait {wait}s"},
                            status_code=429)
    u = usersmod.by_name(name)
    # One message for both failures, on purpose: "no such user" tells somebody
    # probing which names exist.
    if not u or not usersmod.check_password(u["id"], pw):
        remotemod.note_failure(addr)
        return JSONResponse({"error": "that username and password do not match"},
                            status_code=401)
    remotemod.note_success(addr)
    tok = remotemod.issue_session(state.machine_cfg(), u["id"])
    resp = JSONResponse({"ok": True, "id": u["id"], "name": u["name"],
                         "role": u["role"]})
    _set_session_cookie(resp, request, tok)
    usersmod.store_for(u["id"]).log("system", f"signed in: {u['name']}")
    return resp


@app.post("/api/users/logout")
async def api_users_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(remotemod.COOKIE, path="/")
    return resp


@app.get("/api/users")
async def api_users():
    """The roster. Readable by everyone — you cannot share an app with somebody
    whose name you are not allowed to see."""
    return {"users": usersmod.list_users(), "me": _me(), "roles": list(usersmod.ROLES)}


@app.post("/api/users")
async def api_users_create(body: dict, request: Request):
    if (r := _require_admin()):
        return r
    b = body or {}
    first = not usersmod.enabled()
    try:
        u = usersmod.create(str(b.get("name") or ""), str(b.get("password") or ""),
                            role=str(b.get("role") or "executor"),
                            display=str(b.get("display") or ""))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    resp = JSONResponse({"ok": True, "user": u, "signed_in": first})
    if first:
        # Creating the first account is what turns this into a machine that needs
        # a login — including for the person who just did it, who has no session
        # and would be bounced to a sign-in page by their own next click. They
        # proved they were the machine's owner by being able to make the account;
        # hand them the session rather than the door.
        with usersmod.as_user(u["id"]):
            usersmod.store_for(u["id"]).log(
                "system", f"multi-user turned on; {u['name']} is the first admin")
        _set_session_cookie(resp, request,
                            remotemod.issue_session(state.machine_cfg(), u["id"]))
    else:
        state["store"].log("system", f"user created: {u['name']} ({u['role']})")
    return resp


@app.put("/api/users/{uid}")
async def api_users_update(uid: str, body: dict):
    b = body or {}
    me = usersmod.current()
    admin = usersmod.is_admin(me)
    # Your own password is yours. Everything else about an account is the machine's.
    if not admin and uid != me:
        return JSONResponse({"error": "only an admin can change another account"},
                            status_code=403)
    try:
        if b.get("password"):
            usersmod.set_password(uid, str(b["password"]))
        if b.get("role"):
            if not admin:
                return JSONResponse({"error": "only an admin can change a role"},
                                    status_code=403)
            usersmod.set_role(uid, str(b["role"]))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, "user": usersmod.get(uid) and
            {k: v for k, v in usersmod.get(uid).items()
             if k not in ("pass_hash", "salt")}}


@app.delete("/api/users/{uid}")
async def api_users_delete(uid: str, wipe: bool = False):
    if (r := _require_admin()):
        return r
    if uid == usersmod.current():
        return JSONResponse({"error": "you cannot delete the account you are using"},
                            status_code=400)
    try:
        return usersmod.delete(uid, wipe=wipe)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ---- sharing: the one place data crosses between people --------------------

@app.get("/api/folders")
async def api_folders():
    """The shared folders, who they are for, and what is worth pausing over.

    Read by the Users app rather than Settings, because a folder shared with
    somebody is the same kind of fact as an agent shared with somebody, and both
    belong next to the isolation they are the exception to.
    """
    from .tools import folder_problems, folder_risk, folder_shares
    cfg = state.machine_cfg()
    shares = [{**s, "risk": folder_risk(s["path"], s["mode"])} for s in folder_shares(cfg)]
    return {"folders": shares,
            "problems": [{"entry": e, "why": w} for e, w in folder_problems(cfg)],
            "users": [{"id": u["id"], "display": u.get("display") or u["id"]}
                      for u in usersmod.list_users()],
            "admin": usersmod.is_admin(usersmod.current()),
            "multiuser": usersmod.enabled()}


@app.put("/api/folders")
async def api_folders_put(body: dict):
    """Replace the share list. Admin only, and refused rather than silently
    dropped — `sandbox` is a machine key, so a non-admin saving here would
    otherwise appear to work and change nothing."""
    from .tools import check_safe_folder, folder_risk
    if usersmod.enabled() and not usersmod.is_admin(usersmod.current()):
        return JSONResponse({"error": "only an admin can share folders on this machine"},
                            status_code=403)
    out, refused = [], []
    for raw in (body or {}).get("folders") or []:
        path = str((raw or {}).get("path") or "").strip()
        if not path:
            continue
        p, why = check_safe_folder(path)
        # Refuse at the point of decision. Storing an entry the loader will drop
        # is how a settings page comes to list a folder nobody can use.
        if not p:
            refused.append({"entry": path, "why": why})
            continue
        mode = "ro" if str(raw.get("mode") or "rw").lower() != "rw" else "rw"
        users = [str(u).strip() for u in (raw.get("users") or []) if str(u).strip()]
        if not any(o["path"] == p for o in out):
            out.append({"path": p, "mode": mode, "users": users})
    cfg = state["cfg"]
    cfg.setdefault("sandbox", {})["folders"] = out
    cfgmod.save_config(cfg)
    state["store"].log("system", f"shared folders updated ({len(out)})",
                       {"folders": [f"{o['mode']} {o['path']}" for o in out]})
    return {"ok": True, "folders": [{**o, "risk": folder_risk(o["path"], o["mode"])}
                                    for o in out],
            "refused": refused}


@app.get("/api/folders/risk")
async def api_folders_risk(path: str = "", mode: str = "ro"):
    """What is worth pausing over about this folder, asked WHILE it is typed.

    A read-only probe, so it is deliberately not admin-gated — it reveals nothing
    a directory listing would not, and gating it would mean the warning appears
    only after the save it exists to precede.
    """
    from .tools import check_safe_folder, folder_risk
    p, why = check_safe_folder(path)
    return {"risk": why or folder_risk(path, mode), "refused": bool(why and path.strip())}


@app.get("/api/shared")
async def api_shared(kind: str = ""):
    return {"shared": usersmod.shared(kind), "me": _me()}


@app.post("/api/shared")
async def api_share(body: dict):
    """Publish a COPY. Never a link — a shared app that changes under the people
    using it is a supply-chain problem living in a filesystem."""
    b = body or {}
    kind, name = str(b.get("kind") or ""), str(b.get("name") or "")
    store = state["store"]
    if kind == "agent":
        defn = store.get_subagent(name)
        if not defn:
            return JSONResponse({"error": f"no agent called '{name}'"}, status_code=404)
        payload = {k: v for k, v in defn.items() if k not in ("id", "created_at",
                                                              "updated_at", "builtin")}
    elif kind == "app":
        app_rec = next((a for a in store.list_apps(with_html=True)
                        if a.get("name") == name or a.get("id") == name), None)
        if not app_rec:
            return JSONResponse({"error": f"no app called '{name}'"}, status_code=404)
        # The HTML and nothing else. `app_data`, grants and the version history stay
        # behind: an app's stored data is whatever the publisher happened to be doing
        # with it, and shipping that with the app is a data leak wearing a feature's
        # clothes.
        payload = {"name": app_rec.get("name") or name, "icon": app_rec.get("icon") or "",
                   "description": app_rec.get("description") or "",
                   "html": app_rec.get("html") or ""}
    else:
        return JSONResponse({"error": f"only {', '.join(usersmod.SHAREABLE)} can be shared"},
                            status_code=400)
    try:
        rec = usersmod.publish(kind, name, payload, by=_me()["name"] or "this machine")
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    await state["broadcast"]({"type": "shared"})
    return {"ok": True, "shared": rec}


@app.post("/api/shared/take")
async def api_share_take(body: dict):
    """Install a shared copy into MY store. A copy again, so editing it afterwards
    is editing mine and cannot reach back to the person who published it."""
    b = body or {}
    kind, slug = str(b.get("kind") or ""), str(b.get("slug") or "")
    try:
        payload = usersmod.take(kind, slug)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    store = state["store"]
    if kind == "agent":
        name = payload.get("name") or slug
        while store.get_subagent(name):
            name += "-copy"
        store.save_subagent({**payload, "name": name, "builtin": 0})
        await state["broadcast"]({"type": "fabric_defs"})
        return {"ok": True, "installed": name}
    if kind == "app":
        # `save_app` keys on the name, so an unqualified install would silently
        # overwrite an app of mine that happens to share a name with a shared one.
        name = payload.get("name") or slug
        have = {a.get("name", "").lower() for a in store.list_apps()}
        while name.lower() in have:
            name += " (shared)" if not name.endswith("(shared)") else " copy"
        store.save_app(name, payload.get("icon") or "", payload.get("description") or "",
                       payload.get("html") or "", note=f"installed from shared:{slug}")
        await state["broadcast"]({"type": "apps"})
        return {"ok": True, "installed": name}
    return JSONResponse({"error": "unknown kind"}, status_code=400)


@app.delete("/api/shared/{kind}/{slug}")
async def api_unshare(kind: str, slug: str):
    try:
        return usersmod.unpublish(kind, slug, by=_me()["name"] or "",
                                  admin=usersmod.is_admin(usersmod.current()))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=403)


# ---------------------------------------------------------------------------
# Onboarding: the arc from a fresh install to a machine that is working.
#
# Every route here CREATES something — an agent, a flow, a schedule — rather than
# recording that a step happened. `onboarding.state()` then reads the machine back,
# so a step is ticked because the thing exists, not because a flag says so. That is
# what makes "run setup again" honest on day 300.
# ---------------------------------------------------------------------------

@app.get("/api/onboarding")
async def api_onboarding():
    return onboardmod.state(state["cfg"], state["store"])


@app.post("/api/onboarding/skip")
async def api_onboarding_skip(body: dict):
    step = str((body or {}).get("step") or "")
    try:
        res = (onboardmod.unskip if (body or {}).get("undo")
               else onboardmod.skip)(state["cfg"], step)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    cfgmod.save_config(state["cfg"])
    return {**res, **onboardmod.state(state["cfg"], state["store"])}


@app.post("/api/onboarding/confirm")
async def api_onboarding_confirm(body: dict):
    """"What is already there is what I want" — see onboarding.confirm."""
    step = str((body or {}).get("step") or "")
    try:
        res = onboardmod.confirm(state["cfg"], step)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    cfgmod.save_config(state["cfg"])
    return {**res, **onboardmod.state(state["cfg"], state["store"])}


@app.post("/api/onboarding/restart")
async def api_onboarding_restart():
    """Walk the arc again. NOT a factory reset — see onboarding.restart()."""
    onboardmod.restart(state["cfg"])
    cfgmod.save_config(state["cfg"])
    await state["broadcast"]({"type": "setup"})
    return onboardmod.state(state["cfg"], state["store"])


@app.post("/api/onboarding/hello")
async def api_onboarding_hello(body: dict):
    """One real turn against the chosen model, so the user watches it answer.

    Deliberately the ordinary chat path rather than a raw provider ping: what this
    step is proving is that the whole stack works — provider, key, model id, the
    agent loop — and a bare HTTP 200 from an API proves none of that.
    """
    model = (state["cfg"].get("default_model") or "").strip()
    if not model:
        return JSONResponse({"error": "no model is set yet"}, status_code=400)
    text = (body or {}).get("text") or (
        "In two sentences: what can you do on this machine that a chat website cannot?")
    cid = state["store"].create_conversation("✦ First hello")
    state["store"].add_message(cid, "user", text)

    async def emit(_ev):
        pass

    async def approver(*_a, **_k):
        return False        # a hello never needs to touch anything

    agent = Agent(state["cfg"], state["toolbox"], model, emit, approver,
                  conversation_id=cid, surface="gui")
    knowledge.turn_started()
    try:
        res = await asyncio.wait_for(
            agent.run([{"role": "user", "content": text}]), timeout=120)
    except asyncio.TimeoutError:
        return JSONResponse({"error": f"{model} did not answer within two minutes — "
                                      f"check the model name and key in Settings → "
                                      f"AI providers"}, status_code=504)
    except Exception as e:
        return JSONResponse({"error": f"{model} could not answer: {e}"}, status_code=400)
    finally:
        knowledge.turn_ended()
    reply = res.get("content") or "(no text came back)"
    state["store"].add_message(cid, "assistant", reply, {"steps": res.get("steps") or []})
    return {"ok": True, "model": model, "reply": reply, "conversation_id": cid}


@app.post("/api/onboarding/agent")
async def api_onboarding_agent(body: dict):
    """Create the starter specialist. The name is checked against what exists, so
    running setup twice makes a second one rather than silently overwriting the
    first — which might be one somebody has since edited."""
    defn = onboardmod.starter_agent(state["store"])
    defn.update({k: v for k, v in (body or {}).items()
                 if k in ("name", "soul", "tools", "max_steps", "max_seconds")})
    state["store"].save_subagent(defn)
    await state["broadcast"]({"type": "fabric_defs"})
    return {"ok": True, "agent": state["store"].get_subagent(defn["name"])}


@app.post("/api/onboarding/flow")
async def api_onboarding_flow(body: dict):
    """Create the starter flow, rostered with whatever specialists exist."""
    roster = [(body or {}).get("agent")] if (body or {}).get("agent") else \
        [s["name"] for s in state["store"].list_subagents() if not s.get("builtin")] or \
        [s["name"] for s in state["store"].list_subagents()]
    if not roster or not roster[0]:
        return JSONResponse({"error": "build an agent first — a flow orchestrates, "
                                      "it does not do the work itself"}, status_code=400)
    try:
        flow, report = flowsmod.save(state["store"],
                                     onboardmod.starter_flow(state["store"], roster))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    await state["broadcast"]({"type": "fabric_defs"})
    await state["broadcast"]({"type": "grants"})
    return {"ok": True, "flow": flow, "report": report}


@app.post("/api/setup/reset")
async def api_setup_reset(body: dict, request: Request):
    """Factory reset: wipe profile/data, reset config, re-arm the wizard.

    Loopback-only and admin-only. This destroys everything — including, on a
    multi-user machine, every account's home — so it is not something an app
    (which renders inside the desktop and reaches the API same-origin) or a remote
    session gets to trigger. The `SENSITIVE_FOR_APPS` guard blocks the app-referer
    case; this is the belt to that suspenders, and it also stops a signed-in
    executor from wiping the machine."""
    if not remotemod.is_loopback(_client_addr(request)):
        return JSONResponse({"error": "a factory reset can only be run from the machine itself"},
                            status_code=403)
    if usersmod.enabled() and not usersmod.is_admin(usersmod.current()):
        return JSONResponse({"error": "only an admin can factory-reset this machine"},
                            status_code=403)
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


# ---------------------------------------------------------------------------
# Jobs: a recipe, three answers, and something that runs by itself
#
# Thin on purpose. Every route here ends in `jobs.py`, which ends in `flows.py` —
# there is no job engine, no job scheduler and no job permission model, because a
# job IS a flow and a second one of any of those would be a second set of bugs.
# ---------------------------------------------------------------------------

@app.get("/api/jobs")
async def api_jobs(request: Request):
    """The catalogue, the ways out this machine actually has, and what is already
    running. One request, because the first-run screen needs all three at once and a
    wizard that renders in three waves is a wizard that flickers."""
    cfg = state["cfg"]
    return {"recipes": [r.as_dict() for r in jobsmod.RECIPES],
            "deliveries": jobsmod.deliveries(cfg),
            "installed": jobsmod.installed(state["store"])}


@app.post("/api/jobs/preview")
async def api_jobs_preview(body: dict):
    """What installing this would grant, before a row is written."""
    try:
        return jobsmod.preview(state["cfg"], state["store"],
                               (body or {}).get("recipe", ""), (body or {}).get("answers") or {})
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/jobs")
async def api_install_job(body: dict):
    try:
        res = jobsmod.install(state["cfg"], state["store"],
                              (body or {}).get("recipe", ""), (body or {}).get("answers") or {})
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    await state["broadcast"]({"type": "fabric_defs"})
    await state["broadcast"]({"type": "grants"})
    await state["broadcast"]({"type": "tasks"})
    res["next"] = jobsmod.describe_next(state["store"], res["flow"]["name"])
    return res


@app.post("/api/jobs/{name}/run")
async def api_run_job_now(name: str, request: Request):
    """Run a job this second, so the first one proves itself while somebody is watching.

    The whole point of the onboarding beat: a schedule you cannot see fire is a
    promise, and a new user has no reason to believe one. Same PDP decision and same
    run path as `/api/flows/{name}/run` — this is a convenience door, not a bypass.
    """
    flow = state["store"].get_flow(name)
    if not flow:
        return JSONResponse({"error": f"no job '{name}'"}, status_code=404)
    dec = state["pdp"].decide(MAIN, "agent.invoke", f"agent:flow/{name}",
                              {"surface": "gui", "risk": "safe"})
    if dec.effect == "deny":
        return JSONResponse({"error": dec.reason or "not permitted"}, status_code=403)
    run_id = await _start_flow(flow, "", origin={"surface": "gui",
                                                 "ref": _client_addr(request)})
    return {"ok": True, "run_id": run_id, "flow": name}


# ---------------------------------------------------------------------------
# Flows: the master orchestrator's control plane
# ---------------------------------------------------------------------------

@app.get("/api/flows")
async def api_flows(request: Request):
    store = state["store"]
    out = []
    for f in store.list_flows():
        trigs = store.flow_triggers(f["name"])
        for t in trigs:
            if t["kind"] == "webhook":
                # Built from how this request actually arrived, not from the configured
                # port: a server started on another port, reached over the LAN, or behind
                # a tunnel would otherwise hand out a URL that quietly does not work.
                t["url"] = flowsmod.hook_url(state["cfg"], f["name"], t,
                                             base=str(request.base_url).rstrip("/"))
        out.append({**f, "triggers": trigs,
                    "grants": [g for g in store.list_grants()
                               if (g.get("source_ref") or "") == flowsmod.source_ref(f["name"])],
                    # a disabled flow holds no grants, so the card has to be able to say
                    # what enabling it WOULD grant — that is the question being asked
                    "would_grant": flowsmod.declared_grants({**f, "enabled": 1})})
    return {"flows": out}


@app.post("/api/flows/compose")
async def api_compose_flow(body: dict):
    """Draft a flow from a sentence. Writes nothing — the draft opens in the editor and the
    user saves it, because a flow's definition is its permissions."""
    req = ((body or {}).get("request") or "").strip()
    if not req:
        return JSONResponse({"error": "describe what you want to happen"}, status_code=400)
    tools = [{"name": t["name"], "description": t.get("description", "")}
             for t in state["toolbox"].schemas()]
    draft = await flowsmod.compose(state["cfg"], state["store"], req, tools,
                                   model=(body or {}).get("model", ""),
                                   current=(body or {}).get("current"))
    if draft.get("error"):
        return JSONResponse(draft, status_code=502)
    # What it would grant, by the same pure function the editor's preview uses — so "what
    # does this cost me" is computed one way, not two. Validated with store=None on purpose:
    # the roster may name agents that do not exist yet because this draft proposes creating
    # them, and that is a question for Save, not for a preview.
    draft["grants"] = []
    if draft.get("roster"):
        try:
            # Triggers are validated separately: they do not affect what is granted, and a
            # malformed one must not blank out the permissions preview — which is the part
            # the user actually has to approve.
            draft["grants"] = flowsmod.declared_grants(
                flowsmod.validate({**draft, "triggers": []}, None))
        except ValueError as e:
            draft.setdefault("warnings", []).append(str(e))
    kept = []
    for t in (draft.get("triggers") or []):
        try:
            flowsmod._validate_trigger(t)
            kept.append(t)
        except ValueError as e:
            draft.setdefault("warnings", []).append(f"dropped a trigger: {e}")
    draft["triggers"] = kept
    return {"draft": draft}


@app.post("/api/flows/draft")
async def api_draft_flow(body: dict):
    """Compose a flow and put it in the list as a DISABLED card.

    No modal: a draft you can read next to your other flows beats one you have to answer.
    Disabled means it holds no permissions and no armed trigger, which is what makes
    creating it without asking first a safe thing to do."""
    req = ((body or {}).get("request") or "").strip()
    if not req:
        return JSONResponse({"error": "describe what you want to happen"}, status_code=400)
    tools = [{"name": t["name"], "description": t.get("description", "")}
             for t in state["toolbox"].schemas()]
    draft = await flowsmod.compose(state["cfg"], state["store"], req, tools,
                                   model=(body or {}).get("model", ""))
    if draft.get("error"):
        return JSONResponse(draft, status_code=502)
    if not draft.get("roster"):
        return JSONResponse({"error": f"{draft.get('model', 'the model')} did not pick any "
                                      f"agents for this — try saying it differently, or "
                                      f"build it by hand",
                             "warnings": draft.get("warnings") or []}, status_code=422)
    try:
        flow, report = flowsmod.save_draft(state["store"], draft)
    except ValueError as e:
        return JSONResponse({"error": str(e), "warnings": draft.get("warnings") or []},
                            status_code=422)
    await state["broadcast"]({"type": "fabric_defs"})
    return {"flow": flow, "report": report,
            "would_grant": flowsmod.declared_grants({**flow, "enabled": 1})}


@app.get("/api/flows/runs")
async def api_flow_executions(flow: str = "", limit: int = 80):
    """Every execution, newest first, optionally one flow's. This is the answer to "what
    has been running on this machine?" — which the runs list could not give, because it
    mixes flows, workflows and one-off delegations together."""
    store = state["store"]
    rows = [r for r in store.fabric_runs(limit=400) if r.get("kind") == "flow"]
    if flow:
        rows = [r for r in rows if (r.get("flow") or r.get("ref")) == flow]
    out = []
    for r in rows[:limit]:
        kids = store.fabric_runs(parent_run=r["id"])
        out.append({**r,
                    "delegations": len(kids),
                    "agents": sorted({k["ref"] for k in kids}),
                    "failed_steps": [k["ref"] for k in kids if k["status"] != "ok"],
                    "seconds": round((r.get("finished_at") or time.time()) - r["started_at"], 1)})
    return {"runs": out, "flows": sorted({(r.get("flow") or r.get("ref")) for r in rows}),
            "live": [i for i in state["fabric"].live_instances() if i.get("flow")]}


@app.post("/api/subagents/compose")
async def api_compose_subagent(body: dict):
    """Draft or revise one specialist. Writes nothing — the wizard opens with it filled in."""
    req = ((body or {}).get("request") or "").strip()
    if not req:
        return JSONResponse({"error": "say what it should do"}, status_code=400)
    tools = [{"name": t["name"], "description": t.get("description", "")}
             for t in state["toolbox"].schemas()]
    current = None
    if (body or {}).get("name"):
        current = state["store"].get_subagent(body["name"])
    d = await flowsmod.compose_subagent(state["cfg"], state["store"], req, tools,
                                        current=current, model=(body or {}).get("model", ""))
    if d.get("error"):
        return JSONResponse(d, status_code=502)
    return {"draft": d}


@app.post("/api/flows/{name}/enable")
async def api_enable_flow(name: str, body: dict | None = None):
    """Enabling is what grants. Until then a flow is words in a list."""
    on = bool((body or {}).get("enabled", True))
    try:
        flow, report = flowsmod.set_enabled(state["store"], name, on)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    await state["broadcast"]({"type": "fabric_defs"})
    await state["broadcast"]({"type": "grants"})
    return {"flow": flow, "report": report}


@app.post("/api/flows/{name}/discard")
async def api_discard_flow(name: str):
    res = flowsmod.discard(state["store"], name)
    if not res.get("ok"):
        return JSONResponse({"error": f"no flow '{name}'"}, status_code=404)
    await state["broadcast"]({"type": "fabric_defs"})
    await state["broadcast"]({"type": "grants"})
    return res


@app.post("/api/flows/preview")
async def api_flows_preview(body: dict):
    """What saving this definition WOULD grant. `declared_grants` is pure, so the answer
    can be shown before anything is written — a permission dialog that describes itself."""
    try:
        d = flowsmod.validate(body or {}, state["store"])
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"grants": flowsmod.declared_grants(d), "triggers": d["triggers"]}


@app.post("/api/flows")
async def api_save_flow(body: dict):
    try:
        flow, report = flowsmod.save(state["store"], body or {})
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    await state["broadcast"]({"type": "fabric_defs"})
    await state["broadcast"]({"type": "grants"})
    return {"flow": flow, "report": report}


@app.delete("/api/flows/{name}")
async def api_delete_flow(name: str):
    res = flowsmod.delete(state["store"], name)
    if not res.get("ok"):
        return JSONResponse({"error": f"no flow '{name}'"}, status_code=404)
    await state["broadcast"]({"type": "fabric_defs"})
    await state["broadcast"]({"type": "grants"})
    return res


@app.post("/api/flows/{name}/run")
async def api_run_flow(name: str, body: dict, request: Request):
    """Start a flow and return its run id.

    The run id comes back synchronously — unlike the older workflow route, which starts
    the work and leaves the caller to guess which run was theirs. The whole control plane
    is built on being able to name the run you just started.
    """
    flow = state["store"].get_flow(name)
    if not flow:
        return JSONResponse({"error": f"no flow '{name}'"}, status_code=404)
    # A flow you have not enabled CAN be run by hand, and that is the point: it is how you
    # find out what it would do before granting it anything. It is safe for the same reason
    # the disabled state is safe — it holds no grants, so every gated step stops and asks
    # you, and no trigger can start it while you are not looking. What "disabled" forbids
    # is running by itself, not being tried.
    surface = (body or {}).get("surface") or "gui"
    # Who started it goes in the ledger. A flow is an agent invocation like any other,
    # and "it just ran" is not an answer to "who asked for this?".
    dec = state["pdp"].decide(MAIN, "agent.invoke", f"agent:flow/{name}",
                              {"surface": surface, "risk": "safe"})
    if dec.effect == "deny":
        return JSONResponse({"error": dec.reason or "not permitted"}, status_code=403)
    run_id = await _start_flow(flow, (body or {}).get("input", ""),
                              origin={"surface": surface, "ref": _client_addr(request)},
                              conversation_id=(body or {}).get("conversation_id", ""))
    return {"ok": True, "run_id": run_id, "flow": name}


async def _start_flow(flow: dict, input_text: str, origin: dict, **kw) -> str:
    """Start a run in the background and hand back its id immediately.

    The id has to exist before the run does, so the caller can subscribe/redirect without
    polling for "the newest run and hopefully mine".
    """
    fut: asyncio.Future = asyncio.get_event_loop().create_future()

    async def go():
        try:
            res = await state["fabric"].run_flow(flow, input_text, origin=origin,
                                                 run_id_out=fut, **kw)
            return res
        except Exception as e:
            if not fut.done():
                fut.set_exception(e)
            raise
    asyncio.create_task(go())
    return await fut


@app.get("/api/flows/runs/{rid}/artifacts/{handle}")
async def api_flow_artifact(rid: str, handle: str):
    art = state["store"].artifact_get(rid, handle)
    if not art:
        return JSONResponse({"error": "no such handle on that board"}, status_code=404)
    return {"artifact": art}


@app.get("/api/flows/runs/{rid}/board")
async def api_flow_board(rid: str):
    return {"board": state["store"].artifact_index(rid)}


@app.post("/api/hooks/{name}/{trigger_id}")
async def api_flow_hook(name: str, trigger_id: str, request: Request):
    """Start a flow from outside this machine.

    Auth is the per-trigger secret and nothing else: this path sits outside the
    remote-access gate so a service on the internet can reach it. Everything cheap
    happens before anything expensive — unknown hook, bad secret and cooldown are all
    answered before the body is read, so a caller in a retry loop cannot make the OS do
    work by asking rudely. The body is content from outside this machine, so the run it
    starts is tainted: risky steps are shown to a person rather than assumed.
    """
    store = state["store"]
    trig = store.flow_trigger(trigger_id)
    given = request.headers.get("x-agentos-hook-secret") or request.query_params.get("k") or ""
    if not trig or trig["kind"] != "webhook" or not trig["enabled"] or \
            (trig["flow"] or "").lower() != (name or "").lower():
        return JSONResponse({"error": "unknown hook"}, status_code=404)
    if not hmac.compare_digest(str(given), str(trig.get("secret") or "\0")):
        store.log("error", f"webhook: bad secret for flow '{name}'",
                  {"trigger": trigger_id, "from": _client_addr(request)})
        return JSONResponse({"error": "bad secret"}, status_code=401)
    now = time.time()
    wait = (trig.get("cooldown_secs") or 0) - (now - (trig.get("last_fired") or 0))
    if wait > 0:
        store.flow_trigger_fired(trigger_id, dropped=True)
        return JSONResponse({"error": "cooling down", "retry_after": int(wait) + 1},
                            status_code=429)
    flow = store.get_flow(trig["flow"])
    if not flow or not flow.get("enabled"):
        return JSONResponse({"error": "that flow is gone or disabled"}, status_code=409)
    raw = (await request.body())[:64_000].decode("utf-8", "replace")
    store.flow_trigger_fired(trigger_id)
    run_id = await _start_flow(flow, raw,
                               origin={"surface": "webhook", "ref": trigger_id},
                               trigger_id=trigger_id, tainted=True)
    return JSONResponse({"ok": True, "run_id": run_id, "flow": flow["name"]}, status_code=202)


@app.get("/api/fabric/approvals")
async def api_fabric_approvals():
    """What is paused right now, waiting for a person.

    This exists so the TUI and the CLI are first-class here rather than spectators: until
    now only a websocket client could answer an approval, which meant a flow started from
    a terminal could only be watched failing.
    """
    out = []
    for aid, entry in (state.get("pending_approvals") or {}).items():
        if entry["fut"].done():
            continue
        out.append({"id": aid, "name": entry.get("name", ""), "args": entry.get("args", {}),
                    "reason": entry.get("reason", ""), "offer": entry.get("offer"),
                    "run_id": entry.get("run_id", ""), "flow": entry.get("flow", ""),
                    "asked_at": entry.get("asked_at", 0)})
    return {"approvals": out}


@app.post("/api/fabric/approvals/{aid}")
async def api_fabric_approve(aid: str, body: dict):
    await resolve_approval(aid, bool((body or {}).get("approved")),
                           bool((body or {}).get("remember")))
    return {"ok": True}


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
    history, _hinfo = await _history_for(cid, model)
    store.add_message(cid, "user", text)
    history.append({"role": "user", "content": text})

    async def emit(_ev):
        pass

    async def approver(_n, _a, _r, _offer=None):
        return cfg.get("autonomy") == "full"

    # apps call from inside the desktop (GUI); everything else is the headless API gate
    from . import executors as execmod
    engine = execmod.resolve_engine(cfg)
    # An APP asking for a turn is machinery, not a person: it expects AgentOS's
    # tools and its own data store, neither of which an executor has. Forwarding
    # it would break the app, so a forwarder still answers apps itself.
    if engine != "aria" and principal.kind != "app":
        knowledge.turn_started()
        try:
            content, _run = await execmod.forward(
                engine, text, cfg, str(cfgmod.AGENTOS_HOME / "workspace"))
        finally:
            knowledge.turn_ended()
        result = {"content": content, "steps": [{"type": "executor", "name": engine}],
                  "tokens": {"input": 0, "output": 0}}
    else:
        from . import spaces as spacemod
        _surface = "gui" if principal.kind == "app" else "api"
        agent = Agent(cfg, toolbox, model, emit, approver, conversation_id=cid,
                      principal=principal, surface=_surface,
                      space_id=spacemod.active_for(cfg, _surface, store, cid))
        knowledge.turn_started()
        try:
            result = await agent.run(history)
        finally:
            knowledge.turn_ended()
    store.add_message(cid, "assistant", result["content"], {"steps": result["steps"]})
    store.touch_conversation(cid)
    usagemod.record(store, cfg, model, result.get("tokens") or {},
                    surface=("gui" if principal.kind == "app" else "api"),
                    principal=principal.label, conversation_id=cid)
    knowledge.schedule_extraction(cfg, store, cid, text, result["content"], state.get("broadcast"))
    return {"conversation_id": cid, "content": result["content"], "steps": result["steps"]}


async def _history_for(cid: str, model_id: str = "") -> tuple[list[dict], dict]:
    """Rebuild model-facing history: prior turns' tool traces replayed compactly,
    and anything past the context budget folded into a rolling summary. See
    `history.py` for why both of those are the module's job and not this one's."""
    return await historymod.build(state["store"], cid, state["cfg"], model_id)


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

def _ws_origin_ok(ws) -> bool:
    """Refuse a WebSocket handshake that a foreign page opened.

    This is the socket half of `csrf_origin_guard`, and it closes a hole that
    guard could not see. A browser attaches the site's cookies to a WebSocket
    connection AND is not stopped from opening one at a cross-origin URL — the
    same-origin policy does not cover the WS handshake. So a page on the open
    internet, while AgentOS is running on `localhost`, can open
    `ws://localhost:<port>/ws/terminal` and, because `_ws_authed` trusts loopback
    (or trusts nothing at all on a fresh single-user box), be handed a shell on
    the machine. That is Cross-Site WebSocket Hijacking, and on this OS it is
    remote code execution.

    Browsers ALWAYS send `Origin` on a WS handshake, so the rule mirrors
    `_same_origin`: a present Origin must match the Host, `null` (a sandboxed or
    file:// opener) is refused, and an ABSENT Origin is allowed — that is a
    non-browser client (a CLI, a test) with no ambient cookie to abuse, exactly
    the case the HTTP guard also leaves to the auth gate.
    """
    origin = ws.headers.get("origin")
    if not origin:
        return True                      # non-browser: no cookie jar, no CSRF
    if origin == "null":
        return False
    from urllib.parse import urlsplit
    return urlsplit(origin).netloc == ws.headers.get("host", "")


async def _ws_reject(ws) -> bool:
    """One gate every socket passes before `accept()`: cross-origin first, then
    auth. Returns True when the handshake was refused (and already closed), so a
    handler reads `if await _ws_reject(ws): return`. Having ONE gate is the point
    — an origin check that each new socket has to remember to add is one a new
    socket will eventually forget, and this OS's sockets include a shell."""
    if not _ws_origin_ok(ws):
        with contextlib.suppress(Exception):
            state["store"].log("system", "refused a cross-origin WebSocket",
                               {"origin": ws.headers.get("origin", ""),
                                "path": ws.url.path})
        with contextlib.suppress(Exception):
            await ws.close(code=4403)     # 4403: our "forbidden origin"
        return True
    if not _ws_authed(ws):
        with contextlib.suppress(Exception):
            await ws.close(code=4401)
        return True
    return False


def _ws_authed(ws) -> bool:
    """Websockets do not pass through HTTP middleware, so the same gate is
    applied by hand here — a socket is a longer-lived and more capable channel
    than any REST call, and the terminal one is literally a shell."""
    cfg = state.machine_cfg()
    if usersmod.enabled():
        # A machine with accounts is locked by them: only a valid signed session
        # cookie gets a socket, whichever transport it arrived on. Loopback trust
        # cannot survive multi-user for the same reason it cannot for HTTP — see
        # _authed — so it is deliberately not consulted here.
        return _ws_user(ws) is not None
    if not remotemod.enabled(cfg):
        return True
    if cfg["remote"].get("trust_loopback", True) and \
       remotemod.is_loopback((ws.client.host if ws.client else "") or ""):
        return True
    return remotemod.valid_session(cfg, ws.cookies.get(remotemod.COOKIE, ""))


def _ws_user(ws) -> str | None:
    """Which account this socket belongs to, from the SIGNED cookie only.

    None means the cookie did not verify. The empty string is a real answer: a
    single-user machine, where '' is the machine account and every turn runs as
    it. This is the WebSocket half of the `resolve_user` middleware — the HTTP
    middleware never runs for a socket, so a turn launched from the receive loop
    would otherwise resolve `state["store"]` to the machine on a multi-user box,
    quietly reading and writing the wrong person's memory, grants and ledger.
    """
    if not usersmod.enabled():
        return ""
    uid = remotemod.session_user(state.machine_cfg(), ws.cookies.get(remotemod.COOKIE, ""))
    if uid is None or (uid and not usersmod.get(uid)):
        return None
    return uid or ""


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
    if await _ws_reject(ws):
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
    if await _ws_reject(ws):
        return
    import fcntl
    import os
    import pty
    import signal
    import struct
    import termios

    # On a machine with accounts the Terminal is a real shell, so it is exactly the
    # place the data boundary would leak: without a jail, whoever opened it could
    # read every other account's home. So it fails closed — a jail per account, or
    # no shell — and it opens in the acting account's own home, not the OS user's.
    ws_uid = _ws_user(ws) or ""
    from .tools import bwrap_argv, folder_binds, sandbox_conf, sandbox_mechanism
    # The same safe folders the agent's own tools use. The Terminal is the other
    # half of "the agent may work here" — a folder the agent can read and the
    # Terminal cannot is a difference nobody can explain from the outside.
    sb_ro, sb_extra = folder_binds(state.machine_cfg(), ws_uid or None)
    if usersmod.enabled():
        if not sandbox_mechanism():
            await ws.accept()
            with contextlib.suppress(Exception):
                await ws.send_text("This machine has accounts, so the Terminal must run in a "
                                   "per-account jail — install bubblewrap to enable it.\r\n")
                await ws.close()
            return
        home = os.path.realpath(str(usersmod.home_for(ws_uid)))
        os.makedirs(home, exist_ok=True)
        jail = bwrap_argv(home, ["/bin/bash", "-l"], chdir=home,
                          hide=[os.path.realpath(str(usersmod.users_root()))],
                          extra=sb_extra, ro_extra=sb_ro)
    else:
        sandboxed, sb_root = sandbox_conf(state.machine_cfg())
        if sandboxed:
            Path(sb_root).mkdir(parents=True, exist_ok=True)
        jail = bwrap_argv(sb_root, ["/bin/bash", "-l"], extra=sb_extra,
                          ro_extra=sb_ro) if sandboxed else None

    await ws.accept()
    shell = os.environ.get("SHELL", "/bin/bash")
    pid, fd = pty.fork()
    if pid == 0:  # child: become the user's shell, jailed to their own home
        env = dict(os.environ)
        env["TERM"] = "xterm-256color"
        if jail:
            os.execvpe("bwrap", jail, env)
        try:
            os.chdir(os.path.expanduser("~"))
        except OSError:
            pass
        os.execvpe(shell, [shell, "-l"], env)

    with usersmod.as_user(ws_uid):
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
            "uid": data.get("uid", ""),   # the turn that flushes this must run as the same account
            "status": "queued", "reason": "", "at": time.time()}
    state["queues"].setdefault(cid, []).append(item)
    return item


def _queue_public(cid: str) -> list[dict]:
    """The queue as the UI sees it — text and decision only, never image payloads."""
    return [{"id": i["id"], "text": i["text"], "images": len(i["images"]),
             "status": i["status"], "reason": i["reason"], "at": i["at"]}
            for i in state["queues"].get(cid) or []]


async def _queue_broadcast(cid: str, **extra):
    # A queue belongs to one conversation, which belongs to one account — scope it
    # to that owner's sessions, the same as the turn's own events. The owner is on
    # the turn slot (a queue only exists while a turn is running).
    owner = str(state["turns"].get(cid, {}).get("uid", "") or "")
    await state["broadcast_user"]({"type": "queue_update", "conversation_id": cid,
                                   "queue": _queue_public(cid), **extra}, owner)


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
            "context": item["context"], "conversation_id": cid,
            "uid": item.get("uid", "")}
    state["turns"][cid] = {"agent": None, "task": None, "model": ""}   # claim, then start
    state["turns"][cid]["task"] = asyncio.create_task(run_chat(cid, data))
    await _queue_broadcast(cid, started={"id": item["id"], "text": item["text"]})


async def run_chat(cid: str, data: dict):
    """One chat turn, running as its own task — several conversations may run at
    once. Two guarantees on every exit path: the turn slot is released, and a
    terminal event reaches the UI."""
    # Enter the owning account's context BEFORE the first `state["store"]` read:
    # store/cfg/PDP all resolve through `users.current()`, so a turn that read them
    # first and entered the context second would act as the machine, not the user.
    with usersmod.as_user(data.get("uid", "")):
        return await _run_chat(cid, data)


async def _run_chat(cid: str, data: dict):
    cfg, store, toolbox = state["cfg"], state["store"], state["toolbox"]
    turns = state["turns"]
    text = (data.get("text") or "").strip()

    # The account that owns this turn, server-set from the socket's signed cookie
    # (never from the client). Its events reach only that account's own sessions —
    # a turn's working indicator, tokens, reply and approval card are private to
    # the person who started it, not to whoever else is signed in on the machine.
    owner = str(data.get("uid", "") or "")

    async def evsend(ev: dict):
        await state["broadcast_user"]({**ev, "conversation_id": cid}, owner)

    async def approver(name: str, args: dict, reason: str, offer: dict | None = None) -> bool:
        # global broker: the card renders in this chat, but any client may answer
        return await request_approval(name, args, reason, offer=offer, evsend=evsend)

    agent = None
    started = False
    header = ""
    model = data.get("model") or cfg.get("default_model", "")
    # A machine set to forward answers every turn with the other agent, whichever
    # surface it arrived from — chat, omnibar, copilot panel. An explicit engine
    # in the request still wins, so one chat can opt out of the machine setting.
    from . import executors as execmod
    engine = execmod.resolve_engine(cfg, data.get("model") or "")
    if engine != "aria":
        model = engine
    result = {"content": "", "steps": [], "tokens": {"input": 0, "output": 0}}
    # A cloud model nobody has priced does not get to run first and be costed
    # later. Asked once per model, then remembered either way.
    if usagemod.needs_price(cfg, model):
        if not await request_price(model, evsend=evsend):
            await evsend({"type": "error",
                          "message": f"cancelled — {model} has no price set yet"})
            await evsend({"type": "turn_end", "conversation_id": cid})
            turns.pop(cid, None)
            return
    try:
        images = _chat_images(data)
        history, hinfo = await _history_for(cid, model)
        if hinfo.get("compacted"):
            # Never silent: a thread that has been summarised behaves differently
            # from one that has not, and the user is the only one who can tell us
            # the summary lost something that mattered.
            await evsend({"type": "status",
                          "message": f"earlier messages ({hinfo['compacted']}) summarised — "
                                     f"this conversation outgrew the model's context window"})
        store.add_message(cid, "user", text, {"images": images} if images else None)
        entry = {"role": "user", "content": text}
        if images:
            entry["images"] = images
        history.append(entry)
        store.touch_conversation(cid)

        # '@subagent task' addresses a team member directly — it runs INSIDE this chat,
        # streaming its steps like a normal turn, and still shows up in Observability
        mention = fabricmod.parse_mention(store, text)
        # A message trigger can start a flow from the chat too. `@name` is resolved first
        # and always wins: an explicit address is not a pattern to be second-guessed.
        flow_hit = None
        if not mention:
            try:
                flow_hit = flowsmod.match_message(store, text, surface="gui")
            except Exception:
                flow_hit = None
        if model == "claude-code":
            # Engine = Claude Code: delegate the turn to the coding agent already
            # installed on this machine. It keeps AgentOS's turn lifecycle — working
            # indicator, global turn slot, Stop, persistence — because its stream is
            # translated into the same events a local turn emits. AgentOS still owns
            # the desktop; the executor only gets the envelope configured in
            # Settings → Executors, decided before the run rather than per call.
            from . import executors as execmod
            avail = execmod.available()
            if not avail.get("available"):
                raise RuntimeError(avail.get("reason") or "Claude Code is not available")
            env = execmod.envelope_from(cfg, str(cfgmod.AGENTOS_HOME / "workspace"))
            # From the conversation row, not a dict on the server: a restart used to
            # drop every chat's executor session, so a machine that had been running
            # for a week came back with every conversation a stranger.
            env.session_id = store.exec_session(cid)
            # The same per-surface context the built-in agent gets as extra_system.
            # Without it a delegated copilot turn arrived as a bare sentence with
            # no idea which app it was about — the executor is sanitizing it.
            env.context = execmod.context_for(str(data.get("context") or ""))
            # A copilot turn names its app in the origin. If it is a user app,
            # check it out to a real file first: an executor that only understands
            # files could otherwise never touch an app that lives in a DB row, and
            # explaining that was honest but useless.
            # AgentOS has two kinds of app and they are opposites: a USER app is a
            # row in the database (check it out to a file the executor can edit),
            # a BUILT-IN app is the OS's own source. Telling someone asking about
            # the Settings window that "apps live in the database, use App Studio"
            # was both false and a dead end, so the kind is resolved here.
            checkout = None
            origin = str(data.get("origin") or "")
            if origin.startswith("copilot:"):
                app_id = origin.split(":", 1)[1]
                try:
                    checkout = execmod.checkout_app(store, app_id, env.workspace)
                except Exception:
                    checkout = None
                if checkout:
                    env.context += execmod.app_checkout_note(checkout, env.tools)
                elif app_id:
                    env.context += execmod.builtin_app_note(app_id, env.allow_source)
            if not checkout:
                # A plain chat turn. Give it somewhere to put an app if it is asked
                # for one — an executor cannot call create_app, so without this the
                # work lands in a scratch directory App Studio has never heard of,
                # which is what "I built it and it is nowhere" was. The note is
                # conditional and the file starts EMPTY, so a turn that was not an
                # app build installs nothing.
                try:
                    checkout = execmod.new_app_checkout(env.workspace, text[:60])
                    env.context += execmod.new_app_note(checkout)
                except Exception:
                    checkout = None
            run = execmod.Run()
            turns[cid] = {"agent": None, "task": asyncio.current_task(),
                          "model": "claude-code", "executor": run, "uid": owner}
            knowledge.turn_started()
            started = True
            await evsend({"type": "turn_start", "model": "claude-code"})
            # Named for the step it actually is: launching the CLI takes seconds
            # on its own, and "working…" for that gap is indistinguishable from
            # a run that never started.
            await evsend({"type": "status", "message": "starting Claude Code"})
            collected: list[str] = []

            async def _relay(ev: dict):
                if ev.get("type") == "text_delta":
                    collected.append(ev.get("text", ""))
                await evsend(ev)

            try:
                await execmod.run_task(text, env, _relay, run)
            finally:
                execmod.stop(run)          # a cancelled turn must not leave it running
            if run.session_id:
                # Keep the executor's own session so the next turn in this chat is a
                # continuation rather than a stranger with no memory of the last one.
                store.set_exec_session(cid, run.session_id)
            if checkout:
                # Write the edit back as a new app version, and SAY so — a change
                # that appears without a word is indistinguishable from a bug.
                saved, why = execmod.commit_app(store, checkout)
                if saved:
                    await evsend({"type": "status", "message": why})
                    await state["broadcast"]({"type": "apps"})
                elif why:
                    await evsend({"type": "status", "message": why})
            header = ""
            result = {"content": "".join(collected),
                      "steps": [{"type": "executor", "name": "claude-code",
                                 "cost_usd": run.cost_usd, "turns": run.turns,
                                 "denials": run.denials, "envelope": env.describe()}],
                      # who actually answered, so a reloaded conversation still
                      # attributes it correctly rather than crediting the built-in agent
                      "engine": "claude-code", "engine_model": run.model,
                      "tokens": {"input": 0, "output": 0}}
        elif flow_hit:
            trig, flow = flow_hit
            model = state["fabric"].resolve_model({"name": flow["name"],
                                                   "model": flow.get("model") or ""})
            turns[cid] = {"agent": None, "task": asyncio.current_task(),
                          "model": model, "uid": owner}
            knowledge.turn_started()
            started = True
            await evsend({"type": "turn_start", "model": model})
            await evsend({"type": "status",
                          "message": f"flow '{flow['name']}' started — watch it in Workflows → Flows"})
            res = await state["fabric"].run_flow(
                flow, text, origin={"surface": "gui", "ref": trig["id"]},
                conversation_id=cid, trigger_id=trig["id"], approver=approver,
                ui_emit=evsend, agent_slot=turns[cid])
            content = res["content"] or (f"({res['status']}: {res['fault']})" if res["fault"]
                                         else f"({res['status']})")
            header = f"▲ {flow['name']} · {res['delegations']} delegations\n\n"
            if not res["content"]:
                await evsend({"type": "text_delta", "text": header + content})
            usage = res.get("usage") or {}
            result = {"content": content, "steps": [],
                      "tokens": {"input": usage.get("in", 0), "output": usage.get("out", 0)}}
        elif mention:
            defn, task = mention
            model = state["fabric"].resolve_model(defn)
            turns[cid] = {"agent": None, "task": asyncio.current_task(),
                          "model": model, "uid": owner}
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
            # SURFACES is imported at module scope: a function-local `from … import`
            # here made it local to the WHOLE of run_chat, so the finally block
            # referencing it raised UnboundLocalError on every turn that failed
            # before this line — and that exception ate the persistence of the
            # error message itself, leaving an empty bubble instead of the reason.
            surface = data.get("surface") if data.get("surface") in SURFACES else "gui"
            # Copilot/omnibar turns ride the normal chat path with per-surface
            # context appended to the system prompt (the app's live state, the
            # embedded-panel preamble). Sanitized and capped — it is UI-supplied.
            extra = str(data.get("context") or "")[:4096]
            extra = "".join(ch for ch in extra if ch == "\n" or ch == "\t" or ord(ch) >= 32)
            from . import spaces as spacemod
            agent = Agent(cfg, toolbox, model, evsend, approver, conversation_id=cid,
                          surface=surface, extra_system=extra,
                          space_id=spacemod.active_for(cfg, surface, store, cid))
            # anything the user queued while this turn was being set up (the slot is
            # claimed before the task starts) is handed over here, once
            for queued in state["queues"].get(cid) or []:
                agent.offer(queued)
            agent.on_steer_decision = _steer_hook(cid)
            turns[cid] = {"agent": agent, "task": asyncio.current_task(),
                          "model": model, "uid": owner}
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
        # A turn that failed must still leave a message saying so. An empty
        # assistant bubble is the worst outcome: reloading the conversation shows
        # nothing at all, and the reason lives only in a log nobody opened.
        if not (result.get("content") or "").strip():
            result["content"] = f"[error] {type(e).__name__}: {e}"
    finally:
        if started:
            knowledge.turn_ended()
        # Saving the reply comes first and alone. Everything after it is
        # bookkeeping, and bookkeeping that throws must not be able to eat the
        # answer — which is exactly what happened when an UnboundLocalError below
        # skipped this call and left the bubble empty.
        try:
            store.add_message(cid, "assistant", header + result["content"],
                              {"steps": result["steps"],
                               # a reloaded conversation must still say who answered
                               **({"engine": result["engine"]} if result.get("engine") else {}),
                               **({"engine_model": result["engine_model"]}
                                  if result.get("engine_model") else {}),
                               **({"model": model} if model and not result.get("engine") else {})})
            store.touch_conversation(cid)
            tk = result.get("tokens") or {}
            store.log("turn", text[:200], {"conversation_id": cid, "model": model,
                                           "steps": len(result["steps"]),
                                           "in": tk.get("input", 0), "out": tk.get("output", 0)})
            # The turn counted its tokens and used to drop them here. They are the
            # answer to "what did today cost me", which nothing in the OS could
            # say. Read from `data` rather than the local set inside the try: this
            # runs on the failure paths too, and a turn that died after spending
            # tokens has still spent them.
            from . import spaces as _spacemod
            _surface = data.get("surface") if data.get("surface") in SURFACES else "gui"
            usagemod.record(store, cfg, model, tk, surface=_surface, conversation_id=cid,
                            space_id=_spacemod.active_for(cfg, _surface, store, cid))
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
    # Raw rebuild, no tool traces and no compaction: this path does its own
    # bounding (the `keep` window plus the source stripping below), and a build
    # turn's traces carry app source that the stripping is there to remove.
    hist = historymod.render(state["store"].get_messages(cid), {"tool_trace": False})[-keep:]
    for m in hist:
        m.pop("_id", None)
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


@app.get("/api/pricing")
async def api_pricing():
    """Every model this machine knows a price for, and where the price came from."""
    cfg = state["cfg"]
    user = cfg.get("pricing") or {}
    return {"user": user, "skipped": cfg.get("pricing_skip") or [],
            "defaults": [{"pattern": p, "in": r[0], "out": r[1]}
                         for p, r in usagemod.DEFAULT_PRICING],
            "default_model": cfg.get("default_model", ""),
            "default_model_state": usagemod.price_state(cfg, cfg.get("default_model", ""))}


@app.post("/api/pricing/lookup")
async def api_pricing_lookup(body: dict | None = None):
    """Try to find a published price for a model. Never writes anything."""
    return await usagemod.discover_price(state["cfg"], str((body or {}).get("model") or ""))


@app.put("/api/pricing")
async def api_pricing_set(body: dict | None = None):
    """Set or clear a model's price. `{model, in, out}` or `{model, skip: true}`."""
    body = body or {}
    model = str(body.get("model") or "").strip()
    if not model:
        return JSONResponse({"error": "model is required"}, status_code=400)
    if body.get("skip"):
        usagemod.skip_price(state["cfg"], model)
    elif body.get("clear"):
        (state["cfg"].get("pricing") or {}).pop(model, None)
    else:
        try:
            usagemod.set_price(state["cfg"], model, float(body.get("in", 0)),
                               float(body.get("out", 0)))
        except (TypeError, ValueError):
            return JSONResponse({"error": "in/out must be numbers (USD per million tokens)"},
                                status_code=400)
    cfgmod.save_config(state["cfg"])
    await state["broadcast"]({"type": "pricing"})
    return {"ok": True, "state": usagemod.price_state(state["cfg"], model)}


@app.get("/api/usage")
async def api_usage(days: float = 1.0, group: str = "model", space: str = ""):
    """What has been spent. `group`: model | day | surface | kind | conversation | space."""
    return usagemod.report(state["store"], state["cfg"], days=days, group=group, space=space)


@app.get("/api/evals")
async def api_evals():
    """The cases and the last run. The GUI face of `agentos eval`."""
    from . import evals as evalsmod
    cases = [{k: v for k, v in c.items() if not k.startswith("_")}
             for c in evalsmod.load_cases()]
    return {"cases": cases, "last": evalsmod.last_report(),
            "default_model": state["cfg"].get("default_model", "")}


@app.post("/api/evals/run")
async def api_evals_run(body: dict | None = None):
    """Run the suite and return the report.

    Deliberately synchronous and un-streamed: a run is a minute or two of real
    model calls, and the one thing that must not happen is two of them at once
    fighting over the same local GPU. The lock says so rather than queueing
    silently."""
    from . import evals as evalsmod
    body = body or {}
    if state.get("evals_running"):
        return JSONResponse({"error": "an eval run is already going — one at a time, "
                                      "so they do not fight over the model"}, status_code=409)
    models = [m for m in (body.get("models") or []) if isinstance(m, str)] \
        or [state["cfg"].get("default_model", "")]
    models = [m for m in models if m]
    if not models:
        return JSONResponse({"error": "no model configured to test"}, status_code=400)
    bcast = state.get("broadcast")

    async def progress(r):
        if bcast:
            await bcast({"type": "eval_result",
                         "result": {"id": r["id"], "status": r["status"],
                                    "model": r["model"], "seconds": r["seconds"]}})

    state["evals_running"] = True
    try:
        report = await evalsmod.run(
            models, only=body.get("cases") or None, tags=body.get("tags") or None,
            network=bool(body.get("network")), on_result=progress)
        evalsmod.save(report)
        state["store"].log("test", "evals: " + ", ".join(
            f"{m} {s['passed']}/{s['passed'] + s['failed'] + s['errors']} passed"
            for m, s in report["by_model"].items()), {"kind": "evals"})
        if bcast:
            await bcast({"type": "evals_done"})
        return report
    finally:
        state["evals_running"] = False


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
    # Two different questions, and the pillar was only ever answering one of them:
    # pytest says the OS works, evals say the AGENT still behaves. Neither
    # substitutes for the other, so both are reported with their own last result.
    from . import evals as evalsmod
    ev = evalsmod.last_report()
    out["test"] = {"suite": "tests/ (pytest)", "last": last_test,
                   "gate": "self-modification restarts run the suite first",
                   "evals": {
                       "cases": len(evalsmod.load_cases()),
                       "last": ({"created_at": ev["created_at"], "by_model": ev["by_model"]}
                                if ev else None),
                       "gate": "run on request (needs a live model) — `agentos eval`"}}

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
    try:
        spend = usagemod.report(store, cfg, days=1.0)
    except Exception:
        spend = {"cost_usd": 0, "tokens_in": 0, "tokens_out": 0, "unpriced_turns": 0, "note": ""}
    out["manage"] = {"autonomy": cfg.get("autonomy", ""), "model": cfg.get("default_model", ""),
                     "grants": grants, "snapshots": snaps,
                     "sandbox": bool((cfg.get("sandbox") or {}).get("enabled")),
                     "spend_24h": spend}
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
    with usersmod.as_user(data.get("uid", "")):   # the app is built into the owner's store
        return await _run_build(data)


async def _run_build(data: dict):
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
    # Identity is the USER's, not the model's. Left to itself the builder names an
    # app after the sentence that asked for it ("build an application ...") and
    # then makes a SECOND one next time the sentence differs. A name typed here is
    # authoritative: applied to an existing app before the build so create_app
    # updates in place, and forced onto a new one after it.
    want_name = (data.get("name") or "").strip()[:60]
    want_icon = data.get("icon") if isinstance(data.get("icon"), str) else None
    if existing and (want_name or want_icon is not None):
        err = store.rename_app(app_id, name=want_name, icon=want_icon)
        if err:
            await bcast({"type": "build_error_note", "message": err})
        existing = store.get_app(app_id) or existing
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
        elif want_name:
            ctx = (f"Build this app and name it EXACTLY \"{want_name}\" — that is the user's "
                   f"chosen name, not a suggestion. Do not name it after their request.\n\n"
                   f"{prompt}")
        store.add_message(cid, "user", prompt)
        history.append({"role": "user", "content": ctx})

        # enough steps to spec → ground → build → fix, but still bounded; builds get a
        # bigger output budget than chat (a whole app must fit in one tool call), and
        # the thinking channel is OFF — a local thinking model can burn its entire
        # budget reasoning and never emit the app
        # 10 steps was a ceiling set for one-shot local builds, and it is the reason
        # an ambitious brief came back as a sketch: spec → ground → build → fix
        # leaves nothing for actually finishing. A capable model gets room to
        # iterate; small local ones keep the tighter bound they need.
        _cap = 10 if (model or "").startswith("ollama/") else int(cfg.get("build_max_steps", 26))
        bcfg = {**cfg, "max_steps": _cap,
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

        # Claude Code builds the app as a FILE, over as many steps as it needs.
        # The built-in builder gets one turn to emit an entire app in one fenced
        # block, which is why an ambitious brief comes back as a sketch: there is
        # no room to write it, read it back and fix it. An executor works the way
        # a person does, so this is the path for anything bigger than a widget.
        if model == "claude-code":
            from . import executors as execmod
            avail = execmod.available()
            if not avail.get("available"):
                await terminal({"type": "build_error",
                                "message": avail.get("reason", "Claude Code is not available")})
                return
            env = execmod.envelope_from(cfg, str(cfgmod.AGENTOS_HOME / "workspace"))
            if not any(t in env.tools for t in ("Write", "Edit")):
                await terminal({"type": "build_error",
                                "message": ("Claude Code cannot build an app without Write or "
                                            "Edit — tick them in Settings → Executors")})
                return
            # A build is long work; a chat-sized ceiling stops it mid-app, which is
            # the one failure that produces nothing usable at all.
            env.budget_usd = max(env.budget_usd, execmod.BUILD_MIN_BUDGET_USD)
            # Refining keeps the SAME name, because create_app updates in place by
            # name — a new name would silently leave a duplicate app behind. A name
            # the user typed wins over one derived from their sentence.
            app_name = (existing or {}).get("name") or want_name or (prompt[:40] or "New app")
            co = execmod.prepare_build(env.workspace, app_name,
                                       (existing or {}).get("html", ""))
            env.context = execmod.context_for("")
            run = execmod.Run()
            build["executor"] = run
            await bcast({"type": "build_text",
                         "text": f"\n(building with Claude Code in {co['dir']} — "
                                 f"up to ${env.budget_usd:.2f})\n"})

            async def erelay(ev: dict):
                t = ev.get("type")
                if t == "text_delta":
                    await bcast({"type": "build_text", "text": ev.get("text", "")})
                elif t == "tool_start":
                    await bcast({"type": "build_tool", **ev})
                elif t == "tool_end":
                    await bcast({"type": "build_tool_end", **ev})
                elif t == "error":
                    await bcast({"type": "build_error_note", **ev})
                elif t == "thinking_delta":
                    # A delegated build can think for a minute before its first
                    # tool call. Dropping this left "working… 45s" as the only
                    # sign of life, which reads exactly like a hang.
                    await bcast({"type": "build_thinking", "text": ev.get("text", "")})
                elif t == "engine_info":
                    # Say who is actually building and on what — the Studio was
                    # showing a generic spinner for someone else's agent.
                    await bcast({"type": "build_engine", **ev})

            # A heartbeat, because the gaps are the problem. An executor can sit
            # inside one Bash call for minutes with nothing to relay, and silence
            # is indistinguishable from a hang — so say what it is on and how long
            # it has been there, whether or not anything new arrived.
            async def epulse():
                t0 = time.time()
                while True:
                    await asyncio.sleep(10)
                    secs = int(time.time() - t0)
                    where = run.last or "thinking"
                    await bcast({"type": "build_status",
                                 "message": f"{where} · step {run.steps} · "
                                            f"{secs // 60}m {secs % 60:02d}s"
                                            + (f" · ${run.cost_usd:.2f}" if run.cost_usd else "")})

            pulse = asyncio.create_task(epulse())
            relay_failed = ""
            bpersona = persona_for("claude-code")

            async def stage(label: str, task: str) -> str:
                """One executor turn. Returns '' or the relay failure.

                Each stage is its own turn on purpose. The persona already asked for
                spec-then-build-then-fix "silently, in one turn", and that is exactly
                the instruction a model drops: there is nothing to show for the spec
                and the build is right there. Separate turns make each stage's output
                a file that either exists or does not.

                A stage that loses its stream is NOT a stage that failed — the work is
                on disk. Note it and go on to the next one; only the file at the end
                decides whether there is an app.
                """
                nonlocal relay_failed
                await bcast({"type": "build_status", "message": label})
                await bcast({"type": "build_text", "text": f"\n— {label} —\n"})
                try:
                    await execmod.run_task(task, env, erelay, run)
                    return ""
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    relay_failed = f"{type(exc).__name__}: {exc}"
                    store.log("error", f"executor stream failed ({label}): {relay_failed}"[:400])
                    return relay_failed

            try:
                # 1. SPEC — decide what it is before writing any of it.
                await stage("planning", execmod.plan_task(
                    prompt, co, bpersona, existing=bool(existing)))
                spec = execmod.read_side_file(co, "spec")
                if not spec:
                    await bcast({"type": "build_text",
                                 "text": "(no spec was written — building from the "
                                         "request directly)\n"})

                # 2. BUILD — against that spec.
                if not build.get("cancel_requested"):
                    await stage("building", execmod.build_task(
                        prompt, co, bpersona, spec=spec))

                # 3. REVIEW — read it back adversarially, with the mechanical
                #    findings handed over as a floor.
                if not build.get("cancel_requested"):
                    interim, _ = execmod.read_build(co)
                    rep = appcheck.check(interim, _known_tool_names(toolbox))
                    if interim:
                        await stage("reviewing", execmod.review_task(
                            co, bpersona, findings=rep.brief()))

                # 4. FIX — apply the review, unless it said there is nothing to.
                if not build.get("cancel_requested"):
                    review = execmod.read_side_file(co, "review")
                    interim, _ = execmod.read_build(co)
                    rep = appcheck.check(interim, _known_tool_names(toolbox))
                    if review and execmod.review_says_ship(review) and not rep.worth_fixing:
                        await bcast({"type": "build_text",
                                     "text": "\n— review says ship; nothing to fix —\n"})
                    elif review or rep.worth_fixing:
                        await stage("fixing", execmod.fix_task(
                            co, bpersona, review=review, findings=rep.brief()))
            finally:
                pulse.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pulse
                execmod.stop(run)
                build["executor"] = None
            html, problem = execmod.read_build(co)
            if problem:
                await terminal({"type": "build_error",
                                "message": f"{relay_failed} — {problem}" if relay_failed else problem})
                return
            if relay_failed:
                await bcast({"type": "build_error_note",
                             "message": f"lost contact with the executor ({relay_failed}) — "
                                        f"installing the app it had already written"})
            out = await toolbox.create_app(app_name, want_icon or (existing or {}).get("icon", ""),
                                           (existing or {}).get("description") or prompt[:160],
                                           html)
            if str(out).startswith("[error]"):
                await terminal({"type": "build_error", "message": str(out)})
                return
            built = store.get_app(app_id) if existing else _app_by_name(store, app_name)
            if not built:
                await terminal({"type": "build_error",
                                "message": "the app was built but could not be found afterwards"})
                return
            if want_icon is not None or (want_name and not existing):
                store.rename_app(built["id"], name=want_name if not existing else "",
                                 icon=want_icon)
            store.add_message(cid, "assistant",
                              f"Built with Claude Code (${run.cost_usd:.2f}).",
                              {"engine": "claude-code", "engine_model": run.model})
            if not existing:
                store.touch_conversation(cid, f"build: {built['name']}")
            # The same close-out a one-shot build gets. It used to send `app` here
            # and nothing else: the Studio keys on `app_id`, so a build that had
            # actually succeeded printed "no app was produced", left the preview
            # empty, and never asked for the app's permissions.
            manifest_status, remaining = _finish_build_checks(built["id"])
            await bcast({"type": "apps"})
            await terminal({"type": "build_done", "app_id": built["id"],
                            "name": built["name"], "model": "claude-code",
                            "summary": f"Built with Claude Code in {run.steps} steps "
                                       f"(${run.cost_usd:.2f}).",
                            "manifest_status": manifest_status,
                            "warnings": remaining})
            return

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
                    salvage_name = sname or want_name or (prompt[:40] or "New app")
                    out = await toolbox.create_app(salvage_name, "", sdesc or prompt[:160], shtml)
                    if not str(out).startswith("[error]"):
                        # by name, not `list_apps()[0]` — that list is sorted by name
                        newest = _app_by_name(store, salvage_name)
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
        if built and not existing and (want_name or want_icon is not None):
            # the model named it after the request; the user already said what it
            # is called. Re-read it, because the name is what everything shows.
            err = store.rename_app(built["id"], name=want_name, icon=want_icon)
            if err:
                await bcast({"type": "build_error_note", "message": err})
            built = store.get_app(built["id"]) or built
        if built and not existing:
            # the "new app" session becomes this app's session — refinements continue it
            store.touch_conversation(cid, f"build: {built['name']}")
        manifest_status = "none"
        remaining: list[str] = []
        if built:  # builder didn't declare permissions? scan the source and propose them
            # anything the repair pass could not fix ships as an explicit warning,
            # never as a silent "success"
            manifest_status, remaining = _finish_build_checks(built["id"])
        await state["broadcast"]({"type": "apps"})
        if built:
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
    if await _ws_reject(ws):
        return
    await ws.accept()
    state["clients"].add(ws)
    turns, build = state["turns"], state["build"]

    # Which account owns this socket, from the signed cookie, resolved once. Every
    # turn and build started below is stamped with it and runs inside
    # `users.as_user(uid)` — create_task copies the CURRENT context, and the receive
    # loop's context is not the user's because no HTTP middleware runs for a socket.
    ws_uid = _ws_user(ws) or ""
    # Remember which account this socket belongs to, so a turn's events reach only
    # its owner's sessions (see `broadcast_user`). Registered here rather than at
    # `.add()` above because the uid is not known until the cookie is resolved.
    state["client_uids"][ws] = ws_uid

    async def send(event: dict):
        with contextlib.suppress(Exception):
            await ws.send_text(json.dumps(event))

    # a (re)connecting client learns what is still running, so a page reload never
    # strands a spinner — the UI re-attaches (or clears) by conversation_id. Only
    # THIS account's turns: another account's running conversation is not this
    # user's to see, and reporting it here is what showed a freshly signed-in user
    # a spinner "from the previous session".
    await send({"type": "state_sync",
                "running": [c for c, t in turns.items() if t.get("uid", "") == ws_uid],
                "queues": {c: _queue_public(c) for c in state["queues"]
                           if turns.get(c, {}).get("uid", "") == ws_uid},
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
                    # A new conversation is born into the surface's active space and
                    # stays there. Reopening it next month must not silently move it
                    # to whatever project was clicked last — see spaces.py.
                    from . import spaces as spacemod
                    from .policy import SURFACES as _SURFACES
                    _surface = (data.get("surface")
                                if data.get("surface") in _SURFACES else "gui")
                    _space = str(data.get("space_id") or "") or spacemod.active_for(
                        state["cfg"], _surface)
                    cid = state["store"].create_conversation(title, origin=origin,
                                                             space_id=_space)
                    await send({"type": "conversation", "id": cid, "title": title,
                                "origin": origin, "space_id": _space})
                # claim before the task starts, stamped with the owner so a
                # state_sync racing the task creation still scopes it correctly
                turns[cid] = {"agent": None, "task": None, "model": "", "uid": ws_uid}
                data["uid"] = ws_uid   # server-set, never from the client
                turns[cid]["task"] = asyncio.create_task(run_chat(cid, data))
            elif t == "build":
                if build.get("task") and not build["task"].done():
                    await send({"type": "build_error", "message": "A build is already running — wait for it."})
                else:
                    data["uid"] = ws_uid
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
            elif t == "price":
                await resolve_price(data.get("id", ""), str(data.get("action") or "cancel"),
                                    float(data.get("in") or 0), float(data.get("out") or 0))
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
        state["client_uids"].pop(ws, None)
