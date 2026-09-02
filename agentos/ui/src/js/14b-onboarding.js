/* ================= onboarding: the arc, not the form =================
   One screen, eight steps, and every step ends with something real existing on
   this machine. The rule that shapes the whole file: a step is ticked because the
   server can SEE the thing, never because this page remembers clicking it — so
   reload mid-way and you are exactly where you were, and "run setup again" on day
   300 opens with most of it already green.

   It is the same component in both places. There is no first-run version and
   settings version to drift apart; Settings → "Run setup again" opens this.

   THE ARC HAS TWO HOMES AND ONE IMPLEMENTATION.
   It is a full-screen overlay on first run, and the **Setup app** the rest of the
   time — same catalogue, same probe, same panes, same wiring. A "tour mode" that
   only *showed* you the steps would be a second implementation to drift, and the
   one that drifted would be whichever nobody was demoing; so the app is the real
   thing, and it is safe to open because re-running setup is safe by design (it
   creates, it never wipes, and a step already satisfied is already ticked).

   Only ONE arc is alive at a time. Every pane wires itself by element id, so two
   hosts on screen would mean two `#ob-name-go` buttons and a coin toss over which
   one your click reached. `obHost()` enforces that rather than leaving it to
   whoever opens the second one.

   `var`, not `let` — concatenated bundle, and 14-docs-setup calls into it. */
var OB={state:null,open:'',busy:false,done:null,host:null};

/* State is state only if it HAS STEPS. A server older than these routes answers
   404 with a JSON body, `{"detail":"Not Found"}` parses fine and is truthy, so the
   old `if(!OB.state)` guard passed and `S.steps.map` threw halfway through building
   the rail — leaving the rail and the pane both empty. A black window with no
   sentence in it, for the one screen whose whole job is telling you what to do
   next. Check the status and the shape, not just that something came back. */
async function obLoad(){
  try{
    const r=await fetch('/api/onboarding');
    const d=r.ok?await r.json():null;
    OB.state=(d&&Array.isArray(d.steps)&&d.steps.length)?d:null;
  }catch(e){OB.state=null}
  return OB.state;
}
/* One sentence, both homes. The overwhelmingly likely cause is an AgentOS that was
   updated while it was running, so say the thing that fixes it rather than "the
   server did not answer". */
function obUnavailableHTML(){
  return '<p class="mut" style="padding:16px">Setup is unavailable — this server '
    +'has no step list to show. If AgentOS was updated while it was running, '
    +'restart it and open Setup again.</p>';
}
function obStep(id){return ((OB.state||{}).steps||[]).find(s=>s.id===id)}

/* ---------- the shell ---------- */

function obCloseApp(){
  if(typeof winsOf==='function')winsOf('setup').forEach(w=>closeWin(w));
}

/* Claim the arc for one host, tearing down whichever had it. Returns the element
   that now contains the rail and the pane. */
function obHost(el,opts){
  opts=opts||{};
  if(OB.host&&OB.host!==el){
    const ov=$('#ob-wiz');
    if(ov&&(ov===OB.host||ov.contains(OB.host)))ov.remove();     // the overlay had it
    else if(opts.fromOverlay)obCloseApp();
  }
  el.innerHTML='<div class="ob-stage"><div class="ob-rail" id="ob-rail"></div>'
    +'<div class="ob-pane" id="ob-pane"></div></div>';
  OB.host=el;
  return el;
}

async function obShow(opts){
  opts=opts||{};
  await obLoad();
  let ov=$('#ob-wiz');
  if(!ov){
    ov=document.createElement('div');ov.id='ob-wiz';ov.className='wiz ob';
    document.body.appendChild(ov);
    Motion.run(ov,[{opacity:0},{opacity:1}],{duration:240,easing:EASE.out});
  }
  // Returning here used to leave "Run setup again" as a button that did nothing
  // visible at all — the overlay is built first so there is something to say it in,
  // and a way back out of it.
  if(!OB.state){
    ov.innerHTML='<div class="ob-stage"><div class="ob-pane">'+obUnavailableHTML()
      +'<button class="ob-leave" id="ob-leave">Close</button></div></div>';
    OB.host=ov;
    ov.querySelector('#ob-leave').onclick=obClose;
    return;
  }
  obHost(ov,{fromOverlay:true});
  OB.done=opts.onDone||obClose;
  OB.open=opts.step||OB.state.next||(OB.state.steps[0]||{}).id;
  obRender();
}
function obClose(){
  const ov=$('#ob-wiz');if(!ov)return;
  if(OB.host===ov)OB.host=null;
  Motion.run(ov,[{opacity:1},{opacity:0}],{duration:200,easing:EASE.in})
    .finished.then(()=>ov.remove());
}

/* ---------- the same arc, as an app ----------
   A window rather than a takeover, because this is the version you open to look
   at what setup does — including on a machine that finished setup months ago. The
   only differences are the frame it sits in and the last button on the rail, which
   closes a window instead of dismissing a wizard. */
async function renderSetup(body,w){
  body.innerHTML='<div class="dim" style="padding:var(--sp-4)">…</div>';
  await obLoad();
  if(!OB.state){body.innerHTML=obUnavailableHTML();return}
  body.classList.add('ob-inwin');
  obHost(body);
  // Two columns at 500px are two unreadable columns. Watched rather than measured
  // once, because a window is resized and a container query would need
  // `container-type` on every `.wbody` in the OS to work here.
  const fit=()=>body.classList.toggle('narrow',body.clientWidth<700);
  fit();
  if(w&&window.ResizeObserver){
    w._obRO=new ResizeObserver(fit);w._obRO.observe(body);
  }
  OB.done=obCloseApp;
  OB.open=OB.open||OB.state.next||(OB.state.steps[0]||{}).id;
  obRender();
}

