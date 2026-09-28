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
     vermilion bridge, a pagoda, willows and cherry trees; a moon base under a
     blue planet; a garden with a pond, stone lanterns and flowers);
   - light that glows: halos on every lamp and window, bloom-free and cheap;
   - people who stand somewhere, not in a line: each has a spot, a soft shadow, and
     a mood crystal over the head, green to red by how the feeling sits, spinning.
     And each feeling has its own effect: steam for a tantrum, a rain cloud for
     gloom, Zs for dozing, hearts, sparkles, a sweat drop.
   Quality: shadows and the petal/firefly counts follow WORLD.hq, decided once per
   build from the renderer (software rendering and phones get the light version).
   Every effect is caused by a feeling the server worked out; nothing here invents
   one. */

/* ---------------- the scene a person designed ----------------
   world.py SCENE and PROPS: every field is one of a closed set, and the machine's brain
   picks them from the person's words (there is no picker, on purpose: the owner asked for
   the AI to design it). The kits read the choices through these helpers. */
function wlScene(){return (WORLD.v&&WORLD.v.world&&WORLD.v.world.scene)||{}}
function wlHas(p){const s=wlScene().props;return !s||s.indexOf(p)>=0}
var WL_SKY_TINT={rose:0xff7aa2,violet:0x8a6cff,teal:0x3fd0c4,gold:0xffc75a,storm:0x5a6472};
var WL_WATER={teal:[0x0f6f73,0x2fb6a8],blue:[0x145e8a,0x3f9fcc],jade:[0x1d6b4f,0x49a87a],violet:[0x3b2a78,0x7a5cc9],amber:[0x6b4a1a,0xc9983f],ink:[0x0a1422,0x23364d]};
var WL_GROUND={sand:0xd8c08a,snow:0xeef2f8,moss:0x5f8a3a,rust:0xa0583a,ash:0x6a6a72};
var WL_ACCENT={red:0xe74c3c,amber:0xffb347,gold:0xf2c94c,blue:0x4aa3ff,violet:0xa77bff,green:0x4cd48a,white:0xfff1d6};
var WL_CLOUDS={clear:.12,clouds:.9,rain:1,snow:.8,petals:.55,fireflies:.45};
function wlAccent(){return WL_ACCENT[wlScene().accent]||WL_ACCENT.red}
function wlWaterCols(){return WL_WATER[wlScene().water]||WL_WATER.teal}
function wlGround(nat){return WL_GROUND[wlScene().ground]||nat}
/* a surface that is not the ground itself (paving) takes a little of the ground's colour */
function wlGroundMix(T,nat,k){const g=WL_GROUND[wlScene().ground];return g?new T.Color(nat).lerp(new T.Color(g),k).getHex():nat}
function wlCloudAmt(def){const w=wlScene().weather;return w in WL_CLOUDS?WL_CLOUDS[w]:def}
/* the hour the scene shows: the real one, or the time of day it was designed at */
function worldHour(){const t=wlScene().time,fixed={dawn:6.9,day:12.5,dusk:17.2,night:0};
  if(t&&t in fixed)return fixed[t];const d=new Date();return d.getHours()+d.getMinutes()/60}

/* ---------------- shared pieces ---------------- */
function worldDaylight(){
  const h=worldHour();
  return Math.max(0,Math.sin((h-6)/12*Math.PI));
}
/* the sun's direction for the hour: east in the morning, high at noon, set by 18:00 */
function worldSunDir(T){
  const h=worldHour(),a=(h-6)/12*Math.PI;
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
  const c={top:worldMix(T,0x070b22,day>.38?0x3f8fe0:0x4a5fa8,day*1.9),
    horizon:worldMix(T,0x1a2446,dusk?(warm||0xffa36b):0xcfe6ff,Math.min(1,day*2.4)),
    fog:worldMix(T,0x131b3a,dusk?0xe8a882:0xcfe3f5,Math.min(1,day*2.2))};
  // the designed sky: a tint (quieter at night), rain greys it, snow pales the horizon
  const sc=wlScene(),lit=.35+.65*Math.min(1,day*2);
  const tn=WL_SKY_TINT[sc.sky]||(sc.weather==='rain'?WL_SKY_TINT.storm:0);
  if(tn){const col=new T.Color(tn),k=(sc.sky==='storm'||!WL_SKY_TINT[sc.sky]?.5:.36)*lit;
    c.top.lerp(col,k*.8);c.horizon.lerp(col,k);c.fog.lerp(col,k*.7)}
  if(sc.weather==='snow'){const w=new T.Color(0xe8eef6);c.horizon.lerp(w,.25*lit);c.fog.lerp(w,.3*lit)}
  return c;
}
/* Weather is particles over the place: rain or snow falling, petals drifting, fireflies
   at night. What the scene says, over the box the camera sees; clear is nothing. */
