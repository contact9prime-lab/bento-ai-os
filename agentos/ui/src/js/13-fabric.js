/* ================= fabric app — subagents, flows, workflows, observability =================
   `var`, not `let`: the bundle is one concatenated script in filename order, and a
   top-level `let` here is in the temporal dead zone for anything earlier that reaches
   it (09-websocket.js calls fgApply on every fabric event). */
/* Three tabs, not five. "Executions" and "Observability" were both answering "what
   happened" from two different endpoints, and the legacy static-DAG tab had never been used
   on any machine we could see — its engine, tool and API still work, it just no longer costs
   a tab. The app is called Workflows because that is the word people arrive with; the code
   underneath says `flows` throughout, which is written down in CLAUDE.md. */
var fabTab='flows';
var FAB_TABS=['flows','agents','runs'];
async function renderFabric(body,w){
  if(fabTab==='agents')return renderFabAgents(body);
  if(fabTab==='runs')return renderFabRuns(body);
  return renderFabFlows(body,w);
}
function fabTabs(){
  return `<div style="margin-bottom:12px">${segTabs('fab-tabs',['Flows','Agents','Runs'],
    Math.max(0,FAB_TABS.indexOf(fabTab)),'fabSetTab')}</div>`;
}
function fabSetTab(i){fabTab=FAB_TABS[i]||'flows';refreshApp('fabric')}
async function renderFabAgents(body){
  const sa=await fetch('/api/subagents').then(r=>r.json());
  window.__subagents=Object.fromEntries(sa.subagents.map(s=>[s.name,s]));
  const cards=sa.subagents.map(s=>`<div class="teamcard" onclick="openSAW('${esc(s.name)}')">
      <div class="tile">${esc((s.name||'?')[0].toUpperCase())}</div>
      <div class="grow">
        <div class="n">${esc(s.name)}${s.builtin?'<span class="badge">built-in</span>':''}</div>
        <div class="meta"><b>${esc((s.model||'').split('/').pop()||'inherits OS model')}</b> · ${s.tools.length?s.tools.length+' tools':'safe read-only set'}${(s.skills||[]).length?' · '+s.skills.length+' skills':''} · autonomy ≤ ${esc(s.autonomy_cap)} · ${s.max_steps} steps / ${s.max_seconds}s</div>
        <div class="persona">${esc((s.soul||'').slice(0,120))}</div>
      </div>
      <button title="try it in chat: @${esc(s.name)}" onclick="event.stopPropagation();testSubagent('${esc(s.name)}')">Test in chat</button>
      ${(typeof USERS!=='undefined'&&(USERS.me||{}).multiuser)?`<button title="share a copy with everybody on this machine" onclick="event.stopPropagation();usersShare('agent','${esc(s.name)}')">Share</button>`:''}
      <button title="delete" onclick="event.stopPropagation();delSubagent('${s.id}')">✕</button></div>`).join('')
    ||'<p class="mut">No subagents yet — create your first specialist.</p>';
  body.innerHTML=`<div class="pad">${fabTabs()}
    <button class="save" style="margin:0 0 12px" onclick="openSAW()">＋ New subagent</button>
    ${cards}
    <p class="mut" style="margin-top:10px">Address any of them directly from Agent Chat (or Telegram / TUI) with
    <code>@name your task</code> — the run streams into the chat and is tracked in Observability.
    Click a card to edit. <i>inherit</i> follows the OS model; pin one to mix (e.g. generation local, validation on Claude).</p></div>`;
}
async function delSubagent(id){if(!await osConfirm('Delete this subagent?','',{danger:true,confirmText:'Delete'}))return;await fetch('/api/subagents/'+id,{method:'DELETE'});refreshApp('fabric');}

/* --- subagent wizard: pick from what exists (tools, skills, models), don't type it --- */
var SAW=null;   // `var`: the flow editor borrows this wizard, so it is reached from more
                // than one place in the bundle (see the header note on the TDZ)
const SAW_PRESETS={
  'Read-only':['fetch_url','read_file','list_dir','recall','kg_query','system_info'],
  'Research':['fetch_url','read_file','list_dir','recall','kg_query','save_report'],
  'Files & shell':['run_command','read_file','write_file','list_dir','system_info'],
  'Builder':['create_app','read_file','list_dir','fetch_url','system_info'],
};
async function openSAW(name,opts){
  const [tools,skills,models]=await Promise.all([
    fetch('/api/tools').then(r=>r.json()).catch(()=>({tools:[]})),
    fetch('/api/skills').then(r=>r.json()).catch(()=>({skills:[]})),
    fetch('/api/models').then(r=>r.json()).catch(()=>({models:[]}))]);
  const ex=name?(window.__subagents||{})[name]:null;
  // onSaved/onCancel let another editor borrow this wizard: creating the specialist and
  // the flow that needs it is one thought, and making someone leave, create three
  // subagents and come back to re-pick them is how a good idea becomes a chore.
  SAW={step:1,exists:!!ex,tools:tools.tools||[],skills:skills.skills||[],models:models.models||[],q:'',
    onSaved:(opts||{}).onSaved||null,onCancel:(opts||{}).onCancel||null,
    d:ex?{...ex,tools:[...(ex.tools||[])],skills:[...(ex.skills||[])]}
        :{name:(opts||{}).name||'',soul:(opts||{}).soul||'',model:'',
          tools:[...((opts||{}).tools||[])],skills:[],autonomy_cap:'balanced',
          max_steps:12,max_seconds:300,builtin:0,target:'local'}};
  drawSAW();
}
function sawClose(){const cb=SAW&&SAW.onCancel;SAW=null;drawSAW();if(cb)cb()}
/* Draft a specialist, or revise the one on screen. Same call either way — "make it also
   read files" and "make me one that reads files" are one question from two starting points. */
async function sawAi(){
  const ask=$('#sw-ai'),st=$('#sw-ai-status');
  const req=(ask&&ask.value||'').trim();
  if(!req)return toast('say what it should do');
  sawCollect();
  SAW.ask=req;
  if(st)st.innerHTML='thinking…';
  let r;
  try{
    r=await apiJSON('/api/subagents/compose',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({request:req,name:SAW.exists?SAW.d.name:''})});
  }catch(e){if(st)st.innerHTML='<span style="color:var(--err,#f87171)">'+esc(e.message||String(e))+'</span>';return}
  const dr=r.draft||{};
  const was={tools:[...(SAW.d.tools||[])],soul:SAW.d.soul||''};
  SAW.d=Object.assign(SAW.d,{
    name:SAW.exists?SAW.d.name:(dr.name||SAW.d.name),
    soul:dr.soul||SAW.d.soul,tools:dr.tools||[],skills:dr.skills||[],
    autonomy_cap:dr.autonomy_cap||SAW.d.autonomy_cap,
    max_steps:dr.max_steps||SAW.d.max_steps,max_seconds:dr.max_seconds||SAW.d.max_seconds});
  drawSAW();
  const s2=$('#sw-ai-status');
  const added=(SAW.d.tools||[]).filter(t=>!was.tools.includes(t));
  const gone=was.tools.filter(t=>!(SAW.d.tools||[]).includes(t));
  if(s2)s2.innerHTML=esc(
    (was.soul!==(SAW.d.soul||'')?'persona rewritten. ':'')
    +(added.length?'+'+added.join(', ')+' ':'')+(gone.length?'−'+gone.join(', ')+' ':'')
    +((dr.warnings||[]).join(' · ')))
    +' <span class="mut">not saved yet</span>';
}
function drawSAW(){
  let ov=$('#saw-ov');
  if(!SAW){ov&&ov.remove();return}
  if(!ov){ov=document.createElement('div');ov.id='saw-ov';ov.style.cssText='position:fixed;inset:0;z-index:9998;background:rgba(5,7,9,.75);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center';
    ov.onclick=e=>{if(e.target===ov)sawClose()};document.body.appendChild(ov);}
  const d=SAW.d,st=SAW.step;
  const dot=n=>`<span style="width:8px;height:8px;border-radius:50%;display:inline-block;margin:0 3px;background:${n<=st?'var(--acc,#5eead4)':'var(--line,#333)'}"></span>`;
  let inner='';
  if(st===1){
    const opts=['<option value="">inherit from control plane (OS default)</option>']
      .concat(SAW.models.map(m=>`<option value="${m.id}" ${d.model===m.id?'selected':''}>${esc(m.id)}</option>`)).join('');
    inner=`<div class="sawh">${SAW.exists?'Edit':'New'} subagent</div>
      <div class="sawsub">A specialist team member with its own persona, model, and tools. In chat you'll address it as <code>@name</code>.</div>
      <div class="provbox" style="margin-bottom:10px">
        <div class="sub" style="margin-bottom:4px">${SAW.exists
          ?'Ask for a change and it rewrites the persona and tools below — nothing is saved until you press Save.'
          :'Describe what you need and it fills the whole thing in.'}</div>
        <textarea id="sw-ai" rows="2" placeholder="${SAW.exists
          ?'let it read files too · make it stricter about sources'
          :'someone who watches my disk space and tells me when it is filling up'}">${esc(SAW.ask||'')}</textarea>
        <div class="row" style="margin-top:6px"><button class="save" style="margin:0;flex:0 0 120px"
            onclick="sawAi()">✦ ${SAW.exists?'Apply':'Draft it'}</button>
          <div class="grow"><span id="sw-ai-status" class="sub"></span></div></div>
      </div>
      <label>Name</label><input id="sw-name" value="${esc(d.name)}" placeholder="e.g. researcher" ${SAW.exists?'disabled':''} style="font-size:14px">
      <label>Persona — who is it, how does it work?</label>
      <textarea id="sw-soul" rows="4" style="font-size:13px;line-height:1.5" placeholder="You research. Gather real information, verify it, return a dense sourced summary.">${esc(d.soul||'')}</textarea>
      <label>Brain</label><select id="sw-model" style="font-size:13px">${opts}</select>
      <p class="mut" style="font-size:12px">Pin a model to mix smartness across the team — e.g. this one on Claude while others run local.</p>`;
  }else if(st===2){
    const chips=Object.keys(SAW_PRESETS).map(p=>`<button class="sawchip" onclick="sawPreset('${p}')">${p}</button>`).join('')
      +`<button class="sawchip" onclick="SAW.d.tools=[];sawRefreshList()">Clear all</button>`;
    const skl=SAW.skills.map(s=>`<label class="sawrow ${d.skills.includes(s.name)?'on':''}"><input type="checkbox" ${d.skills.includes(s.name)?'checked':''} onchange="sawSkill('${esc(s.name)}',this.checked);this.closest('.sawrow').classList.toggle('on',this.checked)">
        <div class="grow"><div class="n">${esc(s.name)}</div><div class="d">${esc((s.description||'').slice(0,110))}</div></div></label>`).join('')
      ||'<p class="mut">No skills installed yet — add some in the Skills app.</p>';
    inner=`<div class="sawh">Capabilities</div>
      <div class="sawsub">Pick from what's already on this OS — tools, connected MCP servers, installed skills. Nothing to type.</div>
      <div class="row" style="margin:0 0 8px;flex-wrap:wrap;gap:6px">${chips}</div>
      <input id="sw-q" placeholder="Search ${SAW.tools.length} tools by name or what they do…" value="${esc(SAW.q)}" style="font-size:13.5px;padding:10px 12px">
      <div id="sw-list" style="max-height:230px;overflow:auto;margin:8px 0 2px"></div>
      <div id="sw-count" class="sawsub" style="margin:6px 0 10px"></div>
      <div class="sawgrp">Skills it should follow</div>
      <div style="max-height:150px;overflow:auto">${skl}</div>
      <p class="mut" style="margin-top:8px;font-size:12px">Memory and skills access (<code>use_skill</code>, <code>recall</code>, <code>kg_query</code>, <code>remember</code>) is always included.</p>`;
  }else{
    inner=`<div class="sawh">Limits &amp; trust</div>
      <div class="sawsub">How independent is it, and how much may one run cost?</div>
      <label>Autonomy cap (never exceeds the OS level)</label>
      <select id="sw-cap" style="font-size:13px"><option value="paranoid" ${d.autonomy_cap==='paranoid'?'selected':''}>paranoid — everything needs approval</option>
        <option value="balanced" ${d.autonomy_cap==='balanced'?'selected':''}>balanced — risky actions auto-denied when unattended</option>
        <option value="full" ${d.autonomy_cap==='full'?'selected':''}>full — may act freely (careful)</option></select>
      <div class="row" style="margin-top:8px">
        <div style="flex:1"><label>Max steps</label><input id="sw-steps" type="number" value="${d.max_steps}"></div>
        <div style="flex:1"><label>Max seconds</label><input id="sw-secs" type="number" value="${d.max_seconds}"></div>
      </div>
      <div class="provbox" style="margin-top:14px"><div class="sawgrp" style="margin-top:0">Summary</div>
        <div class="meta" style="font-size:12.5px;color:var(--dim)"><b style="color:var(--txt)">${esc(d.name||'?')}</b> · ${esc(d.model||'inherits OS model')} · ${d.tools.length||'safe set'} tools${d.skills.length?' · '+d.skills.length+' skills':''} · ≤ ${esc(d.autonomy_cap)}</div>
        <div class="persona" style="font-size:12px;color:var(--dim2);font-style:italic;margin-top:4px">${esc((d.soul||'').slice(0,160))}</div>
        <div class="meta" style="font-size:12px;color:var(--dim2);margin-top:6px">In chat: <code>@${esc(d.name||'name')} your task</code></div></div>`;
  }
  ov.innerHTML=`<div style="width:620px;max-width:94vw;max-height:88vh;overflow:auto;background:var(--bg2,#111419);border:1px solid var(--line,#232a35);border-radius:16px;padding:24px 26px" onclick="event.stopPropagation()">
    ${inner}
    <div class="row" style="margin-top:16px;align-items:center">
      <div class="grow">${dot(1)}${dot(2)}${dot(3)}</div>
      <button onclick="sawClose()">Cancel</button>
      ${st>1?`<button onclick="sawStep(-1)">← Back</button>`:''}
      ${st<3?`<button class="save" style="margin:0;flex:0 0 100px" onclick="sawStep(1)">Next →</button>`
            :`<button class="save" style="margin:0;flex:0 0 130px" onclick="sawSave()">Save</button>`}
    </div></div>`;
  if(st===2){ // search filters the list in place — the field never loses focus
    const q=$('#sw-q');
    q.oninput=()=>{SAW.q=q.value;sawRefreshList()};
    sawRefreshList();
  }
}
function sawRefreshList(){
  const box=$('#sw-list'),d=SAW.d,q=SAW.q.toLowerCase().trim();
  if(!box)return;
  const hit=t=>!q||t.name.toLowerCase().includes(q)||(t.description||'').toLowerCase().includes(q);
  // group: OS tools first, then one group per connected MCP server (mcp_<server>_<tool>)
  const groups={};
  SAW.tools.filter(hit).forEach(t=>{
    const g=t.name.startsWith('mcp_')?('MCP · '+(t.name.split('_')[1]||'server')):'OS tools';
    (groups[g]=groups[g]||[]).push(t);
  });
  const row=t=>{const on=d.tools.includes(t.name);
    return `<label class="sawrow ${on?'on':''}"><input type="checkbox" ${on?'checked':''}
      onchange="sawTool('${esc(t.name)}',this.checked);this.closest('.sawrow').classList.toggle('on',this.checked)">
      <div class="grow"><div class="n">${esc(t.name)}</div><div class="d">${esc((t.description||'').slice(0,130))}</div></div></label>`};
  box.innerHTML=Object.entries(groups).map(([g,ts])=>
    `<div class="sawgrp">${esc(g)} · ${ts.length}</div>`+ts.slice(0,80).map(row).join('')).join('')
    ||'<p class="mut" style="padding:8px 2px">Nothing matches — try a different word (search also looks at descriptions).</p>';
  const c=$('#sw-count');
  if(c)c.innerHTML=d.tools.length
    ?`Selected <b style="color:var(--txt)">${d.tools.length}</b>: ${d.tools.slice(0,10).map(esc).join(', ')}${d.tools.length>10?' …':''}`
    :'Nothing selected — it gets the safe read-only set.';
}
function sawCollect(){
  const d=SAW.d;
  if(SAW.step===1){if($('#sw-name'))d.name=$('#sw-name').value.trim();d.soul=$('#sw-soul').value;d.model=$('#sw-model').value;}
  if(SAW.step===3){d.autonomy_cap=$('#sw-cap').value;d.max_steps=+$('#sw-steps').value||12;d.max_seconds=+$('#sw-secs').value||300;}
}
function sawStep(delta){sawCollect();if(SAW.step===1&&delta>0&&!SAW.d.name)return toast('give it a name');SAW.step=Math.min(3,Math.max(1,SAW.step+delta));drawSAW()}
function sawTool(name,on){const t=SAW.d.tools;if(on&&!t.includes(name))t.push(name);if(!on)SAW.d.tools=t.filter(x=>x!==name);
  const c=$('#sw-count');if(c)sawRefreshCount();}
