/* ================= memory app ================= */
let memTab='user';
async function renderMemory(body){
  await loadConfig();
  const r=await fetch('/api/memories');const d=await r.json();
  const auto=(cfg.memory||{}).auto_extract!==false;
  const srcBadge=m=>m.source==='auto'?'<span class="badge" title="learned automatically" style="font-size:9px;padding:1px 6px;margin-right:4px">auto</span>':'';
  const when=m=>new Date(m.created_at*1000).toLocaleString();
  const user=d.memories.filter(m=>(m.scope||'user')==='user');
  const sess=d.memories.filter(m=>m.scope==='session');
  let items='';
  if(memTab==='user'){
    items=user.map(m=>`<div class="item" data-f="${esc(m.content)}"><div class="grow">${srcBadge(m)}${esc(m.content)}<div class="sub">${when(m)}</div></div>
      <button title="${m.pinned?'unpin':'pin (always injected first)'}" style="${m.pinned?'':'opacity:.45'};font-size:11px" onclick="pinMemory('${m.id}',${m.pinned?0:1})">${m.pinned?'pinned':'pin'}</button>
      <button title="edit" onclick="editMemory('${m.id}')">✎</button>
      <button title="delete" onclick="delMemory('${m.id}')">✕</button></div>`).join('')
      ||emptyBox('No user memories yet','They appear here as you chat (auto-learn), when the agent calls <code>remember</code>, or when you add one below.','','memory','What should you remember about me? Interview me briefly.');
  }else{
    const groups={};
    sess.forEach(m=>{(groups[m.conversation_id||'?']=groups[m.conversation_id||'?']||{title:m.conversation_title||'(deleted conversation)',items:[]}).items.push(m)});
    items=Object.entries(groups).map(([cid,g])=>`<div data-fgroup><div class="ptitle" style="margin-top:10px">${esc(g.title)}</div>`+
      g.items.map(m=>`<div class="item" data-f="${esc(g.title+' '+m.content)}"><div class="grow">${srcBadge(m)}${esc(m.content)}<div class="sub">${when(m)}</div></div>
        <button title="promote to user memory (durable)" onclick="promoteMemory('${m.id}')">⤴</button>
        <button title="edit" onclick="editMemory('${m.id}')">✎</button>
        <button title="delete" onclick="delMemory('${m.id}')">✕</button></div>`).join('')+'</div>').join('')
      ||emptyBox('No session memories yet','These capture the working context of each conversation (goals, decisions, constraints) and are injected only into that conversation.');
  }
  window.__mems=Object.fromEntries(d.memories.map(m=>[m.id,m.content]));
  const pb=panelShell(body,{
    title:'Memory',
    search:{id:'mem-q',placeholder:'Search memories…'},
    actions:segTabs('mem-tabs',[`User (${user.length})`,`Sessions (${sess.length})`],memTab==='user'?0:1,'memSetTab')
      +`<label class="row" style="flex:0 0 auto;align-items:center;gap:6px;margin:0;font-size:12px" title="After every chat turn, a background pass extracts user memories, session memories and knowledge-graph facts">
        <input type="checkbox" id="mem-auto" style="width:auto" ${auto?'checked':''} onchange="setAutoLearn(this.checked)">auto-learn</label>
      <button class="pghost" title="merge duplicate entities, roll up idle sessions, re-index memory" onclick="tidyKnowledge()">Tidy</button>`,
  });
  pb.innerHTML=`
    ${items}
    <div class="sect">Add a ${memTab==='user'?'user':'session'} memory</div>
    <div class="row"><input id="mem-new" placeholder="${memTab==='user'?'e.g. My name is Piyush; I work at Accacia.':'e.g. We decided to use SQLite for this project.'}">
      <button class="pact" style="flex:0 0 90px" onclick="addMemory()">Add</button></div>
    ${memTab==='session'&&!currentConv?'<p class="mut" style="margin-top:8px">Session memories attach to the active chat — open a conversation first.</p>':''}`;
}
function memSetTab(i){memTab=i===0?'user':'session';refreshApp('memory')}
async function addMemory(){const v=$('#mem-new').value.trim();if(!v)return;
  const b={content:v,scope:memTab};
  if(memTab==='session'){if(!currentConv){toast('open a conversation first');return}b.conversation_id=currentConv}
  await fetch('/api/memories',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});refreshApp('memory');}
