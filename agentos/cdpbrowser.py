"""The shared browser: one real Chromium per person, that the person and the agent use together.

Browser agents fail where people do not: a hidden headless browser meets a CAPTCHA, a
sign-in or a 2FA code, and nobody is there. Here the browser is a window on the desktop.
Its pixels are a CDP screencast (Page.startScreencast) drawn into a Bento window, the
person's mouse and keys go back as real input (Input.dispatch*), and the agent drives the
SAME tab through the same connection. When the agent meets a wall it hands over
(`wait_for_person`): the window pulses, the person signs in or types the code inside it,
and the agent carries on with that signed-in session. Nothing is copied between two
browsers, because there is only one.

How it is wired, and why:

- **A pipe, never a port.** Chromium is started with `--remote-debugging-pipe` (fds 3 and
  4, through a `sh` wrapper that maps them to our stdin and stdout). A debugging PORT is a
  door any local process can open, and this browser holds the person's signed-in sessions;
  a pipe belongs to the process that started it. The WhatsApp bridge's rule again.
- **One profile per person, kept.** `<home>/browser/profile` in the person's own home, so
  sign-ins survive a restart (the "persistent" in persistent browser) and an account never
  sees another's cookies. The process itself stops after `IDLE_S` with nobody watching
  and no agent step; the profile stays. The disk cache is capped.
- **Web pages only.** Navigation, from the agent or from the window's address bar, is
  `http`, `https` or `about:blank`. Chromium runs as the OS user, so `file://` would let a
  page read any file on the disk, and on a machine with accounts any other account's
  home: the browser tools would become a way round the file gate. The tools also refuse
  to read a tab that is showing anything else.
- **The agent's steps go through the gate like any tool.** Reading a page is safe and
  untrusted (its words are somebody else's). Clicking and typing are risky: in a signed-in
  browser a click can buy, post or delete. The source of a page's taint is its site, so
  the gate can tell content read from the same site apart (policy: `same-site`).
- **Everybody sees the agent's hand.** Every agent click and keystroke is announced to the
  window (`agent` events) and drawn there, so the person is never surprised by a page that
  moved on its own.

Stdlib only (asyncio), and no HTTP: the server owns the socket and the routes.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

CANDIDATES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
              "microsoft-edge", "microsoft-edge-stable", "brave-browser")
MAC_APPS = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")
SCHEMES = ("http", "https")
IDLE_S = 20 * 60            # the process stops after this long unwatched and unused
MAX_TABS = 8
VIEW = (1280, 800)          # the page size before a window says its own
MIN_VIEW, MAX_VIEW = (320, 240), (2560, 1600)
WAIT_S, WAIT_MAX_S = 300, 900
TEXT_MAX = 6000             # what browser_read hands the model of a page's words
ELEMENTS_MAX = 120
CACHE_BYTES = 50 * 1024 * 1024

# Wired by the server: who gets told when the browser needs a person, and whether anyone
# is at a screen to be told. Unwired, nobody is (a test, a terminal).
_ATTENTION = [None]          # async (uid, payload) -> None
_PRESENCE = [lambda uid: False]


def bind(attention=None, presence=None):
    if attention is not None:
        _ATTENTION[0] = attention
    if presence is not None:
        _PRESENCE[0] = presence


# ---- which browser, and can it run here ------------------------------------------------

def binary(cfg: dict | None = None) -> str:
    """The Chromium-family browser to drive: an explicit setting, then the usual names on
    PATH, then the macOS app bundles. '' when there is none."""
    want = os.environ.get("AGENTOS_CHROMIUM") or str(((cfg or {}).get("browser") or {}).get("binary") or "")
    if want:
        return want if (os.path.isfile(want) or shutil.which(want)) else ""
    for name in CANDIDATES:
        p = shutil.which(name)
        if p:
            return p
    if sys.platform == "darwin":
        for p in MAC_APPS:
            if os.path.isfile(p):
                return p
    return ""


def status(cfg: dict | None = None) -> dict:
    """Can the shared browser run here, and if not, the sentence and the component."""
    if os.name == "nt":
        return {"ok": False, "why": "The shared browser is not available on Windows yet: it "
                                    "needs a POSIX shell to hand Chromium its pipe.",
                "install": ""}
    b = binary(cfg)
    if not b:
        return {"ok": False, "why": "No Chromium-family browser was found. Install Chromium (or "
                                    "Chrome, Edge or Brave) and the browser window can open.",
                "install": "chromium"}
    return {"ok": True, "binary": b, "why": "", "install": ""}


def allowed(url: str) -> str:
    """'' when a URL may be opened, else the sentence that refuses it."""
    u = str(url or "").strip()
    if u in ("", "about:blank"):
        return ""
    p = urlparse(u)
    if p.scheme not in SCHEMES or not p.netloc:
        return (f"the shared browser opens web pages only (http or https), not "
                f"'{p.scheme or u[:20]}:' addresses")
    return ""


def normalise(url: str) -> str:
    """What a person typed in the address bar, as a URL: a bare name gets https."""
    u = str(url or "").strip()
    if not u:
        return "about:blank"
    if "://" not in u and not u.startswith("about:"):
        u = ("https://" + u) if ("." in u and " " not in u) else \
            "https://duckduckgo.com/?q=" + "+".join(u.split())
    return u


def site_of(url: str) -> str:
    """The host a page is on, without a leading www. — the unit the gate reasons about."""
    h = (urlparse(str(url or "")).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


# ---- the CDP connection ----------------------------------------------------------------

class CDPError(RuntimeError):
    pass


class CDP:
    """JSON messages separated by NUL over Chromium's debugging pipe, with flattened
    sessions (one connection, every tab addressed by its sessionId)."""

    def __init__(self, proc):
        self.proc = proc
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._handlers: dict[str, list] = {}
        self._task = asyncio.create_task(self._read())
        self.closed = asyncio.Event()

    def on(self, method: str, fn):
        self._handlers.setdefault(method, []).append(fn)

    async def send(self, method: str, params: dict | None = None, session: str | None = None,
                   timeout: float = 30.0) -> dict:
        if self.closed.is_set():
            raise CDPError("the browser has closed")
        self._id += 1
        msg = {"id": self._id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        fut = asyncio.get_running_loop().create_future()
        self._pending[self._id] = fut
        try:
            self.proc.stdin.write(json.dumps(msg).encode() + b"\0")
            await self.proc.stdin.drain()
            res = await asyncio.wait_for(fut, timeout)
        except (BrokenPipeError, ConnectionResetError):
            raise CDPError("the browser has closed") from None
        finally:
            self._pending.pop(msg["id"], None)
        if isinstance(res, dict) and "__error__" in res:
            raise CDPError(str(res["__error__"].get("message") or res["__error__"]))
        return res

    async def _read(self):
        try:
            while True:
                raw = await self.proc.stdout.readuntil(b"\0")
                try:
                    d = json.loads(raw[:-1])
                except ValueError:
                    continue
                if "id" in d:
                    fut = self._pending.get(d["id"])
                    if fut and not fut.done():
                        fut.set_result({"__error__": d["error"]} if "error" in d else d.get("result") or {})
                    continue
                for fn in self._handlers.get(d.get("method") or "", []):
                    try:
                        r = fn(d.get("params") or {}, d.get("sessionId") or "")
                        if asyncio.iscoroutine(r):
                            asyncio.create_task(r)
                    except Exception:
                        pass
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionResetError):
            pass
        finally:
            self.closed.set()
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_result({"__error__": {"message": "the browser has closed"}})


# ---- what the agent reads off a page -----------------------------------------------------

# One pass over the page: its words, the things that can be pressed or filled (each
# tagged data-bento-ref so a click lands on exactly what the model was shown), and
# whether it is a wall only a person can get past.
SNAPSHOT_JS = r"""(() => {
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 2 && r.height > 2 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity !== 0; };
  const nameOf = e => (e.getAttribute('aria-label') || e.innerText || e.value || e.placeholder ||
                       e.title || e.alt || e.name || '').trim().replace(/\s+/g, ' ').slice(0, 80);
  const sel = 'a[href],button,input:not([type=hidden]),select,textarea,[role=button],[role=link],' +
              '[role=checkbox],[role=tab],[role=menuitem],[contenteditable=true],summary';
  const els = []; let n = 0;
  document.querySelectorAll('[data-bento-ref]').forEach(e => e.removeAttribute('data-bento-ref'));
  for (const e of document.querySelectorAll(sel)) {
    if (!vis(e)) continue;
    n += 1; if (els.length >= %(max)d) continue;
    e.setAttribute('data-bento-ref', String(n));
    els.push({ref: n, tag: e.tagName.toLowerCase(), role: e.getAttribute('role') || '',
              type: (e.getAttribute('type') || '').toLowerCase(), name: nameOf(e),
              value: (e.tagName === 'INPUT' && !/password/i.test(e.type) && e.value) ? String(e.value).slice(0, 60) : ''});
  }
  const text = (document.body ? document.body.innerText : '').replace(/\n{3,}/g, '\n\n');
  const t = (text || '').slice(0, 20000);
  let wall = null;
  const q = s => [...document.querySelectorAll(s)].some(vis);
  if (q('iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[src*="challenges.cloudflare.com"],iframe[title*="challenge" i],.g-recaptcha,.h-captcha,.cf-turnstile')
      || /verify (that )?you are (a )?human|are you a robot|unusual traffic|press and hold/i.test(t.slice(0, 3000)))
    wall = {kind: 'captcha', why: 'a check that a person is there (CAPTCHA)'};
  else if (q('input[autocomplete="one-time-code"]') ||
           ([...document.querySelectorAll('input')].some(i => vis(i) && /otp|2fa|totp|mfa|verification|one.?time|passcode/i.test((i.name || '') + ' ' + (i.id || '') + ' ' + (i.placeholder || ''))) &&
            /code/i.test(t.slice(0, 4000))))
    wall = {kind: 'code', why: 'a sign-in code (two-factor)'};
  else if (q('input[type=password]'))
    wall = {kind: 'login', why: 'a sign-in with a password'};
  return {url: location.href, title: document.title, text: t, elements: els, more: Math.max(0, n - els.length), wall};
})()"""

BOX_JS = r"""(ref => { const e = document.querySelector('[data-bento-ref="' + ref + '"]');
  if (!e) return null; e.scrollIntoView({block: 'center', inline: 'center'});
  const r = e.getBoundingClientRect();
  return {x: r.left + r.width / 2, y: r.top + r.height / 2, name: (e.getAttribute('aria-label') || e.innerText || e.value || e.placeholder || e.tagName).trim().slice(0, 60)}; })"""

FIND_JS = r"""(want => { want = want.toLowerCase();
  const all = [...document.querySelectorAll('a[href],button,input,select,textarea,[role=button],[role=link],summary,label')];
  const e = all.find(e => ((e.getAttribute('aria-label') || e.innerText || e.value || e.placeholder || '').trim().toLowerCase()) === want)
        || all.find(e => ((e.getAttribute('aria-label') || e.innerText || e.value || e.placeholder || '').toLowerCase()).includes(want));
  if (!e) return null; e.scrollIntoView({block: 'center', inline: 'center'});
  const r = e.getBoundingClientRect();
  return {x: r.left + r.width / 2, y: r.top + r.height / 2, name: (e.getAttribute('aria-label') || e.innerText || e.value || e.placeholder || e.tagName).trim().slice(0, 60)}; })"""

# Keys a person (or the agent) can press by name. Everything else arrives as text.
KEYS = {"Enter": ("Enter", "Enter", 13, "\r"), "Tab": ("Tab", "Tab", 9, ""),
        "Escape": ("Escape", "Escape", 27, ""), "Backspace": ("Backspace", "Backspace", 8, ""),
        "Delete": ("Delete", "Delete", 46, ""), "ArrowUp": ("ArrowUp", "ArrowUp", 38, ""),
        "ArrowDown": ("ArrowDown", "ArrowDown", 40, ""), "ArrowLeft": ("ArrowLeft", "ArrowLeft", 37, ""),
        "ArrowRight": ("ArrowRight", "ArrowRight", 39, ""), "Home": ("Home", "Home", 36, ""),
        "End": ("End", "End", 35, ""), "PageUp": ("PageUp", "PageUp", 33, ""),
        "PageDown": ("PageDown", "PageDown", 34, ""), " ": (" ", "Space", 32, " ")}


# ---- one person's browser --------------------------------------------------------------

class Browser:
    def __init__(self, uid: str, cfg: dict, home: Path):
        self.uid, self.cfg, self.home = uid or "", cfg, Path(home)
        self.proc = None
        self.cdp: CDP | None = None
        self.tabs: dict[str, dict] = {}       # targetId -> {session, url, title}
        self.active = ""
        self.size = VIEW
        self.viewers: dict[int, dict] = {}    # id -> {"bytes": fn, "json": fn, "frame": None, "busy": False}
        self._vid = 0
        self.casting = ""                     # the session being screencast
        self.attention: dict | None = None
        self.resumed = asyncio.Event()
        self.last_use = time.time()
        self.started = 0.0
        self.ua = ""
        self._lock = asyncio.Lock()
        self._watch = None

    # -- life --
    @property
    def running(self) -> bool:
        return bool(self.proc and self.proc.returncode is None and self.cdp and not self.cdp.closed.is_set())

    async def start(self):
        if self.running:
            return
        st = status(self.cfg)
        if not st["ok"]:
            raise CDPError(st["why"])
        prof = self.home / "browser" / "profile"
        prof.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(self.home / "browser", 0o700)
        args = [st["binary"], "--headless=new", "--remote-debugging-pipe",
                f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check",
                "--disable-background-networking", "--disable-sync", "--mute-audio",
                f"--disk-cache-size={CACHE_BYTES}", "--password-store=basic",
                f"--window-size={self.size[0]},{self.size[1]}", "about:blank"]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            args.insert(2, "--no-sandbox")    # Chromium refuses to start as root otherwise
        self.proc = await asyncio.create_subprocess_exec(
            "sh", "-c", 'exec "$0" "$@" 3<&0 4>&1 0</dev/null 1>/dev/null', *args,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=64 * 1024 * 1024)
        self.cdp = CDP(self.proc)
        try:
            ver = await self.cdp.send("Browser.getVersion", timeout=20)
        except Exception as e:
            await self.stop()
            raise CDPError(f"the browser did not start ({e})") from None
        self.ua = str(ver.get("userAgent") or "").replace("HeadlessChrome", "Chrome")
        self.cdp.on("Page.screencastFrame", self._on_frame)
        self.cdp.on("Target.targetInfoChanged", self._on_target)
        self.cdp.on("Target.targetCreated", self._on_target_created)
        self.cdp.on("Target.targetDestroyed", self._on_target_gone)
        await self.cdp.send("Target.setDiscoverTargets", {"discover": True})
        down = Path(str(self.cfg.get("workspace") or self.home)) / "Downloads"
        with contextlib.suppress(Exception):
            down.mkdir(parents=True, exist_ok=True)
            await self.cdp.send("Browser.setDownloadBehavior",
                                {"behavior": "allow", "downloadPath": str(down)})
        self.started = time.time()
        # the about:blank Chromium opened with is a page target we did not create
        for t in (await self.cdp.send("Target.getTargets")).get("targetInfos", []):
            if t.get("type") == "page":
                await self._attach(t["targetId"], t.get("url") or "about:blank")
        if not self.tabs:
            await self.new_tab("about:blank")
        self._watch = asyncio.create_task(self._idle())

    async def stop(self):
        with contextlib.suppress(Exception):
            if self.cdp and not self.cdp.closed.is_set():
                await self.cdp.send("Browser.close", timeout=5)
        if self.proc and self.proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.proc.kill()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.proc.wait(), 5)
        if self._watch and self._watch is not asyncio.current_task():
            self._watch.cancel()
        self.tabs, self.active, self.casting = {}, "", ""
        await self._state()

    async def _idle(self):
        while self.running:
            await asyncio.sleep(30)
            if not self.viewers and time.time() - self.last_use > IDLE_S and not self.attention:
                await self.stop()
                return

    def touch(self):
        self.last_use = time.time()

    # -- tabs --
    async def _attach(self, target: str, url: str):
        if target in self.tabs:
            return self.tabs[target]
        s = (await self.cdp.send("Target.attachToTarget", {"targetId": target, "flatten": True}))["sessionId"]
        tab = {"session": s, "url": url, "title": ""}
        self.tabs[target] = tab
        for m in ("Page.enable", "Runtime.enable"):
            with contextlib.suppress(Exception):
                await self.cdp.send(m, {}, s)
        with contextlib.suppress(Exception):
            await self.cdp.send("Network.setUserAgentOverride", {"userAgent": self.ua}, s)
        await self._metrics(s)
        if not self.active:
            self.active = target
        return tab

    async def _metrics(self, s: str):
        with contextlib.suppress(Exception):
            await self.cdp.send("Emulation.setDeviceMetricsOverride",
                                {"width": self.size[0], "height": self.size[1],
                                 "deviceScaleFactor": 1, "mobile": False}, s)

    def _on_target_created(self, p, _s):
        info = p.get("targetInfo") or {}
        if info.get("type") == "page" and info.get("targetId") not in self.tabs and \
                len(self.tabs) < MAX_TABS and info.get("openerId"):
            # a page opened a window (target=_blank): it becomes a tab here, and the one shown
            async def go():
                with contextlib.suppress(Exception):
                    await self._attach(info["targetId"], info.get("url") or "")
                    await self.switch(info["targetId"])
            return go()

    def _on_target(self, p, _s):
        info = p.get("targetInfo") or {}
        tab = self.tabs.get(info.get("targetId") or "")
        if tab:
            tab["url"], tab["title"] = info.get("url") or tab["url"], info.get("title") or ""
            return self._state()

    def _on_target_gone(self, p, _s):
        tid = p.get("targetId") or ""
        if tid in self.tabs:
            self.tabs.pop(tid, None)
            if self.active == tid:
                self.active = next(iter(self.tabs), "")
                self.casting = ""
                return self._recast()
            return self._state()

    def tab(self) -> dict:
        return self.tabs.get(self.active) or {}

    async def new_tab(self, url: str = "about:blank") -> str:
        if len(self.tabs) >= MAX_TABS:
            raise CDPError(f"{MAX_TABS} tabs are open; close one first")
        bad = allowed(url)
        if bad:
            raise CDPError(bad)
        t = (await self.cdp.send("Target.createTarget", {"url": url}))["targetId"]
        await self._attach(t, url)
        await self.switch(t)
        return t

    async def switch(self, target: str):
        if target not in self.tabs:
            return
        self.active = target
        await self.cdp.send("Target.activateTarget", {"targetId": target})
        await self._recast()

    async def close_tab(self, target: str):
        if target in self.tabs and len(self.tabs) > 1:
            await self.cdp.send("Target.closeTarget", {"targetId": target})

    # -- the picture --
    async def _recast(self):
        want = self.tab().get("session", "") if self.viewers else ""
        if self.casting == want:
            return await self._state()
        if self.casting:
            with contextlib.suppress(Exception):
                await self.cdp.send("Page.stopScreencast", {}, self.casting)
        self.casting = ""
        if want:
            await self.cdp.send("Page.startScreencast",
                                {"format": "jpeg", "quality": 72, "maxWidth": self.size[0],
                                 "maxHeight": self.size[1], "everyNthFrame": 1}, want)
            self.casting = want
        await self._state()

    async def _on_frame(self, p, s):
        with contextlib.suppress(Exception):
            await self.cdp.send("Page.screencastFrameAck", {"sessionId": p.get("sessionId")}, s)
        if s != self.casting:
            return
        data = base64.b64decode(p.get("data") or "")
        for v in list(self.viewers.values()):
            v["frame"] = data
            if not v["busy"]:
                asyncio.create_task(self._flush(v))

    async def _flush(self, v):
        v["busy"] = True
        try:
            while v["frame"] is not None:
                f, v["frame"] = v["frame"], None   # latest frame wins: a slow phone skips, never queues
                await v["bytes"](f)
        except Exception:
            pass
        finally:
            v["busy"] = False

    def snapshot_state(self) -> dict:
        t = self.tab()
        return {"type": "state", "running": self.running, "url": t.get("url", ""),
                "title": t.get("title", ""), "size": list(self.size),
                "tabs": [{"id": k, "title": v.get("title") or site_of(v.get("url")) or "New tab",
                          "url": v.get("url", ""), "active": k == self.active}
                         for k, v in self.tabs.items()],
                "attention": self.attention}

    async def _state(self):
        await self._tell(self.snapshot_state())

    async def _tell(self, msg: dict):
        for v in list(self.viewers.values()):
            with contextlib.suppress(Exception):
                await v["json"](msg)

    # -- viewers (the person's windows) --
    async def add_viewer(self, send_bytes, send_json, w: int = 0, h: int = 0) -> int:
        self._vid += 1
        self.viewers[self._vid] = {"bytes": send_bytes, "json": send_json, "frame": None, "busy": False}
        self.touch()
        if w and h:
            await self.resize(w, h)
        await self._recast()
        return self._vid

    async def drop_viewer(self, vid: int):
        self.viewers.pop(vid, None)
        if not self.viewers:
            await self._recast()

    async def resize(self, w: int, h: int):
        w = max(MIN_VIEW[0], min(MAX_VIEW[0], int(w)))
        h = max(MIN_VIEW[1], min(MAX_VIEW[1], int(h)))
        if (w, h) == tuple(self.size):
            return
        self.size = (w, h)
        for t in self.tabs.values():
            await self._metrics(t["session"])
        if self.casting:
            # the screencast's size is fixed when it starts: restart it at the new one
            with contextlib.suppress(Exception):
                await self.cdp.send("Page.stopScreencast", {}, self.casting)
            self.casting = ""
        if self.viewers:
            await self._recast()

    async def person(self, op: dict):
        """One thing the person did in the window: a pointer, a key, text, navigation."""
        self.touch()
        k = op.get("type")
        s = self.tab().get("session")
        if not s and k not in ("tab_new",):
            return
        if k == "mouse":
            ev = {"mousePressed": "mousePressed", "mouseReleased": "mouseReleased",
                  "mouseMoved": "mouseMoved"}.get(op.get("kind"))
            if not ev:
                return
            await self.cdp.send("Input.dispatchMouseEvent",
                                {"type": ev, "x": float(op.get("x", 0)), "y": float(op.get("y", 0)),
                                 "button": op.get("button") or ("none" if ev == "mouseMoved" else "left"),
                                 "buttons": int(op.get("buttons") or 0),
                                 "clickCount": int(op.get("clicks") or (1 if ev != "mouseMoved" else 0)),
                                 "modifiers": int(op.get("mods") or 0)}, s)
        elif k == "wheel":
            await self.cdp.send("Input.dispatchMouseEvent",
                                {"type": "mouseWheel", "x": float(op.get("x", 0)), "y": float(op.get("y", 0)),
                                 "deltaX": float(op.get("dx", 0)), "deltaY": float(op.get("dy", 0))}, s)
        elif k == "key":
            await self._key(s, str(op.get("key") or ""), int(op.get("mods") or 0))
        elif k == "text":
            txt = str(op.get("text") or "")[:2000]
            if txt:
                await self.cdp.send("Input.insertText", {"text": txt}, s)
        elif k == "navigate":
            url = normalise(op.get("url"))
            bad = allowed(url)
            if bad:
                return await self._tell({"type": "notice", "text": bad})
            await self.cdp.send("Page.navigate", {"url": url}, s)
        elif k in ("back", "forward"):
            h = await self.cdp.send("Page.getNavigationHistory", {}, s)
            i = h.get("currentIndex", 0) + (-1 if k == "back" else 1)
            ent = h.get("entries") or []
            if 0 <= i < len(ent):
                await self.cdp.send("Page.navigateToHistoryEntry", {"entryId": ent[i]["id"]}, s)
        elif k == "reload":
            await self.cdp.send("Page.reload", {}, s)
        elif k == "tab_new":
            await self.new_tab("about:blank")
        elif k == "tab_switch":
            await self.switch(str(op.get("id") or ""))
        elif k == "tab_close":
            await self.close_tab(str(op.get("id") or ""))
        elif k == "resize":
            await self.resize(int(op.get("w") or 0), int(op.get("h") or 0))
        elif k == "resume":
            # "Done, carry on": the person has signed in or typed the code
            self.attention = None
            self.resumed.set()
            await self._state()

    async def _key(self, s: str, key: str, mods: int = 0):
        if key in KEYS:
            k, code, vk, text = KEYS[key]
            down = {"type": "keyDown" if text else "rawKeyDown", "key": k, "code": code,
                    "windowsVirtualKeyCode": vk, "modifiers": mods}
            if text:
                down["text"] = text
            await self.cdp.send("Input.dispatchKeyEvent", down, s)
            await self.cdp.send("Input.dispatchKeyEvent",
                                {"type": "keyUp", "key": k, "code": code, "windowsVirtualKeyCode": vk,
                                 "modifiers": mods}, s)
        elif len(key) == 1:
            if mods & 2 or mods & 4:   # ctrl/cmd + a letter: a shortcut (select all, copy…)
                up = key.upper()
                ev = {"key": key, "code": f"Key{up}" if up.isalpha() else "", "modifiers": mods,
                      "windowsVirtualKeyCode": ord(up)}
                await self.cdp.send("Input.dispatchKeyEvent", {"type": "rawKeyDown", **ev}, s)
                await self.cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", **ev}, s)
            else:
                await self.cdp.send("Input.insertText", {"text": key}, s)

    # -- the agent's hand --
    async def _eval(self, expr: str, s: str | None = None):
        s = s or self.tab().get("session")
        r = await self.cdp.send("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                                    "awaitPromise": True}, s)
        if r.get("exceptionDetails"):
            raise CDPError(str((r["exceptionDetails"].get("exception") or {}).get("description")
                               or r["exceptionDetails"].get("text") or "script error")[:200])
        return (r.get("result") or {}).get("value")

    async def settle(self, timeout: float = 8.0):
        """Wait for the page to stop loading, as far as can be told, so the next read is of
        the page the step led to."""
        end = time.time() + timeout
        await asyncio.sleep(0.25)
        while time.time() < end:
            with contextlib.suppress(Exception):
                if await self._eval("document.readyState") == "complete":
                    break
            await asyncio.sleep(0.25)
        await asyncio.sleep(0.3)

    def page_ok(self) -> str:
        url = self.tab().get("url", "")
        if url in ("", "about:blank"):
            return ""
        return allowed(url) and "this tab is not showing a web page, so the browser tools will not read it"

    async def read(self) -> dict:
        bad = self.page_ok()
        if bad:
            raise CDPError(bad)
        return await self._eval(SNAPSHOT_JS % {"max": ELEMENTS_MAX}) or {}

    async def point(self, ref=None, text: str = "") -> dict | None:
        if ref not in (None, ""):
            return await self._eval(f"({BOX_JS})({json.dumps(str(ref))})")
        if text:
            return await self._eval(f"({FIND_JS})({json.dumps(str(text))})")
        return None

    async def agent_click(self, ref=None, text: str = "", who: str = "agent") -> dict:
        s = self.tab().get("session")
        box = await self.point(ref, text)
        if not box:
            raise CDPError("nothing on the page matches that; call browser_read for the current refs")
        x, y = float(box["x"]), float(box["y"])
        await self._tell({"type": "agent", "kind": "click", "x": x, "y": y, "label": box.get("name", ""), "who": who})
        for ev in ("mouseMoved", "mousePressed", "mouseReleased"):
            await self.cdp.send("Input.dispatchMouseEvent",
                                {"type": ev, "x": x, "y": y, "button": "none" if ev == "mouseMoved" else "left",
                                 "clickCount": 0 if ev == "mouseMoved" else 1}, s)
        return box

    async def agent_type(self, text: str, ref=None, submit: bool = False, who: str = "agent") -> dict | None:
        s = self.tab().get("session")
        box = None
        if ref not in (None, ""):
            box = await self.agent_click(ref=ref, who=who)
            # replace what was there, as a person selecting the field's text would
            await self._eval(f"(r => {{ const e = document.querySelector('[data-bento-ref=\"' + r + '\"]');"
                             f" if (e && 'select' in e) e.select(); }})({json.dumps(str(ref))})")
        await self._tell({"type": "agent", "kind": "type", "text": text[:40], "who": who,
                          "x": box["x"] if box else None, "y": box["y"] if box else None})
        if text:
            await self.cdp.send("Input.insertText", {"text": text}, s)
        if submit:
            await self._key(s, "Enter")
        return box

    async def agent_key(self, key: str, who: str = "agent"):
        await self._tell({"type": "agent", "kind": "key", "text": key, "who": who})
        await self._key(self.tab().get("session"), key)

    async def screenshot(self) -> bytes:
        bad = self.page_ok()
        if bad:
            raise CDPError(bad)
        r = await self.cdp.send("Page.captureScreenshot", {"format": "png"}, self.tab().get("session"))
        return base64.b64decode(r.get("data") or "")

    async def need_person(self, wall: dict, reason: str = ""):
        """The window pulses and the person is told; the agent waits in wait_for_person."""
        self.attention = {"kind": wall.get("kind") or "ask", "why": wall.get("why") or "",
                          "reason": str(reason or "")[:300], "url": self.tab().get("url", ""),
                          "site": site_of(self.tab().get("url", "")), "since": time.time()}
        self.resumed.clear()
        await self._state()
        if _ATTENTION[0]:
            with contextlib.suppress(Exception):
                await _ATTENTION[0](self.uid, dict(self.attention))


# ---- the registry ----------------------------------------------------------------------

_BROWSERS: dict[str, Browser] = {}


def current(uid: str) -> Browser | None:
    b = _BROWSERS.get(uid or "")
    return b if b and b.running else None


async def get(uid: str, cfg: dict, home: Path) -> Browser:
    """This person's browser, started if it is not running."""
    b = _BROWSERS.get(uid or "")
    if b is None:
        b = _BROWSERS[uid or ""] = Browser(uid, cfg, home)
    b.cfg = cfg
    async with b._lock:
        if not b.running:
            await b.start()
    return b


