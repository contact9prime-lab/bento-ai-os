/* ================= Settings → System → Backup (agentos/backup.py) =================
   One encrypted file with the whole machine, to keep safe or carry to another one.
   Making one is a download; restoring is two steps, because a running server must not
   have its home swapped from under it: the file is uploaded and CHECKED in full (the
   server unpacks it into a staging folder), and only then does "Restart and restore"
   restart Bento, which swaps it in before anything opens the home.
   Faces: GUI and SUI are this page. The TUI is `bento backup` / `bento restore`, which
   need no server at all. A remote browser can make a backup (it is sealed with the
   passphrase) but cannot restore: that replaces the whole machine, so it is started at
   the machine itself, and the row says so instead of offering a button that refuses. */
function bkSize(n){n=+n||0;return n>=1e9?(n/1e9).toFixed(1)+' GB':n>=1e6?(n/1e6).toFixed(1)+' MB':n>=1e3?Math.round(n/1e3)+' KB':n+' bytes'}
async function paintBackup(){
  const mk=document.getElementById('bk-make'),rs=document.getElementById('bk-restore');if(!mk||!rs)return;
  let d;
  try{d=await apiJSON('/api/backup')}catch(e){mk.innerHTML=rs.innerHTML=`<span class="mut">${esc(e.message)}</span>`;return}
  BACKUP.info=d;
  backupOffsite(d.offsite);
  const last=document.getElementById('bk-last');
  if(last&&d.last&&d.last.restored_at){
    const r=d.last;
    last.innerHTML=`<div class="bk-done"><b>Restored from ${esc(r.from_host||'another machine')}</b>
      <span class="mut">${new Date(r.created*1000).toLocaleString()} backup${r.accounts&&r.accounts.length?', accounts: '+esc(r.accounts.join(', ')):''}</span>
      ${r.attention&&r.attention.length?`<ul>${r.attention.map(a=>`<li>${esc(a)}</li>`).join('')}</ul>`:''}
      <button class="endbtn" onclick="backupSeen()">OK</button></div>`;
  }
  if(!d.admin){
    mk.innerHTML='<span class="mut">Only an admin can back up this machine, because the file holds every account.</span>';
    rs.innerHTML='<span class="mut">Only an admin can restore over this machine.</span>';return}
  const p=d.plan||{};
  mk.innerHTML=`<div class="bk-box">
    <span class="mut">${p.files||0} files, ${bkSize(p.bytes)}${p.accounts?`, ${p.accounts} account${p.accounts===1?'':'s'}`:''}</span>
    <div class="bk-pws">${secretField('bk-pw','Passphrase')}${secretField('bk-pw2','The same again')}</div>
    ${p.workspace?`<label class="bk-ws"><input type="checkbox" id="bk-ws" checked> Include your workspace <code>${esc(p.workspace)}</code> (${bkSize(p.workspace_bytes)})</label>`:''}
    <div><button class="endbtn" onclick="backupMake(this)">Download backup</button> <span class="mut" id="bk-make-msg">At least ${d.min} characters. Nothing else opens it.</span></div></div>`;
  if(!d.local){
    rs.innerHTML='<span class="mut">A restore replaces this whole machine, so start it on the machine itself, or with <code>bento restore</code>.</span>';return}
  if(d.pending&&d.pending.staging){
    rs.innerHTML=`<div class="bk-box"><span>A backup from <b>${esc(d.pending.host||'another machine')}</b> is checked and ready.</span>
      <div><button class="endbtn" onclick="backupApply(this)">Restart and restore</button>
      <button class="endbtn" onclick="backupCancel()">Cancel</button></div></div>`;return}
  rs.innerHTML=`<div class="bk-box">
    <input type="file" id="bk-file" accept=".bento">
    <div class="bk-pws">${secretField('bk-rpw','Its passphrase')}</div>
    <div><button class="endbtn" onclick="backupCheck(this)">Check it</button> <span class="mut" id="bk-check-msg"></span></div>
    <div id="bk-out"></div></div>`;
}
var BACKUP=BACKUP||{info:null};
/* Is a copy kept anywhere else (offsite.py)? A backup on this disk is lost with it, and one that
   ransomware can reach is locked with everything else. The line and its doors: a cloud standby,
   a bucket (Put Bento in the cloud), or a file downloaded to another disk. */
