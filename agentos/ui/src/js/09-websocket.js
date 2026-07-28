/* ================= websocket ================= */
function connect(){
  ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');
  ws.onopen=()=>{setStatus(true);if(sendBtn&&input)sendBtn.disabled=!input.value.trim()};
  ws.onclose=()=>{setStatus(false);setRunning(false);RUNNING.clear();for(const k in STREAMS)delete STREAMS[k];
    removeWorking(); // never leave "thinking…" on screen with no live socket behind it
    if(window.STUDIO&&STUDIO.building)studioLog('<span class="mut">connection lost — reconnecting…</span>');
    setTimeout(connect,1500)};
  ws.onmessage=e=>handle(JSON.parse(e.data));
}
function setStatus(on){
  $('#statdot').classList.toggle('on',on);
  $('#smdot').style.background=on?'var(--ok)':'var(--err)';
  $('#smstat').textContent=on?'online · '+location.host:'reconnecting…';
}
/* ---- shell command channel: the agent (via the server) drives THIS desktop.
   Every shell_cmd is answered with POST /api/shell/result {id, ok, data}. ---- */
function shellResolveApp(t){
  t=String(t||'').toLowerCase().trim();
  if(!t)return null;
  if(APPS[t])return t;
  for(const id in APPS)if(APPS[id].title.toLowerCase()===t)return id;
  for(const id in APPS)if(APPS[id].title.toLowerCase().includes(t)||id.toLowerCase().includes(t))return id;
  return null;
}
async function shellCmd(ev){
  let ok=true,data=null;
  const target=ev.args&&ev.args.target;
  try{
    switch(ev.action){
      case 'open_app':{
        const id=shellResolveApp(target);
        if(!id)throw `no AgentOS app matches "${target}"`;
        openApp(id);data=`opened ${APPS[id].title}`;break}
      case 'close_app':{
        const id=shellResolveApp(target);
        const ws=id?winsOf(id):[];
        if(!ws.length)throw `no open window for "${target}"`;
        ws.forEach(w=>closeWin(w));data=`closed ${ws.length} ${id} window${ws.length>1?'s':''}`;break}
      case 'focus_app':{
        const id=shellResolveApp(target);
        const w=id?winsOf(id)[0]:null;
        if(!w)throw `no open window for "${target}"`;
        if(w.desk!==curDesk)switchDesk(w.desk);
        if(w.min)restoreWin(w);focusWin(w);data=`focused ${w.app.title}`;break}
      case 'switch_desktop':{
        const n=parseInt(target,10);
        if(!(n>=1&&n<=DESKS))throw `desktop ${target} doesn't exist (1–${DESKS})`;
        switchDesk(n);data=`on desktop ${n}`;break}
      case 'apply_theme':{
        const all=allThemes(), q=String(target||'').toLowerCase().trim();
        const id=Object.keys(all).find(k=>k.toLowerCase()===q)
          ||Object.keys(all).find(k=>(all[k].name||'').toLowerCase()===q)
          ||Object.keys(all).find(k=>k.toLowerCase().includes(q));
        if(!id)throw `no theme called "${target}" — themes: ${Object.keys(all).join(', ')}`;
        applyTheme(id);data=`theme is now ${id}`;break}
      case 'shell_action':{            // a compositor keybinding reached the shell
        if(typeof scRun!=='function'||!scRun(String(target)))throw `unknown action "${target}"`;
        data=`ran ${target}`;break}
      case 'list_open_apps':{
        const arr=[];WM.wins.forEach(w=>arr.push({app:w.id,title:w.app.title,minimized:w.min,maximized:w.max,desktop:w.desk,active:w.el.classList.contains('active')}));
        data={open:arr,current_desktop:curDesk,desktops:DESKS,theme:CURRENT_THEME};break}
      default: throw `unknown shell action "${ev.action}"`;
    }
  }catch(e){ok=false;data=String(e)}
  if(!ok&&!ev.id)toast(String(data));   // palette-suggested actions surface their failure locally
  if(ev.id)try{await fetch('/api/shell/result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:ev.id,ok,data})})}catch(e){}
}

/* ---- chat-event sinks: any surface (omnibar, copilot panels) can render a
   conversation's live stream by registering a handler here. The Chat window
   keeps its inline path below; sinks are additive — buffering into STREAMS
   still happens so opening the conversation in Chat mid-turn stays lossless. */
const CHAT_SINKS=new Map();   // conversation_id -> {start,delta,thinking,toolStart,toolEnd,status,approval,error,end}
function sinkOn(cid,sink){if(cid)CHAT_SINKS.set(cid,sink)}
function sinkOff(cid){CHAT_SINKS.delete(cid)}
/* one approval card builder for every surface (Chat inline, floating, sinks) */
function buildApprovalBox(ev,cur){
  const box=document.createElement('div');box.className='approval';box.id='ap-'+ev.id;
  const detail=ev.name==='run_command'?(ev.args.command||''):(ev.name+' '+JSON.stringify(ev.args,null,1));
  const who=ev.offer?permPrincipalLabel(ev.offer.principal_kind,ev.offer.principal_id):'';
  box.innerHTML=`<div class="atitle">Approval needed${who?' · '+esc(who):''}${cur?'':' · another chat'}</div><div class="acmd">${esc(detail)}</div><div class="areason">${esc(ev.reason||'')}</div><div class="btns"><button class="allow">Allow</button><button class="deny">Deny</button><button class="deny always">${ev.offer?'Allow &amp; remember':'Always allow'}</button></div>`;
  box.querySelector('.allow').onclick=()=>resolveApproval(ev.id,true);
  box.querySelector('.deny:not(.always)').onclick=()=>resolveApproval(ev.id,false);
  box.querySelector('.always').onclick=async()=>{
    if(ev.offer){ // principal-scoped grant, written server-side; revocable in Permissions
      resolveApproval(ev.id,true,true);
      toast('granted to '+who+': '+ev.offer.action+' '+ev.offer.resource);
    }else{
      const pat=ev.name==='run_command'?('run_command '+((ev.args.command||'').trim().split(/\s+/)[0]||'')+' *'):(ev.name+' *');
      await addPolicy('allow',pat);
      resolveApproval(ev.id,true);
      toast('policy added: always allow "'+pat+'"');
    }
  };
  return box;
}
/* the menu-bar spinner reflects EVERY live turn, not just the visible chat */
function updateSpin(){
  const s=$('#spin');if(!s)return;
  s.classList.toggle('on',RUNNING.size>0||running);
  s.title=RUNNING.size>1?RUNNING.size+' agent turns running':'agent is working';
  if(typeof omniPresence==='function')omniPresence();
  if(typeof aiBubble==='function')aiBubble();
}
/* ---- the AI presence bubble (bottom-right): wherever a turn is running — a
   copilot panel, the omnibar, a background task — it shows here, and one click
   opens that conversation in Agent Chat. ---- */
let AIB={last:null,seen:0};
function aiBubble(){
  let b=$('#aibubble');
  if(!b){
    b=document.createElement('div');b.id='aibubble';
    b.innerHTML='<span class="ab-orb"></span><span class="ab-t"></span><span class="ab-n"></span>'
      +'<button class="ab-stop" title="Stop the agent (Ctrl+.)">◼</button>';
    document.body.appendChild(b);
    b.querySelector('.ab-stop').onclick=e=>{e.stopPropagation();stopAllAgents()};
    b.onclick=()=>{
      const cid=[...RUNNING][0]||AIB.last||currentConv;
      openApp('chat');if(cid)openConv(cid);
      AIB.seen=0;aiBubble();
    };
  }
  const n=RUNNING.size;
  if(n)AIB.last=[...RUNNING][0];
  const label=n?(n>1?`${agentName()} · ${n} turns`:`${agentName()} is working`)
               :(AIB.seen?`${agentName()} replied`:'');
  b.classList.toggle('on',!!(n||AIB.seen));
  b.classList.toggle('busy',!!n);
  b.querySelector('.ab-stop').style.display=n?'':'none';
  b.querySelector('.ab-t').textContent=label;
  const badge=b.querySelector('.ab-n');
  badge.textContent=AIB.seen>1?AIB.seen:'';
  badge.style.display=AIB.seen>1?'':'none';
}

function handle(ev){
  if(ev.type&&ev.type.startsWith('build_')){studioBuildEvent(ev);if(ev.type==='build_thinking')jrPulse=Math.min(1.6,jrPulse+.12);return;}
  const _cid=ev.conversation_id, _cur=!_cid||_cid===currentConv, _s=_cid?STREAMS[_cid]:null;
  const _sk=_cid?CHAT_SINKS.get(_cid):null;
  switch(ev.type){
    case 'state_sync':{ // sent on every (re)connect: what is actually still running
      RUNNING.clear();
      (ev.running||[]).forEach(c=>{RUNNING.add(c);if(!STREAMS[c])STREAMS[c]={html:'',text:''}});
      if(currentConv&&RUNNING.has(currentConv)){setRunning(true);showWorking();}
      else{setRunning(false);removeWorking();}
      updateSpin();
      if(window.STUDIO){
        if(ev.build_running){
          if(!STUDIO.building){STUDIO.building=true;const b=$('#st-build');if(b){b.textContent='Cancel';b.classList.add('stop')}studioTickStart();studioLog('<span class="mut">re-attached to the running build…</span>');}
        }else if(STUDIO.building){studioBuildEnded();studioLog('<span class="mut">the build ended while disconnected — check the app list</span>');if(typeof loadUserApps==='function')loadUserApps();}
      }
      break;}
    case 'status':{ // model-side heartbeat ("loading model / evaluating prompt…")
      if(_sk&&_sk.status)_sk.status(ev);
      if(!_cur)break;
      WORK_MSG=ev.message||'';
      if(running)showWorking();       // keep a live indicator up between/after tool calls
      break;}
    case 'conversation':{
      // omnibar/copilot threads announce themselves with an origin — they must
      // never steal the Chat window's current conversation
      if(typeof claimConversation==='function'&&claimConversation(ev)){loadConvs();break}
      currentConv=ev.id; loadConvs(); break;}
    case 'turn_start':{
      if(_cid){RUNNING.add(_cid);STREAMS[_cid]={html:'',text:''};}
      if(_cur)setRunning(true);
      updateSpin();
      if(_sk&&_sk.start)_sk.start(ev);
      loadConvs(); break;}
    case 'text_delta':{
      if(_s)_s.text+=ev.text;
      if(_sk&&_sk.delta)_sk.delta(ev.text,_s?_s.text:'');
      if(!_cur)break;
      curText+=ev.text;
      WORK_MSG='';removeWorking(); // real text is flowing now — drop the "working" placeholder
      if(JARVIS.busy){const r=$('#j-reply');if(r){r.textContent=curText;r.scrollTop=r.scrollHeight}}
      if(!curBody)startAssistant();
      if(curBody){curBody.innerHTML=md(curText);curBody.style.transform='translateZ(0)';scrollDown()} break;}
    case 'thinking_delta':{
      if(_sk&&_sk.thinking)_sk.thinking(ev.text);
      if(!_cur)break;
      if(!curBody)startAssistant();
      if(!curBody)break;
      if(!curThink){curThink=document.createElement('div');curThink.className='think';curBody.parentNode.insertBefore(curThink,curBody);}
      curThink.textContent+=ev.text; curThink.scrollTop=curThink.scrollHeight; scrollDown(); break;}
    case 'tool_start':{
      const argStr=ev.name==='run_command'?(ev.args.command||''):JSON.stringify(ev.args);
      if(_s){ // mirror into the buffer so switching chats mid-turn is lossless
        if(_s.text.trim())_s.html+='<div class="body">'+md(_s.text)+'</div>';
        _s.text='';
        _s.html+=`<div class="tool" data-buf="1"><div class="head"><span class="tname2">${esc(ev.name)}</span><span class="targ">${esc(argStr)}</span><span class="tstat run" data-b="${ev.call_id}">running</span></div><div class="out"></div></div>`;}
      if(typeof agentHands==='function')agentHands(ev);   // visible hands: glow the affected app
      if(_sk&&_sk.toolStart)_sk.toolStart(ev,argStr);
      if(!_cur)break;
      if(!curBody)startAssistant();
      if(!curBody)break;
      flushText();
      const card=document.createElement('div');card.className='tool';card.id='tc-'+ev.call_id;
      card.innerHTML=`<div class="head"><span class="tname2">${esc(ev.name)}</span><span class="targ">${esc(argStr)}</span><span class="tstat run">${ev.pending_approval?'awaiting approval':'running'}</span></div><div class="out"></div>`;
      card.querySelector('.head').onclick=()=>card.classList.toggle('open');
      curBody.parentNode.insertBefore(card,curBody); scrollDown(); break;}
    case 'tool_end':{
      if(_s)_s.html=_s.html.replace(`class="tstat run" data-b="${ev.call_id}">running`,
        `class="tstat ${ev.ok?'ok':'fail'}" data-b="${ev.call_id}">${ev.ok?'done':'failed'}`);
      if(_sk&&_sk.toolEnd)_sk.toolEnd(ev);
      if(!_cur)break;
      const card=$('#tc-'+ev.call_id);
      if(card){const st=card.querySelector('.tstat');st.className='tstat '+(ev.ok?'ok':'fail');st.textContent=ev.ok?'done':'failed';
        card.querySelector('.out').textContent=ev.output||'(no output)';
        if(!ev.ok)card.classList.add('open');}
      // the model is about to think about this result — often the slowest gap in a
      // turn; keep a live indicator so it never looks frozen (and repaints on macOS)
      if(running){WORK_MSG='';showWorking()}
      scrollDown(); break;}
    case 'approval_request':{
      const box=buildApprovalBox(ev,_cur);
      if(_sk&&_sk.approval&&_sk.approval(box,ev)){ /* the sink placed it */ }
      else if(_cur&&feed){
        if(!curBody)startAssistant();
        if(curBody)curBody.parentNode.insertBefore(box,curBody);
      }else{ // approval from a chat you're not looking at — float it, never deadlock
        box.style.cssText='position:fixed;right:18px;bottom:70px;z-index:9999;max-width:440px;box-shadow:0 18px 50px rgba(0,0,0,.5)';
        document.body.appendChild(box);
        box.addEventListener('click',()=>setTimeout(()=>{if(box.classList.contains('resolved'))box.remove()},1000));
      }
      toast('approval needed'); scrollDown(); break;}
    case 'error':{
      if(_s){if(_s.text.trim()){_s.html+='<div class="body">'+md(_s.text)+'</div>';_s.text='';}
        _s.html+='<div class="errmsg">'+esc(ev.message)+'</div>';}
      if(_sk&&_sk.error){_sk.error(ev);if(!_cur)break}
      if(!_cur){toast('chat error: '+ev.message);break}
      if(!curBody)startAssistant();
      if(!curBody){toast('error: '+ev.message);break}
      flushText();
      const d=document.createElement('div');d.className='errmsg';d.textContent=ev.message;
      curBody.parentNode.insertBefore(d,curBody); scrollDown(); break;}
    case 'turn_end':{
      if(_cid){RUNNING.delete(_cid);delete STREAMS[_cid];agentQueueFlush(_cid);}
      updateSpin();
      if(!_cur){AIB.seen++;setTimeout(()=>{if(!RUNNING.size){AIB.seen=0;aiBubble()}},20000)}
      if(_sk&&_sk.end){_sk.end(ev);if(!_cur){aiBubble();loadConvs();break}}
      if(!_cur){aiBubble();loadConvs();break}
      removeWorking();const reply=curText;
      if(JARVIS.on&&JARVIS.busy){JARVIS.busy=false;jarvisSpeakAndListen(reply);}
      else speak(reply);
      setRunning(false); curBody=null; curThink=null; curText=''; loadConvs(); break;}
    case 'task_started': toast('background task running…'); break;
    case 'task_finished': toast('task done: '+(ev.result||'').slice(0,80)); loadConvs(); break;
    case 'control':    // a hardware key changed volume/brightness — show it at once
      updateTray();refreshApp('control');
      if(ev.volume!==undefined)toast('volume '+ev.volume+'%'+(ev.muted?' (muted)':''));
      else if(ev.brightness!==undefined)toast('brightness '+ev.brightness+'%');
      break;
    case 'platform':   // the compositor appeared (or went away) — re-read what we can do
      loadPlatform().then(()=>{updateNativeWindows();refreshApp('syssettings');refreshApp('control')});
      break;
    case 'wallpaper': loadWallpaper(); toast('wallpaper updated'); break;
    case 'shell_cmd': shellCmd(ev); break;   // the agent's hands on this desktop (contract: server shell_command())
    case 'briefing': showBriefing(ev); break;        // "while you were away" — OS-initiated
    case 'suggestion': showSuggestion(ev); break;    // at most one proactive idea at a time
    case 'config': loadConfig().then(()=>{loadModels()}); toast('configuration updated'); refreshApp('policies'); refreshApp('mcp'); break;
    case 'telegram_chats': refreshApp('telegram'); break;
    case 'knowledge_update': refreshApp('memory'); refreshApp('kg'); refreshApp('profile'); break;
    case 'fabric_event': fabricLiveRefresh(); break;
    case 'fabric_defs': refreshApp('fabric'); break;
    case 'setup': location.reload(); break;
    case 'apps': loadUserApps(); refreshApp('studio'); toast('app library updated'); break;
    case 'grants': refreshApp('permissions'); if(ev.revoked)reloadAppFrames(); break;
    case 'widgets': if(Date.now()>widgetEchoUntil)loadWidgets(); break;
    case 'snapshots': refreshApp('snapshots'); break;
    case 'themes': loadThemes().then(()=>refreshApp('themes')); break;
    case 'automations': loadAutomations().then(()=>refreshApp('automations')); break;
    // the server never runs an automation itself — it says "run this" and the
    // desktop does, so a schedule, the agent's tool and the palette all land in
    // the same runner
    case 'automation.run': onAutomationBroadcast(ev.automation); break;
    case 'theme_apply':{const t=ev.theme;if(t){if(t.name)CUSTOM_THEMES[t.name]=t;applyThemeObj(t);if(t.name){CURRENT_THEME=t.name;localStorage.setItem('theme',t.name)}toast('theme applied: '+(t.name||''));refreshApp('themes')} break;}
    case 'train_setup': TRAIN_SETUP_LISTENERS.forEach(fn=>{try{fn(ev)}catch(e){}}); break;
    case 'hermes_setup': HERMES_SETUP_LISTENERS.forEach(fn=>{try{fn(ev)}catch(e){}}); break;
    case 'files': refreshApp('files'); break;
    case 'models': refreshApp('models'); loadModels(); break;
    case 'model_pull':{const p=$('#mdl-prog');if(p)p.textContent=ev.done?'':(''+ev.name+': '+ev.status);
      if(ev.done){refreshApp('models');toast(''+ev.name+' '+(String(ev.status).startsWith('error')?ev.status:'ready'))} break;}
    case 'telegram_in':{
      toast('Telegram: '+ev.text); jarvisOn(3);
      loadConvs(); if(feed&&currentConv===ev.conversation_id&&!RUNNING.has(currentConv))openConv(currentConv); break;}
    case 'telegram_out':{
      jarvisOff();
      loadConvs(); if(feed&&currentConv===ev.conversation_id&&!RUNNING.has(currentConv))openConv(currentConv); break;}
    case 'wm':{ // compositor event (AgentOS session) — replaces window polling
      if(NATIVE_POLL){clearInterval(NATIVE_POLL);NATIVE_POLL=null}
      clearTimeout(wmDebounce);
      wmDebounce=setTimeout(()=>{updateNativeWindows();
        if(ev.event==='output'||ev.event==='workspace')refreshApp('syssettings')},120);
      break;}
    case 'notification':{ // a native app's notification, via our own daemon
      toast((ev.app?ev.app+': ':'')+ev.summary); updateBell(); break;}
    case 'notification_center': updateBell(); break;
  }
  if(ev.type==='thinking_delta')jrPulse=Math.min(1.6,jrPulse+.12);
}
function resolveApproval(id,approved,remember){
  ws.send(JSON.stringify({type:'approval',id,approved,remember:!!remember}));
  const box=$('#ap-'+id); if(box){box.classList.add('resolved');
    box.querySelector('.atitle').textContent=approved?'✓ Allowed':'✕ Denied';}
}
function permPrincipalLabel(kind,id){
  if(kind==='app'){const a=(USERAPPS||[]).find(x=>x.id===id);return 'app "'+(a?a.name:id)+'"';}
  return kind+(id?' "'+id+'"':'');
}
function flushText(){
  if(curText.trim()&&curBody){const d=document.createElement('div');d.className='body';d.innerHTML=md(curText);
    curBody.parentNode.insertBefore(d,curBody);}
  curText=''; if(curBody)curBody.innerHTML='';
}
function startAssistant(){
  if(!feed)return;
  removeWorking();
  $('#welcome')?.remove();
  const m=document.createElement('div');m.className='msg assistant';
  m.innerHTML='<div class="who">▲ '+esc(agentName())+'</div>';
  curBody=document.createElement('div');curBody.className='body';
  m.appendChild(curBody);feed.appendChild(m);curThink=null;
}

