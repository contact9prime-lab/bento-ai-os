/* ---------------- One zoomable map: the agents, the logical map and the device map ----------------
   Reported with a screenshot of the Agents map ("not making any sense, too cluttered … make it
   intuitive: zoom out to see things, zoom in to see more, click a node or search to go further")
   and as "the desktop is flickering like crazy". Both had one cause: the Agents map drew every
   agent, brain, executor, skill and mission at once, 2,448 curves on a 1034x2794 sheet inside a
   blurred window, which Chrome re-tiles on every scroll. Measured on a copy of the owner's hub.

   So the three maps (Settings → Agents, Network & Teams → Maps, Devices) are this one view, and it
   is a map you move through rather than a sheet you squint at:
   - ONE PLACE AT A TIME. What you are looking at sits in the middle; what is inside it is on the
     ring around it; what is inside those shows as small dots beyond, so you can see where there is
     more. The level above is one "↑" node, and the trail in the panel goes back further. A first
     radial tree of everything still piled up on the owner's 47 agents; a focus never does.
   - Tap moves in (and says everything about it in the panel: permissions, tools, address, with the
     doors that act on it). ↑, Fit after zooming out, or the trail moves out. Search goes straight
     to anything, and opens the place it is in.
   - Zoom moves things apart and keeps the markers a size you can read; drag to move.
   - A fixed-size window (contain:strict), so its cost never grows with the team.
   The data is the same answers as before (topology.logical, /api/network); nothing is decided here.
   `var`/functions only: the bundle is one script. */
var ZM={};          // host id -> {root, focus, sel, k, x, y, L}
var ZM_SIZE=[32,21,6];
var ZM_GAP=58;       // arc each node on the ring needs, in map pixels

function zmFlat(n,out,path){out=out||[];path=path||[];out.push({n,path});(n.children||[]).forEach(c=>zmFlat(c,out,path.concat(n)));return out}
function zmFind(st,nid){return zmFlat(st.root).find(x=>x.n.id===nid)}

function zmMount(host,root,o){
  if(!host)return;
  o=o||{};
  const id=host.dataset.zm||(host.dataset.zm='zm'+Math.random().toString(36).slice(2,8));
  const prev=ZM[id];
  const keep=x=>prev&&x&&zmFlat(root).some(y=>y.n.id===x)?x:'';
  ZM[id]={root,focus:keep(prev&&prev.focus)||root.id,sel:keep(prev&&prev.sel),k:prev?prev.k:1,x:prev?prev.x:0,y:prev?prev.y:0,o};
  if(!host.querySelector('.zm')){
    host.innerHTML=`<div class="zm" tabindex="0" aria-label="${esc(o.label||'Map')}">
      <svg class="zm-svg" role="img" aria-label="${esc(o.label||'Map')}"><g class="zm-cam"></g></svg>
      <div class="zm-tools"><input class="zm-q" type="search" placeholder="Find…" aria-label="Find on the map" list="${id}-names">
        <datalist id="${id}-names"></datalist>
        <button class="endbtn zm-b" data-zmb="in" aria-label="Zoom in">＋</button><button class="endbtn zm-b" data-zmb="out" aria-label="Zoom out">−</button>
        <button class="endbtn zm-b" data-zmb="fit">Fit</button><button class="endbtn zm-b zm-up" data-zmb="up" hidden></button></div>
      <aside class="zm-side" hidden></aside>
      <p class="zm-hint">Tap to go in · ↑ goes back · drag to move · scroll to zoom</p></div>`;
    zmWire(host,id);
  }
  zmPaint(host,id);
  if(!prev)zmFit(host,id,true);
}

/* The focus in the middle, its children on a ring big enough for all of them, their children as
   dots just outside each one, and the level above as one node off to the side. */
