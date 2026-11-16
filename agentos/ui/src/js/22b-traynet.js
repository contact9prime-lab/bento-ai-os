/* ================= the network, on the menu bar =================
   Asked for as "it is not showing a wifi option on the top". The kiosk could already join
   Wi-Fi (24h-kiosk.js) and Quick Settings only sent you to the system's own settings, so a
   desktop running Bento, where the system's network menu may not exist, had no way to see
   or change its network. This is the same /api/wifi (wifi.py, NetworkManager) on the bar.

   What it says, all read from the machine:
     - the signal of the network it is on, or wired, or Offline in amber. Offline also
       says what that costs: a cloud brain cannot answer until it is back.
     - when it comes back, one toast naming the network, so a dropped link is noticed both
       ways without anybody watching the icon.
   Joining is the admin's (the route checks; the page says it before asking for a
   password). From another device it warns first: that device reaches Bento over the
   network being changed, so it may lose the page.

   It is the MACHINE's network, so a phone or laptop looking at Bento sees the server's
   Wi-Fi, and the panel says so. No nmcli here (a Mac, a container) and the button is not
   drawn at all: there is nothing it could do. TUI: `bento wifi`. SUI: a page element,
   nothing touches the compositor. Polled once a minute while the page is visible; a scan
   happens only while the panel is open. */
