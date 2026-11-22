/* ================= token analytics app ================= */
/* ================= usage app =================
   Every call to an LLM is counted where it is made (usage.meter), in the account that made it:
   tokens in, out and in all, and dollars, the provider's own figure kept apart from our estimate.
   An admin also sees every account and sets which LLMs are shared and each account's daily quota.
   GUI here; TUI `bento usage llms|share|quota`; the agent answers through `usage_report`. */
var USAGE={days:1,d:null,rows:null};
function usageFmt(n){n=+n||0;return n>=1e6?(n/1e6).toFixed(2)+'M':n>=1e4?(n/1e3).toFixed(1)+'k':n.toLocaleString()}
function usageUsd(v){v=+v||0;return v===0?'$0':v<1?'$'+v.toFixed(4):'$'+v.toFixed(2)}
function usageMoneyWords(l){
  if(l.usd_exact&&l.usd_estimated)return `${usageUsd(l.usd_exact)} stated by the provider, ${usageUsd(l.usd_estimated)} estimated`;
  if(l.usd_estimated)return 'estimated from the price list';
  if(l.usd_exact)return 'as the provider stated it';
  return l.unpriced?'no price for this model':'';
}
async function renderTokens(body){
  let d;
  try{d=await apiJSON('/api/usage/llms?days='+USAGE.days+'&everyone=1')}
  catch(e){body.innerHTML=`<div class="pad"><p class="mut">${esc(e.message||'Usage could not be read.')}</p></div>`;return}
  USAGE.d=d;
  const llms=d.llms||[];
  const sum=llms.reduce((a,l)=>({in:a.in+l.in,out:a.out+l.out,usd:a.usd+l.usd,est:a.est+l.usd_estimated,calls:a.calls+l.calls}),{in:0,out:0,usd:0,est:0,calls:0});
  const when={1:'Today',7:'Last 7 days',30:'Last 30 days'}[USAGE.days]||'';
  const seg=`<div class="seg usg-days">${[[1,'Today'],[7,'7 days'],[30,'30 days']].map(([n,t])=>
    `<button class="${USAGE.days===n?'on':''}" onclick="USAGE.days=${n};refreshApp('tokens')">${t}</button>`).join('')}</div>`;
  const pb=panelShell(body,{title:'Token Analytics',sub:`${when} · ${sum.calls} call${sum.calls===1?'':'s'}`,actions:seg});
  const maxT=Math.max(1,...llms.map(l=>l.total));
  const days=(d.daily||[]).slice(-14),maxD=Math.max(1,...days.map(x=>x.in+x.out));
  const rows=llms.map(l=>{
    const q=l.quota;
    let qh='';
    if(q){
      const parts=[];
      if(q.tokens)parts.push(`${usageFmt(q.left_tokens)} of ${usageFmt(q.tokens)} tokens left`);
      if(q.usd)parts.push(`${usageUsd(q.left_usd)} of ${usageUsd(q.usd)} left`);
      const used=q.tokens?1-(q.left_tokens/q.tokens):1-(q.left_usd/q.usd);
      qh=`<div class="usg-q"><span>Today's quota: ${parts.join(', ')}</span><div class="bar"><i class="${used>=.9?'hot':''}" style="width:${Math.min(100,used*100)}%"></i></div></div>`;
    }
    return `<div class="usg-llm" data-f="${esc(l.name+' '+l.models.map(m=>m.model).join(' '))}">
      <div class="usg-top"><b>${esc(l.name)}</b><span class="usg-usd">${usageUsd(l.usd)}</span></div>
      <div class="usg-nums"><span>${l.calls} call${l.calls===1?'':'s'}</span><span>${usageFmt(l.in)} in</span><span>${usageFmt(l.out)} out</span><span>${usageFmt(l.total)} in all</span></div>
      <div class="bar"><i style="width:${l.total/maxT*100}%"></i></div>
      <div class="usg-how mut">${esc(usageMoneyWords(l))}${l.models.length>1?' · '+l.models.map(m=>esc(m.model.split('/').slice(1).join('/')||m.model)).join(', '):''}</div>
      ${qh}</div>`;
  }).join('');
  pb.innerHTML=`
    <div class="tmgrid">
      <div class="stat"><div class="lbl">In all</div><div class="val">${usageFmt(sum.in+sum.out)}</div></div>
      <div class="stat"><div class="lbl">Input</div><div class="val">${usageFmt(sum.in)}</div></div>
      <div class="stat"><div class="lbl">Output</div><div class="val">${usageFmt(sum.out)}</div></div>
      <div class="stat"><div class="lbl">Spent ${pInfo('A provider that states its bill (OpenRouter, an agent CLI) is counted as stated. Everything else is estimated from the price list, cached input included.')}</div><div class="val">${usageUsd(sum.usd)}${sum.est&&sum.est<sum.usd?` <small>${usageUsd(sum.est)} of it estimated</small>`:sum.est?' <small>estimated</small>':''}</div></div>
    </div>
    <div class="tmsec">${d.admin?'Yours, by LLM':'By LLM'}</div>
    ${rows||(d.admin?'<p class="mut">You haven\'t used a model yet. Every call is counted here as it happens.</p>'
      :emptyBox('Nothing yet','Every call to a model is counted here as it happens.','','tokens','What have I spent on each model this week?'))}
    ${days.length?`<div class="tmsec">By day</div>
    <div class="usg-chart">${days.map(x=>`<div class="usg-col"><div class="usg-bh"><div title="${esc(x.day)}: ${usageFmt(x.in+x.out)} tokens, ${usageUsd(x.usd)}" style="height:${(x.in+x.out)/maxD*100}%"></div></div><span>${esc(x.day.slice(5))}</span></div>`).join('')}</div>`:''}
    ${d.admin?usageAdminHTML(d):''}`;
  if(d.admin)usageQuotaPaint();
}
function usageAdminHTML(d){
  const ev=d.everyone||[];
  const llmIds=[...new Set(ev.flatMap(a=>a.llms.map(l=>l.llm)))];
  const table=ev.length>1||ev.some(a=>a.llms.length)?`<div class="usg-tw"><table class="usg-t"><thead><tr><th>Account</th>${llmIds.map(i=>`<th>${esc((ev.flatMap(a=>a.llms).find(l=>l.llm===i)||{}).name||i)}</th>`).join('')}<th>All</th></tr></thead><tbody>
    ${ev.map(a=>{const by=Object.fromEntries(a.llms.map(l=>[l.llm,l]));const tot=a.llms.reduce((s,l)=>({t:s.t+l.total,u:s.u+l.usd}),{t:0,u:0});
      return `<tr><td>${esc(a.name)}</td>${llmIds.map(i=>by[i]?`<td>${usageFmt(by[i].total)}<small>${usageUsd(by[i].usd)}</small></td>`:'<td class="mut">–</td>').join('')}<td><b>${usageFmt(tot.t)}</b><small>${usageUsd(tot.u)}</small></td></tr>`}).join('')}
    </tbody></table></div>`:'<p class="mut">No account has used a model yet.</p>';
  USAGE.rows=usageQuotaRows(d.sharing||{});
  return `<div class="tmsec">Everyone</div>${table}
    <div class="tmsec">Shared LLMs and daily quotas ${pInfo('Unlimited unless you set a limit. A limit for Everyone applies to each account without its own, and never to an admin. A day ends at midnight here.')}</div>
    <div class="usg-share">${usageShareable(d).map(p=>`<label class="usg-chk ck"><input type="checkbox" data-p="${esc(p.id)}" ${((d.sharing||{}).off||[]).includes(p.id)?'':'checked'}><span>${esc(p.name)}</span></label>`).join('')||'<p class="mut">No provider is switched on yet.</p>'}</div>
    <div id="usg-quotas"></div>
    <div class="row usg-act"><button onclick="usageQuotaAdd()">＋ Add a limit</button><button class="pact" onclick="usageSave()">Save</button></div>`;
}
/* The providers worth a tick: switched on, or already not shared. One switched off shares nothing. */
function usageShareable(d){
  const off=((d.sharing||{}).off)||[];
  return (d.providers||[]).filter(p=>p.on||off.includes(p.id));
}
function usageQuotaRows(sh){
  const out=[];
  for(const [who,per] of Object.entries(sh.quota||{}))for(const [llm,lim] of Object.entries(per||{}))
    out.push({who,llm,tokens:lim.tokens||'',usd:lim.usd||''});
  return out;
}
function usageQuotaPaint(){
  const box=$('#usg-quotas');if(!box)return;
  const d=USAGE.d||{},accs=d.accounts||[],provs=usageShareable(d);
  if(!USAGE.rows.length){box.innerHTML='<p class="mut">No limits: every account may use every shared LLM as much as it likes.</p>';return}
  box.innerHTML=USAGE.rows.map((r,i)=>`<div class="usg-qrow" data-i="${i}">
    <select data-k="who"><option value="*">Everyone</option>${accs.map(a=>`<option value="${esc(a.id)}" ${r.who===a.id?'selected':''}>${esc(a.name)}</option>`).join('')}</select>
    <select data-k="llm">${provs.map(p=>`<option value="${esc(p.id)}" ${r.llm===p.id?'selected':''}>${esc(p.name)}</option>`).join('')}${r.llm&&!provs.some(p=>p.id===r.llm)?`<option selected value="${esc(r.llm)}">${esc(r.llm)}</option>`:''}</select>
    <label><input data-k="tokens" type="number" min="0" step="1000" placeholder="no limit" value="${esc(r.tokens)}"><span>tokens a day</span></label>
    <label><input data-k="usd" type="number" min="0" step="0.5" placeholder="no limit" value="${esc(r.usd)}"><span>$ a day</span></label>
    <button aria-label="Remove this limit" onclick="USAGE.rows.splice(${i},1);usageQuotaPaint()">✕</button></div>`).join('');
  box.querySelectorAll('.usg-qrow [data-k]').forEach(el=>el.onchange=()=>{
    const r=USAGE.rows[+el.closest('.usg-qrow').dataset.i];if(r)r[el.dataset.k]=el.value});
  USAGE.rows.forEach((r,i)=>{const s=box.querySelector(`.usg-qrow[data-i="${i}"] [data-k="who"]`);if(s)s.value=r.who});
}
function usageQuotaAdd(){
  const p=usageShareable(USAGE.d||{})[0];
  USAGE.rows.push({who:'*',llm:p?p.id:'',tokens:'',usd:''});usageQuotaPaint();
}
async function usageSave(){
  const off=[...document.querySelectorAll('.usg-share input[data-p]')].filter(x=>!x.checked).map(x=>x.dataset.p);
  const quota={};
  for(const r of USAGE.rows){
    const t=+r.tokens||0,u=+r.usd||0;if(!r.llm||!(t||u))continue;
    (quota[r.who]=quota[r.who]||{})[r.llm]={...(t?{tokens:t}:{}),...(u?{usd:u}:{})};
  }
  const r=await fetch('/api/usage/sharing',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({off,quota})});
  const j=await r.json().catch(()=>({}));
  if(!r.ok)return toast(j.error||'Could not save the quotas.',{kind:'err'});
  toast(j.dropped&&j.dropped.length?`Saved. Left out: ${j.dropped.join(', ')}`:'Saved the shared LLMs and quotas.');
  refreshApp('tokens');
}

