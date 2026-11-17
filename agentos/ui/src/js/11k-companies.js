/* ---------------- Settings → Companies ----------------
   Asked for as "where is the place in the settings where I can define companies and attach
   folders, management of the companies? I need it in the settings". The companies lived only
   in the Office's ▦ Company panel, which is where departments are DESIGNED. This tab is where
   the companies themselves are managed: every company you keep (open or parked), its name,
   line and objective, a new one, the folders it works in, its departments at a glance, and
   whether it is in your Brief.

   Nothing new is decided here. Each control is a route the panel or the CLI already uses:
   /api/companies (list, create, open, remove), /api/companies/one (one company, open or parked,
   and its name, line and objective), /api/company/folders (company.set_folders, the same checks
   the panel gets), /api/brief/schedule (the Brief's per-company switch).

   The tab is split into sub-sections by the cards' titles (SETSUBS in 11l-setsubs.js), so the
   cards are drawn as children of `.set-subroot`. Everything is text nodes or esc()'d: a company's
   name is the person's words. TUI: `bento company companies|new|open|drop|folders`. SUI: the
   same page. A Zero has no companies of its own (ZERO_TABS_HIDDEN). */
var COSET={list:[],sel:'',d:null,brief:[],err:'',ferr:'',busy:false};

/* One picker at the top decides what the sections below are about: the Default company
   (every agent, and everything outside a company) or one of your companies. Asked for as
   "the settings for the company need to be more intuitive" and "everywhere is the default
   company, just to make it clear". '@default' is the Default company; '' is an open company
   that has no id yet (a single company is given one when it first needs it). */
var CO_DEFAULT='@default';
async function coSetPaint(){
  const box=document.getElementById('co-set');if(!box)return;
  try{
    const [l,b]=await Promise.all([apiJSON('/api/companies'),apiJSON('/api/brief').catch(()=>({}))]);
    COSET.list=l.companies||[];COSET.max=l.max||8;COSET.brief=b.companies||[];
    COSET.briefOn=!(b.schedule&&b.schedule.on===false);
    if(COSET.sel!==CO_DEFAULT){
      const want=COSET.list.find(c=>c.id&&c.id===COSET.sel)||COSET.list.find(c=>c.active)||COSET.list[0];
      COSET.sel=want?want.id:CO_DEFAULT;
    }
    COSET.d=COSET.sel===CO_DEFAULT?null:await apiJSON('/api/companies/one?id='+encodeURIComponent(COSET.sel));
    COSET.err='';
  }catch(e){COSET.err=e.message||String(e)}
  coSetDraw();
}

function coSetTop(){
  const L=COSET.list,full=L.length>=(COSET.max||8);
  return `<div class="co-top" data-f="company default company pick choose switch manage">
    <label class="co-top-pick"><span>Settings for</span><select id="co-pick" aria-label="Which company these settings are for">
      <option value="${CO_DEFAULT}"${COSET.sel===CO_DEFAULT?' selected':''}>Default company · every agent</option>
      ${L.map(c=>`<option value="${esc(c.id)}"${c.id===COSET.sel?' selected':''}>${esc(c.name)}${c.active?' (open)':''}</option>`).join('')}
    </select></label>
    <button class="endbtn" id="co-add"${full?' disabled title="You keep as many companies as you can here. Remove one first."':''}>＋ New company</button></div>`;
}

