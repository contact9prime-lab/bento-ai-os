/* ================= mission control (lifecycle) ================= */
async function renderMission(body,w){
  stopWinTicks(w);          // a re-render replaces the poller, it does not add another
  body.style.cssText='padding:16px;overflow:auto;height:100%';
  body.innerHTML='<div class="mut">loading lifecycle state…</div>';
  const lane=(title,app,rows,accent)=>`
    <div class="provbox" style="cursor:pointer;margin:0" onclick="openApp('${app}')">
      <div class="ptitle" style="display:flex;justify-content:space-between;align-items:center">
        <span>${title}</span><span style="font-size:10px;color:var(--mut)">open ↗</span></div>
      ${rows.map(([k,v,warn])=>`<div style="display:flex;justify-content:space-between;font-size:12px;padding:3px 0">
        <span class="mut">${esc(k)}</span><span style="${warn?'color:var(--warn,#e8b04b)':''}">${esc(String(v))}</span></div>`).join('')}
    </div>`;
  // "12 cases, never run" is a truer thing to show than a blank — the pillar
  // claimed the agent was tested when only the OS was.
  const evalScore=(e)=>{
    if(!e)return '—';
    if(!e.last)return (e.cases||0)+' cases, never run';
    const s=Object.values(e.last.by_model||{})[0]||{};
    const tot=(s.passed||0)+(s.failed||0)+(s.errors||0);
    return tot?`${s.passed}/${tot} passed`:(e.cases||0)+' cases';
  };
  // Tokens are a fact, money is an estimate — so an unpriced turn is shown as
  // tokens, never folded into a dollar figure that would read as "this was free".
  const spend24=(s)=>{
    if(!s||!(s.tokens_in||s.tokens_out))return 'nothing yet';
    const tok=((s.tokens_in||0)+(s.tokens_out||0));
    const t=tok>9999?(tok/1000).toFixed(1)+'k tok':tok+' tok';
    return (s.cost_usd?('$'+s.cost_usd.toFixed(4)+' · '):'')+t+(s.unpriced_turns?' (some unpriced)':'');
  };
  const paint=async()=>{
    let d;
    try{d=await (await fetch('/api/lifecycle')).json()}catch(e){return}
    if(!body.isConnected)return;
    const t=d.train||{},te=d.test||{},o=d.operate||{},b=d.build||{},s=d.ship||{},m=d.manage||{};
    body.innerHTML=`
      <div style="margin-bottom:12px">
        <div style="font-size:16px;font-weight:650">Mission Control</div>
        <div class="mut" style="font-size:12px">the whole lifecycle of what this OS builds — train it, test it, run it, ship it, govern it</div>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px">
      ${lane('🧬 Train','train',[
        ['service',t.service||'—',t.service!=='running'],
        ['jobs running',t.jobs_running??0],
        ['trained models',t.models??0]])}
      ${lane('🧪 Test','evals',[
        ['suite',te.suite||'—'],
        ['last run',te.last?te.last.message:'never',!te.last],
        ['restart gate','tests must pass'],
        ['behaviour evals',evalScore(te.evals),!(te.evals&&te.evals.last)]])}
      ${lane('⚙ Operate','tasks',[
        ['scheduled jobs',(o.tasks_enabled??0)+' on / '+(o.scheduled_tasks??0)],
        ['turns (24h)',o.turns_24h??0],
        ['errors (24h)',o.errors_24h??0,(o.errors_24h||0)>0],
        ['turns running now',o.turns_running??0],
        ['hermes',o.hermes||'—']])}
      ${lane('🔨 Build','studio',[
        ['apps installed',b.apps??0],
        ['build running',b.build_running?'yes':'no'],
        ['latest app',b.last_app||'—']])}
      ${lane('🚀 Ship','files',[
        ['git projects',(s.git_projects||[]).length],
        ['github token',s.github_token?'configured':'not set',!s.github_token],
        ['package',s.package||'—']])}
      ${lane('🛡 Manage','permissions',[
        ['autonomy',m.autonomy||'—'],
        ['model',(m.model||'—').split('/').pop()],
        ['grants',m.grants??0],
        ['snapshots',m.snapshots??0],
        ['sandbox',m.sandbox?'on':'OFF',!m.sandbox],
        ['spend (24h)',spend24(m.spend_24h)]])}
      </div>`;
  };
  await paint();
  winTick(w,paint,6000,{now:false,key:'poll'});
}

