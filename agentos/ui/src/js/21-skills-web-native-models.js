/* ================= skills app ================= */
/* Curated open-source skills — every entry is MIT or Apache-2.0 licensed.
   src is either a git repo (pack — installs every SKILL.md) or a raw SKILL.md URL (single skill). */
const SK_RAW='https://raw.githubusercontent.com/anthropics/skills/main/skills/';
const SKILLS_CATALOG=[
  {k:'superpowers',n:'Superpowers (pack)',d:'TDD, systematic debugging, brainstorming, planning, code review — battle-tested engineering skills',lic:'MIT',src:'https://github.com/obra/superpowers.git'},
  {k:'react-best-practices',n:'React Best Practices',d:'Vercel’s official React & Next.js performance rules',lic:'MIT',src:'https://raw.githubusercontent.com/vercel-labs/agent-skills/main/skills/react-best-practices/SKILL.md'},
  {k:'skill-creator',n:'Skill Creator',d:'Teaches the agent to write new high-quality skills',lic:'Apache-2.0',src:SK_RAW+'skill-creator/SKILL.md'},
  {k:'mcp-builder',n:'MCP Builder',d:'Build new MCP servers (Python/Node) the right way',lic:'Apache-2.0',src:SK_RAW+'mcp-builder/SKILL.md'},
  {k:'webapp-testing',n:'Webapp Testing',d:'Test local web apps with Playwright: screenshots, logs, flows',lic:'Apache-2.0',src:SK_RAW+'webapp-testing/SKILL.md'},
  {k:'frontend-design',n:'Frontend Design',d:'Production-grade, distinctive web interfaces',lic:'Apache-2.0',src:SK_RAW+'frontend-design/SKILL.md'},
  {k:'canvas-design',n:'Canvas Design',d:'Visual art, posters & static designs on HTML canvas',lic:'Apache-2.0',src:SK_RAW+'canvas-design/SKILL.md'},
  {k:'algorithmic-art',n:'Algorithmic Art',d:'Generative art: flow fields, particles, fractals',lic:'Apache-2.0',src:SK_RAW+'algorithmic-art/SKILL.md'},
  {k:'brand-guidelines',n:'Brand Guidelines',d:'Apply consistent brand styling to everything produced',lic:'Apache-2.0',src:SK_RAW+'brand-guidelines/SKILL.md'},
  {k:'theme-factory',n:'Theme Factory',d:'Ready-made visual themes for slides, docs & pages',lic:'Apache-2.0',src:SK_RAW+'theme-factory/SKILL.md'},
  {k:'internal-comms',n:'Internal Comms',d:'Status reports, newsletters & FAQs that inform fast',lic:'Apache-2.0',src:SK_RAW+'internal-comms/SKILL.md'},
];
function skillsCatalogHTML(installed){
  const have=e=>installed.some(x=>(x.source||'')===e.src);
  return `<div data-fgroup><div class="sect">Catalog — open-source skills (MIT / Apache-2.0), one click to install</div>
    <div class="cat">${SKILLS_CATALOG.map(e=>`
      <button class="catcard${have(e)?' inst':''}" data-f="${esc(e.n+' '+e.d)}" onclick="installSkillFrom('${e.src}','${esc(e.n)}')">
        <span class="cn">${esc(e.n)}</span><span class="cd">${esc(e.d)}</span>
        <span class="ck" style="color:var(--ok)">${e.lic}</span>
      </button>`).join('')}
    </div></div>`;
}
async function installSkillFrom(src,label){
  toast('installing '+label+'…');
  const r=await fetch('/api/skills/install',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source:src})});
  const d=await r.json();toast(d.ok?`installed ${d.count} skill(s) from ${label}`:d.error);
  refreshApp('skills');refreshApp('store');
}
async function renderSkills(body){
  const r=await fetch('/api/skills');const d=await r.json();
  const items=d.skills.map(s=>`<div class="item" data-f="${esc(s.name+' '+(s.description||''))}">
      <div class="grow"><b>${esc(s.name)}</b><div class="sub">${esc(s.description||'')}</div></div>
      <button title="edit" onclick="editSkill('${s.id}')">✎</button>
      <button onclick="delSkill('${s.id}')">✕</button></div>`).join('');
  const pb=panelShell(body,{
    title:'Skills',
    sub:`${d.skills.length} installed — procedures the agent loads when relevant`,
    search:{id:'sk-q',placeholder:'Search skills & catalog…'},
  });
  pb.innerHTML=`
    <div data-fgroup><div class="sect">Installed</div>
    ${items||emptyBox('No skills yet','A skill is a reusable procedure the agent can pull in when relevant — house rules, runbooks, how-tos. The agent sees the list and loads one with <code>use_skill</code>.','','skills','Write a starter skill from how I like to work.')}
    </div>
    ${skillsCatalogHTML(d.skills)}
    <div data-fgroup>
    <div class="sect" data-f="install from git or url">Install from git or URL</div>
    <div class="row">
      <input id="sk-src" placeholder="https://github.com/user/repo.git  ·  or a raw .md URL">
      <button class="pact" style="flex:0 0 90px" onclick="installSkill()">Install</button>
    </div>
    <p class="mut" style="margin:8px 0 0">Git repos are scanned for <code>SKILL.md</code> files (falling back to all <code>*.md</code>); YAML frontmatter or the first heading names the skill.</p>
    </div>
    <div data-fgroup>
    <div class="sect" data-f="write a skill">Write a skill</div>
    <input id="sk-name" placeholder="name, e.g. deploy-checklist">
    <input id="sk-desc" placeholder="one-line description (the agent reads this to decide relevance)" style="margin-top:8px">
    <textarea id="sk-content" rows="7" placeholder="The procedure, in markdown…" style="margin-top:8px"></textarea>
    <button class="save" onclick="saveSkill()">Save skill</button>
    </div>`;
}
async function saveSkill(){
  const name=$('#sk-name').value.trim(),desc=$('#sk-desc').value.trim(),content=$('#sk-content').value;
  if(!name||!content.trim())return toast('name and content required');
  await fetch('/api/skills',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name,description:desc,content})});
  toast('skill saved');refreshApp('skills');
}
async function editSkill(id){
  const r=await fetch('/api/skills');const d=await r.json();
  const s=d.skills.find(x=>x.id===id);if(!s)return;
  $('#sk-name').value=s.name;$('#sk-desc').value=s.description||'';$('#sk-content').value=s.content||'';
  $('#sk-content').focus();
}
async function delSkill(id){await fetch('/api/skills/'+id,{method:'DELETE'});refreshApp('skills')}
async function installSkill(){
  const src=$('#sk-src').value.trim();if(!src)return toast('enter a git or raw URL');
  toast('⏳ installing…');
  const r=await fetch('/api/skills/install',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source:src})});
  const d=await r.json();toast(d.ok?`installed ${d.count} skill(s)`:d.error);
  refreshApp('skills');
}

