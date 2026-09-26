/* ================= Office: the playground where the crew is seen at work =================
   A comic-strip office drawn from THIS machine's agents: your agent in the corner office
   behind the mission board, each specialist at a desk in its department, a meeting room
   where huddles gather, a lounge. The chat is the column on the right (the window's own
   agent panel, moved into the layout), so you ask on the right and watch it happen on
   the left.

   What moves, and why only that:

   - **Every movement is an event.** A paper flies to a desk because a mission handed that
     specialist work (`node_add`) or your agent delegated to it (`delegate`); the monitor
     lights and the hands type because its run started (`status`); a burst names each tool
     it calls (`step`); one agent walks across the floor to another because it really asked
     it something (`agent_msg`), and walks back after the answer; a huddle gathers round the
     meeting table because one started (`turn_start.huddle` / `agent_say`). Idle agents sit
     at their desks, breathing and blinking. They do NOT wander for the look: an office
     where everybody strolls about is an office that says work is happening when none is,
     which is the dead-control lie in a friendlier drawing. The pet wanders; it is decor,
     and it is visibly not an agent.
   - **The cast is the real one.** The rooms and who sits in them come from /api/office
     (agentos/office.py), and every face is the server's own character sheet — the same
     person as in Chat, Logs and the Crew stage. This file paints rooms and furniture and
     nobody: there is no second painter (tests/test_avatars.py).
   - **One seam for events.** scenePulse() in 01c forwards to the Crew stage and here, so
     a new scene is not five more edits in the websocket.
   - **The words are there too.** The canvas is a picture; the log under it says the same
     things in sentences (aria-live), and it is what a screen reader reads.

   Cost: one canvas, the rooms pre-rendered once into an offscreen layer and blitted; at
   most 30 frames a second while something moves and 6 while everybody sits; no frame at
   all while the window is asleep (minimised, another desktop, covered, tab hidden); one
   still frame per event under reduced motion. No filter, no blur, no canvas shadow.

   Faces — GUI: this window. SUI: identical, a page; nothing touches the compositor.
   TUI: `bento office` prints the plan (rooms and who sits where) and edits it with the
   same closed set; the play itself cannot exist in a terminal and the verb says so.
   Phone: the chat becomes a sheet behind a Chat button, every control at the tap floor.
   `var`, not `let`: the bundle is one script. */
var OFFICE={w:null,cv:null,ctx:null,raf:0,last:0,t:0,view:null,brains:{},L:null,bg:null,
  people:{},papers:[],bursts:[],pops:[],runs:{},convWho:{},missions:{},huddle:null,
  pet:null,dpr:1,s:1,cw:0,ch:0,font:'',static:false,log:[],sheets:{},design:false,loaded:false};
var OF_K=3;               // world units per sprite pixel: a 16x26 character is 48x78 units
var OF_INK='#191827';     // the comic line: one ink for every outline
var OF_SPEED=170;         // walking, world units a second
var OF_SAY_MS=5200;       // a speech balloon's life
var OF_WORK_MS=12000;     // a desk stays lit this long after the last thing it did
var OF_DESK_W=130, OF_WALL=46, OF_ROOM_H=206, OF_HALL=40, OF_SPINE=34, OF_M=14, OF_GAP=12;
function renderOffice(el,w){
  // A re-render (refreshApp, a websocket `office` event) reloads the plan and keeps
  // everybody where they are — rebuilding the canvas would teleport a walker home.
  if(OFFICE.w===w&&el.querySelector('.of-wrap')){officeLoad();return}
  OFFICE.w=w;OFFICE.people={};OFFICE.papers=[];OFFICE.bursts=[];OFFICE.pops=[];OFFICE.sheets={};
  OFFICE.static=matchMedia('(prefers-reduced-motion: reduce)').matches;
  try{OFFICE.font=getComputedStyle(document.body).fontFamily||'sans-serif'}catch(e){OFFICE.font='sans-serif'}
  // the window's ✦ would open a second copy of the chat that is already on the right
  const cb=w.el.querySelector('.cp-btn');if(cb)cb.style.display='none';
  el.classList.add('of-body');
  el.innerHTML=`<div class="of-wrap">
    <div class="of-stage">
      <div class="of-bar"><b class="of-title">Office</b><span class="of-line" id="of-line">opening…</span>
        <span style="flex:1"></span>
        <button class="endbtn of-vz" title="Visit a linked team's office">⇄ Visit</button>
        <button class="endbtn of-snap" data-ic="camera" title="Send the office right now, as a picture, to your phone">◉ Snap</button>
        <button class="endbtn of-dz" data-ic="palette" title="Change how the office looks and who sits where">✎ Design</button>
        <button class="endbtn of-ct" title="Talk to your agent">Chat</button></div>
      <div class="of-scroll"><canvas class="of-cv" aria-hidden="true"></canvas>
        <div class="of-empty" hidden></div></div>
      <div class="of-log" role="log" aria-live="polite" aria-label="What the office is doing"></div>
      <div class="of-design" hidden></div>
      <div class="of-visit" hidden></div>
    </div>
    <div class="of-chat"></div>
  </div>`;
  OFFICE.cv=el.querySelector('.of-cv');OFFICE.ctx=OFFICE.cv.getContext('2d');
  el.querySelector('.of-dz').onclick=()=>officeDesign(!OFFICE.design);
  el.querySelector('.of-snap').onclick=officeSnap;
  el.querySelector('.of-vz').onclick=()=>officeVisit(OFFICE.visiting===undefined?'':null);
  el.querySelector('.of-ct').onclick=()=>el.querySelector('.of-wrap').classList.toggle('chat-open');
  OFFICE.cv.addEventListener('click',officeTap);
  const chat=el.querySelector('.of-chat');
  if(typeof initCopilot==='function')initCopilot(w,chat);
  const sc=el.querySelector('.of-scroll');
  if(typeof ResizeObserver!=='undefined'){w._ofro=new ResizeObserver(()=>officeLayout());w._ofro.observe(sc)}
  // ms:0 — nothing to poll; this only restarts the loop the moment the window is seen again
  winTick(w,officeKick,0,{key:'office'});
  officeLog('the office is open');
  officeLoad();
}
function officeClose(w){
  cancelAnimationFrame(OFFICE.raf);OFFICE.raf=0;
  try{w._ofro&&w._ofro.disconnect()}catch(e){}
  OFFICE.w=null;OFFICE.cv=null;OFFICE.ctx=null;OFFICE.bg=null;OFFICE.design=false;OFFICE.visiting=undefined;
  return true;
}
async function officeLoad(){
  try{
    const [v,sa]=await Promise.all([apiJSON('/api/office'),
      fetch('/api/subagents').then(r=>r.json()).catch(()=>({}))]);
    OFFICE.view=v;OFFICE.brains={};
    (sa.subagents||sa.agents||[]).forEach(s=>{if(s&&s.name)OFFICE.brains[s.name]=(s.brain&&s.brain.provider_name)||''});
    OFFICE.brains['@agent']=(sa.agent_brain&&sa.agent_brain.provider_name)||'';
    if(typeof avatarsLoad==='function'&&(v.agents||[]).some(n=>!AVATARS.by[n]))await avatarsLoad();
    OFFICE.loaded=true;
    officeLayout();
    if(OFFICE.design)officeDesignPaint();
  }catch(e){const l=document.getElementById('of-line');if(l)l.textContent='could not load the office — '+(e.message||e)}
}
/* The roster moved (a specialist made or deleted, a face changed): reload the plan. */
function officeReload(){if(OFFICE.w)officeLoad()}
function officeContext(){
  const v=OFFICE.view;if(!v)return 'the Office playground (loading)';
  const rooms=v.rooms.filter(r=>r.kind==='dept'||r.kind==='floor').map(r=>`${r.name}: ${r.members.join(', ')||'empty'}`);
  const busy=Object.values(OFFICE.people).filter(p=>p.busy).map(p=>p.label);
  return `the Office playground, "${v.office.name}" in the ${v.style.label} style — ${rooms.join('; ')||'no departments'}.`
    +(busy.length?` Working right now: ${busy.join(', ')}.`:' Nobody is working right now.')
    +' To change how it looks or who sits where, use set_office.';
}

/* ---------------- layout: rooms into rows, desks into rooms ---------------- */
function officeLayout(){
  const O=OFFICE,v=O.view;if(!O.cv||!v)return;
  const sc=O.cv.parentElement,cw=Math.max(280,sc.clientWidth);
  const phone=cw<640;
  O.s=phone?cw/560:Math.max(.78,Math.min(1.3,cw/1100));
  const W=cw/O.s, x0=OF_M+OF_SPINE, avail=W-x0-OF_M;
  // each room's natural width: a desk slot per member, and never narrower than a room
  const want=r=>r.kind==='lead'?300:r.kind==='meeting'?280:r.kind==='lounge'?250
    :Math.max(250,Math.max(1,r.members.length)*OF_DESK_W+40);
  const rows=[];let row=[],used=0;
  v.rooms.forEach(r=>{
    const wn=Math.min(avail,want(r));
    if(row.length&&used+OF_GAP+wn>avail){rows.push(row);row=[];used=0}
    row.push({r,wn});used+=(row.length>1?OF_GAP:0)+wn;
  });
  if(row.length)rows.push(row);
  const plan=rows.map(rw=>{
    const sum=rw.reduce((a,b)=>a+b.wn,0)+OF_GAP*(rw.length-1), extra=(avail-sum)/sum;
    // desks that do not fit one line wrap to a second, and the whole row grows with them
    const lay=rw.map(o=>{const w=o.wn*(1+Math.max(0,extra));
      const per=Math.max(1,Math.floor((w-30)/OF_DESK_W));
      const lines=(o.r.kind==='dept'||o.r.kind==='floor')?Math.max(1,Math.ceil(o.r.members.length/per)):1;
      return {o,w,per,lines}});
    return {lay,h:OF_ROOM_H+(Math.max(...lay.map(l=>l.lines))-1)*112};
  });
  // a short office on a tall window: the rooms get more floor rather than leaving a
  // dark band under them (capped, so one row of rooms does not become a ballroom)
  const natural=OF_M*2+plan.reduce((a,r)=>a+r.h+OF_HALL,0)-OF_HALL*.5, room=sc.clientHeight/O.s;
  const grow=phone?0:Math.max(0,Math.min(140,(room-natural)/plan.length));
  const rooms=[];let y=OF_M;
  plan.forEach((row,ri)=>{
    const h=row.h+grow;let x=x0;
    row.lay.forEach(l=>{rooms.push({...l.o.r,x,y,w:l.w,h,row:ri,per:l.per,door:x+l.w/2,grow});x+=l.w+OF_GAP});
    y+=h+OF_HALL;
  });
  const H=y+OF_M-OF_HALL+OF_HALL*.5;
  O.L={W,H,rooms,rowsY:rows.map((_,i)=>{const r=rooms.find(q=>q.row===i);return r.y+r.h+OF_HALL/2}),spineX:OF_M+OF_SPINE/2};
  // the canvas is as tall as the office: a phone scrolls it rather than shrinking people to ants
  O.cw=cw;O.ch=Math.ceil(H*O.s);O.dpr=Math.min(2,devicePixelRatio||1);
  O.cv.style.width=cw+'px';O.cv.style.height=O.ch+'px';
  O.cv.width=Math.round(cw*O.dpr);O.cv.height=Math.round(O.ch*O.dpr);
  officeSeat();
  officeBg();
  officeEmpty();
  officeLine();
  officeKick();
}
/* Everybody gets a home: a chair at a desk. A person already on the floor keeps
   walking; one whose department changed walks to the new desk rather than jumping. */
