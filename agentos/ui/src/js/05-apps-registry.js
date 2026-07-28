/* ================= apps ================= */
const APPS={
  chat:{id:'chat',title:'Agent Chat',icon:'',w:920,h:620,desc:'Talk to your machine',
    render:renderChat,
    onClose(w){
      if(running){minimizeWin(w);toast('agent is still working — window minimized');return false}
      feed=chatEl=input=sendBtn=null;curBody=null;curThink=null;curText='';
      return true;
    }},
  taskmgr:{id:'taskmgr',title:'Task Manager',icon:'',w:660,h:560,desc:'CPU, memory, processes',
    render:renderTaskMgr,onClose(w){clearInterval(w.timer);return true}},
  terminal:{id:'terminal',title:'Terminal',icon:'',w:860,h:520,desc:'A real shell on this machine',multi:true,
    render:renderTerminal,onClose(w){try{w.ro?.disconnect();w.tws?.close();w.term?.dispose()}catch(e){}return true},
    menus:w=>[['Edit',[
      {label:'Clear the screen',fn:()=>{try{w.term.clear()}catch(e){}}},
      {label:'Copy the selection',fn:()=>{try{navigator.clipboard.writeText(w.term.getSelection()||'')}catch(e){}}},
    ]]]},
  browser:{id:'browser',title:'Web',icon:'',w:520,h:440,desc:'Open the web in your system browser',render:renderBrowser},
  files:{id:'files',title:'Files',icon:'',w:720,h:560,desc:'Your workspace files & reports',multi:true,render:renderFiles,
    menus:w=>[['File',[
      {label:'Go to workspace root',fn:()=>{w.path='';renderFiles(w.el.querySelector('.wbody'),w)}},
      {label:'Go up one folder',fn:()=>{w.path=(w.path||'').split('/').slice(0,-1).join('/');renderFiles(w.el.querySelector('.wbody'),w)}},
      {label:'Copy this path',fn:()=>{navigator.clipboard.writeText(w.path||'.').then(()=>toast('path copied'))}},
    ]]]},
  apps:{id:'apps',title:'Applications',icon:'',w:760,h:600,desc:'All your installed desktop apps',render:renderNativeApps},
  control:{id:'control',title:'Quick Settings',icon:'',w:520,h:560,desc:'Sound, brightness, network, battery',render:renderControl},
  syssettings:{id:'syssettings',title:'System Settings',icon:'⚙',w:760,h:640,desc:'Network, bluetooth, displays, sound, power, session',render:renderSysSettings},
  models:{id:'models',title:'Model Manager',icon:'',w:620,h:560,desc:'Manage local AI models & GPU',render:renderModels},
  memory:{id:'memory',title:'Memory',icon:'◈',w:640,h:540,desc:'User & session memory — what the agent remembers',render:renderMemory},
  profile:{id:'profile',title:'Profile',icon:'',w:700,h:620,desc:'Everything the agent knows about you, in one place',render:renderProfile},
  fabric:{id:'fabric',title:'Team',icon:'',w:860,h:660,desc:'Subagents, visual workflows & data-plane observability',render:renderFabric},
  docs:{id:'docs',title:'Docs',icon:'',w:900,h:640,desc:'The full AgentOS manual, right here',render:renderDocs},
  kg:{id:'kg',title:'Knowledge Graph',icon:'',w:820,h:600,desc:'What the agent knows, as a graph',
    render:renderKG,onClose(w){cancelAnimationFrame(w.raf);return true}},
  soul:{id:'soul',title:'Soul',icon:'',w:640,h:580,desc:'The agent\'s persistent identity',render:renderSoul},
  mcp:{id:'mcp',title:'MCP Servers',icon:'',w:680,h:600,desc:'External tools via Model Context Protocol',render:renderMCP},
  telegram:{id:'telegram',title:'Telegram',icon:'',w:560,h:560,desc:'Chat with your machine from anywhere',render:renderTelegram},
  logs:{id:'logs',title:'Logs',icon:'',w:760,h:560,desc:'Everything the system did',
    render:renderLogs,onClose(w){clearInterval(w.timer);return true}},
  tasks:{id:'tasks',title:'Scheduler',icon:'',w:620,h:520,desc:'Recurring background tasks',render:renderTasks},
  automations:{id:'automations',title:'Automations',icon:'',w:760,h:640,desc:'Named routines & hot corners',render:renderAutomations},
  skills:{id:'skills',title:'Skills',icon:'',w:700,h:600,desc:'Reusable procedures — install from git or URL',render:renderSkills},
  policies:{id:'policies',title:'Policies',icon:'',w:620,h:540,desc:'Always-allow / always-deny rules',render:renderPolicies},
  permissions:{id:'permissions',title:'Permissions',icon:'',w:940,h:680,desc:'Policy console — maps, grants, review & attach',render:renderPermissions},
  store:{id:'store',title:'Store',icon:'',w:760,h:620,desc:'Install apps, channels & skills — or build with AI',render:renderStore},
  studio:{id:'studio',title:'App Studio',icon:'',w:1080,h:680,desc:'Build & edit apps — ask the agent to make them',render:renderStudio},
  themes:{id:'themes',title:'Themes',icon:'',w:720,h:600,desc:'Switch, build & AI-design desktop themes',render:renderThemes},
  personalize:{id:'personalize',title:'Personalize',icon:'',w:620,h:560,desc:'AI wallpapers & gallery',render:renderPersonalize},
  snapshots:{id:'snapshots',title:'Snapshots',icon:'',w:560,h:500,desc:'Restore points — roll the OS back in time',render:renderSnapshots},
  tokens:{id:'tokens',title:'Token Analytics',icon:'',w:600,h:540,desc:'Token usage over time, by model',render:renderTokens},
  train:{id:'train',title:'Train',icon:'',w:1100,h:700,desc:'Fine-tune & evaluate your own models (TrainForge)',
    render:renderTrain,onClose(w){clearInterval(w.timer);if(w._onSetup)TRAIN_SETUP_LISTENERS.delete(w._onSetup);return true}},
  mission:{id:'mission',title:'Mission Control',icon:'◎',w:860,h:600,desc:'The whole lifecycle: Train · Test · Operate · Build · Ship · Manage',
    render:renderMission,onClose(w){clearInterval(w.timer);return true}},
  hermes:{id:'hermes',title:'Hermes',icon:'🜁',w:820,h:660,desc:'Download, configure & control the Hermes agent — use it as your engine',
    render:renderHermes,onClose(w){clearInterval(w.timer);if(w._onSetup)HERMES_SETUP_LISTENERS.delete(w._onSetup);return true}},
  settings:{id:'settings',title:'Settings',icon:'',w:620,h:640,desc:'Providers, voice, autonomy',render:renderSettings},
  about:{id:'about',title:'About AgentOS',icon:'▲',w:400,h:330,desc:'System information',render:renderAbout},
};

