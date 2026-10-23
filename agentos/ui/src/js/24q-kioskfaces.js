/* ---------------- Faces for this machine's own screen (agentos/faces.py) ----------------
   Asked for from a Pi's kiosk: "different faces and widgets so I can add or build", "some cool
   widgets". A face is a layout and its widgets; the kiosk (24h-kiosk.js) wears one at a time.
   chat and office are the kiosk as it was (the column, or the band); clock, board and ambient
   draw #kiosk-face, a layer of widgets, and the Office scene stops while they show, because a
   Pi 3 drawing a canvas nobody sees is the hang this screen was made light to avoid. One timer
   ticks every widget once a second; the machine's numbers are read every 15 s, the Brief every
   minute. An app with a widget view (built in App Studio) sits in the same sandboxed frame the
   desktop's widgets use. Swipe sideways, or tap ◐, to change face. */
var KFACE={st:null,tick:0,sysT:0,briefT:0,sys:null,brief:null,timer:{ms:0,end:0,run:false},open:false,edit:null};

function kfaceCur(){const st=KFACE.st;if(!st)return {id:'chat',layout:'chat',widgets:[]};
  return st.faces.find(f=>f.id===st.current)||st.faces[0]}
function kfaceLayout(){return KIOSK.on?kfaceCur().layout:'chat'}
async function kfaceLoad(){
  try{KFACE.st=await apiJSON('/api/face/faces')}catch(e){KFACE.st=null}
  kfaceApply();
}
function kfaceApply(){
  if(!KIOSK.on)return;
  const f=kfaceCur(),L=f.layout,b=document.body;
  ['chat','office','clock','board','ambient'].forEach(x=>b.classList.toggle('kface-'+x,x===L));
  const own=L==='clock'||L==='board'||L==='ambient';
  let host=document.getElementById('kiosk-face');
  if(own){
    if(!host){host=document.createElement('div');host.id='kiosk-face';document.body.appendChild(host);kfaceSwipe(host)}
    host.className='kf-'+L;
    host.innerHTML=`<div class="kf-grid">${f.widgets.map(w=>`<section class="kf-w kf-w-${esc(w.replace(':','-'))}" data-w="${esc(w)}">${kfaceWidget(w)}</section>`).join('')}</div>`;
    kfaceWire(host);
    if(typeof officeSceneStop==='function')officeSceneStop();
  }else{
    if(host)host.remove();
    if(typeof officeSceneStart==='function'&&!(typeof OFFICE_SCENE!=='undefined'&&OFFICE_SCENE.on))officeSceneStart();
  }
  if(typeof kioskSide==='function'){KIOSK.sideW=-1;kioskSide()}
  clearInterval(KFACE.tick);
  if(own){KFACE.tick=setInterval(kfaceTick,1000);kfaceTick();kfaceData()}
  kfaceSwitcherPaint();
}
function kfaceStop(){clearInterval(KFACE.tick);const h=document.getElementById('kiosk-face');if(h)h.remove();
  ['chat','office','clock','board','ambient'].forEach(x=>document.body.classList.remove('kface-'+x))}

