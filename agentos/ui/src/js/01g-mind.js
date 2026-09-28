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
  still:false,W:0,H:0,dpr:1,energy:.25,sparks:[],flare:{},layout:null,sprites:{},bg:null,ms:0,open:'',telling:false,t0:0};

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
  mindResize();
  mindFetch();
}
function mindStop(){
  if(!MIND.on)return;
  MIND.on=false;
  cancelAnimationFrame(MIND.raf);MIND.raf=0;
  clearTimeout(MIND.fetchT);clearTimeout(MIND.pollT);clearTimeout(MIND.snooze);
  removeEventListener('resize',mindResize);
  document.removeEventListener('visibilitychange',mindKick);
  if(MIND.telling&&typeof speechStop==='function')speechStop();
  if(MIND.host)MIND.host.remove();if(MIND.ui)MIND.ui.remove();
  MIND.host=MIND.ui=MIND.cv=MIND.ctx=null;MIND.snap=null;MIND.sparks=[];MIND.layout=null;MIND.bg=null;MIND.open='';MIND.telling=false;
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
  const bar=rect('omnibar'),dock=rect('dock');
  const top=Math.max(phone?150:130,bar&&bar.bottom<H*.5?bar.bottom+48:0);
  const bottom=Math.min(H-(phone?80:100),dock&&dock.top>H*.5?dock.top-(phone?20:34):H);
  const side=phone?18:W>=1000?272:24;
  const cx=W/2,cy=(top+bottom)/2;
  const rx=Math.max(90,Math.min(560,(W-2*side)/2-(phone?46:70))),ry=Math.max(70,(bottom-top)/2-(phone?34:48));
  const hubs={},order=S.hubs;
  const byHub={};S.nodes.forEach(n=>{(byHub[n.hub]=byHub[n.hub]||[]).push(n)});
  order.forEach((h,i)=>{
    const a=-Math.PI*.82+i*(Math.PI*2/order.length);
    const list=byHub[h.id]||[];
    const rh=Math.min(phone?60:110,(phone?16:24)+(phone?4:7)*Math.sqrt(list.length));
    hubs[h.id]={h,i,x:cx+Math.cos(a)*rx,y:cy+Math.sin(a)*ry,a,rh,spin:(i%2?-1:1)*(.00007+.00003*(i%3)),
      nodes:list.map(n=>{const R=mindRand(mindHash(n.id));
        // a point inside the sphere, biased outward so a cluster reads as a cloud
        const u=R()*2-1,th=R()*Math.PI*2,rr=Math.cbrt(.25+R()*.75),s=Math.sqrt(1-u*u);
        // one connection is drawn as a bundle of strands; the bundle is the one thing
        const bs=[];for(let b=0;b<6;b++)bs.push([R()*2-1,R()*2-1,R()*2-1]);
        return {n,lx:Math.cos(th)*s*rr,ly:u*rr,lz:Math.sin(th)*s*rr,j:R()*2-1,k:R(),bs,x:0,y:0,z:0}})};
  });
  const nodeAt={};Object.values(hubs).forEach(H=>H.nodes.forEach(p=>{nodeAt[p.n.id]=p;p.H=H}));
  MIND.layout={cx,cy,rx,ry,hubs,nodeAt};
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
  const gap=1000/(lively?30:12);
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
  if(!L||!S){mindCore(g,MIND.W/2,MIND.H/2,t,state);return}
  g.setTransform(d,0,0,d,0,0);
  mindProject(t);
  const cx=L.cx,cy=L.cy,hubs=Object.values(L.hubs),wob=MIND.still?0:1;
  g.globalCompositeOperation='lighter';g.lineCap='round';
  // filaments: core → (bent through the hub) → each thing it holds; one stroke per cluster
  hubs.forEach(H=>{
    const n=H.nodes.length,hue=H.h.hue,fl=MIND.flare[H.h.id]||0;
    const busy=H.h.busy?(.5+.5*Math.sin(t/420)):0;
    const alpha=Math.min(.5,(n>80?.07:n>30?.09:.12)+busy*.12+fl*.35);
    g.strokeStyle=`hsla(${hue},95%,62%,${alpha})`;g.lineWidth=n>80?.7:1;
    g.beginPath();
    const nx=-(H.y-cy),ny=H.x-cx,nl=Math.hypot(nx,ny)||1;
    // with nothing in it yet, a cluster is still wired to the core by one strand
    if(!n){g.moveTo(cx,cy);g.quadraticCurveTo((cx+H.x)/2+nx/nl*20,(cy+H.y)/2+ny/nl*20,H.x,H.y)}
    const B=n>150?2:n>60?3:n>20?4:6;
    H.nodes.forEach(p=>{
      const bend=p.j*H.rh*.9+Math.sin(t/2600+p.k*6)*6*wob;
      const qx=cx+(H.x-cx)*.62+nx/nl*bend,qy=cy+(H.y-cy)*.62+ny/nl*bend;
      for(let b=0;b<B;b++){const o=p.bs[b],sp=H.rh*.35;
        g.moveTo(cx+o[2]*3,cy+o[1]*3);g.quadraticCurveTo(qx+o[0]*sp,qy+o[1]*sp,p.x+o[2]*3,p.y+o[0]*3)}
      p.qx=qx;p.qy=qy;
    });
    g.stroke();
  });
  // what connects across the clusters: facts in the graph, a mission's roster, agents who talked
  const at=L.nodeAt;
  g.strokeStyle='hsla(276,90%,72%,.28)';g.lineWidth=.8;g.beginPath();
  S.links.forEach(k=>{if(k.kind!=='fact')return;const a=at[k.a],b=at[k.b];if(a&&b){g.moveTo(a.x,a.y);g.lineTo(b.x,b.y)}});
  g.stroke();
  g.strokeStyle='hsla(36,95%,64%,.32)';g.lineWidth=1;g.beginPath();
  S.links.forEach(k=>{if(k.kind!=='roster')return;const a=at[k.a],B=L.hubs[k.b];
    if(a&&B){g.moveTo(a.x,a.y);g.quadraticCurveTo((a.x+B.x)/2+(cx-(a.x+B.x)/2)*.35,(a.y+B.y)/2+(cy-(a.y+B.y)/2)*.35,B.x,B.y)}});
  g.stroke();
  S.links.forEach(k=>{if(k.kind!=='talk')return;const A=L.hubs[k.a],B=L.hubs[k.b];if(!A||!B)return;
    const q=mindTalkCtrl(A,B);
    g.strokeStyle=`hsla(${(A.h.hue+B.h.hue)/2},90%,70%,.45)`;g.lineWidth=1+Math.log(1+k.n)*1.4;
    g.beginPath();g.moveTo(A.x,A.y);g.quadraticCurveTo(q.x,q.y,B.x,B.y);g.stroke()});
  // the things themselves
  hubs.forEach(H=>{
    const hue=H.h.hue;
    H.nodes.forEach(p=>{
      const n=p.n,bad=n.status==='error'||n.status==='timeout';
      const spr=mindSprite(bad?2:hue,bad?90:100,bad?60:62);
      const s=(n.pinned||n.kind==='skill'||n.on?15:10+Math.min(8,(n.w||0)*1.5))*(.75+p.z*.25);
      g.globalAlpha=Math.max(.35,.8+p.z*.2)*(n.hub==='missions'&&!n.on?.45:1);
      g.drawImage(spr,p.x-s/2,p.y-s/2,s,s);
    });
    g.globalAlpha=1;
    const fl=MIND.flare[H.h.id]||0,busy=H.h.busy?(.5+.5*Math.sin(t/420)):0;
    const s=46+H.rh*.5+busy*18+fl*40;
    g.drawImage(mindSprite(hue),H.x-s/2,H.y-s/2,s,s);
    if(fl)MIND.flare[H.h.id]=fl<.02?0:fl*.93;
  });
  mindSparks(g,t);
  g.globalCompositeOperation='source-over';
  mindCore(g,cx,cy,t,state);
}
function mindTalkCtrl(A,B){
  const L=MIND.layout,mx=(A.x+B.x)/2,my=(A.y+B.y)/2;
  // bow away from the core so the arc reads as between the two, not through the lead
  return {x:mx+(mx-L.cx)*.45,y:my+(my-L.cy)*.45};
}
function mindCore(g,cx,cy,t,state){
  const e=MIND.energy,still=MIND.still;
  // speaking is a voice, so the core swells in syllables rather than a smooth sine
  const talk=state==='speaking'&&!still?(.55+.45*Math.abs(Math.sin(t/110)*Math.sin(t/37+1))):0;
  const R=(34+e*26+talk*16)*(mindPhone()?.8:1);
  g.globalCompositeOperation='lighter';
  const halo=g.createRadialGradient(cx,cy,0,cx,cy,R*4.2);
  halo.addColorStop(0,`rgba(255,244,230,${.55+e*.3})`);
  halo.addColorStop(.12,`rgba(255,196,140,${.35+e*.3})`);
  halo.addColorStop(.35,`rgba(150,120,255,${.12+e*.12})`);
  halo.addColorStop(1,'rgba(40,60,160,0)');
  g.fillStyle=halo;g.beginPath();g.arc(cx,cy,R*4.2,0,Math.PI*2);g.fill();
  g.drawImage(mindSprite(28,100,70),cx-R*1.6,cy-R*1.6,R*3.2,R*3.2);
  g.drawImage(mindSprite(40,40,90),cx-R*.8,cy-R*.8,R*1.6,R*1.6);
  // two thin orbits: thinking spins them, listening opens them wider
  const spin=still?0:t/(state==='thinking'?700:4200);
  g.lineWidth=1.1;
  [[1.7,.34,spin],[2.15,.26,-spin*.8+1]].forEach(([k,sq,a],i)=>{
    const open=state==='listening'?1.15:1;
    g.strokeStyle=`rgba(${i?'150,190,255':'255,210,160'},${.18+e*.35})`;
    g.beginPath();g.ellipse(cx,cy,R*k*open,R*k*sq*open,a,0,Math.PI*2);g.stroke();
  });
  g.globalCompositeOperation='source-over';
}
/* A spark is a real event travelling: from the core out along the filament to the
   cluster that did it, or between two agents that are talking. */
