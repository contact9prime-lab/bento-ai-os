/* ================= the ever-present agent: turn client + copilot panels =================
   One shared machinery for every embedded agent surface:
   - agentTurn(): send a turn on any conversation, with per-surface context and a sink
   - miniFeed(): a compact live renderer (text, thinking, tool cards, approvals)
   - copilot panels: a ✦ conversation inside every app window, scoped to that app
   The Chat window remains the full-history surface; these are the in-place hands. */

let PENDING_SINKS=[];   // sinks waiting for their server-created conversation id, by origin
function claimConversation(ev){
  // Returns true when this new conversation belongs to an embedded surface
  // (omnibar/copilot) — the Chat window must not adopt it as currentConv.
  const i=PENDING_SINKS.findIndex(p=>p.origin===ev.origin);
  if(i>=0){
    const p=PENDING_SINKS.splice(i,1)[0];
    sinkOn(ev.id,p.sink);
    if(p.onCid)p.onCid(ev.id);
    return true;
  }
  return !!(ev.origin&&ev.origin!=='user');
}
/* One turn at a time per conversation is a server rule, so a second ask while
   the agent is busy gets QUEUED (and says so) instead of being dropped. */
const TURN_QUEUE=[];
function agentQueueFlush(cid){
  const i=TURN_QUEUE.findIndex(o=>o.cid===cid);
  if(i<0)return;
  const o=TURN_QUEUE.splice(i,1)[0];
  setTimeout(()=>agentTurn(o),150);
}
function agentTurn(o){
  // o: {text, cid?, origin, title?, context?, sink, onCid?}
  if(!ws||ws.readyState!==1){toast('not connected to the server');return false}
  if(o.cid&&RUNNING.has(o.cid)){
    TURN_QUEUE.push(o);
    if(o.sink){
      if(o.sink.start)o.sink.start();
      if(o.sink.status)o.sink.status({message:`queued — ${agentName()} is finishing something`});
    }
    // never a dead end: the caller can offer "stop what's running and send this now"
    if(o.onQueued)o.onQueued(()=>{
      try{ws.send(JSON.stringify({type:'abort',conversation_id:o.cid}))}catch(e){}
    });
    return true;
  }
  if(o.cid)sinkOn(o.cid,o.sink);
  else PENDING_SINKS.push({origin:o.origin,sink:o.sink,onCid:o.onCid});
  // Acknowledge the send HERE, not when the server says turn_start. Creating a
  // conversation, loading its history and waking the model take seconds, and
  // for all of them the panel used to look exactly like a message that never
  // left — the Chat window has always shown its working row on send, and this
  // is the same promise for every embedded surface.
  if(o.sink&&o.sink.start)o.sink.start({conversation_id:o.cid||''});
  ws.send(JSON.stringify({type:'chat',text:o.text,conversation_id:o.cid||null,
    images:o.images||[],model:'',surface:'gui',origin:o.origin||'user',title:o.title||'',
    context:o.context||''}));
  return true;
}

/* ---- stopping: any turn, from anywhere, at any moment ---- */
function stopAgent(cid){
  if(!ws||ws.readyState!==1)return false;
  ws.send(JSON.stringify({type:'abort',conversation_id:cid||null}));   // no id = stop everything
  return true;
}
function stopAllAgents(){
  const n=RUNNING.size+((window.STUDIO&&STUDIO.building)?1:0);
  // drop anything queued behind it too, or the next turn starts the moment this one dies
  if(typeof TURN_QUEUE!=='undefined')TURN_QUEUE.length=0;
  if(!stopAgent(null))return toast('not connected to the server');
  toast(n?`stopping ${n} running turn${n>1?'s':''}…`:'nothing is running right now');
}

/* Every mini-feed's waiting line, repainted from the shared activity record —
   the same sentence and the same clock the Chat window shows. Called once a
   second from actTick(); a panel whose turn has ended has no record and falls
   back to whatever the last status said. */
