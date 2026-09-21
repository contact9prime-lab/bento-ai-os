/* ================= accounts: the mailbox and the calendar the agent may read =================
   One card per account (agentos/accounts.py), each saving on its own — PUT
   /api/accounts/<id> — and each carrying the one thing a form cannot: the LAST
   REAL PROBE. A filled-in card is not a working account; "Test" signs in and the
   card says what the server said. A saved password is a chip with no input
   (pSecret), so nothing can echo it back.

   Faces — GUI: this. SUI: identical. TUI: `bento mail` / `bento calendar`.
   `var`, not `let` (see CLAUDE.md on the bundle's TDZ trap). */
var ACCTS={list:[]};

async function renderAccounts(){
  const box=document.getElementById('acct-list');if(!box)return;
  let d={};try{d=await (await fetch('/api/accounts')).json()}catch(e){}
  ACCTS.list=d.accounts||[];
  if(!ACCTS.list.length){box.innerHTML='<p class="mut">could not read the accounts</p>';return}
  box.innerHTML=ACCTS.list.map(acctCard).join('');
  ACCTS.list.forEach(a=>{const sel=document.getElementById('ac-'+a.id+'-preset');if(sel)sel.onchange=()=>acctPreset(a.id)});
}
function acctCard(a){
  const lt=a.last_test||{};
  const dot=lt.ok?'on':(a.configured?(lt.detail?'warn':'off'):'off');
  const status=lt.detail?(lt.ok?'✓ ':'✗ ')+lt.detail+(lt.at?' · '+new Date(lt.at*1000).toLocaleString():''):
    (a.configured?'set up — not tested yet':'not set up');
  const fields=a.fields.map(f=>{
    const id='ac-'+a.id+'-'+f.key;
    let ctl;
    if(f.kind==='select')ctl=pSelect(id,[['','— choose —']].concat(f.options),a.values[f.key]||'');
    else if(f.kind==='secret')ctl=pSecret(id,a.set[f.key],a.masked[f.key],f.placeholder);
    else ctl=pText(id,a.values[f.key],f.placeholder,f.kind==='number'?'number':'text');
    return pRow(f.label,ctl,{f:a.id+' '+f.key});
  }).join('');
  return `<div class="pgroup chan" data-f="account ${esc(a.id)} ${esc(a.title)}">
    <h3>${esc(a.title)} <span class="chdot ${dot}">${esc(status)}</span></h3>
    <div class="ghint">${esc(a.what)}</div>
    ${a.hint?`<div class="ghint acct-hint" id="ac-${a.id}-hint">${esc(a.hint)}</div>`:`<div class="ghint acct-hint mut" id="ac-${a.id}-hint"></div>`}
    ${pRow('Switched on',pSwitch('ac-'+a.id+'-on',a.enabled),{desc:a.problem&&a.configured?esc(a.problem):'',f:a.id+' enabled'})}
    ${fields}
    <div class="prow"><div class="pl"><small id="ac-${a.id}-msg" class="mut"></small></div>
      <div class="pc"><button class="endbtn" onclick="acctTest('${esc(a.id)}')">Test</button>
        <button class="endbtn" onclick="acctSave('${esc(a.id)}')">Save</button></div></div>
  </div>`;
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
    if(el.tagName==='INPUT'||el.tagName==='SELECT')body[k]=el.value;
  });
  return body;
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
