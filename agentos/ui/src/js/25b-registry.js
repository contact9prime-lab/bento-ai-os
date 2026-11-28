/* The Bento Registry tab in the Store (registryhub.py, /api/store/registry/*).

   Browsing needs no account. Publishing walks through sign in (a code by email),
   a publisher name and registering this machine, then a report on the exact bytes
   that would go: a credential stops it, personal details are shown and ticked. An
   app from the registry goes on to the Import door's consent screen and an agent
   to the fork preview, so nothing installs here that couldn't install from a file.

   GUI only by drawing; `bento registry` is the terminal face and the SUI face is
   this same page. State lives in REG (var: the bundle loads this file after 25). */
var REG = REG || {kind:'', q:'', st:null, items:[], pub:null, rep:null, got:null, step:'', email:'', err:'', open:false};
var REG_KINDS = [['','All'],['app','Apps'],['agent','Agents'],['skill','Skills'],['soul','Souls'],['tool','Tools']];
var REG_ICON = {app:'▦', agent:'◈', skill:'✎', soul:'☼', tool:'⚙'};

async function renderStoreRegistry(box){
  box.innerHTML = `<div class="reg">
    <div id="reg-acct" class="reg-acct"><p class="mut">Checking your registry sign-in…</p></div>
    <div class="reg-bar">
      <div class="seg reg-kinds" role="tablist">${REG_KINDS.map(([k,l])=>
        `<button role="tab" class="${REG.kind===k?'on':''}" data-k="${k}">${l}</button>`).join('')}</div>
      <input id="reg-q" placeholder="Search the Bento Registry…" value="${esc(REG.q)}">
    </div>
    <div id="reg-list" class="cat"><p class="mut">Loading the registry…</p></div>
    <div id="reg-get"></div>
    <div id="ags-fork"></div>
    <details class="reg-pub" id="reg-pub" ${REG.open?'open':''}>
      <summary><b>Publish to the registry</b> <span class="mut">an app, an agent, a skill, a soul or a tool</span></summary>
      <div id="reg-pub-body"><p class="mut">Loading what you could publish…</p></div>
    </details>
  </div>`;
  box.querySelectorAll('.reg-kinds button').forEach(b=>b.onclick=()=>{REG.kind=b.dataset.k;
    box.querySelectorAll('.reg-kinds button').forEach(x=>x.classList.toggle('on',x===b));regSearch()});
  const q = box.querySelector('#reg-q');
  let t = 0;
  q.oninput = ()=>{clearTimeout(t);t=setTimeout(()=>{REG.q=q.value.trim();regSearch()},300)};
  box.querySelector('#reg-pub').ontoggle = e=>{REG.open=e.target.open;if(REG.open)regPubPaint()};
  regAcct();
  regSearch();
  if(REG.open)regPubPaint();
}

async function regCall(path, body){
  const opt = body===undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};
  let r, d;
  try{ r = await fetch('/api/store/registry/'+path, opt); d = await r.json() }
  catch(e){ return {ok:false, error:'the server could not be reached'} }
  if(!r.ok && d && !d.error) d.error = 'HTTP '+r.status;
  return d || {ok:false, error:'no answer'};
}

