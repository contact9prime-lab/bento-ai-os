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
   - **Drawn, not loaded.** A figure is a filled body, a big head and a face with
     two eyes that blink, in a colour of its own, built from arcs and lines with
     saturation and lightness taken from the theme. No tileset, no sprite sheet,
     no character pack — which is also why this scene raises no asset-licence
     question and adds no bytes to the wheel.
   - **They have to read as PEOPLE.** The first cut drew outlined wire bodies,
     identical in one brass colour, frozen at rest, with a single red dot in the
     middle of each face, and the report on it was one word: scary. Four things
     fixed it and all four are load-bearing — a filled body (an outline is a
     ghost), a colour per specialist that no two share, a face with TWO eyes (one
     centred mark is a cyclops, so the running light moved above the head), and
     idle life, because a row of motionless figures staring out of a dark room is
     a waxwork. `tests/test_immersive.py` pins each one.

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
/* The palette. The first cut used the dial's single brass on everything, and the
   result was a row of identical wire outlines with one red dot where a face
   should be — which reads as a warning symbol, not a colleague, and was reported
   in one word: scary. Three things fixed it, and all three are here rather than
   in the drawing, so a future change cannot make only two of them.

   A figure is FILLED, in a colour OF ITS OWN, and has TWO EYES. Filled shapes
   have weight; an outline is a ghost. A hue per specialist makes a row of them a
   team rather than a queue. And two eyes are the whole difference between a face
   and a target — a single centred mark is a cyclops, which is why the running
   indicator moved off the face entirely and became a light above the head.

   The hues are a small curated set rather than a free hash of the name: a random
   hue lands on bile green and hospital pink about a sixth of the time, and one
   bad draw is a desktop somebody switches off. Saturation and lightness come from
   the theme, not from the table, so the same eight hues sit correctly on either. */
var CREW_HUES=[34, 12, 172, 264, 96, 330, 202, 48];
function crewInk(){
  const light=document.documentElement.dataset.theme==='light';
  // The crew's plate is a dark room in BOTH themes (immersive-crew.svg), as the
  // dial's is, so the figures are light-on-dark either way. What the theme
  // changes is how deep the colour sits — the light theme's page is brighter
  // around this scene, and the same pastels beside it read washed out.
  // Working is MORE COLOUR, not more white. Raising lightness alone took every
  // figure towards beige, so a stage with three of them busy read as one washed
  // pastel repeated — the opposite of the colour-per-specialist it is there for.
  return {light,
    satLit: light ? 62 : 58,  lumLit: light ? 56 : 62,   // working
    satDim: light ? 40 : 34,  lumDim: light ? 44 : 46,   // standing by
    brass: light ? '150,116,52' : '232,197,120',
    ruby:  light ? '212,60,96'   : '236,80,120'};
}
/* One specialist's colours, stable for its name. The eyes are a deep shade of
   the figure's OWN hue rather than a literal black — the rule the whole look
   keeps, and here it also stops eight characters sharing one dead pupil. */
function crewSkin(ink, h, lit){
  const sa = lit ? ink.satLit : ink.satDim, l = lit ? ink.lumLit : ink.lumDim;
  return {hue: h,
          fill: `hsl(${h} ${sa}% ${l}%)`,
          line: `hsl(${h} ${sa + 8}% ${l + 16}%)`,
          dark: `hsl(${h} ${Math.round(sa * .45)}% 14%)`,
          shade: `hsl(${h} 26% 7%)`};
}
/* `ink` is an "r,g,b" triple (the scene's own brass and ruby); `css` overrides it
   with a ready colour, which is how a name is tinted like the figure it belongs
   to without every caller having to build a string. */
function crewText(ctx,txt,x,y,size,ink,alpha,weight,align,css){
  ctx.font=`${weight||500} ${size}px ${CREW.font||'sans-serif'}`;
  ctx.textAlign=align||'center';ctx.textBaseline='middle';
  if(css){ctx.globalAlpha=alpha;ctx.fillStyle=css;ctx.fillText(txt,x,y);ctx.globalAlpha=1}
  else{ctx.fillStyle=`rgba(${ink},${alpha})`;ctx.fillText(txt,x,y)}
}
/* A stable number from a name, so a specialist's build and stance never change
   between reloads. Cheap 32-bit string hash; nothing depends on its quality. */
