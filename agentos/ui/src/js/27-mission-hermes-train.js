/* ================= mission control (lifecycle) ================= */
async function renderMission(body,w){
  body.style.cssText='padding:16px;overflow:auto;height:100%';
  body.innerHTML='<div class="mut">loading lifecycle state…</div>';
  const lane=(title,app,rows,accent)=>`
    <div class="provbox" style="cursor:pointer;margin:0" onclick="openApp('${app}')">
      <div class="ptitle" style="display:flex;justify-content:space-between;align-items:center">
        <span>${title}</span><span style="font-size:10px;color:var(--mut)">open ↗</span></div>
      ${rows.map(([k,v,warn])=>`<div style="display:flex;justify-content:space-between;font-size:12px;padding:3px 0">
        <span class="mut">${esc(k)}</span><span style="${warn?'color:var(--warn,#e8b04b)':''}">${esc(String(v))}</span></div>`).join('')}
    </div>`;
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
      ${lane('🧪 Test','logs',[
        ['suite',te.suite||'—'],
        ['last run',te.last?te.last.message:'never',!te.last],
        ['restart gate','tests must pass']])}
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
        ['sandbox',m.sandbox?'on':'OFF',!m.sandbox]])}
      </div>`;
  };
  await paint();
  w.timer=setInterval(paint,6000);
}

/* ================= hermes app (companion agent + wrapper) ================= */
const HERMES_SETUP_LISTENERS=new Set();
async function renderHermes(body,w){
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
  w.timer=setInterval(async()=>{const el=$('#hz-config');if(el&&document.activeElement===el)return;await paint()},8000);
}

/* ================= train app (TrainForge) ================= */
const TRAIN_SETUP_LISTENERS=new Set();
async function renderTrain(body,w){
  body.style.cssText='display:flex;flex-direction:column;height:100%;padding:0';
  body.innerHTML='<div class="mut" style="padding:24px">checking the training service…</div>';
  const paint=async()=>{
    let st={running:false};
    try{st=await (await fetch('/api/train/status')).json()}catch(e){}
    if(st.running){
      if(!body.querySelector('iframe')){
        body.innerHTML=`<iframe src="${esc(st.url||'http://127.0.0.1:8377')}" style="border:0;width:100%;height:100%;flex:1" title="TrainForge"></iframe>`;
        clearInterval(w.timer);
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
  w.timer=setInterval(paint,4000);
}

