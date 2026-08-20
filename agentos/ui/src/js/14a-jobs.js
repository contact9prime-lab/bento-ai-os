/* ================= jobs: give this machine something to do =================
   Two surfaces over one API (/api/jobs): the last beat of the first-run wizard,
   and a standing app you can come back to. They share `jobCards`/`jobForm` on
   purpose — the screen that gets somebody their first job and the screen that
   gets them their fourth should not drift apart, because the second one is the
   habit and the first one is only the introduction.

   Everything user-facing here obeys the honesty rule: a delivery this machine
   cannot do is shown greyed with the sentence that would fix it, never hidden,
   and the folder a job will read is printed before the job exists.

   `var`, not `let` — this file is concatenated into one script and 14-docs-setup
   calls jobStep() from wizFinish. See CLAUDE.md on the TDZ trap. */
var JOBS={recipes:[],deliveries:[],installed:[],pick:'',busy:false};

async function jobsLoad(){
  try{const d=await (await fetch('/api/jobs')).json();
    JOBS.recipes=d.recipes||[];JOBS.deliveries=d.deliveries||[];JOBS.installed=d.installed||[];
  }catch(e){JOBS.recipes=[];}
  return JOBS;
}

/* the three cards. `sel` is the id currently expanded, '' for none. */
function jobCards(sel){
  return `<div class="job-cards">${JOBS.recipes.map(r=>`
    <button class="job-card${r.id===sel?' on':''}" data-job="${esc(r.id)}">
      <span class="job-mark">${esc(r.icon||'◇')}</span>
      <b>${esc(r.title)}</b>
      <span class="job-blurb">${esc(r.blurb)}</span>
      <span class="job-eg">${esc(r.example)}</span>
    </button>`).join('')}</div>`;
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
    if(n.kind==='minutes')return `<label class="job-q"><span>${esc(n.label)}</span>
      <span class="job-mins"><input id="${id}" type="number" min="5" step="5" value="${esc(n.default||'60')}"> minutes</span>
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
    const scope=(d.scope||[]).map(h=>`<li>may reach <code>${esc(h)}</code> — and no other host</li>`).join('');
    const when=(d.triggers||[]).map(t=>{
      const c=t.config||{};
      if(t.kind==='cron'&&c.type==='daily')return `<li>runs every day at ${esc(c.at)}</li>`;
      if(t.kind==='cron'&&c.type==='interval')return `<li>runs every ${esc(c.minutes)} minutes</li>`;
      if(t.kind==='os_event')return `<li>runs when something changes in that folder</li>`;
      return '';
    }).join('');
    box.innerHTML=`<b>What you are agreeing to</b><ul>${when}${reads}${scope}
      <li>delivers by: ${esc((d.delivery||{}).label||'report')}</li>
      <li>${d.grants.length} permission${d.grants.length===1?'':'s'}, all revocable in Permissions</li></ul>`;
  }catch(e){}
}

/* Wire a rendered form: live consent, and the save. `after(res)` is what the
   surface does with the finished job — the wizard shows a "run it now" beat,
   the app refreshes its list. */
function jobWire(root,r,after){
  root.querySelectorAll('.job-form input').forEach(el=>{
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
      <b>One last thing — give me a job.</b>
      <span>Pick one and I'll do it from now on, without being asked. You can change or stop it any time.</span>
    </div>
    ${jobCards('')}
    <div class="job-slot"></div>
    <button class="wiz-back" id="jf-skip">Not now — take me in →</button>`;
  container.appendChild(box);
  Motion.run(box,[{opacity:0,transform:'translateY(14px)'},{opacity:1,transform:'none'}],
    {duration:280,easing:EASE.out});
  container.scrollTop=container.scrollHeight;
  box.querySelector('#jf-skip').onclick=onDone;
  box.querySelectorAll('.job-card').forEach(b=>b.onclick=()=>{
    const r=JOBS.recipes.find(x=>x.id===b.dataset.job);if(!r)return;
    JOBS.pick=r.id;
    box.querySelectorAll('.job-card').forEach(x=>x.classList.toggle('on',x===b));
    const slot=box.querySelector('.job-slot');
    slot.innerHTML=jobForm(r);
    Motion.run(slot,[{opacity:0,transform:'translateY(10px)'},{opacity:1,transform:'none'}],
      {duration:220,easing:EASE.out});
    jobWire(slot,r,res=>jobDone(slot,res,onDone,name));
    container.scrollTop=container.scrollHeight;
  });
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

/* ---------- the standing app ---------- */
async function renderJobs(body){
  body.innerHTML='<div class="pad"><p class="mut">Reading…</p></div>';
  await jobsLoad();
  const running=JOBS.installed.map(j=>`<div class="item job-row">
      <div class="grow"><b>${esc(j.name)}</b><div class="sub">${esc(j.description)}</div>
        <div class="sub">${j.enabled?'next: '+esc(j.next):'switched off'}</div></div>
      <button class="endbtn" onclick="jobRunNow('${esc(j.name)}')">Run now</button>
      <button class="endbtn" onclick="openApp('fabric')">Edit</button>
    </div>`).join('');
  body.innerHTML=`<div class="pad job-app">
    <h3>What this machine does for you</h3>
    ${running||'<p class="mut">Nothing standing yet — pick something below and it starts today.</p>'}
    <h3 style="margin-top:18px">Give it another job</h3>
    ${jobCards(JOBS.pick)}
    <div class="job-slot"></div></div>`;
  body.querySelectorAll('.job-card').forEach(b=>b.onclick=()=>{
    const r=JOBS.recipes.find(x=>x.id===b.dataset.job);if(!r)return;
    JOBS.pick=r.id;
    body.querySelectorAll('.job-card').forEach(x=>x.classList.toggle('on',x===b));
    const slot=body.querySelector('.job-slot');
    slot.innerHTML=jobForm(r);
    jobWire(slot,r,res=>{
      JOBS.pick='';
      toast(`✓ ${res.flow.name} — runs ${res.next||'when you say so'}`);
      renderJobs(body);
    });
  });
}

async function jobRunNow(name){
  try{
    const d=await (await fetch(`/api/jobs/${encodeURIComponent(name)}/run`,{method:'POST'})).json();
    if(d.error){toast(d.error);return}
    toast(`▶ ${name} started`);
    if(typeof fgWatch==='function')fgWatch(d.run_id);
  }catch(e){toast('could not start it')}
}
