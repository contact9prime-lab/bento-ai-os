/* ================= scheduler app ================= */
async function renderTasks(body){
  const r=await fetch('/api/tasks');const d=await r.json();
  /* Each schedule says what it did (runlog.schedules): how many runs this week, how the
     last one went, and Runs opens Missions → History on just this schedule. A mission's
     schedule is named by its mission, not the prompt it carries. */
  const st={ok:'done',failed:'failed',skipped:'skipped',running:'running',stopped:'stopped',waiting:'waiting for you',partial:'partly done'};
  const items=d.tasks.map(t=>{
    const last=t.last_status?`last run ${st[t.last_status]||t.last_status}${t.last_at?' '+jobAgo(t.last_at):''}`:'has not run yet';
    return `<div class="item task-row" data-f="${esc(t.title||t.prompt)}"><div class="grow">
      ${t.flow?`<span class="job-hkind">mission</span> `:''}${esc(t.title||t.prompt)}
      ${t.app_name?`<div class="sub task-app">for <b>${esc(t.app_name)}</b> <button class="endbtn" onclick="taskOpenApp('${esc(t.app_id)}')">Open app</button></div>`
        :t.app_gone?'<div class="sub">for an app that was deleted</div>':''}
      <div class="sub">${esc(t.words||'')} · ${t.enabled?(t.next_run?'next: '+new Date(t.next_run*1000).toLocaleString():'waiting for its event'):'switched off'}</div>
      <div class="sub"><span class="task-last ${esc(t.last_status||'')}">${esc(last)}</span>${t.runs_7d?` · ${t.runs_7d} run${t.runs_7d===1?'':'s'} this week`:''}${t.failed_7d?` · <b class="job-bad">${t.failed_7d} failed</b>`:''}</div>
      ${t.last_said?`<div class="sub job-hsaid">${esc(t.last_said)}</div>`:''}</div>
    <button class="endbtn" onclick="jobHistoryFor({task_id:'${esc(t.id)}'})">Runs</button>
    <button title="${t.enabled?'Pause':'Resume'}" aria-label="${t.enabled?'Pause':'Resume'}" onclick="toggleTask('${t.id}',${t.enabled?0:1})">${t.enabled?'⏸':'▶'}</button>
    <button title="Delete" aria-label="Delete" onclick="delTask('${t.id}')">✕</button></div>`}).join('');
  const pb=panelShell(body,{
    title:'Schedule',
    sub:`${d.tasks.length} task${d.tasks.length===1?'':'s'} · ${d.tasks.filter(t=>t.enabled).length} active`,
    search:{id:'task-q',placeholder:'Search tasks…'},
  });
  pb.innerHTML=`
    ${items||emptyBox('Nothing scheduled yet','Schedule any prompt to run on its own — "check disk space every hour and notify me", "every morning summarize my unread mail". Add one below or just ask in chat.','','tasks','Set up a useful daily schedule for me.')}
    <div class="sect">New scheduled task</div>
    <input id="task-prompt" placeholder="What should the agent do when this fires?">
    <div class="row" style="margin-top:8px">
      <select id="task-type" style="flex:0 0 190px" onchange="taskTypeHint()">
        <option value="interval">every N minutes</option><option value="daily">daily at a time</option><option value="once">once, after N minutes</option></select>
      <input id="task-when" placeholder="minutes — e.g. 60">
      <button class="pact" style="flex:0 0 90px" onclick="addTask()">Add</button>
    </div>
    <p class="mut" style="margin-top:10px">Background tasks take risky actions only when autonomy is <b>Full</b>; otherwise they stay read-only.</p>`;
}
/* A schedule set up for an app (tasks.app_id) opens that app in App Studio, where
   the same schedule is listed under it. */
