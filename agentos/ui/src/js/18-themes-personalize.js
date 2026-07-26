/* ================= themes app ================= */
async function renderThemes(body){
  await loadThemes();
  const swatch=t=>{const v=t.v||t.vars||{};
    return `<span style="display:flex;gap:3px">${['bg2','acc','acc2','txt'].map(k=>`<i style="width:14px;height:14px;border-radius:4px;background:${v[k]||'#333'};border:1px solid rgba(255,255,255,.15)"></i>`).join('')}</span>`;};
  const cards=Object.entries(allThemes()).map(([k,t])=>`<div class="catcard" style="cursor:pointer" onclick="applyTheme('${esc(k)}');refreshApp('themes')">
      <span class="cn">${esc(t.label||t.name||k)} ${CURRENT_THEME===k?'✓':''}</span>
      <div style="margin:6px 0 4px">${swatch(t)}</div>
      <span class="cd">${t.mode||'dark'}${t.font?' · '+esc(t.font.family||'custom font'):''}${t.css?' · custom CSS':''}${t.shell?' · full shell':''}</span>
      ${t.custom?`<button class="endbtn" style="position:absolute;top:8px;right:8px;padding:1px 7px" onclick="event.stopPropagation();themeDel('${esc(k)}')">✕</button>`:''}
    </div>`).join('');
  body.innerHTML=`<div class="pad">
    <p class="mut" style="margin-bottom:10px">Themes restyle the whole desktop — colors, fonts, windows, menu bar, dock, icons and widgets. A theme can even carry a <b>full replacement shell</b>: a completely different interface built by AI against the OS API (<code>GET /api/registry</code>). Click one to apply instantly.</p>
    <div class="cat">${cards}</div>
    <div class="row" style="margin-top:14px">
      <button class="save" style="margin:0" onclick="themeBuilder()">Open Theme Builder</button>
    </div>
    <label style="margin-top:16px">Design a theme with AI</label>
    <div class="row"><input id="th-ai" placeholder="e.g. a warm sunset theme with glass windows, or matrix terminal green">
      <button class="save" style="margin:0;flex:0 0 90px" onclick="themeAI()">Design</button></div>
    <p class="mut" style="margin:6px 0 0">${esc(agentName())} will generate a full theme (colors, font, chrome) and apply it live.</p>
    <label style="margin-top:16px">Import / export</label>
    <div class="row">
      <button class="endbtn" onclick="themeExport()">⤓ Export current theme (JSON)</button>
      <button class="endbtn" onclick="document.getElementById('th-imp').style.display='block'">⤒ Import…</button>
    </div>
    <textarea id="th-imp" placeholder='Paste a theme JSON: { "name":"My Theme","mode":"dark","v":{…},"css":"…","font":{"url":"…","family":"…"} }' rows="5" style="display:none;margin-top:8px;font-family:var(--mono);font-size:12px"></textarea>
    <button class="save" id="th-imp-btn" style="display:none" onclick="themeImport()">Save & apply imported theme</button>
  </div>`;
  const ta=$('#th-imp');ta&&ta.addEventListener('input',()=>{$('#th-imp-btn').style.display=ta.value.trim()?'block':'none'});
}
function themeAI(){
  const p=$('#th-ai').value.trim();if(!p)return toast('describe the theme');
  const t=allThemes()[CURRENT_THEME]||{};
  const cur=`Currently applied theme: "${t.label||t.name||CURRENT_THEME}"${t.custom?' (custom — refine it in place)':' (built-in)'}, mode ${t.mode||'dark'}, vars ${JSON.stringify(t.v||t.vars||{})}${t.css?', has custom css':''}${t.shell?', has a full replacement shell':''}.`;
  openApp('chat');
  if(input){input.value='Theme request: '+p+'\n\n'+cur+'\nUse the create_theme tool. If this is a REFINEMENT of the theme we are already working on (or of the applied custom theme), call create_theme with that SAME name and only the fields to change — vars merge key-by-key and css/font/shell are kept unless passed. Only pick a new name for a genuinely new theme. For a new theme, give a full set of CSS variables and custom css for the chrome (#menubar, #taskbar dock, .win, .aicon). If I asked for a completely different interface (not just a restyle), fetch GET /api/registry to see every endpoint available and pass shell_html — a full replacement UI.';input.dispatchEvent(new Event('input'));send()}
  toast('designing your theme…');
}
async function themeSave(theme,apply){
  theme.custom=true;theme.apply=!!apply;
  await fetch('/api/themes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(theme)});
}
function themeExport(){
  const t=allThemes()[CURRENT_THEME];if(!t)return;
  const out={name:(t.label||t.name||CURRENT_THEME),mode:t.mode||'dark',v:t.v||t.vars||{},css:t.css||'',font:t.font||undefined,shell:t.shell||undefined};
  const blob=new Blob([JSON.stringify(out,null,2)],{type:'application/json'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=out.name.replace(/\s+/g,'-')+'.theme.json';a.click();
}
async function themeImport(){
  try{const t=JSON.parse($('#th-imp').value);if(!t.name)return toast('theme needs a "name"');
    await themeSave(t,true);await loadThemes();applyTheme(t.name);toast('imported '+t.name);refreshApp('themes');
  }catch(e){toast('invalid JSON: '+e.message)}
}
async function themeDel(name){
  await fetch('/api/themes/'+encodeURIComponent(name),{method:'DELETE'});
  if(CURRENT_THEME===name)applyTheme('agentos');
  await loadThemes();refreshApp('themes');
}
function themeBuilder(){
  const w=WM.wins.get('themes');if(!w)return;
  const body=w.el.querySelector('.wbody');
  const base=allThemes()[CURRENT_THEME]||THEMES.agentos;
  const WB={name:'My Theme',mode:base.mode||'dark',v:{...(base.v||base.vars||{})},css:base.css||'',font:base.font?{...base.font}:null};
  const hex=v=>{v=(v||'').trim();if(/^#([0-9a-f]{6})$/i.test(v))return v;if(/^#([0-9a-f]{3})$/i.test(v))return '#'+v.slice(1).split('').map(c=>c+c).join('');return '#222222'};
  const COLORS=[['bg','Background'],['bg2','Surface'],['bg3','Surface 2'],['bg4','Raised'],['line','Border'],['txt','Text'],['dim','Muted'],['dim2','Faint'],['acc','Accent'],['acc2','Accent 2'],['warn','Warning'],['err','Error'],['ok','Success']];
  body.innerHTML=`<div class="pad">
    <div class="apptop" style="border:none;padding:0 0 10px;gap:8px">
      <button class="endbtn" onclick="refreshApp('themes')">← Back</button>
      <input id="tb-name" value="${esc(WB.name)}" placeholder="theme name" style="flex:1">
      <select id="tb-mode" style="flex:0 0 90px"><option value="dark"${WB.mode==='dark'?' selected':''}>dark</option><option value="light"${WB.mode==='light'?' selected':''}>light</option></select>
    </div>
    <p class="mut" style="margin-bottom:10px">Pick colors — the whole desktop updates live as you edit. </p>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px 18px">
      ${COLORS.map(([k,lab])=>`<label style="display:flex;align-items:center;gap:10px;margin:0;font-size:12.5px;color:var(--txt);font-weight:400">
        <input type="color" data-k="${k}" value="${hex(WB.v[k])}" style="width:36px;height:26px;padding:0;border:1px solid var(--line);background:none;border-radius:6px;cursor:pointer">
        <span style="flex:1">${lab}</span><code style="font-size:10.5px;color:var(--dim2)" id="tb-h-${k}">${esc(WB.v[k]||'')}</code></label>`).join('')}
    </div>
    <label>Glass / overlay (rgba)</label><input id="tb-glass" value="${esc(WB.v.glass||'rgba(20,20,25,.85)')}">
    <label>Web font URL (optional)</label><input id="tb-furl" value="${esc((WB.font&&WB.font.url)||'')}" placeholder="https://fonts.googleapis.com/css2?family=…">
    <label>Font family (optional)</label><input id="tb-ffam" value="${esc((WB.font&&WB.font.family)||'')}" placeholder="e.g. Space Grotesk">
    <label>Advanced CSS (optional — restyle .win, #taskbar, .dimg, .widget, #desktop)</label>
    <textarea id="tb-css" rows="4" style="font-family:var(--mono);font-size:12px">${esc(WB.css)}</textarea>
    <div class="row" style="margin-top:12px">
      <button class="save" style="margin:0" onclick="tbSave()">Save &amp; apply</button>
      <button class="endbtn" onclick="applyTheme(CURRENT_THEME);refreshApp('themes')">Cancel</button>
    </div>
  </div>`;
  const preview=()=>applyThemeObj(WB);
  body.querySelectorAll('input[type=color]').forEach(inp=>inp.oninput=()=>{WB.v[inp.dataset.k]=inp.value;const h=$('#tb-h-'+inp.dataset.k);if(h)h.textContent=inp.value;preview()});
  $('#tb-glass').oninput=e=>{WB.v.glass=e.target.value;preview()};
  $('#tb-mode').onchange=e=>{WB.mode=e.target.value;preview()};
  $('#tb-css').oninput=e=>{WB.css=e.target.value;preview()};
  $('#tb-furl').oninput=e=>{WB.font=WB.font||{};WB.font.url=e.target.value};
  $('#tb-ffam').oninput=e=>{WB.font=WB.font||{};WB.font.family=e.target.value;preview()};
  window._WB=WB;preview();
}
async function tbSave(){
  const WB=window._WB;if(!WB)return;
  WB.name=$('#tb-name').value.trim()||'My Theme';WB.custom=true;
  if(WB.font&&!WB.font.url)WB.font=null;
  await themeSave(WB,true);await loadThemes();applyTheme(WB.name);toast('saved '+WB.name);refreshApp('themes');
}

/* ================= personalize app + wallpaper gallery ================= */
async function renderPersonalize(body){
  let gal=[];try{gal=(await (await fetch('/api/wallpapers')).json()).wallpapers||[]}catch(e){}
  body.innerHTML=`<div class="pad">
    <label>Describe your wallpaper</label>
    <textarea id="pz-prompt" rows="2" placeholder="e.g. dark cyberpunk skyline at dusk, teal neon reflections, rain, cinematic"></textarea>
    <div class="row" style="margin-top:10px">
      <button class="save" style="margin:0" id="pz-gen" onclick="pzGen()">Generate wallpaper</button>
      <button class="endbtn" onclick="wpSystem()">Use system wallpaper</button>
      <button class="endbtn" onclick="fetch('/api/wallpaper',{method:'DELETE'})">Reset</button>
    </div>
    <label style="margin-top:16px">Gallery — every wallpaper you've generated (click to apply)</label>
    <div id="pz-gal" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;margin-top:6px">
      ${gal.length?gal.map(id=>`<div style="position:relative;border-radius:9px;overflow:hidden;border:1px solid var(--line);aspect-ratio:16/9;cursor:pointer" onclick="pzSet('${id}')">
        <img src="/api/wallpapers/${id}" style="width:100%;height:100%;object-fit:cover" loading="lazy">
        <button class="endbtn" style="position:absolute;top:4px;right:4px;padding:1px 6px" onclick="event.stopPropagation();pzDel('${id}')">✕</button>
      </div>`).join(''):'<p class="mut">No wallpapers yet — generate one above.</p>'}
    </div>
    <p class="mut" style="margin-top:12px">Uses your image provider from Settings (Gemini / OpenAI; free pollinations.ai without a key, which caps resolution). You can also tell ${esc(agentName())}: <i>"change my wallpaper to a snowy mountain at sunrise"</i>.</p>
  </div>`;
}
async function pzGen(){
  const p=$('#pz-prompt').value.trim();if(!p)return toast('describe the image first');
  const b=$('#pz-gen');b.disabled=true;b.textContent='⏳ generating…';
  try{
    const r=await fetch('/api/wallpaper/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt:p})});
    const d=await r.json();if(!d.ok)toast(d.result);else{toast('generated');refreshApp('personalize')}
  }catch(e){toast('generation failed — offline?')}
  const b2=$('#pz-gen');if(b2){b2.disabled=false;b2.textContent='Generate wallpaper'}
}
async function pzSet(id){await fetch('/api/wallpapers/'+id+'/set',{method:'POST'});toast('applied')}
async function wpSystem(){const r=await fetch('/api/wallpaper/system',{method:'POST'});const d=await r.json();toast(d.ok?'using your system wallpaper':(d.error||'failed'))}
async function pzDel(id){await fetch('/api/wallpapers/'+id,{method:'DELETE'});refreshApp('personalize')}

