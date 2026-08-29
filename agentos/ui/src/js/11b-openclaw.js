/* ================= OpenClaw plugins ================= */
/* The GUI face of `bento openclaw`. It lives inside Settings → Executors on
   purpose: OpenClaw is an executor here, and its plugins are how you extend it,
   so putting them anywhere else would make somebody hunt for the extension
   surface of a thing they configured on another screen.

   Every decision on this screen is made by agentos/ocplugins.py — the scan, the
   capability sentences, the grants, the hold. Nothing here computes any of it,
   because the CLI and the agent read the same module and a second answer on one
   surface is how the three stop agreeing.

   Three faces:
     GUI  this. It needs no compositor and no root — it is fetch + a list.
     TUI  `bento openclaw` covers it, the same way `bento mcp` is the terminal
          face of the MCP pane. Install, scan, enable and hold are all there, and
          `bento openclaw doctor` is the one thing a headless box most needs.
     SUI  identical to GUI: this is a page, not a native window, and it starts no
          native process, so nothing here touches the compositor or the layer
          shell.

   The whole pane is inert when the `openclaw` CLI is absent: `available:false`
   comes back with a sentence and that sentence is ALL that renders. A row of
   buttons that answer a tap by doing nothing is the dead control the honesty
   rules forbid, and on a machine without OpenClaw every one of these would be. */

var OCP_BUSY = false;

function ocpVerdict(v){
  return v === 'caution' ? '<span class="badge err">caution</span>'
       : v === 'pass'    ? '<span class="badge ok">clean</span>'
       :                   `<span class="badge">${esc(v || 'unscanned')}</span>`;
}

async function renderOcPlugins(){
  const box = document.getElementById('ocp-list');
  if(!box) return;
  let d = null;
  try{ d = await (await fetch('/api/openclaw/plugins')).json() }catch(e){}
  if(!d){ box.innerHTML = '<p class="mut">could not read the plugin list</p>'; return }
  if(!d.available){
    /* Not a disabled button with a tooltip: the sentence, and nothing else. */
    box.innerHTML = `<h3>OpenClaw plugins</h3><div class="ghint mut">${esc(d.problem)}</div>`;
    return;
  }
  const rows = (d.plugins || []).map(p => {
    const state = p.held ? '<span class="badge err">held</span>'
                : p.enabled ? '<span class="badge ok">● on</span>'
                : '<span class="badge">○ off</span>';
    return `<div class="item" data-f="openclaw plugin ${esc(p.id + ' ' + (p.source||''))}"
                 style="align-items:flex-start">
      <div class="grow">
        <b>${esc(p.id)}</b>${p.version?`<span class="mut"> ${esc(p.version)}</span>`:''}
        ${p.bundled?'<span class="ck">ships with OpenClaw</span>':''}
        ${p.source?`<div class="sub mut">${esc(p.source)}</div>`:''}
        ${p.held?`<div class="sub" style="color:var(--err)">held: ${esc(p.held_reason)} — release it in Permissions → Quarantine</div>`:''}
      </div>
      ${state}
      <button class="endbtn" onclick="ocpReview('${esc(p.id)}')">Review</button>
    </div>`;
  }).join('');
  box.innerHTML = `<h3>OpenClaw plugins</h3>
    <div class="ghint">Third-party extensions for OpenClaw — tools, providers, channels and
      hooks. AgentOS scans one before you turn it on, writes what it may reach as real
      permissions, and can hold it. What it cannot do is refuse an individual call the
      plugin makes once it is running: that happens inside OpenClaw's own process.</div>
    <div class="prow">
      <input id="ocp-spec" placeholder="clawhub:name · npm:pkg · git:github.com/owner/repo · a path"
             autocomplete="off" style="flex:1">
      <button class="endbtn" onclick="ocpInstall()">Install</button>
      <button class="endbtn" onclick="ocpSearch()">Search ClawHub</button>
    </div>
    <div id="ocp-results"></div>
    <div id="ocp-review"></div>
    ${rows || '<p class="mut">no plugins installed</p>'}
    ${d.error?`<div class="ghint mut">${esc(d.error)}</div>`:''}
    <div class="ghint mut">OpenClaw loads plugin code when its gateway starts, so a change
      here is live only after that gateway restarts.</div>
    <div class="ghint"><button class="endbtn" onclick="ocpDoctor()">Check them</button>
      — asks OpenClaw whether the plugin tree is healthy, and asks this OS whether every
      enabled plugin still has the permission it was given.</div>`;
}

