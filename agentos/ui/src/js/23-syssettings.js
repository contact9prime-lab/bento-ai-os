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


/* ================= Remote access =================
   Reach this desktop from your phone. Off until a human turns it on here and
   sets a passphrase — and the server only accepts this call from the machine
   itself, so nothing signed in remotely (and no agent, and no app) can widen
   its own access. */
let REMOTE={};
async function sysRemote(el){
  try{REMOTE=await (await fetch('/api/remote')).json()}catch(e){REMOTE={}}
  const on=!!REMOTE.enabled, set=!!REMOTE.configured;
  el.innerHTML=`
    <div class="provbox">
      <div class="ptitle">Remote access
        <span class="rm-pill ${on?'on':''}">${on?'ON':'off'}</span></div>
      <p class="mut" style="margin-top:8px;line-height:1.6">
        Serve this desktop to your phone or another machine on your network.
        <b>Everything you can do here, whoever signs in can do too</b> — including the
        Terminal and the agent's shell — so it stays off until you set a passphrase.
        Using AgentOS on this machine is unaffected either way.</p>

      <label style="margin-top:14px">${set?'Change the passphrase':'Set a passphrase'}</label>
      <div class="row" style="gap:8px">
        <input id="rm-pw" type="password" autocomplete="new-password"
               placeholder="at least 8 characters — a phrase beats a word" style="flex:1">
        <button class="endbtn" onclick="rmSetPass()">${set?'Update':'Set'}</button>
      </div>
      ${set?'<p class="mut" style="margin-top:6px;font-size:11px">A passphrase is set. Changing it signs every remote device out.</p>':''}

      <div class="row" style="margin-top:16px;gap:10px;align-items:center">
        <button class="save" style="margin:0;width:auto;padding:10px 18px${on?';background:var(--err);color:#fff':''}"
                onclick="rmToggle(${on?'false':'true'})" ${set?'':'disabled title="set a passphrase first"'}>
          ${on?'Turn remote access off':'Turn remote access on'}</button>
        <span class="mut" style="font-size:12px">${set?'':'a passphrase is required first'}</span>
      </div>
    </div>

    ${on?`<div class="provbox">
      <div class="ptitle">Reach it from your phone</div>
      ${(REMOTE.addresses||[]).length?`<div class="rm-addr">${REMOTE.addresses.map(a=>`
          <div class="rm-row"><code>${esc(a)}</code>
            <button class="endbtn" onclick="rmCopy('${esc(a)}')">Copy</button></div>`).join('')}</div>`
        :'<p class="mut" style="margin-top:6px">No network address detected.</p>'}
      <p class="mut" style="margin-top:10px;line-height:1.6">
        Open that on your phone, sign in with the passphrase, then
        <b>Share → Add to Home Screen</b> (iOS) or <b>⋮ → Install app</b> (Android) for a
        full-screen app with no browser chrome. The layout adapts to the phone on its own.</p>
      ${REMOTE.listening_on&&REMOTE.listening_on!=='127.0.0.1'?'':
        '<p class="mut" style="margin-top:8px;color:var(--warn)">Restart AgentOS for this to take effect — it is still listening on loopback only.</p>'}
    </div>`:''}

    <div class="provbox">
      <div class="ptitle">Before you open it up</div>
      <ul class="rm-notes">
        <li>This is <b>one shared passphrase for one machine</b>, not per-user accounts. Treat it like the key to the machine, because it is.</li>
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
