/* ================= users: several people on one machine =================
   Three screens in one app, and which you get depends on who you are:

     - a machine with nobody added   → the offer, and what it will cost you
     - an admin                      → the roster, roles, and sign-out
     - an executor                   → their own account, and sign-out

   The offer screen is the important one. Turning multi-user on is the single
   most consequential switch in this OS — it ends loopback trust, so from that
   moment the person at the keyboard has to sign in — and it is irreversible in
   the sense that matters: everything already on the machine becomes the first
   account's. So it says all of that, in sentences, before the button.

   Sharing lives here too rather than in the Store, because it is the only place
   data crosses between people and it should be read next to the isolation it is
   the exception to.

   `var`, not `let`: one concatenated bundle, and the menu bar reads USERS at
   boot before this file's line is reached. See CLAUDE.md on the TDZ trap. */
var USERS={me:null,list:[],roles:['admin','executor'],shared:[],busy:false};

async function usersLoad(){
  try{
    const [u,s]=await Promise.all([
      fetch('/api/users').then(r=>r.ok?r.json():{users:[],me:{}}),
      fetch('/api/shared').then(r=>r.ok?r.json():{shared:[]}),
    ]);
    USERS.me=u.me||{};USERS.list=u.users||[];USERS.roles=u.roles||USERS.roles;
    USERS.shared=s.shared||[];
  }catch(e){}
  return USERS;
}

/* Who you are, in the power menu. Nothing at all on a single-user machine: a
   label saying who you are is noise when there is only one answer, and a "sign
   out" button there would lock somebody out of their own laptop with no account
   to sign back in as. */
async function usersBoot(){
  try{
    const d=await (await fetch('/api/users/who')).json();
    USERS.me=d||{};
    if(!d||!d.multiuser)return;
    const who=document.getElementById('pm-user'),
          out=document.getElementById('pm-signout'),
          hr=document.getElementById('pm-userhr');
    if(who){who.textContent=(d.display||d.name)+(d.admin?' · admin':'');who.hidden=false}
    if(out)out.hidden=false;
    if(hr)hr.hidden=false;
  }catch(e){}
}

async function renderUsers(body,w){
  const pb=panelShell(body,{title:'Users',sub:'Who can use this machine'});
  pb.innerHTML='<div class="dim">…</div>';
  await usersLoad();
  const me=USERS.me||{};
  pb.innerHTML=(me.multiuser?usersRoster():usersOffer())+usersShareBox();
  usersWire(pb,w);
}

/* ---- before anybody has been added ---------------------------------------- */

function usersOffer(){
  return `<div class="usr-offer">
    <div class="usr-mark">◱</div>
    <b>This machine has one user: you.</b>
    <p>Everything — memory, agents, flows, channels, credentials, the gallery —
      lives in one home directory, and anyone at this keyboard is you.</p>
    <p>Adding people gives each of them their own home: their own database, their
      own channels, their own MCP servers and credentials, their own permissions.
      Two files cannot leak into each other, so the isolation is not a query
      somebody has to remember to write.</p>
    <div class="usr-note">
      <b>Three things happen the moment you add the first account.</b>
      <ul>
        <li>Everything already on this machine becomes <em>that</em> account's —
          your agents, your conversations, your linked phone. Nothing is lost and
          nothing is copied to anybody else.</li>
        <li>This desktop starts asking who you are. Being at the keyboard stops
          being an identity, because there is now more than one identity.</li>
        <li>The first account is an admin, whatever you pick — a machine whose only
          account cannot administer it is a machine nobody can administer.</li>
      </ul>
    </div>
    <p class="dim">Settings stay shared: one set of provider keys for the machine,
      not one per person. Agents and apps can be shared deliberately, as copies.</p>
    ${usersForm('Create the first account',true)}
  </div>`;
}

/* ---- the roster ----------------------------------------------------------- */

