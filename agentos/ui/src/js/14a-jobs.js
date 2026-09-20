/* ================= missions: what this machine does for you =================
   Three surfaces over one API (/api/jobs): the last beat of the first-run wizard,
   the onboarding arc's schedule step, and the standing Missions app. They share
   `jobPersonaBar`/`jobCards`/`jobForm` on purpose — the screen that gets somebody
   their first mission and the screen that gets them their fourth should not drift
   apart, because the second one is the habit and the first one is only the
   introduction.

   The first question is WHO IS ASKING. A founder, a coder and a consultant want
   different things from a machine that works while they do not, and a catalogue
   that opens with disk space is a catalogue a founder closes. The persona is a
   filter over ONE catalogue (theirs first, then everybody's, then the rest) —
   never a subset, because a consultant who also writes code must be able to
   reach the coder's missions.

   The app is also the VALUE surface: not "what is scheduled" but what each
   mission did this week, what it last said, and what it holds. Activity is not
   value; the last outcome, in words, is the closest a list can get.

   Everything user-facing here obeys the honesty rule: a delivery this machine
   cannot do is shown greyed with the sentence that would fix it, never hidden,
   and the folder or the addresses a mission will read are printed before it
   exists. Faces — GUI: this. SUI: identical. TUI: `bento job`.

   `var`, not `let` — this file is concatenated into one script and 14-docs-setup
   calls jobStep() from wizFinish. See CLAUDE.md on the TDZ trap. */
var JOBS={recipes:[],personas:[],persona:'',deliveries:[],installed:[],summary:null,ready:null,accounts:{},pick:'',busy:false};

async function jobsLoad(){
  try{const d=await (await fetch('/api/jobs')).json();
    JOBS.recipes=d.recipes||[];JOBS.personas=d.personas||[];JOBS.persona=d.persona||'';
    JOBS.deliveries=d.deliveries||[];JOBS.installed=d.installed||[];JOBS.summary=d.summary||null;JOBS.ready=d.ready||null;JOBS.accounts=d.accounts||{};
  }catch(e){JOBS.recipes=[];}
  return JOBS;
}

/* Can a mission run here at all? A flow runs on the built-in loop with a provider
   model, never through an executor — the only loop whose every step the PDP sees.
   A machine whose brain is Claude Code and has no provider set can chat and
   cannot run a mission, and the honest surface says so HERE, not in a failed row. */
function jobReadyLine(){
  const r=JOBS.ready;if(!r)return '';
  if(r.ok)return `<p class="mut job-ready">${esc(r.note)}</p>`;
  return `<div class="job-notready"><b>Missions cannot run here yet.</b> ${esc(r.note)} <em>${esc(r.fix)}</em>
    <button class="endbtn" onclick="SETTAB='providers';localStorage.setItem('settab','providers');openApp('settings')">Open AI providers</button></div>`;
}

/* Who is asking. One row of chips; the choice is saved per person (`persona` is
   a USER_KEY) and the server re-orders the catalogue. `onPick` redraws the cards. */
function jobPersonaBar(){
  return `<div class="job-who" role="radiogroup" aria-label="Who are you?">
    ${JOBS.personas.map(p=>`<button class="job-p${p.id===JOBS.persona?' on':''}" data-persona="${esc(p.id)}"
        role="radio" aria-checked="${p.id===JOBS.persona}" title="${esc(p.blurb)}">
        <span class="job-p-ic">${esc(p.icon||'○')}</span>${esc(p.label)}</button>`).join('')}
  </div>`;
}
function jobWirePersona(root,onPick){
  root.querySelectorAll('.job-p').forEach(b=>b.onclick=async()=>{
    const id=b.dataset.persona;
    if(JOBS.busy)return;JOBS.busy=true;
    try{
      const d=await (await fetch('/api/jobs/persona',{method:'PUT',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({persona:id===JOBS.persona?'':id})})).json();
      if(d.error){toast(d.error);return}
      JOBS.persona=d.persona||'';JOBS.recipes=d.recipes||JOBS.recipes;JOBS.pick='';
      if(typeof cfg!=='undefined'&&cfg)cfg.persona=JOBS.persona;
      if(typeof homeRender==='function')homeRender();
      root.querySelectorAll('.job-p').forEach(x=>{const on=x.dataset.persona===JOBS.persona;x.classList.toggle('on',on);x.setAttribute('aria-checked',on)});
      onPick&&onPick();
    }catch(e){toast('could not save that')}
    finally{JOBS.busy=false}
  });
}

