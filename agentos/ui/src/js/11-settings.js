/* ================= settings app ================= */
/* ---- preference primitives: every row is label+description left, control right ---- */
function pGroup(title,rows,o){
  o=o||{};
  return `<div class="pgroup${o.danger?' danger':''}" data-f="${esc(o.f||title)}">
    ${title?`<h3>${esc(title)}</h3>`:''}${o.hint?`<div class="ghint">${o.hint}</div>`:''}
    ${rows.join('')}</div>`;
}
function pRow(label,control,o){
  o=o||{};
  const [d,m]=o.more!=null?[o.desc||'',o.more]:pSplit(o.desc);
  return `<div class="prow${o.stack?' stack':''}${o.danger?' danger':''}" data-f="${esc(o.f||label)} ${esc(pPlain(m))}">
    <div class="pl"><b>${esc(label)}</b>${m?pInfo(m):''}${d?`<small>${d}</small>`:''}</div>
    <div class="pc">${control}</div></div>`;
}
/* Settings text is a line or two under the label, and the rest behind an ⓘ that
   shows it on hover, focus or tap. Everything on this page is worth knowing, and
   nothing on it should be a wall somebody has to read to find a switch.
   `desc` is the line, `more` the rest; a desc written as one long paragraph is
   split at its first sentence, so no row ever shows a wall again. `pTidy` does the
   same for the group hints and leads, which are written inline all over the panes. */
var PTIP_AT=140;                     // visible characters a line may run to before it splits
function pPlain(html){return String(html||'').replace(/<[^>]*>/g,'').replace(/&nbsp;/g,' ').replace(/&amp;/g,'&')
  .replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/\s+/g,' ').trim()}
function pInfo(text){
  const t=pPlain(text);if(!t)return '';
  return `<button type="button" class="pinfo" data-tip="${esc(t)}" aria-label="${esc(t)}">i</button>`;
}
/* [the first sentence, the rest] — split only where no tag is open, so a <b> or a
   <code> is never cut in half, and only past the first 30 visible characters. */
function pSplit(html){
  html=String(html||'');
  if(pPlain(html).length<=PTIP_AT)return [html,''];
  const open=[];let vis=0;
  for(let i=0;i<html.length;i++){
    const c=html[i];
    if(c==='<'){const j=html.indexOf('>',i);if(j<0)break;
      const tag=html.slice(i+1,j);
      if(tag[0]==='/')open.pop();else if(!/\/$/.test(tag)&&!/^(br|img|input|hr|wbr)\b/i.test(tag))open.push(tag);
      i=j;continue}
    vis++;
    if(!open.length&&vis>=30&&/[.?!]/.test(c)&&/\s/.test(html[i+1]||'')&&!/\b(e\.g|i\.e|etc|vs)$/i.test(html.slice(Math.max(0,i-4),i)))
      return [html.slice(0,i+1),html.slice(i+2).trim()];
  }
  return [html,''];
}
function pTidy(root){
  (root||document).querySelectorAll('.ghint,.lead,.pl>small').forEach(el=>{
    if(el.dataset.tidy)return;el.dataset.tidy='1';
    if(el.querySelector('button,a,input,select,textarea,label,.pinfo'))return;   // a control inside stays where it is
    const [a,b]=pSplit(el.innerHTML);if(!b)return;
    if(el.matches('.pl>small')){el.innerHTML=a;const lb=el.parentNode.querySelector(':scope>b');
      if(lb&&!el.parentNode.querySelector(':scope>.pinfo'))lb.insertAdjacentHTML('afterend',pInfo(b))}
    else el.innerHTML=a+' '+pInfo(b);
  });
}
/* One tip for the whole page, placed by hand so it never runs off a 390px screen.
   Hover and focus show it; a tap on a touch screen toggles it (a finger has no hover). */
function pTipShow(btn){
  let t=document.getElementById('pinfo-tip');
  if(!t){t=document.createElement('div');t.id='pinfo-tip';t.setAttribute('role','tooltip');document.body.appendChild(t)}
  t.textContent=btn.dataset.tip||'';t.hidden=false;t.dataset.for='1';PTIP.btn=btn;
  const r=btn.getBoundingClientRect(),w=Math.min(320,innerWidth-24);t.style.maxWidth=w+'px';
  const tw=t.offsetWidth,th=t.offsetHeight;
  let x=Math.max(12,Math.min(r.left+r.width/2-tw/2,innerWidth-tw-12));
  let y=r.bottom+8;if(y+th>innerHeight-8)y=Math.max(8,r.top-th-8);
  t.style.left=x+'px';t.style.top=y+'px';
}
function pTipHide(){const t=document.getElementById('pinfo-tip');if(t)t.hidden=true;PTIP.btn=null}
var PTIP={btn:null,bound:false};
function pTipBind(){
  if(PTIP.bound)return;PTIP.bound=true;
  document.addEventListener('pointerover',e=>{const b=e.target.closest&&e.target.closest('.pinfo');if(b&&e.pointerType!=='touch')pTipShow(b)});
  document.addEventListener('pointerout',e=>{const b=e.target.closest&&e.target.closest('.pinfo');if(b&&e.pointerType!=='touch'&&document.activeElement!==b)pTipHide()});
  document.addEventListener('focusin',e=>{if(e.target.classList&&e.target.classList.contains('pinfo'))pTipShow(e.target)});
  document.addEventListener('focusout',e=>{if(e.target.classList&&e.target.classList.contains('pinfo'))pTipHide()});
  document.addEventListener('click',e=>{const b=e.target.closest&&e.target.closest('.pinfo');
    if(b){e.preventDefault();e.stopPropagation();if(PTIP.btn===b&&!document.getElementById('pinfo-tip').hidden)pTipHide();else pTipShow(b);return}
    if(PTIP.btn)pTipHide()},true);
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&PTIP.btn)pTipHide()});
  addEventListener('scroll',()=>{if(PTIP.btn)pTipHide()},true);
}
const pSwitch=(id,on)=>`<label class="psw"><input type="checkbox" id="${id}" ${on?'checked':''}><i></i></label>`;
/* A stored secret is never put back into an input: it shows as a locked chip
   with the last four characters, and "Replace" swaps in an empty field. That
   way nothing can echo the mask back to the server, and a shoulder-surfer sees
   nothing useful. */
/* A key box the browser must not take for a login form. Reported as "piyush keeps coming
   back in the top right corner": a type=password field made Chrome see a sign-in page,
   and it filled the saved username into the text box before it, which is Settings' own
   search box, again on every repaint. So a key is a TEXT field drawn as dots
   (-webkit-text-security, where the engine has it) with the password managers' opt-outs;
   an engine without it keeps type=password, told it is a new password so nothing is
   filled. `secretField` is used by every key box in Settings and Voice. */
function secretField(id,ph,cls){
  const dots=typeof CSS!=='undefined'&&CSS.supports&&CSS.supports('-webkit-text-security','disc');
  return `<input ${dots?'type="text" class="secret-in'+(cls?' '+cls:'')+'"':'type="password"'+(cls?' class="'+cls+'"':'')} id="${id}" placeholder="${esc(ph||'')}"`
    +` autocomplete="new-password" autocorrect="off" autocapitalize="off" spellcheck="false" data-1p-ignore data-lpignore="true" data-form-type="other">`;
}
function pSecret(id,hasKey,masked,ph){
  if(!hasKey)return secretField(id,ph);
  return `<span class="psecret" id="${id}-wrap"><i>saved</i><code>${esc(masked||'••••')}</code>
    <button class="endbtn" onclick="pSecretReplace('${id}')">Replace</button></span>`;
}
function pSecretReplace(id){
  const w=document.getElementById(id+'-wrap');if(!w)return;
  w.outerHTML=secretField(id,'new key…');
  const el=document.getElementById(id);if(el)el.focus();
}
const pText=(id,val,ph,type)=>`<input type="${type||'text'}" id="${id}" value="${esc(val==null?'':val)}" placeholder="${esc(ph||'')}">`;
const pSelect=(id,opts,cur)=>`<select id="${id}">${opts.map(([v,l])=>
  `<option value="${esc(v)}" ${String(v)===String(cur)?'selected':''}>${esc(l)}</option>`).join('')}</select>`;

// [id, glyph, label, icon]: the glyph is the standard desktop's, the icon
// (00d-icons.js) is what the immersive look shows in its coloured tile
const SETTINGS_TABS=[
  ['ai','✦','AI providers','sparkles'],
  ['agent','◈','Agents','agent'],
  ['executors','⇥','Executors','executors'],
  ['channels','◇','Channels','channels'],
  ['accounts','✉','Accounts','accounts'],
  ['locale','◐','Locale','locale'],
  ['keys','⌘','Shortcuts','keys'],
  ['voice','◉','Voice','voice'],
  ['look','◧','Appearance','look'],
  ['system','⚙','System','system'],
];
let SETTAB=localStorage.getItem('settab')||'ai';

