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
  }catch(e){WORLD.flat=true;WORLD.r=null;
    WORLD.why='This screen has no 3D graphics, so the world is drawn flat.'}
  WORLD.host.classList.toggle('flat',WORLD.flat);
  WORLD.host.dataset.kit=WORLD.v.world.kit;
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
function worldDispose(){
  cancelAnimationFrame(WORLD.raf);WORLD.raf=0;
  if(WORLD.scene)WORLD.scene.traverse(o=>{if(o.geometry)o.geometry.dispose();
    const m=o.material;if(m){(Array.isArray(m)?m:[m]).forEach(x=>{if(x.map)x.map.dispose();x.dispose()})}});
  if(WORLD.r){try{WORLD.r.dispose();WORLD.r.forceContextLoss()}catch(e){}}
  WORLD.r=null;WORLD.scene=null;WORLD.kit=null;WORLD.chars={};WORLD.camWide=null;
  if(WORLD.ui){const t=WORLD.ui.querySelector('.wd-tags');if(t)t.innerHTML=''}
}
function worldResize(){
  if(!WORLD.r||!WORLD.cam)return;
  WORLD.r.setSize(innerWidth,innerHeight,false);
  WORLD.cam.aspect=innerWidth/innerHeight;
  // a tall phone screen: a wider lens, and the camera looks down on the quay so the
  // team's two rows sit above the cards instead of under them
  const tall=innerWidth<innerHeight;
  WORLD.cam.fov=tall?58:42;
  if(!WORLD.camWide)WORLD.camWide={p:WORLD.cam.position.clone(),q:WORLD.cam.quaternion.clone()};
  if(tall){WORLD.cam.position.set(0,12,31);WORLD.cam.lookAt(0,-1.5,4)}
  else{WORLD.cam.position.copy(WORLD.camWide.p);WORLD.cam.quaternion.copy(WORLD.camWide.q)}
  WORLD.cam.updateProjectionMatrix();
  Object.values(WORLD.chars).forEach(c=>{if(WORLD.kit)c.home=WORLD.kit.stand(c.i,worldCast().length)});
  worldKick();
}
/* The real hour decides the light: 0 at midnight, 1 at noon. */
function worldDaylight(){
  const d=new Date(),h=d.getHours()+d.getMinutes()/60;
  return Math.max(0,Math.sin((h-6)/12*Math.PI));
}
function worldMix(T,a,b,t){return new T.Color(a).lerp(new T.Color(b),Math.max(0,Math.min(1,t)))}
function worldBox(T,w,h,d,color,o){
  const m=new T.Mesh(new T.BoxGeometry(w,h,d),new T.MeshStandardMaterial(Object.assign({color,roughness:.85},o||{})));
  return m;
}
/* A sky that fades from the horizon to the zenith, recoloured with the hour. */
function worldSky(T,scene){
  const g=new T.SphereGeometry(260,32,16),n=g.attributes.position.count,col=new Float32Array(n*3);
  g.setAttribute('color',new T.BufferAttribute(col,3));
  const m=new T.Mesh(g,new T.MeshBasicMaterial({vertexColors:true,side:T.BackSide,fog:false,depthWrite:false}));
  scene.add(m);
  return {paint(horizon,zenith){const h=new T.Color(horizon),z=new T.Color(zenith),c=new T.Color();
    const p=g.attributes.position.array;
    for(let i=0;i<n;i++){const t=Math.max(0,Math.min(1,p[i*3+1]/140));c.copy(h).lerp(z,Math.pow(t,.6));
      col[i*3]=c.r;col[i*3+1]=c.g;col[i*3+2]=c.b}
    g.attributes.color.needsUpdate=true}};
}
function worldHills(T,scene,z,color,n){
  const m=new T.MeshStandardMaterial({color,flatShading:true,roughness:1});
  for(let i=0;i<n;i++){const h=18+((i*37)%11)*2.2,r=16+((i*23)%7)*3;
    const c=new T.Mesh(new T.ConeGeometry(r,h,6,1),m);c.position.set(-150+i*(300/(n-1))+((i*17)%9),h/2-2,z-((i*13)%5)*6);scene.add(c)}
  return m;
}
/* Where the team stands: one row across a wide screen, rows of four on a tall one (a
   phone), nearer rows closer to the camera so nobody hides behind a colleague. */
