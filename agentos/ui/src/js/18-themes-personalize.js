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
      <button class="save" style="margin:0" onclick="themeBuilder()">Build a theme</button>
    </div>
    <label style="margin-top:16px">Effects</label>
    <p class="mut">Glass is the most expensive thing a desktop can draw, and the cost grows with every
      window you open — five stacked glass windows can cost eight times the frame time of one.
      ${glassLevel()==='full'?'This machine keeps up.':'<b>Turned down on this machine</b> to keep windows smooth.'}</p>
    <div class="gq-row">${[
      ['auto','Automatic','measure this machine and turn glass down only if it cannot keep up'],
      ['full','Full glass','every surface blurs, as the theme designed it'],
      ['reduced','Reduced','only the focused window blurs — flat cost, however many are open'],
      ['off','Off','no blur anywhere, panels go solid. Best on a Raspberry Pi or a VM'],
    ].map(([k,label,tip])=>`<button class="endbtn${GLASS.pref===k?' on':''}" title="${esc(tip)}"
        onclick="setGlass('${k}')">${GLASS.pref===k?'✓ ':''}${esc(label)}</button>`).join('')}</div>
    <p class="mut" style="margin-top:6px">${esc(({auto:'Automatic',full:'Full glass',reduced:'Reduced',off:'Off'})[GLASS.pref]||'')} —
      ${esc(({auto:'currently drawing at "'+glassLevel()+'"',full:'every surface blurs, as the theme designed it',
        reduced:'only the focused window blurs — flat cost, however many are open',
        off:'no blur anywhere, panels go solid'})[GLASS.pref]||'')}.</p>
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
  if(CURRENT_THEME===name)applyTheme('nova');
  await loadThemes();refreshApp('themes');
}
/* ---------------- the Theme Builder: build a look and feel ----------------
   Everything a theme is, as controls: a palette generated from three colours (then
   fine-tuned), corners, depth, glass, font, text size and wallpaper. Every control
   writes a TOKEN (--r-md, --el-3, --glass-blur, --acc-grad, --on-acc, --fs-base…),
   the same ones the built-in themes and the AI designer (`create_theme`) use, so a
   built theme reaches every surface the standard and the immersive look draw — no
   second styling system. The desktop previews live as you move a slider.
   Faces — GUI/SUI: this. TUI: not applicable — a terminal has no palette, glass or
   wallpaper, and a theme is remembered per browser; `create_theme` in chat is the
   words-only way to build one. */
var TB_FONTS=[['','System (Inter)'],['Geist','Geist'],['Inter','Inter'],['Plus Jakarta Sans','Plus Jakarta Sans'],
  ['Space Grotesk','Space Grotesk'],['Outfit','Outfit'],['Manrope','Manrope'],['IBM Plex Sans','IBM Plex Sans'],
  ['DM Sans','DM Sans'],['Nunito','Nunito'],['JetBrains Mono','JetBrains Mono (mono)']];
var TB_DEPTH={flat:['none','none','none','none'],
  soft:['0 2px 6px rgba(0,0,0,.18)','0 6px 18px rgba(0,0,0,.22)','0 12px 32px rgba(0,0,0,.28)','0 22px 56px rgba(0,0,0,.34)'],
  normal:null,
  deep:['0 4px 12px rgba(0,0,0,.4)','0 12px 32px rgba(0,0,0,.46)','0 24px 64px rgba(0,0,0,.54)','0 40px 110px rgba(0,0,0,.62)']};