function officeSeat(){
  const O=OFFICE,keep=O.people,seen={};
  O.L.rooms.forEach(r=>{
    if(r.kind==='lead'){
      const hx=r.x+r.w*.36, hy=r.y+OF_WALL+84+(r.grow||0)*.4;
      seen['@agent']=officePerson(keep['@agent'],'@agent',(typeof agentName==='function'?agentName():'Aria'),r,hx,hy,true);
    }
    if(r.kind!=='dept'&&r.kind!=='floor')return;
    const slot=Math.min(OF_DESK_W+30,(r.w-20)/Math.min(r.per,Math.max(1,r.members.length)));
    r.members.forEach((m,i)=>{
      const col=i%r.per,line=Math.floor(i/r.per),n=Math.min(r.per,r.members.length-line*r.per);
      const x=r.x+r.w/2+(col-(n-1)/2)*slot, y=r.y+OF_WALL+78+line*112+(r.grow||0)*.4;
      seen[m]=officePerson(keep[m],m,m,r,x,y,false);
    });
  });
  O.people=seen;
  if(!O.pet||O.pet.kind!==O.view.office.pet)O.pet=O.view.office.pet!=='none'?officePetNew():null;
}
function officePerson(p,key,label,room,x,y,lead){
  const home={x,y};
  if(!p)return {key,label,room,home,x,y,mode:'seat',path:[],busy:0,say:null,lead,then:null,phase:Math.random()*6.28};
  p.room=room;p.home=home;p.label=label;p.lead=lead;
  if(p.mode==='seat'){p.x=x;p.y=y}
  else if(!p.path.length&&!p.visit)officeWalk(p,home,'seat');
  return p;
}
function officeRoomOf(kind){return OFFICE.L&&OFFICE.L.rooms.find(r=>r.kind===kind)}

/* ---------------- walking ---------------- */
/* A route along the floor plan: out of this room's door into the hallway below it,
   along the spine on the left if the other room is on another row, and in through
   that room's door. Nobody walks through a wall. */
function officeRoute(p,to){
  const L=OFFICE.L,from=p.mode==='seat'?{x:p.home.x,y:p.home.y+50}:{x:p.x,y:p.y};
  const ra=officeRoomAt(from),rb=officeRoomAt(to);
  const pts=[];
  if(p.mode==='seat')pts.push({x:p.home.x+40,y:p.home.y+56});   // stand up, step round the desk
  if(ra&&rb&&ra!==rb){
    const ya=L.rowsY[ra.row],yb=L.rowsY[rb.row];
    pts.push({x:ra.door,y:ra.y+ra.h-14},{x:ra.door,y:ya});
    if(ra.row!==rb.row)pts.push({x:L.spineX,y:ya},{x:L.spineX,y:yb});
    pts.push({x:rb.door,y:yb},{x:rb.door,y:rb.y+rb.h-14});
  }
  pts.push(to);
  return pts;
}
function officeRoomAt(pt){return OFFICE.L.rooms.find(r=>pt.x>=r.x-2&&pt.x<=r.x+r.w+2&&pt.y>=r.y&&pt.y<=r.y+r.h+4)}
function officeWalk(p,to,mode,then){
  if(!p||!OFFICE.L)return;
  const route=officeRoute(p,mode==='seat'?{x:p.home.x+40,y:p.home.y+56}:to);
  if(mode==='seat')route.push({x:p.home.x,y:p.home.y,sit:1});
  p.path=route;p.mode='walk';p.then={mode,fn:then||null};
  if(OFFICE.static){const last=route[route.length-1];p.x=last.x;p.y=last.y;officeArrive(p)}
  officeKick();
}
function officeArrive(p){
  p.path=[];const t=p.then||{};p.then=null;
  p.mode=t.mode||'stand';
  if(p.mode==='seat'){p.x=p.home.x;p.y=p.home.y}
  if(t.fn)t.fn();
}
function officeHome(p){if(p&&(p.mode!=='seat'||p.path.length)){p.visit=null;officeWalk(p,p.home,'seat')}}

/* ---------------- what happened: the one seam's other end ---------------- */
function officeLog(text){
  const O=OFFICE;O.log.unshift({text:String(text).slice(0,160),at:Date.now()});O.log.length=Math.min(O.log.length,4);
  const el=O.w&&O.w.el.querySelector('.of-log');if(!el)return;
  el.innerHTML=O.log.map((e,i)=>`<div class="of-le${i?'':' new'}"><span>${new Date(e.at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</span>${esc(e.text)}</div>`).join('');
}
function officeMatch(label){
  if(!label)return null;
  const k=String(label).toLowerCase().replace(/[^a-z0-9@]/g,'');
  if(k==='@agent'||k==='agent')return OFFICE.people['@agent']||null;
  for(const n in OFFICE.people){const q=n.toLowerCase().replace(/[^a-z0-9@]/g,'');if(q&&q===k)return OFFICE.people[n]}
  return null;
}
function officeSay(p,text,kind,ms){
  if(!p)return;
  p.say={text:String(text||'').replace(/\s+/g,' ').trim().slice(0,140),kind:kind||'say',at:performance.now(),ms:ms||OF_SAY_MS};
  officeKick();
}
function officeWork(p,on){if(!p)return;p.busy=on?performance.now():0;officeLine();officeKick()}
function officePop(p,text){if(!p)return;OFFICE.pops.push({p,text,at:performance.now()});officeKick()}
function officeBurst(p,tool){
  if(!p)return;const now=performance.now();
  // the same step can arrive twice (the chat stream and the run's own telemetry)
  if(OFFICE.bursts.some(b=>b.p===p&&b.tool===tool&&now-b.at<700))return;
  OFFICE.bursts.push({p,tool,word:comicWord(tool),
    at:now,rot:(Math.random()-.5)*.3});
  if(OFFICE.bursts.length>12)OFFICE.bursts.shift();
  p.busy=now;officeKick();
}
/* A paper from somewhere to somebody: the moment a piece of work changes hands. */
function officePaper(from,to,onArrive){
  if(!to)return onArrive&&onArrive();
  OFFICE.papers.push({from,to,at:performance.now(),ms:OFFICE.static?1:950,fn:onArrive});
  officeKick();
}
function officeBoardPoint(){
  const r=officeRoomOf('lead');if(!r)return {x:OF_M,y:OF_M};
  return OFFICE.view.office.decor.includes('whiteboard')?{x:r.x+r.w*.78,y:r.y+OF_WALL+10}:{x:r.door,y:r.y+r.h};
}
function officeHead(p){return p.mode==='seat'?{x:p.x,y:p.y-50}:{x:p.x,y:p.y-80}}
function officeName(k){return k==='@agent'?(typeof agentName==='function'?agentName():'your agent'):k}

function officePulse(kind,label,ev){
  const O=OFFICE;if(!O.w||!O.L)return;
  ev=ev||{};
  if(kind==='turn'){
    const who=ev.speaker?officeMatch(ev.speaker):O.people['@agent'];
    if(label)O.convWho[label]=who?who.key:'@agent';
    if(ev.huddle&&ev.huddle.length)officeHuddle(ev.huddle,label);
    else if(who){officeWork(who,true);officePop(who,'!')}
    return;
  }
  if(kind==='turnend'){
    const who=O.people[O.convWho[label]||'@agent'];
    if(O.huddle&&O.huddle.cid===label)officeHuddleEnd();
    if(who)officeWork(who,false);
    delete O.convWho[label];return;
  }
  if(kind==='tool'){
    const who=O.people[(ev.conversation_id&&O.convWho[ev.conversation_id])||'@agent']||O.people['@agent'];
    if(label==='delegate'){
      const to=officeMatch((ev.args||{}).subagent);
      if(to){officePaper(officeHead(who),to,()=>{officeWork(to,true);officePop(to,'!');
        officeSay(to,'on it: '+((ev.args||{}).task||''),'think',3600)});
        officeLog(`${officeName(who.key)} handed ${to.label} some work`)}
    }
    officeBurst(who,label);return;
  }
  if(kind==='say'){
    if(ev.kind==='talk')return;              // agents asking each other arrive as 'msg'
    const p=officeMatch(label);if(!p)return;
    if(!O.huddle||O.huddle.until<performance.now())officeHuddle([label],ev.conversation_id||'');
    officeHuddleJoin(p);officeSay(p,ev.text,'say',OF_SAY_MS+1500);
    O.huddle.until=performance.now()+25000;
    officeLog(`${p.label} (huddle): ${String(ev.text||'').slice(0,90)}`);
    return;
  }
  if(kind==='msg')return officeMsg(ev);
  if(kind==='flow')return officeFabric(ev);
  if(kind==='done'){
    if(label&&O.missions[label]){delete O.missions[label];officeKick()}
    return;
  }
}
/* One agent asking another (fabric.message). The asker walks to the other's desk and
   asks there; the answer is said at that desk, and then the asker walks back. From a
   mission's master or another team there is nobody here to walk, so the question
   arrives on paper instead. */