/* The cards. With a persona chosen they come in two groups — theirs, then the
   rest — so the first three on screen are the ones written for them. `sel` is
   the id currently expanded, '' for none. */
function jobCards(sel){
  const p=JOBS.persona,who=JOBS.personas.find(x=>x.id===p);
  // an account it cannot run without: the card stays, greyed, with the sentence
  // that would fix it and the door — hidden reads as "this OS cannot do that"
  const missing=r=>(r.wants||[]).filter(a=>!((JOBS.accounts||{})[a]||{}).ready);
  const card=r=>{const miss=missing(r);
    return `<button class="job-card${r.id===sel?' on':''}${miss.length?' needs':''}" data-job="${esc(r.id)}" ${miss.length?`data-needs="${esc(miss.join(','))}"`:''}>
      <span class="job-mark">${esc(r.icon||'◇')}</span>
      <b>${esc(r.title)}</b>
      <span class="job-blurb">${esc(r.blurb)}</span>
      ${r.worth?`<span class="job-worth">${esc(r.worth)}</span>`:''}
      ${miss.length?`<span class="job-needs">${esc(miss.map(a=>((JOBS.accounts||{})[a]||{}).detail||('needs a '+a+' account')).join(' '))}</span>`:`<span class="job-eg">${esc(r.example)}</span>`}
    </button>`};
  if(!p||!who||p==='everyone')return `<div class="job-cards">${JOBS.recipes.map(card).join('')}</div>`;
  const mine=JOBS.recipes.filter(r=>(r.for||[]).includes(p)),rest=JOBS.recipes.filter(r=>!(r.for||[]).includes(p));
  return `<div class="job-grp">For a ${esc(who.label.toLowerCase())}</div>
    <div class="job-cards">${mine.map(card).join('')}</div>
    <div class="job-grp">And for anyone</div>
    <div class="job-cards">${rest.map(card).join('')}</div>`;
}

/* the two or three questions a recipe asks, plus the delivery picker */
function jobForm(r){
  const field=n=>{
    if(n.key==='deliver')return jobDeliver(n);
    const id='jf-'+n.key;
    if(n.kind==='folder')return `<label class="job-q"><span>${esc(n.label)}</span>
      <input id="${id}" value="${esc(n.default||'')}" spellcheck="false" autocomplete="off">
      ${n.help?`<em>${esc(n.help)}</em>`:''}</label>`;
    if(n.kind==='time')return `<label class="job-q"><span>${esc(n.label)}</span>
      <input id="${id}" type="time" value="${esc(n.default||'08:00')}"></label>`;
    if(n.kind==='day')return `<label class="job-q"><span>${esc(n.label)}</span>
      <select id="${id}">${WEEKDAY_NAMES.map(d=>`<option value="${d.toLowerCase()}" ${d.toLowerCase()===(n.default||'friday')?'selected':''}>${d}</option>`).join('')}</select></label>`;
    if(n.kind==='minutes')return `<label class="job-q"><span>${esc(n.label)}</span>
      <span class="job-mins"><input id="${id}" type="number" min="5" step="5" value="${esc(n.default||'60')}"> minutes</span>
      ${n.help?`<em>${esc(n.help)}</em>`:''}</label>`;
    if(n.kind==='lines')return `<label class="job-q"><span>${esc(n.label)}</span>
      <textarea id="${id}" rows="3" placeholder="${esc(n.placeholder||'')}" spellcheck="false" autocomplete="off">${esc(n.default||'')}</textarea>
      ${n.help?`<em>${esc(n.help)}</em>`:''}</label>`;
    return `<label class="job-q"><span>${esc(n.label)}</span>
      <input id="${id}" value="${esc(n.default||'')}" placeholder="${esc(n.placeholder||'')}" spellcheck="false" autocomplete="off">
      ${n.help?`<em>${esc(n.help)}</em>`:''}</label>`;
  };
  return `<div class="job-form">${r.needs.map(field).join('')}
    <div class="job-consent" id="jf-consent"></div>
    <div class="job-go"><button class="wiz-next" id="jf-save">Set it up</button></div></div>`;
}

