/* ================= Settings → System → Put Bento in the cloud (agentos/clouddeploy.py) =================
   Asked for as "deploy it quickly to the cloud, really quick and noob for anyone, so sso and
   done". The card is three steps: a free storage bucket for its memory (Backblaze B2 first,
   the others folded under it), a suggested password, and the Render button (sign in with
   GitHub or Google, fill in the boxes on their page, press Deploy). The other ways are folded
   under it, and the two things to do once it is up are the panes right below this one.
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
      ${h.enabled?`<div><button class="endbtn" onclick="cloudKeepSave(this)">Save now</button></div>`:''}
    </div>`:'';
  el.innerHTML=`${here}<div class="bk-box">
      <span><b>${esc(top.title)}</b> <span class="mut">· ${top.free?'free':'easiest'}</span></span>
      <span class="mut">${esc(top.how)}</span>
      ${top.storage?cloudStorageStep(top.storage):''}
      <div class="cd-pass"><span class="mut">${top.storage?'2. ':''}A password you could use</span>
        <span class="cd-pass-row"><input id="cd-pw" readonly value="${esc(d.passphrase)}" spellcheck="false">
          <button class="endbtn" onclick="cloudDeployCopy()">Copy</button>
          <button class="endbtn" title="Another one" onclick="paintCloudDeploy()">↻</button></span></div>
      <div class="cd-step">${top.storage?'<span class="mut">3. Fill in the password and the bucket on Render\u2019s page.</span>':''}
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

/* Step 1: where its memory is kept. The recommended service is a button; the others, and
   the steps for each, are folded under it so the card stays three lines tall. */
function cloudStorageStep(list){
  const top=list.find(p=>p.recommended)||list[0];
  CLOUDDEP.signup=top.signup;
  const how=p=>`<div class="cd-way"><b>${esc(p.name)}</b>${p.free?` <span class="mut">${esc(p.free)}. ${esc(p.card)}</span>`:''}
      <ol class="cd-steps">${p.steps.map(x=>`<li>${esc(x)}</li>`).join('')}<li>Endpoint: ${esc(p.endpoint)}</li></ol>
      ${p.signup?`<div><button class="endbtn" onclick="cloudDeployOpen(${JSON.stringify(p.signup).replace(/"/g,'&quot;')})">Open ${esc(p.name)}</button></div>`:''}</div>`;
  return `<div class="cd-step"><span class="mut">1. A free storage bucket for its memory. ${esc(top.name)}: ${esc(top.free)}. ${esc(top.card)}</span>
      <div><button class="endbtn" onclick="cloudDeployOpen(CLOUDDEP.signup)">Make a ${esc(top.name.split(' ')[0])} bucket</button>
        ${pInfo('Your password seals everything before it leaves the machine, so the storage only ever holds noise.')}</div>
      <details class="cd-more cd-how"><summary>How, and other storage</summary>${list.map(how).join('')}</details></div>`;
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
    toast(d.saved?`Saved to ${d.where} (${bkSize(d.bytes)})`:'Nothing changed since the last save.');
  }catch(e){toast(e.message)}
  paintCloudDeploy();
}

function cloudDeployGo(id){
  const el=document.getElementById(id);
  if(el)el.scrollIntoView({behavior:'smooth',block:'center'});
}
