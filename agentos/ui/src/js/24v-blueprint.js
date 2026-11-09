/* ================= the Stage's blueprint: a thing taken apart, level by level =================
   stage.py's `blueprint` kind is the closed set; this draws it. Asked for as "give me a fine
   blueprint of Burj Khalifa … it opens the building inside out and I can drill into anything",
   and as a Jarvis-style look that gets to the bottom of things rather than presenting a chart.
   The X-ray (agentos/xray.py) is the same scene built from this machine's own records.

   Five rules:
   - Every word is text (textContent, SVG text nodes), the Stage's rule: a part's words are a
     model's, often copied off a page.
   - The parts nest, so drilling is drawn here at once with no model call. Past the last level,
     "Take this apart" asks the agent (stageDeeper with the part's id), and the answer plays
     next on the Stage with the way back.
   - A state is never colour alone: each status is an icon AND a word, and certainty is the
     line itself (solid known, dashed estimated, dotted unclear), with a legend.
   - Sized from the drawing's LAYOUT box (clientWidth), never getBoundingClientRect: a window
     opening under a scale transform made the remote page 320x240 once. A ResizeObserver
     redraws it, and is dropped when the drawing leaves the page.
   - Nothing moves forever: the parts draw in once, the scan line crosses once, the tour (while
     the story plays) stops at the first touch. Reduced motion draws it still.

   Three faces: the GUI is this file; the TUI and the terminal chat print a blueprint as an
   indented tree (stage.text) and `bento stage xray` prints an X-ray the same way; in SUI it is a
   page like any other, and nothing here touches the compositor.

   Loaded after 24l-stage.js, whose sEl/sSvg/stageTicks/stageReduced it uses; function
   declarations hoist across the bundle, and the Telegram page embeds both files. */

var BP_INK='#7dd3fc', BP_HI='#f8fafc', BP_DIM='rgba(125,211,252,.42)';
var BP_STATUS={ok:['✓','done','#34d399'],refused:['✕','refused','#f87171'],asked:['?','asked you','#fbbf24'],
  waiting:['⏸','waiting','#fbbf24'],failed:['⚠','failed','#f87171'],stopped:['■','stopped','#94a3b8'],
  running:['●','running','#7dd3fc']};
var BP_DASH={known:'',estimated:'7 5',unclear:'1.5 4.5'};
var BP_CERT_WORD={known:'known',estimated:'estimated',unclear:'unclear'};

function bpKids(n){return (n&&n.parts)||[]}
function bpNode(st){   // the level on screen: the subject, or the part at the end of the path
  let n={name:st.sc.subject||st.sc.title,parts:st.sc.parts,form:st.sc.form,role:'',root:true};
  for(const id of st.path){const k=bpKids(n).find(p=>p.id===id);if(!k)break;n=k}
  return n;
}
function bpFind(parts,id){for(const p of parts||[]){if(p.id===id)return p;const k=bpFind(p.parts,id);if(k)return k}return null}
function bpCount(parts){return (parts||[]).reduce((t,p)=>t+1+bpCount(p.parts),0)}
function bpDepth(parts){return (parts||[]).reduce((d,p)=>Math.max(d,1+bpDepth(p.parts)),0)}
function bpVal(f){const v=String(f.value==null?'':f.value),u=String(f.unit||'');
  if(!u||v.indexOf(u)>=0)return v;return /^[A-Za-z]/.test(u)?v+' '+u:v+u}
function bpFmt(n){if(n==null||!isFinite(n))return '';const a=Math.abs(n);
  return a>=1000?Math.round(n).toLocaleString():a>=10?String(Math.round(n)):String(Math.round(n*10)/10)}
function bpHover(){try{return matchMedia('(hover:hover)').matches}catch(e){return false}}

/* ---------- the scene ---------- */
function stageBlueprint(art,sc){
  art.classList.add('bp-art');
  const st={sc,path:[],sel:null,peek:null,tour:null,art,
    live:!window.STAGE_REPORT&&typeof STAGE!=='undefined'&&STAGE.cur&&!STAGE.cur.xray,
    seq:(typeof STAGE!=='undefined'&&STAGE.scenes&&STAGE.scenes[STAGE.at]&&STAGE.scenes[STAGE.at].scene===sc)?STAGE.scenes[STAGE.at].seq:0};
  art._bp=st;
  const wrap=sEl('div','bp');
  const crumbs=sEl('div','bp-crumbs');
  const body=sEl('div','bp-body');
  const draw=sEl('div','bp-draw');
  const svg=sSvg('svg',{class:'bp-svg',role:'group','aria-label':'Blueprint of '+(sc.subject||sc.title||'it')});
  draw.append(svg);
  const spec=sEl('aside','bp-spec');spec.setAttribute('aria-live','polite');
  const loc=sEl('div','bp-loc');loc.setAttribute('aria-hidden','true');
  body.append(draw,spec);wrap.append(crumbs,body);art.append(wrap);
  const info=sEl('div','bp-info');
  // a phone reads the part under its finger here, over the drawing; the panel is below it
  const peek=sEl('div','bp-peek');peek.hidden=true;draw.append(peek);
  st.el={wrap,crumbs,draw,svg,loc,spec,info,peek};
  art.tabIndex=-1;
  art.addEventListener('keydown',e=>bpKey(st,e));
  if(typeof ResizeObserver!=='undefined'){
    let last='';st.ro=new ResizeObserver(()=>{
      if(!art.isConnected){st.ro.disconnect();return}
      const k=draw.clientWidth+'x'+draw.clientHeight;if(k!==last){last=k;bpRender(st,'')}});
    st.ro.observe(draw);
  }
  bpRender(st,'in');
  if(typeof STAGE!=='undefined'&&STAGE.playing&&!window.STAGE_REPORT)bpTour(st);
}