function officeMsg(ev){
  const O=OFFICE,from=officeMatch(ev.from),to=officeMatch(ev.to);
  if(ev.phase==='ask'){
    if(!to)return;
    officeWork(to,true);
    if(from&&from!==to){
      const visit={to:to.key,asked:false,reply:null};
      from.visit=visit;
      officeWalk(from,{x:to.home.x+34,y:to.home.y+62},'stand',()=>{
        if(from.visit!==visit)return;
        officeSay(from,'@'+to.label+' '+(ev.text||''),'say');
        visit.asked=true;
        // the answer came back while it was still walking over: it is heard now, after
        // the question, never before it
        if(visit.reply){const r=visit.reply;setTimeout(()=>officeReply(from,to,r),OFFICE.static?0:1800)}
        else officeSay(to,'…','think',60000);
      });
    }else{
      officePaper(officeBoardPoint(),to,()=>{officeSay(to,(ev.from||'someone')+' asks: '+(ev.text||''),'say')});
    }
    officeLog(`${ev.from} asked ${ev.to}: ${String(ev.text||'').slice(0,90)}`);
    return;
  }
  // the reply: said by the one who was asked, at its own desk
  const who=officeMatch(ev.from),asker=officeMatch(ev.to);
  officeLog(`${ev.from} answered ${ev.to}: ${String(ev.text||'').slice(0,90)}`);
  if(asker&&asker.visit&&asker.visit.to===(who&&who.key)&&!asker.visit.asked){asker.visit.reply=ev.text;return}
  officeReply(asker,who,ev.text);
}
/* The answer, at the answerer's desk; the asker thanks it and walks back. */
function officeReply(asker,who,text){
  if(who){officeSay(who,text,'say',OF_SAY_MS+2000);officeWork(who,true)}
  if(asker&&asker.visit){
    const a=asker,v=a.visit;
    setTimeout(()=>{if(a.visit===v){officeSay(a,'thanks!','say',1800);officeHome(a)}},OFFICE.static?0:OF_SAY_MS);
  }
}
/* A run of a mission, or of one specialist. The run id → who map is how a bare `step`
   (which names a tool and no agent) lands on the right desk. */
function officeFabric(ev){
  const O=OFFICE,e=ev.event;
  if(e==='flow_start'){O.missions[ev.flow]=performance.now();officeLog(`mission ${ev.flow} started`);officeKick();return}
  if(e==='flow_end'){if(ev.flow)delete O.missions[ev.flow];else O.missions={};return}
  if(e==='node_add'){
    const to=officeMatch(ev.agent);
    if(to){officePaper(officeBoardPoint(),to,()=>{officeWork(to,true);officePop(to,'!');
      officeSay(to,'on it: '+(ev.task||''),'think',3600)});
      officeLog(`${to.label} got work: ${String(ev.task||'').slice(0,90)}`)}
    else if(ev.agent&&String(ev.agent).includes('@'))officeLog(`work went to ${ev.agent} on a linked team`);
    return;
  }
  if(e==='status'&&ev.ref){
    const p=officeMatch(ev.ref);if(!p)return;
    if(ev.status==='running'){O.runs[ev.run_id]=p.key;officeWork(p,true);return}
    delete O.runs[ev.run_id];
    const ok=ev.status==='ok'||ev.status==='done';
    officeWork(p,false);
    officeSay(p,ok?'done ✓':'hit a snag ✗','say',3200);
    if(ev.parent_run)officePaper(officeHead(p),{x:officeBoardPoint().x,y:officeBoardPoint().y+20,board:1});
    return;
  }
  if(e==='step'&&ev.status==='start'){const p=O.people[O.runs[ev.run_id]];if(p)officeBurst(p,ev.tool);return}
  if(e==='approval'){
    const p=officeMatch(ev.ref)||O.people[O.runs[ev.run_id]];if(!p)return;
    if(ev.state==='asked'){officeSay(p,'? needs you — '+(ev.tool||''),'shout',120000);p.hand=1;
      officeLog(`${p.label} is waiting for you to allow ${ev.tool||'a step'}`)}
    else{p.hand=0;officeSay(p,ev.state==='allowed'?'thanks!':'ok, not that','say',2000)}
  }
}
/* ---------------- huddles: the meeting room ---------------- */
function officeHuddle(names,cid){
  const O=OFFICE;
  O.huddle={cid:cid||'',who:[],until:performance.now()+25000};
  (names||[]).forEach(n=>{const p=officeMatch(n);if(p)officeHuddleJoin(p)});
  officeLog(`huddle: ${(names||[]).join(', ')}`);
}
function officeHuddleJoin(p){
  const O=OFFICE,h=O.huddle;if(!h||h.who.includes(p))return;
  h.who.push(p);officeWork(p,true);
  const r=officeRoomOf('meeting')||officeRoomOf('lounge')||officeRoomOf('lead');
  const i=h.who.length-1, cx=r.x+r.w/2, ty=r.y+OF_WALL+92+(r.grow||0)*.45;
  // three behind the table (feet at its far edge), three in front, then the two ends
  const spots=[[-58,-30],[0,-34],[58,-30],[-58,62],[0,66],[58,62],[-126,20],[126,20]];
  const s=spots[i%spots.length];
  p.visit={huddle:1};
  officeWalk(p,{x:cx+s[0],y:ty+s[1]},'stand');
}
function officeHuddleEnd(){
  const O=OFFICE,h=O.huddle;if(!h)return;O.huddle=null;
  h.who.forEach(p=>{officeWork(p,false);officeHome(p)});
}

/* ---------------- the loop ---------------- */
function officeKick(){
  const O=OFFICE;if(!O.w||!O.ctx)return;
  if(O.static||!winAwake(O.w)){if(winAwake(O.w))officeDraw();return}
  if(!O.raf){O.last=performance.now();O.raf=requestAnimationFrame(officeFrame)}
}
function officeMoving(){
  const O=OFFICE;
  return O.papers.length||O.bursts.length||O.pops.length||Object.values(O.people).some(p=>p.mode==='walk'||p.busy||p.say)
    ||(O.pet&&O.pet.walking);
}
function officeFrame(now){
  const O=OFFICE;O.raf=0;
  if(!O.w||!O.ctx||!winAwake(O.w))return;       // asleep: the next wake re-kicks
  const busy=officeMoving(), dt=(now-O.last)/1000;
  if(dt<(busy?1/30:1/6)){O.raf=requestAnimationFrame(officeFrame);return}
  O.last=now;officeStep(Math.min(.1,dt));officeDraw();
  O.raf=requestAnimationFrame(officeFrame);
}
function officeStep(dt){
  const O=OFFICE,now=performance.now();O.t+=dt;
  Object.values(O.people).forEach(p=>{
    if(p.mode==='walk'&&p.path.length){
      let d=OF_SPEED*dt;
      while(d>0&&p.path.length){
        const q=p.path[0],dx=q.x-p.x,dy=q.y-p.y,l=Math.hypot(dx,dy);
        if(l<=d){p.x=q.x;p.y=q.y;d-=l;p.path.shift()}else{p.x+=dx/l*d;p.y+=dy/l*d;d=0}
      }
      if(!p.path.length)officeArrive(p);
    }
    if(p.busy&&now-p.busy>OF_WORK_MS&&!p.hand)p.busy=0;
    if(p.say&&now-p.say.at>p.say.ms)p.say=null;
  });
  O.papers=O.papers.filter(pp=>{if(now-pp.at>=pp.ms){if(pp.fn)pp.fn();return false}return true});
  O.bursts=O.bursts.filter(b=>now-b.at<1500);
  O.pops=O.pops.filter(b=>now-b.at<1100);
  if(O.huddle&&O.huddle.until<now&&!O.huddle.cid)officeHuddleEnd();
  if(O.pet)officePetStep(dt);
  officeLine();
}
function officeLine(){
  const el=OFFICE.w&&OFFICE.w.el.querySelector('#of-line');if(!el||!OFFICE.view)return;
  const ps=Object.values(OFFICE.people), n=ps.length-1, busy=ps.filter(p=>p.busy).length;
  const talk=ps.filter(p=>p.visit).length;
  const txt=`${OFFICE.view.office.name} · ${busy?busy+' working':'all quiet'}${talk?' · '+talk+' talking':''} · ${n} ${n===1?'specialist':'specialists'}`;
  if(el.textContent!==txt)el.textContent=txt;
  const t=OFFICE.w.el.querySelector('.of-title');if(t)t.textContent=OFFICE.view.style.label;
}

/* ---------------- drawing: the room layer (once per layout) ---------------- */
function ofRR(ctx,x,y,w,h,r){ctx.beginPath();if(ctx.roundRect)ctx.roundRect(x,y,w,h,r);else ctx.rect(x,y,w,h)}
function ofInk(ctx,lw){ctx.strokeStyle=OF_INK;ctx.lineWidth=lw||2.6;ctx.lineJoin='round';ctx.lineCap='round';ctx.stroke()}
function ofLum(h){const v=[1,3,5].map(i=>parseInt(String(h).slice(i,i+2),16)||0);return v[0]*.299+v[1]*.587+v[2]*.114}
function ofHash(s){let h=2166136261;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)}return (h>>>0)/4294967295}
function ofMix(a,b,t){const p=x=>[1,3,5].map(i=>parseInt(x.slice(i,i+2),16));const A=p(a),B=p(b);
  return '#'+A.map((v,i)=>Math.round(v+(B[i]-v)*t).toString(16).padStart(2,'0')).join('')}
