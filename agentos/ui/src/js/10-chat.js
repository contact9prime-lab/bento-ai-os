/* ================= chat app ================= */
const PLACEHOLDER_IDLE='Ask, tell it what to do, paste an image — or @subagent to address a team member directly';
const PLACEHOLDER_BUSY='Say what comes next — it decides whether that changes the run in flight or waits its turn';
function renderChat(body){
  body.innerHTML=`<div class="chatwrap">
    <div class="cside">
      <button id="newchat">＋ New chat</button>
      <div id="convs"></div>
    </div>
    <div class="cmain">
      <div id="topbar">
        ${/* Two selects, coupled: WHO answers, then WHAT it runs on. One select
              holding both — engines in an optgroup above the models — could show
              Claude Code chosen and a Gemini model selected underneath it, which
              is two answers to the same question disagreeing on screen. The
              second list belongs to the first: choosing an executor narrows it
              to the models that executor can actually wake up. */''}
        <select id="execchip" class="modelchip" title="Which brain answers here"
          onchange="chatPickExecutor(this.value)"><option>…</option></select>
        <select id="modelchip" class="modelchip" title="Which model it runs on"
          onchange="chatPickModel(this.value)"><option>…</option></select>
        <select id="autosel" title="Autonomy">
          <option value="paranoid">Paranoid</option>
          <option value="balanced">Balanced</option>
          <option value="full">Full autonomy</option>
        </select>
        <button id="ttsbtn" class="endbtn" title="Speak replies aloud"></button>
        <button id="clearses" class="endbtn" title="Wipe this conversation's messages and start fresh">Clear session</button>
      </div>
      <div id="chat"><div class="inner" id="feed"></div></div>
      <div id="composer">
        <div id="queue"></div>
        <div id="combox">
          <textarea id="input" rows="1" placeholder="${PLACEHOLDER_IDLE}"></textarea>
          <button id="mic" title="dictate (mic)"></button>
          <button id="send" disabled>➤</button>
        </div>
      </div>
    </div>
  </div>`;
  feed=$('#feed');chatEl=$('#chat');input=$('#input');sendBtn=$('#send');
  sendBtn.onclick=send;
  input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});
  input.addEventListener('input',()=>{input.style.height='auto';input.style.height=Math.min(input.scrollHeight,160)+'px';syncSend();
    draftSave(currentConv,input.value)});   // a half-typed message is work too
  input.addEventListener('paste',e=>{
    const items=[...(e.clipboardData?.items||[])].filter(it=>it.type.startsWith('image/'));
    if(!items.length)return;
    e.preventDefault();
    items.forEach(it=>addPastedImage(it.getAsFile()));
  });
  $('#newchat').onclick=newChat;
  $('#clearses').onclick=clearSession;
  $('#mic').onclick=micToggle;$('#mic').innerHTML=svgMic(14);
  const tb=$('#ttsbtn');
  const setTts=()=>{tb.textContent=VOICE.tts?'Voice on':'Voice off'};
  setTts();
  tb.onclick=()=>{VOICE.tts=!VOICE.tts;saveVoice();setTts();if(!VOICE.tts)speechSynthesis?.cancel()};
  /* The brain is the machine's, not this window's. A per-chat picker meant the
     same machine answered as a different agent depending on which window you
     happened to be in, and background work (tasks, Telegram, the API) could
     never see that choice at all — so "what is this machine running on" had no
     single answer. These two selects change it for everything, everywhere. */
  $('#autosel').onchange=()=>fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({autonomy:$('#autosel').value})});
  loadModels();loadBrains();loadConfig();loadConvs();
  restoreDraft();
  if(currentConv)openConv(currentConv);else showWelcome();
  setRunning(RUNNING.has(currentConv));
  renderQueue();
}
/* The composer's unsent text, per conversation. Restored when the window opens
   and when you switch back to a thread you were mid-sentence in. */
function restoreDraft(cid){
  if(!input)return;
  const d=draftLoad(cid===undefined?currentConv:cid);
  if(!d)  {input.value='';syncSend();return}
  input.value=d;
  input.style.height='auto';input.style.height=Math.min(input.scrollHeight,160)+'px';
  syncSend();
}
function setRunning(r){running=r;
  $('#spin').classList.toggle('on',r);
  if(r)jarvisOn();else jarvisOff();
  if(!sendBtn)return;
  input.placeholder=r?PLACEHOLDER_BUSY:PLACEHOLDER_IDLE;
  syncSend();
}
/* One button, two jobs while a turn runs: with something typed it QUEUES that
   message (the running turn gets to decide whether it changes what it's doing);
   empty, it is the stop button it has always been. */
