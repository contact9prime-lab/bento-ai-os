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

async function obLoad(){
  try{OB.state=await (await fetch('/api/onboarding')).json()}catch(e){OB.state=null}
  return OB.state;
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
  if(!OB.state)return;
  let ov=$('#ob-wiz');
  if(!ov){
    ov=document.createElement('div');ov.id='ob-wiz';ov.className='wiz ob';
    document.body.appendChild(ov);
    Motion.run(ov,[{opacity:0},{opacity:1}],{duration:240,easing:EASE.out});
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
  if(!OB.state){body.innerHTML='<p class="mut" style="padding:16px">Setup is '
    +'unavailable — the server did not answer.</p>';return}
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
    ${S.steps.map(s=>`<button class="ob-item ${s.status}${s.id===OB.open?' on':''}"
        data-step="${esc(s.id)}" ${s.blocked.length?'disabled':''}>
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
  const body=OB_PANES[s.id]?OB_PANES[s.id](s):'<p class="mut">Nothing to do here.</p>';
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
  const sk=$('#ob-skip');
  if(sk)sk.onclick=()=>obSkip(s.id,s.status==='skipped');
  const pn=$('#ob-panel');
  // Most steps live in a Settings tab; accounts have an app of their own. Both are
  // "where this lives afterwards", which is the promise the button makes.
  if(pn)pn.onclick=()=>{
    obClose();
    if(APPS[s.panel])return openApp(s.panel);
    SETTAB=s.panel;localStorage.setItem('settab',s.panel);openApp('settings');
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

  hello:s=>`<p class="mut">One question, answered by your model, through the whole
      agent — provider, key, model name and the tool loop. A green tick from an API
      would prove none of that.</p>
    <div class="job-go"><button class="wiz-next" id="ob-hello-go">Ask it something</button></div>
    <div class="ob-reply" id="ob-reply"></div>`,

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
      await loadConfig();
      obMsg('saved','ok');
      obRefresh(true);
    };
    go.onclick=save;
    inp.onkeydown=e=>{if(e.key==='Enter')save()};
    inp.focus();inp.select();
  },

  async model(){
    const box=$('#ob-model-box');if(!box)return;
    let d={};try{d=await (await fetch('/api/setup')).json()}catch(e){}
    const local=(d.ollama_models||[]);
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
          <b>Anthropic, OpenAI or OpenRouter</b><em>needs an API key</em></label></div></div>
      <div id="ob-cloud" style="display:none">
        <div class="row" style="gap:8px;margin-top:8px">
          <select id="ob-prov">
            <option value="anthropic">Anthropic (Claude)</option>
            <option value="openai">OpenAI</option>
            <option value="openrouter">OpenRouter</option></select>
          <input id="ob-key" placeholder="API key" style="flex:1"></div>
        <input id="ob-cmodel" placeholder="model, e.g. claude-sonnet-5" style="width:100%;margin-top:6px">
      </div>
      <div class="job-go"><button class="wiz-next" id="ob-model-go">Use this model</button></div>`;
    const upd=()=>{const v=(document.querySelector('input[name=ob-model]:checked')||{}).value;
      $('#ob-cloud').style.display=v==='cloud'?'block':'none'};
    box.querySelectorAll('input[name=ob-model]').forEach(r=>r.onchange=upd);upd();
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
    $('#ob-hello-go').onclick=async()=>{
      const btn=$('#ob-hello-go'),out=$('#ob-reply');
      btn.disabled=true;btn.textContent='asking…';obMsg('');
      out.innerHTML='<div class="ob-think">thinking…</div>';
      try{
        const r=await fetch('/api/onboarding/hello',{method:'POST',
          headers:{'Content-Type':'application/json'},body:JSON.stringify({})});
        const d=await r.json();
        if(!r.ok||d.error){
          out.innerHTML='';obMsg(d.error||'it could not answer','warn');return}
        out.innerHTML=`<div class="ob-said"><b>${esc(d.model)}</b>${esc(d.reply)}</div>`;
        obMsg('that came from your model, through the whole agent','ok');
        await obLoad();obRender();
        // keep the reply on screen after the re-render — it is the payoff
        const o=$('#ob-reply');
        if(o)o.innerHTML=`<div class="ob-said"><b>${esc(d.model)}</b>${esc(d.reply)}</div>`;
      }catch(e){out.innerHTML='';obMsg('could not reach the server','warn')}
      finally{btn.disabled=false;btn.textContent='Ask it again'}
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
