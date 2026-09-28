/* ================= Free talk, and every time agents talked =================
   Free talk is the person letting the team talk among themselves for a few minutes
   (fabric.run_free_talk). It is the one time agents talk with nobody asking them
   anything, so it is started only here, by a person, after a caution they tick, and it
   ends on the first of its clock, its message count, a quiet room or Stop. Nothing
   about it is hidden: every message lands in its own Chat thread as it is said, each is
   a run, the session is a run the Run Inspector replays, and the start and end are in
   the ledger.

   The log below it is the one place that lists every time agents talked to each other
   (free talks, huddles, one agent asking another), read from the runs they already are
   (fabric.talk_log, `bento team log`).

   Faces — GUI and SUI: Settings → Agents → Working together, and the Chat thread.
   TUI: `bento team freetalk` starts and stops one, `bento team log` lists them.
   `var`/function declarations only: the bundle is one script. */
var FREETALK={talks:[],opts:null,log:null,understood:false,mode:'talk',minutes:5,messages:20,topic:'',agents:null};

function ftActive(){return (FREETALK.talks||[]).find(t=>t.status==='running')}
function ftLeft(t){const s=Math.max(0,Math.round(t.until-Date.now()/1000));return Math.floor(s/60)+':'+String(s%60).padStart(2,'0')}
function ftAgo(t){const s=Math.round(Date.now()/1000-t);
  return s<45?'just now':s<3600?Math.round(s/60)+' min ago':s<86400?Math.round(s/3600)+' h ago':new Date(t*1000).toLocaleDateString()}

async function freeTalkLoad(){
  try{const d=await apiJSON('/api/team/freetalk');FREETALK.talks=d.talks||[];FREETALK.opts=d}
  catch(e){FREETALK.opts={error:e.message}}
}
async function freeTalkPaint(){
  const box=document.getElementById('s-team-freetalk');if(!box)return;
  if(!FREETALK.opts)await freeTalkLoad();
  const o=FREETALK.opts||{};
  if(o.error){box.innerHTML=`<p class="mut">${esc(o.error)}</p>`;return}
  box.classList.remove('mut');
  const run=ftActive();
  if(run){
    box.innerHTML=`<div class="ft-live"><div class="ft-faces">${run.agents.map(n=>avatarImg(n,'av-tool')).join('')}</div>
      <div class="ft-now"><b>Your team is talking</b><span class="mut">${run.messages} of ${run.max_messages} messages · <span class="ft-clock">${ftLeft(run)}</span> left${run.topic?' · '+esc(run.topic):''}</span></div>
      <div class="ft-acts"><button class="endbtn" onclick="freeTalkOpen('${esc(run.conversation_id)}')">Watch in Chat</button>
      <button class="endbtn danger" onclick="freeTalkStop('${esc(run.id)}')">Stop</button></div></div>`;
    ftTick();
    return;
  }
  if(o.talk==='off'){box.innerHTML=`<p class="mut">Agents messaging each other is off. Turn it on above to let them talk.</p>`;return}
  const names=o.agents||[];
  if(names.length<2){box.innerHTML=`<p class="mut">You need two or more agents first. Create one under Agents above.</p>`;return}
  if(!FREETALK.agents)FREETALK.agents=names.slice(0,o.max_agents||6);
  const opt=(arr,cur,unit)=>arr.map(v=>`<option value="${v}" ${+cur===v?'selected':''}>${v} ${unit}</option>`).join('');
  box.innerHTML=`<div class="ft-form">
    <div class="ft-who">${names.map(n=>`<label class="ft-agent${FREETALK.agents.includes(n)?' on':''}">
      <input type="checkbox" ${FREETALK.agents.includes(n)?'checked':''} onchange="freeTalkPick('${esc(n)}',this.checked)">${avatarImg(n,'av-tool')}${esc(n)}</label>`).join('')}</div>
    <input id="ft-topic" type="text" maxlength="500" placeholder="What about? Leave empty to let them choose" value="${esc(FREETALK.topic)}" oninput="FREETALK.topic=this.value">
    <div class="ft-limits">
      <label>For up to <select id="ft-min" onchange="FREETALK.minutes=+this.value">${opt(o.minutes||[5,10,20],FREETALK.minutes,'min')}</select></label>
      <label>or <select id="ft-msg" onchange="FREETALK.messages=+this.value">${opt(o.messages||[10,20,40],FREETALK.messages,'messages')}</select></label>
      <label><select id="ft-mode" onchange="FREETALK.mode=this.value;freeTalkPaint()">
        <option value="talk" ${FREETALK.mode==='talk'?'selected':''}>Talk only</option>
        <option value="act" ${FREETALK.mode==='act'?'selected':''}>Talk and use their tools</option></select></label>
    </div>
    <div class="ft-warn" role="note"><b>Experimental, and it can cost money.</b>
      <span>Your agents talk with nobody asking them anything, and every message is a model call on their own brain.${FREETALK.mode==='act'
        ?' In this mode they can also use their tools. Anything that needs your permission still asks you, and your permissions and limits still apply.'
        :' In this mode they only talk and can’t use any tools.'} Everything they say is kept in Chat, in their runs and in the ledger.</span></div>
    <label class="ft-ok"><input type="checkbox" ${FREETALK.understood?'checked':''} onchange="FREETALK.understood=this.checked;document.getElementById('ft-go').disabled=!this.checked"> I understand. Let them talk.</label>
    <button id="ft-go" class="save" ${FREETALK.understood?'':'disabled'} onclick="freeTalkStart(this)">Start free talk</button>
  </div>`;
}
function freeTalkPick(n,on){
  const a=FREETALK.agents||[];FREETALK.agents=on?[...new Set([...a,n])]:a.filter(x=>x!==n);
  document.querySelectorAll('.ft-agent').forEach(l=>{const cb=l.querySelector('input');l.classList.toggle('on',cb.checked)});
}
async function freeTalkStart(btn){
  if(!FREETALK.understood)return toast('tick that you understand first');
  if((FREETALK.agents||[]).length<2)return toast('pick two or more agents');
  btn.disabled=true;btn.textContent='Starting…';
  try{
    const d=await apiJSON('/api/team/freetalk',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({agents:FREETALK.agents,topic:FREETALK.topic,minutes:FREETALK.minutes,
        messages:FREETALK.messages,mode:FREETALK.mode,understood:true})});
    FREETALK.understood=false;
    FREETALK.talks=[d.talk,...(FREETALK.talks||[]).filter(t=>t.id!==d.talk.id)];
    freeTalkPaint();
    toast('✓ Your team is talking. Watch it in Chat.',{label:'Watch',go:()=>freeTalkOpen(d.conversation_id)});
  }catch(e){toast(e.message);btn.disabled=false;btn.textContent='Start free talk'}
}
async function freeTalkStop(id){
  try{await apiJSON('/api/team/freetalk/'+encodeURIComponent(id)+'/stop',{method:'POST'});toast('Stopping them now')}
  catch(e){toast(e.message)}
}
function freeTalkOpen(cid){if(!cid)return;openApp('chat');setTimeout(()=>openConv(cid),60)}
/* The clock on the running card. It only runs while that card is on screen. */
var FT_TIMER=0;
function ftTick(){
  clearTimeout(FT_TIMER);
  const el=document.querySelector('#s-team-freetalk .ft-clock'),run=ftActive();
  if(!el||!run)return;
  el.textContent=ftLeft(run);
  FT_TIMER=setTimeout(ftTick,1000);
}

