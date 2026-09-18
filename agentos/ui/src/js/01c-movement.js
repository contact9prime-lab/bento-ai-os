/* ================= Movement: the machine as an automatic watch =================
   The second scene of the immersive look (Settings → Appearance → Immersive →
   Scene). The wallpaper is a dark plate and, on it, a watch movement drawn on
   a canvas — and every part is a real part of this OS:

     the mainspring barrel   the soul: engraved with the agent's name, wound
                             slowly all the time, glowing while a turn runs
     the gear train          turns: creeping while idle, turning while one runs
     one wheel per workflow  each enabled flow is a small wheel with its name;
                             it turns when that flow is running
     the rotor               the automatic weight: every tool call is an
                             impulse and it swings and settles
     the balance wheel       the heartbeat: a slow gentle beat idle, fast and
                             wide while something is running
     the jewels              the pivots; one brightens when its part is live
     glimpses                a tool's name, a flow's name, fading in beside the
                             part that did it — the date window of the thing

   The point is that it is SLOW. Idle, the train makes a turn in a few minutes
   and the balance barely breathes; the desktop should read as alive, not busy.

   Cost, and where it is spent: one canvas the size of the viewport, drawn at
   most 20 times a second, with ~20 shapes. It is not drawn at all when the tab
   is hidden, under a full-screen or maximised window (nobody can see it), or
   under prefers-reduced-motion (drawn once, still). There is no filter, no
   blur, no shadow — a canvas shadow is a blur by another name. The data comes
   from what the page already holds: RUNNING, the websocket's tool_start /
   fabric_event / flow_done (09-websocket.js calls movementPulse), and
   /api/flows once a minute while the scene is on.

   Faces — GUI/SUI: this canvas, inside #wall so the parallax carries it.
   TUI: not applicable, a terminal has no wallpaper; the scene picker says so.
   `var`, not `let`: the bundle is one script. */
var MOVEMENT={on:false,cv:null,ctx:null,raf:0,last:0,t:0,angle:0,rate:0.03,burst:0,
  rotor:{a:Math.PI*.35,v:0},flows:[],flowsAt:0,live:{},glimpses:[],W:0,H:0,dpr:1,drawn:0,static:false};