/* ---- the account: sign in, a name, this machine ---- */
async function regAcct(){
  const el = document.getElementById('reg-acct'); if(!el) return;
  const st = REG.st = await regCall('status');
  if(st.error){ el.innerHTML = `<p class="mut">${esc(st.error)}</p>`; return }
  if(!st.signed_in){
    const waiting = REG.step==='code';
    const to = st.pending||REG.email;
    el.innerHTML = `<div class="reg-line">${waiting
        ? `<b>Check your email.</b> <span class="mut">Type the code we sent to ${esc(to)}.</span>`
        : `<b>Browse freely.</b> <span class="mut">Sign in with your email to publish.</span>`}</div>
      <div class="row">${waiting
        ? `<input id="reg-code" name="one-time-code" inputmode="numeric" autocomplete="one-time-code" maxlength="10" value="" placeholder="6-digit code" aria-label="Code from the email">
           <button class="pact" id="reg-go">Sign in</button><button class="endbtn" id="reg-again">Send again</button><button class="endbtn" id="reg-back">Another email</button>`
        : `<input id="reg-email" type="email" autocomplete="email" placeholder="you@example.com" value="${esc(REG.email)}" aria-label="Your email">
           <button class="pact" id="reg-go">Send a code</button>`}</div>
      ${REG.err?`<p class="reg-err" role="alert">${esc(REG.err)}</p>`:''}`;
    el.querySelector('#reg-go').onclick = waiting ? regVerify : regLogin;
    const inp = el.querySelector(waiting?'#reg-code':'#reg-email');
    inp.onkeydown = e=>{if(e.key==='Enter')(waiting?regVerify:regLogin)()};
    if(waiting){
      /* A browser may autofill the email into the code box: it is not a code, so it goes. */
      const tidy = ()=>{ if(/[^0-9\s]/.test(inp.value)) inp.value='' };
      inp.addEventListener('input', ()=>{ if(inp.value.includes('@')) tidy() });
      setTimeout(tidy, 300); inp.onfocus = tidy;
      el.querySelector('#reg-again').onclick = ()=>regLogin(to);
      el.querySelector('#reg-back').onclick = ()=>{REG.step='';REG.err='';regAcct()};
    }
    return;
  }
  if(!st.handle){
    el.innerHTML = `<div class="reg-line">Signed in as ${esc(st.email)}. <b>Choose the publisher name</b> <span class="mut">shown on everything you publish. Your email never is.</span></div>
      <div class="row"><input id="reg-handle" placeholder="lower-case-name" maxlength="32"><button class="pact" id="reg-go">Save</button>
      <button class="endbtn" id="reg-out">Sign out</button></div>`;
    el.querySelector('#reg-go').onclick = async()=>{
      const d = await regCall('handle',{handle:el.querySelector('#reg-handle').value});
      if(d.error) return toast(d.error,{kind:'err'}); regAcct()};
    el.querySelector('#reg-out').onclick = regLogout;
    return;
  }
  if(!st.registered){
    el.innerHTML = `<div class="reg-line">Publishing as <b>${esc(st.handle)}</b>. <span class="mut">Register this machine so it can sign what you publish. Its key stays here.</span></div>
      <div class="row"><input id="reg-mname" placeholder="A name for this machine" maxlength="60">
      <button class="pact" id="reg-go">Register this machine</button><button class="endbtn" id="reg-out">Sign out</button></div>`;
    el.querySelector('#reg-go').onclick = async()=>{
      const d = await regCall('register',{name:el.querySelector('#reg-mname').value});
      if(d.error) return toast(d.error,{kind:'err'}); toast('this machine can publish for you'); regAcct(); if(REG.open)regPubPaint()};
    el.querySelector('#reg-out').onclick = regLogout;
    return;
  }
  el.innerHTML = `<div class="reg-line reg-ready"><span class="reg-dot" aria-hidden="true"></span>
      <span>Publishing as <b>${esc(st.handle)}</b> from ${esc(st.machine)}</span> ${pInfo('Signed in as '+st.email+'. This machine signs with key '+st.key_id+'. Its private half never leaves this machine.')}</div>
      <div class="row"><button class="endbtn" id="reg-out">Sign out</button>
      <button class="endbtn" id="reg-rev">Stop this machine publishing</button></div>`;
  el.querySelector('#reg-out').onclick = regLogout;
  el.querySelector('#reg-rev').onclick = async()=>{
    if(!await osConfirm('Stop this machine publishing?','What it already published stays signed by it. To publish from here again you would register a new key.',{danger:true,confirmText:'Stop it'}))return;
    const d = await regCall('revoke',{}); if(d.error) return toast(d.error,{kind:'err'}); regAcct()};
}

/* A sign-in refusal stays on the card until the next try: a toast is gone before it is read,
   and in the setup wizard it can sit behind the wizard. */
