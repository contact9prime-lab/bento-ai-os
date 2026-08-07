/* ================= app studio (agentic builder) =================

   Three things this panel owes the person watching it, learned from a build
   that ran for twelve minutes looking exactly like a hang:

   1. SHOW THE WORK. Every tool call, with the file/command it is on and a
      running clock, plus a heartbeat between calls. An executor can sit inside
      one Bash for minutes; silence is indistinguishable from a crash.
   2. THE APP'S IDENTITY IS THE USER'S. Left to itself the builder names an app
      after the sentence that asked for it ("build an application that…") and
      makes a second one next time the sentence differs. Name and icon are
      fields here, not model output.
   3. ASK BEFORE IT RUNS. A built app declares the capabilities it needs; the
      consent screen comes up as part of finishing the build, not as a link the
      user may or may not notice.

   GUI / SUI: the same panel, drawn in a window or in the session shell; the
   picker and consent overlays are page-level, so both get them. TUI: there is
   no App Studio over SSH and this does not add one — building an app is
   watching a preview change, which a terminal cannot do. What a headless
   machine CAN do is already reachable without this window: `/api/build/status`
   reports a running build, and an app's permissions are granted through the
   same manifest endpoints the consent screen calls.
*/
let STUDIO={apps:[],sel:'',building:false,log:null,preview:null,logs:{},surface:'desktop',
  model:localStorage.getItem('studioModel')||'auto',
  tab:'versions',          // bottom-left panel: versions | permissions
  newName:'',newIcon:'',   // identity chosen for the NEXT new app
  tools:{},_toolN:0};
