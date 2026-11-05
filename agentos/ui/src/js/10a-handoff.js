/* ================= handoffs: the chat is where things get MADE =================
   Asking for an app in chat already built one, and asking for a workflow already
   wrote one — but the thing then existed somewhere you had to know to go and
   look. So the OS's three creative surfaces sat next to each other unconnected:
   the prompt bar hands its question to the chat, the chat builds an app or a
   flow, and nothing on screen joined them up.

   This is that seam, and it is derived from the stream rather than announced by
   the server: `tool_end` says a tool finished, and if that tool was one that
   CREATES something, the surface offers the door to it. One place, so every
   surface with a live feed — the Chat window, the omnibar card, a copilot panel
   — gets the same button for free.

   `tool_end` carries no arguments (see agent.py), so the names are remembered
   from `tool_start` and consumed here. */

var TOOL_ARGS={};        // call_id -> args, from tool_start
var HANDOFF_SEEN={};     // conversation_id -> last handoff key, so a retry is not two chips

/* A tool call that never ends — the turn was stopped, the socket dropped, the
   server restarted — leaves its arguments behind. One entry is nothing; a
   desktop left open for a week is not, and this page is the long-lived process
   on a machine that may have 1 GB of RAM. The oldest are dropped: the map only
   exists to carry args from tool_start to the tool_end a moment later. */
function toolArgsRemember(id,args){
  TOOL_ARGS[id]=args||{};
  const keys=Object.keys(TOOL_ARGS);
  if(keys.length>200)keys.slice(0,keys.length-200).forEach(k=>{delete TOOL_ARGS[k]});
}

/* Which tools make something, and where that something lives. A tool NOT in
   here is deliberately not a handoff: `read_file` produced no artefact, and a
   button offering to "open" one would be an invention. */
function handoffFor(name,args){
  args=args||{};
  const nm=String(args.name||'').trim();
  switch(name){
    case 'create_app':
      return {app:'studio',label:'Open in App Studio',
              what:nm||'the app',note:'built here — edit, rebuild or publish it there'};
    case 'export_app_to_git':
      return {app:'studio',label:'Open in App Studio',what:nm||'the app',note:'exported'};
    case 'create_flow':
      return {app:'fabric',label:'Open in Missions',what:nm||'the flow',
              note:'drafted and switched OFF — Enable is what grants it anything'};
    case 'enable_flow':
      return {app:'fabric',label:'Open in Missions',what:nm||'the flow',
              note:args.enabled===false?'switched off':'switched on'};
    case 'save_automation':
      return {app:'automations',label:'Open in Missions',what:nm||'the routine',note:'under Routines'};
    case 'create_subagent':
      // a specialist built for this job: a temporary one is offered to keep, and goes in a
      // day otherwise; a lasting one is a door to where agents are edited
      return args.temporary?{kind:'temp',what:nm||'a new agent',
        note:'built for this job'+((args.tools||[]).length?' · can use '+args.tools.slice(0,4).join(', '):'')+'. Keep it?'}
        :{app:'settings',place:'agent',label:'Open in Agents',what:nm||'the agent',
          note:'a new specialist; it asks you the first time it is given work'};
    case 'schedule_task':
      return {app:'tasks',label:'Open in Missions',
              what:String(args.prompt||'the task').slice(0,60),
              note:args.app?'for '+String(args.app).slice(0,40)+', it runs on its own from now on'
                :'it runs on its own from now on'};
    default:
      return null;
  }
}
/* Opening it means SHOWING the thing, not the app that contains it. A button
   that lands you in App Studio with nothing selected is a redirection, not a
   handoff. */
/* Keep or remove an agent built for one job. Text only: the name is the model's words. */
function handoffTempChip(h){
  const el=document.createElement('div');el.className='handoff';
  const w=document.createElement('span');w.className='ho-what';w.textContent=h.what;
  const n=document.createElement('span');n.className='ho-note';n.textContent=h.note;
  const keep=document.createElement('button');keep.className='ho-go';keep.textContent='Keep';
  const drop=document.createElement('button');drop.className='ho-go';drop.textContent='Remove';
  const act=async on=>{keep.disabled=drop.disabled=true;
    try{const r=await fetch('/api/agents/'+encodeURIComponent(h.what)+'/keep',{method:'POST',
        headers:{'Content-Type':'application/json'},body:JSON.stringify({keep:on})});
      const d=await r.json();if(!r.ok)throw new Error(d.error||r.status);
      n.textContent=on?'kept: it is one of your specialists now':'removed';keep.remove();drop.remove();
    }catch(e){toast('could not: '+(e.message||e));keep.disabled=drop.disabled=false}};
  keep.onclick=()=>act(true);drop.onclick=()=>act(false);
  el.append(w,n,keep,drop);return el;
}
async function handoffOpen(h){
  if(h.app==='studio'){
    const find=()=>(typeof USERAPPS!=='undefined'?USERAPPS:[]).find(a=>a.name===h.what);
    // the chip can be tapped before the `apps` broadcast has reloaded the list
    let hit=find();
    if(!hit&&typeof loadUserApps==='function'){try{await loadUserApps()}catch(e){}hit=find()}
    if(hit&&typeof STUDIO!=='undefined')STUDIO.sel=hit.id;
    openApp('studio');refreshApp('studio');return;
  }
  if(h.app==='fabric'){
    if(typeof FLOW_FOCUS!=='undefined')FLOW_FOCUS=h.what;
    if(typeof fabTab!=='undefined')fabTab='flows';
    openApp('fabric');refreshApp('fabric');return;
  }
  if(h.place&&typeof placeSettings==='function'){placeSettings(h.place)();return}
  openApp(h.app);refreshApp(h.app);
}
function handoffChip(h){
  if(h.kind==='temp')return handoffTempChip(h);
  const el=document.createElement('div');
  el.className='handoff';
  el.innerHTML=`<span class="ho-what"></span><span class="ho-note"></span>`
    +`<button class="ho-go"></button>`;
  el.querySelector('.ho-what').textContent=h.what;
  el.querySelector('.ho-note').textContent=h.note||'';
  const b=el.querySelector('.ho-go');
  b.textContent=h.label;
  b.onclick=()=>handoffOpen(h);
  return el;
}
/* The same door for an app an agent CLI wrote (the `app_saved` event): there was no
   create_app call to hang it on. */
