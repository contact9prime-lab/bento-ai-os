/* ================= mcp app ================= */
let MCPCFG={};
function mcpSnap(s){
  const c={transport:s.transport,command:s.command,args:s.args,url:s.url,enabled:s.enabled};
  if(s.env&&Object.keys(s.env).length)c.env=s.env;
  if(s.headers&&Object.keys(s.headers).length)c.headers=s.headers;
  return c;
}
const mcpBadge=e=>e.oauth?'<span class="ck">OAuth — sign-in opens in your browser</span>'
  :e.env?`<span class="ck">needs ${esc(e.auth||'an API key')}</span>`
  :e.bearer?`<span class="ck">needs ${esc(e.auth||'a token')}${e.opt?' (optional)':''}</span>`:'';
async function renderMCP(body){
  const r=await fetch('/api/mcp');const d=await r.json();
  let REG={};try{((await (await fetch('/api/mcp/registry')).json()).registry||[]).forEach(x=>REG[x.name]=x)}catch(e){}
  MCPCFG={};
  d.servers.forEach(s=>{MCPCFG[s.name]=mcpSnap(s)});
  const badge=s=>s.status==='connected'?`<span class="badge ok">● connected</span>`
    :s.status==='connecting'?`<span class="badge run">connecting…</span>`
    :s.status==='disabled'?`<span class="badge">disabled</span>`
    :`<span class="badge err">error</span>`;
  const toolText=t=>typeof t==='string'?t:(t.name+' '+(t.description||''));
  const items=d.servers.map(s=>{
    const tools=(s.tools||[]).map(t=>typeof t==='string'?{name:t,description:''}:t);
    return `<div class="item" data-f="${esc(s.name+' '+(s.tools||[]).map(toolText).join(' '))}" style="align-items:flex-start">
    <div class="grow">
      <b>${esc(s.name)}</b> <span class="mut">· ${s.transport==='http'?esc(s.url):esc((s.command+' '+(s.args||'')).trim())}</span>
      ${s.error?`<div class="sub" style="color:var(--err)">${esc(s.error)}</div>`:''}
      ${tools.length?`<details class="mtools"><summary>${tools.length} tools — what each one does</summary>
        ${s.instructions?`<div class="minstr">${esc(s.instructions.slice(0,600))}${s.instructions.length>600?'…':''}</div>`:''}
        ${tools.map(t=>`<div class="mtool"><code>${esc(t.name)}</code><span>${esc((t.description||'').split('\n')[0].slice(0,180))||'<i>no description provided by the server</i>'}</span></div>`).join('')}
      </details>`:''}
    </div>${badge(s)}
    ${REG[s.name]&&REG[s.name].doc_file?`<button title="open this server's generated manual in Docs" onclick="docsCur='${esc(REG[s.name].doc_file)}';openApp('docs');refreshApp('docs')">📖</button>`:''}
    <button title="enable/disable" onclick="mcpToggle('${esc(s.name)}')">${s.enabled?'⏸':'▶'}</button>
    <button title="remove" onclick="mcpDel('${esc(s.name)}')">✕</button></div>`}).join('');
  const pb=panelShell(body,{
    title:'MCP Servers',
    sub:`${d.servers.filter(s=>s.status==='connected').length} connected · ${d.servers.length} configured`,
    search:{id:'mcp-q',placeholder:'Search servers, tools & catalog…'},
  });
  pb.innerHTML=`
    ${d.available?'':'<div class="errmsg">python package <code>mcp</code> is not installed — run <code>uv add mcp</code> and restart.</div>'}
    <div class="sect" style="display:flex;align-items:center;gap:10px">Connected channels
      <button class="endbtn" style="font-size:10.5px;margin-left:auto" onclick="STORE_TAB='discover';openApp('store');refreshApp('store')">🔭 Discover more — search the worldwide MCP registry</button></div>
    ${items||emptyBox('No MCP servers yet','Pick one from the catalog below, or use Store → Discover to search the worldwide MCP registry — the agent instantly gains every tool the server exposes.')}
    ${MCP_GROUPS.map((g,gi)=>`
    <div data-fgroup>
    <div class="sect">${esc(g)}</div>
    <div class="cat">${MCP_CATALOG.filter(e=>e.g===gi).map(e=>`
      <button class="catcard${MCPCFG[e.k]?' inst':''}" data-f="${esc(e.n+' '+e.d)}" onclick="mcpPreset('${e.k}')">
        <span class="cn">${esc(e.n)}</span><span class="cd">${esc(e.d)}</span>
        ${mcpBadge(e)}
      </button>`).join('')}
    </div></div>`).join('')}
    <div data-fgroup>
    <div class="sect" data-f="add custom server">Add a custom server</div>
    <div class="row"><input id="mcp-name" placeholder="name (e.g. playwright)">
      <select id="mcp-tr"><option value="stdio">stdio (command)</option><option value="http">http (url)</option></select></div>
    <div class="row" style="margin-top:8px"><input id="mcp-cmd" placeholder="command or url — e.g. npx -y @playwright/mcp@latest">
      <button class="pact" style="flex:0 0 90px" onclick="mcpAdd()">Add</button></div>
    <p class="mut" style="margin-top:10px">MCP tools show up to the agent as <code>mcp_&lt;server&gt;_&lt;tool&gt;</code> and always ask for approval unless autonomy is <b>Full</b>.</p>
    </div>`;
}
async function mcpSave(){
  await fetch('/api/mcp',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({servers:MCPCFG})});
  toast('MCP config saved — reconnecting…');
  setTimeout(()=>refreshApp('mcp'),1200);
  setTimeout(()=>refreshApp('mcp'),5000);
}
function mcpAdd(){
  const name=$('#mcp-name').value.trim().replace(/\s+/g,'-'),tr=$('#mcp-tr').value,val=$('#mcp-cmd').value.trim();
  if(!name||!val)return toast('name and command/url required');
  MCPCFG[name]=tr==='http'?{transport:'http',url:val,enabled:true}
    :{transport:'stdio',command:val.split(/\s+/)[0],args:val.split(/\s+/).slice(1).join(' '),enabled:true};
  mcpSave();
}
/* Catalog entry: k id · g group index · i icon · n name · d description
   stdio: c command, a args ({WS}=workspace, {ASK:question} prompts the user)
   http:  t:'http', u url ({ASK:…} works too), bearer:'prompt' → Authorization: Bearer <answer> (opt:true = skippable)
   env:   [[VAR, where-to-get-it], …] prompted one by one and stored in the server's env
   oauth: true → server signs you in via browser on first connect (mcp-remote)
   auth:  short label for the card badge */