function bpNarrow(st){return st.art.clientWidth<700}
function bpRender(st,how){
  const {svg,draw}=st.el;
  // a narrow Stage scrolls: the drawing takes the room you can see, the panel waits below
  const lvl=st.path.join('/');if(st.wantFor!==lvl){st.wantFor=lvl;st.wantH=0}
  if(bpNarrow(st)&&!window.STAGE_REPORT){
    const h=Math.max(300,st.art.clientHeight-st.el.crumbs.offsetHeight-12,st.wantH||0);
    if(Math.abs((parseFloat(draw.style.height)||0)-h)>2)draw.style.height=h+'px';
  }else if(draw.style.height)draw.style.height='';
  const W=Math.max(280,draw.clientWidth||900),H=Math.max(260,draw.clientHeight||520);
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('width',W);svg.setAttribute('height',H);
  svg.style.setProperty('--bp-h',H+'px');
  svg.textContent='';
  svg.classList.toggle('bp-still',stageReduced()||!!window.STAGE_STILL);
  svg.classList.remove('bp-in','bp-back');void svg.getBoundingClientRect();
  if(how&&!stageReduced())svg.classList.add('bp-'+how);
  bpGrid(svg,W,H);
  const node=bpNode(st),kids=bpKids(node);
  const world=sSvg('g',{class:'bp-world'});svg.append(world);
  const form=node.form||(node.root?st.sc.form:'')||'exploded';
  st.needH=0;
  const L=(form==='tower'?bpTower:form==='flow'?bpFlow:bpExploded)(world,node,kids,W,H,st);
  if(st.needH>H+2&&bpNarrow(st)&&!st.grown){st.grown=true;st.wantH=st.needH;const r=bpRender(st,how);st.grown=false;return r}
  st.items=L;
  bpLinks(world,L,st,form);
  if(!stageReduced()&&!window.STAGE_STILL&&how){
    const scan=sSvg('rect',{class:'bp-scan',x:0,y:0,width:W,height:3});svg.append(scan)}
  st.form=form;
  bpCrumbs(st);
  bpSpec(st);
  bpMark(st);
}