function syncSend(){
  if(!sendBtn||!input)return;
  const has=!!input.value.trim()||PENDING_IMGS.length>0;
  const stop=running&&!has;
  sendBtn.classList.toggle('stop',stop);
  sendBtn.textContent=stop?'◼':'➤';
  sendBtn.title=stop?'Stop the agent':(running?'Queue this — it runs next, or gets folded into what\'s running':'Send');
  sendBtn.disabled=!(has||stop);
}
/* the queue strip above the composer: this conversation's visible to-do list */
function renderQueue(){
  const box=$('#queue'); if(!box)return;
  const q=(currentConv&&QUEUES[currentConv])||[];
  box.classList.toggle('on',q.length>0);
  box.innerHTML='';
  if(!q.length)return;
  const h=document.createElement('div');h.className='qhead';
  h.textContent='Up next · '+q.length;box.appendChild(h);
  q.forEach(i=>{
    const el=document.createElement('div');el.className='qitem'+(i.status==='deferred'?' deferred':'');
    el.innerHTML='<span class="qt"></span><span class="qs"></span><button class="qx" title="remove">✕</button>';
    el.querySelector('.qt').textContent=i.text||'(image)';
    el.querySelector('.qs').textContent=i.status==='deferred'?'after this turn':'queued';
    if(i.reason)el.title=i.reason;
    el.querySelector('.qx').onclick=()=>{
      if(ws&&ws.readyState===1)ws.send(JSON.stringify({type:'queue_remove',conversation_id:currentConv,id:i.id}));
    };
    box.appendChild(el);
  });
}
let PENDING_IMGS=[];
function bubbleImgs(el,urls){
  if(!urls||!urls.length)return;
  const g=document.createElement('div');g.className='bimgs';
  urls.forEach(u=>{const im=document.createElement('img');im.src=u;g.appendChild(im)});
  el.appendChild(g);
}
function addPastedImage(file){
  if(!file)return;
  if(PENDING_IMGS.length>=4){toast('up to 4 images per message');return}
  const img=new Image();
  img.onload=()=>{
    const MAX=1568,sc=Math.min(1,MAX/Math.max(img.width,img.height));
    const c=document.createElement('canvas');
    c.width=Math.round(img.width*sc);c.height=Math.round(img.height*sc);
    c.getContext('2d').drawImage(img,0,0,c.width,c.height);
    // downscale/recompress large pastes (screenshots) so history stays light
    PENDING_IMGS.push((sc<1||file.size>800000)?c.toDataURL('image/jpeg',.9):c.toDataURL('image/png'));
    URL.revokeObjectURL(img.src);renderAttach();
  };
  img.src=URL.createObjectURL(file);
}
function renderAttach(){
  let a=$('#attach');
  if(!PENDING_IMGS.length){a?.remove();syncSend();return}
  if(!a){a=document.createElement('div');a.id='attach';const cb=$('#combox');cb.parentNode.insertBefore(a,cb)}
  a.innerHTML=PENDING_IMGS.map((u,i)=>`<div class="att"><img src="${u}"><button onclick="rmAttach(${i})" title="remove">×</button></div>`).join('');
  syncSend();
}
function rmAttach(i){PENDING_IMGS.splice(i,1);renderAttach()}
function userBubble(text,imgs){
  $('#welcome')?.remove();
  const m=document.createElement('div');m.className='msg user';
  m.innerHTML='<div class="who">you</div><div class="bubble"></div>';
  m.querySelector('.bubble').textContent=text;
  bubbleImgs(m.querySelector('.bubble'),imgs);
  feed.appendChild(m);
  return m;
}
function send(){
  const text=input.value.trim();const imgs=PENDING_IMGS.slice();
  // nothing typed while a turn runs → the button is the stop button
  if(running&&!text&&!imgs.length){ws.send(JSON.stringify({type:'abort',conversation_id:currentConv}));return}
  if((!text&&!imgs.length)||!ws||ws.readyState!==1)return;
  const wasRunning=running;
  // A turn is already running: the server queues this instead of refusing it. The
  // agent triages it at its next step boundary — folded into the live run, or kept
  // as the next turn. Either way the queue strip is the receipt, so no bubble yet.
  if(!wasRunning)userBubble(text,imgs);
  ws.send(JSON.stringify({type:'chat',text,images:imgs,conversation_id:currentConv,model:''}));
  draftClear(currentConv);
  input.value='';input.style.height='auto';PENDING_IMGS=[];renderAttach();
  if(wasRunning){syncSend();scrollDown();return}
  showWorking();scrollDown();setRunning(true);
}
let WORK_T0=0, WORK_MSG='';
function showWorking(){
  if(!feed)return;
  if(!$('#working')){
    const w=document.createElement('div');w.className='working';w.id='working';
    w.innerHTML=`<div class="orb"></div><div class="wcol"><div class="wtxt"></div><div class="wsub"></div></div><div class="dots"><i></i><i></i><i></i></div>`;
    feed.appendChild(w);
  }
  WORK_T0=WORK_T0||Date.now();
  // Start the shared per-second ticker NOW, on send — not when the server's first
  // event arrives. A Claude Code turn cold-starts silently for a minute or more,
  // and without this the row painted once and froze at "0s" until that first event;
  // actSync counts #working as live, so the clock counts up from send. (Paints at
  // once too: a row that says nothing for a second is a flicker.)
  if(typeof actSync==='function')actSync(); else tickWorking();
}
/* The waiting row. Driven by the shared activity record (08b-activity.js) so
   the sentence here, in the copilot panels and on the presence bubble is the
   same sentence — and it is a sentence, not "working": what the step is, how
   long THIS step has taken, and how long the whole turn has. The ticker that
   calls this lives in actTick(); it stops itself when nothing is running. */
