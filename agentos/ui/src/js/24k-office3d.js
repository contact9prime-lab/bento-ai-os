/* ================= The Office in 3D: rooms around the Brain =================
   Asked for with a screenshot of an isometric "agent HQ" (rooms like dioramas round a
   glowing core) and one worry: "when I add so many agents it becomes really cluttered".
   This file is the drawing and nothing else. Who sits where, every walk, every paper,
   every balloon is decided by 24d-office.js exactly as for the flat comic office; the
   plan is laid out round a hub instead of in rows, and this file draws that plan in 3D.

   Clutter is answered by rules, not by shrinking people:

   - **A room seats OF3_SEATS people, and the rest are on its card.** A department of
     nine is four desks and a card that says "9 agents · 3 running" with their faces.
     Who has a desk is decided by what is happening: the head first, then whoever is
     working or waiting for you, then whoever worked last. Somebody without a desk who
     gets work walks in from the door and sits down (of3Need); an idle colleague gives
     the desk up. So the picture shows the work, and the card shows the headcount.
   - **Names are on the cards and in a room's own view, not over every head.** The
     overview tags only people on the move (they are the news). Tap a room or its card
     and the camera goes there, every seat is named, and the side list has the whole
     department, desk or not.
   - **Rooms are one size and stand on one ring**, which grows with the number of rooms
     (ten departments at most, office.py), and the camera fits the ring to the window.

   The rules the flat office lives by hold here too: nothing moves that did not happen
   (the Brain pulses when a memory tool really ran, a spark runs to it along the path);
   every face is the server's character sheet through avatarSrc / avatarRecipeSrc, so
   there is no second painter (tests/test_avatars.py); a screen with no 3D graphics
   gets the flat office and one sentence saying why (OF3.why, shown in Design).

   Cost: three.js is the World's vendored copy, loaded only when this look is on. Static
   furniture is baked (wlBake), so a ten-room office is a few dozen draw calls; people
   are sprites; text is HTML over the canvas. Frames come from the Office's own loop
   (30 a second while something moves, 6 at rest, none asleep). Software rendering and
   phones get no shadows and pixel ratio 1 (worldQuality).

   Faces — GUI: the Office window and the desktop scene. SUI: the same page. TUI: `bento
   office look 3d|flat` sets it; a terminal shows the plan (`bento office`), not a picture.
   `var`, not `let`: the bundle is one script. */
var OF3={T:null,r:null,scene:null,cam:null,cv:null,ui:null,failed:false,why:'',gl:undefined,building:false,
  sig:'',rooms:[],screens:[],sp:{},el:{},view:null,target:null,fit:null,anim:null,focus:null,
  sparks:[],pulse:0,brain:null,papers:[],pet:null,ball:null,hq:false,cw:0,ch:0,dirty:true,drag:null,cardSig:''};
var OF3_SEATS=4;                 // desks in a room; a bigger department is on its card
var OF3_U=100;                   // plan units (the flat office's) per world unit
var OF3_ROOM={w:330,h:280};      // every room is one size, so the ring stays a ring
var OF3_RING=230;                // the walkway round the Brain, in plan units
var OF3_TALL=1.32;               // how much longer the ring is along the screen's up
var OF3_WALL=.95, OF3_SLAB=.18;  // wall height and floor thickness, in world units
var OF3_DIR=[1,1.12,1];          // the isometric view: from the front-right, looking down
var OF3_SPARK=/remember|recall|memor|knowledge|kg_|forget/i;

/* ---------------- may we? ---------------- */
function of3Wanted(){
  const v=OFFICE.view;if(!v||OF3.failed)return false;
  if(of3HQ())return of3GL();        // the Office HQ scene is this look by definition
  if(((v.office||{}).look||'3d')!=='3d')return false;
  return of3GL();
}
function of3GL(){
  if(OF3.gl===undefined){
    try{const c=document.createElement('canvas'),gl=c.getContext('webgl2')||c.getContext('webgl');OF3.gl=!!gl;
      // a probe holds a context until it is collected, and a page gets only a handful
      const x=gl&&gl.getExtension('WEBGL_lose_context');if(x)x.loseContext()}catch(e){OF3.gl=false}
    if(!OF3.gl)OF3.why='This screen has no 3D graphics, so the office is drawn flat.';
  }
  return OF3.gl;
}
/* Office HQ: the desktop scene, full screen, always 3D, its cards tappable. */
function of3HQ(){return !!(OFFICE.w&&OFFICE.w.scene&&typeof OFFICE_SCENE!=='undefined'&&OFFICE_SCENE.hq)}
/* The flat office is drawing: put the 3D one away, keeping three.js loaded. */
function of3Off(){
  if(OF3.r||OF3.cv)of3Dispose();
  if(OFFICE.cv){OFFICE.cv.style.display='';OFFICE.cv.parentElement&&OFFICE.cv.parentElement.classList.remove('of3')}
}

/* ---------------- the plan: rooms on a ring round the Brain ---------------- */
function of3Layout(){
  const O=OFFICE,v=O.view,sc=O.cv.parentElement;
  O.cv.style.display='none';sc.classList.add('of3');
  const rooms=v.rooms,n=Math.max(1,rooms.length);
  // who had which desk survives a reload of the plan (a face changed, a window resized)
  const had={};((O.L&&O.L.radial&&O.L.rooms)||[]).forEach(r=>{if(r.seats)had[r.kind+':'+r.name]=r.seats});
  // far enough apart that two neighbours never touch, whatever the count
  const R=Math.max(n<=2?400:520,520/(2*Math.sin(Math.PI/Math.max(3,n))));
  // The ring takes the shape of the window: a wide one spreads it sideways rather than
  // leaving dark margins, a phone held upright stands it up, and the desktop scene's
  // short band (one-line cards) lets it flatten. Rooms stay as big as the window allows.
  const asp=sc.clientWidth/Math.max(1,sc.clientHeight);
  const wide=Math.max(1,Math.min(2.4,asp/1.1));
  const tall=OF3_TALL*Math.max(1,Math.min(2,1.1/asp))/(asp>2.2?1.25:1);
  const laid=rooms.map((r,i)=>{
    const w=r.kind==='lead'?360:OF3_ROOM.w,h=OF3_ROOM.h;
    // yours first, at the top of the screen (the camera looks from +x,+z), then clockwise.
    // Seen from above at an angle a circle is squashed top to bottom, which stacked the
    // side rooms so close that each card covered the room behind; so the ring is longer
    // along the screen's up direction (OF3_TALL), and reads as round on screen.
    const a=-3*Math.PI/4+i*2*Math.PI/n,u=Math.cos(a+3*Math.PI/4)*tall,s2=Math.sin(a+3*Math.PI/4)*wide;
    const cx=R*(-u*.7071+s2*.7071),cy=R*(-u*.7071-s2*.7071),cl=Math.hypot(cx,cy)||1;
    const dx=-cx/cl,dy=-cy/cl,t=Math.min(w/2/Math.max(1e-6,Math.abs(dx)),h/2/Math.max(1e-6,Math.abs(dy)));
    const doorPt={x:cx+dx*t,y:cy+dy*t};
    return {...r,x:cx-w/2,y:cy-h/2,w,h,cx,cy,ang:a,row:0,grow:0,per:OF3_SEATS,seats:had[r.kind+':'+r.name],
      door:doorPt.x,doorPt,inside:{x:cx+dx*(t-46),y:cy+dy*(t-46)},spoke:{x:-dx*OF3_RING,y:-dy*OF3_RING}};
  });
  const xs=laid.flatMap(r=>[r.x,r.x+r.w]),ys=laid.flatMap(r=>[r.y,r.y+r.h]);
  O.L={radial:true,R,rooms:laid,rowsY:[],spineX:0,W:Math.max(...xs)-Math.min(...xs),H:Math.max(...ys)-Math.min(...ys)};
  O.cw=Math.max(280,sc.clientWidth);O.ch=Math.max(200,sc.clientHeight);O.s=1;
  of3Seat();
  officeEmpty();
  companyCards();
  officeLine();
  OF3.dirty=true;
  if(OF3.r){of3Size();of3Build()}else of3Ensure();
  if(officeAwake())officeDraw();
  officeKick();
}

/* ---------------- seats: who has a desk, and who is on the card ---------------- */
function of3SeatPos(r,k,n){
  const P=n<=1?[[.5,.48]]:n===2?[[.3,.5],[.7,.5]]:[[.3,.36],[.7,.36],[.3,.72],[.7,.72]];
  const q=P[k]||P[0];return {x:r.x+r.w*q[0],y:r.y+r.h*q[1]};
}
function of3Seat(){
  const O=OFFICE,keep=O.people,seen={};
  O.L.rooms.forEach(r=>{
    if(r.kind==='lead'){
      seen['@agent']=officePerson(keep['@agent'],'@agent',(typeof agentName==='function'?agentName():'Aria'),r,r.x+r.w*.5,r.y+r.h*.46,true);
      seen['@agent'].bench=false;
    }
    if(r.kind!=='dept'&&r.kind!=='floor')return;
    r.members.forEach(m=>{
      const p=keep[m];
      // a person keeps the desk they had; everybody else waits at the door, unseen
      const home=p&&!p.bench&&p.room&&p.room.name===r.name&&p.room.kind===r.kind?p.home:r.inside;
      seen[m]=officePerson(p,m,m,r,home.x,home.y,false);
      seen[m].head=r.lead===m;seen[m].title=(r.titles||{})[m]||'';
      if(!p)seen[m].bench=true;
    });
  });
  O.people=seen;
  O.L.rooms.forEach(r=>{if(r.kind==='dept'||r.kind==='floor')of3Reseat(r,null,true)});
  if(!O.pet||O.pet.kind!==O.view.office.pet)O.pet=O.view.office.pet!=='none'?officePetNew():null;
  officeExtrasPlace();
}
/* Hand out the desks. `need` is somebody who must have one now (work arrived for them).
   Seats are stable: nobody moves unless somebody needs the desk more, and the one who
   gives it up is the one who worked longest ago. */