async function renderStudio(body,w){
  // preserve the builder session log across re-renders and app switches
  if(STUDIO.log&&STUDIO.log.isConnected&&STUDIO._logKey)STUDIO.logs[STUDIO._logKey]=STUDIO.log.innerHTML;
  const r=await fetch('/api/apps?html=1');const d=await r.json();STUDIO.apps=d.apps;
  if(STUDIO.sel&&!d.apps.find(a=>a.id===STUDIO.sel))STUDIO.sel='';
  STUDIO._logKey=STUDIO.sel||'new';
  const cur=d.apps.find(a=>a.id===STUDIO.sel)||null;
  const sideItems=d.apps.map(a=>`
    <button class="stapp${a.id===STUDIO.sel?' on':''}" data-f="${esc(a.name+' '+(a.description||''))}" onclick="studioSelect('${a.id}')">
      ${iconTile(a.icon,a.name,a.id,26)}
      <span class="nm"><b>${esc(a.name)}</b><span>${esc(a.description||'')}</span></span>
      <span class="stren" title="rename this app" onclick="event.stopPropagation();renameUserApp('${a.id}','studio')">✏️</span>
    </button>`).join('');
  const pb=panelShell(body,{
    title:'App Studio',
    sub:`${d.apps.length} app${d.apps.length===1?'':'s'}`,
    flush:true,
    search:{id:'st-q',placeholder:'Search your apps…'},
    actions:`<button class="pghost" onclick="studioSelect('')">＋ New app</button>`,
  });
  const idName=cur?cur.name:STUDIO.newName, idIcon=cur?(cur.icon||''):STUDIO.newIcon;
  pb.innerHTML=`
    <div style="display:flex;height:100%;min-height:0">
      <div class="stside">
        <div class="stlist" id="st-list">
          <button class="stapp${STUDIO.sel?'':' on'}" data-f="new app" onclick="studioSelect('')">
            <span class="mono" style="background:var(--bg4);color:var(--acc)">＋</span>
            <span class="nm"><b>New app</b><span>start from a description</span></span>
          </button>
          ${sideItems}
        </div>
      </div>
      <div style="flex:1;display:flex;flex-direction:column;min-width:0">
        <div class="stident">
          <button class="stic" id="st-icon" onclick="studioPickIcon()" title="Choose this app's icon">${iconTile(idIcon,idName||'?',STUDIO.sel||'new',28)}</button>
          <input id="st-name" placeholder="${STUDIO.sel?'App name':'App name (optional — the builder picks one)'}" value="${esc(idName||'')}" maxlength="60">
          <span class="mut" id="st-idnote">${STUDIO.sel?'name &amp; icon apply to this app':'used when this app is built'}</span>
          ${STUDIO.sel?'<button class="endbtn" id="st-idsave" onclick="studioSaveIdentity()">Save</button>':''}
        </div>
        <div class="stcompose">
          <input id="st-prompt" placeholder="${STUDIO.sel?'Describe a change to make to this app…':'Describe the app to build — what it shows, what it tracks, where the data comes from…'}">
          <select id="st-model" class="stmodel" title="Model used to build — Auto picks the most build-capable one available"><option value="auto">Auto</option></select>
          <button class="pact${STUDIO.building?' stop':''}" style="flex:0 0 92px" id="st-build" onclick="studioBuild()">${STUDIO.building?'Cancel':STUDIO.sel?'Update':'Build'}</button>
        </div>
        <div style="flex:1;min-height:0;display:flex">
          <div style="flex:0 0 40%;display:flex;flex-direction:column;border-right:1px solid var(--line);min-width:0">
            <div class="tmsec" style="margin:8px 12px 4px">Builder</div>
            <div id="st-log" class="stlog" style="flex:1;overflow-y:auto;padding:2px 12px 10px;font-size:12.5px;user-select:text"></div>
            <div class="sttabs">
              <button data-t="versions" class="${STUDIO.tab==='versions'?'on':''}" onclick="studioTab('versions')">Versions</button>
              <button data-t="perms" class="${STUDIO.tab==='perms'?'on':''}" onclick="studioTab('perms')">Permissions <span id="st-permdot"></span></button>
            </div>
            <div id="st-panel" style="flex:0 0 auto;max-height:200px;overflow-y:auto;border-top:1px solid var(--line);padding:8px 12px 10px"></div>
          </div>
          <div style="flex:1;display:flex;flex-direction:column;min-width:0">
            <div style="display:flex;align-items:center;gap:8px;padding:7px 10px;border-bottom:1px solid var(--line)">
              <span class="tmsec" style="margin:0">Preview</span>
              <span id="st-live"></span>
              <span id="st-actions" style="margin-left:auto;display:flex;gap:6px"></span>
            </div>
            <div id="st-prev" style="flex:1;background:#0e1116"></div>
          </div>
        </div>
      </div>
    </div>`;
  STUDIO.log=$('#st-log');STUDIO.preview=$('#st-prev');
  const cachedLog=STUDIO.logs[STUDIO._logKey];
  if(cachedLog){STUDIO.log.innerHTML=cachedLog;STUDIO.log.scrollTop=STUDIO.log.scrollHeight}
  else if(STUDIO.sel)studioLoadHistory(STUDIO.sel);   // restore this app's build session from the server
  $('#st-prompt').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();studioBuild()}});
  // a name typed for a NEW app has nowhere to be saved yet — keep it in hand
  $('#st-name').addEventListener('input',e=>{if(!STUDIO.sel)STUDIO.newName=e.target.value});
  $('#st-name').addEventListener('keydown',e=>{if(e.key==='Enter'&&STUDIO.sel)studioSaveIdentity()});
  studioLoadModels();
  studioShowPreview();studioActions();studioPanel();
  if(!STUDIO.sel&&STUDIO.log&&!STUDIO.log.children.length)
    STUDIO.log.innerHTML=`<p class="mut">Describe an app and ${esc(agentName())} builds it live — e.g.
      <i>"a pomodoro timer"</i>, <i>"track the prices of these three products daily"</i>,
      <i>"a dashboard of my scheduled tasks"</i>, or <i>"a button that runs neofetch and shows the output"</i>.
      Apps can call the OS and MCP tools, use the AI model inside their features (appLLM) for the
      judgement calls code cannot make, store their own data, run checks on a schedule, and send you
      alerts on Telegram when something changes.
      Pick an app on the left to refine it — every build is versioned and can be rolled back below.</p>`;
}
function studioSelect(id){
  STUDIO.sel=id||'';
  const w=WM.wins.get('studio');if(w)renderStudio(w.el.querySelector('.wbody'),w);
}
function studioTab(t){
  STUDIO.tab=t;
  const tabs=document.querySelector('.sttabs');
  if(tabs)tabs.querySelectorAll('button').forEach(b=>b.classList.toggle('on',b.dataset.t===t));
  studioPanel();
}
/* ---- identity: the app's name and icon are the user's choice --------------- */
async function studioSaveIdentity(){
  if(!STUDIO.sel)return;
  const name=($('#st-name')?.value||'').trim();
  if(!name)return toast('an app needs a name');
  const r=await fetch('/api/apps/'+STUDIO.sel,{method:'PUT',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name})});
  const d=await r.json().catch(()=>({}));
  if(!r.ok)return toast(d.error||'could not save');
  toast('renamed to “'+name+'”');
  loadUserApps();refreshApp('studio');
}
/* The picker offers the OS's OWN glyph tiles first. An app that picks "tasks"
   gets the same duotone tile Tasks has, so a built app sits on the desktop
   looking like it belongs there — which an emoji sticker never does. */