function regBusy(on, label){
  const b = document.getElementById('reg-go'); if(!b) return;
  b.disabled = on; if(on){ b.dataset.was = b.textContent; b.textContent = label }
  else if(b.dataset.was) b.textContent = b.dataset.was;
}
async function regLogin(again){
  if(typeof again==='string') REG.email = again;
  else REG.email = ((document.getElementById('reg-email')||{}).value||'').trim();
  if(!REG.email.includes('@')){ REG.err = 'Type your email address first.'; return regAcct() }
  REG.err = ''; regBusy(true, 'Sending…');
  const d = await regCall('login',{email:REG.email});
  regBusy(false);
  if(d.error){ REG.err = 'The code was not sent: '+d.error+'.'; return regAcct() }
  REG.step = 'code'; toast('a sign-in code is on its way to '+d.to); regAcct();
}
async function regVerify(){
  const code = ((document.getElementById('reg-code')||{}).value||'').replace(/\s+/g,'');
  if(!/^[0-9]{6,10}$/.test(code)){
    REG.err = code.includes('@') ? 'That is your email. Type the 6-digit code from the email instead.'
                                 : 'The code is the 6 digits in the email.';
    return regAcct();
  }
  REG.err = ''; regBusy(true, 'Signing in…');
  const d = await regCall('verify',{code, email:REG.email});
  regBusy(false);
  if(d.error){ REG.err = 'Not signed in: '+d.error+'.'; return regAcct() }
  REG.step = ''; toast('signed in to the Bento registry'); regAcct(); if(REG.open)regPubPaint();
}
async function regLogout(){ await regCall('logout',{}); REG.step=''; REG.err=''; regAcct(); if(REG.open)regPubPaint() }

/* ---- browsing ---- */
async function regSearch(){
  const el = document.getElementById('reg-list'); if(!el) return;
  const d = await regCall('search?q='+encodeURIComponent(REG.q)+'&kind='+encodeURIComponent(REG.kind));
  if(d.error){ el.innerHTML = `<p class="mut">${esc(d.error)}</p>`; return }
  REG.items = d.items || [];
  if(!REG.items.length){ el.innerHTML = `<p class="mut">Nothing in the registry${REG.q?' matches that':' yet'}. Publish the first one below.</p>`; return }
  el.innerHTML = REG.items.map((it,i)=>`<div class="catcard reg-card">
      <span class="reg-kind">${REG_ICON[it.kind]||'·'} ${esc(it.kind)}</span>
      <span class="cn">${esc(it.icon?it.icon+' ':'')}${esc(it.name)}</span>
      <span class="cd">${esc(it.summary||'')}</span>
      <span class="reg-meta">${it.publisher==='bento'?'<span class="badge ok" title="Published by Bento">Bento</span>':`<span>${esc(it.publisher||'')}</span>`}<span>v${esc(it.latest||'-')}</span>
        <span title="downloads">↓ ${Number(it.downloads||0).toLocaleString()}</span>
        ${it.verdict&&it.verdict!=='pass'?`<span class="reg-flag">${it.verdict==='review'?'has personal details':esc(it.verdict)}</span>`:''}</span>
      <div class="reg-acts"><button class="save" data-get="${i}">Get…</button>
        ${Number(it.version_count)>1?`<button class="endbtn" data-ver="${i}">${it.version_count} versions</button>`:''}</div>
    </div>`).join('');
  el.querySelectorAll('[data-get]').forEach(b=>b.onclick=()=>regGet(REG.items[+b.dataset.get]));
  el.querySelectorAll('[data-ver]').forEach(b=>b.onclick=()=>regVersions(REG.items[+b.dataset.ver]));
}

async function regVersions(it){
  const out = document.getElementById('reg-get');
  const d = await regCall('versions?kind='+encodeURIComponent(it.kind)+'&slug='+encodeURIComponent(it.slug));
  if(d.error) return toast(d.error,{kind:'err'});
  out.innerHTML = `<div class="ghint"><b>${esc(it.name)}</b>: versions
    ${(d.versions||[]).map(v=>`<div class="prow reg-vrow"><b>${esc(v.version)}</b>
      <span class="mut">${esc((v.created_at||'').slice(0,10))} · ↓ ${Number(v.downloads||0)}${v.yanked?' · withdrawn':''}</span>
      <span class="grow">${esc(v.notes||'')}</span>
      ${v.yanked?'':`<button class="endbtn" data-v="${esc(v.version)}">Get this one</button>`}</div>`).join('')}</div>`;
  out.querySelectorAll('[data-v]').forEach(b=>b.onclick=()=>regGet(it, b.dataset.v));
  out.scrollIntoView({block:'nearest'});
}

