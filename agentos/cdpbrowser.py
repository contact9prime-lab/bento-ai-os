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
  sees another's cookies. On a machine with accounts the profile is SEALED at rest
  (`profile.sealed`, seal.py): it opens into a 0700 folder in RAM (`/dev/shm`) only when the
  person's signed-in browser lends the key, is put away again with the account's public key
  every few minutes and when the browser stops, and the folder in RAM is removed. Chromium's
  own cookie "encryption" uses a public key on Linux, so this is what actually protects it. The process itself stops after `IDLE_S` with nobody watching
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
import re
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
# How long a starting browser has to answer. A first start is slow on a cold machine (a
# Pi's first boot, a fresh CI runner builds its font cache): at 20 s it failed with an
# empty "()" for a browser that was still on its way.
START_WAIT = 60

# Wired by the server: who gets told when the browser needs a person, and whether anyone
# is at a screen to be told. Unwired, nobody is (a test, a terminal).
_ATTENTION = [None]          # async (uid, payload) -> None
_PRESENCE = [lambda uid: False]
# The account's own phone chats (its Telegram and WhatsApp owner), as (key, ask, say): where a
# wall goes when nobody is at a screen and no phone turn is running. That is a mission on its
# schedule meeting a lapsed sign-in, reported as needing "the link to login in Telegram".
_OWNER_PHONES = [lambda uid: []]


def bind(attention=None, presence=None, owner_phones=None):
    if attention is not None:
        _ATTENTION[0] = attention
    if presence is not None:
        _PRESENCE[0] = presence
    if owner_phones is not None:
        _OWNER_PHONES[0] = owner_phones


# A phone the person is talking from right now (a Telegram or WhatsApp turn), per account.
# Asked for as "every AI agent dies at the login screen; mine texts me": a wall met during a
# phone turn with no screen open used to end the turn with "[nobody here]". A channel's turn
# registers here while it runs (`reach`), and the wall is asked of that phone instead: a
# picture of the page, what it wants, and a code typed in the chat goes into the page
# (`from_phone`) without ever being saved in the conversation.
_REACH: dict[str, dict] = {}
CODE_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9 -]{2,14}[A-Za-z0-9])\s*$")
DONE_WORDS = {"done", "carry on", "continue", "ok", "okay", "signed in", "go on"}


_SAY: dict[tuple, object] = {}       # (uid, chat) -> how to send that chat a line with buttons


def reach(uid: str, key: str, ask, say=None) -> None:
    """While a phone turn runs, a wall is asked of that phone. `ask(attention, png)` sends
    the picture and the question; `key` names the chat (`unreach` takes it out).
    `say(text, buttons)` sends a line with buttons under it: what the sign-in link says
    (handoff.py) goes through it."""
    _REACH.setdefault(uid or "", {})[key] = ask
    if say is not None:
        _SAY[(uid or "", key)] = say


def unreach(uid: str, key: str) -> None:
    got = _REACH.get(uid or "") or {}
    got.pop(key, None)
    _SAY.pop((uid or "", key), None)
    if not got:
        _REACH.pop(uid or "", None)


def phone_waiting(uid: str, key: str) -> dict | None:
    """The wall this chat is being asked about, if the browser is waiting on it."""
    b = _BROWSERS.get(uid or "")
    if not b or not b.running or not b.attention or key not in (_REACH.get(uid or "") or {}):
        return None
    return dict(b.attention)


def phone_offer(att: dict) -> dict:
    """Can this wall be opened on the phone itself (handoff.py)? A code is typed in the chat,
    so it needs no page; anything else may be offered where the machine allows it."""
    if (att.get("kind") or "ask") == "code":
        return {"ok": False}
    from . import handoff
    return handoff.can_offer(handoff.cfg())


def reply_of(said: str) -> str:
    """What a channel sends for `from_phone`'s answer: nothing when the chat was already told
    (a sign-in link is never repeated through a sender that keeps a diary), else the words."""
    from . import handoff
    if not said or said == handoff.HANDLED:
        return ""
    return said if not said[:1].isalnum() else "✓ " + said


