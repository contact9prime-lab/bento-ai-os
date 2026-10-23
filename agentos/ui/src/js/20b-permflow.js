/* ================= Permissions → Flow: how a request is decided =================
   The gate (policy.PDP._decide) takes the same steps every time and stops at the first
   one that decides. The other tabs list rules; this one draws the steps in order, so a
   person can see WHERE something was allowed, asked or refused:
   - the steps, each with how many of the last day's decisions it made (from the Ledger)
   - Try it: a pretend call traced through them (/api/policy/trace, nothing runs or is
     recorded), lighting the steps it passed and the one that decided
   - the latest decisions, each one tap from its own path.
   The steps come from the server (policy.STAGES), never a second list on the page.
   TUI: `bento grants why <who> <tool> [detail]`, and `bento audit` names the step.
   SUI: the same page. `var` state: the bundle's TDZ rule. */
var PF={stages:null,recent:[],counts:{},trace:null,pick:null,
  who:'user:',tool:'run_command',detail:'',surface:'gui',web:false,busy:false};

async function permFlow(box){
  box.innerHTML='<p class="mut">Reading the gate…</p>';
  const since=Math.floor(Date.now()/1000-24*3600);
  const [st,au]=await Promise.all([
    PF.stages?Promise.resolve({stages:PF.stages}):fetch('/api/policy/stages').then(r=>r.json()).catch(()=>({stages:[]})),
    fetch('/api/audit?limit=400&since='+since).then(r=>r.json()).catch(()=>({entries:[]}))]);
  PF.stages=st.stages||[];
  const rows=(au.entries||[]).filter(a=>a.stage);
  PF.recent=rows.slice(0,12);
  if(PF.pick&&!PF.recent.some(x=>x.id===PF.pick.id))PF.recent.unshift(PF.pick);
  PF.counts={};rows.forEach(a=>{PF.counts[a.stage]=(PF.counts[a.stage]||0)+1});
  pfPaint(box);
}

/* What a lit path shows: a trace, or a ledger row picked from the list. */
function pfPath(){
  if(PF.trace)return {stage:PF.trace.stage,effect:PF.trace.effect};
  if(PF.pick)return {stage:PF.pick.stage,effect:PF.pick.effect};
  return null;
}
function pfEffWord(e){return {allow:'Allowed',ask:'Asks you',deny:'Refused'}[e]||e}
function pfEffCls(e){return e==='deny'?'pf-deny':e==='ask'?'pf-ask':'pf-allow'}

