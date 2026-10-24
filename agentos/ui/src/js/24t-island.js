/* ================= The island: the Office drawn as a place in the sea =================
   Settings → Appearance → Scene → Island, and the Office's own look "island" (office.py
   LOOKS). The same office as the 3D look (24k-office3d.js) and the same state (OFFICE):
   the rooms are still on their ring round the Brain, the desks are still where they were,
   and every walk, paper, balloon and meeting is decided by 24d-office.js exactly as
   before. What this file changes is only the place they stand in:

   - the rooms are open terraces on an island instead of boxes with walls (of3Room and
     of3Window skip their walls while OF3.island is set),
   - behind each terrace grows that department's district of houses, in its colour, as
     many as the person chose in the island builder (office.py `island.houses`) or one
     more than the department has people until they choose,
   - the Brain is a fountain on the plaza, your agent's office has the lighthouse,
   - a railway runs round the shore with a station at every district.

   What moves, and why only that (the Office's rule, kept):
   - **The train runs because work was handed over.** It sets off when the Office flies a
     paper from one room to another (a delegate, a mission's node_add: 24d decides those),
     and it stops at the station that work went to. With nothing handed over it waits at
     your agent's station. A railway that loops for the look would say work is moving when
     none is.
   - **Windows light because somebody in that district is working** (OFFICE.people[*].busy),
     and at night because it is night.
   - The sea and the sky are scenery, like the pet: the water ripples and the light follows
     the hour. The hour is the real one unless the person drags the time of day
     (localStorage `island.hour`, per browser, like the World's quality switch): time is an
     input here, nothing else reads it.

   Faces: the people are 24k's figures, cut from the server's body sheet (00e-avatars.js):
   there is no painter here, only houses, land and water.

   Cost: the island is one baked mesh of vertex colours (wlBake skips nothing here: the
   land, every house, the trees and the railway are one geometry, one material), windows are
   two instanced meshes, the water one plane with a small shader. Frames come from the
   Office's own loop (30 a second while something moves, 6 at rest, none asleep), so the sea
   moves slowly at rest and not at all while the scene is covered.

   Faces — GUI: the Office window (look island) and the desktop scene Island. SUI: the same
   page. TUI: `bento office island` prints the districts and edits them with the same closed
   set; a terminal shows the plan, not the picture.
   `var`, not `let`: the bundle is one script. */
var ISL={tex:null,water:null,train:null,cars:[],curve:null,len:0,stations:{},home:0,
  windows:null,panes:[],lamp:null,lights:null,hourAt:0,hourShown:-1,busySig:'',queue:[],field:null,height:null,top:.175,ctl:null};
var ISL_ROOF=['#e46a4a','#d8644c','#4f8fd0','#5aa878','#efb24a','#d35f5a','#7a8fc9'];
var ISL_TREES={few:18,some:40,lots:80};
/* The hour the island is lit for: the real one, or the one the person dragged it to. */
function islHourSet(){try{const h=localStorage.getItem('island.hour');return h!==null&&h!==''&&isFinite(+h)}catch(e){return false}}
function islHour(){
  try{const h=localStorage.getItem('island.hour');if(h!==null&&h!==''&&isFinite(+h))return ((+h%24)+24)%24}catch(e){}
  const d=new Date();return d.getHours()+d.getMinutes()/60;
}
function islSetHour(h){
  try{if(h===null||h==='')localStorage.removeItem('island.hour');else localStorage.setItem('island.hour',String(+h))}catch(e){}
  ISL.hourShown=-1;islLight();islControlsPaint();OF3.dirty=true;
  if(typeof officeKick==='function')officeKick();
}
/* ---------------- the land: a shape round the rooms, read as one distance ---------------- */
function islSeg(px,pz,ax,az,bx,bz){
  const vx=bx-ax,vz=bz-az,wx=px-ax,wz=pz-az,t=Math.max(0,Math.min(1,(wx*vx+wz*vz)/Math.max(1e-9,vx*vx+vz*vz)));
  return Math.hypot(px-(ax+vx*t),pz-(az+vz*t));
}
function islHash(x,y){const s=Math.sin(x*127.1+y*311.7)*43758.5453;return s-Math.floor(s)}
function islNoise(x,y){
  const ix=Math.floor(x),iy=Math.floor(y),fx=x-ix,fy=y-iy,u=fx*fx*(3-2*fx),v=fy*fy*(3-2*fy);
  const a=islHash(ix,iy),b=islHash(ix+1,iy),c=islHash(ix,iy+1),d=islHash(ix+1,iy+1);
  return a+(b-a)*u+(c-a)*v+(a-b-c+d)*u*v;
}
function islSmooth(a,b,x){const t=Math.max(0,Math.min(1,(x-a)/(b-a)));return t*t*(3-2*t)}
/* Every room's terrace, its district behind it and the plaza, as one signed distance
   (negative on land). Rooms come from the Office's own ring (O.L), in world units. */
function islShapes(L){
  const U=OF3_U,rooms=L.rooms.map(r=>{
    const cx=r.cx/U,cz=r.cy/U,l=Math.hypot(cx,cz)||1,ox=cx/l,oz=cz/l,diag=Math.hypot(r.w,r.h)/U/2;
    return {r,cx,cz,hx:r.w/U/2,hz:r.h/U/2,ox,oz,dx:cx+ox*(diag+.95),dz:cz+oz*(diag+.95),dr:1.95}});
  const lead=rooms.find(q=>q.r.kind==='lead')||rooms[0];
  const lh=lead?{x:lead.cx+lead.ox*(Math.hypot(lead.hx,lead.hz)+2.6)+lead.oz*1.1,z:lead.cz+lead.oz*(Math.hypot(lead.hx,lead.hz)+2.6)-lead.ox*1.1}:{x:6,z:0};
  // the plaza's cobbles, and the land inside the ring of rooms (one town, no lagoons)
  return {rooms,lh,lead,plaza:(OF3_RING+70)/U,hub:Math.max(OF3_RING+70,L.R+40)/U};
}
/* Where the railway runs: round the shore, just inside it, smoothed, and pushed out past any
   terrace it would otherwise cross (a train through somebody's desk is not a railway). */
