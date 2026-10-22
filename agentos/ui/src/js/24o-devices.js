/* ---------------- Devices: the machines on your network, in a window of their own ----------------
   Asked for as "have these devices in the device hub in Bento". The same list as Settings →
   Network (netPaint draws into every .devhub-box), so the two never disagree: each machine,
   what it is to Bento, its switches as last read, Controls, Install and Remove. */
async function renderDevices(body,w){
  const pb=panelShell(body,{title:'Devices',sub:'The machines on your network'});
  pb.innerHTML=`<div class="devhub-box" id="devhub-${esc(w&&w.id||'0')}"><p class="mut">…</p></div>`;
  await netPaint();
}

/* The map: this computer in the middle with its lead agent, every machine with Bento around it
   with ITS agent (the face painted here from the recipe its link or its switches gave), and the
   rest of the network as small dots on an outer ring, so twenty phones don't crowd the Pis. A
   line is a tie: solid for a link or the community, dashed for Bento with no tie yet. A node is
   a door to that machine's Controls below. Positions are percentages, so it fits any width. */
function devMapHTML(v){
  const rows=(v.rows||[]).filter(r=>!r.ignored);
  const bento=rows.filter(r=>r.bento!=='none'&&r.bento!=='removed').slice(0,12);
  const rest=rows.filter(r=>!bento.includes(r));
  const me=v.me||{},pos=(i,n,rx,ry,off)=>{const a=-Math.PI/2+(off||0)+2*Math.PI*i/Math.max(n,1);
    return [50+rx*Math.cos(a),50+ry*Math.sin(a)]};
  const lines=[],nodes=[];
  bento.forEach((r,i)=>{
    const [x,y]=pos(i,bento.length,34,30),tied=(r.connections||[]).some(c=>c.kind!=='key');
    // from the edge of the middle to the edge of the face, never through a name
    const at=t=>[(50+(x-50)*t).toFixed(2),(50+(y-50)*t).toFixed(2)];
    const [ax,ay]=at(.2),[bx,by]=at(.78);
    lines.push(`<line x1="${ax}" y1="${ay}" x2="${bx}" y2="${by}" class="${tied?'tie':'loose'}"/>`);
    const ag=r.agent||{},st=((r.controls||{}).state)||{};
    const face=ag.look&&Object.keys(ag.look).length?avatarRecipeImg(ag.look,'devmap-face',ag.name||'')
      :`<span class="devmap-face devmap-initial">${esc((ag.name||r.display||'?').slice(0,1).toUpperCase())}</span>`;
    const dot=st.running===true?'up':st.running===false?'down':'';
    // above the middle, the name goes above the face, so the line meets the face
    nodes.push(`<button class="devmap-n${y<50?' up':''}" style="left:${x.toFixed(2)}%;top:${y.toFixed(2)}%" data-devnode="${esc(r.key)}"
        aria-label="${esc((ag.name?ag.name+' on ':'')+r.display)}">
      <span class="devmap-ring ${dot}">${face}</span>
      <b>${esc(ag.name||'Bento')}</b><span class="mut">${esc(r.display)}</span></button>`);
  });
  rest.forEach((r,i)=>{const [x,y]=pos(i,rest.length,47,46,Math.PI/rest.length);
    nodes.push(`<span class="devmap-dot" style="left:${x.toFixed(2)}%;top:${y.toFixed(2)}%" title="${esc(r.display+(r.ip&&r.ip!==r.display?' · '+r.ip:''))}"></span>`)});
  const meFace=typeof avatarImg==='function'?avatarImg('@agent','devmap-face'):'';
  return `<div class="devmap" role="img" aria-label="Map of the machines on your network">
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">${lines.join('')}</svg>
    ${nodes.join('')}
    <div class="devmap-n devmap-me" style="left:50%;top:50%"><span class="devmap-ring up">${meFace}</span>
      <b>${esc(me.agent||'Your agent')}</b><span class="mut">${esc(me.name||'this computer')}</span></div>
    ${rest.length?`<p class="devmap-more mut">${rest.length} other machine${rest.length===1?'':'s'} on your network, without Bento</p>`:''}
    ${!bento.length?`<p class="devmap-empty mut">No other machine runs Bento yet. Install it on one below.</p>`:''}
  </div>`;
}
function devMapGo(key){
  NET.open=key;NET.mode='controls';NET.more='';
  netPaint().then(()=>{const m=document.querySelector(`.devhub-box .net-m[data-key="${CSS.escape(key)}"]`);
    if(m)m.scrollIntoView({block:'start',behavior:'smooth'})});
}
