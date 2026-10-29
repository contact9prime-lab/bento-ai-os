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
/* A tie is called by its machine, as on both maps: the label is the link's own handle, which a
   reinstall makes raspberrypi-3, and every Zero's agent starts out with the same name. */
function topoName(t){return t.peer||t.label}

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
  if(t.mine===false)return `<div class="tm-row"><div class="tm-h">${face}<b>${esc(topoName(t))}</b><span class="mut">${esc(t.label)}</span><span class="brainchip">${kind}</span></div>
    <p class="mut">Belongs to ${esc(t.owner_name||'another account')}: they map it.</p></div>`;
  const lead=a.talks_to&&a.talks_to.to==='lead',name=topoName(t);
  return `<div class="tm-row${lead?' wide':''}">
    <div class="tm-h">${face}<b>${esc(name)}</b>${name!==t.label?`<span class="mut">${esc(t.label)}</span>`:''}<span class="brainchip">${kind}</span>
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

/* ---- the maps: one zoomable view for both (24s-zmap.js) ---- */
async function topoMapsPaint(){
  const box=document.getElementById('s-net-maps');if(!box)return;
  const v=TOPO.view;
  if(!box.querySelector('.tp-seg')){
    box.innerHTML=`<div class="seg tp-seg" role="tablist">${[['logical','Logical'],['physical','Physical']].map(([k,l])=>
        `<button role="tab" data-tp="${k}">${l}</button>`).join('')}<span class="sp"></span>
        <button class="endbtn" data-tp-open="1">Open it full</button></div>
      <p class="ghint tp-hint"></p><div class="tp-map zm-host"></div>`;
    box.querySelectorAll('[data-tp]').forEach(b=>b.onclick=()=>{TOPO.view=b.dataset.tp;topoMapsPaint()});
    box.querySelector('[data-tp-open]').onclick=()=>topoOpen(TOPO.view);
  }
  box.querySelectorAll('[data-tp]').forEach(b=>{b.classList.toggle('on',b.dataset.tp===v);b.setAttribute('aria-selected',b.dataset.tp===v)});
  box.querySelector('.tp-hint').textContent=v==='logical'?'Your lead, your companies and their departments, and who each Zero and team talks to. Tap anything to open it.'
    :'The devices this hub is connected to. Tap a group to open it.';
  const host=box.querySelector('.tp-map');
  // a different map in the same place starts fresh
  if(host.dataset.zmv!==v){host.dataset.zmv=v;host.innerHTML='';host.dataset.zm='net'+v}
  try{
    if(v==='logical'){TOPO.tree=await apiJSON('/api/network/logical');zmMount(host,zmLogical(TOPO.tree),{label:'The logical map'})}
    else{const nv=(typeof NET!=='undefined'&&NET.v)||await apiJSON('/api/network');zmMount(host,zmPhysical(nv),{label:'The device map'})}
  }catch(e){host.innerHTML=`<p class="mut">${esc(String(e.message||e))}</p>`}
}
function topoOpen(view){
  try{localStorage.setItem('devices.view',view)}catch(e){}
  openApp('devices');setTimeout(()=>{if(typeof devViewSet==='function')devViewSet(view)},500);
}