function sawRefreshCount(){const d=SAW.d,c=$('#sw-count');
  if(c)c.innerHTML=d.tools.length
    ?`Selected <b style="color:var(--txt)">${d.tools.length}</b>: ${d.tools.slice(0,10).map(esc).join(', ')}${d.tools.length>10?' …':''}`
    :'Nothing selected — it gets the safe read-only set.';}
function sawSkill(name,on){const s=SAW.d.skills;if(on&&!s.includes(name))s.push(name);if(!on)SAW.d.skills=s.filter(x=>x!==name)}
function sawPreset(p){SAW.d.tools=[...SAW_PRESETS[p]];sawRefreshList()}
async function sawSave(){
  sawCollect();
  const d=SAW.d;if(!d.name)return toast('name required');
  const cb=SAW.onSaved;
  await fetch('/api/subagents',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});
  SAW=null;drawSAW();
  if(cb){cb(d.name);return}          // an editor borrowed the wizard; it owns what happens next
  toast('subagent saved — address it in chat with @'+d.name);refreshApp('fabric');
}
function testSubagent(name){
  // test runs live in the chat: open it with the mention prefilled
  openApp('chat');
  setTimeout(()=>{const i=$('#input');if(i){i.value='@'+name+' ';i.focus();i.dispatchEvent(new Event('input'))}},250);
  toast('type the task after @'+name+' — the run streams right here and lands in Observability');
}

/* The static-DAG workflow UI lived here. The engine, /api/workflows and the
   `run_workflow` tool all still work — but no workflow had ever been run on any
   machine we could see, and flows do the same job while deciding at run time, so it
   no longer costs a tab. Deleted rather than hidden: dead UI that nothing reaches is
   worse than none. */


async function fabPlaneStats(){
  const o=await fetch('/api/fabric/observability').then(r=>r.json());
  const runs=(await fetch('/api/fabric/runs?limit=40').then(r=>r.json()));
  const dur=r=>r.finished_at?`${Math.round(r.finished_at-r.started_at)}s`:'…';
  const badge=s=>`<b style="color:${s==='ok'?'var(--ok,#34d399)':s==='running'?'var(--acc,#5eead4)':'var(--err,#f87171)'}">${esc(s)}</b>`;
  const live=runs.live.map(i=>`<div class="item"><div class="grow"><b>${esc(i.ref)}</b> <span class="sub">beat ${Math.round(Date.now()/1000-i.last_beat)}s ago${i.stale?' · <b style="color:var(--err,#f87171)">STALE</b>':''}</span></div>
      <button onclick="cancelRun('${i.run_id}')">⏹</button></div>`).join('');
  const planes=Object.entries(o.per_plane).map(([k,p])=>`<tr><td>${esc(k)}</td><td>${p.runs}</td><td>${p.ok}</td>
      <td>${p.faults?`<b style="color:var(--err,#f87171)">${p.faults}</b>`:0}</td>
      <td>${p.runs?Math.round(p.secs/p.runs):0}s</td><td>${p.tokens_in+p.tokens_out}</td></tr>`).join('');
  const rows=runs.runs.map(r=>`<div class="item" style="cursor:pointer" onclick="showRun('${r.id}')">
      <div class="grow"><span class="lbadge" style="margin-right:4px">${r.kind==='workflow'?'flow':'agent'}</span><b>${esc(r.ref)}</b> ${badge(r.status)}
        <div class="sub">${new Date(r.started_at*1000).toLocaleString()} · ${dur(r)} · ${(r.tokens_in||0)+(r.tokens_out||0)} tok · model ${esc(r.model||'—')}${r.fault?' · <span style="color:var(--err,#f87171)">'+esc(r.fault.slice(0,80))+'</span>':''}</div></div>
      ${r.status==='running'?`<button onclick="event.stopPropagation();cancelRun('${r.id}')">⏹</button>`:''}</div>`).join('')
    ||'<p class="mut">No fabric runs yet — delegate a task or run a workflow.</p>';
  body.innerHTML=`<div class="pad">${fabTabs()}
    ${live?`<div class="ptitle">Live data planes</div>${live}`:''}
    <div class="ptitle">Data planes — faults · performance · usage</div>
    <table style="width:100%;font-size:12px;border-collapse:collapse">
      <tr class="mut"><th style="text-align:left">plane</th><th>runs</th><th>ok</th><th>faults</th><th>avg</th><th>tokens</th></tr>
      <tr><td>main agent (L0 — this OS)</td><td>${o.main_agent.runs}</td><td>—</td>
        <td>${o.main_agent.faults?`<b style="color:var(--err,#f87171)">${o.main_agent.faults}</b>`:0}</td><td>—</td><td>${o.main_agent.tokens_in+o.main_agent.tokens_out}</td></tr>
      ${planes}</table>
    <div class="ptitle" style="margin-top:12px">Runs</div><div id="fab-run-detail"></div>${rows}</div>`;
}
async function cancelRun(id){await fetch('/api/fabric/runs/'+id+'/cancel',{method:'POST'});toast('⏹ cancel sent');}
async function showRun(id){
  const d=await fetch('/api/fabric/runs/'+id).then(r=>r.json());
  const ev=d.events.filter(e=>e.type!=='heartbeat').map(e=>`<div class="sub">${new Date(e.ts*1000).toLocaleTimeString()} · ${esc(e.type)} ${esc(JSON.stringify(e.payload).slice(0,140))}</div>`).join('');
  const steps=(d.steps||[]).map(s=>`<div class="sub">↳ step <b>${esc(s.ref)}</b> ${esc(s.status)} · ${(s.tokens_in||0)+(s.tokens_out||0)} tok · model ${esc(s.model||'—')}</div>`).join('');
  $('#fab-run-detail').innerHTML=`<div class="provbox"><div class="ptitle">${esc(d.run.ref)} · ${esc(d.run.status)}</div>
    ${steps}${d.run.output?`<pre style="white-space:pre-wrap;font-size:11.5px;max-height:160px;overflow:auto">${esc(d.run.output.slice(0,2500))}</pre>`:''}
    <details><summary class="mut">events (${d.events.length})</summary>${ev}</details></div>`;
}
var fabRefreshT=0;
function fabricLiveRefresh(){
  // The flow graph updates itself from the event stream; a full re-render would restart
  // the SVG mid-animation and throw away the log's scroll position.
  if(fabTab==='flow'&&FG.run&&!FG.ended)return;
  const now=Date.now();
  if(now-fabRefreshT<800)return;
  fabRefreshT=now;
  if(WM.wins.get('fabric'))refreshApp('fabric');
}