/* ---- the log: every time agents talked to each other ---- */
var FT_KIND={freetalk:['Free talk','💬'],huddle:['Huddle','🗣'],ask:['Asked a colleague','↔']};
async function talkLogPaint(){
  const box=document.getElementById('s-team-talklog');if(!box)return;
  let d;
  try{d=await apiJSON('/api/team/talklog?limit=40')}catch(e){box.innerHTML=`<p class="mut">${esc(e.message)}</p>`;return}
  FREETALK.log=d.log||[];
  box.classList.remove('mut');
  if(!FREETALK.log.length){box.innerHTML='<p class="mut">Your agents haven’t talked to each other yet. Start a free talk, ask two of them something with “@one @two”, or let them ask each other while they work.</p>';return}
  box.innerHTML=FREETALK.log.map(e=>{
    const k=FT_KIND[e.kind]||[e.kind,'·'];
    const who=e.kind==='ask'?`${avatarImg(e.who[0],'av-tool')}${esc(e.who[0])} → ${avatarImg(e.who[1],'av-tool')}${esc(e.who[1])}`
      :(e.who||[]).map(n=>avatarImg(n,'av-tool')).join('')+esc((e.who||[]).join(', '));
    return `<div class="ft-row"><div class="ft-rh"><span class="ft-k">${k[1]} ${esc(k[0])}</span><span class="ft-rw">${who}</span>
        <span class="mut ft-when">${ftAgo(e.when)}${e.kind!=='ask'?' · '+e.messages+' message'+(e.messages===1?'':'s'):''}</span></div>
      ${e.title?`<div class="ft-t">${esc(e.title)}</div>`:''}
      ${e.kind==='ask'&&e.detail?`<div class="ft-a mut">${esc(e.detail)}</div>`:''}
      <div class="ft-acts">${e.conversation_id?`<button class="endbtn" onclick="freeTalkOpen('${esc(e.conversation_id)}')">Open in Chat</button>`:''}
        <button class="endbtn" onclick="fgWatch('${esc(e.run_id)}')">Replay the run</button></div></div>`;
  }).join('');
}

