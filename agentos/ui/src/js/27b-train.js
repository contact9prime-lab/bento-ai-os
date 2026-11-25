/* ================= Train: a small language model of your own =================
   The page of agentos/slm.py. One answer (/api/train) drawn as four places: Make (say the
   job, see the plan, watch it go through Examples, Training and the Check), Datasets (the
   Hub, a teacher, a file), Runs (a fine-tune as it happens) and Models (what the held-back
   examples say, try it, put it in Ollama, publish it).

   It used to be an iframe onto another server on a loopback port, which a phone or any
   remote browser could not reach at all. Then it was a form in boxes, and the owner's word
   for that was "really bad". What it shows now is the thing itself: a teacher, a student
   and this machine, a line of stages that fills as the work is done, and a model as a
   scoreboard of before and after.

   GUI: this. TUI: `bento train` (the same files, with the server down). SUI: this page,
   no native process, nothing touching the compositor.

   Everything a dataset, a teacher or a model said is somebody else's words: every one of
   them goes through esc() on the way to the page. State is `var`: 09-websocket.js calls
   trainPulse() and loads first. */
var TRAIN={tab:'make',d:null,plan:null,goal:'',hub:[],hubQ:'',ds:null,job:null,jobd:null,model:null,busy:'',tried:null,logOff:0,logText:'',src:'teacher'};

/* drawn here, nothing copied: 24x24, stroke only */
var TRN_IC={
  make:'<path d="M12 3l1.8 4.9L19 9.5l-4.1 2.9L16 18l-4-3-4 3 1.1-5.6L5 9.5l5.2-1.6z"/>',
  data:'<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/><path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/>',
  runs:'<path d="M3 17l5-6 4 3 4-7 5 5"/><path d="M3 21h18"/>',
  models:'<path d="M12 2l8 4.5v9L12 20l-8-4.500v-9z"/><path d="M4 6.500l8 4.500 8-4.500M12 11v9"/>',
  teacher:'<path d="M3 9l9-5 9 5-9 5z"/><path d="M7 11.500V16c0 1.400 2.200 2.500 5 2.500s5-1.100 5-2.500v-4.500"/><path d="M21 9v5"/>',
  student:'<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="8"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2"/>',
  chip:'<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
  hub:'<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>',
  file:'<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
  check:'<path d="M5 12.500l4.500 4.500L19 7.500"/>',
  arrow:'<path d="M5 12h14M13 6l6 6-6 6"/>',
  play:'<path d="M7 5l12 7-12 7z"/>'};
function trnIc(n,cls){return `<svg class="trn-ic ${cls||''}" viewBox="0 0 24 24" aria-hidden="true">${TRN_IC[n]||''}</svg>`}

function trainWin(){return (typeof winsOf==='function'?winsOf('train'):[])[0]}
function trainBody(){const w=trainWin();return w&&w.el.querySelector('.wbody')}
function trainPulse(ev){               /* the server says something of mine changed */
  if(!trainBody())return;
  clearTimeout(TRAIN._t);TRAIN._t=setTimeout(trainLoad,250);
}
async function trainApi(path,method,body,raw){
  const o={method:method||'GET'};
  if(raw){o.body=raw}else if(body!==undefined){o.headers={'Content-Type':'application/json'};o.body=JSON.stringify(body)}
  return apiJSON(path,o);
}
async function trainDo(label,fn){      /* one action at a time, and a failure is a sentence */
  if(TRAIN.busy)return;
  TRAIN.busy=label;trainPaint();
  try{await fn()}catch(e){toast(e.message||String(e),{kind:'err'})}
  TRAIN.busy='';await trainLoad();
}
function trainAgo(t){
  if(!t)return '';
  const s=Math.max(0,Date.now()/1000-t);
  return s<90?'just now':s<3600?Math.round(s/60)+' min ago':s<86400?Math.round(s/3600)+' h ago':Math.round(s/86400)+' d ago';
}
function trainMB(b){return b>=2**30?(b/2**30).toFixed(1)+' GB':Math.round((b||0)/2**20)+' MB'}
function trainShort(id){return String(id||'').split('/').pop()}
function trainHw(d){const hw=d.hardware||{};
  return d.ready?(hw.device==='cuda'?(hw.name||'NVIDIA GPU'):hw.device==='mps'?'Apple GPU':'Processor only'):'Not installed'}
function trainWord(v){                  /* never colour alone: an icon and the word */
  const w=(v&&v.word)||'unchecked';
  const ic=w==='learned'?'✓':w==='no better'?'=':w==='partly'?'~':w==='one answer'?'1':'?';
  return `<span class="trn-word trn-${w.replace(' ','-')}"><i>${ic}</i>${esc(w)}</span>`;
}
/* Before and after, as two bars on one scale with the counts written out. The same measure
   for both, so one axis; the base model is the quiet bar and yours is the accent. */
function trainScore(ev,big){
  const n=(ev&&ev.n)|0;if(!n)return '<div class="mut">Nothing was held back, so there is no check.</div>';
  const b=ev.exact_before|0,a=ev.exact_after|0,w=x=>Math.max(2,Math.round(100*x/n));
  return `<div class="trn-score${big?' big':''}" role="img" aria-label="On ${n} held-back examples the base model matched ${b} and yours matches ${a}">
    <div class="trn-sr"><span>Base model</span><div class="trn-sb"><i style="width:${w(b)}%"></i></div><b>${b}<small> of ${n}</small></b></div>
    <div class="trn-sr mine"><span>Yours</span><div class="trn-sb"><i style="width:${w(a)}%"></i></div><b>${a}<small> of ${n}</small></b></div>
  </div>`;
}

async function renderTrain(body,w){
  stopWinTicks(w);
  body.style.cssText='padding:0;height:100%';
  body.innerHTML='<div class="trn"><div class="mut" style="padding:24px">loading…</div></div>';
  await trainLoad();
  /* poll only while something is at work; the socket's `train` event covers the rest */
  winTick(w,()=>{const d=TRAIN.d;if(!d)return;
    const live=d.running||(d.datasets_list||[]).some(x=>x.state!=='ready')||(d.runs_list||[]).some(x=>x.state==='running');
    if(live)trainLoad()},3000,{now:false,key:'poll'});
}
async function trainLoad(){
  const body=trainBody();if(!body)return;
  try{TRAIN.d=await trainApi('/api/train')}
  catch(e){body.innerHTML=`<div class="trn"><div class="errmsg" style="margin:16px">${esc(e.message)}</div></div>`;return}
  if(TRAIN.tab==='runs')await trainJobLoad();
  trainPaint();
}
async function trainTab(t){TRAIN.tab=t;trainPaint();if(t==='runs'){await trainJobLoad();trainPaint()}}

