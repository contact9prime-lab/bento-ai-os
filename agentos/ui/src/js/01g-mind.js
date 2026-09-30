/* ================= the Mind scene =================
   Settings → Appearance → Scene → Mind. Your lead is the glowing core; around it sit
   Memory, Knowledge, Missions and one cluster per specialist, and every filament is a
   real connection: a memory it keeps, an entity in the graph, a skill, a run this week.
   Asked for with a video of a brain on a wall screen: "get into the brains of our
   agents and their data and how that is interconnected".

   The Office's rule holds here: nothing moves that did not happen. The picture comes
   from /api/mind (agentos/mind.py), a spark runs out along a filament only when the
   websocket says something ran (scenePulse, the one seam), two agents' link lights
   only when one asked the other, and the core swells with the voice (the js-* phases
   Jarvis already sets). The clusters turning slowly is scenery, like the aurora.

   The side panels are the same snapshot in numbers, and "Tell me" says them aloud
   through speakAs, so the voice never claims what the screen does not show.

   Cost, measured in mindFrame (MIND.ms): at most 30 frames a second while the core is
   awake or a spark is travelling, 12 at rest, none while covered (crewCovered) or
   hidden, one still frame under reduced motion. Filaments are one stroke per cluster
   and every glow is a cached sprite, so a frame is a few dozen draw calls plus one
   drawImage per node, and never a filter.

   Faces: GUI and SUI are this page. The TUI gets `bento mind`, which prints the same
   snapshot: the hubs, their counts and the spoken summary. The drawing itself has no
   terminal form. */
var MIND={on:false,snap:null,host:null,ui:null,cv:null,ctx:null,raf:0,last:0,fetchT:0,pollT:0,snooze:0,
  still:false,peace:mindPeaceStored(),W:0,H:0,dpr:1,energy:.25,sparks:[],glints:[],ripples:[],gAcc:0,lastPk:0,
  flare:{},layout:null,sprites:{},bg:null,ms:0,open:'',telling:false,t0:0,prevT:0,P:[],Q:[]};

function mindStart(){
  if(MIND.on)return;
  const wall=document.getElementById('wall'),desk=document.getElementById('desktop');if(!wall||!desk)return;
  MIND.on=true;MIND.t0=performance.now();
  MIND.still=matchMedia('(prefers-reduced-motion: reduce)').matches;
  let host=document.getElementById('mind-scene');
  if(!host){host=document.createElement('div');host.id='mind-scene';host.setAttribute('aria-hidden','true');
    host.innerHTML='<canvas class="mn-cv"></canvas>';wall.appendChild(host)}
  let ui=document.getElementById('mind-ui');
  if(!ui){ui=document.createElement('div');ui.id='mind-ui';
    const home=document.getElementById('home');desk.insertBefore(ui,home?home.nextSibling:null)}
  MIND.host=host;MIND.ui=ui;MIND.cv=host.querySelector('canvas');MIND.ctx=MIND.cv.getContext('2d');
  // every tag, team row and the card's close carry data-hub; one listener reads it
  ui.onclick=e=>{const b=e.target.closest('[data-hub]');if(b)mindCard(b.dataset.hub)};
  ui.innerHTML='<div class="mn-top"></div><div class="mn-say" hidden></div><div class="mn-tags"></div>'+
    '<div class="mn-left"></div><div class="mn-right"></div><div class="mn-card" hidden></div>';
  addEventListener('resize',mindResize);
  document.addEventListener('visibilitychange',mindKick);
  mindPeaceApply();
  mindResize();
  mindFetch();
}
/* Peace: only the mind. Asked for as "too much is happening on the screen; it can just be
   simple and show the mind". The panels, the names, the card and the prompt bar step
   aside (Ctrl+Space still brings the bar), and one quiet button brings them back.
   Remembered by this browser, like the scene. */
function mindPeaceStored(){try{return localStorage.getItem('mind.peace')==='1'}catch(e){return false}}
function mindPeaceApply(){
  if(MIND.ui)MIND.ui.classList.toggle('peace',!!MIND.peace);
  document.body.classList.toggle('mind-peace',!!MIND.peace&&MIND.on);
}
function mindPeace(on){
  MIND.peace=typeof on==='boolean'?on:!MIND.peace;
  try{localStorage.setItem('mind.peace',MIND.peace?'1':'0')}catch(e){}
  if(MIND.peace&&MIND.open){MIND.open='';const c=MIND.ui&&MIND.ui.querySelector('.mn-card');if(c)c.hidden=true;MIND.ui.classList.remove('carded')}
  mindPeaceApply();mindPaintUI();mindLayout();mindKick();
}
function mindStop(){
  if(!MIND.on)return;
  MIND.on=false;
  cancelAnimationFrame(MIND.raf);MIND.raf=0;
  clearTimeout(MIND.fetchT);clearTimeout(MIND.pollT);clearTimeout(MIND.snooze);
  removeEventListener('resize',mindResize);
  document.removeEventListener('visibilitychange',mindKick);
  if(MIND.telling&&typeof speechStop==='function')speechStop();
  document.body.classList.remove('mind-peace');
  if(MIND.host)MIND.host.remove();if(MIND.ui)MIND.ui.remove();
  MIND.host=MIND.ui=MIND.cv=MIND.ctx=null;MIND.snap=null;MIND.sparks=[];MIND.glints=[];MIND.ripples=[];MIND.layout=null;MIND.bg=null;MIND.open='';MIND.telling=false;
}
/* The picture, once now, again a second or so after things happen, and once a minute
   so a memory saved from a phone shows up without an event of its own. */
async function mindFetch(){
  if(!MIND.on)return;
  clearTimeout(MIND.pollT);
  try{
    const r=await fetch('/api/mind');
    if(r.ok){const s=await r.json();if(!MIND.on)return;MIND.snap=s;mindLayout();mindPaintUI()}
  }catch(e){}
  if(MIND.on)MIND.pollT=setTimeout(mindFetch,60000);
  mindKick();
}
function mindSoon(ms){clearTimeout(MIND.fetchT);MIND.fetchT=setTimeout(mindFetch,ms||1500)}
function mindResize(){
  if(!MIND.on||!MIND.cv)return;
  const r=MIND.host.getBoundingClientRect();
  MIND.dpr=Math.min(2,devicePixelRatio||1);
  MIND.W=Math.max(1,r.width);MIND.H=Math.max(1,r.height);
  MIND.cv.width=Math.round(MIND.W*MIND.dpr);MIND.cv.height=Math.round(MIND.H*MIND.dpr);
  MIND.bg=null;mindLayout();mindPlaceTags();mindKick();
}

