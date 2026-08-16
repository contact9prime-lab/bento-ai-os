/* ================= docs app ================= */
let docsCur='', DOCS_ASK=null;
async function renderDocs(body){
  const d=await fetch('/api/docs').then(r=>r.json());
  if(!d.docs.length){body.innerHTML='<div class="pad"><p class="mut">No documentation found on this install.</p></div>';return}
  docsCur=docsCur||d.docs[0].file;
  const items=d.docs.map(x=>`<div class="item" style="cursor:pointer;${x.file===docsCur?'border-left:3px solid var(--acc,#5eead4)':''}" onclick="docsCur='${esc(x.file)}';refreshApp('docs')">
    <div class="grow">${esc(x.title)}</div></div>`).join('');
  const doc=await fetch('/api/docs/'+docsCur).then(r=>r.json());
  body.innerHTML=`<div style="display:flex;height:100%;min-height:0">
    <div class="doc-nav">${items}</div>
    <div style="flex:1;min-width:0;display:flex;flex-direction:column">
      <div class="doc-ask">
        <input id="doc-q" placeholder="Ask about this OS — answered from these pages, with the page named">
        <button id="doc-go">Ask</button>
      </div>
      <div id="doc-ans" class="doc-ans"></div>
      <div style="flex:1;overflow:auto;padding:16px 24px" class="docbody">${md(doc.content||'(not found)')}</div>
    </div></div>`;
  // relative .md links navigate inside the Docs app
  body.querySelectorAll('a.doclink').forEach(a=>a.onclick=e=>{
    e.preventDefault();docsCur=a.dataset.doc.split('#')[0];refreshApp('docs');
  });
  const q=body.querySelector('#doc-q');
  body.querySelector('#doc-go').onclick=()=>docsAsk(q.value);
  q.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();docsAsk(q.value)}});
}
/* Ask the manual. Deliberately an AGENT turn with `search_docs`, not a one-shot
   "stuff the top 5 chunks into a prompt": a real question ("why did my scheduled
   flow stop delegating?") is answered from two or three pages that no single
   similarity search returns together, and the agent can search again with better
   words when the first pass misses. The reply names the page, so the answer is
   checkable against the thing it came from — which is the whole point of having
   the manual on disk rather than in a model's memory. */
function docsAsk(text){
  text=(text||'').trim(); if(!text)return;
  const box=$('#doc-ans'); if(!box)return;
  box.classList.add('on');
  box.innerHTML=`<div class="mf-user">${esc(text)}</div>`;
  const q=$('#doc-q'); if(q)q.value='';
  const sink=miniFeed(box,{scrollEl:box,showThinking:false});
  agentTurn({text,cid:DOCS_ASK,origin:'copilot:docs',title:'✦ Docs',
    context:['You are answering a question about AgentOS itself, from inside its Docs app.',
      `The user is reading ${docsCur}.`,
      'ALWAYS call search_docs first and answer from what it returns — this build\'s',
      'behaviour is what the manual says, not what a similar project does. Search again',
      'with different words if the first pass misses. Name the page you used (e.g.',
      '"see security.md"). If the manual genuinely does not cover it, say so plainly',
      'rather than filling the gap from memory. Two or three sentences unless asked for more.'
    ].join('\n'),
    sink,onCid:id=>{DOCS_ASK=id}});
}

/* ================= first-run setup wizard (agent-led) =================
   Steps 1-2 are minimal forms (they must work before any model exists):
   welcome + name, then pick-a-brain. From step 3 on, the NAMED agent takes
   over: each remaining question arrives as a streamed in-character message
   (POST /api/setup/say) with inline choice chips. Offline-safe end to end —
   every line has a canned fallback baked in here too. */
let WIZ={agent_name:'Aria',autonomy:'balanced',default_model:'',providers:{},autostart:true,
  open_at_login:true,wallpaper_preset:'',voice:false,locale:null,step:1,info:null,convo:[],convoAt:0};