/* ---- copilot context: one line about what each app is showing RIGHT NOW.
   Sync + cheap by design (globals/DOM only) — it's a hint for the embedded
   agent, which can always call tools for authoritative data. ---- */
const APP_CTX={
  chat:()=>`the full chat window; current conversation ${currentConv||'(none)'}${RUNNING.size?', a turn is running':''}`,
  files:w=>`browsing "${w.path||'workspace root'}"${document.querySelectorAll('.fitem').length?` (${document.querySelectorAll('.fitem').length} entries visible)`:''}`,
  terminal:()=>'a live shell on this machine (the user may have a command or error on screen)',
  browser:()=>'the web launcher (opens URLs in the host browser)',
  apps:()=>`the installed native applications grid (${(typeof NATIVEAPPS!=='undefined'&&NATIVEAPPS.length)||0} apps)`,
  control:()=>'Quick Settings: volume, brightness, network, battery, DND',
  syssettings:()=>`System Settings, "${(typeof SYS_TABS!=='undefined'&&SYS_TABS[SYS.tab])||'Network'}" tab open`,
  models:()=>'the local/cloud model manager (Ollama models, GPU/VRAM)',
  memory:()=>`the memory browser, ${typeof memTab!=='undefined'?memTab:'user'} scope, ${Object.keys(window.__mems||{}).length||'?'} memories loaded`,
  profile:()=>'the profile view — everything the agent knows about the user',
  fabric:()=>`the Team app, "${typeof fabTab!=='undefined'?fabTab:'team'}" tab (subagents & workflows)`,
  docs:()=>'the AgentOS manual',
  kg:()=>'the knowledge graph visualization',
  soul:()=>'the agent soul (persistent identity) editor',
  mcp:()=>'MCP server management (connections, tools, env)',
  telegram:()=>'the Telegram bridge (chats, channels, permissions)',
  logs:()=>'the system log viewer',
  tasks:()=>`the Scheduler (${document.querySelectorAll('#tasklist [data-f]').length||'some'} scheduled tasks & triggers listed)`,
  taskmgr:()=>{const c=$('#tm-cpu'),m=$('#tm-mem');return `Task Manager${c?` — CPU ${c.textContent}, RAM ${m?m.textContent:'?'}`:''}`},
  skills:()=>'the skills library (reusable procedures)',
  policies:()=>'always-allow / always-deny policy rules',
  permissions:()=>'the policy console: permission maps, grants, IO gates',
  store:()=>'the Store: app templates, MCP discovery, build-with-AI',
  studio:()=>`App Studio${typeof STUDIO!=='undefined'&&STUDIO.sel?`, editing app "${STUDIO.sel}"`:''}${typeof STUDIO!=='undefined'&&STUDIO.building?' (a build is RUNNING)':''}`,
  themes:()=>`the theme gallery (current theme: ${typeof CURRENT_THEME!=='undefined'?CURRENT_THEME:'agentos'})`,
  personalize:()=>'AI wallpaper generation + gallery',
  snapshots:()=>'OS restore points',
  tokens:()=>'token usage analytics',
  train:()=>'TrainForge — fine-tuning datasets, jobs, models',
  mission:()=>'Mission Control: the Train/Test/Operate/Build/Ship/Manage lifecycle dashboard',
  hermes:()=>'the Hermes companion-agent app (install, config, gateway)',
  settings:()=>'core settings: providers, API keys, autonomy, voice',
  about:()=>'system information',
};
Object.keys(APP_CTX).forEach(id=>{if(APPS[id])APPS[id].context=APP_CTX[id]});

