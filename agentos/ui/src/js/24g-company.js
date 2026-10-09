/* ================= Your company, in the Office (agentos/company.py) =================
   "Imagine your startup: Admin, HR, Finance, Supply, Sales, Tech, Marketing." The
   Office's ▦ Company panel sets that up from a sentence and then runs it: each
   department's card over its room says what it is doing, and a task typed for a
   department is a run of its desk (a flow), so it goes through the gate and shows in
   the Run inspector like any mission.

   Three rules this file keeps:
   - The whole plan is on screen before anything is made, and the counts on the button
     come from /api/company/preview, the same computation the save re-derives.
   - The numbers on a card are counts of runs, approvals and triggers from the server.
     Nothing here estimates or invents a figure.
   - The cards and the panel belong to the Office WINDOW. The desktop scene is under
     every window and cannot be tapped, so it draws none of this.
   - The auditor's verdict on a task is read from the audit run the server keeps
     (company.audit_state); the page never decides whether work passed.
   Faces: GUI and SUI are this page. TUI is `bento company` (show, setup, task, audit,
   check). */
var COMPANY={data:null,plan:null,preview:null,how:'',said:'',dropped:[],open:false,
  filter:'all',focus:'',arrival:null,timer:0,pv:0,talk:true,off:{}};

function companyWindow(){return OFFICE.w&&!OFFICE.w.scene?OFFICE.w:null}

async function companyLoad(){
  if(!companyWindow())return;
  try{COMPANY.data=await apiJSON('/api/company')}
  catch(e){COMPANY.data=null;COMPANY.err=e.message||String(e)}
  companyCards();
  if(COMPANY.open)companyPaint();
}
/* Work started or ended, or an approval came or went: read the counts again, once. */
function companySoon(){
  if(!companyWindow())return;
  clearTimeout(COMPANY.timer);COMPANY.timer=setTimeout(companyLoad,1200);
}

/* ---------------- the cards over the rooms ---------------- */
function companyCards(){
  const w=companyWindow();if(!w)return;
  const host=w.el.querySelector('.of-cards');if(!host)return;
  const O=OFFICE,d=COMPANY.data;
  if(!O.L||!d||!d.departments||!d.departments.length){host.innerHTML='';return}
  host.style.width=O.cw+'px';host.style.height=O.ch+'px';
  const by={};d.departments.forEach(s=>by[s.name.toLowerCase()]=s);
  host.innerHTML=O.L.rooms.filter(r=>r.kind==='dept'&&by[r.name.toLowerCase()]).map(r=>{
    const s=by[r.name.toLowerCase()];
    const next=s.next_at?companyWhen(s.next_at):'';
    const tip=`${s.name}: ${s.doing} doing, ${s.waiting} waiting for you, ${s.done} done this week`
      +(s.failed?`, ${s.failed} failed`:'')+(s.flagged?`, ${s.flagged} flagged by the auditor`:'')
      +(next?`, next run ${next}`:'')+'. Tap to give it a task.';
    const x=Math.round((r.x+r.w)*O.s)-8,y=Math.round((r.y+8)*O.s);
    return `<button class="co-card${s.waiting?' wait':''}${s.doing?' busy':''}" style="right:${Math.max(4,O.cw-x)}px;top:${y}px"
      data-dept="${esc(s.name)}" title="${esc(tip)}" aria-label="${esc(tip)}">
      <span class="co-n">${s.people}<small> ${s.people===1?'agent':'agents'}</small></span>
      <span class="co-k" data-s="▶"><i>doing</i>${s.doing}</span><span class="co-k" data-s="⏱"><i>next</i>${s.next}</span>
      <span class="co-k" data-s="✓"><i>done</i>${s.done}</span>${s.waiting?`<span class="co-w">⚠ ${s.waiting}</span>`:''}${
      s.flagged?`<span class="co-fl">⚑ ${s.flagged}</span>`:''}</button>`;
  }).join('');
  host.querySelectorAll('.co-card').forEach(b=>b.onclick=()=>{COMPANY.focus=b.dataset.dept;officeCompany(true)});
  companyCardsFit(host);
}
/* A card never covers its room's name. It goes beside the sign in the wall band; where
   the room is too narrow it drops its words, and where even that does not fit it sits
   just under the band. The sign's width is measured the way officeRoomBg draws it. */
