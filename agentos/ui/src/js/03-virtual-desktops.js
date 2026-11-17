/* ================= virtual desktops ================= */
let DESKS=+localStorage.getItem('desks')||2;
let curDesk=+localStorage.getItem('curDesk')||1;
function buildPager(){
  const p=$('#pager');if(!p)return;p.innerHTML='';
  for(let i=1;i<=DESKS;i++){
    const b=document.createElement('button');b.className='pgb'+(i===curDesk?' on':'');b.textContent=i;
    const names=[];WM.wins.forEach(w=>{if((w.desk||1)===i&&!w.min)names.push(w.app.title)});
    // a task's desktop says which task, and whether it is still working (24m-taskdesks.js)
    const td=typeof taskDeskOf==='function'?taskDeskOf(i):null;
    if(td){b.classList.add('task');if(!td.done)b.classList.add('run');
      const l=document.createElement('span');l.className='pgt';l.textContent=td.title.slice(0,14);b.append(l)}
    // the scene each desktop shows (01b immersiveSceneOf), when they are not all the same one
    const sc=typeof immersiveSceneOf==='function'&&IMMERSIVE.on?immersiveSceneOf(i):'';
    if(sc&&deskScenesDiffer()){const g=document.createElement('span');g.className='pgs';g.textContent=DESK_SCENE_GLYPH[sc]||'·';
      g.setAttribute('aria-hidden','true');b.append(g);b.dataset.scene=sc}
    b.title=(td?`Desktop ${i}: “${td.title}”, ${td.done?'done':'working'}`:`Desktop ${i}`)
      +(sc&&deskScenesDiffer()?` · ${IMMERSIVE_NAMES[sc]||sc}`:'')
      +(names.length?` — ${names.join(', ')}`:' — empty')
      +'\nclick to switch · right-click to send the active window here · drop a window to move it';
    b.classList.toggle('has',names.length>0);
    b.onclick=()=>switchDesk(i);
    b.oncontextmenu=e=>{e.preventDefault();moveActiveToDesk(i)};
    // the pager is a drop target for windows dragged out of the Spaces overview
    b.ondragover=e=>{e.preventDefault();b.classList.add('drop')};
    b.ondragleave=()=>b.classList.remove('drop');
    b.ondrop=e=>{
      e.preventDefault();b.classList.remove('drop');
      const w=WM.wins.get(e.dataTransfer.getData('text/agentos-window'));
      if(!w||w.desk===i)return;
      w.desk=i;applyDeskVisibility();buildPager();
      if(typeof EXPO!=='undefined'&&EXPO.on){exposeSpaces();exposeGrid()}
      toast(`moved "${w.app.title}" to Desktop ${i}`);
    };
    p.appendChild(b);
  }
  // the wheel over the pager scrolls the desktops, one notch at a time
  if(!p._wheel){p._wheel=1;p.addEventListener('wheel',e=>{e.preventDefault();
    const now=Date.now();if(now-(p._wt||0)<220)return;p._wt=now;switchDeskBy(e.deltaY>0||e.deltaX>0?1:-1)},{passive:false})}
  // a new desktop is somewhere to put something: go there and ask what it shows
  if(DESKS<6){const a=document.createElement('button');a.className='pgb add';a.textContent='+';a.title='add a desktop';
    a.onclick=()=>deskAdd();p.appendChild(a)}
  deskBtnPaint();
}
var DESK_SCENE_GLYPH={island:'⌂',devices:'▦',apps:'⊞',aurora:'✦',movement:'◷',crew:'☺',office:'▤',hq:'▤',world:'❀',mind:'✺'};
/* ---- what a desktop shows, chosen on the desktop ----
   Asked for as "every desktop I add, I can change the scene of the desktop: Town, Device, App Hub
   (with widgets). That option should be available on the desktop itself. Also I should be able to
   have a different company in different desktops". The scenes were already per desktop
   (01b immersiveSceneOf), but the only picker was in Settings. #deskbtn in the menu bar names
   the scene of the desktop in front and opens the menu; a new desktop opens it by itself.
   A desktop may also OPEN one of your companies when you come to it (desk.company.d<n>, this
   browser's). The open company is the account's, so another browser signed in as you moves too.
   TUI: not applicable, a terminal has no desktops or scenes; `bento company open` switches
   companies there. SUI: a page control inside the menu-bar band, whose height it never changes. */
