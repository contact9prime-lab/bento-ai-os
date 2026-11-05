/* ================= the Devices scene: the floor, live, with its alarms =================
   Asked for as "when we are in the device mode the device screen should be there on the hub, so I
   can see all the devices in real time along with alarms … like a device hub instead of the town,
   and an easier way of switching between the device scene and the town, so the desktops could be
   used for that". A scene like the Town, chosen per desktop (01b immersiveSceneNow): on a hub with
   devices one desktop shows the Town and another this board, and the pager switches between them.

   What it draws is the server's one answer, /api/devices/board (devboard.py): every machine this
   hub set up for you and this hub's own boards, each thing as last heard, and the alarms now. The
   values move as device_live arrives (devSceneLive); an alarm raised or cleared refetches. It is
   words and numbers in the desktop layer, so it costs what a page of text costs: no canvas, no
   frame loop, a 4 s refresh that stops while hidden or covered. Nothing here switches anything:
   a switch is device_set, asked of a person, from Devices or a chat.

   Faces: GUI this. TUI: `bento network board` prints the same answer. SUI: the same page, in the
   BACKGROUND layer like every scene; native windows sit above it as they sit above the Town. */
var DEVSCENE={on:false,d:null,el:null,t:0,busy:false,err:'',edit:false,form:null,shown:0};
var DEVSCENE_LEVEL={alarm:'Alarm',warning:'Warning'};

function devSceneStart(){
  if(DEVSCENE.on)return;
  DEVSCENE.on=true;
  const desk=document.getElementById('desktop'),home=document.getElementById('home');
  if(!desk)return;
  let el=document.getElementById('devscene');
  if(!el){el=document.createElement('div');el.id='devscene';el.className='dvs';el.setAttribute('role','region');
    el.setAttribute('aria-label','Devices, live');desk.insertBefore(el,home?home.nextSibling:null)}
  DEVSCENE.el=el;el.hidden=false;
  if(!el.firstChild)el.innerHTML='<p class="dvs-wait">Reading your devices…</p>';
  devSceneLoad();
  clearInterval(DEVSCENE.t);
  DEVSCENE.t=setInterval(()=>{if(!document.hidden&&!document.body.classList.contains('has-win'))devSceneLoad()},4000);
}
function devSceneStop(){
  if(!DEVSCENE.on)return;
  DEVSCENE.on=false;clearInterval(DEVSCENE.t);DEVSCENE.t=0;
  const el=document.getElementById('devscene');if(el)el.hidden=true;
}
async function devSceneLoad(){
  if(!DEVSCENE.on||DEVSCENE.busy)return;
  DEVSCENE.busy=true;
  try{const r=await fetch('/api/devices/board');const d=await r.json();
    if(!r.ok)throw new Error(d.error||'The board could not be read');DEVSCENE.d=d;DEVSCENE.err=''}
  catch(e){DEVSCENE.err=String(e.message||e)}
  DEVSCENE.busy=false;
  // a repaint would take the caret out of the alarm form
  const a=document.activeElement;if(a&&DEVSCENE.el&&DEVSCENE.el.contains(a)&&/INPUT|SELECT/.test(a.tagName))return;
  devScenePaint();
}

function devSceneVal(t){
  const v=t.value;if(v===undefined||v===null)return t.kind==='sensor'?'no reading':'—';
  if(t.onoff){
    if(t.kind==='gpio')return v?'high':'low';
    if(t.kind==='binary_sensor'&&/door/i.test(t.name))return v?'open':'shut';
    if(t.kind==='binary_sensor'&&/motion/i.test(t.name))return v?'moving':'still';
    return v?'on':'off';
  }
  if(typeof v==='number'&&t.unit==='s'){const h=Math.floor(v/3600);return h>=24?`${Math.floor(h/24)} d ${h%24} h`:`${h} h ${Math.floor(v%3600/60)} min`}
  if(typeof v==='number'&&t.unit==='MB'&&v>=1024)return (v/1024).toFixed(1)+' GB';
  if(typeof v==='number'){const n=Math.abs(v)>=100||v===Math.round(v)?String(Math.round(v)):v.toFixed(1);
    return n.replace('-','−')+(t.unit?(t.unit==='°C'||t.unit==='%'?'':' ')+t.unit:'')}
  return String(v);
}
function devSceneAgo(s){
  s=Math.max(0,Math.round(s));
  return s<60?`${s} s`:s<3600?`${Math.floor(s/60)} min`:`${Math.floor(s/3600)} h ${Math.floor(s%3600/60)} min`;
}
/* The thing's name without its node's ("Cold room B: Compressor" under Cold room B). */
function devSceneShort(t){const p=(t.group_name||'')+': ';return t.name.indexOf(p)===0?t.name.slice(p.length):t.name}