function coSetDraw(){
  const box=document.getElementById('co-set');if(!box)return;
  box.classList.add('set-subroot');
  if(COSET.err){box.innerHTML=`<div class="pgroup"><h3>About</h3><p class="co-bad">${esc(COSET.err)}</p></div>`;return}
  const L=COSET.list,d=COSET.d,def=COSET.sel===CO_DEFAULT,full=L.length>=(COSET.max||8);
  const n=(k,w)=>k+' '+w+(k===1?'':'s');
  const people=k=>n(k,'person').replace('persons','people');
  const briefOn=name=>{const b=COSET.brief.find(x=>x.name===name);return !b||b.on};
  const sw=(attr,on,label,dis)=>`<label class="psw"><input type="checkbox" ${attr}${on?' checked':''}${dis?' disabled':''} aria-label="${esc(label)}"><i></i></label>`;
  // About: the Default company says what it is and lists your companies; a company is its line,
  // objective and whether it is open
  const about=def?`<div class="pgroup" data-f="default company about every agent companies list"><h3>About the Default company</h3>
      <div class="ghint">Every agent, and everything that isn't in one of your companies: agents in no department, and chats in the Default company. Its rules apply everywhere unless a company sets its own.</div>
      ${L.length?L.map(c=>`<div class="prow co-set-row"><div class="pl"><div class="co-set-name"><b>${esc(c.name)}</b>${c.active?' <span class="co-set-tag">open now</span>':''}</div>
          <div class="pdesc">${c.about?esc(c.about)+' · ':''}${n(c.departments,'department')} · ${people(c.people)} · ${n(c.missions||0,'mission')}</div></div>
          <div class="pc co-set-acts"><button class="endbtn" data-co-sel="${esc(c.id)}">Settings</button></div></div>`).join('')
        :'<p class="mut co-set-empty">You don’t keep a company yet. Every agent works for the Default company.</p>'}</div>`
    :d?`<div class="pgroup" data-f="company about name line objective goal open remove"><h3>About ${esc(d.name)}</h3>
      <div class="ghint">${d.active?'Open now: the Office, Chat and new missions belong to it.':'Kept as it is. Open it to work in it.'} ${people((d.departments||[]).reduce((s,x)=>s+(x.people||0),0))} in ${n((d.departments||[]).length,'department')}.</div>
      ${pRow('Name',`<input id="co-s-name" maxlength="48" value="${esc(d.name)}" aria-label="Company name">`,{desc:'What it is called everywhere.',f:'company name rename'})}
      ${pRow('What it does',`<input id="co-s-about" maxlength="200" value="${esc(d.about||'')}" placeholder="One line, e.g. a kids learning YouTube channel" aria-label="What it does">`,
        {desc:'Your agent reads it to tell this business from your others.',f:'company line about what it does'})}
      ${pRow('Goal',`<textarea id="co-s-goal" rows="2" maxlength="400" placeholder="What should it achieve?" aria-label="Goal">${esc(d.objective||'')}</textarea>`,
        {desc:'What the company is for. Its departments and missions work towards it.',stack:true,f:'company objective goal'})}
      <div class="co-set-go">${d.active?'':`<button class="endbtn" data-co-open="${esc(d.id)}">Open it</button>`}
        ${d.active||!d.id?'':`<button class="endbtn co-set-del" data-co-del="${esc(d.id)}" data-co-name="${esc(d.name)}">Remove…</button>`}</div>
      ${COSET.cerr?`<div class="co-bad" role="alert">${esc(COSET.cerr)}</div>`:''}</div>`:'';
  // Working together: who may ask whom here, painted by coTalkPaint
  const talk=`<div class="pgroup" data-f="working together talk message ask each other swarm matrix who may ask whom limits"><h3>Working together</h3>
      <div class="ghint">${def?'How agents ask each other for help, everywhere a company doesn’t say otherwise.'
        :`How agents ask each other while working in ${esc(d?d.name:'this company')}. An empty cell follows the Default company.`}</div>
      <div id="co-talk"><p class="mut">loading…</p></div>
      ${def?pRow('Limits','<div id="s-team-limits" class="team-limits mut">loading…</div>',
        {stack:true,desc:'How far agents can go when they ask each other.',more:'Limits count per task and apply from the next question.',
         f:'team limits hops budget clarify ask back huddle rounds agents swarm'}):''}</div>`;
  const depts=d?`<div class="pgroup" data-f="company departments people heads design office"><h3>Departments</h3>
      <div class="ghint">Who works in each department. You design them in the Office.</div>
      ${d.departments.length?d.departments.map(x=>`<div class="prow"><div class="pl"><b>${esc(x.name)}</b>
        <div class="pdesc">${x.head?'Head '+esc(x.head)+' · ':''}${people(x.people)}${x.about?' · '+esc(x.about):''}</div></div></div>`).join('')
        :`<p class="mut">${esc(d.name)} has no departments yet.</p>`}
      <div class="co-set-go"><button class="endbtn" id="co-d-go">${d.active?'Design departments in the Office':'Open '+esc(d.name)+' and design its departments'}</button></div></div>`:'';
  const folders=d?`<div class="pgroup" data-f="company folders files read write access attach"><h3>Folders</h3>
      <div class="ghint">The folders ${esc(d.name)}’s departments and missions may read and write. Your own agent keeps your account’s folders.</div>
      ${companyFoldersHTML(d.folders,COSET.ferr,false)}</div>`:'';
  const brief=`<div class="pgroup" data-f="company brief morning briefing in the brief on off"><h3>In your Brief</h3>
      <div class="ghint">The Brief is what your missions leave for you, sent at the times you set in the Brief app.</div>
      ${pRow('Send me the Brief',sw('id="co-brief-all"',COSET.briefOn,'Send me the Brief'),
        {desc:COSET.briefOn?'It comes at its times, with every company switched on below.':'Off. Nothing is sent; the Brief app still has every item.',
         f:'brief on off send me the brief morning'})}
      ${(def?L:L.filter(c=>c.id===COSET.sel)).map(c=>pRow(c.name,sw(`data-co-brief="${esc(c.name)}"`,briefOn(c.name),c.name+' in your Brief',!COSET.briefOn),
        {desc:briefOn(c.name)?'Its items are in the Brief you are sent.':'Left out of the Brief you are sent. Its items stay in the Brief app.',f:'brief '+c.name})).join('')}
      <div class="co-set-go"><button class="endbtn" id="co-brief-open">Set its times in the Brief app</button></div></div>`;
  const add=(COSET.adding||!L.length)?`<div class="pgroup" data-f="new company create start another business"><h3>A new company</h3>
      <div class="ghint">It gets its own office, people, memory and folders, and opens straight away. The one you have now is kept as it is.</div>
      ${pRow('Name',`<input id="co-n-name" maxlength="48" placeholder="e.g. Homes" aria-label="New company's name">`,{f:'new company name'})}
      ${pRow('What it does',`<input id="co-n-about" maxlength="200" placeholder="e.g. three rented apartments" aria-label="What it does">`,{f:'new company about'})}
      ${pRow('Goal',`<input id="co-n-goal" maxlength="400" placeholder="optional" aria-label="Goal">`,{f:'new company objective goal'})}
      <div class="co-set-go"><button class="endbtn" id="co-n-go"${full?' disabled':''}>Start it</button></div></div>`:'';
  box.innerHTML=coSetTop()+about+talk+depts+folders+brief+add;
  coSetWire(box);
  coTalkPaint();
  if(def&&typeof paintTeamLimits==='function')paintTeamLimits();
}

