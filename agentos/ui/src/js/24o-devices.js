/* ---------------- Devices: the machines on your network, in a window of their own ----------------
   Asked for as "have these devices in the device hub in Bento". The same list as Settings →
   Network (netPaint draws into every .devhub-box), so the two never disagree: each machine,
   what it is to Bento, its switches as last read, Controls, Install and Remove. */
async function renderDevices(body,w){
  const pb=panelShell(body,{title:'Devices',sub:'The machines on your network'});
  pb.innerHTML=`<div class="devhub-box" id="devhub-${esc(w&&w.id||'0')}"><p class="mut">…</p></div>
    <section class="dev-events" aria-label="Events"><h3>Events</h3><div class="dev-ev-box"><p class="mut">…</p></div></section>`;
  await netPaint();
  devEventsLoad();
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
function devMapHTML(v){
  const rows=(v.rows||[]).filter(r=>!r.ignored),ties=(v.ties||[]).filter(t=>!t.stale);
  const old=(v.ties||[]).length-ties.length;
  const tied=new Set();
  const nodes=[],lines=[];
  // one node per live tie; the machine row it is on (by link label) is folded into it
  const zeros=ties.filter(t=>t.kind==='zero'),teams=ties.filter(t=>t.kind!=='zero');
  const rowOf=t=>rows.find(r=>(r.links||[]).some(l=>l.label===t.label));
  ties.forEach(t=>{const r=rowOf(t);if(r)tied.add(r.key)});
  const machines=rows.filter(r=>!tied.has(r.key)&&r.bento!=='none'&&r.bento!=='removed').slice(0,8);
  const rest=rows.filter(r=>!tied.has(r.key)&&!machines.includes(r));
  const pos=(i,n,rx,ry,off)=>{const a=-Math.PI/2+(off||0)+2*Math.PI*i/Math.max(n,1);
    return [50+rx*Math.cos(a),50+ry*Math.sin(a)]};
  const line=(x,y,cls)=>{const at=t=>[(50+(x-50)*t).toFixed(2),(50+(y-50)*t).toFixed(2)];
    const [ax,ay]=at(.17),[bx,by]=at(.8);
    lines.push(`<line x1="${ax}" y1="${ay}" x2="${bx}" y2="${by}" class="${cls}"/>`)};
  const node=(x,y,o)=>{
    nodes.push(`<button class="dm-n ${o.kind} ${o.st}${DEVMAP.busy[o.label]?' busy':''}${y<50?' above':''}" style="left:${x.toFixed(2)}%;top:${y.toFixed(2)}%"
        data-dm="${esc(o.go)}" data-dmk="${esc(o.key)}" data-dmlabel="${esc(o.label||'')}" aria-label="${esc(o.aria)}">
      <span class="dm-ring">${o.face}<i class="dm-st" aria-hidden="true"></i></span>
      <span class="dm-lab"><span class="dm-tag">${esc(o.tag)}</span><b>${esc(o.name)}</b><span class="dm-sub">${esc(o.sub)}</span></span>
      <span class="dm-say" aria-live="polite">${esc(DEVMAP.busy[o.label]||'')}</span></button>`)};
  const tieNode=(t,x,y)=>{const st=tieState(t),r=rowOf(t);
    line(x,y,`${t.kind} ${st.cls}`);
    node(x,y,{kind:t.kind,st:st.cls,label:t.label,go:'tie',key:tieKey(t),face:tieFace(t,'dm-face'),
      tag:t.kind==='zero'?'ZERO':t.kind==='account'?'ACCOUNT':'TEAM',name:(t.agent||{}).name||t.peer,
      sub:t.peer+(t.answering===false?' · not answering':''),aria:`${tieKindWord(t)} ${t.peer}, ${st.word}`})};
  zeros.forEach((t,i)=>{const [x,y]=pos(i,zeros.length,29,33,-.55);tieNode(t,x,y)});
  teams.forEach((t,i)=>{const [x,y]=pos(i,teams.length,40,38,.6);tieNode(t,x,y)});
  machines.forEach((r,i)=>{const [x,y]=pos(i,machines.length,34,35,1.4),ag=r.agent||{},cs=((r.controls||{}).state)||{};
    const st=cs.running===true?'up':cs.running===false?'down':'';
    line(x,y,'machine '+st);
    node(x,y,{kind:'machine',st,label:'',go:'machine',key:r.key,
      face:ag.look&&Object.keys(ag.look).length?avatarRecipeImg(ag.look,'dm-face',ag.name||'')
        :`<span class="dm-face devmap-initial">${esc((ag.name||r.display||'?').slice(0,1).toUpperCase())}</span>`,
      tag:r.bento==='waiting'?'WAITING':'BENTO',name:ag.name||'Bento',sub:r.display,aria:`${ag.name?ag.name+' on ':''}${r.display}`})});
  rest.forEach((r,i)=>{const [x,y]=pos(i,rest.length,47,46,Math.PI/rest.length);
    nodes.push(`<span class="dm-dot" style="left:${x.toFixed(2)}%;top:${y.toFixed(2)}%" title="${esc(r.display+(r.ip&&r.ip!==r.display?' · '+r.ip:''))}"></span>`)});
  const me=v.me||{},meFace=typeof avatarImg==='function'?avatarImg('@agent','dm-face'):'';
  const n=k=>ties.filter(t=>t.kind===k).length;
  return `<div class="dm" role="img" aria-label="Map of the machines and teams tied to this computer">
    <svg class="dm-bg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      <ellipse cx="50" cy="50" rx="29" ry="33"/><ellipse cx="50" cy="50" rx="40" ry="38"/><ellipse cx="50" cy="50" rx="47" ry="46"/>
      ${lines.join('')}</svg>
    ${nodes.join('')}
    <div class="dm-n dm-me" style="left:50%;top:50%"><span class="dm-ring">${meFace}</span>
      <span class="dm-lab"><span class="dm-tag">HUB</span><b>${esc(me.agent||'Your agent')}</b><span class="dm-sub">${esc(me.name||'this computer')}</span></span></div>
    <div class="dm-legend"><span class="zero"><i></i>Zero ${n('zero')}</span><span class="team"><i></i>Team ${n('team')+n('account')}</span>
      ${machines.length?`<span class="machine"><i></i>Bento ${machines.length}</span>`:''}<span class="off"><i></i>not answering</span>
      ${rest.length?`<span class="dot"><i></i>${rest.length} other machine${rest.length===1?'':'s'}</span>`:''}
      ${old?`<span class="old"><i></i>${old} old link${old===1?'':'s'} to remove below</span>`:''}</div>
    ${!ties.length&&!machines.length?`<p class="dm-empty">Nothing is tied to this computer yet. Install Bento on a machine below, or link a team.</p>`:''}
  </div>`;
}
/* A node working right now: a Zero's chat run here (fabric.zero_chat broadcasts zero_work). */
function devMapPulse(ev){
  const k=ev.zero;if(!k)return;
  if(ev.phase==='start')DEVMAP.busy[k]='“'+String(ev.text||'').slice(0,60)+'”';
  else{DEVMAP.busy[k]='answered';setTimeout(()=>{if(DEVMAP.busy[k]==='answered'){delete DEVMAP.busy[k];devMapMark(k)}},6000)}
  devMapMark(k);
}
function devMapMark(k){
  document.querySelectorAll(`.dm-n[data-dmlabel="${CSS.escape(k)}"]`).forEach(n=>{
    n.classList.toggle('busy',!!DEVMAP.busy[k]);const s=n.querySelector('.dm-say');if(s)s.textContent=DEVMAP.busy[k]||''});
}
function devMapWire(box){
  box.querySelectorAll('.dm-n[data-dm]').forEach(n=>n.onclick=()=>{
    if(n.dataset.dm==='tie'){TIES.open=n.dataset.dmk;TIES.view=null;
      tieLists().then(()=>netPaint()).then(()=>{const t=document.querySelector(`.devhub-box .tie[data-tiekey="${CSS.escape(n.dataset.dmk)}"]`);
        if(t)t.scrollIntoView({block:'start',behavior:'smooth'})})}
    else devMapGo(n.dataset.dmk)});
}
function devMapGo(key){
  NET.open=key;NET.mode='controls';NET.more='';
  netPaint().then(()=>{const m=document.querySelector(`.devhub-box .net-m[data-key="${CSS.escape(key)}"]`);
    if(m)m.scrollIntoView({block:'start',behavior:'smooth'})});
}