function usersRoster(){
  const me=USERS.me||{};
  const rows=USERS.list.map(u=>{
    const isMe=u.id===me.id;
    return `<div class="usr-row${isMe?' me':''}" data-f="${esc(u.name+' '+u.role)}">
      <span class="usr-av">${esc((u.display||u.name||'?').slice(0,1).toUpperCase())}</span>
      <span class="usr-who"><b>${esc(u.display||u.name)}</b>
        <em>${esc(u.name)}${isMe?' · this is you':''}</em></span>
      ${me.admin&&!isMe
        ? `<select class="usr-role" data-uid="${esc(u.id)}">${USERS.roles.map(r=>
            `<option value="${esc(r)}"${r===u.role?' selected':''}>${esc(usersRoleName(r))}</option>`).join('')}</select>`
        : `<span class="usr-tag ${u.role==='admin'?'adm':''}">${esc(usersRoleName(u.role))}</span>`}
      <button class="usr-pw" data-uid="${esc(u.id)}">Password…</button>
      ${me.admin&&!isMe?`<button class="usr-del danger" data-uid="${esc(u.id)}"
        data-name="${esc(u.name)}">Remove</button>`:''}
    </div>`;
  }).join('');
  return `<div class="usr-roster">
    <div class="usr-head">
      <span><b>${USERS.list.length}</b> ${USERS.list.length===1?'account':'accounts'}</span>
      <span class="sp"></span>
      <button class="usr-out" id="usr-signout">Sign out</button>
    </div>
    ${rows}
    ${(USERS.me||{}).admin?`<details class="usr-add"><summary>Add somebody</summary>
      ${usersForm('Add the account',false)}</details>`
      :`<p class="dim usr-foot">Only an admin can add or remove accounts. Everything
        inside your own home — agents, flows, channels, credentials — is yours.</p>`}
  </div>`;
}

function usersRoleName(r){
  return r==='admin'?'Admin':'Executor';
}

/* One form, both places. Two roles and one sentence each — this is the entire
   permission model, and a grid of checkboxes would imply one that does not
   exist. Grants already answer "what may this principal do" in far more detail
   than a role could, and they are per user because the table is. */
function usersForm(cta,first){
  return `<form class="usr-form" id="usr-form" autocomplete="off">
    <label><span>Username</span>
      <input id="usr-name" placeholder="ada" autocapitalize="none" spellcheck="false"></label>
    <label><span>Display name</span>
      <input id="usr-display" placeholder="Ada Lovelace"></label>
    <label><span>Password</span>
      <input id="usr-pass" type="password" placeholder="at least 8 characters"
        autocomplete="new-password"></label>
    ${first?'':`<div class="usr-roles">
      <label class="usr-pick"><input type="radio" name="usr-role" value="executor" checked>
        <b>Executor</b><em>Everything inside their own home: agents, flows, jobs, apps,
          channels, MCP, credentials, permissions.</em></label>
      <label class="usr-pick"><input type="radio" name="usr-role" value="admin">
        <b>Admin</b><em>All of that, plus the machine: accounts, providers and models,
          components, remote access.</em></label></div>`}
    <div class="usr-go"><button class="wiz-next" id="usr-save">${esc(cta)}</button>
      <span class="usr-msg" id="usr-msg"></span></div>
  </form>`;
}

/* ---- sharing: the one place data crosses ---------------------------------- */

function usersShareBox(){
  const me=USERS.me||{};
  if(!me.multiuser)return '';
  const items=USERS.shared.length?USERS.shared.map(s=>`
    <div class="usr-share" data-f="${esc(s.name+' '+s.kind)}">
      <span class="usr-kind">${s.kind==='app'?'▤':'◇'}</span>
      <span class="usr-who"><b>${esc(s.name)}</b><em>${esc(s.kind)} · shared by ${esc(s.by||'somebody')}</em></span>
      <button class="usr-take" data-kind="${esc(s.kind)}" data-slug="${esc(s.slug)}">Install a copy</button>
      <button class="usr-unshare" data-kind="${esc(s.kind)}" data-slug="${esc(s.slug)}">Remove</button>
    </div>`).join('')
    :`<p class="dim">Nothing shared yet. Share an agent from Workflows, or an app
       from App Studio — it goes out as a <b>copy</b>, so editing yours afterwards
       never reaches anybody who took it.</p>`;
  return `<div class="usr-shared">
    <div class="usr-head"><span><b>Shared library</b></span></div>
    <p class="dim">The one place anything crosses between accounts, and it crosses
      as a copy. A shared app that changed under the people using it would be a
      supply-chain problem living in a filesystem.</p>
    ${items}</div>`;
}

/* ---- wiring --------------------------------------------------------------- */

