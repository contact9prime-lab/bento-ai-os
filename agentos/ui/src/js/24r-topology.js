/* ---------------- Network & Teams: who each tie talks to, and the maps ----------------
   Asked for as "the Zeros or the teams can talk to either Aria, which controls all the
   departments, or to each department only … caution the user that Aria will have access to many
   things", "Team to agent mapping: show the users what all they have given it access to", and
   "Maps, where the logical maps and the physical maps can be opened … all the way to the
   permission level".

   - Mapping (topoMappingPaint): every Zero and linked team, with Talks to (your lead or one
     department), and what that gives it, read from topology.access: who answers, the people and
     tools they reach, which of your agents it may also ask, and every permission row naming it.
     Talking to the lead carries the caution in words.
   - Maps (topoMapsPaint, and the Devices app's Logical view): the logical map is topology.logical
     (lead, companies, departments, people, down to each one's executor, brain, tools and
     permissions, with each tie hung from what it talks to); the physical map is the device map
     (devMapHTML), the same one Devices opens on.
   TUI: `bento network map`, `bento network ties`. SUI: this page. `var`/functions only. */
var TOPO={ties:null,targets:null,access:{},open:{},view:'logical',tree:null};

async function topoTies(){
  try{return (await apiJSON('/api/network/ties')).ties||[]}catch(e){}
  // not an admin: your own links, from Team Chat's list
  try{const d=await apiJSON('/api/team/links');
    return (d.links||[]).map(lk=>({label:lk.label,kind:lk.kind==='account'?'account':'team',peer:lk.peer_name||lk.label,
      owner:lk.owner||'',mine:true,talks_to:lk.talks_to||{to:'lead'},agent:{}}))}catch(e){return []}
}
function topoKey(t){return (t.owner||'')+'|'+t.label}