/* Delivery: every option, always — a way out that is not configured is shown
   with the sentence that would fix it rather than left out. Absent reads as
   "this OS cannot do that"; greyed reads as "not yet, and here is how". */
function jobDeliver(n){
  return `<div class="job-q"><span>${esc(n.label)}</span>
    <div class="job-ways">${JOBS.deliveries.map(d=>`
      <label class="job-way${d.ready?'':' off'}">
        <input type="radio" name="jf-deliver" value="${esc(d.id)}" ${d.ready?'':'disabled'}
          ${d.id==='report'?'checked':''}>
        <b>${esc(d.label)}</b><em>${esc(d.detail)}</em>
      </label>`).join('')}</div></div>`;
}

function jobAnswers(r){
  const a={};
  r.needs.forEach(n=>{
    if(n.key==='deliver'){a.deliver=(document.querySelector('input[name=jf-deliver]:checked')||{}).value||'report';return}
    const el=document.getElementById('jf-'+n.key);
    if(el)a[n.key]=el.value.trim();
  });
  return a;
}

/* Ask the server what saving this would grant, and print it. Debounced by the
   caller; a failure is silent because it is an aid, not the decision — the save
   itself refuses with the same message if the answers are bad. */
async function jobConsent(r){
  const box=document.getElementById('jf-consent');if(!box)return;
  try{
    const d=await (await fetch('/api/jobs/preview',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({recipe:r.id,answers:jobAnswers(r)})})).json();
    if(d.error){box.innerHTML=`<span class="job-warn">${esc(d.error)}</span>`;return}
    const reads=(d.reads||[]).map(p=>`<li>reads <code>${esc(p)}</code> — and nothing else</li>`).join('');
    const net=(d.net||[]);
    const reach=!net.length?'':net[0]==='*'?'<li>may read the open web (it is research)</li>'
      :`<li>may fetch ${net.length===1?'one address':net.length+' addresses'}: ${net.slice(0,3).map(u=>`<code>${esc(u)}</code>`).join(', ')}${net.length>3?' …':''} — and nothing else</li>`;
    const when=(d.triggers||[]).map(t=>{
      const c=t.config||{};
      if(t.kind==='cron'&&c.type==='daily')return `<li>runs every day at ${esc(c.at)}</li>`;
      if(t.kind==='cron'&&c.type==='weekly')return `<li>runs every ${esc(WEEKDAY_NAMES[+c.day||0])} at ${esc(c.at)}</li>`;
      if(t.kind==='cron'&&c.type==='interval')return `<li>runs every ${esc(c.minutes)} minutes</li>`;
      if(t.kind==='os_event')return `<li>runs when something changes in that folder</li>`;
      return '';
    }).join('');
    box.innerHTML=`<b>What you are agreeing to</b><ul>${when}${reads}${reach}
      <li>delivers by: ${esc((d.delivery||{}).label||'report')}</li>
      <li>${d.grants.length} permission${d.grants.length===1?'':'s'}, all revocable in Permissions</li></ul>`;
  }catch(e){}
}

/* Wire a rendered form: live consent, and the save. `after(res)` is what the
   surface does with the finished mission — the wizard shows a "run it now" beat,
   the app refreshes its list. */
