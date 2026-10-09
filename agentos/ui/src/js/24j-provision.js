/* ================= new machines on the network =================
   provision.py is the whole design; this draws /api/provision. Two faces of it:

   - On a machine that leads (or could): Settings → Agents → Community → New machines.
     Every machine heard waiting is a row (its board, memory, the id to compare with its
     own screen); tick several, type each one's code (or let the community's enrolment
     key prove it), choose what they become (kiosk, one agent, the agent's name) and
     Enable. A machine heard for the first time is also a toast with Review, from
     09-websocket.js, because "whenever a new machine is turned on … we should be able to
     check if we need to provision it".
   - On a machine that is WAITING: a card in the corner of its own screen with the code
     and the id to read out, and "Set it up here instead".

   TUI: `bento pool discover | enable | key | wait`. SUI: identical, a page; nothing here
   touches the compositor. */
var PROV={v:null,sel:{}};

async function provPaint(){
  const box=document.getElementById('s-prov');if(!box)return;
  let v;try{v=await apiJSON('/api/provision')}catch(e){box.innerHTML='';return}
  PROV.v=v;provWaitCard(v);
  const can=v.can_change,rows=[];
  // a waiting machine sets nothing up; its own card says what to do
  if(v.this&&v.this.waiting){
    rows.push(pRow('Waiting to be set up',`<span class="mut">code ${esc(v.this.pin||'(enrolment key)')} · id ${esc(v.this.id)}</span>`
      +`<button class="endbtn" data-prov="nowait"${can?'':' disabled'}>Set it up here instead</button>`,
      {desc:'Another Bento on your network can set this machine up.',
       more:'On the machine that leads your community, choose this one in New machines and type the code.',f:'provision waiting set up code'}));
    box.innerHTML=rows.join('');provWire(box);return;
  }
  if(!(v.role==='leader'||v.has_brain||(v.seen||[]).length)){box.innerHTML='';return}
  const seen=(v.seen||[]).filter(m=>m.state!=='ignored');
  rows.push(pRow('New machines',`<button class="endbtn" data-prov="scan"${can?'':' disabled'}>Look now</button>`,
    {desc:v.watching?'Machines that turn on waiting to be set up show here, and you get a toast.':'This machine is not listening for new ones.',
     more:'A fresh Raspberry Pi with Bento waits by itself. Any other machine waits after bento pool wait on.',
     f:'provision new machines discover raspberry pi poap enable set up scan'}));
  if(seen.length){
    rows.push(`<div class="prov-list">${seen.map(m=>{
      const hw=m.hw||{},on=PROV.sel[m.fp]!==undefined;
      const state=m.state==='enabled'?'set up':m.age<90?'waiting':'waiting · heard '+poolAgo(m.age);
      const proof=m.our_key?`<span class="prov-key">your key${m.auto?', automatic':''}</span>`
        :`<input class="prov-code" data-code="${esc(m.fp)}" inputmode="numeric" maxlength="7" placeholder="code" aria-label="Code on ${esc(m.name)}'s screen"${m.state==='enabled'?' disabled':''}>`;
      return `<div class="prov-m${m.state==='enabled'?' done':''}">
        <label class="prov-pick"><input type="checkbox" data-pick="${esc(m.fp)}" ${on?'checked':''}${m.state==='enabled'||!can?' disabled':''}>
          <b>${esc(m.name)}</b></label>
        <span class="mut">${esc(hw.board||hw.arch||'a machine')} · ${hw.ram_mb||0} MB · id ${esc(m.id)} · ${esc(state)}</span>
        <input class="prov-name" data-name="${esc(m.fp)}" maxlength="32" placeholder="${esc(m.name)}" aria-label="Name for ${esc(m.name)}"${m.state==='enabled'?' disabled':''}>
        ${proof}
        ${m.state!=='enabled'&&can?`<button class="endbtn" data-prov="ignore" data-fp="${esc(m.fp)}">Not this one</button>`:''}</div>`}).join('')}</div>`);
    const f=PROV.form||{kiosk:false,buddy:'auto',agent:''};
    rows.push(pRow('Set them up as',`<label class="prov-opt">${pSwitch('prov-kiosk',!!f.kiosk)} Kiosk</label>
        ${pSelect('prov-buddy',[['auto','Auto'],['on','Only the agent'],['off','The whole crew']],f.buddy)}
        <input id="prov-agent" maxlength="32" placeholder="Agent's name" value="${esc(f.agent||'')}" style="max-width:140px">`,
      {desc:'Each one joins this community and thinks with this machine’s brain.',
       more:'Light mode is on for each, and they get their own agent with that name. You can change any of it on the machine later.',
       f:'provision profile kiosk buddy agent name'}));
    rows.push(pRow('Enable',`<button class="wiz-next" data-prov="enable"${can?'':' disabled'}>Enable with an agent</button>`,
      {desc:'Type the code shown on each machine’s screen, unless it carries your key.',f:'provision enable'}));
  }else{
    rows.push(`<p class="mut prov-empty">No machine is waiting right now. Turn one on, or press Look now.</p>`);
  }
  const ks=v.keys||[];
  rows.push(pRow('Enrolment keys',`${ks.map(k=>`<span class="prov-k">${esc(k.label)}
      <label class="prov-opt">${pSwitch('prov-auto-'+k.id,!!k.auto)} automatic</label>
      <button class="endbtn" data-prov="dropkey" data-kid="${esc(k.id)}">Revoke</button></span>`).join('')}
      <button class="endbtn" data-prov="key"${can?'':' disabled'}>Make a key</button>`,
    {desc:'Put a key on a new machine and nobody has to read a code off its screen.',
     more:'Save it as bento-enroll.txt on the SD card’s boot partition, or install with --enroll. Automatic sets the machine up the moment it is heard.',
     f:'provision enrolment key zero touch sd card automatic'}));
  rows.push('<div id="prov-out" aria-live="polite"></div>');
  box.innerHTML=rows.join('');
  provWire(box);
}
function provWire(box){
  box.querySelectorAll('[data-prov]').forEach(b=>b.onclick=()=>provAct(b.dataset.prov,b));
  box.querySelectorAll('[data-pick]').forEach(c=>c.onchange=()=>{if(c.checked)PROV.sel[c.dataset.pick]=1;else delete PROV.sel[c.dataset.pick]});
  // a typed code ticks its machine, so nobody types six digits and forgets the box
  box.querySelectorAll('[data-code]').forEach(i=>i.oninput=()=>{const c=box.querySelector(`[data-pick="${CSS.escape(i.dataset.code)}"]`);
    if(c&&i.value.replace(/\D/g,'').length===6&&!c.checked){c.checked=true;PROV.sel[i.dataset.code]=1}});
  (PROV.v.keys||[]).forEach(k=>{const s=box.querySelector('#prov-auto-'+k.id);if(s)s.onchange=async()=>{
    const r=await fetch('/api/provision/key/'+encodeURIComponent(k.id),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({auto:s.checked})});
    if(!r.ok)toast('could not change that');provPaint()}});
  const save=()=>{PROV.form={kiosk:!!(box.querySelector('#prov-kiosk')||{}).checked,
    buddy:(box.querySelector('#prov-buddy')||{}).value||'auto',agent:((box.querySelector('#prov-agent')||{}).value||'').trim()}};
  ['#prov-kiosk','#prov-buddy','#prov-agent'].forEach(q=>{const e=box.querySelector(q);if(e)e.onchange=save});
}
async function provAct(act,b){
  const box=document.getElementById('s-prov'),out=document.getElementById('prov-out');
  const post=async(url,body,method)=>{const r=await fetch(url,{method:method||'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
    const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||('could not do that ('+r.status+')'));return d};
  try{
    if(act==='scan'){b.disabled=true;b.textContent='Looking…';const d=await post('/api/provision/scan');
      toast(d.found?`✓ ${d.found} machine${d.found===1?'':'s'} waiting`:'No machine answered. Is it on the same network?');return provPaint()}
    if(act==='ignore'){await post('/api/provision/ignore',{fp:b.dataset.fp});return provPaint()}
    if(act==='nowait'){await post('/api/provision',{wait:false},'PUT');toast('✓ This machine is set up here');return provPaint()}
    if(act==='dropkey'){if(!confirm('Revoke this key? Machines that carry it can no longer be set up with it.'))return;
      await fetch('/api/provision/key/'+encodeURIComponent(b.dataset.kid),{method:'DELETE'});return provPaint()}
    if(act==='key'){
      const label=prompt('A name for this key, like “kitchen Pis”','Pis');if(label===null)return;
      const d=await post('/api/provision/key',{label});
      provPaint().then(()=>{const o=document.getElementById('prov-out');if(!o)return;
        o.innerHTML=`<div class="prov-keytext"><b>Your enrolment key</b> (shown once)
          <code>${esc(d.key.text)}</code>
          <span class="mut">Save it as <code>bento-enroll.txt</code> on the SD card’s boot partition, or run
          <code>bento pool enroll …</code> on the new machine.</span>
          <button class="endbtn" id="prov-copy">Copy</button></div>`;
        const c=document.getElementById('prov-copy');if(c)c.onclick=()=>{navigator.clipboard&&navigator.clipboard.writeText(d.key.text);toast('✓ copied')}});
      return;
    }
    if(act==='enable'){
      const fps=Object.keys(PROV.sel);if(!fps.length){toast('Tick the machines to set up first');return}
      const f=PROV.form||{},prof={kiosk:!!(box.querySelector('#prov-kiosk')||{}).checked,
        buddy:(box.querySelector('#prov-buddy')||{}).value||'auto',lite:true};
      const an=((box.querySelector('#prov-agent')||{}).value||f.agent||'').trim();if(an)prof.agent_name=an;
      const machines=fps.map(fp=>({fp,code:((box.querySelector(`[data-code="${CSS.escape(fp)}"]`)||{}).value||'').replace(/\D/g,''),
        name:((box.querySelector(`[data-name="${CSS.escape(fp)}"]`)||{}).value||'').trim()}));
      b.disabled=true;b.textContent='Setting up…';
      const d=await post('/api/provision/enable',{machines,profile:prof});
      const ok=(d.results||[]).filter(r=>r.ok),bad=(d.results||[]).filter(r=>!r.ok);
      PROV.sel={};
      await provPaint();
      const o=document.getElementById('prov-out');
      if(o)o.innerHTML=(ok.length?`<p class="ok">✓ ${ok.map(r=>esc(r.name)).join(', ')} ${ok.length===1?'is':'are'} set up and joining “${esc(d.pool.name)}”.</p>`:'')
        +bad.map(r=>`<p class="warn">${esc(r.name||'A machine')}: ${esc(r.error)}</p>`).join('');
      if(typeof poolPaint==='function')poolPaint();
      return;
    }
  }catch(e){toast(String(e.message||e));provPaint()}
}

/* ---------------- the waiting machine's own screen ---------------- */
/* A card in the corner, above the setup wizard: the code and the id to read out to
   whoever is at the leader. Not on a remote browser: the code is for somebody standing
   at THIS screen, and a phone looking at the machine is not that. */
function provWaitCard(v){
  let el=document.getElementById('prov-wait');
  const t=(v&&v.this)||{};
  const show=t.waiting&&!(typeof remoteClient==='function'&&remoteClient());
  if(!show){if(el)el.remove();return}
  if(!el){el=document.createElement('div');el.id='prov-wait';el.setAttribute('role','status');document.body.appendChild(el)}
  const hw=t.hw||{};
  el.innerHTML=`<b>Waiting to be set up</b>
    <p>${t.locked?`Too many wrong codes. Try again in ${Math.ceil(t.locked/60)} minutes.`
      :t.pin?`On the Bento that leads your community, open Settings → Agents → Community, choose this machine and type`
      :`This machine carries an enrolment key. On the Bento that leads your community, choose it and press Enable.`}</p>
    ${t.pin&&!t.locked?`<div class="prov-pin">${esc(t.pin.slice(0,3))} ${esc(t.pin.slice(3))}</div>`:''}
    <p class="mut">${esc(hw.board||hw.host||'This machine')} · id ${esc(t.id)}</p>
    <button class="endbtn" id="prov-here">Set it up here instead</button>`;
  el.querySelector('#prov-here').onclick=async()=>{
    await fetch('/api/provision',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({wait:false})});
    el.remove();
  };
}
async function provWaitCheck(){
  try{const v=await apiJSON('/api/provision');PROV.v=v;provWaitCard(v)}catch(e){}
}
