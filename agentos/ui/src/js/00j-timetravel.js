/* ---------------- Time travel: a scrubber over what the agent changed ----------------
   agentos/timetravel.py keeps a checkpoint before every step that changes a file, the
   memory, the graph or a skill (and marks the shell steps it cannot see). This window is
   the scrubber: a track of those checkpoints for one conversation, a slider along it,
   and for the step under the slider exactly what going back would undo (/plan, the same
   computation /rewind performs). Rewind goes back to just before that step: files put
   back, new files set aside (never deleted), memory and graph restored, and the desktop's
   windows put back as they were at that moment. Fork starts a new conversation from that
   step on another brain.

   The window layouts are this page's: each `checkpoint` event saves the open windows
   under the checkpoint's id (this browser's session only), and a rewind restores them.
   A checkpoint taken while this page was closed has no layout, and the window says so.
   Faces: GUI and SUI are this window. TUI: `bento timetravel list|plan|rewind`; a
   terminal has no windows to put back, and a fork starts a turn, which is the server's. */
var TT={data:null,conv:'',sel:-1,plan:null,brains:[],w:null,planT:0};
var TT_LAYOUTS_KEY='tt.layouts',TT_LAYOUTS_MAX=80;

function ttLayouts(){try{return JSON.parse(sessionStorage.getItem(TT_LAYOUTS_KEY)||'{}')}catch(e){return {}}}
function ttLayoutSave(id){
  try{
    const wins=[...WM.wins.values()].filter(w=>w.id!=='timetravel').map(w=>{
      const r=w.el.getBoundingClientRect();
      return {id:w.id,desk:w.desk||1,max:!!w.max,min:!!w.min,l:Math.round(r.left),t:Math.round(r.top),w:Math.round(r.width),h:Math.round(r.height)};
    });
    const all=ttLayouts();all[id]={at:Date.now(),desk:curDesk,wins};
    const keys=Object.keys(all).sort((a,b)=>all[a].at-all[b].at);
    while(keys.length>TT_LAYOUTS_MAX)delete all[keys.shift()];
    sessionStorage.setItem(TT_LAYOUTS_KEY,JSON.stringify(all));
  }catch(e){}
}
/* The windows as they were at a checkpoint: close what was not open, open what was,
   and put each back where it stood. The scrubber's own window stays. */
function ttLayoutRestore(id){
  const lay=ttLayouts()[id];if(!lay)return false;
  const want=new Set(lay.wins.map(x=>x.id));
  [...WM.wins.values()].forEach(w=>{if(w.id!=='timetravel'&&!want.has(w.id))closeWin(w)});
  lay.wins.forEach(x=>{
    if(!APPS[x.id])return;
    const w=WM.wins.get(x.id)||openApp(x.id);if(!w)return;
    if(x.max&&!w.max)toggleMax(w);
    if(!x.max){if(w.max)toggleMax(w);Object.assign(w.el.style,{left:x.l+'px',top:x.t+'px',width:x.w+'px',height:x.h+'px'})}
    if(x.min&&!w.min)minimizeWin(w);
    w.desk=x.desk;
  });
  if(typeof switchDesk==='function'&&lay.desk&&lay.desk!==curDesk)switchDesk(lay.desk);
  return true;
}