def phone_words(att: dict, agent: str = "Bento", button: bool = True, offer: dict | None = None) -> str:
    """What the phone is told about a wall: who needs what, on which site, and the one thing
    to do. One function for every channel, so Telegram and WhatsApp say the same thing.
    `button` is False where the message carries no buttons: the person replies "done" or
    "open". `offer` is `phone_offer`'s answer: when it is ok the page can be opened on this
    phone through remote access, and the sentence says so before anybody taps. When all that
    is missing is remote access, the message says that too."""
    site = att.get("site") or "a page"
    tap = "tap Done" if button else "reply “done”"
    kind = att.get("kind") or "ask"
    head = f"🔐 {agent} needs you on {site}."
    here = ""
    if offer and offer.get("ok"):
        here = (("Tap “Open on this phone”" if button else "Reply “open”")
                + " to do it here: you sign in to your Bento's remote access, then the page opens")
    if kind == "code":
        do = "Reply here with the code and I'll type it into the page."
    elif kind == "login":
        do = ((f"It wants your password. {here}. Or sign in" if here else "It wants your password. Sign in")
              + f" on a screen in the Web window, then {tap}. Passwords don't go through chat.")
    elif kind == "captcha":
        do = ((f"It wants to check you're a person. {here}. Or do that" if here
               else "It wants to check you're a person. Do that")
              + f" on a screen in the Web window, then {tap}.")
    else:
        do = (f"{here}. Or do it" if here else "Do it") + f" on a screen in the Web window, then {tap}."
    if kind != "code" and offer and offer.get("needs") == "remote":
        do += " To do it from this phone, remote access has to be on first."
    said = str(att.get("reason") or "").strip()
    return head + ("\n“" + said[:300] + "”" if said else "") + "\n" + do


async def from_phone(uid: str, key: str, text: str) -> str:
    """A message from the phone while the browser waits on a wall. Returns what to tell the
    phone, or '' when the message is not an answer to the wall (it goes to the agent).

    "open" asks for the page on this phone and "close" closes that link (handoff.py). Those
    answers come back as `handoff.HANDLED`: the chat was told through its own sender, and
    `reply_of` gives a channel what is left to send.

    A code page takes the code: it is typed into the code field and submitted by the person,
    not by the agent, and it is never written to the conversation. "done" carries on, as the
    window's button does. A password is never taken from a chat: chat history keeps it."""
    att = phone_waiting(uid, key)
    if not att:
        return ""
    b = _BROWSERS[uid or ""]
    words = str(text or "").strip()
    if words.lower().rstrip(".!") in DONE_WORDS:
        await b.person({"type": "resume"})
        return "Carrying on."
    from . import handoff
    if handoff.cfg() is not None:
        said = await handoff.from_chat(handoff.cfg(), uid or "", key, words, _SAY.get((uid or "", key)))
        if said:
            return said
    if att.get("kind") == "code" and CODE_RE.match(words) and sum(c.isdigit() for c in words) >= 4:
        ok = await b.person_code(words.replace(" ", ""))
        if not ok:
            return "I couldn't find where the code goes on that page. Open the Web window on a screen."
        return f"Typed into {att.get('site') or 'the page'}. Carrying on."
    return ""


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