function of3Reseat(r,need,first){
  const O=OFFICE,ms=r.members.filter(m=>O.people[m]);if(!ms.length)return;
  const n=Math.min(OF3_SEATS,ms.length);
  r.seats=(r.seats||[]).filter(k=>ms.includes(k)).slice(0,n);
  const pri=m=>{const p=O.people[m];return (r.lead===m?8e12:0)+(p.hand?6e12:0)+(p.busy?4e12+p.busy:0)+(p.worked||0)};
  const want=ms.filter(m=>m===need||r.lead===m||O.people[m].busy||O.people[m].hand).sort((a,b)=>pri(b)-pri(a));
  want.forEach(m=>{
    if(r.seats.includes(m))return;
    if(r.seats.length<n){r.seats.push(m);return}
    // the desk of whoever needs it least, and only if they are idle: somebody working
    // keeps their desk (the card counts the rest), or a busy department would be a
    // stream of people walking in and out, which is the erratic office nobody wants
    let low=-1,lp=Infinity;r.seats.forEach((k,i)=>{if(k===need)return;const q=pri(k);if(q<lp){lp=q;low=i}});
    if(low>=0&&lp<4e12&&lp<pri(m))r.seats[low]=m;
  });
  // empty desks go to the rest, in the order the department lists them
  ms.forEach(m=>{if(r.seats.length<n&&!r.seats.includes(m))r.seats.push(m)});
  ms.forEach(m=>{
    const p=O.people[m],k=r.seats.indexOf(m);
    if(k>=0){
      const at=of3SeatPos(r,k,n),was=p.bench;p.bench=false;
      const moved=p.home.x!==at.x||p.home.y!==at.y;p.home=at;
      if(was&&!first&&!O.static&&p.mode==='seat'){
        // they come in from the door and sit down: work arrived, so they show up for it
        p.x=r.inside.x;p.y=r.inside.y;p.mode='stand';officeWalk(p,at,'seat');
      }else if(p.mode==='seat'&&moved){p.x=at.x;p.y=at.y}
    }else{
      p.bench=true;p.home=r.inside;
      if(p.mode==='seat'){p.x=r.inside.x;p.y=r.inside.y}
    }
  });
  OF3.cardSig='';
}
/* Work, a word or a question for somebody without a desk: give them one first. */
function of3Need(p){
  if(!p||!p.bench||!OFFICE.L||!OFFICE.L.radial||!p.room)return;
  p.worked=performance.now();of3Reseat(p.room,p.key);
}
function of3Shown(p){return !p.bench||p.mode==='walk'||!!p.visit}

/* ---------------- walking: out of the door, round the ring, in at the other ---------------- */
function of3Route(p,to){
  const from=p.mode!=='seat'?{x:p.x,y:p.y}:p.bench?{x:p.home.x,y:p.home.y}:{x:p.home.x,y:p.home.y+50};
  const ra=officeRoomAt(from),rb=officeRoomAt(to),pts=[];
  if(p.mode==='seat'&&!p.bench)pts.push({x:p.home.x+40,y:p.home.y+56});
  if(ra!==rb){
    let a0;
    if(ra){pts.push(ra.inside,ra.doorPt,ra.spoke);a0=Math.atan2(ra.spoke.y,ra.spoke.x)}
    else a0=Math.atan2(from.y,from.x);
    if(rb){
      const a1=Math.atan2(rb.spoke.y,rb.spoke.x);
      let d=a1-a0;while(d>Math.PI)d-=2*Math.PI;while(d<-Math.PI)d+=2*Math.PI;
      const steps=Math.ceil(Math.abs(d)/.35);
      for(let i=1;i<steps;i++){const a=a0+d*i/steps;pts.push({x:Math.cos(a)*OF3_RING,y:Math.sin(a)*OF3_RING})}
      pts.push(rb.spoke,rb.doorPt,rb.inside);
    }
  }
  pts.push(to);
  return pts;
}

/* ---------------- the renderer ---------------- */
async function of3Ensure(){
  if(OF3.r||OF3.building||OF3.failed)return;
  const host=OFFICE.cv&&OFFICE.cv.parentElement;if(!host)return;
  OF3.building=true;
  try{
    const T=OF3.T=OF3.T||(typeof WORLD!=='undefined'&&WORLD.T)||await import('/assets/three.module.min.js');
    if(typeof WORLD!=='undefined'&&!WORLD.T)WORLD.T=T;
    // the window may have closed, or the look changed, while three.js was loading
    if(!OFFICE.L||!OFFICE.L.radial||!OFFICE.cv||OFFICE.cv.parentElement!==host)return;
    const cv=document.createElement('canvas');cv.className='of-cv3';cv.setAttribute('aria-hidden','true');
    host.insertBefore(cv,host.firstChild);OF3.cv=cv;
    // The words go over the picture. In Office HQ the picture is the wall, under the
    // desktop, so its cards and the room list live in the desktop (as the World's tags
    // do) to be tapped; everywhere else they sit on the canvas.
    const ui=document.createElement('div');ui.className='of3-ui';OF3.ui=ui;
    const desk=document.getElementById('desktop'),home=document.getElementById('home');
    if(of3HQ()&&desk){ui.classList.add('hq');desk.insertBefore(ui,home?home.nextSibling:null)}else host.appendChild(ui);
    OF3.r=new T.WebGLRenderer({canvas:cv,antialias:true,powerPreference:'low-power'});
    OF3.r.outputColorSpace=T.SRGBColorSpace;OF3.r.toneMapping=T.ACESFilmicToneMapping;OF3.r.toneMappingExposure=1.05;
    // the kiosk is a small machine's own screen (a Pi): no shadows there either
    OF3.hq=!document.body.classList.contains('kiosk')&&typeof worldQuality==='function'?worldQuality(OF3.r):false;
    if(OF3.hq){OF3.r.shadowMap.enabled=true;OF3.r.shadowMap.type=T.PCFSoftShadowMap}
    of3Input(cv);
    of3Size();of3Build();
  }catch(e){
    console.warn('office 3d',e);
    OF3.failed=true;OF3.why='This screen could not start 3D graphics, so the office is drawn flat.';
    of3Dispose();officeLog(OF3.why);
    if(OFFICE.w)officeLayout();
  }finally{OF3.building=false}
  officeKick();
}
function of3Size(){
  if(!OF3.r)return;
  const O=OFFICE,cw=O.cw,ch=O.ch;
  OF3.r.setPixelRatio(Math.min(devicePixelRatio||1,OF3.hq?1.5:1));
  OF3.r.setSize(cw,ch,false);OF3.cv.style.width=cw+'px';OF3.cv.style.height=ch+'px';
  OF3.cw=cw;OF3.ch=ch;OF3.dirty=true;
  // where the canvas is, seen from the layer the words are placed in
  const a=OF3.cv.getBoundingClientRect(),b=OF3.ui?OF3.ui.getBoundingClientRect():a;
  OF3.off={x:a.left-b.left,y:a.top-b.top};
}
function of3Dispose(){
  const T=OF3.T;
  if(OF3.scene)OF3.scene.traverse(o=>{if(o.geometry)o.geometry.dispose();
    const m=o.material;if(m)(Array.isArray(m)?m:[m]).forEach(x=>{if(x.map)x.map.dispose();x.dispose()})});
  if(OF3.r){try{OF3.r.dispose();OF3.r.forceContextLoss()}catch(e){}}
  if(OF3.cv)OF3.cv.remove();if(OF3.ui)OF3.ui.remove();
  clearTimeout(OF3.rebuild);
  Object.assign(OF3,{r:null,scene:null,cam:null,cv:null,ui:null,sig:'',names:'',rooms:[],screens:[],sp:{},el:{},
    view:null,target:null,fit:null,anim:null,focus:null,sparks:[],brain:null,papers:[],pet:null,ball:null,cardSig:''});
  if(T)OF3.T=T;
}
/* Plan (x, y) to the floor of the world: x stays x, the plan's y is the world's z. */
function of3W(x,y,h){return new OF3.T.Vector3(x/OF3_U,h||0,y/OF3_U)}