function regReportHTML(rep, title){
  const row = (cls, mark, x)=>`<div class="reg-f ${cls}"><b aria-hidden="true">${mark}</b> <span>${esc(x.what)}${x.line?`, line ${x.line}`:''}${x.excerpt?` <code>${esc(x.excerpt)}</code>`:''}</span></div>`;
  const words = {blocked:'Can’t be published as it is', review:'Look at these first', caution:'The app scan has notes', pass:'Nothing personal or secret found'};
  const sec = (rep.security&&rep.security.findings)||[];
  return `<div class="reg-rep v-${esc(rep.verdict)}">
    <div class="reg-rep-h"><b>${esc(title||words[rep.verdict]||rep.verdict)}</b>
      <span class="mut">${Number(rep.bytes||0).toLocaleString()} bytes checked on this machine</span></div>
    ${(rep.blocking||[]).map(b=>row('bad','✗',b)).join('')}
    ${(rep.warnings||[]).map(w=>row('warn','!',w)).join('')}
    ${sec.map(f=>`<div class="reg-f note"><b aria-hidden="true">·</b> <span>line ${esc(f.line)}: ${esc(f.note)}</span></div>`).join('')}
    ${(rep.permissions||[]).length?`<div class="reg-f note"><b aria-hidden="true">·</b> <span>asks for ${esc(rep.permissions.slice(0,10).join(', '))}${rep.permissions.length>10?' …':''}</span></div>`:''}
  </div>`;
}

async function regGet(it, version){
  const out = document.getElementById('reg-get');
  out.innerHTML = '<p class="mut">Downloading and checking it…</p>';
  const d = await regCall('get',{ref:it.kind+'/'+it.slug, version:version||''});
  if(d.error){ out.innerHTML = `<div class="ghint" style="border-color:var(--err)">${esc(d.error)}</div>`; return }
  REG.got = d;
  const head = `<div class="reg-line">✓ <b>${esc(d.name||it.name)} ${esc(d.version)}</b> by ${esc(d.publisher)}. The file matches the publisher’s signature.
      ${d.revoked?'<span class="reg-flag">its machine was revoked since</span>':''}</div>
      <div class="sub ${d.pin_status==='changed-key'?'reg-bad':''}">${esc(d.pin_note)}</div>`;
  if(d.kind==='app'){
    out.innerHTML = `<div class="ghint">${head}${regReportHTML(d.local,'Checked again here')}</div>`;
    await storeImportStage({package:d.package}, ()=>regCall('pin',{sha256:d.sha256}));
    return;
  }
  if(d.kind==='agent'){
    out.innerHTML = `<div class="ghint">${head}${regReportHTML(d.local,'Checked again here')}</div>`;
    await agsPreview(d.package, it.slug);
    regCall('pin',{sha256:d.sha256});
    return;
  }
  const p = d.preview||{};
  const body = d.kind==='tool'
    ? `<pre class="reg-pre">${esc(JSON.stringify(p.mcp,null,1))}</pre><p class="sub mut">It arrives switched off, with any keys for you to fill in.</p>`
    : `<pre class="reg-pre">${esc(p.content||'')}</pre>`;
  const verb = {skill: p.exists?'':'Install the skill', soul:'Save it beside your soul', tool: p.exists?'':'Add the tool, switched off'}[d.kind];
  out.innerHTML = `<div class="ghint">${head}${regReportHTML(d.local,'Checked again here')}
    ${d.kind==='soul'?'<p class="sub">Your agent keeps its own soul. This is saved as a file for you to read, and you choose whether to use any of it.</p>':''}
    ${body}
    <div class="prow">${verb?`<button class="save" id="reg-inst">${verb}</button>`:`<span class="mut">You already have one called ${esc(p.name||it.slug)}. It was left as it is.</span>`}</div></div>`;
  const b = out.querySelector('#reg-inst');
  if(b) b.onclick = async()=>{
    const r = await regCall('install',{sha256:d.sha256});
    if(r.error) return toast(r.error,{kind:'err'});
    toast('installed '+r.installed); out.innerHTML=''; refreshApp('store');
  };
}

