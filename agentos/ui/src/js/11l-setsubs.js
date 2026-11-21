/* ---------------- Settings: sub-sections, and keeping your place ----------------
   Asked for as "all the confusion in the settings is so much messed up, we need sub settings
   if need be" and "when I am changing the settings it takes me to the top of the page".

   SUB-SECTIONS. A long tab is split into a row of sub-sections at its top, and only the chosen
   one is shown. Measured on a throwaway home before this: Agents was 9,774px tall, Channels
   3,923, System 2,744, AI providers 2,554. The split is by the cards' own titles (SETSUBS: a
   label and the title of the card it starts at), so a card added to a tab joins the section
   before it and nothing has to be moved in 11-settings.js. A section whose first card is not on
   the page (an admin's card for a non-admin) is not offered; fewer than two and there is no row.
   Searching shows every card of every tab, so the row goes away while a search is typed. The
   choice is per tab and per browser (localStorage, in a try).

   KEEPING YOUR PLACE. The whole window is drawn again by refreshApp('settings'), which many
   saves cause (an agent or a company changed broadcasts `avatars`; a theme or a scene; a
   company opened). innerHTML put the pane back at the top. The same tab drawn again now keeps
   its scroll position, the search being typed and the field with the caret; the position is
   held for a few seconds while the pieces painted later (lists fetched after the page) grow
   the pane, and given up the moment the person scrolls or types. Another tab starts at its top.

   GUI and SUI: this page. TUI: `bento config` and the verbs each card names; there is no pane to
   scroll. */
var SETSUBS={
  ai:[['In use','In use'],['Providers','Model providers'],['Installed agents','AI agents installed here'],['Images','Image generation'],['Video','Video'],['Voice','Voice']],
  agent:[['Lead agent','Lead agent'],['Models','Models'],['Huddles','Huddles and free talk'],['Your agents','Your agents'],['Map','The map'],['Sharing','Share this agent']],
  companies:[['About','About'],['Working together','Working together'],['Departments','Departments'],['Folders','Folders'],['Brief','In your Brief'],['New company','A new company']],
  network:[['Discovery','Discovery and linkage'],['Linked teams','Linked teams'],['Community','Community'],['Messages','Messages'],['Mapping','Team to agent mapping'],['Maps','Maps']],
  permissions:[['Autonomy','On their own'],['Ethics','Ethics'],['Security','Security'],['Ledger','The ledger']],
  channels:[['Authorization','Authorization'],['Approvals','Approvals'],['Overview','Ways to reach it'],['Remote browser','Remote browser'],['Telegram','Telegram'],['WhatsApp','WhatsApp'],['Built in','Built in']],
  accounts:[['Sign in','Sign in'],['Mail & calendar','Mail'],['Websites','Websites'],['App registration','App registration'],['Vault','Vault'],['GitHub','GitHub']],
  voice:[['Speech','Speech'],['Listening','Listening']],
  look:[['Look','Look'],['Characters','Characters'],['Office','Office'],['This screen','On this screen']],
  system:[['Version','Version'],['People','People'],['Setup','Footprint'],['Backup & cloud','Backup'],['Machine','Machine']],
};
function setSubKey(tab){return 'setsub.'+tab}
function setSubGet(tab){try{return localStorage.getItem(setSubKey(tab))||''}catch(e){return ''}}
function setSubSet(tab,label){try{localStorage.setItem(setSubKey(tab),label)}catch(e){}}
/* A card's title is its first heading: the card itself when it is a part heading
   (`h3.pgh`, `h3.net-part`, `h3.chsec`), or the first h3 inside it (a card's h3 may sit in a
   header row, and may carry a status after the name, which startsWith ignores). */
function setSubTitle(el){
  if(!el||!el.matches)return '';
  if(el.matches('h3'))return el.textContent;
  const h=el.querySelector('h3');
  return h?h.textContent:'';
}
/* What the split works on: the pane's children, with a wrapper that holds several titled
   cards opened up (`.set-subroot`, Channels' #chan-list, Accounts' #acct-list, the share box),
   so a section can start at any of its cards. A card is never opened up: `.pgroup` is a unit. */
