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

async function coSetPaint(){
  const box=document.getElementById('co-set');if(!box)return;
  try{
    const [l,b]=await Promise.all([apiJSON('/api/companies'),apiJSON('/api/brief').catch(()=>({}))]);
    COSET.list=l.companies||[];COSET.max=l.max||8;COSET.brief=b.companies||[];
    COSET.briefOn=!(b.schedule&&b.schedule.on===false);
    const want=COSET.list.find(c=>c.id&&c.id===COSET.sel)||COSET.list.find(c=>c.active)||COSET.list[0];
    COSET.sel=want?want.id:'';
    COSET.d=want?await apiJSON('/api/companies/one?id='+encodeURIComponent(COSET.sel)):null;
    COSET.err='';
  }catch(e){COSET.err=e.message||String(e)}
  coSetDraw();
}

function coSetPick(){
  // which company the cards below are about; only when there is more than one
  if(COSET.list.length<2)return '';
  return `<label class="co-set-for"><span>Company</span><select class="co-set-pick" aria-label="Which company to manage">${
    COSET.list.map(c=>`<option value="${esc(c.id)}"${c.id===COSET.sel?' selected':''}>${esc(c.name)}${c.active?' (open)':''}</option>`).join('')}</select></label>`;
}

function coSetDraw(){
  const box=document.getElementById('co-set');if(!box)return;
  box.classList.add('set-subroot');
  if(COSET.err){box.innerHTML=`<div class="pgroup"><h3>Your companies</h3><p class="co-bad">${esc(COSET.err)}</p></div>`;return}
  const L=COSET.list,d=COSET.d,full=L.length>=(COSET.max||8);
  const n=(k,w)=>k+' '+w+(k===1?'':'s');
  const rows=L.length?L.map(c=>`<div class="prow co-set-row${c.id===COSET.sel?' sel':''}">
      <div class="pl"><div class="co-set-name"><b>${esc(c.name)}</b>${c.active?' <span class="co-set-tag">open now</span>':''}</div>
        <div class="pdesc">${c.about?esc(c.about)+' · ':''}${n(c.departments,'department')} · ${n(c.people,'person').replace('persons','people')} · ${n(c.missions||0,'mission')}</div></div>
      <div class="pc co-set-acts">
        ${c.id===COSET.sel?'':`<button class="endbtn" data-co-sel="${esc(c.id)}">Manage</button>`}
        ${c.active?'':`<button class="endbtn" data-co-open="${esc(c.id)}">Open</button>`}
        ${c.active||!c.id?'':`<button class="endbtn co-set-del" data-co-del="${esc(c.id)}" data-co-name="${esc(c.name)}">Remove…</button>`}
      </div></div>`).join('')
    :`<p class="mut co-set-empty">You don’t keep a company yet. Start one below, or set one up in the Office.</p>`;
  const about=d?`<div class="co-set-edit">
      <div class="of-sec">About ${esc(d.name)}</div>
      ${pRow('Name',`<input id="co-s-name" maxlength="48" value="${esc(d.name)}" aria-label="Company name">`,{desc:'What it is called everywhere.',f:'company name rename'})}
      ${pRow('What it does',`<input id="co-s-about" maxlength="200" value="${esc(d.about||'')}" placeholder="One line, e.g. a kids learning YouTube channel" aria-label="What it does">`,
        {desc:'Your agent reads it to tell this business from your others.',f:'company line about what it does'})}
      ${pRow('Objective',`<textarea id="co-s-goal" rows="2" maxlength="400" placeholder="What should it achieve?" aria-label="Objective">${esc(d.objective||'')}</textarea>`,
        {desc:'What the company is for. Its departments and missions work towards it.',stack:true,f:'company objective goal'})}
    </div>`:'';
  const depts=d?(d.departments.length?d.departments.map(x=>`<div class="prow"><div class="pl"><b>${esc(x.name)}</b>
        <div class="pdesc">${x.head?'Head '+esc(x.head)+' · ':''}${n(x.people,'person').replace('persons','people')}${x.about?' · '+esc(x.about):''}</div></div></div>`).join('')
      :`<p class="mut">${esc(d.name)} has no departments yet.</p>`):'';
  const briefOn=name=>{const b=COSET.brief.find(x=>x.name===name);return !b||b.on};
  box.innerHTML=`
    <div class="pgroup" data-f="companies list open switch remove manage"><h3>Your companies</h3>
      <div class="ghint">The open one is the one you work in now: the Office, Chat and new missions belong to it.</div>
      ${rows}${about}${COSET.cerr?`<div class="co-bad" role="alert">${esc(COSET.cerr)}</div>`:''}</div>
    <div class="pgroup" data-f="new company create start another business"><h3>A new company</h3>
      <div class="ghint">It gets its own office, people, memory and folders, and opens straight away. The one you have now is kept as it is.</div>
      ${pRow('Name',`<input id="co-n-name" maxlength="48" placeholder="e.g. Homes" aria-label="New company's name">`,{f:'new company name'})}
      ${pRow('What it does',`<input id="co-n-about" maxlength="200" placeholder="e.g. three rented apartments" aria-label="What it does">`,{f:'new company about'})}
      ${pRow('Objective',`<input id="co-n-goal" maxlength="400" placeholder="optional" aria-label="Objective">`,{f:'new company objective'})}
      <div class="co-set-go"><button class="endbtn" id="co-n-go"${full?' disabled title="You keep as many companies as you can here. Remove one first."':''}>Start it</button></div></div>
    <div class="pgroup" data-f="company folders files read write access attach"><h3>Folders</h3>
      <div class="ghint">The folders a company’s departments and missions may read and write. Your own agent keeps your account’s folders.</div>
      ${coSetPick()}${d?companyFoldersHTML(d.folders,COSET.ferr,false):'<p class="mut">Start a company first.</p>'}</div>
    <div class="pgroup" data-f="company departments people heads design office"><h3>Departments</h3>
      <div class="ghint">Who works in each department. You design them in the Office.</div>
      ${coSetPick()}${depts}
      ${d?`<div class="co-set-go"><button class="endbtn" id="co-d-go">${d.active?'Design departments in the Office':'Open '+esc(d.name)+' and design its departments'}</button></div>`:''}</div>
    <div class="pgroup" data-f="company brief morning briefing in the brief on off"><h3>In your Brief</h3>
      <div class="ghint">The Brief is what your missions leave for you, sent at the times you set in the Brief app.</div>
      ${pRow('Send me the Brief',`<label class="psw"><input type="checkbox" id="co-brief-all"${COSET.briefOn?' checked':''} aria-label="Send me the Brief"><i></i></label>`,
        {desc:COSET.briefOn?'It comes at its times, with every company switched on below.':'Off. Nothing is sent; the Brief app still has every item.',
         f:'brief on off send me the brief morning'})}
      ${L.length?L.map(c=>pRow(c.name,`<label class="psw"><input type="checkbox" data-co-brief="${esc(c.name)}"${briefOn(c.name)?' checked':''}${COSET.briefOn?'':' disabled'} aria-label="${esc(c.name)} in your Brief"><i></i></label>`,
        {desc:briefOn(c.name)?'Its items are in the Brief you are sent.':'Left out of the Brief you are sent. Its items stay in the Brief app.',f:'brief '+c.name})).join('')
        :'<p class="mut">No companies yet, so the Brief has everything in it.</p>'}
      <div class="co-set-go"><button class="endbtn" id="co-brief-open">Set its times in the Brief app</button></div></div>`;
  coSetWire(box);
}

function coSetWire(box){
  box.querySelectorAll('[data-co-sel]').forEach(b=>b.onclick=()=>{COSET.sel=b.dataset.coSel;COSET.ferr='';coSetPaint()});
  box.querySelectorAll('.co-set-pick').forEach(s=>s.onchange=()=>{COSET.sel=s.value;COSET.ferr='';coSetPaint()});
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
    toast(`✓ ${j.company.name} is started and open`);COSET.sel=j.company.id||'';
    if(typeof officeLoad==='function')officeLoad();await coSetPaint();
    if(typeof setSubShow==='function')setSubShow('Your companies')}
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
