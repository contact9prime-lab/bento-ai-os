/* ================= Settings → Channels → Authorization =================
   Every person and group that reached Telegram or WhatsApp, in one list, waiting first,
   with Allow and Block on each. Asked for as "we need a separate section of Authorization
   for all the channels, so it's easier": requests were spread over the Telegram app's two
   tables and the WhatsApp card, and a group that wrote in sat where nobody looked.
   The list is chanauth.rows on the server, the same one `bento channels who` prints, and
   a decision goes through each bridge's own door, so the person is told they are in.
   Every name is somebody else's words: each cell goes through esc().
   GUI and SUI draw this; the TUI is `bento channels who`, the phones `/allow` and `/block`. */
var CHAN_AUTH={filter:'waiting'};
var CHAN_AUTH_H=['Who','Where','Status','Decided','Messages','Last wrote',''];
async function chanAuthPaint(){
  const box=document.getElementById('chan-auth');if(!box)return;
  let d=null;
  try{d=await apiJSON('/api/channels/authorization')}catch(e){box.innerHTML=`<p class="mut">${esc(String(e.message||e))}</p>`;return}
  const s=d.summary||{},items=d.items||[];
  const f=CHAN_AUTH.filter==='waiting'&&!s.waiting?'all':CHAN_AUTH.filter;
  const shown=f==='all'?items:items.filter(r=>r.state===f);
  const seg=[['waiting','Waiting',s.waiting||0],['allowed','Let in',s.allowed||0],['blocked','Blocked',s.blocked||0],['all','All',items.length]]
    .map(([k,l,n])=>`<button class="${k===f?'on':''}" onclick="chanAuthShow('${jsq(k)}')">${esc(l)} <span class="mut">${n}</span></button>`).join('');
  const rows=shown.map(r=>{
    const where=(r.channel==='telegram'?'Telegram':'WhatsApp')+(r.kind==='group'?' group':'');
    const badge=r.state==='waiting'?'<span class="badge warn">waiting for you</span>'
      :chanBadge(r.state==='allowed',r.state==='allowed'?'let in':'blocked');
    const acts=(r.state!=='allowed'?`<button class="endbtn" onclick="chanAuthDecide('${jsq(r.ref)}',1)">Allow</button>`:'')
      +(r.state!=='blocked'?`<button class="endbtn" onclick="chanAuthDecide('${jsq(r.ref)}',0)">Block</button>`:'');
    return `<tr>${chanCells(CHAN_AUTH_H,[
      `<b>${esc(r.name)}</b>${r.handle?` <span class="mut">${esc(r.handle)}</span>`:''}${r.members?`<small>${esc(r.members)} ${r.members==1?'person':'people'} wrote there</small>`:''}`,
      esc(where),badge,r.decided_at?chanDecided(r):'<span class="mut">not yet</span>',
      esc(r.messages||0),esc(chanWhen(r.last_seen)),`<span class="ct-act">${acts}</span>`])}</tr>`;
  });
  const empty=f==='waiting'?'Nobody is waiting.':'Nobody here yet. When somebody or a group writes to your Telegram bot or WhatsApp, they show up here.';
  const notes=[];
  if(d.telegram_privacy)notes.push(`<div class="wa-line warn"><b>Telegram groups.</b> ${esc(d.telegram_privacy)}</div>`);
  if(d.whatsapp_mode==='cloud')notes.push(`<div class="wa-line mut">WhatsApp groups need the QR-code link. ${pInfo('The Business (Cloud) API does not deliver group messages.')}</div>`);
  box.innerHTML=`<div class="ghint">Who may talk to your agent on Telegram and WhatsApp. New people and groups wait here until you decide. ${pInfo('You get the same question on your Telegram and WhatsApp, and can answer there.')}</div>
    ${notes.join('')}
    <div class="seg" style="margin:8px 16px">${seg}</div>
    ${chanTable(CHAN_AUTH_H,rows,empty)}`;
}
async function chanAuthDecide(ref,allow){
  let d={};
  try{
    const r=await fetch('/api/channels/authorization',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ref,allow:!!allow})});
    d=await r.json().catch(()=>({}));
    if(!r.ok||d.ok===false){toast('Could not change that: '+(d.message||r.status));return}
  }catch(e){toast('could not reach the server');return}
  toast(allow?'Let in. They’ve been told.':'Blocked.');
  chanAuthPaint();
}
function chanAuthShow(k){CHAN_AUTH.filter=k;chanAuthPaint()}
