/* ================= Crew: the roster, drawn, and it is the real one =================
   The third scene of the immersive look (Settings → Appearance → Immersive →
   Scene). A shallow stage across the lower third: the agent in the middle, and
   beside it ONE FIGURE PER SUBAGENT THIS MACHINE ACTUALLY HAS. They rest, they
   look up when a turn starts, and the one that is working steps forward to the
   work line with the tool it just called named above its head.

   Why this shape, and not an office floor with sprites:

   - **Every figure is a real principal.** The roster is /api/subagents, the same
     list the Team app shows. Nothing invented, nobody added for the look. With
     no subagents you get the agent alone and one line saying so — which is the
     honest answer, and a door to building one. A cast of colleagues who do not
     exist would be the dead control this project's honesty rules forbid,
     wearing a friendlier face.
   - **Every movement is an event.** A figure steps forward because a
     `fabric_event` named it, raises its arms because a `tool_start` fired, and
     sits down on `flow_done`. If an animation here does not tell you something
     a text label would not have told you faster, it should not be drawn.
   - **Drawn, not loaded.** Bodies are arcs and rounded rects mixed from the
     theme's own tokens, with build and hue derived from a hash of the name, so
     the same specialist looks the same every time. No tileset, no sprite sheet,
     no character pack — which is also why this scene raises no asset-licence
     question and adds no bytes to the wheel.

   Cost, and where it stops: the same budget as the Movement scene, because it
   is the same loop. One viewport canvas, at most 20 frames a second and 12 when
   idle, ~20 short strokes per figure and at most nine figures. Not drawn at all
   when the tab is hidden, under a full-screen or maximised window, or under a
   phone sheet; one still frame under prefers-reduced-motion. No filter, no blur,
   no canvas shadow. The roster is fetched once a minute while the scene is on,
   and never for the sake of an animation.

   Faces — GUI/SUI: this canvas, inside #wall so the parallax carries it.
   TUI: not applicable, a terminal has no wallpaper; the scene row says so.
   `var`, not `let`: the bundle is one script. */
var CREW={on:false,cv:null,ctx:null,raf:0,last:0,t:0,W:0,H:0,dpr:1,font:'',static:false,
  cast:[],rosterAt:0,busy:{},tool:null,turns:0,drawn:0,drawMs:0,greeted:0};
var CREW_MAX=8;                       // figures beside the agent; a stage, not a census
var CREW_WORK_MS=9000;                // how long a figure stays forward after its last event
var CREW_TOOL_MS=6000;                // how long the tool it called stays named above it

function crewReduced(){return matchMedia('(prefers-reduced-motion: reduce)').matches}
function crewStart(){
  if(CREW.on)return;
  const wall=document.getElementById('wall');if(!wall)return;
  let cv=document.getElementById('crew');
  if(!cv){cv=document.createElement('canvas');cv.id='crew';cv.setAttribute('aria-hidden','true');wall.appendChild(cv)}
  CREW.cv=cv;CREW.ctx=cv.getContext('2d');CREW.on=true;CREW.static=crewReduced();
  // read once: getComputedStyle per label per frame was the expensive thing in 01c
  try{CREW.font=getComputedStyle(document.body).fontFamily||'sans-serif'}catch(e){CREW.font='sans-serif'}
  crewResize();
  addEventListener('resize',crewResize);
  document.addEventListener('visibilitychange',crewKick);
  crewRoster();
  CREW.last=performance.now();
  crewKick();
}
function crewStop(){
  if(!CREW.on)return;
  CREW.on=false;cancelAnimationFrame(CREW.raf);CREW.raf=0;
  removeEventListener('resize',crewResize);
  document.removeEventListener('visibilitychange',crewKick);
  if(CREW.cv)CREW.cv.remove();CREW.cv=null;CREW.ctx=null;
}
function crewResize(){
  const cv=CREW.cv;if(!cv)return;
  const dpr=Math.min(2,devicePixelRatio||1);
  CREW.W=innerWidth;CREW.H=innerHeight;CREW.dpr=dpr;
  cv.width=Math.round(innerWidth*dpr);cv.height=Math.round(innerHeight*dpr);
  crewKick();
}
function crewKick(){
  if(!CREW.on)return;
  if(CREW.static){crewDraw(0);return}
  if(!CREW.raf)CREW.raf=requestAnimationFrame(crewFrame);
}
/* nobody can see it — the same test the dial uses, for the same reason */
function crewCovered(){
  if(document.hidden)return true;
  const b=document.body.classList;
  if(b.contains('has-fullwin'))return true;
  if(typeof WM!=='undefined'&&[...WM.wins.values()].some(w=>w.max&&!w.min))return true;
  if(b.contains('dev-mobile')&&b.contains('has-win'))return true;
  return false;
}
/* The roster IS the cast. Enabled subagents, by name, capped at CREW_MAX — and
   the agent itself is added at draw time, so a machine with no specialists still
   has somebody on stage. Once a minute while the scene is on, never per frame. */