/* The desktop that shows another scene, for the button that goes there. */
function devSceneOther(){
  const n=typeof DESKS!=='undefined'?DESKS:1,cur=deskNow();
  for(let i=1;i<=n;i++)if(i!==cur&&immersiveSceneOf(i)!=='devices')return i;
  return 0;
}

function devScenePaint(){
  const el=DEVSCENE.el;if(!el||!DEVSCENE.on)return;
  const d=DEVSCENE.d;
  if(!d){el.innerHTML=`<p class="dvs-wait">${esc(DEVSCENE.err||'Reading your devices…')}</p>`;return}
  const ms=d.machines||[],al=d.alarms||[];
  const raised=al.filter(a=>a.state==='active'),loud=raised.filter(a=>a.level==='alarm'&&!a.ack);
  const things=ms.reduce((n,m)=>n+m.things.length,0);
  const other=devSceneOther(),otherName=other?(IMMERSIVE_NAMES[immersiveSceneOf(other)]||'the other scene'):'';
  const hot={};al.forEach(a=>{if(a.item)hot[a.machine.toLowerCase()+'|'+a.item]=a.state==='active'?a.level:'pending'});
  const mHot={};al.forEach(a=>{if(a.state==='active'){const k=a.machine.toLowerCase();mHot[k]=mHot[k]==='alarm'?'alarm':a.level}});
  const head=`<header class="dvs-head">
      <div><h1>Devices</h1><p class="dvs-sum">${ms.length} machine${ms.length===1?'':'s'} · ${things} thing${things===1?'':'s'} ·
        <b class="${loud.length?'bad':raised.length?'warn':'ok'}">${raised.length?`${raised.length} alarm${raised.length===1?'':'s'}`:'all clear'}</b>
        ${DEVSCENE.err?`<span class="bad"> · ${esc(DEVSCENE.err)}</span>`:''}</p></div>
      <div class="dvs-acts">
        ${other?`<button class="endbtn" data-dvs="desk" data-n="${other}" title="Desktop ${other}">⇄ ${esc(otherName)}</button>`:''}
        <button class="endbtn" data-dvs="rules">${DEVSCENE.edit?'Done':'Alarms…'}</button>
        <button class="endbtn" data-dvs="app">Open Devices</button></div></header>`;
  const alarms=devAlarmsHTML(al,loud.length);
  const cards=ms.length?ms.map(m=>{
    const ml=m.machine.toLowerCase(),groups=[];
    // the nodes first, the machine's own board last, and on the board only what reads something
    m.things.forEach(t=>{if(t.group==='board'&&(t.value===undefined||t.value===null))return;
      let g=groups.find(x=>x.id===t.group);if(!g)groups.push(g={id:t.group,name:t.group==='board'?'The machine itself':t.group_name,list:[]});g.list.push(t)});
    groups.sort((a,b)=>(a.id==='board')-(b.id==='board'));
    const st=m.up===false?'down':mHot[ml]||'ok';
    return `<article class="dvs-m ${st}" aria-label="${esc(m.machine)}">
      <h2><i class="dvs-dot" aria-hidden="true"></i>${esc(m.machine)}
        <span>${m.up===false?'not answering':m.here?'this hub':m.live?'live':'every minute'}</span></h2>
      ${groups.map(g=>`<div class="dvs-g"><h3>${esc(g.name)}</h3>${g.list.map(t=>{
        const h=hot[ml+'|'+t.id]||'';
        return `<div class="dvs-t${h?' '+h:''}${t.onoff&&t.value?' lit':''}"><span>${esc(devSceneShort(t))}</span>
          <b data-dvl="${esc(m.machine+'|'+t.id)}">${esc(devSceneVal(t))}</b></div>`}).join('')}</div>`).join('')
        ||'<p class="mut">Nothing on this machine can be read yet.</p>'}
    </article>`}).join('')
    :`<p class="dvs-wait">No devices yet. Machines this hub sets up, and ESP32 boards it holds, show here. ${pInfo('Set a Raspberry Pi up from Devices, or add ESP32 boards to this hub. The warehouse demo in Devices has three zones to try.')}</p>`;
  el.innerHTML=head+(DEVSCENE.edit?devSceneRulesHTML():'')+alarms+`<div class="dvs-grid">${cards}</div>`;
  el.querySelectorAll('[data-dvs]').forEach(b=>b.onclick=()=>devSceneAct(b.dataset.dvs,b));
  if(DEVSCENE.edit)devSceneRulesWire(el);
}
/* The alarms, as a list: the scene and Devices → Alarms draw the same rows. Ack buttons carry
   data-dvs="ack" and data-id; the caller wires them to devSceneAct. */
