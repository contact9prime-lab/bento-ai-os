/* ================= System Settings (the DE's own control center) ================= */
const SYS={tab:0};
const SYS_TABS=['Network','Remote access','Bluetooth','Displays','Keyboard & Mouse','Sound','Power','Session','Components'];
function sysTab(i){SYS.tab=i;refreshApp('syssettings')}
async function renderSysSettings(body){
  body.innerHTML=`<div class="pad">
    <div style="margin-bottom:10px">${segTabs('sys-tabs',SYS_TABS,SYS.tab,'sysTab')}</div>
    <div id="sys-body"><p class="mut">…</p></div></div>`;
  const el=$('#sys-body');
  try{
    await [sysNet,sysRemote,sysBt,sysDisplays,sysInput,sysSound,sysPower,sysSession,sysComponents][SYS.tab](el);
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
  el.insertAdjacentHTML('beforeend',await nightLightBox());
}
/* Night light: the display setting you notice by feeling tired rather than by
   looking at a panel. Off unless asked for; warmth and hours are the user's. */
async function nightLightBox(){
  const d=await (await fetch('/api/nightlight')).json().catch(()=>null);
  if(!d)return '';
  const n=d.nightlight||{};
  if(!d.available)return `<div class="provbox"><div class="ptitle">Night light</div>
    <p class="mut" style="margin-top:6px">${esc(d.reason)}</p></div>`;
  return `<div class="provbox"><div class="ptitle">Night light</div>
    <div class="row" style="margin-top:8px;align-items:center;gap:10px;flex-wrap:wrap">
      <label class="psw"><input type="checkbox" id="nl-on" ${n.enabled?'checked':''} onchange="saveNightLight()"><i></i></label>
      <span class="mut">Warm the screen after dark</span>
      <span style="flex:1"></span>
      <label class="mut">from <input id="nl-from" type="time" value="${esc(n.from||'20:00')}" onchange="saveNightLight()"></label>
      <label class="mut">to <input id="nl-to" type="time" value="${esc(n.to||'06:30')}" onchange="saveNightLight()"></label>
      <label class="mut">warmth
        <select id="nl-temp" onchange="saveNightLight()">
          ${[[5000,'subtle'],[4500,'gentle'],[4000,'warm'],[3400,'warmer'],[2800,'candlelight']].map(([k,t])=>
            `<option value="${k}" ${(+n.night_temp||4000)===k?'selected':''}>${t}</option>`).join('')}
        </select></label>
    </div></div>`;
}
async function saveNightLight(){
  const body={enabled:$('#nl-on').checked,from:$('#nl-from').value,to:$('#nl-to').value,
    night_temp:+$('#nl-temp').value,day_temp:6500};
  const r=await fetch('/api/nightlight',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json();toast(d.message||'saved');
}
async function outCfg(name,opts){
  const r=await fetch('/api/wm/outputs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,...opts})});
  const d=await r.json();toast(d.ok?'✓ display updated':(d.message||d.error||'failed'));
  setTimeout(()=>refreshApp('syssettings'),600);
}
async function sysInput(el){
  const d=await (await fetch('/api/input')).json().catch(()=>null);
  if(!d){el.innerHTML='<p class="mut">could not read input settings</p>';return}
  const kb=d.input.keyboard||{}, tp=d.input.touchpad||{};
  const chk=(id,on,label,hint)=>`<div class="prow"><div class="pl"><b>${esc(label)}</b>${hint?`<small>${esc(hint)}</small>`:''}</div>
    <div class="pc"><label class="psw"><input type="checkbox" id="${id}" ${on?'checked':''}><i></i></label></div></div>`;
  el.innerHTML=`<div class="pgroup"><h3>Keyboard</h3>
      <div class="prow"><div class="pl"><b>Layout</b><small>Which letters your keys type.</small></div>
        <div class="pc"><select id="in-layout">${['',...d.layouts].map(l=>
          `<option value="${esc(l)}" ${(kb.layout||'')===l?'selected':''}>${l?esc(l):'system default'}</option>`).join('')}</select>
        <input id="in-variant" placeholder="variant (optional)" value="${esc(kb.variant||'')}" style="max-width:170px"></div></div>
      <div class="prow"><div class="pl"><b>Repeat delay</b><small>Milliseconds before a held key repeats.</small></div>
        <div class="pc"><input type="number" id="in-delay" value="${kb.repeat_delay||300}"></div></div>
      <div class="prow"><div class="pl"><b>Repeat rate</b><small>Repeats per second once it starts.</small></div>
        <div class="pc"><input type="number" id="in-rate" value="${kb.repeat_rate||30}"></div></div>
    </div>
    <div class="pgroup"><h3>Touchpad &amp; pointer</h3>
      ${chk('in-tap',tp.tap!==false,'Tap to click','A tap counts as a click.')}
      ${chk('in-nat',tp.natural_scroll!==false,'Natural scrolling','Content follows your fingers.')}
      ${chk('in-dwt',tp.dwt!==false,'Disable while typing','Ignore the touchpad mid-sentence.')}
      <div class="prow"><div class="pl"><b>Pointer speed</b><small>-1 slowest · 0 default · 1 fastest.</small></div>
        <div class="pc"><input type="number" step="0.1" min="-1" max="1" id="in-accel" value="${tp.accel??0}"></div></div>
      <div class="prow"><div class="pl"><b></b><small>${d.session?'Changes apply to this session immediately.':'Saved now; applied when you log into the AgentOS session.'}</small></div>
        <div class="pc"><button class="pact" onclick="saveInput()">Save</button></div></div>
    </div>`;
}
async function saveInput(){
  const body={keyboard:{layout:$('#in-layout').value,variant:$('#in-variant').value.trim(),
      repeat_delay:+$('#in-delay').value||300,repeat_rate:+$('#in-rate').value||30},
    touchpad:{tap:$('#in-tap').checked,natural_scroll:$('#in-nat').checked,
      dwt:$('#in-dwt').checked,accel:+$('#in-accel').value||0}};
  const r=await fetch('/api/input',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json();toast(d.message||'input settings saved');
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
        ${USERS.lock&&!suiActive()
          ? `<button class="endbtn" title="your password brings it back" onclick="lockDesktop()">🔒 Lock desktop</button>`:''}
        <button class="endbtn" onclick="powerDo('lock','Lock the screen?')">🔒 Lock screen</button>
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
/* Components, grouped by how much the machine needs them, and honest about the
   distro it is actually running on. The server resolves package names per
   distro family, so `c.package` and `c.command` here are what would really run
   — not a Debian command shown to a Fedora user. When there is no route to a
   component at all, `c.available` is false and `c.reason` says why: a sentence
   beats a button that cannot work. */
const COMPGROUPS=[['required','Required','Without these there is no AgentOS session.'],
                  ['recommended','Recommended','A desktop that behaves like one.'],
                  ['optional','Optional','']];
async function sysComponents(el){
  const d=await (await fetch('/api/components')).json();
  const rows=d.components||[], os=d.os||{};
  const head=`<div class="provbox"><div class="ptitle">This machine</div>
    <p class="mut" style="margin-top:6px">${esc(os.describe||'unknown system')}</p>
    ${os.why?`<p class="mut" style="margin-top:4px">${esc(os.why)}</p>`:''}</div>`;
  const card=c=>`<div class="provbox" style="display:flex;align-items:center;gap:10px">
      <div style="flex:1;min-width:0">
        <div style="font-weight:600">${esc(c.title)} <span class="mut" style="font-weight:400">· ${esc(c.licence)}</span></div>
        <div class="mut" style="font-size:11.5px;margin-top:2px">${esc(c.unlocks)}</div>
        ${c.available&&!c.installed?`<div class="mut" style="font-size:11px;margin-top:3px;font-family:monospace">${esc(c.command)}</div>`:''}
      </div>
      ${c.installed?'<span class="mut">✓ installed</span>'
        :c.available?`<button class="endbtn" onclick="installComponent('${c.id}')">Install…</button>`
        :`<span class="mut" style="max-width:200px;text-align:right;font-size:11.5px">${esc(c.reason||'unavailable here')}</span>`}
    </div>`;
  el.innerHTML=head+COMPGROUPS.map(([g,label,note])=>{
    const mine=rows.filter(c=>c.group===g); if(!mine.length)return '';
    const miss=mine.filter(c=>!c.installed&&c.available).length;
    return `<div class="ptitle" style="margin-top:10px">${label}
        <span class="mut" style="font-weight:400">${miss?`· ${miss} missing`:'· all present'}</span></div>
      ${note?`<p class="mut" style="font-size:11.5px;margin:2px 0 6px">${note}</p>`:''}
      ${mine.map(card).join('')}`;
  }).join('');
  el.innerHTML+=`<p class="mut" style="margin-top:4px">These aren't bundled with AgentOS — some carry other licences
    (shown above), so each one installs only when you say yes to it. From a terminal: <code>agentos installer</code>.</p>`;
}


/* ================= Remote access =================
   Reach this desktop from your phone. Off until a human turns it on here and
   sets a passphrase — and the server only accepts this call from the machine
   itself, so nothing signed in remotely (and no agent, and no app) can widen
   its own access. */
let REMOTE={};
/* Where this machine can be reached from — a live probe of Tailscale and any
   tunnel provider, not config. Kept beside REMOTE because the addresses are
   only meaningful once remote access is on. */
let TUNNEL={};
async function sysRemote(el){
  try{REMOTE=await (await fetch('/api/remote')).json()}catch(e){REMOTE={}}
  try{TUNNEL=await (await fetch('/api/tunnel')).json()}catch(e){TUNNEL={}}
  const on=!!REMOTE.enabled, set=!!REMOTE.configured,
        byAccounts=REMOTE.lock==='accounts';   // the accounts ARE the lock — see remote.py
  el.innerHTML=`
    <div class="provbox">
      <div class="ptitle">Remote access
        <span class="rm-pill ${on?'on':''}">${on?'ON':'off'}</span></div>
      <p class="mut" style="margin-top:8px;line-height:1.6">
        Serve this desktop to your phone or another machine on your network.
        <b>Everything you can do here, whoever signs in can do too</b> — including the
        Terminal and the agent's shell — so it stays off until there is a lock on it.
        Using AgentOS on this machine is unaffected either way.</p>

      ${/* Accounts ARE the lock. Offering a second, shared passphrase in front of
            per-person credentials would make "sign in" mean two different things
            depending on where somebody was standing. */''}
      ${byAccounts?`<div class="rm-lock">
        <b>Locked by this machine's accounts.</b>
        Everyone signs in from their phone with the <b>same username and password</b>
        they use here, and lands in their own desktop — their memory, their agents,
        their channels. No separate remote passphrase to invent, share or forget.
        <button class="endbtn" style="margin-top:8px" onclick="openApp('users')">Manage accounts</button>
      </div>`:`
      <label style="margin-top:14px">${set?'Change the passphrase':'Set a passphrase'}</label>
      <div class="row" style="gap:8px">
        <input id="rm-pw" type="password" autocomplete="new-password"
               placeholder="at least 8 characters — a phrase beats a word" style="flex:1">
        <button class="endbtn" onclick="rmSetPass()">${set?'Update':'Set'}</button>
      </div>
      ${set?'<p class="mut" style="margin-top:6px;font-size:11px">A passphrase is set. Changing it signs every remote device out.</p>':''}
      <p class="mut" style="margin-top:6px;font-size:11px">Or add user accounts in
        <a href="#" onclick="openApp('users');return false">Users</a> — they lock this
        themselves, and give each person their own desktop.</p>`}

      <div class="row" style="margin-top:16px;gap:10px;align-items:center">
        <button class="save" style="margin:0;width:auto;padding:10px 18px${on?';background:var(--err);color:#fff':''}"
                onclick="rmToggle(${on?'false':'true'})" ${set?'':'disabled title="set a passphrase or add accounts first"'}>
          ${on?'Turn remote access off':'Turn remote access on'}</button>
        <span class="mut" style="font-size:12px">${set?'':'it needs a lock first — a passphrase, or accounts'}</span>
      </div>
    </div>

    ${on?`<div class="provbox">
      <div class="ptitle">Reach it from your phone</div>
      ${(TUNNEL.reachable||[]).length?`<div class="rm-addr">${TUNNEL.reachable.map(a=>`
          <div class="rm-row"><code>${esc(a.url)}</code>
            <span class="rm-via ${a.via==='Tailscale'?'far':''}">${esc(a.via)} · ${esc(a.who)}</span>
            <button class="endbtn" onclick="rmCopy('${esc(a.url)}')">Copy</button></div>`).join('')}</div>`
        :(REMOTE.addresses||[]).length?`<div class="rm-addr">${REMOTE.addresses.map(a=>`
          <div class="rm-row"><code>${esc(a)}</code>
            <button class="endbtn" onclick="rmCopy('${esc(a)}')">Copy</button></div>`).join('')}</div>`
        :'<p class="mut" style="margin-top:6px">No network address detected.</p>'}
    ${/* The LAN list alone made a machine that was already reachable from
          anywhere look like it only worked in the same room. If there is a
          tunnel provider, say what it would add and what it still needs. */''}
    ${/* If nothing here reaches beyond this Wi-Fi, that is the thing to say — and
          then offer the fix, rather than leaving "remote access" quietly meaning
          "same room only". This is the OS handling it instead of the user
          discovering that a tunnel is a thing that exists. */''}
    ${!(TUNNEL.reachable||[]).some(a=>a.via!=='This network')?`
      <div class="rm-offer">
        <b>Only reachable on this network.</b>
        To open AgentOS from anywhere — a phone on mobile data, a laptop elsewhere —
        this machine needs an address of its own. AgentOS can set one up.
      </div>`:''}
    ${(TUNNEL.providers||[]).filter(p=>p.available||p.install).map(p=>`
      <p class="mut" style="margin-top:8px;line-height:1.6">
        <b>${esc(p.title)}</b> — ${esc(p.what||'')}
        ${p.available?(p.needs?`<br><span style="color:var(--warn)">${esc(p.needs)}</span>${
            p.needs_url?` <button class="endbtn" onclick="openInBrowser('${esc(p.needs_url)}')">Open</button>`:''}`
          :'<br>ready to publish a proper https:// address.')
         :`<br>${esc(p.reason||'')}${p.install_cmd?`
            <br><span class="mut">${esc(p.install_note||'')}</span>
            <br><code class="rm-cmd">${esc(p.install_cmd)}</code>
            <br><button class="endbtn" id="tun-inst-${esc(p.id)}"
                 onclick="tunInstall('${esc(p.id)}')">Install ${esc(p.title)}</button>`
           :''}${p.install?` <button class="endbtn" onclick="openInBrowser('${esc(p.install)}')">Docs</button>`:''}`}</p>`).join('')}
    ${(TUNNEL.published&&TUNNEL.url)?`<div class="rm-offer live">
        <b>Published${TUNNEL.kind==='public'?' to the internet':''}:</b>
        <code>${esc(TUNNEL.url)}</code>
        <button class="endbtn" onclick="rmCopy('${esc(TUNNEL.url)}')">Copy</button>
        <button class="endbtn" onclick="tunStop()">Stop</button></div>`
      :(TUNNEL.providers||[]).some(p=>p.available&&!p.needs)?`
        <p class="mut" style="margin-top:8px">
          <button class="endbtn" onclick="tunStart()">Publish an address for anywhere</button></p>`:''}
      <p class="mut" style="margin-top:10px;line-height:1.6">
        Open that on your phone, sign in ${byAccounts?'with your username and password':'with the passphrase'}, then
        <b>Share → Add to Home Screen</b> (iOS) or <b>⋮ → Install app</b> (Android) for a
        full-screen app with no browser chrome. The layout adapts to the phone on its own.</p>
      ${REMOTE.listening_on&&REMOTE.listening_on!=='127.0.0.1'?'':
        '<p class="mut" style="margin-top:8px;color:var(--warn)">Restart AgentOS for this to take effect — it is still listening on loopback only.</p>'}
    </div>`:''}

    <div class="provbox">
      <div class="ptitle">Before you open it up</div>
      <ul class="rm-notes">
        <li>${byAccounts
          ?'Signing in gets somebody <b>their own desktop</b> — their memory, their agents, their channels. It does not sandbox them from the <b>machine</b>: an executor still has the Terminal and the agent\'s shell.'
          :'This is <b>one shared passphrase for one machine</b>, not per-user accounts. Treat it like the key to the machine, because it is. Adding accounts in Users changes that.'}</li>
        <li>Keep it on your <b>home network or a VPN</b>. Don't port-forward it to the open internet — there is no TLS here, so a passphrase would cross the network in the clear.</li>
        <li>Over the internet, put it behind something that terminates TLS and authenticates — Tailscale, WireGuard, or a reverse proxy you trust.</li>
        <li>Sign-in attempts back off after ${5} failures from one address, and every attempt is written to the Logs app.</li>
      </ul>
    </div>`;
}
async function rmPost(body){
  const r=await fetch('/api/remote',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body)});
  const d=await r.json();
  if(!r.ok){toast(d.error||'could not change remote access');return null}
  return d;
}
async function rmSetPass(){
  const pw=$('#rm-pw').value;
  if(!pw)return toast('type a passphrase first');
  if(await rmPost({passphrase:pw})){toast('✓ passphrase set');refreshApp('syssettings')}
}
async function rmToggle(on){
  if(on&&!await osConfirm('Turn remote access on?',
      'Anyone on your network who has the passphrase gets this desktop — including the Terminal and the agent’s shell. Keep it off the open internet.',
      {confirmText:'Turn it on',danger:true}))return;
  const d=await rmPost({enabled:on});
  if(!d)return;
  toast(on?'remote access on — restart AgentOS to start listening':'remote access off');
  refreshApp('syssettings');
}
function rmCopy(a){navigator.clipboard.writeText(a).then(()=>toast('copied: '+a),()=>toast(a))}

/* ---- tunnels: the OS setting up its own way in ----
   Installing is a visible act with the command shown first, and publishing to
   the public internet is confirmed rather than assumed — "reachable from
   anywhere" and "reachable by anyone" are different promises. */
async function tunInstall(id){
  const btn=document.getElementById('tun-inst-'+id);
  if(btn){btn.disabled=true;btn.textContent='Installing…'}
  try{
    const r=await fetch('/api/tunnel',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'install',provider:id})});
    const d=await r.json();
    toast(d.ok?'✓ '+(d.message||'installed'):(d.message||'could not install'));
    if(d.ok)refreshApp('syssettings');
  }catch(e){toast('could not reach the server')}
  finally{if(btn){btn.disabled=false;btn.textContent='Install'}}
}
async function tunStart(){
  const cf=(TUNNEL.providers||[]).find(p=>p.id==='cloudflared'&&p.available);
  const ts=(TUNNEL.providers||[]).find(p=>p.id==='tailscale'&&p.available&&!p.needs);
  const provider=ts?'tailscale':(cf?'cloudflared':'');
  if(!provider){toast('no tunnel provider is ready');return}
  const publicly=provider==='cloudflared';
  if(publicly&&!await osConfirm('Publish to the public internet?',
      'Anyone with the link reaches your sign-in page. They still need your passphrase, '
      +'but the address itself is public. Stop it any time from here.',
      {danger:true,confirmText:'Publish'}))return;
  toast('setting up…');
  try{
    const r=await fetch('/api/tunnel',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'start',provider,public:publicly})});
    const d=await r.json();
    toast(d.ok?'✓ '+(d.url||d.message):(d.message||'could not publish'));
    refreshApp('syssettings');
  }catch(e){toast('could not reach the server')}
}
async function tunStop(){
  const r=await fetch('/api/tunnel',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:'stop'})});
  const d=await r.json();
  toast(d.message||(d.ok?'stopped':'nothing to stop'));
  refreshApp('syssettings');
}
