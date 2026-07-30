/* ================= Host Screen =================
   What a remote client cannot otherwise see.

   The AgentOS shell is HTML and travels over HTTP. Native apps are windows the
   compositor paints onto the machine's physical display — different pixels, in a
   different place, never part of the page. So from a phone, a launched app is
   invisible: the taskbar knows it exists (the compositor told the server, and the
   server told this page) but there is nothing to render.

   This app closes that gap the cheap, honest way: it asks the server for a frame
   of the real screen (grim, which the session already ships for screenshots) and
   shows it. A still, refreshed — not a video pipeline, and not a fake remote
   desktop. It answers "did it open, and what is it showing", which is the actual
   question. For controlling that screen, see the note at the bottom of the app. */

const HOSTSCREEN={tick:null,busy:false,every:2000,scale:0.75,fit:true};

async function renderHostScreen(body,w){
  const capable=cap('screen.capture').available;
  body.innerHTML=`<div class="phead">
      <span class="pt">Host screen</span>
      <span class="ps">${esc(hostName())} — the real display, including native apps</span>
      <span class="sp"></span>
      <label class="hs-live"><input type="checkbox" id="hs-live" ${capable?'checked':'disabled'}> live</label>
      <select id="hs-every" ${capable?'':'disabled'}>
        <option value="1000">every 1s</option>
        <option value="2000" selected>every 2s</option>
        <option value="5000">every 5s</option>
        <option value="15000">every 15s</option>
      </select>
      <button class="pact" id="hs-now" ${capable?'':'disabled'}>Refresh</button>
    </div>
    <div class="pbody hs-body">
      ${capable?`<div class="hs-stage"><img id="hs-img" alt="the host machine's screen"></div>
        <div class="hs-foot"><span class="mut" id="hs-stat">loading…</span></div>`
       :`<div class="empty"><div class="eh">${capNote('screen.capture')||
          'Screen capture is not available here — it needs the AgentOS Wayland session and grim.'}</div></div>`}
      <p class="mut hs-note">This is a picture, refreshed — you can see the host screen but not click on
        it. Native windows can still be <b>moved, focused, minimised and closed</b> from the taskbar and the
        Window menu, which go through the compositor and work from anywhere.</p>
      <div id="hs-control" class="provbox"><p class="mut">…</p></div>
    </div>`;
  hsControl();
  if(!capable)return;
  const live=$('#hs-live'), every=$('#hs-every');
  live.onchange=()=>hsLive(live.checked,w);
  every.onchange=()=>{HOSTSCREEN.every=+every.value;if(live.checked)hsLive(true,w)};
  $('#hs-now').onclick=()=>hsFrame(w);
  hsFrame(w);
  hsLive(true,w);
}
/* One frame. `busy` is the point: a capture slower than the refresh interval must
   not stack requests behind itself on a machine that is already busy drawing —
   a late tick is dropped, not queued. */
async function hsFrame(w){
  if(HOSTSCREEN.busy)return;
  const img=$('#hs-img'), stat=$('#hs-stat');
  if(!img)return;                                  // the window was closed
  HOSTSCREEN.busy=true;
  const t0=performance.now();
  try{
    const r=await fetch('/api/screen/frame?scale='+HOSTSCREEN.scale+'&t='+Date.now());
    if(!r.ok){
      const d=await r.json().catch(()=>({}));
      if(stat)stat.textContent=d.error||('capture failed ('+r.status+')');
      HOSTSCREEN.busy=false;return;
    }
    const blob=await r.blob();
    const url=URL.createObjectURL(blob);
    const old=img.dataset.url;
    img.src=url;img.dataset.url=url;
    if(old)URL.revokeObjectURL(old);             // one frame in flight, one in memory
    if(stat)stat.textContent=`${new Date().toLocaleTimeString()} · ${Math.round(performance.now()-t0)}ms · ${(blob.size/1024).toFixed(0)} KB`;
  }catch(e){if(stat)stat.textContent='capture failed: '+e.message}
  HOSTSCREEN.busy=false;
}
/* Live refresh, owned by the window. A full-screen PNG every two seconds is the
   most expensive thing the shell does, so it must not survive the window being
   minimised — winTick guarantees that, and repaints the moment you come back. */
function hsLive(on,w){
  hsStop();
  if(on)HOSTSCREEN.tick=winTick(w,()=>hsFrame(w),HOSTSCREEN.every,{now:false,key:'frame'});
}
function hsStop(){stopTick(HOSTSCREEN.tick);HOSTSCREEN.tick=null}


/* ---- taking control: streaming pixels AND sending input back is remote-desktop
   work, so AgentOS starts wayvnc rather than reinventing it. It binds loopback
   only — wayvnc has no password of its own, and putting an unauthenticated
   remote desktop on the network would undo every other lock in this system. */
