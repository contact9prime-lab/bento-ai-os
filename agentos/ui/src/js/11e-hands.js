/* ================= brains, hands and agents (Settings) =================
   Executors → the hands editor (agentos/hands.py over /api/hands).
   Agents    → the lead agent's hands, every other agent's card, and the map
               (agentos/agentmap.py over /api/agents and /api/agents/graph).
   One computation on the server feeds all of it, so the card, the map and
   `bento agents` cannot disagree about who reaches what.
   Faces — TUI: `bento hands`, `bento agents [map|hands]`. SUI: this page, nothing
   native. Phone: every control keeps the --tap floor; the map scrolls sideways
   rather than squeezing four columns into 390px. */
var HANDS={data:null,edit:null};
var AGENTS={data:null,focus:''};

function settingsGo(tab){
  SETTAB=tab;try{localStorage.setItem('settab',tab)}catch(e){}
  const b=document.querySelector(`.prefs-side button[data-t="${tab}"]`);
  if(b)b.click();
}

/* ---------------- Executors: the hands editor ---------------- */
async function renderHands(){
  const box=document.getElementById('hands-list');if(!box)return;
  // apiJSON, never a bare .json(): a server older than the page answers 404 with JSON, and
  // reading that as the list threw later and left "loading…" on screen for good
  try{HANDS.data=await apiJSON('/api/hands')}catch(e){box.innerHTML='<p class="mut">could not load executors — '+esc(e.message)+'</p>';return}
  const d=HANDS.data;
  box.innerHTML=`<div class="hands-top"><button class="pact" onclick="handsEdit('')">＋ New executor</button></div>`
    +d.profiles.map(p=>`<div class="hands-card" data-name="${esc(p.name)}">
      <div class="hands-h"><b>${esc(p.name)}</b>${p.builtin?'<span class="brainchip">built in</span>':''}
        <span class="sp"></span>
        <button class="endbtn" onclick="handsEdit('${esc(p.name)}')">Edit</button>
        <button class="endbtn" onclick="handsEdit('${esc(p.name)}',true)">Duplicate</button>
        ${p.builtin?'':`<button class="endbtn" onclick="handsDelete('${esc(p.name)}')">Delete</button>`}</div>
      <div class="hands-sum">${esc(p.summary)}</div>
      ${p.description?`<div class="mut hands-desc">${esc(p.description)}</div>`:''}
      <div class="mut hands-used">${(p.used_by||[]).length?'Used by '+p.used_by.map(n=>esc(n)).join(', '):'No agent uses it yet'}</div>
      ${HANDS.edit&&HANDS.edit.from===p.name?'<div class="hands-ed" id="hands-ed"></div>':''}
    </div>`).join('')
    +(HANDS.edit&&HANDS.edit.from===''?'<div class="hands-card"><div class="hands-ed" id="hands-ed"></div></div>':'');
  if(HANDS.edit)handsPaintEditor();
}
function handsEdit(name,dup){
  const d=HANDS.data||{profiles:[]};
  const p=d.profiles.find(x=>x.name===name);
  const base=p?JSON.parse(JSON.stringify(p.spec)):{tools:[],folders:[{path:'@workspace',mode:'ro'}],web:'none',mcp:[]};
  HANDS.edit={from:dup?'':(name||''),name:dup?(name+'-copy'):(name||''),exists:!!p&&!dup,
    description:p&&!dup?(p.description||''):'',spec:base};
  renderHands();
}
function handsPaintEditor(){
  const el=document.getElementById('hands-ed');if(!el||!HANDS.edit)return;
  const e=HANDS.edit,s=e.spec,d=HANDS.data;
  const every=s.tools.includes('*');
  const shell=every||(d.shell_tools||[]).some(t=>s.tools.includes(t));
  const groups=Object.entries(d.tools||{}).map(([g,ns])=>{
    const n=ns.filter(t=>s.tools.includes(t)).length;
    return `<details class="hands-grp"><summary>${esc(g)} <span class="mut">${n}/${ns.length}</span></summary>
      <div class="hands-tools">${ns.map(t=>`<label class="tlk-chk"><input type="checkbox" data-tool="${esc(t)}" ${s.tools.includes(t)?'checked':''}><span>${esc(t)}</span></label>`).join('')}</div></details>`}).join('');
  const webMode=Array.isArray(s.web)?'list':s.web;
  const mcpMode=s.mcp.includes('*')?'all':(s.mcp.length?'some':'none');
  el.innerHTML=`<div class="hands-form">
    <label>Name<input id="he-name" value="${esc(e.name)}" ${e.exists?'disabled':''} autocomplete="off" autocapitalize="off" spellcheck="false"></label>
    <label>What it is for<input id="he-desc" value="${esc(e.description)}" placeholder="e.g. writes reports into the shared folder"></label>
    <div class="hands-sec"><b>Tools</b>
      <label class="tlk-chk"><input type="radio" name="he-tm" value="all" ${every?'checked':''}><span>Every tool</span></label>
      <label class="tlk-chk"><input type="radio" name="he-tm" value="some" ${every?'':'checked'}><span>Only the ones ticked</span></label>
      ${every?'':`<div class="hands-groups">${groups}</div>`}
      ${shell?'<p class="mut tlk-why">Includes a shell. A command line reaches whatever the machine’s folder jail allows, not only the folders below — leave the shell tools out to make the folders a real limit.</p>':''}</div>
    <div class="hands-sec"><b>Folders</b>
      <div id="he-folders">${s.folders.map((f,i)=>`<div class="hands-folder"><input data-fi="${i}" value="${esc(f.path)}" placeholder="~/projects or /srv/data" autocomplete="off" autocapitalize="off" spellcheck="false">
        <select data-fm="${i}"><option value="rw" ${f.mode==='rw'?'selected':''}>read-write</option><option value="ro" ${f.mode==='ro'?'selected':''}>read-only</option></select>
        <button class="endbtn" aria-label="Remove this folder" onclick="handsFolder(${i})">✕</button></div>`).join('')||'<p class="mut tlk-why">No folders — the file tools reach nothing.</p>'}</div>
      <div class="tlk-actions"><button class="endbtn" onclick="handsFolder(-1,'')">＋ Folder</button>
        <button class="endbtn" onclick="handsFolder(-1,'@workspace')">＋ Workspace</button>
        <button class="endbtn" onclick="handsFolder(-1,'*')">＋ Anywhere the machine allows</button></div></div>
    <div class="hands-sec"><b>Web</b>
      <select id="he-web"><option value="any" ${webMode==='any'?'selected':''}>Any address</option><option value="none" ${webMode==='none'?'selected':''}>No web</option><option value="list" ${webMode==='list'?'selected':''}>Only these addresses</option></select>
      ${webMode==='list'?`<textarea id="he-weblist" rows="3" placeholder="https://api.github.com/*">${esc((s.web||[]).join('\n'))}</textarea>`:''}</div>
    <div class="hands-sec"><b>MCP servers</b>
      <select id="he-mcp"><option value="all" ${mcpMode==='all'?'selected':''}>Every server</option><option value="some" ${mcpMode==='some'?'selected':''}>Only these</option><option value="none" ${mcpMode==='none'?'selected':''}>None</option></select>
      ${mcpMode==='some'?((d.mcp||[]).length?`<div class="hands-tools">${d.mcp.map(m=>`<label class="tlk-chk"><input type="checkbox" data-mcp="${esc(m)}" ${s.mcp.includes(m)?'checked':''}><span>${esc(m)}</span></label>`).join('')}</div>`:'<p class="mut tlk-why">No MCP servers are set up on this machine yet.</p>'):''}</div>
    <div class="tlk-actions"><button class="pact" onclick="handsSave()">Save</button><button class="endbtn" onclick="HANDS.edit=null;renderHands()">Cancel</button></div>
  </div>`;
  el.querySelectorAll('input[name="he-tm"]').forEach(r=>r.onchange=()=>{handsCollect();HANDS.edit.spec.tools=r.value==='all'?['*']:[];handsPaintEditor()});
  el.querySelector('#he-web').onchange=()=>{handsCollect();const v=el.querySelector('#he-web').value;HANDS.edit.spec.web=v==='list'?[]:v;handsPaintEditor()};
  el.querySelector('#he-mcp').onchange=()=>{handsCollect();const v=el.querySelector('#he-mcp').value;HANDS.edit.spec.mcp=v==='all'?['*']:[];if(v==='some'&&!(d.mcp||[]).length)HANDS.edit.spec.mcp=[];HANDS.edit._mcpSome=v==='some';handsPaintEditor()};
  el.querySelectorAll('input[data-tool]').forEach(c=>c.onchange=()=>{handsCollect();handsPaintEditor()});
  if(HANDS.edit._mcpSome)el.querySelector('#he-mcp').value='some';
}
function handsCollect(){
  const el=document.getElementById('hands-ed');if(!el||!HANDS.edit)return;
  const e=HANDS.edit,s=e.spec;
  const nm=el.querySelector('#he-name');if(nm&&!e.exists)e.name=nm.value.trim();
  e.description=(el.querySelector('#he-desc')||{}).value||'';
  if(!s.tools.includes('*')){
    const ticked=[...el.querySelectorAll('input[data-tool]')].filter(c=>c.checked).map(c=>c.dataset.tool);
    if(el.querySelector('input[data-tool]'))s.tools=ticked;
  }
  s.folders=s.folders.map((f,i)=>({path:((el.querySelector(`[data-fi="${i}"]`)||{}).value||f.path).trim(),
    mode:(el.querySelector(`[data-fm="${i}"]`)||{}).value||f.mode}));
  const wl=el.querySelector('#he-weblist');
  if(wl)s.web=wl.value.split('\n').map(x=>x.trim()).filter(Boolean);
  const mc=[...el.querySelectorAll('input[data-mcp]')];
  if(mc.length)s.mcp=mc.filter(c=>c.checked).map(c=>c.dataset.mcp);
}
function handsFolder(i,add){
  handsCollect();const f=HANDS.edit.spec.folders;
  if(i<0)f.push({path:add||'',mode:add==='@workspace'?'ro':'rw'});else f.splice(i,1);
  handsPaintEditor();
}
async function handsSave(){
  handsCollect();const e=HANDS.edit;
  if(!e.name){toast('give it a name');return}
  const spec={...e.spec,folders:e.spec.folders.filter(f=>f.path)};
  if(Array.isArray(spec.web)&&!spec.web.length)spec.web='none';
  const r=await teamApi('/api/hands/'+encodeURIComponent(e.name),'PUT',{spec,description:e.description});
  if(r){toast(e.name+': '+r.profile.summary);HANDS.edit=null;renderHands();if(document.getElementById('agents-list'))renderAgentsList()}
}
async function handsDelete(name){
  if(!await osConfirm('Delete the executor “'+name+'”?','Any agent using it goes back to the default executor.',{danger:true,confirmText:'Delete'}))return;
  const r=await teamApi('/api/hands/'+encodeURIComponent(name),'DELETE');
  if(r){toast('deleted'+(r.moved_to_default?' — '+r.moved_to_default+' agent(s) moved to default':''));renderHands()}
}

