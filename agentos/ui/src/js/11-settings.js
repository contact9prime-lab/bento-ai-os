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
        <button class="pact" onclick="saveSettings()">Save</button>
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
    P.push(`<h2>AI providers</h2><p class="lead">Where the intelligence comes from. Local models need nothing but Ollama; cloud providers need a key. Everything you enable shows up in the model picker.</p>`);
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
  if(want('agent')){
    P.push(`<h2>Agent</h2><p class="lead">Who your agent is and how far it may go on its own.</p>`);
    P.push(pGroup('Identity',[
      pRow('Name',pText('s-name',cfg.agent_name||'Aria'),{desc:'What it calls itself everywhere in the OS.',f:'agent name'}),
      pRow('Workspace',pText('s-workspace',cfg.workspace),{desc:'Where files, reports and projects are written.',f:'workspace directory'}),
      pRow('Max steps per turn',pText('s-steps',cfg.max_steps,'','number'),{desc:'How many tool steps one turn may take before it stops.',f:'max steps'}),
      pRow('Build model','<select id="s-build-model"><option value="">Use my default model</option></select>',
        {desc:'Which model App Studio builds apps with. AgentOS never substitutes another one on its own.',f:'build model app studio'}),
    ],{f:'agent identity name workspace'}));
    P.push(pGroup('Sandbox',[
      pRow('Folder jail',pSwitch('s-sb-on',cfg.sandbox&&cfg.sandbox.enabled),
        {desc:'Commands and the Terminal run confined (bubblewrap): everything outside is read-only and other home files are hidden.',f:'sandbox jail bubblewrap'}),
      pRow('Folder',pText('s-sb-root',(cfg.sandbox&&cfg.sandbox.root)||cfg.workspace),{f:'sandbox root folder'}),
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
  if(on('s-sb-on')!==undefined)patch.sandbox={enabled:on('s-sb-on'),root:(val('s-sb-root')||'').trim()};
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