async function hsControl(){
  const box=$('#hs-control');if(!box)return;
  let d={};
  try{d=await (await fetch('/api/screen/control')).json()}catch(e){box.innerHTML='';return}
  /* The browser client is what makes this reachable from a phone with nothing
     installed on the phone: AgentOS relays the VNC stream over its own
     authenticated connection, so the VNC port itself never leaves loopback. */
  const web=d.running&&d.novnc
    ? `<div class="rm-addr" style="margin-top:10px"><div class="rm-row">
         <b style="flex:1">Open on this device</b>
         <button class="pact" style="flex:0 0 auto" onclick="openRemoteDesktop()">Remote Desktop ↗</button></div></div>
       <p class="mut" style="margin-top:6px">On your phone, open AgentOS, sign in, and go to
         <code>/remote-desktop</code> — or tap <b>Remote Desktop</b> in Quick Settings. No VNC app needed;
         it runs in the browser over the same passphrase-protected connection.</p>`
    : d.running&&!d.novnc
      ? `<p class="mut" style="margin-top:8px">To use this <b>from a phone browser</b> — no VNC app —
           install the noVNC client (MPL-2.0, a distribution package):</p>
         <button class="endbtn" style="margin-top:8px" onclick="installComponent('novnc')">Install noVNC…</button>`
      : '';
  const body=!d.installed
    ? `<p class="mut" style="margin-top:6px">Not installed. <b>wayvnc</b> (ISC) turns this
         read-only view into a real remote desktop: it streams the screen and sends your
         clicks and keys back to it.</p>
       <button class="pact" style="margin-top:10px" onclick="installComponent('wayvnc')">Install wayvnc…</button>`
    : d.running
      ? `<p class="mut" style="margin-top:6px">Running on <code>${esc(d.host)}:${d.port}</code> — you can use the
           machine, native apps included.</p>${web}
         <p class="mut" style="margin-top:10px">Or point a native VNC client through a tunnel:</p>
         <div class="rm-addr"><div class="rm-row"><code>${esc(d.tunnel)}</code>
           <button class="endbtn" onclick="rmCopy('${esc(d.tunnel)}')">Copy</button></div></div>
         <p class="mut" style="margin-top:8px">${esc(d.note)}</p>
         <button class="endbtn" style="margin-top:10px" onclick="hsControlSet('stop')">Stop remote control</button>`
      : `<p class="mut" style="margin-top:6px">Installed and ready. Start it to control the machine from
           another device — everything on that screen, not just the AgentOS shell.</p>
         <p class="mut">${esc(d.note)}</p>
         ${d.novnc?'<p class="mut">The browser client is installed, so a phone needs nothing at all.</p>'
                  :'<p class="mut">Install <b>noVNC</b> too and it works from a phone browser with no VNC app.</p>'}
         <button class="pact" style="margin-top:10px" onclick="hsControlSet('start')">Start remote control</button>`;
  box.innerHTML=`<div class="ptitle">Take control${d.running?' <span class="rm-pill on">ON</span>':''}</div>${body}`;
}
/* ---- Remote Desktop -------------------------------------------------------
   The real screen, usable, from anywhere — including a phone with nothing
   installed on it. AgentOS relays the VNC stream over its own authenticated
   connection (see agentos/remotedesktop.py), so the VNC port stays on loopback.

   Two ways in, because both are right at different moments:
     · /remote-desktop  a standalone page. On a phone the remote machine should
                        own the whole screen, with no dock drawn over it.
     · this app         a window on the desktop, for using the machine's own
                        screen from another computer alongside everything else.
   On a phone the window IS the screen, so the app gets you the same thing. */
function openRemoteDesktop(){
  // In the session UI, "open a tab" means nothing — there is no browser. Use the
  // app window, which the phone layout already makes full-bleed.
  if((typeof SUI!=='undefined'&&SUI.on)||(typeof isMobile==='function'&&isMobile()))
    return openApp('remotedesk');
  window.open('/remote-desktop','_blank');
}
async function renderRemoteDesk(body,w){
  body.style.cssText='padding:0;height:100%;display:flex;flex-direction:column';
  let d={};
  try{d=await (await fetch('/api/screen/control')).json()}catch(e){}
  if(!d.installed||!d.novnc||!d.running){
    const missing=!d.installed?'wayvnc':(!d.novnc?'novnc':'');
    body.innerHTML=`<div class="pad"><div class="provbox">
      <div class="ptitle">Remote Desktop</div>
      <p class="mut" style="margin-top:6px">Use this machine's real screen — native apps
        included — from your phone or another computer, in a browser. AgentOS relays it over
        the same passphrase-protected connection as the desktop, so the VNC port never leaves
        <code>127.0.0.1</code>.</p>
      ${missing?`<p class="mut" style="margin-top:8px">Needs <b>${esc(missing)}</b>, a distribution
          package AgentOS does not bundle.</p>
        <button class="pact" style="margin-top:10px" onclick="installComponent('${esc(missing)}')">Install ${esc(missing)}…</button>`
       :`<p class="mut" style="margin-top:8px">Everything is installed — the service is just off.</p>
         <button class="pact" style="margin-top:10px" onclick="hsControlSet('start').then(()=>refreshApp('remotedesk'))">Turn Remote Desktop on</button>`}
      <p class="mut" style="margin-top:10px">See also <b>Host Screen</b>, which shows the same
        display as a refreshing picture without needing anything installed.</p>
    </div></div>`;
    return;
  }
  // An iframe, deliberately: the page inside is the same one a phone browser
  // loads, so there is exactly one remote-desktop client to maintain and to fix.
  body.innerHTML=`<iframe src="/remote-desktop" title="Remote Desktop"
     style="border:0;width:100%;height:100%;flex:1;background:#000"
     allow="clipboard-read; clipboard-write"></iframe>`;
}
async function hsControlSet(action){
  const r=await fetch('/api/screen/control',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action})});
  const d=await r.json();
  if(!r.ok)return toast(d.error||'could not change remote control');
  toast(action==='start'?'remote control on — connect a VNC client through the tunnel':'remote control off');
  hsControl();
}