function studioPickIcon(){
  const curIcon=STUDIO.sel?((STUDIO.apps.find(a=>a.id===STUDIO.sel)||{}).icon||''):STUDIO.newIcon;
  const nm=($('#st-name')?.value||'App').trim()||'App';
  const keys=Object.keys(ICONS);
  const ov=document.createElement('div');
  ov.className='stiov';
  ov.innerHTML=`<div class="stibox">
    <b style="font-size:14px">App icon</b>
    <p class="mut" style="margin:4px 0 10px;font-size:12px">Pick a tile, or leave it as the monogram — the OS draws “${esc(nm.charAt(0).toUpperCase())}” on a colour derived from the app itself.</p>
    <div class="stigrid">
      <button data-v="" title="Monogram" class="${curIcon?'':'on'}">${iconTile('',nm,STUDIO.sel||nm,34)}</button>
      ${keys.map(k=>`<button data-v="glyph:${k}" title="${esc(k)}" class="${curIcon==='glyph:'+k?'on':''}">${glyphTile(k,34)}</button>`).join('')}
    </div>
    <label style="display:block;margin-top:12px;font-size:12px" class="mut">…or an emoji</label>
    <div class="row" style="display:flex;gap:8px;margin-top:5px">
      <input id="sti-em" maxlength="4" placeholder="🎯" value="${esc(curIcon&&!curIcon.startsWith('glyph:')?curIcon:'')}" style="flex:0 0 80px;text-align:center">
      <span class="sp" style="flex:1"></span>
      <button class="endbtn sti-x">Cancel</button>
      <button class="pact sti-ok" style="flex:0 0 auto">Use this</button>
    </div>
  </div>`;
  document.body.appendChild(ov);
  let pick=curIcon;
  ov.querySelectorAll('.stigrid button').forEach(b=>b.onclick=()=>{
    pick=b.dataset.v;
    ov.querySelectorAll('.stigrid button').forEach(x=>x.classList.toggle('on',x===b));
    const em=ov.querySelector('#sti-em');if(em)em.value='';
  });
  ov.querySelector('#sti-em').addEventListener('input',e=>{
    const v=e.target.value.trim();
    if(v){pick=v;ov.querySelectorAll('.stigrid button').forEach(x=>x.classList.remove('on'))}
  });
  const close=()=>ov.remove();
  ov.querySelector('.sti-x').onclick=close;
  ov.onclick=e=>{if(e.target===ov)close()};
  ov.querySelector('.sti-ok').onclick=async()=>{
    close();
    if(!STUDIO.sel){                       // no app yet — remember it for the build
      STUDIO.newIcon=pick;
      const btn=$('#st-icon');if(btn)btn.innerHTML=iconTile(pick,nm,'new',28);
      return;
    }
    const r=await fetch('/api/apps/'+STUDIO.sel,{method:'PUT',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({icon:pick})});
    if(!r.ok)return toast('could not set the icon');
    toast('icon updated');loadUserApps();refreshApp('studio');
  };
}
async function studioLoadModels(){
  const sel=$('#st-model');if(!sel)return;
  const cur=STUDIO.model||'auto';
  try{
    const d=await (await fetch('/api/models')).json();
    const list=(d.models||[]);
    /* Executors belong here too. A one-shot model has a single turn to emit an
       entire app; an executor writes it as a file and keeps working until it is
       finished, which is the difference between a sketch and something you could
       demo. Listed first for anything ambitious. */
    // only executors build here: Hermes answers, but has no file workspace to build in
    const engines=(d.engines||[]).filter(e=>e.available&&e.kind==='executor');
    sel.innerHTML=`<option value="auto">My default model${d.default?' · '+esc(d.default):''}</option>`+
      engines.map(e=>`<option value="${esc(e.id)}">${esc(e.name||e.id)} · builds as a file, keeps going until done</option>`).join('')+
      list.map(m=>`<option value="${esc(m.id)}">${esc(m.name+' · '+m.provider+(m.provider==='ollama'?' (local)':''))}</option>`).join('');
    // A model you picked is YOUR choice: if the list doesn't have it this second
    // (provider slow, key toggled, Ollama restarting) keep it selected and say so
    // instead of silently dropping you back to Auto — that reset is exactly how a
    // chosen cloud model turned back into a local one.
    if(cur!=='auto'&&!list.some(m=>m.id===cur)&&!engines.some(e=>e.id===cur))
      sel.insertAdjacentHTML('beforeend',`<option value="${esc(cur)}">${esc(cur)} · unavailable right now</option>`);
    sel.value=cur;
  }catch(e){
    if(cur!=='auto'&&![...sel.options].some(o=>o.value===cur))
      sel.insertAdjacentHTML('beforeend',`<option value="${esc(cur)}">${esc(cur)}</option>`);
    sel.value=cur;                      // a failed fetch must never rewrite the choice
  }
  sel.onchange=()=>{STUDIO.model=sel.value;localStorage.setItem('studioModel',sel.value);
    toast(sel.value==='auto'?'builds pick the best available model':'builds will use '+sel.value)};
}
async function studioLoadHistory(sel){
  // each app has ONE persistent build conversation ("build: <name>") — show it so
  // picking the app back up continues the same session instead of a blank slate
  try{
    const app=STUDIO.apps.find(a=>a.id===sel);if(!app)return;
    const convs=(await (await fetch('/api/conversations')).json()).conversations||[];
    const c=convs.find(x=>x.title==='build: '+app.name);if(!c)return;
    const msgs=(await (await fetch('/api/conversations/'+c.id)).json()).messages||[];
    if(STUDIO.sel!==sel||!STUDIO.log||!STUDIO.log.isConnected||STUDIO.log.children.length)return;
    const lines=msgs.map(m=>{
      let t=(m.content||'').replace(/```[\s\S]*?(```|$)/g,'(code)').trim();
      if(!t)return'';
      if(t.length>280)t=t.slice(0,280)+'…';
      return `<div style="margin:4px 0">${m.role==='user'
        ?`<b style="color:var(--acc2)">You:</b> ${esc(t)}`
        :`<b>▲ ${esc(agentName())}:</b> ${esc(t)}`}</div>`;
    }).filter(Boolean).join('');
    if(!lines)return;
    STUDIO.log.innerHTML=`<div class="mut" style="margin:4px 0;font-size:11px">— session so far —</div>`+lines;
    STUDIO.logs[sel]=STUDIO.log.innerHTML;
    STUDIO.log.scrollTop=STUDIO.log.scrollHeight;
  }catch(e){}
}
/* built apps postMessage their runtime JS errors here — surface them with a one-click fix */
window.addEventListener('message',ev=>{
  const d=ev.data;
  if(!d||d.agentos!=='app_error')return;
  if(!STUDIO.sel||d.app_id!==STUDIO.sel||!STUDIO.log||!STUDIO.log.isConnected||STUDIO.building)return;
  if(STUDIO._lastErr===d.message)return;   // don't spam repeats (e.g. errors in a poll loop)
  STUDIO._lastErr=d.message;
  studioLog(`<span style="color:var(--err)">app runtime error: ${esc(d.message)}${d.source&&d.source!==':0'?' @ '+esc(d.source):''}</span>
    <button style="font-size:11px;padding:3px 10px;margin-left:6px" onclick="studioAutoFix()">Fix automatically</button>`);
  // a just-deployed app that errors on first load gets ONE automatic repair build
  if(STUDIO._justBuilt&&Date.now()-STUDIO._justBuilt<8000&&!STUDIO._autofixed){
    STUDIO._autofixed=true;
    studioLog('<span class="mut">the fresh build crashed on load — repairing automatically…</span>');
    studioAutoFix();
  }
});
function studioAutoFix(){
  const p=$('#st-prompt');if(!p||!STUDIO._lastErr)return;
  p.value='Fix this runtime error, keep everything else identical: '+STUDIO._lastErr;
  STUDIO._lastErr=null;
  studioBuild();
}
function studioActions(){
  const box=$('#st-actions');if(!box)return;
  const pinned=WIDGETS.some(w=>w.app_id===STUDIO.sel&&(w.desk||1)===curDesk);
  const app=(USERAPPS||[]).find(a=>a.id===STUDIO.sel);
  const size=(app&&app.widget_size)||'m';
  box.innerHTML=STUDIO.sel
    ?`<button class="endbtn" onclick="openApp('ua_${STUDIO.sel}')">↗ Open window</button>
      <button class="endbtn" onclick="${pinned?`unpinWidget('${STUDIO.sel}')`:`pinWidget('${STUDIO.sel}')`};studioActions()">${pinned?'Unpin':'Pin to Desktop '+curDesk}</button>
      <span class="wgsize" title="How big this app is when pinned as a widget">
        <span class="mut">Widget</span>
        ${Object.entries(WIDGET_SIZES).map(([k,d])=>
          `<button class="${k===size?'on':''}" onclick="setWidgetSize('${STUDIO.sel}','${k}')" title="${d.label} — ${d.w}×${d.h}">${k.toUpperCase()}</button>`).join('')}
      </span>
      <button class="endbtn" onclick="studioPreviewSurface()">${STUDIO.surface==='widget'?'Preview desktop':'Preview widget'}</button>
      <button class="endbtn" onclick="window.open('/api/apps/${STUDIO.sel}/export')">Export</button>
      <button class="endbtn" onclick="studioDel('${STUDIO.sel}')">Delete</button>`:'';
}
/* The preview switches between the app's two surfaces, at the exact size the
   widget will be — so "does it still read at S?" is answered before pinning. */