/* ---------- layout: fixed hubs on a ring, each cluster a small turning sphere ---------- */
function mindHash(s){let h=2166136261;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)}return h>>>0}
function mindRand(seed){let x=seed||1;return()=>{x^=x<<13;x^=x>>>17;x^=x<<5;return ((x>>>0)%100000)/100000}}
function mindPhone(){return MIND.W<700}
function mindLayout(){
  const S=MIND.snap;if(!S||!MIND.W){MIND.layout=null;return}
  const W=MIND.W,H=MIND.H,phone=mindPhone();
  // the ring fits between what is already on the screen: the prompt bar above, the dock
  // below and the two side panels, measured rather than assumed (a phone has no panels)
  const rect=id=>{const e=document.getElementById(id);if(!e)return null;const r=e.getBoundingClientRect();return r.width&&r.height?r:null};
  // in Peace the panels and the bar step aside, so the ring takes the room they left
  const bar=MIND.peace?null:rect('omnibar'),dock=rect('dock');
  const top=Math.max(phone?150:130,bar&&bar.bottom<H*.5?bar.bottom+48:0);
  const bottom=Math.min(H-(phone?80:100),dock&&dock.top>H*.5?dock.top-(phone?20:34):H);
  const side=phone?18:MIND.peace?60:W>=1000?272:24;
  const cx=W/2,cy=(top+bottom)/2;
  const rx=Math.max(90,Math.min(560,(W-2*side)/2-(phone?46:70))),ry=Math.max(70,(bottom-top)/2-(phone?34:48));
  const hubs={},order=S.hubs,step=Math.PI*2/Math.max(1,order.length);
  const byHub={};S.nodes.forEach(n=>{(byHub[n.hub]=byHub[n.hub]||[]).push(n)});
  order.forEach((h,i)=>{
    // not a clock face: each cluster is nudged round and in by its own seed, so the
    // ring reads as grown rather than placed ("too systematic", from a screenshot).
    // Never further out than the measured ring, so nothing lands under a panel.
    const R0=mindRand(mindHash(h.id)),a=-Math.PI*.82+i*step+(R0()-.5)*step*.4,far=.8+R0()*.2;
    const list=byHub[h.id]||[];
    const rh=Math.min(phone?60:110,(phone?16:24)+(phone?4:7)*Math.sqrt(list.length));
    const x=cx+Math.cos(a)*rx*far,y=cy+Math.sin(a)*ry*far;
    // dendrites: short branching arms reaching away from the core
    const den=[],arms=4+Math.floor(R0()*4),out=Math.atan2(y-cy,x-cx);
    for(let k=0;k<arms;k++){const ang=out+(R0()-.5)*3.4,len=(phone?16:26)+R0()*(phone?20:44);
      den.push({ang,len,w:mindWave(R0),fork:R0()<.7?(R0()<.5?-1:1)*(.4+R0()*.5):0,fl:.35+R0()*.35})}
    hubs[h.id]={h,i,x,y,a,rh,den,w:mindWave(R0),bend:(R0()-.5)*rh*1.4,spin:(i%2?-1:1)*(.00007+.00003*(i%3)),
      nodes:list.map(n=>{const R=mindRand(mindHash(n.id));
        // a point inside the sphere, biased outward so a cluster reads as a cloud
        const u=R()*2-1,th=R()*Math.PI*2,rr=Math.cbrt(.25+R()*.75),s=Math.sqrt(1-u*u);
        // one connection is drawn as a bundle of strands; the bundle is the one thing
        const bs=[];for(let b=0;b<6;b++)bs.push([R()*2-1,R()*2-1,R()*2-1]);
        return {n,lx:Math.cos(th)*s*rr,ly:u*rr,lz:Math.sin(th)*s*rr,j:R()*2-1,k:R(),bs,w:mindWave(R),
          amp:8+R()*18,flash:0,x:0,y:0,z:0}})};
  });
  const nodeAt={};Object.values(hubs).forEach(H=>H.nodes.forEach(p=>{nodeAt[p.n.id]=p;p.H=H}));
  // every link keeps its own wave, worked out once here rather than hashed per frame
  const lw=S.links.map(k=>mindWave(mindRand(mindHash(k.a+'>'+k.b+k.kind))));
  MIND.layout={cx,cy,rx,ry,hubs,nodeAt,lw,cr:(phone?24:30)};
  mindPlaceTags();
}
function mindProject(t){
  const L=MIND.layout;if(!L)return;
  Object.values(L.hubs).forEach(H=>{
    const a=(MIND.still?0:t)*H.spin+H.i,c=Math.cos(a),s=Math.sin(a);
    H.nodes.forEach(p=>{
      const x=p.lx*c-p.lz*s,z=p.lx*s+p.lz*c,d=1/(1.6-z*.45);
      p.x=H.x+x*H.rh*d;p.y=H.y+p.ly*H.rh*d*.9;p.z=z;
    });
  });
}

/* ---------- organic geometry ----------
   A fibre is a quadratic from A to B through Q, pushed off its line by two slow waves
   whose envelope is zero at both ends: it leaves the soma and reaches its node exactly,
   and wanders in between like an axon rather than an arc drawn with a compass. The
   waves drift with time, which is scenery (the clusters' turning is too). */