function companyCardsFit(host){
  const O=OFFICE,ctx=O.ctx;if(!ctx)return;
  host.querySelectorAll('.co-card').forEach(c=>{
    const r=O.L.rooms.find(q=>q.kind==='dept'&&q.name===c.dataset.dept);if(!r)return;
    ctx.save();ofFont(ctx,12.5,800);const tw=Math.min(r.w*.6,ctx.measureText(r.name.toUpperCase()).width+22);ctx.restore();
    const signRight=(r.x+10+tw+6)*O.s, left=()=>O.cw-parseFloat(c.style.right)-c.offsetWidth;
    if(left()>=signRight)return;
    c.classList.add('compact');
    if(left()>=signRight)return;
    c.style.top=Math.round((r.y+OF_WALL+6)*O.s)+'px';
  });
}
function companyWhen(t){
  const s=Math.max(0,t-Date.now()/1000);
  if(s<90)return 'in a minute';if(s<5400)return `in ${Math.round(s/60)} min`;
  if(s<129600)return `in ${Math.round(s/3600)} h`;return `in ${Math.round(s/86400)} days`;
}
function companyAgo(t){
  if(!t)return '';const s=Math.max(0,Date.now()/1000-t);
  if(s<60)return 'just now';if(s<3600)return `${Math.round(s/60)} min ago`;
  if(s<86400)return `${Math.round(s/3600)} h ago`;return `${Math.round(s/86400)} days ago`;
}

/* ---------------- the panel ---------------- */
function officeCompany(open){
  const O=OFFICE,w=companyWindow(),el=w&&w.el.querySelector('.of-company');if(!el)return;
  if(open){if(O.design)officeDesign(false);if(O.visiting!==undefined)officeVisit(null)}
  COMPANY.open=open;el.hidden=!open;
  const b=w.el.querySelector('.of-co');if(b)b.classList.toggle('on',open);
  if(open){companyPaint();companyLoad()}
}
function companyPaint(){
  const w=companyWindow(),el=w&&w.el.querySelector('.of-company');if(!el||el.hidden)return;
  const d=COMPANY.data;
  if(!d){el.innerHTML=`<div class="of-dh"><b>Your company</b><button class="of-x" aria-label="Close">✕</button></div>
    <div class="mut">${esc(COMPANY.err||'loading…')}</div>`;el.querySelector('.of-x').onclick=()=>officeCompany(false);return}
  if(COMPANY.plan)return companyPreviewPaint(el);
  if(!d.departments.length||COMPANY.adding)return companySetupPaint(el);
  companyOverviewPaint(el);
}

