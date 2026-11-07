/* Settings → Permissions → Security: what the watcher knows (agentos/integrity.py, /api/security/status).
   Everything here is shown through text nodes. A file name and an alert's detail are whatever an
   attacker made them, and they come from another process's words. There is no button that clears a
   hold or seals anything, because those are a person's at a terminal, and the card says so.
   TUI: `bento integrity status`, `bento security`, `bento doctor`. SUI: the same page. */
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
  if(held&&(held.files||[]).length){
    const list=secEl('div','prow stack');
    const inner=secEl('div','pl');
    inner.appendChild(secEl('b','','What changed'));
    (held.files||[]).slice(0,12).forEach(f=>inner.appendChild(secEl('code','sec-file',f)));
    inner.appendChild(secEl('small','','Clear it at this machine\'s terminal, outside Bento: bento integrity accept'));
    list.appendChild(inner);kids.push(list);
  }
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
  if(SEC_OPEN)secDetails(st).forEach(r=>kids.push(r));
  box.replaceChildren(...kids);
}
