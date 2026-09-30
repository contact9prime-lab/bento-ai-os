/* ================= Settings → System → Cloud standby (agentos/standby.py) =================
   Your machine works; a paired cloud machine keeps a sealed copy and takes over only while
   yours can't be reached, then hands the work back. This pane pairs the two, shows how
   fresh the copy is, and has the deliberate moves (Move to the cloud, Bring it back).
   Faces: GUI and SUI are this pane plus the standing-by page the server shows in place of
   the desktop on whichever side is not working. The TUI is `bento standby`, which pairs
   and reads with the server down. */
var STANDBY=STANDBY||{d:null};
function sbAgo(t){if(!t)return 'never';const s=Math.max(0,Math.round(Date.now()/1000-t));
  return s<60?s+'s ago':s<3600?Math.floor(s/60)+' min ago':s<86400?Math.floor(s/3600)+' h ago':Math.floor(s/86400)+' days ago'}
async function paintStandby(){
  const el=document.getElementById('sb-box');if(!el)return;
  let d;try{d=await apiJSON('/api/standby')}catch(e){el.innerHTML=`<span class="mut">${esc(e.message)}</span>`;return}
  STANDBY.d=d;
  if(!d.admin){el.innerHTML='<span class="mut">Only an admin can set this up, because it moves the whole machine.</span>';return}
  const vn=d.version_note?`<p class="bk-bad">${esc(d.version_note)}</p>`:'';
  if(!d.role){
    el.innerHTML=`<div class="bk-box">
      <b>Pair with a cloud machine</b>
      <span class="mut">On the cloud machine, open this pane and press Show a code, or run <code>bento standby wait</code>.</span>
      <div class="bk-pws"><input id="sb-url" placeholder="https://your-cloud-bento" autocomplete="off" spellcheck="false">
        <input id="sb-code" placeholder="Code, like K7QM-4XPD" autocomplete="off" spellcheck="false" style="text-transform:uppercase"></div>
      <div><button class="endbtn" onclick="standbyPair(this)">Pair</button></div></div>
    <div class="bk-box" style="margin-top:14px">
      <b>Or make this machine the standby</b>
      <div id="sb-offer"><button class="endbtn" onclick="standbyOffer(this)">Show a code</button></div></div>`;
    return}
  if(d.role==='primary'){
    const sp=d.split&&d.split.path?`<div class="bk-done" style="background:color-mix(in srgb,var(--warn,#e6a23c) 14%,transparent)">
      <b>Both machines worked while they were apart.</b> This machine kept its own. The cloud's copy from ${sbAgo(d.split.at)} is saved.
      <div style="margin-top:6px"><button class="endbtn" onclick="standbyAct('/api/standby/adopt',this,'Switch to the cloud\\u2019s copy? What is here now is kept aside.')">Use the cloud's copy</button>
      <button class="endbtn" onclick="standbyAct('/api/standby/keep',this)">Keep mine</button></div></div>`:'';
    const sw=d.last_swap&&d.last_swap.at&&Date.now()/1000-d.last_swap.at<86400?`<p class="mut">Brought the work back from ${esc(d.last_swap.from||d.peer_host)} ${sbAgo(d.last_swap.at)}.${(d.last_swap.notes||[]).map(n=>' '+esc(n)).join('')}</p>`:'';
    el.innerHTML=`<div class="bk-box">${sp}
      <span><b>${esc(d.peer_host)}</b> stands by at <code>${esc(d.url)}</code></span>
      <span class="mut">Heard back ${sbAgo(d.last_contact)} · last copy ${sbAgo(d.last_push)}${d.last_push_bytes?`, ${bkSize(d.last_push_bytes)}`:''}</span>
      ${d.last_error?`<p class="bk-bad">${esc(d.last_error)}</p>`:''}${d.workspace_note?`<span class="mut">${esc(d.workspace_note)}</span>`:''}${vn}${sw}
      <label class="bk-ws"><input type="checkbox" id="sb-ws" ${d.workspace?'checked':''} onchange="standbySet({workspace:this.checked})"> Include your workspace folder in the copies</label>
      <div><button class="endbtn" onclick="standbyAct('/api/standby/copy',this)">Copy now</button>
      <button class="endbtn" onclick="standbyAct('/api/standby/move',this,'Hand over to ${esc(d.peer_host)} now? It carries on with your missions and channels, and this machine waits until you bring it back.')">Move to the cloud now</button>
      <button class="endbtn" onclick="standbyAct('/api/standby/off',this,'Unpair the two machines? The cloud forgets its copies.')">Unpair</button></div></div>`;
    return}
  // the standby, while it is the one working (a quiet standby shows its own page instead)
  const g=Math.round((d.grace||300)/60);
  el.innerHTML=`<div class="bk-box">
    <span>This machine stands by for <b>${esc(d.peer_host)}</b>.</span>
    ${d.active?`<span>It is the one working now, since ${sbAgo(d.since)}. ${esc(d.reason||'')} It hands the work back when ${esc(d.peer_host)} returns.</span>`:
      `<span class="mut">Heard from it ${sbAgo(d.last_beat)} · newest copy ${sbAgo(d.copy_at)}</span>`}
    ${(d.notes||[]).map(n=>`<span class="mut">${esc(n)}</span>`).join('')}${vn}
    <label class="bk-ws">Take over after <select id="sb-grace" onchange="standbySet({grace:this.value*60})">${[2,5,15,60].map(m=>`<option value="${m}" ${m===g?'selected':''}>${m} min</option>`).join('')}</select> of silence</label>
    <label class="bk-ws"><input type="checkbox" ${d.auto?'checked':''} onchange="standbySet({auto:this.checked})"> Take over by itself</label>
    <div><button class="endbtn" onclick="standbyAct('/api/standby/off',this,'Unpair? This machine forgets the copies it holds.')">Unpair</button></div></div>`;
}
async function standbyPost(url,body){
  const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
  const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||'HTTP '+r.status);return d}