/* Who may ask whom, for the company the picker names. The Default company's mode is
   team.talk and its grid is every agent (the cells with no company); a company has a mode of
   its own or the Default company's, and cells for its own people that fall back to the Default
   company's when empty (fabric.matrix(company=), policy.PDP._talk_here). */
async function coTalkPaint(){
  const box=document.getElementById('co-talk');if(!box)return;
  const def=COSET.sel===CO_DEFAULT,d=COSET.d;
  let m={};
  try{m=await apiJSON('/api/team/matrix'+(def?'':'?company='+encodeURIComponent((d&&(d.id||d.name))||'')))}
  catch(e){box.innerHTML=`<p class="co-bad">${esc(e.message||String(e))}</p>`;return}
  const words={matrix:'Ask me first',swarm:'Swarm: they work together freely',off:'Off'};
  const deflt=(cfg.team&&cfg.team.talk)||'matrix';
  const mode=def?(m.talk||'matrix'):(m.own_talk||'');
  const opts=def?Object.entries(words):[['','Default company’s: '+(words[deflt]||deflt).split(':')[0]],...Object.entries(words)];
  const names=m.agents||[],cells=m.cells||{},base=m.base||{},eff=m.talk||'matrix';
  const head=pRow('Agents message each other',`<select id="co-talk-mode" aria-label="How agents message each other">${opts.map(([v,l])=>
      `<option value="${esc(v)}"${v===mode?' selected':''}>${esc(l)}</option>`).join('')}</select>`,
    {desc:'Let an agent ask a colleague for help in the middle of a task.',
     more:'Ask me first: you are asked the first time, and Allow & remember fills the cell. Swarm: every cell you haven’t blocked is open, and your lead hands your specialists work without asking. A colleague answers with its own model and permissions.',
     f:'talk mode swarm matrix off ask me first'});
  let grid='';
  // the open company may decide it per department instead (company.dept_matrix): colleagues in
  // one department may ask each other, and department cells decide between departments
  let dm=null;
  if(!def&&d&&d.active&&(d.departments||[]).length>=2){try{dm=(await apiJSON('/api/team/matrix')).departments||null}catch(e){}}
  const level=dm?`<div class="tm-legend"><button class="co-link tm-level co-lv" data-mode="${dm.mode==='department'?'agent':'department'}">${dm.mode==='department'?'Decide it per agent instead':'Decide it per department instead'}</button></div>`:'';
  if(eff!=='off'&&dm&&dm.mode==='department'){
    box.innerHTML=head+'<div class="team-matrix co-grid" id="co-dgrid"></div>';
    paintDeptMatrix(box.querySelector('#co-dgrid'),dm,eff);
    coTalkWire(box,def,d,words);
    return;
  }
  if(eff==='off')grid=`<p class="mut co-talk-off">Off${def?'':' in '+esc(d.name)}. Agents can’t message each other here.</p>`;
  else if(names.length<2)grid=`<p class="mut">${def?'You need at least two agents':'This company needs at least two people'} before they can message each other.</p>`;
  else{
    const dflt=v=>v==='allow'?'allow':v==='deny'?'block':eff==='swarm'?'swarm':'ask';
    grid=`<div class="team-matrix co-grid"><table><tr><th></th>${names.map(x=>`<th>${avatarImg(x,'')}${esc(x)}</th>`).join('')}</tr>
      ${names.map(a=>`<tr><th class="tm-row">${avatarImg(a,'')}${esc(a)}</th>${names.map(b=>{
        if(a===b)return '<td><div class="tm-self" aria-hidden="true"></div></td>';
        const own=cells[a+'>'+b]||'',inh=def?'':(base[a+'>'+b]||'');
        const v=own||inh,cls=(v==='allow'?'allow':v==='deny'?'deny':eff==='swarm'?'swarm':'')+(own||def?'':' inherited');
        const said=own?dflt(own):def?dflt(''):'as Default: '+dflt(inh);
        return `<td><button class="tm-cell ${cls}" data-a="${esc(a)}" data-b="${esc(b)}" data-v="${own}" title="${esc(a)} → ${esc(b)}: ${esc(said)}" aria-label="${esc(a)} may ask ${esc(b)}: ${esc(said)}">${esc(own||def?dflt(own):dflt(inh))}</button></td>`}).join('')}</tr>`).join('')}</table></div>
      <div class="tm-legend">Rows ask, columns answer. Tap a cell to switch between ${def?'ask':'the Default company’s'}, allow and block.${def?'':' A faded cell follows the Default company.'}</div>`;
  }
  box.innerHTML=head+grid+level;
  coTalkWire(box,def,d,words);
}
function coTalkWire(box,def,d,words){
  box.querySelector('.co-lv')?.addEventListener('click',e=>teamMatrixLevel(e.target.dataset.mode));
  const sel=box.querySelector('#co-talk-mode');
  if(sel)sel.onchange=async()=>{
    try{
      if(def){const r=await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({team:{talk:sel.value}})});
        if(!r.ok)throw new Error('could not save');cfg.team={...(cfg.team||{}),talk:sel.value}}
      else{const j=await apiJSON('/api/companies/talk',{method:'PUT',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({company:(d&&(d.id||d.name))||'',talk:sel.value})});if(j&&j.error)throw new Error(j.error)}
      toast('✓ '+(sel.value?words[sel.value].split(':')[0]:'Follows the Default company'));
    }catch(e){toast(e.message||String(e),{kind:'err'})}
    if(!def&&!COSET.sel)await coSetPaint();else coTalkPaint();
  };
  box.querySelectorAll('.co-grid:not(#co-dgrid) .tm-cell').forEach(btn=>btn.onclick=async()=>{
    const next={'':'allow',allow:'deny',deny:'ask'}[btn.dataset.v]||'ask';
    const r=await fetch('/api/team/matrix',{method:'PUT',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({from:btn.dataset.a,to:btn.dataset.b,effect:next,...(def?{}:{company:(d&&(d.id||d.name))||''})})})
      .then(r=>r.json()).catch(()=>({error:'the server did not answer'}));
    if(r.error){toast(r.error,{kind:'err'});return}
    coTalkPaint();
  });
}