/* ================= the control plane: a flow run, drawn while it happens =============
   Two strictly separated halves:
     fgApply(ev)  — pure state, never touches the DOM. Events that arrive while the Team
                    window is closed still build a correct graph, so opening it paints the
                    truth once instead of replaying what was missed.
     fgPaint()    — idempotent, driven only by winTick. */
var FG={run:'',flow:'',nodes:new Map(),edges:[],art:new Map(),logs:[],dirty:false,ended:false,
        sel:'',detail:new Map()};

function fgReset(runId,flow){
  FG={run:runId||'',flow:flow||'',nodes:new Map(),edges:[],art:new Map(),logs:[],
      dirty:true,ended:false,sel:'',detail:new Map(),think:null};
}
/* The agent's reasoning as ONE self-replacing line, never 300 log rows.
   Thinking arrives as a stream of small deltas; pushed through fgLog it would evict
   every real control-plane event from the 300-row buffer within seconds, which is a
   worse panel than the empty one this fixes. The tail is what is useful live — where
   the agent is NOW — so keep the end, not the beginning. */
function fgThink(agent,text){
  if(!FG.think||FG.think.agent!==agent)FG.think={agent:agent||'',text:'',t:Date.now()};
  FG.think.text=(FG.think.text+(text||'')).slice(-600);
  FG.think.t=Date.now();
}
function fgLog(level,text){
  FG.logs.push({t:Date.now(),level:level||'info',text:text||''});
  if(FG.logs.length>300)FG.logs.splice(0,FG.logs.length-300);
}
function fgApply(ev){
  if(!ev||!ev.event)return;
  const graphish={flow_start:1,node_add:1,node_status:1,artifact:1,approval:1,log:1,flow_end:1,thinking:1};
  if(!graphish[ev.event])return;
  if(ev.event!=='flow_start'&&ev.run_id&&FG.run&&ev.run_id!==FG.run)return; // another run
  switch(ev.event){
    case 'flow_start':{
      fgReset(ev.run_id,ev.flow);
      FG.nodes.set(ev.run_id,{id:ev.run_id,agent:'master',label:ev.flow||'flow',
        status:'running',depth:0,t:Date.now()});
      fgLog('info','flow '+(ev.flow||'')+' started · '+((ev.origin||{}).surface||'manual')
            +(ev.tainted?' · payload from outside this machine':''));
      break;}
    case 'node_add':{
      if(FG.nodes.has(ev.node_id))break;
      // The master may be missing if flow_start was applied before this client knew the
      // run id (the id is handed to the caller the moment the row exists, which is a
      // beat before the event goes out). A delegation with nothing to hang off is worse
      // than one hanging off a placeholder.
      if(!FG.nodes.has(FG.run))FG.nodes.set(FG.run,{id:FG.run,agent:'master',
        label:FG.flow||'flow',status:'running',depth:0,t:Date.now()});
      FG.nodes.set(ev.node_id,{id:ev.node_id,agent:ev.agent,label:ev.agent,task:ev.task||'',
        status:'running',depth:1,seq:ev.seq||0,t:Date.now()});
      FG.edges.push({from:ev.parent||FG.run,to:ev.node_id,kind:'call'});
      (ev.deps||[]).forEach(h=>FG.edges.push({from:'h:'+h,to:ev.node_id,kind:'data'}));
      fgLog('info','→ '+ev.agent+': '+String(ev.task||'').slice(0,90));
      break;}
    case 'node_status':{
      const n=FG.nodes.get(ev.node_id);if(!n)break;
      n.status=ev.status;n.tokens=ev.tokens;n.fault=ev.fault;n.handle=ev.handle;
      n.child_run=ev.child_run;n.model=ev.model;n.approval='';
      FG.think=null;   // it has acted; the reasoning that led here is now history
      fgLog(ev.status==='ok'?'info':'error',
            n.label+' · '+ev.status+(ev.fault?' · '+ev.fault:'')+(ev.handle?' → '+ev.handle:''));
      break;}
    case 'artifact':
      FG.art.set(ev.handle,ev);break;
    case 'thinking':
      fgThink(ev.agent||'',ev.text||'');break;
    case 'approval':{
      const n=FG.nodes.get(ev.node_id);if(n)n.approval=ev.state;
      fgLog(ev.state==='asked'?'warn':(ev.state==='allowed'?'info':'error'),
            '⏸ '+ev.tool+' — '+ev.state+(ev.via?' ('+ev.via+')':'')
            +(ev.state==='asked'&&ev.reason?' · '+ev.reason:''));
      break;}
    case 'log':
      fgLog(ev.level,ev.text);break;
    case 'flow_end':{
      const n=FG.nodes.get(FG.run);if(n){n.status=ev.status;n.tokens=ev.tokens}
      FG.ended=true;FG.think=null;
      fgLog(ev.status==='ok'?'info':'error','flow '+ev.status
        +(ev.delivered&&ev.delivered.length?' · delivered: '+ev.delivered.join(', '):'')
        +(ev.fault?' · '+ev.fault:''));
      break;}
  }
  FG.dirty=true;
}
async function fgLoad(runId){
  /* Rebuild from the stored stream. The persisted events are the SAME vocabulary the
     websocket pushes, so there is one way to build the graph and not two. */
  try{
    const d=await fetch('/api/fabric/runs/'+runId).then(r=>r.json());
    fgReset(runId,(d.run||{}).flow||(d.run||{}).ref||'');
    (d.events||[]).forEach(e=>fgApply(Object.assign({event:e.type,run_id:runId},e.payload||{})));
    if(!FG.nodes.size)FG.nodes.set(runId,{id:runId,agent:'master',label:(d.run||{}).ref||'flow',
      status:(d.run||{}).status||'running',depth:0,t:Date.now()});
    if((d.run||{}).status&&(d.run||{}).status!=='running')FG.ended=true;
    FG.dirty=true;
  }catch(e){}
}
function fgCol(st){
  return st==='ok'?'var(--ok,#34d399)'
    :st==='running'?'var(--acc,#5eead4)'
    :st==='paused'?'var(--warn,#f59e0b)'
    :(st==='error'||st==='timeout'||st==='cancelled')?'var(--err,#f87171)'
    :st==='partial'?'var(--warn,#f59e0b)':'var(--line,#333)';
}
function fgSvgInner(){
  /* The depth cap is 2 — the master, and the agents it starts — so the layout is two
     columns and needs no solver. */
  const kids=[...FG.nodes.values()].filter(n=>n.depth===1).sort((a,b)=>(a.seq||0)-(b.seq||0));
  const master=FG.nodes.get(FG.run);
  const BW=190,BH=50,GY=64,MX=16,KX=250;
  const H=Math.max(BH+28,kids.length*GY+22),W=KX+BW+16;
  const my=Math.max(14,(H-BH)/2);
  const pos={};
  if(master)pos[master.id]={x:MX,y:my,n:master};
  kids.forEach((n,i)=>pos[n.id]={x:KX,y:14+i*GY,n:n});
  const hnode={};FG.art.forEach((a,h)=>{hnode[h]=a.node_id});
  let lines='';
  FG.edges.forEach(e=>{
    let from=e.from;
    if(e.kind==='data'){const h=from.slice(2);from=hnode[h];if(!from||from===e.to)return}
    const a=pos[from],b=pos[e.to];if(!a||!b)return;
    const y1=a.y+BH/2,y2=b.y+BH/2;
    lines+=`<path d="M${a.x+BW} ${y1} C ${a.x+BW+30} ${y1}, ${b.x-30} ${y2}, ${b.x} ${y2}"
      fill="none" stroke="${e.kind==='data'?'var(--acc,#5eead4)':'rgba(138,148,166,.5)'}"
      stroke-width="1.5" ${e.kind==='data'?'stroke-dasharray="4 3" stroke-opacity=".55"':''}
      marker-end="url(#fgarr)"/>`;
  });
  let boxes='';
  Object.values(pos).forEach(({x,y,n})=>{
    const st=n.approval==='asked'?'paused':(n.status||'');
    const tok=n.tokens?((n.tokens.in||0)+(n.tokens.out||0)):0;
    const sub=n.depth===0
      ?`${FG.nodes.size-1} delegation${FG.nodes.size===2?'':'s'}${tok?' · '+tok+' tok':''}`
      :`${st}${tok?' · '+tok+' tok':''}${n.handle?' · '+n.handle:''}`;
    boxes+=`<g style="cursor:pointer" onclick="fgSelect('${n.id}')">
      <rect x="${x}" y="${y}" rx="10" width="${BW}" height="${BH}"
        fill="${FG.sel===n.id?'rgba(94,234,212,.10)':'rgba(255,255,255,.04)'}"
        stroke="${fgCol(st)}" stroke-width="${FG.sel===n.id?2.6:1.6}">${st==='running'||st==='paused'?
        '<animate attributeName="stroke-opacity" values="1;.3;1" dur="1.2s" repeatCount="indefinite"/>':''}</rect>
      <text x="${x+11}" y="${y+20}" fill="var(--txt,#e6ebf2)" font-size="12" font-weight="600">${
        esc(n.depth===0?('▲ '+n.label):n.label)}${st==='paused'?' ⏸':''}</text>
      <text x="${x+11}" y="${y+37}" fill="var(--dim,#8a94a6)" font-size="10">${esc(sub)}</text></g>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-height:${H+10}px">
    <defs><marker id="fgarr" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
      <path d="M0,0 L7,3.5 L0,7 z" fill="rgba(138,148,166,.7)"/></marker></defs>${lines}${boxes}</svg>`;
}
/* The flow before it has ever run: master, and everyone it MAY call. Drawn ghosted in the
   same visual language as a live run, because "what will this do" and "what did this do"
   are the same picture at two moments — and you should be able to see the first one while
   you are still writing it. */
function fgPredictSvg(def){
  const roster=(def.roster||[]).map(r=>r.subagent||r);
  const BW=190,BH=50,GY=64,MX=16,KX=250;
  const H=Math.max(BH+28,Math.max(1,roster.length)*GY+22),W=KX+BW+16;
  const my=Math.max(14,(H-BH)/2);
  const ghost='stroke-dasharray="5 4" stroke-opacity=".55"';
  let out='',lines='';
  roster.forEach((nm,i)=>{
    const y=14+i*GY;
    lines+=`<path d="M${MX+BW} ${my+BH/2} C ${MX+BW+30} ${my+BH/2}, ${KX-30} ${y+BH/2}, ${KX} ${y+BH/2}"
      fill="none" stroke="rgba(138,148,166,.45)" stroke-width="1.5" ${ghost} marker-end="url(#fgarr)"/>`;
    out+=`<g><rect x="${KX}" y="${y}" rx="10" width="${BW}" height="${BH}"
        fill="rgba(255,255,255,.03)" stroke="var(--line,#333)" stroke-width="1.4" ${ghost}/>
      <text x="${KX+11}" y="${y+20}" fill="var(--dim,#8a94a6)" font-size="12" font-weight="600">${esc(nm)}</text>
      <text x="${KX+11}" y="${y+37}" fill="var(--dim2,#5b6474)" font-size="10">${
        esc(((def.roster||[]).find(r=>(r.subagent||r)===nm)||{}).why||'may be called')}</text></g>`;
  });
  if(!roster.length)out=`<text x="${KX}" y="${my+30}" fill="var(--dim,#8a94a6)" font-size="12">no roster yet</text>`;
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-height:${H+10}px">
    <defs><marker id="fgarr" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
      <path d="M0,0 L7,3.5 L0,7 z" fill="rgba(138,148,166,.55)"/></marker></defs>${lines}
    <g><rect x="${MX}" y="${my}" rx="10" width="${BW}" height="${BH}" fill="rgba(255,255,255,.04)"
        stroke="var(--acc,#5eead4)" stroke-width="1.6" ${ghost}/>
      <text x="${MX+11}" y="${my+20}" fill="var(--txt,#e6ebf2)" font-size="12" font-weight="600">▲ ${esc(def.name||'this flow')}</text>
      <text x="${MX+11}" y="${my+37}" fill="var(--dim,#8a94a6)" font-size="10">picks from ${roster.length} agent${roster.length===1?'':'s'} at run time</text></g>
    ${out}</svg>`;
}
/* The live reasoning line under the log. Dim and italic because it is not a record of
   anything — it is replaced continuously and cleared the moment the agent acts. A flow
   that thinks for a minute before its first tool call used to show an empty panel, which
   reads exactly like a hang; this is the difference between "working" and "stuck". */
function fgThinkRow(){
  const t=FG.think;if(!t||!t.text)return '';
  return `<div style="margin-top:6px;padding-top:6px;border-top:1px solid var(--ln,#2a3040);
    color:var(--dim,#8a94a6);font-style:italic;opacity:.85;white-space:pre-wrap">`
    +`<span style="opacity:.7">${esc(t.agent||'agent')} is thinking · </span>${esc(t.text)}</div>`;
}
function fgLogRow(l){
  const c=l.level==='error'?'var(--err,#f87171)':l.level==='warn'?'var(--warn,#f59e0b)':'var(--dim,#8a94a6)';
  return `<div style="color:${c}"><span style="opacity:.6">${new Date(l.t).toLocaleTimeString()}</span> ${esc(l.text)}</div>`;
}
/* Painted into every open view of this run — the Flows tab's inline panel and the run
   inspector are two windows onto one piece of state, so they are found by CLASS, not id. */
function fgPaint(){
  if(!FG.dirty)return;
  FG.dirty=false;
  const all=s=>[...document.querySelectorAll(s)];
  all('.fg-svg').forEach(svg=>{svg.innerHTML=FG.nodes.size?fgSvgInner()
    :'<p class="mut" style="padding:14px 2px">waiting for the first delegation…</p>'});
  const rows=[...FG.art.values()];
  all('.fg-board').forEach(bd=>{
    bd.innerHTML=rows.length?rows.map(a=>`<div class="item" style="cursor:pointer;padding:5px 0"
        onclick="fgOpenHandle('${esc(a.handle)}')">
        <div class="grow"><b>${esc(a.handle)}</b> <span class="sub">${esc(a.agent||a.kind)} · ${esc(a.status||'')}
        · ${a.bytes||0} B${a.tainted?' · <span style="color:var(--warn,#f59e0b)">tainted</span>':''}</span>
        <div class="sub">${esc((a.preview||'').slice(0,120))}</div></div></div>`).join('')
      :'<p class="mut">nothing on the board yet</p>';
  });
  all('.fg-log').forEach(log=>{
    const atBottom=log.scrollHeight-log.scrollTop-log.clientHeight<24;
    log.innerHTML=(FG.logs.map(fgLogRow).join('')||'<div class="mut">no control-plane events yet</div>')
      +fgThinkRow();
    if(atBottom)log.scrollTop=log.scrollHeight;
  });
  if(FG.run){
    const m=FG.nodes.get(FG.run)||{};
    const kids=[...FG.nodes.values()].filter(n=>n.depth===1);
    const tok=m.tokens?((m.tokens.in||0)+(m.tokens.out||0)):0;
    all('.fg-head').forEach(hd=>{
      hd.innerHTML=`<b>${esc(FG.flow||'')}</b> <span class="sub">run ${esc(FG.run.slice(0,8))} · `
        +`<b style="color:${fgCol(m.status)}">${esc(m.status||'…')}</b>`
        +` · ${kids.length} delegation${kids.length===1?'':'s'}${tok?' · '+tok+' tok':''}</span>`
        +(FG.ended?'':` <button style="float:right" onclick="cancelRun('${FG.run}')">⏹ Stop</button>`);
    });
  }
  fgPaintDetail();
}
/* The debug pane: what one agent was asked, every tool it called, and what came back. */
function fgPaintDetail(){
  const box=$('#fr-detail');
  if(!box)return;
  const n=FG.sel&&FG.nodes.get(FG.sel);
  if(!n){
    box.innerHTML='<p class="mut">Click an agent in the graph to see what it was asked, '
      +'every tool it called, and what came back.</p>';
    return;
  }
  const d=FG.detail.get(FG.sel);
  const tools=(d&&d.steps||[]).map(s=>`<div class="item" style="padding:4px 0">
      <div class="grow"><b>${esc(s.tool||'?')}</b>
      <span class="sub" style="color:${s.ok===false?'var(--err,#f87171)':'var(--dim,#8a94a6)'}">
        ${esc(s.status||'')}${s.ok===false?' · failed':''}</span></div></div>`).join('')
    ||'<p class="mut">'+(d?'it called no tools':'loading…')+'</p>';
  box.innerHTML=`<div class="ptitle" style="margin-top:0">${esc(n.label||'')}
      <span class="sub">${esc(n.status||'')}${n.model?' · '+esc(n.model.split('/').pop()):''}
      ${n.handle?' · → '+esc(n.handle):''}</span>
      ${n.child_run?`<button style="float:right" onclick="showRunInAudit('${esc(n.child_run)}')">full run</button>`:''}</div>
    ${n.task?`<div class="sub" style="margin-bottom:6px"><b>asked:</b> ${esc(n.task)}</div>`:''}
    ${n.fault?`<div class="sub" style="color:var(--err,#f87171)"><b>fault:</b> ${esc(n.fault)}</div>`:''}
    ${n.approval&&n.approval!=='allowed'?`<div class="sub" style="color:var(--warn,#f59e0b)">⏸ approval ${esc(n.approval)}</div>`:''}
    <div class="sawgrp" style="margin-top:6px">Tool calls</div>${tools}
    ${d&&d.output?`<div class="sawgrp">What it returned</div>
      <pre style="white-space:pre-wrap;font-size:11.5px;max-height:180px;overflow:auto">${esc(d.output.slice(0,4000))}</pre>`:''}`;
}
function fgSelect(nodeId){
  FG.sel=nodeId;FG.dirty=true;
  const n=FG.nodes.get(nodeId);
  if(n&&n.child_run&&!FG.detail.has(nodeId))fgLoadDetail(nodeId,n.child_run);
  openRunInspector(FG.run);      // clicking a node is asking to debug it
  fgPaint();
}
async function fgLoadDetail(nodeId,childRun){
  try{
    const d=await fetch('/api/fabric/runs/'+childRun).then(r=>r.json());
    const steps=[];
    (d.events||[]).filter(e=>e.type==='step').forEach(e=>{
      const p=e.payload||{};
      if(p.status==='start')steps.push({tool:p.tool,status:'ran'});
      else if(steps.length){const last=steps.filter(s=>s.tool===p.tool).pop();
        if(last){last.ok=p.ok!==false;last.status=p.ok===false?'error':'ok'}}
    });
    FG.detail.set(nodeId,{steps,output:(d.run||{}).output||'',fault:(d.run||{}).fault||''});
    FG.dirty=true;fgPaint();
  }catch(e){}
}
function showRunInAudit(rid){fabTab='runs';refreshApp('fabric');setTimeout(()=>showRun(rid),150)}
async function fgOpenHandle(h){
  if(!FG.run)return;
  const box=$('#fg-artifact');if(!box)return;
  try{
    const d=await fetch('/api/flows/runs/'+FG.run+'/artifacts/'+encodeURIComponent(h)).then(r=>r.json());
    const a=d.artifact||{};
    box.innerHTML=`<div class="provbox"><div class="ptitle">${esc(h)} · ${esc(a.agent||a.kind||'')}
      <button style="float:right" onclick="$('#fg-artifact').innerHTML=''">✕</button></div>
      ${a.task?`<div class="sub">asked for: ${esc(a.task)}</div>`:''}
      ${(a.deps||[]).length?`<div class="sub">built from: ${esc((a.deps||[]).join(', '))}</div>`:''}
      <pre style="white-space:pre-wrap;font-size:11.5px;max-height:300px;overflow:auto">${
        esc((a.content||'(empty)').slice(0,20000))}</pre></div>`;
  }catch(e){toast('could not open '+h)}
}

/* --- the Flows tab: definitions on the left, the live run on the right ------------- */
var FLOWS_CACHE=[];
var FLOW_SEL='';    // the flow shown in the detail pane
async function renderFabFlows(body,w){
  const [fl,runs]=await Promise.all([
    fetch('/api/flows').then(r=>r.json()).catch(()=>({flows:[]})),
    fetch('/api/fabric/runs?limit=40').then(r=>r.json()).catch(()=>({runs:[],live:[]}))]);
  FLOWS_CACHE=fl.flows||[];
  const flowRuns=(runs.runs||[]).filter(r=>r.kind==='flow');
  const latest={};flowRuns.forEach(r=>{if(!latest[r.flow||r.ref])latest[r.flow||r.ref]=r});
  if(FLOW_FOCUS)FLOW_SEL=FLOW_FOCUS;FLOW_FOCUS='';
  if(!FLOWS_CACHE.some(f=>f.name===FLOW_SEL))FLOW_SEL=(FLOWS_CACHE[0]||{}).name||'';
  const sel=FLOWS_CACHE.find(f=>f.name===FLOW_SEL);

  /* Left: every flow, one line each, readable at a glance. The detail lives on the right,
     so adding a tenth flow costs one row instead of another screenful. */
  const list=FLOWS_CACHE.map(f=>{
    const run=latest[f.name];
    const dot=f.enabled?'var(--ok,#34d399)':(f.draft&&f.draft.model?'var(--acc,#5eead4)':'var(--dim2,#5b6474)');
    return `<div class="item" style="cursor:pointer;padding:7px 8px;border-radius:8px;
        background:${f.name===FLOW_SEL?'rgba(94,234,212,.08)':'transparent'}"
        onclick="flowSelect('${esc(f.name)}')">
      <span style="color:${dot};font-size:9px;margin-right:6px">●</span>
      <div class="grow"><b>${esc(f.name)}</b>
        <div class="sub">${f.enabled?'live':(f.draft&&f.draft.model?'drafted':'off')}${
          run?' · last '+esc(run.status):''}</div></div></div>`;
  }).join('')||'<p class="mut" style="padding:6px">nothing yet</p>';

  body.innerHTML=`<div class="pad">${fabTabs()}
    <div class="row" style="align-items:flex-start;gap:14px">
      <div style="flex:0 0 210px;min-width:180px">
        <textarea id="flw-ask" rows="3" placeholder="Every morning check my disk and tell me on Telegram if it is filling up"></textarea>
        <button class="save" style="margin:6px 0 0" onclick="composeFlow()">✦ Draft a flow</button>
        <button style="width:100%;margin-top:4px" onclick="openFLW()">＋ Build one by hand</button>
        <div id="flw-ask-status" class="sub" style="margin:4px 0"></div>
        <div class="sawgrp">Flows</div>
        ${list}
      </div>
      <div style="flex:1;min-width:0" id="flow-detail">${sel?flowDetail(sel,latest[sel.name]):
        `<p class="mut">No flows yet. A flow is a standing mission: what you want, who may work on it,
         what it may touch, and what starts it. The orchestrator picks the agents and the order while it runs.</p>`}</div>
    </div></div>`;
}
function flowSelect(name){FLOW_SEL=name;refreshApp('fabric')}
function trigLabel(t){
  const c=t.config||{};
  if(t.kind==='cron')return c.type==='daily'?('cron '+(c.at||'08:00'))
    :c.type==='interval'?('every '+(c.minutes||60)+' min'):'once';
  if(t.kind==='message')return 'message "'+(c.pattern||'')+'"';
  if(t.kind==='os_event')return 'on '+(c.event||'event');
  if(t.kind==='flow_done')return 'after '+(c.flow||'another flow')+(c.status&&c.status!=='any'?' ('+c.status+')':'');
  return 'webhook';
}
/* One flow, in full. Everything that used to be crammed into a card, with room to read it. */
function flowDetail(f,run){
  const drafted=f.draft&&f.draft.model&&!f.enabled;
  const trigs=(f.triggers||[]).map(t=>`<span class="lbadge" title="${esc(t.kind)}${
    t.dropped?' · '+t.dropped+' fires dropped by the cooldown':''}">${esc(trigLabel(t))}${
    f.enabled?'':' (not armed)'}</span>`).join(' ')
    ||'<span class="mut">no triggers — runs when you say so</span>';
  const hook=f.enabled&&(f.triggers||[]).find(t=>t.kind==='webhook');
  const gr=f.enabled?(f.grants||[]):(f.would_grant||[]);
  const allow=gr.filter(g=>g.effect!=='deny');
  return `<div class="ptitle" style="margin-top:0">${esc(f.name)}
      ${drafted?'<span class="lbadge" title="drafted by '+esc(f.draft.model)+'">✦ drafted</span>':''}
      <span class="sub">· ${f.enabled?'live':'not enabled'}</span>
      <span style="float:right">
        <button class="save" style="margin:0;display:inline-block;width:auto;padding:4px 12px"
          onclick="enableFlow('${esc(f.name)}',${f.enabled?'false':'true'})">${f.enabled?'Turn off':'Enable'}</button>
        <button onclick="openFLW('${esc(f.name)}')">✎ Edit</button>
        <button title="${drafted?'discard this draft':'delete'}"
          onclick="${drafted?`discardFlow('${esc(f.name)}')`:`delFlow('${esc(f.name)}')`}">✕</button></span></div>
    <div class="sub" style="margin:2px 0 8px">${esc(f.mission||'')}</div>
    <div style="border:1px solid var(--line,#232a35);border-radius:10px;padding:6px;overflow-x:auto">${fgPredictSvg(f)}</div>
    <div class="row" style="margin-top:8px;gap:10px;align-items:flex-start">
      <div style="flex:1;min-width:0">
        <div class="sawgrp" style="margin-top:0">Starts</div><div class="sub">${trigs}</div>
        <div class="sawgrp">Answers to</div>
        <div class="sub">${esc((f.sinks||[]).map(s=>s.kind).join(', ')||'wherever it was triggered from')}</div>
      </div>
      <div style="flex:1;min-width:0">
        <div class="sawgrp" style="margin-top:0">${f.enabled?'Granted':'Would grant'} (${gr.length})</div>
        <div class="sub">${allow.length?esc(allow.slice(0,6).map(g=>g.resource
          .replace(/^tool:|^agent:subagent\//,'')).join(', '))+(allow.length>6?' …':''):'nothing'}</div>
        ${f.enabled?'':'<div class="sub" style="color:var(--warn,#f59e0b);margin-top:3px">holds none of it until you Enable</div>'}
      </div>
    </div>
    ${drafted&&f.draft.notes?`<div class="sub" style="margin-top:6px">✦ assumed: ${esc(f.draft.notes)}</div>`:''}
    ${drafted&&(f.draft.agents_created||[]).length?`<div class="sub">✦ created for it: ${esc(f.draft.agents_created.join(', '))}</div>`:''}
    ${drafted?(f.draft.warnings||[]).map(w=>`<div class="sub" style="color:var(--warn,#f59e0b)">⚠ ${esc(w)}</div>`).join(''):''}
    ${hook?`<div class="sub" style="margin-top:6px">hook: <code style="font-size:11px">${esc(hook.url||'')}</code>
      <button onclick="navigator.clipboard.writeText('${esc(hook.url||'')}');toast('hook URL copied')">copy</button></div>`:''}
    <div class="row" style="margin-top:10px"><input id="fl-in-${esc(f.name)}" placeholder="input for this run (optional)…">
      <button class="save" style="margin:0;flex:0 0 ${f.enabled?'80':'110'}px"
        title="${f.enabled?'run it now':'try it with you watching — it holds no permissions, so every risky step asks you'}"
        onclick="runFlow('${esc(f.name)}')">${f.enabled?'Run':'Test run'}</button></div>
    <div class="sub" style="margin-top:4px">${f.enabled
      ?'Opens the Run Inspector — the graph, the log and every tool call.'
      :'A test run works with you watching: every risky step stops and asks. Nothing fires on its own until you Enable.'}</div>
    ${run?`<div class="sub" style="margin-top:8px;cursor:pointer" onclick="fgWatch('${run.id}')">
      last run: ${esc(run.status)} · ${new Date(run.started_at*1000).toLocaleString()}${
      run.fault?' · <span style="color:var(--err,#f87171)">'+esc(run.fault.slice(0,70))+'</span>':''} → open</div>`:''}`;
}
/* Say what actually went wrong. A blanket "could not reach the model" is worse than no
   message: it sent someone looking at Ollama when the real answer was that the server was
   running code older than the page it had just served. */
async function apiJSON(path,opts){
  let res;
  try{ res=await fetch(path,opts); }
  catch(e){ throw new Error('could not reach AgentOS itself ('+(e.message||'network error')+')') }
  let data=null;
  try{ data=await res.json() }catch(e){}
  if(res.status===404||res.status===405)
    throw new Error('this AgentOS server does not have '+path+' — it is running older code '
      +'than this page. Restart it to pick up the change.');
  if(!res.ok)
    throw new Error(((data&&(data.error||data.detail))||('HTTP '+res.status+' from '+path))
      +((data&&(data.warnings||[]).length)?' — '+data.warnings.join(' · '):''));
  if(!data)throw new Error(path+' answered with something that was not JSON');
  return data;
}
async function composeFlow(){
  const box=$('#flw-ask'),st=$('#flw-ask-status');
  const req=(box&&box.value||'').trim();
  if(!req)return toast('say what you want to happen');
  if(st)st.innerHTML='thinking… (a local model can take a minute)';
  try{
    // The draft lands in the list as a disabled card, not in a modal you have to answer.
    // Disabled means it holds no permissions and no armed trigger, so it is inert until
    // you read it and press Enable — which is what makes creating it without asking safe.
    const r=await apiJSON('/api/flows/draft',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({request:req})});
    if(box)box.value='';
    if(st)st.innerHTML='';
    FLOW_FOCUS=r.flow.name;
    toast('drafted “'+r.flow.name+'” — read it, then Enable');
    refreshApp('fabric');
  }catch(e){
    if(st)st.innerHTML='<span style="color:var(--err,#f87171)">'+esc(e.message||String(e))+'</span>';
  }
}
var FLOW_FOCUS='';   // the card to highlight after a draft lands
async function enableFlow(name,on){
  const r=await fetch('/api/flows/'+encodeURIComponent(name)+'/enable',
    {method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({enabled:on})}).then(r=>r.json());
  if(r.error)return toast(r.error);
  const g=r.report.grants;
  toast(on?`“${name}” is live · ${g.added} permission${g.added===1?'':'s'} granted`
          :`“${name}” is off · ${g.revoked} permission${g.revoked===1?'':'s'} taken back`);
  refreshApp('fabric');
}
async function discardFlow(name){
  if(!await osConfirm('Discard the draft “'+name+'”?',
     'It holds no permissions, so nothing is revoked. Agents it created are removed too, '
     +'unless another flow is using them.',{danger:true,confirmText:'Discard'}))return;
  const r=await fetch('/api/flows/'+encodeURIComponent(name)+'/discard',{method:'POST'})
    .then(r=>r.json());
  toast((r.agents_removed||[]).length?'discarded · also removed '+r.agents_removed.join(', ')
                                     :'discarded');
  refreshApp('fabric');
}
async function fgWatch(runId){await fgLoad(runId);openRunInspector(runId);fgPaint()}

/* ---- Executions: what has actually been running on this machine -------------------- */
var EXEC_FILTER='';
async function renderFabRuns(body){
  /* One "what happened" view. Executions and Observability were the same question asked of
     two endpoints; the per-plane numbers are a strip at the top of the history rather than
     a tab of their own. */
  const [d,o,all]=await Promise.all([
    fetch('/api/flows/runs'+(EXEC_FILTER?'?flow='+encodeURIComponent(EXEC_FILTER):''))
      .then(r=>r.json()).catch(()=>({runs:[],flows:[],live:[]})),
    fetch('/api/fabric/observability').then(r=>r.json()).catch(()=>({per_plane:{},main_agent:{},recent_faults:[]})),
    fetch('/api/fabric/runs?limit=40').then(r=>r.json()).catch(()=>({runs:[]}))]);
  const badge=s=>`<b style="color:${s==='ok'?'var(--ok,#34d399)':s==='running'?'var(--acc,#5eead4)'
    :s==='partial'?'var(--warn,#f59e0b)':'var(--err,#f87171)'}">${esc(s)}</b>`;
  const chips=['<button class="sawchip'+(EXEC_FILTER?'':' on')+'" onclick="execFilter(\'\')">all flows</button>']
    .concat((d.flows||[]).map(f=>`<button class="sawchip${EXEC_FILTER===f?' on':''}"
      onclick="execFilter('${esc(f)}')">${esc(f)}</button>`)).join(' ');
  const rows=(d.runs||[]).map(r=>{
    const when=new Date(r.started_at*1000);
    return `<div class="item" style="cursor:pointer" onclick="fgWatch('${r.id}')">
      <div class="grow">
        <b>${esc(r.flow||r.ref)}</b> ${badge(r.status)}
        <span class="sub">· ${r.delegations} delegation${r.delegations===1?'':'s'}
          · ${r.seconds}s · ${(r.tokens_in||0)+(r.tokens_out||0)} tok · via ${esc(r.origin_surface||'manual')}</span>
        <div class="sub">${when.toLocaleString()}${r.agents.length?' · '+esc(r.agents.join(', ')):''}${
          r.failed_steps.length?' · <span style="color:var(--err,#f87171)">failed: '
            +esc(r.failed_steps.join(', '))+'</span>':''}</div>
        ${r.fault?`<div class="sub" style="color:var(--err,#f87171)">${esc(r.fault.slice(0,140))}</div>`:''}
        ${r.output?`<div class="sub">${esc(r.output.slice(0,150))}</div>`:''}
      </div>
      ${r.status==='running'?`<button onclick="event.stopPropagation();cancelRun('${r.id}')">⏹</button>`:''}
      </div>`;
  }).join('')||`<p class="mut">Nothing has run yet${EXEC_FILTER?' for “'+esc(EXEC_FILTER)+'”':''}.
    Runs started by a trigger, from chat, from Telegram or by hand all land here.</p>`;
  const live=(d.live||[]).map(i=>`<div class="item"><div class="grow"><b>${esc(i.ref)}</b>
      <span class="sub">${esc(i.state||'running')} · beat ${Math.round(Date.now()/1000-i.last_beat)}s ago
      ${i.stale?'· <b style="color:var(--err,#f87171)">STALE</b>':''}</span></div>
      <button onclick="fgWatch('${i.run_id}')">watch</button></div>`).join('');
  const m=o.main_agent||{};
  const planes=Object.entries(o.per_plane||{}).map(([k,p])=>`<tr><td>${esc(k)}</td><td>${p.runs}</td>
      <td>${p.faults?`<b style="color:var(--err,#f87171)">${p.faults}</b>`:0}</td>
      <td>${p.runs?Math.round(p.secs/p.runs):0}s</td><td>${p.tokens_in+p.tokens_out}</td></tr>`).join('');
  const other=(all.runs||[]).filter(r=>r.kind!=='flow').slice(0,12).map(r=>
    `<div class="sub" style="cursor:pointer" onclick="showRun('${r.id}')">${esc(r.kind)} ·
      <b>${esc(r.ref)}</b> ${esc(r.status)} · ${new Date(r.started_at*1000).toLocaleString()}</div>`).join('');
  body.innerHTML=`<div class="pad">${fabTabs()}
    ${live?`<div class="ptitle" style="margin-top:0">Running now</div>${live}`:''}
    <div class="row" style="gap:6px;flex-wrap:wrap;margin:${live?'10px':'0'} 0 8px">${chips}</div>
    ${rows}
    <details style="margin-top:14px"><summary class="mut">Per-agent totals &amp; other runs</summary>
      <table style="width:100%;font-size:12px;border-collapse:collapse;margin-top:6px">
        <tr class="mut"><th style="text-align:left">agent</th><th>runs</th><th>faults</th><th>avg</th><th>tokens</th></tr>
        <tr><td>main agent (this OS)</td><td>${m.runs||0}</td>
          <td>${m.faults?`<b style="color:var(--err,#f87171)">${m.faults}</b>`:0}</td><td>—</td>
          <td>${(m.tokens_in||0)+(m.tokens_out||0)}</td></tr>
        ${planes}</table>
      ${(o.recent_faults||[]).slice(0,5).map(f=>`<div class="sub" style="color:var(--err,#f87171)">
        fault · ${esc(f.ref)}: ${esc(String(f.fault||'').slice(0,90))}</div>`).join('')}
      ${other?`<div class="sawgrp">Delegations &amp; static workflows</div>${other}`:''}
      <div id="fab-run-detail"></div>
    </details>
    <p class="mut" style="margin-top:10px">Click an execution to replay it in the Run Inspector —
      the graph, the control-plane log and every tool call, exactly as it happened.</p></div>`;
}
function execFilter(f){EXEC_FILTER=f;refreshApp('fabric')}

/* ---- the run inspector: what a manual run is actually doing ----------------------
   Triggering a flow by hand is nearly always debugging, so the log comes to you rather
   than being somewhere to go and look for. */
function openRunInspector(runId){
  if(!runId)return;
  const w=openApp('flowrun');
  if(w&&!FG.ended)winTick(w,fgPaint,250,{key:'graph'});
  return w;
}
function renderFlowRun(body,w){
  if(!FG.run){
    body.innerHTML=`<div class="pad"><p class="mut">No run is being watched. Run a flow from
      Workflows → Flows, or click a past run to replay it here.</p>
      <button class="save" onclick="openApp('fabric');fabSetTab(1)">Open Flows</button></div>`;
    return;
  }
  body.innerHTML=`<div class="pad">
    <div class="ptitle" style="margin-top:0"><span class="fg-head"></span></div>
    <div class="row" style="gap:6px;margin-bottom:6px">
      <button onclick="fgRerun()">↻ Run again</button>
      <button onclick="fgOpenBoardRaw()">raw events</button>
      <div class="grow"></div>
    </div>
    <div class="fg-svg" style="min-height:90px;border:1px solid var(--line,#232a35);
      border-radius:12px;padding:6px;overflow-x:auto"></div>
    <div class="row" style="margin-top:8px;align-items:flex-start;gap:10px">
      <div style="flex:1.1;min-width:220px">
        <div class="ptitle" style="margin:0 0 4px">Control-plane log</div>
        <div class="fg-log" style="font-family:ui-monospace,monospace;font-size:11px;line-height:1.5;
          max-height:210px;overflow:auto;border:1px solid var(--line,#232a35);border-radius:10px;padding:8px"></div>
        <div class="ptitle" style="margin:8px 0 4px">Board</div>
        <div class="fg-board"></div>
      </div>
      <div style="flex:1;min-width:220px"><div class="ptitle" style="margin:0 0 4px">Step detail</div>
        <div id="fr-detail"></div>
        <div class="ptitle" style="margin:10px 0 4px">Change this flow with AI</div>
        <div class="sub" style="margin-bottom:4px">Watching it go wrong is the best moment to fix
          it. Editing here does not touch the run in flight — it takes effect next time.</div>
        <textarea id="fr-ai" rows="2" placeholder="give the researcher fetch_url too · tell the writer to be shorter"></textarea>
        <div class="row" style="gap:6px"><button class="save" style="margin:0;flex:0 0 130px"
          onclick="frAiEdit()">✦ Open with this</button></div>
      </div>
    </div>
    <div id="fg-artifact" style="margin-top:8px"></div>
    <div id="fr-raw" style="margin-top:8px"></div></div>`;
  if(w)winTick(w,fgPaint,250,{key:'graph'});
  FG.dirty=true;fgPaint();
}
async function fgRerun(){
  if(!FG.flow)return;
  const d=await fetch('/api/fabric/runs/'+FG.run).then(r=>r.json()).catch(()=>({}));
  const input=((d.run||{}).input)||'';
  const r=await fetch('/api/flows/'+encodeURIComponent(FG.flow)+'/run',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({input,surface:'gui'})}).then(r=>r.json()).catch(()=>({error:'could not start it'}));
  if(r.error)return toast(r.error);
  fgReset(r.run_id,FG.flow);fgPaint();
  toast('running again');
}
/* From the inspector into the editor, carrying the change you just typed. The run keeps
   going: a definition edit is for the next run, and pretending otherwise — mutating a flow
   mid-flight — would make a run's own record of itself a lie. */
async function frAiEdit(){
  if(!FG.flow)return;
  const ask=($('#fr-ai')||{}).value||'';
  const fl=await fetch('/api/flows').then(r=>r.json()).catch(()=>({flows:[]}));
  FLOWS_CACHE=fl.flows||[];
  if(!FLOWS_CACHE.some(f=>f.name===FG.flow))return toast('that flow no longer exists');
  await openFLW(FG.flow);
  const box=$('#flw-ai');
  if(box&&ask.trim()){box.value=ask.trim();flwAiApply()}
  else if(box)box.focus();
}
async function fgOpenBoardRaw(){
  const box=$('#fr-raw');if(!box)return;
  if(box.innerHTML){box.innerHTML='';return}
  const d=await fetch('/api/fabric/runs/'+FG.run).then(r=>r.json()).catch(()=>({events:[]}));
  box.innerHTML=`<div class="provbox"><div class="ptitle" style="margin-top:0">Raw events
      (${(d.events||[]).length})</div>
    <pre style="white-space:pre-wrap;font-size:11px;max-height:240px;overflow:auto">${
      esc((d.events||[]).filter(e=>e.type!=='heartbeat')
        .map(e=>new Date(e.ts*1000).toLocaleTimeString()+'  '+e.type+'  '
          +JSON.stringify(e.payload)).join('\n'))}</pre></div>`;
}
async function runFlow(name){
  const i=$('#fl-in-'+name);
  let r;
  try{
    r=await apiJSON('/api/flows/'+encodeURIComponent(name)+'/run',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({input:(i&&i.value||'').trim(),surface:'gui'})});
  }catch(e){return toast(e.message||String(e))}
  // Only reset if flow_start has not already landed: the server hands back the run id the
  // moment the row exists, which is a beat BEFORE it broadcasts flow_start — so a reset
  // here can arrive second and wipe the master node the event just created.
  if(FG.run!==r.run_id)fgReset(r.run_id,name);
  openRunInspector(r.run_id);   // running by hand is debugging: bring the log to them
  fgPaint();
}
async function delFlow(name){
  if(!await osConfirm('Delete the flow “'+name+'”?',
     'Its triggers stop and the permissions it was granted are revoked. Anything you granted by hand stays.',
     {danger:true,confirmText:'Delete'}))return;
  await fetch('/api/flows/'+encodeURIComponent(name),{method:'DELETE'});
  refreshApp('fabric');
}