function mindSparks(g,t){
  const L=MIND.layout,now=performance.now();
  MIND.sparks=MIND.sparks.filter(s=>now-s.at<s.dur);
  MIND.sparks.forEach(s=>{
    const A=s.from==='core'?{x:L.cx,y:L.cy}:L.hubs[s.from],B=L.hubs[s.to];if(!A||!B)return;
    const q=s.from==='core'?{x:L.cx+(B.x-L.cx)*.55,y:L.cy+(B.y-L.cy)*.55}:mindTalkCtrl(A,B);
    const hue=B.h.hue;
    for(let k=0;k<4;k++){
      const p=Math.max(0,Math.min(1,(now-s.at)/s.dur-k*.035)),u=1-p;
      const x=u*u*A.x+2*u*p*q.x+p*p*B.x,y=u*u*A.y+2*u*p*q.y+p*p*B.y,sz=(22-k*4);
      g.globalAlpha=1-k*.22;g.drawImage(mindSprite(hue,100,70),x-sz/2,y-sz/2,sz,sz);
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
  const agentHub=n=>n&&L.hubs['agent:'+n]?'agent:'+n:'';
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
  else if(kind==='msg'&&ev){const a=agentHub(ev.from),b=agentHub(ev.to);if(a&&b)spark(ev.phase==='ask'?a:b,ev.phase==='ask'?b:a)}
  else if(kind==='say'&&label){const a=agentHub(label),b=agentHub(ev&&ev.to);if(a&&b)spark(a,b);else if(a)MIND.flare[a]=1}
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
  const st=S.stats,b=S.brief||{},agents=S.hubs.filter(h=>h.kind==='agent').length;
  U.querySelector('.mn-top').innerHTML=
    `<span class="mn-dot"></span><b class="mn-state">Quiet</b><span class="mn-sep">·</span>`+
    `<span class="mn-sum">${esc(S.lead)} and ${agents} specialist${agents===1?'':'s'}</span>`+
    `<button class="mn-btn" onclick="mindTell()">Tell me</button>`+
    `<button class="mn-btn" onclick="mindTalk()" aria-label="Talk to ${esc(S.lead)}">🎙 Talk</button>`;
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
    (S.team.length?S.team.map(a=>`<button class="mn-agent${a.busy?' busy':''}" data-hub="agent:${esc(a.name)}">`+
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
  card.hidden=false;U.classList.add('carded');
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
