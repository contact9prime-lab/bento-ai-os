/* ================= SUI: the page, running as the session's desktop =========

   AgentOS has three faces and they are the same code:

     GUI  a window (or tab) on someone else's desktop — macOS, Windows, Linux
     TUI  the terminal client, for a machine with no screen
     SUI  the session UI: this page IS the Linux desktop, drawn by the AgentOS
          session host as a wlr-layer-shell surface on the BACKGROUND layer

   In SUI the page can do two things a web page normally cannot, because the host
   asks the compositor on its behalf (see agentos/shellhost.py):

     struts   reserve the bands the menu bar and dock occupy, so no application
              window can ever cover them — the same mechanism every panel in
              every Linux desktop uses. This is why a maximised native app stops
              above the dock instead of swallowing it.
     raise    come to the front for a moment (Ctrl+Space, a hot corner) by moving
              to the OVERLAY layer, and drop back to BACKGROUND afterwards.

   Loaded early (00-) and declared with `var`, not `let`: device and theme setup
   run before this file in the concatenated bundle and call into it, and a `let`
   read before its own line executes throws instead of being undefined.

   Everything here is a no-op in GUI and TUI. `window.suiCall` only exists when
   the host injected it, so the feature test is the presence of the host, never
   the user agent. */

var SUI = {on: false, top: 0, bottom: 0, raised: false};

function suiActive(){ return !!(window.AGENTOS_SUI && typeof window.suiCall === 'function') }
function suiSend(cmd, args){ if(suiActive()) window.suiCall(cmd, args) }

/* How much vertical space our own chrome needs, measured from the live layout
   rather than hardcoded: themes change the menu bar height, the responsive
   layout changes the dock band, and a phone has different numbers again.
   Measuring means the struts are right for whatever is actually on screen. */
function suiChrome(){
  const h = innerHeight || 900;
  const mb = document.getElementById('menubar');
  const top = mb && mb.offsetHeight ? Math.round(mb.getBoundingClientRect().bottom) : 30;
  let lowest = h;
  for(const id of ['dock', 'omnibar']){
    const el = document.getElementById(id);
    if(!el || !el.offsetHeight) continue;
    const r = el.getBoundingClientRect();
    if(r.height && r.top < lowest) lowest = r.top;
  }
  // A hidden dock (a maximised AgentOS window auto-hides it) must not give back
  // the band — the user peeks it open again, and a strut that came and went
  // would resize every native window on the desktop twice for each peek.
  const bottom = Math.max(0, Math.round(h - lowest));
  return {top: Math.max(0, top), bottom: bottom};
}

var SUI_STRUT_T = 0;
function suiSyncStruts(){
  if(!suiActive()) return;
  clearTimeout(SUI_STRUT_T);
  SUI_STRUT_T = setTimeout(() => {
    const c = suiChrome();
    if(c.top === SUI.top && c.bottom === SUI.bottom) return;   // nothing moved
    SUI.top = c.top; SUI.bottom = c.bottom;
    suiSend('struts', c);
  }, 120);
}

/* Come to the front / go back to being the desktop. In SUI this is a layer
   change, which is atomic; the HTTP fallback is the compositor dance the
   Chromium-rendered session still needs. */
function suiRaise(on){
  if(!suiActive()) return false;
  SUI.raised = on !== false;
  suiSend(SUI.raised ? 'raise' : 'lower');
  document.body.classList.toggle('sui-raised', SUI.raised);
  return true;
}

function suiInit(){
  if(!suiActive()) return;
  SUI.on = true;
  document.body.classList.add('sui');
  // Tell the server, so it stops trying to manage a shell window that no longer
  // exists. Only the host can make this call happen, so it is proof, not a claim.
  fetch('/api/shell/sui', {method: 'POST', headers: {'Content-Type': 'application/json'},
                           body: JSON.stringify({on: true})}).catch(() => {});
  suiSyncStruts();
  // The chrome moves for exactly three reasons: the viewport changed, the theme
  // changed, or the device class changed. All three end up here.
  addEventListener('resize', suiSyncStruts);
  suiSyncStruts();
}