var DESK_MAIN_SCENES=['island','devices','apps'];
var DESKCO={list:[],at:0};
function deskCompanyOf(n){try{return localStorage.getItem('desk.company.d'+n)||''}catch(e){return ''}}
function deskCompanyName(id){const c=DESKCO.list.find(x=>x.id===id);return c?c.name:''}
async function deskCompaniesLoad(){
  try{const r=await fetch('/api/companies',{quiet:true});if(!r.ok)return;
    const j=await r.json();DESKCO.list=(j.companies||[]).filter(c=>c.id);DESKCO.at=Date.now();deskBtnPaint()}catch(e){}
}
function deskCompanySet(n,id){
  try{id?localStorage.setItem('desk.company.d'+n,id):localStorage.removeItem('desk.company.d'+n)}catch(e){}
  deskBtnPaint();
  if(n===curDesk){deskCompanySync(n);deskCompanyChanged()}
}
/* The desktop's company differs from the one the scene was drawn for: the Devices board asks again. */
function deskCompanyChanged(){if(typeof DEVSCENE!=='undefined')DEVSCENE.every=false;if(typeof DEVSCENE!=='undefined'&&DEVSCENE.on&&typeof devSceneLoad==='function')devSceneLoad()}
/* Coming to a desktop opens its company. A desktop with none keeps whichever is open. */
async function deskCompanySync(n){
  const id=deskCompanyOf(n);if(!id)return;
  if(!DESKCO.at)await deskCompaniesLoad();
  const c=DESKCO.list.find(x=>x.id===id);
  if(!c){if(DESKCO.at)deskCompanySet(n,'');return}      // a company you no longer keep
  if(c.active||n!==curDesk)return;
  try{
    const r=await fetch('/api/companies/active',{method:'PUT',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id,surface:'gui'})});
    const j=await r.json().catch(()=>({}));
    if(!r.ok)return toast(`Desktop ${n} could not open ${c.name}: ${j.error||'the server refused'}`,{kind:'err'});
    DESKCO.list=(j.companies||[]).filter(x=>x.id);DESKCO.at=Date.now();
    toast(`Desktop ${n} · ${c.name}`);deskBtnPaint();
  }catch(e){toast(`Desktop ${n} could not open ${c.name}`,{kind:'err'})}
}
function deskAdd(){
  if(DESKS>=9)return;
  DESKS++;localStorage.setItem('desks',DESKS);
  // a number used before starts clean: no scene or company left from a desktop removed earlier
  try{localStorage.removeItem('immersive.scene.d'+DESKS);localStorage.removeItem('desk.company.d'+DESKS)}catch(e){}
  buildPager();switchDesk(DESKS);
  setTimeout(()=>deskMenu(),240);
}
/* Desktop n is going: every desktop after it takes the number before, with its scene and company. */
function deskShift(n){
  const get=k=>{try{return localStorage.getItem(k)}catch(e){return null}};
  const put=(k,v)=>{try{v?localStorage.setItem(k,v):localStorage.removeItem(k)}catch(e){}};
  const im=typeof immersiveSceneOf==='function',sc=[],co=[];
  for(let i=n+1;i<=DESKS;i++){sc.push(im?immersiveSceneOf(i):'');co.push(deskCompanyOf(i))}
  for(let i=n;i<DESKS;i++){
    const s=sc[i-n];
    if(i===1){if(im&&IMMERSIVE.chosen&&s){put('immersive.scene',s);IMMERSIVE.scene=s}}
    else put('immersive.scene.d'+i,s);
    put('desk.company.d'+i,co[i-n]);
  }
  put('immersive.scene.d'+DESKS,'');put('desk.company.d'+DESKS,'');
}
function deskBtnPaint(){
  const b=document.getElementById('deskbtn');if(!b)return;
  const on=typeof IMMERSIVE!=='undefined'&&IMMERSIVE.on;
  const sc=on&&typeof immersiveSceneNow==='function'?immersiveSceneNow():'';
  const co=deskCompanyName(deskCompanyOf(curDesk));
  b.textContent='';
  const g=document.createElement('span');g.className='dkb-g';g.setAttribute('aria-hidden','true');g.textContent=sc?(DESK_SCENE_GLYPH[sc]||'·'):'▪';
  const l=document.createElement('span');l.className='dkb-l';l.textContent=(sc?(IMMERSIVE_NAMES[sc]||sc):'Desktop '+curDesk)+(co?' · '+co:'');
  const c=document.createElement('span');c.className='dkb-c';c.setAttribute('aria-hidden','true');c.textContent='▾';
  b.append(g,l,c);
  b.setAttribute('aria-label',`Desktop ${curDesk} shows ${sc?(IMMERSIVE_NAMES[sc]||sc):'no scene'}${co?', company '+co:''}. Change it`);
  b.onclick=()=>deskMenu();
}
function deskMenuClose(){
  const m=document.getElementById('deskmenu');if(m)m.remove();
  document.removeEventListener('pointerdown',deskMenuOutside,true);document.removeEventListener('keydown',deskMenuKey,true);
  const b=document.getElementById('deskbtn');if(b)b.setAttribute('aria-expanded','false');
}
function deskMenuOutside(e){const m=document.getElementById('deskmenu');
  if(m&&!m.contains(e.target)&&!(e.target.closest&&e.target.closest('#deskbtn')))deskMenuClose()}
