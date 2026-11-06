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
var DEVSCENE={on:false,d:null,el:null,t:0,busy:false,err:'',edit:false,form:null,shown:0,view:'all',allPast:false,focus:''};
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
        <button class="endbtn" data-dvs="rules">${DEVSCENE.edit?'Hide rules':'Alarm rules'}</button>
        <button class="endbtn" data-dvs="app">Open Devices</button></div></header>`;
  const alarms=devAlarmsHTML(d);
  const cards=ms.length?ms.map(m=>{
    const ml=m.machine.toLowerCase(),groups=[];
    // the nodes first, the machine's own board last, and on the board only what reads something
    m.things.forEach(t=>{if(t.group==='board'&&(t.value===undefined||t.value===null))return;
      let g=groups.find(x=>x.id===t.group);if(!g)groups.push(g={id:t.group,name:t.group==='board'?'The machine itself':t.group_name,list:[]});g.list.push(t)});
    groups.sort((a,b)=>(a.id==='board')-(b.id==='board'));
    const st=m.up===false?'down':mHot[ml]||'ok';
    return `<article class="dvs-m ${st}" aria-label="${esc(m.machine)}">
      <h2><i class="dvs-dot" aria-hidden="true"></i>${esc(m.machine)}
        <span>${m.demo?'warehouse demo · ':''}${m.up===false?'not answering':m.here?'this hub':m.live?'live':'every minute'}</span></h2>
      ${groups.map(g=>`<div class="dvs-g"><h3>${esc(g.name)}</h3>${g.list.map(t=>{
        const h=hot[ml+'|'+t.id]||'';
        return `<div class="dvs-t${h?' '+h:''}${t.onoff&&t.value?' lit':''}${t.trend?' has-tr':''}"><span>${esc(devSceneShort(t))}</span>
          ${t.trend?devSceneSpark(t):''}
          <b data-dvl="${esc(m.machine+'|'+t.id)}">${esc(devSceneVal(t))}</b>
          ${t.trend?`<small class="dvs-tr">${devSceneTrendWords(t)}</small>`:''}</div>`}).join('')}</div>`).join('')
        ||'<p class="mut">Nothing on this machine can be read yet.</p>'}
    </article>`}).join('')
    :`<p class="dvs-wait">No devices yet. Machines this hub sets up, and ESP32 boards it holds, show here. ${pInfo('Set a Raspberry Pi up from Devices, or add ESP32 boards to this hub. The warehouse demo in Devices has three zones to try.')}</p>`;
  el.innerHTML=head+devSceneStatsHTML(d.analytics||{})+alarms+(DEVSCENE.edit?devSceneRulesHTML():'')+`<div class="dvs-grid">${cards}</div>`;
  el.querySelectorAll('[data-dvs]').forEach(b=>b.onclick=()=>devSceneAct(b.dataset.dvs,b));
  if(DEVSCENE.edit)devSceneRulesWire(el);
}
/* ---- the analytics: what the floor did, not only what it reads now ----
   Asked for as "the devices screen should be super analytical". Each number carries its last
   hour (telemetry.trend: the hub's own kept readings, a minute apart) as a line with its range,
   mean and change, and the board opens on the day's numbers: machines answering, readings in,
   alarms now and in the last 24 hours by hour, which came back most, and the longest open.
   Every figure is also words, so nothing is colour alone; each mark has a tooltip. */
function devSceneNum(v,unit){
  if(v===null||v===undefined||isNaN(v))return '—';
  const a=Math.abs(v),n=a>=100||v===Math.round(v)?String(Math.round(v)):v.toFixed(1);
  return n.replace('-','−')+(unit?(unit==='°C'||unit==='%'?'':' ')+unit:'');
}
function devSceneTrendWords(t){
  const r=t.trend,d=(r.last!=null&&r.first!=null)?r.last-r.first:null;
  const arrow=d===null||Math.abs(d)<1e-9?'→':d>0?'↑':'↓';
  return `1 h: ${devSceneNum(r.min,t.unit)} to ${devSceneNum(r.max,t.unit)} · avg ${devSceneNum(r.mean,t.unit)} · ${arrow} ${d===null?'—':devSceneNum(Math.abs(d),t.unit)}`;
}
function devSceneSpark(t){
  const r=t.trend,p=r.points||[],W=96,H=22,lo=r.min,hi=r.max,span=(hi-lo)||1;
  const x=i=>(i/(p.length-1||1))*(W-2)+1,y=v=>H-2-((v-lo)/span)*(H-4);
  let path='',pen=false;
  p.forEach((v,i)=>{if(v===null){pen=false;return}path+=(pen?'L':'M')+x(i).toFixed(1)+' '+y(v).toFixed(1)+' ';pen=true});
  const li=p.map((v,i)=>v===null?-1:i).filter(i=>i>=0).pop();
  const dot=li>=0?`<circle cx="${x(li).toFixed(1)}" cy="${y(p[li]).toFixed(1)}" r="2.2"/>`:'';
  return `<svg class="dvs-spark" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img"
    aria-label="${esc(devSceneShort(t))}, last hour: ${esc(devSceneTrendWords(t))}"><title>${esc(devSceneTrendWords(t))}</title>
    <path d="${path}"/>${dot}</svg>`;
}
function devSceneStatsHTML(an){
  if(!an||an.machines===undefined)return '';
  const tile=(k,v,sub,cls)=>`<div class="dvs-k${cls?' '+cls:''}"><span>${esc(k)}</span><b>${v}</b>${sub?`<small>${sub}</small>`:''}</div>`;
  const hrs=an.by_hour||[],mx=Math.max(1,...hrs),W=240,H=40,bw=W/24;
  const bars=hrs.map((n,i)=>{const h=n?Math.max(2,(n/mx)*(H-4)):0,ago=23-i;
    return `<rect x="${(i*bw+1).toFixed(1)}" y="${(H-h).toFixed(1)}" width="${(bw-2).toFixed(1)}" height="${h.toFixed(1)}" rx="1.5"><title>${n} alarm${n===1?'':'s'} raised ${ago?ago+' h ago':'this hour'}</title></rect>`}).join('');
  return `<section class="dvs-stats" aria-label="The last 24 hours">
    ${tile('Machines answering',`${an.answering}/${an.machines}`,'',an.answering<an.machines?'bad':'')}
    ${tile('Readings in',`${an.reading}/${an.things}`,'things reporting a value','')}
    ${tile('Alarms now',String(an.alarms_now),`${an.warnings_now} warning${an.warnings_now===1?'':'s'} · ${an.acked} seen${an.pending?` · ${an.pending} building`:''}`,an.alarms_now?'bad':an.warnings_now?'warn':'')}
    ${tile('Longest open',an.active?devSceneAgo(an.longest):'—','','')}
    ${tile('Last 24 hours',`${an.raised_24h} raised`,`${an.cleared_24h} cleared · ${an.active} open`,'')}
    <div class="dvs-k dvs-hist"><span>Alarms by hour, last 24 h</span>
      <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" preserveAspectRatio="none" role="img"
        aria-label="Alarms raised per hour over the last 24 hours: ${hrs.join(', ')}">${bars}<line x1="0" y1="${H-.5}" x2="${W}" y2="${H-.5}"/></svg>
      ${(an.top||[]).length?`<small>Most often: ${an.top.slice(0,3).map(([t,n])=>`${esc(t)} (${n})`).join(' · ')}</small>`:'<small>No alarms in the last day.</small>'}</div>
  </section>`;
}
/* The alarms, as a table: what is open, then what happened today. The scene and Devices → Alarms
   draw the same rows, with data-dvs buttons the caller wires to devSceneAct. A raised alarm nobody
   has acknowledged blinks and says New; colour is the level, and the level is always also a word.
   The board repaints every few seconds, so the blink takes its phase from the clock, or every
   repaint would restart it. */
function devSceneClock(at){
  if(!at)return '—';const d=new Date(at*1000),n=new Date();
  const t=d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
  return d.toDateString()===n.toDateString()?t:d.toLocaleDateString([],{day:'numeric',month:'short'})+', '+t;
}
function devSceneSource(a){
  if(a.source==='mission')return `mission ${a.flow||''}`.trim();
  if(a.source==='machine'||a.source==='fault')return 'always on';
  if(a.source==='alarm')return a.demo?'demo rule':'your rule';
  return '';
}
function devSceneSev(a,blink){
  const lv=a.level==='warning'?'warning':'alarm';
  return `<span class="dvs-sev ${lv}${blink?' blink':''}"><i aria-hidden="true">${lv==='alarm'?'⚠':'!'}</i>${esc(DEVSCENE_LEVEL[lv])}</span>`;
}
function devSceneOpenRow(a){
  const fresh=a.state==='active'&&!a.ack,src=devSceneSource(a);
  const st=a.state==='pending'?`<span class="dvs-st wait">Building, ${devSceneAgo(a.held)} of ${devSceneAgo(a.for)}</span>`
    :a.state==='unconfirmed'?`<span class="dvs-st wait" title="This was open when Bento last stopped. It stays here until the machine says what it reads now.">Checking with ${esc(a.machine)}</span>`
    :a.ack?`<span class="dvs-st seen">Seen by ${esc(a.ack.by)}</span>`:'<span class="dvs-st new">New</span>';
  // the sentence already says a door is open; only a number has more to say
  const onoff=/\.(switch|binary_sensor|light|fan)\.|^gpio\./.test(a.item||'');
  const now=typeof a.value==='number'&&!onoff?`now ${esc(devSceneNum(a.value,a.unit))}`:'';
  const hasRule=a.source==='alarm'||a.source==='mission';
  return `<tr class="dvs-row ${esc(a.level)} ${esc(a.state)}${fresh?' fresh':''}"${fresh?` style="--ph:-${Date.now()%1200}ms"`:''}>
    <td data-l="Level">${devSceneSev(a,fresh)}</td>
    <td class="dvs-what"><b>${esc(a.text)}</b><small>${[esc(a.machine),now,esc(src)].filter(Boolean).join(' · ')}</small></td>
    <td data-l="Status">${st}</td>
    <td data-l="Raised">${esc(devSceneClock(a.since))}</td>
    <td data-l="Open for">${devSceneAgo(a.held)}</td>
    <td class="dvs-do">${a.state==='active'&&!a.ack?`<button class="endbtn" data-dvs="ack" data-id="${esc(a.id)}"${a.demo?' data-demo="1"':''}>Acknowledge</button>`:''}
      ${hasRule?`<button class="linkbtn" data-dvs="rule" data-id="${esc(a.id)}"${a.demo?' data-demo="1"':''}>Rule</button>`:''}</td></tr>`;
}
function devSceneEndedRow(a){
  const end=a.ended?`<span class="dvs-st ok"${a.why?` title="${esc(a.why)}"`:''}>Cleared ${esc(devSceneClock(a.ended))}${a.why?` · ${esc(a.why)}`:''}</span>`
    :'<span class="dvs-st past" title="Bento stopped while this was open, so nobody recorded when it ended.">Ended, time not recorded</span>';
  return `<tr class="dvs-row ended ${esc(a.level)}">
    <td data-l="Level">${devSceneSev(a,false)}</td>
    <td class="dvs-what"><b>${esc(a.text)}</b><small>${[esc(a.machine),a.ack?`seen by ${esc(a.ack.by)}`:''].filter(Boolean).join(' · ')}</small></td>
    <td data-l="Status">${end}</td>
    <td data-l="Raised">${esc(devSceneClock(a.since))}</td>
    <td data-l="Open for">${a.lasted===null||a.lasted===undefined?'—':devSceneAgo(a.lasted)}</td><td class="dvs-do"></td></tr>`;
}
function devAlarmsHTML(d){
  const al=(d.alarms||[]).slice(),past=d.history||[],view=DEVSCENE.view||'all';
  const rank=a=>a.state==='active'?(a.ack?2:0)+(a.level==='alarm'?0:1):4;
  al.sort((x,y)=>rank(x)-rank(y)||y.since-x.since);
  const tab=(v,l,n)=>`<button class="${view===v?'on':''}" data-dvs="view" data-v="${v}" aria-pressed="${view===v}">${l} <em>${n}</em></button>`;
  const open=view!=='past'?al:[],gone=view!=='open'?past:[];
  const cap=DEVSCENE.allPast?gone.length:8,shown=gone.slice(0,cap);
  const empty=!al.length&&view!=='past'?'<p class="dvs-clear">✓ Nothing open. Every machine is answering and nothing is out of range.</p>':'';
  const rows=open.map(devSceneOpenRow).join('')+shown.map(devSceneEndedRow).join('');
  return `<section class="dvs-alarms" aria-label="Alarms">
    <div class="dvs-al-head"><h2>Alarms</h2>
      <div class="dvs-tabs" role="group" aria-label="Which alarms">${tab('all','All',al.length+past.length)}${tab('open','Open',al.length)}${tab('past','Earlier today',past.length)}</div>
      <button class="linkbtn" data-dvs="rules">${DEVSCENE.edit?'Hide rules':'Alarm rules'}</button></div>
    ${empty}
    ${rows?`<div class="dvs-tw"><table class="dvs-tab"><thead><tr><th>Level</th><th>Alarm</th><th>Status</th><th>Raised</th><th>Open for</th><th></th></tr></thead><tbody aria-live="polite">${rows}</tbody></table></div>`
      :(view==='past'?'<p class="mut">Nothing earlier today.</p>':'')}
    ${gone.length>cap?`<button class="linkbtn" data-dvs="morepast">Show ${gone.length-cap} more</button>`:''}
  </section>`;
}
async function devSceneAct(act,b){
  if(act==='desk')return switchDesk(+b.dataset.n);
  if(act==='app')return openApp('devices');
  if(act==='view'){DEVSCENE.view=b.dataset.v;return devAlarmsRepaint()}
  if(act==='morepast'){DEVSCENE.allPast=true;return devAlarmsRepaint()}
  if(act==='rules'){
    if(!DEVSCENE.on)return typeof devBoardShow==='function'&&(DEVSCENE.edit=true,devBoardShow());
    DEVSCENE.edit=!DEVSCENE.edit;DEVSCENE.form=null;devScenePaint();return devSceneRulesReveal()}
  if(act==='rule'){DEVSCENE.edit=true;DEVSCENE.focus=b.dataset.id;
    const d=DEVSCENE.d||(typeof DEVAL!=='undefined'&&DEVAL.d)||{},r=(d.rule_list||[]).find(x=>x.id===b.dataset.id&&!!x.demo===!!b.dataset.demo);
    if(r&&r.editable)devSceneRuleEdit(r);
    if(!DEVSCENE.on)return typeof devBoardShow==='function'&&devBoardShow();
    devScenePaint();return devSceneRulesReveal(r&&r.editable)}
  if(act==='ack'){b.disabled=true;
    try{const r=await fetch('/api/devices/alarms/ack',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:b.dataset.id,demo:!!b.dataset.demo})});
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
/* Everything that can raise an alarm, in one table: your rules, the demo's (its own hub keeps
   them, the server passes the change on), and what missions that are on watch for, which belong
   to the mission. A row says what it reads now, and the form both adds and edits. */
function devSceneRuleEdit(r){
  DEVSCENE.form={machine:r.machine,item:r.item||'',when:r.when,value:r.value===null||r.value===undefined?'':String(r.value),for:String(r.for||0),level:r.level,editing:{id:r.id,demo:!!r.demo}};
}
function devSceneRulesHTML(){
  const d=DEVSCENE.d||{},rules=d.rule_list||[],ms=d.machines||[],f=DEVSCENE.form||(DEVSCENE.form={machine:(ms[0]||{}).machine||'',item:'',when:'above',value:'',for:'0',level:'alarm'});
  const m=ms.find(x=>x.machine===f.machine)||ms[0]||{things:[]};
  const t=m.things.find(x=>x.id===f.item)||m.things[0];
  if(t&&!f.item)f.item=t.id;
  const whens=t&&t.onoff?['on','off','offline']:['above','below','offline'];
  if(whens.indexOf(f.when)<0)f.when=whens[0];
  const opt=(v,l,sel)=>`<option value="${esc(v)}"${sel?' selected':''}>${esc(l)}</option>`;
  const nowWord={active:'Raised',pending:'Building',unconfirmed:'Checking',clear:'Clear'};
  const row=r=>{const editing=f.editing&&f.editing.id===r.id&&f.editing.demo===!!r.demo;
    return `<tr class="${DEVSCENE.focus===r.id?'focus':''}${editing?' editing':''}">
    <td data-l="Level">${devSceneSev(r,false)}</td>
    <td class="dvs-what"><b>${esc(r.text)}</b><small>${esc(r.machine)}${r.for?` · holds for ${devSceneAgo(r.for)}`:''}</small></td>
    <td data-l="From">${esc(r.source==='mission'?`Mission ${r.flow||''}`:r.demo?'Warehouse demo':'You')}</td>
    <td data-l="Now"><span class="dvs-st ${r.now==='active'?'new':r.now==='clear'?'ok':'wait'}">${esc(nowWord[r.now]||r.now)}</span></td>
    <td class="dvs-do">${r.editable?`<button class="linkbtn" data-dvr="edit" data-id="${esc(r.id)}"${r.demo?' data-demo="1"':''}>Edit</button>
      <button class="linkbtn" data-dvr="del" data-id="${esc(r.id)}"${r.demo?' data-demo="1"':''}>Remove</button>`
      :'<button class="linkbtn" data-dvr="mission">In Missions</button>'}</td></tr>`};
  return `<section class="dvs-rules" aria-label="Alarm rules">
    <h2>Alarm rules ${pInfo('An alarm shows while its condition holds and clears by itself when it stops. Acknowledge only marks that you saw it. A mission that is on watches its own rules, and you change those in the mission.')}</h2>
    ${rules.length?`<div class="dvs-tw"><table class="dvs-tab"><thead><tr><th>Level</th><th>Condition</th><th>From</th><th>Now</th><th></th></tr></thead><tbody>${rules.map(row).join('')}</tbody></table></div>`
      :'<p class="mut">No rules yet. Add the first one below.</p>'}
    <p class="mut dvs-always">Always on: a machine that stops answering, and a sensor with no reading.</p>
    ${ms.length?`<h3>${f.editing?'Edit this rule':'Add a rule'}</h3><div class="dvs-form">
      <select data-f="machine" aria-label="Machine">${ms.map(x=>opt(x.machine,x.machine+(x.demo?' (demo)':''),x.machine===m.machine)).join('')}</select>
      ${f.when!=='offline'?`<select data-f="item" aria-label="Thing">${m.things.map(x=>opt(x.id,x.name,t&&x.id===t.id)).join('')}</select>`:''}
      <select data-f="when" aria-label="Condition">${whens.map(w=>opt(w,devSceneWhen(w,t),w===f.when)).join('')}</select>
      ${f.when==='above'||f.when==='below'?`<input data-f="value" inputmode="decimal" value="${esc(f.value)}" placeholder="value" aria-label="Value">${t&&t.unit?`<span class="mut">${esc(t.unit)}</span>`:''}`:''}
      <label>for <input data-f="for" inputmode="numeric" value="${esc(f.for)}" aria-label="Seconds it must hold"> s</label>
      <select data-f="level" aria-label="Level">${opt('alarm','Alarm',f.level==='alarm')}${opt('warning','Warning',f.level==='warning')}</select>
      <button class="wiz-next" data-dvr="add">${f.editing?'Save rule':'Add rule'}</button>
      ${f.editing?'<button class="linkbtn" data-dvr="cancel">Cancel</button>':''}</div>`:''}</section>`;
}
function devSceneRulesWire(el){
  el.querySelectorAll('[data-f]').forEach(x=>x.onchange=()=>{const f=DEVSCENE.form;f[x.dataset.f]=x.value;
    if(x.dataset.f==='machine')f.item='';if(x.dataset.f==='machine'||x.dataset.f==='item'||x.dataset.f==='when')devScenePaint()});
  el.querySelectorAll('[data-dvr]').forEach(b=>b.onclick=()=>{
    const d=DEVSCENE.d||{},act=b.dataset.dvr,isDemo=!!b.dataset.demo;
    if(act==='mission')return openApp('fabric');
    if(act==='cancel'){DEVSCENE.form=null;return devScenePaint()}
    if(act==='edit'){const r=(d.rule_list||[]).find(x=>x.id===b.dataset.id&&!!x.demo===isDemo);if(r)devSceneRuleEdit(r);return devScenePaint()}
    const own=(d.rules||[]).slice(),demo=(d.demo_rules||[]).slice(),touched={};
    const drop=(id,inDemo)=>{const l=inDemo?demo:own,i=l.findIndex(x=>x.id===id);if(i>=0){l.splice(i,1);touched[inDemo?'demo':'own']=true}};
    if(act==='del')drop(b.dataset.id,isDemo);
    else{el.querySelectorAll('[data-f]').forEach(x=>DEVSCENE.form[x.dataset.f]=x.value);
      const f=DEVSCENE.form,r={machine:f.machine,when:f.when,for:+f.for||0,level:f.level},toDemo=!!((d.machines||[]).find(x=>x.machine===f.machine)||{}).demo;
      if(f.when!=='offline')r.item=f.item;
      if(f.when==='above'||f.when==='below'){if(f.value===''||isNaN(+f.value))return toast('Give it a number to compare with',{kind:'warn'});r.value=+f.value}
      if(f.editing)drop(f.editing.id,f.editing.demo);
      (toDemo?demo:own).push(r);touched[toDemo?'demo':'own']=true}
    devSceneRulesSave(own,demo,touched)});
}
async function devSceneRulesSave(own,demo,touched){
  let ok=true;
  for(const k of Object.keys(touched)){
    try{const r=await fetch('/api/devices/alarms',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({alarms:k==='demo'?demo:own,demo:k==='demo'})});
      const d=await r.json();if(!r.ok)throw new Error(d.error||'Those rules could not be saved');
      if((d.dropped||[]).length)toast('Not kept: '+d.dropped.join('; '),{kind:'warn'})}
    catch(e){ok=false;toast(String(e.message||e),{kind:'err'})}
  }
  if(ok){DEVSCENE.form=null;DEVSCENE.focus=''}
  devSceneLoad();
}
/* The rules open below the table: bring them, or the form when a rule was picked, into view. */
function devSceneRulesReveal(form){
  const el=DEVSCENE.el,x=el&&DEVSCENE.edit&&el.querySelector(form?'.dvs-form':'.dvs-rules');
  if(x)x.scrollIntoView({block:form?'center':'start'});
}
/* The alarm table's filter is shared: repaint whichever of the two surfaces is showing. */
function devAlarmsRepaint(){
  if(DEVSCENE.on)devScenePaint();
  if(typeof devAlarmsPaint==='function'&&document.querySelector('.dev-alarms'))devAlarmsPaint();
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
