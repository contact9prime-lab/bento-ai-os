/* A Zero's light face (zero.py). Its work, memory and integrations are on the hub that
   set it up, and the hub answers it as the account it belongs to. So a Zero's screen is
   its one agent and what comes back: Chat (the answers), the Office (its agent, and
   visits to the hub's office), Files (what the hub sends back) and Settings without the
   tabs for things that live on the hub. Every launcher reads zeroAllows(), so they cannot
   disagree about what a Zero offers.
   GUI: this file. TUI: a Zero is driven from its hub; `bento pool mind` reads its section
   there. SUI: the same page as the desktop, nothing native. */
var ZERO_APPS=['chat','office','files','settings','docs'];
// AI providers (it thinks with the hub), executors, channels and accounts are the hub's
var ZERO_TABS_HIDDEN=['ai','executors','channels','accounts','network'];
function zeroFace(){try{return !!(PLATFORM&&PLATFORM.zero&&PLATFORM.zero.on_hub)}catch(e){return false}}
function zeroHub(){try{return (PLATFORM.zero||{}).hub||''}catch(e){return ''}}
function zeroAllows(id){return !zeroFace()||ZERO_APPS.indexOf(id)>=0}
function zeroTabHidden(tab){return zeroFace()&&ZERO_TABS_HIDDEN.indexOf(tab)>=0}
function zeroPlaceOk(pl){return zeroAllows(pl.app)&&!(pl.tab&&zeroTabHidden(pl.tab))}
/* PLATFORM arrives after the dock and the deck were first drawn, so redraw them once */
function zeroApply(){
  const on=zeroFace();
  document.body.classList.toggle('zero-face',on);
  const chip=document.getElementById('zero-chip');
  if(on&&!chip){const mb=document.getElementById('tray');
    if(mb){const c=document.createElement('span');c.id='zero-chip';c.className='zero-chip';
      c.title='This machine is a Zero. Its work, memory and integrations are on '+zeroHub()+'.';
      c.textContent='Zero · '+zeroHub();c.onclick=()=>openApp('office');mb.prepend(c)}}
  else if(!on&&chip)chip.remove();
  try{if(typeof buildDock==='function')buildDock()}catch(e){}
  try{if(typeof buildDeck==='function')buildDeck()}catch(e){}
  try{if(typeof rebuildLaunchers==='function')rebuildLaunchers()}catch(e){}
}
/* What Settings says at the top of a Zero's panes */
function zeroSettingsNote(){
  if(!zeroFace())return '';
  return `<div class="zero-note"><b>This machine is a Zero of ${esc(zeroHub())}.</b>
    Its agent thinks on ${esc(zeroHub())}, and its memory and integrations live there.
    Mail, channels and MCP servers are set up on ${esc(zeroHub())}, in the account it belongs to.</div>`;
}