var MIND_N=9;
function mindWave(R){return [(1.1+R()*1.6)*Math.PI*2,(2.4+R()*2.2)*Math.PI*2,R()*6.3,R()*6.3,.15+R()*.4]}
function mindFibre(ax,ay,qx,qy,bx,by,w,amp,T,ph,out){
  const N=MIND_N;
  for(let i=0;i<N;i++){
    const s=i/(N-1),u=1-s;
    const x=u*u*ax+2*u*s*qx+s*s*bx,y=u*u*ay+2*u*s*qy+s*s*by;
    const tx=u*(qx-ax)+s*(bx-qx),ty=u*(qy-ay)+s*(by-qy),tl=Math.hypot(tx,ty)||1;
    const o=amp*Math.sin(Math.PI*s)*(Math.sin(s*w[0]+w[2]+ph+T*w[4])*.65+Math.sin(s*w[1]+w[3]-ph-T*w[4]*.7)*.35);
    out[i*2]=x-ty/tl*o;out[i*2+1]=y+tx/tl*o;
  }
  return out;
}
function mindTrace(g,P){
  const N=MIND_N;g.moveTo(P[0],P[1]);
  for(let i=1;i<N-1;i++)g.quadraticCurveTo(P[i*2],P[i*2+1],(P[i*2]+P[i*2+2])/2,(P[i*2+1]+P[i*2+3])/2);
  g.lineTo(P[N*2-2],P[N*2-1]);
}
/* where along a fibre a signal is, s from 0 (A) to 1 (B) */
function mindAt(P,s){
  const f=Math.max(0,Math.min(.9999,s))*(MIND_N-1),i=Math.floor(f),k=f-i;
  return [P[i*2]+(P[i*2+2]-P[i*2])*k,P[i*2+1]+(P[i*2+3]-P[i*2+1])*k];
}
/* the strand b of the connection core → node p, leaving the soma around its edge */
function mindNodeFibre(H,p,b,T,P){
  const L=MIND.layout,cx=L.cx,cy=L.cy,o=p.bs[b];
  const a=Math.atan2(p.y-cy,p.x-cx)+o[0]*.55,r=L.cr*(.55+.35*Math.abs(o[1]));
  const nx=-(H.y-cy),ny=H.x-cx,nl=Math.hypot(nx,ny)||1,bend=p.j*H.rh*.9+o[1]*H.rh*.55+H.bend*.5;
  const dl=Math.hypot(p.x-cx,p.y-cy);
  return mindFibre(cx+Math.cos(a)*r,cy+Math.sin(a)*r,cx+(H.x-cx)*.6+nx/nl*bend,cy+(H.y-cy)*.6+ny/nl*bend,
    p.x+o[2]*3,p.y+o[0]*3,p.w,p.amp*(1+o[2]*.3)*Math.min(1.4,dl/320),T,o[1]*.9,P);
}
/* the core → cluster trunk, for a cluster with nothing in it yet and for a real spark */
function mindHubFibre(H,T,P){
  const L=MIND.layout,cx=L.cx,cy=L.cy,a=Math.atan2(H.y-cy,H.x-cx);
  const nx=-(H.y-cy),ny=H.x-cx,nl=Math.hypot(nx,ny)||1;
  return mindFibre(cx+Math.cos(a)*L.cr*.6,cy+Math.sin(a)*L.cr*.6,cx+(H.x-cx)*.55+nx/nl*H.bend,cy+(H.y-cy)*.55+ny/nl*H.bend,
    H.x,H.y,H.w,18,T,0,P);
}