async function crewRoster(){
  if(!CREW.on)return;
  if(performance.now()-CREW.rosterAt<60000&&CREW.cast.length)return;
  CREW.rosterAt=performance.now();
  try{
    const d=await (await fetch('/api/subagents')).json();
    CREW.cast=(d.subagents||d.agents||[])
      .filter(s=>s&&(s.name||s.id)&&s.enabled!==false)
      .slice(0,CREW_MAX)
      .map(s=>({name:String(s.name||s.id),role:String(s.role||s.what||s.description||'').slice(0,28)}));
  }catch(e){}
}
/* An impulse from the OS, forwarded by movementPulse so the websocket keeps one
   seam. `flow` carries a name that may be a flow, an agent or an event — we
   light whichever cast member it matches, and nobody if it matches none, rather
   than lighting a random figure to make the scene look busy. */
function crewPulse(kind,label,ev){
  if(!CREW.on)return;
  const now=performance.now();
  if(kind==='turn'){CREW.turns++;crewKick();return}
  if(kind==='turnend'){CREW.turns=Math.max(0,CREW.turns-1);crewKick();return}
  if(kind==='tool'&&label){
    CREW.tool={name:String(label).replace(/_/g,' ').slice(0,24),at:now,who:crewWhoIsUp()};
    crewKick();return;
  }
  const who=crewMatch(label)||crewMatch(ev&&ev.agent);
  if(kind==='flow'){if(who)CREW.busy[who]=now;crewKick();return}
  if(kind==='done'){if(who)delete CREW.busy[who];crewKick();return}
}
/* Name → a cast member, loosely: the event's spelling and the roster's rarely
   match on case or separators. Returns null when nothing matches. */
function crewMatch(label){
  if(!label)return null;
  const k=String(label).toLowerCase().replace(/[^a-z0-9]/g,'');
  if(!k)return null;
  const hit=CREW.cast.find(c=>{const n=c.name.toLowerCase().replace(/[^a-z0-9]/g,'');return n&&(n===k||k.includes(n)||n.includes(k))});
  return hit?hit.name:null;
}
/* Who a bare tool call belongs to: the specialist that moved most recently, or
   the agent when none has. A tool call carries no principal in the stream, so
   this is a guess and it is made in ONE place rather than in the drawing. */
function crewWhoIsUp(){
  let best=null,at=0;
  for(const k in CREW.busy)if(CREW.busy[k]>at){at=CREW.busy[k];best=k}
  return best;
}
function crewFrame(now){
  CREW.raf=0;
  if(!CREW.on)return;
  const dt=Math.min(.25,(now-CREW.last)/1000);
  const busy=(typeof RUNNING!=='undefined'&&RUNNING.size)||Object.keys(CREW.busy).length;
  if(dt<(busy?0.048:0.083)){CREW.raf=requestAnimationFrame(crewFrame);return}
  CREW.last=now;
  crewStep(dt);
  if(!crewCovered()){const t0=performance.now();crewDraw(dt);CREW.drawMs=CREW.drawMs*.9+(performance.now()-t0)*.1}
  if(performance.now()-CREW.rosterAt>60000)crewRoster();
  CREW.raf=requestAnimationFrame(crewFrame);
}
function crewStep(dt){
  CREW.t+=dt;
  const now=performance.now();
  for(const k in CREW.busy)if(CREW.busy[k]<now-CREW_WORK_MS)delete CREW.busy[k];
  if(CREW.tool&&CREW.tool.at<now-CREW_TOOL_MS)CREW.tool=null;
}
/* ---- drawing ---- */
/* Same palette as the dial, so the two scenes read as one look: brass on
   graphite after dark, umber on paper in the light theme. A figure's own colour
   is a small hue shift off brass, never a new colour of its own. */