async function renderSettings(body){
  await loadConfig();
  body.innerHTML=`<div class="pshell">
      <div class="phead"><span class="pt">Settings</span><span class="sp"></span>
        <span class="psearch">${SVG_SEARCH}<input id="set-q" type="search" name="settings-find" placeholder="Find a setting…" autocomplete="off" data-1p-ignore data-lpignore="true" data-form-type="other"></span>
        ${/* One Save per page. The sticky bar at the foot is always reachable
              while you scroll; a second copy in the header meant two controls for
              one act, and neither said which settings it covered. */''}
      </div>
      <div class="prefs">
        <div class="prefs-side">${SETTINGS_TABS.map(([id,ic,label,ico])=>
          `<button data-t="${id}" class="${SETTAB===id?'on':''}"><span class="psi"><i>${ic}</i>${uiIcon(ico,14)}</span>${esc(label)}</button>`).join('')}</div>
        <div class="prefs-main" id="prefs-main"></div>
      </div>
    </div>`;
  body.querySelectorAll('.prefs-side button').forEach(b=>b.onclick=()=>{
    SETTAB=b.dataset.t;localStorage.setItem('settab',SETTAB);
    body.querySelectorAll('.prefs-side button').forEach(x=>x.classList.toggle('on',x===b));
    setTab(body);
  });
  // search spans every category, so nothing hides behind a tab
  const q=body.querySelector('#set-q');
  let t;q.oninput=()=>{clearTimeout(t);t=setTimeout(()=>{
    const v=q.value.trim();
    if(v){setTab(body,true);listFilter(body.querySelector('#prefs-main'),v)}
    else setTab(body);
  },140)};
  // every pane is painted in pieces (a provider list arrives later than the page),
  // so the tidy runs on whatever lands in the pane, not once after the first paint
  pTipBind();
  const pm=body.querySelector('#prefs-main');
  if(typeof MutationObserver!=='undefined'){let q=0;
    new MutationObserver(()=>{if(q)return;q=1;queueMicrotask(()=>{q=0;pTidy(pm)})}).observe(pm,{childList:true,subtree:true})}
  setTab(body);
}
function setTab(body,all){
  const main=(body||document).querySelector('#prefs-main');if(!main)return;
  const p=cfg.providers;
  const P=[];
  const want=id=>all||SETTAB===id;
  if(want('ai')){
    P.push(`<h2>AI providers</h2><p class="lead">Every model this machine can think with. Each agent can use its own, set in <a href="#" onclick="settingsGo('agent');return false">Agents</a>. ${pInfo('Cloud providers with a key, models running on this machine, and other AI agents installed here like Claude Code, Gemini CLI or Codex.')}</p>`);
    // The chat chip has always said "change it in Settings → AI providers", and
    // for a long time this panel had nowhere to change it: you could add a key
    // and edit a provider's model LIST, but choosing which model actually answers
    // was only possible as "Set default" in the Model Manager. So editing the
    // list here looked like picking a model and did nothing. This is that control,
    // in the place everything already points at, and it applies on the spot —
    // needing a second Save to make a chosen model take effect is the same bug
    // wearing a different hat.
    P.push(pGroup('Answering', [
      pRow('Your lead agent thinks with',
        `<span class="s-modelrow">
           <select id="s-brain" onchange="pickExecutor(this.value)"><option value="">loading…</option></select>
           <select id="s-model" onchange="pickModel(this.value)"><option value="">loading…</option></select>
           <button class="endbtn" id="s-model-refresh" onclick="paintModelPicker(1)" title="Ask every enabled provider what it can run right now">↻ Refresh</button>
           <button class="endbtn" onclick="openApp('models')" title="Pull, delete and inspect local models">Manage…</button>
         </span>`,
        {desc:'The AI that answers you, and the model it uses.',
         more:'Chat, the prompt bar, Telegram and scheduled jobs all use it. Changes apply right away.',
         f:'model default answers with picker which model refresh available executor engine brain'}),
      pRow('Available', '<span id="s-model-count" class="mut">…</span>',
        {desc:'What your providers can run right now.',more:'Refresh after you pull a model or add a key.',
         f:'available models count refresh providers'}),
    ], {f:'model answering default'}));
    setTimeout(paintModelPicker, 0);      // the list is fetched, not part of cfg
    P.push(pGroup('Local',[
      pRow('Ollama base URL',pText('s-ollama-url',p.ollama.base_url,'http://localhost:11434'),
        {desc:'Models running on this machine. Private and free.',f:'ollama local base url'}),
    ],{f:'ollama local'}));
    const prov=(key,name,idOn,idKey,idModels,ph,desc,obj)=>pGroup(name,[
      pRow('Enabled',pSwitch(idOn,obj&&obj.enabled),{desc,f:key+' enable'}),
      pRow('API key',pSecret(idKey,obj&&obj._has_key,(obj&&obj.api_key)||'',ph),
        {f:key+' api key',desc:(obj&&obj._has_key)?'Saved on this machine and never shown again.':'Paste it once. It stays hidden after that.'}),
      pRow('Models',pText(idModels,((obj&&obj.models)||[]).join(', '),'comma-separated'),{stack:true,f:key+' models'}),
    ],{f:key+' '+name});
    P.push(prov('anthropic','Anthropic','s-ant-on','s-ant-key','s-ant-models','sk-ant-…','Claude models.',p.anthropic));
    P.push(prov('openai','OpenAI','s-oai-on','s-oai-key','s-oai-models','sk-…','GPT models.',p.openai));
    P.push(prov('openrouter','OpenRouter','s-or-on','s-or-key','s-or-models','sk-or-…','One key, hundreds of models.',p.openrouter));
    P.push(prov('google','Google (Gemini)','s-goo-on','s-goo-key','s-goo-models','AIza…','Gemini chat and images. Get a free key at aistudio.google.com.',p.google||{}));
    P.push(pGroup('Custom (OpenAI-compatible)',[
      pRow('Enabled',pSwitch('s-cus-on',p.custom.enabled),{desc:'Anything that speaks the OpenAI API, like LM Studio, vLLM or Groq.',f:'custom enable'}),
      pRow('Base URL',pText('s-cus-url',p.custom.base_url||'','http://localhost:1234/v1'),{f:'custom base url'}),
      pRow('API key',pSecret('s-cus-key',p.custom._has_key,p.custom.api_key||'','optional'),{f:'custom key'}),
      pRow('Models',pText('s-cus-models',(p.custom.models||[]).join(', '),'comma-separated'),{stack:true,f:'custom models'}),
    ],{f:'custom openai compatible endpoint lm studio'}));
    /* Other AI agents installed on this machine are BRAINS too — Claude Code thinks
       with its own model and can answer a turn or run a mission through the bridge.
       They lived under "Executors" when that word meant "who runs the turn"; it now
       means an agent's hands (Settings → Executors), so they are listed here with the
       rest of the brains. The code still calls them executors (agentos/executors.py):
       renaming the identifier would cost every install its saved engine for a word
       nobody sees. */
    P.push(`<h3 class="pgh">AI agents installed here</h3><p class="mut" style="margin:0 0 8px">Another agent can be the brain. Pick it above, or give it to one of your agents. ${pInfo('AgentOS keeps control of the desktop and permissions. An installed agent only reaches the folder you choose.')}</p>`);
    P.push(`<div id="exec-list" class="pgroup" data-f="executors claude code hermes openclaw installed agents brain"><h3>Claude Code</h3><p class="mut">checking…</p></div>`);
    P.push(`<div id="exec-offers"></div>`);
    P.push(`<div id="ocp-list" class="pgroup" data-f="openclaw plugins extensions clawhub"><h3>OpenClaw plugins</h3><p class="mut">checking…</p></div>`);
    setTimeout(renderExecutors,0);
    setTimeout(renderOcPlugins,0);
    P.push(pGroup('Image generation',[
      pRow('Provider',pSelect('s-img-prov',[['auto','auto'],['google','google'],['openai','openai'],['pollinations','pollinations']],(cfg.image&&cfg.image.provider)||'auto'),
        {desc:'Auto tries Google, then OpenAI, then the free pollinations.ai.',f:'image provider'}),
      pRow('Model',pText('s-img-model',(cfg.image&&cfg.image.model)||'','gemini-2.5-flash-image / gpt-image-1'),{f:'image model'}),
    ],{f:'image generation wallpaper'}));
  }
  if(want('executors')){
    /* Executors are HANDS (agentos/hands.py): what an agent can reach — which tools,
       which folders and whether it may write there, which web addresses, which MCP
       servers. A profile is a CEILING the gate checks before any permission (policy
       step 2a, rule "reach"); what an agent is ALLOWED inside it is still its grants.
       11e-hands.js draws the editor. TUI: `bento hands`, `bento agents hands`. SUI:
       this page — nothing native, nothing touching the compositor. */
    P.push(`<h2>Executors</h2><p class="lead">An executor is what an agent can reach. Pick one for each agent in <a href="#" onclick="settingsGo('agent');return false">Agents</a>. ${pInfo('It covers tools, folders (read-only or read-write), web addresses and MCP servers. An agent still needs permission to act, and every step is logged.')}</p>`);
    P.push(`<div id="hands-list" data-f="executors hands profile tools folders web mcp reach default read-only"><p class="mut">loading…</p></div>`);
    setTimeout(renderHands,0);
    P.push(pGroup('The machine\u2019s own limit',[
      pRow('Folder jail',pSwitch('s-sb-on',cfg.sandbox&&cfg.sandbox.enabled),
        {desc:'Runs commands and the Terminal inside a sandbox.',
         more:'Everything outside the folder is read-only and other people\u2019s home files are hidden. A shell can reach whatever this jail allows, even past an executor\u2019s folders.',f:'sandbox jail bubblewrap shell'}),
      pRow('Folder',pText('s-sb-root',(cfg.sandbox&&cfg.sandbox.root)||cfg.workspace),{f:'sandbox root folder'}),
      pRow('Shared folders','<button class="endbtn" onclick="openApp(\'users\')">Open Users</button>',
        {desc:'Extra folders the agent and the Terminal can use, shared with chosen accounts.',
         more:'Each one is read-only or read-write. Manage them in Users, or with bento folders in a terminal.',f:'sandbox safe shared folders ro rw users data access'}),
    ],{f:'sandbox security jail'}));
  }
  if(want('channels')){
    P.push(`<h2>Channels</h2><p class="lead">Every way you can reach this agent, and who can use each one. ${pInfo('They all share the same agent, memory and tools. What changes is who can speak through each one and how much it’s trusted.')}</p>`);
    P.push(`<div id="chan-list" data-f="channels telegram whatsapp api remote tui sui gui scheduled messaging permissions"><p class="mut">checking…</p></div>`);
    setTimeout(renderChannels,0);   // live state, not part of cfg
  }
  if(want('accounts')){
    P.push(`<h2>Accounts</h2><p class="lead">The mailbox and calendar your agent can read for you. ${pInfo('Sign in with Google or Microsoft, or use an app password for anything else. Passwords are kept in the vault, and every read is logged.')}</p>`);
    P.push(pGroup('GitHub',[
      pRow('Personal access token',pSecret('s-gh-token',cfg.github&&cfg.github._has_token,(cfg.github&&cfg.github.token)||'','github_pat_… / ghp_…'),
        {desc:(cfg.github&&cfg.github._has_token)?'A token is saved. Fine-grained tokens work best.':'Lets the agent create repos and push what it builds.',
         more:(cfg.github&&cfg.github._has_token)?'':'The token never shows up in commands or logs.',f:'github token push'}),
      pRow('Username',pText('s-gh-user',(cfg.github&&cfg.github.username)||'','optional'),{f:'github username'}),
    ],{f:'github git ship publish'}));
    P.push(`<div id="acct-list" data-f="accounts mail calendar sign in google microsoft oauth imap caldav ics gmail outlook icloud fastmail app password vault mcp"><p class="mut">checking…</p></div>`);
    setTimeout(renderAccounts,0);
  }
  if(want('agent')){
    /* Agents: the lead agent (always here) and the agents it works with. Each gets a
       BRAIN (AI providers), HANDS (Executors), AUTHORITY (its permissions) and SKILLS,
       and may talk to colleagues and linked teams — all of it read from ONE answer,
       agentmap.overview(), which the map below and `bento agents` read too.
       11e-hands.js draws the list and the map. */
    P.push(`<h2>Agents</h2><p class="lead">Your lead agent and the agents it works with. ${pInfo('Each one gets a brain, an executor, permissions and skills. Everything they do is logged.')}</p>`);
    P.push(pGroup('Lead agent',[
      pRow('Name',pText('s-name',cfg.agent_name||'Aria'),{desc:'What your agent is called everywhere.',f:'agent name'}),
      // the character is part of who the agent is, so it is edited HERE as well as in
      // Appearance — looking for it on the agent's own page and not finding it was the report
      pRow('Look',`<button class="endbtn av-set-btn" onclick="avatarEdit('@agent')" title="Change how your agent looks">${avatarImg('@agent','av-set')}Change…</button>`
        +`<button class="endbtn" onclick="avatarDesignAsk('@agent')">✦ Describe it</button>`,
        {desc:'Its character in Chat, Logs and the Office. Pick one or describe it.',f:'agent look character avatar face appearance'}),
      pRow('Brain','<span id="s-lead-brain" class="mut">…</span> <button class="endbtn" onclick="settingsGo(\'ai\')">Change</button>',
        {desc:'What your lead agent thinks with. You choose it in AI providers.',f:'lead agent brain model provider'}),
      pRow('Executor','<select id="s-lead-hands" onchange="setAgentHands(\'@agent\',this.value)"><option>…</option></select>',
        {desc:'What it can reach: tools, folders, web and MCP.',more:'Set up in Executors. Changes apply right away.',f:'lead agent hands executor profile reach tools folders'}),
      pRow('Workspace',pText('s-workspace',cfg.workspace),{desc:'Where it saves files, reports and projects.',f:'workspace directory'}),
      pRow('Max steps per turn',pText('s-steps',cfg.max_steps,'','number'),{desc:'How many tool steps one turn can take before it stops.',f:'max steps'}),
      pRow('Build model','<select id="s-build-model"><option value="">Use my default model</option></select>',
        {desc:'The model App Studio builds apps with.',more:'AgentOS won’t switch to another model on its own.',f:'build model app studio'}),
    ],{f:'agent identity name workspace lead'}));
    P.push(`<div id="agents-list" data-f="agents specialists sub agents brain hands permissions skills soul new agent"><p class="mut">loading…</p></div>`);
    setTimeout(renderAgentsList,0);
    /* The team: each specialist may answer on its OWN provider — a researcher on a
       local model, a validator on Claude, a writer on GPT — and they can hand work to
       each other and talk it through in a huddle. One switch turns that off (one
       bill, one provider), and each row pins one agent. Both apply on the spot, like
       the brain above. The badge each agent wears on the Crew stage and in chat is
       the same answer these rows show (fabric.agent_brain). Terminal: `bento team`. */
    P.push(pGroup('Working together',[
      pRow('Agents answer on their own providers',pSwitch('s-team-own',!cfg.team||cfg.team.own_brains!==false),
        {desc:'Let each agent use the model you pin for it.',
         more:'Agents on different providers can then work together and talk it through in a huddle. When off, every agent uses the brain above.',
         f:'team agents providers multiple own brain model per agent mix openai claude gemini huddle'}),
      pRow('Who answers on what','<div id="s-team-list" class="team-list mut">loading…</div>',
        {stack:true,desc:'Pick a model for any agent.',
         more:'If its provider is off or has no key, the agent uses the brain above until that’s fixed.',
         f:'team agent model pin provider per agent'}),
      /* Agents messaging each other mid-task (ask_agent). Matrix: each pair is a
         permission, and an empty cell asks you — "Allow & remember" fills it. Swarm:
         every cell you have not blocked is open, so they recruit each other freely,
         still inside the loop, hop and budget limits. Off: no agent can message
         another. It applies on the spot; `bento team talk` is the terminal's switch. */
      pRow('Agents message each other',pSelect('s-team-talk',[
          ['matrix','Ask me first (the matrix below)'],
          ['swarm','Swarm: they work together freely'],
          ['democracy','Democracy: 2 of 3 decide'],
          ['off','Off']],(cfg.team&&cfg.team.talk)||'matrix'),
        {desc:'Let an agent ask a colleague for help in the middle of a task.',
         more:'The colleague answers with its own model and permissions. In Swarm your lead also hands your specialists work without asking. In Democracy those same steps go to a vote of three of your agents, on different brains where they can be, and a majority decides. Huddles end with a vote too. Loops are refused and each task has a question limit.',
         f:'team agents message talk each other swarm democracy vote quorum matrix permission ask'}),
      /* Free talk (24f-freetalk.js): the one time agents talk with nobody asking them
         anything, so it is started here by the person, after a caution they tick, and it
         ends on its clock or its message count. And the one place that lists every time
         agents talked to each other. `bento team freetalk` / `bento team log`. */
      pRow('Let them talk','<div id="s-team-freetalk" class="ft-box mut">loading…</div>',
        {stack:true,desc:'Let your agents talk among themselves for a few minutes. Experimental.',
         more:'It stops at the time or message limit you pick, when they run out of things to say, or when you press Stop. Every message is kept.',
         f:'free talk let them talk agents talk among themselves open floor swarm minutes messages experimental risky'}),
      pRow('Agent-to-agent talk','<div id="s-team-talklog" class="ft-log mut">loading…</div>',
        {stack:true,desc:'Every time your agents talked to each other.',
         more:'Free talks, huddles and one agent asking another. Open one in Chat, or replay its run with every step.',
         f:'agent to agent chat talk log history conversation huddle ask transcript record'}),
      /* The limits: how far a question travels, how many one task may send, how often a
         colleague may ask back, and a huddle's size. Defaults are conservative; each has a
         ceiling no setting passes, because every one multiplies model calls. */
      pRow('Limits','<div id="s-team-limits" class="team-limits mut">loading…</div>',
        {stack:true,desc:'How far agents can go when they ask each other.',more:'Limits count per task and apply from the next question.',
         f:'team limits hops budget clarify ask back huddle rounds agents swarm'}),
      pRow('Who may ask whom','<div id="s-team-matrix" class="team-matrix mut">loading…</div>',
        {stack:true,desc:'Rows ask, columns answer. Tap a cell to switch between ask me, allow and block.',
         more:'Allow and block are normal permissions, so you can also review them in the Permissions app.',
         f:'team matrix who may ask whom agents grid permission'}),
      /* Linked teams: another Bento (mutual TLS) or another account here. The way in is
         Ask → Approve with six digits on both screens (the OAuth device flow); an invite
         code is folded away for headless machines. A link grants nothing: what their
         agents may ask yours is chosen per agent, and never opened by swarm. `bento
         link` is the terminal's face; SUI is this page, nothing touches the compositor. */
      pRow('Linked teams','<div id="s-team-links" class="team-links mut">loading…</div>',
        {stack:true,desc:'Let your agents work with another team, on another machine or another account here.',
         more:'Both screens show the same six digits when you link. Nothing gets through until you choose which of your agents they can ask, and their answers are treated as untrusted.',
         f:'team linked teams remote machine mtls pair invite account handshake federation link request approve'}),
    ],{f:'team agents providers huddle'}));
    setTimeout(paintTeamBrains,0);
    setTimeout(paintTeamLinks,0);
    setTimeout(paintTeamMatrix,0);
    setTimeout(paintTeamLimits,0);
    setTimeout(freeTalkPaint,0);
    setTimeout(talkLogPaint,0);
    P.push(`<div class="pgroup" data-f="map graph permissions who may reach what agents brains hands teams missions"><h3>The map</h3><p class="mut" style="margin:0 0 8px">Every agent, what it thinks with, what it can reach and who it can ask. Tap an agent to see only its lines.</p><div id="agents-graph" class="agraph mut">loading…</div></div>`);
    setTimeout(renderAgentsGraph,0);

    P.push(pGroup('Content from outside',[
      pRow('After reading a web page or an MCP reply',pSelect('s-taint',[
        ['ask','Ask before anything that changes something'],
        ['strict','Refuse to change anything for the rest of the turn'],
        ['off','No extra caution']],(cfg.security&&cfg.security.taint)||'ask'),
        {desc:'Web pages and outside servers can hide instructions meant to trick your agent.',
         more:'This applies for the rest of that turn, even at Full autonomy, which trusts your instructions and nobody else’s.',
         f:'taint injection untrusted prompt security web page mcp'}),
      pRow('Conversation history',pSelect('s-hist-compact',[
        ['on','Summarise older turns when the thread outgrows the model'],
        ['off','Drop them instead']],(cfg.history&&cfg.history.compact===false)?'off':'on'),
        {desc:'What happens when a long thread no longer fits the model.',more:'Either way, the conversation tells you when it happens.',
         f:'history compaction summary context window long thread'}),
    ],{f:'security untrusted injection history'}));
    /* Sharing the agent belongs on the page that answers "who is my agent" —
       11c-agentshare.js renders it, agentbundle.py decides everything. */
    P.push(`<div id="agent-share-box" class="pgroup" data-f="share fork agent bundle export import publish"><h3>Share this agent</h3><p class="mut">checking…</p></div>`);
    setTimeout(renderAgentShare,0);
  }
  if(want('locale')){
    P.push(`<h2>Locale</h2><p class="lead">Where and when you are, so news, weather, prices and holidays fit where you live. ${pInfo('The desktop session also takes your timezone and language from here.')}</p>`);
    P.push(`<div class="pgroup" data-f="locale region country timezone language units clock"><div id="loc-box"><div class="prow"><div class="pl"><small>…</small></div></div></div></div>`);
  }
  if(want('keys')){
    P.push(`<h2>Shortcuts</h2><p class="lead">Click a shortcut, then press the keys you want. ${pInfo('Shortcuts marked session keep working even while a native app has the keyboard.')}</p>`);
    P.push(`<div class="pgroup" data-f="shortcuts keyboard keys bindings hotkeys"><div id="sc-list"></div></div>`);
    P.push(pGroup('',[
      pRow('Restore defaults','<button class="endbtn" onclick="scReset()">Restore</button>',{desc:'Put every shortcut back the way it was.',f:'shortcuts reset'}),
      pRow('Re-apply to session','<button class="endbtn" onclick="scApplySession()">Apply</button>',{desc:'Send these shortcuts to the desktop session again.',f:'shortcuts session apply'}),
    ],{f:'shortcuts actions'}));
  }
  if(want('voice')){
    P.push(`<h2>Voice</h2><p class="lead">Dictate with the mic in the prompt bar or chat, and have replies read aloud.</p>`);
    P.push(pGroup('Speech',[
      pRow('Speak replies aloud',pSwitch('v-tts',VOICE.tts),{desc:'Read every answer out loud.',f:'tts speak voice'}),
      /* Which engine turns text into speech (agentos/speech.py, 11f-speech.js). The
         browser's own voices are the default; the rest are the server's, and the cloud
         ones cost money per character, so the engine is the machine's setting. */
      pRow('Voice engine','<div id="v-engine-box" class="sp-box mut">loading…</div>',
        {stack:true,desc:'This browser, this computer, or ElevenLabs, OpenAI or Google Cloud.',
         more:'The cloud voices sound more natural and cost money per character. Your keys stay on this computer, and every line is kept so a replay costs nothing.',
         f:'voice engine tts elevenlabs openai google cloud text to speech system say piper espeak natural voices'}),
      pRow('Voice','<select id="v-voice"></select>',{desc:'Your lead agent’s voice.',f:'tts voice picker'}),
      pRow('Each agent speaks in its own voice',pSwitch('v-agents',VOICE.agents!==false),
        {desc:'Hear huddles and free talk, with a different voice for each agent.',
         more:'Works with voice on, or in Jarvis mode. Voices come from this device, so a device with few voices tells them apart by pitch.',
         f:'voice agents each own voice huddle free talk jarvis multiple speakers'}),
      pRow('Speak as it answers',pSwitch('v-live',VOICE.live!==false),
        {desc:'Starts talking at the first sentence instead of waiting for the whole reply.',
         more:'With ElevenLabs or OpenAI the sound plays while it is being made. While your lead searches or reads something, it says what it is doing.',
         f:'realtime real time live streaming tts speak as it answers low latency socket engaged'}),
      pRow('Speech rate',pText('v-rate',VOICE.rate||1,'','number'),{f:'speech rate'}),
      pRow('Mic language',pText('v-lang',VOICE.lang||'en-IN','en-IN, en-US, hi-IN…'),{desc:'The language dictation listens for.',f:'mic language dictation'}),
    ],{f:'voice tts speech microphone'}));
  }
  if(want('look')){
    P.push(`<h2>Appearance</h2><p class="lead">How the desktop looks. Themes can change colours, fonts and even the whole shell.</p>`);
    P.push(pGroup('Theme',[
      pRow('Desktop theme',pSelect('s-theme',Object.entries(allThemes()).map(([k,t])=>[k,(t.label||t.name||k)+(t.custom?' ·':'')]),CURRENT_THEME)
        +`<button class="endbtn" onclick="openApp('themes')">Gallery</button>`,{f:'theme appearance'}),
      pRow('Wallpaper','<button class="endbtn" onclick="openApp(\'personalize\')">Personalize</button><button class="endbtn" onclick="wpSystem()">Use system</button>',
        {desc:'Make one with AI, pick one from the gallery, or use your system’s.',f:'wallpaper background'}),
      pRow('Fullscreen','<button class="endbtn" onclick="toggleFullscreen()">Toggle (F11)</button>',{f:'fullscreen'}),
    ],{f:'appearance theme wallpaper'}));
    /* The characters are not part of the immersive look: a face beside a message
       helps in the standard desktop too, so they have their own group, and their
       own switch for somebody who would rather read text. The faces shown here are
       the editor's doors; each specialist's is on its card in Missions → Agents.
       Terminal: `bento avatar` (list / show / set / reroll) — same recipes. */
    P.push(pGroup('Characters',[
      pRow('You and your agent',
        `<button class="endbtn av-set-btn" onclick="avatarEdit('@me')" title="Change how you look">${avatarImg('@me','av-set')}You</button>`
        +`<button class="endbtn av-set-btn" onclick="avatarEdit('@agent')" title="Change how your agent looks">${avatarImg('@agent','av-set')}Your agent</button>`,
        {desc:'You, your agent and every specialist each have a pixel-art character.',
         more:'Click a face to change it. You can also ask your agent, or use bento avatar in a terminal.',
         f:'characters avatars faces pixel art people specialists agent me chat logs crew look'}),
      pRow('Faces beside messages',pSwitch('s-av-on',!AVATARS.off),
        {desc:'Turn off to see plain names instead. Remembered by this browser.',
         f:'characters avatars faces off plain text chat logs'}),
    ],{f:'characters avatars faces'}));
    /* The Office is the crew's scene, so its design lives beside the characters: the
       style, the name on the door, the pet — and "describe it", which the machine's
       brain turns into a design (POST /api/office/design, the same call as the
       Office's own Design panel and the setup step). Departments and who sits where
       stay in the Office, where you can see the desks. Terminal: `bento office`. */
    P.push(`<div class="pgroup" data-f="office scene crew playground design style pet name describe"><h3>Office</h3><div id="s-office"><div class="prow"><div class="pl"><small>…</small></div></div></div></div>`);
    /* A look laid over the theme, not a theme: it is a switch here rather than
       a card in the gallery so that it composes with whichever theme is on.
       Applied the moment it is flipped, like the theme select above — Save is
       for the machine's settings, and this one lives in this browser. */
    P.push(pGroup('Immersive experience',[
      pRow('Immersive experience',pSwitch('s-imm',typeof immersiveOn==='function'&&immersiveOn()),
        {desc:'Adds depth, glass and richer colour on top of your theme.',
         more:'On by default and remembered by this browser. Themes → Effects tones it down on a slow machine. The TUI has no wallpaper or glass, so it has no switch.',
         f:'immersive experience beta premium look glass wallpaper parallax depth macos'}),
      /* The second scene draws the machine's own moving parts. Its cost is
         stated in the row, and so is the terminal's answer: none. */
      pRow('Scene',pSelect('s-imm-scene',[['aurora','Aurora: a sky that follows the day'],['movement','Movement: one slow dial of everything'],['crew','Crew: your specialists at work'],['office','Office: the whole office behind your windows'],['world','World: your agents with feelings (experimental)'],['mind','Mind: your agents and what they know, connected']],
          (typeof IMMERSIVE!=='undefined'&&IMMERSIVE.scene)||'aurora'),
        {desc:'What the wallpaper shows behind your windows.',
         more:'Movement draws at most twenty times a second, pauses when hidden, holds still under reduced motion and uses no blur. Crew shows only the specialists you actually have. World is an experiment: your agents get feelings from what they really do, and all of it sleeps when you pick another scene. Mind draws every memory, fact, mission and run as a strand from your lead, and sparks only when something runs.',
         f:'scene movement watch automatic aurora wallpaper live crew characters avatars figures specialists animated world sims feelings emotions experimental mind brain neural connections'}),

    ],{f:'immersive experience beta look scene movement'}));
  }
  if(want('system')){
    P.push(`<h2>System</h2><p class="lead">The machine itself. Network, displays, sound and the session are in System Settings.</p>`);
    /* Accounts are a machine-level fact and this is where somebody looks for one,
       so the row belongs here — but the app stays the single place they are
       managed. A second roster in Settings would be two lists to keep true, and
       the one nobody demos is the one that drifts. */
    P.push(pGroup('Accounts',[
      pRow('People on this machine','<button class="endbtn" onclick="openApp(\'users\')">Open Users</button>',
        {desc:'Who can sign in, their roles, and what they share.',
         more:'AgentOS stays single-user until you add the first account. After that it asks who you are, at the keyboard and from a phone.',
         f:'users accounts people roles admin executor sign in multi-user shared folders'}),
    ],{f:'users accounts multi-user'}));
    /* The Pi switch. It is in Settings and not only in the installer because the
       machine it matters on is the one you set up once and then reach over SSH
       from a phone — and because what it costs has to be readable before you
       choose it, not discovered the first time a search takes 30 seconds. */
    P.push(pGroup('Footprint',[
      pRow('Profile',pSelect('s-profile',[
          ['auto','Auto: decide from this machine'],
          ['full','Full: keep the MCP catalogue and refresh it daily'],
          ['lite','Light: keep only what this machine uses']],cfg.profile||'auto'),
        {desc:'Light suits a small machine like a Raspberry Pi.',
         more:'It downloads the MCP catalogue only while you search, and keeps telemetry for 7 days instead of 30.',
         f:'profile lite light footprint raspberry pi memory disk mcp catalogue small machine'}),
      pRow('Now','<span id="s-profile-now" class="mut">…</span>',
        {desc:'What this machine is using and keeping right now.',f:'profile current'}),
    ],{f:'footprint profile lite pi'}));
    setTimeout(paintProfile,0);
    P.push(pGroup('Version',[
      pRow('This build','<span id="s-ver" class="mut">checking…</span>',
        {desc:'AgentOS checks for updates and asks before installing one.',
         more:'An update is tested before it’s applied. Then the service restarts and this page reloads.',
         f:'version update upgrade check for updates auto-update'}),
      pRow('Check automatically',pSwitch('s-upd-on',true),
        {desc:'Only the check is automatic. Nothing installs without your OK.',f:'automatic update check'}),
      // Where updates come from is a setting, so a fork under test is followed
      // here, by the background check and by `bento update` alike.
      pRow('Update source',`<span class="row" style="gap:6px;flex-wrap:wrap">
          <input id="s-upd-repo" placeholder="owner/name" style="flex:1 1 180px;min-width:0" title="GitHub repository: owner/name or a github.com URL">
          <input id="s-upd-branch" placeholder="master" style="flex:0 1 140px;min-width:0" title="branch">
        </span><span id="s-upd-src" class="mut" style="display:block;margin-top:4px"></span>`,
        {desc:'The repository and branch updates come from.',
         more:'Point it at a fork to test one. Run bento update --official to go back.',
         f:'update source repository fork branch remote'}),
    ],{f:'version updates'}));
    setTimeout(paintVersion,0);      // live, and it makes a network call
    P.push(pGroup('Setup',[
      pRow('Open Setup','<button class="endbtn" onclick="openApp(\'setup\')">Open the app</button>',
        {desc:'The setup steps in a normal window you can open any time.',
         more:'Steps you’ve already done show a tick. Nothing here deletes anything.',
         f:'setup onboarding wizard app steps arc walkthrough tour open'}),
      pRow('Run it again from the start','<button class="endbtn" onclick="obRestart()">Walk me through it</button>',
        {desc:'Go through setup again, full screen.',
         more:'Anything you skipped is offered again. This doesn’t reset anything. Use Factory reset below for that.',
         f:'setup onboarding wizard first run walkthrough tour again restart start over run through'}),
    ],{f:'setup onboarding'}));
    P.push(pGroup('Machine',[
      pRow('System Settings','<button class="endbtn" onclick="openApp(\'syssettings\')">Open</button>',
        {desc:'Network, Bluetooth, displays, sound, power, session and optional components.',f:'system settings network displays'}),
      pRow('Permissions','<button class="endbtn" onclick="openApp(\'permissions\')">Open</button>',{desc:'What apps and the agent are allowed to do.',f:'permissions grants'}),
      pRow('Snapshots','<button class="endbtn" onclick="openApp(\'snapshots\')">Open</button>',{desc:'Restore points for the whole OS.',f:'snapshots restore'}),
    ],{f:'system machine'}));
    P.push(pGroup('Danger zone',[
      pRow('Factory reset','<button class="endbtn" style="border-color:var(--err);color:var(--err)" onclick="factoryReset()">Reset…</button>',
        {danger:true,desc:'Erases everything and runs first-time setup again.',
         more:'Memory, knowledge, conversations, apps, agents, settings and accounts are all deleted. Only an admin can do it, on the machine itself or with bento reset. Take a Snapshot first.',f:'factory reset wipe danger environment start over clean onboarding again everything'}),
    ],{danger:true,f:'danger zone factory reset'}));
  }
  main.innerHTML=P.join('')+`<div class="savebar"><button class="pact" onclick="saveSettings()">Save</button></div>`;
  const th=main.querySelector('#s-theme');
  if(th)th.onchange=()=>{applyTheme(th.value);toast('theme applied')};
  const im=main.querySelector('#s-imm');
  if(im)im.onchange=()=>setImmersive(im.checked);
  const avs=main.querySelector('#s-av-on');
  if(avs)avs.onchange=()=>setAvatarsOff(!avs.checked);
  const tt=main.querySelector('#s-team-talk');
  if(tt)tt.onchange=async()=>{
    await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({team:{talk:tt.value}})});
    cfg.team={...(cfg.team||{}),talk:tt.value};paintTeamMatrix();
    toast({matrix:'agents ask you before messaging a new colleague',swarm:'swarm: your agents work together without asking you',off:'agents no longer message each other'}[tt.value])};
  const tw=main.querySelector('#s-team-own');
  if(tw)tw.onchange=async()=>{
    await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({team:{own_brains:tw.checked}})});
    cfg.team={...(cfg.team||{}),own_brains:tw.checked};paintTeamBrains();
    toast(tw.checked?'agents answer on their own providers':'every agent uses this machine\u2019s brain')};
  const sc=main.querySelector('#s-imm-scene');
  if(sc)sc.onchange=()=>setImmersiveScene(sc.value);
  if(main.querySelector('#sc-list')){scLoad();scRender()}
  if(main.querySelector('#loc-box'))locRender();
  if(main.querySelector('#s-office'))officeSettingsPaint();
  if(main.querySelector('#v-voice'))settingsVoices();
  if(main.querySelector('#v-engine-box'))speechPaint();
  const bm=main.querySelector('#s-build-model');
  if(bm)fetch('/api/models').then(r=>r.json()).then(d=>{
    const cur=(cfg.build&&cfg.build.model)||'';
    bm.innerHTML='<option value="">Use my default model'+(d.default?' · '+d.default:'')+'</option>'+
      (d.models||[]).map(m=>`<option value="${esc(m.id)}" ${m.id===cur?'selected':''}>${esc(m.id)}</option>`).join('');
    if(cur&&![...bm.options].some(o=>o.value===cur))
      bm.insertAdjacentHTML('beforeend',`<option value="${esc(cur)}" selected>${esc(cur)} · unavailable right now</option>`);
    bm.value=cur;
  }).catch(()=>{});
}
function settingsVoices(){
  const vsel=$('#v-voice');
  const fill=()=>{
    if(!window.speechSynthesis||!vsel)return;
    const vs=speechSynthesis.getVoices();
    vsel.innerHTML='<option value="">(default)</option>'+vs.map(v=>
      `<option value="${esc(v.name)}" ${VOICE.voice===v.name?'selected':''}>${esc(v.name)} · ${esc(v.lang)}</option>`).join('');
  };
  fill();
  if(window.speechSynthesis)speechSynthesis.onvoiceschanged=fill;
}
/* The model picker in Settings → AI providers. Fetched rather than read from
   cfg, because what can answer is a live question — a provider's catalogue, the
   models Ollama has pulled, and any executor this machine forwards to. */