function trainPaint(){
  const body=trainBody(),d=TRAIN.d;if(!body||!d)return;
  /* keep what is being typed: a repaint must not eat a half-written goal */
  const keep={};body.querySelectorAll('[data-keep]').forEach(el=>{keep[el.id]={v:el.value,f:document.activeElement===el,s:el.selectionStart}});
  const sc=(body.querySelector('.trn-pane')||{}).scrollTop||0;
  const tabs=[['make','Make','make'],['datasets','Datasets','data',d.datasets],['runs','Runs','runs',d.jobs],['models','Models','models',d.models]];
  body.querySelector('.trn').innerHTML=`<div class="trn-g">
    <nav class="trn-rail" aria-label="Train">
      <div class="trn-tabs">${tabs.map(([id,l,ic,n])=>`<button class="${TRAIN.tab===id?'on':''}" ${TRAIN.tab===id?'aria-current="page"':''} onclick="trainTab('${jsq(id)}')">${trnIc(ic)}<span>${l}</span>${n?`<small>${n}</small>`:''}</button>`).join('')}</div>
      <div class="trn-rig" title="${esc((d.hardware||{}).words||'')}">
        <div><span>Teacher</span><b>${esc(d.teacher||'none yet')}</b></div>
        <div><span>This machine</span><b>${esc(trainHw(d))}</b></div>
      </div>
    </nav>
    <div class="trn-pane">${trainSetup(d)}${({make:trainMake,datasets:trainDatasets,runs:trainRuns,models:trainModels})[TRAIN.tab](d)}</div></div>`;
  for(const id in keep){const el=body.querySelector('#'+id);if(el){el.value=keep[id].v;if(keep[id].f){el.focus();try{el.setSelectionRange(keep[id].s,keep[id].s)}catch(e){}}}}
  const pane=body.querySelector('.trn-pane');if(pane)pane.scrollTop=sc;
  if(TRAIN.tab==='runs')trainCurveWire();
}

/* ---- what is missing, said once at the top ---- */
function trainSetup(d){
  let h='';
  if(!d.ready)h+=`<div class="trn-need">${trnIc('chip')}<div class="grow"><b>Training isn't installed yet</b>
    <div class="mut">PyTorch and the Hugging Face libraries go in a folder of their own. You can collect examples before that.${pInfo('About 1 GB on a Mac and 5 GB or more on Linux, where PyTorch brings NVIDIA\'s libraries. Nothing is added to Bento itself.')}</div></div>
    <button class="pact" onclick="trainInstall()">Install…</button></div>`;
  if(d.teacher_missing)h+=`<div class="trn-need">${trnIc('teacher')}<div class="grow"><b>No teacher yet</b>
    <div class="mut">${esc(d.teacher_missing)}</div></div>
    <button class="endbtn" onclick="openApp('settings');setTimeout(()=>typeof settingsGo==='function'&&settingsGo('ai'),200)">AI providers</button></div>`;
  if(d.busy&&d.busy.name&&!d.running)h+=`<div class="trn-need">${trnIc('chip')}<div class="grow mut">Another account is training on this machine (${esc(d.busy.name)}). Yours can start when it ends.</div></div>`;
  return h;
}
async function trainInstall(){await installComponent('train-stack');trainLoad()}

/* ---- Make: say the job, see the plan, watch it go ---- */
var TRN_IDEAS=[['Sort support mail','Sort support mail into billing, bug or other. Answer with one word.'],
  ['Tag notes by urgency','Read a note from the warehouse floor and answer urgent or routine.'],
  ['Pull fields from invoices','From an invoice email, give the supplier, the amount and the due date as JSON.'],
  ['Spot a question','Say yes if the message asks me a question I have to answer, otherwise no.']];