function backupOffsite(o){
  const el=document.getElementById('bk-offsite');if(!el)return;
  if(!o){el.hidden=true;return}
  const icon={ok:'✓',warn:'!',bad:'⚠'}[o.level]||'·';
  const go={standby:'sb-box',cloud:'cd-box',backup:'bk-make'};
  el.hidden=false;el.className='bk-offsite '+(o.level||'');
  el.innerHTML=`<div class="bk-off-line"><b aria-hidden="true">${icon}</b> <span>${esc(o.line||'')}</span></div>
    ${o.level!=='ok'&&(o.doors||[]).length?`<div class="bk-off-doors">${o.doors.map(x=>
      `<button class="endbtn" data-go="${esc(go[x.id]||'')}" title="${esc(x.why)}">${esc(x.label)}</button>`).join('')}</div>`:''}`;
  el.querySelectorAll('[data-go]').forEach(b=>b.onclick=()=>{
    const t=document.getElementById(b.dataset.go);if(!t)return;
    if(typeof setSubReveal==='function')setSubReveal(t);
    t.scrollIntoView({block:'center',behavior:'smooth'});
    const f=t.querySelector('input,button');if(f)f.focus({preventScroll:true})});
}
async function backupMake(btn){
  const pw=document.getElementById('bk-pw').value,pw2=document.getElementById('bk-pw2').value,msg=document.getElementById('bk-make-msg');
  const min=(BACKUP.info&&BACKUP.info.min)||8;
  if(pw.length<min)return toast(`Choose a passphrase of at least ${min} characters`,{kind:'warn'});
  if(pw!==pw2)return toast('The two passphrases are different',{kind:'warn'});
  const ws=document.getElementById('bk-ws');
  btn.disabled=true;btn.textContent='Making it…';if(msg)msg.textContent='this can take a while for a big workspace';
  try{
    const r=await fetch('/api/backup',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({passphrase:pw,workspace:ws?ws.checked:true})});
    if(!r.ok){const e=await r.json().catch(()=>({}));throw new Error(e.error||'HTTP '+r.status)}
    const cd=r.headers.get('content-disposition')||'',m=cd.match(/filename="?([^";]+)"?/);
    const blob=await r.blob(),a=document.createElement('a');
    a.href=URL.createObjectURL(blob);a.download=m?m[1]:'bento-backup.bento';document.body.appendChild(a);a.click();
    setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},4000);
    document.getElementById('bk-pw').value=document.getElementById('bk-pw2').value='';
    toast(`Backup saved (${bkSize(blob.size)}). Keep the passphrase somewhere safe: nothing else opens it.`);
    if(msg)msg.textContent='';
  }catch(e){toast('No backup was made: '+e.message,{kind:'err'});if(msg)msg.textContent=''}
  finally{btn.disabled=false;btn.textContent='Download backup'}
}
async function backupCheck(btn){
  const f=document.getElementById('bk-file'),pw=document.getElementById('bk-rpw').value,out=document.getElementById('bk-out');
  if(!f||!f.files||!f.files[0])return toast('Choose the .bento file first',{kind:'warn'});
  if(!pw)return toast('Type the passphrase it was made with',{kind:'warn'});
  btn.disabled=true;btn.textContent='Checking…';
  try{
    const r=await fetch('/api/restore',{method:'POST',body:f.files[0],
      headers:{'Content-Type':'application/octet-stream','X-Bento-Passphrase':encodeURIComponent(pw)}});
    const d=await r.json().catch(()=>({}));
    if(!r.ok)throw new Error(d.error||'HTTP '+r.status);
    out.innerHTML=`<div class="bk-done"><b>It checks out.</b> ${d.files} files${d.accounts&&d.accounts.length?', accounts: '+esc(d.accounts.join(', ')):''}.
      ${d.attention&&d.attention.length?`<ul>${d.attention.map(a=>`<li>${esc(a)}</li>`).join('')}</ul>`:''}</div>`;
    paintBackup();
  }catch(e){out.innerHTML=`<p class="bk-bad">${esc(e.message)}</p>`}
  finally{btn.disabled=false;btn.textContent='Check it'}
}
async function backupApply(btn){
  if(!await osConfirm('Restore this backup?','Bento restarts and swaps it in. What is here now is kept aside, not deleted.',{confirmText:'Restart and restore'}))return;
  btn.disabled=true;btn.textContent='Restarting…';
  try{
    const r=await fetch('/api/restore/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirm:true})});
    const d=await r.json().catch(()=>({}));
    if(!r.ok)throw new Error(d.error||'HTTP '+r.status);
  }catch(e){btn.disabled=false;btn.textContent='Restart and restore';return toast('Nothing was restored: '+e.message,{kind:'err'})}
  toast('Restoring. Bento will be back in a moment.');
  // wait for it to go and come back, then load the restored machine
  const t0=Date.now();let gone=false;
  const poll=async()=>{
    try{const r=await fetch('/api/platform',{cache:'no-store'});if(r.ok&&gone)return location.reload()}catch(e){gone=true}
    if(Date.now()-t0>1500)gone=true;
    if(Date.now()-t0<120000)setTimeout(poll,1500);else location.reload();
  };
  setTimeout(poll,2500);
}
async function backupCancel(){
  try{await fetch('/api/restore',{method:'DELETE'})}catch(e){}
  paintBackup();
}
async function backupSeen(){
  try{await fetch('/api/backup/last',{method:'DELETE'})}catch(e){}
  const l=document.getElementById('bk-last');if(l)l.innerHTML='';
}

/* Settings → System → Encrypted at rest: whether the databases are encrypted with this
   machine's key (dbcrypt.py) and whether the disk is (diskcrypt.py). Two lines, each with what
   it covers; read on every paint, never assumed. */
async function paintAtRest(){
  const el=document.getElementById('ar-box');if(!el)return;
  let d;
  try{d=await apiJSON('/api/at-rest')}catch(e){el.textContent=e.message||'could not read it';return}
  const mk=(t,c,txt)=>{const e=document.createElement(t);if(c)e.className=c;if(txt!=null)e.textContent=txt;return e};
  const row=(icon,level,title,line,detail)=>{
    const r=mk('div','ar-row '+level);
    r.append(mk('b','ar-i',icon));
    const t=mk('div','ar-t');t.append(mk('div','ar-h',title),mk('div','ar-l',line));
    if(detail)t.append(mk('div','ar-d mut',detail));
    r.append(t);return r};
  const db=d.db||{},dk=d.disk||{};
  const dbl=db.state==='encrypted'?'ok':'warn';
  const kids=[row(dbl==='ok'?'✓':'!',dbl,'Databases',db.line||'',db.detail||'')];
  const dkl={on:'ok',off:'warn'}[dk.state]||'warn';
  kids.push(row({on:'✓',off:'!'}[dk.state]||'?',dkl,'Disk',dk.line||'',
    dk.state==='off'?'Turn it on in your system’s settings: FileVault on a Mac, LUKS when Linux is installed, BitLocker on Windows.':''));
  el.replaceChildren(...kids);
}