const MCP_GROUPS=['Essentials — no key needed','Web & search','Developer & data','Apps & SaaS'];
const MCP_CATALOG=[
  // ---- essentials (no auth) ----
  {k:'playwright',g:0,i:'',n:'Playwright',d:'Full browser automation: navigate, click, fill, screenshot',c:'npx',a:'-y @playwright/mcp@latest'},
  {k:'filesystem',g:0,i:'',n:'Filesystem',d:'Read/write files in your workspace',c:'npx',a:'-y @modelcontextprotocol/server-filesystem {WS}'},
  {k:'fetch',g:0,i:'',n:'Fetch',d:'Fetch web pages as clean markdown',c:'uvx',a:'mcp-server-fetch'},
  {k:'memory',g:0,i:'',n:'Memory',d:'Official knowledge-graph memory server',c:'npx',a:'-y @modelcontextprotocol/server-memory'},
  {k:'sequential-thinking',g:0,i:'',n:'Sequential Thinking',d:'Structured step-by-step reasoning',c:'npx',a:'-y @modelcontextprotocol/server-sequentialthinking'},
  {k:'git',g:0,i:'',n:'Git',d:'Inspect and search git repositories',c:'uvx',a:'mcp-server-git'},
  {k:'time',g:0,i:'',n:'Time',d:'Time and timezone conversions',c:'uvx',a:'mcp-server-time'},
  {k:'sqlite',g:0,i:'',n:'SQLite',d:'Query local .db files',c:'uvx',a:'mcp-server-sqlite --db-path {ASK:Full path to the .db file}'},
  {k:'everything',g:0,i:'',n:'Everything',d:'MCP demo server for testing',c:'npx',a:'-y @modelcontextprotocol/server-everything'},
  // ---- web & search ----
  {k:'duckduckgo',g:1,i:'',n:'DuckDuckGo',d:'Free web search, no key needed',c:'uvx',a:'duckduckgo-mcp-server'},
  {k:'brave-search',g:1,i:'',n:'Brave Search',d:'Web search API (generous free tier)',c:'npx',a:'-y @modelcontextprotocol/server-brave-search',env:[['BRAVE_API_KEY','free key from brave.com/search/api']],auth:'API key'},
  {k:'tavily',g:1,i:'',n:'Tavily',d:'AI-grade web search, extract & crawl',c:'npx',a:'-y tavily-mcp@latest',env:[['TAVILY_API_KEY','free key from app.tavily.com']],auth:'API key'},
  {k:'exa',g:1,i:'',n:'Exa',d:'Semantic web search built for AI agents',c:'npx',a:'-y exa-mcp-server',env:[['EXA_API_KEY','from dashboard.exa.ai/api-keys']],auth:'API key'},
  {k:'perplexity',g:1,i:'',n:'Perplexity',d:'Ask questions answered by live web research',c:'npx',a:'-y server-perplexity-ask',env:[['PERPLEXITY_API_KEY','from perplexity.ai → Settings → API']],auth:'API key'},
  {k:'firecrawl',g:1,i:'',n:'Firecrawl',d:'Scrape & crawl any site into clean markdown',c:'npx',a:'-y firecrawl-mcp',env:[['FIRECRAWL_API_KEY','from firecrawl.dev → API keys']],auth:'API key'},
  {k:'context7',g:1,i:'',n:'Context7',d:'Up-to-date library documentation',c:'npx',a:'-y @upstash/context7-mcp'},
  {k:'deepwiki',g:1,i:'',n:'DeepWiki',d:'Ask questions about any public GitHub repo',t:'http',u:'https://mcp.deepwiki.com/mcp'},
  {k:'microsoft-learn',g:1,i:'',n:'Microsoft Learn',d:'Official Microsoft & Azure documentation',t:'http',u:'https://learn.microsoft.com/api/mcp'},
  {k:'huggingface',g:1,i:'',n:'Hugging Face',d:'Search models, datasets, papers & Spaces',t:'http',u:'https://huggingface.co/mcp',bearer:'Hugging Face token from hf.co/settings/tokens — leave empty for anonymous access',opt:true,auth:'token'},
  // ---- developer & data ----
  {k:'github',g:2,i:'',n:'GitHub',d:'Official GitHub MCP: repos, issues, PRs, actions, code search',t:'http',u:'https://api.githubcopilot.com/mcp/',bearer:'GitHub personal access token — create at github.com/settings/tokens',auth:'GitHub PAT'},
  {k:'postgres',g:2,i:'',n:'Postgres',d:'Query a PostgreSQL database',c:'npx',a:'-y @modelcontextprotocol/server-postgres {ASK:Postgres connection string (postgres://…)}',auth:'connection string'},
  {k:'mongodb',g:2,i:'',n:'MongoDB',d:'Query & manage MongoDB / Atlas',c:'npx',a:'-y mongodb-mcp-server',env:[['MDB_MCP_CONNECTION_STRING','mongodb+srv:// string from Atlas → Connect → Drivers']],auth:'connection string'},
  {k:'supabase',g:2,i:'',n:'Supabase',d:'Tables, SQL, migrations, edge functions, logs',c:'npx',a:'-y @supabase/mcp-server-supabase@latest --project-ref {ASK:Supabase project ref (dashboard → Project Settings → General)}',env:[['SUPABASE_ACCESS_TOKEN','personal access token from supabase.com/dashboard/account/tokens']],auth:'access token'},
  {k:'sentry',g:2,i:'',n:'Sentry',d:'Errors, issues & performance from your Sentry org',c:'npx',a:'-y mcp-remote https://mcp.sentry.dev/mcp',oauth:true},
  {k:'kubernetes',g:2,i:'☸',n:'Kubernetes',d:'Manage clusters via your local kubeconfig',c:'npx',a:'-y mcp-server-kubernetes'},
  {k:'aws-docs',g:2,i:'',n:'AWS Docs',d:'Search official AWS documentation',c:'uvx',a:'awslabs.aws-documentation-mcp-server@latest'},
  {k:'cloudflare-docs',g:2,i:'',n:'Cloudflare Docs',d:'Cloudflare product documentation',c:'npx',a:'-y mcp-remote https://docs.mcp.cloudflare.com/sse'},
  {k:'vercel',g:2,i:'▲',n:'Vercel',d:'Projects, deployments & logs on Vercel',c:'npx',a:'-y mcp-remote https://mcp.vercel.com',oauth:true},
  // ---- apps & saas ----
  {k:'notion',g:3,i:'',n:'Notion',d:'Read & write pages and databases',c:'npx',a:'-y @notionhq/notion-mcp-server',env:[['NOTION_TOKEN','internal-integration secret (ntn_…) from notion.so/profile/integrations — then share the target pages with that integration']],auth:'integration secret'},
  {k:'linear',g:3,i:'',n:'Linear',d:'Issues, projects & cycles in Linear',c:'npx',a:'-y mcp-remote https://mcp.linear.app/sse',oauth:true},
  {k:'atlassian',g:3,i:'',n:'Atlassian',d:'Jira issues & Confluence pages',c:'npx',a:'-y mcp-remote https://mcp.atlassian.com/v1/sse',oauth:true},
  {k:'slack',g:3,i:'',n:'Slack',d:'Read/post in your Slack workspace',c:'npx',a:'-y @modelcontextprotocol/server-slack',env:[['SLACK_BOT_TOKEN','xoxb-… bot token from api.slack.com/apps → OAuth & Permissions'],['SLACK_TEAM_ID','workspace ID (starts with T) from your Slack URL or workspace settings']],auth:'bot token'},
  {k:'airtable',g:3,i:'',n:'Airtable',d:'Read & write bases, tables and records',c:'npx',a:'-y airtable-mcp-server',env:[['AIRTABLE_API_KEY','personal access token from airtable.com/create/tokens']],auth:'access token'},
  {k:'stripe',g:3,i:'',n:'Stripe',d:'Customers, payments, invoices, subscriptions',c:'npx',a:'-y @stripe/mcp --tools=all --api-key={ASK:Stripe secret key (sk_…) from dashboard.stripe.com/apikeys — a restricted key is safest}',auth:'secret key'},
  {k:'figma',g:3,i:'',n:'Figma',d:'Pull designs & components for code generation',c:'npx',a:'-y figma-developer-mcp --stdio',env:[['FIGMA_API_KEY','personal access token from Figma → Settings → Security']],auth:'access token'},
  {k:'google-maps',g:3,i:'',n:'Google Maps',d:'Places, geocoding, directions',c:'npx',a:'-y @modelcontextprotocol/server-google-maps',env:[['GOOGLE_MAPS_API_KEY','from console.cloud.google.com → APIs & Services → Credentials']],auth:'API key'},
  {k:'zapier',g:3,i:'',n:'Zapier',d:'8,000+ apps through your Zapier account',t:'http',u:'{ASK:Your personal MCP server URL from mcp.zapier.com (includes its own auth)}',auth:'personal URL'},
  {k:'elevenlabs',g:3,i:'',n:'ElevenLabs',d:'Text-to-speech & voice generation',c:'uvx',a:'elevenlabs-mcp',env:[['ELEVENLABS_API_KEY','from elevenlabs.io → profile → API keys']],auth:'API key'},
];
async function mcpPreset(key){
  const e=MCP_CATALOG.find(x=>x.k===key);
  if(!e||MCPCFG[e.k])return;
  const fill=async(s)=>{      // resolve {WS} and every {ASK:question}; null = user cancelled
    s=s.replace('{WS}',(cfg&&cfg.workspace)||'~');
    let m;
    while((m=s.match(/\{ASK:([^}]+)\}/))){
      const v=await osPrompt(e.n,{message:m[1]});
      if(!v)return null;
      s=s.replace(m[0],v.trim());
    }
    return s;
  };
  let conf;
  if(e.t==='http'){
    const url=await fill(e.u);
    if(url===null)return;
    conf={transport:'http',url,enabled:true};
    if(e.bearer){
      const v=await osPrompt(e.n,{message:e.bearer});
      if(v===null)return;
      if(v.trim())conf.headers={Authorization:'Bearer '+v.trim()};
      else if(!e.opt)return;
    }
  }else{
    const args=await fill(e.a);
    if(args===null)return;
    conf={transport:'stdio',command:e.c,args,enabled:true};
    if(e.env){
      conf.env={};
      for(const [k,hint] of e.env){
        const v=await osPrompt(k,{message:hint});
        if(!v)return;
        conf.env[k]=v.trim();
      }
    }
  }
  if(e.oauth)toast('first connect opens a browser tab to sign in — approve it there');
  MCPCFG[e.k]=conf;mcpSave();
}
function mcpToggle(name){if(MCPCFG[name]){MCPCFG[name].enabled=!MCPCFG[name].enabled;mcpSave()}}
function mcpDel(name){delete MCPCFG[name];mcpSave()}

