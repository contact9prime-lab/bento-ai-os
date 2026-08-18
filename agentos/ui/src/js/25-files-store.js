/* ================= file manager app ================= */
async function renderFiles(body,w){
  w.path=w.path||'';
  const FCOLORS={html:'#38BDF8',htm:'#38BDF8',md:'#a5b4fc',txt:'#8a94a6',json:'#fbbf24',csv:'#4ade80',
    log:'#8a94a6',pdf:'#f87171',sh:'#94a3b8',py:'#60a5fa'};
  const IMG_EXT=new Set(['png','jpg','jpeg','gif','webp','svg']);
  const icon=e=>{
    const s='width:17px;height:17px;display:block';
    if(e.dir)return `<svg viewBox="0 0 24 24" style="${s}"><path d="M3.5 7c0-.9.7-1.6 1.5-1.6h4.2l2 2.4h7.8c.8 0 1.5.7 1.5 1.6v8c0 .9-.7 1.6-1.5 1.6H5c-.8 0-1.5-.7-1.5-1.6Z" fill="#5EA3F7"/></svg>`;
    if(IMG_EXT.has(e.ext))return `<svg viewBox="0 0 24 24" fill="none" stroke="#2DD4BF" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" style="${s}"><rect x="4" y="5" width="16" height="14" rx="2"/><circle cx="9" cy="10" r="1.5"/><path d="M4.4 16.4l4.3-3.8 3.4 2.9 3-2.5 4.5 3.6"/></svg>`;
    const c=FCOLORS[e.ext]||'#8a94a6';
    return `<svg viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" style="${s}"><path d="M6.5 4h7l4 4v12h-11Z"/><path d="M13.5 4v4h4"/></svg>`;
  };
  const fmt=n=>n<1024?n+' B':n<1e6?(n/1024).toFixed(0)+' KB':(n/1e6).toFixed(1)+' MB';
  let d;try{d=await (await fetch('/api/files?path='+encodeURIComponent(w.path))).json()}catch(e){body.innerHTML='<p class="mut" style="padding:16px">could not read files</p>';return}
  w.path=d.path;
  const crumbs=['<span class="fcrumb" data-p="">workspace</span>'];
  let acc='';d.path.split('/').filter(Boolean).forEach(seg=>{acc=acc?acc+'/'+seg:seg;crumbs.push('<span class="fsep">/</span><span class="fcrumb" data-p="'+esc(acc)+'">'+esc(seg)+'</span>')});
  body.innerHTML=`<div class="apptop">
      ${w.path?'<button class="endbtn f-up">Up</button>':''}
      <div style="flex:1;font-size:var(--fs-sm)" class="f-crumbs">${crumbs.join('')}</div>
      <span class="psearch" style="flex:0 0 220px">${SVG_SEARCH}<input class="f-search" placeholder="Search by meaning…" autocomplete="off"></span>
      <button class="endbtn" onclick="refreshApp('files')">⟳</button>
    </div>
    <div class="f-list" style="flex:1;overflow-y:auto;padding:6px 8px;user-select:text">
      ${d.entries.length?d.entries.map(e=>`<div class="fitem" data-rel="${esc(e.rel)}" data-dir="${e.dir?1:0}" data-ext="${esc(e.ext)}">
        <span class="fi">${icon(e)}</span><span class="fn">${esc(e.name)}</span>
        <span class="fmeta">${e.dir?'':fmt(e.size)+' · '+new Date(e.mtime*1000).toLocaleDateString()}</span>
      </div>`).join(''):'<p class="mut" style="padding:14px">empty folder</p>'}
    </div>`;
  // scoped lookups — Files is multi-instance, so no bare $('#…') in here
  body.querySelector('.f-crumbs').querySelectorAll('.fcrumb').forEach(c=>c.onclick=()=>{w.path=c.dataset.p;renderFiles(body,w)});
  const up=body.querySelector('.f-up');if(up)up.onclick=()=>{w.path=w.path.split('/').slice(0,-1).join('/');renderFiles(body,w)};
  const wire=()=>body.querySelectorAll('.fitem').forEach(it=>it.onclick=()=>{
    const rel=it.dataset.rel;
    if(it.dataset.dir==='1'){w.path=rel;renderFiles(body,w)}
    else openFile(rel,it.dataset.ext);
  });
  wire();
  // semantic search: meaning-ranked over the workspace + docs, substring fallback server-side
  const si=body.querySelector('.f-search');let st;
  si.oninput=()=>{
    clearTimeout(st);
    const q=si.value.trim();
    const list=body.querySelector('.f-list');
    if(!q){renderFiles(body,w);return}
    st=setTimeout(async()=>{
      list.innerHTML='<p class="mut" style="padding:14px">searching…</p>';
      let d2;try{d2=await (await fetch('/api/search?q='+encodeURIComponent(q))).json()}catch(e){d2={results:[]}}
      const res=d2.results||[];
      list.innerHTML=res.length?res.map(r=>`<div class="fitem fhit" data-path="${esc(r.path)}">
          <span class="fi">${icon({ext:(r.path.split('.').pop()||'').toLowerCase()})}</span>
          <span class="fn">${esc(r.path.split('/').pop())}<div class="fsnip">${esc(r.snippet)}</div></span>
          <span class="fmeta">${r.kind}</span>
        </div>`).join(''):'<p class="mut" style="padding:14px">nothing matched — the index may still be warming up</p>';
      list.querySelectorAll('.fhit').forEach(h=>h.onclick=()=>openHost({path:h.dataset.path}));
    },300);
  };
}
function openFile(rel,ext){
  // open the real file in the HOST OS default app (browser for html/pdf, viewer for images, etc.)
  openHost({path:rel});
}