/* ---- in Chat: a free talk is one card that grows, stored or live ---- */
/* The header already says who a message is for, so its opening "@name," is not said twice.
   The stored text keeps it: the record is what was said. */
function ftShown(text,to){
  const t=String(text||'');
  return to?t.replace(new RegExp('^\\s*@'+to.replace(/[^\w-]/g,'')+'\\b[,:]?\\s*','i'),''):t;
}
function freeTalkWho(agents){
  return (agents||[]).map(n=>avatarImg(n,'av-who')).join('')+'free talk · '+esc((agents||[]).join(', '));
}
function freeTalkCard(sid,meta,make){
  if(!feed)return null;
  let card=feed.querySelector(`.huddle[data-ft="${CSS.escape(sid)}"]`);
  if(card||!make)return card;
  const m=document.createElement('div');m.className='msg assistant';
  const run=(FREETALK.talks||[]).find(t=>t.id===sid&&t.status==='running');
  m.innerHTML=`<div class="who">${freeTalkWho(meta.agents)}</div><div class="huddle" data-kind="freetalk" data-ft="${esc(sid)}">
    <div class="hud-head ft-head"><span>${meta.topic?esc(meta.topic):'about anything useful to you'} · up to ${esc(meta.minutes||'?')} min or ${esc(meta.messages||'?')} messages · ${meta.mode==='act'?'talk and use tools':'talk only'}</span>
    ${run?`<button class="endbtn danger ft-stop" onclick="freeTalkStop('${esc(sid)}')">Stop</button>`:''}</div></div>`;
  feed.appendChild(m);
  return m.querySelector('.huddle');
}
/* A stored message of a free talk. True when drawn, so openConv skips its own. */
function freeTalkRender(msg){
  const meta=msg.meta||{},sid=meta.freetalk;
  if(!sid||!feed)return false;
  const card=freeTalkCard(sid,meta,true);
  if(meta.phase==='say'){card.insertAdjacentHTML('beforeend',huddleRow({speaker:meta.speaker,to:meta.to,model:meta.model,provider:meta.provider,
    text:ftShown(String(msg.content||'').replace(/^@[\w-]+ \([^)]*\): /,''),meta.to)}));
    card.dataset.n=(+card.dataset.n||0)+1}
  else if(meta.phase==='end'){card.insertAdjacentHTML('beforeend',`<div class="ft-end">${esc(String(msg.content||'').replace(/^\[|\]$/g,''))}</div>`);
    card.querySelector('.ft-stop')?.remove()}
  return true;
}
/* Live: the server's `freetalk` events. The message is already stored when it arrives. */
function freeTalkEvent(ev){
  if(ev.phase==='start'){
    FREETALK.talks=[ev,...(FREETALK.talks||[]).filter(t=>t.id!==ev.id)];
    if(typeof loadConvs==='function')loadConvs();
  }
  const t=(FREETALK.talks||[]).find(x=>x.id===ev.id);
  if(ev.phase==='say'){
    if(t)t.messages=ev.n||t.messages+1;
    if(typeof scenePulse==='function')scenePulse('say',ev.speaker,{kind:'talk',text:ev.text,to:ev.to});
    const here=ev.conversation_id===currentConv;
    if(here&&typeof voiceAgentLine==='function')voiceAgentLine(ev.speaker,ev.text);
    if(here&&feed){
      const card=freeTalkCard(ev.id,{agents:t?t.agents:[ev.speaker],topic:t?t.topic:'',minutes:t?t.minutes:'',messages:t?t.max_messages:'',mode:t?t.mode:'talk'},true);
      // stored before it was sent, so a thread opened in between already drew it
      if((+card.dataset.n||0)<(ev.n||1e9)){
        card.insertAdjacentHTML('beforeend',huddleRow({speaker:ev.speaker,to:ev.to,model:ev.model,provider:ev.provider,text:ftShown(ev.text,ev.to)}));
        card.dataset.n=ev.n||(+card.dataset.n||0)+1;
        if(typeof scrollDown==='function')scrollDown();
      }
    }
  }
  if(ev.phase==='end'){
    if(t){t.status='ended';t.reason=ev.reason}
    if(ev.conversation_id===currentConv&&feed){
      const card=freeTalkCard(ev.id,{},false);
      if(card){card.insertAdjacentHTML('beforeend',`<div class="ft-end">free talk ended: ${esc(ev.reason)}, ${ev.count} message${ev.count===1?'':'s'}</div>`);
        card.querySelector('.ft-stop')?.remove()}
    }
    toast('Free talk ended: '+ev.reason,{label:'Read it',go:()=>freeTalkOpen(ev.conversation_id)});
    talkLogPaint();
  }
  freeTalkPaint();
}
