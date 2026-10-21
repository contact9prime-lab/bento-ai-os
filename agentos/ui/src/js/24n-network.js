/* ================= Settings → Network: what is on it, install, secure =================
   inventory.py is the list and harden.py is "Secure it"; this draws /api/network. Asked for
   as "the discovery of the devices should be another tab … install, maintain the inventory
   and secure the box". One row per machine, Bento or not, with what it is, whose, whether
   Bento runs there and how secure it was last measured. A row opens to two forms: Install
   Bento (provDevForm, the same one New machines used) and Secure it, which shows each step,
   why, and the exact command before anything runs. The rest of setting machines up (new
   machines waiting, Make a Zero, enrolment keys, the SD card) is the New machines box below,
   moved here from Team & Communications.

   TUI: `bento network`, `bento network check|secure|label|forget`. SUI: identical, a page;
   nothing here touches the compositor. A Zero has no Network tab (00k-zeroface.js): its
   network is its hub's business. */
var NET={v:null,open:'',mode:'',check:{},runs:{},steps:{}};

async function netPaint(){
  const box=document.getElementById('s-net');if(!box)return;
  let v;try{v=await apiJSON('/api/network')}catch(e){box.innerHTML=`<p class="mut prov-empty">${esc(String(e.message||e))}</p>`;return}
  NET.v=v;
  const can=v.can_change,rows=[],s=v.summary||{};
  rows.push(pRow('On your network',`<button class="endbtn" data-net="scan"${can?'':' disabled'}>Look at the network</button>`,
    {desc:s.machines?`${s.machines} machine${s.machines===1?'':'s'} · ${s.bento} with Bento · ${s.secured} secured`
      :'Look at the network to list the machines on it.',
     more:'Only this machine’s own private network is looked at. A Raspberry Pi says its name when it joins, and you get a toast.',
     f:'network inventory devices machines scan discover list'}));
  if(v.ssh_missing)rows.push(`<p class="mut prov-empty">${esc(v.ssh_missing)}</p>`);
  const list=(v.rows||[]).filter(r=>!r.ignored);
  if(list.length)rows.push(`<div class="net-list">${list.map(r=>netRowHTML(r,v,can)).join('')}</div>`);
  else rows.push(`<p class="mut prov-empty">Nothing listed yet. Press Look at the network.</p>`);
  // keep what is being typed across a repaint (a broadcast, a line of a running step)
  const kept={};['net-user','net-pw','net-mine','dev-user','dev-pw'].forEach(id=>{const e=document.getElementById(id);if(e)kept[id]=e.value});
  box.innerHTML=rows.join('');
  Object.keys(kept).forEach(id=>{const e=document.getElementById(id);if(e&&kept[id])e.value=kept[id]});
  netWire(box);
}

