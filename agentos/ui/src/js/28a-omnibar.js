/* ================= omnibar: the always-present prompt bar =================
   The OS's one prompt surface. It sits above the dock permanently and is the
   launcher too: Ctrl+Space (or Ctrl+K / Alt+Space) pops it — bar grows, results
   list rises above it, input focused and selected. Typing filters direct
   actions (intent grammar) + apps; Enter runs the highlighted row, or asks the
   agent when the row is "Ask …". Answers stream into cards above the bar. */
const OMNI={cid:null,matches:[],idx:0,pop:false,imgs:[]};

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
    if(!OMNI.imgs.length&&!$('#omnicards').children.length)omniSummon(false);
  }
}
/* the hotkey entry point (Ctrl+Space / Ctrl+K / Alt+Space): focus, select what's
   there so you can just retype, and show the list */
function omniSummon(on){
  const bar=$('#omnibar');if(!bar)return;
  bar.classList.toggle('summoned',on!==false);
}
function omniFocus(){
  const inp=$('#omni-in');if(!inp)return;
  omniSummon(true);                       // come to the front, over any window
  inp.focus();inp.select();
  omniPop(true);
}
function omniOpen(){return OMNI.pop}

/* ---- the results list (direct actions first, then apps, then "ask") ----
   Ranking rules that keep it a LAUNCHER, not a search box:
   - the name is what matters; a hint only counts as a whole-word match
   - when anything matches by prefix/substring, scattered-letter matches are
     dropped entirely (they are what turned "logs" into "Clipboard Manager")
   - AgentOS apps outrank built-in actions, which outrank host apps */