/* ---------------- building the place ---------------- */
var OF3_MAT={};
function of3Mat(key,o){const T=OF3.T;return OF3_MAT[key]||(OF3_MAT[key]=new T.MeshStandardMaterial(Object.assign({roughness:.82,metalness:0},o)))}
function of3Box(par,w,h,d,mat,x,y,z,shadow){
  const m=new OF3.T.Mesh(new OF3.T.BoxGeometry(w,h,d),mat);m.position.set(x,y,z);
  if(OF3.hq&&shadow!==false){m.castShadow=true;m.receiveShadow=true}
  par.add(m);return m;
}
function of3Cyl(par,rt,rb,h,mat,x,y,z,seg){
  const m=new OF3.T.Mesh(new OF3.T.CylinderGeometry(rt,rb,h,seg||18),mat);m.position.set(x,y,z);
  if(OF3.hq){m.castShadow=true;m.receiveShadow=true}par.add(m);return m;
}
function of3Hex(h,k){return new OF3.T.Color(h).lerp(new OF3.T.Color(k[0]),k[1])}
function of3Build(){
  const O=OFFICE,T=OF3.T,L=O.L,v=O.view;if(!T||!OF3.r||!L)return;
  // a new set of rooms (a department added, a colour changed) is drawn at once; only a
  // move of the same rooms waits for the window to settle
  const names=JSON.stringify(L.rooms.map(r=>[r.kind,r.name,r.color,Math.min(OF3_SEATS,r.members.length)]));
  if(names!==OF3.names){OF3.names=names;OF3.now=1;try{return of3BuildNow()}finally{OF3.now=0}}
  return of3BuildNow();
}
function of3BuildNow(){
  const O=OFFICE,T=OF3.T,L=O.L,v=O.view;if(!T||!OF3.r||!L)return;
  const sig=JSON.stringify([L.rooms.map(r=>[r.kind,r.name,r.color,Math.min(OF3_SEATS,r.members.length),Math.round(r.x),Math.round(r.y)]),
    v.office.style,v.office.decor,v.office.pet,OF3.hq]);
  if(sig===OF3.sig&&OF3.scene){of3Fit();return}
  // The ring follows the window's shape, so a resize moves the rooms. Rebuild once the
  // window has settled: dragging an edge fires this many times a second. Until then the
  // old rooms stay (found: maximising left people and cards beside furniture that had
  // not moved, because only the names were in the signature).
  if(OF3.scene&&!OF3.now){of3Fit();clearTimeout(OF3.rebuild);
    OF3.rebuild=setTimeout(()=>{OF3.now=1;try{of3Build()}finally{OF3.now=0}officeKick()},180);return}
  clearTimeout(OF3.rebuild);
  // a new plan: the old scene goes, three.js and the renderer stay
  if(OF3.scene)OF3.scene.traverse(o=>{if(o.geometry)o.geometry.dispose();
    const m=o.material;if(m)(Array.isArray(m)?m:[m]).forEach(x=>{if(x.map&&!x.map.userData.shared)x.map.dispose();x.dispose()})});
  OF3_MAT={};OF3.sp={};OF3.screens=[];OF3.papers=[];OF3.pet=null;OF3.ball=null;
  Object.values(OF3.el).forEach(e=>e.remove());OF3.el={};OF3.cardSig='';
  OF3.sig=sig;
  const S=OF3.scene=new T.Scene();
  // the dark the rooms float in, tinted by the office's style (a greenhouse is a green night)
  S.background=of3Hex(v.style.wall||'#1b2233',['#0e0f1f',.86]);
  S.add(new T.HemisphereLight(0xcfd8ff,0x1a1b30,1.25));
  const sun=new T.DirectionalLight(0xfff1dc,1.55);
  const span=(L.R+300)/OF3_U;
  sun.position.set(-span*.45,span*1.1,span*.25);sun.target.position.set(0,0,0);S.add(sun);S.add(sun.target);
  if(OF3.hq){sun.castShadow=true;const c=sun.shadow.camera;c.left=c.bottom=-span*1.1;c.right=c.top=span*1.1;c.near=.5;c.far=span*4;
    sun.shadow.mapSize.set(2048,2048);sun.shadow.bias=-.0006;sun.shadow.normalBias=.02}
  const fill=new T.DirectionalLight(0x8fa8ff,.35);fill.position.set(span,span*.6,span);S.add(fill);
  const still=new T.Group();S.add(still);
  of3Stars(S,span);
  of3Hub(still,L);
  L.rooms.forEach((r,i)=>of3Room(still,r,i,v));
  if(typeof wlBake==='function')wlBake(T,still);
  of3Fit();
}
/* A few hundred points of light under and around everything: the dark the rooms float in. */
function of3Stars(S,span){
  const T=OF3.T,n=Math.round(260+span*40),pos=new Float32Array(n*3);
  for(let i=0;i<n;i++){const a=Math.random()*6.283,d=Math.sqrt(Math.random())*span*2.2;
    pos[i*3]=Math.cos(a)*d;pos[i*3+1]=-1.2-Math.random()*2;pos[i*3+2]=Math.sin(a)*d}
  const g=new T.BufferGeometry();g.setAttribute('position',new T.BufferAttribute(pos,3));
  S.add(new T.Points(g,new T.PointsMaterial({color:0x8d94c8,size:1.6,sizeAttenuation:false,transparent:true,opacity:.7,depthWrite:false})));
}
/* The Brain: a platform, three rings, an orb and a beam of light, with the walkway
   round it and a path out to every room's door. */
function of3Hub(par,L){
  const T=OF3.T,S=OF3.scene;
  const deck=of3Mat('deck',{color:'#1d2038',roughness:.6});
  of3Cyl(par,1.55,1.62,.16,deck,0,.08,0,48);
  const ringM=of3Mat('ring',{color:'#7dd3fc',emissive:'#38bdf8',emissiveIntensity:1.6,roughness:.4});
  [1.5,1.08,.72].forEach((r,i)=>{const t=new T.Mesh(new T.TorusGeometry(r,i?.018:.03,8,96),ringM);t.rotation.x=Math.PI/2;t.position.y=.17+i*.004;par.add(t)});
  // the walkway: a flat ring, and a path to each door
  const walk=of3Mat('walk',{color:'#262a46',roughness:.9});
  const ring=new T.Mesh(new T.RingGeometry((OF3_RING-26)/OF3_U,(OF3_RING+26)/OF3_U,96),walk);
  ring.rotation.x=-Math.PI/2;ring.position.y=.02;if(OF3.hq)ring.receiveShadow=true;par.add(ring);
  L.rooms.forEach(r=>{
    const a=r.spoke,b=r.doorPt,len=Math.hypot(b.x-a.x,b.y-a.y)/OF3_U,ang=Math.atan2(b.y-a.y,b.x-a.x);
    const mid=of3W((a.x+b.x)/2,(a.y+b.y)/2,.02);
    const strip=new T.Mesh(new T.BoxGeometry(len,.03,.46),walk);strip.position.copy(mid);strip.rotation.y=-ang;par.add(strip);
    const col=OFFICE.view.colors[r.color]||'#94a3b8';
    const line=new T.Mesh(new T.BoxGeometry(len,.012,.05),of3Mat('line:'+col,{color:col,emissive:col,emissiveIntensity:.9}));
    line.position.copy(mid);line.position.y=.045;line.rotation.y=-ang;par.add(line);
  });
  // the orb, its halo and the beam are what pulse, so they stay out of the bake
  const orb=new T.Mesh(new T.SphereGeometry(.3,32,20),new T.MeshStandardMaterial({color:'#dff3ff',emissive:'#9bdcff',emissiveIntensity:2.2,roughness:.2}));
  orb.position.set(0,.9,0);orb.userData.keep=1;S.add(orb);
  const halo=new T.Sprite(new T.SpriteMaterial({map:of3Glow(),color:0x7cc8ff,transparent:true,blending:T.AdditiveBlending,depthWrite:false,opacity:.75}));
  halo.position.copy(orb.position);halo.scale.set(2.6,2.6,1);S.add(halo);
  const beam=new T.Mesh(new T.CylinderGeometry(.09,.2,3.6,24,1,true),new T.MeshBasicMaterial({map:of3Beam(),color:0x9fd8ff,transparent:true,
    blending:T.AdditiveBlending,depthWrite:false,side:T.DoubleSide,opacity:.55}));
  beam.position.set(0,2.4,0);S.add(beam);
  const pad=new T.Sprite(new T.SpriteMaterial({map:of3Glow(),color:0x38bdf8,transparent:true,blending:T.AdditiveBlending,depthWrite:false,opacity:.35}));
  pad.position.set(0,.22,0);pad.scale.set(4.2,4.2,1);S.add(pad);
  OF3.brain={orb,halo,beam};
}
function of3Tex(key,w,h,draw){
  const T=OF3.T,t=(OF3.texs||(OF3.texs={}))[key];if(t)return t;
  const c=document.createElement('canvas');c.width=w;c.height=h;draw(c.getContext('2d'),w,h);
  const x=new T.CanvasTexture(c);x.colorSpace=T.SRGBColorSpace;x.userData.shared=1;return OF3.texs[key]=x;
}
function of3Glow(){return of3Tex('glow',64,64,(g,w)=>{const r=g.createRadialGradient(w/2,w/2,0,w/2,w/2,w/2);
  r.addColorStop(0,'rgba(255,255,255,1)');r.addColorStop(.3,'rgba(255,255,255,.45)');r.addColorStop(1,'rgba(255,255,255,0)');g.fillStyle=r;g.fillRect(0,0,w,w)})}
