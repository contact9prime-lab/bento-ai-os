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
  tab:'builder',           // bottom panel: builder | problems | console | versions | perms | sched
  newName:'',newIcon:'',   // identity chosen for the NEXT new app
  tools:{},_toolN:0,
  // the IDE: open files (one per app), the text being edited, and what the checker said
  tabs:[],docs:{},probs:{},cons:{},pane:'code',ed:null,draft:'',useSel:true};
/* App Studio is an IDE. The explorer lists the apps and the outline of the open one, the
   editor holds the app's one file, the preview runs it, and the panel underneath holds
   the builder (describe a change and your agent makes it), the problems the checker
   found, the app's console, its versions, its permissions and its schedules.

   A repaint keeps the text being edited: the docs live in STUDIO.docs, not in the DOM,
   so an `apps` broadcast (every save sends one) redraws the list without touching the
   editor. Only choosing another app draws the layout again. */
async function renderStudio(body,w){
  const soft=!STUDIO._hard&&body._ideSel===STUDIO.sel&&body.querySelector('.stide');
  STUDIO._hard=false;
  // preserve the builder session log across re-renders and app switches
  // A log that is only the stored history (.st-src) is re-read from the server instead,
  // so a follow-up in Chat shows here the next time the Studio is drawn.
  if(!soft&&STUDIO.log&&STUDIO.log.isConnected&&STUDIO._logKey){
    if(!STUDIO.building&&STUDIO.log.querySelector('.st-src'))delete STUDIO.logs[STUDIO._logKey];
    else STUDIO.logs[STUDIO._logKey]=STUDIO.log.innerHTML;
  }
  if(!soft&&STUDIO.ed&&STUDIO.ed._aid&&STUDIO.docs[STUDIO.ed._aid])STUDIO.docs[STUDIO.ed._aid].view=STUDIO.ed.view();
  const d=await apiJSON('/api/apps').catch(()=>({apps:STUDIO.apps}));STUDIO.apps=d.apps||[];
  if(STUDIO.sel&&!STUDIO.apps.find(a=>a.id===STUDIO.sel))STUDIO.sel='';
  STUDIO.tabs=STUDIO.tabs.filter(id=>STUDIO.apps.find(a=>a.id===id));
  if(STUDIO.sel&&!STUDIO.tabs.includes(STUDIO.sel))STUDIO.tabs.push(STUDIO.sel);
  if(soft){studioList();studioTabsPaint();studioCheckVersion(STUDIO.sel);studioTab(STUDIO.tab,true);studioActions();return}
  body._ideSel=STUDIO.sel;
  STUDIO._logKey=STUDIO.sel||'new';
  const cur=STUDIO.apps.find(a=>a.id===STUDIO.sel)||null;
  const pb=panelShell(body,{
    title:'App Studio',
    sub:`${STUDIO.apps.length} app${STUDIO.apps.length===1?'':'s'}`,
    flush:true,
    search:{id:'st-q',placeholder:'Search your apps…'},
    actions:`<button class="pghost" onclick="studioSelect('')">＋ New app</button>`,
  });
  const idName=cur?cur.name:STUDIO.newName, idIcon=cur?(cur.icon||''):STUDIO.newIcon;
  const lay=studioLayout(),on=t=>STUDIO.tab===t?'on':'';
  pb.innerHTML=`
    <div class="stide-wrap"><div class="stide" data-pane="${esc(STUDIO.pane)}" style="--ide-prev:${lay.prev}px;--ide-bot:${lay.bot}px;--ide-side:${lay.side}px">
      <div class="ide-seg" role="tablist">
        <button data-p="files" class="${STUDIO.pane==='files'?'on':''}" onclick="studioPane('files')">Apps</button>
        <button data-p="code" class="${STUDIO.pane==='code'?'on':''}" onclick="studioPane('code')">Code</button>
        <button data-p="preview" class="${STUDIO.pane==='preview'?'on':''}" onclick="studioPane('preview')">Preview</button>
        <button data-p="panel" class="${STUDIO.pane==='panel'?'on':''}" onclick="studioPane('panel')">Builder</button>
      </div>
      <div class="stside">
        <div class="ide-sec">Apps</div>
        <div class="stlist" id="st-list"></div>
        <div class="ide-sec">Outline <span class="mut" id="st-outn"></span></div>
        <div class="ide-outline" id="st-outline"></div>
      </div>
      <div class="ide-split v" data-split="side" title="Drag to resize"></div>
      <div class="ide-center">
        <div class="stident">
          <button class="stic" id="st-icon" onclick="studioPickIcon()" title="Choose this app's icon">${iconTile(idIcon,idName||'?',STUDIO.sel||'new',24)}</button>
          <input id="st-name" placeholder="${STUDIO.sel?'App name':'App name (optional)'}" value="${esc(idName||'')}" maxlength="60" aria-label="App name">
          ${STUDIO.sel?'<button class="endbtn" id="st-idsave" onclick="studioSaveIdentity()">Rename</button>':''}
          <span class="sp" style="flex:1"></span>
          ${STUDIO.sel?`<button class="endbtn" id="st-run" onclick="studioRun()" title="Run the code in the editor without saving (Ctrl+Enter)" aria-label="Run">▶<span class="lbl"> Run</span></button>
            <button class="pact" id="st-save" onclick="studioSave()" title="Save as a new version (Ctrl+S)">Save</button>`:''}
        </div>
        <div class="ide-tabs" id="st-tabs" role="tablist"></div>
        <div class="ide-edhost" id="st-editor"></div>
        <div class="ide-split h" data-split="bot" title="Drag to resize"></div>
        <div class="ide-bottom">
          <div class="sttabs" role="tablist">
            <button data-t="builder" class="${on('builder')}" onclick="studioTab('builder')">Builder</button>
            <button data-t="problems" class="${on('problems')}" onclick="studioTab('problems')">Problems <span id="st-probdot"></span></button>
            <button data-t="console" class="${on('console')}" onclick="studioTab('console')">Console <span id="st-condot"></span></button>
            <button data-t="versions" class="${on('versions')}" onclick="studioTab('versions')">Versions</button>
            <button data-t="perms" class="${on('perms')}" onclick="studioTab('perms')">Permissions <span id="st-permdot"></span></button>
            <button data-t="sched" class="${on('sched')}" onclick="studioTab('sched')">Schedules <span id="st-scheddot"></span></button>
          </div>
          <div class="ide-pane" data-for="builder"${STUDIO.tab==='builder'?'':' hidden'}>
            <div id="st-log" class="stlog"></div>
            <div class="stcompose">
              <input id="st-prompt" placeholder="${STUDIO.sel?'Describe a change and your agent makes it…':'Describe the app to build: what it shows, what it tracks, where the data comes from…'}">
              <select id="st-model" class="stmodel" title="Which model builds"><option value="auto">Auto</option></select>
              <button class="pact${STUDIO.building?' stop':''}" id="st-build" onclick="studioBuild()">${STUDIO.building?'Cancel':STUDIO.sel?'Update':'Build'}</button>
            </div>
            <div class="ide-selchip" id="st-selchip" hidden></div>
          </div>
          <div class="ide-pane" data-for="problems"${STUDIO.tab==='problems'?'':' hidden'} id="st-probs"></div>
          <div class="ide-pane" data-for="console"${STUDIO.tab==='console'?'':' hidden'} id="st-console"></div>
          <div class="ide-pane" data-for="panel"${['versions','perms','sched'].includes(STUDIO.tab)?'':' hidden'} id="st-panel"></div>
        </div>
      </div>
      <div class="ide-split v" data-split="prev" title="Drag to resize"></div>
      <div class="ide-right">
        <div class="ide-prevbar">
          <span class="ide-sec" style="padding:0">Preview</span>
          <span id="st-live"></span>
          <span id="st-actions"></span>
        </div>
        <div id="st-prev"></div>
      </div>
      <div class="ide-status" id="st-status"></div>
    </div></div>`;
  STUDIO.log=$('#st-log');STUDIO.preview=$('#st-prev');
  const cachedLog=STUDIO.logs[STUDIO._logKey];
  if(cachedLog){STUDIO.log.innerHTML=cachedLog;studioWireHistory();STUDIO.log.scrollTop=STUDIO.log.scrollHeight}
  else if(STUDIO.sel)studioLoadHistory(STUDIO.sel);   // restore this app's build session from the server
  $('#st-prompt').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();studioBuild()}});
  // a name typed for a NEW app has nowhere to be saved yet — keep it in hand
  $('#st-name').addEventListener('input',e=>{if(!STUDIO.sel)STUDIO.newName=e.target.value});
  $('#st-name').addEventListener('keydown',e=>{if(e.key==='Enter'&&STUDIO.sel)studioSaveIdentity()});
  studioSplits(pb.querySelector('.stide'));
  studioList();studioTabsPaint();
  studioLoadModels();
  studioShowPreview();studioActions();studioPanel();
  await studioOpenEditor(STUDIO.sel);
  if(!STUDIO.sel&&STUDIO.log&&!STUDIO.log.children.length)
    STUDIO.log.innerHTML=`<p class="mut">Describe an app and ${esc(agentName())} builds it live. For example
      <i>"a pomodoro timer"</i>, <i>"track the prices of these three products daily"</i> or
      <i>"a dashboard of my scheduled tasks"</i>. You can also start from a blank file and write it yourself.
      Every build and every save is a version you can go back to.</p>`;
}
function studioSelect(id){
  STUDIO.sel=id||'';STUDIO._hard=true;
  if(STUDIO.sel&&STUDIO.pane==='files')STUDIO.pane='code';
  if(!STUDIO.sel)STUDIO.tab='builder';      // a new app starts by being described
  const w=WM.wins.get('studio');if(w)renderStudio(w.el.querySelector('.wbody'),w);
}
function studioTab(t,auto){
  STUDIO.tab=t;
  const root=document.querySelector('.stide');
  if(root){
    root.querySelectorAll('.sttabs button').forEach(b=>b.classList.toggle('on',b.dataset.t===t));
    const which=['versions','perms','sched'].includes(t)?'panel':t;
    root.querySelectorAll('.ide-pane').forEach(p=>p.hidden=p.dataset.for!==which);
  }
  if(!auto&&STUDIO.pane!=='panel'&&root&&root.offsetWidth<760)studioPane('panel');
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
    // only executors build here: an engine with no file workspace cannot build
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
/* The Builder pane shows how this app came to be: the chat or App Studio sessions
   that built it, as recorded on its versions (/api/apps/{id}/conversations). An app
   built in Chat used to open on the intro text, because the history was found only by
   a "build: <name>" title that a chat turn never had. Older builds without a recorded
   conversation still fall back to that title. */
async function studioLoadHistory(sel){
  try{
    const app=STUDIO.apps.find(a=>a.id===sel);if(!app)return;
    let convs=((await (await fetch('/api/apps/'+sel+'/conversations')).json()).conversations)||[];
    if(!convs.length){
      const all=(await (await fetch('/api/conversations')).json()).conversations||[];
      const c=all.find(x=>x.title==='build: '+app.name);
      if(c)convs=[{id:c.id,title:c.title,origin:'studio'}];
    }
    if(!convs.length)return;
    // oldest first, so it reads as the story of the app; the last three are plenty
    convs=convs.slice(0,3).reverse();
    const parts=[];
    for(const c of convs){
      const msgs=(await (await fetch('/api/conversations/'+c.id)).json()).messages||[];
      const studio=String(c.title||'').startsWith('build: ');
      const lines=msgs.map(m=>{
        if(m.role!=='user'&&m.role!=='assistant')return'';
        let t=(m.content||'').replace(/```[\s\S]*?(```|$)/g,'(code)').trim();
        if(!t)return'';
        if(t.length>600)t=t.slice(0,600)+'…';
        return `<div class="st-msg ${m.role}">${m.role==='user'
          ?`<b class="st-who">${chatWho('@me','You')}</b>${esc(t)}`
          :`<b class="st-who">${chatWho('@agent',esc(agentName()))}</b>${esc(t)}`}</div>`;
      }).filter(Boolean).join('');
      if(!lines)continue;
      parts.push(`<div class="st-src"><span>${studio?'Built in App Studio':'Built in Chat'}${studio?'':` · ${esc(c.title||'')}`}</span>`
        +(studio?'':`<button class="endbtn" data-open-chat="${esc(c.id)}">Open in Chat</button>`)+`</div>`+lines);
    }
    if(STUDIO.sel!==sel||!STUDIO.log||!STUDIO.log.isConnected||STUDIO.log.children.length)return;
    if(!parts.length)return;
    STUDIO.log.innerHTML=parts.join('');
    studioWireHistory();
    STUDIO.log.scrollTop=STUDIO.log.scrollHeight;
  }catch(e){}
}
/* "Open in Chat" from the Builder: carry on there, where the app was made */
function studioWireHistory(){
  if(!STUDIO.log)return;
  STUDIO.log.querySelectorAll('[data-open-chat]').forEach(b=>b.onclick=()=>{
    openApp('chat');setTimeout(()=>{if(typeof openConv==='function')openConv(b.dataset.openChat)},150)});
}
/* built apps postMessage their runtime JS errors here — surface them with a one-click fix */
window.addEventListener('message',ev=>{
  const d=ev.data;
  if(!d||d.agentos!=='app_error')return;
  if(!STUDIO.sel||d.app_id!==STUDIO.sel||!STUDIO.log||!STUDIO.log.isConnected||STUDIO.building)return;
  // Only the frame showing this app. What it says is the app's own text, so a person decides
  // whether to act on it: this used to start a build by itself, as if they had asked.
  const prefix='/api/apps/'+STUDIO.sel+'/page';
  if(![...document.querySelectorAll('iframe')].some(f=>f.contentWindow===ev.source&&(f.getAttribute('src')||'').startsWith(prefix)))return;
  const msg=String(d.message||'').slice(0,300);
  studioConsoleAdd(STUDIO.sel,msg,d.source);
  if(STUDIO._lastErr===msg)return;   // don't spam repeats (e.g. errors in a poll loop)
  STUDIO._lastErr=msg;
  studioLog(`<span style="color:var(--err)">app runtime error: ${esc(msg)}${d.source&&d.source!==':0'?' @ '+esc(String(d.source).slice(0,120)):''}</span>
    <button style="font-size:11px;padding:3px 10px;margin-left:6px" onclick="studioAutoFix()">Fix it</button>`);
});
function studioAutoFix(){
  const p=$('#st-prompt');if(!p||!STUDIO._lastErr)return;
  STUDIO._fixErr=STUDIO._lastErr;     // travels apart from the request, fenced by the server
  p.value='Fix the runtime error this app reported, and keep everything else identical.';
  STUDIO._lastErr=null;
  studioBuild();
}
function studioActions(){
  const box=$('#st-actions');if(!box)return;
  // One row over the preview: the two things done most, and the rest behind ⋯.
  box.innerHTML=STUDIO.sel
    ?`<button class="endbtn" onclick="openApp('ua_${jsq(STUDIO.sel)}')" title="Open this app in its own window">↗ Open</button>
      <button class="endbtn" onclick="studioPreviewSurface()" title="Switch the preview between the app and its widget">${STUDIO.surface==='widget'?'App view':'Widget view'}</button>
      <button class="endbtn" onclick="studioMore(event)" title="Pin, widget size, export, delete" aria-label="More">⋯</button>`:'';
}
function studioMore(e){
  const aid=STUDIO.sel;if(!aid)return;
  const pinned=WIDGETS.some(w=>w.app_id===aid&&(w.desk||1)===curDesk);
  const app=(USERAPPS||[]).find(a=>a.id===aid);
  const size=(app&&app.widget_size)||'m';
  const items=[
    {label:pinned?'Unpin from this desktop':'Pin to Desktop '+curDesk,fn:()=>{pinned?unpinWidget(aid):pinWidget(aid);studioActions()}},
    null,
    ...Object.entries(WIDGET_SIZES).map(([k,d])=>({label:(k===size?'✓ ':'   ')+'Widget size '+k.toUpperCase()+' · '+d.w+'×'+d.h,
      fn:()=>setWidgetSize(aid,k)})),
    null,
    {label:'Export',fn:()=>window.open('/api/apps/'+aid+'/export')},
    ...((typeof USERS!=='undefined'&&(USERS.me||{}).multiuser&&app)?[{label:'Share…',fn:()=>usersShare('app',app.name)}]:[]),
    {label:'Delete app…',danger:true,fn:()=>studioDel(aid)},
  ];
  const r=e.currentTarget.getBoundingClientRect();
  showCtxItems({clientX:r.left,clientY:r.bottom+4},items);
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
        <iframe src="/api/apps/${STUDIO.sel}/page?surface=widget&size=${size}&t=${Date.now()}" sandbox="allow-scripts allow-forms"></iframe>
      </div></div>`;
    return;
  }
  const dr=STUDIO.draft&&STUDIO.draft.aid===STUDIO.sel?'&draft='+encodeURIComponent(STUDIO.draft.id):'';
  STUDIO.preview.innerHTML=`<iframe src="/api/apps/${STUDIO.sel}/page?t=${Date.now()}${dr}" style="width:100%;height:100%;border:none;background:#0e1116" sandbox="allow-scripts allow-forms"></iframe>`;
}
/* ---- bottom panel: versions | permissions --------------------------------- */
function studioPanel(){
  if(STUDIO.tab==='perms')studioPerms();else if(STUDIO.tab==='sched')studioSchedules();
  else if(STUDIO.tab==='versions')studioVersions();
  else if(STUDIO.tab==='problems')studioProblemsPaint();else if(STUDIO.tab==='console')studioConsolePaint();
  studioSchedCount();
  // on a phone the tab row scrolls: the chosen tab is the one in view
  const on=document.querySelector('.sttabs button.on');if(on)on.scrollIntoView({block:'nearest',inline:'nearest'});
}
/* The schedules that keep this app fresh or watch for it (tasks.app_id), the same rows
   Missions → Schedule lists. Asked for as "if I ask to set up the schedule, that
   connection should be there": a schedule set up for an app, from the app itself, from
   Chat or from here, is one row in both places. */
async function studioSchedRows(){
  if(!STUDIO.sel)return [];
  const d=await fetch('/api/tasks').then(r=>r.json()).catch(()=>({tasks:[]}));
  return (d.tasks||[]).filter(t=>t.app_id===STUDIO.sel);
}
async function studioSchedCount(){
  const dot=$('#st-scheddot');if(!dot)return;
  const n=(await studioSchedRows()).length;
  if(dot.isConnected)dot.textContent=n?'· '+n:'';
}
async function studioSchedules(){
  const box=$('#st-panel');if(!box)return;
  if(!STUDIO.sel){box.innerHTML='<p class="mut" style="font-size:12px">An app can keep itself up to date on a schedule, even while it is closed. Build it first, then ask here, for example <i>refresh the prices every 10 minutes</i>.</p>';return}
  const rows=await studioSchedRows();
  if(STUDIO.tab!=='sched'||!box.isConnected)return;
  const st={ok:'done',failed:'failed',skipped:'skipped',running:'running',stopped:'stopped'};
  box.innerHTML=rows.map(t=>`<div class="st-sched">
      <span class="grow"><b>${esc(t.words||'')}</b>${t.enabled?'':' · <span class="mut">paused</span>'}
        <span class="sub">${esc(t.title||t.prompt||'')}</span>
        <span class="sub">${t.last_status?'last run '+esc(st[t.last_status]||t.last_status)+(t.last_at&&typeof jobAgo==='function'?' '+esc(jobAgo(t.last_at)):''):'has not run yet'}</span></span>
      <button class="endbtn" onclick="studioOpenSchedules()">Open in Missions</button></div>`).join('')
    ||`<p class="mut" style="font-size:12px">Nothing runs for this app on its own yet. Ask above, for example
       <i>check the prices every 10 minutes</i>, and it is set up here and in Missions → Schedule.</p>`;
}
function studioOpenSchedules(){openApp('tasks');refreshApp('tasks')}   // Missions → Schedule
async function studioVersions(){
  const box=$('#st-panel'),live=$('#st-live');
  if(!box)return;
  if(!STUDIO.sel){box.innerHTML='<p class="mut" style="font-size:12px">Versions appear once an app is built — every build and every edit records one, and any of them can be restored.</p>';if(live)live.innerHTML='';return}
  const d=await fetch('/api/apps/'+STUDIO.sel+'/versions').then(r=>r.json()).catch(()=>({versions:[]}));
  if(STUDIO.tab!=='versions'||!box.isConnected)return;
  const vs=d.versions||[];
  const cur=vs[0];
  studioBadge();
  const ago=t=>{const s=Math.max(1,Math.round(Date.now()/1000-t));return s<60?s+'s':s<3600?Math.round(s/60)+'m':s<86400?Math.round(s/3600)+'h':Math.round(s/86400)+'d'};
  box.innerHTML=(vs.map(v=>`<div style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:12px;border-bottom:1px solid var(--line)">
      <b style="flex:0 0 34px;color:${v===cur?'var(--ok)':'var(--dim)'}">v${v.version}</b>
      <span class="mut" style="flex:0 0 40px">${ago(v.created_at)}</span>
      <span style="flex:1;color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(v.note||'')}">${esc(v.note||'')}</span>
      <button class="endbtn" style="flex:0 0 auto;font-size:11px;padding:2px 10px" onclick="studioCompare(${+v.version})" title="Compare this version with the editor">Compare</button>
      ${v===cur?'<span style="font-size:10.5px;color:var(--ok)">live</span>'
        :`<button style="flex:0 0 auto;font-size:11px;padding:2px 10px" onclick="studioRestore(${+v.version})">Restore</button>`}
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
  STUDIO.draft='';await studioCheckVersion(STUDIO.sel);
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
  STUDIO._cur.innerHTML=(STUDIO._cur===STUDIO._first?'<b class="st-who">'+chatWho('@agent',esc(agentName()))+'</b>':'')+md(body);
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
async function studioBuild(){
  if(STUDIO.building){                       // the button doubles as Cancel while a build runs
    if(ws&&ws.readyState===1)ws.send(JSON.stringify({type:'build_abort'}));
    return;
  }
  const p=$('#st-prompt');if(!p)return;
  let prompt=p.value.trim();if(!prompt)return;
  if(!ws||ws.readyState!==1)return toast('not connected');
  // The builder starts from the SAVED app. Edits still in the editor would be built over,
  // so they are saved first (or the person says to go ahead without them).
  const doc=STUDIO.sel&&STUDIO.docs[STUDIO.sel];
  if(doc&&doc.text!==doc.saved){
    const save=await osConfirm('Save your edits first?','The builder works on the saved app. Unsaved edits in the editor would be left out.',
      {confirmText:'Save and build',cancelText:'Build without them'});
    if(save&&!(await studioSave()))return;
  }
  // A selection in the editor travels with the request, so "make this faster" has a "this".
  const sel=STUDIO.useSel&&STUDIO.ed&&STUDIO.ed._aid===STUDIO.sel&&STUDIO.ed.selection();
  const shown=prompt;
  if(sel&&sel.text.trim())prompt+=`\n\n(This is about lines ${sel.from}–${sel.to} of the app's file:)\n\`\`\`html\n${sel.text.slice(0,6000)}\n\`\`\``;
  STUDIO.building=true;studioStatus();
  const b=$('#st-build');if(b){b.textContent='Cancel';b.classList.add('stop')}
  studioEndSay();STUDIO._first=null;STUDIO.tools={};
  studioLog(`<b style="color:var(--acc2)">You:</b> ${esc(shown)}${sel&&sel.text.trim()?` <span class="mut">· lines ${sel.from}–${sel.to}</span>`:''}`);
  studioTickStart();
  jarvisOn();
  const bmodel=$('#st-model')?.value||STUDIO.model||'auto';
  const msg={type:'build',prompt,app_id:STUDIO.sel,model:bmodel};
  // identity travels with the build: an app the user named is not renamed by the model
  const nm=($('#st-name')?.value||'').trim();
  if(nm)msg.name=nm;
  if(!STUDIO.sel&&STUDIO.newIcon)msg.icon=STUDIO.newIcon;
  if(STUDIO._fixErr){msg.app_error=STUDIO._fixErr;STUDIO._fixErr=null}
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
  studioStatus();
}
function studioBuildEvent(ev){
  switch(ev.type){
    case 'build_start': STUDIO._engShown=false;break;
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
    case 'build_engine':   // who is building, in its own name ("claude-code · 12 tools" was a log line)
      if(STUDIO._engShown)break;STUDIO._engShown=true;   // once a build, not once a stage
      studioLog(`<span class="mut">◈ ${esc(EXEC_TITLES[ev.engine]||ev.engine||'executor')}`
        +`${ev.model?' on '+esc(ev.model):''}</span>`);break;
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
      if(ok&&ev.name==='schedule_task'){
        // set up for this app: the same door Chat's chip gives, and the tab here counts it
        const what=String(ev.output||'').replace(/^scheduled task \w+( for this app)?: ?/,'');
        setTimeout(()=>{studioLog(`<span class="st-schedok">⏱ Scheduled for this app${what?' · '+esc(what):''}</span>`
          +` <button class="endbtn" onclick="studioOpenSchedules()">Open in Missions</button>`);studioSchedCount()},0);
      }
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
          STUDIO.tab='perms';setTimeout(()=>studioTab('perms',true),0);
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

/* ================= the IDE: explorer, editor tabs, problems, console, status ================= */
function studioLayout(){
  let v={};try{v=JSON.parse(localStorage.getItem('studio.layout')||'{}')}catch(e){}
  return {prev:Math.max(240,Math.min(900,+v.prev||380)),bot:Math.max(120,Math.min(640,+v.bot||230)),
          side:Math.max(150,Math.min(400,+v.side||210))};
}
/* The three dividers. Sizes are per browser, a convenience, and the layout still works
   when storage is blocked. */
function studioSplits(root){
  if(!root)return;
  root.querySelectorAll('.ide-split').forEach(h=>h.onpointerdown=e=>{
    e.preventDefault();h.setPointerCapture(e.pointerId);
    const which=h.dataset.split,lay=studioLayout(),x0=e.clientX,y0=e.clientY,start={...lay};
    const scale=root.getBoundingClientRect().width/(root.offsetWidth||1)||1;   // a window opens under a scale transform
    h.onpointermove=m=>{
      const dx=(m.clientX-x0)/scale,dy=(m.clientY-y0)/scale;
      if(which==='prev')lay.prev=Math.max(240,Math.min(900,start.prev-dx));
      if(which==='side')lay.side=Math.max(150,Math.min(400,start.side+dx));
      if(which==='bot')lay.bot=Math.max(120,Math.min(640,start.bot-dy));
      root.style.setProperty('--ide-'+which,lay[which]+'px');
    };
    h.onpointerup=()=>{h.onpointermove=h.onpointerup=null;try{localStorage.setItem('studio.layout',JSON.stringify(lay))}catch(e){}};
  });
  root.addEventListener('keydown',e=>{
    if(!e.defaultPrevented&&(e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='s'&&STUDIO.sel){e.preventDefault();studioSave()}
  });
}
/* On a phone the IDE is one pane at a time: apps, code, preview or the panel. */
function studioPane(k){
  STUDIO.pane=k;
  const root=document.querySelector('.stide');if(!root)return;
  root.dataset.pane=k;
  root.querySelectorAll('.ide-seg button').forEach(b=>b.classList.toggle('on',b.dataset.p===k));
  if(k==='code'&&STUDIO.ed)STUDIO.ed.set(STUDIO.ed.get(),true);   // a hidden textarea had no size to paint at
}
function studioDirty(aid){const d=STUDIO.docs[aid];return !!(d&&d.text!==d.saved)}
function studioList(){
  const box=$('#st-list');if(!box)return;
  const q=(($('#st-q')||{}).value||'').trim();
  box.innerHTML=`<button class="stapp${STUDIO.sel?'':' on'}" data-f="new app" onclick="studioSelect('')">
      <span class="mono" style="background:var(--bg4);color:var(--acc)">＋</span>
      <span class="nm"><b>New app</b><span>describe it, or start blank</span></span>
    </button>`+STUDIO.apps.map(a=>`
    <button class="stapp${a.id===STUDIO.sel?' on':''}" data-f="${esc(a.name+' '+(a.description||''))}" onclick="studioSelect('${jsq(a.id)}')">
      ${iconTile(a.icon,a.name,a.id,24)}
      <span class="nm"><b>${esc(a.name)}${studioDirty(a.id)?' <i class="ide-dot" title="unsaved edits">●</i>':''}</b><span>${esc(a.description||'')}</span></span>
      <span class="stren" title="rename this app" onclick="event.stopPropagation();renameUserApp('${jsq(a.id)}','studio')">✏️</span>
    </button>`).join('');
  if(q&&typeof listFilter==='function')listFilter(box,q);
}
function studioTabsPaint(){
  const box=$('#st-tabs');if(!box)return;
  if(!STUDIO.tabs.length){box.innerHTML='<span class="ide-tab on"><span>New app</span></span>';return}
  box.innerHTML=STUDIO.tabs.map(id=>{
    const a=STUDIO.apps.find(x=>x.id===id)||{name:id};
    return `<span class="ide-tab${id===STUDIO.sel?' on':''}" role="tab" onclick="studioSelect('${jsq(id)}')" title="${esc(a.name)}">
      <span>${esc(a.name)}.html</span>${studioDirty(id)?'<i class="ide-dot" title="unsaved edits">●</i>':''}
      <button class="ide-tx" title="Close" onclick="event.stopPropagation();studioCloseTab('${jsq(id)}')">✕</button></span>`;
  }).join('');
}
async function studioCloseTab(id){
  if(studioDirty(id)&&!await osConfirm('Close without saving?','Your edits to this app are not saved.',{danger:true,confirmText:'Close'}))return;
  delete STUDIO.docs[id];delete STUDIO.probs[id];
  const i=STUDIO.tabs.indexOf(id);STUDIO.tabs=STUDIO.tabs.filter(x=>x!==id);
  if(STUDIO.sel===id)studioSelect(STUDIO.tabs[Math.min(i,STUDIO.tabs.length-1)]||'');else studioTabsPaint();
}
/* The editor for the chosen app. Its text survives every repaint and app switch, so a
   tab can be left with edits in it and come back to them. */
async function studioOpenEditor(aid){
  const host=$('#st-editor');if(!host)return;
  STUDIO.ed=null;
  if(!aid){
    host.innerHTML=`<div class="ide-welcome">
      <b>New app</b>
      <p class="mut">Describe it in the Builder and ${esc(agentName())} writes it, or start from a blank file and write it yourself.</p>
      <div class="row"><button class="pact" onclick="studioPane('panel');studioTab('builder');$('#st-prompt').focus()">Describe it</button>
        <button class="endbtn" onclick="studioNewBlank()">Start from a blank file</button></div>
      <p class="mut ide-keys">In the editor: Ctrl+S saves, Ctrl+Enter runs, Ctrl+F finds, Ctrl+G goes to a line, Ctrl+/ comments.</p>
    </div>`;
    studioOutlinePaint();studioStatus();studioBadge();
    return;
  }
  host.innerHTML='<div class="ide-welcome mut">opening…</div>';
  let doc=STUDIO.docs[aid];
  if(!doc){
    let src;try{src=await apiJSON('/api/apps/'+aid+'/source')}catch(e){host.innerHTML=`<div class="ide-welcome">${esc(e.message)}</div>`;return}
    if(src.error){host.innerHTML=`<div class="ide-welcome">${esc(src.error)}</div>`;return}
    doc=STUDIO.docs[aid]={text:src.html,saved:src.html,base:src.version,view:null};
  }
  if(STUDIO.sel!==aid||!host.isConnected)return;
  const ed=ideEditor(host,{value:doc.text,
    onChange:t=>studioDocChanged(aid,t),onSave:()=>studioSave(),onRun:()=>studioRun(),onCursor:()=>{studioStatus();studioSelChip()}});
  ed._aid=aid;STUDIO.ed=ed;
  ed.restore(doc.view);
  if(STUDIO.probs[aid])ed.setMarks(STUDIO.probs[aid]);else studioCheck(aid);
  studioOutlinePaint();studioStatus();studioBadge();studioProblemsPaint();
  if(doc.stale)studioStaleBanner(aid);
}
function studioDocChanged(aid,text){
  const doc=STUDIO.docs[aid];if(!doc)return;
  const was=doc.text!==doc.saved;doc.text=text;
  const now=doc.text!==doc.saved;
  if(was!==now){studioTabsPaint();studioList();studioBadge()}
  clearTimeout(STUDIO._olT);STUDIO._olT=setTimeout(studioOutlinePaint,400);
  clearTimeout(STUDIO._ckT);STUDIO._ckT=setTimeout(()=>studioCheck(aid),1200);
  studioStatus();
}
/* The checker reads the text in the editor, saved or not, so a problem is found while it
   is being made rather than after the next build. */
async function studioCheck(aid){
  const doc=STUDIO.docs[aid];if(!doc)return;
  const text=doc.text;
  let r;try{r=await (await fetch('/api/apps/check',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({html:text})})).json()}catch(e){return}
  if(!STUDIO.docs[aid]||STUDIO.docs[aid].text!==text)return;     // the text moved on while it was checked
  const probs=(r.problems||[]).slice();
  (r.structure||[]).forEach(m=>probs.unshift({severity:'broken',rule:'structure',message:m,fix:'',line:0}));
  STUDIO.probs[aid]=probs;
  if(STUDIO.ed&&STUDIO.ed._aid===aid)STUDIO.ed.setMarks(probs);
  if(STUDIO.sel===aid){studioProblemsPaint();studioStatus()}
}
var STUDIO_SEV={broken:['err','✖','breaks'],contract:['warn','▲','not a Bento app yet'],polish:['info','●','small']};
function studioProblemsPaint(){
  const box=$('#st-probs'),dot=$('#st-probdot');
  const probs=STUDIO.sel?(STUDIO.probs[STUDIO.sel]||[]):[];
  const bad=probs.filter(p=>p.severity!=='polish').length;
  if(dot)dot.innerHTML=probs.length?`<span class="ide-count${probs.some(p=>p.severity==='broken')?' err':''}">${probs.length}</span>`:'';
  if(!box)return;
  if(!STUDIO.sel){box.innerHTML='<p class="mut ide-empty">Open an app to see what the checker finds in it.</p>';return}
  if(!probs.length){box.innerHTML='<p class="mut ide-empty">✓ No problems in this file.</p>';return}
  box.innerHTML=probs.map((p,i)=>{const s=STUDIO_SEV[p.severity]||STUDIO_SEV.polish;
    return `<div class="ide-prob ${s[0]}${p.line?' go':''}" ${p.line?`onclick="studioGoto(${+p.line})" title="Go to line ${+p.line}"`:''}>
      <span class="ic" title="${esc(s[2])}">${s[1]}</span>
      <span class="grow"><span>${esc(p.message)}</span>${p.fix?`<span class="sub">${esc(p.fix)}</span>`:''}</span>
      <span class="ln mut">${p.line?'line '+p.line:'file'}</span>
      <button class="endbtn" onclick="event.stopPropagation();studioFixWith(${i})" title="Ask the builder to fix this">Fix it</button>
    </div>`}).join('')+(bad?'':'<p class="mut ide-empty">Only small things left.</p>');
}
function studioGoto(line){
  if(!STUDIO.ed)return;
  if(STUDIO.pane!=='code'&&document.querySelector('.stide')?.offsetWidth<760)studioPane('code');
  STUDIO.ed.goto(line);
}
function studioFixWith(i){
  const p=(STUDIO.probs[STUDIO.sel]||[])[i];if(!p)return;
  studioTab('builder');
  const inp=$('#st-prompt');if(!inp)return;
  inp.value=`Fix this${p.line?' (line '+p.line+')':''}: ${p.message}${p.fix?'. '+p.fix:''}. Keep everything else the same.`;
  inp.focus();
}
/* What the app reported while it ran: its own errors, from the preview frame. */
function studioConsoleAdd(aid,msg,source){
  if(!aid)return;
  const list=STUDIO.cons[aid]=STUDIO.cons[aid]||[];
  const last=list[list.length-1];
  if(last&&last.msg===msg){last.n++;last.t=Date.now()}
  else list.push({msg,source:String(source||'').slice(0,120),t:Date.now(),n:1});
  if(list.length>200)list.splice(0,list.length-200);
  if(STUDIO.sel===aid)studioConsolePaint();
}
function studioConsolePaint(){
  const box=$('#st-console'),dot=$('#st-condot');
  const list=STUDIO.sel?(STUDIO.cons[STUDIO.sel]||[]):[];
  if(dot)dot.innerHTML=list.length?`<span class="ide-count err">${list.length}</span>`:'';
  if(!box)return;
  if(!list.length){box.innerHTML='<p class="mut ide-empty">Errors the app throws while it runs show here.</p>';return}
  box.innerHTML=`<div class="ide-conbar"><span class="mut">${list.length} error${list.length===1?'':'s'} from the running app</span>
      <button class="endbtn" onclick="STUDIO.cons[STUDIO.sel]=[];studioConsolePaint()">Clear</button></div>`
    +list.map(c=>`<div class="ide-con"><span class="mut">${new Date(c.t).toLocaleTimeString()}</span>
      <span class="grow">${esc(c.msg)}${c.n>1?` <span class="ide-count">${c.n}</span>`:''}${c.source&&c.source!==':0'?`<span class="sub">${esc(c.source)}</span>`:''}</span></div>`).join('');
  box.scrollTop=box.scrollHeight;
}
var STUDIO_OUTLINE_IC={css:'#',js:'{}',fn:'ƒ',id:'◇',surface:'▣',ai:'✦'};
function studioOutlinePaint(){
  const box=$('#st-outline'),n=$('#st-outn');if(!box)return;
  const doc=STUDIO.sel&&STUDIO.docs[STUDIO.sel];
  if(!doc){box.innerHTML='<p class="mut ide-empty">The parts of the open file show here.</p>';if(n)n.textContent='';return}
  const items=ideOutline(doc.text);
  if(n)n.textContent=items.length?String(items.length):'';
  box.innerHTML=items.map(it=>`<button class="ide-ol k-${it.kind}" onclick="studioGoto(${+it.line})" title="line ${+it.line}">
      <span class="ic">${STUDIO_OUTLINE_IC[it.kind]||'·'}</span><span class="nm">${esc(it.name)}</span><span class="mut">${+it.line}</span></button>`).join('')
    ||'<p class="mut ide-empty">Nothing to list yet.</p>';
}
function studioStatus(){
  const box=$('#st-status');if(!box)return;
  if(!STUDIO.sel){box.innerHTML=`<span>New app</span><span class="sp"></span><span>${STUDIO.building?'building…':'ready'}</span>`;return}
  const doc=STUDIO.docs[STUDIO.sel],ed=STUDIO.ed&&STUDIO.ed._aid===STUDIO.sel?STUDIO.ed:null;
  const p=ed?ed.pos():{line:1,col:1,sel:0},mode={html:'HTML',css:'CSS',js:'JavaScript'}[ed?ed.mode():'html'];
  const probs=STUDIO.probs[STUDIO.sel]||[],errs=probs.filter(x=>x.severity==='broken').length;
  const lines=doc?doc.text.split('\n').length:0;
  box.innerHTML=`<span>${doc?'v'+doc.base:''}${studioDirty(STUDIO.sel)?' · edited':''}</span>
    <span class="${errs?'bad':''}" onclick="studioTab('problems')" style="cursor:pointer">${errs?'✖ '+errs:'✓'}${probs.length-errs?' · ▲ '+(probs.length-errs):''}</span>
    <span class="sp"></span>
    ${STUDIO.building?'<span class="acc">building…</span>':''}
    <span>Ln ${p.line}, Col ${p.col}${p.sel?' ('+p.sel+' selected)':''}</span>
    <span>${lines} lines</span><span>${mode}</span><span>Spaces: 2</span>`;
}
/* The badge over the preview says which code is running in it. */
function studioBadge(){
  const live=$('#st-live');if(!live)return;
  if(!STUDIO.sel){live.innerHTML='';return}
  const doc=STUDIO.docs[STUDIO.sel];
  const draft=STUDIO.draft&&STUDIO.draft.aid===STUDIO.sel;
  live.innerHTML=draft?'<span class="ide-pill warn">running unsaved code</span>'
    :doc?`<span class="ide-pill ok">v${doc.base} live</span>${studioDirty(STUDIO.sel)?' <span class="ide-pill">edits not saved</span>':''}`:'';
}
/* When text is selected, the next request to the builder can be about it. */
function studioSelChip(){
  const chip=$('#st-selchip');if(!chip)return;
  const sel=STUDIO.ed&&STUDIO.ed.selection();
  if(!sel||!sel.text.trim()){chip.hidden=true;return}
  chip.hidden=false;
  chip.innerHTML=`<label><input type="checkbox" ${STUDIO.useSel?'checked':''} onchange="STUDIO.useSel=this.checked">
    Include lines ${sel.from}–${sel.to} in the request</label>`;
}
/* Save is a version. The server refuses it when the app moved on since it was opened
   (a build, a chat, another window), and the person chooses which one stays. */
async function studioSave(force){
  const aid=STUDIO.sel,doc=STUDIO.docs[aid];if(!aid||!doc)return false;
  if(doc.text===doc.saved&&!force){toast('nothing to save');return true}
  const btn=$('#st-save');if(btn)btn.disabled=true;
  const text=doc.text;
  let r,d;
  try{r=await fetch('/api/apps/'+aid+'/source',{method:'PUT',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({html:text,base:doc.base,force:!!force})});d=await r.json().catch(()=>({}))}
  catch(e){if(btn)btn.disabled=false;toast('could not save: '+e.message);return false}
  if(btn)btn.disabled=false;
  if(r.status===409){doc.stale=d.current;studioStaleBanner(aid);return false}
  if(!r.ok){toast(d.error||'could not save');return false}
  doc.saved=text;doc.base=d.version;doc.stale=0;
  STUDIO.draft='';
  if(STUDIO.sel===aid){studioTabsPaint();studioList();studioStatus();studioBadge();studioShowPreview();
    if(STUDIO.tab==='versions')studioVersions()}
  toast(d.changed?'saved as v'+d.version:'nothing changed');
  if(d.review){toast('it asks for something different now, so its permissions are up for review');
    if(STUDIO.sel===aid){studioTab('perms')}}
  return true;
}
/* Run the editor's code in the preview without saving it. */
async function studioRun(){
  const aid=STUDIO.sel,doc=STUDIO.docs[aid];if(!aid||!doc)return;
  if(doc.text===doc.saved){STUDIO.draft='';studioShowPreview();studioBadge();return}
  let d;try{d=await apiJSON('/api/apps/'+aid+'/draft',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({html:doc.text})})}catch(e){return toast(e.message)}
  if(d.error)return toast(d.error);
  STUDIO.draft={aid,id:d.draft};
  if(STUDIO.sel===aid){studioShowPreview();studioBadge()}
  if(document.querySelector('.stide')?.offsetWidth<760)studioPane('preview');
}
/* Something else saved the app: a build, a chat turn, another window. With no edits in
   the editor it simply follows; with edits, the person decides. */
async function studioCheckVersion(aid){
  const doc=aid&&STUDIO.docs[aid];if(!doc)return;
  let src;try{src=await apiJSON('/api/apps/'+aid+'/source')}catch(e){return}
  if(!src||src.error||src.version===doc.base)return;
  if(doc.text===doc.saved){
    doc.text=doc.saved=src.html;doc.base=src.version;doc.stale=0;
    if(STUDIO.ed&&STUDIO.ed._aid===aid){STUDIO.ed.set(src.html,true);studioOutlinePaint();studioCheck(aid)}
  }else{doc.stale=src.version;doc.theirs=src.html;studioStaleBanner(aid)}
  if(STUDIO.sel===aid){studioStatus();studioBadge();studioTabsPaint()}
}
function studioStaleBanner(aid){
  const host=$('#st-editor');if(!host||STUDIO.sel!==aid)return;
  const doc=STUDIO.docs[aid];if(!doc||!doc.stale)return;
  host.querySelector('.ide-stale')?.remove();
  const b=document.createElement('div');b.className='ide-stale';
  b.innerHTML=`<span>The app changed while you were editing (it's v${+doc.stale} now).</span>
    <button class="endbtn" data-a="theirs">Load v${+doc.stale}</button>
    <button class="endbtn" data-a="diff">Compare</button>
    <button class="pact" data-a="mine">Keep mine and save</button>`;
  b.querySelector('[data-a=theirs]').onclick=async()=>{
    if(!await osConfirm('Load v'+doc.stale+'?','Your edits in the editor are dropped.',{danger:true,confirmText:'Load it'}))return;
    const src=await apiJSON('/api/apps/'+aid+'/source');
    doc.text=doc.saved=src.html;doc.base=src.version;doc.stale=0;
    b.remove();if(STUDIO.ed)STUDIO.ed.set(src.html);studioTabsPaint();studioList();studioStatus();studioBadge();studioCheck(aid);
  };
  b.querySelector('[data-a=diff]').onclick=()=>studioCompare(doc.stale);
  b.querySelector('[data-a=mine]').onclick=async()=>{if(await studioSave(true))b.remove()};
  host.prepend(b);
}
async function studioNewBlank(){
  const name=(($('#st-name')||{}).value||'').trim()||await osPrompt('Name the new app',{value:'My app',confirmText:'Create'});
  if(!name)return;
  let d;try{d=await apiJSON('/api/apps/new',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name,icon:STUDIO.newIcon||''})})}catch(e){return toast(e.message)}
  if(d.error)return toast(d.error);
  STUDIO.newName='';STUDIO.newIcon='';
  if(typeof loadUserApps==='function')loadUserApps();
  STUDIO.pane='code';studioSelect(d.id);
  toast(d.name+' started from a blank file');
}
/* Versions → Compare: that version against what is in the editor now. */
async function studioCompare(v){
  const aid=STUDIO.sel,doc=STUDIO.docs[aid];if(!aid)return;
  let old;try{old=await apiJSON('/api/apps/'+aid+'/versions/'+v)}catch(e){return toast(e.message)}
  const now=doc?doc.text:'';
  const r=ideDiff(old.html||'',now);
  const ov=document.createElement('div');ov.className='stiov';
  const body=r.tooBig?'<p class="mut">These two are too different to compare line by line here.</p>'
    :!r.rows.length?'<p class="mut">No difference: the editor holds exactly v'+(+v)+'.</p>'
    :`<div class="ide-diff">${r.head?`<div class="dl skip">… ${r.head} unchanged line${r.head===1?'':'s'}</div>`:''}${r.rows.map(x=>
      `<div class="dl ${x.k==='+'?'add':x.k==='-'?'del':''}"><span class="n">${x.a||''}</span><span class="n">${x.b||''}</span><span class="k">${x.k}</span><span class="t">${esc(x.t)||' '}</span></div>`).join('')}${r.tail?`<div class="dl skip">… ${r.tail} unchanged line${r.tail===1?'':'s'}</div>`:''}</div>`;
  ov.innerHTML=`<div class="stibox ide-diffbox">
    <div class="ide-diffhead"><b>v${+v} → the editor</b>
      ${r.rows?`<span class="ide-pill ok">+${r.added}</span><span class="ide-pill err">−${r.removed}</span>`:''}
      <span class="sp"></span><button class="endbtn sti-x">Close</button></div>${body}</div>`;
  document.body.appendChild(ov);
  const close=()=>ov.remove();
  ov.querySelector('.sti-x').onclick=close;ov.onclick=e=>{if(e.target===ov)close()};
  ov.addEventListener('keydown',e=>{if(e.key==='Escape')close()});
}
