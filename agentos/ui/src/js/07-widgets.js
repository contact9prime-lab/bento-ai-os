/* ================= desktop widgets =================
   Every app has two surfaces: the desktop window (the whole application) and a
   widget (the one glanceable fact). The widget's size is a property of the APP —
   chosen while editing it — not of wherever it happens to be pinned, so the same
   app looks the same on every desktop and after a re-pin. */
const WIDGET_SIZES={s:{w:260,h:170,label:'Small'},m:{w:340,h:240,label:'Medium'},l:{w:460,h:340,label:'Large'}};
function widgetSizeOf(appId){
  const a=(USERAPPS||[]).find(x=>x.id===appId);
  return WIDGET_SIZES[(a&&a.widget_size)||'m']||WIDGET_SIZES.m;
}
async function setWidgetSize(appId,size){
  const a=(USERAPPS||[]).find(x=>x.id===appId);if(a)a.widget_size=size;
  try{await fetch('/api/apps/'+appId,{method:'PUT',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({widget_size:size})})}catch(e){}
  const d=WIDGET_SIZES[size]||WIDGET_SIZES.m;
  WIDGETS.filter(w=>w.app_id===appId).forEach(w=>{w.w=d.w;w.h=d.h});
  // the iframe is told its size in the URL, so it must re-mount to re-render
  if(widgetEls[appId]){widgetEls[appId].remove();delete widgetEls[appId]}
  renderWidgets();saveWidgets();
  if(typeof refreshApp==='function')refreshApp('studio');
  toast('widget size → '+d.label);
}
let WIDGETS=[];              // [{app_id,x,y,w,h}]
const widgetEls={};         // app_id -> element (kept alive so iframes never reload)
let widgetSaveT=0, widgetEchoUntil=0;
async function loadWidgets(){
  try{const r=await fetch('/api/widgets');const d=await r.json();WIDGETS=d.widgets||[]}catch(e){WIDGETS=[]}
  renderWidgets();
}
/* A widget can live in four places: free on the desktop (default), as a card in
   the deck, in the strip beside the prompt bar, or shrunk into the menu bar. */