def quiet_prefs(prof: Path) -> None:
    """Switch off Chromium's own password and autofill pop-ups in the shared profile.

    Found by the sign-in link's live run, with a phone-sized window: as soon as a password
    was typed, the picture became the whole 1280-wide browser window squeezed into the
    view (frames of 390x201 for a 390x735 page). The pop-up Chromium opens over a password
    field is a surface of its own, and the screencast then covers the window instead of the
    page. A pop-up can't be drawn or tapped through a screencast anyway, and an agent's
    shared browser shouldn't be collecting passwords: sign-ins persist as cookies.

    The profile's other settings are kept; this runs before every start, while no Chromium
    has the file open."""
    p = prof / "Default" / "Preferences"
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        if not isinstance(d, dict):
            d = {}
    except (OSError, ValueError):
        d = {}
    d["credentials_enable_service"] = False
    d.setdefault("profile", {})["password_manager_enabled"] = False
    for k in ("profile_enabled", "credit_card_enabled"):
        d.setdefault("autofill", {})[k] = False
    with contextlib.suppress(OSError):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d), encoding="utf-8")


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
        # what the model was last shown (ref -> its label, tag, type, role) and the field it
        # last typed into: the gate reads a click's target from THESE, never from the model
        self.seen: dict[str, dict] = {}
        self.typed_ref = ""
        self._watch = None
        self.run_dir: Path | None = None       # a sealed profile, opened in RAM while running
        self.sealed_at = 0.0

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
        prof = await self._open_profile()
        quiet_prefs(prof)
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
            ver = await self.cdp.send("Browser.getVersion", timeout=START_WAIT)
        except Exception as e:
            await self.stop()
            why = str(e) or (f"no answer in {START_WAIT} s" if isinstance(e, asyncio.TimeoutError)
                             else type(e).__name__)
            raise CDPError(f"the browser did not start ({why})") from None
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
        await asyncio.to_thread(self._close_profile)
        await self._state()

    async def _idle(self):
        while self.running:
            await asyncio.sleep(30)
            if self.run_dir and time.time() - self.sealed_at > RESEAL_S:
                # a crash must not lose more than a few minutes of sign-ins
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(self._seal_profile)
            if not self.viewers and time.time() - self.last_use > IDLE_S and not self.attention:
                await self.stop()
                return

    def touch(self):
        self.last_use = time.time()

    # -- the profile, sealed at rest on a machine with accounts --
    def _sealed(self) -> bool:
        from . import seal
        return bool(self.uid) and seal.exists(self.uid)

    async def _open_profile(self) -> Path:
        base = self.home / "browser"
        base.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(base, 0o700)
        plain = base / "profile"
        if not self._sealed():
            plain.mkdir(parents=True, exist_ok=True)
            return plain
        from . import seal
        # the server's pid in the name: a sweep removes only folders whose server is gone
        run = Path(_tempfile().mkdtemp(prefix=f"bento-browser-{os.getpid()}-{self.uid}-", dir=_ram_dir()))
        os.chmod(run, 0o700)
        box = base / SEALED_PROFILE
        try:
            if box.exists():
                try:
                    priv = await seal.borrow(self.uid, "open your signed-in browser")
                except seal.Sealed as e:
                    raise CDPError(str(e)) from None
                try:
                    data = seal.open_bytes(self.uid, priv, json.loads(box.read_text()), "browser")
                finally:
                    priv = None
                await asyncio.to_thread(_untar, data, run)
            elif plain.exists():
                # the first start after the update: the old clear profile moves in and is sealed
                await asyncio.to_thread(shutil.copytree, plain, run, dirs_exist_ok=True)
        except BaseException:
            shutil.rmtree(run, ignore_errors=True)
            raise
        self.run_dir = run
        if plain.exists():
            await asyncio.to_thread(self._seal_profile)
            shutil.rmtree(plain, ignore_errors=True)
        return run

    def _seal_profile(self) -> None:
        """Put the profile in RAM away under the account's PUBLIC key: needs nothing secret."""
        if not self.run_dir or not self.run_dir.exists():
            return
        from . import seal
        box = seal.seal_bytes(self.uid, _tar(self.run_dir), "browser")
        dest = self.home / "browser" / SEALED_PROFILE
        tmp = dest.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(box, f)
        os.replace(tmp, dest)
        self.sealed_at = time.time()

    def _close_profile(self) -> None:
        if not self.run_dir:
            return
        try:
            self._seal_profile()
        finally:
            shutil.rmtree(self.run_dir, ignore_errors=True)
            self.run_dir = None

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
                "attention": self.attention, "handoff": self._handoff()}

    def _handoff(self) -> dict | None:
        """The sign-in link this page is open through on a phone, if any (handoff.py)."""
        from . import handoff
        return handoff.view(handoff.for_user(self.uid))

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
        elif k == "handoff_close":
            # the desk closes the page that is open on a phone
            from . import handoff
            await handoff.close(self.uid, "closed by you")
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
        snap = await self._eval(SNAPSHOT_JS % {"max": ELEMENTS_MAX}) or {}
        self.seen = {str(e.get("ref")): {k: e.get(k) or "" for k in ("name", "tag", "type", "role")}
                     for e in (snap.get("elements") or []) if isinstance(e, dict)}
        return snap

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
            self.typed_ref = str(ref)
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

    async def person_code(self, code: str) -> bool:
        """A code the person sent from their phone, typed into the page's code field and
        submitted. The window shows that a code went in, never the code itself."""
        s = self.tab().get("session")
        if not s:
            return False
        ref = await self._eval(r"""(() => {
          const vis = e => { const r = e.getBoundingClientRect(); return r.width > 2 && r.height > 2; };
          const ins = [...document.querySelectorAll('input')].filter(i => vis(i) && !/hidden|password|checkbox|radio|submit|button/i.test(i.type));
          const hit = ins.find(i => i.autocomplete === 'one-time-code')
            || ins.find(i => /otp|2fa|totp|mfa|verification|one.?time|passcode|code/i.test((i.name||'') + ' ' + (i.id||'') + ' ' + (i.placeholder||'') + ' ' + (i.getAttribute('aria-label')||'')))
            || (ins.length === 1 ? ins[0] : null);
          if (!hit) return '';
          hit.setAttribute('data-bento-code', '1'); hit.focus();
          if ('select' in hit) hit.select();
          return '1';
        })()""")
        if not ref:
            return False
        await self._tell({"type": "agent", "kind": "type", "text": "a code from your phone", "who": "phone"})
        await self.cdp.send("Input.insertText", {"text": code}, s)
        await self._key(s, "Enter")
        self.touch()
        return True

    async def agent_upload(self, path: str, ref=None, who: str = "agent") -> str:
        """Give a file to the page's file field: the one under `ref`, or the page's first.
        Returns the field's label. The path was checked by the caller (tools.browser_upload)."""
        s = self.tab().get("session")
        pick = ("(r => { let e = r ? document.querySelector('[data-bento-ref=\"' + r + '\"]') : null;"
                " if (e && !(e.tagName === 'INPUT' && e.type === 'file'))"
                "   e = e.querySelector('input[type=file]') || (e.closest('form') || document).querySelector('input[type=file]');"
                " return e || document.querySelector('input[type=file]'); })"
                f"({json.dumps(str(ref)) if ref not in (None, '') else 'null'})")
        r = await self.cdp.send("Runtime.evaluate", {"expression": pick, "returnByValue": False}, s)
        oid = ((r or {}).get("result") or {}).get("objectId")
        if not oid:
            raise CDPError("this page has no file field to give a file to")
        await self._tell({"type": "agent", "kind": "type", "text": "a file: " + os.path.basename(path), "who": who})
        await self.cdp.send("DOM.setFileInputFiles", {"files": [str(path)], "objectId": oid}, s)
        return os.path.basename(path)

    async def agent_key(self, key: str, who: str = "agent"):
        await self._tell({"type": "agent", "kind": "key", "text": key, "who": who})
        await self._key(self.tab().get("session"), key)

    async def screenshot(self) -> bytes:
        bad = self.page_ok()
        if bad:
            raise CDPError(bad)
        r = await self.cdp.send("Page.captureScreenshot", {"format": "png"}, self.tab().get("session"))
        return base64.b64decode(r.get("data") or "")

    async def phone_shot(self) -> bytes:
        """The page as a phone should see it: cropped to what is on it, at twice the size. A
        whole 1280x800 frame of a sign-in form is mostly margin, and on a phone the code box
        was a thin strip (found in the live run). Falls back to the whole frame."""
        box = None
        with contextlib.suppress(Exception):
            box = await self._eval(r"""(() => {
              // the words themselves (a paragraph's box is as wide as the page) and the controls
              let x0 = 1e9, y0 = 1e9, x1 = 0, y1 = 0;
              const add = r => {
                if (r.width < 2 || r.height < 2 || r.bottom < 0 || r.top > innerHeight) return;
                x0 = Math.min(x0, r.left); y0 = Math.min(y0, r.top);
                x1 = Math.max(x1, r.right); y1 = Math.max(y1, Math.min(r.bottom, innerHeight));
              };
              const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
              for (let n = tw.nextNode(); n; n = tw.nextNode()) {
                if (!n.textContent.trim()) continue;
                const rg = document.createRange(); rg.selectNodeContents(n); add(rg.getBoundingClientRect());
              }
              document.body.querySelectorAll('input:not([type=hidden]),button,select,textarea,img,svg').forEach(e => add(e.getBoundingClientRect()));
              if (x1 <= x0 || y1 <= y0) return null;
              const pad = 24;
              return {x: Math.max(0, x0 - pad), y: Math.max(0, y0 - pad),
                      w: Math.min(innerWidth, x1 + pad) - Math.max(0, x0 - pad),
                      h: Math.min(innerHeight, y1 + pad) - Math.max(0, y0 - pad)};
            })()""")
        if not box or box.get("w", 0) < 120 or box.get("h", 0) < 60:
            return await self.screenshot()
        # never narrower than a phone's picture is wide, so a short form is not blown up
        w = max(float(box["w"]), 360.0)
        r = await self.cdp.send("Page.captureScreenshot", {
            "format": "png", "clip": {"x": float(box["x"]), "y": float(box["y"]), "width": w,
                                      "height": float(box["h"]), "scale": 2}}, self.tab().get("session"))
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


