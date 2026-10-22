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
var NET={ctl:{},v:null,open:'',mode:'',more:'',hiddenOpen:false,check:{},runs:{},steps:{},err:{},rekey:{}};

async function netPaint(){
  // Settings → Network and the Devices app draw the same list
  const boxes=[document.getElementById('s-net'),...document.querySelectorAll('.devhub-box')].filter(Boolean);
  if(!boxes.length)return;
  let v;try{v=await apiJSON('/api/network')}catch(e){boxes.forEach(b=>b.innerHTML=`<p class="mut prov-empty">${esc(String(e.message||e))}</p>`);return}
  NET.v=v;
  const can=v.can_change,rows=[],s=v.summary||{};
  rows.push(pRow('Machines',`<button class="endbtn" data-net="scan"${can?'':' disabled'}>Look at the network</button>`,
    {desc:s.machines?`${s.machines} found · ${s.bento} with Bento · ${s.secured} secured`
      :'Look at the network to list the machines on it.',
     more:'Only this machine’s own private network is looked at. A Raspberry Pi says its name when it joins, and you get a toast.',
     f:'network inventory devices machines scan discover list'}));
  if(v.ssh_missing)rows.push(`<p class="mut prov-empty">${esc(v.ssh_missing)}</p>`);
  const fw=v.firewall||{};
  if(fw.words&&can)rows.push(`<div class="net-fw"><p>${esc(fw.words)} ${typeof pInfo!=='function'?'':pInfo('Without them a Pi set up from here can’t join it, hand work over or send code too big for it. Or run: '+(fw.commands||[]).join(' ; '))}</p>
    <div class="net-fw-acts"><button class="endbtn" data-net="fw-open">Open them</button>
    <button class="endbtn" data-net="fw-done">I opened them</button></div></div>`);
  const list=(v.rows||[]).filter(r=>!r.ignored),hidden=(v.rows||[]).filter(r=>r.ignored);
  if(list.length)rows.push(`<div class="net-list">${list.map(r=>netRowHTML(r,v,can)).join('')}</div>`);
  else if(s.machines===0&&!hidden.length)rows.push(`<p class="mut prov-empty">Nothing listed yet.</p>`);
  if(hidden.length)rows.push(netHiddenHTML(hidden,can));
  // keep what is being typed across a repaint (a broadcast, a line of a running step)
  const kept={};['ctl-user','ctl-pw','ctl-pw-keep','net-user','net-pw','net-pw-keep','net-mine','dev-user','dev-pw','dev-agent','dev-auth','dev-kiosk'].forEach(id=>{
    const e=document.getElementById(id);if(e)kept[id]=e.type==='checkbox'?e.checked:e.value});
  boxes.forEach(box=>{box.innerHTML=(box.classList.contains('devhub-box')&&typeof devMapHTML==='function'?devMapHTML(v):'')
    +rows.join('');netWire(box)});
  Object.keys(kept).forEach(id=>{const e=document.getElementById(id);if(!e)return;
    if(e.type==='checkbox')e.checked=kept[id];else if(kept[id])e.value=kept[id]});
}

/* One pill: what it is to Bento, and once it was measured, how secure. "not checked" was a
   second pill on every row and said nothing a person could act on. */
function netBadge(r){
  const b={none:'No Bento',waiting:'Bento, waiting',['set up']:'Bento',linked:'Bento, linked',installed:'Bento',removed:'Bento removed'}[r.bento]||r.bento;
  const sec=r.secured_n<0?'':r.security_words==='secured'?' · secured':' · '+r.security_words;
  const cls=r.secured_n<0?(r.bento==='none'?'':'on'):r.security_words==='secured'?'ok':'warn';
  return `<span class="net-b ${cls}">${esc(b+sec)}</span>`;
}
/* The one thing a row is for, as its button; the rest is behind ⋯ so a phone shows two
   buttons a row, not five. */
