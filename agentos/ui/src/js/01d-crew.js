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
   - **Drawn, not loaded.** Each figure is a small pixel-art PERSON — skin tone,
     hair, glasses, a shirt in the specialist's colour, trousers, shoes — painted
     at run time from a recipe seeded by its name, so the same specialist is the
     same person on every reload. No tileset, no sprite sheet, no character
     pack: this scene raises no asset-licence question and adds no bytes to the
     wheel. The drawing is further down, under "the people".
   - **It took four passes to read as people, and each one left a rule.** Wire
     outlines in one colour with a dot for a face read as SCARY. Filled vector
     blobs read as an infographic. Outlined vector cartoons read as MASCOTS —
     one colour head to toe, a ball for a head. What reads as a person at forty
     pixels is a person's parts, drawn as pixel art so they stay crisp. The rules
     that survived all four — two eyes and nothing on the face that masks it, a
     working light ABOVE the head, a colour per specialist that no two share,
     hands and feet, a shadow at the feet, and nobody ever completely still —
     are each pinned in `tests/test_immersive.py`.

   Cost, and where it stops: the same budget as the Movement scene, because it
   is the same loop. One viewport canvas, at most 20 frames a second and 12 when
   idle, one drawImage per figure from frames painted once, and at most nine figures. Not drawn at all
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
  CREW_SPRITES={};CREW_SPRITE_N=0;
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
/* The colours a figure's LABEL and ground shadow take. The figure itself is a
   sprite (below); only the text beside it is drawn with canvas strings. */
function crewSkin(ink, h, lit){
  const sa = lit ? ink.satLit : ink.satDim, l = lit ? ink.lumLit : ink.lumDim;
  return {hue: h,
          line:  `hsl(${h} ${sa + 8}% ${l + 16}%)`,
          shade: `hsl(${h} 26% 7%)`};
}

/* ---- the people ----

   Each figure is a small PIXEL-ART PERSON: a 16x26 sprite built from a recipe —
   skin tone, hair style and colour, glasses or not, trousers, and a shirt in the
   specialist's own colour — painted once into a tiny offscreen canvas and then
   blitted, scaled by a whole number, with smoothing off. That is the whole
   technique, and three passes of vector drawing before it are why it is here:

   - The vector figures could be made friendly and could be made cartoon, and
     they still read as MASCOTS — one colour from head to toe, a head that is a
     ball. What reads as a person at forty pixels is a person's parts: skin that
     is a skin colour, hair that is a shape of its own, a shirt, trousers, shoes.
     A recipe is what makes a row of eight into eight different people.
   - Pixel art is how a figure this small stays crisp. A vector outline at 40px
     antialiases into a grey smear; a one-pixel outline scaled by an integer is
     a hard edge at any size, and three flat tones per material (light, base,
     shade) give the form without a gradient.
   - It is CHEAPER than what it replaces. Every frame of every recipe is drawn
     once and cached; a figure on screen is one drawImage, where the cartoon
     was about twenty path operations.

   Skin and hair are literal palettes, and that is the one deliberate exception
   to this look's "every colour from the theme" rule: they are properties of
   PEOPLE, not of a theme, and a skin tone recoloured by Dracula would be wrong
   in a way that matters. What the theme still owns is the SHIRT — the
   specialist's colour, at the theme's saturation — and everything around the
   figures. Nothing here is loaded: no tileset, no sprite sheet, no licensed art,
   so there is no asset licence to carve out and nothing added to the wheel. */
var CREW_SPR_W=16, CREW_SPR_H=26;
var CREW_SPRITES={}, CREW_SPRITE_N=0;
var CREW_SKINS=[[252,224,203],[240,199,164],[214,163,122],[166,114,78],[110,73,50]];
var CREW_HAIR=[[40,33,38],[80,53,36],[124,84,52],[222,184,112],[152,66,42],[172,172,180]];
var CREW_DYED=[[226,114,162],[96,132,222],[118,196,160]];
var CREW_PANTS=[[60,78,120],[56,58,68],[150,128,92],[42,50,84],[96,70,52]];
var CREW_STYLES=['short','long','bun','curly','spiky','bald','bob'];
/* several independent picks out of one seed: a hash gives one number, and a
   recipe needs seven that do not move together (mulberry32) */
