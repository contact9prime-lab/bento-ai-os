/* ================= The town: the Office drawn as a place of the person's choosing =================
   Settings → Appearance → Scene → Town, and the Office's own look "island" (office.py LOOKS).
   The same office as the 3D look (24k-office3d.js) and the same state (OFFICE): the rooms
   are still on their ring round the Brain, the desks are still where they were, and every
   walk, paper, balloon and meeting is decided by 24d-office.js exactly as before. What this
   file changes is only the place they stand in.

   The place is a SETTING from a closed set (office.py SETTINGS, ISL_SETS here): an island
   in the sea, a cluster of islands, a city on canals, a castle with walls and a moat, a
   town in a forest. Each setting has its own ground, water, houses, landmark for your
   agent and carrier for work, and nothing else: the person (or the agent, or the Office's
   "Describe it") picks one, and the page draws what it knows how to draw.

   - Every room is a BUILDING in the setting's style, closed while nothing happens in it.
     When somebody in it works, walks or speaks, or someone visits, or the person looks into
     it, the roof lifts and the walls drop so the office inside shows; a few seconds after it
     goes quiet it closes again (islShellWant). The building is a drawing of the room's
     state, decided from OFFICE.people, never a timer.
   - Behind each room grows that department's district of houses, in its colour, as many as
     the person chose (office.py `island.houses`), or four and two a person until they do.
   - The Brain is a fountain on the plaza. Your agent's place is the setting's landmark: a
     lighthouse, a windmill, a bell tower, a castle keep, a watchtower.

   What moves, and why only that (the Office's rule, kept):
   - **The carrier runs because work was handed over.** A train on land, a ferry between
     islands, a gondola on the canal. It sets off when the Office flies a paper from one room
     to another (a delegate, a mission's node_add: 24d decides those) and stops where that
     work went. With nothing handed over it waits at your agent's stop.
   - **A building opens because somebody in it is at work**, and windows light at night.
   - The sea, the sails of a windmill and the sky are scenery, like the pet. The hour is the
     real one unless the person drags the time of day (localStorage `island.hour`, per
     browser): time is an input here, nothing else reads it.

   Faces: the people are 24k's figures, cut from the server's body sheet (00e-avatars.js):
   there is no painter here, only buildings, land and water.

   Cost: the town is one baked mesh of vertex colours (land, houses, trees, track and the
   setting's walls and bridges), windows two instanced meshes, the water one plane with a
   small shader, and each room's building three meshes (walls, their windows, the roof) so it
   can open. Frames come from the Office's own loop (30 a second while something moves, 12 or
   6 at rest, none asleep).

   Faces — GUI: the Office window (look island) and the desktop scene Town. SUI: the same
   page. TUI: `bento office setting` and `bento office island` print and edit the same closed
   set; a terminal shows the plan, not the picture.
   `var`, not `let`: the bundle is one script. */
var ISL={tex:null,water:null,train:null,cars:[],curve:null,len:0,stations:{},home:0,carrier:'train',
  windows:null,panes:[],lamp:null,lights:null,hourAt:0,hourShown:-1,busySig:'',queue:[],field:null,height:null,top:.175,ctl:null,
  shells:[],shellPane:null,spin:null,fitPts:[],set:'island'};
var ISL_ROOF=['#e46a4a','#d8644c','#4f8fd0','#5aa878','#efb24a','#d35f5a','#7a8fc9'];
var ISL_TREES={few:18,some:40,lots:80};
/* The settings the page can draw (office.py SETTINGS). Each is a palette and a set of
   parts; a new one is a row here, its shape in islDist, and its word in office.py. */
var ISL_SETS={
  island:{label:'Island',grass:['#8fbf6a','#a7cf7c'],path:['#d9cbb0','#e8dcc4'],cliff:['#c9a27a','#a8805c'],sand:'#efdcae',bed:'#4d8f95',
    deep:'#2f7f97',shallow:'#7fd6cf',nDeep:'#173b5a',nShallow:'#2f6f86',foam:.7,house:'cottage',shell:'cottage',mark:'lighthouse',carrier:'train',tree:'round',stone:'#e6dccb'},
  islands:{label:'Islands',grass:['#c3c07a','#d4d095'],path:['#f2eee5','#fbf8f2'],cliff:['#d8b98e','#b89169'],sand:'#f3e6c4',bed:'#2f7fae',
    deep:'#1d5fa0',shallow:'#4ec6d8',nDeep:'#102c55',nShallow:'#1f5b80',foam:.75,house:'cube',shell:'cube',mark:'windmill',carrier:'boat',tree:'olive',stone:'#f4f1ea'},
  canals:{label:'Canal city',grass:['#cfc2a8','#dbcfb6'],path:['#ece4d4','#f5efe3'],cliff:['#a95f45','#8d4a35'],sand:'#7d6a55',bed:'#2c5a5a',
    deep:'#2e6b6c',shallow:'#4f998f',nDeep:'#14303a',nShallow:'#22505a',foam:.18,house:'venetian',shell:'venetian',mark:'campanile',carrier:'gondola',tree:'cypress',stone:'#efe9dd'},
  castle:{label:'Castle',grass:['#7fb35e','#93c46c'],path:['#bdb6aa','#cfc8bc'],cliff:['#9d958a','#7f786f'],sand:'#c9b48a',bed:'#3f6b5a',
    deep:'#2f5f58',shallow:'#5d9488',nDeep:'#14302e',nShallow:'#264c48',foam:.3,house:'timber',shell:'stone',mark:'keep',carrier:'train',tree:'round',stone:'#a8a196'},
  forest:{label:'Forest',grass:['#5d8f45','#6fa152'],path:['#a8865c','#b8966a'],cliff:['#7a6248','#5e4a36'],sand:'#9c8a64',bed:'#2c4f48',
    deep:'#2a5a55',shallow:'#4f8a7a',nDeep:'#122826',nShallow:'#1f403c',foam:.35,house:'cabin',shell:'cabin',mark:'watchtower',carrier:'train',tree:'pine',stone:'#8f8a7c'},
};
function islSetName(isl){const s=isl&&isl.setting;return ISL_SETS[s]?s:'island'}
/* The hour the town is lit for: the real one, or the one the person dragged it to. */
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
function islLine(pts,x,z,closed){let d=1e9;const n=pts.length;
  for(let i=0;i<(closed?n:n-1);i++){const a=pts[i],b=pts[(i+1)%n];d=Math.min(d,islSeg(x,z,a[0],a[1],b[0],b[1]))}return d}
function islHash(x,y){const s=Math.sin(x*127.1+y*311.7)*43758.5453;return s-Math.floor(s)}
function islNoise(x,y){
  const ix=Math.floor(x),iy=Math.floor(y),fx=x-ix,fy=y-iy,u=fx*fx*(3-2*fx),v=fy*fy*(3-2*fy);
  const a=islHash(ix,iy),b=islHash(ix+1,iy),c=islHash(ix,iy+1),d=islHash(ix+1,iy+1);
  return a+(b-a)*u+(c-a)*v+(a-b-c+d)*u*v;
}
function islSmooth(a,b,x){const t=Math.max(0,Math.min(1,(x-a)/(b-a)));return t*t*(3-2*t)}
/* Every room, its district behind it and the plaza, in world units, from the Office's own
   ring (O.L). `set` is the setting the land below takes its shape from. */
function islShapes(L,set){
  const U=OF3_U,rooms=L.rooms.map(r=>{
    const cx=r.cx/U,cz=r.cy/U,l=Math.hypot(cx,cz)||1,ox=cx/l,oz=cz/l,diag=Math.hypot(r.w,r.h)/U/2;
    return {r,cx,cz,hx:r.w/U/2,hz:r.h/U/2,ox,oz,dx:cx+ox*(diag+.95),dz:cz+oz*(diag+.95),dr:1.95}});
  const lead=rooms.find(q=>q.r.kind==='lead')||rooms[0];
  const lh=lead?{x:lead.cx+lead.ox*(Math.hypot(lead.hx,lead.hz)+2.6)+lead.oz*1.1,z:lead.cz+lead.oz*(Math.hypot(lead.hx,lead.hz)+2.6)-lead.ox*1.1}:{x:6,z:0};
  let rmax=Math.hypot(lh.x,lh.z)+1;rooms.forEach(q=>rmax=Math.max(rmax,Math.hypot(q.dx,q.dz)+q.dr,Math.hypot(q.cx,q.cz)+Math.hypot(q.hx,q.hz)));
  return {rooms,lh,lead,rmax,set:ISL_SETS[set]?set:'island',plaza:(OF3_RING+70)/U,hub:Math.max(OF3_RING+70,L.R+40)/U};
}
/* The town as it would stand on one island: rooms, districts, plaza, the streets between
   them and the landmark. Every setting starts from this (no noise: a shape, not a coast). */
function islCore(sh,x,z){
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
  if(sh.lead)d=Math.min(d,islSeg(x,z,sh.lh.x,sh.lh.z,sh.lead.cx,sh.lead.cz)-.55);
  return d;
}
/* Where the railway runs: round the coast of the whole town, beyond the districts, so the
   rooms stand in the town and never on the line (an office wrapped in track was the first
   thing the owner asked about); a causeway carries it across a bay. The canal city's canal
   (`inner`) runs closer, just behind the rooms, between them and their districts. Either is
   smoothed and pushed out past any room it would otherwise cross (a train through somebody's
   desk is not a railway, and a canal through it is a flood). */