function worldStand(T,i,n,y,z){
  const tall=innerWidth<innerHeight,per=tall?4:n,rows=Math.ceil(n/per);
  const row=Math.floor(i/per),col=i%per,inRow=row<rows-1?per:n-per*(rows-1);
  const span=tall?Math.min(7.6,inRow*2.2):Math.min(21,inRow*2.9);
  return new T.Vector3(-span/2+span*(inRow>1?col/(inRow-1):.5),y,z+row*3.6);
}
function worldStars(T,scene,n,r){
  const g=new T.BufferGeometry(),p=new Float32Array(n*3);
  for(let i=0;i<n;i++){const th=Math.random()*Math.PI*2,ph=Math.random()*Math.PI*.48;
    p[i*3]=r*Math.cos(th)*Math.cos(ph);p[i*3+1]=r*Math.sin(ph)+4;p[i*3+2]=-Math.abs(r*Math.sin(th)*Math.cos(ph))}
  g.setAttribute('position',new T.BufferAttribute(p,3));
  const m=new T.PointsMaterial({color:0xffffff,size:.6,sizeAttenuation:true,transparent:true,opacity:0});
  const pts=new T.Points(g,m);scene.add(pts);return pts;
}
/* Each kit draws a place and says where people stand, where busy people go, and how
   the light moves. They are deliberately unlike each other: the world IS the setting. */
