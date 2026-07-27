/* ================= omnibar: the always-present prompt bar =================
   The OS's one prompt surface. It sits above the dock permanently and is the
   launcher too: Ctrl+Space (or Ctrl+K / Alt+Space) pops it — bar grows, results
   list rises above it, input focused and selected. Typing filters direct
   actions (intent grammar) + apps; Enter runs the highlighted row, or asks the
   agent when the row is "Ask …". Answers stream into cards above the bar. */
const OMNI={cid:null,matches:[],idx:0,pop:false};

function omniPresence(){
  const orb=$('#omni-orb'),inp=$('#omni-in');if(!orb)return;
  const n=RUNNING.size;
  orb.classList.toggle('busy',n>0);
  if(inp&&!inp.value&&document.activeElement!==inp)
    inp.placeholder=n>0?`${agentName()} is working${n>1?' ('+n+' turns)':''}…`
                       :`Ask ${agentName()} anything — or press Ctrl+Space`;
}
/* ---- pop: the launcher state. Pure state — it never re-selects text, so
   popping open as you type can't swallow the next keystroke. ---- */
function omniPop(on){
  const bar=$('#omnibar'),inp=$('#omni-in');if(!bar)return;
  on=!!on;
  const changed=on!==OMNI.pop;
  OMNI.pop=on;
  bar.classList.toggle('pop',on);
  document.body.classList.toggle('omni-pop',on);
  if(on){
    if(document.activeElement!==inp)inp.focus();
    omniRender(inp.value);
    if(changed)Motion.run(bar,[{transform:'translateX(-50%) scale(.97)'},{transform:'translateX(-50%) scale(1)'}],
      {duration:180,easing:EASE.spring});
  }else{
    $('#omnilist').classList.remove('on');
    OMNI.matches=[];OMNI.idx=0;
  }
}
/* the hotkey entry point (Ctrl+Space / Ctrl+K / Alt+Space): focus, select what's
   there so you can just retype, and show the list */
function omniFocus(){
  const inp=$('#omni-in');if(!inp)return;
  inp.focus();inp.select();
  omniPop(true);
}
function omniOpen(){return OMNI.pop}

/* ---- the results list (direct actions first, then apps, then "ask") ---- */
function omniRender(q){
  const list=$('#omnilist');if(!list)return;
  q=(q||'').trim();
  const items=typeof palActions==='function'?palActions():[];
  const direct=q&&typeof palIntent==='function'?palIntent(q):[];
  const fuzzy=q?items.map(it=>({it,s:palScore(q,it.label+' '+(it.hint||''))})).filter(x=>x.s>0)
      .sort((a,b)=>b.s-a.s).map(x=>x.it).slice(0,Math.max(3,7-direct.length)):items.slice(0,7);
  OMNI.matches=[...direct,...fuzzy];
  if(q)OMNI.matches.push({icon:'▲',label:`Ask ${agentName()}: “${q}”`,hint:'send to the agent',ask:true,
    run:()=>omniAsk(q)});
  // a command gets run by Enter; a question gets asked — highlight accordingly
  OMNI.idx=direct.length?0:(q?OMNI.matches.length-1:0);
  omniPaint();
  if(q&&!direct.length&&typeof palIntentAsync==='function')palIntentAsync(q);
}
function omniPaint(){
  const list=$('#omnilist');if(!list)return;
  if(!OMNI.matches.length){list.classList.remove('on');list.innerHTML='';return}
  list.innerHTML=OMNI.matches.map((it,i)=>`<div class="palitem${i===OMNI.idx?' sel':''}${it.intent?' act':''}${it.ask?' ask':''}" data-i="${i}">
    ${it.id?appIcon(it.id,32):it.nat?nativeIcon(it.nat,32):`<span class="pi">${it.icon||'▸'}</span>`}<span><div class="pl">${esc(it.label)}</div><div class="ph">${esc(it.hint||'')}</div></span></div>`).join('');
  list.classList.add('on');
  list.querySelectorAll('.palitem').forEach(el=>{
    el.onmousedown=e=>{e.preventDefault();omniRun(+el.dataset.i)};      // keep focus in the input
    el.onmousemove=()=>{OMNI.idx=+el.dataset.i;
      list.querySelectorAll('.palitem').forEach((x,i)=>x.classList.toggle('sel',i===OMNI.idx))};
  });
}
function omniRun(i){
  const it=OMNI.matches[i!==undefined?i:OMNI.idx];
  if(!it)return omniAsk($('#omni-in').value);
  $('#omni-in').value='';
  omniPop(false);
  it.run();
}
/* palIntentAsync (model-classified fallback) appends into whichever list is live */
function palRenderList(){omniPaint()}