/* ---------- drawing ---------- */
function mindSprite(hue,sat,light){
  const key=hue+'/'+(sat||100)+'/'+(light||62);
  if(MIND.sprites[key])return MIND.sprites[key];
  const c=document.createElement('canvas');c.width=c.height=64;const g=c.getContext('2d');
  const gr=g.createRadialGradient(32,32,0,32,32,32);
  gr.addColorStop(0,`hsla(${hue},${sat||100}%,92%,1)`);
  gr.addColorStop(.18,`hsla(${hue},${sat||100}%,${light||62}%,.85)`);
  gr.addColorStop(.5,`hsla(${hue},${sat||100}%,${(light||62)-8}%,.18)`);
  gr.addColorStop(1,`hsla(${hue},${sat||100}%,50%,0)`);
  g.fillStyle=gr;g.fillRect(0,0,64,64);
  return MIND.sprites[key]=c;
}
function mindBackground(){
  const c=document.createElement('canvas');c.width=MIND.cv.width;c.height=MIND.cv.height;
  const g=c.getContext('2d'),W=c.width,H=c.height,L=MIND.layout;
  const cx=(L?L.cx:MIND.W/2)*MIND.dpr,cy=(L?L.cy:MIND.H/2)*MIND.dpr;
  const gr=g.createRadialGradient(cx,cy,0,cx,cy,Math.max(W,H)*.75);
  gr.addColorStop(0,'#101634');gr.addColorStop(.45,'#070a1c');gr.addColorStop(1,'#020308');
  g.fillStyle=gr;g.fillRect(0,0,W,H);
  // dust: fixed, faint, for depth; not data, so it never moves
  const R=mindRand(7);g.fillStyle='rgba(170,190,255,.35)';
  for(let i=0;i<Math.round(W*H/9000);i++){const s=R()*1.3*MIND.dpr;g.fillRect(R()*W,R()*H,s,s)}
  return c;
}
function mindEnergyTarget(){
  const b=document.body.classList;
  const talking=MIND.telling||b.contains('js-speaking')||(typeof SPEECH!=='undefined'&&SPEECH.audio&&!SPEECH.audio.paused)||
    (typeof speechSynthesis!=='undefined'&&speechSynthesis.speaking);
  if(talking)return {e:1,state:'speaking'};
  if(b.contains('js-thinking'))return {e:.85,state:'thinking'};
  if(b.contains('js-listening'))return {e:.65,state:'listening'};
  if(typeof RUNNING!=='undefined'&&RUNNING.size)return {e:.6,state:'working'};
  const busy=MIND.snap&&MIND.snap.team.some(t=>t.busy);
  return {e:busy?.45:.25,state:busy?'working':'quiet'};
}
function mindKick(){
  if(!MIND.on||MIND.raf)return;
  MIND.raf=requestAnimationFrame(mindFrame);
}
function mindFrame(now){
  MIND.raf=0;
  if(!MIND.on)return;
  if(typeof crewCovered==='function'&&crewCovered()){clearTimeout(MIND.snooze);MIND.snooze=setTimeout(mindKick,1000);return}
  const tgt=mindEnergyTarget();
  const lively=tgt.e>.3||MIND.sparks.length||Math.abs(MIND.energy-tgt.e)>.02;
  // at rest the glints still travel, and at 12 frames a second they stuttered
  const gap=1000/(lively?30:20);
  if(!MIND.still&&now-MIND.last<gap-2){MIND.raf=requestAnimationFrame(mindFrame);return}
  MIND.last=now;
  const t0=performance.now();
  MIND.energy+=(tgt.e-MIND.energy)*(MIND.still?1:.12);
  mindDraw(now-MIND.t0,tgt.state);
  MIND.ms=MIND.ms*.9+(performance.now()-t0)*.1;
  mindStateText(tgt.state);
  if(!MIND.still)MIND.raf=requestAnimationFrame(mindFrame);
}
function mindDraw(t,state){
  const g=MIND.ctx,L=MIND.layout,S=MIND.snap,d=MIND.dpr;if(!g)return;
  if(!MIND.bg)MIND.bg=mindBackground();
  g.setTransform(1,0,0,1,0,0);g.globalCompositeOperation='source-over';g.drawImage(MIND.bg,0,0);
  const dt=Math.min(.1,Math.max(0,(t-MIND.prevT)/1000));MIND.prevT=t;
  const voice=mindVoice(t,state);
  if(!L||!S){g.setTransform(d,0,0,d,0,0);mindCore(g,MIND.W/2,MIND.H/2,t,state,voice);return}
  g.setTransform(d,0,0,d,0,0);
  mindProject(t);
  const cx=L.cx,cy=L.cy,hubs=Object.values(L.hubs),T=MIND.still?0:t/1000,P=MIND.P;
  g.globalCompositeOperation='lighter';g.lineCap='round';g.lineJoin='round';
  // fibres: core → each thing it holds, a loose bundle of wandering strands per
  // connection; one stroke per cluster, in two shades so a bundle has depth
  hubs.forEach(H=>{
    const n=H.nodes.length,hue=H.h.hue,fl=MIND.flare[H.h.id]||0;
    const busy=H.h.busy?(.5+.5*Math.sin(t/420)):0;
    // bright enough to read with a hundred memories (a screenshot of 83 showed a haze)
    const alpha=Math.min(.55,(n>80?.11:n>30?.14:.19)+busy*.12+fl*.35+voice.level*.08);
    const B=n>150?2:n>60?3:n>20?4:6;
    for(let pass=0;pass<2;pass++){
      g.strokeStyle=`hsla(${hue+(pass?14:-8)},${pass?80:95}%,${pass?70:60}%,${alpha*(pass?.7:1)})`;
      g.lineWidth=(n>80?.8:1)*(pass?.7:1);g.beginPath();
      // with nothing in it yet, a cluster is still wired to the core by one strand
      if(!n&&!pass)mindTrace(g,mindHubFibre(H,T,P));
      H.nodes.forEach(p=>{for(let b=pass;b<B;b+=2)mindTrace(g,mindNodeFibre(H,p,b,T,P))});
      g.stroke();
    }
    // dendrites: the cluster's own short branching arms, reaching away from the core
    g.strokeStyle=`hsla(${hue},90%,66%,${.3+busy*.2+fl*.4})`;g.lineWidth=1;g.beginPath();
    H.den.forEach(D=>{
      const sway=MIND.still?0:Math.sin(T*.6+D.ang*3)*.12,an=D.ang+sway,ex=H.x+Math.cos(an)*D.len,ey=H.y+Math.sin(an)*D.len;
      mindTrace(g,mindFibre(H.x,H.y,H.x+Math.cos(an+.3)*D.len*.5,H.y+Math.sin(an+.3)*D.len*.5,ex,ey,D.w,D.len*.12,T,0,P));
      if(D.fork){const fa=an+D.fork,mx=H.x+Math.cos(an)*D.len*.55,my=H.y+Math.sin(an)*D.len*.55,fl2=D.len*D.fl;
        mindTrace(g,mindFibre(mx,my,mx+Math.cos(fa-.2)*fl2*.5,my+Math.sin(fa-.2)*fl2*.5,mx+Math.cos(fa)*fl2,my+Math.sin(fa)*fl2,D.w,fl2*.15,T,1,P))}
    });
    g.stroke();
  });
  // what connects across the clusters: facts in the graph, memories and runs that name
  // something in it, a mission's roster, agents who talked. Each a wandering fibre too.
  const at=L.nodeAt,lw=L.lw;
  g.lineWidth=.8;g.strokeStyle='hsla(276,90%,72%,.26)';g.beginPath();
  S.links.forEach((k,i)=>{if(k.kind!=='fact')return;const A=at[k.a],B=at[k.b];if(!A||!B)return;
    mindTrace(g,mindFibre(A.x,A.y,(A.x+B.x)/2,(A.y+B.y)/2,B.x,B.y,lw[i],10,T,0,P))});
  g.stroke();
  const byHue={};
  S.links.forEach((k,i)=>{if(k.kind!=='mention')return;const A=at[k.a],B=at[k.b];if(!A||!B)return;
    (byHue[A.H.h.hue]=byHue[A.H.h.hue]||[]).push([A,B,i])});
  g.lineWidth=.9;
  Object.keys(byHue).forEach(hue=>{
    g.strokeStyle=`hsla(${hue},85%,72%,.24)`;g.beginPath();
    byHue[hue].forEach(([A,B,i])=>{const mx=(A.x+B.x)/2,my=(A.y+B.y)/2;
      mindTrace(g,mindFibre(A.x,A.y,mx+(cx-mx)*.4,my+(cy-my)*.4,B.x,B.y,lw[i],16,T,0,P))});
    g.stroke()});
  g.strokeStyle='hsla(36,95%,64%,.3)';g.lineWidth=1;g.beginPath();
  S.links.forEach((k,i)=>{if(k.kind!=='roster')return;const A=at[k.a],H=L.hubs[k.b];if(!A||!H)return;
    const mx=(A.x+H.x)/2,my=(A.y+H.y)/2;
    mindTrace(g,mindFibre(A.x,A.y,mx+(cx-mx)*.35,my+(cy-my)*.35,H.x,H.y,lw[i],14,T,0,P))});
  g.stroke();
  S.links.forEach((k,i)=>{if(k.kind!=='talk')return;const A=L.hubs[k.a],B=L.hubs[k.b];if(!A||!B)return;
    const q=mindTalkCtrl(A,B);
    g.strokeStyle=`hsla(${(A.h.hue+B.h.hue)/2},90%,70%,.42)`;g.lineWidth=1+Math.log(1+k.n)*1.3;
    g.beginPath();mindTrace(g,mindFibre(A.x,A.y,q.x,q.y,B.x,B.y,lw[i],24,T,0,P));g.stroke()});
  // the things themselves: a node that a signal just reached flashes, like a synapse
  hubs.forEach(H=>{
    const hue=H.h.hue;
    H.nodes.forEach(p=>{
      const n=p.n,bad=n.status==='error'||n.status==='timeout';
      const spr=mindSprite(bad?2:hue,bad?90:100,bad?60:62);
      const s=(n.kind==='person'?(n.head?22:18)*(n.busy?1.25:1)
        :n.pinned||n.kind==='skill'||n.on?15:10+Math.min(8,(n.w||0)*1.5))*(.75+p.z*.25)*(1+p.flash*.9);
      g.globalAlpha=Math.min(1,Math.max(.35,.8+p.z*.2)*(n.hub==='missions'&&!n.on?.45:1)+p.flash*.5);
      g.drawImage(spr,p.x-s/2,p.y-s/2,s,s);
      if(p.flash)p.flash=p.flash<.03?0:p.flash*.9;
    });
    g.globalAlpha=1;
    const fl=MIND.flare[H.h.id]||0,busy=H.h.busy?(.5+.5*Math.sin(t/420)):0;
    const s=46+H.rh*.5+busy*18+fl*40;
    g.drawImage(mindSprite(hue),H.x-s/2,H.y-s/2,s,s);
    if(fl)MIND.flare[H.h.id]=fl<.02?0:fl*.93;
  });
  mindGlints(g,t,dt,voice);
  mindSparks(g,t);
  mindCore(g,cx,cy,t,state,voice);
  g.globalCompositeOperation='source-over';
}
function mindTalkCtrl(A,B){
  const L=MIND.layout,mx=(A.x+B.x)/2,my=(A.y+B.y)/2;
  // bow away from the core so the arc reads as between the two, not through the lead
  return {x:mx+(mx-L.cx)*.45,y:my+(my-L.cy)*.45};
}

