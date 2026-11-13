/* ================= the Stage's model: a thing or a place, built in 3D on the sheet =================
   stage.py's `model` kind (and a blueprint's `model`) is the closed set; this draws it. Asked for
   as "paper style detailed blueprint with brown paper and black lines, a bit animated … projected
   in the air … if I have to build Kyoto with pink leaves and trees I should be able to see them
   coming to life". The agent places solids (a shape, where, how big, what colour); nothing it
   wrote runs. The page inks the plan on the sheet line by line, raises each solid out of the
   paper, lets the colour wash in, and then the place lives: leaves sway, petals fall, water runs.

   Three looks, one model: paper (ink and hatching on brown paper, colour as a wash), blueprint
   (white line on blue) and hologram (lines of light over a projector). The person picks; the
   scene's own `style` is where it starts.

   Seven rules:
   - Every word is text (textContent, SVG text nodes): a label is a model's words.
   - One geometry, two painters. mdlBuild turns solids into faces; the WebGL painter (mdlGL) and
     the still one (mdlStill, an ink drawing in SVG) both draw those faces, so a phone's picture,
     a small machine's screen and reduced motion show the same thing the desk does.
   - Lines are real width: each edge is a quad widened on screen in the vertex shader, because
     WebGL lines are one pixel. An edge is drawn where two faces meet at an angle; the outline
     of a round thing is the back faces pushed out (so a sphere has an edge from every side).
   - Hatching is shade: the fragment shader crosses the unlit side with pen strokes in screen
     space, and a colour is a wash that pools unevenly, never a flat fill.
   - Nothing runs forever. The build plays once; the place lives for MDL_LIFE_S after the last
     touch and then rests on one frame. No frame is drawn while hidden or off the page, and the
     renderer is released when the drawing leaves.
   - A small machine's own screen (liteScreen), reduced motion, the Telegram page and a browser
     with no WebGL get the still drawing.
   - Sized from the layout box (clientWidth), the blueprint's rule.

   Three faces: the GUI is this file; the TUI and the terminal chat print a model in words
   (stage.model_line); SUI is a page like any other and nothing here touches the compositor.

   Loaded after 24l-stage.js and 24v-blueprint.js (sEl, sSvg, stageReduced, bp*); function
   declarations hoist across the bundle, and the Telegram page embeds all three files. */

var MDL_COL={pink:'#f2a3bf',red:'#c4452f',orange:'#de8a3e',gold:'#d6a41f',yellow:'#ead05a',green:'#84b061',
  leaf:'#3f7f4c',teal:'#3a9c95',blue:'#4a7fc9',sky:'#a3cdea',navy:'#2b446f',purple:'#8b63b9',brown:'#7b5337',
  wood:'#a87a4f',stone:'#aaa79c',grey:'#8e9197',white:'#f6f2e7',black:'#51473f',sand:'#e2cd9a',glass:'#a8d5df'};
var MDL_LOOK={
  paper:{name:'Paper',bg:'#c8a675',paper:[.784,.651,.459],ink:[.125,.094,.063],style:0,lw:1.3,hull:1.15,hatch:.6},
  blueprint:{name:'Blueprint',bg:'#12437b',paper:[.071,.263,.482],ink:[.93,.97,1],style:1,lw:1.15,hull:1.05,hatch:.34},
  hologram:{name:'Hologram',bg:'#02060e',paper:[.008,.024,.055],ink:[.36,.95,1],style:2,lw:1.5,hull:0,hatch:0}};
var MDL_GROUND={grass:'#a9c07a',water:'#7fb3d0',sand:'#dcc58f',snow:'#f2f0e9',stone:'#b4afa3'};
var MDL_WEATHER={petals:{c:'#f7b4ca',n:260,sp:.55,dr:1.3,sz:7},leaves:{c:'#d8842c',n:170,sp:.75,dr:1.5,sz:7},
  snow:{c:'#ffffff',n:340,sp:.5,dr:.6,sz:5},rain:{c:'#c3dcf1',n:420,sp:7,dr:.04,sz:3},
  fireflies:{c:'#ffe68c',n:90,sp:0,dr:1,sz:7,glow:1},sparks:{c:'#ffb24c',n:170,sp:-1.7,dr:.5,sz:5,glow:1}};
var MDL_NATURAL={tree:1,blossom:1,pine:1,palm:1,bamboo:1,bush:1,rock:1,cloud:1,bird:1,person:2,boat:2,car:2};
var MDL_MOVE={cloud:'drift',bird:'orbit',plane:'orbit',water:'flow',boat:'bob'};
var MDL_LIFE_S=40;       // how long the place lives after the last touch, before it rests
var MDL_FIT=20;          // the model is scaled so its longest side is this many units

