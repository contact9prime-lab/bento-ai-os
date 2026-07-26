/* ================= chat app ================= */
function renderChat(body){
  body.innerHTML=`<div class="chatwrap">
    <div class="cside">
      <button id="newchat">＋ New chat</button>
      <div id="convs"></div>
    </div>
    <div class="cmain">
      <div id="topbar">
        <select id="modelsel" title="Model"></select>
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
        <div id="combox">
          <textarea id="input" rows="1" placeholder="Ask, tell it what to do, paste an image — or @subagent to address a team member directly"></textarea>
          <button id="mic" title="dictate (mic)"></button>
          <button id="send" disabled>➤</button>
        </div>
      </div>
    </div>
  </div>`;
  feed=$('#feed');chatEl=$('#chat');input=$('#input');sendBtn=$('#send');
  sendBtn.onclick=send;
  input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});
  input.addEventListener('input',()=>{input.style.height='auto';input.style.height=Math.min(input.scrollHeight,160)+'px';if(!running)sendBtn.disabled=!input.value.trim()&&!PENDING_IMGS.length});
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
  $('#modelsel').onchange=()=>{const v=$('#modelsel').value;
    // 'hermes' is a per-turn engine choice, not a model — never persist it as the
    // global default (background tasks call the provider with default_model)
    if(v==='hermes'){toast('this chat now uses the Hermes engine');return}
    fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({default_model:v})});};
  $('#autosel').onchange=()=>fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({autonomy:$('#autosel').value})});
  loadModels();loadConfig();loadConvs();
  if(currentConv)openConv(currentConv);else showWelcome();
  setRunning(RUNNING.has(currentConv));
}
function setRunning(r){running=r;
  $('#spin').classList.toggle('on',r);
  if(r)jarvisOn();else jarvisOff();
  if(!sendBtn)return;
  sendBtn.classList.toggle('stop',r);
  sendBtn.textContent=r?'◼':'➤';
  sendBtn.disabled=r?false:(!input.value.trim()&&!PENDING_IMGS.length);
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
  if(!PENDING_IMGS.length){a?.remove();if(sendBtn&&!running)sendBtn.disabled=!input.value.trim();return}
  if(!a){a=document.createElement('div');a.id='attach';const cb=$('#combox');cb.parentNode.insertBefore(a,cb)}
  a.innerHTML=PENDING_IMGS.map((u,i)=>`<div class="att"><img src="${u}"><button onclick="rmAttach(${i})" title="remove">×</button></div>`).join('');
  if(sendBtn&&!running)sendBtn.disabled=false;
}
function rmAttach(i){PENDING_IMGS.splice(i,1);renderAttach()}
function send(){
  if(running){ws.send(JSON.stringify({type:'abort',conversation_id:currentConv}));return}
  const text=input.value.trim();const imgs=PENDING_IMGS.slice();
  if((!text&&!imgs.length)||!ws||ws.readyState!==1)return;
  $('#welcome')?.remove();
  const m=document.createElement('div');m.className='msg user';
  m.innerHTML='<div class="who">you</div><div class="bubble"></div>';
  m.querySelector('.bubble').textContent=text;
  bubbleImgs(m.querySelector('.bubble'),imgs);
  feed.appendChild(m);
  showWorking();scrollDown();
  ws.send(JSON.stringify({type:'chat',text,images:imgs,conversation_id:currentConv,model:$('#modelsel').value}));
  input.value='';input.style.height='auto';PENDING_IMGS=[];renderAttach();setRunning(true);
}
let WORK_TICK=null, WORK_T0=0, WORK_MSG='';
function showWorking(){
  if(!feed)return;
  if(!$('#working')){
    const w=document.createElement('div');w.className='working';w.id='working';
    w.innerHTML=`<div class="orb"></div><div class="wtxt">${esc(agentName())} is working</div><div class="dots"><i></i><i></i><i></i></div><div class="wsub" style="font-size:11px;opacity:.6;margin-left:8px"></div>`;
    feed.appendChild(w);
  }
  WORK_T0=WORK_T0||Date.now();
  if(!WORK_TICK)WORK_TICK=setInterval(tickWorking,1000);
}
function tickWorking(){
  const w=$('#working'); if(!w){clearInterval(WORK_TICK);WORK_TICK=null;return}
  const s=Math.round((Date.now()-WORK_T0)/1000);
  const sub=w.querySelector('.wsub');
  if(sub)sub.textContent=WORK_MSG||(s>3?(s>=60?Math.floor(s/60)+'m '+(s%60)+'s':s+'s')+' · working…':'');
  // a visible per-second mutation forces the compositor to repaint — this is what
  // switching tabs was doing manually on macOS to make streamed text appear
  w.style.opacity=(0.999+(s%2)*0.001);
  scrollDown();
}
function removeWorking(){
  $('#working')?.remove();
  if(WORK_TICK){clearInterval(WORK_TICK);WORK_TICK=null}
  WORK_T0=0;WORK_MSG='';
}
async function loadConvs(){
  const box=$('#convs'); if(!box)return;
  const r=await fetch('/api/conversations');const d=await r.json();
  if(!$('#convs'))return;
  box.innerHTML='';
  d.conversations.forEach(c=>{
    const el=document.createElement('div');el.className='conv'+(c.id===currentConv?' active':'');
    el.innerHTML=`<span class="t"></span><button class="del">✕</button>`;
    el.querySelector('.t').textContent=(RUNNING.has(c.id)?'● ':'')+(c.title||'untitled');
    if(RUNNING.has(c.id))el.querySelector('.t').style.color='var(--acc,#5eead4)';
    el.onclick=e=>{if(!e.target.classList.contains('del'))openConv(c.id)};
    el.querySelector('.del').onclick=async e=>{e.stopPropagation();
      if(RUNNING.has(c.id))return toast('that chat has a turn running — stop it first');
      await fetch('/api/conversations/'+c.id,{method:'DELETE'});
      if(currentConv===c.id)newChat(); else loadConvs();};
    box.appendChild(el);
  });
}
async function openConv(cid){
  currentConv=cid;
  const r=await fetch('/api/conversations/'+cid);const d=await r.json();
  if(!feed)return;
  curBody=null;curThink=null;curText='';
  feed.innerHTML='';
  d.messages.forEach(msg=>{
    const m=document.createElement('div');m.className='msg '+msg.role;
    if(msg.role==='user'){m.innerHTML='<div class="who">you</div><div class="bubble"></div>';const bb=m.querySelector('.bubble');bb.textContent=msg.content;bubbleImgs(bb,msg.meta?.images);}
    else{m.innerHTML='<div class="who">▲ '+esc(agentName())+'</div>';
      (msg.meta?.steps||[]).forEach(s=>{
        if(s.type==='tool'){const card=document.createElement('div');card.className='tool';
          const argStr=s.name==='run_command'?(s.args.command||''):JSON.stringify(s.args);
          card.innerHTML=`<div class="head"><span class="tname2">${esc(s.name)}</span><span class="targ">${esc(argStr)}</span><span class="tstat ${s.ok?'ok':'fail'}">${s.ok?'done':'failed'}</span></div><div class="out"></div>`;
          card.querySelector('.out').textContent=s.output||'';
          card.querySelector('.head').onclick=()=>card.classList.toggle('open');
          m.appendChild(card);}
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
  loadConvs();scrollDown();
}
function newChat(){
  currentConv=null;curBody=null;curThink=null;curText='';
  if(feed){feed.innerHTML='';showWelcome()}
  setRunning(false);
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
  try{
    const r=await fetch('/api/models');const d=await r.json();
    const sel=$('#modelsel');if(!sel)return;
    const prev=sel.value;
    sel.innerHTML='';
    // Engine choice: the built-in agent (Aria, model-backed) or Hermes as the backend
    let hermesOn=false;
    try{const h=await (await fetch('/api/hermes/status')).json();hermesOn=h.installed&&h.engine_enabled!==false}catch(e){}
    if(d.models.length){
      const g=document.createElement('optgroup');g.label='Aria (built-in agent) — model';
      d.models.forEach(m=>{const o=document.createElement('option');o.value=m.id;
        o.textContent=m.name+' · '+m.provider+(m.provider==='ollama'?' (local)':'');g.appendChild(o)});
      sel.appendChild(g);
    }else if(!hermesOn){sel.innerHTML='<option value="">no models — check Settings</option>';return}
    if(hermesOn){
      const g=document.createElement('optgroup');g.label='Other engine';
      const o=document.createElement('option');o.value='hermes';o.textContent='🜁 Hermes agent';
      g.appendChild(o);sel.appendChild(g);
    }
    // keep the prior choice if still present, else the config default, else first model
    const has=v=>[...sel.options].some(o=>o.value===v);
    sel.value=has(prev)?prev:(d.default&&has(d.default)?d.default:(d.models[0]?d.models[0].id:'hermes'));
  }catch(e){}
}
async function loadConfig(){
  const r=await fetch('/api/config');cfg=await r.json();
  if($('#autosel'))$('#autosel').value=cfg.autonomy;
  // wallpaper presets live in config, so the wallpaper may only be resolvable now
  if(cfg&&cfg.desktop&&cfg.desktop.wallpaper_preset&&!$('#wall').classList.contains('has'))loadWallpaper();
}

