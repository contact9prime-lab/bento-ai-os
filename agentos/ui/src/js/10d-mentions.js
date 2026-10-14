/* ---------------- @ suggestions: an agent or a department, by name ----------------
   Typing @ at the start of a message offers the people and the departments it can
   reach: `@nora …` is the specialist answering itself (fabric.parse_mention), `@Sales …`
   is a run of that department's desk (company.parse_department), `@a @b …` a huddle.
   One list from the server (/api/chat/addresses → company.addresses), one popup, and
   every composer gets it by delegation: Chat (#input), the prompt bar (#omni-in) and
   every app's agent panel, the Office's included (.cp-in). Nothing is sent by picking;
   it only writes the address.
   Faces: GUI and SUI are this list. TUI and the channels type the same @ by hand, and
   `bento company` lists the departments. */
var ATS={data:null,at:0,el:null,box:null,items:[],sel:0,start:0,end:0};
var ATS_TTL=30000;
function atsLoad(){
  if(ATS.data&&Date.now()-ATS.at<ATS_TTL)return Promise.resolve(ATS.data);
  return fetch('/api/chat/addresses').then(r=>r.ok?r.json():null).then(j=>{
    if(j&&Array.isArray(j.agents)){ATS.data=j;ATS.at=Date.now()}return ATS.data}).catch(()=>ATS.data);
}
function atsForget(){ATS.at=0}
/* The address being typed: only in the leading run of @words, since only an address
   at the start routes a message. */
function atsToken(el){
  const v=el.value||'',caret=el.selectionStart==null?v.length:el.selectionStart;
  const head=v.slice(0,caret);
  const m=head.match(/^((?:@[^@\s][^@]*?\s+)*)@([^@]*)$/);
  if(!m)return null;
  const q=m[2];
  if(q.length>40||/\n/.test(q))return null;
  return {q,start:m[1].length,end:caret};
}
function atsMatch(d,q){
  const k=q.toLowerCase().replace(/[\s_-]+/g,'');
  const has=s=>String(s||'').toLowerCase().replace(/[\s_&-]+/g,'').startsWith(k)
    ||String(s||'').toLowerCase().split(/[\s_&-]+/).some(w=>w.startsWith(q.toLowerCase().trim()));
  const out=[];
  (d.departments||[]).forEach(x=>{if(!k||has(x.name))out.push({kind:'dept',name:x.name,
    sub:(x.head?'head '+x.head+' · ':'')+x.people+' '+(x.people===1?'person':'people'),hex:x.hex,head:x.head,desk:x.desk})});
  (d.agents||[]).forEach(x=>{if(!k||has(x.name)||has(x.title))out.push({kind:'agent',name:x.name,
    sub:[x.title,x.dept].filter(Boolean).join(' · ')||'specialist'})});
  return out.slice(0,8);
}
function atsClose(){if(ATS.box){ATS.box.remove();ATS.box=null}ATS.items=[];ATS.el=null}
function atsPaint(){
  const el=ATS.el;if(!el||!ATS.items.length){atsClose();return}
  if(!ATS.box){ATS.box=document.createElement('div');ATS.box.className='ats';ATS.box.setAttribute('role','listbox');
    document.body.appendChild(ATS.box);
    // a tap chooses; pointerdown so the field keeps its focus and caret
    ATS.box.addEventListener('pointerdown',e=>{const r=e.target.closest('[data-i]');if(!r)return;
      e.preventDefault();atsPick(+r.dataset.i)})}
  ATS.box.innerHTML=ATS.items.map((x,i)=>`<div class="ats-row${i===ATS.sel?' on':''}" data-i="${i}" role="option" aria-selected="${i===ATS.sel}">
    ${x.kind==='dept'?`<span class="ats-dot" style="background:${esc(x.hex||'#64748b')}">▦</span>`
      :(typeof avatarImg==='function'&&avatarImg(x.name,'ats-av'))||'<span class="ats-dot">@</span>'}
    <span class="ats-name">${x.kind==='dept'?esc(x.name):'@'+esc(x.name)}</span>
    <span class="ats-sub">${x.kind==='dept'?(x.desk?'department · ':'department, no desk · '):''}${esc(x.sub)}</span></div>`).join('');
  const r=el.getBoundingClientRect(),w=Math.min(360,innerWidth-32);
  ATS.box.style.width=w+'px';
  ATS.box.style.left=Math.max(16,Math.min(r.left,innerWidth-w-16))+'px';
  // above the field when there is room (composers sit at the bottom), else below it
  const h=ATS.box.offsetHeight;
  ATS.box.style.top=(r.top-h-6>8?r.top-h-6:r.bottom+6)+'px';
}
function atsPick(i){
  const x=ATS.items[i],el=ATS.el;if(!x||!el)return;
  const v=el.value,addr='@'+(x.kind==='dept'?x.name:x.name)+' ';
  el.value=v.slice(0,ATS.start)+addr+v.slice(ATS.end).replace(/^\S*\s?/,'');
  const p=ATS.start+addr.length;try{el.setSelectionRange(p,p)}catch(e){}
  atsClose();el.focus();el.dispatchEvent(new Event('input',{bubbles:true}));
}
function atsInput(el){
  const t=atsToken(el);if(!t){atsClose();return}
  atsLoad().then(d=>{
    if(!d||document.activeElement!==el){atsClose();return}
    const t2=atsToken(el);if(!t2){atsClose();return}
    ATS.el=el;ATS.start=t2.start;ATS.end=t2.end;
    const items=atsMatch(d,t2.q);
    if(!items.length){atsClose();return}
    if(ATS.items.map(x=>x.name).join('|')!==items.map(x=>x.name).join('|'))ATS.sel=0;
    ATS.items=items;atsPaint();
  });
}
var ATS_FIELDS='#input,#omni-in,.cp-in';
document.addEventListener('input',e=>{const el=e.target;if(el&&el.matches&&el.matches(ATS_FIELDS))atsInput(el)},true);
// capture: while the list is open, the arrows and Enter belong to it, not to the send
document.addEventListener('keydown',e=>{
  if(!ATS.box||!ATS.el||e.target!==ATS.el)return;
  const n=ATS.items.length;
  if(e.key==='ArrowDown'||e.key==='ArrowUp'){ATS.sel=(ATS.sel+(e.key==='ArrowDown'?1:n-1))%n;atsPaint()}
  else if(e.key==='Enter'||e.key==='Tab'){atsPick(ATS.sel)}
  else if(e.key==='Escape'){atsClose()}
  else return;
  e.preventDefault();e.stopImmediatePropagation();
},true);
document.addEventListener('focusout',e=>{if(e.target===ATS.el)setTimeout(()=>{if(document.activeElement!==ATS.el)atsClose()},120)},true);
addEventListener('resize',()=>{if(ATS.box)atsPaint()});
