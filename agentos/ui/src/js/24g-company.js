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
   - So is the review chain (company.review_state): each boss's answer is read back from
     its review run. Who reports to whom is the office's, saved through
     /api/company/reports so a loop is refused by the server, not guessed at here.
   - The objective's work (company.py preview_work/apply_work) is shown in full before it
     is made, with the same counts the save re-derives; every mission lands switched off.
   - A person may keep several companies. The switcher at the top opens another one: the
     server parks the open company whole and brings that one's office, objective and space
     back (company.switch), so nothing here keeps a second copy of any company.
   Faces: GUI and SUI are this page. TUI is `bento company` (show, setup, task, audit,
   review, chain, check, objective, todo, start, companies, new, open, drop). */
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
  // the 3D office puts the same numbers on its own room cards (of3Cards)
  if(O.L.radial){host.innerHTML='';of3Cards(true);return}
  host.style.width=O.cw+'px';host.style.height=O.ch+'px';
  const by={};d.departments.forEach(s=>by[s.name.toLowerCase()]=s);
  host.innerHTML=O.L.rooms.filter(r=>r.kind==='dept'&&by[r.name.toLowerCase()]).map(r=>{
    const s=by[r.name.toLowerCase()];
    const next=s.next_at?companyWhen(s.next_at):'';
    const tip=`${s.name}: ${s.doing} doing, ${s.waiting} waiting for you, ${s.done} done this week`
      +(s.failed?`, ${s.failed} failed`:'')+(s.flagged?`, ${s.flagged} flagged by the auditor`:'')
      +(s.held?`, ${s.held} held at sign-off`:'')+(s.reports_to?`. Reports to ${s.reports_to}`:'')
      +(next?`, next run ${next}`:'')+'. Tap to give it a task.';
    const x=Math.round((r.x+r.w)*O.s)-8,y=Math.round((r.y+8)*O.s);
    return `<button class="co-card${s.waiting?' wait':''}${s.doing?' busy':''}" style="right:${Math.max(4,O.cw-x)}px;top:${y}px"
      data-dept="${esc(s.name)}" title="${esc(tip)}" aria-label="${esc(tip)}">
      <span class="co-n">${s.people}<small> ${s.people===1?'agent':'agents'}</small></span>
      <span class="co-k" data-s="▶"><i>doing</i>${s.doing}</span><span class="co-k" data-s="⏱"><i>next</i>${s.next}</span>
      <span class="co-k" data-s="✓"><i>done</i>${s.done}</span>${s.waiting?`<span class="co-w">⚠ ${s.waiting}</span>`:''}${
      s.held?`<span class="co-w">↩ ${s.held}</span>`:''}${s.flagged?`<span class="co-fl">⚑ ${s.flagged}</span>`:''}</button>`;
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
  if(COMPANY.newco)return companyNewPaint(el);
  if(COMPANY.kit)return companyKitPaint(el);
  if(COMPANY.plan)return companyPreviewPaint(el);
  if(COMPANY.work)return companyWorkPaint(el);
  if(!d.departments.length||COMPANY.adding)return companySetupPaint(el);
  companyOverviewPaint(el);
}

/* ---------------- several companies (company.create / switch) ---------------- */
function companyCos(){
  const d=COMPANY.data,cs=(d&&d.companies)||[];
  if(!cs.length)return '';
  const full=cs.length>=(d.max_companies||8);
  return `<div class="co-cos"><label class="co-cosl"><span class="mut">Company</span>
    <select class="co-switch" aria-label="Open another company">${cs.map(c=>`<option value="${esc(c.id)}"${c.active?' selected':''}>${esc(c.name)}${
      c.active?'':` · ${c.departments} ${c.departments===1?'department':'departments'}`}</option>`).join('')}</select></label>
    <button class="endbtn co-newco"${full?' disabled title="You keep as many companies as you can here. Remove one with bento company drop."':''}>＋ New company</button></div>`;
}
function companyCosWire(el){
  const sw=el.querySelector('.co-switch'),nc=el.querySelector('.co-newco');
  if(sw)sw.onchange=()=>companySwitch(sw.value,sw);
  if(nc)nc.onclick=()=>{COMPANY.newco=true;COMPANY.arrival=null;companyPaint()};
}
function companyReset(){
  Object.assign(COMPANY,{plan:null,preview:null,work:null,arrival:null,adding:false,focus:'',
    picked:new Set(),desc:'',goal:'',task:'',off:{},filter:'all'});
}
async function companySwitch(id,sel){
  const cs=(COMPANY.data&&COMPANY.data.companies)||[],to=cs.find(c=>c.id===id);
  if(!to||to.active)return;
  if(sel)sel.disabled=true;
  try{
    const j=await apiJSON('/api/companies/active',{method:'PUT',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id})});
    if(j.error)throw new Error(j.error);
    companyReset();
    officeLog(`opened ${j.company.name}`);toast(`✓ ${j.company.name} is open`);
    await officeLoad();await companyLoad();
  }catch(e){toast('could not open it: '+(e.message||e));if(sel){sel.disabled=false;companyPaint()}}
}
/* A new company: a name, a line, and what it is for. It opens empty, in its own office
   and space, and the setup sheet follows with the line and the objective filled in. */