function of3Beam(){return of3Tex('beam',8,128,(g,w,h)=>{const r=g.createLinearGradient(0,0,0,h);
  r.addColorStop(0,'rgba(255,255,255,0)');r.addColorStop(.7,'rgba(255,255,255,.55)');r.addColorStop(1,'rgba(255,255,255,.95)');g.fillStyle=r;g.fillRect(0,0,w,h)})}
function of3Shadow(){return of3Tex('shadow',64,64,(g,w)=>{const r=g.createRadialGradient(w/2,w/2,0,w/2,w/2,w/2);
  r.addColorStop(0,'rgba(0,0,0,.5)');r.addColorStop(1,'rgba(0,0,0,0)');g.fillStyle=r;g.fillRect(0,0,w,w)})}
/* A room as a diorama: a coloured slab, a light floor, two walls at the back (the two the
   camera looks past), and the furniture its kind of room has. */
function of3Room(par,r,i,v){
  const T=OF3.T,col=v.colors[r.color]||v.style.accent||'#94a3b8',st=v.office.style,decor=v.office.decor||[];
  const W=r.w/OF3_U,D=r.h/OF3_U,x0=r.x/OF3_U,z0=r.y/OF3_U,cx=x0+W/2,cz=z0+D/2,top=OF3_SLAB;
  const slab=of3Mat('slab:'+col,{color:of3Hex(col,['#0b0c18',.18]),roughness:.7});
  of3Box(par,W,top,D,slab,cx,top/2,cz);
  const floor=of3Mat('floor:'+col,{color:of3Hex(col,['#f6f1e7',.78]),roughness:.9});
  of3Box(par,W-.14,.012,D-.14,floor,cx,top+.006,cz,false).receiveShadow=OF3.hq;
  const wall=of3Mat('wall:'+col,{color:of3Hex(col,['#1d1b2e',.22]),roughness:.85});
  const cap=of3Mat('cap:'+col,{color:of3Hex(col,['#ffffff',.35])});
  of3Box(par,W,OF3_WALL,.08,wall,cx,top+OF3_WALL/2,z0+.04);
  of3Box(par,.08,OF3_WALL,D,wall,x0+.04,top+OF3_WALL/2,cz);
  of3Box(par,W,.03,.1,cap,cx,top+OF3_WALL+.015,z0+.04,false);
  of3Box(par,.1,.03,D,cap,x0+.04,top+OF3_WALL+.015,cz,false);
  // a soft dark pool under the slab, so the rooms float rather than hang
  const pool=new T.Mesh(new T.PlaneGeometry(W*1.5,D*1.5),new T.MeshBasicMaterial({map:of3Shadow(),transparent:true,depthWrite:false}));
  pool.rotation.x=-Math.PI/2;pool.position.set(cx+.25,-.05,cz+.25);pool.userData.keep=1;OF3.scene.add(pool);
  // the wall screen: a dark panel with the department's colour in its lines
  const scr=of3Tex('wallscreen:'+col,128,64,(g,w,h)=>{g.fillStyle='#0d1020';g.fillRect(0,0,w,h);
    g.strokeStyle=col;g.lineWidth=2;g.globalAlpha=.85;g.beginPath();for(let x=6;x<w-6;x+=6){const y=h*.65-Math.abs(Math.sin(x*.09+i))*h*.38;x===6?g.moveTo(x,y):g.lineTo(x,y)}g.stroke();
    g.globalAlpha=.5;g.fillStyle=col;for(let k=0;k<5;k++)g.fillRect(8+k*22,h-12,14,4)});
  const panel=new T.Mesh(new T.PlaneGeometry(.9,.46),new T.MeshStandardMaterial({map:scr,emissive:'#ffffff',emissiveMap:scr,emissiveIntensity:.55,roughness:.4}));
  panel.position.set(cx+(r.kind==='lead'?-.55:.35),top+.6,z0+.085);par.add(panel);
  if(decor.includes('bookshelf')||r.kind==='lead')of3Shelf(par,x0+.13,top,z0+D*(r.kind==='lead'?.2:.38));
  if(decor.includes('posters')){const p=of3Mat('poster:'+i%3,{color:['#f472b6','#facc15','#60a5fa'][i%3]});
    const m=of3Box(par,.02,.42,.3,p,x0+.09,top+.55,z0+D*.78,false);m.userData.k=1}
  if(decor.includes('plants'))[[x0+W-.22,z0+.24],[x0+.24,z0+D-.24]].forEach(q=>of3Plant(par,q[0],top,q[1]));
  of3Lamp(par,x0+.3,top,z0+.3,col);      // in the back corner, clear of every desk
  const seats=Math.min(OF3_SEATS,(r.members||[]).length);
  if(r.kind==='lead'){
    const at={x:(r.x+r.w*.5)/OF3_U,z:(r.y+r.h*.46)/OF3_U};
    OF3.screens.push({room:i,key:'@agent',mats:of3Desk(par,at.x,at.z,col,1.35,2)});
    const c=officeCabinetAt();if(c)of3Cabinet(par,(c.x+c.w/2)/OF3_U,top,(c.y+c.h/2)/OF3_U);
    if(decor.includes('whiteboard'))of3Board(par,(r.x+r.w*.78)/OF3_U,top,z0+.09);
    of3Rug(par,cx,top,cz+.25,W*.62,col);
  }
  if(r.kind==='dept'||r.kind==='floor'){
    for(let k=0;k<seats;k++){const at=of3SeatPos(r,k,seats);
      OF3.screens.push({room:i,seat:k,mats:of3Desk(par,at.x/OF3_U,at.y/OF3_U,col,1,1)})}
    if(!seats)of3Rug(par,cx,top,cz,W*.5,col);
  }
  if(r.kind==='meeting'){
    // the same table officeTableSpot seats people round
    const tc={x:(r.x+r.w/2)/OF3_U,z:(r.y+OF_WALL+92+16)/OF3_U};
    of3Rug(par,tc.x,top,tc.z,1.9,col);
    of3Cyl(par,.62,.62,.05,of3Mat('table',{color:'#e8e2d6',roughness:.5}),tc.x,top+.5,tc.z,40);
    of3Cyl(par,.08,.14,.48,of3Mat('leg',{color:'#3b3f55'}),tc.x,top+.24,tc.z,12);
  }
  if(r.kind==='lounge'){
    of3Rug(par,cx,top,cz+.1,W*.55,col);
    const sofa=of3Mat('sofa:'+col,{color:of3Hex(col,['#3b2f4a',.35])});
    of3Box(par,1.3,.22,.48,sofa,x0+.95,top+.16,z0+.5);of3Box(par,1.3,.42,.14,sofa,x0+.95,top+.3,z0+.3);
    of3Box(par,.6,.04,.4,of3Mat('ctable',{color:'#c9a77c'}),x0+.95,top+.3,z0+1.05);
    const g=officeExtra('guard');
    if(g){const ax=g.x/OF3_U,az=g.y/OF3_U,arm=of3Mat('armchair',{color:'#4b5563'});
      of3Box(par,.5,.2,.44,arm,ax,top+.14,az-.06);of3Box(par,.5,.5,.12,arm,ax,top+.32,az-.26);
      of3Box(par,.1,.3,.44,arm,ax-.26,top+.24,az-.06);of3Box(par,.1,.3,.44,arm,ax+.26,top+.24,az-.06)}
    if(decor.includes('coffee')){of3Box(par,.3,.5,.26,of3Mat('coffee',{color:'#2b2f3f'}),x0+W-.3,top+.25,z0+.3);
      of3Box(par,.06,.06,.02,of3Mat('coffeeled',{color:'#fca5a5',emissive:'#ef4444',emissiveIntensity:2}),x0+W-.3,top+.38,z0+.44,false)}
    if(decor.includes('arcade')){of3Box(par,.4,.9,.36,of3Mat('arcade',{color:'#4c1d95'}),x0+.32,top+.45,z0+D-.5);
      of3Box(par,.3,.24,.02,of3Mat('arcadescr',{color:'#111',emissive:'#22d3ee',emissiveIntensity:1.4}),x0+.32,top+.66,z0+D-.31,false)}
  }
}
function of3Desk(par,x,z,col,wide,mons){
  const T=OF3.T,top=OF3_SLAB,dw=.95*wide;
  const wood=of3Mat('desk',{color:'#ece6da',roughness:.55}),leg=of3Mat('deskleg',{color:'#454a63'});
  const dz=z+.3;
  of3Box(par,dw,.05,.48,wood,x,top+.44,dz);
  of3Box(par,.04,.42,.44,leg,x-dw/2+.04,top+.21,dz);of3Box(par,.04,.42,.44,leg,x+dw/2-.04,top+.21,dz);
  of3Box(par,dw-.1,.3,.03,leg,x,top+.26,dz+.2);                 // the modesty panel hides the legs
  of3Box(par,.3,.015,.1,of3Mat('kbd',{color:'#2b2f42'}),x,top+.475,dz+.04,false);
  // the chair behind them
  const chair=of3Mat('chair:'+col,{color:of3Hex(col,['#1e2235',.6])});
  of3Box(par,.36,.06,.34,chair,x,top+.27,z-.04);of3Box(par,.36,.4,.06,chair,x,top+.5,z-.21);
  of3Cyl(par,.03,.03,.24,leg,x,top+.12,z-.04,8);
  // the monitor(s): their own material, because they light up when the person works.
  // Off to the side and turned towards the chair: a sprite always faces the camera, so a
  // screen straight in front of the person would hide their face.
  const mats=[];
  for(let k=0;k<mons;k++){
    const m=new T.MeshStandardMaterial({color:'#11131f',emissive:new T.Color(col).lerp(new T.Color('#ffffff'),.3),emissiveIntensity:0,roughness:.35});
    const mon=new T.Mesh(new T.BoxGeometry(.36,.24,.03),m);mon.userData.keep=1;
    const side=mons>1?(k?1:-1):-1;
    mon.position.set(x+side*dw*.4,top+.64,dz-.06);mon.rotation.y=-side*.55;if(OF3.hq)mon.castShadow=true;par.add(mon);
    of3Box(par,.04,.13,.04,leg,mon.position.x,top+.52,mon.position.z,false);
    mats.push(m);
  }
  const mug=of3Cyl(par,.035,.03,.08,of3Mat('mug:'+col,{color:col}),x+dw/2-.14,top+.505,dz+.06,10);mug.castShadow=false;
  return mats;
}
function of3Plant(par,x,y,z){
  const T=OF3.T,pot=of3Mat('pot',{color:'#e7e5e4',roughness:.6}),leaf=of3Mat('leaf',{color:'#3f9d4f',roughness:.8,flatShading:true});
  of3Cyl(par,.11,.08,.2,pot,x,y+.1,z,12);
  [[0,.36,0,.17],[.07,.46,.03,.12],[-.06,.47,-.04,.11]].forEach(q=>{
    const m=new T.Mesh(new T.IcosahedronGeometry(q[3],0),leaf);m.position.set(x+q[0],y+q[1],z+q[2]);if(OF3.hq)m.castShadow=true;par.add(m)});
}
function of3Lamp(par,x,y,z,col){
  const T=OF3.T;of3Cyl(par,.012,.012,.7,of3Mat('lamp',{color:'#2d3148'}),x,y+.35,z,6);
  const bulb=new T.Mesh(new T.SphereGeometry(.07,12,8),of3Mat('bulb',{color:'#fff7e0',emissive:'#ffd89a',emissiveIntensity:2.4}));
  bulb.position.set(x,y+.74,z);par.add(bulb);
  const h=new T.Sprite(new T.SpriteMaterial({map:of3Glow(),color:0xffd89a,transparent:true,blending:T.AdditiveBlending,depthWrite:false,opacity:.5}));
  h.material.opacity=.32;h.position.set(x,y+.74,z);h.scale.set(.42,.42,1);OF3.scene.add(h);
}
function of3Shelf(par,x,y,z){
  const wood=of3Mat('shelf',{color:'#7c5a3c'});
  of3Box(par,.16,.04,.7,wood,x,y+.42,z);of3Box(par,.16,.04,.7,wood,x,y+.7,z);
  ['#ef4444','#3b82f6','#f59e0b','#10b981','#a855f7'].forEach((c,k)=>of3Box(par,.12,.2,.08,of3Mat('book:'+c,{color:c}),x,y+.54,z-.26+k*.12,false));
}
function of3Rug(par,x,y,z,s,col){
  const T=OF3.T,m=new T.Mesh(new T.CylinderGeometry(s/2,s/2,.01,40),of3Mat('rug:'+col,{color:of3Hex(col,['#ffffff',.45]),roughness:1}));
  m.position.set(x,y+.015,z);if(OF3.hq)m.receiveShadow=true;par.add(m);
}
function of3Cabinet(par,x,y,z){
  const m=of3Mat('cabinet',{color:'#8b95a7',roughness:.5}),d=of3Mat('drawer',{color:'#aeb7c6'});
  of3Box(par,.32,.62,.34,m,x,y+.31,z);[0,1,2].forEach(k=>of3Box(par,.27,.16,.02,d,x,y+.12+k*.19,z+.175,false));
}
/* The mission board on the wall of your agent's office: what is running, in marker.
   A canvas texture redrawn only when the rows change. */
