/* ================= Share this agent / fork another ================= */
/* The GUI face of `bento agent`. It lives inside Settings → Agent because that
   page already answers "who is my agent" — sharing it and forking somebody
   else's are the same question in both directions.

   Every decision on this screen is made by agentos/agentbundle.py — the
   whitelist export, the leak scan, the verify, the preview, the fork. Nothing
   here computes any of it: the report shown IS the bundle built (one
   computation), and the consent screen IS what fork() re-derives.

   Three faces:
     GUI  this — fetch + a form, no compositor, no root.
     TUI  `bento agent share|show|fork|verify` is the same module, and where a
          headless box publishes from.
     SUI  identical to GUI: a page, no native process.

   The two sentences that must survive any redesign of this pane:
     · nothing key-shaped leaves — a leak finding REFUSES the share, with no
       override control, because a shared credential cannot be unshared;
     · a fork writes ZERO permissions — everything lands disabled, and enabling
       each flow later is the act of granting. */

var AGS_BUNDLE = null;      /* the last built bundle, held for Download */
var AGS_FORKPV = null;      /* the last fork preview, held for the Fork click */
var AGS_FORKSRC = '';

async function renderAgentShare(){
  const box = document.getElementById('agent-share-box');
  if(!box) return;
  let d = null;
  try{ d = await (await fetch('/api/agent/shareables')).json() }catch(e){}
  if(!d){ box.innerHTML = '<div class="pgroup"><h3>Share this agent</h3><div class="ghint mut">could not read what this agent has to share</div></div>'; return }
  const apps = (d.apps||[]).map(a =>
    `<label class="ck" style="margin-right:10px"><input type="checkbox" class="ags-app"
       value="${esc(a.name)}"> ${esc(a.icon||'')} ${esc(a.name)}</label>`).join('') ||
    '<span class="mut">no apps to ship</span>';
  const sign = d.can_sign
    ? `<label class="ck"><input type="checkbox" id="ags-sign"> sign it with this machine's key</label>`
    : `<span class="mut">unsigned, which is fine for your own shares ${pInfo('Run bento registry keygen on this machine to sign what you share.')}</span>`;
  /* Three cards for three intentions: send a copy, serve it live, take somebody
     else's. They were one card with two headings inside it, and the switches were
     bare checkboxes beside text that ran into the card's edge. */
  box.innerHTML = `<div class="pgroup"><h3>Share this agent</h3>
    <div class="ghint">Pack ${esc(d.agent_name)}'s ${d.skills.length} skill(s), ${d.subagents.length} teammate(s),
      ${d.flows.length} flow(s) and ${d.mcp_servers.length} MCP server setup(s) into one file anyone can fork.
      ${pInfo("Your memory, conversations, knowledge graph, keys and secrets stay here. If a credential turns up in the bundle, the share stops, and there's no override.")}</div>
    <div class="prow"><input id="ags-name" placeholder="a name for it (default: ${esc(d.agent_name)})"
        autocomplete="off" class="ags-grow">
      <input id="ags-desc" placeholder="one sentence on what it is for" autocomplete="off" class="ags-grow"></div>
    ${pRow('Apps to include',`<div class="ags-apps">${apps}</div>`,{stack:true,desc:'Tick each one. Apps often hold something personal.',f:'share apps include'})}
    ${pRow('Include the soul',pSwitch('ags-soul',false),{desc:d.has_soul?'Its persona travels with the bundle.':'None written yet.',f:'share soul'})}
    <div class="prow"><div class="pl">${d.can_sign?sign:`<small>${sign}</small>`}</div>
      <div class="pc"><button class="endbtn" onclick="agsShare()">Build the bundle</button></div></div>
    <div id="ags-report"></div></div>
    <div class="pgroup" data-f="host share agent live key peer"><h3>Host it</h3>
    <div class="ghint">Let people you give a key to take the latest version from this machine.
      ${pInfo("A published file is a copy they keep. Hosting logs every take, runs the leak scan each time, and ends when you revoke their key.")}</div>
    <div id="ags-host"><div class="ghint mut">checking…</div></div></div>
    <div class="pgroup" data-f="fork shared agent import"><h3>Fork a shared agent</h3>
    <div class="ghint">Paste a URL, <code>owner/repo</code> or a file, read what's inside, then fork it.
      ${pInfo(`Look for ${d.well_known} files under the GitHub topic ${d.topic}. A fork grants no permissions: flows and MCP servers arrive switched off, and nothing of yours is overwritten.`)}</div>
    <div class="prow">
      <input id="ags-src" placeholder="owner/repo · https://… · ${esc(d.well_known)}" autocomplete="off" class="ags-grow">
      <input id="ags-key" placeholder="peer key, if hosted" autocomplete="off" class="ags-key">
      <button class="endbtn" onclick="agsPreview()">Read it first</button>
      <label class="endbtn" style="cursor:pointer">From a file<input type="file" accept=".json"
        style="display:none" onchange="agsFromFile(this)"></label>
    </div>
    <div class="ghint mut">Only add a key if the agent is hosted on another machine. ${pInfo('Use its http://host:port address. You get their live version, and they can end it at any time.')}</div>
    <div id="ags-fork"></div></div>`;
  renderAgsHost();
}