function coSetWire(box){
  box.querySelectorAll('[data-co-sel]').forEach(b=>b.onclick=()=>{COSET.sel=b.dataset.coSel;COSET.ferr='';coSetPaint()});
  const pick=box.querySelector('#co-pick');if(pick)pick.onchange=()=>{COSET.sel=pick.value;COSET.ferr='';COSET.adding=false;coSetPaint()};
  const addb=box.querySelector('#co-add');if(addb)addb.onclick=()=>{COSET.adding=true;coSetDraw();
    if(typeof setSubShow==='function')setSubShow('New company');const f=document.getElementById('co-n-name');if(f)f.focus()};
  box.querySelectorAll('[data-co-open]').forEach(b=>b.onclick=()=>coSetOpen(b.dataset.coOpen,b));
  box.querySelectorAll('[data-co-del]').forEach(b=>b.onclick=()=>coSetRemove(b.dataset.coDel,b.dataset.coName,b));
  const ed=(id,key)=>{const e=box.querySelector('#'+id);if(e)e.onchange=()=>coSetEdit({[key]:e.value},e)};
  ed('co-s-name','name');ed('co-s-about','about');ed('co-s-goal','objective');
  const go=box.querySelector('#co-n-go');if(go)go.onclick=()=>coSetCreate(go);
  const dg=box.querySelector('#co-d-go');if(dg)dg.onclick=()=>coSetDesign(dg);
  box.querySelectorAll('[data-co-brief]').forEach(c=>c.onchange=()=>coSetBrief(c.dataset.coBrief,c.checked,c));
  const ball=box.querySelector('#co-brief-all');if(ball)ball.onchange=()=>coSetBriefAll(ball.checked,ball);
  const bopen=box.querySelector('#co-brief-open');if(bopen)bopen.onclick=()=>openApp('brief');
  const fsec=box.querySelector('.pgroup[data-f^="company folders"]');
  if(fsec&&COSET.d)companyFoldersWire(fsec,COSET.d.folders,coSetFolders);
}

