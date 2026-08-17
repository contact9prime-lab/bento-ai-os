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
      return {app:'fabric',label:'Open in Workflows',what:nm||'the flow',
              note:'drafted and switched OFF — Enable is what grants it anything'};
    case 'enable_flow':
      return {app:'fabric',label:'Open in Workflows',what:nm||'the flow',
              note:args.enabled===false?'switched off':'switched on'};
    case 'save_automation':
      return {app:'automations',label:'Open in Automations',what:nm||'the routine',note:''};
    case 'schedule_task':
      return {app:'tasks',label:'Open in Scheduler',
              what:String(args.prompt||'the task').slice(0,60),note:'it runs on its own from now on'};
    default:
      return null;
  }
}
/* Opening it means SHOWING the thing, not the app that contains it. A button
   that lands you in App Studio with nothing selected is a redirection, not a
   handoff. */
function handoffOpen(h){
  if(h.app==='studio'){
    const hit=(typeof USERAPPS!=='undefined'?USERAPPS:[]).find(a=>a.name===h.what);
    if(hit&&typeof STUDIO!=='undefined')STUDIO.sel=hit.id;
    openApp('studio');refreshApp('studio');return;
  }
  if(h.app==='fabric'){
    if(typeof FLOW_FOCUS!=='undefined')FLOW_FOCUS=h.what;
    if(typeof fabTab!=='undefined')fabTab='flows';
    openApp('fabric');refreshApp('fabric');return;
  }
  openApp(h.app);refreshApp(h.app);
}
function handoffChip(h){
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