function netBadge(r){
  const b={none:'no Bento',waiting:'Bento, waiting',['set up']:'Bento, set up',linked:'Bento, linked',installed:'Bento installed'}[r.bento]||r.bento;
  return `<span class="net-b ${r.bento==='none'?'':'on'}">${esc(b)}</span>`;
}
function netSecBadge(r){
  const cls=r.secured_n<0?'':r.security_words==='secured'?'ok':'warn';
  return `<span class="net-s ${cls}">${esc(r.security_words)}</span>`;
}
function netRowHTML(r,v,can){
  const open=NET.open===r.key,run=(v.secures||{})[r.ip]||{},inst=(v.installs||{})[r.ip]||{};
  const what=[r.board||r.maker,r.os].filter(Boolean).join(' · ');
  const seen=r.age==null?'':r.stale?'not heard for a week':r.age<120?'heard just now':'heard '+poolAgo(r.age);
  const busy=run.state==='running'?' · securing…':inst.state==='running'?' · installing…':'';
  return `<div class="net-m${open?' open':''}${r.stale?' stale':''}" data-key="${esc(r.key)}" data-ip="${esc(r.ip||'')}">
    <div class="net-top">
      <b>${esc(r.display)}</b>${netBadge(r)}${netSecBadge(r)}
      <span class="mut">${esc(r.ip||'')}${r.mac?' · '+esc(r.mac):''}${what?' · '+esc(what):''}${r.owner_name?' · for '+esc(r.owner_name):''}${seen?' · '+esc(seen):''}${esc(busy)}</span>
    </div>
    ${r.ssh_off?`<p class="mut net-hint">${esc(r.ssh_off)}</p>`:''}
    ${can?`<div class="net-acts">
      ${r.bento==='none'&&r.ssh&&!v.ssh_missing?`<button class="endbtn" data-net="install" data-key="${esc(r.key)}">Install Bento</button>`:''}
      ${r.ip&&!v.ssh_missing&&(r.ssh||r.bento!=='none'||r.secured_n>=0)?`<button class="endbtn" data-net="secure" data-key="${esc(r.key)}">${r.secured_n<0?'Secure it':'Security'}</button>`:''}
      ${(r.connections||[]).length?`<button class="endbtn" data-net="unlink" data-key="${esc(r.key)}">Disconnect</button>`:''}
      <button class="endbtn" data-net="label" data-key="${esc(r.key)}">Rename</button>
      <button class="endbtn" data-net="forget" data-key="${esc(r.key)}">Not this one</button></div>`:''}
    ${open&&NET.mode==='install'?provDevForm({ip:r.ip,ssh:r.ssh,ports:r.ports||[]}):''}
    ${open&&NET.mode==='secure'?netSecureForm(r):''}
    ${open&&NET.mode==='unlink'?netUnlinkForm(r):''}
    ${netLogHTML('net-log-',r.ip,run)}${netLogHTML('dev-log-',r.ip,inst)}
  </div>`;
}
/* A run's lines while it runs, and its last ones when it failed. A finished run says
   itself in the row's badge, so its apt chatter is not left on screen. */
function netLogHTML(prefix,ip,run){
  if(!run||!(run.state==='running'||run.state==='failed'))return '';
  const lines=(run.lines||[]).slice(run.state==='failed'?-6:-40);
  return `<pre class="dev-log" id="${prefix}${esc(String(ip).replace(/\W/g,'_'))}">${esc(lines.join('\n'))}${run.error?'\n✗ '+esc(run.error):''}</pre>`;
}
function netSecureForm(r){
  const c=NET.check[r.ip],steps=(NET.v||{}).steps||[];
  const sel=NET.steps[r.ip]||{};
  return `<div class="dev-form net-form">
    <label>User there <input id="net-user" maxlength="32" placeholder="the user set in Imager" value="${esc((c&&c.user)||r.user||'')}"></label>
    <label>Password <input id="net-pw" type="text" class="dev-secret" autocomplete="off" data-lpignore="true" placeholder="blank: use this machine’s key"></label>
    <label class="net-mine"><span class="net-mine-h">Your own SSH key ${pInfo('After password logins go off, only keys get in. Paste the .pub file from your own computer (~/.ssh/id_ed25519.pub) so you can still log in.')}</span>
      <input id="net-mine" autocomplete="off" spellcheck="false" placeholder="ssh-ed25519 AAAA… you@laptop"></label>
    <div class="dev-acts"><button class="endbtn" data-net="check" data-key="${esc(r.key)}">Check it</button>
      ${c&&!c.problems.length&&steps.some(s=>!c.done[s.id])?`<button class="wiz-next" data-net="go" data-key="${esc(r.key)}">Secure it</button>`:''}</div>
    ${c&&c.done.passwords?`<div class="net-letin"><p class="mut">Password logins are off there, so only keys get in. Bento’s key still does.</p>
      <div class="dev-acts"><button class="endbtn" data-net="letkey" data-key="${esc(r.key)}">Add my key</button>
      <button class="endbtn" data-net="letpw" data-key="${esc(r.key)}">Turn password logins back on</button></div></div>`:''}
    ${c?`<div class="net-steps">${(c.plan||[]).filter(p=>p.id==='yourkey').map(p=>`<div class="net-step"><span class="net-tick">＋</span>
        <div><b>${esc(p.title)}</b><br><span class="mut">${esc(p.why)}</span>
        <details><summary>What runs there</summary><code class="dev-plan">${esc(p.runs)}</code></details></div></div>`).join('')}${steps.map(s=>{const done=!!c.done[s.id],p=(c.plan||[]).find(x=>x.id===s.id);
      const on=sel[s.id]!==false;
      return `<div class="net-step${done?' done':''}">
        ${done?'<span class="net-tick">✓</span>':`<input type="checkbox" data-step="${esc(s.id)}" data-ip="${esc(r.ip)}" ${on?'checked':''} aria-label="${esc(s.title)}">`}
        <div><b>${esc(s.title)}</b>${done?' <span class="mut">already done</span>':''}<br><span class="mut">${esc(s.why)}</span>
        ${p&&!done?`<details><summary>What runs there</summary><code class="dev-plan">${esc(p.runs)}</code></details>`:''}</div></div>`}).join('')}
      ${c.problems.map(p=>`<p class="warn">✗ ${esc(p)}</p>`).join('')}
      ${c.host_key?`<p class="mut">Its key: ${esc(c.host_key)}</p>`:''}</div>`:''}
  </div>`;
}
/* Disconnect: each tie to this machine is its own tick, and nothing is removed until the
   person presses the button. Bento stays installed there; only the ties go. */