function islRailLine(sh){
  const M=72,pts=[],base={...sh,rail:null};
  for(let i=0;i<M;i++){const a=i/M*Math.PI*2;let r=sh.hub*.6;
    while(r<40&&islDist(base,Math.cos(a)*(r+.1),Math.sin(a)*(r+.1))<-.6)r+=.08;
    pts.push(r)}
  let rs=pts.map((r,i)=>{let s=0;for(let k=-3;k<=3;k++)s+=pts[(i+k+M)%M];return s/7});
  const clear=(x,z)=>!sh.rooms.some(q=>Math.abs(x-q.cx)<q.hx+.45&&Math.abs(z-q.cz)<q.hz+.45)&&Math.hypot(x-sh.lh.x,z-sh.lh.z)>.8;
  for(let pass=0;pass<3;pass++){
    rs=rs.map((r,i)=>{const a=i/M*Math.PI*2;let rr=r;while(rr<40&&!clear(Math.cos(a)*rr,Math.sin(a)*rr))rr+=.06;return rr});
    rs=rs.map((r,i)=>Math.max(r,(rs[(i+M-1)%M]+r*2+rs[(i+1)%M])/4));      // smooth without pulling back in
  }
  return rs.map((r,i)=>{const a=i/M*Math.PI*2;return [Math.cos(a)*r,Math.sin(a)*r]});
}
function islDist(sh,x,z){
  let d=Math.hypot(x,z)-sh.hub;
  for(const q of sh.rooms){
    const ax=Math.abs(x-q.cx)-(q.hx+.35),az=Math.abs(z-q.cz)-(q.hz+.35);
    d=Math.min(d,Math.hypot(Math.max(ax,0),Math.max(az,0))+Math.min(Math.max(ax,az),0)-.25);
    d=Math.min(d,Math.hypot(x-q.dx,z-q.dz)-q.dr);
    d=Math.min(d,islSeg(x,z,0,0,q.cx,q.cz)-.75);
  }
  for(let i=0;i<sh.rooms.length;i++){const a=sh.rooms[i],b=sh.rooms[(i+1)%sh.rooms.length];
    if(a!==b)d=Math.min(d,islSeg(x,z,a.cx,a.cz,b.cx,b.cz)-.95)}
  d=Math.min(d,Math.hypot(x-sh.lh.x,z-sh.lh.z)-.95);
  // the land under the railway: where the line had to swing out round a terrace, a causeway
  if(sh.rail)for(let i=0;i<sh.rail.length;i++){const a=sh.rail[i],b=sh.rail[(i+1)%sh.rail.length];d=Math.min(d,islSeg(x,z,a[0],a[1],b[0],b[1])-.5)}
  if(sh.lead)d=Math.min(d,islSeg(x,z,sh.lh.x,sh.lh.z,sh.lead.cx,sh.lead.cz)-.55);
  return d+(islNoise(x*.45,z*.45)-.5)*.5+(islNoise(x*1.4,z*1.4)-.5)*.12;
}
/* ---------------- a bag of geometry, one vertex colour each, baked to one mesh ---------------- */
function islBag(){return {pos:[],nrm:[],col:[]}}
function islAdd(bag,g,m,hex,ao){
  const T=OF3.T,c=new T.Color(hex);let geo=g.index?g.toNonIndexed():g;
  let y0=0,y1=1;if(ao){geo.computeBoundingBox();y0=geo.boundingBox.min.y;y1=geo.boundingBox.max.y}
  const ly=ao?geo.attributes.position.array.slice():null;
  if(m)geo.applyMatrix4(m);
  if(!geo.attributes.normal)geo.computeVertexNormals();
  const p=geo.attributes.position.array,n=geo.attributes.normal.array,cc=new Float32Array(p.length);
  for(let i=0;i<cc.length;i+=3){
    // ao: a wall is darker at its foot, full colour from a third of the way up
    const k=ao?.72+.28*Math.min(1,Math.max(0,(ly[i+1]-y0)/((y1-y0)*.35))):1;
    cc[i]=c.r*k;cc[i+1]=c.g*k;cc[i+2]=c.b*k;
  }
  bag.pos.push(p);bag.nrm.push(n);bag.col.push(cc);
  if(geo!==g)g.dispose();
}
function islMesh(bag,mat){
  const T=OF3.T,cat=a=>{let n=0;a.forEach(x=>n+=x.length);const o=new Float32Array(n);let k=0;a.forEach(x=>{o.set(x,k);k+=x.length});return o};
  const g=new T.BufferGeometry();
  g.setAttribute('position',new T.BufferAttribute(cat(bag.pos),3));
  g.setAttribute('normal',new T.BufferAttribute(cat(bag.nrm),3));
  g.setAttribute('color',new T.BufferAttribute(cat(bag.col),3));
  return new T.Mesh(g,mat);
}
/* A box with rounded edges: an extruded rounded rectangle, which is what makes a house
   read as soft rather than as a crate. */
