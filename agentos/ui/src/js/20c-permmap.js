/* ================= Permissions → Policy map: who reaches what =================
   A map in two columns: on the left who has rules (your agent, specialists, missions,
   apps, linked teams), on the right what those rules reach (tools, files, the web,
   agents…), and one line per pair, green when it only allows, red when it only refuses,
   amber when it does both. Tap either end and the other lines step back, and the rules
   behind it are listed under the map in plain words, with the switches to change them.
   Everyone with no rules is one line: they ask first for everything, so there is
   nothing to draw.
   It reads the same grants as All grants (PERM.grants via permPrincipals), never a
   copy. Phone: no lines (a 390px screen has no room for two columns), the lists and
   the rules stay. TUI: `bento grants list`. `var` state: the bundle's TDZ rule. */
var PM_AREAS=[
  ['Everything','✱',a=>a==='*'],
  ['Tools','⚒',a=>a==='tool.use'||a==='legacy policy'],
  ['Files','▤',a=>a.startsWith('fs.')],
  ['Web','◎',a=>a.startsWith('net.')||a.startsWith('browser.')],
  ['Agents','◈',a=>a.startsWith('agent.')||a.startsWith('team.')||a.startsWith('pool.')],
  ['Memory','◉',a=>a.startsWith('memory.')||a.startsWith('kg.')],
  ['Connections','⧉',a=>a.startsWith('mcp.')||a.startsWith('skill.')||a.startsWith('plugin.')],
  ['Mail & calendar','✉',a=>a.startsWith('mail.')||a.startsWith('calendar.')],
  ['Models','✦',a=>a.startsWith('model.')],
  ['App data','▢',a=>a.startsWith('app.data')],
];
function pmArea(action){const a=PM_AREAS.find(x=>x[2](action||''));return a?a[0]:'Other'}
var PM_GROUPS=[['user','Your agent'],['subagent','Specialists'],['flow','Missions'],['app','Apps'],['team','Linked teams']];

