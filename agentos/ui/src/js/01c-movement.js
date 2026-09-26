/* ================= Movement: one slow dial, and everything on it =================
   The second scene of the immersive look (Settings → Appearance → Immersive →
   Scene). The wallpaper is a dark plate and on it, drawn on a canvas, ONE big
   dial — hairlines, brass, a single ruby — that turns once an hour like the
   bezel of a watch. Everything the machine does is stamped on the dial the
   moment it happens, at twelve o'clock, and then rides round with it:

     a tool call         a short tick, with the tool's name beside it for the
                         first minutes, then just the tick
     a turn              an arc as long as the turn took; glowing while it runs
     a workflow          a mark on the inner ring; lit while that flow runs
     the soul            the centre — the agent's name, the brain as calibre —
                         breathing slowly while a turn runs
     the activity ring   a thin ring with one bright point, creeping while idle
                         and turning while something is running

   So what happened fifteen minutes ago sits at a quarter past, and an hour
   of the machine's life is on the dial at once. It is SLOW on purpose — the
   whole dial makes one turn in sixty minutes — and quiet: nothing here is
   more than a hairline at low alpha, so the greeting and the prompt bar sit
   inside it without a fight.

   Cost, and where it stops: one canvas the size of the viewport, drawn at
   most 20 times a second, a few hundred short strokes. Not drawn at all when
   the tab is hidden, under a full-screen or maximised window, or under a phone
   sheet (nobody can see it); one still frame under prefers-reduced-motion.
   No filter, no blur, no canvas shadow (a shadow is a blur by another name).
   The data is what the page already holds: RUNNING; the websocket's
   turn_start / turn_end / tool_start / fabric_event / flow_done, which call
   movementPulse; and /api/flows once a minute while the scene is on.

   Faces — GUI/SUI: this canvas, inside #wall so the parallax carries it.
   TUI: not applicable, a terminal has no wallpaper; the scene picker says so.
   `var`, not `let`: the bundle is one script. */
var MOVEMENT={on:false,cv:null,ctx:null,raf:0,last:0,t:0,angle:0,rate:0.03,burst:0,
  stamps:[],turns:{},flows:[],flowsAt:0,live:{},W:0,H:0,dpr:1,drawn:0,drawMs:0,font:'',static:false};
var MOVEMENT_PERIOD=3600;                                  // seconds per turn of the dial
var MOVEMENT_IDLE_RATE=0.03, MOVEMENT_RUN_RATE=0.45;       // rad/s of the activity ring
function movementReduced(){return matchMedia('(prefers-reduced-motion: reduce)').matches}
function movementStart(){
  if(MOVEMENT.on)return;
  const wall=document.getElementById('wall');if(!wall)return;
  let cv=document.getElementById('movement');
  if(!cv){cv=document.createElement('canvas');cv.id='movement';cv.setAttribute('aria-hidden','true');wall.appendChild(cv)}
  MOVEMENT.cv=cv;MOVEMENT.ctx=cv.getContext('2d');MOVEMENT.on=true;MOVEMENT.static=movementReduced();
  // read once: getComputedStyle per label per frame was the one expensive thing in the loop
  try{MOVEMENT.font=getComputedStyle(document.body).fontFamily||'sans-serif'}catch(e){MOVEMENT.font='sans-serif'}
  movementResize();
  addEventListener('resize',movementResize);
  document.addEventListener('visibilitychange',movementKick);
  movementFlows();
  MOVEMENT.last=performance.now();
  movementKick();
}
function movementStop(){
  if(!MOVEMENT.on)return;
  MOVEMENT.on=false;cancelAnimationFrame(MOVEMENT.raf);MOVEMENT.raf=0;
  removeEventListener('resize',movementResize);
  document.removeEventListener('visibilitychange',movementKick);
  if(MOVEMENT.cv)MOVEMENT.cv.remove();MOVEMENT.cv=null;MOVEMENT.ctx=null;
}
function movementResize(){
  const cv=MOVEMENT.cv;if(!cv)return;
  const dpr=Math.min(2,devicePixelRatio||1);
  MOVEMENT.W=innerWidth;MOVEMENT.H=innerHeight;MOVEMENT.dpr=dpr;
  cv.width=Math.round(innerWidth*dpr);cv.height=Math.round(innerHeight*dpr);
  MOVEMENT.drawn=0;movementKick();
}
/* something can be seen: (re)start the loop, or draw the one still frame */
function movementKick(){
  if(!MOVEMENT.on)return;
  if(MOVEMENT.static){movementDraw(0);return}
  if(!MOVEMENT.raf)MOVEMENT.raf=requestAnimationFrame(movementFrame);
}
/* nobody can see it: a hidden tab, or a window that covers the whole desktop */
function movementCovered(){
  if(document.hidden)return true;
  const b=document.body.classList;
  if(b.contains('has-fullwin'))return true;
  if(typeof WM!=='undefined'&&[...WM.wins.values()].some(w=>w.max&&!w.min))return true;
  if(b.contains('dev-mobile')&&b.contains('has-win'))return true;   // a sheet is the whole screen
  return false;
}
/* an impulse from the OS: a turn began or ended, a tool ran, a flow moved */
/* The ONE seam between the OS's events and the scenes that draw them: the Crew stage
   (01d), the Office playground (24d) and the play strip (24e). A new scene is one line here, not five more
   edits in a websocket that knows nothing about scenes. */
