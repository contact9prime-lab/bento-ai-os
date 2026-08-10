/* ================= permissions app: the policy console ================= */
let PERM={tab:'map',sel:null,q:'',showRevoked:false,grants:[],apps:[],opts:{principals:[],actions:[],resources:{}},att:null,_attPs:[],_mapPs:[],held:[],qhistory:[]};
const PERM_FAMS=[['Tools','tool.'],['MCP','mcp.'],['Skills','skill.'],['Models','model.'],['Files','fs.'],['Net','net.'],['Memory','memory.','kg.'],['Agents','agent.'],['App data','app.data.']];
function globMatch(pat,val){pat=(pat==null||pat==='')?'*':String(pat);
  return new RegExp('^'+pat.split('*').map(s=>s.replace(/[.+?^${}()|[\]\\]/g,'\\$&')).join('.*')+'$').test(val||'')}
function permFamOf(action){if(action==='*')return 'Full access';if(action==='legacy policy')return 'Legacy rules';
  for(const f of PERM_FAMS)for(let i=1;i<f.length;i++)if(action.startsWith(f[i]))return f[0];return 'Other'}
async function renderPermissions(body){
  try{PERM.grants=(await (await fetch('/api/grants'+(PERM.showRevoked?'?all=1':''))).json()).grants||[]}catch(e){PERM.grants=[]}
  try{PERM.opts=await (await fetch('/api/policy/options')).json()}catch(e){}
  try{PERM.apps=(await (await fetch('/api/apps')).json()).apps||[]}catch(e){PERM.apps=[]}
  try{const q=await (await fetch('/api/quarantine?history=1')).json();
      PERM.held=q.held||[];PERM.qhistory=(q.history||[]).filter(r=>r.released_at)}catch(e){PERM.held=[]}
  await loadConfig();
  const pending=PERM.apps.filter(a=>(a.manifest_status||'none')==='proposed').length;
  body.innerHTML=`<div class="apptop" style="gap:6px">
    ${[['map','Policy map'],['grants','All grants'],['review','Review'+(pending?' ('+pending+')':'')],
       ['quarantine','Quarantine'+(PERM.held.length?' ('+PERM.held.length+')':'')],['attach','＋ Attach']].map(([t,l])=>`<button class="endbtn perm-tab${PERM.tab===t?' on':''}" data-t="${t}" ${(t==='review'&&pending)||(t==='quarantine'&&PERM.held.length)?'style="color:var(--err,#f87171)"':''}>${l}</button>`).join('')}
    <input id="perm-q" placeholder="search apps, agents, rules…" style="flex:1;max-width:250px;margin-left:auto" value="${esc(PERM.q)}">
  </div>
  <div id="perm-body" style="flex:1;overflow-y:auto;padding:12px 14px"></div>`;
  body.querySelectorAll('.perm-tab').forEach(b=>b.onclick=()=>{PERM.tab=b.dataset.t;renderPermissions(body)});
  $('#perm-q').oninput=e=>{PERM.q=e.target.value;permBody()};
  permBody();
}
function permBody(){
  const box=$('#perm-body');if(!box)return;
  ({map:permMap,grants:permGrantsView,review:permReview,quarantine:permQuarantine,
    attach:permAttachView}[PERM.tab]||permMap)(box);
}
function permPrincipals(){
  const map=new Map();
  (PERM.opts.principals||[]).forEach(p=>map.set(p.kind+':'+p.id,{...p,label:p.label||p.id||p.kind}));
  PERM.grants.forEach(g=>{if(g.principal_kind==='user')return;
    const k=g.principal_kind+':'+(g.principal_id||'');
    if(!map.has(k))map.set(k,{kind:g.principal_kind,id:g.principal_id||'',label:permPrincipalLabel(g.principal_kind,g.principal_id)})});
  const out=[...map.values()].map(p=>({...p,
    grants:PERM.grants.filter(g=>!g.revoked_at&&g.principal_kind===p.kind&&globMatch(g.principal_id||'*',p.id))}));
  // the system principal: the main agent acting as you — legacy policies live here
  out.unshift({kind:'user',id:'',label:'System — main agent',system:true,
    grants:[...PERM.grants.filter(g=>!g.revoked_at&&g.principal_kind==='user'),
            ...((cfg&&cfg.policies)||[]).map((p,i)=>({id:'legacy:'+i,action:'legacy policy',
              resource:p.match,effect:p.action==='deny'?'deny':'allow',source:'Policies app',readonly:true}))]});
  return out;
}
function permMap(box){
  const q=PERM.q.toLowerCase();
  const ps=permPrincipals().filter(p=>!q||p.label.toLowerCase().includes(q)||p.kind.includes(q));
  PERM._mapPs=ps;
  const famChip=(p,f)=>{
    const gs=p.grants.filter(g=>permFamOf(g.action)===f);
    if(!gs.length)return '';
    const d=gs.filter(g=>g.effect==='deny').length,a=gs.length-d;
    const col=d&&a?'#f2c94c':d?'var(--err,#f87171)':'var(--ok,#5eead4)';
    return `<span style="font-size:10px;padding:2px 7px;border-radius:9px;border:1px solid ${col};color:${col}">${esc(f)} ${gs.length}</span>`;
  };
  const fams=['Full access','Legacy rules',...PERM_FAMS.map(f=>f[0]),'Other'];
  box.innerHTML=`<p class="mut" style="margin-bottom:10px">Who may do what, at a glance. Click a card for its policy map — toggle any permission between allow/deny, or revoke it.</p>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px">
    ${ps.map((p,i)=>{
      const full=p.grants.some(g=>g.action==='*'&&g.resource==='*'&&g.effect!=='deny');
      const sel=PERM.sel===p.kind+':'+p.id;
      const st=p.status==='proposed'?'<span class="badge err">review pending</span>':p.status==='approved'?'<span class="badge ok">manifest</span>':'';
      return `<div class="perm-card" data-i="${i}" style="cursor:pointer;background:var(--card,#171b22);border:1px solid ${sel?'var(--acc,#5eead4)':'var(--line,#232a35)'};border-radius:12px;padding:12px">
      <div style="display:flex;align-items:center;gap:9px;margin-bottom:8px">
        <span style="width:30px;height:30px;border-radius:8px;background:${tileBg(p.id||p.kind)};display:inline-flex;align-items:center;justify-content:center;font-weight:800;flex:0 0 30px">${esc((p.label[0]||'?').toUpperCase())}</span>
        <div style="min-width:0"><b style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(p.label)}</b>
        <div class="mut" style="font-size:10.5px">${esc(p.kind)} · ${p.grants.length} rule${p.grants.length===1?'':'s'}</div></div>
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:4px">${full?'<span class="badge err">FULL ACCESS</span>':''}${st}
        ${fams.map(f=>famChip(p,f)).join('')||'<span class="mut" style="font-size:11px">no rules — every capability asks first</span>'}</div>
    </div>`}).join('')||'<p class="mut">no apps or agents yet</p>'}
  </div>
  <div id="perm-chart" style="margin-top:18px"></div>`;
  box.querySelectorAll('.perm-card').forEach(c=>c.onclick=()=>{
    const p=PERM._mapPs[+c.dataset.i];const k=p.kind+':'+p.id;
    PERM.sel=PERM.sel===k?null:k;permMap(box);
  });
  const selP=ps.find(p=>PERM.sel===p.kind+':'+p.id);
  if(selP)permChartInto($('#perm-chart'),selP);
}
function permChartInto(el,p){
  if(!el)return;
  const fams={};
  p.grants.forEach(g=>{const f=permFamOf(g.action);(fams[f]=fams[f]||[]).push(g)});
  const chip=g=>{
    const col=g.effect==='deny'?'var(--err,#f87171)':'var(--ok,#5eead4)';
    return `<div class="pm-chip" data-eff="${g.effect}" style="display:flex;align-items:center;gap:8px;background:var(--card,#171b22);border:1px solid ${col};border-radius:9px;padding:6px 10px;margin-bottom:5px;max-width:560px">
      ${g.readonly
        ?`<span style="color:${col};font-weight:700;font-size:12px;padding:0 4px">${g.effect==='deny'?'✕ deny':'✓ allow'}</span>`
        :`<button title="click to flip to ${g.effect==='deny'?'allow':'deny'}" onclick="permToggle('${g.id}','${g.effect==='deny'?'allow':'deny'}')" style="border:none;background:transparent;color:${col};font-weight:700;padding:0 4px;font-size:12px;cursor:pointer">${g.effect==='deny'?'✕ deny':'✓ allow'}</button>`}
      <div class="grow" style="font-family:var(--mono);font-size:12px;word-break:break-all">${esc(g.action)} · ${esc(g.resource)}</div>
      <span class="badge" title="${esc(g.note||'')}">${esc(g.source||'user')}</span>
      ${g.readonly?'':permSurfBadge(g)}
      ${g.readonly?`<button class="endbtn" style="font-size:10px" onclick="openApp('policies')">edit</button>`
                  :`<button onclick="permRevoke('${g.id}')" title="revoke">✕</button>`}</div>`;
  };
  el.innerHTML=`<div class="tmsec" style="margin:4px 0 10px">Policy map — ${esc(p.label)}</div>
  <div id="pm-wrap" style="position:relative;display:flex;gap:80px;align-items:flex-start">
    <svg id="pm-svg" style="position:absolute;inset:0;width:100%;height:100%;pointer-events:none"></svg>
    <div id="pm-left" style="flex:0 0 190px;background:var(--card,#171b22);border:1px solid var(--line,#232a35);border-radius:12px;padding:14px;text-align:center;position:relative;z-index:1">
      <span style="width:44px;height:44px;border-radius:11px;background:${tileBg(p.id||p.kind)};display:inline-flex;align-items:center;justify-content:center;font-weight:800;font-size:18px">${esc((p.label[0]||'?').toUpperCase())}</span>
      <div style="margin-top:8px"><b>${esc(p.label)}</b></div><div class="mut" style="font-size:11px">${esc(p.kind)}</div>
    </div>
    <div style="flex:1;position:relative;z-index:1">
      ${Object.keys(fams).length?Object.entries(fams).map(([f,gs])=>`<div style="margin-bottom:12px">
        <div class="mut" style="font-size:10.5px;letter-spacing:.6px;text-transform:uppercase;margin-bottom:5px">${esc(f)}</div>
        ${gs.map(chip).join('')}</div>`).join('')
      :'<p class="mut">No rules yet — every capability this principal touches will raise a consent prompt. Use ＋ Attach to pre-approve or block things.</p>'}
      ${p.system?'<p class="mut" style="font-size:11px;margin-top:8px">Hard-blocked commands (disk wipes, shutdown) stay blocked regardless of any rule. Legacy rules apply globally and are edited in the Policies app.</p>':''}
    </div>
  </div>`;
  requestAnimationFrame(()=>{
    const svg=$('#pm-svg'),wrap=$('#pm-wrap'),src=$('#pm-left');
    if(!svg||!wrap||!src)return;
    const wr=wrap.getBoundingClientRect(),sr=src.getBoundingClientRect();
    const x1=sr.right-wr.left,y1=sr.top+sr.height/2-wr.top;
    svg.setAttribute('viewBox',`0 0 ${wr.width} ${wr.height}`);
    svg.innerHTML=[...wrap.querySelectorAll('.pm-chip')].map(ch=>{
      const r=ch.getBoundingClientRect();
      const x2=r.left-wr.left,y2=r.top+r.height/2-wr.top;
      const col=ch.dataset.eff==='deny'?'#f87171':'#5eead4';
      return `<path d="M${x1},${y1} C${x1+50},${y1} ${x2-50},${y2} ${x2},${y2}" fill="none" stroke="${col}" stroke-width="1.5" opacity=".5"/>`;
    }).join('');
  });
}
function permGrantsView(box){
  const q=PERM.q.toLowerCase();
  const gs=PERM.grants.filter(g=>{
    const s=(permPrincipalLabel(g.principal_kind,g.principal_id)+' '+g.action+' '+g.resource+' '+(g.note||'')+' '+(g.source||'')).toLowerCase();
    return !q||s.includes(q)});
  box.innerHTML=`<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
    <span class="mut">${gs.length} rule${gs.length===1?'':'s'} — click an effect pill to flip allow/deny</span>
    <label style="margin-left:auto;display:flex;align-items:center;gap:6px;font-size:12px;color:var(--dim);cursor:pointer"><input type="checkbox" id="perm-rev" ${PERM.showRevoked?'checked':''}> show revoked</label></div>
  ${gs.map(g=>{
    const dead=!!g.revoked_at;
    const lbl=permPrincipalLabel(g.principal_kind,g.principal_id);
    return `<div class="item" style="${dead?'opacity:.45':''}">
      <span style="width:22px;height:22px;border-radius:6px;background:${tileBg(g.principal_id||g.principal_kind)};flex:0 0 22px;display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:700">${esc((lbl.replace(/^[a-z]+ "/,'')[0]||'?').toUpperCase())}</span>
      <div class="grow" style="min-width:0"><b style="font-size:12.5px">${esc(lbl)}</b>
        <div style="font-family:var(--mono);font-size:12px;word-break:break-all">${esc(g.action)} · ${esc(g.resource)}</div>
        ${g.note?`<div class="mut" style="font-size:11px">${esc(g.note)}</div>`:''}</div>
      <span class="badge">${esc(g.source||'user')}</span>
      ${dead?'<span class="badge err">revoked</span>'
        :`${permSurfBadge(g)}
         <button class="badge ${g.effect==='deny'?'err':'ok'}" style="cursor:pointer" title="flip to ${g.effect==='deny'?'allow':'deny'}" onclick="permToggle('${g.id}','${g.effect==='deny'?'allow':'deny'}')">${g.effect}</button>
         <button onclick="permRevoke('${g.id}')" title="revoke">✕</button>`}
    </div>`}).join('')||'<p class="mut">nothing matches</p>'}`;
  const cb=$('#perm-rev');if(cb)cb.onchange=e=>{PERM.showRevoked=e.target.checked;refreshApp('permissions')};
}
function permReview(box){
  const q=PERM.q.toLowerCase();
  const apps=PERM.apps.filter(a=>!q||(a.name||'').toLowerCase().includes(q));
  box.innerHTML=`<p class="mut" style="margin-bottom:10px">Each app's declared permissions. Review pending proposals, or (re)scan an app's source to draft its manifest.</p>
  ${apps.map(a=>{
    const st=a.manifest_status||'none';
    const legacy=PERM.grants.some(g=>!g.revoked_at&&g.principal_kind==='app'&&g.principal_id===a.id&&g.source==='legacy');
    const n=PERM.grants.filter(g=>!g.revoked_at&&g.principal_kind==='app'&&g.principal_id===a.id).length;
    const stBadge=st==='approved'?'<span class="badge ok">approved</span>':st==='proposed'?'<span class="badge err">awaiting review</span>':'<span class="badge">no manifest</span>';
    return `<div class="item">
      <span style="width:26px;height:26px;border-radius:7px;background:${tileBg(a.id)};flex:0 0 26px;display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:700">${esc((a.name[0]||'?').toUpperCase())}</span>
      <div class="grow" style="min-width:0"><b>${esc(a.name)}</b> ${stBadge} ${legacy?'<span class="badge err">legacy full access</span>':''}
        <div class="mut" style="font-size:11px">${n} active rule${n===1?'':'s'}${a.description?' · '+esc(a.description):''}</div></div>
      ${st==='proposed'?`<button class="save" style="margin:0" onclick="reviewManifest('${a.id}')">Review</button>`:''}
      <button class="endbtn" onclick="permRescan('${a.id}')">${st==='none'?'Scan':'Rescan'}</button>
      <button class="endbtn" onclick="window.open('/api/apps/${a.id}/export')">Export</button>
    </div>`}).join('')||'<p class="mut">no apps installed</p>'}`;
}
async function permRescan(aid){
  const r=await fetch('/api/apps/'+aid+'/manifest/propose',{method:'POST'});
  if(r.ok){toast('manifest drafted from the app source');reviewManifest(aid)}else toast('scan failed');
}
function permAttachView(box){
  const o=PERM.opts;
  PERM.att=PERM.att||{p:null,action:'tool.use',res:new Set(),effect:'allow',surf:new Set()};
  PERM.att.surf=PERM.att.surf||new Set();
  const att=PERM.att,q=PERM.q.toLowerCase();
  const ps=(o.principals||[]).filter(p=>!q||(p.label||'').toLowerCase().includes(q));
  PERM._attPs=ps;
  const resOpts=(o.resources&&o.resources[att.action])||[];
  box.innerHTML=`<p class="mut" style="margin-bottom:10px">Attach a policy by picking — nothing to type blind. Choose who, what capability, and which resources.</p>
  <div style="display:grid;grid-template-columns:250px 1fr 1.4fr;gap:14px;align-items:start">
    <div><div class="tmsec" style="margin:0 0 6px">1 · Who</div>
      <div style="max-height:360px;overflow-y:auto">${ps.map((p,i)=>`<div class="item" style="cursor:pointer;${att.p&&att.p.kind===p.kind&&att.p.id===p.id?'outline:1px solid var(--acc,#5eead4)':''}" onclick="permAttSel(${i})">
        <span style="width:22px;height:22px;border-radius:6px;background:${tileBg(p.id)};flex:0 0 22px;display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:700">${esc((p.label[0]||'?').toUpperCase())}</span>
        <div class="grow" style="min-width:0"><span style="font-size:12.5px">${esc(p.label)}</span><div class="mut" style="font-size:10px">${esc(p.kind)}</div></div></div>`).join('')||'<p class="mut">none yet</p>'}</div></div>
    <div><div class="tmsec" style="margin:0 0 6px">2 · Capability</div>
      ${(o.actions||[]).map(a=>`<button class="endbtn" style="margin:0 4px 4px 0;${att.action===a?'border-color:var(--acc,#5eead4);color:var(--acc,#5eead4)':''}" onclick="PERM.att.action='${a}';PERM.att.res=new Set();permBody()">${a}</button>`).join('')}
      <div style="display:flex;gap:8px;margin-top:14px;align-items:center">
        <span class="mut" style="font-size:12px">Effect:</span>
        <button class="endbtn" onclick="PERM.att.effect=PERM.att.effect==='allow'?'deny':'allow';permBody()" style="color:${att.effect==='deny'?'var(--err,#f87171)':'var(--ok,#5eead4)'};border-color:${att.effect==='deny'?'var(--err,#f87171)':'var(--ok,#5eead4)'}">${att.effect==='deny'?'✕ deny':'✓ allow'}</button>
        <span class="mut" style="font-size:11px">${att.effect==='deny'?'blocks even things allowed elsewhere':'runs without asking'}</span>
      </div>
      <div style="margin-top:14px">
        <span class="mut" style="font-size:12px">IO gates <span style="font-size:10px">(none picked = every surface)</span>:</span><div style="margin-top:5px">
        ${PERM_SURFACES.map(s=>`<button class="endbtn" style="margin:0 4px 4px 0;${att.surf.has(s)?'border-color:var(--acc2,#22d3ee);color:var(--acc2,#22d3ee)':''}" onclick="PERM.att.surf.has('${s}')?PERM.att.surf.delete('${s}'):PERM.att.surf.add('${s}');permBody()">${s}</button>`).join('')}</div>
        <span class="mut" style="font-size:11px">the rule only applies to calls arriving via these surfaces — elsewhere the IO is denied and logged</span>
      </div></div>
    <div><div class="tmsec" style="margin:0 0 6px">3 · Resources <span class="mut">(${att.res.size} picked)</span></div>
      <div style="max-height:300px;overflow-y:auto">${resOpts.map(r=>`<label class="item" style="cursor:pointer;display:flex;gap:8px;align-items:flex-start">
        <input type="checkbox" ${att.res.has(r.value)?'checked':''} onchange="permAttRes(this.dataset.v,this.checked)" data-v="${esc(r.value)}" style="margin-top:3px;accent-color:var(--acc,#5eead4)">
        <div class="grow" style="min-width:0"><div style="font-size:12.5px">${esc(r.label)}</div><div class="mut" style="font-family:var(--mono);font-size:10.5px;word-break:break-all">${esc(r.value)}</div></div></label>`).join('')||'<p class="mut">nothing available for this capability yet — connect servers / install skills first, or use a custom pattern below</p>'}</div>
      <input id="att-custom" placeholder="custom pattern (optional), e.g. tool:run_command git *" style="width:100%;margin-top:8px">
      <button class="save" style="margin-top:10px" onclick="permAttachGo()">Attach ${att.res.size?att.res.size+' rule'+(att.res.size===1?'':'s'):'rule'}${att.p?' to '+esc(att.p.label):''}</button>
    </div>
  </div>`;
}
function permAttSel(i){PERM.att.p=PERM._attPs[i];permBody()}
function permAttRes(v,on){if(on)PERM.att.res.add(v);else PERM.att.res.delete(v);permBody()}
async function permAttachGo(){
  const att=PERM.att;
  if(!att.p)return toast('pick who first (step 1)');
  const custom=($('#att-custom')?.value||'').trim();
  const resources=[...att.res];if(custom)resources.push(custom);
  if(!resources.length)return toast('pick at least one resource (step 3)');
  const surfaces=att.surf&&att.surf.size?[...att.surf].join(','):'*';
  for(const r of resources)
    await fetch('/api/grants',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({principal_kind:att.p.kind,principal_id:att.p.id,action:att.action,
        resource:r,effect:att.effect,surfaces,note:'attached from the policy console'})});
  toast(resources.length+' rule(s) attached to '+att.p.label+(surfaces!=='*'?' (gates: '+surfaces+')':''));
  PERM.att={p:att.p,action:att.action,res:new Set(),effect:att.effect,surf:new Set()};
  PERM.tab='map';PERM.sel=att.p.kind+':'+att.p.id;
  refreshApp('permissions');
}
async function permToggle(gid,effect){
  await fetch('/api/grants/'+gid,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({effect})});
  refreshApp('permissions');
}
/* IO gates: a grant can be scoped to the surfaces a call arrives on (import/export gates).
   Permitted on all three (GUI, TUI, channels)? it flows everywhere; scoped, it only flows
   there — anywhere else the call is denied and logged as an IO error. */
const PERM_SURFACES=['gui','tui','telegram','api','task'];
function permSurfBadge(g){
  const scoped=g.surfaces&&g.surfaces!=='*';
  return `<button class="endbtn" style="font-size:10px;${scoped?'color:var(--acc2,#22d3ee);border-color:var(--acc2,#22d3ee)':''}"
    title="IO gates — which surfaces this rule applies on (GUI, TUI, Telegram, API, tasks). Click to change."
    onclick="permSurfaces('${g.id}','${esc(g.surfaces||'*')}')">⛩ ${scoped?esc(g.surfaces):'all'}</button>`;
}
async function permSurfaces(gid,cur){
  const v=await osPrompt('IO gates for this rule',{message:'Comma-separated from: '+PERM_SURFACES.join(', ')+' (* = every surface)',value:cur||'*'});
  if(v===null)return;
  const clean=v.trim()==='*'?'*':v.split(',').map(s=>s.trim()).filter(s=>PERM_SURFACES.includes(s)).join(',');
  if(v.trim()!=='*'&&!clean)return toast('no valid surfaces — use: '+PERM_SURFACES.join(', '));
  await fetch('/api/grants/'+gid,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({surfaces:clean||'*'})});
  toast('rule now applies on: '+(clean||'every surface'));
  refreshApp('permissions');
}
async function permRevoke(gid){
  await fetch('/api/grants/'+gid,{method:'DELETE'});
  toast('revoked'); refreshApp('permissions');
}
async function reviewManifest(aid){
  let r; try{r=await (await fetch('/api/apps/'+aid+'/manifest')).json()}catch(e){return toast('failed to load manifest')}
  showConsent(r.manifest,[],async granted=>{
    await fetch('/api/apps/'+aid+'/manifest/approve',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({granted})});
    toast('permissions granted — legacy access retired'); refreshApp('permissions');
  });
}
/* consent modal: manifest permissions with required/optional toggles + prerequisite installs.
   missing = [{label, run:async fn}] */
