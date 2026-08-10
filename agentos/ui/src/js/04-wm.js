/* ================= window manager ================= */
/* WM.wins is keyed by instance key. The FIRST window of an app uses the bare app id as its
   key (so every existing WM.wins.get('<app>') caller keeps working); additional instances of
   multi-instance apps (APPS[id].multi) get '<app>#n'. w.id stays the app id everywhere. */
const WM={wins:new Map(), z:100, cascade:0, seq:0};
function winsOf(appId){const r=[];WM.wins.forEach(w=>{if(w.id===appId)r.push(w)});return r}

function openApp(id,opts){
  opts=opts||{};
  const app=APPS[id];if(!app)return null;
  if(!(app.multi&&opts.fresh)){
    const w=WM.wins.get(id)||winsOf(id)[0];
    if(w){ if(w.desk!==curDesk){w.desk=curDesk;applyDeskVisibility()} if(w.min)restoreWin(w); focusWin(w); return w; }
  }
  dockBounce(id);
  const w=createWin(app);
  sessionSave();   // the arrangement changed
  return w;
}
function openAppNew(id){return openApp(id,{fresh:true})}
/* ---- where a window opens ------------------------------------------------
   This used to be "centre it, plus 26px per window, wrapping every six". Five
   windows therefore landed on top of each other, the same size, offset by less
   than a title bar — the stack in the screenshot that started this. Two fixes,
   in order of how much they matter:

   1. A window you have placed opens where you left it. Geometry is remembered
      per app in localStorage, so the desktop you arranged is the desktop you
      come back to. This is what people actually want and it costs one key.
   2. A window opening for the FIRST time cascades from the top-left of the
      usable area with a step big enough to read a title bar underneath, and
      wraps into a second column rather than marching off the bottom right.

   Sizes are clamped to the usable area (below the menu bar, above the dock),
   not to the whole viewport, so a tall window no longer opens with its footer
   under the dock. */
var WIN_STEP=38, WIN_MARGIN=14;
function winGeomKey(id){return 'wingeom:'+id}
function winSaveGeom(w){
  if(!w||w.max||w.min||w.snap)return;          // remember the shape you chose, not a state
  try{localStorage.setItem(winGeomKey(w.id),JSON.stringify({
    l:parseInt(w.el.style.left,10)||0, t:parseInt(w.el.style.top,10)||0,
    w:parseInt(w.el.style.width,10)||0, h:parseInt(w.el.style.height,10)||0}))}catch(e){}
}
function winLoadGeom(id){
  try{const g=JSON.parse(localStorage.getItem(winGeomKey(id))||'null');
    return (g&&g.w>200&&g.h>140)?g:null}catch(e){return null}
}
/* The rectangle a window may actually use: inside the menu bar and above the
   dock/omnibar band, which is what --mbh and --tbh already describe. */