/* ---------- the drafting sheet ---------- */
var BP_UID=0;
function bpGrid(svg,W,H){
  const id='bp'+(++BP_UID),d=sSvg('defs');
  const p1=sSvg('pattern',{id:id+'-g',width:16,height:16,patternUnits:'userSpaceOnUse'});
  p1.append(sSvg('path',{d:'M16 0H0V16',fill:'none',stroke:'rgba(125,211,252,.07)','stroke-width':1}));
  const p2=sSvg('pattern',{id:id+'-G',width:80,height:80,patternUnits:'userSpaceOnUse'});
  p2.append(sSvg('rect',{width:80,height:80,fill:'url(#'+id+'-g)'}),
    sSvg('path',{d:'M80 0H0V80',fill:'none',stroke:'rgba(125,211,252,.14)','stroke-width':1}));
  const hatch=sSvg('pattern',{id:id+'-h',width:8,height:8,patternUnits:'userSpaceOnUse',patternTransform:'rotate(45)'});
  hatch.append(sSvg('line',{x1:0,y1:0,x2:0,y2:8,stroke:'rgba(125,211,252,.28)','stroke-width':1.2}));
  const glow=sSvg('filter',{id:id+'-glow',x:'-30%',y:'-30%',width:'160%',height:'160%'});
  glow.append(sSvg('feGaussianBlur',{stdDeviation:'2.4',result:'b'}));
  const m=sSvg('feMerge');m.append(sSvg('feMergeNode',{in:'b'}),sSvg('feMergeNode',{in:'SourceGraphic'}));glow.append(m);
  const ah=sSvg('marker',{id:id+'-a',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'});
  ah.append(sSvg('path',{d:'M0 1L10 5L0 9z',fill:BP_INK}));
  d.append(p1,p2,hatch,glow,ah);svg.append(d);
  svg.append(sSvg('rect',{class:'bp-sheet',x:0,y:0,width:W,height:H,fill:'url(#'+id+'-G)'}));
  // registration marks in the corners, as on a drawing
  [[10,10,1,1],[W-10,10,-1,1],[10,H-10,1,-1],[W-10,H-10,-1,-1]].forEach(([x,y,a,b])=>
    svg.append(sSvg('path',{d:`M${x} ${y+14*b}V${y}H${x+14*a}`,class:'bp-reg'})));
  svg.dataset.uid=id;
}
function bpId(svg,k){return 'url(#'+svg.dataset.uid+'-'+k+')'}
function bpSvgOf(g){return g.ownerSVGElement||g}

/* ---------- a part on the sheet ---------- */
function bpPartG(world,p,i,st){
  const g=sSvg('g',{class:'bp-p c-'+(p.certainty||'known')+(p.status?' s-'+p.status:''),tabindex:0,role:'button',
    'data-id':p.id,'aria-label':p.name+(p.role?': '+p.role:'')+(bpKids(p).length?'. '+bpKids(p).length+' parts inside':'')});
  g.style.setProperty('--i',i);
  g.addEventListener('click',e=>{e.stopPropagation();bpTap(st,p,e)});
  g.addEventListener('pointerenter',e=>{if(e.pointerType==='mouse'){st.peek=p.id;bpSpec(st);bpMark(st)}});
  g.addEventListener('pointerleave',e=>{if(e.pointerType==='mouse'&&st.peek===p.id){st.peek=null;bpSpec(st);bpMark(st)}});
  g.addEventListener('focus',()=>{st.peek=p.id;bpSpec(st);bpMark(st)});
  g.addEventListener('blur',()=>{if(st.peek===p.id){st.peek=null;bpSpec(st);bpMark(st)}});
  world.append(g);return g;
}
function bpShape(g,tag,attrs,p){
  const e=sSvg(tag,Object.assign({class:'bp-edge'},attrs));
  const d=BP_DASH[p.certainty||'known'];if(d)e.setAttribute('stroke-dasharray',d);
  g.append(e);return e;
}
function bpBadge(g,p,x,y){
  if(!p.status||!BP_STATUS[p.status])return;
  const [ic,,col]=BP_STATUS[p.status];
  const b=sSvg('g',{class:'bp-badge'});
  b.append(sSvg('circle',{cx:x,cy:y,r:8,fill:'#061a33',stroke:col,'stroke-width':1.4}),
    sSvg('text',{x,y:y+3.6,'text-anchor':'middle',fill:col,'font-size':10,'font-weight':700},ic));
  g.append(b);
}
/* one line of text that fits `w` px, cut at a word */
function bpText(parent,x,y,str,w,cls,anchor){
  const t=sSvg('text',{x,y,class:cls||'','text-anchor':anchor||'start'},str);parent.append(t);
  if(w&&t.getComputedTextLength&&t.getComputedTextLength()>w){
    let s=String(str);while(s.length>3&&t.getComputedTextLength()>w){s=s.replace(/\s*\S+$/,'');if(!/\s/.test(s)){s=s.slice(0,-2)}t.textContent=s+'…'}
  }
  return t;
}
/* up to `lines` lines that fit `w` px, words kept whole, the last cut with an ellipsis */
function bpWrap(parent,x,y,str,w,lines,cls,lh,anchor){
  const words=String(str||'').split(/\s+/).filter(Boolean);let line='',n=0,i=0;lh=lh||14;
  while(i<words.length&&n<lines){
    const t=sSvg('text',{x,y:y+n*lh,class:cls||'','text-anchor':anchor||'start'},'');parent.append(t);line='';
    while(i<words.length){const nxt=line?line+' '+words[i]:words[i];t.textContent=nxt;
      if(t.getComputedTextLength&&t.getComputedTextLength()>w){
        if(line){t.textContent=line;break}
        // one word wider than the line (a path, a URL): keep its end, which is the part that names it
        let wd=words[i];while(wd.length>4&&t.getComputedTextLength()>w){wd=wd.slice(2);t.textContent='…'+wd}
        line=t.textContent;i++;break}
      line=nxt;i++}
    if(n===lines-1&&i<words.length){bpText(parent,x,y+n*lh,t.textContent+' '+words.slice(i).join(' '),w,cls,anchor);t.remove()}
    n++;
  }
  return n;
}
function bpSub(p){   // the second line under a part's name: its first fact, else its role
  const f=(p.facts||[])[0];return f?((f.label?f.label+' ':'')+bpVal(f)):(p.role||'')}

/* ---------- tower: built in layers along a height, bottom first ---------- */
function bpTower(world,node,kids,W,H,st){
  const out=[],unit=node.root?(st.sc.unit||''):(st.sc.unit||'');
  const have=kids.every(p=>p.from!=null&&p.to!=null);
  const spans=kids.map((p,i)=>have?[p.from,p.to]:[i,i+1]);
  let lo=Math.min(0,...spans.map(s=>s[0])),hi=Math.max(...spans.map(s=>s[1]));if(hi<=lo)hi=lo+1;
  // a part that runs most of the height beside others is inside the tower (a core, a lift
  // shaft): drawn as a shaft, not stacked as a floor
  const range=hi-lo;
  const shaft=kids.map((p,i)=>have&&(spans[i][1]-spans[i][0])>=range*.55&&
    spans.some((s,j)=>j!==i&&s[0]<spans[i][1]&&s[1]>spans[i][0]));
  const narrow=W<560,two=!narrow&&kids.length>7;
  const top=30,bot=narrow?34:44,left=narrow?54:64;
  const cx=narrow?Math.max(left+56,W*.3):two?W*.5:W*.38;
  const plotH=H-top-bot,k=plotH/(hi-lo);
  // a width over 1 is the real width in the drawing's unit, drawn to the same scale as the
  // height: the Burj Khalifa comes out as slender as it is. 0 to 1 is a share of the widest.
  const real=kids.some(p=>p.width!=null&&p.width>1);
  const cap=narrow?W*.3:two?W*.2:W*.26;
  const maxW=real?Math.min(cap,Math.max(...kids.map(p=>(p.width||0)))*k):Math.min(cap,240,plotH*.62);
  const wScale=real?Math.min(k,cap/Math.max(1,...kids.map(p=>p.width||0))):0;
  const y=v=>top+(hi-v)*k;
  const svg=bpSvgOf(world);
  // ground and what is under it
  if(lo<0){
    const gy=y(0);
    world.append(sSvg('rect',{x:16,y:gy,width:W-32,height:Math.max(0,y(lo)-gy+10),fill:bpId(svg,'h'),class:'bp-earth'}));
    world.append(sSvg('line',{x1:16,y1:gy,x2:W-16,y2:gy,class:'bp-ground'}));
    // the axis marks 0 already; on a narrow sheet this word would sit on a label
    if(!narrow)bpText(world,W-20,gy-6,'ground · 0'+(unit?' '+unit:''),0,'bp-tiny','end');
  }else world.append(sSvg('line',{x1:16,y1:y(lo),x2:W-16,y2:y(lo),class:'bp-ground'}));
  // the height axis
  world.append(sSvg('line',{x1:left-14,y1:y(hi),x2:left-14,y2:y(lo),class:'bp-axis'}));
  (typeof stageTicks==='function'?stageTicks(lo,hi,narrow?4:6):[lo,hi]).forEach(t=>{
    const ty=y(t);world.append(sSvg('line',{x1:left-19,y1:ty,x2:left-9,y2:ty,class:'bp-axis'}));
    bpText(world,left-22,ty+3.5,(t>0?'+':'')+bpFmt(t),0,'bp-tiny','end')});
  if(unit)bpText(world,left-14,top-12,unit,0,'bp-tiny','middle');
  // the centreline, dash-dot, as on a drawing
  world.append(sSvg('line',{x1:cx,y1:y(hi)-10,x2:cx,y2:y(lo)+6,class:'bp-cl'}));
  const stacked=kids.map((p,i)=>i).filter(i=>!shaft[i]);
  const wOf=i=>{const p=kids[i];if(p.width!=null)return p.width;
    const j=stacked.indexOf(i),n=Math.max(1,stacked.length-1);return j<0?.08:.92-.7*(j/n)};
  const pxW=i=>real?(kids[i].width!=null?(kids[i].width>1?kids[i].width*wScale:kids[i].width*maxW):maxW*.5):maxW*wOf(i);
  // the outline of the whole, drawn once behind the parts with a glow: the silhouette
  const sil=stacked.map(i=>[spans[i][0],spans[i][1],Math.max(4,pxW(i))]).sort((a,b)=>a[0]-b[0]);
  if(sil.length>1){let r='',l='';sil.forEach(([a,b,w])=>{r+=`L${cx+w/2} ${y(a)}L${cx+w/2} ${y(b)}`;l=`L${cx-w/2} ${y(b)}L${cx-w/2} ${y(a)}`+l});
    world.append(sSvg('path',{d:'M'+cx+' '+y(sil[0][0])+r+'L'+cx+' '+y(sil[sil.length-1][1])+l+'Z',class:'bp-sil',filter:bpId(svg,'glow')}))}
  stacked.forEach((i,j)=>{
    const p=kids[i],[a,b]=spans[i];const w=Math.max(4,pxW(i));
    const y0=y(b),y1=y(a),h=Math.max(3,y1-y0);
    const g=bpPartG(world,p,j,st);
    g.append(sSvg('rect',{x:cx-Math.max(w,24)/2,y:y0-Math.max(0,(14-h)/2),width:Math.max(w,24),height:Math.max(h,14),class:'bp-hit'}));
    g.append(sSvg('rect',{x:cx-w/2,y:y0,width:w,height:h,class:'bp-fill'}));
    // floor lines inside a section
    if(h>14){const fl=sSvg('g',{class:'bp-floors'});const step=Math.max(5,Math.min(9,h/10));
      for(let fy=y0+step;fy<y1-2;fy+=step)fl.append(sSvg('line',{x1:cx-w/2+2,y1:fy,x2:cx+w/2-2,y2:fy}));g.append(fl)}
    bpShape(g,'rect',{x:cx-w/2,y:y0,width:w,height:h},p);
    if(bpKids(p).length&&h>16)g.append(sSvg('text',{x:cx,y:y0+h/2+4,'text-anchor':'middle',class:'bp-plus'},'⊕'));
    bpBadge(g,p,cx+w/2,y0);
    // an elevation mark at the top of each section
    world.append(sSvg('path',{d:`M${cx-w/2-9} ${y0-5}l4 5l4 -5z`,class:'bp-elev'}));
    out.push({p,g,box:[cx-w/2,y0,w,h],anchor:[cx+w/2,y0+h/2],left:[cx-w/2,y0+h/2]});
  });
  // a part as wide as the tower that runs its height wraps it (a facade, a skin): drawn as an
  // envelope round the outline, not as a line down the middle
  const widestW=Math.max(1,...stacked.map(i=>kids[i].width||0));
  const wraps=i=>shaft[i]&&kids[i].width!=null&&kids[i].width>=(real?widestW*.9:.9);
  kids.forEach((p,i)=>{if(!wraps(i))return;
    const [a,b]=spans[i],secs=sil.filter(([s0,s1])=>s1>a&&s0<b);if(!secs.length)return;
    const pad=6;let r='',l='';
    secs.forEach(([s0,s1,w])=>{const y0=y(Math.min(s1,b)),y1=y(Math.max(s0,a));r+=`L${cx+w/2+pad} ${y1}L${cx+w/2+pad} ${y0}`;l=`L${cx-w/2-pad} ${y0}L${cx-w/2-pad} ${y1}`+l});
    const g=bpPartG(world,p,stacked.length,st);g.classList.add('bp-wrap');
    const d='M'+cx+' '+y(Math.max(secs[0][0],a))+r+'L'+cx+' '+y(Math.min(secs[secs.length-1][1],b))+l+'Z';
    g.append(sSvg('path',{d,class:'bp-hitline'}));
    bpShape(g,'path',{d},p);
    const hy=y(Math.max(secs[0][0],a))-(y(Math.max(secs[0][0],a))-y(Math.min(secs[secs.length-1][1],b)))*.62;
    const hw=(secs.find(([s0,s1])=>y(s0)>=hy&&y(s1)<=hy)||secs[0])[2];
    out.push({p,g,box:[cx-hw/2-pad,hy-6,hw+pad*2,12],anchor:[cx+hw/2+pad,hy],left:[cx-hw/2-pad,hy]});
    shaft[i]=false;
  });
  // the shafts inside, side by side on the centreline
  const sh=kids.map((p,i)=>i).filter(i=>shaft[i]&&!wraps(i));
  sh.forEach((i,k)=>{
    const p=kids[i],[a,b]=spans[i],w=Math.max(4,Math.min(maxW*.12,10));
    const x=cx-(sh.length*w*1.6)/2+k*w*1.6+w*.3,y0=y(b),h=Math.max(3,y(a)-y0);
    const g=bpPartG(world,p,stacked.length+k,st);g.classList.add('bp-shaft');
    bpShape(g,'rect',{x,y:y0,width:w,height:h},p);
    g.append(sSvg('rect',{x:x-6,y:y0,width:w+12,height:h,class:'bp-hit'}));
    out.push({p,g,box:[x,y0,w,h],anchor:[x+w,y0+h*.3],left:[x,y0+h*.3]});
  });
  // the overall height, as a dimension line beside the tower
  const above=Math.max(...spans.map(s=>s[1]));
  const widest=Math.max(8,...stacked.map(pxW));
  if(!narrow){const dx=cx-widest/2-34;
    world.append(sSvg('line',{x1:dx,y1:y(above),x2:dx,y2:y(Math.max(0,lo)),class:'bp-dim',
      'marker-start':bpId(svg,'a'),'marker-end':bpId(svg,'a')}));
    const ty=(y(above)+y(Math.max(0,lo)))/2;
    const t=sSvg('text',{x:dx-6,y:ty,class:'bp-dimt','text-anchor':'middle',transform:`rotate(-90 ${dx-6} ${ty})`},
      bpFmt(above-Math.max(0,lo))+(unit?' '+unit:''));world.append(t)}
  bpLabels(world,out,W,H,top,bot,cx,widest,two,narrow);
  return out;
}
/* Leader lines to labels in a column, spread so no two touch, the shortest way. */
function bpLabels(world,items,W,H,top,bot,cx,maxW,two,narrow){
  const cols=two?[[],[]]:[[]];
  items.slice().sort((a,b)=>a.anchor[1]-b.anchor[1]).forEach((it,i)=>cols[two?(i%2):0].push(it));
  cols.forEach((col,c)=>{
    const right=c===0;
    const lx=right?cx+maxW/2+(narrow?22:44):cx-maxW/2-60;
    const tw=right?W-lx-14:lx-74;
    const lo=top+8,hi=H-bot-6,avail=hi-lo,n=col.length;
    // two lines a label while they fit; one when they do not; never on top of each other
    let gap=narrow?30:34;const one=n*gap>avail;if(one)gap=Math.max(15,Math.min(20,avail/Math.max(1,n)));
    const yy=col.map(it=>it.anchor[1]);
    for(let k=0;k<n;k++)yy[k]=Math.max(yy[k],k?yy[k-1]+gap:lo);
    for(let k=n-1;k>=0;k--)yy[k]=Math.min(yy[k],k===n-1?hi:yy[k+1]-gap);
    if(n&&yy[0]<lo)for(let k=0;k<n;k++)yy[k]=lo+k*gap;
    col.forEach((it,k)=>{
      const [ax,ay]=right?it.anchor:it.left,ty=yy[k],ex=right?lx-6:lx+6;
      it.g.append(sSvg('path',{d:`M${ax} ${ay}H${(ax+ex)/2}L${ex} ${ty-4}`,class:'bp-lead'}));
      it.g.append(sSvg('circle',{cx:ax,cy:ay,r:2,class:'bp-dot'}));
      const lab=sSvg('g',{class:'bp-label'});it.g.append(lab);
      lab.append(sSvg('rect',{x:right?lx-4:lx-tw-4,y:ty-16,width:tw+8,height:one?gap:gap-2,class:'bp-hit'}));
      bpText(lab,lx,ty,it.p.name,tw,'bp-name',right?'start':'end');
      const sub=!one&&bpSub(it.p);if(sub)bpText(lab,lx,ty+14,sub,tw,'bp-subt',right?'start':'end');
      it.label=[lx,ty];
    });
  });
}
/* ---------- exploded: a thing made of parts round a core ---------- */
function bpExploded(world,node,kids,W,H,st){
  const out=[],n=kids.length,narrow=W<560;
  const few=n<=6;
  const bw=narrow?Math.min(W/2-20,170):Math.max(140,Math.min(few?250:200,W*(few?.22:.19))),bh=narrow?72:few?96:76;
  const cx=W/2,cy=narrow?66:H/2-6;
  const svg=bpSvgOf(world);
  // the housing: the whole, drawn assembled, with the parts pulled out of it
  const core=sSvg('g',{class:'bp-core'});world.append(core);
  const cr=narrow?46:Math.min(70,H*.13);
  core.append(sSvg('circle',{cx,cy,r:cr*1.9,class:'bp-ring'}),sSvg('circle',{cx,cy,r:cr*1.35,class:'bp-ring2'}),
    sSvg('circle',{cx,cy,r:cr,class:'bp-hub'}));
  // the whole's name, centred in the hub on one or two lines
  const probe=sSvg('text',{class:'bp-corename'},node.name||'');core.append(probe);
  const two=probe.getComputedTextLength&&probe.getComputedTextLength()>cr*1.7;probe.remove();
  bpWrap(core,cx,cy+(two?-3:4),node.name,cr*1.7,two?2:1,'bp-corename',15,'middle');
  if(narrow){   // a phone: the core on top and the parts in two columns under it
    // one spine down the gap between the columns, a branch to each part: no line crosses a box
    const cols=2,cw=(W-36)/cols,y0=cy+cr+28,rows=Math.ceil(kids.length/cols);
    world.append(sSvg('line',{x1:cx,y1:cy+cr,x2:cx,y2:y0+(rows-1)*(bh+14)+bh/2,class:'bp-ex'}));
    kids.forEach((p,i)=>{const c=i%cols,r=Math.floor(i/cols);
      const x=18+c*cw+4,y=y0+r*(bh+14),w=cw-8;
      world.append(sSvg('line',{x1:cx,y1:y+bh/2,x2:c?x:x+w,y2:y+bh/2,class:'bp-ex'}));
      out.push(bpBox(world,p,i,st,x,y,w,bh))});
    return out;
  }
  const rx=(W-bw)/2-22,ry=(H-bh)/2-38;
  kids.forEach((p,i)=>{
    const a=-Math.PI/2+i*2*Math.PI/Math.max(1,n)+(n%2?0:Math.PI/n);
    const px=cx+Math.cos(a)*rx,py=cy+Math.sin(a)*ry;
    const x=px-bw/2,y=py-bh/2;
    // the explosion line: from where it sits in the whole to where it was pulled out to
    const sx=cx+Math.cos(a)*cr*1.35,sy=cy+Math.sin(a)*cr*1.35;
    const t=Math.min(Math.abs((bw/2+6)/(Math.cos(a)||1e-9)),Math.abs((bh/2+6)/(Math.sin(a)||1e-9)));
    world.append(sSvg('line',{x1:sx,y1:sy,x2:px-Math.cos(a)*t,y2:py-Math.sin(a)*t,class:'bp-ex','marker-end':bpId(svg,'a')}));
    world.append(sSvg('path',{d:`M${sx-4} ${sy}h8M${sx} ${sy-4}v8`,class:'bp-reg'}));
    out.push(bpBox(world,p,i,st,x,y,bw,bh));
  });
  return out;
}
function bpBox(world,p,i,st,x,y,w,h){
  const g=bpPartG(world,p,i,st);
  g.append(sSvg('rect',{x,y,width:w,height:h,rx:3,class:'bp-fill'}));
  bpShape(g,'rect',{x,y,width:w,height:h,rx:3},p);
  // corner ticks, as a drawing frames a detail
  [[x,y,1,1],[x+w,y,-1,1],[x,y+h,1,-1],[x+w,y+h,-1,-1]].forEach(([a,b,s,t])=>
    g.append(sSvg('path',{d:`M${a+7*s} ${b-3*t}H${a-3*s}V${b+7*t}`,class:'bp-tick'})));
  bpText(g,x+10,y+19,p.name,w-(p.status?30:20),'bp-name');
  // what it is for, on as many lines as the box has room for; then its first number
  const room=Math.max(1,Math.floor((h-46)/13));
  const f=(p.facts||[])[0];
  let used=0;
  if(p.role)used=bpWrap(g,x+10,y+35,p.role,w-20,f&&room>1?room-1:room,'bp-rolet',13);
  if(f&&used<room)bpText(g,x+10,y+35+used*13,(f.label?f.label+' ':'')+bpVal(f),w-20,'bp-subt');
  const k=bpKids(p).length;
  bpText(g,x+10,y+h-9,k?'⊕ '+k+' part'+(k===1?'':'s')+' inside':(p.evidence?'⌖ record':''),w-20,'bp-more');
  bpBadge(g,p,x+w-12,y+12);
  return {p,g,box:[x,y,w,h],anchor:[x+w,y+h/2],left:[x,y+h/2]};
}
/* ---------- flow: a process, in order ---------- */
function bpFlow(world,node,kids,W,H,st){
  const out=[],n=kids.length;
  const few=n<=4;
  const gap=W<560?16:34,bw=W<560?W-56:Math.max(150,Math.min(few?270:220,(W-48-gap*(few?n-1:3))/(few?Math.max(n,3):4))),bh=W<560?70:few?104:84;
  const per=Math.max(1,Math.min(n,Math.floor((W-40+gap)/(bw+gap))));
  const rows=Math.ceil(n/per),rowH=bh+(per===1?20:44);
  const total=rows*rowH-(rowH-bh),y0=Math.max(46,(H-total)/2-6);
  st.needH=total+70;      // a narrow sheet scrolls, so a long flow asks for the height it needs
  const svg=bpSvgOf(world);
  const x0=(W-(per*bw+(per-1)*gap))/2;
  const pos=[];
  kids.forEach((p,i)=>{const r=Math.floor(i/per);let c=i%per;if(r%2)c=per-1-c;   // a snake: the next row comes back
    pos.push([x0+c*(bw+gap),y0+r*rowH])});
  kids.forEach((p,i)=>{if(!i)return;
    const [ax,ay]=pos[i-1],[bx,by]=pos[i];let d;
    if(ay===by){const fwd=bx>ax;d=fwd?`M${ax+bw} ${ay+bh/2}H${bx}`:`M${ax} ${ay+bh/2}H${bx+bw}`}
    else d=`M${ax+bw/2} ${ay+bh}V${by}`;
    world.append(sSvg('path',{d,class:'bp-flow','marker-end':bpId(svg,'a')}))});
  kids.forEach((p,i)=>out.push(bpBox(world,p,i,st,pos[i][0],pos[i][1],bw,bh)));
  return out;
}

/* ---------- how parts depend on each other ---------- */
function bpLinks(world,items,st,form){
  if(form==='tower')return;
  const at={};items.forEach(it=>at[it.p.id]=it);
  const svg=bpSvgOf(world);
  const ids=new Set(items.map(it=>it.p.id));
  (st.sc.links||[]).filter(l=>ids.has(l.from)&&ids.has(l.to)).slice(0,14).forEach((l,i)=>{
    const a=at[l.from],b=at[l.to];
    const [ax,ay]=form==='tower'?a.left:[a.box[0]+a.box[2]/2,a.box[1]+a.box[3]/2];
    const [bx,by]=form==='tower'?b.left:[b.box[0]+b.box[2]/2,b.box[1]+b.box[3]/2];
    const mx=form==='tower'?Math.min(ax,bx)-40-i*10:(ax+bx)/2+(by-ay)*.18,my=form==='tower'?(ay+by)/2:(ay+by)/2-(bx-ax)*.18;
    const path=sSvg('path',{d:`M${ax} ${ay}Q${mx} ${my} ${bx} ${by}`,class:'bp-link','marker-end':bpId(svg,'a'),
      'data-from':l.from,'data-to':l.to});
    world.insertBefore(path,world.firstChild);
    if(l.verb){const t=sSvg('text',{x:(ax+2*mx+bx)/4,y:(ay+2*my+by)/4-4,'text-anchor':'middle',class:'bp-verb',
      'data-from':l.from,'data-to':l.to},l.verb);world.append(t)}
  });
}

/* ---------- the title block, as on a drawing: at the foot of the panel ---------- */
function bpTitleBlock(st){
  const el=st.el.info;el.textContent='';
  const node=bpNode(st),n=bpCount(st.sc.parts),dp=bpDepth(st.sc.parts);
  [['Subject',st.sc.subject||st.sc.title||''],['Level',(st.path.length+1)+' of '+dp+' · '+(st.form||'')],
   ['Parts',bpKids(node).length+' here · '+n+' in all'],
   ['Source',st.sc.illustrative?'illustrative, not data':(st.sc.source||'—')]].forEach(([k,v])=>{
    el.append(sEl('span','bp-tbk',k),sEl('span','bp-tbv',v))});
  return el;
}
/* ---------- where you are ---------- */
function bpCrumbs(st){
  const c=st.el.crumbs;c.textContent='';
  const home=sEl('button','bp-crumb'+(st.path.length?'':' on'),st.sc.subject||st.sc.title||'Blueprint');
  home.onclick=()=>bpGo(st,[]);c.append(home);
  let n={parts:st.sc.parts};
  st.path.forEach((id,i)=>{n=bpKids(n).find(p=>p.id===id);if(!n)return;
    c.append(sEl('span','bp-sep','›'));
    const b=sEl('button','bp-crumb'+(i===st.path.length-1?' on':''),n.name);
    const to=st.path.slice(0,i+1);b.onclick=()=>bpGo(st,to);c.append(b)});
  c.append(sEl('span','bp-sp'));
  if(st.path.length){const up=sEl('button','bp-up','↥ Up');up.title='Back up one level (Esc)';up.onclick=()=>bpGo(st,st.path.slice(0,-1),'back');c.append(up)}
  // the legend: what a dashed or dotted line means
  const lg=sEl('span','bp-legend');
  [['known','known'],['estimated','estimated'],['unclear','unclear']].forEach(([k,w])=>{
    const s=sEl('span','bp-lg c-'+k);s.append(sEl('i',''),document.createTextNode(w));lg.append(s)});
  c.append(lg);
}
function bpLocator(st){
  const box=st.el.loc;box.textContent='';
  if(!st.path.length)return null;
  const W=150,H=110,svg=sSvg('svg',{viewBox:`0 0 ${W} ${H}`,width:W,height:H});box.append(svg);
  // the top level, small, with the branch you are in lit: you are here
  const root={name:'',parts:st.sc.parts,form:st.sc.form,root:true};
  svg.dataset.uid='bpl';
  const g=sSvg('g',{class:'bp-world bp-mini'});svg.append(g);
  const fake={sc:st.sc,path:[],sel:null};
  try{const L=(st.sc.form==='tower'?bpTower:st.sc.form==='flow'?bpFlow:bpExploded)(g,root,bpKids(root),W*4,H*4,fake);
    g.setAttribute('transform','scale(.25)');
    L.forEach(it=>{if(it.p.id===st.path[0])it.g.classList.add('here')});
  }catch(e){}
  box.append(sEl('div','bp-loc-t','You are here: '+st.path.length+' level'+(st.path.length===1?'':'s')+' in'));
  return box;
}
/* ---------- the spec panel: what the part under your finger is ---------- */
function bpSpec(st){
  const el=st.el.spec;el.textContent='';
  const node=bpNode(st),kids=bpKids(node);
  const id=st.peek||st.sel,p=id?kids.find(k=>k.id===id):null;
  if(!p){
    el.append(sEl('div','bp-k',(st.path.length?'Inside ':'Blueprint · ')+(st.path.length?'':'')+kids.length+' parts'+(st.path.length?'':' · '+bpDepth(st.sc.parts)+' levels deep')));
    el.append(sEl('div','bp-h',node.name||st.sc.subject));
    if(node.root&&st.sc.caption)el.append(sEl('p','bp-role',st.sc.caption));
    if(node.role)el.append(sEl('p','bp-role',node.role));
    if(node.detail)el.append(sEl('p','bp-detail',node.detail));
    bpFacts(el,node.facts);
    const un=(node.root?st.sc.unknowns:node.unknowns)||[];
    if(un.length){el.append(sEl('div','bp-k2','Still unclear'));const u=sEl('ul','bp-unk');un.forEach(x=>u.append(sEl('li','',x)));el.append(u)}
    const hint=sEl('p','bp-hint',bpHover()?'Point at a part to read it. Click to open it.':'Tap a part to read it. Tap again to open it.');
    el.append(hint);
    if(!node.root&&node.evidence)el.append(sEl('div','bp-ev',node.evidence));
    bpPanelFoot(st,el);
    return;
  }
  const i=kids.indexOf(p);
  const k=sEl('div','bp-k','Part '+(i+1)+' of '+kids.length+' · ');
  const c=sEl('span','bp-cert c-'+(p.certainty||'known'),BP_CERT_WORD[p.certainty||'known']);k.append(c);el.append(k);
  el.append(sEl('div','bp-h',p.name));
  if(p.status&&BP_STATUS[p.status]){const [ic,w,col]=BP_STATUS[p.status];
    const s=sEl('span','bp-status',ic+' '+w);s.style.color=col;s.style.borderColor=col;el.append(s)}
  if(p.role)el.append(sEl('p','bp-role',p.role));
  if(p.detail)el.append(sEl('p','bp-detail',p.detail));
  if(p.from!=null||p.to!=null){
    const u=st.sc.unit?' '+st.sc.unit:'';
    bpFacts(el,[{label:'from',value:bpFmt(p.from),unit:u.trim()},{label:'to',value:bpFmt(p.to),unit:u.trim()}].concat(p.facts||[]));
  }else bpFacts(el,p.facts);
  if((p.unknowns||[]).length){el.append(sEl('div','bp-k2','Still unclear'));const u=sEl('ul','bp-unk');p.unknowns.forEach(x=>u.append(sEl('li','',x)));el.append(u)}
  if(p.evidence)el.append(sEl('div','bp-ev',p.evidence));
  if(p.source)el.append(typeof stageSource==='function'?stageSource(p.source):sEl('div','st-src','Source: '+p.source));
  const n=bpKids(p).length;
  const acts=sEl('div','bp-acts');
  if(n){const b=sEl('button','bp-open','Open inside · '+n+' part'+(n===1?'':'s')+' ›');b.onclick=()=>bpOpen(st,p);acts.append(b)}
  else if(st.live&&st.seq&&typeof stageDeeper==='function'){
    const b=sEl('button','bp-open','⤵ Take this apart');b.title='Ask for this part as its own blueprint';
    b.onclick=()=>stageDeeper(st.seq,p.id);acts.append(b)}
  else if(p.evidence)acts.append(sEl('span','bp-bottom','This is a record: the bottom of it.'));
  el.append(acts);
  bpPanelFoot(st,el,p);
}
/* What the panel ends on: how this part depends on others, where you are, the title block. */
function bpPanelFoot(st,el,p){
  const name=id=>{const x=bpFind(st.sc.parts,id);return x?x.name:id};
  const here=new Set(bpKids(bpNode(st)).map(k=>k.id));
  const ls=(st.sc.links||[]).filter(l=>p?(l.from===p.id||l.to===p.id):(here.has(l.from)||here.has(l.to)));
  if(ls.length){el.append(sEl('div','bp-k2 bp-k2b','How it connects'));const u=sEl('ul','bp-conn');
    ls.slice(0,8).forEach(l=>u.append(sEl('li','',name(l.from)+' '+(l.verb||'→')+' '+name(l.to))));el.append(u)}
  const loc=bpLocator(st);if(loc)el.append(loc);
  el.append(bpTitleBlock(st));
}
function bpFacts(el,facts){
  if(!(facts||[]).length)return;
  const dl=sEl('dl','bp-facts');
  facts.forEach(f=>{if(f.value===''||f.value==null)return;dl.append(sEl('dt','',f.label||'·'),sEl('dd','',bpVal(f)))});
  el.append(dl);
}
function bpPeek(st){
  const el=st.el.peek;el.textContent='';
  const p=st.sel&&bpNarrow(st)?bpKids(bpNode(st)).find(k=>k.id===st.sel):null;
  el.hidden=!p;if(!p)return;
  // never over the part it is about: low on the drawing, the sheet sits at the top
  const it=(st.items||[]).find(x=>x.p.id===p.id),H=st.el.draw.clientHeight||1;
  el.classList.toggle('up',!!it&&(it.box[1]+it.box[3]/2)>H*.55);
  const top=sEl('div','bp-peek-h');top.append(sEl('b','',p.name));
  if(p.status&&BP_STATUS[p.status]){const [ic,w,col]=BP_STATUS[p.status];const s=sEl('span','bp-status',ic+' '+w);s.style.color=col;s.style.borderColor=col;top.append(s)}
  el.append(top);
  const f=(p.facts||[])[0];
  el.append(sEl('div','bp-peek-r',p.role||(f?(f.label+' '+bpVal(f)):'')));
  const acts=sEl('div','bp-acts');
  const n=bpKids(p).length;
  if(n){const b=sEl('button','bp-open','Open inside · '+n+' ›');b.onclick=()=>bpOpen(st,p);acts.append(b)}
  // only the scene scrolls: scrollIntoView would scroll the Stage's own room too
  const more=sEl('button','bp-more-b','Details ↓');more.onclick=()=>st.art.scrollTo({top:st.el.spec.offsetTop-8,behavior:stageReduced()?'auto':'smooth'});
  acts.append(more);
  const x=sEl('button','bp-x','✕');x.setAttribute('aria-label','Close');x.onclick=()=>{st.sel=null;bpSpec(st);bpMark(st)};acts.append(x);
  el.append(acts);
}
function bpMark(st){
  bpPeek(st);
  const id=st.peek||st.sel;
  st.el.svg.classList.toggle('bp-focus',!!id);
  (st.items||[]).forEach(it=>it.g.classList.toggle('on',it.p.id===id));
  st.el.svg.querySelectorAll('.bp-link,.bp-verb').forEach(l=>l.classList.toggle('on',!!id&&(l.dataset.from===id||l.dataset.to===id)));
}

/* ---------- moving through it ---------- */
function bpTap(st,p,e){
  bpTourStop(st);
  const kids=bpKids(p).length;
  // a mouse reads by pointing, so a click opens; a finger reads by the first tap
  if(kids&&(st.sel===p.id||(e&&e.pointerType==='mouse')||bpHover())){bpOpen(st,p);return}
  st.sel=st.sel===p.id&&!kids?null:p.id;st.peek=null;bpSpec(st);bpMark(st);
}
function bpOpen(st,p){
  if(!bpKids(p).length)return;
  const it=(st.items||[]).find(x=>x.p.id===p.id),world=st.el.svg.querySelector('.bp-world');
  const go=()=>{st.path=st.path.concat(p.id);st.sel=null;st.peek=null;bpRender(st,'in');bpFocusFirst(st)};
  if(!it||!world||stageReduced()){go();return}
  // the drawing flies into the part, then the part's own drawing comes up
  const W=+st.el.svg.getAttribute('width'),H=+st.el.svg.getAttribute('height');
  const [x,y,w,h]=it.box,s=Math.min(6,Math.max(1.6,Math.min(W/Math.max(w,30),H/Math.max(h,30))*.7));
  world.style.transformOrigin=(x+w/2)+'px '+(y+h/2)+'px';
  world.style.transform=`translate(${W/2-(x+w/2)}px,${H/2-(y+h/2)}px) scale(${s})`;
  world.classList.add('bp-dive');
  setTimeout(go,420);
}
function bpGo(st,path,how){bpTourStop(st);const was=st.path.length;st.path=path;st.sel=null;st.peek=null;
  bpRender(st,how||(path.length<was?'back':'in'));bpFocusFirst(st)}
function bpFocusFirst(st){try{if(st.art.contains(document.activeElement)){const g=st.el.svg.querySelector('.bp-p');if(g)g.focus({preventScroll:true})}}catch(e){}}
function bpKey(st,e){
  if(e.key==='Escape'&&st.path.length){e.preventDefault();e.stopPropagation();bpGo(st,st.path.slice(0,-1),'back');return}
  const gs=[...st.el.svg.querySelectorAll('.bp-p')];const i=gs.indexOf(document.activeElement);
  if(i<0)return;
  if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();
    const p=bpKids(bpNode(st)).find(k=>k.id===gs[i].dataset.id);if(p){if(bpKids(p).length)bpOpen(st,p);else{st.sel=p.id;bpSpec(st);bpMark(st)}}return}
  const d={ArrowRight:1,ArrowDown:1,ArrowLeft:-1,ArrowUp:-1}[e.key];
  if(d){e.preventDefault();e.stopPropagation();gs[(i+d+gs.length)%gs.length].focus()}
}

/* ---------- the tour: while the story plays, each part is pointed out in turn ---------- */
function bpTourMs(sc){return Math.min(14000,(sc.parts||[]).length*1700+1200)}
function bpTour(st){
  const kids=bpKids(bpNode(st));let i=0;
  const step=()=>{if(!st.art.isConnected||typeof STAGE==='undefined'||!STAGE.playing){bpTourStop(st);return}
    if(i>=kids.length){st.peek=null;bpSpec(st);bpMark(st);return}
    st.peek=kids[i++].id;bpSpec(st);bpMark(st);st.tour=setTimeout(step,1700)};
  st.tour=setTimeout(step,900);
}
function bpTourStop(st){if(st.tour){clearTimeout(st.tour);st.tour=null}}

/* ---------- X-ray: this machine's own record of an answer or a run, as a blueprint ---------- */
async function stageXray(q,label){
  let d;
  try{d=await apiJSON('/api/stage/xray?'+new URLSearchParams(q).toString())}
  catch(e){toast('could not X-ray it: '+(e.message||e));return}
  if(!d||!d.scene){toast('could not X-ray it: '+((d&&d.error)||'no record'));return}
  STAGE.cur={cid:q.conversation||d.conversation_id||'',answer_to:'xray:'+(q.answer_to||q.run||''),
    question:label||d.scene.subject||'',parent:null,deeper:{},versions:[],xray:q};
  STAGE.scenes=[{id:'xray',seq:1,scene:d.scene}];STAGE.at=0;STAGE.tab='now';STAGE.held=Date.now()+600000;
  const w=typeof WM!=='undefined'&&WM.wins.get('stage');
  if(w){focusWin(w);stagePaint()}else openApp('stage');
}
function xrayButton(q,label){
  const b=sEl('button','xray-btn','⌖ X-ray');
  b.title='Take this apart: who did what, every decision the gate made, what it cost';
  b.onclick=e=>{e.stopPropagation();stageXray(q,label)};return b;
}
/* Chat: an X-ray under each answer, for the question it answers. */
function xrayAttach(cid){
  if(!cid||typeof feed==='undefined'||!feed)return;
  feed.querySelectorAll('.msg.user[data-mid]').forEach(u=>{
    let a=u.nextElementSibling;
    while(a&&!a.classList.contains('assistant')&&!a.classList.contains('user'))a=a.nextElementSibling;
    if(!a||!a.classList.contains('assistant')||a.querySelector(':scope > .xray-btn'))return;
    a.append(xrayButton({conversation:cid,answer_to:u.dataset.mid},'X-ray · '+(u.textContent||'').trim().slice(0,80)));
  });
}
/* A turn that just ended has no message id on the page yet: its X-ray asks for the last one. */
async function xrayLive(cid,msgEl){
  if(!cid||!msgEl||msgEl.querySelector(':scope > .xray-btn'))return;
  // pinned to this question now, so a later turn in the chat never changes what it opens
  let mid='';try{const d=await apiJSON('/api/conversations/'+encodeURIComponent(cid));
    const us=(d.messages||[]).filter(m=>m.role==='user');mid=us.length?us[us.length-1].id:''}catch(e){}
  if(!msgEl.isConnected||msgEl.querySelector(':scope > .xray-btn'))return;
  msgEl.append(xrayButton(mid?{conversation:cid,answer_to:mid}:{conversation:cid},'X-ray of this answer'));
}