var MOVEMENT_IDLE_RATE=0.03, MOVEMENT_RUN_RATE=0.38;    // rad/s of the master wheel
function movementReduced(){return matchMedia('(prefers-reduced-motion: reduce)').matches}
function movementStart(){
  if(MOVEMENT.on)return;
  const wall=document.getElementById('wall');if(!wall)return;
  let cv=document.getElementById('movement');
  if(!cv){cv=document.createElement('canvas');cv.id='movement';cv.setAttribute('aria-hidden','true');wall.appendChild(cv)}
  MOVEMENT.cv=cv;MOVEMENT.ctx=cv.getContext('2d');MOVEMENT.on=true;MOVEMENT.static=movementReduced();
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
/* an impulse from the OS: a tool ran, a flow moved, a turn began or ended */
function movementPulse(kind,label,ev){
  if(!MOVEMENT.on)return;
  const M=MOVEMENT;
  M.rotor.v+=(Math.random()<.5?-1:1)*(kind==='flow'?.9:kind==='tool'?.55:.3);
  M.burst=Math.min(1,M.burst+(kind==='tool'?.35:.2));
  if(kind==='flow'&&label){M.live[label]=performance.now()}
  if(kind==='done'&&label){delete M.live[label]}
  if(label&&kind!=='turn'){
    const g=M.glimpses;
    if(g.length>5)g.shift();
    g.push({kind,label:String(label).replace(/_/g,' ').slice(0,28),at:performance.now()});
  }
  movementKick();
}
async function movementFlows(){
  if(!MOVEMENT.on)return;
  if(performance.now()-MOVEMENT.flowsAt<60000&&MOVEMENT.flows.length)return;
  MOVEMENT.flowsAt=performance.now();
  try{const d=await (await fetch('/api/flows')).json();
    MOVEMENT.flows=(d.flows||[]).filter(f=>f.enabled).slice(0,6).map(f=>f.name)}catch(e){}
}
function movementFrame(now){
  MOVEMENT.raf=0;
  if(!MOVEMENT.on)return;
  const dt=Math.min(.25,(now-MOVEMENT.last)/1000);
  if(dt<0.048){MOVEMENT.raf=requestAnimationFrame(movementFrame);return}   // ≤20 fps
  MOVEMENT.last=now;
  movementStep(dt);
  if(!movementCovered())movementDraw(dt);
  if(performance.now()-MOVEMENT.flowsAt>60000)movementFlows();
  MOVEMENT.raf=requestAnimationFrame(movementFrame);
}
function movementStep(dt){
  const M=MOVEMENT;
  const running=(typeof RUNNING!=='undefined'&&RUNNING.size)||Object.keys(M.live).length;
  const target=running?MOVEMENT_RUN_RATE:MOVEMENT_IDLE_RATE;
  M.rate+=(target-M.rate)*Math.min(1,dt*1.2);
  M.angle+=(M.rate+M.burst*.6)*dt;
  M.burst*=Math.pow(.35,dt);
  M.t+=dt;
  // the rotor: free on its pivot, losing energy, drifting back to hang
  const r=M.rotor;
  r.v+=(Math.PI*.35-r.a)*.35*dt;
  r.v*=Math.pow(.45,dt);
  r.a+=r.v*dt;
  // a flow's wheel keeps turning for a while after its last event
  const cut=performance.now()-90000;
  for(const k in M.live)if(M.live[k]<cut)delete M.live[k];
  M.glimpses=M.glimpses.filter(g=>performance.now()-g.at<3600);
}
/* ---- drawing ---- */
function movementInk(){
  const light=document.documentElement.dataset.theme==='light';
  return light?{brass:'90,66,20',steel:'40,52,70',ruby:'190,40,80',ink:'20,24,32'}
              :{brass:'232,197,120',steel:'186,198,214',ruby:'236,80,120',ink:'236,240,246'};
}
function movementGear(ctx,x,y,r,teeth,a,ink,alpha,spokes){
  ctx.save();ctx.translate(x,y);ctx.rotate(a);
  ctx.beginPath();
  const inner=r*.86,step=Math.PI*2/teeth;
  for(let i=0;i<teeth;i++){
    const t0=i*step,t1=t0+step*.32,t2=t0+step*.5,t3=t0+step*.82;
    ctx.lineTo(Math.cos(t0)*inner,Math.sin(t0)*inner);ctx.lineTo(Math.cos(t1)*r,Math.sin(t1)*r);
    ctx.lineTo(Math.cos(t2)*r,Math.sin(t2)*r);ctx.lineTo(Math.cos(t3)*inner,Math.sin(t3)*inner);
  }
  ctx.closePath();
  ctx.strokeStyle=`rgba(${ink},${alpha})`;ctx.lineWidth=1.1;ctx.stroke();
  ctx.fillStyle=`rgba(${ink},${alpha*.08})`;ctx.fill();
  ctx.beginPath();ctx.arc(0,0,r*.62,0,Math.PI*2);ctx.stroke();
  const n=spokes||5;
  for(let i=0;i<n;i++){const t=i*Math.PI*2/n;ctx.beginPath();ctx.moveTo(Math.cos(t)*r*.14,Math.sin(t)*r*.14);ctx.lineTo(Math.cos(t)*r*.6,Math.sin(t)*r*.6);ctx.stroke()}
  ctx.restore();
}
function movementJewel(ctx,x,y,r,ink,hot){
  ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fillStyle=`rgba(${ink.ruby},${hot?.95:.55})`;ctx.fill();
  if(hot){ctx.beginPath();ctx.arc(x,y,r*2.6,0,Math.PI*2);ctx.fillStyle=`rgba(${ink.ruby},.18)`;ctx.fill()}
  ctx.beginPath();ctx.arc(x-r*.3,y-r*.3,r*.35,0,Math.PI*2);ctx.fillStyle='rgba(255,255,255,.5)';ctx.fill();
}
function movementSpiral(ctx,x,y,r0,r1,turns,a,ink,alpha,breathe){
  ctx.save();ctx.translate(x,y);ctx.rotate(a);ctx.beginPath();
  const n=Math.round(turns*36);
  for(let i=0;i<=n;i++){const f=i/n,t=f*turns*Math.PI*2,rr=r0+(r1-r0)*f*(1+(breathe||0)*f);
    const px=Math.cos(t)*rr,py=Math.sin(t)*rr;i?ctx.lineTo(px,py):ctx.moveTo(px,py)}
  ctx.strokeStyle=`rgba(${ink},${alpha})`;ctx.lineWidth=1;ctx.stroke();ctx.restore();
}
function movementText(ctx,txt,x,y,size,ink,alpha,weight){
  ctx.font=`${weight||500} ${size}px ${getComputedStyle(document.body).fontFamily||'sans-serif'}`;
  ctx.fillStyle=`rgba(${ink},${alpha})`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(txt,x,y);
}
function movementDraw(dt){
  const M=MOVEMENT,ctx=M.ctx;if(!ctx)return;
  const W=M.W,H=M.H,s=Math.min(W,H)/900,ink=movementInk();
  ctx.setTransform(M.dpr,0,0,M.dpr,0,0);ctx.clearRect(0,0,W,H);
  const running=(typeof RUNNING!=='undefined'&&RUNNING.size)>0;
  // landscape: lower-right of the screen, under the scene's text and clear of
  // the dock; portrait (a phone): centred and lower. Every offset is in `s`
  // so the movement is the same shape at 390px and at 4K.
  const portrait=H>W;
  const cx=portrait?W*.5:W*.56,cy=portrait?H*.62:H*.66;
  const A=M.angle;
  // bridges: two plates with Geneva stripes, behind everything
  const stripes=(x,y,w,h,rot)=>{ctx.save();ctx.translate(x,y);ctx.rotate(rot);
    const g=ctx.createLinearGradient(-w/2,0,w/2,0);
    for(let i=0;i<=16;i++){g.addColorStop(i/16,`rgba(${ink.ink},${i%2?.035:.015})`)}
    ctx.fillStyle=g;ctx.beginPath();ctx.roundRect(-w/2,-h/2,w,h,28*s);ctx.fill();
    ctx.strokeStyle=`rgba(${ink.brass},.10)`;ctx.lineWidth=1;ctx.stroke();ctx.restore()};
  stripes(cx+110*s,cy-60*s,580*s,300*s,-.18);
  stripes(cx-130*s,cy+130*s,500*s,200*s,.12);
  // the mainspring barrel: the soul
  const R=130*s;
  ctx.beginPath();ctx.arc(cx,cy,R,0,Math.PI*2);ctx.strokeStyle=`rgba(${ink.brass},.55)`;ctx.lineWidth=1.4;ctx.stroke();
  ctx.beginPath();ctx.arc(cx,cy,R*.92,0,Math.PI*2);ctx.strokeStyle=`rgba(${ink.brass},.22)`;ctx.lineWidth=1;ctx.stroke();
  if(running||M.burst>.05){ctx.beginPath();ctx.arc(cx,cy,R*.9,0,Math.PI*2);ctx.fillStyle=`rgba(${ink.brass},${.05+.08*Math.max(M.burst,running?.6:0)})`;ctx.fill()}
  movementSpiral(ctx,cx,cy,10*s,R*.82,5.5,A*.12,ink.brass,.28,running?.02:0);
  movementJewel(ctx,cx,cy,5*s,ink,running);
  const who=(typeof agentName==='function')?agentName():'Aria';
  const brain=(typeof immersiveBrainText==='function'?immersiveBrainText():'').split(' · ')[0];
  movementText(ctx,'SOUL · '+who.toUpperCase(),cx,cy+R+18*s,10.5*s,ink.brass,.6,600);
  if(brain)movementText(ctx,'CAL. '+brain.toUpperCase(),cx,cy+R+34*s,9.5*s,ink.brass,.4,500);
  // the train: barrel → centre wheel → third → fourth → escape, each faster and smaller
  const train=[{r:95,x:cx+215*s,y:cy-10*s,teeth:28},{r:60,x:cx+355*s,y:cy-80*s,teeth:20},{r:42,x:cx+450*s,y:cy-130*s,teeth:16},{r:30,x:cx+520*s,y:cy-165*s,teeth:12}];
  let ratio=1;
  train.forEach((g,i)=>{ratio*=-(i?train[i-1].r:130)/g.r;
    movementGear(ctx,g.x,g.y,g.r*s,g.teeth,A*ratio,ink.steel,.42,i%2?4:5);
    movementJewel(ctx,g.x,g.y,3.5*s,ink,running&&M.burst>.15&&i===0)});
  // the balance wheel and its hairspring: the heartbeat
  const bx=cx+520*s,by=cy-262*s,br=66*s;
  const f=running?2.4:.55,amp=running?.6:.16;
  const ba=Math.sin(M.t*Math.PI*2*f)*amp;
  ctx.save();ctx.translate(bx,by);ctx.rotate(ba);
  ctx.beginPath();ctx.arc(0,0,br,0,Math.PI*2);ctx.strokeStyle=`rgba(${ink.brass},.7)`;ctx.lineWidth=3*s;ctx.stroke();
  ctx.beginPath();ctx.moveTo(-br,0);ctx.lineTo(br,0);ctx.moveTo(0,-br);ctx.lineTo(0,br);ctx.strokeStyle=`rgba(${ink.brass},.35)`;ctx.lineWidth=1.2;ctx.stroke();
  ctx.restore();
  movementSpiral(ctx,bx,by,6*s,br*.55,4,ba*1.6,ink.steel,.45,ba*.35);
  movementJewel(ctx,bx,by,4*s,ink,running);
  // one wheel per workflow
  const fl=M.flows;
  fl.forEach((name,i)=>{
    const x=cx-290*s+i*84*s,y=cy+110*s+(i%2)*40*s,r=28*s,live=name in M.live;
    movementGear(ctx,x,y,r,12,live?A*3.2:A*.9*(i%2?-1:1),live?ink.brass:ink.steel,live?.7:.3,4);
    movementJewel(ctx,x,y,3*s,ink,live);
    movementText(ctx,name.replace(/[-_]/g,' ').slice(0,18),x,y+r+12*s,9.5*s,live?ink.brass:ink.steel,live?.7:.32,500);
  });
  if(!fl.length)movementText(ctx,'no workflows yet',cx-220*s,cy+140*s,9.5*s,ink.steel,.28,500);
  // the rotor, over everything: an automatic weight that swings on every tool call
  ctx.save();ctx.translate(cx,cy);ctx.rotate(M.rotor.a);
  ctx.beginPath();ctx.arc(0,0,188*s,Math.PI*.08,Math.PI*.92);ctx.arc(0,0,104*s,Math.PI*.92,Math.PI*.08,true);ctx.closePath();
  ctx.fillStyle=`rgba(${ink.brass},.07)`;ctx.fill();ctx.strokeStyle=`rgba(${ink.brass},.32)`;ctx.lineWidth=1.2;ctx.stroke();
  ctx.beginPath();ctx.arc(0,0,188*s,Math.PI*.3,Math.PI*.7);ctx.strokeStyle=`rgba(${ink.brass},.55)`;ctx.lineWidth=5*s;ctx.stroke();
  ctx.restore();
  // glimpses: the name of what just happened, beside the part that did it
  const now=performance.now();
  M.glimpses.forEach((g,i)=>{
    const age=(now-g.at)/1000,a=age<.3?age/.3:age<2.4?1:Math.max(0,1-(age-2.4)/1.2);
    const x=g.kind==='flow'||g.kind==='done'?cx-290*s+((fl.indexOf(g.label)+6)%6)*84*s:cx+215*s,y=g.kind==='flow'||g.kind==='done'?cy+190*s:cy-125*s-i*16*s;
    movementText(ctx,g.label,x,y,11*s,ink.brass,.85*a,600);
  });
  M.drawn++;
}
// first paint: 01b ran before this file existed, so the scene starts itself
if(typeof IMMERSIVE!=='undefined'&&IMMERSIVE.on&&IMMERSIVE.scene==='movement')movementStart();