function trainIdea(i){const el=$('#trn-goal');if(el){el.value=TRN_IDEAS[i][1];el.focus()}}
function trainMake(d){
  const p=TRAIN.plan,runs=d.runs_list||[],live=runs.find(r=>r.state==='running');
  let h=`<section class="trn-hero">
    <h1>Teach a small model one job.</h1>
    <p>A teacher writes the examples, a small model learns them on this machine, and examples it never saw check the result.</p>
    <div class="trn-ask">
      <label class="trn-vh" for="trn-goal">What should the small model do?</label>
      <textarea id="trn-goal" data-keep rows="2" placeholder="What should the small model do?">${esc(TRAIN.goal)}</textarea>
      <div class="trn-askrow">
        <div class="trn-ideas">${TRN_IDEAS.map((x,i)=>`<button onclick="trainIdea(${i})">${esc(x[0])}</button>`).join('')}</div>
        <button class="pact trn-go" ${TRAIN.busy?'disabled':''} onclick="trainPlan()">${TRAIN.busy==='plan'?'Planning…':'Plan it'}${trnIc('arrow')}</button>
      </div>
    </div>
  </section>`;
  if(p)h+=trainPlanHTML(p,d);
  else if(!runs.length)h+=`<ol class="trn-how">
      <li>${trnIc('teacher')}<b>Examples</b><span>${esc(d.teacher||'Your machine\'s brain')} writes them, or bring a dataset.</span></li>
      <li>${trnIc('chip')}<b>Training</b><span>A small open model is fine-tuned here. Nothing leaves.</span></li>
      <li>${trnIc('check')}<b>The check</b><span>Examples it never saw, before and after.</span></li>
      <li>${trnIc('models')}<b>Use it</b><span>Try it, or put it in Ollama for an agent.</span></li></ol>`;
  if(runs.length)h+=`<h2 class="trn-sec">${live?'Under way':'Made from a goal'}</h2>`+runs.map(r=>trainRunHTML(r,d)).join('');
  return h;
}
function trainPlanHTML(p,d){
  const bases=(d.bases||[]),cur=bases.find(b=>b.id===p.base)||{id:p.base,params:'',licence:'',note:''};
  const opts=bases.map(b=>`<option value="${esc(b.id)}" ${b.id===p.base?'selected':''}>${esc(trainShort(b.id))} · ${esc(b.params)}</option>`).join('');
  const calls=p.source==='synthetic'?Math.ceil((p.examples||0)/((d.limits||{}).batch||10)):0;
  const hw=d.hardware||{};
  return `<section class="trn-plan">
    <div class="trn-planhead"><h2>The plan</h2><span class="mut">${esc(p.how||'')}. Change anything before it starts.</span></div>
    <div class="trn-fields">
      <label class="trn-l">Name<input id="trn-p-name" data-keep value="${esc(p.name)}"></label>
      <label class="trn-l trn-wide">The instruction it works under<textarea id="trn-p-task" data-keep rows="2">${esc(p.task)}</textarea></label>
    </div>
    <div class="trn-flow">
      <div class="trn-node">${trnIc('teacher')}<span class="k">Teacher</span><b>${esc(p.teacher||'none yet')}</b>
        <label class="trn-l">Examples to write<input id="trn-p-n" data-keep type="number" min="20" max="1000" value="${p.examples|0}"></label>
        <span class="mut trn-cost">${p.source==='hub'?`From the Hugging Face Hub (search: ${esc(p.hub_query)}). The teacher answers any without an answer.`
          :`It writes them in about ${calls} calls, counted in Usage.`}</span></div>
      <div class="trn-link">${trnIc('arrow')}</div>
      <div class="trn-node">${trnIc('student')}<span class="k">Student</span>
        <label class="trn-l trn-pick"><span class="trn-vh">Student</span><select id="trn-p-base" data-keep>${opts}</select></label>
        <span class="mut">${esc(cur.licence||'')}${cur.note?' · '+esc(cur.note):''}</span>
        <label class="trn-l">Passes over the examples<input id="trn-p-ep" data-keep type="number" min="1" max="20" step="1" value="${p.epochs||3}"></label></div>
      <div class="trn-link">${trnIc('arrow')}</div>
      <div class="trn-node">${trnIc('chip')}<span class="k">This machine</span><b>${esc(trainHw(d))}</b>
        <span class="mut">${esc(d.ready?(hw.words||''):'Install training first.')}</span>
        <span class="mut">One in ten examples is held back to check it.</span></div>
    </div>
    ${(p.dropped||[]).length?`<div class="mut">Not used from the plan: ${esc(p.dropped.join(', '))}.</div>`:''}
    <div class="trn-row trn-end"><button class="endbtn" onclick="TRAIN.plan=null;trainPaint()">Discard</button>
      <button class="pact trn-go" ${(!d.ready||d.teacher_missing||TRAIN.busy)?'disabled':''} onclick="trainRun()">Make it${trnIc('play')}</button></div>
  </section>`;
}
/* A run as a line of stages that fills as the work is done. Which stage is lit is read from
   the run's own steps and its job, never from a timer. */
function trainRunHTML(r,d){
  const steps=r.steps||[],last=steps[steps.length-1]||{},has=t=>steps.some(s=>s.title===t);
  const m=(d.models_list||[]).find(x=>x.id===r.model),j=(d.jobs_list||[]).find(x=>x.id===r.job);
  const dsr=(d.datasets_list||[]).find(x=>x.id===r.dataset)||{},pr=dsr.progress||{};
  /* the base model answers the held-back examples BEFORE training, so that belongs to Training;
     the check is what comes after */
  const checking=!!j&&j.state==='running'&&/after training|merging|saving/.test(j.phase||'');
  const first=!!j&&j.state==='running'&&/before training/.test(j.phase||'');
  const st=[
    ['Examples',has('Wrote examples')||has('Imported from the Hub')||!!r.job,last.title==='Writing examples'||last.title==='Answering',
      pr.want?`${pr.done|0} of ${pr.want}`:dsr.rows?dsr.rows+' ready':((r.plan||{}).examples|0)+' to write',pr.want?(pr.done/pr.want):null],
    ['Training',!!r.model||(j&&j.state==='done'),!!j&&j.state==='running'&&!checking,
      j?(j.state==='running'?(first?`the base model answers first, ${j.step} of ${j.total}`:j.total&&j.phase==='training'?`step ${j.step} of ${j.total}`:checking?j.rows+' learned from':j.phase):j.rows+' learned from'):trainShort((r.plan||{}).base),
      j&&j.total&&j.phase==='training'?j.step/j.total:null],
    ['The check',!!r.model,checking,
      m&&m.eval&&m.eval.n?`${m.eval.exact_after} of ${m.eval.n} match`:checking&&j.total?`${j.step} of ${j.total} answered`:'on examples it never saw',
      checking&&j.total?j.step/j.total:null]];
  const bad=r.state==='failed'||r.state==='stopped';
  return `<article class="trn-run trn-${esc(r.state)}">
    <header><div class="grow"><b>${esc((r.plan||{}).name||'run')}</b><span class="mut">${esc((r.plan||{}).task||'')}</span></div>
      <span class="mut">${esc(trainAgo(r.created))}</span>
      ${r.state==='running'?`<button class="endbtn" onclick="trainDo('stop',()=>trainApi('/api/train/runs/${jsq(r.id)}/stop','POST',{}))">Stop</button>`:''}</header>
    <ol class="trn-stages">${st.map(([name,done,now,sub,frac],i)=>`
      <li class="${done?'done':now&&r.state==='running'?'now':''}">
        <div class="top"><span class="dot">${done?trnIc('check'):i+1}</span><i class="ln"></i></div>
        <b>${name}</b><span class="sub">${esc(sub||'')}</span>
        ${now&&r.state==='running'&&frac!=null?`<div class="bar"><i style="width:${Math.max(4,Math.round(100*frac))}%"></i></div>`:''}</li>`).join('')}</ol>
    ${bad?`<div class="${r.state==='failed'?'errmsg':'mut'}">${esc(last.detail||last.title||'')}</div>`:''}
    ${m?`<div class="trn-result">${trainScore(m.eval,true)}
      <div class="trn-rside">${trainWord(m.verdict)}
        <button class="pact" onclick="trainOpenModel('${jsq(m.id)}')">Open the model</button></div></div>`:''}
    <details class="trn-said"><summary>What happened, step by step</summary>
      <ol class="trn-steps">${steps.map(s=>`<li><b>${esc(s.title)}</b> <span>${esc(s.detail)}</span></li>`).join('')}</ol></details>
  </article>`;
}
async function trainPlan(){
  const goal=($('#trn-goal')||{}).value||'';TRAIN.goal=goal;
  if(!goal.trim())return toast('Say what the model should do.');
  await trainDo('plan',async()=>{TRAIN.plan=await trainApi('/api/train/plan','POST',{goal})});
}
async function trainRun(){
  const p=Object.assign({},TRAIN.plan,{name:$('#trn-p-name').value,task:$('#trn-p-task').value,
    examples:+$('#trn-p-n').value||200,base:$('#trn-p-base').value,epochs:+$('#trn-p-ep').value||3});
  await trainDo('run',async()=>{await trainApi('/api/train/runs','POST',{goal:TRAIN.goal,plan:p});TRAIN.plan=null;TRAIN.goal=''});
}

