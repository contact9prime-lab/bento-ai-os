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
  if(p.classList.contains('show')){popClose(p);return}
  await renderNotifList();
  popOpen(p,{anchor:$('#tray-bell')});
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
/* ---- a new version is available ----
   Not auto-dismissed like the other cards: an update is a decision, and one that
   vanished after 45 seconds would be one people never quite get round to. The
   three answers are all real — install it, remind me later (say nothing and it
   comes back next cycle), or skip this version for good. */
function showUpdate(ev){
  const old=document.getElementById('updcard');if(old)old.remove();
  const c=document.createElement('div');c.id='updcard';c.className='procard';
  /* Two kinds of news, and this card printed one of them wrong for the common
     case: between releases the version does not move, so it read "Update
     available — 0.2.0 / You are running 0.2.0". `updWord` is the same phrasing
     About and Settings use. */
  const bumped=ev.latest&&ev.latest!==ev.current;
  const head=typeof updWord==='function'?updWord(ev):(ev.latest||'');
  c.innerHTML=`<div class="pc-head">▲ ${esc(bumped?'Update available — '+head:head)}</div>
    <div class="pc-text">You are running ${esc(ev.current||'')}${bumped?'':' — the code on '+esc(ev.tracks||'the update branch')+' has moved on'}.${ev.notes?' ':''}
      ${ev.notes?`<span class="mut">${esc(String(ev.notes).split('\n').slice(1,4).join(' ').slice(0,180))}</span>`:''}
      ${(ev.commits||[]).length?`<div class="upd-log">${(ev.commits||[]).slice(0,6).map(x=>
        `<div><code>${esc(x.hash)}</code> ${esc(x.title)}</div>`).join('')}</div>`:''}</div>
    <div id="upd-prog" class="pc-text mut" style="display:none"></div>
    <div class="pc-actions">
      <button class="pc-go">Update now</button>
      <button class="pc-x">Later</button>
      <button class="pc-skip endbtn">${esc(bumped?'Skip '+ev.latest:'Not this one')}</button></div>`;
  $('#desktop').appendChild(c);popIn(c,{origin:'bottom right'});
  c.querySelector('.pc-x').onclick=()=>popOut(c,()=>c.remove());
  c.querySelector('.pc-skip').onclick=()=>{
    /* Skip the MARK, not the version. Skipping "0.2.0" while running 0.2.0 would
       silence every commit that ever lands under that version — a decline that
       quietly turns into "never update this machine again". */
    const mark=ev.mark||ev.latest||'';
    fetch('/api/update',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({skip:mark})});
    popOut(c,()=>c.remove());
    toast(bumped?('skipping '+ev.latest):'not installing these changes');
  };
  c.querySelector('.pc-go').onclick=()=>runUpdate(c);
}
function runUpdate(card){
  const go=card.querySelector('.pc-go'),prog=card.querySelector('#upd-prog');
  go.disabled=true;go.textContent='Updating…';
  card.querySelector('.pc-x').style.display='none';
  card.querySelector('.pc-skip').style.display='none';
  prog.style.display='';prog.textContent='starting…';
  // The card must outlive the restart it causes: the server stops answering
  // partway through, so the reply may never arrive. The websocket's update_done
  // is the real signal; this only reports a refusal we can still hear.
  fetch('/api/update',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
    .then(r=>r.json()).then(d=>{if(!d.ok&&d.error)updateFailed(d)})
    .catch(()=>{});
}
function updateProgress(ev){
  const p=document.getElementById('upd-prog');
  if(p){p.style.display='';p.textContent=ev.message||''}
}
function updateFailed(d){
  const c=document.getElementById('updcard');
  if(!c){toast('update failed: '+(d.error||''));return}
  c.querySelector('#upd-prog').innerHTML=`<span style="color:var(--err)">${esc(d.error||'update failed')}</span>`;
  const go=c.querySelector('.pc-go');go.disabled=false;go.textContent='Try again';
  c.querySelector('.pc-x').style.display='';
}
function updateDone(ev){
  if(!ev.ok){updateFailed(ev);return}
  const c=document.getElementById('updcard');
  if(c)c.querySelector('#upd-prog').textContent=
    `updated to ${ev.version||''} — restarting, this page will come back on its own…`;
  toast('updated to '+(ev.version||'the new version'));
}
function showSuggestion(ev){
  desktopCard('suggcard',
    `<div class="pc-head">${appIcon('chat',15)} ${esc(agentName())} has an idea</div>
     <div class="pc-text">${esc(ev.text||'')}</div>`,
    ()=>{openApp('chat');if(input){input.value=ev.action_prompt||ev.text;send()}},
    ()=>fetch('/api/suggestions/'+ev.id+'/dismiss',{method:'POST'}));
}

/* A running native window reports its app_id (or X11 class); the desktop entry
   that owns that id is what has the real icon. Matching walks from exact id to
   the loosest sensible match, because toolkits disagree: "org.gnome.Nautilus",
   "nautilus" and "Nautilus" are all the same program. */
function natApp(appId){
  const list=(typeof NATIVEAPPS!=='undefined'?NATIVEAPPS:[]);
  if(!list.length||!appId)return null;
  const a=String(appId).toLowerCase(), tail=a.split('.').pop();
  return list.find(x=>x.id.toLowerCase()===a)
    || list.find(x=>x.id.toLowerCase()===tail)
    || list.find(x=>(x.wmclass||'').toLowerCase()===a)
    || list.find(x=>x.id.toLowerCase().endsWith('.'+tail)||x.id.toLowerCase().startsWith(tail+'-'))
    || list.find(x=>x.name.toLowerCase()===tail)
    || null;
}
function natIcon(w,px){
  px=px||46;
  const a=natApp(w.app);
  if(a&&a.has_icon)return `<img class="na" src="/api/native/icon/${encodeURIComponent(a.id)}" loading="lazy" alt="" style="width:${px}px;height:${px}px;object-fit:contain">`;
  const c=((w.app||w.title||'?').trim().charAt(0)||'?').toUpperCase();
  return `<span class="nafallback" style="width:${px}px;height:${px}px;font-size:${Math.round(px*.43)}px">${esc(/[A-Z0-9]/.test(c)?c:'▭')}</span>`;
}
function natName(w){const a=natApp(w.app);return (a&&a.name)||w.app||w.title||'window'}
let NATIVE_POLL=null,wmDebounce=null,NATWINS=[];
/* The compositor pushes window events, but focus moving BETWEEN two native
   windows is easy to miss; a short poll keeps the menu bar honest.

   It backs off while nothing changes. A fixed 1.2s poll is the one piece of
   background work that survives everything else going to sleep, and on a Pi it
   is a request, a compositor IPC round trip and a taskbar repaint every 1.2s
   forever to learn that nothing happened. Any actual change — or any 'wm' event
   — snaps it straight back to responsive. */
const NAT_MIN=1200, NAT_MAX=8000;
let NAT_EVERY=NAT_MIN, NAT_SIG=null;
function startNativePoll(){
  stopNativePoll();
  const tick=async()=>{
    if(NATIVE_POLL===null)return;               // stopped while we were away
    if(!document.hidden)await updateNativeWindows();
    if(NATIVE_POLL!==null)NATIVE_POLL=setTimeout(tick,NAT_EVERY);
  };
  NATIVE_POLL=setTimeout(tick,NAT_EVERY);
}
function stopNativePoll(){clearTimeout(NATIVE_POLL);NATIVE_POLL=null}
function natPollNow(){NAT_EVERY=NAT_MIN}      // something happened — poll like you mean it
async function updateNativeWindows(){
  const box=$('#tbnative');if(!box)return;
  let d;try{d=await (await fetch('/api/windows')).json()}catch(e){return}
  if(!d.available){
    box.classList.remove('has');box.innerHTML='';box._reason=d.reason||'';NATWINS=[];
    // No compositor on this machine — there is nothing for the fallback poll to
    // find, so stop asking. If a session starts later its 'wm' events drive the
    // taskbar directly, which is the path this poll was only ever standing in for.
    stopNativePoll();
    return;
  }
  NATWINS=d.windows||[];
  const sig=NATWINS.map(x=>[x.id,x.focused,x.minimized,x.title].join('')).join('');
  if(sig===NAT_SIG)NAT_EVERY=Math.min(NAT_MAX,Math.round(NAT_EVERY*1.5));
  else{NAT_SIG=sig;NAT_EVERY=NAT_MIN;paintNativeTiles()}   // repaint only when something actually moved
}
function paintNativeTiles(){
  const box=$('#tbnative');if(!box)return;
  box.classList.toggle('has',NATWINS.length>0);
  box.innerHTML=NATWINS.slice(0,10).map(w=>`<button class="tbnat ${w.focused?'on':''} ${w.minimized?'mini':''}"
      data-id="${esc(w.id)}" data-tip="${esc(natName(w)+' — '+(w.title||''))}">${natIcon(w,46)}</button>`).join('');
  const wins=Object.fromEntries(NATWINS.map(w=>[String(w.id),w]));
  box.querySelectorAll('.tbnat').forEach(b=>{
    const w=wins[b.dataset.id]||{id:b.dataset.id,title:''};
    // exactly like an AgentOS window's taskbar tile: click the focused one to
    // put it away, click a hidden one to bring it back
    b.onclick=()=>natWin(w.minimized?'restore':(w.focused?'minimize':'focus'),w.id);
    b.oncontextmenu=e=>{e.preventDefault();natWinMenu(e,w)};
    b.onpointerenter=()=>natCtlShow(b,w);
    b.onpointerleave=()=>natCtlHide(600);
  });
  buildAppMenus();                 // the menu bar follows native focus too
  if(typeof updateDockSeps==='function')updateDockSeps();
}
/* Window controls for the tile under the pointer.
   They live in a FIXED-position element attached to the desktop, not inside the
   tile: #tbnative scrolls horizontally, and `overflow-x:auto` silently clipped
   an absolutely-positioned popup — the buttons were being drawn and then cut
   off, which is exactly what "minimize doesn't work" looked like. */
let NATCTL_T=0;
function natCtlEl(){
  let el=$('#natctl');
  if(!el){
    el=document.createElement('div');el.id='natctl';
    (($('#desktop'))||document.body).appendChild(el);
    el.onpointerenter=()=>clearTimeout(NATCTL_T);
    el.onpointerleave=()=>natCtlHide(200);
  }
  return el;
}
function natCtlShow(tile,w){
  clearTimeout(NATCTL_T);
  const el=natCtlEl();
  el.innerHTML=`<button data-do="${w.minimized?'restore':'minimize'}" title="${w.minimized?'Restore':'Minimize'} — Super+H">${w.minimized?'▴':'–'}</button>
    <button data-do="maximize" title="Maximize">▢</button>
    <button data-do="fullscreen" title="Full screen — Super+F">⤢</button>
    <button data-do="close" title="Close — Super+Q">✕</button>`;
  el.querySelectorAll('button').forEach(b=>b.onclick=e=>{
    e.stopPropagation();natCtlHide(0);
    const a=b.dataset.do;
    natWin(a,w.id,a==='maximize'?{maximize:true}:a==='fullscreen'?{fullscreen:!w.fullscreen}:undefined);
  });
  const r=tile.getBoundingClientRect();
  el.classList.add('on');
  el.style.left=Math.round(r.left+r.width/2-el.offsetWidth/2)+'px';
  el.style.top=Math.round(r.top-el.offsetHeight-8)+'px';
}
function natCtlHide(delay){
  clearTimeout(NATCTL_T);
  NATCTL_T=setTimeout(()=>{const el=$('#natctl');if(el)el.classList.remove('on')},delay||0);
}

/* One door for every native window command.
   The state is applied to the tile IMMEDIATELY and the request goes out behind
   it. The server answers in about two milliseconds, but waiting for the round
   trip before redrawing — and then waiting another 150ms on top — is what made
   minimizing a window feel slow when nothing slow was happening. The compositor
   event that follows reconciles anything we guessed wrong. */
const NAT_OPTIMISTIC={
  minimize:w=>({minimized:true,focused:false}),
  restore:w=>({minimized:false,focused:true}),
  focus:w=>({minimized:false,focused:true}),
  fullscreen:(w,x)=>({fullscreen:x&&x.fullscreen!==undefined?!!x.fullscreen:!w.fullscreen}),
};
function natWin(action,id,extra){
  natPollNow();                              // you just moved a window — watch closely again
  const w=NATWINS.find(x=>String(x.id)===String(id));
  if(w&&NAT_OPTIMISTIC[action]){
    const patch=NAT_OPTIMISTIC[action](w,extra);
    if(patch.focused)NATWINS.forEach(o=>{o.focused=false});
    Object.assign(w,patch);
    paintNativeTiles();                      // redrawn now, not in 150ms
  }else if(action==='close'&&w){
    NATWINS=NATWINS.filter(x=>x!==w);paintNativeTiles();
  }
  return fetch('/api/windows/'+action,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id,...(extra||{})})})
    .then(r=>r.json()).catch(()=>({ok:false}))
    .then(d=>{if(!d||d.ok===false)updateNativeWindows();return d});
}
function natFocused(){return NATWINS.find(w=>w.focused&&!w.minimized)||null}
async function showDesktop(){
  const d=await fetch('/api/windows/showdesktop',{method:'POST'}).then(r=>r.json()).catch(()=>({ok:false}));
  setTimeout(updateNativeWindows,200);
  toast(d.ok?(d.message||'desktop shown'):'could not hide the windows');
}
/* Everything you can do to a native window, in one menu — the same verbs an
   AgentOS window offers, so there is no second-class kind of window here. */