function wlWeather(T,scene,box){
  const w=wlScene().weather,hq=WORLD.hq;
  if(w==='petals'){const p=wlPetals(T,scene,hq?220:80,box);
    return {tick:(dt,t)=>p.tick(dt,t),light(d){p.pts.material.opacity=Math.min(1,.35+d*3)}}}
  if(w==='fireflies'){const f=wlStars(T,scene,hq?90:40,[box[0],box[1],box[2],Math.min(box[3],box[2]+3.5),box[4],box[5]],0xfff27a,.35);
    return {tick(dt,t){f.position.y=Math.sin(t*.7)*.15},light(d){f.material.opacity=1-Math.min(1,d*2.4)}}}
  if(w==='rain'||w==='snow'){
    const rain=w==='rain',n=rain?(hq?1500:600):(hq?700:280),top=box[3]+6;
    const g=new T.BufferGeometry(),p=new Float32Array(n*3);
    for(let i=0;i<n;i++){p[i*3]=box[0]+Math.random()*(box[1]-box[0]);p[i*3+1]=box[2]+Math.random()*(top-box[2]);p[i*3+2]=box[4]+Math.random()*(box[5]-box[4])}
    g.setAttribute('position',new T.BufferAttribute(p,3));
    const m=new T.PointsMaterial({size:rain?.45:.28,map:rain?wlFxTex(T,'rain'):wlGlowTex(T),color:rain?0xb8d4f0:0xffffff,
      transparent:true,depthWrite:false,opacity:rain?.55:.9});
    const pts=new T.Points(g,m);pts.frustumCulled=false;scene.add(pts);
    return {tick(dt,t){const a=g.attributes.position.array;
        for(let i=0;i<n;i++){a[i*3+1]-=dt*(rain?16:1.4+(i%5)*.12);if(!rain)a[i*3]+=Math.sin(t*.9+i)*dt*.35;
          if(a[i*3+1]<box[2]){a[i*3+1]=top;a[i*3]=box[0]+Math.random()*(box[1]-box[0])}}
        g.attributes.position.needsUpdate=true},
      light(d){m.opacity=rain?.35+d*.3:.95}};
  }
  return {tick(){},light(){}};
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
  const acc=wlAccent(),lanternM=wlMat(T,'doorlantern',{color:acc,emissive:acc,emissiveIntensity:.2});
  const lan=new T.Mesh(new T.CylinderGeometry(.16,.16,.34,10),lanternM);lan.position.set(w*.36,h*.46,d/2+.28);g.add(lan);
  g.traverse(o=>{if(o.isMesh){o.castShadow=true;o.receiveShadow=true}});
  if(glow){if(glow.wins.indexOf(wm)<0)glow.wins.push(wm);if(glow.lanterns.indexOf(lanternM)<0)glow.lanterns.push(lanternM);glow.spots.push({obj:win,color:0xffb24d,size:2.6},{obj:lan,color:acc,size:1.8})}
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
  const a0=wlAccent(),cols=[a0,0xfff1d6,new T.Color(a0).lerp(new T.Color(0xffd27a),.5).getHex()];
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

/* A small shuttle: a white body, swept wings, a cockpit and an engine glow. */
function wlShuttle(T){
  const g=new T.Group(),white=wlMat(T,'shuttle',{color:0xf2f4f8,roughness:.45,metalness:.2}),dark=wlMat(T,'shuttledark',{color:0x2a3446,metalness:.5,roughness:.3});
  const body=new T.Mesh(new T.CapsuleGeometry(.55,2.2,6,12),white);body.rotation.z=Math.PI/2;g.add(body);
  const nose=new T.Mesh(new T.SphereGeometry(.42,10,8),dark);nose.scale.set(1,.7,1);nose.position.set(1.2,.3,0);g.add(nose);
  const wing=new T.Mesh(new T.BoxGeometry(1.5,.08,3.4),white);wing.position.set(-.4,-.15,0);g.add(wing);
  const fin=new T.Mesh(new T.BoxGeometry(.9,.9,.08),white);fin.position.set(-1.2,.55,0);g.add(fin);
  const tip=wlMat(T,'shuttletip',{color:0xd9482b});[-1.7,1.7].forEach(z=>{const t=new T.Mesh(new T.BoxGeometry(.6,.1,.1),tip);t.position.set(-.5,-.15,z);g.add(t)});
  wlHalo(T,g,new T.Vector3(-1.75,0,0),0x7fd8ff,1.6).material.opacity=1;
  g.traverse(o=>{if(o.isMesh)o.castShadow=true});
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
    const sky=wlSky(T,scene,{clouds:wlCloudAmt(.8)});
    const hemi=new T.HemisphereLight(0xdfefff,0x3b4a3a,.7);scene.add(hemi);
    const sun=new T.DirectionalLight(0xfff1d6,2.2);scene.add(sun);scene.add(sun.target);
    if(hq){sun.castShadow=true;sun.shadow.mapSize.set(1024,1024);const sc=sun.shadow.camera;sc.left=-26;sc.right=26;sc.top=26;sc.bottom=-26;sc.near=1;sc.far=160;sun.shadow.bias=-.0015}
    const moon=new T.DirectionalLight(0x8fa8ff,0);moon.position.set(20,40,20);scene.add(moon);
    const ranges=[wlRange(T,town,-190,9,420,0x5f7d8f,60),wlRange(T,town,-140,8,320,0x557060,38)];
    // the canal runs away from you, a town on each bank; the team stands on a stone
    // landing at its head, where you are
    const water=wlWater(T,new T.PlaneGeometry(10,236,20,120).rotateX(-Math.PI/2),{edgeX:5,deep:wlWaterCols()[0],shallow:wlWaterCols()[1]});water.mesh.position.set(0,0,-115);scene.add(water.mesh);
    const stone=0x8e8a80;
    [-1,1].forEach(s=>{
      const wall=worldBox(T,1.2,1.9,236,stone,{roughness:.95});wall.position.set(s*5.6,.35,-115);wall.receiveShadow=true;town.add(wall);
      const walk=new T.Mesh(new T.BoxGeometry(6,.3,236),wlMat(T,'walk',{color:wlGroundMix(T,0xe0d4bc,.45),map:wlPaving(T,1.5,59),roughness:1}));walk.position.set(s*9,1.15,-115);walk.receiveShadow=true;town.add(walk);
      const grass=worldBox(T,40,.3,236,wlGround(0x6f9a55),{roughness:1});grass.position.set(s*32,1.1,-115);grass.receiveShadow=true;town.add(grass);
    });
    const landing=new T.Mesh(new T.BoxGeometry(36,1.9,14),new T.MeshStandardMaterial({color:wlGroundMix(T,0xd6cfc2,.4),map:wlPaving(T,9,3.5),roughness:.95}));
    landing.position.set(0,.37,10);landing.receiveShadow=true;town.add(landing);
    const lawn=worldBox(T,120,.3,40,wlGround(0x5f8a4a),{roughness:1});lawn.position.set(0,1.1,30);lawn.receiveShadow=true;town.add(lawn);
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
    if(wlHas('houses'))for(let z=0;z>-150;z-=5.2+((k*7)%3)){
      [-1,1].forEach(s=>{k++;
        if((k*5)%11===0)return;               // a gap, for a tree or a lane
        const w=4+((k*3)%3)*.7,h=3.4+((k*5)%4)*.55;
        const hs=wlMachiya(T,w,h,k,glow);hs.position.set(s*(14.5+((k*11)%3)*.6),1.3,z);hs.rotation.y=s<0?Math.PI/2:-Math.PI/2;town.add(hs);
      });
    }
    if(wlHas('pagoda')){const pagoda=wlPagoda(T,glow);pagoda.position.set(19,1.3,-58);town.add(pagoda)}
    // the vermilion bridge: a deck on an arch, railings and posts
    const red=wlMat(T,'bridgered',{color:0xc0392b,roughness:.55}),deckM=wlMat(T,'bridgedeck',{color:0x7a2a20,roughness:.8});
    const bz=-26,seg=wlHas('bridge')?18:0;
    for(let i=0;i<seg;i++){const x0=-7.5+i*15/seg,x1=x0+15/seg,xm=(x0+x1)/2,y=v=>1.3+2.3*Math.cos(v/7.5*Math.PI/2);
      const ang=Math.atan2(y(x1)-y(x0),x1-x0);
      const d=new T.Mesh(new T.BoxGeometry(15/seg+.05,.22,2.6),deckM);d.position.set(xm,y(xm),bz);d.rotation.z=ang;d.castShadow=true;town.add(d);
      [-1.25,1.25].forEach(zz=>{const r=new T.Mesh(new T.BoxGeometry(15/seg+.05,.1,.1),red);r.position.set(xm,y(xm)+.85,bz+zz);r.rotation.z=ang;town.add(r);
        if(i%3===0){const p=new T.Mesh(new T.BoxGeometry(.12,.9,.12),red);p.position.set(x0,y(x0)+.42,bz+zz);town.add(p)}});}
    if(seg)[-1,1].forEach(s=>{const pier=worldBox(T,.7,2.4,2.8,0x6e6a62);pier.position.set(s*6.6,.2,bz);town.add(pier)});
    // lantern strings across the water, lamps along both quays
    if(wlHas('lanterns'))[-8,-44,-78].forEach(z=>wlLanternString(T,scene,new T.Vector3(-9,6.6,z),new T.Vector3(9,6.6,z),8,glow,halos,town));
    const poleM=wlMat(T,'pole',{color:0x3a2c22}),lampM=wlMat(T,'lamp',{color:0xfff1d6,emissive:0xffc26b,emissiveIntensity:.2});
    glow.lanterns.push(lampM);
    for(let z=-2;z>-120;z-=12){[-1,1].forEach(s=>{
      const p=new T.Mesh(new T.CylinderGeometry(.07,.09,3,6),poleM);p.position.set(s*6.7,2.7,z);town.add(p);
      const lamp=new T.Mesh(new T.BoxGeometry(.38,.5,.38),lampM);lamp.position.set(s*6.7,4.35,z);town.add(lamp);
      wlHalo(T,scene,lamp.position,0xffc26b,2.4,halos);
      if(lampLights.length<8)lampLights.push({pos:new T.Vector3(s*6.7,4.35,z),color:0xffb45a});})}
    water.setLights(lampLights);
    // trees: willows by the water, cherry blossom between the houses, two at the landing
    if(wlHas('trees'))[[-18,6,'w'],[18.5,4,'s'],[8.8,-14,'w'],[-9,-40,'w'],[-9.2,-20,'s'],[9.3,-50,'s'],[-8.8,-70,'w'],[9,-86,'w']].forEach(([x,z,t])=>{
      const tr=t==='w'?wlWillow(T):wlSakura(T);tr.position.set(x,1.3,z);town.add(tr)});
    // moored boats: scenery, like the houses; they do not move
    if(wlHas('boats'))[[3.2,-6,.1],[-3.3,-18,-.08],[3,-52,.05]].forEach(([x,z,r])=>{const b=wlBoat(T);b.position.set(x,.15,z);b.rotation.y=Math.PI/2+r;town.add(b)});
    // every lit window and door lantern gets a halo, as far as the eye reads them
    town.updateMatrixWorld(true);
    const winHalos=[];
    glow.spots.forEach(sp=>{const p=new T.Vector3();sp.obj.getWorldPosition(p);if(p.z>-100)wlHalo(T,scene,p,sp.color,sp.size,winHalos)});
    wlBake(T,town);
    const wx=wlWeather(T,scene,[-18,18,1.5,11,-40,20]);
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
      wx.light(d);
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
      tick(t,dt){water.light(t,lit?lit.d:1,lit?lit.c:wlSkyColors(T,1),lit?lit.sd:new T.Vector3(0,1,0),true);sky.u.time.value=t;wx.tick(dt,t)},
      light(d){const r=light(d);lit={d,c:r.c,sd:r.sd};water.light(sky.u.time.value,d,r.c,r.sd,true)}};
  },
  /* Kestrel Station is a moon base under a blue planet: habitat domes, a comms tower,
     solar arrays, a radar dish and a rover, and the crew on the landing pad. The first
     cut was a ring wheel over a checkered deck, and read as neither a place nor a
     station. Outdoors, like the other two worlds, so the camera and spots work alike. */
  orbit(T,scene,cam){
    WL_MAT={};
    const hq=WORLD.hq,halos=[],beacons=[],padLights=[];
    const base=new T.Group();scene.add(base);
    const sky=wlSky(T,scene,{clouds:0,nebula:true});
    sky.u.top.value.set(0x010208);sky.u.horizon.value.set(0x0b1024);sky.u.night.value=1;
    const tint=WL_SKY_TINT[wlScene().sky];
    if(tint){sky.u.top.value.lerp(new T.Color(tint),.12);sky.u.horizon.value.lerp(new T.Color(tint),.3)}
    sky.u.sunDir.value.set(.7,.35,.3).normalize();
    const hemi=new T.HemisphereLight(0x7f96d8,0x26262c,.55);scene.add(hemi);   // planetshine
    const sun=new T.DirectionalLight(0xfff6ea,2.3);sun.position.set(70,45,40);scene.add(sun);scene.add(sun.target);sun.target.position.set(0,0,-6);
    if(hq){sun.castShadow=true;sun.shadow.mapSize.set(1024,1024);const sc=sun.shadow.camera;sc.left=-40;sc.right=40;sc.top=40;sc.bottom=-40;sc.near=1;sc.far=200;sun.shadow.bias=-.0015}
    // the planet, big and low in the black sky, lit from the side, with an atmosphere rim
    // the planet's seas take the scene's water colour
    const seas=wlScene().water&&wlScene().water!=='blue'?new T.Color(0xffffff).lerp(new T.Color(wlWaterCols()[1]),.6):new T.Color(0xffffff);
    const planet=new T.Mesh(new T.SphereGeometry(70,48,32),new T.MeshStandardMaterial({color:seas,roughness:.9,
      map:wlCanvasTex(T,'land',512,256,(g,w,h)=>{g.fillStyle='#285fb4';g.fillRect(0,0,w,h);
        for(let i=0;i<80;i++){g.fillStyle=['#4d7a55','#6f8a5c','#a8997a','#5a7550'][i%4];g.beginPath();g.ellipse(Math.random()*w,h*.12+Math.random()*h*.76,6+Math.random()*34,4+Math.random()*16,Math.random()*3,0,7);g.fill()}
        g.fillStyle='#eef4ff';g.fillRect(0,0,w,h*.07);g.fillRect(0,h*.93,w,h*.07)})}));
    planet.position.set(-165,78,-360);planet.rotation.z=.35;scene.add(planet);
    const clouds=new T.Mesh(new T.SphereGeometry(70.8,48,32),new T.MeshStandardMaterial({color:0xffffff,transparent:true,opacity:.55,roughness:1,depthWrite:false,
      alphaMap:wlCanvasTex(T,'pclouds',256,128,(g,w,h)=>{g.fillStyle='#000';g.fillRect(0,0,w,h);for(let i=0;i<160;i++){g.fillStyle=`rgba(255,255,255,${.2+Math.random()*.45})`;g.beginPath();g.ellipse(Math.random()*w,Math.random()*h,8+Math.random()*30,3+Math.random()*6,0,0,7);g.fill()}})}));
    clouds.position.copy(planet.position);clouds.rotation.z=.35;scene.add(clouds);
    const atmos=new T.Mesh(new T.SphereGeometry(76,48,32),new T.ShaderMaterial({transparent:true,depthWrite:false,side:T.BackSide,blending:T.AdditiveBlending,
      uniforms:{c:{value:new T.Color(0x5fa8ff)}},
      vertexShader:`varying vec3 vN;void main(){vN=normalize(normalMatrix*normal);gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`,
      fragmentShader:`uniform vec3 c;varying vec3 vN;void main(){float i=pow(max(0.,.78-dot(vN,vec3(0.,0.,-1.))),3.)*1.6;gl_FragColor=vec4(c*i,1.);}`}));
    atmos.position.copy(planet.position);scene.add(atmos);
    // the ground: grey regolith with craters, rising to far ridges
    const craters=[[-30,-40,9,1.6],[26,-50,12,2],[-8,-70,7,1.2],[40,-20,6,1],[-44,-8,7,1.3],[14,-34,4,.7],[-22,-58,5,.9],[52,-44,9,1.6],[-58,-36,10,1.8],[30,18,5,.8],[-34,16,6,1]];
    const gg=new T.PlaneGeometry(280,220,96,76);gg.rotateX(-Math.PI/2);
    const gp=gg.attributes.position.array;
    for(let i=0;i<gp.length;i+=3){const x=gp[i],z=gp[i+2]-30;let h=Math.sin(x*.11)*.35+Math.cos(z*.13+x*.05)*.3;
      craters.forEach(([cx,cz,r,d])=>{const q=Math.hypot(x-cx,z-cz)/r;if(q<1)h-=d*(1-q*q);else if(q<1.5)h+=d*.4*(1-Math.abs(q-1.15)/.35)*(q<1.5?1:0)});
      if(z<-80)h+=(-80-z)*.22*(1+.5*Math.sin(x*.05));
      if(Math.hypot(x,z-8)<18||(Math.abs(x)<30&&z<-8&&z>-58))h*=.15;     // the base sits on levelled ground
      gp[i+1]=h}
    gg.computeVertexNormals();
    const regTex=wlCanvasTex(T,'regolith',256,256,(g,w)=>{g.fillStyle='#77777c';g.fillRect(0,0,w,w);
      for(let i=0;i<1400;i++){const l=Math.random();g.fillStyle=l<.5?'rgba(40,40,48,.22)':'rgba(235,235,240,.18)';g.fillRect(Math.random()*w,Math.random()*w,1+Math.random()*2,1+Math.random()*2)}
      for(let i=0;i<14;i++){const x=Math.random()*w,y=Math.random()*w,r=3+Math.random()*9;g.strokeStyle='rgba(30,30,36,.35)';g.lineWidth=1.5;g.beginPath();g.arc(x,y,r,0,7);g.stroke();g.strokeStyle='rgba(240,240,245,.25)';g.beginPath();g.arc(x+1,y-1,r,3.6,5.6);g.stroke()}}).clone();
    regTex.wrapS=regTex.wrapT=T.RepeatWrapping;regTex.repeat.set(34,27);regTex.needsUpdate=true;
    const ground=new T.Mesh(gg,new T.MeshStandardMaterial({color:wlGround(0xb4b4ba),map:regTex,roughness:1,flatShading:true}));ground.position.z=-30;ground.receiveShadow=true;scene.add(ground);
    const ridge=wlRange(T,base,-200,11,520,0x5c5c63,34);
    // the landing pad the crew stands on: a hexagon with its markings and chasing edge lights
    const padTop=wlCanvasTex(T,'pad',512,512,(g,w)=>{g.fillStyle='#3a3e46';g.fillRect(0,0,w,w);
      g.strokeStyle='#2b2f36';g.lineWidth=3;for(let i=0;i<=8;i++){g.beginPath();g.moveTo(i*64,0);g.lineTo(i*64,w);g.stroke();g.beginPath();g.moveTo(0,i*64);g.lineTo(w,i*64);g.stroke()}
      g.strokeStyle='#f2c230';g.lineWidth=14;g.beginPath();g.arc(w/2,w/2,200,0,7);g.stroke();
      g.strokeStyle='#e8ecf2';g.lineWidth=5;g.beginPath();g.arc(w/2,w/2,150,0,7);g.stroke();
      g.fillStyle='rgba(232,236,242,.85)';g.font='bold 170px sans-serif';g.textAlign='center';g.textBaseline='middle';g.fillText('K',w/2,w/2+8)});
    const padSide=wlMat(T,'padside',{color:0x5a5f68,metalness:.4,roughness:.6});
    const pad=new T.Mesh(new T.CylinderGeometry(16,16.6,.6,6),[padSide,new T.MeshStandardMaterial({color:0xffffff,map:padTop,roughness:.7,metalness:.2}),padSide]);
    pad.rotation.y=Math.PI/6;pad.position.set(0,.2,8);pad.receiveShadow=true;scene.add(pad);
    for(let k=0;k<18;k++){const a=Math.PI/6+k/18*Math.PI*2,r=15.4*Math.cos(Math.PI/6)/Math.cos(((a-Math.PI/6)%(Math.PI/3))-Math.PI/6);
      const p=new T.Vector3(Math.sin(a)*r,.62,8+Math.cos(a)*r);
      const m=new T.MeshStandardMaterial({color:0x223,emissive:wlAccent(),emissiveIntensity:1});const l=new T.Mesh(new T.SphereGeometry(.13,8,6),m);l.position.copy(p);scene.add(l);
      padLights.push({m,h:wlHalo(T,scene,p,wlAccent(),1.1)})}
    // habitat domes joined by tubes, their window bands lit from inside
    const shell=wlMat(T,'shell',{color:0xe7eaf0,roughness:.55,metalness:.15,flatShading:true});
    const ringM=wlMat(T,'domering',{color:0x8c929c,metalness:.5,roughness:.4});
    const winM=wlMat(T,'domewin',{color:0x111,emissive:0xffd9a0,emissiveIntensity:1.4});
    const domes=wlHas('domes')?[[-24,-28,5],[3,-42,7.5],[25,-32,4.5]]:[];
    domes.forEach(([x,z,r])=>{
      const d=new T.Mesh(new T.SphereGeometry(r,18,8,0,Math.PI*2,0,Math.PI/2),shell);d.position.set(x,1.1,z);d.castShadow=true;base.add(d);
      const ring=new T.Mesh(new T.CylinderGeometry(r*1.02,r*1.06,1.2,24),ringM);ring.position.set(x,.6,z);base.add(ring);
      for(let k=0;k<10;k++){const a=k/10*Math.PI*2;const w=new T.Mesh(new T.BoxGeometry(r*.28,.35,.1),winM);
        w.position.set(x+Math.sin(a)*r*1.035,.7,z+Math.cos(a)*r*1.035);w.rotation.y=a;base.add(w);
        if(Math.cos(a)>.3)halos.push(wlHalo(T,scene,w.position.clone().add(new T.Vector3(0,0,.3)),0xffc986,1.6))}
      const hatch=new T.Mesh(new T.CylinderGeometry(.9,.9,.4,12),ringM);hatch.position.set(x,1.1+r,z);base.add(hatch)});
    const tube=(a,b)=>{const A=new T.Vector3(a[0],1.3,a[1]),B=new T.Vector3(b[0],1.3,b[1]),len=A.distanceTo(B);
      const t=new T.Mesh(new T.CylinderGeometry(1,1,len,12),shell);t.position.copy(A).lerp(B,.5);t.lookAt(B);t.rotateX(Math.PI/2);t.castShadow=true;base.add(t)};
    if(domes.length){tube([-24,-28],[3,-42]);tube([3,-42],[25,-32])}
    // the comms tower, a lattice with a red beacon on top
    const steel=wlMat(T,'steel',{color:0xb8bec8,metalness:.6,roughness:.35});
    const tx=20,tz=-52,th=18;
    if(wlHas('tower')){
    [[-1,-1],[1,-1],[1,1],[-1,1]].forEach(([sx,sz])=>{const l=new T.Mesh(new T.CylinderGeometry(.08,.14,th,6),steel);
      l.position.set(tx+sx*.7,th/2,tz+sz*.7);l.rotation.set(-sz*.035,0,sx*.035);base.add(l)});
    for(let y=2;y<th;y+=2.2){const w=.7*(1-y/th*.5);[[0,w],[0,-w]].forEach(([dx,dz])=>{const b=new T.Mesh(new T.BoxGeometry(w*2,.06,.06),steel);b.position.set(tx+dx,y,tz+dz);base.add(b)});
      [[w,0],[-w,0]].forEach(([dx,dz])=>{const b=new T.Mesh(new T.BoxGeometry(.06,.06,w*2),steel);b.position.set(tx+dx,y,tz+dz);base.add(b)})}
    const bm=new T.MeshStandardMaterial({color:0x300,emissive:0xff3b30,emissiveIntensity:2});const bl=new T.Mesh(new T.SphereGeometry(.28,10,8),bm);bl.position.set(tx,th+.3,tz);scene.add(bl);
    beacons.push({m:bm,h:wlHalo(T,scene,bl.position,0xff4a3d,5),ph:0});
    }
    // the radar dish, slowly turning
    const dish=new T.Group();dish.position.set(40,0,-44);if(wlHas('dish'))scene.add(dish);
    const ped=new T.Mesh(new T.CylinderGeometry(.5,.8,4,10),steel);ped.position.y=2;dish.add(ped);
    const bowl=new T.Mesh(new T.SphereGeometry(4,24,10,0,Math.PI*2,0,Math.PI*.3),new T.MeshStandardMaterial({color:0xe9ecf1,side:T.DoubleSide,roughness:.4,metalness:.3}));
    bowl.rotation.x=-Math.PI*.62;bowl.position.set(0,5.4,0);bowl.castShadow=true;dish.add(bowl);
    const horn=new T.Mesh(new T.CylinderGeometry(.06,.06,3,6),steel);horn.position.set(0,6.4,1.6);horn.rotation.x=.9;dish.add(horn);
    // solar arrays in rows
    const cells=wlCanvasTex(T,'cells',128,64,(g,w,h)=>{g.fillStyle='#16244a';g.fillRect(0,0,w,h);g.strokeStyle='#5d7fc4';g.lineWidth=1;
      for(let i=0;i<=8;i++){g.beginPath();g.moveTo(i*16,0);g.lineTo(i*16,h);g.stroke()}for(let i=0;i<=4;i++){g.beginPath();g.moveTo(0,i*16);g.lineTo(w,i*16);g.stroke()}});
    const cellM=wlMat(T,'cellsm',{color:0xffffff,map:cells,metalness:.6,roughness:.25});
    if(wlHas('solar'))[[-52,-40],[-44,-40],[-36,-40],[-52,-48],[-44,-48],[-36,-48],[38,-14],[46,-14],[38,-6],[46,-6]].forEach(([x,z])=>{
      const p=new T.Mesh(new T.BoxGeometry(6.4,.12,3.2),cellM);p.position.set(x,2.2,z);p.rotation.x=-.55;p.castShadow=true;base.add(p);
      const leg=new T.Mesh(new T.CylinderGeometry(.08,.08,2.2,6),steel);leg.position.set(x,1.1,z);base.add(leg)});
    // a rover parked by the pad, and a shuttle on the small pad behind
    const rover=new T.Group();rover.position.set(20,0,9);rover.rotation.y=-.5;
    const body=new T.Mesh(new T.BoxGeometry(4.2,1,2.2),wlMat(T,'roverbody',{color:0xf0f0f2,roughness:.5}));body.position.y=1.2;rover.add(body);
    const cab=new T.Mesh(new T.BoxGeometry(1.8,.9,2),wlMat(T,'rovercab',{color:0x2a3a52,metalness:.5,roughness:.2}));cab.position.set(.9,2.1,0);rover.add(cab);
    const stripe=new T.Mesh(new T.BoxGeometry(4.25,.18,2.25),wlMat(T,'roverstripe',{color:0xf08a24}));stripe.position.y=1.35;rover.add(stripe);
    [-1.5,0,1.5].forEach(x=>[-1.2,1.2].forEach(z=>{const w=new T.Mesh(new T.CylinderGeometry(.55,.55,.4,12),wlMat(T,'tyre',{color:0x2b2b30,roughness:.9}));w.rotation.x=Math.PI/2;w.position.set(x,.55,z);rover.add(w)}));
    const ant=new T.Mesh(new T.CylinderGeometry(.03,.03,1.8,4),steel);ant.position.set(-1.6,2.5,.7);rover.add(ant);
    if(wlHas('rover'))base.add(rover);
    if(wlHas('shuttle')){const pad2=new T.Mesh(new T.CylinderGeometry(5,5.3,.4,6),padSide);pad2.position.set(-30,.2,-10);base.add(pad2);
      const parked=wlShuttle(T);parked.position.set(-30,1.5,-10);parked.rotation.y=.7;base.add(parked)}
    // crates and lamp posts along the walk to the main dome
    const crateM=wlMat(T,'crate',{color:0x7c8594,metalness:.3,roughness:.6});
    [[-10,-10,0],[-11.6,-10.4,0],[-10.8,-9.8,1.1],[12,-12,0]].forEach(([x,z,y])=>{const c=new T.Mesh(new T.BoxGeometry(1.4,1.1,1.4),crateM);c.position.set(x,.55+y,z);c.rotation.y=x;c.castShadow=true;base.add(c)});
    wlBake(T,base);
    const dust=wlStars(T,scene,hq?60:24,[-30,30,.3,2.5,-30,20],0xd9dce6,.18);dust.material.opacity=.35;
    const wx=wlWeather(T,scene,[-30,30,.4,12,-30,20]);
    return {
      spots:[[0,.5,9.2],[-3.3,.5,8.4],[3.3,.5,8.4],[-6.6,.5,7.2],[6.6,.5,7.2],[-1.7,.5,5.4],[1.7,.5,5.4],
        [-9.8,.5,6],[9.8,.5,6],[-5,.5,4.6],[5,.5,4.6],[0,.5,4.2]],
      camWide:[[0,7.4,28],[0,2.6,-30]],camTall:[[0,8.8,27],[0,-4.7,-8]],
      // busy crew fly a shuttle round the base
      busy(i,t){const a=t*.28+i*1.4;return new T.Vector3(Math.cos(a)*24,11+Math.sin(a*1.7+i)*2.5,-22+Math.sin(a)*14)},
      vessel(){const g=wlShuttle(T);scene.add(g);return g},
      tick(t,dt){sky.u.time.value=t;wx.tick(dt,t);planet.rotation.y=t*.004;clouds.rotation.y=t*.006;dish.rotation.y=t*.15;
        beacons.forEach(b=>{const on=(t*.9+b.ph)%1<.18;b.m.emissiveIntensity=on?3:.2;b.h.material.opacity=on?1:.05});
        padLights.forEach((p,k)=>{const f=.35+.65*Math.max(0,Math.cos((t*2.2-k*.35)%(Math.PI*2)));p.m.emissiveIntensity=f*1.6;p.h.material.opacity=f*.8})},
      light(d){halos.forEach(h=>h.material.opacity=.85);wx.light(0);WORLD.r.toneMappingExposure=1.05}};
  },
  garden(T,scene,cam){
    WL_MAT={};
    const hq=WORLD.hq,glow={wins:[],lanterns:[],spots:[]},halos=[];
    const props=new T.Group();scene.add(props);
    const sky=wlSky(T,scene,{clouds:wlCloudAmt(.7)});
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
    // a designed ground (sand, snow, moss, rust, ash) is a plain speckled soil in that colour
    const soil=WL_GROUND[wlScene().ground]?(()=>{const t=wlCanvasTex(T,'soil',256,256,(g,w)=>{g.fillStyle='#d8d8d8';g.fillRect(0,0,w,w);
      for(let i=0;i<900;i++){g.fillStyle=Math.random()<.5?'rgba(0,0,0,.12)':'rgba(255,255,255,.2)';g.fillRect(Math.random()*w,Math.random()*w,2,2)}}).clone();
      t.wrapS=t.wrapT=T.RepeatWrapping;t.repeat.set(26,20);t.needsUpdate=true;return t})():null;
    const ground=new T.Mesh(gg,new T.MeshStandardMaterial({color:soil?wlGround(0xffffff):0xffffff,map:soil||grassTex,roughness:1}));ground.position.z=-20;ground.receiveShadow=true;scene.add(ground);
    // the pond behind the team, a stone rim, a path from where you stand to its edge
    const pc=[-1,-15];
    const pond=wlHas('pond')?wlWater(T,new T.CircleGeometry(7,48).rotateX(-Math.PI/2),{deep:wlWaterCols()[0],shallow:wlWaterCols()[1]}):null;
    if(pond){pond.mesh.position.set(pc[0],.08,pc[1]);pond.mesh.scale.set(1.6,1,1);scene.add(pond.mesh)}
    const rimM=wlMat(T,'rim',{color:0x9a958a,roughness:1,flatShading:true});
    if(pond)for(let i=0;i<38;i++){const a=i/38*Math.PI*2,st=new T.Mesh(new T.DodecahedronGeometry(.45+((i*7)%3)*.12,0),rimM);st.position.set(pc[0]+Math.cos(a)*11.4,.12,pc[1]+Math.sin(a)*7.3);st.castShadow=true;props.add(st)}
    if(wlHas('path'))for(let i=0;i<7;i++){const st=new T.Mesh(new T.CylinderGeometry(.75,.8,.12,10),rimM);st.position.set(Math.sin(i*.9)*.8,.08,16-i*2.4);st.receiveShadow=true;props.add(st)}
    // stone lanterns: two framing the clearing, two by the water
    const lampLights=[];
    const acc=wlAccent();
    if(wlHas('lanterns'))[[-15,2],[15,2],[-10,-7],[9,-8]].forEach(([x,z])=>{const g=new T.Group();
      const base=new T.Mesh(new T.CylinderGeometry(.3,.45,1.2,6),rimM);base.position.y=.6;g.add(base);
      const lm=wlMat(T,'stonelamp',{color:0xd8d2c4,emissive:acc,emissiveIntensity:.1});const box=new T.Mesh(new T.BoxGeometry(.7,.6,.7),lm);box.position.y=1.5;g.add(box);
      if(glow.lanterns.indexOf(lm)<0)glow.lanterns.push(lm);
      const cap=new T.Mesh(new T.ConeGeometry(.75,.5,6),rimM);cap.position.y=2.05;g.add(cap);g.position.set(x,0,z);g.traverse(o=>{if(o.isMesh)o.castShadow=true});props.add(g);
      wlHalo(T,scene,new T.Vector3(x,1.5,z),acc,2.6,halos);lampLights.push({pos:new T.Vector3(x,1.5,z),color:acc})});
    if(pond)pond.setLights(lampLights);
    if(wlHas('trees'))[[-20,-10,'s'],[-14,-26,'t'],[14,-24,'t'],[22,-12,'s'],[-24,0,'w'],[23,1,'t'],[3,-32,'t'],[-5,-34,'s'],[-30,-16,'t'],[30,-20,'s']].forEach(([x,z,t],i)=>{
      let tr;if(t==='w')tr=wlWillow(T);else if(t==='s')tr=wlSakura(T);else{tr=new T.Group();
        const tk=new T.Mesh(new T.CylinderGeometry(.3,.45,3.2,7),wlMat(T,'oakbark',{color:0x6b4423,roughness:1}));tk.position.y=1.6;tr.add(tk);
        [[0,4.6,0,2.4],[1.2,4,.6,1.6],[-1.1,4.1,-.4,1.7]].forEach(([a,b,c,r])=>{const m=new T.Mesh(new T.IcosahedronGeometry(r,1),wlMat(T,'leaf'+(i%2),{color:i%2?0x3f8a3a:0x4f9f45,flatShading:true}));m.position.set(a,b,c);tr.add(m)});
        tr.traverse(o=>{if(o.isMesh)o.castShadow=true})}
      tr.position.set(x,0,z);props.add(tr)});
    wlBake(T,props);
    const flowers=new T.Group();scene.add(flowers);
    const petals=[0xf368e0,0xffd32a,0xff6b6b,0xffffff,0x9b59b6,0xff9f43];let shown=-1;
    const fg=new T.SphereGeometry(.2,6,5),stemG=new T.CylinderGeometry(.03,.03,.5,4),stemM=wlMat(T,'stem',{color:0x3f7d3a});
    const wx=wlWeather(T,scene,[-20,20,.6,9,-20,14]);
    // butterflies are the garden's own, and stay in when it rains or snows
    const wet=['rain','snow'].indexOf(wlScene().weather)>=0;
    const butterflies=wet?null:wlPetals(T,scene,hq?60:24,[-18,18,.5,5,-18,14]);
    if(butterflies){butterflies.pts.material.map=wlFxTex(T,'star');butterflies.pts.material.color=new T.Color(0xffe08a)}
    return {
      spots:[[0,0,6.8],[-3.3,0,6],[3.3,0,6],[-6.6,0,4.8],[6.6,0,4.8],[-1.7,0,3],[1.7,0,3],
        [-9.8,0,3.6],[9.8,0,3.6],[-5,0,2],[5,0,2],[0,0,1.4]],
      camWide:[[0,7.4,27],[0,1.8,-30]],camTall:[[0,8.4,23],[0,-6.2,-12]],
      busy(i,t){return new T.Vector3(-13+(i%5)*6.5+Math.sin(t*.5+i)*1.2,0,-5.4-(i%2)*1.2)},
      vessel(){return null},
      // the garden grows with the whole team: more of the ladder climbed, more blooms,
      // in beds around the pond and along the sides, never where anybody stands
      grow(total){const n=wlHas('flowers')?Math.min(240,30+Math.floor(total/2)):0;if(n===shown)return;shown=n;
        while(flowers.children.length){const c=flowers.children[0];flowers.remove(c);c.geometry.dispose()}
        const g=new T.Group();
        for(let k=0;k<n;k++){const a=k*2.399,r=4+Math.sqrt(k)*1.5,x=pc[0]+Math.cos(a)*r*2.2,z=pc[1]+Math.sin(a)*r*1.3;
          if(Math.hypot((x-pc[0])/12.4,(z-pc[1])/8.2)<1||z>12||(z>-1.5&&Math.abs(x)<12.5)||Math.abs(x)<1.6)continue;
          const col=petals[k%petals.length];
          const f=new T.Mesh(fg,wlMat(T,'flower'+col,{color:col,roughness:.6,emissive:col,emissiveIntensity:.05}));f.position.set(x,.55,z);g.add(f);
          const st=new T.Mesh(stemG,stemM);st.position.set(x,.25,z);g.add(st)}
        wlBake(T,g);while(g.children.length){const c=g.children[0];g.remove(c);flowers.add(c)}},
      tick(t,dt){sky.u.time.value=t;if(pond)pond.light(t,this._d||1,this._c||wlSkyColors(T,1),this._sd||new T.Vector3(0,1,0));
        if(butterflies)butterflies.tick(dt*.3,t);wx.tick(dt,t)},
      light(d){const c=wlSkyColors(T,d);this._d=d;this._c=c;
        sky.u.top.value.copy(c.top);sky.u.horizon.value.copy(c.horizon);const night=1-Math.min(1,d*2.4);sky.u.night.value=night;
        const sd=worldSunDir(T);this._sd=sd;sky.u.sunDir.value.copy(sd);sun.position.copy(sd).multiplyScalar(80);
        wlFog(T,scene,c.fog,60,220);sun.intensity=d*2.4;hemi.intensity=.35+d*.6;moon.intensity=night*.9;
        glow.lanterns.forEach(m=>m.emissiveIntensity=.1+night*2.2);halos.forEach(h=>h.material.opacity=night);
        ranges[0].color.set(worldMix(T,0x1d2640,0x86a0ae,d*1.6));wx.light(d);if(butterflies)butterflies.pts.material.opacity=Math.min(1,d*3);
        WORLD.r.toneMappingExposure=.95+night*.35}};
  },
  /* A small Japanese restaurant after dark (world.KITS izakaya). Asked for from a
     screenshot: a world designed as "a Japanese restaurant" had to be drawn as the canal
     town. Indoors, so the hour shows through the street window and in how bright the
     lanterns burn; the team stands in front of the counter and goes into the kitchen to
     work. The water colour is the tea in the cups and the glaze on the plates. */
  izakaya(T,scene,cam){
    WL_MAT={};
    const hq=WORLD.hq,glow={lanterns:[]},halos=[];
    const props=new T.Group();scene.add(props);
    const acc=wlAccent(),tea=wlWaterCols();
    const hemi=new T.HemisphereLight(0xffe2b8,0x3a2418,.75);scene.add(hemi);
    const key=new T.DirectionalLight(0xffd7a0,1.6);key.position.set(6,18,22);scene.add(key);scene.add(key.target);
    if(hq){key.castShadow=true;key.shadow.mapSize.set(1024,1024);const sc=key.shadow.camera;sc.left=-26;sc.right=26;sc.top=20;sc.bottom=-20;sc.far=80;key.shadow.bias=-.0015}
    // the floor: warm wooden boards, in the ground's colour when one was designed
    const boards=wlCanvasTex(T,'boards',256,256,(g,w)=>{g.fillStyle='#8a5a36';g.fillRect(0,0,w,w);
      for(let y=0;y<8;y++){const l=Math.floor(Math.random()*24);g.fillStyle=`rgb(${128+l},${84+l},${52+l})`;g.fillRect(0,y*32+1,w,30);
        g.fillStyle='rgba(40,20,10,.5)';g.fillRect(0,y*32,w,2);g.fillRect((y*97)%w,y*32,2,32)}}).clone();
    boards.wrapS=boards.wrapT=T.RepeatWrapping;boards.repeat.set(8,6);boards.needsUpdate=true;
    const floor=new T.Mesh(new T.PlaneGeometry(64,40).rotateX(-Math.PI/2),new T.MeshStandardMaterial({color:wlGround(0xffffff),map:boards,roughness:.9}));
    floor.position.set(0,0,-4);floor.receiveShadow=true;scene.add(floor);
    const wood=wlMat(T,'izwood',{color:0x6b4226,roughness:.8}),dark=wlMat(T,'izdark',{color:0x2e1d14,roughness:.9});
    const plaster=wlMat(T,'izplaster',{color:0xe9dcc4,roughness:1}),cedar=wlMat(T,'izcedar',{color:0xb07a4a,roughness:.7});
    // the back wall with a dark timber frame, and the two side walls
    const wall=(w,h,x,y,z,ry)=>{const m=new T.Mesh(new T.BoxGeometry(w,h,.4),plaster);m.position.set(x,y,z);m.rotation.y=ry||0;m.receiveShadow=true;props.add(m)};
    wall(20,12,10,6,-15);wall(10,5.5,-17,9.25,-15);wall(10,1.5,-17,.75,-15);wall(4,12,-24,6,-15);
    wall(26,12,-26,6,-2,Math.PI/2);wall(26,12,26,6,-2,Math.PI/2);
    [-26,-22,-12,0,12,26].forEach(x=>{const b=new T.Mesh(new T.BoxGeometry(.6,12,.6),dark);b.position.set(x,6,-14.7);props.add(b)});
    const beam=new T.Mesh(new T.BoxGeometry(54,.7,.7),dark);beam.position.set(0,11.2,-14.6);props.add(beam);
    for(let i=0;i<5;i++){const cb=new T.Mesh(new T.BoxGeometry(.5,.5,22),dark);cb.position.set(-20+i*10,11.6,-4);props.add(cb)}
    // the street window: a lit street behind glass, and whatever the weather is doing
    let street=null,wx={tick(){},light(){}};
    if(wlHas('window')){
      const sm=new T.MeshBasicMaterial({map:wlCanvasTex(T,'street',512,256,(g,w,h)=>{
        g.fillStyle='#1b2230';g.fillRect(0,0,w,h);
        for(let i=0;i<7;i++){const x=i*76-10,hh=120+((i*37)%70);g.fillStyle=i%2?'#2a2f3d':'#232837';g.fillRect(x,h-hh,70,hh);
          for(let r=0;r<4;r++)for(let c=0;c<3;c++)if((i+r+c)%3){g.fillStyle='rgba(255,200,120,.85)';g.fillRect(x+8+c*20,h-hh+14+r*26,12,14)}}
        g.fillStyle='rgba(255,90,70,.9)';for(let i=0;i<6;i++){g.beginPath();g.arc(40+i*85,h-150,7,0,7);g.fill()}}),fog:false});
      street=new T.Mesh(new T.PlaneGeometry(14,7),sm);street.position.set(-17,4,-21);scene.add(street);
      const frame=wlMat(T,'izframe',{color:0x2e1d14});
      [[-17,7.05,10.2,.3],[-17,1.55,10.2,.3],[-22,4.3,.3,5.8],[-12,4.3,.3,5.8],[-17,4.3,.18,5.8],[-14.5,4.3,.12,5.8],[-19.5,4.3,.12,5.8]].forEach(([x,y,w,h])=>{
        const b=new T.Mesh(new T.BoxGeometry(w,h,.3),frame);b.position.set(x,y,-14.9);props.add(b)});
      wx=wlWeather(T,scene,[-22,-12,1.5,7,-20,-16]);
    }
    // the counter along the middle, a cedar top, and stools in front of it
    if(wlHas('counter')){
      const body=new T.Mesh(new T.BoxGeometry(26,1.6,1.6),wood);body.position.set(1,.8,-5);body.castShadow=true;props.add(body);
      const top=new T.Mesh(new T.BoxGeometry(26.6,.25,2.1),cedar);top.position.set(1,1.72,-5);top.castShadow=true;props.add(top);
      const cup=new T.CylinderGeometry(.18,.14,.32,10),teaM=wlMat(T,'iztea',{color:tea[1],roughness:.3,emissive:tea[1],emissiveIntensity:.08});
      const plate=new T.CylinderGeometry(.42,.38,.08,14),glaze=wlMat(T,'izglaze',{color:tea[0],roughness:.25});
      for(let i=0;i<8;i++){const c=new T.Mesh(cup,teaM);c.position.set(-10+i*3.2,2.01,-4.6);props.add(c);
        if(i%2){const pl=new T.Mesh(plate,glaze);pl.position.set(-9+i*3.2,1.89,-5.1);props.add(pl)}}
      const seat=wlMat(T,'izseat',{color:0x8b1e1e,roughness:.7});
      for(let i=0;i<8;i++){const st=new T.Group(),x=-10.5+i*3.2;
        const leg=new T.Mesh(new T.CylinderGeometry(.12,.16,1.4,6),dark);leg.position.y=.7;st.add(leg);
        const sq=new T.Mesh(new T.CylinderGeometry(.6,.55,.22,12),seat);sq.position.y=1.45;st.add(sq);
        st.position.set(x,0,-2.9);st.traverse(o=>{if(o.isMesh)o.castShadow=true});props.add(st)}
    }
    // shelves of bottles and bowls on the back wall
    if(wlHas('shelves')){
      const bottleCols=[0x2f6b3a,0x7a2b1f,0x2b3f6b,0xd9c9a0,0x5a3a1f,0x3f7f6f];
      for(let r=0;r<3;r++){const sh=new T.Mesh(new T.BoxGeometry(10,.2,1),cedar);sh.position.set(-5,4+r*1.9,-14.3);props.add(sh);
        for(let i=0;i<9;i++){const col=bottleCols[(i+r)%bottleCols.length],tall=(i+r)%3===0;
          const b=new T.Mesh(tall?new T.CylinderGeometry(.18,.24,1.2,8):new T.SphereGeometry(.34,10,8),wlMat(T,'izbottle'+col,{color:col,roughness:.2,metalness:.1}));
          b.position.set(-9.2+i*1.05,4.1+r*1.9+(tall?.6:.3),-14.2);props.add(b)}}
    }
    // the kitchen behind the counter: a range with pots, and steam that never stops
    const steam=[];
    if(wlHas('kitchen')){
      const range=new T.Mesh(new T.BoxGeometry(14,1.8,2.2),wlMat(T,'izsteel',{color:0x9aa0a8,roughness:.35,metalness:.6}));range.position.set(4,.9,-11);range.castShadow=true;props.add(range);
      const pot=new T.CylinderGeometry(.7,.6,.9,14),potM=wlMat(T,'izpot',{color:0x3a3f46,roughness:.4,metalness:.5});
      [-1,2,5,8].forEach(x=>{const p=new T.Mesh(pot,potM);p.position.set(x,2.25,-11);p.castShadow=true;props.add(p);
        if(steam.length<(hq?24:12))for(let k=0;k<(hq?6:3);k++){const s=new T.Sprite(new T.SpriteMaterial({map:wlGlowTex(T),color:0xffffff,transparent:true,opacity:0,depthWrite:false}));
          s.userData={x,ph:Math.random()*4,sp:.6+Math.random()*.5};scene.add(s);steam.push(s)}});
      const hood=new T.Mesh(new T.BoxGeometry(14,.6,2.6),wlMat(T,'izsteel2',{color:0x7c828a,roughness:.4,metalness:.5}));hood.position.set(4,8.2,-11.4);props.add(hood);
    }
    // the noren: split curtains over the kitchen door, in the accent colour with a mark
    if(wlHas('noren')){
      const cloth=wlMat(T,'iznoren',{color:acc,roughness:.9,side:T.DoubleSide,map:wlCanvasTex(T,'noren',128,128,(g,w)=>{
        g.fillStyle='#ffffff';g.fillRect(0,0,w,w);g.strokeStyle='rgba(255,255,255,.0)';
        g.fillStyle='rgba(255,255,255,.95)';g.beginPath();g.arc(w*.5,w*.45,w*.22,0,7);g.fill();
        g.fillStyle='rgba(0,0,0,.18)';g.beginPath();g.arc(w*.5,w*.45,w*.12,0,7);g.fill()})});
      const rod=new T.Mesh(new T.CylinderGeometry(.08,.08,8,6),dark);rod.rotation.z=Math.PI/2;rod.position.set(14,8.6,-13.4);props.add(rod);
      for(let i=0;i<4;i++){const c=new T.Mesh(new T.PlaneGeometry(1.8,3.2),cloth);c.position.set(11.3+i*1.9,6.95,-13.35);props.add(c)}
    }
    // paper lanterns hanging from the beams, lit always and brighter after dark
    const lamps=[];
    if(wlHas('lanterns')){
      const lm=wlMat(T,'izlantern',{color:acc,emissive:acc,emissiveIntensity:.6,roughness:.8});glow.lanterns.push(lm);
      const lg=new T.SphereGeometry(.7,14,10);lg.scale(1,1.25,1);
      [-16,-8,0,8,16,-12,4,12].forEach((x,i)=>{const z=i<5?-2:-8,l=new T.Mesh(lg,lm);l.position.set(x,8.6,z);l.userData.keep=true;scene.add(l);lamps.push(l);
        const cap=new T.Mesh(new T.CylinderGeometry(.35,.35,.15,10),dark);cap.position.set(x,9.55,z);props.add(cap);
        wlHalo(T,scene,new T.Vector3(x,8.6,z),acc,4.2,halos)});
    }
    wlBake(T,props);
    scene.background=new T.Color(0x140c08);
    return {
      spots:[[0,0,6.8],[-3.3,0,6],[3.3,0,6],[-6.6,0,4.8],[6.6,0,4.8],[-1.7,0,3],[1.7,0,3],
        [-9.8,0,3.6],[9.8,0,3.6],[-5,0,2],[5,0,2],[0,0,1.4]],
      camWide:[[0,7.6,27],[0,3.2,-20]],camTall:[[0,8.6,23],[0,-3.8,-10]],
      // at work they go behind the counter to the range
      busy(i,t){return new T.Vector3(-2+(i%5)*2.6+Math.sin(t*.9+i)*.5,0,-8.6-(i%2)*.8)},
      vessel(){return null},
      tick(t,dt){steam.forEach((s,k)=>{const u=((t*s.userData.sp+s.userData.ph)%3)/3;
          s.position.set(s.userData.x+Math.sin(t+k)*.25,2.8+u*4.2,-11);const sz=.8+u*2.2;s.scale.set(sz,sz,1);s.material.opacity=(1-u)*.22});
        lamps.forEach((l,k)=>{l.rotation.z=Math.sin(t*.8+k)*.04});wx.tick(dt,t)},
      light(d){const night=1-Math.min(1,d*2.4);
        if(street)street.material.color.copy(worldMix(T,0xffffff,0x9fc4ff,d*1.4));
        glow.lanterns.forEach(m=>m.emissiveIntensity=.6+night*1.6);halos.forEach(h=>h.material.opacity=.35+night*.65);
        key.intensity=1.1+d*.9;hemi.intensity=.55+d*.35;wlFog(T,scene,new T.Color(0x140c08),70,160);wx.light(d);
        WORLD.r.toneMappingExposure=1.02+night*.18}};
  }
};