/* The version row. Answers from the last check so opening Settings is instant;
   "Check now" is the one that goes and looks. */
/* Live, because the answer is a fact about the machine (how much RAM, what is on
   disk) rather than a setting — and because switching writes the retention keys,
   so the row has to be re-read rather than assumed. */
async function paintProfile(){
  const el=document.getElementById('s-profile-now');if(!el)return;
  const sel=document.getElementById('s-profile');
  if(sel&&!sel._wired){
    sel._wired=1;
    sel.onchange=async()=>{
      el.textContent='applying…';
      const r=await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({profile:sel.value})});
      const d=await r.json().catch(()=>({}));
      if(d.error)toast(d.error);else toast('✓ profile: '+sel.value);
      await loadConfig();paintProfile();
    };
  }
  try{
    const d=await (await fetch('/api/profile')).json();
    el.innerHTML=esc(d.description||'')
      +(d.mcp_cache_bytes?` · MCP cache ${Math.round(d.mcp_cache_bytes/1024)} kB on disk`
                         :' · nothing cached on disk');
  }catch(e){el.textContent='could not read it'}
}
async function paintVersion(check){
  const el=document.getElementById('s-ver'); if(!el)return;
  el.textContent='checking…';
  let d={};
  try{d=await (await fetch('/api/update'+(check?'?check=true':''))).json()}catch(e){
    el.textContent='could not check';return}
  const sw=document.getElementById('s-upd-on'); if(sw)sw.checked=d.enabled!==false;
  const rp=document.getElementById('s-upd-repo'),br=document.getElementById('s-upd-branch'),srcNote=document.getElementById('s-upd-src');
  if(rp&&document.activeElement!==rp)rp.value=d.repo||'';
  if(br&&document.activeElement!==br)br.value=d.branch||'';
  if(srcNote)srcNote.textContent=d.official===false
    ?`a fork, pulled from git remote '${d.remote||''}'. Origin still points at the official repository.`
    :'the official repository';
  const btn=`<button class="endbtn" style="margin-left:10px" onclick="paintVersion(1)">Check now</button>`;
  if(d.update_available){
    // Never a dead button: when an update cannot be installed the reason is the
    // sentence, not a control that fails when pressed.
    /* What is actually arriving, from git. "A new version is available" is not a
       reason to restart the machine somebody is working on; the list of changes
       is. CHANGELOG.md is still shown when there is one, but between releases it
       says nothing, and the commits always do. */
    const ch=(d.changes||[]).length?`<div class="upd-log">${
      (d.changes||[]).slice(0,15).map(c=>
        `<div><code>${esc(c.hash)}</code> ${esc(c.title)}</div>`).join('')}${
      (d.changes||[]).length>15?`<div class="mut">…and ${d.changes.length-15} more</div>`:''}</div>`:'';
    /* Two different pieces of news, and they used to be printed as one:
       "0.2.0 → 0.2.0 available" is what a machine says when it is behind by
       COMMITS and the version file has not moved. The version bump is a release;
       the commits are the code. */
    const bumped=d.latest&&d.latest!==d.current;
    const n=d.behind||0;
    const head=bumped
      ? `<b>${esc(d.current)}</b> → <b style="color:var(--acc)">${esc(d.latest)}</b> available`
      : `<b>${esc(d.current)}</b>${d.build?` <code class="mut">${esc(d.build)}</code>`:''} <b style="color:var(--acc)">· ${n} change${n===1?'':'s'} waiting</b>`
        +` <span class="mut">on ${esc(d.tracks||'')}</span>`;
    /* On another branch and nothing else in the way: offer the switch as a button,
       with what it does in the confirm, rather than a sentence about a CLI flag. */
    const act=d.can_apply?` <button class="pact" style="margin-left:10px" onclick="updateNow(this)">Update now</button>`
      :d.can_switch?` <button class="pact" style="margin-left:10px" onclick="updateNow(this,true)">Switch to ${esc(d.tracks||d.branch||'')} and update</button>`
        +`<div class="mut" style="margin-top:4px">This copy is on ${esc(d.on_branch||'another branch')}. Updating checks out ${esc(d.tracks||d.branch||'')} first.</div>`
      :`<div class="mut" style="margin-top:4px">${esc(d.blocked_reason||'')}</div>`;
    el.innerHTML=head+act+btn+ch+verRollback(d);
  }else{
    /* "Up to date" has to say up to date WITH WHAT. A checkout sitting on another
       branch is the commonest reason a push seems to have no effect, and it was
       invisible here: the panel compared against a branch this copy is not on and
       reported the good news. */
    const where=d.mismatch
      ? `up to date with ${esc(d.tracks||'')}, but this copy is on ${esc(d.on_branch||'another branch')}`
      : (d.latest?`up to date with ${esc(d.tracks||'')}`:'not checked yet');
    el.innerHTML=`<b>${esc(d.current||'?')}</b>${d.build?` <code class="mut">${esc(d.build)}</code>`:''} `
      +`<span class="mut">${d.error?esc(d.error):where}</span>`+btn+verRollback(d);
  }
}
/* The last update can be taken back while it is still what this copy runs. */
function verRollback(d){
  const r=d&&d.rollback;if(!r)return '';
  const when=r.at?new Date(r.at*1000).toLocaleString([],{dateStyle:'medium',timeStyle:'short'}):'';
  return `<div class="upd-back"><span class="mut">Updated${when?' '+esc(when):''}${r.version?' from '+esc(r.version):''}${r.branch?' on '+esc(r.branch):''}.</span>
    <button class="endbtn" onclick="updateRollback(this,'${esc(r.to)}','${esc(r.version||r.to)}')">Roll back to ${esc(r.version||r.to)}</button></div>`;
}
async function updateRollback(btn,to,label){
  if(!confirm('Roll back to '+label+' ('+to+')? AgentOS restarts on the older code. Your data stays, and you can update again later.'))return;
  btn.disabled=true;btn.textContent='Rolling back…';
  try{
    const r=await fetch('/api/update/rollback',{method:'POST'});
    const d=await r.json().catch(()=>({}));
    if(!d.ok){btn.disabled=false;btn.textContent='Roll back';toast(d.error||'could not roll back')}
    else toast('Rolling back to '+label+'. This page comes back on its own.');
  }catch(e){/* the server restarts mid-request on success */}
}
async function updateNow(btn,sw){
  if(sw&&!confirm('Check out the branch updates track, then update? Your own uncommitted changes would stop it, so nothing of yours is overwritten.'))return;
  btn.disabled=true;btn.textContent='Updating…';
  try{
    const r=await fetch('/api/update',{method:'POST',headers:{'Content-Type':'application/json'},body:sw?'{"switch":true}':'{}'});
    const d=await r.json();
    if(!d.ok&&d.error){btn.disabled=false;btn.textContent='Try again';toast(d.error)}
  }catch(e){/* the server restarts mid-request on success — update_done is the real signal */}
}
/* The same two coupled selects as the chat header, painted from the same
   `/api/brains` state — executor, then one of ITS models. It used to be one
   select with engines in an optgroup above the models, and both halves marked
   their own selection: with Claude Code as the engine and a Gemini model still
   in config, TWO options carried `selected` and the browser kept the last one,
   so the control read "gemini" while the machine forwarded to Claude Code. */