/* ================= desktop icons / start menu / ctx menu ================= */
const DESKTOP_APPS=['chat','mission','apps','browser','files','terminal','control','syssettings','store','taskmgr','models','kg','soul','memory','profile','fabric','skills','studio','train','hermes','mcp','telegram','policies','permissions','logs','tokens','tasks','themes','personalize','snapshots','docs','settings','about'];
let USERAPPS=[];
async function loadUserApps(){
  try{const r=await fetch('/api/apps');const d=await r.json();USERAPPS=d.apps||[]}catch(e){USERAPPS=[]}
  Object.keys(APPS).filter(k=>k.startsWith('ua_')).forEach(k=>{
    if(!USERAPPS.find(a=>'ua_'+a.id===k)){const w=WM.wins.get(k);if(w)closeWin(w);delete APPS[k]}
  });
  USERAPPS.forEach(a=>{
    APPS['ua_'+a.id]={id:'ua_'+a.id,title:a.name,icon:a.icon||'',w:640,h:520,desc:a.description||'user app',
      render(body){body.innerHTML=`<iframe src="/api/apps/${a.id}/page" style="flex:1;border:none;background:#0e1116" sandbox="allow-scripts allow-same-origin allow-forms"></iframe>`}};
  });
  rebuildLaunchers();
  renderWidgets();
}
function launcherIds(){return [...DESKTOP_APPS,...USERAPPS.map(a=>'ua_'+a.id)]}
/* user-app management: rename anywhere (desktop right-click, App Studio ✏️) */
function uaCtxMenu(e,aid){
  const a=USERAPPS.find(x=>x.id===aid);
  const m=$('#ctxmenu');
  m.innerHTML=`<button data-a="open">Open</button>
    <button data-a="ren">✏️ Rename…</button>
    <button data-a="studio">Edit in App Studio</button><hr>
    <button data-a="del" style="color:var(--err,#f87171)">Delete app</button>`;
  m.querySelector('[data-a=open]').onclick=()=>{m.classList.remove('show');openApp('ua_'+aid)};
  m.querySelector('[data-a=ren]').onclick=()=>{m.classList.remove('show');renameUserApp(aid)};
  m.querySelector('[data-a=studio]').onclick=()=>{m.classList.remove('show');STUDIO.sel=aid;openApp('studio');refreshApp('studio')};
  m.querySelector('[data-a=del]').onclick=async()=>{m.classList.remove('show');
    if(!await osConfirm('Delete "'+(a?a.name:aid)+'"?','Its data, versions and grants go with it.',{confirmText:'Delete',danger:true}))return;
    await fetch('/api/apps/'+aid,{method:'DELETE'});
    toast('deleted');loadUserApps()};
  ctxShow(e,m);
}
async function renameUserApp(aid,from){
  const a=USERAPPS.find(x=>x.id===aid)||((typeof STUDIO!=='undefined'&&STUDIO.apps)||[]).find(x=>x.id===aid);
  const cur=a?a.name:'';
  const v=await osPrompt('New name for "'+cur+'"',{value:cur,confirmText:'Rename'});
  if(v===null||!v.trim()||v.trim()===cur)return;
  const r=await fetch('/api/apps/'+aid,{method:'PUT',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:v.trim()})});
  const d=await r.json().catch(()=>({}));
  if(!r.ok)return toast(d.error||'rename failed');
  toast('renamed to "'+v.trim()+'"');
  loadUserApps();
  if(from==='studio')refreshApp('studio');
}
/* native (system) apps installed on the host — shown in the start menu & command palette */
let NATIVEAPPS=[];
async function loadNativeApps(){
  try{const d=await (await fetch('/api/native/apps')).json();NATIVEAPPS=d.apps||[]}catch(e){NATIVEAPPS=[]}
  rebuildLaunchers();
}
function nativeIcon(a,px){
  px=px||44;
  return a.has_icon?`<img class="na" src="/api/native/icon/${encodeURIComponent(a.id)}" loading="lazy" alt="" style="width:${px}px;height:${px}px;object-fit:contain">`
    :`<span class="nafallback" style="width:${px}px;height:${px}px;font-size:${Math.round(px*.43)}px">${esc(a.name.charAt(0)||'?')}</span>`;
}
let ICONPOS=JSON.parse(localStorage.getItem('iconpos')||'{}');
function saveIconPos(){localStorage.setItem('iconpos',JSON.stringify(ICONPOS))}
// give each app a distinct, pleasant tile color (like a real app grid) derived from its id
function tileBg(id){
  let h=0;for(const c of id)h=(h*33+c.charCodeAt(0))%360;
  const h2=(h+34)%360;
  return `linear-gradient(150deg,hsl(${h} 46% 40%),hsl(${h2} 52% 26%))`;
}
function rebuildLaunchers(){
  const box=$('#icons');box.innerHTML='';
  launcherIds().forEach((id,i)=>{
    const a=APPS[id];if(!a)return;
    const d=document.createElement('div');d.className='dicon';d.tabIndex=0;d.dataset.id=id;
    d.innerHTML=`${appIcon(id,54)}<div class="dlbl">${esc(a.title)}</div>`;
    // position: saved, else a default column-major grid down the left edge
    if(!ICONPOS[id])ICONPOS[id]={x:GRID.ox+Math.floor(i/8)*GRID.cx,y:GRID.oy+(i%8)*GRID.cy};
    d.style.left=ICONPOS[id].x+'px';d.style.top=ICONPOS[id].y+'px';
    d.onkeydown=e=>{if(e.key==='Enter')openApp(id)};
    if(id.startsWith('ua_'))  // user-built apps get their own menu: rename & delete
      d.oncontextmenu=e=>{e.preventDefault();e.stopPropagation();uaCtxMenu(e,id.slice(3))};
    iconDrag(d,id);
    box.appendChild(d);
  });
  renderBento();
  ensureMarquee();
  smRender(($('#smq')?.value||'').trim().toLowerCase());
}
function smRender(q){
  const sm=$('#smapps');sm.innerHTML='';
  const hit=t=>!q||t.toLowerCase().includes(q);
  const sect=t=>{const d=document.createElement('div');d.className='smsect';d.textContent=t;sm.appendChild(d)};
  const own=launcherIds().filter(id=>APPS[id]&&hit(APPS[id].title+' '+(APPS[id].desc||'')));
  if(own.length){
    sect('Apps');
    own.forEach(id=>{
      const a=APPS[id];
      const b=document.createElement('button');b.className='smapp';b.title=a.desc||'';
      b.innerHTML=`${appIcon(id,48)}<span class="n">${esc(a.title)}</span>`;
      b.onclick=()=>{toggleStart(false);openApp(id)};
      sm.appendChild(b);
    });
  }
  const nat=NATIVEAPPS.filter(a=>hit(a.name+' '+(a.comment||'')));
  if(nat.length){
    sect('System apps');
    nat.forEach(a=>{
      const b=document.createElement('button');b.className='smapp';b.title=a.comment||a.name;
      b.innerHTML=`${nativeIcon(a,44)}<span class="n">${esc(a.name)}</span>`;
      b.onclick=()=>{toggleStart(false);launchNative(a.id,a.name)};
      sm.appendChild(b);
    });
  }
  if(!own.length&&!nat.length)sm.innerHTML='<p class="mut" style="grid-column:1/-1;padding:14px 6px">nothing matches</p>';
}