/* Set it up: a sentence, and the departments as chips. None ticked lets the brain choose. */
function companySetupPaint(el){
  const d=COMPANY.data,picked=COMPANY.picked||(COMPANY.picked=new Set());
  el.innerHTML=`<div class="of-dh"><b>${COMPANY.adding?'Add departments':'Set up your company'}</b><button class="of-x" aria-label="Close">✕</button></div>
    <p class="co-lead">Say what the business does. I'll draft the departments, a head and staff for each, and show you everything before anything is made.</p>
    <textarea class="co-desc" rows="3" maxlength="1200" placeholder="A coffee subscription startup, twelve people, selling online and shipping across India">${esc(COMPANY.desc||'')}</textarea>
    <div class="of-sec">Departments <span class="mut">${picked.size?picked.size+' ticked':'leave empty to let it choose'}</span></div>
    <div class="of-chips co-chips">${d.catalogue.map(c=>`<button class="of-chip${picked.has(c.id)?' on':''}" data-id="${c.id}" aria-pressed="${picked.has(c.id)}"
      title="${esc(c.mandate)}"><i class="of-sw" style="background:${OFFICE.view&&OFFICE.view.colors[c.color]||'#888'}"></i>${esc(c.label)}</button>`).join('')}</div>
    <div class="of-row co-go"><button class="endbtn primary co-draft">Draft my company</button>
      ${COMPANY.adding?'<button class="endbtn co-back">Back</button>':''}</div>
    <div class="of-said mut" aria-live="polite"></div>
    ${d.brain?'':'<p class="mut co-small">No AI brain is set up, so the draft comes from the catalogue as it is. You can edit every person before saving.</p>'}`;
  const q=s=>el.querySelector(s);
  q('.of-x').onclick=()=>officeCompany(false);
  q('.co-desc').oninput=e=>COMPANY.desc=e.target.value;
  el.querySelectorAll('.co-chips .of-chip').forEach(b=>b.onclick=()=>{
    const id=b.dataset.id;picked.has(id)?picked.delete(id):picked.add(id);companyPaint()});
  q('.co-draft').onclick=()=>companyDraft(q('.co-draft'),q('.of-said'));
  if(q('.co-back'))q('.co-back').onclick=()=>{COMPANY.adding=false;companyPaint()};
}
async function companyDraft(btn,said){
  const desc=(COMPANY.desc||'').trim(),ids=[...(COMPANY.picked||[])];
  if(desc.length<3&&!ids.length){toast('say what the company does, or tick some departments');return}
  btn.disabled=true;said.textContent='drafting your company… this can take a minute';
  try{
    const r=await fetch('/api/company/draft',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({description:desc,departments:ids,talk:COMPANY.talk})});
    const j=await r.json();
    if(!r.ok||j.error)throw new Error(j.error||('HTTP '+r.status));
    COMPANY.plan=j.plan;COMPANY.preview=j.preview;COMPANY.how=j.how;COMPANY.who=j.who;
    COMPANY.said=j.said||'';COMPANY.dropped=j.dropped||[];COMPANY.off={};
    companyPaint();
  }catch(e){said.textContent='could not draft it: '+(e.message||e)}
  finally{if(btn.isConnected)btn.disabled=false}
}

/* The plan, all of it: every department, every person, their persona and tools, and
   what saving does. Untick a person or a whole department; open a persona to edit it. */