async function coSetCall(url,method,body,ctl){
  if(ctl)ctl.disabled=true;
  try{const j=await apiJSON(url,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
    if(j&&j.error)throw new Error(j.error);return j}
  finally{if(ctl)ctl.disabled=false}
}
async function coSetEdit(fields,ctl){
  try{const j=await coSetCall('/api/companies/one','PUT',{id:COSET.sel,...fields},ctl);
    COSET.cerr='';toast('✓ Saved');if(typeof setSavedMark==='function')setSavedMark(true);
    if(fields.name)await coSetPaint()}
  catch(e){COSET.cerr=e.message||String(e);toast('could not save: '+COSET.cerr,{kind:'err'});coSetDraw()}
}
async function coSetOpen(id,ctl){
  try{const j=await coSetCall('/api/companies/active','PUT',{id},ctl);
    toast(`✓ ${j.company.name} is open`);COSET.sel=id;
    if(typeof officeLoad==='function')officeLoad();await coSetPaint()}
  catch(e){toast('could not open it: '+(e.message||e),{kind:'err'})}
}
async function coSetRemove(id,name,ctl){
  if(!await osConfirm(`Remove ${name}?`,'Its desks and missions are switched off. Its agents, missions and memory are kept, so nothing is lost.'))return;
  try{const j=await coSetCall('/api/companies/'+encodeURIComponent(id),'DELETE',null,ctl);
    toast(`${name} is off your list`+(j.switched_off&&j.switched_off.length?`; ${j.switched_off.length} missions switched off`:''));
    if(COSET.sel===id)COSET.sel='';await coSetPaint()}
  catch(e){toast('could not remove it: '+(e.message||e),{kind:'err'})}
}
async function coSetCreate(ctl){
  const v=id=>((document.getElementById(id)||{}).value||'').trim();
  const name=v('co-n-name');if(!name){const e=document.getElementById('co-n-name');if(e)e.focus();return}
  try{const j=await coSetCall('/api/companies','POST',{name,about:v('co-n-about'),objective:v('co-n-goal')},ctl);
    toast(`✓ ${j.company.name} is started and open`);COSET.sel=j.company.id||'';COSET.adding=false;
    if(typeof officeLoad==='function')officeLoad();await coSetPaint();
    if(typeof setSubShow==='function')setSubShow('About')}
  catch(e){toast('could not start it: '+(e.message||e),{kind:'err'})}
}
async function coSetFolders(body,ctl){
  try{const j=await coSetCall('/api/company/folders','PUT',{company:(COSET.d&&COSET.d.folders&&COSET.d.folders.id)||COSET.sel||'',...body},ctl);
    COSET.ferr='';COSET.d.folders=j;
    toast(j.inherit?`${j.company} uses your account's folders`
      :`${j.company} works in ${j.folders.length} ${j.folders.length===1?'folder':'folders'}`)}
  catch(e){COSET.ferr=e.message||String(e);toast(COSET.ferr,{kind:'err'})}
  coSetDraw();
}
async function coSetBrief(name,on,ctl){
  try{await coSetCall('/api/brief/schedule','PUT',{companies:{[name]:on}},ctl);
    toast(on?`${name} is in your Brief`:`${name} is left out of your Brief`);
    const b=COSET.brief.find(x=>x.name===name);if(b)b.on=on}
  catch(e){toast('could not save: '+(e.message||e),{kind:'err'});if(ctl)ctl.checked=!on}
}
/* The account's own switch (brief.on): off keeps the times and the items, and sends nothing. */
async function coSetBriefAll(on,ctl){
  try{await coSetCall('/api/brief/schedule','PUT',{on},ctl);COSET.briefOn=on;
    toast(on?'Your Brief is on':'Your Brief is off. Nothing is sent until you switch it on')}
  catch(e){toast('could not save: '+(e.message||e),{kind:'err'});if(ctl)ctl.checked=!on}
  coSetDraw();
}
async function coSetDesign(ctl){
  const d=COSET.d;if(!d)return;
  if(!d.active){try{await coSetCall('/api/companies/active','PUT',{id:d.id},ctl);if(typeof officeLoad==='function')await officeLoad()}
    catch(e){toast('could not open it: '+(e.message||e),{kind:'err'});return}}
  openApp('office');setTimeout(()=>{if(typeof officeCompany==='function')officeCompany(true)},500);
}
