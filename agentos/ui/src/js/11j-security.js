/* Settings → Permissions → Security: what the watcher knows (agentos/integrity.py, /api/security/status).
   Everything here is shown through text nodes. A file name and an alert's detail are whatever an
   attacker made them, and they come from another process's words. An admin may accept a hold here
   (agentos/holdclear.py): the card works out what the change is (/api/security/picture), asks for
   the admin's password, and for an unknown change the authenticator's code as well. A machine whose
   record is signed with a key still accepts only at its terminal, and the card says so.
   TUI: `bento integrity status|changes|accept|code`. SUI: the same page. Phones: Telegram and
   WhatsApp answer the hold themselves (show / accept / keep). */
function secEl(tag,cls,text){
  const e=document.createElement(tag);
  if(cls)e.className=cls;
  if(text!=null)e.textContent=String(text);
  return e;
}
function secRow(label,value,cls){
  const r=secEl('div','prow'+(cls?' '+cls:'')),pl=secEl('div','pl');
  pl.appendChild(secEl('b','',label));
  if(value)pl.appendChild(secEl('small','',value));
  r.appendChild(pl);
  return r;
}
function secWhen(t){
  try{return new Date(Number(t)*1000).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})}catch(e){return ''}
}
function secDetails(st){
  const out=[];
  out.push(secRow('Seal',st.sealed==='none'?'Not sealed. A change made while Bento is stopped goes unseen. Run bento integrity seal.'
    :st.sealed==='bad'?'The record does not check out.'
    :st.sealed==='signed'?'Sealed'+(st.at?' on '+secWhen(st.at):'')+'.'
    :'Sealed'+(st.at?' on '+secWhen(st.at):'')+', with no signature. A process running as this user could rewrite it.'));
  out.push(secRow('Signed',st.signed==='signed'?'By a key you keep off this machine.'
    :st.signed==='release'?'By the release key '+((st.update&&st.update.key_id)||'')+'.'
    :'Unsigned. Run bento integrity keygen to make a key that stays off this machine.'));
  out.push(secRow('Root lock',st.locked?'This user can\'t change the code.'+((st.open_parents&&st.open_parents.length)?' The folder above it is still this user\'s.':'')
    :'Off. Run bento integrity lock to stop this user changing its own gate.'));
  if(st.dev)out.push(secRow('Development checkout','Changed code only warns here, an agent\'s change included.'+((st.dev_changes&&st.dev_changes.length)?' Changed: '+st.dev_changes.slice(-5).join(', '):'')));
  const leds=st.ledgers||[];
  if(leds.length){
    const bad=leds.filter(l=>!l.ok);
    out.push(secRow('Ledger',bad.length?'A row was changed or removed: '+bad[0].reason:'Checked at start and every ten minutes. Intact.'));
  }
  return out;
}
var SEC_OPEN=false;
async function secCardPaint(){
  const box=document.getElementById('s-sec-card');if(!box)return;
  let st;
  try{st=await apiJSON('/api/security/status')}
  catch(e){const g=box.closest('.pgroup');if(g)g.hidden=true;return}
  const held=st.held,alerts=st.alerts||[],kids=[];
  const head=secEl('div','prow'+(held?' danger':'')),pl=secEl('div','pl');
  pl.appendChild(secEl('b','',held?'Agents are stopped':'Watching the code'));
  pl.appendChild(secEl('small','',(st.line||'').replace(/^Agents are stopped because /,'')));
  head.appendChild(pl);
  const more=secEl('button','endbtn',SEC_OPEN?'Less':'Details');
  more.onclick=()=>{SEC_OPEN=!SEC_OPEN;secCardPaint()};
  head.appendChild(more);
  kids.push(head);
  if(held)kids.push(await secHeldBox(held));
  if(alerts.length&&(SEC_OPEN||held)){
    const list=secEl('div','prow stack'),inner=secEl('div','pl');
    inner.appendChild(secEl('b','','Recent alerts'));
    alerts.slice(0,SEC_OPEN?10:3).forEach(a=>{
      const line=secEl('div','sec-alert');
      line.appendChild(secEl('span','mut',secWhen(a.at)+'  '));
      line.appendChild(secEl('span','',a.words||''));
      const d=[a.source,a.detail].filter(Boolean).join(': ');
      if(d)line.appendChild(secEl('small','',d));
      inner.appendChild(line);
    });
    list.appendChild(inner);kids.push(list);
  }
  if(SEC_OPEN){secDetails(st).forEach(r=>kids.push(r));kids.push(secCodeRow(st))}
  box.replaceChildren(...kids);
}

