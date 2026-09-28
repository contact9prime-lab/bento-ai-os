/* ================= the World scene (experimental) =================
   Settings → Appearance → Scene → World. Your agents live in a small 3D world with
   feelings, growth and friendships, and your lead asks how YOU are once a day.

   The owner's rule, and the design: "the moment I leave the world scene it's all
   evaporated, and it comes back when I switch to that world. Scene matters." So this
   file holds a LEASE on the server (world.py): enter when the scene starts, beat every
   15 seconds, leave when it stops or the page goes away. While the lease is held the
   server turns real events into feelings; without it nothing is felt, nothing is read,
   and no agent is told anything. Nothing outside this file calls /api/world.

   Everything drawn is caused by something real: an agent's pose is the feeling the
   server worked out from its runs, and tapping its name tag shows why. When nothing is
   happening, the world is quiet (the water still moves, which is scenery, like the
   aurora).

   three.js (MIT, vendored at /assets/three.module.min.js) is imported only when this
   scene starts, so nobody else pays for it. Characters are the server's own painted
   sheets (avatarSrc, the one door), drawn as sprites: there is still one painter.

   Cost: at most 30 frames a second while somebody is animating and 12 at rest, none
   while covered (crewCovered) or hidden, one still frame under reduced motion. A screen
   with no WebGL (some Linux sessions on software rendering) gets a flat drawing of the
   same world and a sentence saying why, never a blank.

   Faces: GUI and SUI are this page. The TUI has no world, deliberately: it is an
   experiment that lives in a scene, and the owner asked for it to exist nowhere else. */
var WORLD={on:false,id:'',v:null,T:null,r:null,scene:null,cam:null,kit:null,chars:{},host:null,ui:null,
  raf:0,last:0,beatT:0,fetchT:0,snooze:0,flat:false,still:false,t0:0,moods:{},bubbles:{},open:'',menu:false,
  busyAsk:false,fx:[],waterT:0,why:''};
function worldId(){try{return localStorage.getItem('immersive.world')||'lantern-canal'}catch(e){return 'lantern-canal'}}
function worldSetId(id){try{localStorage.setItem('immersive.world',id)}catch(e){}}

async function worldStart(){
  if(WORLD.on)return;
  const wall=document.getElementById('wall'),desk=document.getElementById('desktop');if(!wall||!desk)return;
  WORLD.on=true;WORLD.t0=performance.now();
  WORLD.still=matchMedia('(prefers-reduced-motion: reduce)').matches;
  let host=document.getElementById('world-scene');
  if(!host){host=document.createElement('div');host.id='world-scene';host.setAttribute('aria-hidden','true');
    host.innerHTML='<canvas class="wd-cv"></canvas>';wall.appendChild(host)}
  let ui=document.getElementById('world-ui');
  if(!ui){ui=document.createElement('div');ui.id='world-ui';
    const home=document.getElementById('home');desk.insertBefore(ui,home?home.nextSibling:null)}
  WORLD.host=host;WORLD.ui=ui;
  ui.innerHTML='<div class="wd-tags"></div><div class="wd-chip"></div><div class="wd-side"><div class="wd-ask" hidden></div><div class="wd-card" hidden></div></div>';
  addEventListener('resize',worldResize);
  document.addEventListener('visibilitychange',worldKick);
  addEventListener('pagehide',worldLeaveBeacon);
  if(!await worldEnter(worldId()))await worldEnter('lantern-canal');
  if(!WORLD.on)return;
  await worldBuild();
  worldBeat();
}
function worldStop(){
  if(!WORLD.on)return;
  WORLD.on=false;
  clearTimeout(WORLD.beatT);clearTimeout(WORLD.fetchT);clearTimeout(WORLD.snooze);
  cancelAnimationFrame(WORLD.raf);WORLD.raf=0;
  removeEventListener('resize',worldResize);
  document.removeEventListener('visibilitychange',worldKick);
  removeEventListener('pagehide',worldLeaveBeacon);
  // evaporate: the server forgets it in memory, the page forgets it here
  fetch('/api/world/leave',{method:'POST',keepalive:true}).catch(()=>{});
  worldDispose();
  if(WORLD.host)WORLD.host.remove();if(WORLD.ui)WORLD.ui.remove();
  WORLD.host=WORLD.ui=null;WORLD.v=null;WORLD.moods={};WORLD.bubbles={};WORLD.open='';
}
function worldLeaveBeacon(){try{fetch('/api/world/leave',{method:'POST',keepalive:true})}catch(e){}}
async function worldEnter(id){
  try{
    const r=await fetch('/api/world/enter',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({world:id})});
    const v=await r.json();
    if(!r.ok||!v.live)return false;
    WORLD.id=v.world.id;worldSetId(WORLD.id);WORLD.v=v;return true;
  }catch(e){return false}
}
/* The lease: every 15s while the scene is up. A world that went to sleep (a missed
   beat, another tab left it) is entered again, so what is on screen is always live. */