function crewHash(s){let h=2166136261;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)}return (h>>>0)/4294967295}
/* One figure.

   `p` is 0 at its resting spot and 1 stepped forward, `lift` is the working
   gesture, and everything else on screen comes from CREW.t and the figure's own
   phase — so a figure is NEVER completely still. That is deliberate and it is
   the second half of the "scary" fix: at rest the first cut froze every figure
   into an identical pose, and a row of motionless outlined bodies staring out of
   a dark room is a waxwork. Breathing, a slow sway and an occasional blink cost
   three sines and turn the same drawing into somebody waiting.

   Arcs, lines and one flat ellipse — no canvas shadow anywhere, because a shadow
   is a blur by another name and this layer is re-composited under the parallax.
   The contact ellipse under the feet is a filled shape at low alpha, which is
   what stops the figures reading as floating without costing a blur.

   The arm is TWO segments with an elbow. A single straight line from shoulder to
   hand is the cheaper drawing and it is what made the first cut read as a row of
   scarecrows: a straight limb has no pose, so "working" and "standing" came out
   as the same shape at different angles. An elbow costs one more lineTo. */
function crewFigure(ctx,x,ground,scale,ink,tone,hue,p,lift,label,sub,lit){
  const s=scale, t=CREW.t, ph=tone*6.283, skin=crewSkin(ink,hue,lit);
  const still=CREW.static;                       // reduced motion: one pose, no life
  const breath=still?0:Math.sin(t*1.5+ph);
  const sway  =still?0:Math.sin(t*0.7+ph)*s*.013;
  const bob   =lit&&!still?Math.abs(Math.sin(t*3.0+ph))*s*.055:0;
  const cx=x+sway, y=ground-p*s*.24-bob;
  // Proportions: a LARGE head on a short body. A small head on long thin legs is
  // what a horror silhouette is made of, and it is what the first cut drew.
  const headR=s*.185, legH=s*.15, bw=s*(.26+tone*.05), bh=s*.29+(breath*s*.007);
  const legTop=y-legH, bodyTop=legTop-bh, headY=bodyTop-headR*.78;
  const a=lit?1:.86;
  ctx.lineCap='round';ctx.lineJoin='round';
  // the ground contact, so nobody floats
  if(ctx.ellipse){
    ctx.beginPath();ctx.ellipse(cx,ground+1,bw*.62,s*.028,0,0,Math.PI*2);
    ctx.globalAlpha=.30;ctx.fillStyle=skin.shade;ctx.fill();ctx.globalAlpha=1;
  }
  ctx.globalAlpha=a;
  // legs
  const stance=bw*.30;
  ctx.strokeStyle=skin.fill;ctx.lineWidth=Math.max(2,s*.055);
  ctx.beginPath();
  ctx.moveTo(cx-stance,y);ctx.lineTo(cx-stance,legTop);
  ctx.moveTo(cx+stance,y);ctx.lineTo(cx+stance,legTop);ctx.stroke();
  // arms — hanging and swinging gently at rest, elbow up and hands in when working
  const sh=bodyTop+bh*.22, el=s*.15, fa=s*.13;
  const swing=still?0:Math.sin(t*1.1+ph)*.12;
  ctx.strokeStyle=skin.fill;ctx.lineWidth=Math.max(2,s*.05);
  [-1,1].forEach(d=>{
    const sx=cx+d*bw*.46;
    const ex=sx+d*(el*(.34+.24*lift)), ey=sh+el*(.84-.22*lift+swing*d);
    const hx=ex+d*fa*(.38-.66*lift), hy=ey+fa*(.78-1.46*lift);
    ctx.beginPath();ctx.moveTo(sx,sh);ctx.lineTo(ex,ey);ctx.lineTo(hx,hy);ctx.stroke();
  });
  // body — FILLED. An outline is a ghost; a filled shape has weight.
  ctx.beginPath();
  if(ctx.roundRect)ctx.roundRect(cx-bw/2,bodyTop,bw,bh,bw*.40);
  else ctx.rect(cx-bw/2,bodyTop,bw,bh);
  ctx.fillStyle=skin.fill;ctx.fill();
  // head
  ctx.beginPath();ctx.arc(cx,headY,headR,0,Math.PI*2);
  ctx.fillStyle=skin.line;ctx.fill();
  // the face. Two eyes that blink, and a mouth that is a little wider while
  // working — the running indicator is the light ABOVE the head, never a mark
  // in the middle of the face.
  const blinking=!still&&((t*.31+tone*3)%1)<.045;
  const er=headR*.145, eh=blinking?er*.18:er;
  ctx.fillStyle=skin.dark;
  [-1,1].forEach(d=>{
    ctx.beginPath();
    if(ctx.ellipse)ctx.ellipse(cx+d*headR*.36,headY-headR*.06,er,eh,0,0,Math.PI*2);
    else ctx.arc(cx+d*headR*.36,headY-headR*.06,eh,0,Math.PI*2);
    ctx.fill();
  });
  // The mouth is drawn on EVERY frame, including a blink. Tying it to the eyes
  // made a blinking figure lose its mouth for a tenth of a second, which does not
  // read as a blink — it reads as the face coming apart.
  ctx.beginPath();
  ctx.arc(cx,headY+headR*.16,headR*(lit?.34:.28),lit?.15*Math.PI:.2*Math.PI,lit?.85*Math.PI:.8*Math.PI);
  ctx.strokeStyle=skin.dark;ctx.lineWidth=Math.max(1,headR*.11);ctx.stroke();
  // working: a status light above the head, pulsing. Off the face on purpose.
  if(lit){
    const pulse=still?1:.6+.4*Math.sin(t*4+ph);
    ctx.beginPath();ctx.arc(cx,headY-headR*1.32,Math.max(2.5,s*.036),0,Math.PI*2);
    ctx.fillStyle=`rgba(${ink.ruby},${.55+.45*pulse})`;ctx.fill();
  }
  ctx.globalAlpha=1;
  // the name, tinted like its owner; the role only for the one stepped forward
  crewText(ctx,label,x,ground+s*.24,Math.max(9,s*.115),null,lit?.95:.55,600,'center',skin.line);
  if(sub&&p>.5)crewText(ctx,sub,x,ground+s*.38,Math.max(8,s*.10),null,.42*p,500,'center',skin.line);
  return headY;
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
  // Hues are handed out across the ROW, not derived per name in isolation. A bare
  // hash collides about as often as birthdays do: with four figures on stage two
  // of them came out the same green, and two specialists in one colour is the
  // exact opposite of what a colour per specialist is for. The agent takes its
  // hue first so it is stable whoever else is on stage, and each specialist takes
  // the first free hue from where its own hash points — so a name still decides
  // the colour, and adding a colleague never recolours the people already there.
  // The agent takes the teal the rest of this desktop is branded in, so the
  // figure in the middle reads as THIS machine's agent and not as one more
  // specialist that happens to be bigger.
  const AGENT_IX=2, AGENT_HUE=CREW_HUES[AGENT_IX], used={};
  used[AGENT_IX]=1;
  const hueOf=[];
  for(let i=0;i<n;i++){
    const want=Math.floor(crewHash(C.cast[i].name)*CREW_HUES.length)%CREW_HUES.length;
    let ix=want;
    for(let k=0;k<CREW_HUES.length;k++){const j=(want+k)%CREW_HUES.length;if(!used[j]){ix=j;break}}
    used[ix]=1;hueOf.push(CREW_HUES[ix]);
  }
  // the agent — larger, centre, awake while any turn runs
  const aLift=running?.5+.5*Math.sin(C.t*Math.PI*1.1):0;
  const aBreath=running?0:.5+.5*Math.sin(C.t*Math.PI*.55);
  const headY=crewFigure(ctx,W/2,ground,scale*1.22,ink,.5,AGENT_HUE,running?.55:0,
    running?aLift*.5:0,who,'',running);
  if(running){ // a quiet ring round the agent's head — a ring, never a shadow
    ctx.beginPath();ctx.arc(W/2,headY,scale*1.22*.30+aBreath*2,0,Math.PI*2);
    ctx.strokeStyle=`rgba(${ink.ruby},.22)`;ctx.lineWidth=1.5;ctx.stroke();
  }
  // the cast
  slots.forEach((s,i)=>{
    const lit=!!C.busy[s.c.name];
    const since=lit?(now-C.busy[s.c.name])/CREW_WORK_MS:1;
    const p=lit?Math.min(1,(1-since)*3):0;               // step forward, then ease back
    const lift=lit?.5+.5*Math.sin(C.t*Math.PI*1.6+crewHash(s.c.name)*6):0;
    crewFigure(ctx,s.x,ground,scale,ink,crewHash(s.c.name),hueOf[i],p,lift,
      s.c.name.replace(/[-_]/g,' ').slice(0,18),s.c.role,lit);
  });
  // the tool that just ran, above whoever ran it — the one label that carries news.
  // Tinted like that figure, so with three working at once the name and the person
  // it belongs to are one glance rather than two.
  if(C.tool){
    const age=(now-C.tool.at)/CREW_TOOL_MS,fade=Math.max(0,1-age);
    const owner=C.tool.who?slots.find(s=>s.c.name===C.tool.who):null;
    const sc=owner?scale:scale*1.22;
    const skin=crewSkin(ink,owner?hueOf[slots.indexOf(owner)]:AGENT_HUE,true);
    // clear of the status light, which sits at ~0.87 of a figure's height
    const tx=owner?owner.x:W/2, ty=ground-sc*1.24;
    crewText(ctx,C.tool.name,tx,ty,Math.max(9.5,scale*.125),null,.9*fade,600,'center',skin.line);
    ctx.beginPath();ctx.moveTo(tx,ty+scale*.085);ctx.lineTo(tx,ty+scale*.14);
    ctx.globalAlpha=.55*fade;ctx.strokeStyle=skin.line;ctx.lineWidth=1;ctx.stroke();ctx.globalAlpha=1;
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
