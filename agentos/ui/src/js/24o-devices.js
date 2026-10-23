/* ---------------- Devices: the machines on your network, in a window of their own ----------------
   Asked for as "have these devices in the device hub in Bento". The same list as Settings →
   Network (netPaint draws into every .devhub-box), so the two never disagree: each machine,
   what it is to Bento, its switches as last read, Controls, Install and Remove. */
async function renderDevices(body,w){
  const pb=panelShell(body,{title:'Devices',sub:'The machines on your network'});
  /* Physical: the devices (the map, the list, Events). Logical: your lead, companies,
     departments and people, and who each Zero and team talks to (24r-topology.js). */
  pb.innerHTML=`<div class="seg dev-views" role="tablist">
      <button role="tab" data-dv="physical">Physical</button><button role="tab" data-dv="logical">Logical</button></div>
    <div class="dev-physical"><div class="devhub-box" id="devhub-${esc(w&&w.id||'0')}"><p class="mut">…</p></div>
    <section class="dev-events" aria-label="Events"><h3>Events</h3><div class="dev-ev-box"><p class="mut">…</p></div></section></div>
    <div class="dev-logical" hidden><p class="mut">…</p></div>`;
  pb.querySelectorAll('[data-dv]').forEach(b=>b.onclick=()=>devViewSet(b.dataset.dv));
  let v='physical';try{v=localStorage.getItem('devices.view')||'physical'}catch(e){}
  devViewSet(v);
  await netPaint();
  devEventsLoad();
}
async function devViewSet(v){
  try{localStorage.setItem('devices.view',v)}catch(e){}
  document.querySelectorAll('.dev-views [data-dv]').forEach(b=>{b.classList.toggle('on',b.dataset.dv===v);b.setAttribute('aria-selected',b.dataset.dv===v)});
  document.querySelectorAll('.dev-physical').forEach(x=>x.hidden=v!=='physical');
  const lg=[...document.querySelectorAll('.dev-logical')];lg.forEach(x=>x.hidden=v!=='logical');
  if(v!=='logical'||!lg.length)return;
  try{TOPO.tree=await apiJSON('/api/network/logical')}catch(e){lg.forEach(x=>x.innerHTML=`<p class="mut">${esc(String(e.message||e))}</p>`);return}
  lg.forEach(x=>{x.classList.add('zm-host');x.dataset.zm='devlogical';zmMount(x,zmLogical(TOPO.tree),{label:'The logical map'})});
}

/* Events: what happened to the machines here, newest first (devevents.py). Asked for as "in the
   devices section we need to have events": a Pi that moved to another address, stopped answering
   or came back, updated, had its screen refreshed, and every step done to a machine from here.
   A machine's own row has the same list for it alone (Events, 24p-ties.js). */
var DEVEV={list:null,all:false};
var DEVEV_ICON={moved:'⇄',offline:'○',online:'●',updated:'⬆',refreshed:'⟳',failed:'✗',installed:'✓',secured:'🔒'};
function devEventsList(list){
  const when=s=>new Date(s*1000).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
  return `<ul class="dev-ev">${list.map(e=>`<li class="dev-ev-${esc(e.event)}${e.failed?' bad':''}">
    <span class="dev-ev-i" aria-hidden="true">${DEVEV_ICON[e.event]||'·'}</span>
    <span class="dev-ev-t">${esc(e.text)}</span><time class="mut">${when(e.at)}</time></li>`).join('')}</ul>`;
}
async function devEventsLoad(){
  const boxes=[...document.querySelectorAll('.dev-ev-box')];if(!boxes.length)return;
  try{DEVEV.list=(await apiJSON('/api/network/events?limit=200')).events||[]}
  catch(e){boxes.forEach(b=>b.innerHTML=`<p class="mut">${esc(String(e.message||e))}</p>`);return}
  devEventsPaint();
}
function devEventsPaint(){
  const list=DEVEV.list||[],shown=DEVEV.all?list:list.slice(0,12);
  document.querySelectorAll('.dev-ev-box').forEach(b=>{
    b.innerHTML=list.length?devEventsList(shown)+(list.length>12?`<button class="endbtn dev-ev-more">${DEVEV.all?'Show fewer':'Show all '+list.length}</button>`:'')
      :'<p class="mut">Nothing has happened to the machines here yet.</p>';
    const m=b.querySelector('.dev-ev-more');if(m)m.onclick=()=>{DEVEV.all=!DEVEV.all;devEventsPaint()}});
}
/* A new one, live (server._device_event). A move also repaints the list: the address changed. */
function devEventLive(ev){
  if(DEVEV.list)DEVEV.list.unshift({at:Date.now()/1000,event:ev.event,label:ev.label,text:ev.text});
  devEventsPaint();
  if(ev.event==='moved'){toast('⇄ '+ev.text);if(typeof netPaint==='function')netPaint()}
}

/* The map: this computer in the middle with its lead agent, the Zeros it set up on the ring
   nearest it, the teams it is linked with on the next one, other machines running Bento between,
   and the rest of the network as small dots on the edge, so twenty phones don't crowd the Pis.
   Every node is a tie Network lists too (ties.py, inventory.py), so the map and the list agree:
   a Zero's line is solid, a team's dashed, one that is not answering grey; a node working right
   now (a Zero's chat run here, zero_work) glows and says so. Tapping a node opens its row below.
   Positions are percentages, so it fits any width; faces are painted here from recipes. */
var DEVMAP={busy:{}};
/* The device map is the zoomable map (24s-zmap.js) over the same rows and ties as the list:
   this computer in the middle, then Zeros, linked teams, Bento machines and the other devices,
   each a group you open. It used to be every machine at once, on rings. */
function devMapHTML(v){
  const ties=(v.ties||[]).filter(t=>!t.stale),n=k=>ties.filter(t=>t.kind===k).length;
  return `<div class="dm-wrap"><div class="zm-host dm-zm" data-zm="devphysical"></div>
    <div class="dm-legend"><span class="zero"><i></i>Zero ${n('zero')}</span><span class="team"><i></i>Team ${n('team')+n('account')}</span>
      <span class="off"><i></i>not answering</span></div></div>`;
}
/* A node working right now: a Zero's chat run here (fabric.zero_chat broadcasts zero_work). */
function devMapPulse(ev){
  const k=ev.zero;if(!k)return;
  if(ev.phase==='start')DEVMAP.busy[k]='“'+String(ev.text||'').slice(0,60)+'”';
  else{DEVMAP.busy[k]='answered';setTimeout(()=>{if(DEVMAP.busy[k]==='answered'){delete DEVMAP.busy[k];devMapMark(k)}},6000)}
  devMapMark(k);
}
function devMapMark(k){
  if(typeof NET==='undefined'||!NET.v)return;
  document.querySelectorAll('.dm-zm').forEach(h=>zmMount(h,zmPhysical(NET.v),{label:'The device map'}));
}
function devMapWire(box){
  box.querySelectorAll('.dm-zm').forEach(h=>{if(typeof NET!=='undefined'&&NET.v)zmMount(h,zmPhysical(NET.v),{label:'The device map'})});
}
function devMapGo(key){
  NET.open=key;NET.mode='controls';NET.more='';
  netPaint().then(()=>{const m=document.querySelector(`.devhub-box .net-m[data-key="${CSS.escape(key)}"]`);
    if(m)m.scrollIntoView({block:'start',behavior:'smooth'})});
}