function tickWorking(){
  const w=$('#working'); if(!w)return;
  const cid=currentConv;
  const txt=w.querySelector('.wtxt'), sub=w.querySelector('.wsub');
  // While a tool card sits directly above with its own live timer, THAT is the
  // sentence — repeating it here just says the same thing twice. The row keeps
  // the orb (the turn is alive) and the turn-level clock the card cannot show.
  const inTool=!!(cid&&ACT[cid]&&ACT[cid].phase==='tool');
  const phrase=(!inTool&&typeof actText==='function'&&cid)?actText(cid):'';
  if(txt)txt.textContent=phrase?phrase.charAt(0).toUpperCase()+phrase.slice(1)
                               :(WORK_MSG||agentName()+' is working');
  if(sub)sub.textContent=(typeof actClock==='function'&&cid&&ACT[cid])
    ? actClock(cid)
    : (WORK_T0?actDur(Date.now()-WORK_T0):'');
  // a visible per-second mutation forces the compositor to repaint — this is what
  // switching tabs was doing manually on macOS to make streamed text appear
  const s=Math.round((Date.now()-WORK_T0)/1000);
  w.style.opacity=(0.999+(s%2)*0.001);
  scrollDown();
}
function removeWorking(){
  $('#working')?.remove();
  WORK_T0=0;WORK_MSG='';
  // …and let the ticker stop itself now that this row is gone.
  if(typeof actSync==='function')actSync();
}
async function loadConvs(){
  const box=$('#convs'); if(!box)return;
  const r=await fetch('/api/conversations');const d=await r.json();
  if(!$('#convs'))return;
  box.innerHTML='';
  // the agent's embedded threads (omnibar Desktop, per-app copilots) live in
  // their own sections so app-scoped exchanges never drown the real chats
  const groups=[['Desktop',c=>c.origin==='omni'],
                ['Copilots',c=>(c.origin||'').startsWith('copilot:')],
                ['',c=>c.origin!=='omni'&&!(c.origin||'').startsWith('copilot:')]];
  const row=c=>{
    const el=document.createElement('div');el.className='conv'+(c.id===currentConv?' active':'');
    el.innerHTML=`<span class="t"></span><button class="del">✕</button>`;
    el.querySelector('.t').textContent=(RUNNING.has(c.id)?'● ':'')+(c.title||'untitled');
    if(RUNNING.has(c.id))el.querySelector('.t').style.color='var(--acc,#5eead4)';
    el.onclick=e=>{if(!e.target.classList.contains('del'))openConv(c.id)};
    el.querySelector('.del').onclick=async e=>{e.stopPropagation();
      if(RUNNING.has(c.id))return toast('that chat has a turn running — stop it first');
      await fetch('/api/conversations/'+c.id,{method:'DELETE'});
      if(currentConv===c.id)newChat(); else loadConvs();};
    return el;
  };
  groups.forEach(([label,test])=>{
    const items=d.conversations.filter(test);
    if(!items.length)return;
    if(label){const h=document.createElement('div');h.className='convgrp';h.textContent=label;box.appendChild(h)}
    items.forEach(c=>box.appendChild(row(c)));
  });
}
async function openConv(cid){
  if(input&&currentConv!==cid)draftSave(currentConv,input.value);   // park the one you were typing
  currentConv=cid;
  restoreDraft(cid);
  const r=await fetch('/api/conversations/'+cid);const d=await r.json();
  if(!feed)return;
  curBody=null;curThink=null;curText='';
  feed.innerHTML='';
  d.messages.forEach(msg=>{
    const m=document.createElement('div');m.className='msg '+msg.role;
    if(msg.role==='user'){m.innerHTML='<div class="who">you</div><div class="bubble"></div>';const bb=m.querySelector('.bubble');bb.textContent=msg.content;bubbleImgs(bb,msg.meta?.images);}
    else{m.innerHTML='<div class="who">'+msgWho(msg.meta)+'</div>';
      (msg.meta?.steps||[]).forEach(s=>{
        if(s.type==='tool'){const card=document.createElement('div');card.className='tool';
          // a reopened conversation reads the same way a live one did
          const argStr=actDetail(s.name,s.args)
            ||(s.name==='run_command'?(s.args.command||''):JSON.stringify(s.args));
          card.innerHTML=`<div class="head"><span class="tname2">${esc(s.name)}</span><span class="targ">${esc(argStr)}</span><span class="tstat ${s.ok?'ok':'fail'}">${s.ok?'done':'failed'}</span></div><div class="out"></div>`;
          card.querySelector('.out').textContent=s.output||'';
          card.querySelector('.head').onclick=()=>card.classList.toggle('open');
          m.appendChild(card);}
        else if(s.type==='steer'){   // something you said mid-run, taken into it
          const d=document.createElement('div');d.className='steer';
          d.textContent='took in: '+(s.text||'');d.title=s.reason||'';m.appendChild(d);}
      });
      const b=document.createElement('div');b.className='body';b.innerHTML=md(msg.content||'');m.appendChild(b);}
    feed.appendChild(m);
  });
  // a turn is live in this conversation: replay its buffered stream and keep streaming
  if(RUNNING.has(cid)){
    startAssistant();
    const s=STREAMS[cid];
    if(s&&curBody){
      if(s.html){const holder=document.createElement('div');holder.innerHTML=s.html;
        [...holder.children].forEach(el=>{
          const h=el.querySelector?.('.head');
          if(h)h.onclick=()=>el.classList.toggle('open');
          curBody.parentNode.insertBefore(el,curBody)});}
      curText=s.text;curBody.innerHTML=md(curText);
    }
    showWorking();
  }
  setRunning(RUNNING.has(cid));
  renderQueue();
  loadConvs();scrollDown();
}
function newChat(){
  currentConv=null;curBody=null;curThink=null;curText='';
  if(feed){feed.innerHTML='';showWelcome()}
  setRunning(false);
  renderQueue();
  loadConvs();
}
async function clearSession(){
  if(RUNNING.has(currentConv))return toast('a turn is running in this chat — stop it first');
  if(currentConv)await fetch('/api/conversations/'+currentConv+'/clear',{method:'POST'});
  curBody=null;curText='';
  if(feed){feed.innerHTML='';showWelcome()}
  toast('session cleared');loadConvs();
}
function showWelcome(){
  if(!feed)return;
  const w=document.createElement('div');w.id='welcome';
  w.innerHTML=`<h1>${esc(agentName())}</h1><p>Your machine, with a brain. Local or cloud AI — real actions, your approval.</p>
  <div class="chips">
    <button class="chip">How is this machine doing? Check CPU, memory, disk.</button>
    <button class="chip">What's taking up the most space in my home folder?</button>
    <button class="chip">Fetch the top Hacker News stories and summarize them.</button>
    <button class="chip">Create a project folder with a starter README in my workspace.</button>
    <button class="chip">Every morning at 9:00, check disk space and notify me if it's low.</button>
    <button class="chip">Remember that I prefer concise answers.</button>
  </div>`;
  w.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{input.value=c.textContent.trim();input.dispatchEvent(new Event('input'));input.focus()});
  feed.appendChild(w);
}
async function loadModels(){
  /* Nothing to choose here any more — this reports what Settings decided, so the
     answer to "what is this running on" is the same in every window and for
     background work too. */
  try{
    const d=await (await fetch('/api/models')).json();
    MODELS_STATE=d;
    paintBrainChips();
  }catch(e){}
}
/* The old name, kept because four other files repaint "the model chip" after
   changing something. It is the same paint; there are just two selects now. */