function obRender(){
  const host=OB.host||document;
  const rail=host.querySelector?host.querySelector('.ob-rail'):$('#ob-rail');
  const pane=host.querySelector?host.querySelector('.ob-pane'):$('#ob-pane');
  if(!rail||!pane)return;
  const S=OB.state,agent=(typeof agentName==='function'&&agentName())||'your agent',
        inWin=!!(OB.host&&OB.host.classList&&OB.host.classList.contains('ob-inwin'));
  rail.innerHTML=`<div class="ob-head">
      <div class="ob-mark">▲</div>
      <b>Set up ${esc(agent)}</b>
      <span>${S.done} of ${S.total} done</span>
      <div class="ob-bar"><i style="width:${Math.round(S.done/S.total*100)}%"></i></div>
    </div>
    ${/* A blocked step is dimmed, not disabled: the row still opens, and the pane
          says what it needs and where. `disabled` answered a tap with nothing —
          on a phone, indistinguishable from the OS being broken. */''}
    ${S.steps.map(s=>`<button class="ob-item ${s.status}${s.blocked.length?' blocked':''}${s.id===OB.open?' on':''}"
        data-step="${esc(s.id)}">
      <span class="ob-tick">${s.status==='done'?'✓':s.status==='skipped'?'–':esc(s.icon)}</span>
      <span class="ob-t">${esc(s.title)}
        ${s.detail?`<em>${esc(s.detail)}</em>`
          :s.blocked.length?`<em>needs ${esc(s.blocked.join(', '))}</em>`:''}</span>
    </button>`).join('')}
    ${inWin
      ? `<button class="ob-leave" id="ob-full">Open it full screen</button>
         <button class="ob-leave" id="ob-leave">Close</button>`
      : `<button class="ob-leave" id="ob-leave">${
           S.finished?'Done — take me in →':'Finish later'}</button>`}`;
  rail.querySelectorAll('.ob-item').forEach(b=>b.onclick=()=>{OB.open=b.dataset.step;obRender()});
  /* Closing a WINDOW is not "I have finished setting this machine up". Marking it
     complete here would mean somebody who opened the app to look around, on a
     machine still half configured, silently never saw the first-run screen again. */
  rail.querySelector('#ob-leave').onclick=()=>{
    if(!inWin)markSetupComplete();
    OB.done();
  };
  const full=rail.querySelector('#ob-full');
  if(full)full.onclick=()=>{obCloseApp();obShow({step:OB.open})};
  obPane(pane,obStep(OB.open)||S.steps[0]);
}

/* Each pane is: what this is → what it will produce → the control → skip. The
   "produces" line is load-bearing, not decoration: it is the difference between
   asking somebody to fill in a field and telling them what they are about to get. */
function obPane(pane,s){
  if(!s)return;
  const blocked=(s.blocked||[]).length?s.blocked:null;
  const needs=blocked?`<div class="ob-needs">This step needs ${blocked.map(id=>{
        const st=obStep(id);return `<b>${esc(st?st.title.toLowerCase():id)}</b>`}).join(' and ')} first.
      ${blocked.map(id=>{const st=obStep(id);return st
        ?`<button data-go="${esc(id)}">${esc(st.title)} →</button>`:''}).join('')}</div>`:'';
  const body=blocked?needs
    :OB_PANES[s.id]?OB_PANES[s.id](s):'<p class="mut">Nothing to do here.</p>';
  pane.innerHTML=`<div class="ob-step" data-step="${esc(s.id)}">
    <div class="ob-kicker">${esc(s.icon)} ${esc(s.title)}</div>
    <p class="ob-blurb">${esc(s.blurb)}</p>
    <div class="ob-produces">You will end up with: <b>${esc(s.produces)}</b></div>
    <div class="ob-body">${body}</div>
    <div class="ob-foot">
      ${s.optional?`<button class="wiz-back" id="ob-skip">${
        s.status==='skipped'?'Skipped — do it after all':'Skip this'}</button>`:''}
      ${s.panel?`<button class="wiz-back" id="ob-panel">Open it in Settings instead</button>`:''}
      <span class="ob-msg" id="ob-msg"></span>
    </div></div>`;
  Motion.run(pane.firstElementChild,
    [{opacity:0,transform:'translateY(12px)'},{opacity:1,transform:'none'}],
    {duration:240,easing:EASE.out});
  pane.querySelectorAll('.ob-needs button[data-go]').forEach(b=>b.onclick=()=>{OB.open=b.dataset.go;obRender()});
  if(blocked)return;             // nothing below is wired for a step that cannot run yet
  const sk=$('#ob-skip');
  if(sk)sk.onclick=()=>obSkip(s.id,s.status==='skipped');
  const pn=$('#ob-panel');
  // Most steps live in a Settings tab; accounts have an app of their own. Both are
  // "where this lives afterwards", which is the promise the button makes.
  // Borrowed, not abandoned: the arc closes so the panel has the screen, and the
  // window carries the step it came from so closing it brings the arc back —
  // re-probed, so a token pasted over there returns with the step already ticked.
  // Without it this was a one-way door onto a desktop, with nothing saying eight
  // steps were still waiting or which one you had been on.
  if(pn)pn.onclick=()=>{
    const from=s.id;
    obClose();
    const w=APPS[s.panel]
      ? openApp(s.panel)
      : (SETTAB=s.panel, localStorage.setItem('settab',s.panel), openApp('settings'));
    if(w)w._backToSetup=from;
  };
  if(OB_WIRE[s.id])OB_WIRE[s.id](s);
}