function companyPlanNow(){
  const p=COMPANY.plan;if(!p)return null;
  return {company:p.company,departments:p.departments.filter(d=>!COMPANY.off['d:'+d.name]).map(d=>({...d,
    people:d.people.filter(x=>!COMPANY.off['p:'+x.name])})).filter(d=>d.people.length)};
}
function companyPreviewPaint(el){
  const P=COMPANY.plan,V=COMPANY.preview||{departments:[],notes:[]};
  const pv={};(V.departments||[]).forEach(d=>d.people.forEach(p=>pv[p.name]=p));
  const colors=(OFFICE.view&&OFFICE.view.colors)||{};
  const who=(typeof EXEC_TITLES!=='undefined'&&EXEC_TITLES[COMPANY.who])||COMPANY.who||'your AI';
  const how=COMPANY.how==='brain'?`Drafted by ${esc(who)}.`:esc(COMPANY.said||'Filled in from the catalogue.');
  el.innerHTML=`<div class="of-dh"><b>Your company, drafted</b><button class="of-x" aria-label="Close">✕</button></div>
    <p class="co-lead">${how} Nothing is made until you press the button at the bottom.</p>
    <div class="of-row"><input class="co-name" maxlength="48" placeholder="Company name" value="${esc(P.company.name||'')}" aria-label="Company name"></div>
    <div class="of-row"><input class="co-about" maxlength="200" placeholder="What it does, in one line" value="${esc(P.company.about||'')}" aria-label="What the company does"></div>
    ${P.departments.map(d=>{const doff=!!COMPANY.off['d:'+d.name];
      return `<div class="co-dept${doff?' off':''}" style="--dc:${colors[d.color]||'#888'}">
      <label class="co-dh"><input type="checkbox" data-d="${esc(d.name)}"${doff?'':' checked'}><i class="of-sw"></i><b>${esc(d.name)}</b></label>
      <div class="co-about mut">${esc(d.about||'')}</div>
      ${d.people.map(x=>{const off=doff||!!COMPANY.off['p:'+x.name],q=pv[x.name]||{};
        return `<div class="co-person${off?' off':''}">
        <label class="co-ph"><input type="checkbox" data-p="${esc(x.name)}"${off?'':' checked'}${doff?' disabled':''}>
          <span class="co-pn">${x.lead?'★ ':''}${esc(x.name)}</span><span class="co-pt">${esc(x.title)}</span>
          ${q.status==='exists'?'<span class="co-tag">already here</span>':''}</label>
        <details class="co-more"><summary>Persona and tools</summary>
          <textarea class="co-soul" data-s="${esc(x.name)}" rows="5" maxlength="1600" aria-label="Persona for ${esc(x.name)}">${esc(x.soul)}</textarea>
          <div class="co-tools">${(q.tools||x.tools).map(t=>`<code>${esc(t)}</code>`).join(' ')}</div>
          ${q.status==='exists'?'<div class="mut co-small">This agent exists already. It joins as it is and none of this is written over it.</div>':''}
        </details></div>`}).join('')}</div>`}).join('')}
    <label class="co-talk"><input type="checkbox" class="co-talkcb"${COMPANY.talk?' checked':''}> Colleagues in a department can ask each other, and the heads can ask each other</label>
    ${(V.notes||[]).map(n=>`<p class="mut co-small">${esc(n)}</p>`).join('')}
    ${COMPANY.dropped.length?`<p class="mut co-small">Left out of the draft: ${esc(COMPANY.dropped.join('; '))}</p>`:''}
    <p class="mut co-small">Each department gets a desk, a mission that starts switched off. Until you switch it on in Missions, any step that needs permission asks you first.</p>
    <div class="of-row co-go"><button class="endbtn primary co-apply"${V.fits===false?' disabled':''}>${companyButton(V)}</button>
      <button class="endbtn co-again">Start over</button></div>
    <div class="of-said mut" aria-live="polite"></div>`;
  const q=s=>el.querySelector(s);
  q('.of-x').onclick=()=>officeCompany(false);
  q('.co-name').oninput=e=>{P.company.name=e.target.value};
  q('.co-about').oninput=e=>{P.company.about=e.target.value};
  el.querySelectorAll('[data-d]').forEach(c=>c.onchange=()=>{COMPANY.off['d:'+c.dataset.d]=!c.checked;companyRepreview()});
  el.querySelectorAll('[data-p]').forEach(c=>c.onchange=()=>{COMPANY.off['p:'+c.dataset.p]=!c.checked;companyRepreview()});
  el.querySelectorAll('.co-soul').forEach(t=>t.oninput=()=>{P.departments.forEach(d=>d.people.forEach(x=>{if(x.name===t.dataset.s)x.soul=t.value}))});
  q('.co-talkcb').onchange=e=>{COMPANY.talk=e.target.checked;companyRepreview()};
  q('.co-again').onclick=()=>{COMPANY.plan=null;COMPANY.preview=null;companyPaint()};
  q('.co-apply').onclick=()=>companyApply(q('.co-apply'),q('.of-said'));
}
function companyButton(V){
  const n=V.new||0,d=V.desks||0;
  if(!d)return 'Nothing to make';
  return n?`Make ${n} ${n===1?'agent':'agents'} in ${d} ${d===1?'department':'departments'}`
    :`Set up ${d} ${d===1?'department':'departments'}`;
}
/* An untick changes what saving does: ask the server again, so the button counts what
   the save will make (one computation), then repaint. */
function companyRepreview(){
  clearTimeout(COMPANY.pv);
  COMPANY.pv=setTimeout(async()=>{
    const plan=companyPlanNow();if(!plan)return;
    try{
      const j=await apiJSON('/api/company/preview',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({plan,talk:COMPANY.talk})});
      COMPANY.preview=j.preview;
    }catch(e){}
    const el=companyWindow()&&companyWindow().el.querySelector('.of-company');
    if(el&&COMPANY.plan){const open=[...el.querySelectorAll('details[open] .co-soul')].map(t=>t.dataset.s);
      const top=el.scrollTop;companyPreviewPaint(el);el.scrollTop=top;
      open.forEach(n=>{const t=el.querySelector(`.co-soul[data-s="${CSS.escape(n)}"]`);if(t)t.closest('details').open=true})}
  },250);
}
async function companyApply(btn,said){
  const plan=companyPlanNow();if(!plan||!plan.departments.length){toast('tick at least one department');return}
  btn.disabled=true;said.textContent='making your company…';
  try{
    const r=await fetch('/api/company/apply',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({plan,talk:COMPANY.talk})});
    const j=await r.json();
    if(!r.ok||j.error)throw new Error(j.error||('HTTP '+r.status));
    COMPANY.arrival=j;COMPANY.plan=null;COMPANY.preview=null;COMPANY.adding=false;COMPANY.picked=new Set();COMPANY.desc='';
    officeLog(`company set up: ${j.departments.join(', ')}`);
    toast(`✓ ${j.departments.length} departments, ${j.made.length} new agents`);
    if(typeof avatarsLoad==='function')await avatarsLoad();
    await officeLoad();await companyLoad();
    const el=companyWindow()&&companyWindow().el.querySelector('.of-company');if(el)el.scrollTop=0;
  }catch(e){said.textContent='could not set it up: '+(e.message||e);btn.disabled=false}
}