async function topoMappingPaint(){
  const box=document.getElementById('s-net-mapping');if(!box)return;
  const [ties,targets]=await Promise.all([topoTies(),apiJSON('/api/network/targets').catch(()=>({companies:[],lead:'Aria'}))]);
  TOPO.ties=ties.filter(t=>!t.stale);TOPO.targets=targets;
  if(!TOPO.ties.length){box.innerHTML='<p class="mut">No Zeros or linked teams yet. Link one in Discovery and linkage above.</p>';return}
  await Promise.all(TOPO.ties.filter(t=>t.mine!==false).map(async t=>{
    try{TOPO.access[topoKey(t)]=await apiJSON(`/api/network/ties/${encodeURIComponent(t.label)}/access?owner=${encodeURIComponent(t.owner||'')}`)}
    catch(e){TOPO.access[topoKey(t)]={error:String(e.message||e)}}}));
  box.innerHTML=`<div class="tm-list">${TOPO.ties.map(topoRowHTML).join('')}</div>`;
  box.querySelectorAll('[data-tm=target]').forEach(sel=>sel.onchange=()=>topoSetTarget(sel));
  box.querySelectorAll('[data-tm=more]').forEach(b=>b.onclick=()=>{TOPO.open[b.dataset.k]=!TOPO.open[b.dataset.k];topoMappingPaint()});
}
function topoTargetSelect(t){
  const tt=t.talks_to||{to:'lead'},cur=tt.to==='department'?`d|${tt.company||''}|${tt.department}`:'lead';
  const T=TOPO.targets||{companies:[]};
  const opts=[`<option value="lead"${cur==='lead'?' selected':''}>${esc(T.lead||'Aria')}: everything (all departments)</option>`];
  (T.companies||[]).forEach(c=>{if(!(c.departments||[]).length)return;
    opts.push(`<optgroup label="${esc(c.name)}">`+c.departments.map(d=>{const v=`d|${c.id}|${d.name}`;
      return `<option value="${esc(v)}"${v===cur||(tt.to==='department'&&!tt.company&&c.open&&tt.department===d.name)?' selected':''}${d.desk?'':' disabled'}>${esc(d.name)}${d.desk?'':' (no desk yet)'}</option>`}).join('')+'</optgroup>')});
  return `<select data-tm="target" data-label="${esc(t.label)}" data-owner="${esc(t.owner||'')}" aria-label="Who ${esc(t.label)} talks to">${opts.join('')}</select>`;
}
function topoRowHTML(t){
  const k=topoKey(t),a=TOPO.access[k]||{},open=!!TOPO.open[k];
  const kind=t.kind==='zero'?'Zero':t.kind==='account'?'Account':'Team';
  const face=(t.agent&&t.agent.look&&typeof avatarRecipeImg==='function')?avatarRecipeImg(t.agent.look,'av-tool',t.peer):`<span class="tm-ini">${esc((t.peer||t.label||'?')[0].toUpperCase())}</span>`;
  if(t.mine===false)return `<div class="tm-row"><div class="tm-h">${face}<b>${esc(t.label)}</b><span class="brainchip">${kind}</span></div>
    <p class="mut">Belongs to ${esc(t.owner_name||'another account')}: they map it.</p></div>`;
  const lead=a.talks_to&&a.talks_to.to==='lead';
  return `<div class="tm-row${lead?' wide':''}">
    <div class="tm-h">${face}<b>${esc(t.label)}</b><span class="brainchip">${kind}</span>
      <span class="sp"></span><label class="tm-to"><span>Talks to</span>${topoTargetSelect(t)}</label></div>
    ${a.error?`<p class="tie-warn">${esc(a.error)}</p>`:''}
    ${a.caution?`<p class="tm-caution">⚠ ${esc(a.caution)}</p>`:''}
    <button class="endbtn tm-more" data-tm="more" data-k="${esc(k)}" aria-expanded="${open}">${open?'Hide':'What it can reach'}</button>
    ${open?topoAccessHTML(a):''}
  </div>`;
}
function topoAccessHTML(a){
  const people=(a.reach||[]).map(p=>`<li><b>${esc(p.name)}</b> <span class="mut">${esc(p.hands)}${p.brain?' · '+esc(p.brain):''}</span>
      <div class="tm-tools">${(p.tools||[]).map(x=>`<span class="brainchip">${esc(x)}</span>`).join(' ')||'<span class="mut">no tools of its own</span>'}</div>
      ${p.allow||p.deny?`<div class="mut tm-perm">${p.allow} allowed, ${p.deny} refused</div>`:''}</li>`).join('');
  return `<div class="tm-access">
    <div><span class="ag-k">Answers here</span>${esc(a.words||'')}${a.persona?` <span class="mut">· ${esc(a.persona)}</span>`:''}</div>
    ${(a.tools||[]).length?`<div><span class="ag-k">Through</span>${a.tools.map(x=>`<span class="brainchip">${esc(x)}</span>`).join(' ')}</div>`:''}
    <div><span class="ag-k">Can reach</span>${people?`<ul class="tm-people">${people}</ul>`:'<span class="mut">nobody</span>'}</div>
    <div><span class="ag-k">Also may ask</span>${(a.asks||[]).length?a.asks.map(esc).join(', '):'<span class="mut">none of your agents directly</span>'}</div>
    <div><span class="ag-k">Permissions</span>${(a.grants||[]).length?`<ul class="tm-grants">${a.grants.map(g=>`<li class="${g.effect==='deny'?'bad':''}">${esc(g.words)}${g.source?` <span class="mut">(${esc(g.source)})</span>`:''}</li>`).join('')}</ul>`:'<span class="mut">none written for it</span>'}
      <button class="endbtn" onclick="openApp('permissions')">Open</button></div>
  </div>`;
}
async function topoSetTarget(sel){
  const v=sel.value,body={owner:sel.dataset.owner};
  if(v==='lead')body.to='lead';else{const [,company,...d]=v.split('|');Object.assign(body,{to:'department',company,department:d.join('|')})}
  sel.disabled=true;
  try{const r=await apiJSON(`/api/network/ties/${encodeURIComponent(sel.dataset.label)}/target`,{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify(body)});
    toast(body.to==='lead'?`${sel.dataset.label} talks to ${r.words} now, who can reach every department and agent`:`✓ ${sel.dataset.label} talks to ${r.words}`,
      body.to==='lead'?{kind:'warn'}:{})}catch(e){toast(String(e.message||e),{kind:'err'})}
  TOPO.tree=null;await topoMappingPaint();topoMapsPaint();
}

