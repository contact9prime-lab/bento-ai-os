/* ================= The play strip: the Office, one line tall, wherever a turn is shown =================
   The Office is a whole window. A turn happens in many more places — Chat, the agent panel
   inside every app, the prompt bar's card — and the playground belongs there too, at the
   size of a line: the faces of whoever is working on THIS turn, a "!" when work lands on
   somebody, a comic burst for each tool call with the real tool name beside it, and a short
   balloon when one agent asks another. When the turn ends the strip stays as a still,
   honest record of who worked on it and how many steps each took.

   The Office's rules, unchanged:
   - **Only events.** Every mark on a strip is something the server said happened: a
     `turn_start` names the lead (or the `@specialist` answering), `tool_start` bursts,
     `delegate` and a mission's `node_add` bring a colleague in, `agent_msg` asks and
     answers, a run's `step` bursts on the one it belongs to. Nothing idles for the look.
   - **One seam.** scenePulse (01c) feeds the Crew stage, the Office and this.
   - **The same people and words.** Faces are avatarImg (the server's characters); the
     burst words are comicWord (00f), the Office's own.
   - **Placed by the surface that shows the turn.** A surface calls playHost(cid, fn) when
     it knows the conversation; `fn` says where a strip would go. Nothing is inserted until
     there is something to show, so a plain reply gets no strip at all.

   Cost: a few DOM nodes per turn; bursts are CSS animations removed after they play; no
   timers run when nothing happens. Reduced motion: the marks appear without moving.
   Faces — GUI/SUI: this. TUI: the chat TUI already prints each agent's line and each tool
   call; `bento office` has the roll call. Telegram: the same exchange as a comic strip
   picture (agentos/comic.py). `var` and function declarations only. */
var PLAY={hosts:new Map(),strips:new Map(),lead:{},runs:{},sent:{}};

/* A surface that shows conversation `cid` says where its strip would go: `fn()` returns
   {parent, before} (insert before `before`, or append to `parent`), or null when it cannot
   show one right now. */
function playHost(cid,fn){
  if(!cid)return;
  PLAY.hosts.set(cid,fn);
  if(PLAY.hosts.size>60)PLAY.hosts.delete(PLAY.hosts.keys().next().value);
}
function playStripOf(cid,create){
  let s=cid&&PLAY.strips.get(cid);
  if(s&&s.el.isConnected&&!s.done)return s;
  if(!create||!cid)return null;
  const host=PLAY.hosts.get(cid),at=host&&host();
  if(!at||!at.parent)return null;
  const el=document.createElement('div');el.className='pstrip';el.setAttribute('aria-hidden','true');
  at.parent.insertBefore(el,at.before||null);
  s={cid,el,cast:new Map(),done:false};
  PLAY.strips.set(cid,s);
  if(PLAY.strips.size>40)PLAY.strips.delete(PLAY.strips.keys().next().value);
  // the lead of this turn stands first, even before it has done anything
  playMember(s,PLAY.lead[cid]||'@agent');
  return s;
}
function playName(key){return key==='@agent'?(typeof agentName==='function'?agentName():'agent'):key}
function playMember(s,key,pop){
  let m=s.cast.get(key);
  if(!m){
    const el=document.createElement('span');el.className='ps-p';el.dataset.key=key;
    el.innerHTML=(typeof avatarImg==='function'?avatarImg(key,'ps-face'):'')
      +`<span class="ps-n">${esc(playName(key))}</span><span class="ps-c"></span>`;
    s.el.appendChild(el);
    m={key,el,steps:0,sayT:0};s.cast.set(key,m);
  }
  if(pop)playMark(m,'ps-pop','!');
  return m;
}
/* A mark that plays once and leaves: a "!" or a burst. */
function playMark(m,cls,text,title){
  const b=document.createElement('span');b.className=cls;b.textContent=text;if(title)b.title=title;
  m.el.appendChild(b);
  setTimeout(()=>b.remove(),1500);
}
function playWork(s,key,on){
  const m=playMember(s,key);m.el.classList.toggle('on',!!on);return m;
}
function playStep(s,key,tool){
  const m=playWork(s,key,true);
  m.steps++;
  m.el.querySelector('.ps-c').textContent='×'+m.steps;
  playMark(m,'ps-burst',comicWord(tool),tool);
}
function playSay(s,key,text){
  const m=playMember(s,key);
  let b=m.el.querySelector('.ps-say');
  if(!b){b=document.createElement('span');b.className='ps-say';m.el.appendChild(b)}
  b.textContent=String(text||'').replace(/\s+/g,' ').slice(0,70);
  clearTimeout(m.sayT);m.sayT=setTimeout(()=>b.remove(),6000);
}
/* The turn is over: the strip keeps who took part and how many steps each took, and
   stops saying anybody is working. A strip where only the lead appeared and nothing
   happened is removed — it would be a record of nothing. */
