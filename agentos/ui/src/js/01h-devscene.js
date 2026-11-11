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
var DEVSCENE={on:false,d:null,el:null,t:0,busy:false,err:'',page:'board',rf:'all',rq:'',confirm:'',form:null,shown:0,view:'all',allPast:false,focus:''};
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
  devChatMount();
  if(!el.firstChild)el.innerHTML='<p class="dvs-wait">Reading your devices…</p>';
  devSceneLoad();
  clearInterval(DEVSCENE.t);
  DEVSCENE.t=setInterval(()=>{if(!document.hidden&&!document.body.classList.contains('has-win'))devSceneLoad()},4000);
}
function devSceneStop(){
  if(!DEVSCENE.on)return;
  DEVSCENE.on=false;clearInterval(DEVSCENE.t);DEVSCENE.t=0;devHistClose();
  const el=document.getElementById('devscene');if(el)el.hidden=true;
  // leaving the scene gives the bar back: answers kept for the panel have nowhere to stay
  const wrap=document.getElementById('omnicards');
  if(wrap)[...wrap.children].forEach(c=>{if(c.dataset.done&&c._close)c._close()});
  const bar=document.getElementById('omnibar');if(bar)bar.classList.remove('dvc-news');
}

/* The chat folds to the top right, so the board has the whole screen under it. Asked for as "chat
   can sit there on the right top but the screen below can be used for the devices, and once it opens
   it shows a decent animation to open up the right panel". It is the prompt bar and its answer cards,
   the same turns as anywhere, with a panel behind them that slides in while the board makes room.
   Folded is the default, and the choice is per browser. Pressing the bar, typing, a hotkey or a new
   answer opens it; only the button or Esc on an empty bar folds it, so a turn never hides itself.
   While it's folded an answer lights a dot on the button, and an approval floats on its own (the
   hidden card fails approvalShown). On a phone or a narrow window there's no room for a panel, so the
   bar stays under the board. TUI: not applicable, `bento chat` already is the whole screen. SUI: the
   same page, nothing here touches the compositor. */
