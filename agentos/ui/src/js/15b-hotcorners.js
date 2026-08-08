/* ================= hot corners =================
   Four corners, four gestures, no clicking. Every corner ships bound to
   something useful — an unbound corner teaches you nothing, so the defaults are
   the four things you reach for most:

     top-left      Overview      every window on this desktop, laid out
     top-right     Control Centre  sound, brightness, network, battery
     bottom-left   App deck      the launcher
     bottom-right  Show desktop  everything out of the way, and back again

   Any corner can be rebound to a desktop action, an app, or one of your
   automations — which is the point: a corner is the fastest trigger a saved
   routine can have. Config is per-machine (localStorage), like the deck. */

const HC_DEFAULTS={tl:'expose',tr:'control',bl:'deck',br:'showdesktop'};
const HC_CORNERS=[['tl','Top left'],['tr','Top right'],['bl','Bottom left'],['br','Bottom right']];
const HC_SIZE=10;        // px of the square trigger zone in the very corner
let HOTCORNERS={...HC_DEFAULTS,enabled:true,delay:240};
function hcLoad(){
  try{HOTCORNERS={...HOTCORNERS,...(JSON.parse(localStorage.getItem('hotcorners')||'{}'))}}catch(e){}
}
function hcSave(){localStorage.setItem('hotcorners',JSON.stringify(HOTCORNERS))}
hcLoad();

/* What a corner can be bound to. Desktop actions come from the SAME table the
   keyboard uses, so a corner can never do something a shortcut cannot. */
const HC_ACTIONS=[
  ['','— nothing —'],
  ['expose','Overview — all windows'],
  ['showdesktop','Show desktop'],
  ['deck','App deck'],
  ['deck.all','All apps — the app wall'],
  ['deck.widgets','Widgets — the wall\'s other face'],
  ['launcher','Launcher (start menu)'],
  ['control','Control Centre'],
  ['notifications','Notifications'],
  ['omnibar.focus','Prompt bar — ask the agent'],
  ['chat.open','Open Chat'],
  ['chat.new','New chat'],
  ['terminal','Terminal'],
  ['windows.arrange','Tile the windows'],
  ['voice','Voice mode'],
  ['fullscreen','Full screen'],
  ['settings','Settings'],
  ['lock','Lock the screen'],
];
function hcLabel(v){
  if(!v)return '— nothing —';
  if(v.startsWith('automation:')){
    const a=(AUTOMATIONS||[]).find(x=>x.id===v.slice(11));
    return a?('Automation — '+a.name):'Automation (deleted)';
  }
  if(v.startsWith('app:'))return 'Open '+((APPS[v.slice(4)]&&APPS[v.slice(4)].title)||v.slice(4));
  const hit=HC_ACTIONS.find(a=>a[0]===v);
  return hit?hit[1]:v;
}
function hcFire(corner){
  const v=HOTCORNERS[corner];
  if(!v)return;
  if(v.startsWith('automation:'))return runAutomation(v.slice(11));
  if(v.startsWith('app:'))return openApp(v.slice(4));
  if(v==='showdesktop')return toggleShowDesktop();
  if(v==='launcher')return toggleStart();
  if(v==='control')return toggleControlCenter();
  if(v==='notifications')return openNotifPanel();
  if(v==='lock')return powerDo('lock','Lock the screen?');
  scRun(v);
}

/* ---- show desktop: get everything out of the way, then put it back ---- */
let SHOWDESK=null;   // the windows we minimized, so the same corner restores them
function toggleShowDesktop(){
  if(SHOWDESK&&SHOWDESK.length){
    SHOWDESK.forEach(w=>{if(WM.wins.has(w.key))restoreWin(w)});
    SHOWDESK=null;toast('windows restored');return;
  }
  const hide=[];WM.wins.forEach(w=>{if(!w.min&&(w.desk||1)===curDesk)hide.push(w)});
  if(!hide.length)return toast('the desktop is already clear');
  hide.forEach(minimizeWin);
  SHOWDESK=hide;
}

/* ---- the trigger: dwell in the corner, not just touch it ----
   A pointer flying to a close button clips the corner constantly, so a corner
   only fires after the pointer has RESTED there, and it must leave the zone
   before it can fire again. The hint arc grows during the dwell, which is both
   the affordance and the escape hatch: see it filling, move away. */
