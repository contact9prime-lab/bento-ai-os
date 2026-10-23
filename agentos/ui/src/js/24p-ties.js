/* ---------------- Teams and Zeros: every tie this machine has, in Network ----------------
   Asked for as "in network we should not only show the devices that are zero connected but also
   the teams connection", "where can I select what agents it has access to and what executors it
   can run on", and "a filtered view of KB, memory, sessions and logs for the Pi and other Zeros and
   teams". One row per tie from /api/network (ties.py): whether it answers, whose it is, which of
   this machine's agents it may ask, what its work runs on here, and its own rows read-only.
   The device map (24o) draws the same list, so the two never disagree. */
var TIES={open:'',view:'',rows:null,brains:null,agents:null,busy:{}};

function tieKey(t){return (t.owner||'')+'/'+t.label}
function tieKindWord(t){return t.kind==='zero'?'Zero':t.kind==='account'?'Account here':'Team'}
function tieState(t){
  if(t.stale)return {cls:'stale',word:'Old link',why:'A newer link to the same machine was made after this one. It is left over from a reinstall.'};
  if(t.answering===true)return {cls:'up',word:'Answering',why:''};
  if(t.answering===false)return {cls:'down',word:'Not answering',why:t.why||''};
  return {cls:'',word:'Checking…',why:''};
}
function tieFace(t,cls){
  const ag=t.agent||{};
  return ag.look&&Object.keys(ag.look).length&&typeof avatarRecipeImg==='function'?avatarRecipeImg(ag.look,cls,ag.name||'')
    :`<span class="${cls} devmap-initial">${esc((ag.name||t.peer||'?').slice(0,1).toUpperCase())}</span>`;
}

function tiesHTML(v){
  const ts=v.ties||[];
  if(!ts.length)return pRow('Teams and Zeros','',{desc:'Nothing is linked yet. Link a team above, or install Bento on a Pi.',
    f:'teams zeros links linked'});
  const live=ts.filter(t=>!t.stale),old=ts.filter(t=>t.stale);
  const mode=v.zero_updates||'ask',zs=live.filter(t=>t.kind==='zero');
  const upd=zs.length?pRow('When this hub updates',`<select data-tie="mode" aria-label="When this hub updates, its Zeros">
      <option value="ask"${mode==='ask'?' selected':''}>Ask me to update the Zeros</option>
      <option value="auto"${mode==='auto'?' selected':''}>Update the Zeros too</option>
      <option value="off"${mode==='off'?' selected':''}>Leave the Zeros alone</option></select>`,
    {desc:zs.some(t=>t.behind)?`${zs.filter(t=>t.behind).length} behind this hub. Update each one below.`:'What happens to the machines it set up.',
     more:'A Zero updates itself when its own hub asks, over their link. No password is needed.',
     f:'update zeros pi keep up to date auto update hub'}):'';
  const head=upd+pRow('Teams and Zeros',`<button class="endbtn" data-tie="probe">Check them now</button>`,
    {desc:`${live.filter(t=>t.kind==='zero').length} Zero · ${live.filter(t=>t.kind!=='zero').length} team${old.length?` · ${old.length} old`:''}`,
     more:'A Zero is a small machine set up from here: its chats, memory and work run on this computer. A team is another Bento you linked with: it keeps its own.',
     f:'teams zeros links linked executors brain runs on access agents sessions memory knowledge logs'});
  return head+`<div class="tie-list">${ts.map(tieRowHTML).join('')}</div>`;
}