async function checkSetup(){
  try{
    const s=await fetch('/api/setup').then(r=>r.json());
    if(!s.first_run)return;
    // the wizard branches on PLATFORM.mode (de vs hosted); init loads it in
    // parallel with us, so fetch it ourselves if it hasn't landed yet
    try{if(!Object.keys(PLATFORM.capabilities||{}).length)PLATFORM=await(await fetch('/api/platform')).json()}catch(e){}
    WIZ.info=s;WIZ.agent_name=s.agent_name||'Aria';
    // The arc, not the old four-question form. One component for the first run and
    // for Settings → Run setup again, so the two can never drift.
    if(typeof obShow==='function'){obShow({});return}
    showWizard();
  }catch(e){}
}
const WIZ_SAY_FALLBACK={
  locale:n=>`One thing that changes every answer: where you are. I read this off the machine — is it right? News, weather, prices and times all follow it.`,
  autonomy:n=>`I'm ${n} — good to meet you. How much should I do on my own? Balanced is a good start: I act freely and check with you before anything risky.`,
  autostart:()=>'Should I keep running in the background — for scheduled jobs, alerts and Telegram — even when this window is closed?',
  de_here:()=>"This is your desktop now, so I'm always here — nothing to install, nothing to start.",
  wallpaper:()=>"Let's make this place yours. Pick a wallpaper to start with — I can generate a custom one for you later.",
  voice:()=>'One more thing — should I speak my replies out loud, or keep things quiet?',
  done:()=>"That's everything — welcome to Bento Box AI. Let's get to work.",
};
const WIZ_WALLS={ // ids mirror setup.WALLPAPER_PRESETS; CSS gradients, no file written
  aurora:'linear-gradient(135deg,#0b3d40 0%,#123a5e 45%,#3b1d5a 100%)',
  dusk:'linear-gradient(135deg,#1a1533 0%,#3d2456 50%,#7a3b5e 100%)',
  ember:'linear-gradient(135deg,#2b1010 0%,#5e2a1d 55%,#8a5a24 100%)',
  deep:'linear-gradient(135deg,#05070c 0%,#0b1b2b 60%,#10333b 100%)',
};
/* stream one in-character line into `el`; canned fallback if the endpoint is
   unreachable (the endpoint itself falls back server-side on model errors) */