function zmLayout(st){
  const pos={},vis=[],edges=[];
  const hit=zmFind(st,st.focus)||{n:st.root,path:[]};
  const f=hit.n,kids=f.children||[];
  pos[f.id]={x:0,y:0,d:0,n:f,a:0};vis.push(f.id);
  const R1=Math.max(kids.length<=6?125:170,kids.length*ZM_GAP/(2*Math.PI));
  kids.forEach((c,i)=>{
    const a=-Math.PI/2+2*Math.PI*i/Math.max(kids.length,1);
    pos[c.id]={x:Math.cos(a)*R1,y:Math.sin(a)*R1,d:1,n:c,a};vis.push(c.id);edges.push([f.id,c.id,c.kind]);
    // the dots that say "there is more here": only on a ring with room for them
    const g=kids.length>10?[]:c.children||[],span=Math.min(2*Math.PI/Math.max(kids.length,1)*0.8,0.9),R2=R1+70;
    g.slice(0,24).forEach((gc,j)=>{const b=a+(g.length>1?(j/(Math.min(g.length,24)-1)-.5)*span:0);
      pos[gc.id]={x:Math.cos(b)*R2,y:Math.sin(b)*R2,d:2,n:gc,a:b};vis.push(gc.id);edges.push([c.id,gc.id,'ghost'])});
  });
  return {pos,vis,edges,up:hit.path[hit.path.length-1]||null};
}

