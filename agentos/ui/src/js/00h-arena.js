/* ---------------- the Arena: one task, two or four brains, side by side ----------------
   agentos/arena.py + /api/arena. The window opens maximised and splits into two or four
   panes, one per brain, each streaming its work with a live HUD: time, tokens a second
   (from the first token, so a slow start is time and not speed), tokens, money, refusals
   by the gate and steps. The numbers come from the server (`hud` on every `arena` event);
   this page prices nothing and never says which answer is better.
   Faces: GUI and SUI are this window; on a phone the panes stack. TUI: `bento arena run
   "task" --vs 1 --vs 2` prints the same HUD as a table until every brain is done. */
var ARENA={info:null,n:2,picks:[],cur:null,w:null,task:'',past:null};

function renderArena(body,w){
  ARENA.w=w;
  if(!w.max&&typeof toggleMax==='function'&&innerWidth>700)setTimeout(()=>{if(!w.max)toggleMax(w)},60);
  const pb=panelShell(body,{title:'Arena',sub:'',actions:''});
  pb.innerHTML='<div class="mut" style="padding:14px">reading which brains can take part…</div>';
  apiJSON('/api/arena').then(async info=>{
    ARENA.info=info;
    if(info.live&&info.live.length){ARENA.cur=await apiJSON('/api/arena/'+encodeURIComponent(info.live[0]))}
    arenaPaint(pb);
  }).catch(e=>{pb.innerHTML=emptyBox('Could not open the Arena',esc(e.message))});
  winTick(w,()=>{if(ARENA.cur&&ARENA.cur.live)arenaClock(pb)},1000,{key:'arena'});
}
function arenaPaint(pb){
  pb=pb||(ARENA.w&&ARENA.w.el.querySelector('.pbody'));if(!pb)return;
  if(ARENA.cur)arenaPanes(pb);else arenaSetup(pb);
}
function arenaSetup(pb){
  const ch=(ARENA.info||{}).choices||[];
  if(ch.length<1){pb.innerHTML=emptyBox('No brains to put in the Arena yet',
    'Add a model under Settings → AI providers (a local one is free), or install an agent CLI. The Arena seats two to four of them.');return}
  // default picks: the first brains of different executors, so the first arena is a real contrast
  if(ARENA.picks.length!==ARENA.n){
    const seen=new Set(),first=[];
    ch.forEach((c,i)=>{if(first.length<ARENA.n&&!seen.has(c.executor)){seen.add(c.executor);first.push(i)}});
    for(let i=0;first.length<ARENA.n;i++)first.push(i%ch.length);
    ARENA.picks=first;
  }
  const opt=sel=>ch.map((c,i)=>`<option value="${i}"${i===sel?' selected':''}>${esc(c.label)}</option>`).join('');
  const recent=((ARENA.info||{}).recent||[]);
  pb.innerHTML=`<div class="ar-setup">
    <label class="ar-lbl" for="ar-task">The task every brain gets</label>
    <textarea id="ar-task" rows="3" maxlength="4000" placeholder="Build a retro synth app in App Studio, or fix this broken Python script…">${esc(ARENA.task)}</textarea>
    <div class="ar-row"><span class="seg" id="ar-n">${[2,4].map(n=>`<button data-n="${n}" class="${ARENA.n===n?'on':''}">${n} brains</button>`).join('')}</span></div>
    <div class="ar-seats">${ARENA.picks.map((p,i)=>`<label class="ar-seat"><span>Brain ${i+1}</span><select data-seat="${i}">${opt(p)}</select></label>`).join('')}</div>
    <div class="mut ar-note">Each brain works in its own folder and every step passes your permissions, as in chat.
      ${pInfoSafe('A folder is not a jail: a shell command reaches what the machine’s sandbox allows. Every brain spends its own tokens.')}</div>
    <div class="ar-row"><button class="endbtn primary" id="ar-go">Start the arena</button><span class="mut" id="ar-said"></span></div>
    ${recent.length?`<div class="ar-recent"><div class="of-sec">Earlier arenas</div>${recent.map(r=>
      `<button class="ar-past" data-id="${esc(r.id)}"><b>${esc(r.brains.join(' vs '))}</b><span class="mut">${esc(r.task)}</span></button>`).join('')}</div>`:''}
  </div>`;
  const q=s=>pb.querySelector(s);
  q('#ar-task').oninput=e=>ARENA.task=e.target.value;
  pb.querySelectorAll('#ar-n [data-n]').forEach(b=>b.onclick=()=>{ARENA.n=+b.dataset.n;ARENA.picks=[];arenaSetup(pb)});
  pb.querySelectorAll('[data-seat]').forEach(s=>s.onchange=()=>{ARENA.picks[+s.dataset.seat]=+s.value});
  q('#ar-go').onclick=()=>arenaStart(pb);
  pb.querySelectorAll('.ar-past').forEach(b=>b.onclick=async()=>{
    try{ARENA.cur=await apiJSON('/api/arena/'+encodeURIComponent(b.dataset.id));arenaPaint(pb)}catch(e){toast(e.message,{kind:'err'})}});
}
async function arenaStart(pb){
  const ch=(ARENA.info||{}).choices||[],said=pb.querySelector('#ar-said'),btn=pb.querySelector('#ar-go');
  const task=(pb.querySelector('#ar-task').value||'').trim();
  if(!task){said.textContent='Give the arena a task first.';return}
  btn.disabled=true;said.textContent='starting…';
  try{
    ARENA.cur=await apiJSON('/api/arena',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({task,contenders:ARENA.picks.map(i=>({executor:ch[i].executor,model:ch[i].model}))})});
    arenaPaint(pb);
  }catch(e){said.textContent=e.message;btn.disabled=false}
}
function arenaPanes(pb){
  const a=ARENA.cur,n=a.contenders.length;
  pb.innerHTML=`<div class="ar-top"><div class="ar-task" title="${esc(a.task)}">${esc(a.task)}</div>
      <span class="sp"></span>${a.live?'<button class="endbtn danger" id="ar-stop">Stop</button>':'<button class="endbtn" id="ar-new">New arena</button>'}</div>
    <div class="ar-grid n${n}">${a.contenders.map(c=>`<section class="ar-pane" data-slot="${c.slot}">
      <header><b>${esc(c.label)}</b><span class="ar-st ${esc(c.status)}">${esc(c.status)}</span></header>
      <div class="ar-hud">${arenaHud(c.hud,c)}</div>
      <div class="ar-log">${(c.log||[]).map(l=>`<div class="ar-tool ${l.denied?'denied':l.ok?'ok':'bad'}">▸ ${esc(l.name)}${l.detail?' · '+esc(l.detail):''}</div>`).join('')}${c.answer?`<span class="ar-txt">${esc(c.answer)}</span>`:''}${c.error?`<div class="ar-err">${esc(c.error)}</div>`:''}</div>
      <footer>${c.conversation_id?`<button class="endbtn" data-conv="${esc(c.conversation_id)}">Open in Chat</button>`:''}
        <span class="mut ar-files">${(c.files||[]).length?esc((c.files||[]).length+((c.files||[]).length===1?' file':' files')+' in its folder'):''}</span></footer>
    </section>`).join('')}</div>
    <div class="ar-sum">${(a.summary&&a.summary.lines||[]).map(l=>`<span>${esc(l)}</span>`).join('')}
      ${!a.live?'<span class="mut">Which answer is better is your call.</span>':''}</div>`;
  const q=s=>pb.querySelector(s);
  if(q('#ar-stop'))q('#ar-stop').onclick=()=>apiJSON('/api/arena/'+encodeURIComponent(a.id)+'/stop',{method:'POST'}).catch(e=>toast(e.message,{kind:'err'}));
  if(q('#ar-new'))q('#ar-new').onclick=()=>{ARENA.cur=null;apiJSON('/api/arena').then(i=>{ARENA.info=i;arenaPaint(pb)})};
  pb.querySelectorAll('[data-conv]').forEach(b=>b.onclick=()=>{openApp('chat');setTimeout(()=>openConv(b.dataset.conv),200)});
}
/* The HUD: numbers, each with what it means on hover. */
function arenaHud(h,c){
  h=h||{};
  const chip=(v,l,t,cls)=>`<span class="ar-chip${cls?' '+cls:''}" title="${esc(t)}"><b>${v}</b> ${l}</span>`;
  const secs=h.seconds!=null?h.seconds:0;
  return chip(secs.toFixed?secs.toFixed(1)+'s':secs,'time','From start to finish')
    +chip(h.tok_s!=null?h.tok_s:'—','tok/s','Output tokens a second, from its first output to the end')
    +chip(h.tokens_out||0,'out','Tokens written ('+(h.tokens_in||0)+' read)')
    +chip(h.priced===false?'?':('$'+(h.cost||0).toFixed(4)),'cost',h.priced===false?'No price set for this model':'What this brain spent')
    +chip(h.refused||0,'refused','Steps your permissions refused',(h.refused?'warn':''))
    +chip(h.steps||0,'steps','Tool calls it made');
}
function arenaClock(pb){
  // between events the clock still runs: seconds since the seat started, nothing else
  const a=ARENA.cur;if(!a)return;
  a.contenders.forEach(c=>{
    if(c.status!=='running'||!c.started)return;
    const el=pb.querySelector(`.ar-pane[data-slot="${c.slot}"] .ar-hud b`);
    if(el)el.textContent=(Date.now()/1000-c.started).toFixed(1)+'s';
  });
}
function arenaEvent(ev){
  const a=ARENA.cur;
  if(!a||ev.id!==a.id){if(ARENA.w&&!a&&!ev.done)apiJSON('/api/arena/'+encodeURIComponent(ev.id)).then(x=>{ARENA.cur=x;arenaPaint()}).catch(()=>{});return}
  const pb=ARENA.w&&ARENA.w.el.querySelector('.pbody');
  if(ev.done){apiJSON('/api/arena/'+encodeURIComponent(a.id)).then(x=>{ARENA.cur=x;arenaPaint(pb)}).catch(()=>{});return}
  const c=a.contenders[ev.slot];if(!c)return;
  if(ev.hud)c.hud=ev.hud;
  if(ev.status){c.status=ev.status;if(ev.status==='running'&&!c.started)c.started=Date.now()/1000-((ev.hud||{}).seconds||0)}
  if(!pb)return;
  const pane=pb.querySelector(`.ar-pane[data-slot="${ev.slot}"]`);if(!pane)return;
  pane.querySelector('.ar-hud').innerHTML=arenaHud(c.hud,c);
  const st=pane.querySelector('.ar-st');st.className='ar-st '+c.status;st.textContent=c.status;
  const e=ev.ev,log=pane.querySelector('.ar-log');if(!e)return;
  const stick=log.scrollTop+log.clientHeight>=log.scrollHeight-24;
  if(e.type==='text_delta'){
    let t=log.lastElementChild;
    if(!t||!t.classList.contains('ar-txt')){t=document.createElement('span');t.className='ar-txt';log.appendChild(t)}
    t.textContent+=e.text||'';
  }else if(e.type==='tool_start'){
    const d=document.createElement('div');d.className='ar-tool';d.dataset.call=e.call_id||'';
    d.textContent='▸ '+(e.name||'')+(e.detail?' · '+e.detail:'');log.appendChild(d);
  }else if(e.type==='tool_end'){
    const d=log.querySelector(`.ar-tool[data-call="${CSS.escape(e.call_id||'')}"]`)||document.createElement('div');
    if(!d.parentNode){d.className='ar-tool';d.textContent='▸ '+(e.name||'')+(e.detail?' · '+e.detail:'');log.appendChild(d)}
    const denied=String(e.output||'').startsWith('[denied]');
    d.classList.add(e.ok===false?(denied?'denied':'bad'):'ok');
    if(denied)d.title=String(e.output||'').slice(9);
  }else if(e.type==='error'){
    const d=document.createElement('div');d.className='ar-err';d.textContent=e.message||'error';log.appendChild(d);
  }else if(e.type==='seat_end'){
    pane.querySelector('footer').innerHTML=(c.conversation_id?`<button class="endbtn" data-conv="${esc(c.conversation_id)}">Open in Chat</button>`:'')
      +`<span class="mut">${esc(c.status)}</span>`;
    pane.querySelectorAll('[data-conv]').forEach(b=>b.onclick=()=>{openApp('chat');setTimeout(()=>openConv(b.dataset.conv),200)});
  }
  if(log.childElementCount>400)log.firstElementChild.remove();
  if(stick)log.scrollTop=log.scrollHeight;
}
