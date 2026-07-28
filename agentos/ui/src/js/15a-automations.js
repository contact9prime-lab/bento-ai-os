/* ================= automations =================
   A named, repeatable sequence of desktop steps. You set one up once, give it a
   name, and from then on it does exactly that — whether you fire it from the
   prompt bar, a hot corner, the Automations app, a schedule, or by asking the
   agent for it by name.

   The runner lives here, in the browser, because the steps ARE the desktop:
   open this app, switch to that theme, put the agent on this prompt. The server
   only stores them and broadcasts `automation.run`, so every entry point ends up
   in this one function and they can never drift apart. */

let AUTOMATIONS=[];
async function loadAutomations(){
  try{AUTOMATIONS=(await (await fetch('/api/automations')).json()).automations||[]}catch(e){AUTOMATIONS=[]}
  return AUTOMATIONS;
}
function automationByName(n){
  n=String(n||'').toLowerCase().trim();
  return AUTOMATIONS.find(a=>a.name.toLowerCase()===n)||null;
}

/* ---- the vocabulary a step can speak ----
   Deliberately small: every kind maps to something the desktop already does, so
   an automation composes existing behaviour instead of introducing a second way
   to do it. `action` reaches the same SC_ACTIONS table the keyboard uses. */
const AUTO_ACTIONS=['deck','expose','showdesktop','launcher','control','notifications',
                    'windows.arrange','chat.new','chat.open','terminal','settings',
                    'voice','fullscreen','copilot','agent.stop','help'];
function automationStepLabel(s){
  switch(s.kind){
    case 'app':return 'Open '+((APPS[s.app]&&APPS[s.app].title)||s.app);
    // reuse the hot-corner vocabulary's wording so the same action reads the
    // same everywhere ("Show desktop", not "showdesktop")
    case 'action':{const hit=HC_ACTIONS.find(a=>a[0]===s.action);return hit?hit[1]:'Do '+s.action}
    case 'theme':return 'Theme → '+((allThemes()[s.theme]||{}).label||s.theme);
    case 'wallpaper':return 'Wallpaper → '+s.wallpaper;
    case 'desktop':return 'Go to desktop '+s.desk;
    case 'wait':return 'Wait '+s.ms+'ms';
    case 'agent':return 'Ask: '+String(s.prompt||'').slice(0,70);
  }
  return s.kind;
}

async function runAutomationStep(s){
  switch(s.kind){
    case 'app':      if(APPS[s.app])openApp(s.app); else toast('automation: no app "'+s.app+'"'); break;
    case 'action':   if(!scRun(s.action))toast('automation: unknown action "'+s.action+'"'); break;
    case 'theme':    if(allThemes()[s.theme])applyTheme(s.theme); else toast('automation: no theme "'+s.theme+'"'); break;
    case 'wallpaper':await setBuiltinWallpaper(s.wallpaper); break;
    case 'desktop':  switchDesk(Math.max(1,Math.min(DESKS,+s.desk||1))); break;
    case 'wait':     await new Promise(r=>setTimeout(r,Math.min(60000,+s.ms||0))); break;
    case 'agent':    palAsk(s.prompt); break;
  }
}
let AUTO_RUNNING=false;
async function runAutomation(a){
  if(typeof a==='string')a=automationByName(a)||AUTOMATIONS.find(x=>x.id===a);
  if(!a)return toast('no such automation');
  if(AUTO_RUNNING)return toast('an automation is already running');
  AUTO_RUNNING=true;
  document.body.classList.add('auto-running');
  toast('▶ '+a.name);
  try{
    for(const s of (a.steps||[])){
      await runAutomationStep(s);
      // a beat between steps: windows animate in, and a theme swap runs a view
      // transition — firing the next step mid-flight looks (and feels) broken
      if(s.kind!=='wait')await new Promise(r=>setTimeout(r,160));
    }
  }catch(e){toast('automation "'+a.name+'" failed: '+e.message)}
  AUTO_RUNNING=false;
  document.body.classList.remove('auto-running');
}
/* Fired by the server (a schedule, the agent's run_automation tool, another
   window) — the payload carries the whole automation so this client runs the
   same steps even if its list is stale. */
function onAutomationBroadcast(a){if(a&&a.steps)runAutomation(a)}