/* ---- Datasets ---- */
async function trainSrc(s){TRAIN.src=s;trainPaint();
  if(s==='devices'){try{TRAIN.devs=(await trainApi('/api/train/devices')).machines||[]}catch(e){TRAIN.devs=[]}trainPaint()}}
async function trainFromDevice(key){
  const days=+(($('#trn-dv-days')||{}).value)||7;
  await trainDo('devices',async()=>{const ds=await trainApi('/api/train/datasets/devices','POST',{machine:key,days});toast(ds.words)});
}
function trainDatasets(d){
  const lim=d.limits||{},src=TRAIN.src;
  const tile=(id,ic,t,sub)=>`<button class="trn-src ${src===id?'on':''}" aria-pressed="${src===id}" onclick="trainSrc('${jsq(id)}')">${trnIc(ic)}<b>${t}</b><span>${sub}</span></button>`;
  let h=`<h2 class="trn-sec first">Add examples</h2>
    <div class="trn-srcs">${tile('teacher','teacher','A teacher writes them','Describe the job. '+esc(d.teacher||'Your machine\'s brain')+' does the writing.')}
      ${tile('hub','hub','Hugging Face Hub','Search public datasets and take the first rows of one.')}
      ${tile('devices','chip','Your devices','Sensor readings, with the alarms that followed as the answers.')}
      ${tile('file','file','A file','CSV, TSV, JSON or JSONL of your own.')}</div>
    <div class="trn-card trn-srcbody">`;
  if(src==='teacher')h+=`<label class="trn-l" for="trn-task">The job, as you would tell a person</label>
      <textarea id="trn-task" data-keep rows="3" placeholder="What comes in, and what to answer."></textarea>
      <div class="trn-row"><label class="trn-l trn-inl">How many<input id="trn-n" data-keep type="number" min="10" max="${lim.teach||2000}" value="100"></label>
        <span class="mut">Ten to a call.${pInfo('Written examples are synthetic data: good for teaching a format or a sorting rule, and only as right as the teacher. Read some before you train on them.')}</span>
        <span class="sp"></span><button class="pact" ${d.teacher_missing||TRAIN.busy?'disabled':''} onclick="trainSynth()">Write them</button></div>`;
  else if(src==='hub')h+=`<div class="trn-row"><input id="trn-hubq" data-keep placeholder="Search public datasets: sentiment, sms spam, intent…" value="${esc(TRAIN.hubQ)}" onkeydown="if(event.key==='Enter')trainHub()">
        <button class="pact" onclick="trainHub()">${TRAIN.busy==='hub'?'Searching…':'Search'}</button></div>
      ${(TRAIN.hub||[]).map(r=>`<div class="trn-hub"><div class="grow"><b>${esc(r.repo)}</b>
          <div class="sub">${(r.downloads||0).toLocaleString()} downloads · ${esc(r.licence||'licence not stated')}${r.gated?' · gated':''}</div>
          ${r.about?`<div class="sub">${esc(r.about)}</div>`:''}</div>
          <button class="endbtn" ${r.gated&&!d.token?'disabled title="A gated dataset needs your Hugging Face token (Models)"':''} onclick="trainImport('${jsq(r.repo)}')">Import</button></div>`).join('')}`;
  else if(src==='devices'){
    const ms=TRAIN.devs;
    h+=!ms?'<div class="mut">loading…</div>':!ms.length?`<div class="trn-row"><div class="grow mut">No machine of yours has readings kept yet. They are kept once a Pi or an ESP32 node is set up in Devices.</div>
        <button class="endbtn" onclick="openApp('devices')">Open Devices</button></div>`
      :`<div class="trn-row"><label class="trn-l trn-inl">How far back<select id="trn-dv-days" data-keep><option value="1">1 day</option><option value="7" selected>7 days</option><option value="30">30 days</option></select></label>
          <span class="mut">Each example is 30 minutes of readings. The answer is the alarm that was on, the one that came next, or normal.${pInfo('The answers come from your own alarm record, so nobody writes them. A machine with no alarm on record gives windows without answers, which a teacher can fill in from your instruction.')}</span></div>`
        +ms.map(m=>`<div class="trn-hub"><span class="trn-badge">${trnIc('chip')}</span><div class="grow"><b>${esc(m.machine)}</b>
          <div class="sub">${(m.readings||0).toLocaleString()} readings since ${esc(new Date(m.since*1000).toLocaleDateString())} · ${m.alarms} ${m.alarms===1?'alarm':'alarms'} on record</div>
          <div class="sub">${esc(m.things.slice(0,6).map(t=>t.name).join(', '))}${m.things.length>6?' and '+(m.things.length-6)+' more':''}</div></div>
          <button class="pact" ${TRAIN.busy?'disabled':''} onclick="trainFromDevice('${jsq(m.key)}')">Make examples</button></div>`).join('');
  }
  else h+=`<div class="mut">A prompt column and an answer column. A file with prompts only is fine: a teacher can answer them.</div>
      <div class="trn-row"><input type="file" id="trn-file" accept=".csv,.tsv,.json,.jsonl,.txt" onchange="trainFile(this)"></div>`;
  h+='</div>';
  const list=d.datasets_list||[];
  h+=`<h2 class="trn-sec">Your datasets</h2>`;
  if(!list.length)h+='<div class="trn-empty">'+trnIc('data')+'<span>None yet.</span></div>';
  h+=list.map(x=>{
    const left=x.rows-(x.answers||0),pr=x.progress||{},open=TRAIN.ds&&TRAIN.ds.id===x.id;
    const working=x.state!=='ready',ic=x.source==='hub'?'hub':x.source==='synthetic'?'teacher':x.source==='devices'?'chip':'file';
    const from=x.source==='synthetic'?'written by '+(x.ref||'a teacher'):x.source==='hub'?x.ref:x.source==='devices'?'readings of '+(x.ref||'a machine'):'from '+(x.ref||'a file');
    return `<article class="trn-card trn-ds">
      <div class="trn-row"><span class="trn-badge">${trnIc(ic)}</span>
        <div class="grow"><button class="trn-name" onclick="trainOpenDs('${jsq(x.id)}')" aria-expanded="${open?'true':'false'}">${esc(x.name)}</button>
          <div class="mut">${x.rows} examples${left?`, ${left} without an answer`:''} · ${esc(from)}</div></div>
        ${working?`<button class="endbtn" onclick="trainDo('stop',()=>trainApi('/api/train/datasets/${jsq(x.id)}/stop','POST',{}))">Stop</button>`:`
          ${left?`<button class="endbtn" ${d.teacher_missing?'disabled':''} onclick="trainLabel('${jsq(x.id)}',${left})">Have the teacher answer</button>`:''}
          <button class="pact" ${(!d.ready||x.answers<(lim.min_rows||9))?'disabled':''} onclick="trainStartOn('${jsq(x.id)}')">Train on it</button>
          <button class="endbtn trn-x" title="Delete this dataset" aria-label="Delete ${esc(x.name)}" onclick="trainDelDs('${jsq(x.id)}')">✕</button>`}</div>
      ${working?`<div class="trn-prog"><div class="bar"><i style="width:${pr.want?Math.round(100*pr.done/pr.want):3}%"></i></div>
        <span class="mut">${esc(x.teacher||'The teacher')} is ${x.state==='writing'?'writing':'answering'}: ${pr.done|0} of ${pr.want|0}</span></div>`:''}
      ${x.note?`<div class="mut">${esc(x.note)}</div>`:''}
      ${open?trainDsOpen(TRAIN.ds):''}
    </article>`}).join('');
  return h;
}
function trainDsOpen(x){
  return `<div class="trn-open${x.source==='devices'?' trn-mono':''}">
    <label class="trn-l" for="trn-ds-task">The instruction the model is trained under</label>
    <div class="trn-row"><textarea id="trn-ds-task" data-keep rows="2">${esc(x.system||'')}</textarea>
      <button class="endbtn" onclick="trainDo('save',()=>trainApi('/api/train/datasets/${jsq(x.id)}','PUT',{system:$('#trn-ds-task').value}))">Save</button></div>
    <div class="trn-tw"><table class="trn-t trn-pairs"><thead><tr><th>Prompt</th><th>Answer</th></tr></thead><tbody>
      ${(x.sample||[]).map(r=>`<tr><td data-l="Prompt">${esc(r.prompt)}</td><td data-l="Answer">${r.response?esc(r.response):'<span class="mut">no answer yet</span>'}</td></tr>`).join('')}
    </tbody></table></div>
    <div class="mut">The first ${(x.sample||[]).length} of ${x.rows}.</div></div>`;
}
async function trainOpenDs(id){
  if(TRAIN.ds&&TRAIN.ds.id===id){TRAIN.ds=null;return trainPaint()}
  try{TRAIN.ds=await trainApi('/api/train/datasets/'+id+'?rows=20')}catch(e){toast(e.message,{kind:'err'})}
  trainPaint();
}
async function trainHub(){
  TRAIN.hubQ=($('#trn-hubq')||{}).value||'';
  if(!TRAIN.hubQ.trim())return;
  await trainDo('hub',async()=>{TRAIN.hub=(await trainApi('/api/train/hub?q='+encodeURIComponent(TRAIN.hubQ))).results||[];
    if(!TRAIN.hub.length)toast('Nothing on the Hub for those words.')});
}
async function trainImport(repo){
  const n=await osPrompt('Import '+repo,{message:'How many rows to take (the first of its training split).',value:'1000',confirmText:'Import'});
  if(n===null||n===undefined)return;
  await trainDo('import',async()=>{const ds=await trainApi('/api/train/datasets/hub','POST',{repo,max_rows:+n||1000});
    toast(`Imported ${ds.rows} rows. Read as: prompt = ${ds.how.prompt}, answer = ${ds.how.response||'none'}.`);TRAIN.hub=[]});
}
async function trainSynth(){
  const task=($('#trn-task')||{}).value||'',n=+($('#trn-n')||{}).value||100;
  if(!task.trim())return toast('Say what the job is.');
  const calls=Math.ceil(n/(((TRAIN.d||{}).limits||{}).batch||10));
  if(!await osConfirm('Have the teacher write '+n+' examples?',`${TRAIN.d.teacher} is asked about ${calls} times. The calls are counted in Usage.`,{confirmText:'Write them'}))return;
  await trainDo('synth',async()=>{await trainApi('/api/train/datasets/synth','POST',{task,n,name:task.split(/\s+/).slice(0,4).join(' ')});$('#trn-task').value=''});
}
async function trainLabel(id,left){
  if(!await osConfirm('Have the teacher answer '+left+' prompts?',`${TRAIN.d.teacher} is asked once for each. The calls are counted in Usage.`,{confirmText:'Answer them'}))return;
  await trainDo('label',()=>trainApi('/api/train/datasets/'+id+'/label','POST',{}));
}
async function trainFile(inp){
  const f=inp.files&&inp.files[0];if(!f)return;
  await trainDo('file',async()=>{const ds=await trainApi('/api/train/datasets/file?filename='+encodeURIComponent(f.name),'POST',undefined,f);
    toast(`Imported ${ds.rows} rows from ${f.name}.`)});
}
async function trainDelDs(id){
  if(!await osConfirm('Delete this dataset?','Models trained on it stay.',{confirmText:'Delete'}))return;
  await trainDo('del',()=>trainApi('/api/train/datasets/'+id,'DELETE'));
}
async function trainStartOn(id){
  const d=TRAIN.d,x=(d.datasets_list||[]).find(y=>y.id===id);if(!x)return;
  const base=await osPrompt('Train on “'+x.name+'”',{message:'The student, as owner/name on the Hugging Face Hub. This machine: '+((d.hardware||{}).words||''),value:d.suggested_base,confirmText:'Train'});
  if(!base)return;
  await trainDo('start',async()=>{const j=await trainApi('/api/train/jobs','POST',{dataset:id,base:base.trim(),name:x.name});
    TRAIN.job=j.id;TRAIN.logOff=0;TRAIN.logText='';TRAIN.jobd=null;TRAIN.tab='runs'});
}