async def stop_all():
    for b in list(_BROWSERS.values()):
        with contextlib.suppress(Exception):
            await b.stop()
    _BROWSERS.clear()


def site_now(uid: str) -> str:
    """The site this person's browser is showing, for the gate (cheap: kept from CDP events)."""
    b = _BROWSERS.get(uid or "")
    return site_of(b.tab().get("url", "")) if b and b.running else ""


# ---- the agent's tools, as words ----------------------------------------------------------

def _page_words(snap: dict, wall_note: bool = True) -> str:
    lines = [f"page: {snap.get('title') or '(untitled)'} — {snap.get('url', '')}"]
    els = snap.get("elements") or []
    if els:
        lines.append("things you can click or fill (use the number as ref):")
        for e in els:
            kind = e["tag"] + (f"[{e['type']}]" if e.get("type") else "") + (f" role={e['role']}" if e.get("role") else "")
            val = f" = {e['value']!r}" if e.get("value") else ""
            lines.append(f"  [{e['ref']}] {kind} {e.get('name') or ''}{val}".rstrip())
        if snap.get("more"):
            lines.append(f"  … and {snap['more']} more below; scroll and read again to see them")
    lines.append("text on the page:")
    lines.append((snap.get("text") or "").strip()[:TEXT_MAX] or "(no text)")
    w = snap.get("wall")
    if w and wall_note:
        lines.append(f"[needs you] This page is asking for {w['why']}. You cannot do that part: call "
                     f"browser_wait_for_person and say what the person should do in the browser window. "
                     f"When they are done you carry on in the same signed-in session.")
    return "\n".join(lines)