function netUnlinkForm(r){
  const cs=r.connections||[],needUser=cs.some(c=>c.kind==='key');
  return `<div class="dev-form net-form">
    <div class="net-steps">${cs.map(c=>`<label class="net-step"><input type="checkbox" data-unlink="${esc(c.id)}" checked>
      <div><b>${esc(netConnTitle(c))}</b><br><span class="mut">${esc(netConnWhy(c))}</span></div></label>`).join('')}</div>
    ${needUser?`<label>User there <input id="net-user" maxlength="32" placeholder="the user set in Imager" value="${esc(r.user||'')}"></label>`:''}
    <div class="dev-acts"><button class="wiz-next" data-net="unlinkgo" data-key="${esc(r.key)}">Disconnect</button></div>
  </div>`;
}
function netConnTitle(c){return c.kind==='link'?`The link “${c.label}”`:c.kind==='community'?'Its place in your community':'This machine’s SSH key on it'}
function netConnWhy(c){return c.kind==='link'?'Your agents and its agents stop asking each other, and the permissions that named the link go.'
  :c.kind==='community'?'It stops thinking with this machine’s brain and taking part in shared work.'
  :'Bento can no longer log in there without a password.'}
function netWire(box){
  box.querySelectorAll('[data-net]').forEach(b=>b.onclick=()=>netAct(b.dataset.net,b));
  box.querySelectorAll('[data-prov]').forEach(b=>b.onclick=()=>provAct(b.dataset.prov,b).then(()=>netPaint()));
  box.querySelectorAll('[data-step]').forEach(c=>c.onchange=()=>{
    const m=NET.steps[c.dataset.ip]=NET.steps[c.dataset.ip]||{};m[c.dataset.step]=c.checked});
}
function netRow(key){return ((NET.v||{}).rows||[]).find(r=>r.key===key)||{}}
async function netAct(act,b){
  const r=netRow(b.dataset.key);
  const post=async(url,body,method)=>{const res=await fetch(url,{method:method||'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
    const d=await res.json().catch(()=>({}));if(!res.ok)throw new Error(d.error||('could not do that ('+res.status+')'));return d};
  const creds=()=>({ip:r.ip,port:netPort(r),user:((document.getElementById('net-user')||{}).value||'').trim(),
    password:(document.getElementById('net-pw')||{}).value||'',mine:((document.getElementById('net-mine')||{}).value||'').trim()});
  try{
    if(act==='scan'){b.disabled=true;b.textContent='Looking…';const d=await post('/api/devices/scan');
      toast(d.found?`✓ ${d.found} machine${d.found===1?'':'s'} answered on ${d.networks}`:`Nothing answered on ${d.networks}.`);return netPaint()}
    if(act==='unlinkgo'){const what=[...document.querySelectorAll(`.net-m[data-key="${CSS.escape(r.key)}"] [data-unlink]`)]
        .filter(c=>c.checked).map(c=>c.dataset.unlink);
      if(!what.length){toast('Tick what to remove');return}
      const words=(r.connections||[]).filter(c=>what.includes(c.id)).map(c=>c.words);
      if(!await osConfirm(`Disconnect ${r.display||r.ip}?`,`This removes ${words.join(', ')}. Bento stays installed there.`,{confirmText:'Disconnect'}))return;
      const d=await post('/api/network/disconnect',{key:r.key,what,user:((document.getElementById('net-user')||{}).value||'').trim()});
      NET.open='';
      if((d.removed||[]).length)toast('✓ Removed '+d.removed.join(', '));
      (d.failed||[]).forEach(f=>toast('Could not remove '+f));
      return netPaint()}
    if(act==='install'||act==='secure'||act==='unlink'){const same=NET.open===r.key&&NET.mode===act;
      NET.open=same?'':r.key;NET.mode=same?'':act;if(act==='install')DEV.open=same?'':r.ip;return netPaint()}
    if(act==='label'){const n=prompt('A name for '+(r.display||r.ip),r.label||r.name||'');if(n===null)return;
      await post('/api/network/label',{key:r.key,label:n});return netPaint()}
    if(act==='forget'){await post('/api/network/forget',{key:r.key});return netPaint()}
    if(act==='check'){const c=creds();if(!c.user){toast('Who logs in there? Type the user name.');return}
      b.disabled=true;b.textContent='Checking…';
      try{NET.check[r.ip]=Object.assign(await post('/api/network/check',c),{user:c.user})}
      catch(e){delete NET.check[r.ip];throw e}finally{netPaint()}
      return}
    if(act==='letkey'||act==='letpw'){const c=creds();if(!c.user){toast('Who logs in there? Type the user name.');return}
      if(act==='letkey'&&!c.mine){toast('Paste your own SSH key first',{kind:'warn'});document.getElementById('net-mine')?.focus();return}
      b.disabled=true;
      const d=await post('/api/network/letin',act==='letkey'?{...c,passwords:false}:{...c,mine:'',passwords:true});
      toast(act==='letkey'?'✓ Your key is on '+(r.display||r.ip)+'. Log in with it from your computer.'
        :'✓ Password logins are back on '+(r.display||r.ip)+'.');
      if(NET.check[r.ip])NET.check[r.ip].done=d.security||NET.check[r.ip].done;return netPaint()}
    if(act==='go'){const c=creds(),sel=NET.steps[r.ip]||{};let chk=NET.check[r.ip]||{done:{}};
      // a key pasted after Check it: check again, so the step that adds it is shown before it runs
      if(c.mine&&!(chk.plan||[]).some(p=>p.id==='yourkey')){
        NET.check[r.ip]=chk=Object.assign(await post('/api/network/check',c),{user:c.user});netPaint()}
      const steps=((NET.v||{}).steps||[]).map(s=>s.id).filter(id=>!chk.done[id]&&sel[id]!==false);
      if(!steps.length&&!c.mine){toast('Tick at least one step');return}
      const titles=(c.mine?['let your own key in']:[]).concat(((NET.v||{}).steps||[]).filter(s=>steps.includes(s.id)).map(s=>s.title.toLowerCase()));
      const shut=steps.includes('passwords')&&!c.mine?' Your own password login stops too: only this machine’s key gets in until you add yours.':'';
      if(!await osConfirm(`Secure ${r.display||r.ip}?`,`This will ${titles.join(', ')}. The commands shown run there as ${c.user}.${shut}`,{confirmText:'Secure it'}))return;
      await post('/api/network/secure',{...c,steps});toast('Securing '+(r.display||r.ip)+'…');NET.open='';return netPaint()}
  }catch(e){toast(String(e.message||e),{kind:'err'});netPaint()}
}
function netPort(r){return r.ssh&&(r.ports||[]).length?Number(r.ports[0])||22:22}
function netLine(ev){
  const id='net-log-'+String(ev.ip||'').replace(/\W/g,'_');let el=document.getElementById(id);
  if(!el){const row=document.querySelector(`.net-m[data-ip="${CSS.escape(ev.ip||'')}"]`);if(!row)return;
    el=document.createElement('pre');el.className='dev-log';el.id=id;row.appendChild(el)}
  el.textContent=(el.textContent?el.textContent+'\n':'')+ev.line;el.scrollTop=el.scrollHeight;
}