# ---- what can't be taken back ------------------------------------------------------------
# Asked for as "login to my Instagram and manage my content, and it can build a mission on it",
# then "think of the use cases around it": posting, replying, sending, submitting a form,
# paying, deleting, on any site the person is signed in to. Those are a different consent from
# clicking around, so the gate decides them as `browser.commit site:<host>`, and a mission says
# whether its roster may do them on its own or asks each time (flows `permissions.sites`).
#
# What counts is read from the PAGE: the label of the element the model was shown under that
# ref, or the field it typed into before pressing Enter. The model's own description of what it
# is clicking counts for nothing. English labels only, said in the docs; a label nobody listed
# is an ordinary click, so this is a floor under the person's consent, not a fence round it.
COMMIT_WORDS = (
    "post", "publish", "share", "send", "submit", "tweet", "repost", "retweet", "reply",
    "comment", "pay", "buy", "purchase", "order", "checkout", "check out", "confirm", "book",
    "reserve", "delete", "remove", "unfollow", "follow", "connect", "invite", "apply", "sign",
    "transfer", "withdraw", "accept", "decline", "upload", "schedule", "approve", "donate",
    "subscribe", "unsubscribe", "place order", "go live", "message")
_COMMIT_RE = re.compile(r"(?<![\w-])(" + "|".join(re.escape(w) for w in COMMIT_WORDS) + r")(?![\w-])", re.I)
_PRESSABLE = ("button", "a", "summary")
_SEARCHY = re.compile(r"search|find|filter|query|look ?up", re.I)


