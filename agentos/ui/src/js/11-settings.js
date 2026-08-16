/* ================= settings app ================= */
/* ---- preference primitives: every row is label+description left, control right ---- */
function pGroup(title,rows,o){
  o=o||{};
  return `<div class="pgroup${o.danger?' danger':''}" data-f="${esc(o.f||title)}">
    ${title?`<h3>${esc(title)}</h3>`:''}${o.hint?`<div class="ghint">${o.hint}</div>`:''}
    ${rows.join('')}</div>`;
}
function pRow(label,control,o){
  o=o||{};
  return `<div class="prow${o.stack?' stack':''}${o.danger?' danger':''}" data-f="${esc(o.f||label)}">
    <div class="pl"><b>${esc(label)}</b>${o.desc?`<small>${o.desc}</small>`:''}</div>
    <div class="pc">${control}</div></div>`;
}
const pSwitch=(id,on)=>`<label class="psw"><input type="checkbox" id="${id}" ${on?'checked':''}><i></i></label>`;
/* A stored secret is never put back into an input: it shows as a locked chip
   with the last four characters, and "Replace" swaps in an empty field. That
   way nothing can echo the mask back to the server, and a shoulder-surfer sees
   nothing useful. */
function pSecret(id,hasKey,masked,ph){
  if(!hasKey)return `<input type="password" id="${id}" placeholder="${esc(ph||'')}" autocomplete="off">`;
  return `<span class="psecret" id="${id}-wrap"><i>saved</i><code>${esc(masked||'••••')}</code>
    <button class="endbtn" onclick="pSecretReplace('${id}')">Replace</button></span>`;
}
function pSecretReplace(id){
  const w=document.getElementById(id+'-wrap');if(!w)return;
  w.outerHTML=`<input type="password" id="${id}" placeholder="new key…" autocomplete="off">`;
  const el=document.getElementById(id);if(el)el.focus();
}
const pText=(id,val,ph,type)=>`<input type="${type||'text'}" id="${id}" value="${esc(val==null?'':val)}" placeholder="${esc(ph||'')}">`;
const pSelect=(id,opts,cur)=>`<select id="${id}">${opts.map(([v,l])=>
  `<option value="${esc(v)}" ${String(v)===String(cur)?'selected':''}>${esc(l)}</option>`).join('')}</select>`;

const SETTINGS_TABS=[
  ['ai','✦','AI providers'],
  ['agent','◈','Agent'],
  ['executors','⇥','Executors'],
  ['channels','◇','Channels'],
  ['locale','◐','Locale'],
  ['keys','⌘','Shortcuts'],
  ['voice','◉','Voice'],
  ['look','◧','Appearance'],
  ['system','⚙','System'],
];
let SETTAB=localStorage.getItem('settab')||'ai';

