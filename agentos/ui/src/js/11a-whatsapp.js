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
  box.innerHTML=`${hook}${pairing}${win}${others}
    ${d.configured&&d.enabled?`<div class="wa-line"><button class="endbtn"
      onclick="waTest()">Send me a test message</button>
      <small id="wa-test" class="mut"></small></div>`:''}`;
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