function mdlRnd(seed){let s=seed%2147483647;if(s<=0)s+=2147483646;return ()=>(s=s*16807%2147483647)/2147483647}
function mdlRGB(c){if(!c)return null;const h=MDL_COL[c]||c;if(!/^#[0-9a-f]{6}$/i.test(h))return null;
  return [parseInt(h.slice(1,3),16)/255,parseInt(h.slice(3,5),16)/255,parseInt(h.slice(5,7),16)/255]}
function mdlHex(rgb){return '#'+rgb.map(x=>('0'+Math.round(Math.max(0,Math.min(1,x))*255).toString(16)).slice(-2)).join('')}
var MDL_KEEP={};         // per drawing: the look you picked and whether it has been built, for a repaint of the Stage
function mdlGLok(){try{const c=document.createElement('canvas');return !!(c.getContext('webgl2')||c.getContext('webgl'))}catch(e){return false}}
function mdlLite(){try{return typeof liteScreen==='function'&&liteScreen()}catch(e){return false}}

/* ---------- a solid, as the simple pieces it is made of ---------- */
/* Each piece: k (box, cone, sph, dome, roof, ring, arch), where its base centre is in the
   solid (x, y, z), its size (w, h, d) and its colour (undefined = the solid's own). A cone
   with n sides and a top ratio tp is every prism, frustum and pyramid. */
function mdlPieces(so){
  const w=so.size[0],h=so.size[1],d=so.size[2],c=so.color||null,P=[],T=so.tiers||0;
  const p=(k,x,y,z,pw,ph,pd,col,o)=>{P.push(Object.assign({k,x,y,z,w:pw,h:ph,d:pd,c:col===undefined?c:col},o||{}))};
  const R=mdlRnd(97+Math.round(w*31+h*17));
  switch(so.shape){
  case 'box':p('box',0,0,0,w,h,d);break;
  case 'cylinder':p('cone',0,0,0,w,h,d,c,{n:so._tp?24:20,tp:so._tp||1,bands:so._bands||0});break;
  case 'cone':p('cone',0,0,0,w,h,d,c,{n:20,tp:0});break;
  case 'pyramid':p('cone',0,0,0,w,h,d,c,{n:4,tp:0});break;
  case 'sphere':p('sph',0,0,0,w,h,d,c,{n:14,m:8});break;
  case 'dome':p('dome',0,0,0,w,h,d,c,{n:14,m:5});break;
  case 'roof':p('roof',0,0,0,w,h,d);break;
  case 'ring':p('ring',0,0,0,w,h,d);break;
  case 'arch':p('arch',0,0,0,w,h,d,c,{th:.16});break;
  case 'tree':p('cone',0,0,0,w*.13,h*.5,w*.13,'wood',{n:6,tp:.75});
    p('sph',0,h*.3,0,w,h*.7,d,c||'green',{leaf:1,n:8,m:5});break;
  case 'blossom':p('cone',0,0,0,w*.12,h*.5,w*.12,'brown',{n:6,tp:.7});
    p('sph',-w*.2,h*.34,w*.06,w*.7,h*.5,d*.7,c||'pink',{leaf:1,n:7,m:4});
    p('sph',w*.22,h*.4,-w*.08,w*.66,h*.48,d*.66,c||'pink',{leaf:1,n:7,m:4});
    p('sph',0,h*.54,w*.12,w*.6,h*.46,d*.6,c||'pink',{leaf:1,n:7,m:4});break;
  case 'pine':p('cone',0,0,0,w*.12,h*.3,w*.12,'wood',{n:6,tp:.8});
    p('cone',0,h*.16,0,w,h*.42,d,c||'leaf',{n:7,tp:0,leaf:1});
    p('cone',0,h*.4,0,w*.74,h*.36,d*.74,c||'leaf',{n:7,tp:0,leaf:1});
    p('cone',0,h*.63,0,w*.48,h*.37,d*.48,c||'leaf',{n:7,tp:0,leaf:1});break;
  case 'palm':p('cone',0,0,0,w*.1,h*.86,w*.1,'wood',{n:6,tp:.6});
    for(let i=0;i<6;i++){const a=i/6*6.2832;p('sph',Math.cos(a)*w*.3,h*.8,Math.sin(a)*w*.3,w*.62,h*.13,w*.24,c||'leaf',{leaf:1,n:6,m:3,r:-a})}break;
  case 'bamboo':for(let i=0;i<3;i++){const ox=(R()-.5)*w*.8,oz=(R()-.5)*d*.8,hh=h*(.75+R()*.25);
      p('cone',ox,0,oz,w*.07,hh,w*.07,c||'green',{n:5,tp:.8});
      p('sph',ox,hh*.72,oz,w*.34,hh*.3,w*.34,'leaf',{leaf:1,n:5,m:3})}break;
  case 'bush':p('sph',-w*.15,0,0,w*.7,h,d*.8,c||'leaf',{leaf:1,n:7,m:4});
    p('sph',w*.2,0,d*.1,w*.6,h*.8,d*.7,c||'leaf',{leaf:1,n:7,m:4});break;
  case 'rock':p('sph',0,-h*.22,0,w,h*1.22,d,c||'stone',{n:6,m:3,rough:.2});break;
  case 'mountain':p('dome',0,0,0,w,h,d,c||'stone',{n:11,m:5,peak:1,rough:.13,snow:h>Math.max(w,d)*.3?.7:2});break;
  case 'cloud':p('sph',-w*.24,0,0,w*.5,h*.8,d*.8,c||'white',{n:8,m:4});
    p('sph',w*.04,h*.1,0,w*.56,h,d,c||'white',{n:8,m:4});
    p('sph',w*.3,0,d*.06,w*.44,h*.7,d*.7,c||'white',{n:8,m:4});break;
  case 'water':p('box',0,0,0,w,Math.max(w,d)*.003,d,c||'blue',{flow:1,plate:1});break;
  case 'path':p('box',0,0,0,w,Math.max(w,d)*.004,d,c||'sand',{plate:1});break;
  case 'house':p('box',0,0,0,w,h*.6,d,c||'white');p('roof',0,h*.6,0,w*1.12,h*.4,d*1.16,'brown');
    p('box',0,0,d*.5,w*.18,h*.36,w*.02,'wood');break;
  case 'building':p('box',0,0,0,w,h,d,c,{win:T||Math.max(2,Math.min(30,Math.round(h/(Math.min(w,d)*.42))))});break;
  case 'pagoda':{const t=T||3;p('box',0,0,0,w,h*.04,d,'stone');let y=h*.04;const th=h*.78/t;
    for(let i=0;i<t;i++){const s=1-.12*i;p('box',0,y,0,w*.5*s,th*.56,d*.5*s,c||'red');
      p('cone',0,y+th*.56,0,w*.98*s,th*.44,d*.98*s,'black',{n:4,tp:.42});y+=th}
    p('cone',0,y,0,w*.06,h*.15,w*.06,'gold',{n:6,tp:.3});p('sph',0,y+h*.14,0,w*.1,w*.1,w*.1,'gold',{n:6,m:4});break}
  case 'torii':{const dd=Math.min(d,w*.12);
    p('cone',-w*.36,0,0,w*.085,h*.9,w*.085,c||'red',{n:8,tp:.85});p('cone',w*.36,0,0,w*.085,h*.9,w*.085,c||'red',{n:8,tp:.85});
    p('box',0,h*.64,0,w*.86,h*.07,dd*.6,c||'red');p('box',0,h*.85,0,w*1.08,h*.075,dd,c||'red');
    p('box',0,h*.925,0,w*1.18,h*.05,dd*1.25,'black');break}
  case 'bridge':p('arch',0,0,0,w,h,d,c||'red',{th:.26});
    p('arch',0,h*.14,d*.47,w,h,d*.05,c||'red',{th:.07});p('arch',0,h*.14,-d*.47,w,h,d*.05,c||'red',{th:.07});break;
  case 'lantern':p('cone',0,0,0,w*.7,h*.1,d*.7,'stone',{n:6,tp:.8});p('cone',0,h*.1,0,w*.22,h*.42,d*.22,'stone',{n:6,tp:.9});
    p('box',0,h*.52,0,w*.5,h*.2,d*.5,c||'gold');p('cone',0,h*.72,0,w,h*.2,d,'stone',{n:4,tp:.1});
    p('sph',0,h*.9,0,w*.16,h*.1,d*.16,'stone',{n:6,m:3});break;
  case 'wall':p('box',0,0,0,w,h*.85,d,c||'white');p('roof',0,h*.85,0,w,h*.15,d*1.6,'black');break;
  case 'column':p('box',0,0,0,w,h*.06,d,c);p('cone',0,h*.06,0,w*.72,h*.86,d*.72,c,{n:14,tp:.86});p('box',0,h*.92,0,w,h*.08,d,c);break;
  case 'stairs':{const n=T||6;for(let i=0;i<n;i++)p('box',0,0,d/2-d*(i+.5)/n,w,h*(i+1)/n,d/n,c||'stone')}break;
  case 'person':p('box',-w*.17,0,0,w*.26,h*.46,d*.6,'navy');p('box',w*.17,0,0,w*.26,h*.46,d*.6,'navy');
    p('cone',0,h*.46,0,w*.8,h*.34,d*.9,c||'red',{n:4,tp:.82});
    p('box',-w*.5,h*.5,0,w*.16,h*.29,d*.5,c||'red');p('box',w*.5,h*.5,0,w*.16,h*.29,d*.5,c||'red');
    p('sph',0,h*.81,0,h*.17,h*.19,h*.17,'sand',{n:8,m:5});break;
  case 'bird':p('sph',0,0,0,w*.3,h*.6,d,c||'black',{n:6,m:3});p('box',0,h*.34,0,w,h*.08,d*.42,c||'black');break;
  case 'boat':p('cone',0,0,0,w*.8,h*.28,d*.8,c||'wood',{n:4,tp:1.25});
    p('cone',0,h*.28,0,w*.035,h*.72,w*.035,'wood',{n:5,tp:.8});p('box',w*.13,h*.42,0,w*.42,h*.5,w*.012,'white');break;
  case 'car':p('box',0,h*.2,0,w,h*.42,d,c||'red');p('box',-w*.04,h*.62,0,w*.55,h*.38,d*.86,'glass');
    [[-1,-1],[1,-1],[-1,1],[1,1]].forEach(q=>p('sph',q[0]*w*.3,0,q[1]*d*.46,h*.44,h*.44,d*.2,'black',{n:8,m:4}));break;
  case 'plane':p('sph',0,0,0,w,h*.5,d*.14,c||'white',{n:8,m:5});p('box',0,h*.2,0,w*.2,h*.06,d,c||'white');
    p('box',-w*.44,h*.3,0,w*.1,h*.6,d*.02,c||'white');p('box',-w*.44,h*.26,0,w*.1,h*.05,d*.36,c||'white');break;
  default:p('box',0,0,0,w,h,d);
  }
  return P;
}

/* ---------- a piece as faces ---------- */
/* Vertices round the piece's base centre, faces counter-clockwise seen from outside (checked
   by the signed volume, so a generator only has to be consistent with itself). */
function mdlMesh(pc){
  const v=[],f=[],w=pc.w/2,h=pc.h,d=pc.d/2,k=pc.k;
  const ring=(n,y,rx,rz,ph)=>{const s=v.length;for(let i=0;i<n;i++){const a=(ph||0)+i/n*6.283185;v.push([Math.cos(a)*rx,y,Math.sin(a)*rz])}return s};
  const strip=(b,t,n)=>{for(let i=0;i<n;i++){const j=(i+1)%n;f.push({i:[b+i,t+i,t+j,b+j]})}};
  if(k==='box'){
    [[-1,0,-1],[1,0,-1],[1,0,1],[-1,0,1],[-1,1,-1],[1,1,-1],[1,1,1],[-1,1,1]].forEach(q=>v.push([q[0]*w,q[1]*h,q[2]*d]));
    [[0,1,2,3],[7,6,5,4],[3,2,6,7],[1,0,4,5],[0,3,7,4],[2,1,5,6]].forEach(q=>f.push({i:q}));
    if(pc.win){   // a building's floors and mullions, ruled on its four walls
      const fl=pc.win,line=(a,b,fi)=>{const s=v.length;v.push(a,b);(f[fi].lines=f[fi].lines||[]).push([s,s+1])};
      [[2,-w,d,w,d],[3,w,-d,-w,-d],[4,-w,-d,-w,d],[5,w,d,w,-d]].forEach(q=>{const fi=q[0],x0=q[1],z0=q[2],x1=q[3],z1=q[4];
        for(let j=1;j<fl;j++){const y=h*j/fl;line([x0,y,z0],[x1,y,z1],fi)}
        const L=Math.hypot(x1-x0,z1-z0),cols=Math.max(2,Math.min(9,Math.round(L/(h/fl)/1.1)));
        for(let j=1;j<cols;j++){const u=j/cols;line([x0+(x1-x0)*u,0,z0+(z1-z0)*u],[x0+(x1-x0)*u,h,z0+(z1-z0)*u],fi)}});
    }
  }else if(k==='cone'){
    const n=pc.n||16,tp=pc.tp==null?1:pc.tp,sq=n===4?1.41421:1,ph=n===4?.785398:0;
    const b=ring(n,0,w*sq,d*sq,ph);
    if(tp<.02){const a=v.length;v.push([0,h,0]);for(let i=0;i<n;i++)f.push({i:[b+i,a,b+(i+1)%n]})}
    else{const t=ring(n,h,w*sq*tp,d*sq*tp,ph);strip(b,t,n);const cap=[];for(let i=n-1;i>=0;i--)cap.push(t+i);f.push({i:cap});
      // storeys, ruled round it
      for(let j=1;j<=(pc.bands||0);j++){const u=j/(pc.bands+1),r=1+(tp-1)*u,s0=v.length;
        for(let i=0;i<n;i++){const a=ph+i/n*6.283185;v.push([Math.cos(a)*w*sq*r,h*u,Math.sin(a)*d*sq*r])}
        for(let i=0;i<n;i++)(f[i].lines=f[i].lines||[]).push([s0+i,s0+(i+1)%n])}}
    const bot=[];for(let i=0;i<n;i++)bot.push(b+i);f.push({i:bot});
  }else if(k==='sph'||k==='dome'){
    const n=pc.n||12,m=pc.m||6,dome=k==='dome',rings=[];
    if(dome){for(let j=0;j<m;j++){const a=j/m*1.570796,u=j/m,r=pc.peak?Math.pow(1-u,1.25):Math.cos(a);
        rings.push(ring(n,pc.peak?u*h:Math.sin(a)*h,r*w,r*d,pc.peak?j*.3:0))}
      const top=v.length;v.push([0,h,0]);for(let j=0;j<m-1;j++)strip(rings[j],rings[j+1],n);
      for(let i=0;i<n;i++)f.push({i:[top,rings[m-1]+(i+1)%n,rings[m-1]+i]});
      const bot=[];for(let i=0;i<n;i++)bot.push(rings[0]+i);f.push({i:bot})}
    else{const lo=v.length;v.push([0,0,0]);
      for(let j=1;j<m;j++){const a=-1.570796+j/m*3.141593;rings.push(ring(n,h/2+Math.sin(a)*h/2,Math.cos(a)*w,Math.cos(a)*d))}
      const top=v.length;v.push([0,h,0]);
      for(let i=0;i<n;i++)f.push({i:[lo,rings[0]+i,rings[0]+(i+1)%n]});
      for(let j=0;j<rings.length-1;j++)strip(rings[j],rings[j+1],n);
      const r=rings[rings.length-1];for(let i=0;i<n;i++)f.push({i:[top,r+(i+1)%n,r+i]})}
  }else if(k==='roof'){
    v.push([-w,0,-d],[w,0,-d],[w,0,d],[-w,0,d],[-w,h,0],[w,h,0]);
    [[3,2,5,4],[1,0,4,5],[0,3,4],[2,1,5],[0,1,2,3]].forEach(q=>f.push({i:q}));
  }else if(k==='ring'){
    const n=24,m=8,r=Math.min(h/2,w*.45),R=w-r,q=d/w;
    for(let i=0;i<n;i++){const a=i/n*6.283185;for(let j=0;j<m;j++){const b=j/m*6.283185;
      v.push([(R+r*Math.cos(b))*Math.cos(a),r+r*Math.sin(b),(R+r*Math.cos(b))*Math.sin(a)*q])}}
    for(let i=0;i<n;i++)for(let j=0;j<m;j++){const i2=(i+1)%n,j2=(j+1)%m;f.push({i:[i*m+j,i*m+j2,i2*m+j2,i2*m+j]})}
  }else if(k==='arch'){
    const s=14,th=Math.min(w,h)*(pc.th||.16)*2,ri=Math.max(.02,w-th),hi=Math.max(.02,h-th);
    for(let i=0;i<=s;i++){const a=3.141593-i/s*3.141593,cx=Math.cos(a),sy=Math.sin(a);
      v.push([cx*w,sy*h,d],[cx*w,sy*h,-d],[cx*ri,sy*hi,-d],[cx*ri,sy*hi,d])}
    for(let i=0;i<s;i++)for(let j=0;j<4;j++){const j2=(j+1)%4;f.push({i:[i*4+j,(i+1)*4+j,(i+1)*4+j2,i*4+j2]})}
    f.push({i:[0,1,2,3]},{i:[s*4+3,s*4+2,s*4+1,s*4]});
  }
  if(pc.rough){const R=mdlRnd(11+v.length*7+Math.round(w*13));v.forEach(p=>{if(p[1]>h*.02||k==='sph'){
    const j=1+(R()-.5)*2*pc.rough;p[0]*=j;p[2]*=1+(R()-.5)*2*pc.rough;if(p[1]<h*.98)p[1]*=1+(R()-.5)*pc.rough}})}
  // outward: a closed mesh wound outward has a positive volume
  let vol=0;f.forEach(fc=>{const a=v[fc.i[0]];for(let t=1;t<fc.i.length-1;t++){const b=v[fc.i[t]],c=v[fc.i[t+1]];
    vol+=a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])}});
  if(vol<0)f.forEach(fc=>fc.i.reverse());
  if(pc.snow)f.forEach(fc=>{let y=0;fc.i.forEach(i=>{y+=v[i][1]});if(y/fc.i.length>h*pc.snow)fc.c='white'});
  return {v,f};
}