function pfPaint(box){
  box=box||$('#perm-body');if(!box)return;
  const path=pfPath();
  const at=path?PF.stages.findIndex(s=>s.key===path.stage):-1;
  const steps=PF.stages.map((s,i)=>{
    const state=at<0?'':i<at?' passed':i===at?' decided '+pfEffCls(path.effect):' skipped';
    const n=PF.counts[s.key]||0;
    return `<div class="pf-step${state}" data-k="${esc(s.key)}">
      <div class="pf-num">${i<at?'✓':i+1}</div>
      <div class="pf-txt"><b>${esc(s.label)}</b><span>${esc(s.about)}</span></div>
      ${i===at?`<span class="pf-out ${pfEffCls(path.effect)}">${esc(pfEffWord(path.effect))}</span>`
        :n?`<span class="pf-n" title="decisions made at this step in the last 24 hours">${n}</span>`:''}
    </div>`}).join('<div class="pf-arrow" aria-hidden="true"></div>');
  const ps=[{kind:'user',id:'',label:(typeof agentName==='function'?agentName():'Your agent')+' (your agent)'},
    ...(PERM.opts.principals||[]).map(p=>({kind:p.kind,id:p.id,label:p.label+' · '+(p.kind==='subagent'?'specialist':p.kind)}))];
  const tools=((PERM.opts.resources||{})['tool.use']||[]).map(r=>r.label);
  if(tools.length&&!tools.includes(PF.tool))PF.tool=tools[0];
  const opt=(v,l,on)=>`<option value="${esc(v)}" ${on?'selected':''}>${esc(l)}</option>`;
  const recent=PF.recent.map((a,i)=>{
      const who=a.principal_id?a.principal_id:(a.principal_kind==='user'?'your agent':a.principal_kind);
      const st=(PF.stages.find(s=>s.key===a.stage)||{}).label||a.stage;
      return `<button class="pf-row${PF.pick&&PF.pick.id===a.id?' on':''}" data-i="${i}">
        <span class="audpill ${a.effect==='deny'?'audden':a.effect==='ask'?'audask':'audok'}">${esc(a.effect)}</span>
        <span class="pf-rw"><b>${esc(who)}</b> ${esc(a.action)} <code>${esc(String(a.resource||'').slice(0,60))}</code></span>
        <span class="pf-at">at ${esc(st)}</span></button>`}).join('')
      ||'<p class="mut">Nothing decided in the last day yet.</p>';
  box.innerHTML=`<p class="mut pf-lead">Every request goes down these steps in order and stops at the first one that decides. Try one, or tap a recent decision to see its path.</p>
  <div class="pf">
    <div class="pf-left">
      <div class="pf-h">The steps <span class="mut">· decided in the last day</span></div>
      <div class="pf-steps">${steps}</div>
      <div class="pf-ends"><span class="pf-out pf-allow">Allowed</span><span class="pf-out pf-ask">Asks you</span><span class="pf-out pf-deny">Refused</span></div>
    </div>
    <div class="pf-right">
      <div class="pf-try">
        <div class="pf-h">Try a request</div>
        <label>Who<select id="pf-who">${ps.map(p=>opt(p.kind+':'+p.id,p.label,PF.who===p.kind+':'+p.id)).join('')}</select></label>
        <div class="pf-pair"><label>Does<select id="pf-tool">${tools.map(t=>opt(t,t,PF.tool===t)).join('')}</select></label>
          <label>Via<select id="pf-surf">${PERM_SURFACES.map(s=>opt(s,s,PF.surface===s)).join('')}</select></label></div>
        <label>On<input id="pf-detail" placeholder="a command, file or address (optional)" value="${esc(PF.detail)}"></label>
        <div class="pf-pair"><label class="pf-chk"><input type="checkbox" id="pf-web" ${PF.web?'checked':''}> after reading a web page</label>
          <button class="save" id="pf-go" ${PF.busy?'disabled':''}>Trace it</button></div>
      </div>
      <div id="pf-why">${pfWhy()}</div>
      <div class="pf-h" style="margin-top:14px">Latest decisions</div>
      <div class="pf-recent">${recent}</div>
    </div>
  </div>`;
  const g=id=>box.querySelector(id);
  g('#pf-who').onchange=e=>{PF.who=e.target.value};
  g('#pf-tool').onchange=e=>{PF.tool=e.target.value};
  g('#pf-detail').oninput=e=>{PF.detail=e.target.value};
  g('#pf-detail').onkeydown=e=>{if(e.key==='Enter')pfTrace()};
  g('#pf-surf').onchange=e=>{PF.surface=e.target.value};
  g('#pf-web').onchange=e=>{PF.web=e.target.checked};
  g('#pf-go').onclick=pfTrace;
  box.querySelectorAll('.pf-row').forEach(b=>b.onclick=()=>{
    const a=PF.recent[+b.dataset.i];PF.trace=null;PF.pick=PF.pick&&PF.pick.id===a.id?null:a;pfPaint(box)});
}