async function renderAgsHost(){
  const box = document.getElementById('ags-host');
  if(!box) return;
  let d = null;
  try{ d = await (await fetch('/api/agent/host')).json() }catch(e){}
  if(!d){ box.innerHTML = '<div class="ghint mut">could not read the hosting state</div>'; return }
  const peers = (d.peers||[]).map(p => {
    const st = p.revoked ? '<span class="badge err">revoked</span>'
             : p.expires_at ? `<span class="badge">expires ${new Date(p.expires_at*1000).toLocaleDateString()}</span>`
             : '<span class="badge ok">live</span>';
    const last = p.last_fetch ? new Date(p.last_fetch*1000).toLocaleString() : 'never';
    return `<div class="item"><div class="grow"><b>${esc(p.name)}</b>
        <span class="mut"> last take: ${esc(last)}</span></div>${st}
      ${p.revoked?'':`<button class="endbtn" onclick="agsRevokePeer('${esc(p.name)}')">Revoke</button>`}
    </div>`;
  }).join('');
  box.innerHTML = `
    ${pRow('Host my share',`<label class="psw"><input type="checkbox" id="ags-host-on" ${d.enabled?'checked':''}
        onchange="agsHostToggle(this.checked)"><i></i></label>`,
      {desc:`At <code>${esc(d.endpoint)}</code>`,more:d.reachability,f:'host share endpoint'})}
    ${d.enabled && d.remote===false?`<div class="ghint" style="color:var(--warn)">${esc(d.reachability)}</div>`:''}
    <div class="prow">
      <input id="ags-peer-name" placeholder="who gets a key? e.g. laptop-b, priya" autocomplete="off" class="ags-grow">
      <button class="endbtn" onclick="agsMintPeer()">Mint a key</button>
    </div>
    <div id="ags-peer-key"></div>
    ${peers || '<div class="ghint mut">Nobody holds a key yet.</div>'}`;
}

async function agsHostToggle(on){
  try{ await fetch('/api/agent/host', {method:'PUT', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({enabled: !!on})}) }catch(e){}
  renderAgsHost();
}

async function agsMintPeer(){
  const name = ((document.getElementById('ags-peer-name')||{}).value||'').trim();
  if(!name){ toast('Who is this key for? Give a short name'); return }
  let d = null;
  try{
    d = await (await fetch('/api/agent/peers', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({name})})).json();
  }catch(e){}
  if(!d || d.error){ toast((d&&d.error)||'minting failed'); return }
  /* Shown ONCE, here — it is never readable again, so the person hands it over
     themselves rather than this OS remembering it for anyone who asks later.
     The list re-render runs first, then the key lands in the fresh box. */
  await renderAgsHost();
  const box = document.getElementById('ags-peer-key');
  if(box) box.innerHTML = `<div class="ghint" style="border-color:var(--warn)"><b>Key for
      ${esc(name)}. It's shown only once, so pass it on yourself:</b>
    <pre style="user-select:all">${esc(d.key)}</pre>
    <div class="sub mut">They can paste it into the Fork box on their machine, or run
      <code>bento agent fork http://&lt;this-host&gt; --key &lt;key&gt; --yes</code></div></div>`;
}

async function agsRevokePeer(name){
  if(!confirm(`Stop sharing with '${name}'? Their key and its permission are removed together.`)) return;
  try{ await fetch('/api/agent/peers/' + encodeURIComponent(name), {method:'DELETE'}) }catch(e){}
  renderAgsHost();
}