async function paintModelPicker(refresh){
  const sel=document.getElementById('s-model'),ex=document.getElementById('s-brain');
  if(!sel&&!ex)return;
  const btn=document.getElementById('s-model-refresh');
  const count=document.getElementById('s-model-count');
  if(refresh&&btn){btn.disabled=true;btn.textContent='↻ Asking…'}
  if(refresh&&count)count.textContent='asking each provider…';
  // A refresh is a real round trip to every enabled provider, so it is asked for
  // rather than done on every repaint — a Settings tab that stalled behind three
  // network calls would be worse than a list that is a minute old.
  try{
    // refresh=1 rather than a cache-buster: the probes are cached SERVER-side
    // (each one is a process), so only an explicit ask should pay for them.
    const d=await (await fetch('/api/brains'+(refresh?'?refresh=1':''))).json();
    if(d&&d.executors)BRAINS=d;
  }catch(e){}
  if(btn){btn.disabled=false;btn.textContent='↻ Refresh'}
  const list=BRAINS.executors||[],cur=BRAINS.current||{};
  if(ex){
    const grp=(label,kind)=>{
      const items=list.filter(e=>e.kind===kind);
      if(!items.length)return '';
      return `<optgroup label="${esc(label)}">`+items.map(e=>
        `<option value="${esc(e.id)}"${e.id===cur.executor?' selected':''}${e.available?'':' disabled'}>`
        +esc(e.name)+(e.available?(e.detail?' · '+esc(e.detail):''):' · '+esc(e.reason||'not available'))
        +'</option>').join('')+'</optgroup>';
    };
    const none=cur.executor?'':'<option value="" selected>Nothing set</option>';
    ex.innerHTML=none+grp('Models, answered by '+((cfg&&cfg.agent_name)||'Aria'),'provider')
                +grp('Other agents','agent');
  }
  const chosen=list.find(e=>e.id===cur.executor);
  if(sel){
    const mods=(chosen&&chosen.models)||[];
    sel.innerHTML=mods.length?mods.map(m=>
      `<option value="${esc(m.id)}"${m.id===cur.model?' selected':''}>${esc(m.name||m.id)}</option>`).join('')
      :`<option value="">No models yet. Add a key below or pull one in Model Manager</option>`;
    // A model set in config that the providers no longer offer must stay visible
    // and selected, or opening Settings would silently look like something else
    // is answering.
    if(cur.model&&!mods.some(m=>m.id===cur.model))
      sel.insertAdjacentHTML('afterbegin',`<option value="${esc(cur.model)}" selected>${esc(cur.model)} (not currently offered)</option>`);
    sel.disabled=!mods.length;
  }
  // What was actually found, per executor — the answer to "did adding that key
  // work?" and "did my pull land?", which the picker alone cannot give.
  if(count){
    const provs=list.filter(e=>e.kind==='provider'&&e.available);
    const n=provs.reduce((s,e)=>s+e.models.length,0);
    const per=provs.map(e=>`${esc(e.id)} ${e.models.length}`).join(' · ');
    const agents=list.filter(e=>e.kind==='agent'&&e.available).map(e=>esc(e.name));
    count.innerHTML=n?`<b>${n}</b> model${n===1?'':'s'}: ${per}`
                     :`None found. Enable a provider below or pull one in <a href="#" onclick="openApp('models');return false">Model Manager</a>`;
    count.innerHTML+=agents.length?` · agents here: ${agents.join(', ')}`
      :` · no other agents installed. See <a href="#" onclick="SETTAB='executors';localStorage.setItem('settab','executors');refreshApp('settings');return false">Executors</a>`;
  }
}
async function pickExecutor(id){
  if(!id)return;
  const ex=(BRAINS.executors||[]).find(e=>e.id===id);
  if(await setBrain(id,ex?ex.model:''))paintModelPicker();
  if(typeof paintEngineSelect==='function'&&document.getElementById('s-engine'))renderExecutors();
}
async function pickModel(id){
  const cur=(BRAINS.current||{}).executor;
  if(!cur)return;
  if(await setBrain(cur,id)){paintModelPicker();refreshApp('models')}
}
async function saveSettings(){
  // only the open category is in the DOM, so save exactly what is on screen —
  // reading a field from a hidden tab would throw and lose the whole save
  const el=id=>document.getElementById(id);
  const val=id=>{const e=el(id);return e?e.value:undefined};
  const on=id=>{const e=el(id);return e?e.checked:undefined};
  const list=id=>{const v=val(id);return v===undefined?undefined:v.split(',').map(x=>x.trim()).filter(Boolean)};
  const put=(o,k,v)=>{if(v!==undefined&&v!=='')o[k]=v;return o};
  const prov=(key,idOn,idKey,idModels,idUrl)=>{
    const o={};
    if(on(idOn)!==undefined)o.enabled=on(idOn);
    const k=val(idKey);
    if(k!==undefined&&k!==''&&!k.startsWith('•'))o.api_key=k;   // masks are display-only
    if(list(idModels)!==undefined)o.models=list(idModels);
    if(idUrl&&val(idUrl)!==undefined)o.base_url=val(idUrl);
    return Object.keys(o).length?o:undefined;
  };
  if(el('v-tts')){
    VOICE.tts=on('v-tts');VOICE.voice=val('v-voice')||'';
    VOICE.rate=+val('v-rate')||1;VOICE.lang=(val('v-lang')||'').trim()||'en-IN';
    if(el('v-agents'))VOICE.agents=on('v-agents');
    if(el('v-live'))VOICE.live=on('v-live');
    saveVoice();
  }
  const patch={};
  put(patch,'workspace',val('s-workspace'));
  if(val('s-steps')!==undefined)patch.max_steps=+val('s-steps')||25;
  if(val('s-name')!==undefined)patch.agent_name=(val('s-name')||'').trim()||'Aria';
  /* NOT folders: this page no longer edits them, and sending the key at all
     would send an empty list and silently unshare everything. */
  if(on('s-sb-on')!==undefined)patch.sandbox={enabled:on('s-sb-on'),root:(val('s-sb-root')||'').trim()};
  if(val('s-taint')!==undefined)patch.security={taint:val('s-taint')};
  if(val('s-hist-compact')!==undefined)patch.history={compact:val('s-hist-compact')!=='off'};
  const providers={};
  const add=(k,v)=>{if(v)providers[k]=v};
  add('ollama',val('s-ollama-url')!==undefined?{base_url:val('s-ollama-url')}:undefined);
  add('anthropic',prov('anthropic','s-ant-on','s-ant-key','s-ant-models'));
  add('openai',prov('openai','s-oai-on','s-oai-key','s-oai-models'));
  add('openrouter',prov('openrouter','s-or-on','s-or-key','s-or-models'));
  add('custom',prov('custom','s-cus-on','s-cus-key','s-cus-models','s-cus-url'));
  add('google',prov('google','s-goo-on','s-goo-key','s-goo-models'));
  if(Object.keys(providers).length)patch.providers=providers;
  if(val('s-build-model')!==undefined)patch.build={model:val('s-build-model')};
  if(val('s-img-prov')!==undefined)patch.image={provider:val('s-img-prov'),model:(val('s-img-model')||'').trim()};
  const ght=(val('s-gh-token')||'').trim();
  if((ght&&!ght.startsWith('•'))||val('s-gh-user')!==undefined)
    patch.github={...(ght&&!ght.startsWith('•')?{token:ght}:{}),username:(val('s-gh-user')||'').trim()};
  /* `s-engine` is NOT read here: it applies the moment it changes, through
     /api/brain, so the executor and its model are written together. Sending it
     again with the page-wide Save is a second writer for one setting, and the
     one that wins is whichever ran last. */
  if(on('s-upd-on')!==undefined)patch.updates={enabled:on('s-upd-on')};
  const urp=document.getElementById('s-upd-repo'),ubr=document.getElementById('s-upd-branch');
  if(urp||ubr){patch.updates=patch.updates||{};
    if(urp&&urp.value.trim())patch.updates.repo=urp.value.trim();
    if(ubr&&ubr.value.trim())patch.updates.branch=ubr.value.trim();}
  // Executors: the tool list is checkboxes rather than a field, so it is read
  // from the DOM directly. Only present when the Executors tab is on screen.
  if(document.getElementById('s-exec-on')!==null){
    patch.executors={claude_code:{
      enabled:on('s-exec-on'),
      workspace:(val('s-exec-ws')||'').trim(),
      model:(val('s-exec-model')||'').trim(),
      budget_usd:Number(val('s-exec-budget')||2),
      tools:[...document.querySelectorAll('[data-tool]')].filter(i=>i.checked).map(i=>i.dataset.tool),
      allow_source:on('s-exec-src'),
    }};
  }
  if(!Object.keys(patch).length){toast('nothing to save on this page');return}
  await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)});
  toast('settings saved');loadModels();loadConfig();
}


