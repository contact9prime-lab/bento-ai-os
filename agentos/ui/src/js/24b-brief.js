/* ================= the Brief: what the missions produced, as things to act on =================
   One living page per day (agentos/brief.py): the items every mission wrote —
   needs you / decide / FYI / done for you — each with hands. Done and Later are
   one tap; a decision's choices are buttons and the answer is handed back to the
   agent as a turn; a draft can be sent through the gate, as you, so it asks.
   A mission's next run updates its items rather than adding twins, and an item
   marked done stays done.

   Faces — GUI: this window, and the home scene's line ("2 need you"). Phone: the
   same page as a stack, one item per screen, tap targets at --tap. Telegram: the
   digest with buttons (telegram.py). Voice: "Read it" speaks the headline and the
   items that need you. TUI: `bento brief`.
   `var`, not `let` (the bundle's TDZ trap) — and the home scene (01b) calls
   briefLoad() before this file has run, so the state is created by whichever
   side gets there first and never re-created: `var BRIEF={…}` here would have
   thrown inside the early call and then wiped the page it loaded. */
var BRIEF=(typeof BRIEF==='object'&&BRIEF)||{page:null,i:0,busy:false};

async function briefLoad(){
  if(!BRIEF)BRIEF={page:null,i:0,busy:false};
  try{BRIEF.page=await (await fetch('/api/brief')).json()}catch(e){BRIEF.page=null}
  return BRIEF.page;
}
function briefHeadline(){return (BRIEF.page&&BRIEF.page.headline)||''}

function briefItemHTML(it,idx){
  const src=it.source||{};
  const open=it.state==='open'||it.state==='later';
  const kindTag={needs_you:'needs you',decide:'decide',fyi:'FYI',done:'done for you'}[it.kind]||it.kind;
  const meta=[it.who?esc(it.who):'',it.due?'by '+esc(it.due):'',it.mission?'<i>'+esc(it.mission)+'</i>':''].filter(Boolean).join(' · ');
  let hands='';
  if(open&&it.kind==='decide'){
    hands=(it.options||[]).map(o=>`<button class="endbtn br-opt" onclick="briefAct('${esc(it.id)}','decide','${esc(o)}')">${esc(o)}</button>`).join('');
  }else if(open){
    hands=`<button class="endbtn" onclick="briefAct('${esc(it.id)}','done')">Done</button>
      <button class="endbtn" onclick="briefAct('${esc(it.id)}','later')">Later</button>`;
  }else{
    const who=(typeof agentName==='function')?agentName():'the agent';
    hands=`<span class="br-state">${it.state==='decided'?'decided: '+esc(it.decision||'')+(it.answer_cid?'':' · '+esc(who)+' is writing the reply…'):esc(it.state)}</span>
      <button class="endbtn" onclick="briefAct('${esc(it.id)}','reopen')">Reopen</button>`;
  }
  if(it.draft&&open)hands+=`<button class="endbtn" onclick="briefSend('${esc(it.id)}')" title="Send the draft as you — it will ask first">Send draft…</button>`;
  if(src.type==='mail'&&src.ref)hands+=`<button class="endbtn" onclick="briefOpenMail('${esc(src.ref)}')">Open mail</button>`;
  if(src.type==='report'&&src.ref)hands+=`<button class="endbtn" onclick="openApp('files')">Open report</button>`;
  if(it.answer_cid)hands+=`<button class="endbtn" onclick="openApp('chat');setTimeout(()=>openConv('${esc(it.answer_cid)}'),500)">The reply</button>`;
  return `<div class="br-item k-${esc(it.kind)} s-${esc(it.state)}" data-id="${esc(it.id)}">
    <div class="br-head"><span class="br-kind">${esc(kindTag)}</span>${idx!=null?`<span class="br-n">${idx+1}</span>`:''}</div>
    <b class="br-title">${esc(it.title)}</b>
    ${meta?`<div class="br-meta">${meta}</div>`:''}
    ${it.body?`<div class="br-body">${esc(it.body)}</div>`:''}
    ${it.draft?`<details class="br-draft"><summary>Draft</summary><pre>${esc(it.draft)}</pre></details>`:''}
    <div class="br-hands">${hands}</div>
  </div>`;
}

