/* ================= audit — the access ledger =================
   Logs answer "what happened". This answers "who was allowed to do what, arriving
   on which way in, and under which rule" — the question you cannot grep a JSON
   blob for. Every PDP decision writes one row, in the same vocabulary grants are
   written in, so a filter here and a grant in the Permissions app describe the
   same thing.

   `var`, not `let` — see the note at the top of 25a-gallery.js. */
var audFilter={effect:'',action:'',principal_kind:'',surface:'',q:'',since:24};

async function renderAudit(body,w){
  const qs=new URLSearchParams();
  Object.entries(audFilter).forEach(([k,v])=>{
    if(!v)return;
    if(k==='since')qs.set('since',String(Math.floor(Date.now()/1000-v*3600)));
    else qs.set(k,v);
  });
  if(activeSpace&&activeSpace())qs.set('space',activeSpace());
  const since=audFilter.since?Math.floor(Date.now()/1000-audFilter.since*3600):0;
  const [d,sum]=await Promise.all([
    fetch('/api/audit?limit=400&'+qs).then(r=>r.json()).catch(()=>({entries:[]})),
    fetch('/api/audit/summary?since='+since).then(r=>r.json()).catch(()=>({effects:{}}))]);
  const e=sum.effects||{};
  const RANGE=[[1,'1h'],[24,'24h'],[168,'7d'],[720,'30d'],[0,'All']];
  const pb=panelShell(body,{
    title:'Audit',
    sub:'every capability decision, as it was decided',
    search:{id:'aud-q',placeholder:'Search resource, reason or detail…'},
    actions:`<span class="seg">${RANGE.map(([h,l])=>
        `<button class="${audFilter.since===h?'on':''}" onclick="audRange(${h})">${l}</button>`).join('')}</span>
      <select onchange="audSet('effect',this.value)" style="flex:0 0 auto">
        <option value="">every outcome</option>
        <option value="allow" ${audFilter.effect==='allow'?'selected':''}>allowed</option>
        <option value="deny" ${audFilter.effect==='deny'?'selected':''}>denied</option>
        <option value="ask" ${audFilter.effect==='ask'?'selected':''}>asked</option>
      </select>
      <select onchange="audSet('principal_kind',this.value)" style="flex:0 0 auto">
        <option value="">anyone</option>
        ${['user','app','subagent','workflow','system'].map(k=>
          `<option value="${k}" ${audFilter.principal_kind===k?'selected':''}>${k}</option>`).join('')}
      </select>
      <select onchange="audSet('surface',this.value)" style="flex:0 0 auto">
        <option value="">any way in</option>
        ${['gui','tui','telegram','api','task'].map(k=>
          `<option value="${k}" ${audFilter.surface===k?'selected':''}>${k}</option>`).join('')}
      </select>`,
  });
  const q=$('#aud-q');
  if(q){q.value=audFilter.q;q.oninput=audSearch}
  const stat=(n,l,cls)=>`<div class="stat" style="text-align:center"><div class="val ${cls||''}">${n||0}</div><div class="lbl">${l}</div></div>`;
  const rows=(d.entries||[]).map(a=>{
    const cls=a.effect==='deny'?'audden':a.effect==='ask'?'audask':'audok';
    const who=a.principal_id?`${a.principal_kind}:${a.principal_id}`:a.principal_kind;
    const out=a.outcome&&a.outcome!=='ok'?`<span class="badge">${esc(a.outcome)}</span>`:'';
    return `<div class="item">
      <span class="audpill ${cls}">${esc(a.effect||'?')}</span>
      <div class="grow"><code>${esc(a.action||'')}</code> ${esc(a.resource||'')} ${out}
        <div class="sub">${esc(who)} · via ${esc(a.surface||'unknown')} · rule ${esc(a.rule||'default')}
          ${a.duration_ms?' · '+a.duration_ms+'ms':''} · ${new Date(a.ts*1000).toLocaleString()}
          ${a.reason?'<br>'+esc(a.reason):''}${a.detail?'<br>'+esc(a.detail.slice(0,200)):''}</div></div></div>`;
  }).join('');
  const denied=(sum.top_denied||[]).slice(0,5);
  pb.innerHTML=`
    <div class="tmgrid" style="margin-bottom:10px">
      ${stat(sum.total,'decisions')}${stat(e.allow,'allowed','audok')}
      ${stat(e.deny,'denied','audden')}${stat(e.ask,'asked','audask')}
    </div>
    ${denied.length?`<div class="ptitle">Most refused</div>`+denied.map(t=>
      `<div class="item"><div class="grow"><code>${esc(t.action)}</code> ${esc(t.resource)}</div>
       <span class="badge">${t.n}×</span></div>`).join(''):''}
    <div class="ptitle" style="margin-top:12px">Decisions</div>
    ${rows||emptyBox('Nothing in this period','Every tool call, MCP call, file write and model choice is recorded here as it is decided.')}`;
  if(w)winTick(w,()=>refreshApp('audit'),10000,{key:'audit',now:false});
}
function audSet(k,v){audFilter[k]=v;refreshApp('audit')}
function audRange(h){audFilter.since=h;refreshApp('audit')}
var _audT=null;
function audSearch(ev){clearTimeout(_audT);const v=ev.target.value;
  _audT=setTimeout(()=>{audFilter.q=v;refreshApp('audit')},220)}