function ofFont(ctx,size,weight,italic){ctx.font=`${italic?'italic ':''}${weight||700} ${size}px ${OFFICE.font||'sans-serif'}`}
function officeBg(){
  const O=OFFICE;if(!O.L||!O.cv)return;
  const c=O.bg||(O.bg=document.createElement('canvas'));
  c.width=O.cv.width;c.height=O.cv.height;
  const ctx=c.getContext('2d'),st=O.view.style,L=O.L;
  ctx.setTransform(O.dpr*O.s,0,0,O.dpr*O.s,0,0);
  // the building: hallways and the spine, a flat tone under everything
  ctx.fillStyle=ofMix(st.wall,'#000000',.55);ctx.fillRect(0,0,L.W,L.H);
  ctx.fillStyle=ofMix(st.floor[1],'#000000',.18);
  L.rowsY.forEach(y=>ctx.fillRect(OF_M,y-OF_HALL/2+3,L.W-OF_M*2,OF_HALL-6));
  ctx.fillRect(OF_M,OF_M,OF_SPINE-6,L.H-OF_M*2);
  ofDots(ctx,OF_M,OF_M,OF_SPINE-6,L.H-OF_M*2,'#000000',.12,9);
  L.rooms.forEach((r,i)=>officeRoomBg(ctx,r,i));
  ctx.setTransform(1,0,0,1,0,0);
}
/* Halftone: the comic printer's dot, used for every shadow. */
function ofDots(ctx,x,y,w,h,color,alpha,step){
  ctx.save();ctx.beginPath();ctx.rect(x,y,w,h);ctx.clip();
  ctx.globalAlpha=alpha;ctx.fillStyle=color;
  for(let j=0,yy=y;yy<y+h+step;yy+=step,j++)for(let xx=x+(j%2?step/2:0);xx<x+w+step;xx+=step){
    ctx.beginPath();ctx.arc(xx,yy,step*.22,0,6.283);ctx.fill()}
  ctx.restore();
}
function officeFloor(ctx,r,st,idx){
  const x=r.x,y=r.y+OF_WALL,w=r.w,h=r.h-OF_WALL,a=st.floor[0],b=st.floor[1];
  ctx.save();ctx.beginPath();ctx.rect(x,y,w,h);ctx.clip();
  ctx.fillStyle=a;ctx.fillRect(x,y,w,h);
  ctx.fillStyle=b;ctx.strokeStyle=b;ctx.lineWidth=2;
  const p=st.pattern;
  if(p==='dots'){ofDots(ctx,x,y,w,h,b,1,14)}
  else if(p==='planks'){for(let yy=y+22,k=0;yy<y+h;yy+=22,k++){ctx.beginPath();ctx.moveTo(x,yy);ctx.lineTo(x+w,yy);ctx.stroke();
      for(let xx=x+(k%2?40:95);xx<x+w;xx+=130){ctx.beginPath();ctx.moveTo(xx,yy-22);ctx.lineTo(xx,yy);ctx.stroke()}}}
  else if(p==='tiles'){for(let yy=y,j=0;yy<y+h;yy+=36,j++)for(let xx=x+(j%2)*36;xx<x+w;xx+=72)ctx.fillRect(xx,yy,36,36)}
  else if(p==='rug'){ofRR(ctx,x+18,y+22,w-36,h-40,18);ctx.fill();ctx.lineWidth=3;ctx.strokeStyle=ofMix(st.accent,a,.45);
    ofRR(ctx,x+28,y+32,w-56,h-60,12);ctx.stroke()}
  else if(p==='grid'){ctx.lineWidth=2;for(let yy=y;yy<y+h;yy+=48)for(let xx=x;xx<x+w;xx+=48){ctx.strokeRect(xx+3,yy+3,42,42);
      [[8,8],[40,8],[8,40],[40,40]].forEach(q=>{ctx.beginPath();ctx.arc(xx+q[0],yy+q[1],1.8,0,6.283);ctx.fill()})}}
  else if(p==='stone'){for(let k=0;k<Math.floor(w*h/1500);k++){const u=ofHash(r.name+k),v=ofHash(k+r.name+'y');
      ctx.beginPath();ctx.ellipse(x+u*w,y+v*h,10+u*9,6+v*5,u*3,0,6.283);ctx.fill()}}
  // the wall's shadow on the floor, in dots
  ofDots(ctx,x,y,w,16,'#000000',.22,7);
  ctx.restore();
}
function officeRoomBg(ctx,r,idx){
  const O=OFFICE,st=O.view.style,col=O.view.colors[r.color]||st.accent,decor=O.view.office.decor;
  officeFloor(ctx,r,st,idx);
  // the wall band, lit from above
  ctx.fillStyle=st.wall;ctx.fillRect(r.x,r.y,r.w,OF_WALL);
  ctx.fillStyle=ofMix(st.wall,'#ffffff',.18);ctx.fillRect(r.x,r.y,r.w,6);
  // the sign first in the reading order — a plaque in the department's colour, inside the
  // wall band — and the windows share out whatever wall is left beside it
  ofFont(ctx,12.5,800);const label=r.name.toUpperCase();
  const tw=Math.min(r.w*.6,ctx.measureText(label).width+22);
  const board=r.kind==='lead'&&decor.includes('whiteboard'), poster=decor.includes('posters')&&r.w>260&&r.kind!=='lead';
  const wx0=r.x+tw+26, wx1=r.x+r.w-(board?r.w*.4:poster?54:12);
  const nwin=Math.max(0,Math.min(3,Math.floor((wx1-wx0)/120)));
  for(let i=0;i<nwin;i++)officeWindow(ctx,wx0+(i+.5)*(wx1-wx0)/nwin-26,r.y+10,52,26,st);
  if(poster){
    const px=r.x+r.w-44;ctx.fillStyle=col;ofRR(ctx,px,r.y+8,30,30,3);ctx.fill();ofInk(ctx,2);
    ofFont(ctx,10,900,true);ctx.fillStyle='#fff';ctx.textAlign='center';ctx.textBaseline='middle';
    ctx.fillText(['POW!','ZAP!','SHIP','WOW!'][Math.floor(ofHash(r.name)*4)],px+15,r.y+23);
  }
  // furniture that never moves
  if(decor.includes('plants')){officePlant(ctx,r.x+r.w-22,r.y+r.h-14,col);if(r.w>300)officePlant(ctx,r.x+22,r.y+r.h-14,col)}
  if(r.kind==='meeting')officeTable(ctx,r);
  if(r.kind==='lounge')officeLounge(ctx,r,decor,st);
  // below the mission board, never behind it
  if(r.kind==='lead'&&decor.includes('bookshelf'))officeShelf(ctx,r.x+r.w-40,r.y+OF_WALL+130+(r.grow||0)*.4);
  // the room's outline, broken for the door
  const dw=46;
  ctx.beginPath();ctx.moveTo(r.door-dw/2,r.y+r.h);ctx.lineTo(r.x+6,r.y+r.h);ctx.arcTo(r.x,r.y+r.h,r.x,r.y,6);
  ctx.arcTo(r.x,r.y,r.x+r.w,r.y,6);ctx.arcTo(r.x+r.w,r.y,r.x+r.w,r.y+r.h,6);ctx.arcTo(r.x+r.w,r.y+r.h,r.x,r.y+r.h,6);
  ctx.lineTo(r.door+dw/2,r.y+r.h);ofInk(ctx,3.4);
  ctx.beginPath();ctx.moveTo(r.x,r.y+OF_WALL);ctx.lineTo(r.x+r.w,r.y+OF_WALL);ofInk(ctx,2.2);
  ctx.fillStyle=ofMix(col,'#000000',.2);ofRR(ctx,r.door-dw/2+6,r.y+r.h-3,dw-12,8,3);ctx.fill();
  ctx.fillStyle=col;ofRR(ctx,r.x+10,r.y+11,tw,24,5);ctx.fill();ofInk(ctx,2.4);
  ofFont(ctx,12.5,800);ctx.fillStyle='#fff';ctx.textAlign='left';ctx.textBaseline='middle';
  ctx.save();ctx.beginPath();ctx.rect(r.x+10,r.y+8,tw-8,32);ctx.clip();
  ctx.fillText(label,r.x+21,r.y+23.5);ctx.restore();
  if((r.kind==='floor'||r.kind==='dept')&&!r.members.length){
    ofFont(ctx,12,600);ctx.fillStyle=ofMix(st.floor[0],OF_INK,.6);ctx.textAlign='center';
    ctx.fillText(O.view.agents.length?'nobody here yet — move someone in with Design':'no specialists yet',r.x+r.w/2,r.y+OF_WALL+80);
  }
}
function officeWindow(ctx,x,y,w,h,st){
  const night=st.pattern==='grid'||ofLum(st.wall)<70;
  ctx.fillStyle=st.pattern==='grid'?'#070b18':night?'#1e1b4b':'#bfe8ff';
  if(st.pattern==='grid'){ctx.beginPath();ctx.ellipse(x+w/2,y+h/2,h/2+3,h/2,0,0,6.283);ctx.fill();ofInk(ctx,2.4);
    ctx.fillStyle='#fff';[[.3,.4],[.6,.25],[.7,.7],[.45,.65]].forEach(q=>ctx.fillRect(x+w/2-h/2+q[0]*h,y+q[1]*h,1.6,1.6));return}
  ofRR(ctx,x,y,w,h,3);ctx.fill();
  if(!night){ctx.fillStyle='#fff';ctx.beginPath();ctx.arc(x+16,y+15,5,0,6.283);ctx.arc(x+22,y+13,6,0,6.283);ctx.arc(x+28,y+16,4.5,0,6.283);ctx.fill()}
  else{ctx.fillStyle='#fde68a';ctx.beginPath();ctx.arc(x+w-13,y+9,4,0,6.283);ctx.fill()}
  ofRR(ctx,x,y,w,h,3);ofInk(ctx,2.2);ctx.beginPath();ctx.moveTo(x+w/2,y);ctx.lineTo(x+w/2,y+h);ofInk(ctx,1.6);
}
function officePlant(ctx,x,y,col){
  ctx.fillStyle='#16a34a';[[-7,-18,8],[6,-20,8],[0,-28,9],[-2,-14,7]].forEach(q=>{ctx.beginPath();ctx.ellipse(x+q[0],y+q[1],q[2]*.62,q[2],q[0]*.05,0,6.283);ctx.fill();ofInk(ctx,1.6)});
  ctx.fillStyle=ofMix(col,'#7c2d12',.55);ofRR(ctx,x-8,y-12,16,14,2);ctx.fill();ofInk(ctx,2);
}
function officeShelf(ctx,x,y){
  ctx.fillStyle='#8b5a2b';ofRR(ctx,x-18,y-40,36,64,3);ctx.fill();ofInk(ctx,2.2);
  const books=['#ef4444','#3b82f6','#f59e0b','#10b981','#a855f7','#f43f5e'];
  for(let s=0;s<3;s++){for(let b=0;b<4;b++){ctx.fillStyle=books[(s*4+b)%books.length];ctx.fillRect(x-14+b*7,y-36+s*21,5,16)}
    ctx.beginPath();ctx.moveTo(x-18,y-19+s*21);ctx.lineTo(x+18,y-19+s*21);ofInk(ctx,1.6)}
}
function officeTable(ctx,r){
  const cx=r.x+r.w/2,cy=r.y+OF_WALL+92+(r.grow||0)*.45;
  ctx.fillStyle='#00000026';ctx.beginPath();ctx.ellipse(cx,cy+10,112,34,0,0,6.283);ctx.fill();
  ctx.fillStyle='#f8fafc';ctx.beginPath();ctx.ellipse(cx,cy,108,30,0,0,6.283);ctx.fill();ofInk(ctx,3);
  ctx.fillStyle='#fde68a';ofRR(ctx,cx-14,cy-6,28,12,2);ctx.fill();ofInk(ctx,1.6);   // the notes nobody reads
}
function officeLounge(ctx,r,decor,st){
  const x=r.x,y=r.y+OF_WALL+(r.grow||0)*.4;
  // the sofa
  ctx.fillStyle=ofMix(st.accent,'#1e293b',.35);ofRR(ctx,x+24,y+40,120,44,10);ctx.fill();ofInk(ctx,2.6);
  ctx.fillStyle=ofMix(st.accent,'#ffffff',.15);ofRR(ctx,x+32,y+58,48,22,6);ctx.fill();ofInk(ctx,1.8);ofRR(ctx,x+88,y+58,48,22,6);ctx.fill();ofInk(ctx,1.8);
  if(decor.includes('coffee')){ctx.fillStyle='#334155';ofRR(ctx,x+r.w-58,y+18,34,46,4);ctx.fill();ofInk(ctx,2.4);
    ctx.fillStyle='#ef4444';ctx.beginPath();ctx.arc(x+r.w-41,y+30,4,0,6.283);ctx.fill();
    ctx.fillStyle='#fff';ofRR(ctx,x+r.w-47,y+46,12,12,2);ctx.fill();ofInk(ctx,1.4)}
  if(decor.includes('arcade')){const ax=x+r.w-100;ctx.fillStyle='#7c3aed';ofRR(ctx,ax,y+10,32,62,4);ctx.fill();ofInk(ctx,2.4);
    ctx.fillStyle='#22d3ee';ofRR(ctx,ax+5,y+18,22,16,2);ctx.fill();ofInk(ctx,1.4)}
  if(decor.includes('bookshelf'))officeShelf(ctx,x+r.w/2+30,y+60);
}