function deskMenuKey(e){if(e.key==='Escape'){e.stopPropagation();deskMenuClose();const b=document.getElementById('deskbtn');if(b)b.focus()}}
/* The menu for the desktop in front. Built with text nodes: a company's name is the person's words. */
function deskMenu(){
  if(document.getElementById('deskmenu'))return deskMenuClose();
  const n=curDesk,m=document.createElement('div');m.id='deskmenu';m.setAttribute('role','dialog');m.setAttribute('aria-label',`Desktop ${n}`);
  const el=(tag,cls,text)=>{const x=document.createElement(tag);if(cls)x.className=cls;if(text!==undefined)x.textContent=text;return x};
  const paint=()=>{
    m.textContent='';
    m.append(el('h3','',`Desktop ${n}`));
    const on=typeof IMMERSIVE!=='undefined'&&IMMERSIVE.on,now=on?immersiveSceneNow():'';
    m.append(el('h4','','Scene'));
    if(!on){
      const p=el('p','dkm-note','Scenes come with the immersive look, which is off in this browser.');
      const t=el('button','endbtn','Turn it on');t.type='button';
      t.onclick=()=>{if(typeof setImmersive==='function')setImmersive(true);paint();deskBtnPaint()};
      m.append(p,t);
    }else{
      const lite=typeof liteScreen==='function'&&liteScreen(),ok=s=>!lite||LITE_SCENES[s];
      const row=(list,cls)=>{const r=el('div',cls);r.setAttribute('role','group');
        list.filter(ok).forEach(s=>{const b=el('button','dkm-s'+(s===now?' on':''));b.type='button';b.setAttribute('aria-pressed',String(s===now));
          b.append(el('i','',DESK_SCENE_GLYPH[s]||'·'),el('span','',IMMERSIVE_NAMES[s]||s));
          b.onclick=()=>{setImmersiveScene(s);paint()};r.append(b)});
        return r};
      m.append(row(DESK_MAIN_SCENES,'dkm-main'));
      const rest=IMMERSIVE_SCENES.filter(s=>DESK_MAIN_SCENES.indexOf(s)<0&&ok(s));
      if(rest.length){m.append(el('h4','','More scenes'),row(rest,'dkm-more'))}
      if(lite)m.append(el('p','dkm-note','This small machine draws only the light scenes on its own screen.'));
    }
    if(DESKCO.list.length>1){
      m.append(el('h4','','Company'));
      const cur=deskCompanyOf(n),r=el('div','dkm-co');r.setAttribute('role','radiogroup');r.setAttribute('aria-label','Company on this desktop');
      [{id:'',name:'Whichever is open'}].concat(DESKCO.list).forEach(c=>{
        const b=el('button','dkm-c'+(c.id===cur?' on':''));b.type='button';b.setAttribute('role','radio');b.setAttribute('aria-checked',String(c.id===cur));
        b.append(el('span','',c.name));if(c.id&&c.active)b.append(el('small','','open now'));
        b.onclick=()=>{deskCompanySet(n,c.id);paint()};r.append(b)});
      m.append(r,el('p','dkm-note','Coming to this desktop opens that company, everywhere you are signed in.'));
    }
    if(DESKS>1){const x=el('button','endbtn dkm-rm','Remove this desktop');x.type='button';
      x.onclick=()=>{deskMenuClose();removeDesk(n)};m.append(x)}
  };
  paint();
  document.body.append(m);
  const b=document.getElementById('deskbtn');
  if(b){b.setAttribute('aria-expanded','true');const r=b.getBoundingClientRect();
    m.style.top=Math.round(r.bottom+6)+'px';
    m.style.right=Math.max(8,Math.round(innerWidth-r.right))+'px'}
  document.addEventListener('pointerdown',deskMenuOutside,true);document.addEventListener('keydown',deskMenuKey,true);
  const first=m.querySelector('button.on')||m.querySelector('button');if(first)first.focus();
  // the list may be older than a company made in another window
  deskCompaniesLoad().then(()=>{if(document.getElementById('deskmenu')===m)paint()});
}
function deskScenesDiffer(){
  if(typeof immersiveSceneOf!=='function')return false;
  const s=new Set();for(let i=1;i<=DESKS;i++)s.add(immersiveSceneOf(i));return s.size>1;
}
function deskVisible(w){return (w.desk||1)===curDesk}
function applyDeskVisibility(){
  WM.wins.forEach(w=>{
    const on=deskVisible(w);
    w.el.style.display=(on&&!w.min)?'':'none';
    w.tb.style.display=on?'':'none';
  });
  applyWindowActivity();   // windows on the desktops you left stop working until you come back
}
function switchDesk(n){
  if(typeof sessionSave==='function')sessionSave();
  if(n===curDesk)return;
  const dir=n>curDesk?1:-1;
  // outgoing windows slide away, incoming slide in from the travel direction
  const out=[];WM.wins.forEach(w=>{if(deskVisible(w)&&!w.min)out.push(w)});
  out.forEach(w=>Motion.run(w.el,[{transform:'none',opacity:1},{transform:`translateX(${-46*dir}px)`,opacity:0}],{duration:200,easing:EASE.in}));
  const sceneWas=typeof immersiveSceneNow==='function'?immersiveSceneNow():'';
  curDesk=n;localStorage.setItem('curDesk',n);
  // each desktop shows its own scene: the Town on one, the Devices board on another
  if(typeof immersiveDeskChanged==='function')immersiveDeskChanged(sceneWas);
  // a desktop may open one of your companies (deskCompanySync), and its board follows
  deskMenuClose();deskCompanySync(n);deskCompanyChanged();
  // In session mode a desktop is a real sway workspace, so external windows move
  // with it instead of following you everywhere. The shell comes along too.
  if(typeof PLATFORM!=='undefined'&&PLATFORM.mode==='de')
    fetch('/api/wm/desktop',{method:'POST',quiet:true,headers:{'Content-Type':'application/json'},
      body:JSON.stringify({desktop:n})}).then(()=>{
        if(typeof updateNativeWindows==='function')setTimeout(updateNativeWindows,200)}).catch(()=>{});
  const go=()=>{
    applyDeskVisibility();renderWidgets();buildPager();
    if(typeof deckAuto==='function')deckAuto();
    let top=null;WM.wins.forEach(o=>{if(deskVisible(o)&&!o.min&&(!top||+o.el.style.zIndex>+top.el.style.zIndex))top=o});
    WM.wins.forEach(w=>{if(deskVisible(w)&&!w.min)Motion.run(w.el,[{transform:`translateX(${46*dir}px)`,opacity:0},{transform:'none',opacity:1}],{duration:220,easing:EASE.out})});
    if(top)focusWin(top);
  };
  Motion.reduced||!out.length?go():setTimeout(go,170);
  toast('▪ Desktop '+n);
}
/* Ctrl+← / Ctrl+→ walk the desktops (wrapping), Ctrl+Shift+← / → carry the
   focused window with you — the pair people reach for without being told. */
function switchDeskBy(delta){
  if(DESKS<2)return toast('only one desktop — add another in Spaces (F3)');
  switchDesk(((curDesk-1+delta)%DESKS+DESKS)%DESKS+1);
}
function moveActiveDeskBy(delta){
  if(DESKS<2)return toast('only one desktop — add another in Spaces (F3)');
  const a=(typeof activeWin==='function')&&activeWin();
  if(!a)return toast('no active window to move');
  const n=((curDesk-1+delta)%DESKS+DESKS)%DESKS+1;
  a.desk=n;applyDeskVisibility();buildPager();
  switchDesk(n);
  toast(`"${a.app.title}" → Desktop ${n}`);
}
function moveActiveToDesk(n){
  let act=null;WM.wins.forEach(w=>{if(w.el.classList.contains('active'))act=w});
  if(!act)return toast('no active window to move');
  act.desk=n;applyDeskVisibility();
  toast('moved "'+act.app.title+'" to Desktop '+n);
}


// which companies a desktop can open (the menu asks again when it opens)
setTimeout(()=>{deskCompaniesLoad()},1200);
