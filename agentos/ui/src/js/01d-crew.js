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
   - **They are the SAME people as everywhere else.** Each figure is the
     character the server drew for that principal (agentos/avatars.py) — the
     face beside its messages in Chat, on its lines in Logs and on its card in
     Missions — fetched once as a four-frame sheet and blitted. This file paints
     nobody. It used to (four passes of its own painter, which is where the
     rules below were learned), and a second painter was a second definition of
     a face: the researcher on the stage and the researcher in Chat would have
     been two people the first time either was changed. Nothing is licensed and
     nothing ships: the sheet is generated on this machine from a stored recipe.
   - **The rules the four drawing passes left** — two eyes and nothing on the
     face that masks it, a working light ABOVE the head, a colour per
     specialist that no two share, hands and feet, a shadow at the feet, and
     nobody ever completely still — now live in the server's painter and its
     tests (`tests/test_avatars.py`); the ones about MOVEMENT stay here.
   - **The stage is where the roster changes, too.** A specialist created while
     the scene is on walks in from the edge and says hello; one that finishes a
     piece of work says so in a bubble; in a huddle, the one talking lights up
     with the start of what it said over its head. All three are events, not
     decoration: `fabric_defs`, `flow_done` and `agent_say`.
   - **Every figure says what it runs on.** Under each name is the provider it
     ANSWERS on (fabric.agent_brain via /api/subagents), and while it works the
     light above its head becomes a tag naming it — so three busy agents on three
     providers read as exactly that.

   Cost, and where it stops: the same budget as the Movement scene, because it
   is the same loop. One viewport canvas, at most 20 frames a second and 12 when
   idle, one drawImage per figure from a sheet fetched once, and at most nine figures. Not drawn at all
   when the tab is hidden, under a full-screen or maximised window, or under a
   phone sheet; one still frame under prefers-reduced-motion. No filter, no blur,
   no canvas shadow. The roster is fetched once a minute while the scene is on,
   and never for the sake of an animation.

   Faces — GUI/SUI: this canvas, inside #wall so the parallax carries it.
   TUI: not applicable, a terminal has no wallpaper; the scene row says so.
   `var`, not `let`: the bundle is one script. */
var CREW={on:false,cv:null,ctx:null,raf:0,last:0,t:0,W:0,H:0,dpr:1,font:'',static:false,
  cast:[],rosterAt:0,busy:{},tool:null,turns:0,drawn:0,drawMs:0,greeted:0,
  arrive:{},said:{},known:null};
var CREW_SHEETS={};                   // key → {img,v}: one sheet per character, from the server
var CREW_WALK_MS=2600;                // a new specialist's walk in from the edge
var CREW_SAY_MS=3800;                 // how long a bubble stays up
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
  CREW_SHEETS={};CREW.known=null;CREW.arrive={};CREW.said={};
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
async function crewRoster(force){
  if(!CREW.on)return;
  if(!force&&performance.now()-CREW.rosterAt<60000&&CREW.cast.length)return;
  CREW.rosterAt=performance.now();
  try{
    const d=await (await fetch('/api/subagents')).json();
    // Everybody keeps their place: people already on stage in the order they
    // stood, newcomers after them. Sorted afresh, a new name early in the
    // alphabet slid the whole row sideways the moment it arrived.
    const was=CREW.cast.map(c=>c.name);
    const pos=n=>{const i=was.indexOf(n);return i<0?1e9:i};
    CREW.agentBrain=(d.agent_brain&&d.agent_brain.provider_name)||'';
    CREW.cast=(d.subagents||d.agents||[])
      .filter(s=>s&&(s.name||s.id)&&s.enabled!==false)
      // `brain` is what the agent ANSWERS on (fabric.agent_brain), not what it is
      // pinned to — a switched-off provider sends it to the machine's brain
      .map(s=>({name:String(s.name||s.id),brain:(s.brain&&s.brain.provider_name)||''}))
      .sort((a,b)=>pos(a.name)-pos(b.name))
      .slice(0,CREW_MAX);
    // somebody new has no character yet until /api/avatars has generated one
    if(typeof avatarsLoad==='function'&&CREW.cast.some(c=>!AVATARS.by[c.name]))await avatarsLoad();
    // Arrivals. The first roster is who was already here — nobody walks in on a
    // page load, or every reload would be a parade. After that, a name the stage
    // has not seen walks in from the nearer edge and says hello.
    const now=performance.now();
    if(CREW.known)CREW.cast.forEach(c=>{if(!CREW.known.has(c.name)){CREW.arrive[c.name]=now;crewSay(c.name,'hello!')}});
    CREW.known=new Set(CREW.cast.map(c=>c.name));
    crewKick();
  }catch(e){}
}
/* The roster or somebody's look changed: a new sheet for anybody whose version
   moved, and a fresh roster so a specialist made a moment ago walks on now
   rather than within the minute. Called by 00e's repaint. */