function devAlarmsHTML(al,loud){
  return `<section class="dvs-alarms${loud?' loud':''}" aria-label="Alarms" aria-live="polite">
      ${al.length?al.map(a=>`<div class="dvs-al ${esc(a.level)} ${esc(a.state)}${a.ack?' acked':''}">
        <span class="dvs-al-i" aria-hidden="true">${a.state!=='active'?'◔':a.level==='alarm'?'⚠':'!'}</span>
        <div class="dvs-al-t"><b>${esc(a.text)}</b>
          <span>${esc(a.machine)} · ${a.state==='active'?`${esc(DEVSCENE_LEVEL[a.level]||a.level)} for ${devSceneAgo(a.held)}`
            :`holding ${devSceneAgo(a.held)} of ${devSceneAgo(a.for)}`}${a.flow?` · mission ${esc(a.flow)} watches this`:''}
            ${a.ack?` · seen by ${esc(a.ack.by)}`:''}</span></div>
        ${a.state==='active'&&!a.ack?`<button class="endbtn" data-dvs="ack" data-id="${esc(a.id)}">Acknowledge</button>`:''}</div>`).join('')
        :'<p class="dvs-clear">✓ No alarms. Every machine is answering and nothing is out of range.</p>'}</section>`;
}
async function devSceneAct(act,b){
  if(act==='desk')return switchDesk(+b.dataset.n);
  if(act==='app')return openApp('devices');
  if(act==='rules'){DEVSCENE.edit=!DEVSCENE.edit;return devScenePaint()}
  if(act==='ack'){b.disabled=true;
    try{const r=await fetch('/api/devices/alarms/ack',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:b.dataset.id})});
      const d=await r.json();if(!r.ok)toast(d.error||'That alarm could not be acknowledged',{kind:'err'})}
    catch(e){toast(String(e.message||e),{kind:'err'})}
    if(typeof devAlarmsLoad==='function')devAlarmsLoad();
    return devSceneLoad()}
}

/* ---- the person's alarm rules (devboard.clean_rule), edited in place ---- */
var DEVSCENE_WHEN={above:'is above',below:'is below',on:'is on',off:'is off',offline:'stops answering'};
/* A door is open or shut, a pin high or low, the rest on or off: the words a person says. */
function devSceneWhen(w,t){
  if(t&&t.onoff&&(w==='on'||w==='off')){
    if(/door/i.test(t.name))return w==='on'?'is open':'is shut';
    if(t.kind==='gpio')return w==='on'?'is high':'is low';
  }
  return DEVSCENE_WHEN[w]||w;
}
function devSceneRuleWords(r){
  const d=DEVSCENE.d||{},m=(d.machines||[]).find(x=>x.machine.toLowerCase()===String(r.machine).toLowerCase());
  const t=m&&m.things.find(x=>x.id===r.item);
  const what=r.when==='offline'?r.machine:(t?t.name:r.item)+' on '+r.machine;
  return `${what} ${devSceneWhen(r.when,t)}${r.value!==undefined&&(r.when==='above'||r.when==='below')?' '+r.value+(t&&t.unit?' '+t.unit:''):''}${r.for?` for ${devSceneAgo(r.for)}`:''}`;
}
function devSceneRulesHTML(){
  const d=DEVSCENE.d||{},rules=d.rules||[],ms=d.machines||[],f=DEVSCENE.form||(DEVSCENE.form={machine:(ms[0]||{}).machine||'',item:'',when:'above',value:'',for:'0',level:'alarm'});
  const m=ms.find(x=>x.machine===f.machine)||ms[0]||{things:[]};
  const t=m.things.find(x=>x.id===f.item)||m.things[0];
  if(t&&!f.item)f.item=t.id;
  const whens=f.when==='offline'?['offline']:t&&t.onoff?['on','off','offline']:['above','below','offline'];
  if(whens.indexOf(f.when)<0)f.when=whens[0];
  const opt=(v,l,sel)=>`<option value="${esc(v)}"${sel?' selected':''}>${esc(l)}</option>`;
  return `<section class="dvs-rules" aria-label="Your alarms">
    <h2>Your alarms ${pInfo('An alarm shows here while its condition holds, and clears by itself when it stops. Acknowledge only marks that you saw it. Missions that are on watch their own rules, and those show too.')}</h2>
    ${rules.length?`<ul>${rules.map((r,i)=>`<li><span class="dvs-lv ${esc(r.level)}">${esc(DEVSCENE_LEVEL[r.level]||r.level)}</span>
      <span>${esc(devSceneRuleWords(r))}</span><button class="linkbtn" data-dvr="del" data-i="${i}">Remove</button></li>`).join('')}</ul>`
      :'<p class="mut">No alarms of your own yet.</p>'}
    ${ms.length?`<div class="dvs-form">
      <select data-f="machine" aria-label="Machine">${ms.map(x=>opt(x.machine,x.machine,x.machine===m.machine)).join('')}</select>
      ${f.when!=='offline'?`<select data-f="item" aria-label="Thing">${m.things.map(x=>opt(x.id,x.name,t&&x.id===t.id)).join('')}</select>`:''}
      <select data-f="when" aria-label="Condition">${whens.map(w=>opt(w,devSceneWhen(w,t),w===f.when)).join('')}</select>
      ${f.when==='above'||f.when==='below'?`<input data-f="value" inputmode="decimal" value="${esc(f.value)}" placeholder="value" aria-label="Value">`:''}
      <label>for <input data-f="for" inputmode="numeric" value="${esc(f.for)}" aria-label="Seconds it must hold"> s</label>
      <select data-f="level" aria-label="Level">${opt('alarm','Alarm',f.level==='alarm')}${opt('warning','Warning',f.level==='warning')}</select>
      <button class="wiz-next" data-dvr="add">Add alarm</button></div>`:''}</section>`;
}
function devSceneRulesWire(el){
  el.querySelectorAll('[data-f]').forEach(x=>x.onchange=()=>{const f=DEVSCENE.form;f[x.dataset.f]=x.value;
    if(x.dataset.f==='machine')f.item='';if(x.dataset.f==='machine'||x.dataset.f==='item'||x.dataset.f==='when')devScenePaint()});
  el.querySelectorAll('[data-dvr]').forEach(b=>b.onclick=()=>{
    const rules=((DEVSCENE.d||{}).rules||[]).slice();
    if(b.dataset.dvr==='del')rules.splice(+b.dataset.i,1);
    else{el.querySelectorAll('[data-f]').forEach(x=>DEVSCENE.form[x.dataset.f]=x.value);
      const f=DEVSCENE.form,r={machine:f.machine,when:f.when,for:+f.for||0,level:f.level};
      if(f.when!=='offline')r.item=f.item;
      if(f.when==='above'||f.when==='below'){if(f.value===''||isNaN(+f.value))return toast('Give it a number to compare with',{kind:'warn'});r.value=+f.value}
      rules.push(r)}
    devSceneRulesSave(rules)});
}
async function devSceneRulesSave(rules){
  try{const r=await fetch('/api/devices/alarms',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({alarms:rules})});
    const d=await r.json();if(!r.ok)throw new Error(d.error||'Those alarms could not be saved');
    if((d.dropped||[]).length)toast('Not kept: '+d.dropped.join('; '),{kind:'warn'});
    if(DEVSCENE.d)DEVSCENE.d.rules=d.alarms}
  catch(e){toast(String(e.message||e),{kind:'err'})}
  devSceneLoad();
}