function winArea(){
  const desk=$('#desktop'), cs=getComputedStyle(document.documentElement);
  const px=v=>parseInt(cs.getPropertyValue(v),10)||0;
  const top=px('--mbh'), bottom=px('--tbh');
  return {x:WIN_MARGIN, y:WIN_MARGIN,
          w:Math.max(320,desk.clientWidth-WIN_MARGIN*2),
          h:Math.max(240,desk.clientHeight-top-bottom-WIN_MARGIN),
          top, bottom};
}
function winPlace(el,app){
  const a=winArea();
  const saved=winLoadGeom(app.id);
  let width=Math.min(saved?saved.w:app.w, a.w);
  let height=Math.min(saved?saved.h:app.h, a.h);
  el.style.width=width+'px'; el.style.height=height+'px';
  if(saved){
    // clamp into today's screen: the geometry may come from a bigger monitor
    el.style.left=Math.max(a.x,Math.min(saved.l,a.x+a.w-width))+'px';
    el.style.top=Math.max(a.y,Math.min(saved.t,a.y+a.h-height))+'px';
    return;
  }
  /* How many steps fit before wrapping is a property of the SCREEN, not of the
     window being placed — deriving it from `height` gave each app a different
     wrap point, so the sixth window jumped to a column the fifth had not
     started. Six steps or whatever the screen holds, whichever is smaller. */
  const perCol=Math.max(1,Math.min(6,Math.floor(a.h/(WIN_STEP*3))));
  const n=WM.cascade++;
  const col=Math.floor(n/perCol), row=n%perCol;
  const l=a.x+row*WIN_STEP+col*(WIN_STEP*4);
  const t=a.y+row*WIN_STEP;
  el.style.left=Math.max(a.x,Math.min(l,a.x+a.w-width))+'px';
  el.style.top=Math.max(a.y,Math.min(t,a.y+a.h-height))+'px';
}
function createWin(app){
  const desk=$('#desktop');
  const el=document.createElement('div'); el.className='win';
  winPlace(el,app);
  el.innerHTML=`<div class="ttl">
    <div class="tbtns"><button class="cls" title="close">✕</button><button class="mn" title="minimize">–</button><button class="mx" title="maximize">＋</button></div>
    <div class="tmid"><span class="ticon">${appIcon(app.id,17)}</span><span class="tname">${esc(app.title)}</span></div>
    <span class="tright"><button class="cp-btn" title="${esc('Ask '+((typeof agentName==='function'&&agentName())||'the agent')+' about this app')}">✦</button></span></div>
    <div class="wmain"><div class="wbody"></div><div class="copanel"></div></div>
    ${['n','s','e','w','ne','nw','se','sw'].map(d=>`<div class="rz rz-${d}" data-d="${d}"></div>`).join('')}`;
  desk.appendChild(el);

  const tb=document.createElement('button'); tb.className='tbwin';
  tb.dataset.app=app.id;
  if(DOCK.includes(app.id))tb.classList.add('indock');   // pinned apps surface in the dock itself
  tb.dataset.tip=app.title;
  tb.innerHTML=appIcon(app.id,46);
  $('#tbwins').appendChild(tb);

  const key=WM.wins.has(app.id)?app.id+'#'+(++WM.seq):app.id;
  const w={id:app.id,key,app,el,tb,min:false,max:false,prev:null,snap:null,desk:curDesk};
  WM.wins.set(key,w);
  // on a phone a window IS the screen — open it as a sheet, remembering that the
  // full-screen state was the device's idea so a wider viewport can undo it
  if(typeof isMobile==='function'&&isMobile()){
    w.prev={l:el.style.left,t:el.style.top,w:el.style.width,h:el.style.height};
    w.wasMax=false;w.max=true;el.classList.add('maxed');
  }

  tb.onclick=()=>{ if(w.min){restoreWin(w);focusWin(w)} else if(el.classList.contains('active')) minimizeWin(w); else focusWin(w); };
  el.addEventListener('pointerdown',()=>focusWin(w));
  el.querySelector('.mn').onclick=e=>{e.stopPropagation();minimizeWin(w)};
  el.querySelector('.mx').onclick=e=>{e.stopPropagation();toggleMax(w)};
  el.querySelector('.cls').onclick=e=>{e.stopPropagation();closeWin(w)};
  const ttl=el.querySelector('.ttl');
  ttl.ondblclick=e=>{if(!e.target.closest('button'))toggleMax(w)};
  ttl.oncontextmenu=e=>{e.preventDefault();winMenu(e,w)};
  dragify(w,ttl);
  resizify(w);
  // the agent inside this app: ✦ toggles the copilot panel (remembered per app)
  el.querySelector('.cp-btn').onclick=e=>{e.stopPropagation();toggleCopilot(w)};
  // the panel never opens by itself — a window is a window until you ask for the
  // agent (✦ on the title bar, or the copilot shortcut, which also works in
  // full screen). Until then it sits quietly out of the way.

  app.render(el.querySelector('.wbody'),w);
  setMenubarApp(app.title);
  focusWin(w);
  zoomWin(el,app.id,1);
  if(typeof glassProbe==='function')glassProbe();   // more windows on screen — can this machine still draw them?
  return w;
}
function focusWin(w){
  if(w.min)return;
  w.el.style.zIndex=++WM.z;
  if(WM.z>9e5){ // renormalize so z never grows unbounded across a long session
    const order=[...WM.wins.values()].sort((a,b)=>(+a.el.style.zIndex||0)-(+b.el.style.zIndex||0));
    WM.z=100+order.length; order.forEach((o,i)=>o.el.style.zIndex=100+i);
    w.el.style.zIndex=WM.z=100+order.length+1;
  }
  WM.wins.forEach(o=>{o.el.classList.toggle('active',o===w);o.tb.classList.toggle('on',o===w&&!o.min)});
  setMenubarApp(w.app.title);
  updateDockHide();
  // raising a window can bury (or uncover) another one — re-check who is visible
  applyWindowActivity();
  if(typeof deckAuto==='function')deckAuto();
  if(typeof buildPager==='function')buildPager();
  if(typeof buildDock==='function')buildDock();
}
/* the dock auto-hides while a maximized window is focused; a bottom-edge peek brings it back */
function updateDockHide(){
  let maxed=false;WM.wins.forEach(o=>{if(o.el.classList.contains('active')&&o.max&&!o.min)maxed=true});
  // on a phone every window is maximized, so hiding the dock for one would hide
  // it forever — and there is no pointer to peek with
  if(typeof isMobile==='function'&&isMobile())maxed=false;
  document.body.classList.toggle('dock-hide',maxed);
  if(!maxed)document.body.classList.remove('dock-peek');
}
document.addEventListener('pointermove',e=>{
  if(!document.body.classList.contains('dock-hide'))return;
  if(e.clientY>innerHeight-6)document.body.classList.add('dock-peek');
  else if(document.body.classList.contains('dock-peek')&&e.clientY<innerHeight-110)document.body.classList.remove('dock-peek');
});
function setMenubarApp(title){const el=$('#mbapp');if(el)el.textContent=title||'';
  if(typeof buildAppMenus==='function')buildAppMenus()}