function usersWire(pb,w){
  const form=pb.querySelector('#usr-form');
  if(form)form.onsubmit=e=>{e.preventDefault();usersCreate(pb,w)};
  const out=pb.querySelector('#usr-signout');
  if(out)out.onclick=()=>usersSignOut();

  pb.querySelectorAll('.usr-role').forEach(sel=>{
    sel.onchange=async()=>{
      const r=await usersPut(sel.dataset.uid,{role:sel.value});
      if(r.error){toast(r.error);}
      else toast('✓ role changed');
      renderUsers(w?w.el.querySelector('.wbody'):pb.closest('.wbody')||pb,w);
    };
  });
  pb.querySelectorAll('.usr-pw').forEach(b=>{
    b.onclick=async()=>{
      const pw=await osPrompt('New password',{message:'At least 8 characters.',
        placeholder:'••••••••',password:true,confirmText:'Change it'});
      if(!pw)return;
      const r=await usersPut(b.dataset.uid,{password:pw});
      toast(r.error||'✓ password changed');
    };
  });
  pb.querySelectorAll('.usr-del').forEach(b=>{
    b.onclick=async()=>{
      // Two decisions, asked as two: removing somebody's access and destroying
      // what they made are not the same thing, and one mis-click must not make
      // them one.
      if(!await osConfirm(`Remove ${b.dataset.name}?`,
        'Their home directory is kept — their agents, memory and files stay on this '+
        'machine and can be handed back by recreating the account.',
        {confirmText:'Remove the account',danger:true}))return;
      const r=await (await fetch('/api/users/'+encodeURIComponent(b.dataset.uid),
        {method:'DELETE'})).json();
      toast(r.error||'✓ account removed — their files are still on this machine');
      renderUsers(w?w.el.querySelector('.wbody'):pb,w);
    };
  });
  pb.querySelectorAll('.usr-take').forEach(b=>{
    b.onclick=async()=>{
      const r=await (await fetch('/api/shared/take',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({kind:b.dataset.kind,slug:b.dataset.slug})})).json();
      toast(r.error||`✓ installed as "${r.installed}" — it is yours now, editing it changes only your copy`);
    };
  });
  pb.querySelectorAll('.usr-unshare').forEach(b=>{
    b.onclick=async()=>{
      const r=await (await fetch(`/api/shared/${encodeURIComponent(b.dataset.kind)}/${encodeURIComponent(b.dataset.slug)}`,
        {method:'DELETE'})).json();
      if(r.error)return toast(r.error);
      renderUsers(w?w.el.querySelector('.wbody'):pb,w);
    };
  });
}

async function usersPut(uid,patch){
  try{
    return await (await fetch('/api/users/'+encodeURIComponent(uid),{method:'PUT',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)})).json();
  }catch(e){return {error:String(e)}}
}

async function usersCreate(pb,w){
  if(USERS.busy)return;
  const msg=pb.querySelector('#usr-msg'),btn=pb.querySelector('#usr-save');
  const body={name:(pb.querySelector('#usr-name')||{}).value||'',
              display:(pb.querySelector('#usr-display')||{}).value||'',
              password:(pb.querySelector('#usr-pass')||{}).value||'',
              role:(pb.querySelector('input[name=usr-role]:checked')||{}).value||'executor'};
  const first=!(USERS.me||{}).multiuser;
  if(first&&!await osConfirm('Turn on accounts for this machine?',
      'Everything already here becomes your account. From now on this desktop asks '+
      'who you are, at the keyboard as well as from a phone — so do not forget this '+
      'password.',{confirmText:'Create the account'}))return;
  USERS.busy=true;btn.disabled=true;msg.textContent='';
  try{
    const r=await fetch('/api/users',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json().catch(()=>({}));
    if(!r.ok){msg.textContent=d.error||'could not create the account';msg.className='usr-msg warn';return}
    toast(d.signed_in?'✓ accounts are on — you are signed in as '+body.name
                     :'✓ '+body.name+' can sign in now');
    usersBoot();   // the power menu now has a name to show and a way out
    renderUsers(w?w.el.querySelector('.wbody'):pb,w);
  }catch(e){msg.textContent=String(e);msg.className='usr-msg warn';}
  finally{USERS.busy=false;btn.disabled=false}
}

async function usersSignOut(){
  if(!await osConfirm('Sign out?','Anything running keeps running — it belongs to '+
    'your account, not to this window.',{confirmText:'Sign out'}))return;
  try{await fetch('/api/users/logout',{method:'POST'})}catch(e){}
  location.replace('/login');
}

/* Share something of mine. Called from Workflows (an agent) and App Studio (an
   app), so the sentence about what sharing means is written once, here. */
async function usersShare(kind,name){
  if(!(USERS.me||{}).multiuser){
    toast('sharing needs more than one account — add somebody in Users first');
    return false;
  }
  if(!await osConfirm(`Share "${name}" with everybody on this machine?`,
    'They get a COPY. Changing yours afterwards does not change theirs, and '+
    'nothing else of yours becomes visible.',{confirmText:'Share a copy'}))return false;
  const r=await (await fetch('/api/shared',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({kind,name})})).json();
  toast(r.error||`✓ "${name}" is in the shared library`);
  return !r.error;
}