var DEVCHAT={open:false,read:false};
function devChatWide(){return !!DEVSCENE.on&&innerWidth>900&&!document.body.classList.contains('dev-mobile')}
function devChatKeeps(){return devChatWide()}
function devChatMount(){
  if(!DEVCHAT.read){DEVCHAT.read=true;
    try{DEVCHAT.open=localStorage.getItem('devscene.chat')==='open'}catch(e){}}
  let p=document.getElementById('devchat');
  if(!p){const bar=document.getElementById('omnicards');if(!bar)return;
    p=document.createElement('aside');p.id='devchat';
    p.innerHTML='<p class="dvc-hint">Ask about a machine, an alarm or a reading. Answers stay here until you close them.</p>';
    bar.parentNode.insertBefore(p,bar)}
  devChatPaint();
}
function devChatPaint(){
  document.body.classList.toggle('dvc-open',DEVCHAT.open);
  const b=document.getElementById('omni-fold');if(!b)return;
  const say=DEVCHAT.open?'Fold the chat panel':'Open the chat panel';
  b.setAttribute('aria-expanded',DEVCHAT.open?'true':'false');b.setAttribute('aria-label',say);b.title=say;
  if(DEVCHAT.open)document.getElementById('omnibar').classList.remove('dvc-news');
}
function devChatSet(open){
  DEVCHAT.open=open;
  try{localStorage.setItem('devscene.chat',open?'open':'fold')}catch(e){}
  devChatPaint();
}
function devChatOpen(){if(devChatWide()&&!DEVCHAT.open)devChatSet(true)}
function devChatFold(){
  if(!devChatWide()||!DEVCHAT.open)return;
  devChatSet(false);
  // a launcher left open or a caret in the bar would sit in the small pill
  if(typeof omniPop==='function'&&OMNI.pop)omniPop(false);
  const inp=document.getElementById('omni-in');if(inp&&document.activeElement===inp)inp.blur();
}
function devChatToggle(){
  if(DEVCHAT.open){devChatFold();return}
  devChatOpen();
  const inp=document.getElementById('omni-in');if(inp)inp.focus();
}
function devChatNews(){
  if(devChatWide()&&!DEVCHAT.open)document.getElementById('omnibar').classList.add('dvc-news');
}
async function devSceneLoad(){
  if(!DEVSCENE.on||DEVSCENE.busy)return;
  DEVSCENE.busy=true;
  try{const r=await fetch('/api/devices/board');const d=await r.json();
    if(!r.ok)throw new Error(d.error||'The board could not be read');DEVSCENE.d=d;DEVSCENE.err=''}
  catch(e){DEVSCENE.err=String(e.message||e)}
  DEVSCENE.busy=false;
  // a repaint would take the caret out of the alarm form
  const a=document.activeElement;if(a&&DEVSCENE.el&&DEVSCENE.el.contains(a)&&/INPUT|SELECT|TEXTAREA/.test(a.tagName))return;
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
  const ms=d.machines||[],al=d.alarms||[],page=DEVSCENE.page==='rules'?'rules':'board';
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
        <button class="endbtn" data-dvs="app">Open Devices</button></div>
      <div class="seg dvs-pages" role="tablist" aria-label="Show">
        <button role="tab" class="${page==='board'?'on':''}" aria-selected="${page==='board'}" data-dvs="page" data-v="board">Board</button>
        <button role="tab" class="${page==='rules'?'on':''}" aria-selected="${page==='rules'}" data-dvs="page" data-v="rules">Alarm rules <em>${(d.rule_list||[]).length}</em></button></div></header>`;
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
        return `<button type="button" class="dvs-t${h?' '+h:''}${t.onoff&&t.value?' lit':''}${t.trend?' has-tr':''}" data-dvs="hist"
          data-m="${esc(m.machine)}" data-i="${esc(t.id)}"${m.demo?' data-demo="1"':''} title="Its history, and alarm rules for it"><span>${esc(devSceneShort(t))}</span>
          ${t.trend?devSceneSpark(t):''}
          <b data-dvl="${esc(m.machine+'|'+t.id)}">${esc(devSceneVal(t))}</b>
          ${t.trend?`<small class="dvs-tr">${devSceneTrendWords(t)}</small>`:''}</button>`}).join('')}</div>`).join('')
        ||'<p class="mut">Nothing on this machine can be read yet.</p>'}
    </article>`}).join('')
    :`<p class="dvs-wait">No devices yet. Machines this hub sets up, and ESP32 boards it holds, show here. ${pInfo('Set a Raspberry Pi up from Devices, or add ESP32 boards to this hub. The warehouse demo in Devices has three zones to try.')}</p>`;
  el.innerHTML=head+(page==='rules'?devRulesHTML(d)
    :devSceneStatsHTML(d.analytics||{})+alarms+`<div class="dvs-grid">${cards}</div>`);
  el.querySelectorAll('[data-dvs]').forEach(b=>b.onclick=()=>devSceneAct(b.dataset.dvs,b));
  if(page==='rules')devRulesWire(el,devScenePaint,devSceneLoad);
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
    <td class="dvs-what"><b>${esc(a.label||a.text)}</b><small>${[a.label?esc(a.text):'',esc(a.machine),now,esc(src)].filter(Boolean).join(' · ')}</small>
      ${a.note?`<small class="dvs-note">What to do: ${esc(a.note)}</small>`:''}</td>
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
      <button class="linkbtn" data-dvs="rules">Alarm rules</button></div>
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
  if(act==='page'){DEVSCENE.page=b.dataset.v;DEVSCENE.el&&(DEVSCENE.el.scrollTop=0);return devScenePaint()}
  if(act==='rules')return devRulesShow();
  if(act==='rule'){DEVSCENE.focus=b.dataset.id;
    const d=devRulesBoard()||{},r=(d.rule_list||[]).find(x=>x.id===b.dataset.id&&!!x.demo===!!b.dataset.demo);
    if(r&&r.editable)devSceneRuleEdit(r);
    return devRulesShow()}
  if(act==='hist')return devHistOpen(b.dataset.m,b.dataset.i,!!b.dataset.demo);
  if(act==='ack'){b.disabled=true;
    try{const r=await fetch('/api/devices/alarms/ack',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:b.dataset.id,demo:!!b.dataset.demo})});
      const d=await r.json();if(!r.ok)toast(d.error||'That alarm could not be acknowledged',{kind:'err'})}
    catch(e){toast(String(e.message||e),{kind:'err'})}
    if(typeof devAlarmsLoad==='function')devAlarmsLoad();
    return devSceneLoad()}
}

/* ---- Alarm rules: a page of their own (the Rules view of the scene, and a section in Devices) ----
   Reported as "edit rule comes in but it is not very elaborate. There should be a rule section for
   the alarms". It was a small table opened under the alarms, with a one-line form. Now every rule
   is a card grouped by machine, saying in words what it watches, what that thing reads now, whether
   it is raised, and how often it went off in the last day; the editor is a sentence you fill in
   (machine, thing, condition, value, how long it must hold, alarm or warning), with a name and a
   note of what to do, and a preview that says what the rule would do with the reading right now.
   Rules can be paused without losing them. The rules themselves are devboard.clean_rule's closed
   set; name, note and paused are words beside the condition, so they never change a rule's id.
   Faces: GUI this, drawn by both hosts with the same functions. TUI: `bento network alarms`. SUI:
   the same page. */
var DEVSCENE_WHEN={above:'is above',below:'is below',on:'is on',off:'is off',offline:'stops answering'};
var DEVR_FILTERS=[['all','All'],['raised','Raised now'],['yours','Yours'],['demo','Demo'],['missions','Missions'],['paused','Paused']];
/* A door is open or shut, a pin high or low, the rest on or off: the words a person says. */
function devSceneWhen(w,t){
  if(t&&t.onoff&&(w==='on'||w==='off')){
    if(/door/i.test(t.name))return w==='on'?'is open':'is shut';
    if(/motion/i.test(t.name))return w==='on'?'sees movement':'is still';
    if(t.kind==='gpio')return w==='on'?'is high':'is low';
  }
  return DEVSCENE_WHEN[w]||w;
}
function devRulesBoard(){return DEVSCENE.on?DEVSCENE.d:(typeof DEVAL!=='undefined'&&DEVAL.d)||DEVSCENE.d}
function devRuleMachine(d,name,demo){return (d.machines||[]).find(x=>x.machine===name&&(demo===undefined||!!x.demo===!!demo))}
function devRuleThing(d,r){const m=devRuleMachine(d,r.machine,r.demo);return m&&r.item?m.things.find(x=>x.id===r.item):null}
/* the form, from a rule (to edit it), from a thing (to watch it), or blank */
function devSceneRuleEdit(r,copy){
  const f=r.for||0,min=f&&f%60===0;
  DEVSCENE.form={machine:r.machine,demo:!!r.demo,item:r.item||'',when:r.when,value:r.value===null||r.value===undefined?'':String(r.value),
    for:String(min?f/60:f),forUnit:min?'min':'s',level:r.level||'alarm',name:copy?'':(r.label||''),note:r.note||'',paused:!copy&&!!r.paused,
    editing:copy?null:{id:r.id,demo:!!r.demo}};
}
function devRuleForThing(machine,demo,t){
  const v=typeof t.value==='number'?t.value:'';
  DEVSCENE.form={machine,demo:!!demo,item:t.id,when:t.onoff?'on':'above',value:v===''?'':String(Math.round(v*10)/10),
    for:'0',forUnit:'s',level:'alarm',name:'',note:'',paused:false,editing:null};
}
function devRuleBlank(d){
  const m=(d.machines||[])[0]||{};
  DEVSCENE.form={machine:m.machine||'',demo:!!m.demo,item:'',when:'above',value:'',for:'0',forUnit:'s',level:'alarm',name:'',note:'',paused:false,editing:null};
}
/* What a rule would say about the reading it has now: the editor's preview, and each card's line. */
function devRuleHolds(r,m,t){
  if(r.when==='offline')return m?m.up===false:null;
  if(!t||t.value===undefined||t.value===null)return null;
  if(r.when==='on')return !!t.value;
  if(r.when==='off')return !t.value;
  const v=+r.value;if(r.value===''||isNaN(v)||typeof t.value!=='number')return null;
  return r.when==='above'?t.value>v:t.value<v;
}
function devRuleSentence(r,t){
  const what=r.when==='offline'?esc(r.machine):`<b>${esc(t?devSceneShort(t):r.item||'a thing')}</b> on ${esc(r.machine)}`;
  const val=(r.when==='above'||r.when==='below')&&r.value!==''&&r.value!==undefined&&r.value!==null?` <b>${esc(devSceneNum(+r.value,t&&t.unit||r.unit||''))}</b>`:'';
  const hold=+r.for?` for <b>${devSceneAgo(+r.for)}</b>`:'';
  return `When ${what} ${esc(devSceneWhen(r.when,t))}${val}${hold}, raise ${r.level==='warning'?'a <b>warning</b>':'an <b>alarm</b>'}.`;
}
/* How often each rule went off in the last day, from the board's history and what is open. */
function devRuleCounts(d){
  const c={};const add=(a,open)=>{const k=a.id+'|'+!!a.demo,x=c[k]||(c[k]={n:0,last:0,open:false});x.n++;x.last=Math.max(x.last,a.since||0);if(open)x.open=a};
  (d.history||[]).forEach(a=>add(a,false));(d.alarms||[]).filter(a=>a.state==='active').forEach(a=>add(a,true));
  return c;
}
function devRuleCard(r,d,counts){
  const t=devRuleThing(d,r),m=devRuleMachine(d,r.machine,r.demo),k=counts[r.id+'|'+!!r.demo]||{n:0,last:0};
  const state=r.now==='paused'?['paused','Paused']:r.now==='active'?['raised',`Raised${k.open?' for '+devSceneAgo(k.open.held||0):''}`]
    :r.now==='pending'?['wait','Building up']:r.now==='unconfirmed'?['wait','Checking']:['ok','Clear'];
  const now=r.when==='offline'?(m?(m.up===false?'not answering now':'answering now'):'')
    :t?`reads ${esc(devSceneVal(t))} now`:'';
  const from=r.source==='mission'?`mission ${esc(r.flow||'')}`:r.demo?'warehouse demo':'you';
  const id=esc(r.id),dm=r.demo?' data-demo="1"':'',sure=DEVSCENE.confirm===r.id+'|'+!!r.demo;
  const edited=DEVSCENE.form&&DEVSCENE.form.editing&&DEVSCENE.form.editing.id===r.id&&DEVSCENE.form.editing.demo===!!r.demo;
  return `<article class="dvr-card ${esc(r.level)} ${state[0]}${edited?' editing':''}${DEVSCENE.focus===r.id?' focus':''}" aria-label="${esc(r.label||r.text)}">
    <header>${devSceneSev(r,false)}<h4>${esc(r.label||r.text)}</h4><span class="dvr-state ${state[0]}">${esc(state[1])}</span></header>
    <p class="dvr-cond">${devRuleSentence(r,t)}</p>
    <p class="dvr-meta">${[now,k.n?`went off ${k.n} time${k.n===1?'':'s'} in 24 h, last at ${esc(devSceneClock(k.last))}`:'quiet in the last 24 h',`set by ${from}`].filter(Boolean).join(' · ')}</p>
    ${r.note?`<p class="dvr-note"><b>What to do:</b> ${esc(r.note)}</p>`:''}
    <footer>${r.editable?`<button class="endbtn" data-dvr="edit" data-id="${id}"${dm}>Edit</button>
      <button class="linkbtn" data-dvr="pause" data-id="${id}"${dm}>${r.paused?'Resume':'Pause'}</button>
      <button class="linkbtn" data-dvr="copy" data-id="${id}"${dm}>Duplicate</button>`
      :'<button class="linkbtn" data-dvr="mission">Change it in Missions</button>'}
      ${r.item&&t?`<button class="linkbtn" data-dvr="hist" data-id="${id}"${dm}>History</button>`:''}
      ${r.editable?`<button class="linkbtn dvr-del${sure?' sure':''}" data-dvr="del" data-id="${id}"${dm}>${sure?'Yes, remove it':'Remove'}</button>`:''}</footer>
  </article>`;
}
function devRuleEditorHTML(d){
  const f=DEVSCENE.form,ms=d.machines||[];
  const m=devRuleMachine(d,f.machine,f.demo)||ms[0]||{things:[]};
  if(m.machine&&m.machine!==f.machine){f.machine=m.machine;f.demo=!!m.demo}
  const things=m.things||[];
  let t=things.find(x=>x.id===f.item);if(!t&&f.when!=='offline'){t=things[0];if(t)f.item=t.id}
  const whens=t&&t.onoff?['on','off','offline']:['above','below','offline'];
  if(whens.indexOf(f.when)<0)f.when=whens[0];
  const opt=(v,l,sel)=>`<option value="${esc(v)}"${sel?' selected':''}>${esc(l)}</option>`;
  const groups={};things.forEach(x=>{(groups[x.group_name||'']=groups[x.group_name||'']||[]).push(x)});
  const thingSel=Object.keys(groups).map(g=>`<optgroup label="${esc(g)}">${groups[g].map(x=>opt(x.id,`${devSceneShort(x)} (${devSceneVal(x)})`,t&&x.id===t.id)).join('')}</optgroup>`).join('');
  const num=f.when==='above'||f.when==='below';
  return `<aside class="dvr-ed" aria-label="${f.editing?'Edit this rule':'New rule'}">
    <h3>${f.editing?'Edit this rule':'New rule'}</h3>
    <div class="dvr-sent">
      <label><span>When</span><select data-f="machine" aria-label="Machine">${ms.map(x=>opt(x.machine+'|'+(x.demo?1:0),x.machine+(x.demo?' (demo)':''),x.machine===m.machine&&!!x.demo===!!m.demo)).join('')}</select></label>
      ${f.when!=='offline'?`<label><span>its</span><select data-f="item" aria-label="Thing">${thingSel}</select></label>`:''}
      <label><span>${f.when==='offline'?'':'&nbsp;'}</span><select data-f="when" aria-label="Condition">${whens.map(w=>opt(w,devSceneWhen(w,t),w===f.when)).join('')}</select></label>
      ${num?`<label><span>than</span><span class="dvr-num"><input data-f="value" inputmode="decimal" value="${esc(f.value)}" placeholder="a number" aria-label="Value">${t&&t.unit?`<em>${esc(t.unit)}</em>`:''}</span></label>`:''}
      <label><span>for at least</span><span class="dvr-num"><input data-f="for" inputmode="numeric" value="${esc(f.for)}" aria-label="How long it must hold">
        <select data-f="forUnit" aria-label="Unit">${opt('s','seconds',f.forUnit==='s')}${opt('min','minutes',f.forUnit==='min')}</select></span></label>
    </div>
    <fieldset class="dvr-level"><legend>Raise</legend>
      <label><input type="radio" name="dvr-level" data-f="level" value="alarm"${f.level==='alarm'?' checked':''}> ${devSceneSev({level:'alarm'},false)} <small>needs someone now: it toasts on every screen</small></label>
      <label><input type="radio" name="dvr-level" data-f="level" value="warning"${f.level==='warning'?' checked':''}> ${devSceneSev({level:'warning'},false)} <small>worth a look: it shows on the board</small></label></fieldset>
    <label class="dvr-field"><span>Name <small>(optional)</small></span><input data-f="name" maxlength="60" value="${esc(f.name)}" placeholder="${esc(t?devSceneShort(t)+' too '+(f.when==='below'?'low':'high'):'Cold room B too warm')}"></label>
    <label class="dvr-field"><span>What to do when it goes off <small>(optional)</small></span><textarea data-f="note" maxlength="240" rows="2" placeholder="Check the compressor, then call maintenance">${esc(f.note)}</textarea></label>
    ${f.editing?`<label class="dvr-check"><input type="checkbox" data-f="paused"${f.paused?' checked':''}> Paused <small>kept, but raises nothing</small></label>`:''}
    <div class="dvr-preview" aria-live="polite">${devRulePreview(d)}</div>
    <div class="dvr-acts"><button class="wiz-next" data-dvr="save">${f.editing?'Save changes':'Add this rule'}</button>
      <button class="linkbtn" data-dvr="cancel">Cancel</button></div>
  </aside>`;
}
function devRuleFromForm(){
  const f=DEVSCENE.form,secs=Math.round((+f.for||0)*(f.forUnit==='min'?60:1));
  const r={machine:f.machine,when:f.when,for:secs,level:f.level};
  if(f.when!=='offline')r.item=f.item;
  if(f.when==='above'||f.when==='below')r.value=f.value===''?'':+f.value;
  if((f.name||'').trim())r.name=f.name.trim();
  if((f.note||'').trim())r.note=f.note.trim();
  if(f.paused)r.paused=true;
  return r;
}
/* the sentence a rule would raise, what it would do with the reading now, and what is wrong with it */
function devRuleProblem(d,r){
  const f=DEVSCENE.form;
  if(!r.machine)return 'Pick a machine.';
  if(r.when!=='offline'&&!r.item)return 'Pick the thing to watch.';
  if((r.when==='above'||r.when==='below')&&(r.value===''||isNaN(r.value)))return 'Give it a number to compare with.';
  if(isNaN(r.for)||r.for<0||r.for>3600)return 'How long it must hold is 0 to 60 minutes.';
  const same=x=>x.machine.toLowerCase()===r.machine.toLowerCase()&&(x.item||'')===(r.item||'')&&x.when===r.when
    &&(r.value===undefined||+x.value===+r.value)&&(+x.for||0)===r.for;
  const twin=(d.rule_list||[]).find(x=>!!x.demo===!!f.demo&&same(x)&&!(f.editing&&f.editing.id===x.id&&f.editing.demo===!!x.demo));
  if(twin)return `There's already a rule for exactly this${twin.label?`: ${twin.label}`:''}.`;
  return '';
}
function devRulePreview(d){
  const f=DEVSCENE.form;if(!f)return '';
  const r=devRuleFromForm(),bad=devRuleProblem(d,r),m=devRuleMachine(d,f.machine,f.demo),t=m&&r.item?m.things.find(x=>x.id===r.item):null;
  if(bad)return `<p class="dvr-bad">${esc(bad)}</p>`;
  const h=devRuleHolds(r,m,t);
  const now=r.when==='offline'?(m&&m.up===false?`${esc(r.machine)} isn't answering now`:`${esc(r.machine)} is answering now`)
    :t?`${esc(devSceneShort(t))} reads ${esc(devSceneVal(t))} now`:'';
  const then=r.paused?'It is paused, so it raises nothing.':h===null?'There is no reading to judge yet.'
    :h?(r.for?`So it would be building up, and raised after ${devSceneAgo(r.for)} if it stays that way.`:'So it would be raised straight away.')
    :'So it would stay clear.';
  return `<p>${devRuleSentence({...r,value:r.value===undefined?'':r.value,unit:t&&t.unit},t)}</p><p class="${h&&!r.paused?'dvr-would':'mut'}">${now?now+'. ':''}${then}</p>`;
}
function devRulesHTML(d){
  d=d||{};
  const rules=d.rule_list||[],ms=d.machines||[],flt=DEVSCENE.rf||'all',q=(DEVSCENE.rq||'').toLowerCase(),counts=devRuleCounts(d);
  const pick={all:()=>true,raised:r=>r.now==='active',yours:r=>r.editable&&!r.demo,demo:r=>!!r.demo,missions:r=>r.source==='mission',paused:r=>!!r.paused};
  const n=k=>rules.filter(pick[k]).length;
  const shown=rules.filter(pick[flt]||pick.all).filter(r=>!q||(r.label+' '+r.text+' '+r.machine+' '+(r.note||'')).toLowerCase().indexOf(q)>=0);
  const rank=r=>r.now==='active'?0:r.now==='pending'||r.now==='unconfirmed'?1:r.paused?3:2;
  const byM={};shown.slice().sort((a,b)=>rank(a)-rank(b)||(a.label||a.text).localeCompare(b.label||b.text))
    .forEach(r=>{const k=r.machine+(r.demo?' (demo)':'');(byM[k]=byM[k]||[]).push(r)});
  const raised=n('raised'),paused=n('paused');
  const list=Object.keys(byM).sort().map(k=>`<div class="dvr-group"><h3>${esc(k)} <em>${byM[k].length}</em></h3>
      <div class="dvr-cards">${byM[k].map(r=>devRuleCard(r,d,counts)).join('')}</div></div>`).join('')
    ||(rules.length?'<p class="mut">No rule matches.</p>':`<div class="dvr-empty"><p>No alarm rules yet.</p>
      <p class="mut">A rule watches one thing: a temperature above a limit, a door left open, a machine that stops answering. Tap a reading on the board to start one from it.</p></div>`);
  const ed=DEVSCENE.form&&ms.length;
  return `<section class="dvs-rules dvr" aria-label="Alarm rules">
    <div class="dvr-top"><div><h2>Alarm rules ${pInfo('An alarm shows while its condition holds and clears by itself when it stops. Acknowledge only marks that you saw it. A mission that is on watches its own rules, and you change those in the mission.')}</h2>
      <p class="dvr-sum">${rules.length} rule${rules.length===1?'':'s'} · <b class="${raised?'bad':'ok'}">${raised?raised+' raised now':'none raised'}</b>${paused?` · ${paused} paused`:''}</p></div>
      ${ms.length?`<button class="wiz-next" data-dvr="new">＋ New rule</button>`:''}</div>
    <div class="dvr-bar"><div class="dvs-tabs" role="group" aria-label="Which rules">${DEVR_FILTERS.filter(([k])=>k==='all'||n(k)).map(([k,l])=>
        `<button class="${flt===k?'on':''}" data-dvr="filter" data-v="${k}" aria-pressed="${flt===k}">${l} <em>${n(k)}</em></button>`).join('')}</div>
      ${rules.length>4?`<input class="dvr-q" data-dvr-q type="search" value="${esc(DEVSCENE.rq||'')}" placeholder="Find a rule" aria-label="Find a rule">`:''}</div>
    <div class="dvr-body${ed?' with-ed':''}"><div class="dvr-list">${list}</div>${ed?devRuleEditorHTML(d):''}</div>
    <p class="mut dvs-always">Always on, without a rule: a machine that stops answering, and a sensor with no reading.</p>
  </section>`;
}
/* host: the element the rules were drawn into; repaint draws that host again, reload reads the board */
function devRulesWire(host,repaint,reload){
  const d=devRulesBoard()||{};
  host.querySelectorAll('[data-f]').forEach(x=>{
    const set=()=>{const f=DEVSCENE.form;if(!f)return;const k=x.dataset.f;
      if(k==='machine'){const [mn,dm]=x.value.split(/\|(?=[01]$)/);f.machine=mn;f.demo=dm==='1';f.item=''}
      else if(k==='paused')f.paused=x.checked;
      else if(k==='level'){if(x.checked)f.level=x.value}
      else f[k]=x.value;
      return k};
    x.oninput=()=>{set();const p=host.querySelector('.dvr-preview');if(p)p.innerHTML=devRulePreview(devRulesBoard()||{})};
    x.onchange=()=>{const k=set();if(k==='machine'||k==='item'||k==='when'||k==='level')repaint()}});
  const q=host.querySelector('[data-dvr-q]');
  if(q)q.oninput=()=>{DEVSCENE.rq=q.value;clearTimeout(DEVSCENE.qt);DEVSCENE.qt=setTimeout(()=>{repaint();
    const n=host.querySelector('[data-dvr-q]');if(n){n.focus();n.setSelectionRange(n.value.length,n.value.length)}},250)};
  host.querySelectorAll('[data-dvr]').forEach(b=>b.onclick=()=>{
    const act=b.dataset.dvr,isDemo=!!b.dataset.demo,id=b.dataset.id;
    const r=id&&(d.rule_list||[]).find(x=>x.id===id&&!!x.demo===isDemo);
    if(act==='mission')return openApp('fabric');
    if(act==='filter'){DEVSCENE.rf=b.dataset.v;return repaint()}
    if(act==='new'){devRuleBlank(d);repaint();return devSceneRulesReveal(true,host)}
    if(act==='cancel'){DEVSCENE.form=null;return repaint()}
    if(act==='edit'||act==='copy'){if(r)devSceneRuleEdit(r,act==='copy');repaint();return devSceneRulesReveal(true,host)}
    if(act==='hist'){const t=r&&devRuleThing(d,r);return t&&devHistOpen(r.machine,t.id,!!r.demo)}
    const own=(d.rules||[]).slice(),demo=(d.demo_rules||[]).slice(),touched={};
    const list=inDemo=>inDemo?demo:own,at=(rid,inDemo)=>list(inDemo).findIndex(x=>x.id===rid);
    if(act==='del'){
      const k=id+'|'+isDemo;
      if(DEVSCENE.confirm!==k){DEVSCENE.confirm=k;repaint();clearTimeout(DEVSCENE.ct);
        DEVSCENE.ct=setTimeout(()=>{if(DEVSCENE.confirm===k){DEVSCENE.confirm='';repaint()}},5000);return}
      DEVSCENE.confirm='';const i=at(id,isDemo);if(i>=0){list(isDemo).splice(i,1);touched[isDemo?'demo':'own']=true}
      if(DEVSCENE.form&&DEVSCENE.form.editing&&DEVSCENE.form.editing.id===id)DEVSCENE.form=null;
      return devSceneRulesSave(own,demo,touched,reload,'Rule removed')}
    if(act==='pause'){const i=at(id,isDemo);if(i<0)return;
      const x={...list(isDemo)[i]};if(x.paused)delete x.paused;else x.paused=true;
      list(isDemo)[i]=x;touched[isDemo?'demo':'own']=true;
      return devSceneRulesSave(own,demo,touched,reload,x.paused?'Paused. It raises nothing until you resume it':'Resumed')}
    if(act==='save'){
      const f=DEVSCENE.form;if(!f)return;
      host.querySelectorAll('[data-f]').forEach(x=>{const k=x.dataset.f;if(k==='machine'||k==='level'||k==='paused')return;f[k]=x.value});
      const nr=devRuleFromForm(),bad=devRuleProblem(d,nr);
      if(bad){const p=host.querySelector('.dvr-preview');if(p)p.innerHTML=devRulePreview(d);return toast(bad,{kind:'warn'})}
      if(f.editing){const i=at(f.editing.id,f.editing.demo);if(i>=0){list(f.editing.demo).splice(i,1);touched[f.editing.demo?'demo':'own']=true}}
      list(f.demo).push(nr);touched[f.demo?'demo':'own']=true;
      return devSceneRulesSave(own,demo,touched,reload,f.editing?'Rule saved':'Rule added')}
  });
}
async function devSceneRulesSave(own,demo,touched,reload,said){
  let ok=true;
  for(const k of Object.keys(touched)){
    try{const r=await fetch('/api/devices/alarms',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({alarms:k==='demo'?demo:own,demo:k==='demo'})});
      const d=await r.json();if(!r.ok)throw new Error(d.error||'Those rules could not be saved');
      if((d.dropped||[]).length){ok=false;toast('Not kept: '+d.dropped.join('; '),{kind:'warn'})}}
    catch(e){ok=false;toast(String(e.message||e),{kind:'err'})}
  }
  // the editor is gone once it saved, and a caret left in it would hold the board's refresh off
  if(ok){DEVSCENE.form=null;DEVSCENE.focus='';if(said)toast(said);
    const a=document.activeElement;if(a&&a.blur&&/INPUT|SELECT|TEXTAREA/.test(a.tagName))a.blur()}
  (reload||devSceneLoad)();
  if(DEVSCENE.on&&reload!==devSceneLoad)devSceneLoad();
  if(typeof devAlarmsLoad==='function'&&reload!==devAlarmsLoad)devAlarmsLoad();
}
/* Bring the editor, or the rules, into view. */
function devSceneRulesReveal(form,host){
  const el=host||DEVSCENE.el,x=el&&el.querySelector(form?'.dvr-ed':'.dvs-rules');
  if(x)x.scrollIntoView({block:form?'nearest':'start'});
  const i=form&&x&&x.querySelector('select,input');if(i)i.focus({preventScroll:true});
}

