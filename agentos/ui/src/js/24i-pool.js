/* ================= a community of machines =================
   Settings → Agents → Working together → Community. pool.py is the whole design; this
   draws /api/pool and changes it. One machine LEADS (holds the keys, lends its brain,
   splits bigger work); small machines JOIN over a linked team, share notes and take
   pieces of work. Who leads next is decided by rank among machines whose own admin
   said they may lead. TUI: `bento pool`. SUI: this page, nothing touches the compositor. */
var POOL={v:null};
async function poolPaint(){
  const box=document.getElementById('s-pool');if(!box)return;
  let v;try{v=await apiJSON('/api/pool')}catch(e){box.innerHTML=`<div class="prow"><div class="pl"><small>${esc(String(e.message||e))}</small></div></div>`;return}
  POOL.v=v;
  const can=v.can_change,rows=[];
  const btn=(label,act,extra)=>`<button class="endbtn" data-pool="${act}"${extra||''}${can?'':' disabled'}>${esc(label)}</button>`;
  if(!v.pool){
    const linked=v.linked||[];
    rows.push(pRow('This machine',`<span class="mut">${esc(v.line)}</span>`,
      {desc:'Machines that share one brain, one set of notes, and bigger jobs.',
       more:'One machine leads and pays for the thinking. Small machines like a Raspberry Pi join it, share what they learn and each take a piece of a bigger task.',
       f:'community pool status'}));
    rows.push(pRow('Start a community',`<input id="pool-name" placeholder="Home" maxlength="40" style="max-width:160px"${can?'':' disabled'}>`+btn('Start','create'),
      {desc:v.has_brain?'This machine leads. Others ask to join it.':'Needs a brain of its own first, under AI providers.',
       f:'community start create lead'}));
    rows.push(pRow('Join a community',linked.length
        ?pSelect('pool-join-to',linked.map(l=>[l.label,l.name]),linked[0].label)+btn('Ask to join','join')
        :'<span class="mut">Link with the leader first, above.</span>',
      {desc:'Ask a linked machine that leads a community to let this one in.',
       more:'Its admin approves you. Joining lets the community hand this machine work; you can revoke that in Permissions.',
       f:'community join member raspberry pi'}));
  }else{
    rows.push(pRow(v.pool.name,`<span class="mut">${esc(v.line)}</span>`,
      {desc:v.role==='leader'?'This machine leads. It lends its brain and splits bigger work.':v.role==='pending'?'Waiting for the leader to let you in.':'A member. It shares notes and takes work.',
       more:'The leader is chosen by rank among machines whose admin said they may lead: the one you pin first, then the most capable. If the leader stops answering for a minute, the next one takes over.',
       f:'community status leader member term'}));
    const ms=(v.machines||[]);
    rows.push(pRow('Machines',`<div class="pool-list">${ms.map(m=>{
        const c=m.cap||{},st=m.here?'this machine':m.state==='pending'?'asking to join':m.alive?'up':m.seen!=null?`last heard ${poolAgo(m.seen)}`:'not heard yet';
        const acts=v.role==='leader'&&!m.here&&can?(m.state==='pending'
          ?`<button class="endbtn" data-pool="approve" data-who="${esc(m.fp)}">Let in</button><button class="endbtn" data-pool="remove" data-who="${esc(m.fp)}">Turn away</button>`
          :`<button class="endbtn" data-pool="remove" data-who="${esc(m.fp)}">Remove</button>`):'';
        return `<div class="pool-m${m.alive||m.here?' up':''}"><b>${m.role==='leader'?'★ ':''}${esc(m.name)}</b>
          <span class="mut">${esc(st)} · ${c.ram_mb||0} MB · ${c.cores||0} cores${c.board?' · '+esc(c.board):''}${m.eligible?' · may lead':''}${m.busy?' · working':''}</span>${acts}</div>`}).join('')||'<span class="mut">Nobody yet.</span>'}</div>`,
      {stack:true,desc:'Every machine in the community and when it was last heard.',f:'community machines members roster'}));
    const next=ms.filter(m=>!m.here&&m.eligible&&m.state==='member');
    if(v.role==='leader')rows.push(pRow('Who takes over first',next.length
        ?pSelect('pool-pin',[['','The most capable'],...next.map(m=>[m.fp,m.name])],v.pin||'')
        :'<span class="mut">No other machine may lead yet.</span>',
      {desc:'If this machine goes away, this one leads next.',
       more:'Only machines whose own admin switched on This machine may lead are listed.',
       f:'community pin next leader failover'}));
    rows.push(pRow('This machine may lead',pSwitch('pool-lead',!!v.lead_ok),
      {desc:'If the leader goes away, this machine can take over and pay for the thinking.',
       more:'It needs a brain of its own. Leading spends this machine’s model budget on every member’s calls.',
       f:'community lead elect take over failover'}));
    if(v.role==='member')rows.push(pRow('Think with the leader’s brain',pSwitch('pool-brain',!!v.using_brain),
      {desc:'Model calls go to the leader. This machine needs no key of its own.',f:'community brain model leader thinks'}));
    rows.push(pRow('Shared notes',`<span class="mut">${v.notes} note${v.notes===1?'':'s'}</span><button class="endbtn" data-pool="notes">Show</button>`,
      {desc:'What the machines’ agents chose to share with each other.',
       more:'Agents read them with community_recall and treat them as untrusted, because another machine wrote them.',
       f:'community shared memory notes'}));
    rows.push(pRow('Leave',btn('Leave the community','leave'),{desc:'This machine stops sharing and taking work.',f:'community leave'}));
    if(v.note)rows.push(pRow('Last problem',`<span class="mut">${esc(v.note)}</span>`,{f:'community problem'}));
  }
  box.innerHTML=rows.join('')+'<div id="pool-notes"></div>';
  box.querySelectorAll('[data-pool]').forEach(b=>b.onclick=()=>poolAct(b.dataset.pool,b.dataset.who||''));
  const ld=box.querySelector('#pool-lead');if(ld){ld.disabled=!can;ld.onchange=()=>poolPut({lead_ok:ld.checked})}
  const pn=box.querySelector('#pool-pin');if(pn){pn.disabled=!can;pn.onchange=()=>poolPut({pin:pn.value})}
  const br=box.querySelector('#pool-brain');if(br){br.disabled=!can;br.onchange=()=>poolPut({use_brain:br.checked})}
}
function poolAgo(s){return s<90?s+'s ago':s<5400?Math.round(s/60)+' min ago':Math.round(s/3600)+' h ago'}
async function poolPut(body){
  const r=await fetch('/api/pool',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json().catch(()=>({}));
  if(!r.ok)toast(d.error||'could not change that');else toast('✓ saved');
  poolPaint();
}
async function poolAct(act,who){
  if(act==='notes')return poolNotes();
  if(act==='leave'&&!confirm('Leave the community? This machine stops sharing notes and taking work.'))return;
  const body=act==='create'?{name:(document.getElementById('pool-name')||{}).value||''}
    :act==='join'?{label:(document.getElementById('pool-join-to')||{}).value||''}:{who};
  const r=await fetch('/api/pool/'+act,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json().catch(()=>({}));
  if(!r.ok){toast(d.error||'could not do that');return}
  toast({create:'✓ community started',join:'✓ asked to join',approve:'✓ let in',remove:'✓ removed',leave:'✓ left the community'}[act]||'✓ done');
  poolPaint();
}
async function poolNotes(){
  const el=document.getElementById('pool-notes');if(!el)return;
  if(el.innerHTML){el.innerHTML='';return}
  let d;try{d=await apiJSON('/api/pool/notes')}catch(e){el.textContent=String(e.message||e);return}
  el.innerHTML=`<div class="pool-notes">${(d.notes||[]).map(n=>`<div class="pool-n"><span class="mut">${esc(n.machine||'?')}</span> ${esc(n.content)}
    <button class="endbtn" data-forget="${esc(n.id)}" aria-label="Forget this note">Forget</button></div>`).join('')||'<span class="mut">No notes yet.</span>'}</div>`;
  el.querySelectorAll('[data-forget]').forEach(b=>b.onclick=async()=>{
    await fetch('/api/pool/notes/'+encodeURIComponent(b.dataset.forget),{method:'DELETE'});el.innerHTML='';poolNotes()});
}