async function agsShare(){
  const out = document.getElementById('ags-report');
  out.innerHTML = '<p class="mut">building…</p>';
  const apps = Array.from(document.querySelectorAll('.ags-app:checked')).map(x=>x.value);
  let r = null, d = null;
  try{
    r = await fetch('/api/agent/share', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({name: (document.getElementById('ags-name')||{}).value||'',
                            description: (document.getElementById('ags-desc')||{}).value||'',
                            apps: apps.length?apps:'none',
                            with_soul: !!(document.getElementById('ags-soul')||{}).checked,
                            sign: !!(document.getElementById('ags-sign')||{}).checked})});
    d = await r.json();
  }catch(e){}
  if(!d){ out.innerHTML = '<p class="mut">the share failed. Is the server reachable?</p>'; return }
  if(d.error){
    /* The refusal, with each finding named. Deliberately no way onward from
       here except fixing it — the one control that must not exist. */
    const leaks = (d.leak||[]).map(f =>
      `<div class="sub" style="color:var(--err)">· ${esc(f.looks_like)} at line ${f.line} (starts ${esc(f.excerpt)})</div>`).join('');
    out.innerHTML = `<div class="ghint" style="border-color:var(--err)"><b>Not shared.</b>
      ${esc(d.error)}${leaks}</div>`;
    AGS_BUNDLE = null;
    return;
  }
  AGS_BUNDLE = {bundle: d.bundle, filename: d.filename};
  const t = d.report.traveled;
  const withheld = d.report.withheld.map(w=>`<div class="sub mut">· ${esc(w)}</div>`).join('');
  const soul = d.report.soul_text
    ? `<div class="ghint" style="border-color:var(--warn)"><b>The soul travels with this.</b>
        Read it as a stranger will:<pre style="white-space:pre-wrap">${esc(d.report.soul_text)}</pre></div>`
    : '';
  out.innerHTML = `<div class="ghint"><b>Built.</b> Travels: ${t.skills} skill(s),
      ${t.subagents} teammate(s), ${t.flows} flow(s) (all disabled),
      ${t.apps.length} app(s)${t.apps.length?` (${esc(t.apps.join(', '))})`:''},
      ${t.mcp_servers.length} MCP shape(s)${t.soul?', the soul':''}.
      Leak scan: <span class="badge ok">clean</span>
      ${d.bundle.signature?'<span class="badge ok">signed</span>':'<span class="badge">unsigned</span>'}
      <div style="margin-top:6px">${withheld}</div>
      <div class="prow" style="margin-top:6px">
        <button class="endbtn" onclick="agsDownload()">Download ${esc(d.filename)}</button>
        <span class="mut">to publish, commit it to a repo and add the topic</span>
      </div></div>${soul}`;
}

function agsDownload(){
  if(!AGS_BUNDLE) return;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(AGS_BUNDLE.bundle, null, 2)],
                                        {type:'application/json'}));
  a.download = AGS_BUNDLE.filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

function agsFromFile(input){
  const f = input.files && input.files[0];
  if(!f) return;
  const rd = new FileReader();
  rd.onload = () => {
    try{ agsPreview(JSON.parse(rd.result), f.name) }
    catch(e){ toast('that file is not a bundle: ' + e) }
  };
  rd.readAsText(f);
}