function minimizeWin(w){
  sessionSave();
  w.min=true;w.tb.classList.add('mini');w.tb.classList.remove('on');
  zoomWin(w.el,w.id,-1).then(()=>{if(w.min)w.el.style.display='none'});
  // hand focus to the topmost remaining window
  let top=null;WM.wins.forEach(o=>{if(!o.min&&o!==w&&(!top||+o.el.style.zIndex>+top.el.style.zIndex))top=o});
  if(top)focusWin(top);else{setMenubarApp('');updateDockHide();if(typeof deckAuto==='function')deckAuto();if(typeof buildDock==='function')buildDock()}
  applyWindowActivity();       // nothing to see — stop this window's periodic work
}
function restoreWin(w){
  sessionSave();
  w.min=false;w.el.style.display='';w.tb.classList.remove('mini');
  zoomWin(w.el,w.id,1);
  applyWindowActivity();       // and back to work, refreshing on the way in
  if(typeof deckAuto==='function')deckAuto();
  if(typeof buildDock==='function')buildDock();
}
function toggleMax(w){
  sessionSave();
  flipWin(w.el,()=>{
    if(w.max){w.el.classList.remove('maxed');w.max=false;
      if(w.prev){w.el.style.left=w.prev.l;w.el.style.top=w.prev.t;w.el.style.width=w.prev.w;w.el.style.height=w.prev.h}}
    else{w.prev={l:w.el.style.left,t:w.el.style.top,w:w.el.style.width,h:w.el.style.height};
      w.el.classList.add('maxed');w.max=true}
  });
  focusWin(w);
  updateDockHide();
}
/* every window control in one place — the title bar's right-click menu */
function winMenu(e,w){
  const items=[
    {label:w.fs?'Leave full screen':'Full screen',fn:()=>toggleFullWin(w)},
    {label:w.max?'Restore size':'Maximize',fn:()=>toggleMax(w)},
    {label:'Minimize',fn:()=>minimizeWin(w)},
    null,
    {label:'Tile left',fn:()=>tileWin(w,'left')},
    {label:'Tile right',fn:()=>tileWin(w,'right')},
    {label:'Centre',fn:()=>tileWin(w,'centre')},
  ];
  if(DESKS>1){
    items.push(null);
    for(let n=1;n<=DESKS;n++)if(n!==w.desk)items.push({label:'Move to Desktop '+n,fn:()=>{
      w.desk=n;applyDeskVisibility();toast(`moved to Desktop ${n}`)}});
  }
  if(w.app.multi)items.push(null,{label:'New window',fn:()=>openAppNew(w.id)});
  items.push(null,{label:'Close',danger:true,fn:()=>closeWin(w)});
  showCtxItems(e,items);
}
/* true full screen: over the menu bar, dock and everything else */
function toggleFullWin(w){
  w.fs=!w.fs;
  if(w.fs&&!w.prev)w.prev={l:w.el.style.left,t:w.el.style.top,w:w.el.style.width,h:w.el.style.height};
  flipWin(w.el,()=>{
    w.el.classList.toggle('fullwin',w.fs);
    if(!w.fs&&w.prev){w.el.style.left=w.prev.l;w.el.style.top=w.prev.t;
      w.el.style.width=w.prev.w;w.el.style.height=w.prev.h;w.prev=null}
  });
  document.body.classList.toggle('has-fullwin',w.fs);
  if(w.fs)toast('full screen — Esc or F to exit');
  focusWin(w);
}
/* Ctrl+↓ organises whatever is on this desktop: grid → cascade → back where
   they were. Each window's pre-arrange geometry is remembered so the third
   press really does restore, not approximate. */
