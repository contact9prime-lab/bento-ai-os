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
   - **Drawn, not loaded.** A figure is built from arcs and lines at draw time,
     in a colour of its own, with saturation and lightness taken from the theme.
     No tileset, no sprite sheet, no character pack — which is also why this
     scene raises no asset-licence question and adds no bytes to the wheel.
   - **They have to read as CARTOON PEOPLE, and it took three passes.** The first
     drew outlined wire bodies, identical in one brass colour, frozen at rest,
     with a single red dot in the middle of each face; the report on it was one
     word: scary. The second gave them filled bodies, a colour each and simple
     faces — friendly, and an infographic. The third outlined every shape, which
     is what makes a drawing read as drawn. Each fix is pinned in
     `tests/test_immersive.py`, because every one of them is easy to undo while
     "simplifying" the drawing:
       a filled, OUTLINED body      an outline is what a cartoon is; without one
                                    the same shapes are a diagram, and a fill
                                    with no outline is a ghost
       a colour per specialist      handed out across the row so no two share
                                    one, since a bare hash collides
       a face with TWO eyes         one centred mark is a cyclops, so the running
                                    light lives above the head — and the face
                                    stays SIMPLE, one solid eye plus a catchlight
       hands, feet, squash, life    a limb that ends in mid-air is unfinished, a
                                    bounce without squash is a moved object, and
                                    a motionless row is a waxwork

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
    satLit: light ? 68 : 66,  lumLit: light ? 60 : 70,   // working
    satDim: light ? 56 : 52,  lumDim: light ? 52 : 60,   // standing by
    brass: light ? '150,116,52' : '232,197,120',
    ruby:  light ? '212,60,96'   : '236,80,120'};
}
/* One specialist's colours, stable for its name. The eyes are a deep shade of
   the figure's OWN hue rather than a literal black — the rule the whole look
   keeps, and here it also stops eight characters sharing one dead pupil. */
function crewSkin(ink, h, lit){
  const sa = lit ? ink.satLit : ink.satDim, l = lit ? ink.lumLit : ink.lumDim;
  return {hue: h,
          fill:  `hsl(${h} ${sa}% ${l}%)`,
          // the lit top of a shape: two flat tones is what a cel-painted cartoon
          // does instead of a gradient, and it costs one more fill
          top:   `hsl(${h} ${sa - 6}% ${l + 13}%)`,
          line:  `hsl(${h} ${sa + 8}% ${l + 16}%)`,
          // THE OUTLINE. A deep shade of the figure's own hue rather than one
          // shared black: eight characters sharing one ink is what makes a set
          // look printed rather than drawn, and the rule against literal blacks
          // is the same one the rest of this look keeps.
          ink:   `hsl(${h} ${Math.min(58, sa + 10)}% ${ink.light ? 30 : 26}%)`,
          dark:  `hsl(${h} ${Math.round(sa * .45)}% 14%)`,
          // the whites of the eyes — a very light tint of the hue, never a
          // literal white, so it still belongs to the character
          eye:   `hsl(${h} 34% 96%)`,
          shade: `hsl(${h} 26% 7%)`};
}
/* A limb: one path, stroked TWICE — the outline colour at full width, then the
   skin colour at 62% of it. That is how a cartoon limb is drawn and it is much
   cheaper than outlining a filled shape, because the second stroke reuses the
   path the first one built. */