/* Normals, and which edges are drawn. A face's normal is Newell's; a corner is shaded with the
   faces round it that turn less than the smoothing angle; an edge is inked where its two faces
   turn more than that, or where it has only one. */
function mdlFinish(mesh,smooth){
  const v=mesh.v,f=mesh.f,cut=smooth===2?.93:smooth?.34:.8;
  f.forEach(fc=>{let x=0,y=0,z=0;const n=fc.i.length;
    for(let a=0;a<n;a++){const p=v[fc.i[a]],q=v[fc.i[(a+1)%n]];x+=(p[1]-q[1])*(p[2]+q[2]);y+=(p[2]-q[2])*(p[0]+q[0]);z+=(p[0]-q[0])*(p[1]+q[1])}
    const l=Math.hypot(x,y,z)||1;fc.n=[x/l,y/l,z/l]});
  // vertices that sit in one place are one corner (a sphere's rings share nothing by index at the poles)
  const key=p=>Math.round(p[0]*500)+','+Math.round(p[1]*500)+','+Math.round(p[2]*500),at={},same=[];
  v.forEach((p,i)=>{const k=key(p);if(at[k]==null)at[k]=i;same[i]=at[k]});
  const round=[];f.forEach((fc,fi)=>fc.i.forEach(i=>{(round[same[i]]=round[same[i]]||[]).push(fi)}));
  mesh.hn=v.map((p,i)=>{const fs=round[same[i]]||[];let x=0,y=0,z=0;fs.forEach(fi=>{x+=f[fi].n[0];y+=f[fi].n[1];z+=f[fi].n[2]});
    const l=Math.hypot(x,y,z)||1;return [x/l,y/l,z/l]});
  const edges={};
  f.forEach((fc,fi)=>{const n=fc.i.length;fc.vn=[];fc.e=[];
    for(let a=0;a<n;a++){const i=same[fc.i[a]],fs=round[i]||[];let x=0,y=0,z=0;
      fs.forEach(g=>{const m=f[g].n;if(m[0]*fc.n[0]+m[1]*fc.n[1]+m[2]*fc.n[2]>=cut){x+=m[0];y+=m[1];z+=m[2]}});
      const l=Math.hypot(x,y,z)||1;fc.vn.push([x/l,y/l,z/l]);
      const j=same[fc.i[(a+1)%n]];if(i===j){fc.e.push(null);continue}
      const ek=i<j?i+'_'+j:j+'_'+i;(edges[ek]=edges[ek]||[]).push([fi,a]);fc.e.push(ek)}});
  mesh.hard={};
  Object.keys(edges).forEach(ek=>{const us=edges[ek];
    if(us.length<2){mesh.hard[ek]=1;return}
    const a=f[us[0][0]].n,b=f[us[1][0]].n;if(a[0]*b[0]+a[1]*b[1]+a[2]*b[2]<cut)mesh.hard[ek]=1});
  mesh.edges=edges;mesh.same=same;
  return mesh;
}

/* ---------- the whole model as faces, in the page's own units ---------- */
function mdlBuild(model){
  const solids=model.solids||[],rnd=mdlRnd(4211),out=[];
  // what stands where, so a grove grows round the temple and beside the river, never through them
  const fixed=solids.map((s,i)=>({i,x:s.at[0],z:s.at[2],rx:s.size[0]/2,rz:s.size[2]/2,
    on:!(s.count>1)&&s.at[1]<s.size[1]*.5&&(s.shape==='water'||s.shape==='path'||s.size[1]>=Math.max(s.size[0],s.size[2])*.08)}));
  solids.forEach((so,si)=>{
    const pieces=mdlPieces(so),n=so.count||1,nat=MDL_NATURAL[so.shape],copies=[],gap=Math.max(so.size[0],so.size[2])*.62;
    const yaw0=(so.turn||0)*Math.PI/180;
    for(let c=0;c<n;c++){
      let x=so.at[0],z=so.at[2],yaw=yaw0,sc=1;
      if(n>1){let tries=0,bad=true;
        while(bad&&tries++<12){x=so.at[0]+(rnd()-.5)*so.spread[0];z=so.at[2]+(rnd()-.5)*so.spread[1];
          bad=copies.some(q=>Math.hypot(q.x-x,q.z-z)<gap)||(so.at[1]<.01&&so.shape!=='boat'&&
            fixed.some(fx=>fx.on&&fx.i!==si&&Math.abs(x-fx.x)<fx.rx+gap*.4&&Math.abs(z-fx.z)<fx.rz+gap*.4))}
        if(nat){yaw+=rnd()*6.2832;if(nat===1)sc=.74+rnd()*.52}}
      copies.push({x,z,yaw,sc});
    }
    const meshes=[];
    // tilt lays it over (90 is on its side, along x before it is turned): it turns about its own
    // middle and is then set back down, so `at` stays where its lowest point is
    const tl=(so.tilt||0)*Math.PI/180,ct=Math.cos(tl),stl=Math.sin(tl),hm=so.size[1]/2;
    const local=pieces.map(pc=>{const m=mdlMesh(pc),cy=Math.cos(pc.r||0),sy=Math.sin(pc.r||0);
      m.v=m.v.map(p=>{let x=p[0]*cy+p[2]*sy+pc.x,y=p[1]+pc.y,z=-p[0]*sy+p[2]*cy+pc.z;
        if(tl){const yy=y-hm;y=x*stl+yy*ct+hm;x=x*ct-yy*stl}
        return [x,y,z]});return m});
    let drop=0;if(tl){drop=1e9;local.forEach(m=>m.v.forEach(p=>{if(p[1]<drop)drop=p[1]}))}
    copies.forEach((cp,ci)=>{pieces.forEach((pc,pi)=>{
      const CY=Math.cos(cp.yaw),SY=Math.sin(cp.yaw),src=local[pi];
      const m={v:src.v.map(p=>{const x=p[0]*cp.sc,y=(p[1]-drop)*cp.sc,z=p[2]*cp.sc;return [x*CY+z*SY+cp.x,y+so.at[1],-x*SY+z*CY+cp.z]}),
        f:ci?src.f.map(fc=>({i:fc.i,lines:fc.lines,c:fc.c})):src.f};
      const round=pc.k==='sph'||pc.k==='dome'||pc.k==='ring'||(pc.k==='cone'&&(pc.n||16)>=10);
      mdlFinish(m,pc.rough?2:round||pc.leaf?1:0);
      m.c=mdlRGB(pc.c);m.leaf=!!pc.leaf;m.flow=!!pc.flow;m.plate=!!pc.plate;
      m.straight=!round&&!pc.leaf&&!pc.rough&&pc.k!=='arch';
      meshes.push(m)})});
    let lo=[1e9,1e9,1e9],hi=[-1e9,-1e9,-1e9];
    meshes.forEach(m=>m.v.forEach(p=>{for(let a=0;a<3;a++){if(p[a]<lo[a])lo[a]=p[a];if(p[a]>hi[a])hi[a]=p[a]}}));
    out.push({so,i:si,meshes,lo,hi,flat:hi[1]-lo[1]<Math.max(hi[0]-lo[0],hi[2]-lo[2])*.03,
      move:so.move||MDL_MOVE[so.shape]||''});
  });
  // fit: the longest side becomes MDL_FIT, the middle of the plan the origin, the lowest point the
  // sheet. Mountains, clouds and what flies are a backdrop: the eye frames what stands in front of them.
  let lo=[1e9,1e9,1e9],hi=[-1e9,-1e9,-1e9];
  const back={mountain:1,cloud:1,bird:1,plane:1},front=out.filter(s=>!back[s.so.shape]);
  (front.length?front:out).forEach(s=>{for(let a=0;a<3;a++){if(s.lo[a]<lo[a])lo[a]=s.lo[a];if(s.hi[a]>hi[a])hi[a]=s.hi[a]}});
  if(!out.length){lo=[0,0,0];hi=[1,1,1]}
  const ext=Math.max(hi[0]-lo[0],hi[2]-lo[2],(hi[1]-lo[1])*1.05,.001),k=MDL_FIT/ext;
  const cx=(lo[0]+hi[0])/2,cz=(lo[2]+hi[2])/2,y0=Math.min(lo[1],0);
  const fit=p=>{p[0]=(p[0]-cx)*k;p[1]=(p[1]-y0)*k;p[2]=(p[2]-cz)*k};
  out.forEach(s=>{s.meshes.forEach(m=>m.v.forEach(fit));fit(s.lo);fit(s.hi);
    s.c=[(s.lo[0]+s.hi[0])/2,s.lo[1],(s.lo[2]+s.hi[2])/2]});
  const W=(hi[0]-lo[0])*k,H=(hi[1]-y0)*k,D=(hi[2]-lo[2])*k;
  let far=0;out.forEach(s=>{far=Math.max(far,Math.hypot(Math.max(Math.abs(s.lo[0]),Math.abs(s.hi[0])),Math.max(Math.abs(s.lo[2]),Math.abs(s.hi[2]))))});
  return {solids:out,W,H,D,R:Math.max(Math.hypot(W,D)/2,H*.5,2),far:Math.max(far,2),k};
}

/* the order things are inked and raised: the ground first, then outward from the middle */
function mdlOrder(B){
  const key=s=>(s.flat?0:1e3)+Math.hypot(s.c[0],s.c[2])+(s.so.count>1?40:0)+s.lo[1]*2;
  const idx=B.solids.map((s,i)=>i).sort((a,b)=>key(B.solids[a])-key(B.solids[b]));
  const rank=[];idx.forEach((si,r)=>{rank[si]=idx.length>1?r/(idx.length-1):0});
  return rank;
}

/* ---------- the still drawing: ink on the sheet, in SVG ---------- */
/* An axonometric view with hidden lines removed the old way: faces sorted far to near, each
   painted over what is behind it, then its drawn edges. Shade is hatching (three weights). */