/* ---------- the voice ----------
   While the lead speaks, the core follows the SOUND: an analyser on the <audio> the
   voice plays through (speakAs's SPEECH.audio), so a syllable swells it and a pause
   lets it settle. Reported as "the centre is just beeping": it pulsed on a timer that
   had nothing to do with the words. A browser voice (speechSynthesis) has no stream to
   listen to, so it gets a syllable rhythm, as before. The tap routes the element's
   sound through an AudioContext, which plays nothing while suspended, so it is only
   made once that context is running; otherwise the sound is left alone. */
var MIND_AUDIO={ctx:null,an:null,buf:null,els:new WeakMap(),lvl:0,bins:null};
function mindTap(el){
  const A=MIND_AUDIO;
  if(A.els.has(el))return A.els.get(el);
  try{
    const C=window.AudioContext||window.webkitAudioContext;if(!C)return false;
    if(!A.ctx)A.ctx=new C();
    if(A.ctx.state!=='running'){A.ctx.resume().catch(()=>{});return false}
    if(!A.an){A.an=A.ctx.createAnalyser();A.an.fftSize=128;A.an.smoothingTimeConstant=.55;
      A.an.connect(A.ctx.destination);A.buf=new Uint8Array(A.an.frequencyBinCount)}
    A.ctx.createMediaElementSource(el).connect(A.an);
    A.els.set(el,true);return true;
  }catch(e){A.els.set(el,false);return false}
}
function mindVoice(t,state){
  const A=MIND_AUDIO,N=24;
  if(!A.bins)A.bins=new Float32Array(N);
  let lvl=0;
  if(state==='speaking'&&!MIND.still){
    const el=typeof SPEECH!=='undefined'?SPEECH.audio:null;
    if(el&&!el.paused&&mindTap(el)){
      A.an.getByteFrequencyData(A.buf);
      // the voice band: the first bins of a 128-point FFT are roughly 0 to 8 kHz
      for(let i=0;i<N;i++){const v=A.buf[i+1]/255;A.bins[i]+=(v-A.bins[i])*.5;lvl+=v}
      lvl=Math.min(1,lvl/N*1.8);
    }else{
      // no stream to listen to: syllables, loosely
      lvl=.3+.7*Math.abs(Math.sin(t/105)*Math.sin(t/41+1.3));
      for(let i=0;i<N;i++){const v=lvl*(.4+.6*Math.abs(Math.sin(t/(70+i*9)+i)));A.bins[i]+=(v-A.bins[i])*.4}
    }
  }else for(let i=0;i<N;i++)A.bins[i]*=.8;
  const rise=lvl-A.lvl;
  A.lvl+=(lvl-A.lvl)*(lvl>A.lvl?.55:.18);
  // a syllable's onset sends a ripple out of the core and a few signals down the fibres
  const now=performance.now();
  if(rise>.14&&now-MIND.lastPk>150&&!MIND.still){MIND.lastPk=now;
    MIND.ripples.push({at:now,dur:1100,k:A.lvl});if(MIND.ripples.length>8)MIND.ripples.shift();
    for(let i=0;i<2+Math.round(A.lvl*2);i++)mindGlint(true)}
  return {level:A.lvl,bins:A.bins};
}
function mindCore(g,cx,cy,t,state,v){
  const e=MIND.energy,still=MIND.still,ph=mindPhone()?.8:1,now=performance.now();
  const R=(30+e*20+v.level*24)*ph,T=still?0:t/1000;
  g.globalCompositeOperation='lighter';
  const halo=g.createRadialGradient(cx,cy,0,cx,cy,R*4.4);
  halo.addColorStop(0,`rgba(255,244,230,${.5+e*.3})`);
  halo.addColorStop(.12,`rgba(255,196,140,${.32+e*.3+v.level*.2})`);
  halo.addColorStop(.35,`rgba(150,120,255,${.12+e*.12})`);
  halo.addColorStop(1,'rgba(40,60,160,0)');
  g.fillStyle=halo;g.beginPath();g.arc(cx,cy,R*4.4,0,Math.PI*2);g.fill();
  // ripples: out of the core on a spoken syllable, in towards it while listening
  MIND.ripples=MIND.ripples.filter(r=>now-r.at<r.dur);
  if(state==='listening'&&!still&&(!MIND.ripples.length||now-MIND.ripples[MIND.ripples.length-1].at>700))
    MIND.ripples.push({at:now,dur:1400,k:.5,inward:true});
  MIND.ripples.forEach(r=>{
    const u=(now-r.at)/r.dur,rr=r.inward?R*(3.4-u*2.2):R*(1.1+u*3.2);
    g.strokeStyle=`rgba(255,${r.inward?'220,190':'205,160'},${(1-u)*(.18+r.k*.28)})`;g.lineWidth=1+r.k*1.2;
    g.beginPath();
    for(let k=0;k<=48;k++){const th=k/48*Math.PI*2,w=1+.05*Math.sin(th*5+u*6+r.at)+.04*Math.sin(th*3-u*4);
      const x=cx+Math.cos(th)*rr*w,y=cy+Math.sin(th)*rr*w*.92;k?g.lineTo(x,y):g.moveTo(x,y)}
    g.stroke();
  });
  // the soma: a cell body, never a perfect circle. Speaking, its edge is the voice
  // itself, each direction one band of the sound; at rest it breathes slowly.
  const bins=v.bins,N=bins.length;
  g.beginPath();
  for(let k=0;k<=72;k++){
    // each half of the edge runs through the bands and back, blended between them so
    // the edge is a curve and not a staircase
    const th=k/72*Math.PI*2,h=k<=36?k/36:(72-k)/36,f=h*(N-1),i0=Math.floor(f),fr=f-i0;
    const bin=(bins[i0]||0)*(1-fr)+(bins[Math.min(N-1,i0+1)]||0)*fr;
    const r=R*(1+.08*Math.sin(3*th+T*.9)+.06*Math.sin(5*th-T*1.3)+(state==='thinking'?.05*Math.sin(7*th+T*6):0)+bin*.6);
    const x=cx+Math.cos(th)*r,y=cy+Math.sin(th)*r;k?g.lineTo(x,y):g.moveTo(x,y);
  }
  const body=g.createRadialGradient(cx,cy,0,cx,cy,R*1.5);
  body.addColorStop(0,'rgba(255,250,240,.95)');body.addColorStop(.45,`rgba(255,200,150,${.55+v.level*.3})`);
  body.addColorStop(1,'rgba(160,120,255,.05)');
  g.fillStyle=body;g.fill();
  g.strokeStyle=`rgba(255,220,190,${.12+e*.12+v.level*.2})`;g.lineWidth=1;g.stroke();
  // the nucleus, and a flicker inside it while thinking
  const nk=still?1:1+(state==='thinking'?.12*Math.sin(t/90):0)+v.level*.25;
  g.drawImage(mindSprite(28,100,70),cx-R*1.3*nk,cy-R*1.3*nk,R*2.6*nk,R*2.6*nk);
  g.drawImage(mindSprite(40,40,90),cx-R*.7*nk,cy-R*.7*nk,R*1.4*nk,R*1.4*nk);
  g.globalCompositeOperation='source-over';
}