function obMsg(text,cls){
  const el=$('#ob-msg');if(!el)return;
  el.textContent=text||'';el.className='ob-msg '+(cls||'');
}
async function obSkip(id,undo){
  const r=await fetch('/api/onboarding/skip',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({step:id,undo:!!undo})});
  const d=await r.json();
  if(d.error)return obMsg(d.error,'warn');
  OB.state=d;
  const nx=OB.state.next;
  OB.open=undo?id:(nx||id);
  obRender();
}
/* After anything that changes the machine: re-probe rather than assume. The whole
   point of the design is that the server decides what is done. */
async function obRefresh(advance){
  await obLoad();
  if(advance&&OB.state.next)OB.open=OB.state.next;
  obRender();
}

/* ---------- the panes ---------- */
var OB_PANES={
  name:()=>`<label class="job-q"><span>What should it be called?</span>
      <input id="ob-name" value="${esc((typeof cfg!=='undefined'&&cfg.agent_name)||'Aria')}"
        spellcheck="false" autocomplete="off">
      <em>It answers to this, signs its work with it, and it is what the menu bar says.</em>
    </label>
    <div class="job-go"><button class="wiz-next" id="ob-name-go">Save the name</button></div>`,

  model:s=>`<div id="ob-model-box"><p class="mut">Reading what this machine can run…</p></div>`,

  /* The box is EMPTY, with the fallback question as its placeholder. Two reasons:
     the step's promise is one click to a real reply, so it must still work untouched
     — an empty box sends nothing and the server asks its own question; and the
     question then lives in exactly one place (the route), instead of a copy here
     that drifts from the one non-browser callers get. */
  hello:s=>`<p class="mut">One question, answered by your model, through the whole
      agent — provider, key, model name and the tool loop. A green tick from an API
      would prove none of that.</p>
    <label class="job-q" style="margin-top:10px"><span>Ask it anything</span>
      <textarea id="ob-hello-q" rows="2" spellcheck="false"
        placeholder="In two sentences: what can you do on this machine that a chat website cannot?"
        style="width:100%;resize:vertical"></textarea>
      <em>Leave it empty and it answers the question above.</em></label>
    <div class="job-go"><button class="wiz-next" id="ob-hello-go">Ask it something</button></div>
    <div class="ob-reply" id="ob-reply"></div>`,

  /* The viral entry point: the person who arrived holding a link to somebody's
     shared agent should not have to discover Settings → Agent to use it. Preview
     and fork call the same routes as that pane, and the arrival card is the same
     agsArrivalHTML — one computation, one experience, two doors. */
  fork:s=>`<p class="mut">A shared agent is one file — its skills, teammates, flows
      and chosen apps, with no data and no credentials in it. You read exactly what
      it contains first; the fork writes <b>zero</b> permissions and everything
      lands disabled.</p>
    <div class="prow" style="margin-top:10px">
      <input id="ob-fork-src" placeholder="owner/repo · https://… · bento.agent.json URL" autocomplete="off" class="ags-grow">
      <input id="ob-fork-key" placeholder="peer key (hosted shares only)" autocomplete="off" class="ags-key">
    </div>
    <div class="job-go"><button class="wiz-next" id="ob-fork-read">Read it first</button>
      <label class="wiz-back" style="cursor:pointer">from a file<input type="file" accept=".json"
        style="display:none" id="ob-fork-file"></label></div>
    <div id="ob-fork-out"></div>`,

  /* Three suggestions, not a free text box with no floor. "Describe an app" in front
     of somebody who has never seen this OS build one is a blank page; a sentence they
     can press is a demonstration. The box is still there, seeded from whichever chip
     they pick, because the thing being taught is that a sentence is the input. */
  app:s=>`<p class="mut">Describe a small tool and the agent writes it — HTML, CSS and
      JavaScript — then puts it on your desktop. It is the same builder you will use
      later; this is just the first one.</p>
    <div class="job-ways" id="ob-app-picks">
      ${OB_APP_IDEAS.map((a,i)=>`<label class="job-way">
        <input type="radio" name="ob-app" value="${i}" ${i?'':'checked'}>
        <b>${esc(a.title)}</b><em>${esc(a.blurb)}</em></label>`).join('')}
    </div>
    <label class="job-q" style="margin-top:10px"><span>What should it do?</span>
      <textarea id="ob-app-prompt" rows="2" spellcheck="false"></textarea>
      <em>Edit it, or write your own — a sentence is enough.</em></label>
    <div class="job-go"><button class="wiz-next" id="ob-app-go">Build it</button></div>`,

  agent:s=>`<p class="mut">A specialist is a persona plus a short list of tools. It is
      what flows delegate to, and what <code>@name</code> reaches in any chat.</p>
    <div class="ob-card">
      <b>researcher-plus</b>
      <span>Gathers real information, verifies it against a second source, returns a
        dense sourced summary — and says plainly when it could not find something.</span>
      <span class="mut">fetch_url · read_file · list_dir · recall · kg_query · save_report</span>
    </div>
    <div class="job-go"><button class="wiz-next" id="ob-agent-go">Create this agent</button>
      <button class="endbtn" id="ob-agent-studio">Design my own instead</button></div>`,

  flow:s=>`<p class="mut">A flow is a mission and a roster. You do not draw the steps —
      the orchestrator picks who does what while it runs, inside the permissions the
      flow declares.</p>
    <div class="ob-card">
      <b>first-flow</b>
      <span>Research a topic properly and write it down, sourced, as a saved report.</span>
      <span class="mut">rostered with the agent you just made · may fetch pages and save a report</span>
    </div>
    <div class="job-go"><button class="wiz-next" id="ob-flow-go">Create the flow</button>
      <button class="endbtn" id="ob-flow-run">Create it and run it now</button></div>
    <div class="ob-reply" id="ob-reply"></div>`,

  schedule:s=>`<p class="mut">Pick something for this machine to do without being asked.
      These are the same job recipes as the Jobs app — one catalogue, so what you set
      up here is editable there.</p>
    <div id="ob-jobs"><p class="mut">Reading the recipes…</p></div>`,

  channel:s=>`<p class="mut">Same conversation, same memory, same approval prompts —
      on your phone. Pick one; you can add the other later.</p>
    <div class="ob-cards">
      <button class="job-card" id="ob-ch-tg"><span class="job-mark">✈</span>
        <b>Telegram</b><span class="job-blurb">A bot from @BotFather, one token to paste.
          Official and reliable — the right answer for anything unattended.</span></button>
      <button class="job-card" id="ob-ch-wa"><span class="job-mark">◐</span>
        <b>WhatsApp</b><span class="job-blurb">Scan a QR and this machine becomes a linked
          device. Nothing to register. Unofficial — it says so before anything installs.</span></button>
    </div>`,

  look:s=>`<p class="mut">The parts that make it feel like your machine rather than a
      demo. All of it is changeable later in Settings → Appearance.</p>
    <div id="ob-look"><p class="mut">Reading the themes…</p></div>`,

  /* Deliberately the last step. Everything above is somebody setting this machine
     up, and the first account inherits all of it — so the honest order is "make it
     work, then say who it belongs to", not the other way round. */
  account:s=>`<div id="ob-acct"><p class="mut">Reading the accounts…</p></div>`,
};

