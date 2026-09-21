/* ================= accounts: the mailbox and the calendar the agent may read =================
   One card per account (agentos/accounts.py). The DOORS come first — Sign in with
   Google / Sign in with Microsoft (signin.py: the consent page opens here, the
   tokens land in the vault), or read through an MCP server — and the app-password
   form sits under "Another provider". A button this install cannot honour (no OAuth
   client registered yet) is greyed with the sentence and the App registration group
   below is where it is fixed; it is never a dead control.

   Every card carries the one thing a form cannot: the LAST REAL PROBE. "Test"
   signs in and the card says what the server said. A saved secret is "in the
   vault", never echoed; the vault line says what protects it on THIS machine.

   Faces — GUI: this. SUI: identical. TUI: `bento mail signin google`, `bento
   vault`. Phone: the sign-in finishes on the phone (the callback is a route).
   `var`, not `let` (see CLAUDE.md on the bundle's TDZ trap). */
var ACCTS={list:[],signin:[],vault:null,admin:true,pending:[]};

async function renderAccounts(){
  const box=document.getElementById('acct-list');if(!box)return;
  let d={};try{d=await (await fetch('/api/accounts')).json()}catch(e){}
  ACCTS.list=d.accounts||[];ACCTS.signin=d.signin||[];ACCTS.vault=d.vault||null;ACCTS.admin=d.admin!==false;ACCTS.pending=d.pending||[];
  if(!ACCTS.list.length){box.innerHTML='<p class="mut">could not read the accounts</p>';return}
  box.innerHTML=acctSigninCard()+ACCTS.list.map(acctCard).join('')+acctClientsCard()+acctVaultLine();
  ACCTS.list.forEach(a=>{const sel=document.getElementById('ac-'+a.id+'-preset');if(sel)sel.onchange=()=>acctPreset(a.id)});
}

/* the doors: one row of sign-in buttons for both accounts, since one sign-in serves both */
function acctSigninCard(){
  const rows=ACCTS.signin.map(s=>{
    const rec=s.signed_in||{};
    const on=!!rec.email;
    const uses=(rec.uses||[]).filter(u=>u!=='send');
    const status=on?`signed in as <b>${esc(rec.email)}</b> · reads ${esc(uses.join(' and ')||'nothing yet')}${(rec.uses||[]).includes('send')?' · can send':''}${rec.problem?' · <span class="warn">'+esc(rec.problem)+'</span>':''}`
      :(s.available?'not signed in':'');
    const pend=ACCTS.pending.find(p=>p.provider===s.id);
    const btns=on?`<button class="endbtn" onclick="acctSignin('${s.id}')">Sign in again</button>
        <button class="endbtn" onclick="acctSignout('${s.id}')">Sign out</button>`
      :(s.available?`<button class="endbtn acct-signin" onclick="acctSignin('${s.id}')">Sign in with ${esc(s.label)}</button>`
        :`<button class="endbtn" disabled title="${esc(s.why)}">Sign in with ${esc(s.label)}</button>`);
    const why=(!on&&!s.available)?`<div class="ghint acct-why">${esc(s.why.split('. ')[0])}. <a href="#" onclick="document.getElementById('acct-clients').scrollIntoView({block:'center'});return false">App registration ↓</a></div>`:'';
    const wait=pend?`<div class="ghint">waiting for you to finish signing in (${pend.waiting_for}s) — <a href="${esc(pend.url)}" target="_blank" rel="noopener">open the page again</a></div>`:'';
    return `<div class="prow acct-door" data-f="sign in ${esc(s.label)}"><div class="pl"><b>${esc(s.label)}</b><small class="mut">${status}</small>${why}${wait}</div><div class="pc acct-btns">${btns}</div></div>`;
  }).join('');
  return `<div class="pgroup chan" data-f="accounts sign in google microsoft oauth">
    <h3>Sign in</h3>
    <div class="ghint">One sign-in reads your mail and your calendar. You pick what it may read; the consent page names it; it is revocable from your Google or Microsoft account any time. Sending is asked for separately and every message still asks you first.</div>
    ${rows}
    <div class="prow"><div class="pl"><small class="mut">Asks for:</small></div><div class="pc acct-uses">
      <label><input type="checkbox" id="acct-use-mail" checked> mail</label>
      <label><input type="checkbox" id="acct-use-calendar" checked> calendar</label>
      <label><input type="checkbox" id="acct-use-send"> send (always asks per message)</label></div></div>
  </div>`;
}
function acctUses(){return ['mail','calendar','send'].filter(u=>{const el=document.getElementById('acct-use-'+u);return el&&el.checked})}
/* the consent page opens HERE — this browser is where the human is. On a phone
   driving a headless box the callback still comes back to the box (a route). */