//: the snap zones offered in the Window menu, in reading order
const NAT_SNAP=[['left','left half'],['right','right half'],
                ['tl','top left'],['tr','top right'],['bl','bottom left'],['br','bottom right'],
                ['center','centred'],['full','the whole desk']];
function natWinItems(w){
  const arrange=cap('windows.arrange').available;
  const items=[
    w.minimized?{label:'Restore',keys:'Super+H',fn:()=>natWin('restore',w.id)}
               :{label:'Minimize',keys:'Super+H',fn:()=>natWin('minimize',w.id)},
    {label:'Maximize',fn:()=>natWin('maximize',w.id,{maximize:true})},
    {label:'Restore size',fn:()=>natWin('maximize',w.id,{maximize:false})},
    {label:w.fullscreen?'Leave full screen':'Full screen',keys:'Super+F',
     fn:()=>natWin('fullscreen',w.id,{fullscreen:!w.fullscreen})},
    {label:'Focus',fn:()=>natWin('focus',w.id)},
  ];
  if(arrange){
    items.push(null,{label:w.floating?'Tile':'Float',fn:()=>natWin('floating',w.id,{floating:!w.floating})});
    // Snapping a native window to half or a quarter of the screen. AgentOS's own
    // windows have done this from the start; without it, native windows were the
    // only ones on the desktop you could not put side by side.
    NAT_SNAP.forEach(([zone,label])=>items.push(
      {label:'Snap '+label,fn:()=>natWin('snap',w.id,{zone})}));
    for(let n=1;n<=4;n++)items.push({label:'Move to desktop '+n,fn:()=>natWin('move',w.id,{workspace:String(n)})});
  }
  items.push(null,{label:'Show the desktop',fn:showDesktop},
             {label:'Close window',danger:true,fn:()=>natWin('close',w.id)});
  return items;
}
function natWinMenu(e,w){showCtxItems(e,natWinItems(w))}
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