/* ---- widgets: the markup once, then kfaceTick fills the numbers ---- */
function kfaceWidget(w){
  if(w.startsWith('app:')){const id=w.slice(4);
    return `<iframe title="${esc(id)}" src="/api/apps/${encodeURIComponent(id)}/page?surface=widget&size=m" sandbox="allow-scripts allow-forms"></iframe>`}
  const face=typeof avatarImg==='function'?avatarImg('@agent','kf-face'):'';
  switch(w){
    case 'clock':return `<div class="kf-time"><b class="kf-hm"></b><span class="kf-s"></span></div>`;
    case 'date':return `<div class="kf-day"></div><div class="kf-date"></div>`;
    case 'agent':return `<div class="kf-agent">${face}<div><b>${esc(agentName())}</b><span class="kf-line"></span></div></div>`;
    case 'quote':return `<div class="kf-quote">${face}<p class="kf-said"></p></div>`;
    case 'machine':return `<h4>This machine</h4><div class="kf-stats">
      <div><i>CPU</i><b class="kf-cpu">…</b><span class="kf-bar"><span class="kf-cpub"></span></span></div>
      <div><i>Memory</i><b class="kf-mem">…</b><span class="kf-bar"><span class="kf-memb"></span></span></div>
      <div><i>Temp</i><b class="kf-temp">…</b></div><div><i>Up</i><b class="kf-up">…</b></div></div>`;
    case 'network':return `<h4>Network</h4><div class="kf-net"></div>`;
    case 'timer':return `<h4>Timer</h4><div class="kf-tm">0:00</div><div class="kf-tbtns">
      <button data-t="1">+1</button><button data-t="5">+5</button><button data-t="go" class="go">Start</button><button data-t="0">Reset</button></div>`;
    case 'brief':return `<h4>Your Brief</h4><div class="kf-brief">…</div>`;
  }
  return '';
}
function kfaceTick(){
  const h=document.getElementById('kiosk-face');if(!h)return;
  const d=new Date(),q=s=>h.querySelectorAll(s);
  q('.kf-hm').forEach(e=>e.textContent=d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}));
  q('.kf-s').forEach(e=>e.textContent=String(d.getSeconds()).padStart(2,'0'));
  q('.kf-day').forEach(e=>e.textContent=d.toLocaleDateString([], {weekday:'long'}));
  q('.kf-date').forEach(e=>e.textContent=d.toLocaleDateString([], {day:'numeric',month:'long',year:'numeric'}));
  const line=(KIOSK.busy?agentName()+' is working…':KIOSK.line)||(KIOSK.reply?'Last said: '+KIOSK.reply.replace(/\s+/g,' ').slice(0,90):'Here. Say my name, or type below.');
  q('.kf-line').forEach(e=>e.textContent=line);
  const said=(KIOSK.reply||[...(KIOSK.log||[])].reverse().find(x=>x.who==='agent')?.text||'').replace(/\s+/g,' ').trim();
  q('.kf-said').forEach(e=>{const t=said?'“'+said.slice(0,240)+(said.length>240?'…':'')+'”':'Nothing said here yet today.';if(e.textContent!==t)e.textContent=t});
  // the timer
  const T=KFACE.timer,left=T.run?Math.max(0,T.end-Date.now()):T.ms;
  q('.kf-tm').forEach(e=>{e.textContent=`${Math.floor(left/60000)}:${String(Math.floor(left/1000)%60).padStart(2,'0')}`;e.classList.toggle('run',T.run)});
  q('[data-t="go"]').forEach(b=>b.textContent=T.run?'Stop':'Start');
  if(T.run&&left<=0){T.run=false;T.ms=0;kfaceRing()}
  // the network, from what the kiosk already knows (kioskNet), and the hub it works through
  const n=KIOSK.net||{},wf=n.wifi||{},hub=typeof zeroFace==='function'&&zeroFace()?zeroHub():'';
  q('.kf-net').forEach(e=>{const html=`<div class="kf-nrow"><i class="kf-dot ${n.online?'up':'down'}"></i>${n.online?(wf.connection?'Wi-Fi '+esc(wf.connection)+(wf.signal?` · ${wf.signal}%`:''):(n.wired?'Wired':'Online')):'No network'}</div>`
    +(hub?`<div class="kf-nrow"><i class="kf-dot ${n.online?'up':'down'}"></i>Works on ${esc(hub)}</div>`:'');if(e.innerHTML!==html)e.innerHTML=html});
  if(Date.now()-KFACE.sysT>15000)kfaceData();
}
async function kfaceData(){
  KFACE.sysT=Date.now();
  const h=document.getElementById('kiosk-face');if(!h)return;
  if(h.querySelector('.kf-cpu'))try{const s=await apiJSON('/api/system');
    const mem=s.mem&&s.mem.total_kb?Math.round(s.mem.used_kb/s.mem.total_kb*100):0,up=Math.floor((s.uptime||0)/3600);
    h.querySelectorAll('.kf-cpu').forEach(e=>e.textContent=Math.round(s.cpu||0)+'%');
    h.querySelectorAll('.kf-cpub').forEach(e=>e.style.width=Math.min(100,s.cpu||0)+'%');
    h.querySelectorAll('.kf-mem').forEach(e=>e.textContent=mem+'%');
    h.querySelectorAll('.kf-memb').forEach(e=>e.style.width=mem+'%');
    h.querySelectorAll('.kf-temp').forEach(e=>{e.textContent=s.temp_c!=null?s.temp_c+'°C':'—';e.classList.toggle('hot',(s.temp_c||0)>=70)});
    h.querySelectorAll('.kf-up').forEach(e=>e.textContent=up>=48?Math.floor(up/24)+' days':up+' h');
  }catch(e){}
  if(h.querySelector('.kf-brief')&&Date.now()-KFACE.briefT>60000){KFACE.briefT=Date.now();
    try{const b=await apiJSON('/api/brief');h.querySelectorAll('.kf-brief').forEach(e=>e.textContent=b.headline||'Nothing needs you.')}
    catch(e){h.querySelectorAll('.kf-brief').forEach(e=>e.textContent='Not here.')}}
}
function kfaceRing(){
  kioskSay('The timer is done.','listening');
  try{const a=new (window.AudioContext||window.webkitAudioContext)();
    [0,.35,.7].forEach(t=>{const o=a.createOscillator(),g=a.createGain();o.type='square';o.frequency.value=880;
      g.gain.setValueAtTime(.12,a.currentTime+t);g.gain.exponentialRampToValueAtTime(.001,a.currentTime+t+.25);
      o.connect(g).connect(a.destination);o.start(a.currentTime+t);o.stop(a.currentTime+t+.26)});
    setTimeout(()=>a.close(),1500)}catch(e){}
}
function kfaceWire(host){
  host.querySelectorAll('[data-t]').forEach(b=>b.onclick=e=>{e.stopPropagation();const T=KFACE.timer,v=b.dataset.t;
    if(v==='go'){if(T.run){T.ms=Math.max(0,T.end-Date.now());T.run=false}else if(T.ms>0){T.end=Date.now()+T.ms;T.run=true}}
    else if(v==='0'){T.run=false;T.ms=0}
    else{if(T.run)T.end+=+v*60000;else T.ms+=+v*60000}
    kfaceTick()});
}
/* Swipe sideways to the next face; a tap is left alone (it is for the widgets). */
function kfaceSwipe(el){
  let x0=null,y0=null;
  el.addEventListener('pointerdown',e=>{x0=e.clientX;y0=e.clientY},{passive:true});
  el.addEventListener('pointerup',e=>{if(x0==null)return;const dx=e.clientX-x0,dy=e.clientY-y0;x0=null;
    if(Math.abs(dx)>80&&Math.abs(dx)>Math.abs(dy)*1.5)kfaceStep(dx<0?1:-1)},{passive:true});
}
function kfaceStep(d){const st=KFACE.st;if(!st)return;const i=st.faces.findIndex(f=>f.id===st.current);
  kfaceUse(st.faces[(i+d+st.faces.length)%st.faces.length].id)}