function companyNewPaint(el){
  const N=COMPANY.nc||(COMPANY.nc={name:'',about:'',goal:''});
  el.innerHTML=`<div class="of-dh"><b>A new company</b><button class="of-x" aria-label="Close">✕</button></div>
    <p class="co-lead">It gets its own office, its own people and its own space. The company you have now stays as it is, and you can open it again from the top of this panel.</p>
    <div class="of-row"><input class="co-ncn" maxlength="48" placeholder="Name, e.g. Forgeline" value="${esc(N.name)}" aria-label="Company name"></div>
    <div class="of-row"><input class="co-nca" maxlength="200" placeholder="What it does, e.g. a metal parts manufacturer" value="${esc(N.about)}" aria-label="What it does"></div>
    <div class="of-sec">Objective <span class="mut">optional</span></div>
    <textarea class="co-ncg" rows="2" maxlength="400" placeholder="What should it achieve? For example: cut defects in half by June" aria-label="Objective">${esc(N.goal)}</textarea>
    <div class="of-row co-go"><button class="endbtn primary co-ncgo">Start it</button><button class="endbtn co-back">Back</button></div>
    <div class="of-said mut" aria-live="polite"></div>`;
  const q=s=>el.querySelector(s);
  q('.of-x').onclick=()=>{COMPANY.newco=false;officeCompany(false)};
  q('.co-ncn').oninput=e=>N.name=e.target.value;q('.co-nca').oninput=e=>N.about=e.target.value;
  q('.co-ncg').oninput=e=>N.goal=e.target.value;
  q('.co-back').onclick=()=>{COMPANY.newco=false;companyPaint()};
  q('.co-ncgo').onclick=async()=>{
    const b=q('.co-ncgo'),said=q('.of-said');
    if(!N.name.trim()){toast('give the company a name');q('.co-ncn').focus();return}
    b.disabled=true;said.textContent='starting it…';
    try{
      const j=await apiJSON('/api/companies',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:N.name,about:N.about,objective:N.goal})});
      if(j.error)throw new Error(j.error);
      companyReset();COMPANY.newco=false;COMPANY.desc=N.about?`${N.name}, ${N.about}`:N.name;COMPANY.goal=N.goal;COMPANY.nc=null;
      officeLog(`started ${j.company.name}`);toast(`✓ ${j.company.name} is open. Now give it its departments.`);
      await officeLoad();await companyLoad();
    }catch(e){said.textContent='could not start it: '+(e.message||e);b.disabled=false}
  };
}