function tieRowHTML(t){
  const k=tieKey(t),open=TIES.open===k,st=tieState(t);
  const ag=t.agent||{},who=t.owner?(t.owner_name||'another account'):'this machine';
  const runs=t.brain&&t.brain.executor?tieBrainWord(t.brain):'',access=(t.access||{}).theirs_may_ask||[];
  return `<div class="tie ${t.kind} ${st.cls}${open?' open':''}" data-tiekey="${esc(k)}">
    <div class="tie-top">
      <span class="tie-face">${tieFace(t,'tie-img')}<i class="tie-dot ${st.cls}" title="${esc(st.word)}"></i></span>
      <div class="tie-name"><b>${esc(ag.name||t.peer)}</b><span class="mut">${esc(t.peer)}${t.addr?' · '+esc(t.addr):''}</span></div>
      <span class="tie-kind ${t.kind}">${esc(tieKindWord(t))}</span>
      <span class="tie-st ${st.cls}" title="${esc(st.why)}">${esc(st.word)}</span>
      ${t.version?`<span class="tie-ver${t.behind?' behind':''}" title="${t.behind?'behind this hub':'the version it runs'}">${esc(t.version)}</span>`:''}
      ${t.behind&&t.mine&&t.kind==='zero'&&!t.stale?`<button class="endbtn tie-upd" data-tie="update" data-k="${esc(k)}">Update</button>`:''}
      <button class="endbtn" data-tie="open" data-k="${esc(k)}" aria-expanded="${open}">${open?'Close':'Manage'}</button>
    </div>
    <p class="tie-sub mut">Belongs to ${esc(who)}${runs?` · runs on ${esc(runs)}`:''}${t.mine&&access.length?` · may ask ${esc(access.map(tieAgentWord).join(', '))}`:''}${st.why&&!open?' · '+esc(st.why):''}</p>
    ${open?tieBodyHTML(t):''}
  </div>`;
}
function tieAgentWord(n){return n==='@agent'||n==='lead'?(typeof agentName==='function'?agentName():'your agent'):n}
function tieBrainWord(b){
  if(!b||!b.executor)return 'this machine’s brain';
  if(b.executor==='aria')return (b.model||'').split('/').slice(1).join('/')||b.model;
  const t=(typeof EXEC_TITLES!=='undefined'&&EXEC_TITLES[b.executor])||b.executor;
  return t+(b.model?' · '+b.model:'');
}

function tieBodyHTML(t){
  const k=tieKey(t);
  if(!t.mine)return `<div class="tie-body"><p class="mut">This link belongs to ${esc(t.owner_name||'another account')}. They manage it from their own Network & Teams.</p></div>`;
  const views=t.kind==='zero'?['events','sessions','schedules','memory','knowledge','logs']:['events','sessions','memory','knowledge','logs'];
  const vw=TIES.view&&TIES.view.k===k?TIES.view:null;
  return `<div class="tie-body">
    ${t.stale?`<p class="tie-warn">${esc(tieState(t).why)} Remove it so nothing tries it again.</p>`:''}
    ${t.can_adopt?`<div class="tie-own"><p>It belongs to this machine, not to you, so its chats and memory here are kept where your Chat and Profile don’t show them.</p>
      <button class="endbtn" data-tie="adopt" data-k="${esc(k)}">Make it mine</button></div>`:''}
    <div class="tie-grid">
      <div class="tie-field"><span>Its work here runs on</span>${tieBrainSelect(t)}</div>
      <div class="tie-field"><span>It may ask</span><div class="tie-agents">${tieAgentsHTML(t)}</div></div>
    </div>
    ${t.kind==='zero'&&!t.stale?`<div class="tie-field tie-screen"><span>Its screen</span>${tieScreenHTML(t)}</div>`:''}
    <div class="tie-views" role="tablist">${views.map(w=>`<button class="tie-vb${vw&&vw.what===w?' on':''}" role="tab" aria-selected="${!!(vw&&vw.what===w)}" data-tie="view" data-k="${esc(k)}" data-w="${w}">${{events:'Events',sessions:'Sessions',schedules:'Schedules',memory:'Memory',knowledge:'Knowledge',logs:'Logs'}[w]}</button>`).join('')}</div>
    ${vw?`<div class="tie-view">${tieViewHTML(vw)}</div>`:''}
    <div class="tie-acts"><button class="endbtn danger" data-tie="remove" data-k="${esc(k)}">Remove this link</button></div>
  </div>`;
}

