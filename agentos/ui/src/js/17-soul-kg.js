/* ================= soul app ================= */
async function renderSoul(body){
  const r=await fetch('/api/soul');const d=await r.json();
  body.innerHTML=`<div class="pshell">
    <div class="phead">
      <span class="pt">Soul</span>
      <span class="ps">the agent's persistent identity — injected into every conversation; it can evolve it itself via <code>update_soul</code></span>
      <span class="sp"></span>
      <button class="pact" style="flex:0 0 90px" onclick="soulSave()">Save</button>
    </div>
    <textarea id="soul-ta" spellcheck="false"></textarea>
  </div>`;
  $('#soul-ta').value=d.content;
}
async function soulSave(){
  await fetch('/api/soul',{method:'PUT',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({content:$('#soul-ta').value})});
  toast('soul saved');
}

/* ================= knowledge graph app ================= */
async function renderKG(body,w){
  body.innerHTML=`<div class="apptop">
      <span class="psearch" style="flex:0 1 210px">${SVG_SEARCH}<input id="kg-q" placeholder="Filter the graph…" value="${esc(w._kgq||'')}"></span>
      <input id="kg-s" placeholder="subject"><input id="kg-r" placeholder="relation"><input id="kg-o" placeholder="object">
      <button class="save" style="margin:0;flex:0 0 64px;padding:8px" onclick="kgAdd()">Add</button>
      <button class="endbtn" title="merge duplicate entities, roll up idle sessions, re-index memory" onclick="tidyKnowledge()">Tidy</button>
      <button class="endbtn" onclick="kgClear()">Clear graph</button>
    </div>
    <div style="flex:1;min-height:0;position:relative">
      <canvas id="kgc" style="position:absolute;inset:0;width:100%;height:100%"></canvas>
      <div id="kg-empty" class="mut" style="position:absolute;inset:0;display:none;align-items:center;justify-content:center;text-align:center;padding:30px">
        The graph is empty.<br>Ask the agent to "add what you know about me to the knowledge graph",<br>or add a (subject, relation, object) triple above.</div>
    </div>`;
  {const qi=$('#kg-q');let t;
   qi.oninput=()=>{clearTimeout(t);t=setTimeout(()=>{w._kgq=qi.value;renderKG(body,w).then(()=>{const q2=$('#kg-q');if(q2){q2.focus();q2.setSelectionRange(q2.value.length,q2.value.length)}})},250)};}
  const r=await fetch('/api/kg');const g=await r.json();
  const q=(w._kgq||'').toLowerCase().trim();
  if(q){
    const keep=new Set(g.nodes.filter(n=>(n.name||'').toLowerCase().includes(q)).map(n=>n.id));
    g.edges.forEach(e=>{if(e.relation.toLowerCase().includes(q)){keep.add(e.src);keep.add(e.dst)}});
    g.edges.forEach(e=>{if(keep.has(e.src)||keep.has(e.dst)){keep.add(e.src);keep.add(e.dst)}}); // 1-hop neighbours
    g.nodes=g.nodes.filter(n=>keep.has(n.id));
    g.edges=g.edges.filter(e=>keep.has(e.src)&&keep.has(e.dst));
  }
  const canvas=$('#kgc');if(!canvas)return;
  cancelAnimationFrame(w.raf);w.raf=0;
  stopWinTicks(w);                       // a re-render (search, refresh) replaces the old loop
  if(!g.nodes.length){$('#kg-empty').style.display='flex';
    if(q)$('#kg-empty').innerHTML='Nothing in the graph matches “'+esc(w._kgq)+'”.';return}
  const dpr=devicePixelRatio||1;
  const nodes=g.nodes.map((n,i)=>({...n,
    x:Math.cos(i/g.nodes.length*6.283)*120+(i%7)*13, y:Math.sin(i/g.nodes.length*6.283)*120+(i%5)*11, vx:0,vy:0}));
  const byid={};nodes.forEach(n=>byid[n.id]=n);
  const edges=g.edges.filter(e=>byid[e.src]&&byid[e.dst]);
  const COLORS={person:'#5eead4',org:'#22d3ee',project:'#fbbf24',tool:'#c084fc','':'#8a94a6'};
  let ticks=0;
  const step=()=>{
    w.raf=0;
    if(!canvas.isConnected)return;
    if(!winAwake(w))return;               // nobody is looking — kick() repaints on the way back
    const W=canvas.clientWidth,H=canvas.clientHeight;
    canvas.width=W*dpr;canvas.height=H*dpr;
    // physics
    if(ticks<400){
      for(const a of nodes){
        for(const b of nodes){ if(a===b)continue;
          let dx=a.x-b.x,dy=a.y-b.y,d2=dx*dx+dy*dy+.01,d=Math.sqrt(d2);
          const f=1800/d2; a.vx+=dx/d*f; a.vy+=dy/d*f; }
        a.vx-=a.x*.012; a.vy-=a.y*.012;   // gravity to center
      }
      for(const e of edges){
        const a=byid[e.src],b=byid[e.dst];
        let dx=b.x-a.x,dy=b.y-a.y,d=Math.sqrt(dx*dx+dy*dy)+.01;
        const f=(d-110)*.02; a.vx+=dx/d*f;a.vy+=dy/d*f;b.vx-=dx/d*f;b.vy-=dy/d*f;
      }
      for(const n of nodes){n.x+=n.vx*.5;n.y+=n.vy*.5;n.vx*=.6;n.vy*=.6}
      ticks++;
    }
    // draw
    const ctx=canvas.getContext('2d');
    ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.clearRect(0,0,W,H);
    ctx.save();ctx.translate(W/2,H/2);
    ctx.font='10px sans-serif';
    for(const e of edges){
      const a=byid[e.src],b=byid[e.dst];
      ctx.strokeStyle='rgba(94,234,212,.22)';ctx.lineWidth=1;
      ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();
      ctx.fillStyle='rgba(138,148,166,.85)';
      ctx.fillText(e.relation,(a.x+b.x)/2+4,(a.y+b.y)/2-3);
    }
    ctx.font='600 11.5px sans-serif';
    for(const n of nodes){
      ctx.fillStyle=COLORS[n.type]||COLORS[''];
      ctx.beginPath();ctx.arc(n.x,n.y,7,0,6.283);ctx.fill();
      ctx.strokeStyle='#0b0d10';ctx.lineWidth=2;ctx.stroke();
      ctx.fillStyle='#e6ebf2';ctx.fillText(n.name,n.x+11,n.y+4);
    }
    ctx.restore();
    // The layout settles after 400 ticks and then nothing moves. Holding a 60fps
    // loop open to redraw an identical picture forever is the single most
    // expensive idle thing this shell used to do — so the loop simply ends, and
    // a resize or a wake kicks one more frame. An idle graph costs nothing.
    if(ticks<400)w.raf=requestAnimationFrame(step);
  };
  const kick=()=>{if(!w.raf)w.raf=requestAnimationFrame(step)};
  if(w._kgro)w._kgro.disconnect();
  w._kgro=new ResizeObserver(kick);w._kgro.observe(canvas);
  winTick(w,kick,0,{key:'paint'});                      // ms:0 — repaint when the window comes back, never on a timer
  kick();
}
async function kgAdd(){
  const s=$('#kg-s').value.trim(),rel=$('#kg-r').value.trim(),o=$('#kg-o').value.trim();
  if(!s||!rel||!o)return toast('need subject, relation and object');
  await fetch('/api/kg',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({subject:s,relation:rel,object:o})});
  refreshApp('kg');
}
async function kgClear(){
  if(!await osConfirm('Clear the entire knowledge graph?','This cannot be undone.',{danger:true,confirmText:'Clear'}))return;
  await fetch('/api/kg',{method:'DELETE'});refreshApp('kg');
}

