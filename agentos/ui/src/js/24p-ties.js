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
  if(!ts.length)return pRow('Teams and Zeros','',{desc:'Nothing is linked yet. Link a team in Team & Communications, or install Bento on a Pi below.',
    f:'teams zeros links linked'});
  const live=ts.filter(t=>!t.stale),old=ts.filter(t=>t.stale);
  const head=pRow('Teams and Zeros',`<button class="endbtn" data-tie="probe">Check them now</button>`,
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
  if(!t.mine)return `<div class="tie-body"><p class="mut">This link belongs to ${esc(t.owner_name||'another account')}. They manage it from their own Team & Communications.</p></div>`;
  const views=['sessions','memory','knowledge','logs'];
  const vw=TIES.view&&TIES.view.k===k?TIES.view:null;
  return `<div class="tie-body">
    ${t.stale?`<p class="tie-warn">${esc(tieState(t).why)} Remove it so nothing tries it again.</p>`:''}
    ${t.can_adopt?`<div class="tie-own"><p>It belongs to this machine, not to you, so its chats and memory here are kept where your Chat and Profile don’t show them.</p>
      <button class="endbtn" data-tie="adopt" data-k="${esc(k)}">Make it mine</button></div>`:''}
    <div class="tie-grid">
      <div class="tie-field"><span>Its work here runs on</span>${tieBrainSelect(t)}</div>
      <div class="tie-field"><span>It may ask</span><div class="tie-agents">${tieAgentsHTML(t)}</div></div>
    </div>
    <div class="tie-views" role="tablist">${views.map(w=>`<button class="tie-vb${vw&&vw.what===w?' on':''}" role="tab" aria-selected="${!!(vw&&vw.what===w)}" data-tie="view" data-k="${esc(k)}" data-w="${w}">${{sessions:'Sessions',memory:'Memory',knowledge:'Knowledge',logs:'Logs'}[w]}</button>`).join('')}</div>
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
  if(vw.what==='sessions')return `<ul class="tie-rows">${r.map(c=>`<li><button class="tie-conv" data-tie="conv" data-cid="${esc(c.id)}"><b>${esc(c.title||'chat')}</b><span class="mut">${c.messages} messages · ${when(c.updated_at)}</span></button></li>`).join('')}</ul>`;
  if(vw.what==='memory')return `<ul class="tie-rows">${r.map(m=>`<li>${m.pinned?'📌 ':''}${esc(m.content)}<span class="mut"> · ${esc(m.scope||'')}</span></li>`).join('')}</ul>`;
  if(vw.what==='knowledge')return `<ul class="tie-rows">${r.map(e=>`<li><b>${esc(e.subject)}</b> <span class="mut">${esc(e.relation)}</span> <b>${esc(e.object)}</b></li>`).join('')}</ul>`;
  return `<ul class="tie-rows tie-logs">${r.map(l=>`<li><span class="mut">${when(l.at)}</span> <i>${esc(l.kind)}</i> ${esc(l.text)}</li>`).join('')}</ul>`;
}

function tieFind(k){return ((NET.v||{}).ties||[]).find(t=>tieKey(t)===k)}
async function tieLists(){
  if(!TIES.brains)try{const b=await apiJSON('/api/brains');TIES.brains=b.executors||[]}catch(e){TIES.brains=[]}
  if(!TIES.agents)try{const s=await apiJSON('/api/subagents');TIES.agents=(s.subagents||s.agents||[]).map(x=>x.name).filter(Boolean)}catch(e){TIES.agents=[]}
}
function tiesWire(box){
  box.querySelectorAll('[data-tie]').forEach(el=>{
    const act=el.dataset.tie,t=el.dataset.k?tieFind(el.dataset.k):null;
    if(act==='brain')el.onchange=()=>tieSave(t,'brain',el.value);
    else if(act==='ask')el.onchange=()=>{const box2=el.closest('.tie-agents');
      tieSave(t,'access',[...box2.querySelectorAll('input:checked')].map(i=>i.value))};
    else el.onclick=()=>tieAct(act,t,el);
  });
}
async function tieAct(act,t,el){
  if(act==='probe'){el.disabled=true;el.textContent='Checking…';
    try{const r=await apiJSON('/api/network/ties?probe=2');NET.v.ties=r.ties}catch(e){toast(String(e.message||e))}
    return netPaint()}
  if(act==='open'){const k=tieKey(t);TIES.open=TIES.open===k?'':k;TIES.view=null;
    if(TIES.open){await tieLists()}return netPaint()}
  if(act==='view'){const k=tieKey(t),what=el.dataset.w;
    if(TIES.view&&TIES.view.k===k&&TIES.view.what===what){TIES.view=null;return netPaint()}
    TIES.view={k,what,loading:true};netPaint();
    try{const r=await apiJSON(`/api/network/ties/${encodeURIComponent(t.label)}/view?what=${what}&owner=${encodeURIComponent(t.owner||'')}`);
      TIES.view={k,what,rows:r.rows,note:r.note||''}}catch(e){TIES.view={k,what,error:String(e.message||e)}}
    return netPaint()}
  if(act==='conv'){if(typeof openApp==='function')openApp('chat');
    setTimeout(()=>{if(typeof openConv==='function')openConv(el.dataset.cid)},300);return}
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