function showConsent(manifest,missing,onApprove){
  const perms=(manifest&&manifest.permissions)||[];
  const shield='<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--acc,#5eead4)"><path d="M12 3l8 3v5c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6l8-3z"/></svg>';
  const ov=document.createElement('div');
  ov.style.cssText='position:fixed;inset:0;z-index:9700;display:flex;align-items:center;justify-content:center;background:rgba(5,7,10,.55);backdrop-filter:blur(4px)';
  ov.innerHTML=`<div style="width:min(560px,92vw);max-height:82vh;overflow:auto;background:var(--glass,#171b22);border:1px solid var(--border,#232a35);border-radius:14px;padding:20px">
    <div style="display:flex;align-items:center;gap:10px">${shield}<b style="font-size:15px">${esc(manifest.name||'This app')} requests permission</b></div>
    <p class="mut" style="margin:6px 0 12px">${esc(manifest.description||'')} You can untick optional items — and revoke anything later in Permissions.</p>
    ${perms.length?perms.map((p,i)=>`<label class="item" style="display:flex;gap:10px;align-items:flex-start;cursor:pointer">
      <input type="checkbox" data-i="${i}" checked ${p.required?'disabled':''} style="margin-top:3px;accent-color:var(--acc,#5eead4)">
      <div class="grow"><div style="font-family:var(--mono);font-size:12.5px">${esc(p.action||'*')} · ${esc(p.resource||'*')}</div>
        <div class="mut" style="font-size:12px">${esc(p.reason||'')}${p.required?' · required':' · optional'}</div></div></label>`).join('')
      :'<p class="mut">No capabilities requested — this app only uses its own private data.</p>'}
    ${(missing&&missing.length)?'<label style="display:block;margin-top:12px">Missing prerequisites</label>'+missing.map((m,j)=>`<div class="item"><div class="grow">${esc(m.label)}</div><button class="prq" data-j="${j}">Install</button></div>`).join(''):''}
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">
      <button class="c-cancel">Cancel</button><button class="c-ok save" style="margin:0">Grant selected</button></div>
  </div>`;
  document.body.appendChild(ov);
  ov.querySelectorAll('.prq').forEach(b=>{b.onclick=async()=>{
    b.textContent='installing…';b.disabled=true;
    try{await missing[+b.dataset.j].run();b.textContent='installed'}
    catch(e){b.textContent='failed';b.disabled=false}
  }});
  ov.querySelector('.c-cancel').onclick=()=>ov.remove();
  ov.querySelector('.c-ok').onclick=()=>{
    const granted=[...ov.querySelectorAll('input[type=checkbox]')].filter(c=>c.checked).map(c=>+c.dataset.i);
    ov.remove(); onApprove(granted);
  };
}
function reloadAppFrames(){ // a revoked capability shouldn't live on in an open iframe
  document.querySelectorAll('iframe[src^="/api/apps/"]').forEach(f=>{const s=f.src;f.src=s});
}