async function ocpSearch(){
  const q = (document.getElementById('ocp-spec')||{}).value || '';
  const out = document.getElementById('ocp-results');
  if(!q.trim()){ toast('Type something to search ClawHub for'); return }
  out.innerHTML = '<p class="mut">searching ClawHub…</p>';
  let d = null;
  try{ d = await (await fetch('/api/openclaw/plugins/search?q=' + encodeURIComponent(q))).json() }catch(e){}
  if(!d || !d.available){ out.innerHTML = `<p class="mut">${esc((d&&d.problem)||'search failed')}</p>`; return }
  if(!(d.results||[]).length){ out.innerHTML = `<p class="mut">nothing on ClawHub for “${esc(q)}”</p>`; return }
  out.innerHTML = d.results.map(r => `<div class="item">
      <div class="grow"><b>${esc(r.name)}</b>${r.version?`<span class="mut"> ${esc(r.version)}</span>`:''}
        <div class="sub mut">${esc(r.summary||'no summary')}</div></div>
      <button class="endbtn" onclick="ocpInstall('${esc(r.spec)}')">Install</button>
    </div>`).join('');
}

async function ocpInstall(spec){
  if(OCP_BUSY) return;
  spec = spec || ((document.getElementById('ocp-spec')||{}).value || '').trim();
  if(!spec){ toast('Which plugin? A ClawHub name, npm:…, git:… or a path'); return }
  OCP_BUSY = true;
  toast('Installing ' + spec + ' — it will land disabled');
  let d = null;
  try{
    d = await (await fetch('/api/openclaw/plugins/install', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({spec: spec})
    })).json();
  }catch(e){}
  OCP_BUSY = false;
  if(!d || d.error){
    /* An untrusted source is refused, and the refusal offers the one way past
       it: the person saying they looked. `force` is never sent on its own — it
       answers OpenClaw's own provenance question, so a person has to answer it. */
    if(d && d.needs_force &&
       confirm((d.source_note||'') + '\n\nInstall it anyway? Only if you have looked at ' +
               'the source and vouch for it.')){
      OCP_BUSY = true;
      try{
        d = await (await fetch('/api/openclaw/plugins/install', {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({spec: spec, force: true})
        })).json();
      }catch(e){}
      OCP_BUSY = false;
    }else{
      toast((d && d.error) ? String(d.error).slice(0,200) : 'install failed');
      return;
    }
  }
  if(!d || d.error){ toast(String((d&&d.error)||'install failed').slice(0,200)); return }
  await renderOcPlugins();
  if(d.id) ocpReview(d.id);
}

/* The consent screen. It is the SAME computation the enable runs — the server
   re-derives it rather than trusting anything sent back — so the sentence
   somebody agreed to is the permission they get.

   Rendered INLINE rather than in a window: on a phone (this pane is reached over
   the LAN as often as at a desk) a modal over a 390px screen puts the decision
   and the thing being decided about on two screens, and the review is exactly the
   moment somebody needs to look back at what they typed. */