async def _hit_wall(b: Browser, snap: dict):
    w = snap.get("wall")
    if w and not b.attention:
        await b.need_person(w, "")


async def tool_open(b: Browser, url: str, new_tab: bool = False) -> str:
    url = normalise(url)
    bad = allowed(url)
    if bad:
        return f"[refused] {bad}"
    b.touch()
    if new_tab:
        await b.new_tab(url)
    else:
        await b.cdp.send("Page.navigate", {"url": url}, b.tab().get("session"))
    await b.settle()
    snap = await b.read()
    await _hit_wall(b, snap)
    return _page_words(snap)


async def tool_read(b: Browser) -> str:
    b.touch()
    snap = await b.read()
    await _hit_wall(b, snap)
    return _page_words(snap)


async def tool_click(b: Browser, ref=None, text: str = "", who: str = "agent") -> str:
    b.touch()
    box = await b.agent_click(ref=ref, text=text, who=who)
    await b.settle()
    snap = await b.read()
    await _hit_wall(b, snap)
    return f"clicked “{box.get('name', '')}”.\n" + _page_words(snap)


async def tool_type(b: Browser, text: str, ref=None, submit: bool = False, who: str = "agent") -> str:
    b.touch()
    box = await b.agent_type(str(text or ""), ref=ref, submit=submit, who=who)
    if submit:
        await b.settle()
    snap = await b.read()
    await _hit_wall(b, snap)
    where = f" into “{box.get('name', '')}”" if box else ""
    return f"typed {len(str(text or ''))} characters{where}{' and pressed Enter' if submit else ''}.\n" + \
        _page_words(snap)