async function wizSay(step,el){
  const body={step,name:WIZ.agent_name,model:WIZ.default_model};
  const prov=Object.keys(WIZ.providers||{})[0];
  if(prov){body.provider=prov;body.key=(WIZ.providers[prov]||{}).api_key||'';}
  try{
    const r=await fetch('/api/setup/say',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(!r.ok||!r.body)throw 0;
    const rd=r.body.getReader(),dec=new TextDecoder();let got='';
    for(;;){const c=await rd.read();if(c.done)break;
      const t=dec.decode(c.value,{stream:true});if(!t)continue;
      got+=t;el.textContent=got;el.scrollIntoView({block:'end'});}
    if(got.trim())return;
    throw 0;
  }catch(e){el.textContent=(WIZ_SAY_FALLBACK[step]||WIZ_SAY_FALLBACK.done)(WIZ.agent_name)}
}
function showWizard(){
  let ov=$('#setup-wiz');
  if(!ov){ov=document.createElement('div');ov.id='setup-wiz';ov.className='wiz';
    ov.innerHTML='<div class="wiz-stage" id="wiz-stage"></div>';document.body.appendChild(ov);
    Motion.run(ov,[{opacity:0},{opacity:1}],{duration:260,easing:EASE.out});}
  wizRender();
}
/* animated step swap — never a hard cut */
async function wizGo(step){
  wizCollect();
  const stage=$('#wiz-stage'),old=stage.firstElementChild;
  if(old)await Motion.run(old,[{opacity:1,transform:'none'},{opacity:0,transform:'translateY(-18px)'}],
    {duration:160,easing:EASE.in}).finished;
  WIZ.step=step;wizRender();
}
function wizRender(){
  const stage=$('#wiz-stage'),s=WIZ.info||{};
  if(WIZ.step===1)stage.innerHTML=`<div class="wiz-step">
    <div class="wiz-mark">▲</div>
    <h1 class="wiz-title">Welcome to Bento Box AI</h1>
    <p class="wiz-sub">Your machine, with a brain. Let's set it up together.</p>
    <label class="wiz-q">What should your agent be called?</label>
    <input id="wz-name" class="wiz-input" value="${esc(WIZ.agent_name)}" autocomplete="off" spellcheck="false">
    <button class="wiz-next" onclick="wizGo(2)">Continue →</button>
    ${wizDots(1)}</div>`;
  else if(WIZ.step===2){
    const local=(s.ollama_models||[]).map(m=>`<label class="wiz-pick"><input type="radio" name="wz-model" value="ollama/${esc(m)}" ${WIZ.default_model==='ollama/'+m?'checked':''}><b>ollama/${esc(m)}</b><span>local — private and free</span></label>`).join('');
    stage.innerHTML=`<div class="wiz-step">
    <div class="wiz-mark">▲</div>
    <h1 class="wiz-title">Pick ${esc(WIZ.agent_name)}'s brain</h1>
    <p class="wiz-sub">${local?'Local models found on this machine — or bring a cloud key.':'Nothing runs locally on this machine yet. Bento Box AI can set that up, or you can bring a cloud key.'}</p>
    ${/* "install Ollama later" was the end of the road here: the first screen that
          needs a brain told you what was missing and then left you to it. Offer
          it, with the licence and the exact command, on the screen where it
          matters. */''}
    ${local?'':`<div class="wiz-offer" id="wz-ollama">
      <b>Run models on this machine</b>
      <span>Private, free, no API key. Bento Box AI installs Ollama (MIT, llama.cpp underneath).</span>
      <button class="endbtn" onclick="wizInstallOllama()">Install it for me</button>
    </div>`}
    <div class="wiz-picks">${local}
      <label class="wiz-pick"><input type="radio" name="wz-model" value="cloud" ${WIZ.default_model&&!WIZ.default_model.startsWith('ollama/')?'checked':''}><b>Cloud model</b><span>Anthropic, OpenAI or OpenRouter (API key)</span></label>
    </div>
    <div id="wz-cloud" style="display:none">
      <div class="row"><select id="wz-prov"><option value="anthropic">Anthropic (Claude)</option><option value="openai">OpenAI</option><option value="openrouter">OpenRouter</option></select>
      <input id="wz-key" placeholder="API key"></div>
      <input id="wz-cmodel" placeholder="model, e.g. claude-sonnet-5" style="margin-top:6px;width:100%">
    </div>
    <button class="wiz-next" onclick="wizGo(3)">Continue →</button>
    <button class="wiz-back" onclick="wizGo(1)">← Back</button>
    ${wizDots(2)}</div>`;
    const cloud=$('#wz-cloud'),upd=()=>{cloud.style.display=document.querySelector('input[name="wz-model"]:checked')?.value==='cloud'?'block':'none'};
    document.querySelectorAll('input[name="wz-model"]').forEach(r=>r.onchange=upd);upd();
  }
  else{ // step 3+: the agent takes over — conversation with inline chips
    stage.innerHTML=`<div class="wiz-step wiz-convwrap">
      <div class="wiz-mark wiz-mark-sm">▲</div>
      <div class="wiz-convo" id="wiz-convo"></div></div>`;
    const de=PLATFORM.mode==='de';
    // de mode: autostart is meaningless (AgentOS IS the session) — replaced by a
    // one-line confirmation; wallpaper + voice are de-only questions
    WIZ.convo=de?['locale','autonomy','de_here','wallpaper','voice']:['locale','autonomy','autostart'];
    WIZ.convoAt=0;
    wizAsk();
  }
  const nu=stage.firstElementChild;
  if(nu)Motion.run(nu,[{opacity:0,transform:'translateY(20px)'},{opacity:1,transform:'none'}],{duration:300,easing:EASE.out});
  const nm=$('#wz-name');
  if(nm){nm.focus();nm.select();nm.onkeydown=e=>{if(e.key==='Enter')wizGo(2)}}
}
function wizDots(on){return `<div class="wiz-dots">${[1,2,3].map(n=>`<span class="${n<=on?'on':''}"></span>`).join('')}</div>`}
function wizCollect(){
  if(WIZ.step===1&&$('#wz-name'))WIZ.agent_name=$('#wz-name').value.trim()||'Aria';
  if(WIZ.step===2&&document.querySelector('input[name="wz-model"]')){
    const v=document.querySelector('input[name="wz-model"]:checked')?.value||'';
    if(v==='cloud'){const p=$('#wz-prov').value,k=$('#wz-key').value.trim(),m=$('#wz-cmodel').value.trim();
      WIZ.providers=k?{[p]:{api_key:k}}:{};
      WIZ.default_model=m?(p+'/'+m):'';}
    else{WIZ.default_model=v;WIZ.providers={};}}
}
/* one conversational beat: streamed agent message, then chips (or auto-advance) */
async function wizAsk(){
  const c=$('#wiz-convo');if(!c)return;
  const step=WIZ.convo[WIZ.convoAt];
  if(step===undefined){wizFinish();return}
  const row=document.createElement('div');row.className='wiz-msg';
  row.innerHTML=`<div class="wiz-ava">${esc((WIZ.agent_name||'A')[0].toUpperCase())}</div><div class="wiz-say"></div>`;
  c.appendChild(row);
  Motion.run(row,[{opacity:0,transform:'translateY(12px)'},{opacity:1,transform:'none'}],{duration:240,easing:EASE.out});
  await wizSay(step,row.querySelector('.wiz-say'));
  const chips=wizChips(step);
  if(!chips){ // confirmation beat (de_here): no question, just move on
    WIZ.convoAt++;setTimeout(wizAsk,900);return}
  c.appendChild(chips);
  Motion.run(chips,[{opacity:0,transform:'translateY(10px)'},{opacity:1,transform:'none'}],{duration:220,easing:EASE.out});
  c.scrollTop=c.scrollHeight;
}
function wizChips(step){
  let defs=null;
  if(step==='locale'){
    const el=document.createElement('div');el.className='wiz-chips';
    /* Three states, because this used to have one. The chip was drawn before the
       fetch resolved and read "? · ? detected" — offering a location nobody had
       detected as the RECOMMENDED answer, on the first screen a new user sees.
       While it is still reading, say so; if it could not read, hand the question
       over rather than pretending to an answer. */
    const draw=()=>{
      const lo=(WIZ.locale&&WIZ.locale.locale)||{};
      const place=lo.country_name||lo.country||'';
      const known=!!(place||lo.timezone);
      if(WIZ.locale===undefined){
        el.innerHTML=`<button class="wiz-chip" disabled>reading this machine…</button>`;
        return;
      }
      el.innerHTML=(known
        ? `<button class="wiz-chip rec" data-a="ok">${esc([place,lo.timezone].filter(Boolean).join(' · '))}<em>detected</em></button>
           <button class="wiz-chip" data-a="edit">Somewhere else…</button>`
        : `<button class="wiz-chip rec" data-a="edit">Tell me where you are</button>
           <em class="wiz-note">I could not read a location off this machine.</em>`);
      const ok=el.querySelector('[data-a=ok]');
      if(ok)ok.onclick=b=>wizPicked(el,ok);
      el.querySelector('[data-a=edit]').onclick=async()=>{
        const c=await osPrompt('Which country are you in?',{value:lo.country||'',placeholder:'IN, US, GB…',confirmText:'Set'});
        if(c===null)return;
        const tz=await osPrompt('Timezone',{value:lo.timezone||'',placeholder:'Asia/Kolkata',confirmText:'Set'});
        if(tz===null)return;
        WIZ.locale_override={country:(c||'').trim().toUpperCase(),timezone:(tz||'').trim()};
        await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({locale:WIZ.locale_override})});
        try{WIZ.locale=await (await fetch('/api/locale')).json()}catch(e){}
        draw();
      };
    };
    // undefined means "still asking"; null means the question was answered with
    // nothing, and the two must not look the same to someone waiting on it
    WIZ.locale=undefined;
    fetch('/api/locale').then(r=>r.json())
      .then(d=>{WIZ.locale=d||null;draw()})
      .catch(()=>{WIZ.locale=null;draw()});
    draw();
    return el;
  }
  if(step==='autonomy')defs=[
    ['Paranoid','asks before every action',()=>WIZ.autonomy='paranoid',false],
    ['Balanced','acts freely, asks for risky things',()=>WIZ.autonomy='balanced',true],
    ['Full','never asks',()=>WIZ.autonomy='full',false]];
  else if(step==='autostart')defs=[
    ['Start at login','background service + launcher',()=>{WIZ.autostart=true;WIZ.open_at_login=true},true],
    ['Only when I open it','',()=>{WIZ.autostart=false;WIZ.open_at_login=false},false]];
  else if(step==='voice')defs=[
    ['Yes, speak replies','',()=>WIZ.voice=true,false],
    ['Text only','',()=>WIZ.voice=false,true]];
  else if(step==='wallpaper'){
    const el=document.createElement('div');el.className='wiz-chips';
    el.innerHTML=Object.keys(WIZ_WALLS).map(id=>
      `<button class="wiz-chip wiz-swatch" data-w="${id}" title="${id}"><span style="background:${WIZ_WALLS[id]}"></span>${id}</button>`).join('')+
      `<button class="wiz-chip" data-w="">Let ${esc(WIZ.agent_name)} generate one later</button>`;
    el.querySelectorAll('.wiz-chip').forEach(b=>b.onclick=()=>{
      WIZ.wallpaper_preset=b.dataset.w;
      if(b.dataset.w){const w=$('#wall');if(w){w.style.backgroundImage=WIZ_WALLS[b.dataset.w];w.classList.add('has')}}
      wizPicked(el,b)});
    return el;
  }
  if(!defs)return null;
  const el=document.createElement('div');el.className='wiz-chips';
  el.innerHTML=defs.map(([t,d],i)=>`<button class="wiz-chip${defs[i][3]?' rec':''}" data-i="${i}" ${d?`title="${esc(d)}"`:''}>${esc(t)}${defs[i][3]?'<em>recommended</em>':''}</button>`).join('');
  el.querySelectorAll('.wiz-chip').forEach(b=>b.onclick=()=>{defs[+b.dataset.i][2]();wizPicked(el,b)});
  return el;
}
function wizPicked(el,btn){ // lock the row, keep the choice visible, next beat
  el.querySelectorAll('.wiz-chip').forEach(b=>{b.disabled=true;b.classList.toggle('on',b===btn)});
  Motion.run(btn,[{transform:'scale(1)'},{transform:'scale(1.06)'},{transform:'scale(1)'}],{duration:220,easing:EASE.spring});
  WIZ.convoAt++;setTimeout(wizAsk,350);
}
async function wizFinish(){
  const c=$('#wiz-convo');
  const r=await fetch('/api/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(WIZ)}).then(r=>r.json()).catch(()=>({}));
  WIZ.report=r.report||{};
  // client-side settings the server can't reach: TTS lives in localStorage
  if(WIZ.convo.includes('voice')){VOICE.tts=!!WIZ.voice;saveVoice();}
  const row=document.createElement('div');row.className='wiz-msg';
  row.innerHTML=`<div class="wiz-ava">${esc((WIZ.agent_name||'A')[0].toUpperCase())}</div><div class="wiz-say"></div>`;
  c.appendChild(row);
  Motion.run(row,[{opacity:0,transform:'translateY(12px)'},{opacity:1,transform:'none'}],{duration:240,easing:EASE.out});
  await wizSay('done',row.querySelector('.wiz-say'));
  const fin=document.createElement('div');fin.className='wiz-finish';
  fin.innerHTML=`${(WIZ.report.applied||[]).map(l=>`<div class="sub">· ${esc(l)}</div>`).join('')}
    ${WIZ.report.autostart?`<div class="sub">· ${esc(WIZ.report.autostart)}</div>`:''}
    ${WIZ.report.boot?`<div class="sub">· ${esc(WIZ.report.boot)}</div>`:''}`;
  c.appendChild(fin);
  Motion.run(fin,[{opacity:0,transform:'translateY(10px)'},{opacity:1,transform:'none'}],{duration:260,easing:EASE.out});
  c.scrollTop=c.scrollHeight;
  loadConfig();loadModels();
  // The last beat is not "Enter" — it is "give me a job". A machine you have only
  // configured is a machine you have no reason to open tomorrow; one that is already
  // doing something for you is a habit. jobStep owns the Enter button from here, and
  // offers "Not now" beside it, because a first-run flow you cannot get past is one
  // people learn to click through without reading.
  jobStep(c,wizEnter);
}
function wizEnter(){
  const ov=$('#setup-wiz');
  Motion.run(ov,[{opacity:1},{opacity:0}],{duration:220,easing:EASE.in}).finished.then(()=>ov.remove());
  openApp('chat');
}
async function factoryReset(){
  if(!await osConfirm('Factory reset Bento Box AI?','This wipes ALL data: memory, knowledge graph, conversations, apps, subagents, logs, soul and settings. The first-run wizard will start over.',{confirmText:'Reset'}))return;
  if(!await osConfirm('Really wipe everything?','This cannot be undone.',{danger:true,confirmText:'Reset'}))return;
  await fetch('/api/setup/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirm:true})});
  location.reload();
}



/* First-run offer to install a local model runtime. The command and licence are
   shown before anything runs, and the step re-reads itself after so a freshly
   installed runtime appears as a real choice rather than requiring a restart. */
async function wizInstallOllama(){
  const box=document.getElementById('wz-ollama');if(!box)return;
  const btn=box.querySelector('button');
  if(btn){btn.disabled=true;btn.textContent='Installing…'}
  box.insertAdjacentHTML('beforeend','<span class="mut" id="wz-ollama-note">this downloads a few hundred MB…</span>');
  try{
    const r=await fetch('/api/components/install',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({id:'ollama'})});
    const d=await r.json();
    const note=document.getElementById('wz-ollama-note');
    if(d.ok){
      if(note)note.textContent='installed — pull a model with: ollama pull llama3.2';
      try{WIZ.info=await (await fetch('/api/setup')).json()}catch(e){}
      wizRender();
    }else if(note){
      note.textContent=(d.message||'could not install')+(d.command?` — run: ${d.command}`:'');
    }
  }catch(e){const n=document.getElementById('wz-ollama-note');if(n)n.textContent='could not reach the server'}
  finally{if(btn){btn.disabled=false;btn.textContent='Install it for me'}}
}

/* A manual link is clickable wherever it is rendered, not only inside Docs. The
   agent cites the manual in chat constantly, and a citation you cannot follow is
   a footnote — the link rendered, looked like a link, and did nothing, because
   the only handler was the one Docs attaches to its own body.

   Delegated from the document so it covers markup added after load, which is
   every chat reply. Docs' own per-element handler runs first (bubbling) and calls
   preventDefault, so `defaultPrevented` is how in-app navigation avoids also
   raising a window it is already inside. */
document.addEventListener('click', e => {
  const a = e.target.closest ? e.target.closest('a.doclink') : null;
  if (!a || e.defaultPrevented) return;
  e.preventDefault();
  docsCur = (a.dataset.doc || '').split('#')[0].replace(/^(\.\.?\/)+/, '');
  openApp('docs');
});