/* ---- publishing ---- */
async function regPubPaint(){
  const el = document.getElementById('reg-pub-body'); if(!el) return;
  const st = REG.st || await regCall('status');
  if(!st.can_publish){
    el.innerHTML = `<p class="mut">${esc(st.next||'Sign in above to publish.')}</p>`; return;
  }
  const can = REG.pub || (REG.pub = await regCall('publishables'));
  const kinds = ['app','agent','skill','soul','tool'];
  el.innerHTML = `<div class="reg-form">
      <label>What<select id="rp-kind">${kinds.map(k=>`<option value="${k}">${REG_KINDS.find(x=>x[0]===k)[1].replace(/s$/,'')}</option>`).join('')}</select></label>
      <label>Which<select id="rp-item"></select></label>
      <button class="pact" id="rp-check">Check it</button>
    </div>
    <p class="sub mut">Checking reads the package on this machine. Nothing is sent until you press Publish.</p>
    <div id="rp-rep"></div>`;
  const fill = ()=>{
    const k = el.querySelector('#rp-kind').value;
    const list = can[k]||[];
    el.querySelector('#rp-item').innerHTML = list.length ? list.map(x=>`<option value="${esc(x.id)}">${esc(x.name)}</option>`).join('')
      : '<option value="">nothing of this kind here yet</option>';
    el.querySelector('#rp-rep').innerHTML='';
  };
  el.querySelector('#rp-kind').onchange = fill; fill();
  el.querySelector('#rp-check').onclick = regCheck;
}

async function regCheck(){
  const el = document.getElementById('rp-rep');
  const kind = document.getElementById('rp-kind').value, item = document.getElementById('rp-item').value;
  el.innerHTML = '<p class="mut">Reading it for anything secret or personal…</p>';
  const rep = REG.rep = await regCall('report',{kind, item});
  if(rep.error && !rep.report){ el.innerHTML = `<div class="ghint" style="border-color:var(--err)">${esc(rep.error)}</div>`; return }
  const r = rep.report || rep;
  const next = rep.latest ? regBump(rep.latest) : '1.0.0';
  el.innerHTML = regReportHTML(r) + (r.ok ? `<div class="reg-form reg-meta-form">
      <label>Address<input id="rp-slug" value="${esc(rep.slug||'')}" maxlength="64"></label>
      <label>Version<input id="rp-ver" value="${esc(next)}" maxlength="20"></label>
      <label class="wide">One line on what it does<input id="rp-sum" maxlength="280"></label>
      <label class="wide">What changed${rep.latest?` since ${esc(rep.latest)}`:''}<input id="rp-notes" maxlength="2000"></label>
    </div>
    ${r.warnings.length?`<label class="reg-ack"><input type="checkbox" id="rp-ok"><span>I’ve read the personal details marked ! and they’re fine to share</span></label>`:''}
    <div class="prow"><span class="mut grow">Anyone will be able to download it from bentoboxos.com.</span>
      <button class="save" id="rp-go" ${r.warnings.length?'disabled':''}>Publish ${esc(kind)}</button></div>` : '');
  const ok = document.getElementById('rp-ok'), go = document.getElementById('rp-go');
  if(ok) ok.onchange = ()=>{go.disabled = !ok.checked};
  if(go) go.onclick = regPublish;
}

function regBump(v){ const p = String(v).split('.').map(n=>parseInt(n,10)||0); while(p.length<3)p.push(0); p[2]++; return p.join('.') }

async function regPublish(){
  const rep = REG.rep; if(!rep) return;
  const go = document.getElementById('rp-go'); go.disabled = true; go.textContent = 'Publishing…';
  const d = await regCall('publish',{ack:rep.ack, slug:document.getElementById('rp-slug').value.trim(),
    version:document.getElementById('rp-ver').value.trim(), name:rep.name,
    summary:document.getElementById('rp-sum').value.trim(), notes:document.getElementById('rp-notes').value.trim(),
    understood:!!(document.getElementById('rp-ok')||{}).checked});
  if(d.error){ go.disabled=false; go.textContent='Publish'; return toast(d.error,{kind:'err'}) }
  document.getElementById('rp-rep').innerHTML = `<div class="ghint reg-done">✓ Published <b>${esc(d.kind)}/${esc(d.slug)} ${esc(d.version)}</b> as ${esc(d.publisher)}.
    <a href="${esc(d.page)}" target="_blank" rel="noopener">See it on bentoboxos.com</a></div>`;
  REG.rep = null; regSearch();
}