/* --- the flow editor: permissions and triggers are part of the DEFINITION ---------- */
var FLW=null;
async function openFLW(name,draft){
  const [subs,tools,skills,models]=await Promise.all([
    fetch('/api/subagents').then(r=>r.json()).catch(()=>({subagents:[]})),
    fetch('/api/tools').then(r=>r.json()).catch(()=>({tools:[]})),
    fetch('/api/skills').then(r=>r.json()).catch(()=>({skills:[]})),
    fetch('/api/models').then(r=>r.json()).catch(()=>({models:[]}))]);
  const ex=name?FLOWS_CACHE.find(f=>f.name===name):null;
  FLW={exists:!!ex,subs:subs.subagents||[],tools:tools.tools||[],skills:skills.skills||[],
    models:models.models||[],q:'',draft:(draft||null),
    d:ex?JSON.parse(JSON.stringify(ex))
       :Object.assign({name:'',description:'',mission:'',roster:[],model:'',
         permissions:{tools:[],mcp:[],skills:[],net:[],fs_read:[],fs_write:[],memory:'read-space'},
         sinks:[{kind:'origin'}],triggers:[],autonomy_cap:'balanced',max_delegations:12,
         max_steps:24,max_seconds:1800,enabled:1},draft||{})};
  const p=FLW.d.permissions=FLW.d.permissions||{};
  ['tools','mcp','skills','net','fs_read','fs_write'].forEach(k=>p[k]=p[k]||[]);
  p.memory=p.memory||'read-space';
  // Agents the draft proposes but that do not exist yet. They are created on Save, never
  // before: a draft you closed without saving must not leave three subagents behind.
  FLW.d.new_agents=FLW.d.new_agents||[];
  drawFLW();
}
function flwNewAgent(spec){
  // The wizard is opened OVER the flow editor (appended later, so it stacks above) and the
  // flow's half-filled form is saved into FLW.d first — nothing typed is lost either way.
  flwCollect();
  openSAW(null,{name:(spec||{}).name||'',soul:(spec||{}).soul||'',tools:(spec||{}).tools||[],
    onSaved:async nm=>{
      const sa=await fetch('/api/subagents').then(r=>r.json()).catch(()=>({subagents:[]}));
      FLW.subs=sa.subagents||[];
      FLW.d.new_agents=(FLW.d.new_agents||[]).filter(a=>a.name!==nm);  // it exists now
      flwRoster(nm,true);
      drawFLW();
      toast('“'+nm+'” created and added to the roster');
    },
    onCancel:()=>drawFLW()});
}
function flwDropNewAgent(nm){
  FLW.d.new_agents=(FLW.d.new_agents||[]).filter(a=>a.name!==nm);
  FLW.d.roster=(FLW.d.roster||[]).filter(r=>r.subagent!==nm);
  flwCollect();drawFLW();
}
function flwToggle(list,v,on){const a=FLW.d.permissions[list];
  if(on&&!a.includes(v))a.push(v);if(!on)FLW.d.permissions[list]=a.filter(x=>x!==v);flwPreview()}
