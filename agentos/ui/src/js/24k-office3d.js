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

   - **People work facing their desks, and the desks face the walls.** The first cut drew
     every person as a flat picture turned to the camera behind a desk turned the same
     way, and it was reported as "all of them are facing me": a classroom. Now desks
     stand against the two back walls (of3SeatPos), so you see people from behind with
     their screens over their shoulder; the boss's desk faces the door. A person is a
     little figure of boxes that turns: to the screen while working, a little into the
     room when not, the way they walk, towards whoever they came to see, to the middle
     of the meeting table (of3SeatOf, of3LookAt). The chair turns with them.

   The rules the flat office lives by hold here too: nothing moves that did not happen
   (the Brain pulses when a memory tool really ran, a spark runs to it along the path,
   a screen lights and scrolls only while its person works); every person is the
   server's body sheet (front, blink, back, side) through avatarSrc / avatarRecipeSrc,
   wrapped round boxes, so there is no second painter (tests/test_avatars.py); a screen
   with no 3D graphics gets the flat office and one sentence saying why (OF3.why).

   Cost: three.js is the World's vendored copy, loaded only when this look is on. Static
   furniture is baked (wlBake); a person is six meshes on shared shapes (of3Geo); text is
   HTML over the canvas. Frames come from the Office's own loop (30 a second while
   something moves, 6 at rest, none asleep). Software rendering and phones get no
   shadows and pixel ratio 1 (worldQuality).

   Faces — GUI: the Office window and the desktop scene. SUI: the same page. TUI: `bento
   office look 3d|flat` sets it; a terminal shows the plan (`bento office`), not a picture.
   `var`, not `let`: the bundle is one script. */
var OF3={T:null,r:null,scene:null,cam:null,cv:null,ui:null,failed:false,why:'',gl:undefined,building:false,
  sig:'',rooms:[],screens:[],sp:{},el:{},view:null,target:null,fit:null,anim:null,focus:null,
  sparks:[],pulse:0,brain:null,papers:[],pet:null,ball:null,hq:false,cw:0,ch:0,dirty:true,drag:null,cardSig:'',
  geo:{},chairs:{},table:null};
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
  // The Office scene on the desktop is the comic: Office HQ is the 3D one, so the two scenes
  // are the two looks. Reported as "the 2D comic office I can't see any more, in the scene
  // where we had the boxes", after 3D became the office's default look.
  if(OFFICE.w&&OFFICE.w.scene)return false;
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
  // a renderer bound to another host (the desktop scene, a closed window) is no use here
  if(OF3.cv&&OF3.cv.parentElement!==sc)of3Dispose();
  if(OF3.r){of3Size();of3Build()}else of3Ensure();
  if(officeAwake())officeDraw();
  officeKick();
}

/* ---------------- seats: who has a desk, and who is on the card ---------------- */
/* Where desk k of n stands, and which way its person faces. An office is people at
   their screens, so the desks are against the walls and face them: two along the back
   wall, then down the left one. The camera looks from the front right, so you see each
   person from behind with their screens over their shoulder, which is what a working
   office looks like. (The first cut sat everybody facing you, and it read as a class.)
   fx/fy is the way they face, in plan units; the desk is in front of them. */
function of3SeatPos(r,k,n){
  const back=n<=1?[.55]:[.42,.75];
  if(k<back.length)return {x:r.x+r.w*back[k],y:r.y+88,fx:0,fy:-1};
  const left=n===3?[.6]:[.5,.82];
  return {x:r.x+88,y:r.y+r.h*left[Math.min(k-2,left.length-1)],fx:-1,fy:0};
}
/* Your agent runs the place, so its desk faces the door, with two chairs for visitors. */
function of3LeadSeat(r){return {x:r.x+r.w*.4,y:r.y+80,fx:0,fy:1,boss:1}}
/* A step behind the chair: where somebody stands up to, and comes back to, so a walk
   to or from a desk never goes through it. */
