/* ================= Websites: the sites your agent uses in your browser, signed in as you ======
   The shared browser (cdpbrowser) keeps a sign-in as cookies in this account's own profile; this
   card lists which sites have been signed in to (GET /api/sites), opens a new one for you to sign
   in (POST /api/sites/signin: the Web window shows it), and signs the browser out of one (Forget).
   A mission names its sites in permissions.sites and the consent screen says whether each is
   signed in. Faces — GUI and SUI: this card. TUI: `bento sites`. Phone: a mission that meets a
   sign-in with nobody at a screen asks on the owner's Telegram or WhatsApp (cdpbrowser.tool_wait).
   `var`, not `let`: the bundle's TDZ trap. */
var SITES={list:[],browser:null,busy:''};

async function renderSites(){
  const box=document.getElementById('site-list');if(!box)return;
  let d={};try{d=await apiJSON('/api/sites')}catch(e){box.innerHTML=`<p class="mut">${esc(e.message||'could not read the sites')}</p>`;return}
  SITES.list=d.sites||[];SITES.browser=d.browser||{};
  const ok=SITES.browser.ok!==false;
  const rows=SITES.list.map(r=>{
    const when=new Date((+r.last||0)*1000).toLocaleDateString(undefined,{day:'numeric',month:'short'});
    return `<div class="prow" data-f="website ${esc(r.site)}"><div class="pl"><b>${esc(r.site)}</b>
      <small class="mut">signed in · last seen ${esc(when)}${r.warn?' '+pInfo(r.warn):''}</small></div>
      <div class="pc"><button class="endbtn" onclick="sitesForget('${jsq(r.site)}')">Forget</button></div></div>`;
  }).join('')||`<div class="ghint">No websites yet. Sign in to one below, or ask your agent to log in to it.</div>`;
  box.innerHTML=`<div class="pgroup chan" data-f="websites browser signed in instagram linkedin portal login">
    <h3>Websites</h3>
    <div class="ghint">Sites your agent and your missions use in your browser, signed in as you. ${pInfo('The sign-in stays in your browser on this machine. Your agent never sees the password. Posting or sending on a site asks you first unless a mission was set to post on its own.')}</div>
    ${rows}
    <div class="prow"><div class="pl"><b>Sign in to a site</b><small>${ok?'It opens in the Web window, for you to sign in.':esc(SITES.browser.why||'The shared browser can’t run here.')}</small></div>
      <div class="pc sites-add"><input id="sites-new" placeholder="instagram.com" spellcheck="false" autocomplete="off" ${ok?'':'disabled'}>
      <button class="endbtn" id="sites-go" ${ok?'':'disabled'} onclick="sitesSignIn()">Sign in</button></div></div>
  </div>`;
  const inp=document.getElementById('sites-new');if(inp)inp.onkeydown=e=>{if(e.key==='Enter')sitesSignIn()};
}

/* the page's sign-in: the server opens the site in the shared browser and the Web window shows
   it here. The card repaints when the sign-in is recorded (the `sites` event). */
async function sitesSignIn(site){
  site=String(site||((document.getElementById('sites-new')||{}).value)||'').trim();
  if(!site){toast('Type the site, like instagram.com');return}
  try{
    const j=await apiJSON('/api/sites/signin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({site})});
    if(typeof openApp==='function')openApp('browser');
    toast(`Sign in to ${j.site} in the Web window. I’ll remember it once you’re in.`);
    if(j.warn)setTimeout(()=>toast(j.warn,{kind:'warn'}),600);
  }catch(e){toast(e.message||'could not open it')}
}

async function sitesForget(site){
  const ask=`Sign your browser out of ${site}? Missions that use it will ask you to sign in again.`;
  if(typeof osConfirm==='function'?!(await osConfirm(ask)):!confirm(ask))return;
  try{await apiJSON('/api/sites/forget',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({site})});
    toast(`Signed out of ${site}`);renderSites()}catch(e){toast(e.message||'could not reach the server')}
}
