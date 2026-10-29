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
    <section class="dev-events" aria-label="Events"><h3>Events</h3><div class="dev-ev-box"><p class="mut">…</p></div></section>
    <section class="dev-demo" aria-label="Warehouse demo"><h3>Try it in a simulation</h3><div class="dev-demo-box"><p class="mut">…</p></div></section></div>
    <div class="dev-logical" hidden><p class="mut">…</p></div>`;
  pb.querySelectorAll('[data-dv]').forEach(b=>b.onclick=()=>devViewSet(b.dataset.dv));
  let v='physical';try{v=localStorage.getItem('devices.view')||'physical'}catch(e){}
  devViewSet(v);
  await netPaint();
  devEventsLoad();
  if(w)winTick(w,devDemoLoad,2500,{key:'demo'});else devDemoLoad();
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
var DEVEV_ICON={moved:'⇄',offline:'○',online:'●',updated:'⬆',refreshed:'⟳',failed:'✗',installed:'✓',secured:'🔒',
  hardware:'▦',found:'＋',gone:'－',power:'⚡',board:'▦'};
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

/* The warehouse demo (demos/warehouse.py): a hub, three zone Pis and six ESP32s in a sandbox of
   their own, on this machine's brain or the scripted one. Asked for as "something people can try
   with Bento, to play around, for demos". Its pages are on this machine's loopback, so a browser
   elsewhere gets a sentence instead of buttons that open nothing. */
var DEVDEMO={st:null,busy:false,scripted:false};
async function devDemoLoad(){
  if(!document.querySelector('.dev-demo-box'))return;
  try{DEVDEMO.st=await apiJSON('/api/demo/warehouse')}catch(e){DEVDEMO.st={phase:'off',error:String(e.message||e)}}
  // a repaint would take the caret out of a box somebody is typing in
  const a=document.activeElement;if(a&&a.tagName==='INPUT'&&a.closest('.dev-demo-box'))return;
  devDemoPaint();
}
function devDemoPaint(){
  const typed=document.getElementById('dev-demo-pw'),keepPw=typed&&typed.value,nm=document.getElementById('dev-demo-name');
  if(nm)DEVDEMO.name=nm.value;
  const st=DEVDEMO.st||{},p=st.phase,ac=st.account||{};
  const intro=`<p class="dev-demo-say">A hub, three zone Pis and six ESP32s running a warehouse, all simulated. Ask the hub about it, and cause trouble on the floor. ${pInfo('Everything runs on this computer in a sandbox of its own, so your own Bento, devices and memory are untouched. The hub thinks with a copy of your brain, or with a scripted one that is free and works offline.')}</p>`;
  let body='';
  if(st.unavailable)body=`<p class="mut">${esc(st.unavailable)}</p>`;
  else if(!st.here)body=`<p class="mut">Open Devices on the machine itself to try it. The demo answers only there.</p>`;
  else if(ac.need==='create')body=ac.can_create?`<p>The demo runs as a user of its own, so your chats, devices and memory stay out of it. Create one for it. ${pInfo('A new Bento account, used only for the demo. Sign in as it to start the demo, in a private window if you want to stay signed in here.')}</p>
    <div class="dev-demo-acct"><input id="dev-demo-name" value="${esc(DEVDEMO.name||'demo')}" aria-label="User name" autocomplete="off">
    ${secretField('dev-demo-pw','a password for it')}</div>
    <div class="dev-acts"><button class="wiz-next" data-demo="account"${DEVDEMO.busy?' disabled':''}>Create the demo user</button></div>`
    :`<p class="mut">The demo runs as a user of its own. Ask an admin to create one for it in Devices.</p>`;
  else if(ac.need==='signin')body=`<p>The demo runs as the user <b>${esc(ac.name)}</b>, so it stays out of your account. Sign in as ${esc(ac.name)} to start it. ${pInfo('Use a private window to keep this account signed in here.')}</p>
    <div class="dev-acts"><button class="wiz-next" data-demo="signin">Sign in as ${esc(ac.name)}</button>
    ${p==='ready'||p==='starting'?'<button class="endbtn" data-demo="stop">Stop</button>':''}</div>`;
  else if(p==='ready')body=`<p class="mut">Running on ${esc(st.brain||'a brain')}. Try “${esc((st.try||[])[0]||'')}”</p>
    <div class="dev-acts"><button class="wiz-next" data-demo="floor">Open the floor</button>
    <button class="endbtn" data-demo="hub">Open the hub</button>
    <button class="endbtn" data-demo="stop"${DEVDEMO.busy?' disabled':''}>Stop</button></div>`;
  else if(p==='starting')body=`<p>Setting up, step ${(st.done||0)+1} of ${st.of||6}: ${esc(st.step||'')}…</p>
    <div class="dev-demo-bar"><i style="width:${Math.round(100*(st.done||0)/(st.of||6))}%"></i></div>
    <div class="dev-acts"><button class="endbtn" data-demo="stop">Stop</button></div>`;
  else body=`${p==='failed'&&st.error?`<p class="bad">${esc(st.error)}</p>`:''}
    <label class="dev-demo-opt"><input type="checkbox" id="dev-demo-scripted"${DEVDEMO.scripted?' checked':''}> Use the scripted brain ${pInfo('Free and offline. It understands a warehouse floor: a walk through, a room by name, and switching the fans, lights, charger or a compressor.')}</label>
    <div class="dev-acts"><button class="wiz-next" data-demo="start"${DEVDEMO.busy?' disabled':''}>${st.set_up?'Start the demo':'Set up the demo'}</button>
    ${st.set_up?`<button class="endbtn" data-demo="fresh"${DEVDEMO.busy?' disabled':''}>Start over</button>`:''}</div>
    ${st.set_up?'':'<p class="mut">The first start takes about half a minute.</p>'}`;
  document.querySelectorAll('.dev-demo-box').forEach(box=>{box.innerHTML=intro+body;
    const cb=box.querySelector('#dev-demo-scripted');if(cb)cb.onchange=()=>DEVDEMO.scripted=cb.checked;
    box.querySelectorAll('[data-demo]').forEach(b=>b.onclick=()=>devDemoAct(b.dataset.demo))});
  const pw=document.getElementById('dev-demo-pw');if(pw&&keepPw)pw.value=keepPw;
}
async function devDemoAct(act){
  const st=DEVDEMO.st||{};
  if(act==='floor'||act==='hub'){openHost({url:act==='floor'?st.floor:st.hub});return}
  if(act==='signin'){if(!await osConfirm('Sign out and sign in as '+((st.account||{}).name||'the demo user')+'?','You come back to this account by signing in again.',{confirmText:'Sign out'}))return;
    try{await fetch('/api/users/logout',{method:'POST'})}catch(e){}location.href='/login';return}
  if(act==='account'){const n=document.getElementById('dev-demo-name'),pw=document.getElementById('dev-demo-pw');
    DEVDEMO.name=n?n.value.trim():'demo';DEVDEMO.busy=true;devDemoPaint();
    try{const r=await fetch('/api/demo/warehouse',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({action:'account',name:DEVDEMO.name,password:pw?pw.value:''})});
      const d=await r.json();if(!r.ok)toast(d.error||'That user couldn’t be made',{kind:'err'});
      else toast('✓ Made the user '+DEVDEMO.name+'. Sign in as it to start the demo.')}
    catch(e){toast(String(e.message||e),{kind:'err'})}
    DEVDEMO.busy=false;return devDemoLoad()}
  if(act==='fresh'&&!await osConfirm('Start the demo over?','Its three zones are set up again from nothing. Your own Bento is not touched.',{confirmText:'Start over'}))return;
  DEVDEMO.busy=true;devDemoPaint();
  try{const r=await fetch('/api/demo/warehouse',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(act==='stop'?{action:'stop'}:{action:'start',scripted:DEVDEMO.scripted,fresh:act==='fresh'})});
    const d=await r.json();
    if(!r.ok)toast(d.error||'The demo didn’t start',{kind:'err'});else if(d.note)toast(d.note)}
  catch(e){toast(String(e.message||e),{kind:'err'})}
  DEVDEMO.busy=false;devDemoLoad();
}