function mdlStill(host,model,style,opts){
  opts=opts||{};
  const B=mdlBuild(model),L=MDL_LOOK[style]||MDL_LOOK.paper,holo=style==='hologram';
  const Wd=Math.max(280,host.clientWidth||900),Hd=Math.max(240,host.clientHeight||520);
  const svg=sSvg('svg',{class:'mdl-svg mdl-'+style,viewBox:`0 0 ${Wd} ${Hd}`,width:Wd,height:Hd,role:'img',
    'aria-label':(model.title||'A model')+', drawn in 3D'});
  const uid='mdl'+(++STAGE_UID),defs=sSvg('defs');svg.append(defs);
  const ink=mdlHex(L.ink),paper=mdlHex(L.paper);
  // the sheet: fibres in the paper, a grid on the blueprint
  if(style==='paper'){
    const fl=sSvg('filter',{id:uid+'-grain',x:0,y:0,width:'100%',height:'100%'});
    fl.append(sSvg('feTurbulence',{type:'fractalNoise',baseFrequency:'.9 .35',numOctaves:2,seed:7,result:'n'}),
      sSvg('feColorMatrix',{in:'n',type:'matrix',values:'0 0 0 0 .2  0 0 0 0 .13  0 0 0 0 .06  0 0 0 .22 0'}),
      sSvg('feComposite',{operator:'over',in2:'SourceGraphic'}));
    defs.append(fl);
    svg.append(sSvg('rect',{x:0,y:0,width:Wd,height:Hd,fill:L.bg}),sSvg('rect',{x:0,y:0,width:Wd,height:Hd,fill:L.bg,filter:`url(#${uid}-grain)`}));
  }else{
    svg.append(sSvg('rect',{x:0,y:0,width:Wd,height:Hd,fill:L.bg}));
    if(style==='blueprint'){const g=sSvg('pattern',{id:uid+'-grid',width:32,height:32,patternUnits:'userSpaceOnUse'});
      g.append(sSvg('path',{d:'M32 0H0V32',fill:'none',stroke:'rgba(255,255,255,.13)','stroke-width':1}));defs.append(g);
      svg.append(sSvg('rect',{x:0,y:0,width:Wd,height:Hd,fill:`url(#${uid}-grid)`}))}
  }
  // three weights of hatching
  [['h1',7,.5,0],['h2',5,.62,0],['h3',5,.62,1]].forEach(q=>{
    const pt=sSvg('pattern',{id:uid+'-'+q[0],width:q[1],height:q[1],patternUnits:'userSpaceOnUse',patternTransform:'rotate(-45)'});
    pt.append(sSvg('line',{x1:0,y1:q[1]/2,x2:q[1],y2:q[1]/2,stroke:ink,'stroke-width':.9,opacity:q[2]}));
    if(q[3])pt.append(sSvg('line',{x1:q[1]/2,y1:0,x2:q[1]/2,y2:q[1],stroke:ink,'stroke-width':.9,opacity:q[2]}));
    defs.append(pt)});
  if(holo){const gl=sSvg('filter',{id:uid+'-glow',x:'-20%',y:'-20%',width:'140%',height:'140%'});
    gl.append(sSvg('feGaussianBlur',{stdDeviation:2.2,result:'b'}));const mg=sSvg('feMerge');
    mg.append(sSvg('feMergeNode',{in:'b'}),sSvg('feMergeNode',{in:'SourceGraphic'}));gl.append(mg);defs.append(gl)}
  // the view: turned and tipped, drawn to scale (no perspective: a drawing, not a photograph)
  const az=(opts.az==null?-22:opts.az)*Math.PI/180,el=(opts.el==null?27:opts.el)*Math.PI/180;
  const ca=Math.cos(az),sa=Math.sin(az),ce=Math.cos(el),se=Math.sin(el);
  const view=p=>{const x=p[0]*ca-p[2]*sa,z=p[0]*sa+p[2]*ca;return [x,p[1]*ce-z*se,p[1]*se+z*ce]};   // x right, y up, z towards the eye
  const eye=[sa*ce,se,ca*ce];                // towards the eye, in the model's space
  const sun=[-.45,.8,.4],sl=Math.hypot(sun[0],sun[1],sun[2]);
  let x0=1e9,x1=-1e9,y0=1e9,y1=-1e9;
  B.solids.forEach(s=>s.meshes.forEach(m=>m.v.forEach(p=>{const q=view(p);if(q[0]<x0)x0=q[0];if(q[0]>x1)x1=q[0];if(q[1]<y0)y0=q[1];if(q[1]>y1)y1=q[1]})));
  const pad=opts.pad==null?46:opts.pad,k=Math.min((Wd-pad*2)/Math.max(x1-x0,.01),(Hd-pad*2)/Math.max(y1-y0,.01));
  const ox=Wd/2-(x0+x1)/2*k,oy=Hd/2+(y0+y1)/2*k;
  const P=p=>{const q=view(p);return [ox+q[0]*k,oy-q[1]*k,q[2]]};
  // what it stands on: a wash that pools unevenly on paper, rings of light under a hologram
  const g0=sSvg('g',{class:'mdl-ground'});svg.append(g0);
  const gr=MDL_GROUND[model.ground];
  const rim=(r,n)=>{let d='';for(let i=0;i<=n;i++){const a=i/n*6.2832,w=1+(style==='paper'?Math.sin(a*3+1)*.05+Math.sin(a*7)*.03:0);
    const q=P([Math.cos(a)*r*w,0,Math.sin(a)*r*w]);d+=(i?'L':'M')+q[0].toFixed(1)+' '+q[1].toFixed(1)}return d+'Z'};
  if(holo){[1,.72,.44].forEach((r,i)=>g0.append(sSvg('path',{d:rim(B.R*1.08*r,64),fill:i?'none':'rgba(60,220,255,.06)',stroke:ink,'stroke-width':i?.8:1.4,opacity:i?.4:.8})));
    for(let i=0;i<12;i++){const a=i/12*6.2832,p=P([0,0,0]),q=P([Math.cos(a)*B.R*1.08,0,Math.sin(a)*B.R*1.08]);
      g0.append(sSvg('line',{x1:p[0],y1:p[1],x2:q[0],y2:q[1],stroke:ink,'stroke-width':.6,opacity:.25}))}}
  else if(gr&&style==='paper')g0.append(sSvg('path',{d:rim(B.R*1.12,72),fill:gr,opacity:.5}),sSvg('path',{d:rim(B.R*.9,72),fill:gr,opacity:.32}));
  else g0.append(sSvg('path',{d:rim(B.R*1.1,72),fill:'none',stroke:ink,'stroke-width':.8,'stroke-dasharray':'10 6',opacity:.35}));
  // faces, far to near
  const faces=[];
  B.solids.forEach(s=>s.meshes.forEach(m=>{
    const pv=m.v.map(P);
    const front=m.f.map(fc=>fc.n[0]*eye[0]+fc.n[1]*eye[1]+fc.n[2]*eye[2]>1e-4);
    m.f.forEach((fc,fi)=>{
      if(!front[fi]&&!holo)return;
      let z=0;fc.i.forEach(i=>{z+=pv[i][2]});z/=fc.i.length;
      const lit=(fc.n[0]*sun[0]+fc.n[1]*sun[1]+fc.n[2]*sun[2])/sl*.5+.5;
      let d='',ed='';fc.i.forEach((i,a)=>{d+=(a?'L':'M')+pv[i][0].toFixed(1)+' '+pv[i][1].toFixed(1)});d+='Z';
      fc.e.forEach((ek,a)=>{if(!ek)return;
        let draw=!!m.hard[ek];
        if(!draw&&!holo){const us=m.edges[ek];const other=us[0][0]===fi?(us[1]||us[0])[0]:us[0][0];draw=!front[other]}   // the outline of a round thing
        if(draw){const p=pv[fc.i[a]],q=pv[fc.i[(a+1)%fc.i.length]];ed+='M'+p[0].toFixed(1)+' '+p[1].toFixed(1)+'L'+q[0].toFixed(1)+' '+q[1].toFixed(1)}});
      (fc.lines||[]).forEach(ln=>{const p=pv[ln[0]],q=pv[ln[1]];ed+='M'+p[0].toFixed(1)+' '+p[1].toFixed(1)+'L'+q[0].toFixed(1)+' '+q[1].toFixed(1)});
      faces.push({z,d,ed,lit,c:fc.c?mdlRGB(fc.c):m.c,front:front[fi],plate:m.plate})})}));
  faces.sort((a,b)=>a.z-b.z);
  const g=sSvg('g',{class:'mdl-ink','stroke-linecap':'round','stroke-linejoin':'round'});if(holo)g.setAttribute('filter',`url(#${uid}-glow)`);
  svg.append(g);
  faces.forEach(fc=>{
    if(holo){g.append(sSvg('path',{d:fc.d,fill:fc.front?'rgba(70,225,255,.07)':'none',stroke:'none'}));
      if(fc.ed&&fc.front)g.append(sSvg('path',{d:fc.ed,fill:'none',stroke:fc.c?mdlHex(fc.c.map((x,i)=>x*.5+L.ink[i]*.5)):ink,'stroke-width':1.1}));return}
    const base=fc.c&&style==='paper'?mdlHex(fc.c.map((x,i)=>(x*(.74+.26*fc.lit))*.74+L.paper[i]*.26)):paper;
    g.append(sSvg('path',{d:fc.d,fill:base,stroke:base,'stroke-width':.6}));
    if(!fc.plate){const hk=fc.lit<.3?'h3':fc.lit<.46?'h2':fc.lit<.6?'h1':'';
      if(hk)g.append(sSvg('path',{d:fc.d,fill:`url(#${uid}-${hk})`,stroke:'none',opacity:style==='paper'?.8:.5}))}
    if(fc.ed)g.append(sSvg('path',{d:fc.ed,fill:'none',stroke:ink,'stroke-width':style==='paper'?1.25:1}))});
  // what falls: a few, caught mid-air
  const wx=MDL_WEATHER[model.weather]||(B.solids.some(s=>s.so.shape==='blossom')&&!model.weather?MDL_WEATHER.petals:null);
  if(wx){const R=mdlRnd(77),gw=sSvg('g',{class:'mdl-wx'});
    for(let i=0;i<Math.min(90,wx.n/3);i++){const q=P([(R()-.5)*B.R*2,R()*Math.max(B.H,6)*1.1,(R()-.5)*B.R*2]);
      gw.append(sSvg('ellipse',{cx:q[0],cy:q[1],rx:wx.sz*.42,ry:wx.sz*.26,fill:wx.c,opacity:.55+R()*.4,transform:`rotate(${Math.round(R()*180)} ${q[0].toFixed(1)} ${q[1].toFixed(1)})`}))}
    svg.append(gw)}
  // names, on leaders, kept clear of each other
  const tags=[],gt=sSvg('g',{class:'mdl-tags'});
  const named={};
  B.solids.forEach(s=>{const text=opts.tag?opts.tag(s.so):s.so.label;if(!text||named[text])return;named[text]=1;
    const q=P([(s.lo[0]+s.hi[0])/2,s.hi[1],(s.lo[2]+s.hi[2])/2]);tags.push({x:q[0],y:q[1],text,s})});
  // a photograph cannot be turned to read a crowded name: it keeps the eight biggest things' names
  const vol=t=>(t.s.hi[0]-t.s.lo[0])*(t.s.hi[1]-t.s.lo[1])*(t.s.hi[2]-t.s.lo[2])/(t.s.so.count||1);
  const keep=tags.sort((a,b)=>vol(b)-vol(a)).slice(0,window.STAGE_STILL?8:14).sort((a,b)=>a.y-b.y),used=[];
  keep.forEach(t=>{let y=t.y-22;const wpx=t.text.length*7.5+16;
    let x=Math.max(wpx/2+4,Math.min(Wd-wpx/2-4,t.x));
    for(let n=0;n<12&&used.some(u=>Math.abs(u.y-y)<19&&Math.abs(u.x-x)<(u.w+wpx)/2+8);n++)y-=19;
    y=Math.max(14,y);used.push({x,y,w:wpx});
    gt.append(sSvg('line',{x1:t.x,y1:t.y-2,x2:x,y2:y+5,stroke:ink,'stroke-width':.8,opacity:.7}),
      sSvg('circle',{cx:t.x,cy:t.y-2,r:2,fill:ink}));
    const tx=sSvg('text',{x,y,'text-anchor':'middle',class:'mdl-tag'},t.text);tx.style.fill=ink;gt.append(tx)});
  svg.append(gt);
  host.append(svg);
  return {B,svg};
}

