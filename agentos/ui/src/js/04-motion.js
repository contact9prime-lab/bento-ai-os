/* ================= motion =================
   One motion vocabulary for the whole shell (WAAPI). Everything routes through
   Motion so prefers-reduced-motion is honored in one place. Durations/curves
   mirror the CSS tokens in 00-tokens-base.css. */
const EASE={out:'cubic-bezier(.22,1,.36,1)',in:'cubic-bezier(.4,0,.7,.2)',spring:'cubic-bezier(.34,1.4,.64,1)',inout:'cubic-bezier(.65,0,.35,1)'};
const Motion={
  get reduced(){return matchMedia('(prefers-reduced-motion: reduce)').matches},
  run(el,frames,opts){                       // animate, resolving immediately under reduced motion
    if(this.reduced||!el.animate){return {finished:Promise.resolve(),cancel(){}}}
    const a=el.animate(frames,opts);
    a.finished.catch(()=>{});                // cancelled animations must never surface as unhandled rejections
    return a;
  },
};
/* where on screen an app's icon lives right now (dock tile, window tile, or start button) —
   the anchor that windows zoom out of and minimize into */
function iconRect(appId){
  const el=document.querySelector(`#dock .dockb[data-app="${CSS.escape(appId)}"]`)
    ||[...document.querySelectorAll('#tbwins .tbwin')].find(b=>b.dataset.app===appId)
    ||$('#startbtn');
  return el?el.getBoundingClientRect():null;
}
/* zoom a window between its icon and its on-screen frame. dir: 1 = open (icon→frame), -1 = close */
function zoomWin(el,appId,dir){
  const r=el.getBoundingClientRect(), ir=iconRect(appId);
  const dx=ir?(ir.left+ir.width/2)-(r.left+r.width/2):0;
  const dy=ir?(ir.top+ir.height/2)-(r.top+r.height/2):(innerHeight-r.top);
  const at=`translate(${dx}px,${dy}px) scale(.06)`;
  const frames=dir>0?[{transform:at,opacity:.2},{transform:'none',opacity:1}]
                    :[{transform:'none',opacity:1},{transform:at,opacity:.15}];
  return Motion.run(el,frames,{duration:dir>0?300:230,easing:dir>0?EASE.out:EASE.in}).finished;
}
/* FLIP a window between two layout states: call with a fn that mutates geometry */
function flipWin(el,mutate){
  const a=el.getBoundingClientRect(); mutate(); const b=el.getBoundingClientRect();
  if(Motion.reduced)return Promise.resolve();
  const sx=a.width/b.width, sy=a.height/b.height;
  return Motion.run(el,[
    {transform:`translate(${a.left-b.left}px,${a.top-b.top}px) scale(${sx},${sy})`,transformOrigin:'top left'},
    {transform:'none',transformOrigin:'top left'},
  ],{duration:320,easing:EASE.out}).finished;
}
/* popover entrance: scales out of its anchor edge. origin: 'top'|'bottom'|'point' */
function popIn(el,o){
  o=o||{};
  el.style.transformOrigin=o.origin||'top right';
  Motion.run(el,[{transform:'scale(.9)',opacity:0},{transform:'none',opacity:1}],{duration:170,easing:EASE.out});
}
function popOut(el,done){
  const fin=Motion.run(el,[{transform:'none',opacity:1},{transform:'scale(.94)',opacity:0}],{duration:120,easing:EASE.in}).finished;
  (fin||Promise.resolve()).then(done);
}
/* dock launch feedback: the macOS bounce */
function dockBounce(appId){
  const b=document.querySelector(`#dock .dockb[data-app="${CSS.escape(appId)}"]`);
  if(!b)return;
  Motion.run(b,[
    {transform:'translateY(0)'},{transform:'translateY(-22px)',offset:.3},
    {transform:'translateY(0)',offset:.6},{transform:'translateY(-9px)',offset:.78},
    {transform:'translateY(0)'},
  ],{duration:620,easing:EASE.inout});
}

