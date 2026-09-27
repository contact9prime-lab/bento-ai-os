/* ================= the World scene: how it looks (01f) =================
   The places, the light and the moods drawn on the people. 01e owns the lease, the
   state and the cards; this file owns everything the eye sees, so a new world kit is
   an entry in WORLD_KITS and nothing else.

   The first cut was boxes on a flat plane, a row of sprites and a solid-colour sky;
   the owner's word was "blah". What carries it now, all written here, nothing fetched:
   - a water SHADER: waves, sky reflection by Fresnel, sun glints, and at night every
     lantern's light streaking across the water toward you;
   - a sky SHADER: a gradient that follows the real hour, the sun and its glow, the
     moon, twinkling stars and slow clouds;
   - places with props that say where you are (a canal town with machiya houses, a
     vermilion bridge, a pagoda, willows and cherry trees; a ring station over a
     planet; a garden with a pond, stone lanterns and flowers);
   - light that glows: halos on every lamp and window, bloom-free and cheap;
   - people who stand somewhere, not in a line: each has a spot, a soft shadow, and
     a mood crystal over the head, green to red by how the feeling sits, spinning.
     And each feeling has its own effect: steam for a tantrum, a rain cloud for
     gloom, Zs for dozing, hearts, sparkles, a sweat drop.
   Quality: shadows and the petal/firefly counts follow WORLD.hq, decided once per
   build from the renderer (software rendering and phones get the light version).
   Every effect is caused by a feeling the server worked out; nothing here invents
   one. */

/* ---------------- shared pieces ---------------- */
function worldDaylight(){
  const d=new Date(),h=d.getHours()+d.getMinutes()/60;
  return Math.max(0,Math.sin((h-6)/12*Math.PI));
}
/* the sun's direction for the hour: east in the morning, high at noon, set by 18:00 */
function worldSunDir(T){
  const d=new Date(),h=d.getHours()+d.getMinutes()/60,a=(h-6)/12*Math.PI;
  // a little toward the viewer, so the town's fronts are lit rather than silhouetted
  return new T.Vector3(-Math.cos(a)*.8,Math.max(-.2,Math.sin(a)),.45).normalize();
}
function worldMix(T,a,b,t){return new T.Color(a).lerp(new T.Color(b),Math.max(0,Math.min(1,t)))}
/* One fog per scene, recoloured with the hour: a new Fog every frame is garbage. */
function wlFog(T,scene,color,near,far){
  if(!scene.fog)scene.fog=new T.Fog(color,near,far);else scene.fog.color.copy(color);
}
function worldBox(T,w,h,d,color,o){
  const props=Object.assign({color,roughness:.85},o||{});
  return new T.Mesh(new T.BoxGeometry(w,h,d),wlMat(T,'box:'+JSON.stringify(props),props));
}
var WL_TEX={},WL_MAT={};
/* Materials are shared by key within one build, so baking can merge what shares one.
   Each kit starts with WL_MAT={}: the last build's were disposed with its scene. */
function wlMat(T,key,o){return WL_MAT[key]||(WL_MAT[key]=new T.MeshStandardMaterial(o))}
/* Static props are baked: every mesh under root that shares a material becomes one
   mesh. The canal town is about a thousand meshes as built and a few dozen as drawn,
   which is the difference between smooth and a slideshow on software rendering. */
function wlBake(T,root){
  root.updateMatrixWorld(true);
  const inv=root.matrixWorld.clone().invert(),by=new Map(),drop=[],mx=new T.Matrix4();
  root.traverse(o=>{if(!o.isMesh||Array.isArray(o.material)||o.userData.keep)return;
    const g=o.geometry.index?o.geometry.toNonIndexed():o.geometry.clone();
    g.applyMatrix4(mx.multiplyMatrices(inv,o.matrixWorld));
    const k=o.material.uuid;if(!by.has(k))by.set(k,{m:o.material,gs:[],cast:false,recv:false});
    const e=by.get(k);e.gs.push(g);e.cast=e.cast||o.castShadow;e.recv=e.recv||o.receiveShadow;drop.push(o)});
  drop.forEach(o=>{o.parent.remove(o);o.geometry.dispose()});
  by.forEach(e=>{
    const geo=new T.BufferGeometry();
    ['position','normal','uv'].filter(n=>e.gs.every(g=>g.attributes[n])).forEach(n=>{
      let len=0;e.gs.forEach(g=>len+=g.attributes[n].array.length);
      const arr=new Float32Array(len);let off=0;e.gs.forEach(g=>{arr.set(g.attributes[n].array,off);off+=g.attributes[n].array.length});
      geo.setAttribute(n,new T.BufferAttribute(arr,e.gs[0].attributes[n].itemSize))});
    e.gs.forEach(g=>g.dispose());
    const m=new T.Mesh(geo,e.m);m.castShadow=e.cast;m.receiveShadow=e.recv;root.add(m)});
  return root;
}
function wlCanvasTex(T,key,w,h,draw){
  if(WL_TEX[key])return WL_TEX[key];
  const c=document.createElement('canvas');c.width=w;c.height=h;draw(c.getContext('2d'),w,h);
  const t=new T.CanvasTexture(c);t.colorSpace=T.SRGBColorSpace;return WL_TEX[key]=t;
}
function wlGlowTex(T){return wlCanvasTex(T,'glow',64,64,(g,w)=>{
  const r=g.createRadialGradient(w/2,w/2,0,w/2,w/2,w/2);
  r.addColorStop(0,'rgba(255,255,255,1)');r.addColorStop(.25,'rgba(255,255,255,.55)');r.addColorStop(1,'rgba(255,255,255,0)');
  g.fillStyle=r;g.fillRect(0,0,w,w)})}
function wlShadowTex(T){return wlCanvasTex(T,'shadow',64,64,(g,w)=>{
  const r=g.createRadialGradient(w/2,w/2,0,w/2,w/2,w/2);
  r.addColorStop(0,'rgba(0,0,0,.55)');r.addColorStop(1,'rgba(0,0,0,0)');g.fillStyle=r;g.fillRect(0,0,w,w)})}
/* Paving: stones of slightly different greys with dark joints, painted once. Each use
   clones it for its own repeat; the picture is shared. */
function wlPaving(T,rx,ry){
  const base=wlCanvasTex(T,'paving',256,256,(g,w,h)=>{g.fillStyle='#5f5a52';g.fillRect(0,0,w,h);
    for(let y=0;y<4;y++)for(let x=0;x<4;x++){const l=150+Math.floor(Math.random()*40),o=(y%2)*32;
      g.fillStyle=`rgb(${l},${l-6},${l-16})`;g.fillRect((x*64+o)%w+2,y*64+2,60,60);
      if(o&&x===3){g.fillRect(2,y*64+2,30,60)}
      g.fillStyle='rgba(255,255,255,.05)';g.fillRect((x*64+o)%w+2,y*64+2,60,5)}});
  const t=base.clone();t.wrapS=t.wrapT=T.RepeatWrapping;t.repeat.set(rx,ry);t.needsUpdate=true;return t;
}
/* A halo: an additive sprite that brightens with the night. Cheap light without a
   bloom pass, which on a software renderer would be the whole frame again. */