let ARRANGE_MODE=0;
function arrangeWindows(){
  const desk=$('#desktop'),W=desk.clientWidth,H=desk.clientHeight;
  const wins=[];WM.wins.forEach(x=>{if(!x.min&&(x.desk||1)===curDesk&&!x.fs)wins.push(x)});
  if(!wins.length)return toast('nothing to arrange on this desktop');
  wins.forEach(x=>{if(!x.arr)x.arr={l:x.el.style.left,t:x.el.style.top,w:x.el.style.width,h:x.el.style.height}});
  ARRANGE_MODE=(ARRANGE_MODE+1)%3;
  if(ARRANGE_MODE===1){                      // grid
    const n=wins.length,cols=Math.ceil(Math.sqrt(n)),rows=Math.ceil(n/cols),gap=10;
    const cw=(W-gap*(cols+1))/cols, ch=(H-gap*(rows+1))/rows;
    wins.forEach((x,i)=>{
      const c=i%cols,r=Math.floor(i/cols);
      if(x.max)toggleMax(x);
      flipWin(x.el,()=>{x.el.style.left=(gap+c*(cw+gap))+'px';x.el.style.top=(gap+r*(ch+gap))+'px';
        x.el.style.width=cw+'px';x.el.style.height=ch+'px'});
    });
    toast('▦ tiled — press again to cascade');
  }else if(ARRANGE_MODE===2){                // cascade
    wins.forEach((x,i)=>{
      if(x.max)toggleMax(x);
      flipWin(x.el,()=>{x.el.style.left=(40+i*38)+'px';x.el.style.top=(30+i*34)+'px';
        x.el.style.width=Math.min(920,W-120)+'px';x.el.style.height=Math.min(620,H-110)+'px'});
      focusWin(x);
    });
    toast('▤ cascaded — press again to restore');
  }else{                                     // back where they were
    wins.forEach(x=>{if(x.arr){const a=x.arr;flipWin(x.el,()=>{x.el.style.left=a.l;x.el.style.top=a.t;
      x.el.style.width=a.w;x.el.style.height=a.h});x.arr=null}});
    toast('windows restored');
  }
}
function tileWin(w,where){
  const desk=$('#desktop'),W=desk.clientWidth,H=desk.clientHeight;
  const z=where==='left'?{l:0,t:0,w:W/2,h:H}
    :where==='right'?{l:W/2,t:0,w:W/2,h:H}
    :{l:W*0.15,t:H*0.08,w:W*0.7,h:H*0.8};
  if(w.max)toggleMax(w);
  if(!w.snap)w.snap={l:w.el.style.left,t:w.el.style.top,w:w.el.style.width,h:w.el.style.height};
  flipWin(w.el,()=>{w.el.style.left=z.l+'px';w.el.style.top=z.t+'px';
    w.el.style.width=z.w+'px';w.el.style.height=z.h+'px'});
  focusWin(w);
}
function closeWin(w){
  if(w.app.onClose&&w.app.onClose(w)===false)return;
  sessionSave();
  stopWinTicks(w);                       // whatever the app registered dies with the window
  if(w.fs)document.body.classList.remove('has-fullwin');
  WM.wins.delete(w.key);w.tb.remove();
  zoomWin(w.el,w.id,-1).then(()=>w.el.remove());
  let top=null;WM.wins.forEach(o=>{if(!o.min&&(!top||+o.el.style.zIndex>+top.el.style.zIndex))top=o});
  if(top)focusWin(top);else{setMenubarApp('');updateDockHide();applyWindowActivity()}
  if(typeof deckAuto==='function')deckAuto();
  if(typeof buildDock==='function')buildDock();
}

