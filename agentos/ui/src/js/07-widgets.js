/* ================= desktop widgets ================= */
let WIDGETS=[];              // [{app_id,x,y,w,h}]
const widgetEls={};         // app_id -> element (kept alive so iframes never reload)
let widgetSaveT=0, widgetEchoUntil=0;
async function loadWidgets(){
  try{const r=await fetch('/api/widgets');const d=await r.json();WIDGETS=d.widgets||[]}catch(e){WIDGETS=[]}
  renderWidgets();
}
function renderWidgets(){
  const box=$('#widgets');if(!box)return;
  const apps={};(USERAPPS||[]).forEach(a=>apps[a.id]=a);
  // only widgets pinned to the CURRENT desktop are shown → each desktop is its own space
  const here=WIDGETS.filter(w=>apps[w.app_id]&&(w.desk||1)===curDesk);
  const want=new Set(here.map(w=>w.app_id));
  Object.keys(widgetEls).forEach(id=>{if(!want.has(id)){widgetEls[id].remove();delete widgetEls[id]}});
  here.forEach(wd=>{
    const a=apps[wd.app_id];
    let el=widgetEls[wd.app_id];
    if(!el){el=createWidgetEl(a);widgetEls[wd.app_id]=el;box.appendChild(el)}
    if(el._dragging||el._resizing)return;             // don't fight the user mid-gesture
    el.style.left=(wd.x??40)+'px';el.style.top=(wd.y??40)+'px';
    el.style.width=(wd.w??300)+'px';el.style.height=(wd.h??210)+'px';
  });
}
function createWidgetEl(a){
  const el=document.createElement('div');el.className='widget';el.dataset.app=a.id;
  el.innerHTML=`<div class="wgh"><span class="wgt">${esc(a.name)}</span>
    <button class="rf" title="refresh">⟳</button><button class="op" title="open in window">⤢</button><button class="x" title="unpin">✕</button></div>
    <iframe src="/api/apps/${a.id}/page" sandbox="allow-scripts allow-same-origin allow-forms"></iframe>`;
  const ifr=el.querySelector('iframe');
  el.querySelector('.rf').onclick=()=>{ifr.src='/api/apps/'+a.id+'/page?t='+Date.now()};
  el.querySelector('.op').onclick=()=>openApp('ua_'+a.id);
  el.querySelector('.x').onclick=()=>unpinWidget(a.id);
  widgetDrag(el,el.querySelector('.wgh'),a.id);
  widgetResize(el,a.id);
  return el;
}
function widgetLayout(appId){return WIDGETS.find(w=>w.app_id===appId)}
function widgetDrag(el,handle,appId){
  handle.addEventListener('pointerdown',e=>{
    if(e.target.closest('button'))return;
    e.preventDefault();
    const desk=$('#desktop'),sx=e.clientX,sy=e.clientY,ol=el.offsetLeft,ot=el.offsetTop;
    el._dragging=true;el.style.zIndex=50;
    el.querySelector('iframe').style.pointerEvents='none';   // let the drag win over the page
    handle.setPointerCapture(e.pointerId);
    const move=ev=>{
      let l=Math.max(0,Math.min(ol+ev.clientX-sx,desk.clientWidth-60));
      let t=Math.max(0,Math.min(ot+ev.clientY-sy,desk.clientHeight-40));
      l=Math.round(l/8)*8;t=Math.round(t/8)*8;
      el.style.left=l+'px';el.style.top=t+'px';
    };
    const up=()=>{
      handle.removeEventListener('pointermove',move);handle.removeEventListener('pointerup',up);
      el._dragging=false;el.style.zIndex='';el.querySelector('iframe').style.pointerEvents='';
      const wd=widgetLayout(appId);if(wd){wd.x=el.offsetLeft;wd.y=el.offsetTop;queueWidgetSave()}
    };
    handle.addEventListener('pointermove',move);handle.addEventListener('pointerup',up);
  });
}
function widgetResize(el,appId){
  // CSS `resize:both` gives the corner grip; persist the final size only, and mark busy so
  // background reloads don't clobber it mid-resize.
  let t=0;
  const ro=new ResizeObserver(()=>{
    const wd=widgetLayout(appId);if(!wd)return;
    if(Math.abs(el.offsetWidth-wd.w)<2&&Math.abs(el.offsetHeight-wd.h)<2)return;  // no real change
    el._resizing=true;wd.w=el.offsetWidth;wd.h=el.offsetHeight;
    clearTimeout(t);t=setTimeout(()=>{el._resizing=false;queueWidgetSave()},400);
  });
  ro.observe(el);
}
function queueWidgetSave(){clearTimeout(widgetSaveT);widgetSaveT=setTimeout(saveWidgets,500)}
async function saveWidgets(){
  widgetEchoUntil=Date.now()+1500;   // ignore the broadcast our own PUT triggers (prevents reload/flicker)
  try{await fetch('/api/widgets',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({widgets:WIDGETS})})}catch(e){}
}
function pinWidget(appId){
  if(WIDGETS.some(w=>w.app_id===appId&&(w.desk||1)===curDesk))return toast('already on this desktop');
  const n=WIDGETS.filter(w=>(w.desk||1)===curDesk).length;
  WIDGETS.push({app_id:appId,desk:curDesk,x:170+(n%3)*320,y:40+(n%2)*235,w:300,h:210});
  renderWidgets();saveWidgets();toast('pinned to Desktop '+curDesk);
}
function unpinWidget(appId){
  WIDGETS=WIDGETS.filter(w=>!(w.app_id===appId&&(w.desk||1)===curDesk));
  renderWidgets();saveWidgets();toast('unpinned');refreshApp('studio');
}
function arrangeWidgets(){
  const desk=$('#desktop'),cols=Math.max(1,Math.floor((desk.clientWidth-180)/320));
  WIDGETS.filter(w=>(w.desk||1)===curDesk).forEach((w,i)=>{
    w.w=300;w.h=210;w.x=170+(i%cols)*315;w.y=20+Math.floor(i/cols)*225});
  renderWidgets();saveWidgets();toast('▦ widgets arranged on Desktop '+curDesk);
}