/* ---- Runs: a fine-tune as it happens ---- */
function trainRuns(d){
  const list=d.jobs_list||[];
  if(!list.length)return '<div class="trn-empty">'+trnIc('runs')+'<span>No runs yet. Start one from a dataset, or from Make.</span></div>';
  const j=TRAIN.jobd&&TRAIN.jobd.id===TRAIN.job?TRAIN.jobd:null;
  const mark=x=>x.state==='running'?'<i class="trn-live"></i>':x.state==='done'?'✓':x.state==='failed'?'!':'·';
  return `<div class="trn-split"><div class="trn-list">${list.map(x=>`
      <button class="trn-li ${x.id===TRAIN.job?'on':''}" onclick="trainPickJob('${jsq(x.id)}')"><b><span class="trn-mk" aria-hidden="true">${mark(x)}</span>${esc(x.name)}</b>
        <span class="mut">${esc(x.state==='running'?x.phase:x.state)} · ${esc(trainShort(x.base))}</span></button>`).join('')}</div>
    <div class="trn-detail">${j?trainJobHTML(j):'<div class="mut">loading…</div>'}</div></div>`;
}
function trainJobHTML(j){
  const pct=j.total?Math.round(100*j.step/j.total):0,m=j.metrics||{},curve=j.curve||[];
  const ev=j.eval||{},lossNow=curve.length?curve[curve.length-1].loss:null;
  const tile=(k,v,s)=>`<div class="trn-tile"><span>${k}</span><b>${v}</b>${s?`<small>${s}</small>`:''}</div>`;
  const on=j.device==='cpu'?'the processor':j.device==='mps'?'the Apple GPU':'the GPU';
  return `<div class="trn-row"><div class="grow"><h2 class="trn-jt">${esc(j.name)}</h2>
      <div class="mut">${esc(j.base)}${j.device?' · on '+on:''}</div></div>
      ${j.state==='running'?`<button class="endbtn" onclick="trainDo('stop',()=>trainApi('/api/train/jobs/${jsq(j.id)}/stop','POST',{}))">Stop</button>`
        :`${j.state==='done'?`<button class="pact" onclick="trainOpenModel('${jsq(j.id)}')">Open the model</button>`:''}
          <button class="endbtn" onclick="trainDelJob('${jsq(j.id)}')">Remove</button>`}</div>
    ${j.state==='running'?`<div class="trn-prog"><div class="bar"><i style="width:${pct||3}%"></i></div><span class="mut">${esc(j.phase)}${j.total?` · ${j.step} of ${j.total}`:''}</span></div>`:''}
    ${j.state==='failed'?`<div class="errmsg">${esc(j.error||'It failed. The log says why.')}</div>`:''}
    ${j.state==='stopped'?'<div class="mut">Stopped.</div>':''}
    <div class="trn-tiles">${tile('Learned from',j.rows|0,'examples')}${tile('Held back',j.held|0,'never trained on')}
      ${tile('Loss',lossNow==null?'–':lossNow<.01?lossNow.toFixed(3):lossNow.toFixed(2),curve.length>1?'from '+curve[0].loss.toFixed(2):'')}
      ${tile('Took',m.seconds?(m.seconds>=90?Math.round(m.seconds/60)+' min':Math.round(m.seconds)+' s'):j.state==='running'?'…':'–',m.trainable_params?(100*m.trainable_params/m.params).toFixed(1)+'% of weights trained':'')}</div>
    ${j.verdict?`<div class="trn-result">${trainScore(ev,true)}<div class="trn-rside">${trainWord(j.verdict)}</div></div>
      <div class="mut">${esc(j.verdict.words)}</div>`:''}
    ${trainCurve(curve)}
    ${ev.items?trainExamples(ev.items.slice(0,8)):''}
    <details class="trn-log" ${j.state==='failed'?'open':''}><summary>Log</summary><pre>${esc(TRAIN.logText||'')}</pre></details>`;
}
/* The loss, one series: a thin line, a recessive axis, the first and last value written
   out, a crosshair that reads any point, and the numbers as a table for whoever can't
   use the picture. */
