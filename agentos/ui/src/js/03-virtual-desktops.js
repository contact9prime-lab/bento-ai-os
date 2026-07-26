/* ================= virtual desktops ================= */
let DESKS=+localStorage.getItem('desks')||2;
let curDesk=+localStorage.getItem('curDesk')||1;
function buildPager(){
  const p=$('#pager');if(!p)return;p.innerHTML='';
  for(let i=1;i<=DESKS;i++){
    const b=document.createElement('button');b.className='pgb'+(i===curDesk?' on':'');b.textContent=i;
    b.onclick=()=>switchDesk(i);
    b.oncontextmenu=e=>{e.preventDefault();moveActiveToDesk(i)};
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
  const go=()=>{
    applyDeskVisibility();renderWidgets();buildPager();
    let top=null;WM.wins.forEach(o=>{if(deskVisible(o)&&!o.min&&(!top||+o.el.style.zIndex>+top.el.style.zIndex))top=o});
    WM.wins.forEach(w=>{if(deskVisible(w)&&!w.min)Motion.run(w.el,[{transform:`translateX(${46*dir}px)`,opacity:0},{transform:'none',opacity:1}],{duration:220,easing:EASE.out})});
    if(top)focusWin(top);
  };
  Motion.reduced||!out.length?go():setTimeout(go,170);
  toast('▪ Desktop '+n);
}
function moveActiveToDesk(n){
  let act=null;WM.wins.forEach(w=>{if(w.el.classList.contains('active'))act=w});
  if(!act)return toast('no active window to move');
  act.desk=n;applyDeskVisibility();
  toast('moved "'+act.app.title+'" to Desktop '+n);
}