/* ================= telegram app ================= */
async function renderTelegram(body){
  const r=await fetch('/api/telegram');const d=await r.json();
  const st=d.status==='polling'?`<span class="badge ok">● polling as @${esc(d.bot_username||'…')}</span>`
    :d.status==='error'?`<span class="badge err">error</span>`:`<span class="badge">off</span>`;
  body.innerHTML=`<div class="pad">
    <div class="provbox">
      <div class="ptitle">Telegram bridge ${st}</div>
      ${d.error?`<div class="sub" style="color:var(--err);margin-top:6px">${esc(d.error)}</div>`:''}
      <p class="mut" style="margin-top:8px">
        <span class="stepnum">1</span>Open Telegram, message <b>@BotFather</b> → <code>/newbot</code> → copy the token.<br><br>
        <span class="stepnum">2</span>Paste the token below and enable the bridge.<br><br>
        <span class="stepnum">3</span>Message your new bot <code>/start</code> — the first chat to do so becomes the owner; everyone else is ignored.
      </p>
      <label>Bot token ${d.has_token?'(set)':''}</label>
      <input id="tg-token" placeholder="123456:ABC-…" value="">
      <label style="display:flex;align-items:center;gap:8px;margin-top:12px">
        <input type="checkbox" id="tg-on" style="width:auto" ${d.enabled?'checked':''}> Enable bridge
      </label>
      <button class="save" onclick="tgSave()">Save</button>
    </div>
    <div class="provbox">
      <div class="ptitle">Pairing</div>
      <p class="mut" style="margin-top:6px">${d.owner_chat_id
        ?`Owner chat: <b>${d.owner_chat_id}</b>. Commands: <code>/clear</code> resets a session, <code>/status</code> pings.`
        :(d.bot_username?`Not paired yet — send any message to <a href="https://t.me/${esc(d.bot_username)}" target="_blank" style="color:var(--acc2)">@${esc(d.bot_username)}</a>; the first private chat becomes the owner.`:'Not paired yet — save a token first.')}</p>
      <div class="row" style="margin-top:10px">
        <button class="save" style="margin:0" onclick="tgTest()">Send test message</button>
        ${d.owner_chat_id?'<button class="endbtn" onclick="tgUnpair()">Unpair</button>':''}
      </div>
    </div>
    <div class="provbox">
      <div class="ptitle">Chats, groups &amp; channels</div>
      <p class="mut" style="margin:6px 0 10px">Every user, group or channel that reaches the bot registers here — connect more by adding the bot
        to a group (as a member) or a channel (as an admin). New arrivals start <b>blocked</b>; only chats you enable can talk to the agent.
        Telegram is an IO gate of the permission framework: scope any grant to the <code>telegram</code> surface in the Permissions app
        and it applies (only) here — blocked IO is denied and logged.</p>
      ${(d.chats||[]).map(c=>`<div class="item">
        <span class="lbadge">${c.type==='private'?'user':c.type==='channel'?'channel':'group'}</span>
        <div class="grow"><b>${esc(c.title||c.chat_id)}</b>${c.username?` <span class="mut">@${esc(c.username)}</span>`:''}${c.chat_id===d.owner_chat_id?' <span class="badge ok">owner</span>':''}
          <div class="sub">${esc(c.type)} · ${c.msg_count} msg · last ${new Date(c.last_seen*1000).toLocaleString()}</div></div>
        <span class="badge ${c.allowed?'ok':'err'}">${c.allowed?'enabled':'blocked'}</span>
        <button title="${c.allowed?'disable':'enable'}" onclick="tgAllow(${c.chat_id},${c.allowed?0:1})">${c.allowed?'⏸':'▶'}</button>
        <button onclick="tgDelChat(${c.chat_id})">✕</button>
      </div>`).join('')||'<p class="mut">No chats registered yet.</p>'}
    </div>
  </div>`;
  $('#tg-token').addEventListener('input',e=>{if(e.target.value.trim())$('#tg-on').checked=true});
}
async function tgSave(){
  await fetch('/api/telegram',{method:'PUT',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({enabled:$('#tg-on').checked,bot_token:$('#tg-token').value.trim()})});
  toast('telegram settings saved');setTimeout(()=>refreshApp('telegram'),1500);
}
async function tgTest(){
  const r=await fetch('/api/telegram/test',{method:'POST'});const d=await r.json();
  toast(d.result);
}
async function tgAllow(id,allowed){
  await fetch('/api/telegram/chats/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({allowed:!!allowed})});
  refreshApp('telegram');
}
async function tgDelChat(id){
  await fetch('/api/telegram/chats/'+id,{method:'DELETE'});refreshApp('telegram');
}
async function tgUnpair(){
  await fetch('/api/telegram',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({unpair:true})});
  toast('unpaired');refreshApp('telegram');
}