async function ocpReview(pid){
  const out = document.getElementById('ocp-review');
  if(!out) return;
  out.innerHTML = '<p class="mut">reading it…</p>';
  let p = null;
  try{ p = await (await fetch('/api/openclaw/plugins/' + encodeURIComponent(pid))).json() }catch(e){}
  if(!p || p.error){ out.innerHTML = `<p class="mut">${esc((p&&p.error)||'could not read that plugin')}</p>`; return }
  const line = (k, v) => `<div class="mtool"><code>${esc(k)}</code><span>${esc(v)}</span></div>`;
  out.innerHTML = `<div class="pgroup" data-f="openclaw review ${esc(p.id)}">
    <h3>${esc(p.name||p.id)} ${ocpVerdict((p.security||{}).verdict)}</h3>
    <div class="ghint">${esc(p.source_note||'')}</div>
    <div class="ghint mut">${esc(p.tofu_note||'')}</div>
    ${p.manifest_note?`<div class="ghint mut">${esc(p.manifest_note)}</div>`:''}
    ${p.quarantined?`<div class="ghint" style="color:var(--err)">Held: ${esc((p.quarantine||{}).reason||'')}.
      Release it in Permissions → Quarantine before it can be turned on.</div>`:''}
    <details class="mtools" open><summary>What this machine's scan found</summary>
      ${((p.security||{}).findings||[]).map(f=>line(f.severity, f.note)).join('')
        || '<div class="mtool"><span>nothing to report</span></div>'}</details>
    <details class="mtools" open><summary>Turning it on would let it</summary>
      ${(p.capabilities||[]).map(c=>`<div class="mtool"><span>${esc(c)}</span></div>`).join('')}</details>
    <details class="mtools"><summary>and write ${(p.grants||[]).length} permission(s)</summary>
      ${(p.grants||[]).map(g=>line(g.action, g.resource)).join('')}</details>
    <div class="prow" style="margin-top:12px;flex-wrap:wrap">
      ${p.enabled
        ? `<button class="endbtn" onclick="ocpEnable('${esc(p.id)}',false)">Turn off</button>`
        : `<button class="endbtn" onclick="ocpEnable('${esc(p.id)}',true)">Turn on</button>`}
      <button class="endbtn" onclick="ocpUpdate('${esc(p.id)}')">Update</button>
      ${p.enabled?`<button class="endbtn" onclick="ocpHold('${esc(p.id)}')">Hold it now</button>`:''}
      <button class="endbtn" onclick="ocpUninstall('${esc(p.id)}')">Uninstall</button>
      <button class="endbtn" onclick="document.getElementById('ocp-review').innerHTML=''">Close</button>
    </div>
    <div class="ghint mut">OpenClaw loads plugin code at gateway start — restart its gateway
      before expecting a change here to be live.</div>
  </div>`;
  out.scrollIntoView({block:'nearest', behavior:'smooth'});
}

async function ocpPost(path, body){
  try{
    return await (await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'},
                                     body: JSON.stringify(body||{})})).json();
  }catch(e){ return {error:'the server did not answer'} }
}

async function ocpEnable(pid, on){
  const d = await ocpPost('/api/openclaw/plugins/' + encodeURIComponent(pid) + '/enable',
                          {enabled: !!on});
  if(!d.ok){ toast(String(d.error||'failed').slice(0,200)); return }
  toast(on ? `${pid} is on — ${(d.grants||{}).added||0} permission(s) written`
           : `${pid} is off — ${d.revoked||0} permission(s) taken back`);
  await renderOcPlugins();
  ocpReview(pid);
}

async function ocpUpdate(pid){
  toast('Updating ' + pid + '…');
  const d = await ocpPost('/api/openclaw/plugins/' + encodeURIComponent(pid) + '/update', {});
  if(!d.ok){ toast(String(d.error||'update failed').slice(0,200)); return }
  /* A held update is the supply-chain case this surface exists for, so it is
     said loudly rather than reported as a successful upgrade. */
  toast(d.held ? `${pid} was HELD after updating: ${String(d.reason).slice(0,120)}`
               : `${pid} updated`);
  await renderOcPlugins();
  ocpReview(pid);
}

async function ocpHold(pid){
  if(!confirm(`Stop ${pid} now and take its permissions back?\n\nIt stays installed. ` +
              `Releasing it goes through Permissions → Quarantine.`)) return;
  const d = await ocpPost('/api/openclaw/plugins/' + encodeURIComponent(pid) + '/hold', {});
  toast(d.ok ? `${pid} held` : String(d.error||'failed').slice(0,200));
  await renderOcPlugins();
}

async function ocpUninstall(pid){
  if(!confirm(`Remove ${pid} from OpenClaw and revoke everything it was granted?`)) return;
  let d = null;
  try{
    d = await (await fetch('/api/openclaw/plugins/' + encodeURIComponent(pid),
                           {method:'DELETE'})).json();
  }catch(e){}
  toast((d && d.ok) ? `${pid} removed — ${d.revoked||0} permission(s) taken back`
                    : String((d&&d.error)||'failed').slice(0,200));
  await renderOcPlugins();
}

async function ocpDoctor(){
  let d = null;
  try{ d = await (await fetch('/api/openclaw/plugins-doctor')).json() }catch(e){}
  if(!d || !d.available){ toast((d&&d.problem)||'could not check'); return }
  const a = d.agentos || {};
  const off = (a.disabled||[]);
  toast(off.length
    ? `${off.length} plugin(s) turned off: ` + off.map(x=>x.id + ' (' + x.why + ')').join(', ')
    : `${a.checked||0} plugin(s) checked — every enabled one still has the permission it was given`);
  await renderOcPlugins();
}