function crewAvatarsChanged(){
  if(!CREW.on)return;
  for(const k in CREW_SHEETS){const a=AVATARS.by[k];if(!a||a.v!==CREW_SHEETS[k].v)delete CREW_SHEETS[k]}
  crewRoster(true);
}
/* A bubble above a figure. Short, and only for things that happened. */
/* `turn` marks a huddle line: a conversation has one speaker at a time, so a new
   turn clears the last one's words instead of stacking a crowd of bubbles. */
function crewSay(name,text,turn){
  if(turn)for(const k in CREW.said)if(CREW.said[k].turn)delete CREW.said[k];
  CREW.said[name]={text:String(text).slice(0,40),at:performance.now(),turn:!!turn};crewKick()}
/* An impulse from the OS, forwarded by movementPulse so the websocket keeps one
   seam. `flow` carries a name that may be a flow, an agent or an event — we
   light whichever cast member it matches, and nobody if it matches none, rather
   than lighting a random figure to make the scene look busy. */
function crewPulse(kind,label,ev){
  if(!CREW.on)return;
  const now=performance.now();
  if(kind==='turn'){CREW.turns++;crewKick();return}
  // a turn of a huddle: the one talking lights up, with its words over its head
  if(kind==='say'){const w=crewMatch(label);
    // a question to a colleague says who it is for, so the stage reads as a conversation
    if(w){CREW.busy[w]=now;crewSay(w,(ev&&ev.to?'@'+ev.to+' ':'')+String((ev&&ev.text)||''),true)}
    crewKick();return}
  if(kind==='turnend'){CREW.turns=Math.max(0,CREW.turns-1);crewKick();return}
  if(kind==='tool'&&label){
    CREW.tool={name:String(label).replace(/_/g,' ').slice(0,24),at:now,who:crewWhoIsUp()};
    crewKick();return;
  }
  const who=crewMatch(label)||crewMatch(ev&&ev.agent);
  if(kind==='flow'){if(who)CREW.busy[who]=now;crewKick();return}
  if(kind==='done'){if(who){delete CREW.busy[who];crewSay(who,'done \u2713')}crewKick();return}
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
  for(const k in CREW.said)if(CREW.said[k].at<now-CREW_SAY_MS)delete CREW.said[k];
  for(const k in CREW.arrive)if(CREW.arrive[k]<now-CREW_WALK_MS)delete CREW.arrive[k];
}
/* ---- drawing ---- */
/* The palette for everything that is NOT a person: the labels, the tool name,
   the ground shadow. The people are the server's; what the theme owns here is
   the room around them. Each specialist's colour is its shirt hue — handed out
   when the character was generated, distinct across the roster — so the name
   under a figure and the tool above it are tinted like the person they belong
   to. Brass and ruby are this look's two accents, shared with the dial. */