function mfPaint(){
  document.querySelectorAll('.mf-working').forEach(el=>{
    const cid=el.dataset.cid;
    const t=el.querySelector('.mft'), c=el.querySelector('.mfc');
    if(t&&typeof actText==='function'&&ACT[cid])t.textContent=actText(cid);
    // Before turn_start there is no record yet, so the row keeps its own clock:
    // the seconds between pressing send and the server answering are the ones
    // that felt like nothing had happened.
    if(c)c.textContent=(typeof actClock==='function'&&ACT[cid])?actClock(cid)
      :(el.dataset.t0?actDur(Date.now()-(+el.dataset.t0)):'');
    // While a tool card is open right above it, the card IS the live line — two
    // copies of "running npm test · 12s" in a 300px panel is noise, not progress.
    el.classList.toggle('quiet',!!(ACT[cid]&&ACT[cid].phase==='tool'));
  });
}
/* ---- miniFeed: renders one conversation's live events into a container ---- */
function miniFeed(box,opts){
  opts=opts||{};
  let body=null,text='',think=null,working=null;
  const scroll=()=>{const sc=opts.scrollEl||box;sc.scrollTop=sc.scrollHeight};
  const clearWorking=()=>{if(working){working.remove();working=null}};
  const ensureBody=()=>{
    if(!body){body=document.createElement('div');body.className='mf-body body';box.appendChild(body)}};
  // Which conversation this feed is watching. Known from the first event that
  // carries it — a brand-new thread has no id until the server names it.
  const bind=ev=>{if(working&&ev&&ev.conversation_id)working.dataset.cid=ev.conversation_id};
  return {
    // Called twice on purpose: once locally the instant the message is sent,
    // then again on the server's turn_start. The second call must not wipe the
    // row and restart its clock — it only learns the conversation id.
    start(ev){
      if(working&&working.isConnected){bind(ev);mfPaint();return}
      text='';body=null;think=null;clearWorking();
      if(opts.onStart)opts.onStart();
      working=document.createElement('div');working.className='mf-working';
      working.dataset.t0=Date.now();
      working.innerHTML='<span class="mfo"></span><span class="mft">sent — waking the agent</span><span class="mfc"></span>';
      box.appendChild(working);bind(ev);scroll();
      actSync();          // the row has its own clock now — start the ticker for it
    },
    status(ev){bind(ev);
      if(working&&ev.message)working.querySelector('.mft').textContent=ev.message},
    thinking(t){
      // answer surfaces (cards) stay clean: the reasoning trace only says "thinking…"
      if(opts.showThinking===false){
        if(working)working.querySelector('.mft').textContent='thinking';
        return;
      }
      if(!think){think=document.createElement('div');think.className='think mf-think';box.insertBefore(think,working)}
      think.textContent+=t;think.scrollTop=think.scrollHeight;
    },
    delta(t){
      clearWorking();ensureBody();
      text+=t;body.innerHTML=md(text);scroll();
    },
    toolStart(ev,argStr){
      body=null;text='';think=null;bind(ev);
      const card=document.createElement('div');card.className='tool';card.dataset.mf=ev.call_id;
      // data-t0: actPaintTimers ages it once a second, so a long call is visibly long
      const arg=ev.detail||actDetail(ev.name,ev.args)||argStr;   // words, not JSON
      card.innerHTML=`<div class="head"><span class="tname2">${esc(ev.name)}</span><span class="targ" title="${esc(argStr)}">${esc(arg)}</span><span class="tstat run"${ev.pending_approval?'':` data-t0="${Date.now()}"`}>${ev.pending_approval?'awaiting approval':'running'}</span></div><div class="out"></div>`;
      card.querySelector('.head').onclick=()=>card.classList.toggle('open');
      box.insertBefore(card,working);scroll();mfPaint();
    },
    toolEnd(ev){
      const card=box.querySelector(`.tool[data-mf="${CSS.escape(ev.call_id)}"]`);
      if(card){const st=card.querySelector('.tstat');
        const t0=+st.dataset.t0||0;st.removeAttribute('data-t0');
        st.className='tstat '+(ev.ok?'ok':'fail');
        st.textContent=(ev.ok?'done':'failed')+(t0?' · '+actDur(Date.now()-t0):'');
        card.querySelector('.out').textContent=ev.output||'(no output)';
        if(!ev.ok)card.classList.add('open')}
      mfPaint();
      if(opts.onTool)opts.onTool(ev);
    },
    approval(apBox){box.insertBefore(apBox,working);scroll();return true},
    error(ev){
      clearWorking();
      const d=document.createElement('div');d.className='errmsg';d.textContent=ev.message;
      box.appendChild(d);scroll();
    },
    end(ev){clearWorking();actSync();body=null;think=null;if(opts.onEnd)opts.onEnd(text);text=''},
  };
}