function scenePulse(kind,label,ev){
  if(typeof crewPulse==='function')crewPulse(kind,label,ev);
  if(typeof officePulse==='function')officePulse(kind,label,ev);
  if(typeof playPulse==='function')playPulse(kind,label,ev);     // the play strip (24e): Chat, apps, the bar
}
function movementPulse(kind,label,ev){
  // The crew scene (01d) rides the same impulses. Forwarding here rather than adding a
  // second call beside each of the websocket's five is deliberate: a new scene must not
  // mean five more edits in a file that knows nothing about scenes, and a sixth event
  // wired to only one of them is exactly the drift that produces a half-live desktop.
  scenePulse(kind,label,ev);
  if(!MOVEMENT.on)return;
  const M=MOVEMENT,now=performance.now();
  if(kind==='turn'&&label){M.turns[label]={start:now,end:0};return}
  if(kind==='turnend'&&label){if(M.turns[label])M.turns[label].end=now;return}
  M.burst=Math.min(1,M.burst+(kind==='tool'?.5:.25));
  if(kind==='flow'&&label)M.live[label]=now;
  if(kind==='done'&&label)delete M.live[label];
  if(label){
    M.stamps.push({kind,label:String(label).replace(/_/g,' ').slice(0,26),at:now});
    if(M.stamps.length>120)M.stamps.shift();
  }
  movementKick();
}
async function movementFlows(){
  if(!MOVEMENT.on)return;
  if(performance.now()-MOVEMENT.flowsAt<60000&&MOVEMENT.flows.length)return;
  MOVEMENT.flowsAt=performance.now();
  try{const d=await (await fetch('/api/flows')).json();
    MOVEMENT.flows=(d.flows||[]).filter(f=>f.enabled).slice(0,8).map(f=>f.name)}catch(e){}
}
function movementFrame(now){
  MOVEMENT.raf=0;
  if(!MOVEMENT.on)return;
  const dt=Math.min(.25,(now-MOVEMENT.last)/1000);
  // ≤20 fps while something is happening, 12 while idle: the drawing itself is
  // ~0.3 ms, the cost is compositing a screen-sized canvas, and idle the dial
  // moves a tenth of a degree a second — nobody can see 20 frames of that
  const busy=(typeof RUNNING!=='undefined'&&RUNNING.size)||MOVEMENT.burst>.05;
  if(dt<(busy?0.048:0.083)){MOVEMENT.raf=requestAnimationFrame(movementFrame);return}
  MOVEMENT.last=now;
  movementStep(dt);
  if(!movementCovered()){const t0=performance.now();movementDraw(dt);MOVEMENT.drawMs=MOVEMENT.drawMs*.9+(performance.now()-t0)*.1}
  if(performance.now()-MOVEMENT.flowsAt>60000)movementFlows();
  MOVEMENT.raf=requestAnimationFrame(movementFrame);
}
function movementStep(dt){
  const M=MOVEMENT;
  const running=(typeof RUNNING!=='undefined'&&RUNNING.size)||Object.keys(M.live).length;
  const target=running?MOVEMENT_RUN_RATE:MOVEMENT_IDLE_RATE;
  M.rate+=(target-M.rate)*Math.min(1,dt*1.2);
  M.angle+=(M.rate+M.burst*.8)*dt;
  M.burst*=Math.pow(.3,dt);
  M.t+=dt;
  const now=performance.now(),hour=now-MOVEMENT_PERIOD*1000;
  // a full turn of the dial and a stamp has come round to where it started: gone
  M.stamps=M.stamps.filter(s=>s.at>hour);
  for(const k in M.turns)if((M.turns[k].end||now)<hour)delete M.turns[k];
  for(const k in M.live)if(M.live[k]<now-90000)delete M.live[k];
}
/* ---- drawing ---- */
function movementInk(){
  const light=document.documentElement.dataset.theme==='light';
  return light?{brass:'90,66,20',ruby:'190,40,80',ink:'20,24,32'}
              :{brass:'232,197,120',ruby:'236,80,120',ink:'236,240,246'};
}
function movementText(ctx,txt,x,y,size,ink,alpha,weight,align){
  ctx.font=`${weight||500} ${size}px ${MOVEMENT.font||'sans-serif'}`;
  ctx.fillStyle=`rgba(${ink},${alpha})`;ctx.textAlign=align||'center';ctx.textBaseline='middle';ctx.fillText(txt,x,y);
}
/* an angle on the dial for a moment `ms` ago: twelve o'clock now, sweeping
   clockwise with age, one full turn per MOVEMENT_PERIOD */
