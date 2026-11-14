"""The sign-in door: a page only a person can get past, opened on the phone they are holding.

Asked for with a screenshot of Aria giving up on a GitHub sign-in after fifteen minutes:
"it can only be done at the machine, not from Telegram". The owner's words: "bento should
give the link to open it on the phone directly … it should be prompted about and go via
permission … if granted open it only for the session to key in, move forward".

A password is still never taken from a chat (chat history keeps it). What the chat carries
is a LINK, and what the link opens is the shared browser's own page, drawn on the phone
(`04f-streams.js`, the one live-window client), so the password goes from the phone's
keyboard into the real page and nowhere else.

The rules, each one a way this could have gone wrong:

  * **Asked for by a tap, never opened by an agent.** There is no tool. The wall message
    offers it, the person's tap in their own paired chat is the permission, and that tap is
    a ledger row. The machine's admin can switch the offer off (`handoff.enabled`).
  * **The link alone opens nothing.** Reading a link is a GET, and chat apps fetch links to
    preview them, so a GET only serves a page with a button. The button's POST binds the
    link to that one device (a cookie it can't read), and a second device is refused.
  * **The person says which device it is.** The page then shows four digits and the CHAT
    asks "is that your screen?". Somebody who only read the link gets a number nobody will
    confirm. A phone already signed in to this Bento (its session cookie, for the same
    account) skips the question: the session is the second proof.
  * **Only that page, only that long.** The door takes pointer, keys and text for the tab at
    the wall: no address bar, no tabs. It ends when the person taps Done, when the wall is
    gone (they signed in), or after `LIVE_S`; a link not opened in `OPEN_S` is dead.
  * **A door that exists only while it is used.** With remote access on, the routes are
    this server's (`/handoff/…`, open to the remote gate because the phone may have no
    session; the ticket and the device are its defence). With remote access off there is
    nothing on the network to reach, so a listener is started for this one hand-off on its
    own port, serving these routes and nothing else, and stopped when the hand-off ends.
  * **The road is said.** HTTPS and Tailscale are encrypted; a plain address on the same
    Wi-Fi is not, beyond the Wi-Fi's own lock, and both the chat and the page say which.

Faces. GUI and SUI: the Web window says the page is open on a phone and can close it, and
Settings → Remote access has the switch. TUI: `bento handoff` shows the switch and what is
open, and closes it. The page itself is a phone's; a terminal cannot draw it.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import html
import ipaddress
import json
import os
import secrets
import time
from pathlib import Path

from . import constcmp

OPEN_S = 300                 # a link nobody opened in this long is dead
LIVE_S = 900                 # the longest one hand-off lasts (cdpbrowser.WAIT_MAX_S)
PORT = 8327                  # the temporary door's port, when remote access is off
PORT_TRIES = 6
GUESS_LIMIT, GUESS_S = 12, 300    # wrong tickets from one address before it waits
COOKIE = "bento_handoff"
# What the phone may do to the tab. Never `navigate` or a tab op: the door is for the page
# at the wall, and the shared browser's other tabs hold the person's other sessions.
OPS = frozenset({"mouse", "wheel", "key", "text", "resize", "resume", "back", "reload"})
OPEN_WORDS = {"open", "open it", "open here", "open on this phone", "open on my phone", "link"}
YES_WORDS = {"yes", "y", "yes that's my screen", "yes thats my screen", "that's me", "thats me", "it's me"}
NO_WORDS = {"no", "n", "close", "close it", "no close it", "not me"}

_T: dict[str, dict] = {}                 # sha256(ticket) -> the hand-off
_DOOR: dict = {"server": None, "task": None, "port": 0}
_GUESS: dict[str, list] = {}             # address -> [count, until]
_TS: dict = {"at": 0.0, "state": None}   # Tailscale's answer, kept a minute
# Wired by the server: the machine's config, a ledger row, the person's screens.
_HOOKS: dict = {"cfg": lambda: None, "ledger": None, "screens": None, "session": None}
HANDLED = "[handled]"         # from_chat's answer when it already told the chat itself


def bind(cfg=None, ledger=None, screens=None, session=None):
    for k, v in (("cfg", cfg), ("ledger", ledger), ("screens", screens), ("session", session)):
        if v is not None:
            _HOOKS[k] = v


def _h(s: str) -> str:
    return hashlib.sha256(str(s).encode()).hexdigest()


def cfg():
    """The machine's config, or None where nothing wired one: an unwired embedding offers nothing."""
    try:
        return _HOOKS["cfg"]()
    except Exception:
        return None