function wlHalo(T,scene,pos,color,size,list){
  const s=new T.Sprite(new T.SpriteMaterial({map:wlGlowTex(T),color,transparent:true,blending:T.AdditiveBlending,depthWrite:false,fog:false,opacity:0}));
  s.position.copy(pos);s.scale.set(size,size,1);s.userData.size=size;scene.add(s);if(list)list.push(s);return s;
}
/* Paint on the page, once, for the mood effects. */
function wlFxTex(T,kind){return wlCanvasTex(T,'fx-'+kind,64,64,(g,w)=>{
  g.translate(w/2,w/2);
  if(kind==='puff'){const r=g.createRadialGradient(0,0,2,0,0,28);r.addColorStop(0,'rgba(255,120,90,.95)');r.addColorStop(1,'rgba(255,90,70,0)');g.fillStyle=r;g.beginPath();g.arc(0,0,28,0,7);g.fill()}
  if(kind==='heart'){g.fillStyle='#ff5d8f';g.beginPath();g.moveTo(0,20);g.bezierCurveTo(-30,-2,-18,-26,0,-10);g.bezierCurveTo(18,-26,30,-2,0,20);g.fill()}
  if(kind==='star'){g.fillStyle='#fff3a6';g.beginPath();for(let i=0;i<8;i++){const a=i*Math.PI/4,r=i%2?7:26;g.lineTo(Math.cos(a)*r,Math.sin(a)*r)}g.fill()}
  if(kind==='z'){g.fillStyle='#e8f0ff';g.font='bold 40px sans-serif';g.textAlign='center';g.textBaseline='middle';g.fillText('z',0,2)}
  if(kind==='drop'){g.fillStyle='#8fd3ff';g.beginPath();g.moveTo(0,-24);g.quadraticCurveTo(18,6,0,22);g.quadraticCurveTo(-18,6,0,-24);g.fill()}
  if(kind==='cloud'){g.fillStyle='#8a94a6';[[-12,4,14],[6,0,17],[18,8,11],[-2,10,13]].forEach(([x,y,r])=>{g.beginPath();g.arc(x,y,r,0,7);g.fill()})}
  if(kind==='scribble'){g.strokeStyle='#3a3340';g.lineWidth=4;g.beginPath();for(let i=0;i<14;i++){const a=i*1.9;g.lineTo(Math.cos(a)*(10+i),Math.sin(a)*(8+i*.6))}g.stroke()}
  if(kind==='rain'){g.strokeStyle='#9fd0ff';g.lineWidth=3;g.beginPath();g.moveTo(0,-14);g.lineTo(-3,14);g.stroke()}
  if(kind==='paper'){g.fillStyle='#fff';g.fillRect(-12,-16,24,32);g.fillStyle='#b8c0cc';for(let y=-10;y<12;y+=6)g.fillRect(-8,y,16,2)}
  if(kind==='petal'){g.fillStyle='#ffc1d9';g.beginPath();g.ellipse(0,0,14,8,.6,0,7);g.fill()}
})}
/* The mood crystal's colour: how the feeling sits, green to red. The Sims shape,
   because everybody already reads it. */
var WL_VALENCE={2:0x3ddc84,1:0x9be15d,0:0xf5d547,'-1':0xff9f43,'-2':0xff4d4d};
function wlCrystal(T){
  const m=new T.Mesh(new T.OctahedronGeometry(.2,0),new T.MeshStandardMaterial({color:0x3ddc84,emissive:0x3ddc84,emissiveIntensity:.55,roughness:.25,metalness:.1,flatShading:true}));
  m.scale.set(1,1.75,1);return m;
}

/* ---------------- the sky ---------------- */
var WL_NOISE=`
float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
float noise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);
  return mix(mix(hash(i),hash(i+vec2(1.,0.)),f.x),mix(hash(i+vec2(0.,1.)),hash(i+vec2(1.,1.)),f.x),f.y);}
float fbm(vec2 p){float v=0.,a=.5;for(int i=0;i<OCT;i++){v+=a*noise(p);p*=2.03;a*=.5;}return v;}`;
/* The light version (WORLD.hq false: software rendering, phones) runs the same shaders
   with fewer noise octaves and fewer light streaks. Measured on SwiftShader, the sky's
   clouds and the water's streaks were most of a frame. */
function wlDefines(){return WORLD.hq?{OCT:5,NL:8,FLICKER:1}:{OCT:3,NL:4,FLICKER:0}}
function wlSky(T,scene,o){
  o=o||{};
  const u={top:{value:new T.Color()},horizon:{value:new T.Color()},sunDir:{value:new T.Vector3(0,1,0)},
    sunCol:{value:new T.Color(0xfff1d0)},moonDir:{value:new T.Vector3(.4,.5,-.8).normalize()},
    night:{value:0},time:{value:0},cloud:{value:o.clouds==null?.75:o.clouds},nebula:{value:o.nebula?1:0}};
  const mat=new T.ShaderMaterial({uniforms:u,side:T.BackSide,depthWrite:false,fog:false,defines:wlDefines(),
    vertexShader:`varying vec3 vDir;void main(){vDir=normalize(position);vec4 p=projectionMatrix*modelViewMatrix*vec4(position,1.);gl_Position=p.xyww;}`,
    fragmentShader:`uniform vec3 top,horizon,sunDir,sunCol,moonDir;uniform float night,time,cloud,nebula;varying vec3 vDir;${WL_NOISE}
    void main(){vec3 d=normalize(vDir);float h=max(d.y,0.);
      vec3 col=mix(horizon,top,pow(h,.42));
      float s=max(dot(d,sunDir),0.);col+=sunCol*(pow(s,900.)*6.+pow(s,10.)*.28+pow(s,3.)*.08)*(1.-night);
      float m=max(dot(d,moonDir),0.);col+=vec3(.92,.95,1.)*smoothstep(.99955,.9998,m)*night+vec3(.35,.45,.7)*pow(m,60.)*.5*night;
      vec2 sp=d.xz/(abs(d.y)+.2)*70.;float hs=hash(floor(sp));
      float st=step(.9965,hs)*smoothstep(0.,.25,h+nebula);col+=vec3(st)*max(night,nebula)*(.55+.45*sin(time*2.+hs*60.));
      if(nebula>.5){float n=fbm(d.xy*2.2+vec2(time*.002,0.));col+=vec3(.45,.18,.6)*smoothstep(.45,.9,n)*.55+vec3(.1,.35,.6)*smoothstep(.55,.95,fbm(d.zy*3.1))*.4;}
      if(d.y>0.&&cloud>0.){vec2 cp=d.xz/(d.y+.12)*1.1+vec2(time*.003,0.);
        float c=smoothstep(.52,.86,fbm(cp*1.7))*cloud;
        vec3 cc=mix(vec3(1.,.98,.96),horizon,.25)*mix(1.,.32,night)+sunCol*.2*(1.-night)*pow(s,4.);
        col=mix(col,cc,c*smoothstep(0.,.18,h)*.9);}
      gl_FragColor=vec4(col,1.);
      #include <tonemapping_fragment>
      #include <colorspace_fragment>
    }`});
  const mesh=new T.Mesh(new T.SphereGeometry(300,32,16),mat);mesh.renderOrder=-1;mesh.frustumCulled=false;scene.add(mesh);
  return {u,mesh};
}
/* the sky's colours for the hour: night, dawn/dusk, day */
function wlSkyColors(T,day,warm){
  const dusk=day>0&&day<.38;
  return {top:worldMix(T,0x070b22,day>.38?0x3f8fe0:0x4a5fa8,day*1.9),
    horizon:worldMix(T,0x1a2446,dusk?(warm||0xffa36b):0xcfe6ff,Math.min(1,day*2.4)),
    fog:worldMix(T,0x131b3a,dusk?0xe8a882:0xcfe3f5,Math.min(1,day*2.2))};
}