async function saveAutomation(name,steps,icon){
  const r=await fetch('/api/automations',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name,steps,icon:icon||''})});
  const d=await r.json();
  if(!r.ok)return toast(d.error||'could not save');
  await loadAutomations();
  toast('✓ saved "'+name+'"');
  return d;
}
async function deleteAutomation(id){
  if(!await osConfirm('Delete this automation?','Anything bound to it — a hot corner, a schedule — stops firing.',{confirmText:'Delete',danger:true}))return;
  await fetch('/api/automations/'+encodeURIComponent(id),{method:'DELETE'});
  await loadAutomations();refreshApp('automations');
  if(typeof hcRender==='function')hcRender();
}

/* ================= the Automations app ================= */
let AUTO_DRAFT=null;   // {name, icon, steps:[]} while the builder is open
function autoNewDraft(){return{name:'',icon:'',steps:[]}}
async function renderAutomations(body){
  await loadAutomations();
  const d=AUTO_DRAFT;
  body.innerHTML=`<div class="phead">
      <span class="pt">Automations</span>
      <span class="ps">name a sequence once — run it the same way forever</span>
      <span class="sp"></span>
      <button class="pact" onclick="autoEdit(null)">＋ New automation</button>
    </div>
    <div class="pbody pad">
      ${d?autoBuilderHTML(d):''}
      ${AUTOMATIONS.length?`<div class="auto-grid">${AUTOMATIONS.map(autoCardHTML).join('')}</div>`:
        (d?'':`<div class="empty"><div class="eh">Nothing saved yet. Build a sequence above, or just tell ${esc(agentName())}:
          <i>"whenever I start work, open chat and the terminal, switch to the minimal theme, and summarise my day —
          call it Start work"</i>.</div></div>`)}
      ${hcCardHTML()}
    </div>`;
  body.querySelectorAll('[data-run]').forEach(b=>b.onclick=()=>runAutomation(b.dataset.run));
  body.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>autoEdit(b.dataset.edit));
  body.querySelectorAll('[data-del]').forEach(b=>b.onclick=()=>deleteAutomation(b.dataset.del));
  hcBind(body);
}
function autoCardHTML(a){
  const when=a.last_run?('ran '+new Date(a.last_run*1000).toLocaleString()):'never run';
  return `<div class="auto-card">
    <div class="auto-top"><span class="auto-ic">${esc(a.icon||'▶')}</span>
      <span class="auto-nm">${esc(a.name)}</span></div>
    <ol class="auto-steps">${a.steps.map(s=>`<li>${esc(automationStepLabel(s))}</li>`).join('')}</ol>
    <div class="auto-foot"><span class="mut">${esc(when)}${a.runs?' · '+a.runs+'×':''}</span>
      <span class="sp" style="flex:1"></span>
      <button class="pact" data-run="${esc(a.id)}">Run</button>
      <button class="endbtn" data-edit="${esc(a.id)}">Edit</button>
      <button class="endbtn" data-del="${esc(a.id)}">✕</button></div>
  </div>`;
}
function autoEdit(id){
  const a=id?AUTOMATIONS.find(x=>x.id===id):null;
  AUTO_DRAFT=a?{id:a.id,name:a.name,icon:a.icon||'',steps:JSON.parse(JSON.stringify(a.steps))}:autoNewDraft();
  refreshApp('automations');
}
function autoBuilderHTML(d){
  const wallOpts=(BUILTIN_WALLS||[]).map(w=>`<option value="${esc(w)}">${esc(w)}</option>`).join('');
  return `<div class="provbox auto-builder">
    <div class="ptitle">${d.id?'Edit automation':'New automation'}</div>
    <div class="row" style="margin-top:10px;gap:8px">
      <input id="auto-name" placeholder="Name it — e.g. Start work" value="${esc(d.name)}" style="flex:1">
      <input id="auto-icon" placeholder="🌅" value="${esc(d.icon)}" style="flex:0 0 68px;text-align:center">
    </div>
    <ol class="auto-steps edit">${d.steps.length?d.steps.map((s,i)=>`<li>
        <span>${esc(automationStepLabel(s))}</span>
        <button class="endbtn" onclick="autoMove(${i},-1)" title="Move up">↑</button>
        <button class="endbtn" onclick="autoMove(${i},1)" title="Move down">↓</button>
        <button class="endbtn" onclick="autoDrop(${i})" title="Remove">✕</button>
      </li>`).join(''):'<li class="mut">No steps yet — add one below.</li>'}</ol>
    <label style="margin-top:12px">Add a step</label>
    <div class="row auto-add" style="gap:8px;flex-wrap:wrap">
      <select id="auto-kind" onchange="autoKindChange()">
        <option value="app">Open an app</option>
        <option value="action">Do a desktop action</option>
        <option value="theme">Apply a theme</option>
        <option value="wallpaper">Set a wallpaper</option>
        <option value="desktop">Switch virtual desktop</option>
        <option value="agent">Put the agent on a task</option>
        <option value="wait">Wait</option>
      </select>
      <span id="auto-arg" style="flex:1;min-width:180px;display:flex">
        <select id="auto-val">${Object.keys(APPS).map(k=>`<option value="${esc(k)}">${esc(APPS[k].title)}</option>`).join('')}</select>
      </span>
      <button class="endbtn" onclick="autoAdd()">Add step</button>
    </div>
    <div class="row" style="margin-top:14px;gap:8px">
      <button class="save" style="margin:0;width:auto;padding:10px 18px" onclick="autoSaveDraft()">Save automation</button>
      <button class="endbtn" onclick="autoRunDraft()">Test run</button>
      <button class="endbtn" onclick="AUTO_DRAFT=null;refreshApp('automations')">Cancel</button>
    </div>
    <template id="auto-opts-action"><select id="auto-val">${AUTO_ACTIONS.map(a=>`<option value="${a}">${esc(automationStepLabel({kind:'action',action:a}))}</option>`).join('')}</select></template>
    <template id="auto-opts-theme"><select id="auto-val">${Object.entries(allThemes()).map(([k,t])=>`<option value="${esc(k)}">${esc(t.label||k)}</option>`).join('')}</select></template>
    <template id="auto-opts-wallpaper"><select id="auto-val">${wallOpts}</select></template>
    <template id="auto-opts-desktop"><select id="auto-val">${[1,2,3,4,5,6].map(n=>`<option value="${n}">Desktop ${n}</option>`).join('')}</select></template>
    <template id="auto-opts-agent"><input id="auto-val" placeholder="What should the agent do? e.g. summarise my unread notifications"></template>
    <template id="auto-opts-wait"><input id="auto-val" type="number" min="0" max="60000" step="100" value="500" placeholder="milliseconds"></template>
  </div>`;
}
function autoKindChange(){
  const kind=$('#auto-kind').value, slot=$('#auto-arg'), tpl=$('#auto-opts-'+kind);
  if(kind==='app'){
    slot.innerHTML=`<select id="auto-val">${Object.keys(APPS).map(k=>`<option value="${esc(k)}">${esc(APPS[k].title)}</option>`).join('')}</select>`;
  }else if(tpl){slot.innerHTML=tpl.innerHTML}
}
function autoAdd(){
  const kind=$('#auto-kind').value, v=$('#auto-val')?$('#auto-val').value:'';
  const step={kind};
  if(kind==='app')step.app=v;
  else if(kind==='action')step.action=v;
  else if(kind==='theme')step.theme=v;
  else if(kind==='wallpaper')step.wallpaper=v;
  else if(kind==='desktop')step.desk=+v||1;
  else if(kind==='wait')step.ms=+v||500;
  else if(kind==='agent'){if(!String(v).trim())return toast('what should the agent do?');step.prompt=v}
  AUTO_DRAFT.steps.push(step);autoKeepFields();refreshApp('automations');
}
function autoMove(i,d){
  const s=AUTO_DRAFT.steps,j=i+d;if(j<0||j>=s.length)return;
  [s[i],s[j]]=[s[j],s[i]];autoKeepFields();refreshApp('automations');
}
function autoDrop(i){AUTO_DRAFT.steps.splice(i,1);autoKeepFields();refreshApp('automations')}
function autoKeepFields(){   // a re-render must not eat what's already typed
  const n=$('#auto-name'),ic=$('#auto-icon');
  if(n)AUTO_DRAFT.name=n.value;if(ic)AUTO_DRAFT.icon=ic.value;
}
async function autoSaveDraft(){
  autoKeepFields();
  if(!AUTO_DRAFT.name.trim())return toast('give it a name — that is how you will run it');
  if(!AUTO_DRAFT.steps.length)return toast('add at least one step');
  await saveAutomation(AUTO_DRAFT.name.trim(),AUTO_DRAFT.steps,AUTO_DRAFT.icon);
  AUTO_DRAFT=null;refreshApp('automations');
  if(typeof hcRender==='function')hcRender();
}
function autoRunDraft(){autoKeepFields();runAutomation({name:AUTO_DRAFT.name||'draft',steps:AUTO_DRAFT.steps})}