async function delMemory(id){await fetch('/api/memories/'+id,{method:'DELETE'});refreshApp('memory');}
async function pinMemory(id,p){await fetch('/api/memories/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({pinned:p})});refreshApp('memory');}
async function promoteMemory(id){await fetch('/api/memories/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({scope:'user'})});toast('promoted to user memory');refreshApp('memory');}
async function editMemory(id){
  const cur=(window.__mems||{})[id]||'';
  const v=await osPrompt('Edit memory',{value:cur,confirmText:'Save'});
  if(v===null||!v.trim()||v.trim()===cur)return;
  await fetch('/api/memories/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:v.trim()})});refreshApp('memory');}
async function setAutoLearn(on){
  await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({memory:{auto_extract:!!on}})});
  toast(on?'auto-learn on — memory & knowledge graph populate from every chat':'auto-learn off');}
async function tidyKnowledge(){
  await fetch('/api/knowledge/maintain',{method:'POST'});
  toast('tidying knowledge in the background — merging duplicates, rolling up idle sessions, indexing memory');}

/* ================= profile app — everything the agent knows about you ================= */
async function renderProfile(body){
  const [ms,kg,soul,st]=await Promise.all([
    fetch('/api/memories').then(r=>r.json()),
    fetch('/api/kg').then(r=>r.json()),
    fetch('/api/soul').then(r=>r.json()),
    fetch('/api/knowledge/status').then(r=>r.json()).catch(()=>({}))]);
  const user=ms.memories.filter(m=>(m.scope||'user')==='user');
  const byid={};kg.nodes.forEach(n=>byid[n.id]=n.name);
  const facts=kg.edges.map(e=>({s:byid[e.src]||'?',r:e.relation,o:byid[e.dst]||'?'}));
  const stat=(n,l)=>`<div class="stat" style="text-align:center"><div class="val">${n}</div><div class="lbl">${l}</div></div>`;
  body.innerHTML=`<div class="pad">
    <div class="tmgrid" style="margin-bottom:12px">
      ${stat(user.length,'user memories')}${stat(st.session_memories??ms.memories.length-user.length,'session memories')}
      ${stat(facts.length,'known facts')}${stat(st.kg_nodes??kg.nodes.length,'entities')}
    </div>
    <p class="mut" style="margin:0 0 12px">Semantic recall: ${st.embed_model?('<b>on</b> · '+esc(st.embed_model)+(st.unembedded?` (${st.unembedded} to index)`:'')):'<b>off</b> — install an Ollama embedding model (e.g. <code>nomic-embed-text</code>)'} ·
      Auto-learn: <b>${st.auto_extract===false?'off':'on'}</b></p>
    <div class="ptitle">What the agent knows about you</div>
    ${user.slice(0,50).map(m=>`<div class="item"><div class="grow">${m.pinned?'<span class="badge" style="font-size:9px;padding:1px 6px;margin-right:4px">pinned</span>':''}${esc(m.content)}</div></div>`).join('')||'<p class="mut">Nothing yet — it learns as you chat.</p>'}
    <div class="ptitle" style="margin-top:14px">How things connect</div>
    ${facts.slice(0,50).map(f=>`<div class="item"><div class="grow">${esc(f.s)} <span class="mut">—${esc(f.r)}→</span> ${esc(f.o)}</div></div>`).join('')||'<p class="mut">The knowledge graph is empty.</p>'}
    <div class="ptitle" style="margin-top:14px">Soul</div>
    <pre style="white-space:pre-wrap;font-size:12px;opacity:.85;max-height:180px;overflow:auto">${esc((soul.content||'').slice(0,2500))}</pre>
    <div class="row" style="margin-top:10px">
      <button class="endbtn" onclick="openApp('memory')">◈ Manage memory</button>
      <button class="endbtn" onclick="openApp('kg')">Knowledge graph</button>
      <button class="endbtn" onclick="openApp('soul')">Edit soul</button>
      <button class="endbtn" onclick="tidyKnowledge()">Tidy now</button>
    </div></div>`;
}