/* ---------- the shaders ---------- */
var MDL_SWAY='vec3 mdlSway(vec3 p,float s,float t,float amp){if(s>0.){float ph=t*1.25+p.x*.33+p.z*.27;p.x+=sin(ph)*s*amp;p.z+=cos(ph*.8)*s*amp*.6;}return p;}';
var MDL_NOISE='float mdlH(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}'+
  'float mdlN(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(mdlH(i),mdlH(i+vec2(1.,0.)),f.x),mix(mdlH(i+vec2(0.,1.)),mdlH(i+vec2(1.,1.)),f.x),f.y);}';
var MDL_VS_FILL='attribute vec3 aColor;attribute float aSway;uniform float uTime,uAmp;varying vec3 vN,vC,vW;'+MDL_SWAY+
  'void main(){vec3 p=mdlSway(position,aSway,uTime,uAmp);vec4 w=modelMatrix*vec4(p,1.);vW=w.xyz;vN=normalize(mat3(modelMatrix)*normal);vC=aColor;gl_Position=projectionMatrix*viewMatrix*w;}';
var MDL_FS_FILL='uniform vec3 uPaper,uInk,uLight;uniform float uStyle,uWash,uTime,uTop,uHatch,uSel,uFlow,uPx,uDim;varying vec3 vN,vC,vW;'+MDL_NOISE+
  'float pen(float t,float w){float s=abs(fract(t)-.5);return 1.-smoothstep(w,w+.09,s);}'+
  'void main(){vec3 n=normalize(vN);if(!gl_FrontFacing)n=-n;float l=dot(n,normalize(uLight))*.5+.5;vec2 fc=gl_FragCoord.xy/uPx;'+
  'if(uStyle<1.5){'+
    'float g=mdlN(fc*.03)*.5+mdlN(fc*.1)*.32+mdlH(floor(fc))*.18;'+
    'vec3 base=uPaper*(.965+.07*g);'+
    'if(vC.r>=0.&&uStyle<.5){vec3 wash=vC*(.7+.3*l);wash=mix(wash,wash*(.8+.42*g),.7);base=mix(base,mix(wash,uPaper,.26),uWash);}'+
    'float h=0.;float d=clamp((.62-l)*2.6,0.,1.);'+
    'h+=pen((fc.x+fc.y)/6.5+mdlN(fc*.05)*.35,.1)*d;'+
    'h+=pen((fc.x-fc.y)/6.5+mdlN(fc*.05+9.)*.35,.1)*clamp((.36-l)*4.,0.,1.);'+
    'if(uFlow>0.){float r=pen(vW.z*1.6+sin(vW.x*1.1+uTime*.9)*.35-uTime*.25,.05);h=max(h*.3,r*.5);}'+
    'base=mix(base,uInk,clamp(h,0.,1.)*uHatch);'+
    'base=mix(base,uInk,uSel*.2);'+
    'gl_FragColor=vec4(base,1.);'+
  '}else{'+
    'if(vW.y>uTop)discard;'+
    'vec3 v=normalize(cameraPosition-vW);float fr=pow(1.-abs(dot(n,v)),2.6);'+
    'float scan=.62+.38*sin(vW.y*26.-uTime*3.2);'+
    'vec3 c=vC.r<0.?uInk:mix(uInk,vC,.55);'+
    'float a=(.035+.95*fr)*scan+smoothstep(.5,0.,uTop-vW.y)*.5+uSel*.25;a*=uDim;'+
    'gl_FragColor=vec4(c*a,a);'+
  '}}';
var MDL_VS_HULL='attribute vec3 aHull;attribute float aSway;uniform float uTime,uAmp,uW;uniform vec2 uRes;'+MDL_SWAY+
  'void main(){vec3 p=mdlSway(position,aSway,uTime,uAmp);vec4 c=projectionMatrix*modelViewMatrix*vec4(p,1.);'+
  'vec4 c2=projectionMatrix*modelViewMatrix*vec4(p+aHull*.02,1.);vec2 dir=(c2.xy/c2.w-c.xy/c.w)*uRes;float L=length(dir);'+
  'if(L>1e-5)c.xy+=dir/L*uW*2./uRes*c.w;gl_Position=c;}';
var MDL_FS_HULL='uniform vec3 uInk;void main(){gl_FragColor=vec4(uInk,1.);}';
var MDL_VS_LINE='attribute vec3 aOther;attribute float aSide,aSeed,aSway;uniform float uTime,uAmp,uLW;uniform vec2 uRes;varying vec3 vW;varying float vS;'+MDL_SWAY+
  'void main(){vec3 p=mdlSway(position,aSway,uTime,uAmp),q=mdlSway(aOther,aSway,uTime,uAmp);'+
  'vec4 ma=modelViewMatrix*vec4(p,1.),mb=modelViewMatrix*vec4(q,1.);ma.xyz*=.9988;mb.xyz*=.9988;vec4 a=projectionMatrix*ma,b=projectionMatrix*mb;'+
  'vec2 d=(b.xy/b.w-a.xy/a.w)*uRes;float L=length(d);d=L>1e-5?d/L:vec2(1.,0.);'+
  'a.xy+=vec2(-d.y,d.x)*aSide*uLW*(.72+.56*aSeed)/uRes*a.w;gl_Position=a;vW=(modelMatrix*vec4(p,1.)).xyz;vS=aSeed;}';
var MDL_FS_LINE='uniform vec3 uInk;uniform float uStyle,uTop,uTime,uDim;varying vec3 vW;varying float vS;'+
  'void main(){if(uStyle>1.5){if(vW.y>uTop)discard;float a=(.7+.3*sin(vW.y*26.-uTime*3.2))*uDim;gl_FragColor=vec4(uInk*a,a);}'+
  'else gl_FragColor=vec4(uInk,uStyle<.5?.86+.14*vS:.95);}';
/* the sheet under it: paper with fibres and a wash, a ruled blue sheet, or rings of light */
var MDL_VS_SHEET='varying vec3 vW;void main(){vec4 w=modelMatrix*vec4(position,1.);vW=w.xyz;gl_Position=projectionMatrix*viewMatrix*w;}';
var MDL_FS_SHEET='uniform vec3 uPaper,uInk,uGround;uniform float uStyle,uR,uHas,uTime,uPx,uShow;varying vec3 vW;'+MDL_NOISE+
    'void main(){vec2 fc=gl_FragCoord.xy/uPx;float r=length(vW.xz);'+
  'if(uStyle<.5){float g=mdlN(fc*.03)*.5+mdlN(fc*.1)*.32+mdlH(floor(fc))*.18;float fib=mdlN(vec2(fc.x*.05,fc.y*.9))*.03;'+
    'vec3 c=uPaper*(.965+.07*g-fib);'+
    'float edge=uR*(1.06+.1*mdlN(vW.xz*.22)+.05*mdlN(vW.xz*.9));float m=(1.-smoothstep(edge-.9,edge,r))*uHas*uShow;'+
    'vec3 wash=mix(uGround,uGround*(.82+.36*mdlN(vW.xz*.5+3.)),.7);float pool=smoothstep(edge-2.2,edge-.2,r)*.25;'+
    'c=mix(c,mix(wash,c,.3),m*(.62+pool));'+
    'vec2 gq=abs(fract(vW.xz/2.-.5)-.5)/fwidth(vW.xz/2.);float gl=1.-min(min(gq.x,gq.y),1.);c=mix(c,uInk,gl*.07*(1.-smoothstep(uR*1.3,uR*2.2,r)));'+
    'gl_FragColor=vec4(c,1.);'+
  '}else if(uStyle<1.5){vec3 c=uPaper*(.97+.05*mdlN(fc*.04));'+
    'vec2 a=abs(fract(vW.xz/2.-.5)-.5)/fwidth(vW.xz/2.);vec2 b=abs(fract(vW.xz/10.-.5)-.5)/fwidth(vW.xz/10.);'+
    'float g1=1.-min(min(a.x,a.y),1.),g2=1.-min(min(b.x,b.y),1.);float fade=1.-smoothstep(uR*1.6,uR*3.4,r);'+
    'c=mix(c,uInk,(g1*.1+g2*.2)*fade);gl_FragColor=vec4(c,1.);'+
  '}else{float ring=0.;for(int i=1;i<=4;i++){float rr=uR*1.08*float(i)/4.;ring+=1.-smoothstep(0.,.06,abs(r-rr));}'+
    'float ang=atan(vW.z,vW.x);'+
    'float sp=1.-smoothstep(0.,.012,abs(fract(ang/6.2832*24.+.5)-.5));'+
    'float in_=1.-smoothstep(uR*1.08,uR*1.1,r);float a=(ring*.55+sp*.16*in_+in_*.05)*(.8+.2*sin(uTime*2.+r))*uShow;'+
    'gl_FragColor=vec4(uInk*a,a);}}';