function zmPaint(host,id){
  const st=ZM[id],cam=host.querySelector('.zm-cam');if(!cam)return;
  const L=zmLayout(st);st.L=L;
  // up to ten on a ring, each name sits under its marker; a crowded ring turns them outward
  L.crowded=L.vis.filter(v=>L.pos[v].d===1&&!L.pos[v].up).length>10;
  const P=L.pos;
  const edge=([a,b,k])=>{const A=P[a],B=P[b];if(!A||!B)return'';
    return `<line class="zm-e ${esc(k||'')}${st.sel&&(a===st.sel||b===st.sel)?' on':''}" x1="${A.x.toFixed(1)}" y1="${A.y.toFixed(1)}" x2="${B.x.toFixed(1)}" y2="${B.y.toFixed(1)}"/>`};
  const node=nid=>{const p=P[nid],n=p.n,kids=(n.children||[]).length;
    if(p.d===2)return `<g class="zm-n dot ${esc(n.kind||'')}" data-zid="${esc(n.id)}" transform="translate(${p.x.toFixed(1)},${p.y.toFixed(1)})"><circle class="zm-c" r="${ZM_SIZE[2]}"><title>${esc(n.label)}</title></circle></g>`;
    const r=ZM_SIZE[p.d]*(p.up?0.8:1);
    const img=n.img&&!p.up?`<clipPath id="${id}-c-${zmSafe(n.id)}"><circle r="${r-3}"/></clipPath><image href="${esc(n.img)}" x="${-r+3}" y="${-r+3}" width="${2*r-6}" height="${2*r-6}" clip-path="url(#${id}-c-${zmSafe(n.id)})" preserveAspectRatio="xMidYMin slice"/>`
      :`<text class="zm-ini" dy=".35em">${esc(p.up?'↑':(n.glyph||String(n.label||'?').slice(0,1).toUpperCase()))}</text>`;
    // names go outward from the middle, so a full ring of them never runs into its neighbours
    let lab;
    if(p.d===1&&!p.up&&(L.crowded)){
      const deg=p.a*180/Math.PI,left=Math.cos(p.a)<-0.01,rot=left?deg+180:deg,vert=Math.abs(Math.cos(p.a))<0.35;
      lab=vert?`<text class="zm-l" y="${Math.sin(p.a)>0?r+14:-r-8}">${esc(String(n.label||'').slice(0,26))}</text>`
        :`<text class="zm-l" transform="rotate(${rot.toFixed(1)})" x="${left?-(r+6):r+6}" dy=".35em" text-anchor="${left?'end':'start'}">${esc(String(n.label||'').slice(0,26))}</text>`;
    }else{
      lab=`<text class="zm-l${p.d===0?' big':''}" y="${r+15}">${esc(p.up?'Back to '+String(n.label||'').slice(0,22):String(n.label||'').slice(0,30))}</text>`
        +(n.sub&&p.d===0?`<text class="zm-s" y="${r+29}">${esc(String(n.sub).slice(0,48))}</text>`:'');
    }
    const badge=kids&&p.d===1?`<g class="zm-badge" transform="translate(${(r*.75).toFixed(1)},${(-r*.75).toFixed(1)})"><circle r="9"/><text dy=".35em">${kids>99?'99+':kids}</text></g>`:'';
    return `<g class="zm-n d${p.d} ${p.up?'up ':''}${esc(n.kind||'')} ${esc(n.st||'')}${st.sel===n.id?' sel':''}${kids?' has':''}" data-zid="${esc(n.id)}" transform="translate(${p.x.toFixed(1)},${p.y.toFixed(1)})" tabindex="0" role="button" aria-label="${esc(p.up?'Back to '+n.label:(n.kindWord?n.kindWord+' ':'')+n.label+(kids?', '+kids+' inside':''))}">
      <circle class="zm-c" r="${r}" style="${n.color?'--zc:'+esc(n.color):''}"/>${img}${badge}${lab}</g>`};
  cam.innerHTML=L.edges.map(edge).join('')+L.vis.map(node).join('');
  // the way back out is a button in the toolbar, so the frame only has to hold the place itself
  const ub=host.querySelector('.zm-up');
  if(ub){ub.hidden=!L.up;if(L.up){ub.textContent='↑ '+String(L.up.label).slice(0,24);ub.dataset.up=L.up.id;
    ub.setAttribute('aria-label','Back to '+L.up.label)}}
  zmCam(host,id);
  const dl=host.querySelector('datalist');
  if(dl&&!dl.dataset.done){dl.dataset.done=1;dl.innerHTML=zmFlat(st.root).map(x=>`<option value="${esc(x.n.label)}">`).join('')}
  zmSide(host,id);
}
function zmSafe(s){return String(s).replace(/[^a-z0-9_-]/gi,'_')}
function zmCam(host,id){
  const st=ZM[id],svg=host.querySelector('.zm-svg'),cam=host.querySelector('.zm-cam');if(!svg||!cam)return;
  const w=svg.clientWidth||600,h=svg.clientHeight||400;
  cam.setAttribute('transform',`translate(${(w/2+st.x).toFixed(1)},${(h/2+st.y).toFixed(1)}) scale(${st.k.toFixed(3)})`);
  host.querySelector('.zm')?.classList.toggle('narrow',w<760);
  // like a map: zooming moves places apart, the markers and their names keep a size you can read
  // (never under about half their size, or a small window piles them up again)
  const s=Math.max(0.65,Math.min(1.4,st.k))/st.k;
  if(st.L)cam.querySelectorAll('.zm-n').forEach(g=>{const p=st.L.pos[g.dataset.zid];
    if(p)g.setAttribute('transform',`translate(${p.x.toFixed(1)},${p.y.toFixed(1)}) scale(${s.toFixed(3)})`)});
}
/* Frame what is shown, in the room the panel leaves (beside it when wide, above it when narrow). */
function zmFit(host,id,now){
  const st=ZM[id],svg=host.querySelector('.zm-svg');if(!svg||!st.L)return;
  const ps=Object.values(st.L.pos);if(!ps.length)return;
  const w=svg.clientWidth||600,h=svg.clientHeight||400,wide=w>=760,panel=!!st.sel;
  const xs=ps.map(p=>p.x),ys=ps.map(p=>p.y);
  const bw=Math.max(...xs)-Math.min(...xs)+220,bh=Math.max(...ys)-Math.min(...ys)+170;
  const aw=w-(panel&&wide?320:0),ah=(panel&&!wide?h*0.6:h)-50;
  const k=Math.max(0.3,Math.min(1.3,Math.min(aw/bw,ah/bh)));
  const to={k,x:-((Math.max(...xs)+Math.min(...xs))/2)*k-(panel&&wide?160:0),y:-((Math.max(...ys)+Math.min(...ys))/2)*k+25-(panel&&!wide?h*0.19:0)};
  zmAnimate(host,id,to,now);
}
function zmAnimate(host,id,to,now){
  const st=ZM[id],t0=performance.now(),from={k:st.k,x:st.x,y:st.y};
  const reduce=now||(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches);
  const step=t=>{const f=reduce?1:Math.min(1,(t-t0)/300),e=1-Math.pow(1-f,3);
    st.k=from.k+(to.k-from.k)*e;st.x=from.x+(to.x-from.x)*e;st.y=from.y+(to.y-from.y)*e;zmCam(host,id);
    if(f<1)requestAnimationFrame(step)};
  if(reduce)step(t0+1);else requestAnimationFrame(step);
}
/* Go to a node: a place with things in it becomes the middle; a thing on its own is shown where it
   is, with its panel. "↑" goes back up. */