def enabled(cfg: dict | None) -> bool:
    """The machine's switch. On unless an admin turned it off; the offer still needs a tap."""
    return cfg is not None and bool((cfg.get("handoff") or {}).get("enabled", True))


def _ledger(e: dict, action: str, detail: str):
    """One row per step of a hand-off, on the channel it was asked from."""
    fn = _HOOKS["ledger"]
    if fn:
        key = str(e.get("key") or "")
        surface = "telegram" if key.startswith("tg:") else "whatsapp" if key.startswith("wa:") else "api"
        with contextlib.suppress(Exception):
            fn(e["uid"], action, f"site:{e['site']}", detail, surface)


# ---- how the phone gets here -------------------------------------------------------------

def _kind_of(url: str) -> str:
    """Which road an address is: https, tailscale, or plain (the same network, not encrypted)."""
    u = str(url or "")
    if u.startswith("https://"):
        return "https"
    host = u.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0].strip("[]")
    with contextlib.suppress(ValueError):
        ip = ipaddress.ip_address(host)
        if ip in ipaddress.ip_network("100.64.0.0/10") or ip in ipaddress.ip_network("fd7a:115c:a1e0::/48"):
            return "tailscale"
        if ip.is_loopback:
            return "here"
    if host.endswith(".ts.net"):
        return "tailscale"
    return "plain"


ROAD_WORDS = {
    "https": "Encrypted (HTTPS).",
    "tailscale": "Over Tailscale, which encrypts it.",
    "plain": "Works on the same Wi-Fi. That connection isn't encrypted beyond your Wi-Fi's own lock.",
    "here": "On this machine.",
}


def how(cfg: dict) -> str:
    """'remote' when this server is already reachable (its own routes serve the page), else
    'door': a listener for this one hand-off."""
    from . import remote
    return "remote" if remote.enabled(cfg) else "door"


def can_offer(cfg: dict | None) -> dict:
    """Can a hand-off be offered here right now? Cheap, no subprocess: the wall message asks."""
    if cfg is None:
        return {"ok": False, "why": "Sign-in links aren't set up here."}
    if not enabled(cfg):
        return {"ok": False, "why": "Sign-in links are switched off on this machine."}
    if os.environ.get("AGENTOS_HANDOFF_BASE"):
        return {"ok": True, "how": how(cfg)}
    from . import remote
    if not remote.lan_addresses(1) and not os.environ.get("RENDER_EXTERNAL_URL"):
        return {"ok": False, "why": "This machine has no network address a phone could reach."}
    return {"ok": True, "how": how(cfg)}


async def _tailscale() -> dict:
    if time.time() - _TS["at"] < 60 and _TS["state"] is not None:
        return _TS["state"]
    st: dict = {}
    with contextlib.suppress(Exception):
        from . import tunnel
        st = await asyncio.wait_for(tunnel.tailscale_state(), 6)
    _TS.update(at=time.time(), state=st)
    return st


async def addresses(cfg: dict, port: int, via: str) -> list[dict]:
    """Where the phone can open the page, best road first. `AGENTOS_HANDOFF_BASE` stands in
    for a network in a test or a walk-through, the `AGENTOS_SIGNIN_BASE` idea."""
    env = os.environ.get("AGENTOS_HANDOFF_BASE", "").strip().rstrip("/")
    if env:
        base = env if env.count(":") > 1 else f"{env}:{port}"
        return [{"base": base, "kind": _kind_of(base)}]
    out: list[dict] = []
    if via == "remote":
        # a published address reaches this server's own port: a tunnel, or the cloud host
        pub = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
        with contextlib.suppress(Exception):
            from . import tunnel
            pub = pub or tunnel.cloudflared_url().rstrip("/")
        if pub.startswith("https://"):
            out.append({"base": pub, "kind": "https"})
    ts = await _tailscale()
    if ts.get("running"):
        ip = next((str(i) for i in ts.get("ips") or [] if ":" not in str(i)), "")
        if ip:
            out.append({"base": f"http://{ip}:{port}", "kind": "tailscale"})
    from . import remote
    for a in remote.lan_addresses(port)[:1]:           # the address, not the .local name
        if _kind_of(a) != "tailscale" and not any(x["base"] == a for x in out):
            out.append({"base": a, "kind": _kind_of(a)})
    return out


# ---- the hand-off ------------------------------------------------------------------------