function netMain(r,v){
  // a Bento waiting to be set up is set up below (New machines), with its code
  if(r.bento==='waiting')return `<button class="endbtn" data-net="setup" data-key="${esc(r.key)}">Set it up</button>`;
  if(v.ssh_missing||!r.ip)return '';
  // while Bento installs there, the card under the row is the only thing to look at
  if(((v.installs||{})[r.ip]||{}).state==='running')return '';
  if((r.bento==='none'||r.bento==='removed')&&r.ssh)return `<button class="endbtn" data-net="install" data-key="${esc(r.key)}">${r.bento==='removed'?'Install it again':'Install Bento'}</button>`;
  if(['set up','linked','installed'].includes(r.bento))return `<button class="endbtn" data-net="controls" data-key="${esc(r.key)}">Controls</button>`;
  if(r.ssh||r.bento!=='none'||r.secured_n>=0)
    return `<button class="endbtn" data-net="secure" data-key="${esc(r.key)}">${r.secured_n<0?'Secure it':'Security'}</button>`;
  return '';
}
function netRowHTML(r,v,can){
  const open=NET.open===r.key,run=(v.secures||{})[r.ip]||{},inst=(v.installs||{})[r.ip]||{};
  const what=r.board||r.maker||r.os||'';
  const seen=r.age==null?'':r.stale?'not heard for a week':r.age<120?'heard just now':'heard '+poolAgo(r.age);
  const busy=run.state==='running'?'securing…':inst.state==='running'?'installing Bento…':'';
  const more=NET.more===r.key;
  return `<div class="net-m${open?' open':''}${r.stale?' stale':''}" data-key="${esc(r.key)}" data-ip="${esc(r.ip||'')}">
    <div class="net-top">
      <b title="${esc(r.mac||'')}">${esc(r.display)}</b>${netBadge(r)}
      <span class="mut">${[r.ip,what,r.owner_name?'for '+r.owner_name:'',busy||seen].filter(Boolean).map(esc).join(' · ')}</span>
      ${netSwitchLine(r)}
    </div>
    ${can?`<div class="net-acts">${netMain(r,v)}
      <button class="endbtn net-more-b" data-net="more" data-key="${esc(r.key)}" aria-expanded="${more}" aria-label="More for ${esc(r.display)}">⋯</button></div>
      ${more?`<div class="net-more">
        ${/data-net="(install|controls)"/.test(netMain(r,v))&&r.ip&&!v.ssh_missing?`<button class="endbtn" data-net="secure" data-key="${esc(r.key)}">${r.secured_n<0?'Secure it':'Security'}</button>`:''}
        ${(r.connections||[]).length?`<button class="endbtn" data-net="unlink" data-key="${esc(r.key)}">Disconnect</button>`:''}
        <button class="endbtn" data-net="label" data-key="${esc(r.key)}">Rename</button>
        <button class="endbtn" data-net="forget" data-key="${esc(r.key)}">Hide</button></div>`:''}`:''}
    ${r.ssh_off?`<p class="mut net-hint">${esc(r.ssh_off)}</p>`:''}
    ${open&&NET.mode==='install'?provDevForm({ip:r.ip,ssh:r.ssh,ports:r.ports||[]}):devProgHTML(r.ip)}
    ${open&&NET.mode==='secure'?netSecureForm(r):''}
    ${open&&NET.mode==='controls'?netControlsForm(r,v):''}
    ${open&&NET.mode==='unlink'?netUnlinkForm(r):''}
    ${netLogHTML('net-log-',r.ip,run)}
  </div>`;
}
/* Hidden machines stay one tap away. Hide was "Not this one", and with nothing listing what
   it hid, a machine rejected by mistake could never be set up from here again. */