function movementAngle(ageMs){return -Math.PI/2+(ageMs/1000/MOVEMENT_PERIOD)*Math.PI*2}
function movementDraw(dt){
  const M=MOVEMENT,ctx=M.ctx;if(!ctx)return;
  const W=M.W,H=M.H,ink=movementInk();
  ctx.setTransform(M.dpr,0,0,M.dpr,0,0);ctx.clearRect(0,0,W,H);
  ctx.lineCap='round';
  const running=(typeof RUNNING!=='undefined'&&RUNNING.size)>0;
  const now=performance.now();
  // the dial is the screen: centred, as big as the shorter side allows
  const portrait=H>W;
  const cx=W/2,cy=portrait?H*.60:H*.54,R=Math.min(W,H)*(portrait?.46:.47);
  const rim=R,stampR=R*.86,flowR=R*.62,actR=R*.40;
  // the bezel: sixty minute ticks that turn with the dial, four of them longer
  const rot=(now/1000/MOVEMENT_PERIOD)*Math.PI*2;
  ctx.beginPath();ctx.arc(cx,cy,rim,0,Math.PI*2);ctx.strokeStyle=`rgba(${ink.brass},.20)`;ctx.lineWidth=1;ctx.stroke();
  ctx.beginPath();ctx.arc(cx,cy,rim*.975,0,Math.PI*2);ctx.strokeStyle=`rgba(${ink.brass},.07)`;ctx.stroke();
  for(let i=0;i<60;i++){
    const a=rot+i*Math.PI/30,q=i%15===0,f=i%5===0;
    const r0=rim*(q?.945:f?.958:.968),r1=rim*.99;
    ctx.beginPath();ctx.moveTo(cx+Math.cos(a)*r0,cy+Math.sin(a)*r0);ctx.lineTo(cx+Math.cos(a)*r1,cy+Math.sin(a)*r1);
    ctx.strokeStyle=`rgba(${ink.brass},${q?.45:f?.28:.14})`;ctx.lineWidth=q?1.6:1;ctx.stroke();
  }
  // the twelve o'clock index, fixed: "now"
  ctx.beginPath();ctx.moveTo(cx,cy-rim*.93);ctx.lineTo(cx,cy-rim*.905);ctx.strokeStyle=`rgba(${ink.ruby},.9)`;ctx.lineWidth=2;ctx.stroke();
  // the stamp ring, and a quiet quarter marking so age can be read
  ctx.beginPath();ctx.arc(cx,cy,stampR,0,Math.PI*2);ctx.strokeStyle=`rgba(${ink.brass},.12)`;ctx.lineWidth=1;ctx.stroke();
  [['15 min',.25],['30',.5],['45',.75]].forEach(([t,f])=>{const a=-Math.PI/2+f*Math.PI*2;
    movementText(ctx,t,cx+Math.cos(a)*stampR*1.06,cy+Math.sin(a)*stampR*1.06,9,ink.brass,.22,500)});
  // turns: an arc as long as each took, on the stamp ring; the live one glows
  for(const k in M.turns){const t=M.turns[k];const a0=movementAngle(now-t.start),a1=movementAngle(now-(t.end||now));
    const live=!t.end;ctx.beginPath();ctx.arc(cx,cy,stampR,a1,a0);
    ctx.strokeStyle=`rgba(${ink.brass},${live?.75:.42})`;ctx.lineWidth=live?3:2;ctx.stroke();
    if(live){ctx.beginPath();ctx.arc(cx,cy,stampR,a1,a0);ctx.strokeStyle=`rgba(${ink.brass},.14)`;ctx.lineWidth=10;ctx.stroke()}}
  // tools and flow events: a tick each, named while young
  M.stamps.forEach(s=>{
    const age=now-s.at,a=movementAngle(age),flow=s.kind==='flow'||s.kind==='done';
    const r0=stampR-(flow?10:6),r1=stampR+(flow?10:6);
    const c=flow?ink.ruby:ink.brass,al=Math.max(.22,1-age/1200000);
    ctx.beginPath();ctx.moveTo(cx+Math.cos(a)*r0,cy+Math.sin(a)*r0);ctx.lineTo(cx+Math.cos(a)*r1,cy+Math.sin(a)*r1);
    ctx.strokeStyle=`rgba(${c},${al})`;ctx.lineWidth=flow?1.6:1.2;ctx.stroke();
    const ta=Math.max(0,1-age/420000);                       // the name stays for seven minutes
    if(ta>0){const lr=stampR-18,x=cx+Math.cos(a)*lr,y=cy+Math.sin(a)*lr,left=Math.cos(a)>0;
      movementText(ctx,s.label,x,y,10,c,.7*Math.min(1,ta*3),500,left?'right':'left')}
  });
  // the flows ring: every enabled workflow has a mark; a running one is lit
  ctx.beginPath();ctx.arc(cx,cy,flowR,0,Math.PI*2);ctx.strokeStyle=`rgba(${ink.brass},.09)`;ctx.lineWidth=1;ctx.stroke();
  M.flows.forEach((name,i)=>{
    const a=-Math.PI/2+(i/M.flows.length)*Math.PI*2+rot*.5,live=name in M.live;
    const x=cx+Math.cos(a)*flowR,y=cy+Math.sin(a)*flowR;
    ctx.beginPath();ctx.arc(x,y,live?4:2.5,0,Math.PI*2);ctx.fillStyle=`rgba(${live?ink.ruby:ink.brass},${live?.95:.4})`;ctx.fill();
    if(live){ctx.beginPath();ctx.arc(x,y,11,0,Math.PI*2);ctx.fillStyle=`rgba(${ink.ruby},.14)`;ctx.fill()}
    movementText(ctx,name.replace(/[-_]/g,' ').slice(0,20),x+Math.cos(a)*14,y+Math.sin(a)*14,9.5,live?ink.ruby:ink.brass,live?.8:.3,500,Math.cos(a)>.3?'left':Math.cos(a)<-.3?'right':'center');
  });
  // the activity ring: one bright point that creeps idle and turns while running
  ctx.beginPath();ctx.arc(cx,cy,actR,0,Math.PI*2);ctx.strokeStyle=`rgba(${ink.brass},.10)`;ctx.lineWidth=1;ctx.stroke();
  const aa=M.angle;
  ctx.beginPath();ctx.arc(cx,cy,actR,aa-.9,aa);ctx.strokeStyle=`rgba(${ink.brass},${running?.35:.16})`;ctx.lineWidth=1.5;ctx.stroke();
  ctx.beginPath();ctx.arc(cx+Math.cos(aa)*actR,cy+Math.sin(aa)*actR,running?3.5:2.5,0,Math.PI*2);
  ctx.fillStyle=`rgba(${ink.brass},${running?.95:.55})`;ctx.fill();
  // the soul, at the centre: a slow breath while a turn runs
  const breath=running?.5+.5*Math.sin(M.t*Math.PI*.7):0;
  ctx.beginPath();ctx.arc(cx,cy,R*.16,0,Math.PI*2);ctx.strokeStyle=`rgba(${ink.brass},${.14+.22*breath})`;ctx.lineWidth=1;ctx.stroke();
  if(running){ctx.beginPath();ctx.arc(cx,cy,R*.16*(1+.06*breath),0,Math.PI*2);ctx.fillStyle=`rgba(${ink.brass},${.03+.05*breath})`;ctx.fill()}
  ctx.beginPath();ctx.arc(cx,cy,3,0,Math.PI*2);ctx.fillStyle=`rgba(${ink.ruby},${running?.95:.6})`;ctx.fill();
  const who=(typeof agentName==='function')?agentName():'Aria';
  const brain=(typeof immersiveBrainText==='function'?immersiveBrainText():'').split(' · ')[0];
  movementText(ctx,'SOUL · '+who.toUpperCase(),cx,cy+R*.16+16,10,ink.brass,.5,600);
  if(brain)movementText(ctx,'CAL. '+brain.toUpperCase(),cx,cy+R*.16+31,9,ink.brass,.3,500);
  const nrun=(typeof RUNNING!=='undefined')?RUNNING.size:0;
  movementText(ctx,nrun?`${nrun} ${nrun===1?'turn':'turns'} running`:`${M.stamps.length} in the last hour`,cx,cy+R*.16+46,9,ink.brass,.26,500);
  M.drawn++;
}
// first paint: 01b ran before this file existed, so the scene starts itself
if(typeof IMMERSIVE!=='undefined'&&IMMERSIVE.on&&IMMERSIVE.scene==='movement')movementStart();
