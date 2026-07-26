/* ================= token analytics app ================= */
async function renderTokens(body){
  const d=await (await fetch('/api/analytics/tokens')).json();
  const fmt=n=>n>=1e6?(n/1e6).toFixed(2)+'M':n>=1e3?(n/1e3).toFixed(1)+'k':(''+n);
  const t=d.total||{in:0,out:0,turns:0};
  const models=Object.entries(d.by_model||{}).sort((a,b)=>(b[1].in+b[1].out)-(a[1].in+a[1].out));
  const maxM=Math.max(1,...models.map(([,v])=>v.in+v.out));
  const days=(d.by_day||[]).slice(-14);
  const maxD=Math.max(1,...days.map(x=>x.in+x.out));
  body.innerHTML=`<div class="pad">
    <div class="tmgrid">
      <div class="stat"><div class="lbl">Total tokens</div><div class="val">${fmt(t.in+t.out)}</div></div>
      <div class="stat"><div class="lbl">Input</div><div class="val">${fmt(t.in)}</div></div>
      <div class="stat"><div class="lbl">Output</div><div class="val">${fmt(t.out)}</div></div>
    </div>
    <div class="tmsec">By model · ${t.turns} turns</div>
    ${models.length?models.map(([m,v])=>`<div style="margin-bottom:9px">
      <div style="display:flex;justify-content:space-between;font-size:12.5px"><span>${esc(m.split('/').pop())}</span>
        <span class="mut">${fmt(v.in+v.out)} · ${v.turns}t</span></div>
      <div class="bar"><i style="width:${(v.in+v.out)/maxM*100}%"></i></div></div>`).join('')
      :'<p class="mut">No usage yet. Token counts are recorded per turn (local models report via Ollama; cloud models via their usage API).</p>'}
    <div class="tmsec">Last ${days.length} days</div>
    <div style="display:flex;align-items:flex-end;gap:5px;height:90px;padding:6px 0">
      ${days.length?days.map(x=>`<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;height:100%">
        <div style="flex:1;width:100%;display:flex;align-items:flex-end"><div title="${x.day}: ${fmt(x.in+x.out)}" style="width:100%;border-radius:4px 4px 0 0;background:linear-gradient(var(--acc),var(--acc2));height:${(x.in+x.out)/maxD*100}%;min-height:2px"></div></div>
        <div style="font-size:9px;color:var(--dim2)">${x.day.slice(5)}</div></div>`).join(''):'<p class="mut">no daily data yet</p>'}
    </div>
  </div>`;
}

/* ================= snapshots app ================= */
async function renderSnapshots(body){
  const d=await (await fetch('/api/snapshots')).json();
  const snaps=d.snapshots||[];
  const items=snaps.map(s=>`<div class="item" data-f="${esc(s.label||('Snapshot '+s.id))}">
      <div class="grow"><b>${esc(s.label||('Snapshot '+s.id))}</b>
        <div class="sub">${new Date((s.created_at||s.id)*1000).toLocaleString()}${s.has_source?' · includes source':''}</div></div>
      <button class="endbtn" onclick="snapRestore('${s.id}')">↩ Restore</button>
      <button onclick="snapDel('${s.id}')">✕</button></div>`).join('');
  const pb=panelShell(body,{
    title:'Snapshots',
    sub:`${snaps.length} restore point${snaps.length===1?'':'s'}`,
    search:{id:'snap-q',placeholder:'Search snapshots…'},
  });
  pb.innerHTML=`
    <div class="row"><input id="snap-label" placeholder="label (e.g. before WhatsApp experiment)">
      <button class="pact" style="flex:0 0 130px" onclick="snapCreate()">Snapshot now</button></div>
    <p class="mut" style="margin:8px 0 14px">A snapshot saves your settings, data (apps, widgets, memory), and the OS source code. Restoring rolls everything back and restarts.</p>
    ${items||emptyBox('No snapshots yet','Take one before risky changes — especially before letting the agent modify its own code.')}`;
}
async function snapCreate(){
  const label=$('#snap-label').value.trim();
  await fetch('/api/snapshots',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label})});
  toast('snapshot saved');refreshApp('snapshots');
}
async function snapRestore(id){
  if(!await osConfirm('Restore this snapshot?','Current config, data, and source will be replaced and AgentOS will restart.',{danger:true,confirmText:'Restore'}))return;
  await fetch('/api/snapshots/'+id+'/restore',{method:'POST'});
  toast('↩ restoring — reconnecting…');
}
async function snapDel(id){await fetch('/api/snapshots/'+id,{method:'DELETE'});refreshApp('snapshots')}

/* ================= policies app ================= */
async function renderPolicies(body){
  await loadConfig();
  const pol=cfg.policies||[];
  const items=pol.map((p,i)=>`<div class="item" data-f="${esc(p.action+' '+p.match)}">
      <span class="badge ${p.action==='allow'?'ok':'err'}">${p.action}</span>
      <div class="grow" style="font-family:var(--mono);font-size:12.5px">${esc(p.match)}</div>
      <button onclick="delPolicy(${i})">✕</button></div>`).join('');
  const pb=panelShell(body,{
    title:'Policies',
    sub:`${pol.length} rule${pol.length===1?'':'s'} — what the agent may do without asking`,
    search:{id:'pol-q',placeholder:'Search rules…'},
  });
  pb.innerHTML=`
    ${items||emptyBox('No policies yet','Policies decide what the agent may do without asking — or must never do — matched against the tool + command. The quickest way to create one: click "Always allow" on any approval prompt.')}
    <div class="sect">New rule</div>
    <div class="row">
      <select id="pol-act" style="flex:0 0 110px"><option value="allow">✓ allow</option><option value="deny">✕ deny</option></select>
      <input id="pol-match" placeholder="pattern, e.g. run_command git *   or   mcp_playwright_*">
      <button class="pact" style="flex:0 0 80px" onclick="addPolicyUI()">Add</button>
    </div>
    <p class="mut" style="margin-top:10px">Patterns use * wildcards and match against <code>&lt;tool&gt; &lt;command/args&gt;</code>.
    <b>deny</b> rules win over allow; hard-blocked commands (like wiping the disk) stay blocked regardless.</p>`;
}
async function addPolicy(action,match){
  await loadConfig();
  const pol=cfg.policies||[];
  pol.push({action,match});
  await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({policies:pol})});
  refreshApp('policies');
}
function addPolicyUI(){
  const m=$('#pol-match').value.trim();if(!m)return toast('enter a pattern');
  addPolicy($('#pol-act').value,m);
}
async function delPolicy(i){
  await loadConfig();
  const pol=cfg.policies||[];pol.splice(i,1);
  await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({policies:pol})});
  refreshApp('policies');
}