/* ================= hermes app (companion agent + wrapper) ================= */
const HERMES_SETUP_LISTENERS=new Set();
async function renderHermes(body,w){
  stopWinTicks(w);
  body.style.cssText='padding:0;height:100%;display:flex;flex-direction:column';
  const load=async()=>{try{return await (await fetch('/api/hermes/status')).json()}catch(e){return{installed:false}}};
  const log=(m)=>{const el=$('#hz-log');if(el){el.textContent=m;el.scrollTop=el.scrollHeight}};
  const paint=async()=>{
    const st=await load();if(!body.isConnected)return;
    const busy=st.setup==='installing';
    body.innerHTML=`
      <div style="padding:16px 18px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:12px">
        <div style="font-size:24px">🜁</div>
        <div style="flex:1">
          <div style="font-weight:650">Hermes agent <span class="mut" style="font-weight:400;font-size:11px">· MIT · NousResearch</span></div>
          <div class="mut" style="font-size:12px">${st.installed?('installed — '+esc(st.model||'?')+' · '+esc(st.provider||'?')+' · gateway '+(st.gateway?'running':'stopped')):'not installed'}</div>
        </div>
        ${st.installed?`<span class="pill" style="font-size:11px;padding:4px 9px;border-radius:20px;background:${st.gateway?'rgba(94,234,212,.15)':'var(--bg3)'};border:1px solid var(--line)">${st.gateway?'● live':'○ idle'}</span>`:''}
      </div>
      <div style="padding:16px 18px;overflow:auto;flex:1">
        ${!st.installed?`
          <div class="mut" style="max-width:560px;margin-bottom:12px">Hermes is a second self-hosted agent (WhatsApp/Slack/Discord/Signal, skills, cron). Download it here to use it as an alternative chat engine, or to reach those platforms. AgentOS becomes its control surface — you can edit its config below once installed.</div>
          <button class="pact" id="hz-install" ${busy?'disabled':''}>${busy?'downloading…':'Download Hermes (MIT)'}</button>
          <div class="mut" style="font-size:11px;margin-top:6px">clones ${esc(st.install_dir||'~/.hermes/hermes-agent')} and provisions its venv — a few minutes, one-time</div>
        `:`
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
            <button class="endbtn" id="hz-gw">${st.gateway?'Stop gateway':'Start gateway'}</button>
            <button class="endbtn" id="hz-update">Update Hermes</button>
            <button class="endbtn" onclick="openApp('chat')">Use as chat engine →</button>
          </div>
          <div style="font-weight:600;margin-bottom:6px">Config <span class="mut" style="font-weight:400;font-size:11px">· ${esc(st.config_path||'~/.hermes/config.yaml')} (API keys live in .env and are never shown here)</span></div>
          <textarea id="hz-config" spellcheck="false" style="width:100%;height:300px;font-family:var(--mono);font-size:12px;background:var(--bg2);color:var(--tx);border:1px solid var(--line);border-radius:8px;padding:10px;resize:vertical"></textarea>
          <div style="display:flex;gap:8px;margin-top:8px;align-items:center">
            <button class="pact" id="hz-save">Save config</button>
            <button class="endbtn" id="hz-reload">Reload</button>
            <span class="mut" id="hz-cfgmsg" style="font-size:12px"></span>
          </div>
        `}
        <pre id="hz-log" class="mut" style="font-size:11px;white-space:pre-wrap;margin-top:14px;max-height:120px;overflow:auto"></pre>
      </div>`;
    if(!st.installed){
      const b=$('#hz-install');if(b&&!busy)b.onclick=async()=>{b.disabled=true;b.textContent='downloading…';
        await fetch('/api/hermes/service',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'install'})});};
    }else{
      const ta=$('#hz-config');
      const loadCfg=async()=>{try{const d=await (await fetch('/api/hermes/config')).json();if(ta)ta.value=d.text||''}catch(e){}};
      await loadCfg();
      $('#hz-reload').onclick=loadCfg;
      $('#hz-save').onclick=async()=>{const msg=$('#hz-cfgmsg');msg.textContent='saving…';
        const r=await fetch('/api/hermes/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:ta.value})});
        const d=await r.json();msg.textContent=r.ok?'saved ✓':(d.error||'error');msg.style.color=r.ok?'var(--ok)':'var(--err)';};
      $('#hz-gw').onclick=async()=>{$('#hz-gw').disabled=true;
        await fetch('/api/hermes/service',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:st.gateway?'gateway_stop':'gateway_start'})});
        setTimeout(paint,1500);};
      $('#hz-update').onclick=async()=>{log('updating…');
        await fetch('/api/hermes/service',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'update'})});};
    }
  };
  w._onSetup=ev=>{if(ev.type==='hermes_setup'){log(ev.message||'');if(ev.done)setTimeout(paint,800)}};
  HERMES_SETUP_LISTENERS.add(w._onSetup);
  await paint();
  winTick(w,async()=>{const el=$('#hz-config');if(el&&document.activeElement===el)return;await paint()},8000,{now:false,key:'poll'});
}

