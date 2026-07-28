/* ===== icon layout engine: grid snap, multi-select, marquee, arrangements ===== */
const GRID={ox:14,oy:14,cx:96,cy:104};
const SEL=new Set();          // selected icon ids
function iconEls(){return [...document.querySelectorAll('#icons .dicon')]}
function iconEl(id){return document.querySelector(`.dicon[data-id="${CSS.escape(id)}"]`)}
function setSel(id,on){const el=iconEl(id);if(!el)return;
  if(on){SEL.add(id);el.classList.add('sel')}else{SEL.delete(id);el.classList.remove('sel')}}
function clearSel(){SEL.clear();document.querySelectorAll('.dicon.sel').forEach(x=>x.classList.remove('sel'))}
function snapXY(x,y){
  const desk=$('#desktop');
  let gx=GRID.ox+Math.round((x-GRID.ox)/GRID.cx)*GRID.cx;
  let gy=GRID.oy+Math.round((y-GRID.oy)/GRID.cy)*GRID.cy;
  gx=Math.max(GRID.ox,Math.min(gx,desk.clientWidth-92));
  gy=Math.max(GRID.oy,Math.min(gy,desk.clientHeight-100));
  return {x:gx,y:gy};
}
function occupiedMap(excludeIds){
  const m=new Set();
  launcherIds().forEach(id=>{if(excludeIds.has(id))return;const p=ICONPOS[id];if(p)m.add(p.x+','+p.y)});
  return m;
}
function freeCellNear(x,y,occ){
  // nearest free snapped cell, scanning outward ring by ring
  for(let r=0;r<14;r++){
    for(let dy=-r;dy<=r;dy++)for(let dx=-r;dx<=r;dx++){
      if(Math.max(Math.abs(dx),Math.abs(dy))!==r)continue;
      const c=snapXY(x+dx*GRID.cx,y+dy*GRID.cy);
      const k=c.x+','+c.y;
      if(!occ.has(k)){occ.add(k);return c}
    }
  }
  return snapXY(x,y);
}
function settle(el){el.classList.add('settle');setTimeout(()=>el.classList.remove('settle'),280)}
function applyIconPositions(animate){
  iconEls().forEach(el=>{
    const p=ICONPOS[el.dataset.id];if(!p)return;
    if(animate)settle(el);
    el.style.left=p.x+'px';el.style.top=p.y+'px';
  });
  renderBento();
}
function iconDrag(d,id){
  d.addEventListener('pointerdown',e=>{
    if(e.button!==0)return;
    e.stopPropagation();                     // an icon press never starts a marquee
    const desk=$('#desktop');
    d._moved=false;
    // dragging an unselected icon (no modifier) makes it the sole selection;
    // dragging a selected icon moves the whole selection together
    if(!SEL.has(id)&&!(e.ctrlKey||e.metaKey)){clearSel();setSel(id,true)}
    if(!SEL.has(id)&&(e.ctrlKey||e.metaKey)){setSel(id,true);d._addedOnDown=true}else d._addedOnDown=false;
    const members=[...SEL].map(mid=>({mid,el:iconEl(mid)})).filter(m=>m.el);
    const sx=e.clientX,sy=e.clientY;
    members.forEach(m=>{m.ox=m.el.offsetLeft;m.oy=m.el.offsetTop});
    d.setPointerCapture(e.pointerId);
    const move=ev=>{
      if(!d._moved&&Math.hypot(ev.clientX-sx,ev.clientY-sy)<5)return;
      d._moved=true;
      members.forEach(m=>{
        m.el.classList.add('dragging');
        const x=Math.max(0,Math.min(m.ox+ev.clientX-sx,desk.clientWidth-92));
        const y=Math.max(0,Math.min(m.oy+ev.clientY-sy,desk.clientHeight-100));
        m.el.style.left=x+'px';m.el.style.top=y+'px';
      });
    };
    const up=()=>{
      d.removeEventListener('pointermove',move);d.removeEventListener('pointerup',up);
      if(!d._moved)return;
      const movedIds=new Set(members.map(m=>m.mid));
      const occ=occupiedMap(movedIds);
      members.forEach(m=>{                    // snap each to the nearest free cell, animated
        m.el.classList.remove('dragging');
        const c=freeCellNear(m.el.offsetLeft,m.el.offsetTop,occ);
        settle(m.el);
        m.el.style.left=c.x+'px';m.el.style.top=c.y+'px';
        ICONPOS[m.mid]={x:c.x,y:c.y};
      });
      saveIconPos();
    };
    d.addEventListener('pointermove',move);d.addEventListener('pointerup',up);
  });
  d.onclick=e=>{
    e.stopPropagation();
    if(d._moved)return;                      // a drag is not a click
    if(e.ctrlKey||e.metaKey){if(!d._addedOnDown)setSel(id,!SEL.has(id))}
    else{clearSel();setSel(id,true)}
  };
  d.ondblclick=()=>openApp(id);
}
/* rubber-band selection on empty desktop space */
function ensureMarquee(){
  const icons=$('#icons');
  if(!document.getElementById('marquee')){
    const mq=document.createElement('div');mq.id='marquee';icons.appendChild(mq);
  }
  if(icons._mqWired)return;
  icons._mqWired=true;
  icons.addEventListener('pointerdown',e=>{
    if(e.target!==icons||e.button!==0)return;
    const r=icons.getBoundingClientRect();
    const sx=e.clientX-r.left,sy=e.clientY-r.top;
    let active=false;
    icons.setPointerCapture(e.pointerId);
    const move=ev=>{
      const x=ev.clientX-r.left,y=ev.clientY-r.top;
      if(!active&&Math.hypot(x-sx,y-sy)<4)return;
      active=true;
      const L=Math.min(sx,x),T=Math.min(sy,y),W=Math.abs(x-sx),H=Math.abs(y-sy);
      const mq=$('#marquee');if(!mq)return;
      mq.style.display='block';
      mq.style.left=L+'px';mq.style.top=T+'px';mq.style.width=W+'px';mq.style.height=H+'px';
      iconEls().forEach(el=>{
        const hit=el.offsetLeft<L+W&&el.offsetLeft+el.offsetWidth>L&&el.offsetTop<T+H&&el.offsetTop+el.offsetHeight>T;
        el.classList.toggle('sel',hit);
        if(hit)SEL.add(el.dataset.id);else SEL.delete(el.dataset.id);
      });
    };
    const up=()=>{
      icons.removeEventListener('pointermove',move);icons.removeEventListener('pointerup',up);
      const mq=$('#marquee');if(mq)mq.style.display='none';
      if(!active)clearSel();                 // a plain click on empty space clears the selection
    };
    icons.addEventListener('pointermove',move);icons.addEventListener('pointerup',up);
  });
}
/* arrangements: auto grid, sort by name, bento groups */
function arrangeIcons(byName){
  const desk=$('#desktop');
  const rows=Math.max(1,Math.floor((desk.clientHeight-GRID.oy-6)/GRID.cy));
  let ids=launcherIds().filter(id=>APPS[id]);
  if(byName)ids=ids.slice().sort((a,b)=>APPS[a].title.localeCompare(APPS[b].title));
  ids.forEach((id,i)=>{ICONPOS[id]={x:GRID.ox+Math.floor(i/rows)*GRID.cx,y:GRID.oy+(i%rows)*GRID.cy}});
  localStorage.removeItem('bentoBoxes');
  saveIconPos();applyIconPositions(true);
  toast(byName?'icons sorted by name':'icons auto-arranged');
}
const BENTO_GROUPS=[
  ['Essentials',['chat','apps','browser','files','terminal']],
  ['Create',['store','studio','themes','personalize']],
  ['Intelligence',['models','memory','kg','soul','profile']],
  ['Automation',['fabric','tasks','skills','mcp','telegram']],
  ['System',['taskmgr','control','settings','policies','snapshots','logs','tokens']],
  ['Library',['docs','about']],
];
function arrangeBento(){
  const desk=$('#desktop'),PADX=16,PADT=32,PADB=12,GAP=18;
  const groups=BENTO_GROUPS.map(([label,ids])=>[label,ids.filter(id=>APPS[id])]).filter(g=>g[1].length);
  const ua=launcherIds().filter(id=>id.startsWith('ua_')&&APPS[id]);
  if(ua.length)groups.push(['Your apps',ua]);
  const known=new Set(groups.flatMap(g=>g[1]));
  const rest=launcherIds().filter(id=>APPS[id]&&!known.has(id));
  if(rest.length)groups.push(['More',rest]);
  const boxes=[];
  let x=GRID.ox,y=GRID.oy,rowH=0;
  const maxW=desk.clientWidth-16;
  groups.forEach(([label,ids])=>{
    const cols=Math.min(ids.length,ids.length<=4?2:3);
    const rows=Math.ceil(ids.length/cols);
    const w=PADX*2+cols*GRID.cx-8, h=PADT+PADB+rows*GRID.cy-8;
    if(x+w>maxW&&x>GRID.ox){x=GRID.ox;y+=rowH+GAP;rowH=0}
    ids.forEach((id,i)=>{ICONPOS[id]={x:x+PADX+(i%cols)*GRID.cx,y:y+PADT+Math.floor(i/cols)*GRID.cy}});
    boxes.push({label,x,y,w,h});
    x+=w+GAP;rowH=Math.max(rowH,h);
  });
  localStorage.setItem('bentoBoxes',JSON.stringify(boxes));
  saveIconPos();applyIconPositions(true);
  toast('bento layout applied');
}
function renderBento(){
  document.querySelectorAll('#icons .bento').forEach(b=>b.remove());
  let boxes=[];try{boxes=JSON.parse(localStorage.getItem('bentoBoxes')||'[]')}catch(e){}
  const box=$('#icons');if(!box)return;
  boxes.forEach(b=>{
    const d=document.createElement('div');d.className='bento';
    d.style.left=b.x+'px';d.style.top=b.y+'px';d.style.width=b.w+'px';d.style.height=b.h+'px';
    d.innerHTML=`<span class="blbl">${esc(b.label)}</span>`;
    box.prepend(d);
  });
}
function buildDesktop(){
  rebuildLaunchers();
  $('#desktop').addEventListener('click',e=>{if(e.target.id==='desktop')clearSel()});
  $('#startbtn').onclick=e=>{e.stopPropagation();toggleStart()};
  document.addEventListener('click',e=>{
    if(!e.target.closest('#startmenu'))toggleStart(false);
    if(!e.target.closest('#ctxmenu'))$('#ctxmenu').classList.remove('show');
  });
  $('#desktop').addEventListener('contextmenu',e=>{
    if(e.target.closest('.win'))return;
    e.preventDefault();
    const m=$('#ctxmenu');
    m.innerHTML=`<button data-a="chat">New chat</button><button data-a="taskmgr">Task Manager</button>
      <button data-a="studio">App Studio</button><hr>
      <button data-x="arr-grid">Auto arrange icons</button>
      <button data-x="arr-name">Sort icons by name</button>
      <button data-x="arr-bento">Group icons (bento)</button>
      <button data-x="arrange">Arrange widgets</button><hr>
      <button data-a="personalize">Change wallpaper</button>
      <button data-a="settings">Settings</button><button data-a="about">About AgentOS</button>`;
    m.querySelectorAll('button').forEach(b=>b.onclick=()=>{m.classList.remove('show');
      const x=b.dataset.x;
      if(x==='arrange')arrangeWidgets();
      else if(x==='arr-grid')arrangeIcons(false);
      else if(x==='arr-name')arrangeIcons(true);
      else if(x==='arr-bento')arrangeBento();
      else openApp(b.dataset.a)});
    ctxShow(e,m);
  });
}
function toggleStart(force){
  const on=force!==undefined?force:!$('#startmenu').classList.contains('show');
  $('#startmenu').classList.toggle('show',on);
  $('#startbtn').classList.toggle('on',on);
  if(on){const q=$('#smq');if(q){q.value='';smRender('');setTimeout(()=>q.focus(),10)}}
}
$('#smq').addEventListener('input',e=>smRender(e.target.value.trim().toLowerCase()));
$('#smq').addEventListener('keydown',e=>{
  if(e.key==='Escape')toggleStart(false);
  else if(e.key==='Enter'){const b=$('#smapps .smapp');if(b)b.click()}
});
let DOCK=JSON.parse(localStorage.getItem('dock')||'null')||['chat','store','browser','files','terminal','taskmgr'];
function buildDock(){
  const box=$('#dock');if(!box)return;box.innerHTML='';
  DOCK.forEach(id=>{
    const a=APPS[id];if(!a)return;
    const b=document.createElement('button');b.className='dockb';b.dataset.tip=a.title;b.dataset.app=id;
    b.innerHTML=appIcon(id,46);
    b.classList.toggle('running',winsOf(id).some(w=>!w.min));
    b.onclick=()=>openApp(id);
    b.oncontextmenu=e=>{e.preventDefault();dockCtxMenu(e,id,a)};
    box.appendChild(b);
  });
  // a pinned app's open window lives on its dock tile, not as a second tile in #tbwins
  WM.wins.forEach(w=>w.tb.classList.toggle('indock',DOCK.includes(w.id)));
  updateDockSeps();
}
function dockCtxMenu(e,id,a){
  const open=winsOf(id);
  const items=[];
  if(a.multi||!open.length)items.push({label:open.length?'New window':'Open',fn:()=>openAppNew(id)});
  if(open.length)items.push({label:'Close '+(open.length>1?'all windows':'window'),fn:()=>open.forEach(closeWin)});
  items.push(null,{label:'Remove from Dock',fn:()=>{
    DOCK=DOCK.filter(x=>x!==id);localStorage.setItem('dock',JSON.stringify(DOCK));buildDock();toast('removed from dock')}});
  showCtxItems(e,items);
}
/* ---- dock magnification: continuous neighbor falloff, macOS-style ---- */
(function(){
  const bar=document.getElementById('taskbar');if(!bar)return;
  const RANGE=96, LIFT=16, GROW=.42;
  let raf=0,lastX=null;
  function tiles(){return bar.querySelectorAll('.dockb,.tbwin,.tbnat,#startbtn')}
  function apply(){
    raf=0;
    tiles().forEach(b=>{
      if(lastX===null){b.style.transform='';return}
      const r=b.getBoundingClientRect();
      const d=Math.abs(lastX-(r.left+r.width/2));
      const f=Math.max(0,1-(d/RANGE)*(d/RANGE));      // smooth quadratic falloff
      b.style.transform=f>0.01?`translateY(${-LIFT*f}px) scale(${1+GROW*f})`:'';
    });
  }
  bar.addEventListener('pointermove',e=>{
    if(Motion.reduced)return;
    lastX=e.clientX;
    if(!raf)raf=requestAnimationFrame(apply);
  });
  bar.addEventListener('pointerleave',()=>{
    lastX=null;
    tiles().forEach(b=>{
      b.style.transition='transform .28s cubic-bezier(.22,1,.36,1)';
      b.style.transform='';
      setTimeout(()=>b.style.transition='',300);
    });
  });
})();
function updateDockSeps(){
  // the second separator only shows when something actually sits to its right
  const seps=document.querySelectorAll('#taskbar .dsep');
  const any=[...document.querySelectorAll('#tbwins .tbwin')].some(b=>!b.classList.contains('indock'))
    ||($('#tbnative')&&$('#tbnative').children.length>0);
  if(seps[1])seps[1].style.display=any?'':'none';
}
function pinToDock(id){if(!DOCK.includes(id)){DOCK.push(id);localStorage.setItem('dock',JSON.stringify(DOCK));buildDock();toast('added to dock')}}
function tickClock(){
  // the menu-bar clock follows Settings → Locale (timezone + 12/24h), not the browser
  const lo=(cfg&&cfg.locale)||{};
  const o={};
  if(lo.timezone)o.timeZone=lo.timezone;
  const loc=lo.language||[];
  const n=new Date();
  try{
    $('#tbclock .tm').textContent=n.toLocaleTimeString(loc,{...o,hour:'2-digit',minute:'2-digit',
      hour12:lo.clock?lo.clock==='12h':undefined});
    $('#tbclock .dt').textContent=n.toLocaleDateString(loc,{...o,weekday:'short',day:'numeric',month:'short'});
  }catch(e){
    $('#tbclock .tm').textContent=n.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
    $('#tbclock .dt').textContent=n.toLocaleDateString([],{weekday:'short',day:'numeric',month:'short'});
  }
}

