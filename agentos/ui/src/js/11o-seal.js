/* ================= Your secrets: sealed with your password (seal.py) ======================
   Each account's vault and website sign-ins are locked with a key made from that person's
   password. While they're signed in, half of it sits in this browser's cookie and half on the
   server, so neither alone opens anything. This file is the desktop's part:
   - `seal_need` (09-websocket.js) asks this page to lend its half to one mission step;
   - after a server restart the server holds no half, so the card (and one toast) asks for the
     password once;
   - a recovery code is shown once, by `sealShowCode`, when an account is first sealed here
     (the first account made from the desktop) or a new one is asked for.
   Faces: GUI and SUI, this card and the sign-in page (login.html). TUI: `bento vault`, which
   says the vault is sealed and that it opens from a signed-in browser.
   `var`, not `let`: the bundle's TDZ trap. */
var SEAL={st:null,told:false};

async function sealLoad(){
  try{SEAL.st=await apiJSON('/api/seal')}catch(e){SEAL.st=null}
  return SEAL.st;
}

/* One step of a mission needs the key and this page is the person's: lend this browser's half
   (the cookie goes with the request; script never reads it). Said in a quiet toast. */
async function sealLend(ev){
  try{
    const r=await fetch('/api/seal/lend',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ticket:ev.ticket})});
    const d=await r.json().catch(()=>({}));
    if(d.ok&&ev.why)toast('Opened for a mission: '+ev.why,{kind:'info'});
  }catch(e){}
}

/* The code is shown once and never stored: copy it, download it, and say it was kept. */
function sealShowCode(code,why){
  return new Promise(res=>{
    const mk=(t,c,txt)=>{const e=document.createElement(t);if(c)e.className=c;if(txt!=null)e.textContent=txt;return e};
    const scr=mk('div','dlg-scrim');const dlg=mk('div','dlg seal-dlg');dlg.setAttribute('role','dialog');
    dlg.setAttribute('aria-modal','true');
    const ok=mk('button','dlg-ok','Continue');ok.disabled=true;
    const tick=document.createElement('input');tick.type='checkbox';tick.onchange=()=>{ok.disabled=!tick.checked};
    const lab=mk('label','seal-tick');lab.append(tick,mk('span','',"I've saved it somewhere safe. Bento won't show it again."));
    const copy=mk('button','dlg-cancel','Copy');
    copy.onclick=async()=>{try{await navigator.clipboard.writeText(code);copy.textContent='Copied'}catch(e){copy.textContent='Select it and copy'}};
    const save=mk('button','dlg-cancel','Download');
    save.onclick=()=>{const a=document.createElement('a');a.download='bento-recovery-code.txt';
      a.href=URL.createObjectURL(new Blob(['Bento recovery code\n\n'+code+'\n\nKeep this somewhere safe, away from this computer.\n'],{type:'text/plain'}));
      document.body.append(a);a.click();a.remove()};
    const row=mk('div','dlg-b');row.append(copy,save);
    dlg.append(mk('div','dlg-icn','🔑'),mk('div','dlg-t','Save your recovery code'),mk('div','dlg-m',why||''),
      (()=>{const c=mk('div','seal-code');code.split('-').forEach((g,i,a)=>c.append(mk('span','',g+(i<a.length-1?'-':''))));return c})(),row,lab,(()=>{const b=mk('div','dlg-b');b.append(ok);return b})());
    scr.append(dlg);document.body.append(scr);
    ok.onclick=()=>{scr.remove();res(true)};
    tick.focus();
  });
}

/* Settings → Accounts → Your secrets */
async function renderSeal(){
  const box=document.getElementById('seal-card');if(!box)return;
  const st=await sealLoad();
  if(!st){box.replaceChildren();return}
  const mk=(t,c,txt)=>{const e=document.createElement(t);if(c)e.className=c;if(txt!=null)e.textContent=txt;return e};
  const g=mk('div','pgroup chan');g.dataset.f='secrets sealed vault password recovery code encrypted';
  g.append(mk('h3','','Your secrets'));
  const hint=mk('div','ghint',st.detail||'');g.append(hint);
  if(st.sealed){
    const row=(title,sub,ctl)=>{const r=mk('div','prow');const l=mk('div','pl');l.append(mk('b','',title),mk('small','',sub));
      const c=mk('div','pc');if(ctl)c.append(...ctl);r.append(l,c);return r};
    if(!st.open){
      const pw=document.createElement('input');pw.type='password';pw.placeholder='Your password';pw.autocomplete='current-password';
      const b=mk('button','endbtn','Open');
      b.onclick=async()=>{b.disabled=true;
        try{await apiJSON('/api/seal/open',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw.value})});
          toast('✓ Your secrets are open while you’re signed in');renderSeal()}
        catch(e){toast(e.message||'that did not open it',{kind:'err'})}finally{b.disabled=false}};
      pw.onkeydown=e=>{if(e.key==='Enter')b.click()};
      g.append(row('Closed since Bento restarted','Enter your password once to let your missions use them again.',[pw,b]));
    }else{
      g.append(row('Open while you’re signed in','Missions can use them while a page of yours is open, even locked.'));
    }
    const when=st.code_at?new Date(st.code_at*1000).toLocaleDateString(undefined,{day:'numeric',month:'short',year:'numeric'}):'';
    const nb=mk('button','endbtn','New code');
    nb.onclick=async()=>{
      const pw=await sealAskPassword('A new recovery code','The old one stops working. Enter your password to make a new one.');
      if(!pw)return;
      try{const d=await apiJSON('/api/seal/code',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw})});
        await sealShowCode(d.recovery_code,'This replaces your old recovery code. If you forget your password, it is the only way back to your saved passwords and website sign-ins.');
        renderSeal()}catch(e){toast(e.message||'could not make a new code',{kind:'err'})}};
    g.append(row('Recovery code',when?'Made '+when+'. Shown once, never kept on this machine.':'Shown once, never kept on this machine.',[nb]));
  }
  box.replaceChildren(g);
}

function sealAskPassword(title,msg){
  return new Promise(res=>{
    const mk=(t,c,txt)=>{const e=document.createElement(t);if(c)e.className=c;if(txt!=null)e.textContent=txt;return e};
    const scr=mk('div','dlg-scrim');const dlg=mk('div','dlg');
    const pw=document.createElement('input');pw.type='password';pw.placeholder='Your password';pw.className='seal-pw';
    const ok=mk('button','dlg-ok','Continue'),no=mk('button','dlg-cancel','Cancel');
    const b=mk('div','dlg-b');b.append(no,ok);
    dlg.append(mk('div','dlg-t',title),mk('div','dlg-m',msg),pw,b);scr.append(dlg);document.body.append(scr);
    const done=v=>{scr.remove();res(v)};
    ok.onclick=()=>done(pw.value);no.onclick=()=>done('');
    pw.onkeydown=e=>{if(e.key==='Enter')done(pw.value);if(e.key==='Escape')done('')};
    pw.focus();
  });
}

/* Once per page: a sealed account whose server forgot its half (a restart) is told where to
   open it, with the door. Quiet otherwise. */
async function sealBoot(){
  const st=await sealLoad();
  if(!st||!st.sealed||st.open||SEAL.told)return;
  SEAL.told=true;
  toast('Bento restarted, so your saved passwords and website sign-ins are closed. Enter your password once to open them.',
    {label:'Open',go:()=>{if(typeof placeSettings==='function')placeSettings('accounts','Your secrets')()}});
}
