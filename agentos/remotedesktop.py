"""Remote Desktop — the real screen, on your phone, in the browser.

WHAT THIS ADDS, AND WHY IT IS NOT THE SAME AS REMOTE ACCESS
===========================================================
AgentOS already had two of the three things you want from a phone:

    remote access   the AgentOS desktop itself, over HTTP, laid out for the
                    screen you opened it on. It is the shell — HTML — so it
                    travels perfectly. What it CANNOT show is a native app,
                    because those are pixels the compositor paints on the
                    machine's own display and were never part of the page.
    Host Screen     a still of that display, refreshed. Answers "did it open",
                    but you cannot touch it.

The missing third is control: the screen streamed AND your taps sent back. That
is remote-desktop work, and `wayvnc` (ISC) already does it properly for wlroots
compositors — so AgentOS runs it rather than reinventing it. The problem with
wayvnc alone is that it needs a VNC client app, and it has no password of its
own, so it can only safely listen on loopback.

This module closes both gaps at once, and the shape is the point:

    phone browser ──HTTPS/HTTP──> AgentOS  ──loopback TCP──> wayvnc ──> screen
                    passphrase +           127.0.0.1:5900
                    signed session

The phone speaks to AgentOS, which it already authenticates to. AgentOS relays
that WebSocket to wayvnc on loopback. So:

  · No VNC app to install — the client is noVNC, which is JavaScript.
  · The VNC port never leaves the machine. It stays 127.0.0.1, always, exactly
    as before; nothing new is exposed to the network.
  · The passphrase, the PBKDF2 hash, the signed session cookie, the loopback
    trust rule and the backoff all apply unchanged, because this is just another
    authenticated route on the same server. wayvnc's missing password stops
    mattering, because wayvnc is no longer reachable from anywhere.

noVNC is packaged by the distribution (MPL-2.0) and is asked for, not shipped:
`novnc` in the optional components catalogue. AgentOS serves the copy already on
the machine and bundles none of it.

It is off until it is switched on, like remote access itself.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

#: Where distributions put noVNC's browser client. Debian/Ubuntu and Fedora
#: agree on the first; the others are for people who unpacked it themselves.
NOVNC_DIRS = (
    "/usr/share/novnc",
    "/usr/share/webapps/novnc",
    "/opt/novnc",
    str(Path.home() / ".local/share/novnc"),
)


def novnc_dir() -> str:
    """The installed noVNC client, or '' — identified by the file we actually
    need (core/rfb.js), not by the directory existing."""
    for d in NOVNC_DIRS:
        if os.path.isfile(os.path.join(d, "core", "rfb.js")):
            return d
    return ""


def available() -> dict:
    """What is present, and what each missing piece would unlock."""
    return {
        "novnc": bool(novnc_dir()),
        "novnc_dir": novnc_dir(),
        "wayvnc": bool(shutil.which("wayvnc")),
    }


def ready() -> bool:
    a = available()
    return bool(a["novnc"] and a["wayvnc"])


# =============================================================================
# the phone client
# =============================================================================

def page(ws_path: str = "/ws/vnc", title: str = "") -> str:
    """A remote desktop sized for a thumb.

    Written as its own page rather than an app window inside the desktop for one
    reason: on a phone you want the whole screen for the remote machine, and you
    do not want the AgentOS shell also drawing a dock over it. noVNC's own
    vnc.html is a desktop UI with a settings sidebar; this is the phone one.

    Touch handling is noVNC's, not ours — it already maps taps to clicks, drag to
    drag, two-finger scroll to wheel. What we add is the bit it cannot know: a
    toolbar with the keys a phone keyboard does not have (Esc, Tab, Ctrl, the
    arrows, and Ctrl+Alt+Del), plus a scale toggle, because "fit the screen" and
    "1:1 and pan" are both right at different moments.
    """
    host = title or "this machine"
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>AgentOS — Remote Desktop</title>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="theme-color" content="#0b0d10">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="apple-touch-icon" href="/assets/icon-180.png">
<style>
  :root{{--bg:#0b0d10;--bar:#151920;--line:#232a35;--txt:#e6ebf2;--dim:#8a94a6;--acc:#5eead4;
        --safe-b:env(safe-area-inset-bottom,0px);--safe-t:env(safe-area-inset-top,0px)}}
  *{{box-sizing:border-box;-webkit-tap-highlight-color:transparent}}
  html,body{{margin:0;height:100%;background:var(--bg);color:var(--txt);overflow:hidden;
    font:14px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI',Inter,Roboto,sans-serif}}
  /* noVNC injects its own container div and canvas in here. Both are forced to
     black and to fill the box: a landscape desktop scaled into a portrait phone
     always letterboxes, and letterboxing against black reads as a screen, while
     letterboxing against a lighter grey reads as a broken layout. */
  #screen{{position:fixed;inset:calc(38px + var(--safe-t)) 0 calc(50px + var(--safe-b)) 0;
    background:#000;display:flex;align-items:center;justify-content:center;overflow:hidden}}
  #screen>div{{background:#000!important;width:100%;height:100%;
    display:flex;align-items:center;justify-content:center}}
  #screen canvas{{display:block;background:#000}}
  #rotate{{position:fixed;left:0;right:0;bottom:calc(58px + var(--safe-b));text-align:center;
    color:var(--dim);font-size:12px;pointer-events:none;z-index:4;opacity:0;transition:opacity .3s}}
  #rotate.on{{opacity:1}}
  .bar{{position:fixed;left:0;right:0;display:flex;align-items:center;gap:6px;
    background:var(--bar);border-color:var(--line);z-index:5;padding:0 8px}}
  #top{{top:0;height:calc(38px + var(--safe-t));padding-top:var(--safe-t);border-bottom:1px solid var(--line)}}
  #keys{{bottom:0;height:calc(50px + var(--safe-b));padding-bottom:var(--safe-b);
    border-top:1px solid var(--line);overflow-x:auto;scrollbar-width:none}}
  #keys::-webkit-scrollbar{{display:none}}
  button{{background:#1e242e;color:var(--txt);border:1px solid var(--line);border-radius:9px;
    padding:8px 11px;font-size:13px;font-weight:600;white-space:nowrap;flex:0 0 auto}}
  button:active{{background:#2a323f}}
  .mark{{width:22px;height:22px;border-radius:7px;flex:0 0 auto;
    background:linear-gradient(135deg,#5eead4,#22d3ee);color:#04211c;font-weight:900;
    display:flex;align-items:center;justify-content:center;font-size:12px}}
  #st{{color:var(--dim);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}}
  #st b{{color:var(--acc);font-weight:600}}
  #msg{{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;
    flex-direction:column;gap:14px;text-align:center;padding:30px;z-index:9;background:var(--bg)}}
  #msg.hide{{display:none}}
  #msg .e{{color:#f87171;max-width:34em}}
  a{{color:var(--acc)}}
</style></head><body>
<div class="bar" id="top">
  <span class="mark">&#9650;</span>
  <span id="st">connecting to <b>{host}</b>…</span>
  <button id="fit">Fit</button>
  <button id="kbd">&#9000;</button>
</div>
<div id="screen"></div>
<div id="rotate"></div>
<div class="bar" id="keys">
  <button data-k="Escape">Esc</button>
  <button data-k="Tab">Tab</button>
  <button data-m="ControlLeft">Ctrl</button>
  <button data-m="AltLeft">Alt</button>
  <button data-m="MetaLeft">Super</button>
  <button data-k="ArrowLeft">&#8592;</button>
  <button data-k="ArrowDown">&#8595;</button>
  <button data-k="ArrowUp">&#8593;</button>
  <button data-k="ArrowRight">&#8594;</button>
  <button data-k="Home">Home</button>
  <button data-k="End">End</button>
  <button id="cad">Ctrl+Alt+Del</button>
</div>
<div id="msg"><div class="mark" style="width:56px;height:56px;border-radius:16px;font-size:26px">&#9650;</div>
  <div id="msgt">Starting the remote desktop…</div></div>
<!-- A hidden input is the only way to summon a phone's on-screen keyboard;
     noVNC then reads the real key events from it. -->
<input id="kbin" autocapitalize="off" autocorrect="off" autocomplete="off" spellcheck="false"
       style="position:fixed;opacity:0;pointer-events:none;left:-999px;width:1px;height:1px">
<script type="module">
import RFB from '/novnc/core/rfb.js';

const st = document.getElementById('st'), msg = document.getElementById('msg'),
      msgt = document.getElementById('msgt'), screenEl = document.getElementById('screen');
const say = (html) => {{ st.innerHTML = html; }};
const fail = (text, hint) => {{
  msg.classList.remove('hide');
  msgt.innerHTML = '<div class="e">' + text + '</div>' +
    (hint ? '<p style="color:var(--dim);max-width:34em">' + hint + '</p>' : '');
}};

let rfb = null, scaling = true;

function connect() {{
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const url = proto + '://' + location.host + '{ws_path}';
  try {{
    rfb = new RFB(screenEl, url, {{ wsProtocols: ['binary'] }});
  }} catch (e) {{
    fail('Could not start the VNC client: ' + e.message); return;
  }}
  // scaleViewport and clipViewport are alternatives, not companions: "fit" scales
  // the whole screen down, "1:1" shows real pixels and pans. Setting both leaves
  // noVNC scaling AND clipping, which is how the remote screen ended up as a
  // small strip in the middle of a large empty box.
  rfb.scaleViewport = true;
  rfb.clipViewport = false;
  rfb.resizeSession = false;     // never resize someone's real display to suit a phone
  rfb.focusOnClick = true;

  rfb.addEventListener('connect', () => {{
    msg.classList.add('hide');
    say('connected to <b>{host}</b>');
    hint();
  }});
  rfb.addEventListener('disconnect', (e) => {{
    say('disconnected');
    fail('The remote desktop disconnected.',
         e.detail && e.detail.clean
           ? 'The service was stopped on the machine. Turn Remote Desktop back on in System Settings, then reload.'
           : 'Connection lost. Check that AgentOS is still running, then reload this page.');
  }});
  rfb.addEventListener('securityfailure',
    () => fail('The remote desktop refused the connection.'));
}}
connect();

// ---- the keys a phone keyboard does not have -------------------------------
// Modifier buttons latch: tap Ctrl, then tap C. Anything else would need two
// fingers on a screen that has no second button.
const latched = new Set();
function paintLatches() {{
  document.querySelectorAll('[data-m]').forEach(b =>
    b.style.borderColor = latched.has(b.dataset.m) ? 'var(--acc)' : 'var(--line)');
}}
document.querySelectorAll('[data-m]').forEach(b => b.onclick = () => {{
  const m = b.dataset.m;
  if (latched.has(m)) {{ latched.delete(m); rfb && rfb.sendKey(null, m, false); }}
  else {{ latched.add(m); rfb && rfb.sendKey(null, m, true); }}
  paintLatches();
}});
document.querySelectorAll('[data-k]').forEach(b => b.onclick = () => {{
  if (!rfb) return;
  rfb.sendKey(null, b.dataset.k);
  // a latched modifier applies to exactly one key, like a Shift key would
  latched.forEach(m => rfb.sendKey(null, m, false));
  latched.clear(); paintLatches();
}});
document.getElementById('cad').onclick = () => rfb && rfb.sendCtrlAltDel();

document.getElementById('fit').onclick = (e) => {{
  scaling = !scaling;
  if (rfb) {{ rfb.scaleViewport = scaling; rfb.clipViewport = !scaling; }}
  e.target.textContent = scaling ? 'Fit' : '1:1';
  hint();
}};

/* A landscape desktop on a portrait phone is a thin strip however well it is
   scaled. Rather than pretend otherwise, say the one thing that fixes it. */
function hint() {{
  const el = document.getElementById('rotate');
  const portrait = innerHeight > innerWidth;
  el.textContent = portrait
    ? 'rotate your phone for a bigger view · Fit / 1:1 switches to real pixels'
    : '';
  el.classList.toggle('on', portrait && scaling);
}}
addEventListener('resize', hint);
addEventListener('orientationchange', () => setTimeout(hint, 300));

// The on-screen keyboard only appears for a focused text input, so that is what
// we focus; noVNC forwards the key events it produces.
const kbin = document.getElementById('kbin');
document.getElementById('kbd').onclick = () => {{
  kbin.style.pointerEvents = 'auto';
  kbin.focus();
  setTimeout(() => {{ kbin.style.pointerEvents = 'none'; }}, 50);
}};
for (const type of ['keydown', 'keyup']) {{
  kbin.addEventListener(type, (e) => {{
    if (!rfb) return;
    e.preventDefault();
    rfb.sendKey(e.keyCode || null, e.code, type === 'keydown');
  }});
}}
kbin.addEventListener('input', () => {{ kbin.value = ''; }});
</script></body></html>
"""