function crewInk(){
  const light=document.documentElement.dataset.theme==='light';
  // The crew's plate is a dark room in BOTH themes (immersive-crew.svg), as the
  // dial's is, so the labels are light-on-dark either way; the light theme
  // only sits them a little deeper so they do not read washed out beside it.
  // Working is MORE COLOUR, not more white — lightness alone took every name
  // towards beige, the opposite of the colour-per-specialist it is there for.
  return {light,
    satLit: light ? 68 : 66,  lumLit: light ? 60 : 70,   // working
    satDim: light ? 56 : 52,  lumDim: light ? 52 : 60,   // standing by
    brass: light ? '150,116,52' : '232,197,120',
    ruby:  light ? '212,60,96'   : '236,80,120'};
}
function crewSkin(ink, h, lit){
  const sa = lit ? ink.satLit : ink.satDim, l = lit ? ink.lumLit : ink.lumDim;
  return {hue: h,
          line:  `hsl(${h} ${sa + 8}% ${l + 16}%)`,
          shade: `hsl(${h} 26% 7%)`};
}
/* A character's colour: its shirt hue, from its stored recipe. Until the list
   has loaded, a stable fallback from the name, so the first frame is not grey. */
var CREW_AGENT_HUE=172;               // the server's AGENT_HUE: the desktop's teal
function crewHueOf(key){
  const a=(typeof AVATARS!=='undefined')&&AVATARS.by[key];
  if(a&&a.recipe&&typeof a.recipe.hue==='number')return a.recipe.hue;
  return key==='@agent'?CREW_AGENT_HUE:Math.floor(crewHash(key)*360);
}
/* The sheet: four frames side by side (stand, blink, one arm up, the other),
   16x26 each, fetched once per character and version. A sheet that has not
   arrived yet draws nothing that frame — never a placeholder person. */
