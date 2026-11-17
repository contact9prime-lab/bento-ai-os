/* ---------------- Settings → AI providers: what is in use, and which agents may think ----------------
   Asked for as "the AI providers section should show the list of the providers that are
   activated and settings for each" and "select the agents that are to be enabled as a whole,
   along with the agents installed like Claude Code, Gemini CLI, Codex, Hermes and OpenClaw".

   IN USE is read, never kept: /api/brains (what can answer here, executors.brains), the lead's
   backups (/api/brain/fallbacks) and every agent's brain (/api/agents, fabric.agent_brain), so
   "who uses it" is the same answer the run itself reads. A row's Settings button opens the card
   that holds that provider's switch and key.

   USE THEM is executors.switched_off: one switch per installed agent, through
   PUT /api/executors/use (admin on a machine with accounts). An agent that is off is never a
   brain: not the lead's, not a pin's, not a backup. The lead's own brain can't be switched off
   here; the server says to choose another one first. TUI: `bento brain agents [on|off ID]`.
   SUI: the same page. `var`/function declarations only. */
var PROVUSE={busy:false};

async function paintActiveProviders(){
  const box=document.getElementById('s-active');if(!box)return;
  let br={},fb={},ag={};
  try{[br,fb,ag]=await Promise.all([apiJSON('/api/brains'),apiJSON('/api/brain/fallbacks').catch(()=>({})),
    apiJSON('/api/agents').catch(()=>({}))])}
  catch(e){box.innerHTML=`<p class="mut">${esc(e.message||String(e))}</p>`;return}
  const list=br.executors||[],cur=br.current||{};
  const lead=(cfg&&cfg.agent_name)||'Bento';
  const users={};
  const add=(id,who)=>{if(!id)return;(users[id]=users[id]||[]).includes(who)||users[id].push(who)};
  // the lead's first choice, then its backups, then every agent's own brain
  add(cur.executor,lead);
  (fb.fallbacks||[]).forEach((f,i)=>add(f.executor==='aria'?String(f.model||'').split('/')[0]:f.executor,lead+' (backup '+(i+1)+')'));
  ((ag&&ag.agents)||[]).filter(a=>!a.master&&a.brain&&a.brain.own).forEach(a=>add(a.brain.provider||a.brain.engine,a.name));
  const p=(cfg&&cfg.providers)||{};
  const on=list.filter(e=>e.kind==='provider'?(p[e.id]&&p[e.id].enabled)||(e.id==='pool'&&e.available)
    :(e.on!==false&&!/not installed/i.test(e.reason||'')&&(e.available||e.detail)));
  if(!on.length){box.innerHTML='<p class="mut">Nothing is switched on yet. Add a key to a provider below, or install an agent.</p>';return}
  const where=e=>e.kind==='agent'?'Agents installed here':'Model providers';
  box.innerHTML=on.map(e=>{
    const who=users[e.id]||[];
    const state=e.available?(e.detail||'ready'):(e.reason||'not ready');
    return `<div class="prow act-row${e.available?'':' off'}"><div class="pl"><div class="act-name"><span class="act-dot ${e.available?'ok':'no'}" aria-hidden="true"></span><b>${esc(String(e.name).split(' — ')[0])}</b></div>
        <div class="pdesc">${esc(state)}${who.length?' · used by '+who.map(esc).join(', '):' · nobody uses it yet'}</div></div>
      <div class="pc"><button class="endbtn" data-act-go="${esc(e.kind==='agent'?'Installed agents':'Providers')}" data-act-id="${esc(e.id)}">Settings</button></div></div>`;
  }).join('');
  box.querySelectorAll('[data-act-go]').forEach(b=>b.onclick=()=>provGo(b.dataset.actGo,b.dataset.actId));
}

/* Open a provider's own card: its section, then the card that names it, folded open. */
function provGo(section,id){
  if(typeof setSubShow==='function')setSubShow(section);
  const main=document.getElementById('prefs-main');if(!main)return;
  const key={anthropic:'ant',openai:'oai',openrouter:'or',google:'goo',custom:'cus',ollama:'ollama'}[id];
  let card=null;
  if(key){const f=main.querySelector(`#s-${key}-on,#s-${key}-url`);card=f&&f.closest('.pgroup')}
  if(!card)card=main.querySelector('#exec-use');
  if(!card)return;
  card.classList.add('open');
  if(typeof setSubReveal==='function')setSubReveal(card);
  card.scrollIntoView({block:'start',behavior:'smooth'});
}

async function renderExecUse(){
  const box=document.getElementById('exec-use');if(!box)return;
  let d={};
  try{d=await apiJSON('/api/brains')}catch(e){box.innerHTML=`<h3>Use them</h3><p class="mut">${esc(e.message||String(e))}</p>`;return}
  const agents=(d.executors||[]).filter(e=>e.kind==='agent');
  const cur=(d.current||{}).executor;
  const here=agents.filter(e=>!/not installed/i.test(e.reason||''));
  if(!here.length){box.innerHTML='<h3>Use them</h3><div class="ghint">No other AI agents are installed here yet. You can install one below.</div>';return}
  box.innerHTML='<h3>Use them</h3>'+here.map(e=>{
    const lead=e.id===cur;
    const why=e.on===false?'Off. Nothing here uses it.'
      :!e.available?(e.reason||'Installed, but it can’t answer here yet.')
      :(e.detail?e.detail+'. ':'')+(lead?'Your lead agent thinks with it.':'Your agents may think with it.');
    return pRow(e.name,`<label class="psw"><input type="checkbox" data-exec-use="${esc(e.id)}"${e.on!==false?' checked':''}${lead?' disabled title="Your lead agent thinks with it. Choose another brain in Agents → Lead agent first."':''} aria-label="Use ${esc(e.name)}"><i></i></label>`,
      {desc:esc(why),f:'use '+e.id+' '+e.name});
  }).join('');
  box.querySelectorAll('[data-exec-use]').forEach(c=>c.onchange=()=>execUse(c.dataset.execUse,c.checked,c));
}

async function execUse(engine,on,ctl){
  if(PROVUSE.busy)return;PROVUSE.busy=true;if(ctl)ctl.disabled=true;
  try{
    const j=await apiJSON('/api/executors/use',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({engine,on})});
    if(j&&j.error)throw new Error(j.error);
    cfg.executors=cfg.executors||{};cfg.executors.off=j.off||[];
    toast('✓ '+(j.said||'saved'));
  }catch(e){toast(e.message||String(e),{kind:'err'});if(ctl)ctl.checked=!on}
  finally{PROVUSE.busy=false;if(ctl)ctl.disabled=false}
  renderExecUse();paintActiveProviders();
}

/* Voice tab: the engine is chosen in AI providers, so here it is named, and the browser's
   own voice picker shows only while the browser is the engine (11f-speech.js did that while
   the engine box lived on this tab). */
async function voiceEnginePaint(){
  const now=document.getElementById('v-engine-now');if(!now)return;
  let d={};try{d=await apiJSON('/api/speech')}catch(e){now.textContent=e.message||String(e);return}
  const cur=((d.config||{}).engine)||'browser';
  now.textContent=((d.titles||{})[cur])||cur;
  const bv=document.getElementById('v-voice'),row=bv&&bv.closest('.prow');
  if(row)row.style.display=cur==='browser'?'':'none';
}