function of3Board(par,x,y,z){
  const T=OF3.T,c=document.createElement('canvas');c.width=256;c.height=128;
  const tex=new T.CanvasTexture(c);tex.colorSpace=T.SRGBColorSpace;
  const m=new T.Mesh(new T.PlaneGeometry(.9,.45),new T.MeshStandardMaterial({map:tex,roughness:.6}));
  m.position.set(x,y+.62,z);m.userData.keep=1;par.add(m);
  OF3.board={c,tex,rows:''};of3BoardPaint();
}
function of3BoardPaint(){
  const b=OF3.board;if(!b)return;
  const rows=officeNow(),k=rows.join('|');if(k===b.rows)return;b.rows=k;
  const g=b.c.getContext('2d');g.fillStyle='#fdfdfb';g.fillRect(0,0,256,128);
  g.strokeStyle='#cbd5e1';g.lineWidth=6;g.strokeRect(3,3,250,122);
  g.fillStyle='#ef4444';g.font='900 18px sans-serif';g.fillText('RIGHT NOW',14,30);
  g.font='700 17px sans-serif';g.fillStyle=rows.length?'#1d4ed8':'#94a3b8';
  (rows.length?rows.slice(0,3):['nothing running']).forEach((t,i)=>g.fillText(t.slice(0,24),14,58+i*24));
  b.tex.needsUpdate=true;
}

/* ---------------- the camera: the whole ring, or one room ---------------- */
function of3Basis(){
  const T=OF3.T,d=new T.Vector3(...OF3_DIR).normalize();
  const right=new T.Vector3(d.z,0,-d.x).normalize(),up=new T.Vector3().crossVectors(d,right).normalize();
  return {d,right,up};
}
/* The point on the floor that, looked at, moves the picture by (sx, sy) world units on
   screen. Orthographic, so a pan is exactly this. */
function of3Ground(sx,sy){
  const b=of3Basis(),a=b.right.x,c=b.right.z,e=b.up.x,f=b.up.z,det=a*f-c*e||1;
  return {x:(sx*f-c*sy)/det,z:(a*sy-sx*e)/det};
}
function of3Frame(view){
  const T=OF3.T,asp=OF3.cw/Math.max(1,OF3.ch),b=of3Basis();
  if(!OF3.cam)OF3.cam=new T.OrthographicCamera(-1,1,1,-1,.1,400);
  const c=OF3.cam,h=view.h;
  c.left=-h*asp;c.right=h*asp;c.top=h;c.bottom=-h;
  const t=new T.Vector3(view.x,0,view.z);
  c.position.copy(t).addScaledVector(b.d,80);c.lookAt(t);c.updateProjectionMatrix();c.updateMatrixWorld();
  OF3.view={x:view.x,z:view.z,h};OF3.dirty=true;
}
/* What covers the picture, in pixels: in Office HQ the prompt bar above and the dock
   below, so the ring fits in what is left. Nothing elsewhere. */
function of3Pads(){
  if(!of3HQ()||!OF3.cv)return {t:0,b:0};
  const top=OF3.cv.getBoundingClientRect().top,bar=document.getElementById('omnibar'),dock=document.getElementById('taskbar');
  const r=bar&&bar.offsetParent?bar.getBoundingClientRect():null,d=dock&&dock.offsetParent?dock.getBoundingClientRect():null;
  return {t:r?Math.max(0,r.bottom-top+18):60,b:d?Math.max(0,OF3.ch-(d.top-top)+10):100};
}
/* The whole office in the window, with room above each room for its card. */
function of3FitView(){
  const L=OFFICE.L,b=of3Basis(),asp=OF3.cw/Math.max(1,OF3.ch);
  let x0=1e9,x1=-1e9,y0=1e9,y1=-1e9;
  const see=(x,y,z)=>{const sx=x*b.right.x+z*b.right.z,sy=x*b.up.x+y*b.up.y+z*b.up.z;
    x0=Math.min(x0,sx);x1=Math.max(x1,sx);y0=Math.min(y0,sy);y1=Math.max(y1,sy)};
  L.rooms.forEach(r=>[[r.x,r.y],[r.x+r.w,r.y],[r.x,r.y+r.h],[r.x+r.w,r.y+r.h]].forEach(q=>{
    see(q[0]/OF3_U,-.1,q[1]/OF3_U);see(q[0]/OF3_U,OF3_SLAB+OF3_WALL+.75,q[1]/OF3_U)}));
  y1+=(y1-y0)*.05;      // the top rooms' cards stand above their walls
  const mx=(x1-x0)*.06;x0-=mx;x1+=mx;   // and the side rooms' cards stick out past them
  const pad=of3Pads(),fh=Math.max(.3,(OF3.ch-pad.t-pad.b)/Math.max(1,OF3.ch));
  const h=Math.max((y1-y0)/2/fh,(x1-x0)/2/asp)*1.05,k=2*h/Math.max(1,OF3.ch);
  // the picture's middle goes in the middle of what is left uncovered
  const g=of3Ground((x0+x1)/2,(y0+y1)/2+(pad.t-pad.b)/2*k);
  return {x:g.x,z:g.z,h};
}
function of3RoomView(name){
  const r=OFFICE.L.rooms.find(q=>q.name===name);if(!r)return OF3.fit;
  const b=of3Basis(),cw=OF3.cw,ch=OF3.ch,asp=cw/Math.max(1,ch);
  let x0=1e9,x1=-1e9,y0=1e9,y1=-1e9;
  [[r.x,r.y],[r.x+r.w,r.y],[r.x,r.y+r.h],[r.x+r.w,r.y+r.h]].forEach(q=>[0,OF3_SLAB+OF3_WALL+.25].forEach(h=>{
    const x=q[0]/OF3_U,z=q[1]/OF3_U,sx=x*b.right.x+z*b.right.z,sy=x*b.up.x+h*b.up.y+z*b.up.z;
    x0=Math.min(x0,sx);x1=Math.max(x1,sx);y0=Math.min(y0,sy);y1=Math.max(y1,sy)}));
  // the list of who is in the room covers the right of a wide window, and the bottom of a
  // phone: the room fits in what is left, centred there
  const pad=of3Pads(),phone=cw<=640,list=phone?0:Math.min(280,cw*.3),under=(phone?ch*.46:0)+pad.b,over=pad.t;
  const fw=(cw-list-24)/cw,fh=Math.max(.25,(ch-under-over-16)/ch);
  const h=Math.max((y1-y0)/2/fh,(x1-x0)/2/(asp*fw))*1.08;
  const k=2*h/ch;   // world units per pixel
  const g=of3Ground((x0+x1)/2+list/2*k,(y0+y1)/2-(under-over)/2*k);
  return {x:g.x,z:g.z,h};
}
function of3Fit(){
  if(!OF3.T||!OFFICE.L)return;
  OF3.fit=of3FitView();
  of3Frame(OF3.focus?of3RoomView(OF3.focus):OF3.fit);
}
function of3Go(view,ms){
  const from=OF3.view||view;
  if(OFFICE.static||!ms){of3Frame(view);officeKick();return}
  OF3.anim={from:{...from},to:view,at:performance.now(),ms};officeKick();
}
function of3Focus(name){
  OF3.focus=name||null;OF3.cardSig='';
  if(OF3.ui)OF3.ui.classList.toggle('focused',!!name);
  of3Roster();
  of3Go(name?of3RoomView(name):OF3.fit,OFFICE.static?0:650);
}