/* The company at work: give a department a task, each department's line, and the board. */
function companyOverviewPaint(el){
  const d=COMPANY.data,A=COMPANY.arrival,colors=(OFFICE.view&&OFFICE.view.colors)||{};
  const focus=COMPANY.focus&&d.departments.find(x=>x.name===COMPANY.focus)?COMPANY.focus:(d.departments[0]||{}).name;
  const b=d.board||{tasks:[],counts:{}},f=COMPANY.filter;
  const tasks=b.tasks.filter(t=>f==='all'||t.status===f||(f==='in_progress'&&t.status==='stale')||(f==='failed'&&t.status==='stopped')
    ||(f==='flagged'&&companyFlagged(t)));
  const chip=(k,l)=>`<button class="of-chip${f===k?' on':''}" data-f="${k}" aria-pressed="${f===k}">${l}${k!=='all'&&b.counts[k]?' '+b.counts[k]:''}</button>`;
  const pill={in_progress:'working',waiting:'waiting for you',done:'done',failed:'failed',scheduled:'scheduled',
    stale:'stopped answering',stopped:'stopped'};
  el.innerHTML=`<div class="of-dh"><b>${esc(d.company.name||'Your company')}</b><button class="of-x" aria-label="Close">✕</button></div>
    ${d.company.about?`<p class="co-lead">${esc(d.company.about)}</p>`:''}
    ${A?`<div class="co-arrival"><b>✓ ${A.departments.length} departments set up.</b>
      ${A.made.length?` ${A.made.length} new agents.`:''}${A.joined.length?` ${esc(A.joined.join(', '))} joined as they were.`:''}
      Each desk starts off. ${A.try?esc(A.try):''}
      ${(A.errors||[]).map(e=>`<div class="co-bad">${esc(e)}</div>`).join('')}</div>`:''}
    <div class="of-sec">Give a department a task</div>
    <div class="of-row"><select class="co-dsel" aria-label="Department">${d.departments.map(x=>`<option${x.name===focus?' selected':''}>${esc(x.name)}</option>`).join('')}</select></div>
    <textarea class="co-task" rows="2" maxlength="2000" placeholder="${esc(companyHint(focus))}">${esc(COMPANY.task||'')}</textarea>
    <div class="of-row co-go"><button class="endbtn primary co-send">Send</button><span class="of-said mut co-tsaid" aria-live="polite"></span></div>
    <div class="of-sec">Departments <span class="mut">${d.brain_notes&&(d.brain_notes.memories||d.brain_notes.facts)?`shared memory: ${d.brain_notes.memories} notes, ${d.brain_notes.facts} facts`:''}</span></div>
    ${d.departments.map(x=>`<div class="co-line${x.name===focus?' on':''}" style="--dc:${colors[x.color]||'#888'}">
      <button class="co-lh" data-pick="${esc(x.name)}"><i class="of-sw"></i><b>${esc(x.name)}</b>
        <span class="mut">${x.people} · head ${esc(x.lead||'-')}</span></button>
      <div class="co-lk"><span>doing ${x.doing}</span><span>next ${x.next}</span><span>done ${x.done}</span>
        ${x.waiting?`<span class="co-w">⚠ ${x.waiting} waiting</span>`:''}${x.failed?`<span class="co-bad">${x.failed} failed</span>`:''}${
        x.flagged?`<span class="co-fl">⚑ ${x.flagged} flagged</span>`:''}</div>
      <div class="co-desk mut">${!x.has_desk?'No desk: tasks go to its head in chat.'
        :x.desk_on?'Desk on.':'Desk off, so gated steps ask you.'}
        ${x.has_desk?`<button class="co-link" data-desk="${esc(x.desk)}">${x.desk_on?'Open in Missions':'Switch on in Missions'}</button>`:''}</div>
    </div>`).join('')}
    <div class="of-row"><button class="endbtn co-add">＋ Add departments</button></div>
    <div class="of-sec">Tasks</div>
    <label class="co-audit"><input type="checkbox" class="co-aud"${b.audit!==false?' checked':''}>
      <span>An independent auditor checks every finished task</span>${typeof pInfo==='function'?pInfo('The auditor did none of the work and no department can skip it. Anything it flags goes to your Brief.'):''}</label>
    <div class="of-chips co-filter">${chip('all','All')}${chip('in_progress','Working')}${chip('waiting','Waiting')}${chip('scheduled','Scheduled')}${chip('done','Done')}${chip('flagged','Flagged')}${chip('failed','Failed')}</div>
    <div class="co-board">${tasks.length?tasks.slice(0,40).map(t=>`<button class="co-task-row" ${t.run_id?`data-run="${esc(t.run_id)}"`:''} style="--dc:${colors[t.color]||'#888'}">
      <span class="co-st ${t.status}">${esc(pill[t.status]||t.status)}</span>
      <span class="co-tt">${esc(t.task)}</span>
      <span class="co-tm mut">${esc(t.department)}${t.who?' · '+esc(t.who):''}${t.handoffs?` · ${t.handoffs} ${t.handoffs===1?'hand-over':'hand-overs'}`:''}
        · ${esc(t.status==='scheduled'?companyWhen(t.next_at):companyAgo(t.finished_at||t.started_at))}</span>
      ${t.said&&t.status!=='in_progress'?`<span class="co-said mut">${esc(t.said)}</span>`:''}
      ${companyAuditHTML(t)}
      ${(t.approvals||[]).length?`<span class="co-review" role="button" tabindex="0" data-ap="${esc(t.approvals.join(','))}">Review what it asks</span>`
        :t.in_brief&&t.status==='waiting'?'<span class="co-review" role="button" tabindex="0" data-brief="1">Answer it in the Brief</span>':''}</button>`).join('')
      :`<p class="mut co-small">${f==='all'?'No tasks yet. Give a department one above.':'Nothing here.'}</p>`}</div>`;
  const q=s=>el.querySelector(s);
  q('.of-x').onclick=()=>{COMPANY.arrival=null;officeCompany(false)};
  q('.co-dsel').onchange=e=>{COMPANY.focus=e.target.value;companyPaint()};
  q('.co-task').oninput=e=>COMPANY.task=e.target.value;
  q('.co-task').onkeydown=e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey))q('.co-send').click()};
  q('.co-send').onclick=()=>companyTask(q('.co-dsel').value,q('.co-task'),q('.co-send'),q('.co-tsaid'));
  el.querySelectorAll('[data-pick]').forEach(b=>b.onclick=()=>{COMPANY.focus=b.dataset.pick;companyPaint();
    const t=el.querySelector('.co-task');if(t)t.focus()});
  el.querySelectorAll('[data-desk]').forEach(b=>b.onclick=()=>{
    if(typeof FLOW_FOCUS!=='undefined')FLOW_FOCUS=b.dataset.desk;
    if(typeof fabTab!=='undefined')fabTab='flows';
    openApp('fabric');refreshApp('fabric')});
  el.querySelectorAll('[data-f]').forEach(b=>b.onclick=()=>{COMPANY.filter=b.dataset.f;companyPaint()});
  q('.co-aud').onchange=e=>companyAuditSwitch(e.target);
  el.querySelectorAll('[data-run]').forEach(b=>b.onclick=e=>{
    const ap=e.target.closest('[data-ap]');if(ap)return companyReview(ap.dataset.ap.split(','));
    const ck=e.target.closest('[data-check]');if(ck)return companyCheck(b.dataset.run,ck);
    if(e.target.closest('[data-brief]'))return openApp('brief');
    if(typeof fgWatch==='function')fgWatch(b.dataset.run)});
  q('.co-add').onclick=()=>{COMPANY.adding=true;COMPANY.arrival=null;companyPaint()};
}
/* ---------------- the independent auditor (company.py, fabric ControlPlane.audit) ---------------- */
function companyFlagged(t){const v=(t.audit||{}).verdict;return v==='concerns'||v==='fail'}
/* One line under a task: what the auditor said, or that it is still reading. A task it
   has not checked (the switch was off, or the check could not run) offers Check it. */