def for_user(uid: str) -> dict | None:
    """The hand-off this person has open (not ended), if any."""
    for e in _T.values():
        if e["uid"] == (uid or "") and e["state"] != "ended":
            return e
    return None


def view(e: dict | None) -> dict | None:
    """What a screen may know about a hand-off. Never the ticket or the code."""
    if not e:
        return None
    return {"id": e["id"], "state": e["state"], "site": e["site"], "how": e["how"],
            "port": e["port"], "since": e["made"], "until": e["deadline"]}


def status(cfg: dict, uid: str = "") -> dict:
    return {"enabled": enabled(cfg), "how": how(cfg), "can": can_offer(cfg),
            "open": view(for_user(uid)), "door_port": _DOOR["port"] or 0,
            "port": int((cfg.get("handoff") or {}).get("port") or PORT)}


def _browser(uid: str):
    from . import cdpbrowser
    b = cdpbrowser.current(uid or "")
    return b if (b and b.running) else None


async def _reply(say, text: str, buttons: list | None = None) -> str:
    """Tell the chat. Through `say` when the channel gave one (it keeps the words out of the
    diary: a link is in them), else hand the words back."""
    if say:
        with contextlib.suppress(Exception):
            await say(text, buttons or [])
        return HANDLED
    return text


async def open_for(cfg: dict, uid: str, key: str, say=None) -> str:
    """The person tapped "Open on this phone". Mint the ticket, open the door if this machine
    isn't reachable yet, and tell them the links. `say(text, buttons)` is how the hand-off
    speaks to that chat: the links now, the match question and how it ended later. A button
    is (label, word); a word starting `url:` is a link to open, any other is an answer."""
    uid = uid or ""
    can = can_offer(cfg)
    if not can["ok"]:
        return await _reply(say, can["why"])
    b = _browser(uid)
    if not b or not b.attention:
        return await _reply(say, "Nothing is waiting on a page now.")
    old = for_user(uid)
    if old:
        await end(old, "replaced by a new link", tell=False)
    via = can["how"]
    port = int(os.environ.get("AGENTOS_BOUND_PORT") or cfg.get("port") or 8321)
    if via == "door":
        try:
            port = await _door_open(cfg)
        except Exception as ex:
            return await _reply(say, f"I couldn't open a door for it on this machine ({ex}). "
                                     "Sign in on a screen in the Web window.")
    roads = await addresses(cfg, port, via)
    if not roads:
        _door_close_soon()
        return await _reply(say, "This machine has no network address a phone could reach. "
                                 "Sign in on a screen in the Web window.")
    ticket = secrets.token_urlsafe(24)
    now = time.time()
    e = {"id": secrets.token_hex(4), "h": _h(ticket), "uid": uid, "key": key,
         "site": b.attention.get("site") or "a page", "kind": b.attention.get("kind") or "ask",
         "made": now, "deadline": now + LIVE_S, "how": via, "port": port, "state": "sent",
         "device": "", "code": "", "why": "", "prev": None, "say": say, "socks": set(),
         "refused": 0, "task": None}
    _T[e["h"]] = e
    e["task"] = asyncio.create_task(_watch(e))
    _ledger(e, "handoff.open", f"a sign-in link for {e['site']}, asked from {'Telegram' if key.startswith('tg:') else 'WhatsApp' if key.startswith('wa:') else 'a phone'}"
            + (f"; a door on port {port} for this hand-off" if via == "door" else ""))
    await _screens(e)
    lines = [f"🔗 Open this on your phone to do it on {e['site']} yourself:"]
    for r in roads:
        lines += [f"{r['base']}/handoff/{ticket}", ROAD_WORDS[r["kind"]]]
    lines.append(f"It works on one device, has to be opened within {OPEN_S // 60} minutes, "
                 "and closes when you're done.")
    return await _reply(say, "\n".join(lines), [("Open the page", f"url:{roads[0]['base']}/handoff/{ticket}")])


async def _screens(e: dict):
    """The person's screens hear how the hand-off stands; the Web window draws it."""
    b = _browser(e["uid"])
    if b:
        with contextlib.suppress(Exception):
            await b._state()
    fn = _HOOKS["screens"]
    if fn:
        with contextlib.suppress(Exception):
            await fn(e["uid"], {"type": "browser_handoff", **(view(e) or {})})


async def _say(e: dict, text: str, buttons: list | None = None):
    if e.get("say"):
        with contextlib.suppress(Exception):
            await e["say"](text, buttons or [])