async function worldBeat(){
  if(!WORLD.on)return;
  try{
    const r=await fetch('/api/world/beat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({world:WORLD.id})});
    const d=await r.json();
    if(!d.live&&WORLD.on){await worldEnter(WORLD.id);worldSync()}
  }catch(e){}
  if(WORLD.on)WORLD.beatT=setTimeout(worldBeat,15000);
}
/* Every websocket event passes here while the scene is on (09-websocket). The server
   has already felt it; the page asks for the new state once things settle. */
var WORLD_HEARS=['fabric_event','tool_end','turn_start','turn_end','error','approval_request',
  'approval_resolved','agent_msg','agent_say','subagents','avatars'];
function worldHear(ev){
  if(!WORLD.on||!ev||WORLD_HEARS.indexOf(ev.type)<0)return;
  if(ev.type==='fabric_event'&&['status','step','approval','fault'].indexOf(ev.event)<0)return;
  clearTimeout(WORLD.fetchT);WORLD.fetchT=setTimeout(worldRefresh,ev.type==='subagents'||ev.type==='avatars'?50:600);
}
async function worldRefresh(){
  if(!WORLD.on)return;
  try{
    const v=await (await fetch('/api/world/state')).json();
    if(!WORLD.on)return;
    if(!v.live){await worldEnter(WORLD.id)}else WORLD.v=v;
    worldSync();
  }catch(e){}
}

/* ---------------- building the 3D world ---------------- */
async function worldBuild(){
  worldDispose();
  // a fresh canvas every build: the last one's context was lost on purpose in
  // worldDispose, and a lost context cannot be handed to a new renderer (found
  // switching to a world just built: the scene came up white and flat)
  const cv=document.createElement('canvas');cv.className='wd-cv';
  const old=WORLD.host.querySelector('canvas');if(old)old.replaceWith(cv);else WORLD.host.appendChild(cv);
  WORLD.flat=false;WORLD.why='';
  try{
    WORLD.T=WORLD.T||await import('/assets/three.module.min.js');
    const T=WORLD.T;
    WORLD.r=new T.WebGLRenderer({canvas:cv,antialias:true,powerPreference:'low-power'});
    WORLD.r.setPixelRatio(Math.min(devicePixelRatio||1,document.body.classList.contains('dev-mobile')?1:1.5));
    WORLD.r.outputColorSpace=T.SRGBColorSpace;
    WORLD.r.toneMapping=T.ACESFilmicToneMapping;
    WORLD.hq=worldQuality(WORLD.r);
    if(WORLD.hq){WORLD.r.shadowMap.enabled=true;WORLD.r.shadowMap.type=T.PCFSoftShadowMap}
  }catch(e){WORLD.flat=true;WORLD.r=null;
    WORLD.why='This screen has no 3D graphics, so the world is drawn flat.'}
  WORLD.host.classList.toggle('flat',WORLD.flat);
  WORLD.host.dataset.kit=WORLD.v.world.kit;
  WORLD.fx=[];
  if(!WORLD.flat){
    const T=WORLD.T;
    WORLD.scene=new T.Scene();
    WORLD.cam=new T.PerspectiveCamera(42,innerWidth/innerHeight,.1,400);
    WORLD.kit=(WORLD_KITS[WORLD.v.world.kit]||WORLD_KITS.canal)(T,WORLD.scene,WORLD.cam);
    worldResize();
  }
  worldSync();
  worldKick();
}
/* Shadows and the busier particle counts are for a real GPU. Software rendering (the
   SUI on llvmpipe, a headless box) and phones get the light version, decided once per
   build. localStorage 'world.quality' = high or low overrides it. */
function worldQuality(r){
  try{const o=localStorage.getItem('world.quality');if(o)return o==='high'}catch(e){}
  if(document.body.classList.contains('dev-mobile'))return false;
  try{const gl=r.getContext(),x=gl.getExtension('WEBGL_debug_renderer_info');
    if(x&&/swiftshader|llvmpipe|software/i.test(gl.getParameter(x.UNMASKED_RENDERER_WEBGL)))return false}catch(e){}
  return true;
}
function worldDispose(){
  cancelAnimationFrame(WORLD.raf);WORLD.raf=0;
  if(WORLD.scene)WORLD.scene.traverse(o=>{if(o.geometry)o.geometry.dispose();
    const m=o.material;if(m){(Array.isArray(m)?m:[m]).forEach(x=>{if(x.map)x.map.dispose();x.dispose()})}});
  if(WORLD.r){try{WORLD.r.dispose();WORLD.r.forceContextLoss()}catch(e){}}
  WORLD.r=null;WORLD.scene=null;WORLD.kit=null;WORLD.chars={};WORLD.fx=[];WORLD.camBase=null;
  if(WORLD.ui){const t=WORLD.ui.querySelector('.wd-tags');if(t)t.innerHTML=''}
}
function worldResize(){
  if(!WORLD.r||!WORLD.cam)return;
  WORLD.r.setSize(innerWidth,innerHeight,false);
  WORLD.cam.aspect=innerWidth/innerHeight;
  // a tall phone screen: a wider lens, and the kit's own higher camera so the team
  // sits above the cards instead of under them
  const tall=innerWidth<innerHeight,k=WORLD.kit;
  WORLD.cam.fov=tall?58:42;
  WORLD.camBase=(k&&(tall?k.camTall:k.camWide))||[[0,6,30],[0,3,-20]];
  worldAim(0);
  WORLD.cam.updateProjectionMatrix();
  Object.values(WORLD.chars).forEach(c=>{if(k)c.home=worldSpot(c.i)});
  worldKick();
}
/* The places, the light and the mood effects are drawn by 01f-world-look.js. */
/* The camera breathes: a slow drift of a metre or so, which is what makes a still
   place read as a place rather than a picture. None under reduced motion. */
function worldAim(t){
  const b=WORLD.camBase;if(!b||!WORLD.cam)return;
  const d=WORLD.still?0:1;
  WORLD.cam.position.set(b[0][0]+Math.sin(t*.045)*.9*d,b[0][1]+Math.sin(t*.07)*.12*d,b[0][2]+Math.cos(t*.03)*.4*d);
  WORLD.cam.lookAt(b[1][0],b[1][1],b[1][2]);
}
/* Where each agent stands: the kit's spots, nearest first, so the lead is in front.
   A team bigger than the kit has spots for stands a row further back. */
function worldSpot(i){
  const s=WORLD.kit.spots,n=s.length,p=s[i%n];
  // a phone sees a narrow slice of the place, so the crescent closes up
  const sx=innerWidth<innerHeight?(WORLD.kit.tallX||.55):1;
  return new WORLD.T.Vector3(p[0]*sx,p[1],p[2]-Math.floor(i/n)*3.2);
}

/* ---------------- the people ---------------- */
function worldCast(){return (WORLD.v&&WORLD.v.agents)||[]}
function worldSync(){
  if(!WORLD.on||!WORLD.v)return;
  worldChip();worldAsk();
  const cast=worldCast();
  if(!WORLD.flat&&WORLD.scene){
    const T=WORLD.T;
    const keep=new Set(cast.map(a=>a.name));
    Object.keys(WORLD.chars).forEach(n=>{if(!keep.has(n)){const c=WORLD.chars[n];
      [c.sprite,c.shadow,c.crystal,c.vessel].forEach(o=>{if(o)WORLD.scene.remove(o)});delete WORLD.chars[n]}});
    cast.forEach((a,i)=>{
      let c=WORLD.chars[a.name];
      if(!c){
        const tex=new T.TextureLoader().load(avatarSrc(a.name,{sheet:1}),()=>worldKick());
        tex.magFilter=T.NearestFilter;tex.minFilter=T.NearestFilter;tex.colorSpace=T.SRGBColorSpace;
        tex.repeat.set(.25,1);
        const sp=new T.Sprite(new T.SpriteMaterial({map:tex,transparent:true,alphaTest:.5}));
        sp.scale.set(1.5,2.45,1);sp.center.set(.5,0);
        WORLD.scene.add(sp);
        // everyone starts at their place: walking in from the middle of the world
        // took seconds on software rendering, and read as the team wandering
        sp.position.copy(worldSpot(i));
        // a soft shadow under the feet, and the mood crystal over the head
        const sh=new T.Mesh(new T.PlaneGeometry(1.5,.75),new T.MeshBasicMaterial({map:wlShadowTex(T),transparent:true,depthWrite:false}));
        sh.rotation.x=-Math.PI/2;WORLD.scene.add(sh);
        const cr=wlCrystal(T);WORLD.scene.add(cr);
        c=WORLD.chars[a.name]={sprite:sp,tex,shadow:sh,crystal:cr,i,vessel:null,home:null,phase:Math.random()*6};
      }
      c.i=i;c.a=a;c.home=worldSpot(i);
      const vc=WL_VALENCE[a.mood.valence]!=null?WL_VALENCE[a.mood.valence]:WL_VALENCE[0];
      c.crystal.material.color.setHex(vc);c.crystal.material.emissive.setHex(vc);
      if(a.busy&&!c.vessel)c.vessel=WORLD.kit.vessel();
      if(!a.busy&&c.vessel){WORLD.scene.remove(c.vessel);c.vessel=null}
    });
    if(WORLD.kit.grow)WORLD.kit.grow(cast.reduce((s,a)=>s+(a.level?a.level.xp:0),0));
  }
  worldTags();
  // a feeling that changed says its line for a few seconds. When the whole team moves
  // at once (you told them how you are), the lead and one other speak: eight bubbles
  // together is a wall of text, not a scene.
  const changed=cast.filter(a=>{const was=WORLD.moods[a.name];WORLD.moods[a.name]=a.mood.id;return was&&was!==a.mood.id});
  (changed.length>2?changed.filter((a,i)=>a.name==='@agent'||i===changed.length-1).slice(0,2):changed).forEach(a=>worldSay(a));
  (WORLD.v.events||[]).forEach(e=>{if(e.grew&&!WORLD.bubbles['grew:'+e.agent+e.grew]){
    WORLD.bubbles['grew:'+e.agent+e.grew]=1;worldSay({name:e.agent},'Now a '+e.grew+'!')}});
  if(WORLD.open)worldCard(WORLD.open,true);
  worldKick();
}
function worldEmotion(id){return ((WORLD.v&&WORLD.v.world.emotions)||[]).find(e=>e.id===id)}
function worldSay(a,text){
  if(!text){const e=worldEmotion(a.mood.id);const ls=(e&&e.lines)||[];text=ls[Math.floor(Math.random()*ls.length)]||a.mood.name}
  WORLD.bubbles[a.name]={text,until:performance.now()+7000};worldTags();
}
function worldLabel(n){return n==='@agent'?(typeof agentName==='function'?agentName():'Your agent'):n}
/* Name tags are HTML over the canvas: crisp text, a real button a finger can hit, and
   the door to why each agent feels what it feels. */
function worldTags(){
  const box=WORLD.ui&&WORLD.ui.querySelector('.wd-tags');if(!box)return;
  const cast=worldCast(),now=performance.now();
  const have=new Set();
  cast.forEach((a,i)=>{
    have.add(a.name);
    let el=box.querySelector(`[data-wa="${CSS.escape(a.name)}"]`);
    if(!el){el=document.createElement('button');el.className='wd-tag';el.dataset.wa=a.name;
      el.onclick=()=>worldCard(a.name);box.appendChild(el)}
    const m=a.mood,b=WORLD.bubbles[a.name],say=b&&b.until>now?b.text:'';
    const html=(say?`<span class="wd-say">${esc(say)}</span>`:'')+
      (WORLD.flat?avatarImg(a.name,'wd-flatav',{crop:''}):'')+
      `<span class="wd-name"><b>${esc(m.emoji)}</b> ${esc(worldLabel(a.name))}</span>`;
    if(el._h!==html){el.innerHTML=html;el._h=html}
    el.style.setProperty('--mh',m.hue);
    el.title=`${m.name}. Tap to see why.`;
    el.setAttribute('aria-label',`${worldLabel(a.name)} feels ${m.name}. Tap to see why.`);
    el.className='wd-tag wx-'+m.expression+(a.busy?' busy':'');
    if(WORLD.flat){el.style.left=((i+.5)/cast.length*100)+'%';el.style.top='';el.classList.add('flat')}
  });
  [...box.children].forEach(el=>{if(!have.has(el.dataset.wa))el.remove()});
  Object.keys(WORLD.bubbles).forEach(k=>{if(WORLD.bubbles[k].until&&WORLD.bubbles[k].until<now)delete WORLD.bubbles[k]});
}

/* ---------------- the frame ---------------- */
function worldKick(){
  if(!WORLD.on||WORLD.raf)return;
  WORLD.raf=requestAnimationFrame(worldFrame);
}
function worldCovered(){return typeof crewCovered==='function'?crewCovered():document.hidden}
function worldFrame(now){
  WORLD.raf=0;
  if(!WORLD.on||WORLD.flat||!WORLD.r)return;
  if(worldCovered()){clearTimeout(WORLD.snooze);WORLD.snooze=setTimeout(worldKick,1000);return}
  const lively=worldCast().some(a=>a.busy||['calm','think'].indexOf(a.mood.expression)<0)||
    Object.keys(WORLD.bubbles).length;
  // at rest the only motion is scenery (water, drifting camera), so the light version
  // draws it at 5 frames a second: on software rendering a frame is a real cost
  const gap=lively?(WORLD.hq?.033:.066):(WORLD.hq?.083:.2);
  const dt=(now-WORLD.last)/1000;
  if(!WORLD.still&&dt<gap){WORLD.raf=requestAnimationFrame(worldFrame);return}
  WORLD.last=now;
  const t=(now-WORLD.t0)/1000;
  // light first: the kit's tick reads what light worked out for this hour
  WORLD.kit.light(worldDaylight());
  WORLD.kit.tick(t,WORLD.still?0:Math.min(dt,.1));
  worldAim(t);
  worldPose(t,Math.min(dt,.1));
  const t0=performance.now();
  WORLD.r.render(WORLD.scene,WORLD.cam);
  worldPace(performance.now()-t0);
  worldPlaceTags();
  if(!WORLD.still)WORLD.raf=requestAnimationFrame(worldFrame);
}
/* A slow machine (software rendering in a Linux session, a Pi) draws at a lower
   resolution rather than dropping to a slideshow: ten slow frames in a row halve the
   pixel ratio, down to a quarter. The Office's dpr step-down, for the same reason. */
function worldPace(ms){
  WORLD.slow=ms>40?(WORLD.slow||0)+1:0;
  if(WORLD.slow<10||!WORLD.r)return;
  WORLD.slow=0;
  const pr=WORLD.r.getPixelRatio();
  if(pr>.26){WORLD.r.setPixelRatio(pr/2);WORLD.r.setSize(innerWidth,innerHeight,false)}
}
/* A feeling is a pose, and most feelings have an effect over the head as well. Every
   EXPRESSION world.py lists has one here; calm and think are the quiet ones. */
var WORLD_FX={
  tantrum:[['puff',3.5,{dy:2.5,v:[0,1.6,0],grow:1.6,life:1.1,size:.8,jit:.5}],['paper',2.5,{dy:2.1,v:[2.6,2.8,1.2],g:6,spin:6,life:1.3,size:.5}]],
  slump:[['cloud',1.1,{dy:3.35,v:[.08,0,0],life:2.6,size:1.5,jit:.3}],['rain',7,{dy:3.05,v:[0,-2.6,0],life:.5,size:.55,jit:.8}]],
  doze:[['z',1,{dy:2.7,dx:.35,v:[.4,.6,0],grow:1,life:2.2,size:.5}]],
  cheer:[['star',4,{dy:2.3,v:[1.8,2.4,.6],g:3,spin:4,life:1.1,size:.5}]],
  sparkle:[['star',1.6,{dy:1.7,v:[0,.5,0],life:1.3,size:.42,jit:1}]],
  shiver:[['drop',.9,{dy:2.35,dx:.5,v:[.15,-.3,0],g:1.2,life:1,size:.4}]],
  wave:[['heart',1,{dy:2.6,v:[0,.8,0],grow:.4,life:1.8,size:.5,jit:.4}]],
  care:[['heart',1.4,{dy:2.6,v:[0,.8,0],grow:.4,life:1.8,size:.5,jit:.4}]],
  sulk:[['scribble',.9,{dy:3.1,v:[0,.1,0],life:1.6,size:.75,spin:1}]],
  pace:[['drop',.5,{dy:2.35,dx:-.45,v:[-.1,-.3,0],g:1.2,life:1,size:.36}]]};
function worldPose(t,dt){
  const T=WORLD.T;
  Object.values(WORLD.chars).forEach(c=>{
    const a=c.a;if(!a)return;
    const s=c.sprite,m=s.material,e=a.mood.expression,k=t+c.phase;
    let x=0,y=0,rot=0,frame=((k%4)<.12)?1:0,sy=1,flip=false;
    const target=a.busy?WORLD.kit.busy(c.i,t):c.home;
    if(e==='cheer'){y=Math.abs(Math.sin(k*6))*.5;frame=2+(Math.floor(k*4)%2)}
    else if(e==='tantrum'){y=Math.abs(Math.sin(k*14))*.25;x=Math.sin(k*40)*.08;rot=Math.sin(k*20)*.15}
    else if(e==='slump'){sy=.86;y=-.12}
    else if(e==='pace'){x=Math.sin(k*1.1)*1.1;flip=Math.cos(k*1.1)<0}
    else if(e==='sulk'){flip=true;y=-.18;rot=.08;sy=.9}
    else if(e==='doze'){rot=.18+Math.sin(k*.8)*.04;y=Math.sin(k*.8)*.03;frame=1}
    else if(e==='shiver'){x=Math.sin(k*55)*.04}
    else if(e==='sparkle'){y=Math.abs(Math.sin(k*2.2))*.18}
    else if(e==='wave'){frame=2+(Math.floor(k*3)%2)}
    else if(e==='care'){rot=c.home.x>0?.12:-.12;y=Math.sin(k*1.2)*.03}
    else if(e==='think'){rot=Math.sin(k*.8)*.07}
    else{y=Math.sin(k*1.5)*.03}
    if(WORLD.still){x=0;rot=0;y=Math.max(0,y)}
    s.position.lerp(target,a.busy?.08:.12);
    s.position.x+=x;s.position.y=target.y+y;
    m.rotation=rot;s.scale.y=2.45*sy;
    c.tex.offset.x=frame*.25;c.tex.repeat.x=flip?-.25:.25;if(flip)c.tex.offset.x=(frame+1)*.25;
    const ground=a.busy&&c.vessel?target.y+.25:target.y;
    c.shadow.position.set(s.position.x,ground+.04,s.position.z);c.shadow.visible=!(a.busy&&!c.vessel&&target.y>3);
    const cr=c.crystal;
    cr.position.set(s.position.x,s.position.y+s.scale.y+.55+(WORLD.still?0:Math.sin(k*2)*.06),s.position.z);
    cr.rotation.y=WORLD.still?.6:k*1.6;
    cr.material.emissiveIntensity=.45+(WORLD.still?0:Math.sin(k*3)*.12);
    if(c.vessel){c.vessel.position.set(s.position.x,a.busy?s.position.y-.35:-99,s.position.z)}
    // the feeling's effect: spawned at a rate, never faster than the frame allows
    (WORLD_FX[e]||[]).forEach(([kind,rate,o])=>{if(Math.random()<rate*dt)worldFx(kind,s.position,o)});
  });
  WORLD.fx=WORLD.fx.filter(p=>{p.life-=dt;
    p.m.position.addScaledVector(p.v,dt);p.v.y-=p.g*dt;p.m.material.rotation+=p.spin*dt;
    const f=p.life/p.max;p.m.material.opacity=Math.min(1,f*2.5);
    const sc=p.size*(1+(1-f)*p.grow);p.m.scale.set(sc,sc,1);
    if(p.life<=0){WORLD.scene.remove(p.m);p.m.material.dispose();return false}return true});
}
/* One effect: a painted sprite that rises, falls or drifts, and fades. Textures are
   painted once (wlFxTex) and shared, so an effect costs a material and nothing more. */
function worldFx(kind,at,o){
  if(WORLD.still||WORLD.fx.length>80||!WORLD.scene)return;
  const T=WORLD.T,j=o.jit||0;
  const m=new T.Sprite(new T.SpriteMaterial({map:wlFxTex(T,kind),transparent:true,depthWrite:false}));
  m.position.set(at.x+(o.dx||0)+(Math.random()-.5)*j,at.y+(o.dy||2.4)+(Math.random()-.5)*j*.4,at.z+.05);
  const v=o.v||[0,.6,0],side=Math.random()<.5?-1:1;
  WORLD.scene.add(m);
  WORLD.fx.push({m,v:new T.Vector3(v[0]*(o.g||o.spin?side*(.5+Math.random()*.7):1),v[1]*(.8+Math.random()*.4),v[2]*(Math.random()-.3)),
    g:o.g||0,spin:(o.spin||0)*side,life:o.life||1.5,max:o.life||1.5,size:o.size||.4,grow:o.grow||0});
}
/* Each tag is a button that spans the character, crystal to feet, with the name plate
   under the feet and a bubble above the crystal: tapping the person opens the card. */
function worldPlaceTags(){
  const box=WORLD.ui&&WORLD.ui.querySelector('.wd-tags');if(!box||!WORLD.cam)return;
  const T=WORLD.T,v=new T.Vector3();
  Object.entries(WORLD.chars).forEach(([name,c])=>{
    const el=box.querySelector(`[data-wa="${CSS.escape(name)}"]`);if(!el)return;
    // anchored where the agent stands, not where it hops or paces: a tag that jumps
    // with a cheer is a target a finger misses. A busy agent's tag goes with it.
    const at=c.a&&c.a.busy||!c.home?c.sprite.position:c.home;
    v.copy(at);v.project(WORLD.cam);
    const x=Math.round((v.x*.5+.5)*innerWidth),yf=Math.round((-v.y*.5+.5)*innerHeight),z=v.z;
    v.copy(at);v.y+=2.45+.85;v.project(WORLD.cam);
    const yh=Math.round((-v.y*.5+.5)*innerHeight),hgt=Math.max(0,yf-yh);
    const off=z>1||x<-60||x>innerWidth+60;
    if(el._x!==x||el._y!==yh||el._hg!==hgt){el.style.transform=`translate(${x}px,${yh}px) translateX(-50%)`;
      el.style.setProperty('--ch',hgt+'px');el._x=x;el._y=yh;el._hg=hgt}
    el.hidden=off;
  });
}

/* ---------------- what you can do in the world ---------------- */
function worldChip(){
  const box=WORLD.ui&&WORLD.ui.querySelector('.wd-chip');if(!box||!WORLD.v)return;
  const w=WORLD.v.world;
  box.innerHTML=`<button class="wd-chipb" onclick="worldMenu()" aria-expanded="${WORLD.menu}">
      <span class="wd-globe">🌍</span><b>${esc(w.name)}</b><span class="wd-exp">Experimental</span></button>
    ${WORLD.menu?worldMenuHTML():''}`;
}
function worldMenu(){WORLD.menu=!WORLD.menu;worldChip();if(WORLD.menu)worldListLoad()}
async function worldListLoad(){
  try{WORLD.list=(await (await fetch('/api/worlds')).json()).worlds||[]}catch(e){WORLD.list=[]}
  if(WORLD.menu)worldChip();
}
function worldMenuHTML(){
  const v=WORLD.v,list=WORLD.list||[];
  return `<div class="wd-menu" role="dialog" aria-label="World">
    <p class="wd-blurb">${esc(v.world.blurb||'')}</p>
    ${WORLD.why?`<p class="wd-why">${esc(WORLD.why)}</p>`:''}
    <div class="wd-h">Worlds</div>
    <div class="wd-worlds">${list.map(w=>`<div class="wd-wrow"><button class="wd-w${w.id===WORLD.id?' on':''}" onclick="worldGo('${esc(w.id)}')">
        <b>${esc(w.name)}</b><span>${esc(w.emotions.slice(0,6).map(e=>e.emoji).join(' '))}</span>
        <small>${esc(w.ladder.join(' → '))}</small></button>${w.builtin?'':
        /* your own worlds are deleted from their row: at the bottom of a long menu the
           button was below the fold, and reported as "I am not able to delete the world" */
        `<button class="wd-wdel" title="Delete ${esc(w.name)}" aria-label="Delete ${esc(w.name)}" data-id="${esc(w.id)}" data-name="${esc(w.name)}" onclick="worldDelete(this.dataset.id,this.dataset.name)">✕</button>`}</div>`).join('')||'<small>loading…</small>'}</div>
    <div class="wd-h">Design this scene</div>
    <div class="wd-build"><textarea id="wd-look" rows="2" placeholder="A snowy night with blue lanterns and no boats…">${esc(WORLD.lookWords||'')}</textarea>
      <button class="endbtn" onclick="worldLook(this)">Design it</button></div>
    <div class="wd-looked">${WORLD.lookOut||''}${WORLD.undoLook||(v.world.builtin&&v.world.scene_custom)?`<div class="wd-acts">
      ${WORLD.undoLook?'<button class="endbtn" onclick="worldLookUndo()">Undo</button>':''}
      ${v.world.builtin&&v.world.scene_custom?'<button class="endbtn" onclick="worldLookSet({original:true},\'Back to how it shipped\')">Original look</button>':''}</div>`:''}</div>
    <div class="wd-h">Build your own</div>
    <div class="wd-build"><textarea id="wd-desc" rows="2" placeholder="A night bakery where bread rises at 3am…"></textarea>
      <button class="endbtn" onclick="worldDesign(this)">Build it</button></div>
    <div class="wd-built"></div>
    <label class="wd-row"><input type="checkbox" ${v.inner?'checked':''} onchange="worldInner(this.checked)">
      <span>Agents feel it ${pInfoSafe('While this world is on, each agent is told how it feels and why, and your lead hears how you said you are. It changes their tone and approach, never the rules. Off, and outside this scene, nothing is told.')}</span></label>
    <div class="wd-acts">
      <button class="endbtn" onclick="worldAskAgain()">Ask me again</button>
      <button class="endbtn" onclick="worldReset()">Reset this world</button>
      ${list.find(w=>w.id===WORLD.id&&!w.builtin)?'<button class="endbtn" onclick="worldDelete()">Delete this world</button>':''}
      <button class="endbtn" onclick="setImmersiveScene('aurora')">Leave the world</button></div>
    <p class="wd-note">Feelings here come from what your agents really did. Leave this scene and all of it sleeps until you come back.</p>
  </div>`;
}
function pInfoSafe(t){return typeof pInfo==='function'?pInfo(t):''}
async function worldGo(id){
  if(!await worldEnter(id))return toast('could not open that world');
  WORLD.menu=false;WORLD.moods={};WORLD.bubbles={};WORLD.lookOut='';WORLD.undoLook=null;WORLD.lookWords='';await worldBuild();
}
async function worldPost(url,body,method){
  const r=await fetch(url,{method:method||'POST',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
  const d=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(d.error||'that did not work');
  return d;
}
async function worldInner(on){try{WORLD.v=await worldPost('/api/world/inner',{on});worldSync();
  toast(on?'Your agents feel it now, while this world is on':'Your agents no longer hear about feelings')}catch(e){toast(e.message)}}
async function worldAskAgain(){try{WORLD.v=await worldPost('/api/world/checkin',null,'DELETE');WORLD.menu=false;worldSync()}catch(e){toast(e.message)}}
async function worldReset(){
  if(!confirm('Reset '+WORLD.v.world.name+'? Every feeling, friendship and step of growth here goes back to the start.'))return;
  try{WORLD.v=await worldPost('/api/world/reset',{world:WORLD.id});WORLD.moods={};worldSync();toast('The world starts fresh')}catch(e){toast(e.message)}
}
async function worldDelete(id,name){
  id=id||WORLD.id;name=name||(WORLD.v&&WORLD.v.world.name)||id;
  if(!confirm('Delete '+name+'? The world and everything that happened in it are removed.'))return;
  try{
    await worldPost('/api/world/'+encodeURIComponent(id),null,'DELETE');
    toast('Deleted '+name);
    if(id===WORLD.id)await worldGo('lantern-canal');
    else{await worldListLoad()}
  }catch(e){toast(e.message)}
}
async function worldDesign(btn){
  const box=document.getElementById('wd-desc');const words=(box&&box.value||'').trim();
  if(words.length<3)return toast('describe your world first, a few words is enough');
  btn.disabled=true;btn.textContent='Building…';
  try{
    const d=await worldPost('/api/world/design',{description:words});
    const out=WORLD.ui.querySelector('.wd-built');
    if(out)out.innerHTML=`<p><b>${esc(d.world.name)}</b> is ready: ${esc(d.world.emotions.map(e=>e.emoji+' '+e.name).join(', '))}.</p>`+
      (d.said?`<p class="wd-why">${esc(d.said)}</p>`:'')+(d.dropped&&d.dropped.length?`<p class="wd-why">Left out: ${esc(d.dropped.join('; '))}.</p>`:'');
    setTimeout(()=>worldGo(d.world.id),1400);
  }catch(e){toast(e.message)}
  finally{btn.disabled=false;btn.textContent='Build it'}
}
/* The look is designed by the AI from a description, and only that way: there is no
   field-by-field picker, on purpose. Undo puts back the look it had before. */
async function worldLook(btn){
  const box=document.getElementById('wd-look');const words=(box&&box.value||'').trim();
  if(words.length<3)return toast('describe how it should look, a few words is enough');
  WORLD.lookWords=words;
  btn.disabled=true;btn.textContent='Designing…';
  try{
    const d=await worldPost('/api/world/scene',{world:WORLD.id,description:words});
    WORLD.undoLook={prev:d.previous};
    const sc=d.world.scene||{};
    WORLD.lookOut=`<p>${d.how==='brain'?'Designed by AI'+(d.who?' ('+esc(d.who)+')':''):'Designed from your words'}: `+
      esc([sc.time==='live'?'the real hour':sc.time,sc.weather,sc.sky!=='natural'?sc.sky+' sky':'',sc.water+' water',sc.accent+' lights'].filter(Boolean).join(', '))+'.</p>'+
      (d.said?`<p class="wd-why">${esc(d.said)}</p>`:'')+
      (d.dropped&&d.dropped.length?`<p class="wd-why">Left out: ${esc(d.dropped.join('; '))}.</p>`:'');
    await worldLookApply(d);
  }catch(e){toast(e.message)}
  finally{btn.disabled=false;btn.textContent='Design it'}
}
async function worldLookApply(d){
  if(d.state&&d.state.live)WORLD.v=d.state;
  await worldBuild();worldListLoad();
}
async function worldLookSet(body,msg){
  try{const d=await worldPost('/api/world/scene',Object.assign({world:WORLD.id},body));
    WORLD.lookOut='';WORLD.undoLook=null;await worldLookApply(d);toast(msg)}catch(e){toast(e.message)}
}
function worldLookUndo(){
  const u=WORLD.undoLook;if(!u)return;
  worldLookSet(u.prev?{scene:u.prev}:{original:true},'The scene is back how it was');
}
/* An agent's card: the feeling, every real cause, how far it has grown, who it works
   with, and one thing you can do: a pat on the back. */
function worldCard(name,quiet){
  const card=WORLD.ui&&WORLD.ui.querySelector('.wd-card');if(!card)return;
  const a=worldCast().find(x=>x.name===name);
  if(!a){card.hidden=true;WORLD.open='';return}
  if(!quiet&&WORLD.open===name&&!card.hidden){card.hidden=true;WORLD.open='';return}
  WORLD.open=name;const m=a.mood,l=a.level;
  const ago=s=>s<60?'just now':s<3600?Math.round(s/60)+' min ago':Math.round(s/3600)+' h ago';
  card.hidden=false;card.style.setProperty('--mh',m.hue);
  card.innerHTML=`<button class="wd-x" onclick="worldCard('${esc(name)}')" aria-label="Close">✕</button>
    <div class="wd-who">${avatarImg(name,'wd-face')}<div><b>${esc(worldLabel(name))}</b>
      <div class="wd-feel">${esc(m.emoji)} ${esc(m.name)}${a.busy?' · at work':''}</div></div></div>
    ${a.why.length?`<div class="wd-h">Because</div><ul class="wd-because">${a.why.map(w=>
      `<li>${esc(w.words)}${w.detail?` <code>${esc(w.detail)}</code>`:''} <small>${ago(w.ago)}</small></li>`).join('')}</ul>`:
      `<p class="wd-quiet">Nothing has happened to ${esc(worldLabel(name))} here yet.</p>`}
    ${m.under&&m.under.length?`<p class="wd-under">Also: ${m.under.map(u=>esc(u.emoji+' '+u.name)).join(', ')}</p>`:''}
    <div class="wd-grow"><span>${esc(l.name)}</span>${l.next?`<i style="--p:${Math.max(4,100-l.to_next/(l.to_next+l.xp||1)*100)}%"></i><small>${l.to_next} to ${esc(l.next)}</small>`:'<small>top of the ladder</small>'}</div>
    ${a.friend?`<p class="wd-friend">Works best with ${esc(worldLabel(a.friend))}</p>`:''}
    <button class="endbtn wd-pat" onclick="worldPat('${esc(name)}')">Pat on the back</button>`;
}
async function worldPat(name){
  try{WORLD.v=await worldPost('/api/world/pat',{agent:name});worldSync();
    const a=worldCast().find(x=>x.name===name);if(a)worldSay(a)}catch(e){toast(e.message)}
}
/* The lead asks how you are, once a day in each world. Your answer stays in this
   world; your agents only get gentler for it. */
function worldAsk(){
  const box=WORLD.ui&&WORLD.ui.querySelector('.wd-ask');if(!box||!WORLD.v)return;
  const v=WORLD.v,you=v.you||{};
  if(!v.ask_you&&!(you.reply&&!box._seen)){box.hidden=true;return}
  const c=v.world.checkin||{},lead=worldLabel('@agent');
  box.hidden=false;
  if(!v.ask_you&&you.reply){
    box.innerHTML=`<div class="wd-who">${avatarImg('@agent','wd-face')}<div><b>${esc(lead)}</b>
      <p class="wd-reply">${esc(you.reply)}</p>${you.how==='words'?'<small>No brain answered, so this is the world\'s own reply.</small>':''}</div></div>`;
    box._seen=true;clearTimeout(box._t);box._t=setTimeout(()=>{box.hidden=true},9000);return;
  }
  if(WORLD.busyAsk)return;
  box.innerHTML=`<div class="wd-who">${avatarImg('@agent','wd-face')}<div><b>${esc(lead)}</b>
      <p class="wd-q">${esc(c.question||'How are you feeling today?')}</p></div></div>
    <div class="wd-choices">${(c.choices||[]).map(ch=>`<button class="wd-ch" onclick="worldAnswer('${esc(ch.id)}')"><span>${esc(ch.emoji)}</span>${esc(ch.label)}</button>`).join('')}</div>
    <input id="wd-words" maxlength="280" placeholder="In a few words, if you like">
    <div class="wd-acts"><button class="endbtn wd-skip" onclick="worldAnswer('',true)">Not today</button>
      <small>Only this world keeps it.</small></div>`;
}
async function worldAnswer(choice,skip){
  const box=WORLD.ui.querySelector('.wd-ask');const words=(document.getElementById('wd-words')||{}).value||'';
  WORLD.busyAsk=true;
  if(!skip)box.innerHTML=`<div class="wd-who">${avatarImg('@agent','wd-face')}<div><b>${esc(worldLabel('@agent'))}</b><p class="wd-q">…</p></div></div>`;
  try{WORLD.v=await worldPost('/api/world/checkin',{choice,words,skip:!!skip});box._seen=false}
  catch(e){toast(e.message)}
  WORLD.busyAsk=false;
  if(skip){box.hidden=true;box._seen=true}
  worldSync();
}
/* 01e loads after 01b: at first paint applyImmersive ran before WORLD existed, so the
   scene starts itself here once, and from then on the switch is handled there. */
if(typeof IMMERSIVE!=='undefined'&&IMMERSIVE.on&&IMMERSIVE.scene==='world')setTimeout(worldStart,0);