var TRAYNET={st:null,nets:null,open:false,pick:'',err:'',busy:false,t:0,was:null,scanning:false};
var TRAYNET_MS=60000;
function trayNetIcon(st){
  const w=st&&st.wifi,on=w&&w.state==='connected';
  if(st&&!st.online&&!(st.wired))return `<svg width="16" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M2.5 9.5a14 14 0 0 1 19 0M6 13a9 9 0 0 1 12 0M9.5 16.5a4 4 0 0 1 5 0" opacity=".45"/><path d="M4 3l16 18"/></svg>`;
  if(!on&&st&&st.wired)return `<svg width="16" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="7" y="3" width="10" height="8" rx="1"/><path d="M12 11v4M5 21v-3h14v3M12 15v3"/></svg>`;
  const s=on&&w.signal!=null?w.signal:70;
  const lit=s>=67?3:s>=34?2:1;
  const arc=(d,i)=>`<path d="${d}" opacity="${i<=lit?1:.3}"/>`;
  return `<svg width="16" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">${arc('M9.5 16.5a4 4 0 0 1 5 0',1)}${arc('M6 13a9 9 0 0 1 12 0',2)}${arc('M2.5 9.5a14 14 0 0 1 19 0',3)}<circle cx="12" cy="20" r="1.2" fill="currentColor" stroke="none"/></svg>`;
}
function trayNetLine(st){
  if(!st)return '';
  const w=st.wifi;
  if(w&&w.state==='connected')return `Wi-Fi · ${w.connection}${w.signal!=null?' · '+w.signal+'%':''}`;
  if(st.wired)return 'Wired';
  if(!st.online)return 'Offline';
  return 'Online';
}
async function trayNetLoad(scan){
  clearTimeout(TRAYNET.t);
  const b=document.getElementById('tray-net');if(!b)return;
  let st=null;
  try{st=await apiJSON('/api/wifi'+(scan?'?scan=1':''))}catch(e){st=null}
  if(!st||(!st.ok&&!st.devices?.length&&st.why)){b.hidden=true;TRAYNET.st=st;trayNetSoon();return}
  if(st.networks)TRAYNET.nets=st.networks;
  // back online after being off: say where, once
  if(TRAYNET.was===false&&st.online)toast('✓ Back online'+(st.wifi&&st.wifi.state==='connected'?' · '+st.wifi.connection:''),{kind:'ok'});
  TRAYNET.was=!!st.online;TRAYNET.st=st;
  const off=!st.online;
  b.hidden=false;b.classList.toggle('off',off);
  b.innerHTML=trayNetIcon(st)+(off?'<span class="tn-off">Offline</span>':'');
  b.title=trayNetLine(st)+' · click for networks';
  b.setAttribute('aria-label',trayNetLine(st));
  if(TRAYNET.open)trayNetPaint();
  trayNetSoon();
}
function trayNetSoon(){
  TRAYNET.t=setTimeout(()=>{if(document.hidden){trayNetSoon();return}trayNetLoad(false)},TRAYNET_MS);
}
function trayNetAdmin(){
  try{const m=USERS&&USERS.me;return !(m&&m.multiuser&&!m.admin)}catch(e){return true}
}
function toggleTrayNet(){
  let p=document.getElementById('netpop');
  if(!p){p=document.createElement('div');p.id='netpop';p.setAttribute('role','dialog');
    p.setAttribute('aria-label','Network');document.body.appendChild(p)}
  if(p.classList.contains('show')){popClose(p);return}
  TRAYNET.open=true;TRAYNET.pick='';TRAYNET.err='';
  popOpen(p,{anchor:document.getElementById('tray-net'),close:()=>{TRAYNET.open=false}});
  trayNetPaint();
  if(typeof popIn==='function')popIn(p,{origin:'top right'});
  TRAYNET.scanning=true;trayNetPaint();
  trayNetLoad(true).finally(()=>{TRAYNET.scanning=false;if(TRAYNET.open)trayNetPaint()});
}
function trayNetPaint(){
  const p=document.getElementById('netpop');if(!p||!TRAYNET.open)return;
  const st=TRAYNET.st||{},list=TRAYNET.nets||[];
  const where=(typeof remoteClient==='function'&&remoteClient())
    ?`<p class="tn-note">This is the network of ${esc(typeof hostName==='function'?hostName():'the machine')}, the machine Bento runs on, not of this device.</p>`:'';
  const head=`<div class="tn-head"><b>${esc(trayNetLine(st)||'Network')}</b>
    <button type="button" class="tn-scan" title="Look again">${TRAYNET.scanning?'Looking…':'↻'}</button></div>`
    +(!st.online?`<p class="tn-warn">This machine is offline. Cloud brains can't answer until it's back on a network.</p>`:'')+where;
  if(TRAYNET.pick){
    const n=list.find(x=>x.ssid===TRAYNET.pick)||{secure:true};
    p.innerHTML=head+`<form class="tn-join"><div class="tn-name">${esc(TRAYNET.pick)}</div>
      ${n.secure?`<input class="tn-pw" type="text" autocomplete="off" data-lpignore="true" data-1p-ignore placeholder="Password" aria-label="Wi-Fi password">`:''}
      <div class="tn-row"><button type="button" class="endbtn tn-back">Back</button>
      <button type="submit" class="endbtn pri"${TRAYNET.busy?' disabled':''}>${TRAYNET.busy?'Joining…':'Join'}</button></div>
      ${TRAYNET.err?`<p class="tn-err">${esc(TRAYNET.err)}</p>`:''}</form>`;
    const pw=p.querySelector('.tn-pw');if(pw&&!TRAYNET.busy)pw.focus();
    p.querySelector('.tn-back').onclick=()=>{TRAYNET.pick='';TRAYNET.err='';trayNetPaint()};
    p.querySelector('form').onsubmit=e=>{e.preventDefault();trayNetJoin(pw?pw.value:'')};
  }else{
    const admin=trayNetAdmin();
    p.innerHTML=head+(list.length?`<div class="tn-list">${list.map(n=>`<button type="button" class="tn-n${n.in_use?' on':''}" data-ssid="${esc(n.ssid)}"${n.in_use||!admin?' disabled':''}>
        <span class="tn-s">${trayNetIcon({online:true,wifi:{state:'connected',signal:n.signal}})}</span>
        <span class="tn-nm">${esc(n.ssid)}</span><small>${n.in_use?'connected':(n.secure?'🔒 ':'')+n.signal+'%'}</small></button>`).join('')}</div>`
      :`<p class="tn-note">${TRAYNET.scanning?'Looking for networks…':'No Wi-Fi networks in range.'}</p>`)
      +(admin?'':`<p class="tn-note">Only an admin can change this machine's network.</p>`);
    p.querySelectorAll('.tn-n:not([disabled])').forEach(b=>b.onclick=()=>{TRAYNET.pick=b.dataset.ssid;TRAYNET.err='';trayNetPaint()});
  }
  const sc=p.querySelector('.tn-scan');
  if(sc)sc.onclick=()=>{if(TRAYNET.scanning)return;TRAYNET.scanning=true;trayNetPaint();
    trayNetLoad(true).finally(()=>{TRAYNET.scanning=false;trayNetPaint()})};
}
async function trayNetJoin(password){
  if(TRAYNET.busy)return;
  const ssid=TRAYNET.pick;
  // a phone or laptop reaches Bento over the network being changed
  if(typeof remoteClient==='function'&&remoteClient()&&typeof osConfirm==='function'){
    const ok=await osConfirm(`Switch ${typeof hostName==='function'?hostName():'the machine'} to ${ssid}?`,
      'You are reaching Bento over its network. If the new one is different, this page may stop answering until you join it too.');
    if(!ok)return;
  }
  TRAYNET.busy=true;TRAYNET.err='';trayNetPaint();
  try{
    const r=await fetch('/api/wifi/connect',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ssid,password})});
    const d=await r.json().catch(()=>({}));
    if(!r.ok)throw new Error(d.error||'could not join');
    TRAYNET.pick='';toast('✓ Joined '+(d.ssid||ssid),{kind:'ok'});
    if(d.status){TRAYNET.st=d.status}
  }catch(e){TRAYNET.err=String(e.message||e)}
  TRAYNET.busy=false;trayNetPaint();trayNetLoad(false);
}