async function standbyPair(btn){
  const url=document.getElementById('sb-url').value.trim(),code=document.getElementById('sb-code').value.trim();
  if(!url||!code)return toast('Give the cloud machine’s address and its code',{kind:'warn'});
  btn.disabled=true;btn.textContent='Pairing…';
  try{const d=await standbyPost('/api/standby/pair',{url,code});toast(`Paired. ${d.peer_host} now stands by for this machine.`);paintStandby()}
  catch(e){toast('Not paired: '+e.message,{kind:'err'})}finally{btn.disabled=false;btn.textContent='Pair'}
}
async function standbyOffer(btn){
  btn.disabled=true;
  try{const d=await standbyPost('/api/standby/offer');
    document.getElementById('sb-offer').innerHTML=`<div class="bk-done"><b style="font-size:20px;letter-spacing:2px">${esc(d.code)}</b>
      <p class="mut">Type it on your own machine with this machine's address. It works once, for ten minutes.</p></div>`}
  catch(e){btn.disabled=false;toast(e.message,{kind:'err'})}
}
async function standbySet(body){
  try{await standbyPost('/api/standby/settings',body);toast('Saved')}catch(e){toast('Not saved: '+e.message,{kind:'err'})}
  paintStandby();
}
async function standbyAct(url,btn,ask){
  if(ask&&!await osConfirm(ask,'',{confirmText:btn.textContent}))return;
  const label=btn.textContent;btn.disabled=true;btn.textContent='Working…';
  try{const d=await standbyPost(url);
    if(d.restart){toast((d.message||'Done.')+' Bento is restarting.');setTimeout(()=>location.reload(),9000);return}
    toast(d.message||(d.sent?`Copy sent (${bkSize(d.bytes)})`:(d.why?'No copy needed: '+d.why:'Done.')));paintStandby()}
  catch(e){toast(e.message,{kind:'err'})}finally{btn.disabled=false;btn.textContent=label}
}