function islRound(w,h,d,r){
  const T=OF3.T,s=new T.Shape(),x=-w/2+r,y=-d/2+r,ww=w-2*r,dd=d-2*r;
  s.moveTo(x,y-r);s.lineTo(x+ww,y-r);s.quadraticCurveTo(x+ww+r,y-r,x+ww+r,y);
  s.lineTo(x+ww+r,y+dd);s.quadraticCurveTo(x+ww+r,y+dd+r,x+ww,y+dd+r);
  s.lineTo(x,y+dd+r);s.quadraticCurveTo(x-r,y+dd+r,x-r,y+dd);s.lineTo(x-r,y);s.quadraticCurveTo(x-r,y-r,x,y-r);
  const g=new T.ExtrudeGeometry(s,{depth:Math.max(.001,h-2*r),bevelEnabled:true,bevelSize:r*.9,bevelThickness:r,bevelSegments:2,curveSegments:3});
  g.rotateX(-Math.PI/2);g.translate(0,-h/2+r,0);return g;
}
function islGable(w,d,rise){
  const T=OF3.T,s=new T.Shape();s.moveTo(-d/2,0);s.lineTo(d/2,0);s.lineTo(0,rise);s.lineTo(-d/2,0);
  const g=new T.ExtrudeGeometry(s,{depth:w,bevelEnabled:true,bevelSize:.025,bevelThickness:.025,bevelSegments:1});
  g.translate(0,0,-w/2);g.rotateY(Math.PI/2);return g;
}
/* ---------------- building the island ---------------- */
function islWorld(S,still,L,v){
  const T=OF3.T,U=OF3_U,top=ISL.top,rnd=of3Rand(7+L.rooms.length*31),isl=(v.office&&v.office.island)||{};
  if(ISL.tex){ISL.tex.dispose();ISL.tex=null}
  Object.assign(ISL,{train:null,cars:[],curve:null,stations:{},queue:[],windows:null,panes:[],hourShown:-1,busySig:''});
  (OFFICE.papers||[]).forEach(pp=>{if(pp)pp._isl=1});   // what was in the air before the island was drawn
  const sh=islShapes(L);ISL.sh=sh;
  if(isl.train!==false)sh.rail=islRailLine(sh);
  const dist=(x,z)=>islDist(sh,x,z);
  const height=(x,z)=>{const d=dist(x,z),k=islSmooth(-.05,.55,d);return top-(top+1.5)*Math.pow(k,.8)};
  ISL.height=height;
  const bag=islBag(),C=h=>h;
  // extent: everything plus a margin of sea
  let x0=-4,x1=4,z0=-4,z1=4;
  sh.rooms.forEach(q=>{x0=Math.min(x0,q.dx-3,q.cx-4);x1=Math.max(x1,q.dx+3,q.cx+4);z0=Math.min(z0,q.dz-3,q.cz-4);z1=Math.max(z1,q.dz+3,q.cz+4)});
  x0=Math.min(x0,sh.lh.x-3);x1=Math.max(x1,sh.lh.x+3);z0=Math.min(z0,sh.lh.z-3);z1=Math.max(z1,sh.lh.z+3);
  ISL.ext={x0,x1,z0,z1};
  const onPath=(x,z)=>Math.hypot(x,z)<sh.plaza-.25||sh.rooms.some(q=>islSeg(x,z,0,0,q.cx,q.cz)<.42)
    ||Math.abs(Math.hypot(x,z)-OF3_RING/U)<.3||(!!sh.lead&&islSeg(x,z,sh.lh.x,sh.lh.z,sh.lead.cx,sh.lead.cz)<.32);
  // the ground: a grid draped over the shape, coloured by where it is
  {
    const N=OF3.hq?150:100,W=x1-x0,D=z1-z0,g=new T.PlaneGeometry(W,D,N,Math.round(N*D/W));
    g.rotateX(-Math.PI/2);g.translate((x0+x1)/2,0,(z0+z1)/2);
    const p=g.attributes.position,c=new Float32Array(p.count*3),tmp=new T.Color();
    const grass=new T.Color('#8fbf6a'),grass2=new T.Color('#a7cf7c'),stone=new T.Color('#d9cbb0'),stone2=new T.Color('#e8dcc4'),
      cliff=new T.Color('#c9a27a'),cliff2=new T.Color('#a8805c'),sand=new T.Color('#efdcae'),bed=new T.Color('#4d8f95');
    for(let i=0;i<p.count;i++){
      const x=p.getX(i),z=p.getZ(i),y=height(x,z);p.setY(i,y);
      const n=islNoise(x*.8,z*.8);
      if(y>top-.02)tmp.copy(onPath(x,z)?stone:grass).lerp(onPath(x,z)?stone2:grass2,n*.8);
      else if(y>-.05)tmp.copy(cliff2).lerp(cliff,(y+.05)/(top+.05)).lerp(new T.Color('#b88e66'),(islNoise(x*3,y*6)-.5)*.6+.2);
      else if(y>-.32)tmp.copy(sand);
      else tmp.copy(bed).lerp(sand,Math.max(0,(y+.8)/.5));
      c[i*3]=tmp.r;c[i*3+1]=tmp.g;c[i*3+2]=tmp.b;
    }
    g.setAttribute('color',new T.BufferAttribute(c,3));g.computeVertexNormals();
    const ng=g.toNonIndexed();g.dispose();
    bag.pos.push(ng.attributes.position.array);bag.nrm.push(ng.attributes.normal.array);bag.col.push(ng.attributes.color.array);
  }
  // the railway, first, so the houses keep off it
  const rail=[];
  if(sh.rail){
    const sm=sh.rail.map(p=>new T.Vector3(p[0],top+.03,p[1]));
    const curve=new T.CatmullRomCurve3(sm,true,'centripetal');ISL.curve=curve;ISL.len=curve.getLength();
    const n=Math.floor(ISL.len/.3),sleeper=new T.BoxGeometry(.44,.04,.11),up=new T.Vector3(0,1,0);
    for(let i=0;i<n;i++){const u=i/n,p=curve.getPointAt(u),tg=curve.getTangentAt(u);rail.push(p);
      const m=new T.Matrix4().lookAt(new T.Vector3(),tg,up).setPosition(p.x,top+.02,p.z);islAdd(bag,sleeper.clone(),m,'#8a6a4f')}
    sleeper.dispose();
    [-.14,.14].forEach(side=>{const ps=[];
      for(let i=0;i<=240;i++){const u=(i/240)%1,p=curve.getPointAt(u),tg=curve.getTangentAt(u),nx=-tg.z,nz=tg.x,l=Math.hypot(nx,nz)||1;
        ps.push(new T.Vector3(p.x+nx/l*side,top+.06,p.z+nz/l*side))}
      islAdd(bag,new T.TubeGeometry(new T.CatmullRomCurve3(ps,true),360,.022,6,true),null,'#9aa3ad')});
    // a station where the line passes each room
    sh.rooms.forEach(q=>{
      let best=0,bd=1e9;for(let i=0;i<240;i++){const p=curve.getPointAt(i/240),dd=Math.hypot(p.x-q.dx,p.z-q.dz);if(dd<bd){bd=dd;best=i/240}}
      ISL.stations[q.r.kind+':'+q.r.name]=best;
      if(q.r.kind==='lead')ISL.home=best;
      const p=curve.getPointAt(best),tg=curve.getTangentAt(best),nx=-tg.z,nz=tg.x,l=Math.hypot(nx,nz)||1;
      const side=(nx*(q.cx-p.x)+nz*(q.cz-p.z))>0?1:-1;
      const m=new T.Matrix4().lookAt(new T.Vector3(),tg,up).setPosition(p.x+nx/l*side*.5,top,p.z+nz/l*side*.5);
      const col=v.colors[q.r.color]||'#94a3b8';
      const pl=islRound(.42,.12,1.15,.03);pl.translate(0,.06,0);islAdd(bag,pl,m,'#e2d6c2');
      const rf=islRound(.54,.05,.95,.02);rf.translate(0,.6,0);islAdd(bag,rf,m,col);
      [-.38,.38].forEach(zz=>{const po=new T.CylinderGeometry(.025,.025,.48,8);po.translate(.13,.36,zz);islAdd(bag,po,m,'#5a5f68')});
    });
  }
  const offRail=(x,z,m)=>!rail.some(p=>Math.hypot(p.x-x,p.z-z)<m);
  // the houses: each department's district, behind its terrace as the camera sees it
  const b=of3Basis(),scr=(x,z)=>({sx:x*b.right.x+z*b.right.z,sy:x*b.up.x+z*b.up.z});
  const panes=[];
  const house=(x,z,rot,w,d,floors,wall,roof,room)=>{
    const y0=height(x,z)-.04,hgt=.46*floors+.08;
    const m=new T.Matrix4().compose(new T.Vector3(x,y0,z),new T.Quaternion().setFromAxisAngle(new T.Vector3(0,1,0),rot),new T.Vector3(1,1,1));
    const wg=islRound(w,hgt,d,.045);wg.translate(0,hgt/2,0);islAdd(bag,wg,m,wall,true);
    const pg=islRound(w+.05,.12,d+.05,.03);pg.translate(0,.06,0);islAdd(bag,pg,m,'#'+new T.Color(wall).multiplyScalar(.82).getHexString());
    const rg=islGable(w+.16,d+.18,Math.min(w,d)*.55+.1);rg.translate(0,hgt,0);islAdd(bag,rg,m,roof);
    if(rnd()<.6){const cg=islRound(.12,.32,.12,.02);cg.translate(w*.22,hgt+.27,d*(rnd()<.5?.16:-.16));islAdd(bag,cg,m,'#b9b2a8')}
    const nx=Math.max(1,Math.floor(w/.32));
    for(let f=0;f<floors;f++)for(let k=0;k<nx;k++)for(const side of [1,-1]){
      if(f===0&&side===1&&k===Math.floor(nx/2))continue;
      panes.push({m:m.clone().multiply(new T.Matrix4().makeTranslation(-w/2+(k+.5)*(w/nx),.29+f*.46,side*(d/2+.05))),room});
    }
    const door=islRound(.15,.27,.05,.015);door.translate(-w/2+(Math.floor(nx/2)+.5)*(w/nx),.15,d/2+.05);islAdd(bag,door,m,'#6b4a34');
  };
  const roomBox=q=>{const cs=[[q.cx-q.hx,q.cz-q.hz],[q.cx+q.hx,q.cz-q.hz],[q.cx-q.hx,q.cz+q.hz],[q.cx+q.hx,q.cz+q.hz]].map(c=>scr(c[0],c[1]));
    return {x0:Math.min(...cs.map(c=>c.sx)),x1:Math.max(...cs.map(c=>c.sx)),y0:Math.min(...cs.map(c=>c.sy)),y1:Math.max(...cs.map(c=>c.sy))}};
  const boxes=sh.rooms.map(roomBox);
  const spots=[];
  sh.rooms.forEach((q,qi)=>{
    const r=q.r,col=v.colors[r.color]||'#94a3b8';
    const want=r.kind==='dept'?officeHouses(isl,r):r.kind==='lead'?3:r.kind==='floor'?3:2;
    let made=0;
    for(let tries=0;tries<want*70&&made<want;tries++){
      const a=rnd()*Math.PI*2,rr=.2+rnd()*(q.dr+.6),x=q.dx+Math.cos(a)*rr,z=q.dz+Math.sin(a)*rr;
      if(height(x,z)<top-.01||dist(x,z)>-.45)continue;
      if(Math.abs(x-q.cx)<q.hx+.55&&Math.abs(z-q.cz)<q.hz+.55)continue;               // not on a terrace
      if(sh.rooms.some(o=>Math.abs(x-o.cx)<o.hx+.45&&Math.abs(z-o.cz)<o.hz+.45))continue;
      if(Math.hypot(x,z)<sh.hub+.3||sh.rooms.some(o=>islSeg(x,z,0,0,o.cx,o.cz)<.65))continue;   // the streets stay clear
      if(!offRail(x,z,.58)||spots.some(s=>Math.hypot(s.x-x,s.z-z)<.74))continue;
      // never in front of a terrace as the camera looks: its people would be behind a house
      const s=scr(x,z);let low=false;
      for(const bx of boxes){if(s.sx>bx.x0-.5&&s.sx<bx.x1+.5&&s.sy<bx.y1+.2){
        if(s.sy>bx.y0-1.1){low=null;break}low=true}}     // in front of a terrace: one storey, well clear of it
      if(low===null)continue;
      spots.push({x,z});made++;
      const base=new T.Color(col),wall=base.clone().offsetHSL((rnd()-.5)*.04,(rnd()-.5)*.1,(rnd()-.3)*.12+.1);
      const roof=ISL_ROOF[Math.floor(rnd()*ISL_ROOF.length)],rot=Math.atan2(q.cz-z,q.cx-x)+(rnd()-.5)*.4;
      house(x,z,rot,.62+rnd()*.32,.56+rnd()*.24,low?1:1+Math.floor(rnd()*(made===1?2:3)),'#'+wall.getHexString(),roof,r);
    }
  });
  // the lighthouse: your agent's
  {
    const lh=sh.lh,y0=height(lh.x,lh.z)-.04,hh=2.4,bands=5;
    for(let k=0;k<bands;k++){const r0=.46-k*.045,r1=.46-(k+1)*.045,g=new T.CylinderGeometry(r1,r0,hh/bands,28);
      g.translate(lh.x,y0+(k+.5)*hh/bands,lh.z);islAdd(bag,g,null,k%2?'#f4efe6':'#d9483b')}
    const gal=new T.CylinderGeometry(.38,.38,.06,28);gal.translate(lh.x,y0+hh+.03,lh.z);islAdd(bag,gal,null,'#3a3f4a');
    const cap=new T.ConeGeometry(.3,.36,28);cap.translate(lh.x,y0+hh+.56,lh.z);islAdd(bag,cap,null,'#d9483b');
    const lamp=new T.Mesh(new T.CylinderGeometry(.21,.21,.32,20),new T.MeshStandardMaterial({color:'#fff6d8',emissive:'#ffd36b',emissiveIntensity:.3,roughness:.1}));
    lamp.position.set(lh.x,y0+hh+.22,lh.z);lamp.userData.keep=1;S.add(lamp);ISL.lamp=lamp;
  }
  // the plaza round the Brain: a fountain; the Brain is the orb over it (24k pulses it)
  {
    const ring=new T.CylinderGeometry(.95,1.02,.2,40);ring.translate(0,top+.1,0);islAdd(bag,ring,null,'#e6dccb');
    const pool=new T.CylinderGeometry(.8,.8,.05,40);pool.translate(0,top+.19,0);islAdd(bag,pool,null,'#5fb6c4');
    const col=new T.CylinderGeometry(.11,.16,.55,16);col.translate(0,top+.45,0);islAdd(bag,col,null,'#efe6d6');
    const orb=new T.Mesh(new T.SphereGeometry(.3,32,20),new T.MeshStandardMaterial({color:'#e2d8ff',emissive:'#9b87ff',emissiveIntensity:2.2,roughness:.25}));
    orb.position.set(0,.98,0);orb.userData.keep=1;S.add(orb);
    const halo=new T.Sprite(new T.SpriteMaterial({map:of3Glow(),color:0xb6a6ff,transparent:true,blending:T.AdditiveBlending,depthWrite:false,opacity:.6}));
    halo.position.copy(orb.position);halo.scale.set(2.2,2.2,1);S.add(halo);
    const beam=new T.Mesh(new T.CylinderGeometry(.07,.16,2.6,24,1,true),new T.MeshBasicMaterial({map:of3Beam(),color:0xcfc3ff,transparent:true,
      blending:T.AdditiveBlending,depthWrite:false,side:T.DoubleSide,opacity:.4}));
    beam.position.set(0,2.2,0);S.add(beam);
    OF3.brain={orb,halo,beam};
  }
  // street lamps round the plaza and along each street; their halos come on at dusk (islLight)
  ISL.halos=[];
  {
    const at=[];for(let i=0;i<10;i++){const a=i/10*Math.PI*2+.31;at.push([Math.cos(a)*(sh.plaza-.1),Math.sin(a)*(sh.plaza-.1)])}
    sh.rooms.forEach(q=>{const l=Math.hypot(q.cx,q.cz)||1;[.55,.78].forEach(f=>at.push([q.cx*f+(-q.cz/l)*.5,q.cz*f+(q.cx/l)*.5]))});
    const head=new T.InstancedMesh(new T.SphereGeometry(.06,12,8),new T.MeshBasicMaterial({color:'#fff1c9',toneMapped:false}),at.length);
    at.forEach((p,i)=>{const pole=new T.CylinderGeometry(.018,.025,.62,8);pole.translate(p[0],top+.31,p[1]);islAdd(bag,pole,null,'#3a3f4a');
      head.setMatrixAt(i,new T.Matrix4().makeTranslation(p[0],top+.66,p[1]));
      const h=new T.Sprite(new T.SpriteMaterial({map:of3Glow(),color:0xffc777,transparent:true,blending:T.AdditiveBlending,depthWrite:false,opacity:0}));
      h.position.set(p[0],top+.66,p[1]);h.scale.set(.9,.9,1);S.add(h);ISL.halos.push(h)});
    head.userData.keep=1;S.add(head);ISL.heads=head;
  }
  // trees, where nothing else is
  for(let i=0,n=ISL_TREES[isl.trees]||ISL_TREES.some,k=0;i<n*14&&k<n;i++){
    const x=x0+rnd()*(x1-x0),z=z0+rnd()*(z1-z0);
    if(dist(x,z)>-.3||height(x,z)<top-.01||onPath(x,z)||Math.hypot(x,z)<sh.hub)continue;
    if(sh.rooms.some(o=>Math.abs(x-o.cx)<o.hx+.3&&Math.abs(z-o.cz)<o.hz+.3))continue;
    if(spots.some(s=>Math.hypot(s.x-x,s.z-z)<.55)||!offRail(x,z,.35)||Math.hypot(x-sh.lh.x,z-sh.lh.z)<.7)continue;
    const s=.45+rnd()*.4,t=new T.CylinderGeometry(.04*s,.07*s,.42*s,8);t.translate(x,top+.2*s,z);islAdd(bag,t,null,'#7a5a3e');
    const f=new T.IcosahedronGeometry(.36*s,2);f.scale(1,1.15,1);f.translate(x,top+.62*s,z);
    islAdd(bag,f,null,'#'+new T.Color(rnd()<.5?'#5f9e57':'#78b062').offsetHSL(0,0,(rnd()-.5)*.08).getHexString());k++;
  }
  // a couple of boats in the shallows (scenery, they rock with the water)
  ISL.boats=[];
  for(let i=0;i<3;i++){
    const a=rnd()*Math.PI*2;let r=sh.hub+2;while(r<60&&dist(Math.cos(a)*r,Math.sin(a)*r)<.9)r+=.2;
    const g=new T.Group(),hull=islRound(.62,.16,.26,.06),mast=new T.CylinderGeometry(.015,.015,.6,6),sail=new T.ConeGeometry(.18,.42,3);
    mast.translate(0,.36,0);sail.rotateZ(Math.PI/2*.0);sail.translate(.08,.4,0);
    const bb=islBag();islAdd(bb,hull,null,['#f4efe6','#d9483b','#4f8fd0'][i]);islAdd(bb,mast,null,'#6b4a34');islAdd(bb,sail,null,'#fffaf0');
    const mesh=islMesh(bb,of3Mat('isl-land',{vertexColors:true,roughness:.8}));g.add(mesh);
    g.position.set(Math.cos(a)*(r+.6),-.2,Math.sin(a)*(r+.6));g.rotation.y=-a;g.userData.keep=1;S.add(g);ISL.boats.push(g);
  }
  // one mesh for all of it
  const land=islMesh(bag,of3Mat('isl-land',{vertexColors:true,roughness:.82}));
  land.userData.keep=1;if(OF3.hq){land.castShadow=true;land.receiveShadow=true}
  S.add(land);
  // the windows: a white frame and a pane, two instanced meshes
  if(panes.length){
    const fg=islRound(.18,.24,.016,.008),pg=islRound(.12,.17,.03,.008);
    const frames=new T.InstancedMesh(fg,of3Mat('isl-frame',{color:'#f6f1e8',roughness:.6}),panes.length);
    const glass=new T.InstancedMesh(pg,new T.MeshBasicMaterial({color:'#ffffff',toneMapped:false}),panes.length);
    panes.forEach((p,i)=>{frames.setMatrixAt(i,p.m.clone().multiply(new T.Matrix4().makeTranslation(0,0,-.006)));glass.setMatrixAt(i,p.m);glass.setColorAt(i,new T.Color('#33435a'))});
    frames.userData.keep=1;glass.userData.keep=1;S.add(frames);S.add(glass);
    ISL.windows=glass;ISL.panes=panes;
  }
  // the train, waiting at your agent's station
  if(ISL.curve){
    const mat=of3Mat('isl-land',{vertexColors:true,roughness:.6}),mk=parts=>{const bb=islBag();parts.forEach(q=>islAdd(bb,q[0],null,q[1]));const m=islMesh(bb,mat);m.userData.keep=1;S.add(m);return m};
    const boiler=new T.CylinderGeometry(.13,.13,.42,18);boiler.rotateX(Math.PI/2);boiler.translate(0,.22,.06);
    const cab=islRound(.3,.26,.2,.025);cab.translate(0,.24,-.21);
    const chim=new T.CylinderGeometry(.04,.055,.16,10);chim.translate(0,.4,.19);
    const base=islRound(.31,.06,.66,.015);base.translate(0,.08,0);
    ISL.cars=[mk([[boiler,'#2f3d52'],[cab,'#d9483b'],[chim,'#222831'],[base,'#1f242c']])];
    ['#e7a83d','#4f8fd0'].forEach(c=>{const bd=islRound(.29,.23,.46,.03);bd.translate(0,.21,0);const b2=islRound(.31,.06,.5,.015);b2.translate(0,.08,0);
      ISL.cars.push(mk([[bd,c],[b2,'#1f242c']]))});
    ISL.train={u:ISL.home,speed:0};
    islCars();
  }
  // the sea: one plane that knows where the island is (its distance, as a small texture)
  {
    const N=128,W=x1-x0+8,D=z1-z0+8,cx=(x0+x1)/2,cz=(z0+z1)/2,data=new Uint8Array(N*N*4);
    for(let j=0;j<N;j++)for(let i=0;i<N;i++){const x=cx+(i/(N-1)-.5)*W,z=cz+(j/(N-1)-.5)*D;
      data[(j*N+i)*4]=Math.max(0,Math.min(255,Math.round(128-dist(x,z)*28)));data[(j*N+i)*4+3]=255}
    const tex=new T.DataTexture(data,N,N);tex.magFilter=tex.minFilter=T.LinearFilter;tex.needsUpdate=true;ISL.tex=tex;
    const u={uField:{value:tex},uBox:{value:new T.Vector4(cx,cz,W,D)},uTime:{value:0},uDeep:{value:new T.Color('#2f7f97')},
      uShallow:{value:new T.Color('#7fd6cf')},uSky:{value:new T.Color('#cfe6fb')},uSun:{value:new T.Vector3(.4,.8,.3)},uSunCol:{value:new T.Color('#fff2d6')},uNight:{value:0}};
    const mat=new T.ShaderMaterial({uniforms:u,
      vertexShader:'varying vec3 vW;void main(){vec4 w=modelMatrix*vec4(position,1.0);vW=w.xyz;gl_Position=projectionMatrix*viewMatrix*w;}',
      fragmentShader:`uniform sampler2D uField;uniform vec4 uBox;uniform float uTime,uNight;uniform vec3 uDeep,uShallow,uSky,uSun,uSunCol;varying vec3 vW;
        float h(vec2 p){return fract(sin(dot(p,vec2(12.9898,78.233)))*43758.5453);}
        float n(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.0-2.0*f);return mix(mix(h(i),h(i+vec2(1,0)),f.x),mix(h(i+vec2(0,1)),h(i+vec2(1,1)),f.x),f.y);}
        void main(){
          vec2 uv=(vW.xz-uBox.xy)/uBox.zw+0.5;
          float inside=step(0.0,uv.x)*step(uv.x,1.0)*step(0.0,uv.y)*step(uv.y,1.0);
          float d=mix(4.6,(128.0-texture2D(uField,uv).r*255.0)/28.0,inside);
          float shore=1.0-smoothstep(0.0,2.2,d);
          vec2 q=vW.xz*1.1;
          float w1=n(q+vec2(uTime*.25,uTime*.18)),w2=n(q*2.3-vec2(uTime*.3,-uTime*.2));
          vec3 nrm=normalize(vec3((w1-.5)*.35+(w2-.5)*.18,1.0,(w2-.5)*.35));
          vec3 V=normalize(cameraPosition-vW);
          float fres=pow(1.0-max(dot(V,nrm),0.0),3.0);
          vec3 c=mix(uDeep,uShallow,shore);
          c=mix(c,uSky,fres*.5);
          float glint=pow(max(dot(reflect(-normalize(uSun),nrm),V),0.0),110.0);
          c+=uSunCol*glint*(1.0-uNight)*1.3;
          float foam=smoothstep(.55,.2,d)*(1.0-smoothstep(.2,.05,d));
          foam*=.6+.4*sin(uTime*1.6+d*28.0);
          c=mix(c,vec3(1.0),foam*.7);
          gl_FragColor=vec4(c,1.0);
          #include <colorspace_fragment>
        }`});
    const sea=new T.Mesh(new T.PlaneGeometry(400,400),mat);sea.rotation.x=-Math.PI/2;sea.position.y=-.22;sea.userData.keep=1;S.add(sea);
    ISL.water=u;
  }
  // light: a sky, a sun and the bounce from the ground, all set by the hour (islLight)
  const hemi=new T.HemisphereLight(0xdff1ff,0x8a7a62,1.0),sun=new T.DirectionalLight(0xfff2d6,2.2);
  const span=(L.R+300)/U;
  if(OF3.hq){sun.castShadow=true;const c=sun.shadow.camera;c.left=c.bottom=-span*1.4;c.right=c.top=span*1.4;c.near=.5;c.far=span*5;
    sun.shadow.mapSize.set(2048,2048);sun.shadow.bias=-.0005;sun.shadow.normalBias=.02}
  S.add(hemi);S.add(sun);S.add(sun.target);
  ISL.lights={hemi,sun,span};
  islLight();
  islControls();
}
function officeHouses(isl,r){
  const got=(isl&&isl.houses)||{};
  for(const k in got)if(k.toLowerCase()===String(r.name).toLowerCase())return Math.max(0,Math.min(12,+got[k]||0));
  return Math.min(12,4+2*(r.members||[]).length);
}
/* ---------------- the hour ---------------- */
var ISL_KEYS=[   // hour, sky top, horizon, sun colour, sun strength, ground bounce, night 0..1
  [0,'#0e1a40','#24326a','#9fb4ff',.55,.62,1],[5,'#1b2450','#e48b6a','#ffb08a',.7,.55,.7],
  [7,'#78ade4','#ffd9b0','#ffe0b8',1.8,.95,.1],[12,'#5fa6ec','#cfe6fb','#fff6e4',2.6,1.15,0],
  [17,'#7aa9e0','#ffd7a8','#ffcf9a',2.0,.95,.05],[19,'#3b3f7a','#f08a5d','#ff9a6a',1.35,.88,.5],
  [21,'#152050','#2f3b70','#9fb4ff',.6,.65,.95],[24,'#0e1a40','#24326a','#9fb4ff',.55,.62,1]];
