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

const HOSTSCREEN={timer:null,busy:false,every:2000,scale:0.75,fit:true};

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
/* One frame. Chained rather than on a fixed interval: a slow capture must not
   stack up requests behind itself on a machine that is already busy drawing. */
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
function hsLive(on,w){
  clearTimeout(HOSTSCREEN.timer);HOSTSCREEN.timer=null;
  if(!on)return;
  const tick=async()=>{
    if(!$('#hs-img'))return;                       // window gone — stop for good
    await hsFrame(w);
    HOSTSCREEN.timer=setTimeout(tick,HOSTSCREEN.every);
  };
  HOSTSCREEN.timer=setTimeout(tick,HOSTSCREEN.every);
}
function hsStop(){clearTimeout(HOSTSCREEN.timer);HOSTSCREEN.timer=null}


/* ---- taking control: streaming pixels AND sending input back is remote-desktop
   work, so AgentOS starts wayvnc rather than reinventing it. It binds loopback
   only — wayvnc has no password of its own, and putting an unauthenticated
   remote desktop on the network would undo every other lock in this system. */
async function hsControl(){
  const box=$('#hs-control');if(!box)return;
  let d={};
  try{d=await (await fetch('/api/screen/control')).json()}catch(e){box.innerHTML='';return}
  const body=!d.installed
    ? `<p class="mut" style="margin-top:6px">Not installed. <b>wayvnc</b> (ISC) turns this
         read-only view into a real remote desktop: it streams the screen and sends your
         clicks and keys back to it.</p>
       <button class="pact" style="margin-top:10px" onclick="installComponent('wayvnc')">Install wayvnc…</button>`
    : d.running
      ? `<p class="mut" style="margin-top:6px">Running on <code>${esc(d.host)}:${d.port}</code> — point any VNC
           client at it and you can use the machine, native apps included.</p>
         <div class="rm-addr"><div class="rm-row"><code>${esc(d.tunnel)}</code>
           <button class="endbtn" onclick="rmCopy('${esc(d.tunnel)}')">Copy</button></div></div>
         <p class="mut" style="margin-top:8px">${esc(d.note)}</p>
         <button class="endbtn" style="margin-top:10px" onclick="hsControlSet('stop')">Stop remote control</button>`
      : `<p class="mut" style="margin-top:6px">Installed and ready. Start it to control the machine from
           another device — everything on that screen, not just the AgentOS shell.</p>
         <p class="mut">${esc(d.note)}</p>
         <button class="pact" style="margin-top:10px" onclick="hsControlSet('start')">Start remote control</button>`;
  box.innerHTML=`<div class="ptitle">Take control${d.running?' <span class="rm-pill on">ON</span>':''}</div>${body}`;
}
async function hsControlSet(action){
  const r=await fetch('/api/screen/control',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action})});
  const d=await r.json();
  if(!r.ok)return toast(d.error||'could not change remote control');
  toast(action==='start'?'remote control on — connect a VNC client through the tunnel':'remote control off');
  hsControl();
}