/* ================= train app (TrainForge) ================= */
const TRAIN_SETUP_LISTENERS=new Set();
async function renderTrain(body,w){
  stopWinTicks(w);
  body.style.cssText='display:flex;flex-direction:column;height:100%;padding:0';
  body.innerHTML='<div class="mut" style="padding:24px">checking the training service…</div>';
  const paint=async()=>{
    let st={running:false};
    try{st=await (await fetch('/api/train/status')).json()}catch(e){}
    if(st.running){
      if(!body.querySelector('iframe')){
        body.innerHTML=`<iframe src="${esc(st.url||'http://127.0.0.1:8377')}" style="border:0;width:100%;height:100%;flex:1" title="TrainForge"></iframe>`;
        stopTick(w._tick);   // the iframe is the UI now — stop polling for good
      }
      return;
    }
    if(body.querySelector('iframe'))return; // don't tear down a live UI on a blip
    const busy=st.setup==='fetching'||st.setup==='installing';
    const notHere=!st.path;
    const canGet=st.path||st.fetchable;   // on disk, or a repo URL is configured
    const btnLabel=busy?(st.setup==='fetching'?'downloading…':'installing…'):(notHere?'Get & start TrainForge':'Start TrainForge');
    body.innerHTML=`
      <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;flex:1;gap:14px;padding:30px;text-align:center">
        <div style="font-size:40px">🧬</div>
        <div style="font-size:17px;font-weight:600">Train your own models</div>
        <div class="mut" style="max-width:460px">TrainForge is AgentOS's training service: import datasets, fine-tune models
        (including LoRA fine-tunes of language models on your GPU), watch live loss curves, test every trained model as a
        live endpoint, and publish to Hugging Face. Everything stays on this machine.</div>
        ${notHere&&!st.fetchable?'<div class="errmsg">TrainForge isn\'t installed and no download URL is set — add <code>trainforge.repo</code> (or <code>trainforge.path</code>) in config.json.</div>':''}
        ${notHere&&st.fetchable?'<div class="mut" style="font-size:12px">Not installed yet — the button below downloads and sets it up (one-time, a few minutes; the GPU stack is a few GB).</div>':''}
        <button class="pact" id="tf-start" ${(canGet&&!busy)?'':'disabled'}>${btnLabel}</button>
        <div class="mut" style="font-size:11px">or just ask the agent: “fine-tune a model on …” — it fetches &amp; starts the service itself</div>
        <div id="tf-msg" class="mut" style="max-width:480px">${esc(busy?'setting up…':'')}</div>
      </div>`;
    const b=$('#tf-start');
    if(b&&!busy)b.onclick=async()=>{
      b.disabled=true;b.textContent=notHere?'downloading…':'starting…';
      fetch('/api/train/service',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'start'})})
        .then(r=>r.json()).then(r=>{const el=$('#tf-msg');if(el)el.textContent=r.result||''})
        .catch(e=>{const el=$('#tf-msg');if(el)el.textContent=''+e});
      // start returns only when up (or on error) — the poller flips us to the iframe
    };
  };
  // live setup progress from the server (download / install messages)
  w._onSetup=ev=>{if(ev.type==='train_setup'){const el=$('#tf-msg');if(el)el.textContent=ev.message||''}};
  TRAIN_SETUP_LISTENERS.add(w._onSetup);
  await paint();
  w._tick=winTick(w,paint,4000,{now:false,key:'poll'});
}


/* ================= evals app (behavioural tests for the agent) ================= */
/* The GUI face of `agentos eval`. Mission Control's Test lane links here.
   Deliberately plain: a run is a list of cases going green or red, and the only
   thing worth designing is that a FAILURE says which assertion failed and what
   the agent actually did — a verdict alone sends you to the JSON. */
