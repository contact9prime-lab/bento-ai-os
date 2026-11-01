/* ---------------- A sensor over time: Devices → Hardware → an item ----------------
   Asked for as "drill further to see the data visualization for the last 90 days". The hub keeps
   what each Zero's sensors read (telemetry.py); /api/devices/readings answers one item over a day,
   a week, 30 or 90 days as at most 360 points of [time, mean, min, max], with the range's numbers
   and the machine's events in it. One line in the theme's accent, its min to max as a faint band,
   events as hairlines, a crosshair that finds the time and says the value. Built with DOM nodes,
   text nodes only: an item's name came from another machine. */
var DEVCHART={key:'',item:'',range:'day',data:null,busy:false};
var DEVCHART_RANGES=[['day','Day'],['week','Week'],['month','30 days'],['quarter','90 days']];
var DEVCHART_EVENT={found:'＋',gone:'－',power:'⚡',offline:'○',online:'●',updated:'⬆',board:'▦'};

function devChartOpen(key,item){
  const same=DEVCHART.key===key&&DEVCHART.item===item;
  DEVCHART.key=same?'':key;DEVCHART.item=same?'':item;DEVCHART.data=null;
  if(typeof netPaint==='function')netPaint();
}
/* the placeholder netHardwareHTML puts under the open item; filled after each paint */
function devChartSlot(key,item){
  return DEVCHART.key===key&&DEVCHART.item===item?`<div class="dev-chart" data-key="${esc(key)}" data-item="${esc(item)}"></div>`:'';
}
async function devChartFill(box){
  const slot=box.querySelector('.dev-chart');if(!slot)return;
  if(DEVCHART.data&&DEVCHART.data.item===DEVCHART.item&&DEVCHART.data.range===DEVCHART.range&&DEVCHART.data._key===DEVCHART.key)
    return devChartDraw(slot,DEVCHART.data);
  devChartDraw(slot,DEVCHART.data,true);
  try{
    const d=await apiJSON(`/api/devices/readings?key=${encodeURIComponent(DEVCHART.key)}&item=${encodeURIComponent(DEVCHART.item)}&range=${DEVCHART.range}`);
    d._key=DEVCHART.key;DEVCHART.data=d;
  }catch(e){slot.textContent='';const p=document.createElement('p');p.className='mut';p.textContent=String(e.message||e);slot.appendChild(p);return}
  document.querySelectorAll('.dev-chart').forEach(s=>devChartDraw(s,DEVCHART.data));
}
function devChartBinary(d){return d.kind==='gpio'||d.item==='power.throttle'}
function devChartFmt(d,v){
  if(v==null)return '—';
  if(devChartBinary(d)){
    if(d.item==='power.throttle')return v>=.5?'under-voltage or throttled':'fine';
    return v===1?'high':v===0?'low':`high ${Math.round(v*100)}% of the time`;
  }
  const n=Math.abs(v)>=100?Math.round(v):Math.round(v*10)/10;
  return `${n}${d.unit==='°C'?'°C':d.unit?' '+d.unit:''}`;
}
function devChartWhen(d,t){
  const dt=new Date(t*1000);
  return d.range==='day'?dt.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})
    :dt.toLocaleDateString([],{month:'short',day:'numeric'})+(d.range==='week'?' '+dt.toLocaleTimeString([],{hour:'2-digit'}):'');
}
function devEl(tag,attrs,text){
  const svg=['svg','path','line','rect','circle','text','g','title'].includes(tag);
  const n=svg?document.createElementNS('http://www.w3.org/2000/svg',tag):document.createElement(tag);
  for(const k in attrs||{})n.setAttribute(k,attrs[k]);
  if(text!=null)n.textContent=text;
  return n;
}
function devChartDraw(slot,d,loading){
  slot.textContent='';
  const head=devEl('div',{class:'dev-chart-head'});
  const seg=devEl('div',{class:'seg dev-chart-range',role:'tablist','aria-label':'Range'});
  DEVCHART_RANGES.forEach(([id,label])=>{
    const b=devEl('button',{role:'tab','aria-selected':String(DEVCHART.range===id)},label);
    if(DEVCHART.range===id)b.classList.add('on');
    b.onclick=()=>{DEVCHART.range=id;devChartFill(slot.closest('.devhub-box,#s-net')||document)};
    seg.appendChild(b);
  });
  head.appendChild(seg);
  // a mission that starts when this thing does something (devtrig.py, the Missions editor)
  if(typeof devWhen==='function'&&typeof netRow==='function'){
    const r=netRow(DEVCHART.key),m=r.here?r.display:((r.links||[])[0]||{}).label;
    if(m&&!/\.text_sensor\./.test(DEVCHART.item)){
      const w=devEl('button',{class:'endbtn dev-chart-when',type:'button'},'Start a mission when…');
      w.onclick=()=>devWhen(m,DEVCHART.item);head.appendChild(w)}
  }
  slot.appendChild(head);
  if(loading&&!d){slot.appendChild(devEl('p',{class:'mut'},'Reading…'));return}
  if(loading)slot.classList.add('busy');else slot.classList.remove('busy');
  const st=d.stats||{},pts=d.points||[];
  const stats=devEl('div',{class:'dev-chart-stats'});
  [['Last',st.last],['Min',st.min],['Max',st.max],['Mean',st.mean]].forEach(([k,v])=>{
    if(devChartBinary(d)&&(k==='Min'||k==='Max'))return;
    const s=devEl('span');s.appendChild(devEl('small',{},k));s.appendChild(devEl('b',{},devChartFmt(d,v)));stats.appendChild(s);
  });
  head.appendChild(stats);
  if(!pts.length){
    slot.appendChild(devEl('p',{class:'mut dev-chart-empty'},`No readings from ${d.machine} in ${d.words} yet. A Pi on 0.7.1 or later sends them every minute.`));
    return;
  }
  const W=Math.max(280,slot.clientWidth||600),H=W<480?150:180,L=48,R=10,T=16,B=24;
  let lo=Math.min(...pts.map(p=>p[2])),hi=Math.max(...pts.map(p=>p[3]));
  if(devChartBinary(d)){lo=0;hi=1}
  else{if(hi===lo){hi+=1;lo-=1}const pad=(hi-lo)*.08;hi+=pad;lo-=pad}
  // readings that began well after the range did (a Pi that started sending today) fill the
  // width from where they begin, and the line under the chart says so
  const x0=pts[0][0]-d.start>(d.end-d.start)*.2?Math.max(d.start,pts[0][0]-d.step):d.start;
  const span=d.end-x0,fine=span<2*86400;
  const x=t=>L+(t-x0)/span*(W-L-R),y=v=>T+(1-(v-lo)/(hi-lo))*(H-T-B);
  const svg=devEl('svg',{viewBox:`0 0 ${W} ${H}`,width:W,height:H,class:'dev-chart-svg',tabindex:'0',role:'img',
    'aria-label':`${d.name} on ${d.machine}, ${d.words}: last ${devChartFmt(d,st.last)}, mean ${devChartFmt(d,st.mean)}`});
  const ticks=devChartBinary(d)?[0,1]:[lo+(hi-lo)*.1,lo+(hi-lo)*.5,lo+(hi-lo)*.9];
  ticks.forEach(v=>{
    svg.appendChild(devEl('line',{x1:L,x2:W-R,y1:y(v),y2:y(v),class:'dc-grid'}));
    const lab=devChartBinary(d)?(d.item==='power.throttle'?(v?'bad':'fine'):(v?'high':'low')):devChartFmt({...d,unit:''},v);
    svg.appendChild(devEl('text',{x:L-6,y:y(v)+4,class:'dc-y'},lab));
  });
  [x0,(x0+d.end)/2,d.end].forEach((t,i)=>svg.appendChild(devEl('text',{x:x(t),y:H-6,class:'dc-x',
    'text-anchor':['start','middle','end'][i]},i===2?'now':devChartWhen({...d,range:fine?'day':d.range},t))));
  // runs of points with no gap longer than two and a half steps: a Pi that was away is a break
  const runs=[];let run=[];
  pts.forEach((p,i)=>{if(i&&p[0]-pts[i-1][0]>d.step*2.5){runs.push(run);run=[]}run.push(p)});runs.push(run);
  runs.forEach(r=>{
    if(!devChartBinary(d)&&r.length>1){
      const top=r.map((p,i)=>`${i?'L':'M'}${x(p[0]).toFixed(1)},${y(p[3]).toFixed(1)}`).join('');
      const bot=r.slice().reverse().map(p=>`L${x(p[0]).toFixed(1)},${y(p[2]).toFixed(1)}`).join('');
      svg.appendChild(devEl('path',{d:top+bot+'Z',class:'dc-band'}));
    }
    const step=devChartBinary(d);
    const line=r.map((p,i)=>i?(step?`H${x(p[0]).toFixed(1)}V${y(p[1]).toFixed(1)}`:`L${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`)
      :`M${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join('');
    svg.appendChild(devEl('path',{d:r.length>1?line:line+`h1`,class:'dc-line'}));
  });
  // one unplug is several lines (a receiver, its keyboard, its mouse): one mark, every line in it
  const evs=[];(d.events||[]).forEach(e=>{const same=evs.find(o=>o.event===e.event&&Math.abs(o.at-e.at)<2);
    if(same)same.text+='\n'+e.text;else evs.push({...e})});
  evs.forEach(e=>{
    const ex=x(e.at);if(ex<L||ex>W-R)return;
    const g=devEl('g',{class:'dc-ev'});g.appendChild(devEl('line',{x1:ex,x2:ex,y1:T,y2:H-B}));
    g.appendChild(devEl('text',{x:ex,y:T-4,'text-anchor':'middle'},DEVCHART_EVENT[e.event]||'·'));
    g.appendChild(devEl('title',{},`${devChartWhen({...d,range:'week'},e.at)}: ${e.text}`));svg.appendChild(g);
  });
  const cross=devEl('line',{y1:T,y2:H-B,class:'dc-cross',visibility:'hidden'});
  const dot=devEl('circle',{r:4,class:'dc-dot',visibility:'hidden'});
  svg.appendChild(cross);svg.appendChild(dot);
  const tip=devEl('div',{class:'dc-tip',hidden:''});
  const wrap=devEl('div',{class:'dev-chart-plot'});wrap.appendChild(svg);wrap.appendChild(tip);slot.appendChild(wrap);
  let at=pts.length-1;
  const show=i=>{
    at=Math.max(0,Math.min(pts.length-1,i));const p=pts[at],px=x(p[0]),py=y(p[1]);
    cross.setAttribute('x1',px);cross.setAttribute('x2',px);cross.setAttribute('visibility','visible');
    dot.setAttribute('cx',px);dot.setAttribute('cy',py);dot.setAttribute('visibility','visible');
    tip.textContent='';tip.appendChild(devEl('b',{},devChartFmt(d,p[1])));
    tip.appendChild(devEl('span',{},devChartWhen({...d,range:d.range==='day'?'day':'week'},p[0])));
    if(!devChartBinary(d)&&p[2]!==p[3])tip.appendChild(devEl('span',{class:'mut'},`${devChartFmt(d,p[2])} to ${devChartFmt(d,p[3])}`));
    tip.hidden=false;
    const r=svg.getBoundingClientRect(),k=r.width/W;
    tip.style.left=Math.min(r.width-tip.offsetWidth-4,Math.max(4,px*k+10))+'px';tip.style.top=Math.max(0,py*k-40)+'px';
  };
  const hide=()=>{cross.setAttribute('visibility','hidden');dot.setAttribute('visibility','hidden');tip.hidden=true};
  svg.addEventListener('pointermove',e=>{
    const r=svg.getBoundingClientRect(),t=d.start+((e.clientX-r.left)/r.width*W-L)/(W-L-R)*(d.end-d.start);
    let best=0;pts.forEach((p,i)=>{if(Math.abs(p[0]-t)<Math.abs(pts[best][0]-t))best=i});show(best);
  });
  svg.addEventListener('pointerleave',hide);svg.addEventListener('blur',hide);
  svg.addEventListener('focus',()=>show(at));
  svg.addEventListener('keydown',e=>{if(e.key==='ArrowLeft'){show(at-1);e.preventDefault()}
    else if(e.key==='ArrowRight'){show(at+1);e.preventDefault()}});
  // the numbers without hovering: every point the chart draws
  if(x0>d.start)slot.appendChild(devEl('p',{class:'mut dev-chart-since'},
    `${d.machine} has sent readings since ${devChartWhen({...d,range:fine?'day':'week'},pts[0][0]-d.step/2)}. The rest of ${d.words} fills in as it keeps sending.`));
  const det=devEl('details',{class:'dev-chart-table'});det.appendChild(devEl('summary',{},`Show the numbers (${pts.length})`));
  const tb=devEl('table');const hr=devEl('tr');['Time','Mean','Min','Max'].forEach(h=>hr.appendChild(devEl('th',{},h)));tb.appendChild(hr);
  pts.slice().reverse().forEach(p=>{const tr=devEl('tr');
    [devChartWhen({...d,range:'week'},p[0]),devChartFmt(d,p[1]),devChartFmt(d,p[2]),devChartFmt(d,p[3])].forEach(v=>tr.appendChild(devEl('td',{},v)));
    tb.appendChild(tr)});
  det.appendChild(tb);slot.appendChild(det);
}