/* ---- drag with edge snapping: left/right halves, corners quarters, top maximizes ---- */
function snapZone(x,y,dw,dh){
  const c=140;
  if(x<8&&y<c)return {l:0,t:0,w:dw/2,h:dh/2};
  if(x<8&&y>dh-c)return {l:0,t:dh/2,w:dw/2,h:dh/2};
  if(x>dw-8&&y<c)return {l:dw/2,t:0,w:dw/2,h:dh/2};
  if(x>dw-8&&y>dh-c)return {l:dw/2,t:dh/2,w:dw/2,h:dh/2};
  if(x<8)return {l:0,t:0,w:dw/2,h:dh};
  if(x>dw-8)return {l:dw/2,t:0,w:dw/2,h:dh};
  if(y<4)return {l:0,t:0,w:dw,h:dh,max:true};
  return null;
}
function snapGhost(z){
  let g=$('#snapghost');
  if(!z){if(g)g.classList.remove('on');return}
  if(!g){g=document.createElement('div');g.id='snapghost';$('#desktop').appendChild(g)}
  g.style.left=z.l+'px';g.style.top=z.t+'px';g.style.width=z.w+'px';g.style.height=z.h+'px';
  g.classList.add('on');
}
function applySnap(w,z){
  if(z.max){toggleMax(w);return}
  if(!w.snap)w.snap={l:w.el.style.left,t:w.el.style.top,w:w.el.style.width,h:w.el.style.height};
  flipWin(w.el,()=>{w.el.style.left=z.l+'px';w.el.style.top=z.t+'px';w.el.style.width=z.w+'px';w.el.style.height=z.h+'px'});
}
function dragify(w,handle){
  handle.addEventListener('pointerdown',e=>{
    if(e.target.closest('button'))return;
    if(w.max)return;
    const el=w.el, sx=e.clientX, sy=e.clientY, ol=el.offsetLeft, ot=el.offsetTop;
    const wasSnapped=!!w.snap;
    const desk=$('#desktop');
    let moved=false, zone=null;
    handle.setPointerCapture(e.pointerId);
    const move=ev=>{
      let dx=ev.clientX-sx, dy=ev.clientY-sy;
      if(!moved&&Math.abs(dx)+Math.abs(dy)<3)return;
      if(!moved){moved=true;el.classList.add('dragging')}
      let l=ol+dx, t=ot+dy;
      // dragging a snapped window away releases it back to its remembered size
      if(wasSnapped&&w.snap&&(Math.abs(dx)>40||Math.abs(dy)>40)){
        const pw=parseInt(w.snap.w),ph=parseInt(w.snap.h);
        el.style.width=w.snap.w;el.style.height=w.snap.h;w.snap=null;
        l=ev.clientX-pw/2; t=ev.clientY-12;
      }
      l=Math.max(-el.offsetWidth+90,Math.min(l,desk.clientWidth-90));
      t=Math.max(0,Math.min(t,desk.clientHeight-40));
      el.style.left=l+'px';el.style.top=t+'px';
      zone=snapZone(ev.clientX,ev.clientY-(desk.getBoundingClientRect().top||0),desk.clientWidth,desk.clientHeight);
      snapGhost(zone);
    };
    const up=()=>{
      handle.removeEventListener('pointermove',move);handle.removeEventListener('pointerup',up);
      el.classList.remove('dragging');snapGhost(null);
      if(zone&&moved)applySnap(w,zone);
      else if(moved)winSaveGeom(w);      // where you put it is where it opens next time
    };
    handle.addEventListener('pointermove',move);
    handle.addEventListener('pointerup',up);
  });
}
/* ---- 8-way resize (replaces the browser's CSS resize grip) ---- */
function resizify(w){
  const MIN_W=320, MIN_H=180;
  w.el.querySelectorAll('.rz').forEach(h=>{
    h.addEventListener('pointerdown',e=>{
      if(w.max)return;
      e.stopPropagation();e.preventDefault();
      focusWin(w);
      const d=h.dataset.d, el=w.el, desk=$('#desktop');
      const sx=e.clientX, sy=e.clientY;
      const r={l:el.offsetLeft,t:el.offsetTop,w:el.offsetWidth,h:el.offsetHeight};
      h.setPointerCapture(e.pointerId);
      el.classList.add('dragging');
      const move=ev=>{
        const dx=ev.clientX-sx, dy=ev.clientY-sy;
        let {l,t,w:nw,h:nh}=r;
        if(d.includes('e'))nw=r.w+dx;
        if(d.includes('s'))nh=r.h+dy;
        if(d.includes('w')){nw=r.w-dx;l=r.l+dx}
        if(d.includes('n')){nh=r.h-dy;t=r.t+dy}
        if(nw<MIN_W){if(d.includes('w'))l-=(MIN_W-nw);nw=MIN_W}
        if(nh<MIN_H){if(d.includes('n'))t-=(MIN_H-nh);nh=MIN_H}
        nw=Math.min(nw,desk.clientWidth); nh=Math.min(nh,desk.clientHeight);
        el.style.left=l+'px';el.style.top=t+'px';el.style.width=nw+'px';el.style.height=nh+'px';
      };
      const up=()=>{h.removeEventListener('pointermove',move);h.removeEventListener('pointerup',up);
        el.classList.remove('dragging');w.snap=null;winSaveGeom(w)};
      h.addEventListener('pointermove',move);
      h.addEventListener('pointerup',up);
    });
  });
}
function refreshApp(id){winsOf(id).forEach(w=>w.app.render(w.el.querySelector('.wbody'),w))}

