/* ================= virtual desktops ================= */
let DESKS=+localStorage.getItem('desks')||2;
let curDesk=+localStorage.getItem('curDesk')||1;
function buildPager(){
  const p=$('#pager');if(!p)return;p.innerHTML='';
  for(let i=1;i<=DESKS;i++){
    const b=document.createElement('button');b.className='pgb'+(i===curDesk?' on':'');b.textContent=i;
    const names=[];WM.wins.forEach(w=>{if((w.desk||1)===i&&!w.min)names.push(w.app.title)});
    b.title=`Desktop ${i}`+(names.length?` — ${names.join(', ')}`:' — empty')
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
  if(DESKS<6){const a=document.createElement('button');a.className='pgb add';a.textContent='+';a.title='add a desktop';
    a.onclick=()=>{DESKS++;localStorage.setItem('desks',DESKS);buildPager()};p.appendChild(a)}
}
function deskVisible(w){return (w.desk||1)===curDesk}
function applyDeskVisibility(){
  WM.wins.forEach(w=>{
    const on=deskVisible(w);
    w.el.style.display=(on&&!w.min)?'':'none';
    w.tb.style.display=on?'':'none';
  });
}
function switchDesk(n){
  if(n===curDesk)return;
  const dir=n>curDesk?1:-1;
  // outgoing windows slide away, incoming slide in from the travel direction
  const out=[];WM.wins.forEach(w=>{if(deskVisible(w)&&!w.min)out.push(w)});
  out.forEach(w=>Motion.run(w.el,[{transform:'none',opacity:1},{transform:`translateX(${-46*dir}px)`,opacity:0}],{duration:200,easing:EASE.in}));
  curDesk=n;localStorage.setItem('curDesk',n);
  // In session mode a desktop is a real sway workspace, so external windows move
  // with it instead of following you everywhere. The shell comes along too.
  if(typeof PLATFORM!=='undefined'&&PLATFORM.mode==='de')
    fetch('/api/wm/desktop',{method:'POST',headers:{'Content-Type':'application/json'},
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