/* ---- visible hands: when a tool touches an app, that surface glows ---- */
function agentHands(ev){
  let appId=null;
  if(ev.name==='control_desktop'&&ev.args){
    const t=ev.args.target;
    appId=typeof shellResolveApp==='function'?shellResolveApp(t):null;
    if(ev.args.action==='apply_theme')appId=null;
  }
  else if(ev.name==='set_wallpaper'||ev.name==='generate_wallpaper')appId='personalize';
  else if(ev.name==='create_app'||ev.name==='develop_agentos')appId='studio';
  if(!appId)return;
  const w=(typeof winsOf==='function'?winsOf(appId):[])[0];
  const els=[w&&w.el,document.querySelector(`#dock .dockb[data-app="${CSS.escape(appId)}"]`)].filter(Boolean);
  els.forEach(el=>{
    el.classList.add('agent-touch');
    clearTimeout(el._ht);el._ht=setTimeout(()=>el.classList.remove('agent-touch'),2600);
  });
}

/* ---- copilot panels: the agent inside every app window ---- */
const COPILOT={cids:{}};                 // appId -> conversation id (session cache)
function copilotStarters(appId){
  const S={
    files:['What is in this folder?','Find duplicates here','Organize these files by type'],
    memory:['What do you remember about me?','Clean up outdated memories','Pin the important ones'],
    tasks:['Set up a morning briefing','Why did my last task fail?','What runs today?'],
    taskmgr:['What is eating my RAM?','Anything unusual running?','Free up some memory'],
    syssettings:['Fix my wifi','Pair my headphones','Dim the screen at night'],
    models:['Which model fits my GPU?','Free the VRAM','Pull a good coding model'],
    store:['Find me a weather MCP','Build a notes app with AI','What is worth installing?'],
    studio:['Improve this app','Why does the build fail?','Add an AI feature to it'],
    kg:['What do you know about my projects?','Merge duplicate entities','Show contradictions'],
    logs:['Any errors today?','Summarize what happened','Why did that fail?'],
    themes:['Design me a calm dark theme','Make it feel like a terminal','Match my wallpaper'],
    personalize:['Paint a quiet harbor at dusk','Something minimal and dark','Surprise me'],
    telegram:['Summarize unread chats','Who wrote me today?','Set up channel alerts'],
    mcp:['What tools do I have?','Find and add a calendar server','Which server is failing?'],
    permissions:['What can apps do right now?','Anything risky granted?','Tighten the defaults'],
    tokens:['Where do my tokens go?','Cheaper model for background work?','Usage this week'],
    fabric:['Build me a research team','Why did the last run stall?','Add a validator step'],
    snapshots:['Snapshot before I experiment','What changed since yesterday?'],
    mission:['How healthy is the system?','What needs my attention?'],
    terminal:['Explain the last error','Write the command for me'],
  };
  return S[appId]||['What can you do in here?','Fix what looks wrong','Explain this app'];
}
async function copilotThread(appId,title){
  if(COPILOT.cids[appId])return COPILOT.cids[appId];
  try{
    const d=await (await fetch('/api/conversations')).json();
    const hit=(d.conversations||[]).find(c=>c.origin==='copilot:'+appId);
    if(hit){COPILOT.cids[appId]=hit.id;return hit.id}
  }catch(e){}
  return null;   // created lazily on the first turn (origin routes it back to us)
}
function copilotContext(w){
  const app=w.app;
  let state='';
  try{state=app.context?String(app.context(w)||''):''}catch(e){}
  const others=[];WM.wins.forEach(o=>{if(o.id!==w.id&&!o.min)others.push(o.app.title)});
  return [
    `You are ${agentName()}, embedded as the copilot panel INSIDE the "${app.title}" app of AgentOS.`,
    `The user sees the app right beside your panel. Prefer ACTING through your tools over explaining;`,
    `keep replies short (a sentence or two unless asked). The app refreshes automatically after your tools run.`,
    `App: ${app.title} — ${app.desc||''}.`,
    state?`Live app state: ${state}`:'',
    others.length?`Also open: ${others.join(', ')}.`:'',
    `Desktop control is available via control_desktop/desktop_state; files via search_files/read_file/write_file.`,
  ].filter(Boolean).join('\n');
}
function toggleCopilot(w){
  const panel=w.el.querySelector('.copanel');
  const btn=w.el.querySelector('.cp-btn');
  const open=!panel.classList.contains('open');
  panel.classList.toggle('open',open);
  btn.classList.toggle('on',open);
  localStorage.setItem('copilot:'+w.id,open?'1':'');
  if(open&&!panel.dataset.ready)initCopilot(w,panel);
  if(open)setTimeout(()=>{const i=panel.querySelector('.cp-in');if(i)i.focus()},250);
}
async function initCopilot(w,panel){
  panel.dataset.ready='1';
  panel.innerHTML=`<div class="cp-head"><span class="cp-ava">✦</span><span class="cp-name">${esc(agentName())}</span>
      <span class="cp-app">${esc(w.app.title)}</span><span style="flex:1"></span>
      <button class="cp-open" title="Open in Chat">⤢</button></div>
    <div class="cp-feed"></div>
    <div class="cp-starters"></div>
    <div class="cp-inbar"><textarea class="cp-in" rows="1" placeholder="Ask about ${esc(w.app.title.toLowerCase())}…"></textarea><button class="cp-send">↑</button></div>`;
  const feedEl=panel.querySelector('.cp-feed');
  const input=panel.querySelector('.cp-in');
  const sendBtn2=panel.querySelector('.cp-send');
  const startersEl=panel.querySelector('.cp-starters');
  // starters: the panel invites action the moment it opens
  startersEl.innerHTML=copilotStarters(w.id).map(s=>`<button class="cp-chip">${esc(s)}</button>`).join('');
  startersEl.querySelectorAll('.cp-chip').forEach(b=>b.onclick=()=>{input.value=b.textContent;go()});
  panel.querySelector('.cp-open').onclick=()=>{
    if(COPILOT.cids[w.id]){openApp('chat');openConv(COPILOT.cids[w.id])}
    else{openApp('chat')}
  };
  // prior thread: compact replay of the persistent per-app conversation
  const cid=await copilotThread(w.id,w.app.title);
  if(cid){
    try{
      const d=await (await fetch('/api/conversations/'+cid)).json();
      const msgs=(d.messages||[]).slice(-12);
      feedEl.innerHTML=msgs.map(m=>m.role==='user'
        ?`<div class="mf-user">${esc(m.content)}</div>`
        :m.role==='assistant'?`<div class="mf-body body">${md(m.content||'')}</div>`:'').join('');
      feedEl.scrollTop=feedEl.scrollHeight;
    }catch(e){}
    // re-attach to a live turn — and say so at once, rather than looking idle
    // until the next event happens to arrive
    if(RUNNING.has(cid)){const s=mkSink();sinkOn(cid,s);s.start({conversation_id:cid})}
  }
  let live=null;
  const setBusy=on=>{
    sendBtn2.textContent=on?'◼':'↑';
    sendBtn2.classList.toggle('stop',on);
    sendBtn2.title=on?'Stop this agent':'Send';
  };
  function mkSink(){
    if(live)return live;
    live=miniFeed(feedEl,{scrollEl:feedEl,
      onStart:()=>setBusy(true),
      onTool:()=>{clearTimeout(panel._rt);panel._rt=setTimeout(()=>refreshApp(w.id),450)},
      onEnd:()=>{live=null;setBusy(false);startersEl.style.display='none'}});
    return live;
  }
  function go(){
    const text=input.value.trim();if(!text)return;
    input.value='';
    feedEl.insertAdjacentHTML('beforeend',`<div class="mf-user">${esc(text)}</div>`);
    // the starters were an invitation; leaving them under a question in flight
    // is the panel still offering to begin something it has already begun
    startersEl.style.display='none';
    feedEl.scrollTop=feedEl.scrollHeight;
    const sink=mkSink();
    agentTurn({text,cid:COPILOT.cids[w.id]||null,origin:'copilot:'+w.id,
      title:'✦ '+w.app.title,context:copilotContext(w),sink,
      onCid:id=>{COPILOT.cids[w.id]=id}});
  }
  sendBtn2.onclick=()=>{
    const cid=COPILOT.cids[w.id];
    if(cid&&RUNNING.has(cid)){stopAgent(cid);toast('stopping…');return}   // ◼ while it works
    go();
  };
  input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();go()}});
}