/* The cloud providers this step offers, in the order somebody scanning the list
   would want them. `id` must match a key in cfg.providers — that string is what
   `providers.chat()` dispatches on, so a typo here is a model that saves and then
   cannot answer.

   `model` is a real default rather than a placeholder: "needs an API key" is
   already asking somebody to leave and come back with one, and asking them to also
   know the exact model string is where this step was being abandoned. They can
   still overwrite it. `where` is the page the key comes from, because that is the
   next thing they have to find and every one of these is a different domain. */
/* Deliberately small, offline and useful on day one. Nothing here needs an API key,
   a scraped site or a service to be signed into — a first build that fails because
   the weather API wanted a key teaches the opposite of the intended lesson. */
var OB_APP_IDEAS=[
  {title:'A scratchpad that remembers',
   blurb:'Notes that survive a reload, with a word count',
   prompt:'A simple notes app: one big text area that saves what I type and reloads '
     +'it next time, with a word and character count under it.'},
  {title:'A countdown timer',
   blurb:'Set minutes, watch it run, hear it finish',
   prompt:'A countdown timer: I set the minutes, press start, and it counts down in '
     +'big digits and makes a sound when it reaches zero.'},
  {title:'A colour picker for my theme',
   blurb:'Pick a colour, copy the hex',
   prompt:'A colour tool: a picker, the hex and RGB values shown large, a button to '
     +'copy the hex, and a row of the last few colours I picked.'},
];

var OB_CLOUD=[
  {id:'anthropic',label:'Anthropic (Claude)',model:'claude-sonnet-5',
   where:'console.anthropic.com'},
  {id:'google',label:'Google (Gemini)',model:'gemini-2.5-flash',
   where:'aistudio.google.com'},
  {id:'openai',label:'OpenAI',model:'gpt-4o',where:'platform.openai.com'},
  {id:'deepseek',label:'DeepSeek',model:'deepseek-chat',where:'platform.deepseek.com'},
  {id:'moonshot',label:'Moonshot (Kimi)',model:'kimi-k2-0711-preview',
   where:'platform.moonshot.ai'},
  {id:'openrouter',label:'OpenRouter — many models, one key',
   model:'anthropic/claude-sonnet-4.5',where:'openrouter.ai/keys'},
];