function tieBrainSelect(t){
  const b=t.brain||{},cur=b.executor?(b.executor+'|'+(b.model||'')):'';
  const opts=[`<option value="">This machine’s brain</option>`];
  (TIES.brains||[]).filter(x=>x.available).forEach(x=>{
    const eng=x.engine==='aria'?'aria':x.id;
    if(x.engine==='aria')(x.models||[]).slice(0,30).forEach(m=>opts.push(`<option value="aria|${esc(m.id)}"${cur==='aria|'+m.id?' selected':''}>${esc(x.name.split(' —')[0]+' · '+(m.name||m.id))}</option>`));
    else{opts.push(`<option value="${esc(eng)}|"${cur===eng+'|'?' selected':''}>${esc(x.name)}</option>`);
      (x.models||[]).filter(m=>m.id).slice(0,8).forEach(m=>opts.push(`<option value="${esc(eng)}|${esc(m.id)}"${cur===eng+'|'+m.id?' selected':''}>${esc(x.name+' · '+(m.name||m.id))}</option>`))}
  });
  if(!TIES.brains)opts.push('<option disabled>loading…</option>');
  return `<select class="tie-brain" data-tie="brain" data-k="${esc(tieKey(t))}" aria-label="What its work runs on here">${opts.join('')}</select>`;
}
function tieAgentsHTML(t){
  const on=new Set(((t.access||{}).theirs_may_ask)||[]),names=['@agent',...(TIES.agents||[])];
  if(!TIES.agents)return '<span class="mut">loading…</span>';
  return names.map(n=>`<label class="tie-ag"><input type="checkbox" data-tie="ask" data-k="${esc(tieKey(t))}" value="${esc(n)}"${on.has(n)||(n==='@agent'&&on.has('lead'))?' checked':''}>${esc(tieAgentWord(n))}</label>`).join('');
}

function tieViewHTML(vw){
  if(vw.loading)return '<p class="mut">reading…</p>';
  if(vw.error)return `<p class="tie-warn">${esc(vw.error)}</p>`;
  const r=vw.rows||[],when=s=>s?new Date(s*1000).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}):'';
  if(!r.length)return `<p class="mut">${esc(vw.note||'Nothing here yet.')}</p>`;
  if(vw.what==='events')return devEventsList(r);
  if(vw.what==='sessions')return `<ul class="tie-rows">${r.map(c=>`<li><button class="tie-conv" data-tie="conv" data-cid="${esc(c.id)}"><b>${esc(c.title||'chat')}</b><span class="mut">${c.messages} messages · ${when(c.updated_at)}</span></button></li>`).join('')}</ul>`;
  if(vw.what==='schedules'){
    const every=x=>x.schedule_type==='daily'?'every day at '+x.at_time:x.schedule_type==='weekly'?'every '+['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'][x.weekday]+' at '+x.at_time
      :x.schedule_type==='interval'?'every '+Math.round((x.interval_seconds||0)/60)+' min':'once';
    return `<ul class="tie-rows">${r.map(x=>`<li class="tie-sch"><div><b>${esc(x.prompt)}</b><span class="mut">${esc(every(x))}${x.next_run?' · next '+when(x.next_run):''}${x.last_result?' · last: '+esc(String(x.last_result).replace(/\s+/g,' ').slice(0,80)):''}</span></div>
      <button class="endbtn" data-tie="unsched" data-k="${esc(vw.k)}" data-tid="${esc(x.id)}">Cancel</button></li>`).join('')}</ul>`}
  if(vw.what==='memory')return `<ul class="tie-rows">${r.map(m=>`<li>${m.pinned?'📌 ':''}${esc(m.content)}<span class="mut"> · ${esc(m.scope||'')}</span></li>`).join('')}</ul>`;
  if(vw.what==='knowledge')return `<ul class="tie-rows">${r.map(e=>`<li><b>${esc(e.subject)}</b> <span class="mut">${esc(e.relation)}</span> <b>${esc(e.object)}</b></li>`).join('')}</ul>`;
  return `<ul class="tie-rows tie-logs">${r.map(l=>`<li><span class="mut">${when(l.at)}</span> <i>${esc(l.kind)}</i> ${esc(l.text)}</li>`).join('')}</ul>`;
}