/* ---- shortcut editor: click a row, press the keys ---- */
let SC_REC=null;
function scRender(){
  const box=$('#sc-list');if(!box)return;
  box.innerHTML=Object.keys(SHORTCUTS).map(name=>{
    const sc=SHORTCUTS[name];
    return `<div class="sc-row" data-n="${esc(name)}">
      <span class="sc-l">${esc(sc.label||name)}${sc.session?'<em>session</em>':''}</span>
      <button class="sc-k">${esc(sc.keys||'—')}</button></div>`;
  }).join('');
  box.querySelectorAll('.sc-row').forEach(r=>{
    r.querySelector('.sc-k').onclick=()=>scRecord(r.dataset.n,r.querySelector('.sc-k'));
  });
}
function scRecord(name,btn){
  if(SC_REC&&SC_REC.btn)SC_REC.btn.classList.remove('rec');
  SC_REC={name,btn};btn.classList.add('rec');btn.textContent='press keys…';
  const done=e=>{
    e.preventDefault();e.stopPropagation();
    if(e.key==='Escape'){cancel();return}
    if(['Control','Alt','Shift','Meta'].includes(e.key))return;      // wait for a real key
    const parts=[];
    if(e.ctrlKey)parts.push('Ctrl');
    if(e.altKey)parts.push('Alt');
    if(e.shiftKey)parts.push('Shift');
    if(e.metaKey)parts.push('Meta');
    let k=e.key;
    if(e.code==='Space')k='Space';
    else if(k.length===1)k=k.toUpperCase();
    parts.push(k);
    const keys=parts.join('+');
    const clash=Object.keys(SHORTCUTS).find(n=>n!==name&&SHORTCUTS[n].keys===keys);
    SHORTCUTS[name].keys=keys;
    cleanup();
    scSave().then(()=>{scRender();toast(clash?`${keys} set. It was also ${SHORTCUTS[clash].label}`:`${keys} set`)});
  };
  const cancel=()=>{cleanup();scRender()};
  const cleanup=()=>{window.removeEventListener('keydown',done,true);SC_REC=null};
  window.addEventListener('keydown',done,true);
}
async function scSave(){
  const out={};Object.keys(SHORTCUTS).forEach(n=>out[n]=SHORTCUTS[n].keys);
  cfg.shortcuts=out;
  try{
    await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({shortcuts:out})});
    scApplySession(true);
  }catch(e){toast('could not save shortcuts')}
}
async function scReset(){
  SHORTCUTS=JSON.parse(JSON.stringify(SC_DEFAULTS));
  await scSave();scRender();toast('shortcuts restored');
}
async function scApplySession(quiet){
  try{
    const r=await fetch('/api/shortcuts/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});
    const d=await r.json();
    if(!quiet)toast(d.message||(d.ok?'session shortcuts applied':'not in session mode'));
  }catch(e){if(!quiet)toast('could not reach the session')}
}

/* ---- locale editor ---- */
let LOCALE=null;
async function locRender(){
  const box=$('#loc-box');if(!box)return;
  try{LOCALE=await (await fetch('/api/locale')).json()}
  catch(e){box.innerHTML=pRow('Locale','<span class="mut">could not read it</span>');return}
  const lo=LOCALE.locale, det=LOCALE.detected;
  const countries=Object.entries(LOCALE.countries).sort((a,b)=>a[1].localeCompare(b[1]));
  box.innerHTML=[
    pRow('Country / region',
      pSelect('loc-country',[['','Not set'],...countries.map(([c,n])=>[c,`${n} (${c})`])],lo.country),
      {desc:'Sets what “local” means for news, prices, holidays and sport.',f:'country region locale'}),
    pRow('Timezone',pSelect('loc-tz',[['','Not set'],...LOCALE.timezones.map(t=>[t,t])],lo.timezone),
      {desc:'Used for anything like “today” or “tonight”.',f:'timezone clock time'}),
    pRow('Language',pText('loc-lang',lo.language||'','en-IN'),{f:'language locale'}),
    pRow('City',pText('loc-city',lo.city||'','Bengaluru'),{desc:'Optional. Makes weather and local answers more precise.',f:'city location'}),
    pRow('Units',pSelect('loc-units',[['metric','Metric'],['imperial','Imperial']],lo.units),{f:'units metric imperial'}),
    pRow('Clock',pSelect('loc-clock',[['24h','24-hour'],['12h','12-hour']],lo.clock),{f:'clock 12 24 hour'}),
    pRow('Detected on this machine',
      `<button class="endbtn" onclick="locUseDetected()">Use detected</button>`,
      {desc:`${esc(det.country||'?')} · ${esc(det.timezone||'?')} · ${esc(det.language||'?')}`,f:'detected locale'}),
    pRow('Apply',`<button class="pact" onclick="locSave()">Save locale</button>`,
      {desc:esc(LOCALE.describe.split('.')[0])+'.',f:'save locale apply session'}),
  ].join('');
}
async function locSave(){
  const payload={country:$('#loc-country').value,timezone:$('#loc-tz').value,
    language:$('#loc-lang').value.trim(),city:$('#loc-city').value.trim(),
    units:$('#loc-units').value,clock:$('#loc-clock').value};
  await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({locale:payload})});
  const r=await (await fetch('/api/locale/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).json();
  await loadConfig();tickClock();locRender();
  toast(r.message||'locale saved');
}
async function locUseDetected(){
  await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({locale:{country:'',timezone:'',language:'',city:'',units:'',clock:''}})});
  await loadConfig();tickClock();locRender();toast('using the machine\'s own locale');
}

/* ---- Executors: agents already on this machine that AgentOS can delegate to ----
   Availability is a live probe rather than config, so this panel is rendered
   after the tab paints. Every control here widens or narrows the envelope a
   delegated run gets, and the sentence under the switch always states the
   envelope in full — picking "Claude Code" in Chat should never be a blind grant. */