/* ================= web launcher (opens in the HOST browser) ================= */
async function openHost(opts){
  try{
    const r=await fetch('/api/open',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(opts)});
    const d=await r.json();
    if(d.ok)toast('↗ opened in your browser'); else toast('open failed: '+(d.error||''));
  }catch(e){toast('open failed')}
}
function openInBrowser(url){openHost({url})}
function renderBrowser(body,w){
  const links=[['DuckDuckGo','https://duckduckgo.com'],['Hacker News','https://news.ycombinator.com'],
    ['GitHub','https://github.com'],['Finance','https://finance.yahoo.com'],['Google','https://google.com']];
  body.innerHTML=`<div class="pad" style="display:flex;flex-direction:column;gap:14px">
    <div style="text-align:center;padding-top:6px">
      <div style="font-size:15px;font-weight:700">Web</div>
      <p class="mut" style="margin-top:4px">Opens pages in your real system browser (Chrome/Firefox) — full sites, logins, extensions.</p>
    </div>
    <div class="apptop" style="border:none;padding:0">
      <input id="wb-url" placeholder="Search or type a URL, then Enter…" style="flex:1">
      <button class="save" style="margin:0;flex:0 0 90px" id="wb-go">Open ↗</button>
    </div>
    <label>Quick links</label>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px">
      ${links.map(([n,u])=>`<button class="catcard" data-u="${esc(u)}"><span class="cn">${esc(n)}</span><span class="cd">${esc(u.replace(/^https?:\/\//,''))}</span></button>`).join('')}
    </div>
  </div>`;
  const norm=u=>{u=u.trim();if(!u)return'';
    if(/^https?:\/\//i.test(u))return u;
    if(/^[\w-]+(\.[\w-]+)+(\/|$|:)/.test(u))return'https://'+u;
    return'https://duckduckgo.com/?q='+encodeURIComponent(u);};
  const go=()=>{const u=norm($('#wb-url').value);if(u)openHost({url:u})};
  $('#wb-go').onclick=go;
  $('#wb-url').addEventListener('keydown',e=>{if(e.key==='Enter')go()});
  body.querySelectorAll('.catcard').forEach(b=>b.onclick=()=>openHost({url:b.dataset.u}));
  if(w._pending){openHost({url:w._pending});w._pending=null}
}

/* ================= native applications launcher ================= */
async function renderNativeApps(body,w){
  body.innerHTML=`<div class="apptop"><input id="na-q" placeholder="Search installed apps…" style="flex:1"><span class="mut" id="na-n"></span></div>
    <div id="na-grid" style="flex:1;overflow-y:auto;padding:12px;display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:6px;align-content:start"></div>`;
  let apps=[];try{apps=(await (await fetch('/api/native/apps')).json()).apps||[]}catch(e){}
  const grid=$('#na-grid');
  const draw=q=>{
    const list=apps.filter(a=>!q||a.name.toLowerCase().includes(q)||(a.comment||'').toLowerCase().includes(q));
    $('#na-n').textContent=list.length+' apps';
    grid.innerHTML=list.map(a=>`<button class="naicon" data-id="${esc(a.id)}" title="${esc(a.comment||a.name)}">
      ${a.has_icon?`<img src="/api/native/icon/${encodeURIComponent(a.id)}" loading="lazy">`:`<span class="nafallback">${esc(a.name[0]||'?')}</span>`}
      <span class="nalbl">${esc(a.name)}</span></button>`).join('')||'<p class="mut">no apps found</p>';
    grid.querySelectorAll('.naicon').forEach(b=>b.onclick=()=>launchNative(b.dataset.id,b.title));
  };
  draw('');
  $('#na-q').addEventListener('input',e=>draw(e.target.value.trim().toLowerCase()));
}
async function launchNative(id,name){
  const r=await fetch('/api/native/launch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});
  const d=await r.json();
  toast(d.ok?'↗ launched '+(name||id):'launch failed: '+(d.message||''));
}

/* ================= model manager ================= */
const MODEL_SUGGEST=['llama3.2','qwen2.5:7b','qwen2.5:14b','gemma2:9b','phi3.5','mistral','llava','nomic-embed-text'];
/* curated local-model catalog — the "extensions" of the model world */
const MODEL_CATALOG=[
  {n:'qwen2.5:14b',d:'Strong tool-calling all-rounder — the best local choice for app builds',s:'9 GB'},
  {n:'qwen2.5:7b',d:'Fast tool-capable daily driver',s:'4.7 GB'},
  {n:'qwen2.5-coder:14b',d:'Code generation specialist — great for App Studio',s:'9 GB'},
  {n:'llama3.1:8b',d:'Solid general model with tool support',s:'4.9 GB'},
  {n:'llama3.2',d:'Light and quick for simple chat',s:'2 GB'},
  {n:'deepseek-r1:14b',d:'Reasoning / chain-of-thought specialist',s:'9 GB'},
  {n:'phi4',d:'Compact Microsoft reasoning model',s:'9.1 GB'},
  {n:'mistral',d:'Classic fast 7B',s:'4.1 GB'},
  {n:'gemma2:9b',d:'Good chat quality (weak at tool calls — avoid for builds)',s:'5.4 GB'},
  {n:'llava',d:'Vision — understands screenshots and images',s:'4.7 GB'},
  {n:'qwen2.5:32b',d:'Highest local quality if you have 20+ GB VRAM',s:'20 GB'},
  {n:'nomic-embed-text',d:'Embeddings for search and memory indexing',s:'274 MB'},
];
async function renderModels(body){
  const [d,d2]=await Promise.all([
    fetch('/api/models/manage').then(r=>r.json()),
    fetch('/api/models').then(r=>r.json()).catch(()=>({models:[],default:''}))]);
  const fmtB=n=>n>=1e9?(n/1e9).toFixed(1)+' GB':(n/1e6).toFixed(0)+' MB';
  const running=new Set((d.running||[]).map(m=>m.name));
  const installed=new Set((d.models||[]).map(m=>m.name));
  const gpu=(d.gpu||[]).map(g=>`<div class="stat"><div class="lbl">${esc(g.name)}</div>
    <div class="val">${(g.mem_used_mb/1024).toFixed(1)}<small> / ${(g.mem_total_mb/1024).toFixed(0)} GB · ${g.util}%</small></div>
    <div class="bar"><i style="width:${100*g.mem_used_mb/g.mem_total_mb}%" class="${g.mem_used_mb/g.mem_total_mb>.85?'hot':''}"></i></div></div>`).join('');
  const all=d2.models||[],dft=d2.default||'';
  const provBadge=p=>p==='ollama'?'<span class="badge">local</span>':`<span class="badge" style="color:var(--acc2)">${esc(p)}</span>`;
  const configured=all.map(m=>`<div class="item" data-f="${esc(m.id+' '+m.provider)}">
      <div class="grow"><b>${esc(m.name)}</b> ${provBadge(m.provider)} ${m.id===dft?'<span class="badge ok">✓ default</span>':''}
        <div class="sub">${esc(m.id)}</div></div>
      ${m.id===dft?'':`<button class="endbtn" style="border-color:var(--line);color:var(--dim)" onclick="modelSetDefault('${esc(m.id)}')">Set default</button>`}
    </div>`).join('');
  const pb=panelShell(body,{
    title:'Model Manager',
    sub:`${all.length} configured · ${(d.models||[]).length} local · ${(d.running||[]).length} loaded`,
    search:{id:'mdl-q',placeholder:'Search models & catalog…'},
  });
  pb.innerHTML=`
    ${gpu?`<div class="sect">GPU</div><div class="tmgrid" style="grid-template-columns:1fr">${gpu}</div>`:'<p class="mut">No NVIDIA GPU detected (models run on CPU).</p>'}
    <div data-fgroup><div class="sect">Configured models — chat, builds and scheduled tasks use the default</div>
    ${configured||emptyBox('No models configured','Start Ollama for local models, or add a cloud API key in Settings.','','models','Help me set up a model that fits this machine.')}
    <p class="mut" style="margin:6px 0 0">Cloud providers (Anthropic, OpenAI, OpenRouter…) appear here once their API key is set in <a href="#" onclick="openApp('settings');return false" style="color:var(--acc2)">Settings</a>. Tool-capable models (qwen, claude, gpt) make builds far more reliable.</p></div>
    <div data-fgroup><div class="sect">Local models on disk (Ollama)</div>
    <div id="mdl-list">${(d.models||[]).map(m=>`<div class="item" data-f="${esc(m.name+' '+(m.family||'')+' '+(m.params||''))}">
      <div class="grow"><b>${esc(m.name)}</b> ${running.has(m.name)?'<span class="badge ok">● loaded</span>':''}
        <div class="sub">${fmtB(m.size)}${m.params?' · '+esc(m.params):''}${m.family?' · '+esc(m.family):''}</div></div>
      <button onclick="modelDelete('${esc(m.name)}')" title="delete">✕</button></div>`).join('')||emptyBox('No local models yet','Pull one from the catalog below — downloads run in the background and show progress here.')}</div>
    <div id="mdl-prog" class="mut" style="margin:8px 0"></div></div>
    <div data-fgroup><div class="sect">Get more models</div>
    <div class="cat">${MODEL_CATALOG.map(e=>`
      <div class="catcard${installed.has(e.n)?' inst':''}" data-f="${esc(e.n+' '+e.d)}">
        <span class="cn">${esc(e.n)}</span><span class="cd">${esc(e.d)}</span>
        <span class="ck" style="color:var(--dim2)">${esc(e.s)}</span>
        <button class="save" style="margin-top:8px;padding:6px" ${installed.has(e.n)?'disabled':''} onclick="modelPull('${e.n}')">${installed.has(e.n)?'✓ Installed':'Pull'}</button>
      </div>`).join('')}</div>
    <div class="row" style="margin-top:8px"><input id="mdl-name" placeholder="any model from ollama.com/library — e.g. qwen3:8b" list="mdl-sug">
      <datalist id="mdl-sug">${MODEL_SUGGEST.map(s=>`<option value="${s}">`).join('')}</datalist>
      <button class="pact" style="flex:0 0 90px" onclick="modelPull()">Pull</button></div>
    <p class="mut" style="margin-top:10px">Downloads run in the background. Pick sizes your GPU can hold — a ~14B model needs roughly 9–10 GB of VRAM.</p></div>`;
  $('#mdl-name').addEventListener('keydown',e=>{if(e.key==='Enter')modelPull()});
}
async function modelSetDefault(id){
  await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({default_model:id})});
  toast('default model: '+id);
  loadModels();refreshApp('models');
}
async function modelPull(name){
  name=(name||$('#mdl-name')?.value||'').trim();if(!name)return toast('enter a model name');
  await fetch('/api/models/pull',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
  toast('downloading '+name);
}
async function modelDelete(name){
  if(!await osConfirm('Delete model '+name+'?','',{danger:true,confirmText:'Delete'}))return;
  await fetch('/api/models/'+encodeURIComponent(name),{method:'DELETE'});
  toast('removed '+name);refreshApp('models');loadModels();
}