function setSubUnits(main,bar){
  const out=[];
  const walk=(c,depth)=>{
    if(c===bar)return;
    const kids=[...c.children];
    const opens=c.classList.contains('set-subroot')||(depth<2&&c.tagName==='DIV'&&!c.classList.contains('pgroup')
      &&kids.filter(k=>k.matches('h3')||(k.classList.contains('pgroup')&&k.querySelector('h3'))).length>=2);
    if(opens)kids.forEach(k=>walk(k,depth+1));else out.push(c);
  };
  [...main.children].forEach(c=>walk(c,0));
  return out;
}
function setSubsApply(main){
  if(!main)return;
  const tab=main.dataset.tab||'',defs=SETSUBS[tab];
  let bar=main.querySelector(':scope > .set-subs');
  const clear=()=>{if(bar)bar.remove();main.querySelectorAll('.ssub-off').forEach(e=>e.classList.remove('ssub-off'))};
  if(!defs||main.classList.contains('searching'))return clear();
  const norm=t=>String(t||'').replace(/\s+/g,' ').trim().toLowerCase();
  const units=setSubUnits(main,bar),found=[],of=new Map();
  let cur=-1;
  units.forEach(u=>{
    const t=norm(setSubTitle(u));
    if(t){const i=defs.findIndex(d=>t.startsWith(d[1].toLowerCase()));
      if(i>=0&&!found.some(f=>f.i===i)){found.push({i,el:u,label:defs[i][0]});cur=i}}
    of.set(u,cur)});
  if(found.length<2)return clear();
  let sel=setSubGet(tab);
  if(!found.some(f=>f.label===sel))sel=found[0].label;
  const key=found.map(f=>f.label).join('|');
  if(!bar||bar.dataset.k!==key){
    if(bar)bar.remove();
    bar=document.createElement('nav');bar.className='set-subs';bar.dataset.k=key;
    bar.setAttribute('role','tablist');bar.setAttribute('aria-label','Sections of this page');
    found.forEach(f=>{const b=document.createElement('button');b.type='button';b.textContent=f.label;
      b.dataset.sub=f.label;b.setAttribute('role','tab');b.onclick=()=>setSubShow(f.label,true);bar.appendChild(b)});
    bar.onkeydown=e=>{if(e.key!=='ArrowRight'&&e.key!=='ArrowLeft')return;
      const bs=[...bar.querySelectorAll('button')],i=bs.indexOf(document.activeElement);if(i<0)return;
      const n=bs[(i+(e.key==='ArrowRight'?1:bs.length-1))%bs.length];n.focus();n.click();e.preventDefault()};
    // after the page's own heading and its line, before the first section
    let top=found[0].el;while(top.parentNode&&top.parentNode!==main)top=top.parentNode;
    main.insertBefore(bar,top);
  }
  // A wrapper that was a section's card when it held one titled card ("checking…") and is
  // opened up now that it holds several (the share box) is no longer a unit, so a hide it
  // was given then must go, or every card inside it stays hidden: Sharing showed nothing.
  main.querySelectorAll('.ssub-off').forEach(e=>{if(!of.has(e))e.classList.remove('ssub-off')});
  const selI=found.find(f=>f.label===sel).i;
  units.forEach(u=>{const s=of.get(u);
    u.classList.toggle('ssub-off',s>=0&&s!==selI);
    if(s>=0&&u.dataset.ssub!==defs[s][0])u.dataset.ssub=defs[s][0]});
  bar.querySelectorAll('button').forEach(b=>{const on=b.dataset.sub===sel;
    b.classList.toggle('on',on);b.setAttribute('aria-selected',on?'true':'false');b.tabIndex=on?0:-1});
}
/* Show one section by its label (a chip, or code that sends the person to a card). */
function setSubShow(label,fromChip){
  const main=document.getElementById('prefs-main');if(!main)return;
  setSubSet(main.dataset.tab||SETTAB,label);
  setSubsApply(main);
  if(fromChip){main.scrollTop=0;SETKEEP.until=0}
}
/* Before something scrolls a card into view: make sure its section is the one showing. */
function setSubReveal(el){
  const u=el&&el.closest&&el.closest('[data-ssub]');
  if(u&&u.classList.contains('ssub-off'))setSubShow(u.dataset.ssub);
}

var SETKEEP={want:0,until:0};
function setKeepTake(body){
  const m=body&&body.querySelector('#prefs-main');if(!m)return null;
  const a=document.activeElement,q=body.querySelector('#set-q');
  return {tab:m.dataset.tab||'',top:m.scrollTop,q:q?q.value:'',
    focus:a&&m.contains(a)&&a.id?a.id:'',
    sel:a&&typeof a.selectionStart==='number'?[a.selectionStart,a.selectionEnd]:null};
}
function setKeepGive(body,k){
  const m=body.querySelector('#prefs-main');if(!m||!k)return;
  if(k.q){const q=body.querySelector('#set-q');if(q){q.value=k.q;if(q.oninput)q.oninput()}return}
  if(k.tab&&k.tab===SETTAB&&k.top>0){SETKEEP.want=k.top;SETKEEP.until=Date.now()+4000;m.scrollTop=k.top}
  if(k.focus){const f=document.getElementById(k.focus);
    if(f&&m.contains(f))try{f.focus({preventScroll:true});if(k.sel&&f.setSelectionRange)f.setSelectionRange(k.sel[0],k.sel[1])}catch(e){}}
}
function setKeepSame(main,again){
  if(again&&main.scrollTop>0){SETKEEP.want=main.scrollTop;SETKEEP.until=Date.now()+4000}
  else if(!again){SETKEEP.want=0;SETKEEP.until=0;main.scrollTop=0}
}
function setKeepHold(main){
  if(!main||!SETKEEP.until||Date.now()>SETKEEP.until||!SETKEEP.want)return;
  if(Math.abs(main.scrollTop-SETKEEP.want)>2)main.scrollTop=SETKEEP.want;
}
function setKeepWatch(main){
  // the person scrolling or typing ends the hold at once: their place is wherever they are now
  ['wheel','touchstart','keydown'].forEach(t=>main.addEventListener(t,()=>{SETKEEP.until=0},{passive:true}));
}