/* ---------------- the water ---------------- */
function wlWater(T,geo,o){
  o=o||{};
  const lights=[],lightCol=[];for(let i=0;i<8;i++){lights.push(new T.Vector3(0,-99,0));lightCol.push(new T.Color(0))}
  const u={time:{value:0},night:{value:0},day:{value:1},deep:{value:new T.Color(o.deep||0x0f6f73)},
    shallow:{value:new T.Color(o.shallow||0x2fb6a8)},skyTop:{value:new T.Color()},skyHor:{value:new T.Color()},
    sunDir:{value:new T.Vector3(0,1,0)},sunCol:{value:new T.Color(0xfff1d0)},fogCol:{value:new T.Color()},
    fogNear:{value:40},fogFar:{value:220},lights:{value:lights},lightCol:{value:lightCol},nLights:{value:0},
    edgeX:{value:o.edgeX||0}};
  const mat=new T.ShaderMaterial({uniforms:u,defines:wlDefines(),
    vertexShader:`uniform float time;varying vec3 vW;varying vec3 vN;
      float wv(vec2 p,float t){return sin(p.x*.32+t*1.05)*.07+sin(p.y*.55-t*.85)*.06+sin((p.x+p.y)*.95+t*1.6)*.025;}
      void main(){vec4 w=modelMatrix*vec4(position,1.);float e=.15;float h=wv(w.xz,time);
        vN=normalize(vec3(h-wv(w.xz+vec2(e,0.),time),e,h-wv(w.xz+vec2(0.,e),time)));
        w.y+=h;vW=w.xyz;gl_Position=projectionMatrix*viewMatrix*w;}`,
    fragmentShader:`uniform float time,night,day,fogNear,fogFar,nLights,edgeX;uniform vec3 deep,shallow,skyTop,skyHor,sunDir,sunCol,fogCol;
      uniform vec3 lights[8];uniform vec3 lightCol[8];varying vec3 vW;varying vec3 vN;${WL_NOISE}
      void main(){vec3 V=normalize(cameraPosition-vW);vec2 q=vW.xz*1.4;float t=time*.55;
        float n1=noise(q+vec2(t,t*.6)),n2=noise(q*2.4-vec2(t*.9,-t));
        vec3 N=normalize(vN*4.+vec3((n1-.5)*.9,0.,(n2-.5)*.9));
        float fres=clamp(pow(1.-max(dot(N,V),0.),3.)*.85+.06,0.,1.);
        vec3 R=reflect(-V,N);vec3 sky=mix(skyHor,skyTop,clamp(R.y*1.6,0.,1.));
        vec3 base=mix(deep,shallow,.35+.35*n1);
        vec3 col=mix(base,sky,fres);
        float sd=max(dot(R,sunDir),0.);col+=sunCol*(pow(sd,260.)*3.+pow(sd,24.)*.12)*day;
        col+=vec3(1.)*step(.975,noise(vW.xz*5.+time*1.4))*day*.35;
        for(int i=0;i<NL;i++){if(float(i)>=nLights)break;vec3 L=lights[i];vec2 dz=vW.xz-L.xz;
          vec2 tc=normalize(cameraPosition.xz-L.xz);float al=dot(dz,tc),ac=dot(dz,vec2(-tc.y,tc.x));
          float fl=.8;
          #if FLICKER
          fl=.55+.45*noise(vec2(al*2.5-time*2.,ac*7.));
          #endif
          float g=exp(-ac*ac*5.)*exp(-max(al,0.)*.09)*step(-.3,al)*fl;
          col+=lightCol[i]*g*night*1.3;}
        if(edgeX>0.){col=mix(col,vec3(.92,.97,1.)*mix(1.,.35,night),smoothstep(.35,0.,edgeX-abs(vW.x))*(.18+.25*n2));}
        float dist=length(cameraPosition-vW);col=mix(col,fogCol,smoothstep(fogNear,fogFar,dist));
        gl_FragColor=vec4(col,1.);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`});
  const mesh=new T.Mesh(geo,mat);
  return {mesh,u,
    setLights(list){list.slice(0,8).forEach((l,i)=>{lights[i].copy(l.pos);lightCol[i].set(l.color)});u.nLights.value=Math.min(8,list.length)},
    light(t,day,sky,sunDir,warm){u.time.value=t;u.day.value=day;u.night.value=1-Math.min(1,day*2.4);
      u.skyTop.value.copy(sky.top);u.skyHor.value.copy(sky.horizon);u.fogCol.value.copy(sky.fog);u.sunDir.value.copy(sunDir);
      u.deep.value.set(worldMix(T,o.nightDeep||0x04202b,o.deep||0x0f6f73,day*1.6));
      u.shallow.value.set(worldMix(T,o.nightShallow||0x0c4452,o.shallow||0x2fb6a8,day*1.6));
      if(warm)u.sunCol.value.set(worldMix(T,0xffa36b,0xfff1d0,day*2))}};
}

/* ---------------- props ---------------- */
function wlStars(T,scene,n,box,color,size){
  const g=new T.BufferGeometry(),p=new Float32Array(n*3);
  for(let i=0;i<n;i++){p[i*3]=box[0]+Math.random()*(box[1]-box[0]);p[i*3+1]=box[2]+Math.random()*(box[3]-box[2]);p[i*3+2]=box[4]+Math.random()*(box[5]-box[4])}
  g.setAttribute('position',new T.BufferAttribute(p,3));
  const m=new T.PointsMaterial({color,size,map:wlGlowTex(T),transparent:true,depthWrite:false,blending:T.AdditiveBlending,opacity:0});
  const pts=new T.Points(g,m);scene.add(pts);return pts;
}
function wlPetals(T,scene,n,box){
  const g=new T.BufferGeometry(),p=new Float32Array(n*3),seed=new Float32Array(n);
  for(let i=0;i<n;i++){p[i*3]=box[0]+Math.random()*(box[1]-box[0]);p[i*3+1]=box[2]+Math.random()*(box[3]-box[2]);p[i*3+2]=box[4]+Math.random()*(box[5]-box[4]);seed[i]=Math.random()*6}
  g.setAttribute('position',new T.BufferAttribute(p,3));
  const m=new T.PointsMaterial({size:.32,map:wlFxTex(T,'petal'),transparent:true,depthWrite:false,alphaTest:.05});
  const pts=new T.Points(g,m);scene.add(pts);
  return {pts,tick(dt,t){const a=g.attributes.position.array;
    for(let i=0;i<n;i++){a[i*3+1]-=dt*(.35+seed[i]*.05);a[i*3]+=Math.sin(t*.8+seed[i])*dt*.4;a[i*3+2]+=dt*.15;
      if(a[i*3+1]<box[2]){a[i*3+1]=box[3];a[i*3]=box[0]+Math.random()*(box[1]-box[0]);a[i*3+2]=box[4]+Math.random()*(box[5]-box[4])}}
    g.attributes.position.needsUpdate=true}};
}
/* A machiya: dark timber below, cream plaster above, a middle eave, a hipped tile roof
   with a deep overhang, a noren over the door and a window that lights at night. Built
   facing +z; the caller turns it to the water. */