function tieFind(k){return ((NET.v||{}).ties||[]).find(t=>tieKey(t)===k)}
async function tieLists(){
  if(!TIES.brains)try{const b=await apiJSON('/api/brains');TIES.brains=b.executors||[]}catch(e){TIES.brains=[]}
  if(!TIES.agents)try{const s=await apiJSON('/api/subagents');TIES.agents=(s.subagents||s.agents||[]).map(x=>x.name).filter(Boolean)}catch(e){TIES.agents=[]}
}
/* A Zero's screen, from here: its faces read and changed over its link (/api/network/ties/…/faces),
   with the same strip and editor the screen itself has (24q-kioskfaces.js). Asked for as "can I
   change the widget on the Pi from Devices". Building a widget is the Pi's own App Studio's. */
TIES.faces={};TIES.fedit=null;
async function tieScreenLoad(t){
  const k=tieKey(t);TIES.faces[k]={loading:true};
  try{TIES.faces[k]=await apiJSON(`/api/network/ties/${encodeURIComponent(t.label)}/faces?owner=${encodeURIComponent(t.owner||'')}`)}
  catch(e){TIES.faces[k]={error:String(e.message||e)}}
  netPaint();
}
function tieScreenHTML(t){
  const st=TIES.faces[tieKey(t)];
  if(!st||st.loading)return '<span class="mut">reading its screen…</span>';
  if(st.error)return `<span class="mut">${esc(st.error)}</span>`;
  if(TIES.fedit&&TIES.fedit.k===tieKey(t))return `<div class="tie-faces" data-k="${esc(tieKey(t))}">${kfaceEditorHTML(TIES.fedit,st,{build:false})}</div>`;
  const cur=st.faces.find(f=>f.id===st.current)||{};
  return `<div class="tie-faces" data-k="${esc(tieKey(t))}"><div class="kf-faces">${st.faces.map(f=>
      `<button class="kf-pick${f.id===st.current?' on':''}" data-f="${esc(f.id)}"><span class="kf-thumb kf-t-${esc(f.layout)}"></span>${esc(f.name)}</button>`).join('')}
    <button class="kf-pick kf-new" data-new="1"><span class="kf-thumb">＋</span>New face</button></div>
    ${cur.id&&!cur.builtin?`<button class="endbtn" data-edit="1">Edit ${esc(cur.name)}</button>`:''}</div>`;
}
function tieScreenWire(box){
  box.querySelectorAll('.tie-faces').forEach(fb=>{
    const k=fb.dataset.k,t=tieFind(k),st=TIES.faces[k];if(!t||!st||st.error||st.loading)return;
    const send=async body=>{
      const r=await fetch(`/api/network/ties/${encodeURIComponent(t.label)}/faces`,{method:'PUT',headers:{'content-type':'application/json'},
        body:JSON.stringify({owner:t.owner||'',...body})}).then(x=>x.json()).catch(e=>({error:String(e)}));
      if(r.error)return toast('✗ '+r.error);
      if((r.dropped||[]).length)toast('Left out: '+r.dropped.join(', '));
      TIES.faces[k]=r;TIES.fedit=null;
      toast(`✓ ${t.peer} wears ${((r.faces||[]).find(f=>f.id===r.current)||{}).name||r.current}`);netPaint()};
    fb.querySelectorAll('[data-f]').forEach(b=>b.onclick=()=>send({use:b.dataset.f}));
    const nw=fb.querySelector('[data-new]');if(nw)nw.onclick=()=>{TIES.fedit={k,name:'',layout:'board',widgets:['clock','agent']};netPaint()};
    const ed=fb.querySelector('[data-edit]');if(ed)ed.onclick=()=>{TIES.fedit={k,...JSON.parse(JSON.stringify(st.faces.find(f=>f.id===st.current)))};netPaint()};
    const e=TIES.fedit;if(!e||e.k!==k)return;
    const nm=fb.querySelector('.kf-ename');if(nm)nm.oninput=()=>{e.name=nm.value};
    const ly=fb.querySelector('.kf-elayout');if(ly)ly.onchange=()=>{e.layout=ly.value};
    fb.querySelectorAll('.kf-ew[data-w]').forEach(b=>b.onclick=()=>{const w=b.dataset.w,i=e.widgets.indexOf(w);
      if(i>=0)e.widgets.splice(i,1);else if(e.widgets.length<(st.max_widgets||8))e.widgets.push(w);netPaint()});
    const cn=fb.querySelector('[data-cancel]');if(cn)cn.onclick=()=>{TIES.fedit=null;netPaint()};
    const dl=fb.querySelector('[data-del]');if(dl)dl.onclick=()=>send({delete:dl.dataset.del});
    const sv=fb.querySelector('[data-save]');if(sv)sv.onclick=()=>send({save:{id:e.id||'',name:e.name,layout:e.layout,widgets:e.widgets}});
  });
}
function tiesWire(box){
  tieScreenWire(box);
  box.querySelectorAll('[data-tie]').forEach(el=>{
    const act=el.dataset.tie,t=el.dataset.k?tieFind(el.dataset.k):null;
    if(act==='brain')el.onchange=()=>tieSave(t,'brain',el.value);
    else if(act==='mode')el.onchange=async()=>{const r=await fetch('/api/network/zero-updates',{method:'PUT',headers:{'content-type':'application/json'},
      body:JSON.stringify({mode:el.value})}).then(x=>x.json()).catch(e=>({error:String(e)}));
      toast(r.error?'✗ '+r.error:{ask:'✓ you’ll be asked when a Zero is behind',auto:'✓ the Zeros update when this hub does',off:'✓ the Zeros are left as they are'}[r.mode])}
    else if(act==='ask')el.onchange=()=>{const box2=el.closest('.tie-agents');
      tieSave(t,'access',[...box2.querySelectorAll('input:checked')].map(i=>i.value))};
    else el.onclick=()=>tieAct(act,t,el);
  });
}
async function tieAct(act,t,el){
  if(act==='probe'){el.disabled=true;el.textContent='Checking…';
    try{const r=await apiJSON('/api/network/ties?probe=2');NET.v.ties=r.ties}catch(e){toast(String(e.message||e))}
    return netPaint()}
  if(act==='open'){const k=tieKey(t);TIES.open=TIES.open===k?'':k;TIES.view=null;TIES.fedit=null;
    if(TIES.open){await tieLists();if(t.kind==='zero'&&!t.stale)tieScreenLoad(t)}return netPaint()}
  if(act==='view'){const k=tieKey(t),what=el.dataset.w;
    if(TIES.view&&TIES.view.k===k&&TIES.view.what===what){TIES.view=null;return netPaint()}
    TIES.view={k,what,loading:true};netPaint();
    if(what==='events'){
      try{const r=await apiJSON('/api/network/events?limit=60&who='+encodeURIComponent([t.label,t.addr].filter(Boolean).join(',')));
        TIES.view={k,what,rows:r.events,note:'Nothing has happened to it yet.'}}catch(e){TIES.view={k,what,error:String(e.message||e)}}
      return netPaint()}
    try{const r=await apiJSON(`/api/network/ties/${encodeURIComponent(t.label)}/view?what=${what}&owner=${encodeURIComponent(t.owner||'')}`);
      TIES.view={k,what,rows:r.rows,note:r.note||''}}catch(e){TIES.view={k,what,error:String(e.message||e)}}
    return netPaint()}
  if(act==='conv'){if(typeof openApp==='function')openApp('chat');
    setTimeout(()=>{if(typeof openConv==='function')openConv(el.dataset.cid)},300);return}
  if(act==='update')return tieUpdate(t.label,t.owner,el);
  if(act==='unsched'){
    const r=await fetch(`/api/network/ties/${encodeURIComponent(t.label)}/schedules/${encodeURIComponent(el.dataset.tid)}?owner=${encodeURIComponent(t.owner||'')}`,{method:'DELETE'})
      .then(x=>x.json()).catch(e=>({error:String(e)}));
    if(r.error)return toast('✗ '+r.error);
    toast('✓ cancelled');TIES.view.rows=TIES.view.rows.filter(x=>x.id!==el.dataset.tid);return netPaint()}
  if(act==='adopt'){
    const r=await fetch(`/api/network/ties/${encodeURIComponent(t.label)}/adopt`,{method:'POST'}).then(x=>x.json()).catch(e=>({error:String(e)}));
    if(r.error)return toast('✗ '+r.error);
    toast(`✓ ${t.peer} is yours now`+(r.left_behind?'. What the machine kept for it stays with the machine.':''));
    TIES.open=(r.owner||'')+'/'+t.label;return netPaint()}
  if(act==='remove'){
    // asked on the button itself, like Disconnect's form: a second tap within a few seconds
    if(!el.dataset.sure){el.dataset.sure='1';el.textContent='Tap again to remove';
      el.title='Its agents stop asking yours, and the permissions that named it go';
      setTimeout(()=>{if(el.isConnected){delete el.dataset.sure;el.textContent='Remove this link'}},4000);return}
    const r=await fetch(`/api/network/ties/${encodeURIComponent(t.label)}?owner=${encodeURIComponent(t.owner||'')}`,{method:'DELETE'}).then(x=>x.json()).catch(e=>({error:String(e)}));
    if(r.error)return toast('✗ '+r.error);
    toast('✓ link removed');TIES.open='';return netPaint()}
}
async function tieSave(t,what,val){
  if(!t)return;
  const url=`/api/network/ties/${encodeURIComponent(t.label)}/${what}`;
  let body={owner:t.owner||''};
  if(what==='brain'){const [executor,...m]=String(val||'').split('|');body={...body,executor:executor||'',model:m.join('|')}}
  else body={...body,theirs_may_ask:val};
  const r=await fetch(url,{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify(body)}).then(x=>x.json()).catch(e=>({error:String(e)}));
  if(r.error)return toast('✗ '+r.error);
  if(what==='brain'){t.brain=r.brain;toast(`✓ ${t.peer}’s work here runs on ${tieBrainWord(r.brain)}`)}
  else{t.access={...(t.access||{}),theirs_may_ask:r.theirs_may_ask||val};toast(`✓ saved who ${t.peer} may ask`)}
  netPaint();
}
/* Ask whether each tie answers, once, after the tab first paints: never on every paint. */
var TIES_PROBED=0;
function tiesProbeSoon(){
  if(Date.now()-TIES_PROBED<30000)return;TIES_PROBED=Date.now();
  apiJSON('/api/network/ties?probe=1').then(r=>{if(NET.v){NET.v.ties=r.ties;netPaint()}}).catch(()=>{});
}

/* Ask a Zero to update itself (it answers at once, works, and restarts: its screen shows it). */
async function tieUpdate(label,owner,el){
  if(el){el.disabled=true;el.textContent='Asking…'}
  const r=await fetch(`/api/network/ties/${encodeURIComponent(label)}/update`,{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({owner:owner||''})}).then(x=>x.json()).catch(e=>({error:String(e)}));
  if(r.error){toast('✗ '+r.error);if(el){el.disabled=false;el.textContent='Update'}return}
  if(r.current){toast(`✓ ${r.said||label+' is already up to date'}`);if(el){el.disabled=false;el.textContent='Update'}return}
  toast(`✓ ${label} is updating. It restarts on its own, and a Pi takes a few minutes.`);
  if(el)el.textContent='Updating…';
  setTimeout(()=>{TIES_PROBED=0;if(typeof tiesProbeSoon==='function')tiesProbeSoon()},240000);
}