/* Set it up: a sentence, and the departments as chips. None ticked lets the brain choose. */
function companySetupPaint(el){
  const d=COMPANY.data,picked=COMPANY.picked||(COMPANY.picked=new Set());
  el.innerHTML=`<div class="of-dh"><b>${COMPANY.adding?'Add departments':'Set up your company'}</b><button class="of-x" aria-label="Close">✕</button></div>
    ${COMPANY.adding?'':companyCos()}
    <p class="co-lead">Say what the business does. I'll draft the departments, a head and staff for each, and show you everything before anything is made.</p>
    <textarea class="co-desc" rows="3" maxlength="1200" placeholder="A coffee subscription startup, twelve people, selling online and shipping across India" aria-label="What the business does">${esc(COMPANY.desc||'')}</textarea>
    ${COMPANY.adding?'':`<div class="of-sec">Objective <span class="mut">optional</span>${typeof pInfo==='function'?pInfo('What the company is trying to achieve. With one, the draft also has the missions, schedules and tasks it needs, each given to a department. You see all of it before anything is made.'):''}</div>
    <textarea class="co-goal" rows="2" maxlength="400" placeholder="What should it achieve? For example: win ten new clients this quarter" aria-label="Objective">${esc(COMPANY.goal!==undefined&&COMPANY.goal!==''?COMPANY.goal:(d.company&&d.company.objective)||'')}</textarea>`}
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
  if(q('.co-goal'))q('.co-goal').oninput=e=>COMPANY.goal=e.target.value;
  companyCosWire(el);
  el.querySelectorAll('.co-chips .of-chip').forEach(b=>b.onclick=()=>{
    const id=b.dataset.id;picked.has(id)?picked.delete(id):picked.add(id);companyPaint()});
  q('.co-draft').onclick=()=>companyDraft(q('.co-draft'),q('.of-said'));
  if(q('.co-back'))q('.co-back').onclick=()=>{COMPANY.adding=false;companyPaint()};
}
async function companyDraft(btn,said){
  const desc=(COMPANY.desc||'').trim(),ids=[...(COMPANY.picked||[])];
  const gEl=companyWindow()&&companyWindow().el.querySelector('.co-goal'),goal=gEl?gEl.value.trim():'';
  if(desc.length<3&&!ids.length){toast('say what the company does, or tick some departments');return}
  btn.disabled=true;said.textContent='drafting your company… this can take a minute';
  try{
    const r=await fetch('/api/company/draft',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({description:desc,departments:ids,talk:COMPANY.talk,objective:goal})});
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
  const pv={};((COMPANY.preview||{}).departments||[]).forEach(x=>pv[x.name]=x);
  const departments=p.departments.filter(d=>!COMPANY.off['d:'+d.name]).map(d=>{
    const o=(pv[d.name]||{}).kit_offer,out={...d,people:d.people.filter(x=>!COMPANY.off['p:'+x.name])};
    // the kit as ticked: what the server offered for these answers, minus each untick
    // (not while an answer changed it: the offer on screen is for the old answers)
    if(o&&!(COMPANY.kitStale||{})[d.name])out.kit=companyKitTicked(d.name,o);
    return out}).filter(d=>d.people.length);
  const out={company:p.company,departments};
  if(p.work)out.work=companyWorkNow(p.work,new Set(departments.map(d=>d.name)));
  return out;
}
/* The work as ticked: an unticked mission or task, or one whose department is unticked,
   is not sent, so the server's recount is what the save makes. */
function companyWorkNow(W,keep){
  return {missions:(W.missions||[]).filter(m=>(!keep||keep.has(m.department))&&!COMPANY.off['m:'+m.name]),
    tasks:(W.tasks||[]).filter((t,i)=>(!keep||keep.has(t.department))&&!COMPANY.off['t:'+i])};
}
/* Missions (some on a schedule) and tasks, each with a tick. Shared by the company's
   first setup and by "Plan the work" for a company that has its departments. */
function companyWorkHTML(W,WV,goal,deptOff){
  const pm={};((WV||{}).missions||[]).forEach(m=>pm[m.name]=m);
  const ms=W.missions||[],ts=W.tasks||[];
  return `<div class="of-sec">For the objective</div>
    <div class="of-row"><input class="co-goalin" maxlength="400" placeholder="What should the company achieve?" value="${esc(goal||'')}" aria-label="Objective"></div>
    ${ms.length?`<div class="co-wsub">Missions <span class="mut">${ms.filter(m=>m.every).length} on a schedule</span></div>`
      +ms.map(m=>{const dOff=!!(deptOff&&deptOff(m.department)),off=dOff||!!COMPANY.off['m:'+m.name],q=pm[m.name]||{};
      return `<label class="co-wrow${off?' off':''}"><input type="checkbox" data-m="${esc(m.name)}"${off?'':' checked'}${dOff?' disabled':''}>
        <span class="co-wt"><b>${esc(m.title)}</b><span class="co-wm mut">${esc(m.department)} · ${esc(q.when||(m.every?m.every:'started by hand'))}${
          q.status==='exists'?' · already here, kept as it is':''}</span>
        <span class="co-wd mut">${esc(m.what)}</span></span></label>`}).join(''):''}
    ${ts.length?`<div class="co-wsub">Tasks to start</div>`+ts.map((t,i)=>{const dOff=!!(deptOff&&deptOff(t.department)),off=dOff||!!COMPANY.off['t:'+i];
      return `<label class="co-wrow${off?' off':''}"><input type="checkbox" data-t="${i}"${off?'':' checked'}${dOff?' disabled':''}>
        <span class="co-wt"><span>${esc(t.text)}</span><span class="co-wm mut">${esc(t.department)}</span></span></label>`}).join(''):''}
    ${!ms.length&&!ts.length?'<p class="mut co-small">Nothing drafted for it. Try saying more about the objective.</p>':''}
    <p class="mut co-small">Missions start switched off, so a schedule runs only once you switch its mission on in Missions. Tasks wait on the task board until you start them.</p>`;
}
function companyWorkWire(el,onGoal,again){
  el.querySelectorAll('[data-m]').forEach(c=>c.onchange=()=>{COMPANY.off['m:'+c.dataset.m]=!c.checked;again()});
  el.querySelectorAll('[data-t]').forEach(c=>c.onchange=()=>{COMPANY.off['t:'+c.dataset.t]=!c.checked;again()});
  const g=el.querySelector('.co-goalin');if(g)g.oninput=e=>onGoal(e.target.value);
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
        </details></div>`}).join('')}
      ${doff?'':companyKitBlock(d,(V.departments||[]).find(x=>x.name===d.name))}</div>`}).join('')}
    ${P.work?companyWorkHTML(P.work,V.work,P.company.objective,n=>!!COMPANY.off['d:'+n]):''}
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
  companyKitWire(el,(dn,qid,v)=>{const d=P.departments.find(x=>x.name===dn);if(!d)return;
    d.answers={...(d.answers||{}),[qid]:v};delete d.kit;
    COMPANY.kitStale={...(COMPANY.kitStale||{}),[dn]:true};companyRepreview()},companyRepreview);
  companyWorkWire(el,v=>{P.company.objective=v},companyRepreview);
  q('.co-again').onclick=()=>{COMPANY.plan=null;COMPANY.preview=null;companyPaint()};
  q('.co-apply').onclick=()=>companyApply(q('.co-apply'),q('.of-said'));
}
/* ---------------- the kit a department starts with (company.recommend) ----------------
   Questions first, then the tools, skills and MCP servers teams like it commonly use,
   each with a tick. Skills show their full text. Servers are never installed here: the
   department's card says "Set it up" until one is. One block for a new department in
   the preview and for one that exists (the Kit sheet). */
function companyN(n,w){return n+' '+w+(n===1?'':'s')}
function companyKitTicked(dn,o){
  const off=k=>!!COMPANY.off['k:'+dn+':'+k];
  return {tools:(o.tools||[]).filter(t=>!off('t:'+t)),skills:(o.skills||[]).filter(s=>!off('s:'+s.id)).map(s=>s.id),
    mcp:(o.mcp||[]).filter(m=>!off('m:'+m.id)).map(m=>m.id)};
}
function companyKitBlock(d,v,everyone){
  const o=v&&v.kit_offer;if(!o)return '';
  const dn=d.name,on=k=>!COMPANY.off['k:'+dn+':'+k];
  const ans=o.answers||{};
  return `<details class="co-kit"${COMPANY.kitOpen&&COMPANY.kitOpen[dn]?' open':''} data-kitd="${esc(dn)}"><summary>Kit: ${companyN(o.tools.length,'tool')}, ${companyN(o.skills.length,'skill')}, ${companyN(o.mcp.length,'server')}
      <span class="mut">what teams like this commonly use</span></summary>
    ${(o.questions||[]).map(q=>`<label class="co-kq"><span>${esc(q.ask)}</span><select data-kq="${esc(q.id)}" data-kd="${esc(dn)}">
      ${q.options.map(([k,l])=>`<option value="${esc(k)}"${ans[q.id]===k?' selected':''}>${esc(l)}</option>`).join('')}</select></label>`).join('')}
    ${o.tools.length?`<div class="co-kh">Tools <span class="mut">${everyone?'for everyone here':'for the new people here'}</span></div><div class="co-kt">${o.tools.map(t=>
      `<label class="co-kc"><input type="checkbox" data-kk="${esc(dn)}|t:${esc(t)}"${on('t:'+t)?' checked':''}><code>${esc(t)}</code></label>`).join('')}</div>`:''}
    ${o.skills.length?`<div class="co-kh">Skills</div>${o.skills.map(s=>`<div class="co-ks"><label class="co-kc"><input type="checkbox" data-kk="${esc(dn)}|s:${esc(s.id)}"${on('s:'+s.id)?' checked':''}>
      <b>${esc(s.name)}</b><span class="mut">${esc(s.description)}${s.exists?' · you have this one, it is used as it is':''}</span></label>
      <details class="co-more"><summary>What it says</summary><p class="co-small">${esc(s.content)}</p></details></div>`).join('')}`:''}
    ${o.mcp.length?`<div class="co-kh">MCP servers <span class="mut">set up later with your own key</span></div><div class="co-kt">${o.mcp.map(m=>
      `<label class="co-kc"><input type="checkbox" data-kk="${esc(dn)}|m:${esc(m.id)}"${on('m:'+m.id)?' checked':''}><b>${esc(m.name)}</b><span class="mut">${esc(m.why)}</span></label>`).join('')}</div>`:''}
  </details>`;
}
function companyKitWire(el,onAnswer,again){
  el.querySelectorAll('[data-kq]').forEach(s=>s.onchange=()=>{COMPANY.kitOpen={...(COMPANY.kitOpen||{}),[s.dataset.kd]:true};onAnswer(s.dataset.kd,s.dataset.kq,s.value)});
  el.querySelectorAll('[data-kk]').forEach(c=>c.onchange=()=>{const [dn,k]=c.dataset.kk.split('|');
    COMPANY.kitOpen={...(COMPANY.kitOpen||{}),[dn]:true};COMPANY.off['k:'+dn+':'+k]=!c.checked;again()});
  el.querySelectorAll('details.co-kit').forEach(dt=>dt.ontoggle=()=>{COMPANY.kitOpen={...(COMPANY.kitOpen||{}),[dt.dataset.kitd]:dt.open}});
}
/* On a department's card: the servers its kit wants, and the way to set each one up. */
function companyKitHTML(x){
  const k=x.kit||{},ms=k.mcp||[];
  return `<div class="co-desk mut co-kitline">${ms.length?`Servers: ${ms.map(m=>m.added?`<span class="co-kok">✓ ${esc(m.name)}</span>`
      :`<button class="co-link" data-mcp="${esc(m.preset||'')}" data-mcpc="${esc(m.curated||'')}" data-mcpq="${esc(m.search||m.name)}" title="${esc(m.why)}">Set up ${esc(m.name)}</button>`).join(' ')}`
      :(k.skills||[]).length||(k.tools||[]).length?'Kit given.':'No kit yet.'}
    <button class="co-link" data-kit="${esc(x.name)}">${(k.skills||[]).length||(k.tools||[]).length||ms.length?'Change the kit':'Choose a kit'}</button></div>`;
}
function companyKitSetUp(preset,q,curated){
  if(preset){openApp('mcp');setTimeout(()=>{if(typeof mcpPreset==='function')mcpPreset(preset)},400);return}
  if(curated){openApp('mcp');setTimeout(()=>{if(typeof mcpConnectCurated==='function')mcpConnectCurated(curated)},400);return}
  if(typeof STORE_TAB!=='undefined')STORE_TAB='discover';
  openApp('store');refreshApp('store');
  setTimeout(()=>{const i=document.getElementById('disc-q');if(i){i.value=q;i.focus()}
    if(typeof storeDiscover==='function')storeDiscover(q)},500);
}
/* The Kit sheet, for a department that exists. */
async function companyKitOpen(name){
  COMPANY.kit={dept:name,answers:{},offer:null,err:''};COMPANY.kitOpen={[name]:true};
  Object.keys(COMPANY.off).forEach(k=>{if(k.startsWith('k:'+name+':'))delete COMPANY.off[k]});
  companyPaint();companyKitOffer();
}
async function companyKitOffer(){
  const K=COMPANY.kit;if(!K)return;
  try{const j=await apiJSON('/api/company/kit/offer',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({department:K.dept,answers:K.answers})});
    if(j.error)throw new Error(j.error);K.offer=j.offer;K.current=j.current}
  catch(e){K.err=e.message||String(e)}
  companyPaint();
}
function companyKitPaint(el){
  const K=COMPANY.kit,o=K.offer,dn=K.dept;
  const kt=o?companyKitTicked(dn,o):null;
  el.innerHTML=`<div class="of-dh"><b>${esc(dn)}: its kit</b><button class="of-x" aria-label="Close">✕</button></div>
    <p class="co-lead">A few questions, then what teams like ${esc(dn)} commonly use. Untick what you do not want.</p>
    ${!o?`<div class="mut">${esc(K.err||'loading…')}</div>`:companyKitBlock({name:dn},{kit_offer:o},true)}
    ${o?`<p class="mut co-small">Ticked tools and skills go to everyone in ${esc(dn)}. Servers are never installed here: each needs your own account, and its card says Set it up.</p>
    <div class="of-row co-go"><button class="endbtn primary co-kitgo">Give ${esc(dn)} ${companyN(kt.tools.length,'tool')} and ${companyN(kt.skills.length,'skill')}</button>
      <button class="endbtn co-kitno">Not now</button></div><div class="of-said mut" aria-live="polite"></div>`:''}`;
  const q=s=>el.querySelector(s);
  const close=()=>{COMPANY.kit=null;companyPaint()};
  q('.of-x').onclick=close;
  if(!o)return;
  const det=el.querySelector('details.co-kit');if(det)det.open=true;
  companyKitWire(el,(d,qid,v)=>{K.answers={...K.answers,[qid]:v};companyKitOffer()},()=>companyPaint());
  q('.co-kitno').onclick=close;
  q('.co-kitgo').onclick=async()=>{const b=q('.co-kitgo'),said=q('.of-said');b.disabled=true;said.textContent='setting it up…';
    try{const j=await apiJSON('/api/company/kit',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({department:dn,kit:companyKitTicked(dn,o)})});
      if(j.error)throw new Error(j.error);
      toast(`✓ ${dn}: ${j.skills_made.length} new skills, ${j.agents.length} agents given the kit`);
      COMPANY.kit=null;await companyLoad();
    }catch(e){said.textContent='could not: '+(e.message||e);b.disabled=false}};
}
function companyButton(V){
  const n=V.new||0,d=V.desks||0,w=V.work||{},m=w.new_missions||0,t=(w.tasks||[]).length;
  if(!d)return 'Nothing to make';
  const work=m||t?` with ${[m?`${m} ${m===1?'mission':'missions'}`:'',t?`${t} ${t===1?'task':'tasks'}`:''].filter(Boolean).join(' and ')}`:'';
  const k=V.kit||{},kit=k.skills?` and ${k.skills} ${k.skills===1?'skill':'skills'}`:'';
  return (n?`Make ${n} ${n===1?'agent':'agents'}${kit} in ${d} ${d===1?'department':'departments'}`
    :`Set up ${d} ${d===1?'department':'departments'}${kit}`)+work;
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
      COMPANY.preview=j.preview;COMPANY.kitStale={};
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
    COMPANY.arrival=j;COMPANY.plan=null;COMPANY.preview=null;COMPANY.adding=false;COMPANY.picked=new Set();COMPANY.desc='';COMPANY.goal='';
    officeLog(`company set up: ${j.departments.join(', ')}`);
    toast(`✓ ${j.departments.length} departments, ${j.made.length} new agents`);
    if(typeof avatarsLoad==='function')await avatarsLoad();
    await officeLoad();await companyLoad();
    const el=companyWindow()&&companyWindow().el.querySelector('.of-company');if(el)el.scrollTop=0;
  }catch(e){said.textContent='could not set it up: '+(e.message||e);btn.disabled=false}
}

/* "Plan the work": the objective, then what it calls for (company.preview_work), each
   piece with a tick, then one button that makes exactly what is ticked. */
function companyWorkPaint(el){
  const W=COMPANY.work,d=COMPANY.data,dr=W.draft;
  const who=(typeof EXEC_TITLES!=='undefined'&&EXEC_TITLES[(dr||{}).who])||(dr||{}).who||'your AI';
  el.innerHTML=`<div class="of-dh"><b>${esc(d.company.name||'Your company')}: the work</b><button class="of-x" aria-label="Close">✕</button></div>
    ${!dr?`<p class="co-lead">Say what the company is trying to achieve. I'll draft the missions, schedules and tasks it needs, each for one of your ${d.departments.length} departments, and show you all of it first.</p>
    <textarea class="co-wgoal" rows="3" maxlength="400" placeholder="For example: win ten new clients this quarter" aria-label="Objective">${esc(W.goal||'')}</textarea>
    <div class="of-row co-go"><button class="endbtn primary co-wdraft">Draft the work</button><button class="endbtn co-back">Back</button></div>`
    :`<p class="co-lead">${dr.how==='brain'?`Drafted by ${esc(who)}.`:esc(dr.said||'Filled in from the catalogue.')} Nothing is made until you press the button at the bottom.</p>
    ${companyWorkHTML(dr.work,dr.preview,W.goal)}
    ${(dr.preview.notes||[]).map(n=>`<p class="mut co-small">${esc(n)}</p>`).join('')}
    ${(dr.dropped||[]).length?`<p class="mut co-small">Left out of the draft: ${esc(dr.dropped.join('; '))}</p>`:''}
    <div class="of-row co-go"><button class="endbtn primary co-wapply">${companyWorkButton(dr.preview)}</button>
      <button class="endbtn co-wagain">Start over</button></div>`}
    <div class="of-said mut" aria-live="polite"></div>`;
  const q=s=>el.querySelector(s);
  q('.of-x').onclick=()=>{COMPANY.work=null;officeCompany(false)};
  if(!dr){
    q('.co-wgoal').oninput=e=>W.goal=e.target.value;
    q('.co-back').onclick=()=>{COMPANY.work=null;companyPaint()};
    q('.co-wdraft').onclick=()=>companyWorkDraft(q('.co-wdraft'),q('.of-said'));
    return;
  }
  companyWorkWire(el,v=>{W.goal=v},companyWorkRepreview);
  q('.co-wagain').onclick=()=>{W.draft=null;COMPANY.off={};companyPaint()};
  q('.co-wapply').onclick=()=>companyWorkApply(q('.co-wapply'),q('.of-said'));
}
function companyWorkButton(V){
  const m=(V&&V.new_missions)||0,t=((V&&V.tasks)||[]).length;
  if(!m&&!t)return 'Nothing to make';
  return 'Make '+[m?`${m} ${m===1?'mission':'missions'}`:'',t?`${t} ${t===1?'task':'tasks'}`:''].filter(Boolean).join(' and ');
}
async function companyWorkDraft(btn,said){
  const goal=(COMPANY.work.goal||'').trim();
  if(goal.length<3){toast('say what the company is trying to achieve');return}
  btn.disabled=true;said.textContent='drafting the work… this can take a minute';
  try{
    const j=await apiJSON('/api/company/work/draft',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({objective:goal})});
    if(j.error)throw new Error(j.error);
    if(!COMPANY.work)return;
    COMPANY.off={};COMPANY.work.draft=j;companyPaint();
  }catch(e){said.textContent='could not draft it: '+(e.message||e);if(btn.isConnected)btn.disabled=false}
}
function companyWorkRepreview(){
  clearTimeout(COMPANY.pv);
  COMPANY.pv=setTimeout(async()=>{
    const W=COMPANY.work;if(!W||!W.draft)return;
    try{
      const j=await apiJSON('/api/company/work/preview',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({work:companyWorkNow(W.draft.work),objective:W.goal})});
      // the recount is for the ticked work; the sheet keeps every row so a tick can come back
      const keep=W.draft.preview,pm={};(j.preview.missions||[]).forEach(m=>pm[m.name]=m);
      W.draft.preview={...j.preview,missions:(W.draft.work.missions||[]).map(m=>pm[m.name]||(keep.missions||[]).find(x=>x.name===m.name)||m)};
      W.draft.count=j.preview;
    }catch(e){}
    const el=companyWindow()&&companyWindow().el.querySelector('.of-company');
    if(el&&COMPANY.work){const top=el.scrollTop;companyWorkPaint(el);el.scrollTop=top;
      const b=el.querySelector('.co-wapply');if(b&&W.draft.count)b.textContent=companyWorkButton(W.draft.count)}
  },250);
}
async function companyWorkApply(btn,said){
  const W=COMPANY.work,work=companyWorkNow(W.draft.work);
  if(!work.missions.length&&!work.tasks.length){toast('tick at least one mission or task');return}
  btn.disabled=true;said.textContent='making it…';
  try{
    const j=await apiJSON('/api/company/work/apply',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({work,objective:W.goal})});
    if(j.error)throw new Error(j.error);
    COMPANY.work=null;COMPANY.off={};COMPANY.filter=j.tasks?'todo':'all';
    officeLog(`work for the objective: ${j.missions.length} missions, ${j.tasks} tasks`);
    toast(`✓ ${j.missions.length} ${j.missions.length===1?'mission':'missions'} (off until you switch them on), ${j.tasks} ${j.tasks===1?'task':'tasks'} to start`);
    await companyLoad();
    const el=companyWindow()&&companyWindow().el.querySelector('.of-company');if(el)el.scrollTop=0;
  }catch(e){said.textContent='could not make it: '+(e.message||e);btn.disabled=false}
}
/* Start one of the objective's tasks: a run of its department's desk, like any task. */
async function companyTodo(id,drop,el){
  if(el)el.style.pointerEvents='none';
  try{
    const j=drop?await apiJSON(`/api/company/todo/${encodeURIComponent(id)}`,{method:'DELETE'})
      :await apiJSON(`/api/company/todo/${encodeURIComponent(id)}/start`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    if(j.error)throw new Error(j.error);
    if(!drop){officeLog(`${j.department} started a task`);toast(`${j.department} is on it`)}
    if(COMPANY.filter==='todo'&&!drop)COMPANY.filter='all';
    companySoon();await companyLoad();
  }catch(e){toast(e.message||String(e));if(el)el.style.pointerEvents=''}
}

/* The company at work: give a department a task, each department's line, and the board. */
function companyOverviewPaint(el){
  const d=COMPANY.data,A=COMPANY.arrival,colors=(OFFICE.view&&OFFICE.view.colors)||{};
  const focus=COMPANY.focus&&d.departments.find(x=>x.name===COMPANY.focus)?COMPANY.focus:(d.departments[0]||{}).name;
  const b=d.board||{tasks:[],counts:{}},f=COMPANY.filter;
  const tasks=b.tasks.filter(t=>f==='all'||t.status===f||(f==='in_progress'&&t.status==='stale')||(f==='failed'&&t.status==='stopped')
    ||(f==='flagged'&&companyFlagged(t))||(f==='held'&&companyHeld(t)));
  const chip=(k,l)=>`<button class="of-chip${f===k?' on':''}" data-f="${k}" aria-pressed="${f===k}">${l}${k!=='all'&&b.counts[k]?' '+b.counts[k]:''}</button>`;
  const pill={in_progress:'working',waiting:'waiting for you',done:'done',failed:'failed',scheduled:'scheduled',
    stale:'stopped answering',stopped:'stopped',todo:'to do'};
  el.innerHTML=`<div class="of-dh"><b>${esc(d.company.name||'Your company')}</b><button class="of-x" aria-label="Close">✕</button></div>
    ${companyCos()}
    ${d.company.about?`<p class="co-lead">${esc(d.company.about)}</p>`:''}
    <div class="co-obj">${d.company.objective?`<span class="co-objt"><span class="mut">Objective</span> ${esc(d.company.objective)}</span>`
      :'<span class="co-objt mut">No objective yet. Say what the company is for, and I will draft its missions, schedules and tasks.</span>'}
      <button class="endbtn co-plan">${d.company.objective?'Plan the work':'Set an objective'}</button></div>
    ${A?`<div class="co-arrival"><b>✓ ${A.departments.length} departments set up.</b>
      ${A.made.length?` ${A.made.length} new agents.`:''}${A.joined.length?` ${esc(A.joined.join(', '))} joined as they were.`:''}
      Each desk starts off.${A.work&&(A.work.missions.length||A.work.tasks)?` For the objective: ${A.work.missions.length} ${A.work.missions.length===1?'mission':'missions'}, off until you switch them on, and ${A.work.tasks} ${A.work.tasks===1?'task':'tasks'} to start below.`:''} ${A.try?esc(A.try):''}
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
      <label class="co-rep mut">Reports to <select data-rep="${esc(x.name)}" aria-label="${esc(x.name)} reports to">
        <option value="">${esc(b.lead||'your agent')}</option>${d.departments.filter(y=>y.name!==x.name).map(y=>
          `<option value="${esc(y.name)}"${x.reports_to===y.name?' selected':''}>${esc(y.name)}</option>`).join('')}</select>
        ${x.signed||x.held?`<span>${x.signed} signed off${x.held?`, <b class="co-w">${x.held} held</b>`:''} this week</span>`:''}</label>
      <label class="co-rep mut">Executor <select data-hands="${esc(x.name)}" aria-label="${esc(x.name)}'s executor">
        <option value="">Each agent's own</option>${(d.executors||[]).map(p=>
          `<option value="${esc(p.name)}"${x.hands===p.name?' selected':''}>${esc(p.name)}</option>`).join('')}</select>
        ${typeof pInfo==='function'?pInfo('What the department’s people can reach: tools, folders, web and MCP servers. An agent with an executor of its own keeps it.'):''}</label>
      ${companyKitHTML(x)}
      <div class="co-desk mut">${!x.has_desk?'No desk: tasks go to its head in chat.'
        :x.desk_on?'Desk on.':'Desk off, so gated steps ask you.'}
        ${x.has_desk?`<button class="co-link" data-desk="${esc(x.desk)}">${x.desk_on?'Open in Missions':'Switch on in Missions'}</button>`:''}</div>
      ${(x.missions||[]).length?`<div class="co-desk mut">Missions: ${x.missions.map(m=>`<button class="co-link" data-desk="${esc(m.flow)}">${esc(m.title)}${m.on?'':' (off)'}</button>`).join(' ')}</div>`:''}
    </div>`).join('')}
    <div class="of-row"><button class="endbtn co-add">＋ Add departments</button></div>
    <label class="co-audit co-signoff"><span>Who may ask whom</span><select class="co-perm" aria-label="Who may ask whom is decided per">
      ${[['agent','Per agent'],['department','Per department']].map(([k,l])=>`<option value="${k}"${(d.permissions||'agent')===k?' selected':''}>${l}</option>`).join('')}</select>
      <button class="co-link co-grid">${(d.permissions||'agent')==='department'?'Department grid':'Agent grid'}</button>${typeof pInfo==='function'?pInfo('Per department: people in one department may ask each other, and the grid decides between departments. A block between two agents still holds.'):''}</label>
    <div class="of-sec">Tasks</div>
    <label class="co-audit co-signoff"><span>Sign-off</span><select class="co-rv" aria-label="Who signs finished work off">
      ${[['lead',`Every boss, up to ${b.lead||'your agent'}`],['heads',"The department's own head"],['off','Nobody']].map(([k,l])=>
        `<option value="${k}"${(b.review||'lead')===k?' selected':''}>${esc(l)}</option>`).join('')}</select>${typeof pInfo==='function'?pInfo('A finished task goes to its head, then to the head of each department it reports to, then to your agent. Each one approves it, sends it back to be fixed (twice at most) or passes a decision up. What is held goes to your Brief.'):''}</label>
    <label class="co-audit"><input type="checkbox" class="co-aud"${b.audit!==false?' checked':''}>
      <span>An independent auditor checks every finished task</span>${typeof pInfo==='function'?pInfo('The auditor did none of the work and no department can skip it. Anything it flags goes to your Brief.'):''}</label>
    <div class="of-chips co-filter">${chip('all','All')}${b.counts.todo?chip('todo','To do'):''}${chip('in_progress','Working')}${chip('waiting','Waiting')}${chip('scheduled','Scheduled')}${chip('done','Done')}${chip('held','Held')}${chip('flagged','Flagged')}${chip('failed','Failed')}</div>
    <div class="co-board">${tasks.length?tasks.slice(0,40).map(t=>t.status==='todo'?`<div class="co-task-row co-todo" style="--dc:${colors[t.color]||'#888'}">
      <span class="co-st todo">to do</span><span class="co-tt">${esc(t.task)}</span><span class="co-tm mut">${esc(t.department)}</span>
      <span class="co-tdo"><button class="endbtn primary co-start" data-start="${esc(t.todo)}">Start it</button>
        <button class="endbtn co-drop" data-drop="${esc(t.todo)}" aria-label="Drop this task">Not now</button></span></div>`
      :`<button class="co-task-row" ${t.run_id?`data-run="${esc(t.run_id)}"`:''} style="--dc:${colors[t.color]||'#888'}">
      <span class="co-st ${t.status}">${esc(pill[t.status]||t.status)}</span>
      <span class="co-tt">${esc(t.task)}</span>
      <span class="co-tm mut">${esc(t.department)}${t.who?' · '+esc(t.who):''}${t.handoffs?` · ${t.handoffs} ${t.handoffs===1?'hand-over':'hand-overs'}`:''}
        · ${esc(t.status==='scheduled'?companyWhen(t.next_at):companyAgo(t.finished_at||t.started_at))}</span>
      ${t.said&&t.status!=='in_progress'?`<span class="co-said mut">${esc(t.said)}</span>`:''}
      ${companyReviewHTML(t)}${companyAuditHTML(t)}
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
  q('.co-rv').onchange=e=>companyReviewMode(e.target);
  el.querySelectorAll('[data-rep]').forEach(x=>x.onchange=()=>companyReports(x));
  el.querySelectorAll('[data-hands]').forEach(x=>x.onchange=()=>companyHands(x));
  q('.co-perm').onchange=e=>companyPermMode(e.target);
  q('.co-grid').onclick=()=>{openApp('settings');setTimeout(()=>{document.querySelector('.prefs-side button[data-t="team"]')?.click();
    setTimeout(()=>document.getElementById('s-team-matrix')?.scrollIntoView({block:'start',behavior:'smooth'}),150)},200)};
  el.querySelectorAll('[data-kit]').forEach(b=>b.onclick=()=>companyKitOpen(b.dataset.kit));
  el.querySelectorAll('[data-mcpq]').forEach(b=>b.onclick=()=>companyKitSetUp(b.dataset.mcp,b.dataset.mcpq,b.dataset.mcpc));
  el.querySelectorAll('[data-run]').forEach(b=>b.onclick=e=>{
    const ap=e.target.closest('[data-ap]');if(ap)return companyReview(ap.dataset.ap.split(','));
    const ck=e.target.closest('[data-check]');if(ck)return companyCheck(b.dataset.run,ck);
    if(e.target.closest('[data-brief]'))return openApp('brief');
    if(typeof fgWatch==='function')fgWatch(b.dataset.run)});
  q('.co-add').onclick=()=>{COMPANY.adding=true;COMPANY.arrival=null;companyPaint()};
  q('.co-plan').onclick=()=>{COMPANY.off={};COMPANY.arrival=null;COMPANY.work={goal:d.company.objective||'',draft:null};companyPaint()};
  el.querySelectorAll('[data-start]').forEach(b=>b.onclick=()=>companyTodo(b.dataset.start,false,b));
  el.querySelectorAll('[data-drop]').forEach(b=>b.onclick=()=>companyTodo(b.dataset.drop,true,b));
  companyCosWire(el);
}
/* ---------------- the review chain (company.chain, fabric ControlPlane.review) ---------------- */
function companyHeld(t){const o=(t.review||{}).outcome;return o==='sent_back'||o==='escalated'||o==='unchecked'}
/* The chain under a task: each boss with a mark for what they said, in order, and the
   sentence when it stopped short of the top. Read from the review runs, never decided here. */
function companyReviewHTML(t){
  const r=t.review||{};if(!r.gates||!r.gates.length)return '';
  const lead=((COMPANY.data||{}).board||{}).lead;
  const mark={approve:'✓',send_back:'↩',escalate:'↑',skipped:'–',unchecked:'?'};
  const word={approve:'approved',send_back:'sent it back',escalate:'passed it up',skipped:'could not review',unchecked:'gave no clear answer'};
  const gates=r.gates.map(g=>`<span class="co-gate ${g.answer||'wait'}" title="${esc(g.who+': '+(word[g.answer]||'reviewing')+((g.notes||[])[0]?' · '+g.notes[0]:g.why?' · '+g.why:''))}">${
    avatarImgSafe(g.who===lead?'@agent':g.who)}${esc(g.who)} ${mark[g.answer]||'…'}</span>`).join('<i>→</i>');
  const held=companyHeld(t)||r.outcome==='reworking';
  return `<span class="co-chain${held?' held':''}">${gates}${r.rounds?`<small>${r.rounds} round${r.rounds===1?'':'s'} of fixes</small>`:''}</span>`
    +(held||r.outcome==='unreviewed'?`<span class="co-au none">${esc(r.line||'')}</span>`:'');
}
async function companyReviewMode(sel){
  const v=sel.value;sel.disabled=true;
  try{
    const j=await apiJSON('/api/company',{method:'PUT',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({review:v})});
    if(j.error)throw new Error(j.error);
    toast({lead:'Each boss signs finished work off, up to your agent',heads:"Each department's head signs its work off",off:'Nobody signs finished work off now'}[v]);
    companyLoad();
  }catch(e){toast(e.message||String(e));companyPaint()}
  finally{sel.disabled=false}
}
async function companyReports(sel){
  const dept=sel.dataset.rep;sel.disabled=true;
  try{
    const j=await apiJSON('/api/company/reports',{method:'PUT',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({department:dept,reports_to:sel.value})});
    if(j.error)throw new Error(j.error);
    toast(`${dept} reports to ${j.reports_to}. Sign-off: ${(j.chain||[]).join(' → ')}`);
    companyLoad();
  }catch(e){toast(e.message||String(e),{kind:'err'});companyLoad()}
  finally{sel.disabled=false}
}
/* ---------------- permissions and hands at the department level (company.py) ---------------- */
async function companyHands(sel){
  const dept=sel.dataset.hands;sel.disabled=true;
  try{
    const j=await apiJSON('/api/company/hands',{method:'PUT',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({department:dept,hands:sel.value})});
    if(j.error)throw new Error(j.error);
    toast(j.hands?`${dept} works with the ${j.hands} executor`:`${dept}'s people each use their own executor`);
    companyLoad();
  }catch(e){toast(e.message||String(e),{kind:'err'});companyLoad()}
  finally{sel.disabled=false}
}
async function companyPermMode(sel){
  sel.disabled=true;
  try{
    const j=await apiJSON('/api/company/permissions',{method:'PUT',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({mode:sel.value})});
    if(j.error)throw new Error(j.error);
    toast(j.mode==='department'?'Departments decide who may ask whom. Colleagues may ask each other.':'Each pair of agents decides who may ask whom.');
    companyLoad();
  }catch(e){toast(e.message||String(e),{kind:'err'});companyLoad()}
  finally{sel.disabled=false}
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
    product:'Turn the feedback we have into the three things to build next.',
    production:"Plan next week's production from the open orders in my workspace.",
    quality:'List the defects logged this month and the likely cause of each.',
    delivery:'Write a status note for each active client engagement.'}[String(name||'').toLowerCase()];
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