/* ---- context menu: one animated positioner for every menu in the shell ---- */
function ctxShow(e,m){
  m=m||$('#ctxmenu');
  m.classList.add('show');
  const mw=m.offsetWidth||200, mh=m.offsetHeight||200;
  m.style.left=Math.min(e.clientX,innerWidth-mw-8)+'px';
  m.style.top=Math.max(34,Math.min(e.clientY,innerHeight-mh-8))+'px';
  m.style.transformOrigin=(e.clientY+mh>innerHeight?'bottom':'top')+' '+(e.clientX+mw>innerWidth?'right':'left');
  Motion.run(m,[{transform:'scale(.92)',opacity:0},{transform:'none',opacity:1}],{duration:150,easing:EASE.out});
}
function showCtxItems(e,items){
  const m=$('#ctxmenu');
  m.innerHTML=items.map((it,i)=>it===null?'<hr>':`<button data-i="${i}"${it.danger?' style="color:var(--err)"':''}>${it.label}</button>`).join('');
  m.querySelectorAll('button').forEach(b=>b.onclick=()=>{m.classList.remove('show');const it=items[+b.dataset.i];if(it&&it.fn)it.fn()});
  ctxShow(e,m);
}

/* ---- modal dialogs: AgentOS sheets instead of window.confirm/alert ---- */
function osDialog(o){
  return new Promise(res=>{
    const scr=document.createElement('div');scr.className='dlg-scrim';
    scr.innerHTML=`<div class="dlg" role="alertdialog" aria-modal="true">
      <div class="dlg-icn">${o.danger?'!':'?'}</div>
      <div class="dlg-t">${esc(o.title||'')}</div>
      ${o.message?`<div class="dlg-m">${esc(o.message)}</div>`:''}
      <div class="dlg-b">
        ${o.cancelText===null?'':`<button class="dlg-cancel">${esc(o.cancelText||'Cancel')}</button>`}
        <button class="dlg-ok${o.danger?' danger':''}">${esc(o.confirmText||'OK')}</button>
      </div></div>`;
    document.body.appendChild(scr);
    const dlg=scr.querySelector('.dlg');
    Motion.run(scr,[{opacity:0},{opacity:1}],{duration:140,easing:EASE.out});
    Motion.run(dlg,[{transform:'scale(.92) translateY(10px)',opacity:0},{transform:'none',opacity:1}],{duration:220,easing:EASE.spring});
    const close=v=>{
      Motion.run(scr,[{opacity:1},{opacity:0}],{duration:130,easing:EASE.in});
      popOut(dlg,()=>{scr.remove();res(v)});
    };
    scr.querySelector('.dlg-ok').onclick=()=>close(true);
    const c=scr.querySelector('.dlg-cancel'); if(c)c.onclick=()=>close(false);
    scr.onclick=e=>{if(e.target===scr&&o.cancelText!==null)close(false)};
    scr.addEventListener('keydown',e=>{if(e.key==='Escape'&&o.cancelText!==null)close(false);if(e.key==='Enter')close(true)});
    (c||scr.querySelector('.dlg-ok')).focus();
  });
}
const osConfirm=(title,message,opts)=>osDialog({title,message,...(opts||{})});
const osAlert=(title,message)=>osDialog({title,message,cancelText:null});
/* text-input dialog replacing window.prompt — resolves the string, or null on cancel */
function osPrompt(title,o){
  o=o||{};
  return new Promise(res=>{
    const scr=document.createElement('div');scr.className='dlg-scrim';
    scr.innerHTML=`<div class="dlg" role="dialog" aria-modal="true">
      <div class="dlg-t">${esc(title||'')}</div>
      ${o.message?`<div class="dlg-m">${esc(o.message)}</div>`:''}
      <input class="dlg-in" type="${o.password?'password':'text'}" placeholder="${esc(o.placeholder||'')}">
      <div class="dlg-b">
        <button class="dlg-cancel">Cancel</button>
        <button class="dlg-ok">${esc(o.confirmText||'OK')}</button>
      </div></div>`;
    document.body.appendChild(scr);
    const dlg=scr.querySelector('.dlg'), inp=scr.querySelector('.dlg-in');
    inp.value=o.value||'';
    Motion.run(scr,[{opacity:0},{opacity:1}],{duration:140,easing:EASE.out});
    Motion.run(dlg,[{transform:'scale(.92) translateY(10px)',opacity:0},{transform:'none',opacity:1}],{duration:220,easing:EASE.spring});
    const close=v=>{Motion.run(scr,[{opacity:1},{opacity:0}],{duration:130,easing:EASE.in});popOut(dlg,()=>{scr.remove();res(v)})};
    scr.querySelector('.dlg-ok').onclick=()=>close(inp.value);
    scr.querySelector('.dlg-cancel').onclick=()=>close(null);
    scr.onclick=e=>{if(e.target===scr)close(null)};
    inp.addEventListener('keydown',e=>{if(e.key==='Enter')close(inp.value);if(e.key==='Escape')close(null)});
    inp.focus();inp.select();
  });
}