function islLight(){
  const T=OF3.T,Lg=ISL.lights;if(!T||!Lg||!OF3.scene)return;
  const h=islHour();
  let a=ISL_KEYS[0],b=ISL_KEYS[1];
  for(let i=0;i<ISL_KEYS.length-1;i++)if(h>=ISL_KEYS[i][0]&&h<=ISL_KEYS[i+1][0]){a=ISL_KEYS[i];b=ISL_KEYS[i+1];break}
  const k=(h-a[0])/Math.max(1e-6,b[0]-a[0]),mix=(x,y)=>new T.Color(x).lerp(new T.Color(y),k);
  const top=mix(a[1],b[1]),hor=mix(a[2],b[2]),sunC=mix(a[3],b[3]),night=a[6]+(b[6]-a[6])*k;
  ISL.night=night;
  const ang=(h-6)/12*Math.PI,el=Math.sin(ang),s=Lg.span;
  Lg.sun.position.set(Math.cos(ang)*s*(night>.5?-.5:1),Math.max(.55,night>.5?.8:el)*s*1.3,s*.5);
  Lg.sun.color.copy(sunC);Lg.sun.intensity=a[4]+(b[4]-a[4])*k;
  Lg.hemi.intensity=a[5]+(b[5]-a[5])*k;Lg.hemi.color.copy(top).lerp(new T.Color('#ffffff'),.5);
  OF3.scene.background=hor.clone();
  if(ISL.water){const u=ISL.water;u.uSky.value.copy(hor);u.uSunCol.value.copy(sunC);u.uNight.value=night;
    u.uSun.value.copy(Lg.sun.position).normalize();
    u.uDeep.value.set('#2f7f97').lerp(new T.Color('#173b5a'),night);u.uShallow.value.set('#7fd6cf').lerp(new T.Color('#2f6f86'),night)}
  if(ISL.lamp)ISL.lamp.material.emissiveIntensity=.3+night*3;
  (ISL.halos||[]).forEach(h=>h.material.opacity=Math.max(0,night-.25)*.9);
  if(ISL.heads)ISL.heads.material.color.set(night>.3?'#fff1c9':'#c9ccd4');
  ISL.hourShown=Math.floor(h*4);ISL.busySig='';
  islWindows();
}
/* Lit windows: warm at night, and by day the windows of a district somebody is working in. */
function islWindows(){
  const T=OF3.T,g=ISL.windows;if(!g)return;
  const busy={};Object.values(OFFICE.people||{}).forEach(p=>{if(p.busy&&p.room)busy[p.room.kind+':'+p.room.name]=1});
  const sig=Object.keys(busy).sort().join('|')+'@'+ISL.hourShown;if(sig===ISL.busySig)return;ISL.busySig=sig;
  const dark=new T.Color('#2d3b50'),warm=new T.Color('#ffb84d'),lit=new T.Color('#ffe9a8'),c=new T.Color();
  ISL.panes.forEach((p,i)=>{const on=busy[p.room.kind+':'+p.room.name];
    c.copy(on?lit:dark.clone().lerp(warm,(ISL.night||0)*(.5+.5*islHash(i,3))));g.setColorAt(i,c)});
  if(g.instanceColor)g.instanceColor.needsUpdate=true;OF3.dirty=true;
}
/* ---------------- every frame ---------------- */
function islTick(now){
  if(!OF3.island)return;
  const dt=Math.min(.25,(now-(ISL.last||now))/1000);ISL.last=now;
  if(ISL.water)ISL.water.uTime.value=now/1000;
  (ISL.boats||[]).forEach((b,i)=>{b.position.y=-.2+Math.sin(now/900+i*2)*.02;b.rotation.z=Math.sin(now/1100+i)*.04});
  // the hour: the real one moves on, a quarter of an hour at a time
  if(Math.floor(islHour()*4)!==ISL.hourShown)islLight();
  islWindows();
  islPapers();
  islTrain(dt);
}
/* A paper flying from one room to another is work handed over: the train takes it there. */
function islPapers(){
  (OFFICE.papers||[]).forEach(pp=>{
    if(!pp||pp._isl)return;pp._isl=1;          // each paper once; 24d drops it when it lands
    if(!pp.from||!pp.to||!ISL.curve)return;
    const a=islRoomAt(pp.from),b=islRoomAt(pp.to);
    if(!a||!b||a===b)return;
    const ua=ISL.stations[a.kind+':'+a.name],ub=ISL.stations[b.kind+':'+b.name];
    if(ua!==undefined&&ub!==undefined)ISL.queue.push(ua,ub);
  });
}
function islRoomAt(pt){return (OFFICE.L&&OFFICE.L.rooms||[]).find(r=>pt.x>=r.x-30&&pt.x<=r.x+r.w+30&&pt.y>=r.y-30&&pt.y<=r.y+r.h+30)}
function islTrain(dt){
  const tr=ISL.train;if(!tr||!ISL.curve)return;
  if(tr.to===undefined&&ISL.queue.length)tr.to=ISL.queue.shift();
  if(tr.to===undefined)return;
  const fwd=((tr.to-tr.u)%1+1)%1,dir=fwd<=.5?1:-1,left=dir>0?fwd:1-fwd;
  if(left<.002||OFFICE.static){tr.u=tr.to;tr.to=undefined;tr.speed=0;islCars();return}
  // no trip takes longer than the Office's longest walk: the train shows work moving now
  const want=Math.max(.05,left/(typeof OF_WALK_S!=='undefined'?OF_WALK_S:3.2)*1.3);
  if(tr.dir!==dir){tr.dir=dir;tr.speed=0}
  tr.speed=Math.min(want,tr.speed+dt*.6);
  tr.u=((tr.u+dir*Math.min(left,tr.speed*dt*(left<.03?Math.max(.3,left/.03):1)))%1+1)%1;
  islCars();
}
function islCars(){
  const tr=ISL.train;if(!tr)return;
  ISL.cars.forEach((car,i)=>{
    const u=((tr.u-(tr.dir||1)*i*.39/Math.max(1,ISL.len))%1+1)%1,p=ISL.curve.getPointAt(u),tg=ISL.curve.getTangentAt(u).multiplyScalar(tr.dir||1);
    car.position.set(p.x,ISL.top+.05,p.z);car.lookAt(p.x+tg.x,car.position.y,p.z+tg.z)});
  OF3.dirty=true;
}
function islMoving(){const tr=ISL.train;return !!(OF3.island&&tr&&(tr.to!==undefined||ISL.queue.length))}
/* ---------------- the time of day, as an input ---------------- */
function islControls(){
  if(!OF3.ui||OF3.ui.querySelector('.isl-time'))return islControlsPaint();
  const t=document.createElement('div');t.className='isl-time';t.setAttribute('role','group');t.setAttribute('aria-label','Time of day on the island');
  t.innerHTML='<button class="isl-tb" data-isl="open" title="Time of day" aria-label="Time of day"></button>'
    +'<div class="isl-tr" hidden><input type="range" min="0" max="24" step="0.25" aria-label="Hour of the day">'
    +'<button class="isl-tb isl-live" data-isl="live" title="Back to the real time">Now</button></div>';
  t.onclick=e=>{const b=e.target.closest('[data-isl]');if(!b)return;
    if(b.dataset.isl==='open'){const r=t.querySelector('.isl-tr');r.hidden=!r.hidden;return}
    if(b.dataset.isl==='live')islSetHour(null)};
  t.querySelector('input').oninput=e=>islSetHour(e.target.value);
  OF3.ui.appendChild(t);islControlsPaint();
}
function islControlsPaint(){
  const t=OF3.ui&&OF3.ui.querySelector('.isl-time');if(!t)return;
  const h=islHour(),hh=Math.floor(h),mm=Math.round((h-hh)*60)%60;
  t.querySelector('[data-isl="open"]').textContent=(h>=6.5&&h<19?'☀ ':'☾ ')+String(hh).padStart(2,'0')+':'+String(mm).padStart(2,'0')+(islHourSet()?'':' · now');
  const r=t.querySelector('input');if(r&&document.activeElement!==r)r.value=h;
  t.querySelector('.isl-live').hidden=!islHourSet();
}
function islControlsOff(){const t=OF3.ui&&OF3.ui.querySelector('.isl-time');if(t)t.remove()}
/* Is the 3D office drawn as an island? The Island scene always is; a window when its look is. */
function islWanted(){
  const v=OFFICE.view;if(!v||v.zero)return false;
  if(typeof of3HQ==='function'&&of3HQ())return !!(typeof OFFICE_SCENE!=='undefined'&&OFFICE_SCENE.island);
  if(OFFICE.w&&OFFICE.w.scene)return false;
  return ((v.office||{}).look||'3d')==='island';
}
/* ---------------- the island builder, in the Office's Design panel ----------------
   Houses per district, the railway, the trees: the same closed set as `bento office
   island` and the agent's set_office (office.py clean_island). Saved through officeSave
   like every other field of the plan, so it is the person's change and a ledger row. */