/* ---------- the live painter ---------- */
async function mdlGL(host,model,style,opts){
  opts=opts||{};
  let T;
  try{T=(typeof WORLD!=='undefined'&&WORLD.T)||(typeof OF3!=='undefined'&&OF3.T)||await import('/assets/three.module.min.js')}catch(e){return null}
  if(!host.isConnected)return null;
  const cv=document.createElement('canvas');cv.className='mdl-cv';
  let R;
  try{R=new T.WebGLRenderer({canvas:cv,antialias:true,alpha:false,powerPreference:'low-power'})}catch(e){return null}
  host.append(cv);
  const px=Math.min(window.devicePixelRatio||1,2);R.setPixelRatio(px);
  const B=mdlBuild(model),rank=mdlOrder(B);
  const S=new T.Scene(),cam=new T.PerspectiveCamera(30,1,.1,600),root=new T.Group();S.add(root);
  const U={uTime:{value:0},uRes:{value:new T.Vector2(1,1)},uPaper:{value:new T.Color()},uInk:{value:new T.Color()},
    uStyle:{value:0},uTop:{value:1e4},uHatch:{value:.6},uLight:{value:new T.Vector3(-.45,.8,.4)},uPx:{value:px},
    uLW:{value:1.6*px},uW:{value:1.5*px},uAmp:{value:0},uDim:{value:1}};
  const mats=[];
  const mk=(vs,fs,extra,o)=>{const m=new T.ShaderMaterial(Object.assign({vertexShader:vs,fragmentShader:fs,
    uniforms:Object.assign({},U,extra||{})},o||{}));mats.push(m);return m};
  // the sheet
  const sheetU={uGround:{value:new T.Color(MDL_GROUND[model.ground]||'#c8a675')},uR:{value:B.R},uHas:{value:MDL_GROUND[model.ground]?1:0},uShow:{value:1}};
  const sheet=new T.Mesh(new T.CircleGeometry(Math.max(B.R,B.far)*14,48),mk(MDL_VS_SHEET,MDL_FS_SHEET,sheetU));
  sheet.rotation.x=-Math.PI/2;sheet.position.y=-.004;sheet.renderOrder=-2;S.add(sheet);
  // a projector under a hologram: a cone of light and the puck it comes from
  const beam=new T.Mesh(new T.CylinderGeometry(B.R*1.08,B.R*.1,B.R*.9,40,1,true),new T.ShaderMaterial({transparent:true,depthWrite:false,
    blending:T.AdditiveBlending,side:T.DoubleSide,uniforms:{uInk:U.uInk,uTime:U.uTime,uShow:sheetU.uShow},
    vertexShader:'varying vec2 vU;void main(){vU=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
    fragmentShader:'uniform vec3 uInk;uniform float uTime,uShow;varying vec2 vU;void main(){float a=(1.-vU.y)*.34*(.75+.25*sin(vU.x*190.+uTime*1.3))*(.86+.14*sin(uTime*9.))*uShow;gl_FragColor=vec4(uInk*a,a);}'}));
  const lift=B.R*.6;beam.position.y=-B.R*.45;beam.scale.y=lift/(B.R*.9);beam.position.y=-lift/2;beam.visible=false;beam.renderOrder=-1;S.add(beam);
  const puck=new T.Mesh(new T.CylinderGeometry(B.R*.16,B.R*.2,B.R*.05,32),new T.MeshBasicMaterial({color:0x0a2a3a}));
  const puckTop=new T.Mesh(new T.RingGeometry(B.R*.05,B.R*.11,40),new T.MeshBasicMaterial({color:0x8ff6ff,transparent:true,opacity:.55,blending:T.AdditiveBlending,depthWrite:false}));
  puck.position.y=-lift-B.R*.025;puckTop.rotation.x=-Math.PI/2;puckTop.position.y=-lift+.01;puck.visible=puckTop.visible=false;S.add(puck,puckTop);
  // each solid: its faces, its outline, its lines
  const solids=[],picks=[];
  B.solids.forEach((s,si)=>{
    const pos=[],nor=[],hull=[],col=[],sway=[];
    const lp=[],lo=[],lside=[],lseed=[],lsway=[],lidx=[],segs=[];
    const cx=s.c[0],cz=s.c[2],rn=mdlRnd(31+si*17);
    s.meshes.forEach(m=>{
      let ylo=1e9,yhi=-1e9;m.v.forEach(p=>{if(p[1]<ylo)ylo=p[1];if(p[1]>yhi)yhi=p[1]});
      const sways=m.leaf||s.move==='sway';     // leaves always, and anything told to (a flag, a reed)
      const sw=p=>sways?(m.leaf?.35:0)+(m.leaf?.65:1)*(p[1]-ylo)/Math.max(yhi-ylo,.001):0;
      const c=m.c||[-1,-1,-1];
      m.f.forEach(fc=>{const fcol=fc.c?mdlRGB(fc.c):c;for(let t=1;t<fc.i.length-1;t++)[0,t,t+1].forEach(a=>{const p=m.v[fc.i[a]],n=fc.vn[a],hn=m.hn[fc.i[a]];
        pos.push(p[0]-cx,p[1],p[2]-cz);nor.push(n[0],n[1],n[2]);hull.push(hn[0],hn[1],hn[2]);col.push(fcol[0],fcol[1],fcol[2]);sway.push(sw(p))})});
      const seg=(a,b,over)=>{let ax=a[0],ay=a[1],az=a[2],bx=b[0],by=b[1],bz=b[2];
        if(over){   // a draughtsman's line runs a little past the corner
          const L=Math.hypot(bx-ax,by-ay,bz-az)||1,o1=Math.min(L*.07,.16)*rn(),o2=Math.min(L*.07,.16)*rn();
          const dx=(bx-ax)/L,dy=(by-ay)/L,dz=(bz-az)/L;ax-=dx*o1;ay-=dy*o1;az-=dz*o1;bx+=dx*o2;by+=dy*o2;bz+=dz*o2}
        segs.push({a:[ax-cx,ay,az-cz],b:[bx-cx,by,bz-cz],s:(sw(a)+sw(b))/2,y:Math.min(ay,by)})};
      Object.keys(m.hard).forEach(ek=>{const u=m.edges[ek][0],fc=m.f[u[0]];
        seg(m.v[fc.i[u[1]]],m.v[fc.i[(u[1]+1)%fc.i.length]],m.straight)});
      m.f.forEach(fc=>(fc.lines||[]).forEach(ln=>seg(m.v[ln[0]],m.v[ln[1]],false)));
    });
    segs.sort((a,b)=>a.y-b.y||a.a[0]-b.a[0]);
    segs.forEach(sg=>{const k=lp.length/3,sd=rn();
      [[sg.a,sg.b,1],[sg.a,sg.b,-1],[sg.b,sg.a,-1],[sg.b,sg.a,1]].forEach(q=>{lp.push(q[0][0],q[0][1],q[0][2]);lo.push(q[1][0],q[1][1],q[1][2]);lside.push(q[2]);lseed.push(sd);lsway.push(sg.s)});
      lidx.push(k,k+1,k+2,k+2,k+1,k+3)});
    const g=new T.BufferGeometry();
    g.setAttribute('position',new T.Float32BufferAttribute(pos,3));g.setAttribute('normal',new T.Float32BufferAttribute(nor,3));
    g.setAttribute('aHull',new T.Float32BufferAttribute(hull,3));g.setAttribute('aColor',new T.Float32BufferAttribute(col,3));
    g.setAttribute('aSway',new T.Float32BufferAttribute(sway,1));
    const lg=new T.BufferGeometry();
    lg.setAttribute('position',new T.Float32BufferAttribute(lp,3));lg.setAttribute('aOther',new T.Float32BufferAttribute(lo,3));
    lg.setAttribute('aSide',new T.Float32BufferAttribute(lside,1));lg.setAttribute('aSeed',new T.Float32BufferAttribute(lseed,1));
    lg.setAttribute('aSway',new T.Float32BufferAttribute(lsway,1));lg.setIndex(lidx);
    const pen=Math.max(.5,Math.min(1,Math.pow((s.hi[1]-s.lo[1])/(s.so.count>1?s.so.count>8?5.5:4.4:3.2),.6)));
    const own={uWash:{value:0},uSel:{value:0},uFlow:{value:s.move==='flow'?1:0},uLW:{value:1},uW:{value:1}};
    const fill=new T.Mesh(g,mk(MDL_VS_FILL,MDL_FS_FILL,own,{polygonOffset:true,polygonOffsetFactor:1,polygonOffsetUnits:1}));
    const out=new T.Mesh(g,mk(MDL_VS_HULL,MDL_FS_HULL,own,{side:T.BackSide}));
    const lines=new T.Mesh(lg,mk(MDL_VS_LINE,MDL_FS_LINE,own,{side:T.DoubleSide,transparent:true}));
    lines.frustumCulled=false;out.frustumCulled=false;
    const grp=new T.Group();grp.position.set(cx,0,cz);grp.add(fill,out,lines);root.add(grp);
    fill.userData.si=si;picks.push(fill);
    solids.push({s,grp,fill,out,lines,own,pen,nseg:segs.length,base:[cx,0,cz],r:Math.hypot(cx,cz),a0:Math.atan2(cz,cx),
      rank:rank[si],h:Math.max(s.hi[1],.01),tall:s.hi[1]-s.lo[1]});
  });
  // what falls or drifts
  const wxK=model.weather&&model.weather!=='none'?model.weather:(B.solids.some(s=>s.so.shape==='blossom')?'petals':'');
  let wx=null;
  if(MDL_WEATHER[wxK]){const w=MDL_WEATHER[wxK],n=w.n,p=[],sd=[],rn=mdlRnd(911),top=Math.max(B.H*1.25,8);
    for(let i=0;i<n;i++){const a=rn()*6.2832,r=Math.sqrt(rn())*B.R*1.25;p.push(Math.cos(a)*r,rn()*top,Math.sin(a)*r);sd.push(rn())}
    const g=new T.BufferGeometry();g.setAttribute('position',new T.Float32BufferAttribute(p,3));g.setAttribute('aSeed',new T.Float32BufferAttribute(sd,1));
    const m=new T.ShaderMaterial({transparent:true,depthWrite:false,blending:w.glow?T.AdditiveBlending:T.NormalBlending,
      uniforms:{uTime:U.uTime,uC:{value:new T.Color(w.c)},uTop:{value:top},uSp:{value:w.sp},uDr:{value:w.dr},uSz:{value:w.sz*px},uOn:{value:0},uGlow:{value:w.glow?1:0}},
      vertexShader:'attribute float aSeed;uniform float uTime,uTop,uSp,uDr,uSz;varying float vA;void main(){vec3 p=position;float t=uTime;'+
        'if(uSp!=0.){p.y=mod(p.y-t*uSp*(.7+.6*aSeed),uTop);}else{p.y+=sin(t*.7+aSeed*40.)*.6;}'+
        'p.x+=sin(t*.6+aSeed*31.)*uDr;p.z+=cos(t*.5+aSeed*17.)*uDr*.8;'+
        'vA=uSp==0.?.35+.65*abs(sin(t*1.7+aSeed*50.)):1.;vA*=smoothstep(0.,.6,p.y)*(1.-smoothstep(uTop*.9,uTop,p.y));'+
        'vec4 mv=modelViewMatrix*vec4(p,1.);gl_Position=projectionMatrix*mv;gl_PointSize=uSz*(.6+.8*aSeed)*(30./-mv.z);}',
      fragmentShader:'uniform vec3 uC;uniform float uOn,uGlow;varying float vA;void main(){vec2 q=gl_PointCoord-.5;float d=length(q*vec2(1.,1.5));if(d>.5)discard;'+
        'float a=(uGlow>0.?1.-d*2.:.9)*vA*uOn;gl_FragColor=uGlow>0.?vec4(uC*a,a):vec4(uC,a);}'});
    wx=new T.Points(g,m);wx.frustumCulled=false;wx.renderOrder=5;root.add(wx)}
  // names
  const tagHost=sEl('div','mdl-tags');host.append(tagHost);
  const tags=[];
  const named={};
  solids.forEach(o=>{const text=opts.tag?opts.tag(o.s.so):o.s.so.label;if(!text||tags.length>=14||named[text])return;named[text]=1;
    const el=sEl(opts.pick?'button':'span','mdl-tag',text);el.style.opacity='0';
    if(opts.pick){el.type='button';el.onclick=e=>{e.stopPropagation();opts.pick(o.s.so,o.s.i)}}
    tagHost.append(el);tags.push({el,o,w:text.length*6.8+18})});
  // state
  const st={style:'',t0:performance.now(),t:0,az:-.9,el:1.45,dist:1,azU:0,elU:0,zoom:1,user:false,lastTouch:performance.now(),
    explode:0,explodeTo:0,sel:-1,hover:-1,fit:0,stopped:false,running:false,last:0,done:false,seek:opts.seek};
  const look=()=>MDL_LOOK[st.style];
  const apply=s=>{st.style=s;const L=look();
    U.uPaper.value.setRGB(L.paper[0],L.paper[1],L.paper[2]);U.uInk.value.setRGB(L.ink[0],L.ink[1],L.ink[2]);
    U.uStyle.value=L.style;U.uHatch.value=L.hatch;U.uLW.value=L.lw*px;U.uW.value=L.hull*px;
    S.background=new T.Color(L.bg);host.dataset.style=s;
    const holo=s==='hologram';beam.visible=puck.visible=puckTop.visible=holo;
    sheet.material.transparent=holo;sheet.material.depthWrite=!holo;sheet.material.blending=holo?T.AdditiveBlending:T.NormalBlending;sheet.material.needsUpdate=true;
    solids.forEach(o=>{o.out.visible=!holo;o.own.uLW.value=L.lw*px*o.pen;o.own.uW.value=L.hull*px*o.pen;
      o.fill.material.transparent=holo;o.fill.material.depthWrite=!holo;o.fill.material.side=holo?T.DoubleSide:T.FrontSide;
      o.fill.material.blending=holo?T.AdditiveBlending:T.NormalBlending;
      o.lines.material.blending=holo?T.AdditiveBlending:T.NormalBlending;o.lines.material.depthWrite=!holo;o.lines.material.depthTest=!holo;
      o.fill.material.needsUpdate=true;o.lines.material.needsUpdate=true})};
  const BAR=46;       // the controls' strip: the eye frames the model in the room above it
  const size=()=>{const w=Math.max(160,host.clientWidth||640),h=Math.max(140,host.clientHeight||380);R.setSize(w,h,false);
    cam.aspect=w/(h+BAR);cam.setViewOffset(w,h+BAR,0,0,w,h);cam.updateProjectionMatrix();U.uRes.value.set(w*px,h*px)};
  const ease=u=>u<0?0:u>1?1:u*u*(3-2*u),back=u=>{if(u<=0)return 0;if(u>=1)return 1;const c=1.5;return 1+(c+1)*Math.pow(u-1,3)+c*Math.pow(u-1,2)};
  // the build, in seconds: the plan is inked, then it rises, then the colour comes
  const INK0=.25,INKW=2.3,INKD=.9,RISE0=3.1,RISEW=2.7,RISED=1.15,END=RISE0+RISEW+RISED+1.1;
  const v=new T.Vector3(),ray=new T.Raycaster(),ptr=new T.Vector2();
  const tall=B.H>Math.max(B.W,B.D)*1.25;
  const byY=solids.slice().sort((a,b)=>a.s.lo[1]-b.s.lo[1]);byY.forEach((o,i)=>{o.yr=byY.length>1?i/(byY.length-1):0});
  const frame=now=>{
    st.running=false;
    if(st.stopped)return;
    if(!host.isConnected){dispose();return}
    if(document.hidden){st.running=true;requestAnimationFrame(frame);return}
    if(now-st.last<30){st.running=true;requestAnimationFrame(frame);return}
    st.last=now;
    const t=st.seek!=null?st.seek:(now-st.t0)/1000;st.t=t;U.uTime.value=t;
    const holo=st.style==='hologram',L=look();
    // each solid
    let moving=t<END;
    solids.forEach(o=>{
      const a=INK0+o.rank*INKW,ink=holo?1:ease((t-a)/INKD);
      o.lines.geometry.setDrawRange(0,Math.round(o.nseg*ink)*6);
      const r0=RISE0+o.rank*RISEW,up=holo?1:(o.s.flat?ease((t-r0)/.5):back((t-r0)/RISED));
      o.grp.scale.y=Math.max(.0012,up);
      const shown=holo||t>r0;o.fill.visible=shown;o.out.visible=shown&&!holo&&up>.2;
      o.own.uWash.value=ease((t-r0-RISED*.55)/1.1);
      // pulled apart: up a tower, outward from the middle of anything else
      const e=st.explode;let x=o.base[0],y=0,z=o.base[2];
      if(e>0){if(tall)y+=o.yr*B.H*.55*e;else{x*=1+.7*e;z*=1+.7*e}}     // along its own layout, so a row of parts stays a row
      // what moves, once it stands
      const live=Math.max(0,t-END+1);
      if(live>0&&o.s.move){const m=o.s.move;
        if(m==='spin')o.grp.rotation.y=live*.6;
        else if(m==='bob')y+=Math.sin(live*1.4+o.rank*9)*Math.max(.05,o.tall*.04);
        else if(m==='drift'){const span=B.R*2.6;x=((o.base[0]+live*.35+span/2)%span+span)%span-span/2}
        else if(m==='orbit'){const a2=o.a0+live*.22,rr=Math.max(o.r,B.R*.3);x=Math.cos(a2)*rr;z=Math.sin(a2)*rr;o.grp.rotation.y=-a2-Math.PI/2+Math.PI;y+=Math.sin(live*1.1+o.rank*5)*.25}
      }
      o.grp.position.set(x,y,z);
      o.own.uSel.value+=((st.sel===o.s.i||st.hover===o.s.i?1:0)-o.own.uSel.value)*.25;
    });
    U.uAmp.value=.05*ease((t-END+1)/2);
    if(wx)wx.material.uniforms.uOn.value=ease((t-END+1.2)/2.5);
    // a hologram is swept in from the projector up
    U.uTop.value=holo?ease((t-.5)/3.4)*(B.H*1.7+1)+.001:1e4;
    U.uDim.value=holo?.9+.1*Math.sin(t*23.)*Math.sin(t*3.1):1;
    sheetU.uShow.value=holo?ease(t/.6):ease((t-RISE0+.4)/2.2);
    if(Math.abs(st.explodeTo-st.explode)>.002){st.explode+=(st.explodeTo-st.explode)*.14;moving=true}else st.explode=st.explodeTo;
    // the eye: over the sheet while it is drawn, then down and round it
    const k=holo?1:ease((t-RISE0+.5)/3.2);
    const elA=holo?.4:1.44+(.46-1.44)*k,azA=(holo?1.9:1.4+.55*k)+(st.user?0:Math.max(0,t-END)*.04)+(holo&&!st.user?t*.1:0);
    const el=Math.max(.06,Math.min(1.5,elA+st.elU)),az=azA+st.azU;
    const cy=(holo?B.H*.45-lift*.3:B.H*.42*k)+(tall?B.H*.25*st.explode:0);
    // far enough that every corner of its box is on the sheet, and no farther
    const dx=Math.cos(az)*Math.cos(el),dy=Math.sin(el),dz=Math.sin(az)*Math.cos(el);     // towards the eye
    const rx=-Math.sin(az),rz=Math.cos(az),ux=-Math.cos(az)*dy,uy=Math.cos(el),uz=-Math.sin(az)*dy;
    const tv=Math.tan(cam.fov*Math.PI/360)*.8,th=tv*cam.aspect,grow=1+st.explode*(tall?.45:.7);
    let fit=1;
    for(let c=0;c<8;c++){const px_=(c&1?B.W:-B.W)/2*grow,py_=(c&2?B.H*grow:(holo?-lift*.9:0))-cy,pz_=(c&4?B.D:-B.D)/2*grow;
      const zr=px_*dx+py_*dy+pz_*dz,xr=Math.abs(px_*rx+pz_*rz),yr=Math.abs(px_*ux+py_*uy+pz_*uz);
      fit=Math.max(fit,zr+xr/th,zr+yr/tv)}
    st.fit+=(fit-st.fit)*(st.fit>1?.12:1);
    const dist=st.fit*st.zoom;
    cam.position.set(dx*dist,cy+dy*dist,dz*dist);cam.lookAt(0,cy,0);
    cam.near=Math.max(.3,dist*.12);cam.far=dist*5+Math.max(B.R,B.far)*16;cam.updateProjectionMatrix();
    if(cv.width!==Math.round(Math.max(160,host.clientWidth)*px)||cv.height!==Math.round(Math.max(140,host.clientHeight)*px))size();
    R.render(S,cam);
    // names follow, and step aside for each other
    const W=host.clientWidth,H=host.clientHeight,used=[];
    tags.forEach(tg=>{const o=tg.o;v.set(o.grp.position.x,o.grp.position.y+o.h*o.grp.scale.y+.3,o.grp.position.z).project(cam);
      const on=(holo?t>1.2+o.rank*2:t>RISE0+o.rank*RISEW+RISED*.8)&&v.z<1;
      let x=(v.x+1)/2*W,y=(1-v.y)/2*H-10;
      const hit=used.some(u=>Math.abs(u.y-y)<20&&Math.abs(u.x-x)<(u.w+tg.w)/2);
      const show=on&&!hit&&x>20&&x<W-20&&y>14&&y<H-8;if(show)used.push({x,y,w:tg.w});
      tg.el.style.transform=`translate(${x.toFixed(1)}px,${y.toFixed(1)}px) translate(-50%,-100%)`;tg.el.style.opacity=show?'1':'0';
      tg.el.style.pointerEvents=show?'':'none'});
    if(!st.done&&t>=END){st.done=true;host.classList.add('mdl-built');if(opts.built)opts.built()}
    const alive=(now-st.lastTouch)/1000<MDL_LIFE_S;
    if(st.seek!=null){host.dataset.frame=String(st.seek);return}
    if(moving||alive){st.running=true;requestAnimationFrame(frame)}
    else host.classList.add('mdl-rest');
  };
  const wake=()=>{st.lastTouch=performance.now();host.classList.remove('mdl-rest');if(!st.running&&!st.stopped){st.running=true;requestAnimationFrame(frame)}};
  const dispose=()=>{if(st.stopped)return;st.stopped=true;
    S.traverse(o=>{if(o.geometry)o.geometry.dispose()});mats.forEach(m=>m.dispose());R.dispose();
    try{R.forceContextLoss()}catch(e){}
    if(ro)ro.disconnect()};
  // turning it: drag to turn, pinch or the buttons to come closer, a tap to pick
  let drag=null;const pts=new Map();
  cv.addEventListener('pointerdown',e=>{pts.set(e.pointerId,[e.clientX,e.clientY]);try{cv.setPointerCapture(e.pointerId)}catch(_){}
    drag={x:e.clientX,y:e.clientY,moved:0,az:st.azU,el:st.elU,pinch:0,zoom:st.zoom};wake()});
  cv.addEventListener('pointermove',e=>{
    if(!drag){   // pointing lights the thing under the pointer
      if(e.pointerType==='mouse'&&st.done){const i=pickAt(e);cv.style.cursor=i>=0&&opts.pick?'pointer':'grab';if(i!==st.hover){st.hover=i;wake()}}
      return}
    pts.set(e.pointerId,[e.clientX,e.clientY]);
    if(pts.size>=2){const a=[...pts.values()],d=Math.hypot(a[0][0]-a[1][0],a[0][1]-a[1][1]);
      if(!drag.pinch)drag.pinch=d;else st.zoom=Math.max(.35,Math.min(2.4,drag.zoom*drag.pinch/Math.max(d,1)));drag.moved=9;wake();return}
    const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.moved=Math.max(drag.moved,Math.abs(dx)+Math.abs(dy));
    if(drag.moved>4){st.user=true;st.azU=drag.az+dx*.008;st.elU=drag.el+dy*.006;wake()}});
  const up=e=>{pts.delete(e.pointerId);if(!drag)return;const d=drag;if(!pts.size)drag=null;
    if(d.moved<=4&&st.done){const i=pickAt(e);st.sel=i===st.sel?-1:i;if(i>=0&&opts.pick)opts.pick(B.solids[i].so,i);wake()}};
  cv.addEventListener('pointerup',up);cv.addEventListener('pointercancel',e=>{pts.delete(e.pointerId);drag=null});
  const pickAt=e=>{const r=cv.getBoundingClientRect();if(!r.width)return -1;
    ptr.set((e.clientX-r.left)/r.width*2-1,-((e.clientY-r.top)/r.height*2-1));ray.setFromCamera(ptr,cam);
    const hit=ray.intersectObjects(picks.filter(p=>p.visible),false).find(h=>!B.solids[h.object.userData.si].flat);
    return hit?hit.object.userData.si:-1};
  let ro=null;if(typeof ResizeObserver!=='undefined'){ro=new ResizeObserver(()=>{if(!host.isConnected){dispose();return}size();wake()});ro.observe(host)}
  if(opts.skip)st.t0-=END*1000;
  apply(style);size();st.running=true;requestAnimationFrame(frame);
  return {B,
    style:s=>{apply(s);st.t0=performance.now();st.done=false;st.user=false;st.azU=0;st.elU=0;host.classList.remove('mdl-built');wake()},
    replay:()=>{st.t0=performance.now();st.done=false;st.user=false;st.azU=0;st.elU=0;st.explodeTo=0;host.classList.remove('mdl-built');wake()},
    explode:on=>{st.explodeTo=on?1:0;wake()},
    zoom:f=>{st.zoom=Math.max(.35,Math.min(2.4,st.zoom*f));wake()},
    select:i=>{st.sel=i;wake()},
    dispose,state:st};
}