/* ---------------- input: tap, drag, wheel ---------------- */
function of3Input(cv){
  const O=OFFICE;
  if(O.w&&O.w.scene)return;           // the desktop scene is behind the windows: look, never touch
  cv.addEventListener('click',e=>{if(OF3.dragged){OF3.dragged=false;return}of3Tap(e)});
  cv.addEventListener('dblclick',()=>of3Focus(null));
  cv.addEventListener('wheel',e=>{if(!OF3.view)return;e.preventDefault();
    const v={...OF3.view,h:Math.max(1.2,Math.min((OF3.fit?OF3.fit.h:8)*1.6,OF3.view.h*(e.deltaY>0?1.1:1/1.1)))};
    OF3.anim=null;of3Frame(v);officeKick()},{passive:false});
  cv.addEventListener('pointerdown',e=>{if(e.pointerType==='touch')return;OF3.drag={x:e.clientX,y:e.clientY,v:{...OF3.view}};OF3.dragged=false});
  addEventListener('pointerup',()=>{OF3.drag=null});
  cv.addEventListener('pointermove',e=>{const d=OF3.drag;if(!d||!OF3.view)return;
    const dx=e.clientX-d.x,dy=e.clientY-d.y;if(Math.hypot(dx,dy)>4)OF3.dragged=true;if(!OF3.dragged)return;
    const k=2*d.v.h/OF3.ch,g=of3Ground(-dx*k,dy*k);
    OF3.anim=null;of3Frame({x:d.v.x+g.x,z:d.v.z+g.z,h:d.v.h});officeKick()});
  if(O.w&&O.w.el)O.w.el.addEventListener('keydown',e=>{if(e.key==='Escape'&&OF3.focus){of3Focus(null);e.stopPropagation()}});
}
function of3Project(v3){
  const p=v3.clone().project(OF3.cam);
  return {x:(p.x+1)/2*OF3.cw,y:(1-p.y)/2*OF3.ch,z:p.z};
}
function of3Head(p){
  const seated=p.mode==='seat'&&!p.bench;
  return of3W(p.x,p.y,OF3_SLAB+(seated?.98:1.02)*(p.lead?1.1:1));
}
function of3Tap(e){
  const O=OFFICE;if(!OF3.cam||!O.L)return;
  const r=OF3.cv.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;
  // a person first (their head and body), then the files, the Brain, and the room itself
  let best=null,bd=1e9;
  Object.values(O.people).forEach(p=>{if(!of3Shown(p))return;
    const h=of3Project(of3Head(p)),f=of3Project(of3W(p.x,p.y,OF3_SLAB));
    const dx=Math.abs(x-h.x),inY=y>h.y-14&&y<f.y+6;if(dx<22&&inY&&dx<bd){bd=dx;best=p}});
  if(best)return officeTapPerson(best);
  const c=officeCabinetAt();
  if(c){const q=of3Project(of3W(c.x+c.w/2,c.y+c.h/2,OF3_SLAB+.3));if(Math.hypot(x-q.x,y-q.y)<26)return officeFiles(true)}
  const b=of3Project(new OF3.T.Vector3(0,.9,0));
  if(Math.hypot(x-b.x,y-b.y)<36)return of3BrainOpen();
  const room=O.L.rooms.find(rm=>{const pts=[[rm.x,rm.y],[rm.x+rm.w,rm.y],[rm.x+rm.w,rm.y+rm.h],[rm.x,rm.y+rm.h]].map(q=>of3Project(of3W(q[0],q[1],OF3_SLAB)));
    let inside=false;for(let i=0,j=3;i<4;j=i++){const a=pts[i],c2=pts[j];
      if((a.y>y)!==(c2.y>y)&&x<(c2.x-a.x)*(y-a.y)/(c2.y-a.y)+a.x)inside=!inside}return inside});
  if(room)of3Focus(OF3.focus===room.name?null:room.name);
}
function of3BrainOpen(){if(typeof openApp==='function')openApp('memory')}

/* ---------------- every frame ---------------- */
function of3Draw(){
  const O=OFFICE,T=OF3.T;if(!OF3.r||!OF3.scene||!OF3.cam)return;
  const now=performance.now();
  if(OF3.anim){const a=OF3.anim,q=Math.min(1,(now-a.at)/a.ms),e=q<.5?2*q*q:1-Math.pow(-2*q+2,2)/2;
    of3Frame({x:a.from.x+(a.to.x-a.from.x)*e,z:a.from.z+(a.to.z-a.from.z)*e,h:a.from.h+(a.to.h-a.from.h)*e});
    if(q>=1)OF3.anim=null}
  of3People(now);
  of3Screens(now);
  of3Papers(now);
  of3Sparks(now);
  of3Pet();
  of3BrainLight(now);
  of3BoardPaint();
  OF3.r.render(OF3.scene,OF3.cam);
  of3Overlay(now);
  OF3.dirty=false;
}
/* Is anything in the 3D view still moving? The Office's loop asks officeMoving() for
   its own people; the camera, sparks and the Brain's pulse are this file's. */
