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
  if(!d){ box.innerHTML = '<p class="mut">could not read what this agent has to share</p>'; return }
  const apps = (d.apps||[]).map(a =>
    `<label class="ck" style="margin-right:10px"><input type="checkbox" class="ags-app"
       value="${esc(a.name)}"> ${esc(a.icon||'')} ${esc(a.name)}</label>`).join('') ||
    '<span class="mut">no apps to ship</span>';
  const sign = d.can_sign
    ? `<label class="ck"><input type="checkbox" id="ags-sign"> sign it with this machine's key</label>`
    : `<span class="mut">unsigned (fine for your own shares) — <code>bento registry keygen</code> would let you sign</span>`;
  box.innerHTML = `<h3>Share this agent</h3>
    <div class="ghint">Package what makes ${esc(d.agent_name)} <em>${esc(d.agent_name)}</em> —
      ${d.skills.length} skill(s), ${d.subagents.length} teammate(s), ${d.flows.length} flow(s)
      and the shapes of ${d.mcp_servers.length} MCP server(s) — into one file anyone can fork.
      What never travels: your memory, conversations, knowledge graph, and every key and
      secret. A credential found in the bundle refuses the share outright; there is no
      override, because a shared credential cannot be unshared.</div>
    <div class="prow"><input id="ags-name" placeholder="a name for it (default: ${esc(d.agent_name)})"
        autocomplete="off" style="flex:1">
      <input id="ags-desc" placeholder="one sentence on what it is for" autocomplete="off" style="flex:1"></div>
    <div class="prow"><div class="pl"><small>Ship apps with it? Each is a choice — an app is the
      piece most likely to have something personal built in.</small><div>${apps}</div></div></div>
    <div class="prow">
      <label class="ck"><input type="checkbox" id="ags-soul"> include the soul${d.has_soul?'':' <span class="mut">(none written yet)</span>'}</label>
      ${sign}
      <span class="grow"></span>
      <button class="endbtn" onclick="agsShare()">Build the bundle</button>
    </div>
    <div id="ags-report"></div>
    <h3 style="margin-top:14px">Fork a shared agent</h3>
    <div class="ghint">Point at a <code>${esc(d.well_known)}</code> — a URL, <code>owner/repo[@ref]</code>
      (discovery: GitHub topic <code>${esc(d.topic)}</code>), or a file. You read exactly what it
      contains and the permission ceiling enabling it all would reach, then fork. The fork
      writes <b>zero</b> permissions: every flow lands disabled, MCP servers land off with
      placeholder credentials for you to fill, and nothing of yours is overwritten.</div>
    <div class="prow">
      <input id="ags-src" placeholder="owner/repo · https://… · ${esc(d.well_known)}" autocomplete="off" style="flex:1">
      <button class="endbtn" onclick="agsPreview()">Read it first</button>
      <label class="endbtn" style="cursor:pointer">from a file<input type="file" accept=".json"
        style="display:none" onchange="agsFromFile(this)"></label>
    </div>
    <div id="ags-fork"></div>`;
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
  if(!d){ out.innerHTML = '<p class="mut">the share failed — is the server reachable?</p>'; return }
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
        <span class="mut">commit it to a repo and add the topic to publish</span>
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
  let d = null;
  try{
    d = await (await fetch('/api/agent/fork/preview', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(bundle?{bundle}:{source:src})})).json();
  }catch(e){}
  if(!d){ out.innerHTML = '<p class="mut">could not read it</p>'; return }
  if(d.error){ out.innerHTML = `<div class="ghint" style="border-color:var(--err)">${esc(d.error)}</div>`; return }
  AGS_FORKPV = bundle || null;   /* inline bundle is re-sent; a source is re-fetched */
  AGS_FORKSRC = src;
  const bad = d.verify.status==='checksum-mismatch' || d.verify.status==='bad-signature';
  const vb = d.verify.status==='verified' ? 'ok' : bad ? 'err' : '';
  const items = d.items.map(i =>
    `<div class="sub ${i.skipped?'mut':''}">· ${esc(i.kind)}: <b>${esc(i.name)}</b>${i.skipped?` — ${esc(i.note)}`:''}</div>`).join('');
  const ceil = (d.permissions_ceiling||[]).map(g =>
    `<div class="sub mut">· ${esc(g.principal_kind)}:${esc(g.principal_id)} may ${esc(g.action)}${g.resource?` on ${esc(g.resource)}`:''}</div>`).join('');
  const needs = (d.mcp_needs||[]).filter(m=>m.fill.length).map(m =>
    `<div class="sub mut">· '${esc(m.name)}' will need you to fill: ${esc(m.fill.join(', '))}</div>`).join('');
  const soul = d.soul_included
    ? `<div class="ghint" style="border-color:var(--warn)"><b>A soul is included.</b> It is NOT
        adopted unless you tick this — your agent keeps its own identity otherwise.
        <label class="ck"><input type="checkbox" id="ags-adopt"> adopt it as my agent's identity</label>
        <pre style="white-space:pre-wrap">${esc(d.soul_text)}</pre></div>` : '';
  out.innerHTML = `<div class="ghint">
      <b>${esc(d.name)}</b>${d.description?` — ${esc(d.description)}`:''}
      <div class="sub">integrity: <span class="badge ${vb}">${esc(d.verify.status)}</span> ${esc(d.verify.note)}</div>
      <div class="sub">provenance: <span class="badge ${d.tofu.status==='changed-key'?'err':''}">${esc(d.tofu.status)}</span> ${esc(d.tofu.note)}</div>
      <div class="sub">app scan: ${esc(d.security.verdict)}</div>
      <div style="margin-top:6px">${items}</div>
      <div class="sub" style="margin-top:6px"><b>Permissions written by the fork now:
        ${d.grants_written_now}.</b> Enabling each flow later is what grants — this is the
        ceiling if you enabled everything:</div>${ceil || '<div class="sub mut">· nothing — no flows declare permissions</div>'}
      ${needs}
      ${bad?`<div class="sub" style="color:var(--err)">This will not fork: the bytes are not what the sharer shared.</div>`
           :`<div class="prow" style="margin-top:6px"><button class="endbtn" onclick="agsFork()">Fork it — disabled, nothing granted</button></div>`}
    </div>${soul}`;
}

async function agsFork(){
  const out = document.getElementById('ags-fork');
  const body = AGS_FORKPV ? {bundle: AGS_FORKPV} : {source: AGS_FORKSRC};
  body.adopt_soul = !!(document.getElementById('ags-adopt')||{}).checked;
  let d = null;
  try{
    d = await (await fetch('/api/agent/fork', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})).json();
  }catch(e){}
  if(!d){ toast('the fork failed — is the server reachable?'); return }
  if(d.error){ out.innerHTML = `<div class="ghint" style="border-color:var(--err)">${esc(d.error)}</div>`; return }
  const made = d.created.map(c=>`<div class="sub">· ${esc(c.kind)}: ${esc(c.name)}</div>`).join('');
  const skip = d.skipped.map(s=>`<div class="sub mut">· ${esc(s.kind)}: ${esc(s.name)} — ${esc(s.note)}</div>`).join('');
  out.innerHTML = `<div class="ghint"><b>Forked.</b> ${d.created.length} thing(s) created,
      ${d.skipped.length} skipped, <b>${d.grants_written} permission(s) granted</b> — that
      number is the design.${d.soul?`<div class="sub">soul: ${esc(d.soul)}</div>`:''}
      <div style="margin-top:6px">${made}${skip}</div>
      <div class="sub" style="margin-top:6px">${esc(d.next)}</div></div>`;
}