/* ---------- the drawing with its controls: what a scene and a blueprint both mount ---------- */
/* model: {solids, style, weather, ground, title}. opts: tag(solid) → the name over it,
   pick(solid, i) → a tap on it, still: true for a drawing with no controls. */
function mdlMount(host,model,opts){
  opts=opts||{};
  host.classList.add('mdl');host.textContent='';
  const kept=opts.key?(MDL_KEEP[opts.key]=MDL_KEEP[opts.key]||{}):{};
  const start=MDL_LOOK[kept.style]?kept.style:(MDL_LOOK[model.style]?model.style:'paper');
  const M={host,model,style:start,gl:null};host._mdl=M;
  const still=opts.still||window.STAGE_REPORT||stageReduced()||mdlLite()||!mdlGLok();
  const bar=sEl('div','mdl-bar');
  const paintStill=()=>{host.querySelectorAll('.mdl-svg').forEach(e=>e.remove());host.dataset.style=M.style;
    mdlStill(host,model,M.style,{tag:opts.tag});host.append(bar)};
  const seg=sEl('div','mdl-seg');seg.setAttribute('role','group');seg.setAttribute('aria-label','How it is drawn');
  const setStyle=s=>{M.style=s;kept.style=s;[...seg.children].forEach(b=>{const on=b.dataset.s===s;b.classList.toggle('on',on);b.setAttribute('aria-pressed',String(on))});
    if(M.gl)M.gl.style(s);else paintStill()};
  Object.keys(MDL_LOOK).forEach(s=>{const b=sEl('button','mdl-b'+(s===start?' on':''),MDL_LOOK[s].name.slice(0,s==='paper'?5:4));b.append(sEl('span','mdl-w',MDL_LOOK[s].name.slice(s==='paper'?5:4)));
    b.type='button';b.dataset.s=s;b.setAttribute('aria-label',MDL_LOOK[s].name);
    b.setAttribute('aria-pressed',String(s===start));b.onclick=()=>setStyle(s);seg.append(b)});
  if(!window.STAGE_STILL&&!opts.still)bar.append(seg);
  if(still){paintStill();
    if(!window.STAGE_REPORT&&!opts.still&&(stageReduced()||mdlLite()))host.title='A still drawing: this screen draws it without motion';
    // the layout box settles after the first paint: draw it again to fit
    if(typeof ResizeObserver!=='undefined'){let last='';const ro=new ResizeObserver(()=>{if(!host.isConnected){ro.disconnect();return}
      const k=host.clientWidth+'x'+host.clientHeight;if(k!==last){last=k;paintStill()}});ro.observe(host)}
    return M}
  host.append(bar);
  const acts=sEl('div','mdl-acts');
  const btn=(text,title,fn)=>{const cut=text.indexOf(' '),b=sEl('button','mdl-b',cut<0?text:text.slice(0,cut));if(cut>0)b.append(sEl('span','mdl-w',text.slice(cut)));
    b.type='button';b.title=title;b.setAttribute('aria-label',title);b.onclick=fn;acts.append(b);return b};
  let apart=false;
  const ex=btn('✥ Pull apart','Pull it apart, or put it back',()=>{apart=!apart;ex.classList.toggle('on',apart);ex.setAttribute('aria-pressed',String(apart));if(M.gl)M.gl.explode(apart)});
  ex.setAttribute('aria-pressed','false');
  btn('↻ Build again','Watch it being drawn and built again',()=>{apart=false;ex.classList.remove('on');if(M.gl)M.gl.replay()});
  btn('＋','Come closer',()=>M.gl&&M.gl.zoom(.82));btn('－','Step back',()=>M.gl&&M.gl.zoom(1.22));
  bar.append(acts);
  const hint=sEl('div','mdl-hint','Drag to turn it');host.append(hint);
  mdlGL(host,model,start,{tag:opts.tag,pick:opts.pick,seek:opts.seek!=null?opts.seek:window.MDL_SEEK,skip:!!kept.built,built:()=>{if(!kept.built)hint.classList.add('on');kept.built=true}}).then(gl=>{
    if(!host.isConnected){if(gl)gl.dispose();return}
    if(!gl){hint.remove();acts.remove();paintStill();return}   // no renderer after all: the ink drawing
    M.gl=gl;host.append(bar,hint)});
  return M;
}