function wlMachiya(T,w,h,style,glow){
  const g=new T.Group(),d=4.2;
  style=style%3;
  const wood=[0x3e2c20,0x5a3d2b,0x2e2520][style],plaster=[0xf1e6cf,0xe9dcc0,0xf6efe0][style];
  const low=worldBox(T,w,h*.52,d,wood);low.position.y=h*.26;g.add(low);
  const up=worldBox(T,w*.96,h*.48,d*.96,plaster);up.position.y=h*.52+h*.24;g.add(up);
  const beamM=wlMat(T,'beam',{color:0x2a1f18,roughness:.9});
  [[0,h*.52,w*1.02,.14,d*1.02],[-w*.49,h*.75,.14,h*.48,d*1.0],[w*.49,h*.75,.14,h*.48,d*1.0]].forEach(([x,y,bw,bh,bd])=>{
    const b=new T.Mesh(new T.BoxGeometry(bw,bh,bd),beamM);b.position.set(x,y,0);g.add(b)});
  const tileM=wlMat(T,'tile'+style,{color:[0x384050,0x2f3642,0x4a4a52][style],roughness:.6,flatShading:true});
  const eave=new T.Mesh(new T.BoxGeometry(w*1.12,.16,d*1.25),tileM);eave.position.y=h*.52+.06;eave.position.z=.18;eave.rotation.x=.08;g.add(eave);
  const roof=new T.Mesh(new T.ConeGeometry(1,1,4,1),tileM);roof.rotation.y=Math.PI/4;
  roof.scale.set(w*.82,1.5,d*.92);roof.position.y=h+.72;g.add(roof);
  const noren=new T.Mesh(new T.PlaneGeometry(w*.42,h*.2),wlMat(T,'noren'+style,{color:[0x2d4a8a,0xa3312a,0x2f5d4e][style],side:T.DoubleSide,roughness:1}));
  noren.position.set(-w*.18,h*.4,d/2+.03);g.add(noren);
  const wm=wlMat(T,'win'+style,{color:0x2c2418,emissive:[0xffb24d,0xffc978,0xff9f45][style],emissiveIntensity:0});
  const win=new T.Mesh(new T.PlaneGeometry(w*.36,h*.22),wm);win.position.set(w*.12,h*.76,d/2+.03);g.add(win);
  // a lattice over the window: the machiya's face
  const lat=wlMat(T,'lattice',{color:0x3a2a1e});
  for(let i=-2;i<=2;i++){const b=new T.Mesh(new T.BoxGeometry(.05,h*.22,.04),lat);b.position.set(w*.12+i*w*.07,h*.76,d/2+.06);g.add(b)}
  const lanternM=wlMat(T,'doorlantern',{color:0xd94a38,emissive:0xff5a3a,emissiveIntensity:.2});
  const lan=new T.Mesh(new T.CylinderGeometry(.16,.16,.34,10),lanternM);lan.position.set(w*.36,h*.46,d/2+.28);g.add(lan);
  g.traverse(o=>{if(o.isMesh){o.castShadow=true;o.receiveShadow=true}});
  if(glow){if(glow.wins.indexOf(wm)<0)glow.wins.push(wm);if(glow.lanterns.indexOf(lanternM)<0)glow.lanterns.push(lanternM);glow.spots.push({obj:win,color:0xffb24d,size:2.6},{obj:lan,color:0xff6a3d,size:1.8})}
  return g;
}
function wlWillow(T){
  const g=new T.Group();
  const trunk=new T.Mesh(new T.CylinderGeometry(.22,.35,3.4,7),wlMat(T,'bark',{color:0x5a4330,roughness:1}));trunk.position.y=1.7;g.add(trunk);
  const geo=new T.IcosahedronGeometry(2.3,2),p=geo.attributes.position;
  for(let i=0;i<p.count;i++){const y=p.getY(i);p.setY(i,y<0?y*1.9-.3:y*.7);p.setX(i,p.getX(i)*(1+(y<0?.15:0)));}
  geo.computeVertexNormals();
  const crown=new T.Mesh(geo,wlMat(T,'willow',{color:0x7fb05a,roughness:.9,flatShading:true}));crown.position.y=4.2;g.add(crown);
  // hanging strands: a crossed pair of planes with a painted curtain
  const tex=wlCanvasTex(T,'willow',64,128,(c,w,h)=>{for(let i=0;i<22;i++){c.strokeStyle=`rgba(${110+i*3},${170+i%3*12},90,.9)`;c.lineWidth=2;
    const x=Math.random()*w;c.beginPath();c.moveTo(x,0);c.quadraticCurveTo(x+4,h*.5,x-2,h*(.55+Math.random()*.45));c.stroke()}});
  for(let k=0;k<3;k++){const pl=new T.Mesh(new T.PlaneGeometry(4.2,4.2),wlMat(T,'strands',{map:tex,transparent:true,alphaTest:.3,side:T.DoubleSide}));
    pl.position.y=2.4;pl.rotation.y=k*Math.PI/3;g.add(pl)}
  g.traverse(o=>{if(o.isMesh)o.castShadow=true});
  return g;
}
function wlSakura(T){
  const g=new T.Group();
  const trunk=new T.Mesh(new T.CylinderGeometry(.18,.3,2.6,7),wlMat(T,'bark2',{color:0x4b3428,roughness:1}));trunk.position.y=1.3;g.add(trunk);
  [[0,3.4,0,1.6],[1,3,.4,1.1],[-1,3.1,-.3,1.2],[.2,3.9,-.6,1.1]].forEach(([x,y,z,r],i)=>{
    const c=new T.Mesh(new T.IcosahedronGeometry(r,1),wlMat(T,'blossom'+(i%2),{color:i%2?0xf7b6cf:0xf49ac1,roughness:.8,flatShading:true}));
    c.position.set(x,y,z);g.add(c)});
  g.traverse(o=>{if(o.isMesh)o.castShadow=true});
  return g;
}
function wlPagoda(T,glow){
  const g=new T.Group(),red=wlMat(T,'pagodared',{color:0xb03a2e,roughness:.7}),roofM=wlMat(T,'tile1',{color:0x2f3642,roughness:.6,flatShading:true});
  for(let i=0;i<5;i++){const s=1-i*.14,y=i*2.2;
    const body=new T.Mesh(new T.BoxGeometry(3.2*s,1.7,3.2*s),red);body.position.y=y+.85;g.add(body);
    const roof=new T.Mesh(new T.ConeGeometry(3.4*s,1,4,1),roofM);roof.rotation.y=Math.PI/4;roof.position.y=y+2;roof.scale.y=.55;g.add(roof);
    if(glow){const wm=wlMat(T,'win0',{color:0x2c2418,emissive:0xffb24d,emissiveIntensity:0});
      const w=new T.Mesh(new T.PlaneGeometry(.8*s,.5),wm);w.position.set(0,y+.9,1.6*s+.02);g.add(w);if(glow.wins.indexOf(wm)<0)glow.wins.push(wm)}}
  const spire=new T.Mesh(new T.CylinderGeometry(.06,.1,2.6,6),wlMat(T,'gold',{color:0xc9a44a,metalness:.6,roughness:.3}));spire.position.y=12.2;g.add(spire);
  g.traverse(o=>{if(o.isMesh)o.castShadow=true});
  return g;
}
/* A string of paper lanterns across the water, hanging in a catenary. */
function wlLanternString(T,scene,a,b,n,glow,halos,into){
  into=into||scene;
  const pts=[];for(let i=0;i<=24;i++){const t=i/24;const p=a.clone().lerp(b,t);p.y-=Math.sin(t*Math.PI)*1.3;pts.push(p)}
  const line=new T.Mesh(new T.TubeGeometry(new T.CatmullRomCurve3(pts),24,.025,4,false),wlMat(T,'cord',{color:0x2a2020,roughness:1}));into.add(line);
  const cols=[0xe74c3c,0xfff1d6,0xf39c12];
  for(let i=1;i<n;i++){const t=i/n,p=a.clone().lerp(b,t);p.y-=Math.sin(t*Math.PI)*1.3+.28;
    const c=cols[i%3],m=wlMat(T,'lantern'+c,{color:c,emissive:c,emissiveIntensity:.2,roughness:.7});
    const l=new T.Mesh(new T.SphereGeometry(.22,10,8),m);l.scale.y=1.3;l.position.copy(p);into.add(l);if(glow.lanterns.indexOf(m)<0)glow.lanterns.push(m);
    wlHalo(T,scene,p,c,1.9,halos)}
}
/* Mountains in layers that fade into the air: depth by colour, the painter's trick. */
function wlRange(T,scene,z,n,spread,color,hmax){
  const m=wlMat(T,'range'+z,{color,flatShading:true,roughness:1,fog:true});
  for(let i=0;i<n;i++){const h=hmax*(.55+((i*37)%11)/22),r=h*(1.1+((i*13)%5)/10);
    const c=new T.Mesh(new T.ConeGeometry(r,h,7,1),m);c.position.set(-spread/2+i*spread/(n-1)+((i*17)%9)-4,h/2-3,z-((i*11)%4)*8);scene.add(c)}
  return m;
}
function wlBoat(T){
  const g=new T.Group();
  const hullM=wlMat(T,'hull',{color:0x7a4a26,roughness:.8}),rimM=wlMat(T,'hullrim',{color:0xb83227,roughness:.6});
  const shape=new T.Shape();shape.moveTo(-1.6,0);shape.quadraticCurveTo(-1.2,-.55,0,-.6);shape.quadraticCurveTo(1.3,-.55,1.8,0);
  shape.quadraticCurveTo(1.3,.55,0,.6);shape.quadraticCurveTo(-1.2,.55,-1.6,0);
  const hull=new T.Mesh(new T.ExtrudeGeometry(shape,{depth:.45,bevelEnabled:false}),hullM);hull.rotation.x=-Math.PI/2;hull.position.y=-.15;g.add(hull);
  const rim=new T.Mesh(new T.TorusGeometry(1,.05,4,24),rimM);rim.scale.set(1.65,.58,1);rim.rotation.x=Math.PI/2;rim.position.y=.3;g.add(rim);
  const roof=new T.Mesh(new T.CylinderGeometry(.55,.55,1.3,12,1,true,0,Math.PI),wlMat(T,'boatroof',{color:0xcaa76a,side:T.DoubleSide,roughness:.95}));
  roof.rotation.z=Math.PI/2;roof.rotation.y=Math.PI/2;roof.position.set(-.35,.35,0);g.add(roof);
  g.traverse(o=>{if(o.isMesh){o.castShadow=true}});
  return g;
}