/* ---------------- drawing: every frame ---------------- */
function officeSheet(key){
  const a=(typeof AVATARS!=='undefined')&&AVATARS.by[key],v=a?a.v:0;
  let e=OFFICE.sheets[key];
  if(!e||e.v!==v){const img=new Image();img.decoding='async';img.onload=officeKick;
    img.src=avatarSrc(key,{sheet:1});e=OFFICE.sheets[key]={img,v}}
  return e.img.complete&&e.img.naturalWidth?e.img:null;
}
function officeDraw(){
  const O=OFFICE,ctx=O.ctx;if(!ctx||!O.L)return;
  const k=O.dpr*O.s;
  ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,O.cv.width,O.cv.height);
  if(O.bg)ctx.drawImage(O.bg,0,0);
  ctx.setTransform(k,0,0,k,0,0);
  officeBoard(ctx);
  // desks in depth order, each with its owner if the owner is sitting at it
  const ps=Object.values(O.people).sort((a,b)=>a.home.y-b.home.y);
  ps.forEach(p=>officeDesk(ctx,p));
  // everybody on their feet, back to front
  Object.values(O.people).filter(p=>p.mode!=='seat').sort((a,b)=>a.y-b.y).forEach(p=>officeSprite(ctx,p,p.x,p.y,false));
  if(O.pet)officePetDraw(ctx);
  O.papers.forEach(pp=>officePaperDraw(ctx,pp));
  O.bursts.forEach(b=>officeBurstDraw(ctx,b));
  O.pops.forEach(b=>officePopDraw(ctx,b));
  // newest words on top, and every balloon placed clear of the ones already drawn — two
  // agents talking at once must read as two balloons, not one smudge
  const placed=[];
  Object.values(O.people).filter(p=>p.say).sort((a,b)=>b.say.at-a.say.at).forEach(p=>officeBubble(ctx,p,placed));
}
/* The mission board in the corner office: what is running, in marker. */
function officeBoard(ctx){
  const O=OFFICE,r=officeRoomOf('lead');if(!r||!O.view.office.decor.includes('whiteboard'))return;
  const x=r.x+r.w*.62,y=r.y+6,w=r.w*.34,h=72;
  ctx.fillStyle='#ffffff';ofRR(ctx,x,y,w,h,4);ctx.fill();ofInk(ctx,2.6);
  ofFont(ctx,10,900);ctx.fillStyle='#ef4444';ctx.textAlign='left';ctx.textBaseline='top';ctx.fillText('MISSIONS',x+8,y+7);
  const names=Object.keys(O.missions).slice(0,3);
  ofFont(ctx,10.5,700);ctx.fillStyle='#1d4ed8';
  if(!names.length){ctx.fillStyle='#94a3b8';ctx.fillText('nothing running',x+8,y+26)}
  names.forEach((n,i)=>{const t=n.length>18?n.slice(0,17)+'…':n;ctx.fillText('▸ '+t,x+8,y+24+i*15)});
}
function officeDesk(ctx,p){
  const O=OFFICE,x=p.home.x,y=p.home.y,col=O.view.colors[p.room.color]||O.view.style.accent,st=O.view.style;
  const deskTop={pop:'#ffffff',loft:'#a0673a',tower:'#f1f5f9',cozy:'#d9a36a',space:'#9aa6b8',garden:'#ead9ad',night:'#6b5a80'}[O.view.office.style]||'#fff';
  const W=p.lead?128:104, now=performance.now(), lit=!!p.busy;
  // the chair back, then its owner, then the desk in front of them
  ctx.fillStyle=ofMix(col,'#1e293b',.45);ofRR(ctx,x-22,y-40,44,46,10);ctx.fill();ofInk(ctx,2.2);
  if(p.mode==='seat')officeSprite(ctx,p,x,y+30,true);
  ctx.fillStyle=deskTop;ofRR(ctx,x-W/2,y-4,W,24,4);ctx.fill();ofInk(ctx,2.6);
  ctx.fillStyle=ofMix(deskTop,'#000000',.18);ofRR(ctx,x-W/2+4,y+20,W-8,30,3);ctx.fill();ofInk(ctx,2.6);
  ofDots(ctx,x-W/2+5,y+36,W-10,13,'#000000',.18,6);
  // the monitor beside them: dark until there is work, then lit in the department's colour
  const mx=x-W/2+6,my=y-30;
  ctx.fillStyle='#334155';ctx.fillRect(mx+14,my+22,6,10);
  ctx.fillStyle=lit?ofMix(col,'#ffffff',.25):'#1f2937';ofRR(ctx,mx,my,34,24,3);ctx.fill();ofInk(ctx,2.2);
  if(lit){ctx.fillStyle='#ffffffcc';for(let i=0;i<3;i++){const wl=8+((Math.sin(O.t*6+i*2+p.phase)+1)*8);ctx.fillRect(mx+5,my+5+i*6,wl,2.4)}}
  if(p.lead){ctx.fillStyle=lit?ofMix(col,'#ffffff',.25):'#1f2937';ofRR(ctx,x+W/2-40,my,34,24,3);ctx.fill();ofInk(ctx,2.2)}
  // a mug, so the desk is somebody's
  ctx.fillStyle=col;ofRR(ctx,x+W/2-(p.lead?52:20),y+2,10,11,2);ctx.fill();ofInk(ctx,1.6);
  // the nameplate on the desk front
  ofFont(ctx,11.5,800);const nm=p.label.length>14?p.label.slice(0,13)+'…':p.label;
  const tw=Math.min(W-10,ctx.measureText(nm).width+16);
  ctx.fillStyle=lit?col:'#ffffff';ofRR(ctx,x-tw/2,y+26,tw,18,4);ctx.fill();ofInk(ctx,1.8);
  ctx.fillStyle=lit?'#ffffff':OF_INK;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(nm,x,y+35.5);
  // working: what it answers on, in a tag above the monitor (the Crew stage's rule)
  const brain=O.brains[p.key];
  // hidden while a burst is up: the tool that just ran is the news, the brain is not
  if(lit&&brain&&p.mode==='seat'&&!p.say&&!O.bursts.some(b=>b.p===p)){ofFont(ctx,9.5,800);const bw=ctx.measureText(brain).width+18;
    ctx.fillStyle=OF_INK;ofRR(ctx,x-bw/2,y-78,bw,15,7);ctx.fill();
    ctx.fillStyle=`rgba(244,63,94,${.55+.45*Math.sin(now/180)})`;ctx.fillRect(x-bw/2+6,y-73,4,4);
    ctx.fillStyle='#fff';ctx.textAlign='left';ctx.fillText(brain,x-bw/2+13,y-70)}
}
/* A character from the server's sheet: stand, blink, one arm up, the other. Whole
   device pixels per sprite pixel, smoothing off — or it is not pixel art. */