async function renderSettings(body){
  await loadConfig();
  body.innerHTML=`<div class="pshell">
      <div class="phead"><span class="pt">Settings</span><span class="sp"></span>
        <span class="psearch">${SVG_SEARCH}<input id="set-q" placeholder="Find a setting…" autocomplete="off"></span>
        ${/* One Save per page. The sticky bar at the foot is always reachable
              while you scroll; a second copy in the header meant two controls for
              one act, and neither said which settings it covered. */''}
      </div>
      <div class="prefs">
        <div class="prefs-side">${SETTINGS_TABS.map(([id,ic,label])=>
          `<button data-t="${id}" class="${SETTAB===id?'on':''}"><span class="psi">${ic}</span>${esc(label)}</button>`).join('')}</div>
        <div class="prefs-main" id="prefs-main"></div>
      </div>
    </div>`;
  body.querySelectorAll('.prefs-side button').forEach(b=>b.onclick=()=>{
    SETTAB=b.dataset.t;localStorage.setItem('settab',SETTAB);
    body.querySelectorAll('.prefs-side button').forEach(x=>x.classList.toggle('on',x===b));
    setTab(body);
  });
  // search spans every category, so nothing hides behind a tab
  const q=body.querySelector('#set-q');
  let t;q.oninput=()=>{clearTimeout(t);t=setTimeout(()=>{
    const v=q.value.trim();
    if(v){setTab(body,true);listFilter(body.querySelector('#prefs-main'),v)}
    else setTab(body);
  },140)};
  setTab(body);
}
function setTab(body,all){
  const main=(body||document).querySelector('#prefs-main');if(!main)return;
  const p=cfg.providers;
  const P=[];
  const want=id=>all||SETTAB===id;
  if(want('ai')){
    P.push(`<h2>AI providers</h2><p class="lead">Where the intelligence comes from. Local models need nothing but Ollama; cloud providers need a key. Everything you enable shows up in the picker below.</p>`);
    // The chat chip has always said "change it in Settings → AI providers", and
    // for a long time this panel had nowhere to change it: you could add a key
    // and edit a provider's model LIST, but choosing which model actually answers
    // was only possible as "Set default" in the Model Manager. So editing the
    // list here looked like picking a model and did nothing. This is that control,
    // in the place everything already points at, and it applies on the spot —
    // needing a second Save to make a chosen model take effect is the same bug
    // wearing a different hat.
    P.push(pGroup('Answering', [
      pRow('This machine answers with',
        `<span class="s-modelrow">
           <select id="s-model" onchange="pickModel(this.value)"><option value="">loading…</option></select>
           <button class="endbtn" id="s-model-refresh" onclick="paintModelPicker(1)" title="Ask every enabled provider what it can run right now">↻ Refresh</button>
           <button class="endbtn" onclick="openApp('models')" title="Pull, delete and inspect local models">Manage…</button>
         </span>`,
        {desc:'Every surface uses it — chat, the prompt bar, copilot panels, Telegram, scheduled jobs. Changing it here takes effect immediately.',
         f:'model default answers with picker which model refresh available'}),
      pRow('Available', '<span id="s-model-count" class="mut">…</span>',
        {desc:'Fetched from each enabled provider, not a list typed into config. Refresh after pulling a model or adding a key.',
         f:'available models count refresh providers'}),
    ], {f:'model answering default'}));
    setTimeout(paintModelPicker, 0);      // the list is fetched, not part of cfg
    P.push(pGroup('Local',[
      pRow('Ollama base URL',pText('s-ollama-url',p.ollama.base_url,'http://localhost:11434'),
        {desc:'Local models — private, free, no key.',f:'ollama local base url'}),
    ],{f:'ollama local'}));
    const prov=(key,name,idOn,idKey,idModels,ph,desc,obj)=>pGroup(name,[
      pRow('Enabled',pSwitch(idOn,obj&&obj.enabled),{desc,f:key+' enable'}),
      pRow('API key',pSecret(idKey,obj&&obj._has_key,(obj&&obj.api_key)||'',ph),
        {f:key+' api key',desc:(obj&&obj._has_key)?'Stored on this machine. It is never shown again or sent to the browser.':'Pasted once, then hidden.'}),
      pRow('Models',pText(idModels,((obj&&obj.models)||[]).join(', '),'comma-separated'),{stack:true,f:key+' models'}),
    ],{f:key+' '+name});
    P.push(prov('anthropic','Anthropic','s-ant-on','s-ant-key','s-ant-models','sk-ant-…','Claude models.',p.anthropic));
    P.push(prov('openai','OpenAI','s-oai-on','s-oai-key','s-oai-models','sk-…','GPT models.',p.openai));
    P.push(prov('openrouter','OpenRouter','s-or-on','s-or-key','s-or-models','sk-or-…','One key, hundreds of models.',p.openrouter));
    P.push(prov('google','Google (Gemini)','s-goo-on','s-goo-key','s-goo-models','AIza…','Gemini chat + image generation. Free key at aistudio.google.com.',p.google||{}));
    P.push(pGroup('Custom (OpenAI-compatible)',[
      pRow('Enabled',pSwitch('s-cus-on',p.custom.enabled),{desc:'LM Studio, vLLM, Groq — anything speaking the OpenAI API.',f:'custom enable'}),
      pRow('Base URL',pText('s-cus-url',p.custom.base_url||'','http://localhost:1234/v1'),{f:'custom base url'}),
      pRow('API key',pSecret('s-cus-key',p.custom._has_key,p.custom.api_key||'','optional'),{f:'custom key'}),
      pRow('Models',pText('s-cus-models',(p.custom.models||[]).join(', '),'comma-separated'),{stack:true,f:'custom models'}),
    ],{f:'custom openai compatible endpoint lm studio'}));
    P.push(pGroup('Image generation',[
      pRow('Provider',pSelect('s-img-prov',[['auto','auto'],['google','google'],['openai','openai'],['pollinations','pollinations']],(cfg.image&&cfg.image.provider)||'auto'),
        {desc:'auto picks Google, then OpenAI, else the free pollinations.ai service.',f:'image provider'}),
      pRow('Model',pText('s-img-model',(cfg.image&&cfg.image.model)||'','gemini-2.5-flash-image / gpt-image-1'),{f:'image model'}),
    ],{f:'image generation wallpaper'}));
  }
  if(want('executors')){
    P.push(`<h2>Executors</h2><p class="lead">Other agents already installed on this machine that AgentOS can hand a task to. AgentOS keeps the desktop — an executor only gets files, shell and research inside the folder you choose. Pick one as the engine in Chat to delegate a turn to it.</p>`);
    P.push(pGroup('Forward everything',[
      pRow('This machine answers with',pSelect('s-engine',[
          ['aria',(cfg.agent_name||'Aria')+' (the built-in agent)'],
          ['claude-code','Claude Code']],cfg.engine||'aria'),
        {desc:'Forwarding turns this machine into a front end: every turn a person starts is answered by that agent instead — chat, the prompt bar, copilot panels, Telegram, the API and scheduled turns. Apps and App Studio keep using the built-in agent, because they depend on its tools.',
         f:'forward everything engine forwarder proxy relay'}),
    ],{f:'forwarding engine'}));
    P.push(`<div id="exec-list" class="pgroup" data-f="executors claude code delegate"><h3>Claude Code</h3><p class="mut">checking…</p></div>`);
    setTimeout(renderExecutors,0);   // availability is a probe, not part of cfg
  }
  if(want('channels')){
    P.push(`<h2>Channels</h2><p class="lead">Every way a conversation reaches this machine — this window, the session, a terminal, your phone, the API, the schedule. They all talk to the same agent with the same memory and the same tools. What differs is who can speak through each one, and how far it is trusted.</p>`);
    P.push(`<div id="chan-list" data-f="channels telegram whatsapp api remote tui sui gui scheduled messaging permissions"><p class="mut">checking…</p></div>`);
    setTimeout(renderChannels,0);   // live state, not part of cfg
  }
  if(want('agent')){
    P.push(`<h2>Agent</h2><p class="lead">Who your agent is and how far it may go on its own.</p>`);
    P.push(pGroup('Identity',[
      pRow('Name',pText('s-name',cfg.agent_name||'Aria'),{desc:'What it calls itself everywhere in the OS.',f:'agent name'}),
      pRow('Workspace',pText('s-workspace',cfg.workspace),{desc:'Where files, reports and projects are written.',f:'workspace directory'}),
      pRow('Max steps per turn',pText('s-steps',cfg.max_steps,'','number'),{desc:'How many tool steps one turn may take before it stops.',f:'max steps'}),
      pRow('Build model','<select id="s-build-model"><option value="">Use my default model</option></select>',
        {desc:'Which model App Studio builds apps with. AgentOS never substitutes another one on its own.',f:'build model app studio'}),
    ],{f:'agent identity name workspace'}));
    P.push(pGroup('Content from outside',[
      pRow('After reading a web page or an MCP reply',pSelect('s-taint',[
        ['ask','Ask before anything that changes something'],
        ['strict','Refuse to change anything for the rest of the turn'],
        ['off','No extra caution']],(cfg.security&&cfg.security.taint)||'ask'),
        {desc:'Fetched pages and third-party servers can contain text written to look like an instruction to your agent. This decides what happens for the rest of a turn that has read some — including at Full autonomy, which is trust in <em>your</em> instructions, not a stranger\'s.',
         f:'taint injection untrusted prompt security web page mcp'}),
      pRow('Conversation history',pSelect('s-hist-compact',[
        ['on','Summarise older turns when the thread outgrows the model'],
        ['off','Drop them instead']],(cfg.history&&cfg.history.compact===false)?'off':'on'),
        {desc:'Long threads stop fitting the model\'s context window. Either way you are told in the conversation when it happens.',
         f:'history compaction summary context window long thread'}),
    ],{f:'security untrusted injection history'}));
    P.push(pGroup('Sandbox',[
      pRow('Folder jail',pSwitch('s-sb-on',cfg.sandbox&&cfg.sandbox.enabled),
        {desc:'Commands and the Terminal run confined (bubblewrap): everything outside is read-only and other home files are hidden.',f:'sandbox jail bubblewrap'}),
      pRow('Folder',pText('s-sb-root',(cfg.sandbox&&cfg.sandbox.root)||cfg.workspace),{f:'sandbox root folder'}),
      /* The jail has one root and nobody's data lives in it, so "read last
         quarter's invoices" used to mean copying them in first. These are the
         other places the agent may work — one per line, because a path may
         contain a comma and every separator that splits one is a folder that
         silently never matches. */
      /* Deliberately a pointer and not a second editor. Which folders are open
         and WHO they are open to is one fact; two places to change it is two
         places to disagree, and the copy nobody demos is the one that drifts.
         Settings owns whether there is a jail; Users owns who reaches through it. */
      pRow('Shared folders','<button class="endbtn" onclick="openApp(\'users\')">Open Users</button>',
        {desc:'Folders the agent and the Terminal may work in besides the workspace, each read-only or read-write and shared with named accounts. Managed in Users, next to the isolation they are the exception to — or `bento folders` in a terminal.',f:'sandbox safe shared folders ro rw users data access'}),
        {stack:true,desc:'One share per line: mode (ro/rw), who (* for everyone, or accounts separated by commas), then the folder. The path comes LAST so it may contain spaces. Applies to the agent and the Terminal alike. Folders holding other accounts are refused; bento doctor names any entry that is not in use.',f:'sandbox safe folders share ro rw users data access'}),
    ],{f:'sandbox security'}));
    P.push(pGroup('GitHub',[
      pRow('Personal access token',pSecret('s-gh-token',cfg.github&&cfg.github._has_token,(cfg.github&&cfg.github.token)||'','github_pat_… / ghp_…'),
        {desc:(cfg.github&&cfg.github._has_token)?'A token is already saved. Fine-grained tokens are recommended.':'Lets the agent create repos and push what it builds. Never appears in commands or logs.',f:'github token push'}),
      pRow('Username',pText('s-gh-user',(cfg.github&&cfg.github.username)||'','optional'),{f:'github username'}),
    ],{f:'github git ship publish'}));
  }
  if(want('locale')){
    P.push(`<h2>Locale</h2><p class="lead">Where and when you are. The agent localises anything place- or time-dependent — news, weather, prices, holidays, units — and the AgentOS session inherits your timezone and language.</p>`);
    P.push(`<div class="pgroup" data-f="locale region country timezone language units clock"><div id="loc-box"><div class="prow"><div class="pl"><small>…</small></div></div></div></div>`);
  }
  if(want('keys')){
    P.push(`<h2>Shortcuts</h2><p class="lead">Click a binding, then press the keys you want. Shortcuts marked <em>session</em> are also registered with the compositor, so they keep working while a native app has the keyboard.</p>`);
    P.push(`<div class="pgroup" data-f="shortcuts keyboard keys bindings hotkeys"><div id="sc-list"></div></div>`);
    P.push(pGroup('',[
      pRow('Restore defaults','<button class="endbtn" onclick="scReset()">Restore</button>',{desc:'Put every binding back the way it shipped.',f:'shortcuts reset'}),
      pRow('Re-apply to session','<button class="endbtn" onclick="scApplySession()">Apply</button>',{desc:'Rewrite the compositor keybindings from this table.',f:'shortcuts session apply'}),
    ],{f:'shortcuts actions'}));
  }
  if(want('voice')){
    P.push(`<h2>Voice</h2><p class="lead">Dictate with the mic in the prompt bar or chat; the agent can speak its replies back.</p>`);
    P.push(pGroup('Speech',[
      pRow('Speak replies aloud',pSwitch('v-tts',VOICE.tts),{desc:'Text-to-speech for every answer.',f:'tts speak voice'}),
      pRow('Voice','<select id="v-voice"></select>',{f:'tts voice picker'}),
      pRow('Speech rate',pText('v-rate',VOICE.rate||1,'','number'),{f:'speech rate'}),
      pRow('Mic language',pText('v-lang',VOICE.lang||'en-IN','en-IN, en-US, hi-IN…'),{desc:'Language the dictation recogniser listens for.',f:'mic language dictation'}),
    ],{f:'voice tts speech microphone'}));
  }
  if(want('look')){
    P.push(`<h2>Appearance</h2><p class="lead">How the desktop looks. Themes carry colours, fonts and even whole alternate shells.</p>`);
    P.push(pGroup('Theme',[
      pRow('Desktop theme',pSelect('s-theme',Object.entries(allThemes()).map(([k,t])=>[k,(t.label||t.name||k)+(t.custom?' ·':'')]),CURRENT_THEME)
        +`<button class="endbtn" onclick="openApp('themes')">Gallery</button>`,{f:'theme appearance'}),
      pRow('Wallpaper','<button class="endbtn" onclick="openApp(\'personalize\')">Personalize</button><button class="endbtn" onclick="wpSystem()">Use system</button>',
        {desc:'Generate one with AI, pick from the gallery, or adopt the host desktop\'s.',f:'wallpaper background'}),
      pRow('Fullscreen','<button class="endbtn" onclick="toggleFullscreen()">Toggle (F11)</button>',{f:'fullscreen'}),
    ],{f:'appearance theme wallpaper'}));
  }
  if(want('system')){
    P.push(`<h2>System</h2><p class="lead">The machine underneath — network, displays, sound and session live in System Settings.</p>`);
    P.push(pGroup('Version',[
      pRow('This build','<span id="s-ver" class="mut">checking…</span>',
        {desc:'AgentOS checks for a new version on its own and asks before installing one. Installing pulls the update, verifies it against the test suite, restarts the service and reloads this page.',
         f:'version update upgrade check for updates auto-update'}),
      pRow('Check automatically',pSwitch('s-upd-on',true),
        {desc:'Only the CHECK is automatic. Nothing is ever installed without you saying so.',f:'automatic update check'}),
    ],{f:'version updates'}));
    setTimeout(paintVersion,0);      // live, and it makes a network call
    P.push(pGroup('Setup',[
      pRow('Open Setup','<button class="endbtn" onclick="openApp(\'setup\')">Open the app</button>',
        {desc:'The nine steps as an ordinary window you can open any time — name, model, a first answer, a specialist, a flow, a schedule, a channel, the look, accounts. Steps already done show ticked, because every one is probed rather than remembered. Nothing here wipes anything: it creates.',
         f:'setup onboarding wizard app steps arc walkthrough tour open'}),
      pRow('Run it again from the start','<button class="endbtn" onclick="obRestart()">Walk me through it</button>',
        {desc:'The same steps, full screen, with anything you skipped offered again. Still not a reset — see Factory reset below for that.',
         f:'setup onboarding wizard first run walkthrough tour again restart'}),
    ],{f:'setup onboarding'}));
    P.push(pGroup('Machine',[
      pRow('System Settings','<button class="endbtn" onclick="openApp(\'syssettings\')">Open</button>',
        {desc:'Network, Bluetooth, displays, sound, power, session and optional components.',f:'system settings network displays'}),
      pRow('Permissions','<button class="endbtn" onclick="openApp(\'permissions\')">Open</button>',{desc:'What apps and the agent are allowed to do.',f:'permissions grants'}),
      pRow('Snapshots','<button class="endbtn" onclick="openApp(\'snapshots\')">Open</button>',{desc:'Restore points for the whole OS.',f:'snapshots restore'}),
    ],{f:'system machine'}));
    P.push(pGroup('Danger zone',[
      pRow('Factory reset','<button class="endbtn" style="border-color:var(--err);color:var(--err)" onclick="factoryReset()">Reset…</button>',
        {danger:true,desc:'Wipes memory, knowledge, conversations, apps, subagents, soul and settings, then runs first-time setup again. Take a Snapshot first.',f:'factory reset wipe danger'}),
    ],{danger:true,f:'danger zone factory reset'}));
  }
  main.innerHTML=P.join('')+`<div class="savebar"><button class="pact" onclick="saveSettings()">Save</button></div>`;
  const th=main.querySelector('#s-theme');
  if(th)th.onchange=()=>{applyTheme(th.value);toast('theme applied')};
  if(main.querySelector('#sc-list')){scLoad();scRender()}
  if(main.querySelector('#loc-box'))locRender();
  if(main.querySelector('#v-voice'))settingsVoices();
  const bm=main.querySelector('#s-build-model');
  if(bm)fetch('/api/models').then(r=>r.json()).then(d=>{
    const cur=(cfg.build&&cfg.build.model)||'';
    bm.innerHTML='<option value="">Use my default model'+(d.default?' · '+d.default:'')+'</option>'+
      (d.models||[]).map(m=>`<option value="${esc(m.id)}" ${m.id===cur?'selected':''}>${esc(m.id)}</option>`).join('');
    if(cur&&![...bm.options].some(o=>o.value===cur))
      bm.insertAdjacentHTML('beforeend',`<option value="${esc(cur)}" selected>${esc(cur)} · unavailable right now</option>`);
    bm.value=cur;
  }).catch(()=>{});
}
function settingsVoices(){
  const vsel=$('#v-voice');
  const fill=()=>{
    if(!window.speechSynthesis||!vsel)return;
    const vs=speechSynthesis.getVoices();
    vsel.innerHTML='<option value="">(default)</option>'+vs.map(v=>
      `<option value="${esc(v.name)}" ${VOICE.voice===v.name?'selected':''}>${esc(v.name)} · ${esc(v.lang)}</option>`).join('');
  };
  fill();
  if(window.speechSynthesis)speechSynthesis.onvoiceschanged=fill;
}
/* The model picker in Settings → AI providers. Fetched rather than read from
   cfg, because what can answer is a live question — a provider's catalogue, the
   models Ollama has pulled, and any executor this machine forwards to. */