def _commit_label(e: dict) -> str:
    """A pressable element whose own label is a commit word: its label, else ''."""
    name = " ".join(str(e.get("name") or "").split())
    if not name or len(name) > 40:
        return ""
    tag, typ, role = (str(e.get(k) or "").lower() for k in ("tag", "type", "role"))
    pressable = (tag in _PRESSABLE or role in ("button", "menuitem", "link")
                 or (tag == "input" and typ in ("submit", "button", "image")))
    return name if pressable and _COMMIT_RE.search(name) else ""


def _searchy(e: dict | None) -> bool:
    if not e:
        return False
    return (str(e.get("type") or "").lower() == "search" or str(e.get("role") or "").lower()
            in ("searchbox", "combobox") or bool(_SEARCHY.search(str(e.get("name") or ""))))


def commit_of(uid: str, tool: str, args: dict) -> str:
    """'' for an ordinary step, else what makes it one that can't be taken back, in words
    (the label as the page shows it). Read from what this person's browser last showed."""
    b = _BROWSERS.get(uid or "")
    seen = dict(b.seen) if b else {}
    if tool == "browser_click":
        ref = args.get("ref")
        if ref not in (None, ""):
            got = _commit_label(seen.get(str(ref)) or {})
            return f"“{got}”" if got else ""
        text = " ".join(str(args.get("text") or "").split())[:60]
        if not text:
            return ""
        # a click by words lands on the first element whose label matches them (FIND_JS):
        # judge every element that could be it, and the words themselves
        for e in seen.values():
            if text.lower() in str(e.get("name") or "").lower() and _commit_label(e):
                return f"“{_commit_label(e)}”"
        return f"“{text}”" if _COMMIT_RE.search(text) and len(text) <= 40 else ""
    if tool == "browser_type" and args.get("submit"):
        ref = args.get("ref")
        target = seen.get(str(ref)) if ref not in (None, "") else seen.get(b.typed_ref if b else "")
        return "" if _searchy(target) else "pressing Enter to send what was typed"
    if tool == "browser_key" and "enter" in str(args.get("key") or "").lower():
        return "" if _searchy(seen.get(b.typed_ref) if b else None) else "pressing Enter, which may send or submit"
    return ""


