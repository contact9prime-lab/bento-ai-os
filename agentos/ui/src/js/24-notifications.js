/* ================= notification center ================= */
const NOTIF={unread:0,dnd:false};
function svgBell(px){px=px||14;return `<svg width="${px}" height="${px}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="display:block"><path d="M6 9.5a6 6 0 0 1 12 0c0 5 1.7 6 1.7 6H4.3S6 14.5 6 9.5"/><path d="M10.3 19.5a2 2 0 0 0 3.4 0"/></svg>`}
async function updateBell(){
  const bell=$('#tray-bell');if(!bell)return;
  try{
    const d=await (await fetch('/api/notifications')).json();
    NOTIF.unread=d.unread||0;NOTIF.dnd=!!d.dnd;
    bell.classList.toggle('dnd',NOTIF.dnd);
    bell.innerHTML=svgBell(14)+(NOTIF.unread?`<span class="badge">${NOTIF.unread>99?'99+':NOTIF.unread}</span>`:'');
    bell.style.display=(d.available===false&&PLATFORM.mode!=='de')?'none':'flex';
  }catch(e){}
}
async function renderNotifList(){
  const d=await (await fetch('/api/notifications')).json();
  const list=$('#np-list');
  // the agent's triage digest rides on top — "For you", not a raw log
  const foryou=d.digest&&d.digest.text?`<div class="np-foryou">
      <div class="np-fy-head">${appIcon('chat',15)} For you
        <span style="flex:1"></span>
        <button class="np-x" style="position:static" onclick="dismissDigest()">✕</button></div>
      <div class="np-fy-text">${esc(d.digest.text)}</div>
    </div>`:'';
  // group by app, newest group first — a feed of apps, not a flat log
  const groups=new Map();
  (d.items||[]).forEach(n=>{const k=n.app||'system';if(!groups.has(k))groups.set(k,[]);groups.get(k).push(n)});
  list.innerHTML=foryou+([...groups.entries()].map(([app,items])=>`
    <div class="np-group">${groups.size>1?`<div class="np-gapp">${esc(app)}</div>`:''}
    ${items.map(n=>`<div class="np-item ${n.urgency>=2?'crit':''}${n.importance>=2?' imp':''}">
      <div class="np-app">${esc(app)} · ${new Date(n.time*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}${n.importance>=2?' · <b>important</b>':''}</div>
      <div class="np-sum">${esc(n.summary)}</div>
      ${n.body?`<div class="np-body">${esc(n.body)}</div>`:''}
      <button class="np-x" onclick="dismissNotif(${n.id})">✕</button>
    </div>`).join('')}</div>`).join('')
    ||'<p class="mut" style="padding:10px">nothing here — you\'re all caught up</p>');
  const dnd=$('#np-dnd');
  dnd.innerHTML=svgBell(13)+(d.dnd?'<span class="np-slash"></span>':'');
  dnd.title=d.dnd?'Do not disturb is on':'Do not disturb';
  dnd.classList.toggle('on',!d.dnd);
  dnd.onclick=()=>toggleDnd(!d.dnd).then(renderNotifList);
  $('#np-clear').onclick=async()=>{await fetch('/api/notifications',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'clear'})});renderNotifList()};
  return d;
}
async function openNotifPanel(){
  const p=$('#notifpanel');
  if(p.classList.contains('show')){p.classList.remove('show');return}
  $('#powermenu').classList.remove('show');
  await renderNotifList();
  p.classList.add('show');
  popIn(p,{origin:'top right'});
  await fetch('/api/notifications',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'read'})});
  updateBell();
}
async function dismissNotif(id){
  await fetch('/api/notifications',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'dismiss',id})});
  renderNotifList();
}
async function dismissDigest(){
  await fetch('/api/notifications',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'dismiss_digest'})});
  renderNotifList();
}

/* ---- proactive surfaces: briefing + suggestion cards on the desktop ---- */
function desktopCard(id,html,onAccept,onDismiss){
  const old=document.getElementById(id);if(old)old.remove();
  const c=document.createElement('div');c.id=id;c.className='procard';
  c.innerHTML=html+`<div class="pc-actions">
      ${onAccept?'<button class="pc-go">Open</button>':''}
      <button class="pc-x">Dismiss</button></div>`;
  $('#desktop').appendChild(c);
  popIn(c,{origin:'bottom right'});
  const go=c.querySelector('.pc-go');if(go)go.onclick=()=>{c.remove();onAccept()};
  c.querySelector('.pc-x').onclick=()=>{popOut(c,()=>c.remove());if(onDismiss)onDismiss()};
  setTimeout(()=>{if(c.isConnected)popOut(c,()=>c.remove())},45000);
}
function showBriefing(ev){
  desktopCard('briefcard',
    `<div class="pc-head">${appIcon('chat',15)} While you were away</div>
     <div class="pc-text">${esc(ev.text||'')}</div>`,
    ev.conversation_id?()=>{openApp('chat');openConv(ev.conversation_id)}:null);
}
function showSuggestion(ev){
  desktopCard('suggcard',
    `<div class="pc-head">${appIcon('chat',15)} ${esc(agentName())} has an idea</div>
     <div class="pc-text">${esc(ev.text||'')}</div>`,
    ()=>{openApp('chat');if(input){input.value=ev.action_prompt||ev.text;send()}},
    ()=>fetch('/api/suggestions/'+ev.id+'/dismiss',{method:'POST'}));
}