var WORLD_KITS={
  canal(T,scene,cam){
    cam.position.set(0,6.4,29);cam.lookAt(0,4.6,-6);
    const sky=worldSky(T,scene);
    const hemi=new T.HemisphereLight(0xdfefff,0x3a5a40,.9);scene.add(hemi);
    const sun=new T.DirectionalLight(0xffffff,1.6);sun.position.set(-20,30,10);scene.add(sun);
    const stars=worldStars(T,scene,500,150);
    const hills=worldHills(T,scene,-95,0x40614f,9);
    // water: a wide plane whose vertices ripple, between the two quays
    const wg=new T.PlaneGeometry(140,17,90,16);wg.rotateX(-Math.PI/2);
    const water=new T.Mesh(wg,new T.MeshStandardMaterial({color:0x1fa39a,roughness:.12,metalness:.35,emissive:0x0a3a44,emissiveIntensity:0}));
    water.position.set(0,0,-.5);scene.add(water);
    const base=wg.attributes.position.array.slice();
    const stone=0x8d8a82,grass=0x6d9b57;
    const far=worldBox(T,140,1.8,3,stone);far.position.set(0,.3,-10.5);scene.add(far);
    const farLawn=worldBox(T,140,.3,16,grass);farLawn.position.set(0,1.25,-19.5);scene.add(farLawn);
    const near=worldBox(T,140,1.8,3,stone);near.position.set(0,.3,9.5);scene.add(near);
    const path=worldBox(T,140,.3,12,0xb9a88a);path.position.set(0,1.25,17);scene.add(path);
    // the far bank's houses: cream walls, dark roofs, windows that light at night
    const wins=[];const roofM=new T.MeshStandardMaterial({color:0x2f3640,roughness:.7});
    for(let i=-11;i<=11;i++){
      const w=3+(i*7%3+3)%3*.6,h=2.4+((i*5)%4+4)%4*.5,x=i*5.2+((i*13)%3);
      const house=worldBox(T,w,h,3.2,i%3?0xf1e6cf:0x6b4f3a);house.position.set(x,1.4+h/2,-15.5);scene.add(house);
      const roof=new T.Mesh(new T.ConeGeometry(w*.78,1.5,4,1),roofM);roof.rotation.y=Math.PI/4;
      roof.scale.set(1,1,.7);roof.position.set(x,1.4+h+.72,-15.5);scene.add(roof);
      const wm=new T.MeshStandardMaterial({color:0x332b22,emissive:0xffb347,emissiveIntensity:0});
      const win=new T.Mesh(new T.PlaneGeometry(.8,.7),wm);win.position.set(x,1.4+h*.55,-13.88);scene.add(win);wins.push(wm);
    }
    // the red bridge
    const bridge=new T.Mesh(new T.TorusGeometry(9.5,.45,8,40,Math.PI),new T.MeshStandardMaterial({color:0xc0392b,roughness:.5}));
    bridge.position.set(24,-4.6,-.5);bridge.rotation.y=Math.PI/2;bridge.scale.set(1,.72,1);scene.add(bridge);
    const deck=worldBox(T,2.2,.25,24,0xa93226);deck.position.set(24,2.2,-.5);scene.add(deck);
    // lanterns on poles along the water's edge, behind the people
    const lanterns=[];
    for(let i=-6;i<=6;i++){
      const c=i%2?0xe74c3c:0xf39c12;
      const lm=new T.MeshStandardMaterial({color:c,emissive:c,emissiveIntensity:.2});
      const l=new T.Mesh(new T.SphereGeometry(.16,10,8),lm);l.scale.y=1.3;l.position.set(i*5.6+2.8,3.6,8.4);scene.add(l);lanterns.push(lm);
      const pole=worldBox(T,.06,2.5,.06,0x4a3b2a);pole.position.set(i*5.6+2.8,2.35,8.4);scene.add(pole);
    }
    const glows=[-14,0,14].map(x=>{const g=new T.PointLight(0xffa94d,0,26,1.6);g.position.set(x,4.2,7.5);scene.add(g);return g});
    // two boats moored at the far quay: scenery, like the houses; they do not move
    function boat(){
      const g=new T.Group();
      const hull=worldBox(T,2.8,.5,1.1,0x8b5a2b);hull.position.y=.1;g.add(hull);
      const rim=worldBox(T,2.9,.12,1.2,0xc0392b);rim.position.y=.38;g.add(rim);
      const roof=new T.Mesh(new T.CylinderGeometry(.6,.6,1.4,10,1,true,0,Math.PI),new T.MeshStandardMaterial({color:0xc8a96a,side:T.DoubleSide,roughness:.9}));
      roof.rotation.z=Math.PI/2;roof.position.set(-.5,.5,0);g.add(roof);
      scene.add(g);return g;
    }
    [[-19,-8],[11,-8.2]].forEach(([x,z])=>{const b=boat();b.position.set(x,.2,z)});
    return {
      stand(i,n){return worldStand(T,i,n,1.2,10.6)},
      // busy agents take a boat out on the water
      busy(i,t){return new T.Vector3(((t*.6+i*9)%64)-32,.3+Math.sin(t*1.3+i)*.08,-3.5+(i%3)*2.8)},
      vessel(){return boat()},
      tick(t){
        const p=wg.attributes.position.array;
        for(let i=0;i<p.length;i+=3){const x=base[i],z=base[i+2];
          p[i+1]=Math.sin(x*.35+t*1.1)*.12+Math.cos(z*.9+t*.8)*.08}
        wg.attributes.position.needsUpdate=true;
        if((WORLD.waterT=(WORLD.waterT||0)+1)%3===0)wg.computeVertexNormals();
      },
      light(day){
        const dusk=day<.35;
        sky.paint(worldMix(T,0x1a2447,dusk?0xf6a57a:0xcfe8ff,day*2.2),worldMix(T,0x05081a,0x5aa8f0,day*1.5));
        scene.fog=new T.Fog(worldMix(T,0x10183a,dusk?0xe9b58f:0xcfe8ff,day*2),70,230);
        sun.intensity=.12+day*1.6;hemi.intensity=.35+day*.65;
        stars.material.opacity=Math.max(0,.9-day*3);
        const night=1-Math.min(1,day*2.5);
        lanterns.forEach(m=>m.emissiveIntensity=.25+night*2.2);wins.forEach(m=>m.emissiveIntensity=night*1.6);
        glows.forEach(g=>g.intensity=night*22);
        water.material.color=worldMix(T,0x1b5f6e,0x1fa39a,day*1.4);
        water.material.emissiveIntensity=night*.5;
        hills.color=worldMix(T,0x1c2b34,0x40614f,day*1.5);
      }};
  },
  orbit(T,scene,cam){
    cam.position.set(0,6.8,31);cam.lookAt(0,4.8,-8);
    scene.background=new T.Color(0x03040b);
    const amb=new T.AmbientLight(0x8899ff,.35);scene.add(amb);
    const sun=new T.DirectionalLight(0xffffff,2);sun.position.set(40,20,10);scene.add(sun);
    const stars=worldStars(T,scene,1400,160);stars.material.opacity=1;
    const planet=new T.Mesh(new T.SphereGeometry(42,48,32),new T.MeshStandardMaterial({color:0x2e6fd8,roughness:.9}));
    planet.position.set(-30,-44,-70);scene.add(planet);
    const air=new T.Mesh(new T.SphereGeometry(43.6,48,32),new T.MeshBasicMaterial({color:0x6fb7ff,transparent:true,opacity:.18,side:T.BackSide}));
    air.position.copy(planet.position);scene.add(air);
    const ring=new T.Group();ring.position.set(12,9,-38);scene.add(ring);
    const rim=new T.Mesh(new T.TorusGeometry(14,1.2,12,64),new T.MeshStandardMaterial({color:0xcfd6e6,metalness:.6,roughness:.35}));ring.add(rim);
    for(let i=0;i<6;i++){const s=worldBox(T,.5,28,.5,0x9aa4b8,{metalness:.5});s.rotation.z=i*Math.PI/6;ring.add(s)}
    const hub=new T.Mesh(new T.CylinderGeometry(2.4,2.4,4,20),new T.MeshStandardMaterial({color:0xe8ecf4,metalness:.5,roughness:.3}));hub.rotation.x=Math.PI/2;ring.add(hub);
    ring.rotation.x=.35;
    // the observation deck the crew stands on, with a glowing rail
    const deck=worldBox(T,40,.6,9,0x5d6778,{metalness:.4,roughness:.5});deck.position.set(0,.8,9.5);scene.add(deck);
    const railM=new T.MeshStandardMaterial({color:0x2de2e6,emissive:0x2de2e6,emissiveIntensity:.8});
    const rail=new T.Mesh(new T.BoxGeometry(40,.12,.12),railM);rail.position.set(0,2.6,5.2);scene.add(rail);
    const panels=[];
    for(let i=-4;i<=4;i++){const pm=new T.MeshStandardMaterial({color:0x10141f,emissive:0x3a86ff,emissiveIntensity:.5});
      const p=new T.Mesh(new T.BoxGeometry(2.2,1.2,.3),pm);p.position.set(i*4.4+2.2,1.8,6.4);p.rotation.x=-.25;scene.add(p);panels.push(pm)}
    const pods=[];
    return {
      stand(i,n){return worldStand(T,i,n,1.1,10)},
      // busy crew fly a pod around the station
      busy(i,t){const a=t*.35+i*1.3;return new T.Vector3(12+Math.cos(a)*18,9+Math.sin(a*1.3)*3,-38+Math.sin(a)*18+22)},
      vessel(){const g=new T.Group();
        const body=new T.Mesh(new T.SphereGeometry(.9,16,12),new T.MeshStandardMaterial({color:0xf5f7fb,metalness:.4,roughness:.3}));body.scale.set(1.4,.8,1);g.add(body);
        const jet=new T.Mesh(new T.ConeGeometry(.35,.9,10),new T.MeshBasicMaterial({color:0x7df9ff}));jet.rotation.z=Math.PI/2;jet.position.x=-1.5;g.add(jet);
        scene.add(g);pods.push(g);return g},
      tick(t){ring.rotation.z=t*.05;planet.rotation.y=t*.01;panels.forEach((m,i)=>m.emissiveIntensity=.35+Math.sin(t*2+i)*.15)},
      light(day){sun.position.set(Math.cos(day*Math.PI)*40,20,10);amb.intensity=.3+day*.25}};
  },
  garden(T,scene,cam){
    cam.position.set(0,6.6,30);cam.lookAt(0,4.2,-6);
    const hemi=new T.HemisphereLight(0xfff8e1,0x355e3b,1);scene.add(hemi);
    const sun=new T.DirectionalLight(0xfff1c1,1.6);sun.position.set(-15,30,12);scene.add(sun);
    const stars=worldStars(T,scene,500,150);
    const gg=new T.PlaneGeometry(140,70,70,35);gg.rotateX(-Math.PI/2);
    const gp=gg.attributes.position.array;
    for(let i=0;i<gp.length;i+=3){const x=gp[i],z=gp[i+2];gp[i+1]=Math.sin(x*.12)*.8+Math.cos(z*.2)*.6-(z<-10?0:1.2)*0+(z<-14?Math.sin(x*.08)*2+2:0)}
    gg.computeVertexNormals();
    const ground=new T.Mesh(gg,new T.MeshStandardMaterial({color:0x6aa84f,roughness:1}));ground.position.y=0;scene.add(ground);
    const pond=new T.Mesh(new T.CircleGeometry(6,40),new T.MeshStandardMaterial({color:0x3fa7d6,roughness:.15,metalness:.2}));
    pond.rotation.x=-Math.PI/2;pond.position.set(-12,.35,-3);pond.scale.set(1.4,1,1);scene.add(pond);
    const trees=[];
    [[-26,-12],[-18,-18],[18,-15],[27,-8],[8,-22],[-6,-20],[32,-20]].forEach(([x,z],i)=>{
      const trunk=worldBox(T,.6,3,.6,0x6b4423);trunk.position.set(x,1.8,z);scene.add(trunk);
      const top=new T.Mesh(new T.IcosahedronGeometry(2.4+(i%3)*.5,0),new T.MeshStandardMaterial({color:i%2?0x3f7d3a:0x4f9a45,flatShading:true}));
      top.position.set(x,4.4+(i%3)*.4,z);scene.add(top);trees.push(top)});
    // flowers: the garden grows with the team. More of the ladder climbed, more blooms.
    const flowers=new T.Group();scene.add(flowers);
    const petals=[0xf368e0,0xffd32a,0xff6b6b,0xffffff,0x9b59b6,0xff9f43];
    let shown=-1;
    const fireflies=worldStars(T,scene,60,18);fireflies.position.set(0,-2,6);fireflies.material.color=new T.Color(0xfff275);fireflies.material.size=.35;
    return {
      stand(i,n){return worldStand(T,i,n,.4,10)},
      // busy gardeners go and tend the beds
      busy(i,t){return new T.Vector3(-14+(i%5)*7+Math.sin(t*.5+i)*1.5,.4,1-(i%2)*4)},
      vessel(){return null},
      grow(total){const n=Math.min(160,8+Math.floor(total/2));if(n===shown)return;shown=n;
        while(flowers.children.length)flowers.remove(flowers.children[0]);
        for(let k=0;k<n;k++){const a=k*2.399,r=4+Math.sqrt(k)*2.2,x=Math.cos(a)*r*1.6,z=-4+Math.sin(a)*r*.7;
          if(z>7)continue;
          const f=new T.Mesh(new T.SphereGeometry(.22,6,5),new T.MeshStandardMaterial({color:petals[k%petals.length],roughness:.6}));
          f.position.set(x,.6+Math.random()*.3,z);flowers.add(f)}},
      tick(t){trees.forEach((tr,i)=>tr.rotation.y=Math.sin(t*.3+i)*.05)},
      light(day){
        scene.background=worldMix(T,0x0d1b2a,day>.35?0xbfe6ff:0xffc8a2,day*1.6);
        scene.fog=new T.Fog(scene.background,60,170);
        sun.intensity=.12+day*1.6;hemi.intensity=.25+day*.8;
        stars.material.opacity=Math.max(0,.9-day*3);
        fireflies.material.opacity=Math.max(0,.9-day*3);
      }};
  }
};