function crewRand(seed){
  let a=(Math.floor(seed*4294967295)>>>0)||1;
  return ()=>{a=(a+0x6D2B79F5)|0;let t=Math.imul(a^(a>>>15),1|a);
    t=(t+Math.imul(t^(t>>>7),61|t))^t;return ((t^(t>>>14))>>>0)/4294967296};
}
function crewRgb(h,s,l){
  s/=100;l/=100;const a=s*Math.min(l,1-l);
  const f=n=>{const k=(n+h/30)%12;return l-a*Math.max(-1,Math.min(k-3,9-k,1))};
  return [Math.round(f(0)*255),Math.round(f(8)*255),Math.round(f(4)*255)];
}
function crewTone(c,m){return [Math.min(255,Math.round(c[0]*m)),Math.min(255,Math.round(c[1]*m)),Math.min(255,Math.round(c[2]*m))]}
/* A person, from a seed and the colour the row gave them. */
function crewRecipe(seed,hue,ink,lit){
  const R=crewRand(seed), pick=arr=>arr[Math.floor(R()*arr.length)%arr.length];
  const skin=pick(CREW_SKINS), style=pick(CREW_STYLES);
  const hair=R()<.12?pick(CREW_DYED):pick(CREW_HAIR);
  return {skin, style, hair, pants:pick(CREW_PANTS), glasses:R()<.3, blush:R()<.45,
    // the shirt is the specialist's colour, at the theme's saturation, and a
    // working figure's shirt is the more saturated one — the same rule the
    // label and the tool name follow
    shirt:crewRgb(hue, lit?ink.satLit:ink.satDim, lit?56:48),
    // the outline: a deep shade of that same hue, never one shared black
    line:crewRgb(hue,28,13)};
}
/* Paint one frame of one person into a 16x26 canvas. Frames: 0 standing,
   1 blinking, 2 and 3 the two halves of the working wave (one arm up, then the
   other). Every coordinate below is this file's own drawing on its own grid. */