function paintModelChip(){paintBrainChips()}
var MODELS_STATE={};
/* ---- the brain: one executor, one of ITS models ----------------------------
   `/api/brains` is the single answer to "what can answer here" — local
   providers, cloud providers and other installed agents in one list, each
   owning the models it can wake up. Every surface paints from this: these two
   selects, the menu-bar chip, Settings → AI providers, the wizard. Kept in a
   `var` because the bundle is one script and 09- reaches it. */
var BRAINS={executors:[],current:{executor:'',model:''}};
async function loadBrains(){
  try{
    const d=await (await fetch('/api/brains')).json();
    if(d&&d.executors)BRAINS=d;
  }catch(e){}
  paintBrainChips();paintForwardChip();
}
function curExecutor(){
  return (BRAINS.executors||[]).find(e=>e.id===(BRAINS.current||{}).executor)||null;
}
function paintBrainChips(){
  const ex=$('#execchip'),md=$('#modelchip');
  const cur=BRAINS.current||{},list=BRAINS.executors||[];
  if(ex){
    /* Two groups because they are two kinds of brain: a provider answers
       through Aria's own loop, an agent replaces it. One that is not installed
       stays in the list, disabled, carrying the reason — hidden reads as "this
       OS cannot", and it can, once the thing is there. */
    const grp=(label,kind)=>{
      const items=list.filter(e=>e.kind===kind);
      if(!items.length)return '';
      return `<optgroup label="${esc(label)}">`+items.map(e=>
        `<option value="${esc(e.id)}"${e.id===cur.executor?' selected':''}${e.available?'':' disabled'}>`
        +esc(e.name)+(e.available?(e.detail?' · '+esc(e.detail):''):' — '+esc(e.reason||'not available'))
        +`</option>`).join('')+`</optgroup>`;
    };
    /* Nothing chosen yet is its own state and has to be visible: without a
       placeholder the browser shows the first option, which reads as a machine
       already set to something it is not. */
    const none=cur.executor?'':'<option value="" selected>— nothing set —</option>';
    ex.innerHTML=none+grp('Models — answered by '+agentName(),'provider')
                +grp('Agents — they answer instead','agent');
    const sel=curExecutor();
    ex.classList.toggle('engine',!!(sel&&sel.kind==='agent'));
    ex.title=sel?(sel.what||sel.name):'nothing can answer here yet';
  }
  if(md){
    const sel=curExecutor();
    const mods=(sel&&sel.models)||[];
    md.innerHTML=mods.length
      ? mods.map(m=>`<option value="${esc(m.id)}"${m.id===cur.model?' selected':''}>${esc(m.name||m.id)}</option>`).join('')
      : `<option value="">— no model —</option>`;
    /* A model that is set but no longer offered stays visible and selected, or
       the bar would quietly show something else answering. */
    if(cur.model&&!mods.some(m=>m.id===cur.model))
      md.insertAdjacentHTML('beforeend',
        `<option value="${esc(cur.model)}" selected>${esc(cur.model)} (not currently offered)</option>`);
    md.disabled=!mods.length;
    md.title=(sel&&sel.kind==='agent')
      ?'Which model to ask '+(sel.name||'it')+' for. It brings its own account.'
      :(cur.model||'no model set');
  }
}
/* One write for both, because they are one decision — see executors.set_brain. */
async function setBrain(executor,model){
  const r=await fetch('/api/brain',{method:'PUT',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({executor:executor,model:model||''})});
  const d=await r.json().catch(()=>({}));
  if(!r.ok||d.error){toast(d.error||'could not change the brain');await loadBrains();return false}
  BRAINS={executors:d.executors||[],current:d.current||{},engine:d.engine};
  await loadConfig();await loadModels();
  paintBrainChips();
  toast('✓ '+(d.message||'brain changed'));
  return true;
}
async function chatPickExecutor(v){
  if(!v)return;
  const ex=(BRAINS.executors||[]).find(e=>e.id===v);
  // its own remembered model, not the one the previous executor was on
  await setBrain(v,ex?ex.model:'');
}
async function chatPickModel(v){
  const cur=(BRAINS.current||{}).executor;
  if(!cur)return;
  await setBrain(cur,v);
}
/* One place to change it, and the chip goes there rather than describing where. */
function openModelSettings(){
  const ex=curExecutor();
  SETTAB=(ex&&ex.kind==='agent')?'executors':'ai';
  try{localStorage.setItem('settab',SETTAB)}catch(e){}
  openApp('settings');
}
async function loadConfig(){
  const r=await fetch('/api/config');cfg=await r.json();
  if($('#autosel'))$('#autosel').value=cfg.autonomy;
  // wallpaper presets live in config, so the wallpaper may only be resolvable now
  if(cfg&&cfg.desktop&&cfg.desktop.wallpaper_preset&&!$('#wall').classList.contains('has'))loadWallpaper();
  if(typeof scLoad==='function')scLoad();   // custom keybindings take effect immediately
  paintForwardChip();
  paintModelChip();
}
/* The top bar states the brain — executor and model — because that is the one
   fact that changes what every reply on this machine is. It used to appear only
   when the machine forwarded to another agent, which meant the common case (a
   provider and a model) had no answer on screen at all, and a reply that wasn't
   from your own agent looked exactly like one that was. */