var TB_GLASS={solid:['none','96'],frosted:['blur(30px) saturate(1.7)','58'],clear:['blur(14px) saturate(1.3)','38']};
function tbHex(v){v=(v||'').trim();if(/^#([0-9a-f]{6})$/i.test(v))return v.toLowerCase();if(/^#([0-9a-f]{3})$/i.test(v))return '#'+v.slice(1).split('').map(c=>c+c).join('').toLowerCase();return '#222222'}
function tbRgb(h){h=tbHex(h);return [1,3,5].map(i=>parseInt(h.slice(i,i+2),16)/255)}
function tbHsl(hex){const [r,g,b]=tbRgb(hex),mx=Math.max(r,g,b),mn=Math.min(r,g,b),l=(mx+mn)/2;let h=0,s=0;
  if(mx!==mn){const d=mx-mn;s=l>.5?d/(2-mx-mn):d/(mx+mn);h=mx===r?((g-b)/d+(g<b?6:0)):mx===g?((b-r)/d+2):((r-g)/d+4);h/=6}return [h,s,l]}
function tbFromHsl(h,s,l){const f=n=>{const k=(n+h*12)%12,a=s*Math.min(l,1-l);return Math.round(255*(l-a*Math.max(-1,Math.min(k-3,9-k,1))))};
  return '#'+[f(0),f(8),f(4)].map(x=>x.toString(16).padStart(2,'0')).join('')}
function tbLum(hex){const c=tbRgb(hex).map(x=>x<=.03928?x/12.92:Math.pow((x+.055)/1.055,2.4));return .2126*c[0]+.7152*c[1]+.0722*c[2]}
function tbContrast(a,b){const x=tbLum(a),y=tbLum(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)}
/* A whole palette from three choices: the background's tint, light or dark, and the
   two accents. Surfaces step in lightness from the tint's hue (low saturation, so a
   tint colours the grey rather than painting the screen), text is chosen for
   contrast, and the text ON the accent is whichever of white or ink reads better. */
function tbPalette(tint,mode,acc,acc2){
  const [h,s0]=tbHsl(tint),s=Math.min(s0,.4),dark=mode!=='light';
  const L=dark?[.045,.075,.1,.135,.19,.93,.7,.48]:[.975,.995,.95,.91,.86,.13,.38,.55];
  const S=dark?[s,s,s*.9,s*.85,s*.7,.2,.14,.1]:[s*.5,s*.3,s*.5,s*.5,s*.4,.25,.15,.1];
  const k=['bg','bg2','bg3','bg4','line','txt','dim','dim2'],v={};
  k.forEach((n,i)=>v[n]=tbFromHsl(h,S[i],L[i]));
  const [r,g,b]=tbRgb(v.bg2).map(x=>Math.round(x*255));
  v.glass=`rgba(${r},${g},${b},${dark?.82:.92})`;
  v.acc=acc;v.acc2=acc2;
  v['acc-grad']=`linear-gradient(135deg,${acc} 0%,${acc2} 100%)`;
  v['on-acc']=tbContrast(acc,'#ffffff')>=tbContrast(acc,'#0b0b12')?'#ffffff':'#0b0b12';
  return v;
}
function themeBuilder(from){
  const w=WM.wins.get('themes');if(!w)return;
  const body=w.el.querySelector('.wbody');
  const all=allThemes(),baseId=from||CURRENT_THEME,base=all[baseId]||THEMES.nova;
  const v0={...(base.v||base.vars||{})};
  const WB=window._WB={name:base.custom?(base.label||base.name||baseId):'My Theme',mode:base.mode||'dark',v:v0,css:base.css||'',
    font:base.font?{...base.font}:null,wall_img:base.wall_img||'',from:baseId};
  const cs=getComputedStyle(document.documentElement),tok=k=>(WB.v[k]||cs.getPropertyValue('--'+k)||'').trim();
  const rmd=parseInt(tok('r-md'))||10;
  const depth=WB.v['el-3']==='none'?'flat':(WB.v['el-3']||'').includes('.54')?'deep':(WB.v['el-3']||'').includes('.28')?'soft':'normal';
  const glass=(WB.v['glass-blur']||'').startsWith('none')?'solid':(WB.v['glass-blur']||'').includes('14px')?'clear':'frosted';
  const fsb=parseInt(tok('fs-base'))||14;
  const COLORS=[['bg','Background'],['bg2','Surface'],['bg3','Surface 2'],['bg4','Raised'],['line','Border'],['txt','Text'],['dim','Muted'],['dim2','Faint'],['acc','Accent'],['acc2','Accent 2'],['on-acc','Text on accent'],['warn','Warning'],['err','Error'],['ok','Success']];
  body.innerHTML=`<div class="pad tb">
    <div class="apptop" style="border:none;padding:0 0 10px;gap:8px;flex-wrap:wrap">
      <button class="endbtn" onclick="applyTheme(CURRENT_THEME);refreshApp('themes')">← Back</button>
      <input id="tb-name" value="${esc(WB.name)}" placeholder="theme name" style="flex:1;min-width:140px">
      <select id="tb-from" aria-label="Start from">${Object.entries(all).map(([k,t])=>`<option value="${esc(k)}" ${k===baseId?'selected':''}>start from ${esc(t.label||t.name||k)}</option>`).join('')}</select>
    </div>
    <p class="mut" style="margin:0 0 12px">Build the whole look and feel — the desktop changes live as you edit. Nothing is saved until <b>Save &amp; apply</b>.</p>
    <div class="tb-sec"><b>Colours</b>
      <div class="tb-quick">
        <label>Mode<select id="tb-mode"><option value="dark"${WB.mode==='dark'?' selected':''}>Dark</option><option value="light"${WB.mode==='light'?' selected':''}>Light</option></select></label>
        <label>Background tint<input type="color" id="tb-tint" value="${tbHex(tok('bg3'))}"></label>
        <label>Accent<input type="color" id="tb-acc" value="${tbHex(tok('acc'))}"></label>
        <label>Accent 2<input type="color" id="tb-acc2" value="${tbHex(tok('acc2'))}"></label>
        <button class="pact" onclick="tbGenerate()">Generate palette</button>
      </div>
      <div id="tb-contrast" class="mut tb-note"></div>
      <details class="tb-fine"><summary>Fine-tune every colour</summary>
        <div class="tb-colors">${COLORS.map(([k,lab])=>`<label><input type="color" data-k="${k}" value="${tbHex(tok(k))}"><span>${lab}</span><code id="tb-h-${k}">${esc(tok(k))}</code></label>`).join('')}</div>
      </details></div>
    <div class="tb-sec"><b>Shape</b>
      <label class="tb-slide">Corners <input type="range" id="tb-r" min="0" max="24" step="1" value="${rmd}"><output id="tb-r-o">${rmd}px</output></label></div>
    <div class="tb-sec"><b>Depth</b>
      <div class="seg" id="tb-depth">${['flat','soft','normal','deep'].map(d=>`<button class="${d===depth?'on':''}" data-d="${d}">${d[0].toUpperCase()+d.slice(1)}</button>`).join('')}</div></div>
    <div class="tb-sec"><b>Glass</b>
      <div class="seg" id="tb-glass">${[['solid','Solid'],['frosted','Frosted'],['clear','Clear']].map(([g,l])=>`<button class="${g===glass?'on':''}" data-g="${g}">${l}</button>`).join('')}</div>
      <p class="mut tb-note">Frosted and clear blur what is behind a window — the most expensive thing a desktop draws. Effects (on the Themes page) still turns it down on a machine that cannot keep up.</p></div>
    <div class="tb-sec"><b>Type</b>
      <label>Font<select id="tb-font">${TB_FONTS.map(([f,l])=>`<option value="${esc(f)}" ${((WB.font&&WB.font.family)||'')===f?'selected':''}>${esc(l)}</option>`).join('')}<option value="__custom" ${WB.font&&WB.font.family&&!TB_FONTS.some(x=>x[0]===WB.font.family)?'selected':''}>Another web font…</option></select></label>
      <div id="tb-fcustom" style="display:${WB.font&&WB.font.family&&!TB_FONTS.some(x=>x[0]===WB.font.family)?'flex':'none'};gap:8px;flex-wrap:wrap">
        <input id="tb-furl" value="${esc((WB.font&&WB.font.url)||'')}" placeholder="https://fonts.googleapis.com/css2?family=…" style="flex:2;min-width:200px">
        <input id="tb-ffam" value="${esc((WB.font&&WB.font.family)||'')}" placeholder="family, e.g. Sora" style="flex:1;min-width:120px"></div>
      <label class="tb-slide">Text size <input type="range" id="tb-fs" min="12" max="17" step="1" value="${fsb}"><output id="tb-fs-o">${fsb}px</output></label></div>
    <div class="tb-sec"><b>Wallpaper</b>
      <select id="tb-wall"><option value="">Keep whatever is set</option><option value="__gen" ${WB.css.includes('/*tb:wall*/')?'selected':''}>Made from these colours</option>
        ${(typeof BUILTIN_WALLS!=='undefined'?BUILTIN_WALLS:[]).filter(x=>!x.startsWith('immersive-')).map(x=>`<option value="${esc(x)}" ${WB.wall_img===x?'selected':''}>${esc(x)}</option>`).join('')}</select></div>
    <details class="tb-sec"><summary><b>Advanced CSS</b></summary>
      <p class="mut tb-note">Restyle anything else: .win, #taskbar, #menubar, .aicon, .widget, #desktop.</p>
      <textarea id="tb-css" rows="5" style="font-family:var(--mono);font-size:12px">${esc(WB.css)}</textarea></details>
    <div class="row" style="margin-top:12px;gap:8px;flex-wrap:wrap">
      <button class="save" style="margin:0" onclick="tbSave()">Save &amp; apply</button>
      <button class="endbtn" onclick="tbSave(true)">Export</button>
      <button class="endbtn" onclick="applyTheme(CURRENT_THEME);refreshApp('themes')">Cancel</button>
    </div>
  </div>`;
  const q=s=>body.querySelector(s);
  // _applyThemeObj, not applyThemeObj: a live preview must not start a crossfade per
  // slider step — each one snapshots the screen and paints it over the next frame, so
  // dragging "Corners" left the previous screen showing through every window
  const preview=()=>{_applyThemeObj(WB);tbCheck()};
  body.querySelectorAll('.tb-colors input[type=color]').forEach(inp=>inp.oninput=()=>{WB.v[inp.dataset.k]=inp.value;
    if(inp.dataset.k==='acc'||inp.dataset.k==='acc2')WB.v['acc-grad']=`linear-gradient(135deg,${WB.v.acc||tok('acc')} 0%,${WB.v.acc2||tok('acc2')} 100%)`;
    const h=q('#tb-h-'+inp.dataset.k);if(h)h.textContent=inp.value;preview()});
  q('#tb-from').onchange=e=>themeBuilder(e.target.value);
  q('#tb-mode').onchange=e=>{WB.mode=e.target.value;tbGenerate()};
  ['#tb-tint','#tb-acc','#tb-acc2'].forEach(id=>q(id).oninput=()=>tbGenerate());
  q('#tb-r').oninput=e=>{const r=+e.target.value;Object.assign(WB.v,{'r-sm':Math.round(r*.6)+'px','r-md':r+'px','r-lg':Math.round(r*1.4)+'px','r-xl':Math.round(r*1.9)+'px'});q('#tb-r-o').textContent=r+'px';preview()};
  q('#tb-depth').onclick=e=>{const b=e.target.closest('button');if(!b)return;q('#tb-depth').querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));
    const d=TB_DEPTH[b.dataset.d];['el-2','el-3','el-4','el-5'].forEach((k,i)=>{if(d)WB.v[k]=d[i];else delete WB.v[k]});preview()};
  q('#tb-glass').onclick=e=>{const b=e.target.closest('button');if(!b)return;q('#tb-glass').querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));
    const [blur,pct]=TB_GLASS[b.dataset.g];WB.v['glass-blur']=blur;WB.v['glass-tint']=`color-mix(in srgb,var(--bg2) ${pct}%,transparent)`;preview()};
  q('#tb-font').onchange=e=>{const f=e.target.value;q('#tb-fcustom').style.display=f==='__custom'?'flex':'none';
    if(f==='__custom')return;WB.font=f?{family:f,url:'https://fonts.googleapis.com/css2?family='+encodeURIComponent(f).replace(/%20/g,'+')+':wght@400;500;600;700&display=swap'}:null;preview()};
  q('#tb-furl').oninput=e=>{WB.font=WB.font||{};WB.font.url=e.target.value;preview()};
  q('#tb-ffam').oninput=e=>{WB.font=WB.font||{};WB.font.family=e.target.value;preview()};
  q('#tb-fs').oninput=e=>{const n=+e.target.value;Object.assign(WB.v,{'fs-xs':(n-3)+'px','fs-sm':(n-2)+'px','fs-md':(n-1)+'px','fs-base':n+'px','fs-lg':(n+2)+'px'});q('#tb-fs-o').textContent=n+'px';preview()};
  q('#tb-wall').onchange=e=>{const x=e.target.value;WB.css=WB.css.replace(/\/\*tb:wall\*\/[^\n]*\n?/g,'');WB.wall_img='';
    if(x==='__gen')WB.css='/*tb:wall*/body,#desktop{background:radial-gradient(1100px 700px at 18% -10%,color-mix(in srgb,var(--acc) 45%,transparent),transparent 60%),radial-gradient(900px 650px at 95% 105%,color-mix(in srgb,var(--acc2) 38%,transparent),transparent 60%),var(--bg);background-attachment:fixed}\n'+WB.css;
    else if(x)WB.wall_img=x;
    const tc=q('#tb-css');if(tc)tc.value=WB.css;preview();if(typeof loadWallpaper==='function')loadWallpaper()};
  q('#tb-css').oninput=e=>{WB.css=e.target.value;preview()};
  preview();
}
function tbGenerate(){
  const WB=window._WB,q=s=>document.querySelector(s);if(!WB)return;
  Object.assign(WB.v,tbPalette(q('#tb-tint').value,q('#tb-mode').value,q('#tb-acc').value,q('#tb-acc2').value));
  WB.mode=q('#tb-mode').value;
  document.querySelectorAll('.tb-colors input[type=color]').forEach(i=>{const v=WB.v[i.dataset.k];if(v&&/^#/.test(v)){i.value=tbHex(v);const h=document.getElementById('tb-h-'+i.dataset.k);if(h)h.textContent=v}});
  _applyThemeObj(WB);tbCheck();
}
/* Said, not assumed: whether the text can actually be read. WCAG asks 4.5:1 for body
   text; a palette under it is saved if somebody insists, but never silently. */
function tbCheck(){
  const WB=window._WB,el=document.getElementById('tb-contrast');if(!WB||!el)return;
  const cs=getComputedStyle(document.documentElement),g=k=>tbHex((WB.v[k]||cs.getPropertyValue('--'+k)||'').trim());
  const a=tbContrast(g('txt'),g('bg2')),b=tbContrast(g('on-acc'),g('acc')),c=tbContrast(g('dim'),g('bg2'));
  const mark=x=>x>=4.5?'✓':x>=3?'— low':'✗ too low';
  el.innerHTML=`Text on surfaces ${a.toFixed(1)}:1 ${mark(a)} · muted text ${c.toFixed(1)}:1 ${mark(c)} · text on the accent ${b.toFixed(1)}:1 ${mark(b)}`;
}
async function tbSave(exportOnly){
  const WB=window._WB;if(!WB)return;
  WB.name=(document.getElementById('tb-name')||{}).value?.trim()||'My Theme';
  if(WB.font&&!WB.font.url)WB.font=null;
  const out={name:WB.name,mode:WB.mode,v:WB.v,css:WB.css,font:WB.font||undefined,wall_img:WB.wall_img||undefined};
  if(exportOnly){const blob=new Blob([JSON.stringify(out,null,2)],{type:'application/json'});
    const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=WB.name.replace(/\s+/g,'-')+'.theme.json';a.click();return}
  await themeSave(out,true);await loadThemes();applyTheme(WB.name);toast('saved '+WB.name);refreshApp('themes');
}

/* ================= personalize app + wallpaper gallery ================= */
async function renderPersonalize(body){
  let gal=[];try{gal=(await (await fetch('/api/wallpapers')).json()).wallpapers||[]}catch(e){}
  const picked=pickedWall();
  body.innerHTML=`<div class="pad">
    <label>Built-in wallpapers</label>
    <p class="mut" style="margin:2px 0 8px">Ship with AgentOS, one per design-language theme. They're SVG — a few KB
      each, sharp at any resolution. Pick a theme and its wallpaper follows automatically; choose one here to pin it instead.</p>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px">
      ${BUILTIN_WALLS.map(id=>`<button onclick="pzBuiltin('${id}')" title="${esc(id)}"
        style="position:relative;padding:0;border-radius:9px;overflow:hidden;aspect-ratio:16/9;
          border:2px solid ${id===picked?'var(--acc)':'var(--line)'}">
        <img src="${builtinWallURL(id)}" alt="${esc(id)} wallpaper" style="width:100%;height:100%;object-fit:cover;display:block" loading="lazy">
        <span style="position:absolute;left:0;right:0;bottom:0;padding:3px 7px;text-align:left;font-size:var(--fs-2xs);
          background:linear-gradient(transparent,rgba(0,0,0,.6));color:#fff">${esc(id)}</span>
      </button>`).join('')}
    </div>
    <div class="row" style="margin-top:8px">
      <button class="endbtn" onclick="clearBuiltinWallpaper();refreshApp('personalize')">Follow the theme</button>
    </div>
    <label style="margin-top:18px">Describe your wallpaper</label>
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
    const d=await r.json();
    // a quota/key error is a paragraph, not a toast — show it where it can be read
    if(!d.ok)await osAlert('Image generation failed',String(d.result||'').replace(/^\[error\]\s*/,''));
    else{toast(String(d.result||'generated').replace(/^wallpaper generated with /,'✓ ').slice(0,110));refreshApp('personalize')}
  }catch(e){toast('generation failed — offline?')}
  const b2=$('#pz-gen');if(b2){b2.disabled=false;b2.textContent='Generate wallpaper'}
}
async function pzBuiltin(id){await setBuiltinWallpaper(id);refreshApp('personalize')}
async function pzSet(id){
  localStorage.removeItem('wallpaper.builtin');   // a generated wallpaper replaces the pinned built-in
  await fetch('/api/wallpapers/'+id+'/set',{method:'POST'});toast('applied');
}
async function wpSystem(){const r=await fetch('/api/wallpaper/system',{method:'POST'});const d=await r.json();toast(d.ok?'using your system wallpaper':(d.error||'failed'))}
async function pzDel(id){await fetch('/api/wallpapers/'+id,{method:'DELETE'});refreshApp('personalize')}

