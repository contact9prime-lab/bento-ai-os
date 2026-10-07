/* ================= Settings → System → Put Bento in the cloud (agentos/clouddeploy.py) =================
   Asked for as "deploy it quickly to the cloud, really quick and noob for anyone, so sso and
   done". The card is the Render button (sign in with GitHub or Google, type a password on
   their page, press Deploy) with a password suggestion beside it, the other ways folded under
   it, and the two things to do once it is up, which are the panes right below this one.
   Nothing here deploys: it opens the host's page.
   Faces: GUI and SUI are this card (a link opens in the host's browser at the machine and in
   this browser from a phone, the fileOpen rule). The TUI is `bento cloud`, the same list. */
var CLOUDDEP=CLOUDDEP||{d:null};

async function paintCloudDeploy(){
  const el=document.getElementById('cd-box');if(!el)return;
  let d;try{d=await apiJSON('/api/cloud/deploy')}catch(e){el.innerHTML=`<span class="mut">${esc(e.message)}</span>`;return}
  CLOUDDEP.d=d;
  const opts=d.options||[];
  const top=opts.find(o=>o.recommended)||opts[0];
  const rest=opts.filter(o=>o!==top);
  CLOUDDEP.url=top.url;
  const steps=o=>`<ol class="cd-steps">${(o.steps||[]).map(s=>`<li>${o.kind==='commands'
      ?`<code>${esc(s)}</code>`:esc(s)}</li>`).join('')}</ol>`;
  /* This machine, when it is a cloud machine whose host forgets its disk (keep.py):
     where its memory is kept, or the plain fact that it forgets. */
  const h=d.here||{};
  const here=h.line?`<div class="bk-box cd-here cd-${esc(h.kind||'')}">
      <span><b>This machine</b></span>
      <span>${esc(h.line)}</span>
      ${h.saved_at?`<span class="mut">Saved ${sbAgo(h.saved_at)}${h.saved_bytes?`, ${bkSize(h.saved_bytes)}`:''}${h.restored_at?` · brought back ${sbAgo(h.restored_at)}`:''}</span>`:''}
      ${h.restore_note&&!h.saved_at?`<span class="mut">${esc(h.restore_note)}</span>`:''}
      <div>${h.enabled?`<button class="endbtn" onclick="cloudKeepSave(this)">Save now</button>`:''}
        ${h.url?`<button class="endbtn" onclick="cloudDeployOpen(${JSON.stringify(h.url).replace(/"/g,'&quot;')})">Open on GitHub</button>`:''}
        ${!h.enabled&&h.token_link?`<button class="endbtn" onclick="cloudDeployOpen(${JSON.stringify(h.token_link).replace(/"/g,'&quot;')})">Make a GitHub key</button>`:''}</div>
    </div>`:'';
  CLOUDDEP.key=top.key_url||'';
  el.innerHTML=`${here}<div class="bk-box">
      <span><b>${esc(top.title)}</b> <span class="mut">· ${top.free?'free':'easiest'}</span></span>
      <span class="mut">${esc(top.how)}</span>
      ${top.key_url?`<div class="cd-step"><span class="mut">1. A GitHub key for its memory. Choose No expiration, then Generate token.</span>
        <div><button class="endbtn" onclick="cloudDeployOpen(CLOUDDEP.key)">Make a GitHub key</button></div></div>`:''}
      <div class="cd-pass"><span class="mut">${top.key_url?'2. ':''}A password you could use</span>
        <span class="cd-pass-row"><input id="cd-pw" readonly value="${esc(d.passphrase)}" spellcheck="false">
          <button class="endbtn" onclick="cloudDeployCopy()">Copy</button>
          <button class="endbtn" title="Another one" onclick="paintCloudDeploy()">↻</button></span></div>
      <div class="cd-step">${top.key_url?'<span class="mut">3. Paste both on Render\u2019s page.</span>':''}
        <div><button class="save cd-go" onclick="cloudDeployOpen(CLOUDDEP.url)">Deploy on ${esc(top.title)}</button></div></div>
      <span class="mut">${esc(top.costs)} ${pInfo((top.steps||[]).join(' '))}</span>
    </div>
    <details class="cd-more"><summary>Other ways</summary>
      ${rest.map(o=>`<div class="cd-way"><b>${esc(o.title)}</b> <span class="mut">${esc(o.how)}</span>
        ${steps(o)}<span class="mut">${esc(o.costs)}${o.https?'':' No HTTPS of its own.'}</span></div>`).join('')}
      <div class="cd-way"><b>Not offered</b>${Object.entries(d.not_offered||{}).map(([k,v])=>
        `<span class="mut">${esc(k)}: ${esc(v)}</span>`).join('')}</div>
    </details>
    <div class="cd-after"><span class="mut">Once it's up</span>
      <div><button class="endbtn" onclick="cloudDeployGo('sb-box')">Pair it as your standby</button>
        <button class="endbtn" onclick="cloudDeployGo('bk-make')">Move this machine there</button></div></div>`;
}

/* At the machine the host's own browser opens it; from a phone, this browser does,
   because the host's would open in another room. */
function cloudDeployOpen(url){
  if(typeof remoteClient==='function'&&remoteClient()){window.open(url,'_blank','noopener');return}
  openHost({url});
}

/* navigator.clipboard exists only on HTTPS or localhost; a phone on the LAN over plain
   HTTP has none, so fall back to selecting the text and the old copy command. */
function cloudDeployCopy(){
  const i=document.getElementById('cd-pw');if(!i)return;
  const done=()=>toast('password copied');
  if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(i.value).then(done,()=>{});return}
  i.focus();i.select();try{document.execCommand('copy');done()}catch(e){toast('select it and copy it yourself')}
}

async function cloudKeepSave(b){
  b.disabled=true;b.textContent='Saving…';
  try{const r=await fetch('/api/keep/save',{method:'POST'});const d=await r.json();
    if(!r.ok)throw new Error(d.error||'could not save');
    toast(d.saved?`Saved to GitHub (${bkSize(d.bytes)})`:'Nothing changed since the last save.');
  }catch(e){toast(e.message)}
  paintCloudDeploy();
}

function cloudDeployGo(id){
  const el=document.getElementById(id);
  if(el)el.scrollIntoView({behavior:'smooth',block:'center'});
}