async function acctSignin(provider){
  try{
    const j=await (await fetch('/api/accounts/oauth/'+encodeURIComponent(provider)+'/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({uses:acctUses()})})).json();
    if(j.error){toast(j.error.slice(0,160));return}
    const w=window.open(j.url,'_blank','noopener');
    if(!w)toast('open this to sign in: '+j.url.slice(0,80)+'…');
    toast('finish signing in on the page that opened — this card updates by itself');
    setTimeout(renderAccounts,1500);
  }catch(e){toast('could not reach the server')}
}
async function acctSignout(provider){
  if(typeof osConfirm==='function'?!(await osConfirm('Sign out of '+provider+'? The accounts that read through it are switched off.')):!confirm('Sign out of '+provider+'?'))return;
  try{await fetch('/api/accounts/oauth/'+encodeURIComponent(provider),{method:'DELETE'});renderAccounts();if(typeof refreshApp==='function')refreshApp('jobs')}
  catch(e){toast('could not reach the server')}
}

function acctCard(a){
  const lt=a.last_test||{};
  const dot=lt.ok?'on':(a.configured?(lt.detail?'warn':'off'):'off');
  const status=lt.detail?(lt.ok?'✓ ':'✗ ')+lt.detail+(lt.at?' · '+new Date(lt.at*1000).toLocaleString():''):
    (a.configured?'set up — not tested yet':'not set up');
  const way=a.via;
  const signedWay=way==='google'||way==='microsoft';
  const wayKey=a.id==='mail'?'via':'kind';
  // 'form' = whatever the fields below say (IMAP; an ICS address or CalDAV) — the
  // form decides between ICS and CalDAV itself, so this select never writes `kind`
  // for it and cannot turn a CalDAV account into an ICS one by being saved
  const doorOpts=[['form',a.id==='mail'?'App password (below)':'An address or app password (below)'],['mcp','Through an MCP server']]
    .concat(ACCTS.signin.filter(s=>s.signed_in&&s.signed_in.email).map(s=>[s.id,'Signed in with '+s.label]));
  const doorSel=pSelect('ac-'+a.id+'-'+wayKey,doorOpts,signedWay?way:(way==='mcp'?'mcp':'form'))
    .replace('<select','<select onchange="acctDoor(\''+a.id+'\')"');
  const mcpRow=way==='mcp'?pRow('MCP server',pSelect('ac-'+a.id+'-mcp_server',[['','— choose a connected server —']].concat((a.mcp_servers||[]).map(n=>[n,n])),a.mcp_server||''),
      {desc:(a.mcp_servers||[]).length?'the mission\'s specialists use this server\'s tools instead of the built-in ones':'no MCP server is connected — add one in the MCP app first',f:a.id+' mcp server'}):'';
  const fields=signedWay||way==='mcp'?'':`<details class="acct-adv"><summary>Another provider — an app password${a.id==='calendar'?' or an ICS address':''}</summary>`+a.fields.map(f=>{
    const id='ac-'+a.id+'-'+f.key;
    let ctl;
    if(f.kind==='select')ctl=pSelect(id,[['','— choose —']].concat(f.options),a.values[f.key]||'');
    else if(f.kind==='secret')ctl=pSecret(id,a.set[f.key],a.masked[f.key],f.placeholder);
    else ctl=pText(id,a.values[f.key],f.placeholder,f.kind==='number'?'number':'text');
    return pRow(f.label,ctl,{f:a.id+' '+f.key});
  }).join('')+`</details>`;
  return `<div class="pgroup chan" data-f="account ${esc(a.id)} ${esc(a.title)}">
    <h3>${esc(a.title)} <span class="chdot ${dot}">${esc(status)}</span></h3>
    <div class="ghint">${esc(a.what)}</div>
    ${pRow('Reads through',doorSel,{desc:esc(a.door&&a.door.detail||''),f:a.id+' door via'})}
    ${mcpRow}
    ${pRow('Switched on',pSwitch('ac-'+a.id+'-on',a.enabled),{desc:a.problem&&a.configured?esc(a.problem):'',f:a.id+' enabled'})}
    ${a.hint&&!signedWay?`<div class="ghint acct-hint" id="ac-${a.id}-hint">${esc(a.hint)}</div>`:`<div class="ghint acct-hint mut" id="ac-${a.id}-hint"></div>`}
    ${fields}
    <div class="prow"><div class="pl"><small id="ac-${a.id}-msg" class="mut"></small></div>
      <div class="pc"><button class="endbtn" onclick="acctTest('${esc(a.id)}')">Test</button>
        <button class="endbtn" onclick="acctSave('${esc(a.id)}')">Save</button></div></div>
  </div>`;
}
/* this install's OAuth clients — the machine's, so an admin's; the redirect URI is
   shown because the registration form asks for it and guessing it is the usual failure */
function acctClientsCard(){
  const rows=ACCTS.signin.map(s=>`
    <div class="acct-client" data-f="app registration ${esc(s.label)} client id">
      <div class="ghint"><b>${esc(s.label)}</b> — ${esc(s.hint)} <a href="${esc(s.register)}" target="_blank" rel="noopener">open the console ↗</a></div>
      ${pRow('Redirect URI',`<code class="acct-uri">${esc(s.redirect_uri)}</code>`,{desc:'paste this into the registration as the redirect / callback URI',f:'redirect uri'})}
      ${pRow('Client id',pText('oc-'+s.id+'-client_id',s.client_id||'','…apps.googleusercontent.com','text'),{f:s.label+' client id'})}
      ${s.needs_secret?pRow('Client secret',pSecret('oc-'+s.id+'-client_secret',s.has_secret,s.has_secret?'in config, masked':'','GOCSPX-…'),{desc:'Google issues one for a desktop client and documents it as not secret; it is still masked here',f:s.label+' client secret'}):''}
      ${s.id==='microsoft'?pRow('Tenant',pText('oc-'+s.id+'-tenant',s.tenant||'common','common','text'),{desc:'"common" for personal and work accounts; your tenant id to limit it to one organisation',f:'tenant'}):''}
    </div>`).join('');
  return `<div class="pgroup chan" id="acct-clients" data-f="app registration oauth client id secret">
    <h3>App registration <small class="mut">${ACCTS.admin?'':'admins only'}</small></h3>
    <div class="ghint">Sign in with Google / Microsoft needs an OAuth client that belongs to THIS install — a self-hosted OS has no central application, so the project ships none (the same reason it ships no signing key). Five minutes once, per machine; every account here uses it.</div>
    ${rows}
    <div class="prow"><div class="pl"><small id="oc-msg" class="mut"></small></div><div class="pc"><button class="endbtn" ${ACCTS.admin?'':'disabled'} onclick="acctSaveClients()">Save registration</button></div></div>
  </div>`;
}
async function acctSaveClients(){
  const body={};
  ACCTS.signin.forEach(s=>{const o={};['client_id','client_secret','tenant'].forEach(k=>{const el=document.getElementById('oc-'+s.id+'-'+k);if(el)o[k]=el.value});body[s.id]=o});
  const msg=document.getElementById('oc-msg');
  try{
    const j=await (await fetch('/api/accounts/clients',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
    if(msg){msg.textContent=j.error||'saved — the sign-in buttons above are live';msg.className=j.error?'warn':'ok'}
    if(!j.error)renderAccounts();
  }catch(e){if(msg){msg.textContent='could not reach the server';msg.className='warn'}}
}
/* what protects the secrets on THIS machine — probed, in its own words */
function acctVaultLine(){
  const v=ACCTS.vault;if(!v)return '';
  return `<div class="pgroup chan" data-f="vault secrets keyring"><h3>Vault <span class="chdot ${v.locked?'warn':(v.mechanism?'on':'off')}">${v.count||0} secret${v.count===1?'':'s'}</span></h3>
    <div class="ghint">${esc(v.detail)}${v.names&&v.names.length?' · '+v.names.map(esc).join(', '):''} · <code>bento vault</code></div></div>`;
}
/* choosing a provider shows its one sentence — the app-password sentence is the
   difference between a working card and an evening lost */
function acctPreset(id){
  const a=ACCTS.list.find(x=>x.id===id);if(!a)return;
  const sel=document.getElementById('ac-'+id+'-preset');const p=(a.presets||{})[sel.value]||{};
  const h=document.getElementById('ac-'+id+'-hint');if(h){h.textContent=p.hint||'';h.classList.toggle('mut',!p.hint)}
  if(id==='mail'){const host=document.getElementById('ac-mail-host'),port=document.getElementById('ac-mail-port');
    if(host&&p.host&&!host.value)host.value=p.host;if(port&&p.port&&(!port.value||port.value==='993'))port.value=p.port;
    const sh=document.getElementById('ac-mail-smtp_host'),sp=document.getElementById('ac-mail-smtp_port');
    if(sh&&p.smtp_host&&!sh.value)sh.value=p.smtp_host;if(sp&&p.smtp_port&&(!sp.value||sp.value==='587'))sp.value=p.smtp_port}
  if(id==='calendar'){const url=document.getElementById('ac-calendar-url');if(url&&p.url&&!url.value)url.value=p.url}
}
function acctBody(id){
  const body={};
  const on=document.getElementById('ac-'+id+'-on');if(on)body.enabled=on.checked;
  document.querySelectorAll(`[id^="ac-${id}-"]`).forEach(el=>{
    const k=el.id.slice(('ac-'+id+'-').length);
    if(['on','msg','hint'].indexOf(k)>=0||k.endsWith('-wrap'))return;
    if((k==='via'||k==='kind')&&el.value==='form')return;      // the form decides
    if(el.tagName==='INPUT'||el.tagName==='SELECT')body[k]=el.value;
  });
  return body;
}
/* changing the door re-draws the card around it (the MCP server picker, the
   app-password form) — saved at once, so what is shown is what is on file */
async function acctDoor(id){
  const sel=document.getElementById('ac-'+id+'-'+(id==='mail'?'via':'kind'));if(!sel)return;
  const body={};body[id==='mail'?'via':'kind']=sel.value==='form'?(id==='mail'?'imap':'ics'):sel.value;
  try{const j=await (await fetch('/api/accounts/'+encodeURIComponent(id),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
    if(j.error)toast(j.error);renderAccounts()}catch(e){toast('could not reach the server')}
}
async function acctSave(id,quiet){
  const msg=document.getElementById('ac-'+id+'-msg');
  if(msg&&!quiet){msg.textContent='saving…';msg.className='mut'}
  try{
    const r=await fetch('/api/accounts/'+encodeURIComponent(id),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(acctBody(id))});
    const j=await r.json();
    if(msg&&!quiet){msg.textContent=j.ok?'saved':(j.error||'could not save');msg.className=j.ok?'ok':'warn'}
    if(j.ok&&!quiet)renderAccounts();
    return !!j.ok;
  }catch(e){if(msg){msg.textContent='could not reach the server';msg.className='warn'}return false}
}
/* Test = save what is typed, then really sign in. The outcome is written on the
   account, so the Missions catalogue and this card agree. */
async function acctTest(id){
  const msg=document.getElementById('ac-'+id+'-msg');
  if(msg){msg.textContent='saving, then signing in…';msg.className='mut'}
  if(!await acctSave(id,true)){if(msg){msg.textContent='could not save';msg.className='warn'}return}
  try{
    const j=await (await fetch('/api/accounts/'+encodeURIComponent(id)+'/test',{method:'POST'})).json();
    if(msg){msg.textContent=(j.ok?'✓ ':'✗ ')+(j.detail||j.error||'');msg.className=j.ok?'ok':'warn'}
    renderAccounts();
    if(typeof refreshApp==='function')refreshApp('jobs');
  }catch(e){if(msg){msg.textContent='could not reach the server';msg.className='warn'}}
}