/* ---------- the wiring ---------- */
var OB_WIRE={
  name(){
    const go=$('#ob-name-go'),inp=$('#ob-name');
    const save=async()=>{
      const v=(inp.value||'').trim();
      if(!v)return obMsg('it needs a name','warn');
      obMsg('saving…');
      await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({agent_name:v})});
      // Pressing Save IS the decision, including when the answer is the name it came
      // with. The server cannot see that in the config — "Aria" saved deliberately
      // and "Aria" never touched are the same two bytes — so say it happened. Without
      // this the step stayed todo and the arc sat still, and the only way forward was
      // to dislike the default.
      await fetch('/api/onboarding/confirm',{method:'POST',
        headers:{'Content-Type':'application/json'},body:JSON.stringify({step:'name'})});
      await loadConfig();
      obMsg('saved','ok');
      obRefresh(true);
    };
    go.onclick=save;
    inp.onkeydown=e=>{if(e.key==='Enter')save()};
    inp.focus();inp.select();
  },

  fork(){
    const out=$('#ob-fork-out');
    /* The refresh after a fork re-renders this pane (that is what ticks the
       rail), so the arrival card must be re-drawn from state or it flashes for
       a frame and vanishes — which is exactly what it did first. */
    if(OB.forkArrival){
      out.innerHTML=agsArrivalHTML(OB.forkArrival);
      const btn=[...out.querySelectorAll('button')].find(x=>x.textContent.includes('Test it'));
      if(btn){const orig=btn.onclick;btn.onclick=()=>{obClose();if(orig)orig.call(btn)}}
    }
    let bundle=null;                       // set when the source is a local file
    const read=async(b)=>{
      const src=($('#ob-fork-src')||{}).value.trim(),
            key=($('#ob-fork-key')||{}).value.trim();
      if(!b&&!src)return obMsg('where is it? a link, owner/repo, or a file','warn');
      out.innerHTML='<p class="mut">reading it…</p>';obMsg('');
      let d=null;
      try{d=await (await fetch('/api/agent/fork/preview',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(b?{bundle:b}:{source:src,key})})).json()}catch(e){}
      if(!d){out.innerHTML='<p class="mut">could not read it</p>';return}
      if(d.error){out.innerHTML=`<div class="ghint" style="border-color:var(--err)">${esc(d.error)}</div>`;return}
      bundle=b||null;
      const bad=d.verify.status==='checksum-mismatch'||d.verify.status==='bad-signature';
      const items=d.items.map(i=>`<div class="sub ${i.skipped?'mut':''}">· ${esc(i.kind)}: <b>${esc(i.name)}</b>${i.skipped?' — exists here, skipped':''}</div>`).join('');
      out.innerHTML=`<div class="ghint"><b>${esc(d.name)}</b>${d.description?` — ${esc(d.description)}`:''}
        <div class="sub">integrity: ${esc(d.verify.status)} · provenance: ${esc(d.tofu.status)} · app scan: ${esc(d.security.verdict)}</div>
        <div style="margin-top:6px">${items}</div>
        <div class="sub" style="margin-top:6px"><b>Permissions written now: ${d.grants_written_now}.</b>
          Enabling each flow later is what grants${(d.permissions_ceiling||[]).length?` — the ceiling is ${d.permissions_ceiling.length} grant(s), listed in Settings → Agent`:''}.</div>
        ${d.soul_included?'<div class="sub">a soul is included — it is NOT adopted from here; adopt it later in Settings → Agent after reading it</div>':''}
        ${bad?'<div class="sub" style="color:var(--err)">This will not fork: the bytes are not what the sharer shared.</div>'
             :'<div class="job-go" style="margin-top:6px"><button class="wiz-next" id="ob-fork-go">Fork it — disabled, nothing granted</button></div>'}
      </div>`;
      const go=$('#ob-fork-go');
      if(go)go.onclick=async()=>{
        obMsg('forking…');
        let r=null;
        try{r=await (await fetch('/api/agent/fork',{method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify(bundle?{bundle}:{source:src,key})})).json()}catch(e){}
        if(!r||r.error){obMsg((r&&r.error)||'the fork failed','warn');return}
        obMsg('');
        /* The arrival: the same card Settings shows — what changed, what did
           not, and the chat door. Held in OB state, because the refresh that
           ticks the rail re-renders this pane and would erase a card that only
           lived in the DOM. The wizard closes when they take the chat door —
           the point of the test is the machine, not the wizard. */
        OB.forkArrival=r;
        obRefresh(false);
      };
    };
    $('#ob-fork-read').onclick=()=>read(null);
    $('#ob-fork-file').onchange=function(){
      const f=this.files&&this.files[0];if(!f)return;
      const rd=new FileReader();
      rd.onload=()=>{try{read(JSON.parse(rd.result))}catch(e){obMsg('that file is not a bundle','warn')}};
      rd.readAsText(f);
    };
  },

  async model(){
    const box=$('#ob-model-box');if(!box)return;
    let d={};try{d=await (await fetch('/api/setup')).json()}catch(e){}
    // From the same brain list every other surface reads, so "another agent
    // could answer" says the same thing here as in Settings and in Chat.
    await loadBrains();
    const eng={engines:(BRAINS.executors||[]).filter(e=>e.kind==='agent')
      .map(e=>({id:e.id,name:e.name,available:e.available,reason:e.reason,
                detail:e.detail,licence:e.licence,
                install:e.install_cmd?{command:e.install_cmd}:null}))};
    const local=(d.ollama_models||[]);
    /* The third way to have a brain, and until now the only one this step never
       mentioned: another agent already on the machine answers the turns. It
       belongs HERE because "what will answer me" is one question, and finding out
       afterwards that Claude Code was installed all along — from a Settings tab
       nobody had reason to open yet — is the same gap as a capability that is
       silently missing. Not installed is shown too, with the exact command and
       the licence: hidden reads as "this OS cannot". */
    const engines=(eng.engines||[]);
    const engHtml=engines.length?`<div class="job-q"><span>Or let another agent answer</span>
      <div class="job-ways">${engines.map(e=>{
        const off=e.install||{};
        return e.available
          ? `<label class="job-way"><input type="radio" name="ob-model" value="engine:${esc(e.id)}">
               <b>${esc(e.name)}</b><em>installed${e.detail?' · '+esc(e.detail):''}${
                 e.licence?' · '+esc(e.licence):''} — it brings its own model</em></label>`
          : `<label class="job-way is-off"><input type="radio" disabled>
               <b>${esc(e.name)}</b><em>${esc(e.reason||'not installed')}${
                 e.licence?' · '+esc(e.licence):''}</em>${off.command?
                 `<code class="ob-cmd">${esc(off.command)}</code>`:''}</label>`;
      }).join('')}</div></div>`:'';
    // Local first when there are any: it is free, private, and needs no key — the
    // honest default when the machine can already do it.
    box.innerHTML=`
      ${local.length?`<div class="job-q"><span>On this machine</span>
        <div class="job-ways">${local.map(m=>`<label class="job-way">
          <input type="radio" name="ob-model" value="ollama/${esc(m)}">
          <b>${esc(m)}</b><em>local — private, free, no key</em></label>`).join('')}</div></div>`
        :`<div class="wa-hook"><b>Nothing runs locally yet</b>
          <em>Ollama (MIT) would let this machine run models itself — private, free,
            no API key. It downloads a few hundred MB.</em>
          <div class="wa-line"><button class="endbtn" id="ob-ollama">Install Ollama for me</button>
            <small id="ob-ollama-msg" class="mut"></small></div></div>`}
      <div class="job-q"><span>Or bring a cloud model</span>
        <div class="job-ways"><label class="job-way">
          <input type="radio" name="ob-model" value="cloud" ${local.length?'':'checked'}>
          <b>Claude, Gemini, GPT, DeepSeek, Kimi…</b><em>needs an API key</em></label></div></div>
      <div id="ob-cloud" style="display:none">
        <div class="row" style="gap:8px;margin-top:8px">
          <select id="ob-prov">${OB_CLOUD.map(p=>
            `<option value="${esc(p.id)}">${esc(p.label)}</option>`).join('')}</select>
          <input id="ob-key" placeholder="API key" style="flex:1"></div>
        <input id="ob-cmodel" style="width:100%;margin-top:6px">
        <em class="mut" id="ob-prov-hint" style="display:block;margin-top:4px"></em>
      </div>
      ${engHtml}
      <div class="job-go"><button class="wiz-next" id="ob-model-go">Use this model</button></div>`;
    const upd=()=>{const v=(document.querySelector('input[name=ob-model]:checked')||{}).value;
      $('#ob-cloud').style.display=v==='cloud'?'block':'none'};
    box.querySelectorAll('input[name=ob-model]').forEach(r=>r.onchange=upd);upd();
    /* Follow the provider. The model box is only left alone once it has been typed
       in — silently overwriting somebody's model when they change their mind about
       the provider is worse than a stale default. */
    const prov=$('#ob-prov'),cm=$('#ob-cmodel'),hint=$('#ob-prov-hint');
    const provUpd=()=>{
      const p=OB_CLOUD.find(x=>x.id===prov.value)||OB_CLOUD[0];
      if(!cm.dataset.touched)cm.value=p.model;
      cm.placeholder='model, e.g. '+p.model;
      if(hint)hint.textContent='Key from '+p.where;
    };
    cm.oninput=()=>{cm.dataset.touched='1'};
    prov.onchange=provUpd;provUpd();
    const inst=$('#ob-ollama');
    if(inst)inst.onclick=async()=>{
      const m=$('#ob-ollama-msg');inst.disabled=true;
      if(m)m.textContent='downloading — a few hundred MB…';
      try{
        const r=await (await fetch('/api/components/install',{method:'POST',
          headers:{'Content-Type':'application/json'},body:JSON.stringify({id:'ollama'})})).json();
        if(m)m.textContent=r.ok?'installed — pull a model with: ollama pull llama3.2'
          :(r.message||'could not install');
        if(r.ok)OB_WIRE.model();
      }catch(e){if(m)m.textContent='could not reach the server'}
      finally{inst.disabled=false}
    };
    $('#ob-model-go').onclick=async()=>{
      const v=(document.querySelector('input[name=ob-model]:checked')||{}).value||'';
      let body={};
      if(v==='cloud'){
        const p=$('#ob-prov').value,k=($('#ob-key').value||'').trim(),
              m=($('#ob-cmodel').value||'').trim();
        if(!k||!m)return obMsg('a key and a model name, please','warn');
        body={providers:{[p]:{api_key:k}},default_model:p+'/'+m};
      }else if(v.indexOf('engine:')===0){
        /* Choosing an agent is not choosing a model, so it is a different save:
           /api/setup writes the model config, and the engine is what decides who
           runs the turn at all. It also VALIDATES — an executor that vanished
           between the page loading and the click is refused with the reason
           rather than accepted into a machine that then fails on its first turn. */
        obMsg('saving…');
        /* Through /api/brain, like every other brain change: the executor and
           the model it should run on are one write. It also VALIDATES — an
           executor that vanished between the page loading and the click is
           refused with the reason rather than accepted into a machine that then
           fails on its first turn. */
        const eid=v.slice(7);
        const known=(BRAINS.executors||[]).find(x=>x.id===eid);
        const r=await fetch('/api/brain',{method:'PUT',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({executor:eid,model:known?known.model:''})});
        const jd=await r.json().catch(()=>({}));
        if(jd.error)return obMsg(jd.error,'warn');
        await loadConfig();await loadModels();await loadBrains();
        obMsg('saved','ok');return obRefresh(true);
      }else if(v){body={default_model:v}}
      else return obMsg('pick one','warn');
      obMsg('saving…');
      await fetch('/api/setup',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify(body)});
      await loadConfig();await loadModels();
      obMsg('saved','ok');obRefresh(true);
    };
  },

  hello(){
    const ask=async()=>{
      const btn=$('#ob-hello-go'),out=$('#ob-reply'),q=$('#ob-hello-q');
      const text=((q&&q.value)||'').trim();
      btn.disabled=true;btn.textContent='asking…';obMsg('');
      out.innerHTML='<div class="ob-think">thinking…</div>';
      try{
        const r=await fetch('/api/onboarding/hello',{method:'POST',
          headers:{'Content-Type':'application/json'},
          // only when there is one: an empty field must not send `text:""` and
          // become a turn with no question in it
          body:JSON.stringify(text?{text}:{})});
        const d=await r.json();
        if(!r.ok||d.error){
          out.innerHTML='';obMsg(d.error||'it could not answer','warn');return}
        out.innerHTML=`<div class="ob-said"><b>${esc(d.model)}</b>${esc(d.reply)}</div>`;
        obMsg('that came from your model, through the whole agent','ok');
        await obLoad();obRender();
        // keep the reply on screen after the re-render — it is the payoff
        const o=$('#ob-reply');
        if(o)o.innerHTML=`<div class="ob-said"><b>${esc(d.model)}</b>${esc(d.reply)}</div>`;
        // …and the question with it. obRender() rebuilds the pane from scratch, so
        // without this "Ask it again" silently asks something else.
        const q2=$('#ob-hello-q');
        if(q2&&text)q2.value=text;
      }catch(e){out.innerHTML='';obMsg('could not reach the server','warn')}
      finally{btn.disabled=false;btn.textContent='Ask it again'}
    };
    $('#ob-hello-go').onclick=ask;
    const q=$('#ob-hello-q');
    // Enter inside a two-line box should make a new line; ⌘/Ctrl+Enter sends.
    if(q)q.onkeydown=e=>{
      if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){e.preventDefault();ask()}
    };
  },

  agent(){
    $('#ob-agent-go').onclick=async()=>{
      const b=$('#ob-agent-go');b.disabled=true;obMsg('creating…');
      try{
        const d=await (await fetch('/api/onboarding/agent',{method:'POST',
          headers:{'Content-Type':'application/json'},body:JSON.stringify({})})).json();
        if(d.error)return obMsg(d.error,'warn');
        obMsg(`@${d.agent.name} exists — call it from any chat`,'ok');
        setTimeout(()=>obRefresh(true),900);
      }finally{b.disabled=false}
    };
    $('#ob-agent-studio').onclick=()=>{obClose();openApp('fabric')};
  },

  app(){
    const box=$('#ob-app-prompt'),picks=$('#ob-app-picks');
    const pick=()=>{
      const i=+((document.querySelector('input[name=ob-app]:checked')||{}).value||0);
      // Only while it is still one of ours: once they have typed, the chips stop
      // overwriting it. Picking a different one after editing would silently throw
      // their sentence away.
      if(!box.dataset.touched)box.value=(OB_APP_IDEAS[i]||{}).prompt||'';
    };
    box.oninput=()=>{box.dataset.touched='1'};
    if(picks)picks.querySelectorAll('input[name=ob-app]').forEach(r=>r.onchange=pick);
    pick();
    $('#ob-app-go').onclick=()=>{
      const text=(box.value||'').trim();
      if(!text)return obMsg('describe it in a sentence','warn');
      /* Handed to App Studio rather than built from here. A build streams for a
         minute or two with a log and a live preview, and that watching IS the
         lesson — reproducing a thin version of it inside the arc would teach less
         and be a second builder to keep true. The window carries the step back, so
         closing Studio returns here with the step ticked. */
      obClose();
      const w=openApp('studio');
      if(w)w._backToSetup='app';
      // After render: the field does not exist until Studio has drawn itself.
      setTimeout(()=>{
        const p=$('#st-prompt');
        if(p){p.value=text;p.focus()}
      },220);
    };
  },

  flow(){
    const make=async(run)=>{
      const out=$('#ob-reply');obMsg('creating…');
      const d=await (await fetch('/api/onboarding/flow',{method:'POST',
        headers:{'Content-Type':'application/json'},body:JSON.stringify({})})).json();
      if(d.error)return obMsg(d.error,'warn');
      obMsg(`${d.flow.name} created — ${(d.report.grants||{}).added||0} permissions granted`,'ok');
      if(!run)return setTimeout(()=>obRefresh(true),900);
      out.innerHTML='<div class="ob-think">starting the run…</div>';
      const r=await (await fetch(`/api/flows/${encodeURIComponent(d.flow.name)}/run`,
        {method:'POST',headers:{'Content-Type':'application/json'},
         body:JSON.stringify({input:'What is new in this OS this week?',surface:'gui'})})).json();
      if(r.error){out.innerHTML='';return obMsg(r.error,'warn')}
      obMsg('running — the inspector will follow it','ok');
      obClose();
      if(typeof fgWatch==='function')fgWatch(r.run_id);else openApp('fabric');
    };
    $('#ob-flow-go').onclick=()=>make(false);
    $('#ob-flow-run').onclick=()=>make(true);
  },

  async schedule(){
    const box=$('#ob-jobs');if(!box)return;
    if(typeof jobsLoad!=='function'){box.innerHTML='<p class="mut">Jobs are unavailable.</p>';return}
    await jobsLoad();
    box.innerHTML=jobCards(JOBS.pick)+'<div class="job-slot"></div>';
    box.querySelectorAll('.job-card').forEach(b=>b.onclick=()=>{
      const r=JOBS.recipes.find(x=>x.id===b.dataset.job);if(!r)return;
      JOBS.pick=r.id;
      box.querySelectorAll('.job-card').forEach(x=>x.classList.toggle('on',x===b));
      const slot=box.querySelector('.job-slot');
      slot.innerHTML=jobForm(r);
      jobWire(slot,r,res=>{
        obMsg(`${res.flow.name} — runs ${res.next||'when you say so'}`,'ok');
        setTimeout(()=>obRefresh(true),1100);
      });
    });
  },

  channel(){
    const go=tab=>{SETTAB='channels';localStorage.setItem('settab','channels');
      obClose();openApp('settings');
      setTimeout(()=>{const el=document.querySelector(`.pgroup.chan[data-f*=${tab}]`);
        if(el)el.scrollIntoView({block:'start'})},700)};
    $('#ob-ch-tg').onclick=()=>go('telegram');
    $('#ob-ch-wa').onclick=()=>go('whatsapp');
  },

  async account(){
    const box=$('#ob-acct');if(!box)return;
    let d={};try{d=await (await fetch('/api/users')).json()}catch(e){}
    const list=(d.users||[]),me=d.me||{},first=!me.multiuser;
    box.innerHTML=`
      ${list.length?`<div class="ob-card">
          <b>${list.length} account${list.length===1?'':'s'}</b>
          <span>${list.map(u=>esc(u.name)+' · '+(u.role==='admin'?'admin':'executor')).join('<br>')}</span>
        </div>`:''}
      ${first?`<div class="usr-note">
        <b>Three things happen the moment you add the first account.</b>
        <ul>
          <li>Everything you just set up becomes <em>that</em> account's — the agent,
            the specialist, the flow, the schedule. Nothing is lost.</li>
          <li>This desktop starts asking who you are, at the keyboard as well as from
            a phone. So do not forget the password.</li>
          <li>It is an admin, whatever you pick — a machine whose only account cannot
            administer it is a machine nobody can administer.</li>
        </ul></div>`
       :`<p class="mut">Each account is its own home: own memory, own agents, own
          channels, own credentials. Settings stay shared, and agents and apps can be
          handed over deliberately, as copies.</p>`}
      <p class="mut"><b>It is the same sign-in from anywhere.</b> The username and
        password below are what this person types on their phone too — there is no
        separate remote passphrase to invent or share.</p>
      <form class="usr-form" id="ob-acct-form" autocomplete="off">
        <label><span>Username</span><input id="ob-u-name" placeholder="ada"
          autocapitalize="none" spellcheck="false"></label>
        <label><span>Display name</span><input id="ob-u-disp" placeholder="Ada Lovelace"></label>
        <label><span>Password</span><input id="ob-u-pass" type="password"
          placeholder="at least 8 characters" autocomplete="new-password"></label>
        ${first?'':`<div class="usr-roles">
          <label class="usr-pick"><input type="radio" name="ob-u-role" value="executor" checked>
            <b>Executor</b><em>Everything inside their own home.</em></label>
          <label class="usr-pick"><input type="radio" name="ob-u-role" value="admin">
            <b>Admin</b><em>That, plus the machine: accounts, providers, components,
              remote access.</em></label></div>`}
        <div class="job-go"><button class="wiz-next" id="ob-u-go">${
          first?'Create the first account':'Add this person'}</button>
          ${list.length?'<button class="endbtn" type="button" id="ob-u-manage">Manage accounts</button>':''}
        </div>
      </form>`;
    const mg=$('#ob-u-manage');
    if(mg)mg.onclick=()=>{obClose();openApp('users')};
    $('#ob-acct-form').onsubmit=async e=>{
      e.preventDefault();
      const btn=$('#ob-u-go');
      const body={name:($('#ob-u-name').value||'').trim(),
                  display:($('#ob-u-disp').value||'').trim(),
                  password:$('#ob-u-pass').value||'',
                  role:(document.querySelector('input[name=ob-u-role]:checked')||{}).value||'executor'};
      if(!body.name||!body.password)return obMsg('a username and a password, please','warn');
      if(first&&!await osConfirm('Turn on accounts for this machine?',
        'Everything you have just set up becomes your account. From now on this '+
        'desktop asks who you are — at the keyboard as well as from a phone.',
        {confirmText:'Create the account'}))return;
      btn.disabled=true;obMsg('creating…');
      try{
        const r=await fetch('/api/users',{method:'POST',
          headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        const d=await r.json().catch(()=>({}));
        if(!r.ok)return obMsg(d.error||'could not create the account','warn');
        obMsg(d.signed_in?`signed in as ${body.name} — this is your machine now`
                         :`${body.name} can sign in, here and from their phone`,'ok');
        if(typeof usersBoot==='function')usersBoot();
        setTimeout(()=>obRefresh(false),900);
      }finally{btn.disabled=false}
    };
  },

  async look(){
    const box=$('#ob-look');if(!box)return;
    const names=typeof allThemes==='function'?allThemes():{};
    const ids=Object.keys(names).slice(0,10);
    box.innerHTML=`<div class="job-q"><span>Theme</span>
        <div class="ob-swatches">${ids.map(id=>`
          <button class="ob-sw${(typeof CURRENT_THEME!=='undefined'&&CURRENT_THEME===id)?' on':''}"
            data-theme="${esc(id)}"><i style="background:${esc((names[id].v||{}).acc||'#5eead4')}"></i>
            ${esc(names[id].label||id)}</button>`).join('')}</div></div>
      <div class="job-q"><span>Speak replies out loud</span>
        <div class="job-ways">
          <label class="job-way"><input type="radio" name="ob-voice" value="0" checked>
            <b>Text only</b><em>the quiet default</em></label>
          <label class="job-way"><input type="radio" name="ob-voice" value="1">
            <b>Read them to me</b><em>uses this device's own voice</em></label>
        </div></div>
      <div class="job-go"><button class="wiz-next" id="ob-look-go">Save how it looks</button></div>`;
    box.querySelectorAll('.ob-sw').forEach(b=>b.onclick=()=>{
      applyTheme(b.dataset.theme);
      box.querySelectorAll('.ob-sw').forEach(x=>x.classList.toggle('on',x===b));
    });
    $('#ob-look-go').onclick=async()=>{
      const v=(document.querySelector('input[name=ob-voice]:checked')||{}).value==='1';
      if(typeof VOICE!=='undefined'){VOICE.tts=v;if(typeof saveVoice==='function')saveVoice()}
      await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({desktop:{theme:(typeof CURRENT_THEME!=='undefined'?CURRENT_THEME:''),
                                      voice_tts:v}})});
      await loadConfig();
      obMsg('saved','ok');obRefresh(true);
    };
  },
};

/* Setup is finished when the person says so, not when the last step goes green —
   somebody who skipped three steps has still finished. */
async function markSetupComplete(){
  try{await fetch('/api/setup',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({})})}catch(e){}
}

/* Settings → Start over. Never a factory reset: "run setup again" almost always
   means "I want to change something and cannot remember where it lives". */
async function obRestart(){
  try{await fetch('/api/onboarding/restart',{method:'POST'})}catch(e){}
  obShow({});
}