function studioPreviewSurface(){
  STUDIO.surface=STUDIO.surface==='widget'?'desktop':'widget';
  studioShowPreview();studioActions();
}
function studioShowPreview(){
  if(!STUDIO.preview)return;
  if(!STUDIO.sel){
    STUDIO.preview.innerHTML='<div class="mut" style="display:flex;height:100%;align-items:center;justify-content:center;padding:20px;text-align:center">the built app will preview here</div>';
    return;
  }
  const app=(USERAPPS||[]).find(a=>a.id===STUDIO.sel), size=(app&&app.widget_size)||'m';
  if(STUDIO.surface==='widget'){
    const d=WIDGET_SIZES[size]||WIDGET_SIZES.m;
    STUDIO.preview.innerHTML=`<div class="wgpreview"><div class="widget" style="position:relative;width:${d.w}px;height:${d.h}px">
        <div class="wgh"><span class="wgt">${esc((app&&app.name)||'')}</span><span class="mut" style="font-size:10.5px">${d.label} · ${d.w}×${d.h}</span></div>
        <iframe src="/api/apps/${STUDIO.sel}/page?surface=widget&size=${size}&t=${Date.now()}" sandbox="allow-scripts allow-same-origin allow-forms"></iframe>
      </div></div>`;
    return;
  }
  STUDIO.preview.innerHTML=`<iframe src="/api/apps/${STUDIO.sel}/page?t=${Date.now()}" style="width:100%;height:100%;border:none;background:#0e1116" sandbox="allow-scripts allow-same-origin allow-forms"></iframe>`;
}
/* ---- bottom panel: versions | permissions --------------------------------- */
function studioPanel(){
  if(STUDIO.tab==='perms')studioPerms();else studioVersions();
}
async function studioVersions(){
  const box=$('#st-panel'),live=$('#st-live');
  if(!box)return;
  if(!STUDIO.sel){box.innerHTML='<p class="mut" style="font-size:12px">Versions appear once an app is built — every build and every edit records one, and any of them can be restored.</p>';if(live)live.innerHTML='';return}
  const d=await fetch('/api/apps/'+STUDIO.sel+'/versions').then(r=>r.json()).catch(()=>({versions:[]}));
  if(STUDIO.tab!=='versions'||!box.isConnected)return;
  const vs=d.versions||[];
  const cur=vs[0];
  if(live)live.innerHTML=cur
    ?`<span style="font-size:11px;color:var(--ok);border:1px solid var(--ok);border-radius:999px;padding:1px 9px">deployed · v${cur.version}</span>`:'';
  const ago=t=>{const s=Math.max(1,Math.round(Date.now()/1000-t));return s<60?s+'s':s<3600?Math.round(s/60)+'m':s<86400?Math.round(s/3600)+'h':Math.round(s/86400)+'d'};
  box.innerHTML=(vs.map(v=>`<div style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:12px;border-bottom:1px solid var(--line)">
      <b style="flex:0 0 34px;color:${v===cur?'var(--ok)':'var(--dim)'}">v${v.version}</b>
      <span class="mut" style="flex:0 0 40px">${ago(v.created_at)}</span>
      <span style="flex:1;color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(v.note||'')}">${esc(v.note||'')}</span>
      ${v===cur?'<span style="font-size:10.5px;color:var(--ok)">live</span>'
        :`<button style="flex:0 0 auto;font-size:11px;padding:2px 10px" onclick="studioRestore(${v.version})">Restore</button>`}
    </div>`).join('')||'<p class="mut" style="font-size:12px">No versions yet — every build or edit creates one.</p>');
}
/* Permissions, in the same window the app was built in. An app that needs the
   network, a tool or the model has to say so and be granted it — and the place
   to see that is next to the thing that asked. */