async function kfaceUse(id){
  if(KFACE.st)KFACE.st.current=id;kfaceApply();          // at once on this screen; saved for the next start
  try{const r=await fetch('/api/face/faces',{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify({use:id})});
    if(r.ok)KFACE.st=await r.json()}catch(e){}
}

/* ---- the switcher: ◐ in the kiosk's buttons, the faces in a strip, and ＋ to make one ---- */
function kfaceSwitcherPaint(){
  const hud=document.getElementById('kiosk-hud');if(!hud||!KFACE.st)return;
  const acts=hud.querySelector('.kh-acts');if(!acts)return;
  let b=acts.querySelector('.kh-faces');
  if(!b){b=document.createElement('button');b.className='kh-faces';b.setAttribute('aria-label','Faces');acts.prepend(b);
    b.onclick=()=>{KFACE.open=!KFACE.open;KFACE.edit=null;kfaceSwitcherPaint()}}
  b.innerHTML=`<span class="kh-fi" aria-hidden="true">◐</span><span class="kh-fn">${esc(kfaceCur().name)}</span>`;
  b.title='Face: '+kfaceCur().name;b.classList.toggle('on',KFACE.open);
  let strip=document.getElementById('kf-strip');
  if(!KFACE.open){if(strip)strip.remove();return}
  if(!strip){strip=document.createElement('div');strip.id='kf-strip';document.body.appendChild(strip)}
  strip.innerHTML=KFACE.edit?kfaceEditorHTML(KFACE.edit,KFACE.st):`<div class="kf-faces">${KFACE.st.faces.map(f=>
      `<button class="kf-pick${f.id===KFACE.st.current?' on':''}" data-f="${esc(f.id)}"><span class="kf-thumb kf-t-${esc(f.layout)}"></span>${esc(f.name)}</button>`).join('')}
    <button class="kf-pick kf-new" data-new="1"><span class="kf-thumb">＋</span>New face</button></div>
    ${KFACE.st.faces.find(f=>f.id===KFACE.st.current&&!f.builtin)?`<button class="kf-editcur" data-edit="1">Edit this face</button>`:''}`;
  kfaceEditorWire(strip,()=>{KFACE.open=false;kfaceSwitcherPaint()});
}
/* The editor, shared by the kiosk's strip and Settings → Appearance (faceFacesPaint). */
function kfaceEditorHTML(ed,st,opts){
  opts=opts||{};
  const all=[...st.widgets.map(w=>({id:w.id,name:w.name,what:w.what})),...(st.apps||[]).map(a=>({id:'app:'+a.id,name:a.name,what:'your app’s widget'}))];
  return `<div class="kf-editor"><div class="kf-erow"><input class="kf-ename" maxlength="24" value="${esc(ed.name||'')}" placeholder="Name it, like Kitchen" aria-label="Face name">
    <select class="kf-elayout" aria-label="Layout">${['board','clock','ambient','chat','office'].map(l=>`<option value="${l}"${ed.layout===l?' selected':''}>${{board:'Dashboard',clock:'Clock',ambient:'Ambient',chat:'Chat',office:'Office'}[l]}</option>`).join('')}</select></div>
    <p class="kf-ehint">Tap widgets to put them on, in the order you tap. Up to ${st.max_widgets}.</p>
    <div class="kf-ewidgets">${all.map(w=>{const i=(ed.widgets||[]).indexOf(w.id);return `<button class="kf-ew${i>=0?' on':''}" data-w="${esc(w.id)}" title="${esc(w.what)}">${i>=0?`<i>${i+1}</i>`:''}${esc(w.name)}</button>`}).join('')}
      ${opts.build===false?'':'<button class="kf-ew kf-build" data-build="1">＋ Build a widget</button>'}</div>
    <div class="kf-eacts">${ed.id&&!ed.builtin?`<button class="kf-del" data-del="${esc(ed.id)}">Remove face</button>`:''}<span style="flex:1"></span>
      <button data-cancel="1">Cancel</button><button class="go" data-save="1">Save and wear it</button></div></div>`;
}
function kfaceEditorWire(box,done){
  box.querySelectorAll('[data-f]').forEach(b=>b.onclick=()=>{kfaceUse(b.dataset.f);done&&done()});
  const nw=box.querySelector('[data-new]');if(nw)nw.onclick=()=>{KFACE.edit={name:'',layout:'board',widgets:['clock','agent']};kfaceRepaintEditor(box,done)};
  const ec=box.querySelector('[data-edit]');if(ec)ec.onclick=()=>{KFACE.edit=JSON.parse(JSON.stringify(kfaceCur()));kfaceRepaintEditor(box,done)};
  const ed=KFACE.edit;if(!ed)return;
  const nm=box.querySelector('.kf-ename');if(nm)nm.oninput=()=>{ed.name=nm.value};
  const ly=box.querySelector('.kf-elayout');if(ly)ly.onchange=()=>{ed.layout=ly.value};
  box.querySelectorAll('.kf-ew[data-w]').forEach(b=>b.onclick=()=>{const w=b.dataset.w,i=ed.widgets.indexOf(w);
    if(i>=0)ed.widgets.splice(i,1);else if(ed.widgets.length<KFACE.st.max_widgets)ed.widgets.push(w);kfaceRepaintEditor(box,done)});
  const bw=box.querySelector('[data-build]');
  if(bw)bw.onclick=()=>{
    // a widget is an app with a widget view: App Studio builds it, then it is on this list
    if(typeof kioskLeave==='function'&&KIOSK.on)kioskLeave();
    if(typeof openApp==='function')openApp('studio');
    setTimeout(()=>{const i=document.querySelector('#studio-prompt,.studio textarea,textarea');
      if(i){i.value='A widget for my Pi’s screen that shows ';i.focus()}},800)};
  const cn=box.querySelector('[data-cancel]');if(cn)cn.onclick=()=>{KFACE.edit=null;kfaceRepaintEditor(box,done)};
  const dl=box.querySelector('[data-del]');if(dl)dl.onclick=async()=>{await fetch('/api/face/faces',{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify({delete:dl.dataset.del})});
    KFACE.edit=null;await kfaceLoad();kfaceRepaintEditor(box,done)};
  const sv=box.querySelector('[data-save]');if(sv)sv.onclick=async()=>{
    const r=await fetch('/api/face/faces',{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify({save:{id:ed.id||'',name:ed.name,layout:ed.layout,widgets:ed.widgets}})})
      .then(x=>x.json()).catch(e=>({error:String(e)}));
    if(r.error)return toast('✗ '+r.error);
    if((r.dropped||[]).length)toast('Left out: '+r.dropped.join(', '));
    KFACE.st=r;KFACE.edit=null;kfaceApply();done&&done();if(typeof faceFacesPaint==='function')faceFacesPaint()};
}
function kfaceRepaintEditor(box,done){
  if(box.id==='kf-strip')return kfaceSwitcherPaint();
  if(typeof faceFacesPaint==='function')faceFacesPaint();
}
/* Settings → Appearance → On this screen → Faces: the same list and editor, from any browser
   an admin can reach this machine with (a Pi's kiosk has no keyboard to spare). */
async function faceFacesPaint(){
  const box=document.getElementById('s-faces');if(!box)return;
  if(!KFACE.st)try{KFACE.st=await apiJSON('/api/face/faces')}catch(e){box.innerHTML=`<span class="mut">${esc(String(e.message||e))}</span>`;return}
  box.innerHTML=KFACE.edit?kfaceEditorHTML(KFACE.edit,KFACE.st):`<div class="kf-faces">${KFACE.st.faces.map(f=>
      `<button class="kf-pick${f.id===KFACE.st.current?' on':''}" data-f="${esc(f.id)}"><span class="kf-thumb kf-t-${esc(f.layout)}"></span>${esc(f.name)}</button>`).join('')}
    <button class="kf-pick kf-new" data-new="1"><span class="kf-thumb">＋</span>New face</button></div>
    ${KFACE.st.faces.find(f=>f.id===KFACE.st.current&&!f.builtin)?`<button class="endbtn" data-edit="1">Edit this face</button>`:''}`;
  kfaceEditorWire(box,()=>faceFacesPaint());
}