/* The sentence under the steps: what decided it, and the door to change it. */
function pfWhy(){
  const t=PF.trace,a=PF.pick;
  if(!t&&!a)return '';
  const eff=t?t.effect:a.effect,stage=t?t.stage:a.stage;
  const label=(PF.stages.find(s=>s.key===stage)||{}).label||stage;
  const reason=(t?t.reason:a.reason)||{allow:'Nothing stopped it.',ask:'A person is asked first.',deny:'It was refused.'}[eff]||'';
  const what=t?`${esc(t.action)} <code>${esc(t.resource)}</code> · risk ${esc(t.risk)}${t.autonomy?' · autonomy '+esc(t.autonomy):''}`
    :`${esc(a.action)} <code>${esc(a.resource)}</code> · via ${esc(a.surface||'?')} · ${new Date(a.ts*1000).toLocaleString()}`;
  let doors='';
  const gid=t?(t.grant&&t.grant.id):(/^[0-9a-f]{12}$/.test(a.rule||'')?a.rule:'');
  if(gid){
    const g=t&&t.grant;
    doors=`<div class="pf-rule">Decided by a rule${g?`: <b>${esc(g.effect)}</b> ${esc(g.action)} <code>${esc(g.resource)}</code> <span class="badge">${esc(g.source||'user')}</span>`:''}
      <button class="endbtn" onclick="permRevoke('${esc(gid)}')">Remove this rule</button></div>`;
  }else if(stage==='default'){
    doors=`<div class="pf-rule">No rule covers this yet.
      <button class="endbtn" onclick="pfAttach('allow')">Always allow it</button>
      <button class="endbtn" onclick="pfAttach('deny')">Always refuse it</button></div>`;
  }else if(stage==='reach'){
    doors=`<div class="pf-rule"><button class="endbtn" onclick="placeSettings('executors')()">Change its hands</button></div>`;
  }else if(stage==='channel'){
    doors=`<div class="pf-rule"><button class="endbtn" onclick="placeSettings('channels')()">Channel settings</button></div>`;
  }else if(stage==='rate'){
    doors=`<div class="pf-rule"><button class="endbtn" onclick="PERM.tab='quarantine';refreshApp('permissions')">Open Quarantine</button></div>`;
  }else if(stage==='team'){
    doors=`<div class="pf-rule"><button class="endbtn" onclick="placeSettings('agent')()">Who may ask whom</button></div>`;
  }
  return `<div class="pf-why ${pfEffCls(eff)}">
    <div class="pf-verdict"><b>${esc(pfEffWord(eff))}</b> at <b>${esc(label)}</b></div>
    <div class="pf-what">${what}</div>
    <div class="pf-reason">${esc(reason)}</div>${doors}</div>`;
}

async function pfTrace(){
  if(PF.busy)return;PF.busy=true;
  const [kind,...rest]=PF.who.split(':');
  try{
    const r=await fetch('/api/policy/trace',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({principal_kind:kind,principal_id:rest.join(':'),tool:PF.tool,
        detail:PF.detail,surface:PF.surface,after_web:PF.web})});
    const j=await r.json();
    if(j.error)toast(j.error);else{PF.trace=j;PF.pick=null}
  }catch(e){toast('could not reach the server')}
  PF.busy=false;pfPaint();
}

/* "Always allow / refuse it": the Attach tab with who and the exact resource filled in. */
function pfAttach(effect){
  const t=PF.trace,a=PF.pick;
  const kind=t?PF.who.split(':')[0]:a.principal_kind;
  const id=t?PF.who.split(':').slice(1).join(':'):(a.principal_id||'');
  const action=t?t.action:a.action,res=t?t.resource:a.resource;
  if(kind==='user'&&!id){
    // the main agent is not in the Attach list; write the rule directly
    fetch('/api/grants',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({principal_kind:'user',principal_id:'',action,resource:res,effect,
        note:'written from the Flow tab'})}).then(()=>{toast(effect==='deny'?'refused from now on':'allowed from now on');
        PF.trace=null;PF.pick=null;refreshApp('permissions')});
    return;
  }
  const p=(PERM.opts.principals||[]).find(x=>x.kind===kind&&x.id===id)||{kind,id,label:id||kind};
  PERM.att={p,action,res:new Set(),effect,surf:new Set()};
  PERM.tab='attach';refreshApp('permissions');
  setTimeout(()=>{const c=$('#att-custom');if(c)c.value=res},50);
}