async function studioPerms(){
  const box=$('#st-panel');if(!box)return;
  if(!STUDIO.sel){
    box.innerHTML=`<p class="mut" style="font-size:12px">Built apps run sandboxed with nothing granted by default.
      When a build finishes, AgentOS reads what the app actually calls — OS tools, the network, the AI model,
      its own data — and asks you to approve exactly that list. You can change it here or in Permissions at any time.</p>`;
    return;
  }
  let d;try{d=await (await fetch('/api/apps/'+STUDIO.sel+'/manifest')).json()}catch(e){box.innerHTML='<p class="mut">could not load permissions</p>';return}
  if(STUDIO.tab!=='perms'||!box.isConnected)return;
  const perms=(d.manifest&&d.manifest.permissions)||[],st=d.status||'none';
  const granted=new Set((d.grants||[]).filter(g=>g.effect!=='deny').map(g=>g.action+' '+g.resource));
  const dot=$('#st-permdot');
  if(dot)dot.innerHTML=st==='proposed'?'<span class="stpd"></span>':'';
  const label={none:'not scanned yet',proposed:'awaiting your approval',approved:'granted'}[st]||st;
  box.innerHTML=`<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
      <span style="font-size:11.5px;color:${st==='approved'?'var(--ok)':st==='proposed'?'var(--warn,#e8b04b)':'var(--dim)'}">${esc(label)}</span>
      <span class="sp" style="flex:1"></span>
      ${st==='proposed'?`<button class="pact" style="flex:0 0 auto;font-size:11px;padding:3px 10px" onclick="studioReviewPerms()">Review &amp; grant</button>`:''}
      <button class="endbtn" style="font-size:11px;padding:3px 10px" onclick="studioRescanPerms()">${st==='none'?'Scan':'Rescan'}</button>
    </div>`+
    (perms.length?perms.map(p=>{
      const res=(p.resource||'*').replace('app:self/','app:'+STUDIO.sel+'/');
      const on=granted.has((p.action||'*')+' '+res);
      return `<div style="display:flex;gap:8px;align-items:flex-start;padding:4px 0;font-size:12px;border-bottom:1px solid var(--line)">
        <span style="flex:0 0 14px;color:${on?'var(--ok)':'var(--dim2)'}">${on?'✓':'○'}</span>
        <div style="flex:1;min-width:0">
          <div class="mono" style="font-size:11.5px">${esc(p.action||'*')} · ${esc(p.resource||'*')}</div>
          <div class="mut" style="font-size:11px">${esc(p.reason||'')}${p.required?' · required':''}</div>
        </div></div>`}).join('')
      :'<p class="mut" style="font-size:12px">This app asks for nothing — it only uses its own private data store.</p>');
}
async function studioReviewPerms(){
  const aid=STUDIO.sel;if(!aid)return;
  let r;try{r=await (await fetch('/api/apps/'+aid+'/manifest')).json()}catch(e){return toast('failed to load manifest')}
  showConsent(r.manifest,[],async granted=>{
    await fetch('/api/apps/'+aid+'/manifest/approve',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({granted})});
    toast('permissions granted');
    if(STUDIO.sel===aid){studioPanel();studioShowPreview()}   // reload the app under its new grants
    if(typeof refreshApp==='function')refreshApp('permissions');
  });
}
async function studioRescanPerms(){
  if(!STUDIO.sel)return;
  const r=await fetch('/api/apps/'+STUDIO.sel+'/manifest/propose',{method:'POST'});
  if(!r.ok)return toast('scan failed');
  toast('re-read from the app source');studioPerms();
}
async function studioRestore(v){
  if(!await osConfirm('Restore v'+v+'?','The current version stays in history.',{confirmText:'Restore'}))return;
  await fetch('/api/apps/'+STUDIO.sel+'/versions/'+v+'/restore',{method:'POST'});
  toast('restored v'+v+' — deployed live');
  studioShowPreview();studioPanel();loadUserApps();
}
function studioLog(html,cls){
  if(!STUDIO.log)return;
  const d=document.createElement('div');d.className=cls||'';d.style.margin='4px 0';d.innerHTML=html;
  STUDIO.log.appendChild(d);
  if(STUDIO._status&&STUDIO._status.isConnected&&STUDIO._status!==d)STUDIO.log.appendChild(STUDIO._status); // status line stays last
  STUDIO.log.scrollTop=STUDIO.log.scrollHeight;
  return d;
}
function studioDur(ms){
  const s=Math.round(ms/1000);
  return s<60?s+'s':Math.floor(s/60)+'m '+String(s%60).padStart(2,'0')+'s';
}
/* Text arrives as whole assistant messages. Concatenating them into one <div>
   is what turned a build log into an unreadable slab with sentences fused at the
   full stop ("Syntax passes.Now let me…") — each message is its own block, and
   markdown is rendered rather than escaped. */