/* ---- a thing's history: tap a reading on the board ----
   Asked for as "if I click on the charts it should show the deep historical chart". The sparkline is
   the last hour; the sheet is Devices → Hardware's chart (24u-devchart.js, one drawing) over a day,
   a week, 30 or 90 days, read from /api/devices/history, which finds the thing the way the board
   does (so a Zero's owner sees it too, and the demo's comes from its own hub). From there a rule can
   be started for that thing. The sheet lives outside the scene's markup, so the board's refresh never
   redraws it. */
var DEVHIST={machine:'',item:'',demo:false,range:'day',data:null,el:null};
function devHistOpen(machine,item,demo){
  Object.assign(DEVHIST,{machine,item,demo:!!demo,data:null});
  let el=document.getElementById('devhist');
  if(!el){el=document.createElement('div');el.id='devhist';el.className='dvh';el.setAttribute('role','dialog');el.setAttribute('aria-modal','true');
    el.innerHTML='<div class="dvh-card"><header><div><h2></h2><p class="mut"></p></div><button class="dvh-x" aria-label="Close">✕</button></header><div class="dev-chart dvh-chart"></div></div>';
    document.body.appendChild(el);
    el.onclick=e=>{if(e.target===el)devHistClose()};
    el.querySelector('.dvh-x').onclick=devHistClose;
    el.addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();devHistClose()}})}
  DEVHIST.el=el;el.hidden=false;
  const d=devRulesBoard()||{},m=devRuleMachine(d,machine,demo),t=m&&m.things.find(x=>x.id===item);
  el.setAttribute('aria-label',`${t?devSceneShort(t):item} over time`);
  el.querySelector('h2').textContent=t?devSceneShort(t):item;
  el.querySelector('header p').textContent=`${t&&t.group_name&&t.group!=='board'?t.group_name+' · ':''}${machine}${demo?' (demo)':''}${t?' · reads '+devSceneVal(t)+' now':''}`;
  el.querySelector('.dvh-x').focus({preventScroll:true});
  devHistFill();
}
function devHistClose(){if(DEVHIST.el)DEVHIST.el.hidden=true;DEVHIST.machine=''}
async function devHistFill(){
  const el=DEVHIST.el;if(!el||el.hidden)return;
  const slot=el.querySelector('.dvh-chart'),want=DEVHIST.machine+'|'+DEVHIST.item+'|'+DEVHIST.range;
  const opts={range:DEVHIST.range,onRange:id=>{DEVHIST.range=id;devHistFill()},extra:devHistButtons()};
  devChartDraw(slot,DEVHIST.data,true,opts);
  try{
    const d=await apiJSON(`/api/devices/history?machine=${encodeURIComponent(DEVHIST.machine)}&item=${encodeURIComponent(DEVHIST.item)}&range=${DEVHIST.range}${DEVHIST.demo?'&demo=1':''}`);
    if(want!==DEVHIST.machine+'|'+DEVHIST.item+'|'+DEVHIST.range)return;
    DEVHIST.data=d;devChartDraw(slot,d,false,opts);
  }catch(e){slot.textContent='';const p=document.createElement('p');p.className='mut';p.textContent=String(e.message||e);slot.appendChild(p)}
}
function devHistButtons(){
  const d=devRulesBoard()||{},m=devRuleMachine(d,DEVHIST.machine,DEVHIST.demo),t=m&&m.things.find(x=>x.id===DEVHIST.item);
  if(!t||/\.text_sensor\./.test(t.id))return [];
  const b=document.createElement('button');b.type='button';b.className='endbtn';b.textContent='＋ Alarm rule for this';
  b.onclick=()=>{devRuleForThing(DEVHIST.machine,DEVHIST.demo,t);devHistClose();devRulesShow()};
  return [b];
}
/* Open the rules wherever the person is: the scene's Rules view, or the section in Devices. */
function devRulesShow(){
  if(DEVSCENE.on&&!document.body.classList.contains('has-win')){DEVSCENE.page='rules';devScenePaint();return devSceneRulesReveal(!!DEVSCENE.form)}
  if(document.querySelector('.dev-rules')&&typeof DEVAL!=='undefined'){DEVAL.rules=true;devAlarmsPaint();
    const h=document.querySelector('.dev-rules');return h&&devSceneRulesReveal(!!DEVSCENE.form,h)}
  DEVSCENE.page='rules';if(typeof devBoardShow==='function')devBoardShow();
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
  toast(`⚠ ${a.machine}: ${a.label||a.text}${a.note?'. '+a.note:''}`,{kind:'err',label:'See devices',ms:12000,go:()=>n?switchDesk(n):openApp('devices')});
}
// first paint: 01b ran before this file existed, so the scene starts itself (as 01c and 01g do)
if(typeof IMMERSIVE!=='undefined'&&IMMERSIVE.on&&immersiveSceneNow()==='devices')setTimeout(devSceneStart,0);
