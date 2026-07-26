/* ================= app studio (agentic builder) ================= */
let STUDIO={apps:[],sel:'',building:false,log:null,preview:null,logs:{},model:localStorage.getItem('studioModel')||'auto'};
async function renderStudio(body,w){
  // preserve the builder session log across re-renders and app switches
  if(STUDIO.log&&STUDIO.log.isConnected&&STUDIO._logKey)STUDIO.logs[STUDIO._logKey]=STUDIO.log.innerHTML;
  const r=await fetch('/api/apps?html=1');const d=await r.json();STUDIO.apps=d.apps;
  if(STUDIO.sel&&!d.apps.find(a=>a.id===STUDIO.sel))STUDIO.sel='';
  STUDIO._logKey=STUDIO.sel||'new';
  const sideItems=d.apps.map(a=>`
    <button class="stapp${a.id===STUDIO.sel?' on':''}" data-f="${esc(a.name+' '+(a.description||''))}" onclick="studioSelect('${a.id}')">
      <span class="mono" style="background:${tileBg(a.id)}">${esc((a.name||'?')[0].toUpperCase())}</span>
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
        <div class="stcompose">
          <input id="st-prompt" placeholder="${STUDIO.sel?'Describe a change to make to this app…':'Describe the app to build — what it shows, what it tracks, where the data comes from…'}">
          <select id="st-model" class="stmodel" title="Model used to build — Auto picks the most build-capable one available"><option value="auto">Auto</option></select>
          <button class="pact${STUDIO.building?' stop':''}" style="flex:0 0 92px" id="st-build" onclick="studioBuild()">${STUDIO.building?'Cancel':STUDIO.sel?'Update':'Build'}</button>
        </div>
        <div style="flex:1;min-height:0;display:flex">
          <div style="flex:0 0 38%;display:flex;flex-direction:column;border-right:1px solid var(--line);min-width:0">
            <div class="tmsec" style="margin:8px 12px 4px">Builder</div>
            <div id="st-log" style="flex:1;overflow-y:auto;padding:2px 12px 10px;font-size:12.5px;user-select:text"></div>
            <div id="st-versions" style="flex:0 0 auto;max-height:190px;overflow-y:auto;border-top:1px solid var(--line);padding:8px 12px 10px"></div>
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
  studioLoadModels();
  studioShowPreview();studioActions();studioVersions();
  if(!STUDIO.sel&&STUDIO.log&&!STUDIO.log.children.length)
    STUDIO.log.innerHTML=`<p class="mut">Describe an app and ${esc(agentName())} builds it live — e.g.
      <i>"a pomodoro timer"</i>, <i>"track the prices of these three products daily"</i>,
      <i>"a dashboard of my scheduled tasks"</i>, or <i>"a button that runs neofetch and shows the output"</i>.
      Apps can call the OS and MCP tools, use the AI model inside their features (appLLM), store their
      own data, run checks on a schedule, and send you alerts on Telegram when something changes.
      Pick an app on the left to refine it — every build is versioned and can be rolled back below.</p>`;
}
function studioSelect(id){
  STUDIO.sel=id||'';
  const w=WM.wins.get('studio');if(w)renderStudio(w.el.querySelector('.wbody'),w);
}
async function studioLoadModels(){
  const sel=$('#st-model');if(!sel)return;
  try{
    const d=await (await fetch('/api/models')).json();
    const cur=STUDIO.model||'auto';
    sel.innerHTML='<option value="auto">Auto — best available</option>'+
      (d.models||[]).map(m=>`<option value="${esc(m.id)}">${esc(m.name+' · '+m.provider+(m.provider==='ollama'?' (local)':''))}</option>`).join('');
    sel.value=[...sel.options].some(o=>o.value===cur)?cur:'auto';
    STUDIO.model=sel.value;
  }catch(e){}
  sel.onchange=()=>{STUDIO.model=sel.value;localStorage.setItem('studioModel',sel.value)};
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
  box.innerHTML=STUDIO.sel
    ?`<button class="endbtn" onclick="openApp('ua_${STUDIO.sel}')">↗ Open window</button>
      <button class="endbtn" onclick="${pinned?`unpinWidget('${STUDIO.sel}')`:`pinWidget('${STUDIO.sel}')`};studioActions()">${pinned?'Unpin':'Pin to Desktop '+curDesk}</button>
      <button class="endbtn" onclick="window.open('/api/apps/${STUDIO.sel}/export')">Export</button>
      <button class="endbtn" onclick="studioDel('${STUDIO.sel}')">Delete</button>`:'';
}
function studioShowPreview(){
  if(!STUDIO.preview)return;
  STUDIO.preview.innerHTML=STUDIO.sel
    ?`<iframe src="/api/apps/${STUDIO.sel}/page?t=${Date.now()}" style="width:100%;height:100%;border:none;background:#0e1116" sandbox="allow-scripts allow-same-origin allow-forms"></iframe>`
    :'<div class="mut" style="display:flex;height:100%;align-items:center;justify-content:center;padding:20px;text-align:center">the built app will preview here</div>';
}
async function studioVersions(){
  const box=$('#st-versions'),live=$('#st-live');
  if(!box)return;
  if(!STUDIO.sel){box.innerHTML='';if(live)live.innerHTML='';return}
  const d=await fetch('/api/apps/'+STUDIO.sel+'/versions').then(r=>r.json()).catch(()=>({versions:[]}));
  const vs=d.versions||[];
  const cur=vs[0];
  if(live)live.innerHTML=cur
    ?`<span style="font-size:11px;color:var(--ok);border:1px solid var(--ok);border-radius:999px;padding:1px 9px">deployed · v${cur.version}</span>`:'';
  const ago=t=>{const s=Math.max(1,Math.round(Date.now()/1000-t));return s<60?s+'s':s<3600?Math.round(s/60)+'m':s<86400?Math.round(s/3600)+'h':Math.round(s/86400)+'d'};
  box.innerHTML=`<div class="tmsec" style="margin:0 0 6px">Versions${vs.length?' · '+vs.length:''}</div>`+
    (vs.map(v=>`<div style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:12px;border-bottom:1px solid var(--line)">
      <b style="flex:0 0 34px;color:${v===cur?'var(--ok)':'var(--dim)'}">v${v.version}</b>
      <span class="mut" style="flex:0 0 40px">${ago(v.created_at)}</span>
      <span style="flex:1;color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(v.note||'')}</span>
      ${v===cur?'<span style="font-size:10.5px;color:var(--ok)">live</span>'
        :`<button style="flex:0 0 auto;font-size:11px;padding:2px 10px" onclick="studioRestore(${v.version})">Restore</button>`}
    </div>`).join('')||'<p class="mut" style="font-size:12px">No versions yet — every build or edit creates one.</p>');
}
async function studioRestore(v){
  if(!await osConfirm('Restore v'+v+'?','The current version stays in history.',{confirmText:'Restore'}))return;
  await fetch('/api/apps/'+STUDIO.sel+'/versions/'+v+'/restore',{method:'POST'});
  toast('restored v'+v+' — deployed live');
  studioShowPreview();studioVersions();loadUserApps();
}
function studioLog(html,cls){
  if(!STUDIO.log)return;
  const d=document.createElement('div');d.className=cls||'';d.style.margin='4px 0';d.innerHTML=html;
  STUDIO.log.appendChild(d);
  if(STUDIO._status&&STUDIO._status.isConnected&&STUDIO._status!==d)STUDIO.log.appendChild(STUDIO._status); // status line stays last
  STUDIO.log.scrollTop=STUDIO.log.scrollHeight;
  return d;
}
function studioTickStart(){
  studioTickStop();
  STUDIO._t0=Date.now();
  STUDIO._status=studioLog('<span class="mut">working…</span>');
  STUDIO._tick=setInterval(()=>{
    if(!STUDIO._status||!STUDIO._status.isConnected){if(STUDIO._tick){clearInterval(STUDIO._tick);STUDIO._tick=null}return}
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
  studioLog(`<b style="color:var(--acc2)">You:</b> ${esc(prompt)}`);
  STUDIO._cur=studioLog('');
  studioTickStart();
  jarvisOn();
  const bmodel=$('#st-model')?.value||STUDIO.model||'auto';
  ws.send(JSON.stringify({type:'build',prompt,app_id:STUDIO.sel,model:bmodel}));
  p.value='';
}
function studioBuildEnded(){
  STUDIO.building=false;STUDIO._smsg='';studioTickStop();jarvisOff();
  const b=$('#st-build');if(b){b.disabled=false;b.classList.remove('stop');b.textContent=STUDIO.sel?'Update':'Build'}
}
function studioBuildEvent(ev){
  switch(ev.type){
    case 'build_start': break;
    case 'build_thinking': break;   // keep the log clean; thinking drives the jarvis pulse
    case 'build_text':
      if(STUDIO._cur){STUDIO._cur._t=(STUDIO._cur._t||'')+ev.text;STUDIO._cur.innerHTML='<b>▲ '+esc(agentName())+':</b> '+esc(STUDIO._cur._t)}
      break;
    case 'build_tool':
      studioLog(`<span class="mut">▸ ${esc(ev.name)}${ev.name==='create_app'?' — deploying the app…':ev.name==='fetch_url'?' — checking the live data source…':''}</span>`);break;
    case 'build_tool_end':{ // failed tool calls must be VISIBLE — a silent retry loop looks like a hang
      const ok=ev.ok!==false;
      if(!ok)studioLog(`<span style="color:var(--err)">✗ ${esc(ev.name)} — ${esc((ev.output||'').slice(0,220))}</span>`);
      else if(ev.name==='create_app')studioLog(`<span class="mut">✓ create_app</span>`);
      break;}
    case 'build_status': // model-side heartbeat while it loads/evaluates
      STUDIO._smsg=ev.message||'';break;
    case 'build_error_note': // non-fatal error inside an attempt (the build continues/retries)
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
        studioLog(`<span style="color:var(--ok)">✓ ${esc(ev.name||'app')} ready — deployed live</span>`);
        if(ev.warnings&&ev.warnings.length)
          studioLog(`<span style="color:var(--warn,#e8b04b)">⚠ shipped with known issues: ${esc(ev.warnings.join('; ').slice(0,300))} — ask for a fix or rebuild</span>`);
        if(ev.manifest_status==='proposed')
          studioLog(`<span class="mut">it requests permissions — </span><button style="font-size:11px;padding:3px 10px" onclick="reviewManifest('${ev.app_id}')">Review &amp; grant</button>`);
        if(wasNew)delete STUDIO.logs['new'];   // this session now belongs to the built app
        STUDIO._logKey=ev.app_id;
        studioVersions();
        // re-render to refresh the picker, then preview + open action
        const w=WM.wins.get('studio');if(w){renderStudio(w.el.querySelector('.wbody'),w);}
        toast(''+(ev.name||'app')+' built');
      } else studioLog('<span class="mut">no app was produced — try rephrasing</span>');
      break;
  }
}
async function studioDel(id){
  if(!await osConfirm('Delete this app?','',{danger:true,confirmText:'Delete'}))return;
  await fetch('/api/apps/'+(id||STUDIO.sel),{method:'DELETE'});
  STUDIO.sel='';refreshApp('studio');
}