function trainCurve(pts){
  pts=pts.filter(p=>typeof p.loss==='number');
  if(pts.length<2)return '';
  const W=560,H=150,L=38,R=46,T=12,B=22;
  const xs=pts.map(p=>p.step),ys=pts.map(p=>p.loss);
  const x0=Math.min(...xs),x1=Math.max(...xs),y1=Math.max(...ys),y0=Math.min(0,Math.min(...ys));
  const X=s=>L+(W-L-R)*(x1===x0?0:(s-x0)/(x1-x0)),Y=v=>T+(H-T-B)*(1-(y1===y0?0:(v-y0)/(y1-y0)));
  const path=pts.map((p,i)=>(i?'L':'M')+X(p.step).toFixed(1)+' '+Y(p.loss).toFixed(1)).join(' ');
  const f=pts[0],l=pts[pts.length-1];
  return `<figure class="trn-fig"><figcaption>Training loss by step <span class="mut">Lower means the examples were learned. The held-back check says whether the job was.</span></figcaption>
    <div class="trn-chart" data-pts='${esc(JSON.stringify(pts.map(p=>[p.step,+p.loss.toFixed(4)])))}' data-geo='${JSON.stringify({W,H,L,R,T,B,x0,x1,y0,y1})}'>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Training loss fell from ${f.loss.toFixed(2)} at step ${f.step} to ${l.loss.toFixed(2)} at step ${l.step}">
      <line class="ax" x1="${L}" y1="${H-B}" x2="${W-R}" y2="${H-B}"/>
      <line class="gr" x1="${L}" y1="${Y(y1)}" x2="${W-R}" y2="${Y(y1)}"/>
      <text class="tk" x="${L-6}" y="${Y(y1)+4}" text-anchor="end">${y1.toFixed(1)}</text>
      <text class="tk" x="${L-6}" y="${H-B+4}" text-anchor="end">${y0.toFixed(0)}</text>
      <text class="tk" x="${L}" y="${H-6}">step ${x0}</text><text class="tk" x="${W-R}" y="${H-6}" text-anchor="end">${x1}</text>
      <path class="ln" d="${path}"/>
      <circle class="dot" cx="${X(l.step)}" cy="${Y(l.loss)}" r="4"/>
      <text class="lb" x="${X(l.step)+8}" y="${Y(l.loss)+4}">${l.loss.toFixed(2)}</text>
      <line class="cross" x1="0" x2="0" y1="${T}" y2="${H-B}" visibility="hidden"/><circle class="hov" r="4" visibility="hidden"/>
    </svg><div class="trn-tip" hidden></div></div>
    <details class="trn-tbl"><summary>The numbers</summary><div class="trn-tw"><table class="trn-t"><thead><tr><th>Step</th><th>Loss</th></tr></thead><tbody>
      ${pts.map(p=>`<tr><td>${p.step}</td><td>${p.loss.toFixed(4)}</td></tr>`).join('')}</tbody></table></div></details></figure>`;
}
function trainCurveWire(){
  const box=(trainBody()||document).querySelector('.trn-chart');if(!box)return;
  const pts=JSON.parse(box.dataset.pts),g=JSON.parse(box.dataset.geo),svg=box.querySelector('svg');
  const cross=svg.querySelector('.cross'),hov=svg.querySelector('.hov'),tip=box.querySelector('.trn-tip');
  const X=s=>g.L+(g.W-g.L-g.R)*(g.x1===g.x0?0:(s-g.x0)/(g.x1-g.x0)),Y=v=>g.T+(g.H-g.T-g.B)*(1-(g.y1===g.y0?0:(v-g.y0)/(g.y1-g.y0)));
  const show=i=>{const p=pts[Math.max(0,Math.min(pts.length-1,i))],x=X(p[0]),y=Y(p[1]);
    cross.setAttribute('x1',x);cross.setAttribute('x2',x);cross.setAttribute('visibility','visible');
    hov.setAttribute('cx',x);hov.setAttribute('cy',y);hov.setAttribute('visibility','visible');
    tip.hidden=false;tip.textContent='step '+p[0]+' · loss '+p[1];
    const r=svg.getBoundingClientRect();tip.style.left=Math.min(r.width-110,Math.max(0,x/g.W*r.width+8))+'px';tip.style.top=Math.max(0,y/g.H*r.height-28)+'px';box._i=i};
  const hide=()=>{cross.setAttribute('visibility','hidden');hov.setAttribute('visibility','hidden');tip.hidden=true};
  const near=cx=>{const r=svg.getBoundingClientRect(),sx=(cx-r.left)/r.width*g.W;let b=0,bd=1e9;pts.forEach((p,i)=>{const dd=Math.abs(X(p[0])-sx);if(dd<bd){bd=dd;b=i}});return b};
  svg.onpointermove=e=>show(near(e.clientX));svg.onpointerdown=e=>show(near(e.clientX));svg.onpointerleave=hide;
  svg.tabIndex=0;svg.onkeydown=e=>{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();show(Math.max(0,Math.min(pts.length-1,(box._i==null?pts.length-1:box._i)+(e.key==='ArrowRight'?1:-1))))}else if(e.key==='Escape')hide()};
  svg.onblur=hide;
}
async function trainJobLoad(){
  const list=((TRAIN.d||{}).jobs_list)||[];
  if(!TRAIN.job&&list.length)TRAIN.job=list[0].id;      /* the newest, when none was picked */
  if(!TRAIN.job)return;
  try{
    const j=await trainApi('/api/train/jobs/'+TRAIN.job+'?offset='+(TRAIN.logOff|0));
    TRAIN.logText=(TRAIN.logText+((j.log||{}).content||'')).slice(-20000);TRAIN.logOff=(j.log||{}).offset||0;TRAIN.jobd=j;
  }catch(e){TRAIN.jobd=null;TRAIN.job=null}
}
async function trainPickJob(id){TRAIN.job=id;TRAIN.logOff=0;TRAIN.logText='';TRAIN.jobd=null;await trainJobLoad();trainPaint()}
async function trainDelJob(id){
  if(!await osConfirm('Remove this run?','Its log and held-back examples go. The model it made stays.',{confirmText:'Remove'}))return;
  await trainDo('del',async()=>{await trainApi('/api/train/jobs/'+id,'DELETE');TRAIN.job=null;TRAIN.jobd=null});
}
function trainExamples(items){
  return `<h3 class="trn-sec">Held-back examples <span class="mut">it never trained on these</span></h3>
    <div class="trn-tw"><table class="trn-t trn-ex"><thead><tr><th>Prompt</th><th>Wanted</th><th>Base model</th><th>Yours</th></tr></thead><tbody>
    ${items.map(i=>`<tr><td data-l="Prompt">${esc(i.prompt)}</td><td data-l="Wanted">${esc(i.want)}</td><td data-l="Base model" class="was">${esc(i.before)}</td>
      <td data-l="Yours"><div class="trn-mine"><span class="trn-hit ${i.exact_after?'y':''}" aria-label="${i.exact_after?'matches':'differs'}">${i.exact_after?'✓':'·'}</span><span>${esc(i.after)}</span></div></td></tr>`).join('')}
    </tbody></table></div>`;
}