async function renderExecutors(){
  const box=document.getElementById('exec-list');if(!box)return;
  var d=null;
  try{d=await (await fetch('/api/executors')).json()}catch(e){}
  /* The engine list, from the roster. Every executor this OS knows appears —
     installed or not — because a brain you could have is a fact you need in
     order to choose, and hiding it reads as "this OS cannot". */
  paintEngineSelect(d);
  /* A card per executor that is NOT installed, with its licence and the exact
     command. Rendered before the Claude Code detail below so the offers are not
     buried under one executor's tool checkboxes. */
  const offers=((d&&d.roster)||[]).filter(r=>!r.builtin&&!r.installed).map(r=>{
    const off=r.install||{};
    /* Same card shape as a channel: a heading that reads as a name, the licence
       as a chip, and the prose in `.ghint` — bare <p>s collided with the
       small-caps group heading and the three lines overlapped. */
    return `<div class="pgroup chan" data-f="install executor ${esc(r.id)}">
      <h3>${esc(r.title)} <span class="chdot">${esc(r.licence||'licence unknown')}</span></h3>
      <div class="ghint">${esc(r.what||'')}</div>
      <div class="ghint mut">${esc(r.why_not||'not installed')}</div>
      ${off.command?pRow('Install it',
          `<button class="endbtn" onclick="execInstallComponent('${esc(r.id)}',this)">Install ${esc(r.title)}</button>`,
          {desc:`Runs <code>${esc(off.command)}</code>${off.licence?' · '+esc(off.licence):''}${
             off.available?'':'. '+esc(off.reason||'not available here')}`,
           f:'install '+esc(r.id)})
        :`<div class="ghint mut">There’s no installer for this one here. Install it yourself
            and it will show up.</div>`}
      ${r.docs?`<div class="ghint"><button class="endbtn" onclick="openInBrowser('${esc(r.docs)}')">Read the docs</button></div>`:''}
    </div>`;
  }).join('');
  /* Into their own container, replaced rather than appended: `insertAdjacentHTML`
     on the panel put a second copy of every offer on screen each time this
     re-ran (and it re-runs after an install, which is exactly when somebody is
     looking at it). */
  const obox=document.getElementById('exec-offers');
  if(obox)obox.innerHTML=offers;
  const ex=d&&(d.executors||[]).find(e=>e.id==='claude_code');
  if(!ex){box.innerHTML=obox?'<p class="mut">could not read executors</p>'
                            :(offers||'<p class="mut">could not read executors</p>');return}
  if(!ex.available){
    /* "Not installed" used to end here, which is a dead end wearing an honest
       sentence. The exact command is shown before anything runs, and the button
       runs that command — nothing is installed without agreeing to it. */
    box.innerHTML=`<h3>Claude Code</h3><p class="mut">${esc(ex.reason||'not available')}</p>
      ${ex.install_cmd?`
        <div class="ghint">${esc(ex.install_note||'')}</div>
        ${pRow('Install it',`<button class="endbtn" id="exec-inst"
             onclick="execInstall()">Install Claude Code</button>`,
          {desc:`Runs <code>${esc(ex.install_cmd)}</code> in your own account, without sudo.`,
           f:'install claude code executor'})}
        <pre id="exec-instlog" class="exec-log" hidden></pre>`:''}
      ${ex.install?`<p class="mut"><button class="endbtn" onclick="openInBrowser('${esc(ex.install)}')">Read the docs</button></p>`:''}`;
    return;
  }
  const c=ex.config||{}, tools=c.tools||[];
  const tool=(name,desc)=>`<label class="exec-tool"><input type="checkbox" data-tool="${name}" ${tools.indexOf(name)>=0?'checked':''}> <b>${name}</b> <span class="mut">${esc(desc)}</span></label>`;
  /* How a delegated run is paid for. "Delegate this turn" reads as free when it
     is a subscription and as nothing at all when it is a metered key, and those
     are very different things to click — so it is stated before the switch. */
  const b=ex.billing||{};
  const bill=b.detail?`<div class="ghint bill ${esc(b.mode||'')}">${
    {subscription:'◆',api:'$',none:'!'}[b.mode]||'·'} ${esc(b.detail)}${
    (b.stripped||[]).length?` <span class="mut">(${esc(b.stripped.join(', '))} is set in the environment but is not passed to it)</span>`:''}</div>`:'';
  box.innerHTML=`<h3>Claude Code <span class="mut">${esc(ex.version||'')}</span></h3>
    <div class="ghint">${esc(ex.what||'')}</div>${bill}
    ${pRow('Use as an engine',pSwitch('s-exec-on',ex.enabled),
      {desc:'Adds Claude Code to the model picker in Chat, so it can answer your turns.',f:'enable claude code executor'})}
    ${ex.needs_signin?`<div class="ghint bill none">! Installed, but nobody is signed in yet. Run <code>${esc(ex.signin_cmd||'claude')}</code> once in a terminal.</div>`:''}
    ${pRow('Folder',pText('s-exec-ws',c.workspace),
      {desc:'The only folder it can read or write.',
       more:'The same folder and tools also apply to Gemini CLI and Codex when one of them is the brain.',f:'executor workspace folder gemini codex'})}
    ${pRow('Let it work on AgentOS itself',pSwitch('s-exec-src',c.allow_source),
      {desc:`Also gives it the AgentOS source at <code>${esc(ex.source_root||'')}</code>, so it can fix the OS itself.`,
       more:'Off until you turn it on. It’s told how the UI is built and that the tests must pass.',
       f:'executor agentos source develop self edit'})}
    ${pRow('Model',pText('s-exec-model',c.model,'its own default'),
      {desc:'Leave empty to let Claude Code choose.',more:'It signs in with its own account, separate from your AgentOS provider keys.',f:'executor model'})}
    ${pRow(b.mode==='subscription'?'Work limit':'Spend limit',
      pText('s-exec-budget',c.budget_usd,'','number'),
      {desc:b.mode==='subscription'
        ? 'A guard against runaway work. Your subscription isn’t billed per token.'
        : 'The most one run can spend, in US dollars. Claude Code enforces it.',
       more:b.mode==='subscription'?'Claude Code stops when its estimated cost reaches this. Ask it to carry on and it picks up where it stopped.':'',
       f:'executor budget cost limit work'})}
    ${pRow('Allowed tools',`<div class="exec-tools">
        ${tool('Read','read files')}${tool('Glob','find files')}${tool('Grep','search text')}
        ${tool('WebSearch','search the web')}${tool('WebFetch','read a page')}
        ${tool('Write','create files')}${tool('Edit','change files')}${tool('Bash','run commands')}
      </div>`,{stack:true,desc:'Anything left unticked can’t be used.',more:'You choose these before a run starts. This version of Claude Code can’t ask you for approval call by call.',f:'executor allowed tools permissions'})}
    <div class="ghint" id="exec-envelope">${esc(ex.envelope||'')}</div>`;
  const refresh=()=>{
    const t=[...box.querySelectorAll('[data-tool]')].filter(i=>i.checked).map(i=>i.dataset.tool);
    const writes=t.some(x=>x==='Write'||x==='Edit'||x==='Bash');
    const e=document.getElementById('exec-envelope');
    if(e)e.textContent=`Claude Code in ${document.getElementById('s-exec-ws').value} with `
      +(t.join(', ')||'no tools')+(writes?' (can change files and run commands)':' (read-only)')
      +`, up to $${Number(document.getElementById('s-exec-budget').value||0).toFixed(2)}`;
  };
  box.querySelectorAll('[data-tool],#s-exec-ws,#s-exec-budget').forEach(i=>{
    i.onchange=refresh;i.oninput=refresh;
  });
}

/* Installing is a visible act: the command was shown, the output streams here,
   and the panel re-probes when it finishes rather than claiming success. */
/* One list, three places it is rendered — here, in AI providers and in Chat. All
   three read /api/executors or /api/models, so none of them names an executor. */
function paintEngineSelect(d){
  const sel=document.getElementById('s-engine'); if(!sel)return;
  const cur=(cfg&&cfg.engine)||'aria';
  const rows=((d&&d.roster)||[]);
  if(!rows.length)return;                       // leave "checking…" rather than lie
  sel.innerHTML=rows.map(r=>{
    const label=r.builtin?((cfg.agent_name||'Aria')+' (the built-in agent)')
      :r.installed?(r.title+(r.version?' · '+r.version:''))
      :(r.title+' · '+(r.why_not||'not installed'));
    return `<option value="${esc(r.id)}"${r.id===cur?' selected':''}${
      r.installed?'':' disabled'}>${esc(label)}</option>`;
  }).join('');
}

/* Choosing here goes through /api/brain like every other brain change, so the
   model that executor should run on is written in the same breath. "aria" means
   "stop forwarding": the machine goes back to answering with whichever provider
   model it was last on, which is the only reading of that choice that leaves it
   ABLE to answer. */
async function pickEngine(id){
  if(!id)return;
  const list=BRAINS.executors||[];
  const target=id==='aria'
    ? (list.find(e=>e.kind==='provider'&&e.id===(BRAINS.current||{}).executor)
       ||list.find(e=>e.kind==='provider'&&e.available))
    : list.find(e=>e.id===id);
  if(!target)return toast(id==='aria'
    ?'no provider model to fall back to. Add a key or pull one first'
    :'that executor is not on this machine');
  if(await setBrain(target.id,target.model)){renderExecutors();paintModelPicker()}
}

/* Install any executor from the components catalogue. `execInstall` below is the
   Claude-Code-specific path that predates the roster and still serves its card;
   this one takes the id, so a new executor needs no new function. */
async function execInstallComponent(id,btn){
  const was=btn?btn.textContent:'';
  if(btn){btn.disabled=true;btn.textContent='Installing…'}
  try{
    const r=await fetch('/api/components/install',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});
    const d=await r.json();
    toast(d.ok?('✓ '+(d.message||'installed')):(d.message||'could not install'));
    if(d.ok){await loadModels();renderExecutors()}
  }catch(e){toast('could not reach the server')}
  finally{if(btn){btn.disabled=false;btn.textContent=was}}
}

async function execInstall(){
  const btn=document.getElementById('exec-inst'), log=document.getElementById('exec-instlog');
  if(btn){btn.disabled=true;btn.textContent='Installing…'}
  if(log){log.hidden=false;log.textContent='starting…\n'}
  try{
    const r=await fetch('/api/executors/install',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({id:'claude_code'})});
    const d=await r.json();
    if(log){log.textContent+=(d.message||'')+'\n'}
    toast(d.ok?'✓ '+(d.message||'installed'):(d.message||'could not install'));
    if(d.ok)renderExecutors();
  }catch(e){ toast('could not reach the server') }
  finally{ if(btn){btn.disabled=false;btn.textContent='Install Claude Code'} }
}
/* Progress lines from the installer, broadcast so every open surface sees them. */
function execInstallLine(ev){
  const log=document.getElementById('exec-instlog');
  if(!log)return;
  log.hidden=false;
  if(ev.line){log.textContent+=ev.line+'\n';log.scrollTop=log.scrollHeight}
}

/* ---- channels: every way in, who may use it, and how far it is trusted ----
   Each card saves on its own (PUT /api/channels/<id>) rather than through the
   page-wide Save, because a channel is a self-contained decision and because the
   server answers with why it refused — "still needs Bot token", "that one shares
   a gate with This window" — which is worth showing next to the control that
   caused it rather than as one page-level error. */