/* ================= store ================= */
let STORE_TAB='apps';
async function renderStore(body,w){
  const TABS=['apps','discover','extensions','skills','import','build'];
  const box=panelShell(body,{
    title:'Store',
    search:STORE_TAB==='import'||STORE_TAB==='build'||STORE_TAB==='discover'?null:{id:'store-q',placeholder:'Search the catalog…'},
    actions:segTabs('store-tabs',['Apps','Discover','Extensions','Skills','Import','Build with AI'],TABS.indexOf(STORE_TAB),'storeSetTab'),
  });
  if(STORE_TAB==='discover'){renderStoreDiscover(box);return}
  if(STORE_TAB==='apps'){
    const d=await (await fetch('/api/store/templates')).json();
    box.innerHTML=`<p class="mut" style="margin-bottom:10px">One-click apps — install instantly, then open or pin them to the desktop.</p>
      <div class="cat">${d.templates.map(t=>`<div class="catcard" data-f="${esc(t.name+' '+t.desc)}">
        <span class="cn">${esc(t.name)}</span><span class="cd">${esc(t.desc)}</span>
        <button class="save" style="margin-top:8px;padding:6px" ${t.installed?'disabled':''} onclick="storeInstall('${t.id}')">${t.installed?'✓ Installed':'Install'}</button>
      </div>`).join('')}</div>`;
  } else if(STORE_TAB==='extensions'){
    const r=await fetch('/api/mcp');const md=await r.json();
    MCPCFG={};   // keep the full current config so adding one doesn't wipe the rest
    md.servers.forEach(s=>{MCPCFG[s.name]=mcpSnap(s)});
    const have=new Set(md.servers.map(s=>s.name));
    box.innerHTML=`<p class="mut" style="margin-bottom:10px">Extensions (MCP) give the agent new powers — browser control, GitHub, search, and more.</p>
      ${MCP_GROUPS.map((g,gi)=>`<div data-fgroup><div class="sect">${esc(g)}</div>
      <div class="cat">${MCP_CATALOG.filter(e=>e.g===gi).map(e=>`<div class="catcard${have.has(e.k)?' inst':''}" data-f="${esc(e.n+' '+e.d)}">
        <span class="cn">${esc(e.n)}</span><span class="cd">${esc(e.d)}</span>
        ${mcpBadge(e)}
        <button class="save" style="margin-top:8px;padding:6px" ${have.has(e.k)?'disabled':''} onclick="mcpPreset('${e.k}');toast('connecting ${esc(e.n)}…')">${have.has(e.k)?'✓ Connected':'Add'}</button>
      </div>`).join('')}</div></div>`).join('')}`;
  } else if(STORE_TAB==='skills'){
    const d=await (await fetch('/api/skills')).json();
    box.innerHTML=`<p class="mut" style="margin-bottom:10px">Skills are reusable procedures the agent follows. Install from the catalog, a git repo, or a raw .md URL.</p>
      ${skillsCatalogHTML(d.skills)}
      <div class="row" style="margin-top:8px"><input id="store-sk" placeholder="https://github.com/user/repo.git  ·  or a raw .md URL">
        <button class="pact" style="flex:0 0 90px" onclick="storeInstallSkill()">Install</button></div>
      <div data-fgroup><div class="sect">Installed (${d.skills.length})</div>
      ${d.skills.map(s=>`<div class="item" data-f="${esc(s.name+' '+(s.description||''))}"><div class="grow"><b>${esc(s.name)}</b><div class="sub">${esc(s.description||'')}</div></div></div>`).join('')||'<p class="mut">none yet</p>'}</div>`;
  } else if(STORE_TAB==='import'){
    box.innerHTML=`<p class="mut" style="margin-bottom:10px">Install an app package (<code>.agentapp.json</code>) shared from another AgentOS.
      You review its permissions before anything runs; missing MCP extensions & skills are offered as one-click installs (you supply any API keys).</p>
      <div class="row"><input id="store-pkg-url" placeholder="https://…/app.agentapp.json">
        <button class="pact" style="flex:0 0 110px" onclick="storeImportURL()">Fetch</button></div>
      <div class="row" style="margin-top:8px"><input type="file" id="store-pkg-file" accept=".json,.agentapp.json" style="flex:1">
        <button class="pact" style="flex:0 0 110px" onclick="storeImportFile()">Import file</button></div>
      <p class="mut" style="margin-top:12px;font-size:11px">Packages carry a checksum — modified packages are refused. Secrets are never inside a package.</p>`;
  } else {
    box.innerHTML=`<div style="text-align:center;padding:24px">
      <div style="font-size:16px;font-weight:700;margin:8px 0">Build any app with AI</div>
      <p class="mut" style="max-width:420px;margin:0 auto 16px">Describe what you want and ${esc(agentName())} builds a working app for it — live. It can call the OS, run tools, and fetch data.</p>
      <input id="store-build" placeholder="e.g. a habit tracker with daily checkboxes" style="width:100%;max-width:460px">
      <div style="margin-top:10px"><button class="save" style="display:inline-block;width:auto;padding:9px 22px" onclick="storeBuild()">Build it</button></div>
      <p class="mut" style="margin-top:12px;font-size:11px">Tip: builds work best with a tool-capable model (a qwen model) selected in chat.</p>
    </div>`;
    $('#store-build').addEventListener('keydown',e=>{if(e.key==='Enter')storeBuild()});
  }
}
function storeSetTab(i){STORE_TAB=['apps','discover','extensions','skills','import','build'][i];refreshApp('store')}