function officeSprite(ctx,p,x,feet,seated){
  const O=OFFICE,img=officeSheet(p.key);
  const u=Math.max(2,Math.round(OF_K*O.s*O.dpr*(p.lead?1.1:1)));
  const t=O.t,still=O.static,ph=p.phase;
  const walking=p.mode==='walk'&&!still;
  const blink=!still&&((t*.29+ph)%1)<.05;
  const frame=still?0:walking?(Math.floor(t*7)%2?3:2):p.hand?2:(p.busy&&seated)?(Math.floor(t*5+ph)%2?3:2):blink?1:0;
  const bob=walking?Math.floor(t*7)%2:(!still&&Math.sin(t*1.5+ph)>.4?1:0);
  const k=O.dpr*O.s, dx=Math.round(x*k)-8*u, dy=Math.round(feet*k)-26*u-bob*u;
  if(!seated){ctx.fillStyle='#00000033';ctx.beginPath();ctx.ellipse(x,feet+1,15,4,0,0,6.283);ctx.fill()}
  if(!img)return;
  ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.imageSmoothingEnabled=false;
  ctx.drawImage(img,frame*16,0,16,26,dx,dy,16*u,26*u);ctx.restore();
  if(!seated){ofFont(ctx,10,800);ctx.fillStyle=OF_INK;ctx.textAlign='center';ctx.textBaseline='top';
    ctx.fillText(p.label.length>14?p.label.slice(0,13)+'…':p.label,x,feet+5)}
}
/* A comic balloon: white, inked, a tail to the speaker's head. Thoughts are clouds. */
function officeBubble(ctx,p,placed){
  const O=OFFICE,s=p.say,now=performance.now(),age=(now-s.at)/s.ms;
  const a=age>.85?Math.max(0,(1-age)/.15):1, h0=officeHead(p);
  ofFont(ctx,11.5,700);
  const maxW=O.L.W<700?150:200, lines=[];let cur='';
  s.text.split(' ').forEach(wd=>{const t=cur?cur+' '+wd:wd;if(ctx.measureText(t).width>maxW&&cur){lines.push(cur);cur=wd}else cur=t});
  if(cur)lines.push(cur);
  if(lines.length>3){lines.length=3;lines[2]=lines[2].replace(/\s*\S*$/,'')+'…'}
  const bw=Math.min(maxW,Math.max(...lines.map(l=>ctx.measureText(l).width)))+20, bh=lines.length*14+12;
  let bx=Math.max(4,Math.min(O.L.W-bw-4,h0.x-bw/2+ (p.key.length%2?14:-14))), by=h0.y-bh-18;
  const hit=q=>placed&&placed.find(o=>bx<o.x+o.w+4&&bx+bw+4>o.x&&by<o.y+o.h+4&&by+bh+4>o.y);
  for(let n=0,o;n<6&&(o=hit());n++){
    // try beside it first (a tail can reach sideways), then above it
    const right=o.x+o.w+6, left=o.x-bw-6;
    if(right+bw<O.L.W-4&&Math.abs(right-h0.x)<bw+60&&!placed.some(z=>z!==o&&right<z.x+z.w&&right+bw>z.x&&by<z.y+z.h&&by+bh>z.y))bx=right;
    else if(left>4&&Math.abs(left+bw-h0.x)<bw+60)bx=left;
    else by=o.y-bh-6;
  }
  if(by<4)by=4;
  if(placed)placed.push({x:bx,y:by,w:bw,h:bh});
  ctx.globalAlpha=a;
  const shout=s.kind==='shout';
  ctx.fillStyle=shout?'#fff7d6':'#ffffff';
  if(s.kind==='think'){
    ofRR(ctx,bx,by,bw,bh,bh/2);ctx.fill();ofInk(ctx,2.2);
    [[0,10,5],[-8,16,3]].forEach(q=>{ctx.beginPath();ctx.arc(h0.x+q[0],by+bh+q[1]-4,q[2],0,6.283);ctx.fillStyle='#fff';ctx.fill();ofInk(ctx,1.8)});
  }else{
    ofRR(ctx,bx,by,bw,bh,10);ctx.fill();
    // the tail: drawn over the outline so the balloon and its tail are one shape
    const tx=Math.max(bx+12,Math.min(bx+bw-12,h0.x));
    ctx.beginPath();ctx.moveTo(tx-7,by+bh-1);ctx.lineTo(h0.x,h0.y-4);ctx.lineTo(tx+7,by+bh-1);ctx.closePath();ctx.fill();
    ofRR(ctx,bx,by,bw,bh,10);ofInk(ctx,shout?3:2.2);
    ctx.beginPath();ctx.moveTo(tx-7,by+bh);ctx.lineTo(h0.x,h0.y-4);ctx.lineTo(tx+7,by+bh);ofInk(ctx,2.2);
    ctx.fillStyle=shout?'#fff7d6':'#ffffff';ctx.fillRect(tx-5.5,by+bh-3,11,3);
  }
  ctx.fillStyle=OF_INK;ctx.textAlign='left';ctx.textBaseline='top';ofFont(ctx,11.5,shout?800:700);
  lines.forEach((l,i)=>ctx.fillText(l,bx+10,by+7+i*14));
  ctx.globalAlpha=1;
}
/* A tool call: a jagged burst with the comic word, and the real tool name under it. */
function officeBurstDraw(ctx,b){
  const now=performance.now(),q=(now-b.at)/1500,p=b.p,h0=officeHead(p);
  const grow=OFFICE.static?1:Math.min(1,q*6), a=q>.7?(1-q)/.3:1, x=h0.x+34, y=h0.y-6-q*16;
  ctx.save();ctx.globalAlpha=Math.max(0,a);ctx.translate(x,y);ctx.rotate(b.rot);ctx.scale(grow,grow);
  ctx.beginPath();for(let i=0;i<18;i++){const r=i%2?15:25,an=i/18*6.283;ctx.lineTo(Math.cos(an)*r*1.5,Math.sin(an)*r)}
  ctx.closePath();ctx.fillStyle='#ffe14d';ctx.fill();ofInk(ctx,2.4);
  ofFont(ctx,12,900,true);ctx.fillStyle='#e11d48';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(b.word,0,0);
  ctx.restore();
  if(b.word.replace('!','').toLowerCase()!==String(b.tool).replace(/_/g,' ')){
    ctx.globalAlpha=Math.max(0,a);ofFont(ctx,9,700);ctx.fillStyle=OF_INK;ctx.textAlign='center';ctx.fillText(String(b.tool),x,y+30);ctx.globalAlpha=1}
}
function officePopDraw(ctx,b){
  const q=(performance.now()-b.at)/1100,h0=officeHead(b.p),s=OFFICE.static?1:Math.min(1,q*5)*(1+.15*Math.sin(q*12));
  ctx.save();ctx.globalAlpha=q>.75?(1-q)*4:1;ctx.translate(h0.x-26,h0.y-10);ctx.scale(s,s);
  ofFont(ctx,26,900,true);ctx.textAlign='center';ctx.textBaseline='middle';ctx.lineWidth=5;ctx.strokeStyle=OF_INK;
  ctx.strokeText(b.text,0,0);ctx.fillStyle='#ffd23f';ctx.fillText(b.text,0,0);ctx.restore();
}
function officePaperDraw(ctx,pp){
  const q=Math.min(1,(performance.now()-pp.at)/pp.ms),e=1-Math.pow(1-q,2);
  const to=pp.to.key?officeHead(pp.to):pp.to, x=pp.from.x+(to.x-pp.from.x)*e, y=pp.from.y+(to.y-pp.from.y)*e-Math.sin(q*Math.PI)*60;
  ctx.save();ctx.translate(x,y);ctx.rotate(q*6);
  ctx.fillStyle='#ffffff';ctx.fillRect(-9,-12,18,24);ctx.strokeStyle=OF_INK;ctx.lineWidth=2;ctx.strokeRect(-9,-12,18,24);
  ctx.fillStyle='#94a3b8';for(let i=0;i<4;i++)ctx.fillRect(-6,-8+i*5,12-(i%2)*4,1.6);
  ctx.restore();
}
/* ---------------- the pet: decor that is visibly not an agent ---------------- */
function officePetNew(){
  const r=officeRoomOf('lounge')||officeRoomOf('floor')||OFFICE.L.rooms[OFFICE.L.rooms.length-1];
  return {kind:OFFICE.view.office.pet,room:r,x:r.x+r.w*.6,y:r.y+r.h-40,tx:0,ty:0,wait:2,walking:false,dir:1};
}
function officePetStep(dt){
  const p=OFFICE.pet,r=p.room;if(!r||OFFICE.static)return;
  if(!OFFICE.L.rooms.includes(r)){OFFICE.pet=officePetNew();return}
  if(p.walking){const dx=p.tx-p.x,dy=p.ty-p.y,l=Math.hypot(dx,dy);
    if(l<2){p.walking=false;p.wait=3+Math.random()*6}else{p.x+=dx/l*40*dt;p.y+=dy/l*40*dt;p.dir=dx<0?-1:1}}
  else if((p.wait-=dt)<=0){p.tx=r.x+30+Math.random()*(r.w-60);p.ty=r.y+OF_WALL+60+Math.random()*(r.h-OF_WALL-80);p.walking=true}
}
function officePetDraw(ctx){
  const p=OFFICE.pet,x=p.x,y=p.y,b=p.walking?Math.abs(Math.sin(OFFICE.t*10))*2:0;
  ctx.save();ctx.translate(x,y-b);ctx.scale(p.dir,1);
  ctx.fillStyle='#00000030';ctx.beginPath();ctx.ellipse(0,b+1,14,3.5,0,0,6.283);ctx.fill();
  if(p.kind==='robot'){ctx.fillStyle='#cbd5e1';ofRR(ctx,-11,-20,22,18,4);ctx.fill();ofInk(ctx,2);ctx.fillStyle='#22d3ee';ctx.fillRect(-6,-15,4,4);ctx.fillRect(3,-15,4,4);
    ctx.beginPath();ctx.moveTo(0,-20);ctx.lineTo(0,-27);ofInk(ctx,2);ctx.fillStyle='#ef4444';ctx.beginPath();ctx.arc(0,-28,2.5,0,6.283);ctx.fill();ctx.restore();return}
  const fur=p.kind==='cat'?'#f59e0b':'#a16207';
  ctx.fillStyle=fur;ctx.beginPath();ctx.ellipse(-2,-8,12,7,0,0,6.283);ctx.fill();ofInk(ctx,2);
  ctx.beginPath();ctx.arc(10,-14,6.5,0,6.283);ctx.fill();ofInk(ctx,2);
  if(p.kind==='cat'){ctx.beginPath();ctx.moveTo(6,-18);ctx.lineTo(7,-24);ctx.lineTo(11,-19);ctx.moveTo(11,-19);ctx.lineTo(14,-23);ctx.lineTo(15,-17);ctx.fill();ofInk(ctx,1.6);
    ctx.beginPath();ctx.moveTo(-13,-9);ctx.quadraticCurveTo(-22,-16,-18,-24);ofInk(ctx,2.4)}
  else{ctx.beginPath();ctx.ellipse(6,-13,2.5,5,.4,0,6.283);ctx.fill();ofInk(ctx,1.6);ctx.beginPath();ctx.moveTo(-13,-10);ctx.lineTo(-19,-15);ofInk(ctx,2.4)}
  ctx.fillStyle=OF_INK;ctx.fillRect(11,-15,1.8,1.8);
  ctx.restore();
}