/* ---------------- Agents: the lead, the others, and their hands ---------------- */
async function setAgentHands(key,profile){
  const r=await teamApi('/api/agents/'+encodeURIComponent(key)+'/hands','PUT',{profile});
  if(r){toast((key==='@agent'?(cfg.agent_name||'Your agent'):key)+' now works with “'+r.profile+'”');renderAgentsList();renderAgentsGraph()}
}
async function renderAgentsList(){
  const box=document.getElementById('agents-list');if(!box)return;
  try{AGENTS.data=await apiJSON('/api/agents')}catch(e){
    // the editor saves through /api/subagents, which is older than this list: adding an
    // agent must not depend on the overview having loaded
    box.innerHTML='<p class="mut">could not load agents — '+esc(e.message)+'</p>'
      +'<div class="tlk-actions"><button class="pact" onclick="agentEdit(\'\')">＋ New agent</button></div>';return}
  const d=AGENTS.data,profs=d.profiles||[];
  const opts=cur=>profs.map(p=>`<option value="${esc(p.name)}" ${p.name===cur?'selected':''}>${esc(p.name)}</option>`).join('');
  const lead=d.agents.find(a=>a.master);
  if(lead){
    const lb=document.getElementById('s-lead-brain');
    if(lb)lb.textContent=lead.brain.provider_name+' · '+lead.brain.short;
    const lh=document.getElementById('s-lead-hands');
    if(lh)lh.innerHTML=opts(lead.hands.name);
  }
  const others=d.agents.filter(a=>!a.master);
  box.innerHTML=`<div class="pgroup"><h3>Your agents</h3>
    <p class="mut" style="margin:0 0 8px">${esc(cfg.agent_name||'Your agent')} delegates to these. Each has its own soul, and its own brain, hands, permissions and skills.</p>
    ${others.map(a=>{const au=a.authority,fams=Object.entries(au.families||{});
      return `<div class="ag-card">
      <div class="ag-h"><button class="ag-face" onclick="avatarEdit('${esc(a.key)}')" title="Change how ${esc(a.name)} looks" aria-label="Change how ${esc(a.name)} looks">${avatarImg(a.key,'av-tool')}</button><b>${esc(a.name)}</b>${a.builtin?'<span class="brainchip">built in</span>':''}
        <span class="sp"></span><button class="endbtn" onclick="agentEdit('${esc(a.key)}')">Edit</button></div>
      ${a.soul?`<div class="mut ag-soul">${esc(a.soul)}</div>`:''}
      <div class="ag-rows">
        <div><span class="ag-k">Look</span><button class="endbtn" onclick="avatarEdit('${esc(a.key)}')">Change…</button><button class="endbtn" onclick="avatarDesignAsk('${esc(a.key)}')">✦ Describe it</button></div>
        <div><span class="ag-k">Brain</span>${esc(a.brain.provider_name)} · ${esc(a.brain.short)}${a.brain.note?` <span class="mut">— ${esc(a.brain.note)}</span>`:''}</div>
        <div><span class="ag-k">Executor</span><select aria-label="Executor for ${esc(a.name)}" onchange="setAgentHands('${esc(a.key)}',this.value)">${opts(a.hands.name)}</select> <span class="mut">${esc(a.hands.summary)}</span></div>
        <div><span class="ag-k">Permissions</span>autonomy ${esc(au.autonomy)}${au.allow||au.deny?` · ${au.allow} allowed, ${au.deny} refused`:' · nothing granted yet — it asks'}${fams.length?' <span class="mut">('+fams.map(([k,v])=>esc(k)+' '+v.allow+(v.deny?'/'+v.deny+'✗':'')).join(', ')+')</span>':''}${au.in_missions?` <span class="mut">· ${au.in_missions} more inside missions</span>`:''}
          <button class="endbtn" onclick="openApp('permissions')">Open</button></div>
        <div><span class="ag-k">Skills</span>${(a.skills||[]).length?a.skills.map(x=>`<span class="brainchip">${esc(x)}</span>`).join(' '):'<span class="mut">none</span>'}</div>
        ${a.asks.length||a.blocked.length?`<div><span class="ag-k">May ask</span>${a.asks.map(esc).join(', ')||'<span class="mut">nobody without asking you</span>'}${a.blocked.length?` <span class="mut">· blocked: ${a.blocked.map(esc).join(', ')}</span>`:''}</div>`:''}
        ${a.missions.length?`<div><span class="ag-k">Missions</span>${a.missions.map(esc).join(', ')}</div>`:''}
        ${(a.links||[]).filter(l=>l.they_may_ask||(l.their_missions||[]).length).map(l=>`<div><span class="ag-k">${esc(l.label)}</span>may ask it${l.standing?` · ${l.standing} standing permission${l.standing===1?'':'s'}`:''}${(l.their_missions||[]).length?' · their missions: '+l.their_missions.map(esc).join(', '):''}</div>`).join('')}
      </div></div>`}).join('')||'<p class="mut">No other agents yet.</p>'}
    <div class="tlk-actions"><button class="pact" onclick="agentEdit('')">＋ New agent</button></div></div>`;
}
async function agentEdit(name){
  // the Missions editor's wizard, borrowed: one way to define an agent, not two
  try{const sa=await fetch('/api/subagents').then(r=>r.json());
    window.__subagents=Object.fromEntries((sa.subagents||[]).map(s=>[s.name,s]))}catch(e){}
  if(typeof openSAW!=='function'){toast('the agent editor is not available');return}
  openSAW(name||null,{onSaved:()=>{renderAgentsList();renderAgentsGraph()},onCancel:()=>{}});
}