async def _watch(e: dict):
    """A hand-off ends by itself: not opened in time, the wall gone, or its longest life."""
    try:
        while e["state"] != "ended":
            await asyncio.sleep(1.0)
            now = time.time()
            b = _browser(e["uid"])
            if not b or not b.attention:
                return await end(e, "the page moved on")
            if e["state"] == "sent" and now > e["made"] + OPEN_S:
                return await end(e, "not opened in time")
            if now > e["deadline"]:
                return await end(e, "it ran out of time")
    except asyncio.CancelledError:
        pass


DONE_WHY = ("done", "the page moved on")
DOOR_LINGER = 6.0           # the door outlives its hand-off this long, so the page can hear how it ended
END_WORDS = {
    "done": "✓ Done on your phone. Carrying on.",
    "the page moved on": "✓ That page is past. The link has closed.",
    "not opened in time": "The sign-in link wasn't opened in time, so it has closed. Say “open” for a new one.",
    "it ran out of time": "The sign-in link has closed: it ran out of time.",
    "closed by you": "The sign-in link is closed.",
    "not your screen": "Closed. Nobody got in: the link only showed a number.",
}


async def end(e: dict, why: str, tell: bool = True):
    """End a hand-off. Its page hears it first, then the sockets close, the desk gets its
    size back, and the door goes when nothing else needs it."""
    if e["state"] == "ended":
        return
    was = e["state"]
    e["state"], e["why"] = "ended", why
    if e.get("task") and e["task"] is not asyncio.current_task():
        e["task"].cancel()
    for ws, tell_page in list(e["socks"]):
        with contextlib.suppress(Exception):
            await tell_page({"type": "ended", "done": why in DONE_WHY})
        with contextlib.suppress(Exception):
            await ws.close(code=1000)
    e["socks"].clear()
    b = _browser(e["uid"])
    if b and e.get("prev"):
        with contextlib.suppress(Exception):
            await b.resize(*e["prev"])           # the desk gets its own size back
    _ledger(e, "handoff.end", why + ("; never opened" if was == "sent" else ""))
    await _screens(e)
    if tell and why in END_WORDS:
        await _say(e, END_WORDS[why])
    # an ended ticket is kept a little while so its page can say why, then forgotten
    asyncio.get_running_loop().call_later(120, lambda: _T.pop(e["h"], None))
    _door_close_soon()


async def close(uid: str, why: str = "closed by you") -> bool:
    e = for_user(uid)
    if not e:
        return False
    await end(e, why)
    return True


async def close_all():
    for e in list(_T.values()):
        await end(e, "the server is stopping")
    await _door_close_if_idle()


def _door_close_soon():
    async def later():
        await asyncio.sleep(DOOR_LINGER)
        await _door_close_if_idle()
    if _DOOR["server"] is not None:
        asyncio.create_task(later())


def waiting(uid: str, key: str) -> dict | None:
    """This chat's hand-off, if it has one open."""
    e = for_user(uid)
    return e if (e and e["key"] == key) else None


async def from_chat(cfg: dict, uid: str, key: str, words: str, say=None) -> str:
    """A message from the phone while the browser waits on a wall. '' when it isn't about
    the hand-off. One function for Telegram's buttons and WhatsApp's replies."""
    w = str(words or "").strip().lower().rstrip(".!")
    e = waiting(uid, key)
    if e and e["state"] == "joined":
        if w in YES_WORDS or w == e["code"]:
            e["state"] = "live"
            _ledger(e, "handoff.confirm", "the person said the device is theirs")
            await _screens(e)
            return await _reply(say, "✓ It's open on that screen. Do it there, then tap Done on the page.")
        if w in NO_WORDS:
            await end(e, "not your screen", tell=False)
            return await _reply(say, END_WORDS["not your screen"])
    if w in OPEN_WORDS:
        return await open_for(cfg, uid, key, say)
    if e and w in NO_WORDS:
        await end(e, "closed by you", tell=False)
        return await _reply(say, END_WORDS["closed by you"])
    return ""


# ---- the routes (one app, on this server and on the door) ---------------------------------

def _guess_wait(addr: str) -> int:
    g = _GUESS.get(addr)
    return max(0, int(g[1] - time.time())) if g and g[0] >= GUESS_LIMIT else 0