function crewLimb(ctx, pts, w, ink, fill){
  ctx.beginPath();ctx.moveTo(pts[0], pts[1]);
  for(let i=2;i<pts.length;i+=2)ctx.lineTo(pts[i], pts[i+1]);
  ctx.strokeStyle=ink;ctx.lineWidth=w;ctx.stroke();
  ctx.strokeStyle=fill;ctx.lineWidth=w*.62;ctx.stroke();
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
/* A name cut to the room its own slot has. Six specialists on a phone leaves
   about 48px a head, where "validator" and "researcher" ran into each other and
   read as one word — the label stopped naming anybody. Derived from the step and
   the font size rather than a fixed cap, so it only bites where it must. */
function crewFit(name,step,scale){
  const px=Math.max(9,scale*.115);
  const n=Math.max(5,Math.floor((step*.92)/(px*.58)));
  return name.length>n?name.slice(0,n-1)+'\u2026':name.slice(0,18);
}
/* A stable number from a name, so a specialist's build and stance never change
   between reloads. Cheap 32-bit string hash; nothing depends on its quality. */
function crewHash(s){let h=2166136261;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)}return (h>>>0)/4294967295}
/* One figure, drawn as a CARTOON.

   The flat-vector version this replaces was clean and read as an infographic:
   correct, and nobody's colleague. Six things make a drawing read as a cartoon
   instead, and they are all here because leaving any one out takes the whole
   effect with it:

     an OUTLINE on every shape   the single strongest signal, and the one the
                                 flat version had none of. A limb is one path
                                 stroked twice (crewLimb); a filled shape is a
                                 fill then a stroke.
     TWO FLAT TONES              a lighter top on the head and body. Cel paint,
                                 not a gradient — a gradient per shape per frame
                                 is a cost this layer cannot carry.
     EYES WITH PUPILS            a light sclera, a dark pupil and a highlight
                                 dot. Two plain dots are punctuation; this is a
                                 face that can look at something, and the pupils
                                 DO look — up at the tool label while working.
     EYEBROWS                    one arc each, and most of the expression. They
                                 lift when the specialist starts working.
     HANDS AND FEET              a cartoon limb ends in a mitt or a shoe. A limb
                                 that stops in mid-air reads as unfinished.
     SQUASH AND STRETCH          the body compresses at the bottom of a bounce
                                 and stretches at the top. Without it a bouncing
                                 figure is a rigid object being moved.

   Everything else about the scene is unchanged: `p` is 0 at the resting spot and
   1 stepped forward, `lift` is the working gesture, and the rest comes from
   CREW.t and the figure's own phase so nobody is ever completely still. No
   canvas shadow anywhere — a shadow is a blur by another name, and this layer is
   re-composited under the parallax on every pointer move. */