const WIDGET_PLACES=[['','Desktop'],['deck','App deck'],['bar','Beside the prompt bar'],['menubar','Menu bar']];
function setWidgetPlace(appId,place){
  let wd=WIDGETS.find(w=>w.app_id===appId);
  if(!wd){wd={app_id:appId,desk:curDesk,x:200,y:60,w:300,h:210};WIDGETS.push(wd)}
  wd.place=place||'';
  if(!place){wd.desk=curDesk}
  // the element is rebuilt in its new home; drop the cached one so it re-mounts
  if(widgetEls[appId]){widgetEls[appId].remove();delete widgetEls[appId]}
  renderWidgets();saveWidgets();
  toast('widget → '+((WIDGET_PLACES.find(p=>p[0]===(place||''))||[])[1]||'desktop'));
}
function renderPlacedWidgets(){
  const apps={};(USERAPPS||[]).forEach(a=>apps[a.id]=a);
  // beside the bar: compact live cards
  const bar=$('#barwidgets');
  if(bar){
    const list=WIDGETS.filter(w=>w.place==='bar'&&apps[w.app_id]);
    bar.classList.toggle('on',list.length>0);
    bar.innerHTML=list.map(w=>`<div class="barwidget"><div class="bw-h">${esc(apps[w.app_id].name)}
        <button onclick="setWidgetPlace('${esc(w.app_id)}','')" title="Unpin">✕</button></div>
      <iframe src="/api/apps/${esc(w.app_id)}/page?surface=widget&size=${esc((apps[w.app_id].widget_size)||'m')}" sandbox="allow-scripts allow-forms"></iframe></div>`).join('');
  }
  // menu bar: a thin always-visible readout
  const mb=$('#mbwidgets');
  if(mb){
    const list=WIDGETS.filter(w=>w.place==='menubar'&&apps[w.app_id]);
    mb.innerHTML=list.map(w=>`<iframe class="mbwidget" title="${esc(apps[w.app_id].name)}"
      src="/api/apps/${esc(w.app_id)}/page?surface=widget&size=s" sandbox="allow-scripts allow-forms"></iframe>`).join('');
  }
  if(typeof buildDeck==='function'&&$('#deck'))buildDeck();
}
function renderWidgets(){
  const box=$('#widgets');if(!box)return;
  const apps={};(USERAPPS||[]).forEach(a=>apps[a.id]=a);
  renderPlacedWidgets();
  // only free desktop widgets pinned to the CURRENT desktop are shown here
  const here=WIDGETS.filter(w=>apps[w.app_id]&&!w.place&&(w.desk||1)===curDesk);
  const want=new Set(here.map(w=>w.app_id));
  Object.keys(widgetEls).forEach(id=>{if(!want.has(id)){widgetEls[id].remove();delete widgetEls[id]}});
  here.forEach(wd=>{
    const a=apps[wd.app_id];
    let el=widgetEls[wd.app_id];
    if(!el){el=createWidgetEl(a);widgetEls[wd.app_id]=el;box.appendChild(el)}
    if(el._dragging||el._resizing)return;             // don't fight the user mid-gesture
    const dim=widgetSizeOf(wd.app_id);
    el.style.left=(wd.x??40)+'px';el.style.top=(wd.y??40)+'px';
    el.style.width=(wd.w??dim.w)+'px';el.style.height=(wd.h??dim.h)+'px';
  });
}
function createWidgetEl(a){
  const el=document.createElement('div');el.className='widget';el.dataset.app=a.id;
  el.innerHTML=`<div class="wgh"><span class="wgt">${esc(a.name)}</span>
    <button class="rf" title="refresh">⟳</button><button class="op" title="open in window">⤢</button><button class="x" title="unpin">✕</button></div>
    <iframe src="/api/apps/${a.id}/page?surface=widget&size=${esc(a.widget_size||'m')}" sandbox="allow-scripts allow-forms"></iframe>`;
  const ifr=el.querySelector('iframe');
  el.querySelector('.rf').onclick=()=>{ifr.src='/api/apps/'+a.id+'/page?surface=widget&size='+(a.widget_size||'m')+'&t='+Date.now()};
  el.querySelector('.op').onclick=()=>openApp('ua_'+a.id);
  el.querySelector('.x').onclick=()=>unpinWidget(a.id);
  el.querySelector('.wgh').oncontextmenu=e=>{e.preventDefault();
    showCtxItems(e,Object.entries(WIDGET_SIZES).map(([k,d])=>({label:d.label+' widget',fn:()=>setWidgetSize(a.id,k)}))
      .concat([null],WIDGET_PLACES.map(([p,label])=>({label:'Move to '+label,fn:()=>setWidgetPlace(a.id,p)})))
      .concat([null,{label:'Unpin',danger:true,fn:()=>unpinWidget(a.id)}]))};
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
  const n=WIDGETS.filter(w=>(w.desk||1)===curDesk).length,dim=widgetSizeOf(appId);
  WIDGETS.push({app_id:appId,desk:curDesk,x:170+(n%3)*320,y:40+(n%2)*235,w:dim.w,h:dim.h});
  renderWidgets();saveWidgets();toast('pinned to Desktop '+curDesk);
}
function unpinWidget(appId){
  WIDGETS=WIDGETS.filter(w=>!(w.app_id===appId&&(w.place||(w.desk||1)===curDesk)));
  renderWidgets();saveWidgets();toast('unpinned');refreshApp('studio');
}
function arrangeWidgets(){
  const desk=$('#desktop'),cols=Math.max(1,Math.floor((desk.clientWidth-180)/320));
  WIDGETS.filter(w=>(w.desk||1)===curDesk).forEach((w,i)=>{
    const dim=widgetSizeOf(w.app_id);
    w.w=dim.w;w.h=dim.h;w.x=170+(i%cols)*315;w.y=20+Math.floor(i/cols)*225});
  renderWidgets();saveWidgets();toast('▦ widgets arranged on Desktop '+curDesk);
}