# ---- sites this person is signed in to ---------------------------------------------------
# The sign-in itself is the person's, in the shared browser (the Web window, or the phone
# through the sign-in link). The cookies are what keep it, in this account's own profile.
# This list only says which sites have been signed in to and when, so a mission can say
# "ready" or "sign in first" before it runs, and the person can make the browser forget one.
SITES_FILE = "sites.json"

# Sites whose own terms forbid automating their website. Said wherever a mission declares
# one, in one sentence: the person decides knowing it, and the official API is the safer
# road where there is one (Graph API for Instagram, on the list to build).
STRICT_SITES = {
    "instagram.com": "Instagram doesn't allow automating its website, and an account driven by a bot can be "
                     "flagged or locked. Meta's Graph API is the official road for business accounts.",
    "facebook.com": "Facebook doesn't allow automating its website, and an account can be flagged or locked.",
    "linkedin.com": "LinkedIn doesn't allow automating its website, and an account can be restricted.",
    "x.com": "X doesn't allow automating its website outside its API, and an account can be locked.",
    "twitter.com": "X doesn't allow automating its website outside its API, and an account can be locked.",
    "tiktok.com": "TikTok doesn't allow automating its website, and an account can be banned.",
    "threads.net": "Threads doesn't allow automating its website, and an account can be flagged.",
    "amazon.com": "Amazon doesn't allow automating its website, and an account can be closed.",
}


def strict_words(site: str) -> str:
    site = site_of("https://" + str(site or "").split("://")[-1])
    for host, words in STRICT_SITES.items():
        if site == host or site.endswith("." + host):
            return words
    return ""


def _sites_path(home: Path) -> Path:
    return Path(home) / "browser" / SITES_FILE


def signed_in(home: Path) -> list[dict]:
    """The sites signed in to here, newest first: {site, since, last, how}."""
    try:
        d = json.loads(_sites_path(home).read_text())
    except (OSError, ValueError):
        return []
    rows = [{"site": k, **v} for k, v in (d if isinstance(d, dict) else {}).items()
            if isinstance(v, dict) and site_of("https://" + k) == k]
    return sorted(rows, key=lambda r: -float(r.get("last") or 0))


