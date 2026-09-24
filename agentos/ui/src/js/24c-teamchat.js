/* ================= Team Chat: people on linked teams =================
   A link lets agents reach agents; this is the people behind them. One thread per
   linked team — another Bento (over the same mutual-TLS link) or another account
   here — with each person's own face beside their words, painted from the look that
   travelled with the message, and the other team's agent (its name and face) at the
   top, which is how a team is recognised.

   Honest about delivery: a message this machine cannot hand over now says "kept" and
   goes with the next exchange; one the other side refused says who refused and why.
   No agent reads any of it — there is no tool for it, on purpose.

   TUI: `bento link say LABEL TEXT` / `bento link chat LABEL`, and the chat TUI prints
   an arriving message. SUI: a page like any other window; nothing native. */
var TEAMCHAT={cur:'',threads:[],me:null,thread:null,busy:false};

function openTeamChat(label){
  if(label)TEAMCHAT.cur=label;
  openApp('teamchat');
  if(label)setTimeout(()=>refreshApp('teamchat'),60);
}
function tcTime(ts){
  const d=new Date((ts||0)*1000),now=new Date();
  return d.toDateString()===now.toDateString()?d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})
    :d.toLocaleDateString([], {day:'numeric',month:'short'})+' '+d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
}
function tcWho(t){
  const id=t.identity||{};
  return {face:avatarRecipeImg(id.agent,'av-tool',(id.agent_name||'their agent')+' — '+t.label+'’s agent'),
          name:t.label, sub:id.person?(id.person+(id.agent_name?' · '+id.agent_name+'’s team':'')):(id.agent_name?id.agent_name+'’s team':'')};
}
async function renderTeamChat(body){
  const phone=document.body.classList.contains('dev-mobile');
  let d={};
  try{d=await fetch('/api/team/chat').then(r=>r.json())}catch(e){}
  TEAMCHAT.threads=d.threads||[];TEAMCHAT.me=d.me||null;
  if(!TEAMCHAT.threads.length){
    body.innerHTML=`<div class="pad tc-empty"><p><b>Nobody to write to yet.</b></p>
      <p class="mut">Team Chat is for the people on your linked teams — another Bento, or another account on this machine. Link one first; it takes an address and one tap on the other side.</p>
      <button class="pact" onclick="openLinkedTeams()">Link a team</button></div>`;
    return;
  }
  if(!TEAMCHAT.cur||!TEAMCHAT.threads.some(t=>t.label===TEAMCHAT.cur))
    TEAMCHAT.cur=phone?'':TEAMCHAT.threads[0].label;
  const list=TEAMCHAT.threads.map(t=>{const w=tcWho(t),l=t.last;
    return `<button class="tc-th${t.label===TEAMCHAT.cur?' on':''}" data-l="${esc(t.label)}">
      ${w.face}<span class="tc-th-txt"><b>${esc(w.name)}</b>${t.unread?`<span class="tc-unread">${t.unread}</span>`:''}
      <small class="mut">${l?esc((l.dir==='out'?'you: ':'')+l.text.slice(0,60)):esc(w.sub||'no messages yet')}</small></span></button>`}).join('');
  body.innerHTML=`<div class="tc${phone?' phone':''}${phone&&TEAMCHAT.cur?' in-thread':''}">
    <div class="tc-list">${list}
      <div class="tc-me mut">You appear as ${avatarImg('@me','av-tool')}<b>${esc((d.me||{}).person||'')}</b>
        ${d.multiuser?'':`<button class="endbtn" onclick="tcRename()">Change</button>`}</div></div>
    <div class="tc-main" id="tc-main"></div></div>`;
  body.querySelectorAll('.tc-th').forEach(b=>b.onclick=()=>{TEAMCHAT.cur=b.dataset.l;renderTeamChat(body)});
  if(TEAMCHAT.cur)tcThread(body.querySelector('#tc-main'));
}
function tcMsgHTML(m,t){
  const mine=m.dir==='out';
  const face=mine?avatarImg('@me','av-tool'):avatarRecipeImg(m.look,'av-tool',m.sender);
  const tick=!mine?'':m.delivered===1?'<span class="tc-tick" title="delivered">✓</span>'
    :m.delivered===-1?'<span class="tc-tick bad" title="refused">refused</span>'
    :'<span class="tc-tick wait" title="not delivered yet">kept</span>';
  return `<div class="tc-msg${mine?' mine':''}" data-id="${esc(m.id)}">${face}
    <div class="tc-bub"><div class="tc-meta"><b>${esc(mine?'you':m.sender)}</b> <span class="mut">${tcTime(m.ts)}</span> ${tick}</div>
    <div class="tc-text">${esc(m.text)}</div></div></div>`;
}
async function tcThread(main){
  if(!main)return;
  const label=TEAMCHAT.cur;
  const t=TEAMCHAT.threads.find(x=>x.label===label)||{label,identity:{}};
  const w=tcWho(t);
  main.innerHTML=`<div class="tc-head">${document.body.classList.contains('dev-mobile')?'<button class="endbtn tc-back" onclick="TEAMCHAT.cur=\'\';refreshApp(\'teamchat\')">‹</button>':''}
      ${w.face}<div class="tc-head-txt"><b>${esc(w.name)}</b><small class="mut">${esc(w.sub)}</small></div>
      <label class="tlk-chk tc-mute"><input type="checkbox" ${t.muted?'':'checked'} onchange="tcMute('${esc(label)}',!this.checked)"><span>Take messages</span></label></div>
    <div class="tc-feed" id="tc-feed"><p class="mut pad">Reading…</p></div>
    <div class="tc-compose"><textarea id="tc-in" rows="2" placeholder="Write to ${esc(label)}…" maxlength="4000"></textarea>
      <button class="pact" id="tc-send">Send</button></div>
    <p class="mut tc-note" id="tc-note"></p>`;
  const inp=main.querySelector('#tc-in'),send=main.querySelector('#tc-send');
  send.onclick=()=>tcSend(label);
  inp.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!document.body.classList.contains('dev-mobile')){e.preventDefault();tcSend(label)}};
  let d={};
  try{d=await fetch('/api/team/chat/'+encodeURIComponent(label)).then(r=>r.json())}catch(e){}
  if(TEAMCHAT.cur!==label)return;
  TEAMCHAT.thread=d;
  const feed=main.querySelector('#tc-feed');
  if(!feed)return;
  feed.innerHTML=(d.messages||[]).length?d.messages.map(m=>tcMsgHTML(m,t)).join('')
    :`<p class="mut pad">No messages yet. Say hello — it reaches ${esc(w.sub||label)}.</p>`;
  feed.scrollTop=feed.scrollHeight;
  const note=main.querySelector('#tc-note');
  if(note)note.textContent=d.error||(d.reachable===false?'This machine cannot reach '+label+' directly: what you write is kept and goes the next time '+label+' talks to this machine.':'');
  const th=TEAMCHAT.threads.find(x=>x.label===label);if(th)th.unread=0;
  document.querySelector('.tc-th.on .tc-unread')?.remove();
}
async function tcSend(label){
  const inp=document.getElementById('tc-in');if(!inp||TEAMCHAT.busy)return;
  const text=inp.value.trim();if(!text)return;
  TEAMCHAT.busy=true;
  const r=await fetch('/api/team/chat/'+encodeURIComponent(label),{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text})}).then(r=>r.json()).catch(()=>({error:'the server did not answer'}));
  TEAMCHAT.busy=false;
  if(r.error){toast(r.error);return}
  inp.value='';inp.focus();
  const note=document.getElementById('tc-note');if(note)note.textContent=r.note||'';
  const el=document.querySelector(`.tc-msg[data-id="${CSS.escape(r.message.id)}"] .tc-tick`);
  if(el&&r.delivered){el.className='tc-tick';el.textContent='✓';el.title='delivered'}
}
async function tcMute(label,muted){
  const r=await fetch('/api/team/chat/'+encodeURIComponent(label),{method:'PUT',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({muted})}).then(r=>r.json()).catch(()=>({error:'the server did not answer'}));
  toast(r.error||(muted?'messages from '+label+' are refused — they are told so':'messages from '+label+' are welcome'));
  const t=TEAMCHAT.threads.find(x=>x.label===label);if(t)t.muted=muted;
}
async function tcRename(){
  const cur=(TEAMCHAT.me||{}).person||'';
  const v=await osPrompt('The name you go by in messages',{message:'Shown beside what you write, on the other team’s screen.',value:cur,confirmText:'Save'});
  if(v==null)return;
  const r=await fetch('/api/team/me',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:v})}).then(r=>r.json()).catch(()=>({error:'no answer'}));
  if(r.error)toast(r.error);refreshApp('teamchat');
}
/* A message arrived (or one of ours went out from another screen). Into the open
   thread when it is that one; otherwise the list's count and a toast with Open. */
function teamChatEvent(ev){
  const open=document.querySelector('.tc-feed')&&TEAMCHAT.cur===ev.link;
  if(open){
    const feed=document.getElementById('tc-feed');
    if(!feed.querySelector(`.tc-msg[data-id="${CSS.escape(ev.id)}"]`)){
      feed.querySelector('p.mut.pad')?.remove();
      feed.insertAdjacentHTML('beforeend',tcMsgHTML(ev,{}));feed.scrollTop=feed.scrollHeight;
    }
    if(ev.dir==='in')fetch('/api/team/chat/'+encodeURIComponent(ev.link)+'?pull=0').catch(()=>{});   // mark read
    return;
  }
  if(ev.dir==='in'){
    toast(ev.sender+' · '+ev.link+': '+String(ev.text||'').slice(0,80),{label:'Open',go:()=>openTeamChat(ev.link),ms:9000});
    if(document.querySelector('.tc'))refreshApp('teamchat');
  }
}