function taskOpenApp(id){
  if(typeof STUDIO!=='undefined')STUDIO.sel=id;
  openApp('studio');refreshApp('studio');
}
function taskTypeHint(){
  const t=$('#task-type').value,w=$('#task-when');if(!w)return;
  w.placeholder=t==='daily'?'time — e.g. 09:00':t==='once'?'minutes from now — e.g. 15':'minutes — e.g. 60';
}
async function addTask(){
  const type=$('#task-type').value,when=$('#task-when').value.trim(),prompt=$('#task-prompt').value.trim();
  if(!prompt)return;
  const body={prompt,schedule_type:type};
  if(type==='interval')body.interval_minutes=+when||60;
  if(type==='daily')body.at_time=when||'09:00';
  if(type==='once')body.delay_minutes=+when||0;
  await fetch('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});refreshApp('tasks');}
async function toggleTask(id,en){await fetch('/api/tasks/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:!!en})});refreshApp('tasks');}
async function delTask(id){await fetch('/api/tasks/'+id,{method:'DELETE'});refreshApp('tasks');}

/* ================= task manager app ================= */
function renderTaskMgr(body,w){
  body.innerHTML=`<div class="pad">
    <div class="tmgrid">
      <div class="stat"><div class="lbl">CPU</div><div class="val" id="tm-cpu">–</div><div class="bar"><i id="tm-cpub"></i></div></div>
      <div class="stat"><div class="lbl">Memory</div><div class="val" id="tm-mem">–</div><div class="bar"><i id="tm-memb"></i></div></div>
      <div class="stat"><div class="lbl">Disk (home)</div><div class="val" id="tm-dsk">–</div><div class="bar"><i id="tm-dskb"></i></div></div>
    </div>
    <div class="mut" id="tm-meta">loading…</div>
    <div class="tmsec">Agent</div><div id="tm-agent"></div>
    <div class="tmsec">Windows</div><div id="tm-wins"></div>
    <div class="tmsec">Top processes</div>
    <table class="plist"><thead><tr><th>PID</th><th>Name</th><th class="r">CPU %</th><th class="r">Mem %</th></tr></thead><tbody id="tm-procs"></tbody></table>
  </div>`;
  const poll=async()=>{
    if(!document.getElementById('tm-cpu'))return;
    try{
      const r=await fetch('/api/system');const d=await r.json();
      if(!document.getElementById('tm-cpu'))return;
      const memPct=d.mem.total_kb?100*d.mem.used_kb/d.mem.total_kb:0;
      const dskPct=d.disk.total?100*d.disk.used/d.disk.total:0;
      $('#tm-cpu').textContent=d.cpu.toFixed(0)+'%';
      $('#tm-mem').innerHTML=memPct.toFixed(0)+'% <small>'+fmtBytes(d.mem.used_kb*1024)+' / '+fmtBytes(d.mem.total_kb*1024)+'</small>';
      $('#tm-dsk').innerHTML=dskPct.toFixed(0)+'% <small>'+fmtBytes(d.disk.used)+' / '+fmtBytes(d.disk.total)+'</small>';
      const set=(id,p)=>{const b=$(id);b.style.width=Math.min(p,100)+'%';b.classList.toggle('hot',p>85)};
      set('#tm-cpub',d.cpu);set('#tm-memb',memPct);set('#tm-dskb',dskPct);
      const up=d.uptime,dd=Math.floor(up/86400),hh=Math.floor(up%86400/3600),mm=Math.floor(up%3600/60);
      $('#tm-meta').textContent=`${d.cores} cores · load ${d.load.map(x=>x.toFixed(2)).join(' ')} · up ${dd?dd+'d ':''}${hh}h ${mm}m`;
      $('#tm-procs').innerHTML=d.procs.map(p=>`<tr><td>${p.pid}</td><td class="n">${esc(p.name)}</td><td class="r">${p.cpu.toFixed(1)}</td><td class="r">${p.mem.toFixed(1)}</td></tr>`).join('');
    }catch(e){}
    const ag=$('#tm-agent');
    if(ag)ag.innerHTML=running
      ?`<div class="item"><div class="grow">agent turn in progress<div class="sub">the model is working in Agent Chat</div></div><button class="endbtn" onclick="ws&&ws.send(JSON.stringify({type:'abort'}))">End turn</button></div>`
      :'<p class="mut">idle — no turn running</p>';
    const wl=$('#tm-wins');
    if(wl){wl.innerHTML='';
      WM.wins.forEach(o=>{
        const row=document.createElement('div');row.className='item';
        // "sleeping" is worth saying out loud: it is why a background app's numbers
        // are not moving, and it is the reason ten open apps still feel like one.
        const state=o.min?'minimized':o.max?'maximized':'windowed';
        row.innerHTML=`${appIcon(o.id,26)}<div class="grow">${esc(o.app.title)}<div class="sub">${state}${
          o._awake===false?' · <b>sleeping</b> — no background work':''}</div></div>`;
        const b=document.createElement('button');b.className='endbtn';b.textContent='End task';
        b.onclick=()=>{closeWin(o)};
        row.appendChild(b);wl.appendChild(row);
      });
      if(!WM.wins.size)wl.innerHTML='<p class="mut">no open windows</p>';
    }
  };
  stopWinTicks(w);
  winTick(w,poll,2000,{key:'poll'});   // stops when the window is minimised or on another desktop
}