/* ================= logs app ================= */
function renderLogs(body,w){
  w.kind=w.kind||'';w.q=w.q||'';
  body.innerHTML=`<div class="apptop">
      <select id="log-kind" style="flex:0 0 130px">
        <option value="">all kinds</option><option>turn</option><option>tool</option><option>policy</option><option>mcp</option>
        <option>telegram</option><option>task</option><option>system</option><option>error</option>
      </select>
      <input id="log-q" placeholder="search message & details… (e.g. deny, app:, run_command)" style="flex:1">
      <span class="mut" id="log-count" style="flex:0 0 auto"></span>
      <button class="endbtn" onclick="refreshApp('logs')">↻</button>
      <button class="endbtn" onclick="logsClear()">Clear all</button>
    </div>
    <div style="flex:1;overflow-y:auto;user-select:text"><table class="loglist"><tbody id="log-rows"></tbody></table></div>`;
  $('#log-kind').value=w.kind;$('#log-q').value=w.q;
  $('#log-kind').onchange=()=>{w.kind=$('#log-kind').value;loadLogs(w)};
  let deb;$('#log-q').oninput=e=>{clearTimeout(deb);deb=setTimeout(()=>{w.q=e.target.value;loadLogs(w)},300)};
  clearInterval(w.timer);
  loadLogs(w);
  w.timer=setInterval(()=>{if(document.getElementById('log-rows'))loadLogs(w);else clearInterval(w.timer)},5000);
}
async function loadLogs(w){
  const r=await fetch('/api/logs?kind='+encodeURIComponent(w.kind||'')+'&q='+encodeURIComponent(w.q||''));const d=await r.json();
  const tb=$('#log-rows');if(!tb)return;
  $('#log-count').textContent=d.logs.length+' entries';
  tb.innerHTML=d.logs.map(l=>{
    const t=new Date(l.created_at*1000);
    let m={};try{m=JSON.parse(l.meta||'{}')}catch(e){}
    const keys=Object.keys(m);
    const mtxt=keys.map(k=>k+'='+JSON.stringify(m[k])).join('  ');
    const eff=m.effect==='deny'||l.kind==='error'?'var(--err,#f87171)':(m.effect==='allow'?'var(--ok,#5eead4)':'');
    return `<tr class="lk-${esc(l.kind)}" style="cursor:${keys.length?'pointer':'default'}" onclick="logExpand(this)">
      <td class="lk">${t.toLocaleTimeString()}<br><span style="font-size:10px">${t.toLocaleDateString()}</span></td>
      <td><span class="lbadge" ${eff?`style="color:${eff};border-color:${eff}"`:''}>${esc(l.kind)}</span></td>
      <td>${esc(l.message)}
        ${m.principal?`<span class="badge" style="margin-left:6px">${esc(m.principal)}</span>`:''}
        ${mtxt?`<div class="tools-mini" style="white-space:normal;word-break:break-word">${esc(mtxt.slice(0,220))}${mtxt.length>220?' …':''}</div>
        <pre class="log-full" style="display:none;font-size:11px;background:var(--card,#171b22);border:1px solid var(--line,#232a35);border-radius:8px;padding:8px;margin-top:6px;white-space:pre-wrap;max-height:260px;overflow:auto">${esc(JSON.stringify(m,null,2))}</pre>`:''}</td></tr>`;
  }).join('')||'<tr><td class="mut" style="padding:20px">no log entries</td></tr>';
}
function logExpand(tr){const p=tr.querySelector('.log-full');if(p)p.style.display=p.style.display==='none'?'block':'none'}
async function logsClear(){await fetch('/api/logs',{method:'DELETE'});refreshApp('logs')}