/* A hold: what it is, what changed, and the Accept form. */
var SEC_HOLD={changes:false,msg:'',busy:false};
const SEC_KIND={settled:'Back to normal',known:'Matches GitHub',unknown:'Unknown change'};
function secField(type,ph,id){
  // Never a type=password box (unless the browser can't draw dots): that made the browser take
  // Settings for a sign-in form and fill the saved username into the search box (11-settings.js
  // secretField, tests/test_speech.py). Here the box holds the account's password.
  const i=secEl('input','');i.placeholder=ph;i.id=id;
  i.autocomplete=type==='password'?'new-password':'one-time-code';
  if(type==='password'){
    const dots=typeof CSS!=='undefined'&&CSS.supports&&CSS.supports('-webkit-text-security','disc');
    i.type=dots?'text':'password';if(dots)i.className='secret-in';
    i.spellcheck=false;i.setAttribute('autocapitalize','off');i.setAttribute('autocorrect','off');
    i.setAttribute('data-1p-ignore','');i.setAttribute('data-lpignore','true');i.setAttribute('data-form-type','other');
  }else{i.type='text';i.inputMode='numeric';i.maxLength=7}
  return i;
}
async function secPost(path,body){
  return apiJSON(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
}
async function secHeldBox(held){
  const box=secEl('div','prow stack sec-held'),inner=secEl('div','pl');
  let pic=null;
  try{pic=await apiJSON('/api/security/picture')}catch(e){}
  inner.appendChild(secEl('b','',pic&&pic.kind?SEC_KIND[pic.kind]||'What changed':'What changed'));
  if(pic&&pic.words)inner.appendChild(secEl('small','',pic.words));
  const files=secEl('div','sec-files');
  (held.files||[]).slice(0,12).forEach(f=>files.appendChild(secEl('code','sec-file',f)));
  inner.appendChild(files);
  if(pic&&pic.changes){
    const t=secEl('button','endbtn sec-show',SEC_HOLD.changes?'Hide changes':'Show changes');
    t.onclick=()=>{SEC_HOLD.changes=!SEC_HOLD.changes;secCardPaint()};
    inner.appendChild(t);
    if(SEC_HOLD.changes)inner.appendChild(secEl('pre','sec-diff',pic.changes));
  }
  if(!pic){inner.appendChild(secEl('small','','Accept it at this machine\'s terminal: bento integrity accept'));box.appendChild(inner);return box}
  if(pic.needs_key){
    inner.appendChild(secEl('small','','This machine signs its record with a key, so accept it at its terminal: bento integrity accept --key <path>'));
    box.appendChild(inner);return box;
  }
  const form=secEl('div','sec-accept');
  if(pic.needs_password)form.appendChild(secField('password','Your password','s-sec-pw'));
  const unknown=pic.kind==='unknown';
  if(unknown&&pic.code_set)form.appendChild(secField('text','6-digit code','s-sec-code'));
  const go=secEl('button','endbtn primary','Accept and let agents run');
  go.disabled=SEC_HOLD.busy||(unknown&&!pic.code_set)||pic.paused;
  go.onclick=async()=>{
    const pw=document.getElementById('s-sec-pw'),code=document.getElementById('s-sec-code');
    SEC_HOLD.busy=true;SEC_HOLD.msg='';
    try{
      await secPost('/api/security/accept',{password:pw?pw.value:'',code:code?code.value:''});
      SEC_HOLD.changes=false;     // the security alert says it, on every admin's screen
    }catch(e){SEC_HOLD.msg=e.message||String(e)}
    SEC_HOLD.busy=false;secCardPaint();
  };
  form.appendChild(go);
  // Take it back: the code returns to its commit, copies kept aside (holdclear.undo). No code
  // needed, because it only goes towards a commit. Not offered for a locked home file, which git
  // can't put back, nor once it's settled. TUI: bento integrity undo.
  if(pic.kind!=='settled'&&!(pic.home&&pic.home.length)){
    const back=secEl('button','endbtn','Undo the change');
    back.disabled=SEC_HOLD.busy||pic.paused;
    back.onclick=async()=>{
      const pw=document.getElementById('s-sec-pw');
      SEC_HOLD.busy=true;SEC_HOLD.msg='';
      try{
        const got=await secPost('/api/security/undo',{password:pw?pw.value:''});
        SEC_HOLD.changes=false;
        toast(got.released?'Put back. Agents can run again.':(got.why||'Put back.'));
      }catch(e){SEC_HOLD.msg=e.message||String(e)}
      SEC_HOLD.busy=false;secCardPaint();
    };
    form.appendChild(back);
  }
  inner.appendChild(form);
  const note=unknown&&!pic.code_set?'Bento can\'t vouch for this change, so accepting it here needs an authenticator code. Undo needs only your password.'
    :pic.paused?'Too many wrong answers. Try again in 15 minutes.'
    :'Check what changed first. Undo puts the code back as it was committed and keeps a copy of the change.';
  inner.appendChild(secEl('small','sec-note',note));
  if(unknown&&!pic.code_set){
    const setup=secEl('button','endbtn sec-show','Set up a code');
    setup.onclick=async()=>{SEC_OPEN=true;await secCardPaint();const r=document.getElementById('s-sec-coderow');if(r)r.scrollIntoView({block:'center'})};
    inner.appendChild(setup);
  }
  if(SEC_HOLD.msg)inner.appendChild(secEl('small','sec-err',SEC_HOLD.msg));
  box.appendChild(inner);
  return box;
}

/* The authenticator code an unknown change needs, set up as four steps: an app, your password,
   a scan, and a check that the app's digits are right. The secret is shown once (holdclear.new_code)
   and drawn as a QR code (agentos/qr.py) with the key under it for a phone without a camera.
   TUI: `bento integrity code` prints the same square in half blocks. */
var SEC_CODE={shown:null,msg:'',ok:false,replace:false};
function secSteps(items,from){
  const ol=secEl('ol','sec-steps');ol.start=from||1;
  items.forEach(t=>ol.appendChild(secEl('li','',t)));
  return ol;
}
function secQR(q){
  const NS='http://www.w3.org/2000/svg',svg=document.createElementNS(NS,'svg');
  svg.setAttribute('viewBox','0 0 '+q.size+' '+q.size);svg.setAttribute('class','sec-qr');
  svg.setAttribute('role','img');svg.setAttribute('aria-label','QR code for your authenticator app');
  svg.setAttribute('shape-rendering','crispEdges');
  const bg=document.createElementNS(NS,'rect');bg.setAttribute('width',q.size);bg.setAttribute('height',q.size);bg.setAttribute('fill','#fff');
  const p=document.createElementNS(NS,'path');p.setAttribute('d',q.d);p.setAttribute('fill','#000');
  svg.appendChild(bg);svg.appendChild(p);return svg;
}
function secCodeShown(st){
  const s=SEC_CODE.shown,out=secEl('div','sec-setup');
  out.appendChild(secEl('small','sec-warn','Shown once. If you leave before scanning it, set it up again.'));
  out.appendChild(secSteps(['In the app, tap + and choose Scan a QR code, then point the camera at this square.'],3));
  if(s.qr&&s.qr.d)out.appendChild(secQR(s.qr));
  const alt=secEl('div','sec-key');
  alt.appendChild(secEl('small','','No camera? Choose Enter a setup key, type this key and pick Time based.'));
  const key=(s.secret||'').replace(/(.{4})/g,'$1 ').trim();
  alt.appendChild(secEl('code','sec-file',key));
  const copy=secEl('button','endbtn','Copy key');
  copy.onclick=async()=>{try{await navigator.clipboard.writeText(s.secret);copy.textContent='Copied'}catch(e){copy.textContent='Select it and copy'}};
  alt.appendChild(copy);
  if(s.uri&&/^otpauth:\/\//.test(s.uri)&&window.matchMedia&&matchMedia('(pointer:coarse)').matches){
    const a=secEl('a','endbtn','Open in my authenticator app');a.href=s.uri;alt.appendChild(a);
  }
  out.appendChild(alt);
  out.appendChild(secSteps(['Type the 6 digits the app shows for Bento, to check it works.'],4));
  const form=secEl('div','sec-accept');
  form.appendChild(secField('text','6-digit code','s-sec-check'));
  const b=secEl('button','endbtn primary','Check');
  b.onclick=async()=>{
    const c=document.getElementById('s-sec-check');
    try{await secPost('/api/security/code/check',{code:c?c.value:''});SEC_CODE.ok=true;SEC_CODE.msg=''}
    catch(e){SEC_CODE.msg=e.message||String(e)}
    secCardPaint();
  };
  form.appendChild(b);out.appendChild(form);
  return out;
}
function secCodeRow(st){
  const r=secEl('div','prow stack'),pl=secEl('div','pl');
  r.id='s-sec-coderow';
  pl.appendChild(secEl('b','','Authenticator code'));
  if(SEC_CODE.ok){
    pl.appendChild(secEl('small','sec-good','✓ It works. Keep the app: Bento asks for its code before it accepts a change it can\'t vouch for.'));
    if(st.held)pl.appendChild(secEl('small','','To let the agents run again, give your password and the app\'s next code in the box above.'));
    const done=secEl('button','endbtn','Done');
    done.onclick=()=>{SEC_CODE={shown:null,msg:'',ok:false,replace:false};secCardPaint()};
    pl.appendChild(done);r.appendChild(pl);return r;
  }
  if(SEC_CODE.shown){
    pl.appendChild(secCodeShown(st));
    if(SEC_CODE.msg)pl.appendChild(secEl('small','sec-err',SEC_CODE.msg));
    r.appendChild(pl);return r;
  }
  pl.appendChild(secEl('small','',st.code_set
    ?'Set up. Bento asks for it before it accepts a change it can\'t vouch for, here or from your phone.'
    :'A 6-digit code from an app on your phone. Bento asks for it before it accepts a change it can\'t vouch for.'));
  if(st.code_set&&!SEC_CODE.replace){
    const rb=secEl('button','endbtn sec-show','Replace the code…');
    rb.onclick=()=>{SEC_CODE.replace=true;secCardPaint()};
    pl.appendChild(rb);r.appendChild(pl);return r;
  }
  pl.appendChild(secSteps([
    'Install an authenticator app on your phone: Google Authenticator, Microsoft Authenticator, Authy or 1Password.',
    st.needs_password?'Type the password you sign in to Bento with, then press '+(st.code_set?'Replace the code':'Set up a code')+'.'
      :'Press '+(st.code_set?'Replace the code':'Set up a code')+'.',
    'Scan the square that appears with the app.',
    'Type the 6 digits the app shows, to check it works.']));
  if(st.code_set)pl.appendChild(secEl('small','','Replacing it needs the current code from your app too.'));
  const form=secEl('div','sec-accept');
  if(st.needs_password)form.appendChild(secField('password','Your Bento password','s-sec-cpw'));
  if(st.code_set)form.appendChild(secField('text','Current code','s-sec-ccode'));
  const b=secEl('button','endbtn primary',st.code_set?'Replace the code':'Set up a code');
  b.onclick=async()=>{
    const pw=document.getElementById('s-sec-cpw'),c=document.getElementById('s-sec-ccode');
    try{SEC_CODE.shown=await secPost('/api/security/code',{password:pw?pw.value:'',code:c?c.value:''});SEC_CODE.msg='';SEC_CODE.ok=false}
    catch(e){SEC_CODE.msg=e.message||String(e)}
    await secCardPaint();
    const row=document.getElementById('s-sec-coderow');if(row&&SEC_CODE.shown)row.scrollIntoView({block:'start'});
  };
  form.appendChild(b);pl.appendChild(form);
  if(SEC_CODE.msg)pl.appendChild(secEl('small','sec-err',SEC_CODE.msg+(/password/i.test(SEC_CODE.msg)?' It is the password you sign in to Bento with.':'')));
  r.appendChild(pl);return r;
}