async function agsPreview(bundle, label){
  const out = document.getElementById('ags-fork');
  const src = bundle ? '' : ((document.getElementById('ags-src')||{}).value||'').trim();
  if(!bundle && !src){ toast('Where is the shared agent? A URL, owner/repo, or a file'); return }
  out.innerHTML = '<p class="mut">reading it…</p>';
  const pkey = ((document.getElementById('ags-key')||{}).value||'').trim();
  let d = null;
  try{
    d = await (await fetch('/api/agent/fork/preview', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(bundle?{bundle}:{source:src, key:pkey})})).json();
  }catch(e){}
  if(!d){ out.innerHTML = '<p class="mut">could not read it</p>'; return }
  if(d.error){ out.innerHTML = `<div class="ghint" style="border-color:var(--err)">${esc(d.error)}</div>`; return }
  AGS_FORKPV = bundle || null;   /* inline bundle is re-sent; a source is re-fetched */
  AGS_FORKSRC = src;
  const bad = d.verify.status==='checksum-mismatch' || d.verify.status==='bad-signature';
  const vb = d.verify.status==='verified' ? 'ok' : bad ? 'err' : '';
  const items = d.items.map(i =>
    `<div class="sub ${i.skipped?'mut':''}">· ${esc(i.kind)}: <b>${esc(i.name)}</b>${i.skipped?`, ${esc(i.note)}`:''}</div>`).join('');
  const ceil = (d.permissions_ceiling||[]).map(g =>
    `<div class="sub mut">· ${esc(g.principal_kind)}:${esc(g.principal_id)} may ${esc(g.action)}${g.resource?` on ${esc(g.resource)}`:''}</div>`).join('');
  const needs = (d.mcp_needs||[]).filter(m=>m.fill.length).map(m =>
    `<div class="sub mut">· '${esc(m.name)}' will need you to fill: ${esc(m.fill.join(', '))}</div>`).join('');
  const soul = d.soul_included
    ? `<div class="ghint" style="border-color:var(--warn)"><b>A soul is included.</b> Your agent keeps its own identity unless you tick this.
        <label class="ck"><input type="checkbox" id="ags-adopt"> adopt it as my agent's identity</label>
        <pre style="white-space:pre-wrap">${esc(d.soul_text)}</pre></div>` : '';
  out.innerHTML = `<div class="ghint">
      <b>${esc(d.name)}</b>${d.description?`: ${esc(d.description)}`:''}
      <div class="sub">integrity: <span class="badge ${vb}">${esc(d.verify.status)}</span> ${esc(d.verify.note)}</div>
      <div class="sub">provenance: <span class="badge ${d.tofu.status==='changed-key'?'err':''}">${esc(d.tofu.status)}</span> ${esc(d.tofu.note)}</div>
      <div class="sub">app scan: ${esc(d.security.verdict)}</div>
      <div style="margin-top:6px">${items}</div>
      <div class="sub" style="margin-top:6px"><b>Permissions granted by the fork:
        ${d.grants_written_now}.</b> Turning on each flow later grants its part. If you turned everything on, it could:</div>${ceil || '<div class="sub mut">· nothing, since no flows ask for permissions</div>'}
      ${needs}
      ${bad?`<div class="sub" style="color:var(--err)">This can't be forked because the file was changed after it was shared.</div>`
           :`<div class="prow" style="margin-top:6px"><button class="endbtn" onclick="agsFork()">Fork it, switched off</button></div>`}
    </div>${soul}`;
}

async function agsFork(){
  const out = document.getElementById('ags-fork');
  const body = AGS_FORKPV ? {bundle: AGS_FORKPV}
             : {source: AGS_FORKSRC,
                key: ((document.getElementById('ags-key')||{}).value||'').trim()};
  body.adopt_soul = !!(document.getElementById('ags-adopt')||{}).checked;
  let d = null;
  try{
    d = await (await fetch('/api/agent/fork', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})).json();
  }catch(e){}
  if(!d){ toast('the fork failed. Is the server reachable?'); return }
  if(d.error){ out.innerHTML = `<div class="ghint" style="border-color:var(--err)">${esc(d.error)}</div>`; return }
  out.innerHTML = agsArrivalHTML(d);
}

/* The moment after a fork, drawn the same wherever the fork happened (Settings,
   the setup wizard). The content is the server's `arrival` — ONE computation —
   so this only lays it out: what changed, what did not, and the door into chat
   to actually test the thing. */
function agsArrivalHTML(d){
  const arr = d.arrival || {changed:[], unchanged:[], try_message:''};
  const changed = arr.changed.map(c =>
    `<div class="sub">· <b>${esc(c.kind)}</b>: ${esc(c.names.join(', '))}${c.note?`, ${esc(c.note)}`:''}</div>`).join('')
    || '<div class="sub mut">· nothing, every name already existed here</div>';
  const unchanged = arr.unchanged.map(u=>`<div class="sub mut">· ${esc(u)}</div>`).join('');
  return `<div class="ghint"><b>It arrived.</b> ${d.created.length} thing(s) created,
      ${d.skipped.length} skipped, <b>${d.grants_written} permission(s) granted</b>.${d.soul?`<div class="sub">soul: ${esc(d.soul)}</div>`:''}
      <div style="margin-top:8px"><b>What changed:</b>${changed}</div>
      <div style="margin-top:8px"><b>What did not:</b>${unchanged}</div>
      <div class="prow" style="margin-top:8px">
        <button class="endbtn" onclick='agsTestChat(${JSON.stringify(arr.try_message||'')})'>
          Test it in Chat</button>
        <span class="mut">the question is filled in, press Enter to send it</span>
      </div>
      <div class="sub mut" style="margin-top:6px">${esc(d.next||'')}</div></div>`;
}

function agsTestChat(msg){
  /* Prefilled, never auto-sent — the testSubagent pattern: the first message a
     forked agent receives should still be one its new owner chose to send. */
  openApp('chat');
  setTimeout(()=>{const i=$('#input');
    if(i){i.value=msg||'';i.focus();i.dispatchEvent(new Event('input'))}},250);
}
