/* ================= settings app ================= */
async function renderSettings(body){
  await loadConfig();
  const p=cfg.providers;
  const pb=panelShell(body,{
    title:'Settings',
    search:{id:'set-q',placeholder:'Find a setting…'},
    actions:`<button class="pact" onclick="saveSettings()">Save</button>`,
  });
  pb.innerHTML=`
    <div class="provbox" data-f="ollama local models base url"><div class="ptitle">Ollama (local)</div>
      <label>Base URL</label><input id="s-ollama-url" value="${esc(p.ollama.base_url)}"></div>
    <div class="provbox" data-f="anthropic claude api key cloud models"><div class="ptitle">Anthropic <input type="checkbox" id="s-ant-on" ${p.anthropic.enabled?'checked':''}></div>
      <label>API key ${p.anthropic._has_key?'(set)':''}</label><input id="s-ant-key" placeholder="sk-ant-…" value="${esc(p.anthropic.api_key||'')}">
      <label>Models (comma-separated)</label><input id="s-ant-models" value="${esc((p.anthropic.models||[]).join(', '))}"></div>
    <div class="provbox" data-f="openai gpt api key"><div class="ptitle">OpenAI <input type="checkbox" id="s-oai-on" ${p.openai.enabled?'checked':''}></div>
      <label>API key ${p.openai._has_key?'(set)':''}</label><input id="s-oai-key" placeholder="sk-…" value="${esc(p.openai.api_key||'')}">
      <label>Models</label><input id="s-oai-models" value="${esc((p.openai.models||[]).join(', '))}"></div>
    <div class="provbox" data-f="openrouter api key hundreds of models"><div class="ptitle">OpenRouter — one key, hundreds of models <input type="checkbox" id="s-or-on" ${p.openrouter.enabled?'checked':''}></div>
      <label>API key ${p.openrouter._has_key?'(set)':''}</label><input id="s-or-key" placeholder="sk-or-…" value="${esc(p.openrouter.api_key||'')}">
      <label>Models (comma-separated, e.g. anthropic/claude-sonnet-4.5)</label><input id="s-or-models" value="${esc((p.openrouter.models||[]).join(', '))}"></div>
    <div class="provbox" data-f="custom openai compatible endpoint lm studio llama.cpp base url"><div class="ptitle">Custom (OpenAI-compatible) <input type="checkbox" id="s-cus-on" ${p.custom.enabled?'checked':''}></div>
      <label>Base URL (e.g. http://localhost:1234/v1)</label><input id="s-cus-url" value="${esc(p.custom.base_url||'')}">
      <label>API key (optional)</label><input id="s-cus-key" value="${esc(p.custom.api_key||'')}">
      <label>Models</label><input id="s-cus-models" value="${esc((p.custom.models||[]).join(', '))}"></div>
    <div class="provbox" data-f="google gemini api key image generation chat models"><div class="ptitle">Google (Gemini) <input type="checkbox" id="s-goo-on" ${p.google&&p.google.enabled?'checked':''}></div>
      <label>API key ${p.google&&p.google._has_key?'(set)':''}</label><input id="s-goo-key" placeholder="AIza…" value="${esc((p.google&&p.google.api_key)||'')}">
      <label>Chat models (comma-separated, e.g. gemini-2.5-pro)</label><input id="s-goo-models" value="${esc((p.google&&p.google.models||[]).join(', '))}">
      <p class="mut" style="margin-top:8px">Gemini models appear in the chat &amp; App Studio pickers, and power image generation. Free key at aistudio.google.com.</p></div>
    <div class="provbox" data-f="image generation wallpaper provider model"><div class="ptitle">Image generation</div>
      <label>Provider</label>
      <select id="s-img-prov">${['auto','google','openai','pollinations'].map(v=>`<option value="${v}" ${((cfg.image&&cfg.image.provider)||'auto')===v?'selected':''}>${v}</option>`).join('')}</select>
      <label>Model (optional)</label><input id="s-img-model" placeholder="gemini-2.5-flash-image / gpt-image-1" value="${esc((cfg.image&&cfg.image.model)||'')}">
      <p class="mut" style="margin-top:8px">Powers wallpaper &amp; image generation. <b>auto</b> picks Google, then OpenAI (whichever has a key), else the free pollinations.ai service.</p></div>
    <div class="provbox" data-f="appearance theme fullscreen wallpaper"><div class="ptitle">Appearance</div>
      <label>Theme</label>
      <div class="row">
        <select id="s-theme">${Object.entries(allThemes()).map(([k,t])=>`<option value="${k}" ${CURRENT_THEME===k?'selected':''}>${esc(t.label||t.name||k)}${t.custom?' ·':''}</option>`).join('')}</select>
        <button class="endbtn" style="flex:0 0 auto" onclick="openApp('themes')">Themes</button>
      </div>
      <div class="row" style="margin-top:10px">
        <button class="endbtn" onclick="toggleFullscreen()">Toggle fullscreen (F11)</button>
        <button class="endbtn" onclick="wpSystem()">Use system wallpaper</button>
      </div>
      <p class="mut" style="margin-top:8px">Fullscreen hides the host taskbar; the app also launches fullscreen via <code>agentos app</code>.</p>
    </div>
    <div class="provbox" data-f="github git token push publish ship repositories"><div class="ptitle">GitHub (ship what you build)</div>
      <label>Personal access token ${cfg.github&&cfg.github._has_token?'(set)':''}</label><input id="s-gh-token" type="password" placeholder="github_pat_… / ghp_…" value="${esc((cfg.github&&cfg.github.token)||'')}">
      <label>Username (optional)</label><input id="s-gh-user" value="${esc((cfg.github&&cfg.github.username)||'')}">
      <p class="mut" style="margin-top:8px">Lets the agent create repos and push projects/apps it builds (git_push, export_app_to_git).
      Use a fine-grained token with only the repo permissions you want to grant. The token never appears in commands or logs.</p></div>
    <div class="provbox" data-f="sandbox folder jail bubblewrap security workspace"><div class="ptitle">Sandbox (folder jail) <input type="checkbox" id="s-sb-on" ${(cfg.sandbox&&cfg.sandbox.enabled)?'checked':''}></div>
      <label>Folder the agent &amp; Terminal can control</label>
      <input id="s-sb-root" value="${esc((cfg.sandbox&&cfg.sandbox.root)||cfg.workspace)}">
      <p class="mut" style="margin-top:8px">Commands and the Terminal run jailed to this folder (bubblewrap): everything else is read-only,
      other files in /home are hidden, and sessions always start here. File tools refuse paths outside it.</p>
    </div>
    <div class="provbox" data-f="voice tts speech dictation microphone language rate"><div class="ptitle">Voice</div>
      <label style="display:flex;align-items:center;gap:8px;margin-top:10px"><input type="checkbox" id="v-tts" style="width:auto" ${VOICE.tts?'checked':''}> Speak replies aloud (TTS)</label>
      <label>TTS voice</label><select id="v-voice"></select>
      <div class="row">
        <div><label>Speech rate</label><input id="v-rate" type="number" step="0.1" min="0.5" max="2" value="${VOICE.rate||1}"></div>
        <div><label>Mic language</label><input id="v-lang" value="${esc(VOICE.lang||'en-IN')}" placeholder="en-IN, en-US, hi-IN…"></div>
      </div>
      <p class="mut" style="margin-top:8px">Dictate with the button in chat; toggle speech with in the chat toolbar.</p>
    </div>
    <div class="row" data-f="agent name workspace directory max steps">
      <div><label>Agent name</label><input id="s-name" value="${esc(cfg.agent_name||'Aria')}"></div>
      <div><label>Workspace directory</label><input id="s-workspace" value="${esc(cfg.workspace)}"></div>
      <div><label>Max steps per turn</label><input id="s-steps" type="number" value="${cfg.max_steps}"></div>
    </div>
    <button class="save" onclick="saveSettings()">Save</button>
    <div class="provbox" data-f="danger zone factory reset wipe" style="margin-top:14px;border-color:var(--err,#f87171)"><div class="ptitle" style="color:var(--err,#f87171)">Danger zone</div>
      <p class="mut" style="margin:4px 0 8px">Start fresh: wipes memory, knowledge, conversations, apps, subagents, soul and settings, then runs the first-time setup wizard again. Take a Snapshot first if you might want to come back.</p>
      <button class="endbtn" style="border-color:var(--err,#f87171);color:var(--err,#f87171)" onclick="factoryReset()">Factory reset…</button></div>`;
  $('#s-theme').onchange=()=>{applyTheme($('#s-theme').value);toast('theme applied')};
  const vsel=$('#v-voice');
  const fillVoices=()=>{
    if(!window.speechSynthesis||!vsel)return;
    const vs=speechSynthesis.getVoices();
    vsel.innerHTML='<option value="">(system default)</option>'+vs.map(v=>`<option ${v.name===VOICE.voice?'selected':''}>${esc(v.name)}</option>`).join('');
  };
  fillVoices();
  if(window.speechSynthesis)speechSynthesis.onvoiceschanged=fillVoices;
}
async function saveSettings(){
  VOICE.tts=$('#v-tts').checked;VOICE.voice=$('#v-voice').value;
  VOICE.rate=+$('#v-rate').value||1;VOICE.lang=$('#v-lang').value.trim()||'en-IN';
  saveVoice();
  const models=s=>s.split(',').map(x=>x.trim()).filter(Boolean);
  const patch={workspace:$('#s-workspace').value,max_steps:+$('#s-steps').value||25,
    agent_name:$('#s-name').value.trim()||'Aria',
    sandbox:{enabled:$('#s-sb-on').checked,root:$('#s-sb-root').value.trim()},providers:{
    ollama:{base_url:$('#s-ollama-url').value},
    anthropic:{enabled:$('#s-ant-on').checked,api_key:$('#s-ant-key').value,models:models($('#s-ant-models').value)},
    openai:{enabled:$('#s-oai-on').checked,api_key:$('#s-oai-key').value,models:models($('#s-oai-models').value)},
    openrouter:{enabled:$('#s-or-on').checked,api_key:$('#s-or-key').value,models:models($('#s-or-models').value)},
    custom:{enabled:$('#s-cus-on').checked,base_url:$('#s-cus-url').value,api_key:$('#s-cus-key').value,models:models($('#s-cus-models').value)},
    google:{enabled:$('#s-goo-on').checked,api_key:$('#s-goo-key').value,models:models($('#s-goo-models').value)},
  },image:{provider:$('#s-img-prov').value,model:$('#s-img-model').value.trim()},
  github:{token:$('#s-gh-token').value.trim(),username:$('#s-gh-user').value.trim()}};
  await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)});
  toast('settings saved');loadModels();loadConfig();
}