async function renderBrief(body){
  body.innerHTML='<div class="pad"><p class="mut">Reading…</p></div>';
  await briefLoad();
  const pg=BRIEF.page;
  if(!pg){body.innerHTML='<div class="pad"><p class="mut">Could not read the Brief.</p></div>';return}
  const day=new Date(pg.day+'T12:00:00').toLocaleDateString(undefined,{weekday:'long',day:'numeric',month:'long'});
  const phone=document.body.classList.contains('dev-mobile');
  // a decision stays in view after it is made: the reply lands where the question
  // was, not under a collapsed "handled". Only Done goes there.
  const shown=i=>i.state==='open'||i.state==='later'||i.state==='decided';
  const live=pg.items.filter(shown);
  const rest=pg.items.filter(i=>!shown(i));
  let main;
  if(!pg.items.length){
    main=`<p class="mut br-empty">Nothing yet. When a mission runs, what it finds lands here — as things to act on, not a page to read. Missions are in the dock.</p>`;
  }else if(phone){
    BRIEF.i=Math.min(BRIEF.i,Math.max(0,live.length-1));
    const it=live[BRIEF.i];
    main=it?`<div class="br-stack">${briefItemHTML(it,BRIEF.i)}
      <div class="br-nav"><button class="endbtn" onclick="briefStep(-1)" ${BRIEF.i===0?'disabled':''}>‹</button>
        <span>${BRIEF.i+1} of ${live.length}</span>
        <button class="endbtn" onclick="briefStep(1)" ${BRIEF.i>=live.length-1?'disabled':''}>›</button></div></div>`
      :`<p class="mut br-empty">Everything is handled.</p>`;
    if(rest.length)main+=`<details class="br-done"><summary>${rest.length} handled</summary>${rest.map(i=>briefItemHTML(i)).join('')}</details>`;
  }else{
    main=pg.groups.map(g=>{const its=g.items.filter(shown);if(!its.length)return '';
      return `<h3>${esc(g.label)} <span class="br-count">${its.length}</span></h3><div class="br-list">${its.map(i=>briefItemHTML(i)).join('')}</div>`}).join('');
    if(rest.length)main+=`<details class="br-done"><summary>${rest.length} handled</summary><div class="br-list">${rest.map(i=>briefItemHTML(i)).join('')}</div></details>`;
    if(!live.length)main=`<p class="mut br-empty">Everything is handled.</p>`+main;
  }
  body.innerHTML=`<div class="pad br-app">
    <div class="br-top"><div><div class="br-day">${esc(day)}</div><h2 class="br-hl">${esc(pg.headline)}</h2>
      ${pg.missions.length?`<div class="mut">from ${pg.missions.map(esc).join(', ')}</div>`:''}</div>
      <div class="br-tools"><button class="endbtn" data-ic="mic" onclick="briefSpeak()">Read it</button>
        <button class="endbtn" onclick="openApp('jobs')">Missions</button></div></div>
    ${main}</div>`;
}
function briefStep(d){BRIEF.i=Math.max(0,BRIEF.i+d);refreshApp('brief')}
function briefSpeak(){
  const t=(BRIEF.page&&BRIEF.page.spoken)||'';if(!t)return;
  if(typeof speak==='function'&&typeof VOICE!=='undefined'&&VOICE.tts){speak(t);return}
  try{const u=new SpeechSynthesisUtterance(t);speechSynthesis.cancel();speechSynthesis.speak(u)}catch(e){toast(t.slice(0,160))}
}
async function briefAct(id,action,choice){
  if(BRIEF.busy)return;BRIEF.busy=true;
  const el=document.querySelector(`.br-item[data-id="${id}"]`);if(el)el.classList.add('busy');
  try{
    const r=await fetch(`/api/brief/${encodeURIComponent(id)}/act`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,choice:choice||''})});
    const j=await r.json();
    if(j.error){toast(j.error);return}
    if(action==='decide'){toast(`→ ${choice} — ${agentName?agentName():'the agent'} is on it; the reply lands here`);}
    await briefLoad();refreshApp('brief');if(typeof homeRender==='function')homeRender();
  }catch(e){toast('could not reach the server')}
  finally{BRIEF.busy=false;if(el)el.classList.remove('busy')}
}
/* Send the draft as you: through /api/tool, which is the gate — mail_send asks
   first (an approval card), and the answer says what happened. */
async function briefSend(id){
  const it=(BRIEF.page&&BRIEF.page.items||[]).find(x=>x.id===id);if(!it||!it.draft)return;
  const to=prompt('Send to (address):',(it.source&&it.source.type==='mail'&&it.who&&/@/.test(it.who))?it.who.match(/[^\s<]+@[^\s>]+/)[0]:'');
  if(!to)return;
  const subject=prompt('Subject:','Re: '+it.title);if(subject==null)return;
  try{
    const j=await (await fetch('/api/tool',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'mail_send',args:{to,subject,body:it.draft}})})).json();
    toast(j.error||j.output||j.result||'sent');
    if(!j.error)briefAct(id,'done');
  }catch(e){toast('could not reach the server')}
}
async function briefOpenMail(uid){
  try{
    const j=await (await fetch('/api/tool',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'mail_read',args:{uid:String(uid)}})})).json();
    const text=j.output||j.result||j.error||'';
    if(typeof osAlert==='function')osAlert('Mail',text.slice(0,4000));else alert(text.slice(0,4000));
  }catch(e){toast('could not reach the server')}
}
