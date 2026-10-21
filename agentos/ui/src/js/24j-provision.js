/* ================= new machines on the network =================
   provision.py is the whole design; this draws /api/provision. Two faces of it:

   - On a machine that leads (or could): Settings → Team & Communications → New machines.
     Every machine heard waiting is a row (its board, memory, the id to compare with its
     own screen); tick several, type each one's code (or let the community's enrolment
     key prove it), choose what they become (kiosk, one agent, the agent's name) and
     Enable. A machine heard for the first time is also a toast with Review, from
     09-websocket.js, because "whenever a new machine is turned on … we should be able to
     check if we need to provision it".
   - On a machine that is WAITING: a card in the corner of its own screen with the code
     and the id to read out, and "Set it up here instead".

   A Zero (zero.py) is the same road with the questions taken out: "Make a Zero" shows the one
   line to paste on a Pi (this hub's automatic key and addresses, a Tailscale key if one is
   typed, which is used for the line and kept nowhere), and "Standard setup" is what every
   machine set up from here gets: where its work runs, Light mode, kiosk, and its agents.

   TUI: `bento pool discover | enable | key | wait | zero | standard`. SUI: identical, a page;
   nothing here touches the compositor. */
var PROV={v:null,sel:{},zero:null,agents:null};

async function provPaint(){
  const box=document.getElementById('s-prov');if(!box)return;
  let v;try{v=await apiJSON('/api/provision')}catch(e){box.innerHTML='';return}
  PROV.v=v;provWaitCard(v);
  const can=v.can_change,rows=[];
  // a waiting machine sets nothing up; its own card says what to do
  if(v.this&&v.this.waiting){
    rows.push(pRow('Waiting to be set up',`<span class="mut">code ${esc(v.this.pin||'(enrolment key)')} · id ${esc(v.this.id)}</span>`
      +`<button class="endbtn" data-prov="nowait"${can?'':' disabled'}>Set it up here instead</button>`,
      {desc:'Another Bento on your network can set this machine up.',
       more:'On the machine that leads your community, choose this one in New machines and type the code.',f:'provision waiting set up code'}));
    box.innerHTML=rows.join('');provWire(box);return;
  }
  if(!(v.role==='leader'||v.has_brain||(v.seen||[]).length||(v.devices||[]).length)){box.innerHTML='';return}
  const seen=(v.seen||[]).filter(m=>m.state!=='ignored');
  rows.push(pRow('New machines',`<button class="endbtn" data-prov="scan"${can?'':' disabled'}>Look now</button>`,
    {desc:v.watching?'Machines that turn on waiting to be set up show here, and you get a toast.':'This machine is not listening for new ones.',
     more:'A fresh Raspberry Pi with Bento waits by itself. Any other machine waits after bento pool wait on.',
     f:'provision new machines discover raspberry pi poap enable set up scan'}));
  if(seen.length){
    rows.push(`<div class="prov-list">${seen.map(m=>{
      const hw=m.hw||{},on=PROV.sel[m.fp]!==undefined;
      const state=m.state==='enabled'?'set up':m.age<90?'waiting':'waiting · heard '+poolAgo(m.age);
      const proof=m.our_key?`<span class="prov-key">your key${m.auto?', automatic':''}</span>`
        :`<input class="prov-code" data-code="${esc(m.fp)}" inputmode="numeric" maxlength="7" placeholder="code" aria-label="Code on ${esc(m.name)}'s screen"${m.state==='enabled'?' disabled':''}>`;
      return `<div class="prov-m${m.state==='enabled'?' done':''}">
        <label class="prov-pick"><input type="checkbox" data-pick="${esc(m.fp)}" ${on?'checked':''}${m.state==='enabled'||!can?' disabled':''}>
          <b>${esc(m.name)}</b></label>
        <span class="mut">${esc(hw.board||hw.arch||'a machine')} · ${hw.ram_mb||0} MB · id ${esc(m.id)} · ${esc(state)}
          · <span class="prov-via ${m.via==='tailscale'?'ts':''}">${m.via==='tailscale'?'over Tailscale':'on your network'}</span>${m.owner_name?` · for ${esc(m.owner_name)}`:''}</span>
        <input class="prov-name" data-name="${esc(m.fp)}" maxlength="32" placeholder="${esc(m.name)}" aria-label="Name for ${esc(m.name)}"${m.state==='enabled'?' disabled':''}>
        ${proof}
        ${m.state!=='enabled'&&can?`<button class="endbtn" data-prov="ignore" data-fp="${esc(m.fp)}">Not this one</button>`:''}</div>`}).join('')}</div>`);
    const f=PROV.form||{kiosk:false,buddy:'auto',agent:''};
    rows.push(pRow('Set them up as',`<label class="prov-opt">${pSwitch('prov-kiosk',!!f.kiosk)} Kiosk</label>
        ${pSelect('prov-buddy',[['auto','Auto'],['on','Only the agent'],['off','The whole crew']],f.buddy)}
        <input id="prov-agent" maxlength="32" placeholder="Agent's name" value="${esc(f.agent||'')}" style="max-width:140px">`,
      {desc:'Each one joins this community and thinks with this machine’s brain.',
       more:'Light mode is on for each, and they get their own agent with that name. You can change any of it on the machine later.',
       f:'provision profile kiosk buddy agent name'}));
    rows.push(pRow('Enable',`<button class="wiz-next" data-prov="enable"${can?'':' disabled'}>Enable with an agent</button>`,
      {desc:'Type the code shown on each machine’s screen, unless it carries your key.',f:'provision enable'}));
  }else{
    rows.push(`<p class="mut prov-empty">No machine is waiting right now. Turn one on, or press Look now.</p>`);
  }
  rows.push(provZeroHTML(v,can));
  rows.push(provDevicesHTML(v,can));
  const ks=(v.keys||[]).filter(k=>!k.single);
  rows.push(pRow('Enrolment keys',`${ks.map(k=>`<span class="prov-k">${esc(k.label)}
      <label class="prov-opt">${pSwitch('prov-auto-'+k.id,!!k.auto)} automatic</label>
      <button class="endbtn" data-prov="dropkey" data-kid="${esc(k.id)}">Revoke</button></span>`).join('')}
      <button class="endbtn" data-prov="key"${can?'':' disabled'}>Make a key</button>`,
    {desc:'Put a key on a new machine and nobody has to read a code off its screen.',
     more:'Save it as bento-enroll.txt on the SD card’s boot partition, or install with --enroll. Automatic sets the machine up the moment it is heard.',
     f:'provision enrolment key zero touch sd card automatic'}));
  rows.push('<div id="prov-out" aria-live="polite"></div>');
  /* a repaint (any provision broadcast, the scan's own) must not drop what is being typed
     into the install form: found in the screenshot walk, where Check it saw an empty user */
  const kept={};['dev-user','dev-pw','dev-agent','dev-auth','dev-kiosk'].forEach(id=>{const e=document.getElementById(id);
    if(e)kept[id]=e.type==='checkbox'?e.checked:e.value});
  box.innerHTML=rows.join('');
  Object.keys(kept).forEach(id=>{const e=document.getElementById(id);if(!e)return;
    if(e.type==='checkbox')e.checked=kept[id];else if(kept[id])e.value=kept[id]});
  provWire(box);
}
/* ---------------- a Zero: the one line, and the standard setup every machine gets ---------------- */
function provZeroHTML(v,can){
  const st=v.standard||{},z=PROV.zero,ags=st.agents||[],rows=[];
  /* whose it is: always the person signed in. The hub answers a Zero as that account, with
     its agents, memory and integrations, and nobody makes one for someone else (_zero_for). */
  const mine=v.me_name||'';
  rows.push(pRow('Make a Zero',`<input id="zero-ts" class="dev-secret" autocomplete="off" data-lpignore="true" spellcheck="false"
      placeholder="Tailscale auth key (optional)" aria-label="Tailscale auth key" style="max-width:230px">
      <button class="endbtn" data-prov="zeroline"${v.can_zero!==false?'':' disabled'}>Show the line</button>`,
    {desc:mine?`Paste one line on a Pi. It is yours, ${esc(mine)}, and works with your integrations.`
      :'Paste one line on a Pi and it is set up from here, with nobody at it.',
     more:'It installs Bento in Light mode, joins Tailscale when you add a key, and gets the standard setup below as soon as it is heard. The key goes into the line and nowhere else.',
     f:'zero pi curl one line install tailscale zero touch hub'}));
  if(z)rows.push(`<div class="zero-out">${z.for&&z.for.name?`<p class="mut">For ${esc(z.for.name)}</p>`:''}<code class="zero-line">${esc(z.line)}</code>
      <button class="endbtn" data-prov="zerocopy">Copy</button>
      <p class="mut">${(z.addresses||[]).map(a=>`${esc(a.addr)} ${a.via==='tailscale'?'over Tailscale':'on your network'}`).join(' · ')
        ||'This hub has no address another machine can reach.'}${(z.addresses||[]).some(a=>a.via==='tailscale')?'':
        '. This hub is not on Tailscale, so a Zero has to be on the same network.'}</p></div>`);
  const opts=(PROV.agents||[]).filter(a=>!ags.some(x=>x.name===a.name.toLowerCase()));
  rows.push(pRow('Standard setup',`<span class="zero-std">
      ${pSelect('std-exec',[['hub','Work runs on this hub'],['here','Work runs on the machine']],st.execution||'here')}
      <label class="prov-opt">${pSwitch('std-lite',!!st.lite)} Light mode</label>
      <label class="prov-opt">${pSwitch('std-kiosk',!!st.kiosk)} Kiosk</label>
      <input id="std-agent" maxlength="32" placeholder="Agent’s name" value="${esc(st.agent_name||'')}" style="max-width:140px"></span>`,
    {desc:'Every machine set up from here gets this, with no questions.',
     more:'With work on this hub, a machine’s agent hands its tasks to yours and the files come back to it. A key’s own setup and what you choose when enabling go on top.',
     f:'standard setup profile provisioning zero agents executors execution hub'}));
  rows.push(pRow('Its agents',`<span class="zero-ags">${ags.map(a=>`<span class="prov-k">${esc(a.name)}${a.hands?` <span class="mut">· ${esc(a.hands)}</span>`:''}
        <button class="endbtn" data-prov="stdrm" data-name="${esc(a.name)}" aria-label="Take ${esc(a.name)} out">✕</button></span>`).join('')
      ||'<span class="mut">None of its own</span>'}</span>
      ${opts.length&&can?`<select id="std-add" aria-label="Add one of your agents"><option value="">＋ Add one of your agents</option>
        ${opts.map(a=>`<option value="${esc(a.name)}">${esc(a.name)}</option>`).join('')}</select>`:''}`,
    {desc:'A copy of each, with its executor, is made on every machine set up from here.',
     more:'Only the tools a department may have travel (no shell, push or send). A machine whose work runs on this hub keeps no other agents.',
     f:'standard agents executors hands copy zero'}));
  return rows.join('');
}
async function provStdSave(patch){
  const st=Object.assign({},(PROV.v||{}).standard||{},patch);
  const r=await fetch('/api/provision/standard',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile:st})});
  const d=await r.json().catch(()=>({}));
  if(!r.ok){toast(d.error||'could not save that');return}
  if((d.dropped||[]).length)toast('Not kept: '+d.dropped.join('; '));
  provPaint();
}
async function provAgents(){
  if(PROV.agents)return;
  try{PROV.agents=(await apiJSON('/api/subagents')).subagents||[]}catch(e){PROV.agents=[]}
  provPaint();
}
/* ---------------- machines without Bento (netscan.py, remoteinstall.py, sdcard.py) ----------------
   A Pi or any Linux box that answers SSH but runs nothing of ours: heard when it says its name
   on the network (mDNS), or found by Look at the network. Install Bento logs in with a password
   used once (or this machine's key), shows what the machine is and the exact command, and runs
   the real installer with a key made for that one machine, so it is set up the moment it is
   heard. The SD card writer is for the screen the card is plugged into. */