function flwRoster(nm,on){
  const r=FLW.d.roster;
  if(on&&!r.some(x=>x.subagent===nm))r.push({subagent:nm,why:''});
  if(!on)FLW.d.roster=r.filter(x=>x.subagent!==nm);
  flwPreview();
}
function flwSink(kind,on){
  const s=FLW.d.sinks||[];
  if(on&&!s.some(x=>x.kind===kind))s.push({kind});
  FLW.d.sinks=on?s:s.filter(x=>x.kind!==kind);
}
function flwAddTrigger(kind){
  const c=kind==='cron'?{type:'daily',at:'08:00'}
    :kind==='message'?{pattern:'',mode:'prefix',surfaces:['telegram','gui']}
    :kind==='os_event'?{event:flwFirstOsEvent(),match:''}
    :kind==='flow_done'?{flow:'',status:'any'}:{};
  FLW.d.triggers=(FLW.d.triggers||[]).concat([{kind,config:c,cooldown_secs:60,enabled:1}]);
  drawFLW();
}
/* The first OS event this machine can actually fire. A new trigger must not
   default to one that is greyed out on the box you are standing at. */
function flwFirstOsEvent(){
  const gone=(typeof PLATFORM!=='undefined'&&PLATFORM.os_events)||{};
  return ['notification','file_change','login','idle'].find(x=>!gone[x])||'file_change';
}
function flwDelTrigger(i){FLW.d.triggers.splice(i,1);drawFLW()}
function flwTrigSet(i,key,val){
  const t=FLW.d.triggers[i];if(!t)return;
  if(key==='cooldown_secs')t.cooldown_secs=+val||0;else t.config[key]=val;
}
async function flwPreview(){
  const box=$('#flw-preview');if(!box)return;
  flwCollect();
  try{
    const r=await fetch('/api/flows/preview',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(FLW.d)}).then(r=>r.json());
    if(r.error){box.innerHTML=`<span style="color:var(--warn,#f59e0b)">${esc(r.error)}</span>`;return}
    const g=r.grants||[];
    box.innerHTML=`Saving grants <b>${g.length}</b> permission${g.length===1?'':'s'}: `
      +esc(g.slice(0,6).map(x=>(x.effect==='deny'?'✕ ':'✓ ')+x.resource).join(' · '))
      +(g.length>6?` +${g.length-6} more`:'');
  }catch(e){}
}
function flwCollect(){
  const d=FLW.d,g=id=>{const e=$(id);return e?e.value:''};
  if($('#flw-name'))d.name=g('#flw-name').trim();
  d.description=g('#flw-desc');d.mission=g('#flw-mission');d.model=g('#flw-model');
  d.autonomy_cap=g('#flw-cap')||'balanced';
  d.max_delegations=+g('#flw-deleg')||12;d.max_steps=+g('#flw-steps')||24;
  d.max_seconds=+g('#flw-secs')||1800;
  const lines=s=>String(s||'').split('\n').map(x=>x.trim()).filter(Boolean);
  d.permissions.net=lines(g('#flw-net'));
  d.permissions.fs_read=lines(g('#flw-fsr'));
  d.permissions.fs_write=lines(g('#flw-fsw'));
  d.permissions.memory=g('#flw-mem')||'read-space';
  (d.triggers||[]).forEach((t,i)=>{
    document.querySelectorAll(`[data-trig="${i}"]`).forEach(el=>{
      flwTrigSet(i,el.getAttribute('data-key'),el.type==='number'?+el.value:el.value);
    });
  });
}
function drawFLW(){
  let ov=$('#flw-ov');
  if(!FLW){ov&&ov.remove();return}
  if(!ov){ov=document.createElement('div');ov.id='flw-ov';
    ov.style.cssText='position:fixed;inset:0;z-index:9998;background:rgba(5,7,9,.75);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center';
    ov.onclick=e=>{if(e.target===ov){FLW=null;drawFLW()}};document.body.appendChild(ov);}
  const d=FLW.d,p=d.permissions;
  const pending=(d.new_agents||[]).map(a=>`<label class="sawrow on" style="border-style:dashed">
      <span style="width:16px;text-align:center">✦</span>
      <div class="grow"><div class="n">${esc(a.name)} <span class="lbadge">will be created on save</span></div>
        <div class="d">${esc((a.soul||'').slice(0,90))}${(a.tools||[]).length?' · '+esc((a.tools||[]).join(', ')):''}</div></div>
      <button onclick="event.preventDefault();flwNewAgent(${esc(JSON.stringify(a)).replace(/"/g,'&quot;')})" title="edit and create it now">✎</button>
      <button onclick="event.preventDefault();flwDropNewAgent('${esc(a.name)}')" title="drop it">✕</button></label>`).join('');
  const roster=pending+(FLW.subs.map(s=>{const on=(d.roster||[]).some(x=>x.subagent===s.name);
    return `<label class="sawrow ${on?'on':''}"><input type="checkbox" ${on?'checked':''}
      onchange="flwRoster('${esc(s.name)}',this.checked);this.closest('.sawrow').classList.toggle('on',this.checked)">
      <div class="grow"><div class="n">${esc(s.name)}</div><div class="d">${esc((s.soul||'').slice(0,90))}</div></div></label>`;
  }).join('')||(pending?'':'<p class="mut">No subagents yet — create one below; the master orchestrates, it does not do the work itself.</p>'));
  const q=(FLW.q||'').toLowerCase();
  const tl=FLW.tools.filter(t=>!q||t.name.toLowerCase().includes(q)||(t.description||'').toLowerCase().includes(q))
    .slice(0,60).map(t=>{const on=p.tools.includes(t.name);
      return `<label class="sawrow ${on?'on':''}"><input type="checkbox" ${on?'checked':''}
        onchange="flwToggle('tools','${esc(t.name)}',this.checked);this.closest('.sawrow').classList.toggle('on',this.checked)">
        <div class="grow"><div class="n">${esc(t.name)}</div><div class="d">${esc((t.description||'').slice(0,100))}</div></div></label>`}).join('');
  const skl=FLW.skills.map(s=>{const on=p.skills.includes(s.name);
    return `<label class="sawrow ${on?'on':''}"><input type="checkbox" ${on?'checked':''}
      onchange="flwToggle('skills','${esc(s.name)}',this.checked);this.closest('.sawrow').classList.toggle('on',this.checked)">
      <div class="grow"><div class="n">${esc(s.name)}</div></div></label>`}).join('')
    ||'<p class="mut">No skills installed.</p>';
  const sinkBox=['origin','telegram','gui','notify','report'].map(k=>{
    const on=(d.sinks||[]).some(x=>x.kind===k);
    return `<label class="sawchip ${on?'on':''}" style="cursor:pointer"><input type="checkbox" style="margin-right:5px"
      ${on?'checked':''} onchange="flwSink('${k}',this.checked);this.closest('label').classList.toggle('on',this.checked)">${k}</label>`;
  }).join(' ');
  const trigs=(d.triggers||[]).map((t,i)=>{
    const c=t.config||{};
    let f='';
    if(t.kind==='cron')f=`<select data-trig="${i}" data-key="type" style="width:auto">
        ${['daily','interval','once'].map(x=>`<option ${c.type===x?'selected':''}>${x}</option>`).join('')}</select>
      <input data-trig="${i}" data-key="at" value="${esc(c.at||'08:00')}" placeholder="HH:MM" style="width:80px">
      <input data-trig="${i}" data-key="minutes" type="number" value="${c.minutes||60}" placeholder="minutes" style="width:80px">`;
    else if(t.kind==='message')f=`<input data-trig="${i}" data-key="pattern" value="${esc(c.pattern||'')}" placeholder="pattern e.g. vendor:">
      <select data-trig="${i}" data-key="mode" style="width:auto">${['prefix','substring','regex'].map(x=>`<option ${c.mode===x?'selected':''}>${x}</option>`).join('')}</select>`;
    else if(t.kind==='os_event'){
      // Two of the four OS events need AgentOS to BE the Linux session (the
      // notification daemon claims org.freedesktop.Notifications only in DE mode;
      // the login hook runs only in DE/KIOSK). /api/platform says which can fire
      // here, so on a hosted or headless box they are disabled and say why —
      // offering them would be a control that saves, looks armed, and never fires.
      const gone=(typeof PLATFORM!=='undefined'&&PLATFORM.os_events)||{};
      f=`<select data-trig="${i}" data-key="event" style="width:auto">
        ${['notification','file_change','login','idle'].map(x=>`<option ${c.event===x?'selected':''} ${gone[x]?'disabled':''} title="${esc(gone[x]||'')}">${x}${gone[x]?' — not on this machine':''}</option>`).join('')}</select>
      <input data-trig="${i}" data-key="match" value="${esc(c.match||'')}" placeholder="match…" style="width:110px">
      <input data-trig="${i}" data-key="path" value="${esc(c.path||'')}" placeholder="path…" style="width:110px">`
        +(gone[c.event]?`<div class="sub" style="flex-basis:100%;color:var(--warn,#f0b429)">${esc(gone[c.event])}</div>`:'');
    }
    else if(t.kind==='flow_done'){
      // Chaining, expressed in the OS: this flow starts when another one ends. The
      // list is every OTHER flow — a flow that followed itself would be a loop with
      // no exit, which the save refuses anyway.
      const others=(FLOWS_CACHE||[]).map(x=>x.name).filter(n=>n&&n!==FLOW_SEL);
      f=`<span class="sub">after</span>
      <select data-trig="${i}" data-key="flow" style="width:auto">
        <option value="">— pick a flow —</option>
        ${others.map(n=>`<option ${c.flow===n?'selected':''}>${esc(n)}</option>`).join('')}</select>
      <select data-trig="${i}" data-key="status" style="width:auto">
        ${['any','ok','failed'].map(x=>`<option ${c.status===x?'selected':''}>${x}</option>`).join('')}</select>
      <span class="sub">its output becomes this flow's input</span>`;
    }
    else f=`<span class="sub">a URL with its own secret is minted on save${t.secret?' (already minted)':''}</span>`;
    return `<div class="row" style="gap:5px;margin-bottom:5px;align-items:center">
      <span class="lbadge">${esc(t.kind)}</span>${f}
      <input data-trig="${i}" data-key="cooldown_secs" type="number" value="${t.cooldown_secs||60}" title="cooldown seconds" style="width:70px">
      <button onclick="flwCollect();flwDelTrigger(${i})">✕</button></div>`;
  }).join('');
  const mopts=['<option value="">inherit from control plane (OS default)</option>']
    .concat(FLW.models.map(m=>`<option value="${m.id}" ${d.model===m.id?'selected':''}>${esc(m.id)}</option>`)).join('');

  ov.innerHTML=`<div style="width:1060px;max-width:96vw;max-height:90vh;background:var(--bg2,#111419);
      border:1px solid var(--line,#232a35);border-radius:16px;padding:22px 24px;display:flex;gap:18px"
      onclick="event.stopPropagation()">
   <div style="flex:1.35;min-width:0;overflow:auto;max-height:82vh;padding-right:4px">
    <div class="sawh">${FLW.exists?'Edit':(FLW.draft?'Review this draft':'New flow')}</div>
    <div class="sawsub">A standing mission. The master orchestrator plans it, picks from the roster while it runs,
      and stitches what comes back. What it may touch and what starts it are part of this definition — saving writes
      the permissions, editing reconciles them.</div>
    ${FLW.draft?`<div class="provbox" style="margin:8px 0">
      <div class="sub">✦ Drafted by <b>${esc((FLW.draft.model||'').split('/').pop()||'the model')}</b>.
        Nothing has been created yet — change anything, then Save.</div>
      ${FLW.draft.notes?`<div class="sub" style="margin-top:4px">assumed: ${esc(FLW.draft.notes)}</div>`:''}
      ${(FLW.draft.warnings||[]).map(w=>`<div class="sub" style="color:var(--warn,#f59e0b)">⚠ ${esc(w)}</div>`).join('')}
      ${FLW.draft.request?`<button class="sawchip" style="margin-top:6px" onclick="flwDraftAgain()">✦ Draft again</button>`:''}
      </div>`:''}
    <label>Name</label><input id="flw-name" value="${esc(d.name)}" placeholder="e.g. vendor-digest" ${FLW.exists?'disabled':''}>
    <label>Mission — what it is for, in your own words</label>
    <textarea id="flw-mission" rows="3" placeholder="Summarise this week's vendor mentions and send me the top three.">${esc(d.mission||'')}</textarea>
    <label>Description (optional)</label><input id="flw-desc" value="${esc(d.description||'')}">
    <label>Orchestrator brain</label><select id="flw-model">${mopts}</select>

    <div class="sawgrp">Roster — the only agents it may use</div>
    <div style="max-height:180px;overflow:auto">${roster}</div>
    <button class="sawchip" style="margin-top:6px" onclick="flwNewAgent()">＋ New agent</button>
    <button class="sawchip" style="margin-top:6px" onclick="flwAiOpen()">✦ Change it with AI</button>

    <div class="sawgrp">What the roster may do (granted on save)</div>
    <input id="flw-q" placeholder="Search tools…" oninput="FLW.q=this.value;drawFLW()" value="${esc(FLW.q||'')}">
    <div style="max-height:170px;overflow:auto;margin:6px 0">${tl}</div>
    <div class="row" style="gap:8px">
      <div style="flex:1"><label>Web addresses it may fetch (one per line)</label>
        <textarea id="flw-net" rows="2" placeholder="https://api.example.com/*">${esc((p.net||[]).join('\n'))}</textarea></div>
      <div style="flex:1"><label>Memory</label>
        <select id="flw-mem" onchange="flwPreview()">${['none','read','read-space','read-write'].map(x=>
          `<option value="${x}" ${p.memory===x?'selected':''}>${x}</option>`).join('')}</select></div>
    </div>
    <div class="row" style="gap:8px">
      <div style="flex:1"><label>Files it may read</label><textarea id="flw-fsr" rows="2" placeholder="~/Documents/launch/*">${esc((p.fs_read||[]).join('\n'))}</textarea></div>
      <div style="flex:1"><label>Files it may write</label><textarea id="flw-fsw" rows="2">${esc((p.fs_write||[]).join('\n'))}</textarea></div>
    </div>
    <label>Skills it may load</label><div style="max-height:110px;overflow:auto">${skl}</div>

    <div class="sawgrp">What starts it</div>
    ${trigs||'<p class="mut">Nothing yet — it runs when you press Run.</p>'}
    <div class="row" style="gap:6px;flex-wrap:wrap">
      ${['cron','message','webhook','os_event','flow_done'].map(k=>
        `<button class="sawchip" onclick="flwCollect();flwAddTrigger('${k}')">＋ ${k}</button>`).join('')}
    </div>

    <div class="sawgrp">Where the answer goes</div>
    <div class="row" style="gap:6px;flex-wrap:wrap">${sinkBox}</div>
    <p class="mut" style="font-size:12px"><code>origin</code> answers wherever it was triggered from — a flow
      started from Telegram replies in that chat.</p>

    <div class="sawgrp">Limits &amp; trust</div>
    <div class="row" style="gap:8px">
      <div style="flex:1"><label>Autonomy cap</label><select id="flw-cap">
        ${['paranoid','balanced','full'].map(x=>`<option value="${x}" ${d.autonomy_cap===x?'selected':''}>${x}</option>`).join('')}</select></div>
      <div style="flex:1"><label>Max delegations</label><input id="flw-deleg" type="number" value="${d.max_delegations||12}"></div>
      <div style="flex:1"><label>Max steps</label><input id="flw-steps" type="number" value="${d.max_steps||24}"></div>
      <div style="flex:1"><label>Working seconds</label><input id="flw-secs" type="number" value="${d.max_seconds||1800}"></div>
    </div>
    <p class="mut" style="font-size:12px">Working seconds exclude time spent waiting for you to answer an approval.</p>
   </div>
   <div style="flex:1;min-width:300px;display:flex;flex-direction:column;gap:8px;max-height:82vh">
    <div class="sawgrp" style="margin-top:0">The flow</div>
    <div id="flw-chart" style="border:1px solid var(--line,#232a35);border-radius:10px;padding:6px;
      overflow-x:auto">${fgPredictSvg(d)}</div>
    <p class="mut" style="font-size:12px;margin:0">There are no steps to draw — the master picks who
      to call while it runs. This is who it may call, and it redraws as you change the roster.</p>
    <div class="sawgrp">Change it with AI</div>
    <textarea id="flw-ai" rows="2" placeholder="also send the result to Telegram · drop the validator · run it hourly instead"></textarea>
    <div class="row" style="gap:6px">
      <button class="save" style="margin:0;flex:0 0 120px" onclick="flwAiApply()">✦ Apply</button>
      <div class="grow"><span id="flw-ai-status" class="sub"></span></div>
    </div>
    <div id="flw-ai-diff" class="sub" style="overflow:auto;max-height:150px"></div>
    <div class="provbox" style="margin-top:auto"><div id="flw-preview" class="sub">…</div></div>
    <div class="row">
      <div class="grow"></div>
      <button onclick="FLW=null;drawFLW()">Cancel</button>
      <button class="save" style="margin:0;flex:0 0 130px" onclick="flwSave()">Save flow</button>
    </div>
   </div></div>`;
  flwPreview();
}
async function flwDraftAgain(){
  const req=(FLW.draft||{}).request||'';
  if(!req)return;
  const box=$('#flw-preview');
  if(box)box.innerHTML='drafting again…';
  let r;
  try{
    r=await apiJSON('/api/flows/compose',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({request:req})});
  }catch(e){
    if(box)box.innerHTML='<span style="color:var(--err,#f87171)">'+esc(e.message||String(e))+'</span>';
    return;
  }
  FLW=null;drawFLW();openFLW(null,r.draft);
}
function flwAiOpen(){const a=$('#flw-ai');if(a){a.focus();a.scrollIntoView({block:'center'})}}
/* What changed, in the words of the thing that changed — so an AI edit is reviewable rather
   than a form that silently rearranged itself. */