/* ---------------- a tap: who is this, and ask them ---------------- */
function officeTap(e){
  const O=OFFICE;if(!O.L)return;
  const r=O.cv.getBoundingClientRect(),x=(e.clientX-r.left)/O.s,y=(e.clientY-r.top)/O.s;
  const hit=Object.values(O.people).find(p=>{const h=officeHead(p);return Math.abs(x-h.x)<34&&y>h.y-34&&y<h.y+60});
  if(!hit)return;
  const i=O.w.el.querySelector('.of-chat .cp-in');
  if(hit.key!=='@agent'&&i){i.value='@'+hit.key+' ';i.focus();
    O.w.el.querySelector('.of-wrap').classList.add('chat-open')}
  officeSay(hit,hit.busy?'busy — ask away':(hit.key==='@agent'?'what shall we do?':'yes?'),'say',2200);
}
function officeEmpty(){
  const el=OFFICE.w&&OFFICE.w.el.querySelector('.of-empty');if(!el)return;
  const none=!OFFICE.view.agents.length;
  el.hidden=!none;
  if(none)el.innerHTML=`<b>Your office has one person in it: ${esc(officeName('@agent'))}.</b>
    <span>Specialists take a desk here as soon as they exist. Ask for one in the chat — “make me a researcher and an analyst, put them in a Research department”.</span>`;
}

/* ---------------- Design: how the office looks, and who sits where ---------------- */
function officeDesign(open){
  const O=OFFICE,el=O.w&&O.w.el.querySelector('.of-design');if(!el)return;
  if(open&&O.visiting!==undefined)officeVisit(null);   // one panel over the office at a time
  O.design=open;el.hidden=!open;
  O.w.el.querySelector('.of-dz').classList.toggle('on',open);
  if(open)officeDesignPaint();
}
function officeDesignPaint(){
  const O=OFFICE,el=O.w&&O.w.el.querySelector('.of-design'),v=O.view;if(!el||!v)return;
  const of=v.office,depts=of.departments;
  const where={};depts.forEach(d=>d.members.forEach(m=>where[m]=d.name));
  const opt=(val,label,sel)=>`<option value="${esc(val)}"${sel?' selected':''}>${esc(label)}</option>`;
  el.innerHTML=`<div class="of-dh"><b>Design your office</b><button class="of-x" aria-label="Close">✕</button></div>
    <div class="of-sec">Describe it</div>
    <div class="of-row"><input class="of-ask" placeholder="a cosy space station with a research wing"><button class="endbtn primary of-askb">Design it</button></div>
    <div class="of-said mut" aria-live="polite"></div>
    <div class="of-sec">Style</div>
    <div class="of-styles">${Object.entries(v.styles).map(([k,s])=>`<button class="of-style${k===of.style?' on':''}" data-st="${k}" title="${esc(s.blurb)}">
      <i style="background:linear-gradient(135deg,${s.wall} 0 38%,${s.floor[0]} 38% 72%,${s.accent} 72%)"></i><span>${esc(s.label)}</span></button>`).join('')}</div>
    <div class="of-sec">Name on the door</div>
    <div class="of-row"><input class="of-name" maxlength="24" value="${esc(of.name)}"></div>
    <div class="of-sec">Departments <span class="mut">${depts.length} of ${v.max_departments}</span></div>
    ${depts.map((d,i)=>`<div class="of-row of-dept" data-i="${i}"><i class="of-sw" style="background:${v.colors[d.color]}"></i>
      <input class="of-dn" maxlength="24" value="${esc(d.name)}" aria-label="Department name">
      <select class="of-dc" aria-label="Colour">${Object.keys(v.colors).map(c=>opt(c,c,c===d.color)).join('')}</select>
      <button class="endbtn of-drm" aria-label="Remove ${esc(d.name)}">✕</button></div>`).join('')}
    ${depts.length<v.max_departments?`<div class="of-row"><input class="of-newd" maxlength="24" placeholder="New department, e.g. Research"><button class="endbtn of-addd">Add</button></div>`:''}
    <div class="of-sec">Who sits where</div>
    ${v.agents.length?v.agents.map(a=>`<div class="of-row of-who">${typeof avatarImg==='function'?avatarImg(a,'av-who'):''}<span class="of-an">${esc(a)}</span>
      <select class="of-mv" data-a="${esc(a)}" aria-label="Department for ${esc(a)}">${opt('','Open floor',!where[a])}${depts.map(d=>opt(d.name,d.name,where[a]===d.name)).join('')}</select></div>`).join('')
      :'<div class="mut of-row">No specialists yet — ask for one in the chat and they take a desk.</div>'}
    <div class="of-sec">Shared rooms</div>
    <div class="of-chips">${[['meeting','Meeting room — huddles gather here'],['lounge','Lounge']].map(([k,l])=>`<button class="of-chip${of[k]?' on':''}" data-flag="${k}" aria-pressed="${!!of[k]}">${esc(l)}</button>`).join('')}</div>
    <div class="of-sec">Decor</div>
    <div class="of-chips">${v.decor.map(d=>`<button class="of-chip${of.decor.includes(d)?' on':''}" data-dec="${d}" aria-pressed="${of.decor.includes(d)}">${esc(d)}${d==='whiteboard'?' (mission board)':''}</button>`).join('')}</div>
    <div class="of-sec">Office pet</div>
    <div class="of-chips">${v.pets.map(p=>`<button class="of-chip${of.pet===p?' on':''}" data-pet="${p}">${esc(p)}</button>`).join('')}</div>`;
  const q=s=>el.querySelector(s),qa=s=>el.querySelectorAll(s);
  q('.of-x').onclick=()=>officeDesign(false);
  // the server designs it (not the chat): a turn forwarded to an executor has no set_office
  const ask=()=>officeDescribe(q('.of-ask'),q('.of-said'),q('.of-askb'));
  q('.of-askb').onclick=ask;q('.of-ask').onkeydown=e=>{if(e.key==='Enter')ask()};
  qa('.of-style').forEach(b=>b.onclick=()=>officeSave({style:b.dataset.st}));
  q('.of-name').onchange=e=>officeSave({name:e.target.value});
  const deptsNow=()=>[...qa('.of-dept')].map(r=>{const d=depts[+r.dataset.i];
    return {name:r.querySelector('.of-dn').value,color:r.querySelector('.of-dc').value,members:d.members}});
  qa('.of-dn,.of-dc').forEach(x=>x.onchange=()=>officeSave({departments:deptsNow()}));
  qa('.of-drm').forEach(b=>b.onclick=()=>{const i=+b.closest('.of-dept').dataset.i;
    officeSave({departments:deptsNow().filter((_,j)=>j!==i)})});
  const add=()=>{const n=q('.of-newd').value.trim();if(n)officeSave({departments:[...deptsNow(),{name:n,members:[]}]})};
  if(q('.of-addd')){q('.of-addd').onclick=add;q('.of-newd').onkeydown=e=>{if(e.key==='Enter')add()}}
  qa('.of-mv').forEach(s=>s.onchange=async()=>{
    const r=await fetch('/api/office/place',{method:'PUT',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({agent:s.dataset.a,department:s.value})});
    const d=await r.json();if(!r.ok)return toast(d.error||'could not move them');
    officeLog(`${s.dataset.a} moved to ${s.value||'the open floor'}`);OFFICE.view=d;officeLayout();officeDesignPaint()});
  qa('[data-flag]').forEach(b=>b.onclick=()=>officeSave({[b.dataset.flag]:!of[b.dataset.flag]}));
  qa('[data-dec]').forEach(b=>b.onclick=()=>{const d=b.dataset.dec;
    officeSave({decor:of.decor.includes(d)?of.decor.filter(x=>x!==d):[...of.decor,d]})});
  qa('[data-pet]').forEach(b=>b.onclick=()=>officeSave({pet:b.dataset.pet}));
}
/* "Describe it", in the Office, Settings → Appearance and the setup step: one call to
   /api/office/design, which asks the machine's brain to choose from the closed set and
   says when it matched the words instead. Applied at once, so the answer is an Undo. */