function netHiddenHTML(hidden,can){
  return `<details class="net-hidden"${NET.hiddenOpen?' open':''}><summary>Hidden (${hidden.length})</summary>
    ${hidden.map(r=>`<div class="net-h"><span><b>${esc(r.display)}</b> <span class="mut">${esc([r.ip,r.board||r.maker,r.bento==='waiting'?'waiting to be set up':''].filter(Boolean).join(' · '))}</span></span>
      ${can?`<button class="endbtn" data-net="show" data-key="${esc(r.key)}">Show again</button>`:''}</div>`).join('')}</details>`;
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
    ${devPwHTML('net-pw',r.ip,(c&&c.user)||r.user||'')}
    <label class="net-mine"><span class="net-mine-h">Your own SSH key ${pInfo('After password logins go off, only keys get in. Paste the .pub file from your own computer (~/.ssh/id_ed25519.pub) so you can still log in.')}</span>
      <input id="net-mine" autocomplete="off" spellcheck="false" placeholder="ssh-ed25519 AAAA… you@laptop"></label>
    <div class="dev-acts"><button class="endbtn" data-net="check" data-key="${esc(r.key)}">Check it</button>
      ${c&&!c.problems.length&&steps.some(s=>!c.done[s.id])?`<button class="wiz-next" data-net="go" data-key="${esc(r.key)}">Secure it</button>`:''}</div>
    ${NET.err[r.ip]?`<p class="warn dev-err">✗ ${esc(NET.err[r.ip])}</p>`:''}
    ${sshRekeyHTML(r.ip,netPort(r),NET.rekey[r.ip])}
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
/* Its lead agent's look, changed there: picks from the closed set the editor here draws, or a
   description in words (its own designer picks). The face is painted HERE from its recipe. */
var LOOK_FIELDS=[['skin','Skin'],['hair','Hair'],['style','Hair style'],['outfit','Outfit'],['shirt','Shirt'],['pants','Trousers']];
function netLookHTML(r,st,v){
  const ch=v.look_choices||{},look=st.look||{};
  const cur=f=>{if(f==='shirt')return Object.keys(ch.hues||{}).find(n=>ch.hues[n]===look.hue)||'';
    const x=look[f];return typeof x==='number'?(ch[f]||[])[x]||'':String(x||'')};
  return `<div class="net-look"><div class="net-look-h">${look&&Object.keys(look).length?avatarRecipeImg(look,'net-look-face',st.agent||'its agent'):''}
      <div><b>${esc(st.agent||'Its agent')}</b><br><span class="mut">How its agent looks there: on its screen, in its Office, and on the map here.</span></div></div>
    <div class="net-look-grid">${LOOK_FIELDS.map(([f,t])=>`<label>${t}<select data-look="${f}">
      <option value="">${cur(f)?esc(cur(f)):'as it is'}</option>${(ch[f]||[]).filter(o=>o!==cur(f)).map(o=>`<option value="${esc(o)}">${esc(o)}</option>`).join('')}</select></label>`).join('')}
      <label class="prov-opt"><input type="checkbox" data-look="glasses"${look.glasses?' checked':''}> Glasses</label>
      <label class="prov-opt"><input type="checkbox" data-look="blush"${look.blush?' checked':''}> Blush</label></div>
    <div class="dev-acts"><button class="endbtn" data-net="ctllook" data-key="${esc(r.key)}">Save its look</button></div>
    <label class="net-look-say">Or describe it <input id="ctl-look-say" maxlength="200" placeholder="a cheerful chef with curly grey hair"></label>
    <div class="dev-acts"><button class="endbtn" data-net="ctldesign" data-key="${esc(r.key)}">Design it</button></div></div>`;
}
/* What its switches were last READ as, in one line under the row: the inventory keeps it
   with the time, and nothing here guesses. */
function netSwitchLine(r){
  const c=(r.controls||{}).state;if(!c||r.bento==='removed')return '';
  const ago=r.controls.at?poolAgo(Math.max(0,Math.round(Date.now()/1000-r.controls.at))):'';
  const w=[c.running?'running':'stopped',c.screen?'opens on its screen':'',c.showing&&!c.screen?'still shows Bento on its screen':'',c.listening?'listening':'',
    r.code_handoff?'big code here':'',c.version?'v'+c.version:''].filter(Boolean).join(' · ');
  return `<span class="mut net-sw-line">${esc(w)}${ago?` <span class="net-sw-at">(read ${esc(ago)})</span>`:''}</span>`;
}
function netControlsForm(r,v){
  const c=NET.ctl[r.ip],st=(c&&c.state)||null,sw=(v.switches||[]);
  const row=s=>{const on=s.id==='code'?r.code_handoff:st&&st[s.id];const known=s.id==='code'?r.code_handoff!=null:!!st;
    const cmd=c&&c.commands&&c.commands[s.id];
    return `<div class="net-sw${on?' on':''}">
      <div><b>${esc(s.title)}</b> <span class="mut">${known?(on?'on':'off'):s.id==='code'?'it isn’t linked to this computer':'not read yet'}</span><br><span class="mut">${esc(s.why)}</span>
      ${cmd?`<details><summary>What runs there</summary><code class="dev-plan">on: ${esc(cmd.on)}\noff: ${esc(cmd.off)}</code></details>`:''}</div>
      ${known&&(s.id==='code'||st.installed)?`<button class="endbtn" data-net="ctlsw" data-sw="${esc(s.id)}" data-on="${on?0:1}" data-key="${esc(r.key)}">${on?'Turn off':'Turn on'}</button>`:''}
    </div>`};
  return `<div class="dev-form net-form">
    <label>User there <input id="ctl-user" maxlength="32" value="${esc(r.user||'')}" placeholder="the user set in Imager"></label>
    ${devPwHTML('ctl-pw',r.ip,r.user||'')}
    <div class="dev-acts"><button class="endbtn" data-net="ctlread" data-key="${esc(r.key)}">${st?'Read again':'Read its switches'}</button>
      ${st&&st.installed?`<button class="endbtn" data-net="ctlupdate" data-key="${esc(r.key)}">Update Bento there${st.version?' ('+esc(st.version)+')':''}</button>`:''}</div>
    ${NET.err[r.ip]?`<p class="warn dev-err">✗ ${esc(NET.err[r.ip])}</p>`:''}
    ${sshRekeyHTML(r.ip,netPort(r),NET.rekey[r.ip])}
    <div class="net-sws">${sw.map(row).join('')}</div>
    ${st&&st.installed?netLookHTML(r,st,v):''}
    ${st&&st.installed?`<div class="net-remove"><b>Remove Bento</b><br><span class="mut">Takes the program off and ends its ties to this computer. Its memory and settings stay there, so installing it again picks up where it was.</span>
      <details><summary>What runs there</summary><code class="dev-plan">${esc(c.remove||'')}</code></details>
      <div class="dev-acts"><button class="endbtn danger" data-net="ctlremove" data-key="${esc(r.key)}">Remove Bento</button></div></div>`:''}
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
  if(box.querySelector('.dev-prog.running')&&typeof devProgTick==='function')devProgTick();
  box.querySelectorAll('[data-net]').forEach(b=>b.onclick=()=>netAct(b.dataset.net,b));
  box.querySelectorAll('[data-pwforget]').forEach(b=>b.onclick=()=>devPwForget(b));
  box.querySelectorAll('[data-devnode]').forEach(n=>n.onclick=()=>devMapGo(n.dataset.devnode));
  const hd=box.querySelector('.net-hidden');if(hd)hd.ontoggle=()=>{NET.hiddenOpen=hd.open};
  box.querySelectorAll('[data-prov]').forEach(b=>b.onclick=()=>provAct(b.dataset.prov,b).then(()=>netPaint()));
  // the command shown after Check it follows the switch: --screen is its last flag, the same
  // string the server builds (remoteinstall.plan), so what runs is still what was shown
  const ks=box.querySelector('#dev-kiosk');
  if(ks)ks.onchange=()=>{const ip=DEV.open,c=DEV.check[ip];if(!c||!c.plan)return;
    c.plan=c.plan.replace(/ --screen$/,'')+(ks.checked?' --screen':'');
    const el=box.querySelector('.dev-plan');if(el)el.textContent=c.plan};
  box.querySelectorAll('[data-step]').forEach(c=>c.onchange=()=>{
    const m=NET.steps[c.dataset.ip]=NET.steps[c.dataset.ip]||{};m[c.dataset.step]=c.checked});
}
function netRow(key){return ((NET.v||{}).rows||[]).find(r=>r.key===key)||{}}
async function netAct(act,b){
  const r=netRow(b.dataset.key);
  const post=async(url,body,method)=>{const res=await fetch(url,{method:method||'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
    const d=await res.json().catch(()=>({}));if(!res.ok)throw Object.assign(new Error(d.error||('could not do that ('+res.status+')')),{data:d});return d};
  const creds=()=>({ip:r.ip,port:netPort(r),user:((document.getElementById('net-user')||{}).value||'').trim(),
    password:(document.getElementById('net-pw')||{}).value||'',remember:devPwKeep('net-pw'),mine:((document.getElementById('net-mine')||{}).value||'').trim()});
  try{
    if(act==='fw-open'||act==='fw-done'){b.disabled=true;
      try{await post('/api/network/firewall',{action:act==='fw-open'?'open':'done'});
        toast(act==='fw-open'?'✓ The ports are open':'Noted')}
      catch(e){const n=((e.data||{}).needs||[]).join(' ; ');toast(n?`${e.message}. Run: ${n}`:e.message,{kind:'err'})}
      return netPaint()}
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
    if(act==='controls'){NET.more='';const same=NET.open===r.key&&NET.mode==='controls';
      NET.open=same?'':r.key;NET.mode=same?'':'controls';return netPaint()}
    if(act==='ctlread'||act==='ctlsw'||act==='ctlremove'||act==='ctlupdate'||act==='ctllook'||act==='ctldesign'){
      const cr={ip:r.ip,key:r.key,port:netPort(r),user:((document.getElementById('ctl-user')||{}).value||'').trim(),
        password:(document.getElementById('ctl-pw')||{}).value||'',remember:devPwKeep('ctl-pw')};
      if(act!=='ctlsw'||b.dataset.sw!=='code')if(!cr.user){toast('Type the user there first');return}
      if(act==='ctlremove'&&!await osConfirm(`Remove Bento from ${r.display||r.ip}?`,
        'It stops, the program is taken off, and its ties to this computer end. Its memory and settings stay there.',{confirmText:'Remove Bento'}))return;
      b.disabled=true;const was=b.textContent;b.textContent=act==='ctlremove'?'Removing…':act==='ctlread'?'Reading…':act==='ctlupdate'?'Updating… (a few minutes)':'Working…';
      NET.err[r.ip]='';
      try{
        if(act==='ctlread'){const d=await post('/api/network/controls',cr);NET.ctl[r.ip]=d}
        else if(act==='ctllook'||act==='ctldesign'){
          const box=b.closest('.net-look'),body={...cr};
          if(act==='ctldesign'){body.describe=((document.getElementById('ctl-look-say')||{}).value||'').trim();
            if(!body.describe){toast('Say what it should look like');b.disabled=false;b.textContent=was;return}}
          else{const st0=(NET.ctl[r.ip]||{}).state||{},ch={};
            box.querySelectorAll('select[data-look]').forEach(e=>{if(e.value)ch[e.dataset.look]=e.value});
            box.querySelectorAll('input[data-look]').forEach(e=>{if(!!e.checked!==!!(st0.look||{})[e.dataset.look])ch[e.dataset.look]=e.checked});
            if(!Object.keys(ch).length){toast('Choose what to change first');b.disabled=false;b.textContent=was;return}
            body.changes=ch}
          const d=await post('/api/network/look',body);
          NET.ctl[r.ip]={...(NET.ctl[r.ip]||{}),state:d.state};
          toast(`✓ ${d.state.agent||'Its agent'} has a new look on ${r.display||r.ip}`)}
        else if(act==='ctlupdate'){const d=await post('/api/network/update',cr);
          NET.ctl[r.ip]={...(NET.ctl[r.ip]||{}),state:d.state};
          toast(`✓ ${r.display||r.ip}: ${d.before||'?'} → ${(d.state||{}).version||'?'}`)}
        else if(act==='ctlsw'){const on=b.dataset.on==='1';
          const d=await post('/api/network/switch',{...cr,switch:b.dataset.sw,on});
          if(d.state)NET.ctl[r.ip]={...(NET.ctl[r.ip]||{}),state:d.state};
          toast(`✓ ${(((NET.v||{}).switches||[]).find(x=>x.id===b.dataset.sw)||{}).title||b.dataset.sw} ${on?'on':'off'} on ${r.display||r.ip}`)}
        else{const d=await post('/api/network/remove',cr);delete NET.ctl[r.ip];NET.open='';
          toast(d.ok?`✓ Bento removed from ${r.display||r.ip}${(d.ended||[]).length?'; ended '+d.ended.join(', '):''}`:'It may not all be gone: read its switches again',{kind:d.ok?'ok':'warn'})}
      }catch(e){const d=e.data||{};if(d.key_changed)NET.rekey[r.ip]=d.key_changed;NET.err[r.ip]=e.message;
        if(d.state)NET.ctl[r.ip]={...(NET.ctl[r.ip]||{}),state:d.state}}
      b.disabled=false;b.textContent=was;return netPaint()}
    if(act==='install'||act==='secure'||act==='unlink'){NET.more='';const same=NET.open===r.key&&NET.mode===act;
      NET.open=same?'':r.key;NET.mode=same?'':act;if(act==='install')DEV.open=same?'':r.ip;return netPaint()}
    if(act==='label'){const n=prompt('A name for '+(r.display||r.ip),r.label||r.name||'');if(n===null)return;
      await post('/api/network/label',{key:r.key,label:n});return netPaint()}
    if(act==='setup'){const m=[...document.querySelectorAll('.prov-m')].find(e=>e.textContent.includes(r.name||r.display));
      if(!m){toast('It is not waiting any more. Press Look at the network.');return}
      m.scrollIntoView({block:'center',behavior:'smooth'});const c=m.querySelector('[data-pick]');if(c&&!c.disabled&&!c.checked)c.click();
      (m.querySelector('.prov-code')||m.querySelector('.prov-name'))?.focus({preventScroll:true});return}
    if(act==='more'){NET.more=NET.more===r.key?'':r.key;return netPaint()}
    if(act==='forget'){await post('/api/network/forget',{key:r.key});NET.more='';
      toast(`${r.display||r.ip} is hidden. It is under Hidden if you want it back.`);
      if(typeof provPaint==='function')provPaint();return netPaint()}
    if(act==='show'){await post('/api/network/show',{key:r.key});
      toast(`✓ ${r.display||r.ip} is listed again`);if(typeof provPaint==='function')provPaint();return netPaint()}
    if(act==='check'){const c=creds();if(!c.user){toast('Who logs in there? Type the user name.');return}
      b.disabled=true;b.textContent='Checking…';
      try{NET.check[r.ip]=Object.assign(await post('/api/network/check',c),{user:c.user});delete NET.err[r.ip];delete NET.rekey[r.ip]}
      catch(e){delete NET.check[r.ip];
        // kept under Check it, like the install form: a changed key needs a decision, not a toast
        if(e.data&&e.data.key_changed){NET.err[r.ip]=String(e.message||e);NET.rekey[r.ip]=e.data.key_changed;return}
        delete NET.err[r.ip];delete NET.rekey[r.ip];throw e}finally{netPaint()}
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