/* ================= quarantine: what the OS stopped, and why =================
   A held thing plus the evidence for holding it, so the answer to "why has my app
   stopped working" is on screen with numbers rather than in a log somebody has to
   go and find. Three ways out, and every one of them is recorded. */
function permQuarantine(box){
  const when=t=>new Date(t*1000).toLocaleString();
  const kindIcon={app:'▢',subagent:'◈',flow:'▲'};
  const held=(PERM.held||[]).map(q=>{
    const ev=q.evidence||{};
    return `<div class="provbox" style="border-color:var(--err,#f87171)">
      <div class="ptitle" style="margin-top:0">${kindIcon[q.principal_kind]||'•'}
        ${esc(q.label||q.principal_id)}
        <span class="sub">· ${esc(q.principal_kind)} · held ${when(q.created_at)}</span></div>
      <div class="sub" style="margin:2px 0 6px">${esc(q.reason||'')}</div>
      ${ev.count?`<div class="sub">it made <b>${ev.count}</b> ${ev.class==='llm'?'model':'tool'}
        call${ev.count===1?'':'s'} in ${Math.round(ev.window)}s — the limit is ${ev.allowed}${
        ev.tool?', calling <code>'+esc(String(ev.tool).split('→').pop())+'</code>':''}</div>`:''}
      <div class="sub" style="margin-top:6px">Nothing it asks for runs while it is held.</div>
      <div class="row" style="margin-top:8px;gap:6px;flex-wrap:wrap">
        <button onclick="permRelease('${q.id}','once')"
          title="let it run again — it can be held again if it does this once more">Let it run once</button>
        <button onclick="permRelease('${q.id}','forever')"
          title="never hold this again for going too fast — recorded as your decision">Allow forever</button>
        <button style="color:var(--err,#f87171)" onclick="permRelease('${q.id}','deleted')"
          title="delete it">Delete it</button>
      </div></div>`;
  }).join('')||`<p class="mut">Nothing is quarantined. If an app, agent or flow starts calling
    in a loop — too many model calls or too many tool calls in a short window — the OS stops it
    here and tells you why, rather than letting it run all night.</p>`;
  const past=(PERM.qhistory||[]).map(q=>{
    const said={once:'let it run once',forever:'allowed forever',deleted:'deleted'}[q.release_mode]
      ||esc(q.release_mode||'released');
    return `<div class="sub">${when(q.created_at)} · <b>${esc(q.label||q.principal_id)}</b>
      (${esc(q.principal_kind)}) — ${esc(q.reason||'')} → <b>${said}</b> by ${esc(q.released_by||'user')}</div>`;
  }).join('');
  box.innerHTML=`<div class="ptitle" style="margin-top:0">Held now</div>${held}
    ${past?`<div class="ptitle" style="margin-top:14px">Earlier decisions</div>
      <div class="sub" style="margin-bottom:6px">Kept on the record — "allow forever" is an
      exemption somebody made, and it should stay visible.</div>${past}`:''}`;
}
/* Quarantine as an app in its own right.

   It was only ever a tab inside the policy console, which is the wrong place to keep
   it: Permissions is where you go to think about rules, and quarantine is where you
   go when something has ALREADY stopped working and you want to know why. Nobody
   whose app just went quiet thinks "I should check the policy console" — so the
   answer has to be somewhere you can find without knowing the architecture.

   Same renderer, two homes. `permQuarantine` still draws the tab; this only loads the
   data the tab gets for free from `renderPermissions` and hands it the same box. A
   second copy of the list would drift, and the drift would be in the screen that
   explains why the OS stopped something. */