async function officeDescribe(input,said,btn){
  const t=(input&&input.value||'').trim();if(!t){toast('describe it first — a few words is enough');return null}
  if(btn)btn.disabled=true;if(said)said.textContent='designing…';
  let d;
  try{d=await apiJSON('/api/office/design',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({description:t})})}
  catch(e){if(said)said.textContent=e.message;if(btn)btn.disabled=false;return null}
  if(btn)btn.disabled=false;input.value='';
  const how=d.how==='brain'?`designed by ${d.who||'your agent'}`:d.said;
  const drop=(d.dropped||[]).length?` · not used: ${d.dropped.join(', ')}`:'';
  if(OFFICE.w){OFFICE.view=d;officeLayout();if(OFFICE.design)officeDesignPaint()}
  // the design panel repaints itself above, so the line may be a fresh element now
  if(said&&!said.isConnected&&OFFICE.w)said=OFFICE.w.el.querySelector('.of-said');
  if(said){said.innerHTML=`${esc(how)} — ${esc(d.office.name)}, ${esc((d.styles[d.office.style]||{}).label||d.office.style)}${esc(drop)} <button class="endbtn of-undo">Undo</button>`;
    said.querySelector('.of-undo').onclick=async()=>{await officeSave(d.previous);
      const s2=said.isConnected?said:OFFICE.w&&OFFICE.w.el.querySelector('.of-said');if(s2)s2.textContent='put back as it was'}}
  officeLog('office redesigned: '+t);
  return d;
}
/* Visit a linked team's office. Their answer is the look, their lead and ONLY the
   agents this link may ask (fabric.office_for_link on their side, cleaned by
   teamlink.clean_office on ours) and the picture is drawn HERE by our painter, so
   nothing they send reaches this page as anything but a value. A person in it is a
   door to a chat: one of YOUR agents carries the question (linkedAsk), because that
   is the path the matrix and their gate already govern.
   `label`: '' opens the list, a label visits it, null closes the panel. */
async function officeVisit(label){
  const O=OFFICE,el=O.w&&O.w.el.querySelector('.of-visit');if(!el)return;
  if(label===null){el.hidden=true;O.visiting=undefined;O.w.el.querySelector('.of-vz').classList.remove('on');return}
  if(O.design)officeDesign(false);
  el.hidden=false;O.visiting=label;O.w.el.querySelector('.of-vz').classList.add('on');
  el.innerHTML=`<div class="of-dh"><b>Visit a linked team</b><button class="of-x" aria-label="Close">✕</button></div><div class="of-vbody mut">…</div>`;
  el.querySelector('.of-x').onclick=()=>officeVisit(null);
  const body=el.querySelector('.of-vbody');
  let links;try{links=(await apiJSON('/api/team/links')).links||[]}catch(e){body.textContent=e.message;return}
  if(!links.length){body.innerHTML=`No linked teams yet. A link connects your team with another Bento, or another account here —
      <button class="endbtn" onclick="openLinkedTeams()">Link a team</button>`;return}
  const face=l=>{const id=l.peer_identity||{};return id.agent?avatarRecipeImg(id.agent,'',(id.agent_name||l.label)):''};
  const list=links.map(l=>`<button class="of-vteam${l.label===label?' on':''}" data-l="${esc(l.label)}">${face(l)}
      <span class="grow"><b>${esc(l.label)}</b> <span class="mut">${l.kind==='account'?'an account here':'another machine'}</span></span></button>`).join('');
  if(!label){body.classList.remove('mut');body.innerHTML=list;
    body.querySelectorAll('.of-vteam').forEach(b=>b.onclick=()=>officeVisit(b.dataset.l));return}
  body.innerHTML=list+'<div class="of-vat mut">knocking…</div>';
  body.querySelectorAll('.of-vteam').forEach(b=>b.onclick=()=>officeVisit(b.dataset.l));
  const at=body.querySelector('.of-vat');
  let v;try{v=await apiJSON('/api/team/links/'+encodeURIComponent(label)+'/office')}catch(e){at.textContent=e.message;return}
  if(O.visiting!==label)return;
  at.classList.remove('mut');
  const people=v.rows.filter(r=>r.key!=='@agent');
  const lead=v.rows.find(r=>r.key==='@agent');
  at.innerHTML=`<img class="of-vpic" alt="${esc(v.office.name)}, ${esc(label)}'s office, with the people you may ask" src="/api/team/links/${encodeURIComponent(label)}/office.png?t=${Date.now()}">
    ${lead?`<div class="of-vwho">${avatarRecipeImg(lead.recipe,'',lead.label)}<span class="grow"><b>${esc(lead.label)}</b> <span class="mut">their lead</span></span></div>`:''}
    ${people.map(r=>`<div class="of-vwho">${avatarRecipeImg(r.recipe,'',r.label)}<span class="grow"><b>${esc(r.label)}</b>
        <span class="mut">${r.working?'busy':'free'}</span></span><button class="endbtn" data-ask="${esc(r.key)}">Ask ${esc(r.label)}</button></div>`).join('')
      ||`<p class="mut">None of their agents may be asked over this link yet — that is their cell to tick, on their side.</p>`}
    <p class="mut">What you see is what this link lets you ask, nothing more. A question goes through one of your agents, under your matrix, and is answered under theirs.</p>`;
  at.querySelectorAll('[data-ask]').forEach(b=>b.onclick=()=>linkedAsk(b.dataset.ask,label));
}
/* Start a chat with somebody on a linked team: Chat opens with the question addressed
   to one of YOUR specialists, who asks them (ask_agent → the matrix → their gate).
   Prefilled, never sent — the person finishes the sentence. With no specialist here
   there is nobody to carry it, and the toast says so with the door to make one. */
async function linkedAsk(who,label){
  let mine=[];
  try{mine=((await apiJSON('/api/subagents')).subagents||[]).filter(s=>s.enabled!==false).map(s=>s.name)}catch(e){}
  if(!mine.length)return toast('agents on another team are reached through one of yours — make a specialist first',
    {label:'New agent',go:()=>{openApp('settings');setTimeout(()=>typeof agentEdit==='function'&&agentEdit(''),400)}});
  const carrier=mine.includes('researcher')?'researcher':mine[0];
  openApp('chat');
  setTimeout(()=>{const i=$('#input');if(i){i.value=`@${carrier} ask ${who}@${label}: `;i.focus();i.dispatchEvent(new Event('input'))}},250);
  toast(`finish the question — @${carrier} carries it to ${who} on ${label}`);
}
/* Snap: the roll-call picture (who is at work, as /office draws it) to Telegram and
   WhatsApp, whichever are set up. With neither, the refusal says which to set up and
   the picture is still one tap away — never a button that does nothing. */
async function officeSnap(){
  const b=OFFICE.w&&OFFICE.w.el.querySelector('.of-snap');if(b)b.disabled=true;
  try{
    const r=await fetch('/api/office/snap',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    const d=await r.json().catch(()=>({}));
    if(r.status===404)return toast('this AgentOS server is running older code than this page — restart it to snap',{kind:'err'});
    if(!r.ok)return toast('could not send it — '+(d.error||'HTTP '+r.status),
      {kind:'warn',label:'Open the picture',go:()=>window.open('/api/office/rollcall.png?t='+Date.now(),'_blank')});
    toast('✓ the office, sent to '+d.sent.join(' and ')+((d.notes||[]).length?' · '+d.notes.join(' · '):''));
    officeLog('snapped to '+d.sent.join(' and '));
  }finally{if(b)b.disabled=false}
}
/* Settings → Appearance → Office. The Office window's own Design panel is the full
   editor; this is the part that belongs with the look. */
async function officeSettingsPaint(){
  const box=document.getElementById('s-office');if(!box)return;
  let v;try{v=await apiJSON('/api/office')}catch(e){box.innerHTML='<p class="mut">could not load the office — '+esc(e.message)+'</p>';return}
  OFFICE.view=OFFICE.view||v;
  const of=v.office,opt=(val,label,sel)=>`<option value="${esc(val)}"${sel?' selected':''}>${esc(label)}</option>`;
  box.innerHTML=`<div class="prow"><div class="pl">Style<small id="s-of-blurb">${esc((v.styles[of.style]||{}).blurb||'')}</small></div>
      <div class="pc"><select id="s-of-style" aria-label="Office style">${Object.entries(v.styles).map(([k,st])=>opt(k,st.label,k===of.style)).join('')}</select></div></div>
    <div class="prow"><div class="pl">Name on the door</div><div class="pc"><input id="s-of-name" maxlength="24" value="${esc(of.name)}"></div></div>
    <div class="prow"><div class="pl">Office pet</div><div class="pc"><select id="s-of-pet" aria-label="Office pet">${v.pets.map(p=>opt(p,p,p===of.pet)).join('')}</select></div></div>
    <div class="prow"><div class="pl">Describe it<small>Your agent chooses a style, name, rooms, decor and pet from what you write; with no brain set up, the words are matched instead, and it says so.</small></div>
      <div class="pc"><input id="s-of-ask" maxlength="300" placeholder="a cosy space station with a research wing"><button class="endbtn" id="s-of-askb">Design it</button></div></div>
    <div class="prow"><div class="pl"><span class="mut" id="s-of-said" aria-live="polite"></span></div>
      <div class="pc"><button class="endbtn" onclick="openApp('office')">Open the Office</button></div></div>`;
  const put=async patch=>{await officeSave(patch);officeSettingsPaint()};
  box.querySelector('#s-of-style').onchange=e=>put({style:e.target.value});
  box.querySelector('#s-of-name').onchange=e=>put({name:e.target.value});
  box.querySelector('#s-of-pet').onchange=e=>put({pet:e.target.value});
  const ask=async()=>{const d=await officeDescribe(box.querySelector('#s-of-ask'),box.querySelector('#s-of-said'),box.querySelector('#s-of-askb'));
    if(!d)return;box.querySelector('#s-of-style').value=d.office.style;
    box.querySelector('#s-of-blurb').textContent=(d.styles[d.office.style]||{}).blurb||'';box.querySelector('#s-of-name').value=d.office.name;
    box.querySelector('#s-of-pet').value=d.office.pet};
  box.querySelector('#s-of-askb').onclick=ask;box.querySelector('#s-of-ask').onkeydown=e=>{if(e.key==='Enter')ask()};
}
async function officeSave(patch){
  try{
    const r=await fetch('/api/office',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)});
    const d=await r.json();
    if(!r.ok)return toast(d.error||'could not change the office');
    if(d.dropped&&d.dropped.length)toast('not placed — nobody here is called '+d.dropped.join(', '));
    OFFICE.view=d;officeLayout();officeDesignPaint();
  }catch(e){toast('could not change the office')}
}