/* ---------------- the map ---------------- */
var AG_COLS={brain:0,team:0,mission:0,agent:1,hands:2,skill:3};
var AG_EDGE={brain:'var(--acc)',hands:'color-mix(in srgb,var(--txt) 55%,transparent)',skill:'color-mix(in srgb,var(--txt) 35%,transparent)',
  talk:'#4ade80',blocked:'#f87171',delegate:'#a78bfa',roster:'#fbbf24',link:'#60a5fa'};
async function renderAgentsGraph(){
  const box=document.getElementById('agents-graph');if(!box)return;
  let g;try{g=await apiJSON('/api/agents/graph')}catch(e){box.textContent='could not load the map — '+e.message;return}
  box.classList.remove('mut');
  const cols=[[],[],[],[]];g.nodes.forEach(n=>cols[AG_COLS[n.kind]??3].push(n));
  const W=190,GX=70,GUT=60,H=46,GY=12,X=[0,W+GX+GUT,2*(W+GX)+GUT,3*(W+GX)+GUT];
  const pos={};cols.forEach((c,i)=>c.forEach((n,j)=>pos[n.id]={x:X[i],y:j*(H+GY),col:i}));
  const height=Math.max(...cols.map(c=>c.length*(H+GY)),H)+10,width=X[3]+W+4;
  const f=AGENTS.focus;
  const on=e=>!f||e.from===f||e.to===f;
  const path=e=>{const a=pos[e.from],b=pos[e.to];if(!a||!b)return'';
    const ay=a.y+H/2,by=b.y+H/2;
    if(a.col===b.col){ // agent ↔ agent: an arc in the gutter to the left of the agents
      const x=a.x,bend=Math.min(GUT-8,18+Math.abs(ay-by)/6);
      return `M${x},${ay} C${x-bend},${ay} ${x-bend},${by} ${x},${by}`}
    const [l,r]=a.col<b.col?[a,b]:[b,a],[ly,ry]=a.col<b.col?[ay,by]:[by,ay];
    const x1=l.x+W,x2=r.x,mx=(x1+x2)/2;return `M${x1},${ly} C${mx},${ly} ${mx},${ry} ${x2},${ry}`};
  box.innerHTML=`<div class="agraph-legend">${[['brain','thinks with'],['hands','works with'],['talk','may ask'],['blocked','may not ask'],['delegate','delegates'],['roster','mission roster'],['link','linked team'],['skill','knows']]
      .map(([k,l])=>`<span><i style="background:${AG_EDGE[k]}"></i>${l}</span>`).join('')}${f?' <button class="endbtn" onclick="AGENTS.focus=\'\';renderAgentsGraph()">Show everyone</button>':''}</div>
    <div class="agraph-scroll"><div class="agraph-canvas" style="width:${width}px;height:${height}px">
    <svg width="${width}" height="${height}" aria-hidden="true">${g.edges.map(e=>`<path d="${path(e)}" fill="none" stroke="${AG_EDGE[e.kind]||'var(--line)'}" stroke-width="${e.kind==='brain'||e.kind==='hands'?2:1.5}" ${e.kind==='blocked'?'stroke-dasharray="4 3"':''} opacity="${on(e)?0.9:0.08}"><title>${esc(e.label)}</title></path>`).join('')}</svg>
    ${g.nodes.map(n=>{const p=pos[n.id],dim=f&&n.id!==f&&!g.edges.some(e=>on(e)&&(e.from===n.id||e.to===n.id));
      return `<button class="agn agn-${n.kind}${n.master?' lead':''}${f===n.id?' on':''}" style="left:${p.x}px;top:${p.y}px;width:${W}px;height:${H}px;opacity:${dim?0.3:1}" ${n.kind==='agent'?`onclick="AGENTS.focus=AGENTS.focus==='${esc(n.id)}'?'':'${esc(n.id)}';renderAgentsGraph()"`:'tabindex="-1"'} title="${esc(n.sub||'')}">
        ${n.kind==='agent'?avatarImg(n.key,'av-tool'):''}<span class="agn-t"><b>${esc(n.label)}</b><small>${esc(n.kind==='agent'&&n.master?'lead agent':(n.sub||n.kind))}</small></span></button>`}).join('')}
    </div></div>
    <div class="agraph-cols mut"><span>Brains · teams · missions</span><span>Agents</span><span>Executors</span><span>Skills</span></div>`;
}