function renderTimeTravel(body,w){
  TT.w=w;
  // a bar along the bottom of the desktop, the width of the screen
  // (above the dock, which floats over the bottom of the screen)
  // (after the window manager has placed it, which happens once render returns)
  if(innerWidth>700&&!w.max&&!w.ttPlaced){w.ttPlaced=true;setTimeout(()=>{
    const dk=document.querySelector('#dock'),r=dk&&dk.getBoundingClientRect();
    const bottom=r&&r.height?r.top-10:innerHeight-10,h=Math.min(410,bottom-60);
    Object.assign(w.el.style,{left:'8px',width:(innerWidth-16)+'px',height:h+'px',top:Math.max(40,bottom-h)+'px'})},60)}
  const pb=panelShell(body,{title:'Time travel',sub:'',actions:`<select id="tt-conv" aria-label="Which conversation"></select>`});
  pb.innerHTML='<div class="mut" style="padding:14px">reading the checkpoints…</div>';
  Promise.all([apiJSON('/api/timetravel'+(TT.conv?'?conversation_id='+encodeURIComponent(TT.conv):'')),
               apiJSON('/api/arena').catch(()=>({choices:[]}))]).then(([d,a])=>{
    TT.brains=a.choices||[];
    if(!TT.conv&&d.conversations.length){TT.conv=d.conversations[0].id;return renderTimeTravel(body,w)}
    TT.data=d;TT.sel=d.points.length-1;ttPaint(body);
  }).catch(e=>{pb.innerHTML=emptyBox('Could not read the timeline',esc(e.message))});
}
function ttPaint(body){
  body=body||(TT.w&&TT.w.el.querySelector('.wbody'));if(!body)return;
  const d=TT.data||{points:[],conversations:[]},pb=body.querySelector('.pbody'),sel=body.querySelector('#tt-conv');
  sel.innerHTML=d.conversations.map(c=>`<option value="${esc(c.id)}"${c.id===TT.conv?' selected':''}>${esc(c.title)} · ${c.points}</option>`).join('')
    ||'<option>no conversations yet</option>';
  sel.onchange=()=>{TT.conv=sel.value;renderTimeTravel(body,TT.w)};
  const pts=d.points;
  if(!pts.length){pb.innerHTML=emptyBox('Nothing to go back to yet',
    'A checkpoint is kept before every step where an agent changes a file, its memory or the graph. Ask it to do something and come back.');return}
  const kind=p=>p.unseen?'shell':p.files&&p.files.length?'file':'mem';
  pb.innerHTML=`<div class="tt-wrap" style="--n:${pts.length}">
    <div class="tt-track" style="--n:${pts.length}">
      ${pts.map((p,i)=>`<button class="tt-tick ${kind(p)}${p.state!=='live'?' gone':''}${i===TT.sel?' on':''}" data-i="${i}"
         title="${esc(p.tool+' · '+p.detail)}" aria-label="${esc('Step '+(i+1)+': '+p.tool)}"></button>`).join('')}
    </div>
    <input type="range" id="tt-slide" min="0" max="${pts.length-1}" value="${Math.max(0,TT.sel)}" aria-label="Scrub through the steps">
    <div class="tt-legend mut"><span class="tt-dot file"></span>a file <span class="tt-dot mem"></span>memory or graph <span class="tt-dot shell"></span>shell, cannot be undone</div>
    <div class="tt-detail" id="tt-detail"></div>
  </div>`;
  pb.querySelectorAll('.tt-tick').forEach(b=>b.onclick=()=>ttSelect(+b.dataset.i));
  pb.querySelector('#tt-slide').oninput=e=>ttSelect(+e.target.value);
  ttSelect(TT.sel);
}
function ttSelect(i){
  const pts=(TT.data||{}).points||[];if(!pts[i])return;
  TT.sel=i;
  const pb=TT.w&&TT.w.el.querySelector('.pbody');if(!pb)return;
  pb.querySelectorAll('.tt-tick').forEach((b,k)=>b.classList.toggle('on',k===i));
  const s=pb.querySelector('#tt-slide');if(s&&+s.value!==i)s.value=i;
  const p=pts[i],det=pb.querySelector('#tt-detail');
  det.innerHTML=`<div class="tt-head"><b>Step ${i+1} of ${pts.length}</b> <span class="mut">${esc(new Date(p.ts*1000).toLocaleTimeString())}</span>
      <code>${esc(p.tool)}</code> <span class="tt-what">${esc(p.detail)}</span>${p.state!=='live'?' <span class="mut">(already rewound)</span>':''}</div>
    <div class="tt-plan mut">reading what going back would undo…</div>`;
  clearTimeout(TT.planT);
  TT.planT=setTimeout(()=>apiJSON('/api/timetravel/'+encodeURIComponent(p.id)+'/plan').then(pl=>{
    if(TT.sel!==i)return;TT.plan=pl;ttDetail(det,p,pl);
  }).catch(e=>{det.querySelector('.tt-plan').textContent=e.message}),180);
}
function ttDetail(det,p,pl){
  const busy=((TT.data||{}).busy||[]).indexOf(p.conversation_id)>=0;
  const lay=!!ttLayouts()[p.id];
  const opts=TT.brains.map(c=>`<option value="${esc(c.kind==='provider'?c.model:c.executor)}">${esc(c.label)}</option>`).join('');
  det.querySelector('.tt-plan').outerHTML=`<div class="tt-plan">
    <div>Going back to just before this step would <b>${esc(pl.words.join(', '))}</b>, across ${pl.steps} step${pl.steps===1?'':'s'}.</div>
    ${pl.restore.length?`<div class="mut tt-files">put back: ${pl.restore.map(f=>esc(f.split('/').slice(-2).join('/'))).join(', ')}</div>`:''}
    ${pl.remove.length?`<div class="mut tt-files">set aside: ${pl.remove.map(f=>esc(f.split('/').slice(-2).join('/'))).join(', ')}</div>`:''}
    ${pl.warning?`<div class="tt-warn">${esc(pl.warning)}</div>`:''}
    <div class="mut">${lay?'The windows go back to how they were at that moment.':'This page has no window layout for that moment, so the windows stay as they are.'}</div>
  </div>
  <div class="tt-actions">
    <button class="endbtn danger" id="tt-rewind"${busy||p.state!=='live'?' disabled':''}>Rewind to before this step</button>
    ${busy?'<span class="mut">That conversation is still working. Stop it first.</span>':''}
    <span class="sp"></span>
    <label class="tt-fork">Fork from here on <select id="tt-brain">${opts}</select></label>
    <button class="endbtn" id="tt-forkgo"${p.conversation_id?'':' disabled'}>Fork</button>
  </div>`;
  const q=s=>det.querySelector(s);
  if(q('#tt-rewind'))q('#tt-rewind').onclick=()=>ttRewind(p,pl);
  if(q('#tt-forkgo'))q('#tt-forkgo').onclick=()=>ttFork(p,q('#tt-brain').value);
}
async function ttRewind(p,pl){
  const ok=typeof osConfirm==='function'?await osConfirm('Rewind to before this step?',
    'This will '+pl.words.join(', ')+'. What it replaces is moved aside, not deleted.'+(pl.warning?' '+pl.warning+'.':''),
    {confirmText:'Rewind'}):confirm('Rewind?');
  if(!ok)return;
  try{
    const got=await apiJSON('/api/timetravel/'+encodeURIComponent(p.id)+'/rewind',{method:'POST'});
    const moved=ttLayoutRestore(p.id);
    toast('Rewound: '+got.words.join(', ')+(moved?'. Windows put back.':'.'),{kind:'ok'});
    renderTimeTravel(TT.w.el.querySelector('.wbody'),TT.w);
  }catch(e){toast(e.message,{kind:'err'})}
}
async function ttFork(p,model){
  try{
    const got=await apiJSON('/api/timetravel/'+encodeURIComponent(p.id)+'/fork',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({model})});
    toast('Forked: the same question on '+(got.model||'the default brain')+', from that step.',{kind:'ok'});
    openApp('chat');setTimeout(()=>openConv(got.conversation_id),250);
  }catch(e){toast(e.message,{kind:'err'})}
}