var CHAN_POSTURES=[];
async function renderChannels(){
  const box=document.getElementById('chan-list');if(!box)return;
  var d=null;
  try{d=await (await fetch('/api/channels')).json()}catch(e){}
  if(!d||!d.channels){box.innerHTML='<p class="mut">could not read channels</p>';return}
  CHAN_POSTURES=d.postures||[];
  var html=`<h3 class="chsec">Channels that reach this agent</h3>`
    +d.channels.map(chanCard).join('');
  box.innerHTML=html;
  if(typeof waPanel==='function'&&document.getElementById('wa-extra'))waPanel();
}
function chanCard(c){
  const dot={on:'ok',off:'mut',needs:'warn'}[c.status]||'mut';
  const fields=(c.fields||[]).map(f=>pRow(f.label,
      f.secret?pSecret(`ch-${c.id}-${f.key}`,!!(c.set||{})[f.key],'••••',f.placeholder)
              :pText(`ch-${c.id}-${f.key}`,(c.values||{})[f.key],f.placeholder),
      {desc:f.help,f:c.id+' '+f.label})).join('');
  /* Postures are per IO gate. Channels that share a gate say whose posture they
     follow instead of showing a select that would never be consulted. */
  const posture=c.own_gate
    ? pRow('Permissions',pSelect(`ch-${c.id}-posture`,
        CHAN_POSTURES.map(p=>[p.id,p.label]),c.posture),
        {desc:(CHAN_POSTURES.find(p=>p.id===c.posture)||{}).help||'',
         f:c.id+' permissions posture autonomy'})
    : pRow('Permissions',`<span class="mut">follows ${esc(c.posture_from||'another channel')}</span>`,
        {desc:`Same rules as that channel: ${esc(c.posture_label)}.`,
         f:c.id+' permissions'});
  const onoff=c.builtin
    ? pRow('Available',`<span class="mut">always on</span>`,
        {desc:'This is how you reach the machine, so it can’t be switched off here.',f:c.id+' always on'})
    : pRow('Switched on',pSwitch(`ch-${c.id}-on`,c.enabled),{f:c.id+' enable'});
  /* The walkthrough, open exactly when it is needed. "Create a bot with @BotFather
     and paste its token" is a fine label for the BOX; it is not instructions, and it
     assumes you know BotFather is a Telegram account you message, that /newbot
     exists, and that pairing afterwards is a separate act nobody mentioned.
     `status==='needs'` is the honest trigger: unfilled channels teach, a working one
     folds itself away rather than nagging. */
  const steps=(c.setup||[]).length?`<details class="chsteps" ${c.status==='needs'?'open':''}>
      <summary>How to set this up (${(c.setup||[]).length} steps)</summary>
      ${/* md() rather than a second inline-markdown pass: it escapes first, and it
            is what renders **bold** and `code` everywhere else in the OS. The <p>
            it wraps a single line in is styled flat below. */''}
      <ol>${c.setup.map(s=>`<li>${md(s)}</li>`).join('')}</ol>
    </details>`:'';
  return `<div class="pgroup chan" data-f="channel ${esc(c.id)} ${esc(c.title)}">
    <h3>${esc(c.title)} <span class="chdot ${dot}">${esc(c.detail)}</span></h3>
    <div class="ghint">${esc(c.what)}</div>
    ${pRow('Who can use it',`<span class="mut">${esc(c.reach)}</span>`,
      {desc:c.reach_panel?`Change that in ${esc(c.reach_panel)}.`:'',f:c.id+' who reach access'})}
    ${steps}
    ${onoff}${posture}${fields}
    ${c.note?`<div class="ghint mut">${esc(c.note)}</div>`:''}
    ${/* WhatsApp's two facts a form cannot hold: the callback URL Meta needs, and
         whether the 24-hour window is open. Filled by waPanel() after render. */''}
    ${c.id==='whatsapp'?'<div id="wa-extra" class="wa-extra"></div>':''}
    ${(c.scoped_grants?`<div class="ghint mut">${c.scoped_grants} permission rule${c.scoped_grants==1?'':'s'} apply to this channel. See the Permissions app.</div>`:'')}
    <div class="prow"><div class="pl"><small id="ch-${c.id}-msg" class="mut"></small></div>
      <div class="pc"><button class="endbtn" onclick="chanSave('${esc(c.id)}')">Save</button></div></div>
  </div>`;
}
async function chanSave(id){
  const msg=document.getElementById('ch-'+id+'-msg');
  const body={};
  const on=document.getElementById('ch-'+id+'-on'); if(on)body.enabled=on.checked;
  const po=document.getElementById('ch-'+id+'-posture'); if(po)body.posture=po.value;
  // only fields the user actually typed into: a saved secret shows as a chip
  // with no input, and sending '' for it would read as "clear this"
  document.querySelectorAll(`[id^="ch-${id}-"]`).forEach(el=>{
    const k=el.id.slice(('ch-'+id+'-').length);
    if(['on','posture','msg'].indexOf(k)>=0)return;
    if(el.tagName==='INPUT')body[k]=el.value;
  });
  if(msg){msg.textContent='saving…';msg.className='mut'}
  try{
    const r=await fetch('/api/channels/'+encodeURIComponent(id),
      {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const j=await r.json();
    if(msg){msg.textContent=j.ok?'saved':(j.error||'could not save');msg.className=j.ok?'ok':'warn'}
    if(j.ok)renderChannels();
  }catch(e){if(msg){msg.textContent='could not reach the server';msg.className='warn'}}
}

/* One row per specialist: its face, the brain it answers on RIGHT NOW (the chip),
   and a picker of every model this machine can reach. The chip is the server's
   answer (fabric.agent_brain), so a pin on a switched-off provider reads as what it
   is — pinned, and on the machine's brain until the provider is on. */
async function paintTeamBrains(){
  const box=document.getElementById('s-team-list');if(!box)return;
  let sa={},mods={};
  try{[sa,mods]=await Promise.all([fetch('/api/subagents').then(r=>r.json()),brainChoices()])}catch(e){}
  const list=(sa.subagents||[]);
  if(!list.length){box.textContent='No specialists yet. Ask for one, or create one in Missions → Build → Agents.';return}
  // provider models and the agent CLIs installed here (Claude Code, Gemini CLI, Codex)
  const models=((mods||{}).models||[]).map(m=>m.id);
  const names={};((mods||{}).models||[]).forEach(m=>names[m.id]=m.name||m.id);
  box.classList.remove('mut');
  box.innerHTML=list.map(s=>{
    const b=s.brain||{}, pin=s.model||'';
    const opts=['',...models]; if(pin&&!opts.includes(pin))opts.push(pin);
    return `<div class="team-row">${avatarImg(s.name,'av-set')}<b>${esc(s.name)}</b>
      <select data-agent="${esc(s.name)}" aria-label="Model for ${esc(s.name)}">${opts.map(m=>
        `<option value="${esc(m)}"${m===pin?' selected':''}>${m?esc(names[m]||m)+(models.includes(m)?'':' · not available now'):'This machine\u2019s brain'}</option>`).join('')}</select>
      <span class="team-now">${brainChip(b.model,b.provider_name)}${b.note?` <span class="mut">${esc(b.note)}</span>`:''}</span></div>`;
  }).join('');
  box.querySelectorAll('select[data-agent]').forEach(sel=>sel.onchange=async()=>{
    const r=await fetch('/api/subagents/'+encodeURIComponent(sel.dataset.agent)+'/brain',{method:'PUT',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({model:sel.value})}).then(r=>r.json()).catch(()=>({error:'the server did not answer'}));
    if(r.error){toast(r.error);return}
    toast(sel.dataset.agent+' now answers on '+(r.brain.provider_name||'the default'));paintTeamBrains();
  });
}

/* The matrix: rows ask, columns answer. Each cell is a grant row (fabric.matrix);
   a tap cycles ask → allow → block and writes it through PUT /api/team/matrix. In
   swarm mode an unset cell reads "swarm" (open) — only a block closes it. */
async function paintTeamMatrix(){
  const box=document.getElementById('s-team-matrix');if(!box)return;
  let d={};try{d=await (await fetch('/api/team/matrix')).json()}catch(e){}
  const names=d.agents||[], cells=d.cells||{}, talk=d.talk||'matrix';
  if(names.length<2){box.textContent='You need at least two specialists before they can message each other.';return}
  if(talk==='off'){box.classList.add('mut');box.textContent='Off. Agents can’t message each other. Choose “Ask me first”, “Swarm” or “Democracy” above to turn it on.';return}
  box.classList.remove('mut');
  const blank=talk==='swarm'?'swarm':talk==='democracy'?'vote':'ask';
  const label=(v)=>v==='allow'?'allow':v==='deny'?'block':blank;
  box.innerHTML=`<table><tr><th></th>${names.map(n=>`<th>${avatarImg(n,'')}${esc(n)}</th>`).join('')}</tr>
    ${names.map(a=>`<tr><th class="tm-row">${avatarImg(a,'')}${esc(a)}</th>${names.map(b=>{
      if(a===b)return '<td><div class="tm-self" aria-hidden="true"></div></td>';
      const v=cells[a+'>'+b]||'', cls=v==='allow'?'allow':v==='deny'?'deny':talk==='swarm'?'swarm':talk==='democracy'?'vote':'';
      return `<td><button class="tm-cell ${cls}" data-a="${esc(a)}" data-b="${esc(b)}" data-v="${v}" title="${esc(a)} → ${esc(b)}: ${label(v)}" aria-label="${esc(a)} may ask ${esc(b)}: ${label(v)}">${label(v)}</button></td>`}).join('')}</tr>`).join('')}</table>
    <div class="tm-legend">${talk==='swarm'?'Swarm: every cell you haven’t blocked is open.':talk==='democracy'?'Vote: your lead and two other agents vote on each empty cell, and 2 of 3 decide. Allow and block still win.':'Ask: you are asked the first time, and “Allow & remember” fills the cell.'}</div>`;
  box.querySelectorAll('.tm-cell').forEach(b=>b.onclick=async()=>{
    const next={'':'allow',allow:'deny',deny:'ask'}[b.dataset.v]||'ask';
    const r=await fetch('/api/team/matrix',{method:'PUT',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({from:b.dataset.a,to:b.dataset.b,effect:next})}).then(r=>r.json()).catch(()=>({error:'the server did not answer'}));
    if(r.error){toast(r.error);return}
    paintTeamMatrix();
  });
}

/* One number per limit, with its range from the server (fabric.LIMITS). Saved on
   change; a value out of range is refused with the sentence that says the range. */
async function paintTeamLimits(){
  const box=document.getElementById('s-team-limits');if(!box)return;
  let d={};try{d=await (await fetch('/api/team/limits')).json()}catch(e){}
  const L=d.limits||{},R=d.ranges||{};
  const label={hops:'Hops a question may travel',budget:'Questions per task',clarify:'Times a colleague may ask back',
    huddle_agents:'Agents in a huddle',huddle_rounds:'Rounds in a huddle'};
  box.classList.remove('mut');
  box.innerHTML=Object.keys(R).map(k=>`<label class="tl-row"><span>${esc(label[k]||k)}<small class="mut"> · ${esc(R[k].what)} (${R[k].min}–${R[k].max}, default ${R[k].default})</small></span>
    <input type="number" data-lim="${esc(k)}" min="${R[k].min}" max="${R[k].max}" value="${L[k]}"></label>`).join('');
  box.querySelectorAll('input[data-lim]').forEach(inp=>inp.onchange=async()=>{
    const r=await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({team:{limits:{[inp.dataset.lim]:+inp.value}}})}).then(r=>r.json()).catch(()=>({error:'the server did not answer'}));
    if(r&&r.error){toast(r.error);paintTeamLimits();return}
    toast((label[inp.dataset.lim]||inp.dataset.lim)+': '+inp.value);
  });
}

/* Linked teams. The way in is a REQUEST, the OAuth device flow: type the other
   machine's address (or pick an account here) and press Ask; its person gets an
   Approve / Deny card; both screens show the same six digits, computed on each side
   from the certificates that side saw — so the digits are how a person knows nobody
   is in the middle. The invite string is kept, folded away, for a machine with no
   screen to approve on. Everything is a call to /api/team/links*. */