async def tool_scroll(b: Browser, direction: str = "down") -> str:
    b.touch()
    dy = {"down": 600, "up": -600, "top": -10 ** 6, "bottom": 10 ** 6}.get(str(direction), 600)
    await b._eval(f"window.scrollBy(0, {dy})")
    await asyncio.sleep(0.4)
    return _page_words(await b.read())


async def tool_wait(b: Browser, reason: str, timeout: int = WAIT_S) -> str:
    """Hand the window to the person and wait for "Done", or for the wall to go away."""
    if not _PRESENCE[0](b.uid):
        return ("[nobody here] Nobody has this desktop open, so nobody can do that part now. "
                "Stop here and tell the person, in your answer, what the browser needs them to do.")
    snap = {}
    with contextlib.suppress(Exception):
        snap = await b.read()
    await b.need_person(snap.get("wall") or {"kind": "ask", "why": "a person"}, reason)
    timeout = max(10, min(WAIT_MAX_S, int(timeout or WAIT_S)))
    had_wall = bool(snap.get("wall"))
    end = time.time() + timeout
    while True:
        if time.time() >= end:
            b.attention = None
            await b._state()
            return (f"[timeout] Nobody finished that in {max(1, timeout // 60)} minute(s). "
                    f"Tell the person what is still needed.")
        try:
            await asyncio.wait_for(b.resumed.wait(), 2.0)
            break                                   # they pressed "Done, carry on"
        except asyncio.TimeoutError:
            pass
        if had_wall:
            # or the wall went away on its own: they signed in and the page moved on
            with contextlib.suppress(Exception):
                if not (await b.read()).get("wall"):
                    break
    b.attention = None
    b.resumed.clear()
    await b._state()
    b.touch()
    await b.settle(4)
    snap = await b.read()
    return "[carry on] The person is done. You are in the same session.\n" + _page_words(snap, wall_note=True)


async def tool_tabs(b: Browser) -> str:
    st = b.snapshot_state()
    return "\n".join(f"{'*' if t['active'] else ' '} {t['title']} — {t['url']}" for t in st["tabs"]) or "(no tabs)"