async function renderQuarantine(body){
  try{const q=await (await fetch('/api/quarantine?history=1')).json();
      PERM.held=q.held||[];PERM.qhistory=(q.history||[]).filter(r=>r.released_at)}
  catch(e){PERM.held=[];PERM.qhistory=[]}
  const n=PERM.held.length;
  const pb=panelShell(body,{
    title:'Quarantine',
    sub:n?`${n} held — nothing ${n===1?'it':'they'} ask${n===1?'s':''} for runs while held`
        :'Nothing is held right now',
  });
  pb.innerHTML=`<div id="perm-body"></div>
    <p class="mut" style="margin-top:14px">Rules and grants live in
      <a href="#" onclick="openApp('permissions');PERM.tab='map';refreshApp('permissions');return false">Permissions</a>
      — this is only what has been stopped.</p>`;
  permQuarantine(pb.querySelector('#perm-body'));
}
async function permRelease(qid,mode){
  const q=(PERM.held||[]).find(x=>x.id===qid)||{};
  const name=q.label||q.principal_id||'it';
  const ask={once:['Let “'+name+'” run again?','It stays watched — if it does this again it is held again.'],
    forever:['Allow “'+name+'” forever?','It will never be held for going too fast again. Your decision is recorded.'],
    deleted:['Delete “'+name+'”?','This removes it for good.']}[mode];
  if(!await osConfirm(ask[0],ask[1],{danger:mode==='deleted',
      confirmText:{once:'Let it run',forever:'Allow forever',deleted:'Delete'}[mode]}))return;
  const r=await fetch('/api/quarantine/'+qid+'/release',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})}).then(r=>r.json());
  if(r.error)return toast(r.error);
  toast({once:'released — still watched',forever:'allowed forever',deleted:'deleted'}[mode]);
  refreshApp('permissions');refreshApp('quarantine');refreshApp('apps');refreshApp('fabric');
}