/* The version row. Answers from the last check so opening Settings is instant;
   "Check now" is the one that goes and looks. */
async function paintVersion(check){
  const el=document.getElementById('s-ver'); if(!el)return;
  el.textContent='checking…';
  let d={};
  try{d=await (await fetch('/api/update'+(check?'?check=true':''))).json()}catch(e){
    el.textContent='could not check';return}
  const sw=document.getElementById('s-upd-on'); if(sw)sw.checked=d.enabled!==false;
  const btn=`<button class="endbtn" style="margin-left:10px" onclick="paintVersion(1)">Check now</button>`;
  if(d.update_available){
    // Never a dead button: when an update cannot be installed the reason is the
    // sentence, not a control that fails when pressed.
    el.innerHTML=`<b>${esc(d.current)}</b> → <b style="color:var(--acc)">${esc(d.latest)}</b> available`
      +(d.can_apply?` <button class="pact" style="margin-left:10px" onclick="updateNow(this)">Update now</button>`
                   :`<div class="mut" style="margin-top:4px">${esc(d.blocked_reason||'')}</div>`)+btn;
  }else{
    el.innerHTML=`<b>${esc(d.current||'?')}</b> `
      +`<span class="mut">${d.error?esc(d.error):(d.latest?'up to date':'not checked yet')}</span>`+btn;
  }
}
async function updateNow(btn){
  btn.disabled=true;btn.textContent='Updating…';
  try{
    const r=await fetch('/api/update',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    const d=await r.json();
    if(!d.ok&&d.error){btn.disabled=false;btn.textContent='Try again';toast(d.error)}
  }catch(e){/* the server restarts mid-request on success — update_done is the real signal */}
}
async function paintModelPicker(refresh){
  const sel=document.getElementById('s-model'); if(!sel)return;
  const btn=document.getElementById('s-model-refresh');
  const count=document.getElementById('s-model-count');
  if(refresh&&btn){btn.disabled=true;btn.textContent='↻ Asking…'}
  if(refresh&&count)count.textContent='asking each provider…';
  let d={models:[],default:'',engines:[]};
  // A refresh is a real round trip to every enabled provider, so it is asked for
  // rather than done on every repaint — a Settings tab that stalled behind three
  // network calls would be worse than a list that is a minute old.
  try{d=await (await fetch('/api/models'+(refresh?'?t='+Date.now():''))).json()}catch(e){}
  if(btn){btn.disabled=false;btn.textContent='↻ Refresh'}
  const cur=(cfg&&cfg.default_model)||d.default||'';
  const groups={};
  (d.models||[]).forEach(m=>{(groups[m.provider]=groups[m.provider]||[]).push(m)});
  const opts=Object.keys(groups).sort().map(prov=>
    `<optgroup label="${esc(prov)}">`+groups[prov].map(m=>
      `<option value="${esc(m.id)}"${m.id===cur?' selected':''}>${esc(m.name)}</option>`).join('')
    +`</optgroup>`).join('');
  sel.innerHTML=opts||`<option value="">no models — add a key above, or pull one in Model Manager</option>`;
  // A model set in config that the providers no longer offer must stay visible
  // and selected, or opening Settings would silently look like something else
  // is answering.
  if(cur&&!(d.models||[]).some(m=>m.id===cur))
    sel.insertAdjacentHTML('afterbegin',`<option value="${esc(cur)}" selected>${esc(cur)} (not currently offered)</option>`);
  // What was actually found, per provider — the answer to "did adding that key
  // work?" and "did my pull land?", which the picker alone cannot give.
  if(count){
    const n=(d.models||[]).length;
    const per=Object.keys(groups).sort().map(k=>`${esc(k)} ${groups[k].length}`).join(' · ');
    const eng=(d.engines||[]).filter(e=>e.available).map(e=>esc(e.name));
    count.innerHTML=n?`<b>${n}</b> model${n===1?'':'s'} — ${per}`
                     :`none found — enable a provider below, or pull one in <a href="#" onclick="openApp('models');return false">Model Manager</a>`;
    if(eng.length)count.innerHTML+=` · engines: ${eng.join(', ')}`;
  }
}
async function pickModel(id){
  if(!id)return;
  await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({default_model:id})});
  if(cfg)cfg.default_model=id;
  toast('answering with '+id);
  loadModels();paintModelChip();refreshApp('models');
}
async function saveSettings(){
  // only the open category is in the DOM, so save exactly what is on screen —
  // reading a field from a hidden tab would throw and lose the whole save
  const el=id=>document.getElementById(id);
  const val=id=>{const e=el(id);return e?e.value:undefined};
  const on=id=>{const e=el(id);return e?e.checked:undefined};
  const list=id=>{const v=val(id);return v===undefined?undefined:v.split(',').map(x=>x.trim()).filter(Boolean)};
  const put=(o,k,v)=>{if(v!==undefined&&v!=='')o[k]=v;return o};
  const prov=(key,idOn,idKey,idModels,idUrl)=>{
    const o={};
    if(on(idOn)!==undefined)o.enabled=on(idOn);
    const k=val(idKey);
    if(k!==undefined&&k!==''&&!k.startsWith('•'))o.api_key=k;   // masks are display-only
    if(list(idModels)!==undefined)o.models=list(idModels);
    if(idUrl&&val(idUrl)!==undefined)o.base_url=val(idUrl);
    return Object.keys(o).length?o:undefined;
  };
  if(el('v-tts')){
    VOICE.tts=on('v-tts');VOICE.voice=val('v-voice')||'';
    VOICE.rate=+val('v-rate')||1;VOICE.lang=(val('v-lang')||'').trim()||'en-IN';
    saveVoice();
  }
  const patch={};
  put(patch,'workspace',val('s-workspace'));
  if(val('s-steps')!==undefined)patch.max_steps=+val('s-steps')||25;
  if(val('s-name')!==undefined)patch.agent_name=(val('s-name')||'').trim()||'Aria';
  /* NOT folders: this page no longer edits them, and sending the key at all
     would send an empty list and silently unshare everything. */
  if(on('s-sb-on')!==undefined)patch.sandbox={enabled:on('s-sb-on'),root:(val('s-sb-root')||'').trim()};
  if(val('s-taint')!==undefined)patch.security={taint:val('s-taint')};
  if(val('s-hist-compact')!==undefined)patch.history={compact:val('s-hist-compact')!=='off'};
  const providers={};
  const add=(k,v)=>{if(v)providers[k]=v};
  add('ollama',val('s-ollama-url')!==undefined?{base_url:val('s-ollama-url')}:undefined);
  add('anthropic',prov('anthropic','s-ant-on','s-ant-key','s-ant-models'));
  add('openai',prov('openai','s-oai-on','s-oai-key','s-oai-models'));
  add('openrouter',prov('openrouter','s-or-on','s-or-key','s-or-models'));
  add('custom',prov('custom','s-cus-on','s-cus-key','s-cus-models','s-cus-url'));
  add('google',prov('google','s-goo-on','s-goo-key','s-goo-models'));
  if(Object.keys(providers).length)patch.providers=providers;
  if(val('s-build-model')!==undefined)patch.build={model:val('s-build-model')};
  if(val('s-img-prov')!==undefined)patch.image={provider:val('s-img-prov'),model:(val('s-img-model')||'').trim()};
  const ght=(val('s-gh-token')||'').trim();
  if((ght&&!ght.startsWith('•'))||val('s-gh-user')!==undefined)
    patch.github={...(ght&&!ght.startsWith('•')?{token:ght}:{}),username:(val('s-gh-user')||'').trim()};
  if(val('s-engine')!==undefined)patch.engine=val('s-engine');
  if(on('s-upd-on')!==undefined)patch.updates={enabled:on('s-upd-on')};
  // Executors: the tool list is checkboxes rather than a field, so it is read
  // from the DOM directly. Only present when the Executors tab is on screen.
  if(document.getElementById('s-exec-on')!==null){
    patch.executors={claude_code:{
      enabled:on('s-exec-on'),
      workspace:(val('s-exec-ws')||'').trim(),
      model:(val('s-exec-model')||'').trim(),
      budget_usd:Number(val('s-exec-budget')||2),
      tools:[...document.querySelectorAll('[data-tool]')].filter(i=>i.checked).map(i=>i.dataset.tool),
      allow_source:on('s-exec-src'),
    }};
  }
  if(!Object.keys(patch).length){toast('nothing to save on this page');return}
  await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)});
  toast('settings saved');loadModels();loadConfig();
}