var TEAM_INVITE=null;
function openLinkedTeams(){
  SETTAB='ai';try{localStorage.setItem('settab','ai')}catch(e){}
  openApp('settings');
  setTimeout(()=>{
    if(!document.getElementById('s-team-links'))document.querySelector('.prefs-side button[data-t="agent"]')?.click();
    setTimeout(()=>{const e=document.getElementById('s-team-links');if(e){paintTeamLinks();e.scrollIntoView({block:'start',behavior:'smooth'})}},120);
  },250);
}
function tlkReqHTML(r){
  const who=esc(r.name||'?'), id=r.identity||{};
  const face=avatarRecipeImg(id.agent,'av-set',(id.agent_name||r.name)+'’s agent');
  const team=id.agent_name?` <span class="mut">· ${esc(id.agent_name)}’s team${id.person?', '+esc(id.person):''}</span>`:'';
  if(r.kind==='account')return `<div class="tlk-req">${face}<div><p><b>${who}</b>${team} asks to link teams with you.</p>
      <small class="mut">You’re both on this machine, so there’s nothing to compare.</small></div>
    <div class="tlk-req-act"><button class="pact" onclick="teamLinkAnswer('${esc(r.id)}','approve')">Approve</button><button class="endbtn" onclick="teamLinkAnswer('${esc(r.id)}','deny')">Deny</button></div></div>`;
  return `<div class="tlk-req">${face}<div><p><b>${who}</b>${team} <span class="mut">(${esc(r.addr||'')})</span> asks to link its team with yours.</p>
      <div class="tlk-sas-row">Check that ${who} shows <span class="tlk-sas">${esc(r.sas||'')}</span></div>
      <small class="mut">If the digits differ, something is in between you, so deny it. After you approve, you still choose which of your agents they can ask.</small></div>
    <div class="tlk-req-act"><button class="pact" onclick="teamLinkAnswer('${esc(r.id)}','approve')">Approve</button><button class="endbtn" onclick="teamLinkAnswer('${esc(r.id)}','deny')">Deny</button></div></div>`;
}
function tlkOutHTML(r){
  const who=esc(r.name||r.to_name||'?');
  const st=r.state||'pending';
  const line=st==='pending'
    ?(r.kind==='account'||!r.sas?`Waiting for <b>${esc(r.to_name||r.name)}</b> to approve.`
      :`Waiting for <b>${who}</b> to approve.</p><p class="tlk-sas-row">Make sure it shows <span class="tlk-sas">${esc(r.sas)}</span>`)
    :st==='approved'?`✓ <b>${who}</b> approved. You’re linked.`
    :st==='denied'?`<b>${who}</b> said no.`
    :st==='expired'?`Nobody at <b>${who}</b> answered in ten minutes.`
    :`<b>${who}</b>: ${esc(r.error||st)}`;
  return `<div class="tlk-req out"><div><p>${line}</p></div>${st==='pending'?`<div class="tlk-req-act"><button class="endbtn" onclick="teamLinkWithdraw('${esc(r.id)}')">Withdraw</button></div>`:''}</div>`;
}
async function paintTeamLinks(){
  const box=document.getElementById('s-team-links');if(!box)return;
  let d={},sa={};
  try{[d,sa]=await Promise.all([fetch('/api/team/links').then(r=>r.json()),fetch('/api/subagents').then(r=>r.json())])}catch(e){}
  const mine=(sa.subagents||[]).map(s=>s.name), me=d.me||{};
  const keep=box.querySelector('#tlk-addr')?.value||'', open=box.querySelector('.tlk-more')?.open;
  box.classList.remove('mut');
  const inv=TEAM_INVITE?`<div class="tlk-invite"><b>${TEAM_INVITE.kind==='account'?'Account code':'Invite'}</b>: share it privately. It works once, for ten minutes.
      <div class="tlk-inv-row"><input readonly value="${esc(TEAM_INVITE.invite||TEAM_INVITE.code)}"><button class="endbtn" onclick="navigator.clipboard&&navigator.clipboard.writeText(this.previousElementSibling.value);toast('copied')">Copy</button></div>
      ${TEAM_INVITE.fingerprint?`<small class="mut">This machine’s certificate: ${esc(TEAM_INVITE.fingerprint.slice(0,16))}…. The other side checks it before sending anything.</small>`:''}</div>`:'';
  const links=(d.links||[]).map(l=>{const id=l.peer_identity||{};return `<div class="tlk-card">
      <div class="tlk-head">${avatarRecipeImg(id.agent,'av-tool',(id.agent_name||'their agent'))}<b>${esc(l.label)}</b>${id.agent_name?`<span class="mut">${esc(id.agent_name)}’s team${id.person?' · '+esc(id.person):''}</span>`:''}<span class="brainchip">${l.kind==='account'?'account here':'machine · mTLS'}</span>
        <span class="mut">${esc(l.kind==='machine'?(l.url||'they can reach you, you can’t reach them'):'')}</span>
        <button class="endbtn" onclick="openTeamChat('${esc(l.label)}')">Message</button>
        <button class="endbtn" onclick="teamLinkCheck('${esc(l.label)}',this)">Check</button>
        <button class="endbtn" onclick="teamLinkRemove('${esc(l.label)}')">Remove</button></div>
      <div class="tlk-sub">Their agents may ask: ${mine.length?mine.map(n=>`<label class="tlk-chk"><input type="checkbox" data-link="${esc(l.label)}" data-agent="${esc(n)}" ${(l.theirs_may_ask||[]).includes(n)?'checked':''}> ${avatarImg(n,'av-tool')}${esc(n)}</label>`).join(''):'<span class="mut">you have no specialists yet</span>'}</div>
      <label class="tlk-sub tlk-chk"><input type="checkbox" data-link-mine="${esc(l.label)}" ${l.mine_may_ask?'checked':''}><span>My agents may ask theirs without asking me each time</span></label>
      ${tlMissionsHTML(l)}
      ${tlStandHTML(l,mine,d)}
      <div class="tlk-roster mut" id="tlk-r-${esc(l.label)}"></div></div>`}).join('');
  const others=d.others||[];
  box.innerHTML=`${(d.incoming||[]).length?`<div class="tlk-waiting"><b>Waiting for you</b>${d.incoming.map(tlkReqHTML).join('')}</div>`:''}
    <div class="tlk-ask">
      <div class="tlk-actions"><input id="tlk-addr" placeholder="Another Bento: office.local or 192.168.1.20" autocomplete="off" autocapitalize="off" spellcheck="false">
        <button class="pact" onclick="teamLinkRequest()">Ask to link</button></div>
      ${d.accounts&&others.length?`<div class="tlk-actions"><select id="tlk-acct">${others.map(o=>`<option value="${esc(o.id)}">${esc(o.name)}</option>`).join('')}</select>
        <button class="endbtn" onclick="teamLinkRequestAccount()">Ask this account to link</button></div>`:''}
      ${(d.outgoing||[]).map(tlkOutHTML).join('')}
    </div>
    <div class="tlk-me">This machine: <b>${esc(me.name||'')}</b> <small class="mut">certificate ${esc((me.fingerprint||'').slice(0,16))}…</small></div>
    ${d.can_listen?`<label class="tlk-chk"><input type="checkbox" id="tlk-listen" ${d.listening?'checked':''}><span>Let other machines ask to link (opens port ${esc(me.port)}, mutual TLS only)</span></label>`
      :`<p class="mut tlk-why">${d.listening?'Other machines can ask to link with this one.':'Other machines can’t ask to link with this one until an admin allows it. You can still ask them'+(d.accounts?', and link with another account here.':'.')}</p>`}
    ${d.can_listen&&!d.listening?'<p class="mut tlk-why">You can already ask other machines. Turn this on so they can ask you.</p>':''}
    ${links||'<p class="mut">No linked teams yet.</p>'}
    <details class="tlk-more"${open?' open':''}><summary>Use an invite code instead</summary>
      <p class="mut tlk-why">For a machine with no screen to approve on. Make a code on one side and paste it on the other.</p>
      <div class="tlk-actions">
        <button class="endbtn" onclick="teamLinkInvite('machine')" ${d.listening?'':'disabled'}>Invite a machine</button>
        <input id="tlk-join" placeholder="bento://link/… (an invite from the other machine)"><button class="endbtn" onclick="teamLinkJoin()">Join</button>
        ${d.accounts?`<button class="endbtn" onclick="teamLinkInvite('account')">Invite an account here</button>
          <input id="tlk-code" placeholder="code from another account"><button class="endbtn" onclick="teamLinkRedeem()">Redeem</button>`:''}
      </div>${d.listening?'':'<p class="mut tlk-why">To invite a machine, first let other machines ask to link (above).</p>'}${inv}
    </details>`;
  const a=box.querySelector('#tlk-addr');if(a){a.value=keep;a.onkeydown=e=>{if(e.key==='Enter')teamLinkRequest()}}
  const ls=box.querySelector('#tlk-listen');
  if(ls)ls.onchange=async()=>{const r=await teamApi('/api/team/listen','PUT',{on:ls.checked});if(r)toast(r.listening?'other machines can ask to link (port '+r.port+')':'other machines can no longer ask to link');paintTeamLinks()};
  box.querySelectorAll('input[data-link]').forEach(cb=>cb.onchange=async()=>{
    const lab=cb.dataset.link, sel=[...box.querySelectorAll(`input[data-link="${CSS.escape(lab)}"]`)].filter(x=>x.checked).map(x=>x.dataset.agent);
    await teamApi('/api/team/links/'+encodeURIComponent(lab)+'/access','PUT',{theirs_may_ask:sel});});
  box.querySelectorAll('details.tlk-stand').forEach(x=>x.ontoggle=()=>{TL_STAND_OPEN[x.dataset.stand]=x.open});
  box.querySelectorAll('input[data-link-mine]').forEach(cb=>cb.onchange=()=>teamApi('/api/team/links/'+encodeURIComponent(cb.dataset.linkMine)+'/access','PUT',{mine_may_ask:cb.checked}));
}
/* Standing permissions: what a linked team may have one of YOUR agents change without a
   person here saying yes. A question from another team is untrusted, so by default it can
   make an agent read and answer, never write — this is that yes given ahead of time, for
   one agent, one action, one folder or tool. The same rows the approval card's "Always
   let …" writes and Permissions revokes; the server refuses what can never be standing
   (a shell, a home, a hidden folder) with a sentence, which is shown as it comes.
   Faces: TUI is `bento link let/standing/unlet` (no pointer needed); SUI is this page,
   nothing native — and the card that offers it goes only to the link owner's screens. */
var TL_STAND_OPEN={};
var TL_ACT_WORDS={'fs.write':'write files in','memory.write':'remember things','kg.write':'add to the knowledge graph',
  'media.generate':'generate images','media.write':'save assets','tool.use':'use the tool'};
function tlScope(s){return String(s||'').replace(/^(fs|tool):/,'').replace(/\/?\*$/,'')}
function tlStandHTML(l,mine,d){
  const rows=l.standing||[], lab=esc(l.label);
  return `<details class="tlk-stand" data-stand="${lab}"${TL_STAND_OPEN[l.label]?' open':''}><summary>Without asking me${rows.length?' · '+rows.length:''}</summary>
    <p class="mut tlk-why">Questions from ${lab} can make your agents read and answer, but any change needs a person here to say yes. ${pInfo('Allow one thing ahead of time: one agent, one action, in one folder. If the agent also read a web page or an email on the way, you’re asked again.')}</p>
    ${d.standing_note?`<p class="mut tlk-why">${esc(d.standing_note)}</p>`:''}
    ${rows.map(x=>`<div class="tlk-stand-row">${avatarImg(x.agent,'av-tool')}<span><b>${esc(x.agent)}</b> may ${esc(TL_ACT_WORDS[x.action]||x.action)} <code>${esc(tlScope(x.scope))}</code>${x.expires_at?` <small class="mut">until ${new Date(x.expires_at*1000).toLocaleDateString()}</small>`:''}</span><button class="endbtn" onclick="tlStandRemove('${lab}','${esc(x.id)}')">Remove</button></div>`).join('')}
    ${mine.length?`<div class="tlk-actions tlk-stand-add"><select data-sa="agent" aria-label="Which of your agents">${mine.map(n=>`<option>${esc(n)}</option>`).join('')}</select>
      <select data-sa="action" aria-label="May do">${(d.standing_actions||[]).map(a=>`<option value="${esc(a)}">${esc(TL_ACT_WORDS[a]||a)}</option>`).join('')}</select>
      <input data-sa="scope" placeholder="~/shared · or ${esc((d.standing_tools||[]).join(', '))}" autocomplete="off" autocapitalize="off" spellcheck="false">
      <input data-sa="days" type="number" min="1" inputmode="numeric" placeholder="days (blank: until removed)">
      <button class="pact" onclick="tlStandAdd('${lab}',this)">Allow</button></div>`
      :'<p class="mut tlk-why">You have no specialists yet. This is for them.</p>'}
  </details>`;
}
/* Their missions that use YOUR agents — recorded here when they save one (or on its first
   question), so the side that does the work can see what the other side decided and stop
   it. Stop is a deny row the gate enforces (fabric.stop_mission); the record stays. The
   name is their machine's claim: to stop a MACHINE, untick the agent above. */
function tlMissionsHTML(l){
  const ms=l.missions||[], lab=esc(l.label);
  if(!ms.length)return '';
  const when=t=>t?new Date(t*1000).toLocaleString([], {dateStyle:'medium',timeStyle:'short'}):'never';
  return `<div class="tlk-miss"><div class="tlk-miss-h">Their missions that use your agents</div>
    ${ms.map(m=>`<div class="tlk-miss-row${m.stopped?' stopped':''}">
      <div class="tlk-miss-main"><b>${esc(m.mission)}</b>
        <span class="brainchip">${m.stopped?'stopped by you':m.enabled===false?'off on their side':'on'}</span>
        ${(m.agents||[]).map(a=>avatarImg(a,'av-tool')+esc(a)).join(' ')}
        <div class="mut tlk-why">${m.schedule?esc(m.schedule)+' · ':''}asked ${m.runs} time${m.runs===1?'':'s'}, last ${esc(when(m.last_used))}${m.text?' · '+esc(m.text):''}</div></div>
      <button class="endbtn" onclick="tlMissionStop('${lab}','${esc(m.mission)}',${m.stopped?'false':'true'})">${m.stopped?'Allow again':'Stop'}</button></div>`).join('')}
  </div>`;
}
async function tlMissionStop(label,mission,stop){
  if(stop&&!await osConfirm('Stop '+label+'’s mission “'+mission+'”?',
     'Its questions to your agents will be refused, and they’ll be told why. Allow again undoes it.',{confirmText:'Stop'}))return;
  const r=await teamApi('/api/team/links/'+encodeURIComponent(label)+'/missions/'+encodeURIComponent(mission)+'/'+(stop?'stop':'allow'),'POST',{});
  if(r){toast(stop?'stopped '+label+'’s mission':'allowed again');paintTeamLinks()}
}
async function tlStandAdd(label,btn){
  const box=btn.closest('.tlk-stand-add'),v=k=>(box.querySelector(`[data-sa="${k}"]`)||{}).value||'';
  if(!v('scope').trim()){toast('say which folder or tool');return}
  const r=await teamApi('/api/team/links/'+encodeURIComponent(label)+'/standing','POST',
    {agent:v('agent'),action:v('action'),scope:v('scope').trim(),days:v('days')?Number(v('days')):null});
  if(r){TL_STAND_OPEN[label]=true;toast(label+' may now have '+r.agent+' '+(TL_ACT_WORDS[r.action]||r.action)+' '+tlScope(r.scope)+' without asking');paintTeamLinks()}
}
async function tlStandRemove(label,id){
  if(await teamApi('/api/team/links/'+encodeURIComponent(label)+'/standing/'+encodeURIComponent(id),'DELETE')){
    TL_STAND_OPEN[label]=true;toast('removed. '+label+' needs a person to say yes again');paintTeamLinks()}
}
async function teamApi(url,method,body){
  const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined}).then(r=>r.json()).catch(()=>({error:'the server did not answer'}));
  if(r&&r.error){toast(r.error);return null}
  return r;
}
async function teamLinkRequest(){
  const a=document.getElementById('tlk-addr'),v=(a&&a.value||'').trim();
  if(!v){toast('type the other machine’s name or address');a&&a.focus();return}
  toast('asking '+v+'…');
  const r=await teamApi('/api/team/links/request','POST',{address:v});
  if(r){if(a)a.value='';toast('asked '+r.request.name+'. Check it shows '+r.request.sas);paintTeamLinks()}
}
async function teamLinkRequestAccount(){
  const v=(document.getElementById('tlk-acct')||{}).value||'';
  const r=await teamApi('/api/team/links/request','POST',{account:v});
  if(r){toast('asked '+r.request.to_name+'. They approve from their account');paintTeamLinks()}
}
async function teamLinkAnswer(id,verb){
  const r=await teamApi('/api/team/links/requests/'+encodeURIComponent(id)+'/'+verb,'POST',{});
  if(r)toast(verb==='deny'?'refused':(r.note||('linked with '+((r.link||{}).label||''))));
  paintTeamLinks();
}
async function teamLinkWithdraw(id){if(await teamApi('/api/team/links/requests/'+encodeURIComponent(id),'DELETE'))paintTeamLinks()}
async function teamLinkInvite(kind){const r=await teamApi('/api/team/links/invite','POST',{kind});if(r){TEAM_INVITE=r;paintTeamLinks()}}
async function teamLinkJoin(){const v=(document.getElementById('tlk-join')||{}).value||'';const r=await teamApi('/api/team/links/join','POST',{invite:v.trim()});if(r){toast('linked with '+r.link.label);paintTeamLinks()}}
async function teamLinkRedeem(){const v=(document.getElementById('tlk-code')||{}).value||'';const r=await teamApi('/api/team/links/redeem','POST',{code:v.trim()});if(r){toast('linked with '+r.link.label);paintTeamLinks()}}
async function teamLinkRemove(label){if(!await osConfirm('Remove the link with '+label+'?','Their agents lose every permission here, and yours theirs.',{danger:true,confirmText:'Remove'}))return;
  if(await teamApi('/api/team/links/'+encodeURIComponent(label),'DELETE')){toast('link removed');paintTeamLinks()}}
async function teamLinkCheck(label,btn){
  const el=document.getElementById('tlk-r-'+label);if(el)el.textContent='asking…';
  const r=await fetch('/api/team/links/'+encodeURIComponent(label)+'/roster').then(r=>r.json()).catch(()=>({error:'no answer'}));
  // they show only the agents they let your team ask — a link grants nothing, not even names
  if(el)el.textContent=!r.ok?(r.error||'not reachable')
    :(r.agents||[]).length?'Reachable. Your agents can ask '+r.agents.map(a=>a.name+' ('+a.provider+')').join(', ')+', as name@'+label+'.'
    :'Reachable. They haven’t let your team ask any of their agents yet. That’s up to them.';
}
