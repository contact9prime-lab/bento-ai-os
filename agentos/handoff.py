"""The sign-in link: a page only a person can get past, opened on the phone they are holding,
through remote access and nothing else.

Asked for with a screenshot of Aria giving up on a GitHub sign-in after fifteen minutes:
"it can only be done at the machine, not from Telegram". The owner's words: "bento should
give the link to open it on the phone directly … it should be prompted about and go via
permission … if granted open it only for the session to key in, move forward". The first
cut opened a door of its own for the link (a listener, a ticket, a number to confirm), and
the owner's answer was: "it needs to come in the remote itself … the user will have to
login to the remote and key in the details from that only … it must only go through remote".

A password is still never taken from a chat (chat history keeps it). What the chat carries
is a LINK into this machine's remote access, and what the link opens, after the person has
signed in there, is the shared browser's own page drawn on the phone (`04f-streams.js`, the
one live-window client), so the password goes from the phone's keyboard into the real page.

The rules, each one a way this could have gone wrong:

  * **Only through remote access.** There is no second door. With remote access off nothing
    is offered and the chat says what would turn it on. The routes are behind the remote
    gate like any other page: a phone with no session gets the sign-in page at the link's
    own address, and comes back to the link once it has signed in.
  * **The link is an address, never a key.** Whoever opens it must be signed in to this
    Bento as the person the page is waiting for, with their screen unlocked. Each route
    checks that itself, and so does the socket, which no middleware sees.
  * **Asked for by a tap, never opened by an agent.** There is no tool. The wall message
    offers it, the person's tap in their own paired chat is the permission, and that tap is
    a ledger row. The machine's admin can switch the offer off (`handoff.enabled`).
  * **Only that page, only that long.** The link's page takes pointer, keys and text for
    the tab at the wall: no address bar, no tabs. It ends when the person taps Done, when
    the wall is gone (they signed in), when remote access is switched off, or after
    `LIVE_S`; a link not opened in `OPEN_S` is dead.
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

OPEN_S = 300                 # a link nobody opened in this long is dead
LIVE_S = 900                 # the longest one hand-off lasts (cdpbrowser.WAIT_MAX_S)
# What the phone may do to the tab. Never `navigate` or a tab op: the link is for the page
# at the wall, and the shared browser's other tabs hold the person's other sessions.
OPS = frozenset({"mouse", "wheel", "key", "text", "resize", "resume", "back", "reload"})
OPEN_WORDS = {"open", "open it", "open here", "open on this phone", "open on my phone", "link"}
CLOSE_WORDS = {"close", "close it", "close the link"}

_T: dict[str, dict] = {}                 # sha256(ticket) -> the hand-off
_TS: dict = {"at": 0.0, "state": None}   # Tailscale's answer, kept a minute
# Wired by the server: the machine's config, a ledger row, the person's screens, who a
# request or socket is signed in as, and the gate every socket passes. Unwired, `who` is
# nobody and the socket gate refuses: an embedding that wired nothing is a closed door.
_HOOKS: dict = {"cfg": lambda: None, "ledger": None, "screens": None, "who": None, "ws_gate": None}
HANDLED = "[handled]"         # from_chat's answer when it already told the chat itself


def bind(cfg=None, ledger=None, screens=None, who=None, ws_gate=None):
    for k, v in (("cfg", cfg), ("ledger", ledger), ("screens", screens), ("who", who), ("ws_gate", ws_gate)):
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


REMOTE_OFF = ("Remote access is off on this machine, so a phone has no way in. "
              "Turn it on at the machine with “bento remote --on”, then ask again.")


def can_offer(cfg: dict | None) -> dict:
    """Can a sign-in link be offered here right now? Cheap, no subprocess: the wall message
    asks. `needs` names what is missing when that is remote access, so the chat can say it."""
    if cfg is None:
        return {"ok": False, "why": "Sign-in links aren't set up here."}
    if not enabled(cfg):
        return {"ok": False, "why": "Sign-in links are switched off on this machine."}
    from . import remote
    if not remote.enabled(cfg):
        return {"ok": False, "why": REMOTE_OFF, "needs": "remote"}
    if os.environ.get("AGENTOS_HANDOFF_BASE"):
        return {"ok": True}
    if not remote.lan_addresses(1) and not os.environ.get("RENDER_EXTERNAL_URL"):
        return {"ok": False, "why": "This machine has no network address a phone could reach."}
    return {"ok": True}


async def _tailscale() -> dict:
    if time.time() - _TS["at"] < 60 and _TS["state"] is not None:
        return _TS["state"]
    st: dict = {}
    with contextlib.suppress(Exception):
        from . import tunnel
        st = await asyncio.wait_for(tunnel.tailscale_state(), 6)
    _TS.update(at=time.time(), state=st)
    return st


async def addresses(cfg: dict, port: int) -> list[dict]:
    """Where the phone reaches this machine's remote access, best road first.
    `AGENTOS_HANDOFF_BASE` stands in for a network in a test or a walk-through, the
    `AGENTOS_SIGNIN_BASE` idea."""
    env = os.environ.get("AGENTOS_HANDOFF_BASE", "").strip().rstrip("/")
    if env:
        base = env if env.count(":") > 1 else f"{env}:{port}"
        return [{"base": base, "kind": _kind_of(base)}]
    out: list[dict] = []
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
    """What a screen may know about a hand-off. Never the ticket."""
    if not e:
        return None
    return {"id": e["id"], "state": e["state"], "site": e["site"],
            "since": e["made"], "until": e["deadline"]}


def status(cfg: dict, uid: str = "") -> dict:
    from . import remote
    return {"enabled": enabled(cfg), "remote": remote.enabled(cfg), "can": can_offer(cfg),
            "open": view(for_user(uid))}


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
    """The person tapped "Open on this phone". Mint the link and tell them where it is.
    `say(text, buttons)` is how the hand-off speaks to that chat: the link now, how it ended
    later. A button is (label, word); a word starting `url:` is a link to open."""
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
    port = int(os.environ.get("AGENTOS_BOUND_PORT") or cfg.get("port") or 8321)
    roads = await addresses(cfg, port)
    if not roads:
        return await _reply(say, "This machine has no network address a phone could reach. "
                                 "Sign in on a screen in the Web window.")
    ticket = secrets.token_urlsafe(24)
    now = time.time()
    e = {"id": secrets.token_hex(4), "h": _h(ticket), "uid": uid, "key": key,
         "site": b.attention.get("site") or "a page", "kind": b.attention.get("kind") or "ask",
         "made": now, "deadline": now + LIVE_S, "state": "sent", "why": "", "prev": None,
         "say": say, "socks": set(), "refused": 0, "task": None}
    _T[e["h"]] = e
    e["task"] = asyncio.create_task(_watch(e))
    _ledger(e, "handoff.open", f"a sign-in link for {e['site']}, asked from "
            f"{'Telegram' if key.startswith('tg:') else 'WhatsApp' if key.startswith('wa:') else 'a phone'}, "
            "through remote access")
    await _screens(e)
    lines = [f"🔗 Open this on your phone to do it on {e['site']} yourself:"]
    for r in roads:
        lines += [f"{r['base']}/handoff/{ticket}", ROAD_WORDS[r["kind"]]]
    lines.append("You sign in to your Bento first, as you do for remote access. Then the page opens.")
    lines.append(f"Open it within {OPEN_S // 60} minutes. It closes when you're done.")
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
            from . import remote
            c = cfg()
            if c is None or not remote.enabled(c) or not enabled(c):
                return await end(e, "remote access was turned off")
            if e["state"] == "sent" and now > e["made"] + OPEN_S:
                return await end(e, "not opened in time")
            if now > e["deadline"]:
                return await end(e, "it ran out of time")
    except asyncio.CancelledError:
        pass


DONE_WHY = ("done", "the page moved on")
END_WORDS = {
    "done": "✓ Done on your phone. Carrying on.",
    "the page moved on": "✓ That page is past. The link has closed.",
    "not opened in time": "The sign-in link wasn't opened in time, so it has closed. Say “open” for a new one.",
    "it ran out of time": "The sign-in link has closed: it ran out of time.",
    "closed by you": "The sign-in link is closed.",
    "remote access was turned off": "The sign-in link has closed: remote access was turned off.",
}


async def end(e: dict, why: str, tell: bool = True):
    """End a hand-off. Its page hears it first, then the sockets close and the desk gets its
    size back."""
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


async def close(uid: str, why: str = "closed by you") -> bool:
    e = for_user(uid)
    if not e:
        return False
    await end(e, why)
    return True


async def close_all():
    for e in list(_T.values()):
        await end(e, "the server is stopping")


def waiting(uid: str, key: str) -> dict | None:
    """This chat's hand-off, if it has one open."""
    e = for_user(uid)
    return e if (e and e["key"] == key) else None