/* ---- Discover: search the worldwide public MCP registry, install with consent,
   record in the local MCP Registry (+ generated docs), then build an app on top ---- */
let STORE_DISC={q:'',results:[],seq:0,ctl:null};
function renderStoreDiscover(box){
  box.innerHTML=`<p class="mut" style="margin-bottom:10px">Search the public MCP registry — thousands of servers published by the community.
    Installing one adds it to your <b>MCP Registry</b>, writes a manual page into Docs, and puts it under the permission framework. Then build an app around it.</p>
    <div class="row"><input id="disc-q" placeholder="What capability do you need? e.g. weather, github, postgres, calendar…" value="${esc(STORE_DISC.q)}" autocomplete="off">
      <span class="mut" id="disc-st" style="flex:0 0 auto;font-size:11px"></span></div>
    <div id="disc-results" class="cat" style="margin-top:10px">${storeDiscoverCards()}</div>`;
  STORE_DISC._sig=discSig();  // the grid just rendered — cache its signature
  const inp=$('#disc-q');
  let deb; // results come in as you type — no Search button to wait on
  inp.addEventListener('input',()=>{clearTimeout(deb);deb=setTimeout(()=>storeDiscover(inp.value.trim()),350)});
  inp.addEventListener('keydown',e=>{if(e.key==='Enter'){clearTimeout(deb);storeDiscover(inp.value.trim())}});
  inp.focus();
  if(STORE_DISC.q&&!STORE_DISC.results.length)storeDiscover(STORE_DISC.q);
}
function storeDiscoverCards(){
  if(!STORE_DISC.results.length)
    return `<p class="mut" style="grid-column:1/-1">${STORE_DISC.q?'nothing found — try a broader term':'start typing to search the worldwide registry…'}</p>`;
  return STORE_DISC.results.map((c,i)=>{
    const req=[...(c.env||[]).filter(e=>e.required).map(e=>e.name),
               ...(c.remote_headers||[]).filter(h=>h.required).map(h=>h.name)];
    const kind=c.origin_source==='github'?'GitHub repo':c.origin_source==='npm'?'npm (beyond the registry)'
              :c.remote_url?'remote':(c.registry_type||'package');
    return `<div class="catcard${c.installed?' inst':''}" title="${esc(c.registry_name)}${c.version?' · v'+esc(c.version):''}">
      <span class="cn">${esc(c.registry_name.split(/[/:]/).pop())}</span>
      <span class="cd" style="display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden">${esc(c.description||'(no description)')}</span>
      <span class="ck">${esc(kind)}${req.length?' · 🔑 key needed':''}${c.homepage?` · <a href="${esc(c.homepage)}" target="_blank" style="color:var(--acc2,#22d3ee)" onclick="event.stopPropagation()">homepage ↗</a>`:''}</span>
      ${c.agentic
        ?`<button class="save" style="margin-top:8px;padding:6px" title="No published package — the agent reads the repo, works out how to run it, and connects it (you approve each step)" onclick="storeAgentSetup(${i})">🤖 Set up with AI</button>`
        :`<button class="save" style="margin-top:8px;padding:6px" onclick="storeDiscoverInstall(${i})">Install</button>`}
    </div>`}).join('');
}
function discSig(){
  return STORE_DISC.results.map(c=>c.registry_name+(c.installed?'+':'')).join('|')
         +'|'+(STORE_DISC.q?'q':'');
}
function storeDiscoverPaint(status){
  const st=$('#disc-st');if(st&&status!==undefined)st.textContent=status;
  const el=$('#disc-results');if(!el)return;
  const sig=discSig();
  if(sig===STORE_DISC._sig)return;  // same cards — leave the DOM alone (no flicker)
  STORE_DISC._sig=sig;
  el.innerHTML=storeDiscoverCards();
}
async function storeDiscover(q){
  STORE_DISC.q=q;
  const seq=++STORE_DISC.seq;               // newer keystrokes win…
  if(STORE_DISC.ctl)STORE_DISC.ctl.abort(); // …and stale requests are cancelled
  clearTimeout(STORE_DISC.poll);
  if(!q){STORE_DISC.results=[];storeDiscoverPaint('');return}
  const ctl=new AbortController();STORE_DISC.ctl=ctl;
  // only announce "searching" when the grid is empty — sync-poll re-queries shouldn't
  // blink the status while results are already on screen
  const st=$('#disc-st');if(st&&!STORE_DISC.results.length)st.textContent='searching…';
  try{
    // searches hit the locally-synced index — instant; while the background sync is
    // still pulling the catalog down, results keep growing and we re-query on a timer
    const r=await fetch('/api/store/mcp/search?q='+encodeURIComponent(q)+'&limit=30',{signal:ctl.signal});
    const d=await r.json();
    if(!r.ok)throw new Error(d.error||'search failed');
    if(seq!==STORE_DISC.seq)return;
    STORE_DISC.results=d.candidates||[];
    const ix=d.index||{};
    let status=STORE_DISC.results.length+' result'+(STORE_DISC.results.length===1?'':'s');
    if(ix.syncing)status+=' · indexing the registry — '+(ix.count||0)+' servers so far…';
    if(seq===STORE_DISC.seq&&ix.syncing)
      STORE_DISC.poll=setTimeout(()=>{if(seq===STORE_DISC.seq)storeDiscover(q)},4000);
    storeDiscoverPaint(status);
    // the registry isn't always enough — when results are sparse, the system widens
    // the net itself: npm + GitHub, fetched once per query (sync-poll re-queries
    // reuse the cached extras instead of re-sweeping and re-flickering)
    if(STORE_DISC.results.length<6){
      let extras=(STORE_DISC._deep&&STORE_DISC._deep.q===q)?STORE_DISC._deep.extras:null;
      if(!extras){
        storeDiscoverPaint(status+' · widening the search (npm & GitHub)…');
        const rd=await fetch('/api/store/mcp/discover_more?q='+encodeURIComponent(q),{signal:ctl.signal});
        const dd=await rd.json();
        if(seq!==STORE_DISC.seq)return;
        extras=rd.ok?(dd.candidates||[]):[];
        STORE_DISC._deep={q,extras};
      }
      const seen=new Set(STORE_DISC.results.map(c=>c.registry_name));
      STORE_DISC.results.push(...extras.filter(c=>!seen.has(c.registry_name)));
      let s2=STORE_DISC.results.length+' result'+(STORE_DISC.results.length===1?'':'s');
      if(ix.syncing)s2+=' · registry still indexing…';
      storeDiscoverPaint(s2);
    }
  }catch(e){
    if(e.name==='AbortError')return;
    if(seq===STORE_DISC.seq)storeDiscoverPaint('search failed — '+(e.message||e));
  }
}
function storeAgentSetup(i){
  const c=STORE_DISC.results[i];if(!c)return;
  // no published package to run — hand the repo to the agent: it reads the README,
  // derives the config, asks for keys, and connects it (approval-gated end to end)
  openApp('chat');
  setTimeout(()=>{
    if(!input)return;
    input.value='Set up the MCP server from '+c.homepage+' — fetch the README, work out how to '
      +'run it (npx / uvx / docker) and which API keys or config it needs, ask me for anything '
      +'required, then connect it with add_mcp_server and confirm its tools appear. '
      +'I was searching the store for: "'+STORE_DISC.q+'".';
    input.dispatchEvent(new Event('input'));send();
  },350);
  toast('handed to '+agentName()+' — it will read the repo and set the server up with you');
}
async function storeDiscoverInstall(i){
  const c=STORE_DISC.results[i];if(!c)return;
  const short=c.registry_name.split('/').pop();
  // discovery never installs silently — this is the user's yes/no gate
  if(!await osConfirm(`Discovered "${short}" — would you like to build around it and add it to your MCP Registry?`,c.description||'',{confirmText:'Install'}))return;
  const env={};
  const wants=[...c.env.map(e=>({n:e.name,req:e.required,d:e.description})),
               ...(c.remote_headers||[]).flatMap(h=>((h.value||'').match(/\{([\w.-]+)\}/g)||[]).map(v=>({n:v.slice(1,-1),req:h.required,d:h.description})))];
  for(const w of wants){
    const v=await osPrompt(w.n,{message:(w.d?w.d+' — ':'')+(w.req?'required — leave empty to fill later in the MCP app':'optional')});
    if(v===null)return;
    if(v.trim())env[w.n]=v.trim();
  }
  toast('⏳ installing '+short+'…');
  const r=await fetch('/api/store/mcp/install',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({registry_name:c.registry_name,env})});
  const d=await r.json();
  if(!r.ok)return toast(d.error||'install failed');
  c.installed=true;
  storeDiscoverPaint();  // signature changed (installed flag) — one clean repaint
  toast(`✓ ${d.name} added to the MCP Registry — manual in Docs`+(d.missing_env&&d.missing_env.length?` · disabled until you set: ${d.missing_env.join(', ')}`:''));
  setTimeout(async()=>{
    if(await osConfirm(`Build a desktop app around "${d.name}"?`,`${agentName()} will design an AI-native app that uses its tools (permissions are declared for your consent).`,{confirmText:'Build'})){
      openApp('studio');
      const p=`Build a COMPACT single-screen app (aim for under ~150 lines total — a focused MVP, `+
        `not a suite; big apps take minutes on local models) around the newly installed MCP server "${d.name}". `+
        `Its tools are available as appTool('mcp_${d.name}_<tool>', args) — check GET /api/tools for the exact names `+
        `and build around the 1-2 most useful tools only. Purpose: ${c.description||short}. `+
        `Add ONE small AI touch via appLLM on the returned data. Compose the UI purely from the pre-injected design-system classes (.card/.row/.cols/.kpi/.empty) — no custom CSS. `+
        `Declare permissions: [{"action":"mcp.use","resource":"mcp:${d.name}/*","reason":"uses the ${d.name} integration","required":true}].`;
      setTimeout(()=>{if($('#st-prompt')){$('#st-prompt').value=p;studioBuild()}},300);
    }
  },400);
}
async function storeInstall(id){
  const r=await fetch('/api/store/install',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});
  const d=await r.json();
  if(d.ok)toast('installed '+d.name);
  refreshApp('store');
}
async function storeInstallSkill(){
  const src=$('#store-sk').value.trim();if(!src)return toast('enter a git or raw URL');
  toast('⏳ installing…');
  const r=await fetch('/api/skills/install',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source:src})});
  const d=await r.json();toast(d.ok?`installed ${d.count} skill(s)`:d.error);refreshApp('store');
}
function storeBuild(){
  const p=$('#store-build').value.trim();if(!p)return;
  openApp('studio');
  setTimeout(()=>{if($('#st-prompt')){$('#st-prompt').value=p;studioBuild()}},200);
}
async function storeImportURL(){
  const url=$('#store-pkg-url').value.trim();if(!url)return toast('enter a package URL');
  await storeImportStage({url});
}
async function storeImportFile(){
  const f=$('#store-pkg-file').files[0];if(!f)return toast('choose a package file');
  let pkg; try{pkg=JSON.parse(await f.text())}catch(e){return toast('not a valid package file')}
  await storeImportStage({package:pkg});
}
async function storeImportStage(body){
  const r=await fetch('/api/apps/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json();
  if(!r.ok)return toast(d.error||'import failed');
  const missing=[
    ...(d.missing.mcp_servers||[]).map(m=>({label:'MCP channel "'+m.name+'" — added disabled; you fill its API key in the MCP app',
      run:async()=>{IMPORT_PREREQS.mcp.push(m.name)}})),
    ...(d.missing.skills||[]).map(s=>({label:'Skill "'+s.name+'" from '+(s.source||'?'),
      run:async()=>{IMPORT_PREREQS.skills.push(s.name)}})),
  ];
  IMPORT_PREREQS={mcp:[],skills:[]};
  if(d.name_conflict&&!await osConfirm('An app named "'+d.manifest.name+'" already exists','Importing will overwrite it. Continue?',{danger:true,confirmText:'Overwrite'}))return;
  showConsent(d.manifest,missing,async granted=>{
    const rr=await fetch('/api/apps/import/'+d.install_id+'/confirm',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({granted,install_mcp:IMPORT_PREREQS.mcp,install_skills:IMPORT_PREREQS.skills})});
    const dd=await rr.json();
    toast(rr.ok?('installed '+d.manifest.name):(dd.error||'install failed'));
    refreshApp('store');refreshApp('permissions');
  });
}
let IMPORT_PREREQS={mcp:[],skills:[]};