def note_signed_in(home: Path, site: str, how: str) -> None:
    site = site_of("https://" + str(site or "").split("://")[-1])
    if not site or "." not in site:
        return
    p = _sites_path(home)
    try:
        d = json.loads(p.read_text())
        d = d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        d = {}
    now = time.time()
    row = d.get(site) if isinstance(d.get(site), dict) else {}
    d[site] = {"since": row.get("since") or now, "last": now, "how": str(how or "")[:120]}
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def is_signed_in(home: Path, site: str) -> bool:
    site = site_of("https://" + str(site or "").split("://")[-1])
    return any(r["site"] == site or site.endswith("." + r["site"]) for r in signed_in(home))


async def forget_site(uid: str, cfg: dict, home: Path, site: str) -> str:
    """Sign this browser out of a site: its cookies and storage go, and so does the record."""
    site = site_of("https://" + str(site or "").split("://")[-1])
    if not site or "." not in site:
        return "say which site, like instagram.com"
    b = await get(uid, cfg, home)
    origins = [f"https://{site}", f"https://www.{site}", f"http://{site}"]
    with contextlib.suppress(Exception):
        got = await b.cdp.send("Storage.getCookies", {})
        for c in (got or {}).get("cookies") or []:
            dom = str(c.get("domain") or "").lstrip(".")
            if dom == site or dom.endswith("." + site):
                await b.cdp.send("Network.deleteCookies", {"name": c["name"], "domain": c["domain"],
                                                           "path": c.get("path") or "/"}, b.tab().get("session"))
    for o in origins:
        with contextlib.suppress(Exception):
            await b.cdp.send("Storage.clearDataForOrigin", {"origin": o, "storageTypes": "all"})
    p = _sites_path(home)
    with contextlib.suppress(OSError, ValueError):
        d = json.loads(p.read_text())
        if isinstance(d, dict) and d.pop(site, None) is not None:
            p.write_text(json.dumps(d, indent=1))
    return f"signed out of {site} in the shared browser"


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


SEALED_PROFILE = "profile.sealed"
RESEAL_S = 5 * 60
# Chromium rebuilds these, and they are most of a profile's size: never sealed.
_NO_SEAL = {"Cache", "Code Cache", "GPUCache", "GrShaderCache", "ShaderCache", "GraphiteDawnCache",
            "DawnGraphiteCache", "DawnWebGPUCache", "component_crx_cache", "Crashpad", "Crash Reports",
            "BrowserMetrics", "optimization_guide_model_store", "Safe Browsing", "CacheStorage",
            "ScriptCache", "SingletonLock", "SingletonSocket", "SingletonCookie"}


def _tempfile():
    import tempfile
    return tempfile


def _ram_dir() -> str:
    """Where an opened profile lives while it runs: RAM when this machine has a tmpfs for it."""
    d = "/dev/shm"
    return d if os.path.isdir(d) and os.access(d, os.W_OK) else _tempfile().gettempdir()


def _tar(root: Path) -> bytes:
    import io
    import tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as t:
        def keep(ti):
            parts = Path(ti.name).parts
            if any(p in _NO_SEAL for p in parts) or ti.issym() or ti.islnk():
                return None
            return ti
        t.add(str(root), arcname=".", filter=keep)
    return buf.getvalue()