function paintForwardChip(){
  const chip=$('#fwdchip');if(!chip)return;
  const ex=curExecutor(),cur=BRAINS.current||{};
  if(!ex){chip.hidden=true;return}
  chip.hidden=false;
  const agent=ex.kind==='agent';
  // For an agent executor the model it actually woke up on is reported back by
  // the run itself (engine_info) — better than the alias we asked for, so it
  // wins once it is known.
  const model=(agent?(FWD_MODEL[ex.id]||cur.model||'default'):(cur.model||'no model'))
    .replace(/^(claude-|ollama\/|anthropic\/|openai\/|google\/|openrouter\/|custom\/)/,'');
  const name=ex.name.split('—')[0].trim();
  chip.innerHTML=(agent?'⇥ ':'▲ ')+esc(name)+'<span class="fwdmdl">'+esc(model)+'</span>';
  chip.title=(agent
      ?'Every turn on this machine is answered by '+name
        +' — apps and App Studio still use '+((cfg&&cfg.agent_name)||'Aria')
      :((cfg&&cfg.agent_name)||'Aria')+' answers, running on '+(cur.model||'no model yet'))
    +'. Click to change it.';
  chip.classList.toggle('engine',agent);
}


/* ---- who actually answered -------------------------------------------------
   A reply is labelled with the agent that produced it, not with the built-in
   one by default. When the machine forwards, Claude Code writes the
   text — calling that "Aria" is the kind of quiet mislabelling that makes a
   forwarding machine confusing, and the model is shown alongside so the answer
   to "what is this running on" is on screen rather than something you ask. */
function engineLabel(engine,model){
  const mark={'claude-code':'◈'}[engine]||'▲';
  const name={'claude-code':'Claude Code'}[engine]||agentName();
  const m=(model||'').trim();
  return `${mark} ${esc(name)}${m?`<span class="whomdl">${esc(m)}</span>`:''}`;
}
/* The label for a stored message: its own recorded engine/model, falling back to
   the executor step for turns saved before that was recorded. */
function msgWho(meta){
  const engine=(meta&&meta.engine)
    ||((meta&&meta.steps||[]).find(s=>s&&s.type==='executor')||{}).name||'';
  const model=(meta&&(meta.engine_model||meta.model))||'';
  return engineLabel(engine,model);
}