function companyAuditHTML(t){
  const a=t.audit||{},first=(a.findings||[])[0]||'';
  const check=t.can_check?`<span class="co-review co-check" role="button" tabindex="0" data-check="1">${a.verdict?'Check it again':'Check it'}</span>`:'';
  if(a.state==='checking')return `<span class="co-au checking">${avatarImgSafe('auditor')} The auditor is checking this…</span>`;
  if(a.verdict==='pass')return `<span class="co-au pass">✓ Checked by the auditor${first?': '+esc(first):''}</span>`;
  if(a.verdict==='concerns')return `<span class="co-au concerns">⚑ The auditor has concerns: ${esc(first||'see the run')}</span>`;
  if(a.verdict==='fail')return `<span class="co-au fail">✗ The auditor failed this: ${esc(first||'see the run')}</span>`;
  if(a.verdict)return `<span class="co-au none">Not checked: ${esc(a.why||'the auditor gave no verdict')}</span>${check}`;
  return t.status==='done'?check:'';
}
function avatarImgSafe(name){return typeof avatarImg==='function'?avatarImg(name,'co-av'):''}
async function companyAuditSwitch(box){
  const on=box.checked;box.disabled=true;
  try{
    const j=await apiJSON('/api/company',{method:'PUT',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({audit:on})});
    if(j.error)throw new Error(j.error);
    toast(on?'The auditor checks every finished task again':'Finished tasks are not checked now');
    companyLoad();
  }catch(e){box.checked=!on;toast(e.message||String(e))}
  finally{box.disabled=false}
}
async function companyCheck(runId,el){
  el.textContent='asking the auditor…';
  try{
    const j=await apiJSON('/api/company/audit',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({run_id:runId})});
    if(j.error)throw new Error(j.error);
    companySoon();
  }catch(e){el.textContent=e.message||String(e)}
}
function companyHint(name){
  const t={admin:'List what is due this week and who owes it.',hr:'Draft a job description for our next hire.',
    finance:'Summarise what we spend each month from the files in my workspace.',
    supply:'Compare three suppliers for our main product on price and lead time.',
    sales:'Find ten companies that should be talking to us, with one line on why.',
    tech:'Tell me what changed in the code this week and what looks risky.',
    marketing:"Draft this month's content plan: four posts and one email.",
    support:'What are customers asking most, and which answers are missing?',
    legal:'List the contracts in my workspace and what each commits us to.',
    product:'Turn the feedback we have into the three things to build next.'}[String(name||'').toLowerCase()];
  return t||'What should this department do?';
}
async function companyTask(dept,input,btn,said){
  const task=(input.value||'').trim();if(task.length<3){toast('say what the task is');input.focus();return}
  btn.disabled=true;said.textContent='handing it over…';
  try{
    const j=await apiJSON('/api/company/task',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({department:dept,task})});
    if(j.error)throw new Error(j.error);
    COMPANY.task='';input.value='';said.textContent=`${dept} is on it.`;
    officeLog(`${dept} got a task: ${task.slice(0,90)}`);
    COMPANY.filter='all';companySoon();
  }catch(e){said.textContent=e.message||String(e)}
  finally{btn.disabled=false}
}
/* A task waiting for you, asked before this page was open: the card never reached it.
   Fetch what is waiting, hand it to the approval cards every surface uses (09-websocket),
   and show the first. approval_resolved closes it wherever it was answered. */
async function companyReview(ids){
  try{
    const j=await apiJSON('/api/fabric/approvals');
    const hit=(j.approvals||[]).filter(a=>ids.includes(a.id));
    if(!hit.length){toast('that was answered already');companySoon();return}
    hit.forEach(a=>{APPROVALS[a.id]=a});
    if(typeof approvalWatch==='function')approvalWatch();
    approvalReveal(hit[0].id);
  }catch(e){toast(e.message||String(e))}
}