/* ===== shared panel shell: header + search + actions + body ===== */
const SVG_SEARCH='<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>';
const SVG_EMPTY='<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M3 9h18M8 14h8"/></svg>';
function panelShell(body,o){
  o=o||{};
  /* The title bar already says which app this is. Repeating it as the first thing
     inside the window ("Memory" above "Memory") spent the widest row in every app
     on a word the user just read, and pushed the search box and the controls into
     the corner. It is dropped when it matches the window's own title, and kept
     when it does not — a panel showing something else genuinely needs a label. */
  /* Read the title bar itself rather than making all fourteen callers pass their
     window: what is actually on screen above this panel is the thing that must
     not be repeated, and a copilot panel or a dialog has no title bar at all —
     which is exactly when the label should stay. */
  const bar=body.closest&&body.closest('.win');
  const wtitle=(bar&&bar.querySelector('.tname')||{}).textContent||'';
  const dup=!!wtitle&&String(o.title||'').trim().toLowerCase()===wtitle.trim().toLowerCase();
  body.innerHTML=`<div class="pshell">
    <div class="phead">
      ${dup?'':`<span class="pt">${o.title||''}</span>`}
      ${o.sub?`<span class="ps">${o.sub}</span>`:''}
      <span class="sp"></span>
      ${o.search?`<span class="psearch">${SVG_SEARCH}<input id="${o.search.id}" placeholder="${esc(o.search.placeholder||'Search…')}" autocomplete="off"></span>`:''}
      ${o.actions||''}
    </div>
    <div class="pbody${o.flush?' flush':''}"></div>
  </div>`;
  const pb=body.querySelector('.pbody');
  if(o.search){
    const inp=body.querySelector('#'+o.search.id);
    let t;inp.oninput=()=>{clearTimeout(t);t=setTimeout(()=>o.search.onquery?o.search.onquery(inp.value):listFilter(pb,inp.value),120)};
  }
  return pb;
}
/* generic client-side filter: hides any [data-f] row not matching q; hides [data-fgroup] sections left empty */
function listFilter(scope,q){
  q=(q||'').toLowerCase().trim();
  scope.querySelectorAll('[data-f]').forEach(el=>{
    el.style.display=!q||(el.getAttribute('data-f')||'').toLowerCase().includes(q)?'':'none'});
  scope.querySelectorAll('[data-fgroup]').forEach(g=>{
    const any=[...g.querySelectorAll('[data-f]')].some(el=>el.style.display!=='none');
    g.style.display=any?'':'none'});
}
function emptyBox(title,hint,action,askApp,askPrompt){
  // every empty state is an invitation: the ✦ chip opens this app's copilot
  const ask=askApp?`<button class="cp-chip" style="margin-top:10px" onclick="copilotAsk('${esc(askApp)}',${JSON.stringify(askPrompt||'').replace(/"/g,'&quot;')})">✦ Ask ${esc((typeof agentName==='function'&&agentName())||'the agent')}</button>`:'';
  return `<div class="empty">${SVG_EMPTY}<div class="et">${esc(title)}</div>${hint?`<div class="eh">${hint}</div>`:''}${action||''}${ask}</div>`;
}
/* open (if needed) an app + its copilot panel, prefill and send */
function copilotAsk(appId,prompt){
  const w=winsOf(appId)[0]||openApp(appId);
  if(!w)return;
  const panel=w.el.querySelector('.copanel');
  if(panel&&!panel.classList.contains('open'))toggleCopilot(w);
  let tries=0;
  const t=()=>{
    const i=w.el.querySelector('.cp-in');
    if(!i){if(++tries<20)setTimeout(t,120);return}
    i.value=prompt||'';
    if(prompt)i.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}));
    else i.focus();
  };
  setTimeout(t,160);
}
function segTabs(id,labels,active,fn){
  return `<span class="seg" id="${id}">${labels.map((l,i)=>
    `<button class="${i===active?'on':''}" onclick="${fn}(${i})">${esc(l)}</button>`).join('')}</span>`;
}