function zmSelect(host,id,nid){
  const st=ZM[id];
  if(String(nid).startsWith('↑')){const up=nid.slice(1);st.focus=up;st.sel=up;zmPaint(host,id);zmFit(host,id);return}
  const hit=zmFind(st,nid);if(!hit)return;
  if((hit.n.children||[]).length)st.focus=nid;
  else st.focus=(hit.path[hit.path.length-1]||st.root).id;
  st.sel=nid;zmPaint(host,id);zmFit(host,id);
}
function zmSide(host,id){
  const st=ZM[id],side=host.querySelector('.zm-side');if(!side)return;
  const hit=st.sel&&zmFlat(st.root).find(x=>x.n.id===st.sel);
  if(!hit){side.hidden=true;return}
  const n=hit.n;side.hidden=false;
  side.innerHTML=`<div class="zm-crumbs">${hit.path.map(a=>`<button class="zm-crumb" data-zgo="${esc(a.id)}">${esc(a.label)}</button>`).join('<span>›</span>')}</div>
    <div class="zm-h"><b>${esc(n.label)}</b>${n.kindWord?` <span class="brainchip">${esc(n.kindWord)}</span>`:''}<button class="zm-x" aria-label="Close">✕</button></div>
    ${n.sub?`<p class="mut zm-sub">${esc(n.sub)}</p>`:''}
    <div class="zm-detail">${typeof n.detail==='function'?n.detail():n.detail||''}</div>
    ${(n.children||[]).length?`<div class="zm-kids"><span class="ag-k">Inside</span>${n.children.slice(0,40).map(c=>`<button class="zm-kid" data-zgo="${esc(c.id)}">${esc(c.label)}</button>`).join('')}${n.children.length>40?` <span class="mut">and ${n.children.length-40} more</span>`:''}</div>`:''}`;
  side.querySelector('.zm-x').onclick=()=>{st.sel='';zmPaint(host,id);zmFit(host,id)};
  side.querySelectorAll('[data-zgo]').forEach(b=>b.onclick=()=>zmSelect(host,id,b.dataset.zgo));
  if(typeof n.wire==='function')n.wire(side);
}
function zmWire(host,id){
  const z=host.querySelector('.zm'),svg=host.querySelector('.zm-svg');
  const st=()=>ZM[id];
  const zoomAt=(f,cx,cy)=>{const s=st(),r=svg.getBoundingClientRect(),w=svg.clientWidth,h=svg.clientHeight;
    const px=(cx==null?w/2:cx-r.left)-w/2,py=(cy==null?h/2:cy-r.top)-h/2;
    const k=Math.max(0.2,Math.min(3,s.k*f)),q=k/s.k;s.x=px-(px-s.x)*q;s.y=py-(py-s.y)*q;s.k=k;zmCam(host,id)};
  svg.addEventListener('wheel',e=>{e.preventDefault();zoomAt(Math.exp(-e.deltaY*0.0015),e.clientX,e.clientY)},{passive:false});
  const pts=new Map();let drag=null,moved=0,pinch=0;
  svg.addEventListener('pointerdown',e=>{pts.set(e.pointerId,{x:e.clientX,y:e.clientY});
    const g=e.target.closest&&e.target.closest('.zm-n');
    svg.setPointerCapture(e.pointerId);
    moved=0;drag={x:e.clientX,y:e.clientY,sx:st().x,sy:st().y,node:g?g.dataset.zid:''};
    if(pts.size===2){const [a,b]=[...pts.values()];pinch=Math.hypot(a.x-b.x,a.y-b.y)}});
  svg.addEventListener('pointermove',e=>{if(!pts.has(e.pointerId))return;pts.set(e.pointerId,{x:e.clientX,y:e.clientY});
    if(pts.size===2&&pinch){const [a,b]=[...pts.values()],d=Math.hypot(a.x-b.x,a.y-b.y);zoomAt(d/pinch,(a.x+b.x)/2,(a.y+b.y)/2);pinch=d;moved=99;return}
    if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;moved=Math.max(moved,Math.abs(dx)+Math.abs(dy));
    if(moved>4){const s=st();s.x=drag.sx+dx;s.y=drag.sy+dy;zmCam(host,id)}});
  const up=e=>{pts.delete(e.pointerId);if(pts.size<2)pinch=0;
    if(drag&&moved<=4&&drag.node&&!String(drag.node).startsWith('dot'))zmSelect(host,id,drag.node)
    if(!pts.size)drag=null};
  svg.addEventListener('pointerup',up);svg.addEventListener('pointercancel',e=>{pts.delete(e.pointerId);drag=null});
  host.querySelectorAll('[data-zmb]').forEach(b=>b.onclick=()=>{const k=b.dataset.zmb;
    if(k==='in')zoomAt(1.3);
    else if(k==='out'){const s=st();if(s.k<=0.45&&s.focus!==s.root.id)host.querySelector('.zm-up')?.click();else zoomAt(1/1.3)}
    else if(k==='up'){const s=st();if(b.dataset.up){s.focus=b.dataset.up;s.sel=b.dataset.up;zmPaint(host,id);zmFit(host,id)}}
    else zmFit(host,id)});
  const q=host.querySelector('.zm-q');
  const find=()=>{const v=q.value.trim().toLowerCase();if(!v)return;
    const all=zmFlat(st().root),hit=all.find(x=>String(x.n.label).toLowerCase()===v)||all.find(x=>String(x.n.label).toLowerCase().includes(v));
    if(hit)zmSelect(host,id,hit.n.id);else toast('Nothing on the map is called that.')};
  q.addEventListener('change',find);q.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();find()}});
  z.addEventListener('keydown',e=>{if(e.target===q)return;
    const s=st(),k={'+':()=>zoomAt(1.25),'=':()=>zoomAt(1.25),'-':()=>zoomAt(0.8),'0':()=>zmFit(host,id),
      ArrowLeft:()=>{s.x+=40;zmCam(host,id)},ArrowRight:()=>{s.x-=40;zmCam(host,id)},ArrowUp:()=>{s.y+=40;zmCam(host,id)},ArrowDown:()=>{s.y-=40;zmCam(host,id)}}[e.key];
    if(k){e.preventDefault();k()}
    else if(e.key==='Enter'){const g=e.target.closest&&e.target.closest('.zm-n');if(g)zmSelect(host,id,g.dataset.zid)}
    else if(e.key==='Backspace'||e.key==='Escape'){const s=st();if(s.focus!==s.root.id)host.querySelector('.zm-up')?.click()}});
  if(typeof ResizeObserver==='function')new ResizeObserver(()=>zmCam(host,id)).observe(svg);
}