function flwDiff(before,after){
  const out=[];
  const names=o=>(o.roster||[]).map(r=>r.subagent||r);
  const add=(label,was,now)=>{
    const a=JSON.stringify(was||[]),b=JSON.stringify(now||[]);
    if(a!==b)out.push(label+': '+(was&&was.length?was.join(', '):'—')+' → '+(now&&now.length?now.join(', '):'—'));
  };
  if((before.mission||'')!==(after.mission||''))out.push('mission rewritten');
  add('roster',names(before),names(after));
  add('tools',(before.permissions||{}).tools,(after.permissions||{}).tools);
  add('net',(before.permissions||{}).net,(after.permissions||{}).net);
  add('files read',(before.permissions||{}).fs_read,(after.permissions||{}).fs_read);
  add('files written',(before.permissions||{}).fs_write,(after.permissions||{}).fs_write);
  if(((before.permissions||{}).memory)!==((after.permissions||{}).memory))
    out.push('memory: '+((before.permissions||{}).memory||'?')+' → '+((after.permissions||{}).memory||'?'));
  add('sinks',(before.sinks||[]).map(x=>x.kind),(after.sinks||[]).map(x=>x.kind));
  add('triggers',(before.triggers||[]).map(t=>t.kind),(after.triggers||[]).map(t=>t.kind));
  add('new agents',(before.new_agents||[]).map(a=>a.name),(after.new_agents||[]).map(a=>a.name));
  return out;
}
async function flwAiApply(){
  const ask=$('#flw-ai'),st=$('#flw-ai-status');
  const req=(ask&&ask.value||'').trim();
  if(!req)return toast('say what to change');
  flwCollect();
  const before=JSON.parse(JSON.stringify(FLW.d));
  if(st)st.innerHTML='thinking…';
  let r;
  try{
    r=await apiJSON('/api/flows/compose',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({request:req,current:FLW.d})});
  }catch(e){if(st)st.innerHTML='<span style="color:var(--err,#f87171)">'+esc(e.message||String(e))+'</span>';return}
  const dr=r.draft||{};
  // The name is yours, not the model's: an edit must never quietly fork into a new flow.
  const keepName=FLW.d.name;
  FLW.d=Object.assign(FLW.d,{...dr,name:keepName});
  FLW.d.permissions=Object.assign({tools:[],mcp:[],skills:[],net:[],fs_read:[],fs_write:[],
    memory:'read-space'},dr.permissions||{});
  FLW.d.new_agents=dr.new_agents||[];
  FLW.lastAsk=req;
  drawFLW();
  const changed=flwDiff(before,FLW.d);
  const box=$('#flw-ai-diff');
  if(box)box.innerHTML=(changed.length?'<b>changed:</b><br>'+changed.map(esc).join('<br>')
    :'<span class="mut">it did not change anything — try being more specific</span>')
    +((dr.warnings||[]).length?'<br><span style="color:var(--warn,#f59e0b)">⚠ '
      +esc(dr.warnings.join(' · '))+'</span>':'')
    +(dr.notes?'<br><span class="mut">'+esc(dr.notes)+'</span>':'');
  const st2=$('#flw-ai-status');
  if(st2)st2.innerHTML='<span class="mut">not saved yet — review, then Save flow</span>';
}
async function flwSave(){
  flwCollect();
  if(!FLW.d.name)return toast('give it a name');
  const r=await fetch('/api/flows',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(FLW.d)}).then(r=>r.json());
  if(r.error)return toast(r.error);
  const g=r.report.grants,t=r.report.triggers,made=r.report.agents_created||[];
  FLW=null;drawFLW();
  toast((made.length?`created ${made.join(', ')} · `:'')
    +`flow saved · ${g.added} permissions granted, ${g.revoked} revoked · ${t.added+t.updated} triggers`);
  refreshApp('fabric');
}