function handoffApp(ev,cid,sink,inChat){
  const h={app:'studio',label:'Open in App Studio',what:ev.name||'the app',
    note:ev.new?'built here — its build is in App Studio with this chat':'saved as a new version'};
  const key=h.app+':'+h.what;
  if(HANDOFF_SEEN[cid||'']===key)return;
  HANDOFF_SEEN[cid||'']=key;
  if(sink&&sink.handoff)sink.handoff(h);
  if(inChat&&typeof feed!=='undefined'&&feed&&typeof curBody!=='undefined'&&curBody)
    curBody.parentNode.insertBefore(handoffChip(h),curBody);
}
/* Called from the tool_end handler for every surface. `cid` dedupes: a flow that
   is written and then enabled in the same turn is one thing, and two chips for
   it read as two flows. */
function handoffEmit(ev,cid,sink,inChat){
  if(!ev.ok)return;
  const h=handoffFor(ev.name,TOOL_ARGS[ev.call_id]);
  delete TOOL_ARGS[ev.call_id];
  if(!h)return;
  const key=h.app+':'+h.what;
  if(HANDOFF_SEEN[cid||'']===key)return;
  HANDOFF_SEEN[cid||'']=key;
  if(sink&&sink.handoff)sink.handoff(h);
  if(inChat&&typeof feed!=='undefined'&&feed&&typeof curBody!=='undefined'&&curBody)
    curBody.parentNode.insertBefore(handoffChip(h),curBody);
}

/* A department's work, followed in the chat that asked for it. Reported as "the other
   department, what it is acting on is not known": the department_task card said
   "running" for six minutes and nothing else. The desk's run says which chat asked
   (flow_start carries conversation_id and department, fabric.department_task); from then
   on its runs write into that card: who got which piece, what tool they are on, who
   finished. Every card on the page for that call follows, wherever the chat is drawn. */
var DEPTCARD={runs:{}};
function deptCardFind(ev){
  const want=String(ev.department||'').toLowerCase();
  return [...document.querySelectorAll('.tool')].filter(c=>{
    const n=c.querySelector('.tname2'),st=c.querySelector('.tstat');
    return n&&n.textContent==='department_task'&&st&&st.classList.contains('run')&&!c.dataset.deptRun
      &&(!want||String(c.querySelector('.targ')&&c.querySelector('.targ').textContent||'').toLowerCase().includes(want))});
}
function deptCardLine(run,text){
  const d=DEPTCARD.runs[run];if(!d)return;
  d.lines.push(text);if(d.lines.length>40)d.lines.shift();
  document.querySelectorAll(`.tool[data-dept-run="${CSS.escape(d.top)}"]`).forEach(c=>{
    const out=c.querySelector('.out');if(out){out.textContent=d.lines.join('\n');c.classList.add('open')}
    const st=c.querySelector('.tstat');if(st)st.title=text});
}
function deptCardLive(ev){
  const e=ev.event,run=ev.run_id;if(!run)return;
  if(e==='flow_start'&&ev.department&&ev.conversation_id){
    const cards=deptCardFind(ev);if(!cards.length)return;
    DEPTCARD.runs[run]={top:run,lines:[]};
    cards.forEach(c=>c.dataset.deptRun=run);
    deptCardLine(run,`${ev.department} has it${ev.head?`, led by ${ev.head}`:''}`);return}
  // a child run of a followed desk is followed too
  if(e==='status'&&ev.parent_run&&DEPTCARD.runs[ev.parent_run]&&!DEPTCARD.runs[run])
    DEPTCARD.runs[run]={...DEPTCARD.runs[ev.parent_run],who:ev.ref};
  const d=DEPTCARD.runs[run];if(!d)return;
  if(e==='node_add')deptCardLine(run,`→ ${ev.agent}: ${String(ev.task||'').replace(/\s+/g,' ').slice(0,160)}`);
  else if(e==='status'&&ev.ref&&ev.kind!=='review')deptCardLine(run,ev.status==='running'?`${ev.ref} is working`
    :`${ev.ref} ${ev.status==='ok'||ev.status==='done'?'finished':'stopped ('+ev.status+')'}`);
  else if(e==='step'&&ev.status==='start')deptCardLine(run,`  ${d.who||'the desk'} · ${ev.tool}${ev.detail?' · '+String(ev.detail).slice(0,80):''}`);
  else if(e==='review'&&ev.phase==='start')deptCardLine(run,`${ev.reviewer||'a boss'} is checking it`);
  else if(e==='review'&&ev.phase&&ev.phase!=='start')deptCardLine(run,`${ev.reviewer||'a boss'}: ${ev.verdict||ev.phase}`);
  else if(e==='flow_end'){deptCardLine(run,`${ev.status==='ok'||!ev.status?'done':ev.status}`);delete DEPTCARD.runs[run]}
}