function of3Moving(){return !!(OF3.anim||OF3.sparks.length||(OF3.pulse&&performance.now()-OF3.pulse<1400))}
function of3Sheet(p){
  const src=p.recipe?avatarRecipeSrc(p.recipe,{sheet:1}):avatarSrc(p.key,{sheet:1});
  let s=OF3.sp[p.key];
  if(s&&s.src===src)return s;
  const T=OF3.T;
  if(!s){
    const sp=new T.Sprite(new T.SpriteMaterial({transparent:true,alphaTest:.5}));
    sp.center.set(.5,0);OF3.scene.add(sp);
    const sh=new T.Mesh(new T.PlaneGeometry(.5,.24),new T.MeshBasicMaterial({map:of3Shadow(),transparent:true,depthWrite:false}));
    sh.rotation.x=-Math.PI/2;OF3.scene.add(sh);
    s=OF3.sp[p.key]={sprite:sp,shadow:sh,tex:null,src:''};
  }
  const tex=new T.TextureLoader().load(src,()=>officeKick());
  tex.magFilter=tex.minFilter=T.NearestFilter;tex.generateMipmaps=false;tex.colorSpace=T.SRGBColorSpace;tex.repeat.set(.25,1);
  if(s.tex)s.tex.dispose();s.tex=tex;s.src=src;s.sprite.material.map=tex;s.sprite.material.needsUpdate=true;
  return s;
}
function of3People(now){
  const O=OFFICE,seen=new Set(),all=[...Object.values(O.people),...(O.extras||[])];
  all.forEach(p=>{
    const show=p.recipe||of3Shown(p);
    if(!show){const s=OF3.sp[p.key];if(s){s.sprite.visible=false;s.shadow.visible=false}return}
    const s=of3Sheet(p);seen.add(p.key);
    const seated=p.mode==='seat'&&(p.recipe||!p.bench);
    const {frame,bob}=officeFrameOf(p,seated);
    s.tex.offset.x=frame*.25;
    const k=p.lead?1.1:1,arm=p.role==='guard';
    s.sprite.scale.set(.5*k,.81*k,1);
    s.sprite.position.copy(of3W(p.x,p.y,OF3_SLAB+(seated?(arm?.12:.16):0)+bob*.018));
    s.sprite.visible=true;
    s.shadow.visible=!seated;s.shadow.position.copy(of3W(p.x,p.y,OF3_SLAB+.012));
  });
  Object.keys(OF3.sp).forEach(k=>{if(!seen.has(k)){OF3.sp[k].sprite.visible=false;OF3.sp[k].shadow.visible=false}});
}
/* A monitor is lit while the person at that desk works, in the department's colour. */
function of3Screens(now){
  const O=OFFICE;
  OF3.screens.forEach(s=>{
    const r=O.L.rooms[s.room];if(!r)return;
    const key=s.key||(r.seats||[])[s.seat],p=key&&O.people[key];
    const lit=!!(p&&p.busy&&!p.bench),want=lit?.85+.2*Math.sin(now/160+(s.seat||0)):0;
    s.mats.forEach(m=>{if(Math.abs(m.emissiveIntensity-want)>.01)m.emissiveIntensity=want});
  });
}
/* Papers fly as little white sheets on an arc, from where they came to whoever gets them. */
function of3Papers(now){
  const O=OFFICE,T=OF3.T;
  while(OF3.papers.length<O.papers.length){const m=new T.Mesh(new T.BoxGeometry(.16,.01,.22),new T.MeshBasicMaterial({color:'#ffffff'}));OF3.scene.add(m);OF3.papers.push(m)}
  OF3.papers.forEach((m,i)=>{const pp=O.papers[i];m.visible=!!pp;if(!pp)return;
    const q=Math.min(1,(now-pp.at)/pp.ms),e=1-Math.pow(1-q,2);
    const to=pp.to.key?{x:pp.to.x,y:pp.to.y,h:1}:{x:pp.to.x,y:pp.to.y,h:.6};
    m.position.copy(of3W(pp.from.x+(to.x-pp.from.x)*e,pp.from.y+(to.y-pp.from.y)*e,OF3_SLAB+.9+Math.sin(q*Math.PI)*.9));
    m.rotation.set(q*3,q*6,0)});
}
/* A memory tool ran: a spark runs from that person out of their room to the Brain. */
function of3Tool(p,tool){
  if(!OFFICE.L||!OFFICE.L.radial||!p||!OF3_SPARK.test(String(tool||''))||!OF3.scene)return;
  const r=p.room,pts=[{x:p.x,y:p.y}];
  if(r&&r.doorPt)pts.push(r.inside,r.doorPt,r.spoke);
  pts.push({x:0,y:0});
  const T=OF3.T,s=new T.Sprite(new T.SpriteMaterial({map:of3Glow(),color:0x9bdcff,transparent:true,blending:T.AdditiveBlending,depthWrite:false}));
  s.scale.set(.5,.5,1);OF3.scene.add(s);
  let len=0;for(let i=1;i<pts.length;i++)len+=Math.hypot(pts[i].x-pts[i-1].x,pts[i].y-pts[i-1].y);
  OF3.sparks.push({pts,len,s,at:performance.now(),ms:OFFICE.static?1:Math.min(1800,500+len)});
  officeKick();
}
function of3Sparks(now){
  OF3.sparks=OF3.sparks.filter(k=>{
    const q=Math.min(1,(now-k.at)/k.ms);let d=q*k.len,i=1;
    while(i<k.pts.length-1&&d>Math.hypot(k.pts[i].x-k.pts[i-1].x,k.pts[i].y-k.pts[i-1].y)){d-=Math.hypot(k.pts[i].x-k.pts[i-1].x,k.pts[i].y-k.pts[i-1].y);i++}
    const a=k.pts[i-1],b=k.pts[i],l=Math.hypot(b.x-a.x,b.y-a.y)||1,t=Math.min(1,d/l);
    k.s.position.copy(of3W(a.x+(b.x-a.x)*t,a.y+(b.y-a.y)*t,OF3_SLAB+.3+(i===k.pts.length-1?t*.45:0)));
    if(q>=1){OF3.scene.remove(k.s);k.s.material.dispose();OF3.pulse=now;return false}
    return true});
}
function of3BrainLight(now){
  const b=OF3.brain;if(!b)return;
  const q=OF3.pulse?Math.max(0,1-(now-OF3.pulse)/1400):0;
  b.orb.scale.setScalar(1+.28*q);b.orb.material.emissiveIntensity=2.2+2.4*q;
  b.halo.material.opacity=.7+.3*q;b.halo.scale.setScalar(2.6+1.6*q);b.beam.material.opacity=.5+.4*q;
}
function of3Pet(){
  const O=OFFICE,T=OF3.T,p=O.pet;
  if(!p){if(OF3.pet){OF3.scene.remove(OF3.pet);OF3.pet=null}return}
  if(!OF3.pet||OF3.pet.userData.kind!==p.kind){
    if(OF3.pet)OF3.scene.remove(OF3.pet);
    const g=new T.Group(),fur=p.kind==='cat'?'#f59e0b':p.kind==='dog'?'#a16207':'#cbd5e1',m=of3Mat('pet:'+p.kind,{color:fur});
    const box=(w,h,d,x,y,z,mm)=>{const b=new T.Mesh(new T.BoxGeometry(w,h,d),mm||m);b.position.set(x,y,z);g.add(b)};
    if(p.kind==='robot'){box(.22,.18,.18,0,.14,0);box(.04,.04,.01,-.05,.16,.095,of3Mat('robot-eye',{color:'#22d3ee',emissive:'#22d3ee',emissiveIntensity:2}));
      box(.04,.04,.01,.05,.16,.095,of3Mat('robot-eye',{}));box(.015,.08,.015,0,.27,0)}
    else{box(.26,.12,.12,0,.12,0);box(.12,.11,.11,.15,.2,0);box(.03,.05,.03,.12,.27,-.03);box(.03,.05,.03,.12,.27,.03);
      box(.03,.03,.14,-.15,.17,0)}
    g.userData.kind=p.kind;OF3.scene.add(g);OF3.pet=g;
  }
  const b=p.walking&&!O.static?Math.abs(Math.sin(O.t*10))*.03:0;
  OF3.pet.position.copy(of3W(p.x,p.y,OF3_SLAB+b));OF3.pet.rotation.y=p.dir<0?Math.PI:0;
  if(O.ball){if(!OF3.ball){OF3.ball=new T.Mesh(new T.SphereGeometry(.05,10,8),of3Mat('ball',{color:p.kind==='cat'?'#f472b6':'#facc15'}));OF3.scene.add(OF3.ball)}
    OF3.ball.visible=true;OF3.ball.position.copy(of3W(O.ball.x,O.ball.y,OF3_SLAB+.06+(O.ball.state==='fly'?.4:0)))}
  else if(OF3.ball)OF3.ball.visible=false;
}

/* ---------------- the words over the picture ---------------- */
function of3El(key,cls,html){
  let e=OF3.el[key];
  if(!e){e=document.createElement('div');e.className=cls;OF3.ui.appendChild(e);OF3.el[key]=e;e._h=null}
  if(html!==undefined&&e._h!==html){e.innerHTML=html;e._h=html}
  e._seen=1;return e;
}
/* anchor: 'b' bottom-centre (cards, labels above things), 't' top-centre (name tags
   under feet), 'c' centre, '' top-left (balloons, placed by hand) */
