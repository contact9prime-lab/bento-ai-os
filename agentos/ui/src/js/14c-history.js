/* ================= Missions → History (agentos/runlog.py) =================
   "I can't find the runs of the schedules in the mission." A scheduled prompt's answer
   was a chat nobody could trace back to its schedule, the Schedule tab showed only the
   last result, and a mission's runs were three tabs deep under Build → Runs. So one
   list: everything that ran on its own, newest first, each saying what started it, how
   it went and how long it took, with the door to what it produced (the Run inspector
   for a mission, the conversation in Chat for a scheduled prompt).

   The rows are /api/missions/history, one computation (runlog.history) that `bento job
   history` prints too. A Runs button on a Schedule row or a mission row opens this tab
   filtered to that one (JOBS.hist).
   Faces: GUI and SUI are this page; TUI is `bento job history`. */
function jobHistoryFor(f){
  if(typeof JOBS==='undefined')return;
  JOBS.hist=f||null;JOBS.histShow='all';JOBS.tab='history';
  openApp('jobs');refreshApp('jobs');
}
function jobHistWhen(ts){
  if(!ts)return '';
  const d=new Date(ts*1000),today=new Date();
  const same=d.toDateString()===today.toDateString();
  return (same?'today ':d.toLocaleDateString([],{weekday:'short',day:'numeric',month:'short'})+' ')
    +d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
}
function jobHistTook(s){
  if(s==null)return '';
  if(s<60)return s+'s';
  if(s<3600)return Math.round(s/60)+' min';
  return (s/3600).toFixed(1)+' h';
}
var JOB_HIST_WORD={running:'running',ok:'done',partial:'partly done',failed:'failed',waiting:'waiting for you',
  stopped:'stopped',skipped:'skipped'};
function jobHistRow(r){
  const door=r.run_id?`<button class="endbtn" data-open-run="${esc(r.run_id)}">Open run</button>`
    :r.conversation_id?`<button class="endbtn" data-open-conv="${esc(r.conversation_id)}">Open in Chat</button>`:'';
  return `<div class="item job-hrow ${esc(r.status)}">
    <div class="grow">
      <div class="job-hhead"><span class="job-hst ${esc(r.status)}">${esc(JOB_HIST_WORD[r.status]||r.status)}</span>
        <b>${esc(r.title)}</b>${r.kind==='prompt'?'<span class="job-hkind">scheduled prompt</span>':''}</div>
      <div class="sub">${esc(jobHistWhen(r.started_at))}${r.seconds!=null&&r.status!=='skipped'?' · took '+esc(jobHistTook(r.seconds)):''} · ${esc(r.started_by)}${
        r.tokens?' · '+r.tokens.toLocaleString()+' tokens':''}</div>
      ${r.said?`<div class="sub job-hsaid">${esc(r.said)}</div>`:''}
    </div>${door}</div>`;
}
async function renderJobHistory(body){
  const f=JOBS.hist||{};
  const q=new URLSearchParams();if(f.task_id)q.set('task',f.task_id);if(f.mission)q.set('mission',f.mission);
  body.innerHTML=`<div class="pad job-app">${jobTabs()}<p class="mut">Reading…</p></div>`;
  let d;
  try{d=await apiJSON('/api/missions/history'+(q.toString()?'?'+q:''))}
  catch(e){body.innerHTML=`<div class="pad job-app">${jobTabs()}<p class="mut">${esc(e.message||String(e))}</p></div>`;return}
  const show=JOBS.histShow||'all',c=d.counts||{};
  const rows=(d.runs||[]).filter(r=>show==='all'||(show==='scheduled'&&r.scheduled)||(show==='failed'&&r.status==='failed')
    ||(show==='prompts'&&r.kind==='prompt'));
  const chip=(k,l,n)=>`<button class="of-chip${show===k?' on':''}" data-show="${k}" aria-pressed="${show===k}">${l}${n?' '+n:''}</button>`;
  const title=(d.filter||{}).title;
  body.innerHTML=`<div class="pad job-app">${jobTabs()}
    <h3>${title?'Runs of '+esc(title):'Everything that ran on its own'}</h3>
    ${title?`<p class="mut"><button class="co-link" data-all>Show every run</button></p>`
      :`<p class="mut">Missions and scheduled prompts, newest first. ${c.week||0} this week${c.failed?`, <b class="job-bad">${c.failed} failed</b>`:''}.</p>`}
    <div class="of-chips job-hchips">${chip('all','All')}${chip('scheduled','On a schedule',c.scheduled)}${chip('prompts','Scheduled prompts')}${chip('failed','Failed',c.failed)}</div>
    <div class="job-hlist">${rows.map(jobHistRow).join('')||`<p class="mut">${title?'This has not run yet.':'Nothing has run on its own yet. A mission you switch on, or a prompt you schedule, shows here each time it runs.'}</p>`}</div></div>`;
  body.querySelectorAll('[data-show]').forEach(b=>b.onclick=()=>{JOBS.histShow=b.dataset.show;renderJobHistory(body)});
  const all=body.querySelector('[data-all]');if(all)all.onclick=()=>{JOBS.hist=null;renderJobHistory(body)};
  body.querySelectorAll('[data-open-run]').forEach(b=>b.onclick=()=>fgWatch(b.dataset.openRun));
  body.querySelectorAll('[data-open-conv]').forEach(b=>b.onclick=()=>{openApp('chat');setTimeout(()=>openConv(b.dataset.openConv),150)});
}