function of3Behind(h){return {x:h.x-h.fx*48,y:h.y-h.fy*48}}
function of3Seat(){
  const O=OFFICE,keep=O.people,seen={};
  O.L.rooms.forEach(r=>{
    if(r.kind==='lead'){
      const at=of3LeadSeat(r);
      seen['@agent']=officePerson(keep['@agent'],'@agent',(typeof agentName==='function'?agentName():'Aria'),r,at.x,at.y,true);
      Object.assign(seen['@agent'].home,{fx:at.fx,fy:at.fy,boss:1});
      seen['@agent'].bench=false;
    }
    if(r.kind!=='dept'&&r.kind!=='floor')return;
    r.members.forEach(m=>{
      const p=keep[m];
      // a person keeps the desk they had; everybody else waits at the door, unseen
      const home=p&&!p.bench&&p.room&&p.room.name===r.name&&p.room.kind===r.kind?p.home:r.inside;
      seen[m]=officePerson(p,m,m,r,home.x,home.y,false);
      if(home.fx!==undefined)Object.assign(seen[m].home,{fx:home.fx,fy:home.fy});
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
  const step=p.mode==='seat'&&!p.bench?officeStepOut(p.home):null;
  const from=p.mode!=='seat'?{x:p.x,y:p.y}:step||{x:p.home.x,y:p.home.y};
  const ra=officeRoomAt(from),rb=officeRoomAt(to),pts=[];
  if(step)pts.push(step);
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
    OF3.r=new T.WebGLRenderer({canvas:cv,antialias:true,alpha:true,powerPreference:'low-power'});
    OF3.r.outputColorSpace=T.SRGBColorSpace;OF3.r.toneMapping=T.ACESFilmicToneMapping;OF3.r.toneMappingExposure=1.05;
    // the kiosk is a small machine's own screen (a Pi): no shadows there either
    OF3.hq=!document.body.classList.contains('kiosk')&&typeof worldQuality==='function'?worldQuality(OF3.r):false;
    if(OF3.hq){OF3.r.shadowMap.enabled=true;OF3.r.shadowMap.type=T.PCFSoftShadowMap}
    of3Input(cv);of3Controls();
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
  of3Where();
}
/* Where the picture really is, seen from the layer the words are placed in, measured every
   frame. In Office HQ the canvas is in the wall, which is drawn larger than the screen and
   moves with the mouse (the parallax), while the cards are on the desktop above it; and a
   canvas stretched by its host shows its picture bigger than it was drawn. Measured once,
   at sizing, the cards were left behind by every one of those: reported with a screenshot
   of the room cards bunched in one corner and the rooms, half as big again, elsewhere. */
function of3Where(){
  if(!OF3.cv)return;
  // The area the office was laid out for, against the one it has now. Office HQ and the
  // office band share one element, so switching between them, or a layout measured while
  // the area was hidden, changes its size with no window resize to say so: the picture
  // was drawn three times too big with the cards packed in a corner. Lay it out again.
  const sc=OFFICE.cv&&OFFICE.cv.parentElement;
  const want=sc?Math.max(280,sc.clientWidth)+'x'+Math.max(200,sc.clientHeight):'';
  if(sc&&sc.clientWidth&&!OF3.relaying&&want!==OF3.tried&&(Math.abs(Math.max(280,sc.clientWidth)-OF3.cw)>8||Math.abs(Math.max(200,sc.clientHeight)-OF3.ch)>8)){
    OF3.relaying=true;OF3.tried=want;   // once per size: a size it cannot take is not a loop
    setTimeout(()=>{OF3.relaying=false;try{officeLayout()}catch(e){}},120);
  }
  const a=OF3.cv.getBoundingClientRect(),b=OF3.ui?OF3.ui.getBoundingClientRect():a;
  OF3.off={x:a.left-b.left,y:a.top-b.top,sx:a.width/Math.max(1,OF3.cw||a.width),sy:a.height/Math.max(1,OF3.ch||a.height)};
  // what can be seen of the picture, in its own units: the area it sits in, cut by the
  // screen. A balloon over somebody near the edge is kept inside it (on a phone the
  // meeting room is at the edge, and every line said there ran off the screen)
  const o=OF3.off,v=sc?sc.getBoundingClientRect():a;
  o.vis={l:(Math.max(v.left,0)-b.left-o.x)/(o.sx||1),r:(Math.min(v.right,innerWidth)-b.left-o.x)/(o.sx||1)};
}
function of3Dispose(){
  const T=OF3.T;
  if(OF3.scene)OF3.scene.traverse(o=>{if(o.geometry&&!o.geometry.userData.shared)o.geometry.dispose();
    const m=o.material;if(m)(Array.isArray(m)?m:[m]).forEach(x=>{if(x.map)x.map.dispose();x.dispose()})});
  Object.values(OF3.geo||{}).forEach(g=>g.dispose());
  if(OF3.r){try{OF3.r.dispose();OF3.r.forceContextLoss()}catch(e){}}
  if(OF3.cv)OF3.cv.remove();if(OF3.ui)OF3.ui.remove();
  clearTimeout(OF3.rebuild);
  Object.assign(OF3,{r:null,scene:null,cam:null,cv:null,ui:null,sig:'',names:'',rooms:[],screens:[],sp:{},el:{},
    view:null,target:null,fit:null,anim:null,focus:null,follow:'',followAt:0,userMoved:false,sparks:[],brain:null,papers:[],pet:null,ball:null,cardSig:'',
    geo:{},chairs:{},table:null,texs:{}});
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
    v.office.style,v.office.decor,v.office.pet,OF3.hq,!!(O.w&&O.w.scene)&&!of3HQ()]);
  if(sig===OF3.sig&&OF3.scene){of3Fit();return}
  // The ring follows the window's shape, so a resize moves the rooms. Rebuild once the
  // window has settled: dragging an edge fires this many times a second. Until then the
  // old rooms stay (found: maximising left people and cards beside furniture that had
  // not moved, because only the names were in the signature).
  if(OF3.scene&&!OF3.now){of3Fit();clearTimeout(OF3.rebuild);
    OF3.rebuild=setTimeout(()=>{OF3.now=1;try{of3Build()}finally{OF3.now=0}officeKick()},180);return}
  clearTimeout(OF3.rebuild);
  // a new plan: the old scene goes, three.js and the renderer stay
  if(OF3.scene)OF3.scene.traverse(o=>{if(o.geometry&&!o.geometry.userData.shared)o.geometry.dispose();
    const m=o.material;if(m)(Array.isArray(m)?m:[m]).forEach(x=>{if(x.map&&!x.map.userData.shared)x.map.dispose();x.dispose()})});
  OF3_MAT={};OF3.sp={};OF3.screens=[];OF3.papers=[];OF3.pet=null;OF3.ball=null;OF3.chairs={};OF3.table=null;
  Object.values(OF3.el).forEach(e=>e.remove());OF3.el={};OF3.cardSig='';
  OF3.sig=sig;
  const S=OF3.scene=new T.Scene();
  // the dark the rooms float in, tinted by the office's style (a greenhouse is a green night)
  // The office band on the desktop floats over the wallpaper; a window and Office HQ keep
  // their night. Opaque, the band was a hard-edged dark slab across the wallpaper.
  const band=!!(O.w&&O.w.scene)&&!of3HQ();
  S.background=band?null:of3Hex(v.style.wall||'#1b2233',['#0e0f1f',.86]);
  OF3.r.setClearColor(0,band?0:1);
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
/* A group standing at (x, z) on the slab, turned so its +z looks along (fx, fz). */
function of3At(par,x,z,fx,fz){const g=new OF3.T.Group();g.position.set(x,OF3_SLAB,z);g.rotation.y=Math.atan2(fx,fz);par.add(g);return g}
/* Shapes several things share (the chair, a person's head, an arm): made once. */
function of3Geo(key,make){const g=OF3.geo[key];if(g)return g;const n=make();n.userData.shared=1;return OF3.geo[key]=n}
function of3Merge(gs){
  const T=OF3.T,parts=gs.map(g=>g.index?g.toNonIndexed():g),out=new T.BufferGeometry();
  ['position','normal','uv'].forEach(a=>{
    let n=0;parts.forEach(g=>n+=g.attributes[a].array.length);
    const arr=new Float32Array(n);let o=0;parts.forEach(g=>{arr.set(g.attributes[a].array,o);o+=g.attributes[a].array.length});
    out.setAttribute(a,new T.BufferAttribute(arr,a==='uv'?2:3))});
  gs.forEach(g=>g.dispose());parts.forEach(g=>g.dispose());
  return out;
}
function of3Rand(s){s=s%2147483647||7;return ()=>{s=(s*16807)%2147483647;return (s-1)/2147483646}}
/* Wooden boards, tinted towards the room's colour. */
function of3FloorTex(col){
  const t=of3Tex('floor:'+col,128,128,(g,w,h)=>{
    g.fillStyle='#'+new OF3.T.Color(col).lerp(new OF3.T.Color('#efe6d6'),.84).getHexString();g.fillRect(0,0,w,h);
    const rnd=of3Rand(31);
    for(let y=0;y<h;y+=16){
      g.fillStyle='rgba(60,40,20,.07)';g.fillRect(0,y,w,1);
      for(let x=(y/16%2)*44;x<w;x+=88){g.fillRect(x,y,1,16)}
      for(let k=0;k<6;k++){g.fillStyle=`rgba(${rnd()<.5?'255,255,255':'90,60,30'},.035)`;g.fillRect(rnd()*w,y+2+rnd()*12,20+rnd()*40,1)}
    }});
  const T=OF3.T;t.wrapS=t.wrapT=T.RepeatWrapping;t.repeat.set(2.4,2);return t;
}
/* A city at dusk through the windows: lit offices in the towers. */
function of3Sky(){
  return of3Tex('sky',256,96,(g,w,h)=>{
    const gr=g.createLinearGradient(0,0,0,h);gr.addColorStop(0,'#141a3a');gr.addColorStop(.55,'#3b2f6b');gr.addColorStop(1,'#d9897a');
    g.fillStyle=gr;g.fillRect(0,0,w,h);
    const rnd=of3Rand(11);g.fillStyle='rgba(255,255,255,.7)';for(let k=0;k<26;k++)g.fillRect(rnd()*w,rnd()*h*.4,1,1);
    for(let layer=0;layer<2;layer++){let x=-4;
      while(x<w){const bw=12+rnd()*24,bh=h*(layer?.22+rnd()*.4:.4+rnd()*.5);
        g.fillStyle=layer?'#191b3d':'#232650';g.fillRect(x,h-bh,bw,bh);
        g.fillStyle=layer?'rgba(255,196,120,.9)':'rgba(170,190,255,.55)';
        for(let yy=h-bh+4;yy<h-3;yy+=5)for(let xx=x+2;xx<x+bw-3;xx+=4)if(rnd()<(layer?.42:.25))g.fillRect(xx,yy,2,2);
        x+=bw+(layer?2:6)}}
  });
}
/* A band of windows along a back wall: glass with the city, a frame and mullions.
   axis 'x' runs along the back wall at z; 'z' runs down the left wall at x. */
function of3Window(par,a0,a1,y0,y1,at,axis){
  const T=OF3.T,len=a1-a0,h=y1-y0,mid=(a0+a1)/2,my=(y0+y1)/2,tex=of3Sky();
  const glass=of3Mat('window',{color:'#ffffff',map:tex,emissive:'#ffffff',emissiveMap:tex,emissiveIntensity:.75,roughness:.12,metalness:.1});
  const frame=of3Mat('winframe',{color:'#2a2d42',roughness:.5});
  const pl=new T.Mesh(new T.PlaneGeometry(len,h),glass);
  if(axis==='z'){pl.rotation.y=Math.PI/2;pl.position.set(at,my,mid)}else pl.position.set(mid,my,at);
  par.add(pl);
  const n=Math.max(1,Math.round(len/.55));
  for(let k=0;k<=n;k++){const p=a0+len*k/n;
    if(axis==='z')of3Box(par,.03,h+.02,.035,frame,at+.012,my,p,false);else of3Box(par,.035,h+.02,.03,frame,p,my,at+.012,false)}
  [y0,y1].forEach(y=>{if(axis==='z')of3Box(par,.06,.03,len,frame,at+.02,y,mid,false);else of3Box(par,len,.03,.06,frame,mid,y,at+.02,false)});
}
/* What is on a screen: code, in the department's colour and a few others. */
function of3CodeTex(col){
  return of3Tex('code:'+col,128,128,(g,w,h)=>{
    g.fillStyle='#0b0e1a';g.fillRect(0,0,w,h);
    let seed=0;for(const c of col)seed=seed*31+c.charCodeAt(0);
    const rnd=of3Rand(seed),cols=[col,'#e2e8f0','#94a3b8','#fbbf24','#a78bfa','#34d399',col];
    for(let y=3;y<h;y+=6){let x=3+Math.floor(rnd()*4)*6;if(rnd()<.12)continue;
      while(x<w-8&&rnd()>.16){const l=4+Math.floor(rnd()*18);g.fillStyle=cols[Math.floor(rnd()*cols.length)];g.globalAlpha=.9;g.fillRect(x,y,Math.min(l,w-4-x),3);x+=l+3}}
    g.globalAlpha=1;
  });
}
function of3Plant(par,x,y,z,big,s){
  const T=OF3.T,pot=of3Mat('pot',{color:'#e7e5e4',roughness:.6}),leaf=of3Mat('leaf',{color:'#3f9d4f',roughness:.8,flatShading:true});
  const leaf2=of3Mat('leaf2',{color:'#2f7d3e',roughness:.8,flatShading:true});s=s||1;
  if(big){
    of3Cyl(par,.13,.1,.26,pot,x,y+.13,z,14);
    [[0,.42,0,.17,0],[.08,.58,.04,.14,1],[-.07,.62,-.05,.13,0],[.02,.76,.0,.11,1],[-.09,.46,.07,.12,1]].forEach(q=>{
      const m=new T.Mesh(new T.IcosahedronGeometry(q[3],0),q[4]?leaf2:leaf);m.position.set(x+q[0],y+q[1],z+q[2]);if(OF3.hq)m.castShadow=true;par.add(m)});
    return;
  }
  of3Cyl(par,.1*s,.075*s,.18*s,pot,x,y+.09*s,z,12);
  [[0,.32,0,.15],[.06,.41,.03,.11],[-.05,.42,-.04,.1]].forEach(q=>{
    const m=new T.Mesh(new T.IcosahedronGeometry(q[3]*s,0),leaf);m.position.set(x+q[0]*s,y+q[1]*s,z+q[2]*s);if(OF3.hq)m.castShadow=true;par.add(m)});
}
/* A whiteboard on wheels with sticky notes in three columns. Decor: the notes are not
   tasks (the cards over the rooms count those), so they never change. */
function of3Kanban(par,x,y,z,i,col){
  const T=OF3.T,g=of3At(par,x,z,1,1),frame=of3Mat('kbframe',{color:'#cbd5e1',metalness:.4,roughness:.4});
  g.position.y=y;g.scale.setScalar(.8);
  of3Box(g,.86,.5,.03,of3Mat('kbboard',{color:'#ffffff',emissive:'#ffffff',emissiveIntensity:.18,roughness:.6}),0,.52,0);
  of3Box(g,.9,.03,.05,frame,0,.785,0,false);of3Box(g,.9,.03,.05,frame,0,.255,0,false);
  [-.43,.43].forEach(x=>{of3Box(g,.025,.26,.025,frame,x,.13,0,false);of3Box(g,.025,.02,.22,frame,x,.01,0,false)});
  const rnd=of3Rand(i*7+3),notes=['#fde047','#f9a8d4','#86efac','#93c5fd',col];
  [-.28,0,.28].forEach((cx,c)=>{of3Box(g,.005,.42,.006,of3Mat('kbline',{color:'#cbd5e1'}),cx+.14,.52,.018,false);
    const n=2+Math.floor(rnd()*(c===1?2:3));
    for(let k=0;k<n;k++)of3Box(g,.075,.075,.006,of3Mat('note:'+notes[(k+c)%notes.length],{color:notes[(k+c)%notes.length],emissive:notes[(k+c)%notes.length],emissiveIntensity:.45}),
      cx-.05+(k%2)*.1,.7-Math.floor(k/2)*.1,.02,false)});
}
function of3Beanbag(par,x,y,z,col){
  const T=OF3.T,m=new T.Mesh(new T.SphereGeometry(.2,14,10),of3Mat('bean:'+col,{color:of3Hex(col,['#ffffff',.15]),roughness:.95}));
  m.scale.set(1,.55,1);m.position.set(x,y+.1,z);if(OF3.hq){m.castShadow=true;m.receiveShadow=true}par.add(m);
}
function of3Cooler(par,x,y,z){
  of3Box(par,.22,.5,.22,of3Mat('cooler',{color:'#e2e8f0',roughness:.4}),x,y+.25,z);
  of3Cyl(par,.09,.09,.24,of3Mat('water',{color:'#7dd3fc',transparent:true,opacity:.7,roughness:.1}),x,y+.62,z,14);
  of3Box(par,.08,.03,.02,of3Mat('tap',{color:'#3b82f6'}),x,y+.38,z+.115,false);
}
function of3Art(par,x,y,z,i){
  const c=['#f472b6','#facc15','#60a5fa','#34d399'][i%4];
  of3Box(par,.02,.36,.5,of3Mat('frame',{color:'#1f2937'}),x,y,z,false);
  of3Box(par,.02,.3,.44,of3Mat('art:'+c,{color:c,emissive:c,emissiveIntensity:.15}),x+.012,y,z,false);
}
/* A room as a diorama: a coloured slab, a wooden floor, two walls at the back (the two
   the camera looks past) with windows onto a city, and the furniture its kind of room
   has. Everything here is baked into a few meshes; only what moves stays apart (the
   chairs, which swivel with whoever sits in them, and the screens, which light up). */
function of3Room(par,r,i,v){
  const T=OF3.T,col=v.colors[r.color]||v.style.accent||'#94a3b8',decor=v.office.decor||[];
  const W=r.w/OF3_U,D=r.h/OF3_U,x0=r.x/OF3_U,z0=r.y/OF3_U,cx=x0+W/2,cz=z0+D/2,top=OF3_SLAB;
  const slab=of3Mat('slab:'+col,{color:of3Hex(col,['#0b0c18',.18]),roughness:.7});
  of3Box(par,W,top,D,slab,cx,top/2,cz);
  const floor=of3Mat('floor:'+col,{color:'#ffffff',map:of3FloorTex(col),roughness:.78});
  of3Box(par,W-.14,.012,D-.14,floor,cx,top+.006,cz,false).receiveShadow=OF3.hq;
  const wall=of3Mat('wall:'+col,{color:of3Hex(col,['#1d1b2e',.22]),roughness:.85});
  const cap=of3Mat('cap:'+col,{color:of3Hex(col,['#ffffff',.35])});
  of3Box(par,W,OF3_WALL,.08,wall,cx,top+OF3_WALL/2,z0+.04);
  of3Box(par,.08,OF3_WALL,D,wall,x0+.04,top+OF3_WALL/2,cz);
  of3Box(par,W,.03,.1,cap,cx,top+OF3_WALL+.015,z0+.04,false);
  of3Box(par,.1,.03,D,cap,x0+.04,top+OF3_WALL+.015,cz,false);
  // the skirting light along the two open edges, in the department's colour
  const led=of3Mat('led:'+col,{color:col,emissive:col,emissiveIntensity:1.3});
  of3Box(par,W-.1,.02,.025,led,cx,top+.01,z0+D-.06,false);of3Box(par,.025,.02,D-.1,led,x0+W-.06,top+.01,cz,false);
  // a soft dark pool under the slab, so the rooms float rather than hang
  const pool=new T.Mesh(new T.PlaneGeometry(W*1.5,D*1.5),new T.MeshBasicMaterial({map:of3Shadow(),transparent:true,depthWrite:false}));
  pool.rotation.x=-Math.PI/2;pool.position.set(cx+.25,-.05,cz+.25);pool.userData.keep=1;OF3.scene.add(pool);
  const plant=(x,z,big)=>of3Plant(par,x,top,z,big);
  if(r.kind==='lead')return of3LeadRoom(par,r,i,col,decor,{W,D,x0,z0,cx,cz,top});
  if(r.kind==='meeting')return of3MeetRoom(par,r,i,col,{W,D,x0,z0,cx,cz,top});
  if(r.kind==='lounge')return of3Lounge(par,r,i,col,decor,{W,D,x0,z0,cx,cz,top});
  // a department: windows down both walls, desks against them, a plant in each corner
  of3Window(par,x0+.3,x0+W-.25,top+.42,top+.86,z0+.085,'x');
  of3Window(par,z0+.35,z0+D-.25,top+.42,top+.86,x0+.085,'z');
  plant(x0+.24,z0+.26,true);
  if(decor.includes('plants'))plant(x0+W-.22,z0+D-.24,false);
  const seats=Math.min(OF3_SEATS,(r.members||[]).length);
  // carpet where the desks are, so the room has a working side and an open one
  const carpet=of3Mat('carpet:'+col,{color:of3Hex(col,['#2a2f45',.62]),roughness:1});
  of3Box(par,W-.16,.006,1.2,carpet,cx,top+.014,z0+.68,false).receiveShadow=OF3.hq;
  if(seats>2)of3Box(par,1.2,.006,D-1.36,carpet,x0+.68,top+.014,z0+1.28+(D-1.36)/2,false).receiveShadow=OF3.hq;
  // the team's board, turned to the room: what is to do, being done and done
  of3Kanban(par,x0+W*.66,top,z0+D*.66,i,col);
  for(let k=0;k<seats;k++){const at=of3SeatPos(r,k,seats);
    OF3.screens.push({room:i,seat:k,mats:of3Workstation(par,at,col,k,i+':'+k)})}
  if(seats<3){of3Beanbag(par,x0+W*.32,top,z0+D*.78,col);of3Beanbag(par,x0+W*.48,top,z0+D*.86,'#475569')}
  of3Cooler(par,x0+W-.22,top,z0+D-.55);
}
/* A workstation: desk, two screens, keyboard, a mug, and the chair (which swivels).
   Built facing +z at the origin and turned to face (fx, fy). Returns the screens'
   materials, which light up while the person works. */
function of3Workstation(par,at,col,k,chairKey){
  const T=OF3.T,g=of3At(par,at.x/OF3_U,at.y/OF3_U,at.fx,at.fy);
  const wood=of3Mat('desk',{color:'#e9e2d4',roughness:.55}),leg=of3Mat('deskleg',{color:'#3b4057'});
  of3Box(g,.86,.03,.42,wood,0,.31,.42);
  of3Box(g,.03,.3,.38,leg,-.41,.155,.42);of3Box(g,.03,.3,.38,leg,.41,.155,.42);
  of3Box(g,.8,.16,.02,leg,0,.2,.62,false);
  of3Box(g,.26,.012,.08,of3Mat('kbd',{color:'#262a3c'}),0,.33,.3,false);
  of3Box(g,.04,.014,.06,of3Mat('mouse',{color:'#cbd5e1'}),.2,.33,.3,false);
  of3Cyl(g,.03,.026,.07,of3Mat('mug:'+col,{color:col}),-.34,.36,.3,10).castShadow=false;
  if(k%2)of3Plant(g,-.33,.325,.52,false,.55);else of3Box(g,.13,.03,.17,of3Mat('paper',{color:'#f8fafc'}),.31,.34,.46,false);
  // both screens share one material: one draw for the pair, and they light together
  const mat=of3ScreenMat(col);[-.18,.18].forEach(x=>of3Monitor(g,x,.56,mat,x<0?.2:-.2));
  of3Chair(par,at,col,chairKey);
  return [mat];
}
function of3ScreenMat(col){
  const T=OF3.T,tex=of3CodeTex(col).clone();tex.needsUpdate=true;tex.repeat.set(1,.55);tex.offset.y=Math.random()*.45;
  return new T.MeshStandardMaterial({color:'#0b0d18',map:tex,emissive:'#ffffff',emissiveMap:tex,emissiveIntensity:.18,roughness:.3});
}
function of3Monitor(g,x,z,mat,turn){
  const T=OF3.T,dark=of3Mat('bezel',{color:'#151827',roughness:.4}),m=new T.Group();m.position.set(x,0,z);m.rotation.y=turn||0;g.add(m);
  of3Box(m,.33,.21,.025,dark,0,.52,0);
  of3Box(m,.03,.1,.03,dark,0,.38,.02,false);of3Box(m,.12,.01,.08,dark,0,.33,.02,false);
  const s=new T.Mesh(new T.PlaneGeometry(.3,.18),mat);s.rotation.y=Math.PI;s.position.set(0,.52,-.014);s.userData.keep=1;m.add(s);
}
/* An office chair that turns with whoever sits in it. One shared shape; its own mesh. */
function of3Chair(par,at,col,key,yaw){
  const T=OF3.T,m=new T.Mesh(of3ChairGeo(),of3Mat('chair:'+col,{color:of3Hex(col,['#1a1d2e',.72]),roughness:.7}));
  m.position.set(at.x/OF3_U,OF3_SLAB,at.y/OF3_U);m.rotation.y=yaw!==undefined?yaw:Math.atan2(at.fx,at.fy);m.userData.keep=1;
  if(OF3.hq){m.castShadow=true;m.receiveShadow=true}
  OF3.scene.add(m);if(key)OF3.chairs[key]=m;return m;
}
function of3ChairGeo(){
  return of3Geo('chair',()=>{
    const T=OF3.T,parts=[],add=(w,h,d,x,y,z)=>{const b=new T.BoxGeometry(w,h,d);b.translate(x,y,z);parts.push(b)};
    add(.28,.05,.26,0,.14,-.01);add(.26,.22,.05,0,.3,-.15);add(.03,.11,.03,0,.07,0);
    add(.035,.03,.16,-.15,.22,0);add(.035,.03,.16,.15,.22,0);add(.022,.06,.022,-.15,.18,0);add(.022,.06,.022,.15,.18,0);
    for(let a=0;a<5;a++){const b=new T.BoxGeometry(.19,.025,.035);b.translate(.095,.02,0);b.rotateY(a*Math.PI*2/5);parts.push(b)}
    return of3Merge(parts);
  });
}
/* Your agent's office: an executive desk facing the door with a laptop, two chairs
   for visitors, a sofa under the board, the files, books and a big plant. */
function of3LeadRoom(par,r,i,col,decor,R){
  const T=OF3.T,{W,D,x0,z0,cx,cz,top}=R,at=of3LeadSeat(r);
  of3Window(par,x0+.3,x0+W*.62,top+.42,top+.86,z0+.085,'x');
  of3Window(par,z0+1.8,z0+D-.25,top+.42,top+.86,x0+.085,'z');
  of3Rug(par,at.x/OF3_U,top,at.y/OF3_U+.6,1.7,col);
  const g=of3At(par,at.x/OF3_U,at.y/OF3_U,at.fx,at.fy);
  const walnut=of3Mat('walnut',{color:'#5b3a29',roughness:.45}),brass=of3Mat('brass',{color:'#d6b25e',roughness:.3,metalness:.6});
  of3Box(g,1.15,.04,.5,walnut,0,.33,.42);of3Box(g,1.15,.28,.03,walnut,0,.17,.66);
  of3Box(g,.04,.3,.48,walnut,-.56,.16,.42);of3Box(g,.04,.3,.48,walnut,.56,.16,.42);
  of3Box(g,1.1,.012,.03,brass,0,.31,.67,false);
  // the laptop: low enough that you see who is behind it
  const dark=of3Mat('bezel',{color:'#151827',roughness:.4});
  of3Box(g,.28,.012,.19,dark,0,.357,.36,false);
  const mat=of3ScreenMat(col),lid=new T.Group();lid.position.set(0,.36,.455);lid.rotation.x=.32;g.add(lid);
  of3Box(lid,.28,.18,.012,dark,0,.09,0,false);
  const s=new T.Mesh(new T.PlaneGeometry(.25,.15),mat);s.rotation.y=Math.PI;s.position.set(0,.09,-.008);s.userData.keep=1;lid.add(s);
  OF3.screens.push({room:i,key:'@agent',mats:[mat]});
  of3Cyl(g,.035,.03,.08,of3Mat('mug:'+col,{color:col}),.42,.39,.3,10);
  of3Box(g,.12,.02,.16,of3Mat('paper',{color:'#f8fafc'}),-.4,.36,.44,false);
  of3Chair(par,at,col,'lead');
  // two chairs for whoever comes to report, facing the desk
  [-.36,.36].forEach(x=>of3Chair(par,{x:at.x+x*OF3_U,y:at.y+95,fx:0,fy:-1},'#64748b'));
  // the sofa under the mission board, and a coffee table
  const sofa=of3Mat('sofa:'+col,{color:of3Hex(col,['#3b2f4a',.35])}),sx=x0+W*.8;
  of3Box(par,1.0,.16,.42,sofa,sx,top+.12,z0+.36);of3Box(par,1.0,.32,.12,sofa,sx,top+.24,z0+.18);
  of3Box(par,.12,.24,.42,sofa,sx-.5,top+.16,z0+.36);of3Box(par,.12,.24,.42,sofa,sx+.5,top+.16,z0+.36);
  of3Box(par,.5,.03,.3,walnut,sx,top+.2,z0+.82);of3Box(par,.04,.18,.04,walnut,sx,top+.1,z0+.82,false);
  if(decor.includes('whiteboard'))of3Board(par,sx,top+.08,z0+.09);
  const c=officeCabinetAt();if(c)of3Cabinet(par,(c.x+c.w/2)/OF3_U,top,(c.y+c.h/2)/OF3_U);
  if(decor.includes('bookshelf'))of3Shelf(par,x0+.14,top,z0+D*.5);
  of3Plant(par,x0+W-.24,top,z0+D-.26,true);of3Plant(par,x0+.25,top,z0+.27,true);
  of3Lamp(par,x0+W-.25,top,z0+1.1,col);
}
/* The meeting room: a long table with a chair at every place a meeting seats people
   (officeTableSpot), a screen on the wall, and windows. */
function of3MeetRoom(par,r,i,col,R){
  const T=OF3.T,{W,D,x0,z0,cx,cz,top}=R;
  of3Window(par,z0+.3,z0+D-.25,top+.42,top+.86,x0+.085,'z');
  const tc={x:r.x+r.w/2,y:r.y+155},tx=tc.x/OF3_U,tz=tc.y/OF3_U;
  of3Rug(par,tx,top,tz,2.4,col);
  const tm=of3Mat('table',{color:'#efe8dc',roughness:.4}),leg=of3Mat('leg',{color:'#3b3f55'});
  of3Box(par,1.34,.04,.66,tm,tx,top+.33,tz);of3Cyl(par,.33,.33,.04,tm,tx-.67,top+.33,tz,24);of3Cyl(par,.33,.33,.04,tm,tx+.67,top+.33,tz,24);
  of3Box(par,.9,.3,.08,leg,tx,top+.16,tz,false);
  OF3.table={x:tc.x,y:tc.y,spots:[]};
  for(let k=0;k<8;k++){const s=officeTableSpot(k),ax=Math.max(tc.x-67,Math.min(tc.x+67,s.x));
    const fx=ax-s.x,fy=tc.y-s.y,l=Math.hypot(fx,fy)||1;
    of3Chair(par,{x:s.x,y:s.y,fx:fx/l,fy:fy/l},col,'meet:'+k);OF3.table.spots.push({x:s.x,y:s.y,yaw:Math.atan2(fx/l,fy/l),k})}
  // the screen on the back wall, with a chart in the room's colour
  const scr=of3Tex('wallscreen:'+col,128,64,(g,w,h)=>{g.fillStyle='#0d1020';g.fillRect(0,0,w,h);
    g.strokeStyle=col;g.lineWidth=2;g.globalAlpha=.9;g.beginPath();for(let x=6;x<w-6;x+=6){const y=h*.65-Math.abs(Math.sin(x*.09+i))*h*.38;x===6?g.moveTo(x,y):g.lineTo(x,y)}g.stroke();
    g.globalAlpha=.55;g.fillStyle=col;for(let k=0;k<5;k++)g.fillRect(8+k*22,h-12,14,4)});
  of3Box(par,1.1,.6,.03,of3Mat('bezel',{color:'#151827'}),tx,top+.6,z0+.1,false);
  const p=new T.Mesh(new T.PlaneGeometry(1.04,.54),new T.MeshStandardMaterial({map:scr,emissive:'#ffffff',emissiveMap:scr,emissiveIntensity:.6,roughness:.4}));
  p.position.set(tx,top+.6,z0+.118);par.add(p);
  of3Plant(par,x0+W-.24,top,z0+.26,true);of3Plant(par,x0+.25,top,z0+D-.26,false);
}
/* The lounge: sofa, coffee bar, arcade, a foosball table and bean bags. The guard's
   armchair and the pet sitter are the Office's own regulars (OF_EXTRAS). */
function of3Lounge(par,r,i,col,decor,R){
  const T=OF3.T,{W,D,x0,z0,cx,cz,top}=R;
  of3Window(par,x0+.3,x0+W-.25,top+.42,top+.86,z0+.085,'x');
  of3Rug(par,cx,top,cz+.1,W*.55,col);
  const sofa=of3Mat('sofa:'+col,{color:of3Hex(col,['#3b2f4a',.35])});
  of3Box(par,1.3,.16,.46,sofa,x0+.95,top+.12,z0+.5);of3Box(par,1.3,.34,.12,sofa,x0+.95,top+.25,z0+.3);
  of3Box(par,.12,.25,.46,sofa,x0+.3,top+.16,z0+.5);of3Box(par,.12,.25,.46,sofa,x0+1.6,top+.16,z0+.5);
  of3Box(par,.6,.04,.4,of3Mat('ctable',{color:'#c9a77c'}),x0+.95,top+.22,z0+1.05);
  const g=officeExtra('guard');
  if(g){const ax=g.x/OF3_U,az=g.y/OF3_U,arm=of3Mat('armchair',{color:'#4b5563'});
    of3Box(par,.5,.2,.44,arm,ax,top+.1,az-.06);of3Box(par,.5,.5,.12,arm,ax,top+.25,az-.26);
    of3Box(par,.1,.3,.44,arm,ax-.26,top+.2,az-.06);of3Box(par,.1,.3,.44,arm,ax+.26,top+.2,az-.06)}
  // the coffee bar along the left wall
  const bar=of3Mat('bar',{color:'#2b2f3f',roughness:.5});
  of3Box(par,.36,.36,1.0,bar,x0+.26,top+.18,z0+D*.62);of3Box(par,.4,.03,1.04,of3Mat('walnut',{color:'#5b3a29',roughness:.45}),x0+.26,top+.375,z0+D*.62,false);
  if(decor.includes('coffee')){of3Box(par,.22,.26,.2,of3Mat('coffee',{color:'#cbd5e1',metalness:.4,roughness:.3}),x0+.24,top+.52,z0+D*.5);
    of3Box(par,.05,.05,.02,of3Mat('coffeeled',{color:'#fca5a5',emissive:'#ef4444',emissiveIntensity:2}),x0+.36,top+.55,z0+D*.5,false)}
  if(decor.includes('arcade')){of3Box(par,.4,.9,.36,of3Mat('arcade',{color:'#4c1d95'}),x0+W-.32,top+.45,z0+.35);
    of3Box(par,.3,.24,.02,of3Mat('arcadescr',{color:'#111',emissive:'#22d3ee',emissiveIntensity:1.4}),x0+W-.32,top+.66,z0+.54,false)}
  // foosball
  const fx=x0+W*.66,fz=z0+D*.4,green=of3Mat('pitch',{color:'#15803d',roughness:.8});
  of3Box(par,.7,.05,.4,green,fx,top+.36,fz);of3Box(par,.74,.08,.44,of3Mat('walnut',{}),fx,top+.33,fz,false);
  [-.26,.26].forEach(x=>[-.15,.15].forEach(z=>of3Box(par,.04,.32,.04,leg3(),fx+x,top+.16,fz+z,false)));
  [-.2,-.07,.07,.2].forEach((x,k)=>of3Box(par,.012,.012,.6,of3Mat('rod',{color:'#cbd5e1',metalness:.6}),fx+x,top+.42,fz,false));
  of3Beanbag(par,x0+W*.4,top,z0+D-.45,col);
  of3Plant(par,x0+W-.24,top,z0+D-.26,true);
  function leg3(){return of3Mat('leg',{color:'#3b3f55'})}
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
/* What covers the picture, in pixels: in Office HQ the dock below, and the prompt bar
   with its answers. On a wide screen those are a column on the right (of3Docked), so
   the office plays out on the left while the conversation runs beside it; on a phone
   the bar sits above the ring. Nothing elsewhere. */
function of3Docked(){return of3HQ()&&innerWidth>900&&document.body.classList.contains('imm-hq')}
function of3Pads(){
  if(!of3HQ()||!OF3.cv)return {t:0,b:0,l:0,r:0};
  const box=OF3.cv.getBoundingClientRect(),top=box.top,bar=document.getElementById('omnibar'),dock=document.getElementById('taskbar');
  const r=bar&&bar.offsetParent?bar.getBoundingClientRect():null,d=dock&&dock.offsetParent?dock.getBoundingClientRect():null;
  const b=d?Math.max(0,OF3.ch-(d.top-top)+10):100;
  if(of3Docked()&&r)return {t:24,b,l:0,r:Math.max(0,box.right-r.left+16)};
  return {t:r?Math.max(0,r.bottom-top+18):60,b,l:0,r:0};
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
  const fw=Math.max(.3,(OF3.cw-pad.l-pad.r)/Math.max(1,OF3.cw));
  const h=Math.max((y1-y0)/2/fh,(x1-x0)/2/(asp*fw))*1.05,k=2*h/Math.max(1,OF3.ch);
  // the picture's middle goes in the middle of what is left uncovered
  const g=of3Ground((x0+x1)/2+(pad.r-pad.l)/2*k,(y0+y1)/2+(pad.t-pad.b)/2*k);
  return {x:g.x,z:g.z,h};
}
/* One room filling what is left of the screen. `bare` leaves no space for the list of
   who is in it (the camera following the work, of3Follow). In Office HQ with the
   conversation docked on the right, the list goes on the left. */
function of3RoomView(name,bare){
  const r=OFFICE.L.rooms.find(q=>q.name===name);if(!r)return OF3.fit;
  const b=of3Basis(),cw=OF3.cw,ch=OF3.ch,asp=cw/Math.max(1,ch);
  let x0=1e9,x1=-1e9,y0=1e9,y1=-1e9;
  [[r.x,r.y],[r.x+r.w,r.y],[r.x,r.y+r.h],[r.x+r.w,r.y+r.h]].forEach(q=>[0,OF3_SLAB+OF3_WALL+.25].forEach(h=>{
    const x=q[0]/OF3_U,z=q[1]/OF3_U,sx=x*b.right.x+z*b.right.z,sy=x*b.up.x+h*b.up.y+z*b.up.z;
    x0=Math.min(x0,sx);x1=Math.max(x1,sx);y0=Math.min(y0,sy);y1=Math.max(y1,sy)}));
  // the list of who is in the room covers the right of a wide window, and the bottom of a
  // phone: the room fits in what is left, centred there
  const pad=of3Pads(),phone=cw<=640,list=phone||bare?0:Math.min(280,cw*.3),under=(phone&&!bare?ch*.46:0)+pad.b,over=pad.t;
  const L=pad.l+(of3Docked()?list:0),R=pad.r+(of3Docked()?0:list);
  const fw=Math.max(.25,(cw-L-R-24)/cw),fh=Math.max(.25,(ch-under-over-16)/ch);
  const h=Math.max((y1-y0)/2/fh,(x1-x0)/2/(asp*fw))*(bare?1.3:1.08);
  const k=2*h/ch;   // world units per pixel
  const g=of3Ground((x0+x1)/2+(R-L)/2*k,(y0+y1)/2-(under-over)/2*k);
  return {x:g.x,z:g.z,h};
}
function of3Fit(){
  if(!OF3.T||!OFFICE.L)return;
  OF3.fit=of3FitView();
  of3Frame(OF3.focus?of3RoomView(OF3.focus):OF3.follow?of3RoomView(OF3.follow,true):OF3.fit);
}
function of3Go(view,ms){
  const from=OF3.view||view;
  if(OFFICE.static||!ms){of3Frame(view);officeKick();return}
  OF3.anim={from:{...from},to:view,at:performance.now(),ms};officeKick();
}
function of3Focus(name){
  OF3.focus=name||null;OF3.cardSig='';OF3.follow='';if(!name)OF3.userMoved=false;
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
  cv.addEventListener('wheel',e=>{if(!OF3.view)return;e.preventDefault();of3Wheel(e)},{passive:false});
  cv.addEventListener('pointerdown',e=>{if(e.pointerType==='touch')return;OF3.drag={x:e.clientX,y:e.clientY,v:{...OF3.view}};OF3.dragged=false});
  addEventListener('pointerup',()=>{OF3.drag=null});
  cv.addEventListener('pointermove',e=>{const d=OF3.drag;if(!d||!OF3.view)return;
    const dx=e.clientX-d.x,dy=e.clientY-d.y;if(Math.hypot(dx,dy)>4)OF3.dragged=true;if(!OF3.dragged)return;
    const k=2*d.v.h/OF3.ch,g=of3Ground(-dx*k,dy*k);
    OF3.anim=null;OF3.userMoved=true;OF3.follow='';of3Frame({x:d.v.x+g.x,z:d.v.z+g.z,h:d.v.h});officeKick()});
  if(O.w&&O.w.el)O.w.el.addEventListener('keydown',e=>{if(e.key==='Escape'&&OF3.focus){of3Focus(null);e.stopPropagation()}});
}
/* Zoom: in close enough to see one desk (OF3_ZOOM_MIN, was 1.2, a room at most), out to
   a little past the whole office. Tapping a room's card is the way into a department. */
var OF3_ZOOM_MIN=.55;
function of3Zoom(f,ms){
  if(!OF3.view)return;
  const v={...OF3.view,h:Math.max(OF3_ZOOM_MIN,Math.min((OF3.fit?OF3.fit.h:8)*1.6,OF3.view.h*f))};
  OF3.userMoved=true;OF3.follow='';
  if(ms){of3Go(v,ms)}else{OF3.anim=null;of3Frame(v);officeKick()}
}
function of3Wheel(e){of3Zoom(e.deltaY>0?1.1:1/1.1)}
/* ＋ − ⤢ on the picture: the same zoom for a finger, a keyboard and a screen reader. */
function of3Controls(){
  if(!OF3.ui||OF3.ui.querySelector('.of3-zoom'))return;
  const z=document.createElement('div');z.className='of3-zoom';z.setAttribute('role','group');z.setAttribute('aria-label','Zoom the office');
  z.innerHTML='<button class="of3-zb" data-z="in" title="Zoom in" aria-label="Zoom in">+</button>'
    +'<button class="of3-zb" data-z="out" title="Zoom out" aria-label="Zoom out">−</button>'
    +'<button class="of3-zb" data-z="fit" title="The whole office" aria-label="Show the whole office">⤢</button>';
  z.onclick=e=>{const b=e.target.closest('[data-z]');if(!b)return;
    const k=b.dataset.z;if(k==='fit'){of3Focus(null);return}of3Zoom(k==='in'?1/1.35:1.35,OFFICE.static?0:220)};
  OF3.ui.appendChild(z);
}
/* Office HQ is under the desktop, so the canvas never sees the wheel: the desktop's own
   background passes it on, while nothing else is under the pointer. */
if(typeof document!=='undefined'&&document.addEventListener)document.addEventListener('wheel',e=>{
  if(!of3HQ()||!OF3.view||document.body.classList.contains('has-win'))return;
  if(typeof deckScrollOn==='function'&&deckScrollOn())return;    // the person chose wheel = faces
  const t=e.target;if(!t||!t.closest||t.closest('#omnibar,#omnicards,#taskbar,#menubar,.win,.ats,.approval,#toasts,#deck,.of3-roster,.ctx'))return;
  if(!t.closest('#desktop,#wall'))return;
  e.preventDefault();of3Wheel(e);
},{passive:false});
/* The camera follows the work in Office HQ: when one department is working it glides to
   that room, and back to the whole office a few seconds after the work ends. Several
   at once, and it shows them all. Never when the person moved the camera themselves or
   is looking inside a room. Only events move it: the room counts come from the cards. */
function of3Follow(rows){
  if(!of3HQ()||OF3.focus||OF3.userMoved||!OF3.fit||OFFICE.static)return;
  const busy=rows.filter(x=>x.run&&x.r.kind!=='lead'&&x.r.kind!=='lounge'&&x.r.kind!=='meeting').map(x=>x.r.name);
  const now=performance.now();
  if(busy.length)OF3.followAt=now;
  const want=busy.length===1?busy[0]:'';
  if(!want&&!busy.length&&OF3.follow&&now-(OF3.followAt||0)<6000)return;   // hold a moment
  if(want===(OF3.follow||''))return;
  OF3.follow=want;
  of3Go(want?of3RoomView(want,true):OF3.fit,900);
}
function of3Project(v3){
  const p=v3.clone().project(OF3.cam);
  return {x:(p.x+1)/2*OF3.cw,y:(1-p.y)/2*OF3.ch,z:p.z};
}
/* Just over somebody's head, where a balloon or a burst is pinned. */
function of3Head(p){return of3W(p.x,p.y,OF3_SLAB+.68*(p.lead?1.1:1))}
function of3Tap(e){
  const O=OFFICE;if(!OF3.cam||!O.L)return;
  // the tap in the picture's own pixels, however the canvas is stretched on screen
  const r=OF3.cv.getBoundingClientRect(),x=(e.clientX-r.left)*OF3.cw/Math.max(1,r.width),y=(e.clientY-r.top)*OF3.ch/Math.max(1,r.height);
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
/* ---------------- people: the painter's pixels, wrapped round boxes ----------------
   A person is a little figure of boxes (head, body, two arms, two legs) and every side
   of every box is cut from the server's body sheet: front, blink, back and side, painted
   by avatars.py from the same recipe as every face on this machine. So there is still
   one painter; this file only decides which of its pixels go on which side of which
   box, and turns the figure the way the person is facing. Sizes are in the painter's
   pixels (16 x 26 a frame), OF3_PX world units each. */
var OF3_PX=.026;
/* A rect of one frame of the body sheet (0 front, 1 blink, 2 back, 3 side) as UVs. */
function of3UV(view,x0,y0,x1,y1,flip){
  const o=view*16;let u0=(o+x0)/64,u1=(o+x1)/64;if(flip){const t=u0;u0=u1;u1=t}
  return [u0,1-y1/26,u1,1-y0/26];
}
/* A box w x h x d (pixels) whose six sides show the given rects, centred at (ox, oy, oz). */
function of3Part(w,h,d,faces,ox,oy,oz){
  const P=OF3_PX,g=new OF3.T.BoxGeometry(w*P,h*P,d*P),uv=g.attributes.uv;
  ['px','nx','py','ny','pz','nz'].forEach((f,i)=>{const r=faces[f]||faces.all;
    for(let k=0;k<4;k++){const j=i*4+k,a=uv.getX(j),b=uv.getY(j);uv.setXY(j,r[0]+(r[2]-r[0])*a,r[1]+(r[3]-r[1])*b)}});
  g.translate((ox||0)*P,(oy||0)*P,(oz||0)*P);
  return g;
}
/* Hair that stands off the head (a bun, long hair down the back), in the hair's colour. */
function of3HairParts(style){
  const H=of3UV(2,6,5,9,7),all={all:H},P=[];
  if(style==='bald')return P;
  if(style==='curly'){P.push(of3Part(10,3,10,all,0,9,0));return P}
  if(style==='spiky'){[-2.5,0,2.5].forEach((x,i)=>P.push(of3Part(2,2,2,all,x,10.5,(i-1)*1.5)));P.push(of3Part(8,1,8,all,0,9.5,0));return P}
  P.push(of3Part(8,1,8,{all:H,pz:of3UV(0,4,2,12,3)},0,9.5,0));
  if(style==='bun')P.push(of3Part(4,3,4,all,0,11,-2.5));
  if(style==='long'||style==='bob'){const h=style==='long'?10:7,oy=style==='long'?3:4.5;
    P.push(of3Part(10,h,1,all,0,oy,-4.5),of3Part(1,h-1,6,all,-4.5,oy+.5,-1),of3Part(1,h-1,6,all,4.5,oy+.5,-1))}
  return P;
}
function of3HeadGeo(style,blink){
  return of3Geo('head:'+style+(blink?':b':''),()=>of3Merge([
    of3Part(8,9,8,{pz:of3UV(blink?1:0,4,3,12,12),nz:of3UV(2,4,3,12,12),px:of3UV(3,4,3,12,12,true),nx:of3UV(3,4,3,12,12),
      py:of3UV(2,5,3,11,6),ny:of3UV(0,7,12,9,13)},0,4.5,0),...of3HairParts(style)]));
}
function of3BodyGeo(part){
  return of3Geo('body:'+part,()=>{
    if(part==='torso')return of3Part(8,6,4,{pz:of3UV(0,4,13,12,19),nz:of3UV(2,4,13,12,19),px:of3UV(3,6,13,10,19,true),
      nx:of3UV(3,6,13,10,19),py:of3UV(0,5,14,11,15),ny:of3UV(0,5,19,11,20)},0,9,0);
    if(part==='armL'||part==='armR'){const L=part==='armL',a=L?2:12,b=L?12:2;
      return of3Part(2,5,2,{pz:of3UV(0,a,13,a+2,18),nz:of3UV(2,b,13,b+2,18),px:of3UV(0,a,13,a+1,18),nx:of3UV(0,a,13,a+1,18),
        py:of3UV(0,a,13,a+2,14),ny:of3UV(0,a,17,a+2,18)},0,-2.5,0)}
    const L=part==='legL',a=L?5:8,b=L?8:5,s=L?4:8,sb=L?8:4;
    return of3Merge([
      of3Part(3,4,3,{pz:of3UV(0,a,19,a+3,23),nz:of3UV(2,b,19,b+3,23),px:of3UV(3,6,19,9,23,true),nx:of3UV(3,6,19,9,23),
        py:of3UV(0,a,19,a+3,20),ny:of3UV(0,a,22,a+3,23)},0,-2,0),
      of3Part(4,2,4,{pz:of3UV(0,s,23,s+4,25),nz:of3UV(2,sb,23,sb+4,25),px:of3UV(3,6,23,10,25,true),nx:of3UV(3,6,23,10,25),
        py:of3UV(0,4,23,6,24),ny:of3UV(0,4,23,6,24)},L?-.5:.5,-5,.5)]);
  });
}
function of3Figure(p){
  const T=OF3.T,src=p.recipe?avatarRecipeSrc(p.recipe,{body:1}):avatarSrc(p.key,{body:1});
  let f=OF3.sp[p.key];
  if(f&&f.src===src)return f;
  if(f){OF3.scene.remove(f.root);OF3.scene.remove(f.shadow);f.tex.dispose();f.mat.dispose()}
  const tex=new T.TextureLoader().load(src,()=>officeKick());
  tex.magFilter=tex.minFilter=T.NearestFilter;tex.generateMipmaps=false;tex.colorSpace=T.SRGBColorSpace;
  const mat=new T.MeshStandardMaterial({map:tex,roughness:.85});
  const rec=p.recipe||((AVATARS.by||{})[p.key]||{}).recipe||{},style=rec.style||'short',P=OF3_PX;
  const root=new T.Group(),body=new T.Group();root.add(body);
  // only the head and body cast a shadow: arms and legs add draws for no visible shade
  const mesh=(geo,par,cast)=>{const m=new T.Mesh(geo,mat);if(OF3.hq&&cast)m.castShadow=true;par.add(m);return m};
  const piv=(x,y)=>{const g=new T.Group();g.position.set(x*P,y*P,0);body.add(g);return g};
  mesh(of3BodyGeo('torso'),body,1);
  const head=piv(0,13),armL=piv(-5,12),armR=piv(5,12),legL=piv(-1.5,6),legR=piv(1.5,6);
  const face=mesh(of3HeadGeo(style,0),head,1),blink=mesh(of3HeadGeo(style,1),head,1);blink.visible=false;
  mesh(of3BodyGeo('armL'),armL);mesh(of3BodyGeo('armR'),armR);mesh(of3BodyGeo('legL'),legL);mesh(of3BodyGeo('legR'),legR);
  const shadow=new T.Mesh(new T.PlaneGeometry(.42,.2),new T.MeshBasicMaterial({map:of3Shadow(),transparent:true,depthWrite:false}));
  shadow.rotation.x=-Math.PI/2;OF3.scene.add(shadow);OF3.scene.add(root);
  return OF3.sp[p.key]={root,body,head,armL,armR,legL,legR,face,blink,mat,tex,src,shadow,yaw:null,cur:null};
}
/* Sitting down: at a desk (facing it, turned a little into the room when not working,
   so you see who it is), at the meeting table, or the guard in the armchair. */
function of3SeatOf(p){
  const O=OFFICE;
  if(p.recipe)return p.role==='guard'?{yaw:0}:null;
  if(p.mode==='seat'&&!p.bench&&p.home&&p.home.fx!==undefined){
    const r=p.room,k=r&&r.seats?r.seats.indexOf(p.key):-1,i=r?O.L.rooms.indexOf(r):-1;
    let yaw=Math.atan2(p.home.fx,p.home.fy);
    if(!(p.busy||p.hand||p.home.boss)&&r){
      let d=Math.atan2(r.cx-p.x,r.cy-p.y)-yaw;while(d>Math.PI)d-=2*Math.PI;while(d<-Math.PI)d+=2*Math.PI;
      yaw+=Math.max(-.9,Math.min(.9,d*.5));
    }
    return {yaw,desk:true,chair:OF3.chairs[p.key==='@agent'?'lead':i+':'+k]};
  }
  const t=OF3.table;
  if(t&&p.mode==='stand'){const s=t.spots.find(q=>Math.hypot(q.x-p.x,q.y-p.y)<8);if(s)return {yaw:s.yaw,chair:OF3.chairs['meet:'+s.k]}}
  return null;
}
/* Who somebody standing about is looking at. */
function of3LookAt(p){
  const O=OFFICE,v=p.visit;
  if(v&&v.to&&O.people[v.to]){const q=O.people[v.to];return {x:q.x,y:q.y}}
  if(p.hand){const l=O.people['@agent'];if(l&&l!==p)return {x:l.x,y:l.y}}
  if(p.role==='sitter'&&O.pet)return {x:O.pet.x,y:O.pet.y};
  return null;
}
function of3Turn(a,b,k){let d=b-a;while(d>Math.PI)d-=2*Math.PI;while(d<-Math.PI)d+=2*Math.PI;return a+d*Math.min(1,k)}
function of3People(now){
  const O=OFFICE,seen=new Set(),all=[...Object.values(O.people),...(O.extras||[])],t=now/1000,still=O.static;
  const dt=Math.min(.1,Math.max(0,(now-(OF3.lastT||now))/1000));OF3.lastT=now;
  all.forEach(p=>{
    if(!(p.recipe||of3Shown(p))){const f=OF3.sp[p.key];if(f){f.root.visible=false;f.shadow.visible=false}return}
    const f=of3Figure(p);seen.add(p.key);
    const seat=of3SeatOf(p),walking=p.mode==='walk'&&!still,{frame,bob}=officeFrameOf(p,!!seat);
    let yaw=f.yaw;
    if(walking){const dx=p.x-(f.px===undefined?p.x:f.px),dz=p.y-(f.pz===undefined?p.y:f.pz);if(Math.hypot(dx,dz)>.05)yaw=Math.atan2(dx,dz)}
    else if(seat)yaw=seat.yaw;
    else{const q=of3LookAt(p);if(q&&Math.hypot(q.x-p.x,q.y-p.y)>1)yaw=Math.atan2(q.x-p.x,q.y-p.y)}
    if(yaw===null||yaw===undefined)yaw=Math.PI/4;      // nothing to look at: towards you
    f.px=p.x;f.pz=p.y;f.yaw=yaw;
    f.cur=f.cur===null||still?yaw:of3Turn(f.cur,yaw,dt*7);
    f.root.scale.setScalar(p.lead?1.1:1);
    f.root.position.copy(of3W(p.x,p.y,OF3_SLAB));f.root.rotation.y=f.cur;
    const ph=p.phase||0,sw=walking?Math.sin(t*11+ph):0;
    f.body.position.y=(walking?Math.abs(sw)*.014:0)+bob*.012;
    f.face.visible=frame!==1;f.blink.visible=frame===1;
    if(seat){f.legL.rotation.x=f.legR.rotation.x=-Math.PI/2}
    else{f.legL.rotation.x=sw*.6;f.legR.rotation.x=-sw*.6}
    const busy=!!(p.busy&&seat&&seat.desk&&!still);
    let aL=0,aR=0,zR=0;
    if(p.hand){aR=-Math.PI+.3;zR=-.25;aL=seat?-.6:0}
    else if(busy){aL=-1.2+Math.sin(t*17+ph)*.09;aR=-1.2+Math.sin(t*15+ph+1.7)*.09}
    else if(seat&&seat.desk&&!p.home.boss)aL=aR=-.35;
    else if(seat)aL=aR=-.6;
    else if(walking){aL=-sw*.55;aR=sw*.55}
    f.armL.rotation.set(aL,0,0);f.armR.rotation.set(aR,0,zR);
    // the head: down at the screen while working, a slow look round when not, a nod
    // while speaking. Small and slow, the World's rule for being alive at rest.
    const look=busy||still?0:Math.sin(t*.35+ph)*.3;
    f.head.rotation.set(busy?.16:(p.say&&!still?Math.sin(t*8)*.07:0),look,0);
    if(seat&&seat.chair)seat.chair.rotation.y=f.cur;
    f.root.visible=true;
    f.shadow.visible=!seat;f.shadow.position.copy(of3W(p.x,p.y,OF3_SLAB+.012));
  });
  Object.keys(OF3.sp).forEach(k=>{if(!seen.has(k)){OF3.sp[k].root.visible=false;OF3.sp[k].shadow.visible=false}});
  // an empty desk's chair faces its desk
}
/* A screen is bright and its code scrolls while the person at that desk works; asleep
   it is dim. In the department's colour. */
function of3Screens(now){
  const O=OFFICE;
  OF3.screens.forEach(s=>{
    const r=O.L.rooms[s.room];if(!r)return;
    const key=s.key||(r.seats||[])[s.seat],p=key&&O.people[key];
    const lit=!!(p&&p.busy&&!p.bench),want=lit?.95:.16;
    s.mats.forEach(m=>{if(Math.abs(m.emissiveIntensity-want)>.01)m.emissiveIntensity=want;
      if(lit&&!O.static)m.map.offset.y=(m.map.offset.y+.0035)%.45});
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
  const o=OF3.off||{x:0,y:0,sx:1,sy:1};
  const t=`translate(${Math.round(x*(o.sx||1)+(dx||0)+o.x)}px,${Math.round(y*(o.sy||1)+(dy||0)+o.y)}px)${an}`;
  if(e._t!==t){e.style.transform=t;e._t=t}
}
function of3Overlay(now){
  const O=OFFICE;if(!OF3.ui)return;
  Object.values(OF3.el).forEach(e=>e._seen=0);
  of3Where();
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
    const y0=f.y+(p.mode==='seat'&&!p.bench?14:4),w=e.offsetWidth||60;
    // a crowd round one table steps its names up as well as down, so they stay in the room
    const hit=y=>tags.some(q=>Math.abs(q.x-f.x)<(q.w+w)/2&&Math.abs(q.y-y)<15);
    let y=y0;for(const dy of [15,-15,30,-30])if(hit(y))y=y0+dy;else break;
    tags.push({x:f.x,y,w});of3Place(e,f.x,y,0,0,'t');
  });
  // balloons, newest on top, each placed clear of the ones already placed
  const placed=[];
  Object.values(O.people).filter(p=>p.say&&of3Shown(p)).sort((a,b2)=>b2.say.at-a.say.at).forEach(p=>{
    const s=p.say,age=(now-s.at)/s.ms,h=of3Project(of3Head(p));
    let t=s.text;if(t.length>110)t=t.slice(0,108).replace(/\s+\S*$/,'')+'…';
    const e=of3El('say:'+p.key,'of3-say '+s.kind,esc(t));
    e.style.opacity=age>.85?Math.max(0,(1-age)/.15):1;
    const w=e.offsetWidth||120,hh=e.offsetHeight||30,vis=(OF3.off||{}).vis;let x=h.x-w/2,y=h.y-hh-12;
    if(vis&&vis.r-vis.l>w+12)x=Math.max(vis.l+6,Math.min(x,vis.r-w-6));
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
    return {r,ms,run,wait:s.waiting||0,flag:s.flagged||0,held:s.held||0,up:s.reports_to||''};
  });
  const sig=JSON.stringify([rows.map(x=>[x.r.name,x.ms.length,x.run,x.wait,x.flag,x.held,x.up,x.ms.slice(0,3)]),OF3.focus]);
  if(force||sig!==OF3.cardSig){
    OF3.cardSig=sig;
    rows.forEach((x,i)=>{
      const r=x.r,col=O.view.colors[r.color]||'#94a3b8';
      const kind=r.kind==='meeting'?'huddles gather here':r.kind==='lounge'?'take a break':
        `${x.ms.length} ${x.ms.length===1?'agent':'agents'}${x.run?` · <em>${x.run} running</em>`:''}`;
      const faces=x.ms.slice(0,3).map(m=>typeof avatarImg==='function'?avatarImg(m,'of3-face'):'').join('')+(x.ms.length>3?`<span class="of3-more">+${x.ms.length-3}</span>`:'');
      const tip=`${r.name}: ${x.ms.length} ${x.ms.length===1?'agent':'agents'}, ${x.run} working${x.wait?`, ${x.wait} waiting for you`:''}${x.held?`, ${x.held} held at sign-off`:''}${x.up?`. Reports to ${x.up}`:''}. Tap to look inside.`;
      const e=of3El('card:'+i,'of3-card'+(x.run?' busy':'')+(OF3.focus===r.name?' on':''),
        `<i style="background:${col}"></i><b>${esc(r.name)}</b><span class="of3-k">${x.run?'<span class="of3-dot"></span>':''}${kind}</span>`
        +(faces?`<span class="of3-faces">${faces}</span>`:'')
        +(x.wait?`<span class="of3-w">⚠ ${x.wait}</span>`:'')+(x.held?`<span class="of3-w">↩ ${x.held}</span>`:'')+(x.flag?`<span class="of3-w fl">⚑ ${x.flag}</span>`:''));
      e.title=tip;e.setAttribute('role','button');e.setAttribute('aria-label',tip);e.tabIndex=0;
      e.onclick=()=>of3Focus(OF3.focus===r.name?null:r.name);
      e.onkeydown=ev=>{if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();e.onclick()}};
    });
    Object.keys(OF3.el).forEach(k=>{if(k.startsWith('card:')&&+k.slice(5)>=rows.length){OF3.el[k].remove();delete OF3.el[k]}});
  }
  // over the room: centred on it, standing on its highest point (the back corner's wall)
  of3Follow(rows);
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