var DEV={open:'',check:{},log:{},err:{}};
function provDevicesHTML(v,can){
  /* The machines themselves (with Install Bento) are the inventory above, in Network
     (24n-network.js); this keeps the two ways in that need no machine yet. */
  const remote=typeof remoteClient==='function'&&remoteClient();
  const rows=[];
  rows.push(pRow('This machine’s SSH key',v.pubkey?`<code class="dev-key">${esc(v.pubkey)}</code><button class="endbtn" data-prov="devcopykey">Copy</button>`
      :`<button class="endbtn" data-prov="devkey"${can?'':' disabled'}>Make it</button>`,
    {desc:'Put it in Raspberry Pi Imager and Bento can reach a new Pi with no password.',
     more:'Imager → OS customisation → Services → Allow public-key authentication only. Paste this key there.',
     f:'ssh key public imager raspberry pi password'}));
  if(!remote)rows.push(pRow('Set up an SD card',`<button class="endbtn" data-prov="devcard"${can?'':' disabled'}>Add Bento to a card</button>`,
    {desc:'A Pi with this card installs Bento on its first boot and is set up by this machine.',
     more:'Write Raspberry Pi OS (trixie) with Raspberry Pi Imager first, then open the card’s boot partition here. Only what Bento needs is added.',
     f:'sd card first boot cloud-init imager zero touch poap'}));
  rows.push('<div id="dev-card"></div>');
  return rows.join('');
}
function provDevForm(d){
  const c=DEV.check[d.ip];
  // the port SSH answered on in the scan (its first port), which is 22 on a real Pi
  const sshPort=d.ssh&&(d.ports||[]).length?Number(d.ports[0])||22:22;
  return `<div class="dev-form">
    <label>User there <input id="dev-user" maxlength="32" placeholder="the user set in Imager" value="${esc((c&&c.user)||'')}"></label>
    <label>Password <input id="dev-pw" type="text" class="dev-secret" autocomplete="off" data-lpignore="true" placeholder="blank: use this machine’s key"></label>
    <label><span class="dev-lbl">Its agent’s name ${pInfo('What you call it on its screen: say its name, then what you want. Like Chef in the kitchen, or Fridge.')}</span><input id="dev-agent" maxlength="32" placeholder="Chef, Fridge…"></label>
    <div class="dev-opts"><label class="prov-opt"><input type="checkbox" id="dev-auth"> Let this machine in from now on</label>
    <label class="prov-opt">${pSwitch('dev-kiosk',true)} Open on its screen ${pInfo('Bento opens full screen on it when it starts: the Office, listening. On Raspberry Pi OS Lite this installs cage and Chromium to draw it.')}</label></div>
    <div class="dev-acts"><button class="endbtn" data-prov="devcheck" data-ip="${esc(d.ip)}" data-port="${sshPort}">Check it</button>
      ${c&&!c.problems.length?`<button class="wiz-next" data-prov="devinstall" data-ip="${esc(d.ip)}" data-port="${sshPort}">Install Bento there</button>`:''}</div>
    ${DEV.err[d.ip]?`<p class="warn dev-err">✗ ${esc(DEV.err[d.ip])}</p>`:''}
    ${c?`<div class="dev-facts">${esc([c.board||c.arch,c.os,c.ram_mb+' MB memory',c.free_mb+' MB free'].filter(Boolean).join(' · '))}
      ${c.bento?'<br>Bento is already there.':''}${c.host_key?`<br><span class="mut">Its key: ${esc(c.host_key)}</span>`:''}
      ${c.problems.map(p=>`<br><span class="warn">✗ ${esc(p)}</span>`).join('')}
      <br><span class="mut">This runs there:</span><code class="dev-plan">${esc(c.plan||'')}</code></div>`:''}
  </div>`;
}
function provDevCreds(){
  const g=id=>(document.getElementById(id)||{});
  const agent=(g('dev-agent').value||'').trim();
  return {user:(g('dev-user').value||'').trim(),password:g('dev-pw').value||'',authorize:!!g('dev-auth').checked,
    profile:Object.assign({kiosk:!!g('dev-kiosk').checked,lite:true},agent?{agent_name:agent}:{})};
}
function provDevLine(ev){
  const id='dev-log-'+String(ev.ip||'').replace(/\W/g,'_');let el=document.getElementById(id);
  if(!el){const row=document.querySelector(`.dev-m[data-dev="${CSS.escape(ev.ip||'')}"],.net-m[data-ip="${CSS.escape(ev.ip||'')}"]`);if(!row)return;
    el=document.createElement('pre');el.className='dev-log';el.id=id;row.appendChild(el)}
  el.textContent=(el.textContent?el.textContent+'\n':'')+ev.line;el.scrollTop=el.scrollHeight;
}
function provDevCard(){
  const el=document.getElementById('dev-card');if(!el)return;
  if(el.innerHTML){el.innerHTML='';return}
  el.innerHTML=`<div class="dev-form">
    <label>The card’s boot partition <input id="card-path" placeholder="/media/you/bootfs"></label>
    <label>User on the card <input id="card-user" maxlength="32" placeholder="as set in Imager"></label>
    <label>Name on the network <input id="card-host" maxlength="63" placeholder="pi-kitchen"></label>
    <label><span class="dev-lbl">Its agent’s name ${pInfo('What you call it on its screen: say its name, then what you want. Like Chef in the kitchen, or Fridge.')}</span><input id="card-agent" maxlength="32" placeholder="Chef, Fridge…"></label>
    <label>Wi-Fi (if Imager did not) <input id="card-ssid" maxlength="32" placeholder="network name"></label>
    <label>Wi-Fi password <input id="card-wpw" type="text" class="dev-secret" autocomplete="off" data-lpignore="true"></label>
    <label>Country <input id="card-cc" maxlength="2" placeholder="GB" style="max-width:60px"></label>
    <label class="prov-opt">${pSwitch('card-kiosk',true)} Open on its screen ${pInfo('Bento opens full screen on it when it starts: the Office, listening. On Raspberry Pi OS Lite this installs cage and Chromium to draw it.')}</label>
    <div class="dev-acts"><button class="wiz-next" data-prov="devcardgo">Add Bento to this card</button></div>
    <p class="mut" id="card-out"></p></div>`;
  el.querySelector('[data-prov=devcardgo]').onclick=async()=>{
    const g=id=>(document.getElementById(id)||{}).value||'';
    const body={path:g('card-path').trim(),user:g('card-user').trim(),hostname:g('card-host').trim(),
      profile:Object.assign({kiosk:!!document.getElementById('card-kiosk').checked,lite:true},
        g('card-agent').trim()?{agent_name:g('card-agent').trim()}:{})};
    if(g('card-ssid'))body.wifi={ssid:g('card-ssid'),password:g('card-wpw'),country:g('card-cc')||'GB'};
    const r=await fetch('/api/devices/sdcard',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json().catch(()=>({}));const out=document.getElementById('card-out');
    if(!r.ok){out.textContent=d.error||'could not write the card';out.className='warn';return}
    out.className='ok';out.textContent=`✓ Wrote ${d.written.join(', ')} for ${d.user}. Put the card in the Pi and switch it on; this machine sets it up when it is heard.`;
  };
}
function provWire(box){
  box.querySelectorAll('[data-prov]').forEach(b=>b.onclick=()=>provAct(b.dataset.prov,b));
  box.querySelectorAll('[data-pick]').forEach(c=>c.onchange=()=>{if(c.checked)PROV.sel[c.dataset.pick]=1;else delete PROV.sel[c.dataset.pick]});
  // a typed code ticks its machine, so nobody types six digits and forgets the box
  box.querySelectorAll('[data-code]').forEach(i=>i.oninput=()=>{const c=box.querySelector(`[data-pick="${CSS.escape(i.dataset.code)}"]`);
    if(c&&i.value.replace(/\D/g,'').length===6&&!c.checked){c.checked=true;PROV.sel[i.dataset.code]=1}});
  (PROV.v.keys||[]).forEach(k=>{const s=box.querySelector('#prov-auto-'+k.id);if(s)s.onchange=async()=>{
    const r=await fetch('/api/provision/key/'+encodeURIComponent(k.id),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({auto:s.checked})});
    if(!r.ok)toast('could not change that');provPaint()}});
  const g=q=>box.querySelector(q);
  if(g('#std-exec'))g('#std-exec').onchange=e=>provStdSave({execution:e.target.value});
  if(g('#std-lite'))g('#std-lite').onchange=e=>provStdSave({lite:e.target.checked});
  if(g('#std-kiosk'))g('#std-kiosk').onchange=e=>provStdSave({kiosk:e.target.checked});
  if(g('#std-agent'))g('#std-agent').onchange=e=>provStdSave({agent_name:e.target.value.trim()});
  if(g('#std-add'))g('#std-add').onchange=async e=>{const n=e.target.value;if(!n)return;
    const r=await fetch('/api/provision/standard/agent',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n})});
    const d=await r.json().catch(()=>({}));if(!r.ok)toast(d.error||'could not add that');
    else if((d.dropped||[]).length)toast(`✓ ${n} added. Not kept: ${d.dropped.join('; ')}`);else toast(`✓ ${n} added`);
    provPaint()};
  if(g('.zero-ags'))provAgents();
  const save=()=>{PROV.form={kiosk:!!(box.querySelector('#prov-kiosk')||{}).checked,
    buddy:(box.querySelector('#prov-buddy')||{}).value||'auto',agent:((box.querySelector('#prov-agent')||{}).value||'').trim()}};
  ['#prov-kiosk','#prov-buddy','#prov-agent'].forEach(q=>{const e=box.querySelector(q);if(e)e.onchange=save});
}
async function provAct(act,b){
  const box=document.getElementById('s-prov'),out=document.getElementById('prov-out');
  const post=async(url,body,method)=>{const r=await fetch(url,{method:method||'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
    const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||('could not do that ('+r.status+')'));return d};
  try{
    if(act==='devscan'){b.disabled=true;b.textContent='Looking…';const d=await post('/api/devices/scan');
      toast(d.found?`✓ ${d.found} machine${d.found===1?'':'s'} answered on ${d.networks}`:`Nothing answered on ${d.networks}.`);return provPaint()}
    if(act==='devopen'){DEV.open=DEV.open===b.dataset.ip?'':b.dataset.ip;return provPaint()}
    if(act==='devignore'){await post('/api/devices/ignore',{key:b.dataset.key});return provPaint()}
    if(act==='devkey'){await post('/api/devices/sshkey');return provPaint()}
    if(act==='devcopykey'){navigator.clipboard&&navigator.clipboard.writeText((PROV.v||{}).pubkey||'');toast('✓ copied');return}
    if(act==='devcard')return provDevCard();
    if(act==='devcheck'){const c=provDevCreds();if(!c.user){toast('Who logs in there? Type the user name.');return}
      b.disabled=true;b.textContent='Checking…';
      // a refusal stays in the form under Check it: a toast is gone before it is read
      try{DEV.check[b.dataset.ip]=Object.assign(await post('/api/devices/check',{ip:b.dataset.ip,port:Number(b.dataset.port)||22,...c}),{user:c.user});delete DEV.err[b.dataset.ip]}
      catch(e){delete DEV.check[b.dataset.ip];DEV.err[b.dataset.ip]=String(e.message||e);throw e}
      finally{provPaint()}
      return}
    if(act==='devinstall'){const c=provDevCreds();
      const called=c.profile.agent_name?` Its agent is called ${c.profile.agent_name}.`:'';
      if(!await osConfirm(`Install Bento on ${b.dataset.ip}?`,`The command shown runs there as ${c.user}.${called}`,{confirmText:'Install'}))return;
      await post('/api/devices/install',{ip:b.dataset.ip,port:Number(b.dataset.port)||22,...c});DEV.open='';toast('Installing Bento on '+b.dataset.ip+'…');return provPaint()}
    if(act==='scan'){b.disabled=true;b.textContent='Looking…';const d=await post('/api/provision/scan');
      toast(d.found?`✓ ${d.found} machine${d.found===1?'':'s'} waiting`:'No machine answered. Is it on the same network?');return provPaint()}
    if(act==='ignore'){await post('/api/provision/ignore',{fp:b.dataset.fp});return provPaint()}
    if(act==='zeroline'){const ts=((document.getElementById('zero-ts')||{}).value||'').trim();
      b.disabled=true;try{PROV.zero=await post('/api/provision/zero',{tailscale_key:ts})}finally{b.disabled=false}
      const i=document.getElementById('zero-ts');if(i)i.value='';return provPaint()}
    if(act==='zerocopy'){navigator.clipboard&&navigator.clipboard.writeText((PROV.zero||{}).line||'');toast('✓ copied');return}
    if(act==='stdrm'){await fetch('/api/provision/standard/agent/'+encodeURIComponent(b.dataset.name),{method:'DELETE'});return provPaint()}
    if(act==='nowait'){await post('/api/provision',{wait:false},'PUT');toast('✓ This machine is set up here');return provPaint()}
    if(act==='dropkey'){if(!confirm('Revoke this key? Machines that carry it can no longer be set up with it.'))return;
      await fetch('/api/provision/key/'+encodeURIComponent(b.dataset.kid),{method:'DELETE'});return provPaint()}
    if(act==='key'){
      const label=prompt('A name for this key, like “kitchen Pis”','Pis');if(label===null)return;
      const d=await post('/api/provision/key',{label});
      provPaint().then(()=>{const o=document.getElementById('prov-out');if(!o)return;
        o.innerHTML=`<div class="prov-keytext"><b>Your enrolment key</b> (shown once)
          <code>${esc(d.key.text)}</code>
          <span class="mut">Save it as <code>bento-enroll.txt</code> on the SD card’s boot partition, or run
          <code>bento pool enroll …</code> on the new machine.</span>
          <button class="endbtn" id="prov-copy">Copy</button></div>`;
        const c=document.getElementById('prov-copy');if(c)c.onclick=()=>{navigator.clipboard&&navigator.clipboard.writeText(d.key.text);toast('✓ copied')}});
      return;
    }
    if(act==='enable'){
      const fps=Object.keys(PROV.sel);if(!fps.length){toast('Tick the machines to set up first');return}
      const f=PROV.form||{},prof={kiosk:!!(box.querySelector('#prov-kiosk')||{}).checked,
        buddy:(box.querySelector('#prov-buddy')||{}).value||'auto',lite:true};
      const an=((box.querySelector('#prov-agent')||{}).value||f.agent||'').trim();if(an)prof.agent_name=an;
      const machines=fps.map(fp=>({fp,code:((box.querySelector(`[data-code="${CSS.escape(fp)}"]`)||{}).value||'').replace(/\D/g,''),
        name:((box.querySelector(`[data-name="${CSS.escape(fp)}"]`)||{}).value||'').trim()}));
      b.disabled=true;b.textContent='Setting up…';
      const d=await post('/api/provision/enable',{machines,profile:prof});
      const ok=(d.results||[]).filter(r=>r.ok),bad=(d.results||[]).filter(r=>!r.ok);
      PROV.sel={};
      await provPaint();
      const o=document.getElementById('prov-out');
      if(o)o.innerHTML=(ok.length?`<p class="ok">✓ ${ok.map(r=>esc(r.name)).join(', ')} ${ok.length===1?'is':'are'} set up and joining “${esc(d.pool.name)}”.</p>`:'')
        +bad.map(r=>`<p class="warn">${esc(r.name||'A machine')}: ${esc(r.error)}</p>`).join('');
      if(typeof poolPaint==='function')poolPaint();
      return;
    }
  }catch(e){toast(String(e.message||e),{kind:'err'});provPaint()}
}

/* ---------------- the waiting machine's own screen ---------------- */
/* A card in the corner, above the setup wizard: the code and the id to read out to
   whoever is at the leader. Not on a remote browser: the code is for somebody standing
   at THIS screen, and a phone looking at the machine is not that. */
function provWaitCard(v){
  let el=document.getElementById('prov-wait');
  const t=(v&&v.this)||{};
  const show=t.waiting&&!(typeof remoteClient==='function'&&remoteClient());
  if(!show){if(el)el.remove();return}
  if(!el){el=document.createElement('div');el.id='prov-wait';el.setAttribute('role','status');document.body.appendChild(el)}
  const hw=t.hw||{};
  el.innerHTML=`<b>Waiting to be set up</b>
    <p>${t.locked?`Too many wrong codes. Try again in ${Math.ceil(t.locked/60)} minutes.`
      :t.pin?`On the Bento that leads your community, open Settings → Team & Communications → Community, choose this machine and type`
      :`This machine carries an enrolment key. On the Bento that leads your community, choose it and press Enable.`}</p>
    ${t.pin&&!t.locked?`<div class="prov-pin">${esc(t.pin.slice(0,3))} ${esc(t.pin.slice(3))}</div>`:''}
    <p class="mut">${esc(hw.board||hw.host||'This machine')} · id ${esc(t.id)}</p>
    <button class="endbtn" id="prov-here">Set it up here instead</button>`;
  el.querySelector('#prov-here').onclick=async()=>{
    await fetch('/api/provision',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({wait:false})});
    el.remove();
  };
}
async function provWaitCheck(){
  try{const v=await apiJSON('/api/provision');PROV.v=v;provWaitCard(v)}catch(e){}
}