function crewInk(){
  const light=document.documentElement.dataset.theme==='light';
  return light?{brass:'90,66,20',ruby:'190,40,80',warm:'140,104,40'}
              :{brass:'232,197,120',ruby:'236,80,120',warm:'240,210,150'};
}
function crewText(ctx,txt,x,y,size,ink,alpha,weight,align){
  ctx.font=`${weight||500} ${size}px ${CREW.font||'sans-serif'}`;
  ctx.fillStyle=`rgba(${ink},${alpha})`;ctx.textAlign=align||'center';ctx.textBaseline='middle';ctx.fillText(txt,x,y);
}
/* A stable number from a name, so a specialist's build and stance never change
   between reloads. Cheap 32-bit string hash; nothing depends on its quality. */
function crewHash(s){let h=2166136261;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)}return (h>>>0)/4294967295}
/* One figure. `p` is 0 at its resting spot and 1 stepped forward; `lift` is the
   working gesture. Arcs and lines only — no shadow, which would be a blur.

   The arm is TWO segments with an elbow. A single straight line from shoulder to
   hand is the cheaper drawing and it is the one that made the first cut read as a
   row of scarecrows: a straight limb has no pose, so "working" and "standing" came
   out as the same shape at different angles. An elbow costs one more lineTo. */
function crewFigure(ctx,x,ground,scale,ink,tone,p,lift,label,sub,lit){
  const s=scale,head=s*0.28,body=s*0.60;
  const y=ground-p*s*0.30;                               // forward = up the stage, a little
  const a=lit?.95:.52+.22*p;
  const col=lit?ink.warm:ink.brass;
  const lw=Math.max(1.1,s*.042);
  ctx.lineCap='round';ctx.lineJoin='round';
  // legs — short and set apart by the figure's own build, so a row is not a comb
  const legTop=y-body*.38,stance=s*(.085+tone*.035);
  ctx.strokeStyle=`rgba(${col},${a*.55})`;ctx.lineWidth=lw;
  ctx.beginPath();
  ctx.moveTo(x-stance,y);ctx.lineTo(x-stance*.75,legTop);
  ctx.moveTo(x+stance,y);ctx.lineTo(x+stance*.75,legTop);ctx.stroke();
  // body — a rounded column, filled faintly and outlined
  const bw=s*(0.28+tone*0.07),bh=body*.56,by=legTop;
  ctx.beginPath();
  if(ctx.roundRect)ctx.roundRect(x-bw/2,by-bh,bw,bh,bw*.44);
  else ctx.rect(x-bw/2,by-bh,bw,bh);
  ctx.fillStyle=`rgba(${col},${a*.15})`;ctx.fill();
  ctx.strokeStyle=`rgba(${col},${a*.68})`;ctx.lineWidth=lw*.85;ctx.stroke();
  // arms — hanging at rest, elbow up and hands in toward the work while working
  const sh=by-bh*.80,el=s*.17,fa=s*.15;
  ctx.strokeStyle=`rgba(${col},${a*.60})`;ctx.lineWidth=lw*.9;
  [-1,1].forEach(d=>{
    const sx=x+d*bw*.46;
    const ex=sx+d*(el*(.30+.22*lift)),ey=sh+el*(.86-.20*lift);   // elbow
    const hx=ex+d*fa*(.42-.62*lift),hy2=ey+fa*(.80-1.42*lift);   // hand
    ctx.beginPath();ctx.moveTo(sx,sh);ctx.lineTo(ex,ey);ctx.lineTo(hx,hy2);ctx.stroke();
  });
  // head — and a ruby spark for the one that is actually running
  const hy=by-bh-head*.58;
  ctx.beginPath();ctx.arc(x,hy,head*.5,0,Math.PI*2);
  ctx.fillStyle=`rgba(${col},${a*.18})`;ctx.fill();
  ctx.strokeStyle=`rgba(${col},${a*.75})`;ctx.lineWidth=lw*.85;ctx.stroke();
  if(lit){ctx.beginPath();ctx.arc(x,hy,head*.17,0,Math.PI*2);ctx.fillStyle=`rgba(${ink.ruby},.9)`;ctx.fill()}
  // the name, always; the role only for the one stepped forward, where there is room
  crewText(ctx,label,x,ground+s*.24,Math.max(9,s*.115),col,lit?.85:.38,600);
  if(sub&&p>.5)crewText(ctx,sub,x,ground+s*.38,Math.max(8,s*.10),col,.32*p,500);
  return hy;
}
function crewDraw(dt){
  const C=CREW,ctx=C.ctx;if(!ctx)return;
  const W=C.W,H=C.H,ink=crewInk(),now=performance.now();
  ctx.setTransform(C.dpr,0,0,C.dpr,0,0);ctx.clearRect(0,0,W,H);
  const running=(typeof RUNNING!=='undefined'&&RUNNING.size)>0;
  const who=(typeof agentName==='function')?agentName():'Aria';
  const portrait=H>W;
  // the stage: a shallow line across the lower third, with the work line above it
  const ground=portrait?H*.80:H*.76;
  const n=C.cast.length;
  // The stage has a MINIMUM width, which matters only in the case it was written for:
  // one figure alone. Sized purely by the cast, a machine with no specialists drew its
  // agent at a third of the size of a machine with three — so the emptiest desktop,
  // the one that most needs to look like something, looked the most like nothing.
  const span=Math.min(W*.86,Math.max(420,(n+1)*Math.min(150,W/(n+2))));
  const scale=Math.max(52,Math.min(portrait?84:104,span/Math.max(3.2,n+1.2)*0.82));
  // the floor: ONE hairline, at their feet. The first cut drew a second line where a
  // working figure stands, and at rest that line crossed every figure's shins — a mark
  // that reads as a mistake rather than as a place. Stepping forward is legible from
  // the figure moving and brightening; it does not need to be ruled.
  ctx.beginPath();ctx.moveTo(W/2-span/2,ground+.5);ctx.lineTo(W/2+span/2,ground+.5);
  ctx.strokeStyle=`rgba(${ink.brass},.16)`;ctx.lineWidth=1;ctx.stroke();
  // places: the agent centre, the cast spread either side of it
  const slots=[];
  const step=n?span/(n+1):0;
  for(let i=0;i<n;i++){
    // fill outward from the middle so adding a specialist does not reshuffle the row
    const half=Math.ceil((i+1)/2),side=i%2?1:-1;
    slots.push({c:C.cast[i],x:W/2+side*half*step*0.92});
  }
  // the agent — larger, centre, awake while any turn runs
  const aLift=running?.5+.5*Math.sin(C.t*Math.PI*1.1):0;
  const aBreath=running?0:.5+.5*Math.sin(C.t*Math.PI*.55);
  const headY=crewFigure(ctx,W/2,ground,scale*1.22,ink,.5,running?.55:0,running?aLift*.5:0,
    who,'',running);
  if(running){ // a quiet halo, drawn as a ring rather than a shadow
    ctx.beginPath();ctx.arc(W/2,headY,scale*.38+aBreath*2,0,Math.PI*2);
    ctx.strokeStyle=`rgba(${ink.ruby},.18)`;ctx.lineWidth=1;ctx.stroke();
  }
  // the cast
  slots.forEach(s=>{
    const lit=!!C.busy[s.c.name];
    const since=lit?(now-C.busy[s.c.name])/CREW_WORK_MS:1;
    const p=lit?Math.min(1,(1-since)*3):0;               // step forward, then ease back
    const lift=lit?.5+.5*Math.sin(C.t*Math.PI*1.6+crewHash(s.c.name)*6):0;
    crewFigure(ctx,s.x,ground,scale,ink,crewHash(s.c.name),p,lift,
      s.c.name.replace(/[-_]/g,' ').slice(0,18),s.c.role,lit);
  });
  // the tool that just ran, above whoever ran it — the one label that carries news
  if(C.tool){
    const age=(now-C.tool.at)/CREW_TOOL_MS,fade=Math.max(0,1-age);
    const owner=C.tool.who?slots.find(s=>s.c.name===C.tool.who):null;
    const tx=owner?owner.x:W/2,ty=ground-scale*(owner?1.35:1.75)-6;
    crewText(ctx,C.tool.name,tx,ty,Math.max(9.5,scale*.125),ink.warm,.85*fade,600);
    ctx.beginPath();ctx.moveTo(tx,ty+scale*.10);ctx.lineTo(tx,ty+scale*.17);
    ctx.strokeStyle=`rgba(${ink.warm},${.5*fade})`;ctx.lineWidth=1;ctx.stroke();
  }
  // the standing line. With nobody on the roster it says so and says what to do
  // about it — an empty stage that explains itself, not an empty stage.
  const nb=Object.keys(C.busy).length;
  const line=n===0?'No specialists yet — ask for one and they take a place here'
    :nb?`${nb} of ${n} working`
    :running?`${who} is working · ${n} ${n===1?'specialist':'specialists'} standing by`
    :`${n} ${n===1?'specialist':'specialists'} standing by`;
  crewText(ctx,line,W/2,ground+scale*(portrait?.62:.58),10,ink.brass,n===0?.42:.26,500);
  C.drawn++;
}
// first paint: 01b ran before this file existed, so the scene starts itself
if(typeof IMMERSIVE!=='undefined'&&IMMERSIVE.on&&IMMERSIVE.scene==='crew')crewStart();