function crewFigure(ctx,x,ground,scale,ink,tone,hue,p,lift,label,sub,lit){
  const s=scale, t=CREW.t, ph=tone*6.283, skin=crewSkin(ink,hue,lit);
  const still=CREW.static;                       // reduced motion: one pose, no life
  const breath=still?0:Math.sin(t*1.5+ph);
  const sway  =still?0:Math.sin(t*0.7+ph)*s*.013;
  const hop   =lit&&!still?Math.abs(Math.sin(t*3.0+ph)):0;
  const bob   =hop*s*.055;
  // squash at the bottom of the hop, stretch at the top — the oldest trick in
  // the book and the one that separates a character from a moved object
  const sq    =lit&&!still?(1-hop):0;
  const cx=x+sway, y=ground-p*s*.24-bob;
  const a=lit?1:.88;
  ctx.lineCap='round';ctx.lineJoin='round';
  ctx.globalAlpha=a;
  const lw=Math.max(1.8,s*.05);                  // the outline weight, once
  const limbW=lw*1.3;                            // limbs carry more than an outline does
  // proportions: a LARGE head on a short body, which is what a cartoon is
  const headR=s*.205*(1+sq*.03), legH=s*.13;
  const bw=s*(.28+tone*.05)*(1+sq*.06), bh=(s*.26+breath*s*.006)*(1-sq*.07);
  const legTop=y-legH, bodyTop=legTop-bh, headY=bodyTop-headR*.80;
  // the ground contact, so nobody floats
  if(ctx.ellipse){
    ctx.beginPath();ctx.ellipse(cx,ground+1,bw*.62,s*.028,0,0,Math.PI*2);
    ctx.globalAlpha=.30*a;ctx.fillStyle=skin.shade;ctx.fill();ctx.globalAlpha=a;
  }
  // ---- behind the body: legs and arms ----
  const stance=bw*.28;
  crewLimb(ctx,[cx-stance,y-s*.01,cx-stance,legTop],limbW,skin.ink,skin.fill);
  crewLimb(ctx,[cx+stance,y-s*.01,cx+stance,legTop],limbW,skin.ink,skin.fill);
  // shoes — one path, both feet
  if(ctx.ellipse){
    ctx.beginPath();
    ctx.ellipse(cx-stance,y,s*.052,s*.032,0,0,Math.PI*2);
    ctx.ellipse(cx+stance,y,s*.052,s*.032,0,0,Math.PI*2);
    ctx.fillStyle=skin.ink;ctx.fill();
  }
  const sh=bodyTop+bh*.24, el=s*.15, fa=s*.13;
  const swing=still?0:Math.sin(t*1.1+ph)*.12;
  const hand=[];
  [-1,1].forEach(d=>{
    const ax=cx+d*bw*.44;
    const ex=ax+d*(el*(.36+.26*lift)), ey=sh+el*(.82-.24*lift+swing*d);
    const hx=ex+d*fa*(.40-.68*lift), hy=ey+fa*(.76-1.48*lift);
    crewLimb(ctx,[ax,sh,ex,ey,hx,hy],limbW,skin.ink,skin.fill);
    hand.push(hx,hy);
  });
  // ---- the body ----
  ctx.beginPath();
  if(ctx.roundRect)ctx.roundRect(cx-bw/2,bodyTop,bw,bh,bw*.38);
  else ctx.rect(cx-bw/2,bodyTop,bw,bh);
  ctx.fillStyle=skin.fill;ctx.fill();
  ctx.strokeStyle=skin.ink;ctx.lineWidth=lw;ctx.stroke();
  // mitts, drawn after the body so a hand crossing it stays on top
  ctx.beginPath();
  ctx.arc(hand[0],hand[1],s*.045,0,Math.PI*2);
  ctx.moveTo(hand[2]+s*.045,hand[3]);ctx.arc(hand[2],hand[3],s*.045,0,Math.PI*2);
  ctx.fillStyle=skin.fill;ctx.fill();ctx.strokeStyle=skin.ink;ctx.lineWidth=lw*.8;ctx.stroke();
  // ---- the head ----
  ctx.beginPath();ctx.arc(cx,headY,headR,0,Math.PI*2);
  ctx.fillStyle=skin.fill;ctx.fill();
  ctx.save();ctx.clip();                          // the lit top, again as flat paint
  ctx.beginPath();ctx.arc(cx-headR*.22,headY-headR*.30,headR*.92,0,Math.PI*2);
  ctx.fillStyle=skin.top;ctx.fill();
  ctx.restore();
  ctx.beginPath();ctx.arc(cx,headY,headR,0,Math.PI*2);
  ctx.strokeStyle=skin.ink;ctx.lineWidth=lw;ctx.stroke();
  // ---- the face ----
  // The pupils LOOK somewhere: up at the tool label while working, level at
  // rest. A face that never directs its gaze is a mask with eyes painted on.
  const blinking=!still&&((t*.31+tone*3)%1)<.045;
  const ex=headR*.33, ey=headY-headR*.04, erx=headR*.15, ery=headR*.185;
  if(blinking){
    ctx.beginPath();
    [-1,1].forEach(d=>{ctx.moveTo(cx+d*ex-erx*1.3,ey);ctx.lineTo(cx+d*ex+erx*1.3,ey)});
    ctx.strokeStyle=skin.ink;ctx.lineWidth=lw*.8;ctx.stroke();
  }else{
    // A SOLID dark eye with one catchlight. The cut before this gave each eye a
    // light sclera, a dark rim and an eyebrow, which is correct cartoon anatomy
    // at poster size and turns into a compound eye at forty pixels: a row of
    // them read as insects. At this scale the face wants FEWER marks, not more —
    // three per eye is two too many.
    ctx.beginPath();
    [-1,1].forEach(d=>{
      ctx.moveTo(cx+d*ex+erx,ey);
      if(ctx.ellipse)ctx.ellipse(cx+d*ex,ey,erx,ery,0,0,Math.PI*2);
      else ctx.arc(cx+d*ex,ey,erx,0,Math.PI*2);
    });
    ctx.fillStyle=skin.ink;ctx.fill();
    ctx.beginPath();                               // the catchlight, and nothing else
    [-1,1].forEach(d=>{const hx2=cx+d*ex-erx*.30,hy2=ey-ery*.34,r=erx*.36;
      ctx.moveTo(hx2+r,hy2);ctx.arc(hx2,hy2,r,0,Math.PI*2)});
    ctx.fillStyle=skin.eye;ctx.fill();
  }
  // the mouth, drawn on EVERY frame including a blink: tying it to the eyes made
  // a blinking figure lose its mouth, which reads as the face coming apart
  ctx.beginPath();
  ctx.arc(cx,headY+headR*.26,headR*(lit?.34:.28),lit?.10*Math.PI:.16*Math.PI,lit?.90*Math.PI:.84*Math.PI);
  ctx.strokeStyle=skin.ink;ctx.lineWidth=lw*.8;ctx.stroke();
  // working: a status light above the head, pulsing. Off the face on purpose.
  if(lit){
    const pulse=still?1:.6+.4*Math.sin(t*4+ph);
    ctx.beginPath();ctx.arc(cx,headY-headR*1.32,Math.max(2.5,s*.036),0,Math.PI*2);
    ctx.fillStyle=`rgba(${ink.ruby},${.55+.45*pulse})`;ctx.fill();
    ctx.strokeStyle=skin.ink;ctx.lineWidth=lw*.55;ctx.stroke();
  }
  ctx.globalAlpha=1;
  // the name, tinted like its owner; the role only for the one stepped forward
  crewText(ctx,label,x,ground+s*.26,Math.max(9,s*.115),null,lit?.95:.55,600,'center',skin.line);
  if(sub&&p>.5)crewText(ctx,sub,x,ground+s*.40,Math.max(8,s*.10),null,.42*p,500,'center',skin.line);
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
      crewFit(s.c.name.replace(/[-_]/g,' '),step,scale),s.c.role,lit);
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