function natIcon(app){const c=(app||'?').trim().charAt(0).toUpperCase();return /[A-Z0-9]/.test(c)?c:'▭'}
let NATIVE_POLL=null,wmDebounce=null;
async function updateNativeWindows(){
  const box=$('#tbnative');if(!box)return;
  let d;try{d=await (await fetch('/api/windows')).json()}catch(e){return}
  if(!d.available){box.classList.remove('has');box.innerHTML='';box._reason=d.reason||'';return}
  box.classList.toggle('has',d.windows.length>0);
  box.innerHTML=d.windows.slice(0,8).map(w=>`<button class="tbnat ${w.focused?'on':''}" data-id="${esc(w.id)}" data-tip="${esc(w.title)}">
    ${emojiIcon(natIcon(w.app),46)}</button>`).join('');
  const wins=Object.fromEntries(d.windows.map(w=>[String(w.id),w]));
  box.querySelectorAll('.tbnat').forEach(b=>{
    b.onclick=()=>fetch('/api/windows/focus',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:b.dataset.id})});
    b.oncontextmenu=e=>{e.preventDefault();natWinMenu(e,wins[b.dataset.id]||{id:b.dataset.id,title:''})};
  });
  if(typeof updateDockSeps==='function')updateDockSeps();
}
function natWinMenu(e,w){
  const m=$('#ctxmenu');
  const arrange=cap('windows.arrange').available;
  m.innerHTML=`<button data-a="focus">Focus</button>
    ${arrange?`<button data-a="float">${w.floating?'Tile':'Float'}</button>
    ${[1,2,3,4].map(n=>`<button data-a="ws${n}">Move to desktop ${n}</button>`).join('')}<hr>`:'<hr>'}
    <button data-a="close" style="color:var(--err,#f87171)">Close window</button>`;
  const post=(url,body)=>fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(()=>setTimeout(updateNativeWindows,200));
  m.querySelector('[data-a=focus]').onclick=()=>{m.classList.remove('show');post('/api/windows/focus',{id:w.id})};
  if(arrange){
    m.querySelector('[data-a=float]').onclick=()=>{m.classList.remove('show');post('/api/windows/floating',{id:w.id,floating:!w.floating})};
    [1,2,3,4].forEach(n=>{m.querySelector(`[data-a=ws${n}]`).onclick=()=>{m.classList.remove('show');post('/api/windows/move',{id:w.id,workspace:String(n)})}});
  }
  m.querySelector('[data-a=close]').onclick=()=>{m.classList.remove('show');post('/api/windows/close',{id:w.id})};
  ctxShow(e,m);
}
function svgMic(px){
  px=px||15;
  return `<svg width="${px}" height="${px}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="display:block"><rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0"/><path d="M12 18v2.5"/></svg>`;
}
function svgSpeaker(muted){
  return `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="display:block">
    <path d="M11 5.5 6.8 9H4v6h2.8L11 18.5Z"/>${muted
      ?'<path d="M15.5 9.5l5 5M20.5 9.5l-5 5"/>'
      :'<path d="M14.5 9.5a3.6 3.6 0 0 1 0 5"/><path d="M17 7.4a7 7 0 0 1 0 9.2"/>'}</svg>`;
}
function svgBattery(pct){
  const w=Math.max(1,Math.round(15*Math.min(pct,100)/100));
  const fill=pct<20?'var(--err)':'currentColor';
  return `<svg width="23" height="12" viewBox="0 0 27 13" style="display:block"><rect x="1" y="1.5" width="21" height="10" rx="3" fill="none" stroke="currentColor" stroke-width="1.4" opacity=".55"/><rect x="23.6" y="4.5" width="2.4" height="4" rx="1.1" fill="currentColor" opacity=".55"/><rect x="3" y="3.5" width="${w}" height="6" rx="1.6" fill="${fill}"/></svg>`;
}
async function updateTray(){
  try{
    const d=await (await fetch('/api/control')).json();
    const a=d.audio||{},b=d.battery||{};
    const el=$('#tray-ctl');if(!el)return;
    el.innerHTML=`<span title="volume ${a.volume??'?'}%">${svgSpeaker(a.muted)}</span>`+
      (b.percent!=null?`<span title="battery ${b.percent}% · ${esc(b.state||'')}" style="display:flex;align-items:center;gap:5px">${svgBattery(b.percent)}<span style="font-size:11.5px">${b.percent}%</span></span>`:'');
  }catch(e){}
}