function islDesignHTML(v){
  const isl=(v.office&&v.office.island)||{},max=v.max_houses||12;
  const rows=v.rooms.filter(r=>r.kind==='dept').map(r=>{const n=officeHouses(isl,r);
    return `<div class="of-row isl-row"><span class="isl-dn">${esc(r.name)}</span>
      <button class="endbtn isl-hb" data-ih="${esc(r.name)}" data-d="-1" aria-label="One house fewer in ${esc(r.name)}"${n<=0?' disabled':''}>−</button>
      <b class="isl-n" aria-label="${n} houses">${n}</b>
      <button class="endbtn isl-hb" data-ih="${esc(r.name)}" data-d="1" aria-label="One more house in ${esc(r.name)}"${n>=max?' disabled':''}>+</button></div>`}).join('');
  const train=isl.train!==false,trees=isl.trees||'some';
  return `<div class="of-sec">Island</div>
    ${rows||'<div class="mut of-row">No departments yet. Each one you add grows a district here.</div>'}
    <div class="of-chips"><button class="of-chip${train?' on':''}" data-itrain="1" aria-pressed="${train}">Railway ${train?'on':'off'}</button>
      ${(v.trees||['few','some','lots']).map(t=>`<button class="of-chip${trees===t?' on':''}" data-itrees="${t}" aria-pressed="${trees===t}">${t} trees</button>`).join('')}</div>
    <div class="mut of-row">Houses are scenery. Who works where is still the departments' people.</div>`;
}
function islDesignWire(el,v){
  const isl=JSON.parse(JSON.stringify((v.office&&v.office.island)||{houses:{},train:true,trees:'some'}));
  isl.houses=isl.houses||{};
  const save=()=>officeSave({island:isl});
  el.querySelectorAll('[data-ih]').forEach(b=>b.onclick=()=>{const name=b.dataset.ih,r=v.rooms.find(x=>x.kind==='dept'&&x.name===name);if(!r)return;
    isl.houses[name]=Math.max(0,Math.min(v.max_houses||12,officeHouses(isl,r)+(+b.dataset.d)));save()});
  const tr=el.querySelector('[data-itrain]');if(tr)tr.onclick=()=>{isl.train=isl.train===false;save()};
  el.querySelectorAll('[data-itrees]').forEach(b=>b.onclick=()=>{isl.trees=b.dataset.itrees;save()});
}