/* ---------------- the people ---------------- */
function worldCast(){return (WORLD.v&&WORLD.v.agents)||[]}
function worldSync(){
  if(!WORLD.on||!WORLD.v)return;
  worldChip();worldAsk();
  const cast=worldCast();
  if(!WORLD.flat&&WORLD.scene){
    const T=WORLD.T;
    const keep=new Set(cast.map(a=>a.name));
    Object.keys(WORLD.chars).forEach(n=>{if(!keep.has(n)){const c=WORLD.chars[n];WORLD.scene.remove(c.sprite);if(c.vessel)WORLD.scene.remove(c.vessel);delete WORLD.chars[n]}});
    cast.forEach((a,i)=>{
      let c=WORLD.chars[a.name];
      if(!c){
        const tex=new T.TextureLoader().load(avatarSrc(a.name,{sheet:1}),()=>worldKick());
        tex.magFilter=T.NearestFilter;tex.minFilter=T.NearestFilter;tex.colorSpace=T.SRGBColorSpace;
        tex.repeat.set(.25,1);
        const sp=new T.Sprite(new T.SpriteMaterial({map:tex,transparent:true}));
        sp.scale.set(1.2,1.95,1);sp.center.set(.5,0);
        WORLD.scene.add(sp);
        // everyone starts at their place: walking in from the middle of the world
        // took seconds on software rendering, and read as the team wandering
        sp.position.copy(WORLD.kit.stand(i,cast.length));
        c=WORLD.chars[a.name]={sprite:sp,tex,i,vessel:null,home:null,phase:Math.random()*6};
      }
      c.i=i;c.a=a;c.home=WORLD.kit.stand(i,cast.length);
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
  const gap=lively?.033:.083;
  const dt=(now-WORLD.last)/1000;
  if(!WORLD.still&&dt<gap){WORLD.raf=requestAnimationFrame(worldFrame);return}
  WORLD.last=now;
  const t=(now-WORLD.t0)/1000;
  WORLD.kit.light(worldDaylight());
  if(!WORLD.still)WORLD.kit.tick(t,dt);
  worldPose(t);
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
/* A feeling is a pose. Every EXPRESSION world.py lists has one here. */
function worldPose(t){
  Object.values(WORLD.chars).forEach(c=>{
    const a=c.a;if(!a)return;
    const s=c.sprite,m=s.material,e=a.mood.expression,k=t+c.phase;
    let x=0,y=0,rot=0,frame=((k%4)<.12)?1:0,sy=1,flip=false;
    const target=a.busy?WORLD.kit.busy(c.i,t):c.home;
    if(e==='cheer'){y=Math.abs(Math.sin(k*6))*.5;frame=2+(Math.floor(k*4)%2)}
    else if(e==='tantrum'){y=Math.abs(Math.sin(k*14))*.25;x=Math.sin(k*40)*.08;rot=Math.sin(k*20)*.15;
      if(!WORLD.still&&Math.random()<.08)worldPaper(s.position)}
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
    if(WORLD.still){x=0;rot=0}
    s.position.lerp(target,a.busy?.08:.12);
    s.position.x+=x;s.position.y=target.y+y;
    m.rotation=rot;s.scale.y=1.95*sy;
    c.tex.offset.x=frame*.25;c.tex.repeat.x=flip?-.25:.25;if(flip)c.tex.offset.x=(frame+1)*.25;
    if(c.vessel){c.vessel.position.set(s.position.x,a.busy?s.position.y-.35:-99,s.position.z)}
  });
  WORLD.fx=WORLD.fx.filter(p=>{p.life-=.033;p.m.position.addScaledVector(p.v,.033);p.v.y-=.2;p.m.rotation.z+=.2;
    if(p.life<=0){WORLD.scene.remove(p.m);p.m.geometry.dispose();p.m.material.dispose();return false}return true});
}
function worldPaper(at){
  if(WORLD.fx.length>40)return;
  const T=WORLD.T;
  const m=new T.Mesh(new T.PlaneGeometry(.3,.38),new T.MeshBasicMaterial({color:0xffffff,side:T.DoubleSide}));
  m.position.set(at.x,at.y+1.8,at.z);WORLD.scene.add(m);
  WORLD.fx.push({m,v:new T.Vector3((Math.random()-.5)*3,2+Math.random()*2,(Math.random()-.5)*1.5),life:1.2});
}
function worldPlaceTags(){
  const box=WORLD.ui&&WORLD.ui.querySelector('.wd-tags');if(!box||!WORLD.cam)return;
  const T=WORLD.T,v=new T.Vector3();
  Object.entries(WORLD.chars).forEach(([name,c])=>{
    const el=box.querySelector(`[data-wa="${CSS.escape(name)}"]`);if(!el)return;
    v.copy(c.sprite.position);v.y+=c.sprite.scale.y+.15;v.project(WORLD.cam);
    const x=Math.round((v.x*.5+.5)*innerWidth),y=Math.round((-v.y*.5+.5)*innerHeight);
    const off=v.z>1||x<-60||x>innerWidth+60;
    if(el._x!==x||el._y!==y){el.style.transform=`translate(${x}px,${y}px) translate(-50%,-100%)`;el._x=x;el._y=y}
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
    <div class="wd-worlds">${list.map(w=>`<button class="wd-w${w.id===WORLD.id?' on':''}" onclick="worldGo('${esc(w.id)}')">
        <b>${esc(w.name)}</b><span>${esc(w.emotions.slice(0,6).map(e=>e.emoji).join(' '))}</span>
        <small>${esc(w.ladder.join(' → '))}</small></button>`).join('')||'<small>loading…</small>'}</div>
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
  WORLD.menu=false;WORLD.moods={};WORLD.bubbles={};await worldBuild();
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
async function worldDelete(){
  if(!confirm('Delete '+WORLD.v.world.name+'? The world and everything that happened in it are removed.'))return;
  try{await worldPost('/api/world/'+encodeURIComponent(WORLD.id),null,'DELETE');await worldGo('lantern-canal');toast('World deleted')}catch(e){toast(e.message)}
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