/* ---- the maps ---- */
async function topoMapsPaint(){
  const box=document.getElementById('s-net-maps');if(!box)return;
  try{TOPO.tree=await apiJSON('/api/network/logical')}catch(e){box.innerHTML=`<p class="mut">${esc(String(e.message||e))}</p>`;return}
  const v=TOPO.view;
  box.innerHTML=`<div class="seg tp-seg" role="tablist">${[['logical','Logical'],['physical','Physical']].map(([k,l])=>
      `<button role="tab" class="${v===k?'on':''}" aria-selected="${v===k}" data-tp="${k}">${l}</button>`).join('')}
      <span class="sp"></span><button class="endbtn" onclick="topoOpen('${v}')">Open it full</button></div>
    <p class="ghint">${v==='logical'?'Your lead, your companies, their departments and people, and who each Zero and team talks to. Tap anyone to see their permissions.'
      :'The devices this hub is connected to: Zeros, linked teams and the rest of your network.'}</p>
    <div class="tp-body">${v==='logical'?topoTreeHTML(TOPO.tree):((typeof NET!=='undefined'&&NET.v&&typeof devMapHTML==='function')?devMapHTML(NET.v):'<p class="mut">The device map needs an admin: it names the machines on this network.</p>')}</div>`;
  box.querySelectorAll('[data-tp]').forEach(b=>b.onclick=()=>{TOPO.view=b.dataset.tp;topoMapsPaint()});
  topoTreeWire(box);
  if(v==='physical'&&typeof devMapWire==='function')devMapWire(box);
}
function topoOpen(view){
  try{localStorage.setItem('devices.view',view)}catch(e){}
  openApp('devices');setTimeout(()=>{if(typeof devViewSet==='function')devViewSet(view)},500);
}
function topoTieChips(ts){
  return (ts||[]).map(x=>`<span class="tp-tie ${esc(x.kind||'team')}${x.answering===false?' off':''}" title="${esc(x.label)} talks to this">${x.kind==='zero'?'◫':'⇄'} ${esc(x.label)}${x.missing?' · '+esc(x.missing)+' is gone':''}</span>`).join('');
}
function topoPersonHTML(p,path){
  const on=!!TOPO.open['p:'+path];
  const fams=Object.entries(p.families||{});
  return `<li class="tp-li"><button class="tp-node person${p.head?' head':''}" data-tpk="p:${esc(path)}" aria-expanded="${on}">
      ${typeof avatarImg==='function'?avatarImg(p.lead?'@agent':p.name,'av-tool'):''}<b>${esc(p.label||p.name)}</b>${p.head?' <span class="mut">head</span>':''}</button>
    ${on?`<div class="tp-perm">
      <div><span class="ag-k">Executor</span>${esc(p.hands)}${p.hands_summary?` <span class="mut">${esc(p.hands_summary)}</span>`:''}</div>
      ${p.brain?`<div><span class="ag-k">Brain</span>${esc(p.brain)}</div>`:''}
      <div><span class="ag-k">Tools</span>${(p.tools||[]).map(x=>`<span class="brainchip">${esc(x==='*'?'every tool':x)}</span>`).join(' ')||'<span class="mut">none</span>'}</div>
      <div><span class="ag-k">Permissions</span>${p.autonomy?'autonomy '+esc(p.autonomy)+' · ':''}${p.allow} allowed, ${p.deny} refused${fams.length?' <span class="mut">('+fams.map(([k,v])=>esc(k)+' '+v.allow+(v.deny?'/'+v.deny+'✗':'')).join(', ')+')</span>':''}
        <button class="endbtn" onclick="openApp('permissions')">Open</button></div>
      ${(p.missions||[]).length?`<div><span class="ag-k">Missions</span>${p.missions.map(esc).join(', ')}</div>`:''}
    </div>`:''}</li>`;
}
function topoTreeHTML(tree){
  if(!tree)return '<p class="mut">…</p>';
  const L=tree.lead||{};
  return `<div class="tp-tree"><ul class="tp-ul root"><li class="tp-li">
    <div class="tp-row">${topoPersonHTML({...L,lead:true},'lead').replace(/^<li class="tp-li">|<\/li>$/g,'')}<span class="tp-ties">${topoTieChips(L.ties)}</span></div>
    <ul class="tp-ul">${(tree.companies||[]).map((c,ci)=>`<li class="tp-li"><div class="tp-node company${c.open?' open':''}">▦ <b>${esc(c.name)}</b>${c.open&&!c.default?' <span class="mut">open</span>':''}${c.about?` <span class="mut tp-about">${esc(c.about)}</span>`:''}</div>
      <ul class="tp-ul">${(c.departments||[]).map((d,di)=>`<li class="tp-li"><div class="tp-row"><div class="tp-node dept" style="--dc:${esc(d.color||'')}">▸ <b>${esc(d.name)}</b></div><span class="tp-ties">${topoTieChips(d.ties)}</span></div>
          <ul class="tp-ul">${(d.people||[]).map(p=>topoPersonHTML(p,ci+'/'+di+'/'+p.name)).join('')}</ul></li>`).join('')}
        ${(c.people||[]).map(p=>topoPersonHTML(p,ci+'//'+p.name)).join('')}
        ${c.auditor?topoPersonHTML({...c.auditor,label:c.auditor.name+', checks every department'},ci+'/auditor'):''}</ul></li>`).join('')}</ul>
  </li></ul></div>`;
}
function topoTreeWire(box){
  box.querySelectorAll('[data-tpk]').forEach(b=>b.onclick=()=>{TOPO.open[b.dataset.tpk]=!TOPO.open[b.dataset.tpk];
    const host=b.closest('.tp-body,.dev-logical');if(host){host.innerHTML=topoTreeHTML(TOPO.tree);topoTreeWire(host)}});
}