/* ---- shortcut editor: click a row, press the keys ---- */
let SC_REC=null;
function scRender(){
  const box=$('#sc-list');if(!box)return;
  box.innerHTML=Object.keys(SHORTCUTS).map(name=>{
    const sc=SHORTCUTS[name];
    return `<div class="sc-row" data-n="${esc(name)}">
      <span class="sc-l">${esc(sc.label||name)}${sc.session?'<em>session</em>':''}</span>
      <button class="sc-k">${esc(sc.keys||'—')}</button></div>`;
  }).join('');
  box.querySelectorAll('.sc-row').forEach(r=>{
    r.querySelector('.sc-k').onclick=()=>scRecord(r.dataset.n,r.querySelector('.sc-k'));
  });
}
function scRecord(name,btn){
  if(SC_REC&&SC_REC.btn)SC_REC.btn.classList.remove('rec');
  SC_REC={name,btn};btn.classList.add('rec');btn.textContent='press keys…';
  const done=e=>{
    e.preventDefault();e.stopPropagation();
    if(e.key==='Escape'){cancel();return}
    if(['Control','Alt','Shift','Meta'].includes(e.key))return;      // wait for a real key
    const parts=[];
    if(e.ctrlKey)parts.push('Ctrl');
    if(e.altKey)parts.push('Alt');
    if(e.shiftKey)parts.push('Shift');
    if(e.metaKey)parts.push('Meta');
    let k=e.key;
    if(e.code==='Space')k='Space';
    else if(k.length===1)k=k.toUpperCase();
    parts.push(k);
    const keys=parts.join('+');
    const clash=Object.keys(SHORTCUTS).find(n=>n!==name&&SHORTCUTS[n].keys===keys);
    SHORTCUTS[name].keys=keys;
    cleanup();
    scSave().then(()=>{scRender();toast(clash?`${keys} set — it was also ${SHORTCUTS[clash].label}`:`${keys} set`)});
  };
  const cancel=()=>{cleanup();scRender()};
  const cleanup=()=>{window.removeEventListener('keydown',done,true);SC_REC=null};
  window.addEventListener('keydown',done,true);
}
async function scSave(){
  const out={};Object.keys(SHORTCUTS).forEach(n=>out[n]=SHORTCUTS[n].keys);
  cfg.shortcuts=out;
  try{
    await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({shortcuts:out})});
    scApplySession(true);
  }catch(e){toast('could not save shortcuts')}
}
async function scReset(){
  SHORTCUTS=JSON.parse(JSON.stringify(SC_DEFAULTS));
  await scSave();scRender();toast('shortcuts restored');
}
async function scApplySession(quiet){
  try{
    const r=await fetch('/api/shortcuts/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});
    const d=await r.json();
    if(!quiet)toast(d.message||(d.ok?'session shortcuts applied':'not in session mode'));
  }catch(e){if(!quiet)toast('could not reach the session')}
}

/* ---- locale editor ---- */
let LOCALE=null;
async function locRender(){
  const box=$('#loc-box');if(!box)return;
  try{LOCALE=await (await fetch('/api/locale')).json()}
  catch(e){box.innerHTML=pRow('Locale','<span class="mut">could not read it</span>');return}
  const lo=LOCALE.locale, det=LOCALE.detected;
  const countries=Object.entries(LOCALE.countries).sort((a,b)=>a[1].localeCompare(b[1]));
  box.innerHTML=[
    pRow('Country / region',
      pSelect('loc-country',[['','— not set —'],...countries.map(([c,n])=>[c,`${n} (${c})`])],lo.country),
      {desc:'Decides what "local" means: news, prices, holidays, sport.',f:'country region locale'}),
    pRow('Timezone',pSelect('loc-tz',[['','— not set —'],...LOCALE.timezones.map(t=>[t,t])],lo.timezone),
      {desc:'Every "today" and "tonight" is resolved in this zone.',f:'timezone clock time'}),
    pRow('Language',pText('loc-lang',lo.language||'','en-IN'),{f:'language locale'}),
    pRow('City',pText('loc-city',lo.city||'','Bengaluru'),{desc:'Optional — sharpens weather and local answers.',f:'city location'}),
    pRow('Units',pSelect('loc-units',[['metric','Metric'],['imperial','Imperial']],lo.units),{f:'units metric imperial'}),
    pRow('Clock',pSelect('loc-clock',[['24h','24-hour'],['12h','12-hour']],lo.clock),{f:'clock 12 24 hour'}),
    pRow('Detected on this machine',
      `<button class="endbtn" onclick="locUseDetected()">Use detected</button>`,
      {desc:`${esc(det.country||'?')} · ${esc(det.timezone||'?')} · ${esc(det.language||'?')}`,f:'detected locale'}),
    pRow('Apply',`<button class="pact" onclick="locSave()">Save locale</button>`,
      {desc:esc(LOCALE.describe.split('.')[0])+'.',f:'save locale apply session'}),
  ].join('');
}
async function locSave(){
  const payload={country:$('#loc-country').value,timezone:$('#loc-tz').value,
    language:$('#loc-lang').value.trim(),city:$('#loc-city').value.trim(),
    units:$('#loc-units').value,clock:$('#loc-clock').value};
  await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({locale:payload})});
  const r=await (await fetch('/api/locale/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).json();
  await loadConfig();tickClock();locRender();
  toast(r.message||'locale saved');
}
async function locUseDetected(){
  await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({locale:{country:'',timezone:'',language:'',city:'',units:'',clock:''}})});
  await loadConfig();tickClock();locRender();toast('using the machine\'s own locale');
}