/* ---- Models ---- */
function trainModels(d){
  const list=d.models_list||[];
  let h='';
  if(!list.length)h+='<div class="trn-empty">'+trnIc('models')+'<span>No models yet. A finished run puts one here.</span></div>';
  h+=`<div class="trn-mgrid">`+list.map(m=>{
    const open=TRAIN.model&&TRAIN.model.id===m.id;
    return `<article class="trn-card trn-model${open?' open':''}">
      <header><div class="grow"><button class="trn-name" onclick="trainOpenModel('${jsq(m.id)}')" aria-expanded="${open?'true':'false'}">${esc(m.name)}</button>
        <div class="mut">${esc(trainShort(m.base))} · ${trainMB(m.bytes)} · ${esc(trainAgo(m.created))}</div></div>${trainWord(m.verdict)}</header>
      ${trainScore(m.eval)}
      ${m.ollama?`<div class="trn-where">${trnIc('check')}In Ollama as <b>${esc(m.ollama)}</b></div>`:''}
      ${m.published?`<div class="trn-where">${trnIc('check')}Published as <b>${esc(m.published)}</b></div>`:''}
      ${open?trainModelOpen(TRAIN.model,d):`<button class="endbtn trn-openbtn" onclick="trainOpenModel('${jsq(m.id)}')">Try it, use it</button>`}</article>`}).join('')+'</div>';
  h+=`<div class="trn-card trn-token"><h2 class="trn-h">Hugging Face token</h2>
    <div class="mut">${d.token?'A token is saved in your vault.':'Only needed to publish a model, or to import a private or gated dataset.'}${pInfo('Kept in your vault on this machine. It is handed to the one upload that needs it and never shown again.')}</div>
    <div class="trn-row">${secretField('trn-tok',d.token?'Replace it':'hf_…')}<button class="endbtn" onclick="trainToken()">Save</button>
      ${d.token?`<button class="endbtn" onclick="trainToken(true)">Remove</button>`:''}</div></div>`;
  return h;
}
function trainModelOpen(m,d){
  const t=TRAIN.tried&&TRAIN.tried.id===m.id?TRAIN.tried:null;
  const noOllama=!d.ollama?'Ollama is not installed on this machine.':!d.admin?'Adding a model to Ollama is an admin\'s: every account can then choose it.':'';
  return `<div class="trn-open">
    <div class="mut">${esc((m.verdict||{}).words||'')}</div>
    ${m.system?`<div class="trn-sys"><span>It works under</span>${esc(m.system)}</div>`:''}
    <div class="trn-try"><label class="trn-vh" for="trn-try">Try it</label>
      <textarea id="trn-try" data-keep rows="2" placeholder="Give it something to answer"></textarea>
      <button class="pact" ${TRAIN.busy?'disabled':''} onclick="trainTry('${jsq(m.id)}')">${TRAIN.busy==='try'?'Thinking…':'Ask'}</button></div>
    ${t?`<div class="trn-ans"><div class="mut">${esc(t.prompt)}</div><div>${esc(t.answer)}</div><div class="mut">${t.seconds} s on ${esc(t.device==='cpu'?'the processor':t.device)}, after loading.</div></div>`:''}
    <div class="trn-row trn-acts">
      <button class="pact" ${noOllama||TRAIN.busy?'disabled':''} onclick="trainOllama('${jsq(m.id)}','${jsq(m.ollama_name||'')}')">${m.ollama?'Add to Ollama again':'Add to Ollama'}</button>
      <button class="endbtn" ${d.token&&!TRAIN.busy?'':'disabled'} onclick="trainPublish('${jsq(m.id)}','${jsq(m.name)}')">Publish…</button>
      <span class="sp"></span><button class="endbtn" onclick="trainDelModel('${jsq(m.id)}')">Delete</button></div>
    ${noOllama?`<div class="mut">${esc(noOllama)}</div>`:`<div class="mut">Then it can be this machine's brain, or one agent's.${pInfo('Ollama converts the weights itself. It imports the common small architectures; when it can\'t take one, it says so and you see what it said.')}</div>`}
    ${!d.token?'<div class="mut">Publishing needs your Hugging Face token, below.</div>':''}
    ${(m.examples||[]).length?trainExamples(m.examples.slice(0,12)):''}</div>`;
}
async function trainOpenModel(id){
  TRAIN.tab='models';
  if(TRAIN.model&&TRAIN.model.id===id&&trainBody()&&trainBody().querySelector('.trn-model .trn-open')){TRAIN.model=null;return trainPaint()}
  try{TRAIN.model=await trainApi('/api/train/models/'+id)}catch(e){toast(e.message,{kind:'err'})}
  trainPaint();
}
async function trainTry(id){
  const p=($('#trn-try')||{}).value||'';if(!p.trim())return;
  await trainDo('try',async()=>{const r=await trainApi('/api/train/models/'+id+'/try','POST',{prompts:[p]});
    const a=(r.answers||[])[0]||{};TRAIN.tried={id,prompt:a.prompt,answer:a.answer,seconds:r.seconds,device:r.device}});
}
async function trainOllama(id,name){
  if(!await osConfirm('Add this model to Ollama?',`Ollama converts the weights and keeps a copy as ${name}. Every account on this machine can then choose it. It can take a few minutes.`,{confirmText:'Add it'}))return;
  await trainDo('ollama',async()=>{const m=await trainApi('/api/train/models/'+id+'/ollama','POST',{});toast('✓ In Ollama as '+m.ollama);
    if(TRAIN.model&&TRAIN.model.id===id)TRAIN.model.ollama=m.ollama});
}
async function trainPublish(id,name){
  const repo=await osPrompt('Publish “'+name+'” to the Hugging Face Hub',{message:'The repository, as your-name/model-name. It is uploaded private; you can make it public on the Hub.',placeholder:'your-name/model-name',confirmText:'Next'});
  if(!repo)return;
  if(!await osConfirm('Upload it to '+repo.trim()+'?','The model leaves this machine. Its examples may have come from your own data, and a model can repeat what it was trained on.',{confirmText:'Upload'}))return;
  await trainDo('publish',async()=>{const m=await trainApi('/api/train/models/'+id+'/publish','POST',{repo:repo.trim(),private:true});toast('✓ Published as '+m.published)});
}
async function trainDelModel(id){
  if(!await osConfirm('Delete this model?','Its weights are removed from this machine. A copy already in Ollama or on the Hub stays there.',{confirmText:'Delete'}))return;
  await trainDo('del',async()=>{await trainApi('/api/train/models/'+id,'DELETE');TRAIN.model=null});
}
async function trainToken(remove){
  const v=remove?'':(($('#trn-tok')||{}).value||'').trim();
  if(!remove&&!v)return;
  await trainDo('token',async()=>{await trainApi('/api/train/token','PUT',{token:v});toast(remove?'Removed.':'Saved in your vault.')});
}