function playEnd(cid){
  const s=PLAY.strips.get(cid);if(!s)return;
  s.done=true;s.el.classList.add('done');
  s.cast.forEach(m=>{m.el.classList.remove('on');m.el.querySelectorAll('.ps-say,.ps-burst,.ps-pop').forEach(x=>x.remove())});
  if(s.cast.size<=1&&![...s.cast.values()].some(m=>m.steps))s.el.remove();
  PLAY.strips.delete(cid);
}
/* Which conversation a colleague's run belongs to: the one that last handed it work or
   asked it something. A run's own events carry its id and its agent, not the chat. */
function playFor(agent){return agent&&PLAY.sent[String(agent).toLowerCase()]}

function playPulse(kind,label,ev){
  ev=ev||{};
  const cid=ev.conversation_id||'';
  if(kind==='turn'){if(cid){PLAY.lead[cid]=ev.speaker||'@agent'}return}
  if(kind==='turnend'){playEnd(label);delete PLAY.lead[label];return}
  if(kind==='tool'){
    const s=playStripOf(cid,true);if(!s)return;
    const lead=PLAY.lead[cid]||'@agent';
    playStep(s,lead,label);
    if(label==='delegate'&&ev.args&&ev.args.subagent){
      const to=String(ev.args.subagent);
      PLAY.sent[to.toLowerCase()]=cid;
      playWork(s,to,true);playMark(playMember(s,to),'ps-pop','!');
    }
    return;
  }
  if(kind==='msg'){
    const s=playStripOf(cid,true);if(!s)return;
    if(ev.phase==='ask'){
      PLAY.sent[String(ev.to||'').toLowerCase()]=cid;
      playSay(s,ev.from,'@'+ev.to+' '+(ev.text||''));playWork(s,ev.to,true);
    }else{playSay(s,ev.from,ev.text||'')}
    return;
  }
  if(kind==='say'){
    if(ev.kind==='talk')return;             // asks and answers arrive as 'msg'
    const s=playStripOf(cid,true);if(!s)return;
    playSay(s,ev.speaker||label,ev.text||'');playWork(s,ev.speaker||label,true);
    return;
  }
  if(kind==='flow'){
    const e=ev.event;
    if(e==='node_add'&&ev.agent){
      const c=playFor(ev.agent)||cid;const s=playStripOf(c,!!c);if(!s)return;
      playWork(s,ev.agent,true);playMark(playMember(s,ev.agent),'ps-pop','!');return;
    }
    if(e==='status'&&ev.ref){
      const c=playFor(ev.ref);if(!c)return;
      if(ev.status==='running'){PLAY.runs[ev.run_id]={cid:c,key:ev.ref};return}
      delete PLAY.runs[ev.run_id];
      const s=playStripOf(c,false);if(s)playWork(s,ev.ref,false);
      return;
    }
    if(e==='step'&&ev.status==='start'){
      const r=PLAY.runs[ev.run_id];if(!r)return;
      const s=playStripOf(r.cid,true);if(s)playStep(s,r.key,ev.tool);
    }
  }
}

/* An app window the agent's hands just touched gets a burst too — the same word the
   strip and the Office would show, over the corner of the thing being changed. */
function playWindowBurst(win,tool){
  if(!win||!win.el)return;
  const b=document.createElement('span');b.className='win-burst';b.setAttribute('aria-hidden','true');
  b.textContent=comicWord(tool);
  win.el.appendChild(b);
  setTimeout(()=>b.remove(),1500);
}
