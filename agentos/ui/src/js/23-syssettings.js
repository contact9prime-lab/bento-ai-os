/* ================= System Settings (the DE's own control center) ================= */
const SYS={tab:0};
const SYS_TABS=['Network','Bluetooth','Displays','Sound','Power','Session','Components'];
function sysTab(i){SYS.tab=i;refreshApp('syssettings')}
async function renderSysSettings(body){
  body.innerHTML=`<div class="pad">
    <div style="margin-bottom:10px">${segTabs('sys-tabs',SYS_TABS,SYS.tab,'sysTab')}</div>
    <div id="sys-body"><p class="mut">…</p></div></div>`;
  const el=$('#sys-body');
  try{
    await [sysNet,sysBt,sysDisplays,sysSound,sysPower,sysSession,sysComponents][SYS.tab](el);
  }catch(e){el.innerHTML=`<p class="mut">${esc(String(e))}</p>`}
}
function sigBars(s){return s>75?'▂▄▆█':s>50?'▂▄▆':s>25?'▂▄':'▂'}
async function sysNet(el){
  if(!cap('net.wifi.scan').available){el.innerHTML=`<div class="provbox"><div class="ptitle">Wi-Fi</div>${capNote('net.wifi.scan')||'<p class="mut" style="margin-top:6px">unavailable</p>'}</div>`;return}
  el.innerHTML='<p class="mut">scanning…</p>';
  const d=await (await fetch('/api/net/wifi')).json();
  if(d.error){el.innerHTML=`<p class="mut">${esc(d.error)}</p>`;return}
  el.innerHTML=`<div class="provbox"><div class="ptitle">Wi-Fi</div>
    <div class="row" style="margin-top:8px">
      <button class="endbtn" onclick="wifiAct({action:'${d.wifi_enabled?'disable':'enable'}'})">${d.wifi_enabled?'Turn Wi-Fi off':'Turn Wi-Fi on'}</button>
      <button class="endbtn" onclick="wifiAct({action:'airplane',on:true})">✈ Airplane mode</button>
      <button class="endbtn" onclick="refreshApp('syssettings')">↻ Rescan</button>
    </div></div>
    ${(d.networks||[]).map(n=>`<div class="provbox" style="display:flex;align-items:center;gap:10px">
      <span style="flex:0 0 44px;letter-spacing:1px" title="${n.signal}%">${sigBars(n.signal)}</span>
      <div style="flex:1;min-width:0">
        <div style="font-weight:${n.connected?'700':'500'}">${esc(n.ssid)} ${n.connected?'<span class="mut">· connected</span>':''}</div>
        <div class="mut" style="font-size:11px">${esc(n.security)}${n.saved?' · saved':''}</div>
      </div>
      ${n.connected?'':`<button class="endbtn" onclick="wifiJoin('${esc(n.ssid).replace(/'/g,"\\'")}','${n.security}',${n.saved})">Join</button>`}
      ${n.saved?`<button class="endbtn" onclick="wifiAct({action:'forget',ssid:'${esc(n.ssid).replace(/'/g,"\\'")}'})">Forget</button>`:''}
    </div>`).join('')||'<p class="mut">no networks in range</p>'}`;
}
async function wifiJoin(ssid,security,saved){
  let psk=null;
  if(!saved&&security!=='open'){psk=await osPrompt(`Password for "${ssid}" (${security})`,{password:true,confirmText:'Join'});if(psk===null)return}
  toast('joining '+ssid+'…');
  await wifiAct({action:'join',ssid,psk});
}
async function wifiAct(body){
  const r=await fetch('/api/net/wifi',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json();
  toast(d.ok?'✓ '+(body.action||'done'):(d.error||'failed'));
  setTimeout(()=>refreshApp('syssettings'),800);updateTray();
}
async function sysBt(el){
  if(!cap('bt.status').available){el.innerHTML=`<div class="provbox"><div class="ptitle">Bluetooth</div>${capNote('bt.status')||'<p class="mut" style="margin-top:6px">unavailable</p>'}</div>`;return}
  const d=await (await fetch('/api/bt')).json();
  if(d.error){el.innerHTML=`<p class="mut">${esc(d.error)}</p>`;return}
  const ad=(d.adapters||[])[0];
  el.innerHTML=`<div class="provbox"><div class="ptitle">Bluetooth</div>
    ${ad?`<div class="row" style="margin-top:8px">
      <button class="endbtn" onclick="btAct({action:'power',adapter:'${ad.path}',on:${!ad.powered}})">${ad.powered?'Turn off':'Turn on'}</button>
      <button class="endbtn" onclick="btAct({action:'discover',adapter:'${ad.path}',on:${!ad.discovering}})">${ad.discovering?'Stop scanning':'Scan for devices'}</button>
    </div>`:'<p class="mut" style="margin-top:6px">no adapter</p>'}</div>
    ${(d.devices||[]).map(dev=>`<div class="provbox" style="display:flex;align-items:center;gap:10px">
      <div style="flex:1;min-width:0">
        <div style="font-weight:${dev.connected?'700':'500'}">${esc(dev.name)}
          ${dev.connected?'<span class="mut">· connected</span>':dev.paired?'<span class="mut">· paired</span>':''}
          ${dev.battery!=null?`<span class="mut">· 🔋${dev.battery}%</span>`:''}</div>
        <div class="mut" style="font-size:11px">${esc(dev.address)}</div>
      </div>
      ${dev.connected?`<button class="endbtn" onclick="btAct({action:'disconnect',device:'${dev.path}'})">Disconnect</button>`
        :dev.paired?`<button class="endbtn" onclick="btAct({action:'connect',device:'${dev.path}'})">Connect</button>`
        :`<button class="endbtn" onclick="btAct({action:'pair',device:'${dev.path}'})">Pair</button>`}
      ${dev.paired?`<button class="endbtn" onclick="btRemove('${dev.path}','${esc(dev.name).replace(/'/g,"\\'")}')">✕</button>`:''}
    </div>`).join('')||'<p class="mut">no devices — scan to discover nearby ones</p>'}`;
}
async function btRemove(path,name){
  if(!await osConfirm('Remove '+name+'?','',{danger:true,confirmText:'Remove'}))return;
  btAct({action:'remove',device:path});
}
async function btAct(body){
  const r=await fetch('/api/bt',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json();
  toast(d.ok?'✓ '+body.action:(d.error||'failed'));
  setTimeout(()=>refreshApp('syssettings'),900);
}
async function sysDisplays(el){
  if(!cap('display.configure').available){el.innerHTML=`<div class="provbox"><div class="ptitle">Displays</div>${capNote('display.configure')||'<p class="mut" style="margin-top:6px">unavailable</p>'}</div>`;return}
  const d=await (await fetch('/api/wm/outputs')).json();
  if(!d.available){el.innerHTML=`<p class="mut">${esc(d.reason||'unavailable')}</p>`;return}
  el.innerHTML=(d.outputs||[]).map(o=>{
    const modes=(o.modes||[]).map(m=>{
      const v=`${m.width}x${m.height}@${Math.round((m.refresh||0)/1000)}Hz`;
      const on=o.mode&&m.width===o.mode.width&&m.height===o.mode.height&&Math.round((m.refresh||0)/1000)===Math.round((o.mode.refresh||0)/1000);
      return `<option value="${v}" ${on?'selected':''}>${v}</option>`}).join('');
    return `<div class="provbox"><div class="ptitle">${esc(o.name)} ${o.active?'':'· off'} <span class="mut">${esc([o.make,o.model].filter(Boolean).join(' '))}</span></div>
      <div class="row" style="margin-top:8px;align-items:center;gap:8px;flex-wrap:wrap">
        <select onchange="outCfg('${esc(o.name)}',{mode:this.value})">${modes}</select>
        <select onchange="outCfg('${esc(o.name)}',{scale:+this.value})">
          ${[1,1.25,1.5,1.75,2].map(s=>`<option value="${s}" ${Math.abs((o.scale||1)-s)<.01?'selected':''}>${s*100}%</option>`).join('')}</select>
        <select onchange="outCfg('${esc(o.name)}',{transform:this.value})">
          ${['normal','90','180','270'].map(t=>`<option ${o.transform===t?'selected':''}>${t}</option>`).join('')}</select>
        <button class="endbtn" onclick="outCfg('${esc(o.name)}',{enabled:${!o.active}})">${o.active?'Turn off':'Turn on'}</button>
      </div></div>`}).join('')||'<p class="mut">no outputs reported</p>';
}
async function outCfg(name,opts){
  const r=await fetch('/api/wm/outputs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,...opts})});
  const d=await r.json();toast(d.ok?'✓ display updated':(d.message||d.error||'failed'));
  setTimeout(()=>refreshApp('syssettings'),600);
}
async function sysSound(el){
  const d=await (await fetch('/api/audio/devices')).json().catch(()=>null);
  if(!d||d.error){el.innerHTML=`<div class="provbox"><div class="ptitle">Sound</div>${capNote('audio.devices')||`<p class="mut" style="margin-top:6px">${esc(d?.error||'unavailable')}</p>`}</div>`;return}
  el.innerHTML=`<div class="provbox"><div class="ptitle">Output devices</div>
    ${(d.sinks||[]).map(s=>`<div class="row" style="margin-top:8px;align-items:center">
      <button class="endbtn" style="${s.default?'border-color:var(--acc,#5eead4)':''}" onclick="audioDefault(${s.id})">${s.default?'✓ ':''}${esc(s.description)}</button>
    </div>`).join('')||'<p class="mut" style="margin-top:6px">none</p>'}</div>
  <div class="provbox"><div class="ptitle">Input devices</div>
    ${(d.sources||[]).map(s=>`<div class="row" style="margin-top:8px"><button class="endbtn" style="${s.default?'border-color:var(--acc,#5eead4)':''}" onclick="audioDefault(${s.id})">${s.default?'✓ ':''}${esc(s.description)}</button></div>`).join('')||'<p class="mut" style="margin-top:6px">none</p>'}</div>
  <div class="provbox"><div class="ptitle">App volumes</div>
    ${(d.streams||[]).map(s=>`<div style="display:flex;align-items:center;gap:10px;margin-top:8px">
      <span class="mut" style="flex:0 0 130px;overflow:hidden;text-overflow:ellipsis">${esc(s.app)}</span>
      <input type="range" min="0" max="100" value="70" style="flex:1" onchange="audioVol(${s.id},this.value)">
    </div>`).join('')||'<p class="mut" style="margin-top:6px">nothing playing</p>'}</div>`;
}
async function audioDefault(id){await fetch('/api/audio/devices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'default',id})});toast('✓ default changed');setTimeout(()=>refreshApp('syssettings'),400)}
async function audioVol(id,percent){await fetch('/api/audio/devices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'volume',id,percent:+percent})})}
async function sysPower(el){
  const c=await (await fetch('/api/control')).json();
  const b=c.battery||{};
  let profHtml='';
  if(cap('power.profile').available){
    try{const p=await (await fetch('/api/power/profile')).json();
      profHtml=(p.profiles||[]).map(x=>`<button class="endbtn" style="${x===p.active?'border-color:var(--acc,#5eead4)':''}" onclick="setPowerProfile('${esc(x)}')">${x===p.active?'✓ ':''}${esc(x)}</button>`).join('');
    }catch(e){}
  }else profHtml=capNote('power.profile');
  el.innerHTML=`<div class="provbox"><div class="ptitle">Battery</div>
      <p class="mut" style="margin-top:6px">${b.percent!=null?`${b.percent}% · ${esc(b.state||'')}`:'no battery — mains powered'}</p></div>
    <div class="provbox"><div class="ptitle">Performance profile</div><div class="row" style="margin-top:8px">${profHtml}</div></div>
    <div class="provbox"><div class="ptitle">Session power</div>
      <div class="row" style="margin-top:8px">
        <button class="endbtn" onclick="powerDo('lock','Lock the screen?')">🔒 Lock</button>
        <button class="endbtn" onclick="powerDo('suspend','Suspend the machine?')">🌙 Suspend</button>
      </div>
      <p class="mut" style="margin-top:8px">Idle timers for the AgentOS session live in config
      (<code>desktop.idle_lock_secs</code>, <code>desktop.idle_screen_off_secs</code>) —
      re-run <code>agentos install-session</code> after changing them.</p></div>`;
}
async function sysSession(el){
  const modes=PLATFORM.modes||['auto','de','hosted','kiosk'];
  const cfg=await (await fetch('/api/config')).json();
  const pin=cfg.desktop?.mode||'auto';
  el.innerHTML=`<div class="provbox"><div class="ptitle">Desktop mode</div>
      <p class="mut" style="margin-top:6px">${esc(PLATFORM.summary||'')} (running: <b>${esc(PLATFORM.mode)}</b>, detected: ${esc(PLATFORM.detected_mode)})</p>
      <div class="row" style="margin-top:8px">${modes.map(m=>
        `<button class="endbtn" style="${m===pin?'border-color:var(--acc,#5eead4)':''}" onclick="pinMode('${m}')">${m===pin?'✓ ':''}${m}</button>`).join('')}</div>
      <p class="mut" style="margin-top:8px">"auto" follows how you logged in. Pinning takes effect on the next server start.</p></div>
    <div class="provbox"><div class="ptitle">AgentOS as your desktop</div>
      <p class="mut" style="margin-top:6px">Install AgentOS as a login session — it appears next to Ubuntu at the login
      screen and changes nothing else. Run in the Terminal:</p>
      <p style="margin-top:6px"><code>agentos install-session</code> — selectable Wayland session (needs sway)</p>
      <p style="margin-top:4px"><code>agentos install-session --autologin</code> — boot straight into AgentOS</p>
      <p class="mut" style="margin-top:6px">Escape hatch, always: <b>Ctrl+Alt+F3</b> for a raw terminal, then
      <code>agentos install-session --remove --autologin</code>. Switching back is just logging out and picking Ubuntu.</p></div>`;
}
async function pinMode(mode){
  const cfg=await (await fetch('/api/config')).json();
  cfg.desktop={...(cfg.desktop||{}),mode};
  await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});
  toast('desktop.mode = '+mode+' (takes effect on next server start)');refreshApp('syssettings');
}
async function sysComponents(el){
  const d=await (await fetch('/api/components')).json();
  el.innerHTML=(d.components||[]).map(c=>`<div class="provbox" style="display:flex;align-items:center;gap:10px">
      <div style="flex:1;min-width:0">
        <div style="font-weight:600">${esc(c.title)} <span class="mut" style="font-weight:400">· ${esc(c.licence)}</span></div>
        <div class="mut" style="font-size:11.5px;margin-top:2px">${esc(c.unlocks)}</div>
      </div>
      ${c.installed?'<span class="mut">✓ installed</span>':`<button class="endbtn" onclick="installComponent('${c.id}')">Install…</button>`}
    </div>`).join('');
  el.innerHTML+=`<p class="mut" style="margin-top:4px">These aren't bundled with AgentOS — some carry other licences
    (shown above), so each one installs only when you say yes to it.</p>`;
}