def _guess_bad(addr: str):
    if len(_GUESS) > 4096:
        _GUESS.clear()
    g = _GUESS.setdefault(addr, [0, 0.0])
    if g[1] < time.time():
        g[0] = 0
    g[0] += 1
    g[1] = time.time() + GUESS_S


def _find(ticket: str) -> dict | None:
    return _T.get(_h(ticket)) if 16 <= len(str(ticket)) <= 64 else None


def _mine(e: dict, cookies) -> bool:
    got = cookies.get(COOKIE) or ""
    return bool(e["device"] and got and constcmp.same(_h(got), e["device"]))


def _same_origin(headers) -> bool:
    """A page elsewhere must not drive this one. No Origin is a non-browser client."""
    o = headers.get("origin")
    if not o:
        return True
    return o.split("://", 1)[-1] == (headers.get("host") or "")


_HEAD = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
         "X-Content-Type-Options": "nosniff",
         "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                                    "connect-src 'self' ws: wss:; img-src blob: data:; base-uri 'none'; "
                                    "form-action 'none'; frame-ancestors 'none'"}


def _client_js() -> str:
    """The live-window client, the same one the Web window uses (04f-streams.js up to the
    browser shell). One client, so a phone's touch and keyboard behave the same here."""
    src = (Path(__file__).parent / "ui" / "src" / "js" / "04f-streams.js").read_text(encoding="utf-8")
    cut = src.find("/* ---------------- the shared browser window")
    return src[:cut] if cut > 0 else src