/* ---- the data: the same answers the lists read ---- */
function zmPersonDetail(p){
  const fams=Object.entries(p.families||{});
  return `<div class="zm-rows">
    <div><span class="ag-k">Executor</span>${esc(p.hands||'default')}${p.hands_summary?` <span class="mut">${esc(p.hands_summary)}</span>`:''}</div>
    ${p.brain?`<div><span class="ag-k">Brain</span>${esc(p.brain)}</div>`:''}
    <div><span class="ag-k">Tools</span>${(p.tools||[]).map(x=>`<span class="brainchip">${esc(x==='*'?'every tool':x)}</span>`).join(' ')||'<span class="mut">none</span>'}</div>
    ${(p.skills||[]).length?`<div><span class="ag-k">Skills</span>${p.skills.map(x=>`<span class="brainchip">${esc(x)}</span>`).join(' ')}</div>`:''}
    <div><span class="ag-k">Permissions</span>${p.autonomy?'autonomy '+esc(p.autonomy)+' · ':''}${p.allow||0} allowed, ${p.deny||0} refused${fams.length?' <span class="mut">('+fams.map(([k,v])=>esc(k)+' '+v.allow+(v.deny?'/'+v.deny+'✗':'')).join(', ')+')</span>':''}</div>
    ${(p.missions||[]).length?`<div><span class="ag-k">Missions</span>${p.missions.map(esc).join(', ')}</div>`:''}
    <div class="zm-acts">${p.lead?'':`<button class="endbtn" onclick="agentEdit('${esc(p.name)}')">Edit</button>`}<button class="endbtn" onclick="openApp('permissions')">Permissions</button></div></div>`;
}
function zmAvatar(key){try{return typeof avatarSrc==='function'?avatarSrc(key):''}catch(e){return ''}}
function zmTieNode(t,where){
  return {id:'tie:'+where+':'+t.label,label:t.label,kind:'tie '+(t.kind||'team'),kindWord:t.kind==='zero'?'Zero':'Team',
    st:t.answering===false?'off':'',sub:t.missing?t.missing+' is gone':(t.kind==='zero'?'Zero':'linked team'),glyph:t.kind==='zero'?'◫':'⇄',
    detail:()=>`<div class="zm-rows"><div><span class="ag-k">Talks to</span>${esc(where)}</div>
      <div class="zm-acts"><button class="endbtn" onclick="placeSettings('network')()">Who it talks to</button></div></div>`};
}
function zmTieGroup(ties,where,gid){
  ties=ties||[];
  if(ties.length<2)return ties.map(t=>zmTieNode(t,where));
  return [{id:'g:'+gid,label:ties.length+' talking to '+where,kind:'group ties',glyph:'⇄',kindWord:'',
    sub:ties.map(t=>t.label).join(', '),children:ties.map(t=>zmTieNode(t,where))}];
}
function zmLogical(tree){
  const L=tree.lead||{};
  const person=(p,pre)=>({id:pre+':'+p.name,label:p.label||p.name,kind:'person'+(p.head?' head':''),kindWord:p.head?'head':'agent',
    sub:p.hands&&p.hands!=='default'?p.hands:'',img:zmAvatar(p.name),detail:()=>zmPersonDetail(p)});
  const companies=(tree.companies||[]).map((c,ci)=>({id:'co:'+ci,label:c.name,kind:'company'+(c.default?' default':''),kindWord:c.default?'':'company',
    sub:c.about||(c.open&&!c.default?'open':''),big:true,glyph:'▦',
    detail:()=>`<div class="zm-rows"><div><span class="ag-k">Departments</span>${(c.departments||[]).length}</div>
      <div class="zm-acts"><button class="endbtn" onclick="openApp('office');setTimeout(()=>{if(typeof officeCompany==='function')officeCompany(true)},900)">Company panel</button></div></div>`,
    children:[...(c.departments||[]).map((d,di)=>({id:`d:${ci}:${di}`,label:d.name,kind:'dept',kindWord:'department',glyph:'▸',
        sub:(d.people||[]).length+' people'+(d.head?' · head '+d.head:''),openAtStart:false,
        detail:()=>`<div class="zm-rows">${d.about?`<div>${esc(d.about)}</div>`:''}${d.head?`<div><span class="ag-k">Head</span>${esc(d.head)}</div>`:''}
          ${(d.ties||[]).length?`<div><span class="ag-k">Talking to it</span>${d.ties.map(t=>esc(t.label)).join(', ')}</div>`:''}</div>`,
        children:[...zmTieGroup(d.ties,d.name,`t:${ci}:${di}`),...(d.people||[]).map(p=>person(p,`p:${ci}:${di}`))]})),
      ...(c.people||[]).map(p=>person(p,`p:${ci}`)),
      ...(c.auditor?[person({...c.auditor,label:c.auditor.name+' (auditor)'},`a:${ci}`)]:[])]}));
  return {id:'lead',label:L.name||'Aria',kind:'lead',kindWord:'lead agent',big:true,img:zmAvatar('@agent'),
    detail:()=>zmPersonDetail({...L,lead:true}),
    children:[...zmTieGroup(L.ties,L.name||'Aria','tl'),...companies]};
}
function zmPhysical(v){
  const rows=(v.rows||[]).filter(r=>!r.ignored),ties=(v.ties||[]).filter(t=>!t.stale);
  const rowOf=t=>rows.find(r=>(r.links||[]).some(l=>l.label===t.label));
  const tied=new Set();ties.forEach(t=>{const r=rowOf(t);if(r)tied.add(r.key)});
  const tieN=t=>{const st=typeof tieState==='function'?tieState(t):{cls:'',word:''},r=rowOf(t);
    return {id:'tie:'+tieKey(t),label:(t.agent||{}).name||t.peer||t.label,kind:'device '+(t.kind||'team'),kindWord:t.kind==='zero'?'Zero':'Team',
      st:(t.answering===false?'off':'')+((typeof DEVMAP!=='undefined'&&DEVMAP.busy[t.label])?' busy':''),sub:t.label+(t.addr?' · '+t.addr:''),
      img:t.agent&&t.agent.look&&typeof avatarRecipeSrc==='function'?avatarRecipeSrc(t.agent.look):'',glyph:t.kind==='zero'?'◫':'⇄',
      detail:()=>`<div class="zm-rows"><div><span class="ag-k">State</span>${esc(st.word||'')}${t.version?' · '+esc(t.version):''}</div>
        ${t.addr?`<div><span class="ag-k">Address</span>${esc(t.addr)}</div>`:''}${r&&r.mac?`<div><span class="ag-k">MAC</span>${esc(r.mac)}</div>`:''}
        ${t.talks_to?`<div><span class="ag-k">Talks to</span>${esc(t.talks_to.to==='department'?t.talks_to.department:'your lead agent')}</div>`:''}
        ${typeof DEVMAP!=='undefined'&&DEVMAP.busy[t.label]?`<div><span class="ag-k">Now</span>${esc(DEVMAP.busy[t.label])}</div>`:''}
        <div class="zm-acts"><button class="endbtn" data-zt="${esc(tieKey(t))}">Manage</button></div></div>`,
      wire:side=>side.querySelectorAll('[data-zt]').forEach(b=>b.onclick=()=>{TIES.open=b.dataset.zt;TIES.view=null;
        tieLists().then(()=>netPaint()).then(()=>document.querySelector(`.devhub-box .tie[data-tiekey="${CSS.escape(b.dataset.zt)}"]`)?.scrollIntoView({block:'start',behavior:'smooth'}))})}};
  const rowN=r=>{const ag=r.agent||{},cs=((r.controls||{}).state)||{};
    return {id:'m:'+r.key,label:r.display||r.ip,kind:'device machine',kindWord:r.bento==='none'?'device':'Bento',
      st:cs.running===false?'off':'',sub:(r.ip&&r.ip!==r.display?r.ip:'')+(r.security_words&&r.bento!=='none'?' · '+r.security_words:''),
      img:ag.look&&Object.keys(ag.look).length&&typeof avatarRecipeSrc==='function'?avatarRecipeSrc(ag.look):'',
      detail:()=>`<div class="zm-rows"><div><span class="ag-k">Address</span>${esc(r.ip||'')}</div>${r.mac?`<div><span class="ag-k">MAC</span>${esc(r.mac)}</div>`:''}
        <div><span class="ag-k">Bento</span>${esc(r.bento||'')}${r.security_words?' · '+esc(r.security_words):''}</div>
        <div class="zm-acts"><button class="endbtn" data-zm-go="${esc(r.key)}">Open in the list</button></div></div>`,
      wire:side=>side.querySelectorAll('[data-zm-go]').forEach(b=>b.onclick=()=>devMapGo(b.dataset.zmGo))}};
  const zeros=ties.filter(t=>t.kind==='zero'),teams=ties.filter(t=>t.kind!=='zero');
  const bento=rows.filter(r=>!tied.has(r.key)&&r.bento!=='none'&&r.bento!=='removed'),rest=rows.filter(r=>!tied.has(r.key)&&!bento.includes(r));
  const group=(id,label,kids,open,glyph)=>kids.length?[{id,label,kind:'group',kindWord:'',glyph,openAtStart:open,children:kids}]:[];
  const me=v.me||{};
  return {id:'me',label:me.name||'This computer',kind:'lead',kindWord:'this computer',big:true,img:zmAvatar('@agent'),
    sub:me.ip||'',detail:()=>`<div class="zm-rows">${me.ip?`<div><span class="ag-k">Address</span>${esc(me.ip)}</div>`:''}
      <div><span class="ag-k">Tied to it</span>${zeros.length} Zero${zeros.length===1?'':'s'}, ${teams.length} team${teams.length===1?'':'s'}</div></div>`,
    children:[...group('g:zero','Zeros',zeros.map(tieN),true,'◫'),...group('g:team','Linked teams',teams.map(tieN),true,'⇄'),
      ...group('g:bento','Bento machines',bento.map(rowN),true,'▣'),...group('g:rest','Other devices',rest.map(rowN),false,'•')]};
}