/* ---------- signals ----------
   Resting activity: faint white glints running along the real fibres, out to a node or
   back to the core, a few a second, more while the lead thinks or speaks. Asked for:
   "the neurons in standby should be sending signals". It is scenery, like the drift of
   the fibres, and it is drawn so it cannot be mistaken for news: small, pale, and it
   never lights a cluster. A spoken syllable sends a few warm ones (mindVoice). Only a
   real event sends a SPARK (below), coloured, bright, and it flares its cluster. */
function mindGlint(voice){
  const L=MIND.layout;if(!L||MIND.glints.length>60)return;
  const hs=Object.values(L.hubs).filter(H=>H.nodes.length);if(!hs.length)return;
  // a busy cluster is picked more often, and a bigger one a little more often
  let tot=0;const wt=hs.map(H=>{const v=Math.sqrt(H.nodes.length)*(H.h.busy?2.5:1);tot+=v;return v});
  let r=Math.random()*tot,i=0;while(r>wt[i]&&i<hs.length-1){r-=wt[i];i++}
  const H=hs[i],p=H.nodes[Math.floor(Math.random()*H.nodes.length)];
  MIND.glints.push({H,p,b:Math.floor(Math.random()*2),out:voice||Math.random()<.65,voice:!!voice,
    at:performance.now(),dur:(voice?700:1000)+Math.random()*900});
}
function mindGlints(g,t,dt,v){
  if(!MIND.still&&MIND.layout){
    MIND.gAcc+=dt*(.8+MIND.energy*2.6);
    while(MIND.gAcc>=1){MIND.gAcc-=1;mindGlint(false)}
  }
  const now=performance.now(),T=MIND.still?0:t/1000,P=MIND.Q;
  MIND.glints=MIND.glints.filter(s=>{
    const u=(now-s.at)/s.dur;
    if(u>=1){if(s.out)s.p.flash=Math.max(s.p.flash,s.voice?.8:.45);return false}
    if(!s.H.nodes.includes(s.p))return false;
    mindNodeFibre(s.H,s.p,s.b,T,P);
    const e=u*u*(3-2*u),spr=s.voice?mindSprite(34,100,72):mindSprite(215,40,88);
    for(let k=0;k<3;k++){
      const q=s.out?e-k*.025:1-e+k*.025,[x,y]=mindAt(P,q),sz=(s.voice?11:8)-k*2;
      g.globalAlpha=(s.voice?.9:.6)*(1-k*.3)*Math.min(1,u*6,(1-u)*6+.2);
      g.drawImage(spr,x-sz/2,y-sz/2,sz,sz);
    }
    return true;
  });
  g.globalAlpha=1;
}
/* A spark is a real event travelling: from the core out along the cluster's trunk, or
   between two agents that are talking. */
function mindSparks(g,t){
  const L=MIND.layout,now=performance.now(),T=MIND.still?0:t/1000,P=MIND.Q;
  MIND.sparks=MIND.sparks.filter(s=>now-s.at<s.dur);
  MIND.sparks.forEach(s=>{
    const B=L.hubs[s.to];if(!B)return;
    if(s.from==='core')mindHubFibre(B,T,P);
    else{const A=L.hubs[s.from];if(!A)return;const q=mindTalkCtrl(A,B);mindFibre(A.x,A.y,q.x,q.y,B.x,B.y,B.w,24,T,0,P)}
    const hue=B.h.hue;
    for(let k=0;k<5;k++){
      const [x,y]=mindAt(P,(now-s.at)/s.dur-k*.03),sz=24-k*4;
      g.globalAlpha=1-k*.18;g.drawImage(mindSprite(hue,100,70),x-sz/2,y-sz/2,sz,sz);
    }
    g.globalAlpha=1;
    if(now-s.at>s.dur*.9)MIND.flare[s.to]=1;
  });
}
var MIND_MEMORY_TOOLS=/^(remember|recall|forget|memory_|search_memor|pin_memor)/;
var MIND_KG_TOOLS=/^(kg_|knowledge|graph_)/;
/* Fed only by scenePulse (01c): the websocket's turn, tool, flow, say and msg events. */
function mindPulse(kind,label,ev){
  if(!MIND.on||!MIND.layout)return;
  const L=MIND.layout,now=performance.now(),spark=(from,to)=>{
    if(!L.hubs[to]||(from!=='core'&&!L.hubs[from]))return;
    MIND.sparks.push({from,to,at:now,dur:MIND.still?1:1100});
    if(MIND.sparks.length>24)MIND.sparks.shift();
  };
  // an agent's cluster is its department's when there is a company (mind.py `where`)
  const agentHub=n=>{if(!n)return '';const w=MIND.snap&&MIND.snap.where&&MIND.snap.where[n];
    return w&&L.hubs[w]?w:L.hubs['agent:'+n]?'agent:'+n:''};
  if(kind==='tool'&&label){
    const name=String(label),args=(ev&&ev.args)||{};
    if(MIND_MEMORY_TOOLS.test(name))spark('core','memory');
    else if(MIND_KG_TOOLS.test(name))spark('core','knowledge');
    else if(/^(delegate|ask_agent)$/.test(name)&&agentHub(args.agent||args.to||args.name))spark('core',agentHub(args.agent||args.to||args.name));
    else if(/flow|mission/.test(name))spark('core','missions');
  }else if(kind==='flow'&&ev){
    const who=agentHub(ev.ref||ev.agent);
    if(who)spark(ev.flow?'missions':'core',who);else if(ev.flow)spark('core','missions');
    if(ev.event==='status')mindSoon(1200);
  }else if(kind==='done'){spark('core','missions');mindSoon(1500)}
  else if(kind==='msg'&&ev){const a=agentHub(ev.from),b=agentHub(ev.to);
    if(a&&b&&a===b)MIND.flare[a]=1;else if(a&&b)spark(ev.phase==='ask'?a:b,ev.phase==='ask'?b:a)}
  else if(kind==='say'&&label){const a=agentHub(label),b=agentHub(ev&&ev.to);if(a&&b&&a!==b)spark(a,b);else if(a)MIND.flare[a]=1}
  else if(kind==='turnend')mindSoon(2000);
  mindKick();
}