/* the scene kind */
function stageModel(art,sc){
  const fr=sEl('div','stg-model');art.append(fr);
  const cur=typeof STAGE!=='undefined'&&STAGE.scenes&&STAGE.scenes[STAGE.at];
  mdlMount(fr,{solids:sc.solids||[],style:sc.style,weather:sc.weather,ground:sc.ground,title:sc.title},
    {key:cur&&cur.scene===sc?cur.id:''});
}
function stageModelMs(){return 9500}

/* ---------- a blueprint's own model ---------- */
/* What the thing looks like, for the blueprint's 3D view: the solids the agent gave, or, for a
   tower with heights, its parts stacked to scale (each a storey of the outline). */
function bpModelOf(sc){
  if(sc.model&&sc.model.length)return {solids:sc.model,style:sc.style||'paper',auto:false};
  if(sc.form!=='tower')return null;
  const ps=(sc.parts||[]).filter(p=>p.from!=null&&p.to!=null&&p.to>p.from);
  if(ps.length<2)return null;
  const lo=Math.min(...ps.map(p=>p.from)),hi=Math.max(...ps.map(p=>p.to)),span=hi-lo||1;
  const real=ps.filter(p=>p.width>1).map(p=>p.width),wide=real.length?Math.max(...real):span*.24;
  const wOf=p=>{const mid=((p.from+p.to)/2-lo)/span;
    return Math.max(p.width>1?p.width:p.width?p.width*wide:wide*(1-.55*mid),span*.012)};
  const up=ps.slice().sort((a,b)=>a.from-b.from);
  const solids=up.map((p,i)=>{const w=wOf(p),nx=up.slice(i+1).find(q=>q.from>=p.to-span*.01),hh=p.to-p.from;
    // it narrows towards the part above it, and its storeys are ruled round it
    return {shape:'cylinder',at:[0,p.from-lo,0],size:[w,hh,w],part:p.id,color:p.to<=0&&lo<0?'stone':'glass',
      _tp:nx?Math.max(.74,Math.min(1,wOf(nx)/w)):p.to>=hi-span*.01&&hh>w*4?.35:1,_bands:Math.max(1,Math.min(14,Math.round(hh/span*26)))}});
  // the ground it stands on, when part of it is below, and a rule beside it with the heights
  if(lo<0)solids.push({shape:'ring',at:[0,-lo-span*.003,0],size:[wide*3.4,span*.006,wide*3.4],label:'Ground'});
  const off=wide*1.25,t=span*.004,unit=sc.unit||'';
  solids.push({shape:'box',at:[off,0,0],size:[t,span,t]});
  stageTicks(lo,hi,5).concat([hi]).filter((v,i,a)=>v>=lo&&v<=hi&&a.indexOf(v)===i&&(v===hi||hi-v>span*.06)).forEach(v=>{
    solids.push({shape:'box',at:[off+wide*.09,v-lo-t/2,0],size:[wide*.18,t,t],label:bpFmt(v)+(unit?' '+unit:'')})});
  return {solids,style:sc.style||'paper',auto:true};
}
function bpModelView(st){
  const {draw,svg}=st.el;svg.style.display='none';
  const mdl=bpModelOf(st.sc);if(!mdl){st.mode='parts';return false}
  const box=sEl('div','bp-look bp-model');draw.append(box);
  const name={};(function walk(ps){(ps||[]).forEach(p=>{name[p.id]=p;walk(p.parts)})})(st.sc.parts);
  const top={};(st.sc.parts||[]).forEach(t=>{(function walk(ps){(ps||[]).forEach(p=>{top[p.id]=t.id;walk(p.parts)})})([t])});
  mdlMount(box,{solids:mdl.solids,style:mdl.style,title:st.sc.subject||st.sc.title},{key:st.sid,
    tag:so=>so.label||(so.part&&name[so.part]?name[so.part].name:''),
    pick:so=>{if(!so.part||!top[so.part])return;
      // a tap reads the part in the panel; a second tap on it opens it
      const id=top[so.part],p=name[id];
      if(st.sel===id&&bpKids(p).length){st.mode='parts';bpGo(st,[id]);return}
      st.sel=id;bpSpec(st)}});
  return true;
}