/* A value changed (device_live): the number moves in place, and the board is read again soon
   after, so an alarm it raised shows without waiting for the next refresh. */
function devSceneLive(ev){
  if(!DEVSCENE.on||!DEVSCENE.d)return;
  const m=(DEVSCENE.d.machines||[]).find(x=>x.machine===ev.machine);
  (ev.events||[]).forEach(e=>{const t=m&&m.things.find(x=>x.id===e.item);if(!t)return;
    t.value=e.value;t.at=e.at;
    document.querySelectorAll(`#devscene [data-dvl="${CSS.escape(ev.machine+'|'+e.item)}"]`).forEach(b=>{
      b.textContent=devSceneVal(t);const row=b.parentNode;row.classList.toggle('lit',!!(t.onoff&&t.value));
      row.classList.remove('dvs-blink');void row.offsetWidth;row.classList.add('dvs-blink')})});
  clearTimeout(DEVSCENE.soon);DEVSCENE.soon=setTimeout(devSceneLoad,900);
}
/* An alarm raised, cleared or acknowledged (server._alarms_judge). Off this scene a raised alarm
   is a toast with the way to the board: the desktop that shows it, or the Devices app. */
function devSceneAlarm(ev){
  if(DEVSCENE.on)devSceneLoad();
  const a=ev.alarm||{};
  if(ev.phase!=='raised')return;
  const seen=DEVSCENE.on&&!document.body.classList.contains('has-win');
  if(seen||a.level!=='alarm')return;
  const n=typeof deskShowing==='function'?deskShowing('devices'):0;
  toast(`⚠ ${a.machine}: ${a.text}`,{kind:'err',label:'See devices',ms:12000,go:()=>n?switchDesk(n):openApp('devices')});
}
// first paint: 01b ran before this file existed, so the scene starts itself (as 01c and 01g do)
if(typeof IMMERSIVE!=='undefined'&&IMMERSIVE.on&&immersiveSceneNow()==='devices')setTimeout(devSceneStart,0);
