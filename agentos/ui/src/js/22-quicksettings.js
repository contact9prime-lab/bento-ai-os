/* ================= quick settings + tray ================= */
/* ============ platform capabilities — the UI never asks "what OS?" ============ */
let PLATFORM={mode:'hosted',detected_mode:'hosted',capabilities:{},summary:''};
async function loadPlatform(){
  try{PLATFORM=await (await fetch('/api/platform')).json()}catch(e){}
  updateBell();
}
function cap(id){return PLATFORM.capabilities?.[id]||{available:false,supported:false,reason:'',component:''}}
function capNote(id){
  const c=cap(id);if(c.available)return '';
  return `<p class="mut" style="margin-top:6px;opacity:.8">${esc(c.reason||'Not available here.')}
    ${c.component?`<button class="endbtn" style="margin-left:6px" onclick="installComponent('${esc(c.component)}')">Install…</button>`:''}</p>`;
}
async function installComponent(id){
  let comp=null;
  try{const d=await (await fetch('/api/components')).json();comp=(d.components||[]).find(c=>c.id===id)}catch(e){}
  if(!comp)return toast('unknown component: '+id);
  if(!await osConfirm(`Install ${comp.title}?`,`Package: ${comp.package} (${comp.method}) · Licence: ${comp.licence}. ${comp.unlocks}`,{confirmText:'Install'}))return;
  toast('installing '+comp.title+'…');
  const r=await fetch('/api/components',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});
  const d=await r.json();
  if(d.ok){toast('✓ '+(d.message||'installed'));loadPlatform().then(()=>{refreshApp('control');refreshApp('syssettings')})}
  else if(d.needs_terminal){
    try{await navigator.clipboard.writeText(d.command)}catch(e){}
    await osAlert(d.message,d.command+'  (copied to the clipboard — paste it into the Terminal app)');
  }else toast(d.message||d.error||'install failed');
}

/* Control Center: the tray popover — same capability-driven content as the
   Quick Settings app, in a menubar-anchored panel instead of a window */
function toggleControlCenter(){
  let p=$('#ccpop');
  if(!p){p=document.createElement('div');p.id='ccpop';document.body.appendChild(p);
    document.addEventListener('click',e=>{
      if(!e.target.closest('#ccpop')&&!e.target.closest('#tray-ctl'))p.classList.remove('show');
    });
  }
  const on=!p.classList.contains('show');
  if(!on){p.classList.remove('show');return}
  $('#powermenu').classList.remove('show');$('#notifpanel').classList.remove('show');
  p.classList.add('show');
  renderControl(p);
  popIn(p,{origin:'top right'});
}