function jobWire(root,r,after){
  root.querySelectorAll('.job-form input,.job-form textarea,.job-form select').forEach(el=>{
    let t=null;
    const go=()=>{clearTimeout(t);t=setTimeout(()=>jobConsent(r),260)};
    el.oninput=go;el.onchange=go;
  });
  jobConsent(r);
  const btn=root.querySelector('#jf-save');
  btn.onclick=async()=>{
    if(JOBS.busy)return;JOBS.busy=true;btn.disabled=true;const was=btn.textContent;btn.textContent='Setting it up…';
    try{
      const res=await (await fetch('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({recipe:r.id,answers:jobAnswers(r)})})).json();
      if(res.error){
        const c=document.getElementById('jf-consent');
        if(c)c.innerHTML=`<span class="job-warn">${esc(res.error)}</span>`;
        return;
      }
      await jobsLoad();
      after(res);
    }finally{JOBS.busy=false;btn.disabled=false;btn.textContent=was}
  };
}

/* One place that wires "cards → form → saved" for any container. */
function jobPickable(box,after){
  box.querySelectorAll('.job-card').forEach(b=>b.onclick=()=>{
    const r=JOBS.recipes.find(x=>x.id===b.dataset.job);if(!r)return;
    if(b.dataset.needs){SETTAB='accounts';localStorage.setItem('settab','accounts');openApp('settings');return}
    JOBS.pick=r.id;
    box.querySelectorAll('.job-card').forEach(x=>x.classList.toggle('on',x===b));
    const slot=box.querySelector('.job-slot');
    slot.innerHTML=jobForm(r);
    if(typeof Motion!=='undefined')Motion.run(slot,[{opacity:0,transform:'translateY(10px)'},{opacity:1,transform:'none'}],
      {duration:220,easing:EASE.out});
    jobWire(slot,r,res=>after(slot,res));
    slot.scrollIntoView({block:'nearest',behavior:'smooth'});
  });
}
function jobRedrawCards(box){
  const cards=box.querySelector('.job-catalogue');if(!cards)return;
  cards.innerHTML=jobCards(JOBS.pick);
  const slot=box.querySelector('.job-slot');if(slot)slot.innerHTML='';
  jobPickable(box,box._jobAfter||(()=>{}));
}

/* ---------- the wizard's last beat ---------- */
/* Called by wizFinish once the setup report is on screen. The offer is real but
   never compulsory: "Not now" is a first-class button, because a first-run flow
   that will not let you past it is a first-run flow people learn to click through
   without reading. */
async function jobStep(container,onDone){
  await jobsLoad();
  if(!JOBS.recipes.length){onDone();return}
  const box=document.createElement('div');box.className='wiz-jobs';
  const name=(typeof WIZ!=='undefined'&&WIZ.agent_name)||'your agent';
  box.innerHTML=`<div class="wiz-jobs-head">
      <b>Last thing — what should I do for you every day?</b>
      <span>Say who you are and pick a mission. I'll do it from now on, without being asked, inside exactly the permissions it prints. You can change or stop it any time.</span>
    </div>
    ${jobReadyLine()}
    ${jobPersonaBar()}
    <div class="job-catalogue">${jobCards('')}</div>
    <div class="job-slot"></div>
    <button class="wiz-back" id="jf-skip">Not now — take me in →</button>`;
  container.appendChild(box);
  Motion.run(box,[{opacity:0,transform:'translateY(14px)'},{opacity:1,transform:'none'}],
    {duration:280,easing:EASE.out});
  container.scrollTop=container.scrollHeight;
  box.querySelector('#jf-skip').onclick=onDone;
  box._jobAfter=(slot,res)=>jobDone(slot,res,onDone,name);
  jobPickable(box,box._jobAfter);
  jobWirePersona(box,()=>jobRedrawCards(box));
}

/* The payoff screen. "Run it now" is the important button: a schedule nobody has
   seen fire is a promise, and a new user has no reason to believe one. */
function jobDone(slot,res,onDone,name){
  const reads=(res.reads||[]).map(p=>`<div class="sub">· reads ${esc(p)}</div>`).join('');
  slot.innerHTML=`<div class="job-done">
    <b>✓ ${esc(res.flow.name)}</b>
    <div class="sub">· runs ${esc(res.next||'when you say so')}</div>
    <div class="sub">· delivers: ${esc((res.delivery||{}).label||'to Reports')}</div>
    ${reads}
    ${res.substituted?`<div class="sub job-warn">· ${esc(res.substituted)}</div>`:''}
    <div class="job-go">
      <button class="wiz-next" id="jf-run">Run it now, so I can see it work</button>
      <button class="wiz-back" id="jf-enter">Take me in →</button></div></div>`;
  Motion.run(slot.firstElementChild,[{opacity:0,transform:'scale(.98)'},{opacity:1,transform:'none'}],
    {duration:260,easing:EASE.spring});
  slot.querySelector('#jf-enter').onclick=onDone;
  slot.querySelector('#jf-run').onclick=async()=>{
    const b=slot.querySelector('#jf-run');b.disabled=true;b.textContent=`${name} is on it…`;
    try{
      const d=await (await fetch(`/api/jobs/${encodeURIComponent(res.flow.name)}/run`,
        {method:'POST'})).json();
      if(d.error){b.textContent=d.error;b.disabled=false;return}
      onDone();
      // the run is live: show it, rather than describing it
      if(typeof fgWatch==='function')fgWatch(d.run_id); else openApp('fabric');
    }catch(e){b.textContent='could not start it';b.disabled=false}
  };
}

/* ---------- the standing app: what it does, and what it did ---------- */
function jobAgo(ts){
  if(!ts)return '';
  const s=Math.max(0,Date.now()/1000-ts);
  if(s<90)return 'just now';
  if(s<5400)return Math.round(s/60)+' min ago';
  if(s<129600)return Math.round(s/3600)+' h ago';
  return Math.round(s/86400)+' d ago';
}
function jobSummaryLine(s){
  if(!s||!s.missions)return '';
  const n=(v,w)=>`${v} ${w}${v===1?'':'s'}`;
  return `<div class="job-sum" title="What your missions did in the last seven days. Tokens are counted here; what they cost is priced per model in Usage.">
    <b>${n(s.missions,'mission')}</b>
    <span>this week: ${n(s.runs_7d,'run')}, ${s.ok_7d} delivered${s.failed_7d?`, <i class="job-bad">${s.failed_7d} failed</i>`:''}</span>
    <span>${(s.tokens_7d||0).toLocaleString()} tokens</span>
    <span>${n(s.grants,'permission')} held</span>
  </div>`;
}
function jobRow(j){
  const last=j.last||{};
  const st=last.status||'';
  const cls=st==='ok'?'ok':st?'bad':'';
  const lastLine=!st?'<span class="job-last mut">has not run yet</span>'
    :`<span class="job-last ${cls}"><b>${esc(st)}</b> · ${esc(jobAgo(last.at))}${last.said?` · <q>${esc(last.said)}</q>`:''}</span>`;
  return `<div class="item job-row${j.enabled?'':' off'}${j.running?' live':''}">
    <div class="grow">
      <b>${esc(j.title||j.name)}</b> <span class="job-name">${esc(j.name)}</span>${j.running?'<span class="job-live">running</span>':''}
      <div class="sub">${lastLine}</div>
      <div class="sub">${j.enabled?'next: '+esc(j.next):'switched off'} · this week: ${j.runs_7d} run${j.runs_7d===1?'':'s'}, ${j.ok_7d} ok · ${(j.tokens_7d||0).toLocaleString()} tokens · holds ${j.grants} permission${j.grants===1?'':'s'}</div>
    </div>
    <button class="endbtn" onclick="jobRunNow('${esc(j.name)}')">Run now</button>
    ${last.run_id?`<button class="endbtn" onclick="fgWatch('${esc(last.run_id)}')">Last run</button>`:''}
    <button class="endbtn" onclick="openFLW('${esc(j.name)}')">Edit</button>
  </div>`;
}
async function renderJobs(body){
  body.innerHTML='<div class="pad"><p class="mut">Reading…</p></div>';
  await jobsLoad();
  const rows=JOBS.installed.map(jobRow).join('');
  const who=JOBS.personas.find(x=>x.id===JOBS.persona);
  body.innerHTML=`<div class="pad job-app">
    <h3>What this machine does for you</h3>
    ${jobReadyLine()}
    ${jobSummaryLine(JOBS.summary)}
    ${rows||`<p class="mut">Nothing standing yet. Say who you are, pick a mission, and it starts today — inside exactly the permissions it prints.</p>`}
    <h3 style="margin-top:18px">${rows?'Give it another mission':'Give it a mission'}</h3>
    <p class="mut job-whoq">${who?`Missions for a ${esc(who.label.toLowerCase())} first. Not you? Pick again.`:'Who are you? The catalogue opens on your missions from then on.'}</p>
    ${jobPersonaBar()}
    <div class="job-catalogue">${jobCards(JOBS.pick)}</div>
    <div class="job-slot"></div></div>`;
  body._jobAfter=(slot,res)=>{
    JOBS.pick='';
    toast(`✓ ${res.flow.name} — runs ${res.next||'when you say so'}`);
    renderJobs(body);
  };
  jobPickable(body,body._jobAfter);
  jobWirePersona(body,()=>renderJobs(body));
}

async function jobRunNow(name){
  try{
    const d=await (await fetch(`/api/jobs/${encodeURIComponent(name)}/run`,{method:'POST'})).json();
    if(d.error){toast(d.error);return}
    toast(`▶ ${name} started`);
    if(typeof fgWatch==='function')fgWatch(d.run_id);
  }catch(e){toast('could not start it')}
}
