/* ================= Huddles: agents talking to each other =================
   A huddle is two to four specialists talking a question through, in turns, each on
   its OWN brain (agentos/fabric.py → huddle). The control plane moderates; agents
   never call each other. It reaches the page two ways, and both draw the same card:

   - live, as `agent_say` events — one per turn, the moment it lands — from the
     agent's `huddle` tool or from a message that starts with two names
     ("@researcher @validator should we…");
   - on reload, from the stored text, which is one line per turn
     (`@name (model): text`, fabric.huddle_text). One format for the model, the
     ledger and the page, so there is no second store to fall out of step.

   Every turn is that agent's own face, its name and the provider it answered on —
   the badge is the run's own `model`, never the agent's pin, because a switched-off
   provider sends a pinned agent to the machine's brain and the badge must say so.

   Faces — GUI/SUI: this. TUI: the huddle is plain text in a terminal chat and in
   `bento flow runs` (each turn is a run). `var`/function declarations only. */

/* A model id → the name of what answered it: "anthropic/claude-sonnet-5" →
   "Anthropic". Read from the brains catalogue the chat header already loaded, so
   this page has no second table of provider names. */
function brainName(model){
  const m=String(model||''), pid=m.includes('/')?m.split('/')[0]:m;
  const e=(typeof BRAINS!=='undefined'&&BRAINS.executors||[]).find(x=>x.id===pid);
  if(pid==='custom')return 'Custom server';   // as fabric.agent_brain names it
  return e?String(e.name||pid).split(' — ')[0]:(pid||'default');
}
function brainChip(model,provider){
  const m=String(model||''), short=m.includes('/')?m.split('/').slice(1).join('/'):m;
  const name=provider||brainName(m);
  return `<span class="brainchip" title="${esc(m||'the machine’s brain')}"><b>${esc(name)}</b>${short&&short!=='default'?' · '+esc(short):''}</span>`;
}
function huddleParse(text){
  const lines=String(text||'').split('\n'), out=[];
  lines.forEach(l=>{const m=l.match(/^@([\w-]+) \(([^)]*)\): (.*)$/);if(m)out.push({speaker:m[1],model:m[2],text:m[3]})});
  return out;
}
function huddleRow(e){
  return `<div class="hud-row" data-sp="${esc(e.speaker)}">${avatarImg(e.speaker,'av-who')||`<span class="hud-dot"></span>`}
    <div class="hud-say"><div class="hud-who">@${esc(e.speaker)}${e.to?` <span class="hud-to">→ @${esc(e.to)}</span>`:''} ${e.model||e.provider?brainChip(e.model,e.provider):''}</div>
    <div class="hud-text">${md(e.text||'')}</div></div></div>`;
}
/* `bare`: the message header above already names the room (a huddle started from
   the chat box), so the card does not say it a second time. */
function huddleCard(entries,agents,bare,kind){
  const who=(agents||[...new Set(entries.map(e=>e.speaker))]);
  return `<div class="huddle"${kind?` data-kind="${esc(kind)}"`:''}>${bare?'':`<div class="hud-head">${who.map(n=>avatarImg(n,'av-tool')).join('')}
    <span>${kind==='talk'?'agents talking':'huddle'} · ${esc(who.join(', '))}</span></div>`}${entries.map(huddleRow).join('')||'<div class="mut">nobody had anything to say</div>'}</div>`;
}
/* The label over a huddle started from the chat box: the faces in the room. */
function huddleWho(names){
  return (names||[]).map(n=>avatarImg(n,'av-who')).join('')+'huddle · '+esc((names||[]).join(', '));
}
/* One turn, live. It goes into the assistant message in progress — the tool card
   of the agent's `huddle` call, or the message a "@a @b …" turn opened — and the
   Crew stage hears it too, so the one talking says so over its head. */
function huddleLive(ev,isCur,kind){
  kind=kind||'huddle';
  if(typeof crewPulse==='function')crewPulse('say',ev.speaker,ev);
  // the activity pill: a huddle has no tool calls to report, so say who just spoke
  if(typeof actMove==='function'&&ev.conversation_id)
    actMove(ev.conversation_id,'think',{msg:(kind==='talk'?'agents talking · ':'huddle · ')+ev.speaker+(ev.to?' asked '+ev.to:' just spoke')});
  if(!isCur||!feed)return;
  if(!curBody)startAssistant();
  if(!curBody)return;
  const msg=curBody.parentNode;
  // the huddle already open directly above the reply keeps growing; anything said
  // in between (text, another tool) means this is a new one
  let card=curBody.previousElementSibling;
  if(!card||!card.classList.contains('huddle')||(card.dataset.kind||'huddle')!==kind){
    if(typeof flushText==='function')flushText();
    const holder=document.createElement('div');
    holder.innerHTML=huddleCard([],[],kind==='huddle'&&!!(typeof CUR_ENGINE!=='undefined'&&CUR_ENGINE.huddle),kind);
    card=holder.firstElementChild;card.querySelector('.mut')?.remove();
    msg.insertBefore(card,curBody);
  }
  card.insertAdjacentHTML('beforeend',huddleRow(ev));
  const who=[...new Set([...card.querySelectorAll('.hud-row')].map(r=>r.dataset.sp))];
  if(card.querySelector('.hud-head'))card.querySelector('.hud-head').innerHTML=who.map(n=>avatarImg(n,'av-tool')).join('')+`<span>${kind==='talk'?'agents talking':'huddle'} · ${esc(who.join(', '))}</span>`;
  if(typeof scrollDown==='function')scrollDown();
}

/* One specialist asking another mid-task (`ask_agent`, fabric.message): the
   question in the asker's face, then the answer in the answerer's, with the brain
   it answered on. Same card and same stage as a huddle, because it IS agents
   talking — the difference is who started it (an agent, not you) and what let it
   (the matrix, or swarm). Live only: each answer is its own run, and a reloaded
   conversation finds it in Observability rather than a second store here. */
function agentMsgLive(ev,isCur){
  const e=ev.phase==='ask'
    ?{speaker:ev.from,to:ev.to,text:ev.text,conversation_id:ev.conversation_id}
    :{speaker:ev.from,text:ev.text,model:ev.model,provider:ev.provider,conversation_id:ev.conversation_id};
  huddleLive(e,isCur,'talk');
}
