/* ================= WhatsApp: the two things a form cannot say =================
   The generic channel card in 11-settings draws WhatsApp's four fields fine. What
   it cannot draw are the two things that decide whether this channel actually
   works, and neither is a setting:

     1. The callback URL Meta has to be given, and whether this machine is
        reachable at all. A webhook channel that is "on" but unreachable receives
        nothing, forever, with no error anywhere — the most confusing state this
        integration has, so it is stated rather than left to be discovered.

     2. Meta's 24-hour window. Outside it WhatsApp refuses free-form messages
        outright, so "connected" and "can reach you right now" are different facts
        and the card shows both.

   `var`, not `let` — concatenated bundle, see CLAUDE.md. */
var WA={info:null};

async function waLoad(){
  try{WA.info=await (await fetch('/api/whatsapp')).json()}catch(e){WA.info=null}
  return WA.info;
}

/* Rendered into the placeholder chanCard leaves for it, after the fields. */
async function waPanel(){
  const box=document.getElementById('wa-extra');if(!box)return;
  const d=await waLoad();
  if(!d){box.innerHTML='';return}
  // Two transports, one card. Which one is showing is decided by cfg, not by
  // guessing from which fields happen to be filled in.
  if((d.mode||'cloud')==='baileys'){box.innerHTML=waLinkPanel(d);return}
  const reach=d.reach||{};
  const hook=reach.reachable
    ? `<div class="wa-hook"><b>Callback URL</b>
        <code id="wa-url">${esc(reach.webhook)}</code>
        <button class="endbtn" onclick="waCopy()">Copy</button>
        <em>Paste this into the WhatsApp product page on developers.facebook.com,
          with your verify token, and subscribe to <code>messages</code>.</em></div>`
    : `<div class="wa-hook warnbox"><b>Meta cannot reach this machine yet</b>
        <em>${esc(reach.why||'')}</em></div>`;
  const pairing=d.owner_wa_id
    ? `<div class="wa-line"><b>Paired</b> <code>+${esc(d.owner_wa_id)}</code>
        <button class="endbtn" onclick="waUnpair()">Unpair</button></div>`
    : `<div class="wa-line mut">Not paired yet — message the number from your phone
        once, and that chat becomes the owner.</div>`;
  // Two different facts, said separately on purpose.
  const win=d.owner_wa_id
    ? (d.window_open
        ? `<div class="wa-line ok">The ${d.window_hours}-hour window is open — it can
             message you right now.</div>`
        : `<div class="wa-line warn">The ${d.window_hours}-hour window has closed.
             WhatsApp will not let it speak first; send anything to the number and it
             reopens for a day.</div>`)
    : '';
  const chats=(d.chats||[]).filter(c=>c.wa_id!==d.owner_wa_id);
  const others=chats.length
    ? `<div class="wa-line"><b>Other numbers that wrote in</b></div>`
      +chats.map(c=>`<div class="item wa-row"><div class="grow">
          <code>+${esc(c.wa_id)}</code> ${esc(c.name||'')}</div>
        <button class="endbtn" onclick="waAllow('${esc(c.wa_id)}',${c.allowed?0:1})">
          ${c.allowed?'Block':'Allow'}</button></div>`).join('')
    : '';
  // The way back. Without it, choosing the Business API once is a one-way door:
  // the four fields are the only thing on screen and nothing offers the QR again.
  const modeSwitch=`<div class="wa-line mut" style="margin-top:10px">
    Using the <b>Business (Cloud) API</b> — official, and it needs the fields above.
    <button class="endbtn" onclick="waSetMode('baileys')">Scan a QR code instead</button></div>`;
  box.innerHTML=`${hook}${pairing}${win}${others}
    ${d.configured&&d.enabled?`<div class="wa-line"><button class="endbtn"
      onclick="waTest()">Send me a test message</button>
      <small id="wa-test" class="mut"></small></div>`:''}${modeSwitch}`;
}

function waCopy(){
  const el=document.getElementById('wa-url');if(!el)return;
  navigator.clipboard.writeText(el.textContent.trim()).then(()=>toast('callback URL copied'));
}
async function waUnpair(){
  if(!await osConfirm('Unpair this number?',
    'The next number to message this WhatsApp becomes the owner.',{confirmText:'Unpair'}))return;
  await fetch('/api/whatsapp',{method:'PUT',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({unpair:true})});
  waPanel();
}
async function waAllow(id,allowed){
  await fetch('/api/whatsapp/chats/'+encodeURIComponent(id),
    {method:'PUT',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({allowed:!!allowed})});
  waPanel();
}
async function waTest(){
  const out=document.getElementById('wa-test');
  if(out){out.textContent='sending…';out.className='mut'}
  try{
    const d=await (await fetch('/api/whatsapp/test',{method:'POST'})).json();
    const bad=String(d.result||'').startsWith('[error]');
    if(out){out.textContent=bad?d.result.replace('[error] ',''):'sent — check your phone';
      out.className=bad?'warn':'ok'}
  }catch(e){if(out){out.textContent='could not reach the server';out.className='warn'}}
}

/* ---- the linked-device (Baileys) transport --------------------------------
   The whole flow is one card: offer → install → scan → paired. Splitting it over
   a wizard would be more screens for four states, and the state is always visible
   from the server anyway. */