function crewPaint(rec,frame){
  const W=CREW_SPR_W,H=CREW_SPR_H,buf=new Uint8ClampedArray(W*H*4);
  const put=(x,y,c)=>{if(x<0||y<0||x>=W||y>=H)return;const i=(y*W+x)*4;buf[i]=c[0];buf[i+1]=c[1];buf[i+2]=c[2];buf[i+3]=255};
  const clr=(x,y)=>{if(x<0||y<0||x>=W||y>=H)return;buf[(y*W+x)*4+3]=0};
  const box=(x0,y0,x1,y1,c)=>{for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++)put(x,y,c)};
  const sk=rec.skin,skH=crewTone(sk,1.07),skS=crewTone(sk,.8);
  // A mouth is a LIP colour — warmer and redder than the face — and not a darker
  // skin. Skin at 55% brightness is grey-brown, and two pixels of it under a
  // nose read as a goatee on every light-skinned figure in the row.
  const mouth=[Math.round(sk[0]*.78),Math.round(sk[1]*.42),Math.round(sk[2]*.42)];
  const sh=rec.shirt,shH=crewTone(sh,1.25),shS=crewTone(sh,.7);
  const pa=rec.pants,paS=crewTone(pa,.72);
  const hr=rec.hair,hrH=crewTone(hr,1.35),hrS=crewTone(hr,.7);
  const ln=rec.line;
  // legs, belt and shoes
  box(5,19,7,22,pa);box(8,19,10,22,pa);box(5,19,10,19,paS);
  box(7,20,7,22,paS);box(10,20,10,22,paS);
  box(4,23,7,24,ln);box(8,23,11,24,ln);put(5,23,crewTone(ln,2.2));put(9,23,crewTone(ln,2.2));
  // torso: a lit left edge, a shaded right one, a collar
  box(4,13,11,18,sh);box(5,14,5,17,shH);box(11,14,11,18,shS);box(4,18,11,18,shS);
  box(6,13,9,13,shH);put(7,13,skS);put(8,13,skS);
  box(7,12,8,12,skS);                                   // neck
  // arms: down while standing; while working, one up and then the other
  const armDown=(x0)=>{box(x0,13,x0+1,16,sh);put(x0+(x0<8?0:1),14,x0<8?shH:shS);box(x0,17,x0+1,17,sk)};
  const armUp=(x0)=>{box(x0,9,x0+1,13,sh);box(x0,8,x0+1,8,sk)};
  if(frame===2){armUp(2);armDown(12)}else if(frame===3){armDown(2);armUp(12)}else{armDown(2);armDown(12)}
  // head: rounded, lit from the left, with ears
  box(4,3,11,11,sk);clr(4,3);clr(11,3);clr(4,11);clr(11,11);
  box(5,5,5,9,skH);box(11,4,11,10,skS);box(6,11,9,11,skS);   // a jaw, not a beard: the full-width row read as one on darker skin
  put(3,7,sk);put(3,8,skS);put(12,7,sk);put(12,8,skS);
  // the face: two eyes, a mouth that opens while working, sometimes cheeks
  if(frame===1){put(6,8,ln);put(9,8,ln)}
  else{put(6,7,ln);put(6,8,ln);put(9,7,ln);put(9,8,ln)}
  if(frame>=2){box(7,10,8,10,ln)}else{put(7,10,mouth);put(8,10,mouth)}
  if(rec.blush){const b=[232,136,136];put(5,9,b);put(10,9,b)}
  // Glasses: a rim over each eye and a pale lens beside it. A full frame drawn
  // in the line colour is correct at thirty pixels a lens and a MASK at one:
  // frame, eye and frame side by side filled the whole eye band, and a dark-
  // skinned figure in glasses came out with no face at all.
  if(rec.glasses){
    const lens=[214,226,236];
    box(5,6,7,6,ln);box(8,6,10,6,ln);
    put(5,7,lens);put(7,7,lens);put(8,7,lens);put(10,7,lens);
  }
  // hair, by style
  const cap=()=>{box(4,2,11,4,hr);clr(4,2);clr(11,2);put(4,5,hr);put(11,5,hr);box(6,2,8,2,hrH);put(10,4,hrS)};
  switch(rec.style){
    case 'short': cap();break;
    case 'long':  cap();box(3,4,4,13,hr);box(11,4,12,13,hr);box(3,12,3,13,hrS);box(12,12,12,13,hrS);break;
    case 'bob':   cap();box(3,4,4,10,hr);box(11,4,12,10,hr);box(5,4,10,4,hr);box(3,10,4,10,hrS);box(11,10,12,10,hrS);break;
    case 'bun':   cap();box(6,1,9,2,hr);put(7,1,hrH);break;
    case 'curly': box(3,2,12,4,hr);clr(3,2);clr(12,2);[4,7,10].forEach(x=>{put(x,1,hr);put(x+1,1,hr)});
                  box(3,5,3,7,hr);box(12,5,12,7,hr);[5,8,11].forEach(x=>put(x,3,hrH));break;
    case 'spiky': box(4,3,11,4,hr);[4,6,8,10].forEach(x=>{put(x,2,hr);put(x+1,1,hr)});put(5,1,hrH);put(9,1,hrH);put(4,5,hr);put(11,5,hr);break;
    case 'bald':  box(4,6,4,8,hr);box(11,6,11,8,hr);put(6,4,crewTone(sk,1.18));put(7,4,crewTone(sk,1.18));break;
  }
  // THE OUTLINE: every empty pixel touching the figure becomes the line colour.
  // One pass over the finished figure, so a new hair style needs no outline of
  // its own and cannot forget one.
  const alpha=new Uint8Array(W*H);
  for(let i=0;i<W*H;i++)alpha[i]=buf[i*4+3];
  for(let y=0;y<H;y++)for(let x=0;x<W;x++){
    if(alpha[y*W+x])continue;
    const n=(x>0&&alpha[y*W+x-1])||(x<W-1&&alpha[y*W+x+1])||(y>0&&alpha[(y-1)*W+x])||(y<H-1&&alpha[(y+1)*W+x]);
    if(n)put(x,y,ln);
  }
  const cv=document.createElement('canvas');cv.width=W;cv.height=H;
  cv.getContext('2d').putImageData(new ImageData(buf,W,H),0,0);
  return cv;
}
/* The cache. A frame is painted the first time it is asked for and never
   again; the key carries everything that changes the pixels, the theme's
   lightness included. Bounded, because a roster that churns all day would
   otherwise keep every person it ever drew. */