async def from_chat(cfg: dict, uid: str, key: str, words: str, say=None) -> str:
    """A message from the phone while the browser waits on a wall. '' when it isn't about
    the hand-off. One function for Telegram's buttons and WhatsApp's replies."""
    w = str(words or "").strip().lower().rstrip(".!")
    if w in OPEN_WORDS:
        return await open_for(cfg, uid, key, say)
    e = waiting(uid, key)
    if e and w in CLOSE_WORDS:
        await end(e, "closed by you", tell=False)
        return await _reply(say, END_WORDS["closed by you"])
    return ""


# ---- the routes (this server's, behind the remote gate) -------------------------------------

def _find(ticket: str) -> dict | None:
    return _T.get(_h(ticket)) if 16 <= len(str(ticket)) <= 64 else None


def _who(conn) -> str | None:
    """Who this request or socket is signed in as, by the server's own rules. None is nobody:
    no session, a locked screen, or nothing wired."""
    fn = _HOOKS["who"]
    try:
        return fn(conn) if fn else None
    except Exception:
        return None


def _theirs(e: dict, conn) -> bool:
    """Is this the person the page is waiting for, signed in through remote access?"""
    who = _who(conn)
    return who is not None and who == e["uid"]


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


def page_html(e: dict | None, ticket: str, road: str, agent: str = "Aria", theirs: bool = True) -> str:
    """The link's page, for somebody already signed in. Everything on it that came from
    elsewhere (a site's name, the agent's name) is escaped; the script draws with text nodes."""
    def card(head: str, body: str) -> str:
        return (_PAGE.replace("__TITLE__", head).replace("__BOOT__", "null")
                .replace("__BODY__", f'<main class="card"><h1>{head}</h1><p>{body}</p></main>')
                .replace("__JS__", ""))
    if not e or e["state"] == "ended":
        why = (e or {}).get("why") or ""
        if why in DONE_WHY:
            return card("All done", "You can close this tab. " + html.escape(agent) + " is carrying on.")
        return card("This link has closed",
                    "It works for a few minutes. Ask for a new one in the chat by saying “open”.")
    if not theirs:
        return card("This link isn't yours to open",
                    "Sign in to this Bento as the person the page is waiting for.")
    boot = {"site": e["site"], "agent": agent, "road": road,
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
  // an answer that isn't ours is the sign-in page: the session ended, so load it here
  function api(path,method){return fetch(base+path,{method:method||'GET',credentials:'same-origin',headers:{'Content-Type':'application/json'}})
    .then(function(r){if((r.headers.get('content-type')||'').indexOf('json')<0){location.reload();throw new Error('signed out')}
      return r.json().then(function(j){j._status=r.status;return j})})}
  function opening(){
    var c=card();c.appendChild(el('h1','',BOOT.agent+' needs you to do one thing'));
    c.appendChild(el('div','site',BOOT.site));
    c.appendChild(el('p','','Opening that one page from your Bento. What you type goes straight into the page. It is never put in the chat.'));
    c.appendChild(el('div','road'+(BOOT.road==='plain'?' plain':''),BOOT.roadWords));
  }
  function closed(text){clearInterval(poll);if(sv){sv.destroy();sv=null}var c=card();c.appendChild(el('h1','',text||'This link has closed'));
    c.appendChild(el('p','','You can close this tab.'))}
  function join(){api('/join','POST').then(function(j){
    if(j._status>=400)return closed(j.error);
    paint(j)}).catch(function(){closed('Could not reach your Bento')})}
  function paint(j){
    if(j.state===S.state)return;S.state=j.state;
    if(j.state==='ended')return closed(j.done?'All done':'This link has closed');
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
  if(BOOT){opening();join()}
})();
"""


def _road_of(request) -> str:
    if (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip() == "https" \
            or request.url.scheme == "https":
        return "https"
    return _kind_of("http://" + (request.headers.get("host") or ""))


def routes():
    """The link's routes, under `/handoff` on this server. The remote gate has already turned
    away anybody not signed in (a browser gets the sign-in page at this address); every route
    still asks who it is, because the page is one person's."""
    from starlette.responses import HTMLResponse, JSONResponse
    from starlette.routing import Route, WebSocketRoute

    def addr(conn) -> str:
        return (conn.client.host if conn.client else "") or "?"

    def no(words: str, code: int):
        return JSONResponse({"error": words}, status_code=code, headers=_HEAD)

    def mine(request):
        """(the hand-off, None) for its own person; (None, a refusal) for anybody else."""
        e = _find(request.path_params["ticket"])
        if not e:
            return None, no("This link has closed.", 410)
        if not _theirs(e, request):
            if not e["refused"]:
                _ledger(e, "handoff.refused", f"somebody not signed in as its person tried the link, from {addr(request)}")
            e["refused"] += 1
            return None, no("Sign in to this Bento as the person the page is waiting for.", 403)
        return e, None

    async def landing(request):
        e = _find(request.path_params["ticket"])
        agent = str((cfg() or {}).get("agent_name") or "Aria")
        theirs = bool(e and _theirs(e, request))
        code = 404 if not e else 200 if (theirs or e["state"] == "ended") else 403
        return HTMLResponse(page_html(e, request.path_params["ticket"], _road_of(request), agent, theirs),
                            status_code=code, headers=_HEAD)

    async def join(request):
        e, refused = mine(request)
        if refused:
            return refused
        if e["state"] == "ended":
            return no("This link has closed.", 410)
        if not _same_origin(request.headers):
            return no("Not from this page.", 403)
        if e["state"] == "sent":
            e["state"] = "live"
            _ledger(e, "handoff.join", f"opened on a phone signed in through remote access, from {addr(request)}")
            await _say(e, "✓ It's open on your phone. Do it there, then tap Done on the page.")
            await _screens(e)
        return JSONResponse(_state(e), headers=_HEAD)

    async def state(request):
        e, refused = mine(request)
        return refused or JSONResponse(_state(e), headers=_HEAD)

    async def done(request):
        e, refused = mine(request)
        if refused:
            return refused
        if e["state"] != "live" or not _same_origin(request.headers):
            return no("This link has closed.", 410)
        b = _browser(e["uid"])
        if b:
            await b.person({"type": "resume"})
        await end(e, "done")
        return JSONResponse({"ok": True}, headers=_HEAD)

    async def sock(ws):
        # no middleware sees a socket: the server's one socket gate (the name, the origin,
        # the sign-in), then whose page it is
        gate = _HOOKS["ws_gate"]
        if gate is None:
            await ws.close(code=4401)
            return
        if await gate(ws):
            return
        e = _find(ws.path_params["ticket"])
        if not e or e["state"] != "live" or not _theirs(e, ws):
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
    if e["state"] == "ended":
        out["done"] = e["why"] in DONE_WHY
    return out


def app():
    """The routes as an app of their own, mounted at /handoff."""
    from starlette.applications import Starlette
    from starlette.routing import Mount
    return Starlette(routes=[Mount("/handoff", routes=routes())])
