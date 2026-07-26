/* ================= fabric app — subagents, workflows, observability ================= */
let fabTab='team';
async function renderFabric(body){
  if(fabTab==='team')return renderFabTeam(body);
  if(fabTab==='flows')return renderFabFlows(body);
  return renderFabRuns(body);
}
function fabTabs(){
  return `<div style="margin-bottom:12px">${segTabs('fab-tabs',['Subagents','Workflows','Observability'],
    fabTab==='team'?0:fabTab==='flows'?1:2,'fabSetTab')}</div>`;
}
function fabSetTab(i){fabTab=['team','flows','runs'][i];refreshApp('fabric')}
async function renderFabTeam(body){
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
let SAW=null;
const SAW_PRESETS={
  'Read-only':['fetch_url','read_file','list_dir','recall','kg_query','system_info'],
  'Research':['fetch_url','read_file','list_dir','recall','kg_query','save_report'],
  'Files & shell':['run_command','read_file','write_file','list_dir','system_info'],
  'Builder':['create_app','read_file','list_dir','fetch_url','system_info'],
};
async function openSAW(name){
  const [tools,skills,models]=await Promise.all([
    fetch('/api/tools').then(r=>r.json()).catch(()=>({tools:[]})),
    fetch('/api/skills').then(r=>r.json()).catch(()=>({skills:[]})),
    fetch('/api/models').then(r=>r.json()).catch(()=>({models:[]}))]);
  const ex=name?(window.__subagents||{})[name]:null;
  SAW={step:1,exists:!!ex,tools:tools.tools||[],skills:skills.skills||[],models:models.models||[],q:'',
    d:ex?{...ex,tools:[...(ex.tools||[])],skills:[...(ex.skills||[])]}
        :{name:'',soul:'',model:'',tools:[],skills:[],autonomy_cap:'balanced',max_steps:12,max_seconds:300,builtin:0,target:'local'}};
  drawSAW();
}
function drawSAW(){
  let ov=$('#saw-ov');
  if(!SAW){ov&&ov.remove();return}
  if(!ov){ov=document.createElement('div');ov.id='saw-ov';ov.style.cssText='position:fixed;inset:0;z-index:9998;background:rgba(5,7,9,.75);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center';
    ov.onclick=e=>{if(e.target===ov){SAW=null;drawSAW()}};document.body.appendChild(ov);}
  const d=SAW.d,st=SAW.step;
  const dot=n=>`<span style="width:8px;height:8px;border-radius:50%;display:inline-block;margin:0 3px;background:${n<=st?'var(--acc,#5eead4)':'var(--line,#333)'}"></span>`;
  let inner='';
  if(st===1){
    const opts=['<option value="">inherit from control plane (OS default)</option>']
      .concat(SAW.models.map(m=>`<option value="${m.id}" ${d.model===m.id?'selected':''}>${esc(m.id)}</option>`)).join('');
    inner=`<div class="sawh">${SAW.exists?'Edit':'New'} subagent</div>
      <div class="sawsub">A specialist team member with its own persona, model, and tools. In chat you'll address it as <code>@name</code>.</div>
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
      <button onclick="SAW=null;drawSAW()">Cancel</button>
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
  await fetch('/api/subagents',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});
  SAW=null;drawSAW();toast('subagent saved — address it in chat with @'+d.name);refreshApp('fabric');
}
function testSubagent(name){
  // test runs live in the chat: open it with the mention prefilled
  openApp('chat');
  setTimeout(()=>{const i=$('#input');if(i){i.value='@'+name+' ';i.focus();i.dispatchEvent(new Event('input'))}},250);
  toast('type the task after @'+name+' — the run streams right here and lands in Observability');
}

function wfLayers(steps){
  const done=new Set(),layers=[];let rem=[...steps];
  while(rem.length){
    let layer=rem.filter(s=>(s.depends_on||[]).every(d=>done.has(d)));
    if(!layer.length)layer=[rem[0]];
    layer.forEach(s=>done.add(s.id));rem=rem.filter(s=>!layer.includes(s));layers.push(layer);
  }return layers;
}
function wfSvg(wf,stepStatus){
  const layers=wfLayers(wf.steps||[]);
  const BW=158,BH=46,GX=200,GY=64,pos={};
  layers.forEach((layer,c)=>layer.forEach((s,r)=>pos[s.id]={x:16+c*GX,y:14+r*GY,s}));
  const H=Math.max(...layers.map(l=>l.length))*GY+22, W=16+layers.length*GX;
  const col=st=>st==='ok'?'var(--ok,#34d399)':st==='running'||st==='start'?'var(--acc,#5eead4)':(st==='error'||st==='timeout')?'var(--err,#f87171)':'var(--line,#333)';
  let lines='',boxes='';
  (wf.steps||[]).forEach(s=>{(s.depends_on||[]).forEach(d=>{const a=pos[d],b=pos[s.id];if(!a||!b)return;
    lines+=`<path d="M${a.x+BW} ${a.y+BH/2} C ${a.x+BW+24} ${a.y+BH/2}, ${b.x-24} ${b.y+BH/2}, ${b.x} ${b.y+BH/2}" fill="none" stroke="rgba(138,148,166,.5)" stroke-width="1.5" marker-end="url(#arr)"/>`;})});
  Object.values(pos).forEach(({x,y,s})=>{const st=(stepStatus||{})[s.id]||'';
    boxes+=`<g><rect x="${x}" y="${y}" rx="9" width="${BW}" height="${BH}" fill="rgba(255,255,255,.04)" stroke="${col(st)}" stroke-width="1.6">${st==='running'||st==='start'?'<animate attributeName="stroke-opacity" values="1;.3;1" dur="1.2s" repeatCount="indefinite"/>':''}</rect>
      <text x="${x+10}" y="${y+19}" fill="var(--txt,#e6ebf2)" font-size="12" font-weight="600">${esc(s.name||s.id)}</text>
      <text x="${x+10}" y="${y+35}" fill="var(--dim,#8a94a6)" font-size="10">${esc(s.subagent)}${s.model?' · '+esc(s.model.split('/').pop()):''}${st?' · '+st:''}</text></g>`;});
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-height:${H+10}px"><defs><marker id="arr" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 z" fill="rgba(138,148,166,.7)"/></marker></defs>${lines}${boxes}</svg>`;
}
async function renderFabFlows(body){
  const [wfs,runs]=await Promise.all([fetch('/api/workflows').then(r=>r.json()),
                                      fetch('/api/fabric/runs?limit=30').then(r=>r.json())]);
  // live step status per workflow: read events of its latest run
  const latest={};runs.runs.filter(r=>r.kind==='workflow').forEach(r=>{if(!latest[r.ref])latest[r.ref]=r});
  const statuses={};
  await Promise.all(Object.entries(latest).map(async([name,run])=>{
    try{const d=await fetch('/api/fabric/runs/'+run.id).then(r=>r.json());
      const st={};d.events.forEach(e=>{if(e.type==='step'&&e.payload.wf_step)st[e.payload.wf_step]=e.payload.status});
      statuses[name]={st,run};}catch(e){}}));
  const blocks=wfs.workflows.map(wf=>{
    const live=statuses[wf.name]||{};const run=live.run;
    return `<div class="provbox"><div class="ptitle">${esc(wf.name)} ${wf.builtin?'<span class="mut">· built-in</span>':''}
        <span style="float:right">${run?`<span class="mut">last: ${esc(run.status)}${run.tokens_out?' · '+run.tokens_out+' tok':''}</span>`:''}
        <button title="edit JSON" onclick="editWorkflow('${esc(wf.name)}')">✎</button>
        <button onclick="delWorkflow('${wf.id}')">✕</button></span></div>
      <div class="sub" style="margin:2px 0 8px">${esc(wf.description||'')}</div>
      ${wfSvg(wf,live.st)}
      <div class="row" style="margin-top:6px"><input id="wf-in-${wf.id}" placeholder="input for this workflow…">
        <button class="save" style="margin:0;flex:0 0 70px" onclick="runWorkflow('${esc(wf.name)}','${wf.id}')">Run</button></div>
      ${run&&run.status==='ok'&&run.output?`<details style="margin-top:6px"><summary class="mut">last output</summary><pre style="white-space:pre-wrap;font-size:11.5px;max-height:180px;overflow:auto">${esc(run.output.slice(0,3000))}</pre></details>`:''}
      ${run&&run.fault?`<div class="sub" style="color:var(--err,#f87171)">fault: ${esc(run.fault.slice(0,200))}</div>`:''}</div>`;
  }).join('')||'<p class="mut">No workflows yet.</p>';
  body.innerHTML=`<div class="pad">${fabTabs()}${blocks}
    <div class="ptitle" style="margin-top:10px">New / edit workflow (JSON)</div>
    <div class="row"><input id="wfj-name" placeholder="name"><input id="wfj-desc" placeholder="description"></div>
    <textarea id="wfj-steps" rows="5" placeholder='[{"id":"draft","name":"Draft","subagent":"writer","prompt":"{input}","depends_on":[]},{"id":"validate","subagent":"validator","model":"anthropic/claude-sonnet-5","prompt":"Validate: {draft}","depends_on":["draft"]}]'></textarea>
    <button class="save" onclick="saveWorkflow()">Save workflow</button>
    <p class="mut">Each step runs in its own data plane. <code>{input}</code> and <code>{stepId}</code> substitute into prompts; <code>model</code> per step overrides the subagent (e.g. generate on Ollama, validate on Claude).</p></div>`;
  window.__workflows=Object.fromEntries(wfs.workflows.map(w=>[w.name,w]));
}
function editWorkflow(name){const w=(window.__workflows||{})[name];if(!w)return;
  $('#wfj-name').value=w.name;$('#wfj-desc').value=w.description||'';
  $('#wfj-steps').value=JSON.stringify(w.steps,null,1);}
async function saveWorkflow(){
  const name=$('#wfj-name').value.trim();if(!name)return toast('name required');
  let steps;try{steps=JSON.parse($('#wfj-steps').value)}catch(e){return toast('steps: invalid JSON')}
  const old=(window.__workflows||{})[name]||{};
  await fetch('/api/workflows',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name,description:$('#wfj-desc').value,steps,builtin:old.builtin||0})});
  toast('workflow saved');refreshApp('fabric');}
async function delWorkflow(id){await fetch('/api/workflows/'+id,{method:'DELETE'});refreshApp('fabric');}
async function runWorkflow(name,id){
  const input=$('#wf-in-'+id).value.trim();if(!input)return toast('give the workflow an input');
  await fetch('/api/workflows/'+encodeURIComponent(name)+'/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({input})});
  toast('workflow running');}

async function renderFabRuns(body){
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
let fabRefreshT=0;
function fabricLiveRefresh(){
  const now=Date.now();
  if(now-fabRefreshT<800)return;
  fabRefreshT=now;
  if(WM.wins.get('fabric'))refreshApp('fabric');
}