function omniScore(q,it){
  const ql=q.toLowerCase();
  const t=palScore(q,it.label);                       // 3 prefix · 2 substring · 1 scattered
  if(t>=2)return t;
  if((it.hint||'').toLowerCase().includes(ql))return 1.5;
  return t;                                           // 1 (scattered) or 0
}
function omniRender(q){
  const list=$('#omnilist');if(!list)return;
  q=(q||'').trim();
  const items=typeof palActions==='function'?palActions():[];
  const direct=q&&typeof palIntent==='function'?palIntent(q):[];
  let fuzzy;
  if(q){
    const scored=items.map(it=>({it,s:omniScore(q,it)})).filter(x=>x.s>0);
    const best=scored.reduce((m,x)=>Math.max(m,x.s),0);
    const kept=best>=1.5?scored.filter(x=>x.s>=1.5):scored;     // drop the scattered tail
    const rank=x=>x.s+(x.it.id?0.4:x.it.nat?0:0.2);             // apps > actions > host apps
    fuzzy=kept.sort((a,b)=>rank(b)-rank(a)).slice(0,Math.max(3,7-direct.length));
    fuzzy.forEach(x=>x.it._t=x.s);
    fuzzy=fuzzy.map(x=>x.it);
  }else fuzzy=items.slice(0,7);
  OMNI.matches=[...direct,...fuzzy];
  if(q)OMNI.matches.push({icon:'▲',label:`Ask ${agentName()}: “${q}”`,hint:'send to the agent · ⇧⏎',
    ask:true,run:()=>omniAsk(q)});
  OMNI.idx=omniDefaultIdx(q,direct);
  omniPaint();
  if(q&&!direct.length&&typeof palIntentAsync==='function')palIntentAsync(q);
}
/* What should Enter do? Launch, unless the query reads like something to ask. */
function omniDefaultIdx(q,direct){
  if(!q)return 0;
  if(direct.length)return 0;                                    // a command → run it
  const top=OMNI.matches[0];
  const words=q.split(/\s+/).length;
  const asks=/\?$/.test(q)||/^(what|who|why|how|when|where|is|are|can|should|do|does|tell|explain|summar|write|find out)\b/i.test(q);
  if(top&&!top.ask&&(top._t>=2)&&words<=3&&!asks)return 0;       // a name → launch it
  return OMNI.matches.length-1;                                 // otherwise → ask
}
function omniPaint(){
  const list=$('#omnilist');if(!list)return;
  if(!OMNI.matches.length){list.classList.remove('on');list.innerHTML='';return}
  list.innerHTML=OMNI.matches.map((it,i)=>`<div class="palitem${i===OMNI.idx?' sel':''}${it.intent?' act':''}${it.ask?' ask':''}" data-i="${i}">
    ${it.id?appIcon(it.id,32):it.nat?nativeIcon(it.nat,32):`<span class="pi">${it.icon||'▸'}</span>`}<span class="ptext"><div class="pl">${esc(it.label)}</div><div class="ph">${esc(it.hint||'')}</div></span>
    ${i<9?`<kbd class="ok">alt+${i+1}</kbd>`:''}</div>`).join('')
    +`<div class="omni-hint"><span><kbd>⏎</kbd> ${OMNI.matches[OMNI.idx]&&OMNI.matches[OMNI.idx].ask?'ask':'launch'}</span><span><kbd>⇧⏎</kbd> ask</span><span><kbd>alt+1…9</kbd> quick launch</span><span><kbd>↑↓</kbd> pick</span></div>`;
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
    <div class="oc-tools"><button class="oc-stopnow" style="display:none">◼ Stop</button>
      <button class="oc-chat">Open in Chat</button><button class="oc-x">✕</button></div>`;
  wrap.appendChild(card);
  wrap.classList.add('raised');
  while(wrap.children.length>3)wrap.firstChild.remove();
  popIn(card,{origin:'bottom'});
  const close=()=>{popOut(card,()=>{card.remove();
    if(!wrap.children.length){wrap.classList.remove('raised');if(!OMNI.pop)omniSummon(false)}})};
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
/* ---- attachments: a screenshot is often the whole question ---- */
function omniShots(){
  let box=$('#omni-shots');
  if(!box){box=document.createElement('div');box.id='omni-shots';$('#omnibar').appendChild(box)}
  box.innerHTML=OMNI.imgs.map((u,i)=>`<span class="oshot"><img src="${u}"><button data-i="${i}" title="Remove">✕</button></span>`).join('');
  box.classList.toggle('on',OMNI.imgs.length>0);
  box.querySelectorAll('button').forEach(b=>b.onclick=e=>{e.stopPropagation();OMNI.imgs.splice(+b.dataset.i,1);omniShots()});
}
function omniAddImage(fileOrUrl){
  const done=u=>{if(OMNI.imgs.length>=4)return toast('up to 4 images');OMNI.imgs.push(u);omniShots()};
  if(typeof fileOrUrl==='string')return done(fileOrUrl);
  const img=new Image();
  img.onload=()=>{   // downscale big screenshots so a turn stays light
    const MAX=1568,sc=Math.min(1,MAX/Math.max(img.width,img.height));
    const c=document.createElement('canvas');
    c.width=Math.round(img.width*sc);c.height=Math.round(img.height*sc);
    c.getContext('2d').drawImage(img,0,0,c.width,c.height);
    done(sc<1||fileOrUrl.size>800000?c.toDataURL('image/jpeg',.9):c.toDataURL('image/png'));
    URL.revokeObjectURL(img.src);
  };
  img.src=URL.createObjectURL(fileOrUrl);
}
async function omniShoot(){
  if(!cap('screen.capture').available)return toast('screen capture is not available here');
  toast('capturing the screen…');
  try{
    const r=await fetch('/api/screenshot',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({area:'full',inline:true})});
    const d=await r.json();
    if(!r.ok||!d.data_url)return toast(d.error||'could not capture the screen');
    omniAddImage(d.data_url);
    omniFocus();
  }catch(e){toast('screenshot failed')}
}
async function omniAsk(q){
  q=(q||'').trim();
  const imgs=OMNI.imgs.slice();
  if(!q&&!imgs.length)return;
  if(!q)q='What do you see here?';
  const inp=$('#omni-in');inp.value='';
  OMNI.imgs=[];omniShots();
  omniPop(false);
  await omniThread();
  const {card,feed,close}=omniCard(q);
  const stopBtn=card.querySelector('.oc-stopnow');
  stopBtn.onclick=()=>{stopAgent(OMNI.cid);stopBtn.textContent='stopping…';stopBtn.disabled=true};
  const sink=miniFeed(feed,{scrollEl:feed,showThinking:false,
    onStart:()=>{stopBtn.style.display='';stopBtn.disabled=false;stopBtn.textContent='◼ Stop'},
    onEnd:()=>{
    stopBtn.style.display='none';
    // linger, then fade — unless the pointer is on it or an approval is pending
    setTimeout(()=>{if(card.isConnected&&!card.matches(':hover')&&!card.querySelector('.approval:not(.resolved)'))close()},30000);
  }});
  const ok=agentTurn({text:q,cid:OMNI.cid,origin:'omni',title:'◉ Desktop',images:imgs,
    context:omniContext(),sink,onCid:id=>{OMNI.cid=id},
    onQueued:stop=>{
      const tools=card.querySelector('.oc-tools');
      if(tools.querySelector('.oc-stop'))return;
      const b=document.createElement('button');b.className='oc-stop';b.textContent='Stop current & send';
      b.onclick=()=>{b.disabled=true;b.textContent='stopping…';stop()};
      tools.prepend(b);
    }});
  if(!ok)close();
}
(function(){
  const inp=$('#omni-in'),bar=$('#omnibar');if(!inp)return;
  $('#omni-mic').innerHTML=svgMic(13);
  const shot=$('#omni-shot');
  if(shot){shot.innerHTML='▣';shot.onmousedown=e=>{e.preventDefault();omniShoot()}}
  // paste or drop an image straight onto the bar
  inp.addEventListener('paste',e=>{
    const items=[...(e.clipboardData?.items||[])].filter(it=>it.type.startsWith('image/'));
    if(!items.length)return;
    e.preventDefault();items.forEach(it=>omniAddImage(it.getAsFile()));
  });
  ['dragover','drop'].forEach(ev=>bar.addEventListener(ev,e=>{
    if(!(e.dataTransfer&&[...(e.dataTransfer.types||[])].includes('Files')))return;
    e.preventDefault();
    if(ev==='drop')[...e.dataTransfer.files].filter(f=>f.type.startsWith('image/')).forEach(omniAddImage);
    bar.classList.toggle('dropping',ev==='dragover');
  }));
  bar.addEventListener('dragleave',()=>bar.classList.remove('dropping'));
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
      if(e.shiftKey){omniAsk(inp.value);return}         // ⇧⏎ always asks the agent
      if(OMNI.matches.length)omniRun();else omniAsk(inp.value);
      return}
    if(e.key==='Escape'){e.preventDefault();inp.value='';omniPop(false);omniSummon(false);inp.blur()}
  });
  // clicking away collapses the launcher (the bar itself stays, always)
  document.addEventListener('mousedown',e=>{
    if(e.target.closest('#omnibar')||e.target.closest('#omnilist')||e.target.closest('#omnicards'))return;
    if(OMNI.pop)omniPop(false);
    if(!$('#omnicards').children.length)omniSummon(false);        // back behind the windows
  });
  /* Double-tap Ctrl summons the bar — hands stay on the keyboard, no chord to learn. */
  let lastCtrl=0;
  document.addEventListener('keyup',e=>{
    if(e.key!=='Control')return;
    const now=Date.now();
    if(now-lastCtrl<450&&!OMNI.pop){lastCtrl=0;omniFocus();return}
    lastCtrl=now;
  });
  document.addEventListener('keydown',e=>{if(e.key!=='Control')lastCtrl=0});   // a chord is not a double-tap
  /* Alt+1…9 — always "launch the Nth thing in front of me": a result row when
     the launcher is open, otherwise the Nth app in the dock. */
  document.addEventListener('keydown',e=>{
    if(!e.altKey||e.ctrlKey||e.metaKey||e.shiftKey)return;
    const m=/^Digit([1-9])$/.exec(e.code||'')||/^([1-9])$/.exec(e.key||'');
    if(!m)return;
    e.preventDefault();
    const n=+m[1]-1;
    if(OMNI.pop&&OMNI.matches[n])return omniRun(n);
    const id=(typeof DOCK!=='undefined'&&DOCK[n])||null;
    if(id&&APPS[id]){openApp(id);toast('▸ '+APPS[id].title)}
  });
  // type-anywhere: printable keys with no text field focused land in the bar
  document.addEventListener('keydown',e=>{
    if(e.ctrlKey||e.metaKey||e.altKey)return;
    if(e.key.length!==1)return;                                   // printable only
    const t=document.activeElement;
    if(t&&(/^(input|textarea|select)$/i.test(t.tagName)||t.isContentEditable))return;
    if(e.target.closest&&(e.target.closest('.xterm')||e.target.closest('#setup-wiz')))return;
    omniSummon(true);
    inp.focus();                                                  // the keypress lands in the bar
  });
  omniPresence();
  setInterval(omniPresence,4000);
})();