function waLinkPanel(d){
  const L=d.link||{};
  const modeSwitch=`<div class="wa-line mut" style="margin-top:10px">
    Using the <b>WhatsApp Web link</b> — no Meta account needed.
    <button class="endbtn" onclick="waSetMode('cloud')">Use the Business API instead</button></div>`;
  if(!L.installed){
    // The consent ladder: what it unlocks, its licence, the honest warning, and
    // one button. Nothing is installed before this is read.
    return `<div class="wa-hook warnbox">
      <b>The WhatsApp Web bridge is not installed</b>
      <em>${esc(L.why||'')}</em>
      <div class="wa-line" style="margin-top:8px">Scan a QR code from your phone and this
        machine becomes a linked device — no Meta developer account, no public webhook,
        no 24-hour reply window.</div>
      <div class="wa-line warn" style="margin-top:6px"><b>Unofficial.</b> It emulates a
        linked WhatsApp Web device. WhatsApp does not support this and has banned
        accounts for automating on it — prefer a spare number.</div>
      <div class="wa-line mut">MIT (Baileys) · needs Node.js · downloads ~60 MB</div>
      <div class="wa-line"><button class="pact" onclick="waInstall()">Install the bridge</button>
        <small id="wa-inst" class="mut"></small></div>
    </div>${modeSwitch}`;
  }
  if(L.state==='qr'&&L.qr_svg){
    return `<div class="wa-hook">
      <b>Scan this with WhatsApp</b>
      <em>On your phone: WhatsApp → Settings → Linked devices → Link a device.
        The code refreshes automatically.</em>
      <div class="wa-qr" style="background:#fff;padding:10px;border-radius:10px;
        width:min(260px,60vw);margin:10px 0">${L.qr_svg}</div>
      <button class="endbtn" onclick="waUnlink()">Cancel</button>
    </div>${modeSwitch}`;
  }
  if(L.state==='ready'){
    const owner=d.owner_wa_id
      ? `<div class="wa-line"><b>Paired</b> <code>+${esc(d.owner_wa_id)}</code></div>`
      : `<div class="wa-line mut">Linked, but nobody has written in yet — message this
           WhatsApp from your phone and that chat becomes the owner.</div>`;
    return `<div class="wa-line ok">● Linked as <code>${esc((L.me||'').split(':')[0])}</code>
        — it can message you at any time (no 24-hour window on a linked device).</div>
      ${owner}
      <div class="wa-line"><button class="endbtn" onclick="waTest()">Send me a test message</button>
        <small id="wa-test" class="mut"></small>
        <button class="endbtn" onclick="waUnlink()">Unlink</button></div>${modeSwitch}`;
  }
  const err=L.error?`<div class="wa-line warn">${esc(L.error)}</div>`:'';
  return `<div class="wa-line">Ready to link this machine to WhatsApp.</div>${err}
    <div class="wa-line"><button class="pact" onclick="waLink()">Link with a QR code</button>
      <small id="wa-link" class="mut"></small></div>${modeSwitch}`;
}

/* The transports are named `baileys` and `cloud` — the same strings `whatsapp.MODES`
   validates against. Not `link`, which is what this sent for the life of the button:
   the server answered `{ok:false, "whatsapp mode is one of baileys, cloud"}`, this
   threw the answer away, and waPanel() redrew the identical panel. A rejected write
   and a successful one looked exactly alike, so "Scan a QR code instead" simply did
   nothing, with nowhere to find out why. Say it instead. */
async function waSetMode(mode){
  try{
    const r=await fetch('/api/whatsapp',{method:'PUT',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})});
    const d=await r.json();
    if(!r.ok||d.ok===false)return toast(d.message||d.error||'could not switch');
  }catch(e){return toast('could not reach the server')}
  waPanel();
}
async function waInstall(){
  const out=document.getElementById('wa-inst');
  if(out){out.textContent='installing — this takes a minute…';out.className='mut'}
  try{
    const r=await fetch('/api/components',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id:'whatsapp-bridge'})});
    const d=await r.json();
    if(!r.ok||d.error||d.ok===false){
      // `message` FIRST: components.install() puts the reason there — the npm output,
      // or the command to run by hand — and error/detail are only set by the HTTP
      // layer. Reading those two alone is why a real explanation ("Root access is
      // needed", npm's own failure) arrived and was replaced with "install failed".
      if(out){
        out.textContent=d.error||d.detail||d.message||'install failed';
        // A hand-back is not a failure, it is an instruction, and it is useless
        // without the command it refers to.
        if(d.needs_terminal&&d.command)out.textContent+='  '+d.command;
        out.className='warn';
      }
      return}
    toast('WhatsApp bridge installed');
  }catch(e){if(out){out.textContent='could not reach the server';out.className='warn'}return}
  waPanel();
}
async function waLink(){
  const out=document.getElementById('wa-link');
  if(out){out.textContent='starting the bridge…';out.className='mut'}
  try{
    const r=await fetch('/api/whatsapp/link',{method:'POST'});
    const d=await r.json();
    if(!r.ok||d.error){if(out){out.textContent=d.error||'could not start';out.className='warn'}return}
  }catch(e){if(out){out.textContent='could not reach the server';out.className='warn'}return}
  waPanel();
}
async function waUnlink(){
  if(!await osConfirm('Unlink this device?',
    'AgentOS forgets the WhatsApp credentials and the paired chat. You can scan again at any time.',
    {confirmText:'Unlink'}))return;
  await fetch('/api/whatsapp/link',{method:'DELETE'});
  waPanel();
}