function studioSay(text){
  if(!STUDIO.log)return;
  if(!STUDIO._cur||!STUDIO._cur.isConnected){
    STUDIO._cur=studioLog('','bsay');
    STUDIO._cur._t='';
    STUDIO._first=STUDIO._first||STUDIO._cur;
  }
  STUDIO._cur._t=(STUDIO._cur._t||'')+text;
  const body=STUDIO._cur._t.trim();
  STUDIO._cur.innerHTML=(STUDIO._cur===STUDIO._first?'<b>▲ '+esc(agentName())+'</b>':'')+md(body);
  if(STUDIO._status&&STUDIO._status.isConnected)STUDIO.log.appendChild(STUDIO._status);
  STUDIO.log.scrollTop=STUDIO.log.scrollHeight;
}
function studioEndSay(){STUDIO._cur=null}   // the next text starts a fresh block
function studioTickStart(){
  studioTickStop();
  STUDIO._t0=Date.now();
  STUDIO._status=studioLog('<span class="mut">working…</span>');
  STUDIO._tick=setInterval(()=>{
    if(!STUDIO._status||!STUDIO._status.isConnected){if(STUDIO._tick){clearInterval(STUDIO._tick);STUDIO._tick=null}return}
    // every open tool line carries its own clock, so a four-minute Bash is
    // visibly a four-minute Bash rather than an unexplained gap
    for(const k in STUDIO.tools){
      const el=STUDIO.tools[k];
      if(!el||!el.isConnected){delete STUDIO.tools[k];continue}
      const t=el.querySelector('.bt-t');if(t)t.textContent=studioDur(Date.now()-el._t0);
    }
    const s=Math.round((Date.now()-STUDIO._t0)/1000);
    STUDIO._status.innerHTML='<span class="mut">working… '+(s>=60?Math.floor(s/60)+'m '+(s%60)+'s':s+'s')
      +(STUDIO._smsg?' — '+esc(STUDIO._smsg):(s>45?' — the model is writing the app; large apps take a few minutes on local models. Cancel any time.':''))+'</span>';
  },1000);
}
function studioTickStop(){
  if(STUDIO._tick){clearInterval(STUDIO._tick);STUDIO._tick=null}
  if(STUDIO._status){STUDIO._status.remove();STUDIO._status=null}
}
function studioBuild(){
  if(STUDIO.building){                       // the button doubles as Cancel while a build runs
    if(ws&&ws.readyState===1)ws.send(JSON.stringify({type:'build_abort'}));
    return;
  }
  const p=$('#st-prompt');if(!p)return;
  const prompt=p.value.trim();if(!prompt)return;
  if(!ws||ws.readyState!==1)return toast('not connected');
  STUDIO.building=true;
  const b=$('#st-build');if(b){b.textContent='Cancel';b.classList.add('stop')}
  studioEndSay();STUDIO._first=null;STUDIO.tools={};
  studioLog(`<b style="color:var(--acc2)">You:</b> ${esc(prompt)}`);
  studioTickStart();
  jarvisOn();
  const bmodel=$('#st-model')?.value||STUDIO.model||'auto';
  const msg={type:'build',prompt,app_id:STUDIO.sel,model:bmodel};
  // identity travels with the build: an app the user named is not renamed by the model
  const nm=($('#st-name')?.value||'').trim();
  if(nm)msg.name=nm;
  if(!STUDIO.sel&&STUDIO.newIcon)msg.icon=STUDIO.newIcon;
  ws.send(JSON.stringify(msg));
  p.value='';
}
function studioBuildEnded(){
  STUDIO.building=false;STUDIO._smsg='';studioTickStop();jarvisOff();studioEndSay();
  for(const k in STUDIO.tools){                    // nothing is left spinning
    const el=STUDIO.tools[k];
    if(el&&el.isConnected)el.classList.add('done');
    delete STUDIO.tools[k];
  }
  const b=$('#st-build');if(b){b.disabled=false;b.classList.remove('stop');b.textContent=STUDIO.sel?'Update':'Build'}
}
function studioBuildEvent(ev){
  switch(ev.type){
    case 'build_start': break;
    // Thinking is shown, but as ONE self-replacing line rather than a growing
    // wall: a delegated build can reason for a minute before its first tool
    // call, and "working… 45s" with nothing else reads exactly like a hang.
    // (It also still drives the jarvis pulse — see 09-websocket.js.)
    case 'build_thinking':{
      if(!STUDIO.log||!ev.text)break;
      let el=STUDIO.log.querySelector('.bthink');
      if(!el){el=studioLog('','bthink')}
      el._t=((el._t||'')+ev.text).slice(-400);
      el.textContent='… '+el._t.replace(/\s+/g,' ').trim();
      if(STUDIO._status&&STUDIO._status.isConnected)STUDIO.log.appendChild(STUDIO._status);
      STUDIO.log.scrollTop=STUDIO.log.scrollHeight;break;}
    case 'build_engine':
      studioLog(`<span class="mut">▲ ${esc(ev.engine||'executor')}${ev.model?' · '+esc(ev.model):''}`
        +`${(ev.tools||[]).length?' · '+ev.tools.length+' tools':''}</span>`);break;
    case 'build_text':
      studioSay(ev.text||'');
      break;
    case 'build_tool':{
      studioEndSay();                       // the narration before this call is finished
      const known={create_app:'deploying the app',fetch_url:'checking the live data source',
        Write:'writing the app file',Edit:'editing the app file',Read:'reading it back',
        Bash:'running a command',Glob:'looking for files',Grep:'searching',
        WebFetch:'fetching a page',WebSearch:'searching the web'}[ev.name]||'';
      const el=studioLog(`<span class="btool"><span class="bt-n">▸ ${esc(ev.name||'tool')}</span>`
        +`${ev.detail?`<span class="bt-d">${esc(ev.detail)}</span>`:known?`<span class="bt-d">${esc(known)}</span>`:''}`
        +`<span class="bt-t">0s</span></span>`);
      if(el){el._t0=Date.now();STUDIO.tools[ev.call_id||('n'+(++STUDIO._toolN))]=el}
      break;}
    case 'build_tool_end':{ // failed tool calls must be VISIBLE — a silent retry loop looks like a hang
      const ok=ev.ok!==false;
      const el=STUDIO.tools[ev.call_id];
      if(el&&el.isConnected){
        delete STUDIO.tools[ev.call_id];
        el.classList.add('done');el.classList.toggle('bad',!ok);
        const n=el.querySelector('.bt-n');if(n)n.textContent=(ok?'✓ ':'✗ ')+(ev.name||n.textContent.replace(/^[▸✓✗]\s*/,''));
        const t=el.querySelector('.bt-t');if(t)t.textContent=studioDur(Date.now()-el._t0);
        if(!ok)studioLog(`<span style="color:var(--err)">${esc((ev.output||'').slice(0,220))}</span>`);
      }else if(!ok){
        studioLog(`<span style="color:var(--err)">✗ ${esc(ev.name||'tool')} — ${esc((ev.output||'').slice(0,220))}</span>`);
      }
      break;}
    case 'build_choice':{  // the build produced nothing — the USER picks what runs next
      const opts=(ev.options||[]).filter(Boolean);
      const id='bc'+Date.now().toString(36);
      studioLog(`<div class="bchoice" id="${id}"><b>${esc(ev.message||'no app was produced')}</b>
        <span>Nothing was installed. Run it again with:</span>
        <span class="row">
          <select class="bc-m">${opts.map(o=>`<option value="${esc(o)}">${esc(o)}</option>`).join('')||'<option value="">no other model configured</option>'}</select>
          <button class="pact bc-go">Retry</button>
          <button class="endbtn bc-x">Not now</button>
        </span></div>`);
      const box=document.getElementById(id);
      if(box){
        box.querySelector('.bc-go').onclick=()=>{
          const m=box.querySelector('.bc-m').value;
          if(!m)return toast('add a cloud key in Settings → AI providers first');
          const sel=$('#st-model');if(sel){sel.value=m;STUDIO.model=m;localStorage.setItem('studioModel',m)}
          box.remove();studioBuild();
        };
        box.querySelector('.bc-x').onclick=()=>box.remove();
      }
      break;}
    case 'build_status': // heartbeat: what it is on, and for how long
      STUDIO._smsg=ev.message||'';break;
    case 'build_error_note': // non-fatal error inside an attempt (the build continues/retries)
      studioEndSay();
      studioLog(`<span style="color:var(--err)">${esc(ev.message||'error')}</span>`);break;
    case 'build_error':
      studioBuildEnded();
      studioLog(`<span style="color:var(--err)">${esc(ev.message||'error')}</span>`);break;
    case 'build_done':
      studioBuildEnded();
      if(ev.app_id){
        const wasNew=(STUDIO._logKey||'new')==='new';
        STUDIO.sel=ev.app_id;STUDIO._lastErr=null;
        STUDIO._justBuilt=Date.now();STUDIO._autofixed=false;   // arm the load-crash auto-repair
        STUDIO.newName='';STUDIO.newIcon='';                    // consumed by this build
        studioLog(`<span style="color:var(--ok)">✓ ${esc(ev.name||'app')} ready — deployed live</span>`);
        if(ev.warnings&&ev.warnings.length)
          studioLog(`<span style="color:var(--warn,#e8b04b)">⚠ shipped with known issues: ${esc(ev.warnings.join('; ').slice(0,300))} — ask for a fix or rebuild</span>`);
        if(wasNew)delete STUDIO.logs['new'];   // this session now belongs to the built app
        STUDIO._logKey=ev.app_id;
        // re-render to refresh the picker, then preview + open action
        const w=WM.wins.get('studio');if(w){renderStudio(w.el.querySelector('.wbody'),w);}
        toast(''+(ev.name||'app')+' built');
        // An app asks for what it needs BEFORE it is used, not from a link in a
        // log the user has already scrolled past.
        if(ev.manifest_status==='proposed'){
          STUDIO.tab='perms';
          studioLog(`<span class="mut">it needs permissions to run — </span><button style="font-size:11px;padding:3px 10px" onclick="studioReviewPerms()">Review &amp; grant</button>`);
          setTimeout(()=>{if(STUDIO.sel===ev.app_id)studioReviewPerms()},600);
        }
      } else studioLog('<span class="mut">no app was produced — try rephrasing</span>');
      break;
  }
}
async function studioDel(id){
  if(!await osConfirm('Delete this app?','',{danger:true,confirmText:'Delete'}))return;
  await fetch('/api/apps/'+(id||STUDIO.sel),{method:'DELETE'});
  STUDIO.sel='';refreshApp('studio');
}