/* ================= snapshots app ================= */
async function renderSnapshots(body){
  const d=await (await fetch('/api/snapshots')).json();
  const snaps=d.snapshots||[];
  const items=snaps.map(s=>`<div class="item" data-f="${esc(s.label||('Snapshot '+s.id))}">
      <div class="grow"><b>${esc(s.label||('Snapshot '+s.id))}</b>
        <div class="sub">${new Date((s.created_at||s.id)*1000).toLocaleString()}${s.has_source?' · includes source':''}</div></div>
      <button class="endbtn" onclick="snapRestore('${jsq(s.id)}')">↩ Restore</button>
      <button onclick="snapDel('${jsq(s.id)}')">✕</button></div>`).join('');
  const pb=panelShell(body,{
    title:'Snapshots',
    sub:`${snaps.length} restore point${snaps.length===1?'':'s'}`,
    search:{id:'snap-q',placeholder:'Search snapshots…'},
  });
  pb.innerHTML=`
    <div class="row"><input id="snap-label" placeholder="label (e.g. before WhatsApp experiment)">
      <button class="pact" style="flex:0 0 130px" onclick="snapCreate()">Snapshot now</button></div>
    <p class="mut" style="margin:8px 0 14px">A snapshot saves your settings, data (apps, widgets, memory), and the OS source code. Restoring rolls everything back and restarts.</p>
    ${items||emptyBox('No snapshots yet','Take one before risky changes — especially before letting the agent modify its own code.','','snapshots','Take a snapshot now and explain what it protects.')}`;
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
    title:'Rules',
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