let hcTimer=null, hcArmed=null, hcHint=null;
function hcZone(x,y){
  const w=innerWidth,h=innerHeight;
  if(x<=HC_SIZE&&y<=HC_SIZE)return 'tl';
  if(x>=w-HC_SIZE&&y<=HC_SIZE)return 'tr';
  if(x<=HC_SIZE&&y>=h-HC_SIZE)return 'bl';
  if(x>=w-HC_SIZE&&y>=h-HC_SIZE)return 'br';
  return null;
}
function hcCancel(){
  clearTimeout(hcTimer);hcTimer=null;hcArmed=null;
  if(hcHint){hcHint.classList.remove('on');hcHint.className='hc-hint'}
}
function hcActive(){
  if(!HOTCORNERS.enabled)return false;
  if(typeof isMobile==='function'&&isMobile())return false;    // no pointer to rest
  if(document.querySelector('.win.dragging'))return false;      // mid-drag, not a gesture
  if(typeof AUTO_RUNNING!=='undefined'&&AUTO_RUNNING)return false;
  return true;
}
addEventListener('pointermove',e=>{
  if(e.pointerType==='touch')return;
  if(!hcActive())return hcCancel();
  const z=hcZone(e.clientX,e.clientY);
  if(z===hcArmed)return;              // still dwelling in the same corner
  hcCancel();
  if(!z||!HOTCORNERS[z])return;
  hcArmed=z;
  if(!hcHint){hcHint=document.createElement('div');document.body.appendChild(hcHint)}
  hcHint.className='hc-hint hc-'+z;
  hcHint.style.setProperty('--hc-ms',HOTCORNERS.delay+'ms');
  requestAnimationFrame(()=>hcHint.classList.add('on'));
  hcTimer=setTimeout(()=>{const c=hcArmed;hcCancel();if(c)hcFire(c)},HOTCORNERS.delay);
},{passive:true});
addEventListener('pointerdown',hcCancel,{passive:true});
addEventListener('blur',hcCancel);

/* ---- the settings card, rendered inside the Automations app ---- */
function hcCardHTML(){
  const opts=v=>{
    const auto=(AUTOMATIONS||[]).map(a=>[`automation:${a.id}`,'Automation — '+a.name]);
    const apps=Object.keys(APPS).map(k=>[`app:${k}`,'Open '+APPS[k].title]);
    return [...HC_ACTIONS,...auto,...apps]
      .map(([val,lbl])=>`<option value="${esc(val)}"${val===v?' selected':''}>${esc(lbl)}</option>`).join('');
  };
  return `<div class="provbox hc-box">
    <div class="ptitle">Hot corners
      <label class="hc-on"><input type="checkbox" id="hc-en"${HOTCORNERS.enabled?' checked':''}> enabled</label>
    </div>
    <p class="mut" style="margin:6px 0 12px">Rest the pointer in a corner. Every corner starts bound to something —
      rebind any of them to a desktop action, an app, or one of your automations.</p>
    <div class="hc-grid">
      ${HC_CORNERS.map(([c,lbl])=>`<label class="hc-cell hc-cell-${c}">
        <span class="hc-lbl">${lbl}</span>
        <select data-hc="${c}">${opts(HOTCORNERS[c]||'')}</select>
      </label>`).join('')}
      <div class="hc-screen"><span>screen</span></div>
    </div>
    <div class="row" style="margin-top:12px;align-items:center;gap:10px">
      <span class="mut" style="flex:0 0 auto">Dwell before it fires</span>
      <input type="range" id="hc-delay" min="80" max="800" step="20" value="${HOTCORNERS.delay}" style="flex:1">
      <span class="mut" id="hc-delayn" style="flex:0 0 54px;text-align:right">${HOTCORNERS.delay}ms</span>
      <button class="endbtn" onclick="hcReset()">Reset</button>
    </div>
  </div>`;
}
function hcBind(root){
  root.querySelectorAll('[data-hc]').forEach(s=>s.onchange=()=>{
    HOTCORNERS[s.dataset.hc]=s.value;hcSave();toast(HC_CORNERS.find(c=>c[0]===s.dataset.hc)[1]+' → '+hcLabel(s.value));
  });
  const en=root.querySelector('#hc-en');
  if(en)en.onchange=()=>{HOTCORNERS.enabled=en.checked;hcSave();hcCancel()};
  const d=root.querySelector('#hc-delay');
  if(d)d.oninput=()=>{HOTCORNERS.delay=+d.value;root.querySelector('#hc-delayn').textContent=d.value+'ms';hcSave()};
}
function hcReset(){HOTCORNERS={...HOTCORNERS,...HC_DEFAULTS};hcSave();hcRender()}
function hcRender(){refreshApp('automations')}