async function omniThread(){
  if(OMNI.cid)return OMNI.cid;
  try{
    const d=await (await fetch('/api/conversations')).json();
    const hit=(d.conversations||[]).find(c=>c.origin==='omni');
    if(hit)OMNI.cid=hit.id;
  }catch(e){}
  return OMNI.cid;
}
function omniCard(question){
  const wrap=$('#omnicards');
  const card=document.createElement('div');card.className='ocard';
  card.innerHTML=`<div class="oc-q">${esc(question)}</div><div class="oc-feed"></div>
    <div class="oc-tools"><button class="oc-chat">Open in Chat</button><button class="oc-x">✕</button></div>`;
  wrap.appendChild(card);
  while(wrap.children.length>3)wrap.firstChild.remove();
  popIn(card,{origin:'bottom'});
  const close=()=>{popOut(card,()=>card.remove())};
  card.querySelector('.oc-x').onclick=close;
  card.querySelector('.oc-chat').onclick=()=>{if(OMNI.cid){openApp('chat');openConv(OMNI.cid)}else openApp('chat');close()};
  return {card,feed:card.querySelector('.oc-feed'),close};
}
function omniContext(){
  const open=[];WM.wins.forEach(w=>{if(!w.min)open.push(w.app.title)});
  return [
    `You are ${agentName()}, answering from the AgentOS omnibar — the always-present prompt bar on the desktop.`,
    `The user asked in passing; be FAST and BRIEF (1-3 sentences unless asked for more), and prefer acting`,
    `through tools over explaining. This is the persistent Desktop thread.`,
    open.length?`Open right now: ${open.join(', ')}. Current desktop ${curDesk}/${DESKS}, theme ${CURRENT_THEME}.`:'',
  ].filter(Boolean).join('\n');
}
async function omniAsk(q){
  q=(q||'').trim();if(!q)return;
  const inp=$('#omni-in');inp.value='';
  omniPop(false);
  await omniThread();
  const {card,feed,close}=omniCard(q);
  const sink=miniFeed(feed,{scrollEl:feed,onEnd:()=>{
    // linger, then fade — unless the pointer is on it or an approval is pending
    setTimeout(()=>{if(card.isConnected&&!card.matches(':hover')&&!card.querySelector('.approval:not(.resolved)'))close()},30000);
  }});
  const ok=agentTurn({text:q,cid:OMNI.cid,origin:'omni',title:'◉ Desktop',
    context:omniContext(),sink,onCid:id=>{OMNI.cid=id}});
  if(!ok)close();
}
(function(){
  const inp=$('#omni-in'),bar=$('#omnibar');if(!inp)return;
  $('#omni-mic').innerHTML=svgMic(13);
  $('#omni-mic').onmousedown=e=>{e.preventDefault();jarvisMode(true)};
  $('#omni-chat').onmousedown=e=>{e.preventDefault();openApp('chat');if(OMNI.cid)openConv(OMNI.cid)};
  // clicking anywhere on the bar puts the caret in it
  bar.addEventListener('mousedown',e=>{if(!e.target.closest('button')&&e.target!==inp){e.preventDefault();omniFocus()}});
  // typing opens the launcher; clearing it collapses back to the bare bar
  inp.addEventListener('input',()=>{if(inp.value.trim())omniPop(true);else if(OMNI.pop)omniRender('')});
  inp.addEventListener('keydown',e=>{
    if(e.key==='ArrowDown'){e.preventDefault();OMNI.idx=Math.min(OMNI.idx+1,OMNI.matches.length-1);omniPaint();return}
    if(e.key==='ArrowUp'){e.preventDefault();OMNI.idx=Math.max(OMNI.idx-1,0);omniPaint();return}
    if(e.key==='Tab'&&OMNI.matches.length){e.preventDefault();omniRun();return}
    if(e.key==='Enter'){e.preventDefault();
      if(OMNI.matches.length)omniRun();else omniAsk(inp.value);
      return}
    if(e.key==='Escape'){e.preventDefault();inp.value='';omniPop(false);inp.blur()}
  });
  // clicking away collapses the launcher (the bar itself stays, always)
  document.addEventListener('mousedown',e=>{
    if(OMNI.pop&&!e.target.closest('#omnibar')&&!e.target.closest('#omnilist'))omniPop(false);
  });
  // type-anywhere: printable keys with no text field focused land in the bar
  document.addEventListener('keydown',e=>{
    if(e.ctrlKey||e.metaKey||e.altKey)return;
    if(e.key.length!==1)return;                                   // printable only
    const t=document.activeElement;
    if(t&&(/^(input|textarea|select)$/i.test(t.tagName)||t.isContentEditable))return;
    if(e.target.closest&&(e.target.closest('.xterm')||e.target.closest('#setup-wiz')))return;
    inp.focus();                                                  // the keypress lands in the bar
  });
  omniPresence();
  setInterval(omniPresence,4000);
})();