/* ---- Executors: agents already on this machine that AgentOS can delegate to ----
   Availability is a live probe rather than config, so this panel is rendered
   after the tab paints. Every control here widens or narrows the envelope a
   delegated run gets, and the sentence under the switch always states the
   envelope in full — picking "Claude Code" in Chat should never be a blind grant. */
async function renderExecutors(){
  const box=document.getElementById('exec-list');if(!box)return;
  var d=null;
  try{d=await (await fetch('/api/executors')).json()}catch(e){}
  const ex=d&&(d.executors||[]).find(e=>e.id==='claude_code');
  if(!ex){box.innerHTML='<h3>Claude Code</h3><p class="mut">could not read executors</p>';return}
  if(!ex.available){
    /* "Not installed" used to end here, which is a dead end wearing an honest
       sentence. The exact command is shown before anything runs, and the button
       runs that command — nothing is installed without agreeing to it. */
    box.innerHTML=`<h3>Claude Code</h3><p class="mut">${esc(ex.reason||'not available')}</p>
      ${ex.install_cmd?`
        <div class="ghint">${esc(ex.install_note||'')}</div>
        ${pRow('Install it',`<button class="endbtn" id="exec-inst"
             onclick="execInstall()">Install Claude Code</button>`,
          {desc:`Runs: <code>${esc(ex.install_cmd)}</code> — into your own account, no sudo.`,
           f:'install claude code executor'})}
        <pre id="exec-instlog" class="exec-log" hidden></pre>`:''}
      ${ex.install?`<p class="mut"><button class="endbtn" onclick="openInBrowser('${esc(ex.install)}')">Read the docs</button></p>`:''}`;
    return;
  }
  const c=ex.config||{}, tools=c.tools||[];
  const tool=(name,desc)=>`<label class="exec-tool"><input type="checkbox" data-tool="${name}" ${tools.indexOf(name)>=0?'checked':''}> <b>${name}</b> <span class="mut">${esc(desc)}</span></label>`;
  /* How a delegated run is paid for. "Delegate this turn" reads as free when it
     is a subscription and as nothing at all when it is a metered key, and those
     are very different things to click — so it is stated before the switch. */
  const b=ex.billing||{};
  const bill=b.detail?`<div class="ghint bill ${esc(b.mode||'')}">${
    {subscription:'◆',api:'$',none:'!'}[b.mode]||'·'} ${esc(b.detail)}${
    (b.stripped||[]).length?` <span class="mut">(${esc(b.stripped.join(', '))} is set in the environment but is not passed to it)</span>`:''}</div>`:'';
  box.innerHTML=`<h3>Claude Code <span class="mut">${esc(ex.version||'')}</span></h3>
    <div class="ghint">${esc(ex.what||'')}</div>${bill}
    ${pRow('Use as an engine',pSwitch('s-exec-on',ex.enabled),
      {desc:'Adds “Claude Code” to the model picker in Chat. Each turn you send there is delegated to it.',f:'enable claude code executor'})}
    ${ex.needs_signin?`<div class="ghint bill none">! Installed, but nobody is signed in — run <code>${esc(ex.signin_cmd||'claude')}</code> once in a terminal. Delegated runs will use that subscription.</div>`:''}
    ${pRow('Folder',pText('s-exec-ws',c.workspace),
      {desc:'The only directory it can read or write. Everything else on the machine is out of reach.',f:'executor workspace folder'})}
    ${pRow('Let it work on AgentOS itself',pSwitch('s-exec-src',c.allow_source),
      {desc:`Also gives it <code>${esc(ex.source_root||'')}</code> — the source of this OS — so it can fix AgentOS's own tools and windows. It is told that the UI is built from <code>ui/src</code> and that the suite must pass. Off unless you turn it on: the OS rewriting itself is its own decision.`,
       f:'executor agentos source develop self edit'})}
    ${pRow('Model',pText('s-exec-model',c.model,'its own default'),
      {desc:'Leave empty to let Claude Code choose. It uses its own credentials — not your AgentOS provider keys.',f:'executor model'})}
    ${pRow(b.mode==='subscription'?'Work limit':'Spend limit',
      pText('s-exec-budget',c.budget_usd,'','number'),
      {desc:b.mode==='subscription'
        ? 'You are on a Claude subscription, so runs are not billed per token — this is a runaway guard, not a bill. Claude Code stops when its <em>notional</em> cost reaches it; ask it to carry on and it resumes where it stopped.'
        : 'A hard ceiling in US dollars per run, enforced by Claude Code itself.',
       f:'executor budget cost limit work'})}
    ${pRow('Allowed tools',`<div class="exec-tools">
        ${tool('Read','read files')}${tool('Glob','find files')}${tool('Grep','search text')}
        ${tool('WebSearch','search the web')}${tool('WebFetch','read a page')}
        ${tool('Write','create files')}${tool('Edit','change files')}${tool('Bash','run commands')}
      </div>`,{stack:true,desc:'Decided here, once, before a run starts — this build of Claude Code has no per-call approval hook, so anything left unticked simply cannot be used.',f:'executor allowed tools permissions'})}
    <div class="ghint" id="exec-envelope">${esc(ex.envelope||'')}</div>`;
  const refresh=()=>{
    const t=[...box.querySelectorAll('[data-tool]')].filter(i=>i.checked).map(i=>i.dataset.tool);
    const writes=t.some(x=>x==='Write'||x==='Edit'||x==='Bash');
    const e=document.getElementById('exec-envelope');
    if(e)e.textContent=`Claude Code in ${document.getElementById('s-exec-ws').value} with `
      +(t.join(', ')||'no tools')+(writes?' (can change files and run commands)':' (read-only)')
      +`, up to $${Number(document.getElementById('s-exec-budget').value||0).toFixed(2)}`;
  };
  box.querySelectorAll('[data-tool],#s-exec-ws,#s-exec-budget').forEach(i=>{
    i.onchange=refresh;i.oninput=refresh;
  });
}

/* Installing is a visible act: the command was shown, the output streams here,
   and the panel re-probes when it finishes rather than claiming success. */
async function execInstall(){
  const btn=document.getElementById('exec-inst'), log=document.getElementById('exec-instlog');
  if(btn){btn.disabled=true;btn.textContent='Installing…'}
  if(log){log.hidden=false;log.textContent='starting…\n'}
  try{
    const r=await fetch('/api/executors/install',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({id:'claude_code'})});
    const d=await r.json();
    if(log){log.textContent+=(d.message||'')+'\n'}
    toast(d.ok?'✓ '+(d.message||'installed'):(d.message||'could not install'));
    if(d.ok)renderExecutors();
  }catch(e){ toast('could not reach the server') }
  finally{ if(btn){btn.disabled=false;btn.textContent='Install Claude Code'} }
}
/* Progress lines from the installer, broadcast so every open surface sees them. */
function execInstallLine(ev){
  const log=document.getElementById('exec-instlog');
  if(!log)return;
  log.hidden=false;
  if(ev.line){log.textContent+=ev.line+'\n';log.scrollTop=log.scrollHeight}
}

/* ---- channels: every way in, who may use it, and how far it is trusted ----
   Each card saves on its own (PUT /api/channels/<id>) rather than through the
   page-wide Save, because a channel is a self-contained decision and because the
   server answers with why it refused — "still needs Bot token", "that one shares
   a gate with This window" — which is worth showing next to the control that
   caused it rather than as one page-level error. */
var CHAN_POSTURES=[];
async function renderChannels(){
  const box=document.getElementById('chan-list');if(!box)return;
  var d=null;
  try{d=await (await fetch('/api/channels')).json()}catch(e){}
  if(!d||!d.channels){box.innerHTML='<p class="mut">could not read channels</p>';return}
  CHAN_POSTURES=d.postures||[];
  var html=`<h3 class="chsec">Channels that reach this agent</h3>`
    +d.channels.map(chanCard).join('');
  box.innerHTML=html;
  if(typeof waPanel==='function'&&document.getElementById('wa-extra'))waPanel();
}
function chanCard(c){
  const dot={on:'ok',off:'mut',needs:'warn'}[c.status]||'mut';
  const fields=(c.fields||[]).map(f=>pRow(f.label,
      f.secret?pSecret(`ch-${c.id}-${f.key}`,!!(c.set||{})[f.key],'••••',f.placeholder)
              :pText(`ch-${c.id}-${f.key}`,(c.values||{})[f.key],f.placeholder),
      {desc:f.help,f:c.id+' '+f.label})).join('');
  /* Postures are per IO gate. Channels that share a gate say whose posture they
     follow instead of showing a select that would never be consulted. */
  const posture=c.own_gate
    ? pRow('Permissions',pSelect(`ch-${c.id}-posture`,
        CHAN_POSTURES.map(p=>[p.id,p.label]),c.posture),
        {desc:(CHAN_POSTURES.find(p=>p.id===c.posture)||{}).help||'',
         f:c.id+' permissions posture autonomy'})
    : pRow('Permissions',`<span class="mut">follows ${esc(c.posture_from||'another channel')}</span>`,
        {desc:`Arrives through the same gate, so the same rules apply: ${esc(c.posture_label)}.`,
         f:c.id+' permissions'});
  const onoff=c.builtin
    ? pRow('Available',`<span class="mut">always on</span>`,
        {desc:'This is how you reach the machine — it has no off switch here.',f:c.id+' always on'})
    : pRow('Switched on',pSwitch(`ch-${c.id}-on`,c.enabled),{f:c.id+' enable'});
  /* The walkthrough, open exactly when it is needed. "Create a bot with @BotFather
     and paste its token" is a fine label for the BOX; it is not instructions, and it
     assumes you know BotFather is a Telegram account you message, that /newbot
     exists, and that pairing afterwards is a separate act nobody mentioned.
     `status==='needs'` is the honest trigger: unfilled channels teach, a working one
     folds itself away rather than nagging. */
  const steps=(c.setup||[]).length?`<details class="chsteps" ${c.status==='needs'?'open':''}>
      <summary>How to set this up — ${(c.setup||[]).length} steps</summary>
      ${/* md() rather than a second inline-markdown pass: it escapes first, and it
            is what renders **bold** and `code` everywhere else in the OS. The <p>
            it wraps a single line in is styled flat below. */''}
      <ol>${c.setup.map(s=>`<li>${md(s)}</li>`).join('')}</ol>
    </details>`:'';
  return `<div class="pgroup chan" data-f="channel ${esc(c.id)} ${esc(c.title)}">
    <h3>${esc(c.title)} <span class="chdot ${dot}">${esc(c.detail)}</span></h3>
    <div class="ghint">${esc(c.what)}</div>
    ${pRow('Who can use it',`<span class="mut">${esc(c.reach)}</span>`,
      {desc:c.reach_panel?`Change that in ${esc(c.reach_panel)}.`:'',f:c.id+' who reach access'})}
    ${steps}
    ${onoff}${posture}${fields}
    ${c.note?`<div class="ghint mut">${esc(c.note)}</div>`:''}
    ${/* WhatsApp's two facts a form cannot hold: the callback URL Meta needs, and
         whether the 24-hour window is open. Filled by waPanel() after render. */''}
    ${c.id==='whatsapp'?'<div id="wa-extra" class="wa-extra"></div>':''}
    ${(c.scoped_grants?`<div class="ghint mut">${c.scoped_grants} permission rule${c.scoped_grants==1?'':'s'} apply to this channel — see the Permissions app.</div>`:'')}
    <div class="prow"><div class="pl"><small id="ch-${c.id}-msg" class="mut"></small></div>
      <div class="pc"><button class="endbtn" onclick="chanSave('${esc(c.id)}')">Save</button></div></div>
  </div>`;
}
async function chanSave(id){
  const msg=document.getElementById('ch-'+id+'-msg');
  const body={};
  const on=document.getElementById('ch-'+id+'-on'); if(on)body.enabled=on.checked;
  const po=document.getElementById('ch-'+id+'-posture'); if(po)body.posture=po.value;
  // only fields the user actually typed into: a saved secret shows as a chip
  // with no input, and sending '' for it would read as "clear this"
  document.querySelectorAll(`[id^="ch-${id}-"]`).forEach(el=>{
    const k=el.id.slice(('ch-'+id+'-').length);
    if(['on','posture','msg'].indexOf(k)>=0)return;
    if(el.tagName==='INPUT')body[k]=el.value;
  });
  if(msg){msg.textContent='saving…';msg.className='mut'}
  try{
    const r=await fetch('/api/channels/'+encodeURIComponent(id),
      {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const j=await r.json();
    if(msg){msg.textContent=j.ok?'saved':(j.error||'could not save');msg.className=j.ok?'ok':'warn'}
    if(j.ok)renderChannels();
  }catch(e){if(msg){msg.textContent='could not reach the server';msg.className='warn'}}
}