/* An old command pattern ("run_command git *", "mcp_memory_*") as words. */
function pmPattern(m){
  m=String(m||'').trim();const sp=m.indexOf(' ');
  const tool=sp<0?m:m.slice(0,sp),rest=sp<0?'':m.slice(sp+1).trim();
  const tidy=x=>x.replace(/\s+\*$/,' …').replace(/\*$/,'…');
  if(tool==='run_command')return rest&&rest!=='*'?'run '+tidy(rest):'run any command';
  return 'use '+tidy(tool)+(rest&&rest!=='*'?' with '+tidy(rest):'');
}
/* One rule in a sentence: "may run git status…", "may not write files in /etc". */
function pmSay(g){
  const a=g.action||'',r=String(g.resource||''),v=r.replace(/^(tool|fs|net|agent|mcp|skill|model|memory|kg|app|mail|calendar|site):/,'');
  const glob=x=>x.replace(/\*$/,'…')||'anything';
  const tool=v.replace(/\*$/,'');
  const what=
    a==='*'?'do anything'
    :a==='legacy policy'?pmPattern(r)
    :a==='tool.use'?(tool.startsWith('run_command ')?'run '+glob(tool.slice(12)+(v.endsWith('*')?'*':''))
      :tool==='run_command'?'run any command':tool?'use '+tool:'use any tool')
    :a==='fs.read'?'read files in '+glob(v)
    :a==='fs.write'?'write files in '+glob(v)
    :a==='net.fetch'?(v==='*'?'fetch any web address':'fetch '+glob(v.replace(/^https?:\/\//,'')))
    :a==='agent.invoke'?(v==='main'?'start your agent':'hand work to '+glob(v.replace(/^subagent\//,'')))
    :a==='agent.message'?'ask '+glob(v.replace(/^subagent\//,''))
    :a==='memory.read'?'read memory':a==='memory.write'?'write memory'
    :a==='kg.read'?'read the knowledge graph':a==='kg.write'?'write the knowledge graph'
    :a==='mcp.use'?(v.endsWith('/*')?'use every tool of '+v.slice(0,-2):'use '+v)
    :a==='skill.use'?'use the skill '+glob(v)
    :a==='model.use'?'use the model '+glob(v)
    :a.startsWith('app.data')?(a.endsWith('read')?'read':a.endsWith('write')?'write':'read and write')+' its own data'
    :a==='mail.read'?'read your mail':a==='calendar.read'?'read your calendar'
    :a+' '+r;
  return (g.effect==='deny'?'may not ':'may ')+what;
}
function pmSource(g){
  const s=g.source||'user',ref=String(g.source_ref||'');
  if(ref.startsWith('conv:'))return 'remembered in a chat';
  if(s==='definition'&&ref.startsWith('flow:'))return 'mission '+ref.slice(5);
  return ({user:'you',manifest:'its manifest',matrix:'team matrix',legacy:'old full access',
    definition:'its definition',remembered:'remembered',pass:'guest pass','Rules tab':'a pattern'})[s]||s;
}
function pmWhoLabel(p){
  if(p.kind==='user')return (typeof agentName==='function'?agentName():'Your agent');
  if(p.kind==='team')return String(p.id||'').replace(/\/\*$/,'')||'a linked team';
  return p.label&&!/^(flow|subagent|app) "/.test(p.label)?p.label:(p.id||p.kind);
}
function pmTone(gs){const d=gs.filter(g=>g.effect==='deny').length;return d===gs.length?'deny':d?'mixed':'allow'}

function permMap(box){
  const q=PERM.q.toLowerCase();
  const all=permPrincipals().map(p=>({...p,name:pmWhoLabel(p)}));
  const ruled=all.filter(p=>p.grants.length&&(!q||p.name.toLowerCase().includes(q)||p.kind.includes(q)));
  const idle=all.filter(p=>!p.grants.length);
  PERM._mapPs=ruled;
  // (who, area) → rules: the lines
  const pairs={},areas={};
  ruled.forEach((p,i)=>p.grants.forEach(g=>{const ar=pmArea(g.action);
    (pairs[i+'|'+ar]=pairs[i+'|'+ar]||[]).push(g);(areas[ar]=areas[ar]||[]).push(g)}));
  const areaList=[...PM_AREAS.map(a=>a[0]),'Other'].filter(a=>areas[a]);
  const sel=PERM.sel||'';
  if(sel.startsWith('who:')&&!ruled.some(p=>'who:'+p.kind+':'+p.id===sel))PERM.sel=null;
  const pending=PERM.apps.filter(a=>(a.manifest_status||'none')==='proposed').length;
  const full=ruled.filter(p=>p.grants.some(g=>g.action==='*'&&(g.resource||'*')==='*'&&g.effect!=='deny'));
  const icon=a=>(PM_AREAS.find(x=>x[0]===a)||[0,'•'])[1];
  const groups=PM_GROUPS.map(([k,l])=>[l,ruled.map((p,i)=>[p,i]).filter(([p])=>p.kind===k)])
    .concat([['Others',ruled.map((p,i)=>[p,i]).filter(([p])=>!PM_GROUPS.some(g=>g[0]===p.kind))]])
    .filter(g=>g[1].length);
  box.innerHTML=`<p class="mut pm-lead">Who has rules, and what they reach. Tap a name or a place to see its rules in plain words.</p>
    ${full.length?`<div class="pm-note pm-bad">${full.map(p=>esc(p.name)).join(', ')} ${full.length===1?'has':'have'} full access to everything.</div>`:''}
    ${pending?`<div class="pm-note">${pending} app${pending===1?' is':'s are'} waiting for you to review ${pending===1?'its':'their'} permissions. <button class="endbtn" onclick="PERM.tab='review';refreshApp('permissions')">Review</button></div>`:''}
    <div class="pm-map" id="pm-map">
      <div class="pm-col pm-who">${groups.map(([l,ps])=>`<div class="pm-grp">${esc(l)}</div>`+ps.map(([p,i])=>{
        const k='who:'+p.kind+':'+p.id;
        return `<button class="pm-node${sel===k?' on':''}" data-who="${i}">
          <span class="pm-av" style="background:${tileBg(p.id||p.kind)}">${esc((p.name[0]||'?').toUpperCase())}</span>
          <span class="pm-nm">${esc(p.name)}</span><span class="pm-ct">${p.grants.length}</span></button>`}).join('')).join('')
        ||'<p class="mut">Nobody has rules yet.</p>'}
        ${idle.length&&!q?`<div class="pm-idle" title="${esc(idle.map(p=>pmWhoLabel(p)).join(', '))}">${idle.length} more with no rules: they ask you first for everything.</div>`:''}
      </div>
      <svg class="pm-lines" id="pm-lines" aria-hidden="true"></svg>
      <div class="pm-col pm-what">${areaList.map(a=>{
        const gs=areas[a],d=gs.filter(g=>g.effect==='deny').length;
        return `<button class="pm-node pm-area${sel==='area:'+a?' on':''}" data-area="${esc(a)}">
          <span class="pm-ic">${icon(a)}</span><span class="pm-nm">${esc(a)}</span>
          <span class="pm-ct">${gs.length-d?`<i class="ok">${gs.length-d}</i>`:''}${d?`<i class="no">${d}</i>`:''}</span></button>`}).join('')}
        <div class="pm-legend"><span><i class="pm-sw allow"></i>allows</span><span><i class="pm-sw deny"></i>refuses</span><span><i class="pm-sw mixed"></i>both</span></div>
        <div id="pm-detail"></div>
      </div>
    </div>`;
  box.querySelectorAll('.pm-node[data-who]').forEach(b=>b.onclick=()=>{
    const p=PERM._mapPs[+b.dataset.who],k='who:'+p.kind+':'+p.id;PERM._pmAll=false;PERM.sel=PERM.sel===k?null:k;permMap(box);pmShowDetail()});
  box.querySelectorAll('.pm-node[data-area]').forEach(b=>b.onclick=()=>{
    const k='area:'+b.dataset.area;PERM._pmAll=false;PERM.sel=PERM.sel===k?null:k;permMap(box);pmShowDetail()});
  PERM._pairs=pairs;
  pmDetail();
  pmLines();
  pmShowDetail();
  // the lines follow the layout: a window resized, a font that arrived late
  try{if(PERM._ro)PERM._ro.disconnect();PERM._ro=new ResizeObserver(()=>pmLines());PERM._ro.observe($('#pm-map'))}catch(e){}
  // the places column is sticky, so its end of every line moves as the names scroll
  const sc=box.closest('#perm-body')||box;
  try{if(PERM._ro2)PERM._ro2.disconnect();PERM._ro2=new ResizeObserver(()=>pmShowDetail());PERM._ro2.observe(sc)}catch(e){}
  if(!sc._pmScroll){let raf=0;sc._pmScroll=()=>{if(raf||PERM.tab!=='map')return;raf=requestAnimationFrame(()=>{raf=0;pmLines();pmShowDetail()})};
    sc.addEventListener('scroll',sc._pmScroll,{passive:true})}
}
/* The rules sit in the sticky column under the places, so they are in view wherever the
   names are scrolled; their own box scrolls, sized to what is left of the window. */
function pmShowDetail(){
  const d=$('#pm-detail'),sc=$('#perm-body');if(!d||!sc)return;
  if(document.body.classList.contains('dev-mobile')){d.style.maxHeight='';
    if(d.firstElementChild)d.scrollIntoView({block:'nearest',behavior:'smooth'});return}
  const top=d.getBoundingClientRect().top-sc.getBoundingClientRect().top;
  d.style.maxHeight=Math.max(220,sc.clientHeight-Math.max(0,top)-20)+'px';
}

function pmLines(){
  const svg=$('#pm-lines'),map=$('#pm-map');if(!svg||!map)return;
  const mr=map.getBoundingClientRect(),sr=svg.getBoundingClientRect();
  if(!sr.width){svg.innerHTML='';return}
  svg.setAttribute('viewBox',`0 0 ${sr.width} ${sr.height}`);
  const sel=PERM.sel||'';
  const who={},area={};
  map.querySelectorAll('.pm-node[data-who]').forEach(n=>{const r=n.getBoundingClientRect();who[n.dataset.who]=r.top+r.height/2-sr.top});
  map.querySelectorAll('.pm-node[data-area]').forEach(n=>{const r=n.getBoundingClientRect();area[n.dataset.area]=r.top+r.height/2-sr.top});
  const w=sr.width,out=[];
  Object.entries(PERM._pairs||{}).forEach(([k,gs])=>{
    const [i,a]=k.split('|');if(who[i]==null||area[a]==null)return;
    const p=PERM._mapPs[+i],me=sel==='who:'+p.kind+':'+p.id||sel==='area:'+a;
    const cls='pm-ln '+pmTone(gs)+(sel?(me?' hi':' lo'):'');
    const y1=who[i],y2=area[a],sw=Math.min(1.2+Math.log2(gs.length+1),5);
    out.push(`<path class="${cls}" stroke-width="${sw.toFixed(1)}" d="M0,${y1.toFixed(1)} C${w*.5},${y1.toFixed(1)} ${w*.5},${y2.toFixed(1)} ${w},${y2.toFixed(1)}"><title>${esc(pmWhoLabel(p))} → ${esc(a)}: ${gs.length} rule${gs.length===1?'':'s'}</title></path>`);
  });
  // the highlighted lines last, so they are drawn over the faded ones
  out.sort((x,y)=>(x.includes(' hi')?1:0)-(y.includes(' hi')?1:0));
  svg.innerHTML=out.join('');
}

/* Under the map: the selected end's rules, each a sentence with its switches. */
function pmDetail(){
  const el=$('#pm-detail');if(!el)return;
  const sel=PERM.sel||'';
  if(!sel){el.innerHTML='<p class="mut pm-empty">Tap a name or a place to see its rules.</p>';return}
  const row=pmRuleRow;
  const CAP=40;
  const block=(title,gs,whoOf)=>{
    const more=gs.length>CAP&&!PERM._pmAll;
    return `<div class="pm-sec"><div class="pm-sech">${esc(title)} <span class="mut">${gs.length}</span></div>
      ${(more?gs.slice(0,CAP):gs).map(g=>row(g,whoOf&&whoOf(g))).join('')}
      ${more?`<button class="endbtn" onclick="PERM._pmAll=true;pmDetail()">Show all ${gs.length}</button>`:''}</div>`};
  if(sel.startsWith('who:')){
    const p=PERM._mapPs.find(p=>'who:'+p.kind+':'+p.id===sel);if(!p){el.innerHTML='';return}
    const by={};p.grants.forEach(g=>{const a=pmArea(g.action);(by[a]=by[a]||[]).push(g)});
    const order=[...PM_AREAS.map(a=>a[0]),'Other'].filter(a=>by[a]);
    const traceable=p.kind==='user'||p.kind==='subagent'||p.kind==='app';
    el.innerHTML=`<div class="pm-card">
      <div class="pm-cardh"><b>${esc(pmWhoLabel(p))}</b> <span class="mut">${esc({user:'your agent',subagent:'specialist',flow:'mission',app:'app',team:'linked team'}[p.kind]||p.kind)} · ${p.grants.length} rule${p.grants.length===1?'':'s'}</span>
        <span class="pm-acts">${traceable?`<button class="endbtn" onclick="pmTrace()">Trace a request</button>`:''}
        ${p.kind!=='user'&&p.kind!=='flow'&&p.kind!=='team'?`<button class="endbtn" onclick="pmAdd()">＋ Add a rule</button>`:''}</span></div>
      <p class="mut pm-hint">Anything not listed here goes to the default: ${p.kind==='user'?'your autonomy setting decides, or you are asked':'you are asked first'}.</p>
      ${order.map(a=>block(a,by[a])).join('')}</div>`;
  }else{
    const a=sel.slice(5),gs=[];
    PERM._mapPs.forEach(p=>p.grants.forEach(g=>{if(pmArea(g.action)===a)gs.push([p,g])}));
    el.innerHTML=`<div class="pm-card"><div class="pm-cardh"><b>${esc(a)}</b> <span class="mut">who has a rule here · ${gs.length}</span></div>
      ${block('Rules',gs.map(x=>x[1]),g=>{const x=gs.find(y=>y[1]===g);return x?pmWhoLabel(x[0]):''})}</div>`;
  }
}
/* One rule as a row: the switch, the sentence, where it came from, remove. Shared by
   the map and the Rules tab so a rule reads the same wherever it is shown; the raw
   action and resource are the tooltip, for whoever needs them. */
function pmRuleRow(g,whoName){
  const ro=g.readonly||String(g.id||'').startsWith('legacy:');
  const dead=!!g.revoked_at;
  const deny=g.effect==='deny';
  const tech=(g.action||'')+' · '+(g.resource||'')+(g.note?' — '+g.note:'');
  return `<div class="pm-rule ${deny?'deny':'allow'}${dead?' dead':''}" title="${esc(tech)}">
    ${ro||dead?`<span class="pm-eff">${deny?'✕':'✓'}</span>`
      :`<button class="pm-eff" title="switch to ${deny?'allow':'refuse'}" aria-label="switch to ${deny?'allow':'refuse'}" onclick="permToggle('${g.id}','${deny?'allow':'deny'}')">${deny?'✕':'✓'}</button>`}
    <div class="pm-say">${whoName?`<b>${esc(whoName)}</b> `:''}${esc(pmSay(g))}
      <span class="pm-src">${esc(pmSource(g))}${g.created_at?` · <span title="${esc(new Date(g.created_at*1000).toLocaleString())}">${deny?'set':'approved'} ${esc(pmWhen(g.created_at))}</span>`:''}</span>${permLasts(g)}${dead?`<span class="badge" title="${esc(new Date(g.revoked_at*1000).toLocaleString())}">removed ${esc(pmWhen(g.revoked_at))}</span>`:''}</div>
    ${dead?'':ro?`<button class="pm-x" title="Edit in Patterns" aria-label="Edit in Patterns" onclick="PERM.tab='rules';refreshApp('permissions')">↗</button>`
      :`${g.surfaces&&g.surfaces!=='*'?permSurfBadge(g):''}<button class="pm-x" title="Remove this rule" aria-label="Remove this rule" onclick="permRevoke('${g.id}')">✕</button>`}
  </div>`;
}
/* "today 20:41", "yesterday 09:12", "18 Oct", "3 Mar 2025": when a rule was made. */
function pmWhen(ts){
  const t=new Date(ts*1000),now=new Date();
  const hm=t.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
  if(t.toDateString()===now.toDateString())return 'today '+hm;
  if(new Date(now-864e5).toDateString()===t.toDateString())return 'yesterday '+hm;
  return t.toLocaleDateString([],t.getFullYear()===now.getFullYear()?{day:'numeric',month:'short'}:{day:'numeric',month:'short',year:'numeric'});
}
function pmSelP(){return PERM._mapPs.find(p=>'who:'+p.kind+':'+p.id===PERM.sel)}
function pmTrace(){
  const p=pmSelP();if(!p)return;
  PF.who=p.kind+':'+(p.kind==='user'?'':p.id);PF.trace=null;PF.pick=null;
  PERM.tab='flow';refreshApp('permissions');
}
function pmAdd(){
  const p=pmSelP();if(!p)return;
  PERM.att={p,action:'tool.use',res:new Set(),effect:'allow',surf:new Set()};
  PERM.tab='attach';refreshApp('permissions');
}