/* ================= Quick Settings (capability-driven) ================= */
async function renderControl(body){
  const d=await (await fetch('/api/control')).json();
  const a=d.audio||{},b=d.battery||{},n=d.network||{};
  const deMode=PLATFORM.mode==='de';
  body.innerHTML=`<div class="pad">
    <div class="provbox"><div class="ptitle">Sound</div>
      <div style="display:flex;align-items:center;gap:10px;margin-top:10px">
        <button class="endbtn" id="c-mute" style="flex:0 0 72px">${a.muted?'Unmute':'Mute'}</button>
        <input type="range" id="c-vol" min="0" max="100" value="${a.volume??50}" style="flex:1">
        <span id="c-voln" class="mut" style="flex:0 0 40px;text-align:right">${a.volume??'–'}%</span>
      </div>
      <div id="c-sinks"></div>
    </div>
    <div class="provbox"><div class="ptitle">Brightness</div><div id="c-bright"><p class="mut" style="margin-top:6px">…</p></div></div>
    <div class="provbox"><div class="ptitle">Network</div>
      <p class="mut" style="margin-top:6px" id="c-net">${n.online?n.connections.map(c=>`${c.type==='wifi'?'Wi-Fi':'wired'} · ${esc(c.name)}`).join(', '):'offline'}</p>
      <div class="row" style="margin-top:8px" id="c-radios"></div>
    </div>
    <div class="provbox"><div class="ptitle">Power</div>
      <p class="mut" style="margin-top:6px">${b.percent!=null?`${b.percent}% · ${esc(b.state||'')}`:'no battery — mains powered'}</p>
      ${b.percent!=null?`<div class="bar" style="margin-top:6px"><i style="width:${b.percent}%" class="${b.percent<20?'hot':''}"></i></div>`:''}
      <div class="row" style="margin-top:8px" id="c-profile"></div>
    </div>
    <div class="provbox"><div class="ptitle">Notifications</div><div class="row" style="margin-top:8px" id="c-dnd"></div></div>
    <div class="row" style="margin-top:4px">
      <button class="endbtn" onclick="openApp('syssettings')">⚙ System Settings</button>
      ${cap('settings.open').available?`<button class="endbtn" onclick="ctlSettings('')">Open ${esc(PLATFORM.platform||'host')} Settings ↗</button>`:''}
      ${cap('screen.capture').available?`<button class="endbtn" onclick="takeScreenshot('full')">📸 Screenshot</button>`:''}
    </div>
  </div>`;
  const vol=$('#c-vol');let vt;
  vol.oninput=()=>{$('#c-voln').textContent=vol.value+'%';clearTimeout(vt);vt=setTimeout(()=>ctlSet({volume:+vol.value}),200)};
  $('#c-mute').onclick=async()=>{await ctlSet({mute:!a.muted});refreshApp('control');updateTray()};

  // output device picker
  const sinks=$('#c-sinks');
  if(cap('audio.devices').available){
    try{
      const ad=await (await fetch('/api/audio/devices')).json();
      if(ad.sinks?.length>1){
        sinks.innerHTML=`<select id="c-sink" style="margin-top:8px;width:100%">${ad.sinks.map(s=>
          `<option value="${s.id}" ${s.default?'selected':''}>${esc(s.description)}</option>`).join('')}</select>`;
        $('#c-sink').onchange=async e=>{await fetch('/api/audio/devices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'default',id:+e.target.value})});toast('✓ audio output switched')};
      }
    }catch(e){}
  }else sinks.innerHTML=capNote('audio.devices');

  // brightness
  const br=$('#c-bright');
  if(cap('brightness.get').available){
    try{
      const bd=await (await fetch('/api/brightness')).json();
      br.innerHTML=(bd.displays||[]).map(disp=>`
        <div style="display:flex;align-items:center;gap:10px;margin-top:8px">
          <span class="mut" style="flex:0 0 110px;overflow:hidden;text-overflow:ellipsis">${esc(disp.monitor||disp.name)}</span>
          <input type="range" min="1" max="100" value="${disp.percent??50}" style="flex:1"
            onchange="setBrightness('${esc(disp.name)}','${disp.kind}',this.value)">
        </div>`).join('')||'<p class="mut" style="margin-top:6px">no adjustable displays</p>';
    }catch(e){br.innerHTML='<p class="mut" style="margin-top:6px">brightness unavailable</p>'}
  }else br.innerHTML=capNote('brightness.set');

  // radios: wifi + bluetooth quick toggles
  const radios=$('#c-radios');let rhtml='';
  if(cap('net.wifi.scan').available)rhtml+=`<button class="endbtn" id="c-wifi">Wi-Fi…</button>`;
  if(cap('bt.status').available)rhtml+=`<button class="endbtn" id="c-bt">Bluetooth…</button>`;
  if(!rhtml)rhtml=cap('settings.open').available?`<button class="endbtn" onclick="ctlSettings('wifi')">Wi-Fi ↗</button><button class="endbtn" onclick="ctlSettings('bluetooth')">Bluetooth ↗</button>`:capNote('net.wifi.join');
  radios.innerHTML=rhtml;
  const wob=$('#c-wifi');if(wob)wob.onclick=()=>{openApp('syssettings');SYS.tab=0;refreshApp('syssettings')};
  const bob=$('#c-bt');if(bob)bob.onclick=()=>{openApp('syssettings');SYS.tab=1;refreshApp('syssettings')};

  // power profile
  const prof=$('#c-profile');
  if(cap('power.profile').available){
    try{
      const p=await (await fetch('/api/power/profile')).json();
      prof.innerHTML=(p.profiles||[]).map(x=>
        `<button class="endbtn ${x===p.active?'on':''}" style="${x===p.active?'border-color:var(--acc,#5eead4)':''}" onclick="setPowerProfile('${esc(x)}')">${esc(x)}</button>`).join('');
    }catch(e){}
  }else prof.innerHTML=capNote('power.profile');

  // DND
  const dnd=$('#c-dnd');
  try{
    const nd=await (await fetch('/api/notifications')).json();
    if(nd.available!==false||PLATFORM.mode==='de')
      dnd.innerHTML=`<button class="endbtn" onclick="toggleDnd(${nd.dnd?'false':'true'})">${nd.dnd?'🔕 Do-not-disturb is ON — turn off':'🔔 Turn on do-not-disturb'}</button>`;
    else dnd.innerHTML=`<p class="mut">${esc(nd.reason||'')}</p>`;
  }catch(e){dnd.innerHTML=''}
}
async function ctlSet(opts){await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(opts)});updateTray()}
async function ctlSettings(panel){const r=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({settings:panel})});const d=await r.json();toast(d.ok?'↗ opened settings':d.message)}
async function setBrightness(name,kind,percent){
  const r=await fetch('/api/brightness',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,kind,percent:+percent})});
  const d=await r.json();if(!d.ok)toast(d.error||'brightness failed');
}
async function setPowerProfile(profile){
  const r=await fetch('/api/power/profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile})});
  const d=await r.json();toast(d.ok?'✓ '+profile:(d.error||'failed'));refreshApp('control');
}
async function toggleDnd(on){
  await fetch('/api/notifications',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'dnd',on})});
  updateBell();refreshApp('control');toast(on?'do-not-disturb on':'do-not-disturb off');
}
async function takeScreenshot(area){
  const r=await fetch('/api/screenshot',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({area})});
  const d=await r.json();toast(d.ok?'📸 saved: '+d.path.split('/').pop():(d.error||'screenshot failed'));
}