const EVAL_LISTENERS=new Set();
async function renderEvals(body,w){
  stopWinTicks(w);
  body.style.cssText='padding:0;height:100%;display:flex;flex-direction:column';
  let data={cases:[],last:null},running=false,live={};
  const load=async()=>{try{return await (await fetch('/api/evals')).json()}catch(e){return{cases:[],last:null}}};
  const lastFor=(id)=>((data.last&&data.last.results)||[]).filter(r=>r.id===id).slice(-1)[0];
  const dot=(st)=>st==='pass'?'<span style="color:var(--ok)">●</span>'
    :st==='fail'?'<span style="color:var(--err)">●</span>'
    :st==='error'?'<span style="color:var(--warn)">●</span>'
    :st==='running'?'<span class="mut">◌</span>':'<span class="mut">○</span>';
  const paint=()=>{
    if(!body.isConnected)return;
    const l=data.last,models=l?Object.entries(l.by_model||{}):[];
    const head=models.map(([m,s])=>{
      const tot=(s.passed||0)+(s.failed||0)+(s.errors||0);
      return `<b>${esc(m.split('/').pop())}</b> ${s.passed}/${tot}`;
    }).join(' · ')||'never run';
    body.innerHTML=`
      <div style="padding:14px 18px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:12px">
        <div style="flex:1">
          <div style="font-weight:650">Behavioural evals</div>
          <div class="mut" style="font-size:12px">${data.cases.length} cases · last run: ${head}
            ${l?' · '+new Date(l.created_at*1000).toLocaleString():''}</div>
        </div>
        <button class="pact" id="ev-run" ${running?'disabled':''}>${running?'running…':'Run all'}</button>
      </div>
      <div style="padding:12px 18px;overflow:auto;flex:1">
        <div class="mut" style="font-size:12px;max-width:640px;margin-bottom:12px">
          <code>tests/</code> proves the OS works; these prove the <em>agent</em> still behaves —
          the thing that changes when you edit the soul, the system prompt or the model.
          Each case runs one turn in a throwaway home, so nothing here touches your data.
          Add your own in <code>~/.agentos/evals/*.json</code>, or run them over SSH with
          <code>agentos eval</code>.
        </div>
        ${data.cases.map(c=>{
          const r=live[c.id]||lastFor(c.id)||null;
          const st=r?r.status:'none';
          const failed=(r&&r.checks||[]).filter(x=>!x.ok);
          return `<div class="provbox" style="margin:0 0 8px;cursor:${failed.length?'pointer':'default'}"
                    ${failed.length?`onclick="this.classList.toggle('open')"`:''}>
            <div style="display:flex;gap:10px;align-items:baseline">
              <span>${dot(st)}</span>
              <div style="flex:1">
                <div style="font-size:13px">${esc(c.title||c.id)}</div>
                <div class="mut" style="font-size:11px;font-family:var(--mono)">${esc(c.id)}
                  ${(c.tags||[]).map(t=>`· ${esc(t)}`).join(' ')}
                  ${c.network?'· needs network':''}${c.source?'· '+esc(c.source):''}</div>
              </div>
              <span class="mut" style="font-size:11px">${r&&r.seconds?r.seconds+'s':''}</span>
            </div>
            ${failed.length?`<div class="ev-detail" style="margin-top:8px;font-size:12px">
              ${failed.map(x=>`<div style="color:var(--err)">✗ ${esc(x.assert)}${x.detail?' <span class="mut">('+esc(x.detail)+')</span>':''}</div>`).join('')}
              ${r.tools&&r.tools.length?`<div class="mut" style="margin-top:4px">tools: ${esc(r.tools.join(', '))}</div>`:''}
              ${r.answer?`<div class="mut" style="margin-top:4px;white-space:pre-wrap">${esc(r.answer.slice(0,400))}</div>`:''}
              ${r.error?`<div style="color:var(--warn);margin-top:4px">${esc(r.error)}</div>`:''}
            </div>`:''}
          </div>`;
        }).join('')||'<div class="mut">no cases</div>'}
      </div>`;
    const b=$('#ev-run');
    if(b&&!running)b.onclick=async()=>{
      running=true;live={};data.cases.forEach(c=>{if(!c.network)live[c.id]={status:'running'}});paint();
      try{
        const rep=await (await fetch('/api/evals/run',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({})})).json();
        if(rep&&rep.by_model)data.last=rep; else toast(rep.error||'eval run failed');
      }catch(e){toast('eval run failed: '+e)}
      running=false;live={};paint();
    };
  };
  data=await load();paint();
  // per-case progress while a run is going (the run itself is one long request)
  w._onEval=ev=>{
    if(ev.type==='eval_result'){live[ev.result.id]={status:ev.result.status,seconds:ev.result.seconds};paint()}
    else if(ev.type==='evals_done'){load().then(d=>{data=d;paint()})}
  };
  EVAL_LISTENERS.add(w._onEval);
}