function islRailLine(sh,gap,inner){
  const M=72,pts=[],g=gap||.62;
  for(let i=0;i<M;i++){const a=i/M*Math.PI*2,ca=Math.cos(a),sa=Math.sin(a);let r;
    if(inner){r=sh.hub*.6;while(r<40&&islCore(sh,ca*(r+.1),sa*(r+.1))<-.6)r+=.08}
    else{r=sh.rmax+2;while(r>sh.hub&&islCore(sh,ca*r,sa*r)>-.35)r-=.08}
    pts.push(r)}
  // the coast between two districts dips in to the plaza: a railway takes the bay on a causeway
  const lift=inner?pts:pts.map((r,i)=>{let m=0;for(let k=-4;k<=4;k++)m=Math.max(m,pts[(i+k+M)%M]*(1-Math.abs(k)*.035));return Math.max(r,m)});
  let rs=lift.map((r,i)=>{let s=0;for(let k=-3;k<=3;k++)s+=lift[(i+k+M)%M];return s/7});
  const clear=(x,z)=>!sh.rooms.some(q=>Math.abs(x-q.cx)<q.hx+g&&Math.abs(z-q.cz)<q.hz+g)&&Math.hypot(x-sh.lh.x,z-sh.lh.z)>.95;
  const at=(i,r)=>{const a=i/M*Math.PI*2;return [Math.cos(a)*r,Math.sin(a)*r]};
  for(let pass=0;pass<4;pass++){
    rs=rs.map((r,i)=>{const a=i/M*Math.PI*2;let rr=r;while(rr<40&&!clear(Math.cos(a)*rr,Math.sin(a)*rr))rr+=.06;return rr});
    // and between the points: a straight stretch can still clip a room's corner
    rs=rs.map((r,i)=>{let rr=r;for(let k=0;k<30;k++){const a=at(i,rr),b=at(i+1,rs[(i+1)%M]);
      if([.25,.5,.75].every(f=>clear(a[0]+(b[0]-a[0])*f,a[1]+(b[1]-a[1])*f)))break;rr+=.06}return rr});
    rs=rs.map((r,i)=>Math.max(r,(rs[(i+M-1)%M]+r*2+rs[(i+1)%M])/4));      // smooth without pulling back in
  }
  // the last word is the rooms': no point of the line is left inside one
  rs=rs.map((r,i)=>{const a=i/M*Math.PI*2;let rr=r;while(rr<40&&!clear(Math.cos(a)*rr,Math.sin(a)*rr))rr+=.06;return rr});
  return rs.map((r,i)=>{const a=i/M*Math.PI*2;return [Math.cos(a)*r,Math.sin(a)*r]});
}
/* The ferry's route round a cluster of islands: just outside every islet, in open water. */
function islWaterRing(sh){
  const M=72,rs=[];
  for(let i=0;i<M;i++){const a=i/M*Math.PI*2;let r=sh.rmax+3;
    while(r>sh.hub&&islDist(sh,Math.cos(a)*r,Math.sin(a)*r)>.55)r-=.08;
    rs.push(r+.62)}
  let sm=rs;for(let pass=0;pass<3;pass++)sm=sm.map((r,i)=>Math.max(rs[i],(sm[(i+M-1)%M]+r*2+sm[(i+1)%M])/4));
  return sm.map((r,i)=>{const a=i/M*Math.PI*2;return [Math.cos(a)*r,Math.sin(a)*r]});
}
function islWallAt(sh,a){const M=sh.wallR.length,f=((a/(Math.PI*2))*M%M+M)%M,i=Math.floor(f),k=f-i;return sh.wallR[i]*(1-k)+sh.wallR[(i+1)%M]*k}
/* The land of each setting as one signed distance (negative on land). */
function islDist(sh,x,z){
  const s=sh.set||'island',n=(islNoise(x*.45,z*.45)-.5)*.5+(islNoise(x*1.4,z*1.4)-.5)*.12;
  if(s==='islands'){
    let d=Math.hypot(x,z)-(sh.plaza+.55);
    for(const q of sh.rooms){
      const ax=Math.abs(x-q.cx)-(q.hx+.4),az=Math.abs(z-q.cz)-(q.hz+.4);
      d=Math.min(d,Math.hypot(Math.max(ax,0),Math.max(az,0))+Math.min(Math.max(ax,az),0)-.25);
      d=Math.min(d,Math.hypot(x-q.dx,z-q.dz)-q.dr*.92);
    }
    d=Math.min(d,Math.hypot(x-sh.lh.x,z-sh.lh.z)-.95);
    return d+n*.8;
  }
  if(s==='canals'){
    const a=Math.atan2(z,x),city=Math.hypot(x,z)-(sh.rmax+1.4+Math.sin(a*5)*.35+Math.sin(a*3+1)*.3);
    let d=city+n*.6;
    if(sh.canal)d=Math.max(d,.34-islLine(sh.canal,x,z,true));
    if(sh.side)sh.side.forEach(c=>{d=Math.max(d,.22-islLine(c,x,z,false))});
    return d;
  }
  if(s==='castle'&&sh.wallR){
    const a=Math.atan2(z,x),w=islWallAt(sh,a),r=Math.hypot(x,z);
    return Math.min(r-(w+.42),Math.max(w+1.28-r,r-(w+6.5)+n*2));
  }
  if(s==='forest'){
    let d=Math.hypot(x,z)-(sh.rmax+60);
    if(sh.river)d=Math.max(d,.5-islLine(sh.river,x,z,false)+n*.25);
    return d;
  }
  let d=islCore(sh,x,z);
  // the land under the railway: where the line had to swing out round a room, a causeway
  if(sh.rail)d=Math.min(d,islLine(sh.rail,x,z,true)-.5);
  return d+n;
}
/* ---------------- a bag of geometry, one vertex colour each, baked to one mesh ---------------- */
function islBag(){return {pos:[],nrm:[],col:[]}}
/* `ao` 'wall' (or true): darker at the foot of a wall; 'leaf': a crown darker underneath. */
function islAdd(bag,g,m,hex,ao){
  const T=OF3.T,c=new T.Color(hex);let geo=g.index?g.toNonIndexed():g;
  let y0=0,y1=1;if(ao){geo.computeBoundingBox();y0=geo.boundingBox.min.y;y1=geo.boundingBox.max.y}
  const ly=ao?geo.attributes.position.array.slice():null;
  if(m)geo.applyMatrix4(m);
  if(!geo.attributes.normal)geo.computeVertexNormals();
  const p=geo.attributes.position.array,n=geo.attributes.normal.array,cc=new Float32Array(p.length);
  for(let i=0;i<cc.length;i+=3){
    const f=ao?Math.min(1,Math.max(0,(ly[i+1]-y0)/Math.max(1e-6,y1-y0))):1;
    const k=ao==='leaf'?.68+.42*f:ao?.72+.28*Math.min(1,f/.35):1;
    cc[i]=Math.min(1,c.r*k);cc[i+1]=Math.min(1,c.g*k);cc[i+2]=Math.min(1,c.b*k);
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
function islM(x,y,z,rot){const T=OF3.T;return new T.Matrix4().compose(new T.Vector3(x,y,z),new T.Quaternion().setFromAxisAngle(new T.Vector3(0,1,0),rot||0),new T.Vector3(1,1,1))}
function islBox(bag,w,h,d,x,y,z,hex,m,ao){const g=new OF3.T.BoxGeometry(w,h,d);g.translate(x,y,z);islAdd(bag,g,m,hex,ao)}
/* A box standing at (x,y,z), turned `rot` about its own middle (a merlon round a tower). */
function islBoxAt(bag,w,h,d,x,y,z,rot,hex){islAdd(bag,new OF3.T.BoxGeometry(w,h,d),islM(x,y,z,rot),hex)}
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
/* A gable roof, its ridge along x: w long, d across, `rise` high. */
function islGable(w,d,rise){
  const T=OF3.T,s=new T.Shape();s.moveTo(-d/2,0);s.lineTo(d/2,0);s.lineTo(0,rise);s.lineTo(-d/2,0);
  const g=new T.ExtrudeGeometry(s,{depth:w,bevelEnabled:true,bevelSize:.025,bevelThickness:.025,bevelSegments:1});
  g.translate(0,0,-w/2);g.rotateY(Math.PI/2);return g;
}
/* A hipped roof over w by d: a four-sided cone turned square and stretched. */
function islHip(w,d,rise){const g=new OF3.T.ConeGeometry(1,rise,4,1);g.rotateY(Math.PI/4);g.scale(w/1.4142,1,d/1.4142);g.translate(0,rise/2,0);return g}
function islShade(hex,k){const c=new OF3.T.Color(hex);c.multiplyScalar(k);return '#'+c.getHexString()}
function islMix(a,b,k){return '#'+new OF3.T.Color(a).lerp(new OF3.T.Color(b),k).getHexString()}
/* ---------------- a house, in the setting's style ----------------
   (x,z) on the ground, turned `rot`, w by d, `floors` high. Every style writes into the
   one bag and adds its windows to `panes` (lit by work and by night, islWindows). */
var ISL_PLASTER=['#e9b98f','#d98f6b','#f0d6a8','#c9765a','#e8c3a0','#d7a57a','#efcf9a'];
function islHouse(st,bag,panes,rnd,x,y0,z,rot,w,d,floors,wall,roof,room){
  const T=OF3.T,m=islM(x,y0,z,rot);
  const pane=(px,py,pz,face,big)=>panes.push({m:m.clone().multiply(new T.Matrix4().makeTranslation(px,py,pz)).multiply(new T.Matrix4().makeRotationY(face)).multiply(new T.Matrix4().makeScale(1,big||1,1)),room});
  if(st==='cube'){            // the islands: white cubes, flat roofs, a dome in the district's colour
    const h=.42*floors+.06,white='#f7f4ee';
    const g=islRound(w,h,d,.05);g.translate(0,h/2,0);islAdd(bag,g,m,white,true);
    islBox(bag,w+.04,.06,d+.04,0,h+.03,0,'#ffffff',m);
    if(rnd()<.55){const top=islRound(w*.55,.34,d*.55,.04);top.translate(-w*.18,h+.2,-d*.14);islAdd(bag,top,m,white,true)}
    if(rnd()<.5){const dm=new T.SphereGeometry(Math.min(w,d)*.24,18,10,0,Math.PI*2,0,Math.PI/2);dm.translate(w*.2,h+.06,d*.16);islAdd(bag,dm,m,roof)}
    const door=islRound(.14,.26,.04,.012);door.translate(0,.14,d/2+.02);islAdd(bag,door,m,islShade(roof,.9));
    for(let f=0;f<floors;f++)[-1,1].forEach(s=>{if(f||s<0)pane(s*w*.27,.27+f*.42,d/2+.03,0)});
    pane(w/2+.03,.27,0,Math.PI/2);
    return;
  }
  if(st==='venetian'){        // the canal city: tall plaster houses, low tiled roofs, tall windows
    const fh=.42,h=fh*floors+.1;
    const g=islRound(w,h,d,.025);g.translate(0,h/2,0);islAdd(bag,g,m,wall,true);
    islBox(bag,w+.06,.05,d+.06,0,h+.02,0,'#f1ebe0',m);                       // the cornice
    islBox(bag,w+.02,.035,d+.02,0,fh+.06,0,'#efe6d6',m);                      // a string course
    const rf=islHip(w+.12,d+.12,.22);rf.translate(0,h+.04,0);islAdd(bag,rf,m,'#b8573c');
    if(rnd()<.6){const ch=new T.CylinderGeometry(.06,.035,.22,8);ch.translate(w*.25,h+.26,d*.15);islAdd(bag,ch,m,'#c9a487')}
    const nx=Math.max(2,Math.floor(w/.24));
    for(let f=0;f<floors;f++)for(let k=0;k<nx;k++){
      if(!(f===0&&k===Math.floor(nx/2)))pane(-w/2+(k+.5)*(w/nx),.24+f*fh,d/2+.03,0,1.4);
      if(k<2)pane(w/2+.03,.24+f*fh,-d/4+k*d/2,Math.PI/2,1.4)}
    const door=islRound(.15,.3,.04,.012);door.translate(-w/2+(Math.floor(nx/2)+.5)*(w/nx),.15,d/2+.02);islAdd(bag,door,m,'#5a3a28');
    return;
  }
  if(st==='timber'){          // the castle town: a stone ground floor, a half-timbered upper one
    const fh=.4,h=fh*floors+.04,beam='#4a3528',upper='#efe3c8';
    islBox(bag,w,fh,d,0,fh/2,0,'#a9a39a',m,true);
    for(let f=1;f<floors;f++){
      islBox(bag,w+.06,fh,d+.06,0,fh*f+fh/2,0,upper,m);
      islBox(bag,w+.08,.04,d+.08,0,fh*f+.02,0,beam,m);
      [-1,0,1].forEach(k=>{islBox(bag,.04,fh,.012,k*(w/2+.02),fh*f+fh/2,d/2+.035,beam,m);
        islBox(bag,.012,fh,.04,w/2+.035,fh*f+fh/2,k*(d/2-.02),beam,m)});
      const br=new T.BoxGeometry(.03,Math.hypot(fh,w/2)*.95,.012);br.rotateZ(Math.atan2(w/2,fh));br.translate(-w/4,fh*f+fh/2,d/2+.035);islAdd(bag,br,m,beam);
    }
    const rf=islGable(w+.14,d+.2,Math.min(w,d)*.8+.12);rf.translate(0,h,0);islAdd(bag,rf,m,roof);
    if(rnd()<.5){const ch=islRound(.11,.34,.11,.02);ch.translate(-w*.2,h+.3,d*.12);islAdd(bag,ch,m,'#8f877c')}
    for(let f=0;f<floors;f++)[-1,1].forEach(s=>{if(f||s>0)pane(s*w*.24,.22+f*fh,d/2+.04,0)});
    pane(w/2+.04,.22+(floors-1)*fh,0,Math.PI/2);
    const door=islRound(.15,.26,.04,.012);door.translate(-w*.24,.14,d/2+.02);islAdd(bag,door,m,'#5a3a28');
    return;
  }
  if(st==='cabin'){           // the forest: log cabins, mossy roofs, a stone chimney
    const h=.4*floors+.06,log='#8b5a33',dark='#6f4627';
    islBox(bag,w,h,d,0,h/2,0,log,m,true);
    for(let yy=.07;yy<h-.02;yy+=.09){islBox(bag,w+.03,.022,d+.03,0,yy,0,dark,m)}
    [-1,1].forEach(sx=>[-1,1].forEach(sz=>islBox(bag,.06,h,.06,sx*w/2,h/2,sz*d/2,'#5b3a22',m)));
    const rf=islGable(w+.24,d+.26,Math.min(w,d)*.62+.1);rf.translate(0,h,0);islAdd(bag,rf,m,roof);
    const ch=islRound(.13,.5,.13,.02);ch.translate(w*.28,h+.18,-d*.12);islAdd(bag,ch,m,'#8f8a7c');
    pane(-w*.22,.24,d/2+.03,0);pane(w*.22,.24,d/2+.03,0);pane(w/2+.03,.24,0,Math.PI/2);
    const door=islRound(.15,.28,.04,.012);door.translate(0,.15,d/2+.02);islAdd(bag,door,m,'#4a2f1d');
    islBox(bag,w*.6,.03,.22,0,.015,d/2+.11,'#7a5233',m);                       // a porch
    return;
  }
  // the island: soft plaster cottages in the district's colour, tiled gables
  const hgt=.46*floors+.08;
  const wg=islRound(w,hgt,d,.045);wg.translate(0,hgt/2,0);islAdd(bag,wg,m,wall,true);
  const pg=islRound(w+.05,.12,d+.05,.03);pg.translate(0,.06,0);islAdd(bag,pg,m,islShade(wall,.82));
  const rg=islGable(w+.16,d+.18,Math.min(w,d)*.55+.1);rg.translate(0,hgt,0);islAdd(bag,rg,m,roof);
  if(rnd()<.6){const cg=islRound(.12,.32,.12,.02);cg.translate(w*.22,hgt+.27,d*(rnd()<.5?.16:-.16));islAdd(bag,cg,m,'#b9b2a8')}
  const nx=Math.max(1,Math.floor(w/.32));
  for(let f=0;f<floors;f++)for(let k=0;k<nx;k++)for(const side of [1,-1]){
    if(f===0&&side===1&&k===Math.floor(nx/2))continue;
    pane(-w/2+(k+.5)*(w/nx),.29+f*.46,side*(d/2+.05),side>0?0:Math.PI);
  }
  const door=islRound(.15,.27,.05,.015);door.translate(-w/2+(Math.floor(nx/2)+.5)*(w/nx),.15,d/2+.05);islAdd(bag,door,m,'#6b4a34');
}
/* ---------------- a room's building: closed while quiet, open while it works ----------------
   Walls, their windows and a roof round the room's floor (24k draws the office inside).
   The walls are scaled down to a low parapet and the roof lifts away as it opens. */
var ISL_SHELL_H={cottage:1.05,cube:1,venetian:1.3,stone:1.15,cabin:.98};
function islShell(S,q,st,col,v){
  const T=OF3.T,U=OF3_U,r=q.r,W=r.w/U,D=r.h/U,cx=(r.x+r.w/2)/U,cz=(r.y+r.h/2)/U,H=ISL_SHELL_H[st]||1.05;
  const wall=st==='cube'?'#f7f4ee':st==='venetian'?islMix(ISL_PLASTER[Math.abs(Math.round(q.cx*7+q.cz*3))%ISL_PLASTER.length],col,.38)
    :st==='stone'?'#b8b1a6':st==='cabin'?'#8b5a33':islMix('#f3e7d3',col,.2);
  const wb=islBag(),pb=islBag(),rb=islBag(),t=.1;
  // which wall faces the plaza: the door goes there
  const nx=-cx,nz=-cz,faces=[[0,1,'z',1],[0,-1,'z',-1],[1,0,'x',1],[-1,0,'x',-1]];
  const door=faces.reduce((b,f)=>(f[0]*nx+f[1]*nz)>(b[0]*nx+b[1]*nz)?f:b,faces[0]);
  faces.forEach(f=>{
    const along=f[2]==='z'?W:D,ox=f[2]==='x'?f[3]*(W/2-t/2):0,oz=f[2]==='z'?f[3]*(D/2-t/2):0;
    const bw=f[2]==='z'?along:t,bd=f[2]==='z'?t:along;
    islBox(wb,bw,H,bd,ox,H/2,oz,wall,null,true);
    islBox(wb,bw+.04,.07,bd+.04,ox,H-.035,oz,st==='cabin'?'#5b3a22':st==='stone'?'#9c958a':'#f6efe2');   // cornice
    islBox(wb,bw+.03,.13,bd+.03,ox,.065,oz,islShade(wall,.8));                                            // plinth
    if(st==='cabin')for(let yy=.12;yy<H-.06;yy+=.1)islBox(wb,bw+.025,.022,bd+.025,ox,yy,oz,'#6f4627');
    if(st==='venetian')islBox(wb,bw+.03,.035,bd+.03,ox,H*.5,oz,'#efe6d6');
    // windows along it, and a door on the side facing the plaza
    const n=Math.max(2,Math.floor(along/.55)),isDoor=f===door,mid=Math.floor(n/2),ds=-along/2+(mid+.5)*(along/n);
    for(let k=0;k<n;k++){
      const s=-along/2+(k+.5)*(along/n),px=f[2]==='z'?s:ox+f[3]*(t/2+.012),pz=f[2]==='z'?oz+f[3]*(t/2+.012):s;
      if(isDoor&&k===mid){const dg=new T.BoxGeometry(f[2]==='z'?.26:.03,.5,f[2]==='z'?.03:.26);dg.translate(px,.25,pz);islAdd(wb,dg,null,'#5a3a28');continue}
      const rows=st==='venetian'?[H*.3,H*.72]:[H*.58];
      rows.forEach(y=>{const pg=new T.BoxGeometry(f[2]==='z'?.22:.025,st==='venetian'?.3:.3,f[2]==='z'?.025:.22);pg.translate(px,y,pz);islAdd(pb,pg,null,'#ffffff');
        const fr=new T.BoxGeometry(f[2]==='z'?.28:.02,.04,f[2]==='z'?.02:.28);fr.translate(px,y-.17,pz);islAdd(wb,fr,null,'#f4eee4')});
    }
    if(st==='venetian'&&isDoor){const aw=new T.BoxGeometry(f[2]==='z'?.5:.18,.04,f[2]==='z'?.18:.5);
      if(f[2]==='z')aw.rotateX(f[3]*.35);else aw.rotateZ(-f[3]*.35);
      aw.translate(f[2]==='z'?ds:ox+f[3]*.14,.62,f[2]==='z'?oz+f[3]*.14:ds);islAdd(wb,aw,null,col)}
  });
  // the roof, in the setting's shape
  const dark=islShade(col,.86);
  if(st==='cube'){
    islBox(rb,W+.08,.07,D+.08,0,.035,0,'#ffffff');
    islBox(rb,W+.08,.12,.06,0,.12,(D+.02)/2,'#f7f4ee');islBox(rb,W+.08,.12,.06,0,.12,-(D+.02)/2,'#f7f4ee');
    islBox(rb,.06,.12,D+.08,(W+.02)/2,.12,0,'#f7f4ee');islBox(rb,.06,.12,D+.08,-(W+.02)/2,.12,0,'#f7f4ee');
    const dm=new T.SphereGeometry(Math.min(W,D)*.27,28,14,0,Math.PI*2,0,Math.PI/2);dm.translate(W*.12,.07,-D*.08);islAdd(rb,dm,null,col);
    const cr=new T.CylinderGeometry(.015,.015,.22,6);cr.translate(W*.12,Math.min(W,D)*.27+.16,-D*.08);islAdd(rb,cr,null,'#f4f1ea');
  }else if(st==='venetian'){
    const rf=islHip(W+.18,D+.18,.38);islAdd(rb,rf,null,'#b8573c');
    const al=islRound(.7,.06,.5,.02);al.translate(-W*.18,.3,D*.1);islAdd(rb,al,null,'#8a6a4f');      // an altana, the roof terrace
  }else if(st==='stone'){
    const rf=islHip(W+.2,D+.2,1.15);islAdd(rb,rf,null,islMix('#4a5160',col,.45));
    const tw=new T.CylinderGeometry(.22,.22,.65,16);tw.translate(W/2,.25,D/2);islAdd(rb,tw,null,'#b8b1a6');
    const tc=new T.ConeGeometry(.28,.5,16);tc.translate(W/2,.82,D/2);islAdd(rb,tc,null,dark);
  }else{
    const long=W>=D,rise=st==='cabin'?Math.min(W,D)*.5:Math.min(W,D)*.42,g=islGable((long?W:D)+.3,(long?D:W)+.3,rise);
    if(!long)g.rotateY(Math.PI/2);islAdd(rb,g,null,st==='cabin'?islMix('#3f5f3a',col,.3):dark);
    const ch=islRound(.16,.5,.16,.02);ch.translate(W*.28,rise*.55,-D*.18);islAdd(rb,ch,null,st==='cabin'?'#8f8a7c':'#c9bfb2');
  }
  const g=new T.Group();g.position.set(cx,OF3_SLAB,cz);
  const wg=new T.Group();g.add(wg);
  const wm=islMesh(wb,of3Mat('isl-shell',{vertexColors:true,roughness:.85}));wm.userData.keep=1;
  if(OF3.hq){wm.castShadow=true;wm.receiveShadow=true}
  wg.add(wm);
  const pm=islMesh(pb,ISL.shellPane);pm.userData.keep=1;wg.add(pm);
  const rmat=new T.MeshStandardMaterial({vertexColors:true,roughness:.72,transparent:true});
  const rm=islMesh(rb,rmat);rm.position.y=H;rm.userData.keep=1;if(OF3.hq)rm.castShadow=true;g.add(rm);
  g.userData.keep=1;S.add(g);
  ISL.shells.push({key:r.kind+':'+r.name,name:r.name,g,wg,rm,rmat,H,t:0,last:-1e9});
}
/* Is anything happening in a room, so its building should be open? Read from the Office's
   own people (24d), never a timer: somebody of that room working, walking or speaking,
   somebody visiting it, or the person looking into it. */
function islShellWant(){
  const O=OFFICE,want={},key=r=>r.kind+':'+r.name;
  Object.values(O.people||{}).forEach(p=>{
    if(!p||!p.room)return;
    const home=key(p.room),at=islRoomAt({x:p.x,y:p.y}),here=at?key(at):'';
    if(p.busy||p.say||p.hop)want[home]=1;
    if(p.mode==='walk'){want[home]=1;if(here)want[here]=1}
    else if(here&&here!==home)want[here]=1;
  });
  ISL.shells.forEach(s=>{if(OF3.focus===s.name||OF3.follow===s.name)want[s.key]=1});
  return want;
}
function islShells(now,dt){
  if(!ISL.shells.length)return;
  const want=islShellWant(),snap=!!OFFICE.static;
  ISL.shells.forEach(s=>{
    if(want[s.key])s.last=now;
    const goal=now-s.last<3500?1:0;
    if(snap)s.t=goal;else if(s.t!==goal)s.t=goal>s.t?Math.min(1,s.t+dt/.75):Math.max(0,s.t-dt/1.1);
    const e=s.t*s.t*(3-2*s.t);
    if(s.e===e)return;s.e=e;
    s.wg.scale.y=1-e*.86;
    s.rm.position.y=s.H*(1-e*.86)+e*1.9;
    s.rmat.opacity=Math.max(0,1-e*1.6);s.rm.visible=s.rmat.opacity>.02;
    OF3.dirty=true;
  });
}
function islShellsMoving(){const now=performance.now();return ISL.shells.some(s=>s.t!==(now-s.last<3500?1:0))}
/* ---------------- your agent's landmark, in the setting's style ---------------- */
function islLandmark(S,bag,st,x,y0,z,accent){
  const T=OF3.T,lamp=(r,h,y)=>{const m=new T.Mesh(new T.CylinderGeometry(r,r,h,16),new T.MeshStandardMaterial({color:'#fff6d8',emissive:'#ffd36b',emissiveIntensity:.3,roughness:.2}));
    m.position.set(x,y,z);m.userData.keep=1;S.add(m);ISL.lamp=m};
  if(st==='windmill'){        // the islands: a white windmill, its sails turning in the breeze
    const tw=new T.CylinderGeometry(.36,.46,1.6,24);tw.translate(x,y0+.8,z);islAdd(bag,tw,null,'#f7f4ee',true);
    const cap=new T.ConeGeometry(.44,.5,24);cap.translate(x,y0+1.85,z);islAdd(bag,cap,null,'#8a6a4f');
    const dr=islRound(.2,.34,.06,.02);dr.translate(x+.3,y0+.17,z+.3);islAdd(bag,dr,null,accent);
    lamp(.06,.12,y0+1.1);ISL.lamp.position.set(x+.32,y0+1.1,z+.32);
    const sails=new T.Group(),sb=islBag();
    for(let k=0;k<4;k++){const a=k*Math.PI/2,arm=new T.BoxGeometry(.04,1.05,.03);arm.translate(0,.55,0);arm.rotateZ(a);islAdd(sb,arm,null,'#6b4a34');
      const sail=new T.BoxGeometry(.2,.78,.012);sail.translate(.12,.62,0);sail.rotateZ(a);islAdd(sb,sail,null,'#fffaf0')}
    const sm=islMesh(sb,of3Mat('isl-land',{vertexColors:true,roughness:.8}));sails.add(sm);
    sails.position.set(x+.33,y0+1.55,z+.33);sails.rotation.y=Math.PI/4;sails.userData.keep=1;S.add(sails);ISL.spin=sm;
    return 2.2;
  }
  if(st==='campanile'){       // the canal city: a brick bell tower with a green spire
    const sq=(w,h,y,c)=>islBox(bag,w,h,w,x,y,z,c,null,true);
    sq(.62,2.3,y0+1.15,'#b5654e');sq(.7,.1,y0+2.32,'#efe9dd');
    for(let k=0;k<4;k++){const a=k*Math.PI/2;islBox(bag,.12,.42,.12,x+Math.cos(a)*.27+Math.sin(a)*.27,y0+2.6,z+Math.sin(a)*.27-Math.cos(a)*.27,'#efe9dd')}
    sq(.7,.1,y0+2.86,'#efe9dd');
    const sp=islHip(.66,.66,1.0);sp.translate(x,y0+2.9,z);islAdd(bag,sp,null,'#5f8f7a');
    const an=new T.SphereGeometry(.06,10,8);an.translate(x,y0+3.98,z);islAdd(bag,an,null,'#e8c35a');
    lamp(.14,.28,y0+2.6);return 4;
  }
  if(st==='keep'){            // the castle: the keep, crenellated, its banner in your agent's colour
    const tw=new T.CylinderGeometry(.6,.68,2.4,28);tw.translate(x,y0+1.2,z);islAdd(bag,tw,null,'#a9a196',true);
    const rim=new T.CylinderGeometry(.7,.7,.12,28);rim.translate(x,y0+2.44,z);islAdd(bag,rim,null,'#9a9287');
    for(let k=0;k<12;k++){const a=k/12*Math.PI*2;islBoxAt(bag,.16,.2,.12,x+Math.cos(a)*.62,y0+2.6,z+Math.sin(a)*.62,-a,'#a9a196')}
    const pole=new T.CylinderGeometry(.02,.02,.9,6);pole.translate(x,y0+2.95,z);islAdd(bag,pole,null,'#3a3f4a');
    islBox(bag,.42,.26,.02,x+.22,y0+3.22,z,accent);
    lamp(.12,.26,y0+1.6);ISL.lamp.position.set(x+.42,y0+1.6,z+.42);
    return 3.5;
  }
  if(st==='watchtower'){      // the forest: a wooden watchtower over the trees
    [[-1,-1],[1,-1],[-1,1],[1,1]].forEach(c=>{const l=new T.CylinderGeometry(.05,.065,2.1,8);l.translate(x+c[0]*.36,y0+1.05,z+c[1]*.36);islAdd(bag,l,null,'#6f4627')});
    [.6,1.3].forEach(y=>{islBox(bag,.82,.05,.05,x,y0+y,z+.36,'#7a5233');islBox(bag,.82,.05,.05,x,y0+y,z-.36,'#7a5233');
      islBox(bag,.05,.05,.82,x+.36,y0+y,z,'#7a5233');islBox(bag,.05,.05,.82,x-.36,y0+y,z,'#7a5233')});
    islBox(bag,1.0,.08,1.0,x,y0+2.12,z,'#7a5233');
    islBox(bag,.9,.5,.9,x,y0+2.42,z,'#8b5a33',null,true);
    const rf=islHip(1.15,1.15,.6);rf.translate(x,y0+2.67,z);islAdd(bag,rf,null,'#3f5f3a');
    lamp(.1,.18,y0+2.45);ISL.lamp.position.set(x+.46,y0+2.45,z+.46);
    return 3.3;
  }
  // the island: a lighthouse
  const hh=2.4,bands=5;
  for(let k=0;k<bands;k++){const r0=.46-k*.045,r1=.46-(k+1)*.045,g=new T.CylinderGeometry(r1,r0,hh/bands,28);
    g.translate(x,y0+(k+.5)*hh/bands,z);islAdd(bag,g,null,k%2?'#f4efe6':'#d9483b')}
  const gal=new T.CylinderGeometry(.38,.38,.06,28);gal.translate(x,y0+hh+.03,z);islAdd(bag,gal,null,'#3a3f4a');
  const cap=new T.ConeGeometry(.3,.36,28);cap.translate(x,y0+hh+.56,z);islAdd(bag,cap,null,'#d9483b');
  lamp(.21,.32,y0+hh+.22);
  return 2.9;
}
/* ---------------- trees ---------------- */
function islTree(bag,kind,rnd,x,y,z,s){
  const T=OF3.T,leaf=(c)=>'#'+new T.Color(c).offsetHSL(0,0,(rnd()-.5)*.08).getHexString();
  if(kind==='pine'){
    const t=new T.CylinderGeometry(.035*s,.06*s,.4*s,6);t.translate(x,y+.2*s,z);islAdd(bag,t,null,'#5e4630');
    const c=leaf(rnd()<.5?'#2f5d3a':'#3c6e45');
    [[.38,.62,.42],[.3,.52,.72],[.2,.42,.98]].forEach(k=>{const g=new T.ConeGeometry(k[0]*s,k[1]*s,8);g.translate(x,y+k[2]*s,z);islAdd(bag,g,null,c,'leaf')});
    return;
  }
  if(kind==='cypress'){
    const g=new T.IcosahedronGeometry(.22*s,1);g.scale(.8,2.6,.8);g.translate(x,y+.6*s,z);islAdd(bag,g,null,leaf('#3f6b45'),'leaf');return;
  }
  if(kind==='olive'){
    if(rnd()<.25)return islTree(bag,'cypress',rnd,x,y,z,s*.9);
    const t=new T.CylinderGeometry(.03*s,.05*s,.3*s,6);t.translate(x,y+.15*s,z);islAdd(bag,t,null,'#7a6a55');
    const f=new T.IcosahedronGeometry(.3*s,1);f.scale(1.2,.8,1.2);f.translate(x,y+.42*s,z);islAdd(bag,f,null,leaf('#8a9a5b'),'leaf');return;
  }
  const t=new T.CylinderGeometry(.04*s,.07*s,.42*s,8);t.translate(x,y+.2*s,z);islAdd(bag,t,null,'#7a5a3e');
  const f=new T.IcosahedronGeometry(.36*s,2);f.scale(1,1.15,1);f.translate(x,y+.62*s,z);
  islAdd(bag,f,null,leaf(rnd()<.5?'#5f9e57':'#78b062'),'leaf');
}
/* ---------------- building the town ---------------- */
function islWorld(S,still,L,v){
  const T=OF3.T,U=OF3_U,top=ISL.top,rnd=of3Rand(7+L.rooms.length*31),isl=(v.office&&v.office.island)||{};
  const setName=islSetName(isl),SET=ISL_SETS[setName];
  if(ISL.tex){ISL.tex.dispose();ISL.tex=null}
  Object.assign(ISL,{train:null,cars:[],curve:null,stations:{},queue:[],windows:null,panes:[],hourShown:-1,busySig:'',
    shells:[],spin:null,fitPts:[],set:setName,carrier:SET.carrier,lamp:null});
  ISL.shellPane=new T.MeshStandardMaterial({color:'#2f3d52',emissive:'#ffb84d',emissiveIntensity:0,roughness:.3});
  (OFFICE.papers||[]).forEach(pp=>{if(pp)pp._isl=1});   // what was in the air before the town was drawn
  const sh=islShapes(L,setName);ISL.sh=sh;
  const carry=isl.train!==false;
  // the line everything else keeps off: a railway, a canal, a ferry's route, the castle's wall
  const line=setName==='islands'?islWaterRing(sh):islRailLine(sh,setName==='canals'?.9:.62,setName==='canals');
  if(setName==='island'&&carry)sh.rail=line;
  if(setName==='canals'){
    sh.canal=line;
    // two side canals out to the lagoon, between rooms, where no street crosses
    const angs=sh.rooms.map(q=>Math.atan2(q.cz,q.cx)).sort((a,b)=>a-b),gaps=[];
    for(let i=0;i<angs.length;i++){const a=angs[i],b=i+1<angs.length?angs[i+1]:angs[0]+Math.PI*2;gaps.push({mid:(a+b)/2,w:b-a})}
    sh.side=gaps.sort((a,b)=>b.w-a.w).slice(0,2).map(g=>{const ca=Math.cos(g.mid),sa=Math.sin(g.mid);
      let r0=0,bd=1e9;line.forEach(p=>{const pa=Math.atan2(p[1],p[0]),dd=Math.abs(((pa-g.mid+Math.PI*3)%(Math.PI*2))-Math.PI);if(dd<bd){bd=dd;r0=Math.hypot(p[0],p[1])}});
      return [[ca*r0,sa*r0],[ca*(sh.rmax+3),sa*(sh.rmax+3)]]});
  }
  if(setName==='castle'){
    // the wall goes round the whole town, districts and all: out to where the land would end
    const M=line.length,r=line.map((p,i)=>{const a=i/M*Math.PI*2;let rr=Math.hypot(p[0],p[1]);
      while(rr<40&&islCore(sh,Math.cos(a)*rr,Math.sin(a)*rr)<.15)rr+=.08;return rr});
    let w=r.slice();for(let pass=0;pass<4;pass++)w=w.map((x,i)=>Math.max(r[i],(w[(i+M-1)%M]+x*2+w[(i+1)%M])/4));
    sh.wallR=w.map(x=>x+.25);
  }
  if(setName==='forest'){
    // a river behind the town (the top of the screen), winding, never into it
    const c=sh.rmax+2.7,pts=[];
    for(let t=-sh.rmax-12;t<=sh.rmax+12;t+=.5){const wob=Math.sin(t*.45)*1.1+Math.sin(t*.17+1)*.8;
      pts.push([(t-c-wob)*.7071,(-t-c-wob)*.7071])}
    sh.river=pts;
  }
  const dist=(x,z)=>islDist(sh,x,z);
  const height=(x,z)=>{const d=dist(x,z),k=islSmooth(-.05,.55,d);return top-(top+1.5)*Math.pow(k,.8)};
  ISL.height=height;
  const bag=islBag(),obst=[];
  // extent of the town (what the camera frames) and of the ground (what is drawn)
  let x0=-4,x1=4,z0=-4,z1=4;
  sh.rooms.forEach(q=>{x0=Math.min(x0,q.dx-3,q.cx-4);x1=Math.max(x1,q.dx+3,q.cx+4);z0=Math.min(z0,q.dz-3,q.cz-4);z1=Math.max(z1,q.dz+3,q.cz+4)});
  x0=Math.min(x0,sh.lh.x-3);x1=Math.max(x1,sh.lh.x+3);z0=Math.min(z0,sh.lh.z-3);z1=Math.max(z1,sh.lh.z+3);
  ISL.ext={x0,x1,z0,z1};
  const grow=setName==='forest'?26:setName==='castle'?7:setName==='canals'?2:0;
  const gx0=x0-grow,gx1=x1+grow,gz0=z0-grow,gz1=z1+grow;
  const onPath=(x,z)=>Math.hypot(x,z)<sh.plaza-.25||sh.rooms.some(q=>islSeg(x,z,0,0,q.cx,q.cz)<.42)
    ||Math.abs(Math.hypot(x,z)-OF3_RING/U)<.3||(!!sh.lead&&islSeg(x,z,sh.lh.x,sh.lh.z,sh.lead.cx,sh.lead.cz)<.32);
  const onWaterLine=(x,z,m)=>(sh.canal&&islLine(sh.canal,x,z,true)<m)||(sh.side&&sh.side.some(c=>islLine(c,x,z,false)<m-.1))||(sh.river&&islLine(sh.river,x,z,false)<m+.2);
  // ---- the carrier's way: a track and stations, a ferry's docks, a gondola's moorings ----
  const rail=[];
  const curvePts=line.map(p=>new T.Vector3(p[0],top+.03,p[1]));
  const curve=new T.CatmullRomCurve3(curvePts,true,'centripetal');
  const up=new T.Vector3(0,1,0);
  if(carry){
    ISL.curve=curve;ISL.len=curve.getLength();
    for(let i=0;i<240;i++)rail.push(curve.getPointAt(i/240));
    if(SET.carrier==='train'){
      const n=Math.floor(ISL.len/.3),sleeper=new T.BoxGeometry(.44,.04,.11);
      for(let i=0;i<n;i++){const u=i/n,p=curve.getPointAt(u),tg=curve.getTangentAt(u);
        islAdd(bag,sleeper.clone(),new T.Matrix4().lookAt(new T.Vector3(),tg,up).setPosition(p.x,top+.02,p.z),'#8a6a4f')}
      sleeper.dispose();
      [-.14,.14].forEach(side=>{const ps=[];
        for(let i=0;i<=240;i++){const u=(i/240)%1,p=curve.getPointAt(u),tg=curve.getTangentAt(u),nx=-tg.z,nz=tg.x,l=Math.hypot(nx,nz)||1;
          ps.push(new T.Vector3(p.x+nx/l*side,top+.06,p.z+nz/l*side))}
        islAdd(bag,new T.TubeGeometry(new T.CatmullRomCurve3(ps,true),360,.022,6,true),null,'#9aa3ad')});
    }
    sh.rooms.forEach(q=>{
      let best=0,bd=1e9;for(let i=0;i<240;i++){const p=rail[i],dd=Math.hypot(p.x-q.dx,p.z-q.dz)+Math.hypot(p.x-q.cx,p.z-q.cz)*.4;if(dd<bd){bd=dd;best=i/240}}
      ISL.stations[q.r.kind+':'+q.r.name]=best;
      if(q.r.kind==='lead')ISL.home=best;
      const p=curve.getPointAt(best),tg=curve.getTangentAt(best),nx=-tg.z,nz=tg.x,l=Math.hypot(nx,nz)||1;
      const side=(nx*(q.cx-p.x)+nz*(q.cz-p.z))>0?1:-1;
      const col=v.colors[q.r.color]||'#94a3b8';
      if(SET.carrier==='train'){
        const m=new T.Matrix4().lookAt(new T.Vector3(),tg,up).setPosition(p.x+nx/l*side*.5,top,p.z+nz/l*side*.5);
        const pl=islRound(.42,.12,1.15,.03);pl.translate(0,.06,0);islAdd(bag,pl,m,'#e2d6c2');
        const rf=islRound(.54,.05,.95,.02);rf.translate(0,.6,0);islAdd(bag,rf,m,col);
        [-.38,.38].forEach(zz=>{const po=new T.CylinderGeometry(.025,.025,.48,8);po.translate(.13,.36,zz);islAdd(bag,po,m,'#5a5f68')});
      }else if(SET.carrier==='gondola'){
        // two striped mooring poles at the canal's edge on the room's side
        [-.24,.24].forEach(off=>{const bx=p.x+nx/l*side*.3+tg.x*off,bz=p.z+nz/l*side*.3+tg.z*off;
          for(let k=0;k<5;k++){const c=new T.CylinderGeometry(.03,.03,.16,8);c.translate(bx,-.2+k*.16+.08,bz);islAdd(bag,c,null,k%2?'#f4f1ea':col)}
          const cap=new T.SphereGeometry(.04,8,6);cap.translate(bx,.62,bz);islAdd(bag,cap,null,'#e8c35a')});
      }else{
        // a wooden jetty from the islet's shore out to the ferry
        let lx=p.x,lz=p.z;const dx=q.cx-p.x,dz=q.cz-p.z,dl=Math.hypot(dx,dz)||1;
        for(let k=0;k<40&&dist(lx,lz)>-.05;k++){lx+=dx/dl*.08;lz+=dz/dl*.08}
        const len=Math.hypot(lx-p.x,lz-p.z)+.25,ang=Math.atan2(dx,dz),mx=(lx+p.x)/2-dx/dl*.12,mz=(lz+p.z)/2-dz/dl*.12;
        islBox(bag,.32,.05,len,0,0,0,'#a87a52',islM(mx,top-.06,mz,ang));
        for(let k=0;k<=Math.floor(len/.3);k++)[-1,1].forEach(s=>{const t2=-len/2+k*.3,c=new T.CylinderGeometry(.025,.025,.42,6);c.translate(s*.15,-.12,t2);islAdd(bag,c,islM(mx,top-.06,mz,ang),'#6b4a34')});
      }
    });
  }
  const offRail=(x,z,m)=>!rail.some(p=>Math.hypot(p.x-x,p.z-z)<m)&&!onWaterLine(x,z,m+.1);
  // ---- each room's building ----
  sh.rooms.forEach(q=>{islShell(S,q,SET.shell,v.colors[q.r.color]||'#94a3b8',v);obst.push({rect:q})});
  // ---- the houses: each department's district, behind its room as the camera sees it ----
  const b=of3Basis(),scr=(x,z)=>({sx:x*b.right.x+z*b.right.z,sy:x*b.up.x+z*b.up.z});
  const panes=[];
  const roomBox=q=>{const cs=[[q.cx-q.hx,q.cz-q.hz],[q.cx+q.hx,q.cz-q.hz],[q.cx-q.hx,q.cz+q.hz],[q.cx+q.hx,q.cz+q.hz]].map(c=>scr(c[0],c[1]));
    return {x0:Math.min(...cs.map(c=>c.sx)),x1:Math.max(...cs.map(c=>c.sx)),y0:Math.min(...cs.map(c=>c.sy)),y1:Math.max(...cs.map(c=>c.sy))}};
  const boxes=sh.rooms.map(roomBox);
  const spots=[];
  const free=(x,z,gap)=>{
    if(height(x,z)<top-.01||dist(x,z)>-.4)return false;
    if(sh.rooms.some(o=>Math.abs(x-o.cx)<o.hx+.5&&Math.abs(z-o.cz)<o.hz+.5))return false;
    if(Math.hypot(x,z)<sh.hub+.3||sh.rooms.some(o=>islSeg(x,z,0,0,o.cx,o.cz)<.65))return false;   // the streets stay clear
    if(Math.hypot(x-sh.lh.x,z-sh.lh.z)<1.05)return false;
    if(sh.wallR&&Math.hypot(x,z)>islWallAt(sh,Math.atan2(z,x))-.45)return false;              // inside the castle's walls
    return offRail(x,z,.58)&&!spots.some(s=>Math.hypot(s.x-x,s.z-z)<gap);
  };
  // never in front of a room as the camera looks: its people would be behind a house
  const lowAt=(x,z)=>{const s=scr(x,z);let low=false;
    for(const bx of boxes){if(s.sx>bx.x0-.5&&s.sx<bx.x1+.5&&s.sy<bx.y1+.2){if(s.sy>bx.y0-1.1)return null;low=true}}return low};
  const tall={cottage:3,cube:2,venetian:4,timber:3,cabin:1};
  sh.rooms.forEach(q=>{
    const r=q.r,col=v.colors[r.color]||'#94a3b8';
    const want=r.kind==='dept'?officeHouses(isl,r):r.kind==='lead'?3:r.kind==='floor'?3:2;
    let made=0;
    for(let tries=0;tries<want*70&&made<want;tries++){
      const a=rnd()*Math.PI*2,rr=.2+rnd()*(q.dr+.6),x=q.dx+Math.cos(a)*rr,z=q.dz+Math.sin(a)*rr;
      if(!free(x,z,SET.house==='venetian'?.66:.74))continue;
      const low=lowAt(x,z);if(low===null)continue;
      spots.push({x,z});made++;obst.push({x,z,r:.42});
      const base=new T.Color(col),wall=SET.house==='venetian'?islMix(ISL_PLASTER[Math.floor(rnd()*ISL_PLASTER.length)],col,.22)
        :'#'+base.clone().offsetHSL((rnd()-.5)*.04,(rnd()-.5)*.1,(rnd()-.3)*.12+.1).getHexString();
      const roof=SET.house==='cube'?col:SET.house==='timber'?islMix('#5b4a44',col,.35):SET.house==='cabin'?islMix('#3f5f3a',col,.25):ISL_ROOF[Math.floor(rnd()*ISL_ROOF.length)];
      const rot=Math.atan2(q.cz-z,q.cx-x)+(rnd()-.5)*.4,hi=tall[SET.house]||3;
      islHouse(SET.house,bag,panes,rnd,x,height(x,z)-.04,z,rot,.6+rnd()*.3,.54+rnd()*.24,low?1:Math.min(hi,1+Math.floor(rnd()*(made===1?2:hi))),wall,roof,r);
    }
  });
  // the canal city fills every free street with houses; the others leave fields and woods
  if(setName==='canals'){
    for(let tries=0,made=0;tries<2600&&made<70;tries++){
      const a=rnd()*Math.PI*2,rr=sh.hub+rnd()*(sh.rmax+1.4-sh.hub),x=Math.cos(a)*rr,z=Math.sin(a)*rr;
      if(!free(x,z,.62))continue;const low=lowAt(x,z);if(low===null)continue;
      spots.push({x,z});made++;obst.push({x,z,r:.4});
      const near=onWaterLine(x,z,.75),rot=near?Math.atan2(-z,-x):Math.round((Math.atan2(-z,-x)+(rnd()-.5)*.5)/(Math.PI/2))*(Math.PI/2);
      islHouse('venetian',bag,panes,rnd,x,height(x,z)-.04,z,rot,.52+rnd()*.24,.5+rnd()*.2,low?1:2+Math.floor(rnd()*3),ISL_PLASTER[Math.floor(rnd()*ISL_PLASTER.length)],'#b8573c',null);
    }
  }
  // ---- your agent's landmark ----
  {
    const lh=sh.lh,y0=height(lh.x,lh.z)-.04,accent=v.colors[(sh.lead&&sh.lead.r.color)]||'#14b8a6';
    const hgt=islLandmark(S,bag,SET.mark,lh.x,y0,lh.z,accent);
    obst.push({x:lh.x,z:lh.z,r:.6});ISL.fitPts.push([lh.x,hgt,lh.z]);
  }
  // ---- the plaza round the Brain: a fountain; the Brain is the orb over it (24k pulses it) ----
  {
    const ring=new T.CylinderGeometry(.95,1.02,.2,40);ring.translate(0,top+.1,0);islAdd(bag,ring,null,SET.stone);
    const pool=new T.CylinderGeometry(.8,.8,.05,40);pool.translate(0,top+.19,0);islAdd(bag,pool,null,'#5fb6c4');
    const col=new T.CylinderGeometry(.11,.16,.55,16);col.translate(0,top+.45,0);islAdd(bag,col,null,islMix(SET.stone,'#ffffff',.3));
    const orb=new T.Mesh(new T.SphereGeometry(.3,32,20),new T.MeshStandardMaterial({color:'#e2d8ff',emissive:'#9b87ff',emissiveIntensity:2.2,roughness:.25}));
    orb.position.set(0,.98,0);orb.userData.keep=1;S.add(orb);
    const halo=new T.Sprite(new T.SpriteMaterial({map:of3Glow(),color:0xb6a6ff,transparent:true,blending:T.AdditiveBlending,depthWrite:false,opacity:.6}));
    halo.position.copy(orb.position);halo.scale.set(2.2,2.2,1);S.add(halo);
    const beam=new T.Mesh(new T.CylinderGeometry(.07,.16,2.6,24,1,true),new T.MeshBasicMaterial({map:of3Beam(),color:0xcfc3ff,transparent:true,
      blending:T.AdditiveBlending,depthWrite:false,side:T.DoubleSide,opacity:.4}));
    beam.position.set(0,2.2,0);S.add(beam);
    OF3.brain={orb,halo,beam};obst.push({x:0,z:0,r:1})
  }
  // ---- the setting's own parts: bridges, walls, a river's banks ----
  if(setName==='islands'){
    // a footbridge along every street from the plaza's islet to its room
    sh.rooms.forEach(q=>{const a=q.r.spoke,d=q.r.doorPt,ax=a.x/U,az=a.y/U,dx=d.x/U,dz=d.y/U,len=Math.hypot(dx-ax,dz-az),ang=Math.atan2(dx-ax,dz-az),mx=(ax+dx)/2,mz=(az+dz)/2;
      const m=islM(mx,top-.015,mz,ang);islBox(bag,.5,.05,len,0,0,0,'#b08257',m);
      for(let k=0;k<=Math.floor(len/.32);k++)[-1,1].forEach(s=>{const c=new T.CylinderGeometry(.02,.02,.18,6);c.translate(s*.24,.09,-len/2+k*.32);islAdd(bag,c,m,'#6b4a34')});
      [-1,1].forEach(s=>islBox(bag,.025,.025,len,s*.24,.17,0,'#7a5233',m))});
  }
  if(setName==='canals'){
    // stone bridges over the canal, between the districts
    const angs=sh.rooms.map(q=>Math.atan2(q.cz,q.cx)).sort((a,b)=>a-b);
    for(let i=0;i<angs.length;i++){const a=angs[i],bb=i+1<angs.length?angs[i+1]:angs[0]+Math.PI*2,mid=(a+bb)/2;
      let best=0,bd=1e9;for(let k=0;k<240;k++){const p=curve.getPointAt(k/240),dd=Math.abs(((Math.atan2(p.z,p.x)-mid+Math.PI*3)%(Math.PI*2))-Math.PI);if(dd<bd){bd=dd;best=k/240}}
      const p=curve.getPointAt(best),tg=curve.getTangentAt(best),m=new T.Matrix4().lookAt(new T.Vector3(),tg,up).setPosition(p.x,top-.02,p.z);
      for(let k=0;k<9;k++){const t2=-.62+k*.155,y=.2*Math.cos(t2/.7*Math.PI/2);
        const s=new T.BoxGeometry(1,.06,.17);s.rotateY(Math.PI/2);s.translate(t2,y,0);islAdd(bag,s,m,SET.stone);
        [-.24,.24].forEach(zz=>{const r2=new T.BoxGeometry(.17,.12,.04);r2.translate(t2,y+.09,zz);islAdd(bag,r2,m,'#e3dbcc')})}
      obst.push({x:p.x,z:p.z,r:.35})}
  }
  if(setName==='castle'){
    const M=sh.wallR.length,gate=Math.PI/4,wpt=i=>{const a=i/M*Math.PI*2,r=sh.wallR[i%M];return [Math.cos(a)*r,Math.sin(a)*r,a]};
    const nearGate=a=>Math.abs(((a-gate+Math.PI*3)%(Math.PI*2))-Math.PI)<.16;
    for(let i=0;i<M;i++){const p=wpt(i),q2=wpt(i+1),mid=(p[2]+q2[2])/2;if(nearGate(mid))continue;
      const len=Math.hypot(q2[0]-p[0],q2[1]-p[1])+.04,ang=Math.atan2(q2[0]-p[0],q2[1]-p[1]),mx=(p[0]+q2[0])/2,mz=(p[1]+q2[1])/2,m=islM(mx,top,mz,ang);
      islBox(bag,.24,.72,len,0,.36,0,'#b3ab9f',m,true);
      for(let k=0;k<Math.max(1,Math.floor(len/.2));k+=2)islBox(bag,.26,.12,.1,0,.78,-len/2+.1+k*.2,'#aaa296',m);
      ISL.fitPts.push([mx,1,mz]);obst.push({x:mx,z:mz,r:.25})}
    const tower=(x,z,big)=>{const r=big?.34:.28,h=big?1.25:1.05,t=new T.CylinderGeometry(r,r+.04,h,18);t.translate(x,top+h/2,z);islAdd(bag,t,null,'#aaa296',true);
      for(let k=0;k<8;k++){const a=k/8*Math.PI*2;islBoxAt(bag,.1,.12,.08,x+Math.cos(a)*r,top+h+.06,z+Math.sin(a)*r,-a,'#aaa296')}
      const c=new T.ConeGeometry(r+.06,.45,18);c.translate(x,top+h+.34,z);islAdd(bag,c,null,'#4a5160');obst.push({x,z,r:r+.1})};
    for(let k=0;k<8;k++){const i=Math.round(k*M/8),p=wpt(i);if(!nearGate(p[2]))tower(p[0],p[1],false)}
    // the gatehouse and its drawbridge across the moat
    const gw=islWallAt(sh,gate),ga=[gate-.17,gate+.17].map(a=>[Math.cos(a)*islWallAt(sh,a),Math.sin(a)*islWallAt(sh,a)]);
    ga.forEach(p=>tower(p[0],p[1],true));
    const gx=Math.cos(gate)*gw,gz=Math.sin(gate)*gw,gm=islM(gx,top,gz,-(gate+Math.PI/2));
    islBox(bag,Math.hypot(ga[0][0]-ga[1][0],ga[0][1]-ga[1][1]),.24,.3,0,.86,0,'#a39b90',gm);
    const bm=islM(Math.cos(gate)*(gw+.86),top-.05,Math.sin(gate)*(gw+.86),-gate);
    islBox(bag,1.1,.06,.5,0,0,0,'#8a6a4f',bm);
  }
  // ---- street lamps round the plaza and along each street; halos come on at dusk ----
  ISL.halos=[];
  {
    const at=[];for(let i=0;i<10;i++){const a=i/10*Math.PI*2+.31;at.push([Math.cos(a)*(sh.plaza-.1),Math.sin(a)*(sh.plaza-.1)])}
    sh.rooms.forEach(q=>{const l=Math.hypot(q.cx,q.cz)||1;[.55,.78].forEach(f=>at.push([q.cx*f+(-q.cz/l)*.5,q.cz*f+(q.cx/l)*.5]))});
    const lamps=at.filter(p=>height(p[0],p[1])>top-.02);
    const head=new T.InstancedMesh(new T.SphereGeometry(.06,12,8),new T.MeshBasicMaterial({color:'#fff1c9',toneMapped:false}),Math.max(1,lamps.length));
    lamps.forEach((p,i)=>{const pole=new T.CylinderGeometry(.018,.025,.62,8);pole.translate(p[0],top+.31,p[1]);islAdd(bag,pole,null,'#3a3f4a');
      head.setMatrixAt(i,new T.Matrix4().makeTranslation(p[0],top+.66,p[1]));
      const h=new T.Sprite(new T.SpriteMaterial({map:of3Glow(),color:0xffc777,transparent:true,blending:T.AdditiveBlending,depthWrite:false,opacity:0}));
      h.position.set(p[0],top+.66,p[1]);h.scale.set(.9,.9,1);S.add(h);ISL.halos.push(h)});
    head.count=lamps.length;head.userData.keep=1;S.add(head);ISL.heads=head;
  }
  // ---- trees, where nothing else is ----
  {
    const base=ISL_TREES[isl.trees]||ISL_TREES.some,n=setName==='forest'?base*6:setName==='castle'?Math.round(base*1.6):setName==='canals'?Math.round(base*.25):base;
    const tx0=setName==='forest'||setName==='castle'?gx0+1:x0,tx1=setName==='forest'||setName==='castle'?gx1-1:x1,
      tz0=setName==='forest'||setName==='castle'?gz0+1:z0,tz1=setName==='forest'||setName==='castle'?gz1-1:z1;
    for(let i=0,k=0;i<n*14&&k<n;i++){
      const x=tx0+rnd()*(tx1-tx0),z=tz0+rnd()*(tz1-tz0);
      if(dist(x,z)>-.3||height(x,z)<top-.01||onPath(x,z)||Math.hypot(x,z)<sh.hub)continue;
      if(sh.rooms.some(o=>Math.abs(x-o.cx)<o.hx+.35&&Math.abs(z-o.cz)<o.hz+.35))continue;
      if(spots.some(s=>Math.hypot(s.x-x,s.z-z)<.55)||!offRail(x,z,.35)||Math.hypot(x-sh.lh.x,z-sh.lh.z)<.75)continue;
      if(sh.wallR){const w=islWallAt(sh,Math.atan2(z,x)),r=Math.hypot(x,z);if(Math.abs(r-w)<.5)continue}
      // a forest thickens away from the town; a castle's meadow is open near the moat
      if(setName==='forest'&&rnd()>Math.min(1,.25+Math.max(0,Math.hypot(x,z)-sh.rmax+1)*.22))continue;
      const s=.45+rnd()*.4;islTree(bag,SET.tree,rnd,x,top,z,setName==='forest'?s*1.15:s);obst.push({x,z,r:.22});k++;
    }
  }
  // ---- the ground: a grid draped over the shape, coloured by where it is, shaded by what stands on it ----
  {
    const N=OF3.hq?170:115,W=gx1-gx0,D=gz1-gz0,g=new T.PlaneGeometry(W,D,N,Math.round(N*D/W));
    g.rotateX(-Math.PI/2);g.translate((gx0+gx1)/2,0,(gz0+gz1)/2);
    const p=g.attributes.position,c=new Float32Array(p.count*3),tmp=new T.Color();
    const C=h=>new T.Color(h),grass=C(SET.grass[0]),grass2=C(SET.grass[1]),stone=C(SET.path[0]),stone2=C(SET.path[1]),
      cliff=C(SET.cliff[0]),cliff2=C(SET.cliff[1]),sand=C(SET.sand),bed=C(SET.bed),flower=C('#f2e36b'),dirt=C('#6d5a3f');
    // contact shadows: everything that stands on the ground darkens it a little round its foot
    const B=1,grid={},keyOf=(i,j)=>i+','+j;
    obst.forEach(o=>{const r=o.rect?Math.max(o.rect.hx,o.rect.hz)+.8:o.r+.7,ox=o.rect?o.rect.cx:o.x,oz=o.rect?o.rect.cz:o.z;
      for(let i=Math.floor((ox-r)/B);i<=Math.floor((ox+r)/B);i++)for(let j=Math.floor((oz-r)/B);j<=Math.floor((oz+r)/B);j++)(grid[keyOf(i,j)]=grid[keyOf(i,j)]||[]).push(o)});
    const ao=(x,z)=>{let k=1;for(const o of grid[keyOf(Math.floor(x/B),Math.floor(z/B))]||[]){
      let dd;if(o.rect){const q=o.rect,ax=Math.abs(x-q.cx)-q.hx,az=Math.abs(z-q.cz)-q.hz;dd=Math.hypot(Math.max(ax,0),Math.max(az,0))}
      else dd=Math.max(0,Math.hypot(x-o.x,z-o.z)-o.r*.6);
      k*=1-.3*Math.exp(-dd*dd/.07)}return k};
    const far=setName==='forest'||setName==='castle';
    for(let i=0;i<p.count;i++){
      const x=p.getX(i),z=p.getZ(i),y=height(x,z);p.setY(i,y);
      const nn=islNoise(x*.8,z*.8),path=onPath(x,z);
      if(y>top-.02){
        tmp.copy(path?stone:grass).lerp(path?stone2:grass2,nn*.8);
        // paving reads as laid stones: a faint checker on streets, and everywhere in the canal city
        if(path||setName==='canals')tmp.multiplyScalar(((Math.floor(x*4.2)+Math.floor(z*4.2))&1)?.965:1.01);
        if(!path&&setName==='castle'&&Math.hypot(x,z)>(sh.wallR?islWallAt(sh,Math.atan2(z,x)):99)&&islNoise(x*6,z*6)>.82)tmp.lerp(flower,.35);
        if(!path&&setName==='forest')tmp.lerp(dirt,Math.max(0,islNoise(x*2.2,z*2.2)-.62)*1.2);
        if(far){const rr=Math.hypot(x,z)-sh.rmax;if(rr>0)tmp.multiplyScalar(Math.max(.62,1-rr*.035))}
        tmp.multiplyScalar(ao(x,z));
      }
      else if(y>-.05)tmp.copy(cliff2).lerp(cliff,(y+.05)/(top+.05)).lerp(C(setName==='canals'?'#9a5540':'#b88e66'),(islNoise(x*3,y*6)-.5)*.6+.2);
      else if(y>-.32)tmp.copy(sand);
      else tmp.copy(bed).lerp(sand,Math.max(0,(y+.8)/.5));
      c[i*3]=tmp.r;c[i*3+1]=tmp.g;c[i*3+2]=tmp.b;
    }
    g.setAttribute('color',new T.BufferAttribute(c,3));g.computeVertexNormals();
    const ng=g.toNonIndexed();g.dispose();
    bag.pos.push(ng.attributes.position.array);bag.nrm.push(ng.attributes.normal.array);bag.col.push(ng.attributes.color.array);
  }
  // ---- scenery afloat: boats at sea, gondolas moored on the canal (they rock with the water) ----
  ISL.boats=[];
  const floatMat=of3Mat('isl-land',{vertexColors:true,roughness:.8});
  if(setName==='canals'){
    for(let i=0;i<5;i++){const u=(i+.5)/5+.03,p=curve.getPointAt(u%1),tg=curve.getTangentAt(u%1),nx=-tg.z,nz=tg.x,l=Math.hypot(nx,nz)||1;
      const g=islGondola(floatMat,false);g.position.set(p.x+nx/l*.2,-.2,p.z+nz/l*.2);g.lookAt(g.position.x+tg.x,-.2,g.position.z+tg.z);g.userData.keep=1;S.add(g);ISL.boats.push(g)}
  }else if(setName==='island'||setName==='islands'){
    for(let i=0;i<(setName==='islands'?4:3);i++){
      const a=rnd()*Math.PI*2;let r=sh.hub+2;while(r<60&&dist(Math.cos(a)*r,Math.sin(a)*r)<.9)r+=.2;
      const g=new T.Group(),hull=islRound(.62,.16,.26,.06),mast=new T.CylinderGeometry(.015,.015,.6,6),sail=new T.ConeGeometry(.18,.42,3);
      mast.translate(0,.36,0);sail.translate(.08,.4,0);
      const bb=islBag();islAdd(bb,hull,null,['#f4efe6','#d9483b','#4f8fd0','#f4efe6'][i]);islAdd(bb,mast,null,'#6b4a34');islAdd(bb,sail,null,'#fffaf0');
      g.add(islMesh(bb,floatMat));
      g.position.set(Math.cos(a)*(r+1.1),-.2,Math.sin(a)*(r+1.1));g.rotation.y=-a;g.userData.keep=1;S.add(g);ISL.boats.push(g);
    }
  }
  // ---- one mesh for all of it ----
  const land=islMesh(bag,of3Mat('isl-land',{vertexColors:true,roughness:.82}));
  land.userData.keep=1;if(OF3.hq){land.castShadow=true;land.receiveShadow=true}
  S.add(land);
  // the windows: a white frame and a pane, two instanced meshes
  if(panes.length){
    const fg=islRound(.18,.24,.016,.008),pg=islRound(.12,.17,.03,.008);
    const frames=new T.InstancedMesh(fg,of3Mat('isl-frame',{color:'#f6f1e8',roughness:.6}),panes.length);
    const glass=new T.InstancedMesh(pg,new T.MeshBasicMaterial({color:'#ffffff',toneMapped:false}),panes.length);
    panes.forEach((pp,i)=>{frames.setMatrixAt(i,pp.m.clone().multiply(new T.Matrix4().makeTranslation(0,0,-.006)));glass.setMatrixAt(i,pp.m);glass.setColorAt(i,new T.Color('#33435a'))});
    frames.userData.keep=1;glass.userData.keep=1;S.add(frames);S.add(glass);
    ISL.windows=glass;ISL.panes=panes;
  }
  // ---- the carrier, waiting at your agent's stop ----
  if(ISL.curve){
    const mat=of3Mat('isl-land',{vertexColors:true,roughness:.6}),mk=parts=>{const bb=islBag();parts.forEach(q=>islAdd(bb,q[0],null,q[1]));const m=islMesh(bb,mat);m.userData.keep=1;S.add(m);return m};
    if(SET.carrier==='train'){
      const boiler=new T.CylinderGeometry(.13,.13,.42,18);boiler.rotateX(Math.PI/2);boiler.translate(0,.22,.06);
      const cab=islRound(.3,.26,.2,.025);cab.translate(0,.24,-.21);
      const chim=new T.CylinderGeometry(.04,.055,.16,10);chim.translate(0,.4,.19);
      const base=islRound(.31,.06,.66,.015);base.translate(0,.08,0);
      ISL.cars=[mk([[boiler,'#2f3d52'],[cab,'#d9483b'],[chim,'#222831'],[base,'#1f242c']])];
      ['#e7a83d','#4f8fd0'].forEach(c=>{const bd=islRound(.29,.23,.46,.03);bd.translate(0,.21,0);const b2=islRound(.31,.06,.5,.015);b2.translate(0,.08,0);
        ISL.cars.push(mk([[bd,c],[b2,'#1f242c']]))});
    }else if(SET.carrier==='gondola'){
      const g=islGondola(mat,true);g.userData.keep=1;S.add(g);ISL.cars=[g];
    }else{
      const hull=islRound(.36,.16,.86,.06);hull.translate(0,.08,0);
      const cabin=islRound(.28,.2,.4,.04);cabin.translate(0,.26,-.06);
      const roof=islRound(.32,.04,.46,.015);roof.translate(0,.38,-.06);
      ISL.cars=[mk([[hull,'#f4f1ea'],[cabin,'#2f6fb0'],[roof,'#f4f1ea']])];
    }
    ISL.train={u:ISL.home,speed:0};
    islCars();
  }
  // ---- the water: one plane that knows where the land is (its distance, as a small texture) ----
  {
    const N=160,W=gx1-gx0+8,D=gz1-gz0+8,cx=(gx0+gx1)/2,cz=(gz0+gz1)/2,data=new Uint8Array(N*N*4);
    for(let j=0;j<N;j++)for(let i=0;i<N;i++){const x=cx+(i/(N-1)-.5)*W,z=cz+(j/(N-1)-.5)*D;
      data[(j*N+i)*4]=Math.max(0,Math.min(255,Math.round(128-dist(x,z)*28)));data[(j*N+i)*4+3]=255}
    const tex=new T.DataTexture(data,N,N);tex.magFilter=tex.minFilter=T.LinearFilter;tex.needsUpdate=true;ISL.tex=tex;
    const u={uField:{value:tex},uBox:{value:new T.Vector4(cx,cz,W,D)},uTime:{value:0},uDeep:{value:new T.Color(SET.deep)},
      uShallow:{value:new T.Color(SET.shallow)},uSky:{value:new T.Color('#cfe6fb')},uSun:{value:new T.Vector3(.4,.8,.3)},uSunCol:{value:new T.Color('#fff2d6')},uNight:{value:0},uFoam:{value:SET.foam}};
    const mat=new T.ShaderMaterial({uniforms:u,
      vertexShader:'varying vec3 vW;void main(){vec4 w=modelMatrix*vec4(position,1.0);vW=w.xyz;gl_Position=projectionMatrix*viewMatrix*w;}',
      fragmentShader:`uniform sampler2D uField;uniform vec4 uBox;uniform float uTime,uNight,uFoam;uniform vec3 uDeep,uShallow,uSky,uSun,uSunCol;varying vec3 vW;
        float h(vec2 p){return fract(sin(dot(p,vec2(12.9898,78.233)))*43758.5453);}
        float n(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.0-2.0*f);return mix(mix(h(i),h(i+vec2(1,0)),f.x),mix(h(i+vec2(0,1)),h(i+vec2(1,1)),f.x),f.y);}
        void main(){
          vec2 uv=(vW.xz-uBox.xy)/uBox.zw+0.5;
          float inside=step(0.0,uv.x)*step(uv.x,1.0)*step(0.0,uv.y)*step(uv.y,1.0);
          float d=mix(4.6,(128.0-texture2D(uField,uv).r*255.0)/28.0,inside);
          float shore=1.0-smoothstep(0.0,2.2,d);
          vec2 q=vW.xz*1.1;
          float w1=n(q+vec2(uTime*.25,uTime*.18)),w2=n(q*2.3-vec2(uTime*.3,-uTime*.2)),w3=n(q*5.1+vec2(uTime*.5,uTime*.35));
          vec3 nrm=normalize(vec3((w1-.5)*.35+(w2-.5)*.18+(w3-.5)*.08,1.0,(w2-.5)*.35+(w3-.5)*.08));
          vec3 V=normalize(cameraPosition-vW);
          float fres=pow(1.0-max(dot(V,nrm),0.0),3.0);
          vec3 c=mix(uDeep,uShallow,shore);
          c=mix(c,uSky,fres*.5);
          float glint=pow(max(dot(reflect(-normalize(uSun),nrm),V),0.0),110.0);
          c+=uSunCol*glint*(1.0-uNight)*1.3;
          float foam=smoothstep(.55,.2,d)*(1.0-smoothstep(.2,.05,d));
          foam*=.6+.4*sin(uTime*1.6+d*28.0);
          c=mix(c,vec3(1.0),foam*uFoam);
          gl_FragColor=vec4(c,1.0);
          #include <colorspace_fragment>
        }`});
    const sea=new T.Mesh(new T.PlaneGeometry(400,400),mat);sea.rotation.x=-Math.PI/2;sea.position.y=-.22;sea.userData.keep=1;S.add(sea);
    ISL.water=u;
  }
  // ---- light: a sky, a sun and the bounce from the ground, all set by the hour (islLight) ----
  const hemi=new T.HemisphereLight(0xdff1ff,setName==='forest'?0x56603e:0x8a7a62,1.0),sun=new T.DirectionalLight(0xfff2d6,2.2);
  const span=(L.R+300)/U+(setName==='castle'?1.5:0);
  if(OF3.hq){sun.castShadow=true;const c=sun.shadow.camera;c.left=c.bottom=-span*1.5;c.right=c.top=span*1.5;c.near=.5;c.far=span*5;
    sun.shadow.mapSize.set(2048,2048);sun.shadow.bias=-.0005;sun.shadow.normalBias=.02}
  S.add(hemi);S.add(sun);S.add(sun.target);
  ISL.lights={hemi,sun,span};
  islLight();
  islControls();
}
/* A gondola: long, black, curled at both ends; the one that carries work has its gondolier. */
function islGondola(mat,crew){
  const T=OF3.T,g=new T.Group(),bb=islBag();
  const hull=islRound(.16,.08,.92,.04);hull.translate(0,.04,0);islAdd(bb,hull,null,'#1c1f26');
  [.5,-.5].forEach(z=>{const tip=new T.BoxGeometry(.05,.18,.06);tip.rotateX(z>0?-.6:.6);tip.translate(0,.12,z);islAdd(bb,tip,null,'#1c1f26')});
  const seat=islRound(.13,.05,.22,.02);seat.translate(0,.1,.08);islAdd(bb,seat,null,'#a8332e');
  if(crew){const body=new T.BoxGeometry(.08,.18,.06);body.translate(0,.2,-.3);islAdd(bb,body,null,'#f4f1ea');
    [.15,.22].forEach(y=>islBox(bb,.085,.02,.065,0,y,-.3,'#1f3a6b'));
    const head=new T.SphereGeometry(.04,10,8);head.translate(0,.33,-.3);islAdd(bb,head,null,'#e8b98f');
    const hat=new T.CylinderGeometry(.05,.05,.015,10);hat.translate(0,.37,-.3);islAdd(bb,hat,null,'#e8c35a');
    const oar=new T.CylinderGeometry(.008,.008,.6,4);oar.rotateX(.5);oar.translate(.05,.18,-.42);islAdd(bb,oar,null,'#6b4a34')}
  g.add(islMesh(bb,mat));return g;
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
  const h=islHour(),SET=ISL_SETS[ISL.set]||ISL_SETS.island;
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
    u.uDeep.value.set(SET.deep).lerp(new T.Color(SET.nDeep),night);u.uShallow.value.set(SET.shallow).lerp(new T.Color(SET.nShallow),night)}
  if(ISL.lamp)ISL.lamp.material.emissiveIntensity=.3+night*3;
  if(ISL.shellPane)ISL.shellPane.emissiveIntensity=Math.max(0,night-.15)*1.4;
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
  const dark=new T.Color(ISL.set==='islands'?'#2a4f7a':'#2d3b50'),warm=new T.Color('#ffb84d'),lit=new T.Color('#ffe9a8'),c=new T.Color();
  ISL.panes.forEach((p,i)=>{const on=p.room&&busy[p.room.kind+':'+p.room.name];
    c.copy(on?lit:dark.clone().lerp(warm,(ISL.night||0)*(.5+.5*islHash(i,3))));g.setColorAt(i,c)});
  if(g.instanceColor)g.instanceColor.needsUpdate=true;OF3.dirty=true;
}
/* ---------------- every frame ---------------- */
function islTick(now){
  if(!OF3.island)return;
  const dt=Math.min(.25,(now-(ISL.last||now))/1000);ISL.last=now;
  if(ISL.water)ISL.water.uTime.value=now/1000;
  (ISL.boats||[]).forEach((b,i)=>{b.position.y=-.2+Math.sin(now/900+i*2)*.02;b.rotation.z=Math.sin(now/1100+i)*.04});
  if(ISL.spin)ISL.spin.rotation.z=now/1600;
  // the hour: the real one moves on, a quarter of an hour at a time
  if(Math.floor(islHour()*4)!==ISL.hourShown)islLight();
  islWindows();
  islShells(now,dt);
  islPapers();
  islTrain(dt);
}
/* A paper flying from one room to another is work handed over: the carrier takes it there. */
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
  // no trip takes longer than the Office's longest walk: the carrier shows work moving now
  const want=Math.max(.05,left/(typeof OF_WALK_S!=='undefined'?OF_WALK_S:3.2)*1.3);
  if(tr.dir!==dir){tr.dir=dir;tr.speed=0}
  tr.speed=Math.min(want,tr.speed+dt*.6);
  tr.u=((tr.u+dir*Math.min(left,tr.speed*dt*(left<.03?Math.max(.3,left/.03):1)))%1+1)%1;
  islCars();
}
function islCars(){
  const tr=ISL.train;if(!tr)return;
  const afloat=ISL.carrier!=='train';
  ISL.cars.forEach((car,i)=>{
    const u=((tr.u-(tr.dir||1)*i*.39/Math.max(1,ISL.len))%1+1)%1,p=ISL.curve.getPointAt(u),tg=ISL.curve.getTangentAt(u).multiplyScalar(tr.dir||1);
    car.position.set(p.x,afloat?-.2:ISL.top+.05,p.z);car.lookAt(p.x+tg.x,car.position.y,p.z+tg.z)});
  OF3.dirty=true;
}
function islMoving(){const tr=ISL.train;return !!(OF3.island&&((tr&&(tr.to!==undefined||ISL.queue.length))||islShellsMoving()))}
/* ---------------- the time of day, as an input ---------------- */
function islControls(){
  if(!OF3.ui||OF3.ui.querySelector('.isl-time'))return islControlsPaint();
  const t=document.createElement('div');t.className='isl-time';t.setAttribute('role','group');t.setAttribute('aria-label','Time of day in the town');
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
/* Is the 3D office drawn as a town? The Town scene always is; a window when its look is. */
function islWanted(){
  const v=OFFICE.view;if(!v||v.zero)return false;
  if(typeof of3HQ==='function'&&of3HQ())return !!(typeof OFFICE_SCENE!=='undefined'&&OFFICE_SCENE.island);
  if(OFFICE.w&&OFFICE.w.scene)return false;
  return ((v.office||{}).look||'3d')==='island';
}
/* ---------------- the town builder, in the Office's Design panel ----------------
   The setting, houses per district, the carrier, the trees: the same closed set as
   `bento office setting|island` and the agent's set_office (office.py clean_island).
   Saved through officeSave like every other field of the plan, so it is the person's
   change and a ledger row. Describing it in words ("a city on canals") is the panel's
   Describe it, which asks the brain for the same fields. */
function islDesignHTML(v){
  const isl=(v.office&&v.office.island)||{},max=v.max_houses||12,cur=islSetName(isl),sets=v.settings||{};
  const rows=v.rooms.filter(r=>r.kind==='dept').map(r=>{const n=officeHouses(isl,r);
    return `<div class="of-row isl-row"><span class="isl-dn">${esc(r.name)}</span>
      <button class="endbtn isl-hb" data-ih="${esc(r.name)}" data-d="-1" aria-label="One house fewer in ${esc(r.name)}"${n<=0?' disabled':''}>−</button>
      <b class="isl-n" aria-label="${n} houses">${n}</b>
      <button class="endbtn isl-hb" data-ih="${esc(r.name)}" data-d="1" aria-label="One more house in ${esc(r.name)}"${n>=max?' disabled':''}>+</button></div>`}).join('');
  const train=isl.train!==false,trees=isl.trees||'some',carrier=(ISL_SETS[cur]||ISL_SETS.island).carrier==='train'?'Railway':'Boats';
  return `<div class="of-sec">Setting</div>
    <div class="of-chips isl-sets">${Object.keys(ISL_SETS).map(k=>`<button class="of-chip${cur===k?' on':''}" data-iset="${k}" aria-pressed="${cur===k}" title="${esc(sets[k]||'')}">${esc(ISL_SETS[k].label)}</button>`).join('')}</div>
    <div class="of-sec">Districts</div>
    ${rows||'<div class="mut of-row">No departments yet. Each one you add grows a district here.</div>'}
    <div class="of-chips"><button class="of-chip${train?' on':''}" data-itrain="1" aria-pressed="${train}">${carrier} ${train?'on':'off'}</button>
      ${(v.trees||['few','some','lots']).map(t=>`<button class="of-chip${trees===t?' on':''}" data-itrees="${t}" aria-pressed="${trees===t}">${t} trees</button>`).join('')}</div>
    <div class="mut of-row">Houses are scenery. Who works where is still the departments' people.</div>`;
}
function islDesignWire(el,v){
  const isl=JSON.parse(JSON.stringify((v.office&&v.office.island)||{houses:{},train:true,trees:'some'}));
  isl.houses=isl.houses||{};
  const save=()=>officeSave({island:isl});
  el.querySelectorAll('[data-ih]').forEach(b=>b.onclick=()=>{const name=b.dataset.ih,r=v.rooms.find(x=>x.kind==='dept'&&x.name===name);if(!r)return;
    isl.houses[name]=Math.max(0,Math.min(v.max_houses||12,officeHouses(isl,r)+(+b.dataset.d)));save()});
  el.querySelectorAll('[data-iset]').forEach(b=>b.onclick=()=>{isl.setting=b.dataset.iset;save()});
  const tr=el.querySelector('[data-itrain]');if(tr)tr.onclick=()=>{isl.train=isl.train===false;save()};
  el.querySelectorAll('[data-itrees]').forEach(b=>b.onclick=()=>{isl.trees=b.dataset.itrees;save()});
}