def page_html(e: dict | None, ticket: str, road: str, agent: str = "Aria") -> str:
    """The hand-off's page. Everything on it that came from elsewhere (a site's name, the
    agent's name) is escaped; the script draws with text nodes."""
    if not e or e["state"] == "ended":
        why = (e or {}).get("why") or ""
        done = why in DONE_WHY
        head = "All done" if done else "This link has closed"
        body = ("You can close this tab. " + html.escape(agent) + " is carrying on." if done else
                "It works once, for a few minutes. Ask for a new one in the chat by saying “open”.")
        return (_PAGE.replace("__TITLE__", head).replace("__BOOT__", "null")
                .replace("__BODY__", f'<main class="card"><h1>{head}</h1><p>{body}</p></main>')
                .replace("__JS__", ""))
    boot = {"ticket": ticket, "site": e["site"], "agent": agent, "road": road,
            "roadWords": ROAD_WORDS.get(road, ""), "kind": e["kind"]}
    return (_PAGE.replace("__TITLE__", "Sign in for " + html.escape(agent))
            .replace("__BOOT__", json.dumps(boot).replace("<", "\\u003c"))
            .replace("__BODY__", '<main id="root"></main>')
            .replace("__JS__", "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g,"
                               "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]))}\n"
                               + _client_js() + _PAGE_JS))


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,interactive-widget=resizes-content">
<meta name="robots" content="noindex"><title>__TITLE__</title>
<style>
:root{--bg:#0f0d1a;--card:#1a1728;--line:#2e2a44;--txt:#f1eefc;--mut:#a9a3c4;--acc:#8b5cf6;--ok:#34d399;--warn:#fbbf24}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--bg);color:var(--txt);
font:16px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif;-webkit-text-size-adjust:100%}
body{display:flex;flex-direction:column;height:100dvh;padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)}
main{flex:1;min-height:0;display:flex;flex-direction:column}
.card{margin:auto;max-width:440px;width:100%;padding:24px 20px;text-align:center}
.card h1{font-size:22px;margin:0 0 8px;letter-spacing:-.3px}.card p{color:var(--mut);margin:0 0 16px}
.site{display:inline-block;padding:6px 14px;border-radius:999px;background:var(--card);border:1px solid var(--line);font-weight:600;margin:0 0 16px}
.btn{display:block;width:100%;min-height:52px;border:0;border-radius:14px;background:var(--acc);color:#fff;font:600 17px/1 inherit;padding:0 18px}
.btn.quiet{background:var(--card);border:1px solid var(--line);color:var(--txt)}
.code{font:700 54px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:10px;margin:8px 0 14px;padding-left:10px}
.road{font-size:13px;color:var(--mut);margin-top:16px}.road.plain{color:var(--warn)}
.bar{display:flex;align-items:center;gap:8px;padding:8px 10px;border-bottom:1px solid var(--line);background:var(--card)}
.bar .where{flex:1;min-width:0;font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar button{min-height:44px;min-width:44px;border-radius:12px;border:1px solid var(--line);background:var(--bg);color:var(--txt);font:600 15px/1 inherit;padding:0 12px}
.bar .done{background:var(--ok);border-color:var(--ok);color:#062b1e}
.view{flex:1;min-height:0;position:relative;overflow:hidden;background:#000}
.sv{position:absolute;inset:0}.sv-cv{width:100%;height:100%;display:block;touch-action:none;outline:0}
.sv-hand{position:absolute;inset:0;pointer-events:none}.sv-tap{display:none}
.sv-note{position:absolute;left:8px;right:8px;bottom:8px;padding:8px 12px;border-radius:10px;background:rgba(15,13,26,.92);font-size:13px}
.sv-kb{position:absolute;left:0;top:0;width:1px;height:1px;opacity:0;font-size:16px;border:0;padding:0}
.foot{padding:6px 12px;font-size:12px;color:var(--mut);background:var(--card);border-top:1px solid var(--line)}
.foot.plain{color:var(--warn)}
[hidden]{display:none!important}
</style></head><body>__BODY__
<script>var BOOT=__BOOT__;
__JS__</script></body></html>"""


_PAGE_JS = r"""
(function(){
  var root=document.getElementById('root'),base=location.pathname.replace(/\/$/,''),sv=null,poll=0,S={state:'new'};
  function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e}
  function card(){root.textContent='';var c=el('div','card');root.appendChild(c);return c}
  function road(c){var r=el('div','road'+(BOOT.road==='plain'?' plain':''),BOOT.roadWords);c.appendChild(r)}
  function api(path,method){return fetch(base+path,{method:method||'GET',credentials:'same-origin',headers:{'Content-Type':'application/json'}})
    .then(function(r){return r.json().then(function(j){j._status=r.status;return j})})}
  function landing(){
    var c=card();c.appendChild(el('h1','',BOOT.agent+' needs you to do one thing'));
    c.appendChild(el('div','site',BOOT.site));
    c.appendChild(el('p','','This shows that one page from your Bento, here on this phone. What you type goes straight into the page. It is never put in the chat.'));
    var b=el('button','btn','Show the page');b.onclick=function(){b.disabled=true;join()};c.appendChild(b);road(c);
  }
  function closed(text){clearInterval(poll);if(sv){sv.destroy();sv=null}var c=card();c.appendChild(el('h1','',text||'This link has closed'));
    c.appendChild(el('p','','You can close this tab.'))}
  function refuse(j){var c=card();c.appendChild(el('h1','','This link is in use'));c.appendChild(el('p','',j.error||'It is already open on another device.'))}
  function join(){api('/join','POST').then(function(j){
    if(j._status>=400)return j._status===409?refuse(j):closed(j.error);
    paint(j)}).catch(function(){closed('Could not reach your Bento')})}
  function paint(j){
    if(j.state===S.state&&j.state!=='joined')return;S.state=j.state;
    if(j.state==='ended')return closed(j.done?'All done':'This link has closed');
    if(j.state==='joined'){
      var c=card();c.appendChild(el('h1','','Is this your screen?'));c.appendChild(el('div','code',j.code));
      c.appendChild(el('p','','Go back to the chat and confirm this number. The page opens here as soon as you do.'));road(c);
      if(!poll)poll=setInterval(tick,1500);return}
    if(j.state==='live')live();
  }
  var miss=0;function tick(){api('/state').then(function(j){miss=0;if(j._status>=400){closed(j.error);return}paint(j)}).catch(function(){if(++miss>=4)closed('This link has closed')})}
  function live(){
    root.textContent='';
    var bar=el('div','bar'),where=el('div','where',BOOT.site),kb=el('button','','⌨'),done=el('button','done','Done');
    kb.setAttribute('aria-label','Open the keyboard');bar.appendChild(where);bar.appendChild(kb);bar.appendChild(done);
    var view=el('div','view'),holder=el('div','');view.appendChild(holder);
    var foot=el('div','foot'+(BOOT.road==='plain'?' plain':''),'Only this page is shown. '+BOOT.roadWords);
    root.appendChild(bar);root.appendChild(view);root.appendChild(foot);
    function connect(){
      sv=streamView(holder,{path:base+'/ws',label:BOOT.site,
        onMessage:function(m){if(m.type==='ended')closed(m.done?'All done':'This link has closed')},
        onClose:function(){if(S.state==='live')setTimeout(function(){tick();if(S.state==='live'){holder.textContent='';connect()}},1200)}});
      kb.onclick=function(){sv.keyboard()};
    }
    connect();
    done.onclick=function(){done.disabled=true;api('/done','POST').then(function(){S.state='ended';closed('All done')})};
    if(!poll)poll=setInterval(tick,3000);
  }
  if(BOOT)landing();
})();
"""


def _road_of(request) -> str:
    if (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip() == "https" \
            or request.url.scheme == "https":
        return "https"
    return _kind_of("http://" + (request.headers.get("host") or ""))


def _has_session(request, uid: str) -> bool:
    """Is this phone already signed in to this Bento as the same person? Then the session is
    the second proof and the match question is skipped."""
    fn = _HOOKS["session"]
    try:
        return bool(fn and fn(request, uid))
    except Exception:
        return False


def routes():
    """The hand-off's routes, under `/handoff`. The same list on this server and on the door."""
    from starlette.responses import HTMLResponse, JSONResponse
    from starlette.routing import Route, WebSocketRoute

    def addr(conn) -> str:
        return (conn.client.host if conn.client else "") or "?"

    def lookup(request):
        a = addr(request)
        if _guess_wait(a):
            return None, JSONResponse({"error": "Too many wrong links from here. Wait a few minutes."},
                                      status_code=429, headers=_HEAD)
        e = _find(request.path_params["ticket"])
        if not e:
            _guess_bad(a)
        return e, None

    async def landing(request):
        e, no = lookup(request)
        if no:
            return no
        agent = str((cfg() or {}).get("agent_name") or "Aria")
        return HTMLResponse(page_html(e, request.path_params["ticket"], _road_of(request), agent),
                            status_code=200 if e else 404, headers=_HEAD)

    async def join(request):
        e, no = lookup(request)
        if no:
            return no
        if not e or e["state"] == "ended":
            return JSONResponse({"error": "This link has closed."}, status_code=410, headers=_HEAD)
        if not _same_origin(request.headers):
            return JSONResponse({"error": "Not from this page."}, status_code=403, headers=_HEAD)
        if e["device"]:
            if _mine(e, request.cookies):
                return JSONResponse(_state(e), headers=_HEAD)
            e["refused"] += 1
            if e["refused"] == 1:
                _ledger(e, "handoff.refused", f"a second device tried the link, from {addr(request)}")
                await _say(e, "A second device tried to open the sign-in link and was refused. "
                              "If that was you in another browser, say “open” for a new link.")
            return JSONResponse({"error": "This link is already open on another device."},
                                status_code=409, headers=_HEAD)
        secret = secrets.token_urlsafe(24)
        e["device"] = _h(secret)
        if _has_session(request, e["uid"]):
            e["state"] = "live"
            _ledger(e, "handoff.join", f"opened on a phone signed in to this Bento, from {addr(request)}")
            await _say(e, "✓ It's open on your signed-in phone. Do it there, then tap Done on the page.")
        else:
            e["code"] = f"{secrets.randbelow(10000):04d}"
            e["state"] = "joined"
            _ledger(e, "handoff.join", f"opened on a device, from {addr(request)}")
            await _say(e, f"A device opened the link and shows {e['code']}. Is that your screen?",
                       [("Yes, that's my screen", "yes"), ("No, close it", "no")])
        await _screens(e)
        resp = JSONResponse(_state(e), headers=_HEAD)
        resp.set_cookie(COOKIE, secret, max_age=LIVE_S, httponly=True, samesite="strict",
                        secure=_road_of(request) == "https", path=f"/handoff/{request.path_params['ticket']}")
        return resp

    async def state(request):
        e, no = lookup(request)
        if no:
            return no
        if not e:
            return JSONResponse({"error": "This link has closed."}, status_code=410, headers=_HEAD)
        if e["state"] != "ended" and not _mine(e, request.cookies):
            return JSONResponse({"error": "This link is open on another device."}, status_code=409, headers=_HEAD)
        return JSONResponse(_state(e), headers=_HEAD)

    async def done(request):
        e, no = lookup(request)
        if no:
            return no
        if not e or e["state"] != "live" or not _mine(e, request.cookies) or not _same_origin(request.headers):
            return JSONResponse({"error": "This link has closed."}, status_code=410, headers=_HEAD)
        b = _browser(e["uid"])
        if b:
            await b.person({"type": "resume"})
        await end(e, "done")
        return JSONResponse({"ok": True}, headers=_HEAD)

    async def sock(ws):
        e = _find(ws.path_params["ticket"])
        if (not e or e["state"] != "live" or not _mine(e, ws.cookies) or not _same_origin(ws.headers)):
            await ws.close(code=4403)
            return
        b = _browser(e["uid"])
        if not b or not b.attention:
            await ws.close(code=4410)
            return
        await ws.accept()
        lock = asyncio.Lock()

        async def send_bytes(data):
            async with lock:
                await ws.send_bytes(data)

        async def send_json(msg):
            # the phone hears the page's state, never the browser's other tabs
            if msg.get("type") == "state":
                msg = {"type": "state", "size": msg.get("size"), "url": ""}
            async with lock:
                await ws.send_text(json.dumps(msg))
        try:
            hello = json.loads(await asyncio.wait_for(ws.receive_text(), 15))
        except Exception:
            hello = {}
        if e["prev"] is None:
            e["prev"] = tuple(b.size)
        me = (ws, send_json)
        e["socks"].add(me)
        vid = await b.add_viewer(send_bytes, send_json, int(hello.get("w") or 0), int(hello.get("h") or 0))
        try:
            while e["state"] == "live":
                op = json.loads(await ws.receive_text())
                if op.get("type") not in OPS:
                    continue
                if op.get("type") == "resume":
                    await b.person(op)
                    await end(e, "done")
                    break
                with contextlib.suppress(Exception):
                    await b.person(op)
        except Exception:
            pass
        finally:
            e["socks"].discard(me)
            with contextlib.suppress(Exception):
                await b.drop_viewer(vid)

    return [Route("/{ticket}", landing, methods=["GET"]),
            Route("/{ticket}/join", join, methods=["POST"]),
            Route("/{ticket}/state", state, methods=["GET"]),
            Route("/{ticket}/done", done, methods=["POST"]),
            WebSocketRoute("/{ticket}/ws", sock)]


def _state(e: dict) -> dict:
    out = {"state": e["state"], "site": e["site"]}
    if e["state"] == "joined":
        out["code"] = e["code"]
    if e["state"] == "ended":
        out["done"] = e["why"] in DONE_WHY
    return out


def app():
    """The routes as an app of their own, mounted at /handoff."""
    from starlette.applications import Starlette
    from starlette.routing import Mount
    return Starlette(routes=[Mount("/handoff", routes=routes())])


# ---- the door: a listener for one hand-off, when nothing else is reachable ------------------

async def _door_open(cfg: dict) -> int:
    """Start the door if it isn't up. It serves the hand-off routes and nothing else."""
    if _DOOR["server"] is not None:
        return _DOOR["port"]
    import socket

    import uvicorn
    first = int((cfg.get("handoff") or {}).get("port") or PORT)
    last: Exception | None = None
    for port in range(first, first + PORT_TRIES):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((os.environ.get("AGENTOS_HANDOFF_BIND") or "0.0.0.0", port))
        except OSError as ex:
            last = ex
            continue

        class _Quiet(uvicorn.Server):
            # the main server owns the process's signals; this one is stopped by `should_exit`
            @contextlib.contextmanager
            def capture_signals(self):
                yield

            def install_signal_handlers(self):
                pass
        server = _Quiet(uvicorn.Config(app(), log_level="warning", access_log=False, lifespan="off",
                                       server_header=False, proxy_headers=False))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        _DOOR.update(server=server, task=task, port=port)
        for _ in range(100):
            if server.started or task.done():
                break
            await asyncio.sleep(0.02)
        if task.done():
            _DOOR.update(server=None, task=None, port=0)
            raise RuntimeError("the door did not start")
        return port
    raise RuntimeError(f"no free port from {first}" + (f": {last}" if last else ""))


async def _door_close_if_idle():
    if _DOOR["server"] is None:
        return
    if any(e["state"] != "ended" and e["how"] == "door" for e in _T.values()):
        return
    server, task = _DOOR["server"], _DOOR["task"]
    _DOOR.update(server=None, task=None, port=0)
    server.should_exit = True
    if task is not None and task.get_loop() is not asyncio.get_running_loop():
        return          # a door from a loop that has gone (a test's): nothing here can wait on it
    # a phone that is still on the closing page holds a keep-alive: don't wait for it
    loop = asyncio.get_running_loop()
    loop.call_later(1.5, lambda: setattr(server, "force_exit", True))
    if task and task is not asyncio.current_task():
        with contextlib.suppress(Exception):
            await asyncio.wait_for(asyncio.shield(task), 4)