/* ---------- the words around it ---------- */
function mindStateText(state){
  const el=MIND.ui&&MIND.ui.querySelector('.mn-state');if(!el)return;
  const words={speaking:'Speaking',thinking:'Thinking',listening:'Listening',working:'Working',quiet:'Quiet'};
  if(el.dataset.s===state)return;
  el.dataset.s=state;el.textContent=words[state]||'Quiet';
  MIND.ui.querySelector('.mn-top').dataset.state=state;
}
function mindNum(n){n=+n||0;return n>=1e6?(n/1e6).toFixed(1).replace(/\.0$/,'')+'M':n>=1e4?Math.round(n/1e3)+'k':n>=1e3?(n/1e3).toFixed(1).replace(/\.0$/,'')+'k':String(n)}
function mindPaintUI(){
  const S=MIND.snap,U=MIND.ui;if(!S||!U)return;
  const st=S.stats,b=S.brief||{},agents=S.team.length,depts=S.hubs.filter(h=>h.kind==='dept');
  U.querySelector('.mn-top').innerHTML=
    `<span class="mn-dot"></span><b class="mn-state">Quiet</b><span class="mn-sep">·</span>`+
    `<span class="mn-sum">${esc(S.lead)} and ${agents} specialist${agents===1?'':'s'}${depts.length?` in ${depts.length} department${depts.length===1?'':'s'}`:''}</span>`+
    `<button class="mn-btn" onclick="mindTell()">Tell me</button>`+
    `<button class="mn-btn" onclick="mindTalk()" aria-label="Talk to ${esc(S.lead)}">🎙 Talk</button>`+
    `<button class="mn-btn mn-peace" onclick="mindPeace()" aria-pressed="${MIND.peace?'true':'false'}" title="${MIND.peace?'Show the panels':'Peace: only the mind'}">${MIND.peace?'Show all':'Peace'}</button>`;
  MIND.ui.querySelector('.mn-state').dataset.s='';
  const row=(label,val,sub)=>`<div class="mn-row"><span>${label}</span><b>${val}</b>${sub?`<i>${sub}</i>`:''}</div>`;
  const need=(+b.needs_you||0)+(+b.decide||0);
  U.querySelector('.mn-left').innerHTML=
    `<section class="mn-panel"><h3>This week</h3>`+
      row('Tasks run',mindNum(st.runs),st.failed?`${st.failed} did not finish`:'')+
      row('Mission runs',mindNum(st.missions),st.missions?`${st.missions_ok} finished well`:'')+
      row('Asked each other',mindNum(st.asks),st.free_talks?`${st.free_talks} free talk${st.free_talks===1?'':'s'}`:'')+
      row('Tokens',mindNum(st.tokens),'')+`</section>`+
    `<section class="mn-panel"><h3>What it holds</h3>`+
      row('Memories',mindNum(st.memories),'')+
      row('People, places, topics',mindNum(st.knowledge),st.facts?`${mindNum(st.facts)} facts between them`:'')+
      row('Missions on',mindNum(st.missions_on),'')+`</section>`+
    `<button class="mn-panel mn-brief" onclick="openApp('brief')"><h3>Your Brief today</h3>`+
      (b.open?row('Need you',need,'')+row('For your information',+b.fyi||0,'')+row('Done',+b.done||0,''):'<p class="mn-quiet">Nothing waiting.</p>')+`</button>`;
  const busyLead=typeof RUNNING!=='undefined'&&RUNNING.size>0;
  U.querySelector('.mn-right').innerHTML=`<section class="mn-panel mn-team"><h3>Team</h3>`+
    `<div class="mn-agent lead${busyLead?' busy':''}"><span class="mn-pip"></span><b>${esc(S.lead)}</b><i>${busyLead?'working':'your lead'}</i></div>`+
    depts.map(h=>{const ppl=S.team.filter(a=>a.dept===h.label),busy=ppl.filter(a=>a.busy).length,
      runs=ppl.reduce((n,a)=>n+(a.runs||0),0);
      return `<button class="mn-agent${busy?' busy':''}" data-hub="${esc(h.id)}"><span class="mn-pip" style="--mh:${h.hue}"></span>`+
        `<b>${esc(h.label)}</b><i>${busy?busy+' working':runs?runs+' run'+(runs===1?'':'s')+' this week':'idle'} · ${ppl.length} ${ppl.length===1?'person':'people'}</i></button>`}).join('')+
    (S.team.length?S.team.filter(a=>!a.dept).map(a=>`<button class="mn-agent${a.busy?' busy':''}" data-hub="agent:${esc(a.name)}">`+
      `<span class="mn-pip" style="--mh:${(S.hubs.find(h=>h.id==='agent:'+a.name)||{}).hue||200}"></span><b>${esc(a.name)}</b>`+
      `<i>${a.busy?'working':a.runs?a.runs+' run'+(a.runs===1?'':'s')+' this week':'idle'}${a.brain?' · '+esc(a.brain):''}</i></button>`).join('')
      :'<p class="mn-quiet">No specialists yet.</p>')+`</section>`;
  mindPlaceTags();
  if(MIND.open)mindCard(MIND.open,true);
}
/* Cluster names sit at the hub, which does not move, so a finger can find them. */
function mindPlaceTags(){
  const L=MIND.layout,U=MIND.ui;if(!L||!U)return;
  const box=U.querySelector('.mn-tags');if(!box)return;
  const S=MIND.snap,count=id=>(L.hubs[id]?L.hubs[id].nodes.length:0);
  box.innerHTML=Object.values(L.hubs).map(H=>{
    const h=H.h;
    return `<button class="mn-tag${h.busy?' busy':''}" style="left:${H.x}px;top:${H.y}px;--mh:${h.hue};--rh:${H.rh}px" data-hub="${esc(h.id)}">`+
      `<span class="mn-name">${esc(h.label)}<em>${count(h.id)}</em></span></button>`}).join('');
  // two names that land on each other (a phone, a big team) step apart vertically,
  // away from the core, so each stays a whole target for a finger
  const tags=[...box.children],rs=tags.map(t=>t.getBoundingClientRect()),dy=tags.map(()=>0);
  for(let i=0;i<tags.length;i++)for(let j=0;j<i;j++){
    const a=rs[i],b=rs[j];
    if(a.left<b.right-2&&a.right>b.left+2&&a.top+dy[i]<b.bottom+dy[j]-2&&a.bottom+dy[i]>b.top+dy[j]+2){
      const up=parseFloat(tags[i].style.top)<L.cy;
      dy[i]=up?(b.top+dy[j])-a.bottom-2:(b.bottom+dy[j])-a.top+2;
    }
  }
  tags.forEach((t,i)=>{if(dy[i])t.style.marginTop=dy[i]+'px'});
}
function mindCard(id,refresh){
  const S=MIND.snap,U=MIND.ui;if(!S||!U)return;
  const card=U.querySelector('.mn-card');
  if(!refresh&&MIND.open===id&&!card.hidden){card.hidden=true;MIND.open='';U.classList.remove('carded');return}
  const h=S.hubs.find(x=>x.id===id);if(!h){card.hidden=true;MIND.open='';U.classList.remove('carded');return}
  MIND.open=id;
  const nodes=S.nodes.filter(n=>n.hub===id),li=a=>a.length?'<ul>'+a.join('')+'</ul>':'';
  let body='',go='';
  if(h.kind==='memory'){
    body=`<p>${nodes.length} thing${nodes.length===1?'':'s'} ${esc(S.lead)} remembers about you.</p>`+
      li(nodes.slice(0,6).map(n=>`<li>${n.pinned?'📌 ':''}${esc(n.label)}</li>`));
    go=`<button class="endbtn" onclick="openApp('memory')">Open Memory</button>`;
  }else if(h.kind==='knowledge'){
    const top=nodes.slice().sort((a,b)=>(b.w||0)-(a.w||0)).slice(0,8);
    body=`<p>${S.stats.knowledge} people, places and topics, with ${S.stats.facts} facts between them.</p>`+
      li(top.map(n=>`<li>${esc(n.label)}${n.w?` <i>${n.w} fact${n.w===1?'':'s'}</i>`:''}</li>`));
    go=`<button class="endbtn" onclick="openApp('kg')">Open Knowledge</button>`;
  }else if(h.kind==='missions'){
    body=nodes.length?li(nodes.map(n=>`<li>${esc(n.label)} <i>${n.on?'on':'off'}</i></li>`)):'<p>No missions yet.</p>';
    go=`<button class="endbtn" onclick="openApp('jobs')">Open Missions</button>`;
  }else if(h.kind==='dept'){
    const ppl=nodes.filter(n=>n.kind==='person'),runs=nodes.filter(n=>n.kind==='run');
    const busy=ppl.filter(n=>n.busy).map(n=>n.label);
    body=`<p>${busy.length?esc(busy.join(', '))+' working now.':runs.length?`${runs.length} run${runs.length===1?'':'s'} this week.`:'Nothing this week.'}</p>`+
      li(ppl.map(n=>`<li>${n.head?'★ ':''}${esc(n.label)}${n.title?` <i>${esc(n.title)}</i>`:''}</li>`))+
      li(runs.slice(0,4).map(n=>`<li>${esc(n.label)} <i>${esc(n.status||'')}</i></li>`));
    go=`<button class="endbtn" data-dept="${esc(h.label)}">Give ${esc(h.label)} a task</button>`;
  }else{
    const name=h.label,a=S.team.find(x=>x.name===name)||{},talk=S.links.filter(k=>k.kind==='talk'&&(k.a===id||k.b===id));
    const skills=nodes.filter(n=>n.kind==='skill'),runs=nodes.filter(n=>n.kind==='run');
    body=`<p>${a.busy?'Working right now.':a.runs?`${a.runs} run${a.runs===1?'':'s'} this week.`:'Nothing this week.'}${a.brain?' Thinks with '+esc(a.brain)+'.':''}</p>`+
      (skills.length?`<p class="mn-k">Skills: ${skills.map(s=>esc(s.label)).join(', ')}</p>`:'')+
      (talk.length?`<p class="mn-k">Talked with ${talk.map(k=>esc((k.a===id?k.b:k.a).replace(/^agent:/,''))+` (${k.n})`).join(', ')}</p>`:'')+
      li(runs.slice(0,5).map(n=>`<li>${esc(n.label)} <i>${esc(n.status||'')}</i></li>`));
    go=`<button class="endbtn" onclick="openApp('jobs')">Open in Missions</button>`;
  }
  card.innerHTML=`<div class="mn-ch"><span class="mn-pip" style="--mh:${h.hue}"></span><b>${esc(h.label)}</b>`+
    `<button class="mn-x" aria-label="Close" data-hub="${esc(id)}">✕</button></div>${body}<div class="mn-go">${go}</div>`;
  const dg=card.querySelector('[data-dept]');if(dg)dg.onclick=()=>mindDept(dg.dataset.dept);
  card.hidden=false;U.classList.add('carded');
}
/* A department's card hands over to the Office's company panel, where tasks are given. */
function mindDept(name){
  openApp('office');
  setTimeout(()=>{if(typeof COMPANY!=='undefined'){COMPANY.focus=name;officeCompany(true)}},500);
}
/* The panels, said aloud by the lead, from the same snapshot. */
function mindTell(){
  const S=MIND.snap;if(!S||typeof speakAs!=='function')return;
  const say=MIND.ui.querySelector('.mn-say');
  say.textContent=S.spoken;say.hidden=false;
  MIND.telling=true;mindKick();
  speakAs('@agent',S.spoken,()=>{MIND.telling=false;if(say)say.hidden=true;mindKick()});
}
/* Talking to the lead: Jarvis, with this scene's core as its orb (26-mind.css). */
function mindTalk(){if(typeof jarvisMode==='function')jarvisMode(true);mindKick()}
if(typeof IMMERSIVE!=='undefined'&&IMMERSIVE.on&&IMMERSIVE.scene==='mind')setTimeout(mindStart,0);