function crewSprite(seed,hue,ink,lit,frame){
  const key=`${seed}|${hue}|${lit?1:0}|${ink.light?1:0}|${frame}`;
  let spr=CREW_SPRITES[key];
  if(!spr){
    if(CREW_SPRITE_N>400){CREW_SPRITES={};CREW_SPRITE_N=0}
    spr=CREW_SPRITES[key]=crewPaint(crewRecipe(seed,hue,ink,lit),frame);CREW_SPRITE_N++;
  }
  return spr;
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
   in its first frame. Nothing here is a canvas shadow — the ground contact is a
   flat ellipse, because a shadow is a blur and this layer moves under the
   parallax on every pointer move. */
function crewFigure(ctx,x,ground,scale,ink,tone,hue,p,lift,label,sub,lit){
  const C=CREW, s=scale, t=C.t, ph=tone*6.283, still=C.static, dpr=C.dpr;
  // whole device pixels per sprite pixel: an integer, or it is not pixel art
  const u=Math.max(2,Math.round(s*dpr/25));
  const blinking=!still&&((t*.31+tone*3)%1)<.045;
  const frame=still?0:lit?(Math.floor(t*3.2+ph)%2?3:2):blinking?1:0;
  const breath=still?0:(Math.sin(t*1.6+ph)>.35?1:0);
  const hop=lit&&!still?Math.round(Math.abs(Math.sin(t*3.2+ph))*2):0;
  const bob=lit?hop:breath;                           // in sprite pixels
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
  const spr=crewSprite(tone,hue,ink,lit,frame);
  ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.imageSmoothingEnabled=false;
  ctx.globalAlpha=lit?1:.9;
  ctx.drawImage(spr,dx,dy,CREW_SPR_W*u,CREW_SPR_H*u);
  // working: a status light above the head, pulsing, square like the rest of
  // the figure. Off the face on purpose — one mark in the middle of a face is
  // what made the very first cut of this scene read as frightening.
  if(lit){
    const pulse=still?1:.6+.4*Math.sin(t*4+ph), q=Math.max(2,Math.round(u*1.4));
    ctx.globalAlpha=.55+.45*pulse;ctx.fillStyle=`rgb(${ink.ruby})`;
    ctx.fillRect(cxd-Math.round(q/2),dy-q-u,q,q);
  }
  ctx.restore();
  // the name, tinted like its owner; the role only for the one stepped forward
  const col=crewSkin(ink,hue,lit).line;
  crewText(ctx,label,x,ground+s*.24,Math.max(9,s*.115),null,lit?.95:.6,600,'center',col);
  if(sub&&p>.5)crewText(ctx,sub,x,ground+s*.38,Math.max(8,s*.10),null,.42*p,500,'center',col);
  return (dy+7*u)/dpr;                                 // the head's centre, for the halo
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
  const headY=crewFigure(ctx,W/2,ground,scale*1.22,ink,crewHash(who),AGENT_HUE,running?.55:0,
    running?aLift*.5:0,who,'',running);
  if(running){ // a quiet ring round the agent's head — a ring, never a shadow
    ctx.beginPath();ctx.arc(W/2,headY,scale*1.22*.24+aBreath*2,0,Math.PI*2);
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