var CREW_SPR_W=16, CREW_SPR_H=26;
function crewSheet(key){
  const a=(typeof AVATARS!=='undefined')&&AVATARS.by[key], v=a?a.v:0;
  let e=CREW_SHEETS[key];
  if(!e||e.v!==v){
    const img=new Image();img.decoding='async';
    img.onload=crewKick;
    img.src=avatarSrc(key,{sheet:1});
    e=CREW_SHEETS[key]={img,v};
  }
  return e.img.complete&&e.img.naturalWidth?e.img:null;
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
/* One figure: its shadow, its sprite, its status light, its name.

   `p` is 0 at the resting spot and 1 stepped forward. Motion is in whole
   sprite pixels, the way pixel art moves: an idle figure breathes by one pixel
   on its own slow phase and blinks now and then; a working one hops two pixels
   and waves, one arm and then the other. Under reduced motion it stands still
   in its first frame. A figure WALKING (a new arrival) swings its arms, one
   then the other, and bobs a pixel a step. Nothing here is a canvas shadow — the ground contact is a
   flat ellipse, because a shadow is a blur and this layer moves under the
   parallax on every pointer move. */
function crewFigure(ctx,x,ground,scale,ink,key,hue,p,lift,label,sub,lit,walking){
  const C=CREW, s=scale, t=C.t, tone=crewHash(key), ph=tone*6.283, still=C.static, dpr=C.dpr;
  // whole device pixels per sprite pixel: an integer, or it is not pixel art
  const u=Math.max(2,Math.round(s*dpr/25));
  const blinking=!still&&((t*.31+tone*3)%1)<.045;
  const frame=still?0:walking?(Math.floor(t*6)%2?3:2):lit?(Math.floor(t*3.2+ph)%2?3:2):blinking?1:0;
  const breath=still?0:(Math.sin(t*1.6+ph)>.35?1:0);
  const hop=lit&&!still?Math.round(Math.abs(Math.sin(t*3.2+ph))*2):0;
  const bob=walking&&!still?Math.floor(t*6)%2:lit?hop:breath;   // in sprite pixels
  const y=ground-p*s*.24;
  const feet=Math.round(y*dpr), cxd=Math.round(x*dpr);
  const dx=cxd-8*u, dy=feet-25*u-bob*u;
  // The ground contact, so nobody floats. It follows the STEP — a figure that
  // walks up the stage takes its shadow with it, or it hangs over a mark on the
  // front line like a puppet — and stays down through the HOP, which is the
  // only thing that tells a jump from a float.
  if(ctx.ellipse){
    ctx.beginPath();ctx.ellipse(x,y+1,6*u/dpr,1.4*u/dpr,0,0,Math.PI*2);
    ctx.globalAlpha=.34;ctx.fillStyle=crewSkin(ink,hue,lit).shade;ctx.fill();ctx.globalAlpha=1;
  }
  const sheet=crewSheet(key);
  ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.imageSmoothingEnabled=false;
  ctx.globalAlpha=lit?1:.9;
  if(sheet)ctx.drawImage(sheet,frame*CREW_SPR_W,0,CREW_SPR_W,CREW_SPR_H,dx,dy,CREW_SPR_W*u,CREW_SPR_H*u);
  // working: a status light above the head, pulsing, square like the rest of
  // the figure. Off the face on purpose — one mark in the middle of a face is
  // what made the very first cut of this scene read as frightening.
  const pulse=still?1:.6+.4*Math.sin(t*4+ph), q=Math.max(2,Math.round(u*1.4));
  if(lit&&!sub){
    ctx.globalAlpha=.55+.45*pulse;ctx.fillStyle=`rgb(${ink.ruby})`;
    ctx.fillRect(cxd-Math.round(q/2),dy-q-u,q,q);
  }
  ctx.restore();
  const col=crewSkin(ink,hue,lit).line;
  // Working, with a known brain: the light becomes a tag above the head that says
  // WHAT it is working on — "● Anthropic" — so a row of three busy agents on three
  // providers reads as that at a glance. The dot is the same pulsing ruby light.
  if(lit&&sub)crewTag(ctx,sub,x,dy/dpr-u/dpr,Math.max(9,s*.11),col,.55+.45*pulse,ink);
  // the name, tinted like its owner, and under it the brain it answers on
  crewText(ctx,label,x,ground+s*.24,Math.max(9,s*.115),null,lit?.95:.6,600,'center',col);
  if(sub)crewText(ctx,sub,x,ground+s*.37,Math.max(8,s*.095),null,lit?.7:.34,500,'center',col);
  return (dy+7*u)/dpr;                                 // the head's centre, for the halo
}
/* The working tag: a pill above the head with the pulsing light and the provider. */
function crewTag(ctx,text,x,top,size,col,pulse,ink){
  ctx.font=`600 ${size}px ${CREW.font||'sans-serif'}`;
  const h=Math.round(size*1.6), dot=Math.round(size*.5);
  const w=Math.ceil(ctx.measureText(text).width)+dot+size*1.3;
  const bx=Math.round(x-w/2), by=Math.round(top-h-3);
  ctx.globalAlpha=.82;ctx.fillStyle=ink.light?'rgb(252,248,240)':'rgb(16,18,26)';
  ctx.beginPath();if(ctx.roundRect)ctx.roundRect(bx,by,w,h,h/2);else ctx.rect(bx,by,w,h);ctx.fill();
  ctx.globalAlpha=pulse;ctx.fillStyle=`rgb(${ink.ruby})`;
  ctx.fillRect(bx+Math.round(size*.55),by+Math.round((h-dot)/2),dot,dot);
  ctx.globalAlpha=1;
  crewText(ctx,text,bx+size*.55+dot+(w-size*1.1-dot)/2,by+h/2,size,null,.95,600,'center',col);
}
function crewBubble(ctx,text,x,y,size,col,alpha,ink,maxW){
  ctx.font=`600 ${size}px ${CREW.font||'sans-serif'}`;
  // no wider than the figure's own slot: two neighbours talking must not overlap
  if(maxW&&ctx.measureText(text).width+size*1.1>maxW){
    while(text.length>4&&ctx.measureText(text+'\u2026').width+size*1.1>maxW)text=text.slice(0,-1);
    text=text.trimEnd()+'\u2026';
  }
  const w=Math.ceil(ctx.measureText(text).width)+size*1.1, h=Math.round(size*1.8);
  const bx=Math.round(x-w/2), by=Math.round(y-h);
  ctx.globalAlpha=.9*alpha;ctx.fillStyle=ink.light?'rgb(252,248,240)':'rgb(20,22,30)';
  ctx.beginPath();
  if(ctx.roundRect)ctx.roundRect(bx,by,w,h,h/2);else ctx.rect(bx,by,w,h);
  ctx.fill();ctx.strokeStyle=col;ctx.lineWidth=1;ctx.stroke();
  ctx.fillRect(Math.round(x)-1,by+h,2,3);
  ctx.globalAlpha=1;
  crewText(ctx,text,x,by+h/2,size,null,alpha,600,'center',col);
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
  // Colours are the characters' own: each shirt hue was handed out when the
  // character was generated, distinct across the roster and teal for the agent
  // (avatars.py). Deciding them here as well — which this scene once did, per
  // row — would be a second answer to "what colour is the researcher?".
  const AGENT_HUE=crewHueOf('@agent');
  const hueOf=C.cast.map(c=>crewHueOf(c.name));
  // the agent — larger, centre, awake while any turn runs
  const aLift=running?.5+.5*Math.sin(C.t*Math.PI*1.1):0;
  const aBreath=running?0:.5+.5*Math.sin(C.t*Math.PI*.55);
  const headY=crewFigure(ctx,W/2,ground,scale*1.22,ink,'@agent',AGENT_HUE,running?.55:0,
    running?aLift*.5:0,who,C.agentBrain||'',running);
  const heads={'@agent':{x:W/2,y:headY,sc:scale*1.22,hue:AGENT_HUE}};
  if(running){ // a quiet ring round the agent's head — a ring, never a shadow
    ctx.beginPath();ctx.arc(W/2,headY,scale*1.22*.24+aBreath*2,0,Math.PI*2);
    ctx.strokeStyle=`rgba(${ink.ruby},.22)`;ctx.lineWidth=1.5;ctx.stroke();
  }
  // the cast. A new arrival walks from the nearer edge to its place, eased
  // out so it slows as it arrives; it is drawn at its place from then on.
  slots.forEach((s,i)=>{
    const name=s.c.name, lit=!!C.busy[name];
    const since=lit?(now-C.busy[name])/CREW_WORK_MS:1;
    const p=lit?Math.min(1,(1-since)*3):0;               // step forward, then ease back
    const lift=lit?.5+.5*Math.sin(C.t*Math.PI*1.6+crewHash(name)*6):0;
    let x=s.x, walking=false;
    if(C.arrive[name]&&!C.static){
      const q=Math.min(1,(now-C.arrive[name])/CREW_WALK_MS), from=s.x<W/2?-scale*.4:W+scale*.4;
      x=from+(s.x-from)*(1-Math.pow(1-q,3));walking=q<1;
    }
    const hy=crewFigure(ctx,x,ground,scale,ink,name,hueOf[i],p,lift,
      crewFit(name.replace(/[-_]/g,' '),step,scale),s.c.brain,lit,walking);
    heads[name]={x,y:hy,sc:scale,hue:hueOf[i]};
  });
  // What somebody SAID: a hello on arrival, "done" when its work finished.
  // A flat rounded box and a two-pixel tail, above the head and clear of the
  // working light; it fades out over its last second.
  for(const k in C.said){
    const h=heads[k];if(!h)continue;
    const age=(now-C.said[k].at)/CREW_SAY_MS, a=age>.75?(1-age)*4:1;
    const up=C.busy[k]||(k==='@agent'&&C.turns)?.62:.42;   // clear of the working tag
    crewBubble(ctx,C.said[k].text,h.x,h.y-h.sc*up,Math.max(9.5,scale*.12),crewSkin(ink,h.hue,true).line,a,ink,
      Math.max(90,(step||scale*2)*1.1));
  }
  // the tool that just ran, above whoever ran it — the one label that carries news.
  // Tinted like that figure, so with three working at once the name and the person
  // it belongs to are one glance rather than two.
  if(C.tool){
    const age=(now-C.tool.at)/CREW_TOOL_MS,fade=Math.max(0,1-age);
    const owner=C.tool.who?heads[C.tool.who]:null;
    const sc=owner?scale:scale*1.22;
    const skin=crewSkin(ink,owner?owner.hue:AGENT_HUE,true);
    // clear of the status light, which sits at ~0.87 of a figure's height
    const tx=owner?owner.x:W/2, ty=ground-sc*1.46;
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