function of3Place(e,x,y,dx,dy,anchor){
  const an={b:' translate(-50%,-100%)',t:' translate(-50%,0)',c:' translate(-50%,-50%)'}[anchor===undefined?'b':anchor]||'';
  const o=OF3.off||{x:0,y:0};
  const t=`translate(${Math.round(x+(dx||0)+o.x)}px,${Math.round(y+(dy||0)+o.y)}px)${an}`;
  if(e._t!==t){e.style.transform=t;e._t=t}
}
function of3Overlay(now){
  const O=OFFICE;if(!OF3.ui)return;
  Object.values(OF3.el).forEach(e=>e._seen=0);
  of3Cards();
  const b=of3Project(new OF3.T.Vector3(0,1.55,0)),br=O.view.brain||{};
  of3Place(of3El('brain','of3-brain',`<b>THE BRAIN</b><span>${(br.memories||0).toLocaleString()} ${br.memories===1?'memory':'memories'} · ${(br.facts||0).toLocaleString()} facts</span>`),b.x,b.y);
  const focus=OF3.focus;
  // names: everyone on the move, and every desk in the room you are looking at; two
  // people walking in together get two lines, not one smudge
  const tags=[];
  Object.values(O.people).forEach(p=>{
    if(!of3Shown(p))return;
    const moving=p.mode!=='seat'||p.visit,here=focus&&p.room&&p.room.name===focus;
    if(!(moving||here))return;
    const f=of3Project(of3W(p.x,p.y,OF3_SLAB)),label=(p.head?'★ ':'')+p.label;
    const e=of3El('tag:'+p.key,'of3-tag'+(p.busy?' busy':''),esc(label.length>16?label.slice(0,15)+'…':label));
    let y=f.y+(p.mode==='seat'&&!p.bench?14:4);const w=e.offsetWidth||60;
    for(let n=0;n<4&&tags.some(q=>Math.abs(q.x-f.x)<(q.w+w)/2&&Math.abs(q.y-y)<15);n++)y+=15;
    tags.push({x:f.x,y,w});of3Place(e,f.x,y,0,0,'t');
  });
  // balloons, newest on top, each placed clear of the ones already placed
  const placed=[];
  Object.values(O.people).filter(p=>p.say&&of3Shown(p)).sort((a,b2)=>b2.say.at-a.say.at).forEach(p=>{
    const s=p.say,age=(now-s.at)/s.ms,h=of3Project(of3Head(p));
    let t=s.text;if(t.length>110)t=t.slice(0,108).replace(/\s+\S*$/,'')+'…';
    const e=of3El('say:'+p.key,'of3-say '+s.kind,esc(t));
    e.style.opacity=age>.85?Math.max(0,(1-age)/.15):1;
    const w=e.offsetWidth||120,hh=e.offsetHeight||30;let x=h.x-w/2,y=h.y-hh-12;
    for(let n=0,o;n<6&&(o=placed.find(q=>x<q.x+q.w+4&&x+w+4>q.x&&y<q.y+q.h+4&&y+hh+4>q.y));n++)y=o.y-hh-6;
    placed.push({x,y,w,h:hh});of3Place(e,x,y,0,0,'');
    e.style.setProperty('--tail',Math.round(Math.max(10,Math.min(w-10,h.x-x)))+'px');
  });
  O.bursts.forEach((bu,i)=>{if(!of3Shown(bu.p))return;
    const q=(now-bu.at)/1500,h=of3Project(of3Head(bu.p)),e=of3El('burst:'+i,'of3-burst',
      `<b>${esc(bu.word)}</b>${bu.word.replace('!','').toLowerCase()!==String(bu.tool).replace(/_/g,' ')?`<i>${esc(String(bu.tool))}</i>`:''}`);
    e.style.opacity=q>.7?Math.max(0,(1-q)/.3):1;e.style.setProperty('--s',O.static?1:Math.min(1,q*6));
    of3Place(e,h.x+30,h.y-8-q*16,0,0,'c')});
  O.pops.forEach((po,i)=>{if(!of3Shown(po.p))return;
    const q=(now-po.at)/1100,h=of3Project(of3Head(po.p)),e=of3El('pop:'+i,'of3-pop',esc(po.text));
    e.style.opacity=q>.75?(1-q)*4:1;of3Place(e,h.x-22,h.y-6,0,0,'c')});
  Object.values(O.people).forEach(p=>{if(!p.stuck||!of3Shown(p))return;
    const f=of3Project(of3W(p.home.x,p.home.y+40,OF3_SLAB+.5));of3Place(of3El('stuck:'+p.key,'of3-stuck','✗ stuck'),f.x,f.y,0,0,'c')});
  const chats=Object.keys(O.convWho).length,lead=O.people['@agent'];
  if(lead&&chats>1){const h=of3Project(of3Head(lead));of3Place(of3El('chats','of3-badge','×'+chats),h.x+16,h.y-14,0,0,'c')}
  if(O.meeting){const m=officeRoomOf('meeting');if(m){const q=of3Project(of3W(m.cx,m.cy,OF3_SLAB+.7));
    of3Place(of3El('meet','of3-meet','▸ '+esc(O.meeting.flow)),q.x,q.y)}}
  const c=officeCabinetAt();
  if(c){const q=of3Project(of3W(c.x+c.w/2,c.y,OF3_SLAB+.75));
    of3Place(of3El('files','of3-files',`FILES${O.newFiles?` <em>${O.newFiles}</em>`:''}`),q.x,q.y)}
  Object.entries(OF3.el).forEach(([k,e])=>{if(!e._seen&&!k.startsWith('card:')){e.remove();delete OF3.el[k]}});
}
/* A card over every room: its name, how many are in it, how many are working, and
   their faces. A department of thirty is four desks and this card. */
function of3Cards(force){
  const O=OFFICE;if(!OF3.ui||!OF3.cam||!O.L)return;
  const co={};((typeof COMPANY!=='undefined'&&COMPANY.data&&COMPANY.data.departments)||[]).forEach(s=>co[s.name.toLowerCase()]=s);
  const rows=O.L.rooms.map(r=>{
    const ms=r.kind==='lead'?['@agent']:(r.members||[]),run=ms.filter(m=>O.people[m]&&O.people[m].busy).length;
    const s=co[r.name.toLowerCase()]||{};
    return {r,ms,run,wait:s.waiting||0,flag:s.flagged||0};
  });
  const sig=JSON.stringify([rows.map(x=>[x.r.name,x.ms.length,x.run,x.wait,x.flag,x.ms.slice(0,3)]),OF3.focus]);
  if(force||sig!==OF3.cardSig){
    OF3.cardSig=sig;
    rows.forEach((x,i)=>{
      const r=x.r,col=O.view.colors[r.color]||'#94a3b8';
      const kind=r.kind==='meeting'?'huddles gather here':r.kind==='lounge'?'take a break':
        `${x.ms.length} ${x.ms.length===1?'agent':'agents'}${x.run?` · <em>${x.run} running</em>`:''}`;
      const faces=x.ms.slice(0,3).map(m=>typeof avatarImg==='function'?avatarImg(m,'of3-face'):'').join('')+(x.ms.length>3?`<span class="of3-more">+${x.ms.length-3}</span>`:'');
      const tip=`${r.name}: ${x.ms.length} ${x.ms.length===1?'agent':'agents'}, ${x.run} working${x.wait?`, ${x.wait} waiting for you`:''}. Tap to look inside.`;
      const e=of3El('card:'+i,'of3-card'+(x.run?' busy':'')+(OF3.focus===r.name?' on':''),
        `<i style="background:${col}"></i><b>${esc(r.name)}</b><span class="of3-k">${x.run?'<span class="of3-dot"></span>':''}${kind}</span>`
        +(faces?`<span class="of3-faces">${faces}</span>`:'')
        +(x.wait?`<span class="of3-w">⚠ ${x.wait}</span>`:'')+(x.flag?`<span class="of3-w fl">⚑ ${x.flag}</span>`:''));
      e.title=tip;e.setAttribute('role','button');e.setAttribute('aria-label',tip);e.tabIndex=0;
      e.onclick=()=>of3Focus(OF3.focus===r.name?null:r.name);
      e.onkeydown=ev=>{if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();e.onclick()}};
    });
    Object.keys(OF3.el).forEach(k=>{if(k.startsWith('card:')&&+k.slice(5)>=rows.length){OF3.el[k].remove();delete OF3.el[k]}});
  }
  // over the room: centred on it, standing on its highest point (the back corner's wall)
  rows.forEach((x,i)=>{const r=x.r,e=OF3.el['card:'+i];if(!e)return;e._seen=1;
    const c=of3Project(of3W(r.cx,r.cy,0)),t=of3Project(of3W(r.x,r.y,OF3_SLAB+OF3_WALL));of3Place(e,c.x,t.y-6)});
}
/* Looking inside one room: the whole department in a list, desk or not. */
function of3Roster(){
  const O=OFFICE;if(!OF3.ui)return;
  let el=OF3.ui.querySelector('.of3-roster');
  const r=OF3.focus&&O.L.rooms.find(q=>q.name===OF3.focus);
  if(!r){if(el)el.remove();return}
  if(!el){el=document.createElement('div');el.className='of3-roster';OF3.ui.appendChild(el)}
  const ms=r.kind==='lead'?['@agent']:(r.members||[]);
  const state=p=>!p?'':p.hand?'waiting for you':p.busy?'working':p.bench?'between tasks':'at the desk';
  el.innerHTML=`<div class="of3-rh"><button class="endbtn of3-back">◂ All rooms</button><b>${esc(r.name)}</b></div>
    ${r.about?`<div class="mut of3-about">${esc(r.about)}</div>`:''}
    ${ms.length?ms.map(m=>{const p=O.people[m];return `<button class="of3-row${p&&p.busy?' busy':''}" data-k="${esc(m)}">
      ${typeof avatarImg==='function'?avatarImg(m,'of3-rface'):''}<span><b>${r.lead===m?'★ ':''}${esc(officeName(m))}</b>
      <small>${esc([(r.titles||{})[m],state(p),O.brains[m]].filter(Boolean).join(' · '))}</small></span></button>`}).join('')
      :`<div class="mut of3-about">${r.kind==='meeting'?'Nobody is meeting right now. Huddles and missions with two or more people gather here.':'Nobody sits here.'}</div>`}`;
  el.querySelector('.of3-back').onclick=()=>of3Focus(null);
  el.querySelectorAll('.of3-row').forEach(b=>b.onclick=()=>{const p=O.people[b.dataset.k];if(!p)return;
    // Office HQ has no chat of its own: the Office window opens, ready to ask them
    if(O.w&&O.w.scene){const k=b.dataset.k;openApp('office');
      setTimeout(()=>{const w=OFFICE.w,i=w&&!w.scene&&w.el.querySelector('.of-chat .cp-in');
        if(i&&k!=='@agent'){i.value='@'+k+' ';i.focus();w.el.querySelector('.of-wrap').classList.add('chat-open')}},500);return}
    of3Need(p);officeTapPerson(p)});
}