/* ---------------- the kits ---------------- */
/* Each kit: a place, the spots people stand on (nearest first, the lead takes the
   first), where a busy agent goes, how the light moves, and a camera for a wide and a
   tall screen. */
var WORLD_KITS={
  canal(T,scene,cam){
    WL_MAT={};
    const hq=WORLD.hq,glow={wins:[],lanterns:[],spots:[]},halos=[];
    const town=new T.Group();scene.add(town);
    const sky=wlSky(T,scene,{clouds:.8});
    const hemi=new T.HemisphereLight(0xdfefff,0x3b4a3a,.7);scene.add(hemi);
    const sun=new T.DirectionalLight(0xfff1d6,2.2);scene.add(sun);scene.add(sun.target);
    if(hq){sun.castShadow=true;sun.shadow.mapSize.set(1024,1024);const sc=sun.shadow.camera;sc.left=-26;sc.right=26;sc.top=26;sc.bottom=-26;sc.near=1;sc.far=160;sun.shadow.bias=-.0015}
    const moon=new T.DirectionalLight(0x8fa8ff,0);moon.position.set(20,40,20);scene.add(moon);
    const ranges=[wlRange(T,town,-190,9,420,0x5f7d8f,60),wlRange(T,town,-140,8,320,0x557060,38)];
    // the canal runs away from you, a town on each bank; the team stands on a stone
    // landing at its head, where you are
    const water=wlWater(T,new T.PlaneGeometry(10,236,20,120).rotateX(-Math.PI/2),{edgeX:5});water.mesh.position.set(0,0,-115);scene.add(water.mesh);
    const stone=0x8e8a80;
    [-1,1].forEach(s=>{
      const wall=worldBox(T,1.2,1.9,236,stone,{roughness:.95});wall.position.set(s*5.6,.35,-115);wall.receiveShadow=true;town.add(wall);
      const walk=new T.Mesh(new T.BoxGeometry(6,.3,236),wlMat(T,'walk',{color:0xe0d4bc,map:wlPaving(T,1.5,59),roughness:1}));walk.position.set(s*9,1.15,-115);walk.receiveShadow=true;town.add(walk);
      const grass=worldBox(T,40,.3,236,0x6f9a55,{roughness:1});grass.position.set(s*32,1.1,-115);grass.receiveShadow=true;town.add(grass);
    });
    const landing=new T.Mesh(new T.BoxGeometry(36,1.9,14),new T.MeshStandardMaterial({color:0xd6cfc2,map:wlPaving(T,9,3.5),roughness:.95}));
    landing.position.set(0,.37,10);landing.receiveShadow=true;town.add(landing);
    const lawn=worldBox(T,120,.3,40,0x5f8a4a,{roughness:1});lawn.position.set(0,1.1,30);lawn.receiveShadow=true;town.add(lawn);
    // bollards along the landing's edge over the water
    for(let x=-16;x<=16;x+=4){if(Math.abs(x)<3)continue;const b=new T.Mesh(new T.CylinderGeometry(.18,.22,.6,8),wlMat(T,'bollard',{color:0x6e6a62,roughness:.9}));b.position.set(x,1.6,3.4);b.castShadow=true;town.add(b)}
    // two stone lanterns frame the landing
    const lampLights=[];
    [-1,1].forEach(s=>{const g=new T.Group(),sm=wlMat(T,'toro',{color:0x9a958a,roughness:1,flatShading:true});
      const base=new T.Mesh(new T.CylinderGeometry(.35,.55,1.4,6),sm);base.position.y=.7;g.add(base);
      const lm=wlMat(T,'torolight',{color:0xd8d2c4,emissive:0xffc26b,emissiveIntensity:.1});const box=new T.Mesh(new T.BoxGeometry(.8,.7,.8),lm);box.position.y=1.75;g.add(box);
      if(glow.lanterns.indexOf(lm)<0)glow.lanterns.push(lm);
      const cap=new T.Mesh(new T.ConeGeometry(.9,.6,6),sm);cap.position.y=2.4;g.add(cap);
      g.position.set(s*15,1.3,5.2);g.traverse(o=>{if(o.isMesh)o.castShadow=true});town.add(g);
      wlHalo(T,scene,new T.Vector3(s*15,3.05,5.2),0xffc26b,3,halos);lampLights.push({pos:new T.Vector3(s*15,3.05,5.2),color:0xffb45a})});
    // houses on both banks, facing the water
    let k=0;
    for(let z=0;z>-150;z-=5.2+((k*7)%3)){
      [-1,1].forEach(s=>{k++;
        if((k*5)%11===0)return;               // a gap, for a tree or a lane
        const w=4+((k*3)%3)*.7,h=3.4+((k*5)%4)*.55;
        const hs=wlMachiya(T,w,h,k,glow);hs.position.set(s*(14.5+((k*11)%3)*.6),1.3,z);hs.rotation.y=s<0?Math.PI/2:-Math.PI/2;town.add(hs);
      });
    }
    const pagoda=wlPagoda(T,glow);pagoda.position.set(19,1.3,-58);town.add(pagoda);
    // the vermilion bridge: a deck on an arch, railings and posts
    const red=wlMat(T,'bridgered',{color:0xc0392b,roughness:.55}),deckM=wlMat(T,'bridgedeck',{color:0x7a2a20,roughness:.8});
    const bz=-26,seg=18;
    for(let i=0;i<seg;i++){const x0=-7.5+i*15/seg,x1=x0+15/seg,xm=(x0+x1)/2,y=v=>1.3+2.3*Math.cos(v/7.5*Math.PI/2);
      const ang=Math.atan2(y(x1)-y(x0),x1-x0);
      const d=new T.Mesh(new T.BoxGeometry(15/seg+.05,.22,2.6),deckM);d.position.set(xm,y(xm),bz);d.rotation.z=ang;d.castShadow=true;town.add(d);
      [-1.25,1.25].forEach(zz=>{const r=new T.Mesh(new T.BoxGeometry(15/seg+.05,.1,.1),red);r.position.set(xm,y(xm)+.85,bz+zz);r.rotation.z=ang;town.add(r);
        if(i%3===0){const p=new T.Mesh(new T.BoxGeometry(.12,.9,.12),red);p.position.set(x0,y(x0)+.42,bz+zz);town.add(p)}});}
    [-1,1].forEach(s=>{const pier=worldBox(T,.7,2.4,2.8,0x6e6a62);pier.position.set(s*6.6,.2,bz);town.add(pier)});
    // lantern strings across the water, lamps along both quays
    [-8,-44,-78].forEach(z=>wlLanternString(T,scene,new T.Vector3(-9,6.6,z),new T.Vector3(9,6.6,z),8,glow,halos,town));
    const poleM=wlMat(T,'pole',{color:0x3a2c22}),lampM=wlMat(T,'lamp',{color:0xfff1d6,emissive:0xffc26b,emissiveIntensity:.2});
    glow.lanterns.push(lampM);
    for(let z=-2;z>-120;z-=12){[-1,1].forEach(s=>{
      const p=new T.Mesh(new T.CylinderGeometry(.07,.09,3,6),poleM);p.position.set(s*6.7,2.7,z);town.add(p);
      const lamp=new T.Mesh(new T.BoxGeometry(.38,.5,.38),lampM);lamp.position.set(s*6.7,4.35,z);town.add(lamp);
      wlHalo(T,scene,lamp.position,0xffc26b,2.4,halos);
      if(lampLights.length<8)lampLights.push({pos:new T.Vector3(s*6.7,4.35,z),color:0xffb45a});})}
    water.setLights(lampLights);
    // trees: willows by the water, cherry blossom between the houses, two at the landing
    [[-18,6,'w'],[18.5,4,'s'],[8.8,-14,'w'],[-9,-40,'w'],[-9.2,-20,'s'],[9.3,-50,'s'],[-8.8,-70,'w'],[9,-86,'w']].forEach(([x,z,t])=>{
      const tr=t==='w'?wlWillow(T):wlSakura(T);tr.position.set(x,1.3,z);town.add(tr)});
    // moored boats: scenery, like the houses; they do not move
    [[3.2,-6,.1],[-3.3,-18,-.08],[3,-52,.05]].forEach(([x,z,r])=>{const b=wlBoat(T);b.position.set(x,.15,z);b.rotation.y=Math.PI/2+r;town.add(b)});
    // every lit window and door lantern gets a halo, as far as the eye reads them
    town.updateMatrixWorld(true);
    const winHalos=[];
    glow.spots.forEach(sp=>{const p=new T.Vector3();sp.obj.getWorldPosition(p);if(p.z>-100)wlHalo(T,scene,p,sp.color,sp.size,winHalos)});
    wlBake(T,town);
    const petals=wlPetals(T,scene,hq?220:80,[-18,18,1.5,11,-30,20]);
    const flies=wlStars(T,scene,hq?90:40,[-14,14,1.6,4.5,-40,14],0xfff27a,.35);
    const light=d=>{
      const c=wlSkyColors(T,d);
      sky.u.top.value.copy(c.top);sky.u.horizon.value.copy(c.horizon);sky.u.night.value=1-Math.min(1,d*2.4);
      const sd=worldSunDir(T);sky.u.sunDir.value.copy(sd);sun.position.copy(sd).multiplyScalar(80).add(new T.Vector3(0,0,-8));sun.target.position.set(0,0,-8);
      sky.u.sunCol.value.set(worldMix(T,0xff9a5a,0xfff1d6,d*2));sun.color.copy(sky.u.sunCol.value);
      wlFog(T,scene,c.fog,60,230);
      sun.intensity=d*2.4;hemi.intensity=.35+d*.6;hemi.color.set(worldMix(T,0x6e7fc8,0xdfefff,d*2));
      const night=1-Math.min(1,d*2.4);moon.intensity=night*.9;
      glow.wins.forEach(m=>m.emissiveIntensity=night*2);glow.lanterns.forEach(m=>m.emissiveIntensity=.25+night*2.4);
      halos.forEach(h=>h.material.opacity=.12+night*.85);winHalos.forEach(h=>h.material.opacity=night*.8);
      ranges[0].color.set(worldMix(T,0x1d2640,0x7f98a8,d*1.6));ranges[1].color.set(worldMix(T,0x172230,0x5f7f68,d*1.6));
      petals.pts.material.opacity=Math.min(1,d*3);flies.material.opacity=night;
      WORLD.r.toneMappingExposure=.95+night*.35;
      return {c,sd};
    };
    let lit=null;
    return {
      // on the landing in a loose crescent, the lead in front
      spots:[[0,1.3,8.4],[-3.3,1.3,7.6],[3.3,1.3,7.6],[-6.6,1.3,6.4],[6.6,1.3,6.4],[-1.7,1.3,4.6],[1.7,1.3,4.6],
        [-9.8,1.3,5.2],[9.8,1.3,5.2],[-5,1.3,3.8],[5,1.3,3.8],[0,1.3,3.4]],
      camWide:[[0,7.6,27],[0,2.2,-30]],camTall:[[0,9,25],[0,-4.2,-10]],
      busy(i,t){const z=((t*1.6+i*17)%56)-58;return new T.Vector3(i%2?2:-2,.3+Math.sin(t*1.3+i)*.06,z)},
      vessel(){const b=wlBoat(T);b.rotation.y=Math.PI/2;scene.add(b);return b},
      tick(t,dt){water.light(t,lit?lit.d:1,lit?lit.c:wlSkyColors(T,1),lit?lit.sd:new T.Vector3(0,1,0),true);sky.u.time.value=t;petals.tick(dt,t)},
      light(d){const r=light(d);lit={d,c:r.c,sd:r.sd};water.light(sky.u.time.value,d,r.c,r.sd,true)}};
  },
  orbit(T,scene,cam){
    WL_MAT={};
    const hq=WORLD.hq,halos=[];
    const deckG=new T.Group();scene.add(deckG);
    const sky=wlSky(T,scene,{clouds:0,nebula:true});
    sky.u.top.value.set(0x02030a);sky.u.horizon.value.set(0x0a0d22);sky.u.night.value=1;
    const amb=new T.AmbientLight(0x8899ff,.35);scene.add(amb);
    const hemi=new T.HemisphereLight(0xa9c1ff,0x1a1f33,.7);scene.add(hemi);
    const sun=new T.DirectionalLight(0xfff4e0,3);sun.position.set(60,30,30);scene.add(sun);
    // the planet fills the view below the window: its curve is the horizon
    const planet=new T.Mesh(new T.SphereGeometry(80,64,48),new T.MeshStandardMaterial({color:0x2a6fd6,roughness:.85,
      map:wlCanvasTex(T,'land',512,256,(g,w,h)=>{g.fillStyle='#3a7fe0';g.fillRect(0,0,w,h);
        for(let i=0;i<70;i++){g.fillStyle=['#3f8f4a','#6b9a4a','#c8b27a'][i%3];g.beginPath();g.ellipse(Math.random()*w,h*.15+Math.random()*h*.7,6+Math.random()*34,4+Math.random()*16,Math.random()*3,0,7);g.fill()}})}));
    planet.position.set(-10,-88,-120);scene.add(planet);
    const clouds=new T.Mesh(new T.SphereGeometry(81,64,48),new T.MeshStandardMaterial({color:0xffffff,transparent:true,opacity:.45,roughness:1,depthWrite:false,
      alphaMap:wlCanvasTex(T,'pclouds',256,128,(g,w,h)=>{g.fillStyle='#000';g.fillRect(0,0,w,h);for(let i=0;i<140;i++){g.fillStyle=`rgba(255,255,255,${.2+Math.random()*.4})`;g.beginPath();g.ellipse(Math.random()*w,Math.random()*h,8+Math.random()*30,3+Math.random()*6,0,0,7);g.fill()}})}));
    clouds.position.copy(planet.position);scene.add(clouds);
    wlHalo(T,scene,planet.position,0x6fb7ff,215,halos).material.opacity=.45;
    // the ring station, off to the left and turning
    const ring=new T.Group();ring.position.set(-34,16,-80);scene.add(ring);
    const hullM=new T.MeshStandardMaterial({color:0xd9dee8,metalness:.55,roughness:.35});
    ring.add(new T.Mesh(new T.TorusGeometry(14,1.3,16,96),hullM));
    ring.add(new T.Mesh(new T.TorusGeometry(14,1.32,4,96),new T.MeshStandardMaterial({color:0x111,emissive:0x9fd8ff,emissiveIntensity:.9,wireframe:true})));
    for(let i=0;i<6;i++){const sp=new T.Mesh(new T.BoxGeometry(.5,28,.5),new T.MeshStandardMaterial({color:0x9aa4b8,metalness:.5}));sp.rotation.z=i*Math.PI/6;ring.add(sp)}
    const hub=new T.Mesh(new T.CylinderGeometry(2.6,2.6,4.5,24),hullM);hub.rotation.x=Math.PI/2;ring.add(hub);
    for(let i=0;i<12;i++){const a=i/12*Math.PI*2;wlHalo(T,ring,new T.Vector3(Math.cos(a)*14,Math.sin(a)*14,1.4),i%3?0x9fd8ff:0xff6b6b,1.5,halos)}
    ring.rotation.set(.5,.5,0);
    // the observation deck: a lit floor, a window frame with a glowing sill, consoles
    const floorTex=wlCanvasTex(T,'deckfloor',256,256,(g,w)=>{g.fillStyle='#8f98ab';g.fillRect(0,0,w,w);
      for(let i=0;i<4;i++)for(let j=0;j<4;j++){g.fillStyle=(i+j)%2?'#7f889b':'#98a1b3';g.fillRect(i*64+2,j*64+2,60,60)}
      g.fillStyle='#394255';for(let i=0;i<=4;i++){g.fillRect(i*64-1,0,2,w);g.fillRect(0,i*64-1,w,2)}});
    const lineTex=wlCanvasTex(T,'decklines',256,256,(g,w)=>{g.fillStyle='#000';g.fillRect(0,0,w,w);g.fillStyle='#fff';for(let i=0;i<=4;i++){g.fillRect(i*64-1,0,2,w);g.fillRect(0,i*64-1,w,2)}});
    const ft=floorTex.clone(),lt=lineTex.clone();[ft,lt].forEach(t=>{t.wrapS=t.wrapT=T.RepeatWrapping;t.repeat.set(11,5);t.needsUpdate=true});
    const floor=new T.Mesh(new T.BoxGeometry(46,.4,22),new T.MeshStandardMaterial({color:0xffffff,map:ft,emissive:0x2de2e6,emissiveMap:lt,emissiveIntensity:.35,metalness:.25,roughness:.5}));
    floor.position.set(0,.8,12);floor.receiveShadow=true;scene.add(floor);
    const frameM=wlMat(T,'frame',{color:0x3a4254,metalness:.5,roughness:.4});
    const sill=new T.Mesh(new T.BoxGeometry(46,1.2,.8),frameM);sill.position.set(0,1.6,1.2);deckG.add(sill);
    const railM=new T.MeshStandardMaterial({color:0x2de2e6,emissive:0x2de2e6,emissiveIntensity:1});
    const rail=new T.Mesh(new T.BoxGeometry(46,.08,.12),railM);rail.position.set(0,2.24,1.4);scene.add(rail);
    [-22,-11,11,22].forEach(x=>{const m=new T.Mesh(new T.BoxGeometry(.35,24,.5),frameM);m.position.set(x,12,1);deckG.add(m)});
    const top=new T.Mesh(new T.BoxGeometry(46,.8,.8),frameM);top.position.set(0,23.6,1);deckG.add(top);
    wlBake(T,deckG);
    const panels=[];
    [-13,-7,7,13].forEach((x,i)=>{const c=new T.Mesh(new T.BoxGeometry(2.4,1.1,.7),frameM);c.position.set(x,1.55,2.4);scene.add(c);
      const pm=new T.MeshStandardMaterial({color:0x0a0f1a,emissive:i%2?0x3a86ff:0x2de2e6,emissiveIntensity:.8,transparent:true,opacity:.8,side:T.DoubleSide});
      const p=new T.Mesh(new T.PlaneGeometry(2.2,1.1),pm);p.position.set(x,3,2.5);p.rotation.x=-.18;scene.add(p);panels.push(pm);
      wlHalo(T,scene,new T.Vector3(x,3,2.6),i%2?0x3a86ff:0x2de2e6,3.4,halos).material.opacity=.5});
    const drift=wlStars(T,scene,hq?120:50,[-40,40,-10,30,-80,0],0xbfd8ff,.4);drift.material.opacity=.8;
    return {
      spots:[[0,1,9.2],[-3.3,1,8.4],[3.3,1,8.4],[-6.6,1,7.2],[6.6,1,7.2],[-1.7,1,5.4],[1.7,1,5.4],
        [-9.8,1,6],[9.8,1,6],[-5,1,4.6],[5,1,4.6],[0,1,4.2]],
      camWide:[[0,7.2,29],[0,3.2,-30]],camTall:[[0,8.8,27],[0,-4.7,-8]],
      busy(i,t){const a=t*.3+i*1.3;return new T.Vector3(-34+Math.cos(a)*20,16+Math.sin(a*1.3)*4,-80+Math.sin(a)*20+14)},
      vessel(){const g=new T.Group();
        const body=new T.Mesh(new T.CapsuleGeometry(.6,1.4,6,12),new T.MeshStandardMaterial({color:0xf5f7fb,metalness:.4,roughness:.3}));body.rotation.z=Math.PI/2;g.add(body);
        wlHalo(T,g,new T.Vector3(-1.4,0,0),0x7df9ff,1.8).material.opacity=1;scene.add(g);return g},
      tick(t){ring.rotation.z=t*.04;planet.rotation.y=t*.006;clouds.rotation.y=t*.01;sky.u.time.value=t;
        panels.forEach((m,i)=>m.emissiveIntensity=.55+Math.sin(t*1.7+i)*.25);railM.emissiveIntensity=.8+Math.sin(t*.9)*.2},
      light(d){sun.position.set(Math.cos(d*Math.PI)*60,30,30);amb.intensity=.3+d*.2;WORLD.r.toneMappingExposure=1.05}};
  },
  garden(T,scene,cam){
    WL_MAT={};
    const hq=WORLD.hq,glow={wins:[],lanterns:[],spots:[]},halos=[];
    const props=new T.Group();scene.add(props);
    const sky=wlSky(T,scene,{clouds:.7});
    const hemi=new T.HemisphereLight(0xfff8e1,0x355e3b,.8);scene.add(hemi);
    const sun=new T.DirectionalLight(0xfff1c1,2.2);scene.add(sun);scene.add(sun.target);
    if(hq){sun.castShadow=true;sun.shadow.mapSize.set(1024,1024);const sc=sun.shadow.camera;sc.left=-30;sc.right=30;sc.top=30;sc.bottom=-30;sc.far=160;sun.shadow.bias=-.0015}
    const moon=new T.DirectionalLight(0x9fb4ff,0);moon.position.set(-20,40,20);scene.add(moon);
    const ranges=[wlRange(T,props,-170,9,420,0x6f8f9f,48)];
    const gg=new T.PlaneGeometry(160,120,80,60);gg.rotateX(-Math.PI/2);
    const gp=gg.attributes.position.array;
    for(let i=0;i<gp.length;i+=3){const x=gp[i],z=gp[i+2]-20;gp[i+1]=(z<-38?(Math.sin(x*.07)*2.4+2.6)*Math.min(1,(-38-z)/20):0)+Math.sin(x*.3+z*.2)*.12}
    gg.computeVertexNormals();
    const grassTex=wlCanvasTex(T,'grass',256,256,(g,w)=>{g.fillStyle='#6aa84f';g.fillRect(0,0,w,w);
      for(let i=0;i<900;i++){const l=Math.random();g.fillStyle=l<.5?'rgba(40,90,30,.35)':'rgba(170,215,110,.3)';g.fillRect(Math.random()*w,Math.random()*w,2,3+Math.random()*4)}}).clone();
    grassTex.wrapS=grassTex.wrapT=T.RepeatWrapping;grassTex.repeat.set(26,20);grassTex.needsUpdate=true;
    const ground=new T.Mesh(gg,new T.MeshStandardMaterial({color:0xffffff,map:grassTex,roughness:1}));ground.position.z=-20;ground.receiveShadow=true;scene.add(ground);
    // the pond behind the team, a stone rim, a path from where you stand to its edge
    const pc=[-1,-15];
    const pond=wlWater(T,new T.CircleGeometry(7,48).rotateX(-Math.PI/2),{deep:0x1b6e8a,shallow:0x4fb3c9});pond.mesh.position.set(pc[0],.08,pc[1]);pond.mesh.scale.set(1.6,1,1);scene.add(pond.mesh);
    const rimM=wlMat(T,'rim',{color:0x9a958a,roughness:1,flatShading:true});
    for(let i=0;i<38;i++){const a=i/38*Math.PI*2,st=new T.Mesh(new T.DodecahedronGeometry(.45+((i*7)%3)*.12,0),rimM);st.position.set(pc[0]+Math.cos(a)*11.4,.12,pc[1]+Math.sin(a)*7.3);st.castShadow=true;props.add(st)}
    for(let i=0;i<7;i++){const st=new T.Mesh(new T.CylinderGeometry(.75,.8,.12,10),rimM);st.position.set(Math.sin(i*.9)*.8,.08,16-i*2.4);st.receiveShadow=true;props.add(st)}
    // stone lanterns: two framing the clearing, two by the water
    const lampLights=[];
    [[-15,2],[15,2],[-10,-7],[9,-8]].forEach(([x,z])=>{const g=new T.Group();
      const base=new T.Mesh(new T.CylinderGeometry(.3,.45,1.2,6),rimM);base.position.y=.6;g.add(base);
      const lm=wlMat(T,'stonelamp',{color:0xd8d2c4,emissive:0xffc26b,emissiveIntensity:.1});const box=new T.Mesh(new T.BoxGeometry(.7,.6,.7),lm);box.position.y=1.5;g.add(box);
      if(glow.lanterns.indexOf(lm)<0)glow.lanterns.push(lm);
      const cap=new T.Mesh(new T.ConeGeometry(.75,.5,6),rimM);cap.position.y=2.05;g.add(cap);g.position.set(x,0,z);g.traverse(o=>{if(o.isMesh)o.castShadow=true});props.add(g);
      wlHalo(T,scene,new T.Vector3(x,1.5,z),0xffc26b,2.6,halos);lampLights.push({pos:new T.Vector3(x,1.5,z),color:0xffb45a})});
    pond.setLights(lampLights);
    [[-20,-10,'s'],[-14,-26,'t'],[14,-24,'t'],[22,-12,'s'],[-24,0,'w'],[23,1,'t'],[3,-32,'t'],[-5,-34,'s'],[-30,-16,'t'],[30,-20,'s']].forEach(([x,z,t],i)=>{
      let tr;if(t==='w')tr=wlWillow(T);else if(t==='s')tr=wlSakura(T);else{tr=new T.Group();
        const tk=new T.Mesh(new T.CylinderGeometry(.3,.45,3.2,7),wlMat(T,'oakbark',{color:0x6b4423,roughness:1}));tk.position.y=1.6;tr.add(tk);
        [[0,4.6,0,2.4],[1.2,4,.6,1.6],[-1.1,4.1,-.4,1.7]].forEach(([a,b,c,r])=>{const m=new T.Mesh(new T.IcosahedronGeometry(r,1),wlMat(T,'leaf'+(i%2),{color:i%2?0x3f8a3a:0x4f9f45,flatShading:true}));m.position.set(a,b,c);tr.add(m)});
        tr.traverse(o=>{if(o.isMesh)o.castShadow=true})}
      tr.position.set(x,0,z);props.add(tr)});
    wlBake(T,props);
    const flowers=new T.Group();scene.add(flowers);
    const petals=[0xf368e0,0xffd32a,0xff6b6b,0xffffff,0x9b59b6,0xff9f43];let shown=-1;
    const fg=new T.SphereGeometry(.2,6,5),stemG=new T.CylinderGeometry(.03,.03,.5,4),stemM=wlMat(T,'stem',{color:0x3f7d3a});
    const flies=wlStars(T,scene,hq?80:30,[-20,20,.6,4,-20,14],0xfff27a,.35);
    const butterflies=wlPetals(T,scene,hq?60:24,[-18,18,.5,5,-18,14]);butterflies.pts.material.map=wlFxTex(T,'star');butterflies.pts.material.color=new T.Color(0xffe08a);
    return {
      spots:[[0,0,6.8],[-3.3,0,6],[3.3,0,6],[-6.6,0,4.8],[6.6,0,4.8],[-1.7,0,3],[1.7,0,3],
        [-9.8,0,3.6],[9.8,0,3.6],[-5,0,2],[5,0,2],[0,0,1.4]],
      camWide:[[0,7.4,27],[0,1.8,-30]],camTall:[[0,8.4,23],[0,-6.2,-12]],
      busy(i,t){return new T.Vector3(-13+(i%5)*6.5+Math.sin(t*.5+i)*1.2,0,-5.4-(i%2)*1.2)},
      vessel(){return null},
      // the garden grows with the whole team: more of the ladder climbed, more blooms,
      // in beds around the pond and along the sides, never where anybody stands
      grow(total){const n=Math.min(240,30+Math.floor(total/2));if(n===shown)return;shown=n;
        while(flowers.children.length){const c=flowers.children[0];flowers.remove(c);c.geometry.dispose()}
        const g=new T.Group();
        for(let k=0;k<n;k++){const a=k*2.399,r=4+Math.sqrt(k)*1.5,x=pc[0]+Math.cos(a)*r*2.2,z=pc[1]+Math.sin(a)*r*1.3;
          if(Math.hypot((x-pc[0])/12.4,(z-pc[1])/8.2)<1||z>12||(z>-1.5&&Math.abs(x)<12.5)||Math.abs(x)<1.6)continue;
          const col=petals[k%petals.length];
          const f=new T.Mesh(fg,wlMat(T,'flower'+col,{color:col,roughness:.6,emissive:col,emissiveIntensity:.05}));f.position.set(x,.55,z);g.add(f);
          const st=new T.Mesh(stemG,stemM);st.position.set(x,.25,z);g.add(st)}
        wlBake(T,g);while(g.children.length){const c=g.children[0];g.remove(c);flowers.add(c)}},
      tick(t,dt){sky.u.time.value=t;pond.light(t,this._d||1,this._c||wlSkyColors(T,1),this._sd||new T.Vector3(0,1,0));butterflies.tick(dt*.3,t)},
      light(d){const c=wlSkyColors(T,d);this._d=d;this._c=c;
        sky.u.top.value.copy(c.top);sky.u.horizon.value.copy(c.horizon);const night=1-Math.min(1,d*2.4);sky.u.night.value=night;
        const sd=worldSunDir(T);this._sd=sd;sky.u.sunDir.value.copy(sd);sun.position.copy(sd).multiplyScalar(80);
        wlFog(T,scene,c.fog,60,220);sun.intensity=d*2.4;hemi.intensity=.35+d*.6;moon.intensity=night*.9;
        glow.lanterns.forEach(m=>m.emissiveIntensity=.1+night*2.2);halos.forEach(h=>h.material.opacity=night);
        ranges[0].color.set(worldMix(T,0x1d2640,0x86a0ae,d*1.6));flies.material.opacity=night;butterflies.pts.material.opacity=Math.min(1,d*3);
        WORLD.r.toneMappingExposure=.95+night*.35}};
  }
};