def _untar(data: bytes, dest: Path) -> None:
    import io
    import tarfile
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
        for m in t.getmembers():
            p = Path(m.name)
            if p.is_absolute() or ".." in p.parts or not (m.isfile() or m.isdir()):
                continue
            t.extract(m, dest, filter="data") if sys.version_info >= (3, 12) else t.extract(m, dest)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def sweep_runs() -> int:
    """At start: an opened profile left in RAM by a server that died is removed (it was sealed
    at most RESEAL_S before). Only folders this user owns whose server is no longer running:
    another server on this machine (a demo, a test) may have one open right now."""
    n = 0
    base = Path(_ram_dir())
    for d in base.glob("bento-browser-*"):
        with contextlib.suppress(OSError, ValueError):
            pid = int(d.name.split("-")[2])
            if d.is_dir() and d.stat().st_uid == os.getuid() and pid != os.getpid() and not _alive(pid):
                shutil.rmtree(d, ignore_errors=True)
                n += 1
    return n


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
    phones = dict(_REACH.get(b.uid or "") or {})
    lent = []
    if not _PRESENCE[0](b.uid) and not phones:
        # nobody at a screen and no phone turn: the account's own phone chats, for this wait
        with contextlib.suppress(Exception):
            for key, ask, say in (_OWNER_PHONES[0](b.uid) or []):
                if key not in (_REACH.get(b.uid or "") or {}):
                    reach(b.uid, key, ask, say)
                    lent.append(key)
        phones = dict(_REACH.get(b.uid or "") or {})
    if not _PRESENCE[0](b.uid) and not phones:
        return ("[nobody here] Nobody has this desktop open and no phone chat is set up, so nobody can "
                "do that part now. Stop here and tell the person, in your answer, what the browser needs "
                "them to do (in a mission, file it in the Brief as needs_you).")
    try:
        return await _wait_for_person(b, reason, timeout, phones)
    finally:
        for key in lent:
            unreach(b.uid, key)


async def _wait_for_person(b: Browser, reason: str, timeout: int, phones: dict) -> str:
    snap = {}
    with contextlib.suppress(Exception):
        snap = await b.read()
    await b.need_person(snap.get("wall") or {"kind": "ask", "why": "a person"}, reason)
    if phones:
        # the person is on their phone: show them the page and ask there
        png = b""
        with contextlib.suppress(Exception):
            png = await b.phone_shot()
        for ask in phones.values():
            with contextlib.suppress(Exception):
                await ask(dict(b.attention or {}), png)
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
    if had_wall and not snap.get("wall"):
        # a person got past a sign-in here: the browser keeps it, and the list says so
        with contextlib.suppress(Exception):
            note_signed_in(b.home, site_of(snap.get("url", "")), "signed in by you")
    return "[carry on] The person is done. You are in the same session.\n" + _page_words(snap, wall_note=True)


_SIGN_IN_LINK = re.compile(r"^\s*(log ?in|sign ?in|login|signin)\b", re.I)


async def tool_sign_in(b: Browser, site: str, home: Path) -> str:
    """The person signs in to `site`; the page is already open. Finds the sign-in form (one
    click on the page's own "Log in" link when the front page has none), hands it to the
    person, and records the site once the form has gone."""
    b.touch()
    warn = strict_words(site)
    tail = f"\nNote: {warn}" if warn else ""
    snap = await b.read()
    if not snap.get("wall"):
        link = next((e for e in (snap.get("elements") or [])
                     if _SIGN_IN_LINK.match(str(e.get("name") or ""))), None)
        if link:
            with contextlib.suppress(Exception):
                await b.agent_click(ref=link.get("ref"), who="sign-in")
                await b.settle(6)
                snap = await b.read()
    if not snap.get("wall"):
        if any(_SIGN_IN_LINK.match(str(e.get("name") or "")) for e in (snap.get("elements") or [])):
            return (f"{site} shows a sign-in link but no form I can hand over. Ask the person to sign in "
                    f"in the Web window, then call browser_sites." + tail)
        note_signed_in(home, site, "already signed in")
        return f"{site} shows no sign-in form, so the browser is already signed in there. It's ready." + tail
    said = await tool_wait(b, f"Sign in to {site}, so I can use it for you", WAIT_S)
    if said.startswith("[carry on]"):
        now = await b.read()
        if now.get("wall"):
            return f"{site} still shows a sign-in. Nothing was recorded.\n" + _page_words(now) + tail
        note_signed_in(home, site, "signed in by you")
        return f"Signed in to {site}. The browser keeps it, and missions can use it now." + tail
    return said + tail


async def tool_tabs(b: Browser) -> str:
    st = b.snapshot_state()
    return "\n".join(f"{'*' if t['active'] else ' '} {t['title']} — {t['url']}" for t in st["tabs"]) or "(no tabs)"
